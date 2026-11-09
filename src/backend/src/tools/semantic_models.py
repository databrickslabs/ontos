"""
Semantic Models tools for LLM.

Tools for searching glossary terms and managing semantic links.
"""

from typing import Any, Dict, Optional

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult, tool_failure

logger = get_logger(__name__)


class SearchGlossaryTermsTool(BaseTool):
    """Search the knowledge graph for business concepts, terms, and definitions."""
    
    name = "search_glossary_terms"
    category = "semantic"
    description = "Search the knowledge graph for business concepts, terms, and definitions from ontologies and taxonomies."
    parameters = {
        "term": {
            "type": "string",
            "description": "Business term or concept to search for (e.g., 'Customer', 'Sales', 'Transaction', 'Revenue')"
        },
        "domain": {
            "type": "string",
            "description": "Optional taxonomy/domain filter"
        }
    }
    required_params = ["term"]
    required_scope = "semantic:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        term: str,
        domain: Optional[str] = None
    ) -> ToolResult:
        """Search for business terms/concepts in the knowledge graph."""
        logger.info(f"[search_glossary_terms] Starting - term='{term}', domain={domain}")
        
        if not ctx.semantic_models_manager:
            logger.warning(f"[search_glossary_terms] FAILED: semantic_models_manager is None")
            return ToolResult(
                success=False,
                error="Knowledge graph not available",
                data={"terms": []}
            )
        
        try:
            # Search concepts in the semantic models / knowledge graph
            # Results are ConceptSearchResult with nested 'concept' (OntologyConcept)
            results = ctx.semantic_models_manager.search_ontology_concepts(term, limit=20)
            
            terms = []
            for result in results:
                # result.concept is OntologyConcept with: iri, label, comment, source_context, etc.
                concept = result.concept
                terms.append({
                    "iri": concept.iri,
                    "name": concept.label or concept.iri.split('#')[-1].split('/')[-1],
                    "definition": concept.comment,
                    "taxonomy": concept.source_context,
                    "relevance_score": result.relevance_score,
                    "match_type": result.match_type
                })
            
            logger.info(f"[search_glossary_terms] SUCCESS: Found {len(results)} matching terms")
            return ToolResult(
                success=True,
                data={
                    "terms": terms[:15],
                    "total_found": len(results),
                    "source": "knowledge_graph"
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                **tool_failure("search_glossary_terms", e),
                data={"terms": []}
            )


class AddSemanticLinkTool(BaseTool):
    """Link a data product or contract to a business term/concept from the knowledge graph."""
    
    name = "add_semantic_link"
    category = "semantic"
    description = "Link a data product or contract to a business term/concept from the knowledge graph. Use search_glossary_terms first to find the concept IRI."
    parameters = {
        "entity_type": {
            "type": "string",
            "description": "Type of entity to link",
            "enum": ["data_product", "data_contract"]
        },
        "entity_id": {
            "type": "string",
            "description": "ID of the entity to link"
        },
        "concept_iri": {
            "type": "string",
            "description": "IRI of the concept from the knowledge graph (from search_glossary_terms results)"
        },
        "concept_label": {
            "type": "string",
            "description": "Human-readable label for the concept"
        },
        "relationship_type": {
            "type": "string",
            "description": "Type of relationship (e.g., 'relatedTo', 'hasDomain', 'hasBusinessTerm')",
            "default": "relatedTo"
        }
    }
    required_params = ["entity_type", "entity_id", "concept_iri", "concept_label"]
    required_scope = "semantic:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        entity_type: str,
        entity_id: str,
        concept_iri: str,
        concept_label: str,
        relationship_type: str = "relatedTo"
    ) -> ToolResult:
        """Add a semantic link from an entity to a knowledge graph concept."""
        logger.info(f"[add_semantic_link] Starting - entity_type={entity_type}, entity_id={entity_id}, concept_iri={concept_iri}")
        
        try:
            from src.controller.semantic_links_manager import SemanticLinksManager
            from src.models.semantic_links import EntitySemanticLinkCreate
            
            # Create manager instance
            manager = SemanticLinksManager(
                db=ctx.db,
                semantic_models_manager=ctx.semantic_models_manager
            )
            
            # Check if link already exists
            existing_links = manager.list_for_entity(entity_id=entity_id, entity_type=entity_type)
            for link in existing_links:
                if link.iri == concept_iri:
                    return ToolResult(
                        success=True,
                        data={
                            "success": True,
                            "message": f"Semantic link to '{concept_label}' already exists for this {entity_type}",
                            "link_id": link.id,
                            "already_linked": True
                        }
                    )
            
            # Create the link
            link_data = EntitySemanticLinkCreate(
                entity_type=entity_type,
                entity_id=entity_id,
                iri=concept_iri,
                label=concept_label,
                relationship_type=relationship_type
            )
            
            created = manager.add(link_data, created_by="llm-assistant")
            ctx.db.commit()
            
            logger.info(f"[add_semantic_link] SUCCESS: Linked {entity_type} {entity_id} to concept '{concept_label}'")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "message": f"Linked {entity_type} to business term '{concept_label}'",
                    "link_id": created.id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "concept_iri": concept_iri,
                    "concept_label": concept_label,
                    "relationship_type": relationship_type
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, **tool_failure("add_semantic_link", e))


class ListSemanticLinksTool(BaseTool):
    """List semantic links (business term associations) for a data product or contract."""
    
    name = "list_semantic_links"
    category = "semantic"
    description = "List semantic links (business term associations) for a data product or contract."
    parameters = {
        "entity_type": {
            "type": "string",
            "description": "Type of entity",
            "enum": ["data_product", "data_contract"]
        },
        "entity_id": {
            "type": "string",
            "description": "ID of the entity"
        }
    }
    required_params = ["entity_type", "entity_id"]
    required_scope = "semantic:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        entity_type: str,
        entity_id: str
    ) -> ToolResult:
        """List semantic links for an entity."""
        logger.info(f"[list_semantic_links] Starting - entity_type={entity_type}, entity_id={entity_id}")
        
        try:
            from src.controller.semantic_links_manager import SemanticLinksManager
            
            # Create manager instance
            manager = SemanticLinksManager(
                db=ctx.db,
                semantic_models_manager=ctx.semantic_models_manager
            )
            
            links = manager.list_for_entity(entity_id=entity_id, entity_type=entity_type)
            
            link_list = []
            for link in links:
                link_list.append({
                    "id": link.id,
                    "iri": link.iri,
                    "label": link.label,
                    "relationship_type": link.relationship_type,
                    "created_at": link.created_at.isoformat() if link.created_at else None
                })
            
            logger.info(f"[list_semantic_links] SUCCESS: Found {len(link_list)} links for {entity_type} {entity_id}")
            return ToolResult(
                success=True,
                data={
                    "links": link_list,
                    "total_found": len(link_list),
                    "entity_type": entity_type,
                    "entity_id": entity_id
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                **tool_failure("list_semantic_links", e),
                data={"links": []}
            )


class RemoveSemanticLinkTool(BaseTool):
    """Remove a semantic link from a data product or contract."""
    
    name = "remove_semantic_link"
    category = "semantic"
    description = "Remove a semantic link from a data product or contract. Use list_semantic_links first to find the link ID."
    parameters = {
        "link_id": {
            "type": "string",
            "description": "ID of the semantic link to remove (from list_semantic_links)"
        }
    }
    required_params = ["link_id"]
    required_scope = "semantic:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        link_id: str
    ) -> ToolResult:
        """Remove a semantic link."""
        logger.info(f"[remove_semantic_link] Starting - link_id={link_id}")
        
        try:
            from src.controller.semantic_links_manager import SemanticLinksManager
            
            # Create manager instance
            manager = SemanticLinksManager(
                db=ctx.db,
                semantic_models_manager=ctx.semantic_models_manager
            )
            
            # Remove the link
            success = manager.remove(link_id, removed_by="llm-assistant")
            
            if not success:
                return ToolResult(
                    success=False,
                    error=f"Semantic link '{link_id}' not found"
                )
            
            ctx.db.commit()
            
            logger.info(f"[remove_semantic_link] SUCCESS: Removed link {link_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "message": "Semantic link removed successfully",
                    "link_id": link_id
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, **tool_failure("remove_semantic_link", e))


class FindEntitiesByConceptTool(BaseTool):
    """Find all entities (data products, contracts, etc.) linked to a semantic concept."""
    
    name = "find_entities_by_concept"
    category = "semantic"
    description = "Given a concept IRI from the knowledge graph, find all data products, contracts, and other entities that are semantically linked to it. Use search_glossary_terms first to find the concept IRI."
    parameters = {
        "concept_iri": {
            "type": "string",
            "description": "IRI of the concept from the knowledge graph (from search_glossary_terms results)"
        }
    }
    required_params = ["concept_iri"]
    required_scope = "semantic:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        concept_iri: str
    ) -> ToolResult:
        """Find all entities linked to a concept IRI."""
        logger.info(f"[find_entities_by_concept] Starting - concept_iri={concept_iri}")
        
        try:
            from src.controller.semantic_links_manager import SemanticLinksManager
            
            # Create manager instance
            manager = SemanticLinksManager(
                db=ctx.db,
                semantic_models_manager=ctx.semantic_models_manager
            )
            
            # Get all entities linked to this concept (explicit + inferred)
            links = manager.list_for_iri(iri=concept_iri)
            
            entities = []
            for link in links:
                entities.append({
                    "entity_type": link.entity_type,
                    "entity_id": link.entity_id,
                    "label": link.label,
                    "link_id": link.id,
                    "is_inferred": link.id.startswith("inferred:") if link.id else False
                })
            
            logger.info(f"[find_entities_by_concept] SUCCESS: Found {len(entities)} entities linked to concept")
            return ToolResult(
                success=True,
                data={
                    "entities": entities,
                    "total_found": len(entities),
                    "concept_iri": concept_iri
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                **tool_failure("find_entities_by_concept", e),
                data={"entities": []}
            )


class ExecuteSparqlQueryTool(BaseTool):
    """Execute SPARQL queries against the semantic model graph."""
    
    name = "execute_sparql_query"
    category = "semantic"
    description = "Execute SPARQL queries against the semantic model graph with safety validation. Only SELECT, ASK, DESCRIBE, and CONSTRUCT queries are allowed."
    parameters = {
        "sparql": {
            "type": "string",
            "description": "SPARQL query to execute (SELECT, ASK, DESCRIBE, CONSTRUCT only)"
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return (default: 100, max: 1000)"
        },
        "timeout_seconds": {
            "type": "integer",
            "description": "Query timeout in seconds (default: 30, max: 60)"
        }
    }
    required_params = ["sparql"]
    required_scope = "sparql:query"
    
    async def execute(
        self,
        ctx: ToolContext,
        sparql: str,
        max_results: int = 100,
        timeout_seconds: int = 30
    ) -> ToolResult:
        """Execute a SPARQL query."""
        logger.info(f"[execute_sparql_query] Starting - query length={len(sparql)}")
        
        if not ctx.semantic_models_manager:
            logger.warning("[execute_sparql_query] FAILED: semantic_models_manager is None")
            return ToolResult(
                success=False,
                error="Semantic models not available",
                data={"results": []}
            )
        
        # Enforce limits
        max_results = min(max_results, 1000)
        timeout_seconds = min(timeout_seconds, 60)
        
        try:
            import time
            start_time = time.time()
            
            # Execute query using existing validated query method
            results = ctx.semantic_models_manager.query(
                sparql,
                max_results=max_results,
                timeout_seconds=timeout_seconds
            )
            
            query_time_ms = int((time.time() - start_time) * 1000)
            
            logger.info(f"[execute_sparql_query] SUCCESS: {len(results)} results in {query_time_ms}ms")
            return ToolResult(
                success=True,
                data={
                    "results": results,
                    "count": len(results),
                    "query_time_ms": query_time_ms,
                    "truncated": len(results) >= max_results
                }
            )
            
        except ValueError as e:
            # Validation errors from SPARQLQueryValidator
            logger.warning(f"[execute_sparql_query] VALIDATION FAILED: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                data={"results": []}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                **tool_failure("execute_sparql_query", e),
                data={"results": []}
            )


class GetConceptHierarchyTool(BaseTool):
    """Navigate concept hierarchies to find parent, child, and sibling relationships."""
    
    name = "get_concept_hierarchy"
    category = "semantic"
    description = "Get hierarchical relationships for a concept including ancestors, descendants, and siblings. Use search_glossary_terms first to find the concept IRI."
    parameters = {
        "concept_iri": {
            "type": "string",
            "description": "IRI of the concept to explore (e.g., 'http://ontos.app/terms#Customer')"
        }
    }
    required_params = ["concept_iri"]
    required_scope = "semantic:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        concept_iri: str
    ) -> ToolResult:
        """Get concept hierarchy."""
        logger.info(f"[get_concept_hierarchy] Starting - concept_iri={concept_iri}")
        
        if not ctx.semantic_models_manager:
            logger.warning("[get_concept_hierarchy] FAILED: semantic_models_manager is None")
            return ToolResult(
                success=False,
                error="Semantic models not available"
            )
        
        try:
            hierarchy = ctx.semantic_models_manager.get_concept_hierarchy(concept_iri)
            
            if not hierarchy:
                return ToolResult(
                    success=False,
                    error=f"Concept not found: {concept_iri}"
                )
            
            # Format the response
            result = {
                "concept": {
                    "iri": hierarchy.concept.iri,
                    "label": hierarchy.concept.label,
                    "comment": hierarchy.concept.comment,
                    "concept_type": hierarchy.concept.concept_type,
                    "source_context": hierarchy.concept.source_context
                },
                "ancestors": [
                    {
                        "iri": a.iri,
                        "label": a.label,
                        "concept_type": a.concept_type
                    }
                    for a in hierarchy.ancestors
                ],
                "descendants": [
                    {
                        "iri": d.iri,
                        "label": d.label,
                        "concept_type": d.concept_type
                    }
                    for d in hierarchy.descendants
                ],
                "siblings": [
                    {
                        "iri": s.iri,
                        "label": s.label,
                        "concept_type": s.concept_type
                    }
                    for s in hierarchy.siblings
                ]
            }
            
            logger.info(f"[get_concept_hierarchy] SUCCESS: {len(hierarchy.ancestors)} ancestors, {len(hierarchy.descendants)} descendants, {len(hierarchy.siblings)} siblings")
            return ToolResult(success=True, data=result)
            
        except Exception as e:
            return ToolResult(success=False, **tool_failure("get_concept_hierarchy", e))


class GetConceptNeighborsTool(BaseTool):
    """Discover related concepts through RDF graph relationships."""
    
    name = "get_concept_neighbors"
    category = "semantic"
    description = "Get neighboring concepts and properties connected to a concept via RDF predicates. Shows incoming and outgoing relationships."
    parameters = {
        "concept_iri": {
            "type": "string",
            "description": "IRI of the concept to explore"
        },
        "max_neighbors": {
            "type": "integer",
            "description": "Maximum number of neighbors to return (default: 50, max: 200)"
        }
    }
    required_params = ["concept_iri"]
    required_scope = "semantic:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        concept_iri: str,
        max_neighbors: int = 50
    ) -> ToolResult:
        """Get concept neighbors."""
        logger.info(f"[get_concept_neighbors] Starting - concept_iri={concept_iri}")
        
        if not ctx.semantic_models_manager:
            logger.warning("[get_concept_neighbors] FAILED: semantic_models_manager is None")
            return ToolResult(
                success=False,
                error="Semantic models not available"
            )
        
        # Enforce limit
        max_neighbors = min(max_neighbors, 200)
        
        try:
            neighbors = ctx.semantic_models_manager.neighbors(concept_iri, limit=max_neighbors)
            
            # Separate into outgoing and incoming
            outgoing = []
            incoming = []
            
            for n in neighbors:
                neighbor_info = {
                    "predicate": n.get("predicate"),
                    "display": n.get("display"),
                    "display_type": n.get("displayType"),
                    "step_iri": n.get("stepIri"),
                    "is_resource": n.get("stepIsResource", False)
                }
                
                if n.get("direction") == "outgoing":
                    outgoing.append(neighbor_info)
                elif n.get("direction") == "incoming":
                    incoming.append(neighbor_info)
            
            logger.info(f"[get_concept_neighbors] SUCCESS: {len(outgoing)} outgoing, {len(incoming)} incoming")
            return ToolResult(
                success=True,
                data={
                    "concept_iri": concept_iri,
                    "outgoing": outgoing,
                    "incoming": incoming,
                    "total_outgoing": len(outgoing),
                    "total_incoming": len(incoming)
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                **tool_failure("get_concept_neighbors", e),
                data={"outgoing": [], "incoming": []}
            )

