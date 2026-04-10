import type { Env } from "../db/postgres";
import { withClient } from "../db/postgres";
import { createFeedback } from "../db/queries";
import { error, json } from "../lib/http";

type FeedbackBody = {
  message?: unknown;
};

export async function handleFeedback(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const contentLength = Number(request.headers.get("content-length") ?? 0);
  if (contentLength > 2048) {
    return error(413, "request body too large");
  }

  let body: FeedbackBody;
  try {
    body = (await request.json()) as FeedbackBody;
  } catch {
    return error(400, "invalid JSON body");
  }

  const message = typeof body.message === "string" ? body.message.trim() : "";
  if (!message || message.length > 500) {
    return error(400, "message is required (max 500 chars)");
  }

  await withClient(env, (client) => createFeedback(client, message));
  if (env.DISCORD_WEBHOOK_URL) {
    ctx.waitUntil(forwardToDiscord(env.DISCORD_WEBHOOK_URL, env.SITE_ORIGIN, message));
  }

  return json({ status: "ok" });
}

async function forwardToDiscord(webhookUrl: string, siteOrigin: string, message: string): Promise<void> {
  await fetch(webhookUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "User-Agent": "NBT-Schedule-Cloudflare/1.0",
    },
    body: JSON.stringify({
      content: `**Schedule Suggestion** (from ${siteOrigin}):\n> ${message}`,
    }),
  }).catch(() => undefined);
}
