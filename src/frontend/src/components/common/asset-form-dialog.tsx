import { useState, useEffect, useCallback, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage, FormDescription,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Separator } from '@/components/ui/separator';
import DomainMultiSelector from '@/components/ui/domain-multi-selector';
import { AssetRead, AssetCreate, AssetUpdate } from '@/types/asset';
import { EntityFieldDefinition, EntityTypeSchema } from '@/types/ontology-schema';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useFormatLabel } from '@/lib/format-label';

interface AssetFormDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (asset: AssetRead) => void;
  assetTypeId: string;
  assetTypeName: string;
  /** IRI for the ontology type, e.g. "http://ontos.app/ontology#Dataset" */
  assetTypeIri?: string | null;
  /** Existing asset for edit mode */
  asset?: AssetRead | null;
}

const GROUP_LABELS: Record<string, string> = {
  basic: 'Basic Information',
  governance: 'Governance',
  technical: 'Technical Details',
  security: 'Security',
};

function groupAndSortFields(fields: EntityFieldDefinition[]): [string, EntityFieldDefinition[]][] {
  const groups: Record<string, EntityFieldDefinition[]> = {};
  for (const f of fields) {
    const g = f.field_group || 'basic';
    if (!groups[g]) groups[g] = [];
    groups[g].push(f);
  }
  for (const g of Object.values(groups)) {
    g.sort((a, b) => a.field_order - b.field_order);
  }
  const groupOrder = ['basic', 'governance', 'technical', 'security'];
  return Object.entries(groups).sort(([a], [b]) => {
    const ai = groupOrder.indexOf(a);
    const bi = groupOrder.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
}

/** Fields handled by top-level AssetCreate/AssetUpdate (not stored in properties) */
const TOP_LEVEL_FIELDS = new Set(['name', 'description', 'status', 'version']);

/** System-managed fields that are not user-editable in create/edit forms */
const SYSTEM_FIELDS = new Set([
  'entityId', 'createdAt', 'createdBy', 'updatedAt', 'updatedBy',
  'publishedAt', 'publishedBy', 'certifiedAt', 'certifiedBy',
  'certificationExpiresAt', 'promotedAt', 'promotedBy', 'promotionType',
  'lifecycle', 'sourceConceptIri', 'sourceCollectionIri', 'reviewRequestId',
  'physicalName', 'displayTitle',
]);

export function AssetFormDialog({
  isOpen, onOpenChange, onSuccess,
  assetTypeId, assetTypeName, assetTypeIri, asset,
}: AssetFormDialogProps) {
  const [schema, setSchema] = useState<EntityTypeSchema | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { get: apiGet, post: apiPost, put: apiPut } = useApi();
  const { toast } = useToast();
  const { i18n } = useTranslation();
  const isEdit = !!asset;

  const form = useForm<Record<string, any>>({
    defaultValues: {},
  });

  const fetchSchema = useCallback(async () => {
    if (!assetTypeIri) return;
    setSchemaLoading(true);
    try {
      const response = await apiGet<EntityTypeSchema>(
        `/api/ontology/entity-types/schema?type_iri=${encodeURIComponent(assetTypeIri)}&lang=${encodeURIComponent(i18n.language)}`
      );
      if (response.error) throw new Error(response.error);
      setSchema(response.data ?? null);
    } catch {
      setSchema(null);
    } finally {
      setSchemaLoading(false);
    }
  }, [assetTypeIri, apiGet, i18n.language]);

  useEffect(() => {
    if (isOpen && assetTypeIri) {
      fetchSchema();
    }
  }, [isOpen, assetTypeIri, fetchSchema]);

  useEffect(() => {
    if (!isOpen) return;
    const defaults: Record<string, any> = {};
    if (isEdit && asset) {
      defaults.name = asset.name || '';
      defaults.description = asset.description || '';
      defaults.status = asset.status || 'draft';
      defaults.platform = asset.platform || '';
      defaults.location = asset.location || '';
      defaults.domain_ids = (asset.domains && asset.domains.length > 0)
        ? asset.domains.map(d => d.domain_id)
        : (asset.domain_id ? [asset.domain_id] : []);
      defaults.primary_domain_id = asset.primary_domain_id
        ?? asset.domains?.find(d => d.is_primary)?.domain_id
        ?? asset.domain_id ?? null;
      const props = asset.properties || {};
      if (schema?.fields) {
        for (const f of schema.fields) {
          if (TOP_LEVEL_FIELDS.has(f.name) || SYSTEM_FIELDS.has(f.name)) continue;
          defaults[`prop_${f.name}`] = props[f.name] ?? (f.field_type === 'boolean' ? false : '');
        }
      }
    } else {
      defaults.name = '';
      defaults.description = '';
      defaults.status = 'draft';
      defaults.platform = '';
      defaults.location = '';
      defaults.domain_ids = [];
      defaults.primary_domain_id = null;
      if (schema?.fields) {
        for (const f of schema.fields) {
          if (TOP_LEVEL_FIELDS.has(f.name) || SYSTEM_FIELDS.has(f.name)) continue;
          defaults[`prop_${f.name}`] = f.field_type === 'boolean' ? false : '';
        }
      }
    }
    form.reset(defaults);
  }, [isOpen, schema, isEdit, asset]);

  const groupedFields = useMemo(() => {
    if (!schema?.fields) return [];
    const propertyFields = schema.fields.filter(
      f => !TOP_LEVEL_FIELDS.has(f.name) && !SYSTEM_FIELDS.has(f.name)
    );
    return groupAndSortFields(propertyFields);
  }, [schema]);

  const onSubmit = async (values: Record<string, any>) => {
    setIsSubmitting(true);
    try {
      const properties: Record<string, any> = {};
      for (const [key, val] of Object.entries(values)) {
        if (key.startsWith('prop_')) {
          const propName = key.slice(5);
          if (val !== '' && val !== null && val !== undefined) {
            properties[propName] = val;
          }
        }
      }

      if (isEdit && asset) {
        const payload: AssetUpdate = {
          name: values.name || null,
          description: values.description || null,
          status: values.status || null,
          platform: values.platform || null,
          location: values.location || null,
          domain_ids: values.domain_ids || [],
          primary_domain_id: values.primary_domain_id ?? null,
          properties: Object.keys(properties).length > 0 ? properties : null,
        };
        const response = await apiPut<AssetRead>(`/api/assets/${asset.id}`, payload);
        if (response.error) throw new Error(response.error);
        toast({ title: `${assetTypeName} updated` });
        onSuccess(response.data!);
      } else {
        const payload: AssetCreate = {
          name: values.name,
          description: values.description || null,
          asset_type_id: assetTypeId,
          status: values.status || 'draft',
          platform: values.platform || null,
          location: values.location || null,
          domain_ids: values.domain_ids || [],
          primary_domain_id: values.primary_domain_id ?? null,
          properties: Object.keys(properties).length > 0 ? properties : null,
        };
        const response = await apiPost<AssetRead>('/api/assets', payload);
        if (response.error) throw new Error(response.error);
        toast({ title: `${assetTypeName} created` });
        onSuccess(response.data!);
      }
      onOpenChange(false);
    } catch (err: any) {
      toast({ variant: 'destructive', title: 'Error', description: err.message });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit' : 'Create'} {assetTypeName}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? `Update the properties of this ${assetTypeName.toLowerCase()}.`
              : `Create a new ${assetTypeName.toLowerCase()} asset.`}
          </DialogDescription>
        </DialogHeader>

        {schemaLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Loading schema…</span>
          </div>
        ) : (
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              {/* Core fields always shown */}
              <div className="space-y-4">
                <FormField
                  control={form.control}
                  name="name"
                  rules={{ required: 'Name is required', minLength: { value: 2, message: 'Min 2 characters' } }}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Name *</FormLabel>
                      <FormControl>
                        <Input placeholder={`Enter ${assetTypeName.toLowerCase()} name`} {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="description"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Description</FormLabel>
                      <FormControl>
                        <Textarea
                          placeholder="Optional description"
                          className="min-h-[80px]"
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="grid grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="status"
                    rules={{ required: 'Status is required' }}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Status *</FormLabel>
                        <Select onValueChange={field.onChange} value={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Select status" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="draft">Draft</SelectItem>
                            <SelectItem value="active">Active</SelectItem>
                            <SelectItem value="deprecated">Deprecated</SelectItem>
                            <SelectItem value="retired">Retired</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="platform"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Platform</FormLabel>
                        <FormControl>
                          <Input placeholder="e.g. databricks, snowflake" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
                <FormField
                  control={form.control}
                  name="location"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Location</FormLabel>
                      <FormControl>
                        <Input placeholder="e.g. catalog.schema.table" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="domain_ids"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Domains</FormLabel>
                      <FormControl>
                        <DomainMultiSelector
                          value={field.value || []}
                          primaryDomainId={form.watch('primary_domain_id')}
                          onChange={(domainIds, primaryDomainId) => {
                            field.onChange(domainIds);
                            form.setValue('primary_domain_id', primaryDomainId);
                          }}
                          placeholder="Select domains..."
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* Ontology-driven property fields, grouped */}
              {groupedFields.map(([group, fields]) => (
                <div key={group}>
                  <Separator className="my-4" />
                  <h4 className="text-sm font-semibold text-muted-foreground mb-3">
                    {GROUP_LABELS[group] || group.charAt(0).toUpperCase() + group.slice(1)}
                  </h4>
                  <div className="space-y-4">
                    {fields.map((f) => (
                      <DynamicFormField key={f.name} field={f} form={form} />
                    ))}
                  </div>
                </div>
              ))}

              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {isEdit ? 'Save Changes' : `Create ${assetTypeName}`}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DynamicFormField({ field: f, form }: { field: EntityFieldDefinition; form: any }) {
  const formatLabel = useFormatLabel();
  const fieldName = `prop_${f.name}`;
  const label = formatLabel(f.label);

  if (f.field_type === 'select' && f.select_options) {
    return (
      <FormField
        control={form.control}
        name={fieldName}
        rules={f.is_required ? { required: `${label} is required` } : undefined}
        render={({ field }) => (
          <FormItem>
            <FormLabel>{label}{f.is_required ? ' *' : ''}</FormLabel>
            <Select onValueChange={field.onChange} value={field.value || ''}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue placeholder={`Select ${label.toLowerCase()}`} />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                {f.select_options!.map((opt) => (
                  <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {f.comment && <FormDescription>{f.comment}</FormDescription>}
            <FormMessage />
          </FormItem>
        )}
      />
    );
  }

  if (f.field_type === 'textarea') {
    return (
      <FormField
        control={form.control}
        name={fieldName}
        rules={f.is_required ? { required: `${label} is required` } : undefined}
        render={({ field }) => (
          <FormItem>
            <FormLabel>{label}{f.is_required ? ' *' : ''}</FormLabel>
            <FormControl>
              <Textarea
                placeholder={f.comment || `Enter ${label.toLowerCase()}`}
                className="min-h-[80px]"
                {...field}
              />
            </FormControl>
            {f.comment && <FormDescription>{f.comment}</FormDescription>}
            <FormMessage />
          </FormItem>
        )}
      />
    );
  }

  if (f.field_type === 'boolean' || f.range_type === 'boolean') {
    return (
      <FormField
        control={form.control}
        name={fieldName}
        render={({ field }) => (
          <FormItem className="flex flex-row items-start space-x-3 space-y-0">
            <FormControl>
              <Checkbox
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            </FormControl>
            <div className="space-y-1 leading-none">
              <FormLabel>{label}</FormLabel>
              {f.comment && <FormDescription>{f.comment}</FormDescription>}
            </div>
          </FormItem>
        )}
      />
    );
  }

  // Default: text input (handles text, integer, date, uri, etc.)
  const inputType = f.range_type === 'integer' ? 'number'
    : f.range_type === 'date' || f.range_type === 'datetime' ? 'date'
    : 'text';

  return (
    <FormField
      control={form.control}
      name={fieldName}
      rules={f.is_required ? { required: `${label} is required` } : undefined}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}{f.is_required ? ' *' : ''}</FormLabel>
          <FormControl>
            <Input
              type={inputType}
              placeholder={f.comment || `Enter ${label.toLowerCase()}`}
              {...field}
              value={field.value ?? ''}
            />
          </FormControl>
          {f.comment && <FormDescription>{f.comment}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}
