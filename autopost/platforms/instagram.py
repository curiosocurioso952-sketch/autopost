"""
AutoPost — Conector oficial do Instagram (API: Instagram Graph API da Meta).

Observações importantes:
- A Instagram Graph API publica em CONTA EMPRESARIAL/CREATOR do Instagram
  vinculada a uma Página do Facebook.
- Vídeo de até 15 minutos: fluxo de 2 etapas (create container -> publish).
- O token de acesso vem de um App do Facebook Developers com permissão
  instagram_content_publish.

Documentação: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
"""

import time
from typing import Optional

import requests

from .base import BasePlatform, PublishRequest


class InstagramPlatform(BasePlatform):
    platform_name = "Instagram"

    def __init__(self, access_token: Optional[str] = None,
                 ig_user_id: Optional[str] = None):
        self._token = access_token
        self._user_id = ig_user_id
        self._name: Optional[str] = None

    def connect(self, credentials: dict) -> str:
        token = credentials.get("access_token")
        user_id = credentials.get("ig_user_id")
        if not token or not user_id:
            raise RuntimeError("Informe o access_token e o ig_user_id da conta Instagram.")

        # valida o token e descobre o nome do perfil
        r = requests.get(f"https://graph.facebook.com/v21.0/{user_id}",
                         params={"fields": "username", "access_token": token}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Instagram recusou o token: {r.json().get('error', {}).get('message', r.text)}")

        self._token, self._user_id = token, user_id
        self._name = r.json()["username"]
        return f"Instagram — @{self._name}"

    def disconnect(self) -> None:
        self._token = None
        self._user_id = None
        self._name = None

    def is_connected(self) -> bool:
        return bool(self._token and self._user_id)

    def publish(self, request: PublishRequest) -> str:
        if not self.is_connected():
            raise RuntimeError("Instagram não está conectado.")

        caption = f"{request.description}\n\n{request.hashtags}".strip()
        media_type = request.extra.get("media_type", "REELS")

        create_url = f"https://graph.facebook.com/v21.0/{self._user_id}/media"
        payload = {
            "media_type": media_type,
            "video_url": request.video_path,   # URL pública ou http(s) acessível pela Meta
            "caption": caption,
            "access_token": self._token,
        }
        payload.update(request.extra)

        r = requests.post(create_url, data=payload, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"Falha ao criar container no Instagram: {r.json().get('error', {}).get('message', r.text)}")

        container_id = r.json()["id"]

        # publicar
        p = requests.post(f"https://graph.facebook.com/v21.0/{self._user_id}/media_publish",
                          data={"creation_id": container_id, "access_token": self._token}, timeout=60)
        if p.status_code != 200:
            raise RuntimeError(f"Falha ao publicar no Instagram: {p.json().get('error', {}).get('message', p.text)}")

        media_id = p.json()["id"]

        # esperar processamento e devolver o permalink
        for _ in range(30):
            time.sleep(3)
            s = requests.get(f"https://graph.facebook.com/v21.0/{media_id}",
                             params={"fields": "status_code,permalink", "access_token": self._token},
                             timeout=30)
            data = s.json()
            if data.get("status_code") == "FINISHED":
                return data.get("permalink", f"https://www.instagram.com/reel/{media_id}/")
            if data.get("status_code") == "ERROR":
                raise RuntimeError("Instagram concluiu o processamento do vídeo com erro.")
        raise RuntimeError("Instagram ainda está processando o vídeo; verifique o app no celular.")
