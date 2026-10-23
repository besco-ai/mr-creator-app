#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Capturador de TELAS DESCONHECIDAS
=================================
Quando a máquina de estados (login / OAuth embedded signup / Central de Segurança)
NÃO consegue identificar a tela atual, este módulo salva um SNAPSHOT completo da
tela: URL, título, texto visível, botões e inputs visíveis (com seletores) num
arquivo JSONL + um screenshot PNG.

Objetivo: mapear sistematicamente CADA novo layout/tela do Facebook para
transformá-lo em handler determinístico — sem depender de IA em runtime. Nenhum
layout novo escapa sem ser logado.

Deduplica por ASSINATURA (path da URL + textos dos botões) para não repetir a
mesma tela. É BEST-EFFORT: nunca lança exceção para o chamador.

Saída: <RUNTIME_DIR>/telas_desconhecidas/telas_desconhecidas.jsonl + tela_<sig>.png
"""

import os
import json
import hashlib
import logging

logger = logging.getLogger(__name__)

# Dedup em memória nesta execução (evita reescrever a mesma tela repetidamente).
_ASSINATURAS_VISTAS = set()


def _pasta_capturas():
    try:
        from server.backend import RUNTIME_DIR
        base = RUNTIME_DIR
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pasta = os.path.join(base, 'telas_desconhecidas')
    try:
        os.makedirs(pasta, exist_ok=True)
    except Exception:
        pass
    return pasta


def _js(driver, script):
    """Executa JS no driver, compatível com Playwright (evaluate_page) E Selenium
    (execute_script)."""
    try:
        ep = getattr(driver, 'evaluate_page', None)
        if ep:
            return ep(script)
    except Exception:
        pass
    try:
        es = getattr(driver, 'execute_script', None)
        if es:
            # Selenium espera 'return ...;' — adapta a arrow function.
            return es("return (%s)();" % script)
    except Exception:
        pass
    return None


_JS_EXTRAIR = r"""() => {
    const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
        const s=getComputedStyle(e);
        return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none' && s.opacity!=='0'; };
    const norm = s => (s||'').replace(/\s+/g,' ').trim();
    // Texto visível: folhas (sem filhos) com texto curto — headings, labels, etc.
    const textos = [];
    document.querySelectorAll('h1,h2,h3,h4,strong,p,label,span,div').forEach(e=>{
        if (!vis(e)) return;
        const t = norm(e.innerText);
        if (t && t.length>0 && t.length<160 && !e.querySelector('*')) textos.push(t);
    });
    // Botões / clicáveis visíveis (texto + seletor estável)
    const botoes = [];
    document.querySelectorAll('button,[role="button"],a[role="button"],[role="radio"],[role="option"],input[type="submit"]').forEach(e=>{
        if (!vis(e)) return;
        const t = norm(e.innerText || e.value || e.getAttribute('aria-label') || '');
        if (!t) return;
        const sel = e.tagName.toLowerCase()
            + (e.id ? ('#'+e.id) : '')
            + (e.getAttribute('data-testid') ? ('[data-testid="'+e.getAttribute('data-testid')+'"]') : '')
            + (e.getAttribute('role') ? ('[role="'+e.getAttribute('role')+'"]') : '');
        botoes.push({texto: t.slice(0,90), seletor: sel});
    });
    // Inputs visíveis (rótulo + se está preenchido)
    const inputs = [];
    document.querySelectorAll('input,textarea,[role="combobox"]').forEach(e=>{
        if (!vis(e)) return;
        inputs.push({
            rotulo: norm(e.getAttribute('aria-label') || e.placeholder || ''),
            tipo: (e.type || e.getAttribute('role') || 'text'),
            preenchido: !!(e.value && e.value.length)
        });
    });
    const tset = [...new Set(textos)].slice(0, 40);
    return { titulo: document.title || '', textos: tset,
             botoes: botoes.slice(0, 30), inputs: inputs.slice(0, 20) };
}"""


def salvar_diagnostico(nome, dados, tirar_screenshot=None):
    """Dump GENÉRICO de diagnóstico (sem dedup, sempre escreve). Usado para
    capturar a estrutura exata de um elemento problemático (ex.: a combobox de
    Categoria que não abriu) e poder criar/ajustar o handler determinístico.

    `nome`  -> prefixo do arquivo (ex.: 'categoria_outro').
    `dados` -> dict serializável (será gravado como JSON).
    `tirar_screenshot` -> driver opcional; se passado, salva PNG ao lado.
    BEST-EFFORT — nunca propaga exceção."""
    try:
        pasta = _pasta_capturas()
        try:
            with open(os.path.join(pasta, f'diagnostico_{nome}.jsonl'),
                      'a', encoding='utf-8') as fh:
                fh.write(json.dumps(dados, ensure_ascii=False) + '\n')
        except Exception:
            pass
        if tirar_screenshot is not None:
            png = os.path.join(pasta, f'diagnostico_{nome}.png')
            try:
                if getattr(tirar_screenshot, 'save_screenshot', None):
                    tirar_screenshot.save_screenshot(png)
                elif getattr(tirar_screenshot, '_current_page', None):
                    tirar_screenshot._current_page.screenshot(path=png)
            except Exception:
                pass
        logger.warning("[Diagnostico] '%s' salvo em telas_desconhecidas/", nome)
    except Exception as e:
        logger.debug("[Diagnostico] falha ao salvar '%s': %s", nome, e)


def capturar_tela_desconhecida(driver, contexto='', motivo='tela_nao_identificada'):
    """Salva um snapshot da tela atual (URL + texto + botões + inputs) em JSONL e
    um screenshot PNG. Deduplica por assinatura. Retorna o dict salvo ou None.
    BEST-EFFORT — nunca propaga exceção."""
    try:
        # URL (compatível Playwright/Selenium)
        url = ''
        try:
            url = (getattr(driver, 'current_url', '') or '')
        except Exception:
            url = ''
        if not url:
            try:
                url = _js(driver, "() => location.href") or ''
            except Exception:
                url = ''

        dados = _js(driver, _JS_EXTRAIR) or {}
        botoes = dados.get('botoes', []) or []
        textos = dados.get('textos', []) or []

        # Assinatura: path da URL (sem query) + textos dos botões.
        path = (url.split('?', 1)[0] or '').lower()
        chave = path + '|' + '|'.join(sorted(b.get('texto', '').lower() for b in botoes))
        assinatura = hashlib.md5(chave.encode('utf-8', 'ignore')).hexdigest()[:12]
        if assinatura in _ASSINATURAS_VISTAS:
            return None
        _ASSINATURAS_VISTAS.add(assinatura)

        registro = {
            'assinatura': assinatura,
            'contexto': contexto,
            'motivo': motivo,
            'url': url,
            'titulo': dados.get('titulo', ''),
            'textos': textos,
            'botoes': botoes,
            'inputs': dados.get('inputs', []),
        }
        pasta = _pasta_capturas()

        # Screenshot (Selenium save_screenshot OU Playwright page.screenshot)
        png = os.path.join(pasta, f'tela_{assinatura}.png')
        try:
            if getattr(driver, 'save_screenshot', None):
                driver.save_screenshot(png)
                registro['screenshot'] = png
            elif getattr(driver, '_current_page', None):
                driver._current_page.screenshot(path=png)
                registro['screenshot'] = png
            else:
                registro['screenshot'] = ''
        except Exception:
            registro['screenshot'] = ''

        # Append no JSONL
        try:
            with open(os.path.join(pasta, 'telas_desconhecidas.jsonl'),
                      'a', encoding='utf-8') as fh:
                fh.write(json.dumps(registro, ensure_ascii=False) + '\n')
        except Exception:
            pass

        logger.warning("[CapturaTela] TELA DESCONHECIDA (%s | %s) capturada: %s | botões=%s",
                       contexto, motivo, path,
                       [b.get('texto') for b in botoes][:6])
        return registro
    except Exception as e:
        logger.debug("[CapturaTela] falha ao capturar tela: %s", e)
        return None
