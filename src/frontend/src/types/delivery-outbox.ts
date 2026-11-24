/**
 * The delivery outbox (#1688): changes committed in Ontos and still to deliver
 * through a delivery mode (Git, Unity Catalog, manual), and their last outcome.
 */
import type { ImportDeliveryResult } from '@/types/import-results';

export type DeliveryOutboxStatus = 'pending' | 'delivered' | 'failed';

export interface DeliveryOutboxRow {
  id: string;
  entity_type: string;
  entity_id: string;
  /** Absent when the entity no longer exists. */
  entity_name?: string | null;
  change_type: string;
  mode: string;
  status: DeliveryOutboxStatus;
  /** Code of the last failure, or why nothing was done. */
  code?: string | null;
  params?: Record<string, unknown> | null;
  attempts: number;
  max_attempts: number;
  next_attempt_at?: string | null;
  last_attempt_at?: string | null;
  delivered_at?: string | null;
  queued_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DeliveryOutboxList {
  rows: DeliveryOutboxRow[];
  counts: Partial<Record<DeliveryOutboxStatus, number>>;
}

export interface RedeliverResult {
  entity_type: string;
  entity_id: string;
  delivery?: ImportDeliveryResult | null;
  rows: DeliveryOutboxRow[];
}

/** Where an entity of the outbox is shown in the app, if it has a page. */
export function outboxEntityPath(row: Pick<DeliveryOutboxRow, 'entity_type' | 'entity_id'>):
  string | null {
  if (row.entity_type === 'DataProduct') return `/data-products/${row.entity_id}`;
  return null;
}

/** Codes the outbox and the re-delivery send (`settings:deliveryOutbox.reason.<code>`). */
export const DELIVERY_OUTBOX_REASON_CODES = new Set([
  'delivery_git_unavailable',
  'delivery_git_write_failed',
  'delivery_entity_not_found',
  'delivery_entity_type_unsupported',
  'delivery_no_active_mode',
  'delivery_failed',
]);
