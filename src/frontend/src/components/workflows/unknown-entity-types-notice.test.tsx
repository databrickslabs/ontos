/**
 * Stored trigger entity types the app no longer knows are shown as such, not
 * as "any entity", and can be removed (#1151).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

import i18n from '@/i18n/config';
import { UnknownEntityTypesNotice } from './unknown-entity-types-notice';

afterEach(async () => {
  await act(async () => {
    await i18n.changeLanguage('en');
  });
});

describe('UnknownEntityTypesNotice', () => {
  it('shows each unknown type and removes one', () => {
    const onRemove = vi.fn();
    render(<UnknownEntityTypesNotice values={['dataset']} onRemove={onRemove} />);

    expect(screen.getByText('Unknown entity type: dataset')).toBeInTheDocument();
    expect(screen.getByTestId('unknown-entity-types')).toHaveTextContent(
      'This trigger lists an entity type that no longer exists. '
      + 'It matches nothing: remove it to change the trigger.',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Remove dataset' }));
    expect(onRemove).toHaveBeenCalledWith('dataset');
  });

  it('is translated, with the plural for several types', async () => {
    await act(async () => {
      await i18n.changeLanguage('pt');
    });
    render(<UnknownEntityTypesNotice values={['dataset', 'legacy']} onRemove={() => {}} />);

    expect(screen.getByText('Tipo de entidade desconhecido: legacy')).toBeInTheDocument();
    expect(screen.getByTestId('unknown-entity-types')).toHaveTextContent(
      'Este gatilho lista 2 tipos de entidade que não existem mais.',
    );
  });

  it('renders nothing without unknown types', () => {
    const { container } = render(<UnknownEntityTypesNotice values={[]} onRemove={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});
