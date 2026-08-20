"""
AutoPost — Conector oficial do YouTube (API: videos.insert / upload resumido).

Fluxo de autenticação OAuth2 do Google:
1. O usuário cria credenciais no Google Cloud Console (Client ID + Secret).
2. O cliente da Google gera a URL de autorização; o usuário autoriza no navegador UMA vez.
3. O token de acesso (e refresh) fica salvo em local; o refresh acontece sozinho.

Upload usa upload resumido (30 MiB por bloco), retomável se cair no meio.
"""

import json
import os
from pathlib import Path
from typing import Optional

from .base import BasePlatform, PublishRequest

CHUNK = 30 * 1024 * 1024  # 30 MiB por bloco do upload resumido


class YouTubePlatform(BasePlatform):
    platform_name = "YouTube"

    def __init__(self, client_config_path: Optional[str | Path] = None):
        self._client_config = Path(client_config_path) if client_config_path else None
        self._service = None
        self._channel = None

    # ------------------------------------------------------------------ login
    def connect(self, credentials: dict) -> str:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = Path(__file__).parent.parent.parent / "youtube_token.json"

        if token_path.exists():
            import json as _json
            saved = _json.loads(token_path.read_text())
            scopes = saved.get("scopes") or []
            required = "https://www.googleapis.com/auth/youtube.upload"
            # Token antigo autorizado com escopo insuficiente → apagar e pedir nova autorização
            if required not in scopes:
                token_path.unlink()
            else:
                creds = Credentials.from_authorized_user_info(saved)
                self._service = build("youtube", "v3", credentials=creds)
                try:
                    self._channel = self._service.channels().list(part="snippet", mine=True).execute()
                    if not creds.expired:
                        return f"YouTube — {self._channel['items'][0]['snippet']['title']}"
                except Exception:
                    pass
                if creds.expired and creds.refresh_token:
                    from google.auth.transport.requests import Request
                    creds.refresh(Request())
                    token_path.write_text(creds.to_json())
                    self._service = build("youtube", "v3", credentials=creds)
                    self._channel = self._service.channels().list(part="snippet", mine=True).execute()
                    return f"YouTube — {self._channel['items'][0]['snippet']['title']}"
                # refresh falhou → apagar token e reautorizar
                token_path.unlink()
        # Nova autorização (abre o navegador)
        if not self._client_config or not self._client_config.exists():
            raise RuntimeError("Arquivo de credenciais do Google (client_secret_*.json) não informado ou não existe.")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._client_config), ["https://www.googleapis.com/auth/youtube.upload"])
        creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

        self._service = build("youtube", "v3", credentials=creds)
        self._channel = self._service.channels().list(part="snippet", mine=True).execute()
        title = self._channel["items"][0]["snippet"]["title"]
        return f"YouTube — {title}"

    def disconnect(self) -> None:
        self._service = None
        self._channel = None
        token_path = Path(__file__).parent.parent.parent / "youtube_token.json"
        if token_path.exists():
            token_path.unlink()

    def is_connected(self) -> bool:
        return self._service is not None

    # ---------------------------------------------------------------- publish
    def publish(self, request: PublishRequest) -> str:
        if not self.is_connected():
            raise RuntimeError("YouTube não está conectado. Conecte a conta primeiro.")

        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

        body = {
            "snippet": {
                "title": request.title,
                "description": request.description,
                "tags": [t.strip() for t in request.hashtags.replace("#", "").split(",") if t.strip()],
            },
            "status": {"privacyStatus": request.extra.get("privacy", "private"),
                       "selfDeclaredMadeForKids": False},
        }

        media = MediaFileUpload(request.video_path, mimetype="video/*", resumable=True, chunksize=CHUNK)
        try:
            resp = self._service.videos().insert(part="snippet,status", body=body,
                                                 media_body=media).execute()
            return f"https://youtu.be/{resp['id']}"
        except HttpError as e:
            raise RuntimeError(f"Erro no upload para o YouTube: {e}")
