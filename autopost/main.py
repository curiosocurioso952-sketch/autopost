"""
AutoPost V7 — Interface gráfica (Tkinter, em português).

Novidades da V7 sobre a V6:
  - Abas com rolagem vertical (nada fica cortado, em qualquer resolução)
  - Calendário maior, com destaque dos horários de pico POR DIA DA SEMANA
    (horários dinâmicos automáticos — o app escolhe os melhores horários;
    não existe mais campo manual nem intervalo fixo entre publicações)
  - Configurações do App via engrenagem no cabeçalho (janela própria) — sem aba dedicada
  - Calendário interativo: clique num dia/hora para agendar as publicações selecionadas
  - Tema escuro completo (claro e escuro, salvo no banco)
  - ffmpeg embutido na pasta tools/ (não precisa baixar manualmente)

Estrutura em abas:
  1. Contas        — conectar/desconectar contas por plataforma
  2. Conteúdo      — importar vídeos com miniaturas, gerar título/hashtags
                     com IA, converter para o formato de cada plataforma
                     e gravar legendas
  3. Configurar    — plataformas, legenda, hashtags e quando publicar
  4. Fila          — calendário grande com horários marcados e lista de posts
  5. Execução      — botão INICIAR e monitoramento em tempo real
  (Configurações virou janela aberta pela engrenagem no cabeçalho)

Banco SQLite local — a fila e as preferências sobrevivem a reinicializações.
"""

import os
import http.server
import threading
import time
import urllib.parse
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
from pathlib import Path

from . import database as db
from .scanner import scan_folder, scan_duration_guess
from . import media as mv
from . import ia as ai
from . import settings as prefs
from . import theme as THEME
from .scheduler import Scheduler, PLATFORMS
from .platforms.youtube import YouTubePlatform
from .platforms.instagram import InstagramPlatform
from .platforms.tiktok import TikTokPlatform

THUMB_CACHE = {}  # {vid: tk.PhotoImage}


class AutoPost(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AutoPost — Gerenciador de Publicações Automáticas (V7.5)")
        self.geometry("1280x780")
        self.minsize(1080, 680)

        # carregar preferência de tema e aplicar antes de construir a UI
        dark = prefs.load_setting("tema", "claro") == "escuro"
        self.theme_dark = tk.BooleanVar(value=dark)
        self.CORES = THEME.apply_theme(self, dark)

        self.scheduler = Scheduler(on_event=self.write_log, on_progress=self.on_progress)
        self.scheduler.register("YouTube", YouTubePlatform())
        self.scheduler.register("Instagram", InstagramPlatform())
        self.scheduler.register("TikTok", TikTokPlatform())

        self.var_plats = None  # criado em _build_tab_config
        self.var_privacy = tk.StringVar(value=prefs.load_setting("privacidade", "PUBLIC_TO_EVERYONE"))
        self.var_ai_key = tk.StringVar(value=prefs.load_setting("ia_key", ""))
        self.var_subtitles = tk.BooleanVar(value=prefs.load_setting("gravar_legendas", "0") == "1")
        self.var_convert = tk.BooleanVar(value=prefs.load_setting("converter", "1") == "1")
        self.var_when = tk.StringVar(value="later")
        self.var_idioma = tk.StringVar(value=prefs.load_setting("idioma", "pt-BR"))

        self._build_ui()
        self.refresh_all()
        self.scheduler.start()
        self.write_log("AutoPost V7.5 iniciado. Tema profissional, capa estilo post na prévia, agendamento por data/hora com IA automática e YouTube com arquivo em qualquer pasta.")

    # ===================================================================== UI
    def _build_ui(self):
        # cabeçalho
        header = ttk.Frame(self, padding=(16, 10))
        header.pack(fill="x")
        ttk.Label(header, text="AutoPost", font=("Segoe UI", 17, "bold"),
                  foreground=self.CORES["texto"]).pack(side="left")
        ttk.Label(header, text="Gerenciador de Publicações Automáticas — YouTube • Instagram • TikTok",
                  foreground=self.CORES["cinza"], font=("Segoe UI", 10)).pack(side="left", padx=(12, 0), pady=6)

        # estatísticas globais
        frame_stats = ttk.Frame(self, padding=(16, 0))
        frame_stats.pack(fill="x")
        self.stats = {}
        for label, key in [("Videos na fila", "pending"), ("Agendados", "scheduled"),
                           ("Publicando", "publishing"), ("Publicados", "published"),
                           ("Erros", "errors"), ("Total", "total")]:
            ttk.Label(frame_stats, text=f"{label}: ").pack(side="left")
            v = ttk.Label(frame_stats, text="0", foreground=self.CORES["sucesso"], font=("Segoe UI", 10, "bold"))
            v.pack(side="left", padx=(0, 14))
            self.stats[key] = v

        # abas (o conteúdo de cada aba tem rolagem própria)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        # ao alternar abas, redesenhar o calendário (o canvas precisa da largura
        # real da aba para montar a grade — senão fica vazio em alguns cenários)
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.tab_accounts = self._make_scroll_tab(self.tabs, "Contas")
        self.tab_content = self._make_scroll_tab(self.tabs, "Conteúdo")
        self.tab_config = self._make_scroll_tab(self.tabs, "Configurar Postagem")
        self.tab_queue = self._make_scroll_tab(self.tabs, "Fila e Calendário")
        self.tab_exec = self._make_scroll_tab(self.tabs, "Execução")

        self._build_tab_accounts(self.tab_accounts)
        self._build_tab_content(self.tab_content)
        self._build_tab_config(self.tab_config)
        self._build_tab_queue(self.tab_queue)
        self._build_tab_exec(self.tab_exec)

        # engrenagem de configurações no canto do cabeçalho
        ttk.Button(header, text="⚙  Configurações", command=self.open_settings).pack(side="right", padx=4)

    def _make_scroll_tab(self, notebook, text="") -> ttk.Frame:
        """Cria uma aba cuja área de conteúdo rola verticalmente.

        Estrutura: notebook -> outer (pack, adicionado ao notebook)
                   -> canvas + scrollbar -> inner (o conteúdo real)."""
        outer = ttk.Frame(notebook)
        outer.canvas = tk.Canvas(outer, highlightthickness=0, bg=self.CORES["fundo"])
        outer.vsb = ttk.Scrollbar(outer, orient="vertical", command=outer.canvas.yview)
        outer.inner = ttk.Frame(outer.canvas)
        outer.inner.bind(
            "<Configure>",
            lambda _e, c=outer.canvas: c.configure(scrollregion=c.bbox("all")))
        outer.canvas.bind(
            "<Configure>",
            lambda _e, c=outer.canvas: c.itemconfigure("tabwin", width=c.winfo_width())
            if c.winfo_width() > 0 else None)
        outer.canvas.create_window((0, 0), window=outer.inner, anchor="nw", tags=("tabwin",))
        outer.canvas.configure(yscrollcommand=outer.vsb.set)
        outer.vsb.pack(side="right", fill="y")
        outer.canvas.pack(side="left", fill="both", expand=True)

        # rolagem com a roda do mouse
        def _wheel(event):
            outer.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        outer.canvas.bind("<MouseWheel>", _wheel)
        outer.canvas.bind("<Button-4>", lambda _e: outer.canvas.yview_scroll(-1, "units"))
        outer.canvas.bind("<Button-5>", lambda _e: outer.canvas.yview_scroll(1, "units"))

        # adiciona ao notebook POR ÚLTIMO (após a montagem interna)
        notebook.add(outer, text=text)
        return outer.inner

    def _apply_all_themes(self):
        """Reaplica o tema em toda a janela (após trocar claro/escuro)."""
        self.CORES = THEME.apply_theme(self, self.theme_dark.get())
        # elementos que usam cores fixas precisam ser recoloridos
        self.btn_start.config(bg=self.CORES["destaque"], fg=self.CORES["btn_text"],
                              activebackground="#a31c3c")
        for lbl, key in self.stats.items():
            key.config(foreground=self.CORES["sucesso"])
        self._draw_calendar()
        self._check_ffmpeg()
        self.write_log(f"Tema alterado para {'escuro' if self.theme_dark.get() else 'claro'}.")

    def _on_tab_changed(self, _event=None):
        """Redesenha o calendário após exibir a aba 'Fila e Calendário'."""
        try:
            if self.tabs.index("current") == self.tabs.index(self.tab_queue):
                self._draw_calendar()
        except Exception:
            pass

    # ------------------------------------------------- 1) contas
    def _build_tab_accounts(self, tab):
        ttk.Label(tab, text="Conecte suas contas para publicar automaticamente. "
                  "Cada conta pode operar independentemente.",
                  foreground=self.CORES["cinza"]).pack(anchor="w", pady=(2, 10))

        frame = ttk.Frame(tab)
        frame.pack(fill="x")
        cols = ("Plataforma", "Conta", "Status")
        self.acc_tree = ttk.Treeview(frame, columns=cols, show="headings", height=4)
        for c, w in zip(cols, (220, 420, 160)):
            self.acc_tree.heading(c, text=c)
            self.acc_tree.column(c, width=w)
        self.acc_tree.pack(fill="x")

        bot_frame = ttk.Frame(tab, padding=(0, 10))
        bot_frame.pack(fill="x")
        ttk.Button(bot_frame, text="🟢 Conectar YouTube", command=self.connect_youtube).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="🟢 Conectar Instagram", command=self.connect_instagram).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="🟢 Conectar TikTok", command=self.connect_tiktok).pack(side="left", padx=4)
        ttk.Button(bot_frame, text="🔴 Desconectar selecionada", command=self.disconnect_selected).pack(side="right", padx=4)

        nota = ttk.Label(tab, text=("Nota: todos os conectores usam as APIs oficiais. Instagram exige conta "
                                    "Empresarial/Creator vinculada a uma Página do Facebook; TikTok publica "
                                    "como privado enquanto o app não passa na auditoria oficial. "
                                    "O ffmpeg já vem embutido na pasta tools/."),
                         wraplength=900, foreground=self.CORES["cinza"])
        nota.pack(anchor="w", pady=(4, 10))

    # ------------------------------------------------- 2) conteúdo
    def _build_tab_content(self, tab):
                # 1) importar vídeos
        imp_frame = ttk.LabelFrame(tab, text="1 · Importar vídeos", padding=10)
        imp_frame.pack(fill="x", pady=(0, 10))
        ttk.Button(imp_frame, text="Adicionar vídeos (seleção múltipla)", command=self.add_videos).pack(side="left", padx=(0, 8))
        ttk.Button(imp_frame, text="Adicionar pasta inteira", command=self.import_folder).pack(side="left", padx=(0, 8))
        ttk.Label(imp_frame, text="Clique em 'X Remover' para tirar da lista.",
                  foreground=self.CORES["cinza"]).pack(side="right", padx=8)
        ttk.Button(imp_frame, text="X Remover", command=self.remove_selected).pack(side="right", padx=4)
        # 2) biblioteca de vídeos
        mid = ttk.Frame(tab)
        mid.pack(fill="both", expand=True)
        thumb_frame = ttk.LabelFrame(mid, text="2 · Prévia do vídeo selecionado", padding=10)
        thumb_frame.pack(side="left", padx=(0, 10))
        self.lbl_thumb = ttk.Label(thumb_frame, text="Selecione um vídeo\npara ver a prévia",
                                   foreground=self.CORES["cinza"])
        self.lbl_thumb.pack(pady=(8, 6))
        self.lbl_cover_hint = ttk.Label(thumb_frame, text="", font=("Segoe UI", 8),
                                        foreground=self.CORES["destaque"])
        self.lbl_cover_hint.pack(pady=(0, 8))
        cols = ("#id", "Arquivo", "Título", "Hashtags", "Adicionado em", "Preparado")
        self.vid_tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended", height=16)
        widths = (50, 260, 340, 180, 150, 140)
        for c, w in zip(cols, widths):
            self.vid_tree.heading(c, text=c)
            self.vid_tree.column(c, width=w)
        self.vid_tree.pack(side="left", fill="both", expand=True)
        self.vid_tree.bind("<<TreeviewSelect>>", self.on_video_select)
        self.vid_tree.bind("<Double-1>", lambda _e: self.edit_selected())
        # 3) metadados e preparo
        meta_frame = ttk.LabelFrame(tab, text="3 · Metadados e preparo", padding=10)
        meta_frame.pack(fill="x", pady=(10, 0))
        ttk.Button(meta_frame, text="IA Gerar título/hashtags", command=self.ai_generate).pack(side="left", padx=(0, 8))
        ttk.Button(meta_frame, text="Editar título/descrição/hashtags", command=self.edit_selected).pack(side="left", padx=(0, 8))
        ttk.Button(meta_frame, text="Incluir na configuração", command=self.send_to_config).pack(side="left", padx=(0, 8))
        ttk.Button(meta_frame, text="Preparar vídeos (converter + legendas)", command=self.prepare_selected).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(meta_frame, text="Converter para o formato da plataforma (9:16)", variable=self.var_convert).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(meta_frame, text="Gravar legendas no vídeo", variable=self.var_subtitles).pack(side="left", padx=(0, 12))
        self.lbl_ffmpeg = ttk.Label(meta_frame, text="", foreground=self.CORES["cinza"])
        self.lbl_ffmpeg.pack(side="left")
        self._check_ffmpeg()

    # ------------------------------------------------- 3) configurar postagem
    def _build_tab_config(self, tab):
        ttk.Label(tab, text="Configure como os vídeos selecionados serão publicados. "
                  "A legenda e as hashtags abaixo valem como padrão (podem ser sobrescritas por vídeo).",
                  foreground=self.CORES["cinza"], wraplength=900).pack(anchor="w", pady=(2, 10))

        left = ttk.Frame(tab)
        left.pack(fill="x", pady=(0, 10))
        ttk.Label(left, text="1. Plataformas", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.var_plats = {p: tk.BooleanVar(value=True) for p in ["YouTube", "Instagram", "TikTok"]}
        pframe = ttk.Frame(left)
        pframe.pack(anchor="w", pady=4)
        for p, v in self.var_plats.items():
            ttk.Checkbutton(pframe, text=p, variable=v).pack(side="left", padx=(0, 24))

        ttk.Label(left, text="2. Legenda padrão (use {nome_video} para inserir o título do vídeo automaticamente)",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 4))
        self.e_caption = ttk.Entry(left, width=90)
        self.e_caption.pack(fill="x")
        ttk.Label(left, text="3. Hashtags (separadas por vírgula ou #)", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 4))
        self.e_hashtags = ttk.Entry(left, width=90)
        self.e_hashtags.pack(fill="x")

        mid = ttk.Frame(tab)
        mid.pack(fill="x", pady=(12, 10))
        ttk.Label(mid, text="4. Privacidade (TikTok)", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 4))
        for valor, rotulo in [("PUBLIC_TO_EVERYONE", "Público para todos"),
                              ("MUTUAL_FOLLOW_FRIENDS", "Apenas amigos mútuos"),
                              ("SELF_ONLY", "Privado (só eu)")]:
            ttk.Radiobutton(mid, text=rotulo, variable=self.var_privacy, value=valor).pack(anchor="w")

        right = ttk.Frame(tab)
        right.pack(fill="x", pady=(12, 10))
        ttk.Label(right, text="5. Quando publicar", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.var_when = tk.StringVar(value="later")
        f1 = ttk.Frame(right)
        f1.pack(anchor="w", pady=4)
        ttk.Radiobutton(f1, text="Agora (entra na fila de execução)", variable=self.var_when, value="now").pack(side="left", padx=(0, 18))
        ttk.Radiobutton(f1, text="Agendar (o app sugere os horários de pico)", variable=self.var_when, value="later").pack(side="left")
        ttk.Label(right, text=("Dica: no agendamento, o app usa como sugestão o próximo horário de pico "
                               "disponível — mas no calendário você pode escolher livremente qualquer dia e hora."),
                  foreground=self.CORES["cinza"], wraplength=800).pack(anchor="w", pady=(2, 10))

        bot = ttk.Frame(tab)
        bot.pack(fill="x", pady=(10, 10))
        ttk.Button(bot, text="🚀 Adicionar à fila com esta configuração", command=self.apply_config).pack(side="left", padx=4)
        ttk.Label(bot, text=("Dica: use {nome_video} na legenda para inserir automaticamente o título de cada vídeo."),
                  foreground=self.CORES["cinza"]).pack(side="left", padx=(14, 0))

    # ------------------------------------------------- 4) fila + calendário
    def _build_tab_queue(self, tab):
        top = ttk.Frame(tab, padding=(0, 6))
        top.pack(fill="x", pady=(0, 8))
        ttk.Button(top, text="▶ Publicar selecionadas agora", command=self.push_now).pack(side="left", padx=(0, 8))
        ttk.Button(top, text="X Cancelar selecionadas", command=self.cancel_selected).pack(side="left", padx=(0, 8))
        ttk.Label(top, text="Selecione as publicações na lista ou os vídeos na aba Conteúdo antes de clicar em um dia/hora.",
                  foreground=self.CORES["cinza"]).pack(side="left", padx=(10, 0))
        ttk.Button(top, text="Atualizar", command=self.refresh_all).pack(side="right", padx=4)

        cal_frame = ttk.LabelFrame(tab, text="1 · Calendário do mês — clique no dia e na hora exatos que quiser",
                                   padding=10)
        cal_frame.pack(fill="x", pady=(0, 8))
        self._cal_frame = cal_frame
        self._build_calendar_widget(cal_frame)

        # Agendamento rápido: escolha livre de data + hora + minuto
        fast = ttk.LabelFrame(tab, text="2 · Agendamento rápido — escolha o dia, a hora e os minutos exatos",
                              padding=10)
        fast.pack(fill="x", pady=(0, 8))
        fr = ttk.Frame(fast)
        fr.pack(fill="x")
        ttk.Label(fr, text="Data:").pack(side="left", padx=(0, 4))
        self.var_sched_date = tk.StringVar(value="")
        e_date = ttk.Entry(fr, textvariable=self.var_sched_date, width=12)
        e_date.pack(side="left", padx=(0, 14))
        ttk.Label(fr, text="Hora:").pack(side="left", padx=(0, 4))
        self.var_sched_hour = tk.IntVar(value=18)
        ttk.Spinbox(fr, from_=0, to=23, width=4, textvariable=self.var_sched_hour, format="%02.0f").pack(side="left", padx=(0, 14))
        ttk.Label(fr, text="Min:").pack(side="left", padx=(0, 4))
        self.var_sched_min = tk.IntVar(value=0)
        ttk.Spinbox(fr, from_=0, to=59, width=4, textvariable=self.var_sched_min,
                    values=(0, 15, 30, 45), format="%02.0f").pack(side="left", padx=(0, 14))
        self.var_sched_ai = tk.BooleanVar(value=True)
        ttk.Checkbutton(fr, text="Preencher título/descrição/hashtags automaticamente com a IA (quando a chave estiver salva)",
                        variable=self.var_sched_ai).pack(side="left", padx=(0, 14))
        ttk.Button(fr, text="Agendar selecionados neste horário", command=self.schedule_fast).pack(side="left")
        self.lbl_fast_hint = ttk.Label(fr, text="A célula âmbar no calendário é só uma sugestão — aqui você escolhe qualquer dia e hora.",
                                       foreground=self.CORES["cinza"])
        self.lbl_fast_hint.pack(side="left", padx=(18, 0))
        # data inicial: hoje
        today = datetime.now()
        self.var_sched_date.set(f"{today.year}-{today.month:02d}-{today.day:02d}")

        cols = ("#id", "Plataforma", "Vídeo", "Horário", "Status", "Link / Erro")
        self.post_tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="extended")
        widths = (50, 130, 320, 130, 110, 420)
        for c, w in zip(cols, widths):
            self.post_tree.heading(c, text=c)
            self.post_tree.column(c, width=w)
        self.post_tree.pack(fill="both", expand=True)

    def _build_calendar_widget(self, parent):
        """Monta o calendário mensal GRANDE (grade dias x horas de pico)."""
        nav = ttk.Frame(parent)
        nav.pack(fill="x", pady=(0, 6))
        ttk.Button(nav, text="◀ Mês anterior", command=self.cal_prev).pack(side="left")
        self.lbl_cal_month = ttk.Label(nav, text="", font=("Segoe UI", 13, "bold"))
        self.lbl_cal_month.pack(side="left", padx=18)
        ttk.Button(nav, text="Mês seguinte ▶", command=self.cal_next).pack(side="left")
        ttk.Label(nav, text="As células âmbar são apenas sugestões de horário de pico — você pode agendar em qualquer dia/hora.",
                  foreground=self.CORES["cinza"]).pack(side="right", padx=6)

        self._cal_month = datetime.now().replace(day=1)
        # altura fixa grande para o calendário ficar bem visível
        canvas = tk.Canvas(parent, height=350, bg=self.CORES["superficie"],
                           highlightthickness=1, highlightbackground=self.CORES["borda"], cursor="hand2")
        canvas.pack(fill="x")
        self.cal_canvas = canvas
        canvas.bind("<Configure>", lambda _e: self._draw_calendar())
        canvas.bind("<Button-1>", self.cal_click)
        canvas.bind("<Double-Button-1>", self.cal_click)
        canvas.tag_bind("cell", "<Button-1>", self.cal_click)
        canvas.tag_bind("cell", "<Double-Button-1>", self.cal_click)

    def cal_prev(self):
        self._cal_month = (self._cal_month - timedelta(days=1)).replace(day=1)
        self._draw_calendar()

    def cal_next(self):
        self._cal_month = (self._cal_month + timedelta(days=32)).replace(day=1)
        self._draw_calendar()

    def _peak_hours(self) -> list[int]:
        """Horários de pico dinâmicos (união da semana) para o calendário."""
        return prefs.all_peak_hours()

    def _peak_hours_for_day(self, day: int) -> list[int]:
        """Horários de pico para um dia específico do mês exibido."""
        year, month = self._cal_month.year, self._cal_month.month
        try:
            dt = datetime(year, month, day)
        except ValueError:
            return []
        return prefs.peak_hours_for(dt)

    def _draw_calendar(self):
        """Desenha a grade do mês: colunas = dias, linhas = horas (6h–23h).
        Células de horário de pico (por dia da semana) ficam destacadas."""
        canvas = self.cal_canvas
        try:
            canvas.delete("all")
        except tk.TclError:
            return
        w = max(canvas.winfo_width(), 1100)
        year, month = self._cal_month.year, self._cal_month.month
        first = datetime(year, month, 1)
        days_in_month = (self._cal_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        n_days = days_in_month.day

        conn = db.db()
        posts = conn.execute(
            "SELECT p.scheduled_at, p.platform FROM posts p WHERE p.status IN ('Agendado','Aguardando','Publicando')").fetchall()
        conn.close()
        day_marks = {}
        for r in posts:
            try:
                dt = datetime.fromisoformat(r[0])
            except Exception:
                continue
            if dt.year == year and dt.month == month:
                day_marks.setdefault(dt.day, 0)
                day_marks[dt.day] += 1

        hour_start, hour_end = 6, 23
        n_hours = hour_end - hour_start + 1
        # grades maiores para o calendário ficar legível
        row_h = max(12, 290 // n_hours)
        # preencher toda a largura útil (evita cortar os dias finais do mês)
        col_w = max(30, (w - 64) // n_days)
        x0, y0 = 64, 18
        C = self.CORES

        canvas.create_text(4, y0 - 4, text="Horas", font=("Segoe UI", 8, "bold"), fill=C["cinza"], anchor="w")

        # linha de dias com dia da semana
        dow_names = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
        today = datetime.now()
        for d in range(1, n_days + 1):
            cx = x0 + d * col_w + col_w // 2
            dow = dow_names[(first.weekday() + d - 1) % 7]
            color = C["texto"]
            if today.year == year and today.month == month and today.day == d:
                color = C["destaque"]
            canvas.create_text(cx, y0, text=f"{d}", font=("Segoe UI", 9, "bold"), fill=color)
            canvas.create_text(cx, y0 + 11, text=dow, font=("Segoe UI", 7), fill=C["cinza"])

        for d in range(1, n_days + 1):
            cx = x0 + d * col_w + col_w // 2
            peaks_d = set(self._peak_hours_for_day(d))
            for hi in range(n_hours):
                hour = hour_start + hi
                cy = y0 + 24 + hi * row_h
                if hour in peaks_d:
                    bg, tag = C["pico"], "cell cell-peak"
                else:
                    bg, tag = C["superficie"], "cell"
                cell_id = canvas.create_rectangle(x0 + (d - 1) * col_w + 1, cy, cx + col_w // 2, cy + row_h,
                                                  fill=bg, outline=C["borda"], width=1, tags=(tag,))
                canvas.tag_lower(cell_id)
                # rótulo da hora na primeira coluna
                if d == 1:
                    canvas.create_text(x0 - 4, cy + row_h // 2, text=f"{hour}h",
                                       font=("Segoe UI", 7), fill=C["cinza"], anchor="e")
                if day_marks.get(d, 0) > 0:
                    canvas.create_oval(cx - 4, cy + row_h // 2 - 3, cx + 4, cy + row_h // 2 + 3,
                                       fill=C["destaque"], outline="")
                    canvas.create_text(cx + 6, cy + row_h // 2, text=str(day_marks[d]),
                                       font=("Segoe UI", 6), fill=C["destaque"], anchor="w")

        # legenda do calendário
        ly = y0 + 24 + n_hours * row_h + 4
        canvas.create_rectangle(x0, ly, x0 + 14, ly + 10, fill=C["pico"], outline=C["borda"])
        canvas.create_text(x0 + 20, ly + 5, text="sugestão: horário de pico (escolha é livre)", anchor="w",
                           font=("Segoe UI", 8), fill=C["texto"])
        canvas.create_oval(x0 + 238, ly, x0 + 250, ly + 10, fill=C["destaque"], outline="")
        canvas.create_text(x0 + 256, ly + 5, text="dia com post(s) agendado(s)", anchor="w",
                           font=("Segoe UI", 8), fill=C["texto"])

        # coordenadas fixas para o clique (recomputadas no _draw_calendar)
        self._cal_geom = dict(x0=x0, y0=y0, row_h=row_h, col_w=col_w,
                              hour_start=hour_start, n_hours=n_hours, n_days=n_days)

    def cal_click(self, event):
        """Clique num dia/hora do calendário: agenda as publicações selecionadas na fila
        (ou os vídeos selecionados na aba Conteúdo) exatamente naquele horário.
        Qualquer dia/hora pode ser escolhido — as células âmbar são apenas sugestões de pico."""
        geom = getattr(self, "_cal_geom", None)
        if not geom:
            return
        x0, y0, row_h, col_w = geom["x0"], geom["y0"], geom["row_h"], geom["col_w"]
        day = int((event.x - x0) / col_w) + 1
        hour = geom["hour_start"] + int((event.y - y0 - 24) / row_h)
        if not (1 <= day <= geom["n_days"]) or not (0 <= hour <= 23):
            return  # clique fora da grade ou no cabeçalho
        # feedback visual: pisa a célula clicada por 400 ms
        try:
            canvas = self.cal_canvas
            cx0 = x0 + (day - 1) * col_w + 1
            cy0 = y0 + 24 + (hour - geom["hour_start"]) * row_h
            flash = canvas.create_rectangle(cx0, cy0, cx0 + col_w - 1, cy0 + row_h,
                                            fill=self.CORES["destaque"], outline="white", width=2, stipple="")
            canvas.tag_raise(flash)
            self.after(400, lambda: canvas.delete(flash) if canvas.winfo_exists() else None)
        except Exception:
            pass

        # 1) posts selecionados na fila
        ids = [self.post_tree.item(i)["values"][0] for i in self.post_tree.selection()]
        if not ids:
            # 2) vídeos selecionados na aba Conteúdo (cria posts automáticos)
            vids = [self.vid_tree.item(i)["values"][0] for i in self.vid_tree.selection()]
            if not vids:
                self._show_hint(f"Nada selecionado para agendar.\n\n"
                    "1. Na aba 'Fila e Calendário': selecione as publicações na lista e clique no dia/hora, ou\n"
                    "2. Na aba 'Conteúdo': selecione os vídeos e clique no dia/hora.\n\n"
                    f"Você clicou em {day:02d}/{self._cal_month.month:02d} às {hour}h.")
                return
            # criar posts (uma plataforma marcada por padrão ou as marcadas)
            plats = [p for p, v in self.var_plats.items() if v.get()] if self.var_plats else ["TikTok"]
            if not plats:
                plats = ["TikTok"]
            conn = db.db()
            new_ids = []
            for vid in vids:
                for p in plats:
                    cur = conn.execute("SELECT id FROM posts WHERE video_id=? AND platform=? AND status='Agendado'",
                                       (vid, p)).fetchone()
                    if cur:
                        new_ids.append(cur[0])
                    else:
                        conn.execute("INSERT INTO posts(video_id, platform, status, privacy) VALUES(?,?,?,?)",
                                     (vid, p, "Agendado", self.var_privacy.get()))
                        new_ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.commit()
            conn.close()
            ids = new_ids

        target = datetime(self._cal_month.year, self._cal_month.month, day, hour).isoformat(timespec="minutes")
        conn = db.db()
        conn.execute("UPDATE posts SET scheduled_at=?, status='Agendado' WHERE id IN (%s)"
                     % ",".join("?" for _ in ids), [target] + ids)
        conn.commit()
        conn.close()
        self.write_log(f"{len(ids)} publicação(ões) agendada(s) para {day:02d}/{self._cal_month.month:02d} às {hour}h.")
        self.refresh_all()

    def schedule_fast(self):
        """Agendamento rápido: data + hora + minuto digitados/escolhidos, com IA automática opcional."""
        raw = self.var_sched_date.get().strip()
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            self._show_hint(f"Data inválida. Use o formato AAAA-MM-DD.\nExemplo: {datetime.now().strftime('%Y-%m-%d')}")
            return
        hour = int(self.var_sched_hour.get())
        minute = int(self.var_sched_min.get())
        target = dt.replace(hour=hour, minute=minute).isoformat(timespec="minutes")

        ids = [self.post_tree.item(i)["values"][0] for i in self.post_tree.selection()]
        vids = [self.vid_tree.item(i)["values"][0] for i in self.vid_tree.selection()]
        if not ids and not vids:
            self._show_hint("Nada selecionado para agendar.\n\n"
                "Selecione as publicações na lista da aba 'Fila e Calendário'\n"
                "ou os vídeos na aba 'Conteúdo' antes de agendar.")
            return

        if not ids:
            plats = [p for p, v in self.var_plats.items() if v.get()] if self.var_plats else ["TikTok"]
            if not plats:
                plats = ["TikTok"]
            conn = db.db()
            for vid in vids:
                for p in plats:
                    if not conn.execute("SELECT id FROM posts WHERE video_id=? AND platform=? AND status='Agendado'",
                                        (vid, p)).fetchone():
                        conn.execute("INSERT INTO posts(video_id, platform, status, privacy) VALUES(?,?,?,?)",
                                     (vid, p, "Agendado", self.var_privacy.get()))
            conn.commit()
            conn.close()
            ids = [r[0] for r in db.db().execute(
                "SELECT id FROM posts WHERE video_id IN (%s) AND status='Agendado'"
                % ",".join("?" for _ in vids), vids).fetchall()]
            db.db().close()

        self.agendar_ids(ids, target, auto_ai=self.var_sched_ai.get())

    def agendar_ids(self, ids, target, auto_ai=False):
        """Agenda os posts com data/hora alvo e, se pedido, preenche metadados com a IA."""
        conn = db.db()
        conn.execute("UPDATE posts SET scheduled_at=?, status='Agendado' WHERE id IN (%s)"
                     % ",".join("?" for _ in ids), [target] + ids)
        conn.commit()

        # preencher título/descrição/hashtags automaticamente com a IA
        if auto_ai:
            key = (self.var_ai_key.get().strip() or prefs.load_setting("ia_key", "")).strip()
            if key:
                videos_sem_meta = []
                for pid in ids:
                    row = conn.execute("SELECT video_id FROM posts WHERE id=?", (pid,)).fetchone()
                    if not row:
                        continue
                    vid = row[0]
                    vrow = conn.execute("SELECT id, path, title, hashtags FROM videos WHERE id=?", (vid,)).fetchone()
                    if vrow and (not vrow[2] or not vrow[3]):
                        videos_sem_meta.append((vid, vrow[1]))
                if videos_sem_meta:
                    self.write_log(f"IA: preenchendo título/hashtags de {len(videos_sem_meta)} vídeo(s) em segundo plano...")
                    threading.Thread(target=self._preencher_ia, args=(videos_sem_meta,), daemon=True).start()
        conn.close()

        dt = datetime.fromisoformat(target)
        self.write_log(f"{len(ids)} publicação(ões) agendada(s) para {dt.strftime('%d/%m')} às {dt.strftime('%H')}h{dt.strftime('%M') + 'min' if dt.minute else ''}.")
        self.refresh_all()

    def _preencher_ia(self, videos):
        """Background: gera metadados com a IA e atualiza os vídeos."""
        import ia as _ia
        for vid, path in videos:
            try:
                key = (self.var_ai_key.get().strip() or prefs.load_setting("ia_key", "")).strip()
                if mv.has_ffmpeg() and path and os.path.exists(path):
                    frames = mv.extract_frames(path, 4)
                    meta = _ia.analyze_video(frames, Path(path).name, key)
                    if not meta:
                        meta = _ia.fallback_metadata(Path(path).name)
                else:
                    meta = _ia.fallback_metadata(path)
                conn = db.db()
                conn.execute("UPDATE videos SET title=?, hashtags=?, description=?, "
                             "ai_title=?, ai_caption=?, ai_hashtags=? WHERE id=?",
                             (meta.get("titulo", ""), ", ".join(meta.get("hashtags", [])),
                              meta.get("legenda", ""), meta.get("titulo", ""),
                              meta.get("legenda", ""), ", ".join(meta.get("hashtags", [])), vid))
                conn.commit()
                conn.close()
                self.write_log(f"IA: título/hashtags preenchidos para o vídeo {vid}.")
            except Exception as exc:
                self.write_log(f"IA: falha ao preencher vídeo {vid}: {exc}")

    def _show_hint(self, text: str):
        """Aviso não modal que se fecha sozinho após 5 segundos ou ao clicar."""
        try:
            if getattr(self, "_hint_win", None) and self._hint_win.winfo_exists():
                self._hint_win.destroy()
        except Exception:
            pass
        win = tk.Toplevel(self)
        win.title("AutoPost")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg=self.CORES["fundo"])
        ttk.Label(win, text=text, font=("Segoe UI", 9), wraplength=340,
                  background=self.CORES["fundo"], foreground=self.CORES["texto"]).pack(padx=16, pady=14)
        win.update_idletasks()
        win.geometry(f"{min(380, max(320, win.winfo_width() + 24))}x{min(300, max(150, win.winfo_height() + 16))}")
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")
        self._hint_win = win
        for ev in ("<Button-1>", "<Return>", "<Escape>"):
            win.bind(ev, lambda _e: win.destroy())
        self.after(5000, lambda: win.destroy() if win.winfo_exists() else None)

    # ------------------------------------------------- 5) configurações do app
    def open_settings(self):
        """Abre a Central de Configurações em uma janela própria (engrenagem no cabeçalho)."""
        if getattr(self, "_settings_win", None) and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        win = tk.Toplevel(self)
        win.title("Configurações do AutoPost")
        win.geometry("820x660")
        win.transient(self)
        self._settings_win = win

        outer = ttk.Frame(win)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0, bg=self.CORES["fundo"])
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda _e: canvas.itemconfigure("settingswin", width=canvas.winfo_width())
                    if canvas.winfo_width() > 0 else None)
        canvas.create_window((0, 0), window=inner, anchor="nw", tags=("settingswin",))
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        ttk.Label(inner, text="Central de configurações do AutoPost. As alterações são salvas automaticamente.",
                  foreground=self.CORES["cinza"], wraplength=700).pack(anchor="w", pady=(2, 12))

        # -- Aparência
        f1 = ttk.LabelFrame(inner, text="Aparência", padding=10)
        f1.pack(fill="x", pady=(0, 10))
        ttk.Label(f1, text="Tema do aplicativo").pack(anchor="w", pady=(0, 6))
        ff = ttk.Frame(f1)
        ff.pack(anchor="w", pady=(0, 6))
        ttk.Radiobutton(ff, text="Claro", variable=self.theme_dark, value=False,
                        command=self._on_theme_change).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(ff, text="Escuro", variable=self.theme_dark, value=True,
                        command=self._on_theme_change).pack(side="left")

        # -- Idioma
        f2 = ttk.LabelFrame(inner, text="Idioma da interface", padding=10)
        f2.pack(fill="x", pady=(0, 10))
        ttk.Label(f2, text=("Idioma atual: Português (Brasil). Outros idiomas estão reservados para uma próxima "
                            "versão — escolha aqui para já deixar salvo."),
                  foreground=self.CORES["cinza"], wraplength=800).pack(anchor="w", pady=(0, 6))
        f_id = ttk.Frame(f2)
        f_id.pack(anchor="w")
        self.combo_idioma = ttk.Combobox(f_id, textvariable=self.var_idioma, width=20,
                                         values=["pt-BR", "en-US", "es-ES"], state="readonly")
        self.combo_idioma.pack(side="left")
        ttk.Button(f_id, text="Aplicar idioma", command=self._apply_language).pack(side="left", padx=(8, 0))

        # -- IA
        f3 = ttk.LabelFrame(inner, text="Inteligência Artificial (Manus)", padding=10)
        f3.pack(fill="x", pady=(0, 10))
        ttk.Label(f3, text="Chave da Manus API (gratuita — crie em https://manus.im). A IA analisa os frames do vídeo "
                  "e gera título, hashtags e legendas sozinha.",
                  wraplength=850, foreground=self.CORES["cinza"]).pack(anchor="w", pady=(0, 6))
        f_ai = ttk.Frame(f3)
        f_ai.pack(fill="x")
        self._e_ai_key = ttk.Entry(f_ai, textvariable=self.var_ai_key, width=70, show="•")
        self._e_ai_key.pack(side="left")
        ttk.Button(f_ai, text="Testar chave", command=self.ai_test_key).pack(side="left", padx=6)
        ttk.Button(f_ai, text="Salvar chave", command=self._save_ai_key).pack(side="left", padx=4)

        # -- Privacidade
        f4 = ttk.LabelFrame(inner, text="Privacidade (TikTok)", padding=10)
        f4.pack(fill="x", pady=(0, 10))
        for valor, rotulo in [("PUBLIC_TO_EVERYONE", "Público para todos"),
                              ("MUTUAL_FOLLOW_FRIENDS", "Apenas amigos mútuos"),
                              ("SELF_ONLY", "Privado (só eu)")]:
            ttk.Radiobutton(f4, text=rotulo, variable=self.var_privacy, value=valor,
                            command=self._save_privacy).pack(anchor="w")

        # -- Preferências de preparo
        f5 = ttk.LabelFrame(inner, text="Preparo de vídeos", padding=10)
        f5.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(f5, text="Converter para o formato da plataforma (9:16) — padrão nos novos preparos",
                        variable=self.var_convert, command=self._save_prep).pack(anchor="w")
        ttk.Checkbutton(f5, text="Gravar legendas no vídeo — padrão nos novos preparos",
                        variable=self.var_subtitles, command=self._save_prep).pack(anchor="w")

        # -- Relatórios
        f6 = ttk.LabelFrame(inner, text="Relatórios", padding=10)
        f6.pack(fill="x", pady=(0, 10))
        ttk.Button(f6, text="📥 Exportar relatório de publicações (CSV)", command=self.export_report).pack(side="left", padx=4)
        ttk.Button(f6, text="Limpar histórico de eventos", command=self.clear_log).pack(side="left", padx=4)
        ttk.Label(f6, text=("O ffmpeg (conversor e gravador de legendas) já vem incluído na pasta 'tools' — "
                            "não é preciso baixar nada."),
                  foreground=self.CORES["cinza"]).pack(side="left", padx=(18, 0))

        ttk.Button(inner, text="Fechar", command=win.destroy).pack(pady=(14, 10), anchor="e", padx=20)

    def _on_theme_change(self):
        prefs.save_setting("tema", "escuro" if self.theme_dark.get() else "claro")
        self._apply_all_themes()

    def _save_ai_key(self):
        prefs.save_setting("ia_key", self.var_ai_key.get().strip())
        self.write_log("Chave da Manus API salva nas configurações.")
        messagebox.showinfo("AutoPost", "✅ Chave da IA salva. Ela será carregada automaticamente na próxima vez.")

    def _save_privacy(self):
        prefs.save_setting("privacidade", self.var_privacy.get())

    def _save_prep(self):
        prefs.save_setting("converter", "1" if self.var_convert.get() else "0")
        prefs.save_setting("gravar_legendas", "1" if self.var_subtitles.get() else "0")

    def _apply_language(self):
        lang = self.var_idioma.get()
        prefs.save_setting("idioma", lang)
        if lang == "pt-BR":
            messagebox.showinfo("AutoPost", "Idioma: Português (Brasil) — ativo.")
        else:
            messagebox.showinfo("AutoPost", f"Idioma '{lang}' selecionado — a tradução completa virá na próxima versão. "
                                  "A preferência já está salva.")

    def export_report(self):
        conn = db.db()
        rows = conn.execute(
            "SELECT p.id, p.platform, v.title, p.scheduled_at, p.status, p.link, p.error "
            "FROM posts p JOIN videos v ON v.id=p.video_id ORDER BY p.id").fetchall()
        conn.close()
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"autopost_relatorio_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("ID,Plataforma,Vídeo,Horário agendado,Status,Link,Erro\n")
            for r in rows:
                f.write(",".join(f'"{str(x).replace(chr(34), chr(34)+chr(34))}"' for x in r) + "\n")
        self.write_log(f"Relatório exportado: {Path(path).name}")
        messagebox.showinfo("AutoPost", f"✅ Relatório salvo em:\n{path}")

    def clear_log(self):
        if not messagebox.askyesno("AutoPost", "Apagar todo o histórico de eventos?"):
            return
        conn = db.db()
        conn.execute("DELETE FROM log")
        conn.commit()
        conn.close()
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.write_log("Histórico de eventos limpo.")

    # ------------------------------------------------- 6) execução
    def _build_tab_exec(self, tab):
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 8))
        self.btn_start = tk.Button(top, text="▶  INICIAR PUBLICAÇÃO", font=("Segoe UI", 13, "bold"),
                                   bg=self.CORES["destaque"], fg=self.CORES["btn_text"], activebackground="#a31c3c",
                                   relief="flat", padx=24, pady=8, command=self.start_now)
        self.btn_start.pack(side="left", padx=4)
        self.btn_pause = ttk.Button(top, text="⏸ Pausar", command=self.toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=4)
        ttk.Button(top, text="🛑 Parar tudo", command=self.stop_all).pack(side="left", padx=4)
        self.lbl_phase = ttk.Label(top, text="Aguardando…", foreground=self.CORES["cinza"])
        self.lbl_phase.pack(side="right", padx=10)

        cols = ("Plataforma", "Vídeo", "Status atual", "Atualizado às")
        self.prog_tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="extended")
        widths = (150, 400, 220, 140)
        for c, w in zip(cols, widths):
            self.prog_tree.heading(c, text=c)
            self.prog_tree.column(c, width=w)
        self.prog_tree.pack(fill="both", expand=True)

        log_frame = ttk.LabelFrame(tab, text="Histórico de eventos", padding=4)
        log_frame.pack(fill="x", pady=(6, 10), ipady=20)
        self.log_text = tk.Text(log_frame, height=7, state="disabled", wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill="x")

    # ================================================================ ações
    # ---------------------------- contas
    def connect_youtube(self):
        try:
            from .platforms.youtube import YouTubePlatform as _Y
            win = tk.Toplevel(self)
            win.title("Conectar YouTube")
            win.geometry("500x300")
            win.transient(self)
            ttk.Label(win, text="Para conectar sua conta do YouTube:",
                      font=("Segoe UI", 11, "bold")).pack(pady=(14, 6))
            ttk.Label(win, text="1) Acesse o Google Cloud e crie um projeto com a 'YouTube Data API v3' ativa.\n"
                      "2) Crie credenciais do tipo 'Cliente OAuth (dados do usuário)' com\n"
                      "   escopo https://www.googleapis.com/auth/youtube.upload.\n"
                      "3) Clique abaixo e selecione o seu arquivo client_secrets.json.\n"
                      "   (ele pode estar em qualquer pasta — ex.: Downloads, Desktop)\n"
                      "   Se ele já estiver na pasta do app, basta cancelar esta janela.",
                      justify="left").pack(pady=4)
            path_lbl = ttk.Label(win, text="", wraplength=460, foreground=self.CORES["cinza"])
            path_lbl.pack(pady=2)
            picked = {"path": None}

            def pick():
                p = filedialog.askopenfilename(
                    title="Selecionar client_secrets.json",
                    filetypes=[("Google OAuth", "*.json"), ("Todos", "*.*")])
                if p:
                    picked["path"] = p
                    path_lbl.config(text="Selecionado: " + p, foreground=self.CORES["sucesso"])
                    win.destroy()

            ttk.Button(win, text="Selecionar client_secrets.json", command=pick).pack(pady=8)
            win.update()
            self.wait_window(win)

            # caminho final: o que o usuário escolheu, ou o arquivo na pasta do app
            secrets = Path(picked["path"]) if picked["path"] else (Path(__file__).parent.parent / "client_secrets.json")
            if secrets.exists():
                # copiar para a pasta do app para o OAuth local funcionar depois
                dest = Path(__file__).parent.parent / "client_secrets.json"
                if secrets.resolve() != dest.resolve():
                    dest.write_bytes(secrets.read_bytes())
                yt = _Y(client_config_path=str(dest))
                try:
                    name = yt.connect({"client_config": str(dest)})
                    conn = db.db()
                    conn.execute("INSERT INTO accounts(platform, name, status, credentials) "
                                 "VALUES('YouTube', ?, ?, ?) "
                                 "ON CONFLICT(platform) DO UPDATE SET name=excluded.name, status=excluded.status, credentials=excluded.credentials",
                                 (name, "Conectada", str(dest)))
                    conn.commit()
                    conn.close()
                    self.refresh_all()
                    messagebox.showinfo("YouTube", f"{name} — conectada!")
                except Exception as e:
                    conn = db.db()
                    conn.execute("UPDATE accounts SET status=? WHERE platform=?",
                                 (f"Erro: {e}", "YouTube"))
                    conn.commit()
                    conn.close()
                    self.refresh_all()
                    messagebox.showerror("YouTube", f"Não foi possível concluir a conexão:\n{e}")
            else:
                messagebox.showinfo("YouTube",
                    "Nenhum client_secrets.json encontrado.\n\n"
                    "Salve o arquivo baixado do Google Cloud na pasta do app\n"
                    f"({dest}) e clique em 'Conectar YouTube' novamente.")
        except Exception as e:
            messagebox.showerror("YouTube", f"Erro: {e}")

    def connect_instagram(self):
        try:
            from .platforms.instagram import InstagramPlatform as _I
            win = tk.Toplevel(self)
            win.title("Conectar Instagram")
            win.geometry("500x300")
            win.transient(self)
            ttk.Label(win, text="Para conectar sua conta do Instagram:",
                      font=("Segoe UI", 11, "bold")).pack(pady=(14, 6))
            ttk.Label(win, text="1) Sua conta deve ser Empresarial/Creator.\n"
                      "2) Vincule-a a uma Página do Facebook que você administra.\n"
                      "3) Cole abaixo o Token de Acesso de Longa Duração da Página\n"
                      "   (gerado no Graph API Explorer do Meta for Developers):",
                      justify="left").pack(pady=4)
            e_token = ttk.Entry(win, width=60, show="•")
            e_token.pack(pady=6)

            def go():
                token = e_token.get().strip()
                if not token:
                    messagebox.showinfo("Instagram", "Cole o token antes de conectar.")
                    return
                try:
                    import requests as _rq
                    # descobrir o ig_user_id da Página pelo token
                    r = _rq.get("https://graph.facebook.com/v21.0/me/accounts",
                                params={"access_token": token}, timeout=30)
                    if r.status_code != 200:
                        raise RuntimeError(f"Token recusado: {r.json().get('error', {}).get('message', r.text)}")
                    pages = r.json().get("data", [])
                    page = pages[0] if pages else None
                    if not page:
                        raise RuntimeError("O token não tem acesso a nenhuma Página do Facebook.")
                    pt = page["access_token"]
                    ig = _rq.get(f"https://graph.facebook.com/v21.0/{page['id']}",
                                 params={"fields": "instagram_business_account", "access_token": pt}, timeout=30)
                    ig_id = ig.json().get("instagram_business_account", {}).get("id")
                    if not ig_id:
                        raise RuntimeError("Nenhuma conta Instagram vinculada a esta Página. "
                                           "Vincule a conta no app do Facebook/Instagram.")
                    ig = _I(access_token=token, ig_user_id=ig_id)
                    name = ig.connect({"access_token": token, "ig_user_id": ig_id})
                    conn = db.db()
                    conn.execute("INSERT INTO accounts(platform, name, status, credentials) "
                                 "VALUES('Instagram', ?, ?, ?) "
                                 "ON CONFLICT(platform) DO UPDATE SET name=excluded.name, status=excluded.status, credentials=excluded.credentials",
                                 (name, "Conectada", token))
                    conn.commit()
                    conn.close()
                    win.destroy()
                    self.refresh_all()
                    messagebox.showinfo("Instagram", f"✅ {name} — conectada!")
                except Exception as e:
                    messagebox.showerror("Instagram", f"❌ Falha na conexão:\n{e}")
            ttk.Button(win, text="🟢 Conectar", command=go).pack(pady=10)
        except Exception as e:
            messagebox.showerror("Instagram", f"Erro: {e}")

    def connect_tiktok(self):
        try:
            from .platforms.tiktok import TikTokPlatform as _T
            win = tk.Toplevel(self)
            win.title("Conectar TikTok (API oficial)")
            win.geometry("560x360")
            win.transient(self)
            ttk.Label(win, text="Login TikTok — autorização pela API oficial.",
                      font=("Segoe UI", 11, "bold")).pack(pady=(14, 6))
            ttk.Label(win, text="1) No portal TikTok for Developers, pegue sua 'Client key' e 'Client secret'.\n"
                      "2) Configure o redirect URI da área de trabalho como:\n"
                      "   http://127.0.0.1:8400/?state=autopost\n"
                      "3) Cole as credenciais abaixo e clique em '🟢 Conectar':",
                      justify="left").pack(pady=4)
            f1 = ttk.Frame(win)
            f1.pack(fill="x", padx=20, pady=4)
            ttk.Label(f1, text="Client key: ").pack(side="left")
            e_key = ttk.Entry(f1, width=45)
            e_key.pack(side="left")
            f2 = ttk.Frame(win)
            f2.pack(fill="x", padx=20, pady=4)
            ttk.Label(f2, text="Client secret: ").pack(side="left")
            e_secret = ttk.Entry(f2, width=45, show="•")
            e_secret.pack(side="left")
            f3 = ttk.Frame(win)
            f3.pack(fill="x", padx=20, pady=4)
            ttk.Label(f3, text="E-mail da conta TikTok (para conferir o login): ").pack(side="left")
            e_email = ttk.Entry(f3, width=45)
            e_email.pack(side="left")
            status_lbl = ttk.Label(win, text="", foreground=self.CORES["cinza"])
            status_lbl.pack(pady=4)

            def stop_server():
                srv = getattr(self, "_tt_srv", None)
                if srv:
                    try:
                        srv.shutdown()
                    except Exception:
                        pass

            def go():
                key = e_key.get().strip()
                secret = e_secret.get().strip()
                email = e_email.get().strip()
                if not key or not secret:
                    messagebox.showinfo("TikTok", "Preencha a client key e o client secret.")
                    return
                import webbrowser
                params = {
                    "client_key": key,
                    "response_type": "code",
                    "scope": "user.info.basic,video.upload",
                    "redirect_uri": "http://127.0.0.1:8400/?state=autopost",
                }
                url = "https://www.tiktok.com/auth/authorize/?" + urllib.parse.urlencode(params)

                import socket
                code_holder = {}

                class H(http.server.BaseHTTPRequestHandler):
                    def do_GET(self):  # noqa: N802
                        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        code_holder["code"] = qs.get("code", [""])[0]
                        self.send_response(200)
                        self.send_header("Content-type", "text/html; charset=utf-8")
                        self.end_headers()
                        msg = ("✅ Autorizado! Pode fechar esta aba e voltar ao AutoPost."
                               if code_holder["code"] else "❌ Autorização negada.")
                        self.wfile.write(f"<h2>{msg}</h2>".encode())

                    def log_message(self, *_a):  # noqa: N802
                        pass

                srv = http.server.HTTPServer(("127.0.0.1", 8400), H)
                self._tt_srv = srv

                def serve():
                    srv.handle_request()

                t = threading.Thread(target=serve, daemon=True)
                t.start()
                webbrowser.open(url)

                def check():
                    if code_holder.get("code"):
                        stop_server()
                        try:
                            tt = _T(client_key=key, client_secret=secret)
                            name = tt.connect({"code": code_holder["code"],
                                               "redirect_uri": "http://127.0.0.1:8400/?state=autopost"})
                            conn = db.db()
                            conn.execute(
                                "INSERT INTO accounts(platform, name, status, credentials) "
                                "VALUES('TikTok', ?, 'Conectada', ?) "
                                "ON CONFLICT(platform) DO UPDATE SET name=excluded.name, status='Conectada', credentials=excluded.credentials",
                                (name, key))
                            conn.commit()
                            conn.close()
                            win.destroy()
                            self.refresh_all()
                            messagebox.showinfo("TikTok", f"✅ {name} — conectada pela API oficial!")
                        except Exception as e:
                            status_lbl.config(text=f"❌ Erro: {e}", foreground="red")
                            stop_server()
                    else:
                        self.after(500, check)

                status_lbl.config(text="Aguardando autorização no navegador…")
                self.after(1000, check)

            ttk.Button(win, text="🟢 Conectar", command=go).pack(pady=10)
        except Exception as e:
            messagebox.showerror("TikTok", f"Erro: {e}")

    def disconnect_selected(self):
        sel = self.acc_tree.selection()
        if not sel:
            messagebox.showinfo("AutoPost", "Selecione a conta para desconectar.")
            return
        plat = self.acc_tree.item(sel[0])["values"][0]
        if not messagebox.askyesno("AutoPost", f"Desconectar a conta do {plat}?"):
            return
        conn = db.db()
        conn.execute("UPDATE accounts SET status='Desconectada' WHERE platform=?", (plat,))
        conn.commit()
        conn.close()
        self.write_log(f"Conta do {plat} desconectada.")
        self.refresh_all()

    # ---------------------------- conteúdo
    def add_videos(self):
        files = filedialog.askopenfilenames(
            title="Selecionar vídeos",
            filetypes=[("Vídeos", "*.mp4 *.mov *.avi *.mkv *.webm"), ("Todos", "*.*")])
        if not files:
            return
        self._insert_videos(files)

    def import_folder(self):
        folder = filedialog.askdirectory(title="Selecionar pasta com vídeos")
        if not folder:
            return
        found = scan_folder(Path(folder), ("mp4", "mov", "avi", "mkv", "webm"))
        if not found:
            messagebox.showinfo("AutoPost", "Nenhum vídeo encontrado nesta pasta.")
            return
        self._insert_videos([str(f) for f in found], folder_name=Path(folder).name)

    def _insert_videos(self, files, folder_name=None):
        conn = db.db()
        known = {r[0] for r in conn.execute("SELECT path FROM videos")}
        added = 0
        for path in files:
            path = str(Path(path))
            if path in known:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO videos(path, title, duration) VALUES(?,?,?)",
                (str(path), Path(path).stem, scan_duration_guess(Path(path))))
            known.add(str(path))
            added += 1
        conn.commit()
        origem = f" de {folder_name}" if folder_name else ""
        self.write_log(f"Importados {added} vídeo(s){origem}.")
        self.refresh_all()

    def _clear_thumb_cache(self):
        THUMB_CACHE.clear()

    def on_video_select(self, *_args):
        """Mostra a miniatura do vídeo selecionado (usa a prévia gerada pelo ffmpeg embutido)."""
        sel = self.vid_tree.selection()
        if not sel:
            return
        vid = self.vid_tree.item(sel[0])["values"][0]
        # capa estilo post (frame 16:9 + faixa com o título) — é a prévia principal
        cover_img = self._make_cover_img(vid)
        if cover_img:
            THUMB_CACHE[vid] = cover_img
        img = cover_img or THUMB_CACHE.get(vid)
        err_msg = None
        if img is None:
            conn = db.db()
            row = conn.execute("SELECT path, thumb_path, converted_path FROM videos WHERE id=?", (vid,)).fetchone()
            conn.close()
            if row is None:
                return
            thumb = None
            # 1) miniatura já gerada
            if row["thumb_path"] and Path(row["thumb_path"]).exists():
                thumb = row["thumb_path"]
            # 2) tentar extrair na hora com o ffmpeg embutido (original do vídeo)
            if not thumb and mv.has_ffmpeg() and row["path"] and Path(row["path"]).exists():
                try:
                    thumb = mv.extract_thumb(row["path"], str(mv._THUMB_DIR / f"thumb_{vid}.jpg"))
                except Exception as exc:
                    err_msg = str(exc)
                if thumb:
                    conn = db.db()
                    conn.execute("UPDATE videos SET thumb_path=? WHERE id=?", (thumb, vid))
                    conn.commit()
                    conn.close()
            # 3) fallback: versão já preparada (convertida) — geralmente menor e mais rápida
            if not thumb and mv.has_ffmpeg() and row.get("converted_path") and Path(row["converted_path"]).exists():
                try:
                    thumb = mv.extract_thumb(row["converted_path"], str(mv._THUMB_DIR / f"thumb_{vid}_conv.jpg"))
                except Exception as exc:
                    err_msg = err_msg or str(exc)
            if thumb and Path(thumb).exists():
                try:
                    from PIL import ImageTk, Image
                    im = Image.open(thumb).resize((260, 146), Image.LANCZOS)
                    img = ImageTk.PhotoImage(im, master=self)
                    THUMB_CACHE[vid] = img
                except ModuleNotFoundError:
                    # Pillow não instalada na máquina do usuário — mostrar imagem PPM
                    # convertida em memória com o Tk puro (funciona sem dependências)
                    try:
                        img = tk.PhotoImage(file=str(Path(thumb)), master=self)
                        if img.width() > 0:
                            img = img.zoom(1) if img.width() <= 260 else img.subsample(max(1, img.width() // 260))
                        THUMB_CACHE[vid] = img
                    except Exception as exc:
                        err_msg = err_msg or str(exc)
                except Exception as exc:
                    err_msg = err_msg or str(exc)
        if img:
            self.lbl_thumb.configure(image=img, text="")
            self.lbl_thumb.image = img
            self.lbl_cover_hint.config(text="Assim o post vai aparecer: frame do vídeo com o título na faixa")
        else:
            falta_pillow = "No module named" in (err_msg or "") and "PIL" in (err_msg or "")
            dica = ("\n\nA prévia precisa da biblioteca Pillow, que não está instalada.\n"
                    "Rode no PowerShell:  pip install Pillow\n"
                    "(ou py -3 -m pip install Pillow)") if falta_pillow else ""
            detalhe = f"\n\nDetalhe: {err_msg[:120]}" if err_msg and not falta_pillow else ""
            self.lbl_cover_hint.config(text="")
            self.lbl_thumb.configure(image="", text=f"Prévia indisponível.{dica}{detalhe}" if (dica or detalhe)
                                     else "Prévia indisponível.\nVerifique se o arquivo do vídeo existe\ne clique em 'Preparar vídeos'.")

    def _make_cover_img(self, vid, width=300):
        """Cria a PhotoImage da capa estilo post a partir de cover_path (gerado em background)."""
        try:
            conn = db.db()
            row = conn.execute("SELECT path, cover_path, thumb_path, title FROM videos WHERE id=?", (vid,)).fetchone()
            conn.close()
            if row is None:
                return None
            # regenerar a capa se o título mudou
            need_new = not row["cover_path"] or not Path(row["cover_path"] or "").exists()
            if not need_new and row["title"]:
                import hashlib as _h
                sig = _h.md5((row["title"] + "|").encode()).hexdigest()[:8]
                need_new = sig not in (Path(row["cover_path"]).stem[-8:] if row["cover_path"] else "")
            if need_new and row["title"] and row["path"] and Path(row["path"] or "").exists() and mv.has_ffmpeg():
                out = str(mv._THUMB_DIR / f"cover_{vid}.jpg")
                cover = mv.make_cover(row["path"], row["title"], out)
                if cover:
                    try:
                        db.db().execute("UPDATE videos SET cover_path=? WHERE id=?", (cover, vid))
                        db.db().commit()
                    except Exception:
                        pass
            src = None
            if row["cover_path"] and Path(row["cover_path"]).exists():
                src = row["cover_path"]
            elif row["thumb_path"] and Path(row["thumb_path"]).exists():
                src = row["thumb_path"]
            if not src:
                return None
            try:
                from PIL import ImageTk, Image
            except ModuleNotFoundError:
                # Pillow não instalada na máquina do usuário — converter o JPG
                # para PPM (formato nativo do Tkinter) com o ffmpeg embutido
                ppm = str(mv._THUMB_DIR / f"preview_{vid}.ppm")
                try:
                    import subprocess as _sp
                    _sp.run([mv._FFMPEG_PATH, "-y", "-i", src, "-vf",
                             f"scale={width}:-1", "-frames:v", "1", ppm],
                            check=True, capture_output=True, timeout=60)
                except Exception:
                    return None
                if not Path(ppm).exists():
                    return None
                return tk.PhotoImage(file=ppm, master=self)
            im = Image.open(src)
            h = int(im.height * width / im.width)
            im = im.resize((width, h), Image.LANCZOS)
            # master=self evita TclError "image doesn't exist" em janelas Toplevel/múltiplas
            return ImageTk.PhotoImage(im, master=self)
        except ModuleNotFoundError:
            return None
        except Exception as exc:  # log para diagnosticar capa ausente
            import traceback as _tb
            _tb.print_exc()
            print("[cover] erro para vid=%r: %s" % (vid, exc)[:300])
            return None

    def edit_selected(self):
        sel = self.vid_tree.selection()
        if not sel:
            messagebox.showinfo("AutoPost", "Selecione um vídeo para editar.")
            return
        vid = self.vid_tree.item(sel[0])["values"][0]
        conn = db.db()
        row = conn.execute("SELECT title, description, hashtags FROM videos WHERE id=?", (vid,)).fetchone()
        conn.close()

        win = tk.Toplevel(self)
        win.title("Editar metadados")
        win.geometry("540x420")
        win.transient(self)

        ttk.Label(win, text="Título").pack(pady=(10, 2), anchor="w", padx=20)
        e_title = ttk.Entry(win, width=70); e_title.pack(padx=20); e_title.insert(0, row["title"] or "")
        ttk.Label(win, text="Descrição / legenda").pack(pady=(10, 2), anchor="w", padx=20)
        t_desc = tk.Text(win, height=6, width=60); t_desc.pack(padx=20)
        t_desc.insert("1.0", row["description"] or "")
        ttk.Label(win, text="Hashtags (separadas por vírgula ou #)").pack(pady=(10, 2), anchor="w", padx=20)
        e_tags = ttk.Entry(win, width=70); e_tags.pack(padx=20); e_tags.insert(0, row["hashtags"] or "")

        def save():
            conn = db.db()
            conn.execute("UPDATE videos SET title=?, description=?, hashtags=? WHERE id=?",
                         (e_title.get(), t_desc.get("1.0", "end-1c"), e_tags.get(), vid))
            conn.commit()
            win.destroy()
            self.write_log(f"Metadados do vídeo {vid} atualizados.")
            self.refresh_all()

        ttk.Button(win, text="💾 Salvar", command=save).pack(pady=14)

    def _check_ffmpeg(self):
        self.lbl_ffmpeg.configure(text=("✅ ffmpeg encontrado (embutido na pasta tools/)" if mv.has_ffmpeg()
                                        else "⚠️ ffmpeg não encontrado em tools/ — conversão indisponível"))

    def prepare_selected(self):
        """Converte os vídeos selecionados para o formato e grava legendas."""
        sel = self.vid_tree.selection()
        if not sel:
            messagebox.showinfo("AutoPost", "Selecione os vídeos que quer preparar.")
            return
        if not mv.has_ffmpeg():
            messagebox.showerror("ffmpeg ausente",
                                 "O conversor precisa do ffmpeg.\n\n"
                                 "Copie ffmpeg.exe e ffprobe.exe para a pasta tools/ "
                                 "ao lado do main.py e reinicie o AutoPost.")
            return
        plats = [p for p, v in self.var_plats.items() if v.get()]
        if not plats:
            messagebox.showinfo("AutoPost", "Selecione pelo menos uma plataforma na aba 'Configurar Postagem'.")
            return

        burn = self.var_subtitles.get()
        convert = self.var_convert.get()

        win = tk.Toplevel(self)
        win.title("Preparando vídeos…")
        win.geometry("460x140")
        win.transient(self)
        ttk.Label(win, text="Preparando vídeos… não feche esta janela.", font=("Segoe UI", 10, "bold")).pack(pady=10)
        lbl = ttk.Label(win, text="")
        lbl.pack(pady=4)
        bar = ttk.Progressbar(win, mode="determinate", length=400)
        bar.pack(pady=6)
        self._prepare_bar = bar
        self._prepare_lbl = lbl

        def worker():
            n = len(sel)
            ok, err = 0, 0
            for i, item in enumerate(sel):
                vid = self.vid_tree.item(item)["values"][0]
                conn = db.db()
                row = conn.execute("SELECT path, title, duration FROM videos WHERE id=?", (vid,)).fetchone()
                conn.close()
                if row is None:
                    continue
                self.after(0, lambda v=Path(row["path"]).name, p=i, t=n: (
                    self._prepare_lbl.configure(text=f"({p+1}/{t}) {v[:50]}…"),
                    self._prepare_bar.configure(value=int(100 * p / max(t, 1)))))
                try:
                    out_dir = mv._CONV_DIR / str(vid)
                    out = str(out_dir / f"{Path(row['path']).stem}_autopost.mp4")
                    if convert:
                        mv.convert_video(row["path"], out, plats[0],
                                         callback=lambda p, lbl=self._prepare_lbl, b=self._prepare_bar,
                                         t=n, i=i: self.after(0, lambda pp=p, ii=i: (
                                             lbl.configure(text=f"({ii+1}/{t}) convertendo… {pp}%"),
                                             b.configure(value=int(100 * (ii + pp / 100) / t)))))
                    if burn:
                        d = mv.probe(row["path"])
                        srt = str(out_dir / "legendas.srt")
                        legendas = self._fetch_ai_legendas(vid) or f"{row['title']}"
                        mv.make_srt(legendas, srt, total_duration=d.get("duration"))
                        with_subs = str(out_dir / f"{Path(row['path']).stem}_legendado.mp4")
                        mv.burn_subtitles(out, srt, with_subs, plats[0])
                        out = with_subs
                    conn = db.db()
                    conn.execute("UPDATE videos SET converted_path=? WHERE id=?", (out, vid))
                    conn.commit()
                    ok += 1
                except RuntimeError as e:
                    err += 1
                    self.write_log(f"Erro ao preparar vídeo {vid}: {e}")

            self.after(0, lambda: (
                self._prepare_bar.configure(value=100),
                self._prepare_lbl.configure(text=f"Pronto: {ok} vídeo(s) preparado(s), {err} erro(s)"),
                win.after(1500, win.destroy),
                self.refresh_all()))

        threading.Thread(target=worker, daemon=True).start()

    def _fetch_ai_legendas(self, vid: int) -> str | None:
        """Busca as legendas geradas pela IA para o vídeo (campo ai_caption), se existirem."""
        conn = db.db()
        row = conn.execute("SELECT ai_caption FROM videos WHERE id=?", (vid,)).fetchone()
        conn.close()
        return row["ai_caption"] if row and row["ai_caption"] else None

    def send_to_config(self):
        sel = self.vid_tree.selection()
        if not sel:
            messagebox.showinfo("AutoPost", "Selecione os vídeos que quer publicar.")
            return
        self.tabs.select(2)
        ids = [self.vid_tree.item(i)["values"][0] for i in sel]
        self._last_selected = ids
        self.write_log(f"{len(ids)} vídeo(s) selecionado(s) — configure a postagem na aba ao lado.")

    def remove_selected(self):
        ids = [self.vid_tree.item(i)["values"][0] for i in self.vid_tree.selection()]
        if not ids:
            return
        conn = db.db()
        for vid in ids:
            conn.execute("DELETE FROM posts WHERE video_id=?", (vid,))
            conn.execute("DELETE FROM videos WHERE id=?", (vid,))
        conn.commit()
        for vid in ids:
            THUMB_CACHE.pop(vid, None)
        self.write_log(f"{len(ids)} vídeo(s) removido(s).")
        self.refresh_all()

    # ---------------------------- IA
    def ai_generate(self):
        sel = self.vid_tree.selection()
        if not sel:
            messagebox.showinfo("AutoPost", "Selecione os vídeos que quer analisar.")
            return
        api_key = self.var_ai_key.get().strip() or prefs.load_setting("ia_key", "")
        if not api_key:
            messagebox.showinfo("IA indisponível",
                                "Para gerar título/hashtags com IA, cole sua chave da Manus API "
                                "na janela de Configurações (engrenagem no canto superior direito).\n\n"
                                "Sem a chave, o app usa o nome do arquivo como título.")
            return

        win = tk.Toplevel(self)
        win.title("Analisando vídeos com IA…")
        win.geometry("440x120")
        win.transient(self)
        ttk.Label(win, text="A IA está analisando os frames dos vídeos…").pack(pady=12)
        bar = ttk.Progressbar(win, mode="indeterminate", length=380)
        bar.pack(pady=6)
        bar.start()

        def worker():
            results = []
            for item in sel:
                vid = self.vid_tree.item(item)["values"][0]
                conn = db.db()
                row = conn.execute("SELECT path FROM videos WHERE id=?", (vid,)).fetchone()
                conn.close()
                if row is None:
                    continue
                tmp = Path(mv._THUMB_DIR) / f"ai_{vid}"
                frames = mv.extract_frames(row["path"], str(tmp), count=4)
                meta = ai.analyze_video(frames, Path(row["path"]).name, api_key) or ai.fallback_metadata(Path(row["path"]).name)
                results.append((vid, meta))

            conn = db.db()
            for vid, meta in results:
                conn.execute("UPDATE videos SET ai_title=?, ai_caption=?, ai_hashtags=? WHERE id=?",
                             (meta.get("titulo"), meta.get("legenda"),
                              ", ".join(meta.get("hashtags") or []), vid))
                if meta.get("titulo"):
                    conn.execute("UPDATE videos SET title=? WHERE id=?", (meta.get("titulo")[:100], vid))
                if meta.get("hashtags"):
                    conn.execute("UPDATE videos SET hashtags=? WHERE id=?",
                                 (", ".join(meta.get("hashtags") or []), vid))
                if meta.get("legenda"):
                    conn.execute("UPDATE videos SET description=? WHERE id=?", (meta.get("legenda"), vid))
            conn.commit()
            self.after(0, lambda: (
                win.destroy(),
                messagebox.showinfo("IA concluída",
                                    f"{len(results)} vídeo(s) analisado(s) — título, legenda e hashtags atualizados."),
                self.refresh_all()))

        threading.Thread(target=worker, daemon=True).start()

    def ai_test_key(self):
        key = self.var_ai_key.get().strip()
        if not key:
            messagebox.showinfo("IA", "Cole a chave antes de testar.")
            return
        try:
            import urllib.request, json
            req = urllib.request.Request("https://api.manus.im/v2/task.list", headers={"x-manus-api-key": key})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            ok = "error" not in data or resp.status == 200
            messagebox.showinfo("IA", "✅ Chave válida — IA habilitada." if ok else "❌ Chave inválida ou sem acesso.")
        except Exception as e:
            messagebox.showerror("IA", f"❌ Erro ao validar: {e}")

    # ---------------------------- configuração
    def apply_config(self):
        vids = getattr(self, "_last_selected", None)
        if not vids:
            messagebox.showinfo("AutoPost",
                                "Primeiro selecione os vídeos na aba 'Conteúdo' e clique em '➕ Incluir na configuração'.")
            return
        plats = [p for p, v in self.var_plats.items() if v.get()]
        if not plats:
            messagebox.showinfo("AutoPost", "Selecione pelo menos uma plataforma.")
            return

        caption = self.e_caption.get()
        hashtags = self.e_hashtags.get()
        privacy = self.var_privacy.get()

        when = self.var_when.get()
        if when == "later":
            start = datetime.now()
        else:
            start = datetime.now()

        conn = db.db()
        count = 0
        for i, vid in enumerate(vids):
            row = conn.execute("SELECT title FROM videos WHERE id=?", (vid,)).fetchone()
            title = (row["title"] or Path(conn.execute(
                "SELECT path FROM videos WHERE id=?", (vid,)).fetchone()[0]).stem)
            final_caption = caption.replace("{nome_video}", title)
            for p in plats:
                if when == "later":
                    # agendado: próximo horário de pico dinâmico a partir de agora
                    when_at = prefs.next_peak_slot(datetime.now() + timedelta(minutes=count))
                else:
                    when_at = datetime.now()
                conn.execute(
                    "INSERT INTO posts(video_id, platform, scheduled_at, privacy) VALUES(?,?,?,?)",
                    (vid, p, when_at.isoformat(timespec="minutes"), privacy))
                count += 1
            conn.execute("UPDATE videos SET title=? WHERE id=?", (title, vid))
        conn.commit()

        n = len(vids) * len(plats)
        self.write_log(f"Criadas {n} publicações para {len(vids)} vídeo(s) em {len(plats)} plataforma(s).")
        if when == "now":
            conn = db.db()
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM posts WHERE video_id IN (%s) AND status='Agendado' "
                "ORDER BY id DESC LIMIT ?" % ",".join("?" * len(vids)),
                list(vids) + [n]).fetchall()]
            conn.close()
            self.scheduler.enqueue_immediate(ids)
            self.tabs.select(4)
        else:
            self.tabs.select(3)
        self.refresh_all()

    # ---------------------------- fila
    def refresh_queue(self):
        for x in self.post_tree.get_children():
            self.post_tree.delete(x)
        conn = db.db()
        rows = conn.execute(
            "SELECT p.id, p.platform, v.title, COALESCE(p.scheduled_at,'—'), "
            "p.status, COALESCE(p.link, p.error, '') FROM posts p "
            "JOIN videos v ON v.id=p.video_id ORDER BY p.id DESC").fetchall()
        for pid, plat, title, when, status, extra in rows:
            self.post_tree.insert("", "end", values=(pid, plat, title, when, status, extra))
        conn.close()
        self._draw_calendar()

    def push_now(self):
        ids = [self.post_tree.item(i)["values"][0] for i in self.post_tree.selection()]
        if not ids:
            messagebox.showinfo("AutoPost", "Selecione as publicações para enviar agora.")
            return
        self.scheduler.enqueue_immediate(ids)
        self.write_log(f"{len(ids)} publicações enviadas para a fila de execução imediata.")
        self.tabs.select(4)
        self.refresh_all()

    def cancel_selected(self):
        ids = [self.post_tree.item(i)["values"][0] for i in self.post_tree.selection()]
        if not ids:
            return
        self.scheduler.cancel_posts(ids)
        self.write_log(f"{len(ids)} publicações canceladas.")
        self.refresh_all()

    # ---------------------------- execução
    def start_now(self):
        conn = db.db()
        waiting = conn.execute(
            "SELECT id FROM posts WHERE status IN ('Aguardando','Agendado') ORDER BY scheduled_at").fetchall()
        conn.close()
        ids = [r[0] for r in waiting]
        if not ids:
            messagebox.showinfo("AutoPost", "Não há publicações na fila. "
                                "Selecione vídeos em 'Conteúdo', configure em 'Configurar Postagem' e clique em "
                                "'Adicionar à fila com esta configuração'.")
            return
        self.scheduler.enqueue_immediate(ids)
        self.btn_start.config(state="disabled")
        self.btn_pause.config(state="normal")
        self.lbl_phase.config(text="▶ Publicando…", foreground=self.CORES["destaque"])
        self.write_log(f"Execução iniciada com {len(ids)} publicações.")

    def toggle_pause(self):
        self.scheduler.toggle_pause()
        if self.scheduler._pausing.is_set():
            self.btn_pause.config(text="⏸ Pausar")
            self.lbl_phase.config(text="▶ Publicando…", foreground=self.CORES["destaque"])
        else:
            self.btn_pause.config(text="▶ Retomar")
            self.lbl_phase.config(text="⏸ Pausado", foreground=self.CORES["cinza"])
        self.write_log("Execução pausada." if not self.scheduler._pausing.is_set() else "Execução retomada.")

    def stop_all(self):
        self.scheduler.stop()
        self.btn_start.config(state="normal")
        self.btn_pause.config(state="disabled", text="⏸ Pausar")
        self.lbl_phase.config(text="⏹ Parado", foreground=self.CORES["cinza"])
        self.write_log("Execução parada pelo usuário.")

    def on_progress(self, *args):
        """Atualiza o painel de monitoramento em tempo real."""
        if len(args) == 4:
            post_id, platform, status, _extra = args[0], args[1], args[2], args[3]
            vid_title = ""
        else:
            post_id, video_id, platform, status, _extra = args
            conn = db.db()
            row = conn.execute("SELECT title FROM videos WHERE id=?", (video_id,)).fetchone()
            conn.close()
            vid_title = row["title"] if row else ""
        self.after(0, self._refresh_prog_row, post_id, platform, vid_title, status)

    def _refresh_prog_row(self, post_id, platform, vid_title, status):
        found = False
        for x in self.prog_tree.get_children():
            if self.prog_tree.item(x)["values"][0] == platform and self.prog_tree.item(x)["values"][1] == vid_title:
                self.prog_tree.item(x, values=(platform, vid_title, status,
                                               datetime.now().strftime("%H:%M:%S")))
                found = True
                break
        if not found:
            self.prog_tree.insert("", "end",
                                  values=(platform, vid_title, status,
                                          datetime.now().strftime("%H:%M:%S")))
        self.refresh_stats()

    # ================================================================ util
    def write_log(self, msg: str):
        try:
            conn = db.db()
            conn.execute("INSERT INTO log(message) VALUES(?)", (msg,))
            conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            self.log_text.see("end")
            # limitar o visor para não pesar
            if int(self.log_text.index("end-1c").split(".")[0]) > 2000:
                self.log_text.delete("1.0", "500.0")
            self.log_text.config(state="disabled")
        except Exception:
            pass

    def refresh_all(self):
        try:
            self.refresh_accounts()
            self.refresh_videos()
            self.refresh_queue()
            self.refresh_stats()
        except Exception as e:
            self.write_log(f"Erro ao atualizar tela: {e}")

    def refresh_accounts(self):
        for x in self.acc_tree.get_children():
            self.acc_tree.delete(x)
        conn = db.db()
        for plat in ["YouTube", "Instagram", "TikTok"]:
            row = conn.execute(
                "SELECT name, status FROM accounts WHERE platform=? ORDER BY updated_at DESC LIMIT 1",
                (plat,)).fetchone()
            name = f"{row['name']} ({row['status']})" if row else "—"
            status = row["status"] if row else "Desconectada"
            self.acc_tree.insert("", "end", values=(plat, name, status))
        conn.close()

    def refresh_videos(self):
        # preservar a seleção da lista ao redesenhar
        kept = {self.vid_tree.item(i)["values"][0] for i in self.vid_tree.selection() if self.vid_tree.item(i)["values"]}
        for x in self.vid_tree.get_children():
            self.vid_tree.delete(x)
        conn = db.db()
        for vid, path, title, tags, added, conv in conn.execute(
                "SELECT id, path, title, hashtags, added_at, converted_path FROM videos ORDER BY id DESC"):
            n_conv = 0
            conn2 = db.db()
            row = conn2.execute("SELECT COUNT(*) FROM posts WHERE video_id=?", (vid,)).fetchone()
            n_conv = row[0] if row else 0
            conn2.close()
            if conv and Path(conv).exists():
                plats_vid = sorted({r[0] for r in conn.execute(
                    "SELECT platform FROM posts WHERE video_id=?", (vid,))})
                label = ", ".join(mv.PLATFORM_PROFILES[p]["label"].split(" (")[0] for p in plats_vid) if plats_vid else ""
                prep = f"✅ Pronto ({label})" if label else "✅ Pronto"
            else:
                prep = "—"
            self.vid_tree.insert("", "end", values=(
                vid, Path(path).name, title or Path(path).stem, tags or "", added, prep))
            if kept and vid in kept:
                self.vid_tree.selection_add(self.vid_tree.get_children()[-1])
        conn.close()

        # gerar miniaturas em segundo plano para os vídeos que ainda não têm
        if not getattr(self, "_thumbs_running", False):
            self._thumbs_running = True
            threading.Thread(target=self._build_thumbs, daemon=True).start()

    def _build_thumbs(self):
        """Gera miniaturas de todos os vídeos que ainda não têm (ffmpeg embutido)."""
        try:
            if not mv.has_ffmpeg():
                return
            conn = db.db()
            todo = conn.execute(
                "SELECT id, path FROM videos WHERE (thumb_path IS NULL OR thumb_path='') ORDER BY id").fetchall()
            conn.close()
            for vid, path in todo:
                out = str(mv._THUMB_DIR / f"thumb_{vid}.jpg")
                thumb = mv.extract_thumb(path, out)
                if thumb:
                    db.db().execute("UPDATE videos SET thumb_path=? WHERE id=?", (thumb, vid))
                    db.db().commit()
            # gerar capas estilo post (frame + faixa com o título) para os vídeos com metadados
            conn = db.db()
            covers_todo = conn.execute(
                "SELECT id, path, title FROM videos WHERE (cover_path IS NULL OR cover_path='') AND title != ''").fetchall()
            conn.close()
            for vid, path, title in covers_todo:
                out = str(mv._THUMB_DIR / f"cover_{vid}.jpg")
                cover = mv.make_cover(path, title, out)
                if cover:
                    db.db().execute("UPDATE videos SET cover_path=? WHERE id=?", (cover, vid))
                    db.db().commit()
        except Exception:
            pass
        finally:
            self._thumbs_running = False
            # atualizar a prévia se houver seleção aberta (protegido: esta
            # rotina roda em thread de fundo, fora do loop principal do Tk)
            try:
                sel = self.vid_tree.selection() if hasattr(self, "vid_tree") else None
            except Exception:
                sel = None
            if sel:
                try:
                    self.after(0, self.on_video_select)
                except Exception:
                    pass

    def refresh_stats(self):
        conn = db.db()
        total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(DISTINCT video_id) FROM posts WHERE status IN ('Agendado','Aguardando')").fetchone()[0]
        scheduled = conn.execute("SELECT COUNT(*) FROM posts WHERE status='Agendado'").fetchone()[0]
        publishing = conn.execute("SELECT COUNT(*) FROM posts WHERE status='Publicando'").fetchone()[0]
        published = conn.execute("SELECT COUNT(*) FROM posts WHERE status='Publicado'").fetchone()[0]
        errors = conn.execute("SELECT COUNT(*) FROM posts WHERE status='Erro'").fetchone()[0]
        conn.close()
        for k, v in [("total", total), ("pending", pending), ("scheduled", scheduled),
                     ("publishing", publishing), ("published", published), ("errors", errors)]:
            self.stats[k].config(text=str(v))

    def destroy(self):
        self.scheduler.stop()
        db.close_connection()
        super().destroy()


if __name__ == "__main__":
    db.close_connection()
    app = AutoPost()
    app.mainloop()
