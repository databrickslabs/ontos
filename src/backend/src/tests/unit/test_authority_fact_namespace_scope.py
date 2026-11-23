"""The ``fact`` namespace belongs to ARF's strict evaluator only (#1294 slice 4 review).

A regular Compliance rule that writes ``fact.x`` keeps reading the top-level key ``x``.
"""
from src.common import compliance_dsl


def test_a_regular_compliance_rule_reads_fact_dot_x_as_the_top_level_key():
    obj = {"fact": {"x": 1}, "x": 2}
    passed, _ = compliance_dsl.evaluate_rule_on_object("ASSERT fact.x = 2", obj)
    assert passed is True


def test_a_regular_compliance_rule_reads_a_missing_top_level_key_as_absent():
    passed, _ = compliance_dsl.evaluate_rule_on_object("ASSERT fact.x = 2", {"x": 2})
    assert passed is True


def test_the_strict_arf_evaluator_reads_the_fact_namespace():
    outcome = compliance_dsl.evaluate_rule_strict("ASSERT fact.x = 1", {"fact": {"x": 1}, "x": 2})
    assert outcome.passed is True


def test_the_strict_arf_evaluator_treats_a_missing_fact_as_unknown_not_the_top_level_key():
    outcome = compliance_dsl.evaluate_rule_strict("ASSERT fact.x = 2", {"fact": {}, "x": 2})
    assert outcome.passed is None   # UNKNOWN: fails closed in ARF, never the top-level x
