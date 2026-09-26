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

/* 周报按「周一 ~ 周日」这一段存，列表里标出范围，避免把 week_start 误读成某一天。
   纯日期运算，用本地时间构造避免时区偏移。 */
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
    if (h) { closeLists(); html += `<h${Math.min(h[1].length + 1, 4)}>${inline(h[2])}</h${Math.min(h[1].length + 1, 4)}>`; }
    else if (li) { if (inOl) { html += '</ol>'; inOl = false; } if (!inUl) { html += '<ul>'; inUl = true; } html += `<li>${inline(li[1])}</li>`; }
    else if (o) { if (inUl) { html += '</ul>'; inUl = false; } if (!inOl) { html += '<ol>'; inOl = true; } html += `<li>${inline(o[1])}</li>`; }
    else if (!line.trim()) { closeLists(); }
    else { closeLists(); html += `<p>${inline(line)}</p>`; }
  }
  closeLists();
  return html;
}

/* ---------------------------------------------------------------- 导航 */

function go(page) {
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.p === page));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('show'));
  $('p-' + page).classList.add('show');
  if (page === 'overview') loadOverview().then(() => loadOverviewUsage());
  if (page === 'timeline') loadTimelineDates();
  if (page === 'report') loadReports();
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
  $('ov-date').textContent = `${s.date} · 工作时间 ${s.capture.work_hours.start}–${s.capture.work_hours.end}`;
  $('ov-count').textContent = s.capture.count_today;
  $('ov-next').textContent = s.capture.enabled && s.capture.next_ts
    ? s.capture.next_ts.replace('T', ' ') : (s.capture.enabled ? '—' : '已暂停');
  $('ov-time').textContent = s.report.daily_time;
  const ai = $('ov-ai');
  ai.innerHTML = s.report.pending.length
    ? `<span class="badge bad">${s.report.pending.length} 笔待重试</span>`
    : '<span class="badge ok">正常</span>';
  const badge = $('ov-report-badge');
  if (s.report.today_generated) {
    badge.textContent = '已生成' + (s.report.today_overwritten ? '（00:30 覆盖版）' : '');
    badge.className = 'badge ok';
  } else {
    badge.textContent = `待生成 · ${s.report.daily_time}`;
    badge.className = 'badge wait';
  }
  const pend = $('ov-pending');
  if (s.report.pending.length) {
    pend.style.display = 'block';
    $('ov-pending-list').innerHTML = s.report.pending
      .map(p => `${esc(p.date)}（${p.type}）：${esc(p.reason)}`).join('<br>');
  } else pend.style.display = 'none';

  $('btn-toggle-capture').textContent = s.capture.enabled ? '暂停采集' : '继续采集';
  $('state-dot').style.background = s.report.pending.length ? 'var(--bad)' : 'var(--ok)';
  $('side-status').textContent = s.capture.enabled ? '采集运行中' : '采集已暂停';
}

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

/* 今日应用统计摘要 —— M9 的数据放进总览页，图形可在饼图/柱状图间切换。
   刻意不挂到 boot() 的 10 秒轮询上：应用采样是 5/10 分钟粒度，跟着轮询重绘只会闪。 */

let _ovUsage = null;        // 最近一次取数结果，切换图形时复用，不必重新请求
let _ovUsageMode = 'pie';   // 'pie' | 'bar'

async function loadOverviewUsage() {
  if (!_today) return;
  const r = await call('get_app_usage', _today);
  const card = $('ov-usage');
  if (!r || r.error) { card.style.display = 'none'; return; }
  card.style.display = 'block';
  _ovUsage = r;
  renderOverviewUsage();
}

function renderOverviewUsage() {
  const r = _ovUsage;
  if (!r) return;
  const body = $('ov-usage-body');
  if (!r.items.length) {
    body.innerHTML = '<p style="color:var(--dim);font-size:13px">今天还没有应用使用记录，'
      + '工作时间内开始采集后这里会出现统计。</p>';
    return;
  }
  const top = topN(r.items, 5);
  body.innerHTML =
    `<div style="color:var(--dim);font-size:12px;margin-bottom:12px">共 ${fmtDur(r.total_min)}`
    + ` · 用得最多 ${esc(r.items[0].app)}（${fmtDur(r.items[0].minutes)}）· ${r.samples} 次采样</div>`
    + (_ovUsageMode === 'bar' ? barHtml(top) : pieHtml(top))
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

async function loadTimeline(date) {
  const events = await call('get_timeline', date);
  if (!events || events.error) return;
  const list = $('tl-list');
  list.innerHTML = '';
  for (const e of events) {
    const div = document.createElement('div');
    div.className = 'event';
    const tag = e.category ? `<span class="tag">${esc(e.category)}</span>` : '';
    div.innerHTML = `<div class="time">${esc(e.time)}</div><div class="desc">${tag}${esc(e.analysis)}</div>`;
    list.appendChild(div);
  }
  $('tl-empty').style.display = events.length ? 'none' : 'block';
}

/* ---------------------------------------------------------------- 报表 */

let _kind = 'daily', _selected = null, _currentMd = '';
$('kind-daily').addEventListener('click', () => switchKind('daily'));
$('kind-weekly').addEventListener('click', () => switchKind('weekly'));
function switchKind(kind) {
  _kind = kind;
  $('kind-daily').classList.toggle('on', kind === 'daily');
  $('kind-weekly').classList.toggle('on', kind === 'weekly');
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
    div.className = 'item';
    div.textContent = _kind === 'daily' ? key : weekRange(key);
    if (row.is_overwritten) div.textContent += ' · 补';
    div.addEventListener('click', () => {
      _selected = key;
      list.querySelectorAll('.item').forEach(i => i.classList.toggle('active', i === div));
      showReport(key);
    });
    list.appendChild(div);
  }
  if (rows.length) {
    const first = list.querySelector('.item');
    first.classList.add('active');
    _selected = _kind === 'daily' ? rows[0].date : rows[0].week_start;
    showReport(_selected);
  } else {
    $('rp-body').innerHTML = '<span style="color:var(--dim)">还没有' + (_kind === 'daily' ? '日报' : '周报') + '。</span>';
  }
}

async function showReport(key) {
  const r = await call('get_report', _kind, key);
  if (!r || r.error) { if (r) toast(r.error); return; }
  _currentMd = r.content_md || '';
  const title = _kind === 'daily' ? key : weekRange(key) + ' 周报';
  $('rp-body').innerHTML =
    `<div class="row" style="justify-content:flex-end">
       <span style="color:var(--dim);font-size:12px;margin-right:auto">${esc(title)}　·　生成于 ${esc(r.generated_at.replace('T',' '))}</span>
       <button class="ghost" id="btn-copy">复制全文</button>
       <button class="ghost" id="btn-regen">重新生成</button></div>`
    + renderMarkdown(r.content_md);
  $('btn-copy').addEventListener('click', async () => {
    if (!_currentMd) { toast('还没有可复制的内容'); return; }
    const r2 = await call('copy_text', _currentMd);
    if (r2 && r2.ok) toast('已复制全文，可直接粘贴');
  });
  $('btn-regen').addEventListener('click', () => generate(_kind, _kind === 'daily' ? '今日日报' : '本周周报'));
}

/* ---------------------------------------------------------------- 应用统计图表工具（M9） */

/* 图表手写：项目约束是零构建、零前端框架，不引 ECharts/Chart.js。
   柱状图（div 高度百分比）与饼图（内联 SVG 扇形）都不需要额外依赖。 */

const PIE_COLORS = ['#d97a4a', '#e8a97e', '#8a4d30', '#6fbf73', '#d9c48a', '#6b5f52'];

function fmtDur(min) {
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h}h${String(m).padStart(2, '0')}m` : `${m}m`;
}

/* 超出 n 项就合并成「其他」——条目太多两种图都读不清 */
function topN(items, n) {
  if (items.length <= n) return items.slice();
  const rest = items.slice(n);
  return items.slice(0, n).concat([{
    app: '其他',
    minutes: rest.reduce((s, i) => s + i.minutes, 0),
    percent: Math.round(rest.reduce((s, i) => s + i.percent, 0) * 10) / 10,
  }]);
}

/* 竖向柱状图：div 高度百分比，同样不引图表库。
   配色与饼图共用 PIE_COLORS，按序号取色——同一应用在两种图里颜色一致；
   序号即后端返回的时长降序，所以柱子从左往右由高到低依次排开。 */
function barHtml(items) {
  const max = Math.max(...items.map(i => i.minutes), 1);
  return '<div class="bar-chart">' + items.map((i, idx) => {
    const color = PIE_COLORS[idx % PIE_COLORS.length];
    return `<div class="bar-col" title="${esc(i.app)}：${fmtDur(i.minutes)} · ${i.percent}%">
      <div class="bar-value">${fmtDur(i.minutes)}</div>
      <div class="bar-track"><span class="bar-fill" style="height:${(i.minutes / max * 100).toFixed(1)}%;background:${color}"></span></div>
      <div class="bar-name">${esc(i.app)}</div>
    </div>`;
  }).join('') + '</div>';
}

function pieHtml(items) {
  const total = items.reduce((s, i) => s + i.minutes, 0) || 1;
  const CX = 75, CY = 75, R = 64;
  let angle = -Math.PI / 2;   // 从 12 点方向开始顺时针
  let paths = '';
  items.forEach((i, idx) => {
    const from = angle;
    const to = angle + i.minutes / total * Math.PI * 2;
    angle = to;
    const color = PIE_COLORS[idx % PIE_COLORS.length];
    if (items.length === 1) {   // 整圆时起止点重合，弧线会退化，直接画圆
      paths += `<circle cx="${CX}" cy="${CY}" r="${R}" fill="${color}"/>`;
      return;
    }
    const x1 = CX + R * Math.cos(from), y1 = CY + R * Math.sin(from);
    const x2 = CX + R * Math.cos(to), y2 = CY + R * Math.sin(to);
    const large = (to - from) > Math.PI ? 1 : 0;
    paths += `<path d="M${CX},${CY} L${x1.toFixed(2)},${y1.toFixed(2)}`
      + ` A${R},${R} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)} Z"`
      + ` fill="${color}" stroke="var(--bg)" stroke-width="0.5"/>`;
  });
  const legend = items.map((i, idx) =>
    `<div class="legend-row">
       <span class="swatch" style="background:${PIE_COLORS[idx % PIE_COLORS.length]}"></span>
       <span class="nm">${esc(i.app)}</span><span class="pct">${i.percent}%</span>
     </div>`).join('');
  return `<div class="pie-wrap">
    <svg viewBox="0 0 150 150" width="150" height="150" role="img" aria-label="应用使用占比饼图">${paths}</svg>
    <div class="legend">${legend}</div>
  </div>`;
}

/* ---------------------------------------------------------------- 设置 */

let _interval = 5;
async function loadSettingsForm() {
  const s = await call('get_settings');
  if (!s || s.error) return;
  $('st-url').value = s.base_url;
  $('st-model').value = s.model;
  $('st-key').value = '';
  $('st-haskey').textContent = s.has_key ? '（已配置）' : '（未配置）';
  $('st-ws').value = s.work_hours.start;
  $('st-we').value = s.work_hours.end;
  $('st-dt').value = s.daily_time;
  $('st-ot').value = s.overwrite_time;
  _interval = s.screenshot_interval_min;
  $('st-interval').querySelectorAll('button').forEach(b =>
    b.classList.toggle('on', Number(b.dataset.v) === _interval));
}
$('st-interval').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
  _interval = Number(b.dataset.v);
  $('st-interval').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
}));
$('btn-save').addEventListener('click', async () => {
  const r = await call('save_settings', collectSettings());
  if (r && !r.error) toast('设置已保存');
});
$('btn-test').addEventListener('click', async () => {
  $('st-test-msg').textContent = '测试中…';
  $('st-test-msg').className = 'test-ok';
  const saved = await call('save_settings', collectSettings());
  if (saved && saved.error) { $('st-test-msg').textContent = ''; return; }
  const r = await call('test_connection');
  if (r && !r.error) { $('st-test-msg').textContent = '✓ 连接正常'; $('st-test-msg').className = 'test-ok'; }
  else { $('st-test-msg').textContent = '✗ 连接失败'; $('st-test-msg').className = 'test-bad'; }
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
  $('ob-msg').textContent = '正在测试连通性…'; $('ob-msg').className = 'test-ok';
  const r = await call('finish_onboarding', $('ob-url').value, $('ob-model').value, $('ob-key').value);
  if (r && r.ok) {
    $('sidebar').style.display = 'flex';
    go('overview');
    toast('欢迎使用 HenanDiary，采集已开始');
  } else {
    $('ob-msg').textContent = '连接失败：' + (r ? r.error : '未知错误'); $('ob-msg').className = 'test-bad';
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
  if (s && !s.error && s.onboarding_done) {
    $('sidebar').style.display = 'flex';
    go('overview');
  } else {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('show'));
    $('p-onboard').classList.add('show');
  }
  setInterval(() => {
    const active = document.querySelector('nav button.active');
    if (active && active.dataset.p === 'overview') loadOverview();
  }, 10000);  // 需求确认单：状态轮询 ~10s
}

window.addEventListener('pywebviewready', boot);
setTimeout(boot, 2000);  // pywebviewready 没来时的兜底（重复调用被 _booted 挡住）
