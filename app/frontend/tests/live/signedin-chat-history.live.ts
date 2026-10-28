// Reopen the reviewer's most recent conversation (a read) to see how a stored
// answer renders: markdown, citations, provenance links. Sends nothing.
import { test, expect, shot, axe } from './guard'
import { record } from './collect'

test('chat: reopen the latest own conversation (read only)', async ({ page, evidence }, info) => {
  test.skip(info.project.name !== 'desktop', 'rendering does not depend on the viewport')
  await page.goto('/chat', { waitUntil: 'domcontentloaded' })
  await page.locator('.session-open').first().waitFor()
  await page.locator('.session-open').first().click()
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.waitForTimeout(1500)
  const view = await page.evaluate(() => {
    const assistant = Array.from(document.querySelectorAll<HTMLElement>('[class*="assistant"]'))
    const last = assistant[assistant.length - 1]
    return {
      url: location.pathname + location.search,
      assistantBlocks: assistant.length,
      answerChars: last?.innerText.length ?? 0,
      answerStart: last?.innerText.trim().slice(0, 160) ?? null,
      citations: last ? last.querySelectorAll('a, [class*="cit"], sup').length : 0,
      externalLinks: last ? Array.from(last.querySelectorAll('a[href^="http"]')).map((a) => ({ rel: a.getAttribute('rel'), target: a.getAttribute('target') })).slice(0, 5) : [],
      errorText: document.querySelector('[class*="error"]')?.textContent?.trim().slice(0, 160) ?? null,
    }
  })
  await shot(page, info, 'chat-history-latest', false)
  const violations = await axe(page, info, 'axe-chat-history')
  record(info, 'chat-history', { view, axe: violations, evidence })
  expect(evidence.blocked).toEqual([])
})
