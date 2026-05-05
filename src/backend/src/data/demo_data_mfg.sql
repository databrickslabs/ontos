-- ============================================================================
-- Industry Demo Data: Manufacturing (MFG)
-- ============================================================================
-- Additive overlay loaded via: POST /api/settings/demo-data/load?industry=mfg
--
-- Adds manufacturing-specific data domains, teams, contracts, products, and
-- compliance policies covering production, quality, maintenance, and safety.
--
-- Dataset identifier: 0003 (second UUID group)
-- UUID Format: {type:3}{seq:5}-0003-4000-8000-00000000000N
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. DATA DOMAINS (MFG-specific, children of Core)
-- ============================================================================

INSERT INTO data_domains (id, name, description, parent_id, created_by, created_at, updated_at) VALUES
('00000001-0003-4000-8000-000000000001', 'Production', 'Manufacturing execution, work orders, and production line data.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000002-0003-4000-8000-000000000002', 'Quality', 'Quality control, inspections, non-conformance reports, and CAPA.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000003-0003-4000-8000-000000000003', 'Maintenance', 'Equipment maintenance, predictive analytics, and asset lifecycle.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000004-0003-4000-8000-000000000004', 'Safety & EHS', 'Environmental, health, safety incidents, and regulatory compliance.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000005-0003-4000-8000-000000000005', 'Process Engineering', 'Process parameters, SPC data, and recipe management.', '00000001-0003-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000006-0003-4000-8000-000000000006', 'Warehouse & Logistics', 'Warehouse management, material handling, and shipment tracking.', '00000006-0000-4000-8000-000000000006', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2. TEAMS
-- ============================================================================

INSERT INTO teams (id, name, title, description, domain_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00100001-0003-4000-8000-000000000001', 'production-engineering', 'Production Engineering Team', 'MES integration, production optimization, and OEE improvement', '00000001-0003-4000-8000-000000000001', '{"slack_channel": "https://company.slack.com/channels/prod-eng", "lead": "plant.manager@factory.com"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100002-0003-4000-8000-000000000002', 'quality-assurance', 'Quality Assurance Team', 'Incoming/in-process/final inspection, SPC analysis, and CAPA management', '00000002-0003-4000-8000-000000000002', '{"slack_channel": "https://company.slack.com/channels/qa-team", "tools": ["Minitab", "JMP", "InfinityQS"]}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100003-0003-4000-8000-000000000003', 'predictive-maintenance', 'Predictive Maintenance Team', 'Vibration analysis, thermal imaging, and ML-based failure prediction', '00000003-0003-4000-8000-000000000003', '{"slack_channel": "https://company.slack.com/channels/pred-maint", "responsibilities": ["Condition Monitoring", "CMMS", "Spare Parts Optimization"]}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2b. TEAM MEMBERS
-- ============================================================================

INSERT INTO team_members (id, team_id, member_type, member_identifier, app_role_override, added_by, created_at, updated_at) VALUES
('00200001-0003-4000-8000-000000000001', '00100001-0003-4000-8000-000000000001', 'user', 'plant.manager@factory.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200002-0003-4000-8000-000000000002', '00100001-0003-4000-8000-000000000001', 'group', 'production-engineers', NULL, 'system@demo', NOW(), NOW()),
('00200003-0003-4000-8000-000000000003', '00100002-0003-4000-8000-000000000002', 'user', 'qa.director@factory.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200004-0003-4000-8000-000000000004', '00100002-0003-4000-8000-000000000002', 'group', 'quality-inspectors', NULL, 'system@demo', NOW(), NOW()),
('00200005-0003-4000-8000-000000000005', '00100003-0003-4000-8000-000000000003', 'user', 'reliability.eng@factory.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200006-0003-4000-8000-000000000006', '00100003-0003-4000-8000-000000000003', 'group', 'maintenance-technicians', NULL, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3. PROJECTS
-- ============================================================================

INSERT INTO projects (id, name, title, description, project_type, owner_team_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00300001-0003-4000-8000-000000000001', 'smart-factory', 'Smart Factory Initiative', 'Industry 4.0 digital twin, real-time OEE tracking, and AI-driven production scheduling', 'TEAM', '00100001-0003-4000-8000-000000000001', '{"budget": "$1.8M", "timeline": "15 months", "technologies": ["Azure IoT", "Digital Twin", "Edge Computing"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300002-0003-4000-8000-000000000002', 'zero-defects', 'Zero Defects Program', 'AI-powered visual inspection, real-time SPC, and automated root cause analysis', 'TEAM', '00100002-0003-4000-8000-000000000002', '{"budget": "$900K", "timeline": "8 months", "compliance": ["ISO 9001", "IATF 16949"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300003-0003-4000-8000-000000000003', 'predictive-maintenance-rollout', 'Predictive Maintenance Rollout', 'Deploy vibration and thermal sensors across critical assets with ML failure prediction', 'TEAM', '00100003-0003-4000-8000-000000000003', '{"budget": "$650K", "timeline": "6 months", "target_uptime": "99.2%", "priority": "medium"}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3b. PROJECT-TEAM ASSOCIATIONS
-- ============================================================================

INSERT INTO project_teams (project_id, team_id, assigned_by, assigned_at) VALUES
('00300001-0003-4000-8000-000000000001', '00100001-0003-4000-8000-000000000001', 'system@demo', NOW()),
('00300001-0003-4000-8000-000000000001', '00100003-0003-4000-8000-000000000003', 'system@demo', NOW()),
('00300002-0003-4000-8000-000000000002', '00100002-0003-4000-8000-000000000002', 'system@demo', NOW()),
('00300002-0003-4000-8000-000000000002', '00100001-0003-4000-8000-000000000001', 'system@demo', NOW()),
('00300003-0003-4000-8000-000000000003', '00100003-0003-4000-8000-000000000003', 'system@demo', NOW()),
('00300003-0003-4000-8000-000000000003', '00100001-0003-4000-8000-000000000001', 'system@demo', NOW())

ON CONFLICT (project_id, team_id) DO NOTHING;


-- ============================================================================
-- 4. DATA CONTRACTS
-- ============================================================================

INSERT INTO data_contracts (id, name, kind, api_version, version, status, published, owner_team_id, domain_id, description_purpose, description_usage, description_limitations, publication_scope, created_by, updated_by, created_at, updated_at) VALUES
('00400001-0003-4000-8000-000000000001', 'Production Line Data Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100001-0003-4000-8000-000000000001', '00000001-0003-4000-8000-000000000001', 'Real-time production line data from MES including work orders, cycle times, and machine states', 'OEE calculation, production scheduling optimization, and bottleneck analysis', 'PLC data sampled at 1s intervals; MES timestamps may drift ±500ms; downtime codes require operator confirmation', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400002-0003-4000-8000-000000000002', 'Quality Inspection Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100002-0003-4000-8000-000000000002', '00000002-0003-4000-8000-000000000002', 'In-process and final inspection measurements, defect classifications, and SPC control chart data', 'Real-time quality dashboards, Cpk/Ppk tracking, and automated non-conformance routing', 'CMM measurement uncertainty ±0.005mm; visual inspection results are categorical; SPC rules per AIAG manual', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400003-0003-4000-8000-000000000003', 'Equipment Health Contract', 'DataContract', 'v3.1.0', '2.0.0', 'active', true, '00100003-0003-4000-8000-000000000003', '00000003-0003-4000-8000-000000000003', 'Vibration, temperature, pressure, and current sensor data from critical production equipment', 'Predictive maintenance models, remaining useful life estimation, and maintenance work order prioritization', 'Sensor data sampled at 10Hz for vibration, 1Hz for temperature; edge gateway buffers up to 1h during connectivity loss', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400004-0003-4000-8000-000000000004', 'EHS Incident Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100002-0003-4000-8000-000000000002', '00000004-0003-4000-8000-000000000004', 'Safety incidents, near-misses, environmental monitoring, and OSHA recordable events', 'Safety trend analysis, leading indicator dashboards, and regulatory reporting (OSHA 300 log)', 'Incident severity classification per ANSI Z16.1; near-miss reporting is voluntary and likely under-reported', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

('00400005-0003-4000-8000-000000000005', 'Bill of Materials Contract', 'DataContract', 'v3.1.0', '1.0.0', 'draft', false, '00100001-0003-4000-8000-000000000001', '00000001-0003-4000-8000-000000000001', 'Engineering and manufacturing BOMs with revision history and where-used relationships', 'Cost roll-up, material requirements planning, and engineering change impact analysis', 'BOM effectivity dates may overlap during ECN transitions; phantom assemblies excluded from cost roll-up', 'none', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4b. DATA CONTRACT SCHEMA OBJECTS
-- ============================================================================

INSERT INTO data_contract_schema_objects (id, contract_id, name, logical_type, physical_name, description) VALUES
-- Production Line
('00500001-0003-4000-8000-000000000001', '00400001-0003-4000-8000-000000000001', 'work_orders', 'object', 'mes.work_orders', 'Production work orders and batch records'),
('00500002-0003-4000-8000-000000000002', '00400001-0003-4000-8000-000000000001', 'machine_states', 'object', 'mes.machine_state_log', 'Machine state transitions (running, idle, down, changeover)'),
('00500003-0003-4000-8000-000000000003', '00400001-0003-4000-8000-000000000001', 'cycle_times', 'object', 'mes.cycle_time_actuals', 'Actual vs. standard cycle time measurements'),

-- Quality Inspection
('00500004-0003-4000-8000-000000000004', '00400002-0003-4000-8000-000000000002', 'inspections', 'object', 'quality.inspection_results', 'Dimensional and visual inspection measurements'),
('00500005-0003-4000-8000-000000000005', '00400002-0003-4000-8000-000000000002', 'defects', 'object', 'quality.defect_log', 'Defect classifications and dispositions'),
('00500006-0003-4000-8000-000000000006', '00400002-0003-4000-8000-000000000002', 'spc_data', 'object', 'quality.spc_measurements', 'Statistical process control data points'),

-- Equipment Health
('00500007-0003-4000-8000-000000000007', '00400003-0003-4000-8000-000000000003', 'sensor_readings', 'object', 'maintenance.sensor_timeseries', 'Equipment sensor time-series data'),
('00500008-0003-4000-8000-000000000008', '00400003-0003-4000-8000-000000000003', 'maintenance_records', 'object', 'maintenance.work_orders', 'Maintenance work orders and completion records'),

-- EHS
('00500009-0003-4000-8000-000000000009', '00400004-0003-4000-8000-000000000004', 'incidents', 'object', 'ehs.safety_incidents', 'Safety incidents and near-miss reports'),
('0050000a-0003-4000-8000-000000000010', '00400004-0003-4000-8000-000000000004', 'environmental_readings', 'object', 'ehs.environmental_monitoring', 'Emissions, noise, and waste monitoring')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4c. DATA CONTRACT SCHEMA PROPERTIES
-- ============================================================================

INSERT INTO data_contract_schema_properties (id, object_id, name, logical_type, required, "unique", primary_key, partitioned, primary_key_position, partition_key_position, critical_data_element, transform_description) VALUES
-- work_orders table
('00600001-0003-4000-8000-000000000001', '00500001-0003-4000-8000-000000000001', 'work_order_id', 'string', true, true, true, false, 1, -1, true, 'MES work order number'),
('00600002-0003-4000-8000-000000000002', '00500001-0003-4000-8000-000000000001', 'part_number', 'string', true, false, false, false, -1, -1, true, 'Manufactured part number'),
('00600003-0003-4000-8000-000000000003', '00500001-0003-4000-8000-000000000001', 'quantity_planned', 'integer', true, false, false, false, -1, -1, false, 'Planned production quantity'),
('00600004-0003-4000-8000-000000000004', '00500001-0003-4000-8000-000000000001', 'quantity_produced', 'integer', true, false, false, false, -1, -1, true, 'Actual good parts produced'),
('00600005-0003-4000-8000-000000000005', '00500001-0003-4000-8000-000000000001', 'scrap_count', 'integer', true, false, false, false, -1, -1, true, 'Number of scrapped parts'),
('00600006-0003-4000-8000-000000000006', '00500001-0003-4000-8000-000000000001', 'start_time', 'timestamp', true, false, false, true, -1, 1, false, 'Work order start timestamp'),

-- inspections table
('00600007-0003-4000-8000-000000000007', '00500004-0003-4000-8000-000000000004', 'inspection_id', 'string', true, true, true, false, 1, -1, true, 'Unique inspection record ID'),
('00600008-0003-4000-8000-000000000008', '00500004-0003-4000-8000-000000000004', 'part_number', 'string', true, false, false, false, -1, -1, true, 'Inspected part number'),
('00600009-0003-4000-8000-000000000009', '00500004-0003-4000-8000-000000000004', 'characteristic', 'string', true, false, false, false, -1, -1, false, 'Measured characteristic name'),
('0060000a-0003-4000-8000-000000000010', '00500004-0003-4000-8000-000000000004', 'measured_value', 'decimal', true, false, false, false, -1, -1, true, 'Actual measured value'),
('0060000b-0003-4000-8000-000000000011', '00500004-0003-4000-8000-000000000004', 'upper_spec', 'decimal', true, false, false, false, -1, -1, false, 'Upper specification limit'),
('0060000c-0003-4000-8000-000000000012', '00500004-0003-4000-8000-000000000004', 'lower_spec', 'decimal', true, false, false, false, -1, -1, false, 'Lower specification limit'),
('0060000d-0003-4000-8000-000000000013', '00500004-0003-4000-8000-000000000004', 'disposition', 'string', true, false, false, false, -1, -1, true, 'accept, reject, rework, use_as_is'),

-- sensor_readings table
('0060000e-0003-4000-8000-000000000014', '00500007-0003-4000-8000-000000000007', 'asset_id', 'string', true, false, false, false, -1, -1, true, 'Equipment asset tag'),
('0060000f-0003-4000-8000-000000000015', '00500007-0003-4000-8000-000000000007', 'sensor_type', 'string', true, false, false, false, -1, -1, false, 'vibration, temperature, pressure, current'),
('00600010-0003-4000-8000-000000000016', '00500007-0003-4000-8000-000000000007', 'reading_value', 'decimal', true, false, false, false, -1, -1, true, 'Sensor reading value in SI units'),
('00600011-0003-4000-8000-000000000017', '00500007-0003-4000-8000-000000000007', 'reading_ts', 'timestamp', true, false, false, true, -1, 1, false, 'Reading timestamp (UTC)'),
('00600012-0003-4000-8000-000000000018', '00500007-0003-4000-8000-000000000007', 'health_score', 'decimal', false, false, false, false, -1, -1, true, 'ML-derived equipment health score (0-100)')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5. DATA PRODUCTS
-- ============================================================================

INSERT INTO data_products (id, api_version, kind, status, name, version, domain, tenant, owner_team_id, max_level_inheritance, published, publication_scope, created_at, updated_at) VALUES
('00700001-0003-4000-8000-000000000001', 'v1.0.0', 'DataProduct', 'active', 'Production KPI Dashboard v1', '1.0.0', 'Production', 'mfg-demo', '00100001-0003-4000-8000-000000000001', 99, true, 'org', NOW(), NOW()),
('00700002-0003-4000-8000-000000000002', 'v1.0.0', 'DataProduct', 'active', 'Quality Analytics Platform v1', '1.0.0', 'Quality', 'mfg-demo', '00100002-0003-4000-8000-000000000002', 99, true, 'org', NOW(), NOW()),
('00700003-0003-4000-8000-000000000003', 'v1.0.0', 'DataProduct', 'active', 'Predictive Maintenance v1', '1.0.0', 'Maintenance', 'mfg-demo', '00100003-0003-4000-8000-000000000003', 99, true, 'org', NOW(), NOW()),
('00700004-0003-4000-8000-000000000004', 'v1.0.0', 'DataProduct', 'active', 'Supply Chain Visibility v1', '1.0.0', 'Supply Chain', 'mfg-demo', '00100001-0003-4000-8000-000000000001', 99, true, 'org', NOW(), NOW()),
('00700005-0003-4000-8000-000000000005', 'v1.0.0', 'DataProduct', 'active', 'EHS Safety Analytics v1', '1.0.0', 'Safety & EHS', 'mfg-demo', '00100002-0003-4000-8000-000000000002', 99, true, 'org', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5b. DATA PRODUCT DESCRIPTIONS
-- ============================================================================

INSERT INTO data_product_descriptions (id, product_id, purpose, usage, limitations) VALUES
('00800001-0003-4000-8000-000000000001', '00700001-0003-4000-8000-000000000001', 'Provide real-time OEE, throughput, cycle time, and downtime KPIs across all production lines and shifts.', 'Shop floor TV dashboards, shift handoff reports, and plant manager weekly reviews. Drill-down to line, station, and operator level.', 'OEE calculation excludes planned maintenance windows. Short stops (<2 min) may be under-reported on legacy PLCs.'),
('00800002-0003-4000-8000-000000000002', '00700002-0003-4000-8000-000000000002', 'Provide real-time SPC charts, Cpk trends, Pareto analysis of defect types, and automated CAPA routing.', 'Quality engineering dashboards, customer audit packages, and supplier quality scorecards. Integrates with QMS for NCR workflow.', 'CMM measurement data has 15-minute batch upload delay. Vision system defect images retained 90 days only.'),
('00800003-0003-4000-8000-000000000003', '00700003-0003-4000-8000-000000000003', 'Predict equipment failures 7-30 days ahead using vibration analysis, thermal trending, and ML models trained on historical CMMS data.', 'Maintenance planning optimization, spare parts pre-staging, and production schedule de-risking. API integration with SAP PM.', 'Model accuracy ~87% for bearing failures, ~72% for electrical faults. Requires minimum 30 days of baseline sensor data per asset.'),
('00800004-0003-4000-8000-000000000004', '00700004-0003-4000-8000-000000000004', 'End-to-end supply chain visibility from raw material receipt through finished goods shipment with real-time WIP tracking.', 'Material shortage alerts, supplier on-time delivery tracking, and finished goods inventory optimization.', 'EDI data from suppliers has 4-hour lag. Container tracking updates depend on port infrastructure availability.'),
('00800005-0003-4000-8000-000000000005', '00700005-0003-4000-8000-000000000005', 'Safety leading and lagging indicator analytics including near-miss trends, TRIR, DART rate, and hazard heat maps.', 'Monthly safety committee reviews, OSHA 300 log automation, and contractor safety qualification tracking.', 'Near-miss data is self-reported and subject to reporting bias. Environmental sensor data gaps during calibration windows.')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5c. DATA PRODUCT OUTPUT PORTS
-- ============================================================================

INSERT INTO data_product_output_ports (id, product_id, name, version, description, port_type, status, contract_id, contains_pii, auto_approve, server) VALUES
('00900001-0003-4000-8000-000000000001', '00700001-0003-4000-8000-000000000001', 'production_kpi_stream', '1.0.0', 'Real-time OEE and throughput metrics', 'kafka', 'active', NULL, false, true, '{"host": "kafka.factory.com", "topic": "production-kpis-v1"}'),
('00900002-0003-4000-8000-000000000002', '00700001-0003-4000-8000-000000000001', 'production_kpi_dashboard', '1.0.0', 'Shop floor dashboard connection', 'dashboard', 'active', NULL, false, true, '{"location": "https://bi.factory.com/dashboards/oee-v1"}'),
('00900003-0003-4000-8000-000000000003', '00700002-0003-4000-8000-000000000002', 'quality_analytics_delta', '1.0.0', 'Inspection and SPC data lake table', 'table', 'active', NULL, false, false, '{"location": "s3://mfg-lake/quality/analytics/v1", "format": "delta"}'),
('00900004-0003-4000-8000-000000000004', '00700003-0003-4000-8000-000000000003', 'maintenance_predictions_api', '1.0.0', 'Equipment failure prediction API for CMMS', 'api', 'active', NULL, false, false, '{"location": "https://api.factory.com/maintenance/predict/v1"}'),
('00900005-0003-4000-8000-000000000005', '00700004-0003-4000-8000-000000000004', 'supply_chain_visibility_table', '1.0.0', 'End-to-end material tracking table', 'table', 'active', NULL, false, true, '{"location": "s3://mfg-lake/supply-chain/visibility/v1", "format": "delta"}'),
('00900006-0003-4000-8000-000000000006', '00700005-0003-4000-8000-000000000005', 'ehs_dashboard', '1.0.0', 'Safety analytics dashboard connection', 'dashboard', 'active', NULL, false, true, '{"location": "https://bi.factory.com/dashboards/safety-v1"}')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5d. DATA PRODUCT INPUT PORTS
-- ============================================================================

INSERT INTO data_product_input_ports (id, product_id, name, version, contract_id) VALUES
('00a00001-0003-4000-8000-000000000001', '00700001-0003-4000-8000-000000000001', 'MES Work Orders', '1.0.0', 'production-line-contract-v1'),
('00a00002-0003-4000-8000-000000000002', '00700001-0003-4000-8000-000000000001', 'Machine State Log', '1.0.0', 'production-line-contract-v1'),
('00a00003-0003-4000-8000-000000000003', '00700002-0003-4000-8000-000000000002', 'Inspection Results', '1.0.0', 'quality-inspection-contract-v1'),
('00a00004-0003-4000-8000-000000000004', '00700002-0003-4000-8000-000000000002', 'SPC Measurements', '1.0.0', 'quality-inspection-contract-v1'),
('00a00005-0003-4000-8000-000000000005', '00700003-0003-4000-8000-000000000003', 'Sensor Time-Series', '1.0.0', 'equipment-health-contract-v2'),
('00a00006-0003-4000-8000-000000000006', '00700003-0003-4000-8000-000000000003', 'CMMS History', '1.0.0', 'equipment-health-contract-v2'),
('00a00007-0003-4000-8000-000000000007', '00700004-0003-4000-8000-000000000004', 'WMS Data', '1.0.0', 'production-line-contract-v1'),
('00a00008-0003-4000-8000-000000000008', '00700004-0003-4000-8000-000000000004', 'EDI Supplier Feed', '1.0.0', 'production-line-contract-v1'),
('00a00009-0003-4000-8000-000000000009', '00700005-0003-4000-8000-000000000005', 'Safety Incidents', '1.0.0', 'ehs-incident-contract-v1'),
('00a0000a-0003-4000-8000-000000000010', '00700005-0003-4000-8000-000000000005', 'Environmental Sensors', '1.0.0', 'ehs-incident-contract-v1')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5e. DATA PRODUCT SUPPORT CHANNELS
-- ============================================================================

INSERT INTO data_product_support_channels (id, product_id, channel, url, tool, scope, description) VALUES
('00b00001-0003-4000-8000-000000000001', '00700001-0003-4000-8000-000000000001', 'production-data-ops', 'https://teams.com/channels/prod-data-ops', 'teams', 'interactive', 'Production data pipeline support'),
('00b00002-0003-4000-8000-000000000002', '00700002-0003-4000-8000-000000000002', 'quality-data-support', 'https://slack.com/channels/quality-data', 'slack', 'issues', NULL),
('00b00003-0003-4000-8000-000000000003', '00700003-0003-4000-8000-000000000003', 'pred-maint-support', 'https://jira.factory.com/projects/PREDMAINT', 'ticket', 'issues', 'JIRA project for predictive maintenance model issues'),
('00b00004-0003-4000-8000-000000000004', '00700004-0003-4000-8000-000000000004', 'supply-chain-ops', 'https://teams.com/channels/sc-visibility', 'teams', 'interactive', NULL),
('00b00005-0003-4000-8000-000000000005', '00700005-0003-4000-8000-000000000005', 'ehs-data-support', 'https://slack.com/channels/ehs-analytics', 'slack', 'announcements', 'Safety data updates and incident alerts')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5f. DATA PRODUCT TEAMS
-- ============================================================================

INSERT INTO data_product_teams (id, product_id, name, description) VALUES
('00c00001-0003-4000-8000-000000000001', '00700001-0003-4000-8000-000000000001', 'Production Engineering', NULL),
('00c00002-0003-4000-8000-000000000002', '00700002-0003-4000-8000-000000000002', 'Quality Engineering', NULL),
('00c00003-0003-4000-8000-000000000003', '00700003-0003-4000-8000-000000000003', 'Reliability Engineering', NULL),
('00c00004-0003-4000-8000-000000000004', '00700004-0003-4000-8000-000000000004', 'Supply Chain Analytics', NULL),
('00c00005-0003-4000-8000-000000000005', '00700005-0003-4000-8000-000000000005', 'EHS Analytics', NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5g. DATA PRODUCT TEAM MEMBERS
-- ============================================================================

INSERT INTO data_product_team_members (id, team_id, username, name, role) VALUES
('00d00001-0003-4000-8000-000000000001', '00c00001-0003-4000-8000-000000000001', 'plant.manager@factory.com', 'Mike Plant', 'owner'),
('00d00002-0003-4000-8000-000000000002', '00c00001-0003-4000-8000-000000000001', 'mes.engineer@factory.com', 'Nina MES', 'contributor'),
('00d00003-0003-4000-8000-000000000003', '00c00002-0003-4000-8000-000000000002', 'qa.director@factory.com', 'Oscar QA', 'owner'),
('00d00004-0003-4000-8000-000000000004', '00c00003-0003-4000-8000-000000000003', 'reliability.eng@factory.com', 'Paula Reliability', 'owner'),
('00d00005-0003-4000-8000-000000000005', '00c00004-0003-4000-8000-000000000004', 'sc.analyst@factory.com', 'Quinn SupplyChain', 'owner'),
('00d00006-0003-4000-8000-000000000006', '00c00005-0003-4000-8000-000000000005', 'ehs.manager@factory.com', 'Rachel EHS', 'owner')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 6. COMPLIANCE POLICIES (MFG-specific)
-- ============================================================================

INSERT INTO compliance_policies (id, name, description, failure_message, rule, category, severity, is_active, created_at, updated_at) VALUES
('01100001-0003-4000-8000-000000000001', 'ISO 9001 Traceability', 'Verify lot/serial traceability from raw material to finished goods per ISO 9001:2015',
'Product lot lacks complete material traceability. ISO 9001 Section 8.5.2 requires lot-level traceability for all manufactured products.',
'MATCH (p:Product) ASSERT p.has_lot_traceability = true AND p.genealogy_complete = true', 'quality', 'critical', true, NOW(), NOW()),

('01100002-0003-4000-8000-000000000002', 'SPC Out-of-Control Detection', 'Flag processes where SPC control charts indicate out-of-control conditions',
'Process characteristic is out of statistical control. Western Electric rules violations detected. Production hold and engineering review required.',
'MATCH (c:Characteristic) ASSERT c.spc_status = ''in_control''', 'quality', 'high', true, NOW(), NOW()),

('01100003-0003-4000-8000-000000000003', 'Equipment Calibration Currency', 'Ensure all measurement equipment has current calibration certification',
'Measurement equipment calibration is overdue. All gages, CMMs, and test equipment must have valid calibration certificates per the calibration schedule.',
'MATCH (e:Equipment) WHERE e.type = ''measurement'' ASSERT e.calibration_due_date > datetime()', 'governance', 'critical', true, NOW(), NOW()),

('01100004-0003-4000-8000-000000000004', 'OSHA Recordable Reporting', 'Ensure OSHA recordable incidents are documented within 7 calendar days',
'OSHA recordable incident not documented within required timeframe. Per 29 CFR 1904, OSHA 300 log must be updated within 7 calendar days of incident.',
'MATCH (i:Incident) WHERE i.is_osha_recordable = true ASSERT i.days_to_document <= 7', 'governance', 'high', true, NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 7. NOTIFICATIONS (MFG-specific)
-- ============================================================================

INSERT INTO notifications (id, type, title, subtitle, description, created_at, read, can_delete, recipient) VALUES
('01000001-0003-4000-8000-000000000001', 'error', 'SPC Out of Control', 'Line 3 - Bore Diameter', 'Western Electric Rule 1 violation: Single point beyond 3-sigma on bore diameter for part P-4521. Production hold initiated pending engineering review.', NOW() - INTERVAL '2 hours', false, false, NULL),
('01000002-0003-4000-8000-000000000002', 'warning', 'Predictive Maintenance Alert', 'CNC Mill M-207', 'Spindle bearing health score dropped to 34/100. Predicted failure window: 7-14 days. Recommend scheduling PM during next planned downtime.', NOW() - INTERVAL '8 hours', false, true, NULL),
('01000003-0003-4000-8000-000000000003', 'success', 'OEE Target Achieved', 'Plant A - December', 'Plant A achieved 87.3% OEE for December, exceeding the 85% target. Top performing line: Assembly Line 1 at 91.2%.', NOW() - INTERVAL '1 day', true, true, NULL),
('01000004-0003-4000-8000-000000000004', 'info', 'Calibration Due', '12 Instruments', '12 measurement instruments are due for calibration in the next 14 days. View calibration schedule for details.', NOW() - INTERVAL '2 days', false, true, NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 8. METADATA (Notes, Links)
-- ============================================================================

-- Rich Text Notes (type=016)
INSERT INTO rich_text_metadata (id, entity_id, entity_type, title, short_description, content_markdown, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01600001-0003-4000-8000-000000000001', '00700001-0003-4000-8000-000000000001', 'data_product', 'Overview', 'Real-time OEE and production KPIs across all lines.', E'# Production KPI Dashboard v1\n\nReal-time OEE, throughput, cycle time, and downtime KPIs across all production lines\nand shifts. Powers shop floor TV dashboards and management reviews.\n\n## OEE Calculation\n- Availability: Actual run time vs. planned production time\n- Performance: Actual cycle time vs. ideal cycle time\n- Quality: Good parts vs. total parts produced\n- World-class target: 85% OEE\n\n## Drill-Down Hierarchy\nPlant > Line > Station > Operator with shift-level filtering.\nDowntime Pareto analysis by category (mechanical, electrical, changeover, material).', false, 50, true, 'system@demo', NOW(), NOW()),
('01600002-0003-4000-8000-000000000002', '00700002-0003-4000-8000-000000000002', 'data_product', 'Overview', 'Real-time SPC charts and quality analytics.', E'# Quality Analytics Platform v1\n\nReal-time SPC control charts, Cpk/Ppk trends, defect Pareto analysis, and automated\nCAPA routing for manufacturing quality management.\n\n## SPC Capabilities\n- X-bar/R, X-bar/S, and individual/moving range charts\n- Western Electric and Nelson rules for out-of-control detection\n- Automated Cpk/Ppk calculation with trend alerts\n- Multi-variate control using Hotelling T-squared\n\n## Integration\n- QMS: Automated NCR creation on SPC rule violations\n- CMM: Direct measurement import from Zeiss/Hexagon\n- Vision: Defect image capture and classification\n- ERP: Quality hold and disposition workflow', false, 50, true, 'system@demo', NOW(), NOW()),
('01600003-0003-4000-8000-000000000003', '00700003-0003-4000-8000-000000000003', 'data_product', 'Overview', 'ML-based equipment failure prediction.', E'# Predictive Maintenance v1\n\nPredicts equipment failures 7-30 days ahead using vibration analysis, thermal trending,\nand ML models trained on historical CMMS data.\n\n## Model Performance\n- Bearing failures: ~87% accuracy, 14-day lead time\n- Motor winding: ~82% accuracy, 21-day lead time\n- Hydraulic leaks: ~79% accuracy, 7-day lead time\n- Electrical faults: ~72% accuracy, 10-day lead time\n\n## Sensor Infrastructure\n- Vibration: 10Hz sampling on spindles, bearings, gearboxes\n- Temperature: 1Hz on motors, hydraulic systems\n- Current: 1Hz on main drives\n- Minimum 30 days baseline data required per asset', false, 50, true, 'system@demo', NOW(), NOW()),
('01600004-0003-4000-8000-000000000004', '00700004-0003-4000-8000-000000000004', 'data_product', 'Overview', 'End-to-end material and WIP tracking.', E'# Supply Chain Visibility v1\n\nEnd-to-end supply chain visibility from raw material receipt through finished goods\nshipment with real-time work-in-process tracking.\n\n## Tracking Coverage\n- Inbound: Supplier shipments, receiving, and incoming quality\n- WIP: Work order progress, station-level tracking\n- Outbound: Finished goods, shipping, and delivery confirmation\n- Inventory: Bin-level accuracy, cycle count discrepancy alerts\n\n## Alert System\n- Material shortage predictions (72-hour horizon)\n- Supplier on-time delivery SLA violations\n- WIP bottleneck detection and aging alerts\n- Safety stock threshold breaches', false, 50, true, 'system@demo', NOW(), NOW()),
('01600005-0003-4000-8000-000000000005', '00700005-0003-4000-8000-000000000005', 'data_product', 'Overview', 'Safety leading and lagging indicator analytics.', E'# EHS Safety Analytics v1\n\nSafety leading and lagging indicator analytics including near-miss trends, TRIR, DART\nrate, and hazard heat maps for all manufacturing facilities.\n\n## Metrics Tracked\n- Lagging: TRIR, DART, severity rate, lost workday rate\n- Leading: Near-miss reports, safety observations, training compliance\n- Environmental: Emissions, waste generation, water usage\n- Compliance: OSHA 300 log, inspection findings\n\n## Reporting\n- Monthly safety committee review package\n- OSHA 300/300A automated log generation\n- Contractor safety qualification tracking\n- Incident investigation 5-Why and fishbone templates', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;

-- Link Metadata (type=017)
INSERT INTO link_metadata (id, entity_id, entity_type, title, short_description, url, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01700001-0003-4000-8000-000000000001', '00700001-0003-4000-8000-000000000001', 'data_product', 'Shop Floor Dashboard', 'Live OEE and production metrics.', 'https://bi.factory.com/dashboards/oee-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700002-0003-4000-8000-000000000002', '00700001-0003-4000-8000-000000000001', 'data_product', 'Runbook', 'MES data pipeline operations.', 'https://runbooks.factory.com/production/kpi-dashboard-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700003-0003-4000-8000-000000000003', '00700002-0003-4000-8000-000000000002', 'data_product', 'SPC Rules Reference', 'Western Electric and Nelson rules guide.', 'https://wiki.factory.com/quality/spc-rules-reference', false, 50, true, 'system@demo', NOW(), NOW()),
('01700004-0003-4000-8000-000000000004', '00700002-0003-4000-8000-000000000002', 'data_product', 'Quality Dashboard', 'Cpk trends and defect Pareto.', 'https://bi.factory.com/dashboards/quality-analytics-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700005-0003-4000-8000-000000000005', '00700003-0003-4000-8000-000000000003', 'data_product', 'Model Performance Dashboard', 'Prediction accuracy and lead times.', 'https://bi.factory.com/dashboards/pred-maint-accuracy', false, 50, true, 'system@demo', NOW(), NOW()),
('01700006-0003-4000-8000-000000000006', '00700003-0003-4000-8000-000000000003', 'data_product', 'Sensor Deployment Guide', 'Sensor types, placement, and calibration.', 'https://wiki.factory.com/maintenance/sensor-deployment-guide', false, 50, true, 'system@demo', NOW(), NOW()),
('01700007-0003-4000-8000-000000000007', '00700004-0003-4000-8000-000000000004', 'data_product', 'Runbook', 'Supply chain data pipeline operations.', 'https://runbooks.factory.com/supply-chain/visibility-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700008-0003-4000-8000-000000000008', '00700004-0003-4000-8000-000000000004', 'data_product', 'Inventory Dashboard', 'Stock levels and shortage alerts.', 'https://bi.factory.com/dashboards/inventory-visibility', false, 50, true, 'system@demo', NOW(), NOW()),
('01700009-0003-4000-8000-000000000009', '00700005-0003-4000-8000-000000000005', 'data_product', 'Safety Dashboard', 'TRIR, near-miss trends, and heat maps.', 'https://bi.factory.com/dashboards/safety-analytics-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000a-0003-4000-8000-000000000010', '00700005-0003-4000-8000-000000000005', 'data_product', 'OSHA Compliance Wiki', 'Recordkeeping and reporting requirements.', 'https://wiki.factory.com/ehs/osha-compliance-guide', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


COMMIT;

-- ============================================================================
-- End of MFG Industry Demo Data
-- ============================================================================
