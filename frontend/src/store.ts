import { Protein } from './api'
import { Kind } from './components/KindStep'
import { ResultData } from './components/Results'

export type SavedProject = {
  id: string
  name: string
  kind: Kind | 'novo'
  createdAt: number
  protein: Omit<Protein, 'sequence'> | null
  summary: string
  result: ResultData
}

const KEY = 'tdl.projects'
const MAX = 50

export const KIND_LABEL: Record<string, string> = { protein: 'Protein', mrna: 'mRNA', plantdna: 'Plant DNA', novo: 'Protein' }

export function loadProjects(): SavedProject[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(raw) ? raw : []
  } catch {
    return []
  }
}

export function persist(list: SavedProject[]): SavedProject[] {
  const trimmed = list.slice(0, MAX)
  try {
    localStorage.setItem(KEY, JSON.stringify(trimmed))
  } catch {
    /* storage full or blocked: keep working in memory */
  }
  return trimmed
}

export const newId = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : String(Date.now()))
