import { useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Loader2, Plus, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useDomains } from '@/hooks/use-domains';

// ---------------------------------------------------------------------------
// Guided "Generate" dialog (Concept Builder v2, Define > Generate).
//
// The existing Ontology Generator's core input is a free-text `guidelines`
// prompt (+ base URI). Rather than drop users straight onto that page, this
// dialog asks a few plain questions and COMPOSES them into a strong guidelines
// prompt, then hands off to the real generator engine with the prompt
// pre-filled via ?guidelines=. No engine rebuild — it reconciles the wizard
// idea with the generator we already have.
//
// This is an interim step ahead of Joshua's full LLM interview blueprint
// (skill.mmd); the field set here is deliberately small and maps 1:1 onto the
// generator's guidelines input.
// ---------------------------------------------------------------------------

interface GuidedGenerateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Sentinel for the "no domain" option (Radix Select disallows empty values).
const NO_DOMAIN = '__none__';

/**
 * Compose the guided answers into a single guidelines prompt for the
 * generator. Blank questions are ignored; the rest render as a numbered list.
 * Pure — exported for testing.
 */
export function composeGuidedPrompt(domain: string, questions: string[], objects: string): string {
  const parts: string[] = [];
  if (domain.trim()) {
    parts.push(`Build a domain ontology for: ${domain.trim()}.`);
  }
  const qs = questions.map((q) => q.trim()).filter(Boolean);
  if (qs.length > 0) {
    parts.push(
      `It should help answer these questions:\n${qs.map((q, i) => `${i + 1}. ${q}`).join('\n')}`,
    );
  }
  if (objects.trim()) {
    parts.push(`Key objects and concepts to model: ${objects.trim()}.`);
  }
  return parts.join('\n');
}

export function GuidedGenerateDialog({ open, onOpenChange }: GuidedGenerateDialogProps) {
  const { t } = useTranslation(['semantic-models', 'common']);
  const navigate = useNavigate();

  const { domains, loading: domainsLoading } = useDomains();

  const [domain, setDomain] = useState('');
  const [questions, setQuestions] = useState<string[]>(['']);
  const [objects, setObjects] = useState('');
  const questionRefs = useRef<(HTMLInputElement | null)[]>([]);
  const focusIndexRef = useRef<number | null>(null);

  // The dropdown reflects the free-text field: if the typed domain matches a
  // real data domain (case-insensitive), that domain is shown as selected.
  // The free-text field stays the single source for the composed prompt.
  const selectedDomainId = useMemo(() => {
    const needle = domain.trim().toLowerCase();
    if (!needle) return NO_DOMAIN;
    return domains.find((d) => d.name.toLowerCase() === needle)?.id ?? NO_DOMAIN;
  }, [domain, domains]);

  const handleDomainSelect = (id: string) => {
    if (id === NO_DOMAIN) {
      // Only clear text that came from a domain pick; keep custom free text.
      if (selectedDomainId !== NO_DOMAIN) setDomain('');
      return;
    }
    const picked = domains.find((d) => d.id === id);
    if (picked) setDomain(picked.name);
  };

  const updateQuestion = (index: number, value: string) => {
    setQuestions((prev) => prev.map((q, i) => (i === index ? value : q)));
  };

  const addQuestion = () => {
    setQuestions((prev) => {
      focusIndexRef.current = prev.length;
      return [...prev, ''];
    });
  };

  const removeQuestion = (index: number) => {
    setQuestions((prev) => {
      const next = prev.filter((_, i) => i !== index);
      return next.length > 0 ? next : [''];
    });
  };

  const handleQuestionKeyDown = (index: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (index === questions.length - 1) {
      // Don't stack empty rows: only add when the last one has content.
      if (questions[index].trim()) addQuestion();
    } else {
      questionRefs.current[index + 1]?.focus();
    }
  };

  // Compose the answers into a single guidelines prompt for the generator.
  // Kept human-readable so the user can still tweak it there.
  const composedPrompt = useMemo(
    () => composeGuidedPrompt(domain, questions, objects),
    [domain, questions, objects],
  );

  const canContinue = domain.trim().length > 0;

  const handleContinue = () => {
    const qs = composedPrompt ? `?guidelines=${encodeURIComponent(composedPrompt)}` : '';
    onOpenChange(false);
    navigate(`/concepts/generator${qs}`);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{t('semantic-models:define.guided.title', 'Guided build')}</DialogTitle>
          <DialogDescription>
            {t(
              'semantic-models:define.guided.subtitle',
              'Answer a few questions. We turn them into a prompt for the generator, which drafts a concept scheme you review before keeping. Nothing is saved yet.',
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-1">
          <div className="space-y-1.5">
            <Label htmlFor="guided-domain">
              {t('semantic-models:define.guided.domainLabel', 'What domain are you working in?')}
            </Label>
            {domainsLoading ? (
              <div
                className="flex items-center gap-2 text-sm text-muted-foreground"
                data-testid="guided-domains-loading"
              >
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('semantic-models:define.guided.domainsLoading', 'Loading data domains...')}
              </div>
            ) : domains.length > 0 ? (
              <Select value={selectedDomainId} onValueChange={handleDomainSelect}>
                <SelectTrigger
                  id="guided-domain-select"
                  aria-label={t('semantic-models:define.guided.domainSelectLabel', 'Data domain')}
                >
                  <SelectValue
                    placeholder={t('semantic-models:define.guided.domainSelectPlaceholder', 'Pick a data domain')}
                  />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_DOMAIN}>
                    {t('semantic-models:define.guided.noDomain', 'No data domain (type your own)')}
                  </SelectItem>
                  {domains.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="text-xs text-muted-foreground" data-testid="guided-domains-empty">
                {t(
                  'semantic-models:define.guided.noDomainsHint',
                  'No data domains defined yet. Describe your domain in your own words below.',
                )}
              </p>
            )}
            <Input
              id="guided-domain"
              autoFocus
              placeholder={t(
                'semantic-models:define.guided.domainPlaceholder',
                'e.g. Retail pricing, Clinical trials, Fleet logistics',
              )}
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="guided-questions">
              {t(
                'semantic-models:define.guided.questionsLabel',
                'What questions should it help answer? (optional)',
              )}
            </Label>
            <div className="space-y-2">
              {questions.map((q, index) => (
                <div key={index} className="flex items-center gap-2">
                  <Input
                    id={index === 0 ? 'guided-questions' : undefined}
                    ref={(el) => {
                      questionRefs.current[index] = el;
                      if (el && focusIndexRef.current === index) {
                        focusIndexRef.current = null;
                        el.focus();
                      }
                    }}
                    aria-label={t('semantic-models:define.guided.questionAria', {
                      defaultValue: 'Question {{n}}',
                      n: index + 1,
                    })}
                    placeholder={
                      index === 0
                        ? t(
                            'semantic-models:define.guided.questionPlaceholder',
                            'e.g. Which customers churned last quarter?',
                          )
                        : undefined
                    }
                    value={q}
                    onChange={(e) => updateQuestion(index, e.target.value)}
                    onKeyDown={(e) => handleQuestionKeyDown(index, e)}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    aria-label={t('semantic-models:define.guided.removeQuestion', {
                      defaultValue: 'Remove question {{n}}',
                      n: index + 1,
                    })}
                    disabled={questions.length === 1 && !q}
                    onClick={() => removeQuestion(index)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button type="button" variant="outline" size="sm" className="h-7" onClick={addQuestion}>
                <Plus className="h-3.5 w-3.5 mr-1" />
                {t('semantic-models:define.guided.addQuestion', 'Add question')}
              </Button>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="guided-objects">
              {t(
                'semantic-models:define.guided.objectsLabel',
                'What objects do you work with? (optional)',
              )}
            </Label>
            <Textarea
              id="guided-objects"
              rows={2}
              placeholder={t(
                'semantic-models:define.guided.objectsPlaceholder',
                'e.g. Customer, Order, Shipment, Invoice',
              )}
              value={objects}
              onChange={(e) => setObjects(e.target.value)}
            />
          </div>

          {composedPrompt && (
            <div className="rounded-md border bg-muted/40 p-3">
              <div className="text-xs font-medium text-muted-foreground mb-1">
                {t('semantic-models:define.guided.previewLabel', 'Prompt for the generator')}
              </div>
              <p className="text-sm whitespace-pre-line" data-testid="guided-prompt-preview">
                {composedPrompt}
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button disabled={!canContinue} onClick={handleContinue}>
            {t('semantic-models:define.guided.continue', 'Continue to generator')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
