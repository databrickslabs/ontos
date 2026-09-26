"""
Projects tools for LLM.

Tools for searching, creating, updating, and deleting projects.
"""

from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.common.search_interfaces import SearchIndexItem
from src.controller import search_scoring
from src.models.search_config import SearchConfig
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class SearchProjectsTool(BaseTool):
    """Search for projects via the shared, tokenized scorer (over DB rows)."""

    name = "search_projects"
    category = "organization"
    description = (
        "Search projects by name, title or description. Use FEW BROAD terms, not full "
        "sentences — each term is matched independently and results are ranked by "
        "relevance. Page with 'offset'. Leave 'query' empty (or '*') to list projects; "
        "the response is always paginated and includes 'total_count' and 'has_more'."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "Search terms (e.g., 'customer analytics', 'data platform'). Empty or '*' lists all projects."
        },
        "limit": {
            "type": "integer",
            "description": "Max results to return (default: 25, max: 100)."
        },
        "offset": {
            "type": "integer",
            "description": "Number of results to skip for pagination (default: 0)."
        }
    }
    required_params = ["query"]
    required_scope = "projects:read"

    async def execute(
        self,
        ctx: ToolContext,
        query: str = "",
        limit: int = 25,
        offset: int = 0,
    ) -> ToolResult:
        """Search projects: DB rows adapted to index items, then tokenized-scored."""
        logger.info(f"[search_projects] Starting - query='{query}', limit={limit}, offset={offset}")

        try:
            from src.db_models.projects import ProjectDb

            projects_db = ctx.db.query(ProjectDb).limit(5000).all()
            logger.debug(f"[search_projects] Found {len(projects_db)} total projects in database")

            # Adapt rows to SearchIndexItem so the shared scorer applies (projects are
            # not part of the persistent search index).
            items = [
                SearchIndexItem(
                    id=f"project::{p.id}",
                    type="project",
                    feature_id="projects",
                    title=p.name or p.title or "",
                    description=p.description,
                    link=f"/projects/{p.id}",
                    tags=[x for x in [p.title, p.project_type] if x],
                )
                for p in projects_db
            ]

            config = ctx.search_manager.config if ctx.search_manager else SearchConfig()
            data = search_scoring.search_index(items, query, config, limit=limit, offset=offset)
            logger.info(f"[search_projects] SUCCESS: returned {data['returned']} of {data['total_count']} matching projects")
            return ToolResult(
                success=True,
                data={
                    "projects": data["results"],
                    "total_found": data["total_count"],
                    "returned": data["returned"],
                    "offset": data["offset"],
                    "limit": data["limit"],
                    "has_more": data["has_more"],
                    "query": query,
                },
            )

        except Exception as e:
            logger.error(f"[search_projects] FAILED: {e.__class__.__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{e.__class__.__name__}: {str(e)}", data={"projects": []})


class GetProjectTool(BaseTool):
    """Get a single project by ID."""
    
    name = "get_project"
    category = "organization"
    description = "Get detailed information about a specific project by its ID, including assigned teams."
    parameters = {
        "project_id": {
            "type": "string",
            "description": "The ID of the project to retrieve"
        }
    }
    required_params = ["project_id"]
    required_scope = "projects:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        project_id: str
    ) -> ToolResult:
        """Get a project by ID."""
        logger.info(f"[get_project] Starting - project_id={project_id}")
        
        try:
            from src.controller.projects_manager import projects_manager
            
            project = projects_manager.get_project_by_id(ctx.db, project_id)
            
            if not project:
                return ToolResult(
                    success=False,
                    error=f"Project '{project_id}' not found"
                )
            
            teams = []
            if project.teams:
                for t in project.teams[:10]:  # Limit teams in response
                    teams.append({
                        "id": str(t.id),
                        "name": t.name
                    })
            
            logger.info(f"[get_project] SUCCESS: Found project {project_id}")
            return ToolResult(
                success=True,
                data={
                    "id": str(project.id),
                    "name": project.name,
                    "title": project.title,
                    "description": project.description,
                    "project_type": project.project_type,
                    "owner_team_id": str(project.owner_team_id) if project.owner_team_id else None,
                    "owner_team_name": project.owner_team_name,
                    "team_count": len(project.teams) if project.teams else 0,
                    "teams": teams,
                    "created_at": project.created_at.isoformat() if project.created_at else None
                }
            )
            
        except Exception as e:
            logger.error(f"[get_project] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class CreateProjectTool(BaseTool):
    """Create a new project."""
    
    name = "create_project"
    category = "organization"
    description = "Create a new project. Projects organize work and can have multiple teams assigned."
    parameters = {
        "name": {
            "type": "string",
            "description": "Unique name for the project (e.g., 'customer-analytics-platform')"
        },
        "title": {
            "type": "string",
            "description": "Display title for the project (e.g., 'Customer Analytics Platform')"
        },
        "description": {
            "type": "string",
            "description": "Description of the project's purpose and scope"
        },
        "project_type": {
            "type": "string",
            "description": "Type of project (e.g., 'standard', 'admin')",
            "enum": ["standard", "admin"]
        },
        "owner_team_id": {
            "type": "string",
            "description": "Optional: ID of the team that owns this project"
        },
        "team_ids": {
            "type": "array",
            "description": "Optional: IDs of teams to assign to this project",
            "items": {"type": "string"}
        }
    }
    required_params = ["name", "title"]
    required_scope = "projects:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        name: str,
        title: str,
        description: Optional[str] = None,
        project_type: Optional[str] = None,
        owner_team_id: Optional[str] = None,
        team_ids: Optional[List[str]] = None
    ) -> ToolResult:
        """Create a project."""
        logger.info(f"[create_project] Starting - name='{name}', title='{title}'")
        
        try:
            from src.controller.projects_manager import projects_manager
            from src.models.projects import ProjectCreate
            
            project_create = ProjectCreate(
                name=name,
                title=title,
                description=description or "",
                project_type=project_type or "standard",
                owner_team_id=owner_team_id,
                team_ids=team_ids or []
            )
            
            created = projects_manager.create_project(
                db=ctx.db,
                project_in=project_create,
                current_user_id="llm-assistant"
            )
            
            ctx.db.commit()
            
            logger.info(f"[create_project] SUCCESS: Created project id={created.id}, name={created.name}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "project_id": str(created.id),
                    "name": created.name,
                    "title": created.title,
                    "message": f"Project '{title}' created successfully.",
                    "url": f"/projects/{created.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[create_project] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class UpdateProjectTool(BaseTool):
    """Update an existing project."""
    
    name = "update_project"
    category = "organization"
    description = "Update an existing project's name, title, description, or owner team."
    parameters = {
        "project_id": {
            "type": "string",
            "description": "ID of the project to update"
        },
        "name": {
            "type": "string",
            "description": "New unique name for the project"
        },
        "title": {
            "type": "string",
            "description": "New display title"
        },
        "description": {
            "type": "string",
            "description": "New description"
        },
        "owner_team_id": {
            "type": "string",
            "description": "New owner team ID"
        }
    }
    required_params = ["project_id"]
    required_scope = "projects:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        project_id: str,
        name: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        owner_team_id: Optional[str] = None
    ) -> ToolResult:
        """Update a project."""
        logger.info(f"[update_project] Starting - project_id={project_id}")
        
        try:
            from src.controller.projects_manager import projects_manager
            from src.models.projects import ProjectUpdate
            
            update_data: Dict[str, Any] = {}
            if name is not None:
                update_data["name"] = name
            if title is not None:
                update_data["title"] = title
            if description is not None:
                update_data["description"] = description
            if owner_team_id is not None:
                update_data["owner_team_id"] = owner_team_id if owner_team_id else None
            
            if not update_data:
                return ToolResult(
                    success=False,
                    error="No fields to update. Provide at least one of: name, title, description, owner_team_id"
                )
            
            project_update = ProjectUpdate(**update_data)
            
            updated = projects_manager.update_project(
                db=ctx.db,
                project_id=project_id,
                project_in=project_update,
                current_user_id="llm-assistant"
            )
            
            if not updated:
                return ToolResult(
                    success=False,
                    error=f"Project '{project_id}' not found"
                )
            
            ctx.db.commit()
            
            logger.info(f"[update_project] SUCCESS: Updated project id={updated.id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "project_id": str(updated.id),
                    "name": updated.name,
                    "title": updated.title,
                    "message": f"Project '{updated.title}' updated successfully.",
                    "url": f"/projects/{updated.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[update_project] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class DeleteProjectTool(BaseTool):
    """Delete a project."""
    
    name = "delete_project"
    category = "organization"
    description = "Delete a project by its ID. This will also remove all team assignments for this project."
    parameters = {
        "project_id": {
            "type": "string",
            "description": "The ID of the project to delete"
        }
    }
    required_params = ["project_id"]
    required_scope = "projects:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        project_id: str
    ) -> ToolResult:
        """Delete a project."""
        logger.info(f"[delete_project] Starting - project_id={project_id}")
        
        try:
            from src.controller.projects_manager import projects_manager
            
            deleted = projects_manager.delete_project(ctx.db, project_id)
            
            if not deleted:
                return ToolResult(
                    success=False,
                    error=f"Project '{project_id}' not found or could not be deleted"
                )
            
            ctx.db.commit()
            
            logger.info(f"[delete_project] SUCCESS: Deleted project {project_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "message": f"Project '{deleted.name}' deleted successfully",
                    "project_id": project_id
                }
            )
            
        except Exception as e:
            logger.error(f"[delete_project] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")
