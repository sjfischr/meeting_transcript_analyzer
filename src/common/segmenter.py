"""Utilities for partitioning merged meeting turns into analysis segments."""

from __future__ import annotations

from typing import Iterable, List

from src.models.segment_analysis import Segment
from src.models.types import Turn


try:
    from count_tokens import count_tokens as _count_tokens  # type: ignore
except ImportError:  # pragma: no cover - fallback for packages without count_tokens module
    _count_tokens = None


def _estimate_token_count(text: str) -> int:
    """Approximate token count using the same logic as count_tokens.py when available."""

    if not text:
        return 0

    if _count_tokens is not None:
        try:
            return _count_tokens(text)
        except Exception:
            pass

    # Fallback heuristic (≈4 chars/token) if precise tokenizer is unavailable.
    return max(1, len(text) // 4)


def _collect_segment_speakers(turns: Iterable[Turn]) -> List[str]:
    """Collect unique speakers in preserved order from a sequence of turns."""
    seen = set()
    speakers: List[str] = []
    for turn in turns:
        speaker = turn.get("speaker", "Unknown")
        if speaker not in seen:
            seen.add(speaker)
            speakers.append(speaker)
    return speakers


def create_segments_from_turns(
    turns: List[Turn],
    max_tokens_per_segment: int = 3000,
) -> List[Segment]:
    """Group consecutive turns into segments limited by approximate token count.

    Segment identifiers start at 1 for readability. The topic is a placeholder
    that can later be enriched with LLM inference.
    """

    if not turns:
        return []

    segments: List[Segment] = []
    current_turns: List[Turn] = []
    current_tokens = 0

    for turn in turns:
        turn_tokens = _estimate_token_count(turn.get("text", ""))

        if current_turns and current_tokens + turn_tokens > max_tokens_per_segment:
            segments.append(_build_segment(len(segments) + 1, current_turns))
            current_turns = []
            current_tokens = 0

        current_turns.append(turn)
        current_tokens += turn_tokens

    if current_turns:
        segments.append(_build_segment(len(segments) + 1, current_turns))

    return segments


def _build_segment(segment_id: int, turns: List[Turn]) -> Segment:
    """Construct a Segment model from a list of turns."""

    first_turn = turns[0]
    last_turn = turns[-1]

    def _to_seconds(ts: str) -> float | None:
        if not ts:
            return None
        parts = ts.split(":")
        if len(parts) != 3:
            return None
        try:
            hours, minutes, seconds = map(float, parts)
            return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            return None

    start_time = _to_seconds(first_turn.get("start_ts", ""))
    end_time = _to_seconds(last_turn.get("end_ts", ""))

    speakers = _collect_segment_speakers(turns)
    text = "\n".join(turn.get("text", "") for turn in turns)

    return Segment(
        id=segment_id,
        start_time=start_time,
        end_time=end_time,
        topic=f"Segment {segment_id}",
        speakers=speakers,
        text=text,
    )


def turns_to_segments_for_testing(raw_transcript_text: str) -> List[Segment]:
    """Wrap raw transcript text in a single Segment for local testing."""

    turn: Turn = {
        "idx": 0,
        "start_ts": "00:00:00",
        "end_ts": "00:00:00",
        "speaker": "Tester",
        "type": "monologue",
        "question_likelihood": 0.0,
        "text": raw_transcript_text,
    }
    return create_segments_from_turns([turn], max_tokens_per_segment=10_000)
