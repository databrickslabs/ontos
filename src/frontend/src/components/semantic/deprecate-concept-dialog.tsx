import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Loader2, X } from 'lucide-react';
import ConceptSelectDialog from './concept-select-dialog';

interface Props {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  conceptIri: string;
  onSuccess: () => void;
}

export function DeprecateConceptDialog({ isOpen, onOpenChange, conceptIri, onSuccess }: Props) {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { post } = useApi();
  const { toast } = useToast();
  const [successorIris, setSuccessorIris] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showSuccessorPicker, setShowSuccessorPicker] = useState(false);

  const handleAddSuccessor = useCallback((iri: string) => {
    if (!successorIris.includes(iri) && iri !== conceptIri) {
      setSuccessorIris([...successorIris, iri]);
    }
    setShowSuccessorPicker(false);
  }, [successorIris, conceptIri]);

  const handleRemoveSuccessor = useCallback((iri: string) => {
    setSuccessorIris(successorIris.filter((s) => s !== iri));
  }, [successorIris]);

  const handleConfirm = async () => {
    setIsSubmitting(true);
    try {
      const body = {
        iri: conceptIri,
        replaced_by: successorIris.length > 0 ? successorIris : [],
      };
      const response = await post('/api/semantic-models/concepts/deprecate', body);
      if (response.error) {
        throw new Error(response.error);
      }
      onOpenChange(false);
      setSuccessorIris([]);
      onSuccess();
    } catch (err: any) {
      toast({
        title: t('common:toast.error'),
        description: err?.message || t('semantic-models:messages.error', 'Error'),
        variant: 'destructive',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <AlertDialog open={isOpen} onOpenChange={onOpenChange}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('semantic-models:dialogs.deprecate.title', 'Deprecate concept')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t(
                'semantic-models:dialogs.deprecate.description',
                'Optionally specify one or more successor concepts to indicate what this concept was replaced by.'
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="space-y-3">
            {/* Successor selection area */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">
                {t('semantic-models:dialogs.deprecate.successors', 'Successor concepts')}
              </label>
              <div className="flex flex-wrap gap-2 min-h-8 p-2 border rounded-md bg-muted/30">
                {successorIris.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    {t('semantic-models:dialogs.deprecate.noSuccessors', 'None selected')}
                  </p>
                ) : (
                  successorIris.map((iri) => (
                    <Badge
                      key={iri}
                      variant="secondary"
                      className="pl-2 pr-1 py-1 flex items-center gap-1"
                    >
                      <span className="text-xs truncate max-w-xs" title={iri}>
                        {iri.split(/[/#]/).pop() || iri}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleRemoveSuccessor(iri)}
                        className="ml-1 hover:bg-black/20 rounded-sm p-0.5"
                        aria-label={t('common:actions.remove', 'Remove')}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))
                )}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowSuccessorPicker(true)}
                className="w-full"
              >
                {t('semantic-models:dialogs.deprecate.addSuccessor', '+ Add successor')}
              </Button>
            </div>
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSubmitting}>
              {t('common:actions.cancel', 'Cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirm}
              disabled={isSubmitting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('semantic-models:lifecycle.deprecate', 'Deprecate')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Successor concept picker dialog */}
      <ConceptSelectDialog
        isOpen={showSuccessorPicker}
        onOpenChange={setShowSuccessorPicker}
        onSelect={handleAddSuccessor}
        entityType="class"
      />
    </>
  );
}
