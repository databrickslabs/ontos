import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
import { InfoIcon } from 'lucide-react';
import { WelcomeDisclaimerState } from '@/types/welcome-disclaimer';

const STORAGE_KEY = 'welcome_disclaimer_state';

interface WelcomeDisclaimerDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onAccept: () => void;
    disclaimerText: string;
}

/**
 * Compute a stable, short config_version from the disclaimer text.
 * Any text edit changes the hash and re-prompts everyone.
 *
 * Uses a deterministic FNV-1a-style 32-bit hash so we don't need to ship
 * a crypto polyfill or rely on `crypto.subtle` (async / non-secure context).
 */
function hashText(text: string): string {
    let hash = 0x811c9dc5; // FNV-1a 32-bit offset basis
    for (let i = 0; i < text.length; i++) {
        hash ^= text.charCodeAt(i);
        // 32-bit FNV prime mul, kept in unsigned range
        hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(16).padStart(8, '0');
}

export default function WelcomeDisclaimerDialog({
    open,
    onOpenChange,
    onAccept,
    disclaimerText,
}: WelcomeDisclaimerDialogProps) {
    const [accepted, setAccepted] = useState(false);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            {/* z-[100] beats default modals (z-50). Welcome disclaimer must
                always be the topmost overlay until the user accepts. */}
            <DialogContent className="max-w-2xl z-[100]">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <InfoIcon className="w-5 h-5 text-blue-500" />
                        Welcome to Ontos
                    </DialogTitle>
                    <DialogDescription>
                        Please review the following before continuing.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4 py-4">
                    <div className="prose prose-sm dark:prose-invert max-w-none border rounded-md p-4 bg-muted/30 max-h-[50vh] overflow-y-auto">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {disclaimerText}
                        </ReactMarkdown>
                    </div>

                    <div className="flex items-start space-x-2 pt-2">
                        <Checkbox
                            id="welcome-disclaimer-checkbox"
                            checked={accepted}
                            onCheckedChange={(checked) => setAccepted(checked as boolean)}
                        />
                        <label
                            htmlFor="welcome-disclaimer-checkbox"
                            className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                        >
                            I have read and accept the above
                        </label>
                    </div>
                </div>

                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                    >
                        Cancel
                    </Button>
                    <Button
                        onClick={() => {
                            const state: WelcomeDisclaimerState = {
                                accepted: true,
                                timestamp: new Date().toISOString(),
                                config_version: hashText(disclaimerText),
                            };
                            localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
                            onAccept();
                            onOpenChange(false);
                        }}
                        disabled={!accepted}
                    >
                        Accept and Continue
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

/**
 * Check if user has already accepted the *current* disclaimer text.
 * Returns false when:
 *   - nothing stored
 *   - stored state was not accepted
 *   - stored config_version differs from the hash of the current text
 *     (admin edited the text → re-prompt everyone)
 */
export function hasWelcomeConsent(currentText: string): boolean {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (!stored) return false;

        const state: WelcomeDisclaimerState = JSON.parse(stored);
        if (!state.accepted) return false;

        const currentVersion = hashText(currentText);
        if (state.config_version !== currentVersion) {
            // Disclaimer text changed — invalidate consent.
            localStorage.removeItem(STORAGE_KEY);
            return false;
        }

        return true;
    } catch (error) {
        console.error('Error checking welcome disclaimer consent:', error);
        return false;
    }
}

/** Clear stored welcome-disclaimer consent (e.g. on logout). */
export function clearWelcomeConsent() {
    localStorage.removeItem(STORAGE_KEY);
}

/** Exposed for tests/debug only. */
export const __WELCOME_DISCLAIMER_STORAGE_KEY = STORAGE_KEY;
