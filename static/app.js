/* LEJ AI Session Archive Viewer: browser side.
   Talks only to this app's own JSON routes. Session text is always inserted
   as text nodes, never as HTML. */

const $ = id => document.getElementById(id);
const NARROW = matchMedia('(max-width: 900px)');
const APPS = {
  claude: ['Claude Code', 'CC'], codex: ['Codex', 'Cx'], history: ['Codex typed prompts', 'Cx'],
  t3: ['T3 Code', 'T3'], opencode: ['OpenCode', 'OC'], cursor: ['Cursor', 'Cu'], cursor_app: ['Cursor app', 'Cu'],
  grok: ['Grok', 'Gk'], gemini: ['Gemini CLI', 'Ge'], antigravity: ['Antigravity', 'Ag'],
  claude_ai: ['Claude.ai', 'Cl'], chatgpt: ['ChatGPT', 'GP'],
};
const FOLDER_HINTS = {
  claude: 'Point to the .claude folder, or the projects folder inside it.',
  codex: 'Point to the .codex folder, the one that holds sessions and archived_sessions.',
  t3: 'Point to the database file itself, statev2.sqlite. Copy its matching -wal file along with it.',
  opencode: 'Point to the OpenCode data folder, the one that holds opencode.db or storage.',
  cursor: 'Point to the .cursor folder, or the projects folder inside it.',
  grok: 'Point to the .grok folder.',
};
const state = {
  status: null, online: true, routed: false, lastListKey: '', lastListAt: 0,
  page: 0, total: 0, sessions: [], project: '', listRequest: 0,
  current: '', session: null, sessionRequest: 0, query: null, matchCount: 0,
  blockStart: 0, blockPage: 0, blockTotal: 0, run: null, day: '',
  found: null, config: null, saved: '', tagRows: [], expected: {}, firstRun: false, justSaved: false,
};

/* ---------- small helpers ---------- */

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k in el && k !== 'list') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  el.append(...kids.flat().filter(k => k != null && k !== false));
  return el;
}
const num = n => Number(n || 0).toLocaleString();
const plural = (n, one, many) => num(n) + ' ' + (n === 1 ? one : many || one + 's');
const appName = key => (APPS[key] || [key])[0];
const mark = key => h('span', { class: 'srcmark', title: appName(key), 'aria-hidden': 'true', text: (APPS[key] || [key.slice(0, 2)])[1] });
const date = s => { const d = s ? new Date(s) : null; return d && !isNaN(d) ? d : null; };
const fmt = (d, o) => d.toLocaleString(undefined, o);
const dayText = d => fmt(d, { month: 'short', day: 'numeric', year: 'numeric' });
const timeText = d => fmt(d, { hour: 'numeric', minute: '2-digit' });
const shortDate = d => fmt(d, d.getFullYear() === new Date().getFullYear() ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' });
function span(start, end) {
  const a = date(start), b = date(end);
  if (!a) return start || 'Unknown time';
  let text = dayText(a) + ', ' + timeText(a);
  if (!b || b - a < 60000) return text;
  text += ' to ' + (a.toDateString() === b.toDateString() ? timeText(b) : dayText(b) + ', ' + timeText(b));
  const mins = Math.round((b - a) / 60000);
  return text + ' (' + (mins < 90 ? mins + ' min' : mins < 2880 ? Math.round(mins / 60) + ' hours' : Math.round(mins / 1440) + ' days') + ')';
}
function took(seconds) {
  if (seconds == null) return '';
  return seconds < 90 ? Math.max(1, Math.round(seconds)) + ' seconds' : Math.round(seconds / 60) + ' minutes';
}
/* Titles are often a whole first prompt. Show the first line, cut to a sane length. */
function title(s) {
  const line = String(s.title || '').split('\n').map(x => x.trim()).find(Boolean) || 'Untitled session';
  return line.length > 150 ? line.slice(0, 147).trimEnd() + '…' : line;
}
function folder(path) {
  const parts = String(path || '').split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : '';
}
async function api(path) {
  const r = await fetch(path);
  const d = await r.json();
  if (!r.ok) throw Error(d.error || 'Could not read the archive.');
  return d;
}
async function post(path, data) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(friendly(d.error));
  return d;
}
function friendly(message) {
  const known = {
    'Wait for refresh to finish': 'Indexing is still running. Try again when it finishes.',
    'Expected exactly one conversations.json': "That ZIP doesn't look like an official export: it should hold one conversations.json file.",
    'Export does not match selected format': "That export doesn't match the app you picked. Try the other one.",
    'Source and app data folders must be separate': "That folder holds this app's own data. Pick the folder the sessions came from.",
    'Each tag needs a name and nonempty keyword list': 'Each tag needs a name and at least one keyword.',
    'Request too large': 'That is too much to save at once. Remove a few tags or folders and try again.',
  };
  if (!message) return 'Something went wrong. Check the Terminal window running the viewer.';
  if (/No such file|Errno 2/.test(message)) return 'No file was found at that path. Check the path and try again.';
  if (/not a zip/i.test(message)) return "That file isn't a ZIP. Point to the export ZIP exactly as it was downloaded.";
  return known[message] || message;
}

/* ---------- status: one honest line, details on click ---------- */

const total = () => Object.values(state.status?.counts || {}).reduce((a, b) => a + b, 0);
const expectedTotal = () => Object.values(state.expected).reduce((a, b) => a + b, 0);

async function pollStatus() {
  let d;
  try {
    d = await api('/api/status');
  } catch (e) {
    state.online = false;
    $('offline').hidden = false;
    $('status').dataset.state = 'error';
    $('statusText').textContent = 'Viewer not running';
    return setTimeout(pollStatus, 3000);
  }
  const wasBusy = state.status?.busy;
  state.online = true;
  state.status = d;
  $('offline').hidden = true;
  renderStatus();
  if (!state.routed) { state.routed = true; firstRoute(); }
  const key = JSON.stringify([d.counts, d.busy, d.tags]);
  const due = !d.busy || wasBusy !== d.busy || Date.now() - state.lastListAt > 9000;
  if (key !== state.lastListKey && due) {
    state.lastListKey = key;
    fillFilters();
    listing();
  }
  if (wasBusy && !d.busy) loadSources(); // counts may have changed
  setTimeout(pollStatus, d.busy ? 1500 : 4000);
}

function renderStatus() {
  const d = state.status, n = total(), want = expectedTotal();
  const failed = d.phase.startsWith('Refresh stopped');
  const pill = $('status');
  pill.dataset.state = failed ? 'error' : d.busy ? 'busy' : n ? 'ready' : 'idle';
  const warn = d.warnings.length ? ' · ' + plural(d.warnings.length, 'warning') : '';
  const said = failed ? 'Indexing stopped.' : d.busy ? 'Indexing started. You can read while it runs.' : n ? 'Index ready. ' + plural(n, 'session') + '.' : '';
  if ($('announce').textContent !== said) $('announce').textContent = said;
  $('statusText').textContent = failed ? 'Indexing stopped' + warn
    : d.busy ? 'Indexing · ' + num(n) + (want > n ? ' of about ' + num(want) : ' so far')
    : n ? plural(n, 'session') + warn : 'No sessions yet';

  const phase = d.busy ? (d.phase === 'Starting' ? 'Getting started' : d.phase === 'Applying tag names' ? 'Applying your tags' : d.phase) : '';
  $('phase').textContent = failed ? 'Indexing stopped' : d.busy ? phase : n ? 'Ready to read' : 'Nothing indexed yet';
  $('phaseNote').textContent = failed ? d.phase.replace('Refresh stopped: ', '') + ' What was indexed before the stop is still readable. Rebuild the index to try again.'
    : d.busy ? "You can read while this runs. Search only covers what's indexed so far."
    : n ? (d.seconds != null ? 'The last index took ' + took(d.seconds) + '. ' : '') + 'New sessions show up after you rebuild the index.'
    : 'Turn on a source to build your index.';
  const fraction = want ? Math.min(n / want, 1) : null;
  for (const bar of [$('statusBar'), $('indexingBar')]) {
    if (fraction == null || d.phase === 'Starting') bar.removeAttribute('value'); else bar.value = d.phase === 'Applying tag names' ? 1 : fraction;
  }
  $('statusBar').hidden = !d.busy;
  $('refresh').disabled = d.busy;

  const merged = {};
  for (const [k, v] of Object.entries(d.counts)) merged[k === 'history' ? 'codex' : k] = (merged[k === 'history' ? 'codex' : k] || 0) + v;
  for (const k of Object.keys(state.expected)) merged[k] = merged[k] || 0;
  $('statusCounts').replaceChildren(...Object.entries(merged).map(([k, v]) =>
    h('li', {}, h('span', { text: appName(k) }), h('span', { text: num(v) + (d.busy && state.expected[k] > v ? ' of about ' + num(state.expected[k]) : '') }))));
  $('warnings').hidden = !d.warnings.length;
  $('warnings').firstElementChild.textContent = plural(d.warnings.length, 'file') + ' had a problem. The rest indexed normally.';
  $('warningList').replaceChildren(...d.warnings.slice(0, 100).map(w => h('li', { text: w })));

  $('indexing').hidden = !d.busy;
  $('indexingTitle').textContent = n ? 'Indexing your sessions' : 'Building your index';
  $('indexingText').textContent = phase + '. ' + num(n) + (want > n ? ' of about ' + num(want) : '') + ' sessions so far. '
    + 'A large archive takes several minutes. You can read while it runs.';
  syncSaveBar();
}

$('status').onclick = () => togglePanel($('statusPanel').hidden);
function togglePanel(open) {
  $('statusPanel').hidden = !open;
  $('status').setAttribute('aria-expanded', open);
}
document.addEventListener('click', e => { if (!e.target.closest('.statusWrap')) togglePanel(false); });
$('refresh').onclick = async () => {
  try { await post('/api/refresh', {}); state.status.busy = true; renderStatus(); listing(); }
  catch (e) { $('phaseNote').textContent = e.message; }
};

/* ---------- routing ---------- */

function firstRoute() {
  // A new install has nothing indexed and nothing running: start on Sources.
  if (!location.hash && !total() && !state.status.busy) { state.firstRun = true; location.replace('#/sources'); }
  route();
}
function route() {
  if (!state.routed) return;
  const sources = location.hash.startsWith('#/sources');
  $('sourcesPanel').hidden = !sources;
  document.querySelector('main').hidden = sources;
  $('showSources').toggleAttribute('aria-current', sources);
  $('showSessions').toggleAttribute('aria-current', !sources);
  if (sources) return renderSources();
  const m = location.hash.match(/^#\/session\/(.+)/);
  const id = m ? decodeURIComponent(m[1]) : '';
  document.body.classList.toggle('reading', !!id);
  if (id && id !== state.current) openSession(id);
  if (!id) { state.current = ''; state.session = null; state.sessionRequest++; welcome(); markCurrent(); }
}
addEventListener('hashchange', route);

/* ---------- session list ---------- */

function filters() {
  const p = new URLSearchParams;
  for (const id of ['q', 'source', 'tag', 'from', 'to']) if ($(id).value.trim()) p.set(id, $(id).value.trim());
  if (state.project) p.set('project', state.project);
  if ($('chain').checked) p.set('chain', '1');
  return p;
}
function fillFilters() {
  const d = state.status;
  const fill = (id, all, entries) => {
    const old = $(id).value;
    $(id).replaceChildren(h('option', { value: '', text: all }), ...entries.map(([v, t]) => h('option', { value: v, text: t })));
    $(id).value = [...$(id).options].some(o => o.value === old) ? old : '';
  };
  fill('source', 'All apps', Object.entries(d.counts).map(([k, v]) => [k, appName(k) + ' (' + num(v) + ')']));
  fill('tag', d.tags.length ? 'All tags' : 'No tags yet', d.tags.map(t => [t, t]));
  $('tag').disabled = !d.tags.length;
}
async function listing(keepPage) {
  if (!keepPage) state.page = 0;
  const n = ++state.listRequest, p = filters(), active = [...p.keys()].filter(k => k !== 'chain').length;
  p.set('page', state.page);
  state.lastListAt = Date.now();
  const extra = ['from', 'to'].filter(id => $(id).value).length + (state.project ? 1 : 0) + ($('chain').checked ? 1 : 0);
  $('moreLabel').textContent = 'More filters' + (extra ? ' · ' + extra + ' on' : '');
  $('reset').hidden = !active && !$('chain').checked;
  if (!state.sessions.length) $('list').replaceChildren(...[0, 1, 2, 3].map(() => h('div', { class: 'skeleton' }, h('i'), h('i'))));
  let d;
  try { d = await api('/api/list?' + p); } catch (e) { if (n === state.listRequest) $('error').textContent = e.message; return; }
  if (n !== state.listRequest) return;
  $('error').textContent = '';
  state.total = d.total;
  state.sessions = d.sessions;
  const focused = document.activeElement?.closest?.('.row')?.dataset.id;
  const chain = $('chain').checked && $('tag').value;
  $('list').className = chain ? 'chain' : '';
  $('list').replaceChildren(...d.sessions.map(row));
  if (!d.sessions.length) $('list').replaceChildren(emptyList(active));
  if (focused) $('list').querySelector(`[data-id="${CSS.escape(focused)}"]`)?.focus();
  $('total').textContent = d.total ? plural(d.total, 'session') + (active ? ' found' : '') : '';
  const first = state.page * 50 + 1;
  $('pager').hidden = d.total <= 50;
  $('page').textContent = num(first) + ' to ' + num(Math.min(first + 49, d.total)) + ' of ' + num(d.total);
  $('prev').disabled = state.page === 0;
  $('next').disabled = first + 49 >= d.total;
  $('prev').textContent = $('chain').checked ? 'Earlier' : 'Newer';
  $('next').textContent = $('chain').checked ? 'Later' : 'Older';
  chainHead(d.total);
  markCurrent();
  if (!state.current) welcome();
  if (state.session) neighbors();
}
function row(s) {
  const d = date(s.start);
  return h('button', { class: 'row', type: 'button', 'data-id': s.id, onclick: () => go(s.id) },
    mark(s.source),
    h('span', { class: 'title', text: title(s) }),
    h('span', { class: 'date', text: d ? shortDate(d) : 'No date' }),
    h('span', { class: 'meta' }, h('span', { class: 'sr', text: appName(s.source) + ', ' }),
      [folder(s.project), plural(s.count, 'message')].filter(Boolean).join(' · ')));
}
function emptyList(active) {
  const busy = state.status?.busy;
  if (active) return h('div', { class: 'empty' }, h('strong', { text: 'No sessions match' }),
    busy ? 'Indexing is still running, so this can change. ' : 'Try fewer words, or widen the dates. Search looks for the exact phrase. ',
    h('button', { class: 'text', type: 'button', text: 'Clear filters', onclick: resetFilters }));
  if (busy) return h('div', { class: 'empty' }, h('strong', { text: 'Sessions are on their way' }), 'They show up here as each app is indexed.');
  return h('div', { class: 'empty' }, h('strong', { text: 'No sessions yet' }), 'Turn on a source and save. ',
    h('a', { href: '#/sources', text: 'Choose your sources' }));
}
function chainHead(count) {
  const tag = $('tag').value, box = $('chainHead');
  box.hidden = !tag;
  if (!tag) return;
  const words = state.config?.tags?.[tag];
  const on = $('chain').checked;
  box.replaceChildren(
    h('strong', { text: tag }),
    plural(count, 'session') + (words ? ' that mention ' + words.join(', ') : '') + (on ? ', oldest first.' : '.'),
    h('div', {},
      h('button', { class: 'text', type: 'button', text: on ? 'Show newest first' : 'Read as a chain, oldest first',
        onclick: () => { $('chain').checked = !on; listing(); } }),
      h('a', { id: 'exportChain', href: '/export?tag=' + encodeURIComponent(tag), download: tag + '-chain.md', text: 'Export the whole chain',
        title: 'One Markdown file with every session that has this tag, tool details included' })));
}
function markCurrent() {
  for (const r of $('list').querySelectorAll('.row')) r.toggleAttribute('aria-current', r.dataset.id === state.current);
}
function resetFilters() {
  $('filters').reset();
  state.project = '';
  listing();
}
function go(id) {
  const hash = '#/session/' + encodeURIComponent(id);
  if (location.hash !== hash) location.hash = hash;
  else if ($('q').value.trim()) openSession(id);
}

let typing;
$('q').oninput = () => { clearTimeout(typing); typing = setTimeout(listing, 300); };
$('filters').onsubmit = e => { e.preventDefault(); clearTimeout(typing); listing(); };
for (const id of ['source', 'tag', 'from', 'to', 'chain']) $(id).onchange = () => listing();
$('reset').onclick = resetFilters;
$('prev').onclick = () => { state.page--; listing(true); document.querySelector('aside').scrollTop = 0; };
$('next').onclick = () => { state.page++; listing(true); document.querySelector('aside').scrollTop = 0; };

/* Folder filter: a type-to-narrow box, because an archive can hold thousands of folders. */
const menu = $('projectList');
function projectMenu(open) {
  const words = $('project').value.trim().toLowerCase();
  const all = (state.status?.projects || []).filter(Boolean);
  const hits = all.filter(p => p.toLowerCase().includes(words)).slice(0, 60);
  menu.replaceChildren(...hits.map(p => h('li', { role: 'option', 'data-value': p, 'aria-selected': 'false' }, folder(p), h('small', { text: p }))));
  if (!hits.length) menu.append(h('li', { class: 'none', text: 'No folder matches that' }));
  menu.hidden = !open;
  $('project').setAttribute('aria-expanded', open);
}
function chooseProject(value) {
  state.project = value;
  $('project').value = value ? folder(value) : '';
  $('project').title = value;
  projectMenu(false);
  listing();
}
$('project').onfocus = () => { $('project').select(); projectMenu(true); };
$('project').oninput = () => { if (!$('project').value && state.project) chooseProject(''); else projectMenu(true); };
$('project').onblur = () => setTimeout(() => { projectMenu(false); $('project').value = state.project ? folder(state.project) : ''; }, 150);
$('project').onkeydown = e => {
  const items = [...menu.querySelectorAll('[role=option]')], at = items.findIndex(i => i.getAttribute('aria-selected') === 'true');
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (menu.hidden) return projectMenu(true);
    const next = items[(at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length];
    items[at]?.setAttribute('aria-selected', 'false');
    next?.setAttribute('aria-selected', 'true');
    next?.scrollIntoView({ block: 'nearest' });
  } else if (e.key === 'Enter') { e.preventDefault(); if (items[at]) chooseProject(items[at].dataset.value); }
  else if (e.key === 'Escape') { projectMenu(false); $('project').blur(); }
};
menu.onmousedown = e => { const li = e.target.closest('[role=option]'); if (li) chooseProject(li.dataset.value); };

/* ---------- reader ---------- */

function welcome() {
  if (state.current) return;
  const none = state.status && !total() && !state.status.busy;
  $('reader').replaceChildren(h('div', { class: 'welcome' },
    h('h1', { text: none ? 'Nothing to read yet' : 'Pick a session' }),
    none ? h('p', { text: 'Choose which apps to include. Everything stays on this computer, and your session files are only read, never changed.' })
      : h('p', { text: 'Search a phrase, narrow by app or folder, or pick a tag and read it oldest first to follow one piece of work over time. Tool steps stay folded until you open them.' }),
    none ? h('a', { class: 'primary', href: '#/sources', text: 'Choose your sources' })
      : h('ul', { class: 'keys' },
        h('li', {}, h('kbd', { text: '/' }), ' search'),
        h('li', {}, h('kbd', { text: 'J' }), h('kbd', { text: 'K' }), ' next and previous session'),
        h('li', {}, h('kbd', { text: '↑' }), h('kbd', { text: '↓' }), ' move through the list, ', h('kbd', { text: 'Enter' }), ' to open'))));
}

async function openSession(id, fromStart = false) {
  const request = ++state.sessionRequest;
  const query = $('q').value.trim();
  const params = new URLSearchParams({ id });
  if (fromStart) params.set('page', '0');
  if (query) params.set('q', query);
  state.current = id;
  state.session = null;
  markCurrent();
  let d;
  try { d = await api('/api/session?' + params); }
  catch (e) {
    if (request !== state.sessionRequest) return;
    return $('reader').replaceChildren(backButton(), h('div', { class: 'welcome' }, h('h1', { text: "That session isn't in the index" }),
      h('p', { text: e.message === 'Session not found' ? 'It may have been removed when the index was rebuilt, or its source was turned off.' : e.message })));
  }
  if (request !== state.sessionRequest) return;
  const s = state.session = d.session;
  state.query = query ? new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'giu') : null;
  state.matchCount = d.match_offsets.length;
  state.blockStart = state.blockPage = d.page;
  state.blockTotal = d.total;
  state.run = null;
  state.day = '';
  const model = s.model && s.model !== 'sample' ? s.model : '';
  const facts = [appName(s.source), model, plural(s.count, 'message'), span(s.start, s.end)].filter(Boolean);
  $('reader').replaceChildren(...[
    backButton(),
    h('header', { class: 'sessionHead' },
      h('h1', { text: title(s), title: s.title.length > 150 ? s.title.slice(0, 600) : null }),
      h('div', { class: 'facts' }, mark(s.source), facts.flatMap((f, i) => [i ? h('span', { class: 'sep', 'aria-hidden': 'true', text: '·' }) : null, h('span', { text: f })])),
      s.project ? h('div', { class: 'where', text: s.project }) : null,
      h('div', { class: 'headActions' },
        h('a', { class: 'secondary small', href: '/export?id=' + encodeURIComponent(id), download: 'session.md', text: 'Export as Markdown',
          title: 'Saves the whole session, tool details included' }),
        h('div', { class: 'matches', id: 'matches', hidden: true }),
        d.page ? h('button', { class: 'text', type: 'button', text: 'Read from the start', onclick: () => openSession(id, true) }) : null)),
    lineage(s, d.relatives),
    h('div', { id: 'transcript' }),
    h('div', { class: 'readMore', id: 'readMore' }),
    h('div', { class: 'neighbors', id: 'neighbors' })].filter(Boolean));
  const entries = addBlocks(d.blocks);
  if (!d.blocks.length) $('transcript').append(h('p', { class: 'empty', text: state.status?.busy
    ? 'Nothing indexed for this session yet. Check back when indexing finishes.' : 'This session has no readable messages.' }));
  neighbors();
  $('reader').scrollTop = 0;
  if (NARROW.matches) scrollTo(0, 0);
  if (!fromStart && state.matchCount) {
    const entry = entries[d.match_offsets[0] % 100];
    entry.build?.();
    const mark = entry.querySelector('mark');
    if (!mark) expandMessage(entry.querySelector('.body.clamped'));
    revealMatch(mark || entry);
  }
}
function backButton() {
  return h('a', { class: 'back text', href: '#/sessions', text: '← All sessions' });
}
function lineage(s, relatives) {
  const parent = relatives.find(r => r.id === s.parent), kids = relatives.filter(r => r.id !== s.parent);
  if (!s.parent && !kids.length) return null;
  const link = r => h('a', { href: '#/session/' + encodeURIComponent(r.id), text: title(r) });
  return h('nav', { class: 'card lineage', 'aria-label': 'Related sessions' }, h('ul', {},
    s.parent ? h('li', {}, h('span', { text: 'Started from' }), parent ? link(parent) : "A session that isn't in the index") : null,
    h('li', {}, h('span', { text: 'This session' }), h('b', { class: 'here', text: title(s) })),
    kids.map(k => h('li', { class: 'child' }, h('span', { text: 'Handed off to' }), link(k)))));
}
function neighbors() {
  const box = $('neighbors');
  if (!box) return;
  const at = state.sessions.findIndex(s => s.id === state.current);
  const chain = $('chain').checked && $('tag').value;
  const card = (s, label) => s ? h('button', { type: 'button', onclick: () => go(s.id) }, h('small', { text: label }), h('span', { text: title(s) })) : h('span');
  box.replaceChildren(...(at < 0 ? [] : [
    card(state.sessions[at - 1], chain ? '← Earlier in this chain' : '← Previous in the list'),
    card(state.sessions[at + 1], chain ? 'Later in this chain →' : 'Next in the list →')]));
}

/* Put text into el. Marks search matches. Never parses HTML. */
function put(el, text, q) {
  if (!q) return el.append(text);
  let from = 0;
  for (const match of text.matchAll(q)) {
    el.append(text.slice(from, match.index), h('mark', { text: match[0] }));
    from = match.index + match[0].length;
  }
  el.append(text.slice(from));
}
/* Headings and **bold** read as bold. The markers are dropped; the words stay text. */
function rich(el, text, q) {
  const marks = /^(#{1,4}) +(\S.*)$|\*\*([^*\n]+)\*\*/gm;
  let from = 0, m;
  while ((m = marks.exec(text))) {
    put(el, text.slice(from, m.index), q);
    const strong = h('strong', { class: m[1] ? 'heading' : null });
    put(strong, m[2] ?? m[3], q);
    el.append(strong);
    from = m.index + m[0].length;
  }
  put(el, text.slice(from), q);
}
/* Message text stays text. Fenced code and `inline code` get a code face. */
function body(text, q) {
  const el = h('div', { class: 'body' });
  const parts = text.split(/```([^\n`]*)\n([\s\S]*?)(?:\n?```|$)/g);
  for (let i = 0; i < parts.length; i += 3) {
    const prose = (i ? parts[i].replace(/^\n+/, '') : parts[i]).replace(i + 2 < parts.length ? /\n+$/ : /$^/, '');
    prose.split(/`([^`\n]+)`/g).forEach((piece, n) => {
      if (n % 2) { const c = h('code'); put(c, piece, q); el.append(c); } else if (piece) rich(el, piece, q);
    });
    if (i + 2 < parts.length) {
      const pre = h('pre', { 'data-lang': parts[i + 1].trim() || null });
      put(pre, parts[i + 2], q);
      el.append(pre);
    }
  }
  if (text.length > 6000 || text.split('\n').length > 90) {
    el.classList.add('clamped');
    return [el, h('button', { class: 'text more', type: 'button', text: 'Show the whole message (' + num(text.length) + ' characters)',
      onclick: () => expandMessage(el) })];
  }
  return [el];
}
function expandMessage(el) {
  if (!el?.classList.contains('clamped')) return;
  el.classList.remove('clamped');
  el.nextElementSibling.remove();
}

/* Tool records come in many shapes. Pull out a name and one useful line; keep the rest a click away. */
const TOOL_TYPES = { commandExecution: 'Command', command_execution: 'Command', fileChange: 'File change', file_change: 'File change',
  webSearch: 'Web search', mcpToolCall: 'Tool', dynamic_tool: 'Tool', reasoning: 'Reasoning', summary_text: 'Reasoning',
  tool_result: 'Result', function_call_output: 'Result', custom_tool_call_output: 'Result', checkpoint: 'Checkpoint',
  notification: 'Notice', contextCompaction: 'Context trimmed', tool: 'Tool' };
const oneLine = s => String(s).replace(/\s+/g, ' ').trim().slice(0, 160);
function firstText(v, depth = 0) {
  if (typeof v === 'string') return v;
  if (!v || typeof v !== 'object' || depth > 3) return '';
  if (Array.isArray(v)) return v.map(x => firstText(x, depth + 1)).filter(Boolean).join('\n');
  for (const k of ['command', 'file_path', 'path', 'query', 'pattern', 'url', 'description', 'prompt', 'text', 'output', 'content', 'result', 'summary'])
    if (v[k] != null) { const t = firstText(v[k], depth + 1); if (t) return t; }
  if (depth) return '';
  // Nothing familiar: show the first short values so the line still says something.
  return Object.entries(v).filter(([k, x]) => (typeof x === 'string' && x) || typeof x === 'number').slice(0, 3).map(([k, x]) => k + ': ' + x).join(', ');
}
function describeTool(text) {
  let d;
  const trimmed = text.trim();
  if (text.length < 400000 && /^[[{]/.test(trimmed)) { try { d = JSON.parse(trimmed); } catch { /* plain text */ } }
  if (d === undefined) return { name: 'Output', detail: oneLine(text.slice(0, 400)), main: text };
  const item = Array.isArray(d) ? d[0] : d;
  if (!item || typeof item !== 'object') return { name: 'Tool', detail: oneLine(trimmed.slice(0, 400)), main: text };
  const type = item.type || '';
  const result = /result|output/i.test(type) || (!item.name && !item.input && !item.arguments && ('result' in item || 'output' in item));
  let name = result ? 'Result' : item.name || item.tool || item.toolName || item.title || TOOL_TYPES[type] || 'Tool';
  if (Array.isArray(d) && d.length > 1) name += ' +' + (d.length - 1);
  let args = item.input ?? item.arguments ?? item.state?.input;
  if (typeof args === 'string' && /^[[{]/.test(args.trim())) { try { args = JSON.parse(args); } catch { /* keep string */ } }
  const out = firstText(item.aggregatedOutput ?? item.output ?? item.result ?? item.content ?? item.state?.output ?? item.state?.result ?? item.text ?? item.diffStr);
  const call = firstText(item.command ?? args ?? item.query ?? item.fileName);
  const main = [call && out ? '$ ' + call : call, out].filter(Boolean).join('\n\n');
  return { name: String(name), detail: oneLine((call || out).slice(0, 400)), main, raw: JSON.stringify(d, null, 2) };
}
function toolEl(b, q) {
  const info = describeTool(b.text), t = date(b.time);
  const hit = q && b.text.search(q) >= 0;
  const el = h('details', { class: 'tool' + (hit ? ' hasHit' : '') },
    h('summary', {}, h('span', { class: 'tname', text: info.name }), h('span', { class: 'tdetail', text: info.detail }),
      hit ? h('span', { class: 'hit', title: 'Contains your search' }) : null, t ? h('time', { text: timeText(t) }) : null));
  el.build = () => {
    if (el.build.done) return;
    el.build.done = true;
    const box = h('div', { class: 'toolBody' });
    if (info.main) { const pre = h('pre'); put(pre, info.main, q); box.append(pre); }
    if (info.raw) {
      const raw = h('details', { class: 'raw', open: !info.main }, h('summary', { text: 'Full record' }));
      const pre = h('pre'); put(pre, info.raw, box.querySelector('mark') ? '' : q); raw.append(pre); box.append(raw);
    }
    el.append(box);
  };
  el.addEventListener('toggle', () => el.open && el.build());
  el.info = info;
  return el;
}
/* Close the current run of tool steps. Long runs fold into one line. */
function endRun() {
  const run = state.run;
  state.run = null;
  if (!run) return;
  const box = h('div', { class: 'toolrun' });
  if (run.length < 4) box.append(...run);
  else {
    const names = [...new Set(run.map(t => t.info.name).filter(n => n !== 'Result' && n !== 'Output'))];
    box.append(h('details', { class: 'toolgroup' },
      h('summary', {}, h('span', { class: 'tname', text: run.length + ' tool steps' }),
        h('span', { class: 'tdetail', text: names.slice(0, 5).join(', ') + (names.length > 5 ? ' and more' : '') }),
        run.some(t => t.classList.contains('hasHit')) ? h('span', { class: 'hit', title: 'Contains your search' }) : null,
        run[0].querySelector('time')?.cloneNode(true)),
      ...run));
  }
  $('transcript').append(box);
}
function addBlocks(blocks) {
  const q = state.query, s = state.session;
  const entries = [];
  for (const b of blocks) {
    const t = date(b.time);
    if (b.kind === 'tool') {
      const tool = toolEl(b, q);
      (state.run = state.run || []).push(tool);
      entries.push(tool);
      continue;
    }
    endRun();
    if (t && t.toDateString() !== state.day) {
      state.day = t.toDateString();
      $('transcript').append(h('div', { class: 'day', text: fmt(t, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) }));
    }
    const who = b.role === 'user' ? 'You' : b.role === 'assistant' ? 'Assistant' : b.role.charAt(0).toUpperCase() + b.role.slice(1);
    const model = b.role === 'assistant' && b.model && b.model !== s.model ? b.model : '';
    const turn = h('section', { class: 'turn ' + (b.role === 'user' ? 'user' : 'assistant') },
      h('div', { class: 'turnHead' }, h('span', { class: 'who', text: who }), model ? h('span', { text: model }) : null,
        h('time', { text: t ? timeText(t) : b.time || '' })),
      body(b.text, q));
    entries.push(turn);
    $('transcript').append(turn);
  }
  endRun();
  const loaded = Math.min((state.blockPage + 1) * 100, state.blockTotal), left = state.blockTotal - loaded;
  $('readMore').replaceChildren(...(left <= 0 ? [] : [
    h('button', { class: 'secondary small', type: 'button', id: 'more', text: 'Read the next ' + Math.min(100, left),
      onclick: () => more() }),
    h('button', { class: 'text', type: 'button', text: 'Load all ' + num(left) + ' remaining', onclick: loadAll }),
    h('span', { text: num(loaded - state.blockStart * 100) + ' of ' + num(state.blockTotal) + ' entries shown' })]));
  matchBar(q);
  return entries;
}
async function more() {
  if (!state.session || $('more')?.disabled) return 0;
  const id = state.current, request = state.sessionRequest, page = state.blockPage + 1;
  const controls = $('readMore').querySelectorAll('button');
  for (const button of controls) button.disabled = true;
  try {
    const d = await api('/api/session?id=' + encodeURIComponent(id) + '&page=' + page);
    if (request !== state.sessionRequest) return 0;
    state.blockPage = d.page;
    addBlocks(d.blocks);
    return d.blocks.length;
  } catch (e) {
    if (request === state.sessionRequest) $('readMore').append(h('span', { class: 'problem', text: e.message }));
    return 0;
  } finally {
    for (const button of controls) button.disabled = false;
  }
}
async function loadAll() {
  const request = state.sessionRequest;
  while (request === state.sessionRequest && (state.blockPage + 1) * 100 < state.blockTotal) if (!await more()) break;
}
function matchBar(q) {
  const bar = $('matches');
  if (!bar) return;
  const count = q ? $('transcript').querySelectorAll('.turn:has(mark), .tool.hasHit').length : 0;
  bar.hidden = !q;
  if (!q) return;
  const partial = (state.blockPage + 1) * 100 < state.blockTotal;
  bar.replaceChildren(state.matchCount ? 'Found in ' + plural(state.matchCount, 'entry', 'entries')
    : count ? 'Found in ' + plural(count, 'entry', 'entries') + (partial ? ' so far' : '')
    : partial ? 'Not in the first entries. Load more to find it.' : 'Your search matched this session by a close word form.',
    ...(count ? [h('button', { class: 'text', type: 'button', text: 'Next match', onclick: nextMatch })] : []));
}
function nextMatch() {
  for (const t of $('transcript').querySelectorAll('.tool.hasHit')) t.build();
  const marks = [...$('transcript').querySelectorAll('mark')];
  if (!marks.length) return;
  const at = marks.findIndex(m => m.classList.contains('now'));
  revealMatch(marks[(at + 1) % marks.length]);
}
function revealMatch(next) {
  $('transcript').querySelector('.now')?.classList.remove('now');
  next.classList.add('now');
  for (let p = next; p && p.id !== 'transcript'; p = p.parentElement) {
    if (p.tagName === 'DETAILS') p.open = true;
    expandMessage(p);
  }
  next.scrollIntoView({ block: 'center' });
}

/* ---------- keyboard ---------- */

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { togglePanel(false); if (e.target === $('q') && $('q').value) { $('q').value = ''; listing(); } return; }
  const inList = e.target.closest?.('.row');
  if (inList && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault();
    (e.key === 'ArrowDown' ? inList.nextElementSibling : inList.previousElementSibling)?.focus();
    return;
  }
  if (e.target === $('q') && e.key === 'ArrowDown') { e.preventDefault(); return $('list').querySelector('.row')?.focus(); }
  if (e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || !$('sourcesPanel').hidden) return;
  if (e.key === '/') { e.preventDefault(); $('q').focus(); $('q').select(); }
  if (e.key === 'j' || e.key === 'k') {
    const at = state.sessions.findIndex(s => s.id === state.current);
    const next = state.sessions[at < 0 ? 0 : at + (e.key === 'j' ? 1 : -1)];
    if (next) { go(next.id); $('list').querySelector(`[data-id="${CSS.escape(next.id)}"]`)?.scrollIntoView({ block: 'nearest' }); }
  }
});

/* ---------- sources, folders, imports, tags ---------- */

const snapshot = () => JSON.stringify([state.config?.sources, state.tagRows]);
const dirty = () => !!state.config && snapshot() !== state.saved;
const isCustom = s => !/^\d+$/.test(String(s.id));

async function loadSources() {
  let d;
  try { d = await api('/api/sources'); }
  catch (e) { $('sourcesError').textContent = e.message; $('sourcesLoading').hidden = true; return; }
  const keep = dirty(); // don't throw away edits because a background check came back
  state.found = d;
  state.expected = {};
  for (const s of d.sources) if (s.enabled && s.supported && s.count) state.expected[s.kind] = (state.expected[s.kind] || 0) + s.count;
  if (!keep) {
    state.config = d.config;
    state.tagRows = Object.entries(d.config.tags).map(([name, words]) => ({ name, words: words.join(', ') }));
    state.saved = snapshot();
  }
  $('addKind').replaceChildren(...Object.entries(d.kinds).map(([v]) => h('option', { value: v, text: appName(v) })));
  $('addHint').textContent = FOLDER_HINTS[$('addKind').value] || '';
  $('sourcesLoading').hidden = true;
  $('sourcesError').textContent = '';
  if (state.status) renderStatus();
  if (!$('sourcesPanel').hidden) renderSources();
  chainHead(state.total);
}

function renderSources() {
  const first = state.firstRun && !total();
  $('sourcesTitle').textContent = first ? "Here's what's on this computer" : 'Sources';
  $('sourcesLead').textContent = first
    ? 'These apps have saved sessions here. Turn on the ones you want to read, then save. Nothing is indexed until you do. Everything stays on this computer: the viewer reads your session files, never changes them, and never goes online.'
    : 'Pick which apps to include. Everything stays on this computer: the viewer reads your session files, never changes them, and never goes online.';
  if (!state.config) return;
  const found = Object.fromEntries((state.found?.sources || []).map(s => [s.id, s]));
  const groups = { ready: [], unreadable: [], missing: [] };
  for (const s of state.config.sources) {
    const f = found[s.id];
    if (!f || f.path !== s.path) groups.ready.push(sourceRow(s, null));
    else groups[f.status === 'Supported' ? 'ready' : f.status === 'Not found' ? 'missing' : 'unreadable'].push(sourceRow(s, f));
  }
  const off = state.config.sources.filter(s => !s.enabled && found[s.id]?.status === 'Supported');
  const out = [];
  if (groups.ready.length) out.push(h('div', { class: 'group' },
    h('p', { class: 'groupLabel' }, 'Ready to read',
      off.length > 1 ? h('button', { class: 'text', type: 'button', text: 'Turn on all ' + groups.ready.length,
        onclick: () => { for (const s of off) s.enabled = true; renderSources(); } }) : null),
    h('div', { class: 'card rows' }, groups.ready)));
  else out.push(h('div', { class: 'note', text: "No supported apps were found in the usual places. If your sessions live somewhere else, add that folder below. For Claude.ai or ChatGPT, import an export." }));
  if (groups.unreadable.length) out.push(h('div', { class: 'group' },
    h('p', { class: 'groupLabel' }, "Found, but can't be read yet", h('span', { text: 'Nothing here is counted or indexed' })),
    h('div', { class: 'card rows quiet' }, groups.unreadable)));
  if (groups.missing.length) out.push(h('details', { class: 'group' },
    h('summary', { class: 'help', text: plural(groups.missing.length, 'app') + ' not found on this computer' }),
    h('div', { class: 'card rows quiet' }, groups.missing)));
  $('sourcesList').replaceChildren(...out);
  renderTags();
  syncSaveBar();
}
function sourceRow(s, f) {
  const usable = !f || f.status === 'Supported';
  const toggle = h('input', { type: 'checkbox', class: 'switch', checked: s.enabled && usable, disabled: !usable, 'aria-label': 'Include ' + appName(s.kind),
    onchange: () => { s.enabled = toggle.checked; renderSources(); } });
  const imported = s.kind === 'claude_ai' || s.kind === 'chatgpt';
  const what = imported ? 'conversation' : 'session';
  const state_ = !f ? 'Checked when you save'
    : f.status === 'Supported' ? (f.count == null ? 'Ready' : plural(f.count, what)) : f.status === 'Not found' ? 'Not found' : 'Not supported yet';
  const why = !f ? null
    : f.status.startsWith('Found, not yet supported (') ? "The folder is here, but its format isn't one this version knows. The app may have changed how it saves sessions."
    : f.status.startsWith('Found') ? "The folder is here, but this version can't read this app's format yet."
    : null;
  return h(usable ? 'label' : 'div', { class: 'sourceRow' + (f ? '' : ' pending') },
    usable ? toggle : h('span', { class: 'spacer' }),
    mark(s.kind),
    h('span', { class: 'name', text: appName(s.kind) + (imported ? ' export' : '') }),
    h('span', { class: 'state' + (s.enabled && usable ? ' on' : ''), text: state_ }),
    why ? h('span', { class: 'why', text: why }) : null,
    h('span', { class: 'path', text: imported ? "Imported copy, kept in this app's data folder" : s.path }),
    isCustom(s) ? h('button', { class: 'text', type: 'button', text: imported ? 'Remove from the archive' : 'Remove this folder',
      onclick: e => { e.preventDefault(); state.config.sources = state.config.sources.filter(x => x !== s); renderSources(); } }) : null);
}

$('addKind').onchange = () => { $('addHint').textContent = FOLDER_HINTS[$('addKind').value] || ''; };
const cleanPath = v => v.trim().replace(/^(['"])(.*)\1$/, '$2');
$('addFolder').onclick = () => {
  const path = cleanPath($('addPath').value);
  $('addError').textContent = !path ? 'Paste the full path to the folder first.'
    : state.config.sources.some(s => s.path === path && s.kind === $('addKind').value) ? 'That folder is already in your sources.' : '';
  if ($('addError').textContent) return $('addPath').focus();
  state.config.sources.push({ id: crypto.randomUUID(), kind: $('addKind').value, path, enabled: true });
  $('addPath').value = '';
  $('addCard').open = false;
  renderSources();
  $('sourcesList').querySelector('.pending')?.scrollIntoView({ block: 'center' });
};
$('importExport').onclick = async () => {
  const path = cleanPath($('importPath').value), button = $('importExport');
  $('importDone').hidden = true;
  $('importError').textContent = !path ? 'Paste the full path to the export ZIP first.'
    : dirty() ? 'Save or discard your other changes first. Importing starts indexing right away.'
    : state.status?.busy ? 'Indexing is running. Import when it finishes.' : '';
  if ($('importError').textContent) return;
  button.disabled = true;
  button.textContent = 'Reading the export…';
  try {
    await post('/api/import', { path, kind: $('importKind').value });
    $('importPath').value = '';
    $('importDone').textContent = 'Imported. Indexing has started, and the conversations will show up under Sessions.';
    $('importDone').hidden = false;
    state.status.busy = true;
    listing();
    await loadSources();
  } catch (e) { $('importError').textContent = e.message; }
  button.disabled = false;
  button.textContent = 'Import export';
};

function renderTags() {
  const rows = state.tagRows.map((t, i) => {
    const name = h('input', { value: t.name, placeholder: 'Tag name', 'aria-label': 'Tag name', oninput: () => { t.name = name.value; syncSaveBar(); } });
    const words = h('input', { value: t.words, placeholder: 'Keywords, separated by commas', 'aria-label': 'Keywords for this tag',
      oninput: () => { t.words = words.value; syncSaveBar(); } });
    return h('div', { class: 'tagRow' }, name, words,
      h('button', { class: 'text', type: 'button', text: 'Remove', 'aria-label': 'Remove tag ' + (t.name || i + 1),
        onclick: () => { state.tagRows.splice(i, 1); renderTags(); syncSaveBar(); } }));
  });
  $('tagRows').replaceChildren(...(rows.length ? rows : [h('p', { class: 'tagEmpty', text: 'No tags yet. For example: a tag named "garden" with the keywords "garden planner, seed calendar".' })]));
}
$('addTag').onclick = () => {
  state.tagRows.push({ name: '', words: '' });
  renderTags();
  syncSaveBar();
  $('tagRows').lastElementChild.querySelector('input').focus();
};
function readTags() {
  const tags = {};
  for (const t of state.tagRows) {
    const name = t.name.trim(), words = t.words.split(',').map(w => w.trim()).filter(Boolean);
    if (!name && !words.length) continue;
    if (!name) throw Error('One of your tags has keywords but no name.');
    if (!words.length) throw Error('The tag "' + name + '" needs at least one keyword.');
    if (name in tags) throw Error('Two tags are named "' + name + '". Give each tag its own name.');
    tags[name] = words;
  }
  return tags;
}

function syncSaveBar() {
  if (!state.config) return;
  const changed = dirty(), busy = state.status?.busy;
  $('saveBar').hidden = !changed && !state.justSaved;
  $('discard').hidden = !changed;
  $('saveSources').hidden = !changed;
  $('saveSources').disabled = busy;
  const on = state.config.sources.filter(s => s.enabled).length;
  if (changed) {
    state.justSaved = false;
    $('saveNote').textContent = busy ? 'Indexing is running. You can save when it finishes.'
      : !total() ? plural(on, 'source') + ' turned on. Saving starts your first index, which can take several minutes for a large archive.'
      : 'You have changes that are not saved. Saving rebuilds the index.';
  }
}
$('discard').onclick = () => {
  const s = JSON.parse(state.saved);
  state.config.sources = s[0];
  state.tagRows = s[1];
  $('settingsError').textContent = '';
  renderSources();
};
$('saveSources').onclick = async () => {
  $('settingsError').textContent = '';
  try {
    state.config.tags = readTags();
    await post('/api/config', state.config);
  } catch (e) {
    $('settingsError').textContent = e.message;
    return $('settingsError').scrollIntoView({ block: 'center' });
  }
  // Work out what to expect from what was already counted, in case the next check is slow.
  const found = Object.fromEntries((state.found?.sources || []).map(s => [s.id, s]));
  state.expected = {};
  for (const s of state.config.sources) if (s.enabled && found[s.id]?.count) state.expected[s.kind] = (state.expected[s.kind] || 0) + found[s.id].count;
  state.saved = snapshot();
  state.status.busy = true;
  state.justSaved = true;
  $('saveNote').textContent = 'Saved. Indexing has started.';
  renderStatus();
  listing();
  loadSources();
  if (state.firstRun) location.hash = '#/sessions'; else renderSources();
  setTimeout(() => { state.justSaved = false; syncSaveBar(); }, 5000);
};
addEventListener('beforeunload', e => { if (dirty()) e.preventDefault(); });

/* ---------- start ---------- */

welcome();
pollStatus();
loadSources();
