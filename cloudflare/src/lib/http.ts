export function json(data: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json; charset=utf-8");
  }
  return new Response(JSON.stringify(data), {
    ...init,
    headers,
  });
}

export function text(body: string, init: ResponseInit = {}): Response {
  return new Response(body, init);
}

export function error(status: number, message: string): Response {
  return json({ error: message }, { status });
}
