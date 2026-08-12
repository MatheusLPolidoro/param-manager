/*
 * O estado do front, num lugar só.
 *
 * As views leem daqui e se redesenham quando algo muda; nenhuma view
 * chama `ipc.call` direto. A separação existe porque estado espalhado por
 * view é como duas telas passam a discordar sobre qual app está
 * selecionado.
 */

import { call } from './ipc.js';

/*
 * Assinaturas com escopo.
 *
 * Antes havia uma só, `desenharTudo`, disparada por qualquer mudança —
 * então trocar de página ou de tema reconstruía o formulário de detalhe
 * junto, **perdendo o que estivesse digitado** e piscando a tela inteira.
 *
 * Agora cada ouvinte declara as chaves de estado que lhe interessam e só
 * acorda quando uma delas muda. Ouvinte sem chaves continua acordando
 * sempre, para os casos em que isso é mesmo o certo.
 */
const ouvintes = new Set();

export const state = {
  pronto: false,
  instancia: 'default',
  modo: null,
  temStoreLocal: false,
  versaoLib: '',
  versaoFront: '',
  idiomas: ['pt-BR'],
  prefs: {},

  apps: [],
  appSelecionado: null,
  paginaApps: 0,
  tamanhoApps: 10,
  filtroApps: { termos: [], tipos: [], texto: '' },
  params: [],
  paramSelecionado: null,
  paginaParams: 0,
  tamanhoParams: 10,
  filtroParams: { termos: [], tipos: [], texto: '' },
  detalhe: null,

  catalogo: null,
  sync: { pending: 0, rejected: 0, conflict: 0, total: 0 },
  plano: null,

  aba: 'params',
  carregando: false,
  erroSessao: null,
};

/**
 * Registra um ouvinte. `chaves` limita quando ele acorda.
 *
 * @param {Function} ouvinte
 * @param {string[]|null} chaves Estado que o interessa; `null` = tudo.
 */
export function subscrever(ouvinte, chaves = null) {
  const registro = { ouvinte, chaves: chaves && new Set(chaves) };
  ouvintes.add(registro);
  return () => ouvintes.delete(registro);
}

export function notificar(chaves = null) {
  const mudou = chaves && new Set(chaves);
  ouvintes.forEach(({ ouvinte, chaves: interesse }) => {
    if (!mudou || !interesse) {
      ouvinte(state);
      return;
    }
    for (const chave of mudou) {
      if (interesse.has(chave)) {
        ouvinte(state);
        return;
      }
    }
  });
}

function atribuir(mudancas) {
  Object.assign(state, mudancas);
  notificar(Object.keys(mudancas));
}

/* ------------------------------------------------------------ sessão --- */

export async function bootstrap() {
  const resposta = await call('ui_bootstrap');
  atribuir({
    prefs: resposta.prefs,
    idiomas: resposta.languages,
    versaoLib: resposta.lib_version,
    versaoFront: resposta.front_version,
    instancia: resposta.prefs.last_instance || 'default',
  });
  return resposta;
}

export async function salvarPrefs(mudancas) {
  const resposta = await call('ui_prefs_set', mudancas);
  atribuir({ prefs: resposta.prefs });
  return resposta.prefs;
}

export async function configurar(config) {
  const resposta = await call('configure', config);
  atribuir({
    instancia: resposta.instance_name,
    modo: resposta.mode,
    erroSessao: null,
    pronto: true,
  });
  await salvarPrefs({ last_instance: resposta.instance_name });
  await descreverSessao();
  return resposta;
}

export async function descreverSessao() {
  const resposta = await call('describe_session', {
    instance_name: state.instancia,
  });
  atribuir({
    modo: resposta.mode,
    temStoreLocal: resposta.has_local_store,
    pronto: true,
  });
  return resposta;
}

/**
 * Tenta assumir uma sessão já configurada por env, sem construir nada.
 *
 * `describe_session` falha quando ninguém chamou `configure` — e falhar
 * aqui é o comportamento certo: a lib não deve inventar uma instância com
 * defaults, e a tela de sessão é quem resolve.
 */
export async function tentarSessaoExistente() {
  try {
    await descreverSessao();
    return true;
  } catch (erro) {
    atribuir({ pronto: false, erroSessao: erro.message });
    return false;
  }
}

/* -------------------------------------------------------------- apps --- */

export async function carregarApps() {
  const resposta = await call('list_apps', { instance_name: state.instancia });
  const apps = resposta.apps || [];
  atribuir({ apps });
  if (apps.length && !apps.some((a) => nomeDoApp(a) === state.appSelecionado)) {
    await selecionarApp(nomeDoApp(apps[0]));
  }
  return apps;
}

/** Os dois modos descrevem app de formas diferentes; a UI vê só o nome. */
export function nomeDoApp(app) {
  if (typeof app === 'string') {
    return app;
  }
  return (app && (app.name || app.app)) || '';
}

export function paginaDeApps(pagina) {
  atribuir({ paginaApps: pagina });
}

export function paginaDeParams(pagina) {
  atribuir({ paginaParams: pagina });
}

export function tamanhoDeApps(tamanho) {
  atribuir({ tamanhoApps: tamanho, paginaApps: 0 });
}

export function tamanhoDeParams(tamanho) {
  atribuir({ tamanhoParams: tamanho, paginaParams: 0 });
}

/**
 * Redesenha após mudar um filtro, voltando para a primeira página.
 *
 * O filtro é mutado no lugar por quem o edita — `notificar` é o que faz
 * a tela acompanhar. Voltar à página 1 é obrigatório: filtrar de 40 para
 * 3 itens com a lista na página 3 mostraria vazio.
 */
export function filtroMudou(qual) {
  if (qual === 'apps') {
    state.paginaApps = 0;
    notificar(['filtroApps', 'paginaApps']);
  } else {
    state.paginaParams = 0;
    notificar(['filtroParams', 'paginaParams']);
  }
}

export async function selecionarApp(nome) {
  atribuir({
    appSelecionado: nome,
    paramSelecionado: null,
    detalhe: null,
    // Trocar de app com a tabela na página 3 mostraria vazio.
    paginaParams: 0,
  });
  await carregarParams();
  await carregarSyncStatus();
}

export async function criarApp(nome, descricao) {
  await call('create_app', {
    instance_name: state.instancia,
    name: nome,
    description: descricao || null,
  });
  await carregarApps();
  await selecionarApp(nome);
  // App recém-criado está vazio, e a única coisa a fazer nele é criar
  // parâmetro. Deixar o operador na aba em que estava obrigaria um
  // clique que a intenção já tornou óbvio.
  trocarAba('params');
}

/** Registro do app selecionado, com descrição e o que mais vier. */
export function appAtual() {
  return (
    state.apps.find((app) => nomeDoApp(app) === state.appSelecionado) || null
  );
}

export async function excluirApp(nome) {
  await call('delete_app', { instance_name: state.instancia, app: nome });
  // `detalhe` também, e não só a seleção: sem ele o painel da direita
  // continuava aberto exibindo um parâmetro do app recém-excluído, que
  // já não existe em lugar nenhum.
  atribuir({
    appSelecionado: null,
    params: [],
    paramSelecionado: null,
    detalhe: null,
    paginaParams: 0,
    paginaApps: 0,
  });
  await carregarApps();
  await carregarSyncStatus();
}

/* ------------------------------------------------------- parâmetros --- */

export async function carregarParams() {
  if (!state.appSelecionado) {
    atribuir({ params: [] });
    return [];
  }
  const resposta = await call('list_params', {
    instance_name: state.instancia,
    app: state.appSelecionado,
  });
  atribuir({ params: resposta.params || [] });
  return resposta.params;
}

/**
 * Carrega o valor de um parâmetro — e só aqui o valor trafega.
 *
 * A tabela vive de metadado justamente para que envelope de `secret` não
 * atravesse o IPC a cada redesenho de linha.
 */
export async function selecionarParam(nome) {
  atribuir({ paramSelecionado: nome, detalhe: null });
  if (!nome) {
    return null;
  }
  const resumo = state.params.find((p) => p.name === nome) || { name: nome };
  try {
    const resposta = await call('get_param', {
      instance_name: state.instancia,
      app: state.appSelecionado,
      name: nome,
    });
    atribuir({ detalhe: { ...resumo, value: resposta.value, erro: null } });
  } catch (erro) {
    // Parâmetro sem valor legível (sem chave de custódia, por exemplo)
    // ainda precisa abrir o painel: o metadado é editável.
    atribuir({ detalhe: { ...resumo, value: null, erro: erro.message } });
  }
  return state.detalhe;
}

/**
 * Avisos do catálogo. Conselho, não veto — não impede a gravação.
 *
 * Falhar aqui não pode impedir salvar: a validação é do cliente e o juiz
 * é o servidor. Sem catálogo, devolve lista vazia e segue.
 */
export async function validarParam(corpo) {
  try {
    const resposta = await call('validate_param', {
      instance_name: state.instancia,
      ...corpo,
    });
    return resposta.warnings || [];
  } catch {
    return [];
  }
}

export async function gravarParam(corpo) {
  await call('upsert_param', { instance_name: state.instancia, ...corpo });
  await carregarParams();
  await carregarSyncStatus();
  await selecionarParam(corpo.name);
}

export async function excluirParam(nome) {
  await call('delete_param', {
    instance_name: state.instancia,
    app: state.appSelecionado,
    name: nome,
  });
  atribuir({ paramSelecionado: null, detalhe: null });
  await carregarParams();
  await carregarSyncStatus();
}

/* ---------------------------------------------------- sincronização --- */

export async function carregarSyncStatus() {
  try {
    const resposta = await call('sync_status', {
      instance_name: state.instancia,
    });
    atribuir({
      sync: {
        pending: resposta.pending || 0,
        rejected: resposta.rejected || 0,
        conflict: resposta.conflict || 0,
        total: resposta.total || 0,
      },
    });
  } catch {
    // O rodapé é informativo: falhar nele não pode derrubar a tela.
    atribuir({ sync: { pending: 0, rejected: 0, conflict: 0, total: 0 } });
  }
  return state.sync;
}

export async function calcularPlano(app) {
  const corpo = { instance_name: state.instancia };
  if (app) {
    corpo.app = app;
  }
  const resposta = await call('sync_plan', corpo);
  atribuir({ plano: resposta.plan });
  return resposta.plan;
}

export async function aplicarPlano(plano) {
  const resposta = await call('sync_apply', {
    instance_name: state.instancia,
    plan: plano,
  });
  atribuir({ plano: null });
  await carregarParams();
  await carregarSyncStatus();
  return resposta.result;
}

/* --------------------------------------------------------- catálogo --- */

export async function carregarCatalogo() {
  const resposta = await call('type_catalog', {
    instance_name: state.instancia,
  });
  atribuir({ catalogo: resposta.catalog });
  return resposta.catalog;
}

export async function atualizarCatalogo() {
  await call('refresh_type_catalog', { instance_name: state.instancia });
  return carregarCatalogo();
}

/* ------------------------------------------------------------ abas ---- */

export function trocarAba(aba) {
  atribuir({ aba });
}

export function definirCarregando(carregando) {
  atribuir({ carregando });
}
