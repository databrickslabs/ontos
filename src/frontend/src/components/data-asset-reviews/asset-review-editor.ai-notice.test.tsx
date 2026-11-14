/**
 * The AI analysis can come back with a `notice_code` (the model refused). The
 * editor shows that notice in the user's language and keeps the reply as plain
 * text, never as markdown.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import i18n from '@/i18n/config';
import AssetReviewEditor from './asset-review-editor';
import { AssetType, ReviewedAsset, ReviewedAssetStatus } from '@/types/data-asset-review';

const view: ReviewedAsset = {
  id: 'a-1', asset_fqn: 'main.sales.v_orders', asset_type: AssetType.VIEW,
  status: ReviewedAssetStatus.PENDING, updated_at: new Date().toISOString(),
};
const llmConfig = { enabled: true, endpoint: 'ep', system_prompt: null, disclaimer_text: '' };

function analysis(extra: Record<string, unknown>) {
  return {
    request_id: 'r-1', asset_id: 'a-1', model_used: 'ep', timestamp: new Date().toISOString(),
    ...extra,
  };
}

async function runAnalysis(result: Record<string, unknown>) {
  const get = vi.fn().mockResolvedValue({ data: llmConfig, error: null });
  const post = vi.fn().mockResolvedValue({ data: result, error: null });
  const api = { get, post, put: vi.fn(), delete: vi.fn() } as any;
  render(
    <MemoryRouter>
      <AssetReviewEditor requestId="r-1" asset={view} api={api} onReviewSave={vi.fn()} />
    </MemoryRouter>,
  );
  const button = await screen.findByRole('button', {
    name: i18n.t('data-asset-reviews:editor.runAiAnalysis'),
  });
  await vi.waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
}

describe('AssetReviewEditor AI analysis notices', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('pt');
    localStorage.setItem('llm_consent_state', JSON.stringify({ accepted: true }));
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, status: 200, text: async () => 'SELECT 1',
    } as Response);
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('shows a refused analysis with a localized notice, as plain text', async () => {
    await runAnalysis(analysis({
      analysis_summary: '**I cannot help with that.**',
      phase1_passed: true, render_as_markdown: false, notice_code: 'llm_analysis_refused',
    }));

    expect(
      await screen.findByText(i18n.t('data-asset-reviews:editor.aiNotices.analysisRefused')),
    ).toBeInTheDocument();
    // Plain text: the markdown markers are kept, nothing is rendered bold
    expect(screen.getByText('**I cannot help with that.**')).toBeInTheDocument();
  });

  it('shows a refused security check as a localized notice only', async () => {
    const english = 'Security check failed: the model refused to check the content';
    await runAnalysis(analysis({
      analysis_summary: english,
      phase1_passed: false, render_as_markdown: false, notice_code: 'llm_safety_check_refused',
    }));

    expect(
      await screen.findByText(i18n.t('data-asset-reviews:editor.aiNotices.safetyCheckRefused')),
    ).toBeInTheDocument();
    const badge = i18n.t('data-asset-reviews:editor.securityWarning');
    expect(screen.getByText(badge)).toBeInTheDocument();
    expect(screen.queryByText(english)).toBeNull();
  });

  it('shows no notice for a normal analysis', async () => {
    await runAnalysis(analysis({
      analysis_summary: 'No sensitive data found.',
      phase1_passed: true, render_as_markdown: true,
    }));

    expect(await screen.findByText('No sensitive data found.')).toBeInTheDocument();
    expect(
      screen.queryByText(i18n.t('data-asset-reviews:editor.aiNotices.analysisRefused')),
    ).toBeNull();
  });
});
