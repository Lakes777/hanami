// Front da Lista de Animes: conversa com a própria API usando fetch().
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
};

const $ = (seletor) => document.querySelector(seletor);

// Lixeira da Lucide (lucide.dev, licença ISC), montada elemento por elemento (nada de HTML em texto).
function iconeLixeira() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [nome, valor] of Object.entries({
    viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor",
    "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
  })) svg.setAttribute(nome, valor);
  for (const d of ["M3 6h18", "M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6", "M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2",
    "M10 11v6", "M14 11v6"]) {
    const caminho = document.createElementNS("http://www.w3.org/2000/svg", "path");
    caminho.setAttribute("d", d);
    svg.append(caminho);
  }
  return svg;
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

// ---------- Minha lista ----------

function textoTotal(anime) {
  // 1087 vira "1.087"
  const total = anime.total_episodios === null ? "?" : anime.total_episodios.toLocaleString("pt-BR");
  return `/ ${total} eps.`;
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

function escolherEpisodio(anime, campo) {
  // Espera a pessoa parar de digitar ou de clicar nas setinhas antes de salvar.
  // Cada campo tem o próprio temporizador, para um cartão não cancelar o outro.
  clearTimeout(campo.temporizador);
  campo.temporizador = setTimeout(() => {
    if (campo.value === "") return; // apagou para digitar outro número
    const vistos = Number(campo.value);
    const total = anime.total_episodios;
    if (!Number.isInteger(vistos) || vistos < 0 || (total !== null && vistos > total)) {
      mostrarMensagem(total === null
        ? "Digite um número inteiro de episódios."
        : `Digite um número de 0 a ${total}.`, true);
      campo.value = anime.episodios_vistos;
      return;
    }
    if (vistos !== anime.episodios_vistos) editar(anime.id, mudancasPorEpisodios(anime, vistos));
  }, 700);
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
    dados.total_episodios && `${dados.total_episodios} eps.`,
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

function criarFranquia(temporadas, visiveis) {
  const quadro = $("#molde-franquia").content.firstElementChild.cloneNode(true);
  const nome = temporadas[0].titulo; // a primeira a estrear dá nome à franquia
  quadro.querySelector(".franquia__titulo").textContent = nome;
  const soTemporadas = temporadas.every((a) => !(a.tipo in NOMES_DOS_TIPOS));
  quadro.querySelector(".franquia__info").textContent =
    `${temporadas.length} ${soTemporadas ? "temporadas" : "itens"} na lista`;
  quadro.querySelector('[data-acao="temporadas"]').addEventListener("click", () =>
    abrirTemporadas(temporadas.at(-1), nome),
  );
  quadro.querySelector(".franquia__grade").replaceChildren(...visiveis.map(criarCartaoAnime));
  return quadro;
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

function criarCartaoAnime(anime) {
  const cartao = $("#molde-anime").content.firstElementChild.cloneNode(true);
  preencherCapa(cartao, anime, () => abrirDetalhes(anime));
  cartao.querySelector(".cartao__titulo").textContent = anime.titulo;

  const rotulo = estado.rotulos.get(anime.id);
  const temporada = cartao.querySelector(".cartao__temporada");
  temporada.textContent = rotulo ?? "";
  temporada.hidden = !rotulo;
  // Anime sozinho: o link procura as outras temporadas. Em franquia, o botão fica no quadro.
  const outras = cartao.querySelector('[data-acao="temporadas"]');
  outras.hidden = Boolean(rotulo) || anime.mal_id === null;
  outras.addEventListener("click", () => abrirTemporadas(anime, anime.titulo));
  const vistos = cartao.querySelector('[data-campo="vistos"]');
  vistos.value = anime.episodios_vistos;
  if (anime.total_episodios !== null) vistos.max = anime.total_episodios;
  vistos.addEventListener("input", () => escolherEpisodio(anime, vistos));
  cartao.querySelector(".episodios__total").textContent = textoTotal(anime);

  const porcentagem = anime.total_episodios
    ? (100 * anime.episodios_vistos) / anime.total_episodios
    : 0;
  cartao.querySelector(".progresso__barra").style.width = `${porcentagem}%`;

  const status = cartao.querySelector('[data-campo="status"]');
  status.value = anime.status;
  status.addEventListener("change", () => editar(anime.id, { status: status.value }));

  const nota = cartao.querySelector('[data-campo="nota"]');
  for (let n = 10; n >= 1; n--) nota.add(new Option(String(n), String(n)));
  nota.value = anime.nota ?? "";
  nota.addEventListener("change", () =>
    editar(anime.id, { nota: nota.value ? Number(nota.value) : null }),
  );

  const mais1 = cartao.querySelector('[data-acao="mais1"]');
  const acabou = anime.total_episodios !== null && anime.episodios_vistos >= anime.total_episodios;
  mais1.disabled = acabou;
  mais1.addEventListener("click", () =>
    editar(anime.id, mudancasPorEpisodios(anime, anime.episodios_vistos + 1)),
  );

  const comentarios = cartao.querySelector('[data-acao="comentarios"]');
  comentarios.textContent = anime.comentarios ? `Comentários (${anime.comentarios})` : "Comentar";
  comentarios.addEventListener("click", () => abrirComentarios(anime));

  const lixeira = cartao.querySelector('[data-acao="remover"]');
  lixeira.append(iconeLixeira());
  lixeira.setAttribute("aria-label", `Remover ${anime.titulo}`);
  lixeira.title = "Remover da lista";
  lixeira.addEventListener("click", () => remover(anime));
  return cartao;
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
    grupos.push({ visiveis, temporadas: estado.franquias.get(visiveis[0].franquia) ?? visiveis });
  }
  const elementos = ordenarGrupos(grupos).flatMap(({ visiveis, temporadas }) =>
    temporadas.length > 1 ? [criarFranquia(temporadas, visiveis)] : visiveis.map(criarCartaoAnime),
  );
  $("#lista").replaceChildren(...elementos);

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
  cartao.querySelector(".cartao__titulo").textContent = anime.titulo;

  const info = [
    anime.tipo,
    anime.ano,
    anime.total_episodios && `${anime.total_episodios} eps.`,
    anime.nota_mal && `nota ${anime.nota_mal} no MAL`,
  ].filter(Boolean);
  cartao.querySelector(".cartao__info").textContent = info.join(" · ");
  cartao.querySelector(".cartao__generos").textContent = anime.generos.slice(0, 3).join(", ");

  cartao.querySelector("button").addEventListener("click", async (evento) => {
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
    const botao = cartao.querySelector("button");
    botao.disabled = jaNaLista;
    botao.textContent = jaNaLista ? "✓ Na sua lista" : "+ Adicionar";
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
    mostrarAviso(aviso, animes.length ? "" : `Nenhum anime encontrado para "${termo}".`);
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
  document.title = `${titulo.textContent} | Lista de Animes`;

  const anterior = abasIniciadas && telas.find((tela) => !tela.hidden && tela !== atual);
  const estaTroca = ++trocaAtual;
  abasIniciadas = true;

  function entrar() {
    if (estaTroca !== trocaAtual) return;
    telas.forEach((tela) => {
      tela.hidden = tela !== atual;
      tela.classList.remove("aba-tela--saindo");
    });
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
for (const dialogo of document.querySelectorAll("dialog")) {
  dialogo.addEventListener("click", fecharAoClicarFora);
  dialogo.querySelector("[data-fechar]").addEventListener("click", () => dialogo.close());
}

iniciarAbas();
mostrarAvisoDemo().catch(() => {});
atualizarTudo().catch(() =>
  mostrarAviso($("#aviso-lista"), "Não consegui falar com a API. Ela está rodando?"),
);
