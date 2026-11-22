/**
 * The shared selectors' popover is Radix-modal only inside a Dialog (where a non-modal
 * popover loses clicks), and non-modal on a plain page (a modal popover locks the page
 * behind it, #859 review S9). An explicit `modal` prop overrides either.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';

const popoverModal: Array<boolean | undefined> = [];
vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children, modal }: any) => {
    popoverModal.push(modal);
    return <div>{children}</div>;
  },
  PopoverTrigger: ({ children }: any) => <>{children}</>,
  PopoverContent: ({ children }: any) => <div>{children}</div>,
}));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: vi.fn(async () => ({ data: [] })) }) }));
vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({ domains: [], loading: false, getDomainName: () => '' }),
}));

import TagSelector from './tag-selector';
import DomainMultiSelector from './domain-multi-selector';
import { Dialog, DialogContent } from './dialog';

describe('selector popover modality', () => {
  beforeEach(() => { popoverModal.length = 0; });

  it('TagSelector is non-modal on a plain page', () => {
    render(<TagSelector value={[]} onChange={() => {}} />);
    expect(popoverModal[popoverModal.length - 1]).toBe(false);
  });

  it('DomainMultiSelector is non-modal on a plain page', () => {
    render(<DomainMultiSelector value={[]} onChange={() => {}} />);
    expect(popoverModal[popoverModal.length - 1]).toBe(false);
  });

  it('TagSelector is modal inside a Dialog', () => {
    render(
      <Dialog open>
        <DialogContent>
          <TagSelector value={[]} onChange={() => {}} />
        </DialogContent>
      </Dialog>,
    );
    expect(popoverModal[popoverModal.length - 1]).toBe(true);
  });

  it('DomainMultiSelector is modal inside a Dialog', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DomainMultiSelector value={[]} onChange={() => {}} />
        </DialogContent>
      </Dialog>,
    );
    expect(popoverModal[popoverModal.length - 1]).toBe(true);
  });

  it('an explicit modal prop overrides the Dialog default', () => {
    render(
      <Dialog open>
        <DialogContent>
          <TagSelector value={[]} onChange={() => {}} modal={false} />
        </DialogContent>
      </Dialog>,
    );
    expect(popoverModal[popoverModal.length - 1]).toBe(false);
  });

  it('an explicit modal prop overrides the plain-page default', () => {
    render(<DomainMultiSelector value={[]} onChange={() => {}} modal />);
    expect(popoverModal[popoverModal.length - 1]).toBe(true);
  });
});
