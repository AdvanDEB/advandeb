import api from '@/utils/api'

/**
 * The workshop wiki (/api/wiki, app/backend/app/api/routes/wiki.py).
 *
 * Read-only, and already filtered to what the caller may open: hidden notes
 * are absent from the index, links, backlinks, graph and search alike.
 */

export type WikiLang = 'hr' | 'en'

export interface WikiTitle {
  hr: string
  en: string | null
}

export interface WikiIndexNote {
  id: string
  section: string
  type: string
  tags: string[]
  aliases: string[]
  title: WikiTitle
  en_status: 'ok' | 'outdated' | 'missing'
  updated: string | null
  badges: Record<string, number>
  n_links: number
}

export interface WikiIndex {
  built: string | null
  sections: string[]
  tiers: string[]
  notes: WikiIndexNote[]
}

export interface WikiNote extends WikiIndexNote {
  tier: string
  created: string | null
  md: { hr: string; en: string | null }
  out: string[]
  in: string[]
  assets: Record<string, string>
}

export interface WikiGraph {
  nodes: { id: string; section: string; degree: number }[]
  edges: [string, string][]
}

export interface WikiHit {
  id: string
  section: string
  title: WikiTitle
  snippet: string
  score: number
}

// The index and the notes do not change while a tab is open (a republished
// bundle shows up on the next page load), so each is fetched once.
let indexPromise: Promise<WikiIndex> | null = null
const notes = new Map<string, Promise<WikiNote>>()
let graphPromise: Promise<WikiGraph> | null = null

function once<T>(p: Promise<T>, forget: () => void): Promise<T> {
  return p.catch((err) => { forget(); throw err })
}

export function getWikiIndex(): Promise<WikiIndex> {
  indexPromise ??= once(
    api.get<WikiIndex>('/wiki/index').then(r => r.data),
    () => { indexPromise = null },
  )
  return indexPromise
}

export function getWikiNote(id: string): Promise<WikiNote> {
  let p = notes.get(id)
  if (!p) {
    p = once(
      // A 404 is an answer here (a stale link, or a note the reader may not
      // open); the view says so itself.
      api.get<WikiNote>(`/wiki/notes/${encodeURIComponent(id)}`, { skipErrorToast: [404] }).then(r => r.data),
      () => { notes.delete(id) },
    )
    notes.set(id, p)
  }
  return p
}

export function getWikiGraph(): Promise<WikiGraph> {
  graphPromise ??= once(
    api.get<WikiGraph>('/wiki/graph').then(r => r.data),
    () => { graphPromise = null },
  )
  return graphPromise
}

export async function searchWiki(q: string, lang: WikiLang): Promise<WikiHit[]> {
  const r = await api.get<{ results: WikiHit[] }>('/wiki/search', { params: { q, lang } })
  return r.data.results
}
