"""Unit tests for FileProvider.

Writes real CSV files to a temp dir so the parser, mtime cache, and
DictReader path get exercised end-to-end.
"""

import os
import textwrap
import time
from pathlib import Path

import pytest

from src.controller.directory_providers import (
    DirectoryError,
    DirectoryProviderConfig,
    DirectoryProviderContext,
    FileProvider,
)
from src.controller.directory_providers.file_provider import _clear_cache_for_tests
from src.models.directory import PrincipalType


@pytest.fixture(autouse=True)
def _reset_file_cache():
    """The provider's file cache is class-level; reset between tests."""

    _clear_cache_for_tests()
    yield
    _clear_cache_for_tests()


def _write_csv(tmp_path: Path, body: str, name: str = "principals.csv") -> str:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return str(path)


def _make_provider(path: str) -> FileProvider:
    return FileProvider(
        DirectoryProviderContext(),
        DirectoryProviderConfig(file_path=path),
    )


class TestParsing:
    def test_loads_users_and_groups(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,alice@example.com,Alice Liddell,alice@example.com
            user,bob@example.com,Bob Builder,bob@example.com
            group,Producers,Data Producers,producers-guid
        """)
        provider = _make_provider(path)
        users = provider.search_users("a", top=20)
        groups = provider.search_groups("data", top=20)
        assert [p.id for p in users] == ["alice@example.com"]
        assert [p.display_name for p in groups] == ["Data Producers"]
        assert groups[0].type == PrincipalType.GROUP

    def test_falls_back_display_name_to_id(self, tmp_path: Path):
        # display_name column present but empty for one row -> falls
        # back to the id so the picker can still render a badge.
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,onlyid@example.com,,
        """)
        provider = _make_provider(path)
        results = provider.search_users("only", top=20)
        assert results[0].display_name == "onlyid@example.com"

    def test_skips_blank_rows(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            ,,,
            user,alice@example.com,Alice,alice@example.com
            ,,,
        """)
        provider = _make_provider(path)
        assert len(provider.search_users("a", top=20)) == 1

    def test_rejects_unknown_type(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            robot,alice@example.com,Alice,alice@example.com
        """)
        provider = _make_provider(path)
        with pytest.raises(DirectoryError, match="must be 'user' or 'group'"):
            provider.search_users("a", top=20)

    def test_rejects_missing_required_column(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id
            user,alice@example.com
        """)
        provider = _make_provider(path)
        with pytest.raises(DirectoryError, match="missing required columns"):
            provider.search_users("a", top=20)

    def test_rejects_blank_id(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,,Alice,alice@example.com
        """)
        provider = _make_provider(path)
        with pytest.raises(DirectoryError, match="id is required"):
            provider.search_users("a", top=20)


class TestSearch:
    def test_top_caps_results(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,a1@x,Alice 1,
            user,a2@x,Alice 2,
            user,a3@x,Alice 3,
        """)
        provider = _make_provider(path)
        assert len(provider.search_users("a", top=2)) == 2

    def test_prefix_search_is_case_insensitive(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,alice@example.com,Alice Liddell,
        """)
        provider = _make_provider(path)
        assert len(provider.search_users("ALI", top=20)) == 1

    def test_search_matches_against_id_too(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,bob.builder@example.com,Robert Builder,
        """)
        provider = _make_provider(path)
        assert len(provider.search_users("bob", top=20)) == 1

    def test_empty_query_short_circuits(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,alice@example.com,Alice,
        """)
        provider = _make_provider(path)
        assert provider.search_users("", top=20) == []


class TestCache:
    def test_re_reads_when_mtime_advances(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,alice@example.com,Alice,
        """)
        provider = _make_provider(path)
        assert len(provider.search_users("a", top=20)) == 1
        # Overwrite with two principals and bump mtime explicitly.
        Path(path).write_text(textwrap.dedent("""
            type,id,display_name,sub_label
            user,alice@example.com,Alice,
            user,andre@example.com,Andre,
        """).lstrip(), encoding="utf-8")
        os.utime(path, (time.time() + 5, time.time() + 5))
        assert len(provider.search_users("a", top=20)) == 2


class TestProbe:
    def test_test_succeeds_for_valid_file(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            type,id,display_name,sub_label
            user,alice@example.com,Alice,
        """)
        _make_provider(path).test()

    def test_test_fails_for_missing_file(self, tmp_path: Path):
        provider = _make_provider(str(tmp_path / "does-not-exist.csv"))
        with pytest.raises(DirectoryError, match="not found"):
            provider.test()

    def test_test_fails_for_malformed_csv(self, tmp_path: Path):
        path = _write_csv(tmp_path, """
            no,header,here
            user,foo,bar
        """)
        provider = _make_provider(path)
        with pytest.raises(DirectoryError):
            provider.test()


class TestConstruction:
    def test_requires_file_path(self):
        with pytest.raises(DirectoryError, match="required"):
            FileProvider(
                DirectoryProviderContext(),
                DirectoryProviderConfig(file_path=""),
            )
