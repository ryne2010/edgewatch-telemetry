"""Digest-addressed OTA cache served only on the maintenance network."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from agent.local_ota import OtaError, ReleaseManifest
from telegram_controller.config import ArtifactCacheConfig


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RANGE = re.compile(r"bytes=([0-9]+)-([0-9]*)\Z")


class ArtifactCacheError(RuntimeError):
    """A terminal cache or manifest error."""


class RetryableArtifactCacheError(ArtifactCacheError):
    """A transient origin or local-storage failure."""


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        source = _origin(req.full_url)
        target = _origin(newurl)
        if source[0] == "https" and target[0] != "https":
            raise urllib.error.URLError("HTTPS redirect downgrade is forbidden")
        if source != target:
            raise urllib.error.URLError("cross-origin redirect is forbidden")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        max_connections: int,
        socket_timeout_s: int,
    ) -> None:
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        self._socket_timeout_s = socket_timeout_s
        super().__init__(server_address, handler)

    def get_request(self) -> tuple[Any, Any]:
        request, address = super().get_request()
        request.settimeout(self._socket_timeout_s)
        return request, address

    def process_request(self, request: Any, client_address: Any) -> None:
        self._connection_slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


class ArtifactCache:
    """Fetch each signed release artifact once and retain it by declared digest."""

    def __init__(
        self,
        config: ArtifactCacheConfig,
        *,
        opener: Callable[..., Any] | None = None,
        hold_acquire: Callable[[str], None] | None = None,
        hold_release: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self._opener = opener or urllib.request.build_opener(_SafeRedirectHandler()).open
        self._hold_acquire = hold_acquire
        self._hold_release = hold_release
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._capacity_guard = threading.Lock()
        self._active_downloads: dict[str, int] = {}
        self._pending_hold_releases: set[str] = set()
        self._hash_cache: dict[str, tuple[int, int, int, int, int]] = {}
        self._prepare_directory()
        with self._capacity_guard:
            self._enforce_capacity()

    def _prepare_directory(self) -> None:
        path = self.config.directory
        try:
            if path.exists() and (path.is_symlink() or not path.is_dir()):
                raise ArtifactCacheError("artifact cache path must be a real directory")
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)
        except OSError as exc:
            raise ArtifactCacheError("artifact cache directory is unavailable") from exc

    def artifact_path(self, sha256_hex: str) -> Path:
        if _SHA256.fullmatch(sha256_hex) is None:
            raise ArtifactCacheError("artifact digest is invalid")
        return self.config.directory / sha256_hex

    def ensure(self, payload: Mapping[str, Any]) -> Path:
        try:
            manifest = ReleaseManifest.from_payload(payload)
        except OtaError as exc:
            raise ArtifactCacheError("OTA manifest is invalid") from exc
        if manifest.artifact_size > self.config.max_artifact_bytes:
            raise ArtifactCacheError("OTA artifact exceeds the gateway cache limit")
        lock = self._lock_for(manifest.artifact_sha256)
        with lock:
            destination = self.artifact_path(manifest.artifact_sha256)
            self._release_pending_hold(manifest.artifact_sha256)
            if self._valid_cached(destination, manifest):
                return destination
            try:
                destination.unlink(missing_ok=True)
            except OSError as exc:
                raise RetryableArtifactCacheError("invalid cached OTA artifact could not be removed") from exc
            self._prepare_partial(destination, manifest.artifact_size)
            with self._capacity_guard:
                self._active_downloads[manifest.artifact_sha256] = manifest.artifact_size
                try:
                    self._enforce_capacity()
                except BaseException:
                    self._active_downloads.pop(manifest.artifact_sha256, None)
                    raise
            primary_error: BaseException | None = None
            try:
                self._download(manifest, destination)
                if not self._valid_cached(destination, manifest):
                    destination.unlink(missing_ok=True)
                    raise ArtifactCacheError("cached OTA artifact failed size or digest validation")
                return destination
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                with self._capacity_guard:
                    self._active_downloads.pop(manifest.artifact_sha256, None)
                    try:
                        self._enforce_capacity()
                    except ArtifactCacheError:
                        if primary_error is None:
                            raise

    def _lock_for(self, digest: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(digest, threading.Lock())

    @staticmethod
    def _prepare_partial(destination: Path, artifact_size: int) -> None:
        partial = destination.with_name(f".{destination.name}.part")
        try:
            metadata = partial.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise RetryableArtifactCacheError("partial OTA artifact is unreadable") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise ArtifactCacheError("partial OTA artifact must be a regular file")
        if metadata.st_size <= artifact_size:
            return
        try:
            partial.unlink()
            _fsync_directory(partial.parent)
        except OSError as exc:
            raise RetryableArtifactCacheError("oversized partial OTA artifact could not be removed") from exc

    def _release_pending_hold(self, digest: str) -> None:
        if digest not in self._pending_hold_releases or self._hold_release is None:
            return
        hold_name = f"ota-cache-{digest[:16]}"
        try:
            self._hold_release(hold_name)
        except Exception as exc:
            raise RetryableArtifactCacheError("LTE hold could not be released") from exc
        self._pending_hold_releases.discard(digest)

    def _valid_cached(self, path: Path, manifest: ReleaseManifest) -> bool:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RetryableArtifactCacheError("cached OTA artifact is unreadable") from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ArtifactCacheError("cached OTA artifact must be a regular file")
        if metadata.st_size != manifest.artifact_size:
            return False
        cache_key = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        with self._capacity_guard:
            if self._hash_cache.get(manifest.artifact_sha256) == cache_key:
                return True
        if _sha256(path) != manifest.artifact_sha256:
            return False
        verified = path.lstat()
        verified_key = (
            verified.st_dev,
            verified.st_ino,
            verified.st_size,
            verified.st_mtime_ns,
            verified.st_ctime_ns,
        )
        if verified_key != cache_key or path.is_symlink() or not stat.S_ISREG(verified.st_mode):
            return False
        with self._capacity_guard:
            self._hash_cache[manifest.artifact_sha256] = verified_key
        return True

    def _cache_entries(self) -> list[tuple[Path, str, os.stat_result]]:
        entries: list[tuple[Path, str, os.stat_result]] = []
        try:
            children = list(self.config.directory.iterdir())
        except OSError as exc:
            raise RetryableArtifactCacheError("artifact cache directory is unreadable") from exc
        for path in children:
            digest = path.name
            if digest.startswith(".") and digest.endswith(".part"):
                digest = digest[1:-5]
            if _SHA256.fullmatch(digest) is None:
                continue
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise RetryableArtifactCacheError("artifact cache entry is unreadable") from exc
            if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                continue
            entries.append((path, digest, metadata))
        return entries

    def _enforce_capacity(self) -> None:
        while True:
            entries = self._cache_entries()
            total_bytes = sum(metadata.st_size for _, _, metadata in entries)
            names = {path.name for path, _, _ in entries}
            reserved_bytes = 0
            reserved_objects = 0
            for digest, size in self._active_downloads.items():
                final_name = digest
                partial_name = f".{digest}.part"
                present_size = sum(
                    metadata.st_size for path, entry_digest, metadata in entries if entry_digest == digest
                )
                reserved_bytes += max(0, size - present_size)
                if final_name not in names and partial_name not in names:
                    reserved_objects += 1
            free_bytes = shutil.disk_usage(self.config.directory).free
            over_limit = (
                total_bytes + reserved_bytes > self.config.max_total_bytes
                or len(entries) + reserved_objects > self.config.max_objects
                or free_bytes - reserved_bytes < self.config.minimum_free_bytes
            )
            if not over_limit:
                return
            candidates = [entry for entry in entries if entry[1] not in self._active_downloads]
            if not candidates:
                raise RetryableArtifactCacheError("artifact cache capacity is unavailable")
            path, digest, _ = min(candidates, key=lambda entry: entry[2].st_mtime_ns)
            try:
                path.unlink()
            except OSError as exc:
                raise RetryableArtifactCacheError("artifact cache entry could not be evicted") from exc
            self._hash_cache.pop(digest, None)

    def _download(self, manifest: ReleaseManifest, destination: Path) -> None:
        partial = destination.with_name(f".{destination.name}.part")
        try:
            existing = partial.stat().st_size if partial.exists() else 0
        except OSError as exc:
            raise RetryableArtifactCacheError("partial OTA artifact is unreadable") from exc
        if existing > manifest.artifact_size:
            partial.unlink(missing_ok=True)
            existing = 0
        request = urllib.request.Request(
            manifest.artifact_uri,
            headers={"Range": f"bytes={existing}-"} if existing else {},
        )
        hold_name = f"ota-cache-{manifest.artifact_sha256[:16]}"
        if self._hold_acquire is not None:
            self._hold_acquire(hold_name)
        primary_error: BaseException | None = None
        try:
            try:
                response = self._opener(request, timeout=self.config.download_timeout_s)
            except (OSError, urllib.error.URLError) as exc:
                raise RetryableArtifactCacheError("OTA origin download failed") from exc
            with response:
                final_url = response.geturl() if hasattr(response, "geturl") else request.full_url
                source_origin = _origin(request.full_url)
                final_origin = _origin(final_url)
                if source_origin[0] == "https" and final_origin[0] != "https":
                    raise ArtifactCacheError("OTA origin redirected from HTTPS")
                if source_origin != final_origin:
                    raise ArtifactCacheError("OTA origin redirected to another host")
                if existing and getattr(response, "status", None) != HTTPStatus.PARTIAL_CONTENT:
                    partial.unlink(missing_ok=True)
                    existing = 0
                mode = "ab" if existing else "wb"
                with partial.open(mode) as output:
                    os.chmod(partial, 0o600)
                    self._copy_bounded(response, output, manifest.artifact_size - existing)
            if partial.stat().st_size != manifest.artifact_size:
                raise RetryableArtifactCacheError("OTA origin download was incomplete")
            if _sha256(partial) != manifest.artifact_sha256:
                partial.unlink(missing_ok=True)
                raise ArtifactCacheError("OTA origin artifact digest did not match its manifest")
            os.replace(partial, destination)
            os.chmod(destination, 0o600)
            _fsync_directory(destination.parent)
        except ArtifactCacheError as exc:
            primary_error = exc
            raise
        except OSError as exc:
            primary_error = exc
            raise RetryableArtifactCacheError("OTA artifact could not be stored") from exc
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            if self._hold_release is not None:
                try:
                    self._hold_release(hold_name)
                except Exception as exc:
                    self._pending_hold_releases.add(manifest.artifact_sha256)
                    if primary_error is None:
                        raise RetryableArtifactCacheError("LTE hold could not be released") from exc
                else:
                    self._pending_hold_releases.discard(manifest.artifact_sha256)

    @staticmethod
    def _copy_bounded(source: Any, output: Any, remaining: int) -> None:
        copied = 0
        while copied < remaining:
            chunk = source.read(min(1024 * 1024, remaining - copied + 1))
            if not chunk:
                break
            copied += len(chunk)
            if copied > remaining:
                raise ArtifactCacheError("OTA origin exceeded its declared artifact size")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())


class ArtifactCacheServer:
    """Serve only exact SHA-256 cache objects; no directory listings or uploads."""

    def __init__(self, cache: ArtifactCache) -> None:
        self.cache = cache
        handler = _handler_for(cache)
        try:
            self._server = _BoundedThreadingHTTPServer(
                (cache.config.bind_host, cache.config.port),
                handler,
                max_connections=cache.config.http_max_connections,
                socket_timeout_s=cache.config.http_socket_timeout_s,
            )
        except OSError as exc:
            raise ArtifactCacheError("artifact cache could not bind its maintenance address") from exc
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise ArtifactCacheError("artifact cache server is already running")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="edgewatch-artifact-cache",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        self._thread = None


def _handler_for(cache: ArtifactCache) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "EdgeWatchArtifactCache/1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._serve(include_body=True)

        def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._serve(include_body=False)

        def _serve(self, *, include_body: bool) -> None:
            prefix = "/artifacts/"
            digest = self.path[len(prefix) :] if self.path.startswith(prefix) else ""
            if _SHA256.fullmatch(digest) is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                path = cache.artifact_path(digest)
                metadata = path.lstat()
            except (ArtifactCacheError, OSError):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            start, end = 0, metadata.st_size - 1
            range_header = self.headers.get("Range")
            if range_header:
                match = _RANGE.fullmatch(range_header)
                if match is None:
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
                start = int(match.group(1))
                requested_end = int(match.group(2)) if match.group(2) else end
                end = min(requested_end, end)
                if start > end:
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Range", f"bytes {start}-{end}/{metadata.st_size}")
            else:
                self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "private, immutable")
            self.end_headers()
            if not include_body:
                return
            try:
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = source.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def log_message(self, _format: str, *args: object) -> None:
            del args

    return Handler
