from __future__ import annotations

import json
from pathlib import Path

from agent.sensors.derived.oil_life import OilLifeStateStore
from agent.tools.oil_life import main


def test_oil_life_tool_reset_writes_state(tmp_path: Path, monkeypatch, capsys) -> None:
    state_path = tmp_path / "oil_life_state.json"
    monkeypatch.setattr("sys.argv", ["oil_life", "reset", "--state", str(state_path)])

    main()

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["state_path"] == str(state_path)

    state = OilLifeStateStore(state_path).load()
    assert state.oil_life_runtime_s == 0.0
    assert state.oil_life_last_seen_running_at is None
    assert state.is_running is False


def test_oil_life_tool_show_prints_existing_state(tmp_path: Path, monkeypatch, capsys) -> None:
    state_path = tmp_path / "oil_life_state.json"
    store = OilLifeStateStore(state_path)
    state = store.reset()

    monkeypatch.setattr("sys.argv", ["oil_life", "show", "--state", str(state_path)])
    main()

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["state"]["oil_life_runtime_s"] == 0.0
    assert payload["state"]["oil_life_reset_at"] == state.oil_life_reset_at
