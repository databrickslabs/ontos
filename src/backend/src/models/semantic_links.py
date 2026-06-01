from pydantic import BaseModel
from typing import Optional, Literal


# entity_id formats:
#   uc_catalog = catalog; uc_schema = catalog.schema; uc_table = catalog.schema.table; uc_column = catalog.schema.table.column
#   asset      = AssetDb UUID (polymorphic asset-backed entity: Table, View, Dataset, Dashboard, Column, ...)
EntityType = Literal[
    'data_domain', 'data_product', 'data_contract', 'data_contract_schema', 'data_contract_property',
    'dataset', 'asset', 'uc_catalog', 'uc_schema', 'uc_table', 'uc_column'
]


class EntitySemanticLink(BaseModel):
    id: str
    entity_id: str
    entity_type: EntityType
    iri: str
    label: Optional[str] = None


class EntitySemanticLinkCreate(BaseModel):
    entity_id: str
    entity_type: EntityType
    iri: str
    label: Optional[str] = None


