"""Suggester engines.

Engine = pluggable callable that turns (targets, concepts) into SuggestionDrafts.
v1 ships the deterministic HeuristicSuggester; LLMJudgeSuggester is a future
phase (see PRD).
"""
from .heuristic import HeuristicSuggester  # noqa: F401
