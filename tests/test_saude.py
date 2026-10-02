def test_saude_responde_ok(cliente):
    resposta = cliente.get("/saude")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_documentacao_automatica_existe(cliente):
    assert cliente.get("/docs").status_code == 200


def test_pagina_inicial_mostra_o_front(cliente):
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    assert "<title>Hanami</title>" in resposta.text


def test_arquivos_do_front_sao_servidos(cliente):
    css = cliente.get("/static/estilo.css")
    js = cliente.get("/static/app.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]


def test_front_nunca_usa_innerhtml(cliente):
    # Textos da API (títulos, sinopses) entram com textContent, que não executa HTML.
    # Isso evita XSS: um anime chamado "<script>..." não roda código na página.
    assert "innerHTML" not in cliente.get("/static/app.js").text


def test_front_manda_o_navegador_conferir_se_ha_versao_nova(cliente):
    for caminho in ("/", "/static/app.js", "/static/estilo.css"):
        assert cliente.get(caminho).headers["cache-control"] == "no-cache", caminho


def test_arquivo_sem_mudanca_responde_304(cliente):
    etag = cliente.get("/static/app.js").headers["etag"]

    assert cliente.get("/static/app.js", headers={"If-None-Match": etag}).status_code == 304


def test_respostas_da_api_nao_ganham_o_cabecalho_do_front(cliente):
    assert "cache-control" not in cliente.get("/animes").headers
