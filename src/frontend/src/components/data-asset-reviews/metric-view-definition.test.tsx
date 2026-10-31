import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import MetricViewDefinitionPanel from './metric-view-definition';
import { MetricViewDefinition, MetricViewLinks } from '@/types/data-asset-review';

const postMock = vi.fn();
const deleteMock = vi.fn();
const toastMock = vi.fn();
let canEdit = true;
let pickerProps: { excludeIris?: string[]; title?: string } = {};

vi.mock('@/hooks/use-api', () => ({
    useApi: () => ({ post: postMock, delete: deleteMock }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock('@/stores/permissions-store', () => ({
    usePermissions: () => ({ hasPermission: () => canEdit }),
}));
// The concept picker: one button that picks the Net Revenue concept
vi.mock('@/components/semantic/concept-select-dialog', () => ({
    default: (props: {
        isOpen: boolean; onSelect: (iri: string) => void; excludeIris?: string[]; title?: string;
    }) => {
        pickerProps = props;
        return props.isOpen ? (
            <button type="button" onClick={() => props.onSelect(NET_REVENUE)}>pick concept</button>
        ) : null;
    },
}));

const VIEW = 'main.sales.orders_mv';
const NET_REVENUE = 'http://example.com/glossary#NetRevenue';
const SALES = 'http://example.com/glossary#Sales';

const link = (
    id: string, entityType: 'uc_table' | 'uc_column', entityId: string, iri: string, label: string,
) => ({ id, entity_type: entityType, entity_id: entityId, iri, label });
const REMOVE = { name: 'Remove concept link' };
const revenueLink = link('l-rev', 'uc_column', `${VIEW}.Total Revenue`, NET_REVENUE, 'Net Revenue');
const oldLink = link('l-old', 'uc_column', `${VIEW}.Gross Revenue`, NET_REVENUE, 'Old Revenue');
const removedField = {
    name: 'Gross Revenue', kind: null, entity_id: `${VIEW}.Gross Revenue`, links: [oldLink],
};

const definition: MetricViewDefinition = {
    definition: 'version: 1.1\nsource: main.sales.orders\n',
    metric_view: {
        version: '1.1',
        source: 'main.sales.orders',
        filter: "status = 'closed'",
        joins: [{ name: 'customers', source: 'main.sales.customers', on: 'source.customer_id = customers.id' }],
        dimensions: [
            { name: 'Order Month', expr: "DATE_TRUNC('MONTH', order_date)", comment: 'Month of the order' },
        ],
        measures: [
            { name: 'Total Revenue', expr: 'SUM(amount)', display_name: 'Revenue' },
            { name: 'Orders', expr: 'COUNT(*)' },
        ],
    },
};

describe('MetricViewDefinitionPanel', () => {
    it('shows the source, the dimensions and the measures', () => {
        render(<MetricViewDefinitionPanel definition={definition} />);

        expect(screen.getByText('main.sales.orders')).toBeInTheDocument();
        expect(screen.getByText("status = 'closed'")).toBeInTheDocument();
        expect(screen.getByText(/^customers/)).toBeInTheDocument();
        expect(screen.getByText('ON source.customer_id = customers.id')).toBeInTheDocument();
        expect(screen.getByText('Order Month')).toBeInTheDocument();
        expect(screen.getByText('Month of the order')).toBeInTheDocument();
        expect(screen.getByText("DATE_TRUNC('MONTH', order_date)")).toBeInTheDocument();
        // A measure's display name is shown in place of its name
        expect(screen.getByText('Revenue')).toBeInTheDocument();
        expect(screen.getByText('SUM(amount)')).toBeInTheDocument();
        expect(screen.getByText('COUNT(*)')).toBeInTheDocument();
        expect(screen.getByText('Dimensions')).toBeInTheDocument();
        expect(screen.getByText('Measures')).toBeInTheDocument();
    });

    it('shows the YAML when the definition could not be parsed', () => {
        render(<MetricViewDefinitionPanel definition={{ definition: 'not: [valid', metric_view: null }} />);

        expect(screen.getByText(/could not be read/)).toBeInTheDocument();
        expect(screen.getByText('not: [valid')).toBeVisible();
    });

    it('says when a metric view has no dimensions', () => {
        render(<MetricViewDefinitionPanel definition={{
            ...definition,
            metric_view: { ...definition.metric_view!, dimensions: [] },
        }} />);

        expect(screen.getByText('No dimensions defined.')).toBeInTheDocument();
    });

    it('shows a USING join and the materialization, translated', async () => {
        await i18n.changeLanguage('pt');
        try {
            render(<MetricViewDefinitionPanel definition={{
                ...definition,
                metric_view: {
                    ...definition.metric_view!,
                    joins: [{ name: 'store', source: 'main.sales.stores', on: null, using: ['store_id'] }],
                    materialization: {
                        schedule: 'EVERY 6 HOURS', mode: 'relaxed',
                        materialized_views: [{ name: 'by_status', type: 'aggregated' }],
                    },
                },
            }} />);

            expect(screen.getByText('USING (store_id)')).toBeInTheDocument();
            expect(screen.getByText('Materialização')).toBeInTheDocument();
            expect(screen.getByText(/EVERY 6 HOURS, 1 view materializada/)).toBeInTheDocument();
            expect(screen.getByText('(by_status: aggregated)')).toBeInTheDocument();
        } finally {
            await i18n.changeLanguage('en');
        }
    });
});

const links: MetricViewLinks = {
    view_entity_id: VIEW,
    view_links: [link('l-view', 'uc_table', VIEW, SALES, 'Sales')],
    fields: [
        { name: 'Order Month', kind: 'dimension', entity_id: `${VIEW}.Order Month`, links: [] },
        {
            name: 'Total Revenue', kind: 'measure', entity_id: `${VIEW}.Total Revenue`,
            links: [revenueLink],
        },
        { name: 'Orders', kind: 'measure', entity_id: `${VIEW}.Orders`, links: [] },
    ],
    removed_fields: [],
};

const rowOf = (text: string) => within(screen.getByText(text).closest('tr') as HTMLElement);

describe('MetricViewDefinitionPanel concept links', () => {
    beforeEach(() => {
        postMock.mockReset();
        deleteMock.mockReset();
        toastMock.mockReset();
        canEdit = true;
        pickerProps = {};
        vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false })));
    });

    it('lists the concepts of the view and of each field', () => {
        render(<MetricViewDefinitionPanel definition={{ ...definition, links }} />);

        expect(screen.getByText('Concepts linked to the metric view')).toBeInTheDocument();
        expect(screen.getByText('Sales')).toBeInTheDocument();
        expect(rowOf('Revenue').getByText('Net Revenue')).toBeInTheDocument();
        expect(rowOf('COUNT(*)').queryByText('Net Revenue')).not.toBeInTheDocument();
        expect(screen.getAllByRole('columnheader', { name: 'Concepts' })).toHaveLength(2);
    });

    it('links a concept to a measure as a uc_column', async () => {
        postMock.mockResolvedValue({
            data: link('l-new', 'uc_column', `${VIEW}.Orders`, NET_REVENUE, 'Net Revenue'),
        });
        render(<MetricViewDefinitionPanel definition={{ ...definition, links }} />);

        fireEvent.click(screen.getByRole('button', { name: 'Link a concept to Orders' }));
        expect(pickerProps.title).toBe('Link a concept to Orders');
        expect(pickerProps.excludeIris).toEqual([]);
        fireEvent.click(screen.getByText('pick concept'));

        await waitFor(() => expect(rowOf('COUNT(*)').getByText('Net Revenue')).toBeInTheDocument());
        expect(postMock).toHaveBeenCalledWith('/api/semantic-links/', {
            entity_type: 'uc_column', entity_id: `${VIEW}.Orders`, iri: NET_REVENUE,
        });
        expect(toastMock).toHaveBeenCalledWith({ title: 'Concept linked to Orders.' });
        expect(screen.queryByText('pick concept')).not.toBeInTheDocument();
    });

    it('links a concept to the view as a uc_table, without offering the linked ones', async () => {
        postMock.mockResolvedValue({
            data: link('l-v2', 'uc_table', VIEW, NET_REVENUE, 'Net Revenue'),
        });
        render(<MetricViewDefinitionPanel definition={{ ...definition, links }} />);

        fireEvent.click(screen.getByRole('button', { name: `Link a concept to ${VIEW}` }));
        expect(pickerProps.excludeIris).toEqual([SALES]);
        fireEvent.click(screen.getByText('pick concept'));

        await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/semantic-links/', {
            entity_type: 'uc_table', entity_id: VIEW, iri: NET_REVENUE,
        }));
    });

    it('unlinks a concept from a measure', async () => {
        deleteMock.mockResolvedValue({ data: { deleted: true } });
        render(<MetricViewDefinitionPanel definition={{ ...definition, links }} />);

        fireEvent.click(rowOf('Revenue').getByRole('button', REMOVE));

        await waitFor(() => expect(rowOf('Revenue').queryByText('Net Revenue')).toBeNull());
        expect(deleteMock).toHaveBeenCalledWith('/api/semantic-links/l-rev');
        expect(toastMock).toHaveBeenCalledWith({ title: 'Concept link removed.' });
    });

    it('keeps the links when the API refuses, and says so', async () => {
        postMock.mockResolvedValue({ data: {}, error: 'Failed to add semantic link' });
        deleteMock.mockResolvedValue({ data: {}, error: 'Link not found' });
        render(<MetricViewDefinitionPanel definition={{ ...definition, links }} />);

        fireEvent.click(screen.getByRole('button', { name: 'Link a concept to Orders' }));
        fireEvent.click(screen.getByText('pick concept'));
        await waitFor(() => expect(toastMock).toHaveBeenCalledWith({
            title: 'The concept could not be linked.', variant: 'destructive',
        }));
        expect(screen.getByText('pick concept')).toBeInTheDocument();

        fireEvent.click(rowOf('Revenue').getByRole('button', REMOVE));
        await waitFor(() => expect(toastMock).toHaveBeenCalledWith({
            title: 'The concept link could not be removed.', variant: 'destructive',
        }));
        expect(rowOf('Revenue').getByText('Net Revenue')).toBeInTheDocument();
    });

    it('flags links of fields that are no longer in the definition', async () => {
        deleteMock.mockResolvedValue({ data: { deleted: true } });
        render(<MetricViewDefinitionPanel definition={{
            ...definition,
            links: {
                ...links,
                removed_fields: [removedField],
            },
        }} />);

        expect(screen.getByText('Linked fields no longer in the definition')).toBeInTheDocument();
        expect(screen.getByText('Gross Revenue')).toBeInTheDocument();
        expect(screen.getByText('Old Revenue')).toBeInTheDocument();

        const alert = screen.getByRole('alert');
        fireEvent.click(within(alert).getByRole('button', REMOVE));
        await waitFor(() => expect(
            screen.queryByText('Linked fields no longer in the definition'),
        ).toBeNull());
        expect(deleteMock).toHaveBeenCalledWith('/api/semantic-links/l-old');
    });

    it('shows the links read-only without the permission', () => {
        canEdit = false;
        render(<MetricViewDefinitionPanel definition={{ ...definition, links }} />);

        expect(rowOf('Revenue').getByText('Net Revenue')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Link a concept/ })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', REMOVE)).not.toBeInTheDocument();
    });

    it('has no concepts column without links', () => {
        render(<MetricViewDefinitionPanel definition={definition} />);

        expect(screen.queryByRole('columnheader', { name: 'Concepts' })).not.toBeInTheDocument();
        expect(screen.queryByText('Concepts linked to the metric view')).not.toBeInTheDocument();
    });

    it('is translated', async () => {
        await i18n.changeLanguage('pt');
        try {
            render(<MetricViewDefinitionPanel definition={{
                ...definition,
                links: { ...links, removed_fields: [removedField] },
            }} />);

            expect(screen.getByText('Conceitos vinculados à metric view')).toBeInTheDocument();
            expect(screen.getAllByRole('columnheader', { name: 'Conceitos' })).toHaveLength(2);
            expect(screen.getByRole('button', { name: 'Vincular um conceito a Orders' }))
                .toBeInTheDocument();
            expect(screen.getByText('Campos vinculados que não estão mais na definição'))
                .toBeInTheDocument();
        } finally {
            await i18n.changeLanguage('en');
        }
    });
});
