import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: string | { defaultValue?: string }) =>
      typeof opts === 'string' ? opts : opts?.defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

vi.mock('@/components/term-mapping/suggestion-review', () => ({
  default: () => <div data-testid="shared-reviewer" />,
}))

import ReviewSuggestionsDialog, { type PlaceholderSuggestion } from './review-suggestions-dialog'

const placeholders: PlaceholderSuggestion[] = [
  { id: 's1', concept: 'Revenue', target: 'main.sales.orders', reason: 'name match', confidence: 'high' },
]

describe('ReviewSuggestionsDialog', () => {
  it('has no info tooltip and no developer-facing wording', () => {
    render(
      <ReviewSuggestionsDialog
        open
        onOpenChange={vi.fn()}
        schemeName="Finance"
        placeholders={placeholders}
      />,
    )
    expect(screen.getByText('Review suggested matches')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'about' })).not.toBeInTheDocument()
    expect(screen.queryByText(/shared Review Board surface/)).not.toBeInTheDocument()
    expect(screen.queryByText(/read-model/)).not.toBeInTheDocument()
    expect(screen.queryByText(/shared reviewer/)).not.toBeInTheDocument()
  })

  it('labels sample rows with a plain user-facing note', () => {
    render(
      <ReviewSuggestionsDialog
        open
        onOpenChange={vi.fn()}
        schemeName="Finance"
        placeholders={placeholders}
      />,
    )
    expect(screen.getByText('Sample matches shown for illustration.')).toBeInTheDocument()
    expect(screen.getByText('Revenue')).toBeInTheDocument()
  })

  it('omits the sample note when live suggestions are shown', () => {
    render(
      <ReviewSuggestionsDialog
        open
        onOpenChange={vi.fn()}
        schemeName="Finance"
        liveSuggestions={[
          { id: 'l1', runId: 'r1', concept: 'Customer', target: 'main.crm.customers', reason: 'semantic', confidence: 0.9 },
        ]}
        onAcceptAndApplyAll={vi.fn()}
      />,
    )
    expect(screen.getByText('Customer')).toBeInTheDocument()
    expect(screen.queryByText('Sample matches shown for illustration.')).not.toBeInTheDocument()
  })
})
