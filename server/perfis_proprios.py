#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Registro LOCAL OCULTO dos perfis criados/importados pela PRÓPRIA ferramenta.

Prova OFFLINE de que um navegador (AdsPower/IxBrowser) nasceu do GS Creator a partir
de um perfil COMPRADO no painel. É um dos sinais do PORTÃO DE POSSE das funções
"Reutilizar Logados" e "Reprocessar por grupo" (pedido do dono, 2026-10-08):

    perfil é do GranaSocial  ⇔  bate AQUI (índice local)  OU  bate no PAINEL
                                 (ix_profile_id / bm_email / fb_login do usuário).

Se NÃO bate em nenhum → a ferramenta entende que NÃO é um perfil do GranaSocial,
PULA o perfil e mostra só a mensagem genérica — sem revelar COMO detectou.

O arquivo é assinado (HMAC com chave derivada da máquina) para levantar a barra
contra forja manual. A prova AUTORITATIVA continua sendo o painel; este índice é
cache/offline (cobre app reinstalado, troca de sessão, etc. via painel).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_SEGREDO = b'GSx-ownership-v1::granasocial.xyz::2026-10-08'  # ofuscação local
_CACHE = None  # dict em memória (lazy)


def _hwid() -> str:
    try:
        from server.granasocial_db import gerar_hwid
        return str(gerar_hwid() or '')
    except Exception:
        import platform
        return hashlib.sha256(f"{platform.node()}-{platform.machine()}".encode()).hexdigest()


def _chave() -> bytes:
    return hashlib.sha256(_SEGREDO + _hwid().encode('utf-8', 'ignore')).digest()


def _caminho() -> str:
    base = (os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
            or os.path.expanduser('~'))
    d = os.path.join(base, 'Microsoft', 'CLR', '.gsx')
    try:
        os.makedirs(d, exist_ok=True)
        try:  # atributo OCULTO no Windows (best-effort)
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(d), 0x02)
        except Exception:
            pass
    except Exception:
        pass
    return os.path.join(d, 'devindex.dat')


def _assinar(corpo: dict) -> str:
    raw = json.dumps(corpo, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hmac.new(_chave(), raw, hashlib.sha256).hexdigest()


def _vazio() -> dict:
    return {'v': 1, 'ids': {}, 'idents': []}


def _carregar() -> dict:
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        dados = _vazio()
        try:
            with open(_caminho(), 'r', encoding='utf-8') as f:
                blob = json.load(f)
            corpo = blob.get('corpo') or {}
            sig = str(blob.get('sig') or '')
            if sig and hmac.compare_digest(sig, _assinar(corpo)):
                dados = {
                    'v': int(corpo.get('v') or 1),
                    'ids': {str(k): list(v or []) for k, v in (corpo.get('ids') or {}).items()},
                    'idents': list(corpo.get('idents') or []),
                }
            else:
                # Assinatura ausente/divergente → índice inválido ou adulterado: ignora
                # (não vale como prova de posse; o painel decide).
                logger.warning('[PerfisProprios] índice local inválido/adulterado — ignorado.')
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning('[PerfisProprios] falha ao ler índice local: %s', e)
        _CACHE = dados
        return _CACHE


def _salvar(dados: dict) -> None:
    try:
        corpo = {'v': 1, 'ids': dados.get('ids', {}), 'idents': dados.get('idents', [])}
        blob = {'corpo': corpo, 'sig': _assinar(corpo)}
        alvo = _caminho()
        tmp = alvo + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(blob, f, ensure_ascii=False)
        os.replace(tmp, alvo)
    except Exception as e:
        logger.warning('[PerfisProprios] falha ao salvar índice local: %s', e)


def _norm(s) -> str:
    return str(s or '').strip().lower()


def registrar(engine='', profile_id='', login='', email='', **_extra) -> None:
    """Grava que ESTE perfil/identificador nasceu da ferramenta (perfil comprado).
    Chamado quando o Creator CRIA o navegador de um perfil importado/comprado e
    quando o painel confirma a posse (cache). Best-effort; nunca levanta."""
    try:
        eng = _norm(engine) or 'adspower'
        pid = str(profile_id or '').strip()
        idents = [i for i in (_norm(login), _norm(email)) if i]
        if not pid and not idents:
            return
        with _LOCK:
            d = _carregar()
            mudou = False
            if pid:
                lst = d['ids'].setdefault(eng, [])
                if pid not in lst:
                    lst.append(pid)
                    mudou = True
            for it in idents:
                if it not in d['idents']:
                    d['idents'].append(it)
                    mudou = True
            if mudou:
                _salvar(d)
    except Exception as e:
        logger.warning('[PerfisProprios] registrar falhou: %s', e)


def contem(engine='', profile_id='') -> bool:
    """True se o profile_id já está no índice local (criado pela ferramenta)."""
    pid = str(profile_id or '').strip()
    if not pid:
        return False
    try:
        d = _carregar()
        eng = _norm(engine) or 'adspower'
        if pid in (d['ids'].get(eng) or []):
            return True
        # tolerância: mesmo id gravado sob outro engine
        for v in d['ids'].values():
            if pid in v:
                return True
    except Exception:
        pass
    return False


def contem_identificador(login='', email='') -> bool:
    """True se o login OU e-mail do perfil bate com um identificador já registrado."""
    try:
        alvo = {_norm(login), _norm(email)} - {''}
        if not alvo:
            return False
        d = _carregar()
        return bool(alvo & set(d.get('idents') or []))
    except Exception:
        return False
