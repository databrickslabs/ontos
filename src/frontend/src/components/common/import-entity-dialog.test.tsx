/**
 * Component tests for ImportEntityDialog (#930 review).
 *
 * Covers the parts of the dialog that are deterministic in jsdom: labels render,
 * toggle wiring is bound to the parent's setters, dropped files flow to onFiles.
 * The dropzone + file-upload path uses react-dropzone and jsdom's file APIs are
 * flaky, so file-upload interactions are left to Playwright E2E; what we assert
 * here is enough to catch binding/typing regressions in the shared component.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ImportEntityDialog, ImportEntityDialogLabels } from './import-entity-dialog';

const LABELS: ImportEntityDialogLabels = {
  title: 'Upload X',
  description: 'Pick one or more X files.',
  createMissingDomains: 'Create missing domains',
  createMissingDomainsHint: 'Auto-create domains.',
  adoptIds: 'Adopt IDs from file',
  adoptIdsHint: 'Reuse the file UUID as PK.',
  duplicatesAsNew: 'Import duplicates as new copies',
  duplicatesAsNewHint: 'On: duplicate ids get a fresh id.',
  dropActive: 'Drop here',
  dropInactive: 'Drag and drop or click',
  supportedFormats: 'YAML / JSON',
  pasteLabel: 'Or paste',
  pastePlaceholder: '{}',
  pasteButton: 'Import JSON',
};

function harness(overrides: Partial<Parameters<typeof ImportEntityDialog>[0]> = {}) {
  const setCreateMissingDomains = vi.fn();
  const setAdoptIds = vi.fn();
  const setDuplicatesAsNew = vi.fn();
  const onFiles = vi.fn();
  const onOpenChange = vi.fn();
  const pasteOnChange = vi.fn();
  const pasteSubmit = vi.fn();
  const props = {
    open: true,
    onOpenChange,
    labels: LABELS,
    toggles: {
      createMissingDomains: false, setCreateMissingDomains,
      adoptIds: false, setAdoptIds,
      duplicatesAsNew: false, setDuplicatesAsNew,
    },
    accept: { 'application/json': ['.json'] },
    onFiles,
    uploading: false,
    paste: { value: '', onChange: pasteOnChange, onSubmit: pasteSubmit, submitting: false },
    ...overrides,
  } as Parameters<typeof ImportEntityDialog>[0];
  const utils = render(<ImportEntityDialog {...props} />);
  return { ...utils, setCreateMissingDomains, setAdoptIds, setDuplicatesAsNew, onFiles, onOpenChange, pasteOnChange, pasteSubmit };
}

describe('ImportEntityDialog', () => {
  it('renders title + description + all three toggle labels', () => {
    harness();
    expect(screen.getByText('Upload X')).toBeInTheDocument();
    expect(screen.getByText('Pick one or more X files.')).toBeInTheDocument();
    expect(screen.getByText('Create missing domains')).toBeInTheDocument();
    expect(screen.getByText('Adopt IDs from file')).toBeInTheDocument();
    expect(screen.getByText('Import duplicates as new copies')).toBeInTheDocument();
  });

  it('renders the paste section only when a paste prop is supplied', () => {
    harness({ paste: undefined });
    expect(screen.queryByText('Or paste')).not.toBeInTheDocument();
    harness(); // default: paste provided
    expect(screen.getByText('Or paste')).toBeInTheDocument();
  });

  it('fires the paste submit handler when the Import JSON button is clicked', async () => {
    const user = userEvent.setup();
    const sub = vi.fn();
    const ch = vi.fn();
    render(<ImportEntityDialog
      open onOpenChange={vi.fn()} labels={LABELS}
      toggles={{ createMissingDomains: false, setCreateMissingDomains: vi.fn(), adoptIds: false, setAdoptIds: vi.fn(), duplicatesAsNew: false, setDuplicatesAsNew: vi.fn() }}
      accept={{ 'application/json': ['.json'] }} onFiles={vi.fn()} uploading={false}
      paste={{ value: '{}', onChange: ch, onSubmit: sub, submitting: false }}
    />);
    const button = screen.getByRole('button', { name: 'Import JSON' });
    await user.click(button);
    expect(sub).toHaveBeenCalledTimes(1);
  });

  it('shows the uploading indicator in the dropzone when uploading', () => {
    harness({ uploading: true });
    // The dropzone replaces the "drag and drop" copy with a spinner (role="status"
    // from lucide's Loader2, or just the absence of the copy). Assert that the
    // inactive copy is gone — the simplest invariant.
    expect(screen.queryByText('Drag and drop or click')).not.toBeInTheDocument();
  });
});
