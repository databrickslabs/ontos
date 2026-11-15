/**
 * DropdownMenu and NavigationMenu after the dismissable-layer override.
 *
 * Both used their own copy of @radix-ui/react-dismissable-layer (1.1.11) before the
 * override pinned one copy (1.1.19) for every Radix package. These tests check
 * the behaviors that depend on it: a menu opened inside a modal dialog takes
 * pointer events, a click outside closes a dropdown, and Escape a navigation menu.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from './dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from './dropdown-menu';
import {
  NavigationMenu, NavigationMenuContent, NavigationMenuItem, NavigationMenuList,
  NavigationMenuTrigger,
} from './navigation-menu';

describe('DropdownMenu on the pinned dismissable layer', () => {
  it('takes pointer events inside a modal dialog and runs its item', async () => {
    const onSelect = vi.fn();
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Edit</DialogTitle>
          <DialogDescription>Actions</DialogDescription>
          <DropdownMenu open>
            <DropdownMenuTrigger>Actions</DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={onSelect}>Delete</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </DialogContent>
      </Dialog>,
    );

    const item = await screen.findByText('Delete');
    expect(document.body.style.pointerEvents).toBe('none');
    expect((item.closest('[role="menu"]') as HTMLElement).style.pointerEvents).toBe('auto');
    fireEvent.click(item);
    expect(onSelect).toHaveBeenCalled();
  });

  it('closes on a click outside', async () => {
    render(
      <div>
        <p>outside</p>
        <DropdownMenu>
          <DropdownMenuTrigger>Actions</DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem>Delete</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>,
    );
    const user = userEvent.setup();

    await user.click(screen.getByText('Actions'));
    expect(await screen.findByText('Delete')).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByText('outside'));

    await waitFor(() => expect(screen.queryByText('Delete')).not.toBeInTheDocument());
  });
});

describe('NavigationMenu on the pinned dismissable layer', () => {
  it('opens its content and closes it on Escape', async () => {
    render(
      <NavigationMenu>
        <NavigationMenuList>
          <NavigationMenuItem>
            <NavigationMenuTrigger>Products</NavigationMenuTrigger>
            <NavigationMenuContent>All products</NavigationMenuContent>
          </NavigationMenuItem>
        </NavigationMenuList>
      </NavigationMenu>,
    );
    const user = userEvent.setup();

    await user.click(screen.getByText('Products'));
    expect(await screen.findByText('All products')).toBeInTheDocument();
    await user.keyboard('{Escape}');

    await waitFor(() => expect(screen.queryByText('All products')).not.toBeInTheDocument());
  });
});
