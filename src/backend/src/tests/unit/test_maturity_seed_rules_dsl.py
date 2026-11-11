"""The seeded maturity gate rules evaluate correctly through the compliance DSL.

Boolean gates are seeded as ``ASSERT obj.<flag> = True``. They must pass when the flag
is true and fail when it is false (the DSL once compared the flag to the string "True").
"""
from unittest.mock import MagicMock, patch

import pytest

from src.common.compliance_dsl import evaluate_rule_on_object
from src.repositories.maturity_repository import maturity_repo


def _seeded_rules() -> dict:
    db = MagicMock()
    # No policy exists yet, so the seed creates (db.add) one per gate
    db.query.return_value.filter.return_value.first.return_value = None
    with patch.object(maturity_repo, "is_empty", return_value=True), \
            patch.object(maturity_repo, "create", return_value=MagicMock()), \
            patch.object(maturity_repo, "add_gate"):
        maturity_repo.seed_defaults(db)
    policies = [c.args[0] for c in db.add.call_args_list]
    return {p.name.split("] ", 1)[1]: p.rule for p in policies}


RULES = _seeded_rules()

BOOLEAN_GATES = {
    "Owner is known": "has_owner",
    "Description present": "has_description",
    "Upstream lineage defined": "has_upstream_lineage",
    "Delivery channels defined": "has_delivery_channels",
    "Has output contracts": "has_contract",
}


@pytest.mark.parametrize("gate,flag", BOOLEAN_GATES.items())
def test_boolean_gate_passes_when_true_and_fails_when_false(gate, flag):
    rule = RULES[gate]
    assert flag in rule
    assert evaluate_rule_on_object(rule, {flag: True})[0] is True
    assert evaluate_rule_on_object(rule, {flag: False})[0] is False


@pytest.mark.parametrize("literal", ["True", "TRUE", "true", "False", "FALSE", "false"])
def test_boolean_literal_spellings(literal):
    expected = literal.lower() == "true"
    passed, _ = evaluate_rule_on_object(f"ASSERT obj.flag = {literal}", {"flag": True})
    assert passed is expected
