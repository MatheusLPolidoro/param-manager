/*
 * Paginação da lista que já está em memória.
 *
 * **Não reduz payload nem tempo de carga**: `list_apps` e `list_params`
 * trazem tudo, e nenhuma rota do servidor tem `skip`/`limit`. O que isto
 * resolve é navegação — uma lista com cem itens é ilegível mesmo
 * carregando rápido. Decisão registrada: paginação de servidor ficou de
 * fora por ser mudança de contrato entre dois artefatos liberados à
 * parte.
 *
 * Serve as quatro listas do app — aplicações, parâmetros, usuários e os
 * itens de lista/dicionário — porque todas sofrem do mesmo jeito: um
 * `users` com trinta linhas empurra os botões do formulário para fora
 * da tela.
 */

import { t } from './i18n.js';
import { icone } from './icons.js';

export const TAMANHO_PAGINA = 12;

/** Opções de "linhas por página". Mantidas curtas: é decisão de relance. */
export const TAMANHOS = [5, 10, 25, 50];

/** Tamanho a partir do qual um editor composto passa a paginar. */
export const LIMITE_COMPOSTO = 5;

/**
 * Recorta a lista, corrigindo página fora de faixa.
 *
 * Excluir o último item de uma página deixa `atual` além do fim, e sem a
 * correção a tela fica vazia sem explicação.
 */
export function paginar(itens, atual = 0, tamanho = TAMANHO_PAGINA) {
  const total = Math.max(1, Math.ceil(itens.length / tamanho));
  const pagina = Math.min(Math.max(0, atual), total - 1);
  const inicio = pagina * tamanho;
  return {
    itens: itens.slice(inicio, inicio + tamanho),
    pagina,
    total,
    quantidade: itens.length,
    primeiro: inicio + 1,
    ultimo: Math.min(inicio + tamanho, itens.length),
  };
}

/**
 * Janela de números de página em volta da atual.
 *
 * Listar todas as páginas quebra o layout a partir de algumas dezenas;
 * a janela mantém largura previsível e o primeiro/último sempre
 * alcançáveis pelas setas.
 */
function janela(atual, total, maximo = 7) {
  let inicio = Math.max(0, atual - Math.floor(maximo / 2));
  const fim = Math.min(total, inicio + maximo);
  inicio = Math.max(0, fim - maximo);
  return Array.from({ length: fim - inicio }, (_, i) => inicio + i);
}

function botaoSeta(nome, rotulo, desabilitado, aoClicar) {
  const botao = document.createElement('button');
  botao.type = 'button';
  botao.className = 'btn btn--ghost btn--icone';
  botao.append(icone(nome));
  botao.setAttribute('aria-label', rotulo);
  botao.title = rotulo;
  botao.disabled = desabilitado;
  botao.addEventListener('click', aoClicar);
  return botao;
}

/**
 * Controle de página, ou `null` quando há uma só e nada a escolher.
 *
 * `aoTrocarTamanho` é opcional: onde ele não faz sentido (um editor
 * dentro de um formulário), o seletor de linhas some.
 */
export function controlePaginacao(
  pagina,
  aoTrocar,
  chaveRotulo,
  { tamanho, aoTrocarTamanho } = {}
) {
  if (pagina.total <= 1 && !aoTrocarTamanho) {
    return null;
  }

  const barra = document.createElement('nav');
  barra.className = 'paginacao';
  barra.setAttribute('aria-label', t(chaveRotulo));

  const posicao = document.createElement('span');
  posicao.className = 'paginacao__posicao';
  posicao.textContent = t('paginacao.posicao', {
    primeiro: pagina.primeiro,
    ultimo: pagina.ultimo,
    total: pagina.quantidade,
  });
  // O contador muda sem que o foco saia do botão; sem isto, quem usa
  // leitor de tela clica em "próxima" e não recebe retorno nenhum.
  posicao.setAttribute('aria-live', 'polite');
  barra.append(posicao);

  if (pagina.total > 1) {
    const paginas = document.createElement('div');
    paginas.className = 'paginacao__paginas';

    paginas.append(
      botaoSeta('anterior', t('paginacao.anterior'), pagina.pagina === 0, () =>
        aoTrocar(pagina.pagina - 1)
      )
    );

    janela(pagina.pagina, pagina.total).forEach((indice) => {
      const botao = document.createElement('button');
      botao.type = 'button';
      const atual = indice === pagina.pagina;
      botao.className = `paginacao__numero${atual ? ' paginacao__numero--atual' : ''}`;
      botao.textContent = String(indice + 1);
      botao.setAttribute('aria-label', t('paginacao.ir', { n: indice + 1 }));
      if (atual) {
        botao.setAttribute('aria-current', 'page');
      }
      botao.addEventListener('click', () => aoTrocar(indice));
      paginas.append(botao);
    });

    paginas.append(
      botaoSeta(
        'proximo',
        t('paginacao.proxima'),
        pagina.pagina >= pagina.total - 1,
        () => aoTrocar(pagina.pagina + 1)
      )
    );
    barra.append(paginas);
  }

  if (aoTrocarTamanho) {
    const grupo = document.createElement('label');
    grupo.className = 'paginacao__tamanho';
    grupo.append(document.createTextNode(t('paginacao.porPagina')));

    const seletor = document.createElement('select');
    seletor.className = 'select select--compacto';
    TAMANHOS.forEach((opcaoTamanho) => {
      const opcao = document.createElement('option');
      opcao.value = String(opcaoTamanho);
      opcao.textContent = String(opcaoTamanho);
      opcao.selected = opcaoTamanho === tamanho;
      seletor.append(opcao);
    });
    seletor.addEventListener('change', () =>
      aoTrocarTamanho(Number(seletor.value))
    );

    grupo.append(seletor);
    barra.append(grupo);
  }

  return barra;
}
