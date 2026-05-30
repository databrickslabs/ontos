-- ============================================================================
-- FSI Demo Data — preset=fsi
-- ============================================================================
-- Standalone demo pack loaded via:
--   POST /api/settings/demo-data/load?preset=fsi
--
-- This pack is fully self-contained: loading it on an empty database produces
-- a complete Financial Services vertical demo with no implicit content from
-- any other preset.
--
-- Dataset identifier: 0002 (second UUID group)
-- UUID Format: {type:3}{seq:5}-0002-4000-8000-00000000000N
-- ============================================================================

BEGIN;

-- ============================================================================
-- 0. SHARED PARENT ROWS (idempotent foundation)
-- ============================================================================
-- FSI data_domains FK to base "Core" parent below. Inserted ON CONFLICT DO
-- NOTHING so it is safe to load this preset on top of an empty DB or alongside
-- other presets.

INSERT INTO data_domains (id, name, description, parent_id, created_by, created_at, updated_at) VALUES
('00000001-0000-4000-8000-000000000001', 'Core', 'General, cross-company business concepts.', NULL, 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 1. DATA DOMAINS (FSI-specific, children of Core)
-- ============================================================================

INSERT INTO data_domains (id, name, description, parent_id, created_by, created_at, updated_at) VALUES
('00000001-0002-4000-8000-000000000001', 'Banking', 'Retail and commercial banking operations, accounts, and transactions.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000002-0002-4000-8000-000000000002', 'Capital Markets', 'Trading, securities, derivatives, and market data.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000003-0002-4000-8000-000000000003', 'Risk Management', 'Credit, market, operational, and liquidity risk analytics.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000004-0002-4000-8000-000000000004', 'Regulatory Compliance', 'Basel III/IV, AML/KYC, BCBS 239, and regulatory reporting.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000005-0002-4000-8000-000000000005', 'Insurance', 'Policy management, underwriting, and actuarial data.', '00000001-0000-4000-8000-000000000001', 'system@demo', NOW(), NOW()),
('00000006-0002-4000-8000-000000000006', 'Wealth Management', 'Portfolio analytics, client advisory, and fiduciary data.', '00000001-0002-4000-8000-000000000001', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2. TEAMS
-- ============================================================================

INSERT INTO teams (id, name, title, description, domain_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00100001-0002-4000-8000-000000000001', 'trading-analytics', 'Trading Analytics Team', 'Quantitative analytics for equities, fixed income, and derivatives trading', '00000002-0002-4000-8000-000000000002', '{"slack_channel": "https://company.slack.com/channels/trading-analytics", "lead": "quant.lead@bank.com"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100002-0002-4000-8000-000000000002', 'risk-management', 'Risk Management Team', 'Enterprise risk measurement, stress testing, and model validation', '00000003-0002-4000-8000-000000000003', '{"slack_channel": "https://company.slack.com/channels/risk-mgmt", "tools": ["SAS", "Python", "Moody''s Analytics"]}', 'system@demo', 'system@demo', NOW(), NOW()),
('00100003-0002-4000-8000-000000000003', 'compliance-ops', 'Compliance Operations Team', 'AML transaction monitoring, KYC remediation, and regulatory reporting', '00000004-0002-4000-8000-000000000004', '{"slack_channel": "https://company.slack.com/channels/compliance-ops", "responsibilities": ["BSA/AML", "OFAC", "KYC/CDD", "SAR Filing"]}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 2b. TEAM MEMBERS
-- ============================================================================

INSERT INTO team_members (id, team_id, member_type, member_identifier, app_role_override, added_by, created_at, updated_at) VALUES
('00200001-0002-4000-8000-000000000001', '00100001-0002-4000-8000-000000000001', 'user', 'quant.lead@bank.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200002-0002-4000-8000-000000000002', '00100001-0002-4000-8000-000000000001', 'group', 'quant-traders', NULL, 'system@demo', NOW(), NOW()),
('00200003-0002-4000-8000-000000000003', '00100002-0002-4000-8000-000000000002', 'user', 'chief.risk@bank.com', 'Data Producer', 'system@demo', NOW(), NOW()),
('00200004-0002-4000-8000-000000000004', '00100002-0002-4000-8000-000000000002', 'group', 'risk-analysts', NULL, 'system@demo', NOW(), NOW()),
('00200005-0002-4000-8000-000000000005', '00100003-0002-4000-8000-000000000003', 'user', 'bsa.officer@bank.com', 'Data Steward', 'system@demo', NOW(), NOW()),
('00200006-0002-4000-8000-000000000006', '00100003-0002-4000-8000-000000000003', 'group', 'aml-investigators', NULL, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3. PROJECTS
-- ============================================================================

INSERT INTO projects (id, name, title, description, project_type, owner_team_id, extra_metadata, created_by, updated_by, created_at, updated_at) VALUES
('00300001-0002-4000-8000-000000000001', 'risk-aggregation', 'Enterprise Risk Aggregation', 'BCBS 239-compliant risk data aggregation and reporting infrastructure', 'TEAM', '00100002-0002-4000-8000-000000000002', '{"budget": "$2M", "timeline": "14 months", "compliance": ["BCBS 239", "Basel III", "FRTB"], "priority": "critical"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300002-0002-4000-8000-000000000002', 'aml-modernization', 'AML/KYC Modernization', 'Next-generation transaction monitoring and entity resolution for AML compliance', 'TEAM', '00100003-0002-4000-8000-000000000003', '{"budget": "$1.5M", "timeline": "10 months", "compliance": ["BSA", "FinCEN", "OFAC"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW()),
('00300003-0002-4000-8000-000000000003', 'trading-platform', 'Next-Gen Trading Analytics', 'Real-time trading analytics, P&L attribution, and alpha signal research', 'TEAM', '00100001-0002-4000-8000-000000000001', '{"budget": "$3M", "timeline": "18 months", "technologies": ["Spark", "Kafka", "kdb+"], "priority": "high"}', 'system@demo', 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 3b. PROJECT-TEAM ASSOCIATIONS
-- ============================================================================

INSERT INTO project_teams (project_id, team_id, assigned_by, assigned_at) VALUES
('00300001-0002-4000-8000-000000000001', '00100002-0002-4000-8000-000000000002', 'system@demo', NOW()),
('00300001-0002-4000-8000-000000000001', '00100003-0002-4000-8000-000000000003', 'system@demo', NOW()),
('00300002-0002-4000-8000-000000000002', '00100003-0002-4000-8000-000000000003', 'system@demo', NOW()),
('00300003-0002-4000-8000-000000000003', '00100001-0002-4000-8000-000000000001', 'system@demo', NOW()),
('00300003-0002-4000-8000-000000000003', '00100002-0002-4000-8000-000000000002', 'system@demo', NOW())

ON CONFLICT (project_id, team_id) DO NOTHING;


-- ============================================================================
-- 4. DATA CONTRACTS
-- ============================================================================

INSERT INTO data_contracts (id, name, kind, api_version, version, status, published, owner_team_id, domain_id, description_purpose, description_usage, description_limitations, publication_scope, created_by, updated_by, created_at, updated_at, version_family_id) VALUES
('00400001-0002-4000-8000-000000000001', 'Trading & Market Data Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100001-0002-4000-8000-000000000001', '00000002-0002-4000-8000-000000000002', 'Standardized trade execution, order book, and market data for analytics and regulatory reporting', 'Real-time P&L, best execution analysis, MiFID II transaction reporting, and alpha research', 'Timestamps must be nanosecond precision; all prices in instrument native currency; T+1 settlement data only', 'org', 'system@demo', 'system@demo', NOW(), NOW(), '00400001-0002-4000-8000-000000000001'),
('00400002-0002-4000-8000-000000000002', 'Risk Exposure Contract', 'DataContract', 'v3.1.0', '2.0.0', 'active', true, '00100002-0002-4000-8000-000000000002', '00000003-0002-4000-8000-000000000003', 'Aggregated risk exposures across credit, market, and counterparty risk', 'BCBS 239 risk reports, stress testing scenarios, and limit monitoring', 'Netting requires CSA-level granularity; VaR computed at 99% 10-day horizon; CVA/DVA excluded from market risk', 'org', 'system@demo', 'system@demo', NOW(), NOW(), '00400002-0002-4000-8000-000000000002'),
('00400003-0002-4000-8000-000000000003', 'KYC/AML Data Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100003-0002-4000-8000-000000000003', '00000004-0002-4000-8000-000000000004', 'Customer due diligence, beneficial ownership, and transaction monitoring data', 'Entity resolution, risk scoring, SAR narrative generation, and OFAC screening', 'PEP and sanctions data refreshed daily; beneficial ownership threshold 25%; STR filing requires manual review', 'org', 'system@demo', 'system@demo', NOW(), NOW(), '00400003-0002-4000-8000-000000000003'),
('00400004-0002-4000-8000-000000000004', 'Regulatory Reporting Contract', 'DataContract', 'v3.1.0', '1.0.0', 'draft', false, '00100003-0002-4000-8000-000000000003', '00000004-0002-4000-8000-000000000004', 'Data feeds for prudential regulatory submissions (FR Y-14, CCAR, DFAST)', 'Automated population of regulatory templates and submission validation', 'Quarter-end data only; manual overrides must have four-eyes approval; reconciliation tolerance ±$1M', 'none', 'system@demo', 'system@demo', NOW(), NOW(), '00400004-0002-4000-8000-000000000004'),
('00400005-0002-4000-8000-000000000005', 'Account & Transaction Contract', 'DataContract', 'v3.1.0', '1.0.0', 'active', true, '00100001-0002-4000-8000-000000000001', '00000001-0002-4000-8000-000000000001', 'Core banking account master and transaction data for retail and commercial banking', 'Account analytics, fraud detection, fee optimization, and customer 360 enrichment', 'Real-time balance is T+0 approximation; currency conversion uses daily ECB fix; PII encrypted at rest with AES-256', 'org', 'system@demo', 'system@demo', NOW(), NOW(), '00400005-0002-4000-8000-000000000005')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4b. DATA CONTRACT SCHEMA OBJECTS
-- ============================================================================

INSERT INTO data_contract_schema_objects (id, contract_id, name, logical_type, physical_name, description) VALUES
-- Trading & Market Data
('00500001-0002-4000-8000-000000000001', '00400001-0002-4000-8000-000000000001', 'trades', 'object', 'trading.executed_trades', 'Trade execution records'),
('00500002-0002-4000-8000-000000000002', '00400001-0002-4000-8000-000000000001', 'positions', 'object', 'trading.eod_positions', 'End-of-day position snapshots'),
('00500003-0002-4000-8000-000000000003', '00400001-0002-4000-8000-000000000001', 'market_data', 'object', 'trading.market_data_ticks', 'Tick-level market data'),

-- Risk Exposure
('00500004-0002-4000-8000-000000000004', '00400002-0002-4000-8000-000000000002', 'risk_exposures', 'object', 'risk.aggregated_exposures', 'Risk factor exposures by desk and entity'),
('00500005-0002-4000-8000-000000000005', '00400002-0002-4000-8000-000000000002', 'stress_scenarios', 'object', 'risk.stress_test_results', 'Stress test scenario outputs'),

-- KYC/AML
('00500006-0002-4000-8000-000000000006', '00400003-0002-4000-8000-000000000003', 'customer_kyc', 'object', 'compliance.customer_kyc_profiles', 'KYC profile and due diligence records'),
('00500007-0002-4000-8000-000000000007', '00400003-0002-4000-8000-000000000003', 'aml_alerts', 'object', 'compliance.aml_alerts', 'Transaction monitoring alerts'),

-- Accounts
('00500008-0002-4000-8000-000000000008', '00400005-0002-4000-8000-000000000005', 'accounts', 'object', 'banking.accounts_master', 'Account master records'),
('00500009-0002-4000-8000-000000000009', '00400005-0002-4000-8000-000000000005', 'transactions', 'object', 'banking.account_transactions', 'Account transaction ledger')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 4c. DATA CONTRACT SCHEMA PROPERTIES
-- ============================================================================

INSERT INTO data_contract_schema_properties (id, object_id, name, logical_type, required, "unique", primary_key, partitioned, primary_key_position, partition_key_position, critical_data_element, transform_description) VALUES
-- trades table
('00600001-0002-4000-8000-000000000001', '00500001-0002-4000-8000-000000000001', 'trade_id', 'string', true, true, true, false, 1, -1, true, 'Unique trade execution identifier'),
('00600002-0002-4000-8000-000000000002', '00500001-0002-4000-8000-000000000001', 'instrument_id', 'string', true, false, false, false, -1, -1, true, 'ISIN or internal security identifier'),
('00600003-0002-4000-8000-000000000003', '00500001-0002-4000-8000-000000000001', 'side', 'string', true, false, false, false, -1, -1, false, 'BUY or SELL'),
('00600004-0002-4000-8000-000000000004', '00500001-0002-4000-8000-000000000001', 'quantity', 'decimal', true, false, false, false, -1, -1, true, 'Executed quantity'),
('00600005-0002-4000-8000-000000000005', '00500001-0002-4000-8000-000000000001', 'price', 'decimal', true, false, false, false, -1, -1, true, 'Execution price in instrument currency'),
('00600006-0002-4000-8000-000000000006', '00500001-0002-4000-8000-000000000001', 'execution_ts', 'timestamp', true, false, false, true, -1, 1, true, 'Execution timestamp (nanosecond precision)'),

-- risk_exposures table
('00600007-0002-4000-8000-000000000007', '00500004-0002-4000-8000-000000000004', 'exposure_id', 'string', true, true, true, false, 1, -1, true, 'Unique exposure record ID'),
('00600008-0002-4000-8000-000000000008', '00500004-0002-4000-8000-000000000004', 'risk_type', 'string', true, false, false, false, -1, -1, true, 'credit, market, counterparty, operational'),
('00600009-0002-4000-8000-000000000009', '00500004-0002-4000-8000-000000000004', 'var_99', 'decimal', true, false, false, false, -1, -1, true, 'Value-at-Risk at 99% confidence'),
('0060000a-0002-4000-8000-000000000010', '00500004-0002-4000-8000-000000000004', 'reporting_date', 'date', true, false, false, true, -1, 1, false, 'Risk reporting date'),

-- customer_kyc table
('0060000b-0002-4000-8000-000000000011', '00500006-0002-4000-8000-000000000006', 'customer_id', 'string', true, true, true, false, 1, -1, true, 'Unique customer identifier'),
('0060000c-0002-4000-8000-000000000012', '00500006-0002-4000-8000-000000000006', 'risk_rating', 'string', true, false, false, false, -1, -1, true, 'low, medium, high, prohibited'),
('0060000d-0002-4000-8000-000000000013', '00500006-0002-4000-8000-000000000006', 'pep_status', 'boolean', true, false, false, false, -1, -1, true, 'Politically Exposed Person flag'),
('0060000e-0002-4000-8000-000000000014', '00500006-0002-4000-8000-000000000006', 'last_review_date', 'date', true, false, false, false, -1, -1, false, 'Date of most recent KYC review'),
('0060000f-0002-4000-8000-000000000015', '00500006-0002-4000-8000-000000000006', 'beneficial_owners', 'string', false, false, false, false, -1, -1, true, 'JSON array of beneficial owners (>25% threshold)')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5. DATA PRODUCTS
-- ============================================================================

INSERT INTO data_products (id, api_version, kind, status, name, version, domain, tenant, owner_team_id, max_level_inheritance, published, publication_scope, created_at, updated_at, version_family_id) VALUES
('00700001-0002-4000-8000-000000000001', 'v1.0.0', 'DataProduct', 'active', 'Trading Analytics Dashboard v1', '1.0.0', 'Capital Markets', 'fsi-demo', '00100001-0002-4000-8000-000000000001', 99, true, 'org', NOW(), NOW(), '00700001-0002-4000-8000-000000000001'),
('00700002-0002-4000-8000-000000000002', 'v1.0.0', 'DataProduct', 'active', 'Enterprise Risk Aggregation v1', '1.0.0', 'Risk Management', 'fsi-demo', '00100002-0002-4000-8000-000000000002', 99, true, 'org', NOW(), NOW(), '00700002-0002-4000-8000-000000000002'),
('00700003-0002-4000-8000-000000000003', 'v1.0.0', 'DataProduct', 'active', 'AML Transaction Monitoring v1', '1.0.0', 'Regulatory Compliance', 'fsi-demo', '00100003-0002-4000-8000-000000000003', 99, true, 'org', NOW(), NOW(), '00700003-0002-4000-8000-000000000003'),
('00700004-0002-4000-8000-000000000004', 'v1.0.0', 'DataProduct', 'active', 'Regulatory Reporting Hub v1', '1.0.0', 'Regulatory Compliance', 'fsi-demo', '00100003-0002-4000-8000-000000000003', 99, true, 'org', NOW(), NOW(), '00700004-0002-4000-8000-000000000004'),
('00700005-0002-4000-8000-000000000005', 'v1.0.0', 'DataProduct', 'active', 'Customer 360 Banking v1', '1.0.0', 'Banking', 'fsi-demo', '00100001-0002-4000-8000-000000000001', 99, true, 'org', NOW(), NOW(), '00700005-0002-4000-8000-000000000005')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5b. DATA PRODUCT DESCRIPTIONS
-- ============================================================================

INSERT INTO data_product_descriptions (id, product_id, purpose, usage, limitations) VALUES
('00800001-0002-4000-8000-000000000001', '00700001-0002-4000-8000-000000000001', 'Provide real-time P&L, position analytics, best execution metrics, and risk-adjusted return attribution for trading desks.', 'Desktop dashboards for traders, COO end-of-day reports, and MiFID II best execution analytics.', 'Intraday P&L is mark-to-market estimate. OTC derivatives use model prices with T+1 recalibration.'),
('00800002-0002-4000-8000-000000000002', '00700002-0002-4000-8000-000000000002', 'Aggregate risk exposures across all business lines with BCBS 239-compliant lineage, accuracy, and timeliness.', 'CRO dashboard, board risk appetite reporting, CCAR/DFAST stress test submissions, and limit monitoring.', 'Operational risk uses AMA model. Liquidity risk excludes intraday. Correlation assumptions reviewed quarterly.'),
('00800003-0002-4000-8000-000000000003', '00700003-0002-4000-8000-000000000003', 'Detect suspicious transaction patterns using ML-based models, network analysis, and rule-based scenarios.', 'Investigation case management, SAR auto-narrative drafting, and OFAC real-time screening.', 'Model false positive rate ~85%. Bulk cash structuring detection has 2-hour latency. Cross-border wires real-time.'),
('00800004-0002-4000-8000-000000000004', '00700004-0002-4000-8000-000000000004', 'Centralized hub for regulatory report generation, validation, and submission across prudential and conduct regimes.', 'Automated FR Y-14, Call Report, and LCR/NSFR generation. XBRL tagging and submission to Fed and OCC portals.', 'Quarter-end processing window is 15 business days. Manual adjustments require dual approval.'),
('00800005-0002-4000-8000-000000000005', '00700005-0002-4000-8000-000000000005', 'Unified customer view combining accounts, transactions, KYC, interactions, and product holdings for relationship management.', 'RM desktop, next-best-action engine, and cross-sell/up-sell propensity models.', 'Wealth management data integrated with 24h lag. External data enrichment (Experian, D&B) refreshed monthly.')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5c. DATA PRODUCT OUTPUT PORTS
-- ============================================================================

INSERT INTO data_product_output_ports (id, product_id, name, version, description, port_type, status, contract_id, contains_pii, auto_approve, server) VALUES
('00900001-0002-4000-8000-000000000001', '00700001-0002-4000-8000-000000000001', 'trading_analytics_stream', '1.0.0', 'Real-time P&L and position feed', 'kafka', 'active', NULL, false, false, '{"host": "kafka.bank.com", "topic": "trading-analytics-v1"}'),
('00900002-0002-4000-8000-000000000002', '00700002-0002-4000-8000-000000000002', 'risk_cube_delta', '1.0.0', 'Multi-dimensional risk exposure cube', 'table', 'active', NULL, false, false, '{"location": "s3://fsi-lake/risk/cube/v1", "format": "delta"}'),
('00900003-0002-4000-8000-000000000003', '00700003-0002-4000-8000-000000000003', 'aml_alerts_api', '1.0.0', 'Real-time AML alert API for case management', 'api', 'active', NULL, true, false, '{"location": "https://compliance.bank.com/api/v1/alerts"}'),
('00900004-0002-4000-8000-000000000004', '00700004-0002-4000-8000-000000000004', 'regulatory_submissions', '1.0.0', 'Validated regulatory report packages (XBRL)', 'file', 'active', NULL, false, false, '{"location": "s3://fsi-lake/regulatory/submissions/v1", "format": "xbrl"}'),
('00900005-0002-4000-8000-000000000005', '00700005-0002-4000-8000-000000000005', 'customer_360_banking', '1.0.0', 'Unified customer profile table', 'table', 'active', NULL, true, false, '{"location": "s3://fsi-lake/banking/customer360/v1", "format": "delta"}')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5d. DATA PRODUCT INPUT PORTS
-- ============================================================================

INSERT INTO data_product_input_ports (id, product_id, name, version, contract_id) VALUES
('00a00001-0002-4000-8000-000000000001', '00700001-0002-4000-8000-000000000001', 'Trade Execution Feed', '1.0.0', 'trading-market-data-contract-v1'),
('00a00002-0002-4000-8000-000000000002', '00700001-0002-4000-8000-000000000001', 'Market Data Feed', '1.0.0', 'trading-market-data-contract-v1'),
('00a00003-0002-4000-8000-000000000003', '00700002-0002-4000-8000-000000000002', 'Position Data', '1.0.0', 'risk-exposure-contract-v2'),
('00a00004-0002-4000-8000-000000000004', '00700002-0002-4000-8000-000000000002', 'Counterparty Data', '1.0.0', 'risk-exposure-contract-v2'),
('00a00005-0002-4000-8000-000000000005', '00700003-0002-4000-8000-000000000003', 'Transaction Ledger', '1.0.0', 'kyc-aml-contract-v1'),
('00a00006-0002-4000-8000-000000000006', '00700003-0002-4000-8000-000000000003', 'KYC Profiles', '1.0.0', 'kyc-aml-contract-v1'),
('00a00007-0002-4000-8000-000000000007', '00700004-0002-4000-8000-000000000004', 'Risk Aggregation Data', '1.0.0', 'regulatory-reporting-contract-v1'),
('00a00008-0002-4000-8000-000000000008', '00700005-0002-4000-8000-000000000005', 'Account Master', '1.0.0', 'account-transaction-contract-v1'),
('00a00009-0002-4000-8000-000000000009', '00700005-0002-4000-8000-000000000005', 'Transaction History', '1.0.0', 'account-transaction-contract-v1')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5e. DATA PRODUCT SUPPORT CHANNELS
-- ============================================================================

INSERT INTO data_product_support_channels (id, product_id, channel, url, tool, scope, description) VALUES
('00b00001-0002-4000-8000-000000000001', '00700001-0002-4000-8000-000000000001', 'trading-desk-support', 'https://symphony.bank.com/rooms/trading-analytics', 'slack', 'interactive', 'Real-time support for trading analytics'),
('00b00002-0002-4000-8000-000000000002', '00700002-0002-4000-8000-000000000002', 'risk-data-ops', 'https://jira.bank.com/projects/RISKDATA', 'ticket', 'issues', 'Risk data quality and reconciliation issues'),
('00b00003-0002-4000-8000-000000000003', '00700003-0002-4000-8000-000000000003', 'aml-ops-support', 'https://teams.com/channels/aml-ops', 'teams', 'interactive', NULL),
('00b00004-0002-4000-8000-000000000004', '00700004-0002-4000-8000-000000000004', 'reg-reporting-support', 'https://teams.com/channels/reg-reporting', 'teams', 'issues', 'Regulatory reporting queries and escalations'),
('00b00005-0002-4000-8000-000000000005', '00700005-0002-4000-8000-000000000005', 'banking-data-support', 'https://slack.com/channels/banking-data', 'slack', 'interactive', NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5f. DATA PRODUCT TEAMS
-- ============================================================================

INSERT INTO data_product_teams (id, product_id, name, description) VALUES
('00c00001-0002-4000-8000-000000000001', '00700001-0002-4000-8000-000000000001', 'Quant Analytics', NULL),
('00c00002-0002-4000-8000-000000000002', '00700002-0002-4000-8000-000000000002', 'Risk Engineering', NULL),
('00c00003-0002-4000-8000-000000000003', '00700003-0002-4000-8000-000000000003', 'AML Operations', NULL),
('00c00004-0002-4000-8000-000000000004', '00700004-0002-4000-8000-000000000004', 'Regulatory Tech', NULL),
('00c00005-0002-4000-8000-000000000005', '00700005-0002-4000-8000-000000000005', 'Banking Analytics', NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 5g. DATA PRODUCT TEAM MEMBERS
-- ============================================================================

INSERT INTO data_product_team_members (id, team_id, username, name, role) VALUES
('00d00001-0002-4000-8000-000000000001', '00c00001-0002-4000-8000-000000000001', 'quant.lead@bank.com', 'Marcus Quant', 'owner'),
('00d00002-0002-4000-8000-000000000002', '00c00002-0002-4000-8000-000000000002', 'chief.risk@bank.com', 'Diana Risk', 'owner'),
('00d00003-0002-4000-8000-000000000003', '00c00002-0002-4000-8000-000000000002', 'risk.analyst@bank.com', 'Tom Analyst', 'contributor'),
('00d00004-0002-4000-8000-000000000004', '00c00003-0002-4000-8000-000000000003', 'bsa.officer@bank.com', 'Patricia BSA', 'owner'),
('00d00005-0002-4000-8000-000000000005', '00c00004-0002-4000-8000-000000000004', 'reg.tech@bank.com', 'Kevin RegTech', 'owner'),
('00d00006-0002-4000-8000-000000000006', '00c00005-0002-4000-8000-000000000005', 'banking.analyst@bank.com', 'Laura Banking', 'owner')

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 6. COMPLIANCE POLICIES (FSI-specific)
-- ============================================================================

INSERT INTO compliance_policies (id, name, description, failure_message, rule, category, severity, is_active, created_at, updated_at) VALUES
('01100001-0002-4000-8000-000000000001', 'BCBS 239 Data Lineage', 'Verify all risk data has documented end-to-end lineage per BCBS 239 Principle 4',
'Risk dataset lacks documented data lineage. BCBS 239 requires complete, documented lineage from source to report for all material risk data.',
'MATCH (d:Dataset) WHERE d.domain IN [''Risk Management'', ''Capital Markets''] ASSERT d.has_lineage = true AND d.lineage_validated = true', 'governance', 'critical', true, NOW(), NOW()),

('01100002-0002-4000-8000-000000000002', 'AML Transaction Monitoring Coverage', 'Ensure all customer accounts are covered by AML transaction monitoring',
'Account not covered by AML monitoring. All retail and commercial accounts must be monitored for suspicious activity per BSA requirements.',
'MATCH (a:Account) ASSERT a.aml_monitoring_enabled = true', 'security', 'critical', true, NOW(), NOW()),

('01100003-0002-4000-8000-000000000003', 'KYC Periodic Review', 'Verify KYC profiles are reviewed within regulatory timelines based on risk rating',
'KYC review overdue. High-risk customers must be reviewed annually, medium-risk every 2 years, and low-risk every 3 years.',
'MATCH (c:Customer) ASSERT c.days_since_kyc_review <= CASE c.risk_rating WHEN ''high'' THEN 365 WHEN ''medium'' THEN 730 ELSE 1095 END', 'governance', 'high', true, NOW(), NOW()),

('01100004-0002-4000-8000-000000000004', 'Market Data Timeliness', 'Ensure market data feeds are within acceptable staleness thresholds',
'Market data feed is stale. Real-time feeds must be within 500ms and end-of-day feeds must be available by T+1 06:00 UTC.',
'MATCH (f:MarketDataFeed) WHERE f.feed_type = ''realtime'' ASSERT f.latency_ms <= 500', 'freshness', 'high', true, NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 7. NOTIFICATIONS (FSI-specific)
-- ============================================================================

INSERT INTO notifications (id, type, title, subtitle, description, created_at, read, can_delete, recipient) VALUES
('01000001-0002-4000-8000-000000000001', 'error', 'BCBS 239 Lineage Gap', 'Risk Aggregation Dataset', 'Missing lineage documentation for 3 risk factor inputs in the Market Risk VaR calculation. Remediation required before next CCAR submission.', NOW() - INTERVAL '4 hours', false, false, NULL),
('01000002-0002-4000-8000-000000000002', 'warning', 'KYC Reviews Overdue', '47 High-Risk Customers', '47 high-risk customer KYC profiles are overdue for annual review. Escalation to BSA Officer initiated.', NOW() - INTERVAL '1 day', false, true, NULL),
('01000003-0002-4000-8000-000000000003', 'success', 'CCAR Submission Ready', 'Q4 2025 Stress Test', 'All CCAR datasets validated and reconciled. Submission package ready for Federal Reserve portal upload.', NOW() - INTERVAL '2 days', true, true, NULL),
('01000004-0002-4000-8000-000000000004', 'info', 'New AML Model Deployed', 'v3.2 Network Analysis', 'Updated AML network analysis model deployed to production. Expected 12% improvement in true positive rate for layering detection.', NOW() - INTERVAL '3 days', false, true, NULL)

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 8. METADATA (Notes, Links)
-- ============================================================================

-- Rich Text Notes (type=016)
INSERT INTO rich_text_metadata (id, entity_id, entity_type, title, short_description, content_markdown, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01600001-0002-4000-8000-000000000001', '00700001-0002-4000-8000-000000000001', 'data_product', 'Overview', 'Real-time trading analytics for desks and COO reporting.', E'# Trading Analytics Dashboard v1\n\nReal-time P&L, position analytics, and best execution metrics for equities, fixed income,\nand derivatives trading desks. Powers both intraday trader views and end-of-day COO reports.\n\n## Data Sources\n- FIX execution reports (sub-millisecond)\n- End-of-day position snapshots from booking systems\n- Market data ticks for mark-to-market\n\n## Key Metrics\n- Intraday P&L (realized + unrealized)\n- Best execution TCA (implementation shortfall, VWAP slippage)\n- Risk-adjusted return attribution by strategy', false, 50, true, 'system@demo', NOW(), NOW()),
('01600002-0002-4000-8000-000000000002', '00700002-0002-4000-8000-000000000002', 'data_product', 'Overview', 'BCBS 239-compliant enterprise risk aggregation.', E'# Enterprise Risk Aggregation v1\n\nCentralized risk aggregation platform meeting BCBS 239 principles for risk data accuracy,\ncompleteness, timeliness, and adaptability. Serves CRO dashboard and regulatory submissions.\n\n## Risk Types Covered\n- Market Risk: VaR (historical, Monte Carlo), stressed VaR, IRC\n- Credit Risk: PD, LGD, EAD, expected/unexpected loss\n- Counterparty Risk: CVA, DVA, PFE, wrong-way risk\n- Operational Risk: AMA model outputs\n\n## Regulatory Coverage\nBCBS 239, CCAR/DFAST, FRTB (IMA and SA), Basel III/IV capital calculations.', false, 50, true, 'system@demo', NOW(), NOW()),
('01600003-0002-4000-8000-000000000003', '00700003-0002-4000-8000-000000000003', 'data_product', 'Overview', 'ML-powered AML transaction monitoring and alerts.', E'# AML Transaction Monitoring v1\n\nML-based transaction monitoring system combining rule-based scenarios with network\nanalysis and anomaly detection for anti-money laundering compliance.\n\n## Detection Capabilities\n- Structuring and smurfing detection\n- Layering through complex entity networks\n- Trade-based money laundering signals\n- Rapid movement of funds (velocity checks)\n\n## Investigation Support\n- Auto-generated SAR narratives using NLP\n- Entity relationship visualization\n- Historical transaction pattern comparison\n- OFAC/PEP screening integration', false, 50, true, 'system@demo', NOW(), NOW()),
('01600004-0002-4000-8000-000000000004', '00700004-0002-4000-8000-000000000004', 'data_product', 'Overview', 'Automated regulatory report generation and validation.', E'# Regulatory Reporting Hub v1\n\nCentralized platform for generating, validating, and submitting prudential and conduct\nregulatory reports across multiple jurisdictions.\n\n## Supported Reports\n- FR Y-14A/Q (Fed): Detailed capital and loss projections\n- Call Report (FFIEC): Quarterly condition and income\n- LCR/NSFR: Liquidity coverage and net stable funding\n- CCAR/DFAST: Stress test scenario submissions\n\n## Workflow\n1. Automated data sourcing from upstream risk and finance products\n2. Rule-based validation against regulatory taxonomies\n3. XBRL tagging and cross-filing consistency checks\n4. Dual-approval workflow before portal submission', false, 50, true, 'system@demo', NOW(), NOW()),
('01600005-0002-4000-8000-000000000005', '00700005-0002-4000-8000-000000000005', 'data_product', 'Overview', 'Unified customer view for relationship management.', E'# Customer 360 Banking v1\n\nUnified customer view combining accounts, transactions, KYC profiles, interaction\nhistory, and product holdings for relationship managers and analytics teams.\n\n## Data Integration\n- Core banking: Accounts, balances, transactions\n- CRM: Interactions, complaints, NPS scores\n- KYC/AML: Risk ratings, due diligence status\n- Digital: Online/mobile banking activity, session data\n\n## Use Cases\n- Relationship manager desktop and next-best-action\n- Cross-sell/up-sell propensity scoring\n- Customer lifetime value modeling\n- Attrition risk prediction', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;

-- Link Metadata (type=017)
INSERT INTO link_metadata (id, entity_id, entity_type, title, short_description, url, is_shared, level, inheritable, created_by, created_at, updated_at) VALUES
('01700001-0002-4000-8000-000000000001', '00700001-0002-4000-8000-000000000001', 'data_product', 'Runbook', 'Trading analytics operational procedures.', 'https://runbooks.bank.com/trading/analytics-dashboard-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700002-0002-4000-8000-000000000002', '00700001-0002-4000-8000-000000000001', 'data_product', 'TCA Methodology', 'Transaction cost analysis methodology doc.', 'https://wiki.bank.com/quant/tca-methodology-v3', false, 50, true, 'system@demo', NOW(), NOW()),
('01700003-0002-4000-8000-000000000003', '00700002-0002-4000-8000-000000000002', 'data_product', 'BCBS 239 Compliance Matrix', 'Principle-by-principle compliance mapping.', 'https://wiki.bank.com/risk/bcbs239-compliance-matrix', false, 50, true, 'system@demo', NOW(), NOW()),
('01700004-0002-4000-8000-000000000004', '00700002-0002-4000-8000-000000000002', 'data_product', 'Risk Dashboard', 'CRO risk appetite monitoring.', 'https://bi.bank.com/dashboards/enterprise-risk-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700005-0002-4000-8000-000000000005', '00700003-0002-4000-8000-000000000003', 'data_product', 'Model Validation Report', 'AML model performance and validation.', 'https://docs.bank.com/model-risk/aml-monitoring-v3-validation', false, 50, true, 'system@demo', NOW(), NOW()),
('01700006-0002-4000-8000-000000000006', '00700003-0002-4000-8000-000000000003', 'data_product', 'Investigation Playbook', 'AML investigator workflow guide.', 'https://wiki.bank.com/compliance/aml-investigation-playbook', false, 50, true, 'system@demo', NOW(), NOW()),
('01700007-0002-4000-8000-000000000007', '00700004-0002-4000-8000-000000000004', 'data_product', 'Runbook', 'Regulatory reporting pipeline operations.', 'https://runbooks.bank.com/regulatory/reporting-hub-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('01700008-0002-4000-8000-000000000008', '00700004-0002-4000-8000-000000000004', 'data_product', 'Submission Calendar', 'Regulatory filing deadlines and status.', 'https://wiki.bank.com/regulatory/submission-calendar-2025', false, 50, true, 'system@demo', NOW(), NOW()),
('01700009-0002-4000-8000-000000000009', '00700005-0002-4000-8000-000000000005', 'data_product', 'Runbook', 'Customer 360 pipeline operations.', 'https://runbooks.bank.com/banking/customer-360-v1', false, 50, true, 'system@demo', NOW(), NOW()),
('0170000a-0002-4000-8000-000000000010', '00700005-0002-4000-8000-000000000005', 'data_product', 'RM Desktop Guide', 'Relationship manager user guide.', 'https://wiki.bank.com/banking/rm-desktop-user-guide', false, 50, true, 'system@demo', NOW(), NOW())

ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 9. BUSINESS ROLES (FSI-specific, type=0f0)
-- ============================================================================

INSERT INTO business_roles (id, name, description, category, is_system, is_approver, status, created_by, created_at, updated_at) VALUES
('0f000001-0002-4000-8000-000000000001', 'Chief Risk Officer',          'Accountable for the firm-wide risk framework and BCBS 239 attestation.',                                'governance',  false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000002-0002-4000-8000-000000000002', 'Head of Compliance',          'Owns AML/KYC, sanctions screening, and MAR/MiFID II surveillance programmes.',                          'governance',  false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000003-0002-4000-8000-000000000003', 'Model Risk Manager',          'Validates and monitors quantitative models per SR 11-7 and EU model risk guidance.',                     'governance',  false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000004-0002-4000-8000-000000000004', 'Trading Desk Head',           'Senior trader accountable for desk P&L, risk limits, and best execution.',                              'business',    false, true,  'active', 'system@demo', NOW(), NOW()),
('0f000005-0002-4000-8000-000000000005', 'Regulatory Reporting Lead',   'Owns submissions for FR Y-14, Call Report, LCR/NSFR, FRTB and other prudential filings.',                'operational', false, false, 'active', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 10. DELIVERY METHODS (FSI-specific, type=0f4)
-- ============================================================================

INSERT INTO delivery_methods (id, name, description, category, is_system, status, created_by, created_at, updated_at) VALUES
('0f400001-0002-4000-8000-000000000001', 'FIX Protocol Feed',     'Delivers execution and order events via Financial Information eXchange (FIX 4.4/5.0SP2).',         'streaming', false, 'active', 'system@demo', NOW(), NOW()),
('0f400002-0002-4000-8000-000000000002', 'SWIFT MT Messages',     'Delivers payments and securities messages via SWIFT MT/MX.',                                       'streaming', false, 'active', 'system@demo', NOW(), NOW()),
('0f400003-0002-4000-8000-000000000003', 'Regulatory Portal Submission', 'Submits XBRL-tagged regulatory reports to supervisor portals (Fed, FFIEC, EBA).',          'export',    false, 'active', 'system@demo', NOW(), NOW()),
('0f400004-0002-4000-8000-000000000004', 'Risk Aggregation Cube', 'Materialised cube exposing aggregated risk metrics for CRO dashboards and stress tests.',          'access',    false, 'active', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 11. VERTICAL ASSET TYPES (FSI-specific, is_system=false)
-- ============================================================================

INSERT INTO asset_types (id, name, description, category, icon, required_fields, optional_fields, is_system, status, created_by, created_at, updated_at) VALUES
('0f200101-0002-4000-8000-000000000001', 'Trading Position',  'Open trading position carried on the firm''s books.',                                              'data', 'trending-up',   NULL, NULL, false, 'active', 'system@demo', NOW(), NOW()),
('0f200102-0002-4000-8000-000000000002', 'Risk Limit',        'Configured risk limit (notional, VaR, sensitivity-based) attached to a desk or book.',             'data', 'gauge',         NULL, NULL, false, 'active', 'system@demo', NOW(), NOW()),
('0f200103-0002-4000-8000-000000000003', 'Regulatory Filing', 'Discrete regulatory filing (FR Y-14, FFIEC Call Report, LCR, etc.) with submission lifecycle.',     'data', 'file-text',     NULL, NULL, false, 'active', 'system@demo', NOW(), NOW())
ON CONFLICT (name) DO NOTHING;


-- ============================================================================
-- 12. TAG NAMESPACES + TAGS (FSI governance vocabulary)
-- ============================================================================

INSERT INTO tag_namespaces (id, name, description, created_by, created_at, updated_at) VALUES
('02601001-0002-4000-8000-000000000001', 'fsi-regulatory', 'Banking and capital markets regulatory frameworks.', 'system@demo', NOW(), NOW()),
('02601002-0002-4000-8000-000000000002', 'fsi-risk',       'Risk types and tiering conventions.',                'system@demo', NOW(), NOW()),
('02601003-0002-4000-8000-000000000003', 'fsi-data',       'FSI data classification and lifecycle.',             'system@demo', NOW(), NOW())
ON CONFLICT (name) DO NOTHING;

INSERT INTO tags (id, name, description, possible_values, status, version, namespace_id, parent_id, created_by, created_at, updated_at) VALUES
-- Regulatory
('02700101-0002-4000-8000-000000000001', 'bcbs-239',       'Subject to Basel BCBS 239 risk data aggregation principles.', NULL, 'active', 'v1.0', '02601001-0002-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
('02700102-0002-4000-8000-000000000002', 'mifid-ii',       'Subject to MiFID II / MiFIR transaction reporting.',          NULL, 'active', 'v1.0', '02601001-0002-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
('02700103-0002-4000-8000-000000000003', 'frtb',           'Subject to Fundamental Review of the Trading Book rules.',    NULL, 'active', 'v1.0', '02601001-0002-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
('02700104-0002-4000-8000-000000000004', 'aml-monitored',  'Subject to AML/transaction-monitoring obligations.',          NULL, 'active', 'v1.0', '02601001-0002-4000-8000-000000000001', NULL, 'system@demo', NOW(), NOW()),
-- Risk
('02700105-0002-4000-8000-000000000005', 'risk-tier-1',    'Tier-1 critical for daily risk reporting.',                   NULL, 'active', 'v1.0', '02601002-0002-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
('02700106-0002-4000-8000-000000000006', 'market-risk',    'Market risk relevant.',                                       NULL, 'active', 'v1.0', '02601002-0002-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
('02700107-0002-4000-8000-000000000007', 'credit-risk',    'Credit risk relevant.',                                       NULL, 'active', 'v1.0', '02601002-0002-4000-8000-000000000002', NULL, 'system@demo', NOW(), NOW()),
-- Data
('02700108-0002-4000-8000-000000000008', 'mnpi',           'Material non-public information.',                            NULL, 'active', 'v1.0', '02601003-0002-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW()),
('02700109-0002-4000-8000-000000000009', 'transaction-data','Atomic transaction-level data (no aggregation).',            NULL, 'active', 'v1.0', '02601003-0002-4000-8000-000000000003', NULL, 'system@demo', NOW(), NOW())
ON CONFLICT (namespace_id, name) DO NOTHING;

INSERT INTO tag_namespace_permissions (id, namespace_id, group_id, access_level, created_by, created_at, updated_at) VALUES
('02800101-0002-4000-8000-000000000001', '02601001-0002-4000-8000-000000000001', 'reg-reporting',     'admin',     'system@demo', NOW(), NOW()),
('02800102-0002-4000-8000-000000000002', '02601002-0002-4000-8000-000000000002', 'risk-quant',        'admin',     'system@demo', NOW(), NOW()),
('02800103-0002-4000-8000-000000000003', '02601002-0002-4000-8000-000000000002', 'trading-desk',      'read_only', 'system@demo', NOW(), NOW()),
('02800104-0002-4000-8000-000000000004', '02601003-0002-4000-8000-000000000003', 'compliance',        'admin',     'system@demo', NOW(), NOW())
ON CONFLICT (namespace_id, group_id) DO NOTHING;


-- ============================================================================
-- 13. RDF TRIPLES — FSI concept graph (type=020)
-- ============================================================================

INSERT INTO rdf_triples (id, subject_uri, predicate_uri, object_value, object_is_uri, context_name, source_type, source_identifier, created_by, created_at) VALUES
('02000101-0002-4000-8000-000000000001', 'http://demo.ontos.app/fsi#Trade',           'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('02000102-0002-4000-8000-000000000002', 'http://demo.ontos.app/fsi#Trade',           'http://www.w3.org/2000/01/rdf-schema#label',       'Trade',                                         false, 'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('02000103-0002-4000-8000-000000000003', 'http://demo.ontos.app/fsi#Position',        'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('02000104-0002-4000-8000-000000000004', 'http://demo.ontos.app/fsi#Position',        'http://www.w3.org/2000/01/rdf-schema#label',       'Position',                                      false, 'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('02000105-0002-4000-8000-000000000005', 'http://demo.ontos.app/fsi#Counterparty',    'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('02000106-0002-4000-8000-000000000006', 'http://demo.ontos.app/fsi#Counterparty',    'http://www.w3.org/2000/01/rdf-schema#label',       'Counterparty',                                  false, 'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('02000107-0002-4000-8000-000000000007', 'http://demo.ontos.app/fsi#MarketRisk',      'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('02000108-0002-4000-8000-000000000008', 'http://demo.ontos.app/fsi#MarketRisk',      'http://www.w3.org/2000/01/rdf-schema#label',       'Market Risk',                                   false, 'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('02000109-0002-4000-8000-000000000009', 'http://demo.ontos.app/fsi#CreditRisk',      'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('0200010a-0002-4000-8000-000000000010', 'http://demo.ontos.app/fsi#CreditRisk',      'http://www.w3.org/2000/01/rdf-schema#label',       'Credit Risk',                                   false, 'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('0200010b-0002-4000-8000-000000000011', 'http://demo.ontos.app/fsi#AMLAlert',        'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('0200010c-0002-4000-8000-000000000012', 'http://demo.ontos.app/fsi#AMLAlert',        'http://www.w3.org/2000/01/rdf-schema#label',       'AML Alert',                                     false, 'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('0200010d-0002-4000-8000-000000000013', 'http://demo.ontos.app/fsi#RegulatoryFiling','http://www.w3.org/1999/02/22-rdf-syntax-ns#type',  'http://www.w3.org/2004/02/skos/core#Concept', true,  'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW()),
('0200010e-0002-4000-8000-000000000014', 'http://demo.ontos.app/fsi#RegulatoryFiling','http://www.w3.org/2000/01/rdf-schema#label',       'Regulatory Filing',                             false, 'urn:demo', 'demo', 'demo_data_fsi.sql', 'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 14. ENTITY SEMANTIC LINKS (type=015)
-- ============================================================================

INSERT INTO entity_semantic_links (id, entity_id, entity_type, iri, label, created_by, created_at) VALUES
('01500101-0002-4000-8000-000000000001', '00700001-0002-4000-8000-000000000001', 'data_product', 'http://demo.ontos.app/fsi#Trade',            'Trade',             'system@demo', NOW()),
('01500102-0002-4000-8000-000000000002', '00700001-0002-4000-8000-000000000001', 'data_product', 'http://demo.ontos.app/fsi#Position',         'Position',          'system@demo', NOW()),
('01500103-0002-4000-8000-000000000003', '00700002-0002-4000-8000-000000000002', 'data_product', 'http://demo.ontos.app/fsi#MarketRisk',       'Market Risk',       'system@demo', NOW()),
('01500104-0002-4000-8000-000000000004', '00700002-0002-4000-8000-000000000002', 'data_product', 'http://demo.ontos.app/fsi#CreditRisk',       'Credit Risk',       'system@demo', NOW()),
('01500105-0002-4000-8000-000000000005', '00700003-0002-4000-8000-000000000003', 'data_product', 'http://demo.ontos.app/fsi#AMLAlert',         'AML Alert',         'system@demo', NOW()),
('01500106-0002-4000-8000-000000000006', '00700004-0002-4000-8000-000000000004', 'data_product', 'http://demo.ontos.app/fsi#RegulatoryFiling', 'Regulatory Filing', 'system@demo', NOW()),
('01500107-0002-4000-8000-000000000007', '00700005-0002-4000-8000-000000000005', 'data_product', 'http://demo.ontos.app/fsi#Counterparty',     'Counterparty',      'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 15. ASSETS — FSI catalog objects (type=0f3)
-- ============================================================================

INSERT INTO assets (id, name, description, asset_type_id, platform, location, domain_id, properties, tags, status, created_by, created_at, updated_at) VALUES
-- Trading
('0f300101-0002-4000-8000-000000000001',
 'lakehouse.fsi.trading.executions',
 'FIX-protocol execution reports for equities and FX desks (intraday, sub-second).',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.fsi.trading.executions',
 '00000002-0002-4000-8000-000000000002',
 '{"catalog": "lakehouse", "schema": "fsi_trading", "table_name": "executions", "row_count": 92000000, "format": "delta"}',
 '["transaction-data", "mifid-ii"]',
 'active', 'system@demo', NOW(), NOW()),

-- Trading Position (vertical asset type)
('0f300102-0002-4000-8000-000000000002',
 'positions.equities.eod_2026_05_01',
 'End-of-day equity positions snapshot for May 1 2026.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Trading Position' LIMIT 1), '0f200101-0002-4000-8000-000000000001'), 'Databricks', 'positions.equities.eod_2026_05_01',
 '00000002-0002-4000-8000-000000000002',
 '{"asset_class": "equities", "snapshot_date": "2026-05-01", "instrument_count": 8400}',
 '["risk-tier-1", "market-risk"]',
 'active', 'system@demo', NOW(), NOW()),

-- Risk Limit (vertical asset type)
('0f300103-0002-4000-8000-000000000003',
 'limit.equities.var_99_1d',
 'Equities desk 99% / 1-day VaR limit.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Risk Limit' LIMIT 1), '0f200102-0002-4000-8000-000000000002'), 'Risk System', 'limits/equities/var_99_1d',
 '00000003-0002-4000-8000-000000000003',
 '{"limit_type": "VaR", "confidence": 0.99, "horizon_days": 1, "limit_usd": 25000000}',
 '["risk-tier-1", "market-risk"]',
 'active', 'system@demo', NOW(), NOW()),

-- Risk aggregation table
('0f300104-0002-4000-8000-000000000004',
 'lakehouse.fsi.risk.aggregated_var',
 'Aggregated VaR metrics (firm-wide, by desk, by asset class) feeding CRO dashboard.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.fsi.risk.aggregated_var',
 '00000003-0002-4000-8000-000000000003',
 '{"catalog": "lakehouse", "schema": "fsi_risk", "table_name": "aggregated_var", "format": "delta"}',
 '["bcbs-239", "risk-tier-1"]',
 'active', 'system@demo', NOW(), NOW()),

-- AML stream
('0f300105-0002-4000-8000-000000000005',
 'kafka.fsi.aml.transaction_alerts',
 'Real-time stream of AML scenario hits and ML anomaly alerts.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Stream' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Kafka', 'kafka://broker.bank:9093/aml.transaction_alerts',
 '00000004-0002-4000-8000-000000000004',
 '{"topic": "aml.transaction_alerts", "throughput_msgs_per_sec": 600}',
 '["aml-monitored", "transaction-data"]',
 'active', 'system@demo', NOW(), NOW()),

-- Regulatory Filing (vertical asset type)
('0f300106-0002-4000-8000-000000000006',
 'FFIEC-Call-Report-2026-Q1',
 'FFIEC Call Report quarterly submission for 2026 Q1.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Regulatory Filing' LIMIT 1), '0f200103-0002-4000-8000-000000000003'), 'Reg Portal', 'filings/ffiec/2026-Q1',
 '00000004-0002-4000-8000-000000000004',
 '{"filing_type": "FFIEC Call Report", "period": "2026-Q1", "status": "submitted", "submission_date": "2026-04-30"}',
 '["bcbs-239"]',
 'active', 'system@demo', NOW(), NOW()),

-- Customer table
('0f300107-0002-4000-8000-000000000007',
 'lakehouse.fsi.banking.customer_master',
 'Banking customer master with KYC tier and segment classifications.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Table' LIMIT 1), '0f200001-0000-4000-8000-000000000001'), 'Databricks', 'lakehouse.fsi.banking.customer_master',
 '00000001-0002-4000-8000-000000000001',
 '{"catalog": "lakehouse", "schema": "fsi_banking", "table_name": "customer_master", "row_count": 4200000, "format": "delta"}',
 '["aml-monitored"]',
 'active', 'system@demo', NOW(), NOW()),

-- Dashboard
('0f300108-0002-4000-8000-000000000008',
 'CRO Risk Dashboard',
 'Daily firm-wide risk metrics, breach summary, and stress test results.',
 COALESCE((SELECT id FROM asset_types WHERE name = 'Dashboard' LIMIT 1), '0f200002-0000-4000-8000-000000000002'), 'Databricks', 'https://bi.bank.com/dashboards/cro-risk-v1',
 '00000003-0002-4000-8000-000000000003',
 '{"refresh_schedule": "hourly", "audience": "cro-team"}',
 '["bcbs-239", "risk-tier-1"]',
 'active', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 16. ENTITY RELATIONSHIPS — FSI lineage (type=0fa)
-- ============================================================================

INSERT INTO entity_relationships (id, source_type, source_id, target_type, target_id, relationship_type, created_by, created_at) VALUES
('0fa00101-0002-4000-8000-000000000001', 'data_product', '00700001-0002-4000-8000-000000000001', 'asset', '0f300101-0002-4000-8000-000000000001', 'derives_from', 'system@demo', NOW()),
('0fa00102-0002-4000-8000-000000000002', 'data_product', '00700001-0002-4000-8000-000000000001', 'asset', '0f300102-0002-4000-8000-000000000002', 'derives_from', 'system@demo', NOW()),
('0fa00103-0002-4000-8000-000000000003', 'data_product', '00700002-0002-4000-8000-000000000002', 'asset', '0f300104-0002-4000-8000-000000000004', 'derives_from', 'system@demo', NOW()),
('0fa00104-0002-4000-8000-000000000004', 'data_product', '00700002-0002-4000-8000-000000000002', 'asset', '0f300103-0002-4000-8000-000000000003', 'consumes',     'system@demo', NOW()),
('0fa00105-0002-4000-8000-000000000005', 'data_product', '00700003-0002-4000-8000-000000000003', 'asset', '0f300105-0002-4000-8000-000000000005', 'derives_from', 'system@demo', NOW()),
('0fa00106-0002-4000-8000-000000000006', 'data_product', '00700004-0002-4000-8000-000000000004', 'asset', '0f300106-0002-4000-8000-000000000006', 'produces',     'system@demo', NOW()),
('0fa00107-0002-4000-8000-000000000007', 'data_product', '00700005-0002-4000-8000-000000000005', 'asset', '0f300107-0002-4000-8000-000000000007', 'derives_from', 'system@demo', NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 17. ENTITY TAG ASSOCIATIONS (FSI, type=029)
-- ============================================================================

INSERT INTO entity_tag_associations (id, tag_id, entity_id, entity_type, assigned_value, assigned_by, assigned_at) VALUES
-- Trading Analytics
('02900101-0002-4000-8000-000000000001', '02700102-0002-4000-8000-000000000002', '00700001-0002-4000-8000-000000000001', 'data_product', NULL, 'system@demo', NOW()),
('02900102-0002-4000-8000-000000000002', '02700106-0002-4000-8000-000000000006', '00700001-0002-4000-8000-000000000001', 'data_product', NULL, 'system@demo', NOW()),
-- Enterprise Risk Aggregation
('02900103-0002-4000-8000-000000000003', '02700101-0002-4000-8000-000000000001', '00700002-0002-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),
('02900104-0002-4000-8000-000000000004', '02700105-0002-4000-8000-000000000005', '00700002-0002-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),
('02900105-0002-4000-8000-000000000005', '02700103-0002-4000-8000-000000000003', '00700002-0002-4000-8000-000000000002', 'data_product', NULL, 'system@demo', NOW()),
-- AML Monitoring
('02900106-0002-4000-8000-000000000006', '02700104-0002-4000-8000-000000000004', '00700003-0002-4000-8000-000000000003', 'data_product', NULL, 'system@demo', NOW()),
-- Regulatory Reporting
('02900107-0002-4000-8000-000000000007', '02700101-0002-4000-8000-000000000001', '00700004-0002-4000-8000-000000000004', 'data_product', NULL, 'system@demo', NOW()),
-- Customer 360 Banking
('02900108-0002-4000-8000-000000000008', '02700104-0002-4000-8000-000000000004', '00700005-0002-4000-8000-000000000005', 'data_product', NULL, 'system@demo', NOW())
ON CONFLICT (tag_id, entity_id, entity_type) DO NOTHING;


-- ============================================================================
-- 18. PROCESS WORKFLOWS + STEPS (FSI-specific)
-- ============================================================================

INSERT INTO process_workflows (id, name, description, trigger_config, scope_config, is_active, is_default, version, created_by, updated_by, created_at, updated_at) VALUES
('02a00101-0002-4000-8000-000000000001', 'BCBS 239 Pre-Publish Attestation',
 'Requires CRO sign-off before any risk product is published, per BCBS 239 principles.',
 '{"type": "before_publish", "entity_types": ["data_product"]}',
 '{"type": "domain", "ids": ["00000003-0002-4000-8000-000000000003"]}',
 true, true, 1, 'system@demo', 'system@demo', NOW(), NOW()),
('02a00102-0002-4000-8000-000000000002', 'AML Model Validation Gate',
 'Blocks deployment of AML monitoring updates without independent model validation.',
 '{"type": "before_update", "entity_types": ["data_product"]}',
 '{"type": "domain", "ids": ["00000004-0002-4000-8000-000000000004"]}',
 true, false, 1, 'system@demo', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO workflow_steps (id, workflow_id, step_id, name, step_type, config, on_pass, on_fail, "order", position, created_at, updated_at) VALUES
('02b00101-0002-4000-8000-000000000001', '02a00101-0002-4000-8000-000000000001', 'lineage_check',     'BCBS 239 Lineage Coverage',
 'policy_check',
 '{"policy_id": "01100001-0002-4000-8000-000000000001"}',
 'cro_attest', 'reject', 1, '{"x": 100, "y": 100}', NOW(), NOW()),
('02b00102-0002-4000-8000-000000000002', '02a00101-0002-4000-8000-000000000001', 'cro_attest',        'CRO Attestation',
 'manual_approval',
 '{"approver_role": "0f000001-0002-4000-8000-000000000001"}',
 'approve', 'reject', 2, '{"x": 300, "y": 100}', NOW(), NOW()),
('02b00103-0002-4000-8000-000000000003', '02a00102-0002-4000-8000-000000000002', 'mrm_review',        'Model Risk Manager Review',
 'manual_approval',
 '{"approver_role": "0f000003-0002-4000-8000-000000000003"}',
 'approve', 'reject', 1, '{"x": 100, "y": 100}', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 19. COMPLIANCE RUNS + RESULTS (FSI)
-- ============================================================================

INSERT INTO compliance_runs (id, policy_id, status, started_at, finished_at, success_count, failure_count, score) VALUES
('01200101-0002-4000-8000-000000000001', '01100001-0002-4000-8000-000000000001', 'completed', NOW() - INTERVAL '4 days', NOW() - INTERVAL '4 days' + INTERVAL '15 minutes', 5, 1, 0.833),
('01200102-0002-4000-8000-000000000002', '01100002-0002-4000-8000-000000000002', 'completed', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days' + INTERVAL '6 minutes',  3, 0, 1.000)
ON CONFLICT (id) DO NOTHING;

INSERT INTO compliance_results (id, run_id, object_type, object_id, object_name, passed, message, created_at) VALUES
('01300101-0002-4000-8000-000000000001', '01200101-0002-4000-8000-000000000001', 'data_product', '00700002-0002-4000-8000-000000000002', 'Enterprise Risk Aggregation v1', true,  'Risk aggregation lineage covers all 11 BCBS 239 principles.', NOW() - INTERVAL '4 days'),
('01300102-0002-4000-8000-000000000002', '01200101-0002-4000-8000-000000000001', 'data_product', '00700001-0002-4000-8000-000000000001', 'Trading Analytics Dashboard v1', false, 'Reconciliation lineage missing between FIX feed and EOD positions snapshot.', NOW() - INTERVAL '4 days'),
('01300103-0002-4000-8000-000000000003', '01200102-0002-4000-8000-000000000002', 'data_product', '00700003-0002-4000-8000-000000000003', 'AML Transaction Monitoring v1', true,  'Sanctions screening cycle within 1-day SLA.', NOW() - INTERVAL '2 days')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 20. COST ITEMS (FSI)
-- ============================================================================

INSERT INTO cost_items (id, entity_type, entity_id, title, description, cost_center, custom_center_name, amount_cents, currency, start_month, created_by, created_at, updated_at) VALUES
('01400101-0002-4000-8000-000000000001', 'data_product', '00700001-0002-4000-8000-000000000001', 'Market Data Subscriptions', 'Refinitiv + Bloomberg market-data feeds for trading analytics.', 'tools', NULL, 9800000, 'USD', '2026-01-01', 'system@demo', NOW(), NOW()),
('01400102-0002-4000-8000-000000000002', 'data_product', '00700002-0002-4000-8000-000000000002', 'Risk Compute (DBU)',        'Daily Monte Carlo VaR + stress scenarios.',                       'infrastructure', NULL, 4200000, 'USD', '2026-01-01', 'system@demo', NOW(), NOW()),
('01400103-0002-4000-8000-000000000003', 'data_product', '00700003-0002-4000-8000-000000000003', 'AML Tooling License',       'Annual AML detection and case management tooling.',               'tools', NULL, 1800000, 'USD', '2026-01-01', 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 21. COMMENTS & RATINGS (FSI)
-- ============================================================================

INSERT INTO comments (id, entity_type, entity_id, comment, comment_type, rating, status, created_by, created_at, updated_at) VALUES
('02c00101-0002-4000-8000-000000000001', 'data_product', '00700001-0002-4000-8000-000000000001', 'Real-time TCA is best in class. Latency is excellent.',                       'rating', 5, 'active', 'desk-head@bank.com',         NOW() - INTERVAL '12 days', NOW() - INTERVAL '12 days'),
('02c00102-0002-4000-8000-000000000002', 'data_product', '00700002-0002-4000-8000-000000000002', 'BCBS 239 lineage gaps still tracked in Jira; product otherwise excellent.',  'rating', 4, 'active', 'cro@bank.com',               NOW() - INTERVAL '8 days',  NOW() - INTERVAL '8 days'),
('02c00103-0002-4000-8000-000000000003', 'data_product', '00700003-0002-4000-8000-000000000003', 'False-positive rate dropped 38% after ML migration.',                          'rating', 5, 'active', 'aml-lead@bank.com',          NOW() - INTERVAL '5 days',  NOW() - INTERVAL '5 days'),
('02c00104-0002-4000-8000-000000000004', 'data_product', '00700005-0002-4000-8000-000000000005', 'Customer 360 RM desktop loads quickly; KYC tier integration is great.',       'rating', 4, 'active', 'rm-lead@bank.com',           NOW() - INTERVAL '2 days',  NOW() - INTERVAL '2 days')
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 22. BUSINESS OWNERS (FSI)
-- ============================================================================

INSERT INTO business_owners (id, object_type, object_id, user_email, user_name, role_id, is_active, assigned_at, removed_at, removal_reason, created_by, created_at, updated_at) VALUES
('0fb00101-0002-4000-8000-000000000001', 'data_product',  '00700001-0002-4000-8000-000000000001', 'desk-head@bank.com',     'Trading Desk Head',          '0f000004-0002-4000-8000-000000000004', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0fb00102-0002-4000-8000-000000000002', 'data_product',  '00700002-0002-4000-8000-000000000002', 'cro@bank.com',           'Chief Risk Officer',         '0f000001-0002-4000-8000-000000000001', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0fb00103-0002-4000-8000-000000000003', 'data_product',  '00700003-0002-4000-8000-000000000003', 'aml-lead@bank.com',      'Head of Compliance',         '0f000002-0002-4000-8000-000000000002', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW()),
('0fb00104-0002-4000-8000-000000000004', 'data_product',  '00700004-0002-4000-8000-000000000004', 'reg-reporting@bank.com', 'Regulatory Reporting Lead',  '0f000005-0002-4000-8000-000000000005', true, NOW() - INTERVAL '60 days', NULL, NULL, 'system@demo', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;


-- ============================================================================
-- 23. ENTITY SUBSCRIPTIONS (FSI)
-- ============================================================================

INSERT INTO entity_subscriptions (id, entity_type, entity_id, subscriber_email, subscription_reason, created_at) VALUES
('02200101-0002-4000-8000-000000000001', 'data_product', '00700002-0002-4000-8000-000000000002', 'cro@bank.com',           'owner',    NOW() - INTERVAL '60 days'),
('02200102-0002-4000-8000-000000000002', 'data_product', '00700004-0002-4000-8000-000000000004', 'reg-reporting@bank.com', 'owner',    NOW() - INTERVAL '60 days'),
('02200103-0002-4000-8000-000000000003', 'data_product', '00700001-0002-4000-8000-000000000001', 'risk-quant@bank.com',    'consumer', NOW() - INTERVAL '15 days')
ON CONFLICT DO NOTHING;


COMMIT;

-- ============================================================================
-- End of FSI Demo Data — preset=fsi
-- ============================================================================
