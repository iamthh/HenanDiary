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
  if (page === 'overview') loadOverview();
  if (page === 'timeline') loadTimelineDates();
  if (page === 'report') loadReports();
  if (page === 'settings') loadSettingsForm();
}
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => go(b.dataset.p)));

/* ---------------------------------------------------------------- 总览 */

async function loadOverview() {
  const s = await call('get_state');
  if (!s || s.error) return;
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

let _kind = 'daily', _selected = null;
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
  const title = _kind === 'daily' ? key : weekRange(key) + ' 周报';
  $('rp-body').innerHTML =
    `<div class="row" style="justify-content:flex-end">
       <span style="color:var(--dim);font-size:12px;margin-right:auto">${esc(title)}　·　生成于 ${esc(r.generated_at.replace('T',' '))}</span>
       <button class="ghost" id="btn-regen">重新生成</button></div>`
    + renderMarkdown(r.content_md);
  $('btn-regen').addEventListener('click', () => generate(_kind, _kind === 'daily' ? '今日日报' : '本周周报'));
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
