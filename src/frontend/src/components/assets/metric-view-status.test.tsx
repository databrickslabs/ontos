import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { render, screen } from '@testing-library/react';
import MetricViewStatus from './metric-view-status';
import type {
    MetricViewBaseline,
    MetricViewDrift,
    MetricViewRefresh,
} from '@/types/data-asset-review';

const DIGEST = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2';
const recorded: MetricViewBaseline = {
    digest: DIGEST, approved_at: null, request_id: null, recorded_at: '2026-10-30T10:00:00Z',
};
const inSync: MetricViewDrift = {
    state: 'in_sync', current_digest: DIGEST, last_checked_at: '2026-11-01T09:00:00Z',
};
const drifted: MetricViewDrift = { ...inSync, state: 'drifted', current_digest: 'ff00' };
const failed: MetricViewRefresh = {
    status: 'failed',
    schedule: 'EVERY 6 HOURS',
    pipeline_id: 'pipe-1',
    pipeline_url: 'https://adb-1.example.com/pipelines/pipe-1',
    latest_update_at: '2026-10-31T06:00:00Z',
};

describe('MetricViewStatus', () => {
    afterEach(async () => {
        await i18n.changeLanguage('en');
    });

    it('renders nothing without drift or refresh state', () => {
        const { container } = render(<MetricViewStatus />);
        expect(container).toBeEmptyDOMElement();
    });

    it('shows an in-sync view with a recorded, unapproved baseline', () => {
        render(<MetricViewStatus baseline={recorded} drift={inSync} />);

        expect(screen.getByText('Matches the baseline')).toBeInTheDocument();
        expect(screen.getByText(/from the first definition read; no change has been approved/))
            .toBeInTheDocument();
        expect(screen.getByText('digest a1b2c3d4e5f6')).toHaveAttribute('title', DIGEST);
        expect(screen.getByText(/^Checked /)).toBeInTheDocument();
        expect(screen.queryByText(/differs from the baseline/)).toBeNull();
    });

    it('warns about a drifted definition and says Ontos does not change it', () => {
        render(<MetricViewStatus baseline={recorded} drift={drifted} />);

        expect(screen.getByText('Changed since the baseline')).toBeInTheDocument();
        expect(screen.getByText(/differs from the baseline in Ontos\. Ontos does not change it/))
            .toBeInTheDocument();
    });

    it('shows an approved baseline as approved', () => {
        render(<MetricViewStatus
            baseline={{ ...recorded, approved_at: '2026-10-31T12:00:00Z', request_id: 'r1' }}
            drift={inSync}
        />);

        expect(screen.getByText(/^Baseline approved on /)).toBeInTheDocument();
    });

    it('says when the definition could not be compared and there is no baseline', () => {
        render(<MetricViewStatus baseline={null} drift={{ state: 'unknown' }} />);

        expect(screen.getByText('Not compared')).toBeInTheDocument();
        expect(screen.getByText('No baseline yet.')).toBeInTheDocument();
        expect(screen.getByText('The definition could not be compared with the baseline.'))
            .toBeInTheDocument();
    });

    it('warns about a failed refresh with its schedule and pipeline link', () => {
        render(<MetricViewStatus baseline={recorded} drift={inSync} refresh={failed} />);

        expect(screen.getByText('Failed')).toBeInTheDocument();
        expect(screen.getByText('The last refresh failed')).toBeInTheDocument();
        expect(screen.getByText('Schedule: EVERY 6 HOURS')).toBeInTheDocument();
        expect(screen.getByText(/^Last refresh started /)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /Open pipeline/ }))
            .toHaveAttribute('href', failed.pipeline_url);
    });

    it('says when the refresh state could not be read, without a schedule or link', () => {
        render(<MetricViewStatus refresh={{ status: 'unknown' }} />);

        expect(screen.getByText('Unknown')).toBeInTheDocument();
        expect(screen.getByText('The refresh state could not be read.')).toBeInTheDocument();
        expect(screen.getByText('No schedule: refreshes are started manually.'))
            .toBeInTheDocument();
        expect(screen.queryByRole('link')).toBeNull();
        expect(screen.queryByText('Definition')).toBeNull();
    });

    it('shows a running refresh and keeps a time the browser cannot parse as is', () => {
        render(<MetricViewStatus refresh={{ status: 'running', latest_update_at: 'soon' }} />);

        expect(screen.getByText('Running')).toBeInTheDocument();
        expect(screen.getByText('Last refresh started soon')).toBeInTheDocument();
        expect(screen.queryByText('The last refresh failed')).toBeNull();
    });

    it('is translated into Portuguese', async () => {
        await i18n.changeLanguage('pt');
        render(<MetricViewStatus baseline={recorded} drift={drifted} refresh={failed} />);

        expect(screen.getByText('Alterada desde a linha de base')).toBeInTheDocument();
        expect(screen.getByText('A última atualização falhou')).toBeInTheDocument();
        expect(screen.getByText('Agendamento: EVERY 6 HOURS')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /Abrir pipeline/ })).toBeInTheDocument();
    });
});
