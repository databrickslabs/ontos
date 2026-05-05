-- ============================================================================
-- Demo Data SQL Script
-- ============================================================================
-- This file contains all demo/example data for the application.
-- Load via the /api/settings/demo-data/load endpoint (Admin only).
--
-- Data is inserted in FK-safe order:
-- 1. Data Domains (hierarchical, parents first)
-- 2. Teams and Team Members
-- 3. Projects and Project-Team associations
-- 4. Data Contracts and child tables
-- 5. Data Products and child tables
-- 6. Data Asset Reviews
-- 7. Notifications
-- 8. Compliance Policies and Runs
-- 9. Cost Items
-- 10. RDF Triples (demo ontology concepts)
-- 11. Semantic Links
-- 12. Metadata (notes, links, documents)
--
-- UUID Format: {type:3}{seq:5}-{dataset:4}-4000-8000-00000000000N
-- All type codes are valid hex (0-9, a-f).
--
-- Fields:
--   xxx   = entity type code (see below)
--   yyyyy = record sequence number (hex)
--   zzzz  = dataset identifier
--     0000 = base/default (this file: demo_data.sql)
--     0001 = HLS (demo_data_hls.sql)
--     0002 = FSI (demo_data_fsi.sql)
--     0003 = MFG (demo_data_mfg.sql)
--     0004 = AUTO (demo_data_auto.sql)
--   N     = record sequence (decimal, mirrors yyyyy)
--
-- Type Codes:
--   000 = data_domains
--   001 = teams
--   002 = team_members
--   003 = projects
--   004 = data_contracts
--   005 = schema_objects
--   006 = schema_properties
--   007 = data_products
--   008 = data_product_descriptions
--   009 = output_ports
--   00a = input_ports
--   00b = support_channels
--   00c = data_product_teams
--   00d = data_product_team_members
--   00e = reviews (data_asset_review_requests)
--   00f = reviewed_assets
--   010 = notifications
--   011 = compliance_policies
--   012 = compliance_runs
--   013 = compliance_results
--   014 = cost_items
--   015 = semantic_links
--   016 = rich_text_metadata
--   017 = link_metadata
--   018 = document_metadata
--   019 = mdm_configs
--   01a = mdm_source_links
--   01b = mdm_match_runs
--   01c = mdm_match_candidates
--   01d = data_contract_authoritative_definitions
--   01e = data_contract_schema_object_authoritative_definitions
--   01f = data_contract_schema_property_authoritative_definitions
--   020 = rdf_triples (demo ontology concepts)
--   030 = knowledge_collection_meta (collection metadata in urn:meta:sources)
--   021 = datasets
--   022 = dataset_subscriptions
--   023 = dataset_tags
--   024 = dataset_custom_properties
--   025 = dataset_instances
--   026 = tag_namespaces
--   027 = tags
--   028 = tag_namespace_permissions
--   029 = entity_tag_associations
--   02a = process_workflows
--   02b = workflow_steps
--   02c = comments/ratings
--   02d = data_profiling_runs
--   02e = suggested_quality_checks
--   0f0 = business_roles
--   0f1 = policies (now stored as Policy assets in 0f3)
--   0f2 = asset_types
--   0f3 = assets
--   0f4 = asset_relationships
--   0f5 = policy_attachments (now stored as entity_relationships)
--   0f6 = business_owners
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. DATA DOMAINS (type=000)
-- ============================================================================
-- Hierarchical: Core first, then children

INSERT INTO data_domains (id, name, description, parent_id, created_by, created_at, updated_at) VALUES
-- Root domain
('00000001-0000-4000-8000-000000000001', 'Core', 'General, cross-company business concepts.', NULL, 'system@demo', NOW(), NOW()),

-- Level 1 children of Core
('00000002-0000-4000-8000-000000000002', 'Finance', 'Financial accounting, reporting, and metrics.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000003-0000-4000-8000-000000000003', 'Sales', 'Sales processes, opportunities, leads, and performance.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000004-0000-4000-8000-000000000004', 'Marketing', 'Customer acquisition, campaigns, engagement, and branding.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000005-0000-4000-8000-000000000005', 'Retail', 'All data related to retail business line, including operations and analytics.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000006-0000-4000-8000-000000000006', 'Supply Chain', 'Logistics, inventory management, reordering, and supplier relations.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000007-0000-4000-8000-000000000007', 'Customer', 'Direct customer information, profiles, segmentation, and interactions.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000008-0000-4000-8000-000000000008', 'Product', 'Product catalog, features, lifecycle, and development.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000009-0000-4000-8000-000000000009', 'Human Resources', 'Human resources, employee data, payroll, and recruitment.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('0000000a-0000-4000-8000-000000000010', 'IoT', 'Data from Internet of Things devices, sensors, and telemetry.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('0000000b-0000-4000-8000-000000000011', 'Compliance', 'Data related to legal, regulatory, and internal compliance requirements.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),

-- Level 2 children of Retail
('0000000c-0000-4000-8000-000000000012', 'Retail Operations', 'Store operations, point-of-sale (POS), inventory, and logistics.', '00000005-0000-4000-8000-000000000005', 'system@demo', NOW(), NOW()),
('0000000d-0000-4000-8000-000000000013', 'Retail Analytics', 'Analytics derived from retail operations data, including sales, demand, pricing.', '00000005-0000-4000-8000-000000000005', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2. TEAMS (type=001)
-- ============================================================================

INSERT INTO teams (id, name, title, description, domain_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00100001-0000-4000-8000-000000000001', 'data-engineering', 'Data Engineering Team', 'Responsible for data pipeline development and infrastructure', '00000001-0000-4000-8000-000000000001', '{"slack_channel": "https://company.slack.com/channels/data-eng", "lead": "john.doe@company.com"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100002-0000-4000-8000-000000000002', 'analytics-team', 'Analytics Team', 'Business analytics and reporting team', '0000000d-0000-4000-8000-000000000013', '{"slack_channel": "https://company.slack.com/channels/analytics", "tools": ["Tableau", "Power BI", "SQL"]}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100003-0000-4000-8000-000000000003', 'data-science', 'Data Science Team', 'Machine learning and advanced analytics', '00000008-0000-4000-8000-000000000008', '{"slack_channel": "https://company.slack.com/channels/data-science", "research_areas": ["NLP", "Computer Vision", "Recommendation Systems"]}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100004-0000-4000-8000-000000000004', 'governance-team', 'Data Governance Team', 'Data quality, compliance, and governance oversight', '0000000b-0000-4000-8000-000000000011', '{"slack_channel": "https://company.slack.com/channels/data-governance", "responsibilities": ["Data Quality", "Privacy Compliance", "Access Control"]}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2b. TEAM MEMBERS (type=002)
-- ============================================================================

INSERT INTO team_members (id, team_id, member_type, member_identifier, app_role_override, added_by, created_at, updated_at) VALUES
-- Data Engineering Team
('00200001-0000-4000-8000-000000000001', '00100001-0000-4000-8000-000000000001', 'user', 'john.doe@company.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200002-0000-4000-8000-000000000002', '00100001-0000-4000-8000-000000000001', 'group', 'data-engineers', NULL, 'system@demo', NOW(), NOW()),
('00200003-0000-4000-8000-000000000003', '00100001-0000-4000-8000-000000000001', 'user', 'jane.smith@company.com', 'Data Producer', 'system@demo', NOW(), NOW()),

-- Analytics Team
('00200004-0000-4000-8000-000000000004', '00100002-0000-4000-8000-000000000002', 'user', 'alice.johnson@company.com', 'Data Consumer', 'system@demo', NOW(), NOW()),
('00200005-0000-4000-8000-000000000005', '00100002-0000-4000-8000-000000000002', 'group', 'analysts', NULL, 'system@demo', NOW(), NOW()),

-- Data Science Team
('00200006-0000-4000-8000-000000000006', '00100003-0000-4000-8000-000000000003', 'user', 'bob.wilson@company.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200007-0000-4000-8000-000000000007', '00100003-0000-4000-8000-000000000003', 'group', 'data-scientists', NULL, 'system@demo', NOW(), NOW()),
('00200008-0000-4000-8000-000000000008', '00100003-0000-4000-8000-000000000003', 'user', 'carol.brown@company.com', 'Data Producer', 'system@demo', NOW(), NOW()),

-- Governance Team
('00200009-0000-4000-8000-000000000009', '00100004-0000-4000-8000-000000000004', 'user', 'david.garcia@company.com', 'Data Steward', 'system@demo', NOW(), NOW()),
('0020000a-0000-4000-8000-000000000010', '00100004-0000-4000-8000-000000000004', 'group', 'data-stewards', NULL, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3. PROJECTS (type=003)
-- ============================================================================

INSERT INTO projects (id, name, title, description, project_type, owner_team_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00300001-0000-4000-8000-000000000001', 'customer-360', 'Customer 360 Initiative', 'Comprehensive customer data platform and analytics', 'TEAM', '00100002-0000-4000-8000-000000000002', '{"budget": "$500K", "timeline": "6 months", "stakeholders": ["Marketing", "Sales", "Customer Success"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300002-0000-4000-8000-000000000002', 'financial-reporting', 'Financial Reporting Modernization', 'Modernize financial reporting infrastructure and processes', 'TEAM', '00100004-0000-4000-8000-000000000004', '{"budget": "$300K", "timeline": "4 months", "compliance_requirements": ["SOX", "GAAP"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300003-0000-4000-8000-000000000003', 'ml-platform', 'Machine Learning Platform', 'Build and deploy ML infrastructure and services', 'TEAM', '00100003-0000-4000-8000-000000000003', '{"budget": "$750K", "timeline": "8 months", "technologies": ["MLflow", "Kubernetes", "TensorFlow"], "priority": "medium"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300004-0000-4000-8000-000000000004', 'data-governance-pilot', 'Data Governance Pilot Program', 'Pilot program for implementing data governance best practices', 'TEAM', '00100004-0000-4000-8000-000000000004', '{"budget": "$200K", "timeline": "3 months", "scope": ["Data Quality", "Data Lineage", "Access Control"], "priority": "medium"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300005-0000-4000-8000-000000000005', 'real-time-analytics', 'Real-time Analytics Platform', 'Build real-time streaming analytics capabilities', 'TEAM', '00100001-0000-4000-8000-000000000001', '{"budget": "$400K", "timeline": "5 months", "technologies": ["Kafka", "Spark Streaming", "Delta Lake"], "priority": "low"}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3b. PROJECT-TEAM ASSOCIATIONS
-- ============================================================================

INSERT INTO project_teams (project_id, team_id, assigned_by, assigned_at) VALUES
-- Customer 360: data-engineering, analytics-team, data-science
('00300001-0000-4000-8000-000000000001', '00100001-0000-4000-8000-000000000001', 'system@demo', NOW()),
('00300001-0000-4000-8000-000000000001', '00100002-0000-4000-8000-000000000002', 'system@demo', NOW()),
('00300001-0000-4000-8000-000000000001', '00100003-0000-4000-8000-000000000003', 'system@demo', NOW()),

-- Financial Reporting: data-engineering, analytics-team, governance-team
('00300002-0000-4000-8000-000000000002', '00100001-0000-4000-8000-000000000001', 'system@demo', NOW()),
('00300002-0000-4000-8000-000000000002', '00100002-0000-4000-8000-000000000002', 'system@demo', NOW()),
('00300002-0000-4000-8000-000000000002', '00100004-0000-4000-8000-000000000004', 'system@demo', NOW()),

-- ML Platform: data-engineering, data-science
('00300003-0000-4000-8000-000000000003', '00100001-0000-4000-8000-000000000001', 'system@demo', NOW()),
('00300003-0000-4000-8000-000000000003', '00100003-0000-4000-8000-000000000003', 'system@demo', NOW()),

-- Data Governance Pilot: governance-team, data-engineering
('00300004-0000-4000-8000-000000000004', '00100004-0000-4000-8000-000000000004', 'system@demo', NOW()),
('00300004-0000-4000-8000-000000000004', '00100001-0000-4000-8000-000000000001', 'system@demo', NOW()),

-- Real-time Analytics: data-engineering, analytics-team
('00300005-0000-4000-8000-000000000005', '00100001-0000-4000-8000-000000000001', 'system@demo', NOW()),
('00300005-0000-4000-8000-000000000005', '00100002-0000-4000-8000-000000000002', 'system@demo', NOW())

ON CONFLICT (project_id, team_id) DO NOTHING;


-- ============================================================================
-- 4. DATA CONTRACTS (type=004)
-- ============================================================================

INSERT INTO data_contracts (id, name, kind, api_version, version, status, published, owner_team_id, domain_id, description_purpose, description_usage, description_limitations, publication_scope, created_by, updated_by, created_at, updated_at) VALUES
-- Customer Data Contract
('00400001-0000-4000-8000-000000000001', 'Customer Data Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100001-0000-4000-8000-000000000001', '00000007-0000-4000-8000-000000000007', 'Core customer data contract defining customer profile, preferences, and transaction history', 'Customer master data to power user-facing apps, analytics, and marketing campaigns', 'Emails must be validated; PII must be encrypted at rest; data retention 7 years max', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

-- Product Catalog Contract
('00400002-0000-4000-8000-000000000002', 'Product Catalog Contract', 'DataContract', 'v3.1.0', '1.0.0', 'deprecated', false, '00100002-0000-4000-8000-000000000002', '00000008-0000-4000-8000-000000000008', 'Complete product catalog with categories, inventory, pricing, and vendor information', 'Power e-commerce platform, merchandising experiences, and inventory management', 'Price values must be non-negative; SKUs must be unique; inventory counts must be integers', 'none', 'system@demo', 'system@demo', NOW(), NOW()),

-- Data Sharing Agreement
('00400003-0000-4000-8000-000000000003', 'Data Sharing Agreement', 'DataContract', 'v3.1.0', '2.0.0', 'active', true, '00100004-0000-4000-8000-000000000004', '0000000b-0000-4000-8000-000000000011', 'Legal agreement for data sharing between Analytics and Marketing', 'Enables sharing of aggregated analytics for campaign optimization', 'No external sharing; PII must be masked; delete after 90 days', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

-- IoT Device Data Contract
('00400004-0000-4000-8000-000000000004', 'IoT Device Data Contract', 'DataContract', 'v3.1.0', '1.1.0', 'active', true, '00100003-0000-4000-8000-000000000003', '0000000a-0000-4000-8000-000000000010', 'Comprehensive IoT device management and telemetry data for smart building systems', 'Monitor device health, performance, and environmental data in near real-time for predictive maintenance and energy optimization', 'Timestamps must be UTC; numeric telemetry must be within calibrated device ranges; data retention 2 years max', 'org', 'system@demo', 'system@demo', NOW(), NOW()),

-- IoT Sensor Data Contract (retired)
('00400005-0000-4000-8000-000000000005', 'IoT Sensor Data Contract', 'DataContract', 'v3.1.0', '2.0.0', 'retired', false, '00100003-0000-4000-8000-000000000003', '0000000a-0000-4000-8000-000000000010', 'Real-time IoT sensor data from manufacturing floor', 'Stream analytics and anomaly detection', 'Primary key is (sensor_id, timestamp)', 'none', 'system@demo', 'system@demo', NOW(), NOW()),

-- Financial Transactions Contract
('00400006-0000-4000-8000-000000000006', 'Financial Transactions Contract', 'DataContract', 'v3.1.0', '1.0.0', 'draft', false, '00100004-0000-4000-8000-000000000004', '00000002-0000-4000-8000-000000000002', 'Daily financial transaction data', 'Reconciliation, accounting, and reporting', 'Amount must be >= 0; currency must be ISO-4217', 'none', 'system@demo', 'system@demo', NOW(), NOW()),

-- Inventory Management Contract
('00400007-0000-4000-8000-000000000007', 'Inventory Management Contract', 'DataContract', 'v3.1.0', '1.2.0', 'deprecated', false, '00100002-0000-4000-8000-000000000002', '00000006-0000-4000-8000-000000000006', 'Real-time inventory levels and movements', 'Track stock levels across warehouses', 'Quantity must be integer >= 0', 'none', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4b. DATA CONTRACT SCHEMA OBJECTS (type=005)
-- ============================================================================

INSERT INTO data_contract_schema_objects (id, contract_id, name, logical_type, physical_name, description) VALUES
-- Customer Data Contract schemas
('00500001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'customers', 'object', 'crm.customers_v2', 'Core customer master table'),
('00500002-0000-4000-8000-000000000002', '00400001-0000-4000-8000-000000000001', 'customer_preferences', 'object', 'crm.customer_preferences', 'Customer preference settings'),
('00500003-0000-4000-8000-000000000003', '00400001-0000-4000-8000-000000000001', 'customer_addresses', 'object', 'crm.customer_addresses', 'Customer address information'),

-- IoT Device Data Contract schemas
('00500004-0000-4000-8000-000000000004', '00400004-0000-4000-8000-000000000004', 'devices', 'object', 'iot.devices_master', 'IoT device registry'),
('00500005-0000-4000-8000-000000000005', '00400004-0000-4000-8000-000000000004', 'device_telemetry', 'object', 'iot.device_telemetry_live', 'Device telemetry readings'),
('00500006-0000-4000-8000-000000000006', '00400004-0000-4000-8000-000000000004', 'device_events', 'object', 'iot.device_events_log', 'Device events and alerts')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4c. DATA CONTRACT SCHEMA PROPERTIES (type=006)
-- ============================================================================

INSERT INTO data_contract_schema_properties (id, object_id, name, logical_type, required, "unique", primary_key, partitioned, primary_key_position, partition_key_position, critical_data_element, transform_description) VALUES
-- customers table properties
('00600001-0000-4000-8000-000000000001', '00500001-0000-4000-8000-000000000001', 'customer_id', 'string', true, true, true, false, 1, -1, true, 'Unique customer identifier (UUID format)'),
('00600002-0000-4000-8000-000000000002', '00500001-0000-4000-8000-000000000001', 'email', 'string', true, true, false, false, -1, -1, true, 'Customer email address (primary contact)'),
('00600003-0000-4000-8000-000000000003', '00500001-0000-4000-8000-000000000001', 'first_name', 'string', true, false, false, false, -1, -1, false, 'Customer first name'),
('00600004-0000-4000-8000-000000000004', '00500001-0000-4000-8000-000000000001', 'last_name', 'string', true, false, false, false, -1, -1, false, 'Customer last name'),
('00600005-0000-4000-8000-000000000005', '00500001-0000-4000-8000-000000000001', 'date_of_birth', 'date', false, false, false, false, -1, -1, false, 'Customer date of birth (YYYY-MM-DD)'),
('00600006-0000-4000-8000-000000000006', '00500001-0000-4000-8000-000000000001', 'phone_number', 'string', false, false, false, false, -1, -1, false, 'Primary phone number (E.164 format)'),
('00600007-0000-4000-8000-000000000007', '00500001-0000-4000-8000-000000000001', 'country_code', 'string', true, false, false, false, -1, -1, false, 'ISO 3166-1 alpha-2 country code'),
('00600008-0000-4000-8000-000000000008', '00500001-0000-4000-8000-000000000001', 'registration_date', 'timestamp', true, false, false, false, -1, -1, false, 'Account registration timestamp (UTC)'),
('00600009-0000-4000-8000-000000000009', '00500001-0000-4000-8000-000000000001', 'account_status', 'string', true, false, false, false, -1, -1, false, 'Account status (active, suspended, closed, pending_verification)'),
('0060000a-0000-4000-8000-000000000010', '00500001-0000-4000-8000-000000000001', 'email_verified', 'boolean', true, false, false, false, -1, -1, false, 'Whether email address has been verified'),

-- devices table properties
('0060000b-0000-4000-8000-000000000011', '00500004-0000-4000-8000-000000000004', 'device_id', 'string', true, true, true, false, 1, -1, true, 'Unique device identifier (UUID format)'),
('0060000c-0000-4000-8000-000000000012', '00500004-0000-4000-8000-000000000004', 'device_serial', 'string', true, true, false, false, -1, -1, false, 'Manufacturer serial number'),
('0060000d-0000-4000-8000-000000000013', '00500004-0000-4000-8000-000000000004', 'device_type', 'string', true, false, false, false, -1, -1, false, 'Device type (sensor, actuator, gateway, controller)'),
('0060000e-0000-4000-8000-000000000014', '00500004-0000-4000-8000-000000000004', 'status', 'string', true, false, false, false, -1, -1, false, 'Device status (active, inactive, maintenance, faulty, decommissioned)'),
('0060000f-0000-4000-8000-000000000015', '00500004-0000-4000-8000-000000000004', 'is_online', 'boolean', true, false, false, false, -1, -1, false, 'Current connectivity status')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5. DATA PRODUCTS (type=007)
-- ============================================================================

INSERT INTO data_products (id, api_version, kind, status, name, version, domain, tenant, owner_team_id, max_level_inheritance, published, publication_scope, created_at, updated_at) VALUES
('00700001-0000-4000-8000-000000000001', 'v1.0.0', 'DataProduct', 'active', 'POS Transaction Stream v1', '1.0.0', 'Retail Operations', 'retail-demo', '00100001-0000-4000-8000-000000000001', 99, true, 'org', NOW(), NOW()),
('00700002-0000-4000-8000-000000000002', 'v1.0.0', 'DataProduct', 'active', 'Prepared Sales Transactions v1', '1.0.0', 'Retail Analytics', 'retail-demo', '00100001-0000-4000-8000-000000000001', 99, true, 'org', NOW(), NOW()),
('00700003-0000-4000-8000-000000000003', 'v1.0.0', 'DataProduct', 'active', 'Demand Forecast Model Output v1', '1.0.0', 'Retail Analytics', 'retail-demo', '00100002-0000-4000-8000-000000000002', 99, true, 'org', NOW(), NOW()),
('00700004-0000-4000-8000-000000000004', 'v1.0.0', 'DataProduct', 'active', 'Inventory Optimization Recommendations v1', '1.0.0', 'Supply Chain', 'retail-demo', '00100001-0000-4000-8000-000000000001', 99, true, 'org', NOW(), NOW()),
('00700005-0000-4000-8000-000000000005', 'v1.0.0', 'DataProduct', 'active', 'Price Optimization Model Output v1', '1.0.0', 'Retail Analytics', 'retail-demo', '00100002-0000-4000-8000-000000000002', 99, true, 'org', NOW(), NOW()),
('00700006-0000-4000-8000-000000000006', 'v1.0.0', 'DataProduct', 'active', 'Customer Marketing Recommendations v1', '1.0.0', 'Marketing', 'retail-demo', '00100004-0000-4000-8000-000000000004', 99, true, 'org', NOW(), NOW()),
('00700007-0000-4000-8000-000000000007', 'v1.0.0', 'DataProduct', 'active', 'Retail Performance Dashboard Data v1', '1.0.0', 'Retail Analytics', 'retail-demo', '00100002-0000-4000-8000-000000000002', 99, true, 'org', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5b. DATA PRODUCT DESCRIPTIONS (type=008)
-- ============================================================================

INSERT INTO data_product_descriptions (id, product_id, purpose, usage, limitations) VALUES
('00800001-0000-4000-8000-000000000001', '00700001-0000-4000-8000-000000000001', 'Provide real-time point-of-sale transaction data from store systems for downstream analytics and operational use cases.', 'Consume this stream for real-time fraud detection, inventory tracking, or as a foundation for prepared analytics datasets.', 'Raw data format may contain system-specific codes. Some transactions may have delayed timestamps.'),
('00800002-0000-4000-8000-000000000002', '00700002-0000-4000-8000-000000000002', 'Provide cleaned, validated, and standardized sales transaction data ready for analytics consumption.', 'Use for BI reporting, demand forecasting, customer analytics, and other downstream analytical use cases.', 'Data is batch-processed with 1-hour lag. PII fields are masked according to data governance policies.'),
('00800003-0000-4000-8000-000000000003', '00700003-0000-4000-8000-000000000003', 'Provide predicted demand for products at various locations based on historical sales and external factors.', 'Use for inventory planning, supply chain optimization, and promotional planning.', 'Forecasts are updated daily. Accuracy degrades beyond 30-day horizon.'),
('00800004-0000-4000-8000-000000000004', '00700004-0000-4000-8000-000000000004', 'Provide automated inventory reordering recommendations based on demand forecasts and current stock levels.', 'API consumed by inventory management system to trigger automated reorders.', 'Recommendations assume lead times from supplier contracts.'),
('00800005-0000-4000-8000-000000000005', '00700005-0000-4000-8000-000000000005', 'Provide data-driven pricing recommendations based on demand elasticity and competitive positioning.', 'Review recommendations weekly and apply to pricing systems via bulk import.', 'Model excludes promotional pricing. Recommendations should be reviewed by category managers.'),
('00800006-0000-4000-8000-000000000006', '00700006-0000-4000-8000-000000000006', 'Provide targeted customer segments and personalized product recommendations for marketing campaigns.', 'Export customer lists weekly for email campaigns. Use real-time API for website personalization.', 'Contains PII - restricted access. Email frequency caps applied per GDPR.'),
('00800007-0000-4000-8000-000000000007', '00700007-0000-4000-8000-000000000007', 'Provide aggregated, denormalized data optimized for executive-level retail performance dashboards.', 'Connect BI tools directly via provided connection string. Data refreshes nightly at 2 AM EST.', 'Historical data limited to 2 years rolling window.')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5c. DATA PRODUCT OUTPUT PORTS (type=009)
-- ============================================================================

INSERT INTO data_product_output_ports (id, product_id, name, version, description, port_type, status, contract_id, contains_pii, auto_approve, server) VALUES
('00900001-0000-4000-8000-000000000001', '00700001-0000-4000-8000-000000000001', 'POS Kafka Stream', '1.0.0', 'Real-time feed of raw POS transaction events', 'kafka', 'active', 'pos-transaction-contract-v1', false, false, '{"host": "kafka.example.com", "topic": "pos-transactions-raw-v1"}'),
('00900002-0000-4000-8000-000000000002', '00700002-0000-4000-8000-000000000002', 'prepared_sales_delta', '1.0.0', 'Delta table containing cleaned sales transactions', 'table', 'active', 'prepared-sales-contract-v1', true, false, '{"location": "s3://data-lake/prepared/retail/sales/v1", "format": "delta"}'),
('00900003-0000-4000-8000-000000000003', '00700003-0000-4000-8000-000000000003', 'demand_forecast_table', '1.0.0', 'Delta table containing product demand forecasts', 'table', 'active', 'demand-forecast-contract-v1', false, true, '{"location": "s3://data-analytics/retail/forecast/v1", "format": "delta"}'),
('00900004-0000-4000-8000-000000000004', '00700004-0000-4000-8000-000000000004', 'Inventory Reorder API', '1.0.0', 'API endpoint for inventory management system', 'api', 'active', NULL, false, false, '{"location": "https://api.example.com/inventory/reorder/v1"}'),
('00900005-0000-4000-8000-000000000005', '00700005-0000-4000-8000-000000000005', 'price_recommendations_table', '1.0.0', 'Delta table with optimal price recommendations', 'table', 'active', 'price-recommendations-contract-v1', false, false, '{"location": "s3://data-analytics/retail/pricing/v1", "format": "delta"}'),
('00900006-0000-4000-8000-000000000006', '00700006-0000-4000-8000-000000000006', 'marketing_campaign_list', '1.0.0', 'CSV file with customer IDs and recommended campaigns', 'file', 'active', NULL, true, false, '{"location": "s3://data-marketing/retail/campaigns/v1/targets.csv", "format": "csv"}'),
('00900007-0000-4000-8000-000000000007', '00700007-0000-4000-8000-000000000007', 'BI Tool Connection', '1.0.0', 'Direct connection endpoint for BI tool consumption', 'dashboard', 'active', NULL, false, true, '{"location": "https://bi.example.com/dashboards/retail-perf-v1"}')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5d. DATA PRODUCT INPUT PORTS (type=00a)
-- ============================================================================

INSERT INTO data_product_input_ports (id, product_id, name, version, contract_id) VALUES
('00a00001-0000-4000-8000-000000000001', '00700002-0000-4000-8000-000000000002', 'Raw POS Stream', '1.0.0', 'pos-transaction-contract-v1'),
('00a00002-0000-4000-8000-000000000002', '00700003-0000-4000-8000-000000000003', 'Prepared Sales Data', '1.0.0', 'prepared-sales-contract-v1'),
('00a00003-0000-4000-8000-000000000003', '00700004-0000-4000-8000-000000000004', 'Demand Forecast Data', '1.0.0', 'demand-forecast-contract-v1'),
('00a00004-0000-4000-8000-000000000004', '00700005-0000-4000-8000-000000000005', 'Demand Forecast Data', '1.0.0', 'demand-forecast-contract-v1'),
('00a00005-0000-4000-8000-000000000005', '00700005-0000-4000-8000-000000000005', 'Competitor Pricing Feed', '1.0.0', 'competitor-pricing-contract-v1'),
('00a00006-0000-4000-8000-000000000006', '00700006-0000-4000-8000-000000000006', 'Prepared Sales Data', '1.0.0', 'prepared-sales-contract-v1'),
('00a00007-0000-4000-8000-000000000007', '00700006-0000-4000-8000-000000000006', 'Customer Profile Data', '1.0.0', 'customer-profile-contract-v1'),
('00a00008-0000-4000-8000-000000000008', '00700007-0000-4000-8000-000000000007', 'Prepared Sales Data', '1.0.0', 'prepared-sales-contract-v1'),
('00a00009-0000-4000-8000-000000000009', '00700007-0000-4000-8000-000000000007', 'Demand Forecast Data', '1.0.0', 'demand-forecast-contract-v1'),
('00a0000a-0000-4000-8000-000000000010', '00700007-0000-4000-8000-000000000007', 'Inventory Snapshot', '1.0.0', 'inventory-snapshot-contract-v1')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5e. DATA PRODUCT SUPPORT CHANNELS (type=00b)
-- ============================================================================

INSERT INTO data_product_support_channels (id, product_id, channel, url, tool, scope, description) VALUES
('00b00001-0000-4000-8000-000000000001', '00700001-0000-4000-8000-000000000001', 'pos-stream-support', 'https://slack.com/channels/pos-stream-support', 'slack', 'interactive', '24/7 support channel for POS stream issues'),
('00b00002-0000-4000-8000-000000000002', '00700002-0000-4000-8000-000000000002', 'prepared-data-support', 'https://slack.com/channels/prepared-data-support', 'slack', 'issues', NULL),
('00b00003-0000-4000-8000-000000000003', '00700003-0000-4000-8000-000000000003', 'ml-support', 'https://teams.com/channels/ml-support', 'teams', 'interactive', NULL),
('00b00004-0000-4000-8000-000000000004', '00700004-0000-4000-8000-000000000004', 'inventory-ops-support', 'https://jira.example.com/projects/INV', 'ticket', 'issues', 'JIRA project for inventory optimization issues'),
('00b00005-0000-4000-8000-000000000005', '00700005-0000-4000-8000-000000000005', 'pricing-team', 'https://slack.com/channels/pricing-team', 'slack', 'interactive', NULL),
('00b00006-0000-4000-8000-000000000006', '00700006-0000-4000-8000-000000000006', 'marketing-ops', 'https://slack.com/channels/marketing-ops', 'slack', 'announcements', 'Campaign launch announcements and coordination'),
('00b00007-0000-4000-8000-000000000007', '00700007-0000-4000-8000-000000000007', 'bi-support', 'https://teams.com/channels/bi-support', 'teams', 'interactive', NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5f. DATA PRODUCT TEAMS (type=00c)
-- ============================================================================

INSERT INTO data_product_teams (id, product_id, name, description) VALUES
('00c00001-0000-4000-8000-000000000001', '00700001-0000-4000-8000-000000000001', 'Data Engineering', NULL),
('00c00002-0000-4000-8000-000000000002', '00700002-0000-4000-8000-000000000002', 'Data Engineering', NULL),
('00c00003-0000-4000-8000-000000000003', '00700003-0000-4000-8000-000000000003', 'Analytics Team', NULL),
('00c00004-0000-4000-8000-000000000004', '00700004-0000-4000-8000-000000000004', 'Operations Team', NULL),
('00c00005-0000-4000-8000-000000000005', '00700005-0000-4000-8000-000000000005', 'Analytics Team', NULL),
('00c00006-0000-4000-8000-000000000006', '00700006-0000-4000-8000-000000000006', 'Marketing Team', NULL),
('00c00007-0000-4000-8000-000000000007', '00700007-0000-4000-8000-000000000007', 'Analytics Team', NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5g. DATA PRODUCT TEAM MEMBERS (type=00d)
-- ============================================================================

INSERT INTO data_product_team_members (id, team_id, username, name, role) VALUES
('00d00001-0000-4000-8000-000000000001', '00c00001-0000-4000-8000-000000000001', 'eng-lead@example.com', 'Alice Engineer', 'owner'),
('00d00002-0000-4000-8000-000000000002', '00c00002-0000-4000-8000-000000000002', 'eng-lead@example.com', 'Alice Engineer', 'owner'),
('00d00003-0000-4000-8000-000000000003', '00c00002-0000-4000-8000-000000000002', 'data-steward@example.com', 'Bob Steward', 'data steward'),
('00d00004-0000-4000-8000-000000000004', '00c00003-0000-4000-8000-000000000003', 'ml-lead@example.com', 'Charlie ML', 'owner'),
('00d00005-0000-4000-8000-000000000005', '00c00003-0000-4000-8000-000000000003', 'data-scientist@example.com', 'Dana Scientist', 'contributor'),
('00d00006-0000-4000-8000-000000000006', '00c00004-0000-4000-8000-000000000004', 'ops-lead@example.com', 'Eve Operations', 'owner'),
('00d00007-0000-4000-8000-000000000007', '00c00005-0000-4000-8000-000000000005', 'pricing-analyst@example.com', 'Frank Analyst', 'owner'),
('00d00008-0000-4000-8000-000000000008', '00c00006-0000-4000-8000-000000000006', 'marketing-lead@example.com', 'Grace Marketing', 'owner'),
('00d00009-0000-4000-8000-000000000009', '00c00007-0000-4000-8000-000000000007', 'bi-dev@example.com', 'Henry BI', 'owner')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 6. DATA ASSET REVIEWS (type=00e)
-- ============================================================================

INSERT INTO data_asset_review_requests (id, requester_email, reviewer_email, status, notes, created_at, updated_at) VALUES
('00e00001-0000-4000-8000-000000000001', 'data.user@example.com', 'data.steward@example.com', 'queued', 'Initial review request for core sales data.', NOW(), NOW()),
('00e00002-0000-4000-8000-000000000002', 'analyst@example.com', 'data.steward@example.com', 'in_review', 'Checking staging data before promotion.', NOW(), NOW()),
('00e00003-0000-4000-8000-000000000003', 'data.user@example.com', 'security.officer@example.com', 'approved', 'Security review completed and approved.', NOW(), NOW()),
('00e00004-0000-4000-8000-000000000004', 'trainee@example.com', 'data.steward@example.com', 'needs_review', 'Please clarify the view logic and data sources.', NOW(), NOW()),
('00e00005-0000-4000-8000-000000000005', 'data.engineer@example.com', 'data.architect@example.com', 'queued', 'Review new utility function and its associated storage volume.', NOW(), NOW()),
('00e00006-0000-4000-8000-000000000006', 'data.scientist@example.com', 'lead.data.scientist@example.com', 'in_review', 'Please review this new exploratory analysis notebook for PII and best practices.', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 6b. REVIEWED ASSETS (type=00f)
-- ============================================================================

INSERT INTO reviewed_assets (id, review_request_id, asset_fqn, asset_type, status, comments, updated_at) VALUES
('00f00001-0000-4000-8000-000000000001', '00e00001-0000-4000-8000-000000000001', 'main.sales.orders', 'table', 'pending', NULL, NOW()),
('00f00002-0000-4000-8000-000000000002', '00e00001-0000-4000-8000-000000000001', 'main.marketing.campaign_view', 'view', 'pending', NULL, NOW()),
('00f00003-0000-4000-8000-000000000003', '00e00002-0000-4000-8000-000000000002', 'dev.staging.customer_data', 'table', 'approved', 'Looks good. Ready for prod.', NOW()),
('00f00004-0000-4000-8000-000000000004', '00e00002-0000-4000-8000-000000000002', 'dev.staging.udf_process_customer', 'function', 'pending', NULL, NOW()),
('00f00005-0000-4000-8000-000000000005', '00e00003-0000-4000-8000-000000000003', 'sensitive.hr.employee_pii', 'table', 'approved', 'Access restricted. PII confirmed.', NOW()),
('00f00006-0000-4000-8000-000000000006', '00e00004-0000-4000-8000-000000000004', 'main.finance.quarterly_report_view', 'view', 'needs_clarification', 'What is the source for column X? The calculation seems off.', NOW()),
('00f00007-0000-4000-8000-000000000007', '00e00005-0000-4000-8000-000000000005', 'utils.common.fn_clean_string', 'function', 'pending', NULL, NOW()),
('00f00008-0000-4000-8000-000000000008', '00e00005-0000-4000-8000-000000000005', 'utils.common.raw_uploads', 'volume', 'pending', 'Check access permissions and naming convention for this volume.', NOW()),
('00f00009-0000-4000-8000-000000000009', '00e00006-0000-4000-8000-000000000006', '/Repos/shared/exploratory_analysis/customer_segmentation_v1', 'notebook', 'pending', 'Focus on commands 3 and 5 regarding data handling.', NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 7. NOTIFICATIONS (type=010)
-- ============================================================================

INSERT INTO notifications (id, type, title, subtitle, description, created_at, read, can_delete, recipient) VALUES
('01000001-0000-4000-8000-000000000001', 'success', 'Data Contract Approved', 'Contract: Customer360', 'The data contract for Customer360 has been approved by all stakeholders', NOW() - INTERVAL '1 day', false, true, NULL),
('01000002-0000-4000-8000-000000000002', 'warning', 'Compliance Policy Alert', 'PII Data Encryption', 'Some datasets containing PII are not properly encrypted. Check Compliance dashboard for details.', NOW() - INTERVAL '1 day 1 hour', false, true, NULL),
('01000003-0000-4000-8000-000000000003', 'info', 'New Business Term Added', 'Customer Lifetime Value', 'A new business term has been added to the Finance glossary', NOW() - INTERVAL '2 days', true, true, NULL),
('01000004-0000-4000-8000-000000000004', 'error', 'Security Feature Disabled', 'Column Encryption', 'Column encryption for customer_data.pii_table has been disabled unexpectedly', NOW() - INTERVAL '2 days 2 hours', false, false, NULL),
('01000005-0000-4000-8000-000000000005', 'info', 'System Maintenance', 'Scheduled Downtime', 'System maintenance scheduled for Saturday 20:00 UTC', NOW() - INTERVAL '2 days 4 hours', true, true, NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 8. COMPLIANCE POLICIES (type=011)
-- ============================================================================

INSERT INTO compliance_policies (id, name, description, failure_message, rule, category, severity, is_active, created_at, updated_at) VALUES
('01100001-0000-4000-8000-000000000001', 'Naming Conventions', 'Verify that all objects follow corporate naming conventions', 
'Names must use snake_case format (lowercase letters with underscores). For example: "customer_orders" is valid, but "CustomerOrders" or "customer-orders" are not. Views must be prefixed with "v_".', 
E'MATCH (obj:Object)\nWHERE obj.type IN [''catalog'', ''schema'', ''table'', ''view'']\nASSERT \n  CASE obj.type\n    WHEN ''catalog'' THEN obj.name MATCHES ''^[a-z][a-z0-9_]*$''\n    WHEN ''schema'' THEN obj.name MATCHES ''^[a-z][a-z0-9_]*$''\n    WHEN ''table'' THEN obj.name MATCHES ''^[a-z][a-z0-9_]*$''\n    WHEN ''view'' THEN obj.name MATCHES ''^v_[a-z][a-z0-9_]*$''\n  END', 'governance', 'high', true, NOW(), NOW()),
('01100002-0000-4000-8000-000000000002', 'PII Data Encryption', 'Ensure all PII data is encrypted at rest', 
'All datasets containing Personally Identifiable Information (PII) must be encrypted using AES-256 encryption. Please enable encryption on the table or contact your security team for assistance.',
'MATCH (d:Dataset) WHERE d.contains_pii = true ASSERT d.encryption = ''AES256''', 'security', 'critical', true, NOW(), NOW()),
('01100003-0000-4000-8000-000000000003', 'Data Quality Thresholds', 'Maintain data quality metrics above defined thresholds', 
'Data quality must meet minimum standards: completeness > 95% and accuracy > 98%. Review the data pipeline for missing or incorrect values before publishing.',
'MATCH (d:Dataset) ASSERT d.completeness > 0.95 AND d.accuracy > 0.98', 'quality', 'high', true, NOW(), NOW()),
('01100004-0000-4000-8000-000000000004', 'Access Control', 'Verify proper access controls on sensitive data', 
'High-sensitivity datasets must have restricted access controls configured. Please set access_level to "restricted" and ensure only authorized groups have access.',
'MATCH (d:Dataset) WHERE d.sensitivity = ''high'' ASSERT d.access_level = ''restricted''', 'security', 'critical', true, NOW(), NOW()),
('01100005-0000-4000-8000-000000000005', 'Data Freshness', 'Ensure data is updated within defined timeframes', 
'Data appears to be stale (not updated within the last 24 hours). Check the data pipeline status and ensure scheduled jobs are running correctly.',
'MATCH (d:Dataset) ASSERT d.last_updated > datetime() - duration(''P1D'')', 'freshness', 'medium', true, NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 8b. COMPLIANCE RUNS (type=012)
-- ============================================================================

INSERT INTO compliance_runs (id, policy_id, status, started_at, finished_at, success_count, failure_count, score) VALUES
('01200001-0000-4000-8000-000000000001', '01100001-0000-4000-8000-000000000001', 'succeeded', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day' + INTERVAL '1 minute', 4, 2, 66.7),
('01200002-0000-4000-8000-000000000002', '01100001-0000-4000-8000-000000000001', 'succeeded', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days' + INTERVAL '2 minutes', 5, 1, 83.3),
('01200003-0000-4000-8000-000000000003', '01100002-0000-4000-8000-000000000002', 'succeeded', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day' + INTERVAL '40 seconds', 4, 1, 80.0),
('01200004-0000-4000-8000-000000000004', '01100003-0000-4000-8000-000000000003', 'succeeded', NOW() - INTERVAL '3 days', NOW() - INTERVAL '3 days' + INTERVAL '1 minute 10 seconds', 9, 1, 90.0),
('01200005-0000-4000-8000-000000000005', '01100004-0000-4000-8000-000000000004', 'succeeded', NOW() - INTERVAL '4 days', NOW() - INTERVAL '4 days' + INTERVAL '35 seconds', 3, 1, 75.0),
('01200006-0000-4000-8000-000000000006', '01100005-0000-4000-8000-000000000005', 'succeeded', NOW() - INTERVAL '5 days', NOW() - INTERVAL '5 days' + INTERVAL '28 seconds', 8, 1, 88.9)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 8c. COMPLIANCE RESULTS (type=013)
-- ============================================================================

INSERT INTO compliance_results (id, run_id, object_type, object_id, object_name, passed, message, created_at) VALUES
('01300001-0000-4000-8000-000000000001', '01200001-0000-4000-8000-000000000001', 'catalog', 'analytics', 'analytics', true, NULL, NOW()),
('01300002-0000-4000-8000-000000000002', '01200001-0000-4000-8000-000000000001', 'schema', 'customer_360', 'customer_360', true, NULL, NOW()),
('01300003-0000-4000-8000-000000000003', '01200001-0000-4000-8000-000000000001', 'table', 'Orders', 'Orders', false, 'Expected name to match ^[a-z][a-z0-9_]*$', NOW()),
('01300004-0000-4000-8000-000000000004', '01200001-0000-4000-8000-000000000001', 'view', 'orders_view', 'orders_view', false, 'Views must start with v_', NOW()),
('01300005-0000-4000-8000-000000000005', '01200003-0000-4000-8000-000000000003', 'dataset', 'customer.emails', 'customer.emails', true, NULL, NOW()),
('01300006-0000-4000-8000-000000000006', '01200003-0000-4000-8000-000000000003', 'dataset', 'customer.addresses', 'customer.addresses', true, NULL, NOW()),
('01300007-0000-4000-8000-000000000007', '01200003-0000-4000-8000-000000000003', 'dataset', 'customer.cards', 'customer.cards', false, 'Encryption required: AES256', NOW()),
('01300008-0000-4000-8000-000000000008', '01200004-0000-4000-8000-000000000004', 'dataset', 'sales.orders_daily', 'sales.orders_daily', true, NULL, NOW()),
('01300009-0000-4000-8000-000000000009', '01200004-0000-4000-8000-000000000004', 'dataset', 'sales.orders_raw', 'sales.orders_raw', false, 'completeness=0.91 < 0.95', NOW()),
('0130000a-0000-4000-8000-000000000010', '01200005-0000-4000-8000-000000000005', 'dataset', 'hr.salaries', 'hr.salaries', true, NULL, NOW()),
('0130000b-0000-4000-8000-000000000011', '01200005-0000-4000-8000-000000000005', 'dataset', 'finance.payments', 'finance.payments', false, 'access_level must be restricted', NOW()),
('0130000c-0000-4000-8000-000000000012', '01200006-0000-4000-8000-000000000006', 'dataset', 'bi.product_dim', 'bi.product_dim', true, NULL, NOW()),
('0130000d-0000-4000-8000-000000000013', '01200006-0000-4000-8000-000000000006', 'dataset', 'bi.inventory_fact', 'bi.inventory_fact', false, 'last_updated older than 1 day', NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 9. COST ITEMS (type=014)
-- ============================================================================
-- Note: cost_items.id is UUID type, so we use valid hex UUIDs

INSERT INTO cost_items (id, entity_type, entity_id, title, description, cost_center, custom_center_name, amount_cents, currency, start_month, created_by, created_at, updated_at) VALUES
('01400001-0000-4000-8000-000000000001', 'data_product', '00700001-0000-4000-8000-000000000001', 'Staff', 'Monthly HR cost for developers', 'HR', NULL, 450000, 'USD', '2025-10-01', 'system@demo', NOW(), NOW()),
('01400002-0000-4000-8000-000000000002', 'data_product', '00700001-0000-4000-8000-000000000001', 'Consulting', 'External support', 'OTHER', '3343', 250000, 'USD', '2025-10-01', 'system@demo', NOW(), NOW()),
('01400003-0000-4000-8000-000000000003', 'data_product', '00700001-0000-4000-8000-000000000001', 'Storage', 'Table storage and retention', 'STORAGE', NULL, 120000, 'USD', '2025-10-01', 'system@demo', NOW(), NOW()),
('01400004-0000-4000-8000-000000000004', 'data_product', '00700001-0000-4000-8000-000000000001', 'Maintenance', 'Tooling subscriptions and upkeep', 'MAINTENANCE', NULL, 80000, 'USD', '2025-10-01', 'system@demo', NOW(), NOW()),
('01400005-0000-4000-8000-000000000005', 'data_product', '00700001-0000-4000-8000-000000000001', 'Infra', 'Databricks serverless usage (synced)', 'INFRASTRUCTURE', NULL, 300000, 'USD', '2025-10-01', 'system@demo', NOW(), NOW()),
('01400006-0000-4000-8000-000000000006', 'data_product', '00700002-0000-4000-8000-000000000002', 'Infra', 'Databricks serverless usage (synced)', 'INFRASTRUCTURE', NULL, 220000, 'USD', '2025-10-01', 'system@demo', NOW(), NOW()),
('01400007-0000-4000-8000-000000000007', 'data_product', '00700002-0000-4000-8000-000000000002', 'Staff', 'Data engineer on-call', 'HR', NULL, 350000, 'USD', '2025-10-01', 'system@demo', NOW(), NOW()),
('01400008-0000-4000-8000-000000000008', 'data_product', '00700002-0000-4000-8000-000000000002', 'Storage', 'Delta tables', 'STORAGE', NULL, 90000, 'USD', '2025-10-01', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 10. RDF TRIPLES - Demo Ontology Concepts (type=020)
-- ============================================================================
-- These define the demo business concepts that are referenced by entity_semantic_links.
-- Without these, clicking on semantic links in the UI would find no matching concepts.
-- Uses the demo namespace: http://demo.ontos.app/concepts#

INSERT INTO rdf_triples (id, subject_uri, predicate_uri, object_value, object_is_uri, context_name, source_type, source_identifier, created_by, created_at) VALUES
-- Domain Concepts (rdf:type skos:Concept)
('02000001-0000-4000-8000-000000000001', 'http://demo.ontos.app/concepts#CustomerDomain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000002-0000-4000-8000-000000000002', 'http://demo.ontos.app/concepts#CustomerDomain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Customer Domain', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000003-0000-4000-8000-000000000003', 'http://demo.ontos.app/concepts#FinancialDomain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000004-0000-4000-8000-000000000004', 'http://demo.ontos.app/concepts#FinancialDomain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Financial Domain', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000005-0000-4000-8000-000000000005', 'http://demo.ontos.app/concepts#SalesDomain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000006-0000-4000-8000-000000000006', 'http://demo.ontos.app/concepts#SalesDomain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Sales Domain', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000007-0000-4000-8000-000000000007', 'http://demo.ontos.app/concepts#MarketingDomain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000008-0000-4000-8000-000000000008', 'http://demo.ontos.app/concepts#MarketingDomain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Marketing Domain', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000009-0000-4000-8000-000000000009', 'http://demo.ontos.app/concepts#RetailDomain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200000a-0000-4000-8000-00000000000a', 'http://demo.ontos.app/concepts#RetailDomain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Retail Domain', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200000b-0000-4000-8000-00000000000b', 'http://demo.ontos.app/concepts#ProductDomain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200000c-0000-4000-8000-00000000000c', 'http://demo.ontos.app/concepts#ProductDomain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Product Domain', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200000d-0000-4000-8000-00000000000d', 'http://demo.ontos.app/concepts#EmployeeDomain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200000e-0000-4000-8000-00000000000e', 'http://demo.ontos.app/concepts#EmployeeDomain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Employee Domain', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),

-- Business Concepts (for Data Products)
('0200000f-0000-4000-8000-00000000000f', 'http://demo.ontos.app/concepts#Sale', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000010-0000-4000-8000-000000000010', 'http://demo.ontos.app/concepts#Sale', 'http://www.w3.org/2000/01/rdf-schema#label', 'Sale', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000011-0000-4000-8000-000000000011', 'http://demo.ontos.app/concepts#Transaction', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000012-0000-4000-8000-000000000012', 'http://demo.ontos.app/concepts#Transaction', 'http://www.w3.org/2000/01/rdf-schema#label', 'Transaction', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000013-0000-4000-8000-000000000013', 'http://demo.ontos.app/concepts#Customer', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000014-0000-4000-8000-000000000014', 'http://demo.ontos.app/concepts#Customer', 'http://www.w3.org/2000/01/rdf-schema#label', 'Customer', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000015-0000-4000-8000-000000000015', 'http://demo.ontos.app/concepts#Inventory', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000016-0000-4000-8000-000000000016', 'http://demo.ontos.app/concepts#Inventory', 'http://www.w3.org/2000/01/rdf-schema#label', 'Inventory', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000017-0000-4000-8000-000000000017', 'http://demo.ontos.app/concepts#Product', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000018-0000-4000-8000-000000000018', 'http://demo.ontos.app/concepts#Product', 'http://www.w3.org/2000/01/rdf-schema#label', 'Product', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),

-- Glossary Terms (for Data Contracts and Schemas)
('02000019-0000-4000-8000-000000000019', 'http://demo.ontos.app/glossary#Customer', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200001a-0000-4000-8000-00000000001a', 'http://demo.ontos.app/glossary#Customer', 'http://www.w3.org/2000/01/rdf-schema#label', 'Customer', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200001b-0000-4000-8000-00000000001b', 'http://demo.ontos.app/glossary#PersonalData', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200001c-0000-4000-8000-00000000001c', 'http://demo.ontos.app/glossary#PersonalData', 'http://www.w3.org/2000/01/rdf-schema#label', 'Personal Data', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200001d-0000-4000-8000-00000000001d', 'http://demo.ontos.app/glossary#Product', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200001e-0000-4000-8000-00000000001e', 'http://demo.ontos.app/glossary#Product', 'http://www.w3.org/2000/01/rdf-schema#label', 'Product', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200001f-0000-4000-8000-00000000001f', 'http://demo.ontos.app/glossary#Inventory', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000020-0000-4000-8000-000000000020', 'http://demo.ontos.app/glossary#Inventory', 'http://www.w3.org/2000/01/rdf-schema#label', 'Inventory', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000021-0000-4000-8000-000000000021', 'http://demo.ontos.app/glossary#Device', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000022-0000-4000-8000-000000000022', 'http://demo.ontos.app/glossary#Device', 'http://www.w3.org/2000/01/rdf-schema#label', 'Device', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000023-0000-4000-8000-000000000023', 'http://demo.ontos.app/glossary#Telemetry', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000024-0000-4000-8000-000000000024', 'http://demo.ontos.app/glossary#Telemetry', 'http://www.w3.org/2000/01/rdf-schema#label', 'Telemetry', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000025-0000-4000-8000-000000000025', 'http://demo.ontos.app/glossary#Transaction', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000026-0000-4000-8000-000000000026', 'http://demo.ontos.app/glossary#Transaction', 'http://www.w3.org/2000/01/rdf-schema#label', 'Transaction', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000027-0000-4000-8000-000000000027', 'http://demo.ontos.app/glossary#FinancialRecord', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000028-0000-4000-8000-000000000028', 'http://demo.ontos.app/glossary#FinancialRecord', 'http://www.w3.org/2000/01/rdf-schema#label', 'Financial Record', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),

-- Schema-level glossary terms
('02000029-0000-4000-8000-000000000029', 'http://demo.ontos.app/glossary#CustomerProfile', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200002a-0000-4000-8000-00000000002a', 'http://demo.ontos.app/glossary#CustomerProfile', 'http://www.w3.org/2000/01/rdf-schema#label', 'Customer Profile', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200002b-0000-4000-8000-00000000002b', 'http://demo.ontos.app/glossary#MasterData', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200002c-0000-4000-8000-00000000002c', 'http://demo.ontos.app/glossary#MasterData', 'http://www.w3.org/2000/01/rdf-schema#label', 'Master Data', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200002d-0000-4000-8000-00000000002d', 'http://demo.ontos.app/glossary#CustomerPreference', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200002e-0000-4000-8000-00000000002e', 'http://demo.ontos.app/glossary#CustomerPreference', 'http://www.w3.org/2000/01/rdf-schema#label', 'Customer Preference', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200002f-0000-4000-8000-00000000002f', 'http://demo.ontos.app/glossary#Address', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000030-0000-4000-8000-000000000030', 'http://demo.ontos.app/glossary#Address', 'http://www.w3.org/2000/01/rdf-schema#label', 'Address', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000031-0000-4000-8000-000000000031', 'http://demo.ontos.app/glossary#ContactInformation', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000032-0000-4000-8000-000000000032', 'http://demo.ontos.app/glossary#ContactInformation', 'http://www.w3.org/2000/01/rdf-schema#label', 'Contact Information', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000033-0000-4000-8000-000000000033', 'http://demo.ontos.app/glossary#IoTDevice', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000034-0000-4000-8000-000000000034', 'http://demo.ontos.app/glossary#IoTDevice', 'http://www.w3.org/2000/01/rdf-schema#label', 'IoT Device', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000035-0000-4000-8000-000000000035', 'http://demo.ontos.app/glossary#AssetRegistry', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000036-0000-4000-8000-000000000036', 'http://demo.ontos.app/glossary#AssetRegistry', 'http://www.w3.org/2000/01/rdf-schema#label', 'Asset Registry', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000037-0000-4000-8000-000000000037', 'http://demo.ontos.app/glossary#SensorReading', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000038-0000-4000-8000-000000000038', 'http://demo.ontos.app/glossary#SensorReading', 'http://www.w3.org/2000/01/rdf-schema#label', 'Sensor Reading', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000039-0000-4000-8000-000000000039', 'http://demo.ontos.app/glossary#DeviceEvent', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200003a-0000-4000-8000-00000000003a', 'http://demo.ontos.app/glossary#DeviceEvent', 'http://www.w3.org/2000/01/rdf-schema#label', 'Device Event', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200003b-0000-4000-8000-00000000003b', 'http://demo.ontos.app/glossary#Alert', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200003c-0000-4000-8000-00000000003c', 'http://demo.ontos.app/glossary#Alert', 'http://www.w3.org/2000/01/rdf-schema#label', 'Alert', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),

-- Property-level glossary terms
('0200003d-0000-4000-8000-00000000003d', 'http://demo.ontos.app/glossary#CustomerId', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200003e-0000-4000-8000-00000000003e', 'http://demo.ontos.app/glossary#CustomerId', 'http://www.w3.org/2000/01/rdf-schema#label', 'Customer ID', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200003f-0000-4000-8000-00000000003f', 'http://demo.ontos.app/glossary#UniqueIdentifier', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000040-0000-4000-8000-000000000040', 'http://demo.ontos.app/glossary#UniqueIdentifier', 'http://www.w3.org/2000/01/rdf-schema#label', 'Unique Identifier', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000041-0000-4000-8000-000000000041', 'http://demo.ontos.app/glossary#EmailAddress', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000042-0000-4000-8000-000000000042', 'http://demo.ontos.app/glossary#EmailAddress', 'http://www.w3.org/2000/01/rdf-schema#label', 'Email Address', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000043-0000-4000-8000-000000000043', 'http://demo.ontos.app/glossary#PII', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000044-0000-4000-8000-000000000044', 'http://demo.ontos.app/glossary#PII', 'http://www.w3.org/2000/01/rdf-schema#label', 'PII', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000045-0000-4000-8000-000000000045', 'http://demo.ontos.app/glossary#FirstName', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000046-0000-4000-8000-000000000046', 'http://demo.ontos.app/glossary#FirstName', 'http://www.w3.org/2000/01/rdf-schema#label', 'First Name', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000047-0000-4000-8000-000000000047', 'http://demo.ontos.app/glossary#LastName', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000048-0000-4000-8000-000000000048', 'http://demo.ontos.app/glossary#LastName', 'http://www.w3.org/2000/01/rdf-schema#label', 'Last Name', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000049-0000-4000-8000-000000000049', 'http://demo.ontos.app/glossary#DateOfBirth', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200004a-0000-4000-8000-00000000004a', 'http://demo.ontos.app/glossary#DateOfBirth', 'http://www.w3.org/2000/01/rdf-schema#label', 'Date of Birth', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200004b-0000-4000-8000-00000000004b', 'http://demo.ontos.app/glossary#PhoneNumber', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200004c-0000-4000-8000-00000000004c', 'http://demo.ontos.app/glossary#PhoneNumber', 'http://www.w3.org/2000/01/rdf-schema#label', 'Phone Number', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200004d-0000-4000-8000-00000000004d', 'http://demo.ontos.app/glossary#CountryCode', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200004e-0000-4000-8000-00000000004e', 'http://demo.ontos.app/glossary#CountryCode', 'http://www.w3.org/2000/01/rdf-schema#label', 'Country Code', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('0200004f-0000-4000-8000-00000000004f', 'http://demo.ontos.app/glossary#AccountStatus', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000050-0000-4000-8000-000000000050', 'http://demo.ontos.app/glossary#AccountStatus', 'http://www.w3.org/2000/01/rdf-schema#label', 'Account Status', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000051-0000-4000-8000-000000000051', 'http://demo.ontos.app/glossary#DeviceId', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000052-0000-4000-8000-000000000052', 'http://demo.ontos.app/glossary#DeviceId', 'http://www.w3.org/2000/01/rdf-schema#label', 'Device ID', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000053-0000-4000-8000-000000000053', 'http://demo.ontos.app/glossary#DeviceType', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000054-0000-4000-8000-000000000054', 'http://demo.ontos.app/glossary#DeviceType', 'http://www.w3.org/2000/01/rdf-schema#label', 'Device Type', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000055-0000-4000-8000-000000000055', 'http://demo.ontos.app/glossary#DeviceStatus', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://www.w3.org/2004/02/skos/core#Concept', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
('02000056-0000-4000-8000-000000000056', 'http://demo.ontos.app/glossary#DeviceStatus', 'http://www.w3.org/2000/01/rdf-schema#label', 'Device Status', false, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),

-- Hierarchy Relationships (skos:broader) - Business Concepts under their Domains
-- Sale -> SalesDomain
('02000101-0000-4000-8000-000000000101', 'http://demo.ontos.app/concepts#Sale', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#SalesDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Transaction -> FinancialDomain
('02000102-0000-4000-8000-000000000102', 'http://demo.ontos.app/concepts#Transaction', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#FinancialDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Customer -> CustomerDomain
('02000103-0000-4000-8000-000000000103', 'http://demo.ontos.app/concepts#Customer', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#CustomerDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Inventory -> ProductDomain
('02000104-0000-4000-8000-000000000104', 'http://demo.ontos.app/concepts#Inventory', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#ProductDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Product -> ProductDomain
('02000105-0000-4000-8000-000000000105', 'http://demo.ontos.app/concepts#Product', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#ProductDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),

-- Glossary Terms under their parent concepts/domains
-- Customer glossary term -> Customer concept
('02000111-0000-4000-8000-000000000111', 'http://demo.ontos.app/glossary#Customer', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#Customer', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- PersonalData -> CustomerDomain
('02000112-0000-4000-8000-000000000112', 'http://demo.ontos.app/glossary#PersonalData', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#CustomerDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Product glossary term -> Product concept
('02000113-0000-4000-8000-000000000113', 'http://demo.ontos.app/glossary#Product', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#Product', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Inventory glossary term -> Inventory concept
('02000114-0000-4000-8000-000000000114', 'http://demo.ontos.app/glossary#Inventory', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#Inventory', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Device -> ProductDomain
('02000115-0000-4000-8000-000000000115', 'http://demo.ontos.app/glossary#Device', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#ProductDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Telemetry -> Device
('02000116-0000-4000-8000-000000000116', 'http://demo.ontos.app/glossary#Telemetry', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Device', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Transaction glossary term -> Transaction concept
('02000117-0000-4000-8000-000000000117', 'http://demo.ontos.app/glossary#Transaction', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#Transaction', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- FinancialRecord -> FinancialDomain
('02000118-0000-4000-8000-000000000118', 'http://demo.ontos.app/glossary#FinancialRecord', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#FinancialDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- CustomerProfile -> Customer glossary
('02000119-0000-4000-8000-000000000119', 'http://demo.ontos.app/glossary#CustomerProfile', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Customer', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- MasterData -> CustomerDomain
('0200011a-0000-4000-8000-00000000011a', 'http://demo.ontos.app/glossary#MasterData', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/concepts#CustomerDomain', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- CustomerPreference -> CustomerProfile
('0200011b-0000-4000-8000-00000000011b', 'http://demo.ontos.app/glossary#CustomerPreference', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#CustomerProfile', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Address -> CustomerProfile
('0200011c-0000-4000-8000-00000000011c', 'http://demo.ontos.app/glossary#Address', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#CustomerProfile', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- ContactInformation -> CustomerProfile
('0200011d-0000-4000-8000-00000000011d', 'http://demo.ontos.app/glossary#ContactInformation', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#CustomerProfile', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- IoTDevice -> Device
('0200011e-0000-4000-8000-00000000011e', 'http://demo.ontos.app/glossary#IoTDevice', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Device', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- AssetRegistry -> Device
('0200011f-0000-4000-8000-00000000011f', 'http://demo.ontos.app/glossary#AssetRegistry', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Device', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- SensorReading -> Telemetry
('02000120-0000-4000-8000-000000000120', 'http://demo.ontos.app/glossary#SensorReading', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Telemetry', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- DeviceEvent -> Telemetry
('02000121-0000-4000-8000-000000000121', 'http://demo.ontos.app/glossary#DeviceEvent', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Telemetry', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- Alert -> DeviceEvent
('02000122-0000-4000-8000-000000000122', 'http://demo.ontos.app/glossary#Alert', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#DeviceEvent', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- CustomerId -> Customer glossary
('02000123-0000-4000-8000-000000000123', 'http://demo.ontos.app/glossary#CustomerId', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Customer', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- UniqueIdentifier -> MasterData
('02000124-0000-4000-8000-000000000124', 'http://demo.ontos.app/glossary#UniqueIdentifier', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#MasterData', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- EmailAddress -> ContactInformation
('02000125-0000-4000-8000-000000000125', 'http://demo.ontos.app/glossary#EmailAddress', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#ContactInformation', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- PII -> PersonalData
('02000126-0000-4000-8000-000000000126', 'http://demo.ontos.app/glossary#PII', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#PersonalData', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- FirstName -> PII
('02000127-0000-4000-8000-000000000127', 'http://demo.ontos.app/glossary#FirstName', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#PII', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- LastName -> PII
('02000128-0000-4000-8000-000000000128', 'http://demo.ontos.app/glossary#LastName', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#PII', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- DateOfBirth -> PII
('02000129-0000-4000-8000-000000000129', 'http://demo.ontos.app/glossary#DateOfBirth', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#PII', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- PhoneNumber -> ContactInformation
('0200012a-0000-4000-8000-00000000012a', 'http://demo.ontos.app/glossary#PhoneNumber', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#ContactInformation', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- CountryCode -> Address
('0200012b-0000-4000-8000-00000000012b', 'http://demo.ontos.app/glossary#CountryCode', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Address', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- AccountStatus -> Customer glossary
('0200012c-0000-4000-8000-00000000012c', 'http://demo.ontos.app/glossary#AccountStatus', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Customer', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- DeviceId -> Device
('0200012d-0000-4000-8000-00000000012d', 'http://demo.ontos.app/glossary#DeviceId', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Device', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- DeviceType -> Device
('0200012e-0000-4000-8000-00000000012e', 'http://demo.ontos.app/glossary#DeviceType', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Device', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW()),
-- DeviceStatus -> Device
('0200012f-0000-4000-8000-00000000012f', 'http://demo.ontos.app/glossary#DeviceStatus', 'http://www.w3.org/2004/02/skos/core#broader', 'http://demo.ontos.app/glossary#Device', true, 'urn:demo', 'demo', 'demo_data.sql', 'system@demo', NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 10b. KNOWLEDGE COLLECTIONS (Collection Metadata in urn:meta:sources)
-- ============================================================================
-- Register the demo RDF context as a KnowledgeCollection with hierarchy.
-- Uses ontos: namespace for collection properties.
-- Type codes: 030 = knowledge_collection_meta

INSERT INTO rdf_triples (id, subject_uri, predicate_uri, object_value, object_is_uri, context_name, source_type, source_identifier, created_by, created_at) VALUES
-- Enterprise Glossary Collection (parent collection)
('03000001-0000-4000-8000-000000000001', 'urn:glossary:enterprise', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://ontos.app/ontology#KnowledgeCollection', true, 'urn:meta:sources', 'collection', 'urn:glossary:enterprise', 'system@demo', NOW()),
('03000002-0000-4000-8000-000000000002', 'urn:glossary:enterprise', 'http://www.w3.org/2000/01/rdf-schema#label', 'Enterprise Glossary', false, 'urn:meta:sources', 'collection', 'urn:glossary:enterprise', 'system@demo', NOW()),
('03000003-0000-4000-8000-000000000003', 'urn:glossary:enterprise', 'http://www.w3.org/2000/01/rdf-schema#comment', 'Company-wide business terms and definitions used across all domains', false, 'urn:meta:sources', 'collection', 'urn:glossary:enterprise', 'system@demo', NOW()),
('03000004-0000-4000-8000-000000000004', 'urn:glossary:enterprise', 'http://ontos.app/ontology#collectionType', 'glossary', false, 'urn:meta:sources', 'collection', 'urn:glossary:enterprise', 'system@demo', NOW()),
('03000005-0000-4000-8000-000000000005', 'urn:glossary:enterprise', 'http://ontos.app/ontology#scopeLevel', 'enterprise', false, 'urn:meta:sources', 'collection', 'urn:glossary:enterprise', 'system@demo', NOW()),
('03000006-0000-4000-8000-000000000006', 'urn:glossary:enterprise', 'http://ontos.app/ontology#sourceType', 'custom', false, 'urn:meta:sources', 'collection', 'urn:glossary:enterprise', 'system@demo', NOW()),
('03000007-0000-4000-8000-000000000007', 'urn:glossary:enterprise', 'http://ontos.app/ontology#isEditable', 'true', false, 'urn:meta:sources', 'collection', 'urn:glossary:enterprise', 'system@demo', NOW()),
('03000008-0000-4000-8000-000000000008', 'urn:glossary:enterprise', 'http://ontos.app/ontology#status', 'active', false, 'urn:meta:sources', 'collection', 'urn:glossary:enterprise', 'system@demo', NOW()),

-- Demo Collection (child of Enterprise Glossary - contains the demo concepts)
('03000011-0000-4000-8000-000000000011', 'urn:demo', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://ontos.app/ontology#KnowledgeCollection', true, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),
('03000012-0000-4000-8000-000000000012', 'urn:demo', 'http://www.w3.org/2000/01/rdf-schema#label', 'Demo Business Concepts', false, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),
('03000013-0000-4000-8000-000000000013', 'urn:demo', 'http://www.w3.org/2000/01/rdf-schema#comment', 'Demo business concepts and glossary terms for retail operations', false, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),
('03000014-0000-4000-8000-000000000014', 'urn:demo', 'http://ontos.app/ontology#collectionType', 'glossary', false, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),
('03000015-0000-4000-8000-000000000015', 'urn:demo', 'http://ontos.app/ontology#scopeLevel', 'domain', false, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),
('03000016-0000-4000-8000-000000000016', 'urn:demo', 'http://ontos.app/ontology#parentCollection', 'urn:glossary:enterprise', true, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),
('03000017-0000-4000-8000-000000000017', 'urn:demo', 'http://ontos.app/ontology#sourceType', 'custom', false, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),
('03000018-0000-4000-8000-000000000018', 'urn:demo', 'http://ontos.app/ontology#isEditable', 'true', false, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),
('03000019-0000-4000-8000-000000000019', 'urn:demo', 'http://ontos.app/ontology#status', 'active', false, 'urn:meta:sources', 'collection', 'urn:demo', 'system@demo', NOW()),

-- Customer Domain Glossary (child of Demo - specific to customer domain)
('03000021-0000-4000-8000-000000000021', 'urn:glossary:customer-domain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://ontos.app/ontology#KnowledgeCollection', true, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),
('03000022-0000-4000-8000-000000000022', 'urn:glossary:customer-domain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Customer Domain Glossary', false, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),
('03000023-0000-4000-8000-000000000023', 'urn:glossary:customer-domain', 'http://www.w3.org/2000/01/rdf-schema#comment', 'Business terms specific to customer data and CRM operations', false, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),
('03000024-0000-4000-8000-000000000024', 'urn:glossary:customer-domain', 'http://ontos.app/ontology#collectionType', 'glossary', false, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),
('03000025-0000-4000-8000-000000000025', 'urn:glossary:customer-domain', 'http://ontos.app/ontology#scopeLevel', 'domain', false, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),
('03000026-0000-4000-8000-000000000026', 'urn:glossary:customer-domain', 'http://ontos.app/ontology#parentCollection', 'urn:glossary:enterprise', true, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),
('03000027-0000-4000-8000-000000000027', 'urn:glossary:customer-domain', 'http://ontos.app/ontology#sourceType', 'custom', false, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),
('03000028-0000-4000-8000-000000000028', 'urn:glossary:customer-domain', 'http://ontos.app/ontology#isEditable', 'true', false, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),
('03000029-0000-4000-8000-000000000029', 'urn:glossary:customer-domain', 'http://ontos.app/ontology#status', 'active', false, 'urn:meta:sources', 'collection', 'urn:glossary:customer-domain', 'system@demo', NOW()),

-- IoT Domain Glossary (child of Demo - specific to IoT domain)
('03000031-0000-4000-8000-000000000031', 'urn:glossary:iot-domain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://ontos.app/ontology#KnowledgeCollection', true, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),
('03000032-0000-4000-8000-000000000032', 'urn:glossary:iot-domain', 'http://www.w3.org/2000/01/rdf-schema#label', 'IoT Domain Glossary', false, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),
('03000033-0000-4000-8000-000000000033', 'urn:glossary:iot-domain', 'http://www.w3.org/2000/01/rdf-schema#comment', 'Business terms for IoT devices, sensors, and telemetry data', false, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),
('03000034-0000-4000-8000-000000000034', 'urn:glossary:iot-domain', 'http://ontos.app/ontology#collectionType', 'glossary', false, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),
('03000035-0000-4000-8000-000000000035', 'urn:glossary:iot-domain', 'http://ontos.app/ontology#scopeLevel', 'domain', false, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),
('03000036-0000-4000-8000-000000000036', 'urn:glossary:iot-domain', 'http://ontos.app/ontology#parentCollection', 'urn:glossary:enterprise', true, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),
('03000037-0000-4000-8000-000000000037', 'urn:glossary:iot-domain', 'http://ontos.app/ontology#sourceType', 'custom', false, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),
('03000038-0000-4000-8000-000000000038', 'urn:glossary:iot-domain', 'http://ontos.app/ontology#isEditable', 'true', false, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),
('03000039-0000-4000-8000-000000000039', 'urn:glossary:iot-domain', 'http://ontos.app/ontology#status', 'active', false, 'urn:meta:sources', 'collection', 'urn:glossary:iot-domain', 'system@demo', NOW()),

-- Finance Domain Glossary
('03000041-0000-4000-8000-000000000041', 'urn:glossary:finance-domain', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'http://ontos.app/ontology#KnowledgeCollection', true, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW()),
('03000042-0000-4000-8000-000000000042', 'urn:glossary:finance-domain', 'http://www.w3.org/2000/01/rdf-schema#label', 'Finance Domain Glossary', false, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW()),
('03000043-0000-4000-8000-000000000043', 'urn:glossary:finance-domain', 'http://www.w3.org/2000/01/rdf-schema#comment', 'Financial terms, metrics, and reporting concepts', false, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW()),
('03000044-0000-4000-8000-000000000044', 'urn:glossary:finance-domain', 'http://ontos.app/ontology#collectionType', 'glossary', false, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW()),
('03000045-0000-4000-8000-000000000045', 'urn:glossary:finance-domain', 'http://ontos.app/ontology#scopeLevel', 'domain', false, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW()),
('03000046-0000-4000-8000-000000000046', 'urn:glossary:finance-domain', 'http://ontos.app/ontology#parentCollection', 'urn:glossary:enterprise', true, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW()),
('03000047-0000-4000-8000-000000000047', 'urn:glossary:finance-domain', 'http://ontos.app/ontology#sourceType', 'custom', false, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW()),
('03000048-0000-4000-8000-000000000048', 'urn:glossary:finance-domain', 'http://ontos.app/ontology#isEditable', 'true', false, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW()),
('03000049-0000-4000-8000-000000000049', 'urn:glossary:finance-domain', 'http://ontos.app/ontology#status', 'active', false, 'urn:meta:sources', 'collection', 'urn:glossary:finance-domain', 'system@demo', NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 11. SEMANTIC LINKS (type=015)
-- ============================================================================

INSERT INTO entity_semantic_links (id, entity_id, entity_type, iri, label, created_by, created_at) VALUES
-- Data Domains (link to demo.ontos.app concepts defined in rdf_triples above)
('01500001-0000-4000-8000-000000000001', '00000007-0000-4000-8000-000000000007', 'data_domain', 'http://demo.ontos.app/concepts#CustomerDomain', 'Customer Domain', 'system@demo', NOW()),
('01500002-0000-4000-8000-000000000002', '00000002-0000-4000-8000-000000000002', 'data_domain', 'http://demo.ontos.app/concepts#FinancialDomain', 'Financial Domain', 'system@demo', NOW()),
('01500003-0000-4000-8000-000000000003', '00000003-0000-4000-8000-000000000003', 'data_domain', 'http://demo.ontos.app/concepts#SalesDomain', 'Sales Domain', 'system@demo', NOW()),
('01500004-0000-4000-8000-000000000004', '00000004-0000-4000-8000-000000000004', 'data_domain', 'http://demo.ontos.app/concepts#MarketingDomain', 'Marketing Domain', 'system@demo', NOW()),
('01500005-0000-4000-8000-000000000005', '00000005-0000-4000-8000-000000000005', 'data_domain', 'http://demo.ontos.app/concepts#RetailDomain', 'Retail Domain', 'system@demo', NOW()),
('01500006-0000-4000-8000-000000000006', '00000008-0000-4000-8000-000000000008', 'data_domain', 'http://demo.ontos.app/concepts#ProductDomain', 'Product Domain', 'system@demo', NOW()),
('01500007-0000-4000-8000-000000000007', '00000009-0000-4000-8000-000000000009', 'data_domain', 'http://demo.ontos.app/concepts#EmployeeDomain', 'Employee Domain', 'system@demo', NOW()),

-- Data Products (link to demo.ontos.app concepts)
('01500008-0000-4000-8000-000000000008', '00700001-0000-4000-8000-000000000001', 'data_product', 'http://demo.ontos.app/concepts#Sale', 'Sale', 'system@demo', NOW()),
('01500009-0000-4000-8000-000000000009', '00700002-0000-4000-8000-000000000002', 'data_product', 'http://demo.ontos.app/concepts#Transaction', 'Transaction', 'system@demo', NOW()),
('0150000a-0000-4000-8000-000000000010', '00700006-0000-4000-8000-000000000006', 'data_product', 'http://demo.ontos.app/concepts#Customer', 'Customer', 'system@demo', NOW()),
('0150000b-0000-4000-8000-000000000011', '00700007-0000-4000-8000-000000000007', 'data_product', 'http://demo.ontos.app/concepts#Sale', 'Sale', 'system@demo', NOW()),
('0150000c-0000-4000-8000-000000000012', '00700004-0000-4000-8000-000000000004', 'data_product', 'http://demo.ontos.app/concepts#Inventory', 'Inventory', 'system@demo', NOW()),
('0150000d-0000-4000-8000-000000000013', '00700005-0000-4000-8000-000000000005', 'data_product', 'http://demo.ontos.app/concepts#Product', 'Product', 'system@demo', NOW()),

-- Data Contracts (link to demo.ontos.app glossary terms)
('0150000e-0000-4000-8000-000000000014', '00400001-0000-4000-8000-000000000001', 'data_contract', 'http://demo.ontos.app/glossary#Customer', 'Customer', 'system@demo', NOW()),
('0150000f-0000-4000-8000-000000000015', '00400001-0000-4000-8000-000000000001', 'data_contract', 'http://demo.ontos.app/glossary#PersonalData', 'Personal Data', 'system@demo', NOW()),
('01500010-0000-4000-8000-000000000016', '00400002-0000-4000-8000-000000000002', 'data_contract', 'http://demo.ontos.app/glossary#Product', 'Product', 'system@demo', NOW()),
('01500011-0000-4000-8000-000000000017', '00400002-0000-4000-8000-000000000002', 'data_contract', 'http://demo.ontos.app/glossary#Inventory', 'Inventory', 'system@demo', NOW()),
('01500012-0000-4000-8000-000000000018', '00400004-0000-4000-8000-000000000004', 'data_contract', 'http://demo.ontos.app/glossary#Device', 'Device', 'system@demo', NOW()),
('01500013-0000-4000-8000-000000000019', '00400004-0000-4000-8000-000000000004', 'data_contract', 'http://demo.ontos.app/glossary#Telemetry', 'Telemetry', 'system@demo', NOW()),
('01500014-0000-4000-8000-000000000020', '00400006-0000-4000-8000-000000000006', 'data_contract', 'http://demo.ontos.app/glossary#Transaction', 'Transaction', 'system@demo', NOW()),
('01500015-0000-4000-8000-000000000021', '00400006-0000-4000-8000-000000000006', 'data_contract', 'http://demo.ontos.app/glossary#FinancialRecord', 'Financial Record', 'system@demo', NOW()),

-- Schema Objects - use entity_id = contractId#schemaName, entity_type = data_contract_schema
-- Customer Data Contract (00400001...) schemas: customers, customer_preferences, customer_addresses
('01500016-0000-4000-8000-000000000022', '00400001-0000-4000-8000-000000000001#customers', 'data_contract_schema', 'http://demo.ontos.app/glossary#CustomerProfile', 'Customer Profile', 'system@demo', NOW()),
('01500017-0000-4000-8000-000000000023', '00400001-0000-4000-8000-000000000001#customers', 'data_contract_schema', 'http://demo.ontos.app/glossary#MasterData', 'Master Data', 'system@demo', NOW()),
('01500018-0000-4000-8000-000000000024', '00400001-0000-4000-8000-000000000001#customer_preferences', 'data_contract_schema', 'http://demo.ontos.app/glossary#CustomerPreference', 'Customer Preference', 'system@demo', NOW()),
('01500019-0000-4000-8000-000000000025', '00400001-0000-4000-8000-000000000001#customer_addresses', 'data_contract_schema', 'http://demo.ontos.app/glossary#Address', 'Address', 'system@demo', NOW()),
('0150001a-0000-4000-8000-000000000026', '00400001-0000-4000-8000-000000000001#customer_addresses', 'data_contract_schema', 'http://demo.ontos.app/glossary#ContactInformation', 'Contact Information', 'system@demo', NOW()),
-- IoT Device Registry Contract (00400004...) schemas: devices, sensor_readings, device_events
('0150001b-0000-4000-8000-000000000027', '00400004-0000-4000-8000-000000000004#devices', 'data_contract_schema', 'http://demo.ontos.app/glossary#IoTDevice', 'IoT Device', 'system@demo', NOW()),
('0150001c-0000-4000-8000-000000000028', '00400004-0000-4000-8000-000000000004#devices', 'data_contract_schema', 'http://demo.ontos.app/glossary#AssetRegistry', 'Asset Registry', 'system@demo', NOW()),
('0150001d-0000-4000-8000-000000000029', '00400004-0000-4000-8000-000000000004#sensor_readings', 'data_contract_schema', 'http://demo.ontos.app/glossary#SensorReading', 'Sensor Reading', 'system@demo', NOW()),
('0150001e-0000-4000-8000-000000000030', '00400004-0000-4000-8000-000000000004#device_events', 'data_contract_schema', 'http://demo.ontos.app/glossary#DeviceEvent', 'Device Event', 'system@demo', NOW()),
('0150001f-0000-4000-8000-000000000031', '00400004-0000-4000-8000-000000000004#device_events', 'data_contract_schema', 'http://demo.ontos.app/glossary#Alert', 'Alert', 'system@demo', NOW()),

-- Schema Properties - use entity_id = contractId#schemaName#propertyName, entity_type = data_contract_property
-- Customer Data Contract > customers schema properties
('01500020-0000-4000-8000-000000000032', '00400001-0000-4000-8000-000000000001#customers#customer_id', 'data_contract_property', 'http://demo.ontos.app/glossary#CustomerId', 'customerId', 'system@demo', NOW()),
('01500021-0000-4000-8000-000000000033', '00400001-0000-4000-8000-000000000001#customers#customer_id', 'data_contract_property', 'http://demo.ontos.app/glossary#UniqueIdentifier', 'Unique Identifier', 'system@demo', NOW()),
('01500022-0000-4000-8000-000000000034', '00400001-0000-4000-8000-000000000001#customers#email', 'data_contract_property', 'http://demo.ontos.app/glossary#EmailAddress', 'emailAddress', 'system@demo', NOW()),
('01500023-0000-4000-8000-000000000035', '00400001-0000-4000-8000-000000000001#customers#email', 'data_contract_property', 'http://demo.ontos.app/glossary#PII', 'PII', 'system@demo', NOW()),
('01500024-0000-4000-8000-000000000036', '00400001-0000-4000-8000-000000000001#customers#first_name', 'data_contract_property', 'http://demo.ontos.app/glossary#FirstName', 'firstName', 'system@demo', NOW()),
('01500025-0000-4000-8000-000000000037', '00400001-0000-4000-8000-000000000001#customers#last_name', 'data_contract_property', 'http://demo.ontos.app/glossary#LastName', 'lastName', 'system@demo', NOW()),
('01500026-0000-4000-8000-000000000038', '00400001-0000-4000-8000-000000000001#customers#date_of_birth', 'data_contract_property', 'http://demo.ontos.app/glossary#DateOfBirth', 'dateOfBirth', 'system@demo', NOW()),
('01500027-0000-4000-8000-000000000039', '00400001-0000-4000-8000-000000000001#customers#phone_number', 'data_contract_property', 'http://demo.ontos.app/glossary#PhoneNumber', 'phoneNumber', 'system@demo', NOW()),
('01500028-0000-4000-8000-000000000040', '00400001-0000-4000-8000-000000000001#customers#country_code', 'data_contract_property', 'http://demo.ontos.app/glossary#CountryCode', 'countryCode', 'system@demo', NOW()),
('01500029-0000-4000-8000-000000000041', '00400001-0000-4000-8000-000000000001#customers#account_status', 'data_contract_property', 'http://demo.ontos.app/glossary#AccountStatus', 'accountStatus', 'system@demo', NOW()),
-- IoT Device Registry Contract > devices schema properties
('0150002a-0000-4000-8000-000000000042', '00400004-0000-4000-8000-000000000004#devices#device_id', 'data_contract_property', 'http://demo.ontos.app/glossary#DeviceId', 'deviceId', 'system@demo', NOW()),
('0150002b-0000-4000-8000-000000000043', '00400004-0000-4000-8000-000000000004#devices#device_type', 'data_contract_property', 'http://demo.ontos.app/glossary#DeviceType', 'deviceType', 'system@demo', NOW()),
('0150002c-0000-4000-8000-000000000044', '00400004-0000-4000-8000-000000000004#devices#status', 'data_contract_property', 'http://demo.ontos.app/glossary#DeviceStatus', 'deviceStatus', 'system@demo', NOW()),

-- Datasets (link to demo.ontos.app concepts) — entity_type='Dataset' (asset-backed)
('0150002d-0000-4000-8000-000000000045', '02100001-0000-4000-8000-000000000001', 'Dataset', 'http://demo.ontos.app/concepts#CustomerDomain', 'Customer Domain', 'system@demo', NOW()),
('0150002e-0000-4000-8000-000000000046', '02100001-0000-4000-8000-000000000001', 'Dataset', 'http://demo.ontos.app/glossary#CustomerProfile', 'Customer Profile', 'system@demo', NOW()),
('0150002f-0000-4000-8000-000000000047', '02100004-0000-4000-8000-000000000004', 'Dataset', 'http://demo.ontos.app/glossary#IoTDevice', 'IoT Device', 'system@demo', NOW()),
('01500030-0000-4000-8000-000000000048', '02100005-0000-4000-8000-000000000005', 'Dataset', 'http://demo.ontos.app/glossary#Telemetry', 'Telemetry', 'system@demo', NOW()),
('01500031-0000-4000-8000-000000000049', '02100007-0000-4000-8000-000000000007', 'Dataset', 'http://demo.ontos.app/concepts#SalesDomain', 'Sales Domain', 'system@demo', NOW()),
('01500032-0000-4000-8000-000000000050', '02100007-0000-4000-8000-000000000007', 'Dataset', 'http://demo.ontos.app/concepts#RetailDomain', 'Retail Domain', 'system@demo', NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 11. METADATA (Notes, Links, Documents)
-- ============================================================================

-- Rich Text Notes (type=016)
INSERT INTO rich_text_metadata (id, entity_id, entity_type, title, short_description, content_markdown, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01600001-0000-4000-8000-000000000001', '00000004-0000-4000-8000-000000000004', 'data_domain', 'About the Marketing Domain', 'Scope, key concepts, and stakeholders for Marketing.', E'# Marketing Domain\n\nThe Marketing domain focuses on customer engagement, personalization, and campaign\neffectiveness. Typical assets include customer profiles, segmentation models,\npropensity and uplift scores, and activation datasets for outbound channels.\n\nCore concepts often used across data products:\n- Customer identity and householding\n- Consent and channel preferences\n- Campaign taxonomy and lifecycle\n- Response and attribution measures\n\nGovernance highlights include consent management and PII handling standards.', false, 50, true, 'system@demo', NOW(), NOW()),
('01600002-0000-4000-8000-000000000002', '00700006-0000-4000-8000-000000000006', 'data_product', 'Overview', 'What this product offers and who should use it.', E'# Customer Marketing Recommendations v1\n\nThis product provides targeted customer recommendations to support lifecycle and\npromotional campaigns. It merges prepared sales signals, customer profile\nattributes, and model outputs to produce actionable target lists.\n\nService levels and ownership:\n- Data Owner: Marketing Team\n- SLOs: Daily build by 06:00 UTC; refresh-on-demand supported\n- Data Quality: Monitored via rules on coverage, deduplication, and eligibility', false, 50, true, 'system@demo', NOW(), NOW()),
('01600003-0000-4000-8000-000000000003', '00700006-0000-4000-8000-000000000006', 'data_product', 'Architecture & Flow', 'Inputs, transformations, and outputs at a glance.', E'## Architecture and Flow\n\nInputs include prepared sales transactions and CRM profile data. Core steps:\n1. Feature assembly and feature freshness checks\n2. Inference using latest recommendation model\n3. Eligibility filtering (consent, channel, recency)\n4. Packaging outputs for activation channels', false, 50, true, 'system@demo', NOW(), NOW()),
-- Dataset metadata (entity_type='Dataset' — asset-backed)
('01600004-0000-4000-8000-000000000004', '02100001-0000-4000-8000-000000000001', 'Dataset', 'Customer Profile Dataset', 'Production-ready customer profile data.', E'# Customer Profile Dataset\n\nThis dataset contains production customer profile data consolidated from multiple source systems.\n\n## Key Features\n- Unified customer identifiers across channels\n- Enriched with demographic attributes\n- Daily refresh cycle\n- PII masking applied\n\n## Usage Notes\nConsumers should use the `customer_id` column as the primary key for joins.', false, 50, true, 'system@demo', NOW(), NOW()),
('01600005-0000-4000-8000-000000000005', '02100005-0000-4000-8000-000000000005', 'Dataset', 'IoT Telemetry Overview', 'Real-time telemetry from IoT devices.', E'# IoT Device Telemetry\n\nThis dataset captures streaming telemetry from connected IoT devices.\n\n## Data Characteristics\n- Near real-time ingestion (latency < 5s)\n- Partitioned by device_id and event_date\n- Retention policy: 90 days hot, 2 years cold storage\n\n## Schema Notes\nThe `payload` column contains device-specific JSON data.', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;

-- Data Product rich text notes
INSERT INTO rich_text_metadata (id, entity_id, entity_type, title, short_description, content_markdown, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01600006-0000-4000-8000-000000000006', '00700001-0000-4000-8000-000000000001', 'data_product', 'Overview', 'Real-time POS event streaming for retail analytics.', E'# POS Transaction Stream v1\n\nReal-time point-of-sale transaction feed from all retail locations. Provides sub-second\nevent streaming of every transaction for inventory, analytics, and fraud detection.\n\n## Key Capabilities\n- Sub-second latency from POS terminal to Kafka topic\n- Guaranteed at-least-once delivery with idempotency keys\n- Schema evolution support via Avro with registry\n\n## Service Levels\n- Data Owner: Store Operations Team\n- SLO: 99.9% uptime, p99 latency < 500ms\n- Recovery: Replay from source within 4 hours', false, 50, true, 'system@demo', NOW(), NOW()),
('01600007-0000-4000-8000-000000000007', '00700002-0000-4000-8000-000000000002', 'data_product', 'Overview', 'Cleaned and enriched sales data for analytics.', E'# Prepared Sales Transactions v1\n\nCleaned and enriched sales transaction data combining POS events with product master,\nstore hierarchy, and promotion calendars. Foundation for all downstream analytics.\n\n## Transformations Applied\n- Deduplication and late-arrival handling\n- Product hierarchy enrichment (SKU to Category to Department)\n- Promotion matching and discount attribution\n- Currency normalization to USD\n\n## Refresh Schedule\nDaily batch by 04:00 UTC; intraday micro-batch every 15 minutes.', false, 50, true, 'system@demo', NOW(), NOW()),
('01600008-0000-4000-8000-000000000008', '00700003-0000-4000-8000-000000000003', 'data_product', 'Overview', 'ML-generated demand forecasts for replenishment.', E'# Demand Forecast Model Output v1\n\nML-generated demand forecasts at SKU x Store x Day granularity using a gradient-boosted\ntree ensemble trained on 3 years of sales history with seasonal decomposition.\n\n## Model Details\n- Algorithm: LightGBM with custom loss function\n- Features: Sales history, promotions, weather, events, holidays\n- Horizon: 14-day rolling forecast, updated daily\n- Accuracy: MAPE ~12%% (grocery), ~18%% (general merchandise)\n\n## Consuming This Product\nUse the `forecast_date` and `confidence_interval` columns to assess prediction\nreliability before automated ordering.', false, 50, true, 'system@demo', NOW(), NOW()),
('01600009-0000-4000-8000-000000000009', '00700004-0000-4000-8000-000000000004', 'data_product', 'Overview', 'Replenishment and rebalancing recommendations.', E'# Inventory Optimization Recommendations v1\n\nActionable inventory replenishment and rebalancing recommendations generated by\ncombining demand forecasts with current stock levels, lead times, and safety stock policies.\n\n## Outputs\n- Daily replenishment orders by DC-to-Store lane\n- Rebalancing suggestions between stores in same region\n- Safety stock adjustment recommendations (quarterly)\n\n## Integration Points\n- ERP: SAP MM module for PO generation\n- WMS: Warehouse task creation via API\n- Planning: Weekly review dashboard for planners', false, 50, true, 'system@demo', NOW(), NOW()),
('0160000a-0000-4000-8000-000000000010', '00700005-0000-4000-8000-000000000005', 'data_product', 'Overview', 'Elasticity-based pricing recommendations.', E'# Price Optimization Model Output v1\n\nElasticity-based pricing recommendations for regular and promotional prices. Uses a\ndemand-price response model calibrated weekly per category-market combination.\n\n## Methodology\n- Base price elasticity estimation using log-log regression\n- Cross-elasticity for substitute SKUs within category\n- Promotional lift curves from historical A/B tests\n- Margin and revenue optimization under business constraints\n\n## Guardrails\nAll recommendations are subject to competitive price floors, MAP policies, and\npromotional calendar constraints before execution.', false, 50, true, 'system@demo', NOW(), NOW()),
('0160000b-0000-4000-8000-000000000011', '00700007-0000-4000-8000-000000000007', 'data_product', 'Overview', 'Pre-aggregated KPIs for executive dashboards.', E'# Retail Performance Dashboard Data v1\n\nPre-aggregated KPI dataset powering the executive retail performance dashboards.\nCombines sales, inventory, labor, and customer metrics into a single star schema.\n\n## KPIs Included\n- Sales: Revenue, units, ATV, UPT, conversion rate\n- Inventory: GMROI, weeks of supply, sell-through, shrink\n- Labor: Sales per labor hour, schedule adherence\n- Customer: NPS, repeat rate, basket composition\n\n## Refresh and Access\nRefreshed daily by 06:00 UTC. Available via SQL endpoint and Databricks dashboard.', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- Link Metadata (type=017)
INSERT INTO link_metadata (id, entity_id, entity_type, title, short_description, url, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01700001-0000-4000-8000-000000000001', '00000004-0000-4000-8000-000000000004', 'data_domain', 'Domain Operating Model', 'Roles, responsibilities, workflows.', 'https://wiki.example.com/domains/marketing/operating-model', false, 50, true, 'system@demo', NOW(), NOW()),
('01700002-0000-4000-8000-000000000002', '00700006-0000-4000-8000-000000000006', 'data_product', 'Runbook', 'Operational procedures and on-call.', 'https://runbooks.example.com/marketing/customer-recs-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700003-0000-4000-8000-000000000003', '00700006-0000-4000-8000-000000000006', 'data_product', 'Dashboard', 'Quality and volume tracking.', 'https://bi.example.com/dashboards/customer-recs-quality', false, 50, true, 'system@demo', NOW(), NOW()),
('01700004-0000-4000-8000-000000000004', '00700006-0000-4000-8000-000000000006', 'data_product', 'Design Doc', 'Detailed design and decisions.', 'https://docs.example.com/design/customer-recs-v1', false, 50, true, 'system@demo', NOW(), NOW()),
-- Dataset links (entity_type='Dataset' — asset-backed)
('01700005-0000-4000-8000-000000000005', '02100001-0000-4000-8000-000000000001', 'Dataset', 'Data Catalog Entry', 'View in Unity Catalog.', 'https://catalog.example.com/prod/customer/profiles', false, 50, true, 'system@demo', NOW(), NOW()),
('01700006-0000-4000-8000-000000000006', '02100001-0000-4000-8000-000000000001', 'Dataset', 'Data Lineage', 'Explore upstream and downstream dependencies.', 'https://lineage.example.com/datasets/customer-profile-prod', false, 50, true, 'system@demo', NOW(), NOW()),
('01700007-0000-4000-8000-000000000007', '02100005-0000-4000-8000-000000000005', 'Dataset', 'IoT Device Dashboard', 'Real-time device monitoring.', 'https://iot.example.com/dashboards/telemetry', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;

-- Data Product link metadata
INSERT INTO link_metadata (id, entity_id, entity_type, title, short_description, url, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01700008-0000-4000-8000-000000000008', '00700001-0000-4000-8000-000000000001', 'data_product', 'Runbook', 'Operational procedures and incident response.', 'https://runbooks.example.com/retail/pos-stream-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700009-0000-4000-8000-000000000009', '00700001-0000-4000-8000-000000000001', 'data_product', 'Stream Health Dashboard', 'Kafka lag and throughput monitoring.', 'https://bi.example.com/dashboards/pos-stream-health', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000a-0000-4000-8000-000000000010', '00700002-0000-4000-8000-000000000002', 'data_product', 'Runbook', 'Operational procedures and on-call.', 'https://runbooks.example.com/retail/sales-prep-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000b-0000-4000-8000-000000000011', '00700002-0000-4000-8000-000000000002', 'data_product', 'Data Quality Dashboard', 'Quality metrics and anomaly tracking.', 'https://bi.example.com/dashboards/sales-data-quality', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000c-0000-4000-8000-000000000012', '00700003-0000-4000-8000-000000000003', 'data_product', 'Model Card', 'Model training, features, and performance.', 'https://mlflow.example.com/models/demand-forecast-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000d-0000-4000-8000-000000000013', '00700003-0000-4000-8000-000000000003', 'data_product', 'Forecast Accuracy Dashboard', 'MAPE and bias tracking by category.', 'https://bi.example.com/dashboards/forecast-accuracy', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000e-0000-4000-8000-000000000014', '00700004-0000-4000-8000-000000000004', 'data_product', 'Runbook', 'Replenishment pipeline operations.', 'https://runbooks.example.com/supply-chain/inventory-opt-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000f-0000-4000-8000-000000000015', '00700004-0000-4000-8000-000000000004', 'data_product', 'Optimization Dashboard', 'Fill rate and stockout metrics.', 'https://bi.example.com/dashboards/inventory-optimization', false, 50, true, 'system@demo', NOW(), NOW()),
('01700010-0000-4000-8000-000000000016', '00700005-0000-4000-8000-000000000005', 'data_product', 'Model Card', 'Elasticity model documentation.', 'https://mlflow.example.com/models/price-optimization-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700011-0000-4000-8000-000000000017', '00700005-0000-4000-8000-000000000005', 'data_product', 'Pricing Strategy Wiki', 'Business rules and guardrails.', 'https://wiki.example.com/pricing/strategy-and-constraints', false, 50, true, 'system@demo', NOW(), NOW()),
('01700012-0000-4000-8000-000000000018', '00700007-0000-4000-8000-000000000007', 'data_product', 'Executive Dashboard', 'Live retail performance view.', 'https://bi.example.com/dashboards/retail-performance-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700013-0000-4000-8000-000000000019', '00700007-0000-4000-8000-000000000007', 'data_product', 'Data Catalog Entry', 'View in Unity Catalog.', 'https://catalog.example.com/prod/analytics/retail-performance', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- Document Metadata (type=018)
INSERT INTO document_metadata (id, entity_id, entity_type, title, short_description, original_filename, storage_path, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01800001-0000-4000-8000-000000000001', '00700006-0000-4000-8000-000000000006', 'data_product', 'Overview', 'Product overview visual.', 'customer_recs_overview.svg', 'images/customer_marketing_recos/overview.svg', false, 50, true, 'system@demo', NOW(), NOW()),
('01800002-0000-4000-8000-000000000002', '00700006-0000-4000-8000-000000000006', 'data_product', 'Data Flow', 'High-level data flow.', 'customer_recs_flow.svg', 'images/customer_marketing_recos/flow.svg', false, 50, true, 'system@demo', NOW(), NOW()),
-- Dataset documents (entity_type='Dataset' — asset-backed)
('01800003-0000-4000-8000-000000000003', '02100001-0000-4000-8000-000000000001', 'Dataset', 'ERD Diagram', 'Entity relationship diagram.', 'customer_profile_erd.svg', 'images/datasets/customer_profile_erd.svg', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 12. MDM CONFIGURATIONS (type=019)
-- ============================================================================
-- MDM configs link master contracts to source contracts for entity matching
-- Columns: id, master_contract_id, name, description, entity_type, status, matching_rules, survivorship_rules, project_id, created_at, updated_at, created_by, updated_by

INSERT INTO mdm_configs (id, master_contract_id, name, description, entity_type, status, matching_rules, survivorship_rules, project_id, created_by, updated_by, created_at, updated_at) VALUES
-- Customer MDM: Customer Data Contract as master
('01900001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'Customer Master Data', 'Unified customer master record from CRM and IoT device registrations', 'customer', 'active', 
'[{"name": "email_exact", "type": "deterministic", "fields": ["email"], "weight": 1.0, "threshold": 1.0}, {"name": "name_fuzzy", "type": "probabilistic", "fields": ["first_name", "last_name"], "weight": 0.6, "threshold": 0.85, "algorithm": "jaro_winkler"}, {"name": "phone_match", "type": "deterministic", "fields": ["phone_number"], "weight": 0.8, "threshold": 1.0}]',
'[{"field": "email", "strategy": "most_recent"}, {"field": "phone_number", "strategy": "most_complete"}, {"field": "first_name", "strategy": "source_priority", "priority": ["crm", "iot"]}, {"field": "last_name", "strategy": "source_priority", "priority": ["crm", "iot"]}]',
'00300001-0000-4000-8000-000000000001', 'system@demo', 'system@demo', NOW(), NOW()),

-- Product MDM: Product Catalog Contract as master
('01900002-0000-4000-8000-000000000002', '00400002-0000-4000-8000-000000000002', 'Product Master Data', 'Consolidated product catalog from multiple inventory sources', 'product', 'active',
'[{"name": "sku_exact", "type": "deterministic", "fields": ["sku"], "weight": 1.0, "threshold": 1.0}, {"name": "name_fuzzy", "type": "probabilistic", "fields": ["product_name"], "weight": 0.7, "threshold": 0.90, "algorithm": "levenshtein"}, {"name": "upc_exact", "type": "deterministic", "fields": ["upc"], "weight": 0.9, "threshold": 1.0}]',
'[{"field": "product_name", "strategy": "most_complete"}, {"field": "price", "strategy": "most_recent"}, {"field": "inventory_count", "strategy": "source_wins"}]',
'00300004-0000-4000-8000-000000000004', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 12b. MDM SOURCE LINKS (type=01a)
-- ============================================================================
-- Links source contracts to MDM configurations
-- Columns: id, config_id, source_contract_id, key_column, column_mapping, priority, status, last_sync_at, created_at, updated_at

INSERT INTO mdm_source_links (id, config_id, source_contract_id, key_column, column_mapping, priority, status, last_sync_at, created_at, updated_at) VALUES
-- Customer MDM sources
('01a00001-0000-4000-8000-000000000001', '01900001-0000-4000-8000-000000000001', '00400004-0000-4000-8000-000000000004', 'device_id',
'{"device_id": "customer_id", "device_serial": "external_id", "status": "account_status"}',
2, 'active', NOW() - INTERVAL '2 hours', NOW(), NOW()),

-- Product MDM sources
('01a00002-0000-4000-8000-000000000002', '01900002-0000-4000-8000-000000000002', '00400007-0000-4000-8000-000000000007', 'sku',
'{"sku": "product_id", "item_name": "product_name", "quantity": "inventory_count", "warehouse_id": "location_id"}',
1, 'active', NOW() - INTERVAL '4 hours', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 12c. MDM MATCH RUNS (type=01b)
-- ============================================================================
-- Tracks MDM matching job runs
-- Columns: id, config_id, source_link_id, status, databricks_run_id, total_source_records, total_master_records, matches_found, new_records, started_at, completed_at, error_message, triggered_by

INSERT INTO mdm_match_runs (id, config_id, source_link_id, status, databricks_run_id, total_source_records, total_master_records, matches_found, new_records, started_at, completed_at, error_message, triggered_by) VALUES
-- Customer MDM run (completed successfully)
('01b00001-0000-4000-8000-000000000001', '01900001-0000-4000-8000-000000000001', '01a00001-0000-4000-8000-000000000001', 'completed', 'run-demo-cust-001', 1500, 10000, 1423, 77, NOW() - INTERVAL '3 hours', NOW() - INTERVAL '2 hours 45 minutes', NULL, 'system@demo'),

-- Customer MDM run (older, also completed)
('01b00002-0000-4000-8000-000000000002', '01900001-0000-4000-8000-000000000001', '01a00001-0000-4000-8000-000000000001', 'completed', 'run-demo-cust-002', 1200, 9500, 1180, 20, NOW() - INTERVAL '1 day 3 hours', NOW() - INTERVAL '1 day 2 hours 50 minutes', NULL, 'data.engineer@example.com'),

-- Product MDM run (completed)
('01b00003-0000-4000-8000-000000000003', '01900002-0000-4000-8000-000000000002', '01a00002-0000-4000-8000-000000000002', 'completed', 'run-demo-prod-001', 800, 5000, 750, 50, NOW() - INTERVAL '5 hours', NOW() - INTERVAL '4 hours 40 minutes', NULL, 'system@demo'),

-- Product MDM run (failed example)
('01b00004-0000-4000-8000-000000000004', '01900002-0000-4000-8000-000000000002', '01a00002-0000-4000-8000-000000000002', 'failed', 'run-demo-prod-002', 0, 0, 0, 0, NOW() - INTERVAL '6 hours', NOW() - INTERVAL '5 hours 55 minutes', 'Source table not accessible: permission denied on catalog.schema.inventory', 'ops-lead@example.com')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 12d. MDM MATCH CANDIDATES (type=01c)
-- ============================================================================
-- Individual match candidates awaiting review or processed
-- Columns: id, run_id, master_record_id, source_record_id, source_contract_id, confidence_score, match_type, matched_fields, review_request_id, reviewed_asset_id, status, master_record_data, source_record_data, merged_record_data, reviewed_at, reviewed_by, merged_at

INSERT INTO mdm_match_candidates (id, run_id, master_record_id, source_record_id, source_contract_id, confidence_score, match_type, matched_fields, status, master_record_data, source_record_data) VALUES
-- Customer matches from run 01b00001
('01c00001-0000-4000-8000-000000000001', '01b00001-0000-4000-8000-000000000001', 'CUST-M-001', 'DEV-S-001', '00400004-0000-4000-8000-000000000004', 0.98, 'exact', 
'["email", "phone_number"]',
'approved', 
'{"customer_id": "CUST-M-001", "email": "john.smith@example.com", "first_name": "John", "last_name": "Smith", "phone_number": "+1-555-123-4567"}',
'{"device_id": "DEV-S-001", "device_serial": "IOT-2024-001", "status": "active"}'),

('01c00002-0000-4000-8000-000000000002', '01b00001-0000-4000-8000-000000000001', 'CUST-M-002', 'DEV-S-002', '00400004-0000-4000-8000-000000000004', 0.87, 'fuzzy',
'["first_name", "last_name"]',
'pending',
'{"customer_id": "CUST-M-002", "email": "jane.doe@example.com", "first_name": "Jane", "last_name": "Doe", "phone_number": "+1-555-987-6543"}',
'{"device_id": "DEV-S-002", "device_serial": "IOT-2024-002", "status": "active"}'),

('01c00003-0000-4000-8000-000000000003', '01b00001-0000-4000-8000-000000000001', NULL, 'DEV-S-003', '00400004-0000-4000-8000-000000000004', 0.0, 'new',
'[]',
'pending',
NULL,
'{"device_id": "DEV-S-003", "device_serial": "IOT-2024-003", "status": "inactive"}'),

-- Product matches from run 01b00003
('01c00004-0000-4000-8000-000000000004', '01b00003-0000-4000-8000-000000000003', 'PROD-M-001', 'INV-S-001', '00400007-0000-4000-8000-000000000007', 1.0, 'exact',
'["sku"]',
'merged',
'{"product_id": "PROD-M-001", "product_name": "Widget Pro", "sku": "WGT-PRO-001", "price": 29.99}',
'{"sku": "WGT-PRO-001", "item_name": "Widget Professional", "quantity": 150, "warehouse_id": "WH-EAST-01"}'),

('01c00005-0000-4000-8000-000000000005', '01b00003-0000-4000-8000-000000000003', 'PROD-M-002', 'INV-S-002', '00400007-0000-4000-8000-000000000007', 0.91, 'fuzzy',
'["product_name"]',
'rejected',
'{"product_id": "PROD-M-002", "product_name": "Gadget Deluxe", "sku": "GDG-DLX-002", "price": 49.99}',
'{"sku": "GDG-DELUXE-02", "item_name": "Gadget De Luxe", "quantity": 75, "warehouse_id": "WH-WEST-01"}')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 13. AUTHORITATIVE DEFINITIONS (Business Term Assignments)
-- ============================================================================

-- 13a. Contract-level authoritative definitions (type=01d)
-- Links business terms to entire data contracts
INSERT INTO data_contract_authoritative_definitions (id, contract_id, url, type) VALUES
-- Customer Data Contract business terms
('01d00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'http://glossary.example.com/terms/Customer', 'businessTerm'),
('01d00002-0000-4000-8000-000000000002', '00400001-0000-4000-8000-000000000001', 'http://glossary.example.com/terms/PersonalData', 'businessTerm'),
('01d00003-0000-4000-8000-000000000003', '00400001-0000-4000-8000-000000000001', 'https://gdpr.eu/article-4/', 'regulation'),

-- Product Catalog Contract business terms
('01d00004-0000-4000-8000-000000000004', '00400002-0000-4000-8000-000000000002', 'http://glossary.example.com/terms/Product', 'businessTerm'),
('01d00005-0000-4000-8000-000000000005', '00400002-0000-4000-8000-000000000002', 'http://glossary.example.com/terms/Inventory', 'businessTerm'),

-- IoT Device Data Contract business terms
('01d00006-0000-4000-8000-000000000006', '00400004-0000-4000-8000-000000000004', 'http://glossary.example.com/terms/Device', 'businessTerm'),
('01d00007-0000-4000-8000-000000000007', '00400004-0000-4000-8000-000000000004', 'http://glossary.example.com/terms/Telemetry', 'businessTerm'),

-- Financial Transactions Contract
('01d00008-0000-4000-8000-000000000008', '00400006-0000-4000-8000-000000000006', 'http://glossary.example.com/terms/Transaction', 'businessTerm'),
('01d00009-0000-4000-8000-000000000009', '00400006-0000-4000-8000-000000000006', 'http://glossary.example.com/terms/FinancialRecord', 'businessTerm')

ON CONFLICT (id) DO NOTHING;


-- 13b. Schema object-level authoritative definitions (type=01e)
-- Links business terms to schema objects (tables/views)
INSERT INTO data_contract_schema_object_authoritative_definitions (id, schema_object_id, url, type) VALUES
-- customers table (00500001)
('01e00001-0000-4000-8000-000000000001', '00500001-0000-4000-8000-000000000001', 'http://glossary.example.com/terms/CustomerProfile', 'businessTerm'),
('01e00002-0000-4000-8000-000000000002', '00500001-0000-4000-8000-000000000001', 'http://glossary.example.com/terms/MasterData', 'businessTerm'),

-- customer_preferences table (00500002)
('01e00003-0000-4000-8000-000000000003', '00500002-0000-4000-8000-000000000002', 'http://glossary.example.com/terms/CustomerPreference', 'businessTerm'),

-- customer_addresses table (00500003)
('01e00004-0000-4000-8000-000000000004', '00500003-0000-4000-8000-000000000003', 'http://glossary.example.com/terms/Address', 'businessTerm'),
('01e00005-0000-4000-8000-000000000005', '00500003-0000-4000-8000-000000000003', 'http://glossary.example.com/terms/ContactInformation', 'businessTerm'),

-- devices table (00500004)
('01e00006-0000-4000-8000-000000000006', '00500004-0000-4000-8000-000000000004', 'http://glossary.example.com/terms/IoTDevice', 'businessTerm'),
('01e00007-0000-4000-8000-000000000007', '00500004-0000-4000-8000-000000000004', 'http://glossary.example.com/terms/AssetRegistry', 'businessTerm'),

-- device_telemetry table (00500005)
('01e00008-0000-4000-8000-000000000008', '00500005-0000-4000-8000-000000000005', 'http://glossary.example.com/terms/SensorReading', 'businessTerm'),

-- device_events table (00500006)
('01e00009-0000-4000-8000-000000000009', '00500006-0000-4000-8000-000000000006', 'http://glossary.example.com/terms/DeviceEvent', 'businessTerm'),
('01e0000a-0000-4000-8000-000000000010', '00500006-0000-4000-8000-000000000006', 'http://glossary.example.com/terms/Alert', 'businessTerm')

ON CONFLICT (id) DO NOTHING;


-- 13c. Schema property-level authoritative definitions (type=01f)
-- Links business terms to individual columns/properties
INSERT INTO data_contract_schema_property_authoritative_definitions (id, property_id, url, type) VALUES
-- customers.customer_id (00600001)
('01f00001-0000-4000-8000-000000000001', '00600001-0000-4000-8000-000000000001', 'http://glossary.example.com/terms/CustomerId', 'businessTerm'),
('01f00002-0000-4000-8000-000000000002', '00600001-0000-4000-8000-000000000001', 'http://glossary.example.com/terms/UniqueIdentifier', 'businessTerm'),

-- customers.email (00600002)
('01f00003-0000-4000-8000-000000000003', '00600002-0000-4000-8000-000000000002', 'http://glossary.example.com/terms/EmailAddress', 'businessTerm'),
('01f00004-0000-4000-8000-000000000004', '00600002-0000-4000-8000-000000000002', 'http://glossary.example.com/terms/PII', 'classification'),

-- customers.first_name (00600003)
('01f00005-0000-4000-8000-000000000005', '00600003-0000-4000-8000-000000000003', 'http://glossary.example.com/terms/FirstName', 'businessTerm'),
('01f00006-0000-4000-8000-000000000006', '00600003-0000-4000-8000-000000000003', 'http://glossary.example.com/terms/PersonalName', 'businessTerm'),

-- customers.last_name (00600004)
('01f00007-0000-4000-8000-000000000007', '00600004-0000-4000-8000-000000000004', 'http://glossary.example.com/terms/LastName', 'businessTerm'),
('01f00008-0000-4000-8000-000000000008', '00600004-0000-4000-8000-000000000004', 'http://glossary.example.com/terms/FamilyName', 'businessTerm'),

-- customers.date_of_birth (00600005)
('01f00009-0000-4000-8000-000000000009', '00600005-0000-4000-8000-000000000005', 'http://glossary.example.com/terms/DateOfBirth', 'businessTerm'),
('01f0000a-0000-4000-8000-000000000010', '00600005-0000-4000-8000-000000000005', 'http://glossary.example.com/terms/SensitivePII', 'classification'),

-- customers.phone_number (00600006)
('01f0000b-0000-4000-8000-000000000011', '00600006-0000-4000-8000-000000000006', 'http://glossary.example.com/terms/PhoneNumber', 'businessTerm'),
('01f0000c-0000-4000-8000-000000000012', '00600006-0000-4000-8000-000000000006', 'http://glossary.example.com/terms/ContactPhone', 'businessTerm'),

-- customers.country_code (00600007)
('01f0000d-0000-4000-8000-000000000013', '00600007-0000-4000-8000-000000000007', 'http://glossary.example.com/terms/CountryCode', 'businessTerm'),
('01f0000e-0000-4000-8000-000000000014', '00600007-0000-4000-8000-000000000007', 'https://www.iso.org/iso-3166-country-codes.html', 'standard'),

-- customers.account_status (00600009)
('01f0000f-0000-4000-8000-000000000015', '00600009-0000-4000-8000-000000000009', 'http://glossary.example.com/terms/AccountStatus', 'businessTerm'),

-- devices.device_id (0060000b)
('01f00010-0000-4000-8000-000000000016', '0060000b-0000-4000-8000-000000000011', 'http://glossary.example.com/terms/DeviceId', 'businessTerm'),
('01f00011-0000-4000-8000-000000000017', '0060000b-0000-4000-8000-000000000011', 'http://glossary.example.com/terms/AssetIdentifier', 'businessTerm'),

-- devices.device_type (0060000d)
('01f00012-0000-4000-8000-000000000018', '0060000d-0000-4000-8000-000000000013', 'http://glossary.example.com/terms/DeviceType', 'businessTerm'),
('01f00013-0000-4000-8000-000000000019', '0060000d-0000-4000-8000-000000000013', 'http://glossary.example.com/terms/IoTClassification', 'businessTerm'),

-- devices.status (0060000e)
('01f00014-0000-4000-8000-000000000020', '0060000e-0000-4000-8000-000000000014', 'http://glossary.example.com/terms/DeviceStatus', 'businessTerm'),
('01f00015-0000-4000-8000-000000000021', '0060000e-0000-4000-8000-000000000014', 'http://glossary.example.com/terms/OperationalState', 'businessTerm')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 14. DATA CONTRACT SERVERS
-- ============================================================================
-- Server definitions for contracts (needed for dataset instances)
-- Servers define where contract data can be physically implemented

INSERT INTO data_contract_servers (id, contract_id, server, type, description, environment) VALUES
-- Customer Data Contract servers
('srv00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'uc-dev-workspace', 'databricks', 'Development Unity Catalog workspace', 'dev'),
('srv00002-0000-4000-8000-000000000002', '00400001-0000-4000-8000-000000000001', 'uc-prod-workspace', 'databricks', 'Production Unity Catalog workspace', 'prod'),
('srv00003-0000-4000-8000-000000000003', '00400001-0000-4000-8000-000000000001', 'snowflake-analytics', 'snowflake', 'Snowflake analytics warehouse', 'prod'),

-- IoT Device Data Contract servers
('srv00004-0000-4000-8000-000000000004', '00400004-0000-4000-8000-000000000004', 'uc-iot-dev', 'databricks', 'IoT development environment', 'dev'),
('srv00005-0000-4000-8000-000000000005', '00400004-0000-4000-8000-000000000004', 'uc-iot-prod', 'databricks', 'IoT production environment', 'prod'),

-- Financial Transactions Contract servers
('srv00006-0000-4000-8000-000000000006', '00400006-0000-4000-8000-000000000006', 'finance-dev', 'databricks', 'Finance dev workspace', 'dev'),
('srv00007-0000-4000-8000-000000000007', '00400006-0000-4000-8000-000000000006', 'finance-prod', 'databricks', 'Finance production workspace', 'prod'),
('srv00008-0000-4000-8000-000000000008', '00400006-0000-4000-8000-000000000006', 'bq-finance-reporting', 'bigquery', 'BigQuery finance reporting', 'prod')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 15. DATASETS → ASSETS (type=021, migrated to asset system)
-- ============================================================================
-- Datasets are now stored as Asset rows with asset_type = 'Dataset'.
-- Custom properties are merged into the properties JSON.
-- IDs are preserved from the original dataset IDs for backward compatibility
-- with polymorphic references (semantic_links, metadata, tags).

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES
-- Customer datasets
('02100001-0000-4000-8000-000000000001', 'Customer Master Data',
 'Customer master data including profiles, preferences, and segmentation',
 (SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), NULL, NULL, NULL,
 '{"version": "1.0.0", "published": true, "contract_id": "00400001-0000-4000-8000-000000000001", "owner_team_id": "00100001-0000-4000-8000-000000000001", "project_id": "00300001-0000-4000-8000-000000000001", "data_classification": "confidential", "retention_days": "2555", "refresh_schedule": "daily"}',
 '["customer", "master-data", "pii"]', 'active', 'system@demo', NOW(), NOW()),

('02100002-0000-4000-8000-000000000002', 'Customer Engagement Analytics',
 'Customer engagement metrics and preferences aggregation',
 (SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), NULL, NULL, NULL,
 '{"version": "2.0.0", "published": false, "contract_id": "00400001-0000-4000-8000-000000000001", "owner_team_id": "00100001-0000-4000-8000-000000000001", "project_id": "00300001-0000-4000-8000-000000000001"}',
 '["customer", "analytics"]', 'active', 'system@demo', NOW(), NOW()),

('02100003-0000-4000-8000-000000000003', 'Customer Preferences',
 'Aggregated customer preferences across channels',
 (SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), NULL, NULL, NULL,
 '{"version": "1.0.0", "published": true, "contract_id": "00400001-0000-4000-8000-000000000001", "owner_team_id": "00100002-0000-4000-8000-000000000002", "project_id": "00300001-0000-4000-8000-000000000001"}',
 '["customer", "preferences"]', 'active', 'system@demo', NOW(), NOW()),

-- IoT datasets
('02100004-0000-4000-8000-000000000004', 'IoT Device Management',
 'Registry and management of all IoT devices and configurations',
 (SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), NULL, NULL, NULL,
 '{"version": "1.1.0", "published": true, "contract_id": "00400004-0000-4000-8000-000000000004", "owner_team_id": "00100003-0000-4000-8000-000000000003", "project_id": "00300003-0000-4000-8000-000000000003"}',
 '["iot", "devices"]', 'active', 'system@demo', NOW(), NOW()),

('02100005-0000-4000-8000-000000000005', 'IoT Telemetry',
 'Real-time and historical telemetry data from IoT devices',
 (SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), NULL, NULL, NULL,
 '{"version": "1.1.0", "published": true, "contract_id": "00400004-0000-4000-8000-000000000004", "owner_team_id": "00100003-0000-4000-8000-000000000003", "project_id": "00300003-0000-4000-8000-000000000003", "partition_by": "date", "retention_days": "730", "compression": "zstd"}',
 '["iot", "telemetry", "streaming"]', 'active', 'system@demo', NOW(), NOW()),

-- Financial datasets
('02100006-0000-4000-8000-000000000006', 'Financial Transactions',
 'Daily financial transactions for analytics and reporting',
 (SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), NULL, NULL, NULL,
 '{"version": "1.0.0-alpha", "published": false, "contract_id": "00400006-0000-4000-8000-000000000006", "owner_team_id": "00100004-0000-4000-8000-000000000004", "project_id": "00300002-0000-4000-8000-000000000002"}',
 '["finance", "transactions"]', 'draft', 'system@demo', NOW(), NOW()),

-- Retail/Analytics datasets
('02100007-0000-4000-8000-000000000007', 'Sales Analytics',
 'Aggregated sales analytics for BI dashboards and reporting',
 (SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), NULL, NULL, NULL,
 '{"version": "2.0.0", "published": true, "owner_team_id": "00100002-0000-4000-8000-000000000002", "project_id": "00300005-0000-4000-8000-000000000005", "materialized": "true", "refresh_schedule": "hourly"}',
 '["sales", "analytics", "retail"]', 'active', 'system@demo', NOW(), NOW()),

('02100008-0000-4000-8000-000000000008', 'Inventory Levels',
 'Current inventory levels across warehouses and regions',
 (SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), NULL, NULL, NULL,
 '{"version": "1.2.0", "published": false, "contract_id": "00400007-0000-4000-8000-000000000007", "owner_team_id": "00100001-0000-4000-8000-000000000001", "project_id": "00300005-0000-4000-8000-000000000005"}',
 '["inventory", "supply-chain"]', 'deprecated', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 15b. DATASET INSTANCES → ASSETS (Table / View)
-- ============================================================================
-- Physical implementations are now stored as Asset rows with the appropriate
-- physical type. Relationships to parent Dataset assets are in entity_relationships.

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES
-- Customer Master - Production instances (tables)
('02500001-0000-4000-8000-000000000001', 'Customers Master Table',
 'Primary production instance in Unity Catalog',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'prod_catalog.crm.customers_master', NULL,
 '{"environment": "prod", "tableRole": "main", "physicalPath": "prod_catalog.crm.customers_master", "originalAssetType": "uc_table"}',
 '["production", "crm"]', 'active', 'system@demo', NOW(), NOW()),

('02500002-0000-4000-8000-000000000002', 'Snowflake Customers Replica',
 'Snowflake replica for analytics workloads',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Snowflake', 'ANALYTICS_DB.CRM.CUSTOMERS_MASTER', NULL,
 '{"environment": "prod", "tableRole": "main", "physicalPath": "ANALYTICS_DB.CRM.CUSTOMERS_MASTER", "originalAssetType": "snowflake_table"}',
 '["production", "snowflake"]', 'active', 'system@demo', NOW(), NOW()),

('0250000a-0000-4000-8000-000000000010', 'Customer Addresses',
 'Customer address dimension table',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'prod_catalog.crm.customer_addresses', NULL,
 '{"environment": "prod", "tableRole": "dimension", "physicalPath": "prod_catalog.crm.customer_addresses", "originalAssetType": "uc_table"}',
 '["dimension", "crm"]', 'active', 'system@demo', NOW(), NOW()),

('0250000b-0000-4000-8000-000000000011', 'Countries Lookup',
 'Country reference/lookup table',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'prod_catalog.reference.countries', NULL,
 '{"environment": "prod", "tableRole": "lookup", "physicalPath": "prod_catalog.reference.countries", "originalAssetType": "uc_table"}',
 '["lookup", "reference"]', 'active', 'system@demo', NOW(), NOW()),

-- Customer Master - Development
('02500003-0000-4000-8000-000000000003', 'Dev Customers Table',
 'Development instance for testing new features',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'dev_catalog.crm.customers_master', NULL,
 '{"environment": "dev", "tableRole": "main", "physicalPath": "dev_catalog.crm.customers_master", "originalAssetType": "uc_table"}',
 '["development", "crm"]', 'active', 'system@demo', NOW(), NOW()),

-- Customer Preferences View
('02500004-0000-4000-8000-000000000004', 'Customer Preferences View',
 'Production view aggregating customer preferences',
 (SELECT id FROM asset_types WHERE name = 'View' LIMIT 1), 'Databricks', 'prod_catalog.crm.v_customer_preferences', NULL,
 '{"environment": "prod", "tableRole": "main", "physicalPath": "prod_catalog.crm.v_customer_preferences", "originalAssetType": "uc_view"}',
 '["production", "view", "crm"]', 'active', 'system@demo', NOW(), NOW()),

-- IoT Device Registry instances
('02500005-0000-4000-8000-000000000005', 'Device Registry',
 'Production IoT device registry',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'iot_catalog.devices.device_registry', NULL,
 '{"environment": "prod", "tableRole": "main", "physicalPath": "iot_catalog.devices.device_registry", "originalAssetType": "uc_table"}',
 '["production", "iot"]', 'active', 'system@demo', NOW(), NOW()),

('02500006-0000-4000-8000-000000000006', 'Dev Device Registry',
 'Development IoT device registry for testing',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'iot_dev.devices.device_registry', NULL,
 '{"environment": "dev", "tableRole": "main", "physicalPath": "iot_dev.devices.device_registry", "originalAssetType": "uc_table"}',
 '["development", "iot"]', 'active', 'system@demo', NOW(), NOW()),

('0250000c-0000-4000-8000-000000000012', 'Device Types',
 'Device type dimension table',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'iot_catalog.devices.device_types', NULL,
 '{"environment": "prod", "tableRole": "dimension", "physicalPath": "iot_catalog.devices.device_types", "originalAssetType": "uc_table"}',
 '["dimension", "iot"]', 'active', 'system@demo', NOW(), NOW()),

('0250000d-0000-4000-8000-000000000013', 'Raw Device Data',
 'Staging streaming table for incoming device data',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'iot_staging.devices.device_raw', NULL,
 '{"environment": "prod", "tableRole": "staging", "physicalPath": "iot_staging.devices.device_raw", "originalAssetType": "uc_streaming_table"}',
 '["staging", "iot", "streaming"]', 'active', 'system@demo', NOW(), NOW()),

-- IoT Telemetry
('02500007-0000-4000-8000-000000000007', 'Device Readings',
 'Production streaming telemetry data',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'iot_catalog.telemetry.device_readings', NULL,
 '{"environment": "prod", "tableRole": "main", "physicalPath": "iot_catalog.telemetry.device_readings", "originalAssetType": "uc_streaming_table"}',
 '["production", "telemetry", "streaming"]', 'active', 'system@demo', NOW(), NOW()),

-- Financial Transactions
('02500008-0000-4000-8000-000000000008', 'Daily Transactions',
 'Development instance for financial testing',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'finance_dev.transactions.daily_transactions', NULL,
 '{"environment": "dev", "tableRole": "main", "physicalPath": "finance_dev.transactions.daily_transactions", "originalAssetType": "uc_table"}',
 '["development", "finance"]', 'active', 'system@demo', NOW(), NOW()),

-- Inventory Levels (deprecated)
('02500009-0000-4000-8000-000000000009', 'Current Inventory',
 'Legacy inventory table - migrating to new schema',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Databricks', 'analytics_catalog.supply_chain.inventory_current', NULL,
 '{"environment": "prod", "tableRole": "main", "physicalPath": "analytics_catalog.supply_chain.inventory_current", "originalAssetType": "uc_table"}',
 '["legacy", "supply-chain"]', 'deprecated', 'system@demo', NOW(), NOW()),

-- Additional multi-platform examples
('0250000e-0000-4000-8000-000000000014', 'Retail Events Stream',
 'Kafka topic for real-time retail events',
 (SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), 'Kafka', 'retail-events', NULL,
 '{"environment": "prod", "tableRole": "main", "physicalPath": "retail-events", "originalAssetType": "kafka_topic"}',
 '["streaming", "retail"]', 'active', 'system@demo', NOW(), NOW()),

('0250000f-0000-4000-8000-000000000015', 'Sales Metrics MV',
 'Materialized view for sales KPIs',
 (SELECT id FROM asset_types WHERE name = 'View' LIMIT 1), 'Databricks', 'prod_catalog.analytics.sales_metrics', NULL,
 '{"environment": "prod", "tableRole": "reference", "physicalPath": "prod_catalog.analytics.sales_metrics", "originalAssetType": "uc_materialized_view"}',
 '["materialized-view", "analytics"]', 'active', 'system@demo', NOW(), NOW()),

('02500010-0000-4000-8000-000000000016', 'Customer 360 Dashboard',
 'Lakeview dashboard for customer insights',
 (SELECT id FROM asset_types WHERE name = 'View' LIMIT 1), 'Databricks', 'prod_catalog.crm.customer_360_dashboard', NULL,
 '{"environment": "prod", "tableRole": "reference", "physicalPath": "prod_catalog.crm.customer_360_dashboard", "originalAssetType": "uc_dashboard"}',
 '["dashboard", "customer"]', 'active', 'system@demo', NOW(), NOW()),

('02500011-0000-4000-8000-000000000017', 'PowerBI Customer Dataset',
 'Power BI semantic model for customer analytics',
 (SELECT id FROM asset_types WHERE name = 'View' LIMIT 1), 'Power BI', 'workspace://Workspaces/Analytics/Customer_Analysis', NULL,
 '{"environment": "prod", "tableRole": "reference", "physicalPath": "workspace://Workspaces/Analytics/Customer_Analysis", "originalAssetType": "powerbi_dataset"}',
 '["powerbi", "analytics"]', 'active', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 15c. DATASET → TABLE/VIEW RELATIONSHIPS (entity_relationships)
-- ============================================================================
-- Connect Dataset assets to their Table/View children

INSERT INTO entity_relationships (id, source_type, source_id, target_type, target_id, relationship_type, created_by, created_at) VALUES
-- Customer Master Data → tables
('02150001-0000-4000-8000-000000000001', 'Dataset', '02100001-0000-4000-8000-000000000001', 'Table', '02500001-0000-4000-8000-000000000001', 'hasTable', 'system@demo', NOW()),
('02150002-0000-4000-8000-000000000002', 'Dataset', '02100001-0000-4000-8000-000000000001', 'Table', '02500002-0000-4000-8000-000000000002', 'hasTable', 'system@demo', NOW()),
('02150003-0000-4000-8000-000000000003', 'Dataset', '02100001-0000-4000-8000-000000000001', 'Table', '0250000a-0000-4000-8000-000000000010', 'hasTable', 'system@demo', NOW()),
('02150004-0000-4000-8000-000000000004', 'Dataset', '02100001-0000-4000-8000-000000000001', 'Table', '0250000b-0000-4000-8000-000000000011', 'hasTable', 'system@demo', NOW()),
('02150020-0000-4000-8000-000000000020', 'Dataset', '02100001-0000-4000-8000-000000000001', 'View', '02500010-0000-4000-8000-000000000016', 'hasView', 'system@demo', NOW()),
('02150021-0000-4000-8000-000000000021', 'Dataset', '02100001-0000-4000-8000-000000000001', 'View', '02500011-0000-4000-8000-000000000017', 'hasView', 'system@demo', NOW()),

-- Customer Engagement Analytics → tables
('02150005-0000-4000-8000-000000000005', 'Dataset', '02100002-0000-4000-8000-000000000002', 'Table', '02500003-0000-4000-8000-000000000003', 'hasTable', 'system@demo', NOW()),

-- Customer Preferences → views
('02150006-0000-4000-8000-000000000006', 'Dataset', '02100003-0000-4000-8000-000000000003', 'View', '02500004-0000-4000-8000-000000000004', 'hasView', 'system@demo', NOW()),

-- IoT Device Management → tables
('02150007-0000-4000-8000-000000000007', 'Dataset', '02100004-0000-4000-8000-000000000004', 'Table', '02500005-0000-4000-8000-000000000005', 'hasTable', 'system@demo', NOW()),
('02150008-0000-4000-8000-000000000008', 'Dataset', '02100004-0000-4000-8000-000000000004', 'Table', '02500006-0000-4000-8000-000000000006', 'hasTable', 'system@demo', NOW()),
('02150009-0000-4000-8000-000000000009', 'Dataset', '02100004-0000-4000-8000-000000000004', 'Table', '0250000c-0000-4000-8000-000000000012', 'hasTable', 'system@demo', NOW()),
('02150010-0000-4000-8000-000000000010', 'Dataset', '02100004-0000-4000-8000-000000000004', 'Table', '0250000d-0000-4000-8000-000000000013', 'hasTable', 'system@demo', NOW()),

-- IoT Telemetry → tables
('02150011-0000-4000-8000-000000000011', 'Dataset', '02100005-0000-4000-8000-000000000005', 'Table', '02500007-0000-4000-8000-000000000007', 'hasTable', 'system@demo', NOW()),

-- Financial Transactions → tables
('02150012-0000-4000-8000-000000000012', 'Dataset', '02100006-0000-4000-8000-000000000006', 'Table', '02500008-0000-4000-8000-000000000008', 'hasTable', 'system@demo', NOW()),

-- Inventory Levels → tables
('02150013-0000-4000-8000-000000000013', 'Dataset', '02100008-0000-4000-8000-000000000008', 'Table', '02500009-0000-4000-8000-000000000009', 'hasTable', 'system@demo', NOW()),

-- Sales Analytics → tables
('02150014-0000-4000-8000-000000000014', 'Dataset', '02100007-0000-4000-8000-000000000007', 'Table', '0250000e-0000-4000-8000-000000000014', 'hasTable', 'system@demo', NOW()),
('02150015-0000-4000-8000-000000000015', 'Dataset', '02100007-0000-4000-8000-000000000007', 'View', '0250000f-0000-4000-8000-000000000015', 'hasView', 'system@demo', NOW()),

-- Dataset → DataContract (governedBy) relationships
('02150030-0000-4000-8000-000000000030', 'Dataset', '02100001-0000-4000-8000-000000000001', 'DataContract', '00400001-0000-4000-8000-000000000001', 'governedBy', 'system@demo', NOW()),
('02150031-0000-4000-8000-000000000031', 'Dataset', '02100002-0000-4000-8000-000000000002', 'DataContract', '00400001-0000-4000-8000-000000000001', 'governedBy', 'system@demo', NOW()),
('02150032-0000-4000-8000-000000000032', 'Dataset', '02100003-0000-4000-8000-000000000003', 'DataContract', '00400001-0000-4000-8000-000000000001', 'governedBy', 'system@demo', NOW()),
('02150033-0000-4000-8000-000000000033', 'Dataset', '02100004-0000-4000-8000-000000000004', 'DataContract', '00400004-0000-4000-8000-000000000004', 'governedBy', 'system@demo', NOW()),
('02150034-0000-4000-8000-000000000034', 'Dataset', '02100005-0000-4000-8000-000000000005', 'DataContract', '00400004-0000-4000-8000-000000000004', 'governedBy', 'system@demo', NOW()),
('02150035-0000-4000-8000-000000000035', 'Dataset', '02100006-0000-4000-8000-000000000006', 'DataContract', '00400006-0000-4000-8000-000000000006', 'governedBy', 'system@demo', NOW()),
('02150036-0000-4000-8000-000000000036', 'Dataset', '02100008-0000-4000-8000-000000000008', 'DataContract', '00400007-0000-4000-8000-000000000007', 'governedBy', 'system@demo', NOW())

ON CONFLICT DO NOTHING;


-- ============================================================================
-- 15c2. DATA PRODUCT → DATASET RELATIONSHIPS (entity_relationships)
-- ============================================================================
-- Connect Data Products to their Dataset assets via hasDataset.
-- This establishes the DP > Dataset > Table > Column hierarchy.
-- Mapping based on domain context and data product purpose.

INSERT INTO entity_relationships (id, source_type, source_id, target_type, target_id, relationship_type, created_by, created_at) VALUES
-- Customer Marketing Recommendations (007...006) → Customer Master Data + Customer Preferences
('02150040-0000-4000-8000-000000000040', 'DataProduct', '00700006-0000-4000-8000-000000000006', 'Dataset', '02100001-0000-4000-8000-000000000001', 'hasDataset', 'system@demo', NOW()),
('02150041-0000-4000-8000-000000000041', 'DataProduct', '00700006-0000-4000-8000-000000000006', 'Dataset', '02100003-0000-4000-8000-000000000003', 'hasDataset', 'system@demo', NOW()),
('02150042-0000-4000-8000-000000000042', 'DataProduct', '00700006-0000-4000-8000-000000000006', 'Dataset', '02100002-0000-4000-8000-000000000002', 'hasDataset', 'system@demo', NOW()),

-- Retail Performance Dashboard Data (007...007) → Sales Analytics
('02150043-0000-4000-8000-000000000043', 'DataProduct', '00700007-0000-4000-8000-000000000007', 'Dataset', '02100007-0000-4000-8000-000000000007', 'hasDataset', 'system@demo', NOW()),

-- POS Transaction Stream (007...001) → Sales Analytics
('02150044-0000-4000-8000-000000000044', 'DataProduct', '00700001-0000-4000-8000-000000000001', 'Dataset', '02100007-0000-4000-8000-000000000007', 'hasDataset', 'system@demo', NOW()),

-- Prepared Sales Transactions (007...002) → Sales Analytics
('02150045-0000-4000-8000-000000000045', 'DataProduct', '00700002-0000-4000-8000-000000000002', 'Dataset', '02100007-0000-4000-8000-000000000007', 'hasDataset', 'system@demo', NOW()),

-- Demand Forecast Model Output (007...003) → Inventory Levels + IoT Telemetry
('02150046-0000-4000-8000-000000000046', 'DataProduct', '00700003-0000-4000-8000-000000000003', 'Dataset', '02100008-0000-4000-8000-000000000008', 'hasDataset', 'system@demo', NOW()),
('02150047-0000-4000-8000-000000000047', 'DataProduct', '00700003-0000-4000-8000-000000000003', 'Dataset', '02100005-0000-4000-8000-000000000005', 'hasDataset', 'system@demo', NOW()),

-- Inventory Optimization Recommendations (007...004) → Inventory Levels + IoT Device Management
('02150048-0000-4000-8000-000000000048', 'DataProduct', '00700004-0000-4000-8000-000000000004', 'Dataset', '02100008-0000-4000-8000-000000000008', 'hasDataset', 'system@demo', NOW()),
('02150049-0000-4000-8000-000000000049', 'DataProduct', '00700004-0000-4000-8000-000000000004', 'Dataset', '02100004-0000-4000-8000-000000000004', 'hasDataset', 'system@demo', NOW()),

-- Price Optimization Model Output (007...005) → Sales Analytics + Financial Transactions
('0215004a-0000-4000-8000-000000000050', 'DataProduct', '00700005-0000-4000-8000-000000000005', 'Dataset', '02100007-0000-4000-8000-000000000007', 'hasDataset', 'system@demo', NOW()),
('0215004b-0000-4000-8000-000000000051', 'DataProduct', '00700005-0000-4000-8000-000000000005', 'Dataset', '02100006-0000-4000-8000-000000000006', 'hasDataset', 'system@demo', NOW())

ON CONFLICT DO NOTHING;


-- ============================================================================
-- 15d. DATASET SUBSCRIPTIONS → ENTITY SUBSCRIPTIONS
-- ============================================================================

INSERT INTO entity_subscriptions (id, entity_type, entity_id, subscriber_email, subscription_reason, created_at) VALUES
-- Customer Master Data subscribers
('02200001-0000-4000-8000-000000000001', 'Dataset', '02100001-0000-4000-8000-000000000001', 'alice.johnson@company.com', 'Analytics team lead - need updates for customer 360 project', NOW() - INTERVAL '30 days'),
('02200002-0000-4000-8000-000000000002', 'Dataset', '02100001-0000-4000-8000-000000000001', 'marketing-lead@example.com', 'Campaign targeting use case', NOW() - INTERVAL '20 days'),
('02200003-0000-4000-8000-000000000003', 'Dataset', '02100001-0000-4000-8000-000000000001', 'data.steward@example.com', 'Governance oversight', NOW() - INTERVAL '15 days'),
('02600001-0000-4000-8000-000000000001', 'Dataset', '02100001-0000-4000-8000-000000000001', 'alice.analyst@example.com', 'Needed for marketing dashboards', NOW() - INTERVAL '30 days'),
('02600002-0000-4000-8000-000000000002', 'Dataset', '02100001-0000-4000-8000-000000000001', 'bob.scientist@example.com', 'ML model training data', NOW() - INTERVAL '25 days'),
('02600003-0000-4000-8000-000000000003', 'Dataset', '02100001-0000-4000-8000-000000000001', 'carol.engineer@example.com', 'Data pipeline integration', NOW() - INTERVAL '20 days'),

-- IoT dataset subscribers
('02200004-0000-4000-8000-000000000004', 'Dataset', '02100004-0000-4000-8000-000000000004', 'bob.wilson@company.com', 'ML model training data source', NOW() - INTERVAL '10 days'),
('02200005-0000-4000-8000-000000000005', 'Dataset', '02100005-0000-4000-8000-000000000005', 'bob.wilson@company.com', 'Anomaly detection pipeline', NOW() - INTERVAL '10 days'),
('02600004-0000-4000-8000-000000000004', 'Dataset', '02100005-0000-4000-8000-000000000005', 'david.ops@example.com', 'Real-time monitoring dashboards', NOW() - INTERVAL '15 days'),
('02600005-0000-4000-8000-000000000005', 'Dataset', '02100005-0000-4000-8000-000000000005', 'eve.developer@example.com', 'IoT analytics application', NOW() - INTERVAL '10 days'),

-- Sales Analytics subscribers
('02200006-0000-4000-8000-000000000006', 'Dataset', '02100007-0000-4000-8000-000000000007', 'analyst@example.com', 'Weekly reporting', NOW() - INTERVAL '5 days'),
('02600006-0000-4000-8000-000000000006', 'Dataset', '02100007-0000-4000-8000-000000000007', 'frank.finance@example.com', 'Revenue reporting', NOW() - INTERVAL '5 days'),
('02600007-0000-4000-8000-000000000007', 'Dataset', '02100007-0000-4000-8000-000000000007', 'alice.analyst@example.com', 'Sales trend analysis', NOW() - INTERVAL '3 days')

ON CONFLICT DO NOTHING;


-- ============================================================================
-- 16. TAG NAMESPACES (type=026)
-- ============================================================================
-- Centralized tag namespaces for organizing tags across the platform

-- Note: 'default' namespace is auto-created at startup, so we use 'general' for demo general-purpose tags
INSERT INTO tag_namespaces (id, name, description, created_by, created_at, updated_at) VALUES
('02600100-0000-4000-8000-000000000001', 'general', 'General-purpose tags for common use cases', 'system@demo', NOW(), NOW()),
('02600101-0000-4000-8000-000000000002', 'governance', 'Data governance classifications and sensitivity labels', 'system@demo', NOW(), NOW()),
('02600102-0000-4000-8000-000000000003', 'technical', 'Technical metadata tags for data processing characteristics', 'system@demo', NOW(), NOW()),
('02600103-0000-4000-8000-000000000004', 'business', 'Business domain and functional area tags', 'system@demo', NOW(), NOW()),
('02600104-0000-4000-8000-000000000005', 'compliance', 'Regulatory and compliance requirement tags', 'system@demo', NOW(), NOW())

ON CONFLICT (name) DO NOTHING;


-- ============================================================================
-- 17. TAGS (type=027)
-- ============================================================================
-- Tags within each namespace for categorizing and labeling entities

INSERT INTO tags (id, name, description, possible_values, status, version, namespace_id, parent_id, created_by, created_at, updated_at) VALUES
-- General namespace tags (priority and lifecycle)
('02700001-0000-4000-8000-000000000001', 'priority-high', 'High priority item requiring immediate attention', NULL, 'active', 'v1.0', '02600100-0000-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
('02700002-0000-4000-8000-000000000002', 'priority-medium', 'Medium priority item for standard processing', NULL, 'active', 'v1.0', '02600100-0000-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
('02700003-0000-4000-8000-000000000003', 'priority-low', 'Low priority item for deferred handling', NULL, 'active', 'v1.0', '02600100-0000-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
('02700004-0000-4000-8000-000000000004', 'deprecated', 'Marked for deprecation or removal', NULL, 'active', 'v1.0', '02600100-0000-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),

-- Governance namespace tags (data classification)
('02700005-0000-4000-8000-000000000005', 'pii', 'Contains Personally Identifiable Information', NULL, 'active', 'v1.0', '02600101-0000-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
('02700006-0000-4000-8000-000000000006', 'confidential', 'Confidential data with restricted access', NULL, 'active', 'v1.0', '02600101-0000-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
('02700007-0000-4000-8000-000000000007', 'public', 'Publicly available data with no restrictions', NULL, 'active', 'v1.0', '02600101-0000-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
('02700008-0000-4000-8000-000000000008', 'internal', 'Internal use only within the organization', NULL, 'active', 'v1.0', '02600101-0000-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
('02700009-0000-4000-8000-000000000009', 'restricted', 'Highly restricted data requiring special authorization', NULL, 'active', 'v1.0', '02600101-0000-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),

-- Technical namespace tags (processing characteristics)
('0270000a-0000-4000-8000-000000000010', 'real-time', 'Real-time or streaming data processing', NULL, 'active', 'v1.0', '02600102-0000-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW()),
('0270000b-0000-4000-8000-000000000011', 'batch', 'Batch processing data pipeline', NULL, 'active', 'v1.0', '02600102-0000-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW()),
('0270000c-0000-4000-8000-000000000012', 'streaming', 'Streaming data source or sink', NULL, 'active', 'v1.0', '02600102-0000-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW()),
('0270000d-0000-4000-8000-000000000013', 'delta-table', 'Stored as Delta Lake table format', NULL, 'active', 'v1.0', '02600102-0000-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW()),
('0270000e-0000-4000-8000-000000000014', 'archived', 'Archived or cold storage data', NULL, 'active', 'v1.0', '02600102-0000-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW()),

-- Business namespace tags (functional areas)
('0270000f-0000-4000-8000-000000000015', 'customer-facing', 'Data used for customer-facing applications', NULL, 'active', 'v1.0', '02600103-0000-4000-8000-000000000004', NULL, 'system@demo', NOW(), NOW()),
('02700010-0000-4000-8000-000000000016', 'internal-ops', 'Data for internal operations and processes', NULL, 'active', 'v1.0', '02600103-0000-4000-8000-000000000004', NULL, 'system@demo', NOW(), NOW()),
('02700011-0000-4000-8000-000000000017', 'analytics', 'Data primarily used for analytics purposes', NULL, 'active', 'v1.0', '02600103-0000-4000-8000-000000000004', NULL, 'system@demo', NOW(), NOW()),
('02700012-0000-4000-8000-000000000018', 'reporting', 'Data used for business reporting', NULL, 'active', 'v1.0', '02600103-0000-4000-8000-000000000004', NULL, 'system@demo', NOW(), NOW()),

-- Compliance namespace tags (regulatory requirements)
('02700013-0000-4000-8000-000000000019', 'gdpr', 'Subject to GDPR requirements', NULL, 'active', 'v1.0', '02600104-0000-4000-8000-000000000005', NULL, 'system@demo', NOW(), NOW()),
('02700014-0000-4000-8000-000000000020', 'ccpa', 'Subject to CCPA requirements', NULL, 'active', 'v1.0', '02600104-0000-4000-8000-000000000005', NULL, 'system@demo', NOW(), NOW()),
('02700015-0000-4000-8000-000000000021', 'sox', 'Subject to SOX compliance', NULL, 'active', 'v1.0', '02600104-0000-4000-8000-000000000005', NULL, 'system@demo', NOW(), NOW()),
('02700016-0000-4000-8000-000000000022', 'hipaa', 'Subject to HIPAA requirements', NULL, 'active', 'v1.0', '02600104-0000-4000-8000-000000000005', NULL, 'system@demo', NOW(), NOW()),
('02700017-0000-4000-8000-000000000023', 'pci-dss', 'Subject to PCI-DSS requirements', NULL, 'active', 'v1.0', '02600104-0000-4000-8000-000000000005', NULL, 'system@demo', NOW(), NOW())

ON CONFLICT (namespace_id, name) DO NOTHING;


-- ============================================================================
-- 18. TAG NAMESPACE PERMISSIONS (type=028)
-- ============================================================================
-- Access control for tag namespaces by group

INSERT INTO tag_namespace_permissions (id, namespace_id, group_id, access_level, created_by, created_at, updated_at) VALUES
-- General namespace permissions (everyone can read, stewards can write)
('02800001-0000-4000-8000-000000000001', '02600100-0000-4000-8000-000000000001', 'data-engineers', 'read_write', 'system@demo', NOW(), NOW()),
('02800002-0000-4000-8000-000000000002', '02600100-0000-4000-8000-000000000001', 'analysts', 'read_only', 'system@demo', NOW(), NOW()),
('02800003-0000-4000-8000-000000000003', '02600100-0000-4000-8000-000000000001', 'data-stewards', 'admin', 'system@demo', NOW(), NOW()),
('02800004-0000-4000-8000-000000000004', '02600100-0000-4000-8000-000000000001', 'data-scientists', 'read_write', 'system@demo', NOW(), NOW()),

-- Governance namespace permissions (stewards have full control)
('02800005-0000-4000-8000-000000000005', '02600101-0000-4000-8000-000000000002', 'data-stewards', 'admin', 'system@demo', NOW(), NOW()),
('02800006-0000-4000-8000-000000000006', '02600101-0000-4000-8000-000000000002', 'data-engineers', 'read_only', 'system@demo', NOW(), NOW()),
('02800007-0000-4000-8000-000000000007', '02600101-0000-4000-8000-000000000002', 'analysts', 'read_only', 'system@demo', NOW(), NOW()),

-- Technical namespace permissions (engineers can write)
('02800008-0000-4000-8000-000000000008', '02600102-0000-4000-8000-000000000003', 'data-engineers', 'admin', 'system@demo', NOW(), NOW()),
('02800009-0000-4000-8000-000000000009', '02600102-0000-4000-8000-000000000003', 'data-scientists', 'read_write', 'system@demo', NOW(), NOW()),
('0280000a-0000-4000-8000-000000000010', '02600102-0000-4000-8000-000000000003', 'analysts', 'read_only', 'system@demo', NOW(), NOW()),

-- Business namespace permissions (analysts have more access)
('0280000b-0000-4000-8000-000000000011', '02600103-0000-4000-8000-000000000004', 'analysts', 'read_write', 'system@demo', NOW(), NOW()),
('0280000c-0000-4000-8000-000000000012', '02600103-0000-4000-8000-000000000004', 'data-stewards', 'admin', 'system@demo', NOW(), NOW()),
('0280000d-0000-4000-8000-000000000013', '02600103-0000-4000-8000-000000000004', 'data-engineers', 'read_only', 'system@demo', NOW(), NOW()),

-- Compliance namespace permissions (stewards only)
('0280000e-0000-4000-8000-000000000014', '02600104-0000-4000-8000-000000000005', 'data-stewards', 'admin', 'system@demo', NOW(), NOW()),
('0280000f-0000-4000-8000-000000000015', '02600104-0000-4000-8000-000000000005', 'data-engineers', 'read_only', 'system@demo', NOW(), NOW()),
('02800010-0000-4000-8000-000000000016', '02600104-0000-4000-8000-000000000005', 'analysts', 'read_only', 'system@demo', NOW(), NOW())

ON CONFLICT (namespace_id, group_id) DO NOTHING;


-- ============================================================================
-- 19. ENTITY TAG ASSOCIATIONS (type=029)
-- ============================================================================
-- Links tags to entities (data products, contracts, datasets)

INSERT INTO entity_tag_associations (id, tag_id, entity_id, entity_type, assigned_value, assigned_by, assigned_at) VALUES
-- Data Product tags
-- POS Transaction Stream (00700001) - real-time streaming product
('02900001-0000-4000-8000-000000000001', '0270000a-0000-4000-8000-000000000010', '00700001-0000-4000-8000-000000000001', 'data_product', NULL, 'system@demo', NOW()),
('02900002-0000-4000-8000-000000000002', '0270000c-0000-4000-8000-000000000012', '00700001-0000-4000-8000-000000000001', 'data_product', NULL, 'system@demo', NOW()),
('02900003-0000-4000-8000-000000000003', '02700001-0000-4000-8000-000000000001', '00700001-0000-4000-8000-000000000001', 'data_product', NULL, 'system@demo', NOW()),

-- Prepared Sales Transactions (00700002) - batch analytics product with PII
('02900004-0000-4000-8000-000000000004', '0270000b-0000-4000-8000-000000000011', '00700002-0000-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),
('02900005-0000-4000-8000-000000000005', '02700005-0000-4000-8000-000000000005', '00700002-0000-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),
('02900006-0000-4000-8000-000000000006', '02700011-0000-4000-8000-000000000017', '00700002-0000-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),

-- Customer Marketing Recommendations (00700006) - customer-facing with GDPR
('02900007-0000-4000-8000-000000000007', '0270000f-0000-4000-8000-000000000015', '00700006-0000-4000-8000-000000000006', 'data_product', NULL, 'system@demo', NOW()),
('02900008-0000-4000-8000-000000000008', '02700005-0000-4000-8000-000000000005', '00700006-0000-4000-8000-000000000006', 'data_product', NULL, 'system@demo', NOW()),
('02900009-0000-4000-8000-000000000009', '02700013-0000-4000-8000-000000000019', '00700006-0000-4000-8000-000000000006', 'data_product', NULL, 'system@demo', NOW()),

-- Data Contract tags
-- Customer Data Contract (00400001) - PII, confidential, GDPR
('0290000a-0000-4000-8000-000000000010', '02700005-0000-4000-8000-000000000005', '00400001-0000-4000-8000-000000000001', 'data_contract', NULL, 'system@demo', NOW()),
('0290000b-0000-4000-8000-000000000011', '02700006-0000-4000-8000-000000000006', '00400001-0000-4000-8000-000000000001', 'data_contract', NULL, 'system@demo', NOW()),
('0290000c-0000-4000-8000-000000000012', '02700013-0000-4000-8000-000000000019', '00400001-0000-4000-8000-000000000001', 'data_contract', NULL, 'system@demo', NOW()),
('0290000d-0000-4000-8000-000000000013', '02700001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'data_contract', NULL, 'system@demo', NOW()),

-- Product Catalog Contract (00400002) - internal, deprecated
('0290000e-0000-4000-8000-000000000014', '02700008-0000-4000-8000-000000000008', '00400002-0000-4000-8000-000000000002', 'data_contract', NULL, 'system@demo', NOW()),
('0290000f-0000-4000-8000-000000000015', '02700004-0000-4000-8000-000000000004', '00400002-0000-4000-8000-000000000002', 'data_contract', NULL, 'system@demo', NOW()),

-- IoT Device Data Contract (00400004) - real-time, technical
('02900010-0000-4000-8000-000000000016', '0270000a-0000-4000-8000-000000000010', '00400004-0000-4000-8000-000000000004', 'data_contract', NULL, 'system@demo', NOW()),
('02900011-0000-4000-8000-000000000017', '02700008-0000-4000-8000-000000000008', '00400004-0000-4000-8000-000000000004', 'data_contract', NULL, 'system@demo', NOW()),

-- Financial Transactions Contract (00400006) - SOX compliance
('02900012-0000-4000-8000-000000000018', '02700006-0000-4000-8000-000000000006', '00400006-0000-4000-8000-000000000006', 'data_contract', NULL, 'system@demo', NOW()),
('02900013-0000-4000-8000-000000000019', '02700015-0000-4000-8000-000000000021', '00400006-0000-4000-8000-000000000006', 'data_contract', NULL, 'system@demo', NOW()),
('02900014-0000-4000-8000-000000000020', '02700009-0000-4000-8000-000000000009', '00400006-0000-4000-8000-000000000006', 'data_contract', NULL, 'system@demo', NOW()),

-- Dataset tags (entity_type='Dataset' — asset-backed)
-- Customer Master - Production (02100001) - PII, GDPR, delta-table
('02900015-0000-4000-8000-000000000021', '02700005-0000-4000-8000-000000000005', '02100001-0000-4000-8000-000000000001', 'Dataset', NULL, 'system@demo', NOW()),
('02900016-0000-4000-8000-000000000022', '02700013-0000-4000-8000-000000000019', '02100001-0000-4000-8000-000000000001', 'Dataset', NULL, 'system@demo', NOW()),
('02900017-0000-4000-8000-000000000023', '0270000d-0000-4000-8000-000000000013', '02100001-0000-4000-8000-000000000001', 'Dataset', NULL, 'system@demo', NOW()),
('02900018-0000-4000-8000-000000000024', '02700001-0000-4000-8000-000000000001', '02100001-0000-4000-8000-000000000001', 'Dataset', NULL, 'system@demo', NOW()),

-- IoT Telemetry Stream (02100005) - real-time, streaming
('02900019-0000-4000-8000-000000000025', '0270000a-0000-4000-8000-000000000010', '02100005-0000-4000-8000-000000000005', 'Dataset', NULL, 'system@demo', NOW()),
('0290001a-0000-4000-8000-000000000026', '0270000c-0000-4000-8000-000000000012', '02100005-0000-4000-8000-000000000005', 'Dataset', NULL, 'system@demo', NOW()),
('0290001b-0000-4000-8000-000000000027', '0270000d-0000-4000-8000-000000000013', '02100005-0000-4000-8000-000000000005', 'Dataset', NULL, 'system@demo', NOW()),

-- Sales Analytics Summary (02100007) - analytics, reporting, batch
('0290001c-0000-4000-8000-000000000028', '02700011-0000-4000-8000-000000000017', '02100007-0000-4000-8000-000000000007', 'Dataset', NULL, 'system@demo', NOW()),
('0290001d-0000-4000-8000-000000000029', '02700012-0000-4000-8000-000000000018', '02100007-0000-4000-8000-000000000007', 'Dataset', NULL, 'system@demo', NOW()),
('0290001e-0000-4000-8000-000000000030', '0270000b-0000-4000-8000-000000000011', '02100007-0000-4000-8000-000000000007', 'Dataset', NULL, 'system@demo', NOW()),

-- Inventory Levels (02100008) - deprecated, archived
('0290001f-0000-4000-8000-000000000031', '02700004-0000-4000-8000-000000000004', '02100008-0000-4000-8000-000000000008', 'Dataset', NULL, 'system@demo', NOW()),
('02900020-0000-4000-8000-000000000032', '0270000e-0000-4000-8000-000000000014', '02100008-0000-4000-8000-000000000008', 'Dataset', NULL, 'system@demo', NOW()),

-- Dataset Instance tags (imported from Unity Catalog)
-- Customer Master Production - Main Table (02500001) - delta, partitioned
('02900021-0000-4000-8000-000000000033', '0270000d-0000-4000-8000-000000000013', '02500001-0000-4000-8000-000000000001', 'dataset_instance', NULL, 'system@demo', NOW()),
('02900022-0000-4000-8000-000000000034', '02700010-0000-4000-8000-000000000016', '02500001-0000-4000-8000-000000000001', 'dataset_instance', NULL, 'system@demo', NOW()),

-- Customer Addresses Dimension (0250000a) - delta
('02900023-0000-4000-8000-000000000035', '0270000d-0000-4000-8000-000000000013', '0250000a-0000-4000-8000-000000000010', 'dataset_instance', NULL, 'system@demo', NOW()),

-- IoT Device Registry - Main Table (02500005) - delta, partitioned
('02900024-0000-4000-8000-000000000036', '0270000d-0000-4000-8000-000000000013', '02500005-0000-4000-8000-000000000005', 'dataset_instance', NULL, 'system@demo', NOW()),
('02900025-0000-4000-8000-000000000037', '02700010-0000-4000-8000-000000000016', '02500005-0000-4000-8000-000000000005', 'dataset_instance', NULL, 'system@demo', NOW()),

-- IoT Device Types Dimension (0250000c) - delta
('02900026-0000-4000-8000-000000000038', '0270000d-0000-4000-8000-000000000013', '0250000c-0000-4000-8000-000000000012', 'dataset_instance', NULL, 'system@demo', NOW()),

-- IoT Raw Device Staging (0250000d) - staging table
('02900027-0000-4000-8000-000000000039', '02700008-0000-4000-8000-000000000008', '0250000d-0000-4000-8000-000000000013', 'dataset_instance', NULL, 'system@demo', NOW()),

-- IoT Telemetry Main (02500007) - streaming, real-time
('02900028-0000-4000-8000-000000000040', '0270000a-0000-4000-8000-000000000010', '02500007-0000-4000-8000-000000000007', 'dataset_instance', NULL, 'system@demo', NOW()),
('02900029-0000-4000-8000-000000000041', '0270000c-0000-4000-8000-000000000012', '02500007-0000-4000-8000-000000000007', 'dataset_instance', NULL, 'system@demo', NOW())

ON CONFLICT (tag_id, entity_id, entity_type) DO NOTHING;


-- ============================================================================
-- 20. PROCESS WORKFLOWS (type=02a)
-- ============================================================================
-- Pre-creation validation workflows using policy_check steps that reference
-- the compliance policies defined above (01100001-01100005)

INSERT INTO process_workflows (id, name, description, trigger_config, scope_config, is_active, is_default, version, created_by, updated_by, created_at, updated_at) VALUES
-- Pre-creation compliance validation for catalogs/schemas/tables
('02a00001-0000-4000-8000-000000000001', 'Pre-Creation Compliance Validation', 'Validates naming conventions before asset creation. Blocks creation if validation fails.', 
'{"type": "before_create", "entity_types": ["catalog", "schema", "table", "view"]}',
'{"type": "all"}',
true, true, 1, 'system@demo', 'system@demo', NOW(), NOW()),

-- Data quality validation on updates
('02a00002-0000-4000-8000-000000000002', 'Data Quality Gate', 'Ensures data quality thresholds are met before allowing dataset updates.', 
'{"type": "before_update", "entity_types": ["dataset"]}',
'{"type": "all"}',
true, true, 1, 'system@demo', 'system@demo', NOW(), NOW()),

-- Security compliance workflow for sensitive data
('02a00003-0000-4000-8000-000000000003', 'PII Data Security Check', 'Validates PII encryption and access controls for sensitive data products.', 
'{"type": "on_create", "entity_types": ["data_product", "data_contract"]}',
'{"type": "all"}',
true, true, 1, 'system@demo', 'system@demo', NOW(), NOW()),

-- Freshness monitoring workflow
('02a00004-0000-4000-8000-000000000004', 'Data Freshness Monitor', 'Monitors data freshness and notifies stakeholders when data becomes stale.', 
'{"type": "scheduled", "schedule": "0 6 * * *"}',
'{"type": "all"}',
true, false, 1, 'system@demo', 'system@demo', NOW(), NOW()),

-- Full governance workflow with multiple checks
('02a00005-0000-4000-8000-000000000005', 'Full Governance Pre-Check', 'Comprehensive pre-creation validation including naming, access control, and PII checks.', 
'{"type": "before_create", "entity_types": ["table", "view"]}',
'{"type": "project", "ids": ["00300001-0000-4000-8000-000000000001"]}',
true, false, 1, 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 20b. WORKFLOW STEPS (type=02b)
-- ============================================================================
-- Steps reference compliance policies by ID using the policy_check step type

INSERT INTO workflow_steps (id, workflow_id, step_id, name, step_type, config, on_pass, on_fail, "order", position, created_at, updated_at) VALUES
-- Pre-Creation Compliance Validation workflow steps (02a00001)
-- Uses policy 01100001 (Naming Conventions)
('02b00001-0000-4000-8000-000000000001', '02a00001-0000-4000-8000-000000000001', 'check-naming', 'Check Naming Conventions', 'policy_check', 
'{"policy_id": "01100001-0000-4000-8000-000000000001"}',
'naming-pass', 'naming-fail', 1, '{"x": 250, "y": 150}', NOW(), NOW()),

('02b00002-0000-4000-8000-000000000002', '02a00001-0000-4000-8000-000000000001', 'naming-pass', 'Naming Valid', 'pass', 
'{}',
NULL, NULL, 2, '{"x": 150, "y": 300}', NOW(), NOW()),

('02b00003-0000-4000-8000-000000000003', '02a00001-0000-4000-8000-000000000001', 'naming-fail', 'Naming Invalid', 'fail', 
'{"message": "Asset name does not follow naming conventions"}',
NULL, NULL, 3, '{"x": 350, "y": 300}', NOW(), NOW()),

-- Data Quality Gate workflow steps (02a00002)
-- Uses policy 01100003 (Data Quality Thresholds)
('02b00004-0000-4000-8000-000000000004', '02a00002-0000-4000-8000-000000000002', 'check-quality', 'Check Data Quality', 'policy_check', 
'{"policy_id": "01100003-0000-4000-8000-000000000003"}',
'quality-pass', 'quality-fail', 1, '{"x": 250, "y": 150}', NOW(), NOW()),

('02b00005-0000-4000-8000-000000000005', '02a00002-0000-4000-8000-000000000002', 'quality-pass', 'Quality Check Passed', 'pass', 
'{}',
NULL, NULL, 2, '{"x": 150, "y": 300}', NOW(), NOW()),

('02b00006-0000-4000-8000-000000000006', '02a00002-0000-4000-8000-000000000002', 'quality-fail', 'Quality Check Failed', 'notification', 
'{"recipients": "owner", "template": "validation_failed"}',
NULL, NULL, 3, '{"x": 350, "y": 300}', NOW(), NOW()),

-- PII Data Security Check workflow steps (02a00003)
-- Uses policies 01100002 (PII Encryption) and 01100004 (Access Control)
('02b00007-0000-4000-8000-000000000007', '02a00003-0000-4000-8000-000000000003', 'check-pii', 'Check PII Encryption', 'policy_check', 
'{"policy_id": "01100002-0000-4000-8000-000000000002"}',
'check-access', 'notify-pii-fail', 1, '{"x": 250, "y": 100}', NOW(), NOW()),

('02b00008-0000-4000-8000-000000000008', '02a00003-0000-4000-8000-000000000003', 'check-access', 'Check Access Control', 'policy_check', 
'{"policy_id": "01100004-0000-4000-8000-000000000004"}',
'security-pass', 'notify-access-fail', 2, '{"x": 250, "y": 220}', NOW(), NOW()),

('02b00009-0000-4000-8000-000000000009', '02a00003-0000-4000-8000-000000000003', 'security-pass', 'Security Validated', 'pass', 
'{}',
NULL, NULL, 3, '{"x": 150, "y": 340}', NOW(), NOW()),

('02b0000a-0000-4000-8000-000000000010', '02a00003-0000-4000-8000-000000000003', 'notify-pii-fail', 'Notify PII Failure', 'notification', 
'{"recipients": "domain_owners", "template": "validation_failed"}',
NULL, NULL, 4, '{"x": 350, "y": 340}', NOW(), NOW()),

('02b0000b-0000-4000-8000-000000000011', '02a00003-0000-4000-8000-000000000003', 'notify-access-fail', 'Notify Access Failure', 'notification', 
'{"recipients": "domain_owners", "template": "validation_failed"}',
NULL, NULL, 5, '{"x": 450, "y": 340}', NOW(), NOW()),

-- Data Freshness Monitor workflow steps (02a00004)
-- Uses policy 01100005 (Data Freshness)
('02b0000c-0000-4000-8000-000000000012', '02a00004-0000-4000-8000-000000000004', 'check-freshness', 'Check Data Freshness', 'policy_check', 
'{"policy_id": "01100005-0000-4000-8000-000000000005"}',
'freshness-ok', 'freshness-stale', 1, '{"x": 250, "y": 150}', NOW(), NOW()),

('02b0000d-0000-4000-8000-000000000013', '02a00004-0000-4000-8000-000000000004', 'freshness-ok', 'Data is Fresh', 'pass', 
'{}',
NULL, NULL, 2, '{"x": 150, "y": 300}', NOW(), NOW()),

('02b0000e-0000-4000-8000-000000000014', '02a00004-0000-4000-8000-000000000004', 'freshness-stale', 'Notify Stale Data', 'notification', 
'{"recipients": "owner", "template": "validation_failed"}',
NULL, NULL, 3, '{"x": 350, "y": 300}', NOW(), NOW()),

-- Full Governance Pre-Check workflow steps (02a00005)
-- Uses multiple policies: Naming (01100001), PII (01100002), Access (01100004)
('02b0000f-0000-4000-8000-000000000015', '02a00005-0000-4000-8000-000000000005', 'step-naming', 'Check Naming', 'policy_check', 
'{"policy_id": "01100001-0000-4000-8000-000000000001"}',
'step-pii', 'fail-naming', 1, '{"x": 250, "y": 80}', NOW(), NOW()),

('02b00010-0000-4000-8000-000000000016', '02a00005-0000-4000-8000-000000000005', 'step-pii', 'Check PII Encryption', 'policy_check', 
'{"policy_id": "01100002-0000-4000-8000-000000000002"}',
'step-access', 'fail-pii', 2, '{"x": 250, "y": 180}', NOW(), NOW()),

('02b00011-0000-4000-8000-000000000017', '02a00005-0000-4000-8000-000000000005', 'step-access', 'Check Access Control', 'policy_check', 
'{"policy_id": "01100004-0000-4000-8000-000000000004"}',
'all-passed', 'fail-access', 3, '{"x": 250, "y": 280}', NOW(), NOW()),

('02b00012-0000-4000-8000-000000000018', '02a00005-0000-4000-8000-000000000005', 'all-passed', 'All Checks Passed', 'pass', 
'{}',
NULL, NULL, 4, '{"x": 150, "y": 400}', NOW(), NOW()),

('02b00013-0000-4000-8000-000000000019', '02a00005-0000-4000-8000-000000000005', 'fail-naming', 'Naming Failed', 'fail', 
'{"message": "Asset does not follow naming conventions"}',
NULL, NULL, 5, '{"x": 400, "y": 130}', NOW(), NOW()),

('02b00014-0000-4000-8000-000000000020', '02a00005-0000-4000-8000-000000000005', 'fail-pii', 'PII Check Failed', 'fail', 
'{"message": "PII data must be encrypted"}',
NULL, NULL, 6, '{"x": 400, "y": 230}', NOW(), NOW()),

('02b00015-0000-4000-8000-000000000021', '02a00005-0000-4000-8000-000000000005', 'fail-access', 'Access Check Failed', 'fail', 
'{"message": "Access controls must be properly configured"}',
NULL, NULL, 7, '{"x": 400, "y": 330}', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 20c. REQUEST-BASED WORKFLOWS (type=02d)
-- ============================================================================
-- Workflows that handle request triggers (on_request_review, on_request_access, etc.)
-- These demonstrate the new request/approval workflow pattern.

INSERT INTO process_workflows (id, name, description, trigger_config, scope_config, is_active, is_default, version, created_by, updated_by, created_at, updated_at) VALUES
-- Contract Review Request with Multi-Level Approval
('02d00001-0000-4000-8000-000000000001', 'Contract Review - Multi-Level Approval', 
'Advanced contract review workflow with validation, steward approval, and domain owner sign-off.', 
'{"type": "on_request_review", "entity_types": ["data_contract"]}',
'{"type": "all"}',
true, false, 1, 'system@demo', 'system@demo', NOW(), NOW()),

-- Access Request with Policy Check
('02d00002-0000-4000-8000-000000000002', 'Access Request with Compliance Check', 
'Access grant workflow that validates compliance policies before approval.', 
'{"type": "on_request_access", "entity_types": ["access_grant"]}',
'{"type": "all"}',
true, false, 1, 'system@demo', 'system@demo', NOW(), NOW()),

-- Data Product Publish with Delivery
('02d00003-0000-4000-8000-000000000003', 'Product Publish with Delivery', 
'Data product status change workflow that triggers delivery on approval.', 
'{"type": "on_request_status_change", "entity_types": ["data_product"], "from_status": "under_review", "to_status": "active"}',
'{"type": "all"}',
false, false, 1, 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 20d. REQUEST WORKFLOW STEPS (type=02e)
-- ============================================================================

INSERT INTO workflow_steps (id, workflow_id, step_id, name, step_type, config, on_pass, on_fail, "order", position, created_at, updated_at) VALUES
-- Contract Review - Multi-Level Approval (02d00001)
('02e00001-0000-4000-8000-000000000001', '02d00001-0000-4000-8000-000000000001', 'notify-receipt', 'Confirm Request Received', 'notification',
'{"recipients": "requester", "template": "request_submitted", "custom_message": "Your data contract review request has been submitted. It will go through a multi-level approval process."}',
'validate-schema', NULL, 1, '{"x": 250, "y": 50}', NOW(), NOW()),

('02e00002-0000-4000-8000-000000000002', '02d00001-0000-4000-8000-000000000001', 'validate-schema', 'Validate Schema Completeness', 'validation',
'{"rule": "MATCH (obj:Object) ASSERT LENGTH(obj.schema) > 10 ON_FAIL FAIL ''Schema must be defined''"}',
'steward-approval', 'fail-validation', 2, '{"x": 250, "y": 150}', NOW(), NOW()),

('02e00003-0000-4000-8000-000000000003', '02d00001-0000-4000-8000-000000000001', 'steward-approval', 'Data Steward Approval', 'approval',
'{"approvers": "DataSteward", "timeout_days": 5, "require_all": false}',
'domain-approval', 'notify-steward-reject', 3, '{"x": 250, "y": 250}', NOW(), NOW()),

('02e00004-0000-4000-8000-000000000004', '02d00001-0000-4000-8000-000000000001', 'domain-approval', 'Domain Owner Sign-off', 'approval',
'{"approvers": "DomainOwner", "timeout_days": 3, "require_all": false}',
'notify-approved', 'notify-domain-reject', 4, '{"x": 250, "y": 350}', NOW(), NOW()),

('02e00005-0000-4000-8000-000000000005', '02d00001-0000-4000-8000-000000000001', 'notify-approved', 'Notify Full Approval', 'notification',
'{"recipients": "requester", "template": "request_approved", "custom_message": "Your data contract has been approved by both the data steward and domain owner."}',
'success', NULL, 5, '{"x": 250, "y": 450}', NOW(), NOW()),

('02e00006-0000-4000-8000-000000000006', '02d00001-0000-4000-8000-000000000001', 'notify-steward-reject', 'Notify Steward Rejection', 'notification',
'{"recipients": "requester", "template": "request_rejected", "custom_message": "Your data contract was not approved by the data steward. Please review their feedback."}',
'fail-rejected', NULL, 6, '{"x": 100, "y": 350}', NOW(), NOW()),

('02e00007-0000-4000-8000-000000000007', '02d00001-0000-4000-8000-000000000001', 'notify-domain-reject', 'Notify Domain Rejection', 'notification',
'{"recipients": "requester", "template": "request_rejected", "custom_message": "Your data contract was approved by the steward but rejected by the domain owner."}',
'fail-rejected', NULL, 7, '{"x": 400, "y": 400}', NOW(), NOW()),

('02e00008-0000-4000-8000-000000000008', '02d00001-0000-4000-8000-000000000001', 'fail-validation', 'Schema Validation Failed', 'fail',
'{"message": "Contract schema validation failed"}',
NULL, NULL, 8, '{"x": 400, "y": 200}', NOW(), NOW()),

('02e00009-0000-4000-8000-000000000009', '02d00001-0000-4000-8000-000000000001', 'success', 'Contract Approved', 'pass',
'{}',
NULL, NULL, 9, '{"x": 250, "y": 550}', NOW(), NOW()),

('02e0000a-0000-4000-8000-000000000010', '02d00001-0000-4000-8000-000000000001', 'fail-rejected', 'Contract Rejected', 'fail',
'{"message": "Contract review was rejected"}',
NULL, NULL, 10, '{"x": 100, "y": 450}', NOW(), NOW()),

-- Access Request with Compliance Check (02d00002)
('02e0000b-0000-4000-8000-000000000011', '02d00002-0000-4000-8000-000000000002', 'notify-receipt', 'Confirm Access Request', 'notification',
'{"recipients": "requester", "template": "request_submitted", "custom_message": "Your access request is being processed and will undergo compliance verification."}',
'check-compliance', NULL, 1, '{"x": 250, "y": 50}', NOW(), NOW()),

('02e0000c-0000-4000-8000-000000000012', '02d00002-0000-4000-8000-000000000002', 'check-compliance', 'Check Access Policies', 'conditional',
'{"condition": "obj.permission_level != ''ADMIN'' OR obj.reason != ''''"}',
'admin-approval', 'fail-compliance', 2, '{"x": 250, "y": 150}', NOW(), NOW()),

('02e0000d-0000-4000-8000-000000000013', '02d00002-0000-4000-8000-000000000002', 'admin-approval', 'Admin Approval Required', 'approval',
'{"approvers": "Admin", "timeout_days": 2, "require_all": false}',
'notify-approved', 'notify-rejected', 3, '{"x": 250, "y": 250}', NOW(), NOW()),

('02e0000e-0000-4000-8000-000000000014', '02d00002-0000-4000-8000-000000000002', 'notify-approved', 'Notify Access Granted', 'notification',
'{"recipients": "requester", "template": "request_approved", "custom_message": "Your access request has been approved. You now have access to the requested resource."}',
'success', NULL, 4, '{"x": 250, "y": 350}', NOW(), NOW()),

('02e0000f-0000-4000-8000-000000000015', '02d00002-0000-4000-8000-000000000002', 'notify-rejected', 'Notify Access Denied', 'notification',
'{"recipients": "requester", "template": "request_rejected", "custom_message": "Your access request was denied. Contact an administrator for more information."}',
'fail-rejected', NULL, 5, '{"x": 400, "y": 300}', NOW(), NOW()),

('02e00010-0000-4000-8000-000000000016', '02d00002-0000-4000-8000-000000000002', 'fail-compliance', 'Compliance Check Failed', 'fail',
'{"message": "Access request does not meet compliance requirements"}',
NULL, NULL, 6, '{"x": 400, "y": 200}', NOW(), NOW()),

('02e00011-0000-4000-8000-000000000017', '02d00002-0000-4000-8000-000000000002', 'success', 'Access Granted', 'pass',
'{}',
NULL, NULL, 7, '{"x": 250, "y": 450}', NOW(), NOW()),

('02e00012-0000-4000-8000-000000000018', '02d00002-0000-4000-8000-000000000002', 'fail-rejected', 'Access Denied', 'fail',
'{"message": "Access request was denied"}',
NULL, NULL, 8, '{"x": 400, "y": 400}', NOW(), NOW()),

-- Product Publish with Delivery (02d00003)
('02e00013-0000-4000-8000-000000000019', '02d00003-0000-4000-8000-000000000003', 'notify-receipt', 'Confirm Publish Request', 'notification',
'{"recipients": "requester", "template": "request_submitted", "custom_message": "Your data product publish request is being processed."}',
'domain-approval', NULL, 1, '{"x": 250, "y": 50}', NOW(), NOW()),

('02e00014-0000-4000-8000-000000000020', '02d00003-0000-4000-8000-000000000003', 'domain-approval', 'Domain Owner Approval', 'approval',
'{"approvers": "DomainOwner", "timeout_days": 5, "require_all": false}',
'trigger-delivery', 'notify-rejected', 2, '{"x": 250, "y": 150}', NOW(), NOW()),

('02e00015-0000-4000-8000-000000000021', '02d00003-0000-4000-8000-000000000003', 'trigger-delivery', 'Execute Delivery', 'delivery',
'{"change_type": "publish", "modes": ["direct"]}',
'notify-published', 'notify-delivery-failed', 3, '{"x": 250, "y": 250}', NOW(), NOW()),

('02e00016-0000-4000-8000-000000000022', '02d00003-0000-4000-8000-000000000003', 'notify-published', 'Notify Publication Success', 'notification',
'{"recipients": "requester", "template": "request_approved", "custom_message": "Your data product has been published and is now available in the marketplace."}',
'success', NULL, 4, '{"x": 250, "y": 350}', NOW(), NOW()),

('02e00017-0000-4000-8000-000000000023', '02d00003-0000-4000-8000-000000000003', 'notify-rejected', 'Notify Publish Rejected', 'notification',
'{"recipients": "requester", "template": "request_rejected", "custom_message": "Your publish request was rejected by the domain owner."}',
'fail-rejected', NULL, 5, '{"x": 400, "y": 200}', NOW(), NOW()),

('02e00018-0000-4000-8000-000000000024', '02d00003-0000-4000-8000-000000000003', 'notify-delivery-failed', 'Notify Delivery Failed', 'notification',
'{"recipients": "requester", "template": "validation_failed", "custom_message": "Publication was approved but delivery failed. An administrator has been notified."}',
'fail-delivery', NULL, 6, '{"x": 400, "y": 300}', NOW(), NOW()),

('02e00019-0000-4000-8000-000000000025', '02d00003-0000-4000-8000-000000000003', 'success', 'Product Published', 'pass',
'{}',
NULL, NULL, 7, '{"x": 250, "y": 450}', NOW(), NOW()),

('02e0001a-0000-4000-8000-000000000026', '02d00003-0000-4000-8000-000000000003', 'fail-rejected', 'Publish Rejected', 'fail',
'{"message": "Data product publish request was rejected"}',
NULL, NULL, 8, '{"x": 400, "y": 400}', NOW(), NOW()),

('02e0001b-0000-4000-8000-000000000027', '02d00003-0000-4000-8000-000000000003', 'fail-delivery', 'Delivery Failed', 'fail',
'{"message": "Data product delivery failed"}',
NULL, NULL, 9, '{"x": 400, "y": 500}', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 21. RATINGS (Comments with rating type) (type=02c)
-- ============================================================================
-- Star ratings for data products and datasets in the marketplace

INSERT INTO comments (id, entity_type, entity_id, comment, comment_type, rating, status, created_by, created_at, updated_at) VALUES
-- Data Product ratings
-- POS Transaction Stream (00700001) - 3 ratings, avg ~4.3
('02c00001-0000-4000-8000-000000000001', 'data_product', '00700001-0000-4000-8000-000000000001', 'Excellent real-time data quality and low latency.', 'rating', 5, 'active', 'alice.johnson@company.com', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'),
('02c00002-0000-4000-8000-000000000002', 'data_product', '00700001-0000-4000-8000-000000000001', 'Good stream but documentation could be better.', 'rating', 4, 'active', 'bob.wilson@company.com', NOW() - INTERVAL '15 days', NOW() - INTERVAL '15 days'),
('02c00003-0000-4000-8000-000000000003', 'data_product', '00700001-0000-4000-8000-000000000001', 'Works well for our use case.', 'rating', 4, 'active', 'carol.brown@company.com', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'),

-- Prepared Sales Transactions (00700002) - 4 ratings, avg 4.0
('02c00004-0000-4000-8000-000000000004', 'data_product', '00700002-0000-4000-8000-000000000002', 'Clean data, easy to integrate.', 'rating', 5, 'active', 'alice.johnson@company.com', NOW() - INTERVAL '25 days', NOW() - INTERVAL '25 days'),
('02c00005-0000-4000-8000-000000000005', 'data_product', '00700002-0000-4000-8000-000000000002', 'Useful for analytics but 1-hour lag is limiting.', 'rating', 3, 'active', 'david.garcia@company.com', NOW() - INTERVAL '18 days', NOW() - INTERVAL '18 days'),
('02c00006-0000-4000-8000-000000000006', 'data_product', '00700002-0000-4000-8000-000000000002', 'Great for BI reporting.', 'rating', 4, 'active', 'bob.wilson@company.com', NOW() - INTERVAL '12 days', NOW() - INTERVAL '12 days'),
('02c00007-0000-4000-8000-000000000007', 'data_product', '00700002-0000-4000-8000-000000000002', 'Solid data product.', 'rating', 4, 'active', 'jane.smith@company.com', NOW() - INTERVAL '5 days', NOW() - INTERVAL '5 days'),

-- Demand Forecast Model Output (00700003) - 2 ratings, avg 3.5
('02c00008-0000-4000-8000-000000000008', 'data_product', '00700003-0000-4000-8000-000000000003', 'Forecasts are helpful but accuracy degrades after 2 weeks.', 'rating', 3, 'active', 'ops-lead@example.com', NOW() - INTERVAL '14 days', NOW() - INTERVAL '14 days'),
('02c00009-0000-4000-8000-000000000009', 'data_product', '00700003-0000-4000-8000-000000000003', 'Good for inventory planning.', 'rating', 4, 'active', 'analyst@example.com', NOW() - INTERVAL '7 days', NOW() - INTERVAL '7 days'),

-- Inventory Optimization Recommendations (00700004) - 1 rating
('02c0000a-0000-4000-8000-000000000010', 'data_product', '00700004-0000-4000-8000-000000000004', 'API integrates well with our systems.', 'rating', 4, 'active', 'ops-lead@example.com', NOW() - INTERVAL '21 days', NOW() - INTERVAL '21 days'),

-- Price Optimization Model Output (00700005) - 2 ratings, avg 4.5
('02c0000b-0000-4000-8000-000000000011', 'data_product', '00700005-0000-4000-8000-000000000005', 'Pricing recommendations are spot on!', 'rating', 5, 'active', 'pricing-analyst@example.com', NOW() - INTERVAL '16 days', NOW() - INTERVAL '16 days'),
('02c0000c-0000-4000-8000-000000000012', 'data_product', '00700005-0000-4000-8000-000000000005', 'Good model, needs more competitive data.', 'rating', 4, 'active', 'analyst@example.com', NOW() - INTERVAL '8 days', NOW() - INTERVAL '8 days'),

-- Customer Marketing Recommendations (00700006) - 3 ratings, avg ~4.7
('02c0000d-0000-4000-8000-000000000013', 'data_product', '00700006-0000-4000-8000-000000000006', 'Exactly what we needed for campaign targeting!', 'rating', 5, 'active', 'marketing-lead@example.com', NOW() - INTERVAL '19 days', NOW() - INTERVAL '19 days'),
('02c0000e-0000-4000-8000-000000000014', 'data_product', '00700006-0000-4000-8000-000000000006', 'Great recommendations, API works well.', 'rating', 5, 'active', 'alice.johnson@company.com', NOW() - INTERVAL '11 days', NOW() - INTERVAL '11 days'),
('02c0000f-0000-4000-8000-000000000015', 'data_product', '00700006-0000-4000-8000-000000000006', 'Good segmentation, occasional misses.', 'rating', 4, 'active', 'carol.brown@company.com', NOW() - INTERVAL '3 days', NOW() - INTERVAL '3 days'),

-- Retail Performance Dashboard Data (00700007) - 2 ratings, avg 5.0
('02c00010-0000-4000-8000-000000000016', 'data_product', '00700007-0000-4000-8000-000000000007', 'Perfect for executive dashboards.', 'rating', 5, 'active', 'analyst@example.com', NOW() - INTERVAL '13 days', NOW() - INTERVAL '13 days'),
('02c00011-0000-4000-8000-000000000017', 'data_product', '00700007-0000-4000-8000-000000000007', 'Love the data freshness and aggregations.', 'rating', 5, 'active', 'bi-dev@example.com', NOW() - INTERVAL '4 days', NOW() - INTERVAL '4 days'),

-- Dataset ratings (entity_type='Dataset' — asset-backed)
-- Customer Master Data (02100001) - 4 ratings, avg ~4.5
('02c00012-0000-4000-8000-000000000018', 'Dataset', '02100001-0000-4000-8000-000000000001', 'Comprehensive customer data, well maintained.', 'rating', 5, 'active', 'alice.johnson@company.com', NOW() - INTERVAL '28 days', NOW() - INTERVAL '28 days'),
('02c00013-0000-4000-8000-000000000019', 'Dataset', '02100001-0000-4000-8000-000000000001', 'Great data quality and documentation.', 'rating', 5, 'active', 'bob.wilson@company.com', NOW() - INTERVAL '22 days', NOW() - INTERVAL '22 days'),
('02c00014-0000-4000-8000-000000000020', 'Dataset', '02100001-0000-4000-8000-000000000001', 'Useful for ML training.', 'rating', 4, 'active', 'carol.brown@company.com', NOW() - INTERVAL '15 days', NOW() - INTERVAL '15 days'),
('02c00015-0000-4000-8000-000000000021', 'Dataset', '02100001-0000-4000-8000-000000000001', 'Solid customer master data.', 'rating', 4, 'active', 'data.scientist@example.com', NOW() - INTERVAL '6 days', NOW() - INTERVAL '6 days'),

-- Customer Engagement Analytics (02100002) - 1 rating
('02c00016-0000-4000-8000-000000000022', 'Dataset', '02100002-0000-4000-8000-000000000002', 'Good engagement metrics.', 'rating', 4, 'active', 'marketing-lead@example.com', NOW() - INTERVAL '17 days', NOW() - INTERVAL '17 days'),

-- Customer Preferences (02100003) - 2 ratings, avg 4.0
('02c00017-0000-4000-8000-000000000023', 'Dataset', '02100003-0000-4000-8000-000000000003', 'Useful preference aggregations.', 'rating', 4, 'active', 'alice.johnson@company.com', NOW() - INTERVAL '12 days', NOW() - INTERVAL '12 days'),
('02c00018-0000-4000-8000-000000000024', 'Dataset', '02100003-0000-4000-8000-000000000003', 'Good for personalization.', 'rating', 4, 'active', 'marketing-lead@example.com', NOW() - INTERVAL '5 days', NOW() - INTERVAL '5 days'),

-- IoT Device Management (02100004) - 2 ratings, avg 4.5
('02c00019-0000-4000-8000-000000000025', 'Dataset', '02100004-0000-4000-8000-000000000004', 'Complete device registry, well structured.', 'rating', 5, 'active', 'bob.wilson@company.com', NOW() - INTERVAL '18 days', NOW() - INTERVAL '18 days'),
('02c0001a-0000-4000-8000-000000000026', 'Dataset', '02100004-0000-4000-8000-000000000004', 'Good for device tracking.', 'rating', 4, 'active', 'carol.brown@company.com', NOW() - INTERVAL '9 days', NOW() - INTERVAL '9 days'),

-- IoT Telemetry (02100005) - 3 ratings, avg ~4.3
('02c0001b-0000-4000-8000-000000000027', 'Dataset', '02100005-0000-4000-8000-000000000005', 'Real-time data is accurate and reliable.', 'rating', 5, 'active', 'bob.wilson@company.com', NOW() - INTERVAL '24 days', NOW() - INTERVAL '24 days'),
('02c0001c-0000-4000-8000-000000000028', 'Dataset', '02100005-0000-4000-8000-000000000005', 'Works well for anomaly detection.', 'rating', 4, 'active', 'david.garcia@company.com', NOW() - INTERVAL '14 days', NOW() - INTERVAL '14 days'),
('02c0001d-0000-4000-8000-000000000029', 'Dataset', '02100005-0000-4000-8000-000000000005', 'Good streaming data quality.', 'rating', 4, 'active', 'data.engineer@example.com', NOW() - INTERVAL '4 days', NOW() - INTERVAL '4 days'),

-- Sales Analytics (02100007) - 3 ratings, avg ~4.7
('02c0001e-0000-4000-8000-000000000030', 'Dataset', '02100007-0000-4000-8000-000000000007', 'Excellent for sales trend analysis.', 'rating', 5, 'active', 'analyst@example.com', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'),
('02c0001f-0000-4000-8000-000000000031', 'Dataset', '02100007-0000-4000-8000-000000000007', 'Good aggregations, easy to consume.', 'rating', 5, 'active', 'frank.finance@example.com', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'),
('02c00020-0000-4000-8000-000000000032', 'Dataset', '02100007-0000-4000-8000-000000000007', 'Reliable for weekly reporting.', 'rating', 4, 'active', 'alice.johnson@company.com', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'),

-- Inventory Levels (02100008) - deprecated, 1 old rating
('02c00021-0000-4000-8000-000000000033', 'Dataset', '02100008-0000-4000-8000-000000000008', 'Was useful, now deprecated.', 'rating', 3, 'active', 'ops-lead@example.com', NOW() - INTERVAL '45 days', NOW() - INTERVAL '45 days')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 13. DATA PROFILING RUNS (type=02d)
-- ============================================================================
-- Track DQX profiling runs that generate quality check suggestions

INSERT INTO data_profiling_runs (id, contract_id, source, schema_names, status, summary_stats, run_id, started_at, completed_at, error_message, triggered_by) VALUES
-- Completed DQX run for Customer Data Contract - generated suggestions
('02d00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'dqx', '["customers"]', 'completed', '{"rows_profiled": 150000, "columns_analyzed": 10, "suggestions_generated": 6}', 'run_abc123', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days' + INTERVAL '15 minutes', NULL, 'data.steward@example.com'),

-- Completed DQX run for IoT Device Data Contract - generated suggestions
('02d00002-0000-4000-8000-000000000002', '00400004-0000-4000-8000-000000000004', 'dqx', '["devices"]', 'completed', '{"rows_profiled": 25000, "columns_analyzed": 5, "suggestions_generated": 4}', 'run_def456', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day' + INTERVAL '8 minutes', NULL, 'iot.admin@example.com'),

-- Failed DQX run for illustration
('02d00003-0000-4000-8000-000000000003', '00400006-0000-4000-8000-000000000006', 'dqx', '["transactions"]', 'failed', NULL, 'run_ghi789', NOW() - INTERVAL '3 hours', NOW() - INTERVAL '3 hours' + INTERVAL '2 minutes', 'Connection timeout: Unable to access catalog finance.transactions_raw', 'finance.analyst@example.com')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 14. SUGGESTED QUALITY CHECKS (type=02e)
-- ============================================================================
-- DQX-generated quality check suggestions pending review

INSERT INTO suggested_quality_checks (id, profile_run_id, contract_id, source, schema_name, property_name, status, name, description, level, dimension, severity, type, rule, confidence_score, rationale, created_at) VALUES
-- Customer Data Contract suggestions (from run 02d00001)
-- email column checks
('02e00001-0000-4000-8000-000000000001', '02d00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'dqx', 'customers', 'email', 'pending', 'Email Format Validation', 'Validate that email addresses match standard email format', 'property', 'conformity', 'error', 'library', 'is_email', '0.95', 'Column contains email addresses. 99.2% of sampled values match email pattern. Recommend enforcing email format validation.', NOW() - INTERVAL '2 days'),

('02e00002-0000-4000-8000-000000000002', '02d00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'dqx', 'customers', 'email', 'pending', 'Email Not Null', 'Ensure email field is never null', 'property', 'completeness', 'error', 'library', 'is_not_null', '0.98', 'Email is marked as required. 0 null values found in 150,000 rows sampled. Recommend adding not-null constraint.', NOW() - INTERVAL '2 days'),

-- phone_number column check
('02e00003-0000-4000-8000-000000000003', '02d00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'dqx', 'customers', 'phone_number', 'pending', 'Phone E.164 Format', 'Validate phone numbers follow E.164 international format', 'property', 'conformity', 'warning', 'library', 'matches_regex', '0.82', 'Phone numbers should follow E.164 format. 82% of non-null values match pattern. Some legacy records may need migration.', NOW() - INTERVAL '2 days'),

-- country_code column check
('02e00004-0000-4000-8000-000000000004', '02d00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'dqx', 'customers', 'country_code', 'pending', 'ISO 3166-1 Alpha-2 Code', 'Validate country codes are valid ISO 3166-1 alpha-2 codes', 'property', 'conformity', 'error', 'library', 'is_in_list', '0.91', 'Detected 2-letter country codes. 99.8% match ISO 3166-1 alpha-2 standard. Recommend enforcing allowed values list.', NOW() - INTERVAL '2 days'),

-- date_of_birth column check
('02e00005-0000-4000-8000-000000000005', '02d00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'dqx', 'customers', 'date_of_birth', 'pending', 'Reasonable Birth Date Range', 'Ensure birth dates fall within reasonable range (1900-present, age >= 13)', 'property', 'accuracy', 'warning', 'library', 'is_between', '0.88', 'Date of birth values span wide range. Recommend constraining to reasonable bounds for customer age validation.', NOW() - INTERVAL '2 days'),

-- account_status column check (already accepted)
('02e00006-0000-4000-8000-000000000006', '02d00001-0000-4000-8000-000000000001', '00400001-0000-4000-8000-000000000001', 'dqx', 'customers', 'account_status', 'accepted', 'Account Status Enum Values', 'Validate account_status contains only allowed values', 'property', 'conformity', 'error', 'library', 'is_in_list', '0.99', 'Detected enum-like values: active, suspended, closed, pending_verification. 100% of values match expected set.', NOW() - INTERVAL '2 days'),

-- IoT Device Data Contract suggestions (from run 02d00002)
-- device_serial uniqueness check
('02e00007-0000-4000-8000-000000000007', '02d00002-0000-4000-8000-000000000002', '00400004-0000-4000-8000-000000000004', 'dqx', 'devices', 'device_serial', 'pending', 'Serial Number Uniqueness', 'Ensure device serial numbers are unique across all devices', 'property', 'uniqueness', 'error', 'library', 'is_unique', '0.97', 'Device serial numbers should be unique identifiers. 0 duplicates found in 25,000 devices sampled.', NOW() - INTERVAL '1 day'),

-- device_type enum check
('02e00008-0000-4000-8000-000000000008', '02d00002-0000-4000-8000-000000000002', '00400004-0000-4000-8000-000000000004', 'dqx', 'devices', 'device_type', 'pending', 'Device Type Enum Values', 'Validate device_type contains only allowed values: sensor, actuator, gateway, controller', 'property', 'conformity', 'error', 'library', 'is_in_list', '0.99', 'Detected 4 distinct device types matching expected categories. Recommend enforcing enum constraint.', NOW() - INTERVAL '1 day'),

-- status enum check
('02e00009-0000-4000-8000-000000000009', '02d00002-0000-4000-8000-000000000002', '00400004-0000-4000-8000-000000000004', 'dqx', 'devices', 'status', 'pending', 'Device Status Enum Values', 'Validate status contains only allowed values: active, inactive, maintenance, faulty, decommissioned', 'property', 'conformity', 'error', 'library', 'is_in_list', '0.99', 'Detected 5 distinct status values matching expected device lifecycle states.', NOW() - INTERVAL '1 day'),

-- Table-level row count check
('02e0000a-0000-4000-8000-000000000010', '02d00002-0000-4000-8000-000000000002', '00400004-0000-4000-8000-000000000004', 'dqx', 'devices', NULL, 'pending', 'Minimum Row Count', 'Ensure devices table has at least 1 row (not empty)', 'object', 'completeness', 'warning', 'library', 'row_count', '0.75', 'Table contains 25,000 rows. Recommend adding minimum row count check to detect empty table scenarios.', NOW() - INTERVAL '1 day')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 22. BUSINESS ROLES (type=0f0)
-- ============================================================================
-- Named roles that can be assigned as ownership roles across all object types.

INSERT INTO business_roles (id, name, description, category, is_system, status, created_by, created_at, updated_at) VALUES
-- Governance roles
('0f000001-0000-4000-8000-000000000001', 'Data Owner',           'Accountable for the quality, integrity, and lifecycle of a data asset or product.',                     'governance',   true,  'active', 'system@demo', NOW(), NOW()),
('0f000002-0000-4000-8000-000000000002', 'Domain Owner',         'Responsible for all data products and standards within a data domain.',                                'governance',   true,  'active', 'system@demo', NOW(), NOW()),
('0f000003-0000-4000-8000-000000000003', 'Data Steward',         'Maintains metadata quality, enforces governance policies, and resolves data issues.',                   'governance',   true,  'active', 'system@demo', NOW(), NOW()),
('0f000004-0000-4000-8000-000000000004', 'Business Term Owner',  'Defines and maintains business glossary terms and their relationships.',                               'governance',   true,  'active', 'system@demo', NOW(), NOW()),

-- Technical roles
('0f000005-0000-4000-8000-000000000005', 'Technical Owner',      'Responsible for the technical implementation, pipelines, and infrastructure of a data product.',        'technical',    true,  'active', 'system@demo', NOW(), NOW()),
('0f000006-0000-4000-8000-000000000006', 'Pipeline Owner',       'Owns and operates the ETL/ELT pipelines that produce or transform data.',                              'technical',    false, 'active', 'system@demo', NOW(), NOW()),

-- Business roles
('0f000007-0000-4000-8000-000000000007', 'Business Sponsor',     'Executive or senior stakeholder sponsoring a data product or initiative.',                              'business',     true,  'active', 'system@demo', NOW(), NOW()),
('0f000008-0000-4000-8000-000000000008', 'Subject Matter Expert','Provides domain expertise for defining schemas, quality rules, and business logic.',                    'business',     false, 'active', 'system@demo', NOW(), NOW()),

-- Operational roles
('0f000009-0000-4000-8000-000000000009', 'SLA Manager',          'Monitors and enforces service-level agreements for data products.',                                    'operational',  false, 'active', 'system@demo', NOW(), NOW()),
('0f00000a-0000-4000-8000-000000000010', 'Compliance Officer',   'Ensures data products and assets comply with regulatory and internal policies.',                       'operational',  true,  'active', 'system@demo', NOW(), NOW()),

-- Deprecated example
('0f00000b-0000-4000-8000-000000000011', 'Data Custodian',       'Legacy role replaced by Data Steward. Kept for historical ownership records.',                         'governance',   false, 'deprecated', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;



-- ============================================================================
-- 23b. DELIVERY METHODS (type=0f4)
-- ============================================================================
-- Defines how an output port (deliverable) delivers data to consumers.

INSERT INTO delivery_methods (id, name, description, category, is_system, status, created_by, created_at, updated_at) VALUES
-- Access-based delivery
('0f400001-0000-4000-8000-000000000001', 'Table Access',       'Grants SELECT privileges on underlying tables in Unity Catalog.',                              'access',    true,  'active', 'system@demo', NOW(), NOW()),
('0f400002-0000-4000-8000-000000000002', 'View Access',        'Grants SELECT privileges on a curated view layer.',                                            'access',    true,  'active', 'system@demo', NOW(), NOW()),
('0f400003-0000-4000-8000-000000000003', 'Data Share',         'Shares data via Delta Sharing or Databricks-to-Databricks sharing.',                           'access',    true,  'active', 'system@demo', NOW(), NOW()),

-- Endpoint-based delivery
('0f400004-0000-4000-8000-000000000004', 'Serving Endpoint',   'Exposes an ML model or feature via a Databricks Model Serving endpoint.',                      'endpoint',  true,  'active', 'system@demo', NOW(), NOW()),
('0f400005-0000-4000-8000-000000000005', 'API Endpoint',       'Delivers data through a REST or GraphQL API.',                                                 'endpoint',  true,  'active', 'system@demo', NOW(), NOW()),
('0f400006-0000-4000-8000-000000000006', 'Dashboard',          'Provides data via an interactive dashboard (e.g., Databricks SQL Dashboard, Lakeview).',       'endpoint',  true,  'active', 'system@demo', NOW(), NOW()),

-- Export-based delivery
('0f400007-0000-4000-8000-000000000007', 'File Export',        'Delivers data as exported files (CSV, Parquet, JSON) to a cloud storage location.',            'export',    true,  'active', 'system@demo', NOW(), NOW()),

-- Streaming delivery
('0f400008-0000-4000-8000-000000000008', 'Streaming',          'Delivers data via a streaming channel (e.g., Kafka topic, Delta Live Tables streaming).',      'streaming', true,  'active', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 24. ASSET TYPES — removed (now synced from ontos-ontology.ttl at startup)
-- ============================================================================


-- ============================================================================
-- 25. ASSETS (type=0f3)
-- ============================================================================
-- Concrete cataloged objects linked to asset types, domains, and data products.

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES

-- Systems
('0f300001-0000-4000-8000-000000000001',
 'Databricks Lakehouse',
 'Primary Databricks workspace for all lakehouse tables and pipelines.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'System' LIMIT 1), '0f200009-0000-4000-8000-000000000009'), 'Databricks', 'https://adb-1234567890.azuredatabricks.net',
 '00000001-0000-4000-8000-000000000001',
 '{"type": "lakehouse", "environment": "production", "cloud": "Azure"}',
 '["production", "primary"]',
 'active', 'system@demo', NOW(), NOW()),

('0f300002-0000-4000-8000-000000000002',
 'Power BI Service',
 'Enterprise Power BI tenant for dashboards and reports.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'System' LIMIT 1), '0f200009-0000-4000-8000-000000000009'), 'Power BI', 'https://app.powerbi.com/groups/retail-analytics',
 '00000001-0000-4000-8000-000000000001',
 '{"type": "bi_platform", "environment": "production"}',
 '["analytics", "reporting"]',
 'active', 'system@demo', NOW(), NOW()),

-- Tables (Retail)
('0f300003-0000-4000-8000-000000000003',
 'lakehouse.retail.curated.pos_transactions',
 'Curated POS transaction table with validated, deduplicated retail transactions.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.retail.curated.pos_transactions',
 '0000000c-0000-4000-8000-000000000012',
 '{"catalog": "lakehouse", "schema": "retail_curated", "table_name": "pos_transactions", "row_count": 12500000, "format": "delta"}',
 '["curated", "retail", "pii-free"]',
 'active', 'system@demo', NOW(), NOW()),

('0f300004-0000-4000-8000-000000000004',
 'lakehouse.retail.curated.inventory_levels',
 'Current and historical inventory levels by store, SKU, and date.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.retail.curated.inventory_levels',
 '0000000c-0000-4000-8000-000000000012',
 '{"catalog": "lakehouse", "schema": "retail_curated", "table_name": "inventory_levels", "row_count": 3200000, "format": "delta"}',
 '["curated", "supply-chain"]',
 'active', 'system@demo', NOW(), NOW()),

-- Tables (Customer)
('0f300005-0000-4000-8000-000000000005',
 'lakehouse.customer.curated.customer360',
 'Unified customer profile combining CRM, web, and transaction data.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.customer.curated.customer360',
 '00000007-0000-4000-8000-000000000007',
 '{"catalog": "lakehouse", "schema": "customer_curated", "table_name": "customer360", "row_count": 850000, "format": "delta"}',
 '["curated", "pii", "customer"]',
 'active', 'system@demo', NOW(), NOW()),

-- Tables (Finance)
('0f300006-0000-4000-8000-000000000006',
 'lakehouse.finance.curated.invoices',
 'Validated invoice records for financial reporting and compliance.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.finance.curated.invoices',
 '00000002-0000-4000-8000-000000000002',
 '{"catalog": "lakehouse", "schema": "finance_curated", "table_name": "invoices", "row_count": 2100000, "format": "delta"}',
 '["curated", "finance", "sox-compliant"]',
 'active', 'system@demo', NOW(), NOW()),

-- Dashboard
('0f300007-0000-4000-8000-000000000007',
 'Retail Performance Overview',
 'Executive dashboard showing daily KPIs: revenue, transactions, basket size, conversion.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Dashboard' LIMIT 1), '0f200004-0000-4000-8000-000000000004'), 'Power BI', 'https://app.powerbi.com/groups/retail-analytics/reports/rpt-001',
 '0000000d-0000-4000-8000-000000000013',
 '{"tool": "Power BI", "workspace": "retail-analytics", "report_id": "rpt-001"}',
 '["executive", "kpi", "retail"]',
 'active', 'system@demo', NOW(), NOW()),

('0f300008-0000-4000-8000-000000000008',
 'Customer Lifetime Value Overview',
 'Dashboard showing CLV metrics, segmentation, and churn prediction outputs.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Dashboard' LIMIT 1), '0f200004-0000-4000-8000-000000000004'), 'Power BI', 'https://app.powerbi.com/groups/customer-analytics/reports/rpt-002',
 '00000007-0000-4000-8000-000000000007',
 '{"tool": "Power BI", "workspace": "customer-analytics", "report_id": "rpt-002"}',
 '["analytics", "customer", "ml-driven"]',
 'active', 'system@demo', NOW(), NOW()),

-- API Endpoint
('0f300009-0000-4000-8000-000000000009',
 'POST /v1/customers/search',
 'Customer search API endpoint for internal applications.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'API Endpoint' LIMIT 1), '0f200005-0000-4000-8000-000000000005'), 'Internal API', 'https://api.internal.example.com/v1/customers/search',
 '00000007-0000-4000-8000-000000000007',
 '{"method": "POST", "path": "/v1/customers/search", "auth_scheme": "OAuth2", "version": "v1"}',
 '["api", "customer", "internal"]',
 'active', 'system@demo', NOW(), NOW()),

-- File Dataset (mapped to Dataset type since FileDataset not in ontology)
('0f30000a-0000-4000-8000-000000000010',
 'Marketing Raw Clickstream Events',
 'Raw clickstream parquet files from web analytics, partitioned by date.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Dataset' LIMIT 1), '0f200006-0000-4000-8000-000000000006'), 'Azure ADLS', 'abfss://raw@datalake.dfs.core.windows.net/marketing/clickstream/',
 '00000004-0000-4000-8000-000000000004',
 '{"storage_path": "abfss://raw@datalake.dfs.core.windows.net/marketing/clickstream/", "format": "parquet", "partition_keys": ["date"]}',
 '["raw", "marketing", "clickstream"]',
 'active', 'system@demo', NOW(), NOW()),

-- Stream
('0f30000b-0000-4000-8000-000000000011',
 'iot-device-telemetry',
 'Kafka topic receiving real-time IoT device sensor readings.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Stream' LIMIT 1), '0f200008-0000-4000-8000-000000000008'), 'Confluent Kafka', 'kafka://broker.internal:9092/iot-device-telemetry',
 '0000000a-0000-4000-8000-000000000010',
 '{"stream_name": "iot-device-telemetry", "platform": "Confluent Kafka", "partitions": 12, "retention_hours": 168}',
 '["streaming", "iot", "real-time"]',
 'active', 'system@demo', NOW(), NOW()),

-- ML Model
('0f30000c-0000-4000-8000-000000000012',
 'demand-forecast-v3',
 'XGBoost demand forecasting model registered in Unity Catalog.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'ML Model' LIMIT 1), '0f200007-0000-4000-8000-000000000007'), 'Databricks', 'models:/demand-forecast-v3/Production',
 '0000000d-0000-4000-8000-000000000013',
 '{"model_name": "demand-forecast-v3", "framework": "xgboost", "version": "3", "stage": "Production", "metrics": {"rmse": 12.4, "mape": 0.08}}',
 '["ml", "forecasting", "production"]',
 'active', 'system@demo', NOW(), NOW()),

-- Deprecated asset
('0f30000d-0000-4000-8000-000000000013',
 'legacy.sales.raw.transactions_v1',
 'Deprecated raw sales table from legacy ETL pipeline. Replaced by POS Transaction Stream.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'legacy.sales.raw.transactions_v1',
 '00000003-0000-4000-8000-000000000003',
 '{"catalog": "legacy", "schema": "sales_raw", "table_name": "transactions_v1", "row_count": 0, "format": "delta"}',
 '["deprecated", "legacy"]',
 'deprecated', 'system@demo', NOW() - INTERVAL '180 days', NOW() - INTERVAL '30 days'),

-- Column assets for pos_transactions table (0f300003)
('0f500001-0000-4000-8000-000000000001',
 'transaction_id', 'Unique transaction identifier',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.curated.pos_transactions.transaction_id',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "STRING", "nullable": false, "is_primary_key": true}',
 '["retail"]', 'active', 'system@demo', NOW(), NOW()),
('0f500002-0000-4000-8000-000000000002',
 'store_id', 'Store where the transaction occurred',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.curated.pos_transactions.store_id',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "STRING", "nullable": false}',
 '["retail"]', 'active', 'system@demo', NOW(), NOW()),
('0f500003-0000-4000-8000-000000000003',
 'transaction_amount', 'Total transaction amount in local currency',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.curated.pos_transactions.transaction_amount',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "DECIMAL(10,2)", "nullable": false}',
 '["retail", "financial"]', 'active', 'system@demo', NOW(), NOW()),
('0f500004-0000-4000-8000-000000000004',
 'transaction_timestamp', 'When the transaction was recorded',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.curated.pos_transactions.transaction_timestamp',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "TIMESTAMP", "nullable": false}',
 '["retail"]', 'active', 'system@demo', NOW(), NOW()),

-- Column assets for inventory_levels table (0f300004)
('0f500005-0000-4000-8000-000000000005',
 'product_id', 'SKU identifier for the product',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.curated.inventory_levels.product_id',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "STRING", "nullable": false, "is_primary_key": true}',
 '["supply-chain"]', 'active', 'system@demo', NOW(), NOW()),
('0f500006-0000-4000-8000-000000000006',
 'warehouse_id', 'Warehouse or distribution center identifier',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.curated.inventory_levels.warehouse_id',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "STRING", "nullable": false}',
 '["supply-chain"]', 'active', 'system@demo', NOW(), NOW()),
('0f500007-0000-4000-8000-000000000007',
 'quantity', 'Current inventory quantity on hand',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.curated.inventory_levels.quantity',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "INT", "nullable": false}',
 '["supply-chain"]', 'active', 'system@demo', NOW(), NOW()),
('0f500008-0000-4000-8000-000000000008',
 'last_updated', 'Timestamp of last inventory update',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.curated.inventory_levels.last_updated',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "TIMESTAMP", "nullable": true}',
 '["supply-chain"]', 'active', 'system@demo', NOW(), NOW()),

-- Column assets for Retail Events Stream table (0250000e)
('0f500009-0000-4000-8000-000000000009',
 'event_id', 'Unique event identifier',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.events.retail_events_stream.event_id',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "STRING", "nullable": false, "is_primary_key": true}',
 '["retail", "streaming"]', 'active', 'system@demo', NOW(), NOW()),
('0f50000a-0000-4000-8000-000000000010',
 'store_id', 'Originating store for the retail event',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.events.retail_events_stream.store_id',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "STRING", "nullable": false}',
 '["retail", "streaming"]', 'active', 'system@demo', NOW(), NOW()),
('0f50000b-0000-4000-8000-000000000011',
 'transaction_amount', 'Event transaction amount',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.events.retail_events_stream.transaction_amount',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "DECIMAL(10,2)", "nullable": false}',
 '["retail", "streaming", "financial"]', 'active', 'system@demo', NOW(), NOW()),
('0f50000c-0000-4000-8000-000000000012',
 'event_timestamp', 'When the retail event occurred',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.events.retail_events_stream.event_timestamp',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "TIMESTAMP", "nullable": false}',
 '["retail", "streaming"]', 'active', 'system@demo', NOW(), NOW()),

-- Column assets for Sales Metrics MV view (0250000f)
('0f50000d-0000-4000-8000-000000000013',
 'total_revenue', 'Aggregated total revenue',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.analytics.sales_metrics_mv.total_revenue',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "DECIMAL(15,2)", "nullable": false}',
 '["retail", "analytics", "kpi"]', 'active', 'system@demo', NOW(), NOW()),
('0f50000e-0000-4000-8000-000000000014',
 'avg_order_value', 'Average order value metric',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.analytics.sales_metrics_mv.avg_order_value',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "DECIMAL(10,2)", "nullable": false}',
 '["retail", "analytics", "kpi"]', 'active', 'system@demo', NOW(), NOW()),
('0f50000f-0000-4000-8000-000000000015',
 'transaction_count', 'Total number of transactions',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.analytics.sales_metrics_mv.transaction_count',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "BIGINT", "nullable": false}',
 '["retail", "analytics"]', 'active', 'system@demo', NOW(), NOW()),
('0f500010-0000-4000-8000-000000000016',
 'period_start', 'Start of the aggregation period',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Column' LIMIT 1), '0f20000a-0000-4000-8000-000000000010'), 'Databricks', 'lakehouse.retail.analytics.sales_metrics_mv.period_start',
 '0000000c-0000-4000-8000-000000000012',
 '{"data_type": "DATE", "nullable": false}',
 '["retail", "analytics"]', 'active', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 25b. BUSINESS TERM ASSETS (type=0f7)
-- ============================================================================
-- BusinessTerm assets for business lineage CUJ.

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES
('0f700001-0000-4000-8000-000000000001',
 'Customer', 'A party who has purchased or is eligible to purchase goods or services from the company.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Business Term' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"definition": "A party who has purchased or is eligible to purchase goods or services from the company. Includes both B2C end-consumers and B2B accounts.", "synonyms": "Client, Account, Buyer", "examples": "Retail customer with loyalty card, Enterprise account with MSA"}',
 '["customer", "core-entity", "pii"]', 'active', 'system@demo', NOW(), NOW()),
('0f700002-0000-4000-8000-000000000002',
 'Customer Lifetime Value', 'Predicted total net profit attributed to the entire future relationship with a customer.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Business Term' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"definition": "Predicted total net profit attributed to the entire future relationship with a customer. Calculated using RFM model and historical purchase data.", "synonyms": "CLV, CLTV, LTV", "examples": "A customer with CLV of $2,500 is a high-value segment target"}',
 '["customer", "analytics", "kpi"]', 'active', 'system@demo', NOW(), NOW()),
('0f700003-0000-4000-8000-000000000003',
 'Active Customer', 'A customer who has completed at least one transaction within the last 12 months.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Business Term' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"definition": "A customer who has completed at least one purchase transaction within the trailing 12-month window.", "synonyms": "Current Customer, Engaged Customer", "examples": "Customers in the active segment for marketing campaigns"}',
 '["customer", "segmentation"]', 'active', 'system@demo', NOW(), NOW()),
('0f700004-0000-4000-8000-000000000004',
 'Transaction', 'A financial exchange event recording the purchase of goods or services.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Business Term' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '0000000c-0000-4000-8000-000000000012',
 '{"definition": "A financial exchange event recording the purchase of goods or services at a point of sale or online.", "synonyms": "Purchase, Sale, Order", "examples": "POS receipt #12345, Online order #ORD-67890"}',
 '["retail", "financial", "core-entity"]', 'active', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 25c. LOGICAL ENTITY & ATTRIBUTE ASSETS (type=0f8)
-- ============================================================================
-- Logical model entities bridging business terms to physical implementations.

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES
-- LogicalEntity: Customer
('0f800001-0000-4000-8000-000000000001',
 'Customer', 'Logical entity representing a customer in the conceptual data model.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Logical Entity' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"entityDomain": "Customer", "entitySupertype": "Party"}',
 '["customer", "cdm", "logical-model"]', 'active', 'system@demo', NOW(), NOW()),
-- LogicalEntity: Transaction
('0f800002-0000-4000-8000-000000000002',
 'Transaction', 'Logical entity representing a sales/purchase transaction.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Logical Entity' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '0000000c-0000-4000-8000-000000000012',
 '{"entityDomain": "Sales", "entitySupertype": "Event"}',
 '["retail", "cdm", "logical-model"]', 'active', 'system@demo', NOW(), NOW()),

-- LogicalAttributes for Customer
('0f810001-0000-4000-8000-000000000001',
 'Customer.Id', 'Unique business identifier for a customer.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Logical Attribute' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"attributeDataType": "String", "isIdentifier": true, "sensitivityLevel": "internal"}',
 '["customer", "identifier"]', 'active', 'system@demo', NOW(), NOW()),
('0f810002-0000-4000-8000-000000000002',
 'Customer.Name', 'Full legal name of the customer.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Logical Attribute' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"attributeDataType": "String", "isIdentifier": false, "sensitivityLevel": "pii"}',
 '["customer", "pii"]', 'active', 'system@demo', NOW(), NOW()),
('0f810003-0000-4000-8000-000000000003',
 'Customer.Email', 'Primary email address of the customer.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Logical Attribute' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"attributeDataType": "String", "isIdentifier": false, "sensitivityLevel": "pii"}',
 '["customer", "pii", "contact"]', 'active', 'system@demo', NOW(), NOW()),
('0f810004-0000-4000-8000-000000000004',
 'Customer.Phone', 'Primary phone number of the customer.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Logical Attribute' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"attributeDataType": "String", "isIdentifier": false, "sensitivityLevel": "pii"}',
 '["customer", "pii", "contact"]', 'active', 'system@demo', NOW(), NOW()),

-- LogicalAttributes for Transaction
('0f810005-0000-4000-8000-000000000005',
 'Transaction.Id', 'Unique business identifier for a transaction.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Logical Attribute' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '0000000c-0000-4000-8000-000000000012',
 '{"attributeDataType": "String", "isIdentifier": true, "sensitivityLevel": "internal"}',
 '["retail", "identifier"]', 'active', 'system@demo', NOW(), NOW()),
('0f810006-0000-4000-8000-000000000006',
 'Transaction.Amount', 'Monetary value of the transaction.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Logical Attribute' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '0000000c-0000-4000-8000-000000000012',
 '{"attributeDataType": "Decimal", "isIdentifier": false, "sensitivityLevel": "internal"}',
 '["retail", "financial"]', 'active', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 25d. DELIVERY CHANNEL ASSETS (type=0f9)
-- ============================================================================
-- Delivery channels through which data products expose data.

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES
('0f900001-0000-4000-8000-000000000001',
 'Customer 360 API', 'REST API serving unified customer profile data to downstream applications.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Delivery Channel' LIMIT 1), '00000000-0000-0000-0000-000000000000'), 'Databricks', 'https://api.example.com/v1/customers',
 '00000007-0000-4000-8000-000000000007',
 '{"channelType": "api", "channelUrl": "https://api.example.com/v1/customers", "channelFormat": "json", "refreshFrequency": "real_time"}',
 '["customer", "api", "real-time"]', 'active', 'system@demo', NOW(), NOW()),
('0f900002-0000-4000-8000-000000000002',
 'CLV Dashboard', 'Interactive dashboard showing customer lifetime value trends and segmentation.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Delivery Channel' LIMIT 1), '00000000-0000-0000-0000-000000000000'), 'Databricks', 'https://dashboards.example.com/clv',
 '00000007-0000-4000-8000-000000000007',
 '{"channelType": "dashboard", "channelUrl": "https://dashboards.example.com/clv", "channelFormat": "html", "refreshFrequency": "daily"}',
 '["customer", "analytics", "dashboard"]', 'active', 'system@demo', NOW(), NOW()),
('0f900003-0000-4000-8000-000000000003',
 'Daily Revenue Report', 'Automated daily revenue summary report delivered to finance stakeholders.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Delivery Channel' LIMIT 1), '00000000-0000-0000-0000-000000000000'), 'Databricks', NULL,
 '0000000c-0000-4000-8000-000000000012',
 '{"channelType": "report", "channelFormat": "pdf", "refreshFrequency": "daily"}',
 '["retail", "finance", "report"]', 'active', 'system@demo', NOW(), NOW()),
('0f900004-0000-4000-8000-000000000004',
 'Partner Data Feed', 'Nightly Parquet export of anonymized sales data for partner analytics.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Delivery Channel' LIMIT 1), '00000000-0000-0000-0000-000000000000'), 'Databricks', 's3://partner-data/exports/',
 '0000000c-0000-4000-8000-000000000012',
 '{"channelType": "file_export", "channelFormat": "parquet", "refreshFrequency": "daily"}',
 '["retail", "partner", "export"]', 'active', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 25e. POLICY ASSETS (type=0f1)
-- ============================================================================
-- Formal, reusable rules for data access, usage, protection, and management.
-- Previously stored in a dedicated policies table, now modeled as Policy assets.

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES
-- Access / Privacy policies
('0f100001-0000-4000-8000-000000000001',
 'Customer PII Protection Policy',
 'Customer personally identifiable information must not be visible in any external-facing output. Only users with the Customer Analytics role may view unmasked email and phone fields.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Policy' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"policyType": "access_privacy", "enforcementLevel": "mandatory", "policyContent": "## Scope\nApplies to all assets and data products in the Customer domain.\n\n## Rules\n1. Columns classified as PII (email, phone, address, SSN) MUST be masked in external dashboards and APIs.\n2. Only users with the **Customer Analytics** group may access unmasked PII columns.\n3. Row-level security must filter customer data to the originating region.\n\n## Enforcement\n- Column masking policies in Unity Catalog.\n- Row-level filters on customer_region.", "version": "v1.0", "regulation": "GDPR, CCPA"}',
 '["access-privacy", "mandatory", "pii", "gdpr"]',
 'active', 'system@demo', NOW() - INTERVAL '90 days', NOW() - INTERVAL '5 days'),

('0f100002-0000-4000-8000-000000000002',
 'Employee Data Access Policy',
 'Employee HR data is restricted to HR department members and authorized managers.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Policy' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000009-0000-4000-8000-000000000009',
 '{"policyType": "access_privacy", "enforcementLevel": "mandatory", "policyContent": "## Scope\nHuman Resources domain.\n\n## Rules\n1. Salary, SSN, and performance review data are restricted to HR group members.\n2. Managers may view direct-report summaries only.\n3. No bulk export of employee PII without VP-level approval.", "version": "v1.1", "regulation": "SOX, internal HR policy"}',
 '["access-privacy", "mandatory", "hr"]',
 'active', 'system@demo', NOW() - INTERVAL '120 days', NOW() - INTERVAL '10 days'),

-- Data Quality policies
('0f100003-0000-4000-8000-000000000003',
 'Finance Zero-Null Key Fields Policy',
 'For all Finance domain products, key fields (Invoice.Id, Booking.Amount) must have 0% nulls in production outputs, and data must be refreshed at least once per day.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Policy' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000002-0000-4000-8000-000000000002',
 '{"policyType": "data_quality", "enforcementLevel": "automated", "policyContent": "## Scope\nFinance domain — all production data products.\n\n## Rules\n1. Primary key fields must have null_rate = 0%.\n2. Amount/currency fields must have null_rate = 0%.\n3. Freshness SLA: data must be updated within 24 hours.\n4. Duplicate rate for key fields must be < 0.01%.\n\n## Enforcement\nEncoded as expectations in ODCS contracts. Validated by nightly compliance runs.", "version": "v2.0", "freshness_hours": 24}',
 '["data-quality", "automated", "finance"]',
 'active', 'system@demo', NOW() - INTERVAL '60 days', NOW() - INTERVAL '2 days'),

('0f100004-0000-4000-8000-000000000004',
 'Retail Transactions Completeness Policy',
 'POS transaction data must be complete — no missing store_id, transaction_id, or amount fields in curated layers.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Policy' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '0000000c-0000-4000-8000-000000000012',
 '{"policyType": "data_quality", "enforcementLevel": "automated", "policyContent": "## Scope\nRetail Operations and Retail Analytics domains.\n\n## Rules\n1. store_id, transaction_id, timestamp, and amount are mandatory.\n2. Null rate for these fields must be 0% in curated/gold layers.\n3. Raw/bronze layers may have up to 0.1% nulls with alerting.\n\n## Enforcement\nGreat Expectations suites attached to pipeline output.", "version": "v1.0"}',
 '["data-quality", "automated", "retail"]',
 'active', 'system@demo', NOW() - INTERVAL '45 days', NOW() - INTERVAL '7 days'),

-- Retention / Lifecycle policies
('0f100005-0000-4000-8000-000000000005',
 'Marketing Raw Events 90-Day Retention',
 'Raw event data in the Marketing domain must be retained for 90 days, then aggregated and anonymized.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Policy' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000004-0000-4000-8000-000000000004',
 '{"policyType": "retention_lifecycle", "enforcementLevel": "automated", "policyContent": "## Scope\nMarketing domain — raw/bronze event tables.\n\n## Rules\n1. Raw clickstream and campaign event data retained for 90 days.\n2. After 90 days, data must be aggregated to daily granularity and anonymized (remove user identifiers).\n3. Aggregated data retained for 3 years.\n4. Deletion jobs must run weekly.\n\n## Enforcement\nScheduled Databricks job manages TTL and aggregation.", "version": "v1.0", "retention_days": 90}',
 '["retention", "automated", "marketing"]',
 'active', 'system@demo', NOW() - INTERVAL '30 days', NOW() - INTERVAL '3 days'),

('0f100006-0000-4000-8000-000000000006',
 'IoT Telemetry Data Lifecycle',
 'IoT sensor readings retained at full resolution for 30 days, downsampled to 1-minute averages for 1 year, then purged.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Policy' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '0000000a-0000-4000-8000-000000000010',
 '{"policyType": "retention_lifecycle", "enforcementLevel": "advisory", "policyContent": "## Scope\nIoT domain.\n\n## Rules\n1. Full-resolution telemetry: 30-day retention.\n2. 1-minute downsampled averages: 1-year retention.\n3. Device metadata retained indefinitely.\n4. Alert/anomaly events retained for 2 years.\n\n## Enforcement\nPending automation — currently manual.", "version": "v0.9"}',
 '["retention", "advisory", "iot", "draft"]',
 'draft', 'system@demo', NOW() - INTERVAL '15 days', NOW() - INTERVAL '1 day'),

-- Usage / Purpose limitation
('0f100007-0000-4000-8000-000000000007',
 'EU Customer Data ML Training Restriction',
 'EU customer data may not be used to train models for targeted advertising without explicit consent.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Policy' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 '00000007-0000-4000-8000-000000000007',
 '{"policyType": "usage_purpose", "enforcementLevel": "mandatory", "policyContent": "## Scope\nCustomer and Marketing domains — datasets labeled as \"training datasets\" or \"ML outputs\".\n\n## Rules\n1. Datasets containing EU customer records (country in EU member states) MUST NOT be fed into advertising ML pipelines.\n2. Exception: explicit opt-in consent flag (consent_marketing_ml = true) is present and validated.\n3. All ML training jobs must log data lineage for audit.\n\n## Enforcement\nPipeline pre-checks validate consent flags before training.", "version": "v1.0", "regulation": "GDPR Art. 22"}',
 '["usage-purpose", "mandatory", "gdpr", "ml"]',
 'active', 'system@demo', NOW() - INTERVAL '75 days', NOW() - INTERVAL '20 days'),

-- Custom policy
('0f100008-0000-4000-8000-000000000008',
 'Cross-Domain Data Sharing Approval',
 'Any data product shared across domain boundaries requires written approval from both domain owners.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Policy' LIMIT 1), '00000000-0000-0000-0000-000000000000'), NULL, NULL,
 NULL,
 '{"policyType": "custom", "enforcementLevel": "mandatory", "policyContent": "## Scope\nAll domains.\n\n## Rules\n1. Cross-domain data product subscriptions require approval from the source domain owner AND the consuming domain owner.\n2. Approval must be recorded in the system with justification.\n3. Re-approval required annually or when the data product version changes significantly.\n\n## Enforcement\nWorkflow-based approval in Ontos.", "version": "v1.0"}',
 '["custom", "mandatory", "cross-domain"]',
 'active', 'system@demo', NOW() - INTERVAL '40 days', NOW() - INTERVAL '8 days')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 26. ENTITY RELATIONSHIPS (migrated from deprecated asset_relationships)
-- ============================================================================
-- Directed relationships between entities using the ontology-driven model.

INSERT INTO entity_relationships (id, source_type, source_id, target_type, target_id, relationship_type, properties, created_by, created_at) VALUES
-- Tables belong to Databricks Lakehouse system
('0f400001-0000-4000-8000-000000000001', 'Table', '0f300003-0000-4000-8000-000000000003', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),
('0f400002-0000-4000-8000-000000000002', 'Table', '0f300004-0000-4000-8000-000000000004', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),
('0f400003-0000-4000-8000-000000000003', 'Table', '0f300005-0000-4000-8000-000000000005', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),
('0f400004-0000-4000-8000-000000000004', 'Table', '0f300006-0000-4000-8000-000000000006', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),

-- Dashboards belong to Power BI system
('0f400005-0000-4000-8000-000000000005', 'Dashboard', '0f300007-0000-4000-8000-000000000007', 'System', '0f300002-0000-4000-8000-000000000002', 'belongsToSystem', NULL, 'system@demo', NOW()),
('0f400006-0000-4000-8000-000000000006', 'Dashboard', '0f300008-0000-4000-8000-000000000008', 'System', '0f300002-0000-4000-8000-000000000002', 'belongsToSystem', NULL, 'system@demo', NOW()),

-- Dashboard consumes table data (business lineage)
('0f400007-0000-4000-8000-000000000007', 'Dashboard', '0f300007-0000-4000-8000-000000000007', 'Table', '0f300003-0000-4000-8000-000000000003', 'consumesFrom', '{"lineage_type": "business"}', 'system@demo', NOW()),
('0f400008-0000-4000-8000-000000000008', 'Dashboard', '0f300008-0000-4000-8000-000000000008', 'Table', '0f300005-0000-4000-8000-000000000005', 'consumesFrom', '{"lineage_type": "business"}', 'system@demo', NOW()),

-- ML model consumes table
('0f400009-0000-4000-8000-000000000009', 'MLModel', '0f30000c-0000-4000-8000-000000000012', 'Table', '0f300003-0000-4000-8000-000000000003', 'consumesFrom', '{"purpose": "training"}', 'system@demo', NOW()),
('0f40000a-0000-4000-8000-000000000010', 'MLModel', '0f30000c-0000-4000-8000-000000000012', 'Table', '0f300004-0000-4000-8000-000000000004', 'consumesFrom', '{"purpose": "feature_store"}', 'system@demo', NOW()),

-- Stream feeds into table
('0f40000b-0000-4000-8000-000000000011', 'Stream', '0f30000b-0000-4000-8000-000000000011', 'Table', '0f300003-0000-4000-8000-000000000003', 'producesTo', '{"processing": "streaming_ingest"}', 'system@demo', NOW()),

-- Deprecated table replaced by new one
('0f40000c-0000-4000-8000-000000000012', 'Table', '0f30000d-0000-4000-8000-000000000013', 'Table', '0f300003-0000-4000-8000-000000000003', 'replacedBy', '{"reason": "legacy migration"}', 'system@demo', NOW()),

-- DataProducts deployed on systems
('0f40000d-0000-4000-8000-000000000013', 'DataProduct', '00700001-0000-4000-8000-000000000001', 'System', '0f300001-0000-4000-8000-000000000001', 'deployedOnSystem', NULL, 'system@demo', NOW()),
('0f40000e-0000-4000-8000-000000000014', 'DataProduct', '00700002-0000-4000-8000-000000000002', 'System', '0f300001-0000-4000-8000-000000000001', 'deployedOnSystem', NULL, 'system@demo', NOW()),
('0f40000f-0000-4000-8000-000000000015', 'DataProduct', '00700003-0000-4000-8000-000000000003', 'System', '0f300001-0000-4000-8000-000000000001', 'deployedOnSystem', NULL, 'system@demo', NOW()),
('0f400010-0000-4000-8000-000000000016', 'DataProduct', '00700004-0000-4000-8000-000000000004', 'System', '0f300001-0000-4000-8000-000000000001', 'deployedOnSystem', NULL, 'system@demo', NOW()),
('0f400011-0000-4000-8000-000000000017', 'DataProduct', '00700005-0000-4000-8000-000000000005', 'System', '0f300001-0000-4000-8000-000000000001', 'deployedOnSystem', NULL, 'system@demo', NOW()),
('0f400012-0000-4000-8000-000000000018', 'DataProduct', '00700006-0000-4000-8000-000000000006', 'System', '0f300001-0000-4000-8000-000000000001', 'deployedOnSystem', NULL, 'system@demo', NOW()),
('0f400013-0000-4000-8000-000000000019', 'DataProduct', '00700007-0000-4000-8000-000000000007', 'System', '0f300002-0000-4000-8000-000000000002', 'deployedOnSystem', NULL, 'system@demo', NOW()),

-- Datasets belong to Databricks Lakehouse system
('0f400014-0000-4000-8000-000000000020', 'Dataset', '02100001-0000-4000-8000-000000000001', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),
('0f400015-0000-4000-8000-000000000021', 'Dataset', '02100004-0000-4000-8000-000000000004', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),
('0f400016-0000-4000-8000-000000000022', 'Dataset', '02100007-0000-4000-8000-000000000007', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),

-- Stream belongs to Databricks Lakehouse system
('0f400017-0000-4000-8000-000000000023', 'Stream', '0f30000b-0000-4000-8000-000000000011', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),

-- ML Model belongs to Databricks Lakehouse system
('0f400018-0000-4000-8000-000000000024', 'MLModel', '0f30000c-0000-4000-8000-000000000012', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),

-- API Endpoint belongs to Databricks Lakehouse system
('0f400019-0000-4000-8000-000000000025', 'APIEndpoint', '0f300009-0000-4000-8000-000000000009', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),

-- hasColumn: pos_transactions (0f300003) columns
('0f600001-0000-4000-8000-000000000001', 'Table', '0f300003-0000-4000-8000-000000000003', 'Column', '0f500001-0000-4000-8000-000000000001', 'hasColumn', NULL, 'system@demo', NOW()),
('0f600002-0000-4000-8000-000000000002', 'Table', '0f300003-0000-4000-8000-000000000003', 'Column', '0f500002-0000-4000-8000-000000000002', 'hasColumn', NULL, 'system@demo', NOW()),
('0f600003-0000-4000-8000-000000000003', 'Table', '0f300003-0000-4000-8000-000000000003', 'Column', '0f500003-0000-4000-8000-000000000003', 'hasColumn', NULL, 'system@demo', NOW()),
('0f600004-0000-4000-8000-000000000004', 'Table', '0f300003-0000-4000-8000-000000000003', 'Column', '0f500004-0000-4000-8000-000000000004', 'hasColumn', NULL, 'system@demo', NOW()),

-- hasColumn: inventory_levels (0f300004) columns
('0f600005-0000-4000-8000-000000000005', 'Table', '0f300004-0000-4000-8000-000000000004', 'Column', '0f500005-0000-4000-8000-000000000005', 'hasColumn', NULL, 'system@demo', NOW()),
('0f600006-0000-4000-8000-000000000006', 'Table', '0f300004-0000-4000-8000-000000000004', 'Column', '0f500006-0000-4000-8000-000000000006', 'hasColumn', NULL, 'system@demo', NOW()),
('0f600007-0000-4000-8000-000000000007', 'Table', '0f300004-0000-4000-8000-000000000004', 'Column', '0f500007-0000-4000-8000-000000000007', 'hasColumn', NULL, 'system@demo', NOW()),
('0f600008-0000-4000-8000-000000000008', 'Table', '0f300004-0000-4000-8000-000000000004', 'Column', '0f500008-0000-4000-8000-000000000008', 'hasColumn', NULL, 'system@demo', NOW()),

-- hasColumn: Retail Events Stream (0250000e) columns
('0f600009-0000-4000-8000-000000000009', 'Table', '0250000e-0000-4000-8000-000000000014', 'Column', '0f500009-0000-4000-8000-000000000009', 'hasColumn', NULL, 'system@demo', NOW()),
('0f60000a-0000-4000-8000-000000000010', 'Table', '0250000e-0000-4000-8000-000000000014', 'Column', '0f50000a-0000-4000-8000-000000000010', 'hasColumn', NULL, 'system@demo', NOW()),
('0f60000b-0000-4000-8000-000000000011', 'Table', '0250000e-0000-4000-8000-000000000014', 'Column', '0f50000b-0000-4000-8000-000000000011', 'hasColumn', NULL, 'system@demo', NOW()),
('0f60000c-0000-4000-8000-000000000012', 'Table', '0250000e-0000-4000-8000-000000000014', 'Column', '0f50000c-0000-4000-8000-000000000012', 'hasColumn', NULL, 'system@demo', NOW()),

-- hasColumn: Sales Metrics MV (0250000f) columns
('0f60000d-0000-4000-8000-000000000013', 'View', '0250000f-0000-4000-8000-000000000015', 'Column', '0f50000d-0000-4000-8000-000000000013', 'hasColumn', NULL, 'system@demo', NOW()),
('0f60000e-0000-4000-8000-000000000014', 'View', '0250000f-0000-4000-8000-000000000015', 'Column', '0f50000e-0000-4000-8000-000000000014', 'hasColumn', NULL, 'system@demo', NOW()),
('0f60000f-0000-4000-8000-000000000015', 'View', '0250000f-0000-4000-8000-000000000015', 'Column', '0f50000f-0000-4000-8000-000000000015', 'hasColumn', NULL, 'system@demo', NOW()),
('0f600010-0000-4000-8000-000000000016', 'View', '0250000f-0000-4000-8000-000000000015', 'Column', '0f500010-0000-4000-8000-000000000016', 'hasColumn', NULL, 'system@demo', NOW()),

-- ============================================================================
-- 26b. BUSINESS LINEAGE RELATIONSHIPS
-- ============================================================================

-- BusinessTerm "Customer" relates to LogicalEntity "Customer"
('0fa00001-0000-4000-8000-000000000001', 'BusinessTerm', '0f700001-0000-4000-8000-000000000001', 'LogicalEntity', '0f800001-0000-4000-8000-000000000001', 'relatesTo', NULL, 'system@demo', NOW()),
-- BusinessTerm "Transaction" relates to LogicalEntity "Transaction"
('0fa00002-0000-4000-8000-000000000002', 'BusinessTerm', '0f700004-0000-4000-8000-000000000004', 'LogicalEntity', '0f800002-0000-4000-8000-000000000002', 'relatesTo', NULL, 'system@demo', NOW()),
-- BusinessTerm "Customer Lifetime Value" relates to LogicalEntity "Customer"
('0fa00003-0000-4000-8000-000000000003', 'BusinessTerm', '0f700002-0000-4000-8000-000000000002', 'LogicalEntity', '0f800001-0000-4000-8000-000000000001', 'relatesTo', NULL, 'system@demo', NOW()),

-- LogicalEntity "Customer" has attributes
('0fa00010-0000-4000-8000-000000000010', 'LogicalEntity', '0f800001-0000-4000-8000-000000000001', 'LogicalAttribute', '0f810001-0000-4000-8000-000000000001', 'hasLogicalAttribute', NULL, 'system@demo', NOW()),
('0fa00011-0000-4000-8000-000000000011', 'LogicalEntity', '0f800001-0000-4000-8000-000000000001', 'LogicalAttribute', '0f810002-0000-4000-8000-000000000002', 'hasLogicalAttribute', NULL, 'system@demo', NOW()),
('0fa00012-0000-4000-8000-000000000012', 'LogicalEntity', '0f800001-0000-4000-8000-000000000001', 'LogicalAttribute', '0f810003-0000-4000-8000-000000000003', 'hasLogicalAttribute', NULL, 'system@demo', NOW()),
('0fa00013-0000-4000-8000-000000000013', 'LogicalEntity', '0f800001-0000-4000-8000-000000000001', 'LogicalAttribute', '0f810004-0000-4000-8000-000000000004', 'hasLogicalAttribute', NULL, 'system@demo', NOW()),

-- LogicalEntity "Transaction" has attributes
('0fa00014-0000-4000-8000-000000000014', 'LogicalEntity', '0f800002-0000-4000-8000-000000000002', 'LogicalAttribute', '0f810005-0000-4000-8000-000000000005', 'hasLogicalAttribute', NULL, 'system@demo', NOW()),
('0fa00015-0000-4000-8000-000000000015', 'LogicalEntity', '0f800002-0000-4000-8000-000000000002', 'LogicalAttribute', '0f810006-0000-4000-8000-000000000006', 'hasLogicalAttribute', NULL, 'system@demo', NOW()),

-- LogicalAttribute "Customer.Id" implemented by Customer Master Data Dataset
('0fa00020-0000-4000-8000-000000000020', 'LogicalAttribute', '0f810001-0000-4000-8000-000000000001', 'Dataset', '02100001-0000-4000-8000-000000000001', 'implementedBy', NULL, 'system@demo', NOW()),
-- LogicalAttribute "Customer.Email" implemented by Customer Master Data Dataset
('0fa00021-0000-4000-8000-000000000021', 'LogicalAttribute', '0f810003-0000-4000-8000-000000000003', 'Dataset', '02100001-0000-4000-8000-000000000001', 'implementedBy', NULL, 'system@demo', NOW()),
-- LogicalAttribute "Transaction.Id" implemented by Sales Analytics Dataset
('0fa00022-0000-4000-8000-000000000022', 'LogicalAttribute', '0f810005-0000-4000-8000-000000000005', 'Dataset', '02100004-0000-4000-8000-000000000004', 'implementedBy', NULL, 'system@demo', NOW()),
-- LogicalAttribute "Transaction.Amount" implemented by Sales Analytics Dataset
('0fa00023-0000-4000-8000-000000000023', 'LogicalAttribute', '0f810006-0000-4000-8000-000000000006', 'Dataset', '02100004-0000-4000-8000-000000000004', 'implementedBy', NULL, 'system@demo', NOW()),

-- DataProduct "Customer Marketing Recommendations" exposes delivery channels
('0fa00030-0000-4000-8000-000000000030', 'DataProduct', '00700006-0000-4000-8000-000000000006', 'DeliveryChannel', '0f900001-0000-4000-8000-000000000001', 'exposes', NULL, 'system@demo', NOW()),
('0fa00031-0000-4000-8000-000000000031', 'DataProduct', '00700006-0000-4000-8000-000000000006', 'DeliveryChannel', '0f900002-0000-4000-8000-000000000002', 'exposes', NULL, 'system@demo', NOW()),
-- DataProduct "Retail Performance Dashboard" exposes delivery channels
('0fa00032-0000-4000-8000-000000000032', 'DataProduct', '00700002-0000-4000-8000-000000000002', 'DeliveryChannel', '0f900003-0000-4000-8000-000000000003', 'exposes', NULL, 'system@demo', NOW()),
-- DataProduct "Prepared Sales Transactions" exposes delivery channels
('0fa00033-0000-4000-8000-000000000033', 'DataProduct', '00700003-0000-4000-8000-000000000003', 'DeliveryChannel', '0f900004-0000-4000-8000-000000000004', 'exposes', NULL, 'system@demo', NOW()),

-- DataProduct dependencies (depends_on)
-- "Customer Marketing Recommendations" depends on "Prepared Sales Transactions"
('0fa00040-0000-4000-8000-000000000040', 'DataProduct', '00700006-0000-4000-8000-000000000006', 'DataProduct', '00700003-0000-4000-8000-000000000003', 'dependsOn', NULL, 'system@demo', NOW()),
-- "Retail Performance Dashboard" depends on "POS Transaction Stream"
('0fa00041-0000-4000-8000-000000000041', 'DataProduct', '00700002-0000-4000-8000-000000000002', 'DataProduct', '00700001-0000-4000-8000-000000000001', 'dependsOn', NULL, 'system@demo', NOW()),
-- "Demand Forecast" depends on "Inventory Optimization"
('0fa00042-0000-4000-8000-000000000042', 'DataProduct', '00700004-0000-4000-8000-000000000004', 'DataProduct', '00700005-0000-4000-8000-000000000005', 'dependsOn', NULL, 'system@demo', NOW()),

-- Policy "Customer PII Policy" applies to BusinessTerm "Customer" and LogicalAttributes
('0fa00050-0000-4000-8000-000000000050', 'Policy', '0f100001-0000-4000-8000-000000000001', 'BusinessTerm', '0f700001-0000-4000-8000-000000000001', 'appliesTo', NULL, 'system@demo', NOW()),
('0fa00051-0000-4000-8000-000000000051', 'Policy', '0f100001-0000-4000-8000-000000000001', 'LogicalAttribute', '0f810003-0000-4000-8000-000000000003', 'appliesTo', NULL, 'system@demo', NOW()),
('0fa00052-0000-4000-8000-000000000052', 'Policy', '0f100001-0000-4000-8000-000000000001', 'LogicalAttribute', '0f810004-0000-4000-8000-000000000004', 'appliesTo', NULL, 'system@demo', NOW()),

-- Delivery channels belong to systems
('0fa00060-0000-4000-8000-000000000060', 'DeliveryChannel', '0f900001-0000-4000-8000-000000000001', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),
('0fa00061-0000-4000-8000-000000000061', 'DeliveryChannel', '0f900002-0000-4000-8000-000000000002', 'System', '0f300001-0000-4000-8000-000000000001', 'belongsToSystem', NULL, 'system@demo', NOW()),

-- Policy attachments (migrated from policy_attachments table to entity_relationships)
-- Customer PII Policy → Customer domain, customer360 table, customer search API
('0f500001-0000-4000-8000-000000000051', 'Policy', '0f100001-0000-4000-8000-000000000001', 'DataDomain', '00000007-0000-4000-8000-000000000007', 'appliesTo', '{"notes": "Applies to all assets in the Customer domain"}', 'system@demo', NOW()),
('0f500002-0000-4000-8000-000000000052', 'Table', '0f300005-0000-4000-8000-000000000005', 'Policy', '0f100001-0000-4000-8000-000000000001', 'attachedPolicy', '{"notes": "PII masking required for email, phone columns"}', 'system@demo', NOW()),
('0f500003-0000-4000-8000-000000000053', 'APIEndpoint', '0f300009-0000-4000-8000-000000000009', 'Policy', '0f100001-0000-4000-8000-000000000001', 'attachedPolicy', '{"notes": "API must enforce PII filtering"}', 'system@demo', NOW()),
-- Employee Data Access Policy → HR domain
('0f500004-0000-4000-8000-000000000054', 'Policy', '0f100002-0000-4000-8000-000000000002', 'DataDomain', '00000009-0000-4000-8000-000000000009', 'appliesTo', NULL, 'system@demo', NOW()),
-- Finance Zero-Null Policy → Finance domain, invoices table
('0f500005-0000-4000-8000-000000000055', 'Policy', '0f100003-0000-4000-8000-000000000003', 'DataDomain', '00000002-0000-4000-8000-000000000002', 'appliesTo', NULL, 'system@demo', NOW()),
('0f500006-0000-4000-8000-000000000056', 'Table', '0f300006-0000-4000-8000-000000000006', 'Policy', '0f100003-0000-4000-8000-000000000003', 'attachedPolicy', '{"notes": "Invoice.Id and Booking.Amount must be non-null"}', 'system@demo', NOW()),
-- Retail Completeness Policy → Retail Operations domain, POS transactions table, POS Transaction Stream DP
('0f500007-0000-4000-8000-000000000057', 'Policy', '0f100004-0000-4000-8000-000000000004', 'DataDomain', '0000000c-0000-4000-8000-000000000012', 'appliesTo', NULL, 'system@demo', NOW()),
('0f500008-0000-4000-8000-000000000058', 'Table', '0f300003-0000-4000-8000-000000000003', 'Policy', '0f100004-0000-4000-8000-000000000004', 'attachedPolicy', NULL, 'system@demo', NOW()),
('0f500009-0000-4000-8000-000000000059', 'Policy', '0f100004-0000-4000-8000-000000000004', 'DataProduct', '00700001-0000-4000-8000-000000000001', 'appliesTo', '{"notes": "Completeness validation on output port"}', 'system@demo', NOW()),
-- Marketing Retention Policy → Marketing domain, clickstream dataset
('0f50000a-0000-4000-8000-000000000060', 'Policy', '0f100005-0000-4000-8000-000000000005', 'DataDomain', '00000004-0000-4000-8000-000000000004', 'appliesTo', NULL, 'system@demo', NOW()),
('0f50000b-0000-4000-8000-000000000061', 'Dataset', '0f30000a-0000-4000-8000-000000000010', 'Policy', '0f100005-0000-4000-8000-000000000005', 'attachedPolicy', '{"notes": "Subject to 90-day TTL"}', 'system@demo', NOW()),
-- EU ML Training Restriction → Customer domain, Marketing domain
('0f50000c-0000-4000-8000-000000000062', 'Policy', '0f100007-0000-4000-8000-000000000007', 'DataDomain', '00000007-0000-4000-8000-000000000007', 'appliesTo', '{"notes": "EU customer data subject to consent checks"}', 'system@demo', NOW()),
('0f50000d-0000-4000-8000-000000000063', 'Policy', '0f100007-0000-4000-8000-000000000007', 'DataDomain', '00000004-0000-4000-8000-000000000004', 'appliesTo', '{"notes": "Training datasets in Marketing must check consent"}', 'system@demo', NOW()),
-- Cross-Domain Sharing → Core domain
('0f50000e-0000-4000-8000-000000000064', 'Policy', '0f100008-0000-4000-8000-000000000008', 'DataDomain', '00000001-0000-4000-8000-000000000001', 'appliesTo', '{"notes": "Applies to all cross-domain data product subscriptions"}', 'system@demo', NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 28. BUSINESS OWNERS (type=0f6)
-- ============================================================================
-- Ownership assignments linking users (with a business role) to various objects.
-- Includes both active and historical (removed) assignments.

INSERT INTO business_owners (id, object_type, object_id, user_email, user_name, role_id, is_active, assigned_at, removed_at, removal_reason, created_by, created_at, updated_at) VALUES

-- Data Domain owners
('0f600001-0000-4000-8000-000000000001', 'data_domain', '00000007-0000-4000-8000-000000000007', 'alice.chen@example.com',    'Alice Chen',    '0f000002-0000-4000-8000-000000000002', true,  NOW() - INTERVAL '180 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600002-0000-4000-8000-000000000002', 'data_domain', '00000002-0000-4000-8000-000000000002', 'bob.martinez@example.com',  'Bob Martinez',  '0f000002-0000-4000-8000-000000000002', true,  NOW() - INTERVAL '200 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600003-0000-4000-8000-000000000003', 'data_domain', '0000000c-0000-4000-8000-000000000012', 'carol.wu@example.com',      'Carol Wu',      '0f000002-0000-4000-8000-000000000002', true,  NOW() - INTERVAL '150 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600004-0000-4000-8000-000000000004', 'data_domain', '00000004-0000-4000-8000-000000000004', 'dave.johnson@example.com',  'Dave Johnson',  '0f000002-0000-4000-8000-000000000002', true,  NOW() - INTERVAL '90 days',  NULL, NULL, 'system@demo', NOW(), NOW()),

-- Data Product owners
('0f600005-0000-4000-8000-000000000005', 'data_product', '00700001-0000-4000-8000-000000000001', 'carol.wu@example.com',     'Carol Wu',      '0f000001-0000-4000-8000-000000000001', true,  NOW() - INTERVAL '120 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600006-0000-4000-8000-000000000006', 'data_product', '00700001-0000-4000-8000-000000000001', 'frank.lee@example.com',    'Frank Lee',     '0f000005-0000-4000-8000-000000000005', true,  NOW() - INTERVAL '120 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600007-0000-4000-8000-000000000007', 'data_product', '00700002-0000-4000-8000-000000000002', 'carol.wu@example.com',     'Carol Wu',      '0f000001-0000-4000-8000-000000000001', true,  NOW() - INTERVAL '100 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600008-0000-4000-8000-000000000008', 'data_product', '00700003-0000-4000-8000-000000000003', 'grace.kim@example.com',    'Grace Kim',     '0f000001-0000-4000-8000-000000000001', true,  NOW() - INTERVAL '80 days',  NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600009-0000-4000-8000-000000000009', 'data_product', '00700006-0000-4000-8000-000000000006', 'dave.johnson@example.com', 'Dave Johnson',  '0f000001-0000-4000-8000-000000000001', true,  NOW() - INTERVAL '60 days',  NULL, NULL, 'system@demo', NOW(), NOW()),

-- Data Product — Business Sponsor
('0f60000a-0000-4000-8000-000000000010', 'data_product', '00700001-0000-4000-8000-000000000001', 'eva.director@example.com', 'Eva Director',  '0f000007-0000-4000-8000-000000000007', true,  NOW() - INTERVAL '120 days', NULL, NULL, 'system@demo', NOW(), NOW()),

-- Policy asset owners
('0f60000b-0000-4000-8000-000000000011', 'asset', '0f100001-0000-4000-8000-000000000001', 'alice.chen@example.com',   'Alice Chen',   '0f000001-0000-4000-8000-000000000001', true,  NOW() - INTERVAL '90 days',  NULL, NULL, 'system@demo', NOW(), NOW()),
('0f60000c-0000-4000-8000-000000000012', 'asset', '0f100003-0000-4000-8000-000000000003', 'bob.martinez@example.com', 'Bob Martinez', '0f000001-0000-4000-8000-000000000001', true,  NOW() - INTERVAL '60 days',  NULL, NULL, 'system@demo', NOW(), NOW()),
('0f60000d-0000-4000-8000-000000000013', 'asset', '0f100007-0000-4000-8000-000000000007', 'alice.chen@example.com',   'Alice Chen',   '0f00000a-0000-4000-8000-000000000010', true,  NOW() - INTERVAL '75 days',  NULL, NULL, 'system@demo', NOW(), NOW()),

-- Asset owners
('0f60000e-0000-4000-8000-000000000014', 'asset', '0f300005-0000-4000-8000-000000000005', 'alice.chen@example.com',    'Alice Chen',    '0f000001-0000-4000-8000-000000000001', true,  NOW() - INTERVAL '60 days',  NULL, NULL, 'system@demo', NOW(), NOW()),
('0f60000f-0000-4000-8000-000000000015', 'asset', '0f300005-0000-4000-8000-000000000005', 'frank.lee@example.com',     'Frank Lee',     '0f000005-0000-4000-8000-000000000005', true,  NOW() - INTERVAL '60 days',  NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600010-0000-4000-8000-000000000016', 'asset', '0f300006-0000-4000-8000-000000000006', 'bob.martinez@example.com',  'Bob Martinez',  '0f000001-0000-4000-8000-000000000001', true,  NOW() - INTERVAL '45 days',  NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600011-0000-4000-8000-000000000017', 'asset', '0f300007-0000-4000-8000-000000000007', 'hank.analyst@example.com',  'Hank Analyst',  '0f000008-0000-4000-8000-000000000008', true,  NOW() - INTERVAL '30 days',  NULL, NULL, 'system@demo', NOW(), NOW()),

-- Data Steward assignments
('0f600012-0000-4000-8000-000000000018', 'data_domain', '00000007-0000-4000-8000-000000000007', 'iris.steward@example.com', 'Iris Steward',  '0f000003-0000-4000-8000-000000000003', true,  NOW() - INTERVAL '150 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0f600013-0000-4000-8000-000000000019', 'data_domain', '0000000c-0000-4000-8000-000000000012', 'iris.steward@example.com', 'Iris Steward',  '0f000003-0000-4000-8000-000000000003', true,  NOW() - INTERVAL '100 days', NULL, NULL, 'system@demo', NOW(), NOW()),

-- Historical / removed owners (tracking ownership changes)
('0f600014-0000-4000-8000-000000000020', 'data_product', '00700001-0000-4000-8000-000000000001', 'old.owner@example.com',    'Old Owner',     '0f000001-0000-4000-8000-000000000001', false, NOW() - INTERVAL '300 days', NOW() - INTERVAL '120 days', 'Transferred ownership to Carol Wu upon team restructuring', 'system@demo', NOW() - INTERVAL '300 days', NOW() - INTERVAL '120 days'),
('0f600015-0000-4000-8000-000000000021', 'data_domain', '00000004-0000-4000-8000-000000000004', 'prev.owner@example.com',   'Prev Owner',    '0f000002-0000-4000-8000-000000000002', false, NOW() - INTERVAL '365 days', NOW() - INTERVAL '90 days',  'Left the company — domain ownership reassigned to Dave Johnson', 'system@demo', NOW() - INTERVAL '365 days', NOW() - INTERVAL '90 days'),

-- SLA Manager on a data product
('0f600016-0000-4000-8000-000000000022', 'data_product', '00700002-0000-4000-8000-000000000002', 'jack.ops@example.com',     'Jack Ops',      '0f000009-0000-4000-8000-000000000009', true,  NOW() - INTERVAL '50 days',  NULL, NULL, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


COMMIT;

-- ============================================================================
-- End of Demo Data
-- ============================================================================
