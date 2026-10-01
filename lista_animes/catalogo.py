"""Catálogo de animes da Jikan (https://jikan.moe), com dados do MyAnimeList.

A Jikan é gratuita e não pede chave, mas tem limites: cerca de 3 consultas
por segundo. A busca por nome consulta o MyAnimeList na hora e às vezes falha
com erro 504, quando o MyAnimeList está fora do ar. Por isso, toda falha vira
CatalogoIndisponivel, com uma mensagem que dá para mostrar a quem usa a API.

Quando a busca por nome da Jikan falha, ela é refeita no AniList (https://anilist.co),
outro catálogo gratuito e sem chave. Cada anime do AniList diz o ID dele no MyAnimeList,
então o resto do app continua igual: adicionar usa a busca por ID da Jikan, que
costuma funcionar mesmo com o MyAnimeList fora do ar.
"""

import html
import re
from datetime import date

import httpx

from lista_animes.modelos import AnimeCatalogo, Relacionado

URL_JIKAN = "https://api.jikan.moe/v4"
URL_ANILIST = "https://graphql.anilist.co"

# O AniList usa GraphQL: um POST só, dizendo exatamente quais campos devolver.
BUSCA_ANILIST = """
query ($busca: String, $limite: Int) {
  Page(perPage: $limite) {
    media(search: $busca, type: ANIME, isAdult: false) {
      idMal
      title { romaji english }
      episodes
      format
      seasonYear
      startDate { year month day }
      coverImage { large }
      genres
      description(asHtml: false)
    }
  }
}
"""

# O "format" do AniList com o nome que a Jikan (MyAnimeList) usa para o mesmo tipo.
TIPOS_ANILIST = {
    "TV": "TV",
    "TV_SHORT": "TV",
    "MOVIE": "Movie",
    "SPECIAL": "Special",
    "OVA": "OVA",
    "ONA": "ONA",
    "MUSIC": "Music",
}


# No MyAnimeList, cada temporada é um anime separado, ligado aos outros por "relações".
# Só Prequel (a anterior) e Sequel (a seguinte) contam como temporadas; spin-offs,
# resumos e histórias paralelas ficam de fora.
RELACOES = {"Prequel": "anterior", "Sequel": "seguinte"}


class CatalogoIndisponivel(Exception):
    """A Jikan não respondeu direito. A mensagem explica o motivo."""


def ler_estreia(dados: dict) -> date | None:
    # A Jikan manda "2023-09-29T00:00:00+00:00"; só a data interessa.
    inicio = (dados.get("aired") or {}).get("from")
    return date.fromisoformat(inicio[:10]) if inicio else None


def ler_relacionados(dados: dict) -> list[Relacionado] | None:
    if "relations" not in dados:
        return None  # a resposta não diz nada sobre temporadas (não é o mesmo que "não tem")
    relacionados = []
    for grupo in dados.get("relations") or []:
        relacao = RELACOES.get(grupo["relation"])
        if relacao is None:
            continue
        for item in grupo["entry"]:
            if item["type"] == "anime":  # a relação também pode apontar para um mangá
                relacionados.append(
                    Relacionado(mal_id=item["mal_id"], titulo=item["name"], relacao=relacao)
                )
    return relacionados


def ler_anime(dados: dict) -> AnimeCatalogo:
    """Converte um anime no formato da Jikan (em inglês) para o nosso formato."""
    try:
        return AnimeCatalogo(
            mal_id=dados["mal_id"],
            titulo=dados["title"],
            titulo_ingles=dados.get("title_english"),
            total_episodios=dados.get("episodes"),
            imagem_url=dados.get("images", {}).get("jpg", {}).get("image_url"),
            ano=dados.get("year"),
            nota_mal=dados.get("score"),
            tipo=dados.get("type"),
            sinopse=dados.get("synopsis"),
            generos=[genero["name"] for genero in dados.get("genres", [])],
            estreia=ler_estreia(dados),
            relacionados=ler_relacionados(dados),
        )
    except (KeyError, TypeError, ValueError) as erro:
        raise CatalogoIndisponivel("A Jikan respondeu num formato inesperado.") from erro


def limpar_sinopse(texto: str | None) -> str | None:
    """A sinopse do AniList vem com tags (<br>, <i>) e entidades (&quot;): sobra só o texto."""
    if not texto:
        return None
    texto = re.sub(r"<br\s*/?>", "\n", texto)
    texto = html.unescape(re.sub(r"<[^>]+>", "", texto))
    return re.sub(r"\n{3,}", "\n\n", texto).strip() or None


def ler_estreia_anilist(inicio: dict | None) -> date | None:
    # O AniList manda a data em partes; sem o dia (estreia ainda não marcada), fica sem data.
    inicio = inicio or {}
    if not (inicio.get("year") and inicio.get("month") and inicio.get("day")):
        return None
    return date(inicio["year"], inicio["month"], inicio["day"])


def ler_anime_anilist(dados: dict) -> AnimeCatalogo | None:
    """Converte um anime do AniList para o nosso formato. None se ele não tiver ID do MyAnimeList
    (sem o ID, não dá para adicionar: a lista inteira se organiza por ele)."""
    try:
        if not dados.get("idMal"):
            return None
        titulos = dados.get("title") or {}
        return AnimeCatalogo(
            mal_id=dados["idMal"],
            titulo=titulos.get("romaji") or titulos["english"],
            titulo_ingles=titulos.get("english"),
            total_episodios=dados.get("episodes"),
            imagem_url=(dados.get("coverImage") or {}).get("large"),
            ano=dados.get("seasonYear"),
            # A nota do AniList não é a do MyAnimeList: fica vazia em vez de enganar.
            nota_mal=None,
            tipo=TIPOS_ANILIST.get(dados.get("format")),
            sinopse=limpar_sinopse(dados.get("description")),
            generos=dados.get("genres") or [],
            estreia=ler_estreia_anilist(dados.get("startDate")),
            fonte="anilist",
        )
    except (KeyError, TypeError, ValueError) as erro:
        raise CatalogoIndisponivel("O AniList respondeu num formato inesperado.") from erro


class Catalogo:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        # Nos testes, o transport é um httpx.MockTransport: nenhuma consulta vai à internet.
        self._transport = transport

    def _get(self, caminho: str, params: dict | None = None) -> httpx.Response:
        try:
            with httpx.Client(base_url=URL_JIKAN, timeout=10, transport=self._transport) as cliente:
                resposta = cliente.get(caminho, params=params)
        except httpx.TimeoutException as erro:
            raise CatalogoIndisponivel("A Jikan demorou demais para responder. Tente de novo.") from erro
        except httpx.HTTPError as erro:
            raise CatalogoIndisponivel("Não consegui acessar a Jikan. Confira a internet.") from erro

        if resposta.status_code == 429:
            raise CatalogoIndisponivel("Muitas consultas seguidas à Jikan. Espere alguns segundos.")
        if resposta.status_code >= 500:
            raise CatalogoIndisponivel(
                "O MyAnimeList está fora do ar para a Jikan agora. Tente mais tarde."
            )
        return resposta

    def buscar(self, termo: str, limite: int = 10) -> list[AnimeCatalogo]:
        """Procura animes pelo nome na Jikan e, se ela falhar, no AniList.

        Se os dois falharem, vale a mensagem da Jikan (é o catálogo principal).
        """
        try:
            return self._buscar_na_jikan(termo, limite)
        except CatalogoIndisponivel:
            try:
                return self._buscar_no_anilist(termo, limite)
            except CatalogoIndisponivel:
                pass
            raise  # o "raise" sozinho relança o erro da Jikan

    def _buscar_no_anilist(self, termo: str, limite: int) -> list[AnimeCatalogo]:
        try:
            with httpx.Client(timeout=10, transport=self._transport) as cliente:
                resposta = cliente.post(
                    URL_ANILIST,
                    json={"query": BUSCA_ANILIST, "variables": {"busca": termo, "limite": limite}},
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as erro:
            raise CatalogoIndisponivel("Não consegui acessar o AniList.") from erro
        if resposta.status_code != 200:
            raise CatalogoIndisponivel(f"O AniList recusou a busca (erro {resposta.status_code}).")
        try:
            itens = resposta.json()["data"]["Page"]["media"]
        except (ValueError, KeyError, TypeError) as erro:
            raise CatalogoIndisponivel("O AniList respondeu num formato inesperado.") from erro
        animes, vistos = [], set()
        for item in itens:
            anime = ler_anime_anilist(item)
            if anime is not None and anime.mal_id not in vistos:
                vistos.add(anime.mal_id)
                animes.append(anime)
        return animes

    def _buscar_na_jikan(self, termo: str, limite: int) -> list[AnimeCatalogo]:
        # O sfw esconde conteúdo adulto dos resultados.
        resposta = self._get("/anime", params={"q": termo, "limit": limite, "sfw": "true"})
        if resposta.status_code != 200:
            raise CatalogoIndisponivel(f"A Jikan recusou a busca (erro {resposta.status_code}).")
        try:
            itens = resposta.json()["data"]
        except (ValueError, KeyError) as erro:
            raise CatalogoIndisponivel("A Jikan respondeu num formato inesperado.") from erro

        # A Jikan às vezes repete o mesmo anime na busca; mostramos cada um só uma vez.
        animes, vistos = [], set()
        for item in itens:
            anime = ler_anime(item)
            if anime.mal_id not in vistos:
                vistos.add(anime.mal_id)
                animes.append(anime)
        return animes

    def detalhes(self, mal_id: int) -> AnimeCatalogo | None:
        """Busca um anime pelo ID do MyAnimeList. Devolve None se ele não existir.

        Tenta a versão /full, que já traz as relações (temporada anterior e seguinte).
        Com o MyAnimeList fora do ar, a Jikan só responde o /full se tiver uma cópia
        guardada; já o /anime/{id} simples ela quase sempre tem. Então, se o /full
        falhar, usa o simples: o anime vem sem as relações (relacionados = None).
        """
        try:
            resposta = self._get(f"/anime/{mal_id}/full")
        except CatalogoIndisponivel:
            resposta = self._get(f"/anime/{mal_id}")
        if resposta.status_code == 404:
            return None
        if resposta.status_code != 200:
            raise CatalogoIndisponivel(f"A Jikan recusou a consulta (erro {resposta.status_code}).")
        try:
            return ler_anime(resposta.json()["data"])
        except (ValueError, KeyError) as erro:
            raise CatalogoIndisponivel("A Jikan respondeu num formato inesperado.") from erro
