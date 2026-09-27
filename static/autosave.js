/* 检查表单自动保存：防误退出/误刷新/断网丢失登记内容（审计/现场使用反馈）
   用法：
     const AS = initAutosave({
       key: 'ins_' + INS_ID,            // 同一条记录一个存档槽
       formId: 'ins-form',
       getState: () => ({ current, probs }),      // JS 内存态（检查项/问题）
       setState: d => { current = d.current || []; probs = d.probs || []; renderItems(); renderProbs(); }
     });
     提交成功前调用 AS.clear()；随时可调 AS.save() 立即存。
   说明：文件附件无法暂存，恢复后需重新选择；页面顶部会出现“恢复/丢弃”提示条。 */
function initAutosave(opts) {
  const key = 'slys_autosave_' + opts.key;
  const form = document.getElementById(opts.formId);
  if (!form) return { save() {}, clear() {} };

  function collectFields() {
    const out = {};
    form.querySelectorAll('input,select,textarea').forEach(el => {
      if (!el.name || el.type === 'file' || el.type === 'hidden') return;   // 派生字段/附件不存
      if (el.type === 'checkbox') { out[el.name] = el.checked; return; }
      if (el.type === 'radio') { if (el.checked) out[el.name] = el.value; return; }
      out[el.name] = el.value;
    });
    return out;
  }
  function applyFields(fields) {
    if (!fields) return;
    form.querySelectorAll('input,select,textarea').forEach(el => {
      if (!el.name || el.type === 'file' || el.type === 'hidden') return;
      if (!(el.name in fields)) return;
      if (el.type === 'checkbox') { el.checked = !!fields[el.name]; return; }
      el.value = fields[el.name];
    });
  }

  let timer = null;
  function save() {
    clearTimeout(timer);
    timer = setTimeout(write, 400);
  }
  function write() {
    try {
      localStorage.setItem(key, JSON.stringify({
        t: Date.now(), fields: collectFields(), state: opts.getState ? opts.getState() : null
      }));
    } catch (e) {}
  }
  form.addEventListener('input', save);
  form.addEventListener('change', save);
  window.addEventListener('pagehide', write);      // 退出/切后台/关页前立即落盘
  window.addEventListener('beforeunload', write);

  // 恢复提示条：有未提交存档就显示（7 天内），由用户决定恢复或丢弃
  const MAX_AGE_MS = 7 * 24 * 3600 * 1000;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) {}
  if (saved && Date.now() - (saved.t || 0) > MAX_AGE_MS) {
    try { localStorage.removeItem(key); } catch (e) {}      // 过期存档自动清理，不再提示
    saved = null;
  }
  if (saved && (saved.fields || saved.state)) {
    const bar = document.createElement('div');
    bar.className = 'flash';
    bar.style.cssText = 'display:flex;gap:10px;align-items:center;flex-wrap:wrap';
    const tip = document.createElement('span');
    tip.innerHTML = '发现 <b>' + new Date(saved.t).toLocaleString() + '</b> 自动保存的未提交内容（附件需重新选择）';
    const bOk = document.createElement('button');
    bOk.type = 'button'; bOk.className = 'btn-sm btn-green'; bOk.textContent = '恢复';
    const bNo = document.createElement('button');
    bNo.type = 'button'; bNo.className = 'btn-sm btn-gray'; bNo.textContent = '丢弃';
    bar.appendChild(tip); bar.appendChild(bOk); bar.appendChild(bNo);
    const anchor = document.querySelector('main.container');
    if (anchor) anchor.insertBefore(bar, anchor.firstChild);
    bOk.addEventListener('click', () => {
      applyFields(saved.fields);
      if (opts.setState && saved.state) opts.setState(saved.state);
      bar.remove();
    });
    bNo.addEventListener('click', () => {
      try { localStorage.removeItem(key); } catch (e) {}
      bar.remove();
    });
  }

  return {
    save: write,
    clear() { clearTimeout(timer); try { localStorage.removeItem(key); } catch (e) {} }
  };
}
