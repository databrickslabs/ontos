/**
 * EntityTypeMultiselect — companion to <TriggerPicker>.
 *
 * Renders the entity types the chosen trigger CAN fire for (from the
 * trigger-types endpoint), as a Shadcn-style checkbox-multiselect. Selected
 * values get persisted into `workflow.trigger.entity_types`, which the
 * backend uses to scope dispatch (see ProcessWorkflowRepository.get_for_trigger).
 *
 * Today the trigger.entity_types field is invisible in the UI — workflows
 * end up with `[]` (= "fires for everything") by accident. Surfacing this
 * picker forces the author to make the scope choice deliberately.
 *
 * Design choices:
 *  - If the trigger supports exactly one entity type, we pre-select it but
 *    still show the (single, checked) row so the choice is visible.
 *  - If the trigger has NO supported entity types (e.g. scheduled,
 *    for_approval_response), we render a muted placeholder explaining it
 *    fires regardless of entity type — no checkboxes.
 *  - Selecting zero options is allowed, since the backend treats `[]` as
 *    "any entity" (back-compat with existing rows).
 *  - The wire format stays snake_case (`access_grant`, `data_product`, …)
 *    so we don't break round-trips. `prettyEntityTypeLabel` only affects
 *    what the user sees in the checkbox rows.
 */
import { useEffect } from 'react';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';

/**
 * Display overrides for entity-type wire values. The default rule is
 * snake_case → Sentence case, but some wire values read as internal
 * jargon when surfaced to authors. Add entries here to override on a
 * case-by-case basis without touching the wire format itself.
 *
 *   access_grant → "Data object"
 *     (Reads naturally next to "When a user requests access — Applies to: …")
 *
 * Order matters: overrides win over the snake_case fallback.
 */
const PRETTY_ENTITY_TYPE_OVERRIDES: Record<string, string> = {
  access_grant: 'Data object',
};

/**
 * Convert a snake_case entity-type wire value to Sentence case for display.
 *
 *   "access_grant"       → "Data object"       (override)
 *   "data_product"       → "Data product"
 *   "data_asset_review"  → "Data asset review"
 *   "role"               → "Role"
 *   ""                   → ""
 *
 * Pure / side-effect free / exported for tests. Display only — callers
 * must keep using the raw `value` for any wire-format work (FK lookups,
 * persisted state, etc.).
 */
export function prettyEntityTypeLabel(value: string): string {
  if (!value) return value;
  if (PRETTY_ENTITY_TYPE_OVERRIDES[value]) return PRETTY_ENTITY_TYPE_OVERRIDES[value];
  const spaced = value.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Field-label constants for the entity-type multiselect. Exported so
 * the parent form and tests can reference the same source of truth. */
export const ENTITY_TYPE_MULTISELECT_LABEL = 'Applies to';
export const ENTITY_TYPE_MULTISELECT_HELPER = 'Which kinds of objects this fires on';

export interface EntityTypeMultiselectProps {
  /** The currently-selected trigger value (for context only). */
  triggerType: string;
  /** Currently persisted entity_types on the workflow trigger. */
  value: string[];
  /** Called when the selection changes. Pass the full new array. */
  onChange: (next: string[]) => void;
  /**
   * The entity types this trigger CAN fire for, from
   * GET /api/workflows/trigger-types. Empty list ⇒ "any entity".
   */
  supportedEntityTypes: string[];
}

export function EntityTypeMultiselect({
  triggerType,
  value,
  onChange,
  supportedEntityTypes,
}: EntityTypeMultiselectProps) {
  // Auto-default: if there is exactly one supported entity type and the
  // user hasn't picked anything, prefill it. Keeps the picker visible so
  // the choice is auditable, but spares the user a redundant click.
  useEffect(() => {
    if (supportedEntityTypes.length === 1 && value.length === 0) {
      onChange([supportedEntityTypes[0]]);
    }
    // Intentionally only react to trigger changes — re-prefilling on every
    // render would steal the user's "I really mean none" choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggerType, supportedEntityTypes.join('|')]);

  if (supportedEntityTypes.length === 0) {
    return (
      <div className="space-y-1">
        <Label>{ENTITY_TYPE_MULTISELECT_LABEL}</Label>
        <p className="text-xs text-muted-foreground">
          This trigger fires regardless of entity type.
        </p>
      </div>
    );
  }

  const toggle = (et: string) => {
    if (value.includes(et)) {
      onChange(value.filter((v) => v !== et));
    } else {
      onChange([...value, et]);
    }
  };

  return (
    <div className="space-y-1">
      <Label>{ENTITY_TYPE_MULTISELECT_LABEL}</Label>
      <p className="text-xs text-muted-foreground">
        {ENTITY_TYPE_MULTISELECT_HELPER}
      </p>
      <div className="flex flex-col gap-1 rounded-md border p-2">
        {supportedEntityTypes.map((et) => {
          const id = `entity-type-${et}`;
          const checked = value.includes(et);
          return (
            <div key={et} className="flex items-center gap-2">
              <Checkbox
                id={id}
                checked={checked}
                onCheckedChange={() => toggle(et)}
              />
              <Label htmlFor={id} className="text-sm font-normal cursor-pointer">
                {prettyEntityTypeLabel(et)}
              </Label>
            </div>
          );
        })}
      </div>
    </div>
  );
}
