/**
 * Tests for the pure helpers exported from `data-product-details.tsx`.
 *
 * The component file itself pulls in many heavy modules; we deliberately keep
 * these tests at the constant/lookup/helper level to avoid importing the full
 * view. The map and helpers are the contract that has to stay in lock-step
 * with the ontology (`portHas*` predicates in `ontos-ontology.ttl`) and with
 * the persona/permissions model.
 */
import { describe, it, expect } from 'vitest';
import {
  PORT_TO_ASSET_PREDICATE,
  selectPortAssetPredicate,
  buildLinkAssetRequestBody,
  parseStoredViewMode,
  computeDefaultViewMode,
  shouldShowSectionForViewMode,
  formatDateString,
  getStatusBadgeVariant,
  IN_PLACE_EDITABLE_STATUSES,
  isStatusEditableInPlace,
  isPersonalDraftProduct,
  isProductReadOnly,
  canUserModifyProduct,
  resolveDomainLabel,
  isProductActive,
} from './data-product-details';
import { FeatureAccessLevel } from '@/types/settings';

describe('PORT_TO_ASSET_PREDICATE', () => {
  it('maps each deliverable asset type to its ontology predicate', () => {
    expect(PORT_TO_ASSET_PREDICATE).toEqual({
      Table: 'portHasTable',
      View: 'portHasView',
      Dataset: 'portHasDataset',
      APIEndpoint: 'portHasEndpoint',
      MLModel: 'portHasModel',
    });
  });

  it('returns undefined for container types the ontology rejects', () => {
    // Catalog/Schema were the original 422 trigger — they must not have an
    // entry. If someone adds them here, the corresponding TTL predicate must
    // also exist.
    expect(PORT_TO_ASSET_PREDICATE['Catalog' as keyof typeof PORT_TO_ASSET_PREDICATE]).toBeUndefined();
    expect(PORT_TO_ASSET_PREDICATE['Schema' as keyof typeof PORT_TO_ASSET_PREDICATE]).toBeUndefined();
  });

  it('returns undefined for unknown types so callers can skip + warn', () => {
    expect(PORT_TO_ASSET_PREDICATE['Notebook' as keyof typeof PORT_TO_ASSET_PREDICATE]).toBeUndefined();
    expect(PORT_TO_ASSET_PREDICATE['Dashboard' as keyof typeof PORT_TO_ASSET_PREDICATE]).toBeUndefined();
  });
});

/**
 * Predicate-selection behaviour expected of `handleLinkAssets`. We test the
 * pure logic (compute predicate from asset type) here; the wired-in fetch is
 * verified end-to-end against the deployed app.
 */
describe('selectPortAssetPredicate', () => {
  it.each([
    ['Table', 'portHasTable'],
    ['View', 'portHasView'],
    ['Dataset', 'portHasDataset'],
    ['APIEndpoint', 'portHasEndpoint'],
    ['MLModel', 'portHasModel'],
  ])('picks %s → %s', (assetType, predicate) => {
    expect(selectPortAssetPredicate(assetType)).toBe(predicate);
  });

  it('returns undefined for Catalog/Schema (the original 422 trigger)', () => {
    expect(selectPortAssetPredicate('Catalog')).toBeUndefined();
    expect(selectPortAssetPredicate('Schema')).toBeUndefined();
  });

  it('returns undefined when asset_type_name is missing', () => {
    expect(selectPortAssetPredicate(undefined)).toBeUndefined();
    expect(selectPortAssetPredicate(null)).toBeUndefined();
    expect(selectPortAssetPredicate('')).toBeUndefined();
  });
});

/**
 * The body builder consumed by `handleLinkAssets` to POST to
 * `/api/entity-relationships`. Returns `null` for unsupported types so the
 * caller skips the request instead of letting the backend 422.
 */
describe('buildLinkAssetRequestBody', () => {
  const PORT_ID = 'port-abc-123';

  it.each([
    ['Table', 'portHasTable'],
    ['View', 'portHasView'],
    ['Dataset', 'portHasDataset'],
    ['APIEndpoint', 'portHasEndpoint'],
    ['MLModel', 'portHasModel'],
  ])('builds the right body for %s', (assetType, predicate) => {
    const asset = { id: 'asset-1', asset_type_name: assetType };
    expect(buildLinkAssetRequestBody(asset, PORT_ID)).toEqual({
      source_type: 'OutputPort',
      source_id: PORT_ID,
      target_type: assetType,
      target_id: 'asset-1',
      relationship_type: predicate,
    });
  });

  it('returns null for Catalog/Schema (unsupported by the ontology)', () => {
    expect(buildLinkAssetRequestBody({ id: 'a', asset_type_name: 'Catalog' }, PORT_ID)).toBeNull();
    expect(buildLinkAssetRequestBody({ id: 'a', asset_type_name: 'Schema' }, PORT_ID)).toBeNull();
  });

  it('returns null for unknown asset types', () => {
    expect(buildLinkAssetRequestBody({ id: 'a', asset_type_name: 'Notebook' }, PORT_ID)).toBeNull();
    expect(buildLinkAssetRequestBody({ id: 'a', asset_type_name: 'Dashboard' }, PORT_ID)).toBeNull();
  });

  it('returns null when asset_type_name is missing or empty', () => {
    expect(buildLinkAssetRequestBody({ id: 'a' }, PORT_ID)).toBeNull();
    expect(buildLinkAssetRequestBody({ id: 'a', asset_type_name: undefined }, PORT_ID)).toBeNull();
    expect(buildLinkAssetRequestBody({ id: 'a', asset_type_name: null }, PORT_ID)).toBeNull();
    expect(buildLinkAssetRequestBody({ id: 'a', asset_type_name: '' }, PORT_ID)).toBeNull();
  });

  it('returns null when asset itself is missing', () => {
    expect(buildLinkAssetRequestBody(null, PORT_ID)).toBeNull();
    expect(buildLinkAssetRequestBody(undefined, PORT_ID)).toBeNull();
  });

  it('wires source_id from portId and target_id from asset.id', () => {
    const body = buildLinkAssetRequestBody(
      { id: 'asset-xyz', asset_type_name: 'Table' },
      'port-foo',
    );
    expect(body).not.toBeNull();
    expect(body!.source_id).toBe('port-foo');
    expect(body!.target_id).toBe('asset-xyz');
  });

  it('always sets source_type to OutputPort', () => {
    const body = buildLinkAssetRequestBody(
      { id: 'a', asset_type_name: 'MLModel' },
      PORT_ID,
    );
    expect(body!.source_type).toBe('OutputPort');
  });
});

describe('parseStoredViewMode', () => {
  it.each(['minimal', 'medium', 'large'])('accepts known mode "%s"', (mode) => {
    expect(parseStoredViewMode(mode)).toBe(mode);
  });

  it('returns null for unknown values', () => {
    expect(parseStoredViewMode('huge')).toBeNull();
    expect(parseStoredViewMode('Minimal')).toBeNull(); // case-sensitive on purpose
  });

  it('returns null when nothing is stored', () => {
    expect(parseStoredViewMode(null)).toBeNull();
    expect(parseStoredViewMode(undefined)).toBeNull();
    expect(parseStoredViewMode('')).toBeNull();
  });
});

describe('computeDefaultViewMode', () => {
  it("returns 'large' when the user is in the product's owner team", () => {
    expect(
      computeDefaultViewMode({
        ownerTeamId: 'team-a',
        userGroups: ['team-a', 'team-b'],
        permissionLevel: FeatureAccessLevel.READ_ONLY,
      }),
    ).toBe('large');
  });

  it.each([FeatureAccessLevel.READ_WRITE, FeatureAccessLevel.ADMIN, FeatureAccessLevel.FULL])(
    "returns 'medium' for write-class permission %s",
    (level) => {
      expect(
        computeDefaultViewMode({
          ownerTeamId: 'team-x',
          userGroups: ['team-y'],
          permissionLevel: level,
        }),
      ).toBe('medium');
    },
  );

  it.each([FeatureAccessLevel.READ_ONLY, FeatureAccessLevel.NONE, FeatureAccessLevel.FILTERED])(
    "returns 'minimal' for read-class permission %s",
    (level) => {
      expect(
        computeDefaultViewMode({
          ownerTeamId: 'team-x',
          userGroups: ['team-y'],
          permissionLevel: level,
        }),
      ).toBe('minimal');
    },
  );

  it('returns minimal when groups / ownerTeamId are missing', () => {
    expect(computeDefaultViewMode({})).toBe('minimal');
    expect(computeDefaultViewMode({ ownerTeamId: 'team-a' })).toBe('minimal');
    expect(computeDefaultViewMode({ userGroups: ['team-a'] })).toBe('minimal');
  });

  it('owner-team match wins over a low permission level', () => {
    expect(
      computeDefaultViewMode({
        ownerTeamId: 'team-a',
        userGroups: ['team-a'],
        permissionLevel: FeatureAccessLevel.NONE,
      }),
    ).toBe('large');
  });
});

describe('shouldShowSectionForViewMode', () => {
  it("'minimal' view shows only deliverables / description / hierarchy", () => {
    expect(shouldShowSectionForViewMode('minimal', 'deliverables')).toBe(true);
    expect(shouldShowSectionForViewMode('minimal', 'description')).toBe(true);
    expect(shouldShowSectionForViewMode('minimal', 'hierarchy')).toBe(true);
    expect(shouldShowSectionForViewMode('minimal', 'metadata-panel')).toBe(false);
    expect(shouldShowSectionForViewMode('minimal', 'costs')).toBe(false);
  });

  it("'medium' view hides admin-heavy sections but shows the rest", () => {
    expect(shouldShowSectionForViewMode('medium', 'management-ports')).toBe(false);
    expect(shouldShowSectionForViewMode('medium', 'support-channels')).toBe(false);
    expect(shouldShowSectionForViewMode('medium', 'metadata-panel')).toBe(false);
    expect(shouldShowSectionForViewMode('medium', 'ratings')).toBe(false);
    expect(shouldShowSectionForViewMode('medium', 'costs')).toBe(false);
    expect(shouldShowSectionForViewMode('medium', 'quality')).toBe(false);
    expect(shouldShowSectionForViewMode('medium', 'deliverables')).toBe(true);
    expect(shouldShowSectionForViewMode('medium', 'description')).toBe(true);
  });

  it("'large' view shows everything", () => {
    expect(shouldShowSectionForViewMode('large', 'management-ports')).toBe(true);
    expect(shouldShowSectionForViewMode('large', 'metadata-panel')).toBe(true);
    expect(shouldShowSectionForViewMode('large', 'anything-at-all')).toBe(true);
  });

  it('unknown view modes hide everything', () => {
    // @ts-expect-error - runtime guard against bad localStorage values
    expect(shouldShowSectionForViewMode('xxl', 'deliverables')).toBe(false);
  });
});

describe('formatDateString', () => {
  it('returns the fallback for empty / undefined / null input', () => {
    expect(formatDateString(undefined)).toBe('N/A');
    expect(formatDateString(null)).toBe('N/A');
    expect(formatDateString('')).toBe('N/A');
    expect(formatDateString(undefined, '—')).toBe('—');
  });

  it("returns 'Invalid Date' for unparseable input", () => {
    expect(formatDateString('not-a-real-date')).toBe('Invalid Date');
  });

  it('formats a valid ISO date string', () => {
    // Don't assert on locale-specific format; just confirm we get something
    // non-empty and not the fallback / error sentinel.
    const out = formatDateString('2025-01-02T03:04:05Z');
    expect(out).not.toBe('N/A');
    expect(out).not.toBe('Invalid Date');
    expect(out.length).toBeGreaterThan(0);
  });
});

describe('getStatusBadgeVariant', () => {
  it.each([
    ['active', 'default'],
    ['Active', 'default'],
    ['ACTIVE', 'default'],
  ])('maps %s → default', (status, variant) => {
    expect(getStatusBadgeVariant(status)).toBe(variant);
  });

  it.each([
    ['draft', 'secondary'],
    ['proposed', 'secondary'],
  ])('maps %s → secondary', (status, variant) => {
    expect(getStatusBadgeVariant(status)).toBe(variant);
  });

  it.each([
    ['retired', 'outline'],
    ['deprecated', 'outline'],
  ])('maps %s → outline', (status, variant) => {
    expect(getStatusBadgeVariant(status)).toBe(variant);
  });

  it("falls back to 'default' for unknown / missing status", () => {
    expect(getStatusBadgeVariant(undefined)).toBe('default');
    expect(getStatusBadgeVariant(null)).toBe('default');
    expect(getStatusBadgeVariant('')).toBe('default');
    expect(getStatusBadgeVariant('archived')).toBe('default');
  });
});

describe('IN_PLACE_EDITABLE_STATUSES', () => {
  it('contains exactly the lifecycle statuses where in-place editing is allowed', () => {
    expect(IN_PLACE_EDITABLE_STATUSES).toEqual([
      'draft',
      'sandbox',
      'proposed',
      'under_review',
      'approved',
    ]);
  });
});

describe('isStatusEditableInPlace', () => {
  it.each(['draft', 'sandbox', 'proposed', 'under_review', 'approved'])(
    "%s is editable in place",
    (status) => {
      expect(isStatusEditableInPlace(status)).toBe(true);
    },
  );

  it('case-insensitive on the input', () => {
    expect(isStatusEditableInPlace('DRAFT')).toBe(true);
    expect(isStatusEditableInPlace('Sandbox')).toBe(true);
    expect(isStatusEditableInPlace('Under_Review')).toBe(true);
  });

  it.each(['active', 'retired', 'deprecated'])(
    "'%s' is NOT editable in place (must be cloned)",
    (status) => {
      expect(isStatusEditableInPlace(status)).toBe(false);
    },
  );

  it('returns false for missing / empty status', () => {
    expect(isStatusEditableInPlace(undefined)).toBe(false);
    expect(isStatusEditableInPlace(null)).toBe(false);
    expect(isStatusEditableInPlace('')).toBe(false);
  });
});

describe('isPersonalDraftProduct', () => {
  it('is true when draftOwnerId is set to a string', () => {
    expect(isPersonalDraftProduct({ draftOwnerId: 'user-1' })).toBe(true);
  });

  it('is false when draftOwnerId is null / undefined / missing', () => {
    expect(isPersonalDraftProduct({ draftOwnerId: null })).toBe(false);
    expect(isPersonalDraftProduct({ draftOwnerId: undefined })).toBe(false);
    expect(isPersonalDraftProduct({})).toBe(false);
  });

  it('is false when product itself is null / undefined', () => {
    expect(isPersonalDraftProduct(null)).toBe(false);
    expect(isPersonalDraftProduct(undefined)).toBe(false);
  });
});

describe('isProductReadOnly', () => {
  it('admin is never read-only', () => {
    expect(
      isProductReadOnly({ canAdmin: true, canEditInPlace: false, isPersonalDraft: false }),
    ).toBe(false);
  });

  it('non-admin with editable-in-place status is not read-only', () => {
    expect(
      isProductReadOnly({ canAdmin: false, canEditInPlace: true, isPersonalDraft: false }),
    ).toBe(false);
  });

  it('non-admin on a personal draft is not read-only', () => {
    expect(
      isProductReadOnly({ canAdmin: false, canEditInPlace: false, isPersonalDraft: true }),
    ).toBe(false);
  });

  it('non-admin, non-editable, non-personal-draft is read-only', () => {
    expect(
      isProductReadOnly({ canAdmin: false, canEditInPlace: false, isPersonalDraft: false }),
    ).toBe(true);
  });
});

describe('canUserModifyProduct', () => {
  it('admin can always modify, regardless of other flags', () => {
    expect(
      canUserModifyProduct({
        canAdmin: true,
        canWrite: false,
        canEditInPlace: false,
        isPersonalDraft: false,
      }),
    ).toBe(true);
  });

  it('writer can modify when status is editable in place', () => {
    expect(
      canUserModifyProduct({
        canAdmin: false,
        canWrite: true,
        canEditInPlace: true,
        isPersonalDraft: false,
      }),
    ).toBe(true);
  });

  it('writer can modify a personal draft even on a locked status', () => {
    expect(
      canUserModifyProduct({
        canAdmin: false,
        canWrite: true,
        canEditInPlace: false,
        isPersonalDraft: true,
      }),
    ).toBe(true);
  });

  it('writer cannot modify a locked status that is not their personal draft', () => {
    expect(
      canUserModifyProduct({
        canAdmin: false,
        canWrite: true,
        canEditInPlace: false,
        isPersonalDraft: false,
      }),
    ).toBe(false);
  });

  it('non-writer non-admin can never modify', () => {
    expect(
      canUserModifyProduct({
        canAdmin: false,
        canWrite: false,
        canEditInPlace: true,
        isPersonalDraft: true,
      }),
    ).toBe(false);
  });
});

describe('resolveDomainLabel', () => {
  const NOT_ASSIGNED = '— not assigned —';

  it('returns the resolved name when the lookup succeeds', () => {
    expect(
      resolveDomainLabel({
        domain: 'dom-1',
        resolveName: () => 'Sales',
        notAssignedLabel: NOT_ASSIGNED,
      }),
    ).toBe('Sales');
  });

  it('falls back to the raw domain id when the lookup misses', () => {
    expect(
      resolveDomainLabel({
        domain: 'dom-orphan',
        resolveName: () => undefined,
        notAssignedLabel: NOT_ASSIGNED,
      }),
    ).toBe('dom-orphan');
    expect(
      resolveDomainLabel({
        domain: 'dom-orphan',
        resolveName: () => null,
        notAssignedLabel: NOT_ASSIGNED,
      }),
    ).toBe('dom-orphan');
    expect(
      resolveDomainLabel({
        domain: 'dom-orphan',
        resolveName: () => '',
        notAssignedLabel: NOT_ASSIGNED,
      }),
    ).toBe('dom-orphan');
  });

  it('returns the not-assigned label when the product has no domain', () => {
    const resolveName = () => 'should-not-be-called';
    expect(
      resolveDomainLabel({ domain: undefined, resolveName, notAssignedLabel: NOT_ASSIGNED }),
    ).toBe(NOT_ASSIGNED);
    expect(
      resolveDomainLabel({ domain: null, resolveName, notAssignedLabel: NOT_ASSIGNED }),
    ).toBe(NOT_ASSIGNED);
    expect(
      resolveDomainLabel({ domain: '', resolveName, notAssignedLabel: NOT_ASSIGNED }),
    ).toBe(NOT_ASSIGNED);
  });
});

describe('isProductActive', () => {
  it.each(['active', 'Active', 'ACTIVE'])('is true for %s', (status) => {
    expect(isProductActive(status)).toBe(true);
  });

  it.each(['draft', 'retired', 'deprecated', 'sandbox'])('is false for %s', (status) => {
    expect(isProductActive(status)).toBe(false);
  });

  it('is false for missing status', () => {
    expect(isProductActive(undefined)).toBe(false);
    expect(isProductActive(null)).toBe(false);
    expect(isProductActive('')).toBe(false);
  });
});
