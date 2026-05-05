-- ============================================================================
-- Industry Demo Data: Automotive (AUTO)
-- ============================================================================
-- Additive overlay loaded via: POST /api/settings/demo-data/load?industry=auto
--
-- Adds automotive-specific data domains, teams, contracts, products, and
-- compliance policies covering connected vehicles, ADAS, supply chain quality,
-- warranty analytics, and vehicle configuration management.
--
-- Dataset identifier: 0004 (second UUID group)
-- UUID Format: {type:3}{seq:5}-0004-4000-8000-00000000000N
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. DATA DOMAINS (AUTO-specific, children of Core)
-- ============================================================================

INSERT INTO data_domains (id, name, description, parent_id, created_by, created_at, updated_at) VALUES
('00000001-0004-4000-8000-000000000001', 'Vehicle Engineering', 'Vehicle design, PLM, CAD data, and engineering change management.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000002-0004-4000-8000-000000000002', 'Connected Vehicles', 'Telematics, OTA updates, V2X communication, and in-vehicle diagnostics.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000003-0004-4000-8000-000000000003', 'Autonomous Driving', 'ADAS sensor data, perception models, HD mapping, and simulation.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000004-0004-4000-8000-000000000004', 'Supply Chain & Procurement', 'Tier-N supplier management, JIT/JIS logistics, and sourcing analytics.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000005-0004-4000-8000-000000000005', 'After-Sales & Warranty', 'Warranty claims, recall campaigns, dealer service, and parts logistics.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000006-0004-4000-8000-000000000006', 'Vehicle Manufacturing', 'Body shop, paint, final assembly, and end-of-line testing.', '00000001-0004-4000-8000-000000000001', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2. TEAMS
-- ============================================================================

INSERT INTO teams (id, name, title, description, domain_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00100001-0004-4000-8000-000000000001', 'connected-vehicle-platform', 'Connected Vehicle Platform Team', 'Telematics data platform, OTA update orchestration, and remote diagnostics', '00000002-0004-4000-8000-000000000002', '{"slack_channel": "https://company.slack.com/channels/cv-platform", "lead": "cv.architect@oem.com"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100002-0004-4000-8000-000000000002', 'adas-engineering', 'ADAS & AD Engineering Team', 'Sensor fusion, perception model training, and autonomous driving validation', '00000003-0004-4000-8000-000000000003', '{"slack_channel": "https://company.slack.com/channels/adas-eng", "tools": ["ROS2", "CARLA", "NVIDIA DRIVE"]}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100003-0004-4000-8000-000000000003', 'supply-chain-quality', 'Supply Chain Quality Team', 'Supplier PPAP/APQP management, incoming quality, and supply risk analytics', '00000004-0004-4000-8000-000000000004', '{"slack_channel": "https://company.slack.com/channels/scq-team", "responsibilities": ["PPAP", "APQP", "8D", "Supplier Audits"]}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2b. TEAM MEMBERS
-- ============================================================================

INSERT INTO team_members (id, team_id, member_type, member_identifier, app_role_override, added_by, created_at, updated_at) VALUES
('00200001-0004-4000-8000-000000000001', '00100001-0004-4000-8000-000000000001', 'user', 'cv.architect@oem.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200002-0004-4000-8000-000000000002', '00100001-0004-4000-8000-000000000001', 'group', 'connected-vehicle-devs', NULL, 'system@demo', NOW(), NOW()),
('00200003-0004-4000-8000-000000000003', '00100002-0004-4000-8000-000000000002', 'user', 'adas.lead@oem.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200004-0004-4000-8000-000000000004', '00100002-0004-4000-8000-000000000002', 'group', 'perception-engineers', NULL, 'system@demo', NOW(), NOW()),
('00200005-0004-4000-8000-000000000005', '00100003-0004-4000-8000-000000000003', 'user', 'sqe.manager@oem.com', 'Data Steward', 'system@demo', NOW(), NOW()),
('00200006-0004-4000-8000-000000000006', '00100003-0004-4000-8000-000000000003', 'group', 'supplier-quality-engineers', NULL, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3. PROJECTS
-- ============================================================================

INSERT INTO projects (id, name, title, description, project_type, owner_team_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00300001-0004-4000-8000-000000000001', 'sdv-data-platform', 'Software-Defined Vehicle Data Platform', 'Unified data lakehouse for vehicle telemetry, diagnostics, and OTA analytics across the global fleet', 'TEAM', '00100001-0004-4000-8000-000000000001', '{"budget": "$4.5M", "timeline": "18 months", "technologies": ["Kafka", "Spark Streaming", "Delta Lake", "Unity Catalog"], "priority": "critical"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300002-0004-4000-8000-000000000002', 'adas-data-lake', 'ADAS Training Data Pipeline', 'Petabyte-scale data pipeline for autonomous driving model training, validation, and simulation', 'TEAM', '00100002-0004-4000-8000-000000000002', '{"budget": "$6M", "timeline": "24 months", "technologies": ["Mosaic ML", "Petastorm", "Rosbag", "nuScenes"], "priority": "critical"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300003-0004-4000-8000-000000000003', 'supplier-risk-analytics', 'Supplier Risk & Quality Analytics', 'Real-time supplier risk scoring, PPAP tracking, and early warning system for supply disruptions', 'TEAM', '00100003-0004-4000-8000-000000000003', '{"budget": "$1.2M", "timeline": "10 months", "compliance": ["IATF 16949", "VDA 6.3", "AIAG"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3b. PROJECT-TEAM ASSOCIATIONS
-- ============================================================================

INSERT INTO project_teams (project_id, team_id, assigned_by, assigned_at) VALUES
('00300001-0004-4000-8000-000000000001', '00100001-0004-4000-8000-000000000001', 'system@demo', NOW()),
('00300001-0004-4000-8000-000000000001', '00100002-0004-4000-8000-000000000002', 'system@demo', NOW()),
('00300002-0004-4000-8000-000000000002', '00100002-0004-4000-8000-000000000002', 'system@demo', NOW()),
('00300002-0004-4000-8000-000000000002', '00100001-0004-4000-8000-000000000001', 'system@demo', NOW()),
('00300003-0004-4000-8000-000000000003', '00100003-0004-4000-8000-000000000003', 'system@demo', NOW()),
('00300003-0004-4000-8000-000000000003', '00100001-0004-4000-8000-000000000001', 'system@demo', NOW())

ON CONFLICT (project_id, team_id) DO NOTHING;


-- ============================================================================
-- 4. DATA CONTRACTS
-- ============================================================================

INSERT INTO data_contracts (id, name, kind, api_version, version, status, published, owner_team_id, domain_id, description_purpose, description_usage, description_limitations, publication_scope, created_by, updated_by, created_at, updated_at) VALUES
('00400001-0004-4000-8000-000000000001', 'Vehicle Telematics Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100001-0004-4000-8000-000000000001', '00000002-0004-4000-8000-000000000002', 'Standardized vehicle telemetry including CAN bus signals, diagnostic trouble codes, and driving behavior events', 'Fleet health monitoring, predictive maintenance, usage-based insurance, and OTA campaign targeting', 'CAN signal sampling rate varies by ECU (10ms-1s); DTC freeze-frame data limited to 3 snapshots; GPS accuracy ±3m in urban canyons', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400002-0004-4000-8000-000000000002', 'ADAS Sensor Data Contract', 'DataContract', 'v3.1.0', '2.0.0', 'active', true, '00100002-0004-4000-8000-000000000002', '00000003-0004-4000-8000-000000000003', 'Camera, LiDAR, radar, and ultrasonic sensor recordings with synchronized timestamps and ego-vehicle pose', 'Perception model training, corner-case mining, simulation replay, and safety validation per ISO 21448 (SOTIF)', 'LiDAR point clouds at 10Hz; camera frames at 30fps; radar at 20Hz; temporal sync tolerance ±5ms; PII (faces, plates) must be anonymized before model training', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400003-0004-4000-8000-000000000003', 'Supplier Quality Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100003-0004-4000-8000-000000000003', '00000004-0004-4000-8000-000000000004', 'PPAP submissions, incoming inspection data, supplier SPC, and 8D corrective action reports', 'Supplier quality scorecard, incoming quality trends, PPAP status tracking, and risk-based audit planning', 'Supplier SPC data pushed daily via EDI; 8D reports require manual review before closure; sub-tier data limited to Tier-1 disclosures', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400004-0004-4000-8000-000000000004', 'Warranty Claims Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100001-0004-4000-8000-000000000001', '00000005-0004-4000-8000-000000000005', 'Dealer warranty claims, field failure reports, recall campaign data, and goodwill repair authorizations', 'Early warning analytics, cost-per-vehicle trending, NTF (no trouble found) reduction, and recall scope optimization', 'Claims data lags 5-10 business days from dealer submission; labor codes vary by market; goodwill claims excluded from CPV calculations', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400005-0004-4000-8000-000000000005', 'Vehicle Configuration & BOM Contract', 'DataContract', 'v3.1.0', '1.0.0', 'draft', false, '00100001-0004-4000-8000-000000000001', '00000001-0004-4000-8000-000000000001', 'As-built vehicle configuration, 150% BOM, option constraint rules, and engineering change orders', 'Build-to-order scheduling, variant cost analysis, and engineering change impact assessment', 'ECO effectivity transitions may create temporary BOM inconsistencies; market-specific options encoded differently across legacy PLM systems', 'none', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4b. DATA CONTRACT SCHEMA OBJECTS
-- ============================================================================

INSERT INTO data_contract_schema_objects (id, contract_id, name, logical_type, physical_name, description) VALUES
-- Vehicle Telematics
('00500001-0004-4000-8000-000000000001', '00400001-0004-4000-8000-000000000001', 'vehicle_signals', 'object', 'telematics.can_bus_signals', 'Decoded CAN bus signals per vehicle trip'),
('00500002-0004-4000-8000-000000000002', '00400001-0004-4000-8000-000000000001', 'diagnostic_codes', 'object', 'telematics.dtc_events', 'Diagnostic trouble code events with freeze-frame data'),
('00500003-0004-4000-8000-000000000003', '00400001-0004-4000-8000-000000000001', 'driving_events', 'object', 'telematics.driving_behavior', 'Hard braking, rapid acceleration, and cornering events'),

-- ADAS Sensor Data
('00500004-0004-4000-8000-000000000004', '00400002-0004-4000-8000-000000000002', 'sensor_recordings', 'object', 'adas.sensor_recordings', 'Multi-modal sensor recording metadata and storage references'),
('00500005-0004-4000-8000-000000000005', '00400002-0004-4000-8000-000000000002', 'annotations', 'object', 'adas.ground_truth_labels', '3D bounding box and semantic segmentation annotations'),

-- Supplier Quality
('00500006-0004-4000-8000-000000000006', '00400003-0004-4000-8000-000000000003', 'ppap_submissions', 'object', 'supply_chain.ppap_records', 'PPAP level submissions and element status'),
('00500007-0004-4000-8000-000000000007', '00400003-0004-4000-8000-000000000003', 'incoming_inspections', 'object', 'supply_chain.incoming_quality', 'Incoming material inspection results'),

-- Warranty Claims
('00500008-0004-4000-8000-000000000008', '00400004-0004-4000-8000-000000000004', 'warranty_claims', 'object', 'aftersales.warranty_claims', 'Dealer warranty claim submissions'),
('00500009-0004-4000-8000-000000000009', '00400004-0004-4000-8000-000000000004', 'recall_campaigns', 'object', 'aftersales.recall_campaigns', 'Safety and non-safety recall campaign records')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4c. DATA CONTRACT SCHEMA PROPERTIES
-- ============================================================================

INSERT INTO data_contract_schema_properties (id, object_id, name, logical_type, required, "unique", primary_key, partitioned, primary_key_position, partition_key_position, critical_data_element, transform_description) VALUES
-- vehicle_signals table
('00600001-0004-4000-8000-000000000001', '00500001-0004-4000-8000-000000000001', 'vin', 'string', true, false, false, false, -1, -1, true, 'Vehicle Identification Number (ISO 3779)'),
('00600002-0004-4000-8000-000000000002', '00500001-0004-4000-8000-000000000001', 'trip_id', 'string', true, false, true, false, 1, -1, true, 'Unique trip session identifier'),
('00600003-0004-4000-8000-000000000003', '00500001-0004-4000-8000-000000000001', 'signal_name', 'string', true, false, false, false, -1, -1, true, 'CAN signal name per DBC definition'),
('00600004-0004-4000-8000-000000000004', '00500001-0004-4000-8000-000000000001', 'signal_value', 'decimal', true, false, false, false, -1, -1, true, 'Decoded physical signal value'),
('00600005-0004-4000-8000-000000000005', '00500001-0004-4000-8000-000000000001', 'timestamp_utc', 'timestamp', true, false, false, true, -1, 1, true, 'Signal timestamp (UTC, millisecond precision)'),
('00600006-0004-4000-8000-000000000006', '00500001-0004-4000-8000-000000000001', 'ecu_id', 'string', true, false, false, false, -1, -1, false, 'Source ECU identifier'),

-- sensor_recordings table
('00600007-0004-4000-8000-000000000007', '00500004-0004-4000-8000-000000000004', 'recording_id', 'string', true, true, true, false, 1, -1, true, 'Unique sensor recording session ID'),
('00600008-0004-4000-8000-000000000008', '00500004-0004-4000-8000-000000000004', 'sensor_modality', 'string', true, false, false, false, -1, -1, true, 'camera, lidar, radar, ultrasonic'),
('00600009-0004-4000-8000-000000000009', '00500004-0004-4000-8000-000000000004', 'frame_count', 'integer', true, false, false, false, -1, -1, false, 'Total frames in recording'),
('0060000a-0004-4000-8000-000000000010', '00500004-0004-4000-8000-000000000004', 'storage_uri', 'string', true, false, false, false, -1, -1, false, 'Cloud storage path to raw recording'),
('0060000b-0004-4000-8000-000000000011', '00500004-0004-4000-8000-000000000004', 'recording_date', 'date', true, false, false, true, -1, 1, false, 'Recording capture date'),

-- ppap_submissions table
('0060000c-0004-4000-8000-000000000012', '00500006-0004-4000-8000-000000000006', 'ppap_id', 'string', true, true, true, false, 1, -1, true, 'Unique PPAP submission ID'),
('0060000d-0004-4000-8000-000000000013', '00500006-0004-4000-8000-000000000006', 'supplier_code', 'string', true, false, false, false, -1, -1, true, 'DUNS number or internal supplier code'),
('0060000e-0004-4000-8000-000000000014', '00500006-0004-4000-8000-000000000006', 'part_number', 'string', true, false, false, false, -1, -1, true, 'OEM part number'),
('0060000f-0004-4000-8000-000000000015', '00500006-0004-4000-8000-000000000006', 'ppap_level', 'integer', true, false, false, false, -1, -1, false, 'PPAP submission level (1-5 per AIAG)'),
('00600010-0004-4000-8000-000000000016', '00500006-0004-4000-8000-000000000006', 'disposition', 'string', true, false, false, false, -1, -1, true, 'approved, interim_approved, rejected'),

-- warranty_claims table
('00600011-0004-4000-8000-000000000017', '00500008-0004-4000-8000-000000000008', 'claim_id', 'string', true, true, true, false, 1, -1, true, 'Unique warranty claim number'),
('00600012-0004-4000-8000-000000000018', '00500008-0004-4000-8000-000000000008', 'vin', 'string', true, false, false, false, -1, -1, true, 'Vehicle Identification Number'),
('00600013-0004-4000-8000-000000000019', '00500008-0004-4000-8000-000000000008', 'failure_code', 'string', true, false, false, false, -1, -1, true, 'Standardized failure mode code'),
('00600014-0004-4000-8000-000000000020', '00500008-0004-4000-8000-000000000008', 'mileage_km', 'integer', true, false, false, false, -1, -1, false, 'Vehicle odometer at time of claim'),
('00600015-0004-4000-8000-000000000021', '00500008-0004-4000-8000-000000000008', 'claim_cost_usd', 'decimal', true, false, false, false, -1, -1, true, 'Total claim cost (parts + labor)')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5. DATA PRODUCTS
-- ============================================================================

INSERT INTO data_products (id, api_version, kind, status, name, version, domain, tenant, owner_team_id, max_level_inheritance, published, publication_scope, created_at, updated_at) VALUES
('00700001-0004-4000-8000-000000000001', 'v1.0.0', 'DataProduct', 'active', 'Connected Vehicle Analytics v1', '1.0.0', 'Connected Vehicles', 'auto-demo', '00100001-0004-4000-8000-000000000001', 99, true, 'org', NOW(), NOW()),
('00700002-0004-4000-8000-000000000002', 'v1.0.0', 'DataProduct', 'active', 'ADAS Training Data Pipeline v1', '1.0.0', 'Autonomous Driving', 'auto-demo', '00100002-0004-4000-8000-000000000002', 99, true, 'org', NOW(), NOW()),
('00700003-0004-4000-8000-000000000003', 'v1.0.0', 'DataProduct', 'active', 'Supplier Quality Scorecard v1', '1.0.0', 'Supply Chain & Procurement', 'auto-demo', '00100003-0004-4000-8000-000000000003', 99, true, 'org', NOW(), NOW()),
('00700004-0004-4000-8000-000000000004', 'v1.0.0', 'DataProduct', 'active', 'Warranty Analytics Platform v1', '1.0.0', 'After-Sales & Warranty', 'auto-demo', '00100001-0004-4000-8000-000000000001', 99, true, 'org', NOW(), NOW()),
('00700005-0004-4000-8000-000000000005', 'v1.0.0', 'DataProduct', 'active', 'Vehicle Configuration Intelligence v1', '1.0.0', 'Vehicle Engineering', 'auto-demo', '00100001-0004-4000-8000-000000000001', 99, true, 'org', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5b. DATA PRODUCT DESCRIPTIONS
-- ============================================================================

INSERT INTO data_product_descriptions (id, product_id, purpose, usage, limitations) VALUES
('00800001-0004-4000-8000-000000000001', '00700001-0004-4000-8000-000000000001', 'Provide fleet-wide vehicle health analytics, driving behavior insights, and OTA campaign performance tracking from telematics data.', 'Fleet operations dashboard, usage-based insurance risk scoring, predictive maintenance alerts, and OTA update success rate monitoring.', 'Telematics data depends on cellular connectivity; rural coverage gaps cause 4-12h upload delays. DTC interpretation varies across model years.'),
('00800002-0004-4000-8000-000000000002', '00700002-0004-4000-8000-000000000002', 'Curate, label, and serve petabyte-scale multi-modal sensor data for autonomous driving perception model training and validation.', 'Data selection for model training, corner-case scenario mining, simulation-in-the-loop validation, and ISO 21448 SOTIF evidence collection.', 'Annotation throughput ~500 frames/day per labeler. LiDAR-camera calibration drift requires re-calibration every 2 weeks. Night/rain scenarios under-represented (~8% of corpus).'),
('00800003-0004-4000-8000-000000000003', '00700003-0004-4000-8000-000000000003', 'Aggregate supplier quality metrics (PPM, PPAP status, 8D closure rate) into a unified scorecard for strategic sourcing decisions.', 'Monthly supplier business reviews, new program nomination decisions, and risk-based audit scheduling.', 'Sub-tier (Tier-2+) quality data limited to what Tier-1 discloses. PPM calculations exclude NTF returns. Small-volume suppliers (<1000 parts/month) have high statistical noise.'),
('00800004-0004-4000-8000-000000000004', '00700004-0004-4000-8000-000000000004', 'Detect warranty cost spikes, identify emerging field failure patterns, and optimize recall campaign scope using claims analytics and telematics correlation.', 'Early warning dashboard for quality engineers, cost-per-vehicle trending by model/plant/supplier, and recall scope analysis with VIN-level targeting.', 'Claims data lags 5-10 days. Goodwill and policy repairs excluded from base CPV. Cross-market comparisons require labor rate normalization.'),
('00800005-0004-4000-8000-000000000005', '00700005-0004-4000-8000-000000000005', 'Unified view of vehicle configurations (as-planned, as-built, as-maintained) with full BOM resolution and option compatibility rules.', 'Build-to-order feasibility checks, engineering change impact analysis, and aftersales parts catalog enrichment.', 'Legacy models (pre-2018) have incomplete as-built data. Option constraint rules are market-specific and maintained in separate PLM instances.')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5c. DATA PRODUCT OUTPUT PORTS
-- ============================================================================

INSERT INTO data_product_output_ports (id, product_id, name, version, description, port_type, status, contract_id, contains_pii, auto_approve, server) VALUES
('00900001-0004-4000-8000-000000000001', '00700001-0004-4000-8000-000000000001', 'vehicle_telemetry_stream', '1.0.0', 'Real-time fleet telemetry event stream', 'kafka', 'active', NULL, false, false, '{"host": "kafka.oem.com", "topic": "vehicle-telemetry-v1"}'),
('00900002-0004-4000-8000-000000000002', '00700001-0004-4000-8000-000000000001', 'fleet_health_dashboard', '1.0.0', 'Fleet health monitoring dashboard', 'dashboard', 'active', NULL, false, true, '{"location": "https://bi.oem.com/dashboards/fleet-health-v1"}'),
('00900003-0004-4000-8000-000000000003', '00700002-0004-4000-8000-000000000002', 'adas_training_dataset', '1.0.0', 'Curated and annotated sensor data for model training', 'table', 'active', NULL, false, false, '{"location": "s3://auto-lake/adas/training/v1", "format": "delta"}'),
('00900004-0004-4000-8000-000000000004', '00700003-0004-4000-8000-000000000003', 'supplier_scorecard_api', '1.0.0', 'Supplier quality scorecard REST API', 'api', 'active', NULL, false, false, '{"location": "https://api.oem.com/supply-chain/scorecard/v1"}'),
('00900005-0004-4000-8000-000000000005', '00700004-0004-4000-8000-000000000004', 'warranty_analytics_delta', '1.0.0', 'Warranty claims analytics table', 'table', 'active', NULL, true, false, '{"location": "s3://auto-lake/warranty/analytics/v1", "format": "delta"}'),
('00900006-0004-4000-8000-000000000006', '00700005-0004-4000-8000-000000000005', 'vehicle_config_api', '1.0.0', 'Vehicle configuration lookup API', 'api', 'active', NULL, false, true, '{"location": "https://api.oem.com/vehicle/config/v1"}')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5d. DATA PRODUCT INPUT PORTS
-- ============================================================================

INSERT INTO data_product_input_ports (id, product_id, name, version, contract_id) VALUES
('00a00001-0004-4000-8000-000000000001', '00700001-0004-4000-8000-000000000001', 'CAN Bus Signals', '1.0.0', 'vehicle-telematics-contract-v1'),
('00a00002-0004-4000-8000-000000000002', '00700001-0004-4000-8000-000000000001', 'DTC Events', '1.0.0', 'vehicle-telematics-contract-v1'),
('00a00003-0004-4000-8000-000000000003', '00700002-0004-4000-8000-000000000002', 'Sensor Recordings', '1.0.0', 'adas-sensor-data-contract-v2'),
('00a00004-0004-4000-8000-000000000004', '00700002-0004-4000-8000-000000000002', 'Ground Truth Labels', '1.0.0', 'adas-sensor-data-contract-v2'),
('00a00005-0004-4000-8000-000000000005', '00700003-0004-4000-8000-000000000003', 'PPAP Records', '1.0.0', 'supplier-quality-contract-v1'),
('00a00006-0004-4000-8000-000000000006', '00700003-0004-4000-8000-000000000003', 'Incoming Inspections', '1.0.0', 'supplier-quality-contract-v1'),
('00a00007-0004-4000-8000-000000000007', '00700004-0004-4000-8000-000000000004', 'Warranty Claims', '1.0.0', 'warranty-claims-contract-v1'),
('00a00008-0004-4000-8000-000000000008', '00700004-0004-4000-8000-000000000004', 'Recall Campaigns', '1.0.0', 'warranty-claims-contract-v1'),
('00a00009-0004-4000-8000-000000000009', '00700005-0004-4000-8000-000000000005', 'Vehicle BOM', '1.0.0', 'vehicle-config-bom-contract-v1'),
('00a0000a-0004-4000-8000-000000000010', '00700005-0004-4000-8000-000000000005', 'As-Built Records', '1.0.0', 'vehicle-config-bom-contract-v1')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5e. DATA PRODUCT SUPPORT CHANNELS
-- ============================================================================

INSERT INTO data_product_support_channels (id, product_id, channel, url, tool, scope, description) VALUES
('00b00001-0004-4000-8000-000000000001', '00700001-0004-4000-8000-000000000001', 'cv-platform-support', 'https://teams.com/channels/cv-data-ops', 'teams', 'interactive', 'Connected vehicle data pipeline support'),
('00b00002-0004-4000-8000-000000000002', '00700002-0004-4000-8000-000000000002', 'adas-data-ops', 'https://slack.com/channels/adas-data-ops', 'slack', 'issues', 'ADAS data pipeline and annotation issues'),
('00b00003-0004-4000-8000-000000000003', '00700003-0004-4000-8000-000000000003', 'supplier-quality-support', 'https://jira.oem.com/projects/SQE', 'ticket', 'issues', 'Supplier quality data and scorecard issues'),
('00b00004-0004-4000-8000-000000000004', '00700004-0004-4000-8000-000000000004', 'warranty-analytics-support', 'https://teams.com/channels/warranty-analytics', 'teams', 'interactive', NULL),
('00b00005-0004-4000-8000-000000000005', '00700005-0004-4000-8000-000000000005', 'vehicle-config-support', 'https://slack.com/channels/vehicle-config', 'slack', 'announcements', 'BOM and configuration data updates')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5f. DATA PRODUCT TEAMS
-- ============================================================================

INSERT INTO data_product_teams (id, product_id, name, description) VALUES
('00c00001-0004-4000-8000-000000000001', '00700001-0004-4000-8000-000000000001', 'Connected Vehicle Platform', NULL),
('00c00002-0004-4000-8000-000000000002', '00700002-0004-4000-8000-000000000002', 'ADAS Data Engineering', NULL),
('00c00003-0004-4000-8000-000000000003', '00700003-0004-4000-8000-000000000003', 'Supplier Quality Engineering', NULL),
('00c00004-0004-4000-8000-000000000004', '00700004-0004-4000-8000-000000000004', 'Warranty Analytics', NULL),
('00c00005-0004-4000-8000-000000000005', '00700005-0004-4000-8000-000000000005', 'Vehicle Configuration', NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5g. DATA PRODUCT TEAM MEMBERS
-- ============================================================================

INSERT INTO data_product_team_members (id, team_id, username, name, role) VALUES
('00d00001-0004-4000-8000-000000000001', '00c00001-0004-4000-8000-000000000001', 'cv.architect@oem.com', 'Stefan Telematik', 'owner'),
('00d00002-0004-4000-8000-000000000002', '00c00001-0004-4000-8000-000000000001', 'cv.dataeng@oem.com', 'Yuki Streaming', 'contributor'),
('00d00003-0004-4000-8000-000000000003', '00c00002-0004-4000-8000-000000000002', 'adas.lead@oem.com', 'Priya Perception', 'owner'),
('00d00004-0004-4000-8000-000000000004', '00c00003-0004-4000-8000-000000000003', 'sqe.manager@oem.com', 'Carlos Calidad', 'owner'),
('00d00005-0004-4000-8000-000000000005', '00c00004-0004-4000-8000-000000000004', 'warranty.analyst@oem.com', 'Ingrid Garantie', 'owner'),
('00d00006-0004-4000-8000-000000000006', '00c00005-0004-4000-8000-000000000005', 'config.engineer@oem.com', 'Takeshi Variant', 'owner')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 6. COMPLIANCE POLICIES (AUTO-specific)
-- ============================================================================

INSERT INTO compliance_policies (id, name, description, failure_message, rule, category, severity, is_active, created_at, updated_at) VALUES
('01100001-0004-4000-8000-000000000001', 'UNECE R155 Cybersecurity', 'Verify vehicle data pipelines meet UNECE WP.29 R155 cybersecurity management system requirements',
'Vehicle data pipeline lacks cybersecurity controls. UNECE R155 requires documented threat analysis and risk assessment (TARA) for all vehicle data interfaces.',
'MATCH (d:DataPipeline) WHERE d.domain IN [''Connected Vehicles'', ''Autonomous Driving''] ASSERT d.has_tara = true AND d.encryption_in_transit = true', 'security', 'critical', true, NOW(), NOW()),

('01100002-0004-4000-8000-000000000002', 'IATF 16949 PPAP Compliance', 'Ensure all production parts have approved PPAP submissions at the required level',
'Part is in production without approved PPAP. IATF 16949 Section 8.3.4.4 requires PPAP approval before production shipment. Interim approval requires documented containment plan.',
'MATCH (p:Part) WHERE p.production_status = ''active'' ASSERT p.ppap_status IN [''approved'', ''interim_approved'']', 'quality', 'critical', true, NOW(), NOW()),

('01100003-0004-4000-8000-000000000003', 'GDPR Vehicle Data Privacy', 'Verify that vehicle telematics data containing PII is processed in compliance with GDPR/CCPA',
'Telematics dataset contains PII without proper consent tracking or anonymization. Vehicle location traces, driving behavior, and diagnostic data linked to VIN require explicit consent or pseudonymization.',
'MATCH (d:Dataset) WHERE d.contains_vehicle_pii = true ASSERT d.consent_mechanism IS NOT NULL AND d.retention_days <= 730', 'governance', 'high', true, NOW(), NOW()),

('01100004-0004-4000-8000-000000000004', 'ISO 26262 Data Integrity', 'Ensure ADAS training and validation datasets meet ISO 26262 functional safety data integrity requirements',
'ADAS dataset lacks functional safety traceability. ISO 26262 Part 8 requires documented data management plans, integrity checks, and traceability for safety-relevant data used in ASIL-rated systems.',
'MATCH (d:Dataset) WHERE d.domain = ''Autonomous Driving'' AND d.safety_relevant = true ASSERT d.asil_rating IS NOT NULL AND d.integrity_checksum IS NOT NULL', 'governance', 'critical', true, NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 7. NOTIFICATIONS (AUTO-specific)
-- ============================================================================

INSERT INTO notifications (id, type, title, subtitle, description, created_at, read, can_delete, recipient) VALUES
('01000001-0004-4000-8000-000000000001', 'error', 'OTA Campaign Failure Spike', 'Model X 2025 - ECU FW 4.2.1', 'OTA update campaign for infotainment ECU firmware 4.2.1 has 23% failure rate across Model X fleet (expected <2%). Root cause: insufficient flash memory on early production units. Campaign paused pending engineering review.', NOW() - INTERVAL '3 hours', false, false, NULL),
('01000002-0004-4000-8000-000000000002', 'warning', 'Supplier PPAP Overdue', '4 Critical Path Suppliers', 'PPAP submissions overdue for 4 Tier-1 suppliers on the Model Z launch program. Affected parts: front camera module, battery management ECU, steering rack sensor, and brake-by-wire actuator. SOP at risk if not resolved within 30 days.', NOW() - INTERVAL '1 day', false, true, NULL),
('01000003-0004-4000-8000-000000000003', 'success', 'ADAS Validation Milestone', 'Level 3 Highway Pilot', 'Perception model v7.2 achieved 99.97% object detection recall on highway validation dataset (12M frames). Meets ISO 21448 SOTIF acceptance criteria for Level 3 highway pilot feature release.', NOW() - INTERVAL '2 days', true, true, NULL),
('01000004-0004-4000-8000-000000000004', 'info', 'Warranty Trend Alert', 'Transmission Control Module', 'Early warning system detected 3.2x warranty claim spike for transmission control module (TCM) failure code P0700 across Model Y 2024 vehicles manufactured at Plant B during weeks 12-18. 847 vehicles potentially affected.', NOW() - INTERVAL '4 days', false, true, NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 8. METADATA (Notes, Links)
-- ============================================================================

-- Rich Text Notes (type=016)
INSERT INTO rich_text_metadata (id, entity_id, entity_type, title, short_description, content_markdown, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01600001-0004-4000-8000-000000000001', '00700001-0004-4000-8000-000000000001', 'data_product', 'Overview', 'Fleet-wide vehicle health and driving analytics.', E'# Connected Vehicle Analytics v1\n\nFleet-wide vehicle health analytics, driving behavior insights, and OTA campaign\nperformance tracking from telematics data across the global connected fleet.\n\n## Data Pipeline\n- CAN bus signal ingestion via MQTT/Kafka (100K+ vehicles)\n- DTC event processing with freeze-frame correlation\n- Driving behavior scoring using accelerometer data\n- OTA update status tracking and rollback monitoring\n\n## Key Outputs\n- Predictive maintenance alerts (battery, brakes, HVAC)\n- Usage-based insurance risk scores\n- Fleet-wide DTC trend analysis\n- OTA campaign success rate monitoring', false, 50, true, 'system@demo', NOW(), NOW()),
('01600002-0004-4000-8000-000000000002', '00700002-0004-4000-8000-000000000002', 'data_product', 'Overview', 'Petabyte-scale sensor data for AD model training.', E'# ADAS Training Data Pipeline v1\n\nCurates, labels, and serves petabyte-scale multi-modal sensor data for autonomous driving\nperception model training and validation per ISO 21448 (SOTIF).\n\n## Data Processing\n- Camera (30fps), LiDAR (10Hz), radar (20Hz) synchronization\n- Automated PII anonymization (faces, license plates)\n- Active learning-based scenario mining for corner cases\n- Ground truth annotation pipeline (~500 frames/day/labeler)\n\n## Validation Support\n- Scenario-based testing per ISO 21448 SOTIF\n- ODD coverage tracking and gap analysis\n- Simulation replay with recorded sensor data\n- Regression testing across model versions', false, 50, true, 'system@demo', NOW(), NOW()),
('01600003-0004-4000-8000-000000000003', '00700003-0004-4000-8000-000000000003', 'data_product', 'Overview', 'Unified supplier quality metrics and scorecards.', E'# Supplier Quality Scorecard v1\n\nAggregated supplier quality metrics combining PPM rates, PPAP status, 8D closure\nperformance, and incoming inspection results into a unified scorecard.\n\n## Scorecard Dimensions\n- Quality: PPM (parts per million defective)\n- Delivery: On-time delivery rate, premium freight incidents\n- PPAP: Submission timeliness, first-pass approval rate\n- Responsiveness: 8D closure time, containment effectiveness\n\n## Business Integration\n- Monthly supplier business reviews\n- New program nomination and award decisions\n- Risk-based audit scheduling (VDA 6.3)\n- Supplier development program prioritization', false, 50, true, 'system@demo', NOW(), NOW()),
('01600004-0004-4000-8000-000000000004', '00700004-0004-4000-8000-000000000004', 'data_product', 'Overview', 'Warranty cost analytics and field failure detection.', E'# Warranty Analytics Platform v1\n\nEarly warning analytics for detecting warranty cost spikes, identifying emerging field\nfailure patterns, and optimizing recall campaign scope.\n\n## Analytics Capabilities\n- Cost-per-vehicle (CPV) trending by model/plant/supplier\n- Field failure pattern detection using NLP on technician notes\n- Telematics-warranty correlation for proactive identification\n- Recall scope optimization with VIN-level targeting\n\n## Early Warning System\n- Statistical process control on claim rates by failure code\n- Automatic alerts when CPV exceeds threshold by 2 sigma\n- Comparative analysis across manufacturing plants\n- 12-month rolling trend forecasting', false, 50, true, 'system@demo', NOW(), NOW()),
('01600005-0004-4000-8000-000000000005', '00700005-0004-4000-8000-000000000005', 'data_product', 'Overview', 'Unified vehicle configuration and BOM intelligence.', E'# Vehicle Configuration Intelligence v1\n\nUnified view of vehicle configurations (as-planned, as-built, as-maintained) with full\nBOM resolution and option compatibility rules across all model lines.\n\n## Configuration Views\n- As-Planned: 150% BOM with option constraint rules\n- As-Built: Actual vehicle build record from MES\n- As-Maintained: Service history and replaced parts\n\n## Use Cases\n- Build-to-order feasibility checking\n- Engineering change impact analysis\n- Aftersales parts catalog enrichment\n- Variant cost analysis and complexity reduction', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;

-- Link Metadata (type=017)
INSERT INTO link_metadata (id, entity_id, entity_type, title, short_description, url, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01700001-0004-4000-8000-000000000001', '00700001-0004-4000-8000-000000000001', 'data_product', 'Fleet Health Dashboard', 'Real-time fleet monitoring and alerts.', 'https://bi.oem.com/dashboards/fleet-health-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700002-0004-4000-8000-000000000002', '00700001-0004-4000-8000-000000000001', 'data_product', 'Runbook', 'Telematics pipeline operations.', 'https://runbooks.oem.com/cv/telematics-pipeline-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700003-0004-4000-8000-000000000003', '00700002-0004-4000-8000-000000000002', 'data_product', 'Annotation Guidelines', 'Ground truth labeling standards.', 'https://docs.oem.com/adas/annotation-guidelines-v3', false, 50, true, 'system@demo', NOW(), NOW()),
('01700004-0004-4000-8000-000000000004', '00700002-0004-4000-8000-000000000002', 'data_product', 'SOTIF Evidence Tracker', 'ISO 21448 validation coverage.', 'https://wiki.oem.com/adas/sotif-evidence-tracker', false, 50, true, 'system@demo', NOW(), NOW()),
('01700005-0004-4000-8000-000000000005', '00700003-0004-4000-8000-000000000003', 'data_product', 'Supplier Portal', 'Supplier self-service scorecard access.', 'https://suppliers.oem.com/quality/scorecard', false, 50, true, 'system@demo', NOW(), NOW()),
('01700006-0004-4000-8000-000000000006', '00700003-0004-4000-8000-000000000003', 'data_product', 'VDA 6.3 Audit Schedule', 'Upcoming supplier audit plan.', 'https://wiki.oem.com/supply-chain/vda-audit-schedule', false, 50, true, 'system@demo', NOW(), NOW()),
('01700007-0004-4000-8000-000000000007', '00700004-0004-4000-8000-000000000004', 'data_product', 'Early Warning Dashboard', 'Warranty trend alerts and CPV tracking.', 'https://bi.oem.com/dashboards/warranty-early-warning', false, 50, true, 'system@demo', NOW(), NOW()),
('01700008-0004-4000-8000-000000000008', '00700004-0004-4000-8000-000000000004', 'data_product', 'Recall Scope Analyzer', 'VIN-level recall targeting tool.', 'https://tools.oem.com/warranty/recall-scope-analyzer', false, 50, true, 'system@demo', NOW(), NOW()),
('01700009-0004-4000-8000-000000000009', '00700005-0004-4000-8000-000000000005', 'data_product', 'BOM Explorer', 'Interactive BOM navigation and search.', 'https://tools.oem.com/engineering/bom-explorer', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000a-0004-4000-8000-000000000010', '00700005-0004-4000-8000-000000000005', 'data_product', 'ECO Impact Dashboard', 'Engineering change impact visualization.', 'https://bi.oem.com/dashboards/eco-impact-analysis', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


COMMIT;

-- ============================================================================
-- End of Automotive Industry Demo Data
-- ============================================================================
