"""
Teams tools for LLM.

Tools for searching, creating, updating, and deleting teams.
"""

from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.repositories.entity_domain_association_repository import entity_domain_repo
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class SearchTeamsTool(BaseTool):
    """Search for teams by name or domain."""
    
    name = "search_teams"
    category = "organization"
    description = "Search for teams by name, title, or domain. Returns matching teams with their member counts."
    parameters = {
        "query": {
            "type": "string",
            "description": "Search query for teams (e.g., 'data engineering', 'analytics')"
        },
        "domain_id": {
            "type": "string",
            "description": "Optional filter by domain ID"
        }
    }
    required_params = ["query"]
    required_scope = "teams:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        query: str,
        domain_id: Optional[str] = None
    ) -> ToolResult:
        """Search for teams."""
        logger.info(f"[search_teams] Starting - query='{query}', domain_id={domain_id}")
        
        try:
            from src.db_models.teams import TeamDb
            from src.repositories.entity_domain_association_repository import entity_domain_repo

            db_query = ctx.db.query(TeamDb)
            if domain_id:
                team_ids = entity_domain_repo.find_entity_ids_by_domain(
                    ctx.db, domain_id=domain_id, entity_type="team"
                )
                db_query = db_query.filter(TeamDb.id.in_(team_ids or ["__none__"]))

            teams_db = db_query.limit(500).all()
            logger.debug(f"[search_teams] Found {len(teams_db)} total teams in database")
            
            if not teams_db:
                return ToolResult(
                    success=True,
                    data={"teams": [], "total_found": 0, "message": "No teams found"}
                )
            
            query_lower = query.lower() if query and query != '*' else ''
            filtered = []
            
            for t in teams_db:
                if not query_lower:
                    include = True
                else:
                    name_match = query_lower in (t.name or "").lower()
                    title_match = query_lower in (t.title or "").lower()
                    desc_match = query_lower in (t.description or "").lower()
                    include = name_match or title_match or desc_match
                
                if include:
                    filtered.append({
                        "id": str(t.id),
                        "name": t.name,
                        "title": t.title,
                        "description": t.description,
                        "domain_ids": [
                            d.domain_id for d in entity_domain_repo.get_domains_for_entity(
                                ctx.db, entity_type="team", entity_id=str(t.id)
                            )
                        ],
                        "member_count": len(t.members) if t.members else 0
                    })
            
            logger.info(f"[search_teams] SUCCESS: Found {len(filtered)} matching teams")
            return ToolResult(
                success=True,
                data={
                    "teams": filtered[:20],
                    "total_found": len(filtered)
                }
            )
            
        except Exception as e:
            logger.error(f"[search_teams] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}", data={"teams": []})


class GetTeamTool(BaseTool):
    """Get a single team by ID."""
    
    name = "get_team"
    category = "organization"
    description = "Get detailed information about a specific team by its ID, including its members."
    parameters = {
        "team_id": {
            "type": "string",
            "description": "The ID of the team to retrieve"
        }
    }
    required_params = ["team_id"]
    required_scope = "teams:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        team_id: str
    ) -> ToolResult:
        """Get a team by ID."""
        logger.info(f"[get_team] Starting - team_id={team_id}")
        
        try:
            from src.controller.teams_manager import teams_manager
            
            team = teams_manager.get_team_by_id(ctx.db, team_id)
            
            if not team:
                return ToolResult(
                    success=False,
                    error=f"Team '{team_id}' not found"
                )
            
            members = []
            if team.members:
                for m in team.members[:10]:  # Limit members in response
                    members.append({
                        "member_identifier": m.member_identifier,
                        "member_type": m.member_type
                    })
            
            logger.info(f"[get_team] SUCCESS: Found team {team_id}")
            return ToolResult(
                success=True,
                data={
                    "id": str(team.id),
                    "name": team.name,
                    "title": team.title,
                    "description": team.description,
                    "domains": [
                        {"domain_id": d.domain_id, "domain_name": d.domain_name, "is_primary": d.is_primary}
                        for d in entity_domain_repo.get_domains_for_entity(
                            ctx.db, entity_type="team", entity_id=str(team.id)
                        )
                    ],
                    "member_count": len(team.members) if team.members else 0,
                    "members": members,
                    "created_at": team.created_at.isoformat() if team.created_at else None
                }
            )
            
        except Exception as e:
            logger.error(f"[get_team] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class CreateTeamTool(BaseTool):
    """Create a new team."""
    
    name = "create_team"
    category = "organization"
    description = "Create a new team. Teams can be assigned to domains and contain members (users or groups)."
    parameters = {
        "name": {
            "type": "string",
            "description": "Unique name for the team (e.g., 'data-engineering-team')"
        },
        "title": {
            "type": "string",
            "description": "Display title for the team (e.g., 'Data Engineering Team')"
        },
        "description": {
            "type": "string",
            "description": "Description of the team's purpose and responsibilities"
        },
        "domain_id": {
            "type": "string",
            "description": "Optional: ID of the domain this team belongs to"
        }
    }
    required_params = ["name", "title"]
    required_scope = "teams:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        name: str,
        title: str,
        description: Optional[str] = None,
        domain_id: Optional[str] = None
    ) -> ToolResult:
        """Create a team."""
        logger.info(f"[create_team] Starting - name='{name}', title='{title}'")
        
        try:
            from src.controller.teams_manager import teams_manager
            from src.models.teams import TeamCreate
            
            team_create = TeamCreate(
                name=name,
                title=title,
                description=description or "",
                domain_ids=[domain_id] if domain_id else [],
                primary_domain_id=domain_id or None,
            )
            
            created = teams_manager.create_team(
                db=ctx.db,
                team_in=team_create,
                current_user_id="llm-assistant"
            )
            
            ctx.db.commit()
            
            logger.info(f"[create_team] SUCCESS: Created team id={created.id}, name={created.name}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "team_id": str(created.id),
                    "name": created.name,
                    "title": created.title,
                    "message": f"Team '{title}' created successfully.",
                    "url": f"/teams/{created.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[create_team] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class UpdateTeamTool(BaseTool):
    """Update an existing team."""
    
    name = "update_team"
    category = "organization"
    description = "Update an existing team's name, title, description, or domain assignment."
    parameters = {
        "team_id": {
            "type": "string",
            "description": "ID of the team to update"
        },
        "name": {
            "type": "string",
            "description": "New unique name for the team"
        },
        "title": {
            "type": "string",
            "description": "New display title"
        },
        "description": {
            "type": "string",
            "description": "New description"
        },
        "domain_id": {
            "type": "string",
            "description": "New domain ID (or null to remove domain assignment)"
        }
    }
    required_params = ["team_id"]
    required_scope = "teams:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        team_id: str,
        name: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        domain_id: Optional[str] = None
    ) -> ToolResult:
        """Update a team."""
        logger.info(f"[update_team] Starting - team_id={team_id}")
        
        try:
            from src.controller.teams_manager import teams_manager
            from src.models.teams import TeamUpdate
            
            update_data: Dict[str, Any] = {}
            if name is not None:
                update_data["name"] = name
            if title is not None:
                update_data["title"] = title
            if description is not None:
                update_data["description"] = description
            if domain_id is not None:
                # Single-domain tool contract maps onto multi-domain replace-all.
                update_data["domain_ids"] = [domain_id] if domain_id else []
                update_data["primary_domain_id"] = domain_id or None

            if not update_data:
                return ToolResult(
                    success=False,
                    error="No fields to update. Provide at least one of: name, title, description, domain_id"
                )
            
            team_update = TeamUpdate(**update_data)
            
            updated = teams_manager.update_team(
                db=ctx.db,
                team_id=team_id,
                team_in=team_update,
                current_user_id="llm-assistant"
            )
            
            if not updated:
                return ToolResult(
                    success=False,
                    error=f"Team '{team_id}' not found"
                )
            
            ctx.db.commit()
            
            logger.info(f"[update_team] SUCCESS: Updated team id={updated.id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "team_id": str(updated.id),
                    "name": updated.name,
                    "title": updated.title,
                    "message": f"Team '{updated.title}' updated successfully.",
                    "url": f"/teams/{updated.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[update_team] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class DeleteTeamTool(BaseTool):
    """Delete a team."""
    
    name = "delete_team"
    category = "organization"
    description = "Delete a team by its ID. This will also remove all team member associations."
    parameters = {
        "team_id": {
            "type": "string",
            "description": "The ID of the team to delete"
        }
    }
    required_params = ["team_id"]
    required_scope = "teams:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        team_id: str
    ) -> ToolResult:
        """Delete a team."""
        logger.info(f"[delete_team] Starting - team_id={team_id}")
        
        try:
            from src.controller.teams_manager import teams_manager
            
            deleted = teams_manager.delete_team(ctx.db, team_id)
            
            if not deleted:
                return ToolResult(
                    success=False,
                    error=f"Team '{team_id}' not found or could not be deleted"
                )
            
            ctx.db.commit()
            
            logger.info(f"[delete_team] SUCCESS: Deleted team {team_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "message": f"Team '{deleted.name}' deleted successfully",
                    "team_id": team_id
                }
            )
            
        except Exception as e:
            logger.error(f"[delete_team] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")
