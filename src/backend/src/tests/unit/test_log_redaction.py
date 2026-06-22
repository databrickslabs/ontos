"""Unit tests for ``common.logging.redact_sensitive_keys``.

These pin the redaction contract used by ``settings_routes.update_settings``
(and any future log lines that need to render request bodies safely). The
redactor must:

- Replace values whose key matches a known secret pattern with
  ``***REDACTED***``.
- Match case-insensitive substrings (so ``GITHUB_TOKEN`` and ``my_api_key``
  both redact).
- Recurse into nested dicts and lists.
- Leave benign keys alone — notably keys containing ``path`` such as
  ``WORKSPACE_DEPLOYMENT_PATH``, which are real settings, not secrets.
- Never mutate the original payload (the route still passes the real
  payload to the manager).
"""
from src.common.logging import redact_sensitive_keys


REDACTED = "***REDACTED***"


def test_empty_dict_passes_through():
    assert redact_sensitive_keys({}) == {}


def test_non_sensitive_keys_unchanged():
    payload = {
        "job_cluster_id": "abc123",
        "sync_enabled": True,
        "sync_repository": "git@example.com:org/repo.git",
        "enabled_jobs": ["job-a", "job-b"],
        "WORKSPACE_DEPLOYMENT_PATH": "/Workspace/ontos/dev",
    }
    assert redact_sensitive_keys(payload) == payload


def test_redacts_known_secret_keys():
    payload = {
        "github_token": "ghp_xxx",
        "github_pat": "ghp_yyy",
        "mcp_token": "tok_zzz",
        "password": "hunter2",
        "api_key": "ak_abc",
        "private_key": "-----BEGIN-----",
        "client_secret": "csec",
        "bearer_token": "btok",
        "user_credential": "ucred",
        "passwd": "pwd",
    }
    result = redact_sensitive_keys(payload)
    for k in payload:
        assert result[k] == REDACTED, f"{k} should be redacted"


def test_match_is_case_insensitive():
    assert redact_sensitive_keys({"GITHUB_TOKEN": "x"}) == {"GITHUB_TOKEN": REDACTED}
    assert redact_sensitive_keys({"My_Api_Key": "x"}) == {"My_Api_Key": REDACTED}
    assert redact_sensitive_keys({"PASSWORD": "x"}) == {"PASSWORD": REDACTED}


def test_substring_match_catches_nested_secret_words():
    payload = {
        "github_repo_token": "ghp_xxx",          # 'token' substring
        "user_api_key_field": "ak_abc",          # 'api_key' substring
        "external_bearer_value": "bv",           # 'bearer' substring
    }
    result = redact_sensitive_keys(payload)
    assert result == {
        "github_repo_token": REDACTED,
        "user_api_key_field": REDACTED,
        "external_bearer_value": REDACTED,
    }


def test_path_keys_not_redacted():
    # Regression guard: 'path' must not become a sensitive substring,
    # else WORKSPACE_DEPLOYMENT_PATH and similar settings get clobbered.
    payload = {
        "WORKSPACE_DEPLOYMENT_PATH": "/Workspace/ontos/dev",
        "volume_path": "/Volumes/main/default/x",
        "file_path": "/tmp/y",
        "deployment_path": "/foo",
    }
    assert redact_sensitive_keys(payload) == payload


def test_nested_dicts_recurse():
    payload = {
        "git": {
            "token": "ghp_xxx",
            "repository": "git@host:org/repo.git",
        },
        "llm": {
            "api_key": "ak_abc",
            "model": "claude-opus",
        },
    }
    result = redact_sensitive_keys(payload)
    assert result == {
        "git": {"token": REDACTED, "repository": "git@host:org/repo.git"},
        "llm": {"api_key": REDACTED, "model": "claude-opus"},
    }


def test_lists_of_dicts_recurse():
    payload = {
        "connections": [
            {"name": "snowflake", "client_secret": "csec1"},
            {"name": "bigquery", "credential": "csec2"},
            {"name": "databricks", "host": "h"},
        ],
    }
    result = redact_sensitive_keys(payload)
    assert result == {
        "connections": [
            {"name": "snowflake", "client_secret": REDACTED},
            {"name": "bigquery", "credential": REDACTED},
            {"name": "databricks", "host": "h"},
        ],
    }


def test_non_dict_input_passes_through():
    assert redact_sensitive_keys("a string") == "a string"
    assert redact_sensitive_keys(42) == 42
    assert redact_sensitive_keys(None) is None
    assert redact_sensitive_keys([1, 2, 3]) == [1, 2, 3]


def test_original_payload_not_mutated():
    original = {
        "github_token": "ghp_xxx",
        "nested": {"api_key": "ak_abc", "model": "claude-opus"},
    }
    snapshot = {"github_token": "ghp_xxx", "nested": {"api_key": "ak_abc", "model": "claude-opus"}}
    redact_sensitive_keys(original)
    assert original == snapshot, "redact_sensitive_keys must not mutate input"


def test_non_string_keys_do_not_crash():
    # Defensive: a dict with a non-string key (e.g. int) should pass through
    # without raising. The non-string key can't match a substring pattern.
    payload = {1: "a", "token": "x"}
    assert redact_sensitive_keys(payload) == {1: "a", "token": REDACTED}
