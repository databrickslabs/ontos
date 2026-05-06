import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGet = vi.fn()
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: mockGet,
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  }),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) => {
      if (options && typeof options === 'object' && 'defaultValue' in options) {
        return options.defaultValue as string
      }
      return key
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

import ConceptRelationsPanel from './concept-relations-panel'

const sampleNeighbors = [
  // Outgoing -- should appear
  {
    direction: 'outgoing',
    predicate: 'http://www.w3.org/2000/01/rdf-schema#subClassOf',
    display: 'http://example.org/onto#WeatherObservation',
    displayType: 'resource',
    stepIri: 'http://example.org/onto#WeatherObservation',
    stepIsResource: true,
  },
  {
    direction: 'outgoing',
    predicate: 'http://www.w3.org/2002/07/owl#equivalentClass',
    display: 'http://other.org/onto#Measurement',
    displayType: 'resource',
    stepIri: 'http://other.org/onto#Measurement',
    stepIsResource: true,
  },
  // Incoming -- should appear
  {
    direction: 'incoming',
    predicate: 'http://www.w3.org/2000/01/rdf-schema#subClassOf',
    display: 'http://example.org/onto#TemperatureMeasurement',
    displayType: 'resource',
    stepIri: 'http://example.org/onto#TemperatureMeasurement',
    stepIsResource: true,
  },
  // Hidden noise predicates
  {
    direction: 'outgoing',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    display: 'http://www.w3.org/2002/07/owl#Class',
    displayType: 'resource',
    stepIri: 'http://www.w3.org/2002/07/owl#Class',
    stepIsResource: true,
  },
  {
    direction: 'outgoing',
    predicate: 'http://www.w3.org/2000/01/rdf-schema#label',
    display: 'Atmospheric Measurement',
    displayType: 'literal',
    stepIri: null,
    stepIsResource: false,
  },
  // Predicate-direction items: also dropped to avoid double-counting
  {
    direction: 'predicate',
    predicate: 'http://example.org/onto#AtmosphericMeasurement',
    display: 'http://example.org/onto#someSubject',
    displayType: 'resource',
    stepIri: 'http://example.org/onto#someSubject',
    stepIsResource: true,
  },
]

describe('ConceptRelationsPanel', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockResolvedValue({ data: sampleNeighbors })
  })

  const renderPanel = (overrides: Partial<React.ComponentProps<typeof ConceptRelationsPanel>> = {}) => {
    const props: React.ComponentProps<typeof ConceptRelationsPanel> = {
      conceptIri: 'http://example.org/onto#AtmosphericMeasurement',
      onNavigate: vi.fn(),
      ...overrides,
    }
    return { ...render(<ConceptRelationsPanel {...props} />), props }
  }

  it('renders only meaningful relations (drops rdf:type, label, predicate-direction)', async () => {
    renderPanel()

    await waitFor(() => {
      expect(screen.getByTestId('concept-relations-list')).toBeInTheDocument()
    })

    // Three meaningful relations: 2 outgoing + 1 incoming
    expect(
      screen.getByTestId('relation-outgoing-subClassOf-WeatherObservation'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('relation-outgoing-equivalentClass-Measurement'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('relation-incoming-subClassOf-TemperatureMeasurement'),
    ).toBeInTheDocument()

    // Filtered ones are absent
    expect(screen.queryByText(/owl#Class/)).not.toBeInTheDocument()
    expect(screen.queryByText('Atmospheric Measurement')).not.toBeInTheDocument()
  })

  it('shows total count and outgoing/incoming breakdown in the header', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('concept-relations-list')).toBeInTheDocument()
    })
    // Total is 3 (the visible ones); outgoing 2, incoming 1
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('navigates when clicking on a resource target', async () => {
    const onNavigate = vi.fn()
    renderPanel({ onNavigate })
    await waitFor(() => {
      expect(
        screen.getByTestId('relation-outgoing-equivalentClass-Measurement'),
      ).toBeInTheDocument()
    })
    const user = userEvent.setup()
    const row = screen.getByTestId('relation-outgoing-equivalentClass-Measurement')
    const link = row.querySelector('button')!
    await user.click(link)
    expect(onNavigate).toHaveBeenCalledWith('http://other.org/onto#Measurement')
  })

  it('renders an empty state when no neighbours exist', async () => {
    mockGet.mockResolvedValue({ data: [] })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/No relations found\./i)).toBeInTheDocument()
    })
  })
})
