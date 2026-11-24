import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ConceptMeasureGroups from './concept-measure-groups';
import type { MetricViewConsistency, MeasureRef } from '@/types/metric-view-consistency';

const getMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: getMock }) }));

const REVENUE = 'http://example.com/glossary#Revenue';

const ref = (view: string, readable = true, extra: Partial<MeasureRef> = {}): MeasureRef => ({
    asset_id: `id-${view}`, asset_name: view.split('.').pop() ?? view, view, name: 'Revenue',
    display_name: null, entity_id: `${view}.Revenue`, concepts: [REVENUE], readable, ...extra,
});

const definition = (expression: string) => ({
    expression, source: 'main.sales.orders', filter: ["status='closed'"], joins: [],
    window: [{
        order: 'order_date', semiadditive: 'last', offset: null,
        range: { kind: 'trailing', value: 30, unit: 'day', inclusive: false },
    }],
    parameters: [],
});

const conflict: MetricViewConsistency = {
    concept_iri: REVENUE, asset_id: null, verdict: 'conflict', threshold: 0.75, measures: [],
    unresolved: [ref('main.sales.other', true, { name: 'order_date', entity_id: 'x' })],
    groups: [
        {
            full_digest: 'a', measures: [ref('main.sales.revenue_gross')],
            definition: definition('sum(gross_amount)'), other_concepts: [],
            first_level: null, score: null, differences: null,
        },
        {
            full_digest: 'b', measures: [ref('main.sales.revenue_net')],
            definition: definition('sum(amount-refunds)'),
            other_concepts: ['http://example.com/glossary#NetSales'],
            first_level: 'expression', score: 0.65,
            differences: [{
                component: 'columns', only_a: ['main.sales.orders.gross_amount'],
                only_b: ['main.sales.orders.amount', 'main.sales.orders.refunds'],
            }],
        },
        {
            full_digest: 'c', measures: [ref('main.secret.revenue', false)], definition: null,
            other_concepts: [], first_level: 'scope', score: 0.8, differences: null,
        },
    ],
};

function renderGroups() {
    return render(
        <MemoryRouter><ConceptMeasureGroups conceptIri={REVENUE} /></MemoryRouter>,
    );
}

describe('ConceptMeasureGroups', () => {
    beforeEach(async () => {
        getMock.mockReset();
        await i18n.changeLanguage('en');
    });

    it('groups the linked measures by definition and highlights the differences', async () => {
        getMock.mockResolvedValue({ data: conflict });
        renderGroups();

        expect(await screen.findByText('Conflicting definitions')).toBeInTheDocument();
        expect(getMock).toHaveBeenCalledWith(
            `/api/metric-views/consistency?concept_iri=${encodeURIComponent(REVENUE)}`,
        );
        const groups = screen.getAllByTestId('fingerprint-group');
        expect(groups).toHaveLength(3);
        expect(within(groups[0]).getByText('sum(gross_amount)')).toBeInTheDocument();
        expect(within(groups[0]).getByText('order_date · trailing 30 day · last'))
            .toBeInTheDocument();
        expect(within(groups[0]).getByRole('link', { name: 'main.sales.revenue_gross.Revenue' }))
            .toHaveAttribute('href', '/assets/id-main.sales.revenue_gross');
        const net = within(groups[1]);
        expect(net.getByText('Differs from definition 1 in its expression')).toBeInTheDocument();
        expect(net.getByText('Similarity 65%')).toBeInTheDocument();
        const diff = within(net.getByRole('list', { name: 'Differences' }));
        expect(diff.getByText('Columns')).toBeInTheDocument();
        expect(diff.getByText('main.sales.orders.gross_amount')).toBeInTheDocument();
        expect(diff.getByText('main.sales.orders.amount, main.sales.orders.refunds'))
            .toBeInTheDocument();
        expect(net.getByText('The same definition is also linked to: NetSales'))
            .toBeInTheDocument();
        expect(screen.getByText(/compute 3 different things/)).toBeInTheDocument();
        expect(screen.getByText(
            'Linked fields without a stored definition: main.sales.other.order_date',
        ))
            .toBeInTheDocument();
    });

    it('hides the definition of a view the user cannot read', async () => {
        getMock.mockResolvedValue({ data: conflict });
        renderGroups();

        const groups = await screen.findAllByTestId('fingerprint-group');
        const secret = within(groups[2]);
        expect(secret.getByText(/can't read this metric view in Unity Catalog/))
            .toBeInTheDocument();
        expect(secret.queryByText('Expression')).not.toBeInTheDocument();
        // Ontos-level metadata stays: the measure and its asset
        expect(secret.getByRole('link', { name: 'main.secret.revenue.Revenue' }))
            .toBeInTheDocument();
    });

    it('says when every linked measure computes the same thing', async () => {
        getMock.mockResolvedValue({ data: {
            ...conflict, verdict: 'consistent', unresolved: [], groups: [conflict.groups[0]],
        } });
        renderGroups();

        expect(await screen.findByText('Consistent')).toBeInTheDocument();
        expect(screen.getByText('Every measure linked to this concept computes the same thing.'))
            .toBeInTheDocument();
    });

    it('renders nothing without linked measures or when the request fails', async () => {
        getMock.mockResolvedValueOnce({
            data: { ...conflict, verdict: 'none', groups: [], unresolved: [] },
        });
        const { container, unmount } = renderGroups();
        await vi.waitFor(() => expect(getMock).toHaveBeenCalled());
        expect(container).toBeEmptyDOMElement();
        unmount();

        getMock.mockResolvedValueOnce({ data: {}, error: 'boom' });
        const second = renderGroups();
        await vi.waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
        expect(second.container).toBeEmptyDOMElement();
    });

    it('is translated', async () => {
        await i18n.changeLanguage('pt');
        getMock.mockResolvedValue({ data: conflict });
        renderGroups();

        expect(await screen.findByText('Definições em conflito')).toBeInTheDocument();
        expect(screen.getByText('Medidas de metric views')).toBeInTheDocument();
        expect(screen.getByText('Difere da definição 1 em: expressão')).toBeInTheDocument();
        expect(screen.getByText('Similaridade 65%')).toBeInTheDocument();
        expect(screen.getAllByText('Só em Definição 1:').length).toBeGreaterThan(0);
    });
});
