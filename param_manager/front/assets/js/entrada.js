/*
 * Regras de entrada compartilhadas entre os formulários.
 */

/**
 * Normaliza um identificador: espaço vira `-`.
 *
 * Nome de app e chave de parâmetro viram segmento de URL do lado do
 * servidor (`/parameters/apps/{app}/params/{param}`). Espaço ali obriga
 * quem consome a lembrar de codificar, e o erro só aparece na leitura —
 * longe de quem digitou.
 *
 * Substitui em vez de recusar: quem digitou "meu app" quis dizer
 * "meu-app", e devolver um erro para o usuário apagar e redigitar é
 * atrito sem propósito. Hífens repetidos colapsam, porque teclar espaço
 * duas vezes é comum e `meu--app` não é o que ninguém quis.
 */
export function normalizarChave(texto) {
  return texto.replace(/\s+/g, '-').replace(/-{2,}/g, '-');
}

/**
 * Liga a normalização a um campo, preservando a posição do cursor.
 *
 * Reescrever `value` num `input` joga o cursor para o fim. Sem
 * restaurá-lo, digitar um espaço no meio de um nome já escrito atira o
 * cursor para o fim e o resto do que a pessoa digita sai fora de ordem.
 */
export function ligarNormalizacaoDeChave(campo) {
  campo.addEventListener('input', () => {
    const original = campo.value;
    const normalizado = normalizarChave(original);
    if (original === normalizado) {
      return;
    }
    const posicao = campo.selectionStart;
    // O texto até o cursor encolhe quando espaços repetidos colapsam;
    // medir o prefixo normalizado dá a posição equivalente.
    const prefixo = normalizarChave(original.slice(0, posicao)).length;
    campo.value = normalizado;
    campo.setSelectionRange(prefixo, prefixo);
  });
}
