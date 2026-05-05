-- ============================================================================
-- Industry Demo Data: Health & Life Sciences (HLS)
-- ============================================================================
-- Additive overlay loaded via: POST /api/settings/demo-data/load?industry=hls
--
-- Adds HLS-specific data domains, teams, contracts, products, and compliance
-- policies. References base demo teams where appropriate.
--
-- Dataset identifier: 0001 (second UUID group)
-- UUID Format: {type:3}{seq:5}-0001-4000-8000-00000000000N
-- ============================================================================

BEGIN;

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

INSERT INTO data_contracts (id, name, kind, api_version, version, status, published, owner_team_id, domain_id, description_purpose, description_usage, description_limitations, publication_scope, created_by, updated_by, created_at, updated_at) VALUES
('00400001-0001-4000-8000-000000000001', 'Patient EHR Data Contract', 'DataContract', 'v3.1.0', '2.0.0', 'active', true, '00100001-0001-4000-8000-000000000001', '00000001-0001-4000-8000-000000000001', 'Standardized patient electronic health record data for clinical analytics and care coordination', 'Integrate into clinical dashboards, care pathway analysis, and population health management', 'All PHI must be de-identified for analytics; HIPAA Safe Harbor rules apply; data retention 7 years per state regulations', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400002-0001-4000-8000-000000000002', 'Clinical Trial Data Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100002-0001-4000-8000-000000000002', '00000002-0001-4000-8000-000000000002', 'Clinical trial enrollment, randomization, endpoint, and adverse event data', 'Support study monitoring, interim analyses, DSMB reporting, and regulatory submissions', 'Subject-level data requires IRB approval; blinded data restricted until study unblinding; 21 CFR Part 11 compliant', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400003-0001-4000-8000-000000000003', 'Adverse Event Reporting Contract', 'DataContract', 'v3.1.0', '1.1.0', 'active', true, '00100003-0001-4000-8000-000000000003', '00000003-0001-4000-8000-000000000003', 'Spontaneous and solicited adverse event reports for pharmacovigilance signal detection', 'Feed into safety signal detection algorithms, periodic safety reports (PSURs), and FDA FAERS submissions', 'MedDRA coding required; reporter identities must be anonymized; 15-day expedited reporting for serious AEs', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400004-0001-4000-8000-000000000004', 'Genomic Sequencing Contract', 'DataContract', 'v3.1.0', '1.0.0', 'draft', false, '00100002-0001-4000-8000-000000000002', '00000004-0001-4000-8000-000000000004', 'Whole genome and exome sequencing data for precision medicine research', 'Variant calling pipelines, biomarker discovery, and companion diagnostic development', 'Consent-gated access; re-identification risk assessment required; GINA compliance mandatory', 'none', 'system@demo', 'system@demo', NOW(), NOW()),

('00400005-0001-4000-8000-000000000005', 'Claims & Reimbursement Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100001-0001-4000-8000-000000000001', '00000006-0001-4000-8000-000000000006', 'Healthcare insurance claims, adjudication outcomes, and reimbursement data', 'Revenue cycle analytics, denial management, and payer contract optimization', 'CMS HCPCS/CPT coding standards; member SSN must be masked; data shared under BAA only', 'org', 'system@demo', 'system@demo', NOW(), NOW())

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
('00600014-0001-4000-8000-000000000020', '00500007-0001-4000-8000-000000000007', 'outcome', 'string', true, false, false, false, -1, -1, false, 'recovered, recovering, not_recovered, fatal, unknown')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5. DATA PRODUCTS
-- ============================================================================

INSERT INTO data_products (id, api_version, kind, status, name, version, domain, tenant, owner_team_id, max_level_inheritance, published, publication_scope, created_at, updated_at) VALUES
('00700001-0001-4000-8000-000000000001', 'v1.0.0', 'DataProduct', 'active', 'Patient 360 View v1', '1.0.0', 'Clinical', 'hls-demo', '00100001-0001-4000-8000-000000000001', 99, true, 'org', NOW(), NOW()),
('00700002-0001-4000-8000-000000000002', 'v1.0.0', 'DataProduct', 'active', 'Clinical Trial Analytics v1', '1.0.0', 'Research', 'hls-demo', '00100002-0001-4000-8000-000000000002', 99, true, 'org', NOW(), NOW()),
('00700003-0001-4000-8000-000000000003', 'v1.0.0', 'DataProduct', 'active', 'Drug Safety Signal Detection v1', '1.0.0', 'Regulatory', 'hls-demo', '00100003-0001-4000-8000-000000000003', 99, true, 'org', NOW(), NOW()),
('00700004-0001-4000-8000-000000000004', 'v1.0.0', 'DataProduct', 'active', 'Real-World Evidence Platform v1', '1.0.0', 'Research', 'hls-demo', '00100002-0001-4000-8000-000000000002', 99, true, 'org', NOW(), NOW()),
('00700005-0001-4000-8000-000000000005', 'v1.0.0', 'DataProduct', 'active', 'Claims Analytics Dashboard v1', '1.0.0', 'Claims', 'hls-demo', '00100001-0001-4000-8000-000000000001', 99, true, 'org', NOW(), NOW())

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


COMMIT;

-- ============================================================================
-- End of HLS Industry Demo Data
-- ============================================================================
