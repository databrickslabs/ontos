/**
 * LLM Search Component
 * 
 * Conversational AI interface for querying data products, costs,
 * glossary terms, and executing analytics queries.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Send, Bot, User, Loader2, AlertCircle, Trash2, MessageSquare, Plus, ChevronDown, Sparkles, RefreshCw, Pencil, Bug, ChevronRight, Clock, Wrench, CheckCircle2, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useToast } from '@/hooks/use-toast';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import LLMConsentDialog, { hasLLMConsent } from '@/components/common/llm-consent-dialog';
import type { LLMConfig } from '@/types/llm';
import type {
  ChatMessage,
  DebugInfo,
  LLMSearchStatus,
  SessionSummary,
} from '@/types/llm-search';
import { fetchLLMStatus, fetchSessions, sendMessage, deleteSession } from './llm-search-api';


// ============================================================================
// Message Component
// ============================================================================

interface MessageProps {
  message: ChatMessage;
  debugInfo?: DebugInfo | null;
  onRerun?: (content: string) => void;
  onCopyToInput?: (content: string) => void;
}

function Message({ message, debugInfo, onRerun, onCopyToInput }: MessageProps) {
  const { t } = useTranslation(['search']);
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  
  // Don't render tool messages (they're internal)
  if (message.role === 'tool' || message.role === 'system') {
    return null;
  }
  
  // Don't render assistant messages that are just tool calls (no content)
  if (isAssistant && !message.content && message.tool_calls) {
    return null;
  }

  return (
    <div className="space-y-1">
      <div className={`group flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
        {/* Avatar */}
        <div className={`
          flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center
          ${isUser 
            ? 'bg-sky-500 dark:bg-sky-600 text-white' 
            : 'bg-gradient-to-br from-violet-500 to-purple-600 text-white'
          }
        `}>
          {isUser ? <User className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
        </div>
        
        {/* Message Content */}
        <div className={`
          flex-1 max-w-[80%] rounded-lg px-4 py-3 relative
          ${isUser 
            ? 'bg-sky-100 dark:bg-sky-900/50 text-sky-900 dark:text-sky-100' 
            : 'bg-muted'
          }
        `}>
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown 
                remarkPlugins={[remarkGfm]}
                components={{
                  // Custom table styling
                  table: ({ children }) => (
                    <div className="overflow-x-auto my-2">
                      <table className="min-w-full border-collapse text-sm">
                        {children}
                      </table>
                    </div>
                  ),
                  th: ({ children }) => (
                    <th className="border border-border bg-muted px-3 py-2 text-left font-medium">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-border px-3 py-2">
                      {children}
                    </td>
                  ),
                  // Code blocks
                  code: ({ className, children, ...props }) => {
                    const isInline = !className;
                    return isInline ? (
                      <code className="bg-muted-foreground/20 px-1 py-0.5 rounded text-sm" {...props}>
                        {children}
                      </code>
                    ) : (
                      <code className={`${className} block bg-zinc-900 text-zinc-100 p-3 rounded-md overflow-x-auto`} {...props}>
                        {children}
                      </code>
                    );
                  },
                }}
              >
                {message.content || ''}
              </ReactMarkdown>
            </div>
          )}
          
          {/* Timestamp */}
          <div className={`text-xs mt-2 opacity-60 ${isUser ? 'text-right' : ''}`}>
            {new Date(message.timestamp).toLocaleTimeString()}
          </div>

          {/* Hover actions for user messages */}
          {isUser && message.content && (
            <div className="absolute -left-2 top-1/2 -translate-y-1/2 -translate-x-full flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-muted-foreground hover:text-foreground"
                onClick={() => onCopyToInput?.(message.content || '')}
                title={t('search:llm.copyToInput')}
              >
                <Pencil className="w-3.5 h-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-muted-foreground hover:text-foreground"
                onClick={() => onRerun?.(message.content || '')}
                title={t('search:llm.rerun')}
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Debug panel below assistant messages */}
      {isAssistant && debugInfo && <DebugPanel debug={debugInfo} />}
    </div>
  );
}


// ============================================================================
// Debug Panel Component
// ============================================================================

interface DebugPanelProps {
  debug: DebugInfo;
}

function DebugPanel({ debug }: DebugPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const hasSessionContext = debug.session_context?.is_follow_up && debug.session_context.prior_tool_results > 0;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className="ml-11">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1.5 h-7 text-xs text-muted-foreground hover:text-foreground px-2">
          <Bug className="w-3 h-3" />
          <span>Debug</span>
          <ChevronRight className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
          <span className="opacity-60">
            {debug.total_tool_calls} tool call{debug.total_tool_calls !== 1 ? 's' : ''}
            {hasSessionContext && ` (${debug.session_context!.prior_tool_results} prior)`}
            {' '}&middot; {debug.total_elapsed_ms}ms
          </span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1 rounded-md border border-border bg-muted/50 p-3 text-xs space-y-3 font-mono">
          {/* Session Context */}
          {hasSessionContext && (
            <>
              <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                <MessageSquare className="w-3 h-3" />
                <span>Follow-up: LLM has {debug.session_context!.prior_messages} prior messages ({debug.session_context!.prior_tool_results} tool results) in conversation history</span>
              </div>
              <Separator />
            </>
          )}

          {/* Query Classification */}
          <div>
            <div className="font-semibold text-muted-foreground mb-1">Query Classification</div>
            <div className="space-y-1">
              <div><span className="text-muted-foreground">Query:</span> {debug.query_classification.user_query}</div>
              <div className="flex flex-wrap gap-1 items-center">
                <span className="text-muted-foreground">Categories:</span>
                {debug.query_classification.categories.map((cat) => (
                  <Badge key={cat} variant="secondary" className="text-[10px] px-1.5 py-0">{cat}</Badge>
                ))}
              </div>
              <div><span className="text-muted-foreground">Tools provided:</span> {debug.query_classification.tools_count} ({debug.query_classification.tools_provided.join(', ')})</div>
            </div>
          </div>

          <Separator />

          {/* Model Info */}
          <div className="flex flex-wrap gap-4">
            <div><span className="text-muted-foreground">Model:</span> {debug.model}</div>
            <div><span className="text-muted-foreground">Iterations:</span> {debug.total_iterations}</div>
            <div className="flex items-center gap-1">
              <Clock className="w-3 h-3 text-muted-foreground" />
              <span>{debug.total_elapsed_ms}ms total</span>
            </div>
          </div>

          {/* Tool Executions */}
          {debug.tool_executions.length > 0 && (
            <>
              <Separator />
              <div>
                <div className="font-semibold text-muted-foreground mb-2">Tool Executions</div>
                <div className="space-y-2">
                  {debug.tool_executions.map((exec, idx) => (
                    <ToolExecutionDetail key={idx} exec={exec} />
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Iterations */}
          {debug.iterations.length > 1 && (
            <>
              <Separator />
              <div>
                <div className="font-semibold text-muted-foreground mb-1">LLM Iterations</div>
                {debug.iterations.map((iter, idx) => (
                  <div key={idx} className="flex gap-3 text-muted-foreground">
                    <span>#{iter.iteration}</span>
                    <span>{iter.llm_call_ms}ms</span>
                    <span>{iter.messages_sent} msgs</span>
                    {iter.has_tool_calls && <span>{iter.tool_calls.length} tool call(s)</span>}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function ToolExecutionDetail({ exec }: { exec: DebugInfo['tool_executions'][0] }) {
  const [showResult, setShowResult] = useState(false);

  return (
    <div className="rounded border border-border bg-background p-2 space-y-1">
      <div className="flex items-center gap-2">
        <Wrench className="w-3 h-3 text-muted-foreground" />
        <span className="font-semibold">{exec.tool}</span>
        {exec.success ? (
          <CheckCircle2 className="w-3 h-3 text-green-500" />
        ) : (
          <XCircle className="w-3 h-3 text-red-500" />
        )}
        <span className="text-muted-foreground ml-auto">{exec.execution_ms}ms</span>
      </div>
      <div className="text-muted-foreground">
        <span>Args: </span>
        <code className="text-[10px] break-all">{JSON.stringify(exec.arguments)}</code>
      </div>
      {exec.error && (
        <div className="text-red-500">Error: {exec.error}</div>
      )}
      {exec.result && (
        <Collapsible open={showResult} onOpenChange={setShowResult}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-5 text-[10px] px-1 text-muted-foreground">
              <ChevronRight className={`w-2.5 h-2.5 mr-0.5 transition-transform ${showResult ? 'rotate-90' : ''}`} />
              {showResult ? 'Hide result' : 'Show result'}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-1 p-2 rounded bg-zinc-900 text-zinc-100 text-[10px] overflow-x-auto max-h-48 overflow-y-auto">
              {JSON.stringify(exec.result, null, 2)}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}


// ============================================================================
// Session List Component
// ============================================================================

interface SessionListProps {
  sessions: SessionSummary[];
  currentSessionId?: string;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onNewSession: () => void;
}

function SessionList({ 
  sessions, 
  currentSessionId, 
  onSelectSession, 
  onDeleteSession,
  onNewSession 
}: SessionListProps) {
  const { t } = useTranslation(['search', 'common']);

  if (sessions.length === 0) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <MessageSquare className="w-4 h-4" />
          {t('search:llm.history')}
          <ChevronDown className="w-3 h-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuItem onClick={onNewSession} className="gap-2">
          <Plus className="w-4 h-4" />
          {t('search:llm.newConversation')}
        </DropdownMenuItem>
        <Separator className="my-1" />
        {sessions.map((session) => (
          <DropdownMenuItem
            key={session.id}
            className={`flex justify-between items-center gap-2 ${
              session.id === currentSessionId ? 'bg-accent' : ''
            }`}
            onClick={() => onSelectSession(session.id)}
          >
            <span className="truncate flex-1">
              {session.title || t('search:llm.untitled')}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 opacity-60 hover:opacity-100"
              onClick={(e) => {
                e.stopPropagation();
                onDeleteSession(session.id);
              }}
            >
              <Trash2 className="w-3 h-3" />
            </Button>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}


// ============================================================================
// Example Questions Component
// ============================================================================

interface ExampleQuestionsProps {
  onSelectQuestion: (question: string) => void;
}

function ExampleQuestions({ onSelectQuestion }: ExampleQuestionsProps) {
  const { t } = useTranslation(['search']);

  const examples = [
    t('search:llm.examples.findCustomerData'),
    t('search:llm.examples.dataProductsCost'),
    t('search:llm.examples.businessTermsSales'),
    t('search:llm.examples.showDataProducts'),
  ];

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">{t('search:llm.tryAsking')}</p>
      <div className="flex flex-wrap gap-2">
        {examples.map((question, idx) => (
          <Button
            key={idx}
            variant="outline"
            size="sm"
            className="text-sm"
            onClick={() => onSelectQuestion(question)}
          >
            {question}
          </Button>
        ))}
      </div>
    </div>
  );
}


// ============================================================================
// Main Component
// ============================================================================

export default function LLMSearch() {
  const { t } = useTranslation(['search', 'common']);
  const [status, setStatus] = useState<LLMSearchStatus | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | undefined>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConsentDialog, setShowConsentDialog] = useState(false);
  const [debugMode, setDebugMode] = useState(false);
  const [debugInfoMap, setDebugInfoMap] = useState<Record<string, DebugInfo>>({});
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { toast } = useToast();

  // Hidden keyboard shortcut: Ctrl+Shift+D to toggle debug mode
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        setDebugMode((prev) => {
          const next = !prev;
          toast({ title: next ? 'Debug mode enabled' : 'Debug mode disabled', description: next ? 'LLM intermediate steps will be shown' : undefined });
          return next;
        });
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toast]);
  
  // Build LLMConfig from status for consent dialog
  const llmConfig: LLMConfig = {
    enabled: status?.enabled ?? false,
    endpoint: status?.endpoint ?? null,
    system_prompt: null,
    disclaimer_text: status?.disclaimer ?? '',
  };

  // Scroll to bottom when messages change
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Load status and sessions on mount
  useEffect(() => {
    async function loadInitialData() {
      try {
        const [statusData, sessionsData] = await Promise.all([
          fetchLLMStatus(),
          fetchSessions(),
        ]);
        setStatus(statusData);
        setSessions(sessionsData);
      } catch (err) {
        console.error('Failed to load LLM search data:', err);
        setError(t('search:llm.messages.loadFailed'));
      }
    }
    loadInitialData();
  }, []);

  // Handle sending a message
  const handleSend = async () => {
    const messageContent = input.trim();
    if (!messageContent || isLoading) return;

    // Show consent dialog on first use if not already consented
    if (!hasLLMConsent(llmConfig)) {
      setShowConsentDialog(true);
      return;
    }

    const userMessage: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: messageContent,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);
    setError(null);

    try {
      const response = await sendMessage(messageContent, currentSessionId, debugMode);
      
      // Update session ID
      setCurrentSessionId(response.session_id);
      
      // Add assistant message
      setMessages((prev) => [...prev, response.message]);
      
      // Store debug info keyed by the assistant message ID
      if (response.debug && response.message.id) {
        setDebugInfoMap((prev) => ({ ...prev, [response.message.id]: response.debug! }));
      }
      
      // Refresh sessions list
      const updatedSessions = await fetchSessions();
      setSessions(updatedSessions);
      
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to send message';
      setError(errorMessage);
      toast({
        title: 'Error',
        description: errorMessage,
        variant: 'destructive',
      });
      // Remove the user message on error
      setMessages((prev) => prev.filter((m) => m.id !== userMessage.id));
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  // Handle keyboard submit
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Handle re-running a previous message
  const handleRerun = useCallback(async (content: string) => {
    if (!content || isLoading) return;

    // Show consent dialog on first use if not already consented
    if (!hasLLMConsent(llmConfig)) {
      setInput(content);
      setShowConsentDialog(true);
      return;
    }

    const userMessage: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);
    setError(null);

    try {
      const response = await sendMessage(content, currentSessionId, debugMode);
      setCurrentSessionId(response.session_id);
      setMessages((prev) => [...prev, response.message]);
      if (response.debug && response.message.id) {
        setDebugInfoMap((prev) => ({ ...prev, [response.message.id]: response.debug! }));
      }
      const updatedSessions = await fetchSessions();
      setSessions(updatedSessions);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to send message';
      setError(errorMessage);
      toast({
        title: 'Error',
        description: errorMessage,
        variant: 'destructive',
      });
      setMessages((prev) => prev.filter((m) => m.id !== userMessage.id));
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }, [isLoading, llmConfig, currentSessionId, debugMode, toast]);

  // Handle copying a message to the input for editing
  const handleCopyToInput = useCallback((content: string) => {
    setInput(content);
    inputRef.current?.focus();
  }, []);

  // Handle session selection
  const handleSelectSession = async (sessionId: string) => {
    try {
      const response = await fetch(`/api/llm-search/sessions/${sessionId}`);
      if (!response.ok) throw new Error('Failed to load session');
      const session = await response.json();
      setCurrentSessionId(session.id);
      setMessages(session.messages.filter((m: ChatMessage) => 
        m.role === 'user' || (m.role === 'assistant' && m.content)
      ));
    } catch (err) {
      toast({
        title: t('common:toast.error'),
        description: t('search:llm.messages.loadSessionFailed'),
        variant: 'destructive',
      });
    }
  };

  // Handle session deletion
  const handleDeleteSession = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (currentSessionId === sessionId) {
        setCurrentSessionId(undefined);
        setMessages([]);
      }
      toast({
        title: t('search:llm.messages.sessionDeleted'),
        description: t('search:llm.messages.sessionDeletedDesc'),
      });
    } catch (err) {
      toast({
        title: t('common:toast.error'),
        description: t('search:llm.messages.deleteSessionFailed'),
        variant: 'destructive',
      });
    }
  };

  // Start new session
  const handleNewSession = () => {
    setCurrentSessionId(undefined);
    setMessages([]);
    setDebugInfoMap({});
    setError(null);
    inputRef.current?.focus();
  };

  // Handle example question selection
  const handleSelectQuestion = (question: string) => {
    setInput(question);
    inputRef.current?.focus();
  };

  // Render disabled state if LLM is not enabled
  if (status && !status.enabled) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="w-5 h-5" />
            {t('search:llm.disabledTitle')}
          </CardTitle>
          <CardDescription>
            {t('search:llm.disabledSubtitle')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {t('search:llm.disabledMessage')}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  // Handle consent accepted - continue with the pending message
  const handleConsentAccepted = () => {
    // If there's input, send it after consent
    if (input.trim()) {
      // Small delay to let dialog close
      setTimeout(() => {
        handleSend();
      }, 100);
    }
  };

  return (
    <>
      {/* LLM Consent Dialog */}
      <LLMConsentDialog
        open={showConsentDialog}
        onOpenChange={setShowConsentDialog}
        onAccept={handleConsentAccepted}
        llmConfig={llmConfig}
      />
      
      <Card className="flex flex-col h-[calc(100vh-16rem)]">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-white" />
              </div>
              {t('search:llm.title')}
            </CardTitle>
            <CardDescription className="mt-1">
              {t('search:llm.subtitle')}
            </CardDescription>
          </div>
          <SessionList
            sessions={sessions}
            currentSessionId={currentSessionId}
            onSelectSession={handleSelectSession}
            onDeleteSession={handleDeleteSession}
            onNewSession={handleNewSession}
          />
        </div>
      </CardHeader>

      <Separator />

      {/* Messages Area */}
      <CardContent className="flex-1 overflow-hidden p-0">
        <ScrollArea className="h-full p-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center space-y-6 py-8">
              <div className="w-16 h-16 rounded-full bg-gradient-to-br from-violet-500/20 to-purple-600/20 flex items-center justify-center">
                <Sparkles className="w-8 h-8 text-violet-500" />
              </div>
              <div className="space-y-2">
                <h3 className="text-lg font-medium">{t('search:llm.welcomeTitle')}</h3>
                <p className="text-sm text-muted-foreground max-w-md">
                  {t('search:llm.welcomeMessage')}
                </p>
              </div>
              <ExampleQuestions onSelectQuestion={handleSelectQuestion} />
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message) => (
                <Message
                  key={message.id}
                  message={message}
                  debugInfo={debugInfoMap[message.id]}
                  onRerun={handleRerun}
                  onCopyToInput={handleCopyToInput}
                />
              ))}
              
              {/* Loading indicator */}
              {isLoading && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
                    <Sparkles className="w-4 h-4 text-white" />
                  </div>
                  <div className="bg-muted rounded-lg px-4 py-3 flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm text-muted-foreground">{t('search:llm.thinking')}</span>
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </div>
          )}
        </ScrollArea>
      </CardContent>

      <Separator />

      {/* Input Area */}
      <div className="p-4">
        {error && (
          <Alert variant="destructive" className="mb-3">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        
        <div className="flex gap-2">
          <Textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('search:llm.inputPlaceholder')}
            className="min-h-[44px] max-h-32 resize-none"
            disabled={isLoading}
          />
          <Button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            size="icon"
            className="h-11 w-11 shrink-0"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>
        
        <p className="text-xs text-muted-foreground mt-2 text-center">
          {t('search:llm.inputHint')}
          {status?.model_name && (
            <span className="ml-2 opacity-60">• {t('search:llm.model')}: {status.model_name}</span>
          )}
          {debugMode && (
            <span className="ml-2 inline-flex items-center gap-1 text-amber-600 dark:text-amber-400 cursor-pointer" onClick={() => setDebugMode(false)} title="Click to disable debug mode">
              <Bug className="w-3 h-3 inline" />
              Debug
            </span>
          )}
        </p>
      </div>
    </Card>
    </>
  );
}

