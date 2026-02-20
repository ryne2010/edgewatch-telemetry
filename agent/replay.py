from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


def _parse_dt(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts_from_payload(payload: dict[str, Any]) -> datetime:
    ts_raw = payload.get("ts")
    if not isinstance(ts_raw, str) or not ts_raw.strip():
        raise ValueError("payload missing ts")
    return _parse_dt(ts_raw)


def _iter_replay_points(
    *,
    db_path: str,
    since: datetime,
    until: datetime | None,
    max_points: int | None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[str] = []

    clauses.append("created_at >= ?")
    params.append(since.isoformat())

    if until is not None:
        clauses.append("created_at <= ?")
        params.append(until.isoformat())

    where_sql = " AND ".join(clauses) if clauses else "1=1"
    sql = f"SELECT message_id, payload_json, created_at FROM queue WHERE {where_sql} ORDER BY created_at ASC"

    points: list[dict[str, Any]] = []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    for message_id, payload_json, _ in rows:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            continue

        payload_message_id = payload.get("message_id")
        if payload_message_id != message_id:
            payload["message_id"] = message_id

        ts = _parse_ts_from_payload(payload)
        if ts < since:
            continue
        if until is not None and ts > until:
            continue

        points.append(payload)
        if max_points is not None and len(points) >= max_points:
            break

    return points


def _post_batch(
    *,
    session: requests.Session,
    api_url: str,
    token: str,
    points: list[dict[str, Any]],
    timeout_s: float,
) -> dict[str, Any]:
    response = session.post(
        f"{api_url.rstrip('/')}/api/v1/ingest",
        headers={
            "Authorization": f"Bearer {token}",
            "X-EdgeWatch-Ingest-Source": "replay",
        },
        json={"points": points},
        timeout=timeout_s,
    )

    if response.status_code >= 300:
        body = response.text[:500]
        raise RuntimeError(f"ingest failed ({response.status_code}): {body}")

    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("ingest returned non-object response")
    return data


def main() -> None:
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(description="Replay buffered telemetry by time range")
    parser.add_argument("--since", required=True, help="Inclusive start timestamp (ISO-8601)")
    parser.add_argument("--until", default=None, help="Inclusive end timestamp (ISO-8601)")
    parser.add_argument("--batch-size", type=int, default=100, help="Points per ingest call (1-500)")
    parser.add_argument(
        "--rate-limit-rps",
        type=float,
        default=2.0,
        help="Maximum ingest calls per second (0 disables rate limiting)",
    )
    parser.add_argument("--max-points", type=int, default=None, help="Optional cap on replayed points")
    parser.add_argument("--timeout-s", type=float, default=10.0, help="HTTP timeout for each ingest call")
    parser.add_argument(
        "--api-url",
        default=os.getenv("EDGEWATCH_API_URL", "http://localhost:8082"),
        help="EdgeWatch API base URL",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("EDGEWATCH_DEVICE_TOKEN", "dev-device-token-001"),
        help="Device bearer token",
    )
    parser.add_argument(
        "--device-id",
        default=os.getenv("EDGEWATCH_DEVICE_ID", "demo-well-001"),
        help="Device ID (informational)",
    )
    parser.add_argument(
        "--buffer-db",
        default=os.getenv("BUFFER_DB_PATH", "./edgewatch_buffer.sqlite"),
        help="Path to local SQLite buffer",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print replay plan without posting")
    args = parser.parse_args()

    since = _parse_dt(args.since)
    until = _parse_dt(args.until) if args.until else None
    if until is not None and since > until:
        raise SystemExit("--since must be <= --until")

    if args.batch_size < 1 or args.batch_size > 500:
        raise SystemExit("--batch-size must be between 1 and 500")

    points = _iter_replay_points(
        db_path=args.buffer_db,
        since=since,
        until=until,
        max_points=args.max_points,
    )

    print(
        "[replay] device_id=%s buffer=%s since=%s until=%s points=%s"
        % (
            args.device_id,
            args.buffer_db,
            since.isoformat(),
            until.isoformat() if until else "(none)",
            len(points),
        )
    )

    if args.dry_run or not points:
        return

    session = requests.Session()
    total_sent = 0
    total_accepted = 0
    total_duplicates = 0
    total_quarantined = 0

    min_interval_s = 0.0
    if args.rate_limit_rps > 0:
        min_interval_s = 1.0 / float(args.rate_limit_rps)

    for idx in range(0, len(points), args.batch_size):
        batch = points[idx : idx + args.batch_size]
        started = time.perf_counter()

        data = _post_batch(
            session=session,
            api_url=args.api_url,
            token=args.token,
            points=batch,
            timeout_s=args.timeout_s,
        )

        accepted = int(data.get("accepted", 0))
        duplicates = int(data.get("duplicates", 0))
        quarantined = int(data.get("quarantined", 0))

        total_sent += len(batch)
        total_accepted += accepted
        total_duplicates += duplicates
        total_quarantined += quarantined

        print(
            "[replay] batch=%s sent=%s accepted=%s duplicates=%s quarantined=%s batch_id=%s"
            % (
                (idx // args.batch_size) + 1,
                len(batch),
                accepted,
                duplicates,
                quarantined,
                data.get("batch_id", ""),
            )
        )

        elapsed = time.perf_counter() - started
        if min_interval_s > elapsed:
            time.sleep(min_interval_s - elapsed)

    print(
        "[replay] complete sent=%s accepted=%s duplicates=%s quarantined=%s"
        % (total_sent, total_accepted, total_duplicates, total_quarantined)
    )


if __name__ == "__main__":
    main()
