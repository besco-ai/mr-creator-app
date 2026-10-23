#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camada de TRADUÇÃO p/ pt-BR do texto das telas (2026-10-13).

Pedido do dono: o fluxo inteiro tem que entender a tela em QUALQUER idioma (EN, VI,
RU, ID, HI…). Os detectores do projeto casam o texto da página contra listas PT
(+EN/ES). Esta camada TRADUZ o texto do PRIMEIRO PLANO (diálogo aberto, senão o
[role=main]) para pt-BR e o devolve SOMADO ao original — assim TODAS as listas PT já
existentes passam a valer em qualquer idioma, sem reescrever cada detector.

Regras de segurança/custo:
  • Só traduz quando a página NÃO está em pt (<html lang>), ou quando pedido à força.
  • Nunca altera o DOM (o tradutor do Chrome reescreve nós de texto e QUEBRA o React/
    cliques) — a tradução é só para LEITURA/decisão.
  • Cache por texto (LRU), intervalo mínimo por driver (reaproveita a última tradução
    entre leituras de polling) e disjuntor de 90s em erro/429.
  • Fail-open: qualquer falha devolve só o texto original (nunca piora o atual).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
import time
import urllib.parse
import urllib.request
from collections import OrderedDict

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: "OrderedDict[str, str]" = OrderedDict()
_CACHE_MAX = 600
_MAX_CHARS = 2500
_DISJUNTOR_ATE = 0.0
_ULTIMA_POR_DRIVER: dict = {}      # id(driver) -> (ts, texto_original, traducao)
_INTERVALO_MIN = 1.5               # s entre traduções NOVAS do mesmo driver

_URL = 'https://translate.googleapis.com/translate_a/single'


def expandir_contracoes(s: str) -> str:
    """"isn't"→"is not", "you'll"→"you will"… (as listas EN têm as duas formas)."""
    s = (s or '').replace('’', "'").replace('‘', "'")
    s = re.sub(r"\bcan't\b", 'cannot', s)
    s = re.sub(r"\bwon't\b", 'will not', s)
    s = re.sub(r"n't\b", ' not', s)
    s = re.sub(r"'ll\b", ' will', s)
    s = re.sub(r"'re\b", ' are', s)
    s = re.sub(r"'ve\b", ' have', s)
    s = re.sub(r"\bit's\b", 'it is', s)
    return s


def normalizar(s: str) -> str:
    """minúsculas, sem acento, contrações expandidas, sem pontuação final, 1 espaço."""
    s = expandir_contracoes((s or '').lower())
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    s = re.sub(r'[\s ]+', ' ', s).strip().strip('.!?:;')
    return s


def _traduzir_rede(texto: str, timeout: float = 5.0, tl: str = 'pt') -> str:
    """Chama o endpoint público do Google Translate (gtx). '' se falhar."""
    global _DISJUNTOR_ATE
    if time.time() < _DISJUNTOR_ATE:
        return ''
    try:
        dados = urllib.parse.urlencode({'q': texto}).encode('utf-8')
        qs = urllib.parse.urlencode({'client': 'gtx', 'sl': 'auto', 'tl': tl, 'dt': 't'})
        req = urllib.request.Request(f'{_URL}?{qs}', data=dados, method='POST', headers={
            'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            js = json.loads(r.read().decode('utf-8', 'replace'))
        partes = js[0] if js and isinstance(js, list) else []
        out = ''.join((p[0] or '') for p in partes if isinstance(p, list) and p)
        return out
    except Exception as e:
        _DISJUNTOR_ATE = time.time() + 90
        logger.warning('[Tradutor] falhou (%s) — disjuntor 90s; seguindo só com o original.', e)
        return ''


def _traduzir_cache(t: str, tl: str) -> str:
    chave = f'{tl}\x00{t}'
    with _LOCK:
        if chave in _CACHE:
            _CACHE.move_to_end(chave)
            return _CACHE[chave]
    tr = (_traduzir_rede(t, tl=tl) or '').lower()
    if tr:
        with _LOCK:
            _CACHE[chave] = tr
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return tr


def traduzir_para_ptbr(texto: str) -> str:
    """Tradução de `texto` (minúsculas) em pt-BR **+ inglês** (+ inglês com contrações
    expandidas), separados por quebra de linha. O inglês entra porque a UI da Meta é
    escrita em EN e localizada a partir dele: a volta para EN tende a reproduzir a
    frase ORIGINAL ("Action required", "My business isn't listed"), que as listas EN
    dos detectores já têm. '' se falhar/vazio."""
    t = (texto or '').strip()
    if not t:
        return ''
    t = t[:_MAX_CHARS]
    with _LOCK:
        if t in _CACHE:
            _CACHE.move_to_end(t)
            return _CACHE[t]
    pt = _traduzir_cache(t, 'pt')
    en = _traduzir_cache(t, 'en')
    partes = [x for x in (pt, en, expandir_contracoes(en) if en else '') if x]
    tr = '\n'.join(dict.fromkeys(partes))
    if tr:
        with _LOCK:
            _CACHE[t] = tr
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return tr


# Texto do PRIMEIRO PLANO: diálogo visível mais ao topo (o fluxo vive em modais), senão
# o [role=main], senão o body. Também devolve o <html lang>.
_JS_PRIMEIRO_PLANO = r"""() => {
    const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return r.width > 120 && r.height > 80 && s.visibility !== 'hidden' && s.display !== 'none'; };
    const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
    let alvo = dl.length ? dl[dl.length - 1] : (document.querySelector('[role="main"]') || document.body);
    return { lang: (document.documentElement.getAttribute('lang') || '').toLowerCase(),
             txt: alvo ? (alvo.innerText || '') : '' };
}"""


def idioma_pagina(driver) -> str:
    try:
        return (driver.evaluate_page(
            "() => (document.documentElement.getAttribute('lang') || '').toLowerCase()") or '')
    except Exception:
        return ''


def precisa_traduzir(lang: str) -> bool:
    """pt* não precisa. Vazio (não deu p/ ler) → não traduz (evita custo à toa)."""
    lang = (lang or '').lower()
    return bool(lang) and not lang.startswith('pt')


def traducao_primeiro_plano(driver, forcar: bool = False) -> str:
    """Tradução pt-BR (minúsculas) do texto em primeiro plano, respeitando o intervalo
    mínimo por driver (entre leituras de polling reaproveita a última). '' se a página
    já está em pt (e não `forcar`) ou se falhou."""
    try:
        info = driver.evaluate_page(_JS_PRIMEIRO_PLANO) or {}
    except Exception:
        return ''
    if not forcar and not precisa_traduzir(info.get('lang', '')):
        return ''
    txt = (info.get('txt') or '').strip()[:_MAX_CHARS]
    if not txt:
        return ''
    chave = id(driver)
    agora = time.time()
    with _LOCK:
        ult = _ULTIMA_POR_DRIVER.get(chave)
        em_cache = txt in _CACHE
    if ult and ult[1] == txt:
        return ult[2]
    if ult and not em_cache and agora - ult[0] < _INTERVALO_MIN:
        return ult[2]          # polling rápido: usa a última (só complementa o original)
    tr = traduzir_para_ptbr(txt)
    if tr:
        with _LOCK:
            _ULTIMA_POR_DRIVER[chave] = (agora, txt, tr)
            if len(_ULTIMA_POR_DRIVER) > 200:
                _ULTIMA_POR_DRIVER.clear()
    return tr


def traduzir_lote(textos: list) -> list:
    """Traduz vários rótulos curtos numa chamada (1 por linha). [] se o nº de linhas
    da resposta não bater (aí o chamador não arrisca casar rótulo errado)."""
    textos = [((t or '').replace('\n', ' ').strip()) for t in textos]
    if not textos:
        return []
    junto = '\n'.join(textos)[:_MAX_CHARS]
    por_idioma = []
    for tl in ('pt', 'en'):
        tr = _traduzir_cache(junto, tl)
        linhas = [l.strip() for l in tr.split('\n')] if tr else []
        if len(linhas) == len(textos):
            por_idioma.append(linhas)
    if not por_idioma:
        return []
    out = []
    for i in range(len(textos)):
        vs = [ling[i] for ling in por_idioma if ling[i]]
        vs += [expandir_contracoes(v) for v in vs]
        out.append('\n'.join(dict.fromkeys(vs)))
    return out


# Marca candidatos clicáveis VISÍVEIS (no diálogo do topo, se houver) com data-gs-trc=i
# e devolve seus rótulos (texto curto ou aria-label).
_JS_CANDIDATOS = r"""(sel) => {
    const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
    document.querySelectorAll('[data-gs-trc]').forEach(e => e.removeAttribute('data-gs-trc'));
    const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
    const raiz = dl.length ? dl[dl.length - 1] : document;
    const out = [], vistos = new Set();
    for (const el of raiz.querySelectorAll(sel)) {
        if (!vis(el)) continue;
        if (el.getAttribute('aria-disabled') === 'true' || el.disabled) continue;
        let t = ((el.innerText || '') + '').trim();
        if (!t) t = ((el.getAttribute('aria-label') || '') + '').trim();
        if (!t || t.length > 80 || t.indexOf('\n') !== -1) continue;
        if (vistos.has(t)) continue;
        vistos.add(t);
        el.setAttribute('data-gs-trc', String(out.length));
        out.push(t);
        if (out.length >= 60) break;
    }
    return out;
}"""

_NEG = ('nao ', 'agora nao', 'cancelar', 'voltar', 'sair', 'excluir', 'remover',
        'no ', 'not now', 'cancel', 'back', 'go back', 'exit', 'delete', 'remove',
        'do not', 'dont', 'leave')


def clicar_por_traducao(driver, alvos_pt, seletor_base=None) -> bool:
    """Fallback de AÇÃO em qualquer idioma: traduz os rótulos clicáveis visíveis para
    pt-BR e clica o que casa um dos `alvos_pt` (mesma lista que o chamador já usa —
    as entradas PT casam a tradução). Só age se a página NÃO está em pt. Ranking
    estrito (exato > começa-com > contém curto) e nunca casa rótulo NEGATIVO
    (Não…/Cancelar/Voltar…) com alvo que não seja ele mesmo negativo."""
    if not precisa_traduzir(idioma_pagina(driver)):
        return False
    alvos = [normalizar(a) for a in (alvos_pt or []) if (a or '').strip()]
    alvos = [a for a in dict.fromkeys(alvos) if a]
    if not alvos:
        return False
    sel = seletor_base or ('button, [role="button"], a, [role="radio"], [role="option"], '
                           '[role="menuitem"], [role="menuitemradio"], [role="tab"], label')
    try:
        rotulos = driver.evaluate_page(_JS_CANDIDATOS, sel) or []
    except Exception:
        return False
    if not rotulos:
        return False
    trads = traduzir_lote(rotulos)
    if not trads:
        return False
    melhor = None  # (rank, len, idx, tr)
    for i, bloco in enumerate(trads):
        # cada rótulo traz variantes (pt / en / en expandido) — basta UMA casar
        for tr in {normalizar(v) for v in (bloco or '').split('\n') if v.strip()}:
            for a in alvos:
                if tr.startswith(_NEG) != a.startswith(_NEG):
                    continue
                if tr == a:
                    rk = 0
                elif tr.startswith(a) and len(tr) <= len(a) + 12:
                    rk = 1
                elif a in tr and len(tr) <= len(a) + 10:
                    rk = 2
                else:
                    continue
                c = (rk, len(tr), i, tr)
                if melhor is None or c[:2] < melhor[:2]:
                    melhor = c
    if not melhor:
        return False
    idx = melhor[2]
    loc = f'[data-gs-trc="{idx}"]'
    try:
        driver.locator(loc).first.click(timeout=5000)
    except Exception:
        try:
            if not driver.evaluate_page(
                    "(s) => { const e = document.querySelector(s); if (!e) return false; e.click(); return true; }", loc):
                return False
        except Exception:
            return False
    logger.info("[Tradutor] clique por TRADUÇÃO: '%s' (≈ '%s')", rotulos[idx][:40], melhor[3][:40])
    return True


def com_traducao(driver, texto: str, forcar: bool = False) -> str:
    """`texto` + '\\n' + tradução pt-BR do primeiro plano (quando a página não é pt).
    Uso: trocar `t = texto_da_pagina` por `t = com_traducao(driver, t)` nos detectores
    que só fazem `'frase pt' in t`. Nunca levanta."""
    try:
        tr = traducao_primeiro_plano(driver, forcar=forcar)
    except Exception:
        tr = ''
    return f'{texto}\n{tr}' if tr else texto
