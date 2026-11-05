/* HenanDiary 前端。pywebview 把后端 Api 方法挂在 window.pywebview.api.*，全部返回 Promise。 */

const api = () => {
  // pywebview 注入有延迟，所有调用统一走这个入口判空
  if (window.pywebview && window.pywebview.api) return window.pywebview.api;
  return null;
};

const $ = (id) => document.getElementById(id);

async function call(method, ...args) {
  const a = api();
  if (!a) { toast('后端未就绪，请稍候重试'); return null; }
  try {
    const r = await a[method](...args);
    if (r && r.error) toast(r.error);
    return r;
  } catch (e) {
    toast('调用失败：' + e);
    return null;
  }
}

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 5000);
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

/* ---------------------------------------------------------------- 日期工具 */

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

/* 日期本身就是页标题：日记本的做法，不写成「今日总览」这种栏目名 */
function cnDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return `${y} 年 ${m} 月 ${d} 日`;
}

/* 用本地时间构造，避免 UTC 在东八区跨天（周报区间曾在这里出过 bug） */
function weekdayOf(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return WEEKDAYS[new Date(y, m - 1, d).getDay()];
}

/* 后端时间戳是 ISO8601，界面上只关心时分；解析不出来给破折号，不留空白 */
function clockOf(iso) {
  return typeof iso === 'string' && iso.length >= 16 ? iso.slice(11, 16) : '—';
}

/* 周报按「周一 ~ 周日」这一段存，列表里标出范围，避免把 week_start 误读成某一天。 */
function weekRange(weekStart) {
  const [y, m, d] = weekStart.split('-').map(Number);
  const end = new Date(y, m - 1, d + 6);
  const mm = String(end.getMonth() + 1).padStart(2, '0');
  const dd = String(end.getDate()).padStart(2, '0');
  return `${weekStart} ~ ${mm}-${dd}`;
}

/* 极简 Markdown 渲染：够吃日报的 ## 标题 / 列表 / 段落 / 粗体 / 行内代码。
   不引第三方库（需求确认：无构建、无前端框架）。 */
function renderMarkdown(md) {
  const lines = md.split(/\r?\n/);
  let html = '', inUl = false, inOl = false;
  const closeLists = () => {
    if (inUl) { html += '</ul>'; inUl = false; }
    if (inOl) { html += '</ol>'; inOl = false; }
  };
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
  for (const line of lines) {
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    const o = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const tag = h ? `h${Math.min(h[1].length + 1, 4)}` : '';
    if (h) { closeLists(); html += `<${tag}>${inline(h[2])}</${tag}>`; }
    else if (li) {
      if (inOl) { html += '</ol>'; inOl = false; }
      if (!inUl) { html += '<ul>'; inUl = true; }
      html += `<li>${inline(li[1])}</li>`;
    } else if (o) {
      if (inUl) { html += '</ul>'; inUl = false; }
      if (!inOl) { html += '<ol>'; inOl = true; }
      html += `<li>${inline(o[1])}</li>`;
    } else if (!line.trim()) { closeLists(); }
    else { closeLists(); html += `<p>${inline(line)}</p>`; }
  }
  closeLists();
  return html;
}

/* 摘要卡只吃第一个 ## 章节：「今天做了什么」是导语，混进「时间分布」就成了病句。
   列表项之间用「；」，段落之间用空格——纯空格连起来的几条读着没有停顿。 */
function mdExcerpt(md, limit) {
  const lines = md.split(/\r?\n/);
  const head = lines.findIndex(l => /^##\s+/.test(l));
  let text = '';
  if (head >= 0) {
    const rest = lines.slice(head + 1);
    const next = rest.findIndex(l => /^##\s+/.test(l));
    text = joinExcerpt(next >= 0 ? rest.slice(0, next) : rest);
  }
  /* 没有 ## 标题、或第一节是空的（连着两个标题）：退回整段，别输出空摘要 */
  if (!text) text = joinExcerpt(lines);
  text = text.replace(/[；;]$/, '');
  return text.length > limit ? text.slice(0, limit).trimEnd() + '…' : text;
}

function joinExcerpt(lines) {
  let out = '', prevItem = false;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || /^#{1,6}\s/.test(line)) continue;
    const isItem = /^([-*]|\d+[.)])\s+/.test(line);
    if (out) {
      if (prevItem && isItem) {
        if (!/[。；！？]$/.test(out)) out += '；';   // 上一项已经收过句就不再加分号
      } else out += ' ';
    }
    out += line.replace(/^([-*]|\d+[.)])\s+/, '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/`(.+?)`/g, '$1');
    prevItem = isItem;
  }
  return out;
}

/* ---------------------------------------------------------------- 导航 */

function go(page) {
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('on', b.dataset.p === page));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('on'));
  $('p-' + page).classList.add('on');
  $('main').scrollTop = 0;   // 换页回到页首，否则从长页跳过去会落在半山腰
  if (page === 'overview') loadOverview().then(() => loadOverviewUsage());
  if (page === 'timeline') loadTimelineDates();
  if (page === 'report') loadReports();
  if (page === 'logs') loadLogs(true);
  if (page === 'settings') loadSettingsForm();
}
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => go(b.dataset.p)));

/* ---------------------------------------------------------------- 总览 */

/* 后端认定的「今天」。总览页里涉及日期的取数都用它，避免前端各算一次（跨零点会错位）。 */
let _today = null;

async function loadOverview() {
  const s = await call('get_state');
  if (!s || s.error) return;
  _today = s.date;
  const c = s.capture, rp = s.report;
  const pending = rp.pending.length;

  $('ov-date').textContent = cnDate(s.date);
  $('ov-weekday').textContent = weekdayOf(s.date);
  $('ov-hours').textContent = `${c.work_hours.start}–${c.work_hours.end}`;
  $('ov-records').textContent = c.count_today;
  $('ov-count').textContent = c.count_today;
  $('ov-count-note').textContent = c.last_ts ? `最近 ${clockOf(c.last_ts)}` : '—';
  $('ov-next').textContent = c.enabled ? clockOf(c.next_ts) : '已暂停';
  /* interval_min 缺失时（老版本配置或残缺负载）不硬拼出「undefined 分钟」 */
  $('ov-interval-note').textContent = !c.enabled ? '采集已暂停'
    : (c.interval_min ? `每 ${c.interval_min} 分钟一次` : '按间隔采样');
  $('ov-time').textContent = rp.daily_time;
  $('ov-time-note').textContent = rp.today_generated
    ? (rp.today_overwritten ? '已生成 · 覆盖版' : '已生成') : '待生成';
  /* 总时长只有 get_app_usage 里有。本日已取过就沿用缓存：10 秒轮询也走这里，
     每轮都抹回占位符的话，数字会一亮一灭地闪 */
  if (!_ovUsage || _ovUsageDate !== s.date) {
    $('ov-total').textContent = '—';
    $('ov-total-note').textContent = '按采样估算';
  }

  const ai = $('ov-ai');
  ai.className = pending ? 'tag bad' : 'tag ok';
  ai.textContent = pending ? `${pending} 笔待重试` : '正常';

  const badge = $('ov-report-badge');
  badge.className = rp.today_generated ? 'tag ok' : 'tag wait';
  badge.textContent = rp.today_generated
    ? (rp.today_overwritten ? '已生成 · 覆盖版' : '已生成')
    : `待生成 · ${rp.daily_time}`;

  const pend = $('ov-pending');
  if (pending) {
    pend.style.display = 'block';
    $('ov-pending-list').innerHTML = rp.pending.map(p =>
      `<div class="pending-row"><span class="num">${esc(p.date)}</span>`
      + `<span>${esc(p.type)}</span><span>${esc(p.reason)}</span></div>`).join('');
  } else pend.style.display = 'none';

  $('btn-toggle-capture').textContent = c.enabled ? '暂停采集' : '继续采集';
  $('ov-ex-capture').textContent = c.enabled ? '运行中' : '已暂停';
  $('ov-ex-ai').textContent = pending ? `${pending} 笔待重试` : '正常';
  $('ov-ex-pending').textContent = pending;

  $('state-dot').style.background = pending ? 'var(--bad)' : 'var(--ok)';
  $('side-status').textContent = c.enabled ? '采集运行中' : '采集已暂停';
  $('side-interval').textContent = c.interval_min ? `${c.interval_min} min` : '—';
  $('side-count').textContent = c.count_today;

  $('tb-state').textContent = c.enabled ? '运行中' : '已暂停';
  $('tb-next').textContent = c.enabled ? clockOf(c.next_ts) : '—';
  $('tb-mode').classList.toggle('paused', !c.enabled);

  loadExcerpt(s.date, rp.today_generated);
}

/* 摘要卡的内容只能从 get_report 拿：get_state 不带正文。没生成就不请求，省一次往返。 */
async function loadExcerpt(date, generated) {
  const box = $('ov-excerpt');
  if (!generated) {
    const text = '今天的日报还没生成。到点会自动生成，也可以点上方「立即生成日报」。';
    if (box.textContent !== text) box.textContent = text;
    $('ov-ex-time').textContent = '—';
    return;
  }
  const r = await call('get_report', 'daily', date);
  if (!r || r.error || !r.content_md) {
    const text = '日报正文暂时读不出来，去「日报 / 周报」页看看。';
    if (box.textContent !== text) box.textContent = text;
    $('ov-ex-time').textContent = '—';
    return;
  }
  const text = mdExcerpt(r.content_md, 220);
  if (box.textContent !== text) box.textContent = text;
  $('ov-ex-time').textContent = clockOf(r.generated_at);
}

/* 摘要卡永远是「当天日报」：用户上次停在周报时也得扳回日报，
   否则点「读全文」打开的是周报列表。用 setKind 而不是 switchKind，
   取数交给 go('report')，一次点击只发一个请求。 */
$('ov-more').addEventListener('click', () => {
  setKind('daily');
  go('report');
});

$('btn-toggle-capture').addEventListener('click', async () => {
  const r = await call('toggle_capture');
  if (r && !r.error) { toast(r.enabled ? '已继续采集' : '已暂停采集'); loadOverview(); }
});
$('btn-gen-daily').addEventListener('click', () => generate('daily', '今日日报'));
$('btn-gen-weekly').addEventListener('click', () => generate('weekly', '本周周报'));

let _genBusy = false;
async function generate(kind, label) {
  if (_genBusy) { toast('正在生成中，请稍候…'); return; }
  _genBusy = true;
  toast(`正在生成${label}…（AI 可能要几十秒）`);
  const r = await call('generate', kind);
  _genBusy = false;
  if (r && !r.error) {
    if (r.skipped) toast('未生成：' + r.reason);
    else { toast(`${label}已生成`); loadOverview(); }
  }
}

/* 今日应用统计 —— 数据放进总览页，占比看环形、时长看横向条。
   刻意不挂到 boot() 的 10 秒轮询上：应用采样是 5/10 分钟粒度，跟着轮询重绘只会闪。 */

let _ovUsage = null;        // 最近一次取数结果，切换图形时复用，不必重新请求
let _ovUsageDate = null;    // 上面这份数据属于哪一天，跨零点要靠它判断要不要重置
let _ovUsageMode = 'share'; // 'share'（环形占比）| 'span'（横向时长）

async function loadOverviewUsage() {
  if (!_today) return;
  const r = await call('get_app_usage', _today);
  const card = $('ov-usage');
  if (!r || r.error) {
    // 取不到就退回占位符，别把上一次的数字留在「占屏时长」上
    card.style.display = 'none';
    _ovUsage = null;
    _ovUsageDate = null;
    $('ov-total').textContent = '—';
    $('ov-total-note').textContent = '按采样估算';
    return;
  }
  card.style.display = 'block';
  _ovUsage = r;
  _ovUsageDate = _today;
  $('ov-total').textContent = fmtDur(r.total_min);
  $('ov-total-note').innerHTML = `<span class="num">${r.samples}</span> 次采样`;
  renderOverviewUsage();
}

function renderOverviewUsage() {
  const r = _ovUsage;
  if (!r) return;
  const body = $('ov-usage-body');
  $('ov-usage-samples').textContent = `${r.samples} 次采样`;
  if (!r.items.length) {
    body.innerHTML = '<p class="usage-note">今天还没有应用使用记录，'
      + '工作时间内开始采集后这里会出现统计。</p>';
    return;
  }
  const top = topN(r.items, 4);   // 前四名 + 其他 = 五段，正好用满 --s1..--s5
  const sum = _ovUsageMode === 'span'
    ? `共 <span class="num">${fmtDur(r.total_min)}</span> · ${r.samples} 次采样`
    : `用得最多 <b>${esc(r.items[0].app)}</b> <span class="num">${fmtDur(r.items[0].minutes)}</span>`
      + ` · ${r.samples} 次采样`;
  body.innerHTML = `<div class="usage-sum">${sum}</div>`
    + (_ovUsageMode === 'span' ? barHtml(top) : donutHtml(top, r.total_min))
    + '<div class="usage-note">按采集间隔采样估算，非精确计时；挂机与空闲不计入。</div>';
}

$('ov-usage-mode').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
  _ovUsageMode = b.dataset.v;
  $('ov-usage-mode').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  renderOverviewUsage();
}));

/* ---------------------------------------------------------------- 时间线 */

async function loadTimelineDates() {
  const dates = await call('list_timeline_dates');
  if (!dates || dates.error) return;
  const sel = $('tl-date');
  sel.innerHTML = '';
  for (const d of dates) {
    const opt = document.createElement('option');
    opt.value = d.date;
    opt.textContent = `${d.date}（${d.count} 条）`;
    sel.appendChild(opt);
  }
  if (dates.length) loadTimeline(dates[0].date);
  else { $('tl-list').innerHTML = ''; $('tl-empty').style.display = 'block'; }
}
$('tl-date').addEventListener('change', () => loadTimeline($('tl-date').value));

/* 分类色点：后端是封闭集合（ai.client.IMAGE_ANALYSIS_CATEGORIES），这里只是把中文分类
   归到五支笔上。十种分类必须全部有归属——漏掉的会掉进「其他」的灰，和未知分类长得一样，
   用户就看不出那是「影音」而不是「识别失败」。游戏和「其他」共用中性灰，都属于非生产性。 */
const CAT_VAR = {
  '编码': '--c-dev', '终端': '--c-dev',
  '文档': '--c-doc', '设计': '--c-doc',
  '沟通': '--c-im', '会议': '--c-im',
  '浏览': '--c-web', '影音': '--c-web',
};
const catColor = (c) => `var(${CAT_VAR[c] || '--c-etc'})`;

/* 纸带按小时分组：同一小时的事件挂在一条竖轴旁，时间戳等宽对齐才好扫读 */
function timelineHtml(events) {
  let html = '', hour = '';
  for (const e of events) {
    const h = (e.time || '').slice(0, 2);
    if (h !== hour) {
      if (hour) html += '</div></div>';
      hour = h;
      html += `<div class="hour"><div class="hour-stamp">${esc(h)}:00</div><div class="events">`;
    }
    const cat = e.category
      ? `<span class="cat"><i style="background:${catColor(e.category)}"></i>${esc(e.category)}</span>`
      : '';
    html += `<div class="event"><div class="t">${esc(e.time)}</div>`
      + `<div class="body"><div class="txt">${cat}${esc(e.analysis)}</div></div></div>`;
  }
  if (hour) html += '</div></div>';
  return html;
}

async function loadTimeline(date) {
  const events = await call('get_timeline', date);
  if (!events || events.error) return;
  $('tl-list').innerHTML = timelineHtml(events);
  $('tl-empty').style.display = events.length ? 'none' : 'block';
}

/* ---------------------------------------------------------------- 报表 */

let _kind = 'daily', _selected = null, _currentMd = '';
$('kind-daily').addEventListener('click', () => switchKind('daily'));
$('kind-weekly').addEventListener('click', () => switchKind('weekly'));

/* 只切类型与按钮态，不发请求：进入报表页时 go() 会取数，一次点击不该拉两遍 */
function setKind(kind) {
  _kind = kind;
  $('kind-daily').classList.toggle('on', kind === 'daily');
  $('kind-weekly').classList.toggle('on', kind === 'weekly');
}

function switchKind(kind) {
  setKind(kind);
  loadReports();
}

async function loadReports() {
  const rows = await call('list_reports', _kind);
  if (!rows || rows.error) return;
  const list = $('rp-list');
  list.innerHTML = '';
  for (const row of rows) {
    const key = _kind === 'daily' ? row.date : row.week_start;
    const div = document.createElement('div');
    div.className = 'date-item';
    div.innerHTML = `<span>${esc(_kind === 'daily' ? key : weekRange(key))}</span>`
      + (row.is_overwritten ? '<span class="fix">覆盖版</span>' : '');
    div.addEventListener('click', () => {
      _selected = key;
      list.querySelectorAll('.date-item').forEach(i => i.classList.toggle('on', i === div));
      showReport(key);
    });
    list.appendChild(div);
  }
  if (rows.length) {
    const first = list.querySelector('.date-item');
    first.classList.add('on');
    _selected = _kind === 'daily' ? rows[0].date : rows[0].week_start;
    showReport(_selected);
  } else {
    $('rp-body').innerHTML = '<div class="md"><p class="empty">还没有'
      + (_kind === 'daily' ? '日报' : '周报') + '。</p></div>';
  }
}

async function showReport(key) {
  const r = await call('get_report', _kind, key);
  if (!r || r.error) return;
  _currentMd = r.content_md || '';
  const name = _kind === 'daily' ? key : weekRange(key) + ' 周报';
  const stamp = String(r.generated_at || '');
  /* 标题里已经有日期了，这里只给时刻；ISO 解析不出来才退回原串 */
  const genAt = stamp.length >= 19 ? stamp.slice(11, 19) : stamp.replace('T', ' ');
  $('rp-body').innerHTML =
    `<div class="report-top">
       <div class="title"><span class="num">${esc(name)}</span>
         · 生成于 <span class="num">${esc(genAt)}</span></div>
       <div class="acts">
         <button class="btn" id="btn-copy">复制全文</button>
         <button class="btn quiet" id="btn-regen">重新生成</button>
       </div>
     </div>
     <div class="md">${renderMarkdown(_currentMd)}</div>`;
  $('btn-copy').addEventListener('click', async () => {
    if (!_currentMd) { toast('还没有可复制的内容'); return; }
    const r2 = await call('copy_text', _currentMd);
    if (r2 && r2.ok) toast('已复制全文，可直接粘贴');
  });
  $('btn-regen').addEventListener('click',
    () => generate(_kind, _kind === 'daily' ? '今日日报' : '本周周报'));
}

/* ---------------------------------------------------------------- 图表工具 */

/* 图表手写：项目约束是零构建、零前端框架，不引 ECharts/Chart.js。
   配色全走 CSS 变量（--s1..--s5 / --bar），切皮肤自动跟着变，JS 里不再存色值。 */

function fmtDur(min) {
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h}h${String(m).padStart(2, '0')}m` : `${m}m`;
}

/* 超出 n 项就合并成「其他」——条目太多两种图都读不清。
   n=4 时最多出 5 项，正好对应五档色阶。 */
function topN(items, n) {
  if (items.length <= n) return items.slice();
  const rest = items.slice(n);
  return items.slice(0, n).concat([{
    app: '其他',
    minutes: rest.reduce((s, i) => s + i.minutes, 0),
    percent: Math.round(rest.reduce((s, i) => s + i.percent, 0) * 10) / 10,
  }]);
}

/* 环形段用 path 画：外弧 → 直线切到内弧 → 内弧反向 → 闭合。
   相邻两段各让出半个缝隙角，缝就出来了 —— 不靠描边，缩放到任何尺寸都不会糊。
   单段 100% 时内外弧首尾重合会退化成一条线，单独处理。 */
function donutPaths(items, size, ringWidth) {
  const C = size / 2, ro = C - 1, ri = ro - ringWidth;
  const total = items.reduce((s, i) => s + i.minutes, 0) || 1;
  const GAP = 1.1;
  const rad = (d) => d * Math.PI / 180;
  const pt = (r, a) => [
    (C + r * Math.cos(rad(a))).toFixed(2),
    (C + r * Math.sin(rad(a))).toFixed(2),
  ];
  let cursor = -90;   // 从 12 点方向起，顺时针
  return items.map((it, i) => {
    const sweep = it.minutes / total * 360;
    const a1 = cursor + GAP / 2, a2 = cursor + sweep - GAP / 2;
    cursor += sweep;
    if (items.length === 1) {
      return `<circle class="slice" cx="${C}" cy="${C}" r="${ro - ringWidth / 2}"`
        + ` fill="none" stroke="var(--s1)" stroke-width="${ringWidth}">`
        + `<title>${esc(it.app)}</title></circle>`;
    }
    if (a2 <= a1) return '';
    const [x1, y1] = pt(ro, a1), [x2, y2] = pt(ro, a2);
    const [x3, y3] = pt(ri, a2), [x4, y4] = pt(ri, a1);
    const large = (a2 - a1) > 180 ? 1 : 0;
    return `<path class="slice" d="M${x1},${y1}`
      + ` A${ro},${ro} 0 ${large} 1 ${x2},${y2}`
      + ` L${x3},${y3}`
      + ` A${ri},${ri} 0 ${large} 0 ${x4},${y4} Z"`
      + ` fill="var(--s${i + 1})">`
      + `<title>${esc(it.app)} · ${fmtDur(it.minutes)} · ${it.percent}%</title></path>`;
  }).join('');
}

/* 中心放总时长：这是环形比饼图多的那点信息，否则它只是把饼挖了个洞 */
function donutHtml(items, totalMin) {
  const legend = items.map((it, i) =>
    `<div class="row"><span class="dot" style="background:var(--s${i + 1})"></span>`
    + `<span class="nm">${esc(it.app)}</span>`
    + `<span class="val">${fmtDur(it.minutes)} · ${it.percent}%</span></div>`).join('');
  return `<div class="donut-wrap">
      <div class="donut">
        <svg viewBox="0 0 152 152" role="img" aria-label="应用使用占比环形图">
          ${donutPaths(items, 152, 18)}
        </svg>
        <div class="donut-center">
          <b>${fmtDur(totalMin)}</b><span>总时长</span>
        </div>
      </div>
      <div class="dlegend">${legend}</div>
    </div>`;
}

/* 时长视图：三列同一 grid，条长按相对第一名算；只有第一名上琥珀，其余退到中性灰 */
function barHtml(items) {
  const max = Math.max(...items.map(i => i.minutes), 1);
  return '<div class="bars">' + items.map((i, idx) => {
    const tip = `${i.app}：${fmtDur(i.minutes)} · ${i.percent}%`;
    return `<div class="bar-row${idx === 0 ? ' first' : ''}">`
      + `<span class="nm" title="${esc(tip)}">${esc(i.app)}</span>`
      + `<span class="track"><i class="fill" style="width:${(i.minutes / max * 100).toFixed(1)}%"></i></span>`
      + `<span class="val"><b>${fmtDur(i.minutes)}</b> · ${i.percent}%</span>`
      + '</div>';
  }).join('') + '</div>';
}

/* ---------------------------------------------------------------- 外观皮肤 */

/* 切皮肤 = 换 <html data-theme>，色值全在 CSS 变量里，图表不需要重取配色。
   不走「值没变就 return」：boot() 也要借这一步把首帧缓存写稳。
   应用统计卡只重渲染、不重新取数（沿用 _ovUsage 缓存，和切换占比/时长同一个约定）。 */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem('hd-theme', theme);   // 只给下次启动的首帧用（见 index.html 内联脚本）
  } catch (e) { /* 写不进去就退化为启动闪一帧，不影响本次切换 */ }
  if (_ovUsage) renderOverviewUsage();
}

/* ---------------------------------------------------------------- 运行日志 */

/* 日志只在「运行日志」页处于激活态时才拉（见 boot() 的 60 秒轮询）——这个页面是诊断用的，
   没必要在别的页面后台轮询。_logSig 判内容有没有变：没变就不重绘，否则每 60 秒会把用户的
   滚动位置和正在选中的文字一起抹掉。 */
let _logLevel = '';
let _logSig = null;
let _logTopKey = null;   // 当前列表首行的标识，重绘时靠它算出「这次多出来几条」
let _logShownLevel = null;   // 上一轮渲染时的级别，用来分辨「换档」和「同档刷新」

const logKey = (line) => line.ts + ' ' + line.msg;

async function loadLogs(force) {
  const r = await call('get_logs', _logLevel, 200);
  if (!r || r.error) return;
  const sig = _logLevel + '|' + r.lines.map(logKey).join('\u0000');
  if (!force && sig === _logSig) return;
  _logSig = sig;
  renderLogs(r);
}

function renderLogs(data) {
  const box = $('lg-list');
  /* 换级别 = 换了一整个集合，旧滚动位置没有意义，必须归零；
     只有同一档位里刷新才需要保住位置。两者靠 _logShownLevel 区分——
     不看它的话，切到「信息」时若旧首行恰好也在新集合里，moved===0 就会
     把位置原样留下，人停在一个无意义的半山腰。 */
  const switched = _logShownLevel !== _logLevel;
  const prevTop = switched ? 0 : box.scrollTop;
  const keep = !switched && prevTop > 2 ? _logTopKey : null;  // 只有滚下去过才需要保住位置
  const rowH = box.firstElementChild ? box.firstElementChild.offsetHeight : 0;

  box.innerHTML = data.lines.length
    ? data.lines.map(l => `<div class="log-row" title="${esc(l.name)}">
        <span class="log-ts">${esc(l.ts)}</span>
        <span class="log-lv ${l.level.toLowerCase()}">${esc(l.level)}</span>
        <span class="log-msg">${esc(l.msg)}</span>
      </div>`).join('')
    : '<div class="log-empty">这一类日志还没有记录。</div>';
  _logTopKey = data.lines.length ? logKey(data.lines[0]) : null;

  const total = data.lines.length;
  $('lg-count').textContent = total
    ? `共 ${total} 条${data.truncated ? `（仅显示最近 ${total} 条）` : ''}`
    : '';

  /* 新日志插在顶部，所以要在原位置上「加」新增行的高度，不能直接赋值成新增量：
     绝对赋值会把滚到 300 的人拽回 111。moved === 0 表示一条没多，原位不动。
     moved 为 -1（旧首行已被换档/截断挤掉）→ 回顶部。旧首行已不在列表里同理。
     rowH 只取原首行高度：多行 traceback 的高低不一，会带来几像素误差，可以接受。 */
  const moved = keep ? data.lines.findIndex(l => logKey(l) === keep) : -1;
  box.scrollTop = keep && moved >= 0 && rowH ? prevTop + moved * rowH : 0;
  _logShownLevel = _logLevel;   // 记下这一档，下次渲染才能分辨「换档」和「新增」
}

$('lg-level').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
  _logLevel = b.dataset.v;
  $('lg-level').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  loadLogs(true);
}));
$('btn-log-refresh').addEventListener('click', () => loadLogs(true));
$('btn-log-dir').addEventListener('click', () => call('open_logs_dir'));

/* ---------------------------------------------------------------- 设置 */

let _interval = 5;
async function loadSettingsForm() {
  const s = await call('get_settings');
  if (!s || s.error) return;
  $('st-url').value = s.base_url;
  $('st-model').value = s.model;
  $('st-key').value = '';
  $('st-haskey').textContent = s.has_key ? '已配置' : '未配置';
  $('st-ws').value = s.work_hours.start;
  $('st-we').value = s.work_hours.end;
  $('st-dt').value = s.daily_time;
  $('st-ot').value = s.overwrite_time;
  _interval = s.screenshot_interval_min;
  $('st-interval').querySelectorAll('button').forEach(b =>
    b.classList.toggle('on', Number(b.dataset.v) === _interval));
  $('st-theme').querySelectorAll('button').forEach(b =>
    b.classList.toggle('on', b.dataset.v === s.theme));
}
$('st-interval').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
  _interval = Number(b.dataset.v);
  $('st-interval').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
}));
/* 皮肤是「选中即生效」：先把值落盘，成功了才换界面，避免出现「看着变了其实没存」 */
$('st-theme').querySelectorAll('button').forEach(b => b.addEventListener('click', async () => {
  const theme = b.dataset.v;
  if (document.documentElement.dataset.theme === theme) return;
  const r = await call('set_theme', theme);
  if (!r || r.error) return;
  applyTheme(theme);
  $('st-theme').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
}));

$('btn-save').addEventListener('click', async () => {
  const r = await call('save_settings', collectSettings());
  if (r && !r.error) toast('设置已保存');
});
$('btn-test').addEventListener('click', async () => {
  const msg = $('st-test-msg');
  msg.textContent = '测试中…';
  msg.className = '';
  const saved = await call('save_settings', collectSettings());
  if (saved && saved.error) { msg.textContent = ''; return; }
  const r = await call('test_connection');
  msg.textContent = r && !r.error ? '连接正常' : '连接失败';
  msg.className = r && !r.error ? 'test-ok' : 'test-bad';
});

function collectSettings() {
  return {
    base_url: $('st-url').value, model: $('st-model').value,
    api_key: $('st-key').value, screenshot_interval_min: _interval,
    work_hours: { start: $('st-ws').value, end: $('st-we').value },
    daily_time: $('st-dt').value, overwrite_time: $('st-ot').value,
  };
}

/* 数据管理 */
$('btn-export').addEventListener('click', async () => {
  const r = await call('export_data');
  if (r && !r.error) toast('已导出：' + r.path);
});
$('btn-opendir').addEventListener('click', () => call('open_data_dir'));
$('btn-clear').addEventListener('click', () => $('m-clear').classList.add('show'));
$('clear-cancel').addEventListener('click', () => $('m-clear').classList.remove('show'));
$('clear-ok').addEventListener('click', async () => {
  $('m-clear').classList.remove('show');
  const r = await call('clear_data');
  if (r && !r.error) toast('全部数据已清空');
});

/* ---------------------------------------------------------------- 引导 */

$('ob-ack').addEventListener('change', () => $('ob-next').disabled = !$('ob-ack').checked);
$('ob-next').addEventListener('click', async () => {
  $('ob-step1').style.display = 'none';
  $('ob-step2').style.display = 'block';
  const s = await call('get_settings');
  if (s && !s.error) { $('ob-url').value = s.base_url; $('ob-model').value = s.model; }
});
$('ob-back').addEventListener('click', () => {
  $('ob-step2').style.display = 'none';
  $('ob-step1').style.display = 'block';
});
$('ob-finish').addEventListener('click', async () => {
  $('ob-msg').textContent = '正在测试连通性…';
  $('ob-msg').className = 'test-ok';
  const r = await call('finish_onboarding',
    $('ob-url').value, $('ob-model').value, $('ob-key').value);
  if (r && r.ok) {
    $('sidebar').style.display = 'flex';
    go('overview');
    toast('欢迎使用 HenanDiary，采集已开始');
  } else {
    $('ob-msg').textContent = '连接失败：' + (r ? r.error : '未知错误');
    $('ob-msg').className = 'test-bad';
  }
});

/* ---------------------------------------------------------------- 关闭询问 */

function showCloseAsk() { $('m-close').classList.add('show'); }
window.showCloseAsk = showCloseAsk;  // 后端 evaluate_js 调用

/* 自绘顶栏按钮（frameless 窗口没有原生标题栏） */
$('tb-min').addEventListener('click', () => call('minimize'));
$('tb-max').addEventListener('click', () => call('toggle_maximize'));
$('tb-close').addEventListener('click', showCloseAsk);
$('close-tray').addEventListener('click', () => {
  $('m-close').classList.remove('show');
  call('minimize_to_tray');
});
$('close-quit').addEventListener('click', () => call('quit_app'));

/* ---------------------------------------------------------------- 启动 */

async function boot() {
  if (window._booted) return;
  window._booted = true;
  const s = await call('get_state');
  if (s && !s.error) applyTheme(s.theme);  // 后端是唯一真相，覆盖 index.html 的首帧提示
  if (s && !s.error && s.onboarding_done) {
    $('sidebar').style.display = 'flex';
    go('overview');
  } else {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('on'));
    $('p-onboard').classList.add('on');
    /* 引导没做完时采集还没起：顶栏别写「运行中」，脉搏也停下 */
    $('tb-state').textContent = '待配置';
    $('tb-next').textContent = '—';
    $('tb-mode').classList.add('paused');
  }
  setInterval(() => {
    const active = document.querySelector('nav button.on');
    if (active && active.dataset.p === 'overview') loadOverview();
  }, 10000);  // 需求确认单：状态轮询 ~10s
  setInterval(() => {
    const active = document.querySelector('nav button.on');
    if (active && active.dataset.p === 'logs') loadLogs(false);
  }, 60000);  // F9：日志页 60 秒自动刷新，同样只在本页激活时拉
}

window.addEventListener('pywebviewready', boot);
setTimeout(boot, 2000);  // pywebviewready 没来时的兜底（重复调用被 _booted 挡住）
