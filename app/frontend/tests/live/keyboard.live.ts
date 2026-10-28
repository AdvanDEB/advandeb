// Keyboard-only use of the public pages, signed out: Tab order, whether focus
// is visible at each stop, what Enter does on links, where focus lands after a
// client-side route change, and the in-page "Learn more" anchor. Nothing is
// submitted: on /login and the enrolment form only Tab is pressed.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect, shot, type Evidence } from './guard'
import type { Page } from '@playwright/test'

test.use({ signedIn: false })

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

function record(project: string, name: string, data: unknown) {
  const dir = path.join(OUT, 'data', project)
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, `${name}.json`), JSON.stringify(data, null, 2))
}

/** Press Tab up to `max` times and describe each focused element. */
async function tabWalk(page: Page, max: number) {
  const stops: Record<string, unknown>[] = []
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab')
    const s = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null
      if (!el || el === document.body) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0
      const shadow = cs.boxShadow !== 'none'
      return {
        tag: el.tagName.toLowerCase(),
        label: (el.getAttribute('aria-label') || el.innerText || (el as HTMLInputElement).labels?.[0]?.innerText || (el as HTMLInputElement).placeholder || el.id || '').trim().replace(/\s+/g, ' ').slice(0, 50),
        pos: `${Math.round(r.top + scrollY)},${Math.round(r.left)}`,
        href: el.getAttribute('href'),
        focusVisible: el.matches(':focus-visible'),
        indicator: outline ? `outline ${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}` : shadow ? `box-shadow ${cs.boxShadow}` : `none (border ${cs.borderTopWidth} ${cs.borderTopColor})`,
        inViewport: r.bottom > 0 && r.top < innerHeight,
      }
    })
    if (!s) { stops.push({ tag: '(body)' }); break }
    if (stops.length && stops[0].pos === s.pos) break // wrapped
    stops.push(s)
  }
  return stops
}

async function focusState(page: Page) {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null
    return {
      url: location.pathname + location.hash,
      title: document.title,
      active: el ? `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''}` : null,
      activeText: el && el !== document.body ? (el.innerText || '').trim().slice(0, 40) : null,
      scrollY: Math.round(scrollY),
    }
  })
}

function noSends(evidence: Evidence) {
  expect(evidence.blocked, 'the review must not send anything').toEqual([])
}

test('keyboard: home — tab order, Learn more, Sign in via Enter', async ({ page, evidence }, info) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  await expect(page.locator('h1')).toBeVisible()
  const stops = await tabWalk(page, 15)

  // "Learn more" by keyboard.
  await page.goto('/', { waitUntil: 'networkidle' })
  const learn = page.getByRole('link', { name: 'Learn more' })
  await learn.focus()
  await page.keyboard.press('Enter')
  await page.waitForTimeout(600)
  const afterLearnMore = await focusState(page)
  const sectionTop = await page.locator('#how-it-works').evaluate((e) => Math.round(e.getBoundingClientRect().top))
  await shot(page, info, 'kbd-home-learn-more', false)

  // "Sign in" by keyboard: where does focus go after the route change?
  await page.goto('/', { waitUntil: 'networkidle' })
  const signIn = page.getByRole('link', { name: 'Sign in' })
  await signIn.focus()
  await shot(page, info, 'kbd-home-signin-focused', false)
  await page.keyboard.press('Enter')
  await page.waitForURL('**/login')
  await page.locator('input[type="email"]').waitFor()
  const afterSignIn = await focusState(page)
  // Next Tab from there.
  await page.keyboard.press('Tab')
  const firstTabOnLogin = await focusState(page)

  record(info.project.name, 'kbd-home', { stops, afterLearnMore, sectionTop, afterSignIn, firstTabOnLogin })
  noSends(evidence)
})

test('keyboard: login — tab order and focus indicators (no submit)', async ({ page, evidence }, info) => {
  await page.goto('/login', { waitUntil: 'networkidle' })
  await page.locator('input[type="email"]').waitFor()
  const stops = await tabWalk(page, 8)
  await page.locator('#email').focus()
  await shot(page, info, 'kbd-login-email-focused', false)
  const crop = path.join(OUT, 'screens', info.project.name, 'kbd-login-form-email-focused.png')
  await page.locator('form.login-form').screenshot({ path: crop })
  record(info.project.name, 'kbd-login', { stops, crop })
  noSends(evidence)
})

test('keyboard: not-found — Go to Home via Enter', async ({ page, evidence }, info) => {
  await page.goto('/no-such-page-live-review', { waitUntil: 'networkidle' })
  await expect(page.locator('h1')).toBeVisible()
  const stops = await tabWalk(page, 6)
  await page.getByRole('link', { name: 'Go to Home' }).focus()
  await page.keyboard.press('Enter')
  await page.waitForURL((u) => u.pathname === '/')
  await page.locator('h1').waitFor()
  const afterHome = await focusState(page)
  await shot(page, info, 'kbd-404-to-home', false)
  record(info.project.name, 'kbd-404', { stops, afterHome })
  noSends(evidence)
})

test('keyboard: enrolment — tab order (no submit)', async ({ page, evidence }, info) => {
  await page.goto('/elicitation/join', { waitUntil: 'networkidle' })
  await page.locator('.chip').first().waitFor({ timeout: 15_000 })
  const stops = await tabWalk(page, 40)
  record(info.project.name, 'kbd-join', { stops })
  noSends(evidence)
})
