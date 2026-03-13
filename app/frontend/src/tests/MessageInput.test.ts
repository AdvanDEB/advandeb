import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageInput from '@/components/chat/MessageInput.vue'

describe('MessageInput', () => {
  it('renders textarea', () => {
    const wrapper = mount(MessageInput, { props: { disabled: false } })
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('send button is disabled when input is empty', () => {
    const wrapper = mount(MessageInput, { props: { disabled: false } })
    const btn = wrapper.find('.send-btn')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('send button enables when text is entered', async () => {
    const wrapper = mount(MessageInput, { props: { disabled: false } })
    await wrapper.find('textarea').setValue('Hello world')
    const btn = wrapper.find('.send-btn')
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('emits send with trimmed text on form submit', async () => {
    const wrapper = mount(MessageInput, { props: { disabled: false } })
    await wrapper.find('textarea').setValue('  test message  ')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('send')).toBeTruthy()
    expect(wrapper.emitted('send')![0]).toEqual(['test message'])
  })

  it('clears textarea after send', async () => {
    const wrapper = mount(MessageInput, { props: { disabled: false } })
    const textarea = wrapper.find('textarea')
    await textarea.setValue('hello')
    await wrapper.find('form').trigger('submit')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('does not emit when disabled', async () => {
    const wrapper = mount(MessageInput, { props: { disabled: true } })
    await wrapper.find('textarea').setValue('hello')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('send')).toBeFalsy()
  })
})
