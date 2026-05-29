/**
 * LLM Search Types
 * 
 * TypeScript types for the conversational LLM search feature.
 */

// ============================================================================
// Enums
// ============================================================================

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool';

export type ToolName = 
  | 'search_data_products'
  | 'search_glossary_terms'
  | 'get_data_product_costs'
  | 'get_table_schema'
  | 'execute_analytics_query';


// ============================================================================
// Tool Call Types
// ============================================================================

export interface ToolCall {
  id: string;
  name: ToolName;
  arguments: Record<string, unknown>;
}

export interface ToolResult {
  tool_call_id: string;
  success: boolean;
  result?: Record<string, unknown>;
  error?: string;
}


// ============================================================================
// Message Types
// ============================================================================

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string | null;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  timestamp: string;
}

export interface ChatMessageCreate {
  content: string;
  session_id?: string;
  debug?: boolean;
}


// ============================================================================
// Session Types
// ============================================================================

export interface ConversationSession {
  id: string;
  user_id: string;
  title?: string;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}

export interface SessionSummary {
  id: string;
  title?: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}


// ============================================================================
// Response Types
// ============================================================================

export interface DebugToolExecution {
  tool_call_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  success: boolean;
  error?: string;
  result?: Record<string, unknown>;
  execution_ms: number;
}

export interface DebugIteration {
  iteration: number;
  llm_call_ms: number;
  messages_sent: number;
  has_tool_calls: boolean;
  tool_calls: Array<{ tool: string; arguments: Record<string, unknown> }>;
  response_preview?: string;
}

export interface DebugSessionContext {
  prior_messages: number;
  prior_tool_results: number;
  is_follow_up: boolean;
}

export interface DebugInfo {
  query_classification: {
    user_query: string;
    categories: string[];
    tools_provided: string[];
    tools_count: number;
  };
  model: string;
  system_prompt_length: number;
  session_context?: DebugSessionContext;
  iterations: DebugIteration[];
  tool_executions: DebugToolExecution[];
  total_tool_calls: number;
  total_iterations: number;
  total_elapsed_ms: number;
  max_iterations_reached?: boolean;
}

export interface ChatResponse {
  session_id: string;
  message: ChatMessage;
  tool_calls_executed: number;
  sources: ToolSource[];
  debug?: DebugInfo | null;
}

export interface ToolSource {
  tool: ToolName;
  args: Record<string, unknown>;
  success: boolean;
  error?: string;
}

export type AdoptionMode = 'blank' | 'active';

export interface LLMSearchStatus {
  enabled: boolean;
  endpoint?: string;
  model_name?: string;
  disclaimer: string;
  /**
   * Workspace adoption mode used to pick mode-aware starter prompts.
   * `null` (or absent) means the backend snapshot was unavailable;
   * the UI should fall back to its default starter list in that case.
   */
  adoption_mode?: AdoptionMode | null;
}


// ============================================================================
// Tool Result Data Types
// ============================================================================

export interface DataProductSearchResult {
  id: string;
  name: string;
  domain?: string;
  description?: string;
  status: string;
  output_tables: string[];
  version?: string;
}

export interface GlossaryTermResult {
  id: string;
  name: string;
  definition: string;
  domain?: string;
  synonyms: string[];
  tagged_assets: Array<{
    id?: string;
    name: string;
    type: string;
    path?: string;
  }>;
}

export interface CostBreakdown {
  product_id: string;
  product_name: string;
  total_usd: number;
  items: Array<{
    title: string;
    cost_center: string;
    amount_usd: number;
    description?: string;
  }>;
}

export interface TableSchemaResult {
  table_fqn: string;
  columns: Array<{
    name: string;
    type: string;
    nullable?: boolean;
    comment?: string;
  }>;
  table_type?: string;
  comment?: string;
}

export interface QueryExecutionResult {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  explanation: string;
  truncated: boolean;
}

