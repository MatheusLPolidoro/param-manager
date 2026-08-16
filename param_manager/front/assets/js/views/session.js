/*
 * Tela de sessão: configurar a instância, e ver o que está valendo.
 *
 * Duas coisas que a UI não pode deixar ambíguas, porque a lib é
 * intencionalmente rígida nelas:
 *
 * 1. **Trocar de modo exige instância nova.** `__init__` faz early-return
 *    quando a instância já existe, e essa guarda existe para impedir
 *    reconfiguração de sessão viva. O formulário diz isso, e sugere um
 *    nome novo em vez de fingir que reconfigurou.
 * 2. **Um processo segura uma chave de custódia só.** Ela vem de variável
 *    de ambiente global, sem contexto de instância — então duas sessões
 *    com apps de chaves diferentes não funcionam, e o aviso está aqui em
 *    vez de virar "não decifra" mais tarde.
 */

import { t } from '../i18n.js';
import { anunciar, toast } from '../a11y.js';
import { configurar, state } from '../store.js';

/**
 * Mostra ou esconde os campos que só o modo remoto usa.
 *
 * Esconder, e não desabilitar: campo desabilitado ainda ocupa espaço e
 * ainda sugere que existe algo a preencher ali. Em modo local não há
 * rede nenhuma — URL, usuário e senha não têm significado.
 */
export function ajustarCamposDoModo() {
  const local = document.getElementById('sessao-modo').value === 'local';
  document
    .querySelectorAll('[data-somente-remoto]')
    .forEach((elemento) => {
      elemento.hidden = local;
    });
  document.getElementById('sessao-dica-local').hidden = !local;
}

export function desenharSessao() {
  const instancia = document.getElementById('sessao-instancia');
  const modo = document.getElementById('sessao-modo');
  const url = document.getElementById('sessao-url');

  if (state.pronto && document.activeElement !== instancia) {
    instancia.value = state.instancia;
    if (state.modo) {
      modo.value = state.modo;
    }
  }
  if (!state.pronto && !instancia.value) {
    instancia.value = (state.prefs && state.prefs.last_instance) || 'default';
  }

  const situacao = document.getElementById('sessao-situacao');
  situacao.replaceChildren();

  const bloco = document.createElement('div');
  if (state.pronto) {
    bloco.className = 'alert alert--info';
    bloco.textContent = t('sessao.ativa', {
      instancia: state.instancia,
      modo: t(`modo.${state.modo}`),
      sidecar: state.temStoreLocal ? t('sessao.comSidecar') : t('sessao.semSidecar'),
    });
  } else {
    bloco.className = 'alert alert--warn';
    bloco.setAttribute('role', 'status');
    bloco.textContent = state.erroSessao
      ? t('sessao.inativaComErro', { erro: state.erroSessao })
      : t('sessao.inativa');
  }
  situacao.append(bloco);

  url.placeholder = t('sessao.url.placeholder');
  ajustarCamposDoModo();
}

export function ligarAcoesDeSessao(aoConfigurar) {
  const formulario = document.getElementById('form-sessao');

  document
    .getElementById('sessao-modo')
    .addEventListener('change', ajustarCamposDoModo);

  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const config = {
      instance_name: document.getElementById('sessao-instancia').value.trim(),
      mode: document.getElementById('sessao-modo').value,
    };
    const url = document.getElementById('sessao-url').value.trim();
    const usuario = document.getElementById('sessao-usuario').value.trim();
    const senha = document.getElementById('sessao-senha').value;

    if (url) {
      config.api_url = url;
    }
    if (usuario) {
      config.username = usuario;
    }
    if (senha) {
      config.password = senha;
    }

    if (!config.instance_name) {
      toast(t('sessao.erro.instanciaVazia'), 'error');
      return;
    }

    // Modo remoto sem URL constrói uma sessão que se diz ativa e falha em
    // toda leitura com `Invalid URL '/parameters/apps/'` — erro do
    // `requests` sobre uma URL vazia, que não diz a ninguém o que fazer.
    // A lib aceita construir assim de propósito (é o caminho de quem
    // configura por env); quem tem um formulário na mão não tem motivo
    // para deixar passar.
    if (config.mode === 'remote' && !url) {
      toast(t('sessao.erro.urlObrigatoria'), 'error');
      document.getElementById('sessao-url').focus();
      return;
    }

    try {
      const resposta = await configurar(config);
      // Senha não fica na tela depois de usada.
      document.getElementById('sessao-senha').value = '';

      // `configure` numa instância que já existe é NO-OP e devolve
      // `ok: true` com o modo antigo — `__init__` faz early-return quando
      // `_initialized` está setado, e essa guarda é deliberada na lib.
      // Cantar vitória aqui foi o defeito que fez alguém escolher `local`,
      // ver "Sessão configurada" e não encontrar arquivo local nenhum.
      if (resposta.mode !== config.mode) {
        desenharSessao();
        avisarModoNaoAplicado(config, resposta.mode);
        return;
      }

      desenharSessao();
      toast(t('sessao.configurada', { instancia: config.instance_name }), 'ok');
      if (aoConfigurar) {
        await aoConfigurar();
      }
    } catch (erro) {
      toast(erro.message, 'error');
    }
  });
}

/**
 * Explica o no-op e oferece a saída: uma instância nova.
 *
 * Só avisar deixaria o usuário no mesmo beco, tendo que adivinhar que a
 * solução é trocar o nome. O botão preenche o campo com um sufixo do
 * modo pedido e devolve o foco ao formulário.
 */
function avisarModoNaoAplicado(config, modoReal) {
  const area = document.getElementById('sessao-situacao');
  area.replaceChildren();

  const bloco = document.createElement('div');
  bloco.className = 'alert alert--warn';
  bloco.setAttribute('role', 'alert');

  const texto = document.createElement('p');
  texto.className = 'alert__text';
  texto.textContent = t('sessao.modoNaoAplicado', {
    instancia: config.instance_name,
    atual: t(`modo.${modoReal}`),
    pedido: t(`modo.${config.mode}`),
  });
  bloco.append(texto);

  const sugestao = `${config.instance_name}-${config.mode}`;
  const botao = document.createElement('button');
  botao.type = 'button';
  botao.className = 'btn btn--primary';
  botao.textContent = t('sessao.usarNomeNovo', { nome: sugestao });
  botao.addEventListener('click', () => {
    const campo = document.getElementById('sessao-instancia');
    campo.value = sugestao;
    campo.focus();
  });
  bloco.append(botao);

  area.append(bloco);
  anunciar(texto.textContent, true);
}
