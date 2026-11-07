import { describe, it, expect } from 'vitest'
import { highlight, renderWikiHtml } from '@/utils/wikiRender'
import { fold, preferredLang } from '@/utils/wikiText'

/**
 * Wiki notes arrive as markdown with the builder's link markup already in it
 * (app/scripts/wiki/build_wiki.py). What the view needs from the renderer:
 * claim badges, callouts and images it can style and wire up, and nothing a
 * note could smuggle in.
 */

function dom(html: string) {
  const t = document.createElement('template')
  t.innerHTML = html
  return t.content
}

describe('renderWikiHtml', () => {
  it('turns claim badges into labelled pills and tags their list item', () => {
    const d = dom(renderWikiHtml('- `R` Rečeno je. [1]\n- `T` Iz literature. [2]\n- `x` nije značka', 'en'))
    const badges = d.querySelectorAll('code.badge')
    expect(badges).toHaveLength(2)
    expect(badges[0].classList).toContain('badge-R')
    expect(badges[0].getAttribute('title')).toBe('R · said at the workshop (talk, discussion, slide)')
    expect([...d.querySelectorAll('li')].map(li => li.dataset.b)).toEqual(['R', 'T', undefined])
  })

  it('keeps the builder\'s wiki links and their target', () => {
    const md = 'Vidi <a class="wl" href="/2026Workshop/hr/n/Rezerva" data-id="Rezerva">rezervu</a>.'
    const a = dom(renderWikiHtml(md, 'hr')).querySelector('a.wl') as HTMLAnchorElement
    expect(a.dataset.id).toBe('Rezerva')
    expect(a.getAttribute('href')).toBe('/2026Workshop/hr/n/Rezerva')
  })

  it('makes Obsidian callouts into boxes', () => {
    const d = dom(renderWikiHtml('> [!warning] Pazi\n> Tijelo opomene.', 'hr'))
    const box = d.querySelector('.callout.callout-warning')
    expect(box?.querySelector('.callout-title')?.textContent).toBe('Pazi')
    expect(box?.textContent).toContain('Tijelo opomene.')
  })

  it('fills embedded images from the note\'s assets, and drops ones it lacks', () => {
    const md = '<figure class="embed"><img data-asset="a.jpg" alt="a"></figure>\n\n'
      + '<figure class="embed"><img data-asset="b.jpg" alt="b"></figure>'
    const d = dom(renderWikiHtml(md, 'hr', { 'a.jpg': 'data:image/jpeg;base64,AAAA' }))
    const imgs = d.querySelectorAll('img')
    expect(imgs).toHaveLength(1)
    expect(imgs[0].getAttribute('src')).toBe('data:image/jpeg;base64,AAAA')
  })

  it('sanitises', () => {
    const html = renderWikiHtml('<img src=x onerror="alert(1)"><script>alert(2)</script>[x](javascript:alert(3))', 'hr')
    expect(html).not.toMatch(/onerror|<script|javascript:/)
  })

  it('opens outside links in a new tab', () => {
    const a = dom(renderWikiHtml('[DOI](https://doi.org/10.1/x)', 'hr')).querySelector('a') as HTMLAnchorElement
    expect(a.target).toBe('_blank')
    expect(a.rel).toBe('noopener noreferrer')
  })
})

describe('search helpers', () => {
  it('fold drops diacritics without moving anything', () => {
    const s = 'Đurđa ČITA šuma κ'
    expect(fold(s)).toBe('durda cita suma κ')
    expect(fold(s)).toHaveLength(s.length)
  })

  it('highlight escapes and marks matches found on the folded text', () => {
    expect(highlight('Čovjek <i>i</i> čovjek', ['covjek'], fold))
      .toBe('<mark>Čovjek</mark> &lt;i&gt;i&lt;/i&gt; <mark>čovjek</mark>')
  })

  it('preferredLang remembers the last choice', () => {
    localStorage.setItem('wiki.lang', 'en')
    expect(preferredLang()).toBe('en')
    localStorage.removeItem('wiki.lang')
  })
})
