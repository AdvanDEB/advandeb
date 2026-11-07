import type { WikiLang, WikiTitle } from '@/utils/wikiApi'

/** Interface text, claim badges and labels for the workshop wiki, in both languages. */

export const WIKI_LANGS: WikiLang[] = ['hr', 'en']

export const UI = {
  hr: {
    title: 'Wiki radionice',
    sub: 'Radionica AdvanDEB · 2.–5. 11. 2026.',
    search: 'Pretraži wiki…',
    contents: 'Sadržaj',
    close: 'Zatvori',
    home: 'Početna', hub: 'Sažetak radionice', graph: 'Graf znanja', questions: 'Otvorena pitanja',
    out: 'Povezuje na', in: 'Poveznice prema ovoj bilješci', local: 'Susjedstvo', claims: 'Tvrdnje po vrsti',
    filterHint: 'Klik na značku ističe samo te tvrdnje.', none: 'nema', details: 'Podaci',
    created: 'stvoreno', updated: 'ažurirano', aliases: 'drugi nazivi',
    enMissing: '', enOutdated: '', hrOnly: 'HR',
    results: (n: number) => `${n} rezultata`, noResults: 'Nema rezultata.',
    tag: 'Oznaka', notesIn: (n: number) => `${n} bilješki`,
    notFound: 'Ova bilješka ne postoji ili za nju nemate pristup.',
    unavailable: 'Wiki još nije objavljen na ovom poslužitelju.',
    loading: 'Učitavanje…',
    graphHint: 'Kotačić za zum, povlačenje za pomak, klik otvara bilješku. Veličina čvora je broj veza.',
    showLabels: 'Svi nazivi',
    statNotes: 'bilješki', statLinks: 'veza', statClaims: 'označenih tvrdnji', statSources: 'provjerenih izvora',
    claimsTitle: 'Odakle dolaze tvrdnje',
    claimsRule: 'Svaka tvrdnja nosi značku izvora. R i D znače samo da je nešto rečeno ili zapisano, ne da je točno; kad se R razilazi s propozicijom, simulacijom ili literaturom, obje tvrdnje ostaju uz napomenu „Napetost“.',
    lede: 'Rezultati radionice AdvanDEB o teoriji Dynamic Energy Budget i transportnom DEB-u: pojmovi, modeli, organizmi, provjerena literatura i program po danima, međusobno povezani.',
    internalBanner: 'Sažetak internog projektnog dokumenta. Njegove tvrdnje nose oznaku D: zapisano, ne nužno točno.',
    built: 'Stanje od',
    language: 'Jezik',
  },
  en: {
    title: 'Workshop wiki',
    sub: 'AdvanDEB workshop · 2–5 Nov 2026',
    search: 'Search the wiki…',
    contents: 'Contents',
    close: 'Close',
    home: 'Home', hub: 'Workshop summary', graph: 'Knowledge graph', questions: 'Open questions',
    out: 'Links to', in: 'Linked from', local: 'Neighbourhood', claims: 'Claims by type',
    filterHint: 'Click a badge to highlight only those claims.', none: 'none', details: 'Details',
    created: 'created', updated: 'updated', aliases: 'aliases',
    enMissing: 'Not translated yet: showing the Croatian original.',
    enOutdated: 'The Croatian original changed after this translation was made; the English text may be out of date.',
    hrOnly: 'HR',
    results: (n: number) => `${n} results`, noResults: 'No results.',
    tag: 'Tag', notesIn: (n: number) => `${n} notes`,
    notFound: 'This note does not exist, or you do not have access to it.',
    unavailable: 'The wiki has not been published on this server yet.',
    loading: 'Loading…',
    graphHint: 'Scroll to zoom, drag to pan, click to open. Node size is the number of links.',
    showLabels: 'All labels',
    statNotes: 'notes', statLinks: 'links', statClaims: 'tagged claims', statSources: 'verified sources',
    claimsTitle: 'Where the claims come from',
    claimsRule: 'Every claim carries a source badge. R and D only mean that something was said or written, not that it is true; where R disagrees with a proposition, a simulation or the literature, both claims stay, marked "Tension".',
    lede: 'Results of the AdvanDEB workshop on Dynamic Energy Budget theory and transport DEB: concepts, models, organisms, verified literature and the programme by day, all cross-linked.',
    internalBanner: 'Summary of an internal project document. Its claims carry badge D: written down, not necessarily true.',
    built: 'As of',
    language: 'Language',
  },
} as const

export const SECTIONS: Record<string, [string, string]> = {
  concepts: ['Pojmovi', 'Concepts'],
  models: ['Modeli', 'Models'],
  organisms: ['Organizmi', 'Organisms'],
  project: ['Projekt', 'Project'],
  literature: ['Literatura', 'Literature'],
  journal: ['Program po danima', 'Programme by day'],
  slides: ['Prezentacije', 'Slides & talks'],
  drive: ['Projektni dokumenti', 'Project documents'],
  maps: ['Mape', 'Maps'],
  questions: ['Pitanja', 'Questions'],
  home: ['Početna', 'Home'],
  hub: ['Sažetak', 'Summary'],
  other: ['Ostalo', 'Other'],
}

export const SECTION_COLOR: Record<string, string> = {
  concepts: '#2563eb', models: '#7c3aed', organisms: '#15803d', project: '#b45309',
  literature: '#0f766e', journal: '#64748b', slides: '#db2777', drive: '#a16207',
  maps: '#111827', questions: '#be123c', home: '#111827', hub: '#111827', other: '#9ca3af',
}

export const BADGES: Record<string, [string, string]> = {
  R: ['rečeno na radionici (predavanje, rasprava, slajd)', 'said at the workshop (talk, discussion, slide)'],
  D: ['projektni dokument', 'project document'],
  T: ['provjerena literatura (DOI u Crossrefu/PubMedu)', 'verified literature (DOI checked in Crossref/PubMed)'],
  E: ['empirijski podatak s izvorom', 'empirical measurement with a source'],
  P: ['propozicija: slijedi iz modela', 'proposition: follows from the model'],
  S: ['rezultat simulacije', 'simulation result'],
  H: ['hipoteza: otvoreno i provjerljivo', 'hypothesis: open and testable'],
  I: ['tumačenje bez provjerenog izvora', 'interpretation without a verified source'],
}
export const BADGE_ORDER = 'RDTEPSHI'.split('')

export const TAGS: Record<string, [string, string]> = {
  'tema/homeostaza': ['Homeostaza', 'Homeostasis'],
  'tema/rezerva-struktura': ['Rezerva i struktura', 'Reserve & structure'],
  'tema/kdeb': ['κ-DEB', 'κ-DEB'],
  'tema/tdeb': ['tDEB', 'tDEB'],
  'tema/alpha': ['α', 'α'],
  'tema/reprodukcija': ['Reprodukcija', 'Reproduction'],
  'tema/rast': ['Rast', 'Growth'],
  'tema/energetika': ['Energetika', 'Energetics'],
  'tema/skaliranje': ['Skaliranje', 'Scaling'],
  'tema/fiziologija': ['Fiziologija', 'Physiology'],
  'tema/metodologija': ['Metodologija', 'Methodology'],
  'tema/projekt': ['Projekt', 'Project'],
}

export const TYPES_EN: Record<string, string> = {
  pojam: 'concept', model: 'model', organizam: 'organism', projekt: 'project', izvor: 'source',
  pitanja: 'questions', moc: 'map', dnevnik: 'day', preusmjeravanje: 'redirect',
  dokument: 'document', pregled: 'overview', prezentacija: 'presentation', 'bilješka': 'note',
}

const pick = <T>(pair: [T, T], lang: WikiLang): T => (lang === 'en' ? pair[1] : pair[0])

export const sectionLabel = (s: string, lang: WikiLang) => pick(SECTIONS[s] ?? [s, s], lang)
export const badgeLabel = (b: string, lang: WikiLang) => pick(BADGES[b] ?? [b, b], lang)
export const tagLabel = (t: string, lang: WikiLang) => pick(TAGS[t] ?? [t, t], lang)
export const typeLabel = (t: string, lang: WikiLang) => (lang === 'en' ? TYPES_EN[t] ?? t : t)
export const titleIn = (t: WikiTitle, lang: WikiLang) => (lang === 'en' && t.en) || t.hr

/**
 * Lower case without diacritics, one UTF-16 unit per unit (as the backend's
 * fold), so a match position in the folded text is the same in the original.
 */
export function fold(s: string): string {
  let out = ''
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch === 'đ' || ch === 'Đ') { out += 'd'; continue }
    out += ch.normalize('NFD')[0].toLowerCase()[0] ?? ch
  }
  return out
}

const LANG_KEY = 'wiki.lang'

/** Last choice, else the browser's language: Croatian for hr*, English otherwise. */
export function preferredLang(): WikiLang {
  try {
    const saved = localStorage.getItem(LANG_KEY)
    if (saved === 'hr' || saved === 'en') return saved
  } catch { /* storage blocked: fall through */ }
  return typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('hr') ? 'hr' : 'en'
}

export function rememberLang(lang: WikiLang): void {
  try { localStorage.setItem(LANG_KEY, lang) } catch { /* not worth failing over */ }
}
