import { useState } from 'react';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle, SparklesIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { LLMConfig, LLMConsentState } from '@/types/llm';

const CONSENT_STORAGE_KEY = 'llm_consent_state';

interface LLMConsentDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onAccept: () => void;
    llmConfig: LLMConfig;
}

export default function LLMConsentDialog({
    open,
    onOpenChange,
    onAccept,
    llmConfig,
}: LLMConsentDialogProps) {
    const { t } = useTranslation('common');
    const [accepted, setAccepted] = useState(false);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <SparklesIcon className="w-5 h-5 text-purple-500" />
                        {t('common:llmConsent.title')}
                    </DialogTitle>
                    <DialogDescription>
                        {t('common:llmConsent.description')}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4 py-4">
                    <Alert>
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription className="whitespace-pre-wrap">
                            {llmConfig.disclaimer_text}
                        </AlertDescription>
                    </Alert>

                    <div className="space-y-2 text-sm text-muted-foreground">
                        <p><strong>{t('common:llmConsent.howItWorks')}</strong></p>
                        <ul className="list-disc list-inside space-y-1 ml-2">
                            <li>{t('common:llmConsent.point1')}</li>
                            <li>{t('common:llmConsent.point2')}</li>
                            <li>{t('common:llmConsent.point3')}</li>
                            <li>{t('common:llmConsent.point4')}</li>
                        </ul>
                    </div>

                    <div className="flex items-start space-x-2 pt-4">
                        <Checkbox
                            id="consent-checkbox"
                            checked={accepted}
                            onCheckedChange={(checked) => setAccepted(checked as boolean)}
                        />
                        <label
                            htmlFor="consent-checkbox"
                            className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                        >
                            {t('common:llmConsent.consentLabel')}
                        </label>
                    </div>
                </div>

                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                    >
                        {t('common:actions.cancel')}
                    </Button>
                    <Button
                        onClick={() => {
                            // Store consent in localStorage
                            const consentState: LLMConsentState = {
                                accepted: true,
                                timestamp: new Date().toISOString(),
                                config_version: llmConfig.endpoint || 'unknown',
                            };
                            localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(consentState));
                            onAccept();
                            onOpenChange(false);
                        }}
                        disabled={!accepted}
                    >
                        {t('common:llmConsent.acceptContinue')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

/**
 * Check if user has previously consented to LLM usage
 */
export function hasLLMConsent(currentConfig: LLMConfig): boolean {
    try {
        const storedConsent = localStorage.getItem(CONSENT_STORAGE_KEY);
        if (!storedConsent) return false;

        const consentState: LLMConsentState = JSON.parse(storedConsent);

        // Check if consent exists and was accepted
        if (!consentState.accepted) return false;

        // Optional: Invalidate consent if config changes (endpoint changed)
        if (consentState.config_version && currentConfig.endpoint) {
            if (consentState.config_version !== currentConfig.endpoint) {
                // Config changed, require new consent
                localStorage.removeItem(CONSENT_STORAGE_KEY);
                return false;
            }
        }

        return true;
    } catch (error) {
        console.error('Error checking LLM consent:', error);
        return false;
    }
}

/**
 * Clear stored LLM consent (for settings changes or logout)
 */
export function clearLLMConsent() {
    localStorage.removeItem(CONSENT_STORAGE_KEY);
}
