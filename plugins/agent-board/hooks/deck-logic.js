// 駕駛艙（Flight Deck）的純函式：白話翻譯、時間線、檔案、待辦、工作量與 SVG 圖塊。不碰 $，方便單獨測試。
// 白話翻譯規則與 plugins/chutora/hooks/deck.py 同一份（狀態列用），改一邊時另一邊要一起改。
import { ICONS } from './icons.js'

export const COLORS = {
  bg: '#0B1324', card: '#121D33', line: '#24365C', ink: '#E6ECF5', mute: '#8C9BB5',
  orange: '#FF6A26', orange2: '#FF9A4A', opus: '#FF6A26', sonnet: '#A78BFA', haiku: '#58C4DC',
  ok: '#3FB950', bad: '#F85149', run: '#E3B341', empty: '#1C2B4B',
}
export const MAX_EVENTS = 40

// ---------------------------------------------------------------- 白話翻譯
const base = (p) => {
  const s = String(p ?? '').replace(/\/+$/, '')
  const i = s.lastIndexOf('/')
  return i >= 0 ? s.slice(i + 1) || s : s
}
const short = (s, n) => {
  const t = String(s ?? '').replace(/\s+/g, ' ').trim()
  return t.length <= n ? t : t.slice(0, n - 1) + '…'
}
function stripPrefix(cmd) {
  let c = String(cmd ?? '').trim()
  for (let i = 0; i < 6; i++) {
    const m = c.match(/^(cd\s+\S+\s*(&&|;)\s*)/) || c.match(/^([A-Za-z_][A-Za-z0-9_]*=\S*\s+)/) || c.match(/^(sudo|time|exec|command|nohup)\s+/)
    if (!m) break
    c = c.slice(m[0].length).trim()
  }
  return c
}
const BASH_RULES = [
  [/^(npm|pnpm|yarn|bun)\s+(i|install|ci|add)\b/, '安裝套件', 'Install packages', 'box'],
  [/^(npm|pnpm|yarn|bun)\s+(run\s+)?test\b/, '跑測試', 'Run tests', 'rocket'],
  [/^(npm|pnpm|yarn|bun)\s+(run\s+)?build\b/, '建置', 'Build', 'box'],
  [/^(npm|pnpm|yarn|bun)\s+(run\s+)?lint\b/, '檢查程式碼', 'Lint', 'search'],
  [/^(npm|pnpm|yarn|bun)\s+(run\s+)?(dev|start|serve)\b/, '啟動開發伺服器', 'Start dev server', 'rocket'],
  [/^(npx\s+)?(pytest|jest|vitest|mocha|ava|rspec|phpunit)\b/, '跑測試', 'Run tests', 'rocket'],
  [/^python3?\s+-m\s+(pytest|unittest)\b/, '跑測試', 'Run tests', 'rocket'],
  [/^(go|cargo|dotnet|swift|mix|deno)\s+test\b/, '跑測試', 'Run tests', 'rocket'],
  [/^(mvn|gradle|\.\/gradlew)\s+(\S+\s+)*test\b/, '跑測試', 'Run tests', 'rocket'],
  [/^make\s+(test|check)\b/, '跑測試', 'Run tests', 'rocket'],
  [/^(cargo|go|dotnet|swift)\s+build\b|^(npx\s+)?tsc\b|^make\b|^(mvn|gradle|\.\/gradlew)\b/, '建置', 'Build', 'box'],
  [/^(pip3?|uv|poetry|pipx|brew|apt(-get)?|gem|cargo)\s+(install|add|sync)\b/, '安裝套件', 'Install packages', 'box'],
  [/^(npx\s+)?(eslint|prettier|ruff|black|flake8|mypy|golangci-lint)\b/, '檢查程式碼', 'Lint', 'search'],
  [/^git\s+status\b/, '看 git 狀態', 'Check git status', 'branch'],
  [/^git\s+diff\b/, '看修改差異', 'View changes', 'branch'],
  [/^git\s+(log|show)\b/, '看提交紀錄', 'View history', 'branch'],
  [/^git\s+add\b/, '暫存修改', 'Stage changes', 'branch'],
  [/^git\s+commit\b/, '提交 commit', 'Commit', 'branch'],
  [/^git\s+push\b/, '推上遠端', 'Push', 'branch'],
  [/^git\s+(pull|fetch)\b/, '拉下遠端更新', 'Pull updates', 'branch'],
  [/^git\s+(checkout|switch)\b/, '切換分支', 'Switch branch', 'branch'],
  [/^git\s+(branch)\b/, '看分支', 'List branches', 'branch'],
  [/^git\s+(merge|rebase)\b/, '合併分支', 'Merge branches', 'branch'],
  [/^git\s+clone\b/, '下載 repo', 'Clone repo', 'branch'],
  [/^git\s+stash\b/, '暫存工作區', 'Stash work', 'branch'],
  [/^docker\s+(build|buildx)\b/, '建置容器映像', 'Build image', 'box'],
  [/^docker(-compose|\s+compose)?\s+(run|up|start)\b/, '啟動容器', 'Start containers', 'rocket'],
  [/^(ls|tree|exa|eza)\b/, '看資料夾內容', 'List files', 'folder'],
  [/^(cat|head|tail|less|more|bat|nl)\b/, '看檔案內容', 'View a file', 'doc'],
  [/^(grep|rg|ag|ack)\b/, '搜尋文字', 'Search text', 'search'],
  [/^(find|fd)\b/, '找檔案', 'Find files', 'search'],
  [/^mkdir\b/, '建立資料夾', 'Create folder', 'folder'],
  [/^(rm|rmdir|unlink)\b/, '刪除檔案', 'Delete files', 'scissors'],
  [/^mv\b/, '移動檔案', 'Move files', 'folder'],
  [/^cp\b/, '複製檔案', 'Copy files', 'copies'],
  [/^(curl|wget|http)\b/, '連網抓資料', 'Fetch from network', 'plug'],
  [/^sed\s+-i\b/, '直接改檔案', 'Edit a file in place', 'wrench'],
  [/^(chmod|chown)\b/, '改權限', 'Change permissions', 'wrench'],
  [/^(python3?|node|ruby|php|go\s+run|deno\s+run|bun\s+run|java)\b/, '執行程式', 'Run a program', 'rocket'],
  [/^(echo|printf)\b/, '輸出文字', 'Print text', 'scroll'],
]
const TOOL_PLAIN = {
  Read: ['讀 {x}', 'Read {x}', 'doc'],
  Edit: ['修改 {x}', 'Edit {x}', 'wrench'],
  MultiEdit: ['修改 {x}', 'Edit {x}', 'wrench'],
  Write: ['寫入 {x}', 'Write {x}', 'wrench'],
  NotebookEdit: ['修改筆記本 {x}', 'Edit notebook {x}', 'wrench'],
  Glob: ['找檔案 {x}', 'Find files {x}', 'search'],
  WebFetch: ['讀網頁 {x}', 'Read web page {x}', 'plug'],
  WebSearch: ['上網搜尋「{x}」', 'Search the web for “{x}”', 'search'],
  TodoWrite: ['更新待辦清單', 'Update to-do list', 'clipboard'],
  TaskCreate: ['新增待辦', 'Add a task', 'clipboard'],
  TaskUpdate: ['更新待辦', 'Update a task', 'clipboard'],
  AskUserQuestion: ['問你問題', 'Ask you a question', 'question'],
  Skill: ['載入技能 {x}', 'Load skill {x}', 'next'],
  ToolSearch: ['載入工具', 'Load tools', 'next'],
  ExitPlanMode: ['提出計畫', 'Propose a plan', 'scroll'],
  EnterPlanMode: ['進入規劃模式', 'Enter plan mode', 'scroll'],
  LSP: ['查程式碼定義', 'Look up code', 'search'],
  SendUserMessage: ['傳訊息給你', 'Message you', 'scroll'],
}

// 回傳 { text, raw, icon }：text 白話、raw 原始指令（小字）、icon 像素圖示名稱
export function plain(tool, input, lang = 'zh') {
  const inp = input && typeof input === 'object' ? input : {}
  const zh = lang !== 'en'
  const t = String(tool ?? '')
  try {
    if (t === 'Bash') {
      const cmd = stripPrefix(inp.command)
      const raw = short(cmd, 60)
      for (const [rx, z, e, icon] of BASH_RULES) if (rx.test(cmd)) return { text: zh ? z : e, raw, icon }
      if (!zh && typeof inp.description === 'string' && inp.description.trim()) return { text: short(inp.description, 40), raw, icon: 'rocket' }
      return { text: zh ? '執行指令' : 'Run a command', raw, icon: 'rocket' }
    }
    if (t === 'Grep') {
      const pat = short(inp.pattern, 30)
      const where = inp.path ? short(base(inp.path), 24) : inp.glob ? short(inp.glob, 24) : ''
      if (where) return { text: zh ? `在 ${where} 裡找「${pat}」` : `Search ${where} for “${pat}”`, raw: `Grep "${pat}" ${where}`, icon: 'search' }
      return { text: zh ? `找「${pat}」` : `Search for “${pat}”`, raw: `Grep "${pat}"`, icon: 'search' }
    }
    if (t === 'Agent' || t === 'Task') {
      const who = String(inp.subagent_type || 'general-purpose').split(':').pop()
      const desc = short(inp.description, 32)
      const text = zh ? (desc ? `派工給 ${who}：${desc}` : `派工給 ${who}`) : (desc ? `Delegate to ${who}: ${desc}` : `Delegate to ${who}`)
      return { text, raw: `Agent ${who}`, icon: 'branch' }
    }
    if (t.startsWith('mcp__')) {
      const parts = t.split('__')
      const server = parts[1] || 'MCP'
      const name = parts.length > 2 ? parts[parts.length - 1] : t
      return { text: zh ? `用 ${server} 的 ${name}` : `Use ${server}: ${name}`, raw: t, icon: 'plug' }
    }
    const row = TOOL_PLAIN[t]
    if (row) {
      let x = ''
      let raw = t
      if (['Read', 'Edit', 'MultiEdit', 'Write'].includes(t)) { x = base(inp.file_path); raw = `${t} ${short(inp.file_path, 60)}` }
      else if (t === 'NotebookEdit') { x = base(inp.notebook_path); raw = `${t} ${short(inp.notebook_path, 60)}` }
      else if (t === 'Glob') { x = short(inp.pattern, 30); raw = `Glob ${x}` }
      else if (t === 'WebFetch') { const m = String(inp.url ?? '').match(/^\w+:\/\/([^/]+)/); x = m ? m[1] : short(inp.url, 30); raw = short(inp.url, 60) }
      else if (t === 'WebSearch') { x = short(inp.query, 30); raw = `WebSearch ${x}` }
      else if (t === 'Skill') { x = short(inp.skill, 30); raw = `Skill ${x}` }
      let text = (zh ? row[0] : row[1]).replace('{x}', x).replace(/\s+/g, ' ').trim()
      if (t === 'TodoWrite' && Array.isArray(inp.todos) && inp.todos.length) {
        const done = inp.todos.filter((d) => d && d.status === 'completed').length
        text += zh ? `（${done}/${inp.todos.length}）` : ` (${done}/${inp.todos.length})`
      }
      return { text, raw, icon: row[2] }
    }
  } catch (err) {
    // 翻譯失敗就用工具名稱
  }
  return { text: t || '?', raw: t, icon: 'next' }
}

// ---------------------------------------------------------------- 模型與 agent
export function family(model) {
  const m = String(model ?? '').toLowerCase()
  if (m.includes('opus')) return 'Opus'
  if (m.includes('sonnet')) return 'Sonnet'
  if (m.includes('haiku')) return 'Haiku'
  return m ? 'Other' : ''
}
export function familyColor(f) {
  return f === 'Opus' ? COLORS.opus : f === 'Sonnet' ? COLORS.sonnet : f === 'Haiku' ? COLORS.haiku : COLORS.mute
}

// ---------------------------------------------------------------- 狀態：時間線、檔案、待辦、工作量
export function newDeck() {
  return { events: [], byId: new Map(), edited: new Map(), read: new Set(), todos: [], tasks: new Map(), usage: {}, mainContext: 0, started: undefined }
}

const lines = (s) => (typeof s === 'string' && s.length ? s.split('\n').length : 0)

// 一次工具呼叫開始。agents：agentId → { type, model }（agent.spawn 記下的），用來標子 agent
export function callStart(deck, e, now, agents, lang) {
  const p = plain(e.tool, e, lang)
  const a = e.agentId ? agents.get(e.agentId) : undefined
  const ev = {
    id: e.tool_use_id, tool: String(e.tool), agentId: e.agentId, who: e.agentId ? (a && a.type) || 'agent' : 'main',
    model: e.agentId ? (a && a.model) || '' : '', text: p.text, raw: p.raw, icon: p.icon, start: now, end: undefined,
    status: 'running', count: 1, input: e,
  }
  if (deck.started === undefined) deck.started = now
  deck.events.push(ev)
  deck.byId.set(ev.id, ev)
  while (deck.events.length > MAX_EVENTS) {
    const old = deck.events.shift()
    if (old.status !== 'running') deck.byId.delete(old.id)
  }
  return ev
}

// 一次工具呼叫結束：ran 是 next(e) 的結果
export function callEnd(deck, id, ran, now) {
  const ev = deck.byId.get(id)
  if (!ev) return undefined
  ev.end = now
  ev.status = ran && (ran.deny || ran.isError) ? 'error' : 'ok'
  const inp = ev.input || {}
  if (ev.status === 'ok') {
    if (ev.tool === 'Edit') addEdit(deck, inp.file_path, lines(inp.new_string), lines(inp.old_string))
    else if (ev.tool === 'MultiEdit' && Array.isArray(inp.edits)) for (const x of inp.edits) addEdit(deck, inp.file_path, lines(x && x.new_string), lines(x && x.old_string))
    else if (ev.tool === 'Write') addEdit(deck, inp.file_path, lines(inp.content), 0)
    else if (ev.tool === 'NotebookEdit') addEdit(deck, inp.notebook_path, lines(inp.new_source), 0)
    else if (ev.tool === 'Read' && inp.file_path) deck.read.add(String(inp.file_path))
    else if (ev.tool === 'TodoWrite' && Array.isArray(inp.todos)) deck.todos = inp.todos.filter((t) => t && typeof t === 'object').map((t) => ({ text: String(t.activeForm || t.content || ''), status: String(t.status || 'pending') }))
    else if (ev.tool === 'TaskCreate') {
      const m = String((ran && ran.text) || '').match(/#(\d+)/)
      const key = m ? m[1] : 'n' + deck.tasks.size
      deck.tasks.set(key, { text: String(inp.activeForm || inp.subject || ''), status: 'pending' })
    } else if (ev.tool === 'TaskUpdate' && inp.taskId !== undefined) {
      const t = deck.tasks.get(String(inp.taskId))
      if (t && typeof inp.status === 'string') t.status = inp.status === 'deleted' ? 'deleted' : inp.status
    }
  }
  delete ev.input
  // 連續相同的動作合併成一列（例如連讀好幾次、連跑同一個指令）
  const i = deck.events.indexOf(ev)
  const prev = i > 0 ? deck.events[i - 1] : undefined
  if (prev && prev.status === ev.status && prev.status === 'ok' && prev.who === ev.who && prev.agentId === ev.agentId && prev.text === ev.text) {
    prev.count += ev.count
    prev.end = ev.end
    deck.events.splice(i, 1)
    deck.byId.delete(ev.id)
    return prev
  }
  return ev
}

function addEdit(deck, path, plus, minus) {
  if (!path) return
  const k = String(path)
  const cur = deck.edited.get(k) || { plus: 0, minus: 0 }
  cur.plus += plus
  cur.minus += minus
  deck.edited.set(k, cur)
}

// 待辦進度：TodoWrite 優先，其次 TaskCreate／TaskUpdate。回傳 { done, total, current, next } 或 null
export function todoProgress(deck) {
  const list = deck.todos.length ? deck.todos : [...deck.tasks.values()].filter((t) => t.status !== 'deleted')
  if (!list.length) return null
  const done = list.filter((t) => t.status === 'completed').length
  const cur = list.find((t) => t.status === 'in_progress')
  const nxt = list.find((t) => t.status === 'pending')
  return { done, total: list.length, current: cur ? cur.text : '', next: nxt ? nxt.text : '', states: list.map((t) => t.status) }
}

// turn.step 的 usage 依模型家族累計（input＋cache 寫入＋output，不含 cache 讀取，與狀態列同一個定義）
export function addUsage(deck, usage, model, isMain) {
  if (!usage || typeof usage !== 'object') return false
  const n = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  const f = family(typeof usage.model === 'string' && usage.model ? usage.model : model) || 'Other'
  deck.usage[f] = (deck.usage[f] || 0) + n(usage.input_tokens) + n(usage.cache_creation_input_tokens) + n(usage.output_tokens)
  if (isMain) deck.mainContext = n(usage.input_tokens) + n(usage.cache_creation_input_tokens) + n(usage.cache_read_input_tokens)
  return true
}

// 工作量：各家族 token 與「交給 Sonnet／Haiku」的比例
export function workload(deck) {
  const opus = deck.usage.Opus || 0
  const sonnet = deck.usage.Sonnet || 0
  const haiku = deck.usage.Haiku || 0
  const other = deck.usage.Other || 0
  const total = opus + sonnet + haiku + other
  return { opus, sonnet, haiku, other, total, delegated: total ? (sonnet + haiku) / total : 0 }
}

export function currentEvent(deck) {
  for (let i = deck.events.length - 1; i >= 0; i--) if (deck.events[i].status === 'running') return deck.events[i]
  return deck.events.length ? deck.events[deck.events.length - 1] : undefined
}

export function runningCount(deck) {
  return deck.events.filter((e) => e.status === 'running').length
}

// ---------------------------------------------------------------- SVG 圖塊（桌面版、VS Code、手機）
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')

export function iconSvg(name, size = 18) {
  const body = ICONS[name] || ICONS.next
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="${size}" height="${size}" shape-rendering="crispEdges">${body}</svg>`
}

// 分格進度：完成綠、進行中橘、未做深藍
export function progressSvg(states, width = 400) {
  const n = Math.max(1, Math.min(states.length, 24))
  const gap = 3
  const w = (width - gap * (n - 1)) / n
  const cells = states.slice(0, n).map((s, i) => {
    const c = s === 'completed' ? COLORS.ok : s === 'in_progress' ? COLORS.orange2 : COLORS.empty
    return `<rect x="${(i * (w + gap)).toFixed(1)}" y="0" width="${w.toFixed(1)}" height="10" fill="${c}"/>`
  })
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} 10" width="${width}" height="10" shape-rendering="crispEdges">${cells.join('')}</svg>`
}

// 工作量三色長條
export function workloadSvg(wl, width = 400) {
  const segs = [[wl.opus, COLORS.opus], [wl.sonnet, COLORS.sonnet], [wl.haiku, COLORS.haiku], [wl.other, COLORS.mute]].filter(([v]) => v > 0)
  let x = 0
  const rects = wl.total
    ? segs.map(([v, c]) => {
        const w = (v / wl.total) * width
        const r = `<rect x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="14" fill="${c}"/>`
        x += w
        return r
      })
    : [`<rect x="0" y="0" width="${width}" height="14" fill="${COLORS.empty}"/>`]
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} 14" width="${width}" height="14"><clipPath id="r"><rect width="${width}" height="14" rx="3"/></clipPath><g clip-path="url(#r)" shape-rendering="crispEdges">${rects.join('')}</g></svg>`
}

// 執行中燈號（綠色方塊加光暈，閒置時灰）
export function liveDotSvg(active) {
  const c = active ? COLORS.ok : COLORS.mute
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14" width="14" height="14" shape-rendering="crispEdges"><rect x="1" y="1" width="12" height="12" fill="${c}" opacity=".25"/><rect x="3" y="3" width="8" height="8" fill="${c}"/></svg>`
}

// ---------------------------------------------------------------- 終端機：用文字方塊畫同樣的區塊
export function blockBar(parts, width) {
  // parts: [[value, color]]，回傳 [{ text, color }]，總寬 width 欄
  const total = parts.reduce((s, [v]) => s + v, 0)
  if (!total) return [{ text: '░'.repeat(width), color: COLORS.mute }]
  let used = 0
  const out = parts.map(([v, c], i) => {
    const w = i === parts.length - 1 ? width - used : Math.round((v / total) * width)
    used += w
    return { text: '█'.repeat(Math.max(0, w)), color: c }
  })
  return out.filter((p) => p.text)
}

export function progressCells(states) {
  return states.slice(0, 24).map((s) => ({ text: '■', color: s === 'completed' ? COLORS.ok : s === 'in_progress' ? COLORS.orange2 : COLORS.empty }))
}

export function statusMark(ev) {
  return ev.status === 'ok' ? '✓' : ev.status === 'error' ? '✗' : '…'
}
export function statusColor(ev) {
  return ev.status === 'ok' ? COLORS.ok : ev.status === 'error' ? COLORS.bad : COLORS.run
}

export { esc }
