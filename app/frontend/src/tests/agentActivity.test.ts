import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import AgentActivity from '@/components/chat/AgentActivity.vue'

/**
 * F-032: the Chatbot card read "-0.8s" when it started. startedAt is set when
 * the event arrives, but the component's clock only advanced on a 1 s tick.
 */
afterEach(() => vi.useRealTimers())

describe('AgentActivity elapsed time', () => {
  it('starts at 0.0s, never negative, between clock ticks', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    vi.setSystemTime(1_000_000)
    const w = mount(AgentActivity, { props: { agents: [], workflowTrace: [] } })

    vi.setSystemTime(1_000_800)          // 0.8 s later, before the next tick
    await w.setProps({
      agents: [{ name: 'chatbot', displayName: 'Chatbot', status: 'working', startedAt: Date.now() }],
    })
    await nextTick()
    const shown = w.find('.agent-card').text()
    expect(shown).toContain('0.0s')
    expect(shown).not.toContain('-')

    vi.advanceTimersByTime(2000)
    await nextTick()
    expect(w.find('.agent-card').text()).toContain('2.0s')
  })
})
