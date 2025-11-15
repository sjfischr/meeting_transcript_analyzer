"""LangChain segment analysis pipeline using Amazon Bedrock."""

from __future__ import annotations

import logging
import os
import time
import json
from typing import List

from langchain.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from src.common.bedrock_client import BedrockClient
from src.models.segment_analysis import (
    ActionItem,
    CalendarEvent,
    MeetingAnalysis,
    QAPair,
    Segment,
    SegmentAnalysis,
)

logger = logging.getLogger(__name__)


class BedrockLangChainChat(BaseChatModel):
    """Lightweight LangChain chat model that wraps our BedrockClient."""

    client: BedrockClient
    model_id: str

    @property
    def lc_serializable(self) -> bool:  # pragma: no cover - LC internals
        return True

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("Use _generate_with_output_parser instead")

    def invoke(self, input, **kwargs):
        messages = input if isinstance(input, list) else [input]
        system_prompt = messages[0].content if messages and messages[0].type == "system" else ""
        user_prompt = messages[-1].content if messages else ""
        response = self.client.invoke_with_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=kwargs.get("max_tokens", 4000),
        )
        return response


def get_bedrock_chat_model() -> BaseChatModel:
    """Return a LangChain chat model configured for Claude Sonnet on Bedrock."""

    model_id = os.getenv("SEGMENT_ANALYSIS_MODEL_ID", os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"))
    client = BedrockClient()
    return BedrockLangChainChat(client=client, model_id=model_id)


SEGMENT_PROMPT_TEMPLATE = """
You are an expert meeting analyst helping a community club capture rich notes.
Given a single meeting segment, extract actionable insights.

Rules:
- Respond in JSON matching the requested schema.
- Provide concise yet specific bullet lists.
- Only surface information that appears in the segment text.

Segment metadata:
- Segment ID: {segment_id}
- Speakers: {speakers}
- Approximate time range: {start_time} to {end_time}

Segment transcript:
"""


def build_segment_analysis_chain(llm: BaseChatModel) -> Runnable[[Segment], SegmentAnalysis]:
    """Create a chain that converts Segment objects into structured analyses."""

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You analyze a single segment of a meeting transcript."),
        ("user", SEGMENT_PROMPT_TEMPLATE + "{segment_text}")
    ])

    parser = JsonOutputParser(pydantic_object=SegmentAnalysis)

    return prompt | llm | parser  # type: ignore[return-value]


def _format_time(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"


def analyze_segments(segments: List[Segment]) -> List[SegmentAnalysis]:
    """Run the segment analysis chain over all segments sequentially."""

    if not segments:
        return []

    llm = get_bedrock_chat_model()
    chain = build_segment_analysis_chain(llm)

    results: List[SegmentAnalysis] = []
    for segment in segments:
        start = time.time()
        logger.info(
            "Analyzing segment %s (%s to %s)",
            segment.id,
            _format_time(segment.start_time),
            _format_time(segment.end_time),
        )
        result: SegmentAnalysis = chain.invoke(
            {
                "segment_id": segment.id,
                "speakers": ", ".join(segment.speakers),
                "start_time": _format_time(segment.start_time),
                "end_time": _format_time(segment.end_time),
                "segment_text": segment.text,
            }
        )
        results.append(result)
        elapsed = time.time() - start
        logger.info("Segment %s analyzed in %.2fs", segment.id, elapsed)

    return results


SUMMARY_PROMPT_TEMPLATE = """
You are drafting meeting summaries from structured analyses. Use only the provided
facts; do not invent content. Produce:
- executive_summary: concise paragraph covering decisions and key points.
- detailed_minutes: multi-paragraph narrative organized chronologically by segment.

Segment Analyses (JSON):
{analysis_json}
"""


def _build_summary_chain(llm: BaseChatModel) -> Runnable:
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You compose meeting summaries using structured analysis data."
            " Keep tone professional and actionable.",
        ),
        ("user", SUMMARY_PROMPT_TEMPLATE),
    ])

    class SummaryModel(BaseModel):
        executive_summary: str
        detailed_minutes: str

    parser = JsonOutputParser(pydantic_object=SummaryModel)
    return prompt | llm | parser


def aggregate_meeting_analysis(
    segments: List[Segment],
    analyses: List[SegmentAnalysis],
) -> MeetingAnalysis:
    """Combine segments and their analyses into a meeting-wide summary."""

    analysis_by_id = {analysis.segment_id: analysis for analysis in analyses}
    ordered_analyses: List[SegmentAnalysis] = []
    for segment in segments:
        if segment.id not in analysis_by_id:
            raise ValueError(f"Missing analysis for segment {segment.id}")
        ordered_analyses.append(analysis_by_id[segment.id])

    llm = get_bedrock_chat_model()
    summary_chain = _build_summary_chain(llm)
    summary_payload = summary_chain.invoke(
        {
            "analysis_json": json.dumps([analysis.model_dump() for analysis in ordered_analyses], ensure_ascii=False),
        }
    )

    all_action_items: List[ActionItem] = []
    all_qa_pairs: List[QAPair] = []
    all_calendar_events: List[CalendarEvent] = []
    for analysis in ordered_analyses:
        all_action_items.extend(analysis.action_items)
        all_qa_pairs.extend(analysis.qa_pairs)
        all_calendar_events.extend(analysis.calendar_events)

    return MeetingAnalysis(
        segments=segments,
        segment_analyses=ordered_analyses,
        all_action_items=all_action_items,
        all_qa_pairs=all_qa_pairs,
        all_calendar_events=all_calendar_events,
        executive_summary=summary_payload.executive_summary,
        detailed_minutes=summary_payload.detailed_minutes,
    )


def meeting_analysis_to_qa_pairs_json(meeting: MeetingAnalysis) -> dict:
    """Structure data compatible with 02_qa_pairs.json."""

    qa_pairs_payload = []
    for idx, qa in enumerate(meeting.all_qa_pairs, start=1):
        qa_pairs_payload.append(
            {
                "group_id": idx,
                "type": "qa_exchange",
                "topic": qa.question[:120],
                "start_ts": "",
                "end_ts": "",
                "turns": [
                    {
                        "idx": idx * 2 - 1,
                        "role": "question",
                        "speaker": qa.asked_by or "Unknown",
                        "text": qa.question,
                    },
                    {
                        "idx": idx * 2,
                        "role": "answer",
                        "speaker": qa.answered_by or "Unknown",
                        "text": qa.answer,
                    },
                ],
            }
        )

    return {
        "meeting_id": "",  # caller can set
        "qa_pairs": qa_pairs_payload,
    }


def meeting_analysis_to_minutes_json(meeting: MeetingAnalysis) -> dict:
    """Structure data in the spirit of 03_minutes.json."""

    agenda_items = []
    for segment, analysis in zip(meeting.segments, meeting.segment_analyses):
        agenda_items.append(
            {
                "topic": analysis.key_points[0] if analysis.key_points else segment.topic,
                "summary": "\n".join(analysis.key_points),
                "decisions": analysis.decisions,
                "discussion_points": analysis.key_points,
            }
        )

    action_items = []
    for idx, item in enumerate(meeting.all_action_items, start=1):
        action_items.append(
            {
                "id": idx,
                "description": item.description,
                "owner": item.owner,
                "due_date": item.due_date or "TBD",
                "status": "open",
                "priority": "medium",
            }
        )

    return {
        "meeting_id": "",
        "minutes": {
            "meeting_info": {
                "title": "",
                "date": "",
                "start_time": "",
                "end_time": "",
                "attendees": [],
            },
            "agenda_items": agenda_items,
            "action_items": action_items,
            "announcements": [],
            "next_meeting": {
                "date": "TBD",
                "topics": [],
            },
        },
    }


def meeting_analysis_to_summaries_json(meeting: MeetingAnalysis) -> dict:
    """Structure data similar to 04_summaries.json."""

    key_highlights: List[str] = []
    for analysis in meeting.segment_analyses:
        key_highlights.extend(analysis.key_points)

    return {
        "meeting_id": "",
        "summaries": {
            "executive_summary": meeting.executive_summary,
            "detailed_summary": meeting.detailed_minutes,
            "key_highlights": key_highlights,
            "topics_covered": [
                {
                    "topic": segment.topic,
                    "summary": "\n".join(analysis.key_points),
                    "outcome": "; ".join(analysis.decisions),
                }
                for segment, analysis in zip(meeting.segments, meeting.segment_analyses)
            ],
            "sentiment_analysis": {
                "overall_tone": "neutral",
                "energy_level": "medium",
                "concerns_raised": [],
                "positive_developments": [],
            },
        },
    }


def meeting_analysis_to_calendar_events(meeting: MeetingAnalysis) -> List[CalendarEvent]:
    """Return calendar events extracted from the meeting analysis."""

    return meeting.all_calendar_events
