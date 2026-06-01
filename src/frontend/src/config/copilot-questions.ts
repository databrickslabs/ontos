import { FeatureAccessLevel } from '@/types/settings';

export interface CopilotQuestionDef {
  key: string;
  category: string;
  contexts: string[];
  featureId: string;
  minAccess: FeatureAccessLevel;
  /**
   * Optional adoption-mode filter. When set, the question is ONLY
   * surfaced if the current workspace adoption_mode matches.
   *
   * - `'blank'`: workspace has no published data products yet —
   *   onboarding-style "how do I get started" questions.
   * - `'active'`: workspace has published products — operational
   *   "show me failing checks", "low quality scores" style.
   * - omitted: question is mode-agnostic and shown regardless.
   */
  adoptionMode?: 'blank' | 'active';
  /**
   * When `true`, the question is only surfaced on detail pages
   * where a `selectedEntity` is present in `pageContext`. The
   * localized text MUST use the `{{entityName}}` placeholder, which
   * the hook substitutes with the current entity's name (e.g.
   * `Customer 360`). Without an entity selected, the question is
   * hidden — list pages stay focused on list-level prompts.
   */
  requiresEntity?: boolean;
}

export const COPILOT_CATEGORIES = [
  'getting_started',
  'explore',
  'build',
  'govern',
  'operate',
] as const;

export type CopilotCategory = (typeof COPILOT_CATEGORIES)[number];

export const COPILOT_QUESTIONS: CopilotQuestionDef[] = [
  // ── Getting Started (blank workspace) ─────────────────────────────
  // Surface ONLY when the backend reports `adoption_mode='blank'`.
  // Wording is neutral / generic — no customer specifics. Order in
  // this list = display order within the group.
  { key: 'gs_create_first_product',   category: 'getting_started', contexts: [], featureId: 'data-products',  minAccess: FeatureAccessLevel.READ_ONLY, adoptionMode: 'blank' },
  { key: 'gs_setup_domains',          category: 'getting_started', contexts: [], featureId: 'data-domains',   minAccess: FeatureAccessLevel.READ_ONLY, adoptionMode: 'blank' },
  { key: 'gs_assign_roles',           category: 'getting_started', contexts: [], featureId: 'settings',       minAccess: FeatureAccessLevel.READ_ONLY, adoptionMode: 'blank' },
  { key: 'gs_what_is_ontos',          category: 'getting_started', contexts: [], featureId: 'search',         minAccess: FeatureAccessLevel.READ_ONLY, adoptionMode: 'blank' },
  { key: 'gs_concepts_overview',      category: 'getting_started', contexts: [], featureId: 'search',         minAccess: FeatureAccessLevel.READ_ONLY, adoptionMode: 'blank' },

  // ── Explore & Discover ────────────────────────────────────────────

  // Global / Home – any authenticated user
  { key: 'global_find_customer_data',      category: 'explore', contexts: [],                featureId: 'search',          minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'global_business_terms_sales',    category: 'explore', contexts: [],                featureId: 'search',          minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'global_what_domains_exist',      category: 'explore', contexts: [],                featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_ONLY },

  // Marketplace
  { key: 'mp_browse_products',             category: 'explore', contexts: ['marketplace'],   featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'mp_product_cost',               category: 'explore', contexts: ['marketplace'],   featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'mp_subscribe_product',          category: 'explore', contexts: ['marketplace'],   featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY },

  // Data Catalog
  { key: 'dc_search_tables',              category: 'explore', contexts: ['data-catalog'],  featureId: 'data-catalog',    minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'dc_find_columns',               category: 'explore', contexts: ['data-catalog'],  featureId: 'data-catalog',    minAccess: FeatureAccessLevel.READ_ONLY },

  // Search
  { key: 'search_across_all',             category: 'explore', contexts: ['search'],        featureId: 'search',          minAccess: FeatureAccessLevel.READ_ONLY },

  // ── Build & Create ───────────────────────────────────────────────

  // Data Products – read-only
  { key: 'dp_list_domain',                category: 'build',   contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'dp_show_contracts',             category: 'build',   contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  // Data Products – entity-templated (detail-page only)
  { key: 'dp_quality_score',              category: 'explore', contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dp_owner',                      category: 'explore', contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dp_schema',                     category: 'explore', contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dp_last_updated',               category: 'explore', contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dp_subscribe',                  category: 'explore', contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dp_consumers',                  category: 'govern',  contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  // Data Products – contributor
  { key: 'dp_draft_product',              category: 'build',   contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_WRITE },
  { key: 'dp_package_tables',             category: 'build',   contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_WRITE },
  { key: 'dp_add_output_port',            category: 'build',   contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_WRITE },
  { key: 'dp_publication_status',         category: 'build',   contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_WRITE, requiresEntity: true },
  { key: 'dp_publish_blockers',           category: 'build',   contexts: ['data-products'], featureId: 'data-products',   minAccess: FeatureAccessLevel.READ_WRITE, requiresEntity: true },

  // Data Contracts – read-only
  { key: 'ct_show_failing',               category: 'build',   contexts: ['data-contracts'], featureId: 'data-contracts', minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'ct_explain_quality',            category: 'build',   contexts: ['data-contracts'], featureId: 'data-contracts', minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  // Data Contracts – entity-templated (detail-page only)
  { key: 'ct_what_covers',                category: 'explore', contexts: ['data-contracts'], featureId: 'data-contracts', minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'ct_used_by',                    category: 'build',   contexts: ['data-contracts'], featureId: 'data-contracts', minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'ct_owner',                      category: 'govern',  contexts: ['data-contracts'], featureId: 'data-contracts', minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  // Data Contracts – contributor
  { key: 'ct_create_contract',            category: 'build',   contexts: ['data-contracts'], featureId: 'data-contracts', minAccess: FeatureAccessLevel.READ_WRITE },
  { key: 'ct_add_quality_check',          category: 'build',   contexts: ['data-contracts'], featureId: 'data-contracts', minAccess: FeatureAccessLevel.READ_WRITE, requiresEntity: true },
  { key: 'ct_version_impact',             category: 'build',   contexts: ['data-contracts'], featureId: 'data-contracts', minAccess: FeatureAccessLevel.READ_WRITE, requiresEntity: true },

  // Concepts / Semantic Models – read-only
  { key: 'sm_explain_concept_property',   category: 'build',   contexts: ['concepts'],      featureId: 'semantic-models', minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'sm_browse_collections',         category: 'build',   contexts: ['concepts'],      featureId: 'semantic-models', minAccess: FeatureAccessLevel.READ_ONLY },
  // Concepts – contributor
  { key: 'sm_define_vocabulary',          category: 'build',   contexts: ['concepts'],      featureId: 'semantic-models', minAccess: FeatureAccessLevel.READ_WRITE },
  { key: 'sm_suggest_concepts',           category: 'build',   contexts: ['concepts'],      featureId: 'semantic-models', minAccess: FeatureAccessLevel.READ_WRITE },

  // Assets
  { key: 'asset_find_unmapped',           category: 'build',   contexts: ['assets'],        featureId: 'assets',          minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'asset_map_columns',             category: 'build',   contexts: ['assets'],        featureId: 'assets',          minAccess: FeatureAccessLevel.READ_WRITE },
  { key: 'asset_show_lineage',            category: 'build',   contexts: ['assets'],        featureId: 'assets',          minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  // Assets – entity-templated (detail-page only)
  { key: 'asset_built_on',                category: 'explore', contexts: ['assets'],        featureId: 'assets',          minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'asset_freshness',               category: 'explore', contexts: ['assets'],        featureId: 'assets',          minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'asset_quality',                 category: 'explore', contexts: ['assets'],        featureId: 'assets',          minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'asset_consumers',               category: 'govern',  contexts: ['assets'],        featureId: 'assets',          minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },

  // ── Govern & Comply ──────────────────────────────────────────────

  // Compliance – read-only
  { key: 'comp_low_scores',               category: 'govern',  contexts: ['compliance'],    featureId: 'compliance',      minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'comp_failing_checks',           category: 'govern',  contexts: ['compliance'],    featureId: 'compliance',      minAccess: FeatureAccessLevel.READ_ONLY },
  // Compliance – contributor
  { key: 'comp_create_policy',            category: 'govern',  contexts: ['compliance'],    featureId: 'compliance',      minAccess: FeatureAccessLevel.READ_WRITE },

  // Data Domains
  { key: 'dom_list_domains',              category: 'govern',  contexts: ['data-domains'],  featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_ONLY },
  // `dom_domain_health` is kept as-is for backward compat — its localized
  // text still works for detail pages (the placeholder substitution simply
  // applies). `dom_health_detail` is the new explicit-entity variant.
  { key: 'dom_domain_health',             category: 'govern',  contexts: ['data-domains'],  featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dom_create_domain',             category: 'govern',  contexts: ['data-domains'],  featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_WRITE },
  // Data Domains – entity-templated (detail-page only)
  { key: 'dom_products_in',               category: 'explore', contexts: ['data-domains'],  featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dom_business_terms',            category: 'explore', contexts: ['data-domains'],  featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dom_owner',                     category: 'govern',  contexts: ['data-domains'],  featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },
  { key: 'dom_health_detail',             category: 'govern',  contexts: ['data-domains'],  featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_ONLY, requiresEntity: true },

  // Asset Reviews
  { key: 'rev_pending_reviews',           category: 'govern',  contexts: ['data-asset-reviews'], featureId: 'data-asset-reviews', minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'rev_start_review',             category: 'govern',  contexts: ['data-asset-reviews'], featureId: 'data-asset-reviews', minAccess: FeatureAccessLevel.READ_WRITE },

  // Global governance questions
  { key: 'gov_semantic_coverage',         category: 'govern',  contexts: [],                featureId: 'compliance',      minAccess: FeatureAccessLevel.READ_ONLY },
  { key: 'gov_domains_ready',             category: 'govern',  contexts: [],                featureId: 'data-domains',    minAccess: FeatureAccessLevel.READ_ONLY },

  // ── Operate & Deploy ─────────────────────────────────────────────

  // Catalog Commander
  { key: 'cc_table_columns',              category: 'operate', contexts: ['catalog-commander'], featureId: 'catalog-commander', minAccess: FeatureAccessLevel.FULL },
  { key: 'cc_table_owner',                category: 'operate', contexts: ['catalog-commander'], featureId: 'catalog-commander', minAccess: FeatureAccessLevel.FULL },
  { key: 'cc_table_usage',                category: 'operate', contexts: ['catalog-commander'], featureId: 'catalog-commander', minAccess: FeatureAccessLevel.FULL },

  // Settings – admin only
  { key: 'settings_manage_roles',         category: 'operate', contexts: ['settings'],      featureId: 'settings',        minAccess: FeatureAccessLevel.ADMIN },
  { key: 'settings_configure_jobs',       category: 'operate', contexts: ['settings'],      featureId: 'settings',        minAccess: FeatureAccessLevel.ADMIN },
];
