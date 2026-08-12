/*
 * Chip de estado — um lugar só, porque a tabela e o plano mostram o mesmo
 * vocabulário e discordar entre as duas telas seria confuso de um jeito
 * difícil de perceber.
 *
 * Os cinco estados vêm do `LocalStore`: draft, dirty, synced, conflict,
 * rejected. Modo remoto reporta tudo como `synced`.
 */

import { t } from './i18n.js';

const FAMILIA = {
  synced: 'synced',
  draft: 'pending',
  dirty: 'pending',
  conflict: 'blocked',
  rejected: 'blocked',
};

export function familiaDoEstado(estado) {
  return FAMILIA[estado] || 'neutral';
}

/** Devolve o elemento do chip, já traduzido e legível sem enxergar cor. */
export function chipDeEstado(estado) {
  const elemento = document.createElement('span');
  elemento.className = `chip chip--${familiaDoEstado(estado)}`;
  const rotulo = t(`estado.${estado}`);
  elemento.textContent = rotulo;
  // O texto já diz o estado; o title explica o que ele significa.
  elemento.title = t(`estado.${estado}.explicacao`);
  return elemento;
}
