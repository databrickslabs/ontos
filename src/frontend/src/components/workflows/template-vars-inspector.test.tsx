import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/utils';
import TemplateVarsInspector from './template-vars-inspector';
import * as useApiModule from '@/hooks/use-api';
import * as useToastModule from '@/hooks/use-toast';
import type { TemplateVarsResponse } from '@/types/template-vars';

// ---- shared fixtures ----

const fakeResponse: TemplateVarsResponse = {
  trigger: 'on_request_access',
  entity_type: 'data_product',
  groups: [
    {
      namespace: 'entity',
      description: 'Fields on the request and underlying DP.',
      variables: [
        {
          path: 'entity.catalogs',
          type: 'array',
          description: 'Sorted, deduped catalog names.',
          sample: ['main', 'prod'],
        },
        {
          path: 'entity.entity_id',
          type: 'string',
          description: 'ID of the underlying entity.',
          sample: 'prd-123',
        },
      ],
    },
    {
      namespace: 'flat',
      description: 'Universal variables.',
      variables: [
        {
          path: 'user_email',
          type: 'string',
          description: 'Email of the user firing the trigger.',
          sample: 'alice@example.com',
        },
      ],
    },
  ],
};

function mockUseApi(response: { data: any; error?: string | null }) {
  const getMock = vi.fn().mockResolvedValue(response);
  vi.spyOn(useApiModule, 'useApi').mockReturnValue({
    // The component only uses ``get``; the others must exist for the
    // type contract but are not exercised here.
    get: getMock,
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    loading: false,
  } as any);
  return getMock;
}

function mockUseToast() {
  const toastFn = vi.fn();
  vi.spyOn(useToastModule, 'useToast').mockReturnValue({
    toast: toastFn,
    dismiss: vi.fn(),
    toasts: [],
  } as any);
  return toastFn;
}

describe('TemplateVarsInspector', () => {
  let writeTextMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    // jsdom exposes ``navigator.clipboard`` as a read-only getter, so
    // we install a fresh stub via ``Object.defineProperty`` rather
    // than direct assignment. ``configurable: true`` lets later tests
    // overwrite it in turn.
    writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      writable: true,
      value: { writeText: writeTextMock },
    });
  });

  it('renders a prompt when trigger/entity are missing', () => {
    mockUseApi({ data: fakeResponse });
    renderWithProviders(<TemplateVarsInspector />);
    expect(screen.getByText(/Pick a trigger and entity type/i)).toBeInTheDocument();
  });

  it('fetches with the supplied trigger and entity type', async () => {
    const getMock = mockUseApi({ data: fakeResponse });
    mockUseToast();

    renderWithProviders(
      <TemplateVarsInspector
        triggerType="on_request_access"
        entityType="data_product"
      />,
    );

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith(
        '/api/workflows/template-vars?trigger=on_request_access&entity_type=data_product',
      );
    });
  });

  it('renders every group and variable path', async () => {
    mockUseApi({ data: fakeResponse });
    mockUseToast();
    const user = userEvent.setup();

    renderWithProviders(
      <TemplateVarsInspector
        triggerType="on_request_access"
        entityType="data_product"
      />,
    );

    // Group headers (with counts) render even while collapsed.
    expect(await screen.findByText('entity')).toBeInTheDocument();
    expect(screen.getByText('flat')).toBeInTheDocument();
    // Groups start collapsed (Radix unmounts their content) — expand
    // the entity group so the placeholder rows hydrate before asserting.
    await user.click(screen.getByText('entity'));
    expect(await screen.findByText('${entity.catalogs}')).toBeInTheDocument();
    expect(screen.getByText('${entity.entity_id}')).toBeInTheDocument();
  });

  it('copy button fires navigator.clipboard.writeText with the placeholder', async () => {
    mockUseApi({ data: fakeResponse });
    mockUseToast();
    // ``userEvent.setup()`` installs its own clipboard stub on
    // ``navigator.clipboard`` (so its built-in copy/paste helpers
    // work). To assert what our component writes, we re-stub after
    // setup with our own spy. ``writeOnly`` keeps clipboard
    // interaction inside the test.
    const user = userEvent.setup();
    const localWriteText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      writable: true,
      value: { writeText: localWriteText, readText: vi.fn() },
    });

    renderWithProviders(
      <TemplateVarsInspector
        triggerType="on_request_access"
        entityType="data_product"
      />,
    );

    // Groups start collapsed — expand entity so the row hydrates.
    await screen.findByText('entity');
    await user.click(screen.getByText('entity'));
    await screen.findByText('${entity.catalogs}');

    // Find all copy buttons (one per variable) and pick the one whose
    // aria-label targets ${entity.catalogs}.
    const buttons = screen.getAllByRole('button');
    const copyButton = buttons.find(
      (b) => b.getAttribute('aria-label') === 'Copy ${entity.catalogs}',
    );
    expect(copyButton).toBeDefined();
    await user.click(copyButton!);

    await waitFor(() => {
      expect(localWriteText).toHaveBeenCalledWith('${entity.catalogs}');
    });
  });

  it('renders empty-state when groups list is empty', async () => {
    mockUseApi({
      data: {
        trigger: 'on_create',
        entity_type: 'catalog',
        groups: [],
      } as TemplateVarsResponse,
    });
    mockUseToast();

    renderWithProviders(
      <TemplateVarsInspector triggerType="on_create" entityType="catalog" />,
    );

    expect(
      await screen.findByText(/No variable descriptors are registered/i),
    ).toBeInTheDocument();
  });

  it('renders error state when the API returns an error', async () => {
    mockUseApi({ data: {} as TemplateVarsResponse, error: 'boom' });
    mockUseToast();

    renderWithProviders(
      <TemplateVarsInspector
        triggerType="on_request_access"
        entityType="data_product"
      />,
    );

    expect(await screen.findByText(/Failed to load variables/i)).toBeInTheDocument();
  });
});
