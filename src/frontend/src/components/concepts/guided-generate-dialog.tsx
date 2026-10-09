import { useMemo, useState } from 'react';
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

const EXAMPLE_DOMAINS = ['Customer & orders', 'Supply chain', 'Finance reporting'];

export function GuidedGenerateDialog({ open, onOpenChange }: GuidedGenerateDialogProps) {
  const { t } = useTranslation(['semantic-models', 'common']);
  const navigate = useNavigate();

  const [domain, setDomain] = useState('');
  const [questions, setQuestions] = useState('');
  const [objects, setObjects] = useState('');

  // Compose the free-text answers into a single guidelines prompt for the
  // generator. Kept human-readable so the user can still tweak it there.
  const composedPrompt = useMemo(() => {
    const parts: string[] = [];
    if (domain.trim()) {
      parts.push(`Build a domain ontology for: ${domain.trim()}.`);
    }
    if (questions.trim()) {
      parts.push(`It should help answer these questions: ${questions.trim()}.`);
    }
    if (objects.trim()) {
      parts.push(`Key objects and concepts to model: ${objects.trim()}.`);
    }
    return parts.join(' ');
  }, [domain, questions, objects]);

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
            <div className="flex flex-wrap gap-2 pt-1">
              {EXAMPLE_DOMAINS.map((ex) => (
                <Button
                  key={ex}
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7"
                  onClick={() => setDomain(ex)}
                >
                  {ex}
                </Button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="guided-questions">
              {t(
                'semantic-models:define.guided.questionsLabel',
                'What questions should it help answer? (optional)',
              )}
            </Label>
            <Textarea
              id="guided-questions"
              rows={2}
              placeholder={t(
                'semantic-models:define.guided.questionsPlaceholder',
                'e.g. Which customers churned last quarter? What drives delivery delays?',
              )}
              value={questions}
              onChange={(e) => setQuestions(e.target.value)}
            />
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
              <p className="text-sm">{composedPrompt}</p>
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
