// @vitest-environment node
import fs from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { NodeTypes, type ElementNode, type TemplateChildNode } from '@vue/compiler-dom'

/**
 * F-028: controls a screen reader announced with no name (axe "label",
 * "select-name", "button-name"): the privacy page's only checkbox, the
 * pagination selects and page-number inputs on /facts and /documents, the KB
 * graph's range sliders, and the chat Send button while it shows a spinner.
 *
 * Static check over those SFCs' templates: every <input> (other than
 * hidden/submit/button), <select> and <textarea> has a name from aria-label,
 * aria-labelledby, an enclosing <label> with its own text, or a <label for>.
 */

const FILES = [
  'src/views/PrivacySettingsView.vue',
  'src/views/FactsView.vue',
  'src/components/documents/DocumentLibrary.vue',
  'src/components/kb/SchemaPanel.vue',
  'src/components/chat/MessageInput.vue',
]

type Attr = { name: string, value?: string }

function attrs(el: ElementNode): Attr[] {
  return el.props.map(p => {
    if (p.type === NodeTypes.ATTRIBUTE) return { name: p.name, value: p.value?.content }
    // v-bind:aria-label="…" / :id="…"
    if (p.type === NodeTypes.DIRECTIVE && p.name === 'bind' && p.arg?.type === NodeTypes.SIMPLE_EXPRESSION) {
      return { name: p.arg.content, value: '(bound)' }
    }
    return { name: '' }
  })
}

const has = (el: ElementNode, name: string) => attrs(el).some(a => a.name === name)
const textOf = (n: TemplateChildNode): string =>
  n.type === NodeTypes.TEXT ? n.content.trim()
    : n.type === NodeTypes.INTERPOLATION ? '{{}}'
      : n.type === NodeTypes.ELEMENT && n.tag !== 'input' && n.tag !== 'select' ? n.children.map(textOf).join('') : ''

function unnamed(file: string): string[] {
  const { descriptor } = parseSfc(fs.readFileSync(path.join(process.cwd(), file), 'utf8'), { filename: file })
  const root = descriptor.template!.ast!
  const labelFor = new Set<string>()
  const offenders: string[] = []

  const collect = (nodes: TemplateChildNode[]) => nodes.forEach(n => {
    if (n.type !== NodeTypes.ELEMENT) return
    if (n.tag === 'label') attrs(n).filter(a => a.name === 'for').forEach(a => labelFor.add(a.value ?? ''))
    collect(n.children)
  })
  collect(root.children)

  const walk = (nodes: TemplateChildNode[], inNamedLabel: boolean) => nodes.forEach(n => {
    if (n.type !== NodeTypes.ELEMENT) return
    const named = inNamedLabel || (n.tag === 'label' && textOf(n).length > 0)
    const control = n.tag === 'select' || n.tag === 'textarea' ||
      (n.tag === 'input' && !['hidden', 'submit', 'button'].includes(attrs(n).find(a => a.name === 'type')?.value ?? ''))
    if (control) {
      const id = attrs(n).find(a => a.name === 'id')?.value
      const ok = named || has(n, 'aria-label') || has(n, 'aria-labelledby') || (id !== undefined && labelFor.has(id)) ||
        has(n, 'placeholder') && n.tag === 'textarea'
      if (!ok) offenders.push(`${file}:${n.loc.start.line} <${n.tag} ${n.loc.source.slice(n.tag.length + 1, 60).replace(/\s+/g, ' ')}…>`)
    }
    walk(n.children, named)
  })
  walk(root.children, false)
  return offenders
}

describe('form controls have an accessible name', () => {
  it.each(FILES)('%s', file => {
    expect(unnamed(file)).toEqual([])
  })
})
