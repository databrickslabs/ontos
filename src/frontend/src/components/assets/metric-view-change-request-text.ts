import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';

const PREFIX = 'detail.metricView.changeRequests';

/**
 * The text of a coded change request error or warning in the user's language.
 *
 * The server sends a code with its params (`{code, message, params}`); the
 * English message is the fallback for a code the UI doesn't know. A secured
 * source's `kind` is translated too.
 */
export function useChangeRequestText() {
    const { t } = useTranslation('assets');
    return useCallback((
        code: string | null | undefined,
        message: string | null | undefined,
        params?: Record<string, unknown> | null,
    ): string => {
        const values: Record<string, unknown> = { ...(params ?? {}) };
        if (typeof values.kind === 'string') {
            values.kind = t(`${PREFIX}.securedKinds.${values.kind}`, { defaultValue: values.kind });
        }
        const fallback = message || t(`${PREFIX}.errors.generic`);
        if (!code) return fallback;
        return t(`${PREFIX}.codes.${code}`, { ...values, defaultValue: fallback });
    }, [t]);
}
