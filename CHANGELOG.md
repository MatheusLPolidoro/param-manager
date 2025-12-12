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
