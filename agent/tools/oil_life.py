from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.sensors.derived.oil_life import OilLifeStateStore, now_utc


def _print_state(path: Path, state_json: dict[str, object]) -> None:
    output = {
        "state_path": str(path),
        "state": state_json,
    }
    print(json.dumps(output, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Oil life local state utility")
    parser.add_argument(
        "command",
        choices=("reset", "show"),
        help="operation to perform",
    )
    parser.add_argument(
        "--state",
        default="./agent/state/oil_life_state.json",
        help="path to oil life state JSON",
    )
    args = parser.parse_args()

    state_path = Path(args.state).expanduser()
    store = OilLifeStateStore(state_path)

    if args.command == "reset":
        state = store.reset(now=now_utc())
        _print_state(
            state_path,
            {
                "oil_life_runtime_s": state.oil_life_runtime_s,
                "oil_life_reset_at": state.oil_life_reset_at,
                "oil_life_last_seen_running_at": state.oil_life_last_seen_running_at,
                "is_running": state.is_running,
            },
        )
        return

    if args.command == "show":
        state = store.load()
        _print_state(
            state_path,
            {
                "oil_life_runtime_s": state.oil_life_runtime_s,
                "oil_life_reset_at": state.oil_life_reset_at,
                "oil_life_last_seen_running_at": state.oil_life_last_seen_running_at,
                "is_running": state.is_running,
            },
        )
        return

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
