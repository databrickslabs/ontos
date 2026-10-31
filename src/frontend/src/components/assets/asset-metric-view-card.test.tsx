import { describe, it, expect, vi, beforeEach } from 'vitest';
import i18n from '@/i18n/config';
import { render, screen, waitFor } from '@testing-library/react';
import AssetMetricViewCard, { mayBeMetricView } from './asset-metric-view-card';

const getMock = vi.fn();
vi.mock('@/hooks/use-api', () => ({
    useApi: () => ({ get: getMock, post: vi.fn(), delete: vi.fn() }),
}));
vi.mock('@/stores/permissions-store', () => ({
    usePermissions: () => ({ hasPermission: () => false }),
}));

const VIEW = 'main.sales.orders_mv';
const metricView = {
    definition: 'version: 1.1\nsource: main.sales.orders\n',
    metric_view: {
        version: '1.1',
        source: 'main.sales.orders',
        joins: [],
        dimensions: [{ name: 'Order Month', expr: "DATE_TRUNC('MONTH', order_date)" }],
        measures: [{ name: 'Total Revenue', expr: 'SUM(amount)' }],
    },
    links: {
        view_entity_id: VIEW,
        view_links: [],
        fields: [
            { name: 'Order Month', kind: 'dimension', entity_id: `${VIEW}.Order Month`, links: [] },
            {
                name: 'Total Revenue', kind: 'measure', entity_id: `${VIEW}.Total Revenue`,
                links: [{
                    id: 'l1', entity_type: 'uc_column', entity_id: `${VIEW}.Total Revenue`,
                    iri: 'http://example.com/glossary#NetRevenue', label: 'Net Revenue',
                }],
            },
        ],
        removed_fields: [],
    },
};

describe('mayBeMetricView', () => {
    it('asks only for Databricks views and metric views', () => {
        expect(mayBeMetricView({ asset_type_name: 'View', platform: 'databricks' })).toBe(true);
        expect(mayBeMetricView({ asset_type_name: 'Metric View', platform: 'Databricks' }))
            .toBe(true);
        expect(mayBeMetricView({ asset_type_name: 'Table', platform: 'databricks' })).toBe(false);
        expect(mayBeMetricView({ asset_type_name: 'View', platform: 'snowflake' })).toBe(false);
        expect(mayBeMetricView({ asset_type_name: 'View', platform: null })).toBe(false);
    });
});

describe('AssetMetricViewCard', () => {
    beforeEach(() => {
        getMock.mockReset();
        vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false })));
    });

    it('shows the fields and their concepts', async () => {
        getMock.mockResolvedValue({ data: metricView });
        render(<AssetMetricViewCard assetId="a1" />);

        expect(await screen.findByText('Total Revenue')).toBeInTheDocument();
        expect(getMock).toHaveBeenCalledWith('/api/assets/a1/metric-view');
        expect(screen.getByText('Metric view')).toBeInTheDocument();
        expect(screen.getByText('Net Revenue')).toBeInTheDocument();
    });

    it('renders nothing for an asset that is not a metric view', async () => {
        getMock.mockResolvedValue({
            data: {},
            error: 'This asset is not a Unity Catalog metric view.',
            errorCode: 'metric_view_not_found',
        });
        const { container } = render(<AssetMetricViewCard assetId="a1" />);

        await waitFor(() => expect(container).toBeEmptyDOMElement());
    });

    it('says when the definition could not be loaded, translated', async () => {
        getMock.mockResolvedValue({ data: {}, error: 'boom', errorCode: 'internal_error' });
        await i18n.changeLanguage('pt');
        try {
            render(<AssetMetricViewCard assetId="a1" />);

            expect(await screen.findByText('Não foi possível carregar a definição da metric view.'))
                .toBeInTheDocument();
        } finally {
            await i18n.changeLanguage('en');
        }
    });
});
