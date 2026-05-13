/**
 * Tests for the trigger-picker filter/group logic.
 *
 * We test the exported pure function `partitionTriggers` rather than
 * rendering the full component, because the underlying Radix <Select>
 * hangs in jsdom (see role-form-dialog.test.tsx for prior art).
 */
import { describe, it, expect } from 'vitest';

import {
  partitionTriggers,
  TRIGGER_GROUP_LABELS,
  type TriggerTypeOption,
} from './trigger-picker';

const CATALOG: TriggerTypeOption[] = [
  {
    value: 'on_create',
    label: 'After entity is created',
    workflow_type: 'process',
    entity_types: ['table'],
    is_advanced: false,
    group: 'lifecycle',
  },
  {
    value: 'on_update',
    label: 'After entity is updated',
    workflow_type: 'process',
    entity_types: ['data_product'],
    is_advanced: false,
    group: 'lifecycle',
  },
  {
    value: 'before_create',
    label: 'Before entity is created (validation)',
    workflow_type: 'process',
    entity_types: ['table'],
    is_advanced: false,
    group: 'validation_gates',
  },
  {
    value: 'on_request_access',
    label: 'After an access request is submitted',
    workflow_type: 'process',
    entity_types: ['access_grant'],
    is_advanced: false,
    group: 'request_flow',
  },
  {
    value: 'scheduled',
    label: 'On a schedule (cron)',
    workflow_type: 'process',
    entity_types: [],
    is_advanced: false,
    group: 'system_scheduled',
  },
  {
    value: 'for_subscribe',
    label: 'When a user subscribes (wizard)',
    workflow_type: 'approval',
    entity_types: ['data_product'],
    is_advanced: false,
    group: 'request_flow',
  },
  {
    value: 'for_request_access',
    label: 'When a user requests access (wizard)',
    workflow_type: 'approval',
    entity_types: ['access_grant'],
    is_advanced: false,
    group: 'request_flow',
  },
  {
    value: 'for_approval_response',
    label: 'Approval response dialog (advanced)',
    workflow_type: 'approval',
    entity_types: [],
    is_advanced: true,
    group: 'request_flow',
  },
];

describe('partitionTriggers', () => {
  it('hides approval entries when authoring a process workflow', () => {
    const buckets = partitionTriggers(CATALOG, {
      workflowType: 'process',
      showAdvanced: false,
    });
    const allValues = buckets.flatMap((b) => b.items.map((i) => i.value));
    for (const v of allValues) {
      const entry = CATALOG.find((c) => c.value === v)!;
      expect(entry.workflow_type).toBe('process');
    }
    // None of the for_* entries should appear
    expect(allValues).not.toContain('for_subscribe');
    expect(allValues).not.toContain('for_request_access');
  });

  it('hides process entries when authoring an approval workflow', () => {
    const buckets = partitionTriggers(CATALOG, {
      workflowType: 'approval',
      showAdvanced: false,
    });
    const allValues = buckets.flatMap((b) => b.items.map((i) => i.value));
    for (const v of allValues) {
      const entry = CATALOG.find((c) => c.value === v)!;
      expect(entry.workflow_type).toBe('approval');
    }
    expect(allValues).not.toContain('on_create');
  });

  it('hides advanced triggers by default', () => {
    const buckets = partitionTriggers(CATALOG, {
      workflowType: 'approval',
      showAdvanced: false,
    });
    const allValues = buckets.flatMap((b) => b.items.map((i) => i.value));
    expect(allValues).not.toContain('for_approval_response');
  });

  it('reveals advanced triggers when toggle is on', () => {
    const buckets = partitionTriggers(CATALOG, {
      workflowType: 'approval',
      showAdvanced: true,
    });
    const allValues = buckets.flatMap((b) => b.items.map((i) => i.value));
    expect(allValues).toContain('for_approval_response');
  });

  it('produces groups in the canonical order', () => {
    const buckets = partitionTriggers(CATALOG, {
      workflowType: 'process',
      showAdvanced: false,
    });
    const groupOrder = buckets.map((b) => b.group);
    // Process catalog above has lifecycle + validation_gates + request_flow + system_scheduled
    expect(groupOrder).toEqual([
      'lifecycle',
      'request_flow',
      'validation_gates',
      'system_scheduled',
    ]);
  });

  it('omits groups that have no visible items', () => {
    // Approval catalog has nothing in lifecycle / validation_gates / system_scheduled
    const buckets = partitionTriggers(CATALOG, {
      workflowType: 'approval',
      showAdvanced: false,
    });
    expect(buckets).toHaveLength(1);
    expect(buckets[0].group).toBe('request_flow');
    expect(buckets[0].label).toBe(TRIGGER_GROUP_LABELS.request_flow);
  });

  it('renders user-friendly group labels', () => {
    expect(TRIGGER_GROUP_LABELS.lifecycle).toBe('Lifecycle events');
    expect(TRIGGER_GROUP_LABELS.request_flow).toBe('Request flow');
    expect(TRIGGER_GROUP_LABELS.validation_gates).toBe('Validation gates');
    expect(TRIGGER_GROUP_LABELS.system_scheduled).toBe('System & scheduled');
  });
});
