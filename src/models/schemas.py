"""
JSON schemas for validation in GRiST meeting pipeline.

Contains JSON Schema definitions for validating the structure
and content of all pipeline inputs and outputs.
"""

from typing import Dict, Any


# Turns schema
TURNS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["meeting_id", "time_zone", "turns"],
    "properties": {
        "meeting_id": {"type": "string"},
        "time_zone": {"type": "string"},
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["idx", "start_ts", "end_ts", "speaker", "type", "question_likelihood", "text"],
                "properties": {
                    "idx": {"type": "integer", "minimum": 0},
                    "start_ts": {"type": "string", "pattern": r"^\d{2}:\d{2}:\d{2}$"},
                    "end_ts": {"type": "string", "pattern": r"^\d{2}:\d{2}:\d{2}$"},
                    "speaker": {"type": "string"},
                    "type": {"type": "string", "enum": ["question", "answer", "followup", "monologue", "housekeeping"]},
                    "question_likelihood": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "text": {"type": "string"}
                }
            }
        }
    }
}


# Q&A pairs schema  
QA_PAIRS_SCHEMA: Dict[str, Any] = {
    "type": "object", 
    "required": ["meeting_id", "qa_pairs"],
    "properties": {
        "meeting_id": {"type": "string"},
        "qa_pairs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["group_id", "type", "topic", "start_ts", "end_ts", "turns"],
                "properties": {
                    "group_id": {"type": "integer"},
                    "type": {"type": "string", "enum": ["qa_exchange", "monologue", "discussion", "housekeeping"]},
                    "topic": {"type": "string"},
                    "start_ts": {"type": "string", "pattern": r"^\d{2}:\d{2}:\d{2}$"},
                    "end_ts": {"type": "string", "pattern": r"^\d{2}:\d{2}:\d{2}$"},
                    "turns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["idx", "role", "speaker", "text"],
                            "properties": {
                                "idx": {"type": "integer"},
                                "role": {"type": "string", "enum": ["question", "answer", "followup", "context"]},
                                "speaker": {"type": "string"},
                                "text": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
    }
}


# Minutes schema
MINUTES_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["meeting_id", "minutes"],
    "properties": {
        "meeting_id": {"type": "string"},
        "minutes": {
            "type": "object",
            "required": ["meeting_info", "agenda_items", "action_items", "announcements", "next_meeting"],
            "properties": {
                "meeting_info": {
                    "type": "object",
                    "required": ["title", "date", "start_time", "end_time", "attendees"],
                    "properties": {
                        "title": {"type": "string"},
                        "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                        "start_time": {"type": "string", "pattern": r"^\d{2}:\d{2}$"},
                        "end_time": {"type": "string", "pattern": r"^\d{2}:\d{2}$"},
                        "attendees": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "agenda_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["topic", "summary", "decisions", "discussion_points"],
                        "properties": {
                            "topic": {"type": "string"},
                            "summary": {"type": "string"},
                            "decisions": {"type": "array", "items": {"type": "string"}},
                            "discussion_points": {"type": "array", "items": {"type": "string"}}
                        }
                    }
                },
                "action_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "description", "owner", "due_date", "status", "priority"],
                        "properties": {
                            "id": {"type": "integer"},
                            "description": {"type": "string"},
                            "owner": {"type": ["string", "null"]},
                            "due_date": {"type": "string"},
                            "status": {"type": "string", "enum": ["open", "in_progress", "completed", "cancelled"]},
                            "priority": {"type": "string", "enum": ["high", "medium", "low"]}
                        }
                    }
                },
                "announcements": {"type": "array", "items": {"type": "string"}},
                "next_meeting": {
                    "type": "object",
                    "required": ["date", "topics"],
                    "properties": {
                        "date": {"type": "string"},
                        "topics": {"type": "array", "items": {"type": "string"}}
                    }
                }
            }
        }
    }
}


# Summaries schema
SUMMARIES_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["meeting_id", "summaries"],
    "properties": {
        "meeting_id": {"type": "string"},
        "summaries": {
            "type": "object",
            "required": ["executive_summary", "detailed_summary", "key_highlights", "topics_covered", "sentiment_analysis"],
            "properties": {
                "executive_summary": {"type": "string"},
                "detailed_summary": {"type": "string"},
                "key_highlights": {"type": "array", "items": {"type": "string"}},
                "topics_covered": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["topic", "summary", "outcome"],
                        "properties": {
                            "topic": {"type": "string"},
                            "summary": {"type": "string"},
                            "outcome": {"type": ["string", "null"]}
                        }
                    }
                },
                "sentiment_analysis": {
                    "type": "object",
                    "required": ["overall_tone", "energy_level", "concerns_raised", "positive_developments"],
                    "properties": {
                        "overall_tone": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
                        "energy_level": {"type": "string", "enum": ["high", "medium", "low"]},
                        "concerns_raised": {"type": "array", "items": {"type": "string"}},
                        "positive_developments": {"type": "array", "items": {"type": "string"}}
                    }
                }
            }
        }
    }
}


# Calendar events schema  
CALENDAR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["meeting_id", "calendar_events"],
    "properties": {
        "meeting_id": {"type": "string"},
        "calendar_events": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["event_id", "type", "title", "description", "start_datetime", "end_datetime", "all_day"],
                "properties": {
                    "event_id": {"type": "string"},
                    "type": {"type": "string", "enum": ["meeting", "deadline", "event", "reminder"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "start_datetime": {"type": "string"},
                    "end_datetime": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "location": {"type": ["string", "null"]},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "reminders": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["minutes_before", "method"],
                            "properties": {
                                "minutes_before": {"type": "integer"},
                                "method": {"type": "string", "enum": ["email", "popup"]}
                            }
                        }
                    },
                    "recurrence": {
                        "type": "object",
                        "required": ["frequency"],
                        "properties": {
                            "frequency": {"type": "string", "enum": ["weekly", "monthly", "yearly", "none"]},
                            "interval": {"type": ["integer", "null"]},
                            "end_date": {"type": ["string", "null"]}
                        }
                    },
                    "source_context": {"type": "string"}
                }
            }
        }
    }
}


# Manifest schema
MANIFEST_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["meeting_id", "manifest"],
    "properties": {
        "meeting_id": {"type": "string"},
        "manifest": {
            "type": "object",
            "required": ["processing_info", "source_info", "artifacts", "quality_metrics", "warnings", "next_steps"],
            "properties": {
                "processing_info": {
                    "type": "object",
                    "required": ["start_time", "end_time", "total_duration_seconds", "pipeline_version", "processing_status"],
                    "properties": {
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "total_duration_seconds": {"type": "integer"},
                        "pipeline_version": {"type": "string"},
                        "processing_status": {"type": "string", "enum": ["completed", "failed", "partial"]}
                    }
                },
                "source_info": {
                    "type": "object",
                    "required": ["transcript_file", "file_size_bytes", "transcript_length", "estimated_speakers", "language"],
                    "properties": {
                        "transcript_file": {"type": "string"},
                        "file_size_bytes": {"type": "integer"},
                        "transcript_length": {"type": "string"},
                        "estimated_speakers": {"type": "integer"},
                        "language": {"type": "string"}
                    }
                },
                "artifacts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["filename", "type", "size_bytes", "record_count", "validation_status", "quality_score"],
                        "properties": {
                            "filename": {"type": "string"},
                            "type": {"type": "string", "enum": ["turns", "qa_pairs", "minutes", "summaries", "calendar", "manifest"]},
                            "size_bytes": {"type": "integer"},
                            "record_count": {"type": "integer"},
                            "validation_status": {"type": "string", "enum": ["valid", "invalid", "warning"]},
                            "quality_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            "generation_time_seconds": {"type": "integer"},
                            "dependencies": {"type": "array", "items": {"type": "string"}},
                            "schema_version": {"type": "string"}
                        }
                    }
                },
                "quality_metrics": {
                    "type": "object",
                    "required": ["transcript_clarity", "speaker_identification", "timestamp_accuracy", "content_completeness"],
                    "properties": {
                        "transcript_clarity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "speaker_identification": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "timestamp_accuracy": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "content_completeness": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                    }
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}}
            }
        }
    }
}


def get_schema_by_type(artifact_type: str) -> Dict[str, Any]:
    """
    Get JSON schema for a specific artifact type.
    
    Args:
        artifact_type: Type of artifact (turns, qa_pairs, etc.)
        
    Returns:
        JSON schema dictionary
        
    Raises:
        ValueError: If artifact type is not recognized
    """
    schemas = {
        "turns": TURNS_SCHEMA,
        "qa_pairs": QA_PAIRS_SCHEMA, 
        "minutes": MINUTES_SCHEMA,
        "summaries": SUMMARIES_SCHEMA,
        "calendar": CALENDAR_SCHEMA,
        "manifest": MANIFEST_SCHEMA
    }
    
    if artifact_type not in schemas:
        raise ValueError(f"Unknown artifact type: {artifact_type}")
        
    return schemas[artifact_type]