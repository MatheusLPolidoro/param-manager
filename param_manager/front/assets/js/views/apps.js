/*
 * Rail de apps: lista, seleção e criação.
 */

import { t } from '../i18n.js';
import { confirmar, toast } from '../a11y.js';
import { prefixarIcone } from '../icons.js';
import { ligarNormalizacaoDeChave } from '../entrada.js';
import { paginar, controlePaginacao } from '../paginacao.js';
import { aplicarFiltro, barraDeFiltro } from '../filtros.js';
import {
  criarApp,
  excluirApp,
  filtroMudou,
  nomeDoApp,
  paginaDeApps,
  selecionarApp,
  state,
  tamanhoDeApps,
} from '../store.js';

export function desenharApps() {
  const lista = document.getElementById('lista-apps');
  const rodape = document.getElementById('rodape-apps');
  lista.replaceChildren();
  rodape.replaceChildren();

  // Sem app selecionado não há o que excluir. Deixar o botão vivo
  // convida ao clique que só produz erro.
  document.getElementById('btn-excluir-app').disabled =
    !state.appSelecionado;
  document.getElementById('btn-novo-app').disabled = !state.pronto;

  if (!state.apps.length) {
    const vazio = document.createElement('li');
    vazio.className = 'muted';
    vazio.textContent = t('apps.vazio');
    lista.append(vazio);
    return;
  }

  desenharFiltro();

  const visiveis = aplicarFiltro(state.apps, state.filtroApps, [
    (app) => nomeDoApp(app),
    (app) => (typeof app === 'object' && app ? app.description : ''),
  ]);

  if (!visiveis.length) {
    const vazio = document.createElement('li');
    vazio.className = 'muted';
    vazio.textContent = t('filtro.semResultado');
    lista.append(vazio);
    return;
  }

  const pagina = paginar(visiveis, state.paginaApps, state.tamanhoApps);

  pagina.itens.forEach((app) => {
    const nome = nomeDoApp(app);
    const item = document.createElement('li');
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.className = 'rail__item';
    botao.textContent = nome;
    botao.title = nome;
    prefixarIcone(botao, 'caixa');
    botao.setAttribute(
      'aria-current',
      nome === state.appSelecionado ? 'true' : 'false'
    );
    botao.addEventListener('click', () => {
      selecionarApp(nome).catch((erro) => toast(erro.message, 'error'));
    });
    item.append(botao);
    lista.append(item);
  });

  const controle = controlePaginacao(pagina, paginaDeApps, 'apps.paginacao', {
    tamanho: state.tamanhoApps,
    aoTrocarTamanho: tamanhoDeApps,
  });
  if (controle) {
    rodape.append(controle);
  }
}

/**
 * Barra de filtro da trilha.
 *
 * O foco é devolvido ao campo depois do redesenho porque a barra é
 * recriada a cada tecla — sem isso, digitar a segunda letra da busca já
 * teria perdido o cursor.
 */
function desenharFiltro() {
  const area = document.getElementById('filtro-apps');
  const tinhaFoco = document.activeElement === area.querySelector('input');
  const posicao = tinhaFoco ? area.querySelector('input').selectionStart : 0;

  const { elemento, entrada } = barraDeFiltro({
    filtro: state.filtroApps,
    aoMudar: () => filtroMudou('apps'),
    rotulo: t('filtro.apps'),
    total: state.apps.length,
    exibidos: aplicarFiltro(state.apps, state.filtroApps, [
      (app) => nomeDoApp(app),
      (app) => (typeof app === 'object' && app ? app.description : ''),
    ]).length,
  });

  area.replaceChildren(elemento);
  if (tinhaFoco) {
    entrada.focus();
    entrada.setSelectionRange(posicao, posicao);
  }
}

export function ligarAcoesDeApp() {
  const dialogo = document.getElementById('dialogo-novo-app');
  const formulario = document.getElementById('form-novo-app');

  ligarNormalizacaoDeChave(document.getElementById('novo-app-nome'));

  document.getElementById('btn-novo-app').addEventListener('click', () => {
    formulario.reset();
    dialogo.showModal();
    document.getElementById('novo-app-nome').focus();
  });

  document
    .getElementById('btn-cancelar-app')
    .addEventListener('click', () => dialogo.close());

  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const nome = document.getElementById('novo-app-nome').value.trim();
    const descricao = document.getElementById('novo-app-descricao').value.trim();
    if (!nome) {
      return;
    }
    try {
      await criarApp(nome, descricao);
      dialogo.close();
      toast(t('apps.criado', { nome }), 'ok');
    } catch (erro) {
      toast(erro.message, 'error');
    }
  });

  document
    .getElementById('btn-excluir-app')
    .addEventListener('click', async () => {
      const nome = state.appSelecionado;
      if (!nome) {
        return;
      }
      const total = state.params.length;
      const confirmado = await confirmar({
        titulo: t('apps.excluir.titulo'),
        texto: t('apps.excluir.texto', { nome, total }),
        confirmar: t('acoes.excluir'),
        perigoso: true,
        // Exclusão de app leva os parâmetros junto e não tem desfazer.
        // Digitar o nome tira a ação do reflexo.
        digitar: nome,
      });
      if (!confirmado) {
        return;
      }
      try {
        await excluirApp(nome);
        toast(t('apps.excluido', { nome }), 'ok');
      } catch (erro) {
        toast(erro.message, 'error');
      }
    });
}
