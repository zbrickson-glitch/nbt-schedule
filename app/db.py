import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from app.config import settings

@contextmanager
def get_db():
    conn = psycopg2.connect(
        settings.database_url,
        cursor_factory=RealDictCursor,
        options=f"-c search_path={settings.nbt_schema}",
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
