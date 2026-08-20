"""
AutoPost V6 — Geração de metadados com IA (via Manus API).

Analisa frames do vídeo e gera: título chamativo, hashtags relevantes e
legendas embutidas para o vídeo. Exige uma chave da Manus API (gratuita),
obtida em https://manus.im na página de configurações da API.

Limitações conhecidas:
  * Contas gratuitas podem ter a geração feita por um modelo leve
    (manus-1.6-lite), que entende menos os frames — nesse caso o texto
    é gerado a partir do nome do arquivo e da instrução.
  * As imagens são enviadas em base64 inline (máx. 20 MB por arquivo).
"""

import base64
import json
import os
import time
import urllib.request
import urllib.parse

API_URL = "https://api.manus.im/v2/task.create"
MSG_URL = "https://api.manus.im/v2/task.listMessages"

SCHEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string", "description": "Título chamativo do vídeo em português (máx. 90 caracteres)"},
        "hashtags": {"type": "array", "items": {"type": "string"},
                     "description": "De 5 a 10 hashtags relevantes em português, sem o símbolo # (a IA deve inferir do conteúdo)"},
        "legenda": {"type": "string", "description": "Legenda curta para a postagem (1-2 frases, tom envolvente, em português)"},
        "legendas_video": {"type": "string",
                           "description": "Frases curtas de legenda para gravar no vídeo, uma por linha, no formato 'mm:ss frase' (ex.: 00:03 olha só isso), baseadas no que aparece na cena de cada frame"}
    },
    "required": ["titulo", "hashtags", "legenda"]
}

PROMPT = (
    "Você analisa os frames de um vídeo que será publicado no TikTok/Instagram Reels/YouTube Shorts "
    "por um criador de conteúdo brasileiro. Analise o que aparece nas imagens e gere: "
    "1) um título chamativo em português brasileiro; "
    "2) 5 a 10 hashtags relevantes (sem o símbolo #); "
    "3) uma legenda curta e envolvente para a postagem; "
    "4) legendas embutidas para gravar no vídeo, no formato 'mm:ss frase' por linha, descrevendo o que "
    "acontece em cada frame analisado (se não conseguir discernir a cena, gere legendas genéricas de "
    "engajamento apropriadas para vídeos curtos de entretenimento). "
    "Responda apenas com o JSON estruturado solicitado."
)


def _api_key() -> str:
    return os.environ.get("MANUS_API_KEY", "")


def _post(url: str, data: dict, api_key: str) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "x-manus-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def analyze_video(frames: list[str], video_name: str, api_key: str) -> dict | None:
    """Envia os frames para a Manus API e devolve os metadados gerados."""
    if not api_key:
        return None

    attachments = []
    for path in frames:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        if len(b64) > 20 * 1024 * 1024:
            continue  # frames 320px são bem menores que 20MB
        attachments.append({
            "type": "image",
            "file_data": {
                "name": os.path.basename(path),
                "media_type": "image/jpeg",
                "data": b64,
            },
        })

    prompt = f"Nome do arquivo original: {video_name}\n\n{PROMPT}"

    # ContentPart array conforme a doc oficial (file_data inline)
    payload = {
        "prompt": prompt,
        "message": {
            "content": [
                {"type": "text", "text": prompt},
                *attachments,
            ]
        },
        "structured_output_schema": SCHEMA,
        "capabilities": {"image": True},
    }

    try:
        result = _post(API_URL, payload, api_key)
    except Exception:
        return None

    task_id = result.get("taskId") or result.get("task_id")
    if not task_id:
        return None

    # poll das mensagens
    for _ in range(60):
        time.sleep(3)
        try:
            msgs = _post(MSG_URL, {"taskId": task_id}, api_key)
        except Exception:
            continue
        items = msgs.get("messages") or []
        for m in items:
            out = m.get("structuredOutput") or {}
            if out and out.get("titulo"):
                return out
        if msgs.get("status") == "completed":
            # tenta de novo com o corpo completo
            for m in items:
                if m.get("structuredOutput"):
                    return m["structuredOutput"]
            break
        if msgs.get("status") == "failed":
            return None
    return None


def fallback_metadata(video_name: str) -> dict:
    """Metadados genéricos quando a IA não está disponível."""
    import re as _re
    name = os.path.splitext(os.path.basename(video_name))[0]
    # remove sufixos típicos de download (snapinsta, ids aleatórios)
    cleaned = _re.sub(r"(?i)(?:^|\.)snapinsta[.\w_-]*", "", name)
    cleaned = _re.sub(r"(?i)(?:^|\.)app_video[._\w-]*", "", cleaned)
    cleaned = _re.sub(r"\d{10,}[\w_.-]*", "", cleaned)  # ids longos de arquivo
    cleaned = cleaned.strip("._ -")
    cleaned = _re.sub(r"[^\w\s\u00c0-\u024f]+", " ", cleaned).strip()
    cleaned = " ".join(cleaned.split())
    hashtags = ["fyp", "viral", "tiktok", "reels", "viralizandohoje"]
    if cleaned:
        primeira = cleaned[:40]
        return {
            "titulo": cleaned[:80],
            "hashtags": hashtags,
            "legenda": f"{primeira} ✨ Não deixe de assistir!",
        }
    # nome não aproveitável (ex.: downloads com IDs aleatórios)
    return {
        "titulo": "Novo vídeo imperdível",
        "hashtags": hashtags,
        "legenda": "Confere esse vídeo! ✨ Não deixe de assistir!",
    }
