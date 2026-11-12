'use strict';
const CACHE = 'moa-shell-v12';
const SHELL = ['/', '/static/style.css', '/static/themes.css', '/static/theme.js', '/static/app.js', '/static/pwa.js', '/static/microphone.js', '/static/manifest.webmanifest',
  '/static/vendor/leaflet.js', '/static/vendor/leaflet.css',
  '/static/icons/icon-180.png', '/static/icons/icon-192.png', '/static/icons/icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  // Do not replace a running recording's page with a new version.
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('moa-shell-') && key !== CACHE).map(key => caches.delete(key)))));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.search || !SHELL.includes(url.pathname)) return;
  event.respondWith(fetch(event.request).then(response => {
    // Only public shell assets, never /api/*, recordings, results, map tiles or access keys.
    if (response.ok) event.waitUntil(caches.open(CACHE).then(cache => cache.put(url.pathname, response.clone())));
    return response;
  }).catch(async () => (await caches.match(url.pathname)) || Response.error()));
});
