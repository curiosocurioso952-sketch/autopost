"""
AutoPost — Conector oficial do TikTok (API: Content Posting API v2).

Fluxo de autenticação OAuth2 do TikTok:
1. O usuário cria um app em developers.tiktok.com, adiciona o produto
   "Content Posting API" e habilita a configuração "Direct Post".
2. O usuário autoriza o app com o escopo video.publish no navegador
   (uma única vez); o app recebe um código de autorização.
3. O AutoPost troca o código por access_token (+ refresh_token salvo
   localmente) e publica via upload de arquivo local (FILE_UPLOAD).

Upload usa chunks de 15 MiB enviados via PUT para a upload_url do TikTok,
conforme a documentação oficial (media transfer guide).
"""

import json
import math
import time
from pathlib import Path

import requests

from .base import BasePlatform, PublishRequest

CHUNK = 15 * 1024 * 1024  # 15 MiB por bloco do upload resumido


class TikTokPlatform(BasePlatform):
    platform_name = "TikTok"

    def __init__(self, client_key: str | None = None, client_secret: str | None = None):
        self._client_key = client_key
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._open_id: str | None = None
        self._name: str | None = None
        self._token_path = Path(__file__).parent.parent.parent / "tiktok_token.json"

    # ------------------------------------------------------------------ login
    def connect(self, credentials: dict) -> str:
        """credentials: {code, redirect_uri} (fluxo OAuth) ou {refresh_token}."""
        code = credentials.get("code")
        redirect_uri = credentials.get("redirect_uri", "https://example.com")
        refresh = credentials.get("refresh_token")

        if refresh:
            self._refresh_token = refresh
            self._exchange(refresh_token=refresh)
        elif code and self._client_key and self._client_secret:
            r = requests.post("https://open.tiktokapis.com/v2/oauth/token/",
                              headers={"Content-Type": "application/x-www-form-urlencoded"},
                              data={
                                  "client_key": self._client_key,
                                  "client_secret": self._client_secret,
                                  "code": code,
                                  "grant_type": "authorization_code",
                                  "redirect_uri": redirect_uri,
                              }, timeout=30)
            j = r.json()
            if r.status_code != 200 or "error" in j:
                err = j.get("error", {})
                raise RuntimeError(f"TikTok recusou o código: {err.get('description', r.text)}")
            self._access_token = j["access_token"]
            self._refresh_token = j.get("refresh_token") or self._refresh_token
            self._open_id = j["open_id"]
            self._persist()
        else:
            # tenta carregar token salvo
            if self._token_path.exists():
                saved = json.loads(self._token_path.read_text())
                self._access_token = saved.get("access_token")
                self._refresh_token = saved.get("refresh_token")
                self._open_id = saved.get("open_id")
            if not self._access_token:
                raise RuntimeError("Sem código de autorização nem token salvo. "
                                   "Conecte a conta do TikTok primeiro.")

        if self._refresh_token and self._token_path.exists():
            self._persist()

        # nome do perfil
        u = requests.get("https://open.tiktokapis.com/v2/user/info/",
                         headers={"Authorization": f"Bearer {self._access_token}"}, timeout=30)
        self._name = u.json().get("data", {}).get("user", {}).get("display_name", "TikTok")
        return f"TikTok — @{self._name}"

    def _exchange(self, refresh_token: str) -> None:
        r = requests.post("https://open.tiktokapis.com/v2/oauth/token/",
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          data={
                              "client_key": self._client_key or "",
                              "client_secret": self._client_secret or "",
                              "grant_type": "refresh_token",
                              "refresh_token": refresh_token,
                          }, timeout=30)
        j = r.json()
        if r.status_code != 200 or "error" in j:
            raise RuntimeError(f"Refresh do token TikTok falhou: {j.get('error', {}).get('description', r.text)}")
        self._access_token = j["access_token"]
        self._refresh_token = j.get("refresh_token") or refresh_token
        self._open_id = j.get("open_id") or self._open_id
        self._persist()

    def _persist(self) -> None:
        self._token_path.write_text(json.dumps({
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "open_id": self._open_id,
        }))

    def disconnect(self) -> None:
        self._access_token = None
        self._refresh_token = None
        self._open_id = None
        self._name = None
        if self._token_path.exists():
            self._token_path.unlink()

    def is_connected(self) -> bool:
        return bool(self._access_token)

    # ---------------------------------------------------------------- publish
    def publish(self, request: PublishRequest) -> str:
        if not self.is_connected():
            raise RuntimeError("TikTok não está conectado.")

        headers = {"Authorization": f"Bearer {self._access_token}",
                   "Content-Type": "application/json; charset=UTF-8"}

        # 0) consultar info do criador (obrigatório pela UX guideline)
        ci = requests.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
                           headers=headers, json={}, timeout=30)
        cd = ci.json().get("data", {}) or {}
        creator_name = cd.get("creator_username", self._name or "TikTok")
        options = cd.get("privacy_level_options") or ["SELF_ONLY"]
        if "PUBLIC_TO_EVERYONE" in options:
            privacy = "PUBLIC_TO_EVERYONE"
        elif "MUTUAL_FOLLOW_FRIENDS" in options:
            privacy = "MUTUAL_FOLLOW_FRIENDS"
        else:
            privacy = "SELF_ONLY"
        privacy = request.extra.get("privacy", privacy)

        # 1) inicializar o post com FILE_UPLOAD
        size = Path(request.video_path).stat().st_size
        chunk_count = math.ceil(size / CHUNK)
        init = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/",
                             headers=headers,
                             json={
                                 "post_info": {
                                     "title": request.title,
                                     "privacy_level": privacy,
                                     "disable_duet": False, "disable_comment": False,
                                     "disable_stitch": False,
                                     "video_cover_timestamp_ms": 1000,
                                     "brand_content_toggle": False, "brand_organic_toggle": False,
                                     "is_aigc": False,
                                 },
                                 "source_info": {
                                     "source": "FILE_UPLOAD",
                                     "video_size": size,
                                     "chunk_size": CHUNK,
                                     "total_chunk_count": chunk_count,
                                 },
                             }, timeout=60)
        d = init.json()
        if d.get("error") and d["error"].get("code") not in ("ok", "") or \
           not d.get("data", {}).get("upload_url"):
            err = d.get("error", {})
            if err.get("code") == "unaudited_client_can_only_post_to_private_accounts":
                # tenta novamente como privado (apps não auditados só podem postar privado)
                init = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/",
                                     headers=headers,
                                     json={
                                         "post_info": {
                                             "title": request.title,
                                             "privacy_level": "SELF_ONLY",
                                             "disable_duet": False, "disable_comment": False,
                                             "disable_stitch": False,
                                             "video_cover_timestamp_ms": 1000,
                                             "brand_content_toggle": False, "brand_organic_toggle": False,
                                             "is_aigc": False,
                                         },
                                         "source_info": {
                                             "source": "FILE_UPLOAD",
                                             "video_size": size,
                                             "chunk_size": CHUNK,
                                             "total_chunk_count": chunk_count,
                                         },
                                     }, timeout=60)
                d = init.json()
                if not d.get("data", {}).get("upload_url"):
                    err = d.get("error", {})
                    raise RuntimeError(f"TikTok bloqueou a publicação (app sem auditoria): {err.get('description', d)}")
                privacy = "SELF_ONLY"  # app sem auditoria: publica como privado
            else:
                raise RuntimeError(f"Falha ao iniciar upload no TikTok: {err.get('description', d)}")
        publish_id = d["data"]["publish_id"]
        upload_url = d["data"]["upload_url"]

        # 2) enviar o vídeo em blocos via PUT
        with open(request.video_path, "rb") as f:
            for i in range(chunk_count):
                data = f.read(CHUNK)
                first = i * CHUNK
                last = min(first + len(data), size) - 1
                put = requests.put(upload_url,
                                   headers={
                                       "Content-Type": "video/mp4",
                                       "Content-Length": str(len(data)),
                                       "Content-Range": f"bytes {first}-{last}/{size}",
                                   }, data=data, timeout=300)
                if put.status_code not in (200, 201):
                    raise RuntimeError(f"Falha no envio do bloco {i + 1}/{chunk_count} para o TikTok: {put.text}")

        # 3) publicar
        pub = requests.post(
            f"https://open.tiktokapis.com/v2/post/publish/video/{publish_id}/",
            headers=headers, json={}, timeout=120)
        pd = pub.json()
        if pd.get("error") and pd["error"].get("code") not in ("ok", ""):
            raise RuntimeError(f"Falha ao publicar no TikTok: {pd['error'].get('description', pd)}")

        # 4) aguardar conclusão
        for _ in range(60):
            time.sleep(5)
            chk = requests.get("https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                               headers=headers, params={"publish_id": publish_id}, timeout=30)
            status = chk.json().get("data", {}).get("status")
            if status == "PUBLISH_COMPLETE":
                return f"https://www.tiktok.com/@{creator_name}"
            if status == "PUBLISH_FAILED":
                reason = chk.json().get("data", {}).get("fail_reason", "motivo desconhecido")
                raise RuntimeError(f"TikTok falhou ao publicar: {reason}")
        raise RuntimeError("TikTok ainda está processando o vídeo; confira o app.")
