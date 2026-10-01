"""Rotas da API.

/animes: sua lista (criar, listar com filtros, ver, editar, apagar e estatísticas)
e os comentários de cada anime.
/catalogo: busca no catálogo da Jikan (MyAnimeList).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from lista_animes.banco import AnimeRepetido, Banco, EpisodioInvalido, LimiteExcedido
from lista_animes.catalogo import Catalogo, CatalogoIndisponivel
from lista_animes.modelos import (
    Anime,
    AnimeAtualizacao,
    AnimeCatalogo,
    AnimeNovo,
    Comentario,
    ComentarioNovo,
    Estatisticas,
    ListaExportada,
    Relacionado,
    ResultadoImportacao,
    Status,
)

roteador = APIRouter(prefix="/animes", tags=["animes"])
roteador_catalogo = APIRouter(prefix="/catalogo", tags=["catálogo"])

ERRO_CATALOGO = {503: {"description": "A Jikan (MyAnimeList) está fora do ar"}}

# Máximo de consultas extras à Jikan para completar temporadas antigas sem data
# (a Jikan aceita cerca de 3 consultas por segundo).
MAX_COMPLETAR = 3


def pegar_banco(request: Request) -> Banco:
    # O banco é guardado no app ao criá-lo (app.state.banco). O Depends entrega
    # ele para cada rota, e os testes podem trocar por um banco temporário.
    return request.app.state.banco


def pegar_catalogo(request: Request) -> Catalogo:
    return request.app.state.catalogo


def pegar_limite(request: Request) -> int | None:
    # Só existe na demonstração online (None = sem limite).
    return request.app.state.limite_animes


def pegar_limite_comentarios(request: Request) -> int | None:
    return request.app.state.limite_comentarios


def conferir_limite(banco: Banco, limite: int | None) -> None:
    if limite is not None and len(banco.listar()) >= limite:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"A demonstração aceita até {limite} animes. Remova algum para adicionar outro.",
        )


def catalogo_fora_do_ar(erro: CatalogoIndisponivel) -> HTTPException:
    # 503 = "serviço indisponível": o problema não é o pedido, é a Jikan.
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(erro))


def nao_encontrado(anime_id: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Anime {anime_id} não está na lista")


@roteador.post(
    "", status_code=status.HTTP_201_CREATED, responses={403: {"description": "Limite atingido"}}
)
def adicionar(
    novo: AnimeNovo,
    banco: Banco = Depends(pegar_banco),
    limite: int | None = Depends(pegar_limite),
) -> Anime:
    """Adiciona um anime à lista."""
    conferir_limite(banco, limite)
    return salvar(banco, novo)


def salvar(banco: Banco, novo: AnimeNovo, relacionados: list[int] | None = None) -> Anime:
    try:
        return banco.adicionar(novo, relacionados or [])
    except AnimeRepetido as erro:
        raise HTTPException(status.HTTP_409_CONFLICT, str(erro)) from erro


def consultar(
    catalogo: Catalogo, mal_id: int, consultados: dict[int, AnimeCatalogo | None]
) -> AnimeCatalogo | None:
    # Guarda as respostas durante o pedido: o mesmo anime não é consultado duas vezes.
    if mal_id not in consultados:
        consultados[mal_id] = catalogo.detalhes(mal_id)
    return consultados[mal_id]


def completar_datas(
    banco: Banco,
    catalogo: Catalogo,
    temporadas: list[Anime],
    consultados: dict[int, AnimeCatalogo | None],
) -> list[Anime]:
    """Busca tipo e estreia das temporadas salvas antes desses campos existirem.

    Sem a data, não dá para saber a ordem das temporadas. Se a Jikan falhar,
    segue sem ela: a ordem fica pior, mas nada quebra.
    """
    faltando = [a for a in temporadas if a.estreia is None and a.mal_id is not None]
    if not faltando:
        return temporadas
    for anime in faltando[:MAX_COMPLETAR]:
        try:
            encontrado = consultar(catalogo, anime.mal_id, consultados)
        except CatalogoIndisponivel:
            break
        if encontrado is not None:
            banco.completar(anime.id, encontrado.tipo, encontrado.estreia)
    return banco.franquia(temporadas[0].id) or temporadas


@roteador.get("")
def listar(
    status_anime: Status | None = Query(
        default=None, alias="status", description="Mostra só os animes com esse status"
    ),
    busca: str | None = Query(
        default=None, max_length=100, description="Parte do título (maiúsculas ou minúsculas)"
    ),
    banco: Banco = Depends(pegar_banco),
) -> list[Anime]:
    """Lista os animes, na ordem em que foram adicionados. Os filtros são opcionais."""
    return banco.listar(status=status_anime, busca=busca)


@roteador.post(
    "/do-catalogo/{mal_id}",
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Limite atingido"},
        404: {"description": "Anime não existe no MyAnimeList"},
        **ERRO_CATALOGO,
    },
)
def adicionar_do_catalogo(
    mal_id: int,
    status_anime: Status = Query(default=Status.QUERO_VER, alias="status"),
    banco: Banco = Depends(pegar_banco),
    catalogo: Catalogo = Depends(pegar_catalogo),
    limite: int | None = Depends(pegar_limite),
) -> Anime:
    """Adiciona um anime pelo ID do MyAnimeList: título, episódios e capa vêm da Jikan."""
    conferir_limite(banco, limite)  # antes de consultar a Jikan, para não gastar uma consulta
    try:
        encontrado = catalogo.detalhes(mal_id)
    except CatalogoIndisponivel as erro:
        raise catalogo_fora_do_ar(erro) from erro
    if encontrado is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Não existe anime {mal_id} no MyAnimeList")
    novo = AnimeNovo(
        titulo=encontrado.titulo,
        mal_id=encontrado.mal_id,
        total_episodios=encontrado.total_episodios or None,  # a Jikan pode mandar 0
        imagem_url=encontrado.imagem_url,
        status=status_anime,
        tipo=encontrado.tipo,
        estreia=encontrado.estreia,
    )
    # Se a temporada anterior ou a seguinte já estiver na lista, entra na mesma franquia.
    anime = salvar(banco, novo, [r.mal_id for r in encontrado.relacionados or []])
    temporadas = banco.franquia(anime.id) or []
    if len(temporadas) > 1:
        completar_datas(banco, catalogo, temporadas, {encontrado.mal_id: encontrado})
    return anime


# Esta rota precisa vir antes de /{anime_id}: as rotas são testadas na ordem,
# e "estatisticas" seria lido como um id (e recusado por não ser número).
# As duas rotas ficam antes de /{anime_id}: senão "exportar" seria lido como um id.
@roteador.get("/exportar", response_model=ListaExportada)
def exportar(banco: Banco = Depends(pegar_banco)) -> JSONResponse:
    """Baixa a lista inteira (com comentários e temporadas) num arquivo JSON de backup."""
    agora = datetime.now(timezone.utc)
    lista = ListaExportada(formato="lista-animes", exportado_em=agora, animes=banco.exportar())
    nome = f"lista-animes-{agora:%Y-%m-%d}.json"
    return JSONResponse(
        lista.model_dump(mode="json"),
        # "attachment" faz o navegador baixar o arquivo em vez de mostrar o JSON na tela.
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@roteador.post(
    "/importar",
    responses={
        403: {"description": "Limite da demonstração"},
        409: {"description": "Um anime do arquivo entrou na lista durante a importação"},
    },
)
def importar(
    lista: ListaExportada,
    banco: Banco = Depends(pegar_banco),
    limite: int | None = Depends(pegar_limite),
    limite_comentarios: int | None = Depends(pegar_limite_comentarios),
) -> ResultadoImportacao:
    """Junta à lista os animes de um arquivo de backup (feito pelo /animes/exportar).

    Animes que já estão na lista ficam como estão; os novos entram com os comentários
    e nas franquias certas. Se der algum problema, nada é importado.
    """
    try:
        return banco.importar(lista.animes, limite, limite_comentarios)
    except LimiteExcedido as erro:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(erro)) from erro
    except AnimeRepetido as erro:
        raise HTTPException(status.HTTP_409_CONFLICT, str(erro)) from erro


@roteador.get("/estatisticas")
def estatisticas(banco: Banco = Depends(pegar_banco)) -> Estatisticas:
    """Resumo da lista: quantos animes por status, episódios assistidos e nota média."""
    return banco.estatisticas()


@roteador.get("/{anime_id}", responses={404: {"description": "Anime não encontrado"}})
def ver(anime_id: int, banco: Banco = Depends(pegar_banco)) -> Anime:
    """Mostra um anime da lista."""
    anime = banco.buscar(anime_id)
    if anime is None:
        raise nao_encontrado(anime_id)
    return anime


@roteador.patch("/{anime_id}", responses={404: {"description": "Anime não encontrado"}})
def editar(
    anime_id: int, mudancas: AnimeAtualizacao, banco: Banco = Depends(pegar_banco)
) -> Anime:
    """Muda só os campos enviados (ex.: status e episódios vistos)."""
    try:
        anime = banco.atualizar(anime_id, mudancas)
    except ValidationError as erro:
        # A combinação final não é válida (ex.: 30 episódios vistos de um total de 28).
        detalhes = erro.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detalhes) from erro
    if anime is None:
        raise nao_encontrado(anime_id)
    return anime


@roteador.delete(
    "/{anime_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Anime não encontrado"}},
)
def apagar(anime_id: int, banco: Banco = Depends(pegar_banco)) -> Response:
    """Tira um anime da lista."""
    if not banco.remover(anime_id):
        raise nao_encontrado(anime_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@roteador.get(
    "/{anime_id}/outras-temporadas",
    responses={404: {"description": "Anime não encontrado"}, **ERRO_CATALOGO},
)
def outras_temporadas(
    anime_id: int,
    banco: Banco = Depends(pegar_banco),
    catalogo: Catalogo = Depends(pegar_catalogo),
) -> list[Relacionado]:
    """Temporadas da franquia que ainda não estão na lista (a anterior à primeira
    e a seguinte à última). Depois de adicionar uma, consulte de novo para achar a próxima.

    Se uma vizinha já estiver na lista mas separada (entrou com o MyAnimeList fora
    do ar, sem as relações), ela é juntada à franquia aqui."""
    temporadas = banco.franquia(anime_id)
    if temporadas is None:
        raise nao_encontrado(anime_id)
    consultados: dict[int, AnimeCatalogo | None] = {}
    temporadas = completar_datas(banco, catalogo, temporadas, consultados)
    # Só as pontas: a do meio já tem as vizinhas na lista.
    pontas = [a for a in (temporadas[0], temporadas[-1]) if a.mal_id is not None]
    na_lista = banco.mal_ids()
    faltando: dict[int, Relacionado] = {}
    try:
        for ponta in {a.mal_id: a for a in pontas}.values():
            encontrado = consultar(catalogo, ponta.mal_id, consultados)
            if encontrado is None:
                continue  # saiu do MyAnimeList
            if encontrado.relacionados is None:
                raise CatalogoIndisponivel(
                    "O MyAnimeList está fora do ar, e sem ele não dá para ver as temporadas. "
                    "Tente mais tarde."
                )
            banco.juntar(ponta.id, [r.mal_id for r in encontrado.relacionados])
            for relacionado in encontrado.relacionados:
                if relacionado.mal_id not in na_lista:
                    faltando.setdefault(relacionado.mal_id, relacionado)
    except CatalogoIndisponivel as erro:
        raise catalogo_fora_do_ar(erro) from erro
    return list(faltando.values())


@roteador.get("/{anime_id}/comentarios", responses={404: {"description": "Anime não encontrado"}})
def listar_comentarios(anime_id: int, banco: Banco = Depends(pegar_banco)) -> list[Comentario]:
    """Comentários do anime, do mais novo para o mais antigo."""
    comentarios = banco.listar_comentarios(anime_id)
    if comentarios is None:
        raise nao_encontrado(anime_id)
    return comentarios


@roteador.post(
    "/{anime_id}/comentarios",
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Limite atingido"},
        404: {"description": "Anime não encontrado"},
    },
)
def comentar(
    anime_id: int,
    novo: ComentarioNovo,
    banco: Banco = Depends(pegar_banco),
    limite: int | None = Depends(pegar_limite_comentarios),
) -> Comentario:
    """Escreve um comentário no anime (se quiser, dizendo o episódio)."""
    if limite is not None and banco.contar_comentarios() >= limite:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"A demonstração aceita até {limite} comentários. Apague algum para escrever outro.",
        )
    try:
        comentario = banco.comentar(anime_id, novo)
    except EpisodioInvalido as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(erro)) from erro
    if comentario is None:
        raise nao_encontrado(anime_id)
    return comentario


@roteador.delete(
    "/{anime_id}/comentarios/{comentario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Comentário não encontrado"}},
)
def apagar_comentario(
    anime_id: int, comentario_id: int, banco: Banco = Depends(pegar_banco)
) -> Response:
    """Apaga um comentário."""
    if not banco.apagar_comentario(anime_id, comentario_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Comentário {comentario_id} não existe no anime {anime_id}",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@roteador_catalogo.get("/busca", responses=ERRO_CATALOGO)
def buscar_no_catalogo(
    q: str = Query(min_length=2, max_length=100, description="Nome do anime, ex.: frieren"),
    limite: int = Query(default=10, ge=1, le=25),
    catalogo: Catalogo = Depends(pegar_catalogo),
) -> list[AnimeCatalogo]:
    """Procura animes no MyAnimeList pelo nome."""
    try:
        return catalogo.buscar(q.strip(), limite)
    except CatalogoIndisponivel as erro:
        raise catalogo_fora_do_ar(erro) from erro


@roteador_catalogo.get(
    "/{mal_id}", responses={404: {"description": "Anime não existe no MyAnimeList"}, **ERRO_CATALOGO}
)
def ver_no_catalogo(mal_id: int, catalogo: Catalogo = Depends(pegar_catalogo)) -> AnimeCatalogo:
    """Mostra os detalhes de um anime do MyAnimeList (sinopse, gêneros, nota...)."""
    try:
        anime = catalogo.detalhes(mal_id)
    except CatalogoIndisponivel as erro:
        raise catalogo_fora_do_ar(erro) from erro
    if anime is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Não existe anime {mal_id} no MyAnimeList")
    return anime
