"""
Lambda handler to reprocess downstream artifacts starting from the QA output.

This function allows re-running the minutes, calendar, summaries, and manifest
stages without repeating the expensive preprocessing and grouping work.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from .minutes_actions import lambda_handler as minutes_lambda
from .make_ics import lambda_handler as make_ics_lambda
from .summarize import lambda_handler as summarize_lambda
from .make_manifest import lambda_handler as manifest_lambda

logger = logging.getLogger(__name__)


def _default_prefix(meeting_id: str) -> str:
    return f"meetings/{meeting_id}/"


def _invoke_with_throttle_retry(func, event: Dict[str, Any], context: Any,
                                max_attempts: int = 3, base_sleep: float = 30.0) -> Dict[str, Any]:
    """Call a handler, retrying on Bedrock throttling errors."""
    for attempt in range(1, max_attempts + 1):
        result = func(event, context)
        status = result.get("statusCode")
        if status == 200:
            return result

        error_text = str(result.get("error", ""))
        lowered = error_text.lower()
        retryable = any(
            token in lowered
            for token in (
                "throttlingexception",
                "too many requests",
                "model response is not valid json",
                "invalid response format",
                "failed to parse json",
                "empty response"
            )
        )

        if not retryable or attempt == max_attempts:
            return result

        sleep_time = base_sleep * attempt
        logger.warning(
            "Retrying %s after retryable error (attempt %d/%d) in %.1f seconds: %s",
            getattr(func, "__name__", "handler"),
            attempt,
            max_attempts,
            sleep_time,
            error_text,
        )
        time.sleep(sleep_time)

    return {"statusCode": 500, "error": "Unhandled retry loop exit"}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Reprocess minutes/ICS/summaries/manifest using existing QA output."""
    meeting_id = event["meeting_id"]
    base_output_prefix = event.get("base_output_prefix") or _default_prefix(meeting_id)

    turns_key = event.get("turns_key") or f"{base_output_prefix}01_turns.json"
    qa_key = event.get("qa_key") or f"{base_output_prefix}02_qa_pairs.json"
    minutes_key = event.get("minutes_key") or f"{base_output_prefix}03_minutes.json"
    summaries_key = event.get("summaries_key") or f"{base_output_prefix}04_summaries.json"
    calendar_key = event.get("calendar_key") or f"{base_output_prefix}05_calendar.json"
    manifest_key = event.get("manifest_key") or f"{base_output_prefix}06_manifest.json"

    logger.info(
        "Reprocessing parallel artifacts for meeting %s (QA: %s)",
        meeting_id,
        qa_key,
    )

    skip_calendar = bool(event.get("skip_calendar") or event.get("skip_ics"))

    results: Dict[str, Any] = {
        "meeting_id": meeting_id,
        "base_output_prefix": base_output_prefix,
        "turns_key": turns_key,
        "qa_key": qa_key,
        "skip_calendar": skip_calendar,
    }

    minutes_event = {
        "meeting_id": meeting_id,
        "input_key": qa_key,
        "output_key": minutes_key,
    }
    minutes_result = _invoke_with_throttle_retry(minutes_lambda, minutes_event, context)
    results["minutes"] = minutes_result
    if minutes_result.get("statusCode") != 200:
        results["statusCode"] = minutes_result.get("statusCode", 500)
        results["error"] = minutes_result.get("error", "Minutes generation failed")
        return results

    calendar_output_key: Any = calendar_key
    if skip_calendar:
        logger.info("Skipping calendar generation as requested")
        results["calendar"] = {
            "statusCode": 204,
            "message": "Calendar generation skipped",
            "meeting_id": meeting_id,
        }
        calendar_output_key = None
    else:
        ics_event = {
            "meeting_id": meeting_id,
            "input_key": minutes_key,
            "output_key": calendar_key,
        }
        ics_result = _invoke_with_throttle_retry(make_ics_lambda, ics_event, context)
        results["calendar"] = ics_result
        if ics_result.get("statusCode") != 200:
            results["statusCode"] = ics_result.get("statusCode", 500)
            results["error"] = ics_result.get("error", "Calendar generation failed")
            return results
        calendar_output_key = ics_result.get("output_key", calendar_key)

    summaries_event = {
        "meeting_id": meeting_id,
        "input_key": qa_key,
        "output_key": summaries_key,
    }
    summaries_result = _invoke_with_throttle_retry(summarize_lambda, summaries_event, context)
    results["summaries"] = summaries_result
    if summaries_result.get("statusCode") != 200:
        results["statusCode"] = summaries_result.get("statusCode", 500)
        results["error"] = summaries_result.get("error", "Summaries generation failed")
        return results

    manifest_event = {
        "meeting_id": meeting_id,
        "output_key": manifest_key,
        "turns_key": turns_key,
        "qa_pairs_key": qa_key,
        "minutes_key": minutes_key,
        "summaries_key": summaries_key,
    "calendar_key": calendar_output_key,
    }
    manifest_result = manifest_lambda(manifest_event, context)
    results["manifest"] = manifest_result

    status = 200
    if manifest_result.get("statusCode") != 200:
        status = manifest_result.get("statusCode", 500)

    results["statusCode"] = status
    return results
