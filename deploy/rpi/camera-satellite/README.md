# Camera-satellite service contract

Provisioning installs these units and enables
`edgewatch-camera-satellite-poweroff.path`. It creates the static
`edgewatch-camera` service account, installs
`camera-satellite.env` as root-owned mode `0640`, and installs each referenced
camera credential and live-promotion evidence file as `edgewatch-camera`-owned
mode `0600`.

Before every camera check or wake, the root-only
`edgewatch-camera-model-recovery.service` resolves any durable activation
journal left by a prior process crash or power loss. A normal model activation
holds a fixed root-owned flock through readiness; recovery exits successfully
as deferred while that live owner holds the lock, then reruns on the next
dependency start. Its filesystem sandbox makes only `/opt/edgewatch/models` writable;
the `edgewatch-camera` runtime account remains unable to change model releases
or the active symlink.

The controller key is forced through the typed helper with the immutable
`camera-satellite` runtime profile. The root helper reads only the fixed
root-owned `/etc/edgewatch/agent.env` and `/etc/edgewatch/camera-satellite.env`
files, imports only its control/OTA allowlist, and rejects writable or symlinked
configuration. The generated agent environment keeps OTA apply disabled by
default, points downloads at the private gateway cache, and fixes asset
activation to `scripts/apply_model_bundle.py`; model OTA cannot report applied
until that hook atomically switches and verifies the signed model.
Provisioning requires an initial signed model bundle; camera first boot never
depends on an unspecified model already being present in the image.

Signed application bundles use the same durable local OTA journal to switch
`/opt/edgewatch/current`. The camera profile ignores configurable service names
and starts only `edgewatch-camera-satellite@check.service`. That unit must write
a fresh mode-0600 receipt owned by `edgewatch-camera` whose
`application_target` exactly matches the resolved current release. The helper
checks receipt lifetime and a stability window; a failure or interrupted switch
restores, restarts, and verifies the prior release before clearing the journal.

Before a signed stage or apply, the helper requires `vcgencmd get_throttled` to
return exactly `throttled=0x0`, writes a fresh private power receipt, and the OTA
manager independently rechecks the same firmware evidence. Missing, stale, or
nonzero evidence fails closed.

Use the non-poweroff template for bootstrap, maintenance, and signed-model
readiness checks:

```text
systemctl start edgewatch-camera-satellite@check.service
```

The signed model apply readiness hook must use that exact `@check` unit. It
validates the active bundle signature/digests, LiteRT INT8 tensors, known-answer
vectors, signed preprocessing shapes, camera codecs, and writable evidence ring
without capturing evidence or requesting shutdown.

After an MCU event or daily-health wake, use only the wake template:

```text
systemctl start edgewatch-camera-satellite-wake@event.service
systemctl start edgewatch-camera-satellite-wake@daily.service
```

The wake runner first commits `result.json` atomically. Only then does it commit
a mode-0600 request below `/run`; the path unit consumes that volatile request
and PID 1 schedules a fixed `systemctl poweroff --no-wall`. There is no
configurable shell command. The runner rejects `--poweroff-on-success` for
`check`, so bootstrap and model apply cannot trigger shutdown through this
interface.

The MCU remains the electrical power latch. Its required hardware boundary is
a dedicated, board-qualified `HALT_ACK` signal indicating that Linux has
finished halting; the MCU must keep the Pi, camera, and SD rail powered until
that signal is asserted. A successful result file or service exit is not
permission to remove power. GPIO selection, the final-halt signal mechanism,
and MCU firmware are hardware-specific and are intentionally outside this
repository; they must be qualified before enabling automatic rail cutoff.
