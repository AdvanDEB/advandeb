// /chat, signed in. Every viewport: the layout, the model picker panel and
// (phone) the conversations drawer, looked at only. On desktop, and only when
// LIVE_CHAT_BUDGET is set, ONE short question is sent to see the streaming,
// agent-activity and error states (it creates one conversation in the
// reviewer's own history). Without the budget the guard drops the frame.
import { test, expect, shot, axe } from './guard'
import { record } from './collect'

const SEND = Number(process.env.LIVE_CHAT_BUDGET || 0) > 0

test('chat: layout, panels, and one question on desktop', async ({ page, evidence }, info) => {
  test.setTimeout(180_000)
  await page.goto('/chat', { waitUntil: 'domcontentloaded' })
  await page.locator('textarea').waitFor()
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})

  // Model picker panel (local state only).
  const picker = page.locator('button[aria-expanded]').filter({ hasText: /Nemotron|Claude|GPT|Gemini|GitHub/ }).first()
  let pickerState: unknown = null
  if (await picker.count()) {
    await picker.click()
    await page.waitForTimeout(500)
    pickerState = await page.evaluate(() => ({
      expanded: document.querySelector('button[aria-expanded="true"]')?.textContent?.trim() ?? null,
      dialog: document.querySelector('[role="dialog"]')?.getAttribute('aria-label') ?? null,
    }))
    await shot(page, info, 'chat-llm-panel', false)
    await picker.click()
  }

  let drawer: unknown = null
  if (info.project.name === 'phone') {
    const t = page.locator('button[aria-controls="chat-sessions"]')
    if (await t.count()) {
      await t.click()
      await page.waitForTimeout(500)
      drawer = { expanded: await t.getAttribute('aria-expanded') }
      await shot(page, info, 'chat-sessions-drawer', false)
      await page.keyboard.press('Escape')
      await page.waitForTimeout(300)
      drawer = { ...(drawer as object), afterEscape: await t.getAttribute('aria-expanded') }
    }
  }

  let exchange: unknown = null
  if (SEND && info.project.name === 'desktop') {
    const box = page.locator('textarea').first()
    await box.fill('In one sentence: what does the kappa-rule say in DEB theory?')
    const t0 = Date.now()
    await box.press('Enter')
    let firstToken = -1
    const deadline = Date.now() + 120_000
    while (Date.now() < deadline) {
      const s = await page.evaluate(() => {
        const msgs = Array.from(document.querySelectorAll('[class*="message"]'))
        const last = msgs[msgs.length - 1] as HTMLElement | undefined
        return {
          count: msgs.length,
          lastText: last?.innerText?.trim().slice(0, 300) ?? '',
          busy: !!document.querySelector('[class*="typing"], [class*="streaming"], [aria-busy="true"]'),
        }
      })
      if (firstToken < 0 && s.lastText && !/^In one sentence/.test(s.lastText)) firstToken = Date.now() - t0
      if (firstToken >= 0 && !s.busy) break
      await page.waitForTimeout(1000)
    }
    await page.waitForTimeout(1500)
    exchange = await page.evaluate(() => {
      const msgs = Array.from(document.querySelectorAll('[class*="message"]')) as HTMLElement[]
      return {
        lastText: msgs[msgs.length - 1]?.innerText?.trim().slice(0, 400) ?? null,
        live: Array.from(document.querySelectorAll('[aria-live]')).map((e) => e.getAttribute('aria-live')),
        activity: document.querySelector('.agent-activity')?.textContent?.trim().replace(/\s+/g, ' ').slice(0, 200) ?? null,
        url: location.pathname + location.search,
      }
    })
    exchange = { ...(exchange as object), firstTokenMs: firstToken, totalMs: Date.now() - t0 }
    await shot(page, info, 'chat-exchange', false)
  }

  const violations = await axe(page, info, 'axe-chat-detail')
  record(info, 'chat-detail', { pickerState, drawer, exchange, sent: SEND && info.project.name === 'desktop', axe: violations, evidence })
  // The only blocked requests allowed: the PUTs the app sends after a new
  // conversation is created (model/system prompt), which the guard stops.
  expect(evidence.blocked.filter((b) => !/\/api\/chat\/sessions\/[^/]+\/(llm|system-prompt)$/.test(new URL(b.url).pathname))).toEqual([])
})
