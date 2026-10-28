/**
 * Single-letter shortcuts on a window listener must yield to everything else
 * a key can mean. The KG Builder review keys (y confirm, n reject) fired from
 * a focused button or tab, where the user meant that control, and with
 * Ctrl/Cmd/Alt held, where they meant a browser or OS shortcut — each time
 * sending an unannounced PUT that changed a relation's status (F-027).
 */

const INTERACTIVE_TAGS = new Set(['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'A', 'SUMMARY', 'OPTION'])
const INTERACTIVE_ROLES = new Set([
  'button', 'link', 'tab', 'checkbox', 'radio', 'switch', 'menuitem', 'menuitemcheckbox',
  'menuitemradio', 'option', 'slider', 'spinbutton', 'textbox', 'combobox', 'searchbox', 'treeitem',
])

/** True when the key belongs to the focused element rather than to a page shortcut. */
export function targetsAControl(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  if (INTERACTIVE_TAGS.has(target.tagName)) return true
  const role = target.getAttribute('role')
  return role !== null && INTERACTIVE_ROLES.has(role)
}

/**
 * Whether a keydown may trigger a page-level single-key shortcut: no
 * Ctrl/Cmd/Alt, not already handled, not aimed at a control or text field,
 * and (for keys that act, as opposed to move) not auto-repeat from a held key.
 */
export function isPlainShortcut(ev: KeyboardEvent, { allowRepeat = false } = {}): boolean {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return false
  if (ev.defaultPrevented || ev.isComposing) return false
  if (ev.repeat && !allowRepeat) return false
  return !targetsAControl(ev.target)
}
