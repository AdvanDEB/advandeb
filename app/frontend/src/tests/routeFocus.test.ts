import { describe, it, expect, afterEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { RouterView, createRouter, createMemoryHistory } from 'vue-router'
import RouteFocus from '@/components/common/RouteFocus.vue'

/**
 * After a client-side navigation focus used to stay on the clicked link, or
 * drop to <body> when that link left with the old view, and a screen reader
 * heard nothing (F-006). RouteFocus moves focus to the new view's heading.
 */

const view = (inner: string) => ({ template: `<main id="main-content" tabindex="-1">${inner}</main>` })

function setUp() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: view('<h1>Home</h1><input id="search" />') },
      { path: '/login', component: view('<h1>Sign in</h1>'), meta: { title: 'Sign in' } },
      { path: '/chat', component: view('<p>Chat without a heading</p>') },
    ],
  })
  router.afterEach(to => { document.title = to.meta.title ? `${to.meta.title} · AdvanDEB` : 'AdvanDEB' })
  const Shell = defineComponent(() => () => [h(RouterView), h(RouteFocus)])
  const wrapper = mount(Shell, { attachTo: document.body, global: { plugins: [router] } })
  return { router, wrapper }
}

let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = '' })

const announcer = () => document.querySelector('[aria-live="polite"]')?.textContent?.trim()

describe('RouteFocus', () => {
  it('leaves focus alone on the first load', async () => {
    const s = setUp(); wrapper = s.wrapper
    await s.router.push('/')
    await flushPromises()
    expect(document.activeElement).toBe(document.body)
  })

  it("moves focus to the new view's heading", async () => {
    const s = setUp(); wrapper = s.wrapper
    await s.router.push('/')
    await s.router.push('/login')
    await flushPromises()
    const h1 = document.querySelector('h1')!
    expect(h1.textContent).toBe('Sign in')
    expect(document.activeElement).toBe(h1)
    expect(h1.getAttribute('tabindex')).toBe('-1')
    expect(announcer()).toBe('') // the heading itself is what gets read
  })

  it('falls back to <main> and announces the title when there is no heading', async () => {
    const s = setUp(); wrapper = s.wrapper
    await s.router.push('/')
    await s.router.push('/chat')
    await flushPromises()
    expect(document.activeElement?.id).toBe('main-content')
    expect(announcer()).toBe('AdvanDEB')
  })

  it('does not take focus when only the query changes', async () => {
    const s = setUp(); wrapper = s.wrapper
    await s.router.push('/login')
    await s.router.push('/')
    await flushPromises()
    const input = document.getElementById('search') as HTMLInputElement
    input.focus()
    await s.router.push('/?q=growth')
    await flushPromises()
    expect(document.activeElement).toBe(input)
  })
})
