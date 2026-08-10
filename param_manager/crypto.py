"""
Metade cliente do envelope criptográfico, e o processamento de valores.

**Puro de propósito**: sem estado de instância, sem lock, sem I/O de rede
ou de disco. É o que permite chamá-lo de qualquer camada sem participar
da regra `no-nesting` — nenhuma função daqui pode adquirir lock nenhum.

O envelope é **contrato congelado** com o `fast-param-manager`, que cifra
em `security/crypto_utils.py`. As duas implementações vivem em projetos
liberados separadamente: mudar `count`, `dkLen`, o hash do PBKDF2, o
tamanho do IV, o modo da cifra, a serialização hex ou os nomes
`salt`/`master_key`/`crypto_data`/`iv`/`tag`/`data` invalida todo segredo
já gravado e todo cliente já publicado. Ver a memória `crypto_scheme`.
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2

# Mesmo logger de antes da extração: trocar o nome mudaria a saída de log
# observável e quebraria quem filtra por ele.
logger = logging.getLogger('ParamManager')

# Tipos cujo valor trafega cifrado entre a API e esta biblioteca.
SENSITIVE_TYPES = frozenset({'secret', 'user', 'users'})

# Chaves obrigatórias do envelope criptográfico. Contrato congelado com o
# servidor — ver a documentação do fast-param-manager antes de alterar.
ENVELOPE_KEYS = ('salt', 'master_key', 'crypto_data')


def _is_envelope(value: Any) -> bool:
    """Diz se o valor é um envelope criptográfico íntegro."""
    return isinstance(value, dict) and all(
        key in value for key in ENVELOPE_KEYS
    )


def _is_encrypted_param(param: Any) -> bool:
    """
    Diz se um parâmetro sensível ainda está com o valor cifrado.

    Parâmetros de tipo não sensível são sempre considerados seguros
    para persistir.
    """
    if not isinstance(param, dict):
        return True

    param_type = param.get('type')
    value = param.get('value')

    if param_type == 'secret':
        return _is_envelope(value)
    if param_type == 'user':
        return isinstance(value, dict) and _is_envelope(value.get('password'))
    if param_type == 'users':
        return isinstance(value, list) and all(
            isinstance(item, dict) and _is_envelope(item.get('password'))
            for item in value
        )
    return True


def _process_parameters(params: dict) -> dict:
    """
    Devolve os parâmetros com os valores sensíveis decifrados.

    Para `secret`, `user` e `users` devolve uma cópia profunda — é
    o que garante que o texto claro nunca alcance o cache nem o
    banco local. Tipos não sensíveis são devolvidos POR REFERÊNCIA:
    o dict retornado é o mesmo objeto guardado em `self._cache`, e
    mutá-lo altera o cache do processo.
    """
    return {key: _process_parameter(param) for key, param in params.items()}


def _process_parameter(params: dict) -> dict | None:
    """
    Decifra um parâmetro sensível devolvendo uma cópia.

    Tipos fora de SENSITIVE_TYPES são devolvidos como vieram, sem
    cópia — ver a nota de aliasing em `_process_parameters`.
    """
    if not isinstance(params, dict):
        return params

    if params.get('type') not in SENSITIVE_TYPES:
        return params

    params = copy.deepcopy(params)

    if params.get('type') == 'secret':
        raw = params.get('value')
        if isinstance(raw, dict):
            params['value'] = _decrypt_param(raw)
    elif params.get('type') == 'users':
        raw = params.get('value')
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and isinstance(
                    item.get('password'), dict
                ):
                    item['password'] = _decrypt_param(item['password'])
    elif params.get('type') == 'user':
        raw = params.get('value')
        if isinstance(raw, dict):
            if isinstance(raw.get('password'), dict):
                raw['password'] = _decrypt_param(raw['password'])
    return params


def _extract_value(param_value: dict) -> Any:
    if not isinstance(param_value, dict):
        return None
    if param_value.get('type') in SENSITIVE_TYPES:
        param_value = _process_parameter(param_value)
    return param_value.get('value')


def _decrypt_param(value: dict) -> str | None:
    try:
        if not all(
            k in value for k in ['salt', 'master_key', 'crypto_data']
        ):
            return None

        app_custody_key = os.getenv('CHAVE_CUSTODIA_APP') or os.getenv(
            'APP_CUSTODY_KEY'
        )
        if not app_custody_key:
            logger.error(
                '🔐 CHAVE_CUSTODIA_APP não está definida no ambiente.'
            )
            return None

        salt = bytes.fromhex(value['salt'])
        custody_key = PBKDF2(
            app_custody_key.encode(),
            salt,
            dkLen=32,
            count=100_000,
            hmac_hash_module=SHA256,
        )

        cm_iv = bytes.fromhex(value['master_key']['iv'])
        cm_tag = bytes.fromhex(value['master_key']['tag'])

        # `dado` é a chave legada, tolerada dos dois lados do contrato.
        cm_data = bytes.fromhex(
            value['master_key'].get('data')
            or value['master_key'].get('dado')
        )

        cipher_cm = AES.new(custody_key, AES.MODE_GCM, cm_iv)
        master_key = cipher_cm.decrypt_and_verify(cm_data, cm_tag)

        pw_iv = bytes.fromhex(value['crypto_data']['iv'])
        pw_tag = bytes.fromhex(value['crypto_data']['tag'])
        pw_data = bytes.fromhex(
            value['crypto_data'].get('data')
            or value['crypto_data'].get('dado')
        )
        cipher_pw = AES.new(master_key, AES.MODE_GCM, pw_iv)
        password = cipher_pw.decrypt_and_verify(pw_data, pw_tag)

        return password.decode()
    except Exception as e:
        logger.error(f'Erro ao descriptografar parâmetro secreto: {str(e)}')
        return None
