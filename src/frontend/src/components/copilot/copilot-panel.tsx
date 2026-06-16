import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Send, Loader2, Sparkles, X, MessageSquare, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
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
import { fetchLLMStatus, fetchSessions, sendMessage, deleteSession } from '@/components/search/llm-search-api';
import {
  useCopilotStore,
  type CopilotPageContext,
  COPILOT_MIN_WIDTH,
  COPILOT_MAX_WIDTH,
} from '@/stores/copilot-store';
import { useCopilotQuestions } from '@/hooks/use-copilot-questions';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import type { LLMConfig } from '@/types/llm';
import type { ChatMessage, LLMSearchStatus, SessionSummary } from '@/types/llm-search';

const WELCOME_DISMISSED_KEY = 'copilot-welcome-dismissed';

function buildContextPrefix(ctx: CopilotPageContext): string {
  let prefix = `[Context: User is on the "${ctx.pageName}" page at ${ctx.pageUrl}`;
  if (ctx.selectedEntity) {
    prefix += `, viewing ${ctx.selectedEntity.type} "${ctx.selectedEntity.name}" (id: ${ctx.selectedEntity.id})`;
  }
  prefix += '. Consider this context when answering.]';
  return prefix;
}

function CopilotMessage({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex gap-2 min-w-0 ${isUser ? 'flex-row-reverse' : ''}`}>
      {!isUser && (
        <div className="w-6 h-6 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shrink-0">
          <Sparkles className="w-3 h-3 text-white" />
        </div>
      )}
      <div className={`
        max-w-[85%] min-w-0 rounded-lg px-3 py-2 text-sm break-words
        ${isUser
          ? 'bg-sky-100 dark:bg-sky-900/50 text-sky-900 dark:text-sky-100'
          : 'bg-muted'
        }
      `}>
        {isUser ? (
          <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{message.content}</p>
        ) : (
          <div className="prose prose-sm dark:prose-invert max-w-none break-words [overflow-wrap:anywhere] [&_code]:break-all [&_a]:break-all [&_pre]:whitespace-pre-wrap [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                table: ({ children }) => (
                  <div className="overflow-x-auto my-1">
                    <table className="min-w-full border-collapse text-xs">{children}</table>
                  </div>
                ),
                th: ({ children }) => (
                  <th className="border border-border bg-muted px-2 py-1 text-left font-medium">{children}</th>
                ),
                td: ({ children }) => (
                  <td className="border border-border px-2 py-1">{children}</td>
                ),
                code: ({ className, children, ...props }) => {
                  const isInline = !className;
                  return isInline ? (
                    <code className="bg-muted-foreground/20 px-1 py-0.5 rounded text-xs break-all" {...props}>{children}</code>
                  ) : (
                    <code className={`${className} block bg-zinc-900 text-zinc-100 p-2 rounded-md overflow-x-auto text-xs`} {...props}>{children}</code>
                  );
                },
              }}
            >
              {message.content || ''}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

export default function CopilotPanel() {
  const { t } = useTranslation(['search', 'common']);
  const shortName = useUICustomizationStore((s) => s.getShortName());
  const isOpen = useCopilotStore((s) => s.isOpen);
  const pageContext = useCopilotStore((s) => s.pageContext);
  const panelWidth = useCopilotStore((s) => s.panelWidth);
  const { closePanel, setPanelWidth } = useCopilotStore((s) => s.actions);
  const questionGroups = useCopilotQuestions();

  // Drag-to-resize: attach window-level listeners only while dragging so the
  // pointer can leave the thin handle without losing the drag. We throttle
  // width updates to animation frames to avoid storming the store.
  const isResizingRef = useRef(false);
  const rafIdRef = useRef<number | null>(null);

  const startResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizingRef.current = true;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    const onMove = (ev: MouseEvent) => {
      if (!isResizingRef.current) return;
      if (rafIdRef.current !== null) return;
      rafIdRef.current = requestAnimationFrame(() => {
        rafIdRef.current = null;
        const next = window.innerWidth - ev.clientX;
        setPanelWidth(next);
      });
    };

    const onUp = () => {
      isResizingRef.current = false;
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [setPanelWidth]);

  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
  }, []);

  const [status, setStatus] = useState<LLMSearchStatus | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | undefined>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showConsentDialog, setShowConsentDialog] = useState(false);
  const [isWelcomeDismissed, setIsWelcomeDismissed] = useState(
    () => localStorage.getItem(WELCOME_DISMISSED_KEY) === 'true',
  );

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const llmConfig: LLMConfig = {
    enabled: status?.enabled ?? false,
    endpoint: status?.endpoint ?? null,
    system_prompt: null,
    disclaimer_text: status?.disclaimer ?? '',
  };

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  useEffect(() => {
    if (!isOpen) return;
    async function load() {
      try {
        const [statusData, sessionsData] = await Promise.all([
          fetchLLMStatus(),
          fetchSessions(),
        ]);
        setStatus(statusData);
        setSessions(sessionsData);
      } catch {
        // silently fail on panel open
      }
    }
    load();
  }, [isOpen]);

  const dismissWelcome = () => {
    setIsWelcomeDismissed(true);
    localStorage.setItem(WELCOME_DISMISSED_KEY, 'true');
  };

  const handleSend = async () => {
    const messageContent = input.trim();
    if (!messageContent || isLoading) return;

    if (!hasLLMConsent(llmConfig)) {
      setShowConsentDialog(true);
      return;
    }

    let contextualMessage = messageContent;
    if (pageContext) {
      contextualMessage = buildContextPrefix(pageContext) + '\n\n' + messageContent;
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

    try {
      const response = await sendMessage(contextualMessage, currentSessionId);
      setCurrentSessionId(response.session_id);
      setMessages((prev) => [...prev, response.message]);
      const updatedSessions = await fetchSessions();
      setSessions(updatedSessions);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : t('search:copilot.messageSendFailed');
      toast({ title: t('common:toast.error'), description: errorMessage, variant: 'destructive' });
      setMessages((prev) => prev.filter((m) => m.id !== userMessage.id));
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSelectPrompt = (prompt: string) => {
    setInput(prompt);
    inputRef.current?.focus();
  };

  const handleConsentAccepted = () => {
    if (input.trim()) {
      setTimeout(() => handleSend(), 100);
    }
  };

  const handleSelectSession = async (sessionId: string) => {
    try {
      const response = await fetch(`/api/llm-search/sessions/${sessionId}`);
      if (!response.ok) throw new Error('Failed to load session');
      const session = await response.json();
      setCurrentSessionId(session.id);
      setMessages(session.messages.filter((m: ChatMessage) =>
        m.role === 'user' || (m.role === 'assistant' && m.content)
      ));
    } catch {
      toast({
        title: t('common:toast.error'),
        description: t('search:llm.messages.loadSessionFailed'),
        variant: 'destructive',
      });
    }
  };

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
    } catch {
      toast({
        title: t('common:toast.error'),
        description: t('search:llm.messages.deleteSessionFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleNewSession = () => {
    setCurrentSessionId(undefined);
    setMessages([]);
    inputRef.current?.focus();
  };

  if (!isOpen) return null;

  return (
    <>
      <LLMConsentDialog
        open={showConsentDialog}
        onOpenChange={setShowConsentDialog}
        onAccept={handleConsentAccepted}
        llmConfig={llmConfig}
      />

      {/* Panel container — fixed right side, no overlay */}
      <div
        className="fixed inset-y-0 right-0 z-50 border-l bg-background shadow-lg flex flex-col animate-in slide-in-from-right duration-300"
        style={{ width: panelWidth }}
      >
        {/* Resize handle — thin strip on the left edge */}
        <div
          onMouseDown={startResize}
          role="separator"
          aria-orientation="vertical"
          aria-label={t('search:copilot.resizeHandle', { defaultValue: 'Resize Ask Ontos panel' })}
          aria-valuemin={COPILOT_MIN_WIDTH}
          aria-valuemax={COPILOT_MAX_WIDTH}
          aria-valuenow={panelWidth}
          className="absolute inset-y-0 -left-0.5 w-1.5 cursor-col-resize z-10 hover:bg-violet-500/40 active:bg-violet-500/60 transition-colors"
        />
        {/* Header — h-16 matches the app header so the bottom border aligns */}
        <div className="flex h-16 items-center justify-between gap-2 px-4 border-b shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-semibold leading-tight">{t('search:copilot.title', { shortName })}</h2>
              <p className="text-xs text-muted-foreground">{t('search:copilot.subtitle')}</p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {/* History dropdown */}
            {sessions.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7" title={t('search:llm.history')}>
                    <MessageSquare className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-64">
                  <DropdownMenuItem onClick={handleNewSession} className="gap-2">
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
                      onClick={() => handleSelectSession(session.id)}
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
                          handleDeleteSession(session.id);
                        }}
                      >
                        <Trash2 className="w-3 h-3" />
                      </Button>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={closePanel}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Context badge */}
        {pageContext?.selectedEntity && (
          <div className="px-4 py-2 border-b bg-muted/30 shrink-0">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>{t('search:copilot.askingAbout')}</span>
              <Badge variant="outline" className="text-xs font-medium">
                {pageContext.selectedEntity.name}
              </Badge>
              <Badge variant="secondary" className="text-xs">
                {pageContext.selectedEntity.type}
              </Badge>
            </div>
          </div>
        )}

        {/* Messages / Welcome */}
        <ScrollArea className="flex-1 min-h-0">
          <div className="p-4">
            {messages.length === 0 ? (
              <div className="space-y-5">
                {/* Dismissable welcome card */}
                {!isWelcomeDismissed && (
                  <div className="rounded-lg border bg-muted/30 p-4 relative">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="absolute top-1 right-1 h-6 w-6 text-muted-foreground hover:text-foreground"
                      onClick={dismissWelcome}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                    <div className="flex items-start gap-2 pr-6">
                      <Sparkles className="w-4 h-4 text-violet-500 mt-0.5 shrink-0" />
                      <div>
                        <p className="text-sm font-medium">{t('search:copilot.welcome', { shortName })}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {t('search:copilot.welcomeDescription')}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Context- and role-aware prompts */}
                {questionGroups.map((group) => (
                  <div key={group.category}>
                    <h3 className="text-xs font-medium text-muted-foreground mb-2">
                      {group.label}
                    </h3>
                    <div className="space-y-1.5">
                      {group.questions.map((q) => (
                        <button
                          key={q.key}
                          className="w-full text-left text-sm px-3 py-2 rounded-md border bg-background hover:bg-accent transition-colors"
                          onClick={() => handleSelectPrompt(q.text)}
                        >
                          {q.text}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-3">
                {messages.map((message) => (
                  <CopilotMessage key={message.id} message={message} />
                ))}
                {isLoading && (
                  <div className="flex gap-2">
                    <div className="w-6 h-6 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shrink-0">
                      <Sparkles className="w-3 h-3 text-white" />
                    </div>
                    <div className="bg-muted rounded-lg px-3 py-2 flex items-center gap-2">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span className="text-xs text-muted-foreground">{t('search:llm.thinking')}</span>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>
        </ScrollArea>

        <Separator />

        {/* Input */}
        <div className="p-3 shrink-0">
          <div className="flex gap-2">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('search:copilot.inputPlaceholder', { shortName })}
              className="flex-1 h-9 rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
              disabled={isLoading}
            />
            <Button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              size="icon"
              className="h-9 w-9 shrink-0"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
