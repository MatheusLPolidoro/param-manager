/*
 * Editor de código: numeração de linha e realce de sintaxe.
 *
 * Serve `json` e `pattern`, que são os tipos lidos caractere a caractere.
 * Os dois compartilham o mesmo desenho de propósito — quem edita um
 * reconhece o outro.
 *
 * ## Como funciona, e por que assim
 *
 * Um `<textarea>` **transparente** por cima de um `<pre>` colorido, os
 * dois com métricas idênticas. É a única técnica que preserva o cursor,
 * a seleção, o desfazer e a acessibilidade nativos do campo — reimplantar
 * isso num `contenteditable` custa caro e sempre fica pior.
 *
 * Os dois precisam concordar em **fonte, tamanho, entrelinha, padding e
 * quebra de linha**. Divergir em qualquer um desloca o texto colorido do
 * texto real, e o defeito aparece só no fim de linhas longas.
 *
 * Sem dependência: realçar JSON e regex é um punhado de expressões
 * regulares, e trazer um realçador completo para dois tipos seria
 * desproporcional num app que não tem bundler.
 */

const MAPA_ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };

function escapar(texto) {
  return texto.replace(/[&<>]/g, (c) => MAPA_ESCAPE[c]);
}

/**
 * Realce de JSON.
 *
 * Um passo só, com alternativas ordenadas: string primeiro, para que
 * chaves e números *dentro* de uma string não sejam repintados. A
 * distinção chave/valor sai do `:` que segue a string.
 */
function realcarJson(texto) {
  return escapar(texto).replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([{}[\],])/g,
    (todo, cadeia, doisPontos, literal, numero, pontuacao) => {
      if (cadeia) {
        return doisPontos
          ? `<span class="cod-chave">${cadeia}</span>` +
              `<span class="cod-pontuacao">${doisPontos}</span>`
          : `<span class="cod-cadeia">${cadeia}</span>`;
      }
      if (literal) {
        return `<span class="cod-literal">${literal}</span>`;
      }
      if (numero) {
        return `<span class="cod-numero">${numero}</span>`;
      }
      return `<span class="cod-pontuacao">${pontuacao}</span>`;
    }
  );
}

/**
 * Realce de expressão regular.
 *
 * Escape primeiro: `\d` é um átomo, e deixar a barra invertida solta
 * faria o `d` ser pintado como literal comum. Classe de caracteres vem
 * antes de tudo o mais porque dentro dela `.` e `*` são literais.
 */
function realcarPattern(texto) {
  return escapar(texto).replace(
    /(\\.)|(\[\^?(?:\\.|[^\]\\])*\])|([(){}|])|([*+?]|\{\d+(?:,\d*)?\})|([\^$])/g,
    (todo, escape, classe, grupo, quantificador, ancora) => {
      if (escape) {
        return `<span class="cod-escape">${escape}</span>`;
      }
      if (classe) {
        return `<span class="cod-classe">${classe}</span>`;
      }
      if (grupo) {
        return `<span class="cod-grupo">${grupo}</span>`;
      }
      if (quantificador) {
        return `<span class="cod-quantificador">${quantificador}</span>`;
      }
      return `<span class="cod-ancora">${ancora}</span>`;
    }
  );
}

const REALCADORES = { json: realcarJson, pattern: realcarPattern };

/**
 * Monta o editor. Devolve `{ elemento, campo, ler }`.
 *
 * `campo` é o `<textarea>` de verdade, para quem precisar focar ou
 * posicionar o cursor.
 */
export function editorDeCodigo(tipo, texto, { placeholder = '' } = {}) {
  const realcar = REALCADORES[tipo] || escapar;

  const raiz = document.createElement('div');
  raiz.className = 'codigo';

  const numeros = document.createElement('div');
  numeros.className = 'codigo__numeros';
  numeros.setAttribute('aria-hidden', 'true');

  const painel = document.createElement('div');
  painel.className = 'codigo__painel';

  const realce = document.createElement('pre');
  realce.className = 'codigo__realce';
  realce.setAttribute('aria-hidden', 'true');

  const campo = document.createElement('textarea');
  campo.className = 'codigo__campo';
  campo.value = texto || '';
  campo.placeholder = placeholder;
  campo.spellcheck = false;
  campo.autocapitalize = 'off';
  campo.autocomplete = 'off';
  campo.wrap = 'off';

  function pintar() {
    // A última linha some do `<pre>` quando o texto termina em `\n`;
    // o espaço final a preserva e mantém realce e campo do mesmo tamanho.
    realce.innerHTML = `${realcar(campo.value)} `;

    const linhas = campo.value.split('\n').length;
    if (numeros.childElementCount !== linhas) {
      numeros.replaceChildren();
      for (let i = 1; i <= linhas; i += 1) {
        const numero = document.createElement('span');
        numero.textContent = String(i);
        numeros.append(numero);
      }
    }
  }

  function sincronizarRolagem() {
    realce.scrollTop = campo.scrollTop;
    realce.scrollLeft = campo.scrollLeft;
    numeros.scrollTop = campo.scrollTop;
  }

  campo.addEventListener('input', pintar);
  campo.addEventListener('scroll', sincronizarRolagem);

  // Tab indenta em vez de sair do campo. Num editor de código sair é o
  // comportamento errado — e `Esc` depois de `Tab` continua saindo, que
  // é a saída que a acessibilidade exige.
  campo.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Tab' || evento.shiftKey) {
      return;
    }
    evento.preventDefault();
    const { selectionStart: inicio, selectionEnd: fim, value } = campo;
    campo.value = `${value.slice(0, inicio)}  ${value.slice(fim)}`;
    campo.setSelectionRange(inicio + 2, inicio + 2);
    pintar();
  });

  pintar();
  painel.append(realce, campo);
  raiz.append(numeros, painel);
  return { elemento: raiz, campo, ler: () => campo.value };
}
