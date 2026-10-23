#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Camada avancada de humanizacao — Playwright
======================================================================
Reune comportamentos que apareciam ausentes ou previsiveis no fluxo
atual: warm-up no feed, mouse indeciso, typos em campos longos com
backspace, cooldown exponencial em falhas em cadeia.

Todas as funcoes sao TOLERANTES A FALHAS — se algo der erro elas
apenas logam e retornam, NUNCA quebram o fluxo principal. A motivacao
e ser um vernizinho de humanizacao em cima do fluxo existente, sem
introduzir novos pontos de falha.

Personalidade: cada funcao aceita opcionalmente o dict da personalidade
(server/personality_profile.py) — quando passado, parametros variam de
acordo com o "jeito" daquele perfil; quando nao, usa defaults sensatos.
"""

from __future__ import annotations

import logging
import math
import random
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Utilidades baseicas ─────────────────────────────────────────────────────

def _gauss(media: float, desvio: float, lo: float, hi: float) -> float:
    v = random.gauss(media, desvio)
    return max(lo, min(hi, v))


def _short_sleep(min_ms=80, max_ms=220):
    time.sleep(random.uniform(min_ms / 1000.0, max_ms / 1000.0))


# ── Warm-up no feed ─────────────────────────────────────────────────────────

def aquecer_perfil(driver, personalidade: Optional[Dict[str, Any]] = None,
                   duracao_seg: Optional[int] = None,
                   callback_status: Optional[Callable[[str], None]] = None) -> bool:
    """Simula um humano que abriu o Facebook e fica navegando ANTES de
    ir direto para o Business Suite.

    O que faz:
      * Navega para o feed (https://www.facebook.com/)
      * Aguarda 2-4s carregar
      * Faz scroll suave por N segundos (mistura de baixo/cima)
      * Hover ocasional em posts
      * Eventualmente curte 1-2 posts (apenas se a personalidade tender a)
      * Volta para o topo antes de devolver o controle

    Sempre retorna True/False — qualquer erro vira False e e logado.
    """
    if driver is None:
        return False

    try:
        p = personalidade or {}
        # `warmup_feed_seg` pode vir como INT (personality_profile) OU como
        # RANGE [min, max] (ex.: [3, 8], setado no fluxo de criação de BM). Antes o
        # int() direto explodia com a lista ("int() argument ... not 'list'") e o
        # aquecimento era pulado. Aceita os dois formatos.
        _wf = (duracao_seg if duracao_seg is not None
               else p.get('warmup_feed_seg', random.randint(20, 45)))
        if isinstance(_wf, (list, tuple)) and _wf:
            _wf = (random.randint(int(_wf[0]), int(_wf[-1]))
                   if len(_wf) >= 2 else _wf[0])
        try:
            duracao = int(_wf)
        except Exception:
            duracao = random.randint(20, 45)
        if duracao <= 0:
            return True
        scroll_px = int(p.get('scroll_intensidade_px', random.randint(220, 540)))
        tend_like = float(p.get('tendencia_like', 0.25))

        if callback_status:
            callback_status(f'🟢 Aquecendo perfil ({duracao}s no feed)...')

        try:
            driver.goto('https://www.facebook.com/', timeout=20000)
        except Exception:
            driver.goto('https://www.facebook.com/', timeout=30000)
        _short_sleep(1800, 3500)

        inicio = time.time()
        ja_curtiu = 0
        max_curtidas = 1 if tend_like < 0.35 else 2

        while time.time() - inicio < duracao:
            try:
                direcao = 1 if random.random() < 0.85 else -1
                delta = int(_gauss(scroll_px, scroll_px * 0.35,
                                   scroll_px * 0.3, scroll_px * 1.6)) * direcao
                driver.mouse.wheel(0, delta)
            except Exception:
                pass
            _short_sleep(900, 2800)

            # Eventual hover em um elemento aleatorio (feed posts)
            if random.random() < 0.35:
                try:
                    el = driver.locator('div[role="article"]').first
                    if el and el.count() > 0:
                        try:
                            el.hover(timeout=1500)
                        except Exception:
                            pass
                except Exception:
                    pass

            # Eventual like
            if ja_curtiu < max_curtidas and random.random() < (tend_like / 3):
                try:
                    botoes_curtir = driver.locator(
                        'div[aria-label="Curtir"], div[aria-label="Like"]'
                    )
                    n = botoes_curtir.count()
                    if n > 0:
                        idx = random.randint(0, min(n - 1, 4))
                        botao = botoes_curtir.nth(idx)
                        try:
                            botao.click(timeout=1500)
                            ja_curtiu += 1
                            _short_sleep(600, 1400)
                        except Exception:
                            pass
                except Exception:
                    pass

            # Pausa de "leitura"
            if random.random() < 0.18:
                time.sleep(random.uniform(1.4, 3.0))

        # Volta ao topo para nao deixar a pagina rolada
        try:
            driver.mouse.wheel(0, -99999)
        except Exception:
            pass
        _short_sleep(400, 900)

        if callback_status:
            callback_status('🟢 Aquecimento concluido')
        return True
    except Exception as exc:
        logger.warning('[Humanizacao] Aquecimento falhou (ignorado): %s', exc)
        return False


# ── Warm-up assistindo Reels ────────────────────────────────────────────────

# Comentários curtos, positivos e naturais (em pt — neutros o suficiente)
_COMENTARIOS_REELS = [
    'top', 'muito bom', 'gostei', 'show', 'massa', 'legal', 'curti',
    'sensacional', 'demais', 'perfeito', 'maravilhoso', 'que vídeo bom',
    'adorei', 'incrível', 'kkk bom', 'top demais', 'amei',
]

# aria-labels de "Curtir" em vários idiomas (no warm-up o idioma do perfil
# ainda não foi alterado, então a UI pode estar em qualquer língua).
_LIKE_LABELS = [
    'Like', 'Curtir', 'Gostar', 'Me gusta', "J'aime", 'Mi piace',
    'Gefällt mir', 'Suka', 'Thích', 'Нравится', 'いいね！', 'いいね', '赞',
    '點讚', '讚', '좋아요', 'أعجبني', 'ชอบ', 'Beğen',
]
_COMMENT_LABELS = [
    'Comment', 'Comentar', 'Comentário', 'Kommentar', 'Commenter',
    'Commenta', 'Bình luận', 'Komentar', 'Комментировать', 'コメント',
    '评论', '留言', '댓글', 'تعليق', 'แสดงความคิดเห็น', 'Yorum yap', 'Escribe un comentario',
]


def _curtir_reel_atual(driver) -> bool:
    """Curte o reel que está em foco (botão 'Curtir' visível mais próximo do
    centro da tela), procurando o aria-label em vários idiomas. Best-effort."""
    try:
        clicou = driver.evaluate_page(
            """
            (labels) => {
                function vis(el){
                    var r = el.getBoundingClientRect();
                    var s = getComputedStyle(el);
                    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'
                        && r.top >= -20 && r.bottom <= window.innerHeight + 60;
                }
                var lset = labels.map(function(x){return x.toLowerCase();});
                var els = document.querySelectorAll('[aria-label]');
                var alvo = null, melhor = 1e9, cy = window.innerHeight/2;
                for (var i=0;i<els.length;i++){
                    var el = els[i];
                    var al = (el.getAttribute('aria-label')||'').trim().toLowerCase();
                    if (lset.indexOf(al) === -1) continue;
                    if (el.getAttribute('aria-pressed') === 'true') continue; // já curtido
                    if (!vis(el)) continue;
                    var r = el.getBoundingClientRect();
                    var d = Math.abs((r.top+r.bottom)/2 - cy);
                    if (d < melhor){ melhor = d; alvo = el; }
                }
                if (alvo){ alvo.click(); return true; }
                return false;
            }
            """,
            _LIKE_LABELS,
        )
        return bool(clicou)
    except Exception:
        return False


def _comentar_reel_atual(driver) -> bool:
    """Comenta no reel atual com um texto curto e positivo. Abre a caixa de
    comentário se necessário. Best-effort e tolerante a falhas."""
    try:
        texto = random.choice(_COMENTARIOS_REELS)

        def _tem_caixa():
            try:
                loc = driver.locator('div[contenteditable="true"][role="textbox"]')
                return loc, loc.count()
            except Exception:
                return None, 0

        box, n = _tem_caixa()
        if n == 0:
            # Abrir via botão "Comentar" (aria-label multi-idioma)
            try:
                aberto = driver.evaluate_page(
                    """
                    (labels) => {
                        function vis(el){var r=el.getBoundingClientRect();var s=getComputedStyle(el);
                          return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';}
                        var lset = labels.map(function(x){return x.toLowerCase();});
                        var els = document.querySelectorAll('[aria-label]');
                        for (var i=0;i<els.length;i++){
                            var al=(els[i].getAttribute('aria-label')||'').trim().toLowerCase();
                            if (lset.indexOf(al)!==-1 && vis(els[i])){ els[i].click(); return true; }
                        }
                        return false;
                    }
                    """,
                    _COMMENT_LABELS,
                )
            except Exception:
                aberto = False
            if aberto:
                _short_sleep(1100, 2200)
                box, n = _tem_caixa()

        if n == 0:
            return False

        alvo = box.first
        try:
            alvo.click(timeout=2000)
        except Exception:
            pass
        _short_sleep(300, 700)

        try:
            driver.keyboard.type(texto, delay=random.randint(55, 140))
        except Exception:
            try:
                alvo.type(texto, delay=80)
            except Exception:
                return False
        _short_sleep(400, 900)
        try:
            driver.keyboard.press('Enter')
        except Exception:
            return False
        return True
    except Exception:
        return False


def assistir_reels(driver, personalidade: Optional[Dict[str, Any]] = None,
                   duracao_seg: Optional[int] = None,
                   callback_status: Optional[Callable[[str], None]] = None) -> bool:
    """Simula um humano assistindo Reels do Facebook DEPOIS do warm-up no feed.

    Comportamento ALEATÓRIO/humanizado (para não ficar robotizado):
      * Abre /reels/ e assiste por um tempo TOTAL aleatório
      * Em cada reel, dedica um tempo de atenção aleatório — assiste alguns com
        atenção, pula outros rapidamente
      * Curte alguns de forma natural (probabilidade da personalidade)
      * Comenta poucos, texto curto e positivo (probabilidade BAIXA)
      * Avança para o próximo reel (mistura de seta e scroll)

    Sempre tolerante a falhas — qualquer erro é logado e ignorado.
    """
    if driver is None:
        return False
    try:
        p = personalidade or {}
        duracao = int(duracao_seg if duracao_seg is not None
                      else p.get('warmup_reels_seg', random.randint(25, 70)))
        if duracao <= 0:
            return True
        tend_like = float(p.get('tendencia_like_reels', 0.30))
        tend_coment = float(p.get('tendencia_comentar_reels', 0.10))

        if callback_status:
            callback_status(f'🎬 Aquecendo com Reels ({duracao}s)...')

        navegou = False
        for url in ('https://www.facebook.com/reels/', 'https://www.facebook.com/reel/'):
            try:
                driver.goto(url, timeout=25000)
                navegou = True
                break
            except Exception:
                continue
        if not navegou:
            return False
        _short_sleep(2500, 4500)

        inicio = time.time()
        curtidas = comentarios = reels_vistos = 0
        max_curtidas = random.randint(1, 3)
        max_comentarios = 1 if tend_coment < 0.12 else 2

        while time.time() - inicio < duracao:
            reels_vistos += 1

            # Alguns reels são "pulados" (atenção curta), outros assistidos
            pula = random.random() < 0.35
            atencao = random.uniform(1.2, 3.5) if pula else random.uniform(4.0, 12.0)
            restante = duracao - (time.time() - inicio)
            if restante <= 0:
                break
            atencao = min(atencao, restante)

            # "Assistir": micro-pausas e movimentos ocasionais do mouse
            fim_reel = time.time() + atencao
            while time.time() < fim_reel:
                time.sleep(random.uniform(0.6, 1.4))
                if random.random() < 0.25:
                    try:
                        driver.mouse.move(random.randint(420, 1000),
                                          random.randint(250, 700))
                    except Exception:
                        pass

            # Curtir alguns (apenas os assistidos com atenção)
            if (not pula) and curtidas < max_curtidas and random.random() < tend_like:
                if _curtir_reel_atual(driver):
                    curtidas += 1
                    _short_sleep(600, 1600)

            # Comentar poucos (raro, natural)
            if (not pula) and comentarios < max_comentarios and random.random() < tend_coment:
                if _comentar_reel_atual(driver):
                    comentarios += 1
                    _short_sleep(1000, 2200)

            # Avançar para o próximo reel
            try:
                if random.random() < 0.6:
                    driver.keyboard.press('ArrowDown')
                else:
                    driver.mouse.wheel(0, random.randint(700, 1200))
            except Exception:
                try:
                    driver.mouse.wheel(0, 900)
                except Exception:
                    pass
            _short_sleep(700, 1800)

        if callback_status:
            callback_status(f'🎬 Reels concluído ({reels_vistos} reels, {curtidas} curtidas)')
        logger.info('[Humanizacao] Reels: %s vistos, %s curtidas, %s comentarios',
                    reels_vistos, curtidas, comentarios)
        return True
    except Exception as exc:
        logger.warning('[Humanizacao] Reels falhou (ignorado): %s', exc)
        return False


# ── Mouse indeciso ──────────────────────────────────────────────────────────

def hover_indeciso_antes_de_clicar(driver, seletor_alvo: str,
                                   personalidade: Optional[Dict[str, Any]] = None,
                                   seletores_distratores: Optional[List[str]] = None) -> bool:
    """Move o mouse por 1-3 elementos "vizinhos" antes do clique final.

    Recebe um seletor CSS de destino e (opcional) seletores distratores.
    Se nao receber distratores, usa heuristica generica (botoes/links visiveis
    na pagina). Toda a coreografia e best-effort — em erro, simplesmente
    nao faz nada e retorna False.
    """
    if not driver or not seletor_alvo:
        return False
    try:
        p = personalidade or {}
        paradas = int(p.get('mouse_indeciso_paradas', random.choice([0, 1, 1, 2])))
        if paradas <= 0:
            return True

        distratores = seletores_distratores or [
            'button:visible', 'a:visible',
            '[role="button"]:visible', '[role="link"]:visible',
        ]
        for _ in range(paradas):
            sel = random.choice(distratores)
            try:
                loc = driver.locator(sel)
                if loc.count() > 0:
                    idx = random.randint(0, min(loc.count() - 1, 6))
                    try:
                        loc.nth(idx).hover(timeout=900)
                    except Exception:
                        pass
            except Exception:
                pass
            _short_sleep(120, 380)
        # Pequeno hover no alvo antes do clique propriamente
        try:
            driver.locator(seletor_alvo).first.hover(timeout=1200)
        except Exception:
            pass
        _short_sleep(150, 360)
        return True
    except Exception as exc:
        logger.debug('[Humanizacao] hover indeciso falhou: %s', exc)
        return False


# ── Typo + Backspace ────────────────────────────────────────────────────────

# Mapa simples de teclas adjacentes (QWERTY) para typos realistas
_VIZINHAS = {
    'a': 'sqwz', 'b': 'vghn', 'c': 'xdfv', 'd': 'serfcx', 'e': 'wsdr',
    'f': 'drtgvc', 'g': 'ftyhbv', 'h': 'gyujnb', 'i': 'ujko', 'j': 'huikmn',
    'k': 'jiolm', 'l': 'kop', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp',
    'p': 'ol', 'q': 'wa', 'r': 'edft', 's': 'awedxz', 't': 'rfgy',
    'u': 'yhji', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghu',
    'z': 'asx', '0': '9', '1': '2', '2': '13', '3': '24', '4': '35',
    '5': '46', '6': '57', '7': '68', '8': '79', '9': '80',
}


def _vizinha_de(c: str) -> str:
    base = c.lower()
    opts = _VIZINHAS.get(base)
    if not opts:
        return c
    sub = random.choice(opts)
    return sub.upper() if c.isupper() else sub


def digitar_humano_com_typos(elemento, texto: str,
                             personalidade: Optional[Dict[str, Any]] = None) -> bool:
    """Digita `texto` no `elemento` (locator do Playwright) imitando um
    humano que ocasionalmente erra e corrige com Backspace.

    Padrao seguro: tenta usar `elemento.press(...)` para cada tecla.
    Se isso falhar (ex.: elemento nao aceita keyboard direto), faz
    fallback para `elemento.type(texto)` sem typos.
    """
    if not elemento or not texto:
        return False
    p = personalidade or {}
    media = float(p.get('tecla_media_ms', 90))
    desvio = float(p.get('tecla_desvio_ms', 30))
    chance_typo = float(p.get('chance_typo', 0.012))

    try:
        try:
            elemento.click(timeout=2500)
        except Exception:
            pass

        for c in texto:
            # Eventualmente comete um typo
            if c.isalpha() and random.random() < chance_typo:
                errado = _vizinha_de(c)
                try:
                    elemento.press(errado, delay=_gauss(media, desvio, 30, 250))
                except Exception:
                    elemento.type(errado, delay=int(_gauss(media, desvio, 30, 250)))
                # micro-pausa de "percebeu o erro"
                time.sleep(random.uniform(0.10, 0.30))
                try:
                    elemento.press('Backspace', delay=_gauss(media, desvio, 30, 200))
                except Exception:
                    elemento.type('\b')
                time.sleep(random.uniform(0.04, 0.12))

            # Tecla "correta"
            try:
                elemento.press(c, delay=_gauss(media, desvio, 30, 250))
            except Exception:
                # fallback: type unico caractere
                try:
                    elemento.type(c, delay=int(_gauss(media, desvio, 30, 250)))
                except Exception:
                    return False
        return True
    except Exception as exc:
        logger.debug('[Humanizacao] digitacao falhou (fallback type): %s', exc)
        try:
            elemento.type(texto, delay=int(media))
            return True
        except Exception:
            return False


# ── Cooldown exponencial em falhas em cadeia ────────────────────────────────

class CooldownEmCadeia:
    """Backoff exponencial baseado em falhas consecutivas.

    Reset automatico em sucesso. Ate 5 falhas em cadeia, espera cresce
    de ~20s para ~10min e adiciona jitter aleatorio (+-30%).
    """

    BASES = [0, 20, 60, 180, 360, 600]  # segundos por nivel
    JITTER = 0.30

    def __init__(self):
        self.consecutivas = 0

    def registrar_sucesso(self):
        if self.consecutivas > 0:
            logger.info('[Cooldown] reset (apos %d falha(s))', self.consecutivas)
        self.consecutivas = 0

    def registrar_falha(self):
        self.consecutivas += 1

    def calcular_espera_seg(self) -> float:
        if self.consecutivas <= 0:
            return 0.0
        nivel = min(self.consecutivas, len(self.BASES) - 1)
        base = self.BASES[nivel]
        jitter = random.uniform(-self.JITTER, self.JITTER)
        return max(0.0, base * (1 + jitter))

    def aplicar_se_necessario(self, callback_status=None):
        espera = self.calcular_espera_seg()
        if espera <= 0:
            return
        msg = (f'⏸ Pausa anti-bloqueio: {espera:.0f}s '
               f'(falhas em cadeia: {self.consecutivas})')
        if callback_status:
            try:
                callback_status(msg)
            except Exception:
                pass
        logger.info('[Cooldown] %s', msg)
        # Dorme em janelas curtas para responder a cancelamento externo
        restante = espera
        while restante > 0:
            t = min(restante, 5)
            time.sleep(t)
            restante -= t
