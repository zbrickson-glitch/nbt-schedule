-- NBT LLM Parser v2: Test schema (parallel to nbt.*)
CREATE SCHEMA IF NOT EXISTS nbt_test;

CREATE TABLE IF NOT EXISTS nbt_test.schedule_events (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    time_start TIME NOT NULL,
    time_end TIME,
    studio TEXT,
    show TEXT NOT NULL,
    staff TEXT,
    cast_type TEXT,
    notes TEXT,
    event_type TEXT DEFAULT 'rehearsal',
    fitting_dancer TEXT,
    source_email_id TEXT,
    source_filename TEXT,
    is_revised BOOLEAN DEFAULT FALSE,
    llm_raw_output JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nbt_test.casting (
    id SERIAL PRIMARY KEY,
    dancer_name TEXT NOT NULL,
    show TEXT NOT NULL,
    section TEXT,
    role TEXT DEFAULT 'cast',
    cover_for TEXT,
    source_email_id TEXT,
    llm_raw_output JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nbt_test.parse_log (
    id SERIAL PRIMARY KEY,
    source_email_id TEXT,
    source_filename TEXT,
    pdf_type TEXT,
    input_text TEXT,
    llm_raw_response TEXT,
    parsed_json JSONB,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    latency_ms INTEGER,
    model TEXT DEFAULT 'qwen3-max',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
