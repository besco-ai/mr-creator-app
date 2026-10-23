#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cliente da API do painel (VIA HTTPS).
======================================================================
IMPORTANTE (2026-08-12): este módulo NÃO conecta mais no MySQL direto.
A porta 3306 foi FECHADA para a internet na blindagem de segurança — e a
senha do banco NUNCA mais é embarcada no .exe distribuído. Todas as
operações passam pelo endpoint HTTPS `api/software_api.php`, que roda na
VPS e fala com o MySQL local (127.0.0.1). As assinaturas das funções foram
mantidas idênticas para não quebrar backend.py / acesso.py / etapas.

Autenticação de cada chamada: username + password da sessão ativa (lidos do
`server.acesso._sessao_cache`). O `autenticar()` é a exceção — recebe as
credenciais por parâmetro, pois é o próprio login (ainda não há sessão).

Fonte de verdade (server-side) para:
  * Autenticação do software + binding de HWID (users)
  * Saldo de coins/tokens (users.coins/tokens)
  * Perfis FB comprados (tb_fb_compras + tb_bmcreator_perfis_usados)
  * Estoque de empresas (tb_estoque_cnpj)
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import uuid
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

try:
    import winreg  # Windows: leitura do MachineGuid (registro)
except ImportError:
    winreg = None  # type: ignore

try:
    import requests as _requests
    _TEM_REQUESTS = True
except ImportError:
    _requests = None  # type: ignore
    _TEM_REQUESTS = False

logger = logging.getLogger(__name__)

# ── Endpoint HTTPS ───────────────────────────────────────────────────────────
from server.marca import URL_API as _URL_DA_MARCA   # fonte unica: server/marca.py
_API_URL = _URL_DA_MARCA
_TIMEOUT_PADRAO = 60

# CA embarcado (certifi). Passamos explicito no verify= para NAO herdar um
# REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE quebrado do ambiente da maquina (ver blindagem
# no main.py). verify com caminho explicito NAO e sobrescrito pelas env vars.
try:
    import certifi as _certifi
    _CA_BUNDLE = _certifi.where()
    if not _CA_BUNDLE or not os.path.exists(_CA_BUNDLE):
        _CA_BUNDLE = True
except Exception:
    _CA_BUNDLE = True

# Mensagem genérica p/ QUALQUER falha de infraestrutura. NUNCA expõe
# host/porta/URL/stack na interface — o detalhe fica só no log local.
ERR_CONEXAO = ('Não foi possível conectar ao servidor agora. '
               'Verifique sua internet e tente novamente em instantes.')


def _headers() -> Dict[str, str]:
    return {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': 'GSBMCreator/desktop',
    }


def _cred_sessao() -> tuple:
    """username + password da sessão ativa (para as chamadas autenticadas).
    Lido do acesso._sessao_cache de forma preguiçosa para evitar acoplamento
    de import no topo."""
    try:
        from server.acesso import _sessao_cache
        return (_sessao_cache.get('usuario', '') or '',
                _sessao_cache.get('senha', '') or '')
    except Exception:
        return ('', '')


def _api(action: str, extra: Optional[Dict[str, Any]] = None,
         cred: Optional[tuple] = None, timeout: int = _TIMEOUT_PADRAO) -> Dict[str, Any]:
    """POST JSON ao software_api.php. Normaliza success->sucesso, message->mensagem.
    Em qualquer erro de rede devolve {'sucesso': False, 'mensagem': ERR_CONEXAO}
    (nunca vaza detalhe técnico para a GUI)."""
    if not _TEM_REQUESTS:
        return {'sucesso': False, 'mensagem': ERR_CONEXAO}
    if cred is None:
        cred = _cred_sessao()
    payload: Dict[str, Any] = {
        'action': action,
        'username': cred[0],
        'password': cred[1],
    }
    if extra:
        payload.update(extra)
    try:
        resp = _requests.post(_API_URL, json=payload, headers=_headers(), timeout=timeout, verify=_CA_BUNDLE)
        try:
            data = resp.json()
        except Exception:
            logger.error('[granasocial-api] %s: resposta não-JSON (HTTP %s)', action, resp.status_code)
            return {'sucesso': False, 'mensagem': ERR_CONEXAO}
        if not isinstance(data, dict):
            return {'sucesso': False, 'mensagem': ERR_CONEXAO}
        if 'success' in data and 'sucesso' not in data:
            data['sucesso'] = bool(data['success'])
        if 'message' in data and 'mensagem' not in data:
            data['mensagem'] = data['message']
        return data
    except Exception as exc:
        logger.error('[granasocial-api] %s falhou: %s', action, exc)
        return {'sucesso': False, 'mensagem': ERR_CONEXAO}


# ── Util ────────────────────────────────────────────────────────────────────

def _sha256(senha: str) -> str:
    return hashlib.sha256((senha or '').encode('utf-8')).hexdigest()


_HWID_CACHE: Optional[str] = None


def _machine_guid() -> Optional[str]:
    """MachineGuid do Windows — fixo por instalacao do SO.
    NAO muda com rede/VPN/Wi-Fi/cabo/adaptador virtual."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\Microsoft\Cryptography',
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as chave:
            valor, _ = winreg.QueryValueEx(chave, 'MachineGuid')
            valor = str(valor).strip()
            return valor or None
    except Exception:
        return None


def _hwid_file_path() -> str:
    base = (os.environ.get('PROGRAMDATA')
            or os.environ.get('APPDATA')
            or os.path.expanduser('~'))
    return os.path.join(base, 'GSBMCreator', 'device.id')


def _hwid_persistido() -> str:
    """UUID aleatorio gravado UMA unica vez em disco. Fallback estavel
    quando o MachineGuid nao esta disponivel — uma vez criado, nao muda."""
    path = _hwid_file_path()
    try:
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as fh:
                val = fh.read().strip()
                if val:
                    return val
    except Exception:
        pass
    novo = uuid.uuid4().hex
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(novo)
    except Exception:
        pass
    return novo


def gerar_hwid() -> str:
    """Fingerprint ESTAVEL do computador (64 hex). NAO muda entre execucoes.

    Ordem de preferencia:
      1. MachineGuid do Windows (registro) — fixo por instalacao do SO.
      2. UUID persistido em disco (%PROGRAMDATA%/GSBMCreator/device.id).
      3. Fallback legado MAC+hostname (instavel — apenas ultimo recurso).
    """
    global _HWID_CACHE
    if _HWID_CACHE:
        return _HWID_CACHE

    base = _machine_guid()
    origem = 'machineguid'
    if not base:
        base = _hwid_persistido()
        origem = 'arquivo'
    if not base:
        # Ultimo recurso: metodo antigo, instavel (pode variar com a rede).
        try:
            mac = uuid.UUID(int=uuid.getnode()).hex[-12:]
        except Exception:
            mac = 'unknown'
        try:
            host = socket.gethostname()
        except Exception:
            host = 'unknown'
        base = f'{mac}|{host}'
        origem = 'legado-mac'

    hwid = hashlib.sha256(base.encode('utf-8')).hexdigest()[:64]
    _HWID_CACHE = hwid
    logger.info('[HWID] gerado via %s', origem)
    return hwid


def hostname_atual() -> str:
    try:
        return socket.gethostname()[:128]
    except Exception:
        return 'unknown'


def _normalizar_data(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.fromisoformat(str(valor)).date()
    except Exception:
        try:
            return datetime.strptime(str(valor)[:10], '%Y-%m-%d').date()
        except Exception:
            return None


# ── Autenticacao ────────────────────────────────────────────────────────────

ERR_USER_PASS = 'Usuário ou senha incorretos.'
ERR_BLOQUEADA = 'Sua conta está bloqueada. Contate o administrador.'
ERR_LICENCA   = 'Sua licença expirou.'
ERR_DISPOSITIVO = (
    'Esta conta está vinculada a outro dispositivo. '
    'Solicite o reset de licença no painel.'
)


def autenticar(usuario: str, senha: str) -> Dict[str, Any]:
    """Autentica via HTTPS (action `login`). Faz o binding de HWID no servidor.

    Retorna:
      {'sucesso': True, 'usuario': {...}}   -> OK
      {'sucesso': False, 'mensagem': str}   -> falha amigavel (nunca vaza infra)
    """
    usuario = (usuario or '').strip()
    senha = senha or ''
    if not usuario or not senha:
        return {'sucesso': False, 'mensagem': ERR_USER_PASS}

    resp = _api('login', {
        'hwid': gerar_hwid(),
        'hostname': hostname_atual(),
    }, cred=(usuario, senha), timeout=30)

    if not resp.get('sucesso'):
        # Erros de credencial/licença/HWID vêm do servidor com mensagem própria;
        # erros de rede já viram ERR_CONEXAO em _api. Mapeamos os conhecidos p/ as
        # constantes locais (mesma UX de antes), mantendo o resto como veio.
        msg = str(resp.get('mensagem') or resp.get('message') or ERR_USER_PASS)
        low = msg.lower()
        if 'não encontrado' in low or 'nao encontrado' in low or 'senha incorreta' in low:
            msg = ERR_USER_PASS
        elif 'licença' in low or 'licenca' in low or 'expir' in low:
            msg = ERR_LICENCA
        elif 'computador' in low or 'hwid' in low or 'dispositivo' in low:
            # Licenças multi-PC (2026-10-06): o servidor já diz QUAIS computadores
            # ocupam as licenças e como liberar — mostra o texto dele (sem infra).
            msg = msg if ('licen' in low and 'painel' in low) else ERR_DISPOSITIVO
        elif 'bloque' in low or 'inativ' in low:
            msg = ERR_BLOQUEADA
        return {'sucesso': False, 'mensagem': msg}

    lic = (resp.get('license') or resp.get('dados', {}).get('license') or {}) if isinstance(resp, dict) else {}
    if not lic:
        # Estrutura inesperada — trata como falha amigavel.
        return {'sucesso': False, 'mensagem': ERR_CONEXAO}

    expiry = _normalizar_data(lic.get('license_expiry'))
    usuario_dict = {
        'id': int(lic.get('user_id') or 0),
        'username': lic.get('username') or usuario,
        'email': lic.get('email') or '',
        'nome': lic.get('nome') or '',
        'role': (lic.get('role') or 'user'),
        'coins': float(lic.get('coins') or 0),
        'tokens': int(lic.get('tokens') or 0),
        'saldo': float(lic.get('saldo') or 0),
        'license_expiry': expiry.isoformat() if expiry else None,
        'hwid': lic.get('hwid') or gerar_hwid(),
    }
    return {'sucesso': True, 'usuario': usuario_dict}


def liberar_dispositivo(user_id: int) -> bool:
    """Reset de HWID é operação ADMIN (action `reset_hwid`, protegida por
    admin_key) — não é self-service pelo app cliente. Mantida por compat de
    import; retorna False (o reset é feito pelo painel/admin)."""
    logger.info('[granasocial] liberar_dispositivo(%s): reset de HWID é via painel/admin.', user_id)
    return False


# ── Saldo de coins/tokens ───────────────────────────────────────────────────

def obter_saldos(user_id: int) -> Dict[str, float]:
    resp = _api('get_coins')
    if not resp.get('sucesso'):
        return {'coins': 0.0, 'tokens': 0, 'saldo': 0.0}
    return {
        'coins': float(resp.get('coins') or 0),
        'tokens': int(resp.get('tokens') or 0),
        'saldo': float(resp.get('saldo') or 0),
    }


def debitar_coins(user_id: int, quantidade: float, tipo: str = 'uso_bmcreator',
                  descricao: str = '', referencia_id: Optional[int] = None) -> Dict[str, Any]:
    """Debita coins do usuario (atomico no servidor)."""
    quantidade = float(quantidade or 0)
    if quantidade <= 0:
        return {'sucesso': False, 'mensagem': 'Quantidade invalida'}
    resp = _api('debit_coins', {'quantidade': quantidade, 'descricao': descricao or ''})
    if resp.get('sucesso'):
        return {'sucesso': True, 'coins': float(resp.get('coins') or 0),
                'transacao_id': resp.get('transacao_id'),
                'debitado': float(resp.get('debitado') or quantidade)}
    return {'sucesso': False, 'mensagem': resp.get('mensagem') or 'Falha ao debitar',
            'coins': float(resp.get('coins') or 0)}


def creditar_coins(user_id: int, quantidade: float, tipo: str = 'reembolso_bmcreator',
                   descricao: str = '', referencia_id: Optional[int] = None) -> Dict[str, Any]:
    """Credita coins ao usuario (reembolso ou ajuste)."""
    quantidade = float(quantidade or 0)
    if quantidade <= 0:
        return {'sucesso': False, 'mensagem': 'Quantidade invalida'}
    resp = _api('refund_coin', {'quantidade': quantidade, 'descricao': descricao or ''})
    if resp.get('sucesso'):
        return {'sucesso': True, 'coins': float(resp.get('coins') or 0),
                'creditado': float(resp.get('reembolsado') or resp.get('creditado') or quantidade)}
    return {'sucesso': False, 'mensagem': resp.get('mensagem') or 'Falha ao creditar'}


def buscar_empresa_estoque(tipo: str = 'mei', limit: int = 5) -> List[Dict[str, Any]]:
    """Busca empresas disponiveis no estoque (action `buscar_empresas`, já
    otimizada no servidor por pivô de id — sem ORDER BY RAND lento)."""
    resp = _api('buscar_empresas', {'tipo': (tipo or 'aleatorio'), 'limit': int(limit or 5)})
    if not resp.get('sucesso'):
        return []
    return list(resp.get('empresas') or [])


def marcar_empresa_usada(cnpj: str, motivo: str = '') -> Dict[str, Any]:
    """Marca uma empresa (CNPJ) do estoque como 'usado' (idempotente)."""
    import re as _re
    cnpj_num = _re.sub(r'\D', '', str(cnpj or ''))
    if not cnpj_num:
        return {'sucesso': False, 'mensagem': 'CNPJ vazio'}
    resp = _api('marcar_empresa_usada_cnpj', {'cnpj': cnpj_num})
    if resp.get('sucesso'):
        return {'sucesso': True, 'afetadas': int(resp.get('afetadas') or 0)}
    return {'sucesso': False, 'mensagem': resp.get('mensagem') or 'Falha'}


def creditar_token(user_id: int, quantidade: int = 1,
                   tipo: str = 'estorno_site', descricao: str = '') -> Dict[str, Any]:
    """Credita (estorna) tokens ao usuario."""
    quantidade = int(quantidade or 0)
    if quantidade <= 0:
        return {'sucesso': False, 'mensagem': 'Quantidade invalida'}
    resp = _api('credit_token', {'quantidade': quantidade, 'descricao': descricao or ''})
    if resp.get('sucesso'):
        return {'sucesso': True, 'tokens': int(resp.get('tokens') or 0),
                'creditado': int(resp.get('creditado') or quantidade)}
    return {'sucesso': False, 'mensagem': resp.get('mensagem') or 'Falha ao creditar token'}


def debitar_token(user_id: int, quantidade: int = 1,
                  tipo: str = 'uso_bmcreator', descricao: str = '') -> Dict[str, Any]:
    """Debita tokens do usuario (atomico no servidor, verifica saldo)."""
    quantidade = int(quantidade or 0)
    if quantidade <= 0:
        return {'sucesso': False, 'mensagem': 'Quantidade invalida'}
    resp = _api('debit_token', {'quantidade': quantidade, 'descricao': descricao or ''})
    if resp.get('sucesso'):
        return {'sucesso': True, 'tokens': int(resp.get('tokens') or 0),
                'debitado': int(resp.get('debitado') or quantidade)}
    return {'sucesso': False, 'tokens': int(resp.get('tokens') or 0), 'debitado': 0,
            'mensagem': resp.get('mensagem') or 'Saldo de tokens insuficiente'}


# ── Perfis FB comprados ─────────────────────────────────────────────────────

def listar_compras_disponiveis(user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    """Lista compras concluidas com perfis ainda disponiveis para importar."""
    resp = _api('compras_disponiveis', {'limit': int(limit or 200)})
    if not resp.get('sucesso'):
        return []
    saida = []
    for r in (resp.get('compras') or []):
        try:
            saida.append({
                'compra_id': int(r.get('compra_id')),
                'produto_nome': r.get('produto_nome') or '',
                'quantidade_total': int(r.get('quantidade_total') or 0),
                'ja_importados': int(r.get('ja_importados') or 0),
                'disponiveis': int(r.get('disponiveis') or 0),
                'criado_em': str(r.get('criado_em') or ''),
            })
        except Exception:
            continue
    return saida


def obter_perfis_compra(user_id: int, compra_id: int) -> Dict[str, Any]:
    """Retorna o `dados_conta` de uma compra concluida (valida dono no servidor)."""
    resp = _api('perfis_compra', {'compra_id': int(compra_id)})
    if resp.get('sucesso'):
        return {
            'sucesso': True,
            'compra_id': int(resp.get('compra_id') or compra_id),
            'dados_conta': resp.get('dados_conta') or '',
            'quantidade': int(resp.get('quantidade') or 0),
        }
    return {'sucesso': False, 'mensagem': resp.get('mensagem') or 'Compra nao encontrada'}


def marcar_perfis_importados(user_id: int, compra_id: int,
                             indices: Iterable[int]) -> int:
    """Marca perfis como `importado` (action `marcar_usado`, um por index)."""
    inserted = 0
    for idx in indices:
        resp = _api('marcar_usado', {'compra_id': int(compra_id), 'perfil_index': int(idx)})
        if resp.get('sucesso'):
            inserted += 1
    return inserted


def marcar_perfil_bm_criada(user_id: int, compra_id: int, perfil_index: int,
                            bm_id: str, bm_nome: str) -> bool:
    resp = _api('marcar_bm_criada', {
        'compra_id': int(compra_id),
        'perfil_index': int(perfil_index),
        'bm_id': str(bm_id or '')[:64],
        'bm_nome': str(bm_nome or '')[:255],
    })
    return bool(resp.get('sucesso'))


def verificar_compras_status(user_id: int, compra_ids: Iterable[int]) -> Dict[int, str]:
    """Retorna {compra_id: status} para os ids informados (validacao de .txt).
    Substitui o acesso direto ao MySQL (_cursor) do gs_txt_validator."""
    ids = [int(c) for c in compra_ids if str(c).strip()]
    resp = _api('verificar_compras', {'compra_ids': ids})
    out: Dict[int, str] = {}
    if resp.get('sucesso'):
        for k, v in (resp.get('status_por_id') or {}).items():
            try:
                out[int(k)] = str(v or '')
            except Exception:
                continue
    return out


# ── Lookup de sincronizacao ao painelbr ─────────────────────────────────────

def usuario_existe_em_painelbr(username: str) -> bool:
    """Compat: antes consultava o painelbr por MySQL direto (3306, agora
    fechado). A regra "sincroniza só para editor/admin" agora é derivada do
    `role` retornado pelo login (ver acesso.validar_usuario). Mantida por
    compat de import; retorna False (o acesso.py decide pelo role)."""
    return False
