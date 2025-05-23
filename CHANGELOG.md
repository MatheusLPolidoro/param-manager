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
