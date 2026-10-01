/* Service worker.
 *
 * Two jobs, and one of them is a security control.
 *
 * 1. Stale-while-revalidate for the shell and the API, because an iOS PWA gets
 *    no background refresh whatsoever and the app must therefore paint
 *    instantly from cache and correct itself a moment later.
 *
 * 2. **Refuse every cross-origin request.** The HTML already contains no
 *    third-party subresources and the CSP already says `default-src 'self'`,
 *    so this is the third independent lock on the same door. It exists because
 *    the failure it prevents -- a map tile fetched straight from the phone,
 *    carrying its IP *and* the tile coordinates, which is the location twice
 *    over -- is exactly the one this whole project was built to avoid, and
 *    because the person who eventually adds a "quick" CDN import will not be
 *    thinking about it.
 */
'use strict';

// NOT bumped by hand. The server substitutes a hash of index.html + app.js +
// sw.js when it serves this file, so any shell change invalidates every cache
// automatically. Over one afternoon the manual version of this was bumped
// eight times; the ninth is the one you forget, and the symptom -- a redesign
// invisible to installed devices but fine in a fresh browser -- is nasty to
// diagnose. See app/version.py.
//
// The literal below is what you see when reading the file from disk; it is
// replaced in flight by GET /sw.js.
const VERSION = '__SHELL_VERSION__';
const SHELL = VERSION + '-shell';
const DATA = VERSION + '-data';
const SCOPE = new URL(self.registration.scope).pathname;

const PRECACHE = [
  SCOPE,
  SCOPE + 'app.js',
  SCOPE + 'config.js',
  SCOPE + 'manifest.webmanifest',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(SHELL)
      .then((c) => c.addAll(PRECACHE))      // uncaught: keep the old worker
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Line of defence #3. Nothing leaves this origin, ever.
  if (url.origin !== self.location.origin) {
    e.respondWith(new Response('blocked: cross-origin request', {
      status: 403, statusText: 'Forbidden by service worker'
    }));
    return;
  }

  if (e.request.method !== 'GET') return;

  if (url.pathname.startsWith(SCOPE + 'api/')) {
    e.respondWith(networkFirst(e.request));
    return;
  }
  e.respondWith(staleWhileRevalidate(e.request));
});

async function networkFirst(req) {
  const cache = await caches.open(DATA);
  try {
    const fresh = await fetch(req);
    // What an offline launch shows, newest 8 (invariant 8).
    if (fresh.ok && /api\/(weather|cities)\b/.test(req.url)) cache.put(req, fresh.clone())
      .then(() => cache.keys()).then((ks) => ks.slice(0, -8).forEach((k) => cache.delete(k)));
    return fresh;
  } catch (err) {
    const hit = await cache.match(req);
    if (hit) return hit;
    // An honest failure, in the shape the front end already understands.
    return new Response(JSON.stringify({
      health: { status: 'down', warnings: ['Нет сети и нет кэша'] }
    }), { status: 503, headers: { 'Content-Type': 'application/json' } });
  }
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(req);
  const net = fetch(req).then((res) => {
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  }).catch(() => null);
  return hit || (await net) || new Response('Нет сети', {
    status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
