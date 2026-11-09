"""Regression checks for permissions required by the Databricks App."""
from pathlib import Path

import yaml


MANIFEST_PATH = Path(__file__).resolve().parents[4] / 'manifest.yaml'


def test_manifest_does_not_request_unsupported_uc_domains_obo_scope():
    """Domain sync uses the app identity; Apps does not support a domains OBO scope."""
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())

    assert 'domains' not in manifest['user_api_scopes']
