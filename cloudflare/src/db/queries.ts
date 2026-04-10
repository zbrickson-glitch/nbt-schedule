import type pg from "pg";

export type ScheduleEventRow = {
  id: number;
  date: string;
  time_start: string;
  time_end: string | null;
  studio: string | null;
  show: string;
  staff: string | null;
  cast_type: string | null;
  notes: string | null;
  event_type: string | null;
  fitting_dancer: string | null;
  is_revised: boolean | null;
};

export type CastingRow = {
  dancer_name: string;
  show: string;
  section: string | null;
  role: string | null;
  cover_for: string | null;
};

export type SeasonData = {
  season: string;
  weeks: Array<Record<string, unknown>>;
};

export async function getScheduleForDate(client: pg.Client, eventDate: string): Promise<ScheduleEventRow[]> {
  const result = await client.query<ScheduleEventRow>(
    `SELECT id, date::text, time_start::text, time_end::text, studio, show, staff,
            cast_type, notes, event_type, fitting_dancer, is_revised
       FROM schedule_events
      WHERE date = $1::date
        AND source_email_id = (
          SELECT source_email_id
            FROM schedule_events
           WHERE date = $1::date
           GROUP BY source_email_id
           ORDER BY max(created_at) DESC
           LIMIT 1
        )
      ORDER BY time_start`,
    [eventDate],
  );
  return result.rows;
}

export async function getCasting(client: pg.Client): Promise<CastingRow[]> {
  const result = await client.query<CastingRow>(
    `SELECT dancer_name, show, section, role, cover_for
       FROM casting
      ORDER BY show, section, role, dancer_name`,
  );
  return result.rows;
}

export async function getCastingShows(client: pg.Client): Promise<string[]> {
  const result = await client.query<{ show: string }>(
    `SELECT DISTINCT show
       FROM casting
      ORDER BY show`,
  );
  return result.rows.map((row: { show: string }) => row.show);
}

export async function createFeedback(client: pg.Client, message: string): Promise<void> {
  await client.query(
    `CREATE TABLE IF NOT EXISTS feedback (
      id SERIAL PRIMARY KEY,
      message TEXT NOT NULL,
      created_at TIMESTAMPTZ DEFAULT NOW()
    )`,
  );
  await client.query("INSERT INTO feedback (message) VALUES ($1)", [message]);
}

export async function getCalendarFeedRows(client: pg.Client) {
  const result = await client.query<{
    date: string;
    time_start: string;
    time_end: string | null;
    studio: string | null;
    show: string;
    cast_type: string | null;
    notes: string | null;
  }>(
    `SELECT date::text, time_start::text, time_end::text, studio, show, cast_type, notes
       FROM schedule_events
      WHERE event_type = 'rehearsal'
      ORDER BY date, time_start`,
  );
  return result.rows;
}
