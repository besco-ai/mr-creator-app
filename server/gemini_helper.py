#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gemini Helper - Motor de IA para Reconhecimento Universal de UI
================================================================
Usa a API do Google Gemini para identificar elementos da interface do Facebook
em QUALQUER idioma, eliminando a dependência de dicionários fixos de tradução.

O Gemini analisa o HTML simplificado da página e retorna seletores CSS
precisos para clicar em botões, links e campos, independente do idioma.
"""

import os
import json
import time
import logging
import re
import hashlib

logger = logging.getLogger(__name__)

# Chave da API Gemini (pode ser sobrescrita via config)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'AIzaSyAIhq-UvGxfD9BO2u8Yi8VbGZWZxgDbhA0')

# Cache de respostas para evitar chamadas repetidas
_cache = {}
_cache_ttl = 300  # 5 minutos

# Rate limiting
_last_call_time = 0
_min_interval = 0.5  # 500ms entre chamadas


def _get_cache_key(prompt_hash):
    return prompt_hash


def _check_cache(key):
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry['time'] < _cache_ttl:
            logger.debug(f"[Gemini] Cache hit: {key[:16]}...")
            return entry['result']
        else:
            del _cache[key]
    return None


def _set_cache(key, result):
    _cache[key] = {'result': result, 'time': time.time()}
    # Limpar cache antigo (max 100 entradas)
    if len(_cache) > 100:
        oldest = min(_cache, key=lambda k: _cache[k]['time'])
        del _cache[oldest]


def _extrair_html_simplificado(driver, max_chars=8000):
    """
    Extrai uma versão simplificada do HTML visível da página para enviar ao Gemini.
    Remove scripts, estilos e atributos desnecessários para reduzir tokens.
    """
    try:
        html = driver.execute_script("""
            function simplify(el, depth) {
                if (depth > 6) return '';
                if (!el || !el.tagName) return '';
                
                var tag = el.tagName.toLowerCase();
                if (['script','style','svg','path','link','meta','noscript','iframe'].includes(tag)) return '';
                
                var rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0 && tag !== 'input') return '';
                
                var attrs = '';
                var important = ['role','aria-label','type','name','placeholder','href','id','class','aria-checked','data-testid','tabindex'];
                for (var i = 0; i < important.length; i++) {
                    var val = el.getAttribute(important[i]);
                    if (val) {
                        // Truncar classes longas
                        if (important[i] === 'class') val = val.substring(0, 60);
                        if (important[i] === 'href') val = val.substring(0, 80);
                        attrs += ' ' + important[i] + '="' + val.replace(/"/g, "'") + '"';
                    }
                }
                
                var text = '';
                for (var c = 0; c < el.childNodes.length; c++) {
                    if (el.childNodes[c].nodeType === 3) {
                        var t = el.childNodes[c].textContent.trim();
                        if (t) text += t + ' ';
                    }
                }
                text = text.trim().substring(0, 100);
                
                var children = '';
                for (var c = 0; c < el.children.length; c++) {
                    children += simplify(el.children[c], depth + 1);
                }
                
                // Pular divs vazias sem atributos úteis
                if (!text && !children && !attrs && ['div','span','section'].includes(tag)) return '';
                
                var result = '<' + tag + attrs + '>';
                if (text) result += text;
                result += children;
                result += '</' + tag + '>';
                
                return result;
            }
            
            var main = document.querySelector('[role="main"]') || document.querySelector('[role="dialog"]') || document.body;
            var html = simplify(main, 0);
            return html.substring(0, 12000);
        """)
        
        if html and len(html) > max_chars:
            html = html[:max_chars]
        
        return html or ''
    except Exception as e:
        logger.warning(f"[Gemini] Erro ao extrair HTML: {e}")
        return ''


def _chamar_gemini(prompt, max_retries=2):
    """
    Chama a API do Gemini com rate limiting e retry.
    """
    global _last_call_time
    
    import requests
    
    # Rate limiting
    elapsed = time.time() - _last_call_time
    if elapsed < _min_interval:
        time.sleep(_min_interval - elapsed)
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 500,
            "topP": 0.8
        }
    }
    
    headers = {"Content-Type": "application/json"}
    
    for attempt in range(max_retries + 1):
        try:
            _last_call_time = time.time()
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                return text.strip()
            elif resp.status_code == 429:
                logger.warning(f"[Gemini] Rate limit, aguardando... (tentativa {attempt+1})")
                time.sleep(2 * (attempt + 1))
            else:
                logger.warning(f"[Gemini] Erro HTTP {resp.status_code}: {resp.text[:200]}")
                if attempt < max_retries:
                    time.sleep(1)
        except requests.exceptions.Timeout:
            logger.warning(f"[Gemini] Timeout (tentativa {attempt+1})")
            if attempt < max_retries:
                time.sleep(1)
        except Exception as e:
            logger.warning(f"[Gemini] Erro: {e}")
            if attempt < max_retries:
                time.sleep(1)
    
    return None


def _parse_json_response(text):
    """Extrai JSON de uma resposta do Gemini que pode conter markdown."""
    if not text:
        return None
    
    # Tentar extrair JSON de blocos de código
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()
    
    # Tentar extrair JSON direto
    try:
        return json.loads(text)
    except:
        # Tentar encontrar o primeiro { ... } ou [ ... ]
        brace_match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(1))
            except:
                pass
    
    return None


# ============================================================================
# FUNÇÕES PÚBLICAS - Identificação de Elementos via Gemini
# ============================================================================

def gemini_encontrar_elemento(driver, descricao_acao, contexto="pagina Facebook"):
    """
    Usa o Gemini para encontrar um elemento na página baseado na descrição da ação.
    
    Args:
        driver: Selenium WebDriver
        descricao_acao: Ex: "botão de configurações e privacidade no menu"
        contexto: Ex: "pagina de configurações do Facebook"
    
    Returns:
        WebElement ou None
    """
    html = _extrair_html_simplificado(driver)
    if not html:
        return None
    
    cache_key = hashlib.md5(f"{descricao_acao}:{html[:500]}".encode()).hexdigest()
    cached = _check_cache(cache_key)
    if cached:
        return _executar_seletor(driver, cached)
    
    prompt = f"""Analise este HTML de uma {contexto} e encontre o elemento para: {descricao_acao}

HTML:
{html}

RESPONDA APENAS com um JSON assim (sem explicação):
{{"selector": "seletor CSS para o elemento", "xpath": "xpath alternativo", "text": "texto visível do elemento"}}

REGRAS:
- O seletor deve ser o mais específico possível
- Se houver role="button" ou tag button, prefira esses
- Se o elemento tem aria-label, use [aria-label="valor"]
- Se tem data-testid, use [data-testid="valor"]
- O xpath deve ser funcional como fallback"""

    resp = _chamar_gemini(prompt)
    result = _parse_json_response(resp)
    
    if result:
        _set_cache(cache_key, result)
        return _executar_seletor(driver, result)
    
    return None


def gemini_encontrar_botao_menu_conta(driver):
    """
    Encontra o botão de menu da conta/perfil no Facebook (o avatar/seta no canto superior direito).
    Funciona em qualquer idioma.
    """
    # Primeiro: tentar seletores universais conhecidos (mais rápido que Gemini)
    seletores_rapidos = [
        '[aria-label="Your profile"] svg',
        '[aria-label][role="img"]',
        'div[role="navigation"] div[role="button"]:last-child',
    ]
    
    for sel in seletores_rapidos:
        try:
            els = driver.find_elements("css selector", sel)
            for el in els:
                if el.is_displayed():
                    return el
        except:
            continue
    
    # Fallback: botão com imagem de perfil no topo direito
    el = driver.execute_script("""
        var nav = document.querySelector('[role="banner"]') || document.querySelector('[role="navigation"]');
        if (!nav) return null;
        var buttons = nav.querySelectorAll('[role="button"], button');
        var rightmost = null;
        var maxX = 0;
        for (var i = 0; i < buttons.length; i++) {
            var rect = buttons[i].getBoundingClientRect();
            if (rect.width > 0 && rect.x > maxX && rect.y < 80) {
                maxX = rect.x;
                rightmost = buttons[i];
            }
        }
        return rightmost;
    """)
    
    if el:
        return el
    
    # Último recurso: Gemini
    return gemini_encontrar_elemento(driver, 
        "botão do menu da conta/perfil no canto superior direito (geralmente um avatar circular ou seta)",
        "barra de navegação do Facebook")


def gemini_encontrar_settings_privacy(driver):
    """
    Encontra a opção 'Configurações e privacidade' / 'Settings & privacy' no menu dropdown.
    """
    el = driver.execute_script("""
        var items = document.querySelectorAll('[role="menuitem"], [role="button"], [role="link"], a, div[tabindex]');
        for (var i = 0; i < items.length; i++) {
            var text = (items[i].innerText || items[i].textContent || '').trim().toLowerCase();
            var label = (items[i].getAttribute('aria-label') || '').toLowerCase();
            // Palavras-chave universais para "configurações/settings" + "privacidade/privacy"
            if ((text.includes('setting') && text.includes('priv')) ||
                (text.includes('configura') && text.includes('priv')) ||
                (text.includes('paramètre') && text.includes('confid')) ||
                (text.includes('einstellung') && text.includes('privat')) ||
                (text.includes('impostazion') && text.includes('priv')) ||
                (text.includes('настройк') && text.includes('конфид')) ||
                (text.includes('pengaturan') && text.includes('priv')) ||
                (text.includes('cài đặt') && text.includes('quyền')) ||
                (text.includes('設定') && text.includes('プライバシー')) ||
                (text.includes('설정') && text.includes('개인')) ||
                (text.includes('设置') && text.includes('隐私')) ||
                (label.includes('setting') && label.includes('priv')) ||
                (label.includes('configura') && label.includes('priv'))) {
                var rect = items[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) return items[i];
            }
        }
        return null;
    """)
    
    if el:
        return el
    
    return gemini_encontrar_elemento(driver,
        "opção 'Configurações e privacidade' ou 'Settings & privacy' no menu dropdown aberto",
        "menu dropdown do Facebook")


def gemini_encontrar_opcao_idioma(driver):
    """
    Encontra a opção 'Idioma' / 'Language' no submenu de configurações.
    """
    el = driver.execute_script("""
        var items = document.querySelectorAll('[role="menuitem"], [role="button"], [role="link"], a, div[tabindex], span');
        for (var i = 0; i < items.length; i++) {
            var text = (items[i].innerText || items[i].textContent || '').trim().toLowerCase();
            // Deve conter APENAS a palavra idioma/language (não "configurações e privacidade")
            if (text.length < 30 && (
                text === 'language' || text === 'idioma' || text === 'langue' ||
                text === 'sprache' || text === 'lingua' || text === 'язык' ||
                text === 'bahasa' || text === 'ngôn ngữ' || text === 'ภาษา' ||
                text === '언어' || text === '语言' || text === '言語' ||
                text === 'wika' || text === 'taal' || text === 'اللغة' ||
                text === 'dil' || text === 'limba' || text === 'jazyk' ||
                text === 'nyelv' || text === 'keel' || text === 'kalba' ||
                text === 'idioma e região' || text === 'language and region' ||
                text.includes('language') || text.includes('idioma') ||
                text.includes('langue') || text.includes('sprache') ||
                text.includes('ngôn ngữ') || text.includes('bahasa')
            )) {
                var rect = items[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    var clickable = items[i].closest('[role="menuitem"], [role="button"], a, [tabindex]');
                    return clickable || items[i];
                }
            }
        }
        return null;
    """)
    
    if el:
        return el
    
    return gemini_encontrar_elemento(driver,
        "opção 'Idioma' ou 'Language' no submenu de configurações",
        "submenu de configurações do Facebook")


def gemini_encontrar_editar_idioma(driver):
    """
    Encontra o botão 'Editar' / 'Edit' na seção de idioma da conta.
    """
    el = driver.execute_script("""
        var main = document.querySelector('[role="main"]') || document.body;
        var buttons = main.querySelectorAll('[role="button"], button, a');
        for (var i = 0; i < buttons.length; i++) {
            var text = (buttons[i].innerText || buttons[i].textContent || '').trim().toLowerCase();
            if (text.length < 20 && (
                text === 'edit' || text === 'editar' || text === 'modifier' ||
                text === 'bearbeiten' || text === 'modifica' || text === 'i-edit' ||
                text === 'sunting' || text === 'chỉnh sửa' || text === 'แก้ไข' ||
                text === '편집' || text === '编辑' || text === '編集' ||
                text === 'düzenle' || text === 'تعديل' || text === 'редактировать' ||
                text === 'editovat' || text === 'szerkesztés' || text === 'redigera'
            )) {
                var rect = buttons[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) return buttons[i];
            }
        }
        return null;
    """)
    
    if el:
        return el
    
    return gemini_encontrar_elemento(driver,
        "botão 'Editar' ou 'Edit' na página de configurações de idioma",
        "página de configurações de idioma do Facebook")


def gemini_encontrar_campo_busca_idioma(driver):
    """
    Encontra o campo de busca/pesquisa no modal de seleção de idioma.
    """
    el = driver.execute_script("""
        // Procurar em dialogs/modais primeiro
        var containers = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
        if (containers.length === 0) containers = [document.body];
        
        for (var c = 0; c < containers.length; c++) {
            var inputs = containers[c].querySelectorAll('input[type="text"], input[type="search"], input:not([type])');
            for (var i = 0; i < inputs.length; i++) {
                var rect = inputs[i].getBoundingClientRect();
                if (rect.width > 50 && rect.height > 0 && !inputs[i].disabled) {
                    var ph = (inputs[i].getAttribute('placeholder') || '').toLowerCase();
                    var label = (inputs[i].getAttribute('aria-label') || '').toLowerCase();
                    // Qualquer input que pareça ser busca de idiomas
                    if (ph.includes('search') || ph.includes('pesquis') || ph.includes('buscar') ||
                        ph.includes('chercher') || ph.includes('suchen') || ph.includes('cerca') ||
                        ph.includes('language') || ph.includes('idioma') || ph.includes('langue') ||
                        ph.includes('bahasa') || ph.includes('wika') || ph.includes('ngôn') ||
                        label.includes('search') || label.includes('pesquis') || label.includes('language') ||
                        label.includes('idioma') || label.includes('langue') || label.includes('bahasa')) {
                        return inputs[i];
                    }
                }
            }
            // Se não encontrou por placeholder, pegar o primeiro input visível no modal
            var inputs2 = containers[c].querySelectorAll('input[type="text"], input:not([type])');
            for (var i = 0; i < inputs2.length; i++) {
                var rect = inputs2[i].getBoundingClientRect();
                if (rect.width > 50 && rect.height > 0 && !inputs2[i].disabled) {
                    return inputs2[i];
                }
            }
        }
        return null;
    """)
    
    return el


def gemini_encontrar_ptbr_opcao(driver):
    """
    Encontra a opção 'Português (Brasil)' na lista de idiomas.
    """
    el = driver.execute_script("""
        var termos = ['Português (Brasil)', 'Portuguese (Brazil)', 'Portugués (Brasil)'];
        
        // Procurar em dialogs primeiro
        var containers = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
        if (containers.length === 0) containers = [document.body];
        
        for (var c = 0; c < containers.length; c++) {
            // Radio buttons
            var radios = containers[c].querySelectorAll('[role="radio"], [role="menuitemradio"], [role="option"], input[type="radio"]');
            for (var i = 0; i < radios.length; i++) {
                var text = (radios[i].textContent || '').trim();
                var parentText = radios[i].parentElement ? (radios[i].parentElement.textContent || '').trim() : '';
                for (var j = 0; j < termos.length; j++) {
                    if (text.includes(termos[j]) || parentText.includes(termos[j])) {
                        return radios[i];
                    }
                }
            }
            
            // Spans e labels
            var elements = containers[c].querySelectorAll('span, label, div, li');
            for (var i = 0; i < elements.length; i++) {
                var text = (elements[i].innerText || elements[i].textContent || '').trim();
                for (var j = 0; j < termos.length; j++) {
                    if (text === termos[j] || text.startsWith(termos[j])) {
                        var clickable = elements[i].closest('[role="radio"], [role="menuitemradio"], [role="option"], [role="listitem"], [tabindex], [role="button"]');
                        if (clickable) return clickable;
                        // Tentar o pai
                        var parent = elements[i].parentElement;
                        if (parent) {
                            var radio = parent.querySelector('[role="radio"], input[type="radio"]');
                            if (radio) return parent;
                        }
                        return elements[i];
                    }
                }
            }
        }
        return null;
    """)
    
    return el


def gemini_encontrar_botao_salvar(driver):
    """
    Encontra o botão 'Salvar' / 'Save' / 'Save Changes' em qualquer idioma.
    """
    el = driver.execute_script("""
        // Procurar em dialogs primeiro, depois no main
        var containers = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
        var searchIn = containers.length > 0 ? containers : [document.querySelector('[role="main"]') || document.body];
        
        for (var c = 0; c < searchIn.length; c++) {
            var buttons = searchIn[c].querySelectorAll('button, [role="button"], div[role="button"]');
            for (var i = 0; i < buttons.length; i++) {
                var text = (buttons[i].innerText || buttons[i].textContent || '').trim().toLowerCase();
                var rect = buttons[i].getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                if (buttons[i].disabled || buttons[i].getAttribute('aria-disabled') === 'true') continue;
                
                if (text === 'save' || text === 'salvar' || text === 'enregistrer' ||
                    text === 'speichern' || text === 'salva' || text === 'guardar' ||
                    text === 'сохранить' || text === '保存' || text === '저장' ||
                    text === 'i-save' || text === 'simpan' || text === 'lưu' ||
                    text === 'opslaan' || text === 'حفظ' || text === 'kaydet' ||
                    text.includes('save change') || text.includes('salvar alter') ||
                    text.includes('enregistrer les') || text.includes('änderungen speich') ||
                    text.includes('i-save ang') || text.includes('simpan perubah') ||
                    text.includes('lưu thay') || text.includes('wijzigingen ops')) {
                    return buttons[i];
                }
            }
            
            // Fallback: botão azul/primário
            var buttons2 = searchIn[c].querySelectorAll('button, [role="button"]');
            for (var i = 0; i < buttons2.length; i++) {
                var rect = buttons2[i].getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                var style = getComputedStyle(buttons2[i]);
                var bg = style.backgroundColor;
                if (bg.includes('24, 119, 242') || bg.includes('0, 100, 224')) {
                    return buttons2[i];
                }
            }
        }
        return null;
    """)
    
    if el:
        return el
    
    return gemini_encontrar_elemento(driver,
        "botão 'Salvar' ou 'Save' ou 'Save Changes' para confirmar a alteração",
        "modal ou página de configurações do Facebook")


def gemini_encontrar_botao_submit(driver):
    """
    Encontra o botão Submit/Enviar no formulário de criação de BM.
    """
    el = driver.execute_script("""
        // 1. Botão type=submit
        var submit = document.querySelector('button[type="submit"]');
        if (submit) {
            var rect = submit.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0 && !submit.disabled) return submit;
        }
        
        // 2. Botão por texto
        var buttons = document.querySelectorAll('button, [role="button"], div[role="button"]');
        var submitTexts = ['submit','enviar','soumettre','einreichen','invia','отправить',
                          '提交','送信','gönder','إرسال','kirim','ส่ง','제출',
                          'isumite','ipadala','gửi','hantar','indienen'];
        for (var i = 0; i < buttons.length; i++) {
            var text = (buttons[i].innerText || '').trim().toLowerCase();
            var rect = buttons[i].getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            if (buttons[i].disabled || buttons[i].getAttribute('aria-disabled') === 'true') continue;
            for (var j = 0; j < submitTexts.length; j++) {
                if (text === submitTexts[j]) return buttons[i];
            }
        }
        
        // 3. Botão azul/primário (último na página = mais provável ser submit)
        var candidates = [];
        for (var i = 0; i < buttons.length; i++) {
            var rect = buttons[i].getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            if (buttons[i].disabled || buttons[i].getAttribute('aria-disabled') === 'true') continue;
            var style = getComputedStyle(buttons[i]);
            var bg = style.backgroundColor;
            if (bg.includes('24, 119, 242') || bg.includes('0, 100, 224') || bg.includes('rgb(24')) {
                candidates.push({el: buttons[i], y: rect.y});
            }
        }
        if (candidates.length > 0) {
            candidates.sort(function(a,b) { return b.y - a.y; });
            return candidates[0].el;
        }
        
        return null;
    """)
    
    return el


def gemini_encontrar_botao_done(driver):
    """
    Encontra o botão Done/Concluir/OK no popup pós-criação de BM.
    """
    el = driver.execute_script("""
        var doneTexts = ['done','concluído','concluir','terminé','fertig','fatto','listo',
                        'готово','完成','完了','bitti','تم','selesai','เสร็จสิ้น','완료',
                        'tapos na','tapos','xong','siap','klaar','tamam',
                        'ok','got it','entendi','compris','verstanden','ho capito',
                        'nakuha ko','mengerti','đã hiểu'];
        
        // Procurar em dialogs primeiro
        var dialogs = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
        for (var d = 0; d < dialogs.length; d++) {
            var buttons = dialogs[d].querySelectorAll('button, [role="button"], div[role="button"]');
            for (var i = 0; i < buttons.length; i++) {
                var text = (buttons[i].innerText || '').trim().toLowerCase();
                var rect = buttons[i].getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                for (var j = 0; j < doneTexts.length; j++) {
                    if (text === doneTexts[j]) return buttons[i];
                }
            }
        }
        
        // Procurar em toda a página
        var allButtons = document.querySelectorAll('button, [role="button"], div[role="button"]');
        for (var i = 0; i < allButtons.length; i++) {
            var text = (allButtons[i].innerText || '').trim().toLowerCase();
            var rect = allButtons[i].getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            for (var j = 0; j < doneTexts.length; j++) {
                if (text === doneTexts[j]) return allButtons[i];
            }
        }
        
        return null;
    """)
    
    return el


def gemini_identificar_pagina(driver):
    """
    Usa Gemini para identificar em que página/estado o Facebook está.
    Retorna: 'feed', 'login', 'settings', 'language_settings', 'business_home', 
             'business_create', 'no_access', 'checkpoint', 'unknown'
    """
    try:
        url = driver.current_url.lower()
        
        # Detecção rápida por URL
        if 'login' in url:
            return 'login'
        if 'checkpoint' in url:
            return 'checkpoint'
        if 'settings' in url and 'language' in url:
            return 'language_settings'
        if 'settings' in url:
            return 'settings'
        if 'business.facebook.com' in url:
            # Verificar se é "sem acesso"
            body = driver.execute_script("return (document.body.innerText || '').substring(0, 2000).toLowerCase();")
            no_access_terms = ["can't access", "cannot access", "não é possível acessar",
                             "hindi ma-access", "no se puede acceder", "walang access",
                             "you don't have access", "você não tem acesso",
                             "tidak dapat mengakses", "không thể truy cập"]
            for term in no_access_terms:
                if term in body:
                    return 'no_access'
            
            if 'create' in url or 'loginpage' in url:
                return 'business_create'
            return 'business_home'
        
        if 'facebook.com' in url:
            # Verificar se está logado
            has_feed = driver.execute_script("return !!document.querySelector('[role=\"feed\"], [role=\"banner\"] [role=\"navigation\"]');")
            if has_feed:
                return 'feed'
            has_login = driver.execute_script("return !!document.querySelector('#email, #pass, input[name=\"email\"]');")
            if has_login:
                return 'login'
            return 'feed'  # Provavelmente logado
        
        return 'unknown'
    except:
        return 'unknown'


def gemini_analisar_e_agir(driver, acao_desejada):
    """
    Função de alto nível: analisa a página e executa uma ação usando Gemini.
    Usado como fallback quando os seletores rápidos falham.
    
    Args:
        driver: Selenium WebDriver
        acao_desejada: Descrição da ação em português
    
    Returns:
        WebElement encontrado ou None
    """
    html = _extrair_html_simplificado(driver, max_chars=6000)
    if not html:
        return None
    
    url = driver.current_url
    
    prompt = f"""Você é um assistente de automação web. Analise o HTML abaixo de uma página ({url}) e encontre o elemento correto para a seguinte ação:

AÇÃO: {acao_desejada}

HTML:
{html}

RESPONDA APENAS com JSON (sem explicação, sem markdown):
{{"selector": "seletor_css", "xpath": "//xpath/alternativo", "text": "texto_visivel_do_elemento", "found": true}}

Se não encontrar, responda:
{{"found": false, "reason": "motivo"}}"""

    resp = _chamar_gemini(prompt)
    result = _parse_json_response(resp)
    
    if result and result.get('found'):
        return _executar_seletor(driver, result)
    
    return None


def _executar_seletor(driver, result):
    """Tenta encontrar elemento usando os seletores retornados pelo Gemini."""
    from server.playwright_compat import By
    
    # Tentar CSS selector
    selector = result.get('selector', '')
    if selector:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in els:
                if el.is_displayed():
                    return el
        except:
            pass
    
    # Tentar XPath
    xpath = result.get('xpath', '')
    if xpath:
        try:
            els = driver.find_elements(By.XPATH, xpath)
            for el in els:
                if el.is_displayed():
                    return el
        except:
            pass
    
    # Tentar por texto
    text = result.get('text', '')
    if text:
        try:
            els = driver.find_elements(By.XPATH, f"//*[contains(text(), '{text}')]")
            for el in els:
                if el.is_displayed():
                    return el
        except:
            pass
    
    return None
