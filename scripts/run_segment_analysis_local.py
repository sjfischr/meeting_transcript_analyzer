"""Local runner for segment-based meeting analysis.

Usage:
    python scripts/run_segment_analysis_local.py path/to/transcript.(txt|json)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

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
    return parser.parse_args()


def load_turns_from_json(path: Path) -> List[Turn]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "turns" in data:
        turns_data = data["turns"]
    elif isinstance(data, list):
        turns_data = data
    else:
        raise ValueError(f"Unsupported JSON structure in {path}")

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
            "question_likelihood": raw.get("question_likelihood", 0.0),
            "text": raw.get("text", ""),
        }
        turns.append(turn)
    return turns


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
