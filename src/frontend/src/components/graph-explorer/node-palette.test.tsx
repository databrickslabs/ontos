import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NodePalette from './node-palette';

// Mock react-i18next — return the key as the display text
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

describe('NodePalette', () => {
  it('renders create node and create edge buttons', () => {
    render(
      <NodePalette
        onStartCreateNode={vi.fn()}
        onStartCreateEdge={vi.fn()}
      />,
    );
    expect(screen.getByText('actions.createNode')).toBeInTheDocument();
    expect(screen.getByText('actions.createEdge')).toBeInTheDocument();
  });

  it('calls onStartCreateNode when create node clicked', async () => {
    const user = userEvent.setup();
    const onCreateNode = vi.fn();
    render(
      <NodePalette
        onStartCreateNode={onCreateNode}
        onStartCreateEdge={vi.fn()}
      />,
    );
    await user.click(screen.getByText('actions.createNode'));
    expect(onCreateNode).toHaveBeenCalledTimes(1);
  });

  it('calls onStartCreateEdge when create edge clicked', async () => {
    const user = userEvent.setup();
    const onCreateEdge = vi.fn();
    render(
      <NodePalette
        onStartCreateNode={vi.fn()}
        onStartCreateEdge={onCreateEdge}
      />,
    );
    await user.click(screen.getByText('actions.createEdge'));
    expect(onCreateEdge).toHaveBeenCalledTimes(1);
  });

  it('disables buttons when disabled prop is true', () => {
    render(
      <NodePalette
        onStartCreateNode={vi.fn()}
        onStartCreateEdge={vi.fn()}
        disabled={true}
      />,
    );
    expect(screen.getByText('actions.createNode').closest('button')).toBeDisabled();
    expect(screen.getByText('actions.createEdge').closest('button')).toBeDisabled();
  });

  it('renders instructions', () => {
    render(
      <NodePalette
        onStartCreateNode={vi.fn()}
        onStartCreateEdge={vi.fn()}
      />,
    );
    expect(screen.getByText('palette.instructions')).toBeInTheDocument();
  });

  it('renders without onStartCreateNode', () => {
    render(
      <NodePalette
        onStartCreateEdge={vi.fn()}
      />,
    );
    expect(screen.getByText('actions.createNode').closest('button')).toBeDisabled();
  });
});
