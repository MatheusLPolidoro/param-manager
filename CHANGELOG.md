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
