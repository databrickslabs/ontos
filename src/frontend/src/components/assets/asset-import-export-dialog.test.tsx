import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AssetImportExportDialog, { ImportRowWarnings } from './asset-import-export-dialog';

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

  it('shows a row over the import write limit with the limit', () => {
    render(
      <ImportRowWarnings
        warnings={[{
          code: 'uc_description_import_write_limit',
          message: 'english fallback',
          params: { object: 'main.s.b', limit: 100 },
        }]}
      />
    );
    expect(screen.getByText(/limit of 100 rows tried/)).toHaveTextContent('main.s.b');
  });

  it('renders nothing without warnings', () => {
    const { container } = render(<ImportRowWarnings warnings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('AssetImportExportDialog import help', () => {
  it('says an empty properties cell keeps the stored ones and {} clears them', async () => {
    render(<AssetImportExportDialog isOpen onOpenChange={() => {}} canImport />);
    await userEvent.click(screen.getByRole('tab', { name: /import/i }));
    expect(
      screen.getByText(/empty cell keeps the asset's stored properties; use \{\} to clear them/)
    ).toBeInTheDocument();
  });
});
