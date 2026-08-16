/*
 * Editor de valor por tipo de parâmetro.
 *
 * Espelha o `InputFieldRenderer` do `adm-param`, com uma diferença que
 * não é cosmética: **os nomes de tipo aqui são os do catálogo do
 * servidor** — `int`, `float`, `bool` —, não os `number`/`decimal`/
 * `boolean` que aquele projeto usa no config e depois remenda no
 * renderizador. Catálogo é a fonte; duas grafias para o mesmo tipo é
 * como divergência começa.
 *
 * Cada editor devolve `{ elemento, ler }`. Ler o valor pelo objeto, e
 * não por `getElementById`, é o que permite ter editores compostos
 * (dicionário, lista, usuários) sem inventar um id por linha.
 *
 * Nenhum editor levanta ao montar. `ler()` **pode** levantar quando o
 * texto digitado não é JSON válido — é o único caminho em que a
 * exceção carrega informação que o usuário precisa ver.
 */

import { t } from './i18n.js';
import { icone } from './icons.js';
import {
  LIMITE_COMPOSTO,
  controlePaginacao,
  paginar,
} from './paginacao.js';
import { editorDeCodigo } from './editor-codigo.js';

const TIPOS_SENSIVEIS = ['secret', 'user', 'users'];

/* ------------------------------------------------------------ auxiliares */

function elemento(tag, classe, texto) {
  const el = document.createElement(tag);
  if (classe) {
    el.className = classe;
  }
  if (texto !== undefined) {
    el.textContent = texto;
  }
  return el;
}

function botaoIcone(nome, rotulo, classe = 'btn btn--ghost btn--icone') {
  const botao = elemento('button', classe);
  botao.type = 'button';
  const svg = icone(nome);
  if (svg) {
    botao.append(svg);
  }
  botao.setAttribute('aria-label', rotulo);
  botao.title = rotulo;
  return botao;
}

/** Texto → objeto, com mensagem que diz onde quebrou. */
function lerJson(texto, vazio) {
  if (!texto.trim()) {
    return vazio;
  }
  try {
    return JSON.parse(texto);
  } catch (erro) {
    throw new Error(t('params.erro.json', { detalhe: erro.message }));
  }
}

/* --------------------------------------------------------- tipos simples */

function editorTexto(valor, tipo, sensivel) {
  const entrada = elemento('input', 'input');
  entrada.type = sensivel ? 'password' : 'text';
  entrada.value = valor === null || valor === undefined ? '' : String(valor);
  entrada.placeholder = t(`params.placeholder.${tipo}`);

  if (!sensivel) {
    return { elemento: entrada, ler: () => entrada.value };
  }

  // Revelar é ação explícita: o valor fica visível para quem estiver por
  // perto e em qualquer captura de tela.
  const linha = elemento('div', 'secret');
  const botao = botaoIcone('olho', t('params.revelar'));
  botao.setAttribute('aria-pressed', 'false');
  botao.addEventListener('click', () => {
    const revelado = entrada.type === 'text';
    entrada.type = revelado ? 'password' : 'text';
    botao.setAttribute('aria-pressed', String(!revelado));
    const rotulo = revelado ? t('params.revelar') : t('params.ocultar');
    botao.setAttribute('aria-label', rotulo);
    botao.title = rotulo;
    botao.replaceChildren(icone(revelado ? 'olho' : 'olhoCortado'));
  });
  linha.append(entrada, botao);
  return { elemento: linha, ler: () => entrada.value };
}

/**
 * Número, com o teclado restrito ao que o tipo aceita.
 *
 * `<input type="number">` aceita notação científica: `1e5`, `+`, e para
 * `int` também o separador decimal. Digitar `e` num inteiro passava pelo
 * campo e virava `NaN` no `parseInt` — ou, pior, `1e5` virava `1`
 * silenciosamente, porque `parseInt` para no primeiro caractere inválido.
 *
 * O filtro é no `beforeinput`, e não no `keydown`: ele também cobre colar
 * e ditado, que o `keydown` não vê.
 */
function editorNumero(valor, tipo) {
  const inteiro = tipo === 'int';
  const entrada = elemento('input', 'input input--numero');
  entrada.type = 'number';
  entrada.step = inteiro ? '1' : 'any';
  entrada.inputMode = inteiro ? 'numeric' : 'decimal';
  entrada.value = valor === null || valor === undefined ? '' : valor;
  entrada.placeholder = t(`params.placeholder.${tipo}`);

  const permitido = inteiro ? /^-?\d*$/ : /^-?\d*[.,]?\d*$/;

  entrada.addEventListener('beforeinput', (evento) => {
    if (evento.data === null || evento.data === undefined) {
      return;
    }
    // Reconstrói como ficaria o texto e recusa o que não casar. Testar
    // só o caractere digitado deixaria passar um `-` no meio.
    const atual = entrada.value;
    const inicio = entrada.selectionStart ?? atual.length;
    const fim = entrada.selectionEnd ?? atual.length;
    const futuro = atual.slice(0, inicio) + evento.data + atual.slice(fim);
    if (!permitido.test(futuro)) {
      evento.preventDefault();
    }
  });

  return {
    elemento: entrada,
    ler: () => {
      const texto = entrada.value.trim().replace(',', '.');
      if (!texto) {
        return null;
      }
      const numero = inteiro
        ? Number.parseInt(texto, 10)
        : Number.parseFloat(texto);
      // `NaN` atravessaria como `null` no JSON e o servidor gravaria
      // vazio sem reclamar. Melhor recusar aqui, com o texto na mão.
      if (Number.isNaN(numero)) {
        throw new Error(t('params.erro.numero', { valor: entrada.value }));
      }
      return numero;
    },
  };
}

/**
 * Booleano como par de botões, não como caixa de marcar.
 *
 * A caixa confunde "false" com "não informado" — desmarcada, as duas
 * parecem iguais. Dois botões com estado selecionado tornam a escolha
 * visível, e `role="radiogroup"` faz o leitor de tela anunciar assim.
 */
function editorBooleano(valor) {
  const grupo = elemento('div', 'segmentado');
  grupo.setAttribute('role', 'radiogroup');
  grupo.setAttribute('aria-label', t('params.campo.valor'));

  let atual = valor === true ? true : valor === false ? false : null;

  const botoes = [true, false].map((opcao) => {
    const botao = elemento('button', 'segmentado__opcao');
    botao.type = 'button';
    botao.setAttribute('role', 'radio');
    botao.append(
      icone(opcao ? 'check' : 'fechar'),
      elemento('span', null, t(opcao ? 'params.bool.true' : 'params.bool.false'))
    );
    botao.addEventListener('click', () => {
      atual = opcao;
      sincronizar();
    });
    grupo.append(botao);
    return { botao, opcao };
  });

  function sincronizar() {
    botoes.forEach(({ botao, opcao }) => {
      const marcado = atual === opcao;
      botao.setAttribute('aria-checked', String(marcado));
      botao.classList.toggle('segmentado__opcao--ativo', marcado);
      botao.classList.toggle(
        'segmentado__opcao--verdadeiro',
        marcado && opcao
      );
      botao.classList.toggle('segmentado__opcao--falso', marcado && !opcao);
      // Só o selecionado entra na ordem de tabulação; as setas percorrem
      // o grupo, que é o comportamento esperado de um radiogroup.
      botao.tabIndex = marcado || (atual === null && opcao) ? 0 : -1;
    });
  }

  grupo.addEventListener('keydown', (evento) => {
    if (!['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown'].includes(
      evento.key
    )) {
      return;
    }
    evento.preventDefault();
    atual = !atual;
    sincronizar();
    botoes.find(({ opcao }) => opcao === atual).botao.focus();
  });

  sincronizar();
  return { elemento: grupo, ler: () => atual };
}

function editorDataHora(valor, tipo) {
  const entrada = elemento('input', 'input');
  entrada.type =
    tipo === 'date' ? 'date' : tipo === 'time' ? 'time' : 'datetime-local';
  entrada.value = valor === null || valor === undefined ? '' : String(valor);
  return { elemento: entrada, ler: () => entrada.value || null };
}

/**
 * `json` e `pattern` compartilham o editor de código.
 *
 * Os dois são lidos caractere a caractere — um por causa do aninhamento,
 * o outro porque cada símbolo muda o significado. Tratamento igual para
 * os dois é deliberado: quem edita um reconhece o outro.
 */
function editorCodigo(valor, tipo) {
  const texto =
    valor === null || valor === undefined
      ? ''
      : typeof valor === 'string'
        ? valor
        : JSON.stringify(valor, null, 2);

  const editor = editorDeCodigo(tipo, texto, {
    placeholder: t(`params.placeholder.${tipo}`),
  });

  return {
    elemento: editor.elemento,
    campo: editor.campo,
    ler: () => (tipo === 'json' ? lerJson(editor.ler(), null) : editor.ler()),
  };
}

/* ------------------------------------------------------ tipos compostos */

/**
 * Lista de itens: uma linha por item, com adicionar e remover.
 *
 * O textarea com JSON continua sendo o caminho de fuga — mas ele é o
 * caminho, não o padrão: digitar colchete e vírgula à mão para inserir
 * um e-mail numa lista é onde erro de sintaxe nasce.
 */
function editorLista(valor) {
  const raiz = elemento('div', 'composto');
  const linhas = elemento('div', 'composto__linhas');
  const rodape = elemento('div');

  const itens = Array.isArray(valor) ? valor.slice() : [];
  let pagina = 0;
  let tamanho = LIMITE_COMPOSTO;

  function desenhar() {
    linhas.replaceChildren();
    rodape.replaceChildren();

    if (!itens.length) {
      linhas.append(elemento('p', 'composto__vazio', t('params.lista.vazia')));
      return;
    }

    const recorte = paginar(itens, pagina, tamanho);
    pagina = recorte.pagina;

    recorte.itens.forEach((item) => {
      const indice = itens.indexOf(item);
      const linha = elemento('div', 'composto__linha');

      const ordem = elemento('span', 'composto__ordem', String(indice + 1));

      const entrada = elemento('input', 'input');
      entrada.value = item === null || item === undefined ? '' : String(item);
      entrada.placeholder = t('params.lista.item', { n: indice + 1 });
      entrada.setAttribute('aria-label', t('params.lista.item', { n: indice + 1 }));
      entrada.addEventListener('input', () => {
        itens[indice] = entrada.value;
      });

      const remover = botaoIcone(
        'lixeira',
        t('params.lista.remover', { n: indice + 1 }),
        'btn btn--ghost btn--icone btn--perigo-sutil'
      );
      remover.addEventListener('click', () => {
        itens.splice(indice, 1);
        desenhar();
      });

      linha.append(ordem, entrada, remover);
      linhas.append(linha);
    });

    const controle = controlePaginacao(recorte, (nova) => {
      pagina = nova;
      desenhar();
    }, 'params.lista.paginacao', {
      tamanho,
      aoTrocarTamanho: (novo) => {
        tamanho = novo;
        pagina = 0;
        desenhar();
      },
    });
    if (controle) {
      rodape.append(controle);
    }
  }

  const adicionar = elemento('button', 'btn btn--ghost com-icone');
  adicionar.type = 'button';
  adicionar.append(icone('mais'), elemento('span', null, t('params.lista.adicionar')));
  adicionar.addEventListener('click', () => {
    itens.push('');
    // Item novo vai para o fim; a última página é onde ele está.
    pagina = Math.ceil(itens.length / tamanho) - 1;
    desenhar();
    const campos = linhas.querySelectorAll('input');
    if (campos.length) {
      campos[campos.length - 1].focus();
    }
  });

  desenhar();
  raiz.append(linhas, rodape, adicionar);
  return { elemento: raiz, ler: () => itens.slice() };
}

/** Dicionário: par chave/valor por linha. */
function editorDicionario(valor) {
  const raiz = elemento('div', 'composto');
  const linhas = elemento('div', 'composto__linhas');
  const rodapeDict = elemento('div');
  let paginaDict = 0;
  let tamanhoDict = LIMITE_COMPOSTO;

  const pares =
    valor && typeof valor === 'object' && !Array.isArray(valor)
      ? Object.entries(valor).map(([chave, conteudo]) => ({
          chave,
          conteudo:
            typeof conteudo === 'object' && conteudo !== null
              ? JSON.stringify(conteudo)
              : conteudo,
        }))
      : [];

  function desenhar() {
    linhas.replaceChildren();
    rodapeDict.replaceChildren();

    if (!pares.length) {
      linhas.append(elemento('p', 'composto__vazio', t('params.dict.vazio')));
      return;
    }

    const recorte = paginar(pares, paginaDict, tamanhoDict);
    paginaDict = recorte.pagina;

    recorte.itens.forEach((par) => {
      const indice = pares.indexOf(par);
      const linha = elemento('div', 'composto__linha composto__linha--par');

      const chave = elemento('input', 'input mono');
      chave.value = par.chave;
      chave.placeholder = t('params.dict.chave');
      chave.addEventListener('input', () => {
        par.chave = chave.value;
      });

      const conteudo = elemento('input', 'input');
      conteudo.value =
        par.conteudo === null || par.conteudo === undefined
          ? ''
          : String(par.conteudo);
      conteudo.placeholder = t('params.dict.valor');
      conteudo.addEventListener('input', () => {
        par.conteudo = conteudo.value;
      });

      const remover = botaoIcone(
        'lixeira',
        t('params.dict.remover', { chave: par.chave || indice + 1 }),
        'btn btn--ghost btn--icone btn--perigo-sutil'
      );
      remover.addEventListener('click', () => {
        pares.splice(indice, 1);
        desenhar();
      });

      linha.append(chave, conteudo, remover);
      linhas.append(linha);
    });

    const controle = controlePaginacao(recorte, (nova) => {
      paginaDict = nova;
      desenhar();
    }, 'params.dict.paginacao', {
      tamanho: tamanhoDict,
      aoTrocarTamanho: (novo) => {
        tamanhoDict = novo;
        paginaDict = 0;
        desenhar();
      },
    });
    if (controle) {
      rodapeDict.append(controle);
    }
  }

  const adicionar = elemento('button', 'btn btn--ghost com-icone');
  adicionar.type = 'button';
  adicionar.append(icone('mais'), elemento('span', null, t('params.dict.adicionar')));
  adicionar.addEventListener('click', () => {
    pares.push({ chave: '', conteudo: '' });
    paginaDict = Math.ceil(pares.length / tamanhoDict) - 1;
    desenhar();
    const campos = linhas.querySelectorAll('input');
    if (campos.length) {
      campos[campos.length - 2].focus();
    }
  });

  desenhar();
  raiz.append(linhas, rodapeDict, adicionar);
  return {
    elemento: raiz,
    // Chave vazia é descartada: um par sem nome não tem como ser lido de
    // volta, e gravar `"": valor` produz um parâmetro que ninguém acha.
    ler: () =>
      Object.fromEntries(
        pares
          .filter((par) => par.chave.trim())
          .map((par) => [par.chave.trim(), par.conteudo])
      ),
  };
}

/**
 * Referência: escolhe entre os parâmetros que existem no app.
 *
 * Duas listas, como no `adm-param`: a primeira declara quais parâmetros
 * podem ser referenciados, a segunda escolhe os que valem agora — e a
 * segunda é **subconjunto** da primeira, por construção. Digitar nome de
 * parâmetro à mão é onde referência quebrada nasce.
 */
function editorReferencia(valor, contexto) {
  const disponiveis = (contexto.paramsDoApp || []).filter(
    (nome) => nome !== contexto.nomeAtual
  );
  const referenciaveis = new Set(contexto.referencedParams || []);
  const escolhidos = new Set(Array.isArray(valor) ? valor : []);

  const raiz = elemento('div', 'composto');

  if (!disponiveis.length) {
    raiz.append(
      elemento('p', 'composto__vazio', t('params.reference.semParams'))
    );
    return { elemento: raiz, ler: () => [], referenciaveis: () => [] };
  }

  function grupo(titulo, universo, selecao, aoMudar) {
    const bloco = elemento('fieldset', 'grupo-marcadores');
    bloco.append(elemento('legend', 'field__label', titulo));
    universo.forEach((nome) => {
      const linha = elemento('label', 'checkbox-row');
      const marca = elemento('input');
      marca.type = 'checkbox';
      marca.checked = selecao.has(nome);
      marca.addEventListener('change', () => {
        if (marca.checked) {
          selecao.add(nome);
        } else {
          selecao.delete(nome);
        }
        aoMudar();
      });
      linha.append(marca, elemento('span', 'mono', nome));
      bloco.append(linha);
    });
    return bloco;
  }

  const caixaValor = elemento('div');

  function desenharValor() {
    // Tirar um parâmetro da lista de referenciáveis precisa tirá-lo do
    // valor também, senão sobra uma referência a algo que a própria tela
    // acabou de dizer que não vale.
    [...escolhidos].forEach((nome) => {
      if (!referenciaveis.has(nome)) {
        escolhidos.delete(nome);
      }
    });
    caixaValor.replaceChildren(
      grupo(
        t('params.reference.valor'),
        [...referenciaveis],
        escolhidos,
        () => {}
      )
    );
  }

  raiz.append(
    grupo(
      t('params.reference.referenciaveis'),
      disponiveis,
      referenciaveis,
      desenharValor
    ),
    caixaValor
  );
  desenharValor();

  return {
    elemento: raiz,
    ler: () => [...escolhidos],
    referenciaveis: () => [...referenciaveis],
  };
}

/**
 * Identificador de usuário, no mesmo formato do `adm-param`:
 * `Math.random().toString(36).substring(2, 9)` — sete caracteres base36.
 *
 * Formato copiado de propósito: os dois fronts escrevem no mesmo campo do
 * mesmo servidor, e ID de formatos diferentes na mesma lista confunde
 * quem opera pelos dois.
 *
 * `existentes` é o que impede repetição. A chance de colisão em 36^7 é
 * remota, mas "remota" não é "nunca" — e um `user_id` repetido faz o
 * remover apagar a linha errada, que é falha silenciosa e destrutiva.
 */
function gerarUserId(existentes = new Set()) {
  for (let tentativa = 0; tentativa < 50; tentativa += 1) {
    const id = Math.random().toString(36).substring(2, 9);
    if (!existentes.has(id)) {
      return id;
    }
  }
  // Saída determinística: 50 colisões seguidas indicam gerador travado,
  // e um sufixo de tempo garante unicidade sem laço infinito.
  return `${Math.random().toString(36).substring(2, 5)}${Date.now().toString(36).slice(-4)}`;
}

/**
 * Um usuário: ID gerado, usuário, senha e status.
 *
 * Mesma ordem e mesmos controles do `UserField` do `adm-param`: o ID
 * vem primeiro e é **somente leitura** — quem o edita à mão quebra a
 * referência que o servidor usa —, e o status é um par de botões, não uma
 * caixa de marcar.
 */
function editorUsuario(valor, prefixo = '') {
  const dados =
    valor && typeof valor === 'object' && !Array.isArray(valor) ? valor : {};

  // Cartão de largura contida, não um formulário que se estica. Um único
  // usuário tem três campos curtos; espalhá-los pela largura toda faz a
  // linha de leitura ficar enorme para um conteúdo pequeno.
  const raiz = elemento('div', 'cartao-usuario');

  // Gerado na montagem quando ausente, e não ao salvar: assim ele aparece
  // na tela, e quem precisa citá-lo em outro lugar já pode copiar.
  const identificador = dados.user_id || gerarUserId();

  // O identificador é etiqueta, não campo: é gerado, não se edita, e um
  // `<input>` de largura cheia dava a ele mais peso visual que o nome do
  // usuário — que é o que de fato se lê.
  const faixaId = elemento('div', 'cartao-usuario__id');
  faixaId.append(
    elemento('span', 'eyebrow', t('params.user.user_id')),
    elemento('code', 'codigo-inline', identificador)
  );
  faixaId.title = t('params.user.user_id.dica');

  const grade = elemento('div', 'cartao-usuario__campos');

  function campo(chave, tipo = 'text') {
    const bloco = elemento('div', 'field');
    const rotulo = elemento('label', 'field__label', t(`params.user.${chave}`));
    const entrada = elemento('input', 'input');
    entrada.type = tipo;
    entrada.id = `${prefixo}usuario-${chave}`;
    rotulo.htmlFor = entrada.id;
    entrada.value = dados[chave] === undefined ? '' : String(dados[chave]);
    entrada.placeholder = t(`params.user.${chave}`);
    entrada.autocomplete = chave === 'password' ? 'new-password' : 'off';
    bloco.append(rotulo, entrada);
    grade.append(bloco);
    return entrada;
  }

  const usuario = campo('user');
  const senha = campo('password', 'password');

  const bloco = elemento('div', 'field');
  bloco.append(elemento('span', 'field__label', t('params.user.status')));
  let ativo = dados.status !== false;
  bloco.append(
    parDeBotoes(ativo, (novo) => {
      ativo = novo;
    })
  );
  grade.append(bloco);

  raiz.append(faixaId, grade);
  return {
    elemento: raiz,
    ler: () => ({
      user: usuario.value,
      password: senha.value,
      user_id: identificador,
      status: ativo,
    }),
  };
}

/** Ativo/Inativo como par de botões, igual ao `BooleanSelectField`. */
function parDeBotoes(inicial, aoMudar) {
  const grupo = elemento('div', 'segmentado');
  grupo.setAttribute('role', 'radiogroup');
  grupo.setAttribute('aria-label', t('params.user.status'));

  let atual = inicial !== false;
  const opcoes = [true, false].map((opcao) => {
    const botao = elemento('button', 'segmentado__opcao');
    botao.type = 'button';
    botao.setAttribute('role', 'radio');
    botao.append(
      icone(opcao ? 'check' : 'fechar'),
      elemento(
        'span',
        null,
        t(opcao ? 'params.user.ativo' : 'params.user.inativo')
      )
    );
    botao.addEventListener('click', () => {
      atual = opcao;
      pintar();
      aoMudar(atual);
    });
    grupo.append(botao);
    return { botao, opcao };
  });

  function pintar() {
    opcoes.forEach(({ botao, opcao }) => {
      const marcado = atual === opcao;
      botao.setAttribute('aria-checked', String(marcado));
      botao.classList.toggle('segmentado__opcao--ativo', marcado);
      botao.classList.toggle('segmentado__opcao--verdadeiro', marcado && opcao);
      botao.classList.toggle('segmentado__opcao--falso', marcado && !opcao);
      botao.tabIndex = marcado ? 0 : -1;
    });
  }

  pintar();
  return grupo;
}

/**
 * Interruptor de status. Dois estados, com o desenho dizendo qual.
 *
 * Substitui a caixa de marcar por um `role="switch"`: numa tabela de
 * usuários, a caixa desmarcada some entre as bordas dos campos e não se
 * distingue de "não preenchido". O texto ao lado muda junto, porque cor
 * e posição sozinhas não bastam.
 */
function interruptor(ligado, aoMudar, rotulo) {
  const raiz = elemento('div', 'interruptor');

  const botao = elemento('button', 'interruptor__trilho');
  botao.type = 'button';
  botao.setAttribute('role', 'switch');
  botao.append(elemento('span', 'interruptor__bolinha'));

  const texto = elemento('span', 'interruptor__texto');

  let estado = ligado !== false;

  function pintar() {
    botao.setAttribute('aria-checked', String(estado));
    botao.classList.toggle('interruptor__trilho--ligado', estado);
    texto.textContent = t(estado ? 'params.user.ativo' : 'params.user.inativo');
    const descricao = `${rotulo}: ${texto.textContent}`;
    botao.setAttribute('aria-label', descricao);
    botao.title = descricao;
  }

  botao.addEventListener('click', () => {
    estado = !estado;
    pintar();
    aoMudar(estado);
  });

  pintar();
  raiz.append(botao, texto);
  return raiz;
}

/**
 * Vários usuários: tabela editável, paginada.
 *
 * Tabela de verdade, e não linhas soltas: com cabeçalho, quem lê sabe
 * que a segunda coluna é senha sem precisar clicar. A paginação existe
 * porque um `users` com trinta linhas empurrava os botões do formulário
 * para fora da tela.
 */
function editorUsuarios(valor) {
  const raiz = elemento('div', 'composto');
  const area = elemento('div');
  const rodape = elemento('div');
  const registros = Array.isArray(valor) ? valor.map((u) => ({ ...u })) : [];

  // Registro sem `user_id` ganha um agora — dado antigo pode não tê-lo, e
  // sem ID a remoção não teria como identificar a linha certa.
  const usados = new Set(registros.map((r) => r.user_id).filter(Boolean));
  registros.forEach((registro) => {
    if (!registro.user_id) {
      registro.user_id = gerarUserId(usados);
      usados.add(registro.user_id);
    }
  });

  let pagina = 0;
  let tamanho = LIMITE_COMPOSTO;

  function desenhar() {
    area.replaceChildren();
    rodape.replaceChildren();

    if (!registros.length) {
      area.append(elemento('p', 'composto__vazio', t('params.users.vazio')));
      return;
    }

    const recorte = paginar(registros, pagina, tamanho);
    pagina = recorte.pagina;

    const tabela = elemento('table', 'table table--compacta');
    const cabecalho = elemento('thead');
    const linhaCabecalho = elemento('tr');
    [
      'params.user.user_id',
      'params.user.user',
      'params.user.password',
      'params.user.status',
      'params.users.acoes',
    ].forEach((chave) => {
      const celula = elemento('th', null, t(chave));
      celula.scope = 'col';
      linhaCabecalho.append(celula);
    });
    cabecalho.append(linhaCabecalho);

    const corpo = elemento('tbody');
    recorte.itens.forEach((registro) => {
      const indice = registros.indexOf(registro);
      const linha = elemento('tr');

      const usuario = elemento('input', 'input input--celula');
      usuario.value = registro.user || '';
      usuario.placeholder = t('params.user.user');
      usuario.setAttribute('aria-label', t('params.user.user'));
      usuario.addEventListener('input', () => {
        registro.user = usuario.value;
      });

      const senha = elemento('input', 'input input--celula');
      senha.type = 'password';
      senha.value = registro.password || '';
      senha.placeholder = t('params.user.password');
      senha.setAttribute('aria-label', t('params.user.password'));
      senha.addEventListener('input', () => {
        registro.password = senha.value;
      });

      const remover = botaoIcone(
        'lixeira',
        t('params.users.remover', { n: indice + 1 }),
        'btn btn--ghost btn--icone btn--perigo-sutil'
      );
      remover.addEventListener('click', () => {
        registros.splice(indice, 1);
        desenhar();
      });

      const marcaId = elemento('code', 'codigo-inline', registro.user_id);
      marcaId.title = t('params.user.user_id.dica');

      [
        marcaId,
        usuario,
        senha,
        interruptor(
          registro.status,
          (novo) => {
            registro.status = novo;
          },
          registro.user || t('params.user.status')
        ),
        remover,
      ].forEach((conteudo) => {
        const celula = elemento('td');
        celula.append(conteudo);
        linha.append(celula);
      });
      corpo.append(linha);
    });

    tabela.append(cabecalho, corpo);
    const embrulho = elemento('div', 'table-wrap');
    embrulho.append(tabela);
    area.append(embrulho);

    const controle = controlePaginacao(recorte, (nova) => {
      pagina = nova;
      desenhar();
    }, 'params.users.paginacao', {
      tamanho,
      aoTrocarTamanho: (novo) => {
        tamanho = novo;
        pagina = 0;
        desenhar();
      },
    });
    if (controle) {
      rodape.append(controle);
    }
  }

  const adicionar = elemento('button', 'btn btn--ghost com-icone');
  adicionar.type = 'button';
  adicionar.append(
    icone('mais'),
    elemento('span', null, t('params.users.adicionar'))
  );
  adicionar.addEventListener('click', () => {
    const id = gerarUserId(usados);
    usados.add(id);
    registros.unshift({
      user: '',
      password: '',
      user_id: id,
      status: true,
    });
    // O novo entra no topo e a primeira página é onde ele está.
    pagina = 0;
    desenhar();
    const campo = area.querySelector('input');
    if (campo) {
      campo.focus();
    }
  });

  desenhar();
  raiz.append(area, rodape, adicionar);
  return { elemento: raiz, ler: () => registros.map((r) => ({ ...r })) };
}

/* --------------------------------------------------------- expandir --- */

// Tipos cujo valor não cabe na coluna do painel lateral. `pattern` entra
// não pelo tamanho, mas porque uma expressão regular é lida caractere a
// caractere e um campo de 380px força rolagem horizontal no meio dela.
const TIPOS_EXPANSIVEIS = ['user', 'users', 'json', 'pattern'];

export function podeExpandir(tipo) {
  return TIPOS_EXPANSIVEIS.includes(tipo);
}

/**
 * Abre o editor em diálogo largo e resolve com o valor, ou `null` se
 * cancelado.
 *
 * Monta um editor NOVO sobre o valor atual, em vez de mover o do painel
 * para dentro do diálogo. Mover deixaria o painel sem campo enquanto o
 * diálogo estivesse aberto, e devolvê-lo ao fechar é o tipo de troca de
 * nó que quebra o foco.
 */
export function expandirEditor(tipo, valor, contexto = {}) {
  const dialogo = document.getElementById('dialogo-expandido');
  const corpo = document.getElementById('expandido-corpo');
  const gatilho = document.activeElement;

  document.getElementById('expandido-titulo').textContent = t(
    'params.expandir.titulo',
    { tipo }
  );
  const dica = document.getElementById('expandido-dica');
  const textoDica = t(`params.dica.${tipo}`);
  dica.textContent = textoDica === `params.dica.${tipo}` ? '' : textoDica;
  dica.hidden = !dica.textContent;

  const editor = criarEditor(tipo, valor, contexto);
  corpo.replaceChildren(editor.elemento);

  const ok = document.getElementById('btn-expandido-ok');
  const cancelar = document.getElementById('btn-expandido-cancelar');
  const erro = document.createElement('p');
  erro.className = 'field__error';
  erro.setAttribute('role', 'alert');
  corpo.append(erro);

  return new Promise((resolve) => {
    function encerrar(resultado) {
      ok.removeEventListener('click', aoConfirmar);
      cancelar.removeEventListener('click', aoCancelar);
      dialogo.removeEventListener('close', aoCancelar);
      dialogo.close();
      corpo.replaceChildren();
      if (gatilho && gatilho.focus) {
        gatilho.focus();
      }
      resolve(resultado);
    }
    function aoConfirmar() {
      try {
        encerrar({ valor: editor.ler() });
      } catch (excecao) {
        // Fechar com JSON inválido perderia o que foi digitado.
        erro.textContent = excecao.message;
      }
    }
    function aoCancelar() {
      encerrar(null);
    }

    ok.addEventListener('click', aoConfirmar);
    cancelar.addEventListener('click', aoCancelar);
    dialogo.addEventListener('close', aoCancelar);
    dialogo.showModal();
    const primeiro = corpo.querySelector(
      'input, textarea, select, button'
    );
    (primeiro || ok).focus();
    // Focar um textarea põe o cursor no fim e rola até lá — quem abre o
    // editor expandido quer ver o começo do documento, não o fecha-chaves.
    if (primeiro && primeiro.tagName === 'TEXTAREA') {
      primeiro.setSelectionRange(0, 0);
      primeiro.scrollTop = 0;
    }
  });
}

/* ------------------------------------------------------------- despacho */

/**
 * Monta o editor do tipo. Devolve `{ elemento, ler }`.
 *
 * Tipo desconhecido cai no editor de texto: o catálogo vem do servidor e
 * pode ganhar tipos que este cliente ainda não conhece. Recusar-se a
 * exibir seria pior do que exibir como texto — o servidor valida de todo
 * jeito.
 */
export function criarEditor(tipo, valor, contexto = {}) {
  const sensivel = (contexto.sensiveis || TIPOS_SENSIVEIS).includes(tipo);

  switch (tipo) {
    case 'int':
    case 'float':
      return editorNumero(valor, tipo);
    case 'bool':
      return editorBooleano(valor);
    case 'date':
    case 'datetime':
    case 'time':
      return editorDataHora(valor, tipo);
    case 'list':
      return editorLista(valor);
    case 'dict':
      return editorDicionario(valor);
    case 'json':
    case 'pattern':
      return editorCodigo(valor, tipo);
    case 'reference':
      return editorReferencia(valor, contexto);
    case 'user':
      return editorUsuario(valor);
    case 'users':
      return editorUsuarios(valor);
    case 'secret':
    case 'string':
    default:
      return editorTexto(valor, tipo, sensivel);
  }
}
