"""
LLM Search Manager

Orchestrates conversational LLM search with tool-calling capabilities.
Uses Claude Sonnet 4.5 via Databricks serving endpoints to answer
business questions about data products, glossary terms, costs, and analytics.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from src.common.config import Settings, get_settings
from src.common.logging import get_logger
from src.controller.system_prompts import get_system_prompt
from src.models.llm_search import (
    ConversationSession, ChatMessage, ChatResponse, MessageRole,
    ToolCall, ToolName, SessionSummary, LLMSearchStatus,
    SearchDataProductsParams, SearchGlossaryTermsParams,
    GetDataProductCostsParams, GetTableSchemaParams, ExecuteAnalyticsQueryParams
)
from src.tools import ToolRegistry, ToolContext, create_default_registry

logger = get_logger(__name__)


# Internal grounding markers — the system prompt instructs the model to emit
# two kinds of markers so reviewers can audit grounding, but neither belongs in
# the user-facing response. Strip server-side as a safety net:
#   1. `<!-- ref: file.md#anchor -->` — citation comments. Most markdown
#      renderers drop HTML comments, but the chat UI surfaces them as text.
#   2. `[Confirmed]` / `[Documented]` / `[Inferred]` — three-tier confidence
#      labels. The model still emits them so the act of stratifying anchors
#      the answer in the right source; we capture for audit but hide from
#      end users.
# Capture both into debug_info (`internal_citations`, `confidence_labels`).
_CITATION_COMMENT_RE = re.compile(r"<!--\s*ref:\s*([^>]+?)\s*-->")
_CONFIDENCE_LABEL_RE = re.compile(r"\s*\[(Confirmed|Documented|Inferred)\]")


def _strip_internal_citations(text: str) -> Tuple[str, List[str], List[str]]:
    """Remove internal grounding markers from the response.

    Returns (cleaned_text, citations, confidence_labels). The cleaned text has
    both kinds of markers removed and any triple-newlines created by the strip
    collapsed back to doubles.
    """
    if not text:
        return text, [], []
    citations = [m.strip() for m in _CITATION_COMMENT_RE.findall(text)]
    confidence_labels = list(_CONFIDENCE_LABEL_RE.findall(text))
    cleaned = _CITATION_COMMENT_RE.sub("", text)
    cleaned = _CONFIDENCE_LABEL_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
    return cleaned, citations, confidence_labels


# ============================================================================
# System Prompt
# ============================================================================
#
# The default prompt and the `LLM_SYSTEM_PROMPT` env-override path now live
# in `src.controller.system_prompts.get_system_prompt`. This manager calls
# it once per `_process_with_llm` invocation. Phase 2/3 will start passing
# personalization context (role, page, selected entity, adoption mode)
# through that function — the signature already accepts those.


# ============================================================================
# Session Storage - Database-backed with in-memory cache
# ============================================================================

from src.repositories.llm_sessions_repository import llm_sessions_repository, LLMSessionsRepository
from src.db_models.llm_sessions import LLMSessionDb, LLMMessageDb

# Type alias for clarity (Session is SQLAlchemy Session, already imported at top)
SQLSession = Session


class DatabaseSessionStore:
    """
    Database-backed session storage with in-memory write-through cache.
    
    Sessions are persisted to the database but cached in memory for the
    duration of a request to avoid repeated DB queries during tool execution.
    """
    
    def __init__(self, repository: LLMSessionsRepository):
        self._repository = repository
        # In-memory cache for active sessions (within a request)
        self._cache: Dict[str, ConversationSession] = {}
        self.max_sessions_per_user: int = 50
        self.session_ttl_days: int = 30
    
    def _db_to_pydantic(self, db_session: LLMSessionDb) -> ConversationSession:
        """Convert DB session to Pydantic model."""
        messages = []
        for db_msg in db_session.messages:
            tool_calls = None
            if db_msg.tool_calls:
                try:
                    tool_calls_data = json.loads(db_msg.tool_calls)
                    tool_calls = [
                        ToolCall(
                            id=tc['id'],
                            name=ToolName(tc['name']),
                            arguments=tc.get('arguments', {})
                        )
                        for tc in tool_calls_data
                    ]
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f"Failed to parse tool_calls for message {db_msg.id}: {e}")
            
            messages.append(ChatMessage(
                id=db_msg.id,
                role=MessageRole(db_msg.role),
                content=db_msg.content,
                tool_calls=tool_calls,
                tool_call_id=db_msg.tool_call_id,
                timestamp=db_msg.timestamp
            ))
        
        return ConversationSession(
            id=db_session.id,
            user_id=db_session.user_id,
            title=db_session.title,
            messages=messages,
            created_at=db_session.created_at,
            updated_at=db_session.updated_at
        )
    
    def get(self, db: SQLSession, session_id: str) -> Optional[ConversationSession]:
        """Get a session by ID."""
        # Check cache first
        if session_id in self._cache:
            return self._cache[session_id]
        
        # Load from database
        db_session = self._repository.get_session(db, session_id)
        if db_session:
            session = self._db_to_pydantic(db_session)
            self._cache[session_id] = session
            return session
        return None
    
    def get_for_user(self, db: SQLSession, session_id: str, user_id: str) -> Optional[ConversationSession]:
        """Get a session by ID if owned by user."""
        session = self.get(db, session_id)
        if session and session.user_id == user_id:
            return session
        return None
    
    def create(self, db: SQLSession, user_id: str) -> ConversationSession:
        """Create a new session for a user."""
        db_session = self._repository.create_session(db, user_id)
        session = self._db_to_pydantic(db_session)
        self._cache[session.id] = session
        return session
    
    def delete(self, db: SQLSession, session_id: str, user_id: str) -> bool:
        """Delete a session if owned by user."""
        result = self._repository.delete_session_for_user(db, session_id, user_id)
        if result and session_id in self._cache:
            del self._cache[session_id]
        return result
    
    def list_for_user(self, db: SQLSession, user_id: str) -> List[SessionSummary]:
        """List sessions for a user."""
        db_sessions = self._repository.list_sessions_for_user(db, user_id, limit=self.max_sessions_per_user)
        return [
            SessionSummary(
                id=s.id,
                title=s.title,
                message_count=len(s.messages),
                created_at=s.created_at,
                updated_at=s.updated_at
            )
            for s in db_sessions
        ]
    
    def add_message(
        self,
        db: SQLSession,
        session_id: str,
        role: MessageRole,
        content: Optional[str] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        tool_call_id: Optional[str] = None
    ) -> ChatMessage:
        """Add a message to a session and persist to DB."""
        db_session = self._repository.get_session(db, session_id)
        if not db_session:
            raise ValueError(f"Session {session_id} not found")
        
        # Serialize tool calls for DB
        tool_calls_json = None
        if tool_calls:
            tool_calls_json = [
                {'id': tc.id, 'name': tc.name.value, 'arguments': tc.arguments}
                for tc in tool_calls
            ]
        
        db_message = self._repository.add_message(
            db=db,
            session=db_session,
            role=role.value,
            content=content,
            tool_calls=tool_calls_json,
            tool_call_id=tool_call_id
        )
        
        # Create Pydantic message
        message = ChatMessage(
            id=db_message.id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            timestamp=db_message.timestamp
        )
        
        # Update cache
        if session_id in self._cache:
            self._cache[session_id].messages.append(message)
            self._cache[session_id].updated_at = db_session.updated_at
            if not self._cache[session_id].title and db_session.title:
                self._cache[session_id].title = db_session.title
        
        return message
    
    def clear_cache(self):
        """Clear the in-memory cache (call at end of request)."""
        self._cache.clear()


# Global singleton session store
_global_session_store = DatabaseSessionStore(llm_sessions_repository)


def get_session_store() -> DatabaseSessionStore:
    """Get the global session store singleton."""
    return _global_session_store


# ============================================================================
# LLM Search Manager
# ============================================================================

class LLMSearchManager:
    """
    Orchestrates conversational LLM search with tool-calling.
    
    Architecture:
    1. User sends message
    2. LLM processes with available tools
    3. If LLM requests tool calls, execute them via ToolRegistry
    4. Feed results back to LLM
    5. Repeat until LLM provides final response
    """
    
    def __init__(
        self,
        db: Session,
        settings: Settings,
        data_products_manager: Optional[Any] = None,
        data_contracts_manager: Optional[Any] = None,
        semantic_models_manager: Optional[Any] = None,
        costs_manager: Optional[Any] = None,
        search_manager: Optional[Any] = None,
        workspace_client: Optional[Any] = None
    ):
        self._db = db
        self._settings = settings
        self._data_products_manager = data_products_manager
        self._data_contracts_manager = data_contracts_manager
        self._semantic_models_manager = semantic_models_manager
        self._costs_manager = costs_manager
        self._search_manager = search_manager
        self._ws_client = workspace_client
        self._session_store = get_session_store()  # Use global singleton
        
        # Initialize tool registry with all default tools
        self._tool_registry = create_default_registry()
        
        logger.info(f"LLMSearchManager initialized (ws_client={workspace_client is not None}, semantic_models_manager={semantic_models_manager is not None}, tools={len(self._tool_registry)})")
    
    def _create_tool_context(self) -> ToolContext:
        """Create a ToolContext with current dependencies."""
        return ToolContext(
            db=self._db,
            settings=self._settings,
            workspace_client=self._ws_client,
            data_products_manager=self._data_products_manager,
            data_contracts_manager=self._data_contracts_manager,
            semantic_models_manager=self._semantic_models_manager,
            costs_manager=self._costs_manager,
            search_manager=self._search_manager
        )
    
    def _get_latest_user_message(self, session: ConversationSession) -> str:
        """Get the latest user message content from a session for query classification."""
        for msg in reversed(session.messages):
            if msg.role == MessageRole.USER and msg.content:
                return msg.content
        return ""
    
    # ========================================================================
    # Public API
    # ========================================================================
    
    def get_status(self) -> LLMSearchStatus:
        """Get the status of LLM search functionality."""
        model = self._settings.LLM_ENDPOINT
        return LLMSearchStatus(
            enabled=self._settings.LLM_ENABLED,
            endpoint=model,
            model_name=model,
            disclaimer=self._settings.LLM_DISCLAIMER_TEXT or (
                "This feature uses AI to analyze data assets. AI-generated content may contain errors. "
                "Review all suggestions carefully before taking action."
            )
        )
    
    def list_sessions(self, user_id: str) -> List[SessionSummary]:
        """List conversation sessions for a user."""
        return self._session_store.list_for_user(self._db, user_id)
    
    def delete_session(self, session_id: str, user_id: str) -> bool:
        """Delete a session if owned by user."""
        return self._session_store.delete(self._db, session_id, user_id)
    
    def get_session(self, session_id: str, user_id: str) -> Optional[ConversationSession]:
        """Get a session by ID if owned by user."""
        return self._session_store.get_for_user(self._db, session_id, user_id)
    
    async def chat(
        self,
        user_message: str,
        user_id: str,
        session_id: Optional[str] = None,
        debug: bool = False
    ) -> ChatResponse:
        """
        Process a chat message and return the assistant's response.
        
        Note: The workspace client passed to this manager should already have
        user credentials (OBO) for proper access control and audit trail.
        
        Args:
            user_message: The user's message
            user_id: ID of the user
            session_id: Optional session ID to continue conversation
            debug: When true, include debug info in the response
            
        Returns:
            ChatResponse with the assistant's message
        """
        # Check if LLM is enabled
        if not self._settings.LLM_ENABLED:
            logger.warning("LLM chat requested but LLM_ENABLED is False")
            return ChatResponse(
                session_id="",
                message=ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content="LLM search is not enabled. Please contact your administrator."
                ),
                tool_calls_executed=0,
                sources=[]
            )
        
        # Get or create session
        if session_id:
            session = self._session_store.get_for_user(self._db, session_id, user_id)
            if not session:
                session = self._session_store.create(self._db, user_id)
        else:
            session = self._session_store.create(self._db, user_id)
        
        # Add user message to database (also updates in-memory cache)
        self._session_store.add_message(
            self._db, session.id, MessageRole.USER, content=user_message
        )
        # Re-fetch session from cache to ensure we have updated messages
        session = self._session_store.get(self._db, session.id)
        
        # Process with LLM
        try:
            response_content, tool_calls_executed, sources, debug_info = await self._process_with_llm(
                session, collect_debug=debug
            )
            
            # Add assistant response to database
            assistant_msg = self._session_store.add_message(
                self._db, session.id, MessageRole.ASSISTANT, content=response_content
            )
            
            return ChatResponse(
                session_id=session.id,
                message=assistant_msg,
                tool_calls_executed=tool_calls_executed,
                sources=sources,
                debug=debug_info if debug else None
            )
            
        except Exception as e:
            logger.error(f"Error processing chat: {e}", exc_info=True)
            
            # Create a user-friendly error message
            error_type = type(e).__name__
            if "ValidationError" in str(e):
                user_message = (
                    "I encountered a validation error while processing a request. "
                    "This typically happens when data doesn't match expected formats. "
                    f"Details: {str(e)[:200]}"
                )
            elif "timeout" in str(e).lower() or "timed out" in str(e).lower():
                user_message = (
                    "The request timed out. This might happen with complex queries. "
                    "Please try a simpler question or try again later."
                )
            elif "connection" in str(e).lower() or "network" in str(e).lower():
                user_message = (
                    "I had trouble connecting to a required service. "
                    "Please try again in a moment."
                )
            else:
                user_message = (
                    f"I encountered an error while processing your request ({error_type}). "
                    "Please try rephrasing your question or try again."
                )
            
            # Try to persist the error message to the session
            try:
                error_msg = self._session_store.add_message(
                    self._db, session.id, MessageRole.ASSISTANT,
                    content=user_message
                )
                return ChatResponse(
                    session_id=session.id,
                    message=error_msg,
                    tool_calls_executed=0,
                    sources=[]
                )
            except Exception as persist_error:
                # If we can't persist the error message (e.g., session was lost),
                # return a synthetic response without persisting
                logger.error(f"Failed to persist error message to session: {persist_error}", exc_info=True)
                synthetic_msg = ChatMessage(
                    id=str(uuid.uuid4()),
                    role=MessageRole.ASSISTANT,
                    content=user_message,
                    timestamp=datetime.utcnow()
                )
                return ChatResponse(
                    session_id=session.id,
                    message=synthetic_msg,
                    tool_calls_executed=0,
                    sources=[]
                )
    
    # ========================================================================
    # LLM Processing
    # ========================================================================
    
    async def _process_with_llm(
        self,
        session: ConversationSession,
        collect_debug: bool = False
    ) -> Tuple[str, int, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Process conversation with LLM, handling tool calls.
        
        Returns:
            Tuple of (response_content, tool_calls_count, sources, debug_info)
        """
        import time
        
        process_start = time.time()
        client = self._get_openai_client()
        total_tool_calls = 0
        sources: List[Dict[str, Any]] = []
        max_iterations = 10
        session_id = session.id
        
        # Debug info collection
        debug_info: Optional[Dict[str, Any]] = {
            "iterations": [],
            "tool_executions": [],
        } if collect_debug else None
        
        # Get the latest user message for query classification
        from src.tools.query_classifier import classify_query
        user_query = self._get_latest_user_message(session)
        categories = classify_query(user_query)

        # Get filtered tool definitions based on query categories
        tool_definitions = self._tool_registry.get_openai_definitions_filtered(categories)
        tool_names = [td["function"]["name"] for td in tool_definitions]
        logger.info(f"Using {len(tool_definitions)} tools for categories: {categories}")

        # Resolve the system prompt once per chat invocation. The
        # `get_system_prompt` helper honors `Settings.LLM_SYSTEM_PROMPT`
        # as a verbatim override (previously dead code) and otherwise
        # returns the default grounded prompt. Phase 2/3 will pass role
        # / page / entity / adoption-mode context here.
        system_prompt = get_system_prompt(settings=self._settings)

        if debug_info is not None:
            debug_info["query_classification"] = {
                "user_query": user_query,
                "categories": categories,
                "tools_provided": tool_names,
                "tools_count": len(tool_definitions),
            }
            debug_info["model"] = self._settings.LLM_ENDPOINT
            debug_info["system_prompt_length"] = len(system_prompt)
            debug_info["system_prompt_source"] = (
                "env_override" if self._settings.LLM_SYSTEM_PROMPT else "default"
            )
            # Count prior messages to show if the LLM has conversation context
            prior_msgs = session.messages[:-1]  # exclude the just-added user message
            prior_tool_msgs = [m for m in prior_msgs if m.role == MessageRole.TOOL]
            debug_info["session_context"] = {
                "prior_messages": len(prior_msgs),
                "prior_tool_results": len(prior_tool_msgs),
                "is_follow_up": len(prior_msgs) > 0,
            }
        
        for iteration in range(max_iterations):
            iter_start = time.time()
            
            # Re-fetch session from cache to ensure we have latest messages
            current_session = self._session_store.get(self._db, session_id)
            if not current_session:
                raise RuntimeError(f"Session {session_id} not found in cache")
            
            # Build messages for LLM
            messages = current_session.get_messages_for_llm(system_prompt)
            
            # Call LLM
            try:
                logger.debug(f"Calling LLM (iteration {iteration + 1}/{max_iterations})")
                response = client.chat.completions.create(
                    model=self._settings.LLM_ENDPOINT,
                    messages=messages,
                    tools=tool_definitions,
                    tool_choice="auto",
                    max_tokens=4096
                )
                logger.debug(f"LLM response received successfully")
            except Exception as llm_error:
                logger.error(f"LLM API call failed: {llm_error}", exc_info=True)
                raise RuntimeError(f"Failed to connect to LLM endpoint: {llm_error}")
            
            llm_elapsed_ms = int((time.time() - iter_start) * 1000)
            assistant_message = response.choices[0].message
            
            # Collect iteration debug info
            iter_debug = None
            if debug_info is not None:
                iter_debug = {
                    "iteration": iteration + 1,
                    "llm_call_ms": llm_elapsed_ms,
                    "messages_sent": len(messages),
                    "has_tool_calls": bool(assistant_message.tool_calls),
                    "tool_calls": [],
                    "response_preview": (assistant_message.content or "")[:200] if not assistant_message.tool_calls else None,
                }
            
            # Check if LLM wants to call tools
            if assistant_message.tool_calls:
                # Add assistant message with tool calls to session
                tool_calls = [
                    ToolCall(
                        id=tc.id,
                        name=ToolName(tc.function.name),
                        arguments=json.loads(tc.function.arguments) if tc.function.arguments else {}
                    )
                    for tc in assistant_message.tool_calls
                ]
                self._session_store.add_message(
                    self._db, session_id, MessageRole.ASSISTANT,
                    content=None, tool_calls=tool_calls
                )
                
                ctx = self._create_tool_context()
                
                for tc in assistant_message.tool_calls:
                    total_tool_calls += 1
                    tool_name = tc.function.name
                    tool_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    
                    logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                    
                    tool_start = time.time()
                    result = await self._tool_registry.execute(tool_name, ctx, tool_args)
                    tool_elapsed_ms = int((time.time() - tool_start) * 1000)
                    result_dict = result.to_dict()
                    
                    if not result.success:
                        logger.warning(f"Tool {tool_name} returned error: {result.error}")
                        sources.append({
                            "tool": tool_name,
                            "args": tool_args,
                            "success": False,
                            "error": result.error
                        })
                    else:
                        result_summary = str(result_dict)[:500] + "..." if len(str(result_dict)) > 500 else str(result_dict)
                        logger.info(f"Tool {tool_name} result: {result_summary}")
                        sources.append({
                            "tool": tool_name,
                            "args": tool_args,
                            "success": True
                        })
                    
                    # Collect per-tool debug info
                    if debug_info is not None:
                        result_str = json.dumps(result_dict, default=str)
                        tool_debug = {
                            "tool_call_id": tc.id,
                            "tool": tool_name,
                            "arguments": tool_args,
                            "success": result.success,
                            "error": result.error,
                            "result": result_dict if len(result_str) <= 4000 else {"_truncated": True, "_length": len(result_str), "_preview": result_str[:2000]},
                            "execution_ms": tool_elapsed_ms,
                        }
                        debug_info["tool_executions"].append(tool_debug)
                        if iter_debug is not None:
                            iter_debug["tool_calls"].append({"tool": tool_name, "arguments": tool_args})
                    
                    self._session_store.add_message(
                        self._db, session_id, MessageRole.TOOL,
                        content=json.dumps(result_dict), tool_call_id=tc.id
                    )
            else:
                cleaned_content, citations, confidence_labels = _strip_internal_citations(
                    assistant_message.content or ""
                )
                if debug_info is not None:
                    if iter_debug is not None:
                        debug_info["iterations"].append(iter_debug)
                    debug_info["total_tool_calls"] = total_tool_calls
                    debug_info["total_iterations"] = iteration + 1
                    debug_info["total_elapsed_ms"] = int((time.time() - process_start) * 1000)
                    debug_info["internal_citations"] = citations
                    debug_info["confidence_labels"] = confidence_labels
                return cleaned_content, total_tool_calls, sources, debug_info
            
            if debug_info is not None and iter_debug is not None:
                debug_info["iterations"].append(iter_debug)
        
        # Max iterations reached
        logger.warning(f"Max LLM iterations ({max_iterations}) reached after {total_tool_calls} tool calls")
        if debug_info is not None:
            debug_info["total_tool_calls"] = total_tool_calls
            debug_info["total_iterations"] = max_iterations
            debug_info["total_elapsed_ms"] = int((time.time() - process_start) * 1000)
            debug_info["max_iterations_reached"] = True
        return f"I apologize, but I reached the maximum number of steps ({max_iterations}) while processing your request. I made {total_tool_calls} tool calls. Please try a simpler question or break it into smaller parts.", total_tool_calls, sources, debug_info
    
    def _get_openai_client(self, user_token: Optional[str] = None):
        """Get OpenAI client via the shared factory.

        Args:
            user_token: Per-user OBO token (optional, for Databricks Apps context).
        """
        from src.common.llm_client import create_openai_client

        return create_openai_client(self._settings, user_token=user_token)
