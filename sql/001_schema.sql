CREATE SCHEMA IF NOT EXISTS nbt;

CREATE TABLE IF NOT EXISTS nbt.roster (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL UNIQUE,
    email TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nbt.casting (
    id SERIAL PRIMARY KEY,
    dancer_name TEXT NOT NULL,
    show TEXT NOT NULL,
    section TEXT,
    role TEXT DEFAULT 'cast',
    cover_for TEXT,
    source_email_id TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(dancer_name, show, section, role)
);

CREATE TABLE IF NOT EXISTS nbt.schedule_events (
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
    parser_a_json JSONB,
    parser_b_json JSONB,
    parser_match BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nbt.subscribers (
    id SERIAL PRIMARY KEY,
    dancer_name TEXT NOT NULL,
    email TEXT,
    token TEXT NOT NULL UNIQUE DEFAULT gen_random_uuid()::TEXT,
    shows TEXT[] DEFAULT '{}',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nbt.schedule_history (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    replaced_at TIMESTAMPTZ DEFAULT NOW(),
    old_events JSONB,
    new_email_id TEXT,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_casting_show ON nbt.casting(show);
CREATE INDEX IF NOT EXISTS idx_casting_dancer ON nbt.casting(dancer_name);
CREATE INDEX IF NOT EXISTS idx_schedule_date ON nbt.schedule_events(date);
CREATE INDEX IF NOT EXISTS idx_subscribers_token ON nbt.subscribers(token);
