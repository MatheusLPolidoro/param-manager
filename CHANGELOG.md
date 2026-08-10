Versão 0.5.0 (2026-08-10)

### :warning: MUDANÇAS QUEBRADAS

- Eleve a versão mínima de Python para 3.10. A correção da vulnerabilidade PYSEC-2026-2270 está em uma versão do `python-dotenv` publicada apenas para 3.10 ou superior; as versões alcançáveis em 3.8 e 3.9 continuam expostas, e mantê-las significaria distribuir a falha.

### :zap: NOVAS FUNCIONALIDADES

- Agora é possível desenvolver sem subir o servidor. Passando
  `mode='local'` — ou definindo `PARAM_MANAGER_MODE=local` — as mesmas
  funções de sempre (`create_app`, `upsert_params`, `delete_param`,
  `delete_app`, `get_param`, `get_all_params`) passam a trabalhar num
  arquivo local, sem nenhuma chamada de rede. O padrão continua sendo o
  servidor, então quem não pedir nada não percebe diferença.

  Parâmetros dos tipos `secret`, `user` e `users` não podem ser criados
  nesse modo: a cifragem acontece no servidor, e gravá-los localmente
  significaria guardar o valor em claro. A tentativa falha com uma
  mensagem explicando isso.

  Também foi acrescentada a função `list_apps()`, que lista as aplicações
  nos dois modos.
- Base para o modo de desenvolvimento local: a biblioteca passou a manter
  um arquivo próprio, ao lado do cache, para guardar parâmetros criados sem
  o servidor. Ele é separado de propósito — a limpeza automática do cache,
  que acontece quando a API responde algo ilegível, não alcança o que você
  ainda não sincronizou. Ainda sem efeito visível: nenhuma função pública
  usa esse arquivo nesta versão.
- No modo local, a biblioteca passou a avisar quando um valor provavelmente
  será recusado pelo servidor — comprimento acima do limite, número fora
  da faixa ou tipo desconhecido. O aviso não impede a gravação: quem
  valida de verdade continua sendo o servidor, na sincronização. Serve
  para o erro aparecer na hora, e não no fim de uma sessão inteira de
  trabalho offline.

  A nova função `refresh_type_catalog()` busca no servidor a lista de tipos
  aceitos e os limites padrão, guardando-a para uso offline. Sem ela, vale
  uma cópia embarcada, que pode ficar desatualizada.
- Novo módulo `param_manager.api`, pensado para aplicações com interface
  gráfica. Ele expõe as mesmas operações em funções que sempre devolvem um
  dicionário simples com `ok` indicando sucesso ou falha, em vez de lançar
  exceções — o que evita que um erro atravesse a ponte entre a interface e
  o Python como um rastreamento de pilha.

  Os dados devolvidos são cópias independentes, então alterá-los na
  interface não afeta o estado interno da biblioteca.

  As funções são bloqueantes: chame-as fora do laço de eventos da
  interface, sob pena de a janela travar durante uma requisição ou a
  leitura de um parâmetro protegido.
- Os parâmetros criados no modo local agora podem ser enviados ao servidor.
  A sincronização acontece em duas etapas: `sync_plan()` mostra o que seria
  feito — o que será criado, o que será atualizado e o que está em conflito
  — sem tocar em nada; `sync_apply()` executa apenas o que foi apresentado
  no plano.

  Conflito nunca é resolvido sozinho. Quando o mesmo parâmetro mudou dos
  dois lados, ele fica de fora e é apresentado com os dois valores, para
  que a decisão seja de quem está operando.

  Um parâmetro recusado pelo servidor permanece guardado localmente, com a
  mensagem exata que o servidor devolveu, e os demais continuam sendo
  enviados normalmente. Falta de permissão é tratada de forma distinta de
  valor inválido: o parâmetro segue pendente e volta a ser tentado quando a
  credencial for corrigida.

### :rocket: OTIMIZAÇÕES

- A exceção de parâmetro não encontrado passou a se chamar
  `ParamNotFoundError`, acompanhando o restante da biblioteca, que agora
  usa nomes em inglês. **Nada precisa ser alterado em código já escrito**:
  `ParamNaoEncontradoError` continua exportado e é a mesma classe, então
  um `except` existente segue capturando normalmente.
- Inclua `api_error_cooldown` (e as variáveis `{INSTANCIA}_API_ERROR_COOLDOWN` / `API_ERROR_COOLDOWN`) para configurar por quanto tempo a biblioteca evita novas tentativas após uma falha da API. Sem configuração, o valor continua sendo o mesmo da duração do cache. Valores inválidos ou vazios são ignorados com aviso, caindo na duração do cache.
- Omita `user_editable` do payload quando o chamador não informa o campo, permitindo ao servidor distinguir "não enviado" de "enviado como falso" e liberar a edição de parâmetros marcados como editáveis por usuário comum.

### :bug: CORREÇÕES

- Aplique o tempo limite configurado também nas requisições de autenticação e serialize a renovação de token, evitando travar a aplicação chamadora e disparar renovações concorrentes.
- Ative o intervalo de espera também quando a API responde com erro HTTP, evitando novas tentativas a cada chamada contra um servidor indisponível.
- Buscar um parâmetro ou aplicação inexistentes (404) deixa de ativar o circuit breaker, permitindo novas tentativas sem entrar em modo offline. Apenas erros de indisponibilidade real (5xx, timeout, conexão) ativam o mecanismo de fallback.
- Corrigida uma falha rara em que `get_param` podia lançar `KeyError` na
  aplicação que a consome, em vez de devolver o valor ou `None`. Acontecia
  quando outra thread apagava ou regravava o mesmo parâmetro no exato
  instante da leitura — algo que `delete_param` e `upsert_params` fazem
  internamente. A leitura do cache passou a ser feita de uma vez só, sem
  essa brecha.
- Corrija `from param_manager import *`, que falhava por listar em `__all__` um símbolo não exportado.
- Corrija a corrupção do cache local sob uso concorrente. Em uma aplicação com várias threads, a limpeza de uma tabela simultânea a uma gravação podia truncar o arquivo do cache e derrubar o conteúdo de todos os aplicativos — justamente durante a indisponibilidade da API, que é quando esse cache é a única fonte de dados restante.
- Corrija o registro da instância quando `instance_name` é informado de forma posicional: antes, o gerenciador era configurado com o nome correto mas registrado sob o nome padrão, fazendo duas instâncias lógicas compartilharem o mesmo espaço.
- Corrija o uso de um token de acesso já vencido, que sob concorrência podia ser tratado como válido por até 29 minutos e fazer toda requisição falhar com 401. Threads que chegam juntas com o token vencido passam a renovar uma vez só, em vez de uma renovação por thread: como o refresh token é de uso único na configuração padrão do Keycloak, a segunda renovação invalidava a sessão que a primeira acabara de abrir.
- Elimina race conditions no acesso ao cache em memória: iterações seguras durante modificação concorrente, atualização atômica (CAS) do cache e do circuit breaker, e impossibilidade de resposta atrasada sobrescrever dado mais recente.
- Execute a inicialização da instância sob o lock do multiton, evitando que duas threads inicializem a mesma instância e substituam o lock interno, os caches e o arquivo do TinyDB.
- Limpe também o cache em memória do parâmetro ao apagá-lo por `delete_param`: o valor excluído — possivelmente uma credencial revogada — continuava sendo devolvido por `get_param` até o fim da janela de cache.
- Limpe também o cache em memória do parâmetro ao atualizá-lo por `upsert_params`: o valor anterior continuava sendo devolvido por `get_param` até o fim da janela de cache.
- Remova do banco local o parâmetro apagado por `delete_param`, impedindo que um valor excluído — possivelmente uma credencial revogada — continue sendo servido pelo modo offline.
- Restrinja a limpeza do banco local ao app envolvido: um erro de leitura da API ou do próprio arquivo passa a descartar apenas a tabela daquele app, em vez de apagar o cache offline de todas as aplicações.
- Serialize a renovação de token disparada por respostas 401, evitando que chamadas concorrentes usem o mesmo refresh token e invalidem a sessão umas das outras.
- Um parâmetro cujo valor gravado localmente era nulo não era removido do banco local quando solicitado, causando ressurreição inadvertida na recuperação offline.
- Uma falha ao criar o gerenciador deixa de contaminar as tentativas seguintes. Antes, um erro durante a inicialização — diretório sem permissão de escrita, cache local corrompido — guardava internamente um objeto pela metade, e toda chamada posterior recebia esse mesmo objeto quebrado até o processo ser reiniciado. O cache local que já tenha sido aberto também é fechado, para que a falha não deixe o arquivo travado no Windows.
- Valores inválidos ou vazios de `CACHE_DURATION` e `TIMEOUT` passam a ser ignorados com aviso, em vez de impedir a criação do gerenciador. Antes o erro subia durante a construção e deixava no lugar uma instância inutilizável, cujo uso seguinte falhava com uma mensagem sem relação com a causa. Um `CACHE_DURATION` negativo continua desligando o cache, como já acontecia.

### :shield: SEGURANÇA

- Envie o cabeçalho `Authorization` também nas leituras de parâmetros quando houver credencial configurada, mantendo a leitura anônima funcional quando não houver.
- Impeça que valores de parâmetros `secret`, `user` e `users` sejam gravados em claro no banco local: a decifragem passa a operar sobre cópia e o cache guarda apenas o envelope cifrado.
- Inclua a variável `PARAM_MANAGER_PURGE_PLAINTEXT_CACHE` (desligada por padrão) para remover do banco local valores sensíveis gravados em claro por versões anteriores.
- Inclua o parâmetro `verify_ssl` para controlar a verificação de certificado TLS nas leituras, com precedência construtor > `{INSTANCIA}_VERIFY_SSL` > `VERIFY_SSL`. O padrão continua desligado, por conta dos ambientes com certificado interno.

### :open_file_folder: DOCUMENTAÇÃO

- A documentação passou a cobrir o modo local: como ligá-lo, o que muda no
  armazenamento, por que parâmetros protegidos não podem ser criados
  offline, como funciona o envio em duas etapas para o servidor e como
  conflitos são apresentados para você decidir.

  Corrigidos também três pontos do tutorial que descreviam funções e
  nomes que não existem — `update_param`, `get_param_schema`, as variáveis
  de ambiente de credencial e o caminho do arquivo de fallback —, e a
  página de contribuição, que estava em branco.

  Blocos de código voltaram a ser exibidos como código nas páginas. Antes
  apareciam como texto corrido, com as crases à mostra.
- Esclareça na documentação interna que `verify_ssl` governa apenas as leituras, e que a cópia devolvida na decifragem é garantida somente para parâmetros sensíveis.
- O README agora traz um fluxograma do cliente, mostrando como um `get_param` é resolvido entre cache, cooldown de erro, chamada à API e o fallback local.

### :test_tube: TESTES

- A biblioteca ganhou uma verificação que confronta o esquema publicado
  pelo servidor com as rotas, os códigos de sucesso e os campos que ela de
  fato consome — de modo que uma mudança incompatível do lado do servidor
  apareça como falha de teste, e não como erro em produção. A verificação
  se pula sozinha quando não há esquema disponível.
- A garantia de que a biblioteca não pode entrar em deadlock deixou de
  depender de revisão e passou a ser verificada automaticamente a cada
  build, em duas frentes: a execução real dos métodos públicos, inclusive
  sob concorrência, e uma varredura do código que reprova qualquer
  gravação de cache feita por fora do caminho seguro.

### :classical_building: INFRAESTRUTURA

- A auditoria de vulnerabilidades passa a rodar na versão mínima de Python suportada, e não na mais recente: é ali que as dependências resolvem para as versões mais antigas, onde as falhas conhecidas estão.
- Inclua pipeline de integração contínua com varredura de segredos no histórico, auditoria de vulnerabilidades das dependências, verificação de estilo e testes automatizados em Python 3.8, 3.11 e 3.13, além de uma suíte de integração que exercita o banco local real em vez de um substituto em memória.
- Regrave `requirements-dev.txt` em UTF-8 e preserve a lista padrão de exclusões do ruff, que era substituída pela configuração do projeto.

### :broom: LIMPEZA

- Elimine uma gravação redundante no banco local durante `delete_param`, que repetia o ciclo de leitura e escrita sem alterar o resultado.


Versão 0.4.2 (2026-07-29)

### :bug: CORREÇÕES

- Adicione mais uma tentativa em upsert\_params apos renovar o token.

### :classical_building: INFRAESTRUTURA

- Altere a versão do python-dotenv para atual que não tem alerta no pip-audit.


Versão 0.4.1 (2026-03-26)

### :bug: CORREÇÕES

- Remova propagação de cache em chamada de parâmetro especifico para todos os parâmetros da aplicação.


Versão 0.4.0 (2026-03-26)

### :zap: NOVAS FUNCIONALIDADES

- Aprimore a gestão de variáveis de ambiente: Implemente prioridade para variáveis de ambiente prefixadas com o nome da instância (ex: PLUGIN_API_URL), permitindo configurações granulares sem afetar o escopo global.
- Garanta a segurança entre threads (Thread-Safety): Implemente um lock de classe no método __new__ para evitar condições de corrida na criação de instâncias nomeadas.
- Isole o armazenamento do TinyDB: Configure cada instância para utilizar seu próprio arquivo JSON (ex: params_default.json) em subdiretórios distintos, eliminando conflitos de escrita e travas de arquivo.
- Otimize a recuperação de falhas: Refine os mecanismos de cooldown e fallback local para que falhas de conexão em uma instância não bloqueiem as requisições das demais.
- Persista o contexto no objeto: Armazene o instance_name dentro de cada instância para que logs, erros e metadados reflitam exatamente qual gerenciador está operando.
- Personalize o Logging por instância: Atualize todas as mensagens de logger para incluir o nome da instância ativa, facilitando o rastreamento em ambientes complexos.
- Preserve a compatibilidade do Singleton: Mantenha o funcionamento padrão para chamadas sem argumentos, direcionando-as automaticamente para a instância "default".
- Refatore a estrutura de instâncias para o padrão Multiton: Substitua o atributo único __instance por um dicionário _instances para permitir múltiplos gerenciadores (ex: "default", "plugin_x") no mesmo processo.
- Refatore a limpeza de cache: Ajuste o método clear_cache para que a purga de dados seja restrita à instância atual, sem interferir no cache de outros gerenciadores.

Versão 0.3.8 (2026-01-02)

### :bug: CORREÇÕES

- Inclua validação de banco truncado e correção de limpeza.


Versão 0.3.7 (2025-12-31)

### :bug: CORREÇÕES

- Ajuste _fetch_from_api para limpar db local caso necessário.


Versão 0.3.6 (2025-12-31)

### :bug: CORREÇÕES

- Inclua ajuste para caso corrompido db local ele faça a limpeza e nova chamada para api de parâmetros em _get_from_local_db.


Versão 0.3.3 (2025-12-17)

### :bug: CORREÇÕES

- Corrija utilização de parâmetro save\_cache em \_fetch\_param\_from\_api.


Versão 0.3.1 (2025-12-16)

### :bug: CORREÇÕES
- Inclua parâmetro save_cache para definir se ira ou não salvar do .db local.


Versão 0.3.0 (2025-12-12)

### :zap: NOVAS FUNCIONALIDADES

- Inclua métodos para criação/deleção e atualização de aplicações e parâmetros.

### :open_file_folder: DOCUMENTAÇÃO

- Inclua informações sobre novos parâmetros de criação, atualização e remoção de aplicativos e parâmetros.

### :test_tube: TESTES

- Inclusa novos testes para novos métodos de criação, deleção e atualização de aplicações e parâmetros.


Versão 0.2.6 (2025-12-01)

### :zap: NOVAS FUNCIONALIDADES

- Inclua descriptografia para type user e users.


Versão 0.2.5 (2025-11-28)

### :zap: NOVAS FUNCIONALIDADES

- Inclua compatibilidade com atualização de API de parâmetros.

### :bug: CORREÇÕES

- Corrija descriptografia para aceitar versão antiga e versão nova.


Versão 0.2.2 (2025-07-10)

### :bug: CORREÇÕES

- Corrigido local_path_db e .env para geração de executaveis com o pyinstaller.


Versão 0.2.1 (2025-07-10)

### :bug: CORREÇÕES

- Adicionado dependências no pyproject.toml.


Versão 0.2.0 (2025-07-09)

### :zap: NOVAS FUNCIONALIDADES

- Adicionado tipo "secret" com descriptografia de dados salvos na API com base no arquivo de variaveis de ambiente ".env".


Versão 0.1.7 (2025-07-03)

### :bug: CORREÇÕES

- adicionado suporte a multi-threads.


Versão 0.1.6 (2025-06-19)

### :bug: CORREÇÕES

- Correção de utilização de cache caso a API esteja fora do ar.


Versão 0.1.5 (2025-06-05)

### :bug: CORREÇÕES

- Corrigido leitura de parâmetros unitários ao realizar consulta pelo método get_param.


Versão 0.1.4 (2025-06-01)

### :bug: CORREÇÕES

- Correção de salvamento de arquivo db local com opção de passar o path.


Versão 0.1.3 (2025-05-30)

### :bug: CORREÇÕES

- Correção de url na requisição de todos os parametros e alteração de salvamento de db local para pasta da biblioteca.


Versão 0.1.2 (2025-05-27)

### :bug: CORREÇÕES

- Corrigido salvamente em DB local para chamada de parametro unitario.


Versão 0.1.0 (2025-05-23)

### :zap: NOVAS FUNCIONALIDADES

- Adicionado sistema de cache global para parâmetros de aplicações, reduzindo chamadas à API e melhorando performance.
- Adicionado sistema de fallback para TinyDB, permitindo acesso a parâmetros mesmo quando a API está indisponível.
- Adicionados métodos para limpeza de cache (global, por aplicação e por parâmetro específico), permitindo controle granular sobre dados em cache.
- Implementada integração com API de parâmetros, permitindo recuperação de dados de configuração de forma centralizada.
- Implementado cache específico por parâmetro individual, permitindo consultas mais eficientes para parâmetros frequentemente acessados.
- Implementado padrão Singleton para garantir uma única instância do gerenciador de parâmetros, evitando múltiplas conexões e caches redundantes.

### :rocket: OTIMIZAÇÕES

- Adicionado sistema de logging integrado para rastreamento de operações e diagnóstico de problemas.
- Implementada configuração flexível para URL da API, duração de cache e timeout, permitindo personalização conforme necessidades específicas.
- Implementado método get_cache_info() para inspeção do estado atual do cache, facilitando diagnóstico e depuração.
