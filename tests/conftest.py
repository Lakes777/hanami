import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lista_animes.app import criar_app
from lista_animes.catalogo import Catalogo

DADOS = Path(__file__).parent / "dados"


def frieren_da_jikan() -> dict:
    """Resposta real da Jikan para o Frieren (gravada em tests/dados, sem internet)."""
    return json.loads((DADOS / "jikan_anime_52991.json").read_text(encoding="utf-8"))


def anilist_frieren() -> dict:
    """Resposta real do AniList para a busca "frieren" (gravada em tests/dados)."""
    return json.loads((DADOS / "anilist_busca_frieren.json").read_text(encoding="utf-8"))


class JikanFalsa:
    """Responde no lugar da Jikan (e do AniList, a reserva da busca por nome).
    Cada teste diz o que elas devem devolver."""

    def __init__(self) -> None:
        self.respostas: dict[str, httpx.Response | Exception] = {}
        self.pedidos: list[httpx.Request] = []
        # Se o teste não disser nada, o AniList também está fora do ar.
        self.anilist: httpx.Response | Exception = httpx.Response(503)
        self.pedidos_anilist: list[httpx.Request] = []

    def responder(self, caminho: str, resposta: httpx.Response | Exception) -> None:
        self.respostas["/v4" + caminho] = resposta

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        if pedido.url.host == "graphql.anilist.co":
            self.pedidos_anilist.append(pedido)
            if isinstance(self.anilist, Exception):
                raise self.anilist
            return self.anilist
        self.pedidos.append(pedido)
        resposta = self.respostas.get(pedido.url.path)
        if resposta is None:
            raise AssertionError(f"Consulta inesperada à Jikan: {pedido.url}")
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


@pytest.fixture
def jikan():
    return JikanFalsa()


@pytest.fixture
def catalogo(jikan):
    return Catalogo(transport=httpx.MockTransport(jikan))


@pytest.fixture
def cliente(tmp_path, catalogo):
    # O TestClient chama a API direto na memória, sem abrir porta nem usar internet.
    # Cada teste ganha uma API com banco novo numa pasta temporária e a Jikan falsa.
    return TestClient(criar_app(tmp_path / "teste.db", catalogo))
