#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mapa ÚNICO status(painel/Meta) → TAG (emoji) do multilogin.
======================================================================
Fonte única de verdade para a tag de DESFECHO de uma BM/perfil. Usado pela
ponte de atualização em TEMPO REAL (sem abrir o navegador) e pelo Monitor.

As strings das tags casam com o filtro `_TAGS_DESFECHO` de adspower_api.py e
ixbrowser_api.py (substrings em MAIÚSCULAS), então `adicionar_tags_perfil` as
aceita e `definir_tag_desfecho_perfil` as troca de forma limpa (sem empilhar).
"""

from __future__ import annotations

# Chave CANÔNICA → tag exibida no perfil.
# 2026-10-09: as tags de TIER usam o padrão CURTO e VERDE de SUCESSO pedido pelo dono
# (✅ ... ✅). '✅ BM 2K ✅' já existe no catálogo do AdsPower (id 1217808); 10K/100K/
# ILIMITADA são criadas automaticamente (verdes). Assim que a BM sobe o limite, esta
# tag SUBSTITUI a de VERIFICADA/EM ANALISE no multilogin (desfecho de sucesso).
TAG_POR_STATUS = {
    'em_analise':        '💙 BM EM ANALISE 💙',
    'verificada':        '💚 BM VERIFICADA 💚',
    'verificada_2k':     '✅ BM 2K ✅',
    'verificada_10k':    '✅ BM 10K ✅',
    'verificada_100k':   '✅ BM 100K ✅',
    'verificada_ilimitada': '✅ BM ILIMITADA ✅',
    # ⚠️ 2026-10-12: tags de WABA ficam SÓ no painel web (Minhas BMs). NÃO entram no
    # multilogin (removidas de _PRIORIDADE e não são adicionadas a `cand`). Mantidas só
    # como referência/catálogo; se voltarem à prioridade, voltam a esconder o ciclo da BM.
    'waba_ativa':      '💚 Waba Ativa 💚',
    'waba_restrita':   '🟠 Waba Restrita 🟠',
    'waba_desabilitada': '🔴 Waba Desabilitada 🔴',
    'recorrida':       '💛 BM Recorrida 💛',
    'precisa_atualizar': '🟧 ATUALIZAR BM 🟧',   # rejeitada / mais informações / não verificada
    'bloqueada':       '💔 BM BLOQUEADA 💔',
    'erro':            '⚠️ BM ERRO ⚠️',
}

# Prioridade quando há mais de um sinal (vence o MAIS específico/avançado).
# ⚠️ 2026-10-12 (pedido do dono): a tag do MULTILOGIN mostra SÓ o CICLO da BM
# (em análise / verificada / subiu limite / rejeitada / recorrida / bloqueada), NUNCA o
# status da WABA (restrita/desabilitada/ativa) — esse fica APENAS no painel web (Minhas BMs).
# Antes `waba_restrita`/`waba_desabilitada` venciam `em_analise`/`recorrida` e viravam a tag
# única do perfil, escondendo se a BM estava em análise, verificada ou subiu p/ 2K. Agora as
# chaves `waba_*` NÃO entram na prioridade (não são emitidas ao multilogin).
# Ordem: bloqueada (fim de linha) > recorrida (recurso enviado) > precisa_atualizar (rejeitada)
# > tiers (subiu limite: ilimitada>100k>10k>2k) > verificada (250) > em_analise > erro.
_PRIORIDADE = [
    'bloqueada',
    'recorrida',
    'precisa_atualizar',
    'verificada_ilimitada', 'verificada_100k', 'verificada_10k', 'verificada_2k',
    'verificada',
    'em_analise',
    'erro',
]


def normalizar_status(status='', meta_status='', waba_status='', tier='',
                      admin_status='', is_restricted=False) -> str:
    """Converte os vários campos do painel numa CHAVE canônica de TAG_POR_STATUS.

    Reflete a classificação do conector gsmails→painel (PT/EN/ES):
      - meta_status: mais_info | permanece_desabilitada | restaurada | desabilitada |
                     restrita | verificada_250 | tier_2k | tier_100k
      - status (bm_records): rejeitada | verificada | concluida | em_analise | ...
      - waba_status: aprovada | desabilitada | restrita
    """
    s  = (status or '').strip().lower()
    ms = (meta_status or '').strip().lower()
    ws = (waba_status or '').strip().lower()
    tr = (tier or '').strip().lower()
    adm = (admin_status or '').strip().lower()

    cand = set()

    # Tier (limites aumentados) — casa tanto o `tier` curto quanto a categoria do painel
    # (bm_2k/bm_10k/bm_100k/bm_ilimitada) e o meta_status do conector (tier_*).
    if tr in ('ilimitada', 'ilimitado', 'unlimited', 'tier_ilimitada', 'bm_ilimitada') or ms == 'tier_ilimitada':
        cand.add('verificada_ilimitada')
    if tr in ('100k', 'tier_100k', 'bm_100k') or ms == 'tier_100k':
        cand.add('verificada_100k')
    if tr in ('10k', 'tier_10k', 'bm_10k') or ms == 'tier_10k':
        cand.add('verificada_10k')
    if tr in ('2k', 'tier_2k', 'bm_2k') or ms == 'tier_2k':
        cand.add('verificada_2k')

    # REJEITADA / precisa atualizar (o foco do dono): análise concluída SEM verificação,
    # "mais informações necessárias", ou não verificada pela Meta.
    if (s == 'rejeitada' or ms in ('mais_info', 'permanece_desabilitada', 'nao_verificada')):
        cand.add('precisa_atualizar')

    # Verificada (250) / concluída
    if s in ('verificada', 'concluida') or ms == 'verificada_250':
        cand.add('verificada')

    # WABA (restrita/desabilitada/ativa) → NÃO vira tag do multilogin (fica só no painel web).
    # Mantido de propósito SEM cand.add(...): a saúde da WABA é consultada em "Minhas BMs", e o
    # multilogin só carrega o CICLO da BM. A WABA desabilitada vira sinal de ciclo por OUTRAS
    # vias (recorrida via admin_status; permanece_desabilitada → precisa_atualizar; ver acima).
    # `is_restricted` e `ws`/`ms` de WABA são intencionalmente ignorados aqui.

    # Admin / recorrida
    if adm == 'recorrida':
        cand.add('recorrida')
    if adm == 'bloqueada' or s in ('bloqueada',):
        cand.add('bloqueada')

    # Em análise (estado base)
    if s in ('em_analise', 'em_processamento', 'aguardando_verificacao'):
        cand.add('em_analise')

    for chave in _PRIORIDADE:
        if chave in cand:
            return chave
    return ''


def tag_de(status_canonico: str) -> str:
    """Retorna a tag (emoji) para a chave canônica, ou '' se desconhecida."""
    return TAG_POR_STATUS.get((status_canonico or '').strip().lower(), '')


def tag_para_painel(status='', meta_status='', waba_status='', tier='',
                    admin_status='', is_restricted=False) -> str:
    """Atalho: campos do painel → tag pronta (ou '')."""
    return tag_de(normalizar_status(status, meta_status, waba_status, tier,
                                    admin_status, is_restricted))
