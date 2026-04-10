-- source_email_id is a foreign key to the originating email, NOT a unique row key.
-- One email produces many schedule events. The unique index was wrong.
-- Replace with a regular index for fast lookups.
DROP INDEX IF EXISTS nbt.idx_schedule_events_source_email_id;
CREATE INDEX IF NOT EXISTS idx_schedule_events_source_email_id
  ON nbt.schedule_events(source_email_id)
  WHERE source_email_id IS NOT NULL;
