# Contribuindo

## Preparando o ambiente

```bash
git clone <url-do-repositorio>
cd param-manager
python -m venv .venv
```

Ative a venv e instale as dependências de desenvolvimento:

```bash
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate

pip install -r requirements-dev.txt
```

!!! warning "A venv precisa estar no PATH"
    As tarefas do `taskipy` disparam subprocessos e não herdam a venv
    sozinhas. Sem `.venv/Scripts` no PATH, `task lint` falha dizendo que
    não encontrou o `ruff` — o que parece erro da receita e não é.

## Rodando os testes

```bash
task test              # tudo, com cobertura
task test_unit         # só os unitários
task test_integracao   # só os que usam arquivo real em disco
```

Os testes de integração desta biblioteca **não precisam de servidor nem
de banco**: eles exercitam arquivos TinyDB reais. Existem porque os
mocks mentem — o `MagicMock` devolve o mesmo objeto em toda chamada, um
comportamento que o banco real não tem e que já escondeu um defeito de
persistência aqui.

!!! note "`task test` reescreve o código antes de rodar"
    O passo anterior aos testes é `task fix`, que aplica as correções
    automáticas do `ruff`. Revise o diff resultante antes de commitar.

## Estilo

```bash
task lint     # confere
task format   # formata
task fix      # corrige o que dá para corrigir sozinho
```

O `ruff` roda com 79 colunas e aspas simples. **Instale-o no pin do
projeto** (`ruff==0.11.7`): versões mais novas trazem regras em
`preview` que acusam violações que o código não tem.

Identificadores em inglês; docstrings, comentários, mensagens de log e
de erro **em português**.

## Registrando a mudança no changelog

Toda alteração visível para quem usa a biblioteca precisa de um
fragmento em `chanlogs.d/`, com o tipo no nome do arquivo:

```
chanlogs.d/+nome-curto.fix.md
```

Tipos disponíveis: `breaking`, `feature`, `enhancement`, `fix`,
`deprecation`, `security`, `docs`, `tests`, `infra`, `chore`.

Escreva o **efeito observável para quem usa**, não o mecanismo interno:

> Corrigida uma falha em que a leitura de um parâmetro podia lançar um
> erro em vez de devolver o valor.

e não:

> Corrigido check-then-act entre `_is_param_cache_valid` e o acesso a
> `_param_cache`.

!!! warning "Não edite o `CHANGELOG.md`"
    Ele é gerado pelo `towncrier` a partir dos fragmentos. Escrever nele
    à mão faz o conteúdo ser sobrescrito na próxima geração.

## Documentação

```bash
mkdocs serve                 # pré-visualiza
mkdocs build --strict        # é o que vale como verificação
```

O `--strict` transforma aviso em erro, então link quebrado e página fora
do `nav` reprovam. Ainda assim, **abra a página no navegador antes de
dar por pronto**: já aconteceu de o build passar e o conteúdo sair como
texto cru por falta de uma extensão do Markdown.

A página `estrutura.md` é **gerada no build** por `docs/gen_tree.py`.
Vazia no repositório é o estado correto; o que for escrito ali é
descartado.
