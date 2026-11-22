import { createContext } from 'react';

/**
 * True inside a modal Dialog (DialogContent provides it). A popover opened there must
 * be Radix-modal to stay clickable, while elsewhere a modal popover would lock the page.
 */
export const InsideModalContext = createContext(false);
