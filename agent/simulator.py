from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from buffer import SqliteBuffer
from device_policy import CachedPolicy, DevicePolicy, fetch_device_policy, load_cached_policy, save_cached_policy
from edgewatch_agent import (
    AgentState,
    _changed_keys,
    _compute_state,
    _flush_buffer,
    _mark_point_recorded,
    _maybe_prune,
    _minimal_heartbeat_metrics,
    make_point,
    post_points,
)
from sensors.mock_sensors import read_metrics


def main() -> None:
    """EdgeWatch simulator.

    This is intentionally similar to the real agent, but adds CLI flags that
    simulate intermittent connectivity.
    """

    load_dotenv()
    load_dotenv(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(description="EdgeWatch simulator (optimized send + buffering)")
    parser.add_argument(
        "--simulate-offline-after-s",
        type=int,
        default=0,
        help="Stop sending after N seconds (buffer only)",
    )
    parser.add_argument(
        "--resume-after-s",
        type=int,
        default=0,
        help="Resume sending after N seconds (flush buffer)",
    )
    args = parser.parse_args()

    api_url = os.getenv("EDGEWATCH_API_URL", "http://localhost:8082")
    device_id = os.getenv("EDGEWATCH_DEVICE_ID", "demo-well-001")
    token = os.getenv("EDGEWATCH_DEVICE_TOKEN", "dev-device-token-001")

    buffer_path = os.getenv("BUFFER_DB_PATH", "./edgewatch_buffer.sqlite")
    buf = SqliteBuffer(buffer_path)

    session = requests.Session()

    cached: CachedPolicy | None = load_cached_policy()
    policy: DevicePolicy = cached.policy if cached else _fallback_policy(device_id)

    next_policy_refresh_at = 0.0
    if cached:
        next_policy_refresh_at = cached.fetched_at + float(policy.cache_max_age_s)

    start = time.time()

    print(
        "[simulator] device_id=%s api=%s buffer=%s policy=%s"
        % (device_id, api_url, buffer_path, policy.policy_version)
    )
    print(f"[simulator] offline_after={args.simulate_offline_after_s}s resume_after={args.resume_after_s}s")

    state = AgentState()

    while True:
        now = time.time()
        elapsed = int(now - start)

        offline = args.simulate_offline_after_s > 0 and elapsed >= args.simulate_offline_after_s
        resume = args.resume_after_s > 0 and elapsed >= args.resume_after_s
        if resume:
            offline = False

        # Refresh device policy (best-effort).
        if now >= next_policy_refresh_at:
            try:
                pol, etag, max_age = fetch_device_policy(session, api_url=api_url, token=token, cached=cached)
                if pol is not None:
                    policy = pol
                    if etag:
                        save_cached_policy(policy, etag)
                        cached = load_cached_policy()

                ttl = max_age if max_age is not None else policy.cache_max_age_s
                next_policy_refresh_at = time.time() + float(ttl)
            except Exception as e:
                print(f"[simulator] policy fetch failed (using cached/default): {e!r}")
                next_policy_refresh_at = time.time() + 60.0

        metrics = read_metrics(device_id=device_id)
        current_state, current_alerts = _compute_state(metrics, state.last_alerts, policy)
        critical_active = "WATER_PRESSURE_LOW" in current_alerts

        # Only critical alerts force faster sampling.
        sample_s = (
            policy.reporting.alert_sample_interval_s if critical_active else policy.reporting.sample_interval_s
        )

        send_reason: str | None = None
        payload_metrics: dict[str, object] = {}

        # Bootstrap: send a full snapshot once on startup to establish baseline.
        if state.last_state == "UNKNOWN" and not state.last_metrics_snapshot:
            send_reason = "startup"
            payload_metrics = dict(metrics)

        elif current_alerts != state.last_alerts:
            send_reason = "state_change" if current_state != state.last_state else "alert_change"
            payload_metrics = dict(metrics)
        else:
            if critical_active and (
                now - state.last_alert_snapshot_at >= policy.reporting.alert_report_interval_s
            ):
                send_reason = "alert_snapshot"
                payload_metrics = dict(metrics)
            elif now - state.last_heartbeat_at >= policy.reporting.heartbeat_interval_s:
                send_reason = "heartbeat"
                payload_metrics = _minimal_heartbeat_metrics(metrics)
            else:
                changed = _changed_keys(
                    current=metrics,
                    previous=state.last_metrics_snapshot,
                    thresholds=policy.delta_thresholds,
                )
                if changed:
                    send_reason = "delta"
                    payload_metrics = {k: metrics[k] for k in changed}

        if send_reason:
            baseline_update = (
                dict(payload_metrics) if send_reason in {"delta", "heartbeat"} else dict(metrics)
            )

            payload_metrics["device_state"] = current_state
            point = make_point(payload_metrics)

            _mark_point_recorded(state, now=now, reason=send_reason, alerts=current_alerts)
            state.last_metrics_snapshot.update(baseline_update)

            if offline:
                buf.enqueue(point["message_id"], point, point["ts"])
                _maybe_prune(buf, policy)
                print(f"[simulator] OFFLINE -> buffered ({send_reason}) queue={buf.count()}")
            else:
                try:
                    ok = _flush_buffer(
                        session=session,
                        buf=buf,
                        api_url=api_url,
                        token=token,
                        max_points_per_batch=policy.reporting.max_points_per_batch,
                    )
                    if not ok:
                        raise RuntimeError("buffer flush failed")

                    resp = post_points(session, api_url, token, [point])
                    if 200 <= resp.status_code < 300:
                        print(
                            "[simulator] sent (%s) state=%s alerts=%s queue=%s water=%spsi batt=%sv"
                            % (
                                send_reason,
                                current_state,
                                sorted(current_alerts),
                                buf.count(),
                                metrics.get("water_pressure_psi"),
                                metrics.get("battery_v"),
                            )
                        )
                    else:
                        raise RuntimeError(f"send failed: {resp.status_code} {resp.text[:200]}")

                except Exception as e:
                    buf.enqueue(point["message_id"], point, point["ts"])
                    _maybe_prune(buf, policy)
                    print(f"[simulator] send exception {e!r} -> buffered queue={buf.count()}")

            state.last_state = current_state
            state.last_alerts = set(current_alerts)

        time.sleep(max(1.0, float(sample_s)))


def _fallback_policy(device_id: str) -> DevicePolicy:
    # Keep simulator behavior consistent with the real agent when policy fetch fails.
    from edgewatch_agent import _default_policy

    return _default_policy(device_id)


if __name__ == "__main__":
    main()
