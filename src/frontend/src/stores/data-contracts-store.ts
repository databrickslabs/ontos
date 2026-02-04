import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { DataContractDraft, DataContractListItem } from '@/types/data-contract'

type State = {
  drafts: Record<string, DataContractDraft>
  lastEditedId?: string
  list: DataContractListItem[]
  setList: (items: DataContractListItem[]) => void
  upsertDraft: (id: string, draft: Partial<DataContractDraft>) => void
  removeDraft: (id: string) => void
  setLastEdited: (id?: string) => void
}

export const useDataContractsStore = create<State>()(
  persist(
    (set, _get) => ({
      drafts: {},
      list: [],
      setList: (items) => set({ list: items }),
      upsertDraft: (id, draft) =>
        set((s) => ({ drafts: { ...s.drafts, [id]: { ...(s.drafts[id] || defaultDraft()), ...draft } } })),
      removeDraft: (id) =>
        set((s) => {
          const { [id]: _, ...rest } = s.drafts
          return { drafts: rest }
        }),
      setLastEdited: (id) => set({ lastEditedId: id }),
    }),
    { name: 'ucapp-data-contracts' }
  )
)

export function defaultDraft(): DataContractDraft {
  return {
    name: '',
    version: '1.0.0',
    status: 'draft',
    owner: '',
    kind: 'DataContract',
    apiVersion: 'v3.0.1',
    contract_text: '{\n  "version": "1.0",\n  "kind": "DataContract",\n  "apiVersion": "v3.0.1"\n}',
    format: 'json',
  }
}


