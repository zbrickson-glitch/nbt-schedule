import type { Env } from "./db/postgres";
import { cacheGet, cachePut, withCacheHeaders } from "./lib/cache";
import { handleOptions, withCors } from "./lib/cors";
import { error } from "./lib/http";
import { handleCalendar } from "./routes/calendar";
import { handleCasting, handleCastingShows } from "./routes/casting";
import { handleFeedback } from "./routes/feedback";
import { handleSchedule } from "./routes/schedule";
import { handleSeason } from "./routes/season";

const CACHE_TTLS: Record<string, number> = {
  "/public/casting": 900,
  "/public/casting/shows": 900,
  "/public/season": 3600,
  "/public/calendar.ics": 300,
};

export default {
  async fetch(request, env, ctx): Promise<Response> {
    const url = new URL(request.url);
    const corsOrigin = env.CORS_ALLOW_ORIGIN || "*";

    if (request.method === "OPTIONS" && url.pathname.startsWith("/public/")) {
      return handleOptions(corsOrigin);
    }

    if (!url.pathname.startsWith("/public/")) {
      return env.ASSETS.fetch(request);
    }

    const cached = await cacheGet(request);
    if (cached) {
      return withCors(cached, corsOrigin);
    }

    try {
      let response: Response | null = null;

      if (request.method === "GET" && url.pathname.startsWith("/public/schedule/date/")) {
        const eventDate = url.pathname.replace("/public/schedule/date/", "");
        response = await handleSchedule(request, env, eventDate);
        response = withCacheHeaders(response, 300);
      } else if (request.method === "GET" && url.pathname === "/public/casting") {
        response = withCacheHeaders(await handleCasting(request, env), CACHE_TTLS[url.pathname] ?? 300);
      } else if (request.method === "GET" && url.pathname === "/public/casting/shows") {
        response = withCacheHeaders(await handleCastingShows(request, env), CACHE_TTLS[url.pathname] ?? 300);
      } else if (request.method === "GET" && url.pathname === "/public/season") {
        response = withCacheHeaders(await handleSeason(request, env), CACHE_TTLS[url.pathname] ?? 300);
      } else if (request.method === "POST" && url.pathname === "/public/feedback") {
        response = await handleFeedback(request, env, ctx);
      } else if (request.method === "GET" && url.pathname === "/public/calendar.ics") {
        response = withCacheHeaders(await handleCalendar(request, env), CACHE_TTLS[url.pathname] ?? 300);
      }

      if (!response) {
        return withCors(error(404, "Not found"), corsOrigin);
      }

      ctx.waitUntil(cachePut(request, response));
      return withCors(response, corsOrigin);
    } catch (cause) {
      console.error("Worker request failed", cause);
      return withCors(error(500, "Internal server error"), corsOrigin);
    }
  },
} satisfies ExportedHandler<Env>;
