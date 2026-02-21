from __future__ import annotations

from dataclasses import dataclass

from .principal import Principal


@dataclass(frozen=True)
class AuditActor:
    email: str
    subject: str | None
    role: str
    source: str


def audit_actor_from_principal(principal: Principal) -> AuditActor:
    return AuditActor(
        email=principal.email,
        subject=principal.subject,
        role=principal.role,
        source=principal.source,
    )
