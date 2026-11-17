import os
import time

_engine = None
_cache = {"value": None, "at": 0.0}
CACHE_TTL = 5.0
KEY = "bot_enabled"
OFF_VALUES = ("off", "false", "0", "no", "nonaktif")

def _get_engine():
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine
        _engine = create_engine(os.getenv("DATABASE_URL"))
    return _engine

def _read_setting():
    from sqlalchemy import text
    with _get_engine().connect() as conn:
        row = conn.execute(text(
            """
            SELECT setting_value FROM bot_settings
            WHERE setting_name = :n 
            LIMIT 1
            """
        ),{"n": KEY}).fetchone()
    return row[0] if row else None

def _write_setting(value: str) -> None:
    from sqlalchemy import text
    with _get_engine().begin() as conn:
        exists = conn.execute(text(
            """
            SELECT COUNT(*) FROM bot_settings
            WHERE setting_name = :n
            """
        ),{"n": KEY}).scalar()

        if exists:
            conn.execute(text(
                """
                UPDATE bot_settings
                SET setting_value = :v
                WHERE setting_name = :n
                """    
            ), {"v": value, "n": KEY})
        else:
            conn.execute(text(
                """
                INSERT INTO bot_settings (setting_name, setting_value)
                VALUES (:n, :v)    
                """
            ), {"n": KEY, "v": value})

def is_bot_enabled(force: bool = False) -> bool:
    now = time.time()
    if not force and _cache["value"] is not None and now - _cache["at"] < CACHE_TTL:
        return _cache["value"]
    try:
        raw = _read_setting()
        value = True if raw is None else str(raw).strip().lower() not in OFF_VALUES
    except Exception as e:
        print(f"[settings] gagal membaca {KEY}: {3}; dianggap aktif")
        value = True
    _cache.update(value=value, at=now)
    return value

def set_bot_enabled(enabled: bool) -> None:
    _write_setting("on" if enabled else "off")
    _cache.update(value=enabled, at=time.time())