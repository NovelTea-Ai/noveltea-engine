// NovelTea Engine service worker: shows the push notifications the PC sends when a job finishes
// (a chapter part written, a narration ready). It caches nothing; the app always loads fresh from the PC.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()))

self.addEventListener('push', e => {
  let d = {}
  try { d = e.data ? e.data.json() : {} } catch { d = { title: 'NovelTea Engine', body: e.data ? e.data.text() : '' } }
  e.waitUntil(self.registration.showNotification(d.title || 'NovelTea Engine', {
    body: d.body || '', tag: d.tag || 'noveltea', icon: '/icon-192.png', badge: '/icon-192.png',
    data: { url: d.url || '/' },
  }))
})

self.addEventListener('notificationclick', e => {
  e.notification.close()
  const url = (e.notification.data && e.notification.data.url) || '/'
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const c of list) { if ('focus' in c) return c.focus() }
    return self.clients.openWindow(url)
  }))
})
