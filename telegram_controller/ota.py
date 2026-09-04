from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence, cast

from agent.local_ota import OtaError, ReleaseCatalog, ReleaseManifest


_TERMINAL_RESULTS = {"staged", "applied", "healthy", "failed", "deferred", "rolled_back"}
_SUCCESS_RESULTS = {"applied", "healthy"}


@dataclass(frozen=True)
class OtaDispatchCommand:
    command_id: str
    device_id: str
    operation: str
    arguments: dict[str, Any]

    @property
    def command_type(self) -> str:
        return self.operation

    @property
    def action(self) -> str:
        return self.operation

    @property
    def payload(self) -> dict[str, Any]:
        return self.arguments

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OtaOrchestrator:
    """Manual-only OTA state machine for the Telegram SSH dispatcher boundary."""

    def __init__(
        self,
        catalog: ReleaseCatalog,
        *,
        canary_device_ids: Iterable[str],
        rollout_percentages: Sequence[int] = (10, 50, 100),
        failure_rate_threshold: float = 0.10,
        defer_rate_threshold: float = 0.25,
        dispatcher: Callable[[OtaDispatchCommand], Any] | None = None,
        initial_state: Mapping[str, Any] | None = None,
    ) -> None:
        canaries = tuple(sorted({_device_id(value) for value in canary_device_ids}))
        if not canaries:
            raise OtaError("at least one configured canary is required")
        percentages = tuple(int(value) for value in rollout_percentages)
        if not percentages or any(value <= 0 or value > 100 for value in percentages):
            raise OtaError("rollout percentages must be integers from 1 through 100")
        if tuple(sorted(set(percentages))) != percentages or percentages[-1] != 100:
            raise OtaError("rollout percentages must be strictly increasing and end at 100")
        if not 0 <= failure_rate_threshold <= 1 or not 0 <= defer_rate_threshold <= 1:
            raise OtaError("failure and defer thresholds must be rates from 0 through 1")
        self.catalog = catalog
        self.canary_device_ids = canaries
        self.rollout_percentages = percentages
        self.failure_rate_threshold = failure_rate_threshold
        self.defer_rate_threshold = defer_rate_threshold
        self.dispatcher = dispatcher
        if initial_state is None:
            self.state: dict[str, Any] = self._base_state("idle")
        else:
            self.state = self._restore_state(initial_state)

    @classmethod
    def from_snapshot(
        cls,
        catalog: ReleaseCatalog,
        snapshot: Mapping[str, Any],
        *,
        dispatcher: Callable[[OtaDispatchCommand], Any] | None = None,
    ) -> OtaOrchestrator:
        canaries = snapshot.get("configured_canaries")
        percentages = snapshot.get("rollout_percentages")
        failure_threshold = snapshot.get("failure_rate_threshold")
        defer_threshold = snapshot.get("defer_rate_threshold")
        if not isinstance(canaries, list) or not isinstance(percentages, list):
            raise OtaError("invalid OTA orchestrator snapshot configuration")
        if not isinstance(failure_threshold, (int, float)) or isinstance(failure_threshold, bool):
            raise OtaError("invalid OTA orchestrator failure threshold")
        if not isinstance(defer_threshold, (int, float)) or isinstance(defer_threshold, bool):
            raise OtaError("invalid OTA orchestrator defer threshold")
        return cls(
            catalog,
            canary_device_ids=canaries,
            rollout_percentages=percentages,
            failure_rate_threshold=float(failure_threshold),
            defer_rate_threshold=float(defer_threshold),
            dispatcher=dispatcher,
            initial_state=snapshot,
        )

    def _base_state(self, status: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": status,
            "configured_canaries": list(self.canary_device_ids),
            "rollout_percentages": list(self.rollout_percentages),
            "failure_rate_threshold": self.failure_rate_threshold,
            "defer_rate_threshold": self.defer_rate_threshold,
        }

    def stage(
        self,
        release_alias: str,
        target_device_ids: Iterable[str],
        *,
        manifest: ReleaseManifest | None = None,
    ) -> list[OtaDispatchCommand]:
        if self.state.get("status") not in {"idle", "aborted", "complete"}:
            raise OtaError("an OTA deployment is already active")
        if "://" in release_alias:
            raise OtaError("OTA input must be a release alias, not a URL")
        manifest = self.catalog.resolve(release_alias) if manifest is None else manifest
        targets = tuple(sorted({_device_id(value) for value in target_device_ids}))
        if not targets:
            raise OtaError("OTA deployment requires at least one target")
        canaries = tuple(value for value in self.canary_device_ids if value in targets)
        if not canaries:
            raise OtaError("the frozen target set contains no configured canaries")
        deployment_id = str(uuid.uuid4())
        frozen_hash = hashlib.sha256("\n".join(targets).encode("utf-8")).hexdigest()
        self.state = {
            **self._base_state("staging"),
            "deployment_id": deployment_id,
            "release_alias": release_alias,
            "manifest": manifest.to_command_payload(),
            "manifest_identity": manifest.identity,
            "targets": targets,
            "targets_hash": frozen_hash,
            "canaries": canaries,
            "stage_index": -1,
            "enabled": (),
            "stage_results": {},
            "results": {},
        }
        return self._emit("ota_stage", targets, release_alias=release_alias, manifest=manifest)

    def preview_canary_device_ids(self, deployment_id: str | None = None) -> tuple[str, ...]:
        self._require_deployment(deployment_id)
        self._require_status("staging")
        self._check_staging_gate()
        return tuple(self.state["canaries"])

    def canary(
        self,
        deployment_id: str | None = None,
        results: Mapping[str, str] | None = None,
        *,
        expected_device_ids: Iterable[str] | None = None,
    ) -> list[OtaDispatchCommand]:
        self._require_deployment(deployment_id)
        self._require_status("staging")
        targets = tuple(self.state["canaries"])
        self._require_expected_targets(targets, expected_device_ids)
        if results:
            for device_id, status in results.items():
                self.record_result(device_id, status)
        targets = self.preview_canary_device_ids()
        self.state["status"] = "canary"
        self.state["enabled"] = targets
        self.state["results"] = {}
        return self._emit(
            "ota_canary",
            targets,
            release_alias=str(self.state["release_alias"]),
            manifest=self._manifest(),
        )

    def record_result(self, device_id: str, status: str) -> None:
        if self.state.get("status") not in {"staging", "canary", "rollout"}:
            raise OtaError("deployment is not accepting rollout results")
        device_id = _device_id(device_id)
        eligible = (
            self.state.get("targets", ())
            if self.state.get("status") == "staging"
            else self.state.get("enabled", ())
        )
        if device_id not in eligible:
            raise OtaError("result is not for the current rollout tranche")
        normalized = status.strip().lower()
        if normalized not in _TERMINAL_RESULTS:
            raise OtaError("invalid OTA result status")
        result_key = "stage_results" if self.state.get("status") == "staging" else "results"
        self.state.setdefault(result_key, {})[device_id] = normalized
        self._maybe_complete_rollout()

    def preview_promote_device_ids(self, deployment_id: str | None = None) -> tuple[str, ...]:
        self._require_deployment(deployment_id)
        if self.state.get("status") not in {"canary", "rollout"}:
            raise OtaError("deployment must complete canary or rollout before promotion")
        self._check_gate()
        return self._next_promote_tranche()

    def promote(
        self,
        deployment_id: str | None = None,
        results: Mapping[str, str] | None = None,
        *,
        expected_device_ids: Iterable[str] | None = None,
    ) -> list[OtaDispatchCommand]:
        self._require_deployment(deployment_id)
        if self.state.get("status") not in {"canary", "rollout"}:
            raise OtaError("deployment must complete canary or rollout before promotion")
        tranche = self._next_promote_tranche()
        self._require_expected_targets(tranche, expected_device_ids)
        if results:
            for device_id, status in results.items():
                self.record_result(device_id, status)
        if self.state.get("status") == "complete":
            return []
        tranche = self.preview_promote_device_ids()
        if self._coverage_complete():
            self.state["status"] = "complete"
            return []
        if not tranche:
            raise OtaError("rollout has remaining targets but no promotable tranche")
        next_index = int(self.state["stage_index"]) + 1
        if next_index >= len(self.rollout_percentages):
            self.state["status"] = "complete"
            return []
        already_enabled = set(self.state.get("enabled_all", ())) | set(self.state["canaries"])
        enabled_all = tuple(sorted(already_enabled | set(tranche)))
        self.state["stage_index"] = next_index
        self.state["enabled"] = tranche
        self.state["enabled_all"] = enabled_all
        self.state["results"] = {}
        self.state["status"] = "rollout" if enabled_all != tuple(self.state["targets"]) else "rollout"
        return self._emit("ota_promote", tranche)

    def abort(self, deployment_id: str | None = None) -> list[OtaDispatchCommand]:
        self._require_deployment(deployment_id)
        if self.state.get("status") in {"idle", "aborted", "complete"}:
            raise OtaError("there is no active OTA deployment to abort")
        enabled = set(self.state.get("enabled_all", ())) | set(self.state.get("enabled", ()))
        undispatched = tuple(device_id for device_id in self.state["targets"] if device_id not in enabled)
        self.state["status"] = "aborted"
        self.state["undispatched_at_abort"] = undispatched
        # Undispatched targets have no device-side work to cancel.  In-flight
        # and applied devices are intentionally not presented as rolled back.
        return []

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state))

    def _restore_state(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        try:
            state = json.loads(json.dumps(snapshot))
        except (TypeError, ValueError) as exc:
            raise OtaError("OTA orchestrator snapshot must be JSON serializable") from exc
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            raise OtaError("invalid OTA orchestrator snapshot schema")
        if state.get("configured_canaries") != list(self.canary_device_ids):
            raise OtaError("OTA orchestrator snapshot canaries do not match configuration")
        if state.get("rollout_percentages") != list(self.rollout_percentages):
            raise OtaError("OTA orchestrator snapshot rollout percentages do not match configuration")
        if state.get("failure_rate_threshold") != self.failure_rate_threshold:
            raise OtaError("OTA orchestrator snapshot failure threshold does not match configuration")
        if state.get("defer_rate_threshold") != self.defer_rate_threshold:
            raise OtaError("OTA orchestrator snapshot defer threshold does not match configuration")
        status = state.get("status")
        if status not in {"idle", "staging", "canary", "rollout", "halted", "aborted", "complete"}:
            raise OtaError("invalid OTA orchestrator snapshot status")
        if status == "idle":
            if set(state) != set(self._base_state("idle")):
                raise OtaError("idle OTA orchestrator snapshot contains deployment data")
            return state
        required = {
            "deployment_id",
            "release_alias",
            "manifest",
            "manifest_identity",
            "targets",
            "targets_hash",
            "canaries",
            "stage_index",
            "enabled",
            "stage_results",
            "results",
        }
        allowed = set(self._base_state(str(status))) | required | {"enabled_all", "undispatched_at_abort"}
        unknown = set(state) - allowed
        if unknown:
            raise OtaError(f"OTA orchestrator snapshot has unknown fields: {', '.join(sorted(unknown))}")
        if not required <= set(state):
            raise OtaError("OTA orchestrator snapshot is incomplete")
        _nonempty_snapshot_string(state.get("deployment_id"), "deployment_id")
        manifest_raw = state.get("manifest")
        if not isinstance(manifest_raw, Mapping):
            raise OtaError("OTA orchestrator snapshot manifest is invalid")
        manifest = ReleaseManifest.from_payload(manifest_raw)
        _nonempty_snapshot_string(state.get("release_alias"), "release_alias")
        if manifest.identity != state.get("manifest_identity"):
            raise OtaError("OTA orchestrator snapshot manifest identity is invalid")
        targets = _snapshot_devices(state.get("targets"), "targets")
        if hashlib.sha256("\n".join(targets).encode("utf-8")).hexdigest() != state.get("targets_hash"):
            raise OtaError("OTA orchestrator snapshot target hash is invalid")
        canaries = _snapshot_devices(state.get("canaries"), "canaries")
        if not canaries or not set(canaries) <= set(targets):
            raise OtaError("OTA orchestrator snapshot canaries are invalid")
        if tuple(device for device in self.canary_device_ids if device in targets) != canaries:
            raise OtaError("OTA orchestrator snapshot canaries do not match frozen targets")
        stage_index = state.get("stage_index")
        if (
            isinstance(stage_index, bool)
            or not isinstance(stage_index, int)
            or not -1 <= stage_index < len(self.rollout_percentages)
        ):
            raise OtaError("OTA orchestrator snapshot stage index is invalid")
        enabled = _snapshot_devices(state.get("enabled"), "enabled", allow_empty=True)
        enabled_all = _snapshot_devices(state.get("enabled_all", []), "enabled_all", allow_empty=True)
        if not set(enabled) <= set(targets) or not set(enabled_all) <= set(targets):
            raise OtaError("OTA orchestrator snapshot enabled targets are invalid")
        results_raw = state.get("results")
        if not isinstance(results_raw, Mapping) or not set(results_raw) <= set(enabled):
            raise OtaError("OTA orchestrator snapshot results are invalid")
        if any(value not in _TERMINAL_RESULTS for value in results_raw.values()):
            raise OtaError("OTA orchestrator snapshot contains an invalid result")
        stage_results_raw = state.get("stage_results")
        if not isinstance(stage_results_raw, Mapping) or not set(stage_results_raw) <= set(targets):
            raise OtaError("OTA orchestrator snapshot staging results are invalid")
        if any(value not in _TERMINAL_RESULTS for value in stage_results_raw.values()):
            raise OtaError("OTA orchestrator snapshot contains an invalid staging result")
        if status == "staging" and enabled:
            raise OtaError("staging OTA orchestrator snapshot cannot have apply targets")
        if status == "canary" and enabled != canaries:
            raise OtaError("canary OTA orchestrator snapshot enabled targets are invalid")
        if "undispatched_at_abort" in state:
            undispatched = _snapshot_devices(
                state["undispatched_at_abort"], "undispatched_at_abort", allow_empty=True
            )
            if status != "aborted" or not set(undispatched) <= set(targets):
                raise OtaError("OTA orchestrator snapshot abort targets are invalid")
            state["undispatched_at_abort"] = undispatched
        state["targets"] = targets
        state["canaries"] = canaries
        state["enabled"] = enabled
        if "enabled_all" in state:
            state["enabled_all"] = enabled_all
        state["results"] = dict(results_raw)
        state["stage_results"] = dict(stage_results_raw)
        return state

    def _check_gate(self) -> None:
        enabled = cast(tuple[str, ...], tuple(self.state.get("enabled", ())))
        results = cast(dict[str, str], self.state.get("results", {}))
        if not enabled or any(device_id not in results for device_id in enabled):
            raise OtaError("all devices in the current tranche must reach a terminal result")
        total = len(enabled)
        failures = sum(results[device_id] in {"failed", "rolled_back"} for device_id in enabled)
        deferrals = sum(results[device_id] == "deferred" for device_id in enabled)
        if failures / total > self.failure_rate_threshold:
            self.state["status"] = "halted"
            raise OtaError("failure rate exceeds the promotion gate")
        if deferrals / total > self.defer_rate_threshold:
            self.state["status"] = "halted"
            raise OtaError("defer rate exceeds the promotion gate")
        if any(results[device_id] not in _SUCCESS_RESULTS for device_id in enabled):
            raise OtaError("current rollout tranche is not healthy")

    def _check_staging_gate(self) -> None:
        targets = tuple(self.state["targets"])
        results = cast(dict[str, str], self.state.get("stage_results", {}))
        if any(device_id not in results for device_id in targets):
            raise OtaError("all frozen targets must report a terminal staging result")
        if any(results[device_id] != "staged" for device_id in targets):
            self.state["status"] = "halted"
            raise OtaError("all frozen targets must stage successfully before canary")

    def _coverage_complete(self) -> bool:
        covered = set(self.state.get("enabled_all", ())) | set(self.state.get("canaries", ()))
        return covered == set(self.state.get("targets", ()))

    def _maybe_complete_rollout(self) -> None:
        if self.state.get("status") != "rollout" or not self._coverage_complete():
            return
        enabled = cast(tuple[str, ...], tuple(self.state.get("enabled", ())))
        results = cast(dict[str, str], self.state.get("results", {}))
        if enabled and all(results.get(device_id) in _SUCCESS_RESULTS for device_id in enabled):
            self.state["status"] = "complete"

    def _next_promote_tranche(self) -> tuple[str, ...]:
        next_index = int(self.state["stage_index"]) + 1
        if next_index >= len(self.rollout_percentages):
            return ()
        target_count = math.ceil(len(self.state["targets"]) * self.rollout_percentages[next_index] / 100)
        already_enabled = set(self.state.get("enabled_all", ())) | set(self.state["canaries"])
        desired = tuple(self.state["targets"][:target_count])
        tranche = tuple(device_id for device_id in desired if device_id not in already_enabled)
        if not tranche and target_count < len(self.state["targets"]):
            remaining = [device_id for device_id in self.state["targets"] if device_id not in already_enabled]
            tranche = tuple(remaining[:1])
        return tranche

    def _require_deployment(self, deployment_id: str | None) -> None:
        if deployment_id is not None and deployment_id != self.state.get("deployment_id"):
            raise OtaError("OTA deployment ID does not match the active deployment")

    @staticmethod
    def _require_expected_targets(actual: tuple[str, ...], expected_device_ids: Iterable[str] | None) -> None:
        if expected_device_ids is None:
            return
        expected = tuple(sorted({_device_id(value) for value in expected_device_ids}))
        if expected != actual:
            raise OtaError("OTA confirmation targets are stale")

    def _manifest(self) -> ReleaseManifest:
        return ReleaseManifest.from_payload(self.state["manifest"])

    def _emit(
        self,
        operation: str,
        device_ids: Iterable[str],
        *,
        release_alias: str | None = None,
        manifest: ReleaseManifest | None = None,
    ) -> list[OtaDispatchCommand]:
        if operation not in {"ota_stage", "ota_canary", "ota_promote", "ota_abort"}:
            raise OtaError("orchestrator attempted an untyped OTA operation")
        arguments: dict[str, Any] = {}
        if release_alias is not None:
            if manifest is None:
                raise OtaError("trusted manifest is required with a release alias")
            arguments = {"release_alias": release_alias, "manifest": manifest.to_command_payload()}
        commands = [
            OtaDispatchCommand(
                command_id=f"{self.state['deployment_id']}:{operation}:{device_id}",
                device_id=device_id,
                operation=operation,
                arguments=dict(arguments),
            )
            for device_id in device_ids
        ]
        if self.dispatcher is not None:
            for command in commands:
                self.dispatcher(command)
        return commands

    def _require_status(self, required: str) -> None:
        if self.state.get("status") != required:
            raise OtaError(f"deployment must be {required}")


def _device_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OtaError("device IDs must be non-empty strings")
    return value.strip()


def _nonempty_snapshot_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OtaError(f"OTA orchestrator snapshot {field} is invalid")
    return value.strip()


def _snapshot_devices(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise OtaError(f"OTA orchestrator snapshot {field} must be a list")
    devices = tuple(_device_id(item) for item in value)
    if (not devices and not allow_empty) or devices != tuple(sorted(set(devices))):
        raise OtaError(f"OTA orchestrator snapshot {field} must be sorted and unique")
    return devices
