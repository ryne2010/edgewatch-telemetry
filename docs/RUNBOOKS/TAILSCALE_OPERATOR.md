# Tailscale operator overlay runbook

This runbook covers a private operator-access overlay for EdgeWatch.

Use it when you want:

- MacBook-to-device SSH and troubleshooting over Tailscale
- private browser/API access to operator surfaces when you expose them privately
- to keep EdgeWatch's normal ingest path unchanged

Do not use this runbook to replace the repo's default hosted posture.
The normal recommendation remains:

- public ingest service with device-token auth
- private dashboard/admin surfaces for operators

## Architecture intent

Tailscale is an operator overlay here, not the telemetry transport.

- Keep `EDGEWATCH_API_URL` pointed at the existing public ingest URL.
- Keep device ingest on the current public HTTPS path.
- Use Tailscale only for:
  - device reachability
  - SSH access
  - optional private dashboard/admin entrypoints

## MacBook setup

This workspace already detected a running `Tailscale.app` install on macOS.

- If the menu-bar app is already connected to your tailnet, keep it.
- If you need terminal-driven `tailscale` commands, prefer Tailscale's standalone macOS variant rather than the Mac App Store variant.
- Enable MagicDNS in the Tailscale admin console if it is not already on.

Verification on the MacBook:

- confirm the app shows `Connected`
- confirm `Use Tailscale DNS settings` is enabled if MagicDNS lookups do not resolve
- from Terminal:

```bash
ping <device-machine-name>
ssh <device-machine-name>
```

On macOS, `ping` uses system DNS resolution and is the right quick check for MagicDNS. Tools like `host` and `nslookup` can bypass the system resolver and may not reflect MagicDNS behavior correctly.

## Tailnet policy model

Use Tailscale grants as the source of truth.

- Tag all EdgeWatch nodes with `tag:edgewatch-device`
- Add an optional site tag only when you need location scoping, for example `tag:site-denver`
- Allow only your operator identity or operator group to reach those nodes
- Do not grant broad all-port access by default

Example tailnet policy fragment:

```json
{
  "tagOwners": {
    "tag:edgewatch-device": ["group:netops@example.com"],
    "tag:site-denver": ["group:netops@example.com"]
  },
  "grants": [
    {
      "src": ["user:you@example.com"],
      "dst": ["tag:edgewatch-device:22"]
    },
    {
      "src": ["user:you@example.com"],
      "dst": ["tag:edgewatch-device:443", "tag:edgewatch-device:80"]
    }
  ],
  "ssh": [
    {
      "action": "accept",
      "src": ["user:you@example.com"],
      "dst": ["tag:edgewatch-device"],
      "users": ["pi", "edgewatch", "root"]
    }
  ]
}
```

Adjust the user/group selectors and destination ports to match your actual operator model. If you do not want Tailscale SSH, drop the `ssh` block and use plain SSH over the tailnet.

## Edge device bootstrap

Generate a one-off, pre-approved, tagged auth key in the Tailscale admin console.

Recommended auth-key settings:

- one-off
- pre-approved
- tagged with `tag:edgewatch-device`
- optionally tagged with one site tag

Install Tailscale on Raspberry Pi OS or Debian-based devices:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled
sudo tailscale up --auth-key="$TAILSCALE_AUTH_KEY" --hostname="$DEVICE_ID"
```

If you want Tailscale-managed SSH on the device:

```bash
sudo tailscale set --ssh
```

If you do not want Tailscale SSH:

- leave `sshd` configured normally
- allow only port `22` in Tailscale grants
- use plain `ssh` over the Tailscale address or MagicDNS name

## Device naming

Use hostnames that match your EdgeWatch device IDs when practical.

Good examples:

- `pump-west-1`
- `well-east-2`
- `compressor-yard-3`

This keeps:

- Tailscale machine names
- MagicDNS names
- EdgeWatch `device_id`

close enough that operators do not have to translate between multiple identifiers.

## Verification checklist

After joining a device to the tailnet:

1. Confirm the device appears in the Tailscale Machines page with the expected tags.
2. Confirm MagicDNS resolves from the MacBook:

```bash
ping <device-machine-name>
```

3. Confirm operator SSH works:

```bash
ssh <device-machine-name>
```

4. Confirm the EdgeWatch agent still points at the normal public ingest URL:

```bash
grep '^EDGEWATCH_API_URL=' ~/edgewatch-telemetry/agent/.env
```

5. Confirm at least one private operator flow works over the overlay:
   - SSH into the node
   - browser access to a private dashboard/admin endpoint
   - a curl request to a private operator endpoint from the MacBook

## Failure modes

If `ping <device-machine-name>` fails:

- confirm the MacBook is connected to the correct tailnet
- confirm MagicDNS is enabled
- confirm the device is connected and not expired/removed
- confirm the device hostname is what you expect in the Machines page

If the device is online in Tailscale but `ssh` fails:

- check the grants policy for port `22`
- if using Tailscale SSH, confirm `tailscale set --ssh` was applied on the device
- if using plain SSH, confirm `sshd` is running on the device

If EdgeWatch telemetry breaks after enabling Tailscale:

- verify `EDGEWATCH_API_URL` still targets the public ingest service
- verify you did not replace the device's ingest URL with a private MagicDNS name accidentally

## References

- [Install Tailscale on macOS](https://tailscale.com/docs/install/mac)
- [Install Tailscale on Linux](https://tailscale.com/docs/install/linux)
- [MagicDNS](https://tailscale.com/kb/1081/magicdns)
- [Auth keys](https://tailscale.com/kb/1085/auth-keys)
- [Access control](https://tailscale.com/kb/1393/access-control)
- [Tailscale SSH](https://tailscale.com/kb/1193/tailscale-ssh)
