-- ADM v0.4: pinned subset read by Ontos Authority Resolution.
-- Ontos needs SELECT on this schema only. Ontos never writes to it.
CREATE SCHEMA IF NOT EXISTS `__CATALOG__`.`__SCHEMA__`;

-- ADM v0.4 section 5.2. Role definitions and candidate mandates.
CREATE TABLE IF NOT EXISTS `__CATALOG__`.`__SCHEMA__`.`roles` (
  role_id STRING COMMENT 'role_id',
  role_name STRING COMMENT 'role_name',
  domain STRING COMMENT 'domain',
  authority_scope STRING COMMENT 'authority_scope',
  permissions STRING COMMENT 'permissions',
  max_value DECIMAL(20,4) COMMENT 'max_value',
  currency STRING COMMENT 'currency',
  requires_approval_above DECIMAL(20,4) COMMENT 'requires_approval_above',
  policy_basis_id STRING COMMENT 'policy_basis_id',
  valid_from TIMESTAMP COMMENT 'valid_from',
  valid_to TIMESTAMP COMMENT 'valid_to',
  recorded_at TIMESTAMP COMMENT 'recorded_at',
  superseded_at TIMESTAMP COMMENT 'superseded_at'
)
USING DELTA
TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

-- ADM v0.4 section 5.3. Role assignments (read-only input for Ontos).
CREATE TABLE IF NOT EXISTS `__CATALOG__`.`__SCHEMA__`.`entitlements` (
  entitlement_id STRING COMMENT 'entitlement_id',
  entity_id STRING COMMENT 'entity_id',
  role_id STRING COMMENT 'role_id',
  domain_context STRING COMMENT 'domain_context',
  granted_by STRING COMMENT 'granted_by',
  granted_at TIMESTAMP COMMENT 'granted_at',
  valid_from TIMESTAMP COMMENT 'valid_from',
  valid_to TIMESTAMP COMMENT 'valid_to',
  conditions STRING COMMENT 'conditions',
  revoked_at TIMESTAMP COMMENT 'revoked_at',
  revocation_reason STRING COMMENT 'revocation_reason',
  evidence_id STRING COMMENT 'evidence_id',
  policy_basis_id STRING COMMENT 'policy_basis_id',
  claim_status STRING COMMENT 'claim_status',
  recorded_at TIMESTAMP COMMENT 'recorded_at',
  superseded_at TIMESTAMP COMMENT 'superseded_at'
)
USING DELTA
TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

-- ADM v0.4 section 5.4. Delegation lineage.
CREATE TABLE IF NOT EXISTS `__CATALOG__`.`__SCHEMA__`.`delegation_chains` (
  delegation_id STRING COMMENT 'delegation_id',
  grantor_entity_id STRING COMMENT 'grantor_entity_id',
  grantee_entity_id STRING COMMENT 'grantee_entity_id',
  role_id STRING COMMENT 'role_id',
  scope_restriction STRING COMMENT 'scope_restriction',
  valid_from TIMESTAMP COMMENT 'valid_from',
  valid_to TIMESTAMP COMMENT 'valid_to',
  justification STRING COMMENT 'justification',
  parent_delegation_id STRING COMMENT 'parent_delegation_id',
  max_sub_delegation_depth INT COMMENT 'max_sub_delegation_depth',
  requires_notification BOOLEAN COMMENT 'requires_notification',
  policy_basis_id STRING COMMENT 'policy_basis_id',
  evidence_id STRING COMMENT 'evidence_id',
  recorded_at TIMESTAMP COMMENT 'recorded_at',
  superseded_at TIMESTAMP COMMENT 'superseded_at'
)
USING DELTA
TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

-- ADM v0.4 section 6.1. Verified links from source aliases to canonical entities.
CREATE TABLE IF NOT EXISTS `__CATALOG__`.`__SCHEMA__`.`source_identity_map` (
  identity_link_id STRING COMMENT 'identity_link_id',
  entity_id STRING COMMENT 'entity_id',
  source_system STRING COMMENT 'source_system',
  source_tenant STRING COMMENT 'source_tenant',
  source_id STRING COMMENT 'source_id',
  match_method STRING COMMENT 'match_method',
  verification_status STRING COMMENT 'verification_status',
  evidence_id STRING COMMENT 'evidence_id',
  valid_from TIMESTAMP COMMENT 'valid_from',
  valid_to TIMESTAMP COMMENT 'valid_to',
  recorded_at TIMESTAMP COMMENT 'recorded_at',
  superseded_at TIMESTAMP COMMENT 'superseded_at'
)
USING DELTA
TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');

-- ADM v0.4 section 6.5. Observed decision events; the DNA-Coefficient evidence.
CREATE TABLE IF NOT EXISTS `__CATALOG__`.`__SCHEMA__`.`observed_decision_provenance` (
  observation_id STRING COMMENT 'observation_id',
  business_decision_id STRING COMMENT 'business_decision_id',
  action_code STRING COMMENT 'action_code',
  object_ref STRING COMMENT 'object_ref',
  actor_entity_id STRING COMMENT 'actor_entity_id',
  actor_role STRING COMMENT 'actor_role',
  event_at TIMESTAMP COMMENT 'event_at',
  recorded_at TIMESTAMP COMMENT 'recorded_at',
  decision_basis_ref STRING COMMENT 'decision_basis_ref',
  approval_evidence_id STRING COMMENT 'approval_evidence_id',
  source_evidence_id STRING COMMENT 'source_evidence_id',
  context STRING COMMENT 'context',
  observation_status STRING COMMENT 'observation_status',
  dna_contribution_flag BOOLEAN COMMENT 'dna_contribution_flag'
)
USING DELTA
TBLPROPERTIES ('ontos.adm_version' = 'ADM v0.4');
