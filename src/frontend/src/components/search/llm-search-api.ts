/**
 * Shared API functions for LLM Search / Copilot features.
 */

import type {
  ChatResponse,
  LLMSearchStatus,
  SessionSummary,
} from '@/types/llm-search';
import { useCopilotStore, type CopilotEntity } from '@/stores/copilot-store';

/**
 * Wire-shape for ``POST /api/llm-search/chat``. Mirrors the
 * ``ChatMessageCreate`` Pydantic model on the backend (Phase 3 fields
 * are optional — pre-Phase 3 clients still work).
 */
interface ChatRequestBody {
  content: string;
  session_id?: string;
  debug?: boolean;
  page_name?: string;
  page_url?: string;
  feature_id?: string;
  selected_entity?: CopilotEntity;
}

export async function fetchLLMStatus(): Promise<LLMSearchStatus> {
  const response = await fetch('/api/llm-search/status');
  if (!response.ok) throw new Error('Failed to fetch LLM status');
  return response.json();
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const response = await fetch('/api/llm-search/sessions');
  if (!response.ok) throw new Error('Failed to fetch sessions');
  return response.json();
}

export async function sendMessage(content: string, sessionId?: string, debug?: boolean): Promise<ChatResponse> {
  // Read page context directly from the Zustand store. ``getState()``
  // is the supported escape hatch for non-component callers (this is
  // a plain async function, not a hook). Pulling here keeps both the
  // copilot panel and the LLMSearch page on the same payload shape
  // without forcing them to pass it explicitly.
  const pageContext = useCopilotStore.getState().pageContext;

  const body: ChatRequestBody = {
    content,
    session_id: sessionId,
    debug: debug || false,
  };
  if (pageContext) {
    if (pageContext.pageName) body.page_name = pageContext.pageName;
    if (pageContext.pageUrl) body.page_url = pageContext.pageUrl;
    if (pageContext.featureId) body.feature_id = pageContext.featureId;
    if (pageContext.selectedEntity) body.selected_entity = pageContext.selectedEntity;
  }

  const response = await fetch('/api/llm-search/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Chat request failed' }));
    throw new Error(error.detail || 'Chat request failed');
  }
  return response.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/llm-search/sessions/${sessionId}`, {
    method: 'DELETE',
  });
  if (!response.ok && response.status !== 204) {
    throw new Error('Failed to delete session');
  }
}
