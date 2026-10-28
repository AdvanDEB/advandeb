// F-025 evidence: the signed-in navigation rail on /elicitation, collapsed and
// expanded (desktop 1440, tablet 768) and the phone drawer open. Records the
// computed values the --el-* tokens should have produced, overlaps in the rail
// footer, and every red/pink-hued border, outline or shadow on the page (the
// reported "pink edge"). Look only; the rail toggle is restored afterwards.
import type { Page } from '@playwright/test'
import { test, expect } from './guard'
import { record, screenPath } from './collect'

async function railFacts(page: Page) {
  return page.evaluate(() => {
    const q = (s: string) => document.querySelector<HTMLElement>(s)
    const rect = (el: Element | null) => {
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }
    }
    const sidebar = q('.sidebar')
    const cs = sidebar ? getComputedStyle(sidebar) : null
    const overlap = (a: Element | null, b: Element | null) => {
      if (!a || !b) return null
      const r1 = a.getBoundingClientRect(), r2 = b.getBoundingClientRect()
      const w = Math.min(r1.right, r2.right) - Math.max(r1.left, r2.left)
      const h = Math.min(r1.bottom, r2.bottom) - Math.max(r1.top, r2.top)
      return w > 0 && h > 0 ? { w: Math.round(w), h: Math.round(h) } : null
    }
    const brand = q('.brand-icon'), toggle = q('.rail-toggle')
    const navLink = q('.nav-link')
    const nlcs = navLink ? getComputedStyle(navLink) : null
    return {
      elS2OnSidebar: cs?.getPropertyValue('--el-s2') ?? null,
      elTouchOnSidebar: cs?.getPropertyValue('--el-touch') ?? null,
      sidebarPadding: cs?.padding ?? null,
      sidebarWidth: sidebar ? Math.round(sidebar.getBoundingClientRect().width) : null,
      navLink: navLink ? { height: Math.round(navLink.getBoundingClientRect().height), padding: nlcs!.padding, minHeight: nlcs!.minHeight, gap: nlcs!.gap, margin: nlcs!.margin } : null,
      navLinkHeights: Array.from(document.querySelectorAll('.nav-link')).map((a) => Math.round(a.getBoundingClientRect().height)),
      navIconBoxes: Array.from(document.querySelectorAll('.nav-icon')).map((i) => { const r = i.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)] }),
      railToggle: toggle ? { ...rect(toggle), padding: getComputedStyle(toggle).padding, expanded: toggle.getAttribute('aria-expanded') } : null,
      brandToToggleGapPx: brand && toggle ? Math.round(toggle.getBoundingClientRect().left - brand.getBoundingClientRect().right) : null,
      footer: {
        avatar: rect(q('.user-avatar-placeholder, .user-avatar')),
        logout: rect(q('.logout-btn')),
        logoutIcon: rect(q('.logout-icon')),
        avatarLogoutOverlap: overlap(q('.user-avatar-placeholder, .user-avatar'), q('.logout-btn')),
      },
    }
  })
}

/** Every visible red/pink-hued border, outline or box-shadow on the page. */
async function reddish(page: Page) {
  return page.evaluate(() => {
    const isRed = (c: string) => {
      const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/)
      if (!m) return false
      const [r, g, b, a] = [Number(m[1]), Number(m[2]), Number(m[3]), m[4] === undefined ? 1 : Number(m[4])]
      return a > 0.2 && r > 170 && r - g > 50 && r - b > 20
    }
    const out: { el: string; prop: string; value: string; rect: number[] }[] = []
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('html, body, body *'))) {
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      const name = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/)[0] : '')
      for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
        const w = parseFloat(cs.getPropertyValue(`border-${side.toLowerCase()}-width`))
        const st = cs.getPropertyValue(`border-${side.toLowerCase()}-style`)
        const col = cs.getPropertyValue(`border-${side.toLowerCase()}-color`)
        if (w > 0 && st !== 'none' && isRed(col)) out.push({ el: name, prop: `border-${side.toLowerCase()}`, value: `${w}px ${st} ${col}`, rect: [r.x, r.y, r.width, r.height].map(Math.round) })
      }
      if (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 && isRed(cs.outlineColor)) out.push({ el: name, prop: 'outline', value: `${cs.outlineWidth} ${cs.outlineStyle} ${cs.outlineColor}`, rect: [r.x, r.y, r.width, r.height].map(Math.round) })
      if (cs.boxShadow !== 'none' && (cs.boxShadow.match(/rgba?\([^)]*\)/g) || []).some(isRed)) out.push({ el: name, prop: 'box-shadow', value: cs.boxShadow, rect: [r.x, r.y, r.width, r.height].map(Math.round) })
      if (out.length > 40) break
    }
    return out
  })
}

test('F-025: rail evidence on /elicitation', async ({ page, evidence }, info) => {
  const vp = info.project.name
  await page.goto('/elicitation', { waitUntil: 'domcontentloaded' })
  await page.locator('main h1').waitFor()
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.mouse.move(900, 500) // keep the pointer off the rail (hover widens it)
  await page.waitForTimeout(300)

  const result: Record<string, unknown> = {}
  if (vp !== 'phone') {
    const t = page.locator('.rail-toggle')
    if ((await t.getAttribute('aria-expanded')) === 'true') { await t.click(); await page.mouse.move(900, 500); await page.waitForTimeout(400) }
    result.collapsed = await railFacts(page)
    await page.screenshot({ path: screenPath(info, 'F-025-rail-collapsed') })
    await page.locator('nav#app-sidebar').screenshot({ path: screenPath(info, 'F-025-rail-collapsed-crop') })

    let clicks = 0
    while ((await t.getAttribute('aria-expanded')) !== 'true' && clicks < 3) {
      await t.click(); clicks++
      await page.mouse.move(900, 500)
      await page.waitForTimeout(400)
    }
    result.expandClicksNeeded = clicks
    result.expanded = await railFacts(page)
    await page.screenshot({ path: screenPath(info, 'F-025-rail-expanded') })
    await page.locator('nav#app-sidebar').screenshot({ path: screenPath(info, 'F-025-rail-expanded-crop') })

    // Hover over the logout button (its :hover colour is the only pink in the shell CSS).
    await page.locator('.logout-btn').hover()
    await page.waitForTimeout(200)
    await page.locator('nav#app-sidebar').screenshot({ path: screenPath(info, 'F-025-rail-logout-hover') })
    await page.mouse.move(900, 500)

    // Restore the collapsed preference.
    let back = 0
    while ((await t.getAttribute('aria-expanded')) !== 'false' && back < 3) { await t.click(); back++; await page.waitForTimeout(400) }
    result.restored = await t.getAttribute('aria-expanded')
  } else {
    await page.locator('.hamburger').click()
    await page.waitForTimeout(400)
    result.drawer = await railFacts(page)
    result.hamburger = await page.evaluate(() => {
      const r = document.querySelector('.hamburger')!.getBoundingClientRect()
      return { w: Math.round(r.width), h: Math.round(r.height) }
    })
    await page.screenshot({ path: screenPath(info, 'F-025-rail-drawer-open') })
    await page.keyboard.press('Escape')
  }

  // The "pink edge": any red/pink-hued line, also with <main> focused via the skip link.
  result.reddishAtRest = await reddish(page)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('Tab')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(200)
  result.reddishMainFocused = await reddish(page)
  result.mainFocusOutline = await page.evaluate(() => {
    const m = document.querySelector('main')!
    const cs = getComputedStyle(m)
    return { focused: document.activeElement === m, outline: `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}` }
  })
  result.emojiFontNote = 'review browser has no colour-emoji font: icons render as tofu here; sizes below are tofu boxes'

  record(info, 'F-025-rail', { ...result, evidence })
  expect(evidence.blocked).toEqual([])
})
