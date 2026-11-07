<template>
  <div class="wiki" :lang="lang">
    <aside id="wiki-nav" class="wiki-nav" :class="{ open: navOpen }">
      <div class="nav-head">
        <div class="nav-title">
          <router-link :to="{ name: 'wiki-home', params: { lang } }" class="brand">{{ ui.title }}</router-link>
          <div class="lang" role="group" :aria-label="ui.language">
            <button
              v-for="l in WIKI_LANGS"
              :key="l"
              type="button"
              :aria-pressed="l === lang"
              @click="switchLang(l)"
            >{{ l.toUpperCase() }}</button>
          </div>
          <button type="button" class="nav-close" :aria-label="ui.close" @click="navOpen = false">✕</button>
        </div>
        <p class="sub">{{ ui.sub }}</p>
        <form role="search" @submit.prevent="runSearch">
          <input
            v-model="query"
            class="search"
            type="search"
            :placeholder="ui.search"
            :aria-label="ui.search"
            @input="searchSoon"
          >
        </form>
      </div>

      <nav class="nav-body" :aria-label="ui.contents">
        <router-link
          v-for="p in pins"
          :key="p.key"
          :to="p.to"
          class="pin"
          :class="{ active: p.active }"
        >
          <span class="pin-icon" aria-hidden="true">{{ p.icon }}</span>{{ p.label }}
        </router-link>

        <div v-for="g in groups" :key="g.section" class="grp">
          <button
            type="button"
            class="grp-head"
            :aria-expanded="!isClosed(g)"
            @click="toggleGroup(g.section)"
          >
            <span class="caret" :class="{ closed: isClosed(g) }" aria-hidden="true">▾</span>
            {{ sectionLabel(g.section, lang) }}
            <span class="count">{{ g.notes.length }}</span>
          </button>
          <ul v-show="!isClosed(g)">
            <li v-for="n in g.notes" :key="n.id">
              <router-link :to="noteRoute(n.id)" :class="{ active: view === 'note' && n.id === noteId }">
                {{ titleIn(n.title, lang) }}
                <span v-if="lang === 'en' && n.en_status === 'missing'" class="hrtag" :title="ui.enMissing">{{ ui.hrOnly }}</span>
              </router-link>
            </li>
          </ul>
        </div>
      </nav>
    </aside>

    <section ref="mainEl" class="wiki-main" :class="{ 'graph-mode': view === 'graph' }">
      <button
        type="button"
        class="contents-toggle"
        aria-controls="wiki-nav"
        :aria-expanded="navOpen"
        @click="navOpen = !navOpen"
      >☰ {{ ui.contents }}</button>

      <p v-if="error" class="state">{{ error }}</p>

      <WikiGraph
        v-else-if="view === 'graph' && graph"
        :graph="graph"
        :lang="lang"
        :titles="titles"
        @open="id => router.push(noteRoute(id))"
      />

      <div v-else-if="view === 'search'" class="page">
        <h1 class="title">{{ ui.results(hits.length) }}</h1>
        <p v-if="!hits.length && !loading" class="state">{{ ui.noResults }}</p>
        <ul class="list">
          <li v-for="h in hits" :key="h.id">
            <router-link class="t" :to="noteRoute(h.id)">{{ titleIn(h.title, lang) }}</router-link>
            <!-- eslint-disable-next-line vue/no-v-html -- escaped by highlight() -->
            <div class="snip"><span class="muted">{{ sectionLabel(h.section, lang) }} · </span><span v-html="highlight(h.snippet, terms, fold)" /></div>
          </li>
        </ul>
      </div>

      <div v-else-if="view === 'tag'" class="page">
        <div class="crumbs">{{ ui.tag }}</div>
        <h1 class="title">#{{ tagLabel(tag, lang) }}</h1>
        <p class="meta-line">{{ ui.notesIn(tagged.length) }}</p>
        <ul class="list">
          <li v-for="n in tagged" :key="n.id">
            <router-link class="t" :to="noteRoute(n.id)">{{ titleIn(n.title, lang) }}</router-link>
            <div class="snip muted">{{ sectionLabel(n.section, lang) }}</div>
          </li>
        </ul>
      </div>

      <article v-else-if="note" class="page">
        <template v-if="view === 'home'">
          <div class="crumbs">{{ ui.built }} {{ builtLabel }}</div>
          <h1 class="title">{{ ui.title }}</h1>
          <p class="lede">{{ ui.lede }}</p>
          <div class="stats">
            <div class="stat"><b>{{ index?.notes.length ?? 0 }}</b><span>{{ ui.statNotes }}</span></div>
            <div class="stat"><b>{{ totals.links }}</b><span>{{ ui.statLinks }}</span></div>
            <div class="stat"><b>{{ totals.claims }}</b><span>{{ ui.statClaims }}</span></div>
            <div class="stat"><b>{{ totals.sources }}</b><span>{{ ui.statSources }}</span></div>
          </div>
          <div class="claims">
            <b>{{ ui.claimsTitle }}</b>
            <div class="bar" aria-hidden="true">
              <span
                v-for="b in totals.badges"
                :key="b[0]"
                :class="`badge-${b[0]}`"
                :style="{ flex: b[1] }"
              />
            </div>
            <div class="legend">
              <span v-for="b in totals.badges" :key="b[0]">
                <code :class="['badge', `badge-${b[0]}`]">{{ b[0] }}</code>{{ badgeLabel(b[0], lang) }} · <b>{{ b[1] }}</b>
              </span>
            </div>
            <p class="rule">{{ ui.claimsRule }}</p>
          </div>
        </template>
        <template v-else>
          <div class="crumbs">
            <router-link :to="{ name: 'wiki-home', params: { lang } }">{{ ui.home }}</router-link>
            › {{ sectionLabel(note.section, lang) }}
          </div>
          <h1 class="title">{{ titleIn(note.title, lang) }}</h1>
          <div class="meta-line">
            <span class="chip">{{ typeLabel(note.type, lang) }}</span>
            <router-link
              v-for="t in note.tags.filter(t => t !== 'advandeb')"
              :key="t"
              class="chip"
              :to="{ name: 'wiki-tag', params: { lang, tag: t } }"
            >#{{ tagLabel(t, lang) }}</router-link>
            <span v-if="note.updated">{{ ui.updated }} {{ note.updated }}</span>
          </div>
          <p v-if="lang === 'en' && note.md.en === null" class="banner">{{ ui.enMissing }}</p>
          <p v-else-if="lang === 'en' && note.en_status === 'outdated'" class="banner warn">{{ ui.enOutdated }}</p>
          <p v-if="note.tier === 'internal'" class="banner">{{ ui.internalBanner }}</p>
        </template>

        <!-- eslint-disable-next-line vue/no-v-html -- sanitised by renderWikiHtml (DOMPurify) -->
        <div
          class="prose"
          :class="badgeFilterClasses"
          :lang="lang === 'en' && note.md.en === null ? 'hr' : lang"
          @click="onProseClick"
          v-html="noteHtml"
        />

        <aside v-if="!wide" class="wiki-ctx inline">
          <WikiContextPanel />
        </aside>
      </article>

      <p v-else-if="loading" class="state">{{ ui.loading }}</p>
    </section>

    <aside v-if="wide && note && (view === 'note' || view === 'home')" class="wiki-ctx">
      <WikiContextPanel />
    </aside>

    <div v-if="lightbox" class="lightbox" role="dialog" aria-modal="true" @click="lightbox = null">
      <img :src="lightbox" alt="">
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import WikiGraph from '@/components/wiki/WikiGraph.vue'
import {
  getWikiGraph, getWikiIndex, getWikiNote, searchWiki,
  type WikiGraph as WikiGraphData, type WikiHit, type WikiIndex, type WikiLang, type WikiNote,
} from '@/utils/wikiApi'
import { highlight, renderWikiHtml } from '@/utils/wikiRender'
import {
  BADGE_ORDER, SECTION_COLOR, UI, WIKI_LANGS, badgeLabel, fold, rememberLang, sectionLabel,
  tagLabel, titleIn, typeLabel,
} from '@/utils/wikiText'

const HOME_NOTE = 'Početna'
const HUB_NOTE = 'Sažetak radionice'
const QUESTIONS_NOTE = 'Otvorena pitanja'
const PINNED_SECTIONS = new Set(['home', 'hub'])

const route = useRoute()
const router = useRouter()

const lang = computed<WikiLang>(() => (route.params.lang === 'en' ? 'en' : 'hr'))
const ui = computed(() => UI[lang.value])
const view = computed(() => {
  switch (route.name) {
    case 'wiki-note': return 'note'
    case 'wiki-graph': return 'graph'
    case 'wiki-search': return 'search'
    case 'wiki-tag': return 'tag'
    default: return 'home'
  }
})
const noteId = computed(() => (view.value === 'note' ? String(route.params.id ?? '') : HOME_NOTE))
const tag = computed(() => String(route.params.tag ?? ''))

const index = shallowRef<WikiIndex | null>(null)
const note = shallowRef<WikiNote | null>(null)
const graph = shallowRef<WikiGraphData | null>(null)
const hits = shallowRef<WikiHit[]>([])
const error = ref('')
const loading = ref(false)
const navOpen = ref(false)
const lightbox = ref<string | null>(null)
const query = ref(typeof route.query.q === 'string' ? route.query.q : '')
const mainEl = ref<HTMLElement | null>(null)
const badgeFilter = ref<Set<string>>(new Set())

// The context column sits beside the text on wide screens and under it otherwise.
const wideQuery = typeof window !== 'undefined' ? window.matchMedia('(min-width: 1180px)') : null
const wide = ref(wideQuery?.matches ?? true)
const onWide = (e: MediaQueryListEvent) => { wide.value = e.matches }

function noteRoute(id: string) {
  return { name: 'wiki-note', params: { lang: lang.value, id } }
}

function describe(err: unknown): string {
  const status = (err as { response?: { status?: number } })?.response?.status
  if (status === 404) return ui.value.notFound
  if (status === 503) return ui.value.unavailable
  return (err as Error)?.message || 'Error'
}

// --- data ---------------------------------------------------------------- //

const byId = computed(() => new Map((index.value?.notes ?? []).map(n => [n.id, n])))
const titles = computed(() => Object.fromEntries(
  (index.value?.notes ?? []).map(n => [n.id, titleIn(n.title, lang.value)])))
const titleOf = (id: string) => titles.value[id] ?? id

const collator = computed(() => new Intl.Collator(lang.value, { sensitivity: 'base', numeric: true }))

const groups = computed(() => {
  if (!index.value) return []
  return index.value.sections
    .filter(s => !PINNED_SECTIONS.has(s))
    .map(section => {
      const notes = index.value!.notes.filter(n => n.section === section)
      notes.sort(section === 'journal'
        ? (a, b) => a.id.localeCompare(b.id)
        : (a, b) => collator.value.compare(titleIn(a.title, lang.value), titleIn(b.title, lang.value)))
      return { section, notes }
    })
    .filter(g => g.notes.length)
})

const CLOSED_KEY = 'wiki.closed'
const closed = ref<Set<string>>(new Set(readClosed()))
function readClosed(): string[] {
  try { return JSON.parse(localStorage.getItem(CLOSED_KEY) ?? '["drive","maps"]') } catch { return ['drive', 'maps'] }
}
function isClosed(g: { section: string; notes: { id: string }[] }) {
  // A group never hides the note being read.
  return closed.value.has(g.section) && !(view.value === 'note' && g.notes.some(n => n.id === noteId.value))
}
function toggleGroup(section: string) {
  const next = new Set(closed.value)
  if (next.has(section)) next.delete(section)
  else next.add(section)
  closed.value = next
  try { localStorage.setItem(CLOSED_KEY, JSON.stringify([...next])) } catch { /* fine */ }
}

interface Pin {
  key: string
  icon: string
  label: string
  to: RouteLocationRaw
  active: boolean
}

const pins = computed(() => {
  const l = lang.value
  const list: Pin[] = [
    { key: 'home', icon: '⌂', label: ui.value.home, to: { name: 'wiki-home', params: { lang: l } }, active: view.value === 'home' },
  ]
  if (byId.value.has(HUB_NOTE)) {
    list.push({ key: 'hub', icon: '◎', label: ui.value.hub, to: noteRoute(HUB_NOTE), active: view.value === 'note' && noteId.value === HUB_NOTE })
  }
  list.push({ key: 'graph', icon: '✱', label: ui.value.graph, to: { name: 'wiki-graph', params: { lang: l } }, active: view.value === 'graph' })
  if (byId.value.has(QUESTIONS_NOTE)) {
    list.push({ key: 'q', icon: '?', label: ui.value.questions, to: noteRoute(QUESTIONS_NOTE), active: view.value === 'note' && noteId.value === QUESTIONS_NOTE })
  }
  return list
})

const totals = computed(() => {
  const notes = index.value?.notes ?? []
  const sum: Record<string, number> = {}
  let claims = 0
  for (const n of notes) {
    for (const [b, c] of Object.entries(n.badges)) { sum[b] = (sum[b] ?? 0) + c; claims += c }
  }
  return {
    links: notes.reduce((a, n) => a + n.n_links, 0),
    claims,
    sources: notes.filter(n => n.section === 'literature').length,
    badges: BADGE_ORDER.filter(b => sum[b]).map(b => [b, sum[b]] as [string, number]),
  }
})

const builtLabel = computed(() => (index.value?.built ?? '').replace('T', ' '))

const tagged = computed(() => (index.value?.notes ?? [])
  .filter(n => n.tags.includes(tag.value))
  .sort((a, b) => collator.value.compare(titleIn(a.title, lang.value), titleIn(b.title, lang.value))))

const terms = computed(() => fold(String(route.query.q ?? '')).split(/\s+/).filter(Boolean))

const noteHtml = computed(() => {
  const n = note.value
  if (!n) return ''
  const md = (lang.value === 'en' && n.md.en !== null) ? n.md.en : n.md.hr
  return renderWikiHtml(md, lang.value, n.assets)
})

const badgeFilterClasses = computed(() => {
  if (!badgeFilter.value.size) return {}
  return { filtering: true, ...Object.fromEntries([...badgeFilter.value].map(b => [`f-${b}`, true])) }
})

// --- loading ------------------------------------------------------------- //

async function load() {
  error.value = ''
  badgeFilter.value = new Set()
  loading.value = true
  try {
    index.value ??= await getWikiIndex()
    if (view.value === 'note' || view.value === 'home') {
      const id = noteId.value
      const n = await getWikiNote(id)
      if (id === noteId.value) {
        note.value = n
        document.title = view.value === 'home' ? `${ui.value.title} · AdvanDEB` : `${titleIn(n.title, lang.value)} · Wiki · AdvanDEB`
        mainEl.value?.scrollTo({ top: 0 })
      }
    } else if (view.value === 'graph') {
      graph.value ??= await getWikiGraph()
    } else if (view.value === 'search') {
      const q = String(route.query.q ?? '').trim()
      hits.value = q ? await searchWiki(q, lang.value) : []
    }
  } catch (err) {
    note.value = null
    error.value = describe(err)
  } finally {
    loading.value = false
  }
}

watch(() => [route.name, route.params.id, route.params.tag, route.query.q, lang.value], load, { immediate: true })
watch(lang, l => rememberLang(l), { immediate: true })
watch(() => route.fullPath, () => { navOpen.value = false })

onMounted(() => wideQuery?.addEventListener('change', onWide))
onBeforeUnmount(() => wideQuery?.removeEventListener('change', onWide))

// --- actions ------------------------------------------------------------- //

function switchLang(l: WikiLang) {
  if (l === lang.value) return
  router.replace({ name: route.name ?? 'wiki-home', params: { ...route.params, lang: l }, query: route.query })
}

let searchTimer: ReturnType<typeof setTimeout> | undefined
function runSearch() {
  clearTimeout(searchTimer)
  const q = query.value.trim()
  if (!q) return
  const target = { name: 'wiki-search', params: { lang: lang.value }, query: { q } }
  if (view.value === 'search') router.replace(target)
  else router.push(target)
}
function searchSoon() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(runSearch, 300)
}

function onProseClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  const a = target.closest('a')
  if (a?.classList.contains('asset-link')) {
    e.preventDefault()
    lightbox.value = note.value?.assets[a.dataset.asset ?? ''] ?? null
    return
  }
  if (target.tagName === 'IMG' && target.closest('figure.embed')) {
    lightbox.value = (target as HTMLImageElement).src
    return
  }
  // Let the browser have modified clicks (new tab, new window): the href is a real path.
  if (!a || !a.dataset.id || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
  e.preventDefault()
  router.push(noteRoute(a.dataset.id))
}

function toggleBadge(b: string) {
  const next = new Set(badgeFilter.value)
  if (next.has(b)) next.delete(b)
  else next.add(b)
  badgeFilter.value = next
}

// --- the context column, rendered beside or under the text ---------------- //

function localGraph(n: WikiNote) {
  const nb = [...new Set([...n.in, ...n.out])].slice(0, 28)
  const W = 248
  const H = 210
  const cx = W / 2
  const cy = H / 2
  const pts = nb.map((id, i) => {
    const a = (i / nb.length) * Math.PI * 2 - Math.PI / 2
    const r = nb.length > 14 ? (i % 2 ? 88 : 62) : 80
    return { id, x: cx + Math.cos(a) * r * 1.15, y: cy + Math.sin(a) * r * 0.9 }
  })
  const section = (id: string) => byId.value.get(id)?.section ?? 'other'
  return h('svg', { class: 'local', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': ui.value.local }, [
    ...pts.map(p => h('line', { x1: cx, y1: cy, x2: p.x, y2: p.y })),
    ...pts.map(p => h(RouterLink, { to: noteRoute(p.id), custom: true }, {
      default: ({ href, navigate }: { href: string; navigate: (e: MouseEvent) => void }) =>
        h('a', { href, onClick: navigate }, [
          h('circle', { cx: p.x, cy: p.y, r: 5, fill: SECTION_COLOR[section(p.id)] ?? '#9ca3af' }, [h('title', titleOf(p.id))]),
        ]),
    })),
    h('circle', { class: 'self', cx, cy, r: 8, fill: SECTION_COLOR[n.section] ?? '#9ca3af' }),
  ])
}

function linkList(ids: string[]) {
  if (!ids.length) return h('p', { class: 'empty' }, ui.value.none)
  const sorted = [...ids].sort((a, b) => collator.value.compare(titleOf(a), titleOf(b)))
  return h('ul', sorted.map(id => h('li', [
    h(RouterLink, { to: noteRoute(id) }, () => [
      titleOf(id),
      h('span', { class: 'sec' }, ` · ${sectionLabel(byId.value.get(id)?.section ?? 'other', lang.value)}`),
    ]),
  ])))
}

const WikiContextPanel = defineComponent({
  name: 'WikiContextPanel',
  setup() {
    return () => {
      const n = note.value
      if (!n) return null
      const badges = BADGE_ORDER.filter(b => n.badges[b])
      return [
        badges.length ? [
          h('h2', ui.value.claims),
          h('div', { class: 'badgebar' }, badges.map(b => h('button', {
            type: 'button',
            title: badgeLabel(b, lang.value),
            'aria-pressed': badgeFilter.value.has(b),
            onClick: () => toggleBadge(b),
          }, [h('code', { class: ['badge', `badge-${b}`] }, b), String(n.badges[b])]))),
          h('p', { class: 'hint' }, ui.value.filterHint),
        ] : null,
        h('h2', ui.value.local),
        localGraph(n),
        h('h2', `${ui.value.in} (${n.in.length})`),
        linkList(n.in),
        h('h2', `${ui.value.out} (${n.out.length})`),
        linkList(n.out),
        h('h2', ui.value.details),
        h('p', { class: 'muted' }, [
          n.created ? `${ui.value.created} ${n.created}` : '',
          n.updated ? ` · ${ui.value.updated} ${n.updated}` : '',
        ]),
        n.aliases.length ? h('p', { class: 'muted' }, `${ui.value.aliases}: ${n.aliases.join(' · ')}`) : null,
      ]
    }
  },
})
</script>

<style scoped>
.wiki {
  --b-R: #b45309; --b-D: #475569; --b-T: #15803d; --b-E: #0f766e;
  --b-P: #7c3aed; --b-S: #4338ca; --b-H: #be123c; --b-I: #6b7280;
  --wiki-serif: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 290px;
  background: var(--app-bg);
  color: var(--app-ink);
}

/* --- navigation column --- */
.wiki-nav {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--app-line);
  background: var(--app-bg-2);
}
.nav-head { padding: 14px 14px 10px; border-bottom: 1px solid var(--app-line); }
.nav-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.brand { font: 600 1.05rem/1.2 var(--wiki-serif); color: var(--app-ink); text-decoration: none; }
.lang { display: inline-flex; border: 1px solid var(--app-line-2); border-radius: 999px; overflow: hidden; flex-shrink: 0; }
.lang button {
  border: 0; background: transparent; padding: 2px 10px; font-size: 0.72rem; font-weight: 700;
  color: var(--app-ink-3); cursor: pointer;
}
.lang button[aria-pressed="true"] { background: var(--app-ink); color: var(--app-bg); }
.sub { margin: 4px 0 10px; font-size: 0.75rem; color: var(--app-ink-3); }
.search {
  width: 100%; padding: 6px 10px; border: 1px solid var(--app-line-2); border-radius: var(--app-radius-lg);
  background: var(--app-bg); font: inherit; font-size: 0.85rem;
}
.search:focus { outline: 2px solid var(--app-primary-line); border-color: var(--app-primary); }
.nav-body { flex: 1; overflow-y: auto; padding: 8px 6px 24px; }
.pin {
  display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: var(--app-radius);
  color: var(--app-ink); text-decoration: none; font-size: 0.875rem;
}
.pin:hover { background: var(--app-bg-3); }
.pin.active { background: var(--app-primary-soft); color: var(--app-primary-ink); }
.pin-icon { width: 18px; text-align: center; color: var(--app-ink-3); }
.grp { margin-top: 6px; }
.grp-head {
  width: 100%; display: flex; align-items: center; gap: 6px; border: 0; background: none; cursor: pointer;
  padding: 6px 10px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--app-ink-3); text-align: left;
}
.grp-head .count { margin-left: auto; font-weight: 500; letter-spacing: 0; }
.caret { display: inline-block; transition: transform 0.15s; }
.caret.closed { transform: rotate(-90deg); }
.grp ul { list-style: none; margin: 0; padding: 0; }
.grp li a {
  display: flex; gap: 6px; align-items: baseline; padding: 4px 10px 4px 26px; border-radius: var(--app-radius);
  color: var(--app-ink-2); text-decoration: none; font-size: 0.83rem; line-height: 1.35;
}
.grp li a:hover { background: var(--app-bg-3); color: var(--app-ink); }
.grp li a.active { background: var(--app-primary-soft); color: var(--app-primary-ink); }
.hrtag {
  margin-left: auto; flex-shrink: 0; font-size: 0.62rem; color: var(--app-ink-3);
  border: 1px solid var(--app-line-2); border-radius: 3px; padding: 0 3px;
}

/* --- main column --- */
.wiki-main { overflow-y: auto; min-width: 0; display: flex; flex-direction: column; }
.wiki-main.graph-mode { overflow: hidden; }
.contents-toggle, .nav-close { display: none; }
.state { padding: 2rem; color: var(--app-ink-3); }
.page { width: 100%; max-width: 780px; margin: 0 auto; padding: 28px 40px 80px; }
.crumbs { font-size: 0.75rem; color: var(--app-ink-3); }
.crumbs a { color: var(--app-ink-3); text-decoration: none; }
.crumbs a:hover { color: var(--app-primary-strong); }
.title { font: 600 1.9rem/1.2 var(--wiki-serif); margin: 8px 0 6px; text-wrap: balance; }
.meta-line { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 0.78rem; color: var(--app-ink-3); margin: 0 0 18px; }
.chip {
  font-size: 0.72rem; padding: 1px 8px; border-radius: 999px; background: var(--app-bg-3); color: var(--app-ink-2);
  border: 1px solid var(--app-line); text-decoration: none;
}
a.chip:hover { border-color: var(--app-primary); color: var(--app-primary-strong); }
.banner {
  border: 1px solid var(--app-line); background: var(--app-bg-2); border-radius: var(--app-radius-lg);
  padding: 8px 12px; font-size: 0.83rem; color: var(--app-ink-2); margin: 0 0 16px;
}
.banner.warn { border-color: var(--app-warning); background: var(--app-warning-soft); color: var(--app-warning-ink); }
.muted { color: var(--app-ink-3); }

.lede { font: 1.1rem/1.6 var(--wiki-serif); color: var(--app-ink-2); margin: 0 0 18px; }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 18px; }
.stat { border: 1px solid var(--app-line); border-radius: var(--app-radius-xl); padding: 10px 12px; }
.stat b { display: block; font: 600 1.5rem/1.1 var(--wiki-serif); font-variant-numeric: tabular-nums; }
.stat span { font-size: 0.75rem; color: var(--app-ink-3); }
.claims { border: 1px solid var(--app-line); border-radius: var(--app-radius-xl); padding: 12px 14px; margin-bottom: 26px; font-size: 0.85rem; }
.claims .bar { display: flex; gap: 2px; height: 12px; border-radius: 3px; overflow: hidden; margin: 8px 0; }
.claims .bar span { display: block; height: 100%; }
.claims .legend { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--app-ink-2); }
.claims .legend code { margin-right: 4px; vertical-align: 0; }
.claims .rule { margin: 10px 0 0; color: var(--app-ink-3); font-size: 0.8rem; line-height: 1.5; }

.list { list-style: none; padding: 0; margin: 0; }
.list li { padding: 10px 0; border-bottom: 1px solid var(--app-line); }
.list .t { font: 600 1rem var(--wiki-serif); color: var(--app-ink); text-decoration: none; }
.list .t:hover { color: var(--app-primary-strong); }
.snip { font-size: 0.85rem; color: var(--app-ink-2); margin-top: 2px; }
.snip :deep(mark) { background: var(--app-primary-soft-2); color: inherit; border-radius: 2px; }

/* badge colours (also used by the home page bar and legend) */
.badge-R { background: var(--b-R); } .badge-D { background: var(--b-D); } .badge-T { background: var(--b-T); }
.badge-E { background: var(--b-E); } .badge-P { background: var(--b-P); } .badge-S { background: var(--b-S); }
.badge-H { background: var(--b-H); } .badge-I { background: var(--b-I); }
code.badge, .prose :deep(code.badge), .wiki-ctx :deep(code.badge) {
  display: inline-block; width: 19px; padding: 3px 0; border-radius: 4px; color: #fff; text-align: center;
  font: 700 11px/1 ui-sans-serif, system-ui, sans-serif; vertical-align: 2px; cursor: help;
}
.prose :deep(code.badge-R), .wiki-ctx :deep(code.badge-R) { background: var(--b-R); }
.prose :deep(code.badge-D), .wiki-ctx :deep(code.badge-D) { background: var(--b-D); }
.prose :deep(code.badge-T), .wiki-ctx :deep(code.badge-T) { background: var(--b-T); }
.prose :deep(code.badge-E), .wiki-ctx :deep(code.badge-E) { background: var(--b-E); }
.prose :deep(code.badge-P), .wiki-ctx :deep(code.badge-P) { background: var(--b-P); }
.prose :deep(code.badge-S), .wiki-ctx :deep(code.badge-S) { background: var(--b-S); }
.prose :deep(code.badge-H), .wiki-ctx :deep(code.badge-H) { background: var(--b-H); }
.prose :deep(code.badge-I), .wiki-ctx :deep(code.badge-I) { background: var(--b-I); }

/* --- rendered note --- */
.prose { font: 1.05rem/1.65 var(--wiki-serif); }
.prose :deep(h2) { font: 600 1.25rem/1.3 var(--wiki-serif); margin: 30px 0 10px; padding-bottom: 4px; border-bottom: 1px solid var(--app-line); }
.prose :deep(h3) { font: 600 1.05rem/1.3 var(--wiki-serif); margin: 22px 0 8px; }
.prose :deep(p) { margin: 0 0 12px; }
.prose :deep(ul), .prose :deep(ol) { padding-left: 22px; margin: 0 0 14px; }
.prose :deep(li) { margin: 4px 0; }
.prose :deep(li::marker) { color: var(--app-ink-4); }
.prose :deep(code) { font: 0.82rem ui-monospace, Menlo, Consolas, monospace; background: var(--app-bg-3); padding: 1px 5px; border-radius: 4px; }
.prose :deep(pre) { background: var(--app-bg-3); padding: 12px; border-radius: var(--app-radius-lg); overflow-x: auto; }
.prose :deep(pre code) { background: none; padding: 0; }
.prose :deep(table) {
  display: block; overflow-x: auto; border-collapse: collapse; width: 100%; margin: 8px 0 18px;
  font: 0.875rem/1.45 ui-sans-serif, system-ui, sans-serif;
}
.prose :deep(th), .prose :deep(td) { border: 1px solid var(--app-line); padding: 6px 9px; text-align: left; vertical-align: top; }
.prose :deep(th) { background: var(--app-bg-2); font-weight: 600; }
.prose :deep(blockquote) { margin: 0 0 14px; padding: 4px 14px; border-left: 3px solid var(--app-line-2); color: var(--app-ink-2); }
.prose :deep(hr) { border: 0; border-top: 1px solid var(--app-line); margin: 24px 0; }
.prose :deep(a.wl) { color: var(--app-primary-strong); text-decoration: none; border-bottom: 1px solid var(--app-primary-line); }
.prose :deep(a.wl:hover) { background: var(--app-primary-soft); border-bottom-color: var(--app-primary-strong); }
.prose :deep(.wl.broken) { color: var(--app-danger-strong); border-bottom: 1px dashed var(--app-danger-line); }
.prose :deep(figure.embed) { margin: 14px 0; }
.prose :deep(figure.embed img) {
  max-width: 100%; max-height: 380px; object-fit: contain; border-radius: var(--app-radius);
  border: 1px solid var(--app-line); background: var(--app-bg-2); cursor: zoom-in;
}
.prose :deep(figcaption) { font: 0.75rem ui-sans-serif, system-ui, sans-serif; color: var(--app-ink-3); margin-top: 4px; }
.prose :deep(.callout) {
  border: 1px solid var(--app-line); border-left: 3px solid var(--app-primary); border-radius: var(--app-radius);
  padding: 8px 12px; margin: 0 0 14px; background: var(--app-primary-soft);
  font: 0.9rem/1.55 ui-sans-serif, system-ui, sans-serif; color: var(--app-ink-2);
}
.prose :deep(.callout-warning) { border-left-color: var(--app-warning); background: var(--app-warning-soft); }
.prose :deep(.callout-title) { font-weight: 600; color: var(--app-ink); margin-bottom: 2px; }
.prose :deep(.callout p:last-child) { margin-bottom: 0; }

/* badge filter: dim every tagged claim except the selected kinds */
.prose.filtering :deep(li[data-b]) { opacity: 0.22; }
.prose.f-R :deep(li[data-b="R"]), .prose.f-D :deep(li[data-b="D"]), .prose.f-T :deep(li[data-b="T"]),
.prose.f-E :deep(li[data-b="E"]), .prose.f-P :deep(li[data-b="P"]), .prose.f-S :deep(li[data-b="S"]),
.prose.f-H :deep(li[data-b="H"]), .prose.f-I :deep(li[data-b="I"]) { opacity: 1; }

/* --- context column --- */
.wiki-ctx { border-left: 1px solid var(--app-line); overflow-y: auto; padding: 18px 16px 40px; font-size: 0.8rem; }
.wiki-ctx.inline { border-left: 0; border-top: 1px solid var(--app-line); margin-top: 34px; padding: 10px 0 0; }
.wiki-ctx :deep(h2) {
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--app-ink-3); margin: 18px 0 8px;
}
.wiki-ctx :deep(h2:first-child) { margin-top: 0; }
.wiki-ctx :deep(ul) { list-style: none; margin: 0; padding: 0; }
.wiki-ctx :deep(li a) { display: block; padding: 3px 0; color: var(--app-ink-2); text-decoration: none; line-height: 1.35; }
.wiki-ctx :deep(li a:hover) { color: var(--app-primary-strong); }
.wiki-ctx :deep(.sec) { color: var(--app-ink-4); font-size: 0.7rem; }
.wiki-ctx :deep(.empty), .wiki-ctx :deep(.hint), .wiki-ctx :deep(.muted) { color: var(--app-ink-3); margin: 4px 0; }
.wiki-ctx :deep(.badgebar) { display: flex; flex-wrap: wrap; gap: 6px; }
.wiki-ctx :deep(.badgebar button) {
  display: inline-flex; align-items: center; gap: 5px; padding: 2px 7px 2px 3px; cursor: pointer;
  border: 1px solid var(--app-line-2); border-radius: var(--app-radius); background: var(--app-bg); font-size: 0.75rem;
}
.wiki-ctx :deep(.badgebar button[aria-pressed="true"]) { border-color: var(--app-ink-2); background: var(--app-bg-3); }
.wiki-ctx :deep(.badgebar code.badge) { vertical-align: 0; }
.wiki-ctx :deep(svg.local) {
  display: block; width: 100%; max-width: 320px; height: auto; background: var(--app-bg-2);
  border: 1px solid var(--app-line); border-radius: var(--app-radius-lg);
}
.wiki-ctx :deep(svg.local line) { stroke: var(--app-ink-4); stroke-opacity: 0.5; }
.wiki-ctx :deep(svg.local circle.self) { stroke: var(--app-ink); stroke-width: 2px; }

.lightbox {
  position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 16px;
  background: rgba(0, 0, 0, 0.82); cursor: zoom-out;
}
.lightbox img { max-width: 100%; max-height: 100%; border-radius: 4px; }

@media (max-width: 1179px) {
  .wiki { grid-template-columns: 240px minmax(0, 1fr); }
}
@media (max-width: 760px) {
  .wiki { grid-template-columns: minmax(0, 1fr); position: relative; }
  .wiki-nav { display: none; position: absolute; inset: 0; z-index: 20; }
  .wiki-nav.open { display: flex; }
  .contents-toggle {
    display: block; align-self: flex-start; margin: 10px 16px 0; padding: 4px 10px; font-size: 0.8rem;
    border: 1px solid var(--app-line-2); border-radius: var(--app-radius); background: var(--app-bg); cursor: pointer;
  }
  .nav-close {
    display: block; border: 0; background: none; font-size: 1rem; color: var(--app-ink-3); cursor: pointer;
  }
  .page { padding: 16px 16px 60px; }
  .title { font-size: 1.55rem; }
  .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
