"""Invalid search_config.yaml is rejected with a logged warning, never silently replaced by defaults."""
from pathlib import Path
from unittest import mock

import pytest

from src.common import search_config_loader as loader_mod
from src.common.search_config_loader import SearchConfigLoader


def _load(tmp_path: Path, text: str):
    path = tmp_path / "search_config.yaml"
    path.write_text(text, encoding="utf-8")
    return SearchConfigLoader(config_path=path).load(force_reload=True)


def test_yaml_list_at_root_is_rejected_with_warning(tmp_path):
    with mock.patch.object(loader_mod.logger, "warning") as warn:
        with pytest.raises(ValueError, match="YAML mapping"):
            _load(tmp_path, "- a\n- b\n")
    assert warn.called and "not a YAML mapping" in warn.call_args[0][0]


def test_malformed_section_is_rejected_with_warning(tmp_path):
    with mock.patch.object(loader_mod.logger, "warning") as warn:
        with pytest.raises(ValueError, match="malformed section"):
            _load(tmp_path, "asset_types: [1, 2]\n")
    assert warn.called


def test_unknown_match_type_warns_and_defaults(tmp_path):
    with mock.patch.object(loader_mod.logger, "warning") as warn:
        cfg = _load(tmp_path, "asset_types:\n  data-product:\n    extra_fields:\n"
                              "      owner:\n        match_type: bogus\n")
    assert "data-product" in cfg.asset_types
    assert any("Unknown match_type" in c[0][0] for c in warn.call_args_list)
