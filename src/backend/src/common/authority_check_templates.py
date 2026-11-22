"""ARF check templates: starter decision checks shipped with Ontos (ARF 1.2.0).

An author adds one with "Add check > From ARF template". The rule is copied into
the AR version's own check (no link to a Compliance Check), so the template can
evolve here without changing any saved AR.

Every template in this module reads only plain ``obj.<field>`` request fields
(the resolve request's top-level fields and its params). Templates that need the
``ctx.`` or ``req.`` namespaces, or justification fields, are added in later
releases; the registry is shaped so they can be appended without changing callers.
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class CheckTemplate:
    key: str
    name: str
    description: str
    rule: str
    failure_message: str
    dimension: str = "policy"
    direction: str = "neutral"


TEMPLATES: Tuple[CheckTemplate, ...] = (
    CheckTemplate(
        key="mfa_required",
        name="MFA required",
        description="The request must be made with multi-factor authentication (request param mfa_verified).",
        rule="ASSERT obj.mfa_verified = True",
        failure_message="Multi-factor authentication is required for this decision.",
        dimension="policy",
    ),
    CheckTemplate(
        key="no_sod_conflict",
        name="No segregation-of-duties conflict",
        description="The request must not carry a segregation-of-duties conflict (request param sod_conflict).",
        rule="ASSERT obj.sod_conflict = False",
        failure_message="The request has a segregation-of-duties conflict.",
        dimension="policy",
    ),
    CheckTemplate(
        # The IS NOT NULL test must follow the != inside the AND: a missing grantee
        # would otherwise pass the != (the DSL treats a missing operand as unequal).
        key="no_self_grant",
        name="No self-grant",
        description="The grantee must not be the requesting actor (request params grantee, actor_identity).",
        rule="ASSERT obj.grantee != obj.actor_identity AND obj.grantee IS NOT NULL",
        failure_message="The grantee must not be the requesting actor.",
        dimension="people",
    ),
)

_BY_KEY = {t.key: t for t in TEMPLATES}


def list_templates() -> Tuple[CheckTemplate, ...]:
    return TEMPLATES


def get_template(key: Optional[str]) -> Optional[CheckTemplate]:
    return _BY_KEY.get(key or "")
