/**
 * Markdown → sanitised HTML for chat transcripts.
 *
 * Two copies of renderMarkdown existed (chat and the admin chat viewer); only
 * one highlighted code, and it did so by calling `marked.use()` on the global
 * instance, so the admin viewer picked up the chat renderer by accident of
 * import order. This module owns one private `Marked` instance instead.
 *
 * highlight.js is imported as core plus an explicit language list. The bare
 * `import hljs from 'highlight.js'` registers all ~190 grammars and was most of
 * the 964 kB markdown-vendor chunk. A fence in an unlisted language renders as
 * plaintext — still a readable code block, just not coloured.
 */
import { Marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import cpp from 'highlight.js/lib/languages/cpp'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import julia from 'highlight.js/lib/languages/julia'
import latex from 'highlight.js/lib/languages/latex'
import markdown from 'highlight.js/lib/languages/markdown'
import matlab from 'highlight.js/lib/languages/matlab'
import plaintext from 'highlight.js/lib/languages/plaintext'
import python from 'highlight.js/lib/languages/python'
import r from 'highlight.js/lib/languages/r'
import shell from 'highlight.js/lib/languages/shell'
import sql from 'highlight.js/lib/languages/sql'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

// The languages a DEB modelling conversation plausibly contains. Aliases
// (py, sh, js, html, tex, yml, …) come with each grammar.
const LANGUAGES = {
  bash, cpp, javascript, json, julia, latex, markdown, matlab,
  plaintext, python, r, shell, sql, xml, yaml,
}
for (const [name, grammar] of Object.entries(LANGUAGES)) {
  hljs.registerLanguage(name, grammar)
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

const md = new Marked({
  renderer: {
    code(code: string, infostring?: string) {
      const requested = infostring?.split(/\s+/)[0] || ''
      const language = requested && hljs.getLanguage(requested) ? requested : 'plaintext'
      const highlighted = hljs.highlight(code, { language }).value
      return (
        `<div class="code-block-wrapper">` +
        `<div class="code-block-header"><span class="code-lang">${escapeHtml(language)}</span>` +
        `<button type="button" class="code-copy-btn" data-code="${escapeHtml(code)}" aria-label="Copy code">Copy</button></div>` +
        `<pre><code class="hljs language-${escapeHtml(language)}">${highlighted}</code></pre></div>`
      )
    },
  },
})

/** Render untrusted markdown (model output, user text) to sanitised HTML. */
export function renderMarkdown(text: string | null | undefined): string {
  if (!text) return ''
  return DOMPurify.sanitize(md.parse(text, { async: false }) as string)
}
