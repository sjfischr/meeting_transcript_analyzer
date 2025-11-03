"""Command-line helpers for GRiST meeting pipeline maintenance."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

DEFAULT_MEETING_PREFIX = "meetings/"
TRIGGER_SUFFIX = ".txt"
DEFAULT_LIST_LIMIT = 10


def resolve_bucket(explicit: Optional[str]) -> str:
    bucket = explicit or os.getenv("ARTIFACTS_BUCKET") or os.getenv("BUCKET")
    if not bucket:
        raise SystemExit(
            "Artifacts bucket not provided. Use --bucket or set ARTIFACTS_BUCKET/BUCKET."
        )
    return bucket


def extract_meeting_id(key: str) -> str:
    if key.startswith(DEFAULT_MEETING_PREFIX):
        parts = key[len(DEFAULT_MEETING_PREFIX) :].split("/", 1)
        if parts:
            return parts[0]
    return key.rsplit("/", 1)[-1].replace(TRIGGER_SUFFIX, "")


def list_recent_jobs(bucket: str, prefix: Optional[str], limit: int) -> List[Dict[str, Any]]:
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    kwargs: Dict[str, Any] = {"Bucket": bucket}
    if prefix:
        kwargs["Prefix"] = prefix

    items: List[Dict[str, Any]] = []
    for page in paginator.paginate(**kwargs):
        contents: Iterable[Dict[str, Any]] = page.get("Contents", [])
        for obj in contents:
            key = obj["Key"]
            if not key.endswith(TRIGGER_SUFFIX):
                continue
            items.append(obj)

    items.sort(key=lambda obj: obj["LastModified"], reverse=True)
    return items[:limit]


def cmd_list_jobs(args: argparse.Namespace) -> None:
    bucket = resolve_bucket(args.bucket)
    items = list_recent_jobs(bucket=bucket, prefix=args.prefix, limit=args.limit)

    if not items:
        print("No transcript uploads found.")
        return

    print(f"Recent transcript uploads in s3://{bucket}/{args.prefix or ''}")
    for obj in items:
        last_modified: datetime = obj["LastModified"].astimezone(timezone.utc)
        meeting_id = extract_meeting_id(obj["Key"])
        size_kb = obj["Size"] / 1024
        print(
            f"- {meeting_id} | {obj['Key']} | {last_modified.isoformat()} | {size_kb:.1f} KB"
        )


def build_reprocess_payload(args: argparse.Namespace) -> Dict[str, Any]:
    meeting_id = args.meeting_id
    prefix = args.base_output_prefix or f"{DEFAULT_MEETING_PREFIX}{meeting_id}/"
    payload: Dict[str, Any] = {"meeting_id": meeting_id}

    if args.base_output_prefix:
        payload["base_output_prefix"] = args.base_output_prefix
    else:
        payload["base_output_prefix"] = prefix

    if args.turns_key:
        payload["turns_key"] = args.turns_key
    else:
        payload["turns_key"] = f"{prefix}01_turns.json"

    if args.qa_key:
        payload["qa_key"] = args.qa_key
    else:
        payload["qa_key"] = f"{prefix}02_qa_pairs.json"

    if args.minutes_key:
        payload["minutes_key"] = args.minutes_key
    if args.summaries_key:
        payload["summaries_key"] = args.summaries_key
    if args.skip_calendar:
        payload["skip_calendar"] = True
    elif args.calendar_key:
        payload["calendar_key"] = args.calendar_key
    if args.manifest_key:
        payload["manifest_key"] = args.manifest_key

    return payload


def resolve_lambda_name(args: argparse.Namespace, lambda_client: Any) -> str:
    explicit = args.function_name
    if explicit:
        return explicit

    stack_name = args.stack_name or os.getenv("SAM_STACK_NAME")
    if stack_name:
        cf = boto3.client("cloudformation", region_name=args.region)
        try:
            detail = cf.describe_stack_resource(
                StackName=stack_name,
                LogicalResourceId="ReprocessParallelFn",
            )
            return detail["StackResourceDetail"]["PhysicalResourceId"]
        except ClientError as exc:
            print(
                f"Warning: could not resolve ReprocessParallelFn in stack {stack_name}: {exc}"
            )

    # Fallback: search Lambda functions in account for matching name
    try:
        paginator = lambda_client.get_paginator("list_functions")
        matches: List[str] = []
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                name = fn.get("FunctionName")
                if not name:
                    continue
                if "ReprocessParallelFn" in name:
                    matches.append(name)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(
                "Warning: multiple Lambda functions match '*ReprocessParallelFn':\n"
                + "\n".join(f"  - {m}" for m in matches)
                + "\nUsing the first entry; specify --function-name to override."
            )
            return matches[0]
    except ClientError as exc:
        print(f"Warning: could not list Lambda functions: {exc}")

    return "ReprocessParallelFn"


def cmd_reprocess(args: argparse.Namespace) -> None:
    payload = build_reprocess_payload(args)
    config = Config(read_timeout=900, connect_timeout=30)
    lambda_client = boto3.client("lambda", region_name=args.region, config=config)

    function_name = resolve_lambda_name(args, lambda_client)

    response = lambda_client.invoke(
        FunctionName=function_name,
        Payload=json.dumps(payload).encode("utf-8"),
    )

    body = response.get("Payload")
    if body is not None:
        result_text = body.read().decode("utf-8")
        try:
            parsed = json.loads(result_text)
            print(json.dumps(parsed, indent=2))
        except json.JSONDecodeError:
            print(result_text)
    else:
        print(json.dumps(response, default=str, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List recent transcript uploads")
    list_parser.add_argument("--bucket", help="Artifacts bucket (defaults to env)")
    list_parser.add_argument("--prefix", help="Prefix to search (e.g. meetings/)")
    list_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIST_LIMIT,
        help=f"Maximum jobs to display (default {DEFAULT_LIST_LIMIT})",
    )
    list_parser.set_defaults(func=cmd_list_jobs)

    reprocess_parser = subparsers.add_parser(
        "reprocess", help="Invoke ReprocessParallelFn for a meeting"
    )
    reprocess_parser.add_argument("meeting_id", help="Meeting identifier")
    reprocess_parser.add_argument(
        "--function-name",
        help="Override Lambda function name (defaults to stack logical resource)",
    )
    reprocess_parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        help="AWS region (defaults to AWS_REGION/AWS_DEFAULT_REGION)",
    )
    reprocess_parser.add_argument(
        "--stack-name",
        default=os.getenv("SAM_STACK_NAME") or os.getenv("CFN_STACK_NAME"),
        help="CloudFormation stack name (used to auto-resolve function name)",
    )
    reprocess_parser.add_argument(
        "--base-output-prefix",
        help="Custom base prefix for artifacts (defaults to meetings/{meeting_id}/)",
    )
    reprocess_parser.add_argument("--turns-key", help="Override turns artifact key")
    reprocess_parser.add_argument("--qa-key", help="Override QA artifact key")
    reprocess_parser.add_argument("--minutes-key", help="Override minutes artifact key")
    reprocess_parser.add_argument("--summaries-key", help="Override summaries artifact key")
    reprocess_parser.add_argument("--calendar-key", help="Override calendar artifact key")
    reprocess_parser.add_argument("--manifest-key", help="Override manifest artifact key")
    reprocess_parser.add_argument(
        "--skip-calendar",
        action="store_true",
        help="Skip calendar (ICS) generation and continue pipeline",
    )
    reprocess_parser.set_defaults(func=cmd_reprocess)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
