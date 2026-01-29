from __future__ import annotations

import argparse
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

    parser = argparse.ArgumentParser(description="EdgeWatch simulator (device heartbeat + buffering)")
    parser.add_argument("--simulate-offline-after-s", type=int, default=0, help="Stop sending after N seconds (buffer only)")
    parser.add_argument("--resume-after-s", type=int, default=0, help="Resume sending after N seconds (flush buffer)")
    args = parser.parse_args()

    api_url = os.getenv("EDGEWATCH_API_URL", "http://localhost:8082")
    device_id = os.getenv("EDGEWATCH_DEVICE_ID", "demo-well-001")
    token = os.getenv("EDGEWATCH_DEVICE_TOKEN", "dev-device-token-001")
    interval_s = int(os.getenv("HEARTBEAT_INTERVAL_S", "30"))
    buffer_path = os.getenv("BUFFER_DB_PATH", "./edgewatch_buffer.sqlite")

    buf = SqliteBuffer(buffer_path)
    start = time.time()

    print(f"[simulator] device_id={device_id} api={api_url} interval_s={interval_s}")
    print(f"[simulator] offline_after={args.simulate_offline_after_s}s resume_after={args.resume_after_s}s")

    while True:
        elapsed = int(time.time() - start)
        offline = args.simulate_offline_after_s > 0 and elapsed >= args.simulate_offline_after_s
        resume = args.resume_after_s > 0 and elapsed >= args.resume_after_s
        if resume:
            offline = False

        # flush buffer if online
        if not offline:
            queued = buf.dequeue_batch(limit=50)
            if queued:
                try:
                    resp = post_points(api_url, token, [m.payload for m in queued])
                    if 200 <= resp.status_code < 300:
                        for m in queued:
                            buf.delete(m.message_id)
                        print(f"[simulator] flushed {len(queued)} buffered points (queue={buf.count()})")
                    else:
                        print(f"[simulator] flush failed: {resp.status_code} {resp.text[:200]}")
                except Exception as e:
                    print(f"[simulator] flush exception: {e!r}")

        metrics = read_metrics(device_id=device_id)
        point = make_point(metrics)

        if offline:
            buf.enqueue(point["message_id"], point, point["ts"])
            print(f"[simulator] OFFLINE -> buffered heartbeat (queue={buf.count()})")
        else:
            try:
                resp = post_points(api_url, token, [point])
                if 200 <= resp.status_code < 300:
                    print(f"[simulator] sent heartbeat ok (queue={buf.count()}) water={metrics.get('water_pressure_psi')}psi")
                else:
                    buf.enqueue(point["message_id"], point, point["ts"])
                    print(f"[simulator] send failed {resp.status_code} -> buffered (queue={buf.count()})")
            except Exception as e:
                buf.enqueue(point["message_id"], point, point["ts"])
                print(f"[simulator] exception {e!r} -> buffered (queue={buf.count()})")

        time.sleep(interval_s)


if __name__ == "__main__":
    main()
