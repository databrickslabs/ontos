"""The search index entry of an asset: its name, type, domains and tags.

Shared by AssetsManager (full writes) and TagsManager (tag writes, tag rename and delete),
so a tag change refreshes the entry without going through AssetsManager.
"""
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import object_session

from src.common.search_interfaces import SearchIndexItem
from src.db_models.assets import AssetDb
from src.repositories.entity_domain_association_repository import entity_domain_repo

if TYPE_CHECKING:
    from src.controller.tags_manager import TagsManager


def build_asset_search_item(
    asset_db_obj: AssetDb,
    tags_manager: "TagsManager",
    preloaded_domains=None,
    preloaded_tags=None,
) -> Optional[SearchIndexItem]:
    """Convert a single asset DB object to a SearchIndexItem. Returns None for retired assets.

    ``preloaded_domains`` (a list of AssignedDomain) lets the bulk indexer batch the
    junction lookup once instead of querying per asset (avoids N+1); when omitted the
    single-item path queries via the object's session.
    """
    if asset_db_obj.status == 'retired':
        return None
    type_name = asset_db_obj.asset_type.name if asset_db_obj.asset_type else 'Asset'
    assigned_tags = preloaded_tags
    if assigned_tags is None:
        _tag_session = object_session(asset_db_obj)
        assigned_tags = tags_manager.list_assigned_tags(
            _tag_session, entity_id=str(asset_db_obj.id), entity_type="asset"
        ) if _tag_session is not None else []
    # Tag names (as before the shared store) and their FQNs, so a search by either finds it
    tags = list(dict.fromkeys(
        term for t in assigned_tags for term in (t.tag_name, t.fully_qualified_name) if term
    ))
    primary_domain_id = None
    assigned = preloaded_domains
    if assigned is None:
        _session = object_session(asset_db_obj)
        assigned = entity_domain_repo.get_domains_for_entity(
            _session, entity_type="asset", entity_id=str(asset_db_obj.id)
        ) if _session is not None else []
    if assigned:
        # Index every assigned domain NAME so domain-keyed search matches by any of
        # an entity's domains (primary or additional) — issue #520 story 14.
        primary_domain_id = next((d.domain_id for d in assigned if d.is_primary), None)
        tags = tags + [d.domain_name for d in assigned if d.domain_name]
    return SearchIndexItem(
        id=f"asset::{asset_db_obj.id}",
        type=f"asset-{type_name.lower().replace(' ', '-')}",
        title=asset_db_obj.name,
        description=asset_db_obj.description or '',
        link=f"/assets/{asset_db_obj.id}",
        tags=tags,
        feature_id="assets",
        extra_data={
            "asset_type": type_name,
            "platform": asset_db_obj.platform or '',
            "status": asset_db_obj.status or '',
            "domain_id": primary_domain_id or '',
        },
    )
