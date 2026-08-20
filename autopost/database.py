"""
AutoPost — Banco de dados local (SQLite).

Responsável por guardar vídeos, publicações agendadas, contas conectadas
e histórico de eventos. Se o computador reiniciar no meio da madrugada,
o programa sabe exatamente onde parou ao reabrir.
"""

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "autopost.db"

_lock = threading.local()


def _new_connection() -> sqlite3.Connection:
    """Cria e configura uma nova conexão SQLite."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_connection() -> sqlite3.Connection:
    """Retorna uma conexão dedicada por thread (Tkinter roda na thread principal).
    Reconecta automaticamente se a conexão guardada tiver sido fechada."""
    if not hasattr(_lock, "conn") or _lock.conn is None:
        _lock.conn = _new_connection()
    return _lock.conn




def close_connection() -> None:
    """Fecha a conexão da thread atual (chamado apenas na saída do programa)."""
    if hasattr(_lock, "conn") and _lock.conn is not None:
        _lock.conn.close()
        _lock.conn = None


class SharedConn:
    """Wrapper da conexão SQLite compartilhada por thread: delega tudo, mas o
    close() não tem efeito. Assim nenhum módulo quebra o banco ao fechar a
    conexão que ele recebeu de db() (o erro era 'closed database').
    Só close_connection() — saída do programa — fecha de verdade."""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection):
        object.__setattr__(self, "_conn", conn)

    def close(self) -> None:  # no-op
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    def __iter__(self):
        return iter(self._conn)

    def __repr__(self):
        return f"SharedConn({self._conn!r})"


def db() -> SharedConn:
    """Alias curto usado pela interface e pelo executor.
    Migra o banco e devolve a conexão compartilhada da thread. Todos os módulos
    devem usar a mesma conexão da sua thread (sqlite3 não tolera várias
    conexões gravando ao mesmo tempo — isso causava 'database is locked')."""
    conn = get_connection()
    # se a conexão compartilhada foi fechada (ex.: saída de outro módulo), recriar
    try:
        conn.execute("SELECT 1")
    except Exception:
        close_connection()
        conn = get_connection()
    _migrate(conn)
    return SharedConn(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS videos (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            path      TEXT    NOT NULL UNIQUE,
            title     TEXT,
            description TEXT,
            hashtags  TEXT,
            duration  INTEGER,
            added_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            status    TEXT    NOT NULL DEFAULT 'Pendente'
        );

        CREATE TABLE IF NOT EXISTS posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            platform    TEXT    NOT NULL,
            account     TEXT,
            scheduled_at TEXT,
            status      TEXT    NOT NULL DEFAULT 'Agendado',
            link        TEXT,
            error       TEXT,
            privacy     TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT    NOT NULL,
            name        TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'Desconectada',
            credentials TEXT,
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            message   TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            k         TEXT PRIMARY KEY,
            v         TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_posts_video   ON posts(video_id);
        CREATE INDEX IF NOT EXISTS idx_posts_status  ON posts(status);
        CREATE INDEX IF NOT EXISTS idx_posts_sched   ON posts(scheduled_at);
    """)
    conn.commit()

    # migrações incrementais — uma por coluna, todas idempotentes
    for sql in [
        # V5 — privacidade por publicação (TikTok)
        "ALTER TABLE posts ADD COLUMN privacy TEXT",
        # V6 — miniatura em cache, arquivo convertido (formato da plataforma)
        "ALTER TABLE videos ADD COLUMN thumb_path TEXT",
        "ALTER TABLE videos ADD COLUMN converted_path TEXT",
        # V6 — metadados gerados pela IA (título, legenda, hashtags)
        "ALTER TABLE videos ADD COLUMN ai_title TEXT",
        "ALTER TABLE videos ADD COLUMN ai_caption TEXT",
        "ALTER TABLE videos ADD COLUMN ai_hashtags TEXT",
        # V7.4 — capa estilo post (frame do vídeo + faixa com o título)
        "ALTER TABLE videos ADD COLUMN cover_path TEXT",
    ]:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass
