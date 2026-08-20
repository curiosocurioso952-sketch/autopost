"""
AutoPost — Base comum para todos os conectores de plataforma.

YouTube, Instagram e TikTok implementam a mesma interface:
conectar / desconectar / publicar. Isso permite trocar ou adicionar
plataformas sem mexer no núcleo.

Publicação direta por API oficial (nada de simular cliques no navegador).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PublishRequest:
    video_path: str
    title: str
    description: str
    hashtags: str
    extra: dict  # metadados específicos por plataforma (visibilidade, thumbnail etc.)


class BasePlatform(ABC):
    platform_name: str = "Plataforma"

    @abstractmethod
    def connect(self, credentials: dict) -> str:
        """Autentica e retorna o nome da conta conectada (ex: canal do YouTube).
        Lança RuntimeError em caso de falha."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def publish(self, request: PublishRequest) -> str:
        """Publica o vídeo e retorna a URL da publicação.
        Lança RuntimeError com a mensagem de erro em caso de falha."""
        ...
