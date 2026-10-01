"""Formatos dos dados: o que a API recebe e o que ela devolve.

O Pydantic valida tudo sozinho. Se chegar uma nota 11 ou um título vazio,
a API recusa antes de qualquer coisa ser salva no banco.
"""

from datetime import date, datetime
from typing import Literal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Só aceita links web (a capa do anime vem da Jikan, ex.: https://cdn.myanimelist.net/...).
PADRAO_URL = r"^https?://\S+$"


class Status(str, Enum):
    QUERO_VER = "quero_ver"
    ASSISTINDO = "assistindo"
    CONCLUIDO = "concluido"
    ABANDONADO = "abandonado"


class AnimeNovo(BaseModel):
    """Dados para adicionar um anime à lista."""

    # O exemplo aparece já preenchido no "Try it out" da página /docs.
    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "titulo": "Sousou no Frieren",
                    "mal_id": 52991,
                    "total_episodios": 28,
                    "imagem_url": "https://cdn.myanimelist.net/images/anime/1015/138006.jpg",
                    "status": "assistindo",
                    "episodios_vistos": 12,
                    "nota": 10,
                }
            ]
        },
    )

    titulo: str = Field(min_length=1, max_length=200)
    mal_id: int | None = Field(default=None, gt=0, description="ID do anime no MyAnimeList")
    total_episodios: int | None = Field(default=None, ge=1)
    imagem_url: str | None = Field(default=None, pattern=PADRAO_URL)
    status: Status = Status.QUERO_VER
    episodios_vistos: int = Field(default=0, ge=0)
    nota: int | None = Field(default=None, ge=1, le=10, description="De 1 a 10, como no MyAnimeList")
    tipo: str | None = Field(default=None, max_length=20, description="TV, Movie, OVA...")
    estreia: date | None = Field(default=None, description="Data de estreia (ordena as temporadas)")

    @model_validator(mode="after")
    def vistos_cabem_no_total(self) -> "AnimeNovo":
        if self.total_episodios is not None and self.episodios_vistos > self.total_episodios:
            raise ValueError(
                f"episodios_vistos ({self.episodios_vistos}) passa do total "
                f"de episódios ({self.total_episodios})"
            )
        return self


class AnimeAtualizacao(BaseModel):
    """Campos que podem mudar depois. Só os que forem enviados são alterados."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"status": "concluido", "episodios_vistos": 28, "nota": 10}]},
    )

    titulo: str | None = Field(default=None, min_length=1, max_length=200)
    total_episodios: int | None = Field(default=None, ge=1)
    imagem_url: str | None = Field(default=None, pattern=PADRAO_URL)
    status: Status | None = None
    episodios_vistos: int | None = Field(default=None, ge=0)
    nota: int | None = Field(default=None, ge=1, le=10)


class Anime(AnimeNovo):
    """Um anime já salvo na lista."""

    id: int
    criado_em: datetime
    franquia: int = Field(
        description="Animes com o mesmo número são temporadas (ou filmes) da mesma história"
    )
    comentarios: int = Field(default=0, description="Quantos comentários o anime tem")


class ComentarioNovo(BaseModel):
    """Uma anotação sua sobre o anime, se quiser ligada a um episódio."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"texto": "A luta desse episódio foi incrível", "episodio": 7}]},
    )

    texto: str = Field(min_length=1, max_length=1000)
    episodio: int | None = Field(default=None, ge=1, description="Episódio comentado (opcional)")


class Comentario(ComentarioNovo):
    """Um comentário já salvo."""

    id: int
    anime_id: int
    criado_em: datetime


class Estatisticas(BaseModel):
    """Resumo da lista inteira."""

    total: int
    por_status: dict[Status, int]
    episodios_assistidos: int
    nota_media: float | None = Field(description="Média das notas dadas, com 1 casa decimal")


class Relacionado(BaseModel):
    """A temporada (ou filme) que vem antes ou depois de um anime no MyAnimeList."""

    mal_id: int
    titulo: str
    relacao: Literal["anterior", "seguinte"]


class AnimeCatalogo(BaseModel):
    """Um anime do catálogo da Jikan (MyAnimeList), ainda fora da sua lista."""

    mal_id: int
    titulo: str
    titulo_ingles: str | None = None
    total_episodios: int | None = None
    imagem_url: str | None = None
    ano: int | None = None
    nota_mal: float | None = Field(default=None, description="Nota média no MyAnimeList")
    tipo: str | None = Field(default=None, description="TV, Movie, OVA...")
    sinopse: str | None = None
    generos: list[str] = []
    estreia: date | None = None
    relacionados: list[Relacionado] | None = Field(
        default=None,
        description="Temporada anterior e seguinte. None quando não deu para saber "
        "(a busca não traz, e o MyAnimeList pode estar fora do ar)",
    )
    fonte: Literal["jikan", "anilist"] = Field(
        default="jikan",
        description='De onde veio: "anilist" quando a busca da Jikan falhou e o AniList respondeu',
    )


# ---------- Exportar e importar (backup da lista num arquivo JSON) ----------


class ComentarioExportado(ComentarioNovo):
    """Um comentário dentro do arquivo de backup (sem ids, que mudam de um banco para outro)."""

    criado_em: datetime


class AnimeExportado(AnimeNovo):
    """Um anime dentro do arquivo de backup, com os comentários dele."""

    criado_em: datetime
    franquia: int = Field(
        description="Animes com o mesmo número no arquivo são da mesma franquia "
        "(o número muda ao importar)"
    )
    comentarios: list[ComentarioExportado] = Field(default=[], max_length=1000)

    @model_validator(mode="after")
    def episodios_dos_comentarios_existem(self) -> "AnimeExportado":
        for comentario in self.comentarios:
            total = self.total_episodios
            episodio = comentario.episodio
            if episodio is not None and total is not None and episodio > total:
                raise ValueError(
                    f'um comentário de "{self.titulo}" cita o episódio {episodio}, '
                    f"mas o anime tem só {total}"
                )
        return self


class ListaExportada(BaseModel):
    """O arquivo de backup: a lista inteira, com comentários e franquias."""

    formato: Literal["lista-animes"] = Field(description='Sempre "lista-animes"')
    versao: Literal[1] = 1
    exportado_em: datetime | None = None
    animes: list[AnimeExportado] = Field(max_length=5000)


class ResultadoImportacao(BaseModel):
    importados: int = Field(description="Animes novos que entraram na lista")
    repetidos: int = Field(
        description="Animes do arquivo que já estavam na lista (ficaram como estavam)"
    )
    comentarios: int = Field(description="Comentários que vieram junto com os animes novos")
