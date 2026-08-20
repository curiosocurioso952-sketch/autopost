"""Insere o vídeo de teste no banco antes do teste da GUI (para o clique no calendário ter seleção)."""
import sys, os
from pathlib import Path

ROOT = Path("/home/ubuntu/autopost")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from autopost import database as db  # noqa

VID = "/home/ubuntu/testvid/Você teria coragem de fazer isso por R$ 1 MILHÃO.mp4"
conn = db.db()
row = conn.execute("SELECT id FROM videos WHERE path=?", (VID,)).fetchone()
if row is None:
    conn.execute(
        "INSERT INTO videos(path, title, hashtags, status) VALUES(?,?,?,?)",
        (VID, "Você teria coragem de fazer isso por R$ 1 MILHÃO", "viral, humor, desafio", "Adicionado"))
    conn.commit()
    print("inserido id", conn.execute("SELECT last_insert_rowid()").fetchone()[0])
else:
    print("já existe id", row[0])
conn.close()
