"""AniList: a reserva da busca por nome quando a Jikan (MyAnimeList) falha."""

import json
from datetime import date

import httpx
import pytest

from lista_animes.catalogo import CatalogoIndisponivel, ler_anime_anilist, limpar_sinopse
from tests.conftest import anilist_frieren, frieren_da_jikan

FORA_DO_AR = httpx.Response(504, json={"status": 504})


def busca_anilist(*animes: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": {"Page": {"media": list(animes)}}})


def test_ler_anime_converte_resposta_real_do_anilist():
    frieren, terceira = anilist_frieren()["data"]["Page"]["media"]

    anime = ler_anime_anilist(frieren)

    assert anime.mal_id == 52991  # o ID do MyAnimeList, que o resto do app usa
    assert anime.titulo == "Sousou no Frieren"
    assert anime.titulo_ingles.startswith("Frieren")
    assert anime.total_episodios == 28
    assert anime.tipo == "TV"
    assert anime.ano == 2023
    assert anime.estreia == date(2023, 9, 29)
    assert anime.generos == ["Adventure", "Drama", "Fantasy"]
    assert anime.imagem_url.startswith("https://")
    assert "<br>" not in anime.sinopse
    assert anime.nota_mal is None  # a nota do AniList não é a do MyAnimeList
    assert anime.relacionados is None
    assert anime.fonte == "anilist"
    # Estreia sem o dia marcado e episódios ainda desconhecidos ficam vazios.
    assert ler_anime_anilist(terceira).estreia is None
    assert ler_anime_anilist(terceira).total_episodios is None


def test_anime_do_anilist_sem_id_do_myanimelist_fica_de_fora():
    assert ler_anime_anilist({"idMal": None, "title": {"romaji": "Só no AniList"}}) is None


def test_tipo_do_anilist_vira_o_nome_do_myanimelist():
    base = {"idMal": 1, "title": {"romaji": "X"}}

    assert ler_anime_anilist({**base, "format": "MOVIE"}).tipo == "Movie"
    assert ler_anime_anilist({**base, "format": "TV_SHORT"}).tipo == "TV"
    assert ler_anime_anilist({**base, "format": "NOVO_FORMATO"}).tipo is None


def test_limpar_sinopse_tira_tags_e_entidades():
    texto = "Primeira parte &quot;citada&quot;.\n<br><br>\n<i>(Fonte: Crunchyroll)</i>"

    assert limpar_sinopse(texto) == 'Primeira parte "citada".\n\n(Fonte: Crunchyroll)'
    assert limpar_sinopse("") is None
    assert limpar_sinopse(None) is None


def test_com_a_jikan_fora_do_ar_a_busca_usa_o_anilist(catalogo, jikan):
    jikan.responder("/anime", FORA_DO_AR)
    jikan.anilist = httpx.Response(200, json=anilist_frieren())

    resultado = catalogo.buscar("frieren", limite=5)

    assert [a.mal_id for a in resultado] == [52991, 63816]
    assert {a.fonte for a in resultado} == {"anilist"}
    [pedido] = jikan.pedidos_anilist
    assert json.loads(pedido.content)["variables"] == {"busca": "frieren", "limite": 5}


def test_com_a_jikan_funcionando_o_anilist_nem_e_consultado(catalogo, jikan):
    jikan.responder("/anime", httpx.Response(200, json={"data": [frieren_da_jikan()["data"]]}))

    [anime] = catalogo.buscar("frieren")

    assert anime.fonte == "jikan"
    assert jikan.pedidos_anilist == []


def test_busca_no_anilist_remove_repetidos_e_os_sem_id(catalogo, jikan):
    jikan.responder("/anime", FORA_DO_AR)
    um = {"idMal": 1, "title": {"romaji": "Cowboy Bebop"}}
    jikan.anilist = busca_anilist(um, {"idMal": None, "title": {"romaji": "Sem ID"}}, um)

    assert [a.mal_id for a in catalogo.buscar("bebop")] == [1]


def test_resultado_quebrado_do_anilist_e_pulado_sem_derrubar_os_outros(catalogo, jikan):
    jikan.responder("/anime", FORA_DO_AR)
    sem_titulo = {"idMal": 2, "title": {"romaji": None, "english": None}}
    jikan.anilist = busca_anilist({"idMal": 1, "title": {"romaji": "Cowboy Bebop"}}, sem_titulo)

    assert [a.mal_id for a in catalogo.buscar("bebop")] == [1]


@pytest.mark.parametrize(
    "resposta_anilist",
    [
        httpx.Response(503),
        httpx.Response(200, text="<html>não é JSON</html>"),
        httpx.Response(200, json={"errors": [{"message": "Not Found"}], "data": None}),
        httpx.Response(200, json={"data": {"Page": {"media": None}}}),
        httpx.ConnectError("sem internet"),
    ],
)
def test_com_os_dois_fora_do_ar_vale_a_mensagem_da_jikan(catalogo, jikan, resposta_anilist):
    jikan.responder("/anime", FORA_DO_AR)
    jikan.anilist = resposta_anilist

    with pytest.raises(CatalogoIndisponivel, match="MyAnimeList está fora do ar"):
        catalogo.buscar("frieren")


def test_rota_de_busca_diz_que_os_resultados_vieram_do_anilist(cliente, jikan):
    jikan.responder("/anime", FORA_DO_AR)
    jikan.anilist = httpx.Response(200, json=anilist_frieren())

    resposta = cliente.get("/catalogo/busca", params={"q": "frieren"})

    assert resposta.status_code == 200
    assert resposta.json()[0]["fonte"] == "anilist"
    assert resposta.json()[0]["mal_id"] == 52991
