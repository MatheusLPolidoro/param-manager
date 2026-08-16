/*
 * Catálogo de tipos: o que o servidor publica, e o que a lib usa offline.
 *
 * A tela existe porque a validação do cliente é conselho, não veto: saber
 * qual `max_length` padrão está em vigor explica por que uma string de 40
 * caracteres foi recusada lá e passou aqui.
 */

import { t } from '../i18n.js';
import { toast } from '../a11y.js';
import { atualizarCatalogo, state } from '../store.js';

export function desenharTipos() {
  const area = document.getElementById('tipos-conteudo');
  area.replaceChildren();

  const catalogo = state.catalogo;
  if (!catalogo) {
    const vazio = document.createElement('p');
    vazio.className = 'muted';
    vazio.textContent = t('tipos.vazio');
    area.append(vazio);
    return;
  }

  const sensiveis = new Set(catalogo.sensitive || []);

  const tabela = document.createElement('table');
  tabela.className = 'table';
  const cabecalho = document.createElement('thead');
  const linhaCabecalho = document.createElement('tr');
  [t('tipos.coluna.tipo'), t('tipos.coluna.sensivel')].forEach((texto) => {
    const celula = document.createElement('th');
    celula.scope = 'col';
    celula.textContent = texto;
    linhaCabecalho.append(celula);
  });
  cabecalho.append(linhaCabecalho);

  const corpo = document.createElement('tbody');
  (catalogo.types || []).forEach((tipo) => {
    const linha = document.createElement('tr');
    const nome = document.createElement('td');
    nome.className = 'mono';
    nome.textContent = tipo;

    const sensivel = document.createElement('td');
    const chip = document.createElement('span');
    const ehSensivel = sensiveis.has(tipo);
    chip.className = `chip chip--${ehSensivel ? 'blocked' : 'neutral'}`;
    chip.textContent = ehSensivel ? t('tipos.sensivel') : t('tipos.comum');
    chip.title = ehSensivel ? t('tipos.sensivel.explicacao') : '';
    sensivel.append(chip);

    linha.append(nome, sensivel);
    corpo.append(linha);
  });

  tabela.append(cabecalho, corpo);
  const embrulho = document.createElement('div');
  embrulho.className = 'table-wrap';
  embrulho.append(tabela);
  area.append(embrulho);

  const defaults = catalogo.defaults || {};
  const lista = document.createElement('dl');
  lista.className = 'stack stack--tight';
  Object.entries(defaults).forEach(([chave, valor]) => {
    const termo = document.createElement('dt');
    termo.className = 'eyebrow';
    termo.textContent = chave;
    const definicao = document.createElement('dd');
    definicao.className = 'mono definicao';
    definicao.textContent = String(valor);
    lista.append(termo, definicao);
  });

  const cartao = document.createElement('div');
  cartao.className = 'card';
  const titulo = document.createElement('h2');
  titulo.textContent = t('tipos.defaults');
  const explicacao = document.createElement('p');
  explicacao.className = 'muted';
  explicacao.textContent = t('tipos.defaults.explicacao');
  cartao.append(titulo, explicacao, lista);
  area.append(cartao);
}

export function ligarAcoesDeTipos() {
  document
    .getElementById('btn-atualizar-catalogo')
    .addEventListener('click', async () => {
      try {
        await atualizarCatalogo();
        desenharTipos();
        toast(t('tipos.atualizado'), 'ok');
      } catch (erro) {
        toast(erro.message, 'error');
      }
    });
}
