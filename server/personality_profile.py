#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Personalidade comportamental persistida por perfil
======================================================================
Cada profile_id ganha um "jeito" proprio (velocidade de digitacao, padrao
de scroll, tendencia a erros, intervalo entre cliques). O JSON e salvo
em disco — assim, na proxima execucao do mesmo perfil, o comportamento
permanece consistente, dificultando heuristicas de "mesmo bot, sessoes
diferentes".

Uso:
    p = obter_personalidade(profile_id)
    delay = p['delay_entre_cliques_ms']
    if random.random() < p['chance_typo']: ...
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys

logger = logging.getLogger(__name__)


def _base_dir() -> str:
    """Pasta persistente para personalidades. Funciona em dev e em .exe."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath('.')
    pasta = os.path.join(base, 'config', 'personalidades')
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _caminho(profile_id: str) -> str:
    safe = ''.join(c for c in str(profile_id) if c.isalnum() or c in '-_')[:96]
    return os.path.join(_base_dir(), f'{safe}.json')


def _gerar_personalidade_nova() -> dict:
    """Sorteia atributos uma unica vez. Eles ficam fixos no JSON do perfil."""
    return {
        # Velocidade de digitacao (ms entre teclas) — gauss(media, desvio)
        'tecla_media_ms': round(random.uniform(70, 140), 1),
        'tecla_desvio_ms': round(random.uniform(20, 45), 1),
        # Chance de typo por palavra digitada (0.5% a 2.5%)
        'chance_typo': round(random.uniform(0.005, 0.025), 4),
        # Delay entre cliques sequenciais (ms)
        'delay_entre_cliques_ms': random.randint(180, 520),
        # Intensidade do scroll (px medio por evento)
        'scroll_intensidade_px': random.randint(220, 540),
        # Quantas paradas em media o mouse faz antes do clique final (mouse indeciso)
        'mouse_indeciso_paradas': random.choice([0, 1, 1, 2, 2, 3]),
        # Tempo de "leitura" do feed em warm-up (segundos)
        'warmup_feed_seg': random.randint(20, 55),
        # Tendencia a curtir ou nao postagens (0..1)
        'tendencia_like': round(random.uniform(0.15, 0.55), 2),
        # Tempo assistindo Reels no warm-up (segundos)
        'warmup_reels_seg': random.randint(25, 70),
        # Tendencia a curtir Reels (0..1)
        'tendencia_like_reels': round(random.uniform(0.20, 0.50), 2),
        # Tendencia a comentar em Reels (baixa — comportamento natural) (0..1)
        'tendencia_comentar_reels': round(random.uniform(0.05, 0.18), 2),
        # Sementeira aleatoria para qualquer outro uso determinstico
        'seed': random.randint(1, 2**31 - 1),
    }


def obter_personalidade(profile_id) -> dict:
    """Retorna a personalidade salva. Gera e salva se nao existir."""
    if profile_id is None:
        return _gerar_personalidade_nova()
    cam = _caminho(str(profile_id))
    if os.path.exists(cam):
        try:
            with open(cam, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            if isinstance(dados, dict) and 'tecla_media_ms' in dados:
                return dados
        except Exception as exc:
            logger.warning('[Personalidade] %s corrompido: %s', cam, exc)
    nova = _gerar_personalidade_nova()
    try:
        with open(cam, 'w', encoding='utf-8') as f:
            json.dump(nova, f, ensure_ascii=False, indent=2)
        logger.info('[Personalidade] Nova personalidade salva: %s', cam)
    except Exception as exc:
        logger.warning('[Personalidade] Falha ao salvar %s: %s', cam, exc)
    return nova


def atualizar_personalidade(profile_id, patch: dict):
    """Atualiza alguns campos da personalidade (use com moderacao)."""
    if not patch:
        return
    p = obter_personalidade(profile_id)
    p.update({k: v for k, v in patch.items() if k in p})
    try:
        with open(_caminho(str(profile_id)), 'w', encoding='utf-8') as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning('[Personalidade] Falha ao atualizar %s: %s', profile_id, exc)
