"""
Catálogo de tipos e validação advisory.

A validação daqui é CONSELHO. Quem valida de verdade é o servidor, na
sincronização — então estes testes afirmam que ela avisa, e afirmam com
igual ênfase que ela **não bloqueia**.

FIX-PM-18
"""

import pytest

from param_manager.type_catalog import (
    CATALOGO_EMBARCADO,
    validar_advisory,
)

# Limite padrão que o servidor aplica quando o payload não traz o dele.
# É a armadilha que motivou o catálogo.
MAX_LENGTH_PADRAO = 30


def test_catalogo_embarcado_tem_a_forma_publicada():
    """As três chaves que o cliente lê precisam existir no piso."""
    assert set(CATALOGO_EMBARCADO) == {'types', 'sensitive', 'defaults'}
    assert set(CATALOGO_EMBARCADO['defaults']) == {
        'min_length',
        'max_length',
        'min_value',
        'max_value',
    }


def test_piso_embarcado_conhece_os_tipos_sensiveis():
    """
    O conjunto sensível do piso precisa bater com o que o modo local
    recusa — senão a recusa e o aviso discordariam.
    """
    from param_manager.crypto import SENSITIVE_TYPES

    assert sorted(CATALOGO_EMBARCADO['sensitive']) == sorted(SENSITIVE_TYPES)


def test_payload_valido_nao_gera_aviso():
    assert validar_advisory({'value': 8080, 'type': 'int'}) == []


def test_string_longa_demais_avisa_com_o_limite_padrao():
    """
    FIX-PM-18: a armadilha central.

    O cliente omite `max_length` quando o chamador não informa, e o
    servidor aplica 30. Sem este aviso, a recusa só apareceria no fim de
    uma sessão inteira de trabalho offline.
    """
    payload = {'value': 'x' * 40, 'type': 'string'}

    avisos = validar_advisory(payload)

    assert len(avisos) == 1
    assert str(MAX_LENGTH_PADRAO) in avisos[0]
    assert 'max_length' in avisos[0]


def test_limite_explicito_no_payload_vence_o_default():
    """Informar o limite é justamente como se eleva o teto."""
    payload = {'value': 'x' * 40, 'type': 'string', 'max_length': 100}

    assert validar_advisory(payload) == []


def test_numero_acima_do_maximo_avisa():
    payload = {'value': 2_000_000, 'type': 'int'}

    avisos = validar_advisory(payload)

    assert len(avisos) == 1
    assert 'max_value' in avisos[0]


def test_tipo_desconhecido_avisa():
    avisos = validar_advisory({'value': 1, 'type': 'inexistente'})

    assert any('não está no catálogo' in a for a in avisos)


def test_catalogo_novo_ensina_tipo_que_o_piso_nao_conhece():
    """
    FIX-PM-18: é por isso que o catálogo é dado, e não código.

    Tipo novo no servidor deixa de gerar aviso assim que o catálogo é
    atualizado — sem release da biblioteca.
    """
    catalogo = {
        **CATALOGO_EMBARCADO,
        'types': [*CATALOGO_EMBARCADO['types'], 'duration'],
    }

    assert validar_advisory({'value': 1, 'type': 'duration'}) != []
    assert validar_advisory({'value': 1, 'type': 'duration'}, catalogo) == []


def test_lista_tambem_passa_pelo_limite_de_comprimento():
    payload = {'value': list(range(40)), 'type': 'list'}

    assert validar_advisory(payload) != []


@pytest.mark.parametrize(
    'payload',
    [
        {'value': None, 'type': 'string'},
        {'value': {'a': 1}, 'type': 'dict'},
        {},
    ],
)
def test_nunca_levanta_seja_qual_for_o_payload(payload):
    """
    FIX-PM-18: conselho que derruba o processo não é conselho.

    Esta função roda no caminho de escrita do modo local; uma exceção
    aqui transformaria uma dica em falha de gravação.
    """
    assert isinstance(validar_advisory(payload), list)
