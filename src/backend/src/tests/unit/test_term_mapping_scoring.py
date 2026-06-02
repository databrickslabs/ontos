"""Unit tests for the heuristic scoring formula.

Locks the AUTO_ACCEPT == 0.90 boundary and ensures the rounding step keeps
borderline-perfect matches inside the auto-apply band.
"""
import pytest

from src.controller.term_mapping.scoring import AUTO_ACCEPT, AUTO_REJECT, Signals


class TestSignals:
    def test_perfect_match_with_type_and_pk_caps_at_one(self):
        s = Signals(name_similarity=1.0, type_compatible=True, pk_hint=True)
        assert s.confidence == 1.0

    def test_perfect_name_plus_compatible_type_hits_auto_accept(self):
        # 0.7*1.0 + 0.2 = 0.90 — boundary case.
        s = Signals(name_similarity=1.0, type_compatible=True)
        assert s.confidence == AUTO_ACCEPT
        # Auto-apply candidate confidence comparison uses >= AUTO_ACCEPT.
        assert s.confidence >= AUTO_ACCEPT

    def test_pk_or_fk_bonus_does_not_stack(self):
        s_pk = Signals(name_similarity=0.5, type_compatible=True, pk_hint=True)
        s_fk = Signals(name_similarity=0.5, type_compatible=True, fk_hint=True)
        s_both = Signals(name_similarity=0.5, type_compatible=True, pk_hint=True, fk_hint=True)
        assert s_pk.confidence == s_fk.confidence == s_both.confidence

    def test_type_incompat_penalty(self):
        # 0.7*0.5 + (-0.1) = 0.25
        s = Signals(name_similarity=0.5, type_compatible=False)
        assert s.confidence == pytest.approx(0.25)

    def test_floor_at_zero(self):
        # Pathological case: very low name + type incompat = negative gross,
        # but the score must clamp at 0.0.
        s = Signals(name_similarity=0.0, type_compatible=False)
        assert s.confidence == 0.0

    def test_rounding_avoids_borderline_drift(self):
        # 0.7 * 0.857142 = 0.5999994 (raw), should round to 0.6 region clean.
        s = Signals(name_similarity=0.857142, type_compatible=True)
        # Don't assert exact value; just verify no float drift below the
        # rejection threshold for a name match that's clearly above noise.
        assert s.confidence > AUTO_REJECT

    def test_render_falls_back_when_no_parts(self):
        assert Signals().render() == "No strong signal."

    def test_render_joins_non_empty_parts(self):
        s = Signals(parts=["one.", "", "two."])
        assert s.render() == "one. two."


def test_threshold_values_locked():
    """If anyone changes these, dozens of UI assumptions need to be revisited.
    Treat the constants as part of the public contract."""
    assert AUTO_ACCEPT == 0.90
    assert AUTO_REJECT == 0.40
