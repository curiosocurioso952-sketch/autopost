"""
AutoPost V7 — Preferências do aplicativo.

- Horários de pico dinâmicos por dia da semana (baseado em dados de engajamento
  de redes sociais no Brasil: picos na manhã, almoço, fim de tarde e noite).
  O usuário não precisa (nem pode) digitar horários manualmente — o app decide.

- Persistência de preferências (tema, chave IA, idioma) na tabela `settings`
  do banco SQLite.
"""

from datetime import datetime

# Horários recomendados por dia da semana (0 = segunda, 6 = domingo).
# Fontes gerais de engajamento (BR): 7-9h (manhã/metrô), 12-13h (almoço),
# 17-19h (fim de tarde), 20-22h (noite relaxando). Sexta e sábado têm pico
# mais tarde; domingo tende ao início da noite.
PEAK_HOURS_BY_WEEKDAY: dict[int, list[int]] = {
    0: [7, 12, 18, 21],   # Segunda
    1: [7, 12, 18, 21],   # Terça
    2: [7, 12, 18, 21],   # Quarta
    3: [7, 12, 18, 21],   # Quinta
    4: [8, 12, 17, 22],   # Sexta
    5: [10, 14, 19, 22],  # Sábado
    6: [11, 15, 20, 22],  # Domingo
}

WEEKDAY_LABELS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def peak_hours_for(dt: datetime) -> list[int]:
    """Horários de pico recomendados para a data (considera o dia da semana)."""
    return list(PEAK_HOURS_BY_WEEKDAY.get(dt.weekday(), [7, 12, 18, 21]))


def next_peak_slot(dt: datetime) -> datetime:
    """Próximo slot de horário de pico a partir de dt (retorna dt se dt já está
    num slot de pico, com os minutos zerados)."""
    from datetime import timedelta
    c = dt.replace(second=0, microsecond=0)
    for _ in range(7 * 24 + 24):  # procurar pelos próximos ~7 dias
        if c.hour in peak_hours_for(c):
            return c
        c += timedelta(hours=1)
    return dt  # fallback: nunca deveria chegar aqui


def all_peak_hours() -> list[int]:
    """União ordenada de todos os horários de pico da semana (para o calendário)."""
    seen = []
    for hours in PEAK_HOURS_BY_WEEKDAY.values():
        for h in hours:
            if h not in seen:
                seen.append(h)
    return sorted(seen)


# -------------------------------------------------------------------- banco

def load_setting(k: str, default: str = "") -> str:
    """Lê uma preferência do banco. Cria a linha com o valor padrão se faltar.
    Não fecha a conexão: o database.py compartilha UMA conexão por thread (sqlite3
    só tolera uma gravando por vez); fechá-la aqui deixava a interface com 'closed
    database' — vídeos sumiam da lista e contadores zeravam."""
    from . import database as db
    conn = db.db()
    row = conn.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO settings(k, v) VALUES(?,?)", (k, default))
        conn.commit()
        return default
    return row["v"]


def save_setting(k: str, v: str) -> None:
    """Grava uma preferência do banco. Não fecha a conexão (ver load_setting)."""
    from . import database as db
    conn = db.db()
    conn.execute("INSERT INTO settings(k, v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (k, v))
    conn.commit()
