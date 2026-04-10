import type { Env } from "../db/postgres";
import { withClient } from "../db/postgres";
import { getCalendarFeedRows } from "../db/queries";
import { buildCalendarFeed } from "../lib/ics";
import { text } from "../lib/http";

export async function handleCalendar(_request: Request, env: Env): Promise<Response> {
  const rows = await withClient(env, (client) => getCalendarFeedRows(client));
  const feed = buildCalendarFeed(
    rows.map((row: Awaited<ReturnType<typeof getCalendarFeedRows>>[number]) => ({
      date: row.date,
      timeStart: row.time_start,
      timeEnd: row.time_end,
      studio: row.studio,
      show: row.show,
      castType: row.cast_type,
      notes: row.notes,
    })),
  );

  return text(feed, {
    headers: {
      "Content-Type": "text/calendar; charset=utf-8",
    },
  });
}
