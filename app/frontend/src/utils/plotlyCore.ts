/**
 * A minimal Plotly bundle for the tDEB result charts.
 *
 * The prebuilt `plotly.js-dist-min` carries every trace type Plotly supports —
 * around 1.2 MB gzipped. The tDEB charts use exactly two (line plots and a
 * Sankey diagram), so this registers just those against Plotly's core.
 *
 * Import Plotly from here rather than from `plotly.js` directly; pulling in the
 * package root would defeat the point and re-bundle everything.
 */
// @ts-expect-error — plotly.js/lib/* ships no type declarations
import Plotly from 'plotly.js/lib/core'
// @ts-expect-error — plotly.js/lib/* ships no type declarations
import scatter from 'plotly.js/lib/scatter'
// @ts-expect-error — plotly.js/lib/* ships no type declarations
import sankey from 'plotly.js/lib/sankey'

Plotly.register([scatter, sankey])

export type PlotData = Record<string, unknown>
export type PlotLayout = Record<string, unknown>
export type PlotConfig = Record<string, unknown>

interface PlotlyApi {
  newPlot(root: HTMLElement, data: PlotData[], layout?: PlotLayout, config?: PlotConfig): Promise<HTMLElement>
  react(root: HTMLElement, data: PlotData[], layout?: PlotLayout, config?: PlotConfig): Promise<HTMLElement>
  relayout(root: HTMLElement, layout: PlotLayout): Promise<HTMLElement>
  extendTraces(root: HTMLElement, update: Record<string, unknown[]>, indices: number[]): Promise<HTMLElement>
  purge(root: HTMLElement): void
  toImage(root: HTMLElement, opts: { format: string; width: number; height: number; scale?: number }): Promise<string>
}

export default Plotly as PlotlyApi
