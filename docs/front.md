# Front desktop

Aplicativo de desktop para gerenciar parâmetros sem escrever código: aplicações,
parâmetros, o plano de sincronização e o catálogo de tipos. Roda em português e
inglês, com tema claro e escuro.

Ele vem dentro do próprio pacote, como **extra**: quem só lê parâmetros num
servidor não instala nada a mais.

## Instalação

```bash
pip install "param-manager[front]"
```

E para abrir:

```bash
param-manager-front
# ou
python -m param_manager.front
```

Não é preciso Rust nem Node: o extra traz um componente nativo já compilado.

!!! warning "Python 3.11 a 3.13"

    O extra só instala nessas versões. A biblioteca em si funciona do 3.10 em
    diante, mas o front não:

    - **No 3.10**, uma dependência do front só corrige suas vulnerabilidades
      conhecidas em versões que exigem 3.11.
    - **A partir do 3.14**, o componente nativo ainda não publica pacote.

    Nessas versões, `pip install "param-manager[front]"` instala só a
    biblioteca, sem erro, e o comando `param-manager-front` não abre.

### Runtime de webview

A janela usa o navegador embutido do sistema operacional:

| Sistema | O que instalar |
|---|---|
| Windows | [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (Evergreen Bootstrapper) |
| Linux | `libwebkit2gtk-4.1-0`, `libgtk-3-0`, `libappindicator3-1` |
| macOS | nada, já vem no sistema |

## Como usar

A primeira tela é **Sessão**. Preencha o nome da instância e o modo, conecte, e
o resto da interface passa a operar sobre aquela sessão.

- **Modo local** grava no arquivo local do [modo local](modo_local.md), sem
  rede. É o modo de desenvolver sem servidor. Os tipos `secret`, `user` e
  `users` são recusados aqui, porque a cifragem acontece no servidor.
- **Modo remoto** fala com a API e exige a URL.

O caminho do arquivo local e as credenciais vêm das mesmas variáveis de
ambiente e do mesmo `.env` da biblioteca — ver [Configuração](configuracao.md).
O front guarda só as próprias preferências (tema, idioma, última instância) em
`front-prefs.json`, no diretório de configuração do sistema.

Trocar de modo exige uma **instância nova**: uma sessão já aberta não é
reconfigurada.

!!! note "Uma chave de custódia por processo"

    A chave que decifra os parâmetros protegidos é lida de uma variável de
    ambiente **global**. Um processo usa exatamente uma chave, então aplicações
    com chaves diferentes precisam ser abertas em processos diferentes.
