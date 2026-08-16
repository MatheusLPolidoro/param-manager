"""
Preferências do FRONT — tema, idioma, última sessão usada.

Isto não é dado do usuário, é estado de janela. Mora em arquivo próprio no
diretório de configuração do sistema operacional, e **nunca** no sidecar
da lib: o sidecar guarda parâmetros que o operador escreveu e que a
sincronização vai empurrar, e um `drop_table` de recuperação não pode
levar junto a escolha de tema — nem o inverso, um reset de tema não pode
encostar em rascunho não sincronizado.

Sem dependência externa: `platformdirs` resolveria isto, mas seria uma
dependência nova numa lib cujo produto é ser embutível.
"""

from __future__ import annotations

import json
import locale
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

IDIOMAS_SUPORTADOS = ('pt-BR', 'en')
IDIOMA_PADRAO = 'pt-BR'
TEMAS_VALIDOS = ('system', 'light', 'dark')

PADROES: Dict[str, Any] = {
    'theme': 'system',
    'language': None,
    'last_instance': 'default',
    'sidebar_width': 240,
    'rail_collapsed': False,
}


def _base_config() -> Path:
    """Diretório de configuração do SO, sem trazer `platformdirs` junto."""
    if sys.platform == 'win32':
        raiz = os.environ.get('APPDATA') or os.path.expanduser('~')
        return Path(raiz) / 'param-manager'
    if sys.platform == 'darwin':
        suporte = Path.home() / 'Library' / 'Application Support'
        return suporte / 'param-manager'
    raiz = os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config')
    return Path(raiz) / 'param-manager'


def caminho_prefs() -> Path:
    return _base_config() / 'front-prefs.json'


def idioma_do_sistema() -> str:
    """
    Idioma inicial, deduzido do locale, com queda para pt-BR.

    `getlocale` devolve coisas como `pt_BR` ou `Portuguese_Brazil`; só o
    prefixo interessa, e qualquer coisa fora da lista suportada vira o
    padrão em vez de deixar a interface com chaves cruas na tela.
    """
    try:
        bruto = locale.getlocale()[0] or ''
    except (TypeError, ValueError):
        bruto = ''
    bruto = bruto.replace('-', '_').lower()
    if bruto.startswith('pt'):
        return 'pt-BR'
    if bruto.startswith('en'):
        return 'en'
    return IDIOMA_PADRAO


def carregar() -> Dict[str, Any]:
    """
    Preferências em vigor. Arquivo ausente ou corrompido vira os padrões.

    Preferência ilegível não pode impedir o app de abrir: o pior caso
    aceitável é o usuário reescolher o tema.
    """
    prefs = dict(PADROES)
    try:
        with caminho_prefs().open(encoding='utf-8') as arquivo:
            gravado = json.load(arquivo)
    except (OSError, ValueError):
        return prefs

    if isinstance(gravado, dict):
        for chave in PADROES:
            if chave in gravado:
                prefs[chave] = gravado[chave]
    return _sanear(prefs)


def _sanear(prefs: Dict[str, Any]) -> Dict[str, Any]:
    if prefs.get('theme') not in TEMAS_VALIDOS:
        prefs['theme'] = PADROES['theme']
    if prefs.get('language') not in IDIOMAS_SUPORTADOS:
        prefs['language'] = None
    largura = prefs.get('sidebar_width')
    if not isinstance(largura, (int, float)) or isinstance(largura, bool):
        prefs['sidebar_width'] = PADROES['sidebar_width']
    else:
        # Mesmos limites do `rail.js`. Duplicados de propósito: um
        # arquivo editado à mão com 4000 empurraria a tabela para fora da
        # tela, e o front não tem como recusar o que já leu.
        prefs['sidebar_width'] = min(420, max(180, int(largura)))
    if not isinstance(prefs.get('rail_collapsed'), bool):
        prefs['rail_collapsed'] = False
    if not isinstance(prefs.get('last_instance'), str):
        prefs['last_instance'] = PADROES['last_instance']
    return prefs


def salvar(**mudancas: Any) -> Dict[str, Any]:
    """
    Grava só as chaves conhecidas, por escrita atômica.

    O `replace` sobre um temporário no mesmo diretório existe porque o app
    fechando no meio de um `write` deixaria um JSON truncado — que na
    próxima subida cai no caminho de "corrompido, usa padrão" e o usuário
    perde as escolhas dele sem entender por quê.
    """
    prefs = carregar()
    prefs.update({k: v for k, v in mudancas.items() if k in PADROES})
    prefs = _sanear(prefs)

    destino = caminho_prefs()
    destino.parent.mkdir(parents=True, exist_ok=True)
    descritor, temporario = tempfile.mkstemp(
        dir=str(destino.parent), suffix='.tmp'
    )
    try:
        with os.fdopen(descritor, 'w', encoding='utf-8') as arquivo:
            json.dump(prefs, arquivo, ensure_ascii=False, indent=2)
        os.replace(temporario, destino)
    except OSError:
        Path(temporario).unlink(missing_ok=True)
        raise
    return prefs
