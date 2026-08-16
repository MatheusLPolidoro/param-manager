/*
 * Filtros de lista: termos livres acumulados e seleção por tipo.
 *
 * Espelha o par `SearchInput` + `TypeFilterDropdown` do `adm-param`: o
 * campo de busca vira **etiqueta** ao teclar Enter, então dá para
 * empilhar critérios em vez de reescrever a busca a cada tentativa.
 *
 * Regra de combinação, e ela não é óbvia:
 *
 * - **entre termos, E** — cada etiqueta estreita o resultado, que é o
 *   que "adicionar um filtro" significa para quem está procurando;
 * - **entre tipos, OU** — marcar `int` e `float` quer dizer "qualquer um
 *   dos dois"; E ali daria lista vazia sempre, já que um parâmetro tem
 *   um tipo só;
 * - **entre os dois grupos, E**.
 */

import { t } from './i18n.js';
import { icone } from './icons.js';

/** Estado de um filtro. Puro: quem desenha decide o que fazer com ele. */
export function criarFiltro() {
  return { termos: [], tipos: [], texto: '' };
}

export function filtroVazio(filtro) {
  return !filtro.termos.length && !filtro.tipos.length;
}

function combina(texto, termo) {
  return String(texto || '')
    .toLowerCase()
    .includes(termo.toLowerCase());
}

/**
 * Aplica o filtro sobre uma lista.
 *
 * `campos` diz onde procurar cada termo — nome e descrição, tipicamente.
 * `tipoDe` extrai o tipo do item, ou `null` quando a lista não tem tipo
 * (a de aplicações, por exemplo).
 */
export function aplicarFiltro(itens, filtro, campos, tipoDe = null) {
  return itens.filter((item) => {
    const casaTermos = filtro.termos.every((termo) =>
      campos.some((campo) => combina(campo(item), termo))
    );
    if (!casaTermos) {
      return false;
    }
    if (!filtro.tipos.length || !tipoDe) {
      return true;
    }
    return filtro.tipos.includes(tipoDe(item));
  });
}

function etiqueta(texto, aoRemover, classe = 'etiqueta') {
  const marca = document.createElement('span');
  marca.className = classe;
  marca.append(document.createTextNode(texto));

  const remover = document.createElement('button');
  remover.type = 'button';
  remover.className = 'etiqueta__remover';
  remover.append(icone('fechar'));
  remover.setAttribute('aria-label', t('filtro.remover', { termo: texto }));
  remover.title = t('filtro.remover', { termo: texto });
  remover.addEventListener('click', aoRemover);

  marca.append(remover);
  return marca;
}

/**
 * Monta a barra de filtro. Devolve o elemento; o estado é o que veio.
 *
 * `aoMudar` é chamado depois de toda alteração — quem chama redesenha a
 * lista a partir do mesmo `filtro`.
 */
export function barraDeFiltro({
  filtro,
  aoMudar,
  tipos = [],
  rotulo,
  total = 0,
  exibidos = 0,
}) {
  const barra = document.createElement('div');
  barra.className = 'filtro';
  barra.setAttribute('role', 'search');
  barra.setAttribute('aria-label', rotulo);

  const linha = document.createElement('div');
  linha.className = 'filtro__linha';

  // --- campo de busca ---
  const caixa = document.createElement('div');
  caixa.className = 'filtro__campo';
  const lupa = icone('lupa', 'icone filtro__lupa');
  if (lupa) {
    caixa.append(lupa);
  }

  const entrada = document.createElement('input');
  entrada.type = 'search';
  entrada.className = 'input filtro__entrada';
  entrada.value = filtro.texto;
  // Placeholder curto porque a trilha tem 240px e qualquer frase é
  // cortada ali. A instrução do Enter vai para o `title`, onde cabe.
  entrada.placeholder = t('filtro.placeholder');
  entrada.title = t('filtro.dica');
  entrada.setAttribute('aria-label', `${rotulo}. ${t('filtro.dica')}`);
  entrada.addEventListener('input', () => {
    // O texto em digitação já filtra, sem esperar Enter: buscar exige
    // retorno imediato. Enter apenas o promove a etiqueta.
    filtro.texto = entrada.value;
    aoMudar({ manterFoco: true });
  });
  entrada.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Enter') {
      return;
    }
    evento.preventDefault();
    const termo = entrada.value.trim();
    if (termo && !filtro.termos.includes(termo)) {
      filtro.termos.push(termo);
    }
    filtro.texto = '';
    aoMudar({ manterFoco: true });
  });
  caixa.append(entrada);
  linha.append(caixa);

  // --- seleção de tipos ---
  if (tipos.length) {
    const seletor = document.createElement('select');
    seletor.className = 'select filtro__tipos';
    seletor.setAttribute('aria-label', t('filtro.tipo'));

    const vazio = document.createElement('option');
    vazio.value = '';
    vazio.textContent = t('filtro.tipo');
    seletor.append(vazio);

    tipos
      .filter((tipo) => !filtro.tipos.includes(tipo))
      .forEach((tipo) => {
        const opcao = document.createElement('option');
        opcao.value = tipo;
        opcao.textContent = tipo;
        seletor.append(opcao);
      });

    seletor.addEventListener('change', () => {
      if (seletor.value) {
        filtro.tipos.push(seletor.value);
        aoMudar({});
      }
    });
    linha.append(seletor);
  }

  // --- limpar ---
  if (!filtroVazio(filtro) || filtro.texto) {
    const limpar = document.createElement('button');
    limpar.type = 'button';
    limpar.className = 'btn btn--ghost btn--icone';
    limpar.append(icone('fechar'));
    limpar.setAttribute('aria-label', t('filtro.limpar'));
    limpar.title = t('filtro.limpar');
    limpar.addEventListener('click', () => {
      filtro.termos = [];
      filtro.tipos = [];
      filtro.texto = '';
      aoMudar({});
    });
    linha.append(limpar);
  }

  barra.append(linha);

  // --- etiquetas ativas ---
  if (!filtroVazio(filtro)) {
    const ativas = document.createElement('div');
    ativas.className = 'filtro__etiquetas';

    filtro.termos.forEach((termo, indice) => {
      ativas.append(
        etiqueta(termo, () => {
          filtro.termos.splice(indice, 1);
          aoMudar({});
        })
      );
    });
    filtro.tipos.forEach((tipo, indice) => {
      ativas.append(
        etiqueta(
          tipo,
          () => {
            filtro.tipos.splice(indice, 1);
            aoMudar({});
          },
          'etiqueta etiqueta--tipo'
        )
      );
    });

    barra.append(ativas);

    const contagem = document.createElement('p');
    contagem.className = 'filtro__contagem';
    // `polite` porque o número muda a cada tecla: assertivo interromperia
    // o leitor de tela a cada caractere digitado.
    contagem.setAttribute('aria-live', 'polite');
    contagem.textContent = t('filtro.resultados', {
      exibidos,
      total,
    });
    barra.append(contagem);
  }

  return { elemento: barra, entrada };
}
