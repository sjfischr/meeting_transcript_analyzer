"""Pydantic models supporting segment-level meeting analysis."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class Segment(BaseModel):
    """Represents a contiguous slice of the meeting transcript with shared context."""

    id: int
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    topic: str
    speakers: List[str]
    text: str


class ActionItem(BaseModel):
    """Tracks a follow-up action derived from the discussion."""

    id: str
    description: str
    owner: Optional[str] = None
    due_date: Optional[str] = None


class QAPair(BaseModel):
    """Captures a question-and-answer exchange within a segment."""

    question: str
    answer: str
    asked_by: Optional[str] = None
    answered_by: Optional[str] = None


class CalendarEvent(BaseModel):
    """Defines a proposed calendar event inferred from the meeting."""

    uid: str
    title: str
    start: str
    end: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None


class SegmentAnalysis(BaseModel):
    """Holds structured insights extracted from a single segment."""

    segment_id: int
    key_points: List[str]
    decisions: List[str]
    action_items: List[ActionItem]
    qa_pairs: List[QAPair]
    calendar_events: List[CalendarEvent]


class MeetingAnalysis(BaseModel):
    """Aggregates per-segment analyses into meeting-wide artifacts."""

    segments: List[Segment]
    segment_analyses: List[SegmentAnalysis]
    all_action_items: List[ActionItem]
    all_qa_pairs: List[QAPair]
    all_calendar_events: List[CalendarEvent]
    executive_summary: str
    detailed_minutes: str
