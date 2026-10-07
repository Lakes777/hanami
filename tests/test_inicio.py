"""Confere o início (lobby): a seção, as pranchas do fundo e a rota pelo hash.

O movimento das faixas é conferido à mão com os prints; aqui ficam a marcação servida
pela API, os SVGs e as regras do CSS que o movimento depende.
"""

import re
from html.parser import HTMLParser

import pytest

PRANCHAS = ["manga", "tv", "sakura", "torii", "ficha", "pelicula"]


class Telas(HTMLParser):
    """Guarda as tags abertas, anotando em qual tela (section.aba-tela) cada uma está."""

    def __init__(self) -> None:
        super().__init__()
        self.elementos: list[tuple[str, dict, str | None]] = []
        self.pilha: list[str | None] = []

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        tela = next((t for t in reversed(self.pilha) if t), None)
        self.elementos.append((tag, atributos, tela))
        if tag in {"img", "input", "meta", "link", "br"}:
            return  # tags sem fechamento
        e_tela = tag == "section" and "aba-tela" in atributos.get("class", "")
        self.pilha.append(atributos["id"] if e_tela else None)

    def handle_endtag(self, tag):
        if self.pilha:
            self.pilha.pop()


@pytest.fixture
def pagina(cliente):
    leitor = Telas()
    leitor.feed(cliente.get("/").text)
    return leitor.elementos


@pytest.fixture
def estilo(cliente):
    return cliente.get("/static/estilo.css").text


@pytest.fixture
def app_js(cliente):
    return cliente.get("/static/app.js").text


def test_inicio_e_a_primeira_tela(pagina):
    """O app.js abre a primeira tela quando o endereço não tem hash: tem que ser o início."""
    telas = [a["id"] for t, a, _ in pagina if t == "section" and "aba-tela" in a.get("class", "")]
    assert telas == ["inicio", "minha-lista", "adicionar"]


def test_cada_tela_tem_um_h1_so(pagina):
    for tela in ["inicio", "minha-lista", "adicionar"]:
        titulos = [a for t, a, onde in pagina if t == "h1" and onde == tela]
        assert len(titulos) == 1, tela
        assert titulos[0].get("tabindex") == "-1"  # recebe o foco ao trocar de aba
    assert not [a for t, a, onde in pagina if t == "h1" and onde is None]


def test_inicio_tem_nome_destaques_e_botoes(pagina):
    no_inicio = [(t, a) for t, a, onde in pagina if onde == "inicio"]
    links = {a.get("href"): a for t, a in no_inicio if t == "a"}
    assert "botao--vivo" in links["#minha-lista"]["class"]  # Começar
    github = links["https://github.com/Lakes777/hanami"]
    assert github["rel"] == "noopener"
    destaques = [a for t, a in no_inicio if t == "li" and "destaque" in a.get("class", "").split()]
    # Saltam e brilham com o mouse, como os cartões da lista
    assert all("spot" in a["class"].split() for a in destaques)
    assert len(destaques) == 3


def test_menu_e_nome_do_topo_levam_ao_inicio(pagina):
    menu = [a.get("href") for t, a, _ in pagina if t == "a" and a.get("class") == "menu__link"]
    assert menu == ["#inicio", "#minha-lista", "#adicionar"]
    topo = next(a for t, a, _ in pagina if "topo__titulo" in a.get("class", ""))
    assert topo["href"] == "#inicio"


def test_pranchas_do_fundo_sao_decorativas(pagina):
    fundo = next(a for t, a, _ in pagina if a.get("class") == "lobby__fundo")
    assert fundo["aria-hidden"] == "true"
    imagens = [a for t, a, onde in pagina if t == "img" and "/pranchas/" in a.get("src", "")]
    # 3 faixas com as 6 pranchas cada; o app.js repete o conjunto conforme a largura da tela
    assert len(imagens) == 18
    assert all(a["alt"] == "" for a in imagens)
    assert {a["src"].rsplit("/", 1)[1] for a in imagens} == {f"{n}.svg" for n in PRANCHAS}


@pytest.mark.parametrize("nome", PRANCHAS)
def test_pranchas_sao_servidas_como_svg_leve(cliente, nome):
    resposta = cliente.get(f"/static/pranchas/{nome}.svg")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("image/svg+xml")
    svg = resposta.text
    assert 'viewBox="0 0 520 300"' in svg
    assert 'fill="none"' in svg and "stroke=" in svg  # desenho de linha, sem preenchimento
    assert len(resposta.content) < 4000
    # Nada de script, imagem embutida ou arquivo de fora dentro do desenho
    assert not re.search(r"<script|<image|<foreignObject|https?://(?!www\.w3\.org)", svg)


def test_faixas_andam_so_com_transform(estilo):
    deslizar = re.search(r"@keyframes deslizar \{(.*?)\n\}", estilo, re.S).group(1)
    assert "translate3d(-50%, 0, 0)" in deslizar
    assert "opacity" not in deslizar
    trilho = re.search(r"\.faixa__trilho \{(.*?)\}", estilo, re.S).group(1)
    assert "will-change: transform" in trilho
    for duracao in ["64s", "78s", "96s"]:
        assert duracao in estilo
    assert "animation-direction: reverse" in estilo


def bloco_de_menos_movimento(estilo):
    inicio = estilo.index("@media (prefers-reduced-motion: reduce)")
    # O bloco termina na primeira chave que fecha sozinha numa linha
    return estilo[inicio : estilo.index("\n}", inicio)]


def test_faixas_param_com_menos_animacao(estilo):
    """A regra geral de menos movimento desliga toda animação (inclusive as faixas)."""
    bloco = bloco_de_menos_movimento(estilo)
    assert "animation: none !important" in bloco
    # E nenhuma regra das faixas, dentro do bloco, religa a animação
    for seletor, regra in re.findall(r"([^{}]+)\{([^{}]*)\}", bloco):
        if "faixa" in seletor:
            assert "animation" not in regra, seletor


def test_lobby_desconta_a_altura_do_topo(estilo):
    """Uma variável só para a altura do topo: o lobby e a rolagem usam o mesmo valor."""
    assert re.search(r"--altura-topo: \d+px", estilo)
    lobby = re.search(r"\.lobby \{(.*?)\}", estilo, re.S).group(1)
    assert "min-height: calc(100svh - var(--altura-topo))" in lobby
    assert "scroll-padding-top: calc(var(--altura-topo)" in estilo


def test_fundo_nao_cria_rolagem_de_lado(estilo):
    fundo = re.search(r"\.lobby__fundo \{(.*?)\}", estilo, re.S).group(1)
    assert "position: fixed" in fundo and "overflow: hidden" in fundo
    assert re.search(r"\.faixa \{[^}]*overflow: hidden", estilo)


def test_app_js_repete_as_faixas_e_trata_o_inicio(app_js):
    preparar = re.search(r"function prepararInicio\(.*?\n}", app_js, re.S).group()
    assert "cloneNode()" in preparar
    assert 'atual.id === "inicio"' in app_js


def test_faixas_cobrem_telas_largas(app_js):
    """Cada metade do trilho tem que passar da largura da tela, senão abre um vão no loop:
    o conjunto se repete conforme a tela e só depois a metade é duplicada (-50% exato)."""
    preparar = re.search(r"function prepararInicio\(.*?\n}", app_js, re.S).group()
    assert "Math.max(screen.width, window.innerWidth)" in preparar
    assert "Math.ceil(largura / 2200)" in preparar
    repetir = preparar.index("i < repeticoes")
    duplicar = preparar.index("for (const prancha of [...trilho.children]) trilho.append")
    assert repetir < duplicar


def test_numeros_do_inicio(app_js, pagina):
    """A linha de números some com a lista vazia e acerta singular e plural."""
    funcao = re.search(r"function mostrarNumerosNoInicio\(.*?\n}", app_js, re.S).group()
    assert "linha.hidden = e.total === 0" in funcao
    assert 'e.total === 1 ? "anime" : "animes"' in funcao
    assert 'vistos === 1 ? "episódio visto" : "episódios vistos"' in funcao
    assert "textContent" in funcao and "innerHTML" not in funcao
    assert "mostrarNumerosNoInicio(e)" in app_js  # chamada ao carregar as estatísticas
    linha = next(a for t, a, _ in pagina if a.get("id") == "lobby-numeros")
    assert "hidden" in linha  # começa escondida até a API responder


def test_aviso_de_demo_fica_fora_do_inicio(app_js, estilo):
    assert re.search(r"\.no-inicio \.demo \{\s*display: none;", estilo)
    assert 'classList.toggle("no-inicio", noInicio)' in app_js
    assert 'const noInicio = atual.id === "inicio"' in app_js
