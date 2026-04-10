// Service worker for PWA install support
const CACHE_NAME = 'nbt-schedule-v1';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
    // Network-first strategy - always try to get fresh data
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
