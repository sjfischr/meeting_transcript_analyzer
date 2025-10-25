"""
Type definitions for GRiST meeting pipeline.

Contains all the TypedDict and data class definitions used
throughout the pipeline for type safety and documentation.
"""

from typing import TypedDict, List, Optional, Literal, Union
from datetime import datetime


# Turn types
TurnType = Literal["question", "answer", "followup", "monologue", "housekeeping"]
GroupType = Literal["qa_exchange", "monologue", "discussion", "housekeeping"]
Priority = Literal["high", "medium", "low"]
EventType = Literal["meeting", "deadline", "event", "reminder"]
Sentiment = Literal["positive", "neutral", "negative", "mixed"]
EnergyLevel = Literal["high", "medium", "low"]


class Turn(TypedDict):
    """Individual turn in a meeting transcript."""
    idx: int
    start_ts: str  # HH:MM:SS format
    end_ts: str    # HH:MM:SS format
    speaker: str
    type: TurnType
    question_likelihood: float  # 0.0 to 1.0
    text: str


class TurnsOutput(TypedDict):
    """Output from the turns processing step."""
    meeting_id: str
    time_zone: str
    turns: List[Turn]


class QATurn(TypedDict):
    """Turn within a Q&A group."""
    idx: int  # Original turn index
    role: Literal["question", "answer", "followup", "context"]
    speaker: str
    text: str


class QAGroup(TypedDict):
    """Grouped Q&A exchange."""
    group_id: int
    type: GroupType
    topic: str
    start_ts: str
    end_ts: str
    turns: List[QATurn]


class QAPairsOutput(TypedDict):
    """Output from the Q&A grouping step."""
    meeting_id: str
    qa_pairs: List[QAGroup]


class MeetingInfo(TypedDict):
    """Basic meeting information."""
    title: str
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str    # HH:MM
    attendees: List[str]


class AgendaItem(TypedDict):
    """Agenda item with discussion summary."""
    topic: str
    summary: str
    decisions: List[str]
    discussion_points: List[str]


class ActionItem(TypedDict):
    """Action item from the meeting."""
    id: int
    description: str
    owner: Optional[str]
    due_date: str  # YYYY-MM-DD or 'TBD'
    status: Literal["open", "in_progress", "completed", "cancelled"]
    priority: Priority


class NextMeeting(TypedDict):
    """Information about the next scheduled meeting."""
    date: str  # YYYY-MM-DD or 'TBD'
    topics: List[str]


class Minutes(TypedDict):
    """Complete meeting minutes."""
    meeting_info: MeetingInfo
    agenda_items: List[AgendaItem]
    action_items: List[ActionItem]
    announcements: List[str]
    next_meeting: NextMeeting


class MinutesOutput(TypedDict):
    """Output from the minutes generation step."""
    meeting_id: str
    minutes: Minutes


class TopicSummary(TypedDict):
    """Summary of a specific topic discussed."""
    topic: str
    summary: str
    outcome: Optional[str]


class SentimentAnalysis(TypedDict):
    """Sentiment analysis of the meeting."""
    overall_tone: Sentiment
    energy_level: EnergyLevel
    concerns_raised: List[str]
    positive_developments: List[str]


class Summaries(TypedDict):
    """Multiple types of meeting summaries."""
    executive_summary: str
    detailed_summary: str
    key_highlights: List[str]
    topics_covered: List[TopicSummary]
    sentiment_analysis: SentimentAnalysis


class SummariesOutput(TypedDict):
    """Output from the summaries generation step."""
    meeting_id: str
    summaries: Summaries


class EventReminder(TypedDict):
    """Reminder configuration for calendar events."""
    minutes_before: int
    method: Literal["email", "popup"]


class EventRecurrence(TypedDict):
    """Recurrence pattern for calendar events."""
    frequency: Literal["weekly", "monthly", "yearly", "none"]
    interval: Optional[int]
    end_date: Optional[str]  # YYYY-MM-DD


class CalendarEvent(TypedDict):
    """Calendar event extracted from meeting."""
    event_id: str
    type: EventType
    title: str
    description: str
    start_datetime: str  # ISO 8601 format
    end_datetime: str    # ISO 8601 format
    all_day: bool
    location: Optional[str]
    attendees: List[str]
    reminders: List[EventReminder]
    recurrence: EventRecurrence
    source_context: str


class CalendarOutput(TypedDict):
    """Output from the calendar generation step."""
    meeting_id: str
    calendar_events: List[CalendarEvent]


class ProcessingInfo(TypedDict):
    """Information about the processing pipeline run."""
    start_time: str  # ISO 8601 datetime
    end_time: str    # ISO 8601 datetime
    total_duration_seconds: int
    pipeline_version: str
    processing_status: Literal["completed", "failed", "partial"]


class SourceInfo(TypedDict):
    """Information about the source transcript."""
    transcript_file: str
    file_size_bytes: int
    transcript_length: str  # HH:MM:SS
    estimated_speakers: int
    language: str


class ArtifactInfo(TypedDict):
    """Information about a generated artifact."""
    filename: str
    type: Literal["turns", "qa_pairs", "minutes", "summaries", "calendar", "manifest"]
    size_bytes: int
    record_count: int
    validation_status: Literal["valid", "invalid", "warning"]
    quality_score: float  # 0.0 to 1.0
    generation_time_seconds: int
    dependencies: List[str]
    schema_version: str


class QualityMetrics(TypedDict):
    """Quality assessment of the processing."""
    transcript_clarity: float      # 0.0 to 1.0
    speaker_identification: float  # 0.0 to 1.0
    timestamp_accuracy: float      # 0.0 to 1.0
    content_completeness: float    # 0.0 to 1.0


class Manifest(TypedDict):
    """Complete processing manifest."""
    processing_info: ProcessingInfo
    source_info: SourceInfo
    artifacts: List[ArtifactInfo]
    quality_metrics: QualityMetrics
    warnings: List[str]
    next_steps: List[str]


class ManifestOutput(TypedDict):
    """Output from the manifest generation step."""
    meeting_id: str
    manifest: Manifest


# Lambda event types
class LambdaEvent(TypedDict):
    """Base Lambda event structure."""
    meeting_id: str
    input_key: str
    output_key: str


class StepFunctionInput(TypedDict):
    """Input to the Step Functions state machine."""
    meeting_id: str
    transcript_key: str
    output_prefix: str