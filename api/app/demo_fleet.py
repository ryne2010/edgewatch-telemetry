"""Demo fleet helpers.

We treat "demo fleet" identifiers (device_id, display_name, token) as *templates*
where the Nth device is derived deterministically.

Rules
- Indexing is **1-based**.
- If the base value ends with a 3-digit suffix (e.g. `demo-well-001`), we replace
  that suffix with the requested index.
- Otherwise, we append `-NNN` for n > 1.

Why this matters
- Terraform + simulation jobs + API bootstrap must agree on device identifiers,
  otherwise you can end up with mismatched demo fleets.
"""

from __future__ import annotations

import re


_SUFFIX_RE = re.compile(r"^(.*?)(\d{3})$")


def split_suffix_3digits(value: str) -> tuple[str, int] | None:
    m = _SUFFIX_RE.match(value)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def derive_nth(value: str, n: int) -> str:
    """Derive the Nth demo value from a base template."""

    if n <= 1:
        return value
    split = split_suffix_3digits(value)
    if split:
        prefix, _ = split
        return f"{prefix}{n:03d}"
    return f"{value}-{n:03d}"
