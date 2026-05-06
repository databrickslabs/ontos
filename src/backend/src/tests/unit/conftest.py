# Skip unit-test modules that are broken pending fixes.
#
# These tests were silently excluded from CI for a long time (testpaths only
# pointed at backend/tests), so they bit-rotted relative to current schemas
# and managers. We now collect the rest of backend/src/tests/unit/ so coverage
# reflects reality; the broken modules below are quarantined here so the
# coverage gate can ratchet up. Fix-and-remove one entry at a time.
#
# TODO(coverage): unquarantine each module after rewriting its fixtures.
collect_ignore = [
    "test_audit_manager.py",
    "test_comments_manager.py",
    "test_costs_manager.py",
    "test_data_products_manager.py",
    "test_llm_client.py",
    "test_metadata_manager.py",
    "test_notifications_manager.py",
    "test_search_manager.py",
    "test_security_features_manager.py",
    "test_semantic_links_manager.py",
    "test_settings_manager.py",
    "test_users_manager.py",
    "test_workflow_executor_scripts.py",
    "test_workflow_notification_channels.py",
]
