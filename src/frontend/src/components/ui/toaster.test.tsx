/**
 * A toast must not swallow Escape: while it is showing and focus is outside
 * it, Escape acts on the topmost dialog/popover/sheet as if no toast were there.
 */
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { useState } from 'react';
import { Toaster } from './toaster';
import { toast } from '@/hooks/use-toast';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from './dialog';

function Harness({ onOpenChange }: { onOpenChange?: (o: boolean) => void }) {
  const [open, setOpen] = useState(true);
  const [inner, setInner] = useState(false);
  return (
    <>
      <Dialog open={open} onOpenChange={(o) => { onOpenChange?.(o); setOpen(o); }}>
        <DialogContent>
          <DialogTitle>Title</DialogTitle>
          <DialogDescription>Body</DialogDescription>
          <button onClick={() => setInner(true)}>pop</button>
          <Dialog open={inner} onOpenChange={setInner}>
            <DialogContent>
              <DialogTitle>Inner</DialogTitle>
              <DialogDescription>popover body</DialogDescription>
            </DialogContent>
          </Dialog>
        </DialogContent>
      </Dialog>
      <Toaster />
    </>
  );
}

const showToast = () => act(() => { toast({ title: 'Saved', description: 'ok' }); });
const esc = (el: Element | null = document.activeElement) =>
  fireEvent.keyDown(el ?? document.body, { key: 'Escape' });

afterEach(() => { act(() => { vi.clearAllTimers(); }); });

describe('Toaster Escape handling', () => {
  it('closes the dialog on Escape while a toast is showing', async () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);
    await showToast();
    await screen.findByText('Saved');
    esc();
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(screen.queryByText('Saved')).toBeNull();
  });

  it('closes only the toast when focus is inside the toast', async () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);
    await showToast();
    const title = await screen.findByText('Saved');
    esc(title);
    await waitFor(() => expect(title.closest('[data-state="closed"]')).not.toBeNull());
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it('closes the toast on Escape when no dialog is open', async () => {
    render(<><Toaster /></>);
    await showToast();
    await screen.findByText('Saved');
    esc(document.body);
    await waitFor(() => expect(screen.queryByText('Saved')).toBeNull());
  });

  it('closes only the nested dialog, not the outer one, on Escape', async () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);
    await screen.findByText('Title');
    fireEvent.click(screen.getByText('pop'));
    await screen.findByText('popover body');
    await showToast();
    await screen.findByText('Saved');
    esc();
    await waitFor(() => expect(screen.queryByText('popover body')).toBeNull());
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByText('Title')).toBeTruthy();
  });
});
