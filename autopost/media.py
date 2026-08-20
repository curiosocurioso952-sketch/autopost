"""
AutoPost V6 — Processamento de vídeo (ffmpeg).

Responsável por:
  * localizar o ffmpeg no Windows (PATH ou pasta tools/ ao lado do app)
  * extrair miniaturas dos vídeos para a lista de conteúdo
  * converter vídeos para o formato exigido por cada plataforma
    (9:16 vertical, h264+aac, limites de duração)
  * gravar legendas (burn-in) no vídeo

O ffmpeg.exe é pesado (~100 MB), então ele não acompanha o ZIP do app.
Na primeira necessidade de conversão, o app mostra um aviso com o caminho
para o usuário baixá-lo (script guiado em PowerShell incluso).
"""

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

_THUMB_DIR = Path(__file__).parent.parent / "thumbs"
_CONV_DIR = Path(__file__).parent.parent / "converted"

_lock = threading.Lock()


def _ffmpeg_path() -> str | None:
    """Localiza o ffmpeg.exe no Windows."""
    if sys.platform == "win32":
        here = Path(__file__).parent.parent
        for candidate in (here / "tools" / "ffmpeg.exe", here / "ffmpeg.exe"):
            if candidate.exists():
                return str(candidate)
        if shutil.which("ffmpeg.exe"):
            return shutil.which("ffmpeg.exe")
        return None
    return shutil.which("ffmpeg")


def has_ffmpeg() -> bool:
    return _ffmpeg_path() is not None


def run_ffmpeg(args: list[str], timeout: int = 300) -> str:
    """Executa ffmpeg/ffprobe e devolve a saída de erro. Levanta RuntimeError se falhar."""
    exe = _ffmpeg_path()
    if exe is None:
        raise RuntimeError("ffmpeg não encontrado")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error"] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {proc.stderr[:300]}")
    return proc.stderr


def _ffprobe_path() -> str | None:
    """Localiza o ffprobe.exe no Windows (mesma pasta do ffmpeg)."""
    if sys.platform == "win32":
        here = Path(__file__).parent.parent
        for candidate in (here / "tools" / "ffprobe.exe", here / "ffprobe.exe"):
            if candidate.exists():
                return str(candidate)
        if shutil.which("ffprobe.exe"):
            return shutil.which("ffprobe.exe")
        # ffmpeg.exe e ffprobe.exe costumam vir juntos; tentar inferir pela pasta
        ffmpeg = _ffmpeg_path()
        if ffmpeg:
            p = Path(ffmpeg).with_name("ffprobe.exe")
            if p.exists():
                return str(p)
        return None
    return shutil.which("ffprobe")


def probe(video: str) -> dict:
    """Informações básicas do vídeo via ffprobe (resolução, duração, orientação)."""
    exe = _ffprobe_path() or _ffmpeg_path()
    if exe is None:
        return {}
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-show_entries",
           "stream=width,height,codec_type,duration:format=duration",
           "-of", "json", "-v", "quiet", str(video)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if proc.returncode != 0:
        return {}
    import json
    try:
        data = json.loads(proc.stdout)
    except Exception:
        return {}
    out = {"width": 0, "height": 0, "duration": 0, "is_vertical": False}
    for s in data.get("streams", []) or []:
        if s.get("codec_type") == "video":
            out["width"] = int(s.get("width") or 0)
            out["height"] = int(s.get("height") or 0)
            out["duration"] = float(s.get("duration") or 0)
            break
    if not out["duration"]:
        out["duration"] = float(data.get("format", {}).get("duration") or 0)
    out["is_vertical"] = out["height"] > out["width"]
    return out


def _copy_for_ffmpeg(video: str) -> str:
    """Contorna falhas do ffmpeg com caminhos contendo acentos no Windows:
    copia o vídeo para a pasta thumbs/ com nome simples (sem acentos) e devolve o novo path."""
    vid = Path(video)
    if vid.exists() and vid.name.isascii():
        return str(vid)
    if not vid.exists():
        raise FileNotFoundError(str(vid))
    import hashlib
    safe = "tmp_" + hashlib.md5(str(vid).encode("utf-8")).hexdigest()[:12] + vid.suffix.lower()
    dest = _THUMB_DIR / safe
    dest.write_bytes(vid.read_bytes())
    return str(dest)


def extract_thumb(video: str, thumb_path: str, t_seconds: float = 1.0) -> str | None:
    """Extrai uma miniatura do vídeo (320px de largura) no instante t_seconds. Retorna o path ou None."""
    exe = _ffmpeg_path()
    if exe is None:
        return None
    _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    t = 1.0 if t_seconds is None else float(t_seconds)
    src = str(video)
    # caminhos não-ASCII falham no ffmpeg do Windows — copiar primeiro quando necessário
    if not Path(src).name.isascii() and Path(src).exists():
        try:
            src = _copy_for_ffmpeg(video)
        except Exception:
            pass
    try:
        run_ffmpeg([
            "-ss", str(t), "-i", src,
            "-frames:v", "1", "-vf", "scale=320:-1",
            "-q:v", "3", "-update", "1", str(thumb_path),
        ], timeout=120)
        if Path(thumb_path).exists() and Path(thumb_path).stat().st_size > 0:
            return thumb_path
        return None
    except RuntimeError:
        # fallback: renomear para nome simples (código de erro do ffmpeg com acentos)
        try:
            safe_src = _copy_for_ffmpeg(video)
            if safe_src != src:
                run_ffmpeg([
                    "-ss", str(t), "-i", safe_src,
                    "-frames:v", "1", "-vf", "scale=320:-1",
                    "-q:v", "3", "-update", "1", str(thumb_path),
                ], timeout=120)
                if Path(thumb_path).exists() and Path(thumb_path).stat().st_size > 0:
                    return thumb_path
        except Exception:
            pass
        return None


def _pil_available() -> bool:
    """Verifica se a Pillow está instalada (nem sempre o usuário instalou)."""
    try:
        import PIL  # noqa
        return True
    except Exception:
        return False


def make_cover(video: str, title: str, out_path: str, width: int = 480) -> str | None:
    """Gera a capa do post (como o vídeo vai aparecer na rede): frame do vídeo em
    formato 16:9 com uma faixa inferior escura contendo o título. Devolve o path ou None.
    Funciona mesmo SEM a Pillow (usa ffmpeg puro com drawtext)."""
    try:
        if _pil_available():
            return _make_cover_pil(video, title, out_path, width)
        return _make_cover_ffmpeg(video, title, out_path, width)
    except Exception:
        return None


def _make_cover_pil(video: str, title: str, out_path: str, width: int = 480) -> str | None:
    """Caminho PIL: recorte 16:9 + faixa com título via Pillow (melhor tipografia)."""
    from PIL import Image, ImageDraw, ImageFont
    height = int(width * 9 / 16)
    _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    tmp_frame = Path(out_path).with_name("_cover_frame.jpg")
    frame = extract_thumb(video, str(tmp_frame), t_seconds=1.0) or extract_thumb(video, str(tmp_frame), t_seconds=0.3)
    if not frame:
        return None
    base = Image.open(frame).convert("RGB")
    # recortar para 16:9 centralizado
    bw, bh = base.size
    target_ratio = 16 / 9
    if bw / bh > target_ratio:
        new_w = int(bh * target_ratio)
        x0 = (bw - new_w) // 2
        base = base.crop((x0, 0, x0 + new_w, bh))
    elif bw / bh < target_ratio:
        new_h = int(bw / target_ratio)
        y0 = (bh - new_h) // 2
        base = base.crop((0, y0, bw, y0 + new_h))
    base = base.resize((width, height), Image.LANCZOS)
    canvas = Image.new("RGB", (width, height), "#111114")
    canvas.paste(base, (0, 0))
    # faixa inferior com o título
    band_h = max(34, height // 4)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, height - band_h, width, height], fill=(17, 17, 20, 255))
    gradient = int(band_h * 0.35)
    for i in range(gradient):
        alpha = int(255 * (1 - i / gradient))
        draw.line([0, height - band_h + i, width, height - band_h + i],
                  fill=(17, 17, 20, alpha))
    # texto com quebra de linha
    font = None
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "C:/Windows/Fonts/arialbd.ttf"):
        if os.path.exists(cand):
            font = ImageFont.truetype(cand, max(12, band_h // 3))
            break
    if font is None:
        font = ImageFont.load_default()
    import textwrap as _tw
    chars = max(20, width // 7)
    lines = _tw.wrap(title or "Novo vídeo", width=chars)[:3]
    pad = 8
    ty = height - band_h + pad
    for ln in lines:
        draw.text((pad + 4, ty), ln.strip(), font=font, fill=(255, 255, 255))
        ty += font.size + 4
    canvas.save(out_path, "JPEG", quality=85)
    if tmp_frame.exists():
        tmp_frame.unlink()
    return out_path


def _make_cover_ffmpeg(video: str, title: str, out_path: str, width: int = 480) -> str | None:
    """Caminho ffmpeg puro (sem Pillow): frame em 16:9 com caixa de texto e título.
    Usado no Windows quando o usuário não instalou a Pillow."""
    exe = _ffmpeg_path()
    if exe is None:
        return None
    height = int(width * 9 / 16)
    _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    tmp_frame = Path(out_path).with_name("_cover_frame.jpg")
    frame = extract_thumb(video, str(tmp_frame), t_seconds=1.0) or extract_thumb(video, str(tmp_frame), t_seconds=0.3)
    if not frame:
        return None
    import textwrap as _tw
    # quebrar o título em até 3 linhas (≈ 40 caracteres por linha no vídeo)
    lines = _tw.wrap((title or "Novo vídeo")[:120], width=40)[:3]
    text = " \\n ".join(ln.strip() for ln in lines)
    box_h = 30 + len(lines) * 22
    font = "C\\\\Windows\\\\Fonts\\\\arialbd.ttf"
    filters = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        f"drawbox=x=0:y=ih-{box_h}:w=iw:h={box_h}:color=black@0.75:t=fill,"
        f"drawtext=fontfile={font}:text='{text}':fontcolor=white:fontsize=18:" +
        f"x=12:y=h-{box_h}+10:box=0"
    )
    try:
        run_ffmpeg(["-i", str(frame), "-vf", filters, "-frames:v", "1", "-q:v", "3",
                    "-update", "1", str(out_path)], timeout=120)
        if Path(out_path).exists() and Path(out_path).stat().st_size > 0:
            if tmp_frame.exists():
                tmp_frame.unlink()
            return out_path
    except RuntimeError:
        pass
    return None


def extract_frames(video: str, out_dir: str, count: int = 4) -> list[str]:
    """Extrai `count` frames equidistantes para a análise por IA. Retorna lista de paths."""
    exe = _ffmpeg_path()
    if exe is None:
        return []
    d = probe(video)
    dur = max(d.get("duration") or 1, 3)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        t = dur * (i + 0.5) / count
        out = os.path.join(out_dir, f"frame_{i+1}.jpg")
        p = extract_thumb(video, out, t_seconds=t)
        if p:
            paths.append(p)
    return paths


# Perfis de conversão por plataforma (TikTok / Instagram Reels / YouTube Shorts)
# Vertical 1080x1920, h264+aac, máx 600s (limite do upload direto do TikTok).
PLATFORM_PROFILES = {
    "TikTok": dict(width=1080, height=1920, max_duration=600, label="TikTok (vertical 9:16, até 10 min)"),
    "Instagram": dict(width=1080, height=1920, max_duration=600, label="Instagram Reels (vertical 9:16, até 10 min)"),
    "YouTube": dict(width=1080, height=1920, max_duration=3600, label="YouTube Shorts (vertical 9:16)"),
}


def build_filter(profile: dict) -> str:
    """Filtro de vídeo: escala para o perfil mantendo proporção (com preenchimento preto)."""
    w, h = profile["width"], profile["height"]
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p")


def convert_video(video: str, out_path: str, platform: str, max_duration: int | None = None,
                  callback=None) -> str:
    """Converte o vídeo para o formato da plataforma. Retorna o path final ou levanta RuntimeError.

    callback(progress_0_100) — relatório de progresso opcional."""
    profile = PLATFORM_PROFILES.get(platform, PLATFORM_PROFILES["TikTok"])
    max_dur = max_duration if max_duration is not None else profile["max_duration"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    vf = build_filter(profile)
    args = ["-i", str(video), "-vf", vf, "-c:v", "libx264", "-preset", "medium",
            "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
    if max_dur:
        args += ["-t", str(int(max_dur))]

    exe = _ffmpeg_path()
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error"] + args + [str(out_path)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    duration = probe(video).get("duration") or 0
    while True:
        line = proc.stderr.readline()
        if line == "" and proc.poll() is not None:
            break
        if line.startswith("time="):
            try:
                ts = line.split("time=")[1].split(" ")[0]
                h, m, s = ts.split(":")
                t = int(h) * 3600 + int(m) * 60 + float(s)
                if duration and callback:
                    callback(min(100, int(100 * t / duration)))
            except Exception:
                pass

    proc.wait(timeout=300)
    if proc.returncode != 0:
        err = proc.stderr.read()
        raise RuntimeError(f"Conversão falhou: {err[:300]}")
    if not Path(out_path).exists() or Path(out_path).stat().st_size < 1000:
        raise RuntimeError("Conversão não produziu um arquivo válido")
    return out_path


def burn_subtitles(video: str, srt_path: str, out_path: str, platform: str = "TikTok") -> str:
    """Grava legendas (.srt) no vídeo e já aplica o formato da plataforma."""
    profile = PLATFORM_PROFILES.get(platform, PLATFORM_PROFILES["TikTok"])
    vf = (f"subtitles='{srt_path.replace(chr(92), chr(92)*2)}':force_style='FontSize=14,"
          f"FontName=DejaVu Sans,BorderStyle=1,Outline=1,Shadow=0',"
          f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease,"
          f"pad={profile['width']}:{profile['height']}:(ow-iw)/2:(oh-ih)/2:black,"
          f"fps=30,format=yuv420p")
    run_ffmpeg(["-i", str(video), "-vf", vf, "-c:v", "libx264", "-preset", "medium",
                "-crf", "23", "-c:a", "copy", str(out_path)], timeout=1800)
    return out_path


def make_srt(subtitles_text: str, out_path: str, total_duration: float | None = None) -> str:
    """Gera um arquivo .srt a partir de um texto.
    O texto pode conter blocos no formato 'mm:ss texto...' ou será distribuído
    igualmente se não houver tempos."""
    lines = [ln.strip() for ln in (subtitles_text or "").splitlines() if ln.strip()]
    if not lines:
        raise ValueError("Texto de legendas vazio")

    def fmt(n: int) -> str:
        m, s = divmod(int(n), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d},000"

    entries = []
    # formato suportado: "00:05 primeira frase" (tempo no início da linha)
    import re
    pat = re.compile(r"^(?:(\d{1,2}):(\d{2}))\s+(.*)$")
    for ln in lines:
        m = pat.match(ln)
        if m:
            t = int(m.group(1)) * 60 + int(m.group(2))
            entries.append((t, m.group(3)))
        else:
            entries.append((None, ln))

    with _lock:
        with open(out_path, "w", encoding="utf-8") as f:
            if entries[0][0] is None and total_duration:
                # distribuir uniformemente
                n = len(entries)
                step = total_duration / n
                for i, (_, text) in enumerate(entries):
                    start = int(i * step)
                    end = int((i + 1) * step)
                    f.write(f"{i+1}\n{fmt(start)} --> {fmt(end)}\n{text}\n\n")
            else:
                for i, (t, text) in enumerate(entries):
                    if t is None:
                        t = 0
                    end = t + 5
                    f.write(f"{i+1}\n{fmt(t)} --> {fmt(end)}\n{text}\n\n")
    return out_path
