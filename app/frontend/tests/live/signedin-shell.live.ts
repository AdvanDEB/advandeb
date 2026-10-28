// The signed-in shell (AppLayout): navigation rail, its expand toggle, the
// phone drawer, the skip link, focus and title after a route change, and the
// sizes of controls whose CSS reads the --el-* tokens (F-001). Look only; the
// rail toggle writes a local preference and is restored afterwards.
import { test, expect, shot, axe } from './guard'
import { open, record, screenPath } from './collect'

async function shellMetrics(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const box = (sel: string) => {
      const el = document.querySelector<HTMLElement>(sel)
      if (!el || !el.getClientRects().length) return null
      const r = el.getBoundingClientRect()
      const cs = getComputedStyle(el)
      return { w: Math.round(r.width), h: Math.round(r.height), padding: cs.padding, minHeight: cs.minHeight, transition: cs.transitionDuration }
    }
    return {
      token: getComputedStyle(document.documentElement).getPropertyValue('--el-touch'),
      sidebar: box('.sidebar'),
      navLink: box('.nav-link'),
      navLinks: Array.from(document.querySelectorAll<HTMLElement>('.nav-link')).map((a) => Math.round(a.getBoundingClientRect().height)),
      navLabels: Array.from(document.querySelectorAll<HTMLElement>('.nav-link')).map((a) => a.getAttribute('aria-label')),
      railToggle: box('.rail-toggle'),
      logout: box('.logout-btn'),
      hamburger: box('.hamburger'),
      skipLink: !!document.querySelector('a.skip-link'),
      expanded: document.querySelector('.rail-toggle')?.getAttribute('aria-expanded') ?? null,
    }
  })
}

test('shell: rail, toggle, skip link, route change', async ({ page, evidence }, info) => {
  const phone = info.project.name === 'phone'
  await open(page, '/documentation')
  const before = await shellMetrics(page)
  await shot(page, info, 'shell-documentation-fold', false)
  const navShot = screenPath(info, 'shell-sidebar')
  if (!phone) await page.locator('nav#app-sidebar').screenshot({ path: navShot })

  // Skip link: first Tab stop, and Enter moves focus to <main>.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('Tab')
  const firstStop = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement
    const r = el.getBoundingClientRect()
    return { cls: el.className, text: el.innerText?.trim(), visibleInViewport: r.top >= 0 && r.left >= 0 && r.width > 1 }
  })
  await shot(page, info, 'shell-skip-link-focused', false)
  await page.keyboard.press('Enter')
  const afterSkip = await page.evaluate(() => (document.activeElement as HTMLElement)?.id || document.activeElement?.tagName)

  // Rail toggle (desktop/tablet) or drawer (phone).
  let toggled: unknown
  if (!phone) {
    const t = page.locator('.rail-toggle')
    const states: (string | null)[] = [await t.getAttribute('aria-expanded')]
    await t.click()
    await page.waitForTimeout(400)
    states.push(await t.getAttribute('aria-expanded'))
    toggled = await shellMetrics(page)
    await shot(page, info, 'shell-rail-toggled', false)
    await page.locator('nav#app-sidebar').screenshot({ path: screenPath(info, 'shell-sidebar-toggled') })
    await t.click() // restore the preference
    await page.waitForTimeout(400)
    states.push(await t.getAttribute('aria-expanded'))
    if (states[2] !== states[0]) { // one more try, then record what happened
      await t.click()
      await page.waitForTimeout(400)
      states.push(await t.getAttribute('aria-expanded'))
    }
    toggled = { metrics: toggled, states }
  } else {
    await page.locator('.hamburger').click()
    await page.waitForTimeout(400)
    const drawer = await page.evaluate(() => ({
      active: (document.activeElement as HTMLElement)?.getAttribute('aria-label') || document.activeElement?.tagName,
      inSidebar: !!document.activeElement?.closest('#app-sidebar'),
      expanded: document.querySelector('.hamburger')?.getAttribute('aria-expanded'),
    }))
    const m = await shellMetrics(page)
    await shot(page, info, 'shell-drawer-open', false)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)
    const afterEsc = await page.evaluate(() => ({
      expanded: document.querySelector('.hamburger')?.getAttribute('aria-expanded'),
      active: (document.activeElement as HTMLElement)?.getAttribute('aria-label') || document.activeElement?.tagName,
    }))
    toggled = { drawer, metrics: m, afterEsc }
  }

  // Route change through the nav: title and focus afterwards.
  if (phone) await page.locator('.hamburger').click()
  await page.locator('.nav-link[aria-label="Facts"]').click()
  await page.waitForURL('**/facts')
  await page.waitForTimeout(800)
  const afterNav = await page.evaluate(() => ({
    title: document.title,
    active: document.activeElement?.tagName + ((document.activeElement as HTMLElement)?.className ? '.' + String((document.activeElement as HTMLElement).className).split(' ')[0] : ''),
    ariaCurrent: document.querySelector('[aria-current="page"]')?.getAttribute('aria-label'),
    drawerOpen: document.querySelector('.hamburger')?.getAttribute('aria-expanded') ?? null,
  }))

  const violations = await axe(page, info, 'axe-shell-facts')
  record(info, 'shell', { before, firstStop, afterSkip, toggled, afterNav, axe: violations, evidence })
  expect(evidence.blocked).toEqual([])
})
