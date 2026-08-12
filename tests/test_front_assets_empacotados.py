"""
O wheel precisa sair com a interface dentro.

Assets são arquivos comuns, não módulos: setuptools só os inclui se
`package-data` os listar. O defeito de esquecer um padrão é dos piores —
o build fica verde, o wheel instala, e a janela abre sem CSS na máquina de
quem instalou.

Também confere que todo caminho referenciado pelo `index.html` e pelos
imports de ES module existe: um `href` errado é 404 silencioso dentro da
webview.

FIX-PM-22
"""

import re
from fnmatch import fnmatch
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FRONT = RAIZ / 'param_manager' / 'front'
ASSETS = FRONT / 'assets'


def padroes_declarados():
    """Lê os globs de `package-data` sem depender de um parser de TOML."""
    texto = (RAIZ / 'pyproject.toml').read_text(encoding='utf-8')
    bloco = re.search(
        r'\[tool\.setuptools\.package-data\](.*?)(\n\[|\Z)',
        texto,
        re.DOTALL,
    )
    assert bloco, 'pyproject.toml não declara [tool.setuptools.package-data]'
    return re.findall(r'"([^"]+)"', bloco.group(1))


def coberto(relativo, padroes):
    for padrao in padroes:
        if fnmatch(relativo, padrao):
            return True
        # `assets/**/*` precisa casar com `assets/css/base.css`; fnmatch
        # trata `*` como qualquer coisa, inclusive `/`, então o teste
        # normaliza o padrão em vez de reimplementar o glob do setuptools.
        if fnmatch(relativo, padrao.replace('**/', '')):
            return True
    return False


def test_todo_arquivo_nao_python_do_front_esta_declarado():
    padroes = padroes_declarados()
    faltando = []

    for caminho in FRONT.rglob('*'):
        if caminho.is_dir() or caminho.suffix == '.py':
            continue
        if '__pycache__' in caminho.parts:
            continue
        relativo = caminho.relative_to(FRONT).as_posix()
        if not coberto(relativo, padroes):
            faltando.append(relativo)

    assert not faltando, (
        f'fora do package-data e portanto fora do wheel: {faltando}'
    )


def test_a_configuracao_do_tauri_esta_declarada():
    padroes = padroes_declarados()

    assert coberto('tauri.conf.json', padroes)
    assert coberto('capabilities/default.toml', padroes)


def test_o_html_referencia_apenas_arquivos_existentes():
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    referencias = re.findall(r'(?:href|src)="([^"#:]+)"', html)
    ausentes = [
        referencia
        for referencia in referencias
        if not (ASSETS / referencia).exists()
    ]

    assert not ausentes, f'referências quebradas no index.html: {ausentes}'


def test_os_imports_de_modulo_resolvem():
    """
    Import relativo errado não falha no build: falha na webview, mudo.

    `vendor/axe.min.js` é a exceção declarada — é carregado dentro de um
    `try` justamente por ser opcional.
    """
    quebrados = []
    for arquivo in (ASSETS / 'js').rglob('*.js'):
        fonte = arquivo.read_text(encoding='utf-8')
        alvos = re.findall(r"from '([^']+)'", fonte)
        alvos += re.findall(r"import\('([^']+)'\)", fonte)
        for alvo in alvos:
            if 'vendor/axe' in alvo:
                continue
            if not (arquivo.parent / alvo).resolve().exists():
                quebrados.append(f'{arquivo.name} → {alvo}')

    assert not quebrados, f'imports que não resolvem: {quebrados}'


def test_o_frontend_dist_aponta_para_a_pasta_de_assets():
    """
    `frontendDist` e o diretório real precisam concordar.

    Se divergirem, o Tauri serve uma pasta vazia e a janela abre em
    branco — sem erro em lugar nenhum.
    """
    config = (FRONT / 'tauri.conf.json').read_text(encoding='utf-8')
    destino = re.search(r'"frontendDist"\s*:\s*"([^"]+)"', config)

    assert destino, 'tauri.conf.json não declara frontendDist'
    assert (FRONT / destino.group(1)).is_dir()
    assert (FRONT / destino.group(1) / 'index.html').exists()


def test_a_config_nao_declara_csp():
    """
    Declarar `app.security.csp` derruba o app — e de um jeito ilegível.

    O `pytauri-wheel` serve os assets por um `Assets` que lê do disco, e
    o `csp_hashes` desse leitor é `unimplemented!()`
    (`python/pytauri-wheel/src/lib.rs:58`). O Tauri só o chama quando há
    CSP configurada, então uma CSP transforma a subida num panic de Rust
    com backtrace de `PyInit_ext_mod` — nada nele aponta para o
    `tauri.conf.json`.

    Isto já aconteceu uma vez, na primeira subida deste app. O teste
    existe para não acontecer de novo.
    """
    config = (FRONT / 'tauri.conf.json').read_text(encoding='utf-8')

    assert '"csp"' not in config, (
        'CSP configurada: o pytauri-wheel não implementa csp_hashes e o '
        'app entra em panic ao abrir a janela.'
    )


def test_a_capability_cobre_a_janela_declarada():
    """
    A janela do `tauri.conf.json` precisa estar na lista da capability.

    Rótulo fora da lista significa janela sem permissão de IPC: ela abre,
    e todo `pyInvoke` falha.
    """
    config = (FRONT / 'tauri.conf.json').read_text(encoding='utf-8')
    capability = (FRONT / 'capabilities' / 'default.toml').read_text(
        encoding='utf-8'
    )

    rotulo = re.search(r'"label"\s*:\s*"([^"]+)"', config)
    assert rotulo, 'tauri.conf.json não declara o label da janela'
    assert f'"{rotulo.group(1)}"' in capability
    assert 'pytauri:default' in capability
