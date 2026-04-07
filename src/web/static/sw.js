/**
 * PAGAL OS Service Worker — enables PWA install, offline caching, and push notifications.
 */

const CACHE_NAME = 'pagal-os-v1';
const STATIC_ASSETS = [
    '/',
    '/static/style.css',
    '/static/app.js',
    '/static/manifest.json',
];

// Install: cache static assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch: network-first for API, cache-first for static assets
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // API calls: always go to network
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(fetch(event.request).catch(() =>
            new Response(JSON.stringify({ ok: false, error: 'Offline' }), {
                headers: { 'Content-Type': 'application/json' },
            })
        ));
        return;
    }

    // Static assets: cache-first
    event.respondWith(
        caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
});

// Push notifications from agents
self.addEventListener('push', (event) => {
    const data = event.data ? event.data.json() : { title: 'PAGAL OS', body: 'Agent notification' };
    event.waitUntil(
        self.registration.showNotification(data.title || 'PAGAL OS', {
            body: data.body || 'Your agent has completed a task.',
            icon: '/static/icon-192.png',
            badge: '/static/icon-192.png',
            data: data.url || '/',
        })
    );
});

// Click notification -> open app
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(clients.openWindow(event.notification.data || '/'));
});
