"""
Knowledge Base per l'agente Arduino.
SQLite per dati strutturati, ChromaDB per ricerca semantica.
"""
import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "arduino_agent.db"
CHROMA_PATH = Path(__file__).parent / "chroma"

# ── Schema SQLite ──────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS snippets (
    id TEXT PRIMARY KEY,
    task_description TEXT NOT NULL,
    code TEXT NOT NULL,
    board TEXT DEFAULT 'arduino:avr:uno',
    libraries TEXT DEFAULT '[]',   -- JSON array
    tags TEXT DEFAULT '[]',        -- JSON array
    run_count INTEGER DEFAULT 1,
    success_count INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS libraries (
    name TEXT PRIMARY KEY,
    version TEXT,
    include_header TEXT,           -- es. #include <DHT.h>
    install_cmd TEXT,              -- es. arduino-cli lib install "DHT sensor library"
    description TEXT,
    example_code TEXT,
    source TEXT DEFAULT 'learned'  -- 'learned' | 'manual' | 'scraped'
);

CREATE TABLE IF NOT EXISTS error_fixes (
    id TEXT PRIMARY KEY,
    error_pattern TEXT NOT NULL,   -- regex o testo dell'errore
    cause TEXT,
    fix_description TEXT,
    fix_code_patch TEXT,           -- patch di codice se applicabile
    confirmed_count INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS boards (
    fqbn TEXT PRIMARY KEY,
    name TEXT,
    upload_port TEXT,              -- può essere null (rilevato auto)
    baud_rate INTEGER DEFAULT 9600
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    mode TEXT DEFAULT 'NEW',
    success INTEGER DEFAULT 0,
    iterations INTEGER DEFAULT 0,
    final_code TEXT,
    serial_output TEXT,
    thinking_log TEXT,             -- JSON
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,       -- es. "OLED animation", "LED blink", "sensor read"
    lesson TEXT NOT NULL,          -- la lezione: "specifica sempre posizioni iniziali hardcoded"
    spec_hint TEXT,                -- cosa scrivere nella task description per prevenire il bug
    hardware_quirk TEXT,           -- note hardware specifiche (nullable)
    board TEXT DEFAULT '',         -- board a cui si applica, vuoto = universale
    confirmed_count INTEGER DEFAULT 1,
    created_at TEXT
);

INSERT OR IGNORE INTO boards VALUES ('arduino:avr:uno', 'Arduino Uno', NULL, 9600);
INSERT OR IGNORE INTO boards VALUES ('arduino:avr:nano', 'Arduino Nano', NULL, 9600);
INSERT OR IGNORE INTO boards VALUES ('arduino:avr:mega', 'Arduino Mega', NULL, 9600);
"""


def _get_conn() -> sqlite3.Connection:
    """Apre e ritorna una connessione SQLite con row_factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Crea le tabelle se non esistono e popola le board di default."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def add_snippet(
    task: str,
    code: str,
    board: str = "arduino:avr:uno",
    libraries: list = None,
    tags: list = None,
) -> str:
    """Aggiunge uno snippet al DB e ritorna l'id generato."""
    if libraries is None:
        libraries = []
    if tags is None:
        tags = []

    sid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO snippets
                (id, task_description, code, board, libraries, tags,
                 run_count, success_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            """,
            (sid, task, code, board, json.dumps(libraries), json.dumps(tags), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return sid


def get_snippet(sid: str) -> dict:
    """Ritorna uno snippet come dict, oppure None se non trovato."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM snippets WHERE id = ?", (sid,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["libraries"] = json.loads(d["libraries"] or "[]")
        d["tags"] = json.loads(d["tags"] or "[]")
        return d
    finally:
        conn.close()


def update_snippet_stats(sid: str, success: bool) -> None:
    """Incrementa run_count e, se success=True, anche success_count."""
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    try:
        if success:
            conn.execute(
                """
                UPDATE snippets
                SET run_count = run_count + 1,
                    success_count = success_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, sid),
            )
        else:
            conn.execute(
                """
                UPDATE snippets
                SET run_count = run_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, sid),
            )
        conn.commit()
    finally:
        conn.close()


def search_snippets_text(keyword: str, limit: int = 10) -> list:
    """Ricerca testuale semplice su task_description e tags degli snippet."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM snippets
            WHERE task_description LIKE ? OR tags LIKE ?
            ORDER BY success_count DESC
            LIMIT ?
            """,
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["libraries"] = json.loads(d["libraries"] or "[]")
            d["tags"] = json.loads(d["tags"] or "[]")
            result.append(d)
        return result
    finally:
        conn.close()


def add_library(
    name: str,
    version: str = None,
    include: str = None,
    install_cmd: str = None,
    description: str = None,
    example: str = None,
    source: str = "manual",
) -> None:
    """Aggiunge o sostituisce una libreria nel DB."""
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO libraries
                (name, version, include_header, install_cmd,
                 description, example_code, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, version, include, install_cmd, description, example, source),
        )
        conn.commit()
    finally:
        conn.close()


def get_library(name: str) -> dict:
    """Ritorna una libreria come dict, oppure None se non trovata."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM libraries WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def search_libraries(keyword: str) -> list:
    """Cerca librerie per nome o descrizione."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM libraries
            WHERE name LIKE ? OR description LIKE ?
            """,
            (f"%{keyword}%", f"%{keyword}%"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_error_fix(
    pattern: str,
    cause: str = None,
    fix_description: str = None,
    fix_patch: str = None,
) -> str:
    """Aggiunge un fix per un errore e ritorna l'id."""
    eid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO error_fixes
                (id, error_pattern, cause, fix_description,
                 fix_code_patch, confirmed_count, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (eid, pattern, cause, fix_description, fix_patch, now),
        )
        conn.commit()
    finally:
        conn.close()
    return eid


def increment_fix_confirmed(pattern: str) -> None:
    """Incrementa confirmed_count per tutti i fix che matchano il pattern."""
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE error_fixes
            SET confirmed_count = confirmed_count + 1
            WHERE error_pattern = ?
            """,
            (pattern,),
        )
        conn.commit()
    finally:
        conn.close()


def get_error_fixes(pattern: str = None, limit: int = 20) -> list:
    """Ritorna i fix di errore, opzionalmente filtrati per pattern."""
    conn = _get_conn()
    try:
        if pattern:
            rows = conn.execute(
                """
                SELECT * FROM error_fixes
                WHERE error_pattern LIKE ?
                ORDER BY confirmed_count DESC
                LIMIT ?
                """,
                (f"%{pattern}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM error_fixes
                ORDER BY confirmed_count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_run(
    task: str,
    mode: str = "NEW",
    success: bool = False,
    iterations: int = 0,
    final_code: str = None,
    serial_output: str = None,
    thinking_log: list = None,
) -> str:
    """Aggiunge un record di esecuzione e ritorna l'id."""
    rid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO runs
                (id, task, mode, success, iterations,
                 final_code, serial_output, thinking_log, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                task,
                mode,
                1 if success else 0,
                iterations,
                final_code,
                serial_output,
                json.dumps(thinking_log or []),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return rid


def add_lesson(
    task_type: str,
    lesson: str,
    spec_hint: str = None,
    hardware_quirk: str = None,
    board: str = "",
) -> str:
    """Aggiunge una lezione appresa. Ritorna l'id. Sincronizza anche in ChromaDB."""
    lid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO lessons
                (id, task_type, lesson, spec_hint, hardware_quirk, board,
                 confirmed_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (lid, task_type, lesson, spec_hint, hardware_quirk, board, now),
        )
        conn.commit()
    finally:
        conn.close()
    # Sincronizza in ChromaDB per la ricerca semantica
    try:
        from knowledge.semantic import index_lesson
        index_lesson(
            lid=lid,
            task_type=task_type,
            lesson=lesson,
            spec_hint=spec_hint,
            hardware_quirk=hardware_quirk,
            board=board,
        )
    except Exception:
        pass  # ChromaDB opzionale — SQLite è fonte di verità
    return lid


def search_lessons(keyword: str, board: str = "", limit: int = 10) -> list:
    """Cerca lezioni per keyword (anche multi-parola) in task_type, lesson, spec_hint.
    Ogni parola viene cercata separatamente; si ritornano le righe che matchano almeno una."""
    conn = _get_conn()
    try:
        words = [w for w in keyword.lower().split() if len(w) > 2]
        if not words:
            words = [keyword]
        conditions = " OR ".join(
            "(LOWER(task_type) LIKE ? OR LOWER(lesson) LIKE ? OR LOWER(spec_hint) LIKE ?)"
            for _ in words
        )
        params = []
        for w in words:
            kw = f"%{w}%"
            params += [kw, kw, kw]
        params.append(board)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM lessons
            WHERE ({conditions})
            ORDER BY
                CASE WHEN board = ? THEN 0 ELSE 1 END,
                confirmed_count DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def increment_lesson_confirmed(lid: str) -> None:
    """Incrementa confirmed_count per una lezione (vista funzionare di nuovo)."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE lessons SET confirmed_count = confirmed_count + 1 WHERE id = ?",
            (lid,),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_runs(n: int = 10) -> list:
    """Ritorna gli ultimi n run ordinati per data decrescente."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["thinking_log"] = json.loads(d["thinking_log"] or "[]")
            result.append(d)
        return result
    finally:
        conn.close()
