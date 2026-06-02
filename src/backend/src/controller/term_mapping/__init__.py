"""Term-mapping engine, adapters, and helpers.

This package houses the deterministic + LLM suggester engines, the per-target
adapters that translate Ontos entities into a uniform feature shape, and the
shared scoring/naming helpers ported from the onyx_ontology source repo.

The top-level TermMappingManager (controller/term_mapping_manager.py) orchestrates
runs, queue persistence, apply, and undo across these components.
"""
