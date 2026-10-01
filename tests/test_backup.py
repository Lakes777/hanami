"""Exportar a lista num arquivo JSON e importar de volta (backup)."""

import pytest
from fastapi.testclient import TestClient

from lista_animes.app import criar_app

FRIEREN = {"titulo": "Sousou no Frieren", "mal_id": 52991, "total_episodios": 28}
FRIEREN_2 = {"titulo": "Sousou no Frieren 2nd Season", "mal_id": 59978, "total_episodios": 10}
BEBOP = {"titulo": "Cowboy Bebop", "mal_id": 1, "total_episodios": 26}
# Fora da lista de exemplo da demonstração (que já tem o Frieren e o Cowboy Bebop).
NOVO_A = {"titulo": "Anime de Teste A", "mal_id": 900001, "total_episodios": 12}
NOVO_B = {"titulo": "Anime de Teste B", "mal_id": 900002, "total_episodios": 12}
COMENTARIO = {"texto": "oi", "criado_em": "2026-09-01T12:00:00+00:00"}


def adicionar(cliente, dados):
    resposta = cliente.post("/animes", json=dados)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def item(dados, franquia, **extras):
    """Um anime como aparece no arquivo de backup."""
    return {"criado_em": "2026-09-01T12:00:00+00:00", "franquia": franquia, **dados, **extras}


def arquivo(*animes):
    return {"formato": "lista-animes", "versao": 1, "animes": list(animes)}


@pytest.fixture
def outro_cliente(tmp_path, catalogo):
    # Uma segunda API, com outro banco: o "computador novo" para onde o backup vai.
    return TestClient(criar_app(tmp_path / "outro.db", catalogo))


def test_exportar_lista_vazia(cliente):
    resposta = cliente.get("/animes/exportar")

    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["formato"] == "lista-animes"
    assert dados["versao"] == 1
    assert dados["animes"] == []


def test_exportar_baixa_como_arquivo_com_a_data(cliente):
    disposicao = cliente.get("/animes/exportar").headers["content-disposition"]

    assert disposicao.startswith('attachment; filename="lista-animes-')
    assert disposicao.endswith('.json"')


def test_exportar_leva_progresso_comentarios_e_franquia(cliente):
    frieren = adicionar(
        cliente, {**FRIEREN, "status": "assistindo", "episodios_vistos": 19, "nota": 10}
    )
    cliente.post(
        f"/animes/{frieren['id']}/comentarios", json={"texto": "Que episódio!", "episodio": 10}
    )

    [anime] = cliente.get("/animes/exportar").json()["animes"]

    assert anime["titulo"] == "Sousou no Frieren"
    assert anime["episodios_vistos"] == 19
    assert anime["nota"] == 10
    assert anime["franquia"] == frieren["franquia"]
    assert [(c["texto"], c["episodio"]) for c in anime["comentarios"]] == [("Que episódio!", 10)]
    assert "id" not in anime  # ids mudam de um banco para outro


def test_backup_vai_e_volta_igual(cliente, outro_cliente):
    frieren = adicionar(cliente, {**FRIEREN, "status": "assistindo", "episodios_vistos": 19})
    cliente.post("/animes", json=FRIEREN_2)
    # Junta as temporadas como o app faz quando a Jikan diz que uma vem depois da outra.
    cliente.app.state.banco.juntar(frieren["id"], [FRIEREN_2["mal_id"]])
    adicionar(cliente, BEBOP)
    cliente.post(
        f"/animes/{frieren['id']}/comentarios", json={"texto": "Que episódio!", "episodio": 10}
    )
    backup = cliente.get("/animes/exportar").json()

    resposta = outro_cliente.post("/animes/importar", json=backup)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {"importados": 3, "repetidos": 0, "comentarios": 1}
    animes = outro_cliente.get("/animes").json()
    titulos = [FRIEREN["titulo"], FRIEREN_2["titulo"], BEBOP["titulo"]]
    assert [a["titulo"] for a in animes] == titulos
    frieren_novo, frieren_2_novo, bebop_novo = animes
    assert frieren_novo["franquia"] == frieren_2_novo["franquia"] != bebop_novo["franquia"]
    assert frieren_novo["episodios_vistos"] == 19
    assert frieren_novo["comentarios"] == 1
    # A data em que o anime entrou na lista é a do backup, não a da importação.
    originais = cliente.get("/animes").json()
    assert [a["criado_em"] for a in animes] == [a["criado_em"] for a in originais]


def test_importar_de_novo_nao_duplica(cliente):
    adicionar(cliente, FRIEREN)
    backup = cliente.get("/animes/exportar").json()

    resposta = cliente.post("/animes/importar", json=backup)

    assert resposta.json() == {"importados": 0, "repetidos": 1, "comentarios": 0}
    assert len(cliente.get("/animes").json()) == 1


def test_anime_que_ja_esta_na_lista_fica_como_esta(cliente):
    adicionar(cliente, {**FRIEREN, "episodios_vistos": 5})

    cliente.post("/animes/importar", json=arquivo(item(FRIEREN, 1, episodios_vistos=20)))

    assert cliente.get("/animes").json()[0]["episodios_vistos"] == 5


def test_temporada_nova_entra_na_franquia_que_ja_esta_na_lista(cliente):
    frieren = adicionar(cliente, FRIEREN)

    cliente.post("/animes/importar", json=arquivo(item(FRIEREN, 7), item(FRIEREN_2, 7)))

    franquias = {a["titulo"]: a["franquia"] for a in cliente.get("/animes").json()}
    assert franquias[FRIEREN_2["titulo"]] == frieren["franquia"]


def test_anime_sem_mal_id_repetido_pelo_titulo(cliente):
    adicionar(cliente, {"titulo": "Meu Anime Caseiro"})

    caseiro = item({"titulo": "meu anime caseiro"}, 1)
    resposta = cliente.post("/animes/importar", json=arquivo(caseiro))

    assert resposta.json()["repetidos"] == 1


def test_mesmo_anime_duas_vezes_no_arquivo_entra_uma_vez(cliente):
    resposta = cliente.post("/animes/importar", json=arquivo(item(FRIEREN, 1), item(FRIEREN, 2)))

    assert resposta.json() == {"importados": 1, "repetidos": 1, "comentarios": 0}


@pytest.mark.parametrize(
    "conteudo",
    [
        {"formato": "outra-coisa", "animes": []},
        {"animes": []},
        arquivo(item(FRIEREN, 1, episodios_vistos=99)),  # mais episódios vistos que o total
        # comentário de um episódio que o anime não tem
        arquivo(item(FRIEREN, 1, comentarios=[{**COMENTARIO, "episodio": 50}])),
        arquivo(item(FRIEREN, 1, nota=11)),
    ],
)
def test_arquivo_invalido_e_recusado_sem_importar_nada(cliente, conteudo):
    resposta = cliente.post("/animes/importar", json=conteudo)

    assert resposta.status_code == 422
    assert cliente.get("/animes").json() == []


def test_demo_recusa_importar_alem_do_limite_e_nao_importa_nada(tmp_path, catalogo):
    cliente_demo = TestClient(criar_app(tmp_path / "demo.db", catalogo, demo=True))
    antes = cliente_demo.get("/animes").json()
    cliente_demo.app.state.limite_animes = len(antes) + 1  # cabe só mais um

    resposta = cliente_demo.post("/animes/importar", json=arquivo(item(NOVO_A, 1), item(NOVO_B, 2)))

    assert resposta.status_code == 403
    assert "até" in resposta.json()["detail"]
    assert cliente_demo.get("/animes").json() == antes


def test_demo_recusa_importar_alem_do_limite_de_comentarios(tmp_path, catalogo):
    cliente_demo = TestClient(criar_app(tmp_path / "demo.db", catalogo, demo=True))
    cliente_demo.app.state.limite_comentarios = cliente_demo.app.state.banco.contar_comentarios()

    resposta = cliente_demo.post(
        "/animes/importar", json=arquivo(item(NOVO_A, 1, comentarios=[COMENTARIO]))
    )

    assert resposta.status_code == 403
    assert "comentários" in resposta.json()["detail"]
