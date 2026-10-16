import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MetricViewDefinitionPanel from './metric-view-definition';
import { MetricViewDefinition } from '@/types/data-asset-review';

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
        expect(screen.getByText('customers')).toBeInTheDocument();
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
});
