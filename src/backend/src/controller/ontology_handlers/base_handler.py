"""
Base class for ontology handlers.

Each handler knows how to:
1. Parse the module structure from the YAML definition
2. Fetch ontology files from remote sources or cache
3. Combine selected modules into a single graph
4. Resolve dependencies between modules
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import hashlib
import json

from rdflib import Graph, ConjunctiveGraph
from rdflib.namespace import RDF, RDFS, OWL, SKOS

from src.models.industry_ontology import (
    IndustryOntology,
    ModuleTreeNode,
    OntologyModule,
    MaturityLevel,
)
from src.common.logging import get_logger
from src.owl.owl_parser import clean_truncated_turtle

logger = get_logger(__name__)


class OntologyHandler(ABC):
    """
    Abstract base class for ontology handlers.
    
    Subclasses implement specific logic for different ontology types:
    - SimpleOWLHandler: Single-file ontologies
    - FIBOHandler: Hierarchical domain/module structure
    - SchemaOrgHandler: Schema.org vocabulary
    - etc.
    """
    
    # Cache TTL in seconds (default 7 days)
    CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
    
    def __init__(self, cache_dir: Path):
        """
        Initialize the handler.
        
        Args:
            cache_dir: Directory for caching downloaded ontology files
        """
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    def get_module_tree(self, ontology: IndustryOntology) -> List[ModuleTreeNode]:
        """
        Build the module selection tree for the UI.
        
        Args:
            ontology: The ontology definition from the registry
            
        Returns:
            List of root nodes for the tree view
        """
        pass
    
    @abstractmethod
    def resolve_dependencies(
        self, 
        ontology: IndustryOntology, 
        selected_ids: List[str]
    ) -> Tuple[List[str], List[str]]:
        """
        Resolve all dependencies for the selected modules.
        
        Args:
            ontology: The ontology definition
            selected_ids: List of selected module path IDs
            
        Returns:
            Tuple of (all_required_ids, auto_added_ids)
            - all_required_ids: Complete list including dependencies
            - auto_added_ids: Dependencies that were automatically added
        """
        pass
    
    @abstractmethod
    def fetch_modules(
        self, 
        ontology: IndustryOntology, 
        module_ids: List[str],
        force_refresh: bool = False
    ) -> Dict[str, str]:
        """
        Fetch the content of selected modules.
        
        Args:
            ontology: The ontology definition
            module_ids: List of module path IDs to fetch
            force_refresh: If True, bypass cache and fetch fresh
            
        Returns:
            Dict mapping module_id to content string
        """
        pass
    
    @abstractmethod
    def combine_modules(
        self, 
        ontology: IndustryOntology,
        module_contents: Dict[str, str]
    ) -> Graph:
        """
        Combine multiple module contents into a single RDF graph.
        
        Args:
            ontology: The ontology definition
            module_contents: Dict mapping module_id to content string
            
        Returns:
            Combined RDF graph
        """
        pass
    
    # =========================================================================
    # Common utility methods
    # =========================================================================
    
    def get_cache_path(self, ontology_id: str, module_id: str) -> Path:
        """Get the cache file path for a module."""
        # Create safe filename from IDs
        safe_name = f"{ontology_id}_{module_id}".replace("/", "_").replace(":", "_")
        return self._cache_dir / f"{safe_name}.ttl"
    
    def get_cache_meta_path(self, ontology_id: str, module_id: str) -> Path:
        """Get the cache metadata file path."""
        safe_name = f"{ontology_id}_{module_id}".replace("/", "_").replace(":", "_")
        return self._cache_dir / f"{safe_name}.meta.json"
    
    def is_cached(self, ontology_id: str, module_id: str) -> bool:
        """Check if a module is cached."""
        cache_path = self.get_cache_path(ontology_id, module_id)
        meta_path = self.get_cache_meta_path(ontology_id, module_id)
        return cache_path.exists() and meta_path.exists()
    
    def is_cache_stale(self, ontology_id: str, module_id: str) -> bool:
        """Check if cached module is stale (older than TTL)."""
        meta_path = self.get_cache_meta_path(ontology_id, module_id)
        if not meta_path.exists():
            return True
        
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            cached_at = datetime.fromisoformat(meta.get('cached_at', ''))
            return datetime.now() - cached_at > timedelta(seconds=self.CACHE_TTL_SECONDS)
        except Exception:
            return True
    
    def read_from_cache(self, ontology_id: str, module_id: str) -> Optional[str]:
        """Read module content from cache."""
        cache_path = self.get_cache_path(ontology_id, module_id)
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to read cache for {ontology_id}/{module_id}: {e}")
            return None
    
    def write_to_cache(
        self, 
        ontology_id: str, 
        module_id: str, 
        content: str,
        source_url: Optional[str] = None
    ) -> None:
        """Write module content to cache."""
        cache_path = self.get_cache_path(ontology_id, module_id)
        meta_path = self.get_cache_meta_path(ontology_id, module_id)
        
        try:
            # Write content
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Write metadata
            meta = {
                'ontology_id': ontology_id,
                'module_id': module_id,
                'cached_at': datetime.now().isoformat(),
                'source_url': source_url,
                'content_hash': hashlib.sha256(content.encode()).hexdigest(),
                'size_bytes': len(content.encode('utf-8')),
            }
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2)
                
            logger.debug(f"Cached {ontology_id}/{module_id} ({len(content)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to write cache for {ontology_id}/{module_id}: {e}")
    
    def clear_cache(self, ontology_id: str, module_id: Optional[str] = None) -> int:
        """
        Clear cached files.
        
        Args:
            ontology_id: Ontology ID
            module_id: If provided, clear only this module; otherwise clear all for ontology
            
        Returns:
            Number of files cleared
        """
        count = 0
        pattern = f"{ontology_id}_"
        if module_id:
            pattern = f"{ontology_id}_{module_id}".replace("/", "_").replace(":", "_")
        
        for f in self._cache_dir.iterdir():
            if f.name.startswith(pattern):
                try:
                    f.unlink()
                    count += 1
                except Exception:
                    pass
        
        return count
    
    def detect_format(self, content: str, url: Optional[str] = None) -> str:
        """
        Detect the RDF format of content.
        
        Args:
            content: The content string
            url: Optional URL hint
            
        Returns:
            Format string for rdflib (e.g., 'turtle', 'xml', 'json-ld')
        """
        # Check URL extension first
        if url:
            url_lower = url.lower()
            if url_lower.endswith('.ttl'):
                return 'turtle'
            elif url_lower.endswith('.rdf') or url_lower.endswith('.xml') or url_lower.endswith('.owl'):
                return 'xml'
            elif url_lower.endswith('.jsonld') or url_lower.endswith('.json'):
                return 'json-ld'
            elif url_lower.endswith('.nt'):
                return 'nt'
            elif url_lower.endswith('.n3'):
                return 'n3'
        
        # Try to detect from content
        content_stripped = content.strip()
        
        # JSON-LD starts with { or [
        if content_stripped.startswith('{') or content_stripped.startswith('['):
            return 'json-ld'
        
        # XML/RDF starts with <?xml or <rdf:RDF
        if content_stripped.startswith('<?xml') or content_stripped.startswith('<rdf:RDF'):
            return 'xml'
        
        # N-Triples: each line is a triple ending with .
        lines = content_stripped.split('\n')
        if all(line.strip().endswith('.') or line.strip().startswith('#') or not line.strip() 
               for line in lines[:10] if line.strip()):
            # Could be N-Triples or Turtle
            if '@prefix' in content_stripped or '@base' in content_stripped:
                return 'turtle'
            return 'nt'
        
        # Default to Turtle (most common)
        return 'turtle'
    
    def parse_graph(self, content: str, format_hint: Optional[str] = None, url: Optional[str] = None) -> Graph:
        """
        Parse content into an RDF graph.
        
        Args:
            content: The content string
            format_hint: Optional format hint
            url: Optional URL for format detection
            
        Returns:
            Parsed RDF graph
        """
        g = Graph()
        
        # Determine format
        if format_hint:
            fmt = format_hint
        else:
            fmt = self.detect_format(content, url)
        
        # Map format names
        format_map = {
            'rdfxml': 'xml',
            'turtle': 'turtle',
            'jsonld': 'json-ld',
            'json-ld': 'json-ld',
            'owl': 'xml',
            'n3': 'n3',
            'nt': 'nt',
            'ntriples': 'nt',
        }
        fmt = format_map.get(fmt, fmt)
        
        cleaned_content = clean_truncated_turtle(content) if fmt in ('turtle', 'n3') else content
        try:
            g.parse(data=cleaned_content, format=fmt)
        except Exception as e:
            # Try alternative formats
            for alt_fmt in ['turtle', 'xml', 'json-ld', 'nt']:
                if alt_fmt != fmt:
                    try:
                        alt_content = (
                            clean_truncated_turtle(content) if alt_fmt in ('turtle', 'n3') else content
                        )
                        g.parse(data=alt_content, format=alt_fmt)
                        logger.debug(f"Parsed as {alt_fmt} after {fmt} failed")
                        break
                    except Exception:
                        continue
            else:
                raise ValueError(f"Failed to parse content: {e}")
        
        return g
    
    def create_module_node(
        self,
        id: str,
        name: str,
        node_type: str,
        description: Optional[str] = None,
        maturity: Optional[MaturityLevel] = None,
        owl_url: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        children: Optional[List[ModuleTreeNode]] = None,
        selectable: bool = True,
    ) -> ModuleTreeNode:
        """Helper to create a ModuleTreeNode."""
        return ModuleTreeNode(
            id=id,
            name=name,
            node_type=node_type,
            description=description,
            maturity=maturity,
            owl_url=owl_url,
            dependencies=dependencies or [],
            children=children or [],
            selectable=selectable,
        )
