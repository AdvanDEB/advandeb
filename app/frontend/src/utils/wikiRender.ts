import { Marked } from 'marked'
import DOMPurify from 'dompurify'
import type { WikiLang } from '@/utils/wikiApi'
import { BADGES, badgeLabel } from '@/utils/wikiText'

/**
 * A wiki note's markdown → safe HTML for v-html.
 *
 * The builder has already turned Obsidian links into
 * `<a class="wl" href="/2026Workshop/…" data-id="…">`, so marked only does markdown.
 * DOMPurify runs on the result like everywhere else in the app. After that,
 * claim badges (`R`, `T` …) get their colour and tooltip, Obsidian callouts
 * (`> [!note] Title`) become boxes, and embedded images get their data URI
 * from the note's assets.
 */

const md = new Marked({ gfm: true, breaks: true })

const CALLOUT = /^\s*\[!(\w+)\][+-]?\s*([\s\S]*?)(?:<br>\n?|$)([\s\S]*)$/

export function renderWikiHtml(source: string, lang: WikiLang, assets: Record<string, string> = {}): string {
  const html = DOMPurify.sanitize(md.parse(source, { async: false }) as string, {
    ADD_ATTR: ['data-id', 'data-asset'],
  })
  const tpl = document.createElement('template')
  tpl.innerHTML = html
  const root = tpl.content

  root.querySelectorAll('code').forEach((c) => {
    const b = c.textContent?.trim() ?? ''
    if (BADGES[b] && c.parentElement?.tagName !== 'PRE') {
      c.classList.add('badge', `badge-${b}`)
      c.title = `${b} · ${badgeLabel(b, lang)}`
      c.dataset.b = b
      const li = c.parentElement
      if (li?.tagName === 'LI' && li.firstElementChild === c) li.dataset.b = b
    }
  })

  root.querySelectorAll('blockquote').forEach((q) => {
    const p = q.firstElementChild
    if (!p || p.tagName !== 'P') return
    const m = p.innerHTML.match(CALLOUT)
    if (!m) return
    const box = document.createElement('div')
    box.className = `callout callout-${m[1].toLowerCase()}`
    const head = document.createElement('div')
    head.className = 'callout-title'
    head.innerHTML = m[2] || m[1]
    box.appendChild(head)
    if (m[3].trim()) {
      const rest = document.createElement('p')
      rest.innerHTML = m[3]
      box.appendChild(rest)
    }
    Array.from(q.children).slice(1).forEach(ch => box.appendChild(ch))
    q.replaceWith(box)
  })

  root.querySelectorAll<HTMLImageElement>('img[data-asset]').forEach((img) => {
    const uri = assets[img.dataset.asset ?? '']
    if (uri?.startsWith('data:image/')) img.src = uri
    else img.closest('figure')?.remove()
  })

  root.querySelectorAll<HTMLAnchorElement>('a[href^="http"]').forEach((a) => {
    a.target = '_blank'
    a.rel = 'noopener noreferrer'
  })

  return tpl.innerHTML
}

/** Escape, then mark every occurrence of the (folded) terms in a plain-text snippet. */
export function highlight(text: string, terms: string[], foldFn: (s: string) => string): string {
  const esc = (s: string) => s.replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch] as string))
  const folded = foldFn(text)
  const marks: [number, number][] = []
  for (const t of terms.filter(Boolean)) {
    let i = folded.indexOf(t)
    while (i !== -1) {
      marks.push([i, i + t.length])
      i = folded.indexOf(t, i + t.length)
    }
  }
  marks.sort((a, b) => a[0] - b[0])
  let out = ''
  let pos = 0
  for (const [a, b] of marks) {
    if (a < pos) continue
    out += esc(text.slice(pos, a)) + '<mark>' + esc(text.slice(a, b)) + '</mark>'
    pos = b
  }
  return out + esc(text.slice(pos))
}
