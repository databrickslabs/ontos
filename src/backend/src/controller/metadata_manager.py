from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy.orm import Session
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import VolumeType

from src.common.logging import get_logger
from src.common.config import Settings, resolve_volume
from src.models.metadata import (
    RichText, RichTextCreate, RichTextUpdate,
    Link, LinkCreate, LinkUpdate,
    Document, DocumentCreate,
    MetadataAttachment, MetadataAttachmentCreate,
    SharedAssetListResponse, MergedMetadataResponse,
)
from src.repositories.metadata_repository import (
    rich_text_repo, link_repo, document_repo, attachment_repo,
    RichTextRepository, LinkRepository, DocumentRepository, MetadataAttachmentRepository,
)
from src.repositories.change_log_repository import change_log_repo
from src.db_models.change_log import ChangeLogDb
from src.db_models.metadata import MetadataAttachmentDb

logger = get_logger(__name__)

# Constant for shared asset entity_id
SHARED_ENTITY_ID = "__shared__"


class MetadataManager:
    def __init__(
        self,
        rich_text_repository: RichTextRepository = rich_text_repo,
        link_repository: LinkRepository = link_repo,
        document_repository: DocumentRepository = document_repo,
        attachment_repository: MetadataAttachmentRepository = attachment_repo,
    ):
        self._rich_text_repo = rich_text_repository
        self._link_repo = link_repository
        self._document_repo = document_repository
        self._attachment_repo = attachment_repository

    def _log_change(self, db: Session, *, entity_type: str, entity_id: str, action: str, username: Optional[str], details_json: Optional[str] = None) -> None:
        entry = ChangeLogDb(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            username=username,
            details_json=details_json,
        )
        db.add(entry)
        db.commit()

    # --- Volume Management ---
    
    def ensure_volume_path(self, ws: WorkspaceClient, settings: Settings, base_dir: str) -> str:
        """Ensure Unity Catalog volume exists and return filesystem path.
        
        Args:
            ws: WorkspaceClient for SDK calls
            settings: Application settings with catalog/schema/volume config
            base_dir: Base directory name within volume (not used in path construction)
            
        Returns:
            Filesystem mount path for the volume (e.g., /Volumes/catalog/schema/volume)
            
        Raises:
            Exception: If volume creation or access fails
        """
        resolved = resolve_volume(settings)
        if not resolved:
            raise ValueError("DATABRICKS_VOLUME is not configured")
        catalog, schema, volume = resolved
        # Unity Catalog volume name (catalog.schema.volume)
        volume_name = f"{catalog}.{schema}.{volume}"
        # Filesystem mount path for the volume
        volume_fs_base = f"/Volumes/{catalog}/{schema}/{volume}"
        
        try:
            try:
                # Ensure volume exists
                ws.volumes.read(volume_name)
                logger.debug(f"Volume {volume_name} already exists")
            except Exception as e:
                logger.info(f"Creating volume {volume_name}")
                ws.volumes.create(
                    catalog_name=catalog,
                    schema_name=schema,
                    name=volume,
                    volume_type=VolumeType.MANAGED,
                )
                logger.info(f"Successfully created volume {volume_name}")
        except Exception as e:
            logger.error(f"Failed ensuring volume/path {volume_name}: {e!s}")
            raise
        
        # Return FS base path; caller appends base_dir/filename
        return volume_fs_base

    # --- Rich Text ---
    def create_rich_text(self, db: Session, *, data: RichTextCreate, user_email: Optional[str]) -> RichText:
        db_obj = self._rich_text_repo.create(db, obj_in=data)
        db.commit()
        db.refresh(db_obj)
        self._log_change(db, entity_type=f"{data.entity_type}:rich_text", entity_id=data.entity_id, action="CREATE", username=user_email)
        return RichText.from_orm(db_obj)

    def list_rich_texts(self, db: Session, *, entity_type: str, entity_id: str) -> List[RichText]:
        rows = self._rich_text_repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        return [RichText.from_orm(r) for r in rows]

    def update_rich_text(self, db: Session, *, id: str, data: RichTextUpdate, user_email: Optional[str]) -> Optional[RichText]:
        db_obj = self._rich_text_repo.get(db, id=id)
        if not db_obj:
            return None
        updated = self._rich_text_repo.update(db, db_obj=db_obj, obj_in=data)
        db.commit()
        db.refresh(updated)
        self._log_change(db, entity_type=f"{updated.entity_type}:rich_text", entity_id=updated.entity_id, action="UPDATE", username=user_email)
        return RichText.from_orm(updated)

    def delete_rich_text(self, db: Session, *, id: str, user_email: Optional[str]) -> bool:
        db_obj = self._rich_text_repo.get(db, id=id)
        if not db_obj:
            return False
        entity_type, entity_id = db_obj.entity_type, db_obj.entity_id
        removed = self._rich_text_repo.remove(db, id=id)
        if removed:
            db.commit()
            self._log_change(db, entity_type=f"{entity_type}:rich_text", entity_id=entity_id, action="DELETE", username=user_email)
            return True
        return False

    # --- Link ---
    def create_link(self, db: Session, *, data: LinkCreate, user_email: Optional[str]) -> Link:
        db_obj = self._link_repo.create(db, obj_in=data)
        db.commit()
        db.refresh(db_obj)
        self._log_change(db, entity_type=f"{data.entity_type}:link", entity_id=data.entity_id, action="CREATE", username=user_email)
        return Link.from_orm(db_obj)

    def list_links(self, db: Session, *, entity_type: str, entity_id: str) -> List[Link]:
        rows = self._link_repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        return [Link.from_orm(r) for r in rows]

    def update_link(self, db: Session, *, id: str, data: LinkUpdate, user_email: Optional[str]) -> Optional[Link]:
        db_obj = self._link_repo.get(db, id=id)
        if not db_obj:
            return None
        updated = self._link_repo.update(db, db_obj=db_obj, obj_in=data)
        db.commit()
        db.refresh(updated)
        self._log_change(db, entity_type=f"{updated.entity_type}:link", entity_id=updated.entity_id, action="UPDATE", username=user_email)
        return Link.from_orm(updated)

    def delete_link(self, db: Session, *, id: str, user_email: Optional[str]) -> bool:
        db_obj = self._link_repo.get(db, id=id)
        if not db_obj:
            return False
        entity_type, entity_id = db_obj.entity_type, db_obj.entity_id
        removed = self._link_repo.remove(db, id=id)
        if removed:
            db.commit()
            self._log_change(db, entity_type=f"{entity_type}:link", entity_id=entity_id, action="DELETE", username=user_email)
            return True
        return False

    # --- Document ---
    def create_document_record(self, db: Session, *, data: DocumentCreate, filename: str, content_type: Optional[str], size_bytes: Optional[int], storage_path: str, user_email: Optional[str]) -> Document:
        # DocumentCreate has base fields; other metadata supplied by upload logic
        from src.db_models.metadata import DocumentMetadataDb
        db_obj = DocumentMetadataDb(
            entity_id=data.entity_id,
            entity_type=data.entity_type,
            title=data.title,
            short_description=data.short_description,
            original_filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            created_by=user_email,
            updated_by=user_email,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        self._log_change(db, entity_type=f"{data.entity_type}:document", entity_id=data.entity_id, action="CREATE", username=user_email)
        return Document.from_orm(db_obj)

    def list_documents(self, db: Session, *, entity_type: str, entity_id: str) -> List[Document]:
        rows = self._document_repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        return [Document.from_orm(r) for r in rows]

    def delete_document(self, db: Session, *, id: str, user_email: Optional[str]) -> bool:
        db_obj = self._document_repo.get(db, id=id)
        if not db_obj:
            return False
        entity_type, entity_id = db_obj.entity_type, db_obj.entity_id
        removed = self._document_repo.remove(db, id=id)
        if removed:
            db.commit()
            self._log_change(db, entity_type=f"{entity_type}:document", entity_id=entity_id, action="DELETE", username=user_email)
            return True
        return False

    def get_document(self, db: Session, *, id: str) -> Optional[Document]:
        db_obj = self._document_repo.get(db, id=id)
        if not db_obj:
            return None
        return Document.from_orm(db_obj)

    # =========================================================================
    # Shared Assets Management
    # =========================================================================
    
    def list_shared_assets(self, db: Session, *, entity_type: Optional[str] = None) -> SharedAssetListResponse:
        """List all shared assets, optionally filtered by entity type."""
        rich_texts = [RichText.from_orm(r) for r in self._rich_text_repo.list_shared(db, entity_type=entity_type)]
        links = [Link.from_orm(l) for l in self._link_repo.list_shared(db, entity_type=entity_type)]
        documents = [Document.from_orm(d) for d in self._document_repo.list_shared(db, entity_type=entity_type)]
        return SharedAssetListResponse(rich_texts=rich_texts, links=links, documents=documents)
    
    def create_shared_rich_text(self, db: Session, *, data: RichTextCreate, user_email: Optional[str]) -> RichText:
        """Create a shared rich text asset."""
        # Override entity_id for shared assets
        data_dict = data.model_dump()
        data_dict['entity_id'] = SHARED_ENTITY_ID
        data_dict['is_shared'] = True
        data_obj = RichTextCreate(**data_dict)
        db_obj = self._rich_text_repo.create(db, obj_in=data_obj)
        db.commit()
        db.refresh(db_obj)
        self._log_change(db, entity_type="shared:rich_text", entity_id=str(db_obj.id), action="CREATE", username=user_email)
        return RichText.from_orm(db_obj)
    
    def create_shared_link(self, db: Session, *, data: LinkCreate, user_email: Optional[str]) -> Link:
        """Create a shared link asset."""
        data_dict = data.model_dump()
        data_dict['entity_id'] = SHARED_ENTITY_ID
        data_dict['is_shared'] = True
        data_obj = LinkCreate(**data_dict)
        db_obj = self._link_repo.create(db, obj_in=data_obj)
        db.commit()
        db.refresh(db_obj)
        self._log_change(db, entity_type="shared:link", entity_id=str(db_obj.id), action="CREATE", username=user_email)
        return Link.from_orm(db_obj)

    # =========================================================================
    # Metadata Attachments (attaching shared assets to entities)
    # =========================================================================
    
    def attach_shared_asset(
        self, db: Session, *, 
        entity_type: str, entity_id: str, 
        data: MetadataAttachmentCreate,
        user_email: Optional[str]
    ) -> MetadataAttachment:
        """Attach a shared asset to an entity."""
        # Check if attachment already exists
        existing = self._attachment_repo.get_attachment(
            db, entity_type=entity_type, entity_id=entity_id,
            asset_type=data.asset_type, asset_id=data.asset_id
        )
        if existing:
            # Update level_override if provided
            if data.level_override is not None:
                existing.level_override = data.level_override
                db.commit()
                db.refresh(existing)
            return MetadataAttachment.from_orm(existing)
        
        # Create new attachment
        db_obj = MetadataAttachmentDb(
            entity_type=entity_type,
            entity_id=entity_id,
            asset_type=data.asset_type,
            asset_id=data.asset_id,
            level_override=data.level_override,
            created_by=user_email,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        self._log_change(
            db, entity_type=f"{entity_type}:attachment", 
            entity_id=entity_id, action="ATTACH", username=user_email
        )
        return MetadataAttachment.from_orm(db_obj)
    
    def detach_shared_asset(
        self, db: Session, *,
        entity_type: str, entity_id: str,
        asset_type: str, asset_id: str,
        user_email: Optional[str]
    ) -> bool:
        """Detach a shared asset from an entity."""
        removed = self._attachment_repo.delete_attachment(
            db, entity_type=entity_type, entity_id=entity_id,
            asset_type=asset_type, asset_id=asset_id
        )
        if removed:
            db.commit()
            self._log_change(
                db, entity_type=f"{entity_type}:attachment",
                entity_id=entity_id, action="DETACH", username=user_email
            )
        return removed
    
    def list_attachments(
        self, db: Session, *, entity_type: str, entity_id: str
    ) -> List[MetadataAttachment]:
        """List all shared asset attachments for an entity."""
        rows = self._attachment_repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        return [MetadataAttachment.from_orm(r) for r in rows]

    # =========================================================================
    # Merged Metadata with Inheritance
    # =========================================================================
    
    def resolve_inheritance_sources(
        self, db: Session, *, entity_type: str, entity_id: str
    ) -> List[Tuple[str, str]]:
        """Entities whose inheritable metadata flows into this one, as (entity_type, entity_id).

        - Data contract: the assets that implement it, i.e. stored ``implementsContract``
          relationships plus Table/View assets whose location matches a schema
          object's physical name (the same rule business lineage uses).
        - Data product: each output port's contract and the asset at the port's
          ``asset_identifier`` (exact location match, any asset type, so dashboard
          ports work too). Inheritance is one hop; a product does not pick up
          metadata its contracts inherit from their assets.
        """
        found: List[Tuple[str, str]] = []

        def add(kind: str, ident: Optional[str]) -> None:
            if ident and (kind, str(ident)) not in found:
                found.append((kind, str(ident)))

        if entity_type == "data_contract":
            from src.db_models.entity_relationships import EntityRelationshipDb
            from src.db_models.data_contracts import SchemaObjectDb
            from src.controller.model_lineage import ModelLineageResolver

            rels = (
                db.query(EntityRelationshipDb.source_id)
                .filter(
                    EntityRelationshipDb.target_type == "DataContract",
                    EntityRelationshipDb.target_id == entity_id,
                    EntityRelationshipDb.relationship_type == "implementsContract",
                )
                .all()
            )
            for (source_id,) in rels:
                add("asset", source_id)
            physical_names = (
                db.query(SchemaObjectDb.physical_name)
                .filter(SchemaObjectDb.contract_id == entity_id, SchemaObjectDb.physical_name.isnot(None))
                .all()
            )
            for (physical_name,) in physical_names:
                pn = physical_name.strip().lower()
                if pn:
                    for asset in ModelLineageResolver._query_physical_assets(db, pn, exact=False):
                        add("asset", asset.id)

        elif entity_type == "data_product":
            from sqlalchemy import func
            from src.db_models.assets import AssetDb
            from src.db_models.data_products import OutputPortDb
            from src.controller.model_lineage import ModelLineageResolver

            ports = db.query(OutputPortDb).filter(OutputPortDb.product_id == entity_id).all()
            for port in ports:
                contract = ModelLineageResolver._contract_by_ref(db, port.contract_id)
                if contract is not None:
                    add("data_contract", contract.id)
                identifier = (port.asset_identifier or "").strip().lower()
                if identifier:
                    for asset in db.query(AssetDb).filter(func.lower(AssetDb.location) == identifier).all():
                        add("asset", asset.id)

        return found

    def _source_names(self, db: Session, sources: List[Tuple[str, str]]) -> Dict[str, str]:
        """Display names for inheritance sources, keyed like ``sources`` values."""
        from uuid import UUID
        from src.db_models.assets import AssetDb
        from src.db_models.data_contracts import DataContractDb

        names: Dict[str, str] = {}
        contract_ids = [ident for kind, ident in sources if kind == "data_contract"]
        if contract_ids:
            for c in db.query(DataContractDb.id, DataContractDb.name).filter(DataContractDb.id.in_(contract_ids)).all():
                names[f"contract:{c.id}"] = c.name
        asset_ids = []
        for kind, ident in sources:
            if kind == "asset":
                try:
                    asset_ids.append(UUID(ident))
                except (ValueError, TypeError):
                    continue
        if asset_ids:
            for a in db.query(AssetDb.id, AssetDb.name).filter(AssetDb.id.in_(asset_ids)).all():
                names[f"asset:{a.id}"] = a.name
        return names

    def _default_max_level(self, db: Session, entity_type: str, entity_id: str) -> int:
        if entity_type == "data_product":
            from src.db_models.data_products import DataProductDb
            product = db.query(DataProductDb.max_level_inheritance).filter(DataProductDb.id == entity_id).first()
            if product is not None and product[0] is not None:
                return product[0]
        return 99

    def get_merged_metadata(
        self, db: Session, *,
        entity_type: str, entity_id: str,
        contract_ids: Optional[List[str]] = None,
        max_level_inheritance: Optional[int] = None
    ) -> MergedMetadataResponse:
        """
        Get merged metadata for an entity, including inherited metadata.
        
        - Direct metadata attached to the entity
        - Attached shared assets
        - Inherited metadata from the sources found by ``resolve_inheritance_sources``
          (contracts and assets), plus any explicitly passed ``contract_ids``
        
        Merging logic:
        - All items are sorted by level (ascending)
        - For same level, entity's own metadata comes before inherited
        - Only metadata with inheritable=True and level <= max_level_inheritance is inherited.
          The default is the product's ``max_level_inheritance`` (99 for other entities).
        """
        if max_level_inheritance is None:
            max_level_inheritance = self._default_max_level(db, entity_type, entity_id)
        sources: Dict[str, str] = {}
        
        # 1. Get direct metadata for the entity
        direct_rich_texts = self._rich_text_repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        direct_links = self._link_repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        direct_docs = self._document_repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        
        for rt in direct_rich_texts:
            sources[str(rt.id)] = entity_id
        for link in direct_links:
            sources[str(link.id)] = entity_id
        for doc in direct_docs:
            sources[str(doc.id)] = entity_id
        
        # 2. Get attached shared assets
        attachments = self._attachment_repo.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        
        attached_rt_ids = [a.asset_id for a in attachments if a.asset_type == 'rich_text']
        attached_link_ids = [a.asset_id for a in attachments if a.asset_type == 'link']
        attached_doc_ids = [a.asset_id for a in attachments if a.asset_type == 'document']
        
        attached_rich_texts = self._rich_text_repo.get_by_ids(db, ids=attached_rt_ids)
        attached_links = self._link_repo.get_by_ids(db, ids=attached_link_ids)
        attached_docs = self._document_repo.get_by_ids(db, ids=attached_doc_ids)
        
        for rt in attached_rich_texts:
            sources[str(rt.id)] = f"shared:{entity_id}"
        for link in attached_links:
            sources[str(link.id)] = f"shared:{entity_id}"
        for doc in attached_docs:
            sources[str(doc.id)] = f"shared:{entity_id}"
        
        # 3. Get inherited metadata from contracts (if any)
        inherited_rich_texts = []
        inherited_links = []
        inherited_docs = []
        
        inherit_from = self.resolve_inheritance_sources(db, entity_type=entity_type, entity_id=entity_id)
        for contract_id in contract_ids or []:
            if ("data_contract", contract_id) not in inherit_from:
                inherit_from.append(("data_contract", contract_id))

        for source_type, source_id in inherit_from:
            source_key = f"contract:{source_id}" if source_type == "data_contract" else f"asset:{source_id}"
            source_rts = self._rich_text_repo.list_inheritable_for_entity(
                db, entity_type=source_type, entity_id=source_id, max_level=max_level_inheritance
            )
            source_links = self._link_repo.list_inheritable_for_entity(
                db, entity_type=source_type, entity_id=source_id, max_level=max_level_inheritance
            )
            source_docs = self._document_repo.list_inheritable_for_entity(
                db, entity_type=source_type, entity_id=source_id, max_level=max_level_inheritance
            )

            # An item reachable through several sources keeps its first source
            for rt in source_rts:
                sources.setdefault(str(rt.id), source_key)
            for link in source_links:
                sources.setdefault(str(link.id), source_key)
            for doc in source_docs:
                sources.setdefault(str(doc.id), source_key)

            inherited_rich_texts.extend(source_rts)
            inherited_links.extend(source_links)
            inherited_docs.extend(source_docs)
        
        # 4. Merge and sort by level
        all_rich_texts = list(direct_rich_texts) + list(attached_rich_texts) + inherited_rich_texts
        all_links = list(direct_links) + list(attached_links) + inherited_links
        all_docs = list(direct_docs) + list(attached_docs) + inherited_docs
        
        # Sort by level (ascending), then by created_at
        all_rich_texts.sort(key=lambda x: (x.level, x.created_at))
        all_links.sort(key=lambda x: (x.level, x.created_at))
        all_docs.sort(key=lambda x: (x.level, x.created_at))
        
        # Deduplicate by ID (keep first occurrence which is the one with lower level)
        seen_rt_ids = set()
        unique_rich_texts = []
        for rt in all_rich_texts:
            if str(rt.id) not in seen_rt_ids:
                seen_rt_ids.add(str(rt.id))
                unique_rich_texts.append(rt)
        
        seen_link_ids = set()
        unique_links = []
        for link in all_links:
            if str(link.id) not in seen_link_ids:
                seen_link_ids.add(str(link.id))
                unique_links.append(link)
        
        seen_doc_ids = set()
        unique_docs = []
        for doc in all_docs:
            if str(doc.id) not in seen_doc_ids:
                seen_doc_ids.add(str(doc.id))
                unique_docs.append(doc)
        
        return MergedMetadataResponse(
            rich_texts=[RichText.from_orm(rt) for rt in unique_rich_texts],
            links=[Link.from_orm(link) for link in unique_links],
            documents=[Document.from_orm(doc) for doc in unique_docs],
            sources=sources,
            source_names=self._source_names(db, inherit_from),
        )