# ADR: Telegram fleet control without the EdgeWatch API

- Status: Accepted
- Date: 2026-08-09

## Context

The field-validation fleet sends telemetry through Telegram and cannot rely on
an always-available EdgeWatch API. Operators also need typed device controls and
OTA orchestration from Telegram.

A Telegram bot has one update stream. Multiple Raspberry Pis cannot safely
consume the same bot with independent `getUpdates` offsets, and one bot webhook
has one destination. Installing the control-bot credential on every field node
would also let a compromised node impersonate the controller.

Hologram Spacebridge already provides authenticated SSH reachability to the
cellular devices, while direct SSH is available during home-network bring-up.

## Decision

### Controller topology

Run one supervised Telegram fleet controller on an operator-controlled host.
The controller:

- owns a dedicated control-bot credential that is never installed on devices;
- receives updates with one long-polling consumer, so no public webhook is
  required for the initial deployment;
- authorizes immutable numeric Telegram chat and user IDs;
- persists update IDs, commands, target rows, confirmations, deployment state,
  outbound replies, and audit records in SQLite before acknowledging work;
- dispatches only typed command envelopes through a fixed SSH device helper;
- uses direct pinned-host-key SSH at home and Hologram Spacebridge SSH in the
  field;
- keeps the dispatcher boundary replaceable by the canonical EdgeWatch API in
  a later deployment.

Telegram remains the operator interface. SSH/Spacebridge is the interim device
command transport; Telegram is not treated as a durable device command queue.

### Credential boundary

The telemetry bot token may remain on devices for outbound telemetry. Fleet
control uses a different bot token held only by the controller. A dedicated SSH
controller key is installed with an authorized-keys forced command that invokes
the root-owned typed helper and prohibits arbitrary commands, forwarding, PTYs,
and agent forwarding. The ordinary operator SSH key remains separate.

Secret and private-key configuration uses file references. Secret files must be
mode `0600` or stricter. SSH host keys are pinned; disabling host-key checking is
not supported.

### Command policy

The controller recognizes only these typed operations:

- viewer: status, health, network, power, queue, version, OTA status;
- operator: sample now, sync now, active/sleep mode, continuous/eco power,
  alert mute/unmute, agent restart;
- admin: reboot, deep sleep, OTA stage/canary/promote/abort;
- guarded and disabled by default: single-device shutdown.

Arbitrary shell, raw modem commands, arbitrary file/environment access,
credential display, user-supplied artifact URLs, fleet shutdown, and destructive
data operations are not part of the protocol.

Mutating fleet operations create a durable preview with a frozen target set,
exclusions, canaries, expiry, concurrency, and immutable hash. Confirmation is
one-use, actor/chat/topic-bound, re-authorized at dispatch, and expires after two
minutes by default.

### Delivery and idempotency

Every controller command and target has a stable ID and expiry. The device helper
persists an applied-command ledger and returns the original result for a replayed
ID. Transport failures retry with bounded exponential backoff. Invalid input,
authorization failure, host-key mismatch, incompatibility, and cryptographic
verification failure do not retry.

Telegram reply failure does not roll back accepted work. Replies have their own
durable retry state. A command is reported applied only after the device helper
returns a valid result and any required post-action health check succeeds.

### OTA

Telegram input may name only a release alias from the controller's local release
catalog. It may not supply a URL, digest, signature, or command.

Every OTA release is immutable and includes artifact type, URI, size, SHA-256,
signature, signature scheme, key ID, compatibility, and version identity. The
Telegram lane rejects unsigned artifacts and the `none` signature scheme.

`stage` downloads and verifies without activation. `canary` freezes and applies
the configured canary targets. `promote` advances exactly one rollout tranche
after health/failure gates pass. `abort` prevents undispatched targets from
starting but does not claim to undo already-applied devices.

Application bundles are the first apply path. System-image application remains
disabled until the real-device reboot and bad-release rollback validation gate
is complete.

## Consequences

- No public EdgeWatch API or webhook is required for home or initial field use.
- The controller host must remain online for timely commands and retries.
- Field dispatch depends on Hologram Spacebridge availability and the device's
  SSH service.
- Telegram telemetry continues if the controller is offline; control and OTA do
  not.
- The controller becomes a sensitive operational asset and requires protected
  backups of its configuration, keys, SQLite state, and SSH known-hosts file.
- A later hosted EdgeWatch control plane can replace the SSH dispatcher without
  changing Telegram parsing, RBAC, preview, audit, or rollout semantics.
