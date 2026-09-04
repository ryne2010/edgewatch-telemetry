from __future__ import annotations

import math
from dataclasses import dataclass

_SUPPORTED_AUDIO_CODECS = frozenset({"aac", "pcm_alaw", "pcm_mulaw"})
_SUPPORTED_POWER = frozenset({"12v", "poe", "12v_or_poe"})


@dataclass(frozen=True)
class CameraQualificationEvidence:
    works_without_internet: bool
    works_without_cloud_account: bool
    local_credentials_supported: bool
    video_codec: str
    audio_codec: str | None
    ingress_rating: str
    power_interface: str
    first_media_seconds: tuple[float, ...]
    successful_power_cycles: int
    attempted_power_cycles: int
    automatic_stream_recovery: bool
    recovery_observation_hours: float
    satellite_electronics_cost_usd: float


@dataclass(frozen=True)
class CameraQualificationResult:
    qualified: bool
    failures: tuple[str, ...]


def evaluate_camera_qualification(
    evidence: CameraQualificationEvidence,
) -> CameraQualificationResult:
    failures: list[str] = []
    if not evidence.works_without_internet:
        failures.append("camera requires Internet access")
    if not evidence.works_without_cloud_account:
        failures.append("camera requires a cloud account")
    if not evidence.local_credentials_supported:
        failures.append("camera lacks local credentials")
    if evidence.video_codec.lower() != "h264":
        failures.append("camera substream is not H.264")
    audio_codec = (evidence.audio_codec or "").lower()
    if audio_codec not in _SUPPORTED_AUDIO_CODECS:
        failures.append("camera does not expose AAC or G.711 audio")
    if evidence.ingress_rating.upper() not in {"IP67", "IP68"}:
        failures.append("camera enclosure is below IP67")
    if evidence.power_interface.lower() not in _SUPPORTED_POWER:
        failures.append("camera does not support 12 V or PoE power")
    if not evidence.first_media_seconds or any(
        not math.isfinite(item) or item <= 0.0 or item > 90.0 for item in evidence.first_media_seconds
    ):
        failures.append("first usable video/audio was not within 0..90 seconds")
    if (
        evidence.attempted_power_cycles < 100
        or evidence.successful_power_cycles < 99
        or evidence.successful_power_cycles > evidence.attempted_power_cycles
    ):
        failures.append("camera did not pass at least 99 of 100 power cycles")
    if (
        not evidence.automatic_stream_recovery
        or not math.isfinite(evidence.recovery_observation_hours)
        or evidence.recovery_observation_hours < 24.0
    ):
        failures.append("camera did not pass 24-hour automatic stream recovery")
    if (
        not math.isfinite(evidence.satellite_electronics_cost_usd)
        or evidence.satellite_electronics_cost_usd < 0.0
        or evidence.satellite_electronics_cost_usd >= 200.0
    ):
        failures.append("satellite electronics cost is not below $200")
    return CameraQualificationResult(qualified=not failures, failures=tuple(failures))
