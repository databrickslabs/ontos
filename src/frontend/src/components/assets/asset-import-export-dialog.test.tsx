import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ImportRowWarnings } from './asset-import-export-dialog';

describe('ImportRowWarnings', () => {
  it('shows a saved row whose description was not written to Unity Catalog', () => {
    render(
      <ImportRowWarnings
        warnings={[{
          code: 'uc_description_permission_denied',
          message: 'english fallback',
          params: { object: 'main.sales.orders' },
        }]}
      />
    );
    expect(
      screen.getByText(/Unity Catalog refused to change the description of main.sales.orders/)
    ).toBeInTheDocument();
  });

  it('renders nothing without warnings', () => {
    const { container } = render(<ImportRowWarnings warnings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
