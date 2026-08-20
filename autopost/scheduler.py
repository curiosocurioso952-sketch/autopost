"""
AutoPost V5 — Executor de publicações.

Fusão do antigo agendador com o novo modo de execução imediata. A thread em
segundo plano trabalha em dois regimes:

1. Agendado: verifica a tabela `posts` a cada 15 segundos e publica tudo cujo
   horário chegou (continua valendo mesmo se o computador reiniciar).
2. Imediato: quando o usuário clica em "▶ INICIAR", cria publicações
   'Aguardando' na fila e o mesmo loop as processa na ordem, atualizando o
   status para 'Publicando'/'Publicado'/'Erro' e emitindo eventos de progresso.

Publicação direta por API oficial (nada de simular cliques no navegador).
"""

import sqlite3
import threading
import time
from datetime import datetime

from . import database as db
from .platforms.base import PublishRequest
from .platforms.youtube import YouTubePlatform
from .platforms.instagram import InstagramPlatform
from .platforms.tiktok import TikTokPlatform

PLATFORMS = {
    "YouTube": YouTubePlatform,
    "Instagram": InstagramPlatform,
    "TikTok": TikTokPlatform,
}


class Scheduler:
    """Executor em segundo plano. Suporta agendamento e execução imediata."""

    def __init__(self, on_event=None, on_progress=None):
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._on_event = on_event or (lambda m: None)
        self._on_progress = on_progress or (lambda a, b, c, d, e: None)
        # (post_id) ordenados pelo usuário para o modo imediato
        self._immediate_queue: list[int] = []
        self._pausing = threading.Event()
        self._pausing.set()  # não pausado por padrão
        self._instances: dict[str, object] = {}

    # -------------------------------------------------------------- controle
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._pausing.set()

    # ------------------------------------------------------------- imediato
    def enqueue_immediate(self, post_ids: list[int]):
        """Adiciona publicações ao modo imediato (fila "INICIAR agora")."""
        with self._lock:
            for pid in post_ids:
                if pid not in self._immediate_queue:
                    self._immediate_queue.append(pid)
            db.db().execute(
                "UPDATE posts SET status='Aguardando', scheduled_at=? "
                "WHERE id IN (%s)" % ",".join("?" for _ in post_ids),
                [datetime.now().isoformat(timespec="minutes")] + list(post_ids))
            db.db().commit()

    def cancel_posts(self, post_ids: list[int]):
        with self._lock:
            self._immediate_queue = [p for p in self._immediate_queue if p not in post_ids]
            conn = db.db()
            conn.execute(
                "UPDATE posts SET status='Cancelado' WHERE id IN (%s) AND status NOT IN ('Publicando','Publicado')"
                % ",".join("?" for _ in post_ids), post_ids)
            conn.commit()
            

    def toggle_pause(self):
        if self._pausing.is_set():
            self._pausing.clear()
        else:
            self._pausing.set()

    # ------------------------------------------------------------------ loop
    def _run(self):
        while not self._stop.is_set():
            self._pausing.wait()
            self._process_queue()
            self._process_scheduled()
            self._stop.wait(10)

    def _process_queue(self):
        """Modo imediato: processa as publicações da fila do usuário."""
        with self._lock:
            todo = list(self._immediate_queue)
        for post_id in todo:
            if self._stop.is_set():
                return
            self._pausing.wait()
            conn = db.db()
            row = conn.execute(
                "SELECT id, video_id, platform, status FROM posts WHERE id=?",
                (post_id,)).fetchone()
            if row is None:
                with self._lock:
                    self._immediate_queue = [p for p in self._immediate_queue if p != post_id]
                
                continue
            if row["status"] in ("Publicado", "Erro", "Cancelado"):
                with self._lock:
                    self._immediate_queue = [p for p in self._immediate_queue if p != post_id]
                
                continue
            if row["status"] == "Aguardando":
                self._progress(post_id, row["video_id"], row["platform"], "Iniciando…")
                conn.execute("UPDATE posts SET status='Publicando' WHERE id=?", (post_id,))
                conn.commit()
            
            self._execute(post_id, row["video_id"], row["platform"])

    def _process_scheduled(self):
        """Modo agendado: publica posts vencidos pelo horário."""
        conn = db.db()
        now = datetime.now().isoformat(timespec="minutes")
        rows = conn.execute(
            "SELECT id, video_id, platform FROM posts "
            "WHERE status='Agendado' AND scheduled_at<=? ORDER BY scheduled_at", (now,)
        ).fetchall()
        
        for row in rows:
            self._execute(row["id"], row["video_id"], row["platform"])

    def _execute(self, post_id: int, video_id: int, platform: str):
        conn = db.db()
        row = conn.execute(
            "SELECT v.path, v.title, v.description, v.hashtags, v.converted_path, p.privacy "
            "FROM videos v JOIN posts p ON p.video_id=v.id WHERE p.id=?", (post_id,)).fetchone()
        if row is None:
            conn.execute("UPDATE posts SET status='Erro', error='Vídeo removido' WHERE id=?", (post_id,))
            conn.commit()
            return

        klass = PLATFORMS.get(platform)
        inst = self._instances.get(platform)
        if inst is None or not inst.is_connected():
            conn.execute("UPDATE posts SET status='Aguardando', error='Plataforma não conectada' WHERE id=?",
                         (post_id,))
            conn.commit()
            self._on_event(f"[{platform}] Conta não conectada — '{row['title']}' aguardando conexão.")
            return

        # metadados específicos por plataforma (privacidade do TikTok, tipo de mídia etc.)
        extra = {}
        if platform == "TikTok":
            extra["privacy"] = (row["privacy"] or "PUBLIC_TO_EVERYONE").upper().replace(" ", "_")

        # se o vídeo foi convertido para o formato da plataforma, publicar a versão preparada
        import os
        source = row["path"]
        if row["converted_path"] and os.path.exists(row["converted_path"]):
            source = row["converted_path"]

        req = PublishRequest(
            video_path=source, title=row["title"] or "",
            description=row["description"] or "", hashtags=row["hashtags"] or "",
            extra=extra)
        self._progress(post_id, video_id, platform, "Enviando vídeo…")
        try:
            link = inst.publish(req)
            conn.execute("UPDATE posts SET status='Publicado', link=? WHERE id=?", (link, post_id))
            self._on_event(f"[{platform}] Publicado: {row['title']} → {link}")
        except Exception as e:
            conn.execute("UPDATE posts SET status='Erro', error=? WHERE id=?", (str(e)[:300], post_id))
            self._on_event(f"[{platform}] Erro ao publicar '{row['title']}': {e}")
        self._progress(post_id, video_id, platform,
                       conn.execute("SELECT status FROM posts WHERE id=?", (post_id,)).fetchone()["status"])
        conn.commit()

    # ------------------------------------------------------------------ util
    def _progress(self, post_id: int, video_id: int, platform: str, status: str):
        """Emite evento de progresso para o painel de monitoramento."""
        try:
            self._on_progress(post_id, video_id, platform, status, "")
        except TypeError:
            self._on_progress(post_id, platform, status)

    def _event(self, msg: str):
        self._on_event(msg)

    def register(self, platform: str, instance):
        self._instances[platform] = instance
