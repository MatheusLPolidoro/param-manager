/*
 * Tabela de parâmetros e o painel de detalhe/edição.
 *
 * A tabela mostra metadado; o valor só é buscado quando uma linha é
 * aberta. Não é economia de bytes: é o que evita envelope de `secret`
 * atravessando o IPC a cada redesenho.
 */

import { formatarData, formatarDataRelativa, t } from '../i18n.js';
import { chipDeEstado } from '../estado.js';
import { confirmar, ligarNavegacaoDeLinhas, toast } from '../a11y.js';
import { controlePaginacao, paginar } from '../paginacao.js';
import { aplicarFiltro, barraDeFiltro } from '../filtros.js';
import { ligarNormalizacaoDeChave } from '../entrada.js';
import { icone, iconeDoTipo, prefixarIcone } from '../icons.js';
import { criarEditor, expandirEditor, podeExpandir } from '../campos.js';
import {
  appAtual,
  excluirParam,
  filtroMudou,
  gravarParam,
  paginaDeParams,
  selecionarParam,
  state,
  tamanhoDeParams,
  validarParam,
} from '../store.js';

// Editor do campo de valor em vigor, montado por `campoDeValor`. É por
// ele que `salvarParam` lê o valor — editores compostos (lista,
// dicionário, usuários) não teriam um `getElementById` para oferecer.
let editorAtual = null;

// App do rascunho em edição, para descartá-lo ao trocar de app.
let ultimoApp = null;

// Parâmetro que o painel está exibindo, para saber se um redesenho é
// "o mesmo de novo" (preservar o digitado) ou "outro" (recomeçar).
let ultimoDetalhe = null;

// Campos que a tela é dona e recompõe ao salvar. Tudo que NÃO estiver
// aqui é metadado que o formulário não edita e precisa voltar intacto no
// payload — ver o comentário em `salvarParam`.
const CAMPOS_DO_FORMULARIO = new Set([
  'name',
  'value',
  'type',
  'param_type',
  'description',
  'user_editable',
  // não são payload: vêm do sidecar e o servidor não os aceita
  'state',
  'updated_at',
  'last_error',
  'erro',
  'novo',
]);

// Campos de metadado que a aba de detalhe exibe como somente leitura,
// na ordem em que fazem sentido para quem opera.
const CAMPOS_INFORMATIVOS = [
  'min_length',
  'max_length',
  'min_value',
  'max_value',
  'referenced_params',
];

let editando = null;

function tiposDisponiveis() {
  const catalogo = state.catalogo || {};
  return catalogo.types || ['string'];
}

function tiposSensiveis() {
  const catalogo = state.catalogo || {};
  return catalogo.sensitive || ['secret', 'user', 'users'];
}

export function desenharParams() {
  const corpo = document.getElementById('corpo-params');
  const vazio = document.getElementById('params-vazio');
  corpo.replaceChildren();

  // Um rascunho de edição pertence ao app onde nasceu. Trocar de app —
  // ou excluir o app — precisa descartá-lo, senão o painel da direita
  // continua oferecendo "Salvar" num parâmetro de outro lugar.
  if (state.appSelecionado !== ultimoApp) {
    ultimoApp = state.appSelecionado;
    editando = null;
  }

  desenharCabecalhoDoApp();

  if (!state.appSelecionado) {
    vazio.hidden = false;
    vazio.textContent = t('params.semApp');
    return;
  }
  if (!state.params.length) {
    document.getElementById('filtro-params').replaceChildren();
    vazio.hidden = false;
    vazio.textContent = t('params.vazio');
    return;
  }

  desenharFiltroDeParams();

  const visiveis = paramsVisiveis();
  if (!visiveis.length) {
    vazio.hidden = false;
    vazio.textContent = t('filtro.semResultado');
    document.getElementById('rodape-params').replaceChildren();
    return;
  }
  vazio.hidden = true;

  const pagina = paginar(visiveis, state.paginaParams, state.tamanhoParams);
  const rodape = document.getElementById('rodape-params');
  rodape.replaceChildren();

  pagina.itens.forEach((param) => {
    const linha = document.createElement('tr');
    linha.dataset.nome = param.name;
    linha.tabIndex = -1;
    linha.setAttribute(
      'aria-selected',
      param.name === state.paramSelecionado ? 'true' : 'false'
    );
    linha.addEventListener('click', () => abrirParam(param.name));

    const nome = document.createElement('td');
    nome.className = 'mono';
    nome.textContent = param.name;

    // Ícone + nome: a família do tipo é reconhecível de relance numa
    // tabela longa, e o texto continua lá para quem não vê o desenho.
    const tipo = document.createElement('td');
    const marca = document.createElement('span');
    marca.className = 'com-icone';
    const desenho = iconeDoTipo(param.type);
    if (desenho) {
      marca.append(desenho);
    }
    marca.append(document.createTextNode(param.type || '—'));
    tipo.append(marca);

    const estado = document.createElement('td');
    estado.append(chipDeEstado(param.state));

    // Relativo na coluna, absoluto no `title`: "há 2 horas" responde a
    // pergunta de varredura ("o que mexi agora?"), e a data exata
    // continua a um repouso do ponteiro para quem precisa dela.
    const atualizado = document.createElement('td');
    atualizado.textContent = formatarDataRelativa(param.updated_at);
    atualizado.title = formatarData(param.updated_at);

    linha.append(nome, tipo, estado, atualizado);
    corpo.append(linha);
  });

  // A primeira linha é o ponto de entrada por teclado; as demais são
  // alcançadas por seta, como `role="grid"` promete.
  const primeira = corpo.querySelector('tr');
  if (primeira) {
    primeira.tabIndex = 0;
  }

  const controle = controlePaginacao(
    pagina,
    paginaDeParams,
    'params.paginacao',
    { tamanho: state.tamanhoParams, aoTrocarTamanho: tamanhoDeParams }
  );
  if (controle) {
    rodape.append(controle);
  }
}

/** Nome, descrição e tipo entram na busca livre; o tipo também filtra. */
function paramsVisiveis() {
  return aplicarFiltro(
    state.params,
    state.filtroParams,
    [(p) => p.name, (p) => p.description, (p) => p.type],
    (p) => p.type
  );
}

function desenharFiltroDeParams() {
  const area = document.getElementById('filtro-params');
  const campoAtual = area.querySelector('input');
  const tinhaFoco = document.activeElement === campoAtual;
  const posicao = tinhaFoco ? campoAtual.selectionStart : 0;

  // Só os tipos que existem NESTE app: oferecer os quinze do catálogo
  // faria a maioria devolver lista vazia.
  const tipos = [...new Set(state.params.map((p) => p.type).filter(Boolean))]
    .sort();

  const { elemento, entrada } = barraDeFiltro({
    filtro: state.filtroParams,
    aoMudar: () => filtroMudou('params'),
    tipos,
    rotulo: t('filtro.params'),
    total: state.params.length,
    exibidos: paramsVisiveis().length,
  });

  area.replaceChildren(elemento);
  if (tinhaFoco) {
    entrada.focus();
    entrada.setSelectionRange(posicao, posicao);
  }
}

/**
 * Nome e descrição do app acima da tabela.
 *
 * A descrição existia no dado desde sempre e não aparecia em lugar
 * nenhum — quem batizou o app de `crm` era o único que sabia o que ele
 * era. Sem descrição, o espaço não fica reservado: linha vazia é ruído.
 */
function desenharCabecalhoDoApp() {
  const titulo = document.getElementById('params-titulo');
  const descricao = document.getElementById('app-descricao');
  const app = appAtual();

  titulo.textContent = state.appSelecionado
    ? state.appSelecionado
    : t('params.titulo');

  const texto = app && typeof app === 'object' ? app.description : '';
  descricao.textContent = texto || '';
  descricao.hidden = !texto;
}

async function abrirParam(nome) {
  try {
    await selecionarParam(nome);
    editando = null;
    desenharDetalhe();
  } catch (erro) {
    toast(erro.message, 'error');
  }
}

/* ------------------------------------------------------------ detalhe --- */

/**
 * O que o painel está exibindo agora — rascunho ou registro carregado.
 *
 * Preserva o que o formulário já tem digitado, para que voltar do editor
 * expandido não descarte nome, tipo ou descrição alterados na tela.
 */
function dadosEmEdicao() {
  const base = editando || state.detalhe || {};
  const nome = document.getElementById('detalhe-nome');
  const tipo = document.getElementById('detalhe-tipo');
  const descricao = document.getElementById('detalhe-descricao');
  return {
    ...base,
    novo: Boolean(editando && editando.novo),
    name: nome ? nome.value : base.name,
    type: tipo ? tipo.value : base.type,
    description: descricao ? descricao.value : base.description,
  };
}

/**
 * Monta o campo de valor com o editor do tipo.
 *
 * O editor vem de `campos.js` e devolve `{ elemento, ler }` — ler pelo
 * objeto, e não por `getElementById`, é o que permite editores compostos
 * (lista, dicionário, usuários) sem inventar um id por linha.
 */
function campoDeValor(tipo, valor, contexto) {
  const campo = document.createElement('div');
  campo.className = 'field';

  const cabecalho = document.createElement('div');
  cabecalho.className = 'field__cabecalho';

  const rotulo = document.createElement('span');
  rotulo.className = 'field__label';
  rotulo.id = 'rotulo-valor';
  rotulo.textContent = t('params.campo.valor');
  cabecalho.append(rotulo);

  const editor = criarEditor(tipo, valor, contexto);

  if (podeExpandir(tipo)) {
    const expandir = document.createElement('button');
    expandir.type = 'button';
    expandir.className = 'btn btn--ghost com-icone btn--compacto';
    expandir.append(
      icone('expandir'),
      document.createTextNode(t('params.expandir'))
    );
    expandir.addEventListener('click', async () => {
      // Parte do valor ATUAL do editor, não do gravado: quem já digitou
      // algo e clica em expandir espera continuar de onde parou.
      let atual;
      try {
        atual = editor.ler();
      } catch {
        atual = valor;
      }
      const resultado = await expandirEditor(tipo, atual, contexto);
      if (resultado) {
        // Redesenha o painel com o valor trazido de volta. Trocar o nó
        // do editor no lugar deixaria `editorAtual` apontando para um
        // elemento fora da árvore.
        editando = { ...dadosEmEdicao(), value: resultado.valor };
        desenharDetalhe();
      }
    });
    cabecalho.append(expandir);
  }

  campo.append(cabecalho);
  // O editor pode ser um grupo (radiogroup, fieldset), e aí `<label for>`
  // não se aplica: quem nomeia é o `aria-labelledby`.
  editor.elemento.setAttribute('aria-labelledby', 'rotulo-valor');
  campo.append(editor.elemento);

  const dica = t(`params.dica.${tipo}`);
  if (dica !== `params.dica.${tipo}`) {
    const texto = document.createElement('span');
    texto.className = 'field__hint';
    texto.textContent = dica;
    campo.append(texto);
  }

  return { campo, editor };
}

/**
 * Bloco somente leitura com limites, estado e data.
 *
 * Somente leitura de propósito: são regras que o servidor aplica e que
 * o formulário não edita hoje. Mostrá-las explica por que um valor foi
 * recusado lá e passou aqui — que é a dúvida que o `max_length` padrão
 * de 30 produz com frequência.
 */
function blocoInformativo(dados, novo) {
  if (novo) {
    return null;
  }

  const linhas = CAMPOS_INFORMATIVOS.filter(
    (campo) => dados[campo] !== undefined && dados[campo] !== null
  ).map((campo) => [
    t(`params.meta.${campo}`),
    Array.isArray(dados[campo]) ? dados[campo].join(', ') : dados[campo],
  ]);

  if (dados.state) {
    linhas.unshift([t('params.coluna.estado'), t(`estado.${dados.state}`)]);
  }
  if (dados.type) {
    linhas.unshift([t('params.campo.tipo'), dados.type]);
  }
  if (dados.updated_at) {
    linhas.push([
      t('params.coluna.atualizado'),
      `${formatarDataRelativa(dados.updated_at)} · ${formatarData(dados.updated_at)}`,
    ]);
  }
  if (state.appSelecionado) {
    linhas.unshift([t('params.meta.app'), state.appSelecionado]);
  }
  if (!linhas.length) {
    return null;
  }

  const bloco = document.createElement('dl');
  bloco.className = 'meta';

  linhas.forEach(([rotulo, valor]) => {
    const termo = document.createElement('dt');
    termo.className = 'eyebrow';
    termo.textContent = rotulo;
    const definicao = document.createElement('dd');
    definicao.className = 'definicao mono';
    definicao.textContent = String(valor);
    bloco.append(termo, definicao);
  });

  if (dados.last_error) {
    const termo = document.createElement('dt');
    termo.className = 'eyebrow';
    termo.textContent = t('params.meta.last_error');
    const definicao = document.createElement('dd');
    definicao.className = 'definicao';
    definicao.textContent = dados.last_error;
    bloco.append(termo, definicao);
  }

  return bloco;
}

export function desenharDetalhe() {
  const painel = document.getElementById('detalhe');
  const corpo = document.getElementById('detalhe-corpo');
  const shell = document.getElementById('app-body');

  // Se o painel já mostra ESTE parâmetro e há algo digitado, o que está
  // na tela vale mais que o que veio do store: redesenhar por cima
  // apagaria a edição em curso. Acontece quando algo fora do formulário
  // muda — a listagem recarregando, por exemplo.
  const alvo = (editando || state.detalhe || {}).name;
  if (alvo && corpo.querySelector('#detalhe-nome') && alvo === ultimoDetalhe) {
    editando = dadosEmEdicao();
  }
  ultimoDetalhe = alvo || null;

  corpo.replaceChildren();

  const dados = editando || state.detalhe;
  if (!dados) {
    shell.dataset.detail = 'hidden';
    painel.hidden = true;
    return;
  }
  shell.dataset.detail = 'shown';
  painel.hidden = false;

  const novo = Boolean(editando && editando.novo);
  const sensiveis = tiposSensiveis();

  document.getElementById('detalhe-titulo').textContent = novo
    ? t('params.novo.titulo')
    : dados.name;

  if (dados.erro) {
    const alerta = document.createElement('div');
    alerta.className = 'alert alert--warn';
    alerta.setAttribute('role', 'status');
    alerta.textContent = t('params.valorIlegivel', { erro: dados.erro });
    corpo.append(alerta);
  }

  const formulario = document.createElement('form');
  formulario.className = 'stack';
  formulario.id = 'form-param';
  formulario.noValidate = true;

  // nome
  const campoNome = document.createElement('div');
  campoNome.className = 'field';
  const rotuloNome = document.createElement('label');
  rotuloNome.className = 'field__label';
  rotuloNome.htmlFor = 'detalhe-nome';
  rotuloNome.textContent = t('params.campo.nome');
  const entradaNome = document.createElement('input');
  entradaNome.className = 'input mono';
  entradaNome.id = 'detalhe-nome';
  entradaNome.value = dados.name || '';
  entradaNome.disabled = !novo;
  entradaNome.required = true;
  ligarNormalizacaoDeChave(entradaNome);
  campoNome.append(rotuloNome, entradaNome);

  // tipo
  const campoTipo = document.createElement('div');
  campoTipo.className = 'field';
  const rotuloTipo = document.createElement('label');
  rotuloTipo.className = 'field__label';
  rotuloTipo.htmlFor = 'detalhe-tipo';
  rotuloTipo.textContent = t('params.campo.tipo');
  const selecaoTipo = document.createElement('select');
  selecaoTipo.className = 'select';
  selecaoTipo.id = 'detalhe-tipo';
  tiposDisponiveis().forEach((tipo) => {
    const opcao = document.createElement('option');
    opcao.value = tipo;
    opcao.textContent = tipo;
    opcao.selected = tipo === (dados.type || 'string');
    selecaoTipo.append(opcao);
  });
  campoTipo.append(rotuloTipo, selecaoTipo);

  const tipoAtual = dados.type || 'string';
  const { campo: campoValor, editor } = campoDeValor(tipoAtual, dados.value, {
    sensiveis,
    // `reference` escolhe entre os parâmetros que existem no app; sem
    // essa lista o campo não teria o que oferecer.
    paramsDoApp: state.params.map((p) => p.name),
    nomeAtual: dados.name,
    referencedParams: dados.referenced_params,
  });
  editorAtual = editor;

  // Trocar o tipo troca o editor: um textarea de JSON para um `int` só
  // produziria recusa do servidor mais tarde.
  selecaoTipo.addEventListener('change', () => {
    editando = {
      ...dados,
      novo,
      type: selecaoTipo.value,
      name: entradaNome.value,
      value: null,
    };
    desenharDetalhe();
  });

  // descrição
  const campoDescricao = document.createElement('div');
  campoDescricao.className = 'field';
  const rotuloDescricao = document.createElement('label');
  rotuloDescricao.className = 'field__label';
  rotuloDescricao.htmlFor = 'detalhe-descricao';
  rotuloDescricao.textContent = t('params.campo.descricao');
  // Textarea, e não input de uma linha: descrição de parâmetro costuma
  // explicar quando mexer nele, e isso não cabe numa linha. Cresce com o
  // conteúdo e para de crescer no limite, para não empurrar os botões
  // para fora da tela.
  const entradaDescricao = document.createElement('textarea');
  entradaDescricao.className = 'textarea textarea--prosa';
  entradaDescricao.id = 'detalhe-descricao';
  entradaDescricao.rows = 2;
  entradaDescricao.value = dados.description || '';
  campoDescricao.append(rotuloDescricao, entradaDescricao);

  // user_editable
  const linhaEditavel = document.createElement('div');
  linhaEditavel.className = 'checkbox-row';
  const marcaEditavel = document.createElement('input');
  marcaEditavel.type = 'checkbox';
  marcaEditavel.id = 'detalhe-editavel';
  marcaEditavel.checked = dados.user_editable === true;
  const rotuloEditavel = document.createElement('label');
  rotuloEditavel.htmlFor = 'detalhe-editavel';
  rotuloEditavel.textContent = t('params.campo.userEditable');
  linhaEditavel.append(marcaEditavel, rotuloEditavel);

  const erro = document.createElement('div');
  erro.className = 'field__error';
  erro.id = 'detalhe-erro';
  erro.setAttribute('role', 'alert');

  const avisos = document.createElement('div');
  avisos.className = 'stack stack--tight';
  avisos.id = 'detalhe-avisos';
  avisos.setAttribute('aria-live', 'polite');

  const acoes = document.createElement('div');
  acoes.className = 'btn-row';
  const salvar = document.createElement('button');
  salvar.type = 'submit';
  salvar.className = 'btn btn--primary';
  salvar.textContent = t('acoes.salvar');
  acoes.append(salvar);

  if (!novo) {
    const excluir = document.createElement('button');
    excluir.type = 'button';
    excluir.className = 'btn btn--danger';
    excluir.textContent = t('acoes.excluir');
    excluir.addEventListener('click', () => removerParam(dados.name));
    acoes.append(excluir);
  }

  const fechar = document.createElement('button');
  fechar.type = 'button';
  fechar.className = 'btn btn--ghost';
  fechar.textContent = t('acoes.fechar');
  fechar.addEventListener('click', fecharDetalhe);
  acoes.append(fechar);

  formulario.append(
    campoNome,
    campoTipo,
    campoValor,
    campoDescricao,
    linhaEditavel,
    avisos,
    erro,
    acoes
  );

  const informativos = blocoInformativo(dados, novo);
  if (informativos) {
    formulario.append(informativos);
  }
  formulario.addEventListener('submit', (evento) => {
    evento.preventDefault();
    salvarParam(novo);
  });
  corpo.append(formulario);
}

async function salvarParam(novo) {
  const erro = document.getElementById('detalhe-erro');
  erro.textContent = '';

  const nome = document.getElementById('detalhe-nome').value.trim();
  if (!nome) {
    erro.textContent = t('params.erro.nomeVazio');
    return;
  }

  let valor;
  try {
    valor = editorAtual.ler();
  } catch (excecao) {
    // A mensagem já vem pronta do editor — ela nomeia onde o JSON
    // quebrou, e reescrevê-la aqui perderia isso.
    erro.textContent = excecao.message;
    return;
  }

  // Metadado que o formulário não edita — limites, `referenced_params` e
  // o que o servidor vier a acrescentar — é reenviado como veio.
  //
  // Não é zelo: em modo local o `upsert_param` **substitui o payload
  // inteiro**, então um campo omitido aqui é um campo apagado no disco.
  // Editar o valor de um parâmetro chegou a destruir o `max_length` dele
  // por causa disto. `CAMPOS_DO_FORMULARIO` são os que a tela é dona e
  // recompõe abaixo; o resto passa intacto.
  const original = (editando && editando.novo ? null : state.detalhe) || {};
  const corpo = { app: state.appSelecionado };
  for (const [chave, conteudo] of Object.entries(original)) {
    if (!CAMPOS_DO_FORMULARIO.has(chave) && conteudo !== undefined) {
      corpo[chave] = conteudo;
    }
  }

  corpo.name = nome;
  corpo.value = valor;
  corpo.param_type = document.getElementById('detalhe-tipo').value;

  const descricao = document.getElementById('detalhe-descricao').value.trim();
  if (descricao) {
    corpo.description = descricao;
  }
  // Só vai no payload quando marcado: a lib distingue "não enviado" de
  // "enviado como false", e é assim que o servidor preserva o default.
  if (document.getElementById('detalhe-editavel').checked) {
    corpo.user_editable = true;
  }
  // `reference` grava duas listas: o que pode ser referenciado e o que
  // vale agora. A segunda é subconjunto da primeira, por construção.
  if (editorAtual.referenciaveis) {
    corpo.referenced_params = editorAtual.referenciaveis();
  }

  // Conselho antes de gravar, nunca veto: quem valida de verdade é o
  // servidor, na sincronização. Bloquear aqui significaria reimplementar
  // a regra dele no cliente — o erro que o envelope criptográfico já
  // custou caro neste produto.
  const avisos = await validarParam(corpo);
  mostrarAvisos(avisos);

  try {
    await gravarParam(corpo);
    editando = null;
    desenharDetalhe();
    mostrarAvisos(avisos);
    toast(t(novo ? 'params.criado' : 'params.salvo', { nome }), 'ok');
  } catch (excecao) {
    // Recusa de tipo sensível em modo local vem da lib com a explicação
    // pronta: mostrar como veio, sem reinterpretar.
    erro.textContent = excecao.message;
  }
}

/**
 * Pinta os avisos do catálogo como aviso, não como erro.
 *
 * A distinção visual importa: erro impediu de salvar, aviso não. Pintar
 * os dois igual ensina o usuário a ignorar os dois.
 */
function mostrarAvisos(avisos) {
  const area = document.getElementById('detalhe-avisos');
  if (!area) {
    return;
  }
  area.replaceChildren();
  if (!avisos.length) {
    return;
  }

  const bloco = document.createElement('div');
  bloco.className = 'alert alert--warn';
  bloco.setAttribute('role', 'status');

  const titulo = document.createElement('strong');
  titulo.textContent = t('params.avisos.titulo', { total: avisos.length });
  bloco.append(titulo);

  avisos.forEach((aviso) => {
    const linha = document.createElement('p');
    linha.className = 'alert__text';
    // Texto da lib, exibido como veio: ele nomeia a regra e o limite.
    linha.textContent = aviso;
    bloco.append(linha);
  });
  area.append(bloco);
}

async function removerParam(nome) {
  const confirmado = await confirmar({
    titulo: t('params.excluir.titulo'),
    texto: t('params.excluir.texto', { nome, app: state.appSelecionado }),
    confirmar: t('acoes.excluir'),
    perigoso: true,
    digitar: nome,
  });
  if (!confirmado) {
    return;
  }
  try {
    await excluirParam(nome);
    editando = null;
    desenharDetalhe();
    toast(t('params.excluido', { nome }), 'ok');
  } catch (erro) {
    toast(erro.message, 'error');
  }
}

/** Fecha o painel de detalhe, descartando o rascunho. */
export function fecharDetalhe() {
  editando = null;
  ultimoDetalhe = null;
  selecionarParam(null).then(desenharDetalhe);
}

/**
 * Clicar no vazio da área de conteúdo fecha o painel.
 *
 * O escopo é **só a coluna do meio**, e isso é deliberado. "Qualquer
 * lugar fora do painel" parece mais simples e está errado: o botão de
 * tema, o seletor de idioma e a paginação da trilha ficam fora dele, e
 * fechar o painel ao trocar de tema descartaria o rascunho de quem
 * estava editando — exatamente a perda que este lote veio corrigir.
 *
 * Dentro do conteúdo, três regiões não fecham: a tabela (clicar numa
 * linha troca de parâmetro), o filtro e o botão de novo parâmetro. A
 * trilha também não precisa fechar — escolher outro app já limpa o
 * detalhe pelo store.
 *
 * Escuta em captura porque a linha da tabela chama `stopPropagation` em
 * alguns caminhos, e captura chega antes.
 */
function ligarFecharAoClicarFora() {
  document.addEventListener(
    'pointerdown',
    (evento) => {
      const painel = document.getElementById('detalhe');
      if (painel.hidden) {
        return;
      }
      const alvo = evento.target;
      const noConteudo = alvo.closest('#conteudo');
      if (
        !noConteudo ||
        painel.contains(alvo) ||
        alvo.closest('.table-wrap') ||
        alvo.closest('.filtro') ||
        alvo.closest('.paginacao') ||
        alvo.closest('dialog') ||
        alvo.closest('#btn-novo-param')
      ) {
        return;
      }
      fecharDetalhe();
    },
    true
  );

  // `Esc` fecha também, e é o que o teclado espera de um painel aberto.
  document.addEventListener('keydown', (evento) => {
    const painel = document.getElementById('detalhe');
    if (
      evento.key === 'Escape' &&
      !painel.hidden &&
      !document.querySelector('dialog[open]')
    ) {
      fecharDetalhe();
    }
  });
}

export function ligarAcoesDeParam() {
  const tabela = document.getElementById('tabela-params');
  ligarNavegacaoDeLinhas(tabela, abrirParam);
  ligarFecharAoClicarFora();

  document.getElementById('btn-novo-param').addEventListener('click', () => {
    if (!state.appSelecionado) {
      toast(t('params.semApp'), 'error');
      return;
    }
    editando = {
      novo: true,
      name: '',
      type: 'string',
      value: '',
      description: '',
    };
    desenharDetalhe();
    const campo = document.getElementById('detalhe-nome');
    if (campo) {
      campo.focus();
    }
  });
}
