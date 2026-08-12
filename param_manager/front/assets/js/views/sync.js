/*
 * Tela de sincronização: calcular o plano, olhar o diff, aplicar.
 *
 * Duas fases separadas por um botão, exatamente como a lib as separa:
 * `sync_plan` não grava nada, `sync_apply` só aplica o que o plano
 * marcou. Conflito nunca entra sozinho — promovê-lo a `update` é ação
 * explícita do operador, uma caixa por item, e é isso que deixa a decisão
 * registrada no plano em vez de num parâmetro solto.
 */

import { t } from '../i18n.js';
import { confirmar, toast } from '../a11y.js';
import { aplicarPlano, calcularPlano, state } from '../store.js';

const ACAO_CONFLITO = 'conflict';

function familiaDaAcao(acao) {
  if (acao === ACAO_CONFLITO) {
    return 'blocked';
  }
  return acao === 'create' ? 'pending' : 'synced';
}

export function desenharSync() {
  const area = document.getElementById('sync-conteudo');
  const resumo = document.getElementById('sync-resumo');
  area.replaceChildren();

  resumo.textContent = t('sync.resumo', {
    pendentes: state.sync.pending,
    conflitos: state.sync.conflict,
    rejeitados: state.sync.rejected,
  });

  if (state.modo !== 'local') {
    const aviso = document.createElement('div');
    aviso.className = 'alert alert--info';
    aviso.textContent = t('sync.somenteLocal');
    area.append(aviso);
    return;
  }

  const plano = state.plano;
  if (!plano) {
    const vazio = document.createElement('p');
    vazio.className = 'muted';
    vazio.textContent = t('sync.semPlano');
    area.append(vazio);
    return;
  }

  if (plano.apps_to_create && plano.apps_to_create.length) {
    const bloco = document.createElement('div');
    bloco.className = 'alert alert--info';
    bloco.textContent = t('sync.appsACriar', {
      apps: plano.apps_to_create.join(', '),
    });
    area.append(bloco);
  }

  const itens = plano.params || [];
  if (!itens.length) {
    const vazio = document.createElement('p');
    vazio.className = 'muted';
    vazio.textContent = t('sync.nadaAEnviar');
    area.append(vazio);
    return;
  }

  itens.forEach((item, indice) => {
    area.append(desenharItem(item, indice));
  });
}

function desenharItem(item, indice) {
  const bloco = document.createElement('article');
  bloco.className = 'plan-item';
  if (item.action === ACAO_CONFLITO) {
    bloco.classList.add('plan-item--blocked');
  }

  const cabecalho = document.createElement('div');
  cabecalho.className = 'plan-item__head';

  const nome = document.createElement('span');
  nome.className = 'plan-item__name';
  nome.textContent = `${item.app} · ${item.name}`;

  const acao = document.createElement('span');
  acao.className = `chip chip--${familiaDaAcao(item.action)}`;
  acao.textContent = t(`sync.acao.${item.action}`);

  cabecalho.append(nome, acao);
  bloco.append(cabecalho);

  if (item.reason) {
    const motivo = document.createElement('p');
    motivo.className = 'plan-item__detail';
    motivo.textContent = t('sync.motivo', { motivo: item.reason });
    bloco.append(motivo);
  }

  const diff = document.createElement('p');
  diff.className = 'plan-item__detail mono';
  diff.textContent = t('sync.diff', {
    local: resumirPayload(item.local),
    remoto: resumirPayload(item.remote),
  });
  bloco.append(diff);

  if (item.action === ACAO_CONFLITO) {
    const linha = document.createElement('div');
    linha.className = 'checkbox-row';
    const marca = document.createElement('input');
    marca.type = 'checkbox';
    marca.id = `promover-${indice}`;
    marca.dataset.indice = String(indice);
    marca.className = 'promover-conflito';
    const rotulo = document.createElement('label');
    rotulo.htmlFor = marca.id;
    rotulo.textContent = t('sync.promover');
    linha.append(marca, rotulo);
    bloco.append(linha);
  }

  return bloco;
}

/**
 * Resumo curto do payload, sem revelar valor sensível.
 *
 * O diff serve para decidir se envia; mostrar o valor inteiro de um
 * `secret` numa lista que pode ter dezenas de linhas seria expor o que a
 * tabela cuidadosamente não mostra.
 */
function resumirPayload(payload) {
  if (!payload) {
    return t('sync.ausente');
  }
  const tipo = payload.type || '?';
  if (['secret', 'user', 'users'].includes(tipo)) {
    return `${tipo}: ${t('sync.oculto')}`;
  }
  let valor = payload.value;
  if (typeof valor === 'object' && valor !== null) {
    valor = JSON.stringify(valor);
  }
  valor = String(valor);
  if (valor.length > 60) {
    valor = `${valor.slice(0, 57)}…`;
  }
  return `${tipo}: ${valor}`;
}

export function ligarAcoesDeSync() {
  document
    .getElementById('btn-calcular-plano')
    .addEventListener('click', async () => {
      try {
        await calcularPlano(null);
        desenharSync();
        toast(t('sync.planoCalculado'), 'ok');
      } catch (erro) {
        toast(erro.message, 'error');
      }
    });

  document
    .getElementById('btn-aplicar-plano')
    .addEventListener('click', async () => {
      if (!state.plano) {
        toast(t('sync.semPlano'), 'error');
        return;
      }

      const plano = promoverConflitosMarcados(state.plano);
      const aplicaveis = (plano.params || []).filter((item) =>
        ['create', 'update'].includes(item.action)
      );
      const confirmado = await confirmar({
        titulo: t('sync.aplicar.titulo'),
        texto: t('sync.aplicar.texto', { total: aplicaveis.length }),
        confirmar: t('acoes.aplicar'),
        perigoso: false,
      });
      if (!confirmado) {
        return;
      }

      try {
        const resultado = await aplicarPlano(plano);
        desenharSync();
        toast(t('sync.aplicado', { total: aplicaveis.length }), 'ok');
        relatar(resultado);
      } catch (erro) {
        toast(erro.message, 'error');
      }
    });
}

/**
 * Aplica as promoções que o operador marcou, numa cópia do plano.
 *
 * Mutar `state.plano` faria a tela mentir se a aplicação falhasse: os
 * conflitos apareceriam como `update` sem nunca terem sido enviados.
 */
function promoverConflitosMarcados(plano) {
  const marcados = new Set(
    Array.from(document.querySelectorAll('.promover-conflito'))
      .filter((entrada) => entrada.checked)
      .map((entrada) => Number(entrada.dataset.indice))
  );
  return {
    ...plano,
    params: (plano.params || []).map((item, indice) =>
      marcados.has(indice) ? { ...item, action: 'update' } : item
    ),
  };
}

/**
 * Mostra o que o servidor recusou, com o texto dele.
 *
 * Um 422 traz o `detail` verbatim de propósito: reescrevê-lo esconderia
 * qual regra foi violada, que é a única informação útil ali.
 */
function relatar(resultado) {
  const rejeitados = (resultado && resultado.rejected) || [];
  if (!rejeitados.length) {
    return;
  }
  const area = document.getElementById('sync-conteudo');
  const bloco = document.createElement('div');
  bloco.className = 'alert alert--error';
  bloco.setAttribute('role', 'alert');

  const titulo = document.createElement('strong');
  titulo.textContent = t('sync.rejeitados', { total: rejeitados.length });
  bloco.append(titulo);

  rejeitados.forEach((item) => {
    const linha = document.createElement('p');
    linha.className = 'alert__text';
    linha.textContent = `${item.app} · ${item.name}: ${item.detail || ''}`;
    bloco.append(linha);
  });
  area.prepend(bloco);
}
