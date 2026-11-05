import type { InferredSchemaObject } from './infer-from-asset-dialog';

/** The inferred fields every schema editor keeps, with transform sources as the editors' comma-separated text. */
export function inferredPropertyFields(p: InferredSchemaObject['properties'][number]) {
  return {
    name: p.name,
    physicalType: p.physicalType,
    logicalType: p.logicalType || 'string',
    required: p.required,
    description: p.description,
    partitioned: p.partitioned,
    ...(p.businessName ? { businessName: p.businessName } : {}),
    ...(p.physicalName ? { physicalName: p.physicalName } : {}),
    ...(p.transformLogic ? { transformLogic: p.transformLogic } : {}),
    ...(p.transformSourceObjects?.length ? { transformSourceObjects: p.transformSourceObjects.join(', ') } : {}),
  };
}
