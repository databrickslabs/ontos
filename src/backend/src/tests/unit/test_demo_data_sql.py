"""Unit tests for the demo-data SQL parser (``src.utils.demo_data_sql``).

The parser recovers ``(table, pk_column, [ids])`` from a demo pack so teardown can
delete the exact rows a pack inserts (drift-proof, replacing the old hand-written
prefix list). These tests pin the tricky bits: quotes-with-semicolons, JSON
payloads with commas, ``COALESCE((SELECT ...))`` in a value, interleaved comments,
``ON CONFLICT`` tails, and non-``id`` primary keys.
"""
import pytest

from src.utils.demo_data_sql import parse_demo_inserts


def test_basic_single_row():
    sql = "INSERT INTO teams (id, name) VALUES ('t1', 'Alpha') ON CONFLICT (id) DO NOTHING;"
    out = parse_demo_inserts(sql)
    assert len(out) == 1
    assert out[0].table == "teams"
    assert out[0].pk_column == "id"
    assert out[0].pk_values == ["t1"]


def test_multi_row_and_order():
    sql = (
        "INSERT INTO data_domains (id, name) VALUES ('d1','A'),('d2','B');\n"
        "INSERT INTO teams (id, name) VALUES ('t1','X');\n"
    )
    out = parse_demo_inserts(sql)
    assert [d.table for d in out] == ["data_domains", "teams"]
    assert out[0].pk_values == ["d1", "d2"]


def test_semicolon_inside_quoted_string_does_not_terminate():
    # A description containing ';' must not split the statement (the old regex bug
    # that silently dropped the entire data_contracts INSERT).
    sql = (
        "INSERT INTO data_contracts (id, name, description) VALUES\n"
        "('c1', 'Telemetry', 'rate varies (10ms-1s); DTC limited; GPS +/-3m'),\n"
        "('c2', 'Sensors', 'LiDAR 10Hz; camera 30fps')\n"
        "ON CONFLICT (id) DO NOTHING;"
    )
    out = parse_demo_inserts(sql)
    assert len(out) == 1
    assert out[0].pk_values == ["c1", "c2"]


def test_json_commas_and_coalesce_subquery():
    sql = (
        "INSERT INTO assets (id, name, asset_type_id, properties) VALUES\n"
        "('a1', 'fleet.eu',\n"
        " COALESCE((SELECT id FROM asset_types WHERE name = 'Fleet' LIMIT 1), 'fallback'),\n"
        " '{\"region\": \"EU\", \"count\": 120000, \"nested\": {\"a\": 1}}')\n"
        "ON CONFLICT (id) DO NOTHING;"
    )
    out = parse_demo_inserts(sql)
    assert len(out) == 1
    assert out[0].table == "assets"
    assert out[0].pk_values == ["a1"]


def test_interleaved_line_comments_in_values():
    sql = (
        "INSERT INTO assets (id, name) VALUES\n"
        "-- Vehicle Fleet (vertical asset type)\n"
        "('a1', 'one'),\n"
        "-- ECU Software (vertical asset type)\n"
        "('a2', 'two')\n"
        "ON CONFLICT (id) DO NOTHING;"
    )
    out = parse_demo_inserts(sql)
    assert out[0].pk_values == ["a1", "a2"]


def test_semicolon_inside_line_comment_does_not_terminate():
    # A ';' sitting inside a '--' comment within the VALUES body must not end the
    # statement — the arf pack hit this with a separator like
    # "-- AR 3: Ontos Role Request (meta-authority over Ontos itself; …)"
    # and the parser silently dropped every row after the comment, so teardown
    # left those orphaned.
    sql = (
        "INSERT INTO authority_relations (id, name) VALUES\n"
        "-- AR 1: Trade Promotion\n"
        "('r1', 'Trade Promotion'),\n"
        "-- AR 2: Platform Access\n"
        "('r2', 'Platform Access'),\n"
        "-- AR 3: Ontos Role (meta-authority over Ontos itself; still draft)\n"
        "('r3', 'Ontos Role'),\n"
        "-- AR 4: DP Decommissioning\n"
        "('r4', 'DP Decommissioning')\n"
        "ON CONFLICT (id) DO NOTHING;"
    )
    out = parse_demo_inserts(sql)
    assert len(out) == 1
    assert out[0].pk_values == ["r1", "r2", "r3", "r4"]


def test_non_id_primary_key():
    sql = (
        "INSERT INTO project_teams (project_id, team_id, assigned_by) VALUES\n"
        "('p1', 't1', 'system@demo');"
    )
    out = parse_demo_inserts(sql)
    assert out[0].pk_column == "project_id"
    assert out[0].pk_values == ["p1"]


def test_escaped_single_quote_in_value():
    sql = "INSERT INTO teams (id, name) VALUES ('t1', 'O''Brien Team');"
    out = parse_demo_inserts(sql)
    assert out[0].pk_values == ["t1"]


def test_on_conflict_paren_list_not_parsed_as_row():
    # ON CONFLICT (id) has parens; must not be mistaken for a VALUES row.
    sql = "INSERT INTO teams (id, name) VALUES ('t1','A') ON CONFLICT (id) DO NOTHING;"
    out = parse_demo_inserts(sql)
    assert out[0].pk_values == ["t1"]


@pytest.mark.parametrize("preset", ["retail", "hls", "fsi", "mfg", "auto", "arf"])
def test_real_packs_parse_cleanly(preset):
    from pathlib import Path
    import src.utils.demo_data_sql as mod

    data_dir = Path(mod.__file__).parent.parent / "data"
    pack = data_dir / f"demo_data_{preset}.sql"
    if not pack.exists():
        pytest.skip(f"{pack.name} not present")
    out = parse_demo_inserts(pack.read_text(encoding="utf-8"))
    assert out, "expected at least one INSERT parsed"
    # Every parsed pk value in the real packs is a UUID.
    for d in out:
        for v in d.pk_values:
            assert len(v) == 36 and v.count("-") == 4, (d.table, v)
    # Every pack ships domain assignments (shared polymorphic table).
    tables = {d.table for d in out}
    assert "entity_domain_associations" in tables


@pytest.mark.parametrize("preset", ["retail", "hls", "fsi", "mfg", "auto"])
def test_vertical_packs_capture_data_contracts(preset):
    """Vertical packs ship data_contracts (which carry ';'-laden descriptions);
    the arf pack is governance-only and doesn't."""
    from pathlib import Path
    import src.utils.demo_data_sql as mod

    data_dir = Path(mod.__file__).parent.parent / "data"
    pack = data_dir / f"demo_data_{preset}.sql"
    if not pack.exists():
        pytest.skip(f"{pack.name} not present")
    out = parse_demo_inserts(pack.read_text(encoding="utf-8"))
    assert "data_contracts" in {d.table for d in out}


def test_arf_pack_recovers_all_ar_rows():
    """Regression for the ';'-in-comment parser bug: the arf pack has four
    AR rows separated by '-- AR N: … itself; …' comment lines, and the parser
    must recover every row (not just the first two)."""
    from pathlib import Path
    import src.utils.demo_data_sql as mod

    data_dir = Path(mod.__file__).parent.parent / "data"
    pack = data_dir / "demo_data_arf.sql"
    if not pack.exists():
        pytest.skip("demo_data_arf.sql not present")
    out = parse_demo_inserts(pack.read_text(encoding="utf-8"))
    by_table = {d.table: d for d in out}
    assert len(by_table["authority_relations"].pk_values) == 6
    assert len(by_table["authority_affirmations"].pk_values) == 12
    assert len(by_table["authority_criteria"].pk_values) == 10
    assert len(by_table["authority_prerequisites"].pk_values) == 2
    assert len(by_table["authority_resource_refs"].pk_values) == 2
    assert len(by_table["entity_semantic_links"].pk_values) == 1
