/**
 * How a passage's source is shown to an expert.
 *
 * The citation is resolved on the server when the item is served; this only
 * formats it. An unresolved one says so in plain words — an expert told
 * "Kooy93.pdf" as if that were a reference would be misled about how much
 * the system knows.
 */
import type { PassageCitation } from '@/types/elicitation.generated'

export interface CitationView {
  /** Authors and year, e.g. "Tolla, Kooijman & Poggiale (2007)". */
  lead: string
  title: string | null
  /** Journal or publisher, then pages when known. */
  venue: string | null
  doiUrl: string | null
  doi: string | null
  /** Set only when the source could not be identified. */
  unresolved: string | null
}

const MAX_AUTHORS = 6

export function authorList(authors: string[]): string {
  const names = authors.map((a) => a.trim()).filter(Boolean)
  if (!names.length) return ''
  if (names.length > MAX_AUTHORS) return `${names.slice(0, MAX_AUTHORS).join(', ')} et al.`
  if (names.length === 1) return names[0]
  return `${names.slice(0, -1).join(', ')} & ${names[names.length - 1]}`
}

export function doiUrl(doi: string | null | undefined): string | null {
  return doi ? `https://doi.org/${doi}` : null
}

export function citationView(c: PassageCitation | null | undefined): CitationView {
  if (!c || c.status === 'unresolved' || !c.title) {
    const file = c?.file_name
    const where = c?.library_id ? ` (DEB library #${c.library_id})` : ''
    return {
      lead: '',
      title: null,
      venue: null,
      doi: c?.doi ?? null,
      doiUrl: doiUrl(c?.doi),
      unresolved: file
        ? `Source not yet identified — file ${file}${where}`
        : 'Source not yet identified',
    }
  }
  const authors = authorList(c.authors)
  const year = c.year ? `(${c.year})` : '(n.d.)'
  const venue = [c.journal, c.pages ? `pp. ${c.pages}` : null].filter(Boolean).join(', ')
  return {
    lead: authors ? `${authors} ${year}` : year,
    title: c.title,
    venue: venue || null,
    doi: c.doi,
    doiUrl: doiUrl(c.doi),
    unresolved: null,
  }
}

/** One line of plain text, for titles and screen-reader labels. */
export function citationText(c: PassageCitation | null | undefined): string {
  const v = citationView(c)
  if (v.unresolved) return v.unresolved
  return [v.lead, v.title, v.venue, v.doi ? `doi:${v.doi}` : null]
    .filter(Boolean).join('. ')
}
