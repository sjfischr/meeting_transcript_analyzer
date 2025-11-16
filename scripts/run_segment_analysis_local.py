"""Local runner for segment-based meeting analysis.

Usage:
    python scripts/run_segment_analysis_local.py path/to/transcript.(txt|json)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

# Ensure repo root is on sys.path for `src` imports when executed directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ics import Calendar, Event  # type: ignore

from src.common.segmenter import create_segments_from_turns, turns_to_segments_for_testing
from src.common.segment_analysis_chain import (
    aggregate_meeting_analysis,
    analyze_segments,
    meeting_analysis_to_calendar_events,
    meeting_analysis_to_minutes_json,
    meeting_analysis_to_qa_pairs_json,
    meeting_analysis_to_summaries_json,
)
from src.models.segment_analysis import Segment
from src.models.types import Turn

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path, help="Path to transcript .txt or 01_turns.json file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory (defaults to <input>/segment_analysis_output)",
    )
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="Use heuristic offline model instead of calling Bedrock",
    )
    return parser.parse_args()


def _seconds_to_ts(value: Optional[float]) -> str:
    if value is None or value < 0:
        return "00:00:00"
    seconds = float(value)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".rstrip("0").rstrip(".")


def _parse_turns_payload(turns_data: Iterable[Dict]) -> List[Turn]:
    turns: List[Turn] = []
    for raw in turns_data:
        if not isinstance(raw, dict):
            raise ValueError("Turn entries must be objects")
        turn: Turn = {
            "idx": raw.get("idx", len(turns)),
            "start_ts": raw.get("start_ts", "00:00:00"),
            "end_ts": raw.get("end_ts", "00:00:00"),
            "speaker": raw.get("speaker", "Unknown"),
            "type": raw.get("type", "monologue"),
            "question_likelihood": float(raw.get("question_likelihood", 0.0)),
            "text": raw.get("text", ""),
        }
        turns.append(turn)
    return turns


def _build_turn(
    idx: int,
    speaker: str,
    tokens: List[str],
    start_sec: Optional[float],
    end_sec: Optional[float],
) -> Turn:
    text = "".join(tokens).strip()
    question = 1.0 if text.endswith("?") else 0.0
    turn_type = "question" if question else "monologue"
    return {
        "idx": idx,
        "start_ts": _seconds_to_ts(start_sec),
        "end_ts": _seconds_to_ts(end_sec),
        "speaker": speaker or "Unknown",
        "type": turn_type,
        "question_likelihood": question,
        "text": text,
    }


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_turns_from_items_sequence(items: Sequence[Dict], start_idx: int = 0) -> List[Turn]:
    turns: List[Turn] = []
    current_speaker: Optional[str] = None
    current_tokens: List[str] = []
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    idx = start_idx

    def flush() -> None:
        nonlocal idx, current_tokens, start_sec, end_sec, current_speaker
        if current_tokens and current_speaker is not None:
            turns.append(_build_turn(idx, current_speaker, current_tokens, start_sec, end_sec))
            idx += 1
        current_tokens = []
        start_sec = None
        end_sec = None
        current_speaker = None

    for item in items:
        speaker = item.get("speaker_label", current_speaker)
        item_type = item.get("type")
        alt = item.get("alternatives", [{}])
        content = alt[0].get("content", "")

        if speaker != current_speaker and current_tokens:
            flush()

        if current_speaker is None:
            current_speaker = speaker or "Unknown"

        if item_type == "pronunciation":
            if current_tokens:
                current_tokens.append(" ")
            current_tokens.append(content)
            word_start = _safe_float(item.get("start_time"))
            word_end = _safe_float(item.get("end_time"))
            if start_sec is None:
                start_sec = word_start
            if word_end is not None:
                end_sec = word_end
        elif item_type == "punctuation":
            if current_tokens:
                current_tokens.append(content)

    flush()
    return turns


def _load_turns_from_transcribe(data: Dict) -> List[Turn]:
    results = data.get("results", {})
    items = results.get("items", [])
    if not items:
        raise ValueError("Transcribe payload missing results.items content")

    segments_meta = results.get("speaker_labels", {}).get("segments", [])
    if segments_meta:
        segment_ranges = []
        for idx, segment in enumerate(segments_meta):
            start = _safe_float(segment.get("start_time")) or 0.0
            end = _safe_float(segment.get("end_time"))
            if end is None:
                end = start
            segment_ranges.append(
                {
                    "index": idx,
                    "start": start,
                    "end": end,
                    "speaker": segment.get("speaker_label", "Unknown"),
                }
            )

        turns: List[Turn] = []
        current_speaker: Optional[str] = None
        current_segment_idx: Optional[int] = None
        current_tokens: List[str] = []
        start_sec: Optional[float] = None
        end_sec: Optional[float] = None
        idx = 0
        seg_pointer = 0
        tolerance = 1e-3

        def flush() -> None:
            nonlocal idx, current_tokens, start_sec, end_sec, current_speaker, current_segment_idx
            if current_tokens and current_speaker is not None:
                turns.append(_build_turn(idx, current_speaker, current_tokens, start_sec, end_sec))
                idx += 1
            current_tokens = []
            start_sec = None
            end_sec = None
            current_speaker = None
            current_segment_idx = None

        def assign_segment(time_value: Optional[float], fallback_idx: Optional[int]) -> Optional[int]:
            nonlocal seg_pointer
            if not segment_ranges:
                return fallback_idx

            if time_value is None:
                return fallback_idx

            # advance pointer if the item occurs after the current segment
            while seg_pointer + 1 < len(segment_ranges) and time_value >= segment_ranges[seg_pointer + 1]["start"] - tolerance:
                seg_pointer += 1

            # ensure we are within the selected segment bounds; move forward if necessary
            while seg_pointer < len(segment_ranges) and time_value > segment_ranges[seg_pointer]["end"] + tolerance:
                if seg_pointer + 1 < len(segment_ranges):
                    seg_pointer += 1
                else:
                    break

            return seg_pointer

        for item in items:
            item_type = item.get("type")
            alt = item.get("alternatives", [{}])
            content = alt[0].get("content", "")

            item_time = _safe_float(item.get("start_time"))
            if item_time is None:
                item_time = _safe_float(item.get("end_time"))

            assigned_idx = assign_segment(item_time, current_segment_idx)
            assigned_segment = segment_ranges[assigned_idx] if assigned_idx is not None else None
            speaker = assigned_segment["speaker"] if assigned_segment else item.get("speaker_label")

            if speaker is None:
                speaker = current_speaker or "Unknown"

            if (
                current_tokens
                and (speaker != current_speaker or assigned_idx != current_segment_idx)
            ):
                flush()

            if current_speaker is None:
                current_speaker = speaker or "Unknown"
                current_segment_idx = assigned_idx
            else:
                current_segment_idx = assigned_idx
                if current_speaker is None:
                    current_speaker = speaker or "Unknown"

            if item_type == "pronunciation":
                if current_tokens:
                    current_tokens.append(" ")
                current_tokens.append(content)
                word_start = _safe_float(item.get("start_time"))
                word_end = _safe_float(item.get("end_time"))
                if start_sec is None:
                    start_sec = word_start
                if word_end is not None:
                    end_sec = word_end
            elif item_type == "punctuation":
                if current_tokens:
                    current_tokens.append(content)

        flush()

        if len(turns) == 0:
            # fallback if segments did not yield tokens (e.g., unexpected format)
            return _build_turns_from_items_sequence(items)

        return turns

    return _build_turns_from_items_sequence(items)


def load_turns_from_json(path: Path) -> List[Turn]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "results" in data and "items" in data["results"]:
        return _load_turns_from_transcribe(data)
    if isinstance(data, dict) and "turns" in data:
        return _parse_turns_payload(data["turns"])
    if isinstance(data, list):
        return _parse_turns_payload(data)
    raise ValueError(f"Unsupported JSON structure in {path}")


def load_segments(input_path: Path) -> List[Segment]:
    if input_path.suffix.lower() == ".json":
        turns = load_turns_from_json(input_path)
        return create_segments_from_turns(turns)

    if input_path.suffix.lower() == ".txt":
        text = input_path.read_text(encoding="utf-8")
        return turns_to_segments_for_testing(text)

    raise ValueError("Input must be a .txt transcript or 01_turns.json file")


def serialize_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def serialize_ics(path: Path, calendar_events) -> None:
    calendar = Calendar()
    for event in calendar_events:
        cal_event = Event()
        cal_event.uid = event.uid
        cal_event.name = event.title
        cal_event.begin = event.start
        if event.end:
            cal_event.end = event.end
        if event.location:
            cal_event.location = event.location
        if event.description:
            cal_event.description = event.description
        calendar.events.add(cal_event)

    path.write_text(str(calendar), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    args = parse_args()

    if args.mock_llm:
        os.environ.setdefault("MOCK_BEDROCK", "1")

    input_path = args.input_path.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_dir = (args.output_dir or input_path.parent / "segment_analysis_output").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    meeting_id = input_path.stem

    logger.info("Loading segments from %s", input_path)
    segments = load_segments(input_path)
    logger.info("%d segments prepared", len(segments))

    analyses = analyze_segments(segments)
    meeting = aggregate_meeting_analysis(segments, analyses)

    qa_json = meeting_analysis_to_qa_pairs_json(meeting)
    minutes_json = meeting_analysis_to_minutes_json(meeting)
    summaries_json = meeting_analysis_to_summaries_json(meeting)
    calendar_events = meeting_analysis_to_calendar_events(meeting)

    for payload in (qa_json, minutes_json, summaries_json):
        payload["meeting_id"] = meeting_id

    if "minutes" in minutes_json:
        minutes_info = minutes_json["minutes"]["meeting_info"]
        minutes_info["title"] = meeting_id

    serialize_json(output_dir / "02_qa_pairs.json", qa_json)
    serialize_json(output_dir / "03_minutes.json", minutes_json)
    serialize_json(output_dir / "04_summaries.json", summaries_json)
    serialize_ics(output_dir / "05_events.ics", calendar_events)

    logger.info(
        "Segments: %d, Action Items: %d, Calendar Events: %d",
        len(segments),
        len(meeting.all_action_items),
        len(calendar_events),
    )
    logger.info("Outputs written to %s", output_dir)


if __name__ == "__main__":
    main()
