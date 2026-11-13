import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, GripVertical, Loader2, Plus, Trash2 } from 'lucide-react';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useApi } from '@/hooks/use-api';
import { cn } from '@/lib/utils';
import {
  STAGE_COLORS,
  categoryLabel,
  lifecycleErrorText,
  orderedStages,
  stageColorClass,
  stageLabel,
} from '@/lib/lifecycle-stages';
import StageGraphPreview from '@/components/lifecycle/stage-graph-preview';
import {
  STAGE_CATEGORIES,
  type LifecycleEntityType,
  type LifecycleStage,
  type LifecycleStageGroup,
  type LifecycleStageGroupWrite,
  type LifecycleStageTransition,
  type StageCategory,
} from '@/types/lifecycle-stage-groups';

/** A stage row of the editor: `uid` is stable while the key is typed. */
export interface EditorStage extends LifecycleStage {
  uid: string;
  /** Stored already: its key is immutable (entities store it in `status`). */
  persisted: boolean;
  /** The key follows the label until it is edited by hand. */
  keyTouched: boolean;
}

export interface EditorState {
  name: string;
  description: string;
  isDefault: boolean;
  stages: EditorStage[];
  /** `${from_uid}>${to_uid}` */
  transitions: Set<string>;
}

let uidCounter = 0;
const nextUid = () => `s${++uidCounter}`;

/** A stage key from a label: lowercase letters, digits and underscores. */
export function slugKey(label: string): string {
  return label
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
}

/** The editor's state of a stored group, or of a new one (one draft and one active stage). */
export function initialEditorState(group: LifecycleStageGroup | null): EditorState {
  if (!group) {
    const draft: EditorStage = {
      uid: nextUid(), key: 'draft', label: 'Draft', category: 'draft', color: 'gray',
      order: 0, is_initial: true, persisted: false, keyTouched: false,
    };
    const active: EditorStage = {
      uid: nextUid(), key: 'active', label: 'Active', category: 'active', color: 'green',
      order: 1, is_initial: false, persisted: false, keyTouched: false,
    };
    return {
      name: '', description: '', isDefault: false, stages: [draft, active],
      transitions: new Set([`${draft.uid}>${active.uid}`]),
    };
  }
  const stages = orderedStages(group).map((s) => ({
    ...s, uid: nextUid(), persisted: Boolean(group.id), keyTouched: true,
  }));
  const uidOf = new Map(stages.map((s) => [s.key, s.uid]));
  const transitions = new Set(
    group.transitions
      .filter((t) => uidOf.has(t.from_key) && uidOf.has(t.to_key))
      .map((t) => `${uidOf.get(t.from_key)}>${uidOf.get(t.to_key)}`),
  );
  return {
    name: group.name, description: group.description ?? '',
    isDefault: group.is_default_for_type, stages, transitions,
  };
}

/** The save body of the editor's state: stages in table order, transitions by key. */
export function toWrite(
  state: EditorState, entityType: LifecycleEntityType,
): LifecycleStageGroupWrite {
  const keyOf = new Map(state.stages.map((s) => [s.uid, s.key]));
  const transitions: LifecycleStageTransition[] = [];
  for (const pair of state.transitions) {
    const [from, to] = pair.split('>');
    if (keyOf.has(from) && keyOf.has(to)) {
      transitions.push({ from_key: keyOf.get(from)!, to_key: keyOf.get(to)! });
    }
  }
  return {
    name: state.name.trim(),
    description: state.description.trim() || null,
    entity_type: entityType,
    is_default_for_type: state.isDefault,
    stages: state.stages.map((s, order) => ({
      key: s.key, label: s.label.trim(), category: s.category, color: s.color,
      order, is_initial: s.is_initial,
    })),
    transitions,
  };
}

/** The stage keys an API error names (to mark their rows). */
export function keysOfError(params: Record<string, unknown> | null | undefined): Set<string> {
  const out = new Set<string>();
  if (!params) return out;
  for (const name of ['key', 'fromKey', 'toKey']) {
    if (typeof params[name] === 'string') out.add(params[name] as string);
  }
  if (Array.isArray(params.stages)) params.stages.forEach((k) => out.add(String(k)));
  return out;
}

interface StageRowProps {
  stage: EditorStage;
  index: number;
  count: number;
  invalid: boolean;
  disabled: boolean;
  onChange: (patch: Partial<EditorStage>) => void;
  onMove: (to: number) => void;
  onRemove: () => void;
}

function StageRow({
  stage, index, count, invalid, disabled, onChange, onMove, onRemove,
}: StageRowProps) {
  const { t } = useTranslation(['lifecycle', 'common']);
  const sortable = useSortable({ id: stage.uid, disabled });
  const style = {
    transform: CSS.Transform.toString(sortable.transform),
    transition: sortable.transition,
  };
  const label = stage.label || stage.key;
  return (
    <tr
      ref={sortable.setNodeRef}
      style={style}
      className={cn('border-b align-middle', invalid && 'bg-destructive/10')}
      data-testid={`stage-row-${stage.key}`}
      aria-invalid={invalid || undefined}
    >
      <td className="px-1 py-1 w-16">
        <div className="flex items-center">
          <button
            type="button"
            className="cursor-grab text-muted-foreground p-1 disabled:opacity-30"
            aria-label={t('lifecycle:editor.dragStage', { stage: label })}
            disabled={disabled}
            {...sortable.attributes}
            {...sortable.listeners}
          >
            <GripVertical className="h-4 w-4" />
          </button>
          <div className="flex flex-col">
            <button
              type="button"
              className="text-muted-foreground disabled:opacity-20"
              onClick={() => onMove(index - 1)}
              disabled={disabled || index === 0}
              aria-label={t('lifecycle:editor.moveUp', { stage: label })}
            >
              <ArrowUp className="h-3 w-3" />
            </button>
            <button
              type="button"
              className="text-muted-foreground disabled:opacity-20"
              onClick={() => onMove(index + 1)}
              disabled={disabled || index === count - 1}
              aria-label={t('lifecycle:editor.moveDown', { stage: label })}
            >
              <ArrowDown className="h-3 w-3" />
            </button>
          </div>
        </div>
      </td>
      <td className="px-1 py-1">
        <Input
          value={stage.label}
          onChange={(e) => {
            const value = e.target.value;
            onChange(stage.keyTouched || stage.persisted
              ? { label: value }
              : { label: value, key: slugKey(value) });
          }}
          aria-label={t('lifecycle:editor.stageLabel', { index: index + 1 })}
          disabled={disabled}
          className="h-8"
        />
      </td>
      <td className="px-1 py-1">
        <Input
          value={stage.key}
          onChange={(e) => onChange({ key: e.target.value, keyTouched: true })}
          aria-label={t('lifecycle:editor.stageKey', { index: index + 1 })}
          title={stage.persisted ? t('lifecycle:editor.keyImmutable') : undefined}
          disabled={disabled || stage.persisted}
          className="h-8 font-mono text-xs"
        />
      </td>
      <td className="px-1 py-1 w-36">
        <Select
          value={stage.category}
          onValueChange={(v) => onChange({ category: v as StageCategory })}
          disabled={disabled}
        >
          <SelectTrigger
            className="h-8"
            aria-label={t('lifecycle:editor.stageCategory', { index: index + 1 })}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STAGE_CATEGORIES.map((c) => (
              <SelectItem key={c} value={c}>{categoryLabel(c, t)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
      <td className="px-1 py-1 w-32">
        <Select
          value={stage.color ?? 'gray'}
          onValueChange={(v) => onChange({ color: v })}
          disabled={disabled}
        >
          <SelectTrigger
            className="h-8"
            aria-label={t('lifecycle:editor.stageColor', { index: index + 1 })}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.keys(STAGE_COLORS).map((c) => (
              <SelectItem key={c} value={c}>
                <span className={cn('rounded px-1.5 text-xs', STAGE_COLORS[c])}>
                  {t(`lifecycle:color.${c}`, { defaultValue: c })}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
      <td className="px-1 py-1 text-center w-16">
        <RadioGroupItem
          value={stage.uid}
          aria-label={t('lifecycle:editor.firstStage', { stage: label })}
          disabled={disabled}
        />
      </td>
      <td className="px-1 py-1 w-10">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-destructive"
          onClick={onRemove}
          disabled={disabled || count <= 1}
          aria-label={t('lifecycle:editor.removeStage', { stage: label })}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </td>
    </tr>
  );
}

interface TransitionMatrixProps {
  stages: EditorStage[];
  transitions: Set<string>;
  disabled: boolean;
  onToggle: (pair: string) => void;
}

/** From (rows) x to (columns): a checked cell is an allowed move. */
export function TransitionMatrix(
  { stages, transitions, disabled, onToggle }: TransitionMatrixProps,
) {
  const { t } = useTranslation(['lifecycle']);
  const name = (s: EditorStage) => (s.label ? stageLabel(s, t) : s.key);
  return (
    <div className="overflow-x-auto">
      <table className="text-xs" aria-label={t('lifecycle:editor.matrix')}>
        <thead>
          <tr>
            <th className="px-2 py-1 text-left text-muted-foreground">
              {t('lifecycle:editor.fromTo')}
            </th>
            {stages.map((s) => (
              <th key={s.uid} scope="col" className="px-2 py-1 font-medium">{name(s)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stages.map((from) => (
            <tr key={from.uid}>
              <th scope="row" className="px-2 py-1 text-left font-medium">{name(from)}</th>
              {stages.map((to) => {
                const pair = `${from.uid}>${to.uid}`;
                return (
                  <td key={to.uid} className="px-2 py-1 text-center">
                    {from.uid === to.uid ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <Checkbox
                        checked={transitions.has(pair)}
                        onCheckedChange={() => onToggle(pair)}
                        disabled={disabled}
                        aria-label={t('lifecycle:editor.allowMove', {
                          from: name(from), to: name(to),
                        })}
                      />
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface LifecycleStageGroupEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: LifecycleEntityType;
  /** The group to edit; null creates one. */
  group: LifecycleStageGroup | null;
  readOnly?: boolean;
  onSaved: (group: LifecycleStageGroup) => void;
}

/**
 * Create or edit a Lifecycle Stage Group: name, default, the ordered stage
 * table (drag or arrows to reorder), the transition matrix and a graph
 * preview. The backend validates the save; its coded error is shown inline
 * and the stages it names are marked.
 */
export default function LifecycleStageGroupEditor({
  open, onOpenChange, entityType, group, readOnly = false, onSaved,
}: LifecycleStageGroupEditorProps) {
  const { t } = useTranslation(['lifecycle', 'common']);
  const { post, put } = useApi();
  const [state, setState] = useState<EditorState>(() => initialEditorState(group));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invalidKeys, setInvalidKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (open) {
      setState(initialEditorState(group));
      setError(null);
      setInvalidKeys(new Set());
    }
  }, [open, group]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const initialUid = state.stages.find((s) => s.is_initial)?.uid ?? '';
  // Stored default: it stays the default until another group takes over
  const defaultLocked = Boolean(group?.is_default_for_type);

  const patchStage = (uid: string, patch: Partial<EditorStage>) =>
    setState((s) => ({
      ...s, stages: s.stages.map((st) => (st.uid === uid ? { ...st, ...patch } : st)),
    }));

  const moveStage = (from: number, to: number) =>
    setState((s) => (to < 0 || to >= s.stages.length
      ? s
      : { ...s, stages: arrayMove(s.stages, from, to) }));

  const removeStage = (uid: string) =>
    setState((s) => {
      let stages = s.stages.filter((st) => st.uid !== uid);
      if (stages.length && !stages.some((st) => st.is_initial)) {
        stages = stages.map((st, i) => ({ ...st, is_initial: i === 0 }));
      }
      const transitions = new Set(
        [...s.transitions].filter((p) => !p.split('>').includes(uid)),
      );
      return { ...s, stages, transitions };
    });

  const addStage = () =>
    setState((s) => ({
      ...s,
      stages: [...s.stages, {
        uid: nextUid(), key: '', label: '', category: 'review', color: 'blue',
        order: s.stages.length, is_initial: false, persisted: false, keyTouched: false,
      }],
    }));

  const toggle = (pair: string) =>
    setState((s) => {
      const transitions = new Set(s.transitions);
      if (transitions.has(pair)) transitions.delete(pair);
      else transitions.add(pair);
      return { ...s, transitions };
    });

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = state.stages.findIndex((s) => s.uid === active.id);
    const to = state.stages.findIndex((s) => s.uid === over.id);
    moveStage(from, to);
  };

  const write = useMemo(() => toWrite(state, entityType), [state, entityType]);
  const canSave = !readOnly && !saving && write.name.length > 0
    && write.stages.every((s) => s.key && s.label);

  const save = async () => {
    setSaving(true);
    setError(null);
    setInvalidKeys(new Set());
    const response = group?.id
      ? await put<LifecycleStageGroup>(`/api/lifecycle-stage-groups/${group.id}`, write)
      : await post<LifecycleStageGroup>('/api/lifecycle-stage-groups', write);
    setSaving(false);
    if (response.error) {
      setError(lifecycleErrorText(response, t));
      setInvalidKeys(keysOfError(response.errorParams));
      return;
    }
    onSaved(response.data);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {group?.id ? t('lifecycle:editor.editTitle') : t('lifecycle:editor.createTitle')}
          </DialogTitle>
          <DialogDescription>{t('lifecycle:editor.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="lifecycle-group-name">{t('lifecycle:editor.name')}</Label>
              <Input
                id="lifecycle-group-name"
                value={state.name}
                onChange={(e) => setState((s) => ({ ...s, name: e.target.value }))}
                disabled={readOnly}
              />
            </div>
            <div className="flex items-end gap-2 pb-2">
              <Switch
                id="lifecycle-group-default"
                checked={state.isDefault}
                onCheckedChange={(v) => setState((s) => ({ ...s, isDefault: v }))}
                disabled={readOnly || defaultLocked}
              />
              <Label htmlFor="lifecycle-group-default">
                {t('lifecycle:editor.isDefault', {
                  entityType: t(`lifecycle:entityType.${entityType}`),
                })}
              </Label>
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="lifecycle-group-description">
              {t('lifecycle:editor.groupDescription')}
            </Label>
            <Textarea
              id="lifecycle-group-description"
              rows={2}
              value={state.description}
              onChange={(e) => setState((s) => ({ ...s, description: e.target.value }))}
              disabled={readOnly}
            />
          </div>

          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">{t('lifecycle:editor.stages')}</h3>
              <Button type="button" size="sm" variant="outline" onClick={addStage}
                disabled={readOnly}>
                <Plus className="h-4 w-4 mr-1" /> {t('lifecycle:editor.addStage')}
              </Button>
            </div>
            <DndContext
              sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}
            >
              <RadioGroup
                value={initialUid}
                onValueChange={(uid) => setState((s) => ({
                  ...s, stages: s.stages.map((st) => ({ ...st, is_initial: st.uid === uid })),
                }))}
                className="block"
                aria-label={t('lifecycle:editor.first')}
              >
                <table className="w-full text-sm" aria-label={t('lifecycle:editor.stages')}>
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      <th className="px-1 py-1" />
                      <th className="px-1 py-1">{t('lifecycle:editor.label')}</th>
                      <th className="px-1 py-1">{t('lifecycle:editor.key')}</th>
                      <th className="px-1 py-1">{t('lifecycle:editor.category')}</th>
                      <th className="px-1 py-1">{t('lifecycle:editor.color')}</th>
                      <th className="px-1 py-1 text-center">{t('lifecycle:editor.first')}</th>
                      <th className="px-1 py-1" />
                    </tr>
                  </thead>
                  <SortableContext
                    items={state.stages.map((s) => s.uid)}
                    strategy={verticalListSortingStrategy}
                  >
                    <tbody>
                      {state.stages.map((stage, index) => (
                        <StageRow
                          key={stage.uid}
                          stage={stage}
                          index={index}
                          count={state.stages.length}
                          invalid={invalidKeys.has(stage.key)}
                          disabled={readOnly}
                          onChange={(patch) => patchStage(stage.uid, patch)}
                          onMove={(to) => moveStage(index, to)}
                          onRemove={() => removeStage(stage.uid)}
                        />
                      ))}
                    </tbody>
                  </SortableContext>
                </table>
              </RadioGroup>
            </DndContext>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('lifecycle:editor.transitions')}</h3>
            <p className="text-xs text-muted-foreground">{t('lifecycle:editor.matrixHint')}</p>
            <TransitionMatrix
              stages={state.stages}
              transitions={state.transitions}
              disabled={readOnly}
              onToggle={toggle}
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('lifecycle:editor.preview')}</h3>
            <StageGraphPreview stages={write.stages} transitions={write.transitions} />
            <div className="flex flex-wrap gap-1">
              {write.stages.map((s) => (
                <span key={s.key || s.order}
                  className={cn('rounded border px-1.5 text-xs', stageColorClass(s))}>
                  {s.label || s.key} · {categoryLabel(s.category, t)}
                </span>
              ))}
            </div>
          </section>

          {error && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:actions.cancel')}
          </Button>
          {!readOnly && (
            <Button onClick={save} disabled={!canSave}>
              {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              {t('common:actions.save')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
