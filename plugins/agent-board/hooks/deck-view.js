// 駕駛艙面板的畫面：桌面版／VS Code／手機用 Svg 畫進度格、工作量長條與像素圖示；終端機用文字與色塊畫同樣的區塊。
import {
  COLORS, currentEvent, familyColor, iconSvg, liveDotSvg, progressSvg, workloadSvg, todoProgress, workload,
  runningCount, blockBar, progressCells, statusMark, statusColor, quotaSvg, pctColor, resetLabel,
} from './deck-logic.js'
import { formatElapsed, formatTokens, truncate } from './board-logic.js'

const L = {
  zh: {
    title: '駕駛艙', live: '執行中', idle: '待命', now: '現在', nothing: '還沒有動作', nth: (n) => `第 ${n} 個動作`,
    todo: '待辦進度', next: '下一項', work: '這次的工作量', delegated: '工作交給 Sonnet／Haiku',
    trimmed: '瘦身與去重擋下（估算）', ctx: '主對話 context', timeline: '動作時間線', files: '碰過的檔案',
    edited: '改過', read: '讀過', expand: '展開 ▸', fold: '收起 ▾', plain: '白話', raw: '原始指令',
    collapse: '▾ 縮小', main: '主對話', none: '—', doing: '正在', did: '剛完成', failed: '失敗',
    quota: '總額度（不含分模型）', h5: '5 小時', wk: '每週', reset: '重置', noQuota: '沒有額度讀數', lastTurn: '上一輪 token',
    tIn: '輸入', tCw: '快取寫', tCr: '快取讀', tOut: '輸出',
  },
  en: {
    title: 'Flight Deck', live: 'Running', idle: 'Idle', now: 'Now', nothing: 'No actions yet', nth: (n) => `action #${n}`,
    todo: 'To-do progress', next: 'Next', work: 'Workload this session', delegated: 'handed to Sonnet/Haiku',
    trimmed: 'kept out by trimming (est.)', ctx: 'main context', timeline: 'Timeline', files: 'Files touched',
    edited: 'Edited', read: 'Read', expand: 'Show ▸', fold: 'Hide ▾', plain: 'Plain', raw: 'Raw',
    collapse: '▾ Collapse', main: 'main', none: '—', doing: '', did: 'Just did', failed: 'Failed',
    quota: 'Usage limits (all models)', h5: '5-hour', wk: 'Weekly', reset: 'resets', noQuota: 'No usage reading', lastTurn: 'Last turn tokens',
    tIn: 'in', tCw: 'cache write', tCr: 'cache read', tOut: 'out',
  },
}

const dur = (ev, now) => formatElapsed((ev.end ?? now) - ev.start)
const base = (p) => String(p).split('/').pop()

// 一個 agent 標籤：Opus 橘、Sonnet 紫、Haiku 藍
function whoTag(ev, mainModel) {
  const fam = ev.who === 'main' ? mainModel || 'Opus' : ev.model || 'Sonnet'
  return { label: ev.who === 'main' ? fam : ev.who, color: familyColor(fam) }
}

export function renderDeck(el, ctx) {
  const { Box, Text, Button, Svg } = el
  const { deck, now, lang, surface, columns, rawMode, showRead, mainModel, savedTokens, subagentSection, footer } = ctx
  const t = L[lang] || L.zh
  const graphic = surface !== 'terminal' && typeof Svg === 'function'
  const cols = typeof columns === 'number' && columns > 0 ? columns : 60
  const px = Math.max(220, Math.min(520, Math.round(cols * 7.2)))
  const cur = currentEvent(deck)
  const active = runningCount(deck) > 0
  const prog = todoProgress(deck)
  const wl = workload(deck)
  const label = (s) => Text({ size: 'caption', dimColor: true, children: [s] })
  const section = (key, children) => Box({ key, flexDirection: 'column', gap: graphic ? 1 : 0, paddingY: graphic ? 1 : 0, children })

  // 頂端
  const elapsedAll = deck.started !== undefined ? formatElapsed(now - deck.started) : ''
  const header = Box({
    key: 'hd', flexDirection: 'row', alignItems: 'center', gap: 1,
    children: [
      graphic ? Svg({ key: 'logo', source: iconSvg('chute', 22), alt: 'Chutora', width: 22, height: 22 }) : Text({ color: COLORS.orange, children: ['▲'] }),
      Text({ bold: true, weight: 'bold', size: 'heading', children: [t.title] }),
      lang === 'zh' ? Text({ dimColor: true, size: 'caption', children: ['Flight Deck'] }) : null,
      Box({ flexGrow: 1, children: [] }),
      graphic ? Svg({ key: 'dot', source: liveDotSvg(active), alt: active ? t.live : t.idle, width: 14, height: 14 }) : Text({ color: active ? COLORS.ok : COLORS.mute, children: ['■'] }),
      Text({ color: active ? COLORS.ok : COLORS.mute, mono: true, children: [(active ? t.live : t.idle) + (elapsedAll ? ' ' + elapsedAll : '')] }),
    ].filter(Boolean),
  })

  // 現在
  let nowCard
  if (!cur) {
    nowCard = Text({ dimColor: true, children: [t.nothing] })
  } else {
    const tag = whoTag(cur, mainModel)
    const verb = cur.status === 'running' ? t.doing : cur.status === 'error' ? t.failed + ' · ' : t.did + ' · '
    const idx = deck.events.indexOf(cur) + 1
    nowCard = Box({
      key: 'now', flexDirection: 'row', alignItems: 'center', gap: 1, paddingX: 1, paddingY: graphic ? 1 : 0,
      borderStyle: 'round', borderColor: cur.status === 'error' ? COLORS.bad : COLORS.orange2,
      children: [
        graphic ? Svg({ key: 'nowicon', source: iconSvg(cur.icon, 28), alt: cur.text, width: 28, height: 28 }) : null,
        Box({
          flexDirection: 'column', flexGrow: 1, children: [
            Box({ flexDirection: 'row', gap: 1, children: [
              Text({ color: tag.color, bold: true, children: [tag.label + (cur.model && cur.who !== 'main' ? ' · ' + cur.model : '')] }),
              Text({ bold: true, weight: 'bold', children: [verb + cur.text] }),
            ] }),
            cur.raw && cur.raw !== cur.text ? Text({ mono: true, dimColor: true, size: 'footnote', wrap: 'truncate-end', children: [cur.raw] }) : null,
          ].filter(Boolean),
        }),
        Box({ flexDirection: 'column', alignItems: 'flex-end', children: [
          Text({ bold: true, mono: true, color: cur.status === 'running' ? COLORS.ink : statusColor(cur), children: [dur(cur, now)] }),
          Text({ dimColor: true, size: 'caption', children: [t.nth(idx)] }),
        ] }),
      ].filter(Boolean),
    })
  }
  const parts = [header, section('s-now', [label(t.now), nowCard])]

  // 額度：5 小時／每週用量（附進度條與重置時間），與上一輪 token（主對話）
  {
    const lim = (deck.quota && deck.quota.limits) || {}
    const last = deck.quota && deck.quota.lastTurn
    const winRow = (key, name, w) => {
      const pct = Math.round(w.pct)
      const barW = Math.max(120, Math.min(px, 320))
      const bar = graphic
        ? Svg({ key: 'qb-' + key, source: quotaSvg(w.pct, barW), alt: `${pct}%`, width: barW, height: 10 })
        : Box({ flexDirection: 'row', children: blockBar([[Math.min(100, w.pct), pctColor(w.pct)], [Math.max(0, 100 - w.pct), COLORS.empty]].filter(([v]) => v > 0), 20).map((p, i) => Text({ key: 'q' + key + i, color: p.color, children: [p.text] })) })
      const rs = resetLabel(w.resets_at, now, lang)
      return Box({ key: 'qr-' + key, flexDirection: 'row', alignItems: 'center', gap: 1, children: [
        Text({ dimColor: true, children: [name] }),
        Text({ bold: true, mono: true, color: pctColor(w.pct), children: [pct + '%'] }),
        bar,
        rs ? Text({ dimColor: true, size: 'caption', children: [t.reset + ' ' + rs] }) : null,
      ].filter(Boolean) })
    }
    const rows = [
      lim.five_hour ? winRow('h5', t.h5, lim.five_hour) : null,
      lim.seven_day ? winRow('wk', t.wk, lim.seven_day) : null,
    ].filter(Boolean)
    const tk = last
      ? Text({ mono: true, children: [`${t.lastTurn}：${t.tIn} ${formatTokens(last.input)} · ${t.tCw} ${formatTokens(last.cache_write)} · ${t.tCr} ${formatTokens(last.cache_read)} · ${t.tOut} ${formatTokens(last.output)}`] })
      : null
    parts.push(section('s-quota', [label(t.quota), ...(rows.length ? rows : [Text({ dimColor: true, children: [t.noQuota] })]), tk].filter(Boolean)))
  }

  // 待辦進度
  if (prog) {
    const bar = graphic
      ? Svg({ key: 'prog', source: progressSvg(prog.states, px), alt: `${prog.done}/${prog.total}`, width: px, height: 10 })
      : Box({ flexDirection: 'row', children: progressCells(prog.states).map((c, i) => Text({ key: 'c' + i, color: c.color, children: [c.text + ' '] })) })
    parts.push(section('s-todo', [
      Box({ flexDirection: 'row', children: [label(t.todo), Box({ flexGrow: 1, children: [] }), Text({ mono: true, children: [`${prog.done} / ${prog.total}`] })] }),
      bar,
      prog.current || prog.next
        ? Text({ wrap: 'truncate-end', children: [(prog.current ? '▸ ' + prog.current : '') + (prog.next ? (prog.current ? ' · ' : '') + t.next + '：' + prog.next : '')] })
        : null,
    ].filter(Boolean)))
  }

  // 工作量
  const legend = Box({ flexDirection: 'row', gap: 2, flexWrap: 'wrap', children: [
    ['Opus', wl.opus], ['Sonnet', wl.sonnet], ['Haiku', wl.haiku],
  ].map(([n, v]) => Box({ key: 'lg' + n, flexDirection: 'row', gap: 1, children: [
    Text({ color: familyColor(n), children: ['■'] }), Text({ dimColor: true, children: [n] }), Text({ bold: true, children: [formatTokens(v)] }),
  ] })) })
  const bar = graphic
    ? Svg({ key: 'wl', source: workloadSvg(wl, px), alt: 'workload', width: px, height: 14 })
    : Box({ flexDirection: 'row', children: blockBar([[wl.opus, COLORS.opus], [wl.sonnet, COLORS.sonnet], [wl.haiku, COLORS.haiku], [wl.other, COLORS.mute]].filter(([v]) => v > 0), Math.max(10, Math.min(cols - 2, 48))).map((p, i) => Text({ key: 'b' + i, color: p.color, children: [p.text] })) })
  const stat = (key, big, small) => Box({
    key, flexDirection: 'column', flexGrow: 1, paddingX: 1, borderStyle: graphic ? 'round' : undefined, borderColor: COLORS.line,
    children: [Text({ bold: true, weight: 'bold', size: graphic ? 'title' : undefined, children: [big] }), Text({ dimColor: true, size: 'caption', children: [small] })],
  })
  const stats = [
    stat('st1', wl.total ? Math.round(wl.delegated * 100) + '%' : t.none, t.delegated),
    stat('st2', savedTokens > 0 ? '≈' + formatTokens(savedTokens) : t.none, t.trimmed),
    stat('st3', deck.mainContext ? formatTokens(deck.mainContext) : t.none, t.ctx),
  ]
  parts.push(section('s-work', [label(t.work), bar, legend, Box({ flexDirection: graphic ? 'row' : 'column', gap: 1, children: stats })]))

  // 時間線（最新的在下面，跟對話方向一致）
  const rows = deck.events.slice(-14).map((ev) => {
    const tag = whoTag(ev, mainModel)
    const sub = ev.who !== 'main'
    const title = ev.text + (ev.count > 1 ? ' ×' + ev.count : '')
    return Box({
      key: 'ev-' + ev.id, flexDirection: 'row', alignItems: 'center', gap: 1, paddingLeft: sub ? 2 : 0,
      children: [
        Text({ color: tag.color, bold: true, children: [truncate(tag.label, 10)] }),
        graphic ? Svg({ key: 'i-' + ev.id, source: iconSvg(ev.icon, 16), alt: ev.icon, width: 16, height: 16 }) : null,
        Box({ flexDirection: 'column', flexGrow: 1, children: [
          Text({ wrap: 'truncate-end', children: [rawMode ? ev.raw || ev.text : title] }),
          !rawMode && graphic && ev.raw && ev.raw !== ev.text ? Text({ mono: true, dimColor: true, size: 'caption', wrap: 'truncate-end', children: [ev.raw] }) : null,
        ].filter(Boolean) }),
        Text({ color: statusColor(ev), mono: true, children: [statusMark(ev) + ' ' + dur(ev, now)] }),
      ].filter(Boolean),
    })
  })
  parts.push(section('s-tl', [label(t.timeline), ...(rows.length ? rows : [Text({ dimColor: true, children: [t.nothing] })])]))

  // 碰過的檔案
  if (deck.edited.size || deck.read.size) {
    const edited = [...deck.edited].slice(-8).map(([p, d]) => Box({ key: 'f-' + p, flexDirection: 'row', gap: 1, children: [
      Text({ mono: true, children: [truncate(base(p), 30)] }),
      Text({ color: COLORS.ok, mono: true, children: ['+' + d.plus] }),
      d.minus ? Text({ color: COLORS.bad, mono: true, children: ['−' + d.minus] }) : null,
    ].filter(Boolean) }))
    const readList = showRead ? [...deck.read].slice(-12).map((p) => Text({ key: 'r-' + p, mono: true, dimColor: true, children: [truncate(base(p), 36)] })) : []
    parts.push(section('s-files', [
      label(t.files),
      deck.edited.size ? Text({ dimColor: true, size: 'caption', children: [`${t.edited} ${deck.edited.size}`] }) : null,
      Box({ flexDirection: graphic ? 'row' : 'column', flexWrap: 'wrap', gap: 1, children: edited }),
      deck.read.size ? Box({ flexDirection: 'row', gap: 1, alignItems: 'center', children: [
        Text({ dimColor: true, size: 'caption', children: [`${t.read} ${deck.read.size}`] }),
        ctx.toggleRead ? Button({ key: 'readtoggle', label: showRead ? t.fold : t.expand, onPress: ctx.toggleRead }) : null,
      ].filter(Boolean) }) : null,
      ...readList,
    ].filter(Boolean)))
  }

  if (subagentSection) parts.push(section('s-sub', subagentSection))
  if (footer) parts.push(footer)
  return Box({ flexDirection: 'column', gap: graphic ? 1 : 0, padding: graphic ? 1 : 0, backgroundColor: graphic ? COLORS.bg : undefined, children: parts })
}

export { L as DECK_LABELS }
