import fs from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'
import router from '@/router'

/**
 * index.html, robots.txt and sitemap.xml are static, so nothing kept them in
 * step with the app (F-015, F-018): og:image and twitter:image were relative
 * (scrapers need absolute URLs), og:url differed from the canonical by a
 * slash, and robots.txt disallowed a /scenarios that does not exist while
 * leaving /admin, /settings, /elicitation and /documentation open.
 */

// vitest runs from app/frontend (jsdom here: the router needs a window).
const root = process.cwd()
const read = (f: string) => fs.readFileSync(path.join(root, f), 'utf8')
const meta = (html: string, attr: string, name: string) =>
  html.match(new RegExp(`<meta ${attr}="${name}" content="([^"]*)"`))?.[1]

describe('index.html social metadata', () => {
  const html = read('index.html')
  const canonical = html.match(/<link rel="canonical" href="([^"]*)"/)?.[1]

  it('uses absolute image URLs', () => {
    expect(meta(html, 'property', 'og:image')).toMatch(/^https:\/\/advandeb\.com\//)
    expect(meta(html, 'name', 'twitter:image')).toMatch(/^https:\/\/advandeb\.com\//)
  })

  it('og:url is the canonical URL', () => {
    expect(canonical).toBe('https://advandeb.com/')
    expect(meta(html, 'property', 'og:url')).toBe(canonical)
  })
})

describe('robots.txt', () => {
  const lines = read('public/robots.txt').split('\n').map(l => l.trim())
  const disallowed = lines.filter(l => l.startsWith('Disallow:')).map(l => l.slice(9).trim())
  const allowed = lines.filter(l => l.startsWith('Allow:')).map(l => l.slice(6).trim())
  const blocked = (p: string) => {
    const longest = (list: string[]) => Math.max(-1, ...list.filter(r => p.startsWith(r)).map(r => r.length))
    return longest(disallowed) > longest(allowed)
  }
  const routes = router.getRoutes().filter(r => !r.path.includes(':pathMatch'))

  it('keeps crawlers off every signed-in route', () => {
    const open = routes.filter(r => r.meta.requiresAuth && !blocked(r.path)).map(r => r.path)
    expect(open).toEqual([])
  })

  it('leaves the public pages crawlable', () => {
    expect(blocked('/')).toBe(false)
    expect(blocked('/elicitation/join')).toBe(false)
  })

  it('names only prefixes that exist', () => {
    const exists = (prefix: string) =>
      prefix === '/api/' || routes.some(r => r.path === prefix || r.path.startsWith(prefix + '/'))
    expect(disallowed.filter(p => !exists(p))).toEqual([])
  })
})
