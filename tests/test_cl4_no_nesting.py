"""
CL-4 — a invariante `no-nesting` como teste executável.

Duas metades, deliberadamente diferentes em técnica:

1. **Runtime**: wrappers instrumentados nos três locks de instância,
   exercitando os métodos públicos, assertando que nenhuma thread
   segurou dois locks ao mesmo tempo. Sem aninhamento não há ciclo,
   logo não há deadlock possível.
2. **Estático**: varredura por AST provando que os cinco dicts de estado
   só são tocados pelos seis helpers acordados. Sem esta metade a
   unidade validaria só a parte fácil, e uma escrita direta de cache
   (que é o que abre race de publicação) passaria despercebida.

FIX-PM-12
"""

import ast
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import param_manager.manager as manager_mod

API = 'http://test-api.example.com'

# Os três locks de instância. `_lock_singleton` fica de fora de
# propósito: é de classe, e a única exceção permitida à regra
# (_lock_singleton -> _lock dentro de __init__) acontece antes de
# qualquer instrumentação ser instalada.
LOCKS_DE_INSTANCIA = ('_lock', '_state_lock', '_token_lock')

# Os cinco dicts protegidos por _state_lock.
DICTS_DE_ESTADO = frozenset({
    '_cache',
    '_cache_timestamp',
    '_param_cache',
    '_param_cache_timestamp',
    '_api_error_timestamp',
})

# Quem pode tocar nos cinco dicts. Os seis helpers acordados, mais
# __init__ (que os cria) e clear_cache (ação explícita do operador,
# com semântica própria documentada no ponto).
TOCADORES_LEGITIMOS = frozenset({
    '__init__',
    '_snapshot_cache',
    '_publish_cache',
    '_arm_breaker',
    '_disarm_breaker',
    '_breaker_active',
    '_snapshot_info',
    'clear_cache',
})

# Violações conhecidas e ainda ABERTAS. Estão aqui NOMEADAS, e não
# silenciadas: o objetivo da CL-4 é tornar o resto visível, então
# qualquer escrita nova reprova, e fechar uma destas significa apagar a
# linha correspondente — não editá-la (ver
# test_violacoes_conhecidas_nao_crescem).
#
# - _fetch_param_from_api e get_param escrevem _param_cache e
#   _param_cache_timestamp direto, e _fetch_param_from_api ainda
#   publica em _cache SEM gravar _cache_timestamp — o carimbo que o
#   CAS de _publish_cache confere. É a metade do R5 que ficou aberta
#   no lote de concorrência.
# - delete_param substitui self._cache[app] por dict novo sob
#   _state_lock. A escrita em si está correta e é deliberada (R2), mas
#   dispensa o CAS que upsert_params respeita via _publish_cache.
#   Inconsistência de contrato, não race conhecida.
VIOLACOES_CONHECIDAS = frozenset({
    '_fetch_param_from_api',
    'get_param',
    'delete_param',
})


class _LockEspiao:
    """
    Envelope de `threading.Lock` que registra quem segura o quê.

    Delega para um Lock real: o comportamento de exclusão mútua é o
    mesmo, só ganha contabilidade. Registrar a violação em vez de
    levantar dentro do `with` é deliberado — levantar ali trocaria o
    relatório de aninhamento por um traceback de teardown no meio de
    uma seção crítica.
    """

    def __init__(self, nome, registro, segurados):
        self._nome = nome
        self._lock = threading.Lock()
        self._registro = registro
        self._segurados = segurados

    def _pilha(self):
        if not hasattr(self._segurados, 'pilha'):
            self._segurados.pilha = []
        return self._segurados.pilha

    def __enter__(self):
        pilha = self._pilha()
        if pilha:
            self._registro.append((
                threading.current_thread().name,
                tuple(pilha),
                self._nome,
            ))
        self._lock.acquire()
        pilha.append(self._nome)
        return self

    def __exit__(self, *exc):
        self._pilha().pop()
        self._lock.release()
        return False

    # get_cache_info e afins não usam, mas o contrato de Lock inclui
    # acquire/release soltos — delegar evita surpresa se alguém passar
    # a usá-los.
    def acquire(self, *a, **kw):
        resultado = self._lock.acquire(*a, **kw)
        if resultado:
            self._pilha().append(self._nome)
        return resultado

    def release(self):
        self._pilha().pop()
        self._lock.release()


@pytest.fixture
def pm_instrumentado(setup_param_manager):
    """Troca os três locks de instância por espiões."""
    pm, mock_table, requests_mock = setup_param_manager

    # Sem isto o merge de _save_to_local_db faz {**MagicMock()} e
    # estoura antes de exercitar qualquer lock.
    mock_table.get.return_value = None

    registro = []
    segurados = threading.local()

    for nome in LOCKS_DE_INSTANCIA:
        setattr(pm, nome, _LockEspiao(nome, registro, segurados))

    return pm, mock_table, requests_mock, registro


def _registrar_rotas(requests_mock, app='app_teste', param='chave'):
    """Todas as rotas que os métodos públicos do cliente consomem."""
    requests_mock.post(
        f'{API}/auth/token',
        json={'access_token': 'tok', 'refresh_token': 'ref'},
    )
    requests_mock.post(
        f'{API}/parameters/apps/',
        json={'message': 'criado', 'app': {'name': app}},
        status_code=201,
    )
    requests_mock.put(
        f'{API}/parameters/apps/{app}/params/',
        json={'app': app, 'params': {param: {'value': 1, 'type': 'int'}}},
    )
    requests_mock.get(
        f'{API}/parameters/apps/{app}/params/',
        json={'params': {param: {'value': 1, 'type': 'int'}}},
    )
    requests_mock.get(
        f'{API}/parameters/apps/{app}/params/{param}',
        json={'param': {'value': 1, 'type': 'int'}},
    )
    requests_mock.delete(
        f'{API}/parameters/apps/{app}/params/{param}',
        json={'message': 'removido'},
    )
    requests_mock.delete(
        f'{API}/parameters/apps/{app}',
        json={'message': 'removido'},
    )


def _exercitar_superficie_publica(pm, app='app_teste', param='chave'):
    """Chama todos os métodos públicos, na ordem em que um app usaria."""
    pm.create_app(app, 'descricao')
    pm.upsert_params(app, param, value=1, param_type='int')
    pm.get_all_params(app)
    pm.get_param(app, param)
    pm.get_cache_info()
    pm.delete_param(app, param)
    pm.clear_cache(app)
    pm.get_all_params(app)
    pm.clear_cache()
    pm.delete_app(app)


def test_nenhuma_thread_segura_dois_locks_de_instancia(pm_instrumentado):
    """
    FIX-PM-12: a regra `no-nesting` deixa de ser convenção.

    Exercita a superfície pública inteira em thread única. Aninhamento
    é propriedade do caminho de código, não do paralelismo: se um
    método adquire B enquanto segura A, uma thread só já revela.
    """
    pm, _mock_table, requests_mock, registro = pm_instrumentado
    _registrar_rotas(requests_mock)

    _exercitar_superficie_publica(pm)

    assert registro == [], (
        'Aninhamento de locks detectado — a regra `no-nesting` foi '
        f'violada: {registro}. Cada tupla é (thread, locks já '
        'segurados, lock adquirido por cima).'
    )


def test_no_nesting_sob_concorrencia(pm_instrumentado):
    """
    FIX-PM-12: mesma invariante com várias threads na superfície.

    Barreira para forçar a largada junta — nunca `sleep`. O
    faulthandler_timeout=60 do pyproject dumpa todas as threads se
    algum caminho travar, em vez de pendurar o job.
    """
    pm, _mock_table, requests_mock, registro = pm_instrumentado
    _registrar_rotas(requests_mock)

    n = 4
    largada = threading.Barrier(n)
    erros = []
    corrida_r5b = []

    def trabalhador():
        try:
            largada.wait(timeout=10)
            _exercitar_superficie_publica(pm)
        except KeyError as e:
            # R5-b, reproduzida abaixo de forma determinística. Este
            # teste tem outro assunto (no-nesting); tolerar SÓ esta
            # exceção evita que a race conhecida mascare o que ele
            # realmente afere, sem esconder nenhuma outra falha.
            corrida_r5b.append(e)
        except Exception as e:  # pragma: no cover
            erros.append(e)

    threads = [
        threading.Thread(target=trabalhador, name=f'w{i}') for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not [t for t in threads if t.is_alive()], (
        'Thread não terminou — possível deadlock, que é exatamente o '
        'que a regra `no-nesting` existe para tornar impossível.'
    )
    assert erros == [], f'Erro inesperado nas threads: {erros}'
    assert registro == [], (
        f'Aninhamento de locks sob concorrência: {registro}'
    )


# Métodos de dict que mutam o receptor. Chamá-los sobre um dos cinco
# dicts é escrita, ainda que a sintaxe pareça leitura.
METODOS_MUTADORES = frozenset({
    'pop',
    'popitem',
    'clear',
    'update',
    'setdefault',
})


def _e_dict_de_estado(no):
    """Diz se o nó é `self.<um dos cinco dicts>`."""
    return (
        isinstance(no, ast.Attribute)
        and isinstance(no.value, ast.Name)
        and no.value.id == 'self'
        and no.attr in DICTS_DE_ESTADO
    )


def _alvos_escritos(no):
    """
    Dicts de estado que este nó ESCREVE. Leitura não conta.

    A distinção é o ponto: ler `_cache` para decidir validade é barato
    e inofensivo; publicar nele sem CAS é o que reabre a race. Uma
    regra que proíba as duas coisas seria abandonada na primeira vez
    que atrapalhasse, e regra abandonada não protege nada.
    """
    escritos = set()

    # self._cache[k] = v  /  del self._cache[k]  /  self._cache = {}
    if isinstance(no, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        alvos = no.targets if isinstance(no, ast.Assign) else [no.target]
        for alvo in alvos:
            for sub in ast.walk(alvo):
                if _e_dict_de_estado(sub):
                    escritos.add(sub.attr)
                elif isinstance(sub, ast.Subscript) and _e_dict_de_estado(
                    sub.value
                ):
                    escritos.add(sub.value.attr)

    elif isinstance(no, ast.Delete):
        for alvo in no.targets:
            for sub in ast.walk(alvo):
                if isinstance(sub, ast.Subscript) and _e_dict_de_estado(
                    sub.value
                ):
                    escritos.add(sub.value.attr)

    # self._cache.pop(k) e afins
    elif isinstance(no, ast.Call):
        func = no.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in METODOS_MUTADORES
            and _e_dict_de_estado(func.value)
        ):
            escritos.add(func.value.attr)

    return escritos


def _escritores_dos_dicts_de_estado():
    """
    Devolve {nome_do_metodo: {dicts que ele ESCREVE}} lendo o AST.

    Estático de propósito: cobertura em runtime só prova o caminho que
    o teste andou, e o objeto aqui é uma regra sobre o código inteiro.
    """
    fonte = Path(manager_mod.__file__).read_text(encoding='utf-8')
    arvore = ast.parse(fonte)

    classe = next(
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.ClassDef) and no.name == 'ParamManager'
    )

    escritores = {}
    for metodo in classe.body:
        if not isinstance(metodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for no in ast.walk(metodo):
            escritos = _alvos_escritos(no)
            if escritos:
                escritores.setdefault(metodo.name, set()).update(escritos)
    return escritores


def test_dicts_de_estado_so_sao_escritos_pelos_helpers():
    """
    FIX-PM-12: o contrato dos seis helpers vira regra verificável.

    Escrita direta nos dicts é o que reabre a race de publicação —
    gravar cache sem CAS, ou sem o timestamp que o CAS confere.
    """
    escritores = _escritores_dos_dicts_de_estado()
    permitidos = TOCADORES_LEGITIMOS | VIOLACOES_CONHECIDAS

    infratores = {
        nome: sorted(dicts)
        for nome, dicts in escritores.items()
        if nome not in permitidos
    }

    assert infratores == {}, (
        'Estes métodos ESCREVEM nos dicts de estado sem passar pelos '
        f'seis helpers acordados: {infratores}. Use _snapshot_cache, '
        '_publish_cache, _arm_breaker, _disarm_breaker, '
        '_breaker_active ou _snapshot_info — o acesso direto é o que '
        'reintroduz a race de publicação (R5).'
    )


def test_violacoes_conhecidas_nao_crescem():
    """
    FIX-PM-12: a lista de exceções é teto, não gaveta.

    Se uma violação for corrigida, este teste reprova e obriga a apagar
    a linha correspondente — impedindo que a exceção sobreviva à causa.
    """
    escritores = _escritores_dos_dicts_de_estado()
    ainda_violando = {
        nome for nome in VIOLACOES_CONHECIDAS if nome in escritores
    }

    assert ainda_violando == set(VIOLACOES_CONHECIDAS), (
        'VIOLACOES_CONHECIDAS lista método que não viola mais: '
        f'{set(VIOLACOES_CONHECIDAS) - ainda_violando}. Apague a '
        'entrada em vez de deixá-la envelhecer.'
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        'R5-b em aberto: get_param faz check-then-act entre '
        '_is_param_cache_valid (que solta o _state_lock) e a leitura '
        'self._param_cache[key], em manager.py:1128-1135. Um '
        'clear_cache(app, param) concorrente — chamado por delete_param '
        'e por upsert_params — remove a chave na janela e o KeyError '
        'escapa para a aplicação consumidora. Corrigir é escopo de '
        'outra unidade; quando entrar, este xfail vira verde e o '
        'strict=True obriga a remover o marcador.'
    ),
)
def test_get_param_nao_estoura_keyerror_em_corrida_com_clear_cache(
    setup_param_manager,
):
    """
    FIX-PM-13: leitura pública não pode morrer por race de cache.

    Reprodução determinística — a concorrência é simulada de dentro da
    janela, não por sorte de escalonamento: o side_effect remove a
    chave exatamente entre a checagem de validade e a leitura, que é o
    que uma thread concorrente faria.
    """
    pm, mock_table, _requests_mock = setup_param_manager
    mock_table.get.return_value = None

    chave = 'app_teste:chave'
    pm._param_cache[chave] = {'value': 1, 'type': 'int'}
    pm._param_cache_timestamp[chave] = time.time()

    def valida_e_alguem_limpa(app_name, param_name):
        # A thread concorrente entra aqui, no exato ponto em que o
        # _state_lock já foi solto e a leitura ainda não aconteceu.
        pm._param_cache.pop(f'{app_name}:{param_name}', None)
        pm._param_cache_timestamp.pop(f'{app_name}:{param_name}', None)
        return True

    with patch.object(
        pm, '_is_param_cache_valid', side_effect=valida_e_alguem_limpa
    ):
        # Não deve levantar: o contrato da lib é que leitura devolve
        # valor ou None, nunca explode na cara do consumidor.
        pm.get_param('app_teste', 'chave')
