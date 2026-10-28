import { describe, it, expect, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import NodeTablePanel, { ROW_HEIGHT, OVERSCAN } from '@/components/kb/NodeTablePanel.vue'
import type { GraphNode } from '@/utils/kbApi'

/** Degrees descend with the index, so the default sort (degree, desc) keeps index order. */
function makeNodes(n: number): GraphNode[] {
  return Array.from({ length: n }, (_, i) => ({
    _id: `n${i}`,
    schema_id: 's1',
    node_type: i % 2 ? 'document' : 'fact',
    entity_collection: 'docs',
    entity_id: `e${i}`,
    label: `Node ${i}`,
    properties: {},
    degree: n - i,
  }))
}

const N = 5000
let wrapper: VueWrapper | null = null

function mountPanel(nodes = makeNodes(N), selectedNode: GraphNode | null = null) {
  wrapper = mount(NodeTablePanel, { props: { nodes, selectedNode }, attachTo: document.body })
  return wrapper
}

function rowLabels(w: VueWrapper): string[] {
  return w.findAll('tr.ntp-row').map(r => r.find('.col-label-cell').text())
}

function spacerHeight(w: VueWrapper, which: 'top' | 'bottom'): number {
  const el = w.find(`tr.ntp-spacer--${which}`)
  return el.exists() ? parseFloat((el.element as HTMLElement).style.height) : 0
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('NodeTablePanel virtualisation', () => {
  it('renders only a window of rows for 5,000 nodes, with spacers for the rest', () => {
    const w = mountPanel()
    const rows = w.findAll('tr.ntp-row')

    expect(rows.length).toBeGreaterThan(0)
    expect(rows.length).toBeLessThan(60)
    expect(rowLabels(w)[0]).toBe('Node 0')

    // Nothing above the first row; everything not rendered is accounted for below.
    expect(w.find('tr.ntp-spacer--top').exists()).toBe(false)
    expect(spacerHeight(w, 'bottom')).toBe((N - rows.length) * ROW_HEIGHT)

    // The full size is still advertised to assistive tech (+1 for the header row).
    expect(w.find('table').attributes('aria-rowcount')).toBe(String(N + 1))
    expect(w.find('.ntp-count').text()).toBe(`${N} / ${N}`)
  })

  it('moves the window when the table scrolls', async () => {
    const w = mountPanel()
    const scroller = w.find('.ntp-scroll').element as HTMLElement

    scroller.scrollTop = 2500 * ROW_HEIGHT
    await w.find('.ntp-scroll').trigger('scroll')

    const labels = rowLabels(w)
    expect(labels).toContain('Node 2500')
    expect(labels).not.toContain('Node 0')
    expect(labels[0]).toBe(`Node ${2500 - OVERSCAN}`)
    expect(w.findAll('tr.ntp-row').length).toBeLessThan(60)

    const rendered = labels.length
    expect(spacerHeight(w, 'top')).toBe((2500 - OVERSCAN) * ROW_HEIGHT)
    expect(spacerHeight(w, 'top') + rendered * ROW_HEIGHT + spacerHeight(w, 'bottom')).toBe(N * ROW_HEIGHT)

    // Rows keep their absolute position for assistive tech.
    expect(w.find('tr.ntp-row').attributes('aria-rowindex')).toBe(String(2500 - OVERSCAN + 2))
  })

  it('emits select with the clicked node, including after scrolling', async () => {
    const w = mountPanel()
    await w.findAll('tr.ntp-row')[3].trigger('click')
    expect(w.emitted('select')?.[0]?.[0]).toMatchObject({ _id: 'n3' })

    const scroller = w.find('.ntp-scroll').element as HTMLElement
    scroller.scrollTop = 4000 * ROW_HEIGHT
    await w.find('.ntp-scroll').trigger('scroll')
    const row = w.findAll('tr.ntp-row').find(r => r.text().includes('Node 4001'))!
    await row.trigger('click')
    expect(w.emitted('select')?.[1]?.[0]).toMatchObject({ _id: 'n4001' })
  })

  it('marks the selected node and keeps the active row on it', async () => {
    const nodes = makeNodes(N)
    const w = mountPanel(nodes, null)
    await w.setProps({ selectedNode: nodes[2] })

    const row = w.findAll('tr.ntp-row')[2]
    expect(row.classes()).toContain('row-selected')
    expect(row.attributes('aria-selected')).toBe('true')
    expect(w.findAll('tr.ntp-row')[1].attributes('aria-selected')).toBe('false')
    // Keyboard navigation resumes from the selection.
    expect(w.find('table').attributes('aria-activedescendant')).toBe(row.attributes('id'))
  })

  it('selects from the keyboard: arrows move the active row, Enter/Space select', async () => {
    const w = mountPanel()
    const table = w.find('table')
    expect(table.attributes('tabindex')).toBe('0')
    expect(table.attributes('role')).toBe('grid')

    await table.trigger('keydown', { key: 'ArrowDown' })
    await table.trigger('keydown', { key: 'ArrowDown' })
    await table.trigger('keydown', { key: 'Enter' })
    expect(w.emitted('select')?.[0]?.[0]).toMatchObject({ _id: 'n2' })

    const active = w.find('tr.row-active')
    expect(active.find('.col-label-cell').text()).toBe('Node 2')
    expect(table.attributes('aria-activedescendant')).toBe(active.attributes('id'))

    await table.trigger('keydown', { key: 'ArrowUp' })
    await table.trigger('keydown', { key: ' ' })
    expect(w.emitted('select')?.[1]?.[0]).toMatchObject({ _id: 'n1' })
  })

  it('End jumps to the last row and scrolls it into the rendered window', async () => {
    const w = mountPanel()
    const table = w.find('table')

    await table.trigger('keydown', { key: 'End' })
    await nextTick()

    const labels = rowLabels(w)
    expect(labels).toContain(`Node ${N - 1}`)
    expect(labels.length).toBeLessThan(60)
    expect(w.find('tr.row-active').find('.col-label-cell').text()).toBe(`Node ${N - 1}`)

    await table.trigger('keydown', { key: 'Enter' })
    expect(w.emitted('select')?.[0]?.[0]).toMatchObject({ _id: `n${N - 1}` })

    await table.trigger('keydown', { key: 'Home' })
    expect(rowLabels(w)[0]).toBe('Node 0')
  })

  it('still filters and sorts over the whole list', async () => {
    const w = mountPanel()

    // "Node 49", "Node 490"–"499", "Node 4900"–"4999": 111 matches.
    await w.find('input.ntp-search').setValue('Node 49')
    expect(w.find('.ntp-count').text()).toBe(`111 / ${N}`)
    expect(w.find('table').attributes('aria-rowcount')).toBe('112')
    expect(w.findAll('tr.ntp-row').length).toBeLessThan(60)
    expect(rowLabels(w)[0]).toBe('Node 49') // highest degree first

    // Sorting by label is a real button now, and announces its direction.
    const labelHeader = w.find('th.col-label')
    await labelHeader.find('button').trigger('click')
    expect(labelHeader.attributes('aria-sort')).toBe('ascending')
    expect(rowLabels(w)[0]).toBe('Node 49')
    expect(rowLabels(w)[1]).toBe('Node 490')

    await w.find('input.ntp-search').setValue('no such node')
    expect(w.findAll('tr.ntp-row').length).toBe(0)
    expect(w.find('.ntp-empty').exists()).toBe(true)
  })
})
