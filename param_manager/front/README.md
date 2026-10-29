# Front desktop do param-manager

Aplicativo de desktop para gerenciar parâmetros: aplicações, parâmetros, o plano de
sincronização e o catálogo de tipos. Roda em PyTauri, em português e inglês, com tema
claro e escuro.

## Instalação

```bash
pip install "param-manager[front]"
param-manager-front          # ou: python -m param_manager.front
```

O extra traz `pytauri-wheel`, que é um wheel nativo — **não é preciso Rust nem Node**.
O extra funciona do **Python 3.11 ao 3.13**. O `pytauri-wheel` publica wheels por minor
de CPython e não é `abi3`, então a partir do 3.14 o extra simplesmente não resolve, em
vez de o pip tentar compilar do sdist. No 3.10 ele também não resolve: o `pillow`, que
vem junto, só corrige suas vulnerabilidades conhecidas em versões que exigem 3.11.

Runtime de webview exigido pelo sistema operacional:

| | |
|---|---|
| Windows | [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (Evergreen Bootstrapper) |
| Linux | `libwebkit2gtk-4.1-0`, `libgtk-3-0`, `libappindicator3-1` |
| macOS | nada, já vem no sistema |

## Como usar

A primeira tela é **Sessão**. Preencha o nome da instância e o modo, conecte, e o resto
da interface passa a operar sobre aquela sessão.

- **Modo local** grava no arquivo *sidecar*, sem rede. É o modo de desenvolver sem
  servidor. Tipos sensíveis (`secret`, `user`, `users`) são recusados aqui: a cifragem
  acontece no servidor.
- **Modo remoto** fala com a API e exige a URL.

O caminho do sidecar e as credenciais continuam vindo de variável de ambiente e do `.env`
da biblioteca — o front não os reinventa. Só o que é dele (tema, idioma, última instância)
fica em `front-prefs.json`, no diretório de configuração do sistema.

Trocar de modo exige uma **instância nova**: uma sessão já construída não é reconfigurada,
e essa guarda é da biblioteca.

Uma advertência que a tela repete e vale repetir aqui: a chave de custódia é lida de
variável de ambiente **global**, então um processo segura exatamente uma chave.
Aplicações com chaves diferentes precisam de processos diferentes.

## Arquitetura

```
front/
├── handlers.py   → funções puras sobre param_manager.api. NÃO importa pytauri
├── bridge.py     → Commands() + registro. A ÚNICA que importa pytauri
├── launcher.py   → resolve caminhos, monta o builder, sobe o portal
├── session.py    → preferências do front (tema, idioma, última instância)
└── assets/       → HTML, CSS e ES modules. Sem build, sem bundler
```

Duas regras de import sustentam isso, e `tests/test_front_desacoplamento.py` reprova quem
as quebrar:

1. **A única porta para a biblioteca é `param_manager.api`.** É o que permite reescrever
   ou descartar o front sem encostar em `manager.py`.
2. **`pytauri` só em `bridge.py` e `launcher.py`.** `pytauri_wheel` liga contra
   WebView2/gtk e nem importa numa imagem `python:3-slim` — com os handlers livres dele, a
   suíte inteira roda no CI sem instalar o extra.

## Desenvolvimento

Os assets são lidos do disco a cada subida: editar CSS ou JS e reabrir a janela basta.

```bash
# aponta o frontendDist para um servidor de desenvolvimento
PARAM_MANAGER_FRONT_DEV=http://localhost:1420 param-manager-front
```

Abrir com `?dev=1` na URL roda as checagens de acessibilidade e imprime o resultado no
console da webview. Elas cobrem controle sem nome acessível, campo sem rótulo, `id`
duplicado e afins. Para usar o axe-core completo, coloque o bundle em
`assets/js/vendor/axe.min.js` — ele é carregado se existir e ignorado se não.

### Duas armadilhas já pagas

**Não declare `app.security.csp` no `tauri.conf.json`.** O `pytauri-wheel` serve os assets
por um leitor de disco cujo `csp_hashes` é `unimplemented!()`, e o Tauri só o chama quando
há CSP configurada. O resultado é um panic de Rust com backtrace de `PyInit_ext_mod`, sem
nada que aponte para o arquivo de configuração. `test_front_assets_empacotados.py` barra a
reintrodução.

**O `package-data` do `pyproject.toml` é o que põe os assets no wheel.** Sem ele o build
fica verde e a janela abre sem interface na máquina de quem instalou. O piso do setuptools
é 62.3 por causa disso: o glob `**` não funciona antes dessa versão.

**Wheel velho em `dist/` mente sobre o código.** Os testes conferem a árvore de fontes, não
o artefato — então uma correção nos assets fica invisível para quem instalou o wheel
anterior, e o sintoma é o defeito já corrigido reaparecendo. Como a versão não muda entre
builds de desenvolvimento, o pip também não reinstala sozinho. Limpe antes de construir e
force na hora de instalar:

```powershell
Remove-Item -Recurse -Force build, dist, param_manager.egg-info -ErrorAction SilentlyContinue
python -m build --wheel
pip install --force-reinstall --no-deps dist\param_manager-0.6.0-py3-none-any.whl
```
