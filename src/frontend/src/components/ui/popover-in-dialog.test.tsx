/**
 * A popover opened inside a modal dialog can be clicked.
 *
 * The modal dialog sets `pointer-events: none` on <body>; Radix gives the
 * layers above it `pointer-events: auto`, but only for layers registered in the
 * same dismissable-layer context. With two copies of
 * @radix-ui/react-dismissable-layer (one for the dialog, one for the popover),
 * the popover kept `none`: its list showed over the dialog but every click went
 * to the dialog under it (the "Link contract" picker of a product's deliverable).
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from './dialog';
import { Popover, PopoverContent, PopoverTrigger } from './popover';

describe('Popover inside a Dialog', () => {
  it('takes pointer events', async () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Link contract</DialogTitle>
          <DialogDescription>Pick one</DialogDescription>
          <Popover open>
            <PopoverTrigger>Choose</PopoverTrigger>
            <PopoverContent>contract list</PopoverContent>
          </Popover>
        </DialogContent>
      </Dialog>,
    );

    const list = await screen.findByText('contract list');
    expect(document.body.style.pointerEvents).toBe('none');
    expect(list.style.pointerEvents).toBe('auto');
  });
});
