/*
 * Ícones — SVG desenhado aqui, sem dependência e sem arquivo por ícone.
 *
 * Não há Node nem bundler neste app, e a CSP não pode ser declarada
 * (o `pytauri-wheel` dá panic com ela), então uma folha de sprites
 * externa ou uma fonte de ícones teriam um custo maior do que valem.
 * Doze traçados resolvem as ações que existem.
 *
 * Três regras que os fazem se comportar:
 *
 * 1. `stroke="currentColor"` e nada de `fill` — herdam a cor do texto,
 *    então funcionam nos dois temas sem uma linha de CSS a mais.
 * 2. `aria-hidden="true"` sempre. Ícone aqui **acompanha** um rótulo,
 *    nunca o substitui; anunciá-lo faria o leitor de tela repetir.
 * 3. Grade de 24, traço de 2, pontas arredondadas — é o que os mantém
 *    parecidos entre si.
 */

const TRACADOS = {
  mais: '<path d="M12 5v14M5 12h14"/>',
  lixeira:
    '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>',
  sincronizar:
    '<path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-7.9-4.7"/>' +
    '<path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 7.9 4.7"/>' +
    '<path d="M3 21v-5h5M21 3v5h-5"/>',
  olho: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/>'
    + '<circle cx="12" cy="12" r="3"/>',
  olhoCortado:
    '<path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-3 3.9"/>'
    + '<path d="M6.6 6.6A17.6 17.6 0 0 0 2 12s3.6 7 10 7a10.7 10.7 0 0 0 4.6-1"/>'
    + '<path d="M3 3l18 18"/>',
  sol: '<circle cx="12" cy="12" r="4"/>'
    + '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
    + 'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  lua: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>',
  globo: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
    + '<path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18Z"/>',
  caixa: '<path d="M3 7l9-4 9 4-9 4-9-4Z"/><path d="M3 7v10l9 4 9-4V7"/>'
    + '<path d="M12 11v10"/>',
  etiqueta:
    '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0l-7.2-7.2A2 2 0 0 1 3 12V4h8'
    + 'a2 2 0 0 1 1.4.6l7.2 7.2a2 2 0 0 1 0 2.6Z"/><circle cx="7" cy="8" r="1"/>',
  engrenagem:
    '<circle cx="12" cy="12" r="3"/>'
    + '<path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 '
    + '1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5'
    + ' 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 '
    + '1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8'
    + 'l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3'
    + 'a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 '
    + '2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1'
    + 'a1.6 1.6 0 0 0-1.5 1Z"/>',
  anterior: '<path d="M15 18l-6-6 6-6"/>',
  proximo: '<path d="M9 18l6-6-6-6"/>',
  monitor:
    '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  alerta:
    '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>'
    + '<path d="M12 9v4M12 17h.01"/>',
  fechar: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  expandir:
    '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  lupa: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  funil: '<path d="M22 3H2l8 9.5V19l4 2v-8.5L22 3Z"/>',
  chave: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 8.6-8.6"/>'
    + '<path d="m17 6 2.5 2.5M14.5 8.5 17 11"/>',
  raio: '<path d="M13 2 3 14h8l-1 8 10-12h-8l1-8Z"/>',
  nuvem:
    '<path d="M17.5 19a4.5 4.5 0 0 0 .5-9 6 6 0 0 0-11.6-1.5A4 4 0 0 0 6.5 19Z"/>',
  disco: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/>'
    + '<path d="M17 21v-8H7v8M7 3v5h8"/>',

  // --- tipos de parâmetro -------------------------------------------------
  // Um por família, não um por tipo: `int` e `float` são o mesmo desenho,
  // e o rótulo ao lado já os separa.
  texto: '<path d="M4 7V5h16v2M9 19h6M12 5v14"/>',
  numero: '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
  alternador:
    '<rect x="1" y="6" width="22" height="12" rx="6"/><circle cx="8" cy="12" r="3"/>',
  calendario:
    '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/>',
  relogio: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  chaves:
    '<path d="M8 3H7a2 2 0 0 0-2 2v4a2 2 0 0 1-2 2 2 2 0 0 1 2 2v4a2 2 0 0 0 2 2h1"/>'
    + '<path d="M16 3h1a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2 2 2 0 0 0-2 2v4a2 2 0 0 1-2 2h-1"/>',
  lista: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  arquivo:
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/>'
    + '<path d="M14 2v6h6"/>',
  elo: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/>'
    + '<path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  usuario: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
    + '<circle cx="12" cy="7" r="4"/>',
  usuarios:
    '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
    + '<path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
  regex:
    '<path d="M17 3v10M12.7 5.5l8.6 5M12.7 10.5l8.6-5"/>'
    + '<rect x="3" y="16" width="5" height="5" rx="1"/>',
};

/*
 * Tipo de parâmetro → ícone. Famílias, não um desenho por tipo.
 *
 * Tipo fora do mapa cai em `texto`: o catálogo vem do servidor e pode
 * ganhar tipos que este cliente não conhece — mostrar o genérico é
 * melhor do que deixar um buraco na linha.
 */
const ICONE_POR_TIPO = {
  string: 'texto',
  pattern: 'regex',
  int: 'numero',
  float: 'numero',
  bool: 'alternador',
  date: 'calendario',
  datetime: 'calendario',
  time: 'relogio',
  dict: 'chaves',
  json: 'arquivo',
  list: 'lista',
  reference: 'elo',
  secret: 'olhoCortado',
  user: 'usuario',
  users: 'usuarios',
};

export function iconeDoTipo(tipo) {
  return icone(ICONE_POR_TIPO[tipo] || 'texto');
}

/**
 * Devolve o `<svg>` do ícone, ou `null` se o nome não existir.
 *
 * Devolver `null` em vez de levantar: um ícone que falta é um defeito
 * cosmético, e derrubar a renderização de uma tela por causa dele seria
 * desproporcional.
 */
export function icone(nome, classe = 'icone') {
  const tracado = TRACADOS[nome];
  if (!tracado) {
    return null;
  }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('class', classe);
  // Conteúdo é constante deste módulo, nunca dado do usuário.
  svg.innerHTML = tracado;
  return svg;
}

/** Põe o ícone antes do texto que já está no elemento. */
export function prefixarIcone(elemento, nome) {
  const svg = icone(nome);
  if (svg) {
    elemento.prepend(svg);
    elemento.classList.add('com-icone');
  }
  return elemento;
}
