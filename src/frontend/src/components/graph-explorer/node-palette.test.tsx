import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NodePalette from './node-palette';

describe('NodePalette', () => {
  it('renders create node and create edge buttons', () => {
    render(
      <NodePalette
        onStartCreateNode={vi.fn()}
        onStartCreateEdge={vi.fn()}
      />,
    );
    expect(screen.getByText('Create Node')).toBeInTheDocument();
    expect(screen.getByText('Create Edge')).toBeInTheDocument();
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
    await user.click(screen.getByText('Create Node'));
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
    await user.click(screen.getByText('Create Edge'));
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
    expect(screen.getByText('Create Node').closest('button')).toBeDisabled();
    expect(screen.getByText('Create Edge').closest('button')).toBeDisabled();
  });

  it('renders instructions', () => {
    render(
      <NodePalette
        onStartCreateNode={vi.fn()}
        onStartCreateEdge={vi.fn()}
      />,
    );
    expect(screen.getByText('Instructions')).toBeInTheDocument();
  });

  it('renders without onStartCreateNode', () => {
    render(
      <NodePalette
        onStartCreateEdge={vi.fn()}
      />,
    );
    expect(screen.getByText('Create Node').closest('button')).toBeDisabled();
  });
});
