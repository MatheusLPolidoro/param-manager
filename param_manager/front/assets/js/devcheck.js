/*
 * Verificação de acessibilidade em modo de desenvolvimento (`?dev=1`).
 *
 * **Não substitui o axe-core.** Cobre o punhado de defeitos que este app
 * consegue introduzir sozinho — controle sem nome acessível, campo sem
 * rótulo, `id` duplicado, `aria-selected` numa linha que ninguém alcança
 * pelo teclado — e que são justamente os que aparecem ao gerar DOM por
 * JavaScript.
 *
 * Se `js/vendor/axe.min.js` existir, ele é usado e manda: basta soltar o
 * arquivo ali. Nada no empacotamento o exige, e o CI não depende dele —
 * é ferramenta de quem está desenvolvendo, não portão de qualidade.
 */

function nomeAcessivel(elemento) {
  return (
    elemento.getAttribute('aria-label') ||
    elemento.getAttribute('title') ||
    (elemento.textContent || '').trim() ||
    (elemento.labels && elemento.labels.length
      ? elemento.labels[0].textContent.trim()
      : '')
  );
}

function checagensProprias() {
  const problemas = [];

  document.querySelectorAll('button, [role="button"]').forEach((botao) => {
    if (!nomeAcessivel(botao)) {
      problemas.push(['controle sem nome acessível', botao]);
    }
  });

  document.querySelectorAll('input, select, textarea').forEach((campo) => {
    if (campo.type === 'hidden') {
      return;
    }
    if (!nomeAcessivel(campo) && !campo.getAttribute('aria-labelledby')) {
      problemas.push(['campo sem rótulo', campo]);
    }
  });

  const vistos = new Set();
  document.querySelectorAll('[id]').forEach((elemento) => {
    if (vistos.has(elemento.id)) {
      problemas.push([`id duplicado: ${elemento.id}`, elemento]);
    }
    vistos.add(elemento.id);
  });

  document.querySelectorAll('img').forEach((imagem) => {
    if (!imagem.hasAttribute('alt')) {
      problemas.push(['imagem sem alt', imagem]);
    }
  });

  document.querySelectorAll('[aria-selected]').forEach((linha) => {
    if (linha.tabIndex === undefined || linha.tabIndex === null) {
      problemas.push(['aria-selected sem foco possível', linha]);
    }
  });

  return problemas;
}

async function tentarAxe() {
  try {
    const modulo = await import('./vendor/axe.min.js');
    const axe = modulo.default || window.axe;
    if (!axe) {
      return null;
    }
    return axe.run(document, { resultTypes: ['violations'] });
  } catch {
    return null;
  }
}

export async function rodarChecagens() {
  const proprias = checagensProprias();
  if (proprias.length) {
    console.warn(`[a11y] ${proprias.length} problema(s) próprio(s):`);
    proprias.forEach(([descricao, elemento]) =>
      console.warn(' -', descricao, elemento)
    );
  } else {
    console.info('[a11y] checagens próprias: nenhum problema.');
  }

  const resultado = await tentarAxe();
  if (!resultado) {
    console.info(
      '[a11y] axe-core ausente. Para usá-lo, coloque o bundle em ' +
        'assets/js/vendor/axe.min.js.'
    );
    return;
  }
  if (resultado.violations.length) {
    console.warn(`[a11y] axe: ${resultado.violations.length} violação(ões)`);
    console.table(
      resultado.violations.map((v) => ({
        id: v.id,
        impacto: v.impact,
        nos: v.nodes.length,
      }))
    );
  } else {
    console.info('[a11y] axe: nenhuma violação.');
  }
}
