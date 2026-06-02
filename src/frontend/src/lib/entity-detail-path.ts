/**
 * Resolve the in-app detail route for a notification / workflow payload that
 * references an entity. Centralised here so the notification bell, approval
 * dialog, and any future surface that wants to deep-link from a payload all
 * agree on which entity types are linkable.
 *
 * Supported keys (checked in order):
 *   - `product_id` / `data_product_id` → `/data-products/<id>`
 *   - `contract_id` / `data_contract_id` → `/data-contracts/<id>`
 *   - `entity_id` + `entity_type` ∈ {data_product, data_contract}
 *
 * Returns `null` when the entity type is not linkable (e.g. the proxy
 * `access_grant` type — callers should use `underlying_entity_type` /
 * `underlying_entity_id` instead).
 */
export function getEntityDetailPathFromPayload(
  payload: Record<string, unknown> | null | undefined,
): string | null {
  if (!payload || typeof payload !== 'object') return null;

  const productId = payload.product_id ?? payload.data_product_id;
  if (typeof productId === 'string' && productId.length > 0) {
    return `/data-products/${productId}`;
  }

  const contractId = payload.contract_id ?? payload.data_contract_id;
  if (typeof contractId === 'string' && contractId.length > 0) {
    return `/data-contracts/${contractId}`;
  }

  const entityId = payload.entity_id;
  const rawType = payload.entity_type;
  if (typeof entityId !== 'string' || !entityId) return null;
  const entityType = typeof rawType === 'string' ? rawType.toLowerCase() : '';
  if (entityType === 'data_product' || entityType === 'dataproduct') {
    return `/data-products/${entityId}`;
  }
  if (entityType === 'data_contract' || entityType === 'datacontract') {
    return `/data-contracts/${entityId}`;
  }
  return null;
}

/**
 * Variant that resolves the path for the *underlying* entity carried by a
 * workflow approval payload. Access-grant approvals have `entity_type` set to
 * the proxy `access_grant` and the real resource lives under
 * `underlying_entity_*`.
 */
export function getUnderlyingEntityDetailPath(
  payload: Record<string, unknown> | null | undefined,
): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const underlyingType = payload.underlying_entity_type;
  const underlyingId = payload.underlying_entity_id;
  if (typeof underlyingType === 'string' && typeof underlyingId === 'string') {
    return getEntityDetailPathFromPayload({
      entity_type: underlyingType,
      entity_id: underlyingId,
    });
  }
  return getEntityDetailPathFromPayload(payload);
}
