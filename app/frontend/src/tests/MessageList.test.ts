import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageList from '@/components/chat/MessageList.vue'

const makeMsg = (role: 'user' | 'assistant', content: string) => ({
  id: crypto.randomUUID(),
  role,
  content,
  citations: [],
})

describe('MessageList', () => {
  it('renders empty state when no messages', () => {
    const wrapper = mount(MessageList, { props: { messages: [] } })
    expect(wrapper.find('.empty-state').exists()).toBe(true)
  })

  it('renders user and assistant messages', () => {
    const messages = [
      makeMsg('user', 'Hello'),
      makeMsg('assistant', 'World'),
    ]
    const wrapper = mount(MessageList, { props: { messages } })
    const items = wrapper.findAll('.message')
    expect(items).toHaveLength(2)
    expect(items[0].classes()).toContain('user')
    expect(items[1].classes()).toContain('assistant')
  })

  it('renders markdown in assistant messages', () => {
    const messages = [makeMsg('assistant', '**bold text**')]
    const wrapper = mount(MessageList, { props: { messages } })
    expect(wrapper.find('.message-content').html()).toContain('<strong>')
  })

  it('shows citation badges when citations present', () => {
    const messages = [{
      id: '1',
      role: 'assistant' as const,
      content: 'Some answer',
      citations: [{ id: 'c1', index: 1, text: 'Source A' }],
    }]
    const wrapper = mount(MessageList, { props: { messages } })
    expect(wrapper.find('.citation-badge').exists()).toBe(true)
    expect(wrapper.find('.citation-badge').text()).toBe('[1]')
  })

  it('emits show-provenance when citation clicked', async () => {
    const messages = [{
      id: '1',
      role: 'assistant' as const,
      content: 'Answer',
      citations: [{ id: 'cit-42', index: 1, text: 'Source' }],
    }]
    const wrapper = mount(MessageList, { props: { messages } })
    await wrapper.find('.citation-badge').trigger('click')
    const emitted = wrapper.emitted('show-provenance')
    expect(emitted).toBeTruthy()
    expect((emitted![0][0] as any).id).toBe('cit-42')
  })
})
