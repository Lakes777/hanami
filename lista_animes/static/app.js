// Front do Hanami: conversa com a própria API usando fetch().
// Todo texto vindo da API entra na página com textContent, que não interpreta HTML,
// então um título como "<script>..." aparece como texto e não é executado.

// A ordem escolhida fica guardada só neste navegador. localStorage pode não existir
// (janela anônima, armazenamento bloqueado): aí vale a ordem padrão.
const ORDENS = ["recentes", "antigos", "titulo", "nota"];

function lerOrdemSalva() {
  try {
    const salva = localStorage.getItem("lista-animes:ordem");
    return ORDENS.includes(salva) ? salva : "recentes";
  } catch {
    return "recentes";
  }
}

function salvarOrdem(ordem) {
  try {
    localStorage.setItem("lista-animes:ordem", ordem);
  } catch {
    // sem armazenamento: a escolha vale só até recarregar a página
  }
}

const estado = {
  status: "",
  busca: "",
  malIdsNaLista: new Set(),
  franquias: new Map(), // número da franquia -> temporadas dela (da lista completa)
  rotulos: new Map(), // id do anime -> "Temporada 2", "Filme"...
  ordem: lerOrdemSalva(),
  detalhes: new Map(), // mal_id -> dados do catálogo (para não pedir à Jikan de novo)
  detalhesDe: null, // mal_id aberto na janela de detalhes
  animeComentado: null,
  temporadasDe: null, // anime cujas outras temporadas estão abertas na janela
  animeEditado: null, // anime aberto na janela "Editar"
  temporadaEscolhida: new Map(), // número da franquia -> id da temporada mostrada no cartão
};

const $ = (seletor) => document.querySelector(seletor);

// Ícones da Lucide (lucide.dev, licença ISC), montados elemento por elemento (nada de HTML em texto).
const ICONES = {
  lixeira: ["M3 6h18", "M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6", "M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2",
    "M10 11v6", "M14 11v6"],
  comentario: ["M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"],
  lapis: ["M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z",
    "m15 5 4 4"],
  camadas: ["M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z",
    "M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12",
    "M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"],
  mais: ["M5 12h14", "M12 5v14"],
  certo: ["M20 6 9 17l-5-5"],
  busca: ["M3 11a8 8 0 1 0 16 0a8 8 0 1 0 -16 0", "m21 21-4.3-4.3"],
  estrela: ["M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"],
};

function icone(nome, tamanho = 18) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [atributo, valor] of Object.entries({
    viewBox: "0 0 24 24", width: tamanho, height: tamanho, fill: "none", stroke: "currentColor",
    "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
  })) svg.setAttribute(atributo, valor);
  for (const d of ICONES[nome]) {
    const caminho = document.createElementNS("http://www.w3.org/2000/svg", "path");
    caminho.setAttribute("d", d);
    svg.append(caminho);
  }
  return svg;
}

// Botão só de ícone: o texto vai no aria-label (leitor de tela) e no title (dica do mouse).
function prepararBotaoIcone(botao, nome, rotulo, dica = rotulo) {
  botao.prepend(icone(nome));
  botao.setAttribute("aria-label", rotulo);
  botao.title = dica;
}

// ---------- Conversa com a API ----------

async function api(caminho, opcoes = {}) {
  const resposta = await fetch(caminho, {
    headers: { "Content-Type": "application/json" },
    ...opcoes,
  });
  if (resposta.status === 204) return null;
  const dados = await resposta.json().catch(() => null);
  if (!resposta.ok) throw new Error(mensagemDeErro(dados, resposta.status));
  return dados;
}

function mensagemDeErro(dados, codigo) {
  const detalhe = dados?.detail;
  if (typeof detalhe === "string") return detalhe;
  // Erros de validação (422) vêm como lista; mostramos a primeira mensagem.
  if (Array.isArray(detalhe) && detalhe[0]?.msg) return detalhe[0].msg.replace("Value error, ", "");
  return `Algo deu errado (erro ${codigo}).`;
}

// ---------- Mensagens rápidas ----------

let temporizadorMensagem;

function mostrarMensagem(texto, erro = false) {
  const caixa = $("#mensagem");
  caixa.textContent = texto;
  caixa.classList.toggle("mensagem--erro", erro);
  caixa.hidden = false;
  clearTimeout(temporizadorMensagem);
  temporizadorMensagem = setTimeout(() => (caixa.hidden = true), 3500);
}

function mostrarAviso(elemento, texto) {
  elemento.textContent = texto;
  elemento.hidden = !texto;
}

// ---------- Estatísticas ----------

async function carregarEstatisticas() {
  const e = await api("/animes/estatisticas");
  const numeros = [
    [e.total, e.total === 1 ? "anime na lista" : "animes na lista"],
    [e.por_status.assistindo, "assistindo"],
    [e.por_status.concluido, "concluídos"],
    [e.episodios_assistidos, "episódios vistos"],
    [e.nota_media ?? "—", "nota média"],
  ];
  mostrarNumerosNoInicio(e);
  $("#estatisticas").replaceChildren(
    ...numeros.map(([valor, rotulo]) => {
      const caixa = document.createElement("div");
      caixa.className = "numero";
      const v = document.createElement("span");
      v.className = "numero__valor";
      v.textContent = typeof valor === "number" ? valor.toLocaleString("pt-BR") : valor;
      const r = document.createElement("span");
      r.className = "numero__rotulo";
      r.textContent = rotulo;
      caixa.append(v, r);
      return caixa;
    }),
  );
}

// No início, uma linha só com o tamanho da lista (some se a lista estiver vazia)
function mostrarNumerosNoInicio(e) {
  const linha = $("#lobby-numeros");
  linha.hidden = e.total === 0;
  if (linha.hidden) return;
  const partes = [`${e.total.toLocaleString("pt-BR")} ${e.total === 1 ? "anime" : "animes"} na lista`];
  if (e.episodios_assistidos > 0) {
    const vistos = e.episodios_assistidos;
    partes.push(`${vistos.toLocaleString("pt-BR")} ${vistos === 1 ? "episódio visto" : "episódios vistos"}`);
  }
  linha.textContent = partes.join(" · ");
}

// ---------- Minha lista ----------

// "1 ep." e "26 eps."
function eps(numero) {
  return numero === 1 ? "ep." : "eps.";
}

function textoTotal(anime) {
  // 1087 vira "1.087"
  return anime.total_episodios === null ? "?" : anime.total_episodios.toLocaleString("pt-BR");
}

// O status acompanha os episódios: começou a ver vira "assistindo",
// chegou ao último vira "concluído" e voltou atrás num concluído vira "assistindo" de novo.
function mudancasPorEpisodios(anime, vistos) {
  const mudancas = { episodios_vistos: vistos };
  const total = anime.total_episodios;
  if (vistos > 0 && anime.status === "quero_ver") mudancas.status = "assistindo";
  if (total !== null && vistos === total) mudancas.status = "concluido";
  if (total !== null && vistos < total && anime.status === "concluido") mudancas.status = "assistindo";
  return mudancas;
}

// A capa fica dentro de um botão que abre os detalhes; o nome vai no botão (aria-label),
// então a imagem não precisa de texto alternativo próprio.
function preencherCapa(cartao, anime, abrir) {
  const img = cartao.querySelector(".cartao__capa");
  if (anime.imagem_url) img.src = anime.imagem_url;
  else img.removeAttribute("src");
  const botao = cartao.querySelector('[data-acao="detalhes"]');
  if (anime.mal_id === null) {
    // Anime cadastrado à mão: não há o que buscar no MyAnimeList. A capa vira só imagem.
    botao.disabled = true;
    img.alt = `Capa de ${anime.titulo}`;
    return;
  }
  botao.setAttribute("aria-label", `Ver sinopse e detalhes de ${anime.titulo}`);
  botao.title = "Ver sinopse e detalhes";
  botao.addEventListener("click", abrir);
}

// ---------- Detalhes (sinopse e gêneros do MyAnimeList) ----------

function mostrarDetalhes(dados) {
  const info = [
    dados.tipo,
    dados.ano,
    dados.total_episodios && `${dados.total_episodios} ${eps(dados.total_episodios)}`,
    dados.nota_mal && `nota ${dados.nota_mal.toLocaleString("pt-BR")} no MAL`,
  ].filter(Boolean);
  $("#detalhes-info").textContent = info.join(" · ");
  $("#detalhes-generos").replaceChildren(
    ...dados.generos.map((genero) => {
      const item = document.createElement("li");
      item.textContent = genero;
      return item;
    }),
  );
  $("#detalhes-sinopse").textContent = dados.sinopse || "Sem sinopse no MyAnimeList.";
  const link = $("#detalhes-link");
  link.href = `https://myanimelist.net/anime/${dados.mal_id}`;
  link.hidden = false;
}

// dados: o anime do catálogo, quando já se tem (resultado da busca); senão, pede à API.
async function abrirDetalhes(anime, dados = null) {
  const malId = anime.mal_id;
  estado.detalhesDe = malId;
  if (dados) estado.detalhes.set(malId, dados);
  $("#detalhes-titulo").textContent = anime.titulo;
  $("#detalhes-info").textContent = "";
  $("#detalhes-generos").replaceChildren();
  $("#detalhes-sinopse").textContent = "";
  $("#detalhes-link").hidden = true;
  $("#dialogo-detalhes").showModal();

  const guardado = estado.detalhes.get(malId);
  if (guardado) {
    mostrarAviso($("#aviso-detalhes"), "");
    return mostrarDetalhes(guardado);
  }
  mostrarAviso($("#aviso-detalhes"), "Buscando no MyAnimeList...");
  try {
    const encontrado = await api(`/catalogo/${malId}`);
    estado.detalhes.set(malId, encontrado);
    if (estado.detalhesDe !== malId) return; // a pessoa já abriu outro anime
    mostrarAviso($("#aviso-detalhes"), "");
    mostrarDetalhes(encontrado);
  } catch (erro) {
    if (estado.detalhesDe === malId) mostrarAviso($("#aviso-detalhes"), erro.message);
  }
}

// ---------- Temporadas (franquias) ----------

// No MyAnimeList, filmes e OVAs também fazem parte da franquia; eles não contam como temporada.
const NOMES_DOS_TIPOS = {
  Movie: "Filme",
  OVA: "OVA",
  ONA: "ONA",
  Special: "Especial",
  "TV Special": "Especial",
  Music: "Clipe",
};

function organizarFranquias(todos) {
  // A API já manda as temporadas juntas e em ordem de estreia.
  estado.franquias = new Map();
  for (const anime of todos) {
    if (!estado.franquias.has(anime.franquia)) estado.franquias.set(anime.franquia, []);
    estado.franquias.get(anime.franquia).push(anime);
  }
  estado.rotulos = new Map();
  for (const temporadas of estado.franquias.values()) {
    if (temporadas.length < 2) continue;
    let numero = 0;
    for (const anime of temporadas) {
      estado.rotulos.set(anime.id, NOMES_DOS_TIPOS[anime.tipo] ?? `Temporada ${++numero}`);
    }
  }
}

function criarItemTemporada(relacionado) {
  const item = $("#molde-temporada").content.firstElementChild.cloneNode(true);
  item.querySelector(".temporada__relacao").textContent =
    relacionado.relacao === "anterior" ? "Vem antes" : "Vem depois";
  item.querySelector(".temporada__titulo").textContent = relacionado.titulo;
  item.querySelector("button").addEventListener("click", async (evento) => {
    const botao = evento.currentTarget;
    botao.disabled = true;
    try {
      await api(`/animes/do-catalogo/${relacionado.mal_id}`, { method: "POST" });
      mostrarMensagem(`"${relacionado.titulo}" entrou na sua lista!`);
      await atualizarTudo();
      await carregarTemporadas(); // procura a próxima (a franquia agora vai mais longe)
    } catch (erro) {
      mostrarMensagem(erro.message, true);
      botao.disabled = false;
    }
  });
  return item;
}

async function carregarTemporadas() {
  const aviso = $("#aviso-temporadas");
  $("#lista-temporadas").replaceChildren();
  mostrarAviso(aviso, "Procurando no MyAnimeList...");
  try {
    const faltando = await api(`/animes/${estado.temporadasDe.id}/outras-temporadas`);
    $("#lista-temporadas").replaceChildren(...faltando.map(criarItemTemporada));
    // A consulta pode ter juntado temporadas que estavam separadas: atualiza a lista.
    await atualizarTudo();
    mostrarAviso(aviso, faltando.length
      ? ""
      : "Nenhuma outra temporada encontrada: as que existem já estão na sua lista.");
  } catch (erro) {
    mostrarAviso(aviso, erro.message);
  }
}

function abrirTemporadas(anime, nome) {
  estado.temporadasDe = anime;
  $("#temporadas-franquia").textContent = nome;
  $("#dialogo-temporadas").showModal();
  carregarTemporadas();
}

// ---------- Cartões da lista ----------

// franquia: { temporadas, visiveis } quando o anime faz parte de uma franquia com 2 ou mais na lista.
function criarCartaoAnime(anime, franquia = null) {
  const cartao = $("#molde-anime").content.firstElementChild.cloneNode(true);
  cartao.dataset.id = anime.id;
  cartao.dataset.franquia = anime.franquia;
  preencherCapa(cartao, anime, () => abrirDetalhes(anime));
  const titulo = cartao.querySelector(".cartao__titulo");
  titulo.textContent = anime.titulo;
  titulo.title = anime.titulo; // o título longo é cortado em 2 linhas; o mouse mostra inteiro

  // Nota: um selo discreto na capa (só quando há nota)
  if (anime.nota !== null) {
    const selo = cartao.querySelector(".cartao__nota");
    const texto = document.createElement("span");
    texto.textContent = anime.nota;
    selo.append(icone("estrela", 12), texto);
    selo.setAttribute("aria-label", `Nota ${anime.nota}`);
    selo.setAttribute("role", "img");
    selo.hidden = false;
  }

  const status = cartao.querySelector('[data-campo="status"]');
  status.value = anime.status;
  status.dataset.status = anime.status;
  status.setAttribute("aria-label", `Status de ${anime.titulo}`);
  status.addEventListener("change", () => editar(anime.id, { status: status.value }));

  const episodios = cartao.querySelector(".episodios__texto");
  const vistos = document.createElement("strong");
  vistos.textContent = anime.episodios_vistos.toLocaleString("pt-BR");
  episodios.append(vistos, ` / ${textoTotal(anime)} ${eps(anime.total_episodios)}`);

  const porcentagem = anime.total_episodios
    ? (100 * anime.episodios_vistos) / anime.total_episodios
    : 0;
  cartao.querySelector(".progresso__barra").style.width = `${porcentagem}%`;

  const mais1 = cartao.querySelector('[data-acao="mais1"]');
  const acabou = anime.total_episodios !== null && anime.episodios_vistos >= anime.total_episodios;
  mais1.disabled = acabou;
  mais1.setAttribute("aria-label", `+1 ep. de ${anime.titulo}`);
  mais1.addEventListener("click", () =>
    editar(anime.id, mudancasPorEpisodios(anime, anime.episodios_vistos + 1)),
  );

  const comentarios = cartao.querySelector('[data-acao="comentarios"]');
  if (anime.comentarios) {
    const contagem = document.createElement("span");
    contagem.className = "botao-icone__contagem";
    contagem.textContent = anime.comentarios;
    comentarios.append(contagem);
    comentarios.classList.add("botao-icone--com-texto");
  }
  prepararBotaoIcone(comentarios, "comentario",
    anime.comentarios ? `Comentários de ${anime.titulo} (${anime.comentarios})` : `Comentar ${anime.titulo}`,
    anime.comentarios ? "Ver comentários" : "Comentar");
  comentarios.addEventListener("click", () => abrirComentarios(anime));

  const editarBotao = cartao.querySelector('[data-acao="editar"]');
  prepararBotaoIcone(editarBotao, "lapis", `Editar status, episódios e nota de ${anime.titulo}`,
    "Editar status, episódios e nota");
  editarBotao.addEventListener("click", () => abrirEdicao(anime));

  // Outras temporadas: no anime sozinho procura a partir dele; na franquia, a partir da última.
  const outras = cartao.querySelector('[data-acao="temporadas"]');
  const nomeFranquia = franquia ? franquia.temporadas[0].titulo : anime.titulo;
  outras.hidden = !franquia && anime.mal_id === null;
  prepararBotaoIcone(outras, "camadas", `Ver outras temporadas de ${nomeFranquia}`, "Ver outras temporadas");
  outras.addEventListener("click", () =>
    abrirTemporadas(franquia ? franquia.temporadas.at(-1) : anime, nomeFranquia),
  );

  const lixeira = cartao.querySelector('[data-acao="remover"]');
  prepararBotaoIcone(lixeira, "lixeira", `Remover ${anime.titulo}`, "Remover da lista");
  lixeira.addEventListener("click", () => remover(anime));
  return cartao;
}

// ---------- Franquia: um cartão só, com as temporadas trocadas por botões sobre a capa ----------
// Assim a franquia ocupa uma célula da grade como qualquer anime e o ritmo da grade não quebra.

function temporadaInicial(visiveis) {
  const escolhida = visiveis.find((a) => a.id === estado.temporadaEscolhida.get(visiveis[0].franquia));
  return escolhida
    ?? visiveis.find((a) => a.status === "assistindo")
    ?? visiveis.find((a) => a.status !== "concluido")
    ?? visiveis.at(-1);
}

function rotuloCurto(rotulo) {
  return rotulo.replace(/^Temporada (\d+)$/, "T$1");
}

function criarCartaoFranquia(temporadas, visiveis, anime = temporadaInicial(visiveis)) {
  const cartao = criarCartaoAnime(anime, { temporadas, visiveis });
  cartao.classList.add("cartao--franquia");
  const nome = temporadas[0].titulo; // a primeira a estrear dá nome à franquia
  const soTemporadas = temporadas.every((a) => !(a.tipo in NOMES_DOS_TIPOS));

  const grupo = document.createElement("div");
  grupo.className = "cartao__temporadas";
  grupo.setAttribute("role", "group");
  grupo.setAttribute("aria-label",
    `${nome}: ${temporadas.length} ${soTemporadas ? "temporadas" : "itens"} na lista`);
  for (const temporada of visiveis) {
    const rotulo = estado.rotulos.get(temporada.id) ?? temporada.titulo;
    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = "temporada-botao";
    botao.textContent = rotuloCurto(rotulo);
    botao.dataset.temporada = temporada.id;
    botao.setAttribute("aria-label", `${rotulo}: ${temporada.titulo}`);
    botao.title = `${rotulo}: ${temporada.titulo}`;
    botao.setAttribute("aria-pressed", String(temporada === anime));
    botao.addEventListener("click", () => {
      if (temporada === anime) return;
      estado.temporadaEscolhida.set(anime.franquia, temporada.id);
      const novo = criarCartaoFranquia(temporadas, visiveis, temporada);
      cartao.replaceWith(novo);
      novo.querySelector(`[data-temporada="${temporada.id}"]`).focus();
    });
    grupo.append(botao);
  }
  cartao.querySelector(".cartao__midia").append(grupo);
  return cartao;
}

// ---------- Editar (status, episódios vistos e nota) ----------

function abrirEdicao(anime) {
  estado.animeEditado = anime;
  $("#editar-titulo").textContent = anime.titulo;
  const rotulo = estado.rotulos.get(anime.id);
  $("#editar-temporada").textContent = rotulo ?? "";
  $("#editar-temporada").hidden = !rotulo;
  $("#editar-status").value = anime.status;
  const vistos = $("#editar-vistos");
  vistos.value = anime.episodios_vistos;
  if (anime.total_episodios !== null) vistos.max = anime.total_episodios;
  else vistos.removeAttribute("max");
  $("#editar-total").textContent = anime.total_episodios === null
    ? "(total ainda não conhecido)"
    : `de ${textoTotal(anime)}`;
  $("#editar-nota").value = anime.nota ?? "";
  $("#dialogo-editar").showModal();
}

// O que mandar no PATCH depois da janela Editar: só o que mudou.
// Os episódios ajustam o status sozinhos; se a pessoa escolheu outro status, vale a escolha dela.
function mudancasDaEdicao(anime, { vistos, status, nota }) {
  const mudancas = vistos !== anime.episodios_vistos ? mudancasPorEpisodios(anime, vistos) : {};
  if (status !== anime.status) mudancas.status = status;
  if (nota !== anime.nota) mudancas.nota = nota;
  return mudancas;
}

async function salvarEdicao(evento) {
  evento.preventDefault();
  const anime = estado.animeEditado;
  const vistos = Number($("#editar-vistos").value);
  const total = anime.total_episodios;
  if (!Number.isInteger(vistos) || vistos < 0 || (total !== null && vistos > total)) {
    return mostrarMensagem(total === null
      ? "Digite um número inteiro de episódios."
      : `Digite um número de 0 a ${total}.`, true);
  }
  const mudancas = mudancasDaEdicao(anime, {
    vistos,
    status: $("#editar-status").value,
    nota: $("#editar-nota").value ? Number($("#editar-nota").value) : null,
  });
  $("#dialogo-editar").close();
  if (Object.keys(mudancas).length) await editar(anime.id, mudancas);
}

// ---------- Foco do teclado ao redesenhar a lista ----------

function lembrarFoco() {
  const focado = document.activeElement;
  const cartao = focado?.closest?.("#lista .cartao");
  if (!cartao) return null;
  const { acao, campo, temporada } = focado.dataset;
  return {
    id: cartao.dataset.id,
    franquia: cartao.dataset.franquia,
    indice: [...$("#lista").children].indexOf(cartao),
    seletor: acao ? `[data-acao="${acao}"]`
      : campo ? `[data-campo="${campo}"]`
      : temporada ? `[data-temporada="${temporada}"]` : null,
  };
}

// Volta ao mesmo botão. Se ele sumiu ou ficou desativado (o anime acabou, a franquia passou
// para a próxima temporada), vai para o Editar do mesmo cartão. Se o cartão saiu da lista
// (ex.: filtro "Assistindo" e o anime foi concluído), vai para o cartão que ficou no lugar dele
// ou, com a lista vazia, para o título da lista. Nunca deixa o foco cair no <body>.
function devolverFoco(foco) {
  if (!foco) return;
  const usavel = (elemento) => (elemento && !elemento.disabled && !elemento.hidden ? elemento : null);
  const cartoes = $("#lista").children;
  const mesmo = $(`#lista .cartao[data-id="${foco.id}"]`);
  // A franquia passou a mostrar outra temporada: vai para o Editar (e não para o +1 ep. da
  // outra temporada, para um Enter repetido não marcar episódio no anime errado).
  const daFranquia = !mesmo && $(`#lista .cartao[data-franquia="${foco.franquia}"]`);
  const alvo = mesmo
    ? usavel(foco.seletor && mesmo.querySelector(foco.seletor)) ?? mesmo.querySelector('[data-acao="editar"]')
    : daFranquia?.querySelector('[data-acao="editar"]')
      ?? cartoes[Math.min(foco.indice, cartoes.length - 1)]?.querySelector('[data-acao="editar"]')
      ?? $("#titulo-lista");
  alvo.focus();
}

async function carregarLista() {
  const parametros = new URLSearchParams();
  if (estado.status) parametros.set("status", estado.status);
  if (estado.busca) parametros.set("busca", estado.busca);

  const animes = await api(`/animes?${parametros}`);
  // Junta as temporadas da mesma franquia num grupo (elas já vêm uma depois da outra).
  const grupos = [];
  for (let i = 0; i < animes.length; ) {
    const visiveis = [animes[i]];
    while (animes[i + visiveis.length]?.franquia === animes[i].franquia) {
      visiveis.push(animes[i + visiveis.length]);
    }
    i += visiveis.length;
    // A lista filtrada e o mapa das franquias vêm de pedidos separados e podem divergir
    // (alguém mudou a lista no meio). Se o mapa não tiver todas as visíveis, valem as visíveis.
    const daFranquia = estado.franquias.get(visiveis[0].franquia) ?? [];
    const completa = visiveis.every((v) => daFranquia.some((t) => t.id === v.id));
    grupos.push({ visiveis, temporadas: completa ? daFranquia : visiveis });
  }
  const elementos = ordenarGrupos(grupos).map(({ visiveis, temporadas }) =>
    visiveis.length > 1 || temporadas.length > 1
      ? criarCartaoFranquia(temporadas, visiveis)
      : criarCartaoAnime(visiveis[0]),
  );
  // Os cartões são recriados: quem estava com o foco num botão (ex.: +1 ep.) volta para ele.
  const foco = lembrarFoco();
  $("#lista").replaceChildren(...elementos);
  devolverFoco(foco);

  let aviso = "";
  if (animes.length === 0) {
    const filtrando = estado.status || estado.busca;
    aviso = filtrando
      ? "Nenhum anime com esse filtro."
      : "Sua lista está vazia. Busque um anime na aba Adicionar e clique em + Adicionar.";
  }
  mostrarAviso($("#aviso-lista"), aviso);
}

// A ordem vale para os grupos: as temporadas de uma franquia continuam juntas, na ordem de estreia.
// A API manda os grupos na ordem em que foram adicionados (é a ordem "antigos").
const porTitulo = new Intl.Collator("pt-BR", { sensitivity: "base", numeric: true });

function ordenarGrupos(grupos) {
  const titulo = (grupo) => grupo.temporadas[0].titulo;
  const ultimoAdicionado = (grupo) => Math.max(...grupo.temporadas.map((a) => a.id));
  const melhorNota = (grupo) => Math.max(0, ...grupo.visiveis.map((a) => a.nota ?? 0));
  const comparar = {
    antigos: () => 0, // sort() é estável: fica a ordem da API
    recentes: (a, b) => ultimoAdicionado(b) - ultimoAdicionado(a),
    titulo: (a, b) => porTitulo.compare(titulo(a), titulo(b)),
    // Sem nota vai para o fim; empate desempata pelo título.
    nota: (a, b) => melhorNota(b) - melhorNota(a) || porTitulo.compare(titulo(a), titulo(b)),
  }[estado.ordem];
  return [...grupos].sort(comparar);
}

async function atualizarTudo() {
  // A lista completa (sem filtro) diz quais animes do catálogo já foram adicionados.
  const todos = await api("/animes");
  estado.malIdsNaLista = new Set(todos.map((a) => a.mal_id).filter(Boolean));
  organizarFranquias(todos);
  await Promise.all([carregarLista(), carregarEstatisticas()]);
  marcarAdicionadosNoCatalogo();
}

async function editar(id, mudancas) {
  try {
    await api(`/animes/${id}`, { method: "PATCH", body: JSON.stringify(mudancas) });
    if (mudancas.status === "concluido") mostrarMensagem("Anime concluído!");
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
  await atualizarTudo();
}

async function remover(anime) {
  if (!confirm(`Remover "${anime.titulo}" da sua lista?`)) return;
  try {
    await api(`/animes/${anime.id}`, { method: "DELETE" });
    mostrarMensagem(`"${anime.titulo}" saiu da lista.`);
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
  await atualizarTudo();
}

// ---------- Comentários ----------

function dataHora(texto) {
  // A API guarda em UTC; o navegador mostra no fuso de quem está vendo.
  return new Date(texto).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function criarComentario(comentario) {
  const item = $("#molde-comentario").content.firstElementChild.cloneNode(true);
  const info = [comentario.episodio && `Ep. ${comentario.episodio}`, dataHora(comentario.criado_em)];
  item.querySelector(".comentario__info").textContent = info.filter(Boolean).join(" · ");
  item.querySelector(".comentario__texto").textContent = comentario.texto;
  item.querySelector("button").addEventListener("click", () => apagarComentario(comentario));
  return item;
}

async function carregarComentarios() {
  const anime = estado.animeComentado;
  const comentarios = await api(`/animes/${anime.id}/comentarios`);
  $("#lista-comentarios").replaceChildren(...comentarios.map(criarComentario));
  mostrarAviso($("#aviso-comentarios"), comentarios.length ? "" : "Nenhum comentário ainda.");
}

async function abrirComentarios(anime) {
  estado.animeComentado = anime;
  $("#comentarios-titulo").textContent = anime.titulo;
  $("#form-comentario").reset();
  const episodio = $("#episodio-comentario");
  if (anime.total_episodios !== null) episodio.max = anime.total_episodios;
  else episodio.removeAttribute("max");
  $("#lista-comentarios").replaceChildren();
  mostrarAviso($("#aviso-comentarios"), "Carregando...");
  $("#dialogo-comentarios").showModal();
  try {
    await carregarComentarios();
  } catch (erro) {
    mostrarAviso($("#aviso-comentarios"), erro.message);
  }
}

async function enviarComentario(evento) {
  evento.preventDefault();
  const anime = estado.animeComentado;
  const episodio = $("#episodio-comentario").value;
  const botao = evento.submitter;
  botao.disabled = true;
  try {
    await api(`/animes/${anime.id}/comentarios`, {
      method: "POST",
      body: JSON.stringify({
        texto: $("#texto-comentario").value,
        episodio: episodio ? Number(episodio) : null,
      }),
    });
    $("#form-comentario").reset();
    await Promise.all([carregarComentarios(), carregarLista()]); // a lista mostra a contagem nova
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  } finally {
    botao.disabled = false;
  }
}

async function apagarComentario(comentario) {
  if (!confirm("Apagar este comentário?")) return;
  try {
    await api(`/animes/${comentario.anime_id}/comentarios/${comentario.id}`, { method: "DELETE" });
    await Promise.all([carregarComentarios(), carregarLista()]);
  } catch (erro) {
    mostrarMensagem(erro.message, true);
  }
}

function fecharAoClicarFora(evento) {
  // O clique no fundo escuro (fora da caixa) cai no próprio <dialog>.
  if (evento.target === evento.currentTarget) evento.currentTarget.close();
}

// ---------- Catálogo (Jikan) ----------

function criarCartaoCatalogo(anime) {
  const cartao = $("#molde-catalogo").content.firstElementChild.cloneNode(true);
  cartao.dataset.malId = anime.mal_id;
  preencherCapa(cartao, anime, () => abrirDetalhes(anime, anime));
  const titulo = cartao.querySelector(".cartao__titulo");
  titulo.textContent = anime.titulo;
  titulo.title = anime.titulo;

  const info = [
    anime.tipo,
    anime.ano,
    anime.total_episodios && `${anime.total_episodios} ${eps(anime.total_episodios)}`,
    anime.nota_mal && `nota ${anime.nota_mal} no MAL`,
  ].filter(Boolean);
  cartao.querySelector(".cartao__info").textContent = info.join(" · ");
  cartao.querySelector(".cartao__generos").textContent = anime.generos.slice(0, 3).join(", ");

  // Pelo data-acao: o primeiro <button> do cartão é a capa (que abre os detalhes).
  cartao.querySelector('[data-acao="adicionar"]').addEventListener("click", async (evento) => {
    const botao = evento.currentTarget;
    botao.disabled = true;
    try {
      await api(`/animes/do-catalogo/${anime.mal_id}`, { method: "POST" });
      mostrarMensagem(`"${anime.titulo}" entrou na sua lista!`);
      await atualizarTudo();
    } catch (erro) {
      mostrarMensagem(erro.message, true);
      botao.disabled = false;
    }
  });
  return cartao;
}

function marcarAdicionadosNoCatalogo() {
  for (const cartao of $("#resultados-catalogo").children) {
    const jaNaLista = estado.malIdsNaLista.has(Number(cartao.dataset.malId));
    const botao = cartao.querySelector('[data-acao="adicionar"]');
    botao.disabled = jaNaLista;
    botao.classList.toggle("cartao__adicionar--na-lista", jaNaLista);
    botao.replaceChildren(icone(jaNaLista ? "certo" : "mais", 16), jaNaLista ? "Na sua lista" : "Adicionar");
  }
}

// Aceita o ID ("52991") ou o link da página do anime no MyAnimeList
// ("https://myanimelist.net/anime/52991/Sousou_no_Frieren"). Devolve null se for um nome.
function extrairMalId(texto) {
  const encontrado = texto.match(/^(\d+)$/) || texto.match(/myanimelist\.net\/anime\/(\d+)/);
  return encontrado ? Number(encontrado[1]) : null;
}

async function procurar(termo) {
  const malId = extrairMalId(termo);
  if (malId !== null) {
    // A busca por ID usa a cópia guardada pela Jikan: costuma funcionar
    // mesmo quando a busca por nome falha com o MyAnimeList fora do ar.
    return [await api(`/catalogo/${malId}`)];
  }
  if (termo.length < 2) throw new Error("Digite pelo menos 2 letras do nome.");
  return api(`/catalogo/busca?${new URLSearchParams({ q: termo })}`);
}

async function buscarNoCatalogo(evento) {
  evento.preventDefault();
  const termo = $("#termo-catalogo").value.trim();
  const botao = evento.submitter;
  const aviso = $("#aviso-catalogo");

  botao.disabled = true;
  mostrarAviso(aviso, "Buscando no MyAnimeList...");
  try {
    const animes = await procurar(termo);
    $("#resultados-catalogo").replaceChildren(...animes.map(criarCartaoCatalogo));
    marcarAdicionadosNoCatalogo();
    let texto = animes.length ? "" : `Nenhum anime encontrado para "${termo}".`;
    if (animes.some((anime) => anime.fonte === "anilist")) {
      texto = "A busca do MyAnimeList está fora do ar agora, então estes resultados vieram do AniList."
        + " Adicionar funciona do mesmo jeito.";
    }
    mostrarAviso(aviso, texto);
  } catch (erro) {
    $("#resultados-catalogo").replaceChildren();
    let texto = erro.message;
    if (extrairMalId(termo) === null && erro.message.includes("fora do ar")) {
      texto += " Dica: cole o link do anime no MyAnimeList (ex.: myanimelist.net/anime/52991)."
        + " A busca por ID costuma funcionar mesmo assim.";
    }
    mostrarAviso(aviso, texto);
  } finally {
    botao.disabled = false;
  }
}

// ---------- Backup (exportar e importar) ----------

async function importarBackup(evento) {
  const arquivo = evento.target.files[0];
  evento.target.value = ""; // permite escolher o mesmo arquivo de novo depois
  if (!arquivo) return;
  if (arquivo.size > 5_000_000) return mostrarMensagem("Arquivo grande demais (o máximo é 5 MB).", true);
  let lista;
  try {
    lista = JSON.parse(await arquivo.text());
  } catch {
    lista = null;
  }
  // Confere antes de enviar: assim a mensagem é clara, e não um erro de validação em inglês.
  if (lista?.formato !== "lista-animes" || !Array.isArray(lista.animes)) {
    return mostrarMensagem("Esse arquivo não é um backup do Hanami.", true);
  }
  try {
    const r = await api("/animes/importar", { method: "POST", body: JSON.stringify(lista) });
    const partes = [`${r.importados} ${r.importados === 1 ? "anime importado" : "animes importados"}`];
    if (r.repetidos) partes.push(`${r.repetidos} já ${r.repetidos === 1 ? "estava" : "estavam"} na lista`);
    if (r.comentarios) partes.push(`${r.comentarios} ${r.comentarios === 1 ? "comentário" : "comentários"}`);
    mostrarMensagem(`Backup importado: ${partes.join(", ")}.`);
    await atualizarTudo();
  } catch (erro) {
    mostrarMensagem(`Não deu para importar: ${erro.message}`, true);
  }
}

// ---------- Filtros ----------

function escolherAba(evento) {
  const aba = evento.target.closest(".aba");
  if (!aba) return;
  for (const outra of $("#abas").querySelectorAll(".aba")) {
    outra.classList.toggle("aba--ativa", outra === aba);
    outra.setAttribute("aria-selected", String(outra === aba));
  }
  moverPilula($("#abas-pilula"), aba);
  estado.status = aba.dataset.status;
  carregarLista().catch((erro) => mostrarMensagem(erro.message, true));
}

let temporizadorFiltro;

function filtrarPorTitulo(evento) {
  // Espera a pessoa parar de digitar (300 ms) antes de consultar a API.
  clearTimeout(temporizadorFiltro);
  temporizadorFiltro = setTimeout(() => {
    estado.busca = evento.target.value.trim();
    carregarLista().catch((erro) => mostrarMensagem(erro.message, true));
  }, 300);
}

// ---------- Abas (iguais às do portfólio e do Controle de Gastos) ----------

const telas = [...document.querySelectorAll("main > .aba-tela")];
const linksMenu = document.querySelectorAll(".menu__link");
let abasIniciadas = false;
let trocaAtual = 0; // ao clicar rápido nas duas abas, só a última troca vale

// Pílula desliza até o item ativo (serve para o menu e para os filtros de status)
function moverPilula(pilula, ativo) {
  if (!ativo || !ativo.offsetWidth) return; // escondida (outra aba aberta): mede depois
  const primeiraVez = !pilula.style.width;
  if (primeiraVez) pilula.style.transition = "none"; // nasce no lugar, sem deslizar do canto
  pilula.style.width = `${ativo.offsetWidth}px`;
  pilula.style.height = `${ativo.offsetHeight}px`;
  pilula.style.transform = `translate(${ativo.offsetLeft}px, ${ativo.offsetTop}px)`;
  if (primeiraVez) {
    void pilula.offsetWidth;
    pilula.style.transition = "";
  }
}

function moverPilulas() {
  moverPilula($("#menu-pilula"), $(".menu__link--ativo"));
  moverPilula($("#abas-pilula"), $(".aba--ativa"));
}

function mostrarAba(focar) {
  // Os ids das abas são simples (sem acento nem espaço): o hash é comparado como veio,
  // sem decodeURIComponent, que quebraria a página com um endereço como "#%".
  const id = location.hash.slice(1);
  const atual = telas.find((tela) => tela.id === id) ?? telas[0];

  linksMenu.forEach((link) => {
    const ativo = link.getAttribute("href") === `#${atual.id}`;
    link.classList.toggle("menu__link--ativo", ativo);
    if (ativo) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  moverPilula($("#menu-pilula"), $(".menu__link--ativo"));
  const titulo = atual.querySelector(".aba-tela__titulo");
  const noInicio = atual.id === "inicio";
  document.title = noInicio ? "Hanami" : `${titulo.textContent} | Hanami`;

  const anterior = abasIniciadas && telas.find((tela) => !tela.hidden && tela !== atual);
  const estaTroca = ++trocaAtual;
  abasIniciadas = true;

  function entrar() {
    if (estaTroca !== trocaAtual) return;
    telas.forEach((tela) => {
      tela.hidden = tela !== atual;
      tela.classList.remove("aba-tela--saindo");
    });
    // O aviso de demonstração fica só nas abas do app; no início ele cobriria o lobby
    document.documentElement.classList.toggle("no-inicio", noInicio);
    atual.classList.remove("aba-tela--entrando");
    void atual.offsetWidth; // força o navegador a reiniciar a animação
    atual.classList.add("aba-tela--entrando", "animar-barras");
    setTimeout(() => atual.classList.remove("animar-barras"), 1400); // 0,5 s de espera + 0,8 s
    // A pílula dos filtros só pode ser medida com a aba visível.
    moverPilula($("#abas-pilula"), $(".aba--ativa"));
    window.scrollTo({ top: 0, behavior: "instant" });
    if (focar) titulo.focus({ preventScroll: true });
  }

  // A aba anterior some rapidinho antes da nova entrar
  if (anterior) {
    anterior.classList.add("aba-tela--saindo");
    setTimeout(entrar, 150);
  } else {
    entrar();
  }
}

function iniciarAbas() {
  document.documentElement.classList.add("com-abas");
  window.addEventListener("hashchange", () => mostrarAba(true));
  window.addEventListener("resize", moverPilulas);
  document.fonts.ready.then(moverPilulas);
  mostrarAba(false);
}

// ---------- Início (lobby) ----------

// Cada faixa de pranchas anda de 0 a -50%: o trilho é uma metade repetida duas vezes,
// então o fim da volta é igual ao começo e o loop não tem emenda. Cada metade precisa
// passar da largura da tela (o conjunto de 6 pranchas tem uns 2.350 px), senão abre um
// vão em telas largas: o conjunto se repete quantas vezes for preciso.
// As cópias são só enfeite (alt="").
function prepararInicio() {
  const largura = Math.max(screen.width, window.innerWidth);
  const repeticoes = Math.max(1, Math.ceil(largura / 2200));
  for (const trilho of document.querySelectorAll(".faixa__trilho")) {
    const conjunto = [...trilho.children];
    for (let i = 1; i < repeticoes; i++) {
      for (const prancha of conjunto) trilho.append(prancha.cloneNode());
    }
    for (const prancha of [...trilho.children]) trilho.append(prancha.cloneNode());
  }
  for (const lugar of document.querySelectorAll(".destaque__icone")) {
    lugar.append(icone(lugar.dataset.icone, 20));
  }
  // Com a aba do navegador escondida, as faixas param (não gastam nada à toa)
  document.addEventListener("visibilitychange", () => {
    document.documentElement.classList.toggle("pagina-escondida", document.hidden);
  });
}

// Brilho que segue o mouse nos cartões (.spot). Um ouvinte só, na página toda,
// porque os cartões são recriados a cada atualização da lista.
document.addEventListener("pointermove", (evento) => {
  const cartao = evento.target.closest?.(".spot");
  if (!cartao) return;
  const caixa = cartao.getBoundingClientRect();
  cartao.style.setProperty("--mx", `${evento.clientX - caixa.left}px`);
  cartao.style.setProperty("--my", `${evento.clientY - caixa.top}px`);
});

// ---------- Início ----------

async function mostrarAvisoDemo() {
  const { demo } = await api("/info");
  $("#aviso-demo").hidden = !demo;
}

$("#form-catalogo").addEventListener("submit", buscarNoCatalogo);
$("#abas").addEventListener("click", escolherAba);
$("#filtro-titulo").addEventListener("input", filtrarPorTitulo);
$("#ordem").value = estado.ordem;
$("#ordem").addEventListener("change", (evento) => {
  estado.ordem = evento.target.value;
  salvarOrdem(estado.ordem);
  carregarLista().catch((erro) => mostrarMensagem(erro.message, true));
});
$("#form-comentario").addEventListener("submit", enviarComentario);
$("#form-editar").addEventListener("submit", salvarEdicao);
for (let n = 10; n >= 1; n--) $("#editar-nota").add(new Option(String(n), String(n)));
$("#arquivo-backup").addEventListener("change", importarBackup);
for (const dialogo of document.querySelectorAll("dialog")) {
  dialogo.addEventListener("click", fecharAoClicarFora);
  for (const botao of dialogo.querySelectorAll("[data-fechar]")) {
    botao.addEventListener("click", () => dialogo.close());
  }
}

prepararInicio();
iniciarAbas();
mostrarAvisoDemo().catch(() => {});
atualizarTudo().catch(() =>
  mostrarAviso($("#aviso-lista"), "Não consegui falar com a API. Ela está rodando?"),
);
