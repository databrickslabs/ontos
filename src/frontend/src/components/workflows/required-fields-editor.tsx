/**
 * Required Fields Editor
 *
 * In-UI editor for the `required_fields` array on `user_action` workflow steps.
 *
 * Closes the gap where authors previously had to drop to YAML / API to add
 * custom fields. Renders inside the existing Step Configuration dialog as a
 * single collapsible "Custom fields" panel.
 *
 * Field shape is intentionally identical to what the approval wizard renderer
 * (approval-wizard-dialog.tsx) consumes:
 *   {
 *     id: string;            // slug-cased, unique within the step
 *     label: string;
 *     type: 'text' | 'select';
 *     required?: boolean;
 *     options?: Array<{ value: string; label: string }>;  // when type === 'select'
 *     options_endpoint?: string;                          // when type === 'select'
 *   }
 *
 * Round-trips YAML-authored fields cleanly: unmodified entries are kept
 * byte-identical (we only touch keys the user edits).
 *
 * Props in, props out — parent owns state.
 */
import { useMemo } from 'react';
import { Plus, Trash2, ChevronDown, ChevronRight } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';

// ─── Types ──────────────────────────────────────────────────────────────────

export type RequiredFieldType = 'text' | 'select';

export interface RequiredFieldOption {
  value: string;
  label: string;
}

export interface RequiredField {
  id: string;
  label: string;
  type: RequiredFieldType;
  required?: boolean;
  /** Static options (mutually exclusive with options_endpoint) */
  options?: RequiredFieldOption[];
  /** Dynamic options endpoint (mutually exclusive with options) */
  options_endpoint?: string;
  /** Pass-through for any extra keys we don't manage in the UI (preserves YAML round-trip). */
  [k: string]: unknown;
}

export interface RequiredFieldsEditorProps {
  value: RequiredField[];
  onChange: (next: RequiredField[]) => void;
  /** Optional id-prefix to scope DOM ids when rendered multiple times in one page. */
  idPrefix?: string;
  /** Initial collapsed state. Defaults to expanded if any fields exist, otherwise collapsed. */
  defaultOpen?: boolean;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const SLUG_RE = /^[a-z][a-z0-9_]*$/;

export function isValidSlug(id: string): boolean {
  return SLUG_RE.test(id);
}

/** Pure: compute which field ids are duplicated within the list. */
export function duplicateIds(fields: RequiredField[]): Set<string> {
  const seen = new Map<string, number>();
  for (const f of fields) {
    if (!f.id) continue;
    seen.set(f.id, (seen.get(f.id) ?? 0) + 1);
  }
  const dupes = new Set<string>();
  for (const [id, count] of seen) {
    if (count > 1) dupes.add(id);
  }
  return dupes;
}

/** Suggest an unused field id like `field_1`, `field_2`, ... */
function suggestNewId(existing: RequiredField[]): string {
  const taken = new Set(existing.map((f) => f.id));
  let i = existing.length + 1;
  while (taken.has(`field_${i}`)) i += 1;
  return `field_${i}`;
}

/**
 * Apply a mode switch on a select field. Pure — exposed for unit tests.
 *
 * The contract is "exactly one of `options` / `options_endpoint` is present"
 * — i.e. switching modes deletes the other side so the persisted shape is
 * never ambiguous when the wizard renderer reads it back.
 */
export function applyOptionsModeChange(
  field: RequiredField,
  mode: 'static' | 'endpoint',
): RequiredField {
  if (field.type !== 'select') return field;
  const next: RequiredField = { ...field };
  if (mode === 'static') {
    delete next.options_endpoint;
    if (!Array.isArray(next.options)) {
      next.options = [];
    }
  } else {
    delete next.options;
    if (typeof next.options_endpoint !== 'string') {
      next.options_endpoint = '';
    }
  }
  return next;
}

/**
 * Detect which "options mode" a select field is in.
 * - 'static'  → user is using inline options
 * - 'endpoint' → user is using options_endpoint
 *
 * Default: 'static' (matches the more common authoring pattern).
 */
function getOptionsMode(field: RequiredField): 'static' | 'endpoint' {
  if (typeof field.options_endpoint === 'string' && field.options_endpoint.length > 0) {
    return 'endpoint';
  }
  if (Array.isArray(field.options)) {
    return 'static';
  }
  return 'static';
}

// ─── Component ──────────────────────────────────────────────────────────────

export default function RequiredFieldsEditor({
  value,
  onChange,
  idPrefix = 'rfe',
  defaultOpen,
}: RequiredFieldsEditorProps) {
  const fields = value ?? [];
  const dupes = useMemo(() => duplicateIds(fields), [fields]);
  const initiallyOpen = defaultOpen ?? fields.length > 0;

  // ── Mutation helpers ──────────────────────────────────────────────────────

  const updateField = (index: number, patch: Partial<RequiredField>) => {
    const next = fields.map((f, i) => (i === index ? { ...f, ...patch } : f));
    onChange(next);
  };

  const removeField = (index: number) => {
    onChange(fields.filter((_, i) => i !== index));
  };

  const addField = () => {
    const newField: RequiredField = {
      id: suggestNewId(fields),
      label: '',
      type: 'text',
      required: false,
    };
    onChange([...fields, newField]);
  };

  // Change type and clean up type-specific keys so we don't leak `options`
  // onto a `text` field after the author toggles back.
  const changeFieldType = (index: number, nextType: RequiredFieldType) => {
    const current = fields[index];
    if (current.type === nextType) return;
    const cleaned: RequiredField = {
      ...current,
      type: nextType,
    };
    if (nextType !== 'select') {
      delete cleaned.options;
      delete cleaned.options_endpoint;
    }
    const next = fields.map((f, i) => (i === index ? cleaned : f));
    onChange(next);
  };

  // Switch between static / endpoint modes for a select field. See
  // `applyOptionsModeChange` for the pure cleanup contract.
  const setOptionsMode = (index: number, mode: 'static' | 'endpoint') => {
    const current = fields[index];
    if (current.type !== 'select') return;
    const cleaned = applyOptionsModeChange(current, mode);
    const next = fields.map((f, i) => (i === index ? cleaned : f));
    onChange(next);
  };

  const updateOption = (
    fieldIndex: number,
    optIndex: number,
    patch: Partial<RequiredFieldOption>,
  ) => {
    const current = fields[fieldIndex];
    const opts = Array.isArray(current.options) ? current.options : [];
    const nextOpts = opts.map((o, i) => (i === optIndex ? { ...o, ...patch } : o));
    updateField(fieldIndex, { options: nextOpts });
  };

  const addOption = (fieldIndex: number) => {
    const current = fields[fieldIndex];
    const opts = Array.isArray(current.options) ? current.options : [];
    updateField(fieldIndex, { options: [...opts, { value: '', label: '' }] });
  };

  const removeOption = (fieldIndex: number, optIndex: number) => {
    const current = fields[fieldIndex];
    const opts = Array.isArray(current.options) ? current.options : [];
    updateField(fieldIndex, { options: opts.filter((_, i) => i !== optIndex) });
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Collapsible defaultOpen={initiallyOpen} className="border rounded-md">
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-muted/40 rounded-t-md group"
          data-testid={`${idPrefix}-toggle`}
        >
          <div className="flex items-center gap-2">
            <ChevronRight className="h-4 w-4 transition-transform group-data-[state=open]:rotate-90" />
            <span className="text-sm font-medium">Custom fields</span>
            <span className="text-xs text-muted-foreground">
              ({fields.length})
            </span>
          </div>
          <ChevronDown className="h-4 w-4 text-muted-foreground opacity-0 group-data-[state=open]:opacity-0" />
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent className="px-3 pb-3 pt-1 space-y-3">
        {fields.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No custom fields yet. Add fields the requester must fill in before submitting.
          </p>
        )}

        {fields.map((field, idx) => {
          const idInvalid = field.id !== '' && !isValidSlug(field.id);
          const idEmpty = field.id === '';
          const idDup = field.id !== '' && dupes.has(field.id);
          const idError = idEmpty
            ? 'ID is required.'
            : idInvalid
              ? 'ID must be lowercase letters, digits, or underscores, starting with a letter.'
              : idDup
                ? 'ID must be unique within this step.'
                : null;
          const rowTestId = `${idPrefix}-row-${idx}`;
          return (
            <div
              key={idx}
              data-testid={rowTestId}
              className="border rounded-md p-3 space-y-2 bg-muted/20"
            >
              {/* Top row: id / label / type / required / delete */}
              <div className="grid grid-cols-12 gap-2 items-end">
                <div className="col-span-3 space-y-1">
                  <Label htmlFor={`${idPrefix}-${idx}-id`} className="text-xs">
                    Field ID
                  </Label>
                  <Input
                    id={`${idPrefix}-${idx}-id`}
                    data-testid={`${rowTestId}-id`}
                    value={field.id}
                    onChange={(e) => updateField(idx, { id: e.target.value })}
                    placeholder="e.g. target_group"
                    className={idError ? 'border-destructive focus-visible:ring-destructive' : ''}
                    aria-invalid={idError != null}
                  />
                </div>
                <div className="col-span-4 space-y-1">
                  <Label htmlFor={`${idPrefix}-${idx}-label`} className="text-xs">
                    Label
                  </Label>
                  <Input
                    id={`${idPrefix}-${idx}-label`}
                    data-testid={`${rowTestId}-label`}
                    value={field.label}
                    onChange={(e) => updateField(idx, { label: e.target.value })}
                    placeholder="Shown to requester"
                  />
                </div>
                <div className="col-span-3 space-y-1">
                  <Label className="text-xs">Type</Label>
                  <Select
                    value={field.type}
                    onValueChange={(v) => changeFieldType(idx, v as RequiredFieldType)}
                  >
                    <SelectTrigger data-testid={`${rowTestId}-type`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="text">Text</SelectItem>
                      <SelectItem value="select">Select</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="col-span-1 flex flex-col items-center gap-1 pb-1">
                  <Label className="text-xs">Req.</Label>
                  <Switch
                    data-testid={`${rowTestId}-required`}
                    checked={!!field.required}
                    onCheckedChange={(checked) => updateField(idx, { required: checked })}
                  />
                </div>
                <div className="col-span-1 flex justify-end pb-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="Remove field"
                    data-testid={`${rowTestId}-delete`}
                    onClick={() => removeField(idx)}
                  >
                    <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                  </Button>
                </div>
              </div>

              {idError && (
                <p
                  className="text-xs text-destructive"
                  data-testid={`${rowTestId}-id-error`}
                >
                  {idError}
                </p>
              )}

              {/* Type-specific reveal: select-only options config */}
              {field.type === 'select' && (
                <div
                  className="mt-2 pl-2 border-l-2 border-muted-foreground/20 space-y-2"
                  data-testid={`${rowTestId}-select-config`}
                >
                  <RadioGroup
                    value={getOptionsMode(field)}
                    onValueChange={(v) => setOptionsMode(idx, v as 'static' | 'endpoint')}
                    className="flex flex-row gap-4"
                  >
                    <div className="flex items-center gap-2">
                      <RadioGroupItem
                        value="static"
                        id={`${idPrefix}-${idx}-mode-static`}
                        data-testid={`${rowTestId}-mode-static`}
                      />
                      <Label
                        htmlFor={`${idPrefix}-${idx}-mode-static`}
                        className="text-xs font-normal cursor-pointer"
                      >
                        Static options
                      </Label>
                    </div>
                    <div className="flex items-center gap-2">
                      <RadioGroupItem
                        value="endpoint"
                        id={`${idPrefix}-${idx}-mode-endpoint`}
                        data-testid={`${rowTestId}-mode-endpoint`}
                      />
                      <Label
                        htmlFor={`${idPrefix}-${idx}-mode-endpoint`}
                        className="text-xs font-normal cursor-pointer"
                      >
                        From endpoint
                      </Label>
                    </div>
                  </RadioGroup>

                  {getOptionsMode(field) === 'static' && (
                    <div
                      className="space-y-2"
                      data-testid={`${rowTestId}-static-options`}
                    >
                      {(field.options ?? []).map((opt, optIdx) => (
                        <div
                          key={optIdx}
                          className="grid grid-cols-12 gap-2 items-center"
                          data-testid={`${rowTestId}-option-${optIdx}`}
                        >
                          <Input
                            className="col-span-5"
                            placeholder="value"
                            data-testid={`${rowTestId}-option-${optIdx}-value`}
                            value={opt.value}
                            onChange={(e) =>
                              updateOption(idx, optIdx, { value: e.target.value })
                            }
                          />
                          <Input
                            className="col-span-6"
                            placeholder="label"
                            data-testid={`${rowTestId}-option-${optIdx}-label`}
                            value={opt.label}
                            onChange={(e) =>
                              updateOption(idx, optIdx, { label: e.target.value })
                            }
                          />
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="col-span-1"
                            aria-label="Remove option"
                            data-testid={`${rowTestId}-option-${optIdx}-delete`}
                            onClick={() => removeOption(idx, optIdx)}
                          >
                            <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" />
                          </Button>
                        </div>
                      ))}
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => addOption(idx)}
                        data-testid={`${rowTestId}-add-option`}
                      >
                        <Plus className="h-3 w-3 mr-1" /> Add option
                      </Button>
                    </div>
                  )}

                  {getOptionsMode(field) === 'endpoint' && (
                    <div className="space-y-1">
                      <Label
                        htmlFor={`${idPrefix}-${idx}-endpoint`}
                        className="text-xs"
                      >
                        Options endpoint
                      </Label>
                      <Input
                        id={`${idPrefix}-${idx}-endpoint`}
                        data-testid={`${rowTestId}-endpoint`}
                        placeholder="/api/workspace/groups"
                        value={field.options_endpoint ?? ''}
                        onChange={(e) =>
                          updateField(idx, { options_endpoint: e.target.value })
                        }
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Backend endpoint returning JSON{' '}
                        <code>{`{ options: [{ value, label }] }`}</code>.
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addField}
          data-testid={`${idPrefix}-add-field`}
        >
          <Plus className="h-4 w-4 mr-1" /> Add field
        </Button>
      </CollapsibleContent>
    </Collapsible>
  );
}
