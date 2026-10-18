-- ============================================================================
-- ARF Demo Data — preset=arf
-- ============================================================================
-- Standalone demo pack loaded via:
--   POST /api/settings/demo-data/load?preset=arf
--
-- ARF v2 additions: Trade Promotion requires two prerequisite ARs (Market
-- Compliance + Budget Delegation), carries typed domain_context resource
-- refs, and is semantically linked to the "Trade Promotion" Business Concept
-- (urn:demo:concept:trade-promotion) so find_authority_for_concept can
-- locate it without a slug.
--
-- Four core Authority Relations covering distinct governance domains, each with:
--   • an AR-ladder maturity level cached on the row
--   • two authored Compliance-DSL criteria (every criterion must link to a
--     persisted compliance policy — authority_criteria.compliance_policy_id
--     is NOT NULL)
--   • three N-functional affirmation participants (approver and/or reviewer),
--     wired to Business Roles, so the Request-Review flow can mint
--     DataAssetReviewRequests from them
--   • a primary data-domain assignment via entity_domain_associations
--     (entity_type = 'authority_relation')
--
-- Dataset identifier: 0005 (sixth UUID group — retail=0000, hls=0001,
-- fsi=0002, mfg=0003, auto=0004)
-- UUID Format: {type:3}{seq:5}-0005-4000-8000-00000000000N
--
-- Type codes (second half of the UUID prefix):
--   000 = data_domains
--   011 = compliance_policies
--   031 = entity_domain_associations
--   0a0 = authority_relations
--   0a1 = authority_affirmations
--   0a2 = authority_criteria
--   0a3 = authority_prerequisites
--   0a4 = authority_resource_refs
--   015 = entity_semantic_links
--   0f0 = business_roles
--   0ff = maturity_levels (AR ladder)
-- ============================================================================

BEGIN;


-- ============================================================================
-- 1. DATA DOMAINS (ARF-specific, top-level — self-contained pack)
-- ============================================================================

INSERT INTO data_domains (id, name, description, parent_id, created_by, created_at, updated_at) VALUES
('00000001-0005-4000-8000-000000000001', 'Commercial Operations', 'Trade promotions, channel pricing, and go-to-market execution.',       NULL, 'system@demo', NOW(), NOW()),
('00000002-0005-4000-8000-000000000002', 'IT Security',           'Platform access, identity, and segregation-of-duties controls.',     NULL, 'system@demo', NOW(), NOW()),
('00000003-0005-4000-8000-000000000003', 'Platform Engineering',  'Ontos application platform and internal data-governance tooling.',   NULL, 'system@demo', NOW(), NOW()),
('00000004-0005-4000-8000-000000000004', 'Data Governance',       'Enterprise data-product lifecycle, stewardship, and retirement.',    NULL, 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2. COMPLIANCE POLICIES (ARF criteria sources)
-- ============================================================================
-- Every authority_criteria.compliance_policy_id must resolve, so these must
-- be inserted before the criteria section. Each AR consumes two of these.

INSERT INTO compliance_policies (id, name, description, failure_message, rule, category, severity, is_active, created_at, updated_at) VALUES
('01100001-0005-4000-8000-000000000001', 'Trade Promotion Budget Threshold',
 'Promotion requests above the VP sign-off threshold must carry explicit VP approval.',
 'Promotion budget exceeds the delegation threshold without the required VP sign-off.',
 'MATCH (p:PromotionProposal) ASSERT p.budget_usd <= 500000 OR p.has_vp_sign_off = true',
 'Governance', 'critical', true, NOW(), NOW()),

('01100002-0005-4000-8000-000000000002', 'Trade Promotion Margin Floor',
 'Promotions must preserve a minimum expected gross-margin percentage after discount.',
 'Expected margin after promotion discount is below the configured floor.',
 'MATCH (p:PromotionProposal) ASSERT p.expected_margin_pct >= 15',
 'Data Quality', 'high', true, NOW(), NOW()),

('01100003-0005-4000-8000-000000000003', 'Platform Access MFA Required',
 'Every production-platform access grant must be bound to an MFA-enabled identity.',
 'Access grant was issued to a principal that does not have MFA enabled.',
 'MATCH (g:AccessGrant) ASSERT g.mfa_enabled = true',
 'Security', 'critical', true, NOW(), NOW()),

('01100004-0005-4000-8000-000000000004', 'Platform Access Segregation of Duties',
 'Grants must not combine incompatible duties (eg deploy + approve-deploy on the same tier).',
 'Access grant combines duties that violate segregation-of-duties policy for this tier.',
 'MATCH (g:AccessGrant) ASSERT g.has_sod_conflict = false',
 'Security', 'high', true, NOW(), NOW()),

('01100005-0005-4000-8000-000000000005', 'Ontos Role Request Sponsor',
 'Every app-role request must be sponsored by a recognized Data Steward or Domain Owner.',
 'Role request has no sponsor, or the sponsor is not a Data Steward or Domain Owner.',
 'MATCH (r:RoleRequest) ASSERT r.sponsor_role IN [''Data Steward'', ''Domain Owner'']',
 'Governance', 'high', true, NOW(), NOW()),

('01100006-0005-4000-8000-000000000006', 'Ontos Role Request Expiry',
 'Elevated-role requests must carry an explicit expiry date (no indefinite grants).',
 'Role request does not carry an expiry date — indefinite grants are not permitted.',
 'MATCH (r:RoleRequest) ASSERT r.has_expiry_date = true',
 'Governance', 'medium', true, NOW(), NOW()),

('01100007-0005-4000-8000-000000000007', 'Data Product No Active Consumers',
 'A data product may be decommissioned only once it has zero active downstream consumers.',
 'Data product still has active downstream consumers and cannot be decommissioned.',
 'MATCH (d:DataProduct) ASSERT d.active_consumer_count = 0',
 'Data Quality', 'critical', true, NOW(), NOW()),

('01100008-0005-4000-8000-000000000008', 'Data Product Retention Plan Approved',
 'A decommission package must include a retention/archival plan signed off by the data owner.',
 'Decommission request has no approved retention/archival plan.',
 'MATCH (d:DataProduct) ASSERT d.retention_plan_approved = true',
 'Governance', 'high', true, NOW(), NOW()),

-- AR-maturity gate policies (wired into maturity_gates in section 4b). These
-- evaluate against the enriched AuthorityRelation dict surfaced by the
-- maturity evaluator (fully_affirmed, dna_measured, dna_within_ceiling, …) —
-- NOT against domain objects like PromotionProposal above.
('01100009-0005-4000-8000-000000000009', 'ARF Maturity — Authored',
 'An Authority Relation row exists (L1). Trivially true for anything that reaches the evaluator.',
 'Authority Relation entity type mismatch.',
 'MATCH (ar:AuthorityRelation) ASSERT ar.entity_type = ''AuthorityRelation''',
 'Governance', 'low', true, NOW(), NOW()),

('0110000a-0005-4000-8000-000000000010', 'ARF Maturity — Fully Attested',
 'Every required N-functional approver has affirmed the AR (L2).',
 'One or more required approvers have not yet affirmed.',
 'MATCH (ar:AuthorityRelation) ASSERT ar.fully_affirmed = true',
 'Governance', 'high', true, NOW(), NOW()),

('0110000b-0005-4000-8000-000000000011', 'ARF Maturity — DNA Measured',
 'A DNA-Coefficient has been computed from bound evidence at least once (L3).',
 'DNA-Coefficient has not yet been measured for this AR.',
 'MATCH (ar:AuthorityRelation) ASSERT ar.dna_measured = true',
 'Data Quality', 'medium', true, NOW(), NOW()),

('0110000c-0005-4000-8000-000000000012', 'ARF Maturity — DNA Within Ceiling',
 'The measured DNA-Coefficient is at or below the AR''s activation ceiling (L4).',
 'DNA-Coefficient exceeds the configured activation ceiling.',
 'MATCH (ar:AuthorityRelation) ASSERT ar.dna_within_ceiling = true',
 'Data Quality', 'high', true, NOW(), NOW()),

('0110000d-0005-4000-8000-000000000013', 'ARF Maturity — Agent-Called',
 'The AR has been invoked by agents (via MCP) more than 10 times — deterministic autonomous use (L5).',
 'The AR has not yet been called by agents in volume.',
 'MATCH (ar:AuthorityRelation) ASSERT ar.usage_count > 10',
 'Governance', 'medium', true, NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- Prerequisite-AR criteria (Market Compliance + Budget Delegation).
INSERT INTO compliance_policies (id, name, description, failure_message, rule, category, severity, is_active, created_at, updated_at) VALUES
('0110000e-0005-4000-8000-000000000014', 'Promotion Market Clearance',
 'Trade promotions may only run in markets cleared by commercial compliance.',
 'Promotion market is not cleared by commercial compliance.',
 'MATCH (p:PromotionProposal) ASSERT p.market IN [''DE'', ''AT'', ''CH'']',
 'Governance', 'high', true, NOW(), NOW()),

('0110000f-0005-4000-8000-000000000015', 'Promotion Budget Delegation Ceiling',
 'Promotion budgets above the regional delegation ceiling need group finance.',
 'Promotion budget exceeds the regional delegation ceiling.',
 'MATCH (p:PromotionProposal) ASSERT p.budget_usd <= 2000000',
 'Governance', 'critical', true, NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3. BUSINESS ROLES (participants referenced by AR affirmations)
-- ============================================================================

INSERT INTO business_roles (id, name, description, category, is_system, is_approver, status, created_by, created_at, updated_at) VALUES
('0f000001-0005-4000-8000-000000000001', 'Trade Marketing Director',    'Owns the trade-promotion plan and sign-off for proposals above the delegation threshold.', 'business',    false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000002-0005-4000-8000-000000000002', 'Finance Controller',          'Validates financial impact — budget, margin, and accrual — of commercial authority decisions.', 'business',    false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000003-0005-4000-8000-000000000003', 'Commercial Governance Lead',  'Independent governance over commercial authority definitions.', 'governance',  false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000004-0005-4000-8000-000000000004', 'Chief Information Security Officer', 'Accountable for platform-access authority and SoD policy.', 'governance', false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000005-0005-4000-8000-000000000005', 'Platform Operations Lead',    'Operates the production platform; validates that access grants are implementable.', 'operational', false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000006-0005-4000-8000-000000000006', 'Head of Infrastructure Engineering', 'Technical authority over the identity and infrastructure substrate.', 'technical', false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000007-0005-4000-8000-000000000007', 'Data Governance Officer',     'Governance for Ontos itself: role model, feature permissions, access requests.', 'governance',  false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000008-0005-4000-8000-000000000008', 'Application Owner',           'Business accountability for an Ontos deployment and its users.', 'business',    false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000009-0005-4000-8000-000000000009', 'Platform Admin',              'Technical administrator of the Ontos installation.', 'technical',   false, true,  'active', 'system@demo', NOW(), NOW()),
('0f00000a-0005-4000-8000-000000000010', 'Chief Data Officer',          'Enterprise accountability for the data-product portfolio and lifecycle.', 'governance',  false, true,  'active', 'system@demo', NOW(), NOW()),
('0f00000b-0005-4000-8000-000000000011', 'Data Product Owner',          'Owns a specific data product and signs off on its lifecycle transitions.', 'business',    false, true,  'active', 'system@demo', NOW(), NOW()),
('0f00000c-0005-4000-8000-000000000012', 'Enterprise Architect',        'Validates downstream impact and architectural dependencies of lifecycle moves.', 'technical', false, true,  'active', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4. MATURITY LEVELS (AR-specific ladder — entity_type = 'AuthorityRelation')
-- ============================================================================
-- The ARF ladder is distinct from the shared DP/DC default ladder. Each AR
-- row caches its achieved level_order; the gates (level → policy) are left
-- unseeded for the demo — the manager treats the cache as source-of-truth.

INSERT INTO maturity_levels (id, level_order, name, description, entity_type, created_at, updated_at) VALUES
('0ff00001-0005-4000-8000-000000000001', 1, 'Drafted',    'Authority is authored but has no participant sign-off yet.',               'AuthorityRelation', NOW(), NOW()),
('0ff00002-0005-4000-8000-000000000002', 2, 'Attested',   'All required N-functional affirmations have been collected.',             'AuthorityRelation', NOW(), NOW()),
('0ff00003-0005-4000-8000-000000000003', 3, 'Measured',   'A DNA-Coefficient has been computed from bound evidence at least once.',  'AuthorityRelation', NOW(), NOW()),
('0ff00004-0005-4000-8000-000000000004', 4, 'Converged',  'DNA-Coefficient is within threshold and stable across recent runs.',      'AuthorityRelation', NOW(), NOW()),
('0ff00005-0005-4000-8000-000000000005', 5, 'Autonomous', 'Agents call this authority deterministically via MCP; no human in loop.', 'AuthorityRelation', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4b. MATURITY GATES (level → compliance_policy)
-- ============================================================================
-- Without these, every level has zero required gates and the evaluator
-- vacuously passes every level — stamping every AR at the highest level
-- regardless of actual state. Wiring each level to a dedicated AR-level
-- policy makes the ladder meaningful: evaluation stops at the first failed
-- required gate (cumulative semantics).

INSERT INTO maturity_gates (id, maturity_level_id, compliance_policy_id, required, display_order, created_at) VALUES
('0fe00001-0005-4000-8000-000000000001', '0ff00001-0005-4000-8000-000000000001', '01100009-0005-4000-8000-000000000009', true, 0, NOW()),
('0fe00002-0005-4000-8000-000000000002', '0ff00002-0005-4000-8000-000000000002', '0110000a-0005-4000-8000-000000000010', true, 0, NOW()),
('0fe00003-0005-4000-8000-000000000003', '0ff00003-0005-4000-8000-000000000003', '0110000b-0005-4000-8000-000000000011', true, 0, NOW()),
('0fe00004-0005-4000-8000-000000000004', '0ff00004-0005-4000-8000-000000000004', '0110000c-0005-4000-8000-000000000012', true, 0, NOW()),
('0fe00005-0005-4000-8000-000000000005', '0ff00005-0005-4000-8000-000000000005', '0110000d-0005-4000-8000-000000000013', true, 0, NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5. AUTHORITY RELATIONS (the four demo ARs)
-- ============================================================================
-- Each AR is a single-version row for simplicity (version_family_id = id,
-- parent_relation_id = NULL, version = '1.0.0'). The manager accepts this
-- shape; versioning parity only becomes visible when a user clones a version.

INSERT INTO authority_relations (
  id, slug, name, description,
  status, version, version_family_id, parent_relation_id, base_name, change_summary, draft_owner_id,
  actor_role, actor_identity, actor_since, action,
  object_type, object_id, object_resolves_to,
  domain_context, justification_chain, decision_logic,
  evidence_binding, evidence_sources,
  dna_magnitude, dna_direction, dna_dimensions, dna_measured_at, dna_max_threshold, dna_scoring_config,
  schedule_cron,
  maturity_level_order, maturity_evaluated_at,
  usage_count, approved_count, denied_count,
  created_at, updated_at, created_by
) VALUES
-- ----------------------------------------------------------------------------
-- AR 1: Trade Promotion Budget Approval  (business authority, ARF-paper canonical)
-- ----------------------------------------------------------------------------
('0a000001-0005-4000-8000-000000000001',
 'trade-promotion-budget-approval',
 'Trade Promotion Budget Approval',
 'Who may approve a trade-promotion proposal, under what budget/margin bounds, and with which commercial governance oversight. Mirrors ARF §3.7 — Alpha Cola, modern-trade DE.',
 'active', '1.0.0', '0a000001-0005-4000-8000-000000000001', NULL, 'Trade Promotion Budget Approval', NULL, NULL,
 'Trade Marketing Director', 'trade.marketing.director@demo.local', NOW() - INTERVAL '180 days', 'approve',
 'data_product', NULL, '["urn:demo:brand:alpha-cola","urn:demo:channel:modern-trade","urn:demo:market:DE"]',
 '{"brand":"Alpha Cola","channel":"modern-trade","market":"DE","threshold_usd": 500000,"margin_floor_pct": 15}',
 '{"policy_id":"TP-POL-2024","doc_url":"https://wiki.demo.local/commercial/trade-promo-policy","effective_date":"2024-01-01","derived_from":"Commercial Policy Handbook 2024 §4.2"}',
 '{"allowed_principals":["role:Trade Marketing Director"],"threshold_usd": 500000,"required_affirmations": 3}',
 NULL,
 '[{"type":"delta_table","ref":"demo.commercial.promotion_approvals","column_map":{"amount":"budget_usd","margin":"expected_margin_pct"}}]',
 0.1500, 'actual-exceeds-documented',
 '{"people": 0.08,"policy": 0.07,"structural": 0.0}',
 NOW() - INTERVAL '6 hours', 0.3000, NULL,
 '0 6 * * 1',
 4, NOW() - INTERVAL '6 hours',
 142, 128, 14,
 NOW() - INTERVAL '210 days', NOW(), 'system@demo'),

-- ----------------------------------------------------------------------------
-- AR 2: Production Platform Access Grant  (IT security authority)
-- ----------------------------------------------------------------------------
('0a000002-0005-4000-8000-000000000002',
 'production-platform-access-grant',
 'Production Platform Access Grant',
 'Who may grant production-tier platform access, with MFA and segregation-of-duties required on every grant.',
 'active', '1.0.0', '0a000002-0005-4000-8000-000000000002', NULL, 'Production Platform Access Grant', NULL, NULL,
 'Chief Information Security Officer', 'ciso@demo.local', NOW() - INTERVAL '365 days', 'approve',
 'asset', NULL, '["urn:demo:env:production","urn:demo:tier:platform"]',
 '{"env":"production","tier":"platform","requires_mfa": true,"requires_sod_check": true}',
 '{"policy_id":"SEC-ACCESS-2025","doc_url":"https://wiki.demo.local/security/access-policy","effective_date":"2025-01-15","derived_from":"InfoSec Standard SEC-STD-07"}',
 '{"allowed_principals":["role:Chief Information Security Officer","role:Platform Operations Lead"],"required_affirmations": 2}',
 NULL,
 '[{"type":"delta_table","ref":"demo.security.access_grants","column_map":{"principal":"grantee_email","approved":"approved_flag"}}]',
 0.0800, 'documented-exceeds-actual',
 '{"people": 0.04,"policy": 0.04,"structural": 0.0}',
 NOW() - INTERVAL '12 hours', 0.3000, NULL,
 '0 2 * * *',
 4, NOW() - INTERVAL '12 hours',
 8, 7, 1,
 NOW() - INTERVAL '400 days', NOW(), 'system@demo'),

-- ----------------------------------------------------------------------------
-- AR 3: Ontos Role Request Approval  (meta-authority over Ontos itself; draft)
-- ----------------------------------------------------------------------------
('0a000003-0005-4000-8000-000000000003',
 'ontos-role-request-approval',
 'Ontos Role Request Approval',
 'Who may approve an application-role request inside Ontos, including the sponsor and expiry constraints that must hold. Still in draft — DNA not yet measured.',
 'draft', '1.0.0', '0a000003-0005-4000-8000-000000000003', NULL, 'Ontos Role Request Approval', NULL, NULL,
 'Data Governance Officer', 'data.governance.officer@demo.local', NULL, 'approve',
 'role_request', NULL, '["urn:demo:system:ontos","urn:demo:scope:feature-role"]',
 '{"system":"ontos","role_scope":"feature","role_type":"approver","requires_sponsor": true,"requires_expiry": true}',
 '{"policy_id":"ONTOS-RBAC-2025","doc_url":"https://docs.demo.local/ontos/rbac","effective_date":"2025-03-01"}',
 NULL,
 NULL,
 '[{"type":"delta_table","ref":"demo.ontos.role_requests","column_map":{"principal":"requester_email","sponsor_role":"sponsor_role"}}]',
 NULL, NULL,
 NULL,
 NULL, 0.3000, NULL,
 NULL,
 1, NULL,
 0, 0, 0,
 NOW() - INTERVAL '14 days', NOW(), 'system@demo'),

-- ----------------------------------------------------------------------------
-- AR 4: Published Data Product Decommissioning  (governance; needs_review)
-- ----------------------------------------------------------------------------
('0a000004-0005-4000-8000-000000000004',
 'data-product-decommissioning',
 'Published Data Product Decommissioning',
 'Who may retire a published data product, under what consumer-impact and retention-plan constraints. DNA is above threshold — the AR needs human review.',
 'needs_review', '1.0.0', '0a000004-0005-4000-8000-000000000004', NULL, 'Published Data Product Decommissioning', NULL, NULL,
 'Chief Data Officer', 'cdo@demo.local', NOW() - INTERVAL '540 days', 'approve',
 'data_product', NULL, '["urn:demo:lifecycle:decommission","urn:demo:scope:data-product"]',
 '{"status":"active","lifecycle_stage":"production","grace_period_days": 90,"notify_consumers": true}',
 '{"policy_id":"DP-LIFECYCLE-2025","doc_url":"https://docs.demo.local/governance/dp-lifecycle","effective_date":"2025-02-01","derived_from":"Data Lifecycle Standard §6"}',
 '{"allowed_principals":["role:Chief Data Officer","role:Data Product Owner"],"required_affirmations": 3,"grace_period_days": 90}',
 NULL,
 '[{"type":"delta_table","ref":"demo.catalog.data_product_usage","column_map":{"product_id":"product_id","consumers":"active_consumer_count"}}]',
 0.4200, 'actual-exceeds-documented',
 '{"people": 0.15,"policy": 0.22,"structural": 0.05}',
 NOW() - INTERVAL '3 days', 0.3000, NULL,
 '0 5 * * 1',
 3, NOW() - INTERVAL '3 days',
 47, 31, 16,
 NOW() - INTERVAL '120 days', NOW(), 'system@demo'),
-- ----------------------------------------------------------------------------
-- AR 5: Market Compliance Clearance  (prerequisite of AR 1)
-- ----------------------------------------------------------------------------
('0a000005-0005-4000-8000-000000000005',
 'market-compliance',
 'Market Compliance Clearance',
 'Whether a commercial action may run in the target market at all. Required before any trade-promotion approval.',
 'active', '1.0.0', '0a000005-0005-4000-8000-000000000005', NULL, 'Market Compliance Clearance', NULL, NULL,
 'Commercial Compliance Lead', 'commercial.compliance@demo.local', NOW() - INTERVAL '300 days', 'approve',
 'data_product', NULL, '["urn:demo:channel:modern-trade"]',
 '{"cleared_markets":"DE,AT,CH"}',
 '{"policy_id":"COM-COMPLIANCE-2024","doc_url":"https://wiki.demo.local/commercial/market-clearance","effective_date":"2024-01-01"}',
 NULL,
 NULL,
 NULL,
 0.0500, 'neutral',
 '{"people": 0.0,"policy": 0.05,"structural": 0.0}',
 NOW() - INTERVAL '1 day', 0.3000, NULL,
 NULL,
 4, NOW() - INTERVAL '1 day',
 0, 0, 0,
 NOW() - INTERVAL '300 days', NOW(), 'system@demo'),
-- ----------------------------------------------------------------------------
-- AR 6: Promotion Budget Delegation  (prerequisite of AR 1)
-- ----------------------------------------------------------------------------
('0a000006-0005-4000-8000-000000000006',
 'budget-delegation',
 'Promotion Budget Delegation',
 'Whether the promotion budget sits inside the regional finance delegation. Required before any trade-promotion approval.',
 'active', '1.0.0', '0a000006-0005-4000-8000-000000000006', NULL, 'Promotion Budget Delegation', NULL, NULL,
 'Regional Finance Controller', 'regional.finance@demo.local', NOW() - INTERVAL '300 days', 'approve',
 'data_product', NULL, NULL,
 '{"ceiling_usd": 2000000}',
 '{"policy_id":"FIN-DELEGATION-2024","doc_url":"https://wiki.demo.local/finance/delegation-of-authority","effective_date":"2024-01-01"}',
 NULL,
 NULL,
 NULL,
 0.0700, 'neutral',
 '{"people": 0.0,"policy": 0.07,"structural": 0.0}',
 NOW() - INTERVAL '1 day', 0.3000, NULL,
 NULL,
 4, NOW() - INTERVAL '1 day',
 0, 0, 0,
 NOW() - INTERVAL '300 days', NOW(), 'system@demo')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 6. AUTHORITY CRITERIA (two per AR, bound to pre-seeded compliance policies)
-- ============================================================================
-- Each criterion carries ARF-specific facets (direction, weight, dimension)
-- that the plain compliance policy cannot — the DNAco engine signs failures
-- by direction and weights them per the ``weight`` and ``dimension`` here.

INSERT INTO authority_criteria (id, relation_id, compliance_policy_id, direction, weight, dimension, display_order, enabled, created_at) VALUES
-- AR 1: Trade Promotion
('0a200001-0005-4000-8000-000000000001', '0a000001-0005-4000-8000-000000000001', '01100001-0005-4000-8000-000000000001', 'actual-exceeds-documented', 1.0, 'policy', 1, true, NOW()),
('0a200002-0005-4000-8000-000000000002', '0a000001-0005-4000-8000-000000000001', '01100002-0005-4000-8000-000000000002', 'documented-exceeds-actual', 0.8, 'people', 2, true, NOW()),
-- AR 2: Platform Access
('0a200003-0005-4000-8000-000000000003', '0a000002-0005-4000-8000-000000000002', '01100003-0005-4000-8000-000000000003', 'actual-exceeds-documented', 1.0, 'policy', 1, true, NOW()),
('0a200004-0005-4000-8000-000000000004', '0a000002-0005-4000-8000-000000000002', '01100004-0005-4000-8000-000000000004', 'actual-exceeds-documented', 1.0, 'policy', 2, true, NOW()),
-- AR 3: Ontos Role Request (draft — enabled but not yet measured)
('0a200005-0005-4000-8000-000000000005', '0a000003-0005-4000-8000-000000000003', '01100005-0005-4000-8000-000000000005', 'documented-exceeds-actual', 0.8, 'people', 1, true, NOW()),
('0a200006-0005-4000-8000-000000000006', '0a000003-0005-4000-8000-000000000003', '01100006-0005-4000-8000-000000000006', 'neutral',                   0.6, 'policy', 2, true, NOW()),
-- AR 4: DP Decommissioning
('0a200007-0005-4000-8000-000000000007', '0a000004-0005-4000-8000-000000000004', '01100007-0005-4000-8000-000000000007', 'actual-exceeds-documented', 1.0, 'policy',     1, true, NOW()),
('0a200008-0005-4000-8000-000000000008', '0a000004-0005-4000-8000-000000000004', '01100008-0005-4000-8000-000000000008', 'documented-exceeds-actual', 0.9, 'structural', 2, true, NOW()),
-- AR 5 / AR 6: prerequisite gates (one criterion each)
('0a200009-0005-4000-8000-000000000009', '0a000005-0005-4000-8000-000000000005', '0110000e-0005-4000-8000-000000000014', 'neutral', 1.0, 'policy', 1, true, NOW()),
('0a20000a-0005-4000-8000-000000000010', '0a000006-0005-4000-8000-000000000006', '0110000f-0005-4000-8000-000000000015', 'neutral', 1.0, 'policy', 1, true, NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 7. AUTHORITY AFFIRMATIONS (N-functional participants; approver + reviewer)
-- ============================================================================
-- Every AR gets 3 participants spanning categories. Some are flagged as
-- reviewers (is_reviewer=true, review_status='pending') so the user can mint
-- Asset Reviews from the AR detail page. principal is a raw email/group
-- string — no FK — and the demo user ``lars.george@databricks.com`` (admin
-- group ``admins``) is seeded as one of the approvers on each AR.

INSERT INTO authority_affirmations (
  id, relation_id, role, business_role_id, role_category, principal, principal_type,
  is_approver, is_reviewer, required, affirmed, affirmed_by, affirmed_at,
  review_status, review_answers, review_request_id,
  notes, sort_order
) VALUES
-- AR 1: Trade Promotion
('0a100001-0005-4000-8000-000000000001', '0a000001-0005-4000-8000-000000000001',
 'Trade Marketing Director', '0f000001-0005-4000-8000-000000000001', 'business',
 'lars.george@databricks.com', 'user',
 true, true, true, true, 'lars.george@databricks.com', NOW() - INTERVAL '45 days',
 'completed', '{"q1":"Yes — we sign off on all proposals above threshold weekly."}', NULL,
 'Primary business approver.', 0),

('0a100002-0005-4000-8000-000000000002', '0a000001-0005-4000-8000-000000000001',
 'Finance Controller', '0f000002-0005-4000-8000-000000000002', 'business',
 'finance.controller@demo.local', 'user',
 true, true, true, true, 'finance.controller@demo.local', NOW() - INTERVAL '42 days',
 'in_review', NULL, NULL,
 'Reviews financial impact and margin.', 1),

('0a100003-0005-4000-8000-000000000003', '0a000001-0005-4000-8000-000000000001',
 'Commercial Governance Lead', '0f000003-0005-4000-8000-000000000003', 'governance',
 'commercial.governance@demo.local', 'user',
 true, false, true, true, 'commercial.governance@demo.local', NOW() - INTERVAL '40 days',
 'na', NULL, NULL,
 'Independent governance oversight.', 2),

-- AR 2: Platform Access
('0a100004-0005-4000-8000-000000000004', '0a000002-0005-4000-8000-000000000002',
 'Chief Information Security Officer', '0f000004-0005-4000-8000-000000000004', 'governance',
 'ciso@demo.local', 'user',
 true, true, true, true, 'ciso@demo.local', NOW() - INTERVAL '120 days',
 'completed', '{"q1":"Grants are reviewed quarterly against baseline."}', NULL,
 'Accountable governance owner.', 0),

('0a100005-0005-4000-8000-000000000005', '0a000002-0005-4000-8000-000000000002',
 'Platform Operations Lead', '0f000005-0005-4000-8000-000000000005', 'operational',
 'platform.ops.lead@demo.local', 'user',
 true, true, true, true, 'platform.ops.lead@demo.local', NOW() - INTERVAL '118 days',
 'pending', NULL, NULL,
 'Validates implementability of grants.', 1),

('0a100006-0005-4000-8000-000000000006', '0a000002-0005-4000-8000-000000000002',
 'Head of Infrastructure Engineering', '0f000006-0005-4000-8000-000000000006', 'technical',
 'infra.eng.head@demo.local', 'user',
 true, false, true, true, 'infra.eng.head@demo.local', NOW() - INTERVAL '115 days',
 'na', NULL, NULL,
 'Technical substrate authority — affirmed.', 2),

-- AR 3: Ontos Role Request (draft — nobody affirmed yet; two reviewers staged)
('0a100007-0005-4000-8000-000000000007', '0a000003-0005-4000-8000-000000000003',
 'Data Governance Officer', '0f000007-0005-4000-8000-000000000007', 'governance',
 'lars.george@databricks.com', 'user',
 true, true, true, false, NULL, NULL,
 'pending', NULL, NULL,
 'Will chair the review.', 0),

('0a100008-0005-4000-8000-000000000008', '0a000003-0005-4000-8000-000000000003',
 'Application Owner', '0f000008-0005-4000-8000-000000000008', 'business',
 'app.owner@demo.local', 'user',
 true, true, true, false, NULL, NULL,
 'pending', NULL, NULL,
 'Business accountability for the Ontos deployment.', 1),

('0a100009-0005-4000-8000-000000000009', '0a000003-0005-4000-8000-000000000003',
 'Platform Admin', '0f000009-0005-4000-8000-000000000009', 'technical',
 'admins', 'group',
 true, false, true, false, NULL, NULL,
 'na', NULL, NULL,
 'Group-based technical approver.', 2),

-- AR 4: DP Decommissioning (needs_review — pending reviewer flow is the point)
('0a10000a-0005-4000-8000-000000000010', '0a000004-0005-4000-8000-000000000004',
 'Chief Data Officer', '0f00000a-0005-4000-8000-000000000010', 'governance',
 'cdo@demo.local', 'user',
 true, true, true, true, 'cdo@demo.local', NOW() - INTERVAL '15 days',
 'completed', '{"q1":"Lifecycle policy applies to all GA data products."}', NULL,
 'Governance accountability.', 0),

('0a10000b-0005-4000-8000-000000000011', '0a000004-0005-4000-8000-000000000004',
 'Data Product Owner', '0f00000b-0005-4000-8000-000000000011', 'business',
 'lars.george@databricks.com', 'user',
 true, true, true, true, 'lars.george@databricks.com', NOW() - INTERVAL '13 days',
 'in_review', NULL, NULL,
 'Signed off on the retention plan; review of DNA breach pending.', 1),

('0a10000c-0005-4000-8000-000000000012', '0a000004-0005-4000-8000-000000000004',
 'Enterprise Architect', '0f00000c-0005-4000-8000-000000000012', 'technical',
 'enterprise.architect@demo.local', 'user',
 true, true, true, true, 'enterprise.architect@demo.local', NOW() - INTERVAL '12 days',
 'pending', NULL, NULL,
 'Validates downstream architectural impact.', 2)
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 8. ENTITY_DOMAIN_ASSOCIATIONS (primary data-domain per AR)
-- ============================================================================
-- Uses the polymorphic association table with entity_type='authority_relation'
-- (the same string the AR manager uses when it hands domain assignments
-- through to the shared DataDomainsManager).

INSERT INTO entity_domain_associations (id, domain_id, entity_id, entity_type, is_primary, assigned_by, assigned_at) VALUES
('03100001-0005-4000-8000-000000000001', '00000001-0005-4000-8000-000000000001', '0a000001-0005-4000-8000-000000000001', 'authority_relation', true, 'system@demo', NOW()),
('03100002-0005-4000-8000-000000000002', '00000002-0005-4000-8000-000000000002', '0a000002-0005-4000-8000-000000000002', 'authority_relation', true, 'system@demo', NOW()),
('03100003-0005-4000-8000-000000000003', '00000003-0005-4000-8000-000000000003', '0a000003-0005-4000-8000-000000000003', 'authority_relation', true, 'system@demo', NOW()),
('03100004-0005-4000-8000-000000000004', '00000004-0005-4000-8000-000000000004', '0a000004-0005-4000-8000-000000000004', 'authority_relation', true, 'system@demo', NOW()),
('03100005-0005-4000-8000-000000000005', '00000001-0005-4000-8000-000000000001', '0a000005-0005-4000-8000-000000000005', 'authority_relation', true, 'system@demo', NOW()),
('03100006-0005-4000-8000-000000000006', '00000001-0005-4000-8000-000000000001', '0a000006-0005-4000-8000-000000000006', 'authority_relation', true, 'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 9. AUTHORITY PREREQUISITES (Trade Promotion requires AR 5 + AR 6)
-- ============================================================================
-- Edges are keyed by family slug, never by version id.

INSERT INTO authority_prerequisites (id, relation_family_slug, prerequisite_family_slug, required, display_order, notes, created_at) VALUES
('0a300001-0005-4000-8000-000000000001', 'trade-promotion-budget-approval', 'market-compliance', true, 0, 'Market must be cleared before any promotion approval.', NOW()),
('0a300002-0005-4000-8000-000000000002', 'trade-promotion-budget-approval', 'budget-delegation', true, 1, 'Budget must sit inside the regional delegation.', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 10. AUTHORITY RESOURCE REFS (typed pointers behind AR 1's domain_context)
-- ============================================================================

INSERT INTO authority_resource_refs (id, relation_id, field_path, ref_type, literal_value, entity_type, entity_id, mcp_result_pointer, created_at, updated_at) VALUES
('0a400001-0005-4000-8000-000000000001', '0a000001-0005-4000-8000-000000000001', 'domain_context.market', 'literal', 'DE', NULL, NULL, '$', NOW(), NOW()),
('0a400002-0005-4000-8000-000000000002', '0a000001-0005-4000-8000-000000000001', 'domain_context.brand', 'ontos_entity', NULL, 'business_concept', 'urn:demo:brand:alpha-cola', '$', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 11. ENTITY_SEMANTIC_LINKS (AR 1 family -> "Trade Promotion" concept)
-- ============================================================================
-- entity_id is the AR's version_family_id so the link survives version bumps.

INSERT INTO entity_semantic_links (id, entity_id, entity_type, iri, label, created_by, created_at) VALUES
('01500001-0005-4000-8000-000000000001', '0a000001-0005-4000-8000-000000000001', 'authority_relation', 'urn:demo:concept:trade-promotion', 'Trade Promotion', 'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


COMMIT;
