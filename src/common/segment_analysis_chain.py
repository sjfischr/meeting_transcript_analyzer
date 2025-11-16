"""LangChain segment analysis pipeline using Amazon Bedrock."""

from __future__ import annotations

import logging
import os
import time
import json
import re
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


def _mock_mode_enabled() -> bool:
    """Return True when mock processing should replace Bedrock interactions."""

    flag = os.getenv("MOCK_BEDROCK") or os.getenv("USE_MOCK_BEDROCK")
    return bool(flag and flag.lower() not in {"0", "false", "no"})


class BedrockLangChainChat(BaseChatModel):
    """Lightweight LangChain chat model that wraps our BedrockClient."""

    client: BedrockClient
    model_id: str

    @property
    def lc_serializable(self) -> bool:  # pragma: no cover - LC internals
        return True

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LC internals
        return "bedrock-langchain-chat"

    @property
    def _identifying_params(self) -> dict:  # pragma: no cover - LC internals
        return {"model_id": self.model_id}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("Use _generate_with_output_parser instead")

    def invoke(self, input, config=None, **kwargs):
        if hasattr(input, "to_messages"):
            messages = input.to_messages()
        elif isinstance(input, list):
            messages = input
        else:
            messages = [input]

        system_prompt = ""
        if messages:
            first = messages[0]
            if getattr(first, "type", None) == "system":
                system_prompt = first.content

        user_prompt = messages[-1].content if messages else ""
        response = self.client.invoke_with_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=kwargs.get("max_tokens", 4000),
        )
        return json.dumps(response)


def get_bedrock_chat_model() -> BaseChatModel:
    """Return a LangChain chat model configured for Claude Sonnet on Bedrock."""

    model_id = os.getenv(
        "SEGMENT_ANALYSIS_MODEL_ID",
        os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    )
    client = BedrockClient()
    return BedrockLangChainChat(client=client, model_id=model_id)


SEGMENT_PROMPT_TEMPLATE = """
You are an expert meeting analyst helping a community club capture rich notes.
Given a single meeting segment, extract actionable insights.

{format_instructions}

Precision rules:
- Key points: include every material discussion outcome as 1-2 sentence bullets (target 5-8 when content allows).
- Decisions: enumerate each explicit or implied decision with the rationale or next step folded in.
- Action items: capture all commitments; assign IDs sequentially as "{segment_id}-A1", "{segment_id}-A2", etc.; specify owner if named (else "Unassigned") and set due_date to "TBD" when absent.
- QA pairs: list every direct question posed in the segment; answers must be 2-3 sentences summarizing the response and citing any follow-up requirements or responsible parties.
- Calendar events: include events with clear title, timing, and description; leave fields empty only when not provided in the transcript.
- Do not invent facts—only use information present in the segment.

Segment metadata:
- Segment ID: {segment_id}
- Speakers: {speakers}
- Approximate time range: {start_time} to {end_time}

Segment transcript:
"""


def build_segment_analysis_chain(llm: BaseChatModel) -> Runnable[[Segment], SegmentAnalysis]:
    """Create a chain that converts Segment objects into structured analyses."""

    parser = JsonOutputParser(pydantic_object=SegmentAnalysis)

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You analyze a single segment of a meeting transcript."),
        ("user", SEGMENT_PROMPT_TEMPLATE + "{segment_text}")
    ]).partial(format_instructions=parser.get_format_instructions())

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

    if _mock_mode_enabled():
        return [_mock_analyze_segment(segment) for segment in segments]

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
        raw_result = chain.invoke(
            {
                "segment_id": segment.id,
                "speakers": ", ".join(segment.speakers),
                "start_time": _format_time(segment.start_time),
                "end_time": _format_time(segment.end_time),
                "segment_text": segment.text,
            }
        )
        if isinstance(raw_result, dict):
            result = SegmentAnalysis.model_validate(raw_result)
        else:
            result = raw_result
        results.append(result)
        elapsed = time.time() - start
        logger.info("Segment %s analyzed in %.2fs", segment.id, elapsed)

    return results


SUMMARY_PROMPT_TEMPLATE = """
You are drafting meeting summaries from structured analyses. Use only the provided
facts; do not invent content. Produce the specified JSON fields.

- executive_summary: write two dense paragraphs that surface major themes, decisions, and follow-up responsibilities across all segments.
- detailed_minutes: generate a multi-paragraph chronological narrative; dedicate at least one sentence per segment highlighting key points, decisions, and action owners.

{format_instructions}

Segment Analyses (JSON):
{analysis_json}
"""


def _build_summary_chain(llm: BaseChatModel) -> Runnable:
    class SummaryModel(BaseModel):
        executive_summary: str
        detailed_minutes: str

    parser = JsonOutputParser(pydantic_object=SummaryModel)
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You compose meeting summaries using structured analysis data."
            " Keep tone professional and actionable.",
        ),
        ("user", SUMMARY_PROMPT_TEMPLATE),
    ]).partial(format_instructions=parser.get_format_instructions())
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

    if _mock_mode_enabled():
        summary_payload = _mock_summary_from_analyses(segments, ordered_analyses)
        executive_summary = summary_payload.executive_summary
        detailed_minutes = summary_payload.detailed_minutes
    else:
        llm = get_bedrock_chat_model()
        summary_chain = _build_summary_chain(llm)
        summary_payload = summary_chain.invoke(
            {
                "analysis_json": json.dumps([analysis.model_dump() for analysis in ordered_analyses], ensure_ascii=False),
            }
        )

        if isinstance(summary_payload, dict):
            executive_summary = summary_payload.get("executive_summary", "")
            detailed_minutes = summary_payload.get("detailed_minutes", "")
        else:
            executive_summary = summary_payload.executive_summary
            detailed_minutes = summary_payload.detailed_minutes

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
    executive_summary=executive_summary,
    detailed_minutes=detailed_minutes,
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


def _mock_analyze_segment(segment: Segment) -> SegmentAnalysis:
    """Generate lightweight heuristic analysis for offline testing."""

    text = segment.text.strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    key_points = sentences[:3] if sentences else [text[:120]] if text else []

    lowered = text.lower()
    decisions: List[str] = []
    if any(token in lowered for token in ["decide", "decided", "agreed", "approve", "approved"]):
        decisions.append("Group reached a decision noted in the transcript excerpt.")

    action_items: List[ActionItem] = []
    if any(token in lowered for token in ["action", "follow up", "todo", "task", "next steps"]):
        action_items.append(
            ActionItem(
                id=f"{segment.id}-A1",
                description="Follow up on the discussed action item.",
                owner=segment.speakers[0] if segment.speakers else None,
                due_date=None,
            )
        )

    qa_pairs: List[QAPair] = []
    for sentence in sentences:
        if "?" in sentence:
            qa_pairs.append(
                QAPair(
                    question=sentence,
                    answer="Response captured in meeting notes.",
                    asked_by=segment.speakers[0] if segment.speakers else None,
                    answered_by=segment.speakers[1] if len(segment.speakers) > 1 else None,
                )
            )
            break

    return SegmentAnalysis(
        segment_id=segment.id,
        key_points=key_points,
        decisions=decisions,
        action_items=action_items,
        qa_pairs=qa_pairs,
        calendar_events=[],
    )


def _mock_summary_from_analyses(
    segments: List[Segment],
    analyses: List[SegmentAnalysis],
):
    """Build a deterministic summary payload when Bedrock is unavailable."""

    topics = [segment.topic for segment in segments if segment.topic]
    highlights: List[str] = []
    for analysis in analyses:
        highlights.extend(analysis.key_points)

    executive_parts = [
        "Offline mock summary generated without Bedrock.",
        f"Covered topics: {', '.join(topics)}" if topics else "Topics referenced in transcript segments.",
    ]
    executive_summary = " ".join(executive_parts)

    detailed_lines: List[str] = []
    for segment, analysis in zip(segments, analyses):
        header = f"Segment {segment.id} ({', '.join(segment.speakers)})"
        detailed_lines.append(header.strip())
        detailed_lines.extend(analysis.key_points)
        if analysis.decisions:
            detailed_lines.append("Decisions: " + "; ".join(analysis.decisions))
        if analysis.action_items:
            descriptions = [item.description for item in analysis.action_items]
            detailed_lines.append("Action Items: " + "; ".join(descriptions))

    detailed_minutes = "\n".join(detailed_lines)

    class _SummaryPayload(BaseModel):
        executive_summary: str
        detailed_minutes: str

    return _SummaryPayload(executive_summary=executive_summary, detailed_minutes=detailed_minutes)
