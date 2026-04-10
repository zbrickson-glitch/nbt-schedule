import type { Env } from "../db/postgres";
import { withClient } from "../db/postgres";
import { getScheduleForDate } from "../db/queries";
import { error, json } from "../lib/http";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export async function handleSchedule(_request: Request, env: Env, eventDate: string): Promise<Response> {
  if (!DATE_RE.test(eventDate)) {
    return error(400, "event_date must be YYYY-MM-DD");
  }

  const rows = await withClient(env, (client) => getScheduleForDate(client, eventDate));
  return json(rows);
}
