const CACHE = 'slys-shell-v1';
// 离线外壳缓存：静态资源离线可用；页面走网络（失败时回缓存）。
// 提交类操作需要网络（恢复后重试）；表单内容由 autosave.js 暂存本地，不怕丢。
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(resp => {
      const copy = resp.clone();
      caches.open(CACHE).then(cc => cc.put(e.request, copy));
      return resp;
    })));
  } else if (url.pathname === '/onsite') {
    // 现场登记页离线可用：网络优先，断网回缓存外壳（表单内容由 autosave.js 本地暂存兜底）
    e.respondWith(fetch(e.request).then(resp => {
      const copy = resp.clone();
      caches.open(CACHE).then(cc => cc.put(e.request, copy));
      return resp;
    }).catch(() => caches.match(e.request)));
  }
});
