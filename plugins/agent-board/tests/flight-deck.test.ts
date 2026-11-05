import { expect, mock, test } from 'claude-code/testing'
import { plain, newDeck, callStart, callEnd, todoProgress, addUsage, workload, progressSvg, workloadSvg, iconSvg } from '../hooks/deck-logic.js'

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
