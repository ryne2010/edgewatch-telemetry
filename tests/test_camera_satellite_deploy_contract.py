from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_camera_satellite_systemd_unit_is_local_bounded_and_hardened() -> None:
    unit = (ROOT / "deploy/rpi/camera-satellite/edgewatch-camera-satellite@.service").read_text(
        encoding="utf-8"
    )

    assert "/opt/edgewatch/app/.venv/bin/python -m agent.camera_satellite_runner --mode %i" in unit
    assert "User=edgewatch-camera" in unit
    assert "EnvironmentFile=/etc/edgewatch/camera-satellite.env" in unit
    assert "ExecCondition=/usr/bin/test %i = check" in unit
    assert "TimeoutStartSec=180" in unit
    assert "RuntimeMaxSec=180" in unit
    assert "StateDirectory=edgewatch-camera-satellite edgewatch-media" in unit
    assert "ProtectSystem=strict" in unit
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in unit
    assert "Restart=" not in unit
    assert "--poweroff-on-success" not in unit
    assert "TELEGRAM" not in unit
    assert "LTE" not in unit
    assert "Requires=edgewatch-camera-model-recovery.service" in unit

    wake_unit = (ROOT / "deploy/rpi/camera-satellite/edgewatch-camera-satellite-wake@.service").read_text(
        encoding="utf-8"
    )
    assert "--mode %i --poweroff-on-success" in wake_unit
    assert "Requires=edgewatch-camera-model-recovery.service" in wake_unit

    recovery_unit = (ROOT / "deploy/rpi/camera-satellite/edgewatch-camera-model-recovery.service").read_text(
        encoding="utf-8"
    )
    assert "User=root" in recovery_unit
    assert "--recover-only" in recovery_unit
    assert "ProtectSystem=strict" in recovery_unit
    assert "ReadWritePaths=/opt/edgewatch/models" in recovery_unit
    assert "RemainAfterExit" not in recovery_unit
    assert "User=edgewatch-camera" not in recovery_unit

    path_unit = (ROOT / "deploy/rpi/camera-satellite/edgewatch-camera-satellite-poweroff.path").read_text(
        encoding="utf-8"
    )
    poweroff_unit = (
        ROOT / "deploy/rpi/camera-satellite/edgewatch-camera-satellite-poweroff.service"
    ).read_text(encoding="utf-8")
    assert "PathExists=/run/edgewatch-camera-satellite/poweroff.request" in path_unit
    assert "ExecStart=/usr/bin/rm -f /run/edgewatch-camera-satellite/poweroff.request" in poweroff_unit
    assert "ExecStart=/usr/bin/systemctl poweroff --no-wall" in poweroff_unit
    assert "EnvironmentFile=" not in poweroff_unit


def test_camera_satellite_environment_keeps_credentials_in_a_secret_file() -> None:
    example = (ROOT / "deploy/rpi/camera-satellite/camera-satellite.env.example").read_text(encoding="utf-8")

    assert "MEDIA_RTSP_CAM1_CREDENTIALS_FILE=" in example
    assert "MEDIA_RTSP_CAM1_URL=rtsp://" in example
    assert "EDGEWATCH_INFERENCE_MODE=shadow" in example
    assert "EDGEWATCH_MODEL_LITERT_VERSION=2.1.6" in example
    assert "EDGEWATCH_CURRENT_SYMLINK=/opt/edgewatch/current" in example
    assert "EDGEWATCH_SATELLITE_EVIDENCE_MAX_BYTES=" in example
    assert "EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH=/run/" in example
    assert "password=" not in example


def test_model_apply_readiness_uses_non_poweroff_camera_check() -> None:
    apply_script = (ROOT / "scripts/apply_model_bundle.py").read_text(encoding="utf-8")

    assert '"edgewatch-camera-satellite@check.service"' in apply_script
    assert '["/usr/bin/systemctl", "start", _CHECK_UNIT]' in apply_script
    assert 'payload.get("mode") == "check"' in apply_script
    assert 'payload.get("poweroff_requested") is False' in apply_script
    assert "--poweroff-on-success" not in apply_script
