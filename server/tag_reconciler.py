#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reconciliador de TAGS em TEMPO REAL (sem abrir o navegador).
======================================================================
Enquanto o GS Creator está aberto (com o multilogin ligado), um thread leve puxa
do painel o STATUS atual das BMs do usuário (action `painel_bms_tags`) e aplica a
TAG correta no perfil via `definir_tag_desfecho_perfil` — 100% por HTTP local do
AdsPower/IxBrowser, SEM abrir o navegador.

Resolve o pedido do dono: a tag muda sozinha quando o status muda (ex.: enviou p/
análise → EM ANALISE; a Meta verificou/subiu p/ 2K → VERIFICADA 2K; rejeitou →
PRECISA ATUALIZAR; recorreu → BM Recorrida; bloqueou → BM BLOQUEADA).
A tag do multilogin reflete SÓ o CICLO da BM — o status da WABA (restrita/
desabilitada/ativa) fica apenas no painel web (Minhas BMs), 2026-10-12.

Cadência: 3 min (escolha do dono). Best-effort: nunca quebra o fluxo nem trava.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_thread = None
_stop = threading.Event()
_ultimo = {}          # profile_id -> última tag aplicada (evita chamadas redundantes)
_lock = threading.Lock()


def _ciclo(get_engine, get_mod) -> int:
    """Um ciclo de reconciliação. Retorna nº de tags atualizadas."""
    try:
        from server import painel_integration as pi
        from server import status_tags as st
    except Exception:
        return 0

    engine = (get_engine() or '').strip().lower()
    bms = pi.listar_bms_tags(engine=engine)
    if not bms:
        return 0
    mod = get_mod()
    fn = getattr(mod, 'definir_tag_desfecho_perfil', None) if mod else None
    if not fn:
        return 0

    aplicadas = 0
    for b in bms:
        pid = str(b.get('profile_id') or '').strip()
        if not pid:
            continue
        # Se a BM tem engine conhecido e difere do engine ATUAL, não aplica (perfil é
        # de outro navegador que não está aberto agora).
        beng = str(b.get('engine') or '').strip().lower()
        if beng and engine and beng != engine:
            continue
        try:
            is_restr = bool(int(b.get('is_restricted') or 0))
        except Exception:
            is_restr = bool(b.get('is_restricted'))
        tag = st.tag_para_painel(
            status=b.get('status', ''), meta_status=b.get('meta_status', ''),
            waba_status=b.get('waba_status', ''), tier=b.get('bm_limit_category', ''),
            admin_status=b.get('admin_status', ''), is_restricted=is_restr)
        if not tag:
            continue
        with _lock:
            if _ultimo.get(pid) == tag:
                continue
        try:
            if fn(pid, tag):
                with _lock:
                    _ultimo[pid] = tag
                aplicadas += 1
        except Exception as e:
            logger.debug('[TagRecon] perfil %s: %s', pid, e)

    if aplicadas:
        logger.info('[TagRecon] %d tag(s) atualizadas em tempo real (engine=%s).', aplicadas, engine)
    return aplicadas


def iniciar(get_engine, get_mod, intervalo=180):
    """Inicia o reconciliador (idempotente). `get_engine()`→'adspower'|'ixbrowser';
    `get_mod()`→módulo do engine ativo (adspower_api/ixbrowser_api)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def _loop():
        # roda uma vez logo ao iniciar, depois a cada `intervalo`
        while not _stop.is_set():
            try:
                _ciclo(get_engine, get_mod)
            except Exception as e:
                logger.debug('[TagRecon] ciclo falhou: %s', e)
            _stop.wait(max(30, int(intervalo)))

    _thread = threading.Thread(target=_loop, name='gs-tag-reconciler', daemon=True)
    _thread.start()
    logger.info('[TagRecon] Reconciliador de tags em tempo real iniciado (cada %ds).', intervalo)


def parar():
    _stop.set()


def esquecer(profile_id=None):
    """Limpa o cache (de um perfil ou de todos) p/ forçar reaplicação no próximo ciclo."""
    with _lock:
        if profile_id is None:
            _ultimo.clear()
        else:
            _ultimo.pop(str(profile_id), None)
