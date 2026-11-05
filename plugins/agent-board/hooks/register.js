import {
  agentLine,
  countActive,
  isActive,
  layoutRow,
  recordUsage,
  shouldAutoOpen,
  shouldStayOpen,
  showDetailButton,
  DETAIL_MODE_CONTEXT,
  replyModeLabel,
  sortAgents,
  summarizeUsage,
  collapsedLabel,
} from './board-logic.js'
import { newDeck, callStart, callEnd, addUsage, runningCount, family } from './deck-logic.js'
import { renderDeck, DECK_LABELS } from './deck-view.js'

const PANE = 'agent-board'
const paneTitle = () => (lang === 'en' ? 'Flight Deck' : '駕駛艙')

// 計時器與快取在模組層級；reload 時 register 會重跑，狀態會歸零
let timer = null
let agents = []
let nowMs = 0
// 面板縮小時只畫一顆按鈕；記住使用者的選擇，自動開啟時沿用
let collapsed = false
// 依 agentId 累計的 token／金額（來自 turn.step 的 usage）
const usageByAgent = new Map()
// 依 agentId 記開始／結束時間與 spawn 解析後的模型：{ start, end, model }
const metaByAgent = new Map()
// 使用者用 /agent-board 關掉後，常駐模式就不再自動重開，直到再用 /agent-board 打開
let userClosed = false
// 回覆模式：'concise'（預設，照 reply-detail 的精簡版）或 'detail'（每則回覆都寫詳細版）；reload 後回到精簡
let replyMode = 'concise'
// 駕駛艙：主對話與子 agent 的動作時間線、檔案、待辦與工作量（reload 後歸零）
let deck = newDeck()
// agentId → { type, model }：時間線用來標子 agent
const agentInfo = new Map()
let lang = 'zh'
let rawMode = false
let showRead = false
let mainModel = ''
let savedTokens = 0
let savedReadAt = 0
let redrawPending = false

// 重繪節流：連續的工具呼叫最多每 250ms 重畫一次
function redraw($) {
  if (redrawPending) return
  redrawPending = true
  $.clock.after(250, () => {
    redrawPending = false
    $.ui.invalidate('ui.render')
  })
}

// 語言：CHUTORA_LANG → ~/.claude/chutora/lang（/chutora lang 寫入）→ LC_ALL／LANG → 中文
async function detectLang($) {
  const pick = (v) => {
    const s = String(v || '').trim().toLowerCase()
    return s.startsWith('zh') ? 'zh' : s.startsWith('en') ? 'en' : null
  }
  try {
    const env = pick(await $.env.get('CHUTORA_LANG'))
    if (env) return env
    const home = await $.env.get('HOME')
    if (home) {
      try {
        const f = pick(await $.fs.read(home + '/.claude/chutora/lang'))
        if (f) return f
      } catch (err) {
        // 沒有語言檔
      }
    }
    const loc = (await $.env.get('LC_ALL')) || (await $.env.get('LC_MESSAGES')) || (await $.env.get('LANG'))
    if (loc) return String(loc).toLowerCase().startsWith('zh') ? 'zh' : 'en'
  } catch (err) {
    // 讀不到環境就用中文
  }
  return 'zh'
}

// 這個 session 瘦身／去重／MCP 瘦身擋下的量（chutora 的 activity 檔，字元 ÷4 估算 token），最多每 5 秒讀一次
async function readSaved($) {
  const now = await $.clock.now()
  if (now - savedReadAt < 5000) return
  savedReadAt = now
  try {
    const home = await $.env.get('HOME')
    const sid = await $.session.id()
    if (!home || !sid || !/^[A-Za-z0-9_.-]+$/.test(sid)) return
    const st = JSON.parse(await $.fs.read(home + '/.claude/chutora/activity/' + sid + '.json'))
    const sv = (st && st.saved) || {}
    savedTokens = Math.floor(Object.values(sv).reduce((s, v) => s + (typeof v === 'number' ? v : 0), 0) / 4)
  } catch (err) {
    // 沒裝 chutora 或還沒有紀錄
  }
}

// 面板要真的放上畫面才算開著：$.ui.panes() 也會列出等待放置（isPlaced: false）的面板
async function isShown($) {
  const panes = await $.ui.panes()
  return panes.some((p) => p.id === PANE && p.isPlaced !== false)
}

// 常駐模式：面板不在畫面上就重開。
// 引擎對非使用者觸發的 ui.open 有寬度門檻（沒手動開過要 144 欄、開過要 110 欄），
// VS Code 的聊天面板常常不夠寬，session.start 開的面板就停在未放置；
// 畫面重連、寬度改變、回合開始與結束時都檢查一次，其中 turn.start 由使用者送出訊息觸發，不受門檻限制
async function ensureOpen($, options) {
  if (!shouldStayOpen(options) || userClosed) return
  try {
    if (!(await isShown($))) await $.ui.open({ id: PANE, title: paneTitle() })
  } catch (err) {
    $.ui.log('agent-board：' + err.message, { to: 'debug' })
  }
}

// 重新讀 agent 清單、更新狀態列；有進行中的 agent 就確保計時器在跑，沒有就停掉
async function refresh($) {
  agents = await $.agent.list()
  nowMs = await $.clock.now()
  await readSaved($)
  // 第一次看到不再進行中的 agent 時記下結束時間，之後經過時間就不再增加
  for (const a of agents) {
    const m = metaByAgent.get(a.id)
    if (m && m.end === undefined && !isActive(a)) m.end = nowMs
  }
  // 狀態列附上開啟方式：面板關掉後沒有按鈕能再打開，只能靠 /agent-board
  const line = summarizeUsage(agents, usageByAgent)
  $.ui.status(line && line + '・/agent-board 開關')
  $.ui.invalidate('ui.render')
  if (countActive(agents) > 0 || runningCount(deck) > 0) {
    if (timer === null) {
      timer = $.clock.every(1000, () => refresh($))
    }
  } else if (timer !== null) {
    timer.cancel()
    timer = null
  }
}

export function register(on, options) {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'agent-board',
      description: '開關子 agent 狀態看板',
      // 子 agent 在跑時主對話的 turn 通常還沒結束，不設 immediate 會等到 turn 結束才開
      immediate: true,
    })
    lang = await detectLang($)
    // 常駐模式：一開始就開面板（不帶 focus），沒有子 agent 時顯示「目前沒有子 agent」
    await ensureOpen($, options)
    return next(e)
  })

  // 畫面（VS Code webview、終端機）連上或寬度改變時，補開沒放上畫面的面板
  on('session.attach', async ($, e, next) => {
    const result = await next(e)
    await ensureOpen($, options)
    return result
  })
  on('session.measure', async ($, e, next) => {
    const result = await next(e)
    await ensureOpen($, options)
    return result
  })

  // 子 agent 即將啟動：先開面板（不帶 focus）再交出事件，
  // 因為文件沒寫 next 是在 agent 開始還是結束時返回，先開才保證是即時的
  on('agent.spawn', async ($, e, next) => {
    // 看板出錯不能影響子 agent 本身的啟動
    try {
      if (shouldAutoOpen(options)) {
        await $.ui.open({ id: PANE, title: paneTitle() })
      }
    } catch (err) {
      $.ui.log('agent-board：' + err.message, { to: 'debug' })
    }
    let startMs
    try {
      startMs = await $.clock.now()
    } catch (err) {
      $.ui.log('agent-board：' + err.message, { to: 'debug' })
    }
    const result = await next(e)
    try {
      if (result && result.agentId) {
        metaByAgent.set(result.agentId, { start: startMs, end: undefined, model: result.model })
        agentInfo.set(result.agentId, { type: String(e.subagentType || 'agent').split(':').pop(), model: family(result.model) })
      }
      await refresh($)
      // agent 可能還沒出現在清單上，稍後補一次，避免計時器因「沒有進行中」而停掉
      $.clock.after(1500, () => refresh($))
    } catch (err) {
      $.ui.log('agent-board：' + err.message, { to: 'debug' })
    }
    return result
  }).catch(($, e, next) => next(e))

  // 子 agent 的每次模型請求：完成後把 usage 累加起來。主對話（沒有 agentId）直接放行。
  // 記錄出錯不能影響請求，結果一定原樣回傳。只讀 usage，不呼叫模型、不寫對話紀錄。
  on('turn.step', async function* ($, e, next) {
    const result = yield* next(e)
    try {
      if (e.agentId && recordUsage(usageByAgent, e.agentId, result && result.usage, e.model)) {
        $.ui.invalidate('ui.render')
      }
      if (!e.agentId && e.model) mainModel = family(e.model)
      if (addUsage(deck, result && result.usage, e.model, !e.agentId)) redraw($)
    } catch (err) {
      // 不能讓看板的錯誤影響請求
    }
    return result
  })

  // 使用者送出下一則訊息時，若沒有進行中的 agent 就收起面板（常駐模式不收）
  on('turn.start', async ($, e, next) => {
    if (shouldStayOpen(options)) {
      await ensureOpen($, options)
      return next(e)
    }
    agents = await $.agent.list()
    if (countActive(agents) === 0) {
      await $.ui.close({ id: PANE })
    }
    return next(e)
  })

  // 回合結束時再檢查一次（例如回合中途畫面重連過）
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await ensureOpen($, options)
    return result
  })

  // 駕駛艙：記下每一次工具呼叫（主對話與子 agent）。只觀察不改動：結果一定原樣回傳，
  // 記錄出錯也不影響工具；.catch 讓 hook 失敗時照常放行（已呼叫過 next 就重播同一個結果）
  on('tool.call', async ($, e, next) => {
    let id
    try {
      const now = await $.clock.now()
      id = callStart(deck, e, now, agentInfo, lang).id
      if (timer === null) refresh($)
      redraw($)
    } catch (err) {
      id = undefined
    }
    const ran = await next(e)
    try {
      if (id !== undefined) {
        callEnd(deck, id, ran, await $.clock.now())
        redraw($)
      }
    } catch (err) {
      // 看板的錯誤不能影響工具結果
    }
    return ran
  }).catch(($, e, next) => next(e))

  // 回覆模式為詳細時，在使用者送出的訊息附上詳細版要求；系統產生的訊息（isMeta）不動
  on('prompt.submit', async ($, e, next) => {
    if (replyMode !== 'detail' || e.isMeta) return next(e)
    return next({ ...e, context: [...(e.context || []), DETAIL_MODE_CONTEXT] })
  }).catch(($, e, next) => next(e))

  // /agent-board：開關面板，自己處理完不呼叫 next。
  // 用 isPlaced 判斷：看不見的面板也在清單裡，只看 id 會把它當成開著而關掉
  on('command.run', { command: 'agent-board' }, async ($) => {
    if (await isShown($)) {
      userClosed = true
      await $.ui.close({ id: PANE })
    } else {
      userClosed = false
      await $.ui.open({ id: PANE, title: paneTitle(), closeOnEscape: true })
      await refresh($)
    }
    return {}
  })

  on('ui.render', { component: 'Pane' }, async ($, e, next) => {
    if (e.requestId !== PANE) return next(e)
    const el = $.ui.resolve(e)
    const { Box, Text, Button } = el
    const t = DECK_LABELS[lang] || DECK_LABELS.zh

    const summary = summarizeUsage(agents, usageByAgent) || (lang === 'en' ? 'No subagents' : '目前沒有子 agent')
    const toggle = () => {
      collapsed = !collapsed
      $.ui.invalidate('ui.render')
    }
    // 底部按鈕列：白話／原始指令、可關掉的回覆模式切換鍵、縮小／展開
    const switchMode = () => {
      replyMode = replyMode === 'detail' ? 'concise' : 'detail'
      $.ui.invalidate('ui.render')
    }
    const detail = !showDetailButton(options)
      ? []
      : [Button({ key: 'mode', label: replyModeLabel(replyMode), onPress: switchMode })]
    const buttonRow = (first) => Box({ flexDirection: 'row', gap: 1, children: [first, ...detail] })
    if (collapsed) {
      return Box({
        flexDirection: 'column',
        children: [buttonRow(Button({ key: 'expand', label: '▸ ' + collapsedLabel(agents, usageByAgent), onPress: toggle }))],
      })
    }

    const columns = e.props && e.props.bodyColumns
    const rows = sortAgents(agents).flatMap((a) =>
      layoutRow(
        agentLine(a, usageByAgent.get(a.id), metaByAgent.get(a.id), nowMs),
        a.description,
        columns
      ).map((line, i) =>
        Text({ key: 'row-' + a.id + '-' + i, dimColor: i > 0, children: [line] })
      )
    )
    const subagentSection = [
      Text({ size: 'caption', dimColor: true, children: [lang === 'en' ? 'Subagents' : '子 agent'] }),
      Text({ bold: true, children: [summary] }),
      ...rows,
      Text({ dimColor: true, size: 'caption', children: ['金額為估計（API 牌價）'] }),
    ]
    const footer = Box({
      key: 'ft', flexDirection: 'row', gap: 1, children: [
        Button({ key: 'plain', label: (rawMode ? '' : '● ') + t.plain, onPress: () => { rawMode = false; $.ui.invalidate('ui.render') } }),
        Button({ key: 'raw', label: (rawMode ? '● ' : '') + t.raw, onPress: () => { rawMode = true; $.ui.invalidate('ui.render') } }),
        ...detail,
        Box({ flexGrow: 1, children: [] }),
        Button({ key: 'collapse', label: t.collapse, onPress: toggle }),
      ],
    })
    return renderDeck(el, {
      deck, now: nowMs || (await $.clock.now()), lang, surface: e.surface, columns, rawMode, showRead, mainModel,
      savedTokens, subagentSection, footer,
      toggleRead: () => { showRead = !showRead; $.ui.invalidate('ui.render') },
    })
  })
}
