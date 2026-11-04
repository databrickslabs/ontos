"""Regression checks for permissions required by the Databricks App."""
from pathlib import Path

import yaml


MANIFEST_PATH = Path(__file__).resolve().parents[4] / 'manifest.yaml'


def test_manifest_requests_uc_domains_scope():
    """Domain sync must receive an OBO token authorized for UC Domains APIs."""
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())

    assert 'domains' in manifest['user_api_scopes']
