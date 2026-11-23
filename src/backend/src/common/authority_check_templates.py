"""ARF check templates: starter decision checks shipped with Ontos (ARF 1.2.0).

An author adds one with "Add check > From ARF template". The rule is copied into
the AR version's own check (no link to a Compliance Check), so the template can
evolve here without changing any saved AR.

Templates read request fields as ``obj.<field>`` and, where a comparison needs one, the
AR's parameters as ``ctx.<param>`` (a template that needs a parameter says so in its
description). Justification fields come with the policy batch. A co-sign is a duty (the decision
is conditional until the co-signer acts), not a check, so it lives in the ODRL rule
editor, where duties are expressed.
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
        key="amount_within_threshold",
        name="Amount within threshold",
        description=(
            "The request amount (request field value) must be at or below the AR's threshold "
            "parameter. The AR needs a 'threshold' parameter in its domain context (ctx.threshold); "
            "without it the check fails closed."
        ),
        rule="ASSERT obj.value <= ctx.threshold",
        failure_message="The amount is above the threshold for this decision.",
        dimension="policy",
    ),
    CheckTemplate(
        # A missing grantee or actor fails the check (ARF rules fail closed on a missing operand).
        key="no_self_grant",
        name="No self-grant",
        description="The grantee must not be the requesting actor (request params grantee, actor_identity).",
        rule="ASSERT obj.grantee != obj.actor_identity",
        failure_message="The grantee must not be the requesting actor.",
        dimension="people",
    ),
)

_BY_KEY = {t.key: t for t in TEMPLATES}


def list_templates() -> Tuple[CheckTemplate, ...]:
    return TEMPLATES


def get_template(key: Optional[str]) -> Optional[CheckTemplate]:
    return _BY_KEY.get(key or "")
