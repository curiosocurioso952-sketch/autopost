"""
AutoPost — Leitura automática de vídeos a partir de pastas.

Escaneia recursivamente uma pasta, detecta os formatos de vídeo suportados,
leva em conta arquivos já importados e devolve a lista de novidades.
"""

from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".m4v", ".flv"}


def scan_folder(folder: str | Path) -> list[Path]:
    """Devolve os arquivos de vídeo existentes na pasta (recursivo), ordenados por nome."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    files.sort(key=lambda p: p.name.lower())
    return files


def scan_duration_guess(path: Path) -> int | None:
    """Tenta obter a duração do vídeo em segundos (dependência opcional: moviepy/ffmpeg)."""
    try:
        from moviepy import VideoFileClip
        with VideoFileClip(str(path)) as clip:
            return int(clip.duration) if clip.duration else None
    except Exception:
        return None
