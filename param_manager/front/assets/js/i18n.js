/*
 * Tradução. Nenhuma string literal de interface mora fora dos catálogos.
 *
 * O HTML declara `data-i18n` e é preenchido na subida; o JS chama `t()`.
 * A regra existe para que "traduzir" seja sempre a mesma operação —
 * acrescentar uma chave nos dois arquivos — e para que
 * `tests/test_front_i18n.py` consiga provar que nenhuma ficou para trás.
 */

const CATALOGOS = {};
let idiomaAtual = 'pt-BR';

/** Carrega um catálogo e passa a usá-lo. */
export async function carregarIdioma(idioma) {
  if (!CATALOGOS[idioma]) {
    const resposta = await fetch(`i18n/${idioma}.json`);
    if (!resposta.ok) {
      throw new Error(`Catálogo de idioma ausente: ${idioma}`);
    }
    CATALOGOS[idioma] = await resposta.json();
  }
  idiomaAtual = idioma;
  document.documentElement.lang = idioma;
  return idioma;
}

export function idioma() {
  return idiomaAtual;
}

/**
 * Traduz uma chave, interpolando `{vars}`.
 *
 * Chave ausente devolve a própria chave: numa tela, `params.state.dirty`
 * é feio mas diz o que falta. Devolver vazio esconderia o defeito.
 */
export function t(chave, vars) {
  const catalogo = CATALOGOS[idiomaAtual] || {};
  let texto = catalogo[chave];
  if (texto === undefined) {
    return chave;
  }
  if (vars) {
    for (const [nome, valor] of Object.entries(vars)) {
      texto = texto.split(`{${nome}}`).join(String(valor));
    }
  }
  return texto;
}

/**
 * Aplica o catálogo ao HTML estático.
 *
 * `data-i18n` preenche o texto; `data-i18n-attr` preenche atributos, no
 * formato `atributo:chave`, separados por vírgula — é como `title`,
 * `aria-label` e `placeholder` são traduzidos sem JS por elemento.
 */
export function traduzirDocumento(raiz = document) {
  raiz.querySelectorAll('[data-i18n]').forEach((elemento) => {
    elemento.textContent = t(elemento.dataset.i18n);
  });
  raiz.querySelectorAll('[data-i18n-attr]').forEach((elemento) => {
    elemento.dataset.i18nAttr.split(',').forEach((par) => {
      const [atributo, chave] = par.split(':').map((s) => s.trim());
      if (atributo && chave) {
        elemento.setAttribute(atributo, t(chave));
      }
    });
  });
}

/**
 * Normaliza os dois formatos de data que chegam aqui.
 *
 * O sidecar guarda epoch em segundos (`time.time()`); o servidor devolve
 * ISO-8601. Tratar só um deixava a coluna "atualizado" em travessão no
 * outro modo — e como o travessão também é o valor legítimo de "sem
 * data", o defeito passava por comportamento.
 */
function paraData(valor) {
  if (valor === null || valor === undefined || valor === '') {
    return null;
  }
  if (typeof valor === 'number') {
    const epoch = new Date(valor * 1000);
    return Number.isNaN(epoch.getTime()) ? null : epoch;
  }

  // O servidor carimba em UTC mas serializa SEM fuso
  // (`2026-08-11T23:01:37.466078`), e o JavaScript lê data-e-hora sem
  // fuso como **hora local**. Num fuso a oeste isso joga o carimbo para
  // o futuro, e a coluna mostrava "em 3 horas" para algo gravado agora.
  //
  // A marcação é acrescentada só quando ela falta, para não estragar
  // uma data que já venha com fuso.
  const semFuso = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;
  const texto = semFuso.test(valor) ? `${valor.replace(' ', 'T')}Z` : valor;
  const data = new Date(texto);
  return Number.isNaN(data.getTime()) ? null : data;
}

/** Data e hora completas, no formato do idioma. Ausente vira travessão. */
export function formatarData(valor) {
  const data = paraData(valor);
  return data ? data.toLocaleString(idiomaAtual) : '—';
}

const DEGRAUS = [
  ['second', 60],
  ['minute', 60],
  ['hour', 24],
  ['day', 7],
  ['week', 4.35],
  ['month', 12],
  ['year', Infinity],
];

/**
 * Tempo relativo — "há 2 horas" em vez de "11/08/2026, 14:56:37".
 *
 * `Intl.RelativeTimeFormat` é nativo da webview e já sabe os dois
 * idiomas. Preferido ao `humanize` do Python por duas razões: não
 * acrescenta dependência a uma biblioteca cujo produto é ser embutível,
 * e **é recalculado a cada redesenho** — uma string humanizada no lado
 * Python seria produzida na busca e envelheceria na tela, com a linha
 * dizendo "há 2 minutos" meia hora depois.
 *
 * Acima de uma semana devolve a data absoluta: "há 3 meses" não ajuda
 * ninguém a achar o que mudou, e a data exata ajuda.
 */
export function formatarDataRelativa(valor) {
  const data = paraData(valor);
  if (!data) {
    return '—';
  }
  const formatador = new Intl.RelativeTimeFormat(idiomaAtual, {
    numeric: 'auto',
  });

  let delta = (data.getTime() - Date.now()) / 1000;
  for (const [unidade, limite] of DEGRAUS) {
    if (Math.abs(delta) < limite) {
      return formatador.format(Math.round(delta), unidade);
    }
    delta /= limite;
    if (unidade === 'day') {
      break;
    }
  }
  return data.toLocaleDateString(idiomaAtual);
}
