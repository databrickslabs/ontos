"""
Search configuration loader utility.

Loads, validates, and saves search_config.yaml.
Provides caching and hot-reload support.
"""
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

import yaml
from pydantic import ValidationError

from src.models.search_config import (
    SearchConfig,
    DefaultsConfig,
    DefaultFieldsConfig,
    AssetTypeConfig,
    FieldConfig,
    RankingConfig,
    MatchType,
    SortField,
)
from src.common.logging import get_logger

logger = get_logger(__name__)

# Default config file path
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "data" / "search_config.yaml"


class SearchConfigLoader:
    """
    Loader for search configuration.
    
    Handles:
    - Loading from YAML file
    - Validation via Pydantic models
    - Saving updates back to YAML
    - Caching with file modification detection
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the config loader.
        
        Args:
            config_path: Path to the search_config.yaml file.
                         Defaults to src/data/search_config.yaml
        """
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._config: Optional[SearchConfig] = None
        self._last_modified: Optional[float] = None
        logger.info(f"SearchConfigLoader initialized with path: {self.config_path}")
    
    def _file_modified(self) -> bool:
        """Check if the config file has been modified since last load."""
        try:
            current_mtime = os.path.getmtime(self.config_path)
            return self._last_modified is None or current_mtime > self._last_modified
        except OSError:
            return True
    
    def load(self, force_reload: bool = False) -> SearchConfig:
        """
        Load the search configuration.
        
        Uses cached config if file hasn't changed, unless force_reload is True.
        
        Args:
            force_reload: If True, reload from disk regardless of cache
            
        Returns:
            SearchConfig: The loaded configuration
        """
        # Return cached config if file hasn't changed
        if not force_reload and self._config is not None and not self._file_modified():
            return self._config
        
        logger.info(f"Loading search config from {self.config_path}")
        
        try:
            if not self.config_path.exists():
                logger.warning(f"Config file not found at {self.config_path}, using defaults")
                self._config = self._create_default_config()
                return self._config
            
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
            
            if raw_data is None:
                logger.warning("Config file is empty, using defaults")
                self._config = self._create_default_config()
                return self._config
            
            # Parse and validate using Pydantic. A malformed structure (e.g. a YAML
            # list at the root) is rejected loudly, never replaced by defaults.
            if not isinstance(raw_data, dict):
                logger.warning(
                    "Search config %s is not a YAML mapping (got %s); rejecting it",
                    self.config_path, type(raw_data).__name__,
                )
                raise ValueError("Search config must be a YAML mapping")
            try:
                self._config = self._parse_config(raw_data)
            except (AttributeError, TypeError, KeyError) as e:
                logger.warning("Search config %s has a malformed section: %s", self.config_path, e)
                raise ValueError("Search config has a malformed section") from e
            self._last_modified = os.path.getmtime(self.config_path)
            
            logger.info(
                f"Search config loaded successfully: "
                f"version={self._config.version}, "
                f"asset_types={list(self._config.asset_types.keys())}"
            )
            return self._config
            
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML config: {e}")
            raise ValueError(f"Invalid YAML in search config: {e}")
        except ValidationError as e:
            logger.error(f"Config validation failed: {e}")
            raise ValueError(f"Search config validation error: {e}")
    
    def _parse_config(self, raw_data: dict) -> SearchConfig:
        """
        Parse raw YAML data into SearchConfig model.
        
        Handles the nested structure and enum conversions.
        """
        # Parse defaults
        defaults_data = raw_data.get("defaults", {})
        fields_data = defaults_data.get("fields", {})
        
        default_fields = DefaultFieldsConfig(
            title=self._parse_field_config(fields_data.get("title", {})),
            description=self._parse_field_config(fields_data.get("description", {})),
            tags=self._parse_field_config(fields_data.get("tags", {})),
        )
        defaults = DefaultsConfig(fields=default_fields)
        
        # Parse asset types
        asset_types: dict[str, AssetTypeConfig] = {}
        for asset_type, asset_data in raw_data.get("asset_types", {}).items():
            if asset_data is None:
                asset_data = {}
            
            # Parse field overrides
            fields = {}
            for field_name, field_data in asset_data.get("fields", {}).items():
                fields[field_name] = self._parse_field_config(field_data)
            
            # Parse extra fields
            extra_fields = {}
            for field_name, field_data in asset_data.get("extra_fields", {}).items():
                extra_fields[field_name] = self._parse_field_config(field_data)
            
            asset_types[asset_type] = AssetTypeConfig(
                enabled=asset_data.get("enabled", True),
                inherit_defaults=asset_data.get("inherit_defaults", True),
                fields=fields,
                extra_fields=extra_fields,
            )
        
        # Parse ranking
        ranking_data = raw_data.get("ranking", {})
        ranking = RankingConfig(
            primary_sort=self._parse_sort_field(ranking_data.get("primary_sort", "match_priority")),
            secondary_sort=self._parse_sort_field(ranking_data.get("secondary_sort", "boost_score")),
            tertiary_sort=self._parse_sort_field(ranking_data.get("tertiary_sort", "title_asc")),
        )
        
        return SearchConfig(
            version=raw_data.get("version", "1.0"),
            defaults=defaults,
            asset_types=asset_types,
            ranking=ranking,
        )
    
    def _parse_field_config(self, data: dict) -> FieldConfig:
        """Parse a field configuration from raw dict."""
        if not data:
            return FieldConfig()
        
        match_type_str = data.get("match_type", "substring")
        try:
            match_type = MatchType(match_type_str)
        except ValueError:
            logger.warning(f"Unknown match_type '{match_type_str}', defaulting to substring")
            match_type = MatchType.SUBSTRING
        
        return FieldConfig(
            indexed=data.get("indexed", True),
            match_type=match_type,
            priority=data.get("priority", 10),
            boost=data.get("boost", 1.0),
            source=data.get("source"),
        )
    
    def _parse_sort_field(self, value: str) -> SortField:
        """Parse a sort field enum value."""
        try:
            return SortField(value)
        except ValueError:
            logger.warning(f"Unknown sort field '{value}', defaulting to match_priority")
            return SortField.MATCH_PRIORITY
    
    def _create_default_config(self) -> SearchConfig:
        """Create a default configuration when no file exists."""
        return SearchConfig(
            version="1.0",
            defaults=DefaultsConfig(fields=DefaultFieldsConfig()),
            asset_types={
                "data-product": AssetTypeConfig(enabled=True, inherit_defaults=True),
                "data-contract": AssetTypeConfig(enabled=True, inherit_defaults=True),
                "glossary-term": AssetTypeConfig(enabled=True, inherit_defaults=True),
                "dataset": AssetTypeConfig(enabled=True, inherit_defaults=True),
                "data-asset-review": AssetTypeConfig(enabled=True, inherit_defaults=True),
                "tag": AssetTypeConfig(enabled=True, inherit_defaults=True),
                "data-domain": AssetTypeConfig(enabled=True, inherit_defaults=True),
            },
            ranking=RankingConfig(),
        )
    
    def save(self, config: SearchConfig) -> None:
        """
        Save the configuration to YAML file.
        
        Args:
            config: The configuration to save
        """
        logger.info(f"Saving search config to {self.config_path}")
        
        try:
            # Convert to dict for YAML serialization
            data = self._config_to_dict(config)
            
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, "w", encoding="utf-8") as f:
                # Add header comment
                f.write("# Search Configuration\n")
                f.write("# Defines which fields are indexed per asset type, match strategies, and ranking behavior\n")
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            
            # Update cache
            self._config = config
            self._last_modified = os.path.getmtime(self.config_path)
            
            logger.info("Search config saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save search config: {e}")
            raise
    
    def _config_to_dict(self, config: SearchConfig) -> dict:
        """Convert SearchConfig to a dict suitable for YAML serialization."""
        # Build defaults
        defaults = {
            "fields": {
                "title": self._field_config_to_dict(config.defaults.fields.title),
                "description": self._field_config_to_dict(config.defaults.fields.description),
                "tags": self._field_config_to_dict(config.defaults.fields.tags),
            }
        }
        
        # Build asset types
        asset_types = {}
        for asset_type, asset_config in config.asset_types.items():
            asset_dict: dict = {
                "enabled": asset_config.enabled,
                "inherit_defaults": asset_config.inherit_defaults,
            }
            
            if asset_config.fields:
                asset_dict["fields"] = {
                    k: self._field_config_to_dict(v)
                    for k, v in asset_config.fields.items()
                }
            
            if asset_config.extra_fields:
                asset_dict["extra_fields"] = {
                    k: self._field_config_to_dict(v)
                    for k, v in asset_config.extra_fields.items()
                }
            
            asset_types[asset_type] = asset_dict
        
        # Build ranking
        ranking = {
            "primary_sort": config.ranking.primary_sort.value,
            "secondary_sort": config.ranking.secondary_sort.value,
            "tertiary_sort": config.ranking.tertiary_sort.value,
        }
        
        return {
            "version": config.version,
            "defaults": defaults,
            "asset_types": asset_types,
            "ranking": ranking,
        }
    
    def _field_config_to_dict(self, field: FieldConfig) -> dict:
        """Convert FieldConfig to dict."""
        result = {
            "indexed": field.indexed,
            "match_type": field.match_type.value,
            "priority": field.priority,
            "boost": field.boost,
        }
        if field.source:
            result["source"] = field.source
        return result
    
    def update(self, updates: dict) -> SearchConfig:
        """
        Apply partial updates to the configuration.
        
        Args:
            updates: Dictionary with partial updates (defaults, asset_types, ranking)
            
        Returns:
            The updated SearchConfig
        """
        current = self.load()
        
        # Apply updates
        if "defaults" in updates:
            # Merge defaults
            defaults_update = updates["defaults"]
            if "fields" in defaults_update:
                for field_name, field_data in defaults_update["fields"].items():
                    if hasattr(current.defaults.fields, field_name):
                        existing = getattr(current.defaults.fields, field_name)
                        updated = self._merge_field_config(existing, field_data)
                        setattr(current.defaults.fields, field_name, updated)
        
        if "asset_types" in updates:
            for asset_type, asset_data in updates["asset_types"].items():
                if asset_type in current.asset_types:
                    # Merge with existing
                    existing = current.asset_types[asset_type]
                    if "enabled" in asset_data:
                        existing.enabled = asset_data["enabled"]
                    if "inherit_defaults" in asset_data:
                        existing.inherit_defaults = asset_data["inherit_defaults"]
                    if "fields" in asset_data:
                        for field_name, field_data in asset_data["fields"].items():
                            if field_name in existing.fields:
                                existing.fields[field_name] = self._merge_field_config(
                                    existing.fields[field_name], field_data
                                )
                            else:
                                existing.fields[field_name] = self._parse_field_config(field_data)
                    if "extra_fields" in asset_data:
                        for field_name, field_data in asset_data["extra_fields"].items():
                            if field_name in existing.extra_fields:
                                existing.extra_fields[field_name] = self._merge_field_config(
                                    existing.extra_fields[field_name], field_data
                                )
                            else:
                                existing.extra_fields[field_name] = self._parse_field_config(field_data)
                else:
                    # Add new asset type
                    current.asset_types[asset_type] = AssetTypeConfig(
                        enabled=asset_data.get("enabled", True),
                        inherit_defaults=asset_data.get("inherit_defaults", True),
                        fields={k: self._parse_field_config(v) for k, v in asset_data.get("fields", {}).items()},
                        extra_fields={k: self._parse_field_config(v) for k, v in asset_data.get("extra_fields", {}).items()},
                    )
        
        if "ranking" in updates:
            ranking_data = updates["ranking"]
            if "primary_sort" in ranking_data:
                current.ranking.primary_sort = self._parse_sort_field(ranking_data["primary_sort"])
            if "secondary_sort" in ranking_data:
                current.ranking.secondary_sort = self._parse_sort_field(ranking_data["secondary_sort"])
            if "tertiary_sort" in ranking_data:
                current.ranking.tertiary_sort = self._parse_sort_field(ranking_data["tertiary_sort"])
        
        # Save and return
        self.save(current)
        return current
    
    def _merge_field_config(self, existing: FieldConfig, updates: dict) -> FieldConfig:
        """Merge updates into an existing field config."""
        return FieldConfig(
            indexed=updates.get("indexed", existing.indexed),
            match_type=self._parse_match_type(updates.get("match_type", existing.match_type.value)),
            priority=updates.get("priority", existing.priority),
            boost=updates.get("boost", existing.boost),
            source=updates.get("source", existing.source),
        )
    
    def _parse_match_type(self, value: str) -> MatchType:
        """Parse a match type value."""
        if isinstance(value, MatchType):
            return value
        try:
            return MatchType(value)
        except ValueError:
            return MatchType.SUBSTRING


# Singleton instance for global access
_loader_instance: Optional[SearchConfigLoader] = None


def get_search_config_loader() -> SearchConfigLoader:
    """Get the global SearchConfigLoader instance."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = SearchConfigLoader()
    return _loader_instance


def get_search_config() -> SearchConfig:
    """Convenience function to get the current search config."""
    return get_search_config_loader().load()

