import type { Env } from "../db/postgres";
import { withClient } from "../db/postgres";
import { getCasting, getCastingShows } from "../db/queries";
import { json } from "../lib/http";

export async function handleCasting(_request: Request, env: Env): Promise<Response> {
  const rows = await withClient(env, (client) => getCasting(client));
  return json(rows);
}

export async function handleCastingShows(_request: Request, env: Env): Promise<Response> {
  const rows = await withClient(env, (client) => getCastingShows(client));
  return json(rows);
}
