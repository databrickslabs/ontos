import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { OntologyConcept } from '@/types/ontology'

// ---- Mocks ----------------------------------------------------------------

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

// Stub reactflow to surface node/edge inputs for assertion without exercising
// the real renderer (which has heavy DOM/measurement requirements in jsdom).
vi.mock('reactflow', () => {
  const Position = { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' }
  const MarkerType = { ArrowClosed: 'arrowclosed' }
  const Handle = (_props: any) => null
  const ReactFlowProvider = ({ children }: any) => children
  const useReactFlow = () => ({ fitView: vi.fn() })
  const ReactFlow = ({ nodes = [], edges = [], nodeTypes = {} }: any) => {
    const renderNode = (n: any) => {
      const NodeComp = nodeTypes[n.type]
      return (
        <div key={n.id} data-testid={`rf-node-${n.id}`}>
          {NodeComp ? <NodeComp data={n.data} /> : null}
        </div>
      )
    }
    return (
      <div data-testid="rf-canvas">
        <div data-testid="rf-nodes" data-count={nodes.length}>
          {nodes.map(renderNode)}
        </div>
        <div data-testid="rf-edges" data-count={edges.length}>
          {edges.map((e: any) => (
            <div key={e.id} data-testid={`rf-edge-${e.id}`} />
          ))}
        </div>
      </div>
    )
  }
  return {
    __esModule: true,
    default: ReactFlow,
    Position,
    MarkerType,
    Handle,
    ReactFlowProvider,
    useReactFlow,
  }
})

// Re-import after mocks are registered
import ConceptNeighborhoodGraph from './concept-neighborhood-graph'

// ---- Fixtures -------------------------------------------------------------

const concept: OntologyConcept = {
  iri: 'https://example.org/onto#Customer',
  label: 'Customer',
  concept_type: 'class',
  parent_concepts: [],
  child_concepts: [],
  properties: [],
  tagged_assets: [],
  synonyms: [],
  examples: [],
}

const neighborsResponse = [
  // 1 parent via subClassOf
  {
    direction: 'outgoing',
    predicate: 'http://www.w3.org/2000/01/rdf-schema#subClassOf',
    display: 'https://example.org/onto#Party',
    displayType: 'resource',
    stepIri: 'https://example.org/onto#Party',
    stepIsResource: true,
  },
  // 3 children via incoming subClassOf
  {
    direction: 'incoming',
    predicate: 'http://www.w3.org/2000/01/rdf-schema#subClassOf',
    display: 'https://example.org/onto#PremiumCustomer',
    displayType: 'resource',
    stepIri: 'https://example.org/onto#PremiumCustomer',
    stepIsResource: true,
  },
  {
    direction: 'incoming',
    predicate: 'http://www.w3.org/2000/01/rdf-schema#subClassOf',
    display: 'https://example.org/onto#RetailCustomer',
    displayType: 'resource',
    stepIri: 'https://example.org/onto#RetailCustomer',
    stepIsResource: true,
  },
  {
    direction: 'incoming',
    predicate: 'http://www.w3.org/2000/01/rdf-schema#subClassOf',
    display: 'https://example.org/onto#WholesaleCustomer',
    displayType: 'resource',
    stepIri: 'https://example.org/onto#WholesaleCustomer',
    stepIsResource: true,
  },
  // unrelated outgoing predicate (should be ignored)
  {
    direction: 'outgoing',
    predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    display: 'http://www.w3.org/2002/07/owl#Class',
    displayType: 'resource',
    stepIri: 'http://www.w3.org/2002/07/owl#Class',
    stepIsResource: true,
  },
]

describe('ConceptNeighborhoodGraph', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/semantic-models/neighbors')) {
        return { data: neighborsResponse }
      }
      return { data: [] }
    })
  })

  it('renders 5 nodes (1 parent + current + 3 children) and 4 edges', async () => {
    render(<ConceptNeighborhoodGraph concept={concept} onNavigate={() => {}} />)

    await waitFor(() => {
      const nodesContainer = screen.getByTestId('rf-nodes')
      expect(nodesContainer.getAttribute('data-count')).toBe('5')
    })

    const edgesContainer = screen.getByTestId('rf-edges')
    expect(edgesContainer.getAttribute('data-count')).toBe('4')

    expect(
      screen.getByTestId('rf-node-parent-https://example.org/onto#Party'),
    ).toBeInTheDocument()
    expect(screen.getByTestId('rf-node-current')).toBeInTheDocument()
    expect(
      screen.getByTestId('rf-node-child-https://example.org/onto#PremiumCustomer'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('rf-node-child-https://example.org/onto#RetailCustomer'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('rf-node-child-https://example.org/onto#WholesaleCustomer'),
    ).toBeInTheDocument()
  })

  it('fires onNavigate with the child IRI when a child node is clicked', async () => {
    const onNavigate = vi.fn()
    render(<ConceptNeighborhoodGraph concept={concept} onNavigate={onNavigate} />)

    await waitFor(() => {
      expect(
        screen.getByTestId('rf-node-child-https://example.org/onto#PremiumCustomer'),
      ).toBeInTheDocument()
    })

    const child = screen.getByText('PremiumCustomer')
    const user = userEvent.setup()
    await user.click(child)

    expect(onNavigate).toHaveBeenCalledWith('https://example.org/onto#PremiumCustomer')
  })

  it('renders empty state when there are no related concepts', async () => {
    mockGet.mockImplementation(async () => ({ data: [] }))
    render(<ConceptNeighborhoodGraph concept={concept} onNavigate={() => {}} />)
    expect(await screen.findByText('No related concepts.')).toBeInTheDocument()
    expect(screen.queryByTestId('rf-canvas')).not.toBeInTheDocument()
  })
})
