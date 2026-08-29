/**
 * LaTeX export for tDEB models.
 *
 * Bundles a `model.tex` alongside PNG renders of the network diagram and the
 * result charts, so a model can be dropped straight into a manuscript.
 */
import JSZip from 'jszip'

export interface LatexEquationItem {
  latex: string
  params?: string
  label?: string
  sublabel?: string
}

export interface LatexSection {
  title: string
  items: LatexEquationItem[]
}

export interface LatexLegendItem {
  latex: string
  text: string
}

export interface LatexBundleInput {
  modelName: string
  sections: LatexSection[]
  legend: LatexLegendItem[]
  networkSvg: SVGSVGElement | null
  charts: { states: Blob | null; fluxes: Blob | null; sankey: Blob | null }
}

/** Escape text destined for LaTeX prose (not maths). */
function esc(s: string): string {
  return s
    .replace(/\\/g, '\\textbackslash{}')
    .replace(/([&%$#_{}])/g, '\\$1')
    .replace(/~/g, '\\textasciitilde{}')
    .replace(/\^/g, '\\textasciicircum{}')
}

/**
 * Rasterise the live network SVG.
 *
 * The SVG is styled by a scoped stylesheet, and a detached clone loaded as an
 * image gets none of it — so the computed style of every drawn element is
 * copied onto the clone inline before serialising.
 */
async function svgToPng(svg: SVGSVGElement, width: number, height: number): Promise<Blob> {
  const clone = svg.cloneNode(true) as SVGSVGElement

  // Drop the pan/zoom transform and frame the content instead, so the export
  // does not depend on where the user happened to leave the viewport.
  const cloneGroup = clone.querySelector('.canvas-group')
  cloneGroup?.removeAttribute('transform')

  const sourceGroup = svg.querySelector('.canvas-group') as SVGGraphicsElement | null
  if (sourceGroup) {
    const box = sourceGroup.getBBox()
    const pad = 40
    clone.setAttribute(
      'viewBox',
      `${box.x - pad} ${box.y - pad} ${box.width + pad * 2} ${box.height + pad * 2}`,
    )
  }
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')

  const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
  background.setAttribute('width', '100%')
  background.setAttribute('height', '100%')
  background.setAttribute('fill', '#0f172a')
  clone.insertBefore(background, clone.firstChild)

  const inlineRules: { selector: string; props: string[] }[] = [
    { selector: '.node-circle', props: ['fill', 'stroke', 'stroke-width', 'opacity'] },
    { selector: '.node-halo', props: ['fill', 'opacity'] },
    { selector: '.node-label', props: ['fill', 'font-family', 'font-size', 'font-weight', 'text-anchor'] },
    { selector: '.node-value', props: ['fill', 'font-family', 'font-size', 'text-anchor'] },
    { selector: '.edge-line', props: ['stroke', 'stroke-width', 'fill'] },
    { selector: '.edge-label', props: ['fill', 'font-family', 'font-size', 'text-anchor'] },
    { selector: 'marker path', props: ['fill'] },
  ]

  for (const rule of inlineRules) {
    const originals = svg.querySelectorAll(rule.selector)
    const copies = clone.querySelectorAll(rule.selector)
    originals.forEach((original, i) => {
      const target = copies[i] as SVGElement | undefined
      if (!target) return
      const computed = window.getComputedStyle(original)
      for (const prop of rule.props) {
        target.style.setProperty(prop, computed.getPropertyValue(prop))
      }
    })
  }

  // The invisible click targets would paint as opaque strokes once inlined.
  clone.querySelectorAll('.edge-hit, .rubber-band').forEach(el => el.remove())

  const serialized = new XMLSerializer().serializeToString(clone)
  const url = URL.createObjectURL(new Blob([serialized], { type: 'image/svg+xml;charset=utf-8' }))

  try {
    return await new Promise<Blob>((resolve, reject) => {
      const img = new Image()
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = width * 2
        canvas.height = height * 2
        const ctx = canvas.getContext('2d')
        if (!ctx) { reject(new Error('Canvas is unavailable')); return }
        ctx.scale(2, 2)
        ctx.drawImage(img, 0, 0, width, height)
        canvas.toBlob(
          blob => blob ? resolve(blob) : reject(new Error('Could not encode the diagram')),
          'image/png',
        )
      }
      img.onerror = () => reject(new Error('Could not rasterise the network diagram'))
      img.src = url
    })
  } finally {
    URL.revokeObjectURL(url)
  }
}

function figure(file: string, caption: string, width: string): string {
  return [
    '\\begin{figure}[htbp]',
    '\\centering',
    `\\includegraphics[width=${width}\\textwidth]{${file}}`,
    `\\caption{${caption}}`,
    '\\end{figure}',
    '',
  ].join('\n')
}

function buildTex(input: LatexBundleInput, images: string[]): string {
  const lines: string[] = [
    '\\documentclass[11pt,a4paper]{article}',
    '\\usepackage[utf8]{inputenc}',
    '\\usepackage[T1]{fontenc}',
    '\\usepackage{amsmath,amssymb}',
    '\\usepackage{graphicx}',
    '\\usepackage[margin=2.5cm]{geometry}',
    '\\usepackage{hyperref}',
    '',
    `\\title{${esc(input.modelName)}}`,
    '\\date{\\today}',
    '',
    '\\begin{document}',
    '\\maketitle',
    '',
    '\\section{Model}',
    '',
  ]

  if (images.includes('network.png')) {
    lines.push(figure('network.png', 'Transport network of the model', '0.85'))
  }

  lines.push('\\section{Equations}', '')

  for (const section of input.sections) {
    if (!section.items.length) continue
    lines.push(`\\subsection{${esc(section.title)}}`, '')

    // The ODE system reads best as one aligned block; everything else gets a
    // numbered equation per item so individual fluxes can be cited.
    if (section.title === 'ODE system') {
      lines.push('\\begin{align}')
      section.items.forEach((item, i) => {
        lines.push(`  ${item.latex}${i < section.items.length - 1 ? ' \\\\' : ''}`)
      })
      lines.push('\\end{align}', '')
      continue
    }

    for (const item of section.items) {
      if (item.label) {
        const sub = item.sublabel ? ` (${esc(item.sublabel)})` : ''
        lines.push(`\\paragraph{${esc(item.label)}${sub}}`)
      }
      lines.push('\\begin{equation}', `  ${item.latex}`, '\\end{equation}')
      if (item.params) lines.push(`\\noindent where $${item.params}$`, '')
    }
    lines.push('')
  }

  if (input.legend.length) {
    lines.push('\\subsection{Flow legend}', '', '\\begin{itemize}')
    for (const item of input.legend) {
      lines.push(`  \\item $${item.latex}$ --- ${esc(item.text)}`)
    }
    lines.push('\\end{itemize}', '')
  }

  lines.push('\\section{Simulation results}', '')
  if (images.includes('states.png')) {
    lines.push(figure('states.png', 'Compartment states over time', '0.9'))
  }
  if (images.includes('fluxes.png')) {
    lines.push(figure('fluxes.png', 'Energy fluxes over time', '0.9'))
  }
  if (images.includes('sankey.png')) {
    lines.push(figure('sankey.png', 'Sankey diagram of mean energy flows', '0.85'))
  }

  lines.push('\\end{document}', '')
  return lines.join('\n')
}

/** Build the export zip. Individual images are skipped if they fail to render. */
export async function buildLatexBundle(input: LatexBundleInput): Promise<Blob> {
  const zip = new JSZip()
  const images: string[] = []

  if (input.networkSvg) {
    try {
      zip.file('network.png', await svgToPng(input.networkSvg, 800, 600))
      images.push('network.png')
    } catch {
      // A missing diagram should not cost the user the rest of the bundle.
    }
  }

  for (const [name, blob] of [
    ['states.png', input.charts.states],
    ['fluxes.png', input.charts.fluxes],
    ['sankey.png', input.charts.sankey],
  ] as const) {
    if (blob) {
      zip.file(name, blob)
      images.push(name)
    }
  }

  zip.file('model.tex', buildTex(input, images))
  return zip.generateAsync({ type: 'blob' })
}
