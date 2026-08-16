/*
 * Orquestra a subida e liga as views ao store.
 *
 * Ordem que importa: preferências → idioma → tradução do HTML → sessão →
 * dados. Traduzir depois de desenhar faria a interface piscar em inglês
 * antes de assumir o idioma escolhido.
 */

import { carregarIdioma, t, traduzirDocumento } from './i18n.js';
import { anunciar, aplicarTema, toast } from './a11y.js';
import { icone, prefixarIcone } from './icons.js';
import { ligarRail } from './rail.js';
import {
  bootstrap,
  carregarApps,
  carregarCatalogo,
  carregarSyncStatus,
  salvarPrefs,
  state,
  subscrever,
  tentarSessaoExistente,
  trocarAba,
} from './store.js';
import { desenharApps, ligarAcoesDeApp } from './views/apps.js';
import {
  desenharDetalhe,
  desenharParams,
  ligarAcoesDeParam,
} from './views/params.js';
import { desenharSync, ligarAcoesDeSync } from './views/sync.js';
import { desenharTipos, ligarAcoesDeTipos } from './views/types.js';
import { desenharSessao, ligarAcoesDeSessao } from './views/session.js';

const ABAS = ['params', 'sync', 'tipos', 'sessao'];

/**
 * Cada view acorda só com o estado que a define.
 *
 * É isto que faz trocar de página **não** reconstruir o formulário de
 * detalhe — que era onde o valor digitado se perdia — e trocar de tema
 * não redesenhar nada, já que o tema vive num atributo da raiz e não no
 * DOM das views.
 *
 * Ao acrescentar estado ao store, some a chave à lista de quem depende
 * dela. Esquecer disso produz uma tela que não atualiza — sintoma chato,
 * mas visível na hora; o contrário, redesenhar tudo, era invisível e
 * destruía trabalho.
 */
const ASSINATURAS = [
  [desenharApps, ['apps', 'appSelecionado', 'paginaApps', 'tamanhoApps',
    'filtroApps', 'pronto', 'params']],
  [desenharParams, ['params', 'paramSelecionado', 'paginaParams',
    'tamanhoParams', 'filtroParams', 'appSelecionado', 'apps']],
  [desenharDetalhe, ['detalhe', 'paramSelecionado', 'appSelecionado']],
  [desenharSync, ['sync', 'plano', 'modo', 'appSelecionado']],
  [desenharTipos, ['catalogo']],
  [desenharSessao, ['pronto', 'modo', 'instancia', 'erroSessao',
    'temStoreLocal', 'prefs']],
  [desenharRodape, ['instancia', 'modo', 'sync', 'versaoLib', 'versaoFront',
    'pronto']],
  [desenharAbas, ['aba']],
];

function desenharTudo() {
  ASSINATURAS.forEach(([desenhar]) => desenhar());
}

function desenharRodape() {
  document.getElementById('rodape-instancia').textContent = state.pronto
    ? state.instancia
    : '—';

  const modo = document.getElementById('rodape-modo');
  modo.textContent = state.modo ? t(`modo.${state.modo}`) : '—';
  modo.className = state.modo
    ? `chip chip--${state.modo === 'local' ? 'pending' : 'synced'}`
    : 'chip chip--neutral';
  modo.title = state.modo ? t(`modo.${state.modo}.explicacao`) : '';

  const pendentes = document.getElementById('rodape-pendentes');
  pendentes.textContent = t('rodape.pendentes', {
    total: state.sync.pending,
  });

  document.getElementById('rodape-versoes').textContent = t('rodape.versoes', {
    lib: state.versaoLib,
    front: state.versaoFront,
  });
}

function desenharAbas() {
  ABAS.forEach((aba) => {
    const botao = document.getElementById(`tab-${aba}`);
    const painel = document.getElementById(`painel-${aba}`);
    const ativa = state.aba === aba;
    botao.setAttribute('aria-selected', String(ativa));
    botao.tabIndex = ativa ? 0 : -1;
    painel.hidden = !ativa;
  });
}

function ligarAbas() {
  const lista = document.getElementById('abas');
  ABAS.forEach((aba) => {
    document
      .getElementById(`tab-${aba}`)
      .addEventListener('click', () => trocarAba(aba));
  });

  // `role="tablist"` promete setas; cumprir é o mínimo.
  lista.addEventListener('keydown', (evento) => {
    const atual = ABAS.indexOf(state.aba);
    let proxima = null;
    if (evento.key === 'ArrowRight') {
      proxima = ABAS[(atual + 1) % ABAS.length];
    } else if (evento.key === 'ArrowLeft') {
      proxima = ABAS[(atual - 1 + ABAS.length) % ABAS.length];
    }
    if (proxima) {
      evento.preventDefault();
      trocarAba(proxima);
      document.getElementById(`tab-${proxima}`).focus();
    }
  });
}

// Sistema → claro → escuro → sistema. O ciclo é curto o bastante para um
// botão só; um seletor de três opções custava a mesma decisão e mais
// largura no cabeçalho.
const CICLO_DE_TEMA = ['system', 'light', 'dark'];
const ICONE_DE_TEMA = { system: 'monitor', light: 'sol', dark: 'lua' };

function pintarBotaoDeTema(tema) {
  const botao = document.getElementById('btn-tema');
  botao.replaceChildren();
  const svg = icone(ICONE_DE_TEMA[tema] || 'monitor');
  if (svg) {
    botao.append(svg);
  }
  // O rótulo diz o tema ATUAL e o próximo, porque um ícone de sol
  // sozinho é ambíguo: não dá para saber se representa o estado ou a
  // ação.
  const proximo = CICLO_DE_TEMA[
    (CICLO_DE_TEMA.indexOf(tema) + 1) % CICLO_DE_TEMA.length
  ];
  const rotulo = t('prefs.tema.alternar', {
    atual: t(`prefs.tema.${tema}`),
    proximo: t(`prefs.tema.${proximo}`),
  });
  botao.setAttribute('aria-label', rotulo);
  botao.title = rotulo;
}

function ligarPreferencias() {
  const seletorIdioma = document.getElementById('seletor-idioma');

  document.getElementById('btn-tema').addEventListener('click', async () => {
    const atual = state.prefs.theme || 'system';
    const proximo = CICLO_DE_TEMA[
      (CICLO_DE_TEMA.indexOf(atual) + 1) % CICLO_DE_TEMA.length
    ];
    aplicarTema(proximo);
    await salvarPrefs({ theme: proximo });
    pintarBotaoDeTema(proximo);
    anunciar(t(`prefs.tema.${proximo}`));
  });

  seletorIdioma.addEventListener('change', async () => {
    await carregarIdioma(seletorIdioma.value);
    await salvarPrefs({ language: seletorIdioma.value });
    traduzirDocumento();
    pintarBotaoDeTema(state.prefs.theme || 'system');
    desenharTudo();
  });
}

function preencherSeletores(idiomaAtivo, tema) {
  const seletorIdioma = document.getElementById('seletor-idioma');
  seletorIdioma.replaceChildren();
  state.idiomas.forEach((idioma) => {
    const opcao = document.createElement('option');
    opcao.value = idioma;
    opcao.textContent = t(`idioma.${idioma}`);
    opcao.selected = idioma === idiomaAtivo;
    seletorIdioma.append(opcao);
  });
  pintarBotaoDeTema(tema);
}

/** Dados que só fazem sentido com sessão configurada. */
async function carregarDados() {
  try {
    await carregarCatalogo();
  } catch {
    // Catálogo é conselho; sem ele a tela de tipos fica vazia e o resto
    // funciona. Não vale derrubar a subida por isso.
  }
  await carregarApps();
  await carregarSyncStatus();
}

/**
 * Põe ícone nos controles fixos do HTML, uma vez só.
 *
 * Aqui e não no HTML porque `icons.js` monta o SVG por `createElementNS`
 * — repetir vinte linhas de `<svg>` no markup tornaria qualquer ajuste
 * de traço uma edição em vinte lugares.
 */
function ligarIcones() {
  const mapa = {
    'btn-novo-app': 'mais',
    'btn-excluir-app': 'lixeira',
    'btn-novo-param': 'mais',
    'btn-calcular-plano': 'sincronizar',
    'btn-aplicar-plano': 'sincronizar',
    'btn-atualizar-catalogo': 'etiqueta',
  };
  for (const [id, nome] of Object.entries(mapa)) {
    const elemento = document.getElementById(id);
    if (elemento) {
      prefixarIcone(elemento, nome);
    }
  }

  // O botão de nova aplicação é só o ícone: o `+` textual saía com peso
  // diferente do resto e o nome acessível já vem do `aria-label`.
  const novoApp = document.getElementById('btn-novo-app');
  novoApp.textContent = '';
  novoApp.classList.add('btn--icone');
  prefixarIcone(novoApp, 'mais');

  prefixarIcone(document.getElementById('btn-rail'), 'caixa');
}

/**
 * Gaveta da trilha de aplicações, usada só nas larguras estreitas.
 *
 * `aria-expanded` acompanha o estado porque o botão existe para leitor
 * de tela também, e ele precisa saber se a região está aberta. Fecha ao
 * escolher um app: em tela estreita a gaveta cobre a tabela, e deixá-la
 * aberta esconderia justamente o resultado do clique.
 */
function ligarGaveta() {
  const botao = document.getElementById('btn-rail');
  const rail = document.getElementById('rail');

  function definir(aberto) {
    rail.dataset.aberto = String(aberto);
    botao.setAttribute('aria-expanded', String(aberto));
  }

  botao.addEventListener('click', () => {
    definir(rail.dataset.aberto !== 'true');
  });

  rail.addEventListener('click', (evento) => {
    if (evento.target.closest('.rail__item')) {
      definir(false);
    }
  });

  document.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape' && rail.dataset.aberto === 'true') {
      definir(false);
      botao.focus();
    }
  });

  definir(false);
}

async function iniciar() {
  ligarIcones();
  ligarGaveta();
  ligarAbas();
  ligarPreferencias();
  ligarAcoesDeApp();
  ligarAcoesDeParam();
  ligarAcoesDeSync();
  ligarAcoesDeTipos();
  ligarAcoesDeSessao(carregarDados);

  ASSINATURAS.forEach(([desenhar, chaves]) => subscrever(desenhar, chaves));

  let inicial;
  try {
    inicial = await bootstrap();
  } catch (erro) {
    document.getElementById('erro-fatal').hidden = false;
    document.getElementById('erro-fatal').textContent = erro.message;
    return;
  }

  aplicarTema(inicial.prefs.theme);
  await carregarIdioma(inicial.language);
  traduzirDocumento();
  preencherSeletores(inicial.language, inicial.prefs.theme);
  // Depois do idioma: os rótulos da trilha (recolher, redimensionar) são
  // traduzidos na montagem, não por `data-i18n`.
  ligarRail();

  const temSessao = await tentarSessaoExistente();
  if (temSessao) {
    await carregarDados();
  } else {
    // Sem sessão a única tela útil é a de configuração — abrir noutra
    // seria mostrar tabela vazia e deixar o usuário procurando o motivo.
    trocarAba('sessao');
  }

  desenharTudo();

  if (new URLSearchParams(window.location.search).get('dev') === '1') {
    const { rodarChecagens } = await import('./devcheck.js');
    await rodarChecagens();
  }
}

window.addEventListener('unhandledrejection', (evento) => {
  toast(String(evento.reason && evento.reason.message), 'error');
});

iniciar().catch((erro) => {
  const alvo = document.getElementById('erro-fatal');
  alvo.hidden = false;
  alvo.textContent = erro.message;
});
