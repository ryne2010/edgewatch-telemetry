from __future__ import annotations

import base64
import hashlib
import io
import os
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway_runtime.artifact_cache import (
    ArtifactCache,
    ArtifactCacheError,
    ArtifactCacheServer,
    RetryableArtifactCacheError,
)
from telegram_controller.config import ArtifactCacheConfig


class Response(io.BytesIO):
    def __init__(self, value: bytes, status: int = 200) -> None:
        super().__init__(value)
        self.status = status


def _manifest(payload: bytes) -> dict[str, object]:
    return {
        "version": "1.2.3",
        "git_tag": "v1.2.3",
        "commit_sha": "a" * 40,
        "update_type": "asset_bundle",
        "artifact_uri": "https://updates.example.invalid/model.tar",
        "artifact_size": len(payload),
        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
        "artifact_signature": base64.b64encode(b"artifact-signature").decode(),
        "artifact_signature_scheme": "openssl_rsa_sha256",
        "signature_key_id": "release",
        "runtime_dependency_sha256": "b" * 64,
        "compatibility": {
            "schema_version": 1,
            "hardware_models": ["raspberry-pi-zero-2"],
            "release_channel": "stable",
            "minimum_python_version": "3.11.0",
            "minimum_runtime_schema": 1,
            "minimum_ota_schema": 1,
            "requires_stable_power": True,
            "requires_apply_enabled": True,
            "minimum_free_bytes": 0,
        },
        "manifest_signature": base64.b64encode(b"manifest-signature").decode(),
    }


def _config(tmp_path: Path, *, port: int = 8091) -> ArtifactCacheConfig:
    return ArtifactCacheConfig(tmp_path / "cache", "127.0.0.1", port, download_timeout_s=5)


def test_gateway_downloads_a_digest_once_and_holds_lte(tmp_path: Path) -> None:
    payload = b"signed model bundle"
    calls: list[urllib.request.Request] = []
    holds: list[tuple[str, str]] = []

    def open_once(request: urllib.request.Request, **_kwargs: object) -> Response:
        calls.append(request)
        return Response(payload)

    cache = ArtifactCache(
        _config(tmp_path),
        opener=open_once,
        hold_acquire=lambda name: holds.append(("acquire", name)),
        hold_release=lambda name: holds.append(("release", name)),
    )

    first = cache.ensure(_manifest(payload))
    second = cache.ensure(_manifest(payload))

    assert first == second
    assert first.read_bytes() == payload
    assert len(calls) == 1
    assert calls[0].full_url == "https://updates.example.invalid/model.tar"
    assert [kind for kind, _ in holds] == ["acquire", "release"]
    assert os.stat(first).st_mode & 0o777 == 0o600


def test_gateway_resumes_partial_download_and_rejects_wrong_digest(tmp_path: Path) -> None:
    payload = b"0123456789"
    manifest = _manifest(payload)
    digest = str(manifest["artifact_sha256"])
    partial = _config(tmp_path).directory / f".{digest}.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(payload[:4])
    seen_headers: list[dict[str, str]] = []

    def resume(request: urllib.request.Request, **_kwargs: object) -> Response:
        seen_headers.append(dict(request.header_items()))
        return Response(payload[4:], status=206)

    cache = ArtifactCache(_config(tmp_path), opener=resume)
    assert cache.ensure(manifest).read_bytes() == payload
    assert seen_headers == [{"Range": "bytes=4-"}]

    bad = dict(manifest)
    bad["artifact_sha256"] = "0" * 64
    with pytest.raises(ArtifactCacheError, match="digest"):
        ArtifactCache(_config(tmp_path / "bad"), opener=lambda *_a, **_k: Response(payload)).ensure(bad)


def test_gateway_removes_oversized_partial_before_capacity_reservation(tmp_path: Path) -> None:
    payload = b"payload"
    manifest = _manifest(payload)
    config = replace(
        _config(tmp_path),
        max_total_bytes=len(payload),
        max_objects=1,
        minimum_free_bytes=0,
    )
    requests: list[urllib.request.Request] = []

    def redownload(request: urllib.request.Request, **_kwargs: object) -> Response:
        requests.append(request)
        return Response(payload)

    cache = ArtifactCache(config, opener=redownload)
    digest = str(manifest["artifact_sha256"])
    partial = config.directory / f".{digest}.part"
    partial.write_bytes(b"stale-partial")

    assert cache.ensure(manifest).read_bytes() == payload
    assert len(b"stale-partial") > config.max_total_bytes
    assert requests[0].get_header("Range") is None
    assert not partial.exists()


def test_cache_server_has_no_listing_and_supports_bounded_ranges(tmp_path: Path) -> None:
    payload = b"abcdefghijklmnopqrstuvwxyz"
    cache = ArtifactCache(_config(tmp_path, port=0), opener=lambda *_a, **_k: Response(payload))
    path = cache.ensure(_manifest(payload))
    server = ArtifactCacheServer(cache)
    port = server._server.server_port
    server.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
        assert missing.value.code == 404

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/artifacts/{path.name}",
            headers={"Range": "bytes=5-9"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 206
            assert response.read() == payload[5:10]
            assert response.headers["Content-Range"] == f"bytes 5-9/{len(payload)}"
    finally:
        server.stop()


def test_cache_failure_releases_lte_hold(tmp_path: Path) -> None:
    released: list[str] = []

    def fail(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise urllib.error.URLError("offline")

    cache = ArtifactCache(
        _config(tmp_path),
        opener=fail,
        hold_acquire=lambda _name: None,
        hold_release=released.append,
    )
    with pytest.raises(ArtifactCacheError, match="download"):
        cache.ensure(_manifest(b"payload"))
    assert len(released) == 1


def test_cache_evicts_oldest_object_to_enforce_fleet_limits(tmp_path: Path) -> None:
    first_payload = b"first"
    second_payload = b"other"
    config = replace(
        _config(tmp_path),
        max_total_bytes=len(first_payload),
        max_objects=1,
        minimum_free_bytes=0,
    )
    payloads = iter((first_payload, second_payload))
    cache = ArtifactCache(config, opener=lambda *_a, **_k: Response(next(payloads)))

    first = cache.ensure(_manifest(first_payload))
    second = cache.ensure(_manifest(second_payload))

    assert not first.exists()
    assert second.read_bytes() == second_payload


def test_cache_never_evicts_an_active_download(tmp_path: Path) -> None:
    config = replace(_config(tmp_path), max_total_bytes=8, max_objects=2, minimum_free_bytes=0)
    cache = ArtifactCache(config)
    active_digest = "a" * 64
    idle_digest = "b" * 64
    cache.artifact_path(active_digest).write_bytes(b"aaaa")
    cache.artifact_path(idle_digest).write_bytes(b"bbbb")
    object.__setattr__(config, "max_total_bytes", 4)
    cache._active_downloads[active_digest] = 4

    with cache._capacity_guard:
        cache._enforce_capacity()

    assert cache.artifact_path(active_digest).exists()
    assert not cache.artifact_path(idle_digest).exists()


def test_cache_reuses_safe_hash_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = b"signed model bundle"
    import gateway_runtime.artifact_cache as cache_module

    original = cache_module._sha256
    hashes: list[Path] = []

    def counted(path: Path) -> str:
        hashes.append(path)
        return original(path)

    monkeypatch.setattr(cache_module, "_sha256", counted)
    cache = ArtifactCache(_config(tmp_path), opener=lambda *_a, **_k: Response(payload))
    cache.ensure(_manifest(payload))
    initial_hashes = len(hashes)
    cache.ensure(_manifest(payload))

    assert len(hashes) == initial_hashes


def test_hold_release_failure_is_retryable_without_masking_download_error(tmp_path: Path) -> None:
    def release_failure(_name: str) -> None:
        raise OSError("release failed")

    cache = ArtifactCache(
        _config(tmp_path),
        opener=lambda *_a, **_k: Response(b"payload"),
        hold_acquire=lambda _name: None,
        hold_release=release_failure,
    )
    with pytest.raises(RetryableArtifactCacheError, match="hold could not be released"):
        cache.ensure(_manifest(b"payload"))

    def download_failure(*_args: object, **_kwargs: object) -> Response:
        raise urllib.error.URLError("offline")

    cache = ArtifactCache(
        _config(tmp_path / "primary"),
        opener=download_failure,
        hold_acquire=lambda _name: None,
        hold_release=release_failure,
    )
    with pytest.raises(RetryableArtifactCacheError, match="origin download failed"):
        cache.ensure(_manifest(b"payload"))


@pytest.mark.parametrize(
    "redirect_url",
    ["http://updates.example.invalid/model.tar", "https://cdn.example.invalid/model.tar"],
)
def test_cache_rejects_https_downgrade_and_cross_host_redirects(tmp_path: Path, redirect_url: str) -> None:
    class RedirectedResponse(Response):
        def geturl(self) -> str:
            return redirect_url

    cache = ArtifactCache(_config(tmp_path), opener=lambda *_a, **_k: RedirectedResponse(b"payload"))
    with pytest.raises(ArtifactCacheError, match="redirect"):
        cache.ensure(_manifest(b"payload"))
