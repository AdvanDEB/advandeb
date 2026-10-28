// /elicitation/join, signed out: how the public enrolment form renders and
// behaves before anything is sent. Nothing here submits the form — the only
// interactions are focus, blur and the client-side area chips/ratings.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect, shot } from './guard'

test.use({ signedIn: false })

const OUT = process.env.LIVE_OUT || '/tmp/advandeb-live'

function record(project: string, name: string, data: unknown) {
  const dir = path.join(OUT, 'data', project)
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, `${name}.json`), JSON.stringify(data, null, 2))
}

test('enrolment form: styling tokens and controls', async ({ page, evidence }, info) => {
  await page.goto('/elicitation/join', { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.locator('.chip').first().waitFor({ timeout: 15_000 })

  const styles = await page.evaluate(() => {
    const cs = (el: Element | null) => (el ? getComputedStyle(el) : null)
    const root = getComputedStyle(document.documentElement)
    const pageEl = document.querySelector('.enrol-page')
    const submit = document.querySelector<HTMLButtonElement>('button[type="submit"]')
    const input = document.querySelector('input[autocomplete="name"]')
    const chip = document.querySelector('.chip')
    const pick = (s: CSSStyleDeclaration | null, keys: string[]) =>
      s ? Object.fromEntries(keys.map((k) => [k, s.getPropertyValue(k)])) : null
    return {
      tokenOnRoot: { '--el-s1': root.getPropertyValue('--el-s1'), '--el-accent': root.getPropertyValue('--el-accent') },
      tokenOnPage: pageEl ? { '--el-accent': getComputedStyle(pageEl).getPropertyValue('--el-accent') } : null,
      page: pick(cs(pageEl), ['background-color', 'padding-top']),
      submit: submit ? {
        text: submit.innerText,
        rect: submit.getBoundingClientRect().toJSON(),
        ...pick(cs(submit), ['background-color', 'color', 'border-top-width', 'border-top-style', 'padding-top', 'min-height']),
      } : null,
      nameInput: input ? {
        rect: input.getBoundingClientRect().toJSON(),
        ...pick(cs(input), ['border-top-width', 'border-top-style', 'border-top-color', 'padding-top', 'min-height', 'font-size']),
        required: (input as HTMLInputElement).required,
        ariaRequired: input.getAttribute('aria-required'),
      } : null,
      chip: chip ? { rect: chip.getBoundingClientRect().toJSON(), ...pick(cs(chip), ['background-color', 'border-top-style', 'padding-top']) } : null,
      requiredMarkers: Array.from(document.querySelectorAll('.field input, .field select')).map((el) => ({
        name: (el.closest('label')?.querySelector('span')?.textContent || '').trim(),
        required: (el as HTMLInputElement).required,
        ariaRequired: el.getAttribute('aria-required'),
      })),
    }
  })

  await shot(page, info, 'join-actions', false)
  const actions = page.locator('.actions')
  await actions.scrollIntoViewIfNeeded()
  const file = path.join(OUT, 'screens', info.project.name, 'join-actions-element.png')
  await actions.screenshot({ path: file })

  // Familiarity: pick one area and rate it — local state only.
  await page.locator('.chip').first().click()
  const scale = page.locator('[role="radiogroup"]').first()
  await scale.waitFor()
  const radios = scale.locator('[role="radio"]')
  await radios.nth(2).click()
  const radio = await page.evaluate(() => {
    const g = document.querySelector('[role="radiogroup"]')!
    const items = Array.from(g.querySelectorAll<HTMLElement>('[role="radio"]'))
    return {
      tabStops: items.filter((b) => b.tabIndex >= 0).length,
      checked: items.map((b) => b.getAttribute('aria-checked')),
      sizes: items.map((b) => { const r = b.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)] }),
    }
  })
  // Arrow keys are the ARIA radiogroup contract; does focus/selection move?
  await radios.nth(2).focus()
  await page.keyboard.press('ArrowRight')
  const arrow = await page.evaluate(() => ({
    focused: (document.activeElement as HTMLElement)?.getAttribute('aria-label'),
    checked: Array.from(document.querySelectorAll('[role="radiogroup"] [role="radio"]')).map((b) => b.getAttribute('aria-checked')),
  }))
  await shot(page, info, 'join-rated', false)

  // Blur validation (client-side only): focus the name field, leave it empty.
  const name = page.locator('input[autocomplete="name"]')
  await name.focus()
  await page.keyboard.press('Tab')
  const afterBlur = await page.evaluate(() => {
    const input = document.querySelector('input[autocomplete="name"]')!
    const err = input.closest('label')?.querySelector('.err')
    return {
      ariaInvalid: input.getAttribute('aria-invalid'),
      errText: err?.textContent?.trim() ?? null,
      errId: err?.id || null,
      describedBy: input.getAttribute('aria-describedby'),
      errRole: err?.getAttribute('role') ?? null,
      errLive: err?.closest('[aria-live]')?.getAttribute('aria-live') ?? null,
      why: document.querySelector('.actions .why')?.textContent?.trim() ?? null,
      whyLive: document.querySelector('.actions .why')?.getAttribute('aria-live') ?? null,
    }
  })
  await shot(page, info, 'join-after-blur', false)

  // A tap right after leaving an empty field: the blur adds an error line
  // above the target. Does the tap still land? (email is focused now.)
  const target = page.locator('.chip').nth(3)
  const before = await target.boundingBox()
  await target.click()
  const lostTap = {
    yBefore: before && Math.round(before.y),
    yAfter: await target.boundingBox().then((b) => b && Math.round(b.y)),
    pressed: await target.getAttribute('aria-pressed'),
  }
  await shot(page, info, 'join-lost-tap', false)

  record(info.project.name, 'join-detail', { styles, afterBlur, radio, arrow, lostTap, actionsShot: file })
  expect(evidence.blocked, 'the review must not send anything').toEqual([])
})
