import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import MetricViewChangeRequests from './metric-view-change-requests';
import type { MetricViewChangeRequest } from '@/types/metric-view-change-request';

const getMock = vi.fn();
const postMock = vi.fn();
const canWrite = { value: true };
vi.mock('@/hooks/use-api', () => ({
    useApi: () => ({ get: getMock, post: postMock, delete: vi.fn() }),
}));
vi.mock('@/stores/permissions-store', () => ({
    usePermissions: () => ({ hasPermission: () => canWrite.value }),
}));
vi.mock('@/stores/user-store', () => ({
    useUserStore: (select: (s: unknown) => unknown) =>
        select({ userInfo: { email: 'modeller@example.com' } }),
}));

const BASE_URL = '/api/assets/a1/metric-view/change-requests';
const DEFINITION = 'version: 1.1\nsource: main.sales.orders\n';

function request(overrides: Partial<MetricViewChangeRequest> = {}): MetricViewChangeRequest {
    return {
        id: 'r1',
        asset_id: 'a1',
        metric_view_fqn: 'main.sales.orders_mv',
        status: 'draft',
        justification: 'Net of refunds',
        base_digest: 'b'.repeat(64),
        proposed_digest: 'abcdef1234567890'.padEnd(64, '0'),
        proposed_definition: DEFINITION,
        warnings: [],
        requested_by: 'modeller@example.com',
        created_at: '2026-11-01T10:00:00Z',
        ddl: 'ALTER VIEW `main`.`sales`.`orders_mv` AS $$\nversion: 1.1\n$$',
        ...overrides,
    };
}

function renderList() {
    return render(<MetricViewChangeRequests assetId="a1" currentDefinition={DEFINITION} />);
}

describe('MetricViewChangeRequests', () => {
    beforeEach(async () => {
        getMock.mockReset();
        postMock.mockReset();
        canWrite.value = true;
        await i18n.changeLanguage('en');
    });
    afterEach(async () => {
        await i18n.changeLanguage('en');
    });

    it('lists the requests with their status, warnings and delivery', async () => {
        getMock.mockResolvedValue({ data: [
            request({
                id: 'r2', status: 'delivered', delivery_mode: 'indirect,manual',
                decided_by: 'steward@example.com', decided_at: '2026-11-01T11:00:00Z',
                warnings: [{
                    code: 'metric_view_linked_field_removed', message: 'x',
                    params: { field: 'Region', links: 1 },
                }],
            }),
            request(),
        ] });

        renderList();

        expect(await screen.findByText('Delivered')).toBeInTheDocument();
        expect(screen.getByText('Draft')).toBeInTheDocument();
        expect(screen.getByText(
            'The field Region has concept links (1) and is removed.',
        )).toBeInTheDocument();
        expect(screen.getByText(/files in Git, notification to the owners/)).toBeInTheDocument();
        expect(screen.getByText('Statement to apply')).toBeInTheDocument();
        expect(getMock).toHaveBeenCalledWith(BASE_URL);
    });

    it('shows a delivery error and an applied request in Portuguese', async () => {
        await i18n.changeLanguage('pt');
        getMock.mockResolvedValue({ data: [
            request({
                id: 'r3', status: 'failed',
                error: { code: 'metric_view_delivery_git_unavailable', message: 'x', params: {} },
            }),
            request({ id: 'r4', status: 'delivered', applied_at: '2026-11-01T12:00:00Z' }),
        ] });

        renderList();

        expect(await screen.findByText('Falha na entrega')).toBeInTheDocument();
        expect(screen.getByText(
            'O repositório Git da entrega Indireta não está disponível.',
        )).toBeInTheDocument();
        expect(screen.getByText(/esta definição agora é a linha de base/)).toBeInTheDocument();
    });

    it('submits a draft and shows a refused pre-check in the user language', async () => {
        getMock.mockResolvedValue({ data: [request()] });
        postMock.mockResolvedValue({
            data: {}, error: 'stale', errorCode: 'metric_view_base_stale', errorParams: {},
        });

        renderList();
        fireEvent.click(await screen.findByRole('button', { name: 'Submit for review' }));

        await waitFor(() => expect(postMock).toHaveBeenCalledWith(`${BASE_URL}/r1/submit`, {}));
        expect(await screen.findByRole('alert')).toHaveTextContent(
            'The metric view changed in Unity Catalog since this draft was written.',
        );
    });

    it('cancels a request in review; others see no actions', async () => {
        getMock.mockResolvedValue({ data: [
            request({ status: 'in_review' }),
            request({ id: 'r5', requested_by: 'someone@example.com' }),
        ] });
        postMock.mockResolvedValue({ data: {} });

        renderList();
        expect(await screen.findByText(/Waiting for approval/)).toBeInTheDocument();
        const cancel = screen.getAllByRole('button', { name: 'Cancel request' });
        expect(cancel).toHaveLength(1);
        expect(screen.queryByRole('button', { name: 'Submit for review' })).toBeNull();
        fireEvent.click(cancel[0]);

        await waitFor(() => expect(postMock).toHaveBeenCalledWith(`${BASE_URL}/r1/cancel`, {}));
    });

    it('offers no proposal without write access and survives a failed load', async () => {
        canWrite.value = false;
        getMock.mockResolvedValue({ data: {}, error: 'boom' });

        renderList();

        expect(await screen.findByText('The change requests could not be loaded.'))
            .toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Propose change' })).toBeNull();
    });

    it('shows an empty list', async () => {
        getMock.mockResolvedValue({ data: [] });

        renderList();

        expect(await screen.findByText('No change requests yet.')).toBeInTheDocument();
    });
});

describe('ProposeMetricViewChangeDialog', () => {
    beforeEach(async () => {
        getMock.mockReset();
        postMock.mockReset();
        canWrite.value = true;
        getMock.mockResolvedValue({ data: [] });
        await i18n.changeLanguage('en');
    });

    it('shows the YAML parse error under the editor, translated', async () => {
        await i18n.changeLanguage('pt');
        postMock.mockResolvedValue({
            data: {}, error: 'bad', errorCode: 'metric_view_definition_invalid_yaml',
            errorParams: { line: 2, column: 9 },
        });

        renderList();
        fireEvent.click(await screen.findByRole('button', { name: 'Propor alteração' }));
        const editor = screen.getByLabelText('Definição YAML');
        expect(editor).toHaveValue(DEFINITION);
        fireEvent.change(editor, { target: { value: 'source: [unclosed' } });
        fireEvent.click(screen.getByRole('button', { name: 'Salvar como rascunho' }));

        expect(await screen.findByRole('alert')).toHaveTextContent(
            'O YAML não é válido (linha 2, coluna 9).',
        );
        expect(postMock).toHaveBeenCalledWith(BASE_URL, {
            definition: 'source: [unclosed', justification: null,
        });
        await i18n.changeLanguage('en');
    });

    it('saves and submits the draft, then closes', async () => {
        postMock
            .mockResolvedValueOnce({ data: { id: 'r9' } })
            .mockResolvedValueOnce({ data: { id: 'r9', status: 'in_review' } });

        renderList();
        fireEvent.click(await screen.findByRole('button', { name: 'Propose change' }));
        fireEvent.change(screen.getByLabelText('Justification'), { target: { value: ' Net ' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save and submit for review' }));

        await waitFor(() => expect(postMock).toHaveBeenCalledWith(`${BASE_URL}/r9/submit`, {}));
        expect(postMock.mock.calls[0]).toEqual([BASE_URL, {
            definition: DEFINITION, justification: 'Net',
        }]);
        await waitFor(() => expect(screen.queryByLabelText('YAML definition')).toBeNull());
    });

    it('keeps the dialog open when the submit is refused', async () => {
        postMock
            .mockResolvedValueOnce({ data: { id: 'r9' } })
            .mockResolvedValueOnce({
                data: {}, error: 'no wf', errorCode: 'metric_view_change_no_approval',
                errorParams: {},
            });

        renderList();
        fireEvent.click(await screen.findByRole('button', { name: 'Propose change' }));
        fireEvent.click(screen.getByRole('button', { name: 'Save and submit for review' }));

        expect(await screen.findByRole('alert')).toHaveTextContent(
            'No active workflow asks for an approval of this change',
        );
        expect(screen.getByLabelText('YAML definition')).toBeInTheDocument();
    });

    it('falls back to the server message for an unknown code', async () => {
        postMock.mockResolvedValue({ data: {}, error: 'Server said no', errorCode: 'other_code' });

        renderList();
        fireEvent.click(await screen.findByRole('button', { name: 'Propose change' }));
        fireEvent.click(screen.getByRole('button', { name: 'Save as draft' }));

        expect(await screen.findByRole('alert')).toHaveTextContent('Server said no');
    });
});
