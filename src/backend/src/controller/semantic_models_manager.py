from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta
from rdflib import Graph, ConjunctiveGraph, Dataset
from rdflib.namespace import RDF, RDFS, SKOS, OWL
from rdflib import URIRef, Literal, Namespace, BNode

# Ontos application ontology namespace
ONTOS = Namespace("http://ontos.app/ontology#")

# XSD namespace for datatype handling
from rdflib.namespace import XSD
from sqlalchemy.orm import Session
import signal
from contextlib import contextmanager
import json
import shutil
from filelock import FileLock

from src.db_models.semantic_models import SemanticModelDb
from src.models.semantic_models import (
    SemanticModel as SemanticModelApi,
    SemanticModelCreate,
    SemanticModelUpdate,
    SemanticModelPreview,
)
from src.models.ontology import (
    OntologyConcept,
    OntologyProperty,
    SemanticModel as SemanticModelOntology,
    ConceptHierarchy,
    TaxonomyStats,
    ConceptSearchResult
)
from src.repositories.semantic_models_repository import semantic_models_repo
from src.repositories.rdf_triples_repository import rdf_triples_repo
from src.common.logging import get_logger
from src.common.sparql_validator import SPARQLQueryValidator


logger = get_logger(__name__)


def _sanitize_context_name(name: str) -> str:
    """Sanitize a name for use in URN context identifiers.
    
    Replaces special characters that are problematic in URNs with safe alternatives.
    Preserves human readability while ensuring valid URN syntax.
    
    Args:
        name: The original name (e.g., filename like "my_ontology.ttl")
    
    Returns:
        Sanitized name safe for use in URN (e.g., "my_ontology.ttl")
    """
    import re
    # Replace spaces with underscores
    sanitized = name.replace(' ', '_')
    # Remove or replace characters that are problematic in URNs
    # Keep alphanumeric, underscores, hyphens, and dots
    sanitized = re.sub(r'[^a-zA-Z0-9_.\-]', '_', sanitized)
    # Collapse multiple underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    # Ensure we have a valid name (fallback if empty)
    if not sanitized:
        sanitized = "unnamed"
    return sanitized


@contextmanager
def timeout(seconds: int):
    """Context manager for query timeout using signals.
    
    Note: This only works on Unix-like systems. On Windows, this will
    not enforce a timeout but will still allow the query to execute.
    """
    def timeout_handler(signum, frame):
        raise TimeoutError("Query execution timeout")
    
    # Only set up signal handler on Unix-like systems
    if hasattr(signal, 'SIGALRM'):
        original_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, original_handler)
    else:
        # On Windows or systems without SIGALRM, just yield without timeout
        logger.warning("Query timeout not available on this platform")
        yield


class CachedResult:
    """Simple cache entry with TTL"""
    def __init__(self, value: Any, ttl_seconds: int = 300):
        self.value = value
        self.expires_at = datetime.now() + timedelta(seconds=ttl_seconds)

    def is_valid(self) -> bool:
        return datetime.now() < self.expires_at


class SemanticModelsManager:
    def __init__(self, db: Session, data_dir: Optional[Path] = None):
        self._db = db
        self._data_dir = data_dir or Path(__file__).parent.parent / "data"
        # Use ConjunctiveGraph to support named graphs/contexts
        self._graph = ConjunctiveGraph()
        # Cache for expensive operations (TTL: 5 minutes)
        self._cache: Dict[str, CachedResult] = {}
        # In-memory caches populated during rebuild — always authoritative
        # when set, bypassing the file-based persistent cache.
        self._cached_concepts: Optional[List[OntologyConcept]] = None
        self._cached_taxonomies: Optional[List] = None
        self._cached_stats: Optional[TaxonomyStats] = None
        logger.info(f"SemanticModelsManager initialized with data_dir: {self._data_dir}")
        # Load file-based taxonomies immediately
        try:
            self.rebuild_graph_from_enabled()
        except Exception as e:
            logger.error(f"Failed to rebuild graph during initialization: {e}")

    def list(self) -> List[SemanticModelApi]:
        items = semantic_models_repo.get_multi(self._db)
        return [self._to_api(m) for m in items]

    def get(self, model_id: str) -> Optional[SemanticModelApi]:
        m = semantic_models_repo.get(self._db, id=model_id)
        return self._to_api(m) if m else None

    def create(self, data: SemanticModelCreate, created_by: Optional[str]) -> SemanticModelApi:
        # Validate content can be parsed BEFORE creating DB record to avoid dead rows
        temp_graph = None
        fmt = None
        if data.content_text:
            try:
                temp_graph = Graph()
                # Detect format from content - Turtle content starts with @prefix or @base
                content_stripped = data.content_text.strip()
                if content_stripped.startswith('@prefix') or content_stripped.startswith('@base'):
                    fmt = 'turtle'
                elif content_stripped.startswith('{') or content_stripped.startswith('['):
                    fmt = 'json-ld'
                elif content_stripped.startswith('<?xml') or content_stripped.startswith('<rdf:RDF'):
                    fmt = 'xml'
                else:
                    # Default based on format field
                    fmt = 'turtle' if data.format in ('skos', 'rdfs') else 'xml'
                temp_graph.parse(data=data.content_text, format=fmt)
                
                if len(temp_graph) == 0:
                    raise ValueError("Content parsed but contains no triples")
                    
                logger.info(f"Validated content: {len(temp_graph)} triples in {fmt} format")
            except Exception as e:
                logger.error(f"Failed to parse semantic model content: {e}")
                raise ValueError(f"Invalid ontology content: {e}")
        
        # Now create DB record since content is valid
        db_obj = semantic_models_repo.create(self._db, obj_in=data)
        if created_by:
            db_obj.created_by = created_by
            db_obj.updated_by = created_by
            self._db.add(db_obj)
        self._db.flush()
        self._db.refresh(db_obj)
        
        # Import triples to rdf_triples table (already validated above)
        if temp_graph is not None and len(temp_graph) > 0:
            try:
                sanitized_name = _sanitize_context_name(db_obj.name)
                context_name = f"urn:semantic-model:{sanitized_name}"
                self._import_graph_to_db(
                    graph=temp_graph,
                    context_name=context_name,
                    source_type='upload',
                    source_identifier=db_obj.name,
                    created_by=created_by,
                )
            except Exception as e:
                # Rollback the DB record since import failed
                logger.error(f"Failed to import triples, rolling back: {e}")
                self._db.rollback()
                raise ValueError(f"Failed to import triples: {e}")
        
        self._db.commit()  # Persist changes immediately since manager uses singleton session
        return self._to_api(db_obj)

    def update(self, model_id: str, update: SemanticModelUpdate, updated_by: Optional[str]) -> Optional[SemanticModelApi]:
        db_obj = semantic_models_repo.get(self._db, id=model_id)
        if not db_obj:
            return None
        updated = semantic_models_repo.update(self._db, db_obj=db_obj, obj_in=update)
        if updated_by:
            updated.updated_by = updated_by
            self._db.add(updated)
        self._db.flush()
        self._db.refresh(updated)
        self._db.commit()  # Persist changes immediately since manager uses singleton session
        return self._to_api(updated)

    def replace_content(self, model_id: str, content_text: str, original_filename: Optional[str], content_type: Optional[str], size_bytes: Optional[int], updated_by: Optional[str]) -> Optional[SemanticModelApi]:
        db_obj = semantic_models_repo.get(self._db, id=model_id)
        if not db_obj:
            return None
        db_obj.content_text = content_text
        if original_filename is not None:
            db_obj.original_filename = original_filename
        if content_type is not None:
            db_obj.content_type = content_type
        if size_bytes is not None:
            db_obj.size_bytes = str(size_bytes)
        if updated_by:
            db_obj.updated_by = updated_by
        self._db.add(db_obj)
        self._db.flush()
        self._db.refresh(db_obj)
        
        # Update rdf_triples: remove old triples, import new ones
        # Use sanitized name for human-readable context identifiers
        sanitized_name = _sanitize_context_name(db_obj.name)
        context_name = f"urn:semantic-model:{sanitized_name}"
        try:
            # Remove existing triples for this model
            rdf_triples_repo.remove_by_context(self._db, context_name)
            
            # Import new triples
            temp_graph = Graph()
            fmt = 'turtle' if db_obj.format == 'skos' else 'xml'
            temp_graph.parse(data=content_text, format=fmt)
            self._import_graph_to_db(
                graph=temp_graph,
                context_name=context_name,
                source_type='upload',
                source_identifier=db_obj.name,
                created_by=updated_by,
            )
        except Exception as e:
            logger.warning(f"Failed to update semantic model triples in database: {e}")
        
        self._db.commit()  # Persist changes immediately since manager uses singleton session
        return self._to_api(db_obj)

    def delete(self, model_id: str) -> bool:
        # Get the model before deleting to check if we need to delete the physical file
        model = semantic_models_repo.get(self._db, id=model_id)
        if not model:
            return False
        
        # If this was loaded from data/semantic_models/ directory, delete the physical file too
        if model.created_by == 'system@startup' and model.original_filename:
            try:
                file_path = self._data_dir / "semantic_models" / model.original_filename
                if file_path.exists() and file_path.is_file():
                    file_path.unlink()
                    logger.info(f"Deleted physical file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete physical file for model {model_id}: {e}")
        
        # Delete triples from rdf_triples table
        # Use sanitized name for human-readable context identifiers (consistent with create/replace)
        sanitized_name = _sanitize_context_name(model.name)
        context_name = f"urn:semantic-model:{sanitized_name}"
        try:
            deleted_count = rdf_triples_repo.remove_by_context(self._db, context_name)
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} triples for semantic model '{model.name}' (context: {context_name})")
        except Exception as e:
            logger.warning(f"Failed to delete triples for semantic model '{model.name}': {e}")
        
        # Delete from database
        obj = semantic_models_repo.remove(self._db, id=model_id)
        self._db.commit()  # Persist changes immediately since manager uses singleton session
        return obj is not None

    def preview(self, model_id: str, max_chars: int = 2000) -> Optional[SemanticModelPreview]:
        db_obj = semantic_models_repo.get(self._db, id=model_id)
        if not db_obj:
            return None
        return SemanticModelPreview(
            id=db_obj.id,
            name=db_obj.name,
            format=db_obj.format,  # type: ignore
            preview=db_obj.content_text[:max_chars] if db_obj.content_text else ""
        )

    def get_content(self, model_id: str) -> Optional[Dict[str, str]]:
        """Get the full content of a semantic model.
        
        For database models: returns content_text from DB.
        For file-based models (id starts with 'file-'): reads from filesystem.
        
        Returns:
            Dict with 'content', 'format', and 'name' keys, or None if not found.
        """
        # Handle file-based models (pseudo-IDs like 'file-databricks_ontology')
        if model_id.startswith('file-'):
            file_name = model_id[5:]  # Remove 'file-' prefix
            taxonomy_dir = self._data_dir / "taxonomies"
            
            # Try common extensions
            for ext in ['.ttl', '.rdf', '.owl', '.xml', '.n3', '.nt']:
                file_path = taxonomy_dir / f"{file_name}{ext}"
                if file_path.exists() and file_path.is_file():
                    try:
                        content = file_path.read_text(encoding='utf-8')
                        # Determine format from extension
                        fmt = 'skos' if ext in ['.ttl', '.n3', '.nt'] else 'rdfs'
                        return {
                            'content': content,
                            'format': fmt,
                            'name': file_name
                        }
                    except Exception as e:
                        logger.error(f"Failed to read file-based model '{file_name}': {e}")
                        return None
            
            # Try without adding extension (file_name might already include it)
            file_path = taxonomy_dir / file_name
            if file_path.exists() and file_path.is_file():
                try:
                    content = file_path.read_text(encoding='utf-8')
                    ext = file_path.suffix.lower()
                    fmt = 'skos' if ext in ['.ttl', '.n3', '.nt'] else 'rdfs'
                    return {
                        'content': content,
                        'format': fmt,
                        'name': file_name
                    }
                except Exception as e:
                    logger.error(f"Failed to read file-based model '{file_name}': {e}")
                    return None
            
            logger.warning(f"File-based model not found: {file_name}")
            return None
        
        # Handle database models
        db_obj = semantic_models_repo.get(self._db, id=model_id)
        if not db_obj:
            return None
        
        return {
            'content': db_obj.content_text or '',
            'format': db_obj.format,
            'name': db_obj.name
        }

    def _to_api(self, db_obj: SemanticModelDb) -> SemanticModelApi:
        return SemanticModelApi(
            id=db_obj.id,
            name=db_obj.name,
            format=db_obj.format,  # type: ignore
            original_filename=db_obj.original_filename,
            content_type=db_obj.content_type,
            size_bytes=int(db_obj.size_bytes) if db_obj.size_bytes is not None and str(db_obj.size_bytes).isdigit() else None,
            enabled=db_obj.enabled,
            created_by=db_obj.created_by,
            updated_by=db_obj.updated_by,
            createdAt=db_obj.created_at,
            updatedAt=db_obj.updated_at,
        )

    # --- Graph Management ---
    def _parse_into_graph(self, content_text: str, fmt: str) -> None:
        """Parse content into the main graph.
        
        Auto-detects format from content since the fmt field is often unreliable.
        """
        if not content_text or not content_text.strip():
            return
            
        # Auto-detect format from content
        content_stripped = content_text.strip()
        if content_stripped.startswith('@prefix') or content_stripped.startswith('@base'):
            parse_format = 'turtle'
        elif content_stripped.startswith('{') or content_stripped.startswith('['):
            parse_format = 'json-ld'
        elif content_stripped.startswith('<?xml') or content_stripped.startswith('<rdf:RDF'):
            parse_format = 'xml'
        else:
            # Default to turtle for modern ontologies
            parse_format = 'turtle'
        
        self._graph.parse(data=content_text, format=parse_format)

    def _parse_into_graph_context(self, content_text: str, fmt: str, context: Graph) -> None:
        """Parse content into a specific named graph context.
        
        Auto-detects format from content since the fmt field is often unreliable
        (e.g., 'rdfs' may contain Turtle, JSON-LD, or RDF/XML).
        """
        if not content_text or not content_text.strip():
            return
            
        # Auto-detect format from content
        content_stripped = content_text.strip()
        if content_stripped.startswith('@prefix') or content_stripped.startswith('@base'):
            parse_format = 'turtle'
        elif content_stripped.startswith('{') or content_stripped.startswith('['):
            parse_format = 'json-ld'
        elif content_stripped.startswith('<?xml') or content_stripped.startswith('<rdf:RDF'):
            parse_format = 'xml'
        else:
            # Default to turtle for modern ontologies
            parse_format = 'turtle'
        
        context.parse(data=content_text, format=parse_format)

    # --- RDF Triple Persistence Methods ---
    
    def _skolemize_bnode(self, bnode: BNode, context_name: str) -> str:
        """Convert a blank node to a stable URI for persistence.
        
        Blank nodes are graph-local identifiers. To persist them, we convert
        them to URIs that include the context name for global uniqueness.
        """
        return f"urn:ontos:bnode:{context_name}:{str(bnode)}"

    def _is_skolemized_bnode(self, uri_str: str) -> bool:
        """Check if a URI string is a skolemized blank node."""
        return uri_str.startswith("urn:ontos:bnode:")

    def _walk_rdf_list(self, context, list_head) -> List:
        """Walk an RDF Collection (rdf:List) and return all members.
        
        Works with both real BNodes and skolemized blank node URIRefs.
        """
        members = []
        current = list_head
        nil_str = str(RDF.nil)
        seen = set()
        while current and str(current) != nil_str:
            current_str = str(current)
            if current_str in seen:
                break
            seen.add(current_str)
            firsts = list(context.objects(current, RDF.first))
            if firsts:
                members.append(firsts[0])
            rests = list(context.objects(current, RDF.rest))
            current = rests[0] if rests else None
        return members

    def _extract_parents_from_owl_equivalent_class(self, context, concept_uri: URIRef) -> List[str]:
        """Extract implicit parent classes from owl:equivalentClass + owl:intersectionOf.
        
        OWL semantics: if A ≡ B ∩ C then A ⊑ B and A ⊑ C.
        Named classes in the intersection are treated as parents;
        restrictions and other blank node class expressions are skipped.
        """
        parents = []
        for eq_class in context.objects(concept_uri, OWL.equivalentClass):
            for intersection_list_head in context.objects(eq_class, OWL.intersectionOf):
                for member in self._walk_rdf_list(context, intersection_list_head):
                    member_str = str(member)
                    if (not isinstance(member, BNode)
                            and not self._is_skolemized_bnode(member_str)
                            and not member_str.startswith("http://www.w3.org/")
                            and member_str not in parents):
                        parents.append(member_str)
        return parents

    def _find_children_via_owl_equivalent_class(self, context, concept_uri: URIRef) -> List[str]:
        """Find classes that are implicit children via owl:equivalentClass + owl:intersectionOf.
        
        If B ≡ A ∩ ..., then B ⊑ A, so B is a child of A.
        """
        children = []
        concept_str = str(concept_uri)
        for subj in context.subjects(OWL.equivalentClass, None):
            subj_str = str(subj)
            if isinstance(subj, BNode) or self._is_skolemized_bnode(subj_str):
                continue
            parents = self._extract_parents_from_owl_equivalent_class(context, subj)
            if concept_str in parents and subj_str not in children:
                children.append(subj_str)
        return children

    def _import_graph_to_db(
        self,
        graph: Graph,
        context_name: str,
        source_type: str,
        source_identifier: str,
        created_by: Optional[str] = None,
    ) -> int:
        """Import all triples from an rdflib graph into the database.
        
        Uses bulk insert with ON CONFLICT DO NOTHING for idempotent imports.
        Blank nodes are skolemized to stable URIs.
        
        Args:
            graph: The rdflib Graph to import
            context_name: Named graph context (e.g., 'urn:taxonomy:databricks_ontology')
            source_type: Type of source ('file', 'upload', 'demo', 'link')
            source_identifier: Identifier for the source (filename, model_id, etc.)
            created_by: User who initiated the import
        
        Returns:
            Number of triples actually inserted (excludes duplicates)
        """
        triples_to_insert = []
        
        for subj, pred, obj in graph:
            # Handle subject (can be URI or blank node)
            if isinstance(subj, BNode):
                subject_uri = self._skolemize_bnode(subj, context_name)
            else:
                subject_uri = str(subj)
            
            predicate_uri = str(pred)
            
            # Handle object (can be URI, blank node, or literal)
            if isinstance(obj, BNode):
                object_value = self._skolemize_bnode(obj, context_name)
                object_is_uri = True
                object_language = ''
                object_datatype = ''
            elif isinstance(obj, Literal):
                object_value = str(obj)
                object_is_uri = False
                object_language = obj.language if obj.language else ''
                object_datatype = str(obj.datatype) if obj.datatype else ''
            else:
                # URIRef
                object_value = str(obj)
                object_is_uri = True
                object_language = ''
                object_datatype = ''
            
            triples_to_insert.append({
                'subject_uri': subject_uri,
                'predicate_uri': predicate_uri,
                'object_value': object_value,
                'object_is_uri': object_is_uri,
                'object_language': object_language,
                'object_datatype': object_datatype,
                'context_name': context_name,
                'source_type': source_type,
                'source_identifier': source_identifier,
                'created_by': created_by,
            })
        
        if triples_to_insert:
            inserted = rdf_triples_repo.add_triples_bulk(self._db, triples_to_insert)
            self._db.commit()
            logger.info(f"Imported {inserted}/{len(triples_to_insert)} triples "
                       f"from {source_type}:{source_identifier} to context '{context_name}'")
            return inserted
        return 0

    def _sync_bundled_taxonomies(self) -> None:
        """Sync bundled taxonomy files from data/taxonomies/ to the database.
        
        Called on every startup. Uses ON CONFLICT DO NOTHING for idempotent
        behavior - existing triples are skipped, new/missing triples are added.
        This allows:
        - First run: imports everything
        - Subsequent runs: fast no-op for existing triples
        - New files added: automatically imported
        - Partial DB: self-healing backfill
        """
        taxonomy_dir = self._data_dir / "taxonomies"
        
        if not taxonomy_dir.exists() or not taxonomy_dir.is_dir():
            logger.warning(f"Taxonomy directory does not exist: {taxonomy_dir}")
            return
        
        taxonomy_files = list(taxonomy_dir.glob("*.ttl"))
        logger.info(f"Syncing {len(taxonomy_files)} bundled taxonomy files to database")
        
        for f in taxonomy_files:
            if not f.is_file():
                continue
            
            context_name = f"urn:taxonomy:{f.stem}"
            
            try:
                # Parse the TTL file into a temporary graph
                temp_graph = Graph()
                temp_graph.parse(f.as_posix(), format='turtle')
                triple_count = len(temp_graph)
                
                # Import to database (idempotent with ON CONFLICT DO NOTHING)
                inserted = self._import_graph_to_db(
                    graph=temp_graph,
                    context_name=context_name,
                    source_type='file',
                    source_identifier=f.name,
                    created_by='system@startup',
                )
                
                if inserted > 0:
                    logger.info(f"Synced taxonomy '{f.name}': {inserted} new triples "
                               f"(total in file: {triple_count})")
                else:
                    logger.debug(f"Taxonomy '{f.name}' already synced ({triple_count} triples)")
                    
            except Exception as e:
                logger.error(f"Failed to sync taxonomy {f.name}: {e}")
                self._db.rollback()

    def _get_disabled_context_names(self) -> set:
        """Build the set of rdf_triples context names belonging to disabled semantic models."""
        disabled_contexts: set = set()
        all_models = semantic_models_repo.get_multi(self._db)
        for m in all_models:
            if not m.enabled:
                sanitized = _sanitize_context_name(m.name)
                disabled_contexts.add(f"urn:semantic-model:{sanitized}")
        return disabled_contexts

    def _load_triples_from_db_to_graph(self) -> None:
        """Load triples from the database into the in-memory graph.
        
        This replaces direct file loading - the database is now the source of truth.
        Triples are organized into named graph contexts based on their context_name.
        Contexts belonging to disabled semantic models are skipped.
        """
        disabled_contexts = self._get_disabled_context_names()
        if disabled_contexts:
            logger.info(f"Skipping {len(disabled_contexts)} disabled contexts: {disabled_contexts}")

        all_triples = rdf_triples_repo.list_all(self._db)
        loaded = 0
        skipped = 0

        for triple in all_triples:
            if triple.context_name in disabled_contexts:
                skipped += 1
                continue

            context = self._graph.get_context(triple.context_name)
            
            subj = URIRef(triple.subject_uri)
            pred = URIRef(triple.predicate_uri)
            
            if triple.object_is_uri:
                obj = URIRef(triple.object_value)
            else:
                if triple.object_language:
                    obj = Literal(triple.object_value, lang=triple.object_language)
                elif triple.object_datatype:
                    obj = Literal(triple.object_value, datatype=URIRef(triple.object_datatype))
                else:
                    obj = Literal(triple.object_value)
            
            context.add((subj, pred, obj))
            loaded += 1

        logger.info(f"Loaded {loaded} triples into graph (skipped {skipped} from disabled models)")
        
        # Log stats by context
        contexts = rdf_triples_repo.list_contexts(self._db)
        for ctx in contexts:
            if ctx not in disabled_contexts:
                count = rdf_triples_repo.count_by_context(self._db, ctx)
                logger.debug(f"Loaded context '{ctx}': {count} triples")

    def _sync_entity_semantic_links_to_graph(self) -> None:
        """Sync semantic links from entity_semantic_links table to in-memory graph.
        
        This ensures that any links that weren't properly dual-written to rdf_triples
        (e.g., due to transaction timing or app_state not being available) are still
        available for graph queries.
        
        Links are added to the 'urn:semantic-links' context with the predicate
        http://ontos.app/ontology#semanticAssignment.
        """
        from src.repositories.semantic_links_repository import entity_semantic_links_repo
        
        context_name = "urn:semantic-links"
        context = self._graph.get_context(context_name)
        predicate = ONTOS.semanticAssignment
        
        links = entity_semantic_links_repo.list_all(self._db)
        added_count = 0
        
        for link in links:
            # Build the subject URI from entity_type and entity_id
            subject_uri = f"urn:ontos:{link.entity_type}:{link.entity_id}"
            subj = URIRef(subject_uri)
            obj = URIRef(link.iri)
            
            # Check if triple already exists in the graph
            if (subj, predicate, obj) not in context:
                context.add((subj, predicate, obj))
                added_count += 1
        
        if added_count > 0:
            logger.info(f"Synced {added_count} semantic links from entity_semantic_links to graph")
        else:
            logger.debug(f"All {len(links)} semantic links already present in graph")

    def _load_database_glossaries_into_graph(self) -> None:
        """Load database glossaries as RDF triples into named graphs"""
        try:
            # We'll need to import the business glossaries manager to avoid circular imports
            # For now, we'll defer this implementation
            logger.debug("Database glossary loading will be implemented when business glossaries manager is updated")
        except Exception as e:
            logger.warning(f"Failed to load database glossaries into graph: {e}")

    def _register_sources_as_collections(self) -> None:
        """Auto-register existing RDF sources as KnowledgeCollection entries.
        
        Scans all contexts in the in-memory graph and creates collection
        metadata in urn:meta:sources for any that aren't already registered.
        Imported sources are marked as non-editable by default.
        """
        from datetime import datetime
        
        META_CONTEXT = "urn:meta:sources"
        now = datetime.utcnow().isoformat() + "Z"
        
        # Get or create meta context
        meta_context = self._graph.get_context(URIRef(META_CONTEXT))
        
        # Find all existing collections
        existing_collections = set()
        for subj in meta_context.subjects(RDF.type, ONTOS.KnowledgeCollection):
            existing_collections.add(str(subj))
        
        registered_count = 0
        
        # Scan all contexts and register missing ones
        for context in self._graph.contexts():
            context_name = str(context.identifier)
            
            # Skip system contexts
            if context_name in ("urn:x-rdflib:default", META_CONTEXT, ""):
                continue
            
            # Skip if already registered
            if context_name in existing_collections:
                continue
            
            # Infer collection type and label from context name
            if context_name.startswith("urn:taxonomy:"):
                coll_type = "taxonomy"
                label = context_name.replace("urn:taxonomy:", "").replace("-", " ").replace("_", " ").title()
            elif context_name.startswith("urn:glossary:"):
                coll_type = "glossary"
                label = context_name.replace("urn:glossary:", "").replace("-", " ").replace("_", " ").title()
            elif context_name.startswith("urn:ontology:"):
                coll_type = "ontology"
                label = context_name.replace("urn:ontology:", "").replace("-", " ").replace("_", " ").title()
            elif context_name.startswith("urn:semantic-model:"):
                coll_type = "ontology"
                label = context_name.replace("urn:semantic-model:", "").replace("-", " ").replace("_", " ").title()
            else:
                coll_type = "ontology"
                # Extract label from last segment
                label = context_name.split(":")[-1].replace("-", " ").replace("_", " ").title()
            
            # Count concepts in this context
            concept_count = len(list(context.subjects(RDF.type, SKOS.Concept)))
            if concept_count == 0:
                # Also count RDFS classes
                concept_count = len(list(context.subjects(RDF.type, RDFS.Class)))
            
            logger.debug(f"Auto-registering source as collection: {context_name} ({concept_count} concepts)")
            
            # Create collection metadata triples
            coll_uri = URIRef(context_name)
            
            # Add to in-memory graph
            meta_context.add((coll_uri, RDF.type, ONTOS.KnowledgeCollection))
            meta_context.add((coll_uri, RDFS.label, Literal(label)))
            meta_context.add((coll_uri, ONTOS.collectionType, Literal(coll_type)))
            meta_context.add((coll_uri, ONTOS.scopeLevel, Literal("external")))
            meta_context.add((coll_uri, ONTOS.sourceType, Literal("imported")))
            meta_context.add((coll_uri, ONTOS.isEditable, Literal("false")))
            meta_context.add((coll_uri, ONTOS.status, Literal("active")))
            meta_context.add((coll_uri, ONTOS.createdAt, Literal(now, datatype=XSD.dateTime)))
            meta_context.add((coll_uri, ONTOS.createdBy, URIRef("urn:user:system")))
            
            # Also persist to database
            triples = [
                (context_name, str(RDF.type), str(ONTOS.KnowledgeCollection), True),
                (context_name, str(RDFS.label), label, False),
                (context_name, str(ONTOS.collectionType), coll_type, False),
                (context_name, str(ONTOS.scopeLevel), "external", False),
                (context_name, str(ONTOS.sourceType), "imported", False),
                (context_name, str(ONTOS.isEditable), "false", False),
                (context_name, str(ONTOS.status), "active", False),
                (context_name, str(ONTOS.createdAt), now, False),
                (context_name, str(ONTOS.createdBy), "urn:user:system", True),
            ]
            
            for subj, pred, obj, is_uri in triples:
                rdf_triples_repo.add_triple(
                    self._db,
                    subject_uri=subj,
                    predicate_uri=pred,
                    object_value=obj,
                    object_is_uri=is_uri,
                    context_name=META_CONTEXT,
                    source_type="collection",
                    source_identifier=context_name,
                    created_by="system",
                )
            
            registered_count += 1
        
        if registered_count > 0:
            self._db.commit()
            logger.info(f"Auto-registered {registered_count} sources as collections")

    def rebuild_graph_from_enabled(self) -> None:
        """Rebuild the in-memory RDF graph from database and dynamic sources.
        
        The database (rdf_triples table) is the source of truth for:
        - Bundled taxonomies (synced from data/taxonomies/ on startup)
        - User-uploaded ontologies
        - Demo data
        - Semantic links
        
        Dynamic sources (computed, not stored):
        - Application entities (data domains, data products, data contracts)
        - Database glossaries
        """
        logger.info("Starting to rebuild graph from database and dynamic sources")
        self._graph = ConjunctiveGraph()
        
        # Step 1: Sync bundled taxonomy files to database (idempotent)
        # This ensures any new/missing files are imported
        try:
            self._sync_bundled_taxonomies()
        except Exception as e:
            logger.error(f"Failed to sync bundled taxonomies: {e}")
        
        # Step 2: Load all triples from database into in-memory graph
        # This includes: taxonomies, user uploads, demo data, semantic links
        try:
            self._load_triples_from_db_to_graph()
        except Exception as e:
            logger.error(f"Failed to load triples from database: {e}")
        
        # Step 3: Load database-backed semantic models (legacy support)
        # These are models stored as content_text in semantic_models table
        # TODO: Migrate these to rdf_triples table as well
        items = semantic_models_repo.get_multi(self._db)
        for it in items:
            if not it.enabled:
                continue
            try:
                # Use sanitized name for human-readable context identifiers
                sanitized_name = _sanitize_context_name(it.name)
                context_name = f"urn:semantic-model:{sanitized_name}"
                context = self._graph.get_context(context_name)
                self._parse_into_graph_context(it.content_text or "", it.format, context)
                logger.debug(f"Loaded semantic model '{it.name}' into context '{context_name}'")
            except Exception as e:
                logger.warning(f"Skipping model '{it.name}' due to parse error: {e}")
        
        # Step 4: Load application entities (dynamically computed, not stored)
        try:
            self._load_app_entities_into_graph()
        except Exception as e:
            logger.warning(f"Failed to load application entities into graph: {e}")
        
        # Step 5: Load database glossaries (dynamically computed)
        self._load_database_glossaries_into_graph()
        
        # Step 6: Auto-register sources as KnowledgeCollections
        try:
            self._register_sources_as_collections()
        except Exception as e:
            logger.error(f"Failed to register sources as collections: {e}")
        
        # Step 7: Sync semantic links from entity_semantic_links table
        # This ensures any links that weren't properly dual-written to rdf_triples
        # are still present in the in-memory graph
        try:
            self._sync_entity_semantic_links_to_graph()
        except Exception as e:
            logger.warning(f"Failed to sync entity semantic links to graph: {e}")

        # Build persistent caches after graph is rebuilt
        try:
            self._build_persistent_caches_atomic()
        except Exception as e:
            logger.error(f"Failed to build persistent caches: {e}", exc_info=True)

    def _build_persistent_caches_atomic(self) -> None:
        """Build and save persistent caches atomically to disk.

        Uses atomic directory swap to prevent partial cache reads.
        Cache files are JSON-serialized for fast loading.
        """
        cache_dir = self._data_dir / "cache"
        temp_dir = self._data_dir / "cache_building"
        lock_file = self._data_dir / "cache" / "rebuild.lock"

        # Ensure lock directory exists
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Prevent concurrent cache builds
        with FileLock(str(lock_file), timeout=300):
            logger.info("Building persistent caches...")

            # Clean temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True)

            try:
                # Build all caches in temp directory
                # 1. All concepts
                logger.info("Computing all concepts for cache...")
                all_concepts = self._compute_all_concepts()
                concepts_data = [c.model_dump() for c in all_concepts]
                with open(temp_dir / "concepts_all.json", "w") as f:
                    json.dump(concepts_data, f)
                logger.info(f"Cached {len(all_concepts)} concepts")

                # 2. Taxonomies
                logger.info("Computing taxonomies for cache...")
                taxonomies = self._compute_taxonomies()
                taxonomies_data = [t.model_dump() for t in taxonomies]
                with open(temp_dir / "taxonomies.json", "w") as f:
                    json.dump(taxonomies_data, f)
                logger.info(f"Cached {len(taxonomies)} taxonomies")

                # 3. Stats (depends on concepts and taxonomies)
                logger.info("Computing stats for cache...")
                stats = self._compute_stats(all_concepts, taxonomies)
                with open(temp_dir / "stats.json", "w") as f:
                    json.dump(stats.model_dump(), f)
                logger.info("Cached stats")

                # Atomic swap: move temp files to final location
                cache_dir.mkdir(parents=True, exist_ok=True)
                for file in temp_dir.glob("*.json"):
                    final_path = cache_dir / file.name
                    # Remove old file if exists
                    if final_path.exists():
                        final_path.unlink()
                    # Move new file
                    file.rename(final_path)

                # Remove temp directory
                temp_dir.rmdir()

                # Update in-memory caches so subsequent API calls
                # see the freshly computed data immediately.
                self._cached_concepts = all_concepts
                self._cached_taxonomies = taxonomies
                self._cached_stats = stats

                logger.info("Persistent caches built successfully")

            except Exception as e:
                # Clean up temp directory on failure
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                raise

    def _compute_taxonomies(self) -> List:
        """Compute taxonomies without caching - used for building persistent cache"""
        from src.models.ontology import SemanticModel as SemanticModelOntology

        taxonomies = []

        # Check if graph has any triples
        total_triples = len(self._graph)
        context_count = len(list(self._graph.contexts()))
        logger.info(f"Graph has {total_triples} total triples and {context_count} contexts")

        # Get contexts from the graph
        for context in self._graph.contexts():
            logger.debug(f"Processing context: {context} (type: {type(context)})")

            # Get the context identifier
            if hasattr(context, 'identifier'):
                context_id = context.identifier
            else:
                logger.debug(f"Context has no identifier attribute: {context}")
                continue

            if not isinstance(context_id, URIRef):
                logger.debug(f"Context identifier is not URIRef: {context_id} ({type(context_id)})")
                continue

            context_str = str(context_id)
            logger.debug(f"Processing context with identifier: {context_str}")

            # Count concepts and properties in this context
            try:
                class_count_query = """
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                SELECT (COUNT(DISTINCT ?concept) AS ?count) WHERE {
                    {
                        ?concept a rdfs:Class .
                    } UNION {
                        ?concept a skos:Concept .
                    } UNION {
                        ?concept a skos:ConceptScheme .
                    } UNION {
                        ?concept a owl:Class .
                    } UNION {
                        # Include any resource that is used as a class (has instances or subclasses)
                        ?concept rdfs:subClassOf ?parent .
                    } UNION {
                        ?instance a ?concept .
                        FILTER(?concept != rdfs:Class && ?concept != skos:Concept && ?concept != rdf:Property && ?concept != owl:Class)
                    } UNION {
                        # Include resources with semantic properties that make them conceptual
                        ?concept rdfs:label ?someLabel .
                        ?concept rdfs:comment ?someComment .
                    }
                    # Filter out blank nodes (anonymous classes, restrictions, etc.)
                    # Note: isBlank() + also filter urn:ontos:bnode: URIs (converted blank nodes)
                    FILTER(!isBlank(?concept))
                    FILTER(!STRSTARTS(STR(?concept), "urn:ontos:bnode:"))
                    
                    # Filter out basic RDF/RDFS/SKOS/OWL vocabulary terms
                    FILTER(!STRSTARTS(STR(?concept), "http://www.w3.org/1999/02/22-rdf-syntax-ns#"))
                    FILTER(!STRSTARTS(STR(?concept), "http://www.w3.org/2000/01/rdf-schema#"))
                    FILTER(!STRSTARTS(STR(?concept), "http://www.w3.org/2004/02/skos/core#"))
                    FILTER(!STRSTARTS(STR(?concept), "http://www.w3.org/2002/07/owl#"))
                }
                """

                count_results = list(context.query(class_count_query))
                concepts_count = int(count_results[0][0]) if count_results and count_results[0][0] is not None else 0

                properties_count = len(list(context.subjects(RDF.type, RDF.Property)))

                logger.debug(f"Context {context_str}: {concepts_count} concepts, {properties_count} properties")

            except Exception as e:
                logger.warning(f"Error counting concepts in context {context_str}: {e}")
                concepts_count = 0
                properties_count = 0

            # Determine taxonomy type and name
            if context_str.startswith("urn:taxonomy:"):
                source_type = "file"
                name = context_str.replace("urn:taxonomy:", "")
                format_str = "ttl"
            elif context_str.startswith("urn:semantic-model:"):
                source_type = "database"
                name = context_str.replace("urn:semantic-model:", "")
                format_str = "rdfs"
            elif context_str.startswith("urn:schema:"):
                source_type = "schema"
                name = context_str.replace("urn:schema:", "")
                format_str = "ttl"
            elif context_str.startswith("urn:glossary:"):
                source_type = "database"
                name = context_str.replace("urn:glossary:", "")
                format_str = "rdfs"
            else:
                source_type = "external"
                name = context_str
                format_str = None

            taxonomies.append(SemanticModelOntology(
                name=name,
                description=f"{source_type.title()} taxonomy: {name}",
                source_type=source_type,
                format=format_str,
                concepts_count=concepts_count,
                properties_count=properties_count
            ))

        return sorted(taxonomies, key=lambda t: (t.source_type, t.name))

    def _compute_stats(self, all_concepts: List, taxonomies: List) -> Any:
        """Compute stats without caching - used for building persistent cache"""
        from src.models.ontology import TaxonomyStats

        total_concepts = sum(t.concepts_count for t in taxonomies)
        total_properties = sum(t.properties_count for t in taxonomies)

        # Get concepts by type
        concepts_by_type = {}
        for concept in all_concepts:
            concept_type = concept.concept_type
            concepts_by_type[concept_type] = concepts_by_type.get(concept_type, 0) + 1

        # Count top-level concepts (those without parents)
        top_level_concepts = sum(1 for concept in all_concepts if not concept.parent_concepts)

        return TaxonomyStats(
            total_concepts=total_concepts,
            total_properties=total_properties,
            taxonomies=taxonomies,
            concepts_by_type=concepts_by_type,
            top_level_concepts=top_level_concepts
        )

    # Call after create/update/delete/enable/disable
    def on_models_changed(self) -> None:
        try:
            self.rebuild_graph_from_enabled()
            # Invalidate cache when models change
            self._invalidate_cache()
        except Exception as e:
            logger.error(f"Failed to rebuild RDF graph: {e}")

    def _invalidate_cache(self) -> None:
        """Clear all cache entries (in-memory and persistent file cache)."""
        self._cache.clear()
        
        # Also delete persistent cache files so they get rebuilt on next read
        cache_dir = self._data_dir / "cache"
        if cache_dir.exists():
            for cache_file in ["concepts_all.json", "taxonomies.json", "stats.json"]:
                cache_path = cache_dir / cache_file
                if cache_path.exists():
                    try:
                        cache_path.unlink()
                        logger.debug(f"Deleted persistent cache file: {cache_file}")
                    except Exception as e:
                        logger.warning(f"Failed to delete cache file {cache_file}: {e}")
        
        logger.info("Semantic models cache invalidated (in-memory and persistent)")

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached value if still valid"""
        if key in self._cache:
            cached = self._cache[key]
            if cached.is_valid():
                logger.debug(f"Cache hit for key: {key}")
                return cached.value
            else:
                logger.debug(f"Cache expired for key: {key}")
                del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Store value in cache with TTL"""
        self._cache[key] = CachedResult(value, ttl_seconds)
        logger.debug(f"Cached value for key: {key} (TTL: {ttl_seconds}s)")

    def query(self, sparql: str, max_results: int = 1000, timeout_seconds: int = 30) -> List[dict]:
        """Execute a SPARQL query with security and safety constraints.
        
        Args:
            sparql: The SPARQL query string
            max_results: Maximum number of results to return (default: 1000)
            timeout_seconds: Query execution timeout in seconds (default: 30)
            
        Returns:
            List of result dictionaries
            
        Raises:
            ValueError: If query validation fails or execution times out
        """
        # Validate query first
        validation_error = SPARQLQueryValidator.validate(sparql)
        if validation_error:
            logger.warning(f"SPARQL query validation failed: {validation_error}")
            raise ValueError(f"Invalid SPARQL query: {validation_error}")
        
        # Log sanitized query for security auditing
        sanitized = SPARQLQueryValidator.sanitize_for_logging(sparql)
        logger.info(f"Executing validated SPARQL query: {sanitized}")
        
        results = []
        try:
            # Execute with timeout (Unix-like systems only)
            with timeout(timeout_seconds):
                qres = self._graph.query(sparql)
                
                # Limit results to prevent memory exhaustion
                for idx, row in enumerate(qres):
                    if idx >= max_results:
                        logger.warning(f"Query results truncated at {max_results} rows")
                        break
                    
                    # rdflib QueryResult rows are tuple-like
                    result_row = {}
                    for var_idx, var in enumerate(qres.vars):
                        key = str(var)
                        val = row[var_idx]
                        result_row[key] = str(val) if val is not None else None
                    results.append(result_row)
                
                logger.info(f"SPARQL query completed successfully, returned {len(results)} results")
                
        except TimeoutError:
            logger.error(f"SPARQL query timeout after {timeout_seconds} seconds")
            raise ValueError(f"Query execution timeout - query too expensive (limit: {timeout_seconds}s)")
        except Exception as e:
            logger.error(f"SPARQL query execution error: {e}", exc_info=True)
            raise ValueError(f"Query execution failed: {str(e)}")
        
        return results

    # Simple prefix search over resources and properties (case-insensitive contains)
    def prefix_search(self, prefix: str, limit: int = 20) -> List[dict]:
        q = prefix.lower()
        seen = set()
        results: List[dict] = []
        for s, p, o in self._graph:
            for term, kind in ((s, 'resource'), (p, 'property')):
                if term is None:
                    continue
                name = str(term)
                if q in name.lower() and name not in seen:
                    results.append({ 'value': name, 'type': kind })
                    seen.add(name)
                    if len(results) >= limit:
                        return results
        return results

    # Search for classes/concepts with optional text filter
    def search_concepts(self, text_filter: str = "", limit: int = 50) -> List[dict]:
        sparql_query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT DISTINCT ?class_iri ?label
        WHERE {{
            {{
                ?class_iri a rdfs:Class .
            }}
            UNION
            {{
                ?class_iri rdfs:subClassOf ?other .
            }}
            UNION
            {{
                ?class_iri a skos:Concept .
            }}
            UNION
            {{
                ?class_iri a owl:Class .
            }}
            OPTIONAL {{ ?class_iri rdfs:label ?label }}
            OPTIONAL {{ ?class_iri skos:prefLabel ?label }}
            {f'FILTER(CONTAINS(LCASE(STR(?class_iri)), LCASE("{text_filter}")) || CONTAINS(LCASE(STR(?label)), LCASE("{text_filter}")))' if text_filter.strip() else ''}
        }}
        ORDER BY ?class_iri
        LIMIT {limit}
        """
        
        try:
            raw_results = self.query(sparql_query)
            results = []
            for row in raw_results:
                class_iri = row.get('class_iri', '')
                label = row.get('label', '')
                
                # Use label if available, otherwise extract last part of IRI
                if label and label.strip():
                    display_name = label.strip()
                else:
                    # Extract the last segment after # or /
                    if '#' in class_iri:
                        display_name = class_iri.split('#')[-1]
                    elif '/' in class_iri:
                        display_name = class_iri.split('/')[-1]
                    else:
                        display_name = class_iri
                
                results.append({
                    'value': class_iri,
                    'label': display_name,
                    'type': 'class'
                })
            
            return results
        except Exception as e:
            # If SPARQL fails, fall back to empty results
            return []

    def search_properties(self, text_filter: str = "", limit: int = 50) -> List[dict]:
        """Search for properties in the semantic models using SPARQL.

        Returns:
        - OWL properties (owl:ObjectProperty, owl:DatatypeProperty)
        - RDFS properties (rdfs:Property)
        """
        sparql_query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT DISTINCT ?property_iri ?label
        WHERE {{
            {{
                ?property_iri a owl:ObjectProperty .
            }}
            UNION
            {{
                ?property_iri a owl:DatatypeProperty .
            }}
            UNION
            {{
                ?property_iri a rdfs:Property .
            }}
            OPTIONAL {{ ?property_iri rdfs:label ?label }}
            {f'FILTER(CONTAINS(LCASE(STR(?property_iri)), LCASE("{text_filter}")) || CONTAINS(LCASE(STR(?label)), LCASE("{text_filter}")))' if text_filter.strip() else ''}
        }}
        ORDER BY ?property_iri
        LIMIT {limit}
        """

        try:
            raw_results = self.query(sparql_query)
            results = []
            for row in raw_results:
                property_iri = row.get('property_iri', '')
                label = row.get('label', '')

                # Use label if available, otherwise extract last part of IRI
                if label and label.strip():
                    display_name = label.strip()
                else:
                    # Extract the last segment after # or /
                    if '#' in property_iri:
                        display_name = property_iri.split('#')[-1]
                    elif '/' in property_iri:
                        display_name = property_iri.split('/')[-1]
                    else:
                        display_name = property_iri

                results.append({
                    'value': property_iri,
                    'label': display_name,
                    'type': 'property'
                })

            return results
        except Exception as e:
            # If SPARQL fails, fall back to empty results
            return []

    def get_child_concepts(self, parent_iri: str, limit: int = 10) -> List[dict]:
        """Get child concepts of a given parent concept for suggestions."""
        if not parent_iri:
            return []
            
        try:
            parent_concept = self.get_concept_details(parent_iri)
            if not parent_concept or not parent_concept.child_concepts:
                return []
            
            # Convert child concept IRIs to the format expected by the dialog
            results = []
            for child_iri in parent_concept.child_concepts[:limit]:
                child_concept = self.get_concept_details(child_iri)
                if child_concept:
                    results.append({
                        'value': child_iri,
                        'label': child_concept.label,
                        'type': 'class'
                    })
            
            return results
        except Exception as e:
            logger.error(f"Failed to get child concepts for {parent_iri}: {e}")
            return []

    def find_best_ancestor_concept_iri(self, parent_iris: List[str]) -> str:
        """Find the first parent IRI in the hierarchy that has child concepts available."""
        if not parent_iris:
            return ""
        
        for parent_iri in parent_iris:
            if parent_iri:
                try:
                    child_concepts = self.get_child_concepts(parent_iri, limit=1)
                    if child_concepts:
                        return parent_iri
                except Exception as e:
                    logger.debug(f"Failed to get child concepts for {parent_iri}: {e}")
                    continue
        
        return ""

    def search_concepts_with_suggestions(self, text_filter: str = "", parent_iris: List[str] = None, limit: int = 50) -> dict:
        """Search for concepts with suggested child concepts first if parent_iris is provided.
        
        Args:
            text_filter: Text filter for concept search
            parent_iris: List of parent concept IRIs in hierarchy order (nearest first)
            limit: Maximum number of results to return
        """
        suggested = []
        other_results = []
        
        # Find the best parent concept from the hierarchy
        if parent_iris:
            best_parent_iri = self.find_best_ancestor_concept_iri(parent_iris)
            if best_parent_iri:
                suggested = self.get_child_concepts(best_parent_iri, limit=10)
        
        # Get all matching concepts
        all_results = self.search_concepts(text_filter, limit=limit)
        
        # Filter out suggested concepts from other results
        suggested_iris = {result['value'] for result in suggested}
        other_results = [result for result in all_results if result['value'] not in suggested_iris]
        
        return {
            'suggested': suggested,
            'other': other_results
        }

    def search_properties_with_suggestions(self, text_filter: str = "", parent_iris: List[str] = None, limit: int = 50) -> dict:
        """Search for properties with suggested child properties first if parent_iris is provided.

        Args:
            text_filter: Text filter for property search
            parent_iris: List of parent concept IRIs in hierarchy order (nearest first)
            limit: Maximum number of results to return
        """
        # For properties, we don't typically have parent-child hierarchies like concepts,
        # so we'll return empty suggestions and all properties as "other"
        suggested = []

        # Get all matching properties
        all_results = self.search_properties(text_filter, limit=limit)

        return {
            'suggested': suggested,
            'other': all_results
        }

    # Outgoing neighbors of a resource: returns distinct predicate/object pairs
    def neighbors(self, resource_iri: str, limit: int = 200) -> List[dict]:
        from rdflib import URIRef
        from rdflib.namespace import RDF
        results: List[dict] = []
        seen: set[tuple[str, str, str]] = set()  # (direction, predicate, display)
        count = 0
        uri = URIRef(resource_iri)

        def detect_type(node: any) -> str:
            if not isinstance(node, URIRef):
                return 'literal'
            try:
                for _ in self._graph.triples((None, node, None)):
                    return 'property'
            except Exception:
                pass
            try:
                for _ in self._graph.triples((node, RDF.type, RDF.Property)):
                    return 'property'
            except Exception:
                pass
            return 'resource'

        def add(direction: str, predicate, display_node, step_node):
            nonlocal count
            display_str = str(display_node)
            key = (direction, str(predicate), display_str)
            if key in seen:
                return
            seen.add(key)
            item = {
                'direction': direction,
                'predicate': str(predicate),
                'display': display_str,
                'displayType': detect_type(display_node),
                'stepIri': str(step_node) if isinstance(step_node, URIRef) else None,
                'stepIsResource': isinstance(step_node, URIRef),
            }
            results.append(item)
            count += 1

        # 1) Outgoing (uri as subject) → show object
        for _, p, o in self._graph.triples((uri, None, None)):
            if count >= limit:
                break
            add('outgoing', p, o, o)

        # 2) Incoming (uri as object) → show subject
        for s, p, _ in self._graph.triples((None, None, uri)):
            if count >= limit:
                break
            add('incoming', p, s, s)

        # 3) Predicate usage (uri as predicate) → show both subject and object entries
        for s, _, o in self._graph.triples((None, uri, None)):
            if count >= limit:
                break
            add('predicate', uri, s, s)
            if count >= limit:
                break
            add('predicate', uri, o, o)

        return results

    def get_resource_description(
        self, resource_iri: str, expand_blank_depth: int = 1
    ) -> Dict[str, Any]:
        """Get full description of a resource: all direct triples plus expanded blank nodes.

        For SHACL shapes with nested sh:property [ ... ], the blank node contents
        (path, minInclusive, etc.) are included in expanded form so the UI can show them.
        """
        from rdflib import URIRef

        uri = URIRef(resource_iri)
        triples_out: List[Dict[str, Any]] = []

        def serialize_object(obj: Any) -> tuple[str, str, Any]:
            """Return (object_value, objectType, subject_ref_for_expansion or None).
            subject_ref_for_expansion is the node to use for (node, None, None) triples.
            """
            if isinstance(obj, Literal):
                return (str(obj), "literal", None)
            if isinstance(obj, URIRef):
                # Skolemized blank nodes are stored as URIs; expand them like bnodes
                obj_str = str(obj)
                if obj_str.startswith("urn:ontos:bnode:"):
                    return (obj_str, "bnode", obj)
                return (obj_str, "uri", None)
            if isinstance(obj, BNode):
                return (str(obj), "bnode", obj)
            return (str(obj), "literal", None)

        for _s, p, o in self._graph.triples((uri, None, None)):
            obj_val, obj_type, expand_subj = serialize_object(o)
            entry: Dict[str, Any] = {
                "predicate": str(p),
                "object": obj_val,
                "objectType": obj_type,
            }
            if obj_type == "bnode" and expand_subj is not None and expand_blank_depth >= 1:
                expanded: List[Dict[str, Any]] = []
                for _bs, bp, bo in self._graph.triples((expand_subj, None, None)):
                    bo_val, bo_type, _ = serialize_object(bo)
                    expanded.append({
                        "predicate": str(bp),
                        "object": bo_val,
                        "objectType": bo_type,
                    })
                entry["expanded"] = expanded
            triples_out.append(entry)

        return {"iri": resource_iri, "triples": triples_out}

    # --- App Entities & Incremental Link Updates ---

    def _load_app_entities_into_graph(self) -> None:
        """Load core application entities into the RDF graph with labels/types.

        Adds triples into the 'urn:app-entities' named graph so they persist across rebuilds.
        """
        from sqlalchemy import text as sql_text
        from rdflib.namespace import RDF

        context = self._graph.get_context("urn:app-entities")

        # Data Domains: table data_domains(id, name)
        try:
            rows = self._db.execute(sql_text("SELECT id, name FROM data_domains")).fetchall()
            for r in rows:
                subj = URIRef(f"urn:ontos:data_domain:{r[0]}")
                context.add((subj, RDF.type, URIRef("urn:ontos:entity-type:data_domain")))
                if r[1]:
                    context.add((subj, RDFS.label, Literal(str(r[1]))))
        except Exception as e:
            logger.debug(f"Skipping data domains load into graph: {e}")

        # Data Products: ODPS v1.0.0 schema - use data_products table with id and name fields
        try:
            rows = self._db.execute(sql_text("SELECT id, name FROM data_products")).fetchall()
            for r in rows:
                subj = URIRef(f"urn:ontos:data_product:{r[0]}")
                context.add((subj, RDF.type, URIRef("urn:ontos:entity-type:data_product")))
                if r[1]:
                    context.add((subj, RDFS.label, Literal(str(r[1]))))
        except Exception as e:
            logger.debug(f"Skipping data products load into graph: {e}")

        # Data Contracts: table data_contracts(id, name)
        try:
            rows = self._db.execute(sql_text("SELECT id, name FROM data_contracts")).fetchall()
            for r in rows:
                subj = URIRef(f"urn:ontos:data_contract:{r[0]}")
                # Add both internal type and ODCS standard type
                context.add((subj, RDF.type, URIRef("urn:ontos:entity-type:data_contract")))
                context.add((subj, RDF.type, URIRef("http://odcs.bitol.io/terms#DataContract")))
                if r[1]:
                    context.add((subj, RDFS.label, Literal(str(r[1]))))
        except Exception as e:
            logger.debug(f"Skipping data contracts load into graph: {e}")

    def add_entity_semantic_link_to_graph(self, entity_type: str, entity_id: str, iri: str, created_by: Optional[str] = None) -> None:
        """Incrementally add a single semantic link triple into the graph and database.
        
        Dual-write: Updates both the in-memory graph AND persists to rdf_triples table.
        The entity_semantic_links table is the primary record (written by SemanticLinksManager),
        this ensures the triple is also in rdf_triples for graph queries.
        """
        context_name = "urn:semantic-links"
        subject_uri = f"urn:ontos:{entity_type}:{entity_id}"
        predicate_uri = str(ONTOS.semanticAssignment)
        
        # Add to in-memory graph
        try:
            context = self._graph.get_context(context_name)
            subj = URIRef(subject_uri)
            obj = URIRef(iri)
            context.add((subj, ONTOS.semanticAssignment, obj))
        except Exception as e:
            logger.warning(f"Failed to add semantic link to in-memory graph: {e}")
        
        # Persist to database (dual-write)
        try:
            rdf_triples_repo.add_triple(
                db=self._db,
                subject_uri=subject_uri,
                predicate_uri=predicate_uri,
                object_value=iri,
                object_is_uri=True,
                context_name=context_name,
                source_type='link',
                source_identifier=f"{entity_type}:{entity_id}",
                created_by=created_by,
            )
            self._db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist semantic link to database: {e}")

    def remove_entity_semantic_link_from_graph(self, entity_type: str, entity_id: str, iri: str) -> None:
        """Incrementally remove a single semantic link triple from the graph and database.
        
        Dual-write: Removes from both the in-memory graph AND rdf_triples table.
        """
        context_name = "urn:semantic-links"
        subject_uri = f"urn:ontos:{entity_type}:{entity_id}"
        predicate_uri = str(ONTOS.semanticAssignment)
        
        # Remove from in-memory graph
        try:
            context = self._graph.get_context(context_name)
            subj = URIRef(subject_uri)
            obj = URIRef(iri)
            context.remove((subj, ONTOS.semanticAssignment, obj))
        except Exception as e:
            logger.warning(f"Failed to remove semantic link from in-memory graph: {e}")
        
        # Remove from database (dual-write)
        try:
            rdf_triples_repo.remove_triple(
                db=self._db,
                subject_uri=subject_uri,
                predicate_uri=predicate_uri,
                object_value=iri,
                context_name=context_name,
            )
            self._db.commit()
        except Exception as e:
            logger.warning(f"Failed to remove semantic link from database: {e}")

    # --- New Ontology Methods ---
    
    def get_taxonomies(self) -> List[SemanticModelOntology]:
        """Get all available taxonomies/ontologies with their metadata"""
        # Prefer in-memory cache (always fresh after rebuild)
        if self._cached_taxonomies is not None:
            return self._cached_taxonomies

        # Cold start: fall back to persistent file cache
        cache_file = self._data_dir / "cache" / "taxonomies.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)
                    return [SemanticModelOntology(**item) for item in data]
            except Exception as e:
                logger.warning(f"Failed to load taxonomies from persistent cache: {e}")

        logger.warning("Persistent cache not found for taxonomies, computing live")
        taxonomies = self._compute_taxonomies()
        return taxonomies

    def _compute_all_concepts(self, taxonomy_name: str = None) -> List[OntologyConcept]:
        """Compute all concepts without caching - used for building persistent cache"""
        concepts = []

        # Determine which contexts to search
        contexts_to_search = []
        if taxonomy_name:
            # Find the specific context
            target_contexts = [
                f"urn:taxonomy:{taxonomy_name}",
                f"urn:semantic-model:{taxonomy_name}",
                f"urn:schema:{taxonomy_name}",
                f"urn:glossary:{taxonomy_name}"
            ]
            for context in self._graph.contexts():
                if hasattr(context, 'identifier') and str(context.identifier) in target_contexts:
                    contexts_to_search.append((str(context.identifier), context))
        else:
            # Search all contexts
            contexts_to_search = [(str(context.identifier), context)
                                for context in self._graph.contexts()
                                if hasattr(context, 'identifier')]

        for context_name, context in contexts_to_search:
            # Find all classes and concepts in this context
            # NOTE: Removed expensive UNION clauses that scanned all rdf:type triples
            # which caused server to hang with large triple counts (50k+)
            class_query = """
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX dcat: <http://www.w3.org/ns/dcat#>
            SELECT DISTINCT ?concept ?label ?comment WHERE {
                # Classes
                {
                    ?concept a rdfs:Class .
                } UNION {
                    ?concept a owl:Class .
                } UNION {
                    ?concept rdfs:subClassOf ?parent .
                }
                # SKOS Concepts
                UNION {
                    ?concept a skos:Concept .
                } UNION {
                    ?concept a skos:ConceptScheme .
                }
                # Properties (all types)
                UNION {
                    ?concept a rdf:Property .
                } UNION {
                    ?concept a owl:ObjectProperty .
                } UNION {
                    ?concept a owl:DatatypeProperty .
                } UNION {
                    ?concept a owl:AnnotationProperty .
                } UNION {
                    ?concept rdfs:subPropertyOf ?parentProp .
                }
                # Individuals (named instances)
                UNION {
                    ?concept a owl:NamedIndividual .
                }
                # Extract labels with priority: skos:prefLabel > rdfs:label
                OPTIONAL { ?concept skos:prefLabel ?skos_pref_label }
                OPTIONAL { ?concept rdfs:label ?rdfs_label }
                BIND(COALESCE(STR(?skos_pref_label), STR(?rdfs_label)) AS ?label)

                # Extract comments/definitions with priority: skos:definition > rdfs:comment
                OPTIONAL { ?concept skos:definition ?skos_definition }
                OPTIONAL { ?concept rdfs:comment ?rdfs_comment }
                BIND(COALESCE(STR(?skos_definition), STR(?rdfs_comment)) AS ?comment)

                # Filter out blank nodes (anonymous classes, restrictions, etc.)
                # Note: isBlank() + also filter urn:ontos:bnode: URIs (converted blank nodes)
                FILTER(!isBlank(?concept))
                FILTER(!STRSTARTS(STR(?concept), "urn:ontos:bnode:"))
                
                # Filter out basic RDF/RDFS/SKOS/OWL vocabulary terms
                FILTER(!STRSTARTS(STR(?concept), "http://www.w3.org/1999/02/22-rdf-syntax-ns#"))
                FILTER(!STRSTARTS(STR(?concept), "http://www.w3.org/2000/01/rdf-schema#"))
                FILTER(!STRSTARTS(STR(?concept), "http://www.w3.org/2004/02/skos/core#"))
                FILTER(!STRSTARTS(STR(?concept), "http://www.w3.org/2002/07/owl#"))
            }
            ORDER BY ?concept
            """

            try:
                results = context.query(class_query)
                results_list = list(results)
                logger.debug(f"SPARQL query returned {len(results_list)} results for context {context_name}")

                # First pass: collect unique concept IRIs to avoid duplicates from multi-label results
                seen_iris = set()
                unique_concept_iris = []
                for row in results_list:
                    try:
                        if hasattr(row, 'concept'):
                            concept_iri = str(row.concept)
                        else:
                            concept_iri = str(row[0]) if len(row) > 0 else None
                    except Exception:
                        continue
                    if concept_iri and concept_iri not in seen_iris:
                        seen_iris.add(concept_iri)
                        unique_concept_iris.append(concept_iri)
                
                logger.debug(f"Processing {len(unique_concept_iris)} unique concepts (from {len(results_list)} SPARQL rows)")

                # Second pass: process each unique concept
                for concept_iri in unique_concept_iris:
                    concept_uri = URIRef(concept_iri)

                    # Build labels dictionary from all available labels with language tags
                    labels = {}
                    # Get skos:prefLabel values (preferred)
                    for label_literal in context.objects(concept_uri, SKOS.prefLabel):
                        lang = getattr(label_literal, 'language', None) or ""
                        labels[lang] = str(label_literal)
                    # Get rdfs:label values (fallback, don't overwrite prefLabel)
                    for label_literal in context.objects(concept_uri, RDFS.label):
                        lang = getattr(label_literal, 'language', None) or ""
                        if lang not in labels:
                            labels[lang] = str(label_literal)
                    
                    # Helper to find label by language with regional variant support (en-US, en-GB -> en)
                    def find_by_lang(d: dict, lang: str) -> str | None:
                        if lang in d:
                            return d[lang]
                        # Try regional variants (e.g., 'en' matches 'en-US', 'en-GB')
                        prefix = lang + '-'
                        for k, v in d.items():
                            if k.startswith(prefix):
                                return v
                        return None
                    
                    # Compute primary label with fallback chain: en/en-* > "" (no lang) > any > IRI local name
                    primary_label = (
                        find_by_lang(labels, 'en') or
                        labels.get('') or
                        (next(iter(labels.values()), None) if labels else None) or
                        concept_iri.split('#')[-1].split('/')[-1]
                    )

                    # Build comments dictionary from all available definitions/comments with language tags
                    comments = {}
                    # Get skos:definition values (preferred)
                    for def_literal in context.objects(concept_uri, SKOS.definition):
                        lang = getattr(def_literal, 'language', None) or ""
                        comments[lang] = str(def_literal)
                    # Get rdfs:comment values (fallback, don't overwrite definition)
                    for comment_literal in context.objects(concept_uri, RDFS.comment):
                        lang = getattr(comment_literal, 'language', None) or ""
                        if lang not in comments:
                            comments[lang] = str(comment_literal)
                    
                    # Compute primary comment with same fallback chain as labels
                    comment = (
                        find_by_lang(comments, 'en') or
                        comments.get('') or
                        (next(iter(comments.values()), None) if comments else None)
                    )

                    # Determine concept type with comprehensive type checking
                    # Check for classes first
                    if (concept_uri, RDF.type, RDFS.Class) in context:
                        concept_type = "class"
                    elif (concept_uri, RDF.type, OWL.Class) in context:
                        concept_type = "class"
                    # Check for SKOS concepts
                    elif (concept_uri, RDF.type, SKOS.Concept) in context:
                        concept_type = "concept"
                    elif (concept_uri, RDF.type, SKOS.ConceptScheme) in context:
                        concept_type = "concept"
                    # Check for all property types
                    elif (concept_uri, RDF.type, RDF.Property) in context:
                        concept_type = "property"
                    elif (concept_uri, RDF.type, OWL.ObjectProperty) in context:
                        concept_type = "property"
                    elif (concept_uri, RDF.type, OWL.DatatypeProperty) in context:
                        concept_type = "property"
                    elif (concept_uri, RDF.type, OWL.AnnotationProperty) in context:
                        concept_type = "property"
                    # Check if it has subPropertyOf (inherited property)
                    elif any(context.objects(concept_uri, RDFS.subPropertyOf)):
                        concept_type = "property"
                    # Check if it has subClassOf but wasn't caught above (inherited class)
                    elif any(context.objects(concept_uri, RDFS.subClassOf)):
                        concept_type = "class"
                    # Check if it has owl:equivalentClass (defined class)
                    elif any(context.objects(concept_uri, OWL.equivalentClass)):
                        concept_type = "class"
                    # Named individuals
                    elif (concept_uri, RDF.type, OWL.NamedIndividual) in context:
                        concept_type = "individual"
                    else:
                        concept_type = "individual"

                    # Get parent concepts/properties
                    parent_concepts = []
                    # Handle rdfs:subClassOf relationships (class-to-class)
                    for parent in context.objects(concept_uri, RDFS.subClassOf):
                        parent_str = str(parent)
                        if not isinstance(parent, BNode) and not self._is_skolemized_bnode(parent_str):
                            parent_concepts.append(parent_str)
                    # Handle owl:equivalentClass + owl:intersectionOf (A ≡ B ∩ C implies A ⊑ B)
                    for parent_iri in self._extract_parents_from_owl_equivalent_class(context, concept_uri):
                        if parent_iri not in parent_concepts:
                            parent_concepts.append(parent_iri)
                    # Handle rdfs:subPropertyOf relationships (property-to-property)
                    for parent in context.objects(concept_uri, RDFS.subPropertyOf):
                        parent_str = str(parent)
                        if not isinstance(parent, BNode) and not self._is_skolemized_bnode(parent_str):
                            parent_concepts.append(parent_str)
                    # Handle SKOS broader relationships
                    for parent in context.objects(concept_uri, SKOS.broader):
                        parent_concepts.append(str(parent))
                    # Handle rdf:type relationships (instance-to-class)
                    for parent_type in context.objects(concept_uri, RDF.type):
                        # Only include custom types, not basic RDF/RDFS/SKOS/OWL types
                        parent_type_str = str(parent_type)
                        if not any(parent_type_str.startswith(prefix) for prefix in [
                            "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                            "http://www.w3.org/2000/01/rdf-schema#",
                            "http://www.w3.org/2004/02/skos/core#",
                            "http://www.w3.org/2002/07/owl#"
                        ]):
                            parent_concepts.append(parent_type_str)

                    # Extract source context name
                    source_context = None
                    if context_name.startswith("urn:taxonomy:"):
                        source_context = context_name.replace("urn:taxonomy:", "")
                    elif context_name.startswith("urn:semantic-model:"):
                        source_context = context_name.replace("urn:semantic-model:", "")
                    elif context_name.startswith("urn:schema:"):
                        source_context = context_name.replace("urn:schema:", "")
                    elif context_name.startswith("urn:glossary:"):
                        source_context = context_name.replace("urn:glossary:", "")
                    elif context_name.startswith("urn:demo"):
                        source_context = "Demo Data"
                    elif context_name.startswith("urn:app-entities"):
                        source_context = "Application Entities"

                    # For properties, extract domain/range
                    domain_val = None
                    range_val = None
                    if concept_type == "property":
                        domains = list(context.objects(concept_uri, RDFS.domain))
                        domains = [d for d in domains if not isinstance(d, BNode) and not self._is_skolemized_bnode(str(d))]
                        domain_val = str(domains[0]) if domains else None
                        ranges = list(context.objects(concept_uri, RDFS.range))
                        ranges = [r for r in ranges if not isinstance(r, BNode) and not self._is_skolemized_bnode(str(r))]
                        range_val = str(ranges[0]) if ranges else None

                    # Extract related concepts (skos:related)
                    related_concepts = [str(r) for r in context.objects(concept_uri, SKOS.related)]

                    concepts.append(OntologyConcept(
                        iri=concept_iri,
                        label=primary_label,
                        labels=labels,
                        comment=comment,
                        comments=comments,
                        concept_type=concept_type,
                        source_context=source_context,
                        parent_concepts=parent_concepts,
                        domain=domain_val,
                        range=range_val,
                        related_concepts=related_concepts
                    ))
            except Exception as e:
                logger.warning(f"Failed to query concepts in context {context_name}: {e}")

        # Second pass: populate child_concepts using O(n) dictionary lookup
        concept_map = {concept.iri: concept for concept in concepts}
        for concept in concepts:
            # For each parent of this concept, add this concept as a child
            for parent_iri in concept.parent_concepts:
                if parent_iri in concept_map:
                    parent_concept = concept_map[parent_iri]
                    if concept.iri not in parent_concept.child_concepts:
                        parent_concept.child_concepts.append(concept.iri)

        return concepts

    def get_concepts_by_taxonomy(self, taxonomy_name: str = None) -> List[OntologyConcept]:
        """Get concepts, optionally filtered by taxonomy"""
        # Check cache first
        cache_key = f"concepts_by_taxonomy:{taxonomy_name or 'all'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Compute concepts
        concepts = self._compute_all_concepts(taxonomy_name)

        # Cache for 5 minutes
        self._set_cached(cache_key, concepts, ttl_seconds=300)
        return concepts
    
    def get_concept_details(self, concept_iri: str) -> Optional[OntologyConcept]:
        """Get detailed information about a specific concept"""
        concept = None
        
        # Search all contexts for this concept
        for context in self._graph.contexts():
            if not hasattr(context, 'identifier'):
                continue
            context_id = context.identifier
            context_name = str(context_id)
            
            # Check if concept exists in this context
            concept_uri = URIRef(concept_iri)
            if (concept_uri, None, None) not in context:
                continue
            
            # Get basic info
            labels = list(context.objects(concept_uri, RDFS.label))
            labels.extend(list(context.objects(concept_uri, SKOS.prefLabel)))
            label = str(labels[0]) if labels else None
            
            comments = list(context.objects(concept_uri, RDFS.comment))  
            comments.extend(list(context.objects(concept_uri, SKOS.definition)))
            comment = str(comments[0]) if comments else None
            
            # Determine type
            concept_type = "individual"  # default
            if (concept_uri, RDF.type, RDFS.Class) in context:
                concept_type = "class"
            elif (concept_uri, RDF.type, SKOS.Concept) in context:
                concept_type = "concept"
            
            # Get parent concepts
            parent_concepts = []
            # Handle rdfs:subClassOf relationships (class-to-class)
            for parent in context.objects(concept_uri, RDFS.subClassOf):
                parent_str = str(parent)
                if not isinstance(parent, BNode) and not self._is_skolemized_bnode(parent_str):
                    parent_concepts.append(parent_str)
            # Handle owl:equivalentClass + owl:intersectionOf (A ≡ B ∩ C implies A ⊑ B)
            for parent_iri in self._extract_parents_from_owl_equivalent_class(context, concept_uri):
                if parent_iri not in parent_concepts:
                    parent_concepts.append(parent_iri)
            # Handle SKOS broader relationships
            for parent in context.objects(concept_uri, SKOS.broader):
                parent_concepts.append(str(parent))
            # Handle rdf:type relationships (instance-to-class)
            for parent_type in context.objects(concept_uri, RDF.type):
                # Only include custom types, not basic RDF/RDFS/SKOS types
                parent_type_str = str(parent_type)
                if not any(parent_type_str.startswith(prefix) for prefix in [
                    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                    "http://www.w3.org/2000/01/rdf-schema#", 
                    "http://www.w3.org/2004/02/skos/core#"
                ]):
                    parent_concepts.append(parent_type_str)
            
            # Get child concepts
            child_concepts = []
            # Handle rdfs:subClassOf relationships (find classes that are subclasses of this one)
            for child in context.subjects(RDFS.subClassOf, concept_uri):
                child_str = str(child)
                if not isinstance(child, BNode) and not self._is_skolemized_bnode(child_str):
                    child_concepts.append(child_str)
            # Handle owl:equivalentClass + owl:intersectionOf (if B ≡ A ∩ ..., B is a child of A)
            for child_iri in self._find_children_via_owl_equivalent_class(context, concept_uri):
                if child_iri not in child_concepts:
                    child_concepts.append(child_iri)
            # Handle SKOS narrower relationships
            for child in context.subjects(SKOS.broader, concept_uri):
                child_concepts.append(str(child))
            # Handle rdf:type relationships (find instances of this class)
            for child in context.subjects(RDF.type, concept_uri):
                child_concepts.append(str(child))
            
            # Extract source context
            source_context = None
            if context_name.startswith("urn:taxonomy:"):
                source_context = context_name.replace("urn:taxonomy:", "")
            elif context_name.startswith("urn:semantic-model:"):
                source_context = context_name.replace("urn:semantic-model:", "")
            elif context_name.startswith("urn:schema:"):
                source_context = context_name.replace("urn:schema:", "")
            elif context_name.startswith("urn:glossary:"):
                source_context = context_name.replace("urn:glossary:", "")
            elif context_name.startswith("urn:demo"):
                source_context = "Demo Data"
            elif context_name.startswith("urn:app-entities"):
                source_context = "Application Entities"
            
            concept = OntologyConcept(
                iri=concept_iri,
                label=label,
                comment=comment,
                concept_type=concept_type,
                source_context=source_context,
                parent_concepts=parent_concepts,
                child_concepts=child_concepts
            )
            break  # Found in first matching context
        
        return concept
    
    def get_concept_hierarchy(self, concept_iri: str) -> Optional[ConceptHierarchy]:
        """Get hierarchical relationships for a concept"""
        concept = self.get_concept_details(concept_iri)
        if not concept:
            return None
        
        # Get ancestors (recursive parent lookup)
        ancestors = []
        visited = set()
        
        def get_ancestors_recursive(iri: str):
            if iri in visited:
                return
            visited.add(iri)
            
            parent_concept = self.get_concept_details(iri)
            if not parent_concept:
                return
                
            for parent_iri in parent_concept.parent_concepts:
                parent = self.get_concept_details(parent_iri)
                if parent and parent not in ancestors:
                    ancestors.append(parent)
                    get_ancestors_recursive(parent_iri)
        
        for parent_iri in concept.parent_concepts:
            get_ancestors_recursive(parent_iri)
        
        # Get descendants (recursive child lookup)
        descendants = []
        visited = set()
        
        def get_descendants_recursive(iri: str):
            if iri in visited:
                return
            visited.add(iri)
            
            child_concept = self.get_concept_details(iri)
            if not child_concept:
                return
                
            for child_iri in child_concept.child_concepts:
                child = self.get_concept_details(child_iri)
                if child and child not in descendants:
                    descendants.append(child)
                    get_descendants_recursive(child_iri)
        
        for child_iri in concept.child_concepts:
            get_descendants_recursive(child_iri)
        
        # Get siblings (concepts that share the same parents)
        siblings = []
        if concept.parent_concepts:
            for parent_iri in concept.parent_concepts:
                parent = self.get_concept_details(parent_iri)
                if parent:
                    for sibling_iri in parent.child_concepts:
                        if sibling_iri != concept_iri:
                            sibling = self.get_concept_details(sibling_iri)
                            if sibling and sibling not in siblings:
                                siblings.append(sibling)
        
        return ConceptHierarchy(
            concept=concept,
            ancestors=ancestors,
            descendants=descendants,
            siblings=siblings
        )
    
    def search_ontology_concepts(self, query: str, taxonomy_name: str = None, limit: int = 50) -> List[ConceptSearchResult]:
        """Search for concepts by text query"""
        results = []
        
        # Get concepts to search through
        concepts = self.get_concepts_by_taxonomy(taxonomy_name)
        
        query_lower = query.lower()
        
        for concept in concepts:
            score = 0.0
            match_type = None
            
            # Check label match
            if concept.label and query_lower in concept.label.lower():
                score += 10.0
                match_type = 'label'
                # Exact match gets higher score
                if concept.label.lower() == query_lower:
                    score += 20.0
            
            # Check comment/description match
            if concept.comment and query_lower in concept.comment.lower():
                score += 5.0
                if not match_type:
                    match_type = 'comment'
            
            # Check IRI match
            if query_lower in concept.iri.lower():
                score += 3.0
                if not match_type:
                    match_type = 'iri'
            
            if score > 0:
                results.append(ConceptSearchResult(
                    concept=concept,
                    relevance_score=score,
                    match_type=match_type or 'iri'
                ))
        
        # Sort by relevance score (descending)
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        
        return results[:limit]
    
    def get_taxonomy_stats(self) -> TaxonomyStats:
        """Get statistics about loaded taxonomies"""
        # Prefer in-memory cache (always fresh after rebuild)
        if self._cached_stats is not None:
            return self._cached_stats

        # Cold start: fall back to persistent file cache
        cache_file = self._data_dir / "cache" / "stats.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)
                    return TaxonomyStats(**data)
            except Exception as e:
                logger.warning(f"Failed to load stats from persistent cache: {e}")

        logger.warning("Persistent cache not found for stats, computing live")
        taxonomies = self.get_taxonomies()
        all_concepts = self.get_concepts_by_taxonomy()
        stats = self._compute_stats(all_concepts, taxonomies)
        return stats

    def get_grouped_concepts(self) -> Dict[str, List[OntologyConcept]]:
        """Return all concepts grouped by their source context name.

        Group key is derived from OntologyConcept.source_context, or 'Unassigned' when missing.
        Concepts in each group are sorted by label (fallback to IRI).
        """
        # Prefer in-memory cache (always fresh after rebuild)
        if self._cached_concepts is not None:
            concepts = self._cached_concepts
        else:
            # Cold start: fall back to persistent file cache
            cache_file = self._data_dir / "cache" / "concepts_all.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r") as f:
                        data = json.load(f)
                        concepts = [OntologyConcept(**item) for item in data]
                except Exception as e:
                    logger.warning(f"Failed to load concepts from persistent cache: {e}")
                    concepts = self.get_concepts_by_taxonomy()
            else:
                logger.warning("Persistent cache not found for concepts, computing live")
                concepts = self.get_concepts_by_taxonomy()

        # Group concepts by source_context
        grouped: Dict[str, List[OntologyConcept]] = {}
        for concept in concepts:
            source = concept.source_context or "Unassigned"
            if source not in grouped:
                grouped[source] = []
            grouped[source].append(concept)

        # Sort concepts within each group
        for source in grouped:
            grouped[source].sort(key=lambda c: (c.label or c.iri))

        return grouped

    def get_properties_grouped(self) -> Dict[str, List[Dict[str, Any]]]:
        """Return all RDF/OWL properties grouped by their source context name.

        Queries owl:ObjectProperty, owl:DatatypeProperty, rdfs:Property from each
        context in the graph and returns them with source_context for grouping.

        Each property is returned as a dict with:
        - iri: The property IRI
        - label: Human-readable label
        - concept_type: Always "property" for tree compatibility
        - property_type: "object", "datatype", or "annotation"
        - domain: Domain class IRI (optional)
        - range: Range class/datatype IRI (optional)
        - comment: Description (optional)
        - source_context: The source taxonomy name
        - parent_concepts: Empty list for tree compatibility
        - child_concepts: Empty list for tree compatibility
        """
        grouped: Dict[str, List[Dict[str, Any]]] = {}

        for context in self._graph.contexts():
            if not hasattr(context, 'identifier'):
                continue
            context_id = context.identifier
            if not isinstance(context_id, URIRef):
                continue
            context_name = str(context_id)

            # Extract source context name (same logic as concepts)
            source_context = None
            if context_name.startswith("urn:taxonomy:"):
                source_context = context_name.replace("urn:taxonomy:", "")
            elif context_name.startswith("urn:semantic-model:"):
                source_context = context_name.replace("urn:semantic-model:", "")
            elif context_name.startswith("urn:schema:"):
                source_context = context_name.replace("urn:schema:", "")
            elif context_name.startswith("urn:glossary:"):
                source_context = context_name.replace("urn:glossary:", "")
            elif context_name.startswith("urn:demo"):
                source_context = "Demo Data"
            elif context_name.startswith("urn:app-entities"):
                source_context = "Application Entities"

            if not source_context:
                source_context = "Unassigned"

            # Query properties in this context
            try:
                # Find all property types
                properties_found = set()

                # owl:ObjectProperty
                for prop_uri in context.subjects(RDF.type, OWL.ObjectProperty):
                    properties_found.add((str(prop_uri), "object"))

                # owl:DatatypeProperty
                for prop_uri in context.subjects(RDF.type, OWL.DatatypeProperty):
                    properties_found.add((str(prop_uri), "datatype"))

                # owl:AnnotationProperty
                for prop_uri in context.subjects(RDF.type, OWL.AnnotationProperty):
                    properties_found.add((str(prop_uri), "annotation"))

                # rdfs:Property (generic)
                for prop_uri in context.subjects(RDF.type, RDF.Property):
                    # Only add if not already typed more specifically
                    prop_str = str(prop_uri)
                    if not any(prop_str == p[0] for p in properties_found):
                        properties_found.add((prop_str, "datatype"))  # Default to datatype

                for prop_iri, property_type in properties_found:
                    # Skip standard vocabulary properties
                    if any(prop_iri.startswith(prefix) for prefix in [
                        "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                        "http://www.w3.org/2000/01/rdf-schema#",
                        "http://www.w3.org/2004/02/skos/core#",
                        "http://www.w3.org/2002/07/owl#"
                    ]):
                        continue

                    prop_uri = URIRef(prop_iri)

                    # Build labels dictionary with all language variants
                    labels_dict = {}
                    # Get skos:prefLabel values (preferred)
                    for label_literal in context.objects(prop_uri, SKOS.prefLabel):
                        lang = getattr(label_literal, 'language', None) or ""
                        labels_dict[lang] = str(label_literal)
                    # Get rdfs:label values (fallback, don't overwrite prefLabel)
                    for label_literal in context.objects(prop_uri, RDFS.label):
                        lang = getattr(label_literal, 'language', None) or ""
                        if lang not in labels_dict:
                            labels_dict[lang] = str(label_literal)
                    
                    # Helper to find label by language with regional variant support
                    def find_by_lang(d: dict, lang: str) -> str | None:
                        if lang in d:
                            return d[lang]
                        prefix = lang + '-'
                        for k, v in d.items():
                            if k.startswith(prefix):
                                return v
                        return None
                    
                    # Compute primary label with fallback chain: en > "" (no lang) > any > IRI local name
                    primary_label = (
                        find_by_lang(labels_dict, 'en') or
                        labels_dict.get('') or
                        (next(iter(labels_dict.values()), None) if labels_dict else None) or
                        prop_iri.split('#')[-1].split('/')[-1]
                    )

                    # Build comments dictionary with all language variants
                    comments_dict = {}
                    # Get skos:definition values (preferred)
                    for def_literal in context.objects(prop_uri, SKOS.definition):
                        lang = getattr(def_literal, 'language', None) or ""
                        comments_dict[lang] = str(def_literal)
                    # Get rdfs:comment values (fallback, don't overwrite definition)
                    for comment_literal in context.objects(prop_uri, RDFS.comment):
                        lang = getattr(comment_literal, 'language', None) or ""
                        if lang not in comments_dict:
                            comments_dict[lang] = str(comment_literal)
                    
                    # Compute primary comment with fallback chain
                    primary_comment = (
                        find_by_lang(comments_dict, 'en') or
                        comments_dict.get('') or
                        (next(iter(comments_dict.values()), None) if comments_dict else None)
                    )

                    # Get domain
                    domains = list(context.objects(prop_uri, RDFS.domain))
                    domain = str(domains[0]) if domains else None

                    # Get range
                    ranges = list(context.objects(prop_uri, RDFS.range))
                    range_val = str(ranges[0]) if ranges else None

                    # Get parent properties via rdfs:subPropertyOf
                    parent_properties = []
                    for parent in context.objects(prop_uri, RDFS.subPropertyOf):
                        parent_str = str(parent)
                        # Skip OWL top properties and standard vocabulary
                        if not any(parent_str.startswith(prefix) for prefix in [
                            "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                            "http://www.w3.org/2000/01/rdf-schema#",
                            "http://www.w3.org/2004/02/skos/core#",
                            "http://www.w3.org/2002/07/owl#"
                        ]):
                            parent_properties.append(parent_str)

                    # Build property dict compatible with concept structure
                    prop_dict = {
                        "iri": prop_iri,
                        "label": primary_label,
                        "labels": labels_dict,  # All labels with language tags
                        "comment": primary_comment,
                        "comments": comments_dict,  # All comments with language tags
                        "concept_type": "property",  # For tree compatibility
                        "property_type": property_type,
                        "domain": domain,
                        "range": range_val,
                        "source_context": source_context,
                        "parent_concepts": parent_properties,
                        "child_concepts": [],  # Populated in second pass below
                        "tagged_assets": [],
                    }

                    if source_context not in grouped:
                        grouped[source_context] = []
                    grouped[source_context].append(prop_dict)

            except Exception as e:
                logger.warning(f"Failed to query properties in context {context_name}: {e}")

        # Second pass: populate child_concepts based on parent relationships
        # Build a flat map of all properties by IRI for O(n) lookup
        all_properties: Dict[str, Dict[str, Any]] = {}
        for source_props in grouped.values():
            for prop in source_props:
                all_properties[prop["iri"]] = prop

        # For each property, add it as a child to its parents
        for prop in all_properties.values():
            for parent_iri in prop["parent_concepts"]:
                if parent_iri in all_properties:
                    parent_prop = all_properties[parent_iri]
                    if prop["iri"] not in parent_prop["child_concepts"]:
                        parent_prop["child_concepts"].append(prop["iri"])

        # Sort properties within each group
        for source in grouped:
            grouped[source].sort(key=lambda p: (p.get("label") or p.get("iri")))

        return grouped

    # ========================================================================
    # KNOWLEDGE COLLECTION CRUD
    # ========================================================================

    def get_collections(self) -> List[Dict[str, Any]]:
        """Get all knowledge collections with hierarchy information.
        
        Collections are stored as triples in the urn:meta:sources context.
        Returns a flat list; use parent_collection_iri to build hierarchy.
        """
        from src.models.ontology import KnowledgeCollection, CollectionType, ScopeLevel, SourceType
        
        META_CONTEXT = "urn:meta:sources"
        collections = []
        
        # Get all concepts grouped by source_context for efficient counting
        # This uses the comprehensive SPARQL query that properly unions all concept types
        grouped_concepts = self.get_grouped_concepts()
        
        # Query all Collection instances from the meta context
        try:
            context = self._graph.get_context(URIRef(META_CONTEXT))
            
            # Find all subjects that are ontos:KnowledgeCollection
            collection_iris = set()
            for subj in context.subjects(RDF.type, ONTOS.KnowledgeCollection):
                collection_iris.add(str(subj))
            
            for coll_iri in collection_iris:
                coll_uri = URIRef(coll_iri)
                
                # Extract properties
                label = self._get_literal(context, coll_uri, RDFS.label)
                description = self._get_literal(context, coll_uri, RDFS.comment)
                coll_type = self._get_literal(context, coll_uri, ONTOS.collectionType) or "glossary"
                scope = self._get_literal(context, coll_uri, ONTOS.scopeLevel) or "enterprise"
                source_type = self._get_literal(context, coll_uri, ONTOS.sourceType) or "custom"
                source_url = self._get_literal(context, coll_uri, ONTOS.sourceUrl)
                parent_iri = self._get_uri(context, coll_uri, ONTOS.parentCollection)
                is_editable = self._get_literal(context, coll_uri, ONTOS.isEditable)
                status = self._get_literal(context, coll_uri, ONTOS.status) or "active"
                created_at = self._get_literal(context, coll_uri, ONTOS.createdAt)
                created_by = self._get_uri(context, coll_uri, ONTOS.createdBy)
                
                # Count concepts using the grouped concepts data
                # Collection IRI: "urn:glossary:enterprise-glossary" -> suffix: "enterprise-glossary"
                # Concept source_context is already the suffix (e.g., "enterprise-glossary")
                coll_suffix = coll_iri.split(":")[-1]
                concept_count = len(grouped_concepts.get(coll_suffix, []))
                
                collections.append({
                    "iri": coll_iri,
                    "label": label or coll_iri.split(":")[-1],
                    "description": description,
                    "collection_type": coll_type,
                    "scope_level": scope,
                    "source_type": source_type,
                    "source_url": source_url,
                    "parent_collection_iri": parent_iri,
                    "is_editable": is_editable in ("true", "True", True, "1"),
                    "status": status,
                    "created_at": created_at,
                    "created_by": created_by,
                    "concept_count": concept_count,
                })
        except Exception as e:
            logger.warning(f"Failed to query collections: {e}")
        
        # Sort by scope level and label
        scope_order = {"enterprise": 0, "domain": 1, "department": 2, "team": 3, "project": 4, "external": 5}
        collections.sort(key=lambda c: (scope_order.get(c.get("scope_level", ""), 99), c.get("label", "")))
        
        return collections

    def get_collection(self, collection_iri: str) -> Optional[Dict[str, Any]]:
        """Get a single collection by IRI."""
        collections = self.get_collections()
        for coll in collections:
            if coll["iri"] == collection_iri:
                return coll
        return None

    def create_collection(
        self,
        label: str,
        collection_type: str = "glossary",
        scope_level: str = "enterprise",
        description: Optional[str] = None,
        parent_collection_iri: Optional[str] = None,
        is_editable: bool = True,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new knowledge collection.
        
        Creates triples in the urn:meta:sources context and an empty context
        for the collection's concepts.
        """
        from datetime import datetime
        
        META_CONTEXT = "urn:meta:sources"
        
        # Generate IRI from label
        sanitized = _sanitize_context_name(label.lower().replace(" ", "-"))
        prefix = "urn:glossary:" if collection_type == "glossary" else \
                 "urn:taxonomy:" if collection_type == "taxonomy" else "urn:ontology:"
        collection_iri = f"{prefix}{sanitized}"
        
        # Check if already exists
        existing = self.get_collection(collection_iri)
        if existing:
            raise ValueError(f"Collection already exists: {collection_iri}")
        
        # Create triples for the collection metadata
        now = datetime.utcnow().isoformat() + "Z"
        triples = [
            (collection_iri, str(RDF.type), str(ONTOS.KnowledgeCollection), True),
            (collection_iri, str(RDFS.label), label, False),
            (collection_iri, str(ONTOS.collectionType), collection_type, False),
            (collection_iri, str(ONTOS.scopeLevel), scope_level, False),
            (collection_iri, str(ONTOS.sourceType), "custom", False),
            (collection_iri, str(ONTOS.isEditable), str(is_editable).lower(), False),
            (collection_iri, str(ONTOS.status), "active", False),
            (collection_iri, str(ONTOS.createdAt), now, False),
        ]
        
        if description:
            triples.append((collection_iri, str(RDFS.comment), description, False))
        if parent_collection_iri:
            triples.append((collection_iri, str(ONTOS.parentCollection), parent_collection_iri, True))
        if created_by:
            user_uri = f"urn:user:{created_by}" if not created_by.startswith("urn:") else created_by
            triples.append((collection_iri, str(ONTOS.createdBy), user_uri, True))
        
        # Add to database
        for subj, pred, obj, is_uri in triples:
            rdf_triples_repo.add_triple(
                self._db,
                subject_uri=subj,
                predicate_uri=pred,
                object_value=obj,
                object_is_uri=is_uri,
                context_name=META_CONTEXT,
                source_type="collection",
                source_identifier=collection_iri,
                created_by=created_by,
            )
        
        # Also add to in-memory graph
        meta_context = self._graph.get_context(URIRef(META_CONTEXT))
        coll_uri = URIRef(collection_iri)
        meta_context.add((coll_uri, RDF.type, ONTOS.KnowledgeCollection))
        meta_context.add((coll_uri, RDFS.label, Literal(label)))
        meta_context.add((coll_uri, ONTOS.collectionType, Literal(collection_type)))
        meta_context.add((coll_uri, ONTOS.scopeLevel, Literal(scope_level)))
        meta_context.add((coll_uri, ONTOS.sourceType, Literal("custom")))
        meta_context.add((coll_uri, ONTOS.isEditable, Literal(str(is_editable).lower())))
        meta_context.add((coll_uri, ONTOS.status, Literal("active")))
        meta_context.add((coll_uri, ONTOS.createdAt, Literal(now, datatype=XSD.dateTime)))
        if description:
            meta_context.add((coll_uri, RDFS.comment, Literal(description)))
        if parent_collection_iri:
            meta_context.add((coll_uri, ONTOS.parentCollection, URIRef(parent_collection_iri)))
        if created_by:
            user_uri = f"urn:user:{created_by}" if not created_by.startswith("urn:") else created_by
            meta_context.add((coll_uri, ONTOS.createdBy, URIRef(user_uri)))
        
        self._db.commit()
        self._invalidate_cache()
        
        return self.get_collection(collection_iri)

    def update_collection(
        self,
        collection_iri: str,
        label: Optional[str] = None,
        description: Optional[str] = None,
        scope_level: Optional[str] = None,
        parent_collection_iri: Optional[str] = None,
        is_editable: Optional[bool] = None,
        updated_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a knowledge collection's metadata."""
        from datetime import datetime
        
        META_CONTEXT = "urn:meta:sources"
        
        existing = self.get_collection(collection_iri)
        if not existing:
            return None
        
        coll_uri = URIRef(collection_iri)
        meta_context = self._graph.get_context(URIRef(META_CONTEXT))
        now = datetime.utcnow().isoformat() + "Z"
        
        updates = []
        if label is not None:
            # Remove old, add new
            rdf_triples_repo.remove_by_subject_predicate(self._db, collection_iri, str(RDFS.label), META_CONTEXT)
            updates.append((collection_iri, str(RDFS.label), label, False))
            meta_context.remove((coll_uri, RDFS.label, None))
            meta_context.add((coll_uri, RDFS.label, Literal(label)))
        
        if description is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, collection_iri, str(RDFS.comment), META_CONTEXT)
            updates.append((collection_iri, str(RDFS.comment), description, False))
            meta_context.remove((coll_uri, RDFS.comment, None))
            meta_context.add((coll_uri, RDFS.comment, Literal(description)))
        
        if scope_level is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, collection_iri, str(ONTOS.scopeLevel), META_CONTEXT)
            updates.append((collection_iri, str(ONTOS.scopeLevel), scope_level, False))
            meta_context.remove((coll_uri, ONTOS.scopeLevel, None))
            meta_context.add((coll_uri, ONTOS.scopeLevel, Literal(scope_level)))
        
        if parent_collection_iri is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, collection_iri, str(ONTOS.parentCollection), META_CONTEXT)
            if parent_collection_iri:  # Empty string means remove parent
                updates.append((collection_iri, str(ONTOS.parentCollection), parent_collection_iri, True))
                meta_context.add((coll_uri, ONTOS.parentCollection, URIRef(parent_collection_iri)))
            meta_context.remove((coll_uri, ONTOS.parentCollection, None))
        
        if is_editable is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, collection_iri, str(ONTOS.isEditable), META_CONTEXT)
            updates.append((collection_iri, str(ONTOS.isEditable), str(is_editable).lower(), False))
            meta_context.remove((coll_uri, ONTOS.isEditable, None))
            meta_context.add((coll_uri, ONTOS.isEditable, Literal(str(is_editable).lower())))
        
        # Update timestamp
        rdf_triples_repo.remove_by_subject_predicate(self._db, collection_iri, str(ONTOS.updatedAt), META_CONTEXT)
        updates.append((collection_iri, str(ONTOS.updatedAt), now, False))
        meta_context.remove((coll_uri, ONTOS.updatedAt, None))
        meta_context.add((coll_uri, ONTOS.updatedAt, Literal(now, datatype=XSD.dateTime)))
        
        if updated_by:
            user_uri = f"urn:user:{updated_by}" if not updated_by.startswith("urn:") else updated_by
            rdf_triples_repo.remove_by_subject_predicate(self._db, collection_iri, str(ONTOS.updatedBy), META_CONTEXT)
            updates.append((collection_iri, str(ONTOS.updatedBy), user_uri, True))
            meta_context.remove((coll_uri, ONTOS.updatedBy, None))
            meta_context.add((coll_uri, ONTOS.updatedBy, URIRef(user_uri)))
        
        # Add new triples to database
        for subj, pred, obj, is_uri in updates:
            rdf_triples_repo.add_triple(
                self._db,
                subject_uri=subj,
                predicate_uri=pred,
                object_value=obj,
                object_is_uri=is_uri,
                context_name=META_CONTEXT,
                source_type="collection",
                source_identifier=collection_iri,
                created_by=updated_by,
            )
        
        self._db.commit()
        self._invalidate_cache()
        
        return self.get_collection(collection_iri)

    def delete_collection(self, collection_iri: str, deleted_by: Optional[str] = None) -> bool:
        """Delete a knowledge collection and all its concepts.
        
        Only custom collections can be deleted. Imported collections should be
        disabled instead.
        """
        META_CONTEXT = "urn:meta:sources"
        
        existing = self.get_collection(collection_iri)
        if not existing:
            return False
        
        if existing.get("source_type") == "imported":
            raise ValueError("Cannot delete imported collections. Disable editing instead.")
        
        # Remove collection metadata from meta context
        rdf_triples_repo.remove_by_subject(self._db, collection_iri, META_CONTEXT)
        
        # Remove all concepts in the collection's context
        rdf_triples_repo.remove_by_context(self._db, collection_iri)
        
        # Remove from in-memory graph
        meta_context = self._graph.get_context(URIRef(META_CONTEXT))
        coll_uri = URIRef(collection_iri)
        for triple in list(meta_context.triples((coll_uri, None, None))):
            meta_context.remove(triple)
        
        # Remove the collection's context from in-memory graph
        try:
            coll_context = self._graph.get_context(URIRef(collection_iri))
            self._graph.remove_context(coll_context)
        except:
            pass
        
        self._db.commit()
        self._invalidate_cache()
        
        return True

    # ========================================================================
    # CONCEPT CRUD
    # ========================================================================

    def create_concept(
        self,
        collection_iri: str,
        label: str,
        definition: Optional[str] = None,
        concept_type: str = "concept",
        synonyms: List[str] = None,
        examples: List[str] = None,
        broader_iris: List[str] = None,
        narrower_iris: List[str] = None,
        related_iris: List[str] = None,
        owners: List[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new concept in a collection.
        
        Creates SKOS-compatible triples in the collection's context.
        New concepts start with status 'draft'.
        
        owners: List of dicts with keys: user_uri, role (e.g., business_owner, data_steward)
        """
        from datetime import datetime
        
        # Verify collection exists and is editable
        collection = self.get_collection(collection_iri)
        if not collection:
            raise ValueError(f"Collection not found: {collection_iri}")
        if not collection.get("is_editable"):
            raise ValueError(f"Collection is not editable: {collection_iri}")
        
        # Generate concept IRI
        sanitized = _sanitize_context_name(label.lower().replace(" ", "-"))
        concept_iri = f"{collection_iri}/{sanitized}"
        
        # Check if already exists
        existing = self.get_concept(concept_iri)
        if existing:
            raise ValueError(f"Concept already exists: {concept_iri}")
        
        now = datetime.utcnow().isoformat() + "Z"
        synonyms = synonyms or []
        examples = examples or []
        broader_iris = broader_iris or []
        narrower_iris = narrower_iris or []
        related_iris = related_iris or []
        owners = owners or []
        
        # Build triples
        triples = [
            (concept_iri, str(RDF.type), str(SKOS.Concept), True),
            (concept_iri, str(SKOS.prefLabel), label, False),
            (concept_iri, str(ONTOS.status), "draft", False),
            (concept_iri, str(ONTOS.version), "1.0.0", False),
            (concept_iri, str(ONTOS.createdAt), now, False),
        ]
        
        if definition:
            triples.append((concept_iri, str(SKOS.definition), definition, False))
        
        for syn in synonyms:
            triples.append((concept_iri, str(SKOS.altLabel), syn, False))
        
        for ex in examples:
            triples.append((concept_iri, str(SKOS.example), ex, False))
        
        for broader in broader_iris:
            triples.append((concept_iri, str(SKOS.broader), broader, True))
        
        for narrower in narrower_iris:
            triples.append((concept_iri, str(SKOS.narrower), narrower, True))
        
        for related in related_iris:
            triples.append((concept_iri, str(SKOS.related), related, True))
        
        if created_by:
            user_uri = f"urn:user:{created_by}" if not created_by.startswith("urn:") else created_by
            triples.append((concept_iri, str(ONTOS.createdBy), user_uri, True))
        
        # Add to database
        for subj, pred, obj, is_uri in triples:
            rdf_triples_repo.add_triple(
                self._db,
                subject_uri=subj,
                predicate_uri=pred,
                object_value=obj,
                object_is_uri=is_uri,
                context_name=collection_iri,
                source_type="concept",
                source_identifier=concept_iri,
                created_by=created_by,
            )
        
        # Add to in-memory graph
        coll_context = self._graph.get_context(URIRef(collection_iri))
        concept_uri = URIRef(concept_iri)
        coll_context.add((concept_uri, RDF.type, SKOS.Concept))
        coll_context.add((concept_uri, SKOS.prefLabel, Literal(label)))
        coll_context.add((concept_uri, ONTOS.status, Literal("draft")))
        coll_context.add((concept_uri, ONTOS.version, Literal("1.0.0")))
        coll_context.add((concept_uri, ONTOS.createdAt, Literal(now, datatype=XSD.dateTime)))
        
        if definition:
            coll_context.add((concept_uri, SKOS.definition, Literal(definition)))
        for syn in synonyms:
            coll_context.add((concept_uri, SKOS.altLabel, Literal(syn)))
        for ex in examples:
            coll_context.add((concept_uri, SKOS.example, Literal(ex)))
        for broader in broader_iris:
            coll_context.add((concept_uri, SKOS.broader, URIRef(broader)))
        for narrower in narrower_iris:
            coll_context.add((concept_uri, SKOS.narrower, URIRef(narrower)))
        for related in related_iris:
            coll_context.add((concept_uri, SKOS.related, URIRef(related)))
        if created_by:
            user_uri = f"urn:user:{created_by}" if not created_by.startswith("urn:") else created_by
            coll_context.add((concept_uri, ONTOS.createdBy, URIRef(user_uri)))
        
        self._db.commit()
        
        # Add owners if provided
        for owner in owners:
            owner_user = owner.get("user_uri", "")
            owner_role = owner.get("role", "business_owner")
            if owner_user:
                # Normalize user URI
                if not owner_user.startswith("urn:"):
                    owner_user = f"urn:user:{owner_user}"
                try:
                    self.add_concept_owner(
                        concept_iri=concept_iri,
                        user_email=owner_user.replace("urn:user:", ""),
                        role=owner_role,
                        assigned_by=created_by,
                    )
                except Exception as e:
                    logger.warning(f"Failed to add owner {owner_user} to concept: {e}")
        
        self._invalidate_cache()
        
        return self.get_concept(concept_iri)

    def get_concept(self, concept_iri: str) -> Optional[Dict[str, Any]]:
        """Get a concept by IRI with all its properties and governance info."""
        concept_uri = URIRef(concept_iri)
        
        # Find which context contains this concept
        for context in self._graph.contexts():
            context_name = str(context.identifier)
            if context_name == "urn:x-rdflib:default":
                continue
            
            # Check if concept exists in this context
            if (concept_uri, RDF.type, None) in context:
                # Extract all properties
                label = self._get_literal(context, concept_uri, SKOS.prefLabel)
                if not label:
                    label = self._get_literal(context, concept_uri, RDFS.label)
                
                definition = self._get_literal(context, concept_uri, SKOS.definition)
                if not definition:
                    definition = self._get_literal(context, concept_uri, RDFS.comment)
                
                # Determine concept type
                concept_type = "concept"
                for rdf_type in context.objects(concept_uri, RDF.type):
                    type_str = str(rdf_type)
                    if type_str == str(SKOS.Concept):
                        concept_type = "concept"
                    elif type_str == str(RDFS.Class) or type_str == str(OWL.Class):
                        concept_type = "class"
                    elif type_str == str(RDF.Property) or type_str == str(OWL.ObjectProperty):
                        concept_type = "property"
                
                # Get synonyms and examples
                synonyms = [str(s) for s in context.objects(concept_uri, SKOS.altLabel)]
                examples = [str(e) for e in context.objects(concept_uri, SKOS.example)]
                
                # Get hierarchy
                broader = [str(b) for b in context.objects(concept_uri, SKOS.broader)]
                narrower = [str(n) for n in context.objects(concept_uri, SKOS.narrower)]
                related = [str(r) for r in context.objects(concept_uri, SKOS.related)]
                
                # Also check rdfs:subClassOf for classes
                for parent in context.objects(concept_uri, RDFS.subClassOf):
                    parent_str = str(parent)
                    if not isinstance(parent, BNode) and not self._is_skolemized_bnode(parent_str) and parent_str not in broader:
                        broader.append(parent_str)
                # Also check owl:equivalentClass + owl:intersectionOf
                for parent_iri in self._extract_parents_from_owl_equivalent_class(context, concept_uri):
                    if parent_iri not in broader:
                        broader.append(parent_iri)
                
                # Get governance info
                status = self._get_literal(context, concept_uri, ONTOS.status)
                version = self._get_literal(context, concept_uri, ONTOS.version)
                created_at = self._get_literal(context, concept_uri, ONTOS.createdAt)
                created_by = self._get_uri(context, concept_uri, ONTOS.createdBy)
                updated_at = self._get_literal(context, concept_uri, ONTOS.updatedAt)
                updated_by = self._get_uri(context, concept_uri, ONTOS.updatedBy)
                published_at = self._get_literal(context, concept_uri, ONTOS.publishedAt)
                published_by = self._get_uri(context, concept_uri, ONTOS.publishedBy)
                certified_at = self._get_literal(context, concept_uri, ONTOS.certifiedAt)
                certified_by = self._get_uri(context, concept_uri, ONTOS.certifiedBy)
                cert_expires = self._get_literal(context, concept_uri, ONTOS.certificationExpiresAt)
                review_id = self._get_literal(context, concept_uri, ONTOS.reviewRequestId)
                
                # Get provenance
                source_concept = self._get_uri(context, concept_uri, ONTOS.sourceConceptIri)
                source_coll = self._get_uri(context, concept_uri, ONTOS.sourceCollectionIri)
                promotion_type = self._get_literal(context, concept_uri, ONTOS.promotionType)
                
                # Get owners
                owners = []
                for owner_uri in context.objects(concept_uri, ONTOS.hasOwner):
                    owner_user = self._get_uri(context, owner_uri, ONTOS.ownershipUser)
                    owner_role = self._get_literal(context, owner_uri, ONTOS.ownershipRole)
                    owner_assigned = self._get_literal(context, owner_uri, ONTOS.ownershipAssignedAt)
                    owner_by = self._get_uri(context, owner_uri, ONTOS.ownershipAssignedBy)
                    if owner_user and owner_role:
                        owners.append({
                            "user_uri": owner_user,
                            "role": owner_role,
                            "assigned_at": owner_assigned,
                            "assigned_by": owner_by,
                        })
                
                return {
                    "iri": concept_iri,
                    "label": label,
                    "comment": definition,
                    "concept_type": concept_type,
                    "source_context": context_name,
                    "parent_concepts": broader,
                    "child_concepts": narrower,
                    "related_concepts": related,
                    "synonyms": synonyms,
                    "examples": examples,
                    "status": status,
                    "version": version,
                    "owners": owners,
                    "created_at": created_at,
                    "created_by": created_by,
                    "updated_at": updated_at,
                    "updated_by": updated_by,
                    "published_at": published_at,
                    "published_by": published_by,
                    "certified_at": certified_at,
                    "certified_by": certified_by,
                    "certification_expires_at": cert_expires,
                    "source_concept_iri": source_concept,
                    "source_collection_iri": source_coll,
                    "promotion_type": promotion_type,
                    "review_request_id": review_id,
                    "tagged_assets": [],
                    "properties": [],
                }
        
        return None

    def update_concept(
        self,
        concept_iri: str,
        label: Optional[str] = None,
        definition: Optional[str] = None,
        synonyms: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        broader_iris: Optional[List[str]] = None,
        narrower_iris: Optional[List[str]] = None,
        related_iris: Optional[List[str]] = None,
        updated_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a concept's properties.
        
        Only concepts with status 'draft' can be freely edited.
        Published concepts require creating a new version.
        """
        from datetime import datetime
        
        existing = self.get_concept(concept_iri)
        if not existing:
            return None
        
        collection_iri = existing.get("source_context")
        if not collection_iri:
            raise ValueError("Cannot determine collection for concept")
        
        # Check if collection is editable
        collection = self.get_collection(collection_iri)
        if collection and not collection.get("is_editable"):
            raise ValueError(f"Collection is not editable: {collection_iri}")
        
        # Check status - only draft can be freely edited
        status = existing.get("status")
        if status and status not in ("draft", None):
            raise ValueError(f"Cannot edit concept with status '{status}'. Submit changes for review or create new version.")
        
        concept_uri = URIRef(concept_iri)
        coll_context = self._graph.get_context(URIRef(collection_iri))
        now = datetime.utcnow().isoformat() + "Z"
        
        updates = []
        
        if label is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(SKOS.prefLabel), collection_iri)
            updates.append((concept_iri, str(SKOS.prefLabel), label, False))
            coll_context.remove((concept_uri, SKOS.prefLabel, None))
            coll_context.add((concept_uri, SKOS.prefLabel, Literal(label)))
        
        if definition is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(SKOS.definition), collection_iri)
            updates.append((concept_iri, str(SKOS.definition), definition, False))
            coll_context.remove((concept_uri, SKOS.definition, None))
            coll_context.add((concept_uri, SKOS.definition, Literal(definition)))
        
        if synonyms is not None:
            # Remove all existing synonyms
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(SKOS.altLabel), collection_iri)
            coll_context.remove((concept_uri, SKOS.altLabel, None))
            for syn in synonyms:
                updates.append((concept_iri, str(SKOS.altLabel), syn, False))
                coll_context.add((concept_uri, SKOS.altLabel, Literal(syn)))
        
        if examples is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(SKOS.example), collection_iri)
            coll_context.remove((concept_uri, SKOS.example, None))
            for ex in examples:
                updates.append((concept_iri, str(SKOS.example), ex, False))
                coll_context.add((concept_uri, SKOS.example, Literal(ex)))
        
        if broader_iris is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(SKOS.broader), collection_iri)
            coll_context.remove((concept_uri, SKOS.broader, None))
            for broader in broader_iris:
                updates.append((concept_iri, str(SKOS.broader), broader, True))
                coll_context.add((concept_uri, SKOS.broader, URIRef(broader)))
        
        if narrower_iris is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(SKOS.narrower), collection_iri)
            coll_context.remove((concept_uri, SKOS.narrower, None))
            for narrower in narrower_iris:
                updates.append((concept_iri, str(SKOS.narrower), narrower, True))
                coll_context.add((concept_uri, SKOS.narrower, URIRef(narrower)))
        
        if related_iris is not None:
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(SKOS.related), collection_iri)
            coll_context.remove((concept_uri, SKOS.related, None))
            for related in related_iris:
                updates.append((concept_iri, str(SKOS.related), related, True))
                coll_context.add((concept_uri, SKOS.related, URIRef(related)))
        
        # Update timestamp
        rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.updatedAt), collection_iri)
        updates.append((concept_iri, str(ONTOS.updatedAt), now, False))
        coll_context.remove((concept_uri, ONTOS.updatedAt, None))
        coll_context.add((concept_uri, ONTOS.updatedAt, Literal(now, datatype=XSD.dateTime)))
        
        if updated_by:
            user_uri = f"urn:user:{updated_by}" if not updated_by.startswith("urn:") else updated_by
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.updatedBy), collection_iri)
            updates.append((concept_iri, str(ONTOS.updatedBy), user_uri, True))
            coll_context.remove((concept_uri, ONTOS.updatedBy, None))
            coll_context.add((concept_uri, ONTOS.updatedBy, URIRef(user_uri)))
        
        # Add to database
        for subj, pred, obj, is_uri in updates:
            rdf_triples_repo.add_triple(
                self._db,
                subject_uri=subj,
                predicate_uri=pred,
                object_value=obj,
                object_is_uri=is_uri,
                context_name=collection_iri,
                source_type="concept",
                source_identifier=concept_iri,
                created_by=updated_by,
            )
        
        self._db.commit()
        self._invalidate_cache()
        
        return self.get_concept(concept_iri)

    def delete_concept(self, concept_iri: str, deleted_by: Optional[str] = None) -> bool:
        """Delete a concept.
        
        Only concepts with status 'draft' can be deleted.
        Published concepts should be deprecated instead.
        """
        existing = self.get_concept(concept_iri)
        if not existing:
            return False
        
        collection_iri = existing.get("source_context")
        if not collection_iri:
            return False
        
        # Check if collection is editable
        collection = self.get_collection(collection_iri)
        if collection and not collection.get("is_editable"):
            raise ValueError(f"Collection is not editable: {collection_iri}")
        
        # Check status - only draft can be deleted
        status = existing.get("status")
        if status and status not in ("draft", None):
            raise ValueError(f"Cannot delete concept with status '{status}'. Deprecate it instead.")
        
        # Remove all triples for this concept
        rdf_triples_repo.remove_by_subject(self._db, concept_iri, collection_iri)
        
        # Also remove any ownership records
        for owner in existing.get("owners", []):
            owner_iri = f"{concept_iri}/owner/{owner.get('user_uri', '').split(':')[-1]}"
            rdf_triples_repo.remove_by_subject(self._db, owner_iri, collection_iri)
        
        # Remove from in-memory graph
        concept_uri = URIRef(concept_iri)
        coll_context = self._graph.get_context(URIRef(collection_iri))
        for triple in list(coll_context.triples((concept_uri, None, None))):
            coll_context.remove(triple)
        
        self._db.commit()
        self._invalidate_cache()
        
        return True

    # ========================================================================
    # OWNERSHIP MANAGEMENT
    # ========================================================================

    def add_concept_owner(
        self,
        concept_iri: str,
        user_email: str,
        role: str,
        assigned_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Add an owner to a concept using named reification pattern.
        
        Creates a named Ownership node linked to the concept.
        """
        from datetime import datetime
        
        existing = self.get_concept(concept_iri)
        if not existing:
            return None
        
        collection_iri = existing.get("source_context")
        if not collection_iri:
            raise ValueError("Cannot determine collection for concept")
        
        # Check if collection is editable
        collection = self.get_collection(collection_iri)
        if collection and not collection.get("is_editable"):
            raise ValueError(f"Collection is not editable: {collection_iri}")
        
        # Generate ownership IRI
        sanitized_email = _sanitize_context_name(user_email.replace("@", "_at_"))
        ownership_iri = f"{concept_iri}/owner/{sanitized_email}"
        
        # Check if already exists
        for owner in existing.get("owners", []):
            if owner.get("user_uri", "").endswith(user_email):
                raise ValueError(f"User already has ownership: {user_email}")
        
        now = datetime.utcnow().isoformat() + "Z"
        user_uri = f"urn:user:{user_email}"
        
        triples = [
            (ownership_iri, str(RDF.type), str(ONTOS.Ownership), True),
            (ownership_iri, str(ONTOS.ownershipUser), user_uri, True),
            (ownership_iri, str(ONTOS.ownershipRole), role, False),
            (ownership_iri, str(ONTOS.ownershipAssignedAt), now, False),
            (concept_iri, str(ONTOS.hasOwner), ownership_iri, True),
        ]
        
        if assigned_by:
            assigner_uri = f"urn:user:{assigned_by}" if not assigned_by.startswith("urn:") else assigned_by
            triples.append((ownership_iri, str(ONTOS.ownershipAssignedBy), assigner_uri, True))
        
        # Add to database
        for subj, pred, obj, is_uri in triples:
            rdf_triples_repo.add_triple(
                self._db,
                subject_uri=subj,
                predicate_uri=pred,
                object_value=obj,
                object_is_uri=is_uri,
                context_name=collection_iri,
                source_type="ownership",
                source_identifier=concept_iri,
                created_by=assigned_by,
            )
        
        # Add to in-memory graph
        coll_context = self._graph.get_context(URIRef(collection_iri))
        ownership_uri = URIRef(ownership_iri)
        concept_uri = URIRef(concept_iri)
        
        coll_context.add((ownership_uri, RDF.type, ONTOS.Ownership))
        coll_context.add((ownership_uri, ONTOS.ownershipUser, URIRef(user_uri)))
        coll_context.add((ownership_uri, ONTOS.ownershipRole, Literal(role)))
        coll_context.add((ownership_uri, ONTOS.ownershipAssignedAt, Literal(now, datatype=XSD.dateTime)))
        coll_context.add((concept_uri, ONTOS.hasOwner, ownership_uri))
        if assigned_by:
            assigner_uri = f"urn:user:{assigned_by}" if not assigned_by.startswith("urn:") else assigned_by
            coll_context.add((ownership_uri, ONTOS.ownershipAssignedBy, URIRef(assigner_uri)))
        
        self._db.commit()
        self._invalidate_cache()
        
        return self.get_concept(concept_iri)

    def remove_concept_owner(
        self,
        concept_iri: str,
        user_email: str,
        removed_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Remove an owner from a concept."""
        existing = self.get_concept(concept_iri)
        if not existing:
            return None
        
        collection_iri = existing.get("source_context")
        if not collection_iri:
            raise ValueError("Cannot determine collection for concept")
        
        # Find the ownership IRI
        sanitized_email = _sanitize_context_name(user_email.replace("@", "_at_"))
        ownership_iri = f"{concept_iri}/owner/{sanitized_email}"
        
        # Remove from database
        rdf_triples_repo.remove_by_subject(self._db, ownership_iri, collection_iri)
        # Remove the specific hasOwner triple linking concept to this ownership
        rdf_triples_repo.remove_triple(
            self._db, concept_iri, str(ONTOS.hasOwner), ownership_iri, collection_iri
        )
        
        # Remove from in-memory graph
        coll_context = self._graph.get_context(URIRef(collection_iri))
        ownership_uri = URIRef(ownership_iri)
        concept_uri = URIRef(concept_iri)
        
        for triple in list(coll_context.triples((ownership_uri, None, None))):
            coll_context.remove(triple)
        coll_context.remove((concept_uri, ONTOS.hasOwner, ownership_uri))
        
        self._db.commit()
        self._invalidate_cache()
        
        return self.get_concept(concept_iri)

    # ========================================================================
    # LIFECYCLE STATUS TRANSITIONS
    # ========================================================================

    def update_concept_status(
        self,
        concept_iri: str,
        new_status: str,
        updated_by: Optional[str] = None,
        review_request_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update the status of a concept with validation.
        
        Valid transitions:
        - draft -> under_review (requires reviewers)
        - under_review -> approved | draft (reviewer action)
        - approved -> published (admin action)
        - published -> certified | deprecated
        - certified -> deprecated | archived
        - deprecated -> archived
        """
        from datetime import datetime
        
        VALID_TRANSITIONS = {
            "draft": ["under_review"],
            "under_review": ["approved", "draft"],  # draft = changes requested
            "approved": ["published"],
            "published": ["certified", "deprecated"],
            "certified": ["deprecated", "archived"],
            "deprecated": ["archived"],
            "archived": [],
        }
        
        existing = self.get_concept(concept_iri)
        if not existing:
            return None
        
        collection_iri = existing.get("source_context")
        current_status = existing.get("status") or "draft"
        
        # Validate transition
        allowed = VALID_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise ValueError(f"Invalid status transition: {current_status} -> {new_status}. Allowed: {allowed}")
        
        concept_uri = URIRef(concept_iri)
        coll_context = self._graph.get_context(URIRef(collection_iri))
        now = datetime.utcnow().isoformat() + "Z"
        
        # Update status
        rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.status), collection_iri)
        rdf_triples_repo.add_triple(
            self._db, concept_iri, str(ONTOS.status), new_status,
            False, None, None, collection_iri, "concept", concept_iri, updated_by
        )
        coll_context.remove((concept_uri, ONTOS.status, None))
        coll_context.add((concept_uri, ONTOS.status, Literal(new_status)))
        
        # Update timestamp
        rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.updatedAt), collection_iri)
        rdf_triples_repo.add_triple(
            self._db, concept_iri, str(ONTOS.updatedAt), now,
            False, None, None, collection_iri, "concept", concept_iri, updated_by
        )
        coll_context.remove((concept_uri, ONTOS.updatedAt, None))
        coll_context.add((concept_uri, ONTOS.updatedAt, Literal(now, datatype=XSD.dateTime)))
        
        # Handle status-specific fields
        if new_status == "under_review" and review_request_id:
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.reviewRequestId), collection_iri)
            rdf_triples_repo.add_triple(
                self._db, concept_iri, str(ONTOS.reviewRequestId), review_request_id,
                False, None, None, collection_iri, "concept", concept_iri, updated_by
            )
            coll_context.remove((concept_uri, ONTOS.reviewRequestId, None))
            coll_context.add((concept_uri, ONTOS.reviewRequestId, Literal(review_request_id)))
        
        if new_status == "published" and updated_by:
            user_uri = f"urn:user:{updated_by}" if not updated_by.startswith("urn:") else updated_by
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.publishedAt), collection_iri)
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.publishedBy), collection_iri)
            rdf_triples_repo.add_triple(
                self._db, concept_iri, str(ONTOS.publishedAt), now,
                False, None, None, collection_iri, "concept", concept_iri, updated_by
            )
            rdf_triples_repo.add_triple(
                self._db, concept_iri, str(ONTOS.publishedBy), user_uri,
                True, None, None, collection_iri, "concept", concept_iri, updated_by
            )
            coll_context.remove((concept_uri, ONTOS.publishedAt, None))
            coll_context.remove((concept_uri, ONTOS.publishedBy, None))
            coll_context.add((concept_uri, ONTOS.publishedAt, Literal(now, datatype=XSD.dateTime)))
            coll_context.add((concept_uri, ONTOS.publishedBy, URIRef(user_uri)))
        
        if new_status == "certified" and updated_by:
            from datetime import timedelta
            user_uri = f"urn:user:{updated_by}" if not updated_by.startswith("urn:") else updated_by
            expires = (datetime.utcnow() + timedelta(days=365)).isoformat() + "Z"
            
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.certifiedAt), collection_iri)
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.certifiedBy), collection_iri)
            rdf_triples_repo.remove_by_subject_predicate(self._db, concept_iri, str(ONTOS.certificationExpiresAt), collection_iri)
            rdf_triples_repo.add_triple(
                self._db, concept_iri, str(ONTOS.certifiedAt), now,
                False, None, None, collection_iri, "concept", concept_iri, updated_by
            )
            rdf_triples_repo.add_triple(
                self._db, concept_iri, str(ONTOS.certifiedBy), user_uri,
                True, None, None, collection_iri, "concept", concept_iri, updated_by
            )
            rdf_triples_repo.add_triple(
                self._db, concept_iri, str(ONTOS.certificationExpiresAt), expires,
                False, None, None, collection_iri, "concept", concept_iri, updated_by
            )
            coll_context.remove((concept_uri, ONTOS.certifiedAt, None))
            coll_context.remove((concept_uri, ONTOS.certifiedBy, None))
            coll_context.remove((concept_uri, ONTOS.certificationExpiresAt, None))
            coll_context.add((concept_uri, ONTOS.certifiedAt, Literal(now, datatype=XSD.dateTime)))
            coll_context.add((concept_uri, ONTOS.certifiedBy, URIRef(user_uri)))
            coll_context.add((concept_uri, ONTOS.certificationExpiresAt, Literal(expires, datatype=XSD.dateTime)))
        
        self._db.commit()
        self._invalidate_cache()
        
        return self.get_concept(concept_iri)

    def submit_concept_for_review(
        self,
        concept_iri: str,
        reviewer_email: str,
        submitted_by: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a concept for review via the DataAssetReviewManager.
        
        Creates a review request and updates concept status to 'under_review'.
        Returns the updated concept with review_request_id set.
        """
        from src.models.data_asset_reviews import (
            DataAssetReviewRequestCreate,
            AssetType,
        )
        
        existing = self.get_concept(concept_iri)
        if not existing:
            raise ValueError(f"Concept not found: {concept_iri}")
        
        status = existing.get("status") or "draft"
        if status != "draft":
            raise ValueError(f"Can only submit draft concepts for review. Current status: {status}")
        
        # Create the review request
        # Note: This requires the DataAssetReviewManager to be available
        # The actual integration happens in the route layer
        review_request_data = {
            "concept_iri": concept_iri,
            "concept_label": existing.get("label"),
            "reviewer_email": reviewer_email,
            "requester_email": submitted_by,
            "notes": notes,
            "asset_type": "knowledge_concept",
        }
        
        # Return the data needed for review request creation
        # The route layer will create the actual review request
        return review_request_data

    # ========================================================================
    # COLLECTION EXPORT
    # ========================================================================

    def export_collection_as_turtle(self, collection_iri: str) -> str:
        """Export a collection's concepts as Turtle format.
        
        Returns the serialized RDF graph for the collection.
        """
        collection = self.get_collection(collection_iri)
        if not collection:
            raise ValueError(f"Collection not found: {collection_iri}")
        
        # Get the context for this collection
        try:
            coll_context = self._graph.get_context(URIRef(collection_iri))
            return coll_context.serialize(format='turtle')
        except Exception as e:
            logger.error(f"Failed to export collection: {e}")
            raise ValueError(f"Failed to export collection: {e}")

    def export_collection_as_rdfxml(self, collection_iri: str) -> str:
        """Export a collection's concepts as RDF/XML format.
        
        Returns the serialized RDF graph for the collection.
        """
        collection = self.get_collection(collection_iri)
        if not collection:
            raise ValueError(f"Collection not found: {collection_iri}")
        
        try:
            coll_context = self._graph.get_context(URIRef(collection_iri))
            return coll_context.serialize(format='xml')
        except Exception as e:
            logger.error(f"Failed to export collection: {e}")
            raise ValueError(f"Failed to export collection: {e}")

    def import_rdf_to_collection(
        self,
        collection_iri: str,
        content: str,
        format: str = "turtle",
        imported_by: Optional[str] = None,
    ) -> int:
        """Import RDF content into an existing collection.
        
        Parses the RDF and adds triples to the collection's context.
        Returns the number of triples imported.
        """
        collection = self.get_collection(collection_iri)
        if not collection:
            raise ValueError(f"Collection not found: {collection_iri}")
        if not collection.get("is_editable"):
            raise ValueError(f"Collection is not editable: {collection_iri}")
        
        # Parse the content
        temp_graph = Graph()
        rdf_format = "turtle" if format.lower() in ("ttl", "turtle") else "xml"
        temp_graph.parse(data=content, format=rdf_format)
        
        # Import to database
        count = self._import_graph_to_db(
            graph=temp_graph,
            context_name=collection_iri,
            source_type="import",
            source_identifier=collection_iri,
            created_by=imported_by,
        )
        
        # Also add to in-memory graph
        coll_context = self._graph.get_context(URIRef(collection_iri))
        for triple in temp_graph:
            coll_context.add(triple)
        
        self._invalidate_cache()
        
        return count

    # ========================================================================
    # COLLECTION HIERARCHY
    # ========================================================================

    def get_collections_with_hierarchy(self) -> List[Dict[str, Any]]:
        """Get collections organized as a hierarchy tree.
        
        Returns root collections with nested child_collections arrays.
        """
        all_collections = self.get_collections()
        
        # Build lookup map
        by_iri = {c["iri"]: c for c in all_collections}
        
        # Add child_collections to each
        for coll in all_collections:
            coll["child_collections"] = []
        
        # Build hierarchy
        roots = []
        for coll in all_collections:
            parent_iri = coll.get("parent_collection_iri")
            if parent_iri and parent_iri in by_iri:
                by_iri[parent_iri]["child_collections"].append(coll)
            else:
                roots.append(coll)
        
        # Sort children
        def sort_children(coll):
            scope_order = {"enterprise": 0, "domain": 1, "department": 2, "team": 3, "project": 4, "external": 5}
            coll["child_collections"].sort(key=lambda c: (scope_order.get(c.get("scope_level", ""), 99), c.get("label", "")))
            for child in coll["child_collections"]:
                sort_children(child)
        
        for root in roots:
            sort_children(root)
        
        return roots

    def get_collection_ancestors(self, collection_iri: str) -> List[Dict[str, Any]]:
        """Get all ancestor collections for a given collection."""
        all_collections = self.get_collections()
        by_iri = {c["iri"]: c for c in all_collections}
        
        ancestors = []
        current = by_iri.get(collection_iri)
        
        while current:
            parent_iri = current.get("parent_collection_iri")
            if parent_iri and parent_iri in by_iri:
                parent = by_iri[parent_iri]
                ancestors.append(parent)
                current = parent
            else:
                break
        
        ancestors.reverse()  # Root first
        return ancestors

    def get_collection_descendants(self, collection_iri: str) -> List[Dict[str, Any]]:
        """Get all descendant collections for a given collection."""
        all_collections = self.get_collections()
        
        descendants = []
        stack = [collection_iri]
        
        while stack:
            current_iri = stack.pop()
            for coll in all_collections:
                if coll.get("parent_collection_iri") == current_iri:
                    descendants.append(coll)
                    stack.append(coll["iri"])
        
        return descendants

    # ========================================================================
    # PROMOTION AND MIGRATION
    # ========================================================================

    def promote_concept(
        self,
        concept_iri: str,
        target_collection_iri: str,
        deprecate_source: bool = True,
        promoted_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Promote a concept to a higher-scope collection.
        
        Creates a copy in the target collection with provenance tracking.
        Optionally deprecates the original.
        """
        from datetime import datetime
        
        existing = self.get_concept(concept_iri)
        if not existing:
            raise ValueError(f"Concept not found: {concept_iri}")
        
        source_collection_iri = existing.get("source_context")
        target_collection = self.get_collection(target_collection_iri)
        
        if not target_collection:
            raise ValueError(f"Target collection not found: {target_collection_iri}")
        if not target_collection.get("is_editable"):
            raise ValueError(f"Target collection is not editable: {target_collection_iri}")
        
        # Generate new IRI in target collection
        label = existing.get("label") or concept_iri.split("/")[-1]
        sanitized = _sanitize_context_name(label.lower().replace(" ", "-"))
        new_iri = f"{target_collection_iri}/{sanitized}"
        
        # Check if already exists
        if self.get_concept(new_iri):
            raise ValueError(f"Concept already exists in target: {new_iri}")
        
        # Create new concept with provenance
        new_concept = self.create_concept(
            collection_iri=target_collection_iri,
            label=label,
            definition=existing.get("comment"),
            concept_type=existing.get("concept_type", "concept"),
            synonyms=existing.get("synonyms", []),
            examples=existing.get("examples", []),
            broader_iris=existing.get("parent_concepts", []),
            narrower_iris=existing.get("child_concepts", []),
            related_iris=existing.get("related_concepts", []),
            created_by=promoted_by,
        )
        
        # Add provenance triples
        now = datetime.utcnow().isoformat() + "Z"
        provenance_triples = [
            (new_iri, str(ONTOS.sourceConceptIri), concept_iri, True),
            (new_iri, str(ONTOS.sourceCollectionIri), source_collection_iri, True),
            (new_iri, str(ONTOS.promotionType), "promoted", False),
            (new_iri, str(ONTOS.promotedAt), now, False),
        ]
        if promoted_by:
            user_uri = f"urn:user:{promoted_by}" if not promoted_by.startswith("urn:") else promoted_by
            provenance_triples.append((new_iri, str(ONTOS.promotedBy), user_uri, True))
        
        for subj, pred, obj, is_uri in provenance_triples:
            rdf_triples_repo.add_triple(
                self._db, subj, pred, obj, is_uri,
                None, None, target_collection_iri, "concept", new_iri, promoted_by
            )
        
        # Update in-memory graph
        target_context = self._graph.get_context(URIRef(target_collection_iri))
        new_uri = URIRef(new_iri)
        target_context.add((new_uri, ONTOS.sourceConceptIri, URIRef(concept_iri)))
        target_context.add((new_uri, ONTOS.sourceCollectionIri, URIRef(source_collection_iri)))
        target_context.add((new_uri, ONTOS.promotionType, Literal("promoted")))
        target_context.add((new_uri, ONTOS.promotedAt, Literal(now, datatype=XSD.dateTime)))
        if promoted_by:
            user_uri = f"urn:user:{promoted_by}" if not promoted_by.startswith("urn:") else promoted_by
            target_context.add((new_uri, ONTOS.promotedBy, URIRef(user_uri)))
        
        # Deprecate original if requested
        if deprecate_source:
            self.update_concept_status(concept_iri, "deprecated", promoted_by)
            # Add seeAlso to point to promoted version
            rdf_triples_repo.add_triple(
                self._db, concept_iri, str(RDFS.seeAlso), new_iri,
                True, None, None, source_collection_iri, "concept", concept_iri, promoted_by
            )
            source_context = self._graph.get_context(URIRef(source_collection_iri))
            source_context.add((URIRef(concept_iri), RDFS.seeAlso, URIRef(new_iri)))
        
        self._db.commit()
        self._invalidate_cache()
        
        return self.get_concept(new_iri)

    def migrate_concept(
        self,
        concept_iri: str,
        target_collection_iri: str,
        delete_source: bool = False,
        migrated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Migrate a concept to a different collection (not necessarily in hierarchy).
        
        Similar to promote but uses 'migrated' provenance type.
        Can optionally delete the source concept (only if draft).
        """
        from datetime import datetime
        
        existing = self.get_concept(concept_iri)
        if not existing:
            raise ValueError(f"Concept not found: {concept_iri}")
        
        source_collection_iri = existing.get("source_context")
        target_collection = self.get_collection(target_collection_iri)
        
        if not target_collection:
            raise ValueError(f"Target collection not found: {target_collection_iri}")
        if not target_collection.get("is_editable"):
            raise ValueError(f"Target collection is not editable: {target_collection_iri}")
        
        # Generate new IRI in target collection
        label = existing.get("label") or concept_iri.split("/")[-1]
        sanitized = _sanitize_context_name(label.lower().replace(" ", "-"))
        new_iri = f"{target_collection_iri}/{sanitized}"
        
        # Check if already exists
        if self.get_concept(new_iri):
            raise ValueError(f"Concept already exists in target: {new_iri}")
        
        # Create new concept with provenance
        new_concept = self.create_concept(
            collection_iri=target_collection_iri,
            label=label,
            definition=existing.get("comment"),
            concept_type=existing.get("concept_type", "concept"),
            synonyms=existing.get("synonyms", []),
            examples=existing.get("examples", []),
            broader_iris=existing.get("parent_concepts", []),
            narrower_iris=existing.get("child_concepts", []),
            related_iris=existing.get("related_concepts", []),
            created_by=migrated_by,
        )
        
        # Add provenance triples
        now = datetime.utcnow().isoformat() + "Z"
        provenance_triples = [
            (new_iri, str(ONTOS.sourceConceptIri), concept_iri, True),
            (new_iri, str(ONTOS.sourceCollectionIri), source_collection_iri, True),
            (new_iri, str(ONTOS.promotionType), "migrated", False),
            (new_iri, str(ONTOS.promotedAt), now, False),
        ]
        if migrated_by:
            user_uri = f"urn:user:{migrated_by}" if not migrated_by.startswith("urn:") else migrated_by
            provenance_triples.append((new_iri, str(ONTOS.promotedBy), user_uri, True))
        
        for subj, pred, obj, is_uri in provenance_triples:
            rdf_triples_repo.add_triple(
                self._db, subj, pred, obj, is_uri,
                None, None, target_collection_iri, "concept", new_iri, migrated_by
            )
        
        # Update in-memory graph
        target_context = self._graph.get_context(URIRef(target_collection_iri))
        new_uri = URIRef(new_iri)
        target_context.add((new_uri, ONTOS.sourceConceptIri, URIRef(concept_iri)))
        target_context.add((new_uri, ONTOS.sourceCollectionIri, URIRef(source_collection_iri)))
        target_context.add((new_uri, ONTOS.promotionType, Literal("migrated")))
        target_context.add((new_uri, ONTOS.promotedAt, Literal(now, datatype=XSD.dateTime)))
        
        # Delete or deprecate original
        status = existing.get("status") or "draft"
        if delete_source:
            if status and status != "draft":
                raise ValueError("Cannot delete non-draft concept. Will deprecate instead.")
            self.delete_concept(concept_iri, migrated_by)
        elif status == "draft":
            # Draft concepts cannot transition to deprecated; delete instead
            self.delete_concept(concept_iri, migrated_by)
        else:
            self.update_concept_status(concept_iri, "deprecated", migrated_by)
        
        self._db.commit()
        self._invalidate_cache()
        
        return self.get_concept(new_iri)

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _get_literal(self, context, subject: URIRef, predicate) -> Optional[str]:
        """Get a literal value from a triple."""
        for obj in context.objects(subject, predicate):
            if isinstance(obj, Literal):
                return str(obj)
            elif isinstance(obj, str):
                return obj
        return None

    def _get_uri(self, context, subject: URIRef, predicate) -> Optional[str]:
        """Get a URI value from a triple."""
        for obj in context.objects(subject, predicate):
            if isinstance(obj, URIRef):
                return str(obj)
            elif isinstance(obj, str) and (obj.startswith("urn:") or obj.startswith("http")):
                return obj
        return None

    def _invalidate_cache(self):
        """Invalidate all cached results."""
        self._cache.clear()

