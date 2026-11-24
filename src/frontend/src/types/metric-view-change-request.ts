import type { MetricViewDefinition } from '@/types/data-asset-review';

type MetricViewSpec = NonNullable<MetricViewDefinition['metric_view']>;

/** Status of a metric view definition change request (#1124 phase 3). */
export type MetricViewChangeRequestStatus =
  | 'draft'
  | 'in_review'
  | 'approved'
  | 'rejected'
  | 'delivered'
  | 'failed'
  | 'cancelled';

/** A pre-check warning or a delivery error: a code the UI translates. */
export interface CodedNote {
  code: string;
  message: string;
  params?: Record<string, unknown>;
}

export interface MetricViewChangeRequest {
  id: string;
  asset_id: string;
  metric_view_fqn: string;
  status: MetricViewChangeRequestStatus;
  justification?: string | null;
  base_digest: string;
  proposed_digest: string;
  proposed_definition: string;
  warnings: CodedNote[];
  error?: CodedNote | null;
  delivery_mode?: string | null;
  delivery_reference?: string | null;
  workflow_execution_id?: string | null;
  requested_by: string;
  decided_by?: string | null;
  decision_message?: string | null;
  created_at?: string | null;
  submitted_at?: string | null;
  decided_at?: string | null;
  delivered_at?: string | null;
  applied_at?: string | null;
  ddl?: string | null;
}

export interface MetricViewChangeRequestDetail extends MetricViewChangeRequest {
  base_definition: string;
  base_metric_view?: MetricViewSpec | null;
  proposed_metric_view?: MetricViewSpec | null;
}
