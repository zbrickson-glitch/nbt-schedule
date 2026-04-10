-- Enforce idempotency at DB level: one ingest per source email
-- Allows NULL source_email_id for manual entries
CREATE UNIQUE INDEX IF NOT EXISTS idx_schedule_events_source_email_id
  ON nbt.schedule_events(source_email_id)
  WHERE source_email_id IS NOT NULL;

-- Drop unused column (LLM comparison result, never written after today's cleanup)
ALTER TABLE nbt.schedule_events
  DROP COLUMN IF EXISTS parser_b_json;
