import { expect, mock, test } from 'claude-code/testing'
import { DECK_LABELS } from '../hooks/deck-view.js'
import { plain, newDeck, callStart, callEnd, todoProgress, addUsage, workload, progressSvg, workloadSvg, iconSvg, normalizeLimits, applyMeasure, recordTurn, mergeUsageFile, resetLabel, quotaSvg } from '../hooks/deck-logic.js'

test('白話翻譯：與 chutora 狀態列同一份規則', async () => {
  expect(plain('Bash', { command: 'cd app && npm test -- checkout' }).text).toBe('跑測試')
  expect(plain('Bash', { command: 'git push' }, 'en').text).toBe('Push')
  expect(plain('Grep', { pattern: 'TypeError', path: '/a/src' })).toEqual({ text: '在 src 裡找「TypeError」', raw: 'Grep "TypeError" src', icon: 'search' })
  expect(plain('Agent', { subagent_type: 'chutora:worker', description: '修 checkout' }).text).toBe('派工給 worker：修 checkout')
  expect(plain('Read', { file_path: '/a/src/checkout.ts' }).text).toBe('讀 checkout.ts')
  expect(plain('mcp__slack__send', {}, 'en').text).toBe('Use slack: send')
  expect(plain('Unknown', {}).text).toBe('Unknown')
})

test('時間線：子 agent 標名、連續相同動作合併、檔案增刪行數、待辦與工作量', async () => {
  const d = newDeck()
  const info = new Map([['a1', { type: 'worker', model: 'Sonnet' }]])
  callStart(d, { tool: 'Grep', tool_use_id: 'c1', pattern: 'TypeError', path: '/a/src' }, 0, info, 'zh')
  callEnd(d, 'c1', { result: 'x' }, 1000)
  callStart(d, { tool: 'Read', tool_use_id: 'c2', file_path: '/a/src/checkout.ts', agentId: 'a1' }, 1000, info, 'zh')
  callEnd(d, 'c2', { result: 'x' }, 1400)
  callStart(d, { tool: 'Read', tool_use_id: 'c3', file_path: '/a/src/checkout.ts', agentId: 'a1' }, 1500, info, 'zh')
  callEnd(d, 'c3', { result: 'x' }, 1600)
  callStart(d, { tool: 'Edit', tool_use_id: 'c4', file_path: '/a/src/checkout.ts', old_string: 'a', new_string: 'a\nb', agentId: 'a1' }, 2000, info, 'zh')
  callEnd(d, 'c4', { result: 'x' }, 4000)
  callStart(d, { tool: 'Bash', tool_use_id: 'c5', command: 'npm test', agentId: 'a1' }, 4000, info, 'zh')
  callEnd(d, 'c5', { isError: true, result: 'x' }, 9000)
  callStart(d, { tool: 'TodoWrite', tool_use_id: 'c6', todos: [{ content: 'a', status: 'completed' }, { content: 'b', activeForm: '補測試', status: 'in_progress' }, { content: 'c', status: 'pending' }] }, 9000, info, 'zh')
  callEnd(d, 'c6', { result: 'x' }, 9100)

  expect(d.events.map((e) => [e.who, e.text, e.status, e.count])).toEqual([
    ['main', '在 src 裡找「TypeError」', 'ok', 1],
    ['worker', '讀 checkout.ts', 'ok', 2],
    ['worker', '修改 checkout.ts', 'ok', 1],
    ['worker', '跑測試', 'error', 1],
    ['main', '更新待辦清單（1/3）', 'ok', 1],
  ])
  expect(d.edited.get('/a/src/checkout.ts')).toEqual({ plus: 2, minus: 1 })
  expect([...d.read]).toEqual(['/a/src/checkout.ts'])
  expect(todoProgress(d)).toEqual({ done: 1, total: 3, current: '補測試', next: 'c', states: ['completed', 'in_progress', 'pending'] })

  addUsage(d, { input_tokens: 1000, cache_creation_input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 50000 }, 'claude-opus-5-5', true)
  addUsage(d, { input_tokens: 3000, output_tokens: 0 }, 'claude-sonnet-5-5', false)
  const wl = workload(d)
  expect([wl.opus, wl.sonnet, wl.total, wl.delegated]).toEqual([1000, 3000, 4000, 0.75])
  expect(d.mainContext).toBe(51000)
})

test('時間線最多保留 40 筆；SVG 圖塊在字元上限內', async () => {
  const d = newDeck()
  for (let i = 0; i < 60; i++) {
    callStart(d, { tool: 'Bash', tool_use_id: 'x' + i, command: 'echo ' + i }, i, new Map(), 'zh')
    callEnd(d, 'x' + i, { isError: i % 2 === 0, result: '' }, i + 1)
  }
  expect(d.events.length).toBe(40)
  expect(progressSvg(['completed', 'in_progress', 'pending']).length).toBeLessThan(131072)
  expect(workloadSvg({ opus: 1, sonnet: 2, haiku: 3, other: 0, total: 6 }).includes('#A78BFA')).toBe(true)
  expect(iconSvg('chute').startsWith('<svg')).toBe(true)
})

function setup(on: any) {
  mock.clock(on)
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('agent.list', () => ({ value: [{ id: 'a1', description: '修 checkout', type: 'worker', status: 'running' }] }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('tool.call', () => ({ result: 'ok', text: 'ok' }))
}

for (const surface of ['terminal', 'desktop'] as const) {
  test('駕駛艙面板（' + surface + '）：現在、時間線、子 agent 縮排、檔案、按鈕', async ($, on) => {
    setup(on)
    await $.session.start({ surface, isInteractive: true, cwd: '/work' })
    await $.agent.spawn({ prompt: 'x', description: '修 checkout', subagentType: 'chutora:worker', isBackground: true, origin: { kind: 'model' } } as any)
    await $.tool.call({ tool: 'Grep', pattern: 'TypeError', path: '/a/src' } as any)
    await $.tool.call({ tool: 'Edit', file_path: '/a/src/checkout.ts', old_string: 'a', new_string: 'a\nb\nc', replace_all: false, agentId: 'a1' } as any)
    const ui = await $.ui.mount({
      plugin: 'agent-board', component: 'Pane', requestId: 'agent-board', surface,
      viewport: { columns: 100, rows: 40 },
      props: { title: '駕駛艙', isFocused: true, bodyColumns: 70, placement: 'inline', scroll: { offset: 0, bodyRows: 30 }, view: {} },
    } as any)
    expect(await ui.find({ type: 'Text', text: /^駕駛艙$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /在 src 裡找「TypeError」/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /修改 checkout\.ts/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^worker$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^改過 1$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\+3$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /估計（API 牌價）/ })).toBeDefined()
    if (surface === 'desktop') expect(await ui.find({ type: 'Svg' })).toBeDefined()
    else expect(await ui.find({ type: 'Svg' })).toBeUndefined()
    // 切到原始指令：時間線改顯示原始指令
    await ui.press({ key: 'raw' })
    expect(await ui.find({ type: 'Text', text: /^Grep "TypeError" src$/ })).toBeDefined()
    await ui.press({ key: 'plain' })
    expect(await ui.find({ type: 'Text', text: /在 src 裡找「TypeError」/ })).toBeDefined()
    await ui.unmount()
  })
}

test('tool.call 只觀察：結果原樣回傳', async ($, on) => {
  setup(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  const ran: any = await $.tool.call({ tool: 'Grep', pattern: 'x' } as any)
  expect(ran.result).toBe('ok')
})

const RL = [
  { kind: 'five_hour', percentUsed: 42, resetsAt: '2026-11-09T10:13:00.000Z' },
  { kind: 'seven_day', percentUsed: 18.5, resetsAt: '2026-11-12T06:00:00.000Z' },
  { kind: 'spend_limit', percentUsed: 5 },
]
const T0 = Date.parse('2026-11-09T08:00:00.000Z')

test('額度：讀數正規化、空讀數不清舊值、上一輪 token（cache 讀取不算進 total）', async () => {
  expect(normalizeLimits(RL)).toEqual({ five_hour: { pct: 42, resets_at: Date.parse('2026-11-09T10:13:00.000Z') / 1000 }, seven_day: { pct: 18.5, resets_at: Date.parse('2026-11-12T06:00:00.000Z') / 1000 } })
  expect(normalizeLimits([{ kind: 'five_hour', percentUsed: 'x' }, null])).toEqual({})
  const d = newDeck()
  expect(applyMeasure(d, RL)).toBe(true)
  expect(applyMeasure(d, [])).toBe(false)
  expect(d.quota.limits.five_hour.pct).toBe(42)
  expect(recordTurn(d, { input_tokens: 10, cache_creation_input_tokens: 200, cache_read_input_tokens: 5000, output_tokens: 30 })).toBe(true)
  expect(d.quota.lastTurn).toEqual({ input: 10, cache_write: 200, cache_read: 5000, output: 30, total: 240 })
  expect(recordTurn(d, undefined)).toBe(false)
})

test('額度：寫入 usage.json 只在較新時覆蓋並保留其他欄位；壞檔當空', async () => {
  const lim = { five_hour: { pct: 42, resets_at: 100 } }
  const old = JSON.stringify({ v: 1, limits: { source: 'statusline', updated_at: 1000, five_hour: { pct: 1, resets_at: 5 } }, claude: { net: -3 } })
  expect(mergeUsageFile(old, lim, 1000)).toBe(null)
  expect(mergeUsageFile(old, lim, 999)).toBe(null)
  const out = JSON.parse(mergeUsageFile(old, lim, 1001) as string)
  expect(out.limits).toEqual({ source: 'claude-mod', updated_at: 1001, five_hour: { pct: 42, resets_at: 100 } })
  expect(out.claude).toEqual({ net: -3 })
  expect(JSON.parse(mergeUsageFile('{壞掉', lim, 5) as string).limits.updated_at).toBe(5)
  expect(JSON.parse(mergeUsageFile('', lim, 5) as string).v).toBe(1)
  expect(mergeUsageFile(old, {}, 2000)).toBe(null)
})

test('額度：重置時間文字與長條圖', async () => {
  const sec = (ms: number) => Math.floor((T0 + ms) / 1000)
  expect(resetLabel(sec(2 * 3600e3 + 13 * 60e3), T0)).toBe('2h13m 後')
  expect(resetLabel(sec(45 * 60e3), T0, 'en')).toBe('in 45m')
  expect(resetLabel(sec(-1000), T0)).toBe('即將重置')
  expect(resetLabel(sec(3 * 86400e3), T0)).toMatch(/^週[日一二三四五六] \d\d:\d\d$/)
  expect(resetLabel(sec(3 * 86400e3), T0, 'en')).toMatch(/^[A-Z][a-z]{2} \d\d:\d\d$/)
  expect(quotaSvg(96, 200).includes('#F85149')).toBe(true)
  expect(quotaSvg(85, 200).includes('#E3B341')).toBe(true)
  expect(quotaSvg(10, 200).includes('#3FB950')).toBe(true)
})

function quotaSetup(on: any, writes: string[], file?: string, usage: any = { rateLimits: RL }, lang = 'zh') {
  mock.clock(on, { now: T0 })
  mock.env(on, { HOME: '/home/u', CHUTORA_LANG: lang })
  on('session.measure', () => ({ changed: ['rateLimits'] }))
  on('turn.complete', () => ({ text: '' }))
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('agent.list', () => ({ value: [] }))
  on('session.usage', () => ({ value: { startedAt: 0, context: {}, rateLimits: usage.rateLimits } }))
  on('fs.read', () => {
    if (file === undefined) throw new Error('ENOENT')
    return { value: file }
  })
  on('fs.write', (_$: any, e: any) => {
    writes.push(e.path + '\n' + e.text)
    return { value: undefined }
  })
}

for (const surface of ['terminal', 'desktop'] as const) {
  test('駕駛艙額度區（' + surface + '）：5h／週、重置、上一輪 token、寫入 usage.json', async ($, on) => {
    const writes: string[] = []
    quotaSetup(on, writes, JSON.stringify({ v: 1, claude: { net: 7 } }))
    await $.session.start({ surface, isInteractive: true, cwd: '/work' })
    expect(writes.length).toBe(1)
    const [path, text] = writes[0].split('\n')
    expect(path).toBe('/home/u/.claude/chutora/usage.json')
    const j = JSON.parse(text)
    expect(j.claude).toEqual({ net: 7 })
    expect(j.limits.source).toBe('claude-mod')
    expect(j.limits.updated_at).toBe(Math.floor(T0 / 1000))
    expect(j.limits.five_hour.pct).toBe(42)

    await $.session.measure({ context: {}, rateLimits: [{ kind: 'five_hour', percentUsed: 97, resetsAt: '2026-11-09T09:30:00.000Z' }], changed: ['rateLimits'] } as any)
    await $.turn.complete({ turnId: 't1', answer: '', durationMs: 5, isAborted: false, reason: 'end_turn', usage: { model: 'claude-opus-5-5', input_tokens: 12, output_tokens: 300, cache_read_input_tokens: 90000, cache_creation_input_tokens: 1500 } } as any)
    const ui = await $.ui.mount({
      plugin: 'agent-board', component: 'Pane', requestId: 'agent-board', surface,
      viewport: { columns: 100, rows: 40 },
      props: { title: '駕駛艙', isFocused: true, bodyColumns: 70, placement: 'inline', scroll: { offset: 0, bodyRows: 30 }, view: {} },
    } as any)
    expect(await ui.find({ type: 'Text', text: /^總額度（不含分模型）$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^97%$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /重置 1h30m 後/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /上一輪 token：輸入 12 · 快取寫 1\.5k · 快取讀 90k · 輸出 300/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /沒有額度讀數/ })).toBeUndefined()
    await ui.unmount()
  })
}

test('駕駛艙額度區：沒有讀數（非訂閱）顯示「沒有額度讀數」，英文版跟 lang', async ($, on) => {
  const writes: string[] = []
  quotaSetup(on, writes, undefined, { rateLimits: [] }, 'en')
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(writes.length).toBe(0)
  const mount = () => $.ui.mount({
    plugin: 'agent-board', component: 'Pane', requestId: 'agent-board', surface: 'terminal',
    viewport: { columns: 100, rows: 40 },
    props: { title: '駕駛艙', isFocused: true, bodyColumns: 70, placement: 'inline', scroll: { offset: 0, bodyRows: 30 }, view: {} },
  } as any)
  const ui = await mount()
  expect(await ui.find({ type: 'Text', text: /^No usage reading$/ })).toBeDefined()
  await ui.unmount()
  expect(DECK_LABELS.zh.noQuota).toBe('沒有額度讀數')
})

test('額度寫檔失敗時安靜略過，且檔案較新時不覆蓋', async ($, on) => {
  const writes: string[] = []
  quotaSetup(on, writes, JSON.stringify({ v: 1, limits: { source: 'statusline', updated_at: Math.floor(T0 / 1000) + 50 } }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(writes.length).toBe(0)
})
