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

const MV = 'Metric View';
const getResolved = () => getMock.mock.results.length > 0;

describe('AssetMetricViewCard', () => {
    beforeEach(() => {
        getMock.mockReset();
        vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false })));
    });

    it.each([MV, 'View'])('shows the fields and their concepts on a %s asset', async (type) => {
        getMock.mockResolvedValue({ data: metricView });
        render(<AssetMetricViewCard assetId="a1" assetTypeName={type} />);

        expect(await screen.findByText('Total Revenue')).toBeInTheDocument();
        expect(getMock).toHaveBeenCalledWith('/api/assets/a1/metric-view');
        expect(screen.getByText('Metric view')).toBeInTheDocument();
        expect(screen.getByText('Net Revenue')).toBeInTheDocument();
    });

    it.each([MV, 'View'])('renders nothing when a %s asset is not a metric view', async (type) => {
        getMock.mockResolvedValue({
            data: {},
            error: 'This asset is not a Unity Catalog metric view.',
            errorCode: 'metric_view_not_found',
        });
        const { container } = render(<AssetMetricViewCard assetId="a1" assetTypeName={type} />);

        await waitFor(() => expect(getResolved()).toBe(true));
        await waitFor(() => expect(container).toBeEmptyDOMElement());
    });

    it('says the user token is required on a Metric View asset', async () => {
        getMock.mockResolvedValue({
            data: {},
            error: "Reading Unity Catalog needs the user's Databricks token.",
            errorCode: 'user_token_required',
        });
        render(<AssetMetricViewCard assetId="a1" assetTypeName={MV} />);

        expect(await screen.findByText(/read from Unity Catalog with your own access/))
            .toBeInTheDocument();
        expect(screen.queryByText(/could not be loaded/)).toBeNull();
    });

    it('says when the definition of a Metric View asset could not be loaded, translated',
        async () => {
            getMock.mockResolvedValue({ data: {}, error: 'boom', errorCode: 'internal_error' });
            await i18n.changeLanguage('pt');
            try {
                render(<AssetMetricViewCard assetId="a1" assetTypeName={MV} />);

                expect(await screen.findByText(
                    'Não foi possível carregar a definição da metric view.',
                )).toBeInTheDocument();
            } finally {
                await i18n.changeLanguage('en');
            }
        });

    it.each([
        ['user_token_required', "Reading Unity Catalog needs the user's Databricks token."],
        ['user_client_unavailable', 'The user client could not be created.'],
        ['internal_error', 'boom'],
    ])('stays silent on a plain View asset when the answer is %s', async (code, error) => {
        getMock.mockResolvedValue({ data: {}, error, errorCode: code });
        const { container } = render(<AssetMetricViewCard assetId="a1" assetTypeName="View" />);

        expect(container).toBeEmptyDOMElement(); // nothing while loading either
        await waitFor(() => expect(getResolved()).toBe(true));
        await new Promise((r) => setTimeout(r, 0));
        expect(container).toBeEmptyDOMElement();
        expect(screen.queryByText('Metric view')).toBeNull();
    });

    it('shows the loading state on a Metric View asset only', () => {
        getMock.mockReturnValue(new Promise(() => {}));
        render(<AssetMetricViewCard assetId="a1" assetTypeName={MV} />);

        expect(screen.getByLabelText('Loading the metric view')).toBeInTheDocument();
    });
});
