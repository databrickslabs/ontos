-- ============================================================================
-- Schema catchup helper for older Ontos deployments
-- ============================================================================
-- WHAT
--   ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS for columns the
--   ORM/code now expects but that may be missing on environments where
--   alembic migrations weren't fully applied (e.g. dev workspaces that
--   started before a particular revision landed).
--
-- WHY THIS LIVES IN data/ AND NOT alembic/
--   These statements DO mirror what alembic migrations do at runtime —
--   `e2_semantic_models_display_name`, `aa9_add_is_approver_to_business_roles`,
--   etc. — but they're kept here as a manual fallback because the loader
--   surface is reachable from the running app (POST /api/settings/demo-data/load
--   ?industry=migrate, admin-only) without needing alembic CLI access. Useful
--   when a deployed app is in a stuck-migration state and the operator wants a
--   non-destructive idempotent fixup.
--
-- HOW TO USE
--   POST /api/settings/demo-data/load?industry=migrate (Admin role required).
--   Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS guards).
--
-- IS THIS DEMO DATA? No. Despite the file naming convention shared with
--   demo_data_*.sql, this contains zero seed rows — only schema additions.
--   The naming reflects the loader endpoint shape, not the file's purpose.
-- ============================================================================

BEGIN;

-- === semantic_models ===
ALTER TABLE semantic_models ADD COLUMN IF NOT EXISTS display_name VARCHAR;

-- === data_contract_team: add ALL columns the code expects ===
ALTER TABLE data_contract_team ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_team ADD COLUMN IF NOT EXISTS name VARCHAR;
ALTER TABLE data_contract_team ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE data_contract_team ADD COLUMN IF NOT EXISTS date_in VARCHAR;
ALTER TABLE data_contract_team ADD COLUMN IF NOT EXISTS date_out VARCHAR;
ALTER TABLE data_contract_team ADD COLUMN IF NOT EXISTS replaced_by_username VARCHAR;

-- === data_contract_support: add ALL columns ===
ALTER TABLE data_contract_support ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_support ADD COLUMN IF NOT EXISTS invitation_url VARCHAR;

-- === data_contract_servers ===
ALTER TABLE data_contract_servers ADD COLUMN IF NOT EXISTS stable_id VARCHAR;

-- === stable_id on all other contract child tables ===
ALTER TABLE data_contract_authoritative_definitions ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_custom_properties ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_roles ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_sla_properties ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_schema_objects ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_schema_properties ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_schema_object_authoritative_definitions ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_schema_object_custom_properties ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_schema_property_authoritative_definitions ADD COLUMN IF NOT EXISTS stable_id VARCHAR;
ALTER TABLE data_contract_quality_checks ADD COLUMN IF NOT EXISTS stable_id VARCHAR;

-- === Missing tables ===
CREATE TABLE IF NOT EXISTS data_contract_team_metadata (
    id VARCHAR PRIMARY KEY,
    contract_id VARCHAR NOT NULL REFERENCES data_contracts(id) ON DELETE CASCADE,
    stable_id VARCHAR, name VARCHAR, description TEXT,
    tags_json TEXT, custom_properties_json TEXT, authoritative_definitions_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_dc_team_metadata_cid ON data_contract_team_metadata(contract_id);

-- === Workflow snapshot columns (PRD #242) ===
ALTER TABLE agreement_wizard_sessions ADD COLUMN IF NOT EXISTS workflow_snapshot TEXT;
ALTER TABLE agreement_wizard_sessions ADD COLUMN IF NOT EXISTS workflow_name VARCHAR(255);
ALTER TABLE agreements ADD COLUMN IF NOT EXISTS workflow_snapshot TEXT;
ALTER TABLE agreements ADD COLUMN IF NOT EXISTS workflow_name VARCHAR(255);
ALTER TABLE agreements ADD COLUMN IF NOT EXISTS workflow_version INTEGER;

COMMIT;
