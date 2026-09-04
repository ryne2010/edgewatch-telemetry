from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import ceil
from typing import Any, Protocol

from agent.local_ota import OtaError, ReleaseCatalog, ReleaseManifest

from .config import ControllerConfig
from .models import DispatchEnvelope, DispatchResult, Role
from .ota import OtaDispatchCommand, OtaOrchestrator
from .parser import Command, CommandParseError, parse_command
from .presentation import ReplyState, operation_subsystem, render_control_text
from .rbac import AuthorizationError, authorize
from .store import ConfirmationError, ControllerStore


class DeviceDispatcher(Protocol):
    def dispatch(self, envelope: DispatchEnvelope) -> DispatchResult: ...


class ControllerService:
    def __init__(
        self,
        config: ControllerConfig,
        store: ControllerStore,
        dispatcher: DeviceDispatcher,
        *,
        clock=time.time,
        sleeper=time.sleep,
        dispatch_attempts: int = 3,
    ):
        self.config = config
        self.store = store
        self.dispatcher = dispatcher
        self.clock = clock
        self.sleeper = sleeper
        self.dispatch_attempts = dispatch_attempts
        self.ota_catalog = None if config.ota is None else ReleaseCatalog.load(config.ota.catalog_file)

    def handle_update(self, update: dict[str, Any]) -> bool:
        update_id = update.get("update_id")
        if not isinstance(update_id, int) or self.store.is_update_processed(update_id):
            return False
        message = update.get("message")
        if not isinstance(message, dict):
            self.store.mark_update_processed(update_id, self._now())
            return True
        chat = message.get("chat", {})
        sender = message.get("from", {})
        text_raw = message.get("text")
        text = text_raw if isinstance(text_raw, str) else ""
        chat_id = str(chat.get("id")) if isinstance(chat, dict) and isinstance(chat.get("id"), int) else ""
        user_id = (
            str(sender.get("id")) if isinstance(sender, dict) and isinstance(sender.get("id"), int) else ""
        )
        topic_raw = message.get("message_thread_id")
        topic_id = str(topic_raw) if isinstance(topic_raw, int) else None
        try:
            command = parse_command(text)
            authorize(self.config, user_id, chat_id, topic_id, command)
            replies = self._accept(update_id, user_id, chat_id, topic_id, command)
        except (CommandParseError, AuthorizationError, ConfirmationError, OtaError, ValueError) as exc:
            replies = (render_control_text(f"Rejected: {exc}", state="failed"),)
        if chat_id:
            self.store.enqueue_reply_group(chat_id, topic_id, replies, self._now())
        self.store.mark_update_processed(update_id, self._now())
        return True

    def _accept(
        self, update_id: int, user_id: str, chat_id: str, topic_id: str | None, command: Command
    ) -> tuple[str, ...]:
        if command.operation == "confirm":
            confirmation_id = command.confirmation_id or ""
            stored = self.store.inspect_confirmation(confirmation_id, user_id, chat_id, topic_id, self._now())
            if stored["target"] != command.target:
                raise ConfirmationError("confirmation target does not match")
            replay = Command(
                stored["scope"],
                stored["target"],
                stored["operation"],
                stored["arguments"],
                self._required_role(stored["operation"], stored["arguments"]),
                True,
            )
            authorize(self.config, user_id, chat_id, topic_id, replay)
            command_id = self.store.consume_confirmation(
                confirmation_id, user_id, chat_id, topic_id, self._now()
            )
            return (
                render_control_text(
                    f"Command confirmed and queued: {command_id}.",
                    state="queued",
                    subsystem=operation_subsystem(str(stored["operation"])),
                ),
            )
        existing = self.store.get_command_by_update(update_id)
        if existing is not None:
            if existing["status"] == "preview":
                confirmation_id = self.store.get_confirmation_for_command(existing["command_id"])
                if confirmation_id is None:
                    preview = existing.get("preview")
                    if not isinstance(preview, dict):
                        raise ConfirmationError("confirmation preview is missing")
                    confirmation_id = self.store.create_confirmation(
                        existing["command_id"],
                        user_id,
                        chat_id,
                        topic_id,
                        int(preview["confirmation_expires_at"]),
                        self._now(),
                    )
                return self._render_preview(existing, confirmation_id)
            return (
                render_control_text(
                    f"Command already queued: {existing['command_id']}.",
                    state="queued",
                    subsystem=operation_subsystem(str(existing["operation"])),
                ),
            )
        if command.scope == "fleet" and command.operation == "ota_status":
            now = self._now()
            dispatch_policy = self._dispatch_policy(())
            command_expires_at = now + ceil(float(dispatch_policy["max_dispatch_duration_s"]))
            preview = {
                "schema_version": 1,
                "scope": command.scope,
                "target": command.target,
                "operation": command.operation,
                "arguments": dict(command.arguments),
                "eligible_device_ids": [],
                "excluded_devices": [],
                "ota_canary_device_ids": [],
                "confirmation_expires_at": now,
                "command_expires_at": command_expires_at,
                "dispatch_policy": dispatch_policy,
            }
            command_id = self.store.create_command(
                update_id=update_id,
                actor_id=user_id,
                chat_id=chat_id,
                topic_id=topic_id,
                scope=command.scope,
                target=command.target,
                operation=command.operation,
                arguments=dict(command.arguments),
                device_ids=(),
                expires_at=command_expires_at,
                status="accepted",
                preview=preview,
                dispatch_policy=dispatch_policy,
                now=now,
            )
            self.store.complete_local_command(
                command_id,
                "applied",
                render_control_text(self._ota_status(command.target), state="info", subsystem="ota"),
                now,
            )
            return ()
        device_ids, exclusions, canaries = self._resolve_preview(command)
        frozen_arguments = self._frozen_arguments(command)
        now = self._now()
        preview_required = command.scope == "fleet" and command.mutating
        confirmation_expires_at = now + self.config.confirmation_ttl_s
        dispatch_policy = self._dispatch_policy(device_ids)
        command_expires_at = (
            confirmation_expires_at + ceil(float(dispatch_policy["max_dispatch_duration_s"]))
            if preview_required
            else now + ceil(float(dispatch_policy["max_dispatch_duration_s"]))
        )
        preview = (
            {
                "schema_version": 1,
                "scope": command.scope,
                "target": command.target,
                "operation": command.operation,
                "arguments": frozen_arguments,
                "eligible_device_ids": list(device_ids),
                "excluded_devices": exclusions,
                "ota_canary_device_ids": list(canaries),
                "confirmation_expires_at": confirmation_expires_at,
                "command_expires_at": command_expires_at,
                "dispatch_policy": dispatch_policy,
            }
            if command.scope == "fleet"
            else None
        )
        command_id = self.store.create_command(
            update_id=update_id,
            actor_id=user_id,
            chat_id=chat_id,
            topic_id=topic_id,
            scope=command.scope,
            target=command.target,
            operation=command.operation,
            arguments=frozen_arguments,
            device_ids=device_ids,
            expires_at=command_expires_at,
            status="preview" if preview_required else "accepted",
            preview=preview,
            dispatch_policy=dispatch_policy,
            now=now,
        )
        if preview_required:
            confirmation_id = self.store.create_confirmation(
                command_id, user_id, chat_id, topic_id, confirmation_expires_at, now
            )
            return self._render_preview(self.store.get_command(command_id), confirmation_id)
        return (
            render_control_text(
                f"Command accepted and queued: {command_id}.",
                state="queued",
                subsystem=operation_subsystem(command.operation),
            ),
        )

    def _frozen_arguments(self, command: Command) -> dict[str, Any]:
        arguments = dict(command.arguments)
        if command.operation != "ota_stage":
            return arguments
        if self.ota_catalog is None:
            raise OtaError("OTA is not configured")
        manifest = self.ota_catalog.resolve(str(arguments["release_alias"]))
        arguments["manifest"] = manifest.to_command_payload()
        arguments["manifest_identity"] = manifest.identity
        return arguments

    def resolve_targets(self, command: Command) -> tuple[str, ...]:
        return self._resolve_preview(command)[0]

    def _resolve_preview(
        self, command: Command
    ) -> tuple[tuple[str, ...], list[dict[str, str]], tuple[str, ...]]:
        if command.scope == "device":
            device = self.config.devices.get(command.target)
            if device is None or not device.enabled:
                raise ValueError("unknown or disabled device")
            self._capability_check(device.device_id, command.operation)
            if command.operation == "shutdown" and not self.config.shutdown_enabled:
                raise ValueError("shutdown is disabled")
            return (device.device_id,), [], ()
        fleet = self.config.fleets.get(command.target)
        if fleet is None:
            raise ValueError("unknown fleet")
        if command.operation.startswith("ota_"):
            targets = self._resolve_ota_targets(command)
            canaries = tuple(device_id for device_id in fleet.canary_device_ids if device_id in targets)
            exclusions = self._fleet_exclusions(fleet.device_ids, targets, command.operation)
            return targets, exclusions, canaries
        if command.operation == "shutdown":
            raise ValueError("fleet shutdown is not supported")
        ids = tuple(
            device_id for device_id in fleet.device_ids if self._device_eligible(device_id, command.operation)
        )
        if not ids:
            raise ValueError("fleet has no eligible devices")
        return ids, self._fleet_exclusions(fleet.device_ids, ids, command.operation), ()

    def _device_eligible(self, device_id: str, operation: str) -> bool:
        device = self.config.devices[device_id]
        if not device.enabled:
            return False
        capabilities = device.capabilities
        return not capabilities or operation in capabilities or operation.split("_", 1)[0] in capabilities

    def _fleet_exclusions(
        self, inventory_ids: tuple[str, ...], eligible_ids: tuple[str, ...], operation: str
    ) -> list[dict[str, str]]:
        eligible = set(eligible_ids)
        exclusions: list[dict[str, str]] = []
        for device_id in inventory_ids:
            if device_id in eligible:
                continue
            device = self.config.devices[device_id]
            reason = "disabled" if not device.enabled else f"missing capability: {operation}"
            exclusions.append({"device_id": device_id, "reason": reason})
        return exclusions

    def _capability_check(self, device_id: str, operation: str) -> None:
        capabilities = self.config.devices[device_id].capabilities
        if capabilities and operation not in capabilities and operation.split("_", 1)[0] not in capabilities:
            raise ValueError(f"device {device_id} does not support {operation}")

    def _dispatch(self, command_id: str, *, worker_id: str, lease_s: int) -> str:
        command = self.store.get_command(command_id)
        if command.get("scope") == "fleet" and str(command["operation"]).startswith("ota_"):
            return self._dispatch_ota(command, worker_id=worker_id, lease_s=lease_s)
        if command["expires_at"] <= self._now():
            self.store.set_command_status(command_id, "expired")
            return "Command expired before dispatch."
        successes = 0
        target_rows = {row["device_id"]: row for row in self.store.get_command_targets(command_id)}
        pending: list[DispatchEnvelope] = []
        for device_id in command["device_ids"]:
            target_status = target_rows[device_id]["status"]
            if target_status == "applied":
                successes += 1
                continue
            if target_status in {"failed", "not_dispatched"}:
                continue
            pending.append(
                DispatchEnvelope(
                    version=1,
                    command_id=command_id,
                    device_id=device_id,
                    issued_at=self._rfc3339(command["created_at"]),
                    expires_at=self._rfc3339(command["expires_at"]),
                    type=command["operation"],
                    args=command["arguments"],
                )
            )
        self.store.set_command_status(command_id, "dispatching")
        accepted = 0
        workers = self._command_dispatch_workers(command)
        policy = self._command_dispatch_policy(command)
        for wave_number, start in enumerate(range(0, len(pending), workers), start=1):
            if command["expires_at"] <= self._now():
                self.store.set_command_status(command_id, "expired")
                return "Command expired between dispatch waves."
            if not self.store.renew_command_lease(command_id, worker_id, lease_s, self._now()):
                raise ValueError("dispatch lease was lost")
            wave = pending[start : start + workers]
            results = self._dispatch_envelopes(wave, workers, policy)
            for envelope in wave:
                result = results[envelope.device_id]
                target_status = "applied" if result.ok else "failed"
                if result.details.get("status") == "accepted":
                    target_status = "accepted"
                    accepted += 1
                self.store.set_target_result(
                    command_id,
                    envelope.device_id,
                    target_status,
                    {
                        "ok": result.ok,
                        "summary": result.summary,
                        "retryable": result.retryable,
                        "details": dict(result.details),
                    },
                )
                successes += int(result.ok)
            completed = min(start + len(wave), len(pending))
            self.store.enqueue_command_progress(
                command_id,
                f"wave-{wave_number}",
                render_control_text(
                    f"{command['operation']}: dispatch wave {wave_number} complete "
                    f"({completed}/{len(pending)} pending target(s)).",
                    state="queued",
                    subsystem=operation_subsystem(str(command["operation"])),
                ),
                self._now(),
            )
        status = (
            "applied"
            if successes == len(command["device_ids"])
            else ("dispatching" if accepted else "failed")
        )
        self.store.set_command_status(command_id, status)
        failed = len(command["device_ids"]) - successes - accepted
        return (
            f"{command['operation']}: {successes}/{len(command['device_ids'])} target(s) applied; "
            f"{accepted} accepted/pending; {failed} failed."
        )

    def dispatch_once(self, worker_id: str | None = None) -> bool:
        """Claim and execute one durable command outside the Telegram update loop."""
        owner = worker_id or f"worker-{uuid.uuid4()}"
        lease_s = self._lease_duration_s()
        command = self.store.claim_next_command(owner, lease_s, self._now())
        if command is None:
            self.store.reconcile_completion_replies(self._now())
            return False
        command_id = str(command["command_id"])
        try:
            existing_status = str(command["status"])
            if existing_status in {"applied", "failed", "expired", "aborted"}:
                self.store.complete_command(
                    command_id,
                    owner,
                    existing_status,
                    self._completion_reply(
                        self._reconciled_summary(command),
                        existing_status,
                        str(command["operation"]),
                        command,
                    ),
                    self._now(),
                )
                return True
            if int(command["expires_at"]) <= self._now():
                self.store.complete_command(
                    command_id,
                    owner,
                    "expired",
                    self._completion_reply(
                        "Command expired before dispatch.",
                        "expired",
                        str(command["operation"]),
                        command,
                    ),
                    self._now(),
                )
                return True
            summary = self._dispatch(command_id, worker_id=owner, lease_s=lease_s)
            terminal = str(self.store.get_command(command_id)["status"])
            if terminal in {"applied", "failed", "expired", "aborted"}:
                self.store.complete_command(
                    command_id,
                    owner,
                    terminal,
                    self._completion_reply(summary, terminal, str(command["operation"]), command),
                    self._now(),
                )
            else:
                poll_interval = int(self._command_dispatch_policy(command)["accepted_poll_interval_s"])
                self.store.defer_command(
                    command_id,
                    owner,
                    self._now() + poll_interval,
                )
        except (ConfirmationError, OtaError, ValueError) as exc:
            self.store.complete_command(
                command_id,
                owner,
                "failed",
                self._completion_reply(
                    f"Command failed: {exc}", "failed", str(command["operation"]), command
                ),
                self._now(),
            )
        except BaseException:
            # The lease is intentionally retained. A restarted worker reclaims
            # it after expiry and replays the stable per-device command IDs.
            raise
        return True

    def _reconciled_summary(self, command: dict[str, Any]) -> str:
        status = str(command["status"])
        if status == "expired":
            return "Command expired before dispatch completed."
        if command.get("scope") == "fleet" and str(command["operation"]).startswith("ota_"):
            orchestrator = self._ota_orchestrator(str(command["target"]))
            return self._ota_dispatch_summary(orchestrator, command)
        targets = self.store.get_command_targets(str(command["command_id"]))
        successes = sum(row["status"] == "applied" for row in targets)
        accepted = sum(row["status"] == "accepted" for row in targets)
        failed = len(targets) - successes - accepted
        return (
            f"{command['operation']}: {successes}/{len(targets)} target(s) applied; "
            f"{accepted} accepted/pending; {failed} failed."
        )

    def resume_pending(self) -> None:
        owner = f"resume-{uuid.uuid4()}"
        while self.dispatch_once(owner):
            pass

    def resume_pending_commands(self) -> None:
        """Compatibility alias for callers created with the initial controller prototype."""
        self.resume_pending()

    def _resolve_ota_targets(self, command: Command) -> tuple[str, ...]:
        fleet = self.config.fleets[command.target]
        orchestrator = self._ota_orchestrator(
            command.target, fresh_if_terminal=command.operation == "ota_stage"
        )
        if command.operation == "ota_stage":
            if orchestrator.snapshot()["status"] not in {"idle", "aborted", "complete"}:
                raise OtaError("an OTA deployment is already active")
            release_alias = str(command.arguments["release_alias"])
            orchestrator.catalog.resolve(release_alias)
            targets = tuple(
                sorted(
                    device_id
                    for device_id in fleet.device_ids
                    if self._device_eligible(device_id, command.operation)
                )
            )
            if not targets:
                raise OtaError("fleet has no eligible OTA devices")
            if not set(fleet.canary_device_ids) & set(targets):
                raise OtaError("the frozen target set contains no configured canaries")
        elif command.operation == "ota_canary":
            targets = self._ota_preview_targets(
                orchestrator,
                "canary",
                str(command.arguments["deployment_id"]),
                command.target,
            )
        elif command.operation == "ota_promote":
            targets = self._ota_preview_targets(
                orchestrator,
                "promote",
                str(command.arguments["deployment_id"]),
                command.target,
            )
        elif command.operation == "ota_abort":
            deployment_id = str(command.arguments["deployment_id"])
            probe = OtaOrchestrator.from_snapshot(orchestrator.catalog, orchestrator.snapshot())
            probe.abort(deployment_id)
            targets = tuple(orchestrator.snapshot().get("targets", ()))
        else:
            raise OtaError("unsupported controller OTA operation")
        if command.operation == "ota_abort":
            return tuple(sorted(targets))
        for device_id in targets:
            device = self.config.devices.get(device_id)
            if device is None or not device.enabled:
                raise OtaError(f"frozen OTA target {device_id} is unavailable")
            self._capability_check(device_id, command.operation)
        return tuple(sorted(targets))

    def _ota_preview_targets(
        self,
        orchestrator: OtaOrchestrator,
        action: str,
        deployment_id: str,
        fleet_id: str,
    ) -> tuple[str, ...]:
        try:
            if action == "canary":
                return orchestrator.preview_canary_device_ids(deployment_id)
            return orchestrator.preview_promote_device_ids(deployment_id)
        except OtaError:
            # Gate evaluation can halt a deployment. Preserve that transition
            # even though the requested preview is rejected.
            self._save_ota_orchestrator(fleet_id, orchestrator)
            raise

    def _dispatch_ota(self, command: dict[str, Any], *, worker_id: str, lease_s: int) -> str:
        command_id = str(command["command_id"])
        if int(command["expires_at"]) <= self._now():
            self.store.set_command_status(command_id, "expired")
            return "Command expired before dispatch."
        orchestrator = self._ota_orchestrator(
            str(command["target"]), fresh_if_terminal=command["operation"] == "ota_stage"
        )
        if command["status"] == "confirmed":
            try:
                emitted = self._transition_ota(orchestrator, command)
            except OtaError:
                self.store.set_state_and_command_status(
                    self._ota_state_key(str(command["target"])),
                    orchestrator.snapshot(),
                    command_id,
                    "failed",
                    self._now(),
                )
                raise
            self.store.set_state_and_command_status(
                self._ota_state_key(str(command["target"])),
                orchestrator.snapshot(),
                command_id,
                "dispatching",
                self._now(),
            )
        elif command["status"] == "dispatching":
            emitted = self._rebuild_ota_commands(orchestrator, command)
        elif command["status"] in {"applied", "failed", "expired", "aborted"}:
            return self._ota_dispatch_summary(orchestrator, command)
        else:
            raise OtaError("OTA command is not confirmed for dispatch")

        if command["operation"] == "ota_abort":
            for device_id in command["device_ids"]:
                self.store.set_target_result(
                    command_id,
                    device_id,
                    "not_dispatched",
                    {
                        "ok": True,
                        "summary": "deployment aborted before additional rollout dispatch",
                        "retryable": False,
                        "details": {},
                    },
                )
            self.store.set_command_status(command_id, "applied")
            return self._ota_dispatch_summary(orchestrator, command, successes=0)

        expected = tuple(sorted(str(value) for value in command["device_ids"]))
        if tuple(sorted(item.device_id for item in emitted)) != expected:
            self.store.set_command_status(command_id, "failed")
            raise OtaError("OTA confirmation targets are stale")
        target_rows = {row["device_id"]: row for row in self.store.get_command_targets(command_id)}
        successes = 0
        pending_items: list[tuple[OtaDispatchCommand, DispatchEnvelope]] = []
        for item in emitted:
            target_status = target_rows[item.device_id]["status"]
            if target_status == "applied":
                successes += 1
                continue
            if target_status in {"failed", "not_dispatched"}:
                continue
            pending_items.append(
                (
                    item,
                    DispatchEnvelope(
                        version=1,
                        command_id=item.command_id,
                        device_id=item.device_id,
                        issued_at=self._rfc3339(int(command["created_at"])),
                        expires_at=self._rfc3339(int(command["expires_at"])),
                        type=item.operation,
                        args=item.arguments,
                    ),
                )
            )
        workers = self._command_dispatch_workers(command)
        policy = self._command_dispatch_policy(command)
        for wave_number, start in enumerate(range(0, len(pending_items), workers), start=1):
            if int(command["expires_at"]) <= self._now():
                self.store.set_command_status(command_id, "expired")
                return "OTA command expired between dispatch waves."
            if self._ota_abort_requested(command, orchestrator):
                self.store.set_command_status(command_id, "aborted")
                return self._ota_dispatch_summary(orchestrator, command, successes=successes)
            if not self.store.renew_command_lease(command_id, worker_id, lease_s, self._now()):
                raise OtaError("dispatch lease was lost")
            wave = pending_items[start : start + workers]
            dispatch_results = self._dispatch_envelopes([envelope for _, envelope in wave], workers, policy)
            for item, envelope in wave:
                result = dispatch_results[envelope.device_id]
                rollout_status = self._ota_result_status(item.operation, result)
                self._record_ota_result(orchestrator, item.device_id, rollout_status)
                self._save_ota_orchestrator(str(command["target"]), orchestrator)
                succeeded = (
                    rollout_status == "staged"
                    if item.operation == "ota_stage"
                    else (rollout_status in {"applied", "healthy"})
                )
                self.store.set_target_result(
                    command_id,
                    item.device_id,
                    "applied" if succeeded else "failed",
                    {
                        "ok": result.ok,
                        "summary": result.summary,
                        "retryable": result.retryable,
                        "details": dict(result.details),
                        "rollout_status": rollout_status,
                    },
                )
                successes += int(succeeded)
            self.store.enqueue_command_progress(
                command_id,
                f"wave-{wave_number}",
                render_control_text(
                    f"{command['operation']}: dispatch wave {wave_number} complete "
                    f"({min(start + len(wave), len(pending_items))}/{len(pending_items)} target(s)).",
                    state="queued",
                    subsystem="ota",
                ),
                self._now(),
            )
        final_status = "applied" if successes == len(emitted) else "failed"
        self.store.set_command_status(command_id, final_status)
        return self._ota_dispatch_summary(orchestrator, command, successes=successes)

    def _transition_ota(
        self, orchestrator: OtaOrchestrator, command: dict[str, Any]
    ) -> list[OtaDispatchCommand]:
        operation = str(command["operation"])
        arguments = command["arguments"]
        targets = tuple(str(value) for value in command["device_ids"])
        if operation == "ota_stage":
            manifest_raw = arguments.get("manifest")
            if not isinstance(manifest_raw, dict):
                raise OtaError("frozen OTA manifest is missing")
            manifest = ReleaseManifest.from_payload(manifest_raw)
            if manifest.identity != arguments.get("manifest_identity"):
                raise OtaError("frozen OTA manifest identity does not match")
            return orchestrator.stage(str(arguments["release_alias"]), targets, manifest=manifest)
        deployment_id = str(arguments["deployment_id"])
        if operation == "ota_canary":
            return orchestrator.canary(deployment_id, expected_device_ids=targets)
        if operation == "ota_promote":
            return orchestrator.promote(deployment_id, expected_device_ids=targets)
        if operation == "ota_abort":
            snapshot = orchestrator.snapshot()
            if (
                snapshot.get("status") == "aborted"
                and snapshot.get("deployment_id") == deployment_id
                and self.store.is_ota_abort_requested(str(command["target"]), deployment_id)
            ):
                return []
            return orchestrator.abort(deployment_id)
        raise OtaError("unsupported controller OTA operation")

    def _rebuild_ota_commands(
        self, orchestrator: OtaOrchestrator, command: dict[str, Any]
    ) -> list[OtaDispatchCommand]:
        snapshot = orchestrator.snapshot()
        operation = str(command["operation"])
        arguments = command["arguments"]
        targets = tuple(sorted(str(value) for value in command["device_ids"]))
        deployment_id = snapshot.get("deployment_id")
        if not isinstance(deployment_id, str):
            raise OtaError("durable OTA deployment state is missing")
        supplied_deployment = arguments.get("deployment_id")
        if supplied_deployment is not None and supplied_deployment != deployment_id:
            raise OtaError("OTA deployment ID does not match the active deployment")
        if operation == "ota_stage":
            if tuple(snapshot.get("targets", ())) != targets or snapshot.get(
                "release_alias"
            ) != arguments.get("release_alias"):
                raise OtaError("OTA confirmation targets are stale")
            ota_arguments = {
                "release_alias": snapshot["release_alias"],
                "manifest": snapshot["manifest"],
            }
        elif operation == "ota_canary":
            if (
                snapshot.get("status") not in {"canary", "complete"}
                or tuple(snapshot.get("enabled", ())) != targets
            ):
                raise OtaError("OTA confirmation targets are stale")
            ota_arguments = {
                "release_alias": snapshot["release_alias"],
                "manifest": snapshot["manifest"],
            }
        elif operation == "ota_promote":
            if snapshot.get("status") not in {"rollout", "complete"}:
                raise OtaError("durable OTA rollout phase does not match the command")
            if tuple(snapshot.get("enabled", ())) != targets and not (
                snapshot.get("status") == "complete" and not targets
            ):
                raise OtaError("OTA confirmation targets are stale")
            ota_arguments = {}
        elif operation == "ota_abort":
            if snapshot.get("status") != "aborted":
                raise OtaError("durable OTA rollout phase does not match the command")
            return []
        else:
            raise OtaError("unsupported controller OTA operation")
        return [
            OtaDispatchCommand(
                command_id=f"{deployment_id}:{operation}:{device_id}",
                device_id=device_id,
                operation=operation,
                arguments=dict(ota_arguments),
            )
            for device_id in targets
        ]

    @staticmethod
    def _record_ota_result(orchestrator: OtaOrchestrator, device_id: str, rollout_status: str) -> None:
        snapshot = orchestrator.snapshot()
        result_key = "stage_results" if snapshot.get("status") == "staging" else "results"
        existing = snapshot.get(result_key, {}).get(device_id)
        if existing is not None:
            if existing != rollout_status:
                raise OtaError("replayed OTA result does not match durable state")
            return
        orchestrator.record_result(device_id, rollout_status)

    @staticmethod
    def _ota_result_status(operation: str, result: DispatchResult) -> str:
        inner = result.details.get("result")
        if isinstance(inner, dict):
            status = inner.get("status")
            if status in {"staged", "applied", "healthy", "failed", "deferred", "rolled_back"}:
                return str(status)
        if not result.ok:
            return "failed"
        return "staged" if operation == "ota_stage" else "applied"

    def _ota_orchestrator(self, fleet_id: str, *, fresh_if_terminal: bool = False) -> OtaOrchestrator:
        ota_config = self.config.ota
        catalog = self.ota_catalog
        if ota_config is None or catalog is None:
            raise OtaError("OTA control is not configured")
        fleet = self.config.fleets.get(fleet_id)
        if fleet is None:
            raise OtaError("unknown OTA fleet")
        snapshot = self.store.get_state(self._ota_state_key(fleet_id))
        if snapshot is not None and not (
            fresh_if_terminal and snapshot.get("status") in {"aborted", "complete"}
        ):
            return OtaOrchestrator.from_snapshot(catalog, snapshot)
        return OtaOrchestrator(
            catalog,
            canary_device_ids=fleet.canary_device_ids,
            rollout_percentages=ota_config.rollout_percentages,
            failure_rate_threshold=ota_config.failure_rate_threshold,
            defer_rate_threshold=ota_config.defer_rate_threshold,
        )

    def _save_ota_orchestrator(self, fleet_id: str, orchestrator: OtaOrchestrator) -> None:
        self.store.set_state(self._ota_state_key(fleet_id), orchestrator.snapshot(), self._now())

    def _ota_status(self, fleet_id: str) -> str:
        orchestrator = self._ota_orchestrator(fleet_id)
        snapshot = orchestrator.snapshot()
        if snapshot["status"] == "idle":
            return f"OTA {fleet_id}: idle; no active deployment."
        targets = tuple(snapshot.get("targets", ()))
        staged = snapshot.get("stage_results", {})
        results = snapshot.get("results", {})
        return (
            f"OTA {fleet_id}: {snapshot['status']}; deployment {snapshot['deployment_id']}; "
            f"release {snapshot['release_alias']}; staged {len(staged)}/{len(targets)}; "
            f"current tranche results {len(results)}/{len(snapshot.get('enabled', ()))}."
        )

    @staticmethod
    def _ota_state_key(fleet_id: str) -> str:
        return f"ota:{fleet_id}"

    @staticmethod
    def _ota_dispatch_summary(
        orchestrator: OtaOrchestrator,
        command: dict[str, Any],
        *,
        successes: int | None = None,
    ) -> str:
        snapshot = orchestrator.snapshot()
        if command["operation"] == "ota_abort":
            return (
                f"ota_abort: deployment {snapshot['deployment_id']} aborted; "
                "no device rollback was commanded."
            )
        total = len(command["device_ids"])
        applied = successes
        if applied is None:
            applied = total if command["status"] == "applied" else 0
        return (
            f"{command['operation']}: {applied}/{total} target(s) applied; "
            f"deployment {snapshot.get('deployment_id', 'unavailable')}."
        )

    def _dispatch_policy(self, device_ids: tuple[str, ...]) -> dict[str, Any]:
        target_count = len(device_ids)
        workers = max(1, min(self.config.fleet_dispatch_concurrency, target_count))
        backoff = [0.25 * (2**attempt) for attempt in range(self.dispatch_attempts - 1)]
        uses_spacebridge = any(
            self.config.devices[device_id].transport == "spacebridge" for device_id in device_ids
        )
        tunnel_overhead_s = self.config.ssh.connect_timeout_s + 4 if uses_spacebridge else 0
        per_attempt_worst_case_s = self.config.ssh.command_timeout_s + tunnel_overhead_s
        per_wave_s = self.dispatch_attempts * per_attempt_worst_case_s + sum(backoff)
        completion_window_s = self.config.command_ttl_s
        return {
            "mode": "bounded_concurrency",
            "max_workers": workers,
            "attempts_per_target": self.dispatch_attempts,
            "per_attempt_timeout_s": self.config.ssh.command_timeout_s,
            "spacebridge_tunnel_connect_timeout_s": (
                self.config.ssh.connect_timeout_s if uses_spacebridge else 0
            ),
            "spacebridge_tunnel_cleanup_s": 4 if uses_spacebridge else 0,
            "per_attempt_worst_case_s": per_attempt_worst_case_s,
            "retry_backoff_s": backoff,
            "accepted_poll_interval_s": self.config.accepted_poll_interval_s,
            "accepted_completion_window_s": completion_window_s,
            "max_dispatch_duration_s": (ceil(target_count / workers) * per_wave_s + completion_window_s + 30),
        }

    def _command_dispatch_workers(self, command: dict[str, Any]) -> int:
        policy = command.get("dispatch_policy")
        if policy is None:
            raise ConfirmationError("frozen dispatch policy is missing")
        if not isinstance(policy, dict) or not isinstance(policy.get("max_workers"), int):
            raise ConfirmationError("frozen dispatch policy is missing or corrupt")
        return max(1, min(int(policy["max_workers"]), 32))

    def _command_dispatch_policy(self, command: dict[str, Any]) -> dict[str, Any]:
        policy = command.get("dispatch_policy")
        if policy is None:
            raise ConfirmationError("frozen dispatch policy is missing")
        if not isinstance(policy, dict):
            raise ConfirmationError("frozen dispatch policy is corrupt")
        return policy

    def _lease_duration_s(self) -> int:
        # A lease must cover one worst-case wave. It is renewed between waves.
        mixed_ids = tuple(self.config.devices)
        policy = self._dispatch_policy(mixed_ids)
        return max(
            30,
            ceil(
                int(policy["attempts_per_target"]) * float(policy["per_attempt_worst_case_s"])
                + sum(float(value) for value in policy["retry_backoff_s"])
                + 5
            ),
        )

    def _ota_abort_requested(self, command: dict[str, Any], orchestrator: OtaOrchestrator) -> bool:
        if command["operation"] == "ota_abort":
            return False
        snapshot = orchestrator.snapshot()
        deployment_id = snapshot.get("deployment_id")
        if not isinstance(deployment_id, str) or not self.store.is_ota_abort_requested(
            str(command["target"]), deployment_id
        ):
            return False
        if snapshot.get("status") not in {"aborted", "complete", "idle"}:
            orchestrator.abort(deployment_id)
            self._save_ota_orchestrator(str(command["target"]), orchestrator)
        return True

    def _render_preview(self, command: dict[str, Any], confirmation_id: str) -> tuple[str, ...]:
        preview = command.get("preview")
        digest = command.get("preview_sha256")
        if not isinstance(preview, dict) or not isinstance(digest, str):
            raise ConfirmationError("confirmation preview is missing")
        eligible = preview["eligible_device_ids"]
        excluded = preview["excluded_devices"]
        policy = preview["dispatch_policy"]
        expires = self._rfc3339(int(preview["confirmation_expires_at"]))
        command_expires = self._rfc3339(int(preview["command_expires_at"]))
        header = render_control_text(
            f"Preview {command['operation']}: {len(eligible)} frozen target(s), "
            f"{len(excluded)} excluded.\nFull SHA-256: {digest}\n"
            f"Confirmation expires: {expires}\nCommand valid through: {command_expires}\n"
            f"Dispatch: up to {policy['max_workers']} concurrent, "
            f"{policy['attempts_per_target']} attempt(s) per target.",
            state="queued",
            subsystem=operation_subsystem(str(command["operation"])),
        )
        if command["operation"] == "ota_stage":
            arguments = preview.get("arguments", {})
            manifest = arguments.get("manifest", {}) if isinstance(arguments, dict) else {}
            if isinstance(manifest, dict):
                header += (
                    f"\nRelease: {manifest.get('version', 'unavailable')}"
                    f"\nGit tag: {manifest.get('git_tag', 'unavailable')}"
                    f"\nCommit: {manifest.get('commit_sha', 'unavailable')}"
                    f"\nArtifact SHA-256: {manifest.get('artifact_sha256', 'unavailable')}"
                    f"\nRuntime dependency SHA-256: "
                    f"{manifest.get('runtime_dependency_sha256', 'unavailable')}"
                    f"\nManifest identity SHA-256: "
                    f"{arguments.get('manifest_identity', 'unavailable')}"
                )
        lines = [f"TARGET {device_id}" for device_id in eligible]
        lines.extend(f"EXCLUDED {item['device_id']}: {item['reason']}" for item in excluded)
        canaries = preview.get("ota_canary_device_ids", [])
        if canaries:
            lines.append(f"OTA CANARIES: {', '.join(canaries)}")
        family = "ota" if str(command["operation"]).startswith("ota_") else "fleet"
        confirm = f"Confirm with /{family} {command['target']} confirm {confirmation_id}"
        return self._paginate_preview(header, lines, confirm)

    @staticmethod
    def _paginate_preview(header: str, lines: list[str], confirm: str) -> tuple[str, ...]:
        # Keep headroom below Telegram's 4096-character limit. Long configured
        # identifiers are split across pages without dropping any characters.
        body = "\n".join(lines) or "(no target detail)"
        combined = f"{header}\n{body}\n{confirm}"
        if len(combined) <= 4000:
            return (combined,)
        page_size = 3500
        chunks: list[str] = []
        current: list[str] = []
        current_size = 0
        for line in lines or ["(no target detail)"]:
            if len(line) > page_size:
                if current:
                    chunks.append("\n".join(current))
                    current = []
                    current_size = 0
                chunks.extend(line[index : index + page_size] for index in range(0, len(line), page_size))
                continue
            added_size = len(line) + (1 if current else 0)
            if current and current_size + added_size > page_size:
                chunks.append("\n".join(current))
                current = []
                current_size = 0
                added_size = len(line)
            current.append(line)
            current_size += added_size
        if current:
            chunks.append("\n".join(current))
        pages = [header]
        pages.extend(
            f"Target review {index}/{len(chunks)}:\n{chunk}" for index, chunk in enumerate(chunks, start=1)
        )
        pages.append(confirm)
        return tuple(pages)

    def _now(self) -> int:
        return int(self.clock())

    def _dispatch_target(self, envelope: DispatchEnvelope, policy: dict[str, Any]) -> DispatchResult:
        result = DispatchResult(False, "dispatch failed", retryable=True)
        attempts = int(policy["attempts_per_target"])
        backoff = [float(value) for value in policy["retry_backoff_s"]]
        for attempt in range(attempts):
            try:
                result = self.dispatcher.dispatch(envelope)
            except Exception:
                result = DispatchResult(False, "dispatch failed", retryable=True)
            if result.ok or not result.retryable:
                return result
            if result.details.get("status") == "accepted":
                return result
            if attempt + 1 < attempts:
                self.sleeper(backoff[attempt])
        return result

    def _dispatch_envelopes(
        self, envelopes: list[DispatchEnvelope], max_workers: int, policy: dict[str, Any]
    ) -> dict[str, DispatchResult]:
        if not envelopes:
            return {}
        if max_workers == 1:
            return {envelope.device_id: self._dispatch_target(envelope, policy) for envelope in envelopes}
        results: dict[str, DispatchResult] = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="edgewatch-dispatch") as pool:
            futures = {
                pool.submit(self._dispatch_target, envelope, policy): envelope for envelope in envelopes
            }
            for future in as_completed(futures):
                envelope = futures[future]
                try:
                    results[envelope.device_id] = future.result()
                except Exception:
                    results[envelope.device_id] = DispatchResult(False, "dispatch failed", retryable=True)
        return results

    def _completion_reply(
        self,
        text: str,
        status: str,
        operation: str,
        command: dict[str, Any] | None = None,
    ) -> str:
        state: ReplyState
        if status == "applied":
            state = "success"
        elif status in {"expired", "aborted"}:
            state = "warning"
        else:
            state = "failed"
        if status == "applied" and command is not None:
            detail = self._single_device_result(command)
            if detail is not None:
                text = f"{detail}\n{text}"
        return render_control_text(
            text,
            state=state,
            subsystem=operation_subsystem(operation),
        )

    def _single_device_result(self, command: dict[str, Any]) -> str | None:
        operation = str(command["operation"])
        if (
            command.get("scope") != "device"
            or operation not in {"status", "health", "network", "power", "queue", "version", "ota_status"}
            or len(command.get("device_ids", ())) != 1
        ):
            return None
        targets = self.store.get_command_targets(str(command["command_id"]))
        if len(targets) != 1 or targets[0]["status"] != "applied":
            return None
        stored = targets[0].get("result")
        details = stored.get("details") if isinstance(stored, dict) else None
        result = details.get("result") if isinstance(details, dict) else None
        if not isinstance(result, dict):
            return None
        rendered = self._render_device_result(operation, result)
        if not rendered:
            return None
        device_id = self._display_value(targets[0]["device_id"], max_chars=64) or "device"
        return f"{device_id}: {rendered}"[:1500]

    @classmethod
    def _render_device_result(cls, operation: str, result: dict[str, Any]) -> str:
        if operation == "status":
            local_control = result.get("local_control")
            local_control = local_control if isinstance(local_control, dict) else {}
            overrides = local_control.get("overrides")
            overrides = overrides if isinstance(overrides, dict) else {}
            alerts = local_control.get("alerts")
            alerts = alerts if isinstance(alerts, dict) else {}
            return cls._render_fields(
                (
                    ("ready", result.get("ready")),
                    ("transport", result.get("transport")),
                    ("version", result.get("version")),
                    ("operation", result.get("operation_mode", overrides.get("operation_mode"))),
                    (
                        "power",
                        result.get("runtime_power_mode", overrides.get("runtime_power_mode")),
                    ),
                    (
                        "alerts muted until",
                        result.get("alerts_muted_until", alerts.get("muted_until")),
                    ),
                    ("pending requests", result.get("pending_requests")),
                    ("sleep interval s", overrides.get("sleep_poll_interval_s")),
                )
            )
        if operation == "health":
            return cls._render_fields((("ready", result.get("ready")),))
        if operation == "network":
            interfaces = result.get("interfaces")
            if not isinstance(interfaces, list):
                return ""
            rendered_interfaces: list[str] = []
            for item in interfaces[:8]:
                if not isinstance(item, dict):
                    continue
                name = cls._display_value(item.get("name"), max_chars=32)
                state = cls._display_value(item.get("state"), max_chars=24)
                if name is not None and state is not None:
                    rendered_interfaces.append(f"{name}={state}")
            if len(interfaces) > 8:
                rendered_interfaces.append(f"+{len(interfaces) - 8} more")
            return "interfaces: " + ", ".join(rendered_interfaces) if rendered_interfaces else ""
        if operation == "power":
            return cls._render_fields(
                (
                    ("mode", result.get("runtime_power_mode")),
                    ("source", result.get("source")),
                    ("input out of range", result.get("input_out_of_range")),
                    ("unsustainable", result.get("unsustainable")),
                    ("saver active", result.get("saver_active")),
                    ("throttled", result.get("throttled")),
                )
            )
        if operation == "queue":
            return cls._render_fields(
                (
                    ("queued points", result.get("queued_points")),
                    ("database bytes", result.get("database_bytes")),
                )
            )
        if operation == "version":
            return cls._render_fields((("version", result.get("version")),))
        if operation == "ota_status":
            ota = result.get("ota")
            ota = ota if isinstance(ota, dict) else {}
            active = ota.get("active")
            active = active if isinstance(active, dict) else {}
            active_manifest = active.get("manifest")
            active_manifest = active_manifest if isinstance(active_manifest, dict) else {}
            staged = ota.get("staged")
            staged = staged if isinstance(staged, dict) else {}
            staged_manifest = staged.get("manifest")
            staged_manifest = staged_manifest if isinstance(staged_manifest, dict) else {}
            return cls._render_fields(
                (
                    ("status", result.get("status")),
                    ("active version", active_manifest.get("version")),
                    ("active tag", active_manifest.get("git_tag")),
                    ("staged version", staged_manifest.get("version")),
                    ("staged tag", staged_manifest.get("git_tag")),
                    ("aborted", ota.get("aborted")),
                )
            )
        return ""

    @classmethod
    def _render_fields(cls, fields: tuple[tuple[str, Any], ...]) -> str:
        rendered = []
        for label, raw in fields:
            value = cls._display_value(raw)
            if value is not None:
                rendered.append(f"{label}: {value}")
        return "; ".join(rendered)

    @staticmethod
    def _display_value(value: Any, *, max_chars: int = 96) -> str | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)[:max_chars]
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.split())
        if not normalized:
            return None
        if len(normalized) > max_chars:
            return normalized[: max_chars - 1] + "…"
        return normalized

    @staticmethod
    def _rfc3339(epoch_seconds: int) -> str:
        return (
            datetime.fromtimestamp(epoch_seconds, tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        )

    @staticmethod
    def _required_role(operation: str, arguments: dict[str, Any]) -> Role:
        if operation.startswith("ota_") or operation in {"deep_sleep", "reboot", "shutdown"}:
            return Role.ADMIN
        if operation == "set_power_mode" and arguments.get("mode") == "deep_sleep":
            return Role.ADMIN
        if operation in {"status", "health", "network", "power", "queue", "version", "ota_status"}:
            return Role.VIEWER
        return Role.OPERATOR
