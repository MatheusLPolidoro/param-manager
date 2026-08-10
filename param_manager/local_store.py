"""
Armazenamento local do modo de desenvolvimento — o arquivo *sidecar*.

Duas bases TinyDB convivem por instância, com papéis que não se misturam:

- `params_<instance>.json` — **cache do que o servidor disse**. Formato
  congelado: `table(<app>)`, `doc_id=1`, `{'timestamp', 'params'}`. É o
  que um cliente 0.4.x lê como fallback offline. **Nada aqui escreve
  nele.**
- `local_<instance>.json` — **este módulo**. Rascunho autorado offline,
  metadados de app e estado de sincronização.

## Por que arquivo separado, e não tabelas reservadas no mesmo

As duas opções são compatíveis com o cliente antigo — ele nunca enumera
tabelas. O que decide é o raio de explosão dos caminhos de recuperação
que já existem no `manager.py`: um `drop_table(app)` dispara quando a
**resposta da API** vem com JSON inválido, e outro quando a leitura local
falha. Num arquivo compartilhado, um erro de parsing de resposta apagaria
parâmetros autorados localmente e ainda não sincronizados — perda de dado
do usuário causada por uma falha sem relação nenhuma com ele. O sidecar
elimina a classe inteira.

De quebra, dispensa a guarda anticolisão: `AppCreateRequest.name` não tem
validação de padrão no servidor, então um app chamado `__pm_apps__` é
hoje um nome legal.

## Concorrência

**Não cria lock.** Recebe o `threading.Lock` do `ParamManager` e o usa em
toda operação, de modo que o invariante passa a ser "todo e qualquer
acesso a qualquer TinyDB desta instância acontece sob aquele lock". Um
quinto lock é veto registrado: a fixture da CL-4 instrumenta três locks
de instância e um lock novo passaria despercebido por ela.

**Nada aqui adquire o `_state_lock` nem faz rede.** Isso criaria as
arestas `_lock -> _state_lock` e lock-sobre-I/O que a regra `no-nesting`
existe para impedir.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from tinydb import Query, TinyDB

from param_manager.crypto import SENSITIVE_TYPES

logger = logging.getLogger('ParamManager')

# Versão do formato do sidecar. A migração é preguiçosa: acontece na
# primeira abertura que encontrar versão menor, sem script e sem janela.
SCHEMA_VERSION = 1

TABELA_META = 'meta'
TABELA_APPS = 'apps'
TABELA_PARAMS = 'params'

# Estados de um parâmetro local. Não existe tabela de outbox: o estado
# mora DENTRO do registro do parâmetro, e "o que falta sincronizar" é uma
# consulta sobre os sujos.
#
# O motivo é atômico: `JSONStorage` reescreve o arquivo inteiro a cada
# escrita, então "grava o param + anexa entrada no outbox" em dois
# lugares não é atômico, e um crash no meio deixa param que nunca
# sincroniza ou entrada órfã.
ESTADO_DRAFT = 'draft'
ESTADO_DIRTY = 'dirty'
ESTADO_SYNCED = 'synced'
ESTADO_CONFLICT = 'conflict'
ESTADO_REJECTED = 'rejected'

ESTADOS_VALIDOS = frozenset({
    ESTADO_DRAFT,
    ESTADO_DIRTY,
    ESTADO_SYNCED,
    ESTADO_CONFLICT,
    ESTADO_REJECTED,
})

# Estados que ainda precisam ir ao servidor.
ESTADOS_PENDENTES = frozenset({ESTADO_DRAFT, ESTADO_DIRTY})

ORIGEM_LOCAL = 'local'
ORIGEM_SERVIDOR = 'server'


class LocalStoreError(Exception):
    """Falha de uso do armazenamento local."""


def payload_hash(payload: Any) -> str:
    """
    Impressão estável de um payload de parâmetro.

    `sort_keys` porque a ordem das chaves não é significativa e varia
    entre serializações — sem isso, o mesmo conteúdo geraria hashes
    diferentes e toda comparação viraria conflito.

    Serve de `base_hash`: a versão que o cliente viu por último como
    sincronizada. É com ele que a sincronização decide se o servidor
    mudou por baixo. **Não use `params_version` para isso** — o servidor
    o declara `exclude=True` e ele não aparece em resposta nenhuma.
    """
    bruto = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, default=str
    )
    return hashlib.sha256(bruto.encode('utf-8')).hexdigest()


class LocalStore:
    """
    Acesso ao sidecar. Sem regra de negócio e sem rede.

    Guarda de última linha: recusa gravar parâmetro de tipo sensível.
    O modo local não sabe cifrar — o `encrypt` do envelope congelado vive
    só no servidor — e gravar `secret` em claro violaria o invariante de
    que texto claro nunca toca o disco.
    """

    def __init__(self, db_path: str, lock, instance_name: str):
        self._db_path = db_path
        self._lock = lock
        self._instance_name = instance_name
        self._db = TinyDB(db_path)
        try:
            self._garantir_schema()
        except Exception:
            # O handle já está aberto quando a validação de schema falha.
            # Deixá-lo pendurado troca "não abriu" por "arquivo travado",
            # que no Windows é pior: o usuário nem consegue mais mexer no
            # rascunho à mão. Mesma lição do R7 no __init__ do manager.
            self._db.close()
            raise

    # ---------------------------------------------------------- schema

    def _garantir_schema(self) -> None:
        """
        Cria ou migra o cabeçalho do arquivo.

        Migração preguiçosa: roda na abertura, não em script. Um arquivo
        de versão futura é motivo para PARAR, não para adivinhar — abrir
        um formato que não se conhece é como se corrompe rascunho.
        """
        with self._lock:
            meta = self._db.table(TABELA_META)
            registro = meta.get(doc_id=1)

            if registro is None:
                meta.insert({
                    'schema_version': SCHEMA_VERSION,
                    'instance': self._instance_name,
                    'created_at': time.time(),
                })
                return

            versao = registro.get('schema_version', 0)
            if versao > SCHEMA_VERSION:
                raise LocalStoreError(
                    f'O arquivo local {self._db_path} está na versão '
                    f'{versao}, mais nova que a suportada '
                    f'({SCHEMA_VERSION}). Atualize a biblioteca; abrir '
                    f'assim mesmo arriscaria corromper o rascunho.'
                )
            if versao < SCHEMA_VERSION:
                # Sem passo nenhum ainda: a v1 é a primeira. Quando
                # houver v2, a migração entra aqui, em degraus.
                meta.update(
                    {'schema_version': SCHEMA_VERSION}, doc_ids=[1]
                )
                logger.info(
                    f'[ParamManager: {self._instance_name}] Arquivo local '
                    f'migrado da versão {versao} para {SCHEMA_VERSION}.'
                )

    @property
    def schema_version(self) -> int:
        with self._lock:
            registro = self._db.table(TABELA_META).get(doc_id=1) or {}
        return registro.get('schema_version', 0)

    def close(self) -> None:
        """Fecha o handle. No Windows, deixar aberto trava o arquivo."""
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------ apps

    def upsert_app(
        self,
        name: str,
        description: Optional[str] = None,
        status: str = 'active',
        origin: str = ORIGEM_LOCAL,
    ) -> Dict[str, Any]:
        """Cria ou atualiza o app local. `created_at` é preservado."""
        agora = time.time()
        with self._lock:
            tabela = self._db.table(TABELA_APPS)
            existente = tabela.get(Query().name == name)
            registro = {
                'name': name,
                'description': description,
                'status': status,
                'origin': origin,
                'created_at': (
                    existente.get('created_at') if existente else agora
                ),
                'updated_at': agora,
                'synced_at': (
                    existente.get('synced_at') if existente else None
                ),
            }
            tabela.upsert(registro, Query().name == name)
        return registro

    def get_app(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._db.table(TABELA_APPS).get(Query().name == name)

    def list_apps(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(
                self._db.table(TABELA_APPS).all(),
                key=lambda a: a.get('name', ''),
            )

    def delete_app(self, name: str) -> bool:
        """Remove o app e TODOS os seus parâmetros, numa transação só."""
        with self._lock:
            apps = self._db.table(TABELA_APPS)
            if not apps.get(Query().name == name):
                return False
            apps.remove(Query().name == name)
            self._db.table(TABELA_PARAMS).remove(Query().app == name)
        return True

    def marcar_app_sincronizado(self, name: str) -> None:
        with self._lock:
            self._db.table(TABELA_APPS).update(
                {'synced_at': time.time(), 'origin': ORIGEM_SERVIDOR},
                Query().name == name,
            )

    # -------------------------------------------------------- params

    def upsert_param(
        self,
        app: str,
        name: str,
        payload: Dict[str, Any],
        state: str = ESTADO_DRAFT,
    ) -> Dict[str, Any]:
        """
        Grava um parâmetro local no formato exato do PUT do servidor.

        `payload` é o que iria no corpo — guardar já no formato final
        evita uma tradução na hora de sincronizar, que é onde divergência
        de formato costuma aparecer.
        """
        if state not in ESTADOS_VALIDOS:
            raise LocalStoreError(
                f'Estado inválido: {state!r}. Válidos: '
                f'{sorted(ESTADOS_VALIDOS)}.'
            )
        self._recusar_sensivel(app, name, payload)

        agora = time.time()
        with self._lock:
            tabela = self._db.table(TABELA_PARAMS)
            filtro = (Query().app == app) & (Query().name == name)
            existente = tabela.get(filtro)
            registro = {
                'app': app,
                'name': name,
                'payload': payload,
                'state': state,
                'base_hash': (
                    existente.get('base_hash') if existente else None
                ),
                'last_error': None,
                'updated_at': agora,
            }
            tabela.upsert(registro, filtro)
        return registro

    @staticmethod
    def _recusar_sensivel(
        app: str, name: str, payload: Dict[str, Any]
    ) -> None:
        """
        Guarda de última linha do modo local.

        Recusar aqui, e não só na camada de cima, é o que garante que
        nenhum caminho novo consiga gravar texto claro por engano. O
        `encrypt` do envelope vive só no servidor: o modo local não tem
        como produzir um envelope válido, e gravar o valor em claro
        violaria o invariante da biblioteca.
        """
        tipo = (payload or {}).get('type')
        if tipo in SENSITIVE_TYPES:
            raise LocalStoreError(
                f"O parâmetro '{name}' do app '{app}' é do tipo '{tipo}', "
                f'que só pode ser criado com o servidor: a cifragem do '
                f'envelope acontece lá. Sincronize e crie-o em modo '
                f'remoto.'
            )

    def get_param(self, app: str, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._db.table(TABELA_PARAMS).get(
                (Query().app == app) & (Query().name == name)
            )

    def list_params(self, app: str) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(
                self._db.table(TABELA_PARAMS).search(Query().app == app),
                key=lambda p: p.get('name', ''),
            )

    def delete_param(self, app: str, name: str) -> bool:
        with self._lock:
            tabela = self._db.table(TABELA_PARAMS)
            filtro = (Query().app == app) & (Query().name == name)
            if not tabela.get(filtro):
                return False
            tabela.remove(filtro)
        return True

    def pendentes(self, app: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        O que falta sincronizar. É consulta, não fila.

        Sem tabela de outbox não há invariante entre dois lugares para
        um crash quebrar: uma escrita, um lock.
        """
        with self._lock:
            tabela = self._db.table(TABELA_PARAMS)
            registros = (
                tabela.search(Query().app == app)
                if app is not None
                else tabela.all()
            )
        return sorted(
            (r for r in registros if r.get('state') in ESTADOS_PENDENTES),
            key=lambda p: (p.get('app', ''), p.get('name', '')),
        )

    def marcar(
        self,
        app: str,
        name: str,
        state: str,
        base_hash: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> bool:
        """
        Move o parâmetro de estado depois de uma tentativa de sync.

        `last_error` guarda o `detail` do servidor **verbatim**: um 422
        traduzido perde a única informação que diz por que o parâmetro
        foi recusado.
        """
        if state not in ESTADOS_VALIDOS:
            raise LocalStoreError(
                f'Estado inválido: {state!r}. Válidos: '
                f'{sorted(ESTADOS_VALIDOS)}.'
            )
        with self._lock:
            tabela = self._db.table(TABELA_PARAMS)
            filtro = (Query().app == app) & (Query().name == name)
            if not tabela.get(filtro):
                return False
            mudanca: Dict[str, Any] = {
                'state': state,
                'last_error': last_error,
                'updated_at': time.time(),
            }
            if base_hash is not None:
                mudanca['base_hash'] = base_hash
            tabela.update(mudanca, filtro)
        return True
