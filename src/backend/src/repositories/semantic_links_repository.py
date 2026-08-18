from typing import List
from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.models.semantic_links import EntitySemanticLinkCreate


class EntitySemanticLinksRepository(CRUDBase[EntitySemanticLinkDb, EntitySemanticLinkCreate, dict]):
    def list_for_entity(self, db: Session, entity_id: str, entity_type: str) -> List[EntitySemanticLinkDb]:
        return db.query(self.model).filter(
            self.model.entity_id == entity_id,
            self.model.entity_type == entity_type
        ).all()

    def list_for_iri(self, db: Session, iri: str) -> List[EntitySemanticLinkDb]:
        return db.query(self.model).filter(self.model.iri == iri).all()

    def list_for_entity_prefix(
        self, db: Session, entity_id_prefix: str, entity_type: str
    ) -> List[EntitySemanticLinkDb]:
        """List links whose entity_id starts with the given prefix.

        Used to fetch all property-level links for a contract schema in one
        query (entity_id shape: ``{contract_id}#{schema}#{property}``), so the
        UI can render column-level concept assignments without an API call per
        property. The ``%``/``_`` LIKE wildcards are escaped so contract ids
        and schema names containing them match literally.
        """
        escaped = (
            entity_id_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        return db.query(self.model).filter(
            self.model.entity_type == entity_type,
            self.model.entity_id.like(f"{escaped}%", escape="\\"),
        ).all()

    def get_by_entity_and_iri(self, db: Session, entity_id: str, entity_type: str, iri: str) -> EntitySemanticLinkDb | None:
        return db.query(self.model).filter(
            self.model.entity_id == entity_id,
            self.model.entity_type == entity_type,
            self.model.iri == iri
        ).first()

    def list_all(self, db: Session) -> List[EntitySemanticLinkDb]:
        return db.query(self.model).all()


entity_semantic_links_repo = EntitySemanticLinksRepository(EntitySemanticLinkDb)


