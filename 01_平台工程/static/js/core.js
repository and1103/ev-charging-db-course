export const state = {session: null, csrfToken: null, serverTime: null};

export function node(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') e.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'className') e.className = value;
    else if (key === 'dataset') Object.assign(e.dataset, value);
    else if (key in e && !key.startsWith('aria')) e[key] = value;
    else e.setAttribute(key, value === true ? '' : String(value));
  }
  const append = value => {
    if (Array.isArray(value)) value.forEach(append);
    else if (value !== null && value !== undefined && value !== false) e.append(value instanceof Node ? value : document.createTextNode(String(value)));
  };
  children.forEach(append);
  return e;
}

const errorLabels = {400:'请检查填写内容',401:'请先登录，或检查账号密码',403:'当前账号没有此操作权限',404:'记录不存在或不在你的权限范围内',409:'当前状态不允许此操作，请刷新后重试',413:'上传内容过大，最多支持 2 MB',429:'操作过于频繁，请稍后再试',500:'服务暂时出错，请稍后再试'};
export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('X-UI-Request', '1');
  const method = (options.method || 'GET').toUpperCase();
  let body = options.body;
  if (body !== undefined && body !== null && typeof body !== 'string' && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json'); body = JSON.stringify(body);
  }
  if (!['GET','HEAD','OPTIONS'].includes(method) && state.csrfToken) headers.set('X-CSRF-Token', state.csrfToken);
  let response;
  try { response = await fetch(path, {...options, method, body, headers, credentials:'same-origin', cache:'no-store'}); }
  catch { throw new Error('无法连接本地服务，请检查后端是否正在运行。'); }
  const result = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = result?.error || result?.message;
    const error = new Error(detail && /[\u4e00-\u9fff]/.test(detail) ? detail : `${errorLabels[response.status] || '请求失败'}${detail ? '（'+detail+'）' : ''}`);
    error.status = response.status;
    if (response.status === 401 && !path.startsWith('/auth/') && location.pathname !== '/ui/login') {
      location.assign('/ui/login');
    }
    throw error;
  }
  return result;
}

export async function loadSession() {
  const value = await api('/ui/session');
  state.session = value.user || null; state.csrfToken = value.csrf_token; state.serverTime = value.server_time;
  return value;
}

export function toast(message, tone = 'success') {
  const host = document.getElementById('toast-region');
  if (!host) return;
  const e = node('div', {className:`toast ${tone}`, role:tone === 'error' ? 'alert' : 'status'}, message);
  host.append(e); setTimeout(() => e.remove(), 6000);
}
export function button(label, action, kind = 'primary') {
  const b = node('button', {type:'button', className:`btn ${kind}`}, label);
  b.addEventListener('click', async () => {
    if (b.disabled) return;
    b.disabled = true; b.setAttribute('aria-busy','true');
    try { await action(); } catch (error) { toast(error.message || '操作失败', 'error'); }
    finally { b.disabled = false; b.removeAttribute('aria-busy'); }
  });
  return b;
}
export function form(fields, onSubmit, submitLabel = '提交', opts = {}) {
  const f = node('form', {className:`business-form ${opts.inline ? 'inline-form' : ''}`});
  if (opts.description) f.append(notice(opts.description));
  const grid = node('div',{className:'form-grid'});
  for (const spec of fields) {
    const {label, name, type = 'text', value = '', options = [], ...rest} = spec;
    let input;
    if (type === 'select') input = node('select', {name}, options.map(v => node('option',{value:typeof v === 'object' ? v.value : v, selected:String(typeof v === 'object' ? v.value : v) === String(value)}, typeof v === 'object' ? v.label : v)));
    else if (type === 'textarea') input = node('textarea', {name, rows:spec.rows || 4, value});
    else input = node('input', {name, type, value:type === 'checkbox' ? '1' : value, checked:type === 'checkbox' ? Boolean(value) : undefined});
    for (const attr of ['required','min','max','step','placeholder','readOnly','disabled','autocomplete','pattern','maxLength','accept']) {
      if (rest[attr] !== undefined) { if (attr in input) input[attr] = rest[attr]; else input.setAttribute(attr, rest[attr]); }
    }
    const wrapper = node('label', {className:`form-field ${type === 'textarea' ? 'wide' : ''} ${type === 'checkbox' ? 'checkbox-field' : ''}`}, node('span',{},label || name, spec.required ? node('span',{className:'required'},' *') : null), input, spec.help ? node('small',{className:'field-help'},spec.help) : null);
    if (type === 'hidden') wrapper.hidden = true;
    grid.append(wrapper);
  }
  f.append(grid);
  const error = node('div',{className:'form-error',role:'alert'});
  const submit = node('button',{type:'submit',className:'btn primary'},submitLabel);
  f.append(error,node('div',{className:'form-actions'},submit));
  f.addEventListener('submit',async event => {
    event.preventDefault(); if (submit.disabled || !f.reportValidity()) return;
    const values = Object.fromEntries(new FormData(f));
    fields.filter(x=>x.type==='checkbox').forEach(x=>values[x.name] = Boolean(f.elements.namedItem(x.name)?.checked));
    error.textContent = ''; submit.disabled = true; submit.setAttribute('aria-busy','true');
    try { await onSubmit(values, f); } catch (e) { error.textContent = e.message || '操作失败'; }
    finally { submit.disabled = false; submit.removeAttribute('aria-busy'); }
  });
  return f;
}

export function panel(title, ...children) { return node('section',{className:'panel'}, title ? node('div',{className:'panel-heading'}, typeof title === 'string' ? node('h2',{},title) : title) : null, ...children); }
export function dataTable(columns, rows) {
  if (!rows?.length) return node('div',{className:'empty-state'},node('span',{className:'empty-symbol'},'—'),node('strong',{},'暂无符合条件的数据'),node('p',{},'可以调整查询条件，或先完成相应业务操作。'));
  const table = node('table',{},node('thead',{},node('tr',{},columns.map(c=>node('th',{scope:'col'},c.label || c.key)))));
  table.append(node('tbody',{},rows.map(row=>node('tr',{},columns.map(c=>node('td',{className:c.className || ''},c.render ? c.render(row) : row[c.key] ?? '—'))))));
  return node('div',{className:'table-wrap'},table);
}
const labels = {idle:'空闲',occupied:'使用中',offline:'离线',fault:'故障',charging:'充电中',starting:'启动中',finishing:'结束中',billed:'待付款',paid:'已支付',review:'待复核',cancelled:'已取消',waiting:'排队中',called:'已叫号',converted:'已转订单',expired:'已过期',held:'已留枪',used:'已使用',released:'已释放',draft:'待确认',confirmed:'已确认',pending:'待处理',approved:'已通过',rejected:'已拒绝',open:'进行中',complete:'已完成',active:'活动中',closed:'已关闭',accept:'接受',reject:'拒绝',maintenance:'维修人员',driver:'车主',admin:'管理员',operator:'运营商',settlement:'结算人员',fleet:'车队负责人',flat:'平时段',peak:'峰时段',valley:'谷时段',normal:'正常',good:'正常',missing:'缺少采样',invalid:'数据异常',stale:'数据过期',acceptance:'投运验收',amendment:'参数变更',AC:'交流',DC:'直流',wallet:'钱包',mock:'模拟支付'};
Object.assign(labels, {verified:'已核验',enabled:'已启用',disabled:'已停用',failed:'失败'});
export function badge(value) {
  const code = value === true || value === 1 ? 'active' : value === false || value === 0 ? 'offline' : String(value ?? 'unknown');
  const good = ['idle','paid','confirmed','approved','complete','closed','active','normal','good','accept','used','verified','enabled'];
  const bad = ['fault','rejected','reject','invalid','failed'];
  const warn = ['review','pending','billed','waiting','called','held','draft','stale'];
  return node('span',{className:`badge ${good.includes(code)?'good':bad.includes(code)?'bad':warn.includes(code)?'warn':'neutral'}`},labels[code] || code);
}
export function money(v) { return v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}); }
export function stat(label,value,hint='') { return node('div',{className:'stat-card'},node('span',{className:'stat-label'},label),node('strong',{className:'stat-value'},value ?? '—'),node('small',{},hint)); }
export function notice(message,tone='info') { return node('div',{className:`notice ${tone}`,role:tone==='error'?'alert':'note'},message); }
export function modal(title,content) {
  const dialog = node('dialog',{className:'modal'});
  const close = () => { dialog.close(); dialog.remove(); };
  dialog.append(node('div',{className:'modal-heading'},node('h2',{},title),button('关闭',close,'ghost small')),content);
  document.body.append(dialog); dialog.addEventListener('close',()=>dialog.remove());
  dialog.addEventListener('click',e=>{ if(e.target === dialog && e.clientX < dialog.getBoundingClientRect().left) close(); });
  dialog.showModal(); return close;
}
export function navigate(view,params={}) { const search = new URLSearchParams(params).toString(); location.hash = view+(search?'?'+search:''); }
export function refresh() { window.dispatchEvent(new Event('hashchange')); }
export function dateTime(v) { if (!v) return '—'; const d = new Date(v); return Number.isNaN(d.valueOf()) ? String(v) : d.toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}); }
export function roleName(code) { return labels[code] || code; }
