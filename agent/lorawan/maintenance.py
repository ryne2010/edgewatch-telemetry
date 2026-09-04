from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable

from .chirpstack import ChirpStackUplink
from .config import DeviceIdentity, DeviceRegistry, IdentityConfigError
from .protocol import HealthFlag, ProtocolError, command_token, encode_wake
from .store import GatewayStore, StoreConflictError, WakeRecord


class WakeRequestError(ValueError):
    """Raised when maintenance wake intent cannot be represented safely."""


@dataclass(frozen=True)
class WakeHandlingResult:
    ready_command_ids: tuple[str, ...] = ()
    published_command_id: str | None = None
    publish_deferred: bool = False


WakePublisher = Callable[[DeviceIdentity, bytes, int], bool]


class MaintenanceWakeCoordinator:
    """Durable Class A coordinator for the authenticated maintenance-wake operation."""

    def __init__(
        self,
        registry: DeviceRegistry,
        store: GatewayStore,
        publisher: WakePublisher,
        *,
        worker_id: str = "maintenance-wake",
        publish_lease_s: int = 30,
        publish_retry_s: int = 60,
    ) -> None:
        if not 1 <= publish_lease_s <= 300:
            raise WakeRequestError("publish_lease_s must be from 1 through 300")
        if not 1 <= publish_retry_s <= 3_600:
            raise WakeRequestError("publish_retry_s must be from 1 through 3600")
        if (
            not isinstance(worker_id, str)
            or not 1 <= len(worker_id) <= 64
            or any(not (char.isalnum() or char in "_.:-") for char in worker_id)
        ):
            raise WakeRequestError("worker_id must use 1..64 safe identifier characters")
        self.registry = registry
        self.store = store
        self.publisher = publisher
        self.worker_id = worker_id
        self.publish_lease_s = publish_lease_s
        self.publish_retry_s = publish_retry_s

    def request_wake(
        self,
        command_id: str,
        device_id: str,
        *,
        expires_at: int,
        readiness_timeout_s: int = 300,
        now: int | None = None,
        nonce: int | None = None,
    ) -> WakeRecord:
        """Persist wake intent before any radio action; replay returns the same record."""

        issued_at = int(time.time()) if now is None else now
        if isinstance(issued_at, bool) or not isinstance(issued_at, int) or issued_at < 0:
            raise WakeRequestError("now must be a non-negative integer")
        if isinstance(expires_at, bool) or not isinstance(expires_at, int):
            raise WakeRequestError("expires_at must be an integer")
        if (
            isinstance(readiness_timeout_s, bool)
            or not isinstance(readiness_timeout_s, int)
            or not 5 <= readiness_timeout_s <= 3_600
        ):
            raise WakeRequestError("readiness_timeout_s must be from 5 through 3600")
        try:
            identity = self.registry.by_device_id(device_id)
        except IdentityConfigError as exc:
            raise WakeRequestError("wake target is not present in the closed inventory") from exc

        existing = self.store.get_wake(command_id)
        if existing is not None:
            if (
                existing.device_id != device_id
                or existing.expires_at != expires_at
                or existing.readiness_timeout_s != readiness_timeout_s
            ):
                raise StoreConflictError("command_id was reused with different wake intent")
            return existing

        if not issued_at + 60 <= expires_at <= issued_at + 86_400:
            raise WakeRequestError("wake lifetime must be from 60 seconds through 24 hours")

        wake_nonce = secrets.randbits(32) if nonce is None else nonce
        try:
            payload = encode_wake(
                command_id=command_id,
                expires_at=expires_at,
                nonce=wake_nonce,
                readiness_timeout_s=readiness_timeout_s,
                key=identity.wake_key_bytes,
            )
        except ProtocolError as exc:
            raise WakeRequestError(str(exc)) from exc
        try:
            self.store.create_wake(
                command_id=command_id,
                command_token=command_token(command_id),
                device_id=device_id,
                dev_eui=identity.dev_eui,
                issued_at=issued_at,
                expires_at=expires_at,
                readiness_timeout_s=readiness_timeout_s,
                nonce=wake_nonce,
                payload=payload,
            )
        except StoreConflictError:
            concurrent = self.store.get_wake(command_id)
            if (
                concurrent is not None
                and concurrent.device_id == device_id
                and concurrent.expires_at == expires_at
                and concurrent.readiness_timeout_s == readiness_timeout_s
            ):
                return concurrent
            raise
        created = self.store.get_wake(command_id)
        if created is None:  # defensive: a committed insert must be immediately readable
            raise RuntimeError("wake request was not durably persisted")
        return created

    def handle_uplink(
        self,
        uplink: ChirpStackUplink,
        *,
        now: int | None = None,
    ) -> WakeHandlingResult:
        """Use an uplink as the Class A downlink opportunity and readiness receipt."""

        timestamp = int(time.time()) if now is None else now
        identity = self.registry.by_dev_eui(uplink.dev_eui)
        if uplink.device_id != identity.device_id or uplink.application_id != identity.application_id:
            raise WakeRequestError("uplink identity does not match the closed inventory")
        ready_ids: tuple[str, ...] = ()
        if uplink.frame.flags & HealthFlag.MAINTENANCE_READY:
            ready_ids = self.store.mark_device_ready(
                uplink.dev_eui,
                uplink.frame.model_digest,
                now=timestamp,
            )

        wake = self.store.claim_wake_for_uplink(
            uplink.dev_eui,
            self.worker_id,
            now=timestamp,
            lease_s=self.publish_lease_s,
        )
        if wake is None:
            return WakeHandlingResult(ready_command_ids=ready_ids)

        try:
            published = self.publisher(identity, wake.payload, timestamp)
        except Exception:
            published = False
        if not published:
            self.store.retry_wake_publish(
                wake.command_id,
                self.worker_id,
                failure_code="mqtt_publish_failed",
                retry_after_s=self.publish_retry_s,
                now=timestamp,
            )
            return WakeHandlingResult(ready_command_ids=ready_ids, publish_deferred=True)
        if not self.store.mark_wake_published(wake.command_id, self.worker_id, now=timestamp):
            raise RuntimeError("wake publish lease was lost before the result could be committed")
        return WakeHandlingResult(
            ready_command_ids=ready_ids,
            published_command_id=wake.command_id,
        )

    def expire(self, *, now: int | None = None) -> int:
        return self.store.expire_wakes(now=now)
