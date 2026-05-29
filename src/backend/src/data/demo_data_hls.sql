-- ============================================================================
-- HLS Demo Data — preset=hls
-- ============================================================================
-- Standalone demo pack loaded via:
--   POST /api/settings/demo-data/load?preset=hls
--
-- This pack is fully self-contained: loading it on an empty database produces
-- a complete Health & Life Sciences vertical demo with no implicit content from
-- any other preset.
--
-- Dataset identifier: 0001 (second UUID group)
-- UUID Format: {type:3}{seq:5}-0001-4000-8000-00000000000N
-- ============================================================================

BEGIN;

-- ============================================================================
-- 0. SHARED PARENT ROWS (idempotent foundation)
-- ============================================================================
-- HLS data_domains FK to base "Core" and "Finance" parents below.
-- Inserted with ON CONFLICT DO NOTHING so it is safe to load this preset on
-- top of an empty DB or alongside other presets.

INSERT INTO data_domains (id, name, description, parent_id, created_by, created_at, updated_at) VALUES
('00000001-0000-4000-8000-000000000001', 'Core', 'General, cross-company business concepts.', NULL, 'system@demo', NOW(), NOW()),
('00000002-0000-4000-8000-000000000002', 'Finance', 'Financial accounting, reporting, and metrics.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 1. DATA DOMAINS (HLS-specific, children of Core)
-- ============================================================================

INSERT INTO data_domains (id, name, description, parent_id, created_by, created_at, updated_at) VALUES
('00000001-0001-4000-8000-000000000001', 'Clinical', 'Clinical operations, patient data, and care delivery.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000002-0001-4000-8000-000000000002', 'Research', 'Clinical trials, research studies, and experimental data.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000003-0001-4000-8000-000000000003', 'Regulatory', 'FDA submissions, compliance filings, and audit trails.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000004-0001-4000-8000-000000000004', 'Genomics', 'Genomic sequencing, biomarkers, and precision medicine.', '00000002-0001-4000-8000-000000000002', 'system@demo', NOW(), NOW()),
('00000005-0001-4000-8000-000000000005', 'Pharmacy', 'Drug inventory, prescriptions, and dispensing operations.', '00000001-0001-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000006-0001-4000-8000-000000000006', 'Claims', 'Insurance claims processing, adjudication, and reimbursement.', '00000002-0000-4000-8000-000000000002', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2. TEAMS
-- ============================================================================

INSERT INTO teams (id, name, title, description, domain_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00100001-0001-4000-8000-000000000001', 'clinical-data', 'Clinical Data Team', 'Manages EHR integration, patient data pipelines, and clinical analytics', '00000001-0001-4000-8000-000000000001', '{"slack_channel": "https://company.slack.com/channels/clinical-data", "lead": "dr.chen@hospital.org"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100002-0001-4000-8000-000000000002', 'research-and-dev', 'Research & Development Team', 'Clinical trial data management, study design analytics, and biostatistics', '00000002-0001-4000-8000-000000000002', '{"slack_channel": "https://company.slack.com/channels/rd-data", "tools": ["SAS", "R", "Python", "REDCap"]}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100003-0001-4000-8000-000000000003', 'regulatory-affairs', 'Regulatory Affairs Team', 'FDA/EMA submission preparation, pharmacovigilance, and compliance monitoring', '00000003-0001-4000-8000-000000000003', '{"slack_channel": "https://company.slack.com/channels/reg-affairs", "responsibilities": ["FDA 21 CFR Part 11", "HIPAA", "GxP"]}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2b. TEAM MEMBERS
-- ============================================================================

INSERT INTO team_members (id, team_id, member_type, member_identifier, app_role_override, added_by, created_at, updated_at) VALUES
('00200001-0001-4000-8000-000000000001', '00100001-0001-4000-8000-000000000001', 'user', 'dr.chen@hospital.org', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200002-0001-4000-8000-000000000002', '00100001-0001-4000-8000-000000000001', 'group', 'clinical-informatics', NULL, 'system@demo', NOW(), NOW()),
('00200003-0001-4000-8000-000000000003', '00100002-0001-4000-8000-000000000002', 'user', 'dr.patel@pharma.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200004-0001-4000-8000-000000000004', '00100002-0001-4000-8000-000000000002', 'group', 'biostatisticians', NULL, 'system@demo', NOW(), NOW()),
('00200005-0001-4000-8000-000000000005', '00100003-0001-4000-8000-000000000003', 'user', 'sarah.compliance@pharma.com', 'Data Steward', 'system@demo', NOW(), NOW()),
('00200006-0001-4000-8000-000000000006', '00100003-0001-4000-8000-000000000003', 'group', 'regulatory-team', NULL, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3. PROJECTS
-- ============================================================================

INSERT INTO projects (id, name, title, description, project_type, owner_team_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00300001-0001-4000-8000-000000000001', 'patient-360', 'Patient 360 Platform', 'Unified patient view integrating EHR, claims, genomics, and social determinants of health', 'TEAM', '00100001-0001-4000-8000-000000000001', '{"budget": "$1.2M", "timeline": "12 months", "compliance": ["HIPAA", "HITECH"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300002-0001-4000-8000-000000000002', 'clinical-trial-analytics', 'Clinical Trial Analytics', 'Advanced analytics for clinical trial site selection, patient recruitment, and endpoint analysis', 'TEAM', '00100002-0001-4000-8000-000000000002', '{"budget": "$800K", "timeline": "9 months", "compliance": ["ICH-GCP", "21 CFR Part 11"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300003-0001-4000-8000-000000000003', 'drug-safety-monitoring', 'Drug Safety Monitoring', 'Pharmacovigilance signal detection and adverse event reporting automation', 'TEAM', '00100003-0001-4000-8000-000000000003', '{"budget": "$600K", "timeline": "6 months", "compliance": ["FDA FAERS", "EMA EudraVigilance"], "priority": "critical"}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3b. PROJECT-TEAM ASSOCIATIONS
-- ============================================================================

INSERT INTO project_teams (project_id, team_id, assigned_by, assigned_at) VALUES
('00300001-0001-4000-8000-000000000001', '00100001-0001-4000-8000-000000000001', 'system@demo', NOW()),
('00300001-0001-4000-8000-000000000001', '00100002-0001-4000-8000-000000000002', 'system@demo', NOW()),
('00300002-0001-4000-8000-000000000002', '00100002-0001-4000-8000-000000000002', 'system@demo', NOW()),
('00300002-0001-4000-8000-000000000002', '00100003-0001-4000-8000-000000000003', 'system@demo', NOW()),
('00300003-0001-4000-8000-000000000003', '00100003-0001-4000-8000-000000000003', 'system@demo', NOW()),
('00300003-0001-4000-8000-000000000003', '00100001-0001-4000-8000-000000000001', 'system@demo', NOW())

ON CONFLICT (project_id, team_id) DO NOTHING;


-- ============================================================================
-- 4. DATA CONTRACTS
-- ============================================================================

INSERT INTO data_contracts (id, name, kind, api_version, version, status, published, owner_team_id, domain_id, description_purpose, description_usage, description_limitations, publication_scope, created_by, updated_by, created_at, updated_at, version_family_id) VALUES
('00400001-0001-4000-8000-000000000001', 'Patient EHR Data Contract', 'DataContract', 'v3.1.0', '2.0.0', 'active', true, '00100001-0001-4000-8000-000000000001', '00000001-0001-4000-8000-000000000001', 'Standardized patient electronic health record data for clinical analytics and care coordination', 'Integrate into clinical dashboards, care pathway analysis, and population health management', 'All PHI must be de-identified for analytics; HIPAA Safe Harbor rules apply; data retention 7 years per state regulations', 'org', 'system@demo', 'system@demo', NOW(), NOW(), '00400001-0001-4000-8000-000000000001'),
('00400002-0001-4000-8000-000000000002', 'Clinical Trial Data Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100002-0001-4000-8000-000000000002', '00000002-0001-4000-8000-000000000002', 'Clinical trial enrollment, randomization, endpoint, and adverse event data', 'Support study monitoring, interim analyses, DSMB reporting, and regulatory submissions', 'Subject-level data requires IRB approval; blinded data restricted until study unblinding; 21 CFR Part 11 compliant', 'org', 'system@demo', 'system@demo', NOW(), NOW(), '00400002-0001-4000-8000-000000000002'),
('00400003-0001-4000-8000-000000000003', 'Adverse Event Reporting Contract', 'DataContract', 'v3.1.0', '1.1.0', 'active', true, '00100003-0001-4000-8000-000000000003', '00000003-0001-4000-8000-000000000003', 'Spontaneous and solicited adverse event reports for pharmacovigilance signal detection', 'Feed into safety signal detection algorithms, periodic safety reports (PSURs), and FDA FAERS submissions', 'MedDRA coding required; reporter identities must be anonymized; 15-day expedited reporting for serious AEs', 'org', 'system@demo', 'system@demo', NOW(), NOW(), '00400003-0001-4000-8000-000000000003'),
('00400004-0001-4000-8000-000000000004', 'Genomic Sequencing Contract', 'DataContract', 'v3.1.0', '1.0.0', 'draft', false, '00100002-0001-4000-8000-000000000002', '00000004-0001-4000-8000-000000000004', 'Whole genome and exome sequencing data for precision medicine research', 'Variant calling pipelines, biomarker discovery, and companion diagnostic development', 'Consent-gated access; re-identification risk assessment required; GINA compliance mandatory', 'none', 'system@demo', 'system@demo', NOW(), NOW(), '00400004-0001-4000-8000-000000000004'),
('00400005-0001-4000-8000-000000000005', 'Claims & Reimbursement Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100001-0001-4000-8000-000000000001', '00000006-0001-4000-8000-000000000006', 'Healthcare insurance claims, adjudication outcomes, and reimbursement data', 'Revenue cycle analytics, denial management, and payer contract optimization', 'CMS HCPCS/CPT coding standards; member SSN must be masked; data shared under BAA only', 'org', 'system@demo', 'system@demo', NOW(), NOW(), '00400005-0001-4000-8000-000000000005')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4b. DATA CONTRACT SCHEMA OBJECTS
-- ============================================================================

INSERT INTO data_contract_schema_objects (id, contract_id, name, logical_type, physical_name, description) VALUES
-- Patient EHR
('00500001-0001-4000-8000-000000000001', '00400001-0001-4000-8000-000000000001', 'patients', 'object', 'ehr.patients_master', 'Patient demographics and identifiers'),
('00500002-0001-4000-8000-000000000002', '00400001-0001-4000-8000-000000000001', 'encounters', 'object', 'ehr.encounters', 'Clinical encounters (inpatient, outpatient, ED)'),
('00500003-0001-4000-8000-000000000003', '00400001-0001-4000-8000-000000000001', 'diagnoses', 'object', 'ehr.diagnoses', 'ICD-10 coded diagnoses per encounter'),

-- Clinical Trials
('00500004-0001-4000-8000-000000000004', '00400002-0001-4000-8000-000000000002', 'subjects', 'object', 'trials.subjects', 'Trial subject enrollment and demographics'),
('00500005-0001-4000-8000-000000000005', '00400002-0001-4000-8000-000000000002', 'visits', 'object', 'trials.scheduled_visits', 'Protocol-defined visit schedule and completion'),
('00500006-0001-4000-8000-000000000006', '00400002-0001-4000-8000-000000000002', 'endpoints', 'object', 'trials.endpoint_results', 'Primary and secondary endpoint measurements'),

-- Adverse Events
('00500007-0001-4000-8000-000000000007', '00400003-0001-4000-8000-000000000003', 'adverse_events', 'object', 'safety.adverse_events', 'Individual case safety reports (ICSRs)'),
('00500008-0001-4000-8000-000000000008', '00400003-0001-4000-8000-000000000003', 'signal_assessments', 'object', 'safety.signal_assessments', 'Pharmacovigilance signal detection results'),

-- Claims
('00500009-0001-4000-8000-000000000009', '00400005-0001-4000-8000-000000000005', 'claims', 'object', 'claims.medical_claims', 'Professional and facility claims'),
('0050000a-0001-4000-8000-000000000010', '00400005-0001-4000-8000-000000000005', 'remittances', 'object', 'claims.remittance_advice', 'ERA/EOB payment details')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4c. DATA CONTRACT SCHEMA PROPERTIES
-- ============================================================================

INSERT INTO data_contract_schema_properties (id, object_id, name, logical_type, required, "unique", primary_key, partitioned, primary_key_position, partition_key_position, critical_data_element, transform_description) VALUES
-- patients table
('00600001-0001-4000-8000-000000000001', '00500001-0001-4000-8000-000000000001', 'patient_id', 'string', true, true, true, false, 1, -1, true, 'De-identified patient identifier (hash of MRN)'),
('00600002-0001-4000-8000-000000000002', '00500001-0001-4000-8000-000000000001', 'date_of_birth', 'date', true, false, false, false, -1, -1, true, 'Patient date of birth (shifted per Safe Harbor)'),
('00600003-0001-4000-8000-000000000003', '00500001-0001-4000-8000-000000000001', 'gender', 'string', true, false, false, false, -1, -1, false, 'Administrative gender (M, F, O, U)'),
('00600004-0001-4000-8000-000000000004', '00500001-0001-4000-8000-000000000001', 'race_ethnicity', 'string', false, false, false, false, -1, -1, false, 'OMB race/ethnicity category'),
('00600005-0001-4000-8000-000000000005', '00500001-0001-4000-8000-000000000001', 'zip_3', 'string', false, false, false, false, -1, -1, false, 'First 3 digits of ZIP code (Safe Harbor)'),

-- encounters table
('00600006-0001-4000-8000-000000000006', '00500002-0001-4000-8000-000000000002', 'encounter_id', 'string', true, true, true, false, 1, -1, true, 'Unique encounter identifier'),
('00600007-0001-4000-8000-000000000007', '00500002-0001-4000-8000-000000000002', 'patient_id', 'string', true, false, false, false, -1, -1, true, 'FK to patients.patient_id'),
('00600008-0001-4000-8000-000000000008', '00500002-0001-4000-8000-000000000002', 'encounter_type', 'string', true, false, false, false, -1, -1, false, 'inpatient, outpatient, emergency, observation'),
('00600009-0001-4000-8000-000000000009', '00500002-0001-4000-8000-000000000002', 'admit_date', 'timestamp', true, false, false, true, -1, 1, false, 'Admission or visit date (UTC)'),
('0060000a-0001-4000-8000-000000000010', '00500002-0001-4000-8000-000000000002', 'discharge_date', 'timestamp', false, false, false, false, -1, -1, false, 'Discharge date (NULL if still admitted)'),

-- subjects table
('0060000b-0001-4000-8000-000000000011', '00500004-0001-4000-8000-000000000004', 'subject_id', 'string', true, true, true, false, 1, -1, true, 'Randomization ID'),
('0060000c-0001-4000-8000-000000000012', '00500004-0001-4000-8000-000000000004', 'study_id', 'string', true, false, false, false, -1, -1, true, 'Protocol number'),
('0060000d-0001-4000-8000-000000000013', '00500004-0001-4000-8000-000000000004', 'arm', 'string', true, false, false, false, -1, -1, false, 'Treatment arm assignment'),
('0060000e-0001-4000-8000-000000000014', '00500004-0001-4000-8000-000000000004', 'enrollment_date', 'date', true, false, false, false, -1, -1, false, 'Date of informed consent'),
('0060000f-0001-4000-8000-000000000015', '00500004-0001-4000-8000-000000000004', 'status', 'string', true, false, false, false, -1, -1, false, 'enrolled, completed, withdrawn, screen_failure'),

-- adverse_events table
('00600010-0001-4000-8000-000000000016', '00500007-0001-4000-8000-000000000007', 'case_id', 'string', true, true, true, false, 1, -1, true, 'ICSR case number'),
('00600011-0001-4000-8000-000000000017', '00500007-0001-4000-8000-000000000007', 'meddra_pt', 'string', true, false, false, false, -1, -1, true, 'MedDRA Preferred Term'),
('00600012-0001-4000-8000-000000000018', '00500007-0001-4000-8000-000000000007', 'seriousness', 'string', true, false, false, false, -1, -1, true, 'serious, non_serious'),
('00600013-0001-4000-8000-000000000019', '00500007-0001-4000-8000-000000000007', 'onset_date', 'date', true, false, false, false, -1, -1, false, 'Date of AE onset'),
('00600014-0001-4000-8000-000000000020', '00500007-0001-4000-8000-000000000007', 'outcome', 'string', true, false, false, false, -1, -1, false, 'recovered, recovering, not_recovered, fatal, unknown'),

-- diagnoses table (00500003 — Patient EHR)
('00600015-0001-4000-8000-000000000021', '00500003-0001-4000-8000-000000000003', 'diagnosis_id', 'string', true, true, true, false, 1, -1, true, 'Unique diagnosis row identifier'),
('00600016-0001-4000-8000-000000000022', '00500003-0001-4000-8000-000000000003', 'encounter_id', 'string', true, false, false, false, -1, -1, true, 'FK to encounters.encounter_id'),
('00600017-0001-4000-8000-000000000023', '00500003-0001-4000-8000-000000000003', 'icd10_code', 'string', true, false, false, false, -1, -1, true, 'ICD-10-CM diagnosis code'),
('00600018-0001-4000-8000-000000000024', '00500003-0001-4000-8000-000000000003', 'is_primary', 'boolean', true, false, false, false, -1, -1, false, 'Primary diagnosis flag'),
('00600019-0001-4000-8000-000000000025', '00500003-0001-4000-8000-000000000003', 'diagnosed_at', 'timestamp', true, false, false, false, -1, -1, false, 'Diagnosis timestamp (UTC)'),

-- visits table (00500005 — Clinical Trials)
('0060001a-0001-4000-8000-000000000026', '00500005-0001-4000-8000-000000000005', 'visit_id', 'string', true, true, true, false, 1, -1, true, 'Unique visit identifier'),
('0060001b-0001-4000-8000-000000000027', '00500005-0001-4000-8000-000000000005', 'subject_id', 'string', true, false, false, false, -1, -1, true, 'FK to subjects.subject_id'),
('0060001c-0001-4000-8000-000000000028', '00500005-0001-4000-8000-000000000005', 'visit_name', 'string', true, false, false, false, -1, -1, false, 'Protocol-defined visit label (e.g. V1, V2)'),
('0060001d-0001-4000-8000-000000000029', '00500005-0001-4000-8000-000000000005', 'scheduled_date', 'date', true, false, false, false, -1, -1, false, 'Scheduled visit date'),
('0060001e-0001-4000-8000-000000000030', '00500005-0001-4000-8000-000000000005', 'completed_date', 'date', false, false, false, false, -1, -1, false, 'Actual completion date (NULL if missed)'),

-- endpoints table (00500006)
('0060001f-0001-4000-8000-000000000031', '00500006-0001-4000-8000-000000000006', 'endpoint_id', 'string', true, true, true, false, 1, -1, true, 'Unique endpoint measurement identifier'),
('00600020-0001-4000-8000-000000000032', '00500006-0001-4000-8000-000000000006', 'subject_id', 'string', true, false, false, false, -1, -1, true, 'FK to subjects.subject_id'),
('00600021-0001-4000-8000-000000000033', '00500006-0001-4000-8000-000000000006', 'endpoint_name', 'string', true, false, false, false, -1, -1, true, 'Endpoint measure name (e.g. ORR, OS, PFS)'),
('00600022-0001-4000-8000-000000000034', '00500006-0001-4000-8000-000000000006', 'value_numeric', 'decimal', false, false, false, false, -1, -1, true, 'Numeric value (NULL for categorical)'),
('00600023-0001-4000-8000-000000000035', '00500006-0001-4000-8000-000000000006', 'value_text', 'string', false, false, false, false, -1, -1, false, 'Categorical value (NULL for numeric)'),
('00600024-0001-4000-8000-000000000036', '00500006-0001-4000-8000-000000000006', 'measured_date', 'date', true, false, false, false, -1, -1, false, 'Measurement date'),

-- signal_assessments table (00500008)
('00600025-0001-4000-8000-000000000037', '00500008-0001-4000-8000-000000000008', 'assessment_id', 'string', true, true, true, false, 1, -1, true, 'Unique signal assessment identifier'),
('00600026-0001-4000-8000-000000000038', '00500008-0001-4000-8000-000000000008', 'product_id', 'string', true, false, false, false, -1, -1, true, 'Product identifier (substance code)'),
('00600027-0001-4000-8000-000000000039', '00500008-0001-4000-8000-000000000008', 'meddra_pt', 'string', true, false, false, false, -1, -1, true, 'Adverse event PT under assessment'),
('00600028-0001-4000-8000-000000000040', '00500008-0001-4000-8000-000000000008', 'signal_score', 'decimal', true, false, false, false, -1, -1, true, 'Disproportionality / ML signal score'),
('00600029-0001-4000-8000-000000000041', '00500008-0001-4000-8000-000000000008', 'assessment_date', 'date', true, false, false, true, -1, 1, false, 'Assessment cycle date (partition key)'),

-- claims table (00500009)
('0060002a-0001-4000-8000-000000000042', '00500009-0001-4000-8000-000000000009', 'claim_id', 'string', true, true, true, false, 1, -1, true, 'Unique medical claim identifier'),
('0060002b-0001-4000-8000-000000000043', '00500009-0001-4000-8000-000000000009', 'member_id', 'string', true, false, false, false, -1, -1, true, 'FK to members (insurance plan member)'),
('0060002c-0001-4000-8000-000000000044', '00500009-0001-4000-8000-000000000009', 'service_date', 'date', true, false, false, true, -1, 1, true, 'Date of service (partition key)'),
('0060002d-0001-4000-8000-000000000045', '00500009-0001-4000-8000-000000000009', 'cpt_code', 'string', true, false, false, false, -1, -1, true, 'CMS HCPCS / CPT procedure code'),
('0060002e-0001-4000-8000-000000000046', '00500009-0001-4000-8000-000000000009', 'billed_amount', 'decimal', true, false, false, false, -1, -1, true, 'Amount billed (>= 0)'),
('0060002f-0001-4000-8000-000000000047', '00500009-0001-4000-8000-000000000009', 'allowed_amount', 'decimal', true, false, false, false, -1, -1, true, 'Amount allowed by payer'),

-- remittances table (0050000a)
('00600030-0001-4000-8000-000000000048', '0050000a-0001-4000-8000-000000000010', 'remittance_id', 'string', true, true, true, false, 1, -1, true, 'Unique remittance advice identifier'),
('00600031-0001-4000-8000-000000000049', '0050000a-0001-4000-8000-000000000010', 'claim_id', 'string', true, false, false, false, -1, -1, true, 'FK to claims.claim_id'),
('00600032-0001-4000-8000-000000000050', '0050000a-0001-4000-8000-000000000010', 'paid_amount', 'decimal', true, false, false, false, -1, -1, true, 'Amount paid by payer'),
('00600033-0001-4000-8000-000000000051', '0050000a-0001-4000-8000-000000000010', 'denial_code', 'string', false, false, false, false, -1, -1, false, 'CARC reason code (NULL if paid)'),
('00600034-0001-4000-8000-000000000052', '0050000a-0001-4000-8000-000000000010', 'paid_date', 'date', true, false, false, false, -1, -1, false, 'Payment processed date')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4d. DATA CONTRACT QUALITY CHECKS (HLS-specific)
-- ============================================================================

INSERT INTO data_contract_quality_checks (id, object_id, property_id, level, name, description, dimension, business_impact, severity, type, rule, must_be, must_not_be, must_be_gt, must_be_ge, must_be_lt, must_be_le, must_be_between_min, must_be_between_max, query, engine, implementation, schedule, scheduler) VALUES
-- Patients
('03000001-0001-4000-8000-000000000001', '00500001-0001-4000-8000-000000000001', '00600001-0001-4000-8000-000000000001', 'property', 'patient_id_unique', 'patient_id (de-identified) must be unique',          'uniqueness',   'regulatory', 'error',   'library', 'unique',     NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '@daily',   'airflow'),
('03000002-0001-4000-8000-000000000002', '00500001-0001-4000-8000-000000000001', '00600003-0001-4000-8000-000000000003', 'property', 'gender_values',     'gender must be one of M/F/O/U',                       'conformity',   'regulatory', 'warning', 'library', 'enumValues', 'M,F,O,U', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '@daily', 'airflow'),
-- Diagnoses
('03000003-0001-4000-8000-000000000003', '00500003-0001-4000-8000-000000000003', '00600017-0001-4000-8000-000000000023', 'property', 'icd10_format',      'icd10_code should match ICD-10-CM regex',             'conformity',   'regulatory', 'warning', 'library', 'regex',      '^[A-Z][0-9]{2}(\\.[0-9A-Z]{1,4})?$', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '@daily',   'airflow'),
-- Adverse events
('03000004-0001-4000-8000-000000000004', '00500007-0001-4000-8000-000000000007', '00600012-0001-4000-8000-000000000018', 'property', 'seriousness_values','seriousness must be serious or non_serious',          'conformity',   'regulatory', 'error',   'library', 'enumValues', 'serious,non_serious', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '@hourly', 'airflow'),
('03000005-0001-4000-8000-000000000005', '00500007-0001-4000-8000-000000000007', NULL,                                  'object',   'expedited_15d',     'Expedited reporting freshness — serious AEs reported within 15 calendar days', 'timeliness', 'regulatory', 'error', 'sql', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'SELECT MAX(EXTRACT(epoch FROM (NOW() - onset_date))/86400) FROM safety.adverse_events WHERE seriousness = ''serious''', 'spark', NULL, '0 4 * * *', 'airflow'),
-- Endpoints
('03000006-0001-4000-8000-000000000006', '00500006-0001-4000-8000-000000000006', '0060001f-0001-4000-8000-000000000031', 'property', 'endpoint_id_unique','endpoint_id must be unique',                          'uniqueness',   'regulatory', 'error',   'library', 'unique',     NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '@daily',   'airflow'),
-- Claims
('03000007-0001-4000-8000-000000000007', '00500009-0001-4000-8000-000000000009', '0060002e-0001-4000-8000-000000000046', 'property', 'billed_non_neg',    'billed_amount must be >= 0',                          'accuracy',     'operational','error',   'library', 'rangeCheck', NULL, NULL, NULL, '0', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '@daily',  'airflow'),
('03000008-0001-4000-8000-000000000008', '00500009-0001-4000-8000-000000000009', '0060002d-0001-4000-8000-000000000045', 'property', 'cpt_format',        'CPT code is 5 alphanumeric characters',               'conformity',   'regulatory', 'warning', 'library', 'regex',      '^[A-Z0-9]{5}$', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '@daily', 'airflow')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5. DATA PRODUCTS
-- ============================================================================

INSERT INTO data_products (id, api_version, kind, status, name, version, domain, tenant, owner_team_id, max_level_inheritance, published, publication_scope, created_at, updated_at, version_family_id) VALUES
('00700001-0001-4000-8000-000000000001', 'v1.0.0', 'DataProduct', 'active', 'Patient 360 View v1', '1.0.0', 'Clinical', 'hls-demo', '00100001-0001-4000-8000-000000000001', 99, true, 'org', NOW(), NOW(), '00700001-0001-4000-8000-000000000001'),
('00700002-0001-4000-8000-000000000002', 'v1.0.0', 'DataProduct', 'active', 'Clinical Trial Analytics v1', '1.0.0', 'Research', 'hls-demo', '00100002-0001-4000-8000-000000000002', 99, true, 'org', NOW(), NOW(), '00700002-0001-4000-8000-000000000002'),
('00700003-0001-4000-8000-000000000003', 'v1.0.0', 'DataProduct', 'active', 'Drug Safety Signal Detection v1', '1.0.0', 'Regulatory', 'hls-demo', '00100003-0001-4000-8000-000000000003', 99, true, 'org', NOW(), NOW(), '00700003-0001-4000-8000-000000000003'),
('00700004-0001-4000-8000-000000000004', 'v1.0.0', 'DataProduct', 'active', 'Real-World Evidence Platform v1', '1.0.0', 'Research', 'hls-demo', '00100002-0001-4000-8000-000000000002', 99, true, 'org', NOW(), NOW(), '00700004-0001-4000-8000-000000000004'),
('00700005-0001-4000-8000-000000000005', 'v1.0.0', 'DataProduct', 'active', 'Claims Analytics Dashboard v1', '1.0.0', 'Claims', 'hls-demo', '00100001-0001-4000-8000-000000000001', 99, true, 'org', NOW(), NOW(), '00700005-0001-4000-8000-000000000005')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5b. DATA PRODUCT DESCRIPTIONS
-- ============================================================================

INSERT INTO data_product_descriptions (id, product_id, purpose, usage, limitations) VALUES
('00800001-0001-4000-8000-000000000001', '00700001-0001-4000-8000-000000000001', 'Provide a unified, longitudinal view of patient data integrating EHR, claims, lab results, and social determinants of health.', 'Power clinical decision support, population health dashboards, and care gap identification. Supports FHIR R4 export.', 'PHI is de-identified using Safe Harbor method. Data latency is 4 hours from source EHR systems. Genomic data excluded unless separate consent obtained.'),
('00800002-0001-4000-8000-000000000002', '00700002-0001-4000-8000-000000000002', 'Provide cleaned, CDISC-compliant clinical trial data for study monitoring, interim analyses, and regulatory submissions.', 'Connect to SAS, R, or Python environments for biostatistical analysis. Feed DSMB dashboards and site performance reports.', 'Blinded data only until study unblinding. Subject-level access requires IRB approval and study-specific DTA.'),
('00800003-0001-4000-8000-000000000003', '00700003-0001-4000-8000-000000000003', 'Detect safety signals from spontaneous AE reports using disproportionality analysis and NLP-extracted case narratives.', 'Automated FAERS/EudraVigilance submission preparation. Signal prioritization dashboards for safety review board.', 'Under-reporting bias inherent in spontaneous systems. NLP extraction accuracy ~92% for MedDRA coding.'),
('00800004-0001-4000-8000-000000000004', '00700004-0001-4000-8000-000000000004', 'Combine claims, EHR, and registry data for real-world evidence generation supporting label expansions and HEOR studies.', 'Cohort identification, treatment pattern analysis, and comparative effectiveness research via self-service analytics.', 'Claims data has 30-60 day lag. EHR linkage rate ~78%. Results are observational and may have residual confounding.'),
('00800005-0001-4000-8000-000000000005', '00700005-0001-4000-8000-000000000005', 'Provide aggregated claims analytics for revenue cycle optimization, denial root-cause analysis, and payer mix reporting.', 'Connect BI tools for executive dashboards. Export denial patterns for RCM team action items.', 'Limited to commercial and Medicare Advantage claims. Medicaid data varies by state contract.')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5c. DATA PRODUCT OUTPUT PORTS
-- ============================================================================

INSERT INTO data_product_output_ports (id, product_id, name, version, description, port_type, status, contract_id, contains_pii, auto_approve, server) VALUES
('00900001-0001-4000-8000-000000000001', '00700001-0001-4000-8000-000000000001', 'patient_360_delta', '1.0.0', 'De-identified patient longitudinal table', 'table', 'active', NULL, true, false, '{"location": "s3://hls-lake/curated/patient360/v1", "format": "delta"}'),
('00900002-0001-4000-8000-000000000002', '00700001-0001-4000-8000-000000000001', 'FHIR R4 API', '1.0.0', 'FHIR-compliant patient resource API', 'api', 'active', NULL, false, false, '{"location": "https://fhir.hospital.org/api/v4/Patient"}'),
('00900003-0001-4000-8000-000000000003', '00700002-0001-4000-8000-000000000002', 'trial_analytics_sdtm', '1.0.0', 'CDISC SDTM-formatted trial datasets', 'table', 'active', NULL, false, false, '{"location": "s3://hls-lake/trials/sdtm/v1", "format": "delta"}'),
('00900004-0001-4000-8000-000000000004', '00700003-0001-4000-8000-000000000003', 'safety_signals_table', '1.0.0', 'Signal detection scores and case series', 'table', 'active', NULL, false, true, '{"location": "s3://hls-lake/safety/signals/v1", "format": "delta"}'),
('00900005-0001-4000-8000-000000000005', '00700004-0001-4000-8000-000000000004', 'rwe_cohort_builder', '1.0.0', 'Self-service cohort query API for RWE studies', 'api', 'active', NULL, true, false, '{"location": "https://rwe.pharma.com/api/v1/cohorts"}'),
('00900006-0001-4000-8000-000000000006', '00700005-0001-4000-8000-000000000005', 'claims_analytics_dashboard', '1.0.0', 'BI connection for claims performance dashboards', 'dashboard', 'active', NULL, false, true, '{"location": "https://bi.hospital.org/dashboards/claims-analytics"}')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5d. DATA PRODUCT INPUT PORTS
-- ============================================================================

INSERT INTO data_product_input_ports (id, product_id, name, version, contract_id) VALUES
('00a00001-0001-4000-8000-000000000001', '00700001-0001-4000-8000-000000000001', 'EHR Patient Data', '1.0.0', 'patient-ehr-contract-v2'),
('00a00002-0001-4000-8000-000000000002', '00700001-0001-4000-8000-000000000001', 'Claims Feed', '1.0.0', 'claims-reimbursement-contract-v1'),
('00a00003-0001-4000-8000-000000000003', '00700002-0001-4000-8000-000000000002', 'Raw Trial Data (EDC)', '1.0.0', 'clinical-trial-contract-v1'),
('00a00004-0001-4000-8000-000000000004', '00700003-0001-4000-8000-000000000003', 'Adverse Event Reports', '1.0.0', 'adverse-event-contract-v1'),
('00a00005-0001-4000-8000-000000000005', '00700004-0001-4000-8000-000000000004', 'Patient 360 Data', '1.0.0', 'patient-ehr-contract-v2'),
('00a00006-0001-4000-8000-000000000006', '00700004-0001-4000-8000-000000000004', 'Claims Data', '1.0.0', 'claims-reimbursement-contract-v1'),
('00a00007-0001-4000-8000-000000000007', '00700005-0001-4000-8000-000000000005', 'Claims & Remittance Data', '1.0.0', 'claims-reimbursement-contract-v1')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5e. DATA PRODUCT SUPPORT CHANNELS
-- ============================================================================

INSERT INTO data_product_support_channels (id, product_id, channel, url, tool, scope, description) VALUES
('00b00001-0001-4000-8000-000000000001', '00700001-0001-4000-8000-000000000001', 'clinical-data-support', 'https://teams.com/channels/clinical-data', 'teams', 'interactive', 'Clinical informatics support for Patient 360'),
('00b00002-0001-4000-8000-000000000002', '00700002-0001-4000-8000-000000000002', 'trial-data-support', 'https://slack.com/channels/trial-data', 'slack', 'issues', 'Biostatistics and data management support'),
('00b00003-0001-4000-8000-000000000003', '00700003-0001-4000-8000-000000000003', 'drug-safety-ops', 'https://jira.pharma.com/projects/SAFETY', 'ticket', 'issues', 'JIRA project for safety signal triage'),
('00b00004-0001-4000-8000-000000000004', '00700004-0001-4000-8000-000000000004', 'rwe-support', 'https://slack.com/channels/rwe-platform', 'slack', 'interactive', NULL),
('00b00005-0001-4000-8000-000000000005', '00700005-0001-4000-8000-000000000005', 'rcm-analytics', 'https://teams.com/channels/rcm-analytics', 'teams', 'announcements', 'Revenue cycle analytics updates')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5f. DATA PRODUCT TEAMS
-- ============================================================================

INSERT INTO data_product_teams (id, product_id, name, description) VALUES
('00c00001-0001-4000-8000-000000000001', '00700001-0001-4000-8000-000000000001', 'Clinical Informatics', NULL),
('00c00002-0001-4000-8000-000000000002', '00700002-0001-4000-8000-000000000002', 'Biostatistics', NULL),
('00c00003-0001-4000-8000-000000000003', '00700003-0001-4000-8000-000000000003', 'Pharmacovigilance', NULL),
('00c00004-0001-4000-8000-000000000004', '00700004-0001-4000-8000-000000000004', 'Real-World Evidence', NULL),
('00c00005-0001-4000-8000-000000000005', '00700005-0001-4000-8000-000000000005', 'Revenue Cycle', NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5g. DATA PRODUCT TEAM MEMBERS
-- ============================================================================

INSERT INTO data_product_team_members (id, team_id, username, name, role) VALUES
('00d00001-0001-4000-8000-000000000001', '00c00001-0001-4000-8000-000000000001', 'dr.chen@hospital.org', 'Dr. Wei Chen', 'owner'),
('00d00002-0001-4000-8000-000000000002', '00c00001-0001-4000-8000-000000000001', 'nurse.data@hospital.org', 'Maria Lopez', 'contributor'),
('00d00003-0001-4000-8000-000000000003', '00c00002-0001-4000-8000-000000000002', 'dr.patel@pharma.com', 'Dr. Anita Patel', 'owner'),
('00d00004-0001-4000-8000-000000000004', '00c00003-0001-4000-8000-000000000003', 'sarah.compliance@pharma.com', 'Sarah Compliance', 'owner'),
('00d00005-0001-4000-8000-000000000005', '00c00004-0001-4000-8000-000000000004', 'rwe-lead@pharma.com', 'James Real-World', 'owner'),
('00d00006-0001-4000-8000-000000000006', '00c00005-0001-4000-8000-000000000005', 'rcm-analyst@hospital.org', 'Karen Revenue', 'owner')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 6. COMPLIANCE POLICIES (HLS-specific)
-- ============================================================================

INSERT INTO compliance_policies (id, name, description, failure_message, rule, category, severity, is_active, created_at, updated_at) VALUES
('01100001-0001-4000-8000-000000000001', 'HIPAA PHI De-identification', 'Verify all patient data is de-identified per HIPAA Safe Harbor method',
'Protected Health Information (PHI) detected in dataset. All 18 HIPAA identifiers must be removed or generalized per the Safe Harbor method before analytical use.',
'MATCH (d:Dataset) WHERE d.domain IN [''Clinical'', ''Research''] AND d.contains_phi = true ASSERT d.deidentification_method = ''safe_harbor''', 'security', 'critical', true, NOW(), NOW()),

('01100002-0001-4000-8000-000000000002', '21 CFR Part 11 Audit Trail', 'Ensure electronic records have complete audit trails per FDA regulations',
'Dataset lacks required audit trail for 21 CFR Part 11 compliance. All clinical trial electronic records must have timestamped, user-attributed audit trails that cannot be modified.',
'MATCH (d:Dataset) WHERE d.domain = ''Research'' ASSERT d.has_audit_trail = true AND d.audit_trail_immutable = true', 'governance', 'critical', true, NOW(), NOW()),

('01100003-0001-4000-8000-000000000003', 'CDISC Standards Compliance', 'Verify clinical trial data conforms to CDISC SDTM/ADaM standards',
'Clinical trial dataset does not conform to CDISC standards. All submission-ready datasets must follow SDTM or ADaM data models.',
'MATCH (d:Dataset) WHERE d.domain = ''Research'' AND d.is_submission_ready = true ASSERT d.cdisc_standard IN [''SDTM'', ''ADaM'']', 'quality', 'high', true, NOW(), NOW()),

('01100004-0001-4000-8000-000000000004', 'Adverse Event Reporting Timeliness', 'Ensure serious adverse events are reported within regulatory timelines',
'Serious adverse event reporting exceeds 15-day regulatory deadline. Expedited ICSRs must be submitted within 15 calendar days of initial receipt.',
'MATCH (ae:AdverseEvent) WHERE ae.seriousness = ''serious'' ASSERT ae.days_to_report <= 15', 'governance', 'critical', true, NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 7. NOTIFICATIONS (HLS-specific)
-- ============================================================================

INSERT INTO notifications (id, type, title, subtitle, description, created_at, read, can_delete, recipient) VALUES
('01000001-0001-4000-8000-000000000001', 'warning', 'HIPAA Compliance Alert', 'Patient 360 Dataset', 'PHI detected in the Patient 360 analytics dataset. De-identification validation failed for 3 records. Immediate review required.', NOW() - INTERVAL '6 hours', false, false, NULL),
('01000002-0001-4000-8000-000000000002', 'info', 'Clinical Trial Data Refresh', 'Study ONCO-2025-001', 'SDTM datasets for Study ONCO-2025-001 have been refreshed with Week 24 interim analysis data.', NOW() - INTERVAL '1 day', false, true, NULL),
('01000003-0001-4000-8000-000000000003', 'error', 'Expedited AE Report Overdue', 'Case ICSR-2025-4521', 'Serious adverse event case ICSR-2025-4521 has exceeded the 15-day reporting deadline. Escalation required.', NOW() - INTERVAL '2 hours', false, false, NULL),
('01000004-0001-4000-8000-000000000004', 'success', 'FDA Submission Package Ready', 'NDA-2025-3847', 'All CDISC datasets and define.xml for NDA-2025-3847 have passed validation. Package ready for eCTD submission.', NOW() - INTERVAL '3 days', true, true, NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 8. METADATA (Notes, Links)
-- ============================================================================

-- Rich Text Notes (type=016)
INSERT INTO rich_text_metadata (id, entity_id, entity_type, title, short_description, content_markdown, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01600001-0001-4000-8000-000000000001', '00700001-0001-4000-8000-000000000001', 'data_product', 'Overview', 'Unified longitudinal patient view for clinical analytics.', E'# Patient 360 View v1\n\nUnified longitudinal patient data integrating EHR, claims, lab results, and social\ndeterminants of health. Supports clinical decision support and population health.\n\n## Data Sources\n- Epic/Cerner EHR via HL7 FHIR R4\n- Commercial and Medicare claims feeds\n- Lab results (LOINC coded)\n- SDOH data from census and survey sources\n\n## Privacy and Compliance\n- HIPAA Safe Harbor de-identification applied\n- PHI access requires BAA and IRB approval\n- Audit trail on all patient-level queries\n- Data retention: 7 years per state regulations', false, 50, true, 'system@demo', NOW(), NOW()),
('01600002-0001-4000-8000-000000000002', '00700002-0001-4000-8000-000000000002', 'data_product', 'Overview', 'CDISC-compliant clinical trial data for study analytics.', E'# Clinical Trial Analytics v1\n\nCleaned and harmonized clinical trial data following CDISC SDTM and ADaM standards.\nSupports study monitoring, interim analyses, and regulatory submissions.\n\n## Standards Compliance\n- SDTM v3.3 for tabulation datasets\n- ADaM v2.1 for analysis-ready datasets\n- Define-XML v2.0 for metadata\n- MedDRA v26.0 for adverse event coding\n\n## Access Controls\n- Blinded data: Restricted to unblinded statisticians\n- Subject-level: Requires active IRB approval\n- Study-specific DTA required for external collaborators', false, 50, true, 'system@demo', NOW(), NOW()),
('01600003-0001-4000-8000-000000000003', '00700003-0001-4000-8000-000000000003', 'data_product', 'Overview', 'Pharmacovigilance signal detection from AE reports.', E'# Drug Safety Signal Detection v1\n\nAutomated safety signal detection using disproportionality analysis (PRR, ROR, EBGM)\nand NLP-extracted case narratives from spontaneous adverse event reports.\n\n## Detection Methods\n- Proportional Reporting Ratio (PRR)\n- Reporting Odds Ratio (ROR)\n- Empirical Bayesian Geometric Mean (EBGM)\n- NLP narrative extraction (~92% MedDRA coding accuracy)\n\n## Regulatory Integration\n- FDA FAERS submission formatting\n- EMA EudraVigilance E2B(R3) export\n- Automated PSUR/PBRER signal summaries\n- 15-day expedited reporting for serious unexpected AEs', false, 50, true, 'system@demo', NOW(), NOW()),
('01600004-0001-4000-8000-000000000004', '00700004-0001-4000-8000-000000000004', 'data_product', 'Overview', 'Real-world evidence for label expansion and HEOR.', E'# Real-World Evidence Platform v1\n\nIntegrated claims, EHR, and registry data platform for generating real-world evidence\nto support label expansions, comparative effectiveness, and health economics studies.\n\n## Capabilities\n- Self-service cohort builder with inclusion/exclusion criteria\n- Propensity score matching and IPTW support\n- Treatment pattern analysis and Kaplan-Meier curves\n- Claims-EHR linkage rate: ~78%\n\n## Study Design Support\n- Retrospective cohort studies\n- Case-control analyses\n- Interrupted time series\n- Target trial emulation framework', false, 50, true, 'system@demo', NOW(), NOW()),
('01600005-0001-4000-8000-000000000005', '00700005-0001-4000-8000-000000000005', 'data_product', 'Overview', 'Revenue cycle analytics and denial management.', E'# Claims Analytics Dashboard v1\n\nAggregated claims analytics for revenue cycle optimization, denial root-cause analysis,\npayer mix reporting, and contract performance monitoring.\n\n## KPIs Tracked\n- Clean claim rate and first-pass resolution rate\n- Denial rate by payer, CPT code, and denial reason\n- Days in A/R by aging bucket\n- Net collection rate and contractual adjustment trends\n\n## Data Coverage\n- Commercial insurance (all major payers)\n- Medicare Advantage\n- Medicaid (varies by state contract)\n- Workers'' compensation', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;

-- Link Metadata (type=017)
INSERT INTO link_metadata (id, entity_id, entity_type, title, short_description, url, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01700001-0001-4000-8000-000000000001', '00700001-0001-4000-8000-000000000001', 'data_product', 'FHIR API Documentation', 'FHIR R4 Patient resource API reference.', 'https://fhir.hospital.org/api/v4/documentation', false, 50, true, 'system@demo', NOW(), NOW()),
('01700002-0001-4000-8000-000000000002', '00700001-0001-4000-8000-000000000001', 'data_product', 'HIPAA Compliance Guide', 'De-identification and access policies.', 'https://wiki.hospital.org/compliance/hipaa-data-access', false, 50, true, 'system@demo', NOW(), NOW()),
('01700003-0001-4000-8000-000000000003', '00700002-0001-4000-8000-000000000002', 'data_product', 'CDISC Implementation Guide', 'SDTM/ADaM mapping specifications.', 'https://docs.pharma.com/trials/cdisc-implementation-guide', false, 50, true, 'system@demo', NOW(), NOW()),
('01700004-0001-4000-8000-000000000004', '00700002-0001-4000-8000-000000000002', 'data_product', 'Study Monitoring Dashboard', 'Enrollment, site performance, and data quality.', 'https://bi.pharma.com/dashboards/trial-monitoring', false, 50, true, 'system@demo', NOW(), NOW()),
('01700005-0001-4000-8000-000000000005', '00700003-0001-4000-8000-000000000003', 'data_product', 'Signal Review Board Wiki', 'Signal triage process and escalation.', 'https://wiki.pharma.com/safety/signal-review-process', false, 50, true, 'system@demo', NOW(), NOW()),
('01700006-0001-4000-8000-000000000006', '00700003-0001-4000-8000-000000000003', 'data_product', 'FAERS Submission Guide', 'FDA adverse event submission procedures.', 'https://docs.pharma.com/regulatory/faers-submission-guide', false, 50, true, 'system@demo', NOW(), NOW()),
('01700007-0001-4000-8000-000000000007', '00700004-0001-4000-8000-000000000004', 'data_product', 'RWE Study Design Toolkit', 'Cohort definition templates and analysis guides.', 'https://wiki.pharma.com/rwe/study-design-toolkit', false, 50, true, 'system@demo', NOW(), NOW()),
('01700008-0001-4000-8000-000000000008', '00700004-0001-4000-8000-000000000004', 'data_product', 'Data Linkage Dashboard', 'Claims-EHR linkage rates and coverage.', 'https://bi.pharma.com/dashboards/rwe-data-linkage', false, 50, true, 'system@demo', NOW(), NOW()),
('01700009-0001-4000-8000-000000000009', '00700005-0001-4000-8000-000000000005', 'data_product', 'Runbook', 'Claims pipeline operations and on-call.', 'https://runbooks.hospital.org/rcm/claims-analytics-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000a-0001-4000-8000-000000000010', '00700005-0001-4000-8000-000000000005', 'data_product', 'Denial Management Dashboard', 'Denial trends and root cause analysis.', 'https://bi.hospital.org/dashboards/denial-management', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 9. BUSINESS ROLES (HLS-specific, type=0f0)
-- ============================================================================
-- Vertical-specific ownership/contributor roles. is_system=false marks them as
-- demo content (cleared with the rest of the HLS pack).

INSERT INTO business_roles (id, name, description, category, is_system, is_approver, status, created_by, created_at, updated_at) VALUES
('0f000001-0001-4000-8000-000000000001', 'Clinical Data Steward', 'Maintains clinical data quality, terminology mapping (ICD-10, LOINC, SNOMED), and HIPAA-compliant access policies.', 'governance', false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000002-0001-4000-8000-000000000002', 'Principal Investigator', 'Lead clinician/scientist accountable for a clinical trial protocol and its data.', 'business', false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000003-0001-4000-8000-000000000003', 'IRB Coordinator', 'Manages Institutional Review Board approvals and consent tracking.', 'governance', false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000004-0001-4000-8000-000000000004', 'Privacy Officer (HIPAA)', 'Ensures Protected Health Information handling complies with HIPAA Privacy and Security Rules.', 'governance', false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000005-0001-4000-8000-000000000005', 'Pharmacovigilance Lead', 'Owns adverse event signal detection, ICSR reporting, and PSUR/PBRER submissions.', 'operational', false, false, 'active', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 10. DELIVERY METHODS (HLS-specific, type=0f4)
-- ============================================================================

INSERT INTO delivery_methods (id, name, description, category, is_system, status, created_by, created_at, updated_at) VALUES
('0f400001-0001-4000-8000-000000000001', 'HL7 FHIR API',         'Delivers clinical resources via HL7 FHIR R4 REST API (Patient, Observation, Condition, Encounter).', 'endpoint',  false, 'active', 'system@demo', NOW(), NOW()),
('0f400002-0001-4000-8000-000000000002', 'EDI 837 Claims Feed',  'Delivers claims data via X12 EDI 837 institutional/professional transactions.',                       'export',    false, 'active', 'system@demo', NOW(), NOW()),
('0f400003-0001-4000-8000-000000000003', 'REDCap Export',        'Pulls case-report-form data from REDCap study databases via API export.',                              'access',    false, 'active', 'system@demo', NOW(), NOW()),
('0f400004-0001-4000-8000-000000000004', 'CDISC Define-XML',     'Submission package formatted as Define-XML 2.0 with SDTM/ADaM datasets.',                              'export',    false, 'active', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 11. VERTICAL ASSET TYPES (HLS-specific, is_system=false)
-- ============================================================================
-- Asset types unique to HLS that aren't in the shared ontology. These survive
-- ontology re-syncs because they are NOT marked is_system. Use lookups by name
-- in subsequent INSERTs (with COALESCE fallback to literal id) to make the
-- file resilient to manual edits.

INSERT INTO asset_types (id, name, description, category, icon, required_fields, optional_fields, is_system, status, created_by, created_at, updated_at) VALUES
('0f200101-0001-4000-8000-000000000001', 'Patient Cohort',         'A defined group of patients with shared inclusion/exclusion criteria for clinical research or analytics.', 'data', 'users',     NULL, NULL, false, 'active', 'system@demo', NOW(), NOW()),
('0f200102-0001-4000-8000-000000000002', 'Clinical Trial Dataset', 'CDISC SDTM/ADaM dataset associated with a clinical trial protocol.',                                      'data', 'flask',     NULL, NULL, false, 'active', 'system@demo', NOW(), NOW()),
('0f200103-0001-4000-8000-000000000003', 'Adverse Event Case',     'Individual Case Safety Report (ICSR) capturing a single adverse drug event.',                             'data', 'shield',    NULL, NULL, false, 'active', 'system@demo', NOW(), NOW())
ON CONFLICT (name) DO NOTHING;


-- ============================================================================
-- 12. TAG NAMESPACES + TAGS (HLS governance vocabulary)
-- ============================================================================

INSERT INTO tag_namespaces (id, name, description, created_by, created_at, updated_at) VALUES
('02601001-0001-4000-8000-000000000001', 'hls-phi',          'Protected Health Information sensitivity classifications.',          'system@demo', NOW(), NOW()),
('02601002-0001-4000-8000-000000000002', 'hls-regulatory',   'HLS regulatory frameworks (HIPAA, 21 CFR Part 11, GxP).',           'system@demo', NOW(), NOW()),
('02601003-0001-4000-8000-000000000003', 'hls-clinical',     'Clinical data context and lifecycle stage.',                         'system@demo', NOW(), NOW())
ON CONFLICT (name) DO NOTHING;

INSERT INTO tags (id, name, description, possible_values, status, version, namespace_id, parent_id, created_by, created_at, updated_at) VALUES
-- PHI sensitivity
('02700101-0001-4000-8000-000000000001', 'phi-direct',         'Contains direct PHI identifiers (name, MRN, DOB, etc.).', NULL, 'active', 'v1.0', '02601001-0001-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
('02700102-0001-4000-8000-000000000002', 'phi-deidentified',   'PHI removed via Safe Harbor or Expert Determination.',     NULL, 'active', 'v1.0', '02601001-0001-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
('02700103-0001-4000-8000-000000000003', 'phi-limited',        'Limited Data Set per HIPAA \u00a7164.514(e).',                NULL, 'active', 'v1.0', '02601001-0001-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
-- Regulatory
('02700104-0001-4000-8000-000000000004', 'hipaa',              'Subject to HIPAA Privacy and Security Rules.',             NULL, 'active', 'v1.0', '02601002-0001-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
('02700105-0001-4000-8000-000000000005', '21cfr-part-11',      'Subject to FDA 21 CFR Part 11 electronic records rule.',   NULL, 'active', 'v1.0', '02601002-0001-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
('02700106-0001-4000-8000-000000000006', 'gcp-validated',      'Validated under Good Clinical Practice guidelines.',       NULL, 'active', 'v1.0', '02601002-0001-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
-- Clinical context
('02700107-0001-4000-8000-000000000007', 'cohort-eligible',    'Suitable for cohort-building queries.',                     NULL, 'active', 'v1.0', '02601003-0001-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW()),
('02700108-0001-4000-8000-000000000008', 'submission-ready',   'Submission-ready CDISC dataset.',                          NULL, 'active', 'v1.0', '02601003-0001-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW()),
('02700109-0001-4000-8000-000000000009', 'rwe-source',         'Real-world evidence data source.',                          NULL, 'active', 'v1.0', '02601003-0001-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW())
ON CONFLICT (namespace_id, name) DO NOTHING;

INSERT INTO tag_namespace_permissions (id, namespace_id, group_id, access_level, created_by, created_at, updated_at) VALUES
('02800101-0001-4000-8000-000000000001', '02601001-0001-4000-8000-000000000001', 'clinical-informatics', 'admin',      'system@demo', NOW(), NOW()),
('02800102-0001-4000-8000-000000000002', '02601001-0001-4000-8000-000000000001', 'biostatisticians',     'read_only',  'system@demo', NOW(), NOW()),
('02800103-0001-4000-8000-000000000003', '02601002-0001-4000-8000-000000000002', 'regulatory-team',      'admin',      'system@demo', NOW(), NOW()),
('02800104-0001-4000-8000-000000000004', '02601003-0001-4000-8000-000000000003', 'clinical-informatics', 'read_write', 'system@demo', NOW(), NOW())
ON CONFLICT (namespace_id, group_id) DO NOTHING;


-- ============================================================================
-- 13. RDF TRIPLES — HLS concept graph (type=020)
-- ============================================================================
-- A small SKOS concept graph for the HLS knowledge graph view. Each concept has
-- (rdf:type, rdfs:label) pair. Linked from data_contracts/products via section 14.

INSERT INTO rdf_triples (id, subject_uri, predicate_uri, object_value, object_is_uri, context_name, source_type, source_identifier, created_by, created_at) VALUES
-- Patient (Clinical concept root)
('02000101-0001-4000-8000-000000000001', 'http://demo.ontos.app/hls#Patient',          'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000102-0001-4000-8000-000000000002', 'http://demo.ontos.app/hls#Patient',          'http://www.w3.org/2000/01/rdf-schema#label',       'Patient',                                       false, 'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000103-0001-4000-8000-000000000003', 'http://demo.ontos.app/hls#Encounter',        'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000104-0001-4000-8000-000000000004', 'http://demo.ontos.app/hls#Encounter',        'http://www.w3.org/2000/01/rdf-schema#label',       'Encounter',                                     false, 'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000105-0001-4000-8000-000000000005', 'http://demo.ontos.app/hls#Diagnosis',        'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000106-0001-4000-8000-000000000006', 'http://demo.ontos.app/hls#Diagnosis',        'http://www.w3.org/2000/01/rdf-schema#label',       'Diagnosis',                                     false, 'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000107-0001-4000-8000-000000000007', 'http://demo.ontos.app/hls#Medication',       'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000108-0001-4000-8000-000000000008', 'http://demo.ontos.app/hls#Medication',       'http://www.w3.org/2000/01/rdf-schema#label',       'Medication',                                    false, 'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000109-0001-4000-8000-000000000009', 'http://demo.ontos.app/hls#AdverseEvent',     'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('0200010a-0001-4000-8000-000000000010', 'http://demo.ontos.app/hls#AdverseEvent',     'http://www.w3.org/2000/01/rdf-schema#label',       'Adverse Event',                                 false, 'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('0200010b-0001-4000-8000-000000000011', 'http://demo.ontos.app/hls#ClinicalTrial',    'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('0200010c-0001-4000-8000-000000000012', 'http://demo.ontos.app/hls#ClinicalTrial',    'http://www.w3.org/2000/01/rdf-schema#label',       'Clinical Trial',                                false, 'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('0200010d-0001-4000-8000-000000000013', 'http://demo.ontos.app/hls#Claim',            'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('0200010e-0001-4000-8000-000000000014', 'http://demo.ontos.app/hls#Claim',            'http://www.w3.org/2000/01/rdf-schema#label',       'Insurance Claim',                               false, 'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('0200010f-0001-4000-8000-000000000015', 'http://demo.ontos.app/hls#Cohort',           'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW()),
('02000110-0001-4000-8000-000000000016', 'http://demo.ontos.app/hls#Cohort',           'http://www.w3.org/2000/01/rdf-schema#label',       'Patient Cohort',                                false, 'urn:demo', 'demo', 'demo_data_hls.sql', 'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 14. ENTITY SEMANTIC LINKS — HLS contracts/products → concepts (type=015)
-- ============================================================================

INSERT INTO entity_semantic_links (id, entity_id, entity_type, iri, label, created_by, created_at) VALUES
('01500101-0001-4000-8000-000000000001', '00400001-0001-4000-8000-000000000001', 'data_contract', 'http://demo.ontos.app/hls#Patient',       'Patient',        'system@demo', NOW()),
('01500102-0001-4000-8000-000000000002', '00400001-0001-4000-8000-000000000001', 'data_contract', 'http://demo.ontos.app/hls#Encounter',     'Encounter',      'system@demo', NOW()),
('01500103-0001-4000-8000-000000000003', '00400002-0001-4000-8000-000000000002', 'data_contract', 'http://demo.ontos.app/hls#ClinicalTrial', 'Clinical Trial', 'system@demo', NOW()),
('01500104-0001-4000-8000-000000000004', '00400003-0001-4000-8000-000000000003', 'data_contract', 'http://demo.ontos.app/hls#AdverseEvent',  'Adverse Event',  'system@demo', NOW()),
('01500105-0001-4000-8000-000000000005', '00400005-0001-4000-8000-000000000005', 'data_contract', 'http://demo.ontos.app/hls#Claim',         'Insurance Claim','system@demo', NOW()),
('01500106-0001-4000-8000-000000000006', '00700001-0001-4000-8000-000000000001', 'data_product',  'http://demo.ontos.app/hls#Patient',       'Patient',        'system@demo', NOW()),
('01500107-0001-4000-8000-000000000007', '00700002-0001-4000-8000-000000000002', 'data_product',  'http://demo.ontos.app/hls#ClinicalTrial', 'Clinical Trial', 'system@demo', NOW()),
('01500108-0001-4000-8000-000000000008', '00700003-0001-4000-8000-000000000003', 'data_product',  'http://demo.ontos.app/hls#AdverseEvent',  'Adverse Event',  'system@demo', NOW()),
('01500109-0001-4000-8000-000000000009', '00700004-0001-4000-8000-000000000004', 'data_product',  'http://demo.ontos.app/hls#Cohort',        'Patient Cohort', 'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 15. ASSETS — concrete HLS catalog objects (type=0f3)
-- ============================================================================
-- Datasets (021), physical tables (025), and dashboards/streams referenced by
-- the HLS data products. asset_type_id is resolved by name; falls back to a
-- known ontology UUID if the type name is missing.

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES
-- Tables (Clinical)
('0f300101-0001-4000-8000-000000000001',
 'lakehouse.hls.curated.patients',
 'De-identified patient master record (HIPAA Safe Harbor).',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.hls.curated.patients',
 '00000001-0001-4000-8000-000000000001',
 '{"catalog": "lakehouse", "schema": "hls_curated", "table_name": "patients", "row_count": 2400000, "format": "delta"}',
 '["curated", "phi-deidentified"]',
 'active', 'system@demo', NOW(), NOW()),

('0f300102-0001-4000-8000-000000000002',
 'lakehouse.hls.curated.encounters',
 'Inpatient and outpatient encounters with billing codes.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.hls.curated.encounters',
 '00000001-0001-4000-8000-000000000001',
 '{"catalog": "lakehouse", "schema": "hls_curated", "table_name": "encounters", "row_count": 18500000, "format": "delta"}',
 '["curated", "phi-limited"]',
 'active', 'system@demo', NOW(), NOW()),

-- Patient Cohort (vertical asset type)
('0f300103-0001-4000-8000-000000000003',
 'cohort.oncology.her2_positive_2024',
 'HER2-positive breast cancer cohort for 2024 RWE study (~12,400 patients).',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Patient Cohort' LIMIT 1), '0f200101-0001-4000-8000-000000000001'), 'Databricks', 'cohort.oncology.her2_positive_2024',
 '00000002-0001-4000-8000-000000000002',
 '{"cohort_size": 12400, "inclusion_criteria": ["HER2+", "stage_II_or_III"], "study_id": "ONCO-RWE-2024-08"}',
 '["cohort-eligible", "rwe-source"]',
 'active', 'system@demo', NOW(), NOW()),

-- Clinical Trial Dataset (vertical asset type)
('0f300104-0001-4000-8000-000000000004',
 'sdtm.onco-2025-001.dm',
 'CDISC SDTM DM (Demographics) dataset for protocol ONCO-2025-001.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Clinical Trial Dataset' LIMIT 1), '0f200102-0001-4000-8000-000000000002'), 'Databricks', 'sdtm.onco-2025-001.dm',
 '00000002-0001-4000-8000-000000000002',
 '{"protocol": "ONCO-2025-001", "cdisc_standard": "SDTM", "version": "3.3", "dataset": "DM"}',
 '["submission-ready", "21cfr-part-11"]',
 'active', 'system@demo', NOW(), NOW()),

-- Dashboard
('0f300105-0001-4000-8000-000000000005',
 'Trial Monitoring Dashboard',
 'Site enrollment, screen failure rate, and SAE summary across active oncology trials.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Dashboard' LIMIT 1), '0f200002-0000-4000-8000-000000000002'), 'Databricks', 'https://bi.pharma.com/dashboards/trial-monitoring',
 '00000002-0001-4000-8000-000000000002',
 '{"refresh_schedule": "daily", "audience": "study-team"}',
 '["analytics"]',
 'active', 'system@demo', NOW(), NOW()),

-- Streaming source (FAERS feed)
('0f300106-0001-4000-8000-000000000006',
 'kafka.pharma.faers.case_events',
 'Real-time stream of incoming FAERS adverse-event case submissions.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Stream' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Kafka', 'kafka://broker.pharma:9093/faers.case_events',
 '00000003-0001-4000-8000-000000000003',
 '{"topic": "faers.case_events", "throughput_msgs_per_sec": 1200}',
 '["real-time"]',
 'active', 'system@demo', NOW(), NOW()),

-- Adverse Event Case (vertical asset type)
('0f300107-0001-4000-8000-000000000007',
 'ICSR-2025-4521',
 'Individual Case Safety Report — serious adverse event, drug XYZ.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Adverse Event Case' LIMIT 1), '0f200103-0001-4000-8000-000000000003'), 'Pharma Safety DB', 'safety://cases/ICSR-2025-4521',
 '00000003-0001-4000-8000-000000000003',
 '{"seriousness": "serious", "expectedness": "unexpected", "days_to_report": 12, "regulatory_status": "submitted"}',
 '["hipaa", "21cfr-part-11"]',
 'active', 'system@demo', NOW(), NOW()),

-- Claims table
('0f300108-0001-4000-8000-000000000008',
 'lakehouse.hls.claims.adjudicated',
 'Adjudicated medical and pharmacy claims (commercial + Medicare Advantage).',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.hls.claims.adjudicated',
 '00000006-0001-4000-8000-000000000006',
 '{"catalog": "lakehouse", "schema": "hls_claims", "table_name": "adjudicated", "row_count": 45000000, "format": "delta"}',
 '["curated"]',
 'active', 'system@demo', NOW(), NOW()),

-- ── Column assets for the HLS Tables / Streams above ──
-- 0f300101 lakehouse.hls.curated.patients
('0f520101-0001-4000-8000-000000000001', 'patient_id',     'De-identified patient identifier (hash of MRN)',  (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.patients.patient_id',     '00000001-0001-4000-8000-000000000001', '{"data_type": "STRING",   "nullable": false, "is_primary_key": true}', '["phi", "key", "deidentified"]', 'active', 'system@demo', NOW(), NOW()),
('0f520102-0001-4000-8000-000000000002', 'date_of_birth',  'Patient date of birth (Safe Harbor shifted)',     (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.patients.date_of_birth',  '00000001-0001-4000-8000-000000000001', '{"data_type": "DATE",     "nullable": false}',                          '["phi", "deidentified"]',         'active', 'system@demo', NOW(), NOW()),
('0f520103-0001-4000-8000-000000000003', 'gender',         'Administrative gender (M/F/O/U)',                 (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.patients.gender',         '00000001-0001-4000-8000-000000000001', '{"data_type": "STRING",   "nullable": false}',                          '["phi"]',                          'active', 'system@demo', NOW(), NOW()),
('0f520104-0001-4000-8000-000000000004', 'race_ethnicity', 'OMB race/ethnicity category',                     (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.patients.race_ethnicity', '00000001-0001-4000-8000-000000000001', '{"data_type": "STRING",   "nullable": true }',                          '["phi"]',                          'active', 'system@demo', NOW(), NOW()),
('0f520105-0001-4000-8000-000000000005', 'zip_3',          'First 3 digits of ZIP (Safe Harbor)',             (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.patients.zip_3',          '00000001-0001-4000-8000-000000000001', '{"data_type": "STRING",   "nullable": true }',                          '["phi", "deidentified"]',         'active', 'system@demo', NOW(), NOW()),

-- 0f300102 lakehouse.hls.curated.encounters
('0f520111-0001-4000-8000-000000000011', 'encounter_id',   'Unique encounter identifier',                     (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.encounters.encounter_id',  '00000001-0001-4000-8000-000000000001', '{"data_type": "STRING",   "nullable": false, "is_primary_key": true}', '["phi", "key"]',                  'active', 'system@demo', NOW(), NOW()),
('0f520112-0001-4000-8000-000000000012', 'patient_id',     'FK to patients.patient_id',                       (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.encounters.patient_id',    '00000001-0001-4000-8000-000000000001', '{"data_type": "STRING",   "nullable": false}',                          '["phi", "fk"]',                   'active', 'system@demo', NOW(), NOW()),
('0f520113-0001-4000-8000-000000000013', 'encounter_type', 'inpatient | outpatient | emergency | observation',(SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.encounters.encounter_type','00000001-0001-4000-8000-000000000001', '{"data_type": "STRING",   "nullable": false}',                          '["phi"]',                          'active', 'system@demo', NOW(), NOW()),
('0f520114-0001-4000-8000-000000000014', 'admit_date',     'Admit/visit date (UTC)',                          (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.encounters.admit_date',    '00000001-0001-4000-8000-000000000001', '{"data_type": "TIMESTAMP","nullable": false, "partition_key": true}',  '["phi", "partition"]',            'active', 'system@demo', NOW(), NOW()),
('0f520115-0001-4000-8000-000000000015', 'discharge_date', 'Discharge date (NULL if still admitted)',         (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.curated.encounters.discharge_date','00000001-0001-4000-8000-000000000001', '{"data_type": "TIMESTAMP","nullable": true }',                          '["phi"]',                          'active', 'system@demo', NOW(), NOW()),

-- 0f300106 kafka.pharma.faers.case_events (Stream)
('0f520121-0001-4000-8000-000000000021', 'case_id',        'ICSR case number',                                (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Kafka',      'kafka.pharma.faers.case_events.case_id',         '00000003-0001-4000-8000-000000000003', '{"data_type": "STRING",  "nullable": false, "is_primary_key": true}', '["pharmacovigilance", "key"]',   'active', 'system@demo', NOW(), NOW()),
('0f520122-0001-4000-8000-000000000022', 'product_id',     'Product (substance) identifier',                  (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Kafka',      'kafka.pharma.faers.case_events.product_id',      '00000003-0001-4000-8000-000000000003', '{"data_type": "STRING",  "nullable": false}',                          '["pharmacovigilance"]',           'active', 'system@demo', NOW(), NOW()),
('0f520123-0001-4000-8000-000000000023', 'meddra_pt',      'MedDRA preferred term',                            (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Kafka',      'kafka.pharma.faers.case_events.meddra_pt',       '00000003-0001-4000-8000-000000000003', '{"data_type": "STRING",  "nullable": false}',                          '["pharmacovigilance"]',           'active', 'system@demo', NOW(), NOW()),
('0f520124-0001-4000-8000-000000000024', 'seriousness',    'serious | non_serious',                            (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Kafka',      'kafka.pharma.faers.case_events.seriousness',     '00000003-0001-4000-8000-000000000003', '{"data_type": "STRING",  "nullable": false}',                          '["pharmacovigilance"]',           'active', 'system@demo', NOW(), NOW()),
('0f520125-0001-4000-8000-000000000025', 'received_ts',    'Submission receive timestamp (UTC)',              (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Kafka',      'kafka.pharma.faers.case_events.received_ts',     '00000003-0001-4000-8000-000000000003', '{"data_type": "TIMESTAMP","nullable": false}',                         '["pharmacovigilance"]',           'active', 'system@demo', NOW(), NOW()),

-- 0f300108 lakehouse.hls.claims.adjudicated
('0f520131-0001-4000-8000-000000000031', 'claim_id',       'Unique medical claim identifier',                 (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.claims.adjudicated.claim_id',      '00000006-0001-4000-8000-000000000006', '{"data_type": "STRING",  "nullable": false, "is_primary_key": true}', '["claims", "key"]',               'active', 'system@demo', NOW(), NOW()),
('0f520132-0001-4000-8000-000000000032', 'member_id',      'Insurance plan member identifier',                (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.claims.adjudicated.member_id',     '00000006-0001-4000-8000-000000000006', '{"data_type": "STRING",  "nullable": false}',                          '["claims", "phi"]',               'active', 'system@demo', NOW(), NOW()),
('0f520133-0001-4000-8000-000000000033', 'service_date',   'Date of service (partition)',                     (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.claims.adjudicated.service_date',  '00000006-0001-4000-8000-000000000006', '{"data_type": "DATE",    "nullable": false, "partition_key": true}',  '["claims", "partition"]',         'active', 'system@demo', NOW(), NOW()),
('0f520134-0001-4000-8000-000000000034', 'cpt_code',       'CMS HCPCS / CPT procedure code',                  (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.claims.adjudicated.cpt_code',      '00000006-0001-4000-8000-000000000006', '{"data_type": "STRING",  "nullable": false}',                          '["claims"]',                       'active', 'system@demo', NOW(), NOW()),
('0f520135-0001-4000-8000-000000000035', 'allowed_amount', 'Amount allowed by payer (USD)',                   (SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), 'Databricks', 'lakehouse.hls.claims.adjudicated.allowed_amount','00000006-0001-4000-8000-000000000006', '{"data_type": "DECIMAL(18,2)","nullable": false}',                     '["claims", "kpi"]',               'active', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 15b. hasColumn RELATIONSHIPS (HLS)
-- ============================================================================
INSERT INTO entity_relationships (id, source_type, source_id, target_type, target_id, relationship_type, properties, created_by, created_at) VALUES
('0f620101-0001-4000-8000-000000000001', 'Table',  '0f300101-0001-4000-8000-000000000001', 'Column', '0f520101-0001-4000-8000-000000000001', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620102-0001-4000-8000-000000000002', 'Table',  '0f300101-0001-4000-8000-000000000001', 'Column', '0f520102-0001-4000-8000-000000000002', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620103-0001-4000-8000-000000000003', 'Table',  '0f300101-0001-4000-8000-000000000001', 'Column', '0f520103-0001-4000-8000-000000000003', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620104-0001-4000-8000-000000000004', 'Table',  '0f300101-0001-4000-8000-000000000001', 'Column', '0f520104-0001-4000-8000-000000000004', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620105-0001-4000-8000-000000000005', 'Table',  '0f300101-0001-4000-8000-000000000001', 'Column', '0f520105-0001-4000-8000-000000000005', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620111-0001-4000-8000-000000000011', 'Table',  '0f300102-0001-4000-8000-000000000002', 'Column', '0f520111-0001-4000-8000-000000000011', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620112-0001-4000-8000-000000000012', 'Table',  '0f300102-0001-4000-8000-000000000002', 'Column', '0f520112-0001-4000-8000-000000000012', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620113-0001-4000-8000-000000000013', 'Table',  '0f300102-0001-4000-8000-000000000002', 'Column', '0f520113-0001-4000-8000-000000000013', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620114-0001-4000-8000-000000000014', 'Table',  '0f300102-0001-4000-8000-000000000002', 'Column', '0f520114-0001-4000-8000-000000000014', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620115-0001-4000-8000-000000000015', 'Table',  '0f300102-0001-4000-8000-000000000002', 'Column', '0f520115-0001-4000-8000-000000000015', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620121-0001-4000-8000-000000000021', 'Stream', '0f300106-0001-4000-8000-000000000006', 'Column', '0f520121-0001-4000-8000-000000000021', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620122-0001-4000-8000-000000000022', 'Stream', '0f300106-0001-4000-8000-000000000006', 'Column', '0f520122-0001-4000-8000-000000000022', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620123-0001-4000-8000-000000000023', 'Stream', '0f300106-0001-4000-8000-000000000006', 'Column', '0f520123-0001-4000-8000-000000000023', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620124-0001-4000-8000-000000000024', 'Stream', '0f300106-0001-4000-8000-000000000006', 'Column', '0f520124-0001-4000-8000-000000000024', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620125-0001-4000-8000-000000000025', 'Stream', '0f300106-0001-4000-8000-000000000006', 'Column', '0f520125-0001-4000-8000-000000000025', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620131-0001-4000-8000-000000000031', 'Table',  '0f300108-0001-4000-8000-000000000008', 'Column', '0f520131-0001-4000-8000-000000000031', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620132-0001-4000-8000-000000000032', 'Table',  '0f300108-0001-4000-8000-000000000008', 'Column', '0f520132-0001-4000-8000-000000000032', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620133-0001-4000-8000-000000000033', 'Table',  '0f300108-0001-4000-8000-000000000008', 'Column', '0f520133-0001-4000-8000-000000000033', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620134-0001-4000-8000-000000000034', 'Table',  '0f300108-0001-4000-8000-000000000008', 'Column', '0f520134-0001-4000-8000-000000000034', 'hasColumn', NULL, 'system@demo', NOW()),
('0f620135-0001-4000-8000-000000000035', 'Table',  '0f300108-0001-4000-8000-000000000008', 'Column', '0f520135-0001-4000-8000-000000000035', 'hasColumn', NULL, 'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 16. ENTITY RELATIONSHIPS — HLS lineage (type=0fa for business lineage)
-- ============================================================================

INSERT INTO entity_relationships (id, source_type, source_id, target_type, target_id, relationship_type, created_by, created_at) VALUES
-- Patient 360 product → underlying tables (lineage)
('0fa00101-0001-4000-8000-000000000001', 'data_product', '00700001-0001-4000-8000-000000000001', 'asset', '0f300101-0001-4000-8000-000000000001', 'derives_from', 'system@demo', NOW()),
('0fa00102-0001-4000-8000-000000000002', 'data_product', '00700001-0001-4000-8000-000000000001', 'asset', '0f300102-0001-4000-8000-000000000002', 'derives_from', 'system@demo', NOW()),
-- Clinical Trial Analytics product → SDTM dataset
('0fa00103-0001-4000-8000-000000000003', 'data_product', '00700002-0001-4000-8000-000000000002', 'asset', '0f300104-0001-4000-8000-000000000004', 'derives_from', 'system@demo', NOW()),
-- Drug Safety Signal Detection product → FAERS stream + ICSR cases
('0fa00104-0001-4000-8000-000000000004', 'data_product', '00700003-0001-4000-8000-000000000003', 'asset', '0f300106-0001-4000-8000-000000000006', 'derives_from', 'system@demo', NOW()),
('0fa00105-0001-4000-8000-000000000005', 'data_product', '00700003-0001-4000-8000-000000000003', 'asset', '0f300107-0001-4000-8000-000000000007', 'consumes', 'system@demo', NOW()),
-- RWE Platform product → claims + cohort
('0fa00106-0001-4000-8000-000000000006', 'data_product', '00700004-0001-4000-8000-000000000004', 'asset', '0f300108-0001-4000-8000-000000000008', 'derives_from', 'system@demo', NOW()),
('0fa00107-0001-4000-8000-000000000007', 'data_product', '00700004-0001-4000-8000-000000000004', 'asset', '0f300103-0001-4000-8000-000000000003', 'consumes', 'system@demo', NOW()),
-- Claims Analytics product → claims table
('0fa00108-0001-4000-8000-000000000008', 'data_product', '00700005-0001-4000-8000-000000000005', 'asset', '0f300108-0001-4000-8000-000000000008', 'derives_from', 'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 17. ENTITY TAG ASSOCIATIONS (HLS, type=029)
-- ============================================================================

INSERT INTO entity_tag_associations (id, tag_id, entity_id, entity_type, assigned_value, assigned_by, assigned_at) VALUES
-- Patient 360 product
('02900101-0001-4000-8000-000000000001', '02700102-0001-4000-8000-000000000002', '00700001-0001-4000-8000-000000000001', 'data_product', NULL, 'system@demo', NOW()),
('02900102-0001-4000-8000-000000000002', '02700104-0001-4000-8000-000000000004', '00700001-0001-4000-8000-000000000001', 'data_product', NULL, 'system@demo', NOW()),
-- Clinical Trial Analytics product
('02900103-0001-4000-8000-000000000003', '02700105-0001-4000-8000-000000000005', '00700002-0001-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),
('02900104-0001-4000-8000-000000000004', '02700108-0001-4000-8000-000000000008', '00700002-0001-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),
('02900105-0001-4000-8000-000000000005', '02700106-0001-4000-8000-000000000006', '00700002-0001-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),
-- Drug Safety
('02900106-0001-4000-8000-000000000006', '02700104-0001-4000-8000-000000000004', '00700003-0001-4000-8000-000000000003', 'data_product', NULL, 'system@demo', NOW()),
('02900107-0001-4000-8000-000000000007', '02700105-0001-4000-8000-000000000005', '00700003-0001-4000-8000-000000000003', 'data_product', NULL, 'system@demo', NOW()),
-- RWE
('02900108-0001-4000-8000-000000000008', '02700109-0001-4000-8000-000000000009', '00700004-0001-4000-8000-000000000004', 'data_product', NULL, 'system@demo', NOW()),
('02900109-0001-4000-8000-000000000009', '02700107-0001-4000-8000-000000000007', '00700004-0001-4000-8000-000000000004', 'data_product', NULL, 'system@demo', NOW()),
-- Contracts
('0290010a-0001-4000-8000-000000000010', '02700101-0001-4000-8000-000000000001', '00400001-0001-4000-8000-000000000001', 'data_contract', NULL, 'system@demo', NOW()),
('0290010b-0001-4000-8000-000000000011', '02700104-0001-4000-8000-000000000004', '00400001-0001-4000-8000-000000000001', 'data_contract', NULL, 'system@demo', NOW())
ON CONFLICT (tag_id, entity_id, entity_type) DO NOTHING;


-- ============================================================================
-- 18. PROCESS WORKFLOWS + STEPS (HLS-specific)
-- ============================================================================

INSERT INTO process_workflows (id, name, description, trigger_config, scope_config, is_active, is_default, version, created_by, updated_by, created_at, updated_at) VALUES
('02a00101-0001-4000-8000-000000000001', 'IRB Approval Gate',
 'Block publishing of clinical research data products until IRB approval is on file.',
 '{"type": "before_publish", "entity_types": ["data_product"]}',
 '{"type": "domain", "ids": ["00000002-0001-4000-8000-000000000002"]}',
 true, true, 1, 'system@demo', 'system@demo', NOW(), NOW()),
('02a00102-0001-4000-8000-000000000002', 'HIPAA PHI Pre-Publish Check',
 'Validates that PHI is de-identified or covered by a signed BAA before any HLS data product is exposed to consumers.',
 '{"type": "before_publish", "entity_types": ["data_product", "data_contract"]}',
 '{"type": "all"}',
 true, true, 1, 'system@demo', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO workflow_steps (id, workflow_id, step_id, name, step_type, config, on_pass, on_fail, "order", position, created_at, updated_at) VALUES
('02b00101-0001-4000-8000-000000000001', '02a00101-0001-4000-8000-000000000001', 'irb_doc_check', 'IRB Document Present',
 'policy_check',
 '{"policy_id": "01100002-0001-4000-8000-000000000002"}',
 'irb_active', 'reject', 1, '{"x": 100, "y": 100}', NOW(), NOW()),
('02b00102-0001-4000-8000-000000000002', '02a00101-0001-4000-8000-000000000001', 'irb_active',     'IRB Approval Active',
 'manual_approval',
 '{"approver_role": "0f000003-0001-4000-8000-000000000003"}',
 'approve', 'reject', 2, '{"x": 300, "y": 100}', NOW(), NOW()),
('02b00103-0001-4000-8000-000000000003', '02a00102-0001-4000-8000-000000000002', 'phi_classification', 'PHI Classification',
 'policy_check',
 '{"policy_id": "01100001-0001-4000-8000-000000000001"}',
 'phi_review', 'block', 1, '{"x": 100, "y": 100}', NOW(), NOW()),
('02b00104-0001-4000-8000-000000000004', '02a00102-0001-4000-8000-000000000002', 'phi_review', 'Privacy Officer Review',
 'manual_approval',
 '{"approver_role": "0f000004-0001-4000-8000-000000000004"}',
 'approve', 'block', 2, '{"x": 300, "y": 100}', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 19. COMPLIANCE RUNS + RESULTS (HLS, types 012 / 013)
-- ============================================================================

INSERT INTO compliance_runs (id, policy_id, status, started_at, finished_at, success_count, failure_count, score) VALUES
('01200101-0001-4000-8000-000000000001', '01100001-0001-4000-8000-000000000001', 'completed', NOW() - INTERVAL '7 days', NOW() - INTERVAL '7 days' + INTERVAL '12 minutes', 6, 1, 0.857),
('01200102-0001-4000-8000-000000000002', '01100002-0001-4000-8000-000000000002', 'completed', NOW() - INTERVAL '5 days', NOW() - INTERVAL '5 days' + INTERVAL '8 minutes',  4, 0, 1.000),
('01200103-0001-4000-8000-000000000003', '01100004-0001-4000-8000-000000000004', 'completed', NOW() - INTERVAL '1 days', NOW() - INTERVAL '1 days' + INTERVAL '4 minutes',  2, 1, 0.667)
ON CONFLICT (id) DO NOTHING;

INSERT INTO compliance_results (id, run_id, object_type, object_id, object_name, passed, message, created_at) VALUES
('01300101-0001-4000-8000-000000000001', '01200101-0001-4000-8000-000000000001', 'data_product', '00700001-0001-4000-8000-000000000001', 'Patient 360 View v1',                 true,  'PHI de-identification verified.', NOW() - INTERVAL '7 days'),
('01300102-0001-4000-8000-000000000002', '01200101-0001-4000-8000-000000000001', 'data_product', '00700004-0001-4000-8000-000000000004', 'Real-World Evidence Platform v1',     true,  'Limited Data Set certification on file.', NOW() - INTERVAL '7 days'),
('01300103-0001-4000-8000-000000000003', '01200101-0001-4000-8000-000000000001', 'data_contract','00400003-0001-4000-8000-000000000003', 'Adverse Event Reports Contract',      false, 'Free-text narrative may contain residual PHI; manual review queued.', NOW() - INTERVAL '7 days'),
('01300104-0001-4000-8000-000000000004', '01200102-0001-4000-8000-000000000002', 'data_product', '00700002-0001-4000-8000-000000000002', 'Clinical Trial Analytics v1',         true,  'Audit trail validated against 21 CFR Part 11.', NOW() - INTERVAL '5 days'),
('01300105-0001-4000-8000-000000000005', '01200103-0001-4000-8000-000000000003', 'data_product', '00700003-0001-4000-8000-000000000003', 'Drug Safety Signal Detection v1',     false, 'One ICSR exceeded the 15-day reporting window (case ICSR-2025-4521).', NOW() - INTERVAL '1 days')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 20. COST ITEMS (HLS, type=014)
-- ============================================================================

INSERT INTO cost_items (id, entity_type, entity_id, title, description, cost_center, custom_center_name, amount_cents, currency, start_month, created_by, created_at, updated_at) VALUES
('01400101-0001-4000-8000-000000000001', 'data_product', '00700001-0001-4000-8000-000000000001', 'Compute (DBU)',          'Monthly Databricks compute for Patient 360 pipelines.',     'infrastructure', NULL, 1820000, 'USD', '2026-01-01', 'system@demo', NOW(), NOW()),
('01400102-0001-4000-8000-000000000002', 'data_product', '00700002-0001-4000-8000-000000000002', 'CDISC Validator Tooling','Annual license for CDISC SDTM/ADaM validation tooling.',    'tools',          NULL,  650000, 'USD', '2026-01-01', 'system@demo', NOW(), NOW()),
('01400103-0001-4000-8000-000000000003', 'data_product', '00700003-0001-4000-8000-000000000003', 'Pharmacovigilance FTE',  'Two FTE pharmacovigilance analysts allocated to signal review.', 'hr',          NULL, 4500000, 'USD', '2026-01-01', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 21. COMMENTS & RATINGS (HLS, type=02c)
-- ============================================================================

INSERT INTO comments (id, entity_type, entity_id, comment, comment_type, rating, status, created_by, created_at, updated_at) VALUES
('02c00101-0001-4000-8000-000000000001', 'data_product', '00700001-0001-4000-8000-000000000001', 'Outstanding starting point for population-health analyses; FHIR mapping is excellent.', 'rating', 5, 'active', 'dr.chen@hospital.org',         NOW() - INTERVAL '14 days', NOW() - INTERVAL '14 days'),
('02c00102-0001-4000-8000-000000000002', 'data_product', '00700002-0001-4000-8000-000000000002', 'CDISC compliance is solid. Would love deeper ADaM coverage in v2.',                       'rating', 4, 'active', 'dr.patel@pharma.com',          NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'),
('02c00103-0001-4000-8000-000000000003', 'data_product', '00700003-0001-4000-8000-000000000003', 'Signal detection works well; needs better narrative summarization.',                      'rating', 4, 'active', 'sarah.compliance@pharma.com',  NOW() - INTERVAL '8 days',  NOW() - INTERVAL '8 days'),
('02c00104-0001-4000-8000-000000000004', 'data_product', '00700004-0001-4000-8000-000000000004', 'Cohort builder UX is great. Linkage rate documented clearly.',                            'rating', 5, 'active', 'rwe-lead@pharma.com',          NOW() - INTERVAL '4 days',  NOW() - INTERVAL '4 days'),
('02c00105-0001-4000-8000-000000000005', 'data_product', '00700005-0001-4000-8000-000000000005', 'Denial drill-down by payer + CPT is exactly what RCM needed.',                            'rating', 5, 'active', 'rcm-analyst@hospital.org',     NOW() - INTERVAL '2 days',  NOW() - INTERVAL '2 days')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 22. BUSINESS OWNERS (HLS, type=0fb)
-- ============================================================================

INSERT INTO business_owners (id, object_type, object_id, user_email, user_name, role_id, is_active, assigned_at, removed_at, removal_reason, created_by, created_at, updated_at) VALUES
('0fb00101-0001-4000-8000-000000000001', 'data_product',  '00700001-0001-4000-8000-000000000001', 'dr.chen@hospital.org',         'Dr. Wei Chen',         '0f000001-0001-4000-8000-000000000001', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0fb00102-0001-4000-8000-000000000002', 'data_product',  '00700002-0001-4000-8000-000000000002', 'dr.patel@pharma.com',          'Dr. Anita Patel',      '0f000002-0001-4000-8000-000000000002', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0fb00103-0001-4000-8000-000000000003', 'data_product',  '00700003-0001-4000-8000-000000000003', 'sarah.compliance@pharma.com',  'Sarah Compliance',     '0f000005-0001-4000-8000-000000000005', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0fb00104-0001-4000-8000-000000000004', 'data_contract', '00400001-0001-4000-8000-000000000001', 'dr.chen@hospital.org',         'Dr. Wei Chen',         '0f000004-0001-4000-8000-000000000004', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0fb00105-0001-4000-8000-000000000005', 'data_contract', '00400003-0001-4000-8000-000000000003', 'sarah.compliance@pharma.com',  'Sarah Compliance',     '0f000005-0001-4000-8000-000000000005', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 23. ENTITY SUBSCRIPTIONS (HLS, type=022)
-- ============================================================================

INSERT INTO entity_subscriptions (id, entity_type, entity_id, subscriber_email, subscription_reason, created_at) VALUES
('02200101-0001-4000-8000-000000000001', 'data_product', '00700001-0001-4000-8000-000000000001', 'dr.chen@hospital.org',     'owner',     NOW() - INTERVAL '60 days'),
('02200102-0001-4000-8000-000000000002', 'data_product', '00700001-0001-4000-8000-000000000001', 'rwe-lead@pharma.com',      'consumer',  NOW() - INTERVAL '30 days'),
('02200103-0001-4000-8000-000000000003', 'data_product', '00700003-0001-4000-8000-000000000003', 'sarah.compliance@pharma.com', 'owner',  NOW() - INTERVAL '60 days')
ON CONFLICT DO NOTHING;


COMMIT;

-- ============================================================================
-- End of HLS Demo Data — preset=hls
-- ============================================================================
