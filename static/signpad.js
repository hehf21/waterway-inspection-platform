/* 手写签名板：支持触屏/鼠标，输出 PNG dataURL（配合 /inspections/{id}/sign 提交）
   - 旋转屏幕/窗口缩放不丢笔迹（按新画布尺寸缩放重绘）
   - 有无笔迹用 dataset.ink 标记，避免空白画布数据校验被缩放干扰 */
function initSignPad(canvasId, clearBtnId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;

  function setup(preserve) {
    const w = canvas.clientWidth || 320, h = canvas.clientHeight || 180;
    const prev = (preserve && canvas.dataset.ink === '1') ? canvas.toDataURL('image/png') : null;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.lineWidth = 2.5; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#000';
    if (!prev) canvas.dataset.ink = '0';
    if (prev) {
      const img = new Image();
      img.onload = () => ctx.drawImage(img, 0, 0, w, h);   // 恢复笔迹（缩放到新尺寸）
      img.src = prev;
    }
  }
  setup(false);
  window.addEventListener('resize', () => setup(true));   // 缩放/旋转保留笔迹

  const ctx = () => canvas.getContext('2d');
  let drawing = false, last = null;
  const pos = e => {
    const r = canvas.getBoundingClientRect();
    const p = e.touches ? e.touches[0] : e;
    return [p.clientX - r.left, p.clientY - r.top];
  };
  const start = e => {
    const w = canvas.clientWidth || 320, h = canvas.clientHeight || 180;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) setup(true);   // 画布显示尺寸变了（如签字区展开）先同步，防笔迹错位
    drawing = true; last = pos(e); e.preventDefault();
  };
  const move = e => {
    if (!drawing) return;
    const [x, y] = pos(e);
    const c = ctx();
    c.beginPath(); c.moveTo(last[0], last[1]); c.lineTo(x, y); c.stroke();
    last = [x, y];
    canvas.dataset.ink = '1';
    e.preventDefault();
  };
  const end = () => { drawing = false; };
  canvas.addEventListener('mousedown', start);
  canvas.addEventListener('mousemove', move);
  window.addEventListener('mouseup', end);
  canvas.addEventListener('touchstart', start, { passive: false });
  canvas.addEventListener('touchmove', move, { passive: false });
  canvas.addEventListener('touchend', end);
  if (clearBtnId) {
    const btn = document.getElementById(clearBtnId);
    if (btn) btn.addEventListener('click', () => setup(false));   // 重签=清空画布
  }
}

function signPadData(canvasId) {
  const canvas = document.getElementById(canvasId);
  return canvas ? canvas.toDataURL('image/png') : '';
}

function submitSign(formId, canvasId) {
  const canvas = document.getElementById(canvasId);
  const data = canvas ? canvas.toDataURL('image/png') : '';
  if (!canvas || canvas.dataset.ink !== '1') { alert('请先在签名区手写签字'); return; }
  const form = document.getElementById(formId);
  form.querySelector('[name=image]').value = data;
  form.submit();
}
