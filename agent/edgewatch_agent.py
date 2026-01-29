from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

from buffer import SqliteBuffer
from sensors.mock_sensors import read_metrics


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_point(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message_id": uuid.uuid4().hex,
        "ts": utcnow_iso(),
        "metrics": metrics,
    }


def post_points(api_url: str, token: str, points: List[Dict[str, Any]], timeout_s: float = 5.0) -> requests.Response:
    return requests.post(
        f"{api_url.rstrip('/')}/api/v1/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={"points": points},
        timeout=timeout_s,
    )


def main() -> None:
    load_dotenv()

    api_url = os.getenv("EDGEWATCH_API_URL", "http://localhost:8082")
    device_id = os.getenv("EDGEWATCH_DEVICE_ID", "demo-well-001")
    token = os.getenv("EDGEWATCH_DEVICE_TOKEN", "dev-device-token-001")
    interval_s = int(os.getenv("HEARTBEAT_INTERVAL_S", "30"))
    buffer_path = os.getenv("BUFFER_DB_PATH", "./edgewatch_buffer.sqlite")

    buf = SqliteBuffer(buffer_path)

    print(f"[edgewatch-agent] device_id={device_id} api={api_url} interval_s={interval_s} buffer={buffer_path}")

    while True:
        # 1) Flush buffer first (oldest first)
        queued = buf.dequeue_batch(limit=50)
        if queued:
            try:
                resp = post_points(api_url, token, [m.payload for m in queued])
                if resp.status_code >= 200 and resp.status_code < 300:
                    for m in queued:
                        buf.delete(m.message_id)
                    print(f"[edgewatch-agent] flushed {len(queued)} buffered points (queue={buf.count()})")
                else:
                    print(f"[edgewatch-agent] flush failed: {resp.status_code} {resp.text[:200]}")
            except Exception as e:
                print(f"[edgewatch-agent] flush exception: {e!r}")

        # 2) Create current heartbeat point
        metrics = read_metrics(device_id=device_id)
        point = make_point(metrics)

        # 3) Send current point
        try:
            resp = post_points(api_url, token, [point])
            if resp.status_code >= 200 and resp.status_code < 300:
                print(f"[edgewatch-agent] sent heartbeat ok (queue={buf.count()}) metrics={list(metrics.keys())}")
            else:
                print(f"[edgewatch-agent] send failed: {resp.status_code} {resp.text[:200]}")
                buf.enqueue(point["message_id"], point, point["ts"])
        except Exception as e:
            print(f"[edgewatch-agent] send exception: {e!r} (buffering)")
            buf.enqueue(point["message_id"], point, point["ts"])

        time.sleep(interval_s)


if __name__ == "__main__":
    main()
