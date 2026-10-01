"""Guarda a lista de animes num arquivo SQLite.

Usa o sqlite3 que já vem com o Python, com SQL escrito à mão, sem ORM.
Cada operação abre e fecha a própria conexão. O FastAPI atende pedidos
em threads diferentes, e uma conexão do sqlite3 não pode ser dividida entre elas.
"""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from lista_animes.modelos import (
    Anime,
    AnimeAtualizacao,
    AnimeExportado,
    AnimeNovo,
    Comentario,
    ComentarioExportado,
    ComentarioNovo,
    Estatisticas,
    ResultadoImportacao,
    Status,
)

CRIAR_TABELAS = [
    """
CREATE TABLE IF NOT EXISTS animes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo           TEXT    NOT NULL,
    mal_id           INTEGER UNIQUE,
    total_episodios  INTEGER,
    imagem_url       TEXT,
    status           TEXT    NOT NULL,
    episodios_vistos INTEGER NOT NULL DEFAULT 0,
    nota             INTEGER,
    criado_em        TEXT    NOT NULL,
    tipo             TEXT,
    estreia          TEXT,
    franquia         INTEGER
)
""",
    # ON DELETE CASCADE: quando um anime sai da lista, os comentários dele vão junto.
    """
CREATE TABLE IF NOT EXISTS comentarios (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id  INTEGER NOT NULL REFERENCES animes (id) ON DELETE CASCADE,
    texto     TEXT    NOT NULL,
    episodio  INTEGER,
    criado_em TEXT    NOT NULL
)
""",
    "CREATE INDEX IF NOT EXISTS comentarios_por_anime ON comentarios (anime_id)",
]

# Colunas que entraram depois da primeira versão. Bancos antigos ganham elas ao abrir.
COLUNAS_NOVAS = {"tipo": "TEXT", "estreia": "TEXT", "franquia": "INTEGER"}

# Cada anime vem com a contagem de comentários, calculada na hora pelo SQLite.
SELECIONAR_ANIMES = (
    "SELECT animes.*, "
    "(SELECT COUNT(*) FROM comentarios WHERE comentarios.anime_id = animes.id) AS comentarios "
    "FROM animes"
)

# Temporadas da mesma franquia ficam juntas: as franquias na ordem em que foram
# adicionadas e, dentro de cada uma, as temporadas pela data de estreia.
ORDEM_DA_LISTA = (
    "ORDER BY (SELECT MIN(outro.id) FROM animes AS outro WHERE outro.franquia = animes.franquia), "
    "animes.estreia IS NULL, animes.estreia, animes.id"
)


# Migrações: ajustes nos dados salvos por versões antigas, rodados ao abrir o banco.
MIGRACOES = [
    # Antes, imagem_url aceitava qualquer texto; agora só links http(s).
    # Sem isso, um único item antigo inválido derrubava a listagem inteira.
    "UPDATE animes SET imagem_url = NULL "
    "WHERE imagem_url NOT LIKE 'http://_%' AND imagem_url NOT LIKE 'https://_%'",
    # Antes não havia franquias: cada anime antigo vira uma franquia sozinho.
    "UPDATE animes SET franquia = id WHERE franquia IS NULL",
    "CREATE INDEX IF NOT EXISTS animes_por_franquia ON animes (franquia)",
]


def utc(momento: datetime) -> str:
    """A data em UTC, no formato que o banco usa: "2026-09-30T22:15:00+00:00"."""
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


class AnimeRepetido(Exception):
    """O anime (mesmo mal_id) já está na lista."""


class EpisodioInvalido(Exception):
    """O comentário cita um episódio que o anime não tem."""


class LimiteExcedido(Exception):
    """A importação passaria do limite de animes ou de comentários (demonstração online)."""


class Banco:
    def __init__(self, caminho: Path | str) -> None:
        self.caminho = Path(caminho)
        with self._conectar() as conexao:
            for comando in CRIAR_TABELAS:
                conexao.execute(comando)
            existentes = {linha["name"] for linha in conexao.execute("PRAGMA table_info(animes)")}
            for coluna, tipo in COLUNAS_NOVAS.items():
                if coluna not in existentes:
                    conexao.execute(f"ALTER TABLE animes ADD COLUMN {coluna} {tipo}")
            for migracao in MIGRACOES:
                conexao.execute(migracao)

    @contextmanager
    def _conectar(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.caminho)) as conexao:
            conexao.row_factory = sqlite3.Row  # linhas acessíveis por nome: linha["titulo"]
            # O SQLite só respeita o REFERENCES (e o ON DELETE CASCADE) com isto ligado,
            # e precisa ser ligado em cada conexão.
            conexao.execute("PRAGMA foreign_keys = ON")
            with conexao:  # confirma (commit) no final, ou desfaz tudo se der erro
                yield conexao

    def adicionar(self, novo: AnimeNovo, relacionados: Iterable[int] = ()) -> Anime:
        """Salva o anime. relacionados são os mal_id da temporada anterior e da seguinte:
        se alguma delas já estiver na lista, o anime entra na franquia dela."""
        dados = novo.model_dump(mode="json")
        dados["criado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        colunas = ", ".join(dados)
        marcadores = ", ".join(f":{coluna}" for coluna in dados)
        relacionados = list(relacionados)
        try:
            # Tudo numa transação só: o anime nunca fica salvo sem franquia.
            with self._conectar() as conexao:
                # Os valores vão por marcadores (:titulo), nunca colados no texto do SQL.
                # Isso evita SQL injection.
                cursor = conexao.execute(
                    f"INSERT INTO animes ({colunas}) VALUES ({marcadores})", dados
                )
                anime_id = cursor.lastrowid
                franquia = self._juntar_franquias(conexao, anime_id, relacionados)
        except sqlite3.IntegrityError as erro:
            raise AnimeRepetido(f"O anime com mal_id {novo.mal_id} já está na lista") from erro
        return Anime(id=anime_id, franquia=franquia, **dados)

    @staticmethod
    def _juntar_franquias(conexao: sqlite3.Connection, anime_id: int, relacionados: list[int]) -> int:
        marcadores = ", ".join("?" * len(relacionados))
        # A franquia do próprio anime (se já tiver) e as das temporadas vizinhas na lista.
        franquias = [
            linha[0]
            for linha in conexao.execute(
                f"SELECT DISTINCT franquia FROM animes WHERE id = ? OR mal_id IN ({marcadores})",
                [anime_id, *relacionados],
            )
            if linha[0] is not None
        ]
        # Sem parentes na lista, o anime começa uma franquia nova (com o próprio id).
        # Se ele liga duas franquias (tinha a 1ª e a 3ª temporada e chegou a 2ª),
        # as duas viram uma só.
        franquia = min(franquias, default=anime_id)
        marcadores = ", ".join("?" * len(franquias))
        conexao.execute(
            f"UPDATE animes SET franquia = ? WHERE id = ? OR franquia IN ({marcadores})",
            [franquia, anime_id, *franquias],
        )
        return franquia

    def listar(self, status: Status | None = None, busca: str | None = None) -> list[Anime]:
        # Monta o WHERE só com os filtros que foram pedidos.
        condicoes, valores = [], []
        if status is not None:
            condicoes.append("status = ?")
            valores.append(status.value)
        if busca and busca.strip():
            # No LIKE, % e _ são curingas. Escapamos para que "100%" busque o texto "100%".
            termo = busca.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            condicoes.append("titulo LIKE ? ESCAPE '\\'")
            valores.append(f"%{termo}%")
        where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
        with self._conectar() as conexao:
            linhas = conexao.execute(
                f"{SELECIONAR_ANIMES} {where} {ORDEM_DA_LISTA}", valores
            ).fetchall()
        return [Anime(**linha) for linha in linhas]

    def estatisticas(self) -> Estatisticas:
        with self._conectar() as conexao:
            contagem = dict(
                conexao.execute("SELECT status, COUNT(*) FROM animes GROUP BY status").fetchall()
            )
            # COUNT(nota) conta só as linhas que têm nota (ignora NULL).
            episodios, com_nota, soma_notas = conexao.execute(
                "SELECT COALESCE(SUM(episodios_vistos), 0), COUNT(nota), COALESCE(SUM(nota), 0) "
                "FROM animes"
            ).fetchone()
        nota_media = None
        if com_nota:
            # Decimal com ROUND_HALF_UP: 8.25 vira 8.3, como aprendemos na escola.
            media = (Decimal(soma_notas) / com_nota).quantize(Decimal("0.1"), ROUND_HALF_UP)
            nota_media = float(media)
        return Estatisticas(
            total=sum(contagem.values()),
            por_status={s: contagem.get(s.value, 0) for s in Status},
            episodios_assistidos=episodios,
            nota_media=nota_media,
        )

    def buscar(self, anime_id: int) -> Anime | None:
        with self._conectar() as conexao:
            linha = conexao.execute(
                f"{SELECIONAR_ANIMES} WHERE id = ?", (anime_id,)
            ).fetchone()
        return Anime(**linha) if linha else None

    def atualizar(self, anime_id: int, mudancas: AnimeAtualizacao) -> Anime | None:
        atual = self.buscar(anime_id)
        if atual is None:
            return None
        # Junta o que já existe com o que mudou e valida o resultado inteiro de novo.
        # Assim a regra "vistos <= total" também vale para atualizações parciais.
        alterados = mudancas.model_dump(exclude_unset=True)
        atualizado = Anime.model_validate({**atual.model_dump(), **alterados})
        if alterados:
            dados = atualizado.model_dump(mode="json", include=set(alterados))
            atribuicoes = ", ".join(f"{campo} = :{campo}" for campo in dados)
            with self._conectar() as conexao:
                conexao.execute(
                    f"UPDATE animes SET {atribuicoes} WHERE id = :id", {**dados, "id": anime_id}
                )
        return atualizado

    def franquia(self, anime_id: int) -> list[Anime] | None:
        """Todas as temporadas da franquia do anime, em ordem. None se o anime não existe."""
        anime = self.buscar(anime_id)
        if anime is None:
            return None
        with self._conectar() as conexao:
            linhas = conexao.execute(
                f"{SELECIONAR_ANIMES} WHERE franquia = ? {ORDEM_DA_LISTA}", (anime.franquia,)
            ).fetchall()
        return [Anime(**linha) for linha in linhas]

    def juntar(self, anime_id: int, relacionados: Iterable[int]) -> None:
        """Junta à franquia do anime as temporadas vizinhas que já estão na lista
        (para animes que entraram sem as relações, com o MyAnimeList fora do ar)."""
        with self._conectar() as conexao:
            self._juntar_franquias(conexao, anime_id, list(relacionados))

    def mal_ids(self) -> set[int]:
        with self._conectar() as conexao:
            linhas = conexao.execute("SELECT mal_id FROM animes WHERE mal_id IS NOT NULL")
            return {linha[0] for linha in linhas}

    def completar(self, anime_id: int, tipo: str | None, estreia: date | None) -> None:
        """Preenche tipo e estreia de animes salvos antes de existirem esses campos."""
        with self._conectar() as conexao:
            conexao.execute(
                "UPDATE animes SET tipo = COALESCE(tipo, ?), estreia = COALESCE(estreia, ?) "
                "WHERE id = ?",
                (tipo, estreia.isoformat() if estreia else None, anime_id),
            )

    def remover(self, anime_id: int) -> bool:
        with self._conectar() as conexao:
            cursor = conexao.execute("DELETE FROM animes WHERE id = ?", (anime_id,))
        return cursor.rowcount > 0

    def listar_comentarios(self, anime_id: int) -> list[Comentario] | None:
        """Comentários do anime, do mais novo para o mais antigo. None se o anime não existe."""
        with self._conectar() as conexao:
            if conexao.execute("SELECT 1 FROM animes WHERE id = ?", (anime_id,)).fetchone() is None:
                return None
            linhas = conexao.execute(
                "SELECT * FROM comentarios WHERE anime_id = ? ORDER BY id DESC", (anime_id,)
            ).fetchall()
        return [Comentario(**linha) for linha in linhas]

    def comentar(self, anime_id: int, novo: ComentarioNovo) -> Comentario | None:
        """Salva um comentário no anime. None se o anime não existe."""
        with self._conectar() as conexao:
            anime = conexao.execute(
                "SELECT total_episodios FROM animes WHERE id = ?", (anime_id,)
            ).fetchone()
            if anime is None:
                return None
            total = anime["total_episodios"]
            if novo.episodio is not None and total is not None and novo.episodio > total:
                raise EpisodioInvalido(f"Esse anime tem só {total} episódios")
            dados = {
                **novo.model_dump(),
                "anime_id": anime_id,
                "criado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            cursor = conexao.execute(
                "INSERT INTO comentarios (anime_id, texto, episodio, criado_em) "
                "VALUES (:anime_id, :texto, :episodio, :criado_em)",
                dados,
            )
        return Comentario(id=cursor.lastrowid, **dados)

    def apagar_comentario(self, anime_id: int, comentario_id: int) -> bool:
        with self._conectar() as conexao:
            # Confere o anime também: não dá para apagar o comentário de outro anime pelo link errado.
            cursor = conexao.execute(
                "DELETE FROM comentarios WHERE id = ? AND anime_id = ?", (comentario_id, anime_id)
            )
        return cursor.rowcount > 0

    def contar_comentarios(self) -> int:
        with self._conectar() as conexao:
            return conexao.execute("SELECT COUNT(*) FROM comentarios").fetchone()[0]

    def exportar(self) -> list[AnimeExportado]:
        """A lista inteira, na ordem da tela, com os comentários de cada anime."""
        animes = self.listar()
        with self._conectar() as conexao:
            linhas = conexao.execute(
                "SELECT anime_id, texto, episodio, criado_em FROM comentarios ORDER BY id"
            ).fetchall()
        por_anime: dict[int, list[ComentarioExportado]] = {}
        for linha in linhas:
            por_anime.setdefault(linha["anime_id"], []).append(
                ComentarioExportado(
                    texto=linha["texto"], episodio=linha["episodio"], criado_em=linha["criado_em"]
                )
            )
        return [
            AnimeExportado(
                **anime.model_dump(exclude={"id", "comentarios"}),
                comentarios=por_anime.get(anime.id, []),
            )
            for anime in animes
        ]

    def importar(
        self,
        animes: list[AnimeExportado],
        limite_animes: int | None = None,
        limite_comentarios: int | None = None,
    ) -> ResultadoImportacao:
        """Junta à lista os animes do arquivo que ainda não estão nela (pelo mal_id ou, sem ele,
        pelo título), com os comentários e as franquias. O que já está na lista fica como está.

        Tudo numa transação: se passar do limite, nada é importado.
        """
        # Arquivo maior que o limite já é recusado antes de inserir qualquer coisa.
        # Mesmo com repetidos, o total depois é conferido de novo, dentro da transação.
        if limite_animes is not None and len(animes) > limite_animes:
            raise LimiteExcedido(f"A demonstração aceita até {limite_animes} animes.")
        if limite_comentarios is not None:
            if sum(len(anime.comentarios) for anime in animes) > limite_comentarios:
                raise LimiteExcedido(
                    f"A demonstração aceita até {limite_comentarios} comentários."
                )
        try:
            return self._importar(animes, limite_animes, limite_comentarios)
        except sqlite3.IntegrityError as erro:
            # Ex.: o mesmo anime adicionado em outra aba no meio da importação.
            raise AnimeRepetido("Um anime do arquivo entrou na lista agora há pouco. "
                                "Importe de novo.") from erro

    def _importar(
        self,
        animes: list[AnimeExportado],
        limite_animes: int | None,
        limite_comentarios: int | None,
    ) -> ResultadoImportacao:
        importados = repetidos = comentarios = 0
        with self._conectar() as conexao:
            franquia_do_mal_id = dict(
                conexao.execute(
                    "SELECT mal_id, franquia FROM animes WHERE mal_id IS NOT NULL"
                ).fetchall()
            )
            franquia_do_titulo = {
                titulo.casefold(): franquia
                for titulo, franquia in conexao.execute(
                    "SELECT titulo, franquia FROM animes WHERE mal_id IS NULL"
                )
            }
            # Franquia do arquivo -> franquia no banco. Se uma temporada já está na lista,
            # as outras da mesma franquia entram junto dela.
            franquias: dict[int, int] = {}
            for anime in animes:
                if anime.mal_id in franquia_do_mal_id:
                    franquias.setdefault(anime.franquia, franquia_do_mal_id[anime.mal_id])

            for anime in animes:
                if anime.mal_id is not None:
                    franquia_existente = franquia_do_mal_id.get(anime.mal_id)
                else:
                    franquia_existente = franquia_do_titulo.get(anime.titulo.casefold())
                if franquia_existente is not None:
                    repetidos += 1
                    # As outras temporadas da mesma franquia do arquivo vão para junto dele.
                    franquias.setdefault(anime.franquia, franquia_existente)
                    continue
                dados = anime.model_dump(mode="json", exclude={"comentarios"})
                # Sempre em UTC e no mesmo formato do adicionar() ("...+00:00").
                dados["criado_em"] = utc(anime.criado_em)
                dados["franquia"] = franquias.get(anime.franquia)
                colunas = ", ".join(dados)
                marcadores = ", ".join(f":{coluna}" for coluna in dados)
                anime_id = conexao.execute(
                    f"INSERT INTO animes ({colunas}) VALUES ({marcadores})", dados
                ).lastrowid
                if dados["franquia"] is None:
                    # Primeiro anime da franquia: ela ganha o número dele, como no adicionar().
                    franquias[anime.franquia] = anime_id
                    conexao.execute(
                        "UPDATE animes SET franquia = ? WHERE id = ?", (anime_id, anime_id)
                    )
                # O mesmo anime duas vezes no arquivo entra uma vez só.
                if anime.mal_id is not None:
                    franquia_do_mal_id[anime.mal_id] = franquias[anime.franquia]
                else:
                    franquia_do_titulo[anime.titulo.casefold()] = franquias[anime.franquia]
                for comentario in anime.comentarios:
                    conexao.execute(
                        "INSERT INTO comentarios (anime_id, texto, episodio, criado_em) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            anime_id,
                            comentario.texto,
                            comentario.episodio,
                            utc(comentario.criado_em),
                        ),
                    )
                importados += 1
                comentarios += len(anime.comentarios)

            total_animes = conexao.execute("SELECT COUNT(*) FROM animes").fetchone()[0]
            total_comentarios = conexao.execute("SELECT COUNT(*) FROM comentarios").fetchone()[0]
            # A exceção sai de dentro do "with": a transação é desfeita e nada fica salvo.
            if limite_animes is not None and total_animes > limite_animes:
                raise LimiteExcedido(
                    f"A demonstração aceita até {limite_animes} animes; "
                    f"com este arquivo seriam {total_animes}."
                )
            if limite_comentarios is not None and total_comentarios > limite_comentarios:
                raise LimiteExcedido(
                    f"A demonstração aceita até {limite_comentarios} comentários; "
                    f"com este arquivo seriam {total_comentarios}."
                )
        return ResultadoImportacao(
            importados=importados, repetidos=repetidos, comentarios=comentarios
        )
