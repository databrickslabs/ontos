import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import MeasureConsistencyList from './measure-consistency-list';
import type { MetricViewConsistency, MeasureRef } from '@/types/metric-view-consistency';

const getMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: getMock }) }));

const REVENUE = 'http://example.com/glossary#Revenue';
const ref = (view: string, name: string, extra: Partial<MeasureRef> = {}): MeasureRef => ({
    asset_id: `id-${view}`, asset_name: view, view, name, display_name: null,
    entity_id: `${view}.${name}`, concepts: [], readable: true, ...extra,
});

const data: MetricViewConsistency = {
    concept_iri: null, asset_id: 'a1', verdict: null, groups: [], unresolved: [], threshold: 0.75,
    measures: [
        {
            measure: ref('main.sales.gross', 'Revenue', { concepts: [REVENUE] }), error: null,
            matches: [
                {
                    measure: ref('main.sales.net', 'Revenue', { concepts: [REVENUE] }),
                    verdict: 'conflict', first_level: 'expression', score: 0.65,
                    differences: [{
                        component: 'columns', only_a: ['main.sales.orders.gross_amount'],
                        only_b: ['main.sales.orders.amount'],
                    }],
                },
                {
                    measure: ref('main.secret.mv', 'Gross', { readable: false, asset_id: null }),
                    verdict: 'unrecognized_duplicate', first_level: null, score: 1,
                    differences: null,
                },
            ],
        },
        { measure: ref('main.sales.gross', 'Orders'), error: null, matches: [] },
        { measure: ref('main.sales.gross', 'Loop'), error: 'reference_cycle', matches: [] },
    ],
};

function renderList() {
    return render(<MemoryRouter><MeasureConsistencyList assetId="a1" /></MemoryRouter>);
}

describe('MeasureConsistencyList', () => {
    beforeEach(async () => {
        getMock.mockReset();
        await i18n.changeLanguage('en');
    });

    it('lists per measure the same and similar definitions, with the differences', async () => {
        getMock.mockResolvedValue({ data });
        renderList();

        expect(await screen.findByText('Same or similar definitions')).toBeInTheDocument();
        expect(getMock).toHaveBeenCalledWith('/api/metric-views/consistency?asset_id=a1');
        const blocks = screen.getAllByTestId('measure-consistency');
        // Orders has no match and is left out
        expect(blocks).toHaveLength(2);
        const [conflict, unrecognized] = within(blocks[0]).getAllByTestId('measure-match');
        expect(within(conflict).getByText('Conflict')).toBeInTheDocument();
        expect(within(conflict).getByRole('link', { name: 'main.sales.net.Revenue' }))
            .toHaveAttribute('href', '/assets/id-main.sales.net');
        expect(within(conflict).getByText('linked to Revenue')).toBeInTheDocument();
        expect(within(conflict).getByText('Similarity 65%')).toBeInTheDocument();
        expect(within(conflict).getByText('Only in Revenue:')).toBeInTheDocument();
        expect(within(conflict).getByText('main.sales.orders.gross_amount')).toBeInTheDocument();
        expect(within(conflict).getByText('Only in main.sales.net.Revenue:')).toBeInTheDocument();
        expect(within(unrecognized).getByText('Unrecognized duplicate')).toBeInTheDocument();
        expect(within(unrecognized).getByText('main.secret.mv.Gross')).toBeInTheDocument();
        expect(within(unrecognized).queryByRole('link')).not.toBeInTheDocument();
        expect(within(unrecognized).getByText(/can't read this metric view/)).toBeInTheDocument();
        expect(within(blocks[1]).getByText(/references form a cycle/)).toBeInTheDocument();
    });

    it('renders nothing when no measure has a match or the request fails', async () => {
        getMock.mockResolvedValueOnce({ data: { ...data, measures: [data.measures[1]] } });
        const first = renderList();
        await vi.waitFor(() => expect(getMock).toHaveBeenCalled());
        expect(first.container).toBeEmptyDOMElement();
        first.unmount();

        getMock.mockResolvedValueOnce({ data: {}, error: 'boom' });
        const second = renderList();
        await vi.waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
        expect(second.container).toBeEmptyDOMElement();
    });

    it('is translated', async () => {
        await i18n.changeLanguage('pt');
        getMock.mockResolvedValue({ data });
        renderList();

        expect(await screen.findByText('Definições iguais ou parecidas')).toBeInTheDocument();
        expect(screen.getByText('Conflito')).toBeInTheDocument();
        expect(screen.getByText('Duplicada não reconhecida')).toBeInTheDocument();
        expect(screen.getByText('Similaridade 65%')).toBeInTheDocument();
    });
});
