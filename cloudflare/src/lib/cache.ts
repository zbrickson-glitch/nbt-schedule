const CACHE_HOST = "https://cache.nbt.local";

export async function cacheGet(request: Request): Promise<Response | null> {
  if (request.method !== "GET") {
    return null;
  }
  const cache = caches.default;
  const cacheKey = new Request(new URL(request.url, CACHE_HOST).toString(), request);
  const cached = await cache.match(cacheKey);
  return cached ?? null;
}

export async function cachePut(request: Request, response: Response): Promise<void> {
  if (request.method !== "GET" || !response.ok) {
    return;
  }
  const cache = caches.default;
  const cacheKey = new Request(new URL(request.url, CACHE_HOST).toString(), request);
  await cache.put(cacheKey, response.clone());
}

export function withCacheHeaders(response: Response, maxAgeSeconds: number): Response {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", `public, max-age=${maxAgeSeconds}, s-maxage=${maxAgeSeconds}`);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}
