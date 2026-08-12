/*
 * Trilha de aplicações: recolher e redimensionar.
 *
 * A largura vive em `--rail`, na raiz, e não numa regra do `.rail`: é o
 * grid do `.app-body` que usa o token para dimensionar a coluna. Mexer
 * na largura do elemento sem mexer na coluna deixaria a trilha e o
 * conteúdo desalinhados.
 *
 * O estado é preferência do front, não do domínio — mora no
 * `front-prefs.json` junto com tema e idioma.
 */

import { t } from './i18n.js';
import { icone } from './icons.js';
import { anunciar } from './a11y.js';
import { salvarPrefs, state } from './store.js';

export const LARGURA_MINIMA = 180;
export const LARGURA_MAXIMA = 420;
const LARGURA_PADRAO = 240;

function limitar(valor) {
  return Math.min(LARGURA_MAXIMA, Math.max(LARGURA_MINIMA, valor));
}

function aplicarLargura(px) {
  document.documentElement.style.setProperty('--rail', `${limitar(px)}px`);
}

function aplicarRecolhida(recolhida) {
  document.getElementById('app-body').dataset.rail = recolhida
    ? 'recolhida'
    : 'aberta';
  const botao = document.getElementById('btn-recolher-rail');
  botao.setAttribute('aria-expanded', String(!recolhida));
  botao.replaceChildren(icone(recolhida ? 'proximo' : 'anterior'));
  const rotulo = t(recolhida ? 'apps.mostrarLista' : 'apps.recolherLista');
  botao.setAttribute('aria-label', rotulo);
  botao.title = rotulo;
}

/**
 * Liga o botão de recolher e a alça de redimensionar.
 *
 * O arrasto usa *pointer capture*: sem ele, mover o ponteiro rápido o
 * suficiente para sair da alça larga de 6px encerra o arrasto no meio.
 */
export function ligarRail() {
  const prefs = state.prefs || {};
  aplicarLargura(prefs.sidebar_width || LARGURA_PADRAO);
  aplicarRecolhida(Boolean(prefs.rail_collapsed));

  document
    .getElementById('btn-recolher-rail')
    .addEventListener('click', async () => {
      const recolhida =
        document.getElementById('app-body').dataset.rail !== 'recolhida';
      aplicarRecolhida(recolhida);
      await salvarPrefs({ rail_collapsed: recolhida });
      anunciar(t(recolhida ? 'apps.recolhida' : 'apps.expandida'));
    });

  const alca = document.getElementById('alca-rail');
  let arrastando = false;

  alca.addEventListener('pointerdown', (evento) => {
    // Só o botão principal arrasta; o secundário abre menu de contexto.
    if (evento.button !== 0) {
      return;
    }
    arrastando = true;
    alca.setPointerCapture(evento.pointerId);
    document.body.classList.add('redimensionando');
    evento.preventDefault();
  });

  alca.addEventListener('pointermove', (evento) => {
    if (arrastando) {
      aplicarLargura(evento.clientX);
    }
  });

  async function encerrar(evento) {
    if (!arrastando) {
      return;
    }
    arrastando = false;
    if (alca.hasPointerCapture(evento.pointerId)) {
      alca.releasePointerCapture(evento.pointerId);
    }
    document.body.classList.remove('redimensionando');
    const atual = Number.parseInt(
      getComputedStyle(document.documentElement).getPropertyValue('--rail'),
      10
    );
    await salvarPrefs({ sidebar_width: atual });
  }

  alca.addEventListener('pointerup', encerrar);
  alca.addEventListener('pointercancel', encerrar);

  // Teclado: a alça é `separator` e responde a setas, porque arrastar não
  // é alcançável sem ponteiro.
  alca.addEventListener('keydown', async (evento) => {
    const passo = evento.shiftKey ? 40 : 10;
    let atual = Number.parseInt(
      getComputedStyle(document.documentElement).getPropertyValue('--rail'),
      10
    );
    if (evento.key === 'ArrowLeft') {
      atual -= passo;
    } else if (evento.key === 'ArrowRight') {
      atual += passo;
    } else if (evento.key === 'Home') {
      atual = LARGURA_PADRAO;
    } else {
      return;
    }
    evento.preventDefault();
    aplicarLargura(atual);
    alca.setAttribute('aria-valuenow', String(limitar(atual)));
    await salvarPrefs({ sidebar_width: limitar(atual) });
  });
}
