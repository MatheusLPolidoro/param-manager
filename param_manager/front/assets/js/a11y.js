/*
 * Acessibilidade: as peças que a UI reusa em toda tela.
 *
 * Não é uma camada de enfeite — é onde moram foco preso, anúncio para
 * leitor de tela e navegação por setas na tabela. Deixar isso para cada
 * view significa que metade delas esquece.
 */

import { t } from './i18n.js';
import { icone } from './icons.js';

/** Anuncia num `aria-live`, para quem não vê o toast aparecer. */
export function anunciar(mensagem, assertivo = false) {
  const alvo = document.getElementById(
    assertivo ? 'live-assertivo' : 'live-educado'
  );
  if (!alvo) {
    return;
  }
  // Limpar antes força o leitor a reanunciar mensagens repetidas.
  alvo.textContent = '';
  window.setTimeout(() => {
    alvo.textContent = mensagem;
  }, 50);
}

/** Toast visual. Erro também vai para o `aria-live` assertivo. */
export function toast(mensagem, tipo = 'ok') {
  const area = document.getElementById('toasts');
  if (!area) {
    return;
  }
  const elemento = document.createElement('div');
  elemento.className = `toast toast--${tipo}`;
  elemento.textContent = mensagem;
  area.append(elemento);
  anunciar(mensagem, tipo === 'error');
  window.setTimeout(() => elemento.remove(), 6000);
}

/**
 * Confirmação modal. Resolve `true` só no botão de confirmar.
 *
 * `<dialog showModal>` já prende o foco e trata `Esc`; o que falta e é
 * feito aqui é devolver o foco a quem abriu — sem isso o teclado volta
 * para o começo do documento depois de cada confirmação.
 */
export function confirmar({
  titulo,
  texto,
  confirmar: rotulo,
  perigoso,
  digitar,
}) {
  const dialogo = document.getElementById('dialogo-confirmacao');
  const gatilho = document.activeElement;
  dialogo.querySelector('[data-slot="titulo"]').textContent = titulo;
  dialogo.querySelector('[data-slot="texto"]').textContent = texto;

  const marca = dialogo.querySelector('[data-slot="icone"]');
  marca.replaceChildren();
  if (perigoso) {
    const svg = icone('alerta', 'icone icone--alerta');
    if (svg) {
      marca.append(svg);
    }
  }

  const botaoOk = dialogo.querySelector('[data-slot="ok"]');
  botaoOk.textContent = rotulo || t('acoes.confirmar');
  botaoOk.className = perigoso ? 'btn btn--danger' : 'btn btn--primary';

  // Confirmação por digitação: o botão só destrava quando o nome exato
  // é digitado. Existe porque um diálogo de sim/não é confirmado no
  // reflexo — e apagar um app leva os parâmetros dele junto, sem desfazer.
  const bloco = dialogo.querySelector('[data-slot="digitar"]');
  const entrada = dialogo.querySelector('[data-slot="digitado"]');
  const instrucao = dialogo.querySelector('[data-slot="instrucao"]');
  bloco.hidden = !digitar;
  entrada.value = '';

  function avaliar() {
    botaoOk.disabled = Boolean(digitar) && entrada.value.trim() !== digitar;
  }

  if (digitar) {
    instrucao.textContent = t('acoes.digiteParaConfirmar', { nome: digitar });
    entrada.setAttribute('aria-label', t('acoes.digiteParaConfirmar', {
      nome: digitar,
    }));
    entrada.addEventListener('input', avaliar);
  }
  avaliar();

  return new Promise((resolve) => {
    function fechar(valor) {
      dialogo.removeEventListener('close', aoFechar);
      botaoOk.removeEventListener('click', aoConfirmar);
      entrada.removeEventListener('input', avaliar);
      formulario.removeEventListener('submit', aoEnviar);
      dialogo.close();
      if (gatilho && gatilho.focus) {
        gatilho.focus();
      }
      resolve(valor);
    }
    function aoConfirmar() {
      if (!botaoOk.disabled) {
        fechar(true);
      }
    }
    function aoFechar() {
      fechar(false);
    }
    // Enter no campo confirma, se já estiver liberado — digitar o nome e
    // ter de mover a mão até o botão é atrito sem propósito.
    function aoEnviar(evento) {
      evento.preventDefault();
      aoConfirmar();
    }

    const formulario = bloco;
    formulario.addEventListener('submit', aoEnviar);
    botaoOk.addEventListener('click', aoConfirmar);
    dialogo.addEventListener('close', aoFechar);
    dialogo.showModal();
    // Com digitação, o foco vai para o campo: o botão nasce desabilitado
    // e focar nele deixaria o teclado num controle inerte.
    (digitar ? entrada : botaoOk).focus();
  });
}

/**
 * Navegação por setas numa grade de linhas.
 *
 * `role="grid"` promete ao leitor de tela que setas funcionam. Prometer e
 * não cumprir é pior que não prometer.
 */
export function ligarNavegacaoDeLinhas(tabela, aoSelecionar) {
  tabela.addEventListener('keydown', (evento) => {
    const linhas = Array.from(tabela.querySelectorAll('tbody tr'));
    if (!linhas.length) {
      return;
    }
    const atual = linhas.indexOf(document.activeElement.closest('tr'));
    let alvo = null;

    if (evento.key === 'ArrowDown') {
      alvo = linhas[Math.min(atual + 1, linhas.length - 1)];
    } else if (evento.key === 'ArrowUp') {
      alvo = linhas[Math.max(atual - 1, 0)];
    } else if (evento.key === 'Home') {
      alvo = linhas[0];
    } else if (evento.key === 'End') {
      alvo = linhas[linhas.length - 1];
    } else if (evento.key === 'Enter' || evento.key === ' ') {
      const linha = document.activeElement.closest('tr');
      if (linha && linha.dataset.nome) {
        evento.preventDefault();
        aoSelecionar(linha.dataset.nome);
      }
      return;
    }

    if (alvo) {
      evento.preventDefault();
      alvo.focus();
    }
  });
}

/** Aplica o tema escolhido; `system` tira o carimbo e devolve ao SO. */
export function aplicarTema(tema) {
  if (tema === 'light' || tema === 'dark') {
    document.documentElement.dataset.theme = tema;
  } else {
    delete document.documentElement.dataset.theme;
  }
}
