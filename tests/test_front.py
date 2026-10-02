"""Confere a marcação do front: os cartões leves, a janela de edição e a acessibilidade.

Os testes leem o index.html servido pela API e procuram os elementos dentro de cada
<template>, sem navegador. O comportamento (cliques) é conferido à mão com os prints.
"""

import re
from html.parser import HTMLParser

import pytest


class Elementos(HTMLParser):
    """Guarda cada tag aberta com os atributos e o id do <template> ou <dialog> onde ela está."""

    def __init__(self) -> None:
        super().__init__()
        self.elementos: list[tuple[str, dict, str | None]] = []
        self.dentro: list[str | None] = []

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        onde = next((d for d in reversed(self.dentro) if d), None)
        self.elementos.append((tag, atributos, onde))
        if tag in {"template", "dialog"}:
            self.dentro.append(atributos.get("id"))

    def handle_endtag(self, tag):
        if tag in {"template", "dialog"} and self.dentro:
            self.dentro.pop()


@pytest.fixture
def pagina(cliente):
    leitor = Elementos()
    leitor.feed(cliente.get("/").text)
    return leitor.elementos


@pytest.fixture
def app_js(cliente):
    return cliente.get("/static/app.js").text


@pytest.fixture
def estilo(cliente):
    return cliente.get("/static/estilo.css").text


def em(pagina, onde):
    return [(tag, atributos) for tag, atributos, lugar in pagina if lugar == onde]


def test_cartao_mantem_todas_as_acoes(pagina):
    """O cartão ficou mais leve, mas nenhuma função sumiu."""
    acoes = {a.get("data-acao") for _, a in em(pagina, "molde-anime")}
    assert {"detalhes", "mais1", "comentarios", "editar", "temporadas", "remover"} <= acoes
    campos = {a.get("data-campo") for _, a in em(pagina, "molde-anime")}
    assert "status" in campos


def test_cartao_mostra_so_o_principal(pagina):
    """Nota e episódio exato saíram do cartão: ficam na janela Editar."""
    campos = {a.get("data-campo") for _, a in em(pagina, "molde-anime")}
    assert "nota" not in campos
    assert "vistos" not in campos
    assert not [a for t, a in em(pagina, "molde-anime") if t == "input"]


def test_acoes_secundarias_sao_botoes_de_icone(pagina):
    icones = {
        a["data-acao"]
        for t, a in em(pagina, "molde-anime")
        if t == "button" and "botao-icone" in a.get("class", "")
    }
    assert icones == {"comentarios", "editar", "temporadas", "remover"}


def test_botoes_de_icone_recebem_nome_acessivel(app_js):
    """Sem texto visível, cada botão de ícone precisa de aria-label (posto pelo app.js)."""
    funcao = re.search(r"function prepararBotaoIcone\(.*?\n}", app_js, re.S).group()
    assert 'setAttribute("aria-label"' in funcao
    for nome in ["comentario", "lapis", "camadas", "lixeira"]:
        assert re.search(rf'prepararBotaoIcone\(\w+, "{nome}"', app_js), nome


def test_janela_de_edicao_tem_status_episodios_e_nota(pagina):
    elementos = em(pagina, "dialogo-editar")
    ids = {a.get("id") for _, a in elementos}
    assert {"form-editar", "editar-status", "editar-vistos", "editar-nota"} <= ids
    vistos = next(a for _, a in elementos if a.get("id") == "editar-vistos")
    assert vistos["type"] == "number" and vistos["min"] == "0"
    assert any(t == "button" and a.get("type") == "submit" for t, a in elementos)
    assert any("data-fechar" in a for _, a in elementos)


def test_janelas_tem_titulo_e_botao_de_fechar(pagina):
    janelas = [a for t, a, _ in pagina if t == "dialog"]
    assert len(janelas) == 4
    for janela in janelas:
        assert janela.get("aria-labelledby"), janela["id"]
        assert any("data-fechar" in a for _, a in em(pagina, janela["id"])), janela["id"]


def test_franquia_vira_um_cartao_so(pagina, app_js):
    """O quadro que ocupava a linha inteira deu lugar a um cartão com botões de temporada."""
    assert "molde-franquia" not in {a.get("id") for t, a, _ in pagina if t == "template"}
    assert "function criarCartaoFranquia(" in app_js
    assert 'setAttribute("aria-pressed"' in app_js


def test_titulo_do_cartao_tem_limite_de_linhas(estilo):
    regra = re.search(r"\.cartao__titulo \{(.*?)\}", estilo, re.S).group(1)
    assert "line-clamp: 2" in regra
    assert "min-height" in regra  # um título de 1 linha ocupa o mesmo espaço que um de 2


def test_estilo_respeita_quem_prefere_menos_animacao(estilo):
    assert "@media (prefers-reduced-motion: reduce)" in estilo


def test_front_sem_emojis(cliente):
    """Visual sóbrio: ícones são SVG; nenhum emoji nem símbolo como ✓ no texto."""
    simbolos = re.compile("[☀-➿\U0001f000-\U0001faff]")
    for caminho in ["/", "/static/app.js", "/static/estilo.css"]:
        assert not simbolos.search(cliente.get(caminho).text), caminho


def test_botoes_de_temporada_tem_tamanho_de_toque(estilo):
    regra = re.search(r"\.temporada-botao \{(.*?)\}", estilo, re.S).group(1)
    assert "min-height: 32px" in regra


def test_lista_aguenta_franquias_divergentes(app_js):
    """O mapa das franquias vem de outro pedido: sem rótulo ou sem a temporada, a lista não quebra."""
    assert "visiveis.length > 1 || temporadas.length > 1" in app_js
    assert "estado.rotulos.get(temporada.id) ?? temporada.titulo" in app_js


def test_regra_da_edicao_fica_numa_funcao_separada(app_js):
    """A regra (episódios mudam o status, mas a escolha da pessoa vale mais) é conferida no
    navegador com mudancasDaEdicao; salvarEdicao só lê o formulário e chama ela."""
    salvar = re.search(r"async function salvarEdicao\(.*?\n}", app_js, re.S).group()
    assert "mudancasDaEdicao(anime," in salvar
    regra = re.search(r"function mudancasDaEdicao\(.*?\n}", app_js, re.S).group()
    assert regra.index("mudancasPorEpisodios") < regra.index("mudancas.status = status")


def test_foco_nunca_cai_no_body(app_js):
    devolver = re.search(r"function devolverFoco\(.*?\n}", app_js, re.S).group()
    assert '[data-acao="editar"]' in devolver
    assert '$("#titulo-lista")' in devolver
