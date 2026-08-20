"""
AutoPost V7.4 — Temas claro e escuro (tema próprio registrado).

Causa do problema anterior: no Windows o ttk aplica o tema nativo ("vista") e
o style.theme_use("clam") + style.configure não sobrescreve todos os elementos
(Treeview.Heading, botões etc. ficam com a cor padrão do sistema = cinza lavada).
Solução: registrar um TEMA PRÓPRIO via style.theme_create(), herdando do "clam",
com as cores definidas para todos os elementos — assim o Windows renderiza o app
com a paleta da marca em vez do cinza padrão.
"""

import tkinter as tk
from tkinter import ttk

THEME_LIGHT = {
    # marca: fundo off-white quente, tons suaves e pastel, destaque terracota suave
    "fundo": "#faf8f5",
    "aba": "#ece9e4",       # abas inativas: bege neutro suave
    "destaque": "#c05a6d",  # terracota rosado suave — marca sem estourar
    "sucesso": "#4c8c5f",
    "texto": "#3d3a36",
    "cinza": "#8a8680",
    "pico": "#d9a441",      # âmbar suave, não saturado
    "superficie": "#ffffff",
    "borda": "#d8d3cc",
    "texto2": "#6f6b64",
    "btn_text": "#ffffff",
    "tree_head": "#efece7",
    "btn": "#5b6372",       # botão azul-acinzentado suave para contraste claro
}

THEME_DARK = {
    # marca: cinza-quente escuro, tons suaves, destaque terracota suave legível
    "fundo": "#21201e",
    "aba": "#45423e",       # abas inativas mais claras que o fundo, sem estourar
    "destaque": "#d17985",  # terracota rosado suave legível no escuro
    "sucesso": "#7dbb8c",
    "texto": "#efece7",
    "cinza": "#b8b3ac",
    "pico": "#e0b15f",
    "superficie": "#2d2b28",
    "borda": "#4f4c48",
    "texto2": "#d4d0c9",
    "btn_text": "#f6f4f0",
    "tree_head": "#383633",
    "btn": "#6c7588",
}


THEME_NAME_LIGHT = "autopost_claro"
THEME_NAME_DARK = "autopost_escuro"


def _register_theme(style, dark: bool) -> str:
    """Registra o tema próprio herdando do "clam" e o ativa.
    No Windows o tema nativo (vista) ignora style.configure puro — registrar
    um tema novo garante que TODAS as cores sejam respeitadas."""
    theme = THEME_DARK if dark else THEME_LIGHT
    name = THEME_NAME_DARK if dark else THEME_NAME_LIGHT
    try:
        style.theme_create(name, parent="clam", settings={
            ".": {"configure": {
                "background": theme["fundo"], "foreground": theme["texto"],
                "fieldbackground": theme["superficie"],
            }},
            "TFrame": {"configure": {"background": theme["fundo"]}},
            "TLabel": {"configure": {"background": theme["fundo"],
                                     "foreground": theme["texto"]}},
            "TButton": {"configure": {
                "background": theme["btn"], "foreground": theme["btn_text"],
                "borderwidth": 1, "bordercolor": theme["borda"],
                "relief": "flat", "padding": [10, 5]}},
            "TButton": {"map": {
                "background": [("active", "#262a38" if dark else "#6b7180"),
                               ("pressed", "#1c1f2c" if dark else "#575c6a")]},
             "configure": {
                "background": theme["btn"], "foreground": theme["btn_text"],
                "borderwidth": 1, "bordercolor": theme["borda"]}},
            "TLabelFrame": {"configure": {
                "background": theme["superficie"], "foreground": theme["texto"],
                "borderwidth": 1, "bordercolor": theme["borda"]}},
            "TLabelFrame.Label": {"configure": {
                "background": theme["superficie"], "foreground": theme["texto"]}},
            "TNotebook": {"configure": {
                "background": theme["fundo"], "tabmargins": [4, 4, 4, 0]}},
            "TNotebook.Tab": {"configure": {
                "background": theme["aba"], "foreground": theme["texto"],
                "padding": [12, 6], "borderwidth": 1}},
            "TNotebook.Tab": {"map": {
                "background": [("selected", theme["destaque"]),
                               ("!selected", theme["aba"])]},
             "configure": {
                "background": theme["aba"], "foreground": theme["texto"]}},
            "Treeview": {"configure": {
                "background": theme["superficie"],
                "foreground": theme["texto"],
                "fieldbackground": theme["superficie"],
                "rowheight": 24}},
            "Treeview": {"map": {
                "background": [("selected", theme["destaque"])]}},
            "Treeview.Heading": {"configure": {
                "background": theme["tree_head"],
                "foreground": theme["texto"], "borderwidth": 1,
                "bordercolor": theme["borda"]}},
            "TScrollbar": {"configure": {
                "background": theme["aba"], "troughcolor": theme["fundo"],
                "arrowcolor": theme["texto"], "bordercolor": theme["borda"]}},
            "TCheckbutton": {"configure": {
                "background": theme["fundo"], "foreground": theme["texto"]}},
            "TRadiobutton": {"configure": {
                "background": theme["fundo"], "foreground": theme["texto"]}},
            "TEntry": {"configure": {
                "fieldbackground": theme["superficie"],
                "foreground": theme["texto"], "bordercolor": theme["borda"]}},
            "TSpinbox": {"configure": {
                "fieldbackground": theme["superficie"],
                "foreground": theme["texto"]}},
            "TCombobox": {"configure": {
                "fieldbackground": theme["superficie"],
                "foreground": theme["texto"]}},
            "TProgressbar": {"configure": {
                "background": theme["destaque"], "troughcolor": theme["aba"]}},
        })
    except Exception:
        pass
    style.theme_use(name)
    return name


def apply_theme(root: tk.Tk, dark: bool) -> dict:
    """Registra o tema próprio (funciona no Windows vista e Linux) e aplica as cores."""
    theme = THEME_DARK if dark else THEME_LIGHT
    style = ttk.Style(root)
    _register_theme(style, dark)

    # cor do fundo da janela
    root.configure(bg=theme["fundo"])

    # elemento raiz: fundo e texto padrão
    style.configure(".", background=theme["fundo"], foreground=theme["texto"],
                    fieldbackground=theme["superficie"])
    style.configure("TFrame", background=theme["fundo"])
    style.configure("TLabel", background=theme["fundo"], foreground=theme["texto"])

    # botões: corpo escuro no claro (contraste), claro no escuro
    # os configure/map abaixo apenas ajustam detalhes depois do registro do tema
    style.configure("TProgressbar", background=theme["destaque"], troughcolor=theme["aba"])
    return theme
