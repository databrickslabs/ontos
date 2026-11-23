-- ADM v0.4 demo schema: fictitious data for Ontos Authority Resolution (ARF 1.2.0, #1294 slice 4).
--
-- Creates demo.arf_adm (the pinned subset, same DDL as adm_v0_4_ddl.sql) and fills it for
-- the demo Trade Promotion Budget Approval AR. Every identity, role and figure is invented.
-- Load it on a SQL warehouse, then grant the app service principal SELECT on demo.arf_adm
-- and set it as the shared ADM schema in Settings (or as the AR's override).
--
-- Re-running it replaces the demo data (the tables are emptied first).

CREATE SCHEMA IF NOT EXISTS `demo`.`arf_adm`;

CREATE TABLE IF NOT EXISTS `demo`.`arf_adm`.`roles` (
  role_id STRING, role_name STRING, domain STRING, authority_scope STRING, permissions STRING,
  max_value DECIMAL(20,4), currency STRING, requires_approval_above DECIMAL(20,4), policy_basis_id STRING,
  valid_from TIMESTAMP, valid_to TIMESTAMP, recorded_at TIMESTAMP, superseded_at TIMESTAMP
) USING DELTA TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

CREATE TABLE IF NOT EXISTS `demo`.`arf_adm`.`entitlements` (
  entitlement_id STRING, entity_id STRING, role_id STRING, domain_context STRING, granted_by STRING,
  granted_at TIMESTAMP, valid_from TIMESTAMP, valid_to TIMESTAMP, conditions STRING, revoked_at TIMESTAMP,
  revocation_reason STRING, evidence_id STRING, policy_basis_id STRING, claim_status STRING,
  recorded_at TIMESTAMP, superseded_at TIMESTAMP
) USING DELTA TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

CREATE TABLE IF NOT EXISTS `demo`.`arf_adm`.`delegation_chains` (
  delegation_id STRING, grantor_entity_id STRING, grantee_entity_id STRING, role_id STRING,
  scope_restriction STRING, valid_from TIMESTAMP, valid_to TIMESTAMP, justification STRING,
  parent_delegation_id STRING, max_sub_delegation_depth INT, requires_notification BOOLEAN,
  policy_basis_id STRING, evidence_id STRING, recorded_at TIMESTAMP, superseded_at TIMESTAMP
) USING DELTA TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

CREATE TABLE IF NOT EXISTS `demo`.`arf_adm`.`source_identity_map` (
  identity_link_id STRING, entity_id STRING, source_system STRING, source_tenant STRING, source_id STRING,
  match_method STRING, verification_status STRING, evidence_id STRING, valid_from TIMESTAMP,
  valid_to TIMESTAMP, recorded_at TIMESTAMP, superseded_at TIMESTAMP
) USING DELTA TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

CREATE TABLE IF NOT EXISTS `demo`.`arf_adm`.`observed_decision_provenance` (
  observation_id STRING, business_decision_id STRING, action_code STRING, object_ref STRING,
  actor_entity_id STRING, actor_role STRING, event_at TIMESTAMP, recorded_at TIMESTAMP,
  decision_basis_ref STRING, approval_evidence_id STRING, source_evidence_id STRING, context STRING,
  observation_status STRING, dna_contribution_flag BOOLEAN
) USING DELTA TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

DELETE FROM `demo`.`arf_adm`.`observed_decision_provenance` WHERE true;
DELETE FROM `demo`.`arf_adm`.`source_identity_map` WHERE true;
DELETE FROM `demo`.`arf_adm`.`entitlements` WHERE true;
DELETE FROM `demo`.`arf_adm`.`delegation_chains` WHERE true;
DELETE FROM `demo`.`arf_adm`.`roles` WHERE true;

-- Roles: the Trade Marketing Director role carries the approve code (the AR's actor role).
INSERT INTO `demo`.`arf_adm`.`roles`
VALUES
  ('Trade Marketing Director', 'Trade Marketing Director', 'PROCUREMENT', 'REGIONAL',
   '["approve", "escalate"]', 500000.0000, 'USD', 250000.0000, 'TP-POL-2024',
   TIMESTAMP '2024-01-01 00:00:00', NULL, TIMESTAMP '2024-01-01 00:00:00', NULL),
  ('Regional Finance Controller', 'Regional Finance Controller', 'FINANCE', 'REGIONAL',
   '["approve"]', 2000000.0000, 'USD', NULL, 'TP-POL-2024',
   TIMESTAMP '2024-01-01 00:00:00', NULL, TIMESTAMP '2024-01-01 00:00:00', NULL);

-- Identity: one VERIFIED link (read) and one PENDING link (ignored: the actor is unknown).
INSERT INTO `demo`.`arf_adm`.`source_identity_map`
VALUES
  ('link-0001', 'ent-trade-marketing-director', 'workday', 'demo-tenant', 'trade.marketing.director@demo.local',
   'AUTHORITATIVE_ID', 'VERIFIED', 'ev-hr-0001', TIMESTAMP '2024-01-01 00:00:00', NULL,
   TIMESTAMP '2024-01-02 00:00:00', NULL),
  ('link-0002', 'ent-regional-finance', 'workday', 'demo-tenant', 'regional.finance@demo.local',
   'VERIFIED_LINK', 'PENDING', 'ev-hr-0002', TIMESTAMP '2024-01-01 00:00:00', NULL,
   TIMESTAMP '2024-01-02 00:00:00', NULL);

-- Entitlements: the verified director holds the role. The finance controller's is revoked.
INSERT INTO `demo`.`arf_adm`.`entitlements`
VALUES
  ('ent-0001', 'ent-trade-marketing-director', 'Trade Marketing Director', '{"market": "DE", "channel": "modern-trade"}',
   'ent-cmo-office', TIMESTAMP '2024-01-05 00:00:00', TIMESTAMP '2024-01-05 00:00:00', NULL, NULL, NULL, NULL,
   'ev-appt-0001', 'TP-POL-2024', 'VERIFIED', TIMESTAMP '2024-01-05 00:00:00', NULL),
  ('ent-0002', 'ent-regional-finance', 'Regional Finance Controller', '{"market": "DE"}',
   'ent-cfo-office', TIMESTAMP '2024-01-05 00:00:00', TIMESTAMP '2024-01-05 00:00:00', NULL, NULL,
   TIMESTAMP '2025-06-01 00:00:00', 'role moved to another region', 'ev-appt-0002', 'TP-POL-2024', 'VERIFIED',
   TIMESTAMP '2024-01-05 00:00:00', NULL);

-- No delegations in the demo: the delegation fact reads false.

-- Observed decisions: 120 budget approvals over the last 60 days, on three promotions.
-- About one in seven actors is an unidentified contractor (the link is not VERIFIED), and one
-- in four approvals is escalated (the VP sign-off rule reads it). Fully generated from range().
INSERT INTO `demo`.`arf_adm`.`observed_decision_provenance`
SELECT
  concat('obs-', lpad(cast(id AS STRING), 4, '0')),
  concat('bd-trade-', cast(id AS STRING)),
  'approve',
  concat('dp:trade-promotion-', cast(id % 3 AS STRING)),
  CASE WHEN id % 7 = 0 THEN 'ent-unidentified-contractor' ELSE 'ent-trade-marketing-director' END,
  CASE WHEN id % 5 = 0 THEN 'RECOMMENDER' ELSE 'APPROVER' END,
  current_timestamp() - make_dt_interval(cast(id % 60 AS INT), 6, 0, 0),
  current_timestamp() - make_dt_interval(cast(id % 60 AS INT), 5, 0, 0),
  NULL,
  concat('ev-approval-', cast(id AS STRING)),
  NULL,
  concat('{"value": "', cast(12 + id % 6 AS STRING), '%", "budget_usd": ', cast(150000 + id * 1000 AS STRING),
         ', "market": "DE", "channel": "modern-trade", "escalated": ',
         CASE WHEN id % 4 = 0 THEN 'true' ELSE 'false' END, '}'),
  'REPORTED',
  true
FROM range(1, 121);
