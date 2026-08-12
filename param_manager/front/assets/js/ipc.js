/*
 * Ponte com o Python. O único módulo que conhece `pyInvoke`.
 *
 * Do lado de lá nada levanta: os handlers devolvem sempre
 * `{ok: bool, ...}`. Aqui esse contrato vira exceção de JavaScript, para
 * a UI escrever `try/catch` em vez de conferir `ok` em cada chamada e
 * esquecer numa delas.
 */

export class IpcError extends Error {
  constructor(message, errorType) {
    super(message);
    this.name = 'IpcError';
    this.errorType = errorType || 'IpcError';
  }
}

function pyInvoke() {
  return window.__TAURI__ && window.__TAURI__.pytauri
    ? window.__TAURI__.pytauri.pyInvoke
    : null;
}

/**
 * Chama um comando e devolve a resposta já validada.
 *
 * @param {string} command Nome do handler, idêntico ao do Python.
 * @param {object} body Corpo do comando.
 * @returns {Promise<object>} A resposta, garantidamente com `ok: true`.
 */
export async function call(command, body = {}) {
  const invoke = pyInvoke();
  if (!invoke) {
    throw new IpcError(
      'A ponte com o Python não está disponível nesta janela.',
      'BridgeUnavailable'
    );
  }

  let resposta;
  try {
    resposta = await invoke(command, body);
  } catch (erro) {
    // Falha da própria ponte (comando inexistente, corpo não
    // serializável). Não é o `ok: false` do handler.
    throw new IpcError(String(erro && erro.message ? erro.message : erro),
      'BridgeError');
  }

  if (!resposta || resposta.ok !== true) {
    const mensagem = (resposta && resposta.error) || 'Falha desconhecida.';
    throw new IpcError(mensagem, resposta && resposta.error_type);
  }
  return resposta;
}
