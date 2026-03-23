/**
 * Tests for DataContractWizardDialog schema inference functionality
 */

import { screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/utils'
import DataContractWizardDialog from './data-contract-wizard-dialog'
import type { InferredSchemaObject } from './infer-from-asset-dialog'

// Mock the hooks and components
vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({
    domains: [
      { id: 'domain1', name: 'Test Domain 1' },
      { id: 'domain2', name: 'Test Domain 2' }
    ],
    loading: false,
    refetch: vi.fn()
  })
}))

// Create a shared mockToast function
const mockToast = vi.fn()

vi.mock('@/hooks/use-toast', () => ({
  default: () => ({
    toast: mockToast
  }),
  useToast: () => ({
    toast: mockToast
  })
}))

// Track schemas to pass to onInfer per-test
let currentMockSchemas: InferredSchemaObject[] = []

vi.mock('./infer-from-asset-dialog', () => ({
  default: ({ isOpen, onInfer }: { isOpen: boolean; onOpenChange: (open: boolean) => void; onInfer: (schemas: InferredSchemaObject[]) => void }) => {
    if (!isOpen) return null
    return (
      <div data-testid="infer-from-asset-dialog">
        <button
          onClick={() => onInfer(currentMockSchemas)}
          data-testid="select-dataset"
        >
          Select Asset
        </button>
      </div>
    )
  }
}))

vi.mock('@/components/business-concepts/business-concepts-display', () => ({
  default: () => <div data-testid="business-concepts-display" />
}))

const storageLocation = 's3://databricks-e2demofieldengwest/b169b504-4c54-49f2-bc3a-adf4b128f36d/tables/c39d273a-d87b-4a62-8792-0193f142fca7'

const sampleInferredSchemas: InferredSchemaObject[] = [
  {
    name: 'table_a',
    physicalName: storageLocation,
    description: 'The table contains records of various entries identified by a unique ID.',
    physicalType: 'DELTA',
    properties: [
      {
        name: 'id',
        physicalType: 'int',
        logicalType: 'integer',
        required: true,
        description: 'A unique identifier for each entry in the table, allowing for easy tracking and referencing of specific records.',
        partitioned: false,
      },
      {
        name: 'info',
        physicalType: 'string',
        logicalType: 'string',
        required: false,
        description: 'Contains additional details related to each entry, which can provide context or further information necessary for analysis or reporting.',
        partitioned: false,
      }
    ]
  }
]

describe('DataContractWizardDialog Schema Inference', () => {
  const mockOnOpenChange = vi.fn()
  const mockOnSubmit = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    currentMockSchemas = sampleInferredSchemas
  })

  it('should render the wizard dialog', () => {
    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
      />
    )

    expect(screen.getByText(/Data Contract Wizard/i)).toBeInTheDocument()
    expect(screen.getByText('Build a contract incrementally according to ODCS v3.0.2')).toBeInTheDocument()
  })

  it('should handle schema inference from UC dataset', async () => {
    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
        initial={{ name: 'Test Contract', version: '1.0.0', status: 'draft' }}
      />
    )

    // Navigate to step 2 (Schema)
    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    // Wait for step 2 to appear
    await waitFor(() => {
      expect(screen.getByText(/Infer from Asset/i)).toBeInTheDocument()
    }, { timeout: 5000 })

    // Click "Infer from Asset" button to open the dialog
    const inferButton = screen.getByText(/Infer from Asset/i)
    fireEvent.click(inferButton)

    // Click the asset selection in the mocked dialog
    const selectDatasetButton = screen.getByTestId('select-dataset')
    fireEvent.click(selectDatasetButton)

    // Wait for schema to be populated
    await waitFor(() => {
      expect(screen.getByDisplayValue('table_a')).toBeInTheDocument()
    })

    // Verify physical name is set to storage location
    expect(screen.getByDisplayValue(storageLocation)).toBeInTheDocument()
  })

  it('should properly set physical and logical types from UC metadata', async () => {
    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
        initial={{ name: 'Test Contract', version: '1.0.0', status: 'draft' }}
      />
    )

    // Navigate to step 2 and trigger inference
    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    const inferButton = screen.getByText(/Infer from Asset/i)
    fireEvent.click(inferButton)

    const selectDatasetButton = screen.getByTestId('select-dataset')
    fireEvent.click(selectDatasetButton)

    // Wait for schema to be populated
    await waitFor(() => {
      expect(screen.getByDisplayValue('id')).toBeInTheDocument()
    })

    // Check that physical types are populated
    const physicalTypeInputs = screen.getAllByPlaceholderText(/VARCHAR|BIGINT/i)
    expect(physicalTypeInputs.length).toBeGreaterThan(0)

    // Check that logical type dropdowns show ODCS types
    const logicalTypeSelects = screen.getAllByText('integer')
    expect(logicalTypeSelects.length).toBeGreaterThan(0)
  })

  it('should populate column descriptions from UC comments', async () => {
    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
        initial={{ name: 'Test Contract', version: '1.0.0', status: 'draft' }}
      />
    )

    // Navigate to step 2 and trigger inference
    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    const inferButton = screen.getByText(/Infer from Asset/i)
    fireEvent.click(inferButton)

    const selectDatasetButton = screen.getByTestId('select-dataset')
    fireEvent.click(selectDatasetButton)

    // Wait for schema to be populated - use partial match since descriptions are long
    await waitFor(() => {
      expect(screen.getByDisplayValue(/A unique identifier for each entry/i)).toBeInTheDocument()
    })

    // Verify second column description
    expect(screen.getByDisplayValue(/Contains additional details related to each entry/i)).toBeInTheDocument()
  })

  it('should handle partition information correctly', async () => {
    currentMockSchemas = [
      {
        ...sampleInferredSchemas[0],
        properties: [
          ...sampleInferredSchemas[0].properties,
          {
            name: 'partition_date',
            physicalType: 'date',
            logicalType: 'date',
            required: true,
            description: 'Partition column',
            partitioned: true,
          }
        ]
      }
    ]

    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
        initial={{ name: 'Test Contract', version: '1.0.0', status: 'draft' }}
      />
    )

    // Trigger inference
    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    const inferButton = screen.getByText(/Infer from Asset/i)
    fireEvent.click(inferButton)

    const selectDatasetButton = screen.getByTestId('select-dataset')
    fireEvent.click(selectDatasetButton)

    // Wait for schema to be populated
    await waitFor(() => {
      expect(screen.getByDisplayValue('partition_date')).toBeInTheDocument()
    })
  })

  it('should handle empty schema gracefully', async () => {
    currentMockSchemas = [
      {
        name: 'empty_table',
        physicalName: '',
        description: '',
        physicalType: '',
        properties: []
      }
    ]

    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
        initial={{ name: 'Test Contract', version: '1.0.0', status: 'draft' }}
      />
    )

    // Trigger inference
    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    const inferButton = screen.getByText(/Infer from Asset/i)
    fireEvent.click(inferButton)

    const selectDatasetButton = screen.getByTestId('select-dataset')
    fireEvent.click(selectDatasetButton)

    // Wait for success toast with 0 columns
    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Schema inferred successfully' })
      )
    })
  })

  it('should handle multiple schemas inference', async () => {
    currentMockSchemas = [
      { ...sampleInferredSchemas[0] },
      {
        name: 'table_b',
        physicalName: '',
        description: '',
        physicalType: 'DELTA',
        properties: [
          { name: 'col1', physicalType: 'string', logicalType: 'string', required: false, description: '', partitioned: false }
        ]
      }
    ]

    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
        initial={{ name: 'Test Contract', version: '1.0.0', status: 'draft' }}
      />
    )

    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    const inferButton = screen.getByText(/Infer from Asset/i)
    fireEvent.click(inferButton)

    const selectDatasetButton = screen.getByTestId('select-dataset')
    fireEvent.click(selectDatasetButton)

    // Wait for success toast
    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith({
        title: 'Schema inferred successfully',
        description: 'Added 2 schemas with 3 columns',
      })
    })
  })

  it('should show success message after inference', async () => {
    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
        initial={{ name: 'Test Contract', version: '1.0.0', status: 'draft' }}
      />
    )

    // Trigger inference
    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    const inferButton = screen.getByText(/Infer from Asset/i)
    fireEvent.click(inferButton)

    const selectDatasetButton = screen.getByTestId('select-dataset')
    fireEvent.click(selectDatasetButton)

    // Wait for success message
    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith({
        title: 'Schema inferred successfully',
        description: 'Added 1 schema with 2 columns',
      })
    })
  })

  it('should map various UC types to correct ODCS logical types', async () => {
    currentMockSchemas = [
      {
        name: 'varied_types_table',
        physicalName: '',
        description: '',
        physicalType: 'DELTA',
        properties: [
          { name: 'int_col', physicalType: 'int', logicalType: 'integer', required: false, description: '', partitioned: false },
          { name: 'bigint_col', physicalType: 'bigint', logicalType: 'integer', required: false, description: '', partitioned: false },
          { name: 'string_col', physicalType: 'string', logicalType: 'string', required: false, description: '', partitioned: false },
          { name: 'double_col', physicalType: 'double', logicalType: 'number', required: false, description: '', partitioned: false },
          { name: 'date_col', physicalType: 'date', logicalType: 'date', required: false, description: '', partitioned: false },
          { name: 'bool_col', physicalType: 'boolean', logicalType: 'boolean', required: false, description: '', partitioned: false },
          { name: 'array_col', physicalType: 'array<string>', logicalType: 'array', required: false, description: '', partitioned: false },
        ]
      }
    ]

    renderWithProviders(
      <DataContractWizardDialog
        isOpen={true}
        onOpenChange={mockOnOpenChange}
        onSubmit={mockOnSubmit}
        initial={{ name: 'Test Contract', version: '1.0.0', status: 'draft' }}
      />
    )

    // Trigger inference
    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    const inferButton = screen.getByText(/Infer from Asset/i)
    fireEvent.click(inferButton)

    const selectDatasetButton = screen.getByTestId('select-dataset')
    fireEvent.click(selectDatasetButton)

    // Wait for schema to be populated
    await waitFor(() => {
      expect(screen.getByDisplayValue('int_col')).toBeInTheDocument()
    })
  })
})
