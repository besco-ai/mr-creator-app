#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""""Automação Facebook - v10 ANTI-DETECÇÃO 2026
====================================================
MELHORIAS v10:
- ANTI-DETECÇÃO: Simula 100% comportamento humano real
- MOVIMENTOS DE MOUSE: Curvas Bézier não-lineares
- DELAYS HUMANIZADOS: Distribuição Gaussiana natural
- DIGITAÇÃO REALISTA: Velocidade variável por caractere
- STEALTH JS: Mascaramento de webdriver/automation
- HEADERS REALISTAS: User-Agent rotativo + headers naturais
- DETECÇÃO DE CAPTCHA: Identifica e aborta se detectado
- COMPORTAMENTO NATURAL: Scroll, hover, cliques aleatórios
"""

import time
import random
import re
import logging
from server.playwright_compat import (
    conectar_playwright, ChromeOptions, Service, By, Keys, ActionChains,
    WebDriverWait, EC, TimeoutException, NoSuchElementException,
    ElementClickInterceptedException, StaleElementReferenceException,
    WebDriverException,
)
from server.config_manager import ConfigManager
from server.block_detector import BlockDetector
from server.marca import URL_MAIL as _URL_MAIL_DA_MARCA

logger = logging.getLogger(__name__)

# Inicializa o gerenciador de configurações globalmente
config_manager = ConfigManager()

# ============================================================================
# MODO SEGUNDO PLANO
# ============================================================================
# Quando True, a automação NÃO rouba o foco do sistema: não traz a janela do
# navegador para frente (SetForegroundWindow), não envia teclas/cliques reais
# (pyautogui / Win32 keybd_event) e não move o mouse físico. Tudo é feito via
# DOM/CDP, deixando o usuário trabalhar no PC ao mesmo tempo. O login funciona
# mesmo assim porque os campos são preenchidos e o botão é clicado via JS, que
# atravessa a bolha nativa "Fazer login como ..." sem precisar de foco do SO.
EXECUTAR_EM_SEGUNDO_PLANO = True

# MODO PARALELO: quando há 2+ navegadores simultâneos, NENHUMA ação de nível-SO
# (SetForegroundWindow / ESC real via Win32) pode ser usada — elas agem na janela
# em FOCO do sistema e, com várias janelas de título igual ("Facebook"), acabam
# focando/ESCando a janela do worker ERRADO (corrompe o fluxo do outro perfil).
# Em paralelo, tudo é por DOM/CDP (per-driver, isolado). Setado pelo backend.
_MODO_PARALELO = False


def set_modo_paralelo(ativo):
    """Liga/desliga o modo paralelo (chamado pelo backend quando simultâneos>1).
    Em paralelo, as ações de nível-SO (foco/ESC real) são DESLIGADAS para não
    interferir na janela de outro worker."""
    global _MODO_PARALELO
    _MODO_PARALELO = bool(ativo)


# Importar Gemini Helper (fallback)
try:
    from server.gemini_helper import (
        gemini_encontrar_elemento,
        gemini_encontrar_campo_busca_idioma,
        gemini_encontrar_ptbr_opcao,
        gemini_encontrar_botao_salvar,
        gemini_encontrar_botao_submit,
        gemini_encontrar_botao_done,
        gemini_identificar_pagina,
        gemini_analisar_e_agir
    )
    _TEM_GEMINI = True
    logger.info("[Gemini] Motor de IA carregado com sucesso")
except ImportError as e:
    _TEM_GEMINI = False

# Importar Human Behavior (Anti-Deteccao)
try:
    from server.human_behavior import (
        HumanBehaviorSimulator,
        HumanDelays,
        HumanMouseMovement,
        HumanTyping,
        HumanNavigation,
        HumanBrowserProfile,
        CaptchaDetection
    )
    _TEM_HUMAN_BEHAVIOR = True
    logger.info("[Anti-Deteccao] Sistema de comportamento humano carregado com sucesso")
except ImportError as e:
    _TEM_HUMAN_BEHAVIOR = False
    logger.warning(f"[Anti-Deteccao] Nao disponivel: {e}")
    class HumanDelays:
        @staticmethod
        def short_delay(min_s=0.1, max_s=0.5):
            time.sleep(random.uniform(min_s, max_s))
        @staticmethod
        def micro_delay(min_ms=10, max_ms=50):
            time.sleep(random.uniform(min_ms, max_ms) / 1000)
    logger.warning(f"[Gemini] Não disponível: {e}")


# ============================================================================
# DELAYS OTIMIZADOS - Rápidos mas naturais
# ============================================================================

def _delay(min_s=0.1, max_s=0.3):
    """Delay mínimo para estabilidade."""
    time.sleep(random.uniform(min_s, max_s))

def _delay_medio(min_s=0.5, max_s=1.2):
    """Delay médio para transições de página."""
    time.sleep(random.uniform(min_s, max_s))

def _delay_pagina(min_s=1.5, max_s=3.0):
    """Delay para carregamento de página."""
    time.sleep(random.uniform(min_s, max_s))

def _delay_digitacao():
    """Delay entre teclas."""
    time.sleep(random.uniform(0.01, 0.04))


# ============================================================================
# ESPERA INTELIGENTE - Substitui delays fixos
# ============================================================================

def _esperar_pagina_carregar(driver, timeout=10):
    """Espera a página carregar completamente."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except:
        pass


def _pagina_estatica_pronta(driver, timeout=20, settle=1.2):
    """FLUXO RIGOROSO: espera a página carregar 100% E ficar ESTÁTICA (sem
    mudança relevante no DOM por `settle`s) ANTES de ler frases/capturar seletores
    /clicar. É mais rápido que um sleep fixo quando a página carrega rápido, e
    mais seguro quando está lenta (com F5 automático se travar). Reaproveita o
    PageStateManager (que já sai NA HORA se o navegador foi fechado). Retorna True
    se estabilizou; segue best-effort no timeout."""
    try:
        from server.page_state_manager import PageStateManager
        return bool(PageStateManager.wait_until_stable(
            driver, timeout=timeout, settle_time=settle,
            f5_after=max(15, int(timeout * 0.6)), callback_status=None))
    except Exception:
        _delay_pagina(1.5, 2.5)
        return True

def _esperar_elemento(driver, by, valor, timeout=10):
    """Espera um elemento estar presente e visível."""
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, valor))
        )
    except TimeoutException:
        return None

def _esperar_clicavel(driver, by, valor, timeout=10):
    """Espera um elemento estar clicável."""
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, valor))
        )
    except TimeoutException:
        return None

def _esperar_qualquer(driver, locators, timeout=10):
    """Espera qualquer um dos elementos aparecer."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        for by, valor in locators:
            try:
                els = driver.find_elements(by, valor)
                for el in els:
                    try:
                        if el.is_displayed():
                            return el
                    except StaleElementReferenceException:
                        continue
            except:
                pass
        time.sleep(0.3)
    return None


# ============================================================================
# UTILITÁRIOS DE INTERAÇÃO - Otimizados
# ============================================================================

def _clicar(driver, elemento, tentativas=3):
    """Clica em um elemento com retry e fallback JS."""
    for i in range(tentativas):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
            _delay(0.1, 0.2)
            elemento.click()
            return True
        except ElementClickInterceptedException:
            try:
                driver.execute_script("arguments[0].click();", elemento)
                return True
            except:
                _delay(0.2, 0.5)
        except StaleElementReferenceException:
            _delay(0.3, 0.5)
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", elemento)
                return True
            except:
                _delay(0.2, 0.5)
    return False


def _digitar(elemento, texto, limpar=True):
    """Digita texto em um campo com velocidade otimizada."""
    try:
        elemento.click()
        _delay(0.1, 0.2)
        if limpar:
            elemento.send_keys(Keys.CONTROL + "a")
            _delay(0.05, 0.1)
            elemento.send_keys(Keys.DELETE)
            _delay(0.1, 0.2)
        for char in texto:
            elemento.send_keys(char)
            _delay_digitacao()
        _delay(0.1, 0.3)
    except Exception as e:
        logger.warning(f"Erro ao digitar, tentando via JS: {e}")
        try:
            driver = elemento.parent
            driver.execute_script("""
                var el = arguments[0];
                var val = arguments[1];
                var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeSetter.call(el, val);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            """, elemento, texto)
        except:
            pass


def _valor_campo(driver, elemento):
    try:
        valor = driver.execute_script("return (arguments[0].value || '').toString();", elemento)
        return (valor or '').strip()
    except Exception:
        try:
            return (elemento.get_attribute('value') or '').strip()
        except Exception:
            return ''


def _somente_ascii_basico(texto):
    if not texto:
        return ''
    texto = str(texto)
    texto = re.sub(r"[^A-Za-z0-9 .&_-]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _gerar_nome_bm_valido(nome_bm, nome_completo=None, email_bm=None):
    """Gera nome válido para BM. Aceita nome_bm como string ou lista de fallbacks."""
    # Se nome_bm for string, montar lista de candidatos
    if isinstance(nome_bm, (list, tuple)):
        candidatos = list(nome_bm)
    else:
        candidatos = [nome_bm]

    if nome_completo and nome_completo not in candidatos:
        candidatos.append(nome_completo)

    if email_bm and '@' in str(email_bm):
        candidatos.append(
            str(email_bm).split('@', 1)[0]
            .replace('.', ' ').replace('_', ' ').replace('-', ' '))

    for candidato in candidatos:
        limpo = _somente_ascii_basico(candidato)
        if limpo:
            partes = [p for p in limpo.split() if p]
            if len(partes) == 1:
                limpo = f"{partes[0]} Market"
            return limpo[:48].strip()

    nome, sobrenome, _ = gerar_nome_brasileiro()
    return f"{nome} {sobrenome} Market"


def _gerar_nome_pessoa_valido(nome_completo):
    limpo = _somente_ascii_basico(nome_completo)
    partes = [p for p in limpo.split() if p]
    if len(partes) >= 2:
        return ' '.join(partes[:4])[:60].strip()
    nome, sobrenome, nome_comp = gerar_nome_brasileiro()
    return nome_comp


def _preencher_input_humano(driver, elemento, valor, nome_campo='campo'):
    """
    Preenche um input simulando comportamento humano natural.
    Usa execCommand('insertText') que é o método mais confiável para React/Facebook.
    """
    valor = (valor or '').strip()
    if not elemento or not valor:
        logger.warning("[%s] Sem elemento ou valor — skip", nome_campo)
        return False

    for tentativa in range(1, 4):
        try:
            # 1. Scroll suave até o campo
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({behavior:'smooth', block:'center'});", elemento)
                time.sleep(random.uniform(0.3, 0.5))
            except Exception:
                pass

            # 2. Clicar no campo (focar)
            try:
                driver.execute_script("arguments[0].click(); arguments[0].focus();", elemento)
            except Exception:
                try:
                    elemento.click()
                except Exception:
                    pass
            time.sleep(random.uniform(0.25, 0.5))

            # 3. Limpar campo se tiver valor pré-existente (campo Nome vem pré-preenchido!)
            valor_pre = _valor_campo(driver, elemento)
            if valor_pre:
                logger.info("[%s] Valor pré-existente: '%s' — limpando", nome_campo, valor_pre)
                # Selecionar tudo e apagar via JS (mais confiável em React)
                driver.execute_script("""
                    var el = arguments[0];
                    el.focus();
                    el.select();
                    document.execCommand('selectAll');
                    document.execCommand('delete');
                """, elemento)
                time.sleep(random.uniform(0.2, 0.4))

                # Se não limpou via execCommand, tentar Ctrl+A + Backspace
                if _valor_campo(driver, elemento):
                    try:
                        elemento.send_keys(Keys.CONTROL + 'a')
                        time.sleep(random.uniform(0.08, 0.15))
                        elemento.send_keys(Keys.BACKSPACE)
                        time.sleep(random.uniform(0.15, 0.3))
                    except Exception:
                        pass

                # Último recurso: React native setter
                if _valor_campo(driver, elemento):
                    try:
                        driver.execute_script("""
                            var el = arguments[0];
                            var setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value').set;
                            setter.call(el, '');
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        """, elemento)
                        time.sleep(random.uniform(0.1, 0.2))
                    except Exception:
                        pass

            # 4. Garantir foco antes de digitar
            driver.execute_script("arguments[0].focus();", elemento)
            time.sleep(random.uniform(0.1, 0.25))

            # 5. Digitar via execCommand('insertText') — RÁPIDO
            # OTIMIZAÇÃO: Envia o texto completo de uma vez para não atrasar o fluxo
            driver.execute_script("document.execCommand('insertText', false, arguments[0]);", valor)
            time.sleep(random.uniform(0.1, 0.2))

            # 6. Pausa (humano olha o que digitou)
            time.sleep(random.uniform(0.1, 0.2))

            # 7. Disparar eventos para React atualizar
            driver.execute_script("""
                var el = arguments[0];
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            """, elemento)
            time.sleep(random.uniform(0.1, 0.2))

            # 8. Validar
            valor_final = _valor_campo(driver, elemento)
            if valor_final.strip().lower() == valor.strip().lower():
                logger.info("[%s] OK: '%s'", nome_campo, valor_final)
                return True

            # Fallback: send_keys caractere a caractere
            logger.warning("[%s] Tentativa %d: esperado='%s' obtido='%s' — fallback send_keys",
                          nome_campo, tentativa, valor, valor_final)
            try:
                driver.execute_script("arguments[0].focus(); arguments[0].click();", elemento)
                time.sleep(0.1)
                elemento.send_keys(Keys.CONTROL + 'a')
                time.sleep(0.1)
                elemento.send_keys(Keys.BACKSPACE)
                time.sleep(0.2)
                # Fallback otimizado para enviar string completa
                elemento.send_keys(valor)
                time.sleep(0.2)
            except Exception:
                pass

            valor_final = _valor_campo(driver, elemento)
            if valor_final.strip().lower() == valor.strip().lower():
                logger.info("[%s] OK (send_keys): '%s'", nome_campo, valor_final)
                return True

        except Exception as exc:
            logger.warning("[%s] Erro tentativa %d: %s", nome_campo, tentativa, exc)
        time.sleep(random.uniform(0.3, 0.6))

    logger.error("[%s] FALHA após 3 tentativas. Valor desejado: '%s'", nome_campo, valor)
    return False


def _preencher_input_forte(driver, elemento, valor, nome_campo='campo', tentativas=3):
    """Preenche input usando React native setter — método mais confiável para Facebook."""
    valor = (valor or '').strip()
    if not elemento or not valor:
        return False

    for tentativa in range(1, tentativas + 1):
        try:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", elemento)
            except Exception:
                pass
            try:
                elemento.click()
                _delay(0.08, 0.18)
            except Exception:
                pass

            try:
                driver.execute_script("""
                    var el = arguments[0];
                    var val = arguments[1];
                    el.focus();
                    try {
                        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, '');
                        setter.call(el, val);
                    } catch (e) {
                        el.value = '';
                        el.value = val;
                    }
                    el.dispatchEvent(new InputEvent('input', {bubbles: true, data: val, inputType: 'insertText'}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    el.dispatchEvent(new Event('blur', {bubbles: true}));
                """, elemento, valor)
            except Exception:
                try:
                    elemento.clear()
                except Exception:
                    pass
                _digitar(elemento, valor, limpar=True)

            valor_atual = _valor_campo(driver, elemento)
            if valor_atual.strip().lower() == valor.strip().lower():
                logger.info("Campo %s preenchido com sucesso: %s", nome_campo, valor_atual)
                return True

            # fallback misto: digitar por cima caso o React ignore o setter
            try:
                elemento.click()
                _delay(0.05, 0.12)
                elemento.send_keys(Keys.CONTROL + 'a')
                _delay(0.03, 0.08)
                elemento.send_keys(Keys.DELETE)
                _delay(0.05, 0.12)
                for ch in valor:
                    elemento.send_keys(ch)
                    _delay(0.01, 0.03)
            except Exception:
                pass

            valor_atual = _valor_campo(driver, elemento)
            if valor_atual.strip().lower() == valor.strip().lower():
                logger.info("Campo %s preenchido com sucesso no fallback: %s", nome_campo, valor_atual)
                return True
        except Exception as exc:
            logger.warning("Falha ao preencher %s (tentativa %s/%s): %s", nome_campo, tentativa, tentativas, exc)
        _delay(0.12, 0.28)

    logger.error("Nao foi possivel preencher %s com o valor: %s", nome_campo, valor)
    return False


def _aguardar_popup_criacao_bm(driver, timeout=20):
    """
    Aguarda a popup/dialog de criação de BM aparecer.
    Detecta pelo heading "Crie seu portfólio empresarial" ou pelo
    dialog[role=dialog] que contém 3 inputs visíveis.
    Retorna: True se popup está aberta, False se timeout.
    """
    textos_heading = [
        'crie seu portfólio empresarial',
        'create your business portfolio',
        'create a business portfolio',
        'gumawa ng iyong portfolio',
        'buat portofolio bisnis',
    ]

    for _ in range(timeout * 2):  # check a cada 0.5s
        try:
            encontrou = driver.execute_script("""
                var textos = arguments[0];
                // 1. Procurar heading com o texto
                var headings = document.querySelectorAll('[role="heading"], h1, h2, h3');
                for (var h = 0; h < headings.length; h++) {
                    var t = (headings[h].innerText || '').toLowerCase().trim();
                    for (var i = 0; i < textos.length; i++) {
                        if (t.includes(textos[i])) return true;
                    }
                }
                // 2. Verificar dialog com 3+ inputs
                var dialogs = document.querySelectorAll('[role="dialog"]');
                for (var d = 0; d < dialogs.length; d++) {
                    var inputs = dialogs[d].querySelectorAll('input');
                    var visCount = 0;
                    for (var k = 0; k < inputs.length; k++) {
                        var r = inputs[k].getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) visCount++;
                    }
                    if (visCount >= 3) return true;
                }
                return false;
            """, textos_heading)

            if encontrou:
                logger.info("[BM Form] Popup de criação detectada!")
                return True
        except Exception:
            pass
        time.sleep(0.5)

    logger.warning("[BM Form] Popup de criação NÃO apareceu após %ds", timeout)
    return False


def _localizar_campos_criacao_bm(driver):
    """
    Localiza os 3 campos do formulário de criação de BM.

    Campos esperados (form "Crie seu portfólio empresarial"):
      1. "Nome da sua conta e empresa" → campo_empresa
      2. "Seu nome"                   → campo_nome
      3. "Seu email comercial"        → campo_email

    IMPORTANTE: NÃO retorna elementos via execute_script (Playwright serializa
    DOM elements como {} vazio). Em vez disso, marca cada input com um
    atributo data-bm-campo e depois localiza via find_element/CSS_SELECTOR.

    Retorna: (campo_empresa, campo_nome, campo_email)
    """

    # ═══ Limpar atributos anteriores ═══
    try:
        driver.execute_script("""
            document.querySelectorAll('[data-bm-campo]').forEach(function(el){
                el.removeAttribute('data-bm-campo');
            });
        """)
    except Exception:
        pass

    # ═══ Estratégia principal: JS marca os inputs com data-bm-campo ═══
    marcou = False
    try:
        resultado = driver.execute_script("""
            function visivel(el) {
                if (!el || el.disabled) return false;
                var r = el.getBoundingClientRect();
                var s = getComputedStyle(el);
                return r.width > 0 && r.height > 0
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }

            /* Coleta texto descritivo PERTO do input (max 5 níveis):
               - aria-label, aria-labelledby
               - placeholder
               - Texto de irmãos (siblings) que NÃO contêm outros inputs */
            function nearbyText(el) {
                var txt = '';

                /* aria-label */
                var ariaL = (el.getAttribute('aria-label') || '').trim();
                if (ariaL) txt += ' ' + ariaL;

                /* aria-labelledby */
                var ariaBy = (el.getAttribute('aria-labelledby') || '').trim();
                if (ariaBy) {
                    var parts = ariaBy.split(/\\s+/);
                    for (var i = 0; i < parts.length; i++) {
                        var n = document.getElementById(parts[i]);
                        if (n) txt += ' ' + (n.innerText || n.textContent || '');
                    }
                }

                /* placeholder */
                var ph = (el.getAttribute('placeholder') || '').trim();
                if (ph) txt += ' ' + ph;

                /* Subir até 5 níveis, coletar texto de irmãos que NÃO tenham inputs */
                var p = el.parentElement;
                for (var depth = 0; depth < 5 && p; depth++) {
                    var children = p.children;
                    for (var c = 0; c < children.length; c++) {
                        var child = children[c];
                        if (child === el || child.contains(el)) continue;
                        /* Ignorar irmãos que contêm outros inputs (evita pegar label de outro campo) */
                        if (child.querySelector && child.querySelector('input')) continue;
                        var t = (child.innerText || child.textContent || '').trim();
                        if (t.length > 2 && t.length < 120) {
                            txt += ' ' + t;
                        }
                    }
                    /* Parar se já coletou texto suficiente */
                    if (txt.trim().length > 10) break;
                    p = p.parentElement;
                }

                return txt.toLowerCase();
            }

            var inputs = Array.from(
                document.querySelectorAll('input')
            ).filter(function(el) {
                if (!visivel(el)) return false;
                var t = (el.type || '').toLowerCase();
                return t === '' || t === 'text' || t === 'email' || t === 'search';
            }).sort(function(a, b) {
                return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
            });

            var found = {empresa: null, nome: null, email: null};

            /* Fase 1: Detecção semântica */
            for (var i = 0; i < inputs.length; i++) {
                var el = inputs[i];
                var ctx = nearbyText(el);
                var type = (el.getAttribute('type') || '').toLowerCase();
                var ph = (el.getAttribute('placeholder') || '').toLowerCase();

                /* Email — checar PRIMEIRO (type=email é inequívoco) */
                if (!found.email && (
                    type === 'email'
                    || ctx.indexOf('email comercial') !== -1
                    || ctx.indexOf('seu email') !== -1
                    || ctx.indexOf('email válido') !== -1
                    || ctx.indexOf('business email') !== -1
                    || ctx.indexOf('your email') !== -1
                )) {
                    found.email = el;
                    continue;
                }

                /* Empresa / Nome da conta */
                if (!found.empresa && (
                    ph.indexOf('market') !== -1
                    || ph.indexOf('jasper') !== -1
                    || ctx.indexOf('nome da sua conta') !== -1
                    || ctx.indexOf('conta e empresa') !== -1
                    || ctx.indexOf('business name') !== -1
                    || ctx.indexOf('account name') !== -1
                    || ctx.indexOf('portfólio') !== -1
                    || ctx.indexOf('portfolio') !== -1
                )) {
                    found.empresa = el;
                    continue;
                }

                /* Seu nome */
                if (!found.nome && (
                    ph.indexOf('nome e sobrenome') !== -1
                    || ph.indexOf('insira seu nome') !== -1
                    || ctx.indexOf('seu nome') !== -1
                    || ctx.indexOf('your name') !== -1
                    || ctx.indexOf('nome completo') !== -1
                )) {
                    found.nome = el;
                    continue;
                }
            }

            /* Fase 2: Fallback posicional para campos não encontrados */
            var remaining = inputs.filter(function(el) {
                return el !== found.empresa && el !== found.nome && el !== found.email;
            });

            if (!found.empresa && remaining.length > 0) found.empresa = remaining.shift();
            if (!found.nome && remaining.length > 0)    found.nome = remaining.shift();
            if (!found.email && remaining.length > 0)   found.email = remaining.shift();

            /* Marcar com data-bm-campo para localização posterior via CSS */
            var ok = {empresa: false, nome: false, email: false};
            if (found.empresa) { found.empresa.setAttribute('data-bm-campo', 'empresa'); ok.empresa = true; }
            if (found.nome)    { found.nome.setAttribute('data-bm-campo', 'nome');       ok.nome = true; }
            if (found.email)   { found.email.setAttribute('data-bm-campo', 'email');     ok.email = true; }

            return ok;
        """)
        if isinstance(resultado, dict):
            marcou = any(resultado.get(k) for k in ('empresa', 'nome', 'email'))
    except Exception as exc:
        logger.warning("Falha na detecção dos campos BM: %s", exc)

    # ═══ Localizar elementos pelos atributos data-bm-campo ═══
    campo_empresa = campo_nome = campo_email = None

    if marcou:
        for chave, setter in [('empresa', lambda e: None), ('nome', lambda e: None), ('email', lambda e: None)]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, f'[data-bm-campo="{chave}"]')
                if chave == 'empresa':
                    campo_empresa = el
                elif chave == 'nome':
                    campo_nome = el
                elif chave == 'email':
                    campo_email = el
            except Exception:
                pass

    # ═══ Fallback posicional puro (se marcação falhou) ═══
    if not (campo_empresa and campo_nome and campo_email):
        try:
            driver.execute_script("""
                var inputs = Array.from(document.querySelectorAll('input'))
                    .filter(function(el) {
                        var r = el.getBoundingClientRect();
                        var t = (el.type || '').toLowerCase();
                        return r.width > 0 && r.height > 0 && !el.disabled
                            && t !== 'hidden' && t !== 'submit' && t !== 'button'
                            && t !== 'checkbox' && t !== 'radio' && t !== 'file';
                    })
                    .sort(function(a, b) {
                        return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
                    });

                if (inputs.length >= 1 && !document.querySelector('[data-bm-campo="empresa"]'))
                    inputs[0].setAttribute('data-bm-campo', 'empresa');
                if (inputs.length >= 2 && !document.querySelector('[data-bm-campo="nome"]'))
                    inputs[1].setAttribute('data-bm-campo', 'nome');
                if (inputs.length >= 3 && !document.querySelector('[data-bm-campo="email"]'))
                    inputs[2].setAttribute('data-bm-campo', 'email');
            """)
            if not campo_empresa:
                try:
                    campo_empresa = driver.find_element(By.CSS_SELECTOR, '[data-bm-campo="empresa"]')
                except Exception:
                    pass
            if not campo_nome:
                try:
                    campo_nome = driver.find_element(By.CSS_SELECTOR, '[data-bm-campo="nome"]')
                except Exception:
                    pass
            if not campo_email:
                try:
                    campo_email = driver.find_element(By.CSS_SELECTOR, '[data-bm-campo="email"]')
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Fallback posicional falhou: %s", exc)

    logger.info("[BM Form] empresa=%s nome=%s email=%s",
                bool(campo_empresa), bool(campo_nome), bool(campo_email))

    return campo_empresa, campo_nome, campo_email


# ============================================================================
# NOMES BRASILEIROS
# ============================================================================

NOMES_BR = [
    "Ana", "Maria", "Julia", "Beatriz", "Larissa", "Fernanda", "Camila",
    "Gabriela", "Leticia", "Amanda", "Bruna", "Carolina", "Daniela",
    "Patricia", "Renata", "Tatiana", "Vanessa", "Priscila", "Mariana",
    "Pedro", "Lucas", "Mateus", "Rafael", "Gabriel", "Thiago", "Bruno",
    "Felipe", "Gustavo", "Leonardo", "Diego", "Rodrigo", "Andre",
    "Carlos", "Eduardo", "Fernando", "Marcelo", "Ricardo", "Roberto"
]

SOBRENOMES_BR = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira",
    "Alves", "Pereira", "Lima", "Gomes", "Costa", "Ribeiro", "Martins",
    "Carvalho", "Almeida", "Lopes", "Soares", "Fernandes", "Vieira",
    "Barbosa", "Rocha", "Dias", "Nascimento", "Andrade", "Moreira",
    "Nunes", "Marques", "Machado", "Mendes", "Freitas", "Cardoso"
]


def gerar_nome_brasileiro():
    """Gera um nome completo brasileiro aleatório."""
    nome = random.choice(NOMES_BR)
    sobrenome = random.choice(SOBRENOMES_BR)
    return nome, sobrenome, f"{nome} {sobrenome}"


# ============================================================================
# CONEXÃO SELENIUM VIA IXBROWSER
# ============================================================================

def conectar_selenium(debugging_address, webdriver_path=None):
    """Conecta ao IXBrowser via Playwright/CDP."""
    try:
        return conectar_playwright(debugging_address, webdriver_path)
    except Exception as e:
        logger.error(f"Falha ao conectar Playwright: {e}")
        return None


def navegador_foi_fechado(driver):
    """True se o navegador controlado FOI FECHADO (pelo usuário na mão ou caiu).

    Detecta NA HORA para abortar o perfil como Erro/Falha, em vez de ficar preso
    em 'Processando' com um navegador que nem está mais aberto. Usa o
    `driver.is_alive()` (conexão CDP + nº de abas); se o driver não tiver o método
    (compat.), tenta uma leitura barata (`window_handles`) — se falhar, fechado."""
    if driver is None:
        return True
    try:
        fn = getattr(driver, 'is_alive', None)
        if callable(fn):
            return not fn()
    except Exception:
        return True
    # Fallback p/ drivers sem is_alive: leitura barata que quebra se estiver fechado.
    try:
        _ = list(getattr(driver, 'window_handles', []) or [])
        return False
    except Exception:
        return True


def _tratar_captcha_se_preciso(driver, callback_status=None):
    """CAPTCHA-ANYWHERE: se aparecer um reCAPTCHA em QUALQUER tela do fluxo,
    resolve via CapSolver e segue. Faz uma checagem INSTANTÂNEA de presença antes
    (não adiciona delay quando não há captcha) e só então resolve. Best-effort —
    nunca quebra o fluxo. Retorna True se resolveu um captcha nesta chamada."""
    try:
        from server import captcha_solver
        if not captcha_solver.captcha_presente(driver):
            return False
        r = captcha_solver.resolver_captcha_se_preciso(
            driver, callback_status=callback_status, aguardar_widget_seg=3)
        return r == 'resolvido'
    except Exception as e:
        logger.debug("[Captcha] handler falhou: %s", e)
        return False


def _erro_credencial_visivel(driver):
    """True quando o Facebook mostra na tela que o usuário/senha não servem.
    Serve para NÃO gastar reenvios de login numa credencial que ele já recusou."""
    try:
        return bool(driver.execute_script(r"""
            var t = ((document.body && document.body.innerText) || '').toLowerCase();
            var marcas = ['senha incorreta','a senha que você digitou','wrong password',
                          'incorrect password','senha que voce digitou',
                          // "As informações de login que você inseriu estão incorretas"
                          // (print do dono 2026-10-13) + EN/ES
                          'informações de login que você inseriu','informacoes de login que voce inseriu',
                          'informações de login estão incorretas','login information you entered',
                          'the login information you entered is incorrect',
                          'información de inicio de sesión que ingresaste','informacion de inicio de sesion',
                          'não foi possível encontrar sua conta','nao foi possivel encontrar sua conta',
                          "we couldn't find your account", 'couldn’t find your account',
                          'o email ou o número de telefone que você inseriu',
                          'contraseña incorrecta'];
            for (var i=0;i<marcas.length;i++){ if (t.indexOf(marcas[i]) !== -1) return true; }
            return false;
        """))
    except Exception:
        return False


def _snap_login(driver, motivo=''):
    """Salva um print da tela em logs/snaps_login/ para diagnosticar a falha
    depois (o navegador é fechado logo em seguida). Best-effort."""
    try:
        import os
        page = getattr(driver, '_current_page', None)
        if page is None:
            return ''
        pasta = os.path.join(os.getcwd(), 'logs', 'snaps_login')
        os.makedirs(pasta, exist_ok=True)
        nome = f"{time.strftime('%H%M%S')}_{(motivo or 'snap')[:40]}.png"
        caminho = os.path.join(pasta, nome)
        page.screenshot(path=caminho, full_page=False)
        logger.info("[Login] snapshot da tela: %s | url=%s", caminho,
                    (driver.current_url or '')[:150])
        return caminho
    except Exception as e:
        logger.debug("[Login] snapshot falhou: %s", e)
        return ''


def fechar_aviso_conta_protegida(driver, callback_status=None):
    """Fecha o aviso 'Meta took steps to protect your account' (/hacked-protection).

    NÃO é checkpoint — é um informativo com um único botão que devolve ao feed
    ("Back to Facebook"). Deixá-lo aberto TRAVA o login: o bot não reconhece a home
    e fica parado (relato do usuário 2026-09-02).

    A detecção NÃO depende de tradução, porque o rótulo muda com o idioma do perfil
    ("Voltar para o Facebook", "Quay lại Facebook", "Kembali ke Facebook",
    "Назад в Facebook", "กลับไปที่ Facebook", "Facebook पर वापस जाएं"...). Três
    camadas, da mais confiável para a mais genérica:

      1. O botão cujo texto contém "facebook" — a MARCA nunca é traduzida, então
         isso casa o "Back to Facebook" em qualquer idioma.
      2. O CTA primário do diálogo (azul do Facebook, largura cheia).
      3. O último botão do diálogo (o CTA fica no rodapé) e, por fim, o "X".

    Só age quando a tela É esse aviso, para nunca clicar à toa em outra tela.

    POLL (2026-09-26): o modal costuma renderizar 1-3s DEPOIS de a página assentar
    — uma única leitura passava batido e o bot seguia com o aviso na frente. Agora
    espera o modal aparecer (até ~6s) e insiste no clique (Back to Facebook / X) até
    ele SUMIR, confirmando o fechamento.
    Retorna True se fechou o aviso."""
    import time as _t
    # /hacked-protection/details → "Not Found" (página CRUA, sem modal nem botão — print do
    # dono 2026-10-13): não há o que clicar e o poll abaixo esperava um modal que nunca
    # vem. Remédio provado pelo dono: ir de novo a facebook.com → cai no checkpoint "We
    # suspect automated behavior" → Dismiss (handler existente) → home normal.
    if _hacked_protection_not_found(driver) and (_t.sleep(1.5) or _hacked_protection_not_found(driver)):
        logger.info("[Aviso] /hacked-protection 'Not Found' — voltando ao facebook.com.")
        if callback_status:
            callback_status("Aviso 'conta protegida' em branco (Not Found) — voltando ao Facebook...")
        try:
            driver.get('https://www.facebook.com/')
        except Exception:
            pass
        _pagina_estatica_pronta(driver, timeout=20)
        try:
            _tratar_aviso_comportamento_automatizado(driver, callback_status)
        except Exception as _e:
            logger.debug("[Aviso] Dismiss pós Not Found: %s", _e)
        return True
    _fim = _t.time() + 6.0
    _agiu = False
    while True:
        _r = _tentar_fechar_aviso_conta_protegida(driver)
        if _r == 'clicado':
            _agiu = True
            _delay_pagina(0.8, 1.4)      # clicou → re-checa: sumiu? 2º modal?
            continue
        if _r == 'pendente' and _t.time() < _fim:
            _delay_pagina(0.6, 1.0)      # é o aviso, mas os botões ainda não renderizaram
            continue
        break                            # '' (não é/deixou de ser o aviso) ou timeout
    if _agiu:
        logger.info("[Aviso] 'Conta protegida' (/hacked-protection) — aviso dispensado.")
        if callback_status:
            callback_status("Aviso 'Meta protegeu sua conta' — fechado, seguindo para o feed...")
        _delay_pagina(1.0, 1.8)
    return _agiu


def _hacked_protection_not_found(driver):
    """True se estamos em /hacked-protection e a página é o 'Not Found' CRU: sem diálogo,
    sem botão e quase sem texto (idioma-agnóstico — a resposta do servidor é sempre
    curta; 'not found' só reforça)."""
    try:
        return bool(driver.execute_script(r"""
            var url = (location.href || '').toLowerCase();
            if (url.indexOf('hacked-protection') < 0) return false;
            if (document.readyState !== 'complete') return false;   // ainda carregando
            var b = document.body; if (!b) return false;
            var txt = (b.innerText || '').trim().toLowerCase();
            var temBotao = !!document.querySelector('[role="button"], button, [role="dialog"], input');
            return !temBotao && (txt.indexOf('not found') >= 0 || txt.length < 40);
        """))
    except Exception:
        return False


def _tentar_fechar_aviso_conta_protegida(driver):
    """Uma tentativa: detecta o aviso e clica p/ fechar. Retorna:
      'fechado'  → é o aviso e ele NÃO está mais na tela (já dispensado);
      'clicado'  → é o aviso e clicamos num botão de dispensar agora;
      'pendente' → é o aviso mas o modal/botões ainda não renderizaram;
      ''         → NÃO é a tela do aviso (não faz nada)."""
    try:
        clicado = driver.execute_script(r"""
            function vis(el){
                if (!el) return false;
                var r = el.getBoundingClientRect(), s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 &&
                       s.visibility !== 'hidden' && s.display !== 'none';
            }
            // CLIQUE ROBUSTO (React): o .click() puro NÃO dispara o onClick delegado do
            // Facebook em muitos casos (o w2 marcava "clicado" mas a popup não fechava,
            // 2026-09-27). Disparamos a sequência COMPLETA de eventos ponteiro+mouse no
            // CENTRO do elemento (via elementFromPoint, que é o alvo real que a Meta ouve)
            // e, por garantia, o .click() nativo também.
            function realClick(el){
                if (!el) return false;
                try {
                    var r = el.getBoundingClientRect();
                    var cx = r.left + r.width/2, cy = r.top + r.height/2;
                    var t = document.elementFromPoint(cx, cy) || el;
                    var seq = ['pointerover','pointerenter','pointerdown','mousedown',
                               'pointerup','mouseup','click'];
                    for (var k=0;k<seq.length;k++){
                        var type = seq[k], ev;
                        try {
                            if (type.indexOf('pointer') === 0)
                                ev = new PointerEvent(type, {bubbles:true, cancelable:true,
                                     clientX:cx, clientY:cy, pointerId:1, isPrimary:true});
                            else
                                ev = new MouseEvent(type, {bubbles:true, cancelable:true,
                                     clientX:cx, clientY:cy});
                            t.dispatchEvent(ev);
                        } catch(e){}
                    }
                    try { el.click(); } catch(e){}
                    return true;
                } catch(e){ try { el.click(); return true; } catch(e2){ return false; } }
            }
            var url = (location.href || '').toLowerCase();
            // ⚠️ SÓ pela URL /hacked-protection (gatilho inequívoco) OU pelas frases
            // ESPECÍFICAS do pop-up de reativação (sem URL própria).
            var _b = (document.body ? document.body.innerText : '').toLowerCase();
            var reativado = _b.indexOf('no longer suspended') >= 0
                         || _b.indexOf("you're back on facebook") >= 0
                         || _b.indexOf('back on facebook') >= 0
                         || _b.indexOf('não está mais suspensa') >= 0
                         || _b.indexOf('nao esta mais suspensa') >= 0
                         || _b.indexOf('de volta ao facebook') >= 0;
            if (url.indexOf('hacked-protection') < 0 && !reativado) return '';

            // Diálogo do TOPO (pode haver stack de modais — pega o último visível).
            var dlgs = [].slice.call(document.querySelectorAll(
                'div[role="dialog"], [aria-modal="true"]')).filter(vis);
            var dlg = dlgs.length ? dlgs[dlgs.length - 1] : null;
            var escopo = dlg || document;
            var botoes = [].slice.call(escopo.querySelectorAll('[role="button"], button')).filter(vis);
            if (!botoes.length) return 'pendente';

            // ── (1) X estrutural, IDIOMA-AGNÓSTICO (preferido: fecha sem navegar) ──
            // 1a) aria-label casa uma palavra de "fechar" em vários idiomas.
            var CLOSE = ['close','fechar','cerrar','fermer','schließen','schliessen',
                         'tutup','закрыть','đóng','stäng','chiudi','关闭','關閉','閉じる',
                         '닫기','إغلاق','बंद','ปิด','kapat','sluiten','zamknij','luk','sulje'];
            var xbtn = null;
            for (var i=0;i<botoes.length;i++){
                var al = (botoes[i].getAttribute('aria-label')||'').trim().toLowerCase();
                if (al && CLOSE.some(function(c){return al.indexOf(c)>=0;})) { xbtn = botoes[i]; break; }
            }
            // 1b) sem aria-label traduzido: o X é um [role=button] PEQUENO, com <svg>
            //     e SEM texto (as ações de texto — "Back to Facebook" — têm innerText).
            if (!xbtn){
                for (var i=0;i<botoes.length;i++){
                    var b = botoes[i], txt = (b.innerText||'').trim();
                    var rr = b.getBoundingClientRect();
                    if (!txt && b.querySelector('svg') && rr.width <= 64 && rr.height <= 64) { xbtn = b; break; }
                }
            }
            if (xbtn && realClick(xbtn)) return 'x';

            // ── (2) "Back to Facebook": a MARCA não é traduzida em nenhum idioma ──
            for (var i=0;i<botoes.length;i++){
                var t = (botoes[i].innerText || '').trim();
                if (t && t.length <= 60 && t.toLowerCase().indexOf('facebook') >= 0) {
                    if (realClick(botoes[i])) return 'texto:' + t;
                }
            }

            // ── (3) CTA primário (azul, largura cheia) ou último botão do diálogo ──
            var larguraRef = dlg ? dlg.getBoundingClientRect().width : window.innerWidth;
            for (var i=0;i<botoes.length;i++){
                var st = getComputedStyle(botoes[i]), bg = st.backgroundColor || '';
                var azul = bg.indexOf('8, 102, 255') >= 0 || bg.indexOf('24, 119, 242') >= 0
                        || bg.indexOf('0, 100, 224') >= 0 || bg.indexOf('0, 129, 251') >= 0;
                if (azul && botoes[i].getBoundingClientRect().width >= larguraRef * 0.5) {
                    if (realClick(botoes[i])) return 'cta-azul';
                }
            }
            if (dlg) {
                var ult = botoes[botoes.length - 1];
                var tu = (ult.innerText || '').trim();
                if (tu && tu.length <= 60) { if (realClick(ult)) return 'ultimo:' + tu; }
            }
            return 'pendente';
        """)
        if not clicado:
            return ''            # NÃO é a tela do aviso.
        if clicado == 'pendente':
            return 'pendente'    # é o aviso, mas os botões ainda não renderizaram.
        logger.info("[Aviso] 'Conta protegida' (/hacked-protection) clicado por %s", clicado)
        return 'clicado'
    except Exception as e:
        logger.debug("[Aviso] _tentar_fechar_aviso_conta_protegida: %s", e)
        return ''


def _erro_pedido_invalido(driver):
    """True se a tela mostra o erro 'Pedido inválido / não foi possível validar
    sua solicitação — comece o fluxo de novo'. Acontece quando o COOKIE/SESSÃO
    expira e o Facebook abre o fluxo de 2FA (two_step_verification/authentication)
    que então FALHA — não é 2FA legítimo nem checkpoint: é sessão inválida, e a
    saída é logar com usuário+senha.

    Detecção pela FRASE ESPECÍFICA do erro (título 'Pedido inválido/Invalid
    request' + corpo 'could not validate your request ... start the flow from
    beginning'). É seguro usar o texto aqui — ao contrário das frases de
    SEGURANÇA (que aparecem na Central e não podem ser gatilho), esta é uma
    mensagem de ERRO exclusiva de um fluxo que falhou, não de uma tela legítima."""
    try:
        return bool(driver.execute_script(r"""
            var b = (document.body ? document.body.innerText : '') || '';
            b = b.toLowerCase();
            var alvos = [
                'could not validate your request',
                'not validate your request',
                'nao foi possivel validar', 'não foi possível validar',
                'no pudimos validar', 'no se pudo validar',
                'starting the flow from beginning',
                'start the flow from the beginning',
                'comece o fluxo', 'inicie o fluxo', 'reinicie o fluxo',
                'pedido invalido', 'pedido inválido',
                'solicitacao invalida', 'solicitação inválida',
                'invalid request', 'solicitud no valida', 'solicitud no válida'
            ];
            for (var i=0;i<alvos.length;i++){ if (b.indexOf(alvos[i])>=0) return true; }
            return false;
        """))
    except Exception:
        return False


def _fechar_dialogo_generico(driver):
    """Fecha um diálogo simples de aviso/erro clicando OK/Entendi/Fechar/Continuar
    ou o 'X'. Best-effort — usado p/ dispensar o 'Pedido inválido' antes de voltar
    ao facebook.com. Idioma-agnóstico no que dá (marca 'X' por aria-label)."""
    try:
        return bool(driver.execute_script(r"""
            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                var s=getComputedStyle(el);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
            var dlg = document.querySelector('div[role="dialog"]') || document;
            var btns = dlg.querySelectorAll('div[role="button"],button,span[role="button"],a[role="button"],input[type="submit"]');
            var alvos = ['ok','entendi','entendido','fechar','close','got it','continuar',
                         'continue','tentar novamente','try again','aceptar','fermer','schließen'];
            for (var i=0;i<btns.length;i++){ if(!vis(btns[i])) continue;
                var t=((btns[i].innerText||btns[i].value||'')+'').trim().toLowerCase();
                for (var j=0;j<alvos.length;j++){ if(t===alvos[j]){ btns[i].click(); return true; } } }
            var xs = dlg.querySelectorAll('[aria-label][role="button"], [role="button"][aria-label]');
            for (var k=0;k<xs.length;k++){ if(!vis(xs[k])) continue;
                var al=(xs[k].getAttribute('aria-label')||'').toLowerCase();
                if (al.indexOf('close')>=0||al.indexOf('fechar')>=0||al.indexOf('cerrar')>=0
                    ||al.indexOf('fermer')>=0||al.indexOf('schließen')>=0){ xs[k].click(); return true; } }
            return false;
        """))
    except Exception:
        return False


def _tentar_home_direto(driver, callback_status=None):
    """Abre facebook.com direto para ver se a sessão JÁ está logada.

    Depois de resolver o reCAPTCHA o Facebook às vezes devolve o formulário de
    login mesmo tendo criado a sessão — e o bot matava o perfil achando que era
    bounce. Abrindo a home direto isso fica claro na hora: se a home carregar,
    está logado e não há credencial nenhuma para reenviar. Retorna True se caiu
    na home."""
    try:
        from server.page_state_manager import PageStateManager
        if callback_status:
            callback_status("Conferindo se a sessão já está logada (facebook.com)...")
        driver.get("https://www.facebook.com/")
        PageStateManager.wait_until_stable(driver, timeout=20, settle_time=1.0)
        # Pode cair na HOME com um AVISO DISPENSÁVEL na frente (ex.: "Meta took steps
        # to protect your account" /hacked-protection, "logged you out from suspicious
        # devices"). A sessão ESTÁ logada — o PSM classifica isso como 'checkpoint_dismiss'.
        # Antes o método devolvia tela!='home' => FALSO "não logado" e o fluxo quebrava
        # (relato + print do usuário 2026-09-01). Agora FECHA o aviso e reconfere.
        for _tent in range(3):
            # O aviso /hacked-protection cobre o feed e faz a home não ser
            # reconhecida. Fecha ANTES de classificar a tela — vale em qualquer
            # idioma e não depende da classificação do PSM.
            if fechar_aviso_conta_protegida(driver, callback_status):
                PageStateManager.wait_until_stable(driver, timeout=12, settle_time=1.0)
            tela, _ = PageStateManager.identify_current_screen(driver)
            logger.info("[Login] Acesso direto ao facebook.com — tela=%s", tela)
            if tela == 'home':
                return True
            if tela == 'checkpoint_dismiss':
                if callback_status:
                    callback_status("Aviso de segurança na home — fechando e seguindo...")
                _tratar_aviso_comportamento_automatizado(driver, callback_status)
                PageStateManager.wait_until_stable(driver, timeout=12, settle_time=1.0)
                continue
            break
        tela, _ = PageStateManager.identify_current_screen(driver)
        return tela == 'home'
    except Exception as e:
        logger.debug("[Login] acesso direto ao facebook.com falhou: %s", e)
        return False


def _tem_campo_codigo_2fa(driver):
    """True se o campo de DIGITAR o código 2FA está visível na tela. Usado para
    separar a tela de 2FA de verdade da tela de reCAPTCHA — as duas moram na
    mesma URL (`two_step_verification/authentication`)."""
    try:
        return bool(driver.execute_script("""
            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                var s=getComputedStyle(el);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
            // Campo ESPECÍFICO de código (vale em qualquer URL):
            if (vis(document.querySelector('input[name="approvals_code"], #approvals_code, input[autocomplete="one-time-code"]')))
                return true;
            // Na URL genuína de 2FA (two_factor/two_step), o campo "Code" moderno pode
            // não ter atributo específico — aceita um input numérico/tel/text VISÍVEL,
            // desde que não seja o campo de e-mail/usuário do login (que não vive nessa URL).
            var u = (location.href||'').toLowerCase();
            var em2fa = u.indexOf('two_factor')>=0 || u.indexOf('two_step')>=0 ||
                        u.indexOf('checkpoint/?next')>=0 && u.indexOf('602')>=0;
            if (em2fa) {
                var cands = document.querySelectorAll('input[inputmode="numeric"], input[type="tel"], input[type="text"]');
                for (var i=0;i<cands.length;i++){
                    var el=cands[i], n=(el.getAttribute('name')||'').toLowerCase();
                    if (n.indexOf('email')>=0 || n==='email' || n.indexOf('pass')>=0) continue;
                    if (vis(el)) return true;
                }
            }
            return false;
        """))
    except Exception:
        return False


def _resolver_captcha_login(driver, callback_status=None, aguardar_widget_seg=20):
    """Resolve o reCAPTCHA da tela dedicada de captcha do LOGIN (ex.:
    two_step_verification/authentication mostrando só 'Não sou um robô').
    Espera mais tempo pelo widget (a tela é sabidamente um captcha) e, após
    injetar o token, tenta avançar clicando Continuar/Enviar. Retorna:
      'resolvido' | 'sem_token' | 'falhou' | 'no_captcha'."""
    try:
        from server import captcha_solver
        # O solver já confirma o avanço da tela (URL mudou / widget sumiu) e
        # clica Continuar quando o FB não auto-submete — não clicamos nada aqui
        # depois, para não acertar um botão da tela SEGUINTE por engano.
        return captcha_solver.resolver_captcha_se_preciso(
            driver, callback_status=callback_status,
            aguardar_widget_seg=aguardar_widget_seg,
            tentativas=2, permitir_refresh=True)
    except Exception as e:
        logger.warning("[Captcha] resolver login falhou: %s", e)
        return 'falhou'


def _avancar_apos_captcha(driver):
    """Após resolver o reCAPTCHA no login, clica um botão Continuar/Enviar se
    houver (algumas telas não auto-submetem quando o token é injetado).
    Best-effort — nunca quebra o fluxo."""
    try:
        return bool(driver.execute_script(r"""
            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                var s=getComputedStyle(el);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
            var alvos=['continuar','continue','enviar','submit','próximo','proximo',
                       'next','avançar','avancar','confirmar','confirm'];
            var els=document.querySelectorAll(
                'div[role="button"],button,span[role="button"],a[role="button"],input[type="submit"]');
            for(var i=0;i<els.length;i++){ if(!vis(els[i])) continue;
                var t=((els[i].innerText||els[i].value||'')+'').trim().toLowerCase();
                for(var j=0;j<alvos.length;j++){ if(t===alvos[j]){ els[i].click(); return true; } } }
            return false;
        """))
    except Exception:
        return False


# ============================================================================
# VERIFICAÇÃO DE LOGIN
# ============================================================================

def _confirmar_logado_via_reels(driver):
    """Confirma a sessão ativa abrindo o REELS: só um perfil LOGADO acessa
    `/reel/?s=tab` sem ser redirecionado ao login. Usado como desempate quando a
    Home fica ambígua (evita tratar perfil logado como deslogado/checkpoint)."""
    try:
        driver.get("https://web.facebook.com/reel/?s=tab")
        _delay_pagina(1.2, 2.2)
        _esperar_pagina_carregar(driver, timeout=8)
        u = (driver.current_url or '').lower()
        if '/login' in u or 'login.php' in u or 'login/device-based' in u:
            return False
        lf = driver.find_elements(By.CSS_SELECTOR, '#email, #pass, input[name="email"], input[name="pass"]')
        if lf and any(el.is_displayed() for el in lf):
            return False
        # Continuou no /reel com player/main = LOGADO (deslogado não abre o Reels).
        ok = driver.execute_script("""
            if (location.pathname.indexOf('/reel') !== -1) {
                if (document.querySelector('video')) return true;
                if (document.querySelector('[role="main"]')) return true;
            }
            if (document.querySelector('[role="feed"], [role="navigation"]')) return true;
            return false;
        """)
        return bool(ok)
    except Exception:
        return False


class _SessaoOcupada:
    """Marca o driver como 'em login' (_sg_busy) enquanto verifica/faz login, p/ o
    guardião automático de sessão (session_guard, ganchos em driver.get e nas esperas)
    NÃO disparar um re-login ANINHADO dentro do próprio login."""
    def __init__(self, driver):
        self.d = driver
        self.antes = False

    def __enter__(self):
        try:
            self.antes = bool(getattr(self.d, '_sg_busy', False))
            self.d._sg_busy = True
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        try:
            self.d._sg_busy = self.antes
        except Exception:
            pass
        return False


def verificar_login_facebook(driver, timeout=10, callback_status=None):
    """Verifica se está logado no Facebook (Home/Feed) — com desempate por Reels."""
    with _SessaoOcupada(driver):
        return _verificar_login_facebook(driver, timeout, callback_status)


def _verificar_login_facebook(driver, timeout=10, callback_status=None):
    try:
        driver.get("https://www.facebook.com/")
        _delay_pagina(2.0, 3.5)
        _esperar_pagina_carregar(driver, timeout=8)

        # SEMPRE checar se há o aviso de Automated Behavior ao carregar a Home
        _tratar_aviso_comportamento_automatizado(driver, callback_status)
        # E o aviso "Meta took steps to protect your account" (/hacked-protection):
        # é só informativo, mas fica por cima do feed e o bot não reconhece a home.
        if fechar_aviso_conta_protegida(driver, callback_status):
            _esperar_pagina_carregar(driver, timeout=8)

        url = (driver.current_url or '').lower()
        # ⚠️ NÃO tratar 'checkpoint' na URL como deslogado: a HOME LOGADA carrega com
        # '?checkpoint_src=...' e isso fazia perfil LOGADO ser marcado como checkpoint.
        # Só é deslogado quando cai de fato na tela de LOGIN.
        if '/login' in url or 'login.php' in url or 'login/device-based' in url:
            return False

        # Formulário de login VISÍVEL = deslogado.
        login_form = driver.find_elements(By.CSS_SELECTOR, '#email, #pass, input[name="email"], input[name="pass"]')
        if login_form and any(el.is_displayed() for el in login_form):
            return False

        # Indicadores fortes de sessão ativa na Home.
        logado = driver.execute_script("""
            if (document.querySelector('[role="feed"]')) return true;
            if (document.querySelector('[role="banner"] [role="navigation"]')) return true;
            if (document.querySelector('input[type="search"], [role="search"]')) return true;
            var nav = document.querySelectorAll('[role="navigation"]');
            if (nav.length > 0) return true;
            return false;
        """)
        if bool(logado):
            return True

        # AMBÍGUO (Home sem feed/nav e sem formulário de login) → confirma pelo REELS.
        return _confirmar_logado_via_reels(driver)

    except Exception as e:
        logger.error(f"Erro ao verificar login: {e}")
        return False


# ============================================================================
# LOGIN COM CREDENCIAIS
# ============================================================================

# Arquivo de cache para coordenadas dos popups do browser
import os as _os
import json as _json

_POPUP_COORDS_FILE = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    'config', 'popup_coords.json'
)

def _carregar_coords_popup(chave):
    """Carrega coordenadas salvas para um popup específico."""
    try:
        if _os.path.exists(_POPUP_COORDS_FILE):
            with open(_POPUP_COORDS_FILE, 'r') as f:
                dados = _json.load(f)
            return dados.get(chave)
    except Exception:
        pass
    return None


def _salvar_coords_popup(chave, x, y):
    """Salva coordenadas de clique bem-sucedido para uso futuro."""
    try:
        dados = {}
        if _os.path.exists(_POPUP_COORDS_FILE):
            with open(_POPUP_COORDS_FILE, 'r') as f:
                dados = _json.load(f)
        dados[chave] = {'x': x, 'y': y}
        _os.makedirs(_os.path.dirname(_POPUP_COORDS_FILE), exist_ok=True)
        with open(_POPUP_COORDS_FILE, 'w') as f:
            _json.dump(dados, f, indent=2)
        logger.info(f"[PopupCache] Coordenadas salvas: {chave} = ({x}, {y})")
    except Exception as e:
        logger.warning(f"[PopupCache] Erro ao salvar coords: {e}")


def _clicar_pyautogui(x, y, label='popup'):
    """Clica com o mouse real via pyautogui nas coordenadas informadas."""
    if EXECUTAR_EM_SEGUNDO_PLANO:
        # Em segundo plano não movemos o mouse físico (roubaria o controle do
        # usuário). Os popups são tratados por DOM nos handlers correspondentes.
        return False
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.moveTo(x, y, duration=0.3)
        import time as _t; _t.sleep(0.15)
        pyautogui.click(x, y)
        _t.sleep(0.3)
        pyautogui.click(x, y)
        logger.info(f"[Mouse] Clicou em {label} ({x}, {y})")
        return True
    except Exception as e:
        logger.warning(f"[Mouse] Erro ao clicar em {label}: {e}")
        return False


def _verificar_e_clicar_popup_fazer_login(driver, callback_status=None, timeout_aparecer=10):
    """
    Detecta e clica no botão 'Fazer login' do popup 'Fazer login como'.
    O popup é renderizado pelo BROWSER (fora do DOM) — usa APENAS pyautogui
    com detecção visual por screenshot. Salva coords para execuções futuras.

    timeout_aparecer: segundos a aguardar o popup aparecer visualmente antes
    de desistir (FASE 2). Usar valor menor quando chamado após preencher as
    credenciais (o popup já deveria estar visível).
    """
    # ISOLAMENTO POR-NAVEGADOR: em SEGUNDO PLANO / PARALELO NÃO usamos
    # pyautogui/screenshot — capturar a TELA INTEIRA custa caro e, com N
    # navegadores, poderia cross-detectar a janela de OUTRO worker; e o clique
    # físico já está desligado (`_clicar_pyautogui` retorna False). O popup nativo
    # "Fazer login como" é dispensado por ESC via CDP dentro do fluxo de login.
    if EXECUTAR_EM_SEGUNDO_PLANO or _MODO_PARALELO:
        return False
    CHAVE_CACHE = 'fazer_login_popup'

    def _escanear_botoes_azuis(y_max_pct=0.50):
        """
        Captura screenshot e retorna clusters de pixels azul-Facebook.
        Usa numpy para velocidade. Retorna (cx, cy, tamanho) com centro
        calculado pelo bounding box (não centroide) para máxima precisão.
        """
        try:
            import pyautogui
            import numpy as np
            pyautogui.FAILSAFE = False
            shot = pyautogui.screenshot()
            w, h = shot.size
            x0, x1 = w // 5, 4 * w // 5
            y0, y1 = int(h * 0.03), int(h * y_max_pct)

            arr = np.array(shot.crop((x0, y0, x1, y1)))
            R, G, B = arr[:,:,0], arr[:,:,1], arr[:,:,2]
            mask = (B.astype(int) - R.astype(int) > 70) & (B > 150) & (G > 70) & (R < 140)

            ys_px, xs_px = np.where(mask)
            if len(xs_px) == 0:
                return []

            # Converter de volta para coords absolutas
            xs_abs = xs_px + x0
            ys_abs = ys_px + y0

            # Clusterizar por faixa de y (12px por faixa)
            faixas = {}
            for xa, ya in zip(xs_abs, ys_abs):
                faixa = int(ya) // 12
                faixas.setdefault(faixa, []).append((int(xa), int(ya)))

            clusters = []
            for pts in faixas.values():
                if len(pts) < 4:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                cx = (min(xs) + max(xs)) // 2
                cy = (min(ys) + max(ys)) // 2
                clusters.append((cx, cy, len(pts)))

            clusters.sort(key=lambda c: c[2], reverse=True)
            return clusters
        except Exception as e:
            logger.warning(f"[Mouse] Erro ao escanear: {e}")
            return []

    def _popup_visivel_visualmente():
        """Retorna True se existe botão azul na região do popup (topo da tela)."""
        return len(_escanear_botoes_azuis(y_max_pct=0.45)) > 0

    try:
        if callback_status:
            callback_status("Verificando popup 'Fazer login como'...")

        # ── FASE 1: Coordenadas salvas (execução rápida) ──
        coords_salvas = _carregar_coords_popup(CHAVE_CACHE)
        if coords_salvas:
            logger.info(f"[Login] Coords salvas encontradas: {coords_salvas}")
            # Aguardar popup aparecer visualmente (máx 8s)
            for _ in range(16):
                if _popup_visivel_visualmente():
                    break
                time.sleep(0.5)

            if _popup_visivel_visualmente():
                if callback_status:
                    callback_status(f"Clicando popup com coords salvas ({coords_salvas['x']},{coords_salvas['y']})...")
                time.sleep(0.3)
                _clicar_pyautogui(coords_salvas['x'], coords_salvas['y'], 'fazer_login_salvo')
                time.sleep(1.5)
                if not _popup_visivel_visualmente():
                    logger.info("[Login] Popup fechou com coords salvas!")
                    return True
                logger.warning("[Login] Coords salvas não funcionaram. Redetectando...")

        # ── FASE 2: Aguardar popup aparecer visualmente ──
        start = time.time()
        popup_presente = False
        while time.time() - start < timeout_aparecer:
            if _popup_visivel_visualmente():
                popup_presente = True
                break
            time.sleep(0.5)

        if not popup_presente:
            logger.info(f"[Login] Nenhum popup azul detectado na tela ({timeout_aparecer}s). Seguindo sem popup.")
            return False

        logger.info("[Login] Popup 'Fazer login como' detectado visualmente!")
        if callback_status:
            callback_status("Popup detectado! Clicando com mouse real...")

        time.sleep(0.5)  # aguardar renderização completa

        # ── FASE 3: Clicar em loop até popup sumir visualmente ──
        for tentativa in range(25):
            if not _popup_visivel_visualmente():
                logger.info(f"[Login] Popup sumiu na tentativa {tentativa + 1}!")
                return True

            clusters = _escanear_botoes_azuis()
            logger.info(f"[Login] Tentativa {tentativa + 1}/25 — {len(clusters)} clusters azuis")

            if clusters:
                # O botão "Fazer login" fica ABAIXO do título "Fazer login como"
                # → pegar o cluster com MAIOR y (mais baixo na tela) dentro do popup
                clusters_topo = sorted(clusters, key=lambda c: c[1], reverse=True)
                cx, cy, tam = clusters_topo[0]

                logger.info(f"[Login] Clicando cluster ({cx},{cy}) tam={tam}")
                if callback_status:
                    callback_status(f"Clicando popup ({cx},{cy})...")
                _clicar_pyautogui(cx, cy, 'fazer_login')
                time.sleep(1.3)

                if not _popup_visivel_visualmente():
                    _salvar_coords_popup(CHAVE_CACHE, cx, cy)
                    logger.info(f"[Login] Popup fechou! Coords salvas ({cx},{cy}).")
                    return True
            else:
                # Fallback por posição estimada da janela
                try:
                    import pyautogui
                    win_x = driver.execute_script("return window.screenX || window.screenLeft || 0;")
                    win_y = driver.execute_script("return window.screenY || window.screenTop || 0;")
                    win_w = driver.execute_script("return window.outerWidth || 1366;")
                    cx = win_x + win_w // 2 - 60
                    cy = win_y + 155
                    logger.info(f"[Login] Fallback estimado ({cx},{cy})")
                    _clicar_pyautogui(cx, cy, 'fazer_login_est')
                    time.sleep(1.3)
                    if not _popup_visivel_visualmente():
                        _salvar_coords_popup(CHAVE_CACHE, cx, cy)
                        return True
                except Exception:
                    pass

            time.sleep(0.4)

        if not _popup_visivel_visualmente():
            return True

        logger.error("[Login] Popup persistiu após 25 tentativas.")
        return False

    except Exception as e:
        logger.warning(f"[Login] Erro em _verificar_e_clicar_popup_fazer_login: {e}")
        return False


def _tratar_popup_ok_entendi(driver, callback_status=None):
    """
    Detecta e clica em 'Ok, entendi' no popup 'Faça login sem complicação' /
    'Remember Password' que aparece após redirecionamento de login.
    Usa APENAS detecção visual (pyautogui screenshot) pois o popup é
    renderizado pelo browser, fora do DOM da página.
    """
    # Em segundo plano, evitamos a captura de tela + mouse físico. O popup
    # "Ok, entendi" também é tratado por DOM em _tratar_popups_login_facebook.
    if EXECUTAR_EM_SEGUNDO_PLANO:
        return False

    CHAVE_CACHE = 'ok_entendi_popup'

    def _escanear_botoes_azuis_topo():
        """
        Escaneia a região do topo da tela procurando botões azuis.
        Usa numpy para velocidade. Retorna (cx, cy, tamanho) com bounding box.
        """
        try:
            import pyautogui
            import numpy as np
            pyautogui.FAILSAFE = False
            shot = pyautogui.screenshot()
            w, h = shot.size
            x0, x1 = w // 5, 4 * w // 5
            y0, y1 = int(h * 0.03), int(h * 0.42)

            arr = np.array(shot.crop((x0, y0, x1, y1)))
            R, G, B = arr[:,:,0], arr[:,:,1], arr[:,:,2]
            mask = (B.astype(int) - R.astype(int) > 70) & (B > 150) & (G > 70) & (R < 140)

            ys_px, xs_px = np.where(mask)
            if len(xs_px) == 0:
                return []

            xs_abs = xs_px + x0
            ys_abs = ys_px + y0

            faixas = {}
            for xa, ya in zip(xs_abs, ys_abs):
                faixa = int(ya) // 12
                faixas.setdefault(faixa, []).append((int(xa), int(ya)))

            clusters = []
            for pts in faixas.values():
                if len(pts) < 4:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                cx = (min(xs) + max(xs)) // 2
                cy = (min(ys) + max(ys)) // 2
                clusters.append((cx, cy, len(pts)))

            clusters.sort(key=lambda c: c[2], reverse=True)
            return clusters
        except Exception as e:
            logger.warning(f"[OkEntendi] Erro ao escanear: {e}")
            return []

    def _popup_visivel_visualmente():
        return len(_escanear_botoes_azuis_topo()) > 0

    # Verificar se há popup visual por até 8s após login
    try:
        start = time.time()
        while time.time() - start < 8:
            if _popup_visivel_visualmente():
                break
            time.sleep(0.5)

        if not _popup_visivel_visualmente():
            return False

        logger.info("[Login] Popup pós-login detectado visualmente (Ok/Remember)!")
        if callback_status:
            callback_status("Popup 'Ok, entendi' detectado! Clicando...")

        # Tentar coordenadas salvas primeiro
        coords = _carregar_coords_popup(CHAVE_CACHE)
        if coords:
            time.sleep(0.4)
            _clicar_pyautogui(coords['x'], coords['y'], 'ok_entendi_salvo')
            time.sleep(1.2)
            if not _popup_visivel_visualmente():
                logger.info("[Login] Popup 'Ok, entendi' fechou com coords salvas!")
                return True

        time.sleep(0.5)

        for tentativa in range(20):
            if not _popup_visivel_visualmente():
                return True

            clusters = _escanear_botoes_azuis_topo()
            if clusters:
                # 'Ok, entendi' é o botão ESQUERDO — menor x
                clusters.sort(key=lambda c: c[0])
                cx, cy, tam = clusters[0]
                logger.info(f"[OkEntendi] Clicando botão esquerdo ({cx},{cy})")
                _clicar_pyautogui(cx, cy, 'ok_entendi')
                time.sleep(1.2)
                if not _popup_visivel_visualmente():
                    _salvar_coords_popup(CHAVE_CACHE, cx, cy)
                    logger.info(f"[Login] 'Ok, entendi' fechado! Coords salvas ({cx},{cy})")
                    return True
            else:
                # Fallback por posição estimada
                try:
                    win_x = driver.execute_script("return window.screenX || window.screenLeft || 0;")
                    win_y = driver.execute_script("return window.screenY || window.screenTop || 0;")
                    win_w = driver.execute_script("return window.outerWidth || 1366;")
                    cx = win_x + int(win_w * 0.40)
                    cy = win_y + 165
                    logger.info(f"[OkEntendi] Fallback estimado ({cx},{cy})")
                    _clicar_pyautogui(cx, cy, 'ok_entendi_est')
                    time.sleep(1.2)
                    if not _popup_visivel_visualmente():
                        _salvar_coords_popup(CHAVE_CACHE, cx, cy)
                        return True
                except Exception:
                    pass
            time.sleep(0.5)

        return not _popup_visivel_visualmente()
    except Exception as e:
        logger.warning(f"[Login] Erro ao tratar popup ok_entendi: {e}")
        return False


def _tratar_teen_account_interstitial(driver, callback_status=None):
    """
    Detecta e atravessa o interstitial pós-login que aparece em alguns perfis
    ('teen-account-interstitial' / graduation_day — "You're 18 now, review
    settings"). O fluxo varia por perfil, mas é sempre clicar o botão PRIMÁRIO
    (azul, no rodapé) em sequência até sair do interstitial:
        Review settings → Next → Done    (ou See your settings → Done, etc.)
    INDEPENDENTE DE IDIOMA e robusto ao React do FB (clique via eventos reais).
    Retorna True se saiu do interstitial.
    """
    try:
        if 'teen-account-interstitial' not in (driver.current_url or '').lower():
            return False

        logger.info("[Login] Interstitial pós-login (teen/graduation) detectado!")
        if callback_status:
            callback_status("Tela de revisão de configurações detectada — avançando...")

        # Textos dos botões PRIMÁRIOS dessas telas (vários idiomas).
        textos = [
            'review settings', 'see your settings', 'next', 'done', 'continue',
            'got it', 'finish', 'ok',
            'revisar configurações', 'revisar', 'ver configurações',
            'avançar', 'próximo', 'proximo', 'continuar', 'concluir',
            'concluído', 'concluido', 'pronto', 'finalizar', 'entendi',
            'revisar configuración', 'siguiente', 'listo', 'continuar',
        ]

        avancou_alguma = False
        for _ in range(12):
            url = (driver.current_url or '').lower()
            if 'teen-account-interstitial' not in url:
                logger.info("[Teen] Interstitial atravessado com sucesso.")
                if callback_status:
                    callback_status("Configurações revisadas — seguindo para a home.")
                return True

            clicou = driver.execute_script("""
                var alvos = arguments[0];
                function visivel(el){
                    var r = el.getBoundingClientRect();
                    var s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 &&
                           s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
                }
                function clicarReal(el){
                    if(!el) return false;
                    var r = el.getBoundingClientRect();
                    var cx = r.left + r.width/2, cy = r.top + r.height/2;
                    var base = {bubbles:true, cancelable:true, view:window, clientX:cx, clientY:cy, button:0, buttons:1};
                    ['pointerover','pointerenter','pointermove','pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){
                        var ev; try { ev = (t.indexOf('pointer')===0) ? new PointerEvent(t,base) : new MouseEvent(t,base); } catch(e){ ev = new MouseEvent(t,base); }
                        el.dispatchEvent(ev);
                    });
                    try { el.click(); } catch(e){}
                    return true;
                }
                var els = document.querySelectorAll('div[role="button"], a[role="button"], button, [role="button"]');
                var cands = [];
                for (var i=0;i<els.length;i++){
                    if(!visivel(els[i])) continue;
                    var t = (els[i].innerText || els[i].textContent || '').trim().toLowerCase();
                    if(!t || t.length > 30) continue;        // botão de ação tem texto curto
                    for (var j=0;j<alvos.length;j++){
                        if(t === alvos[j] || t.indexOf(alvos[j]) !== -1){
                            var r = els[i].getBoundingClientRect();
                            cands.push({el: els[i], top: r.top, prio: j});
                            break;
                        }
                    }
                }
                if(cands.length === 0) {
                    // FIX 2026-10-12 — fallback IDIOMA-AGNÓSTICO (a tela já é garantida
                    // pela URL teen-account-interstitial): botão PRIMÁRIO AZUL mais
                    // abaixo (rodapé). Sem isto, em VI/RU/HI/TR... nenhum texto casava e
                    // o login girava aqui até o deadline.
                    for (var k=0;k<els.length;k++){
                        if(!visivel(els[k])) continue;
                        var bg = (getComputedStyle(els[k]).backgroundColor || '');
                        if (bg.indexOf('8, 102, 255') !== -1 || bg.indexOf('24, 119, 242') !== -1
                            || bg.indexOf('0, 100, 224') !== -1 || bg.indexOf('11, 105, 255') !== -1) {
                            cands.push({el: els[k], top: els[k].getBoundingClientRect().top, prio: 0});
                        }
                    }
                    if(cands.length === 0) return false;
                }
                // Primário = mais ABAIXO na tela (rodapé). Em empate, menor prio (lista).
                cands.sort(function(a,b){ return (b.top - a.top) || (a.prio - b.prio); });
                clicarReal(cands[0].el);
                return true;
            """, textos)

            if clicou:
                avancou_alguma = True
                logger.info("[Teen] Botão primário do interstitial clicado.")
            else:
                # Fallback nativo: clica o botão de rodapé com texto-alvo via Selenium.
                try:
                    botoes = driver.find_elements(
                        By.XPATH, "//div[@role='button'] | //a[@role='button'] | //button")
                    melhor = None
                    for b in botoes:
                        try:
                            txt = (b.text or '').strip().lower()
                        except Exception:
                            continue
                        if not txt or len(txt) > 30:
                            continue
                        if any(a in txt for a in textos):
                            if melhor is None or b.location['y'] > melhor.location['y']:
                                melhor = b
                    if melhor is not None:
                        try:
                            ActionChains(driver).move_to_element(melhor).pause(0.2).click(melhor).perform()
                        except Exception:
                            driver.execute_script("arguments[0].click();", melhor)
                        avancou_alguma = True
                        logger.info("[Teen] Botão primário clicado via fallback nativo.")
                except Exception:
                    pass

            _delay_pagina(1.2, 2.2)
            try:
                _esperar_pagina_carregar(driver, timeout=8)
            except Exception:
                pass

        fora = 'teen-account-interstitial' not in (driver.current_url or '').lower()
        if not fora:
            logger.warning("[Teen] Interstitial ainda ativo após tentativas (avancou=%s).", avancou_alguma)
        return fora

    except Exception as e:
        logger.warning(f"[Login] Erro ao tratar interstitial pós-login: {e}")
        return False


def _focar_janela_navegador(driver):
    """
    Traz a janela do navegador para o PRIMEIRO PLANO (foreground) no Windows.
    Isso é essencial para que teclas enviadas via pyautogui (ex.: ESC) cheguem
    de fato ao navegador — caso contrário o ESC vai para a janela que estiver
    em foco no SO (que pode não ser o navegador controlado).

    Encontra a janela pelo título da aba (driver.title) e, como reforço, por
    palavras-chave de navegador. Para trazer ao primeiro plano usa
    AttachThreadInput (e NÃO o "truque do ALT"): pressionar ALT no Chrome ATIVA
    o menu de 3 pontinhos (canto superior direito), o que o usuário via piscar a
    cada foco. AttachThreadInput contorna a restrição de SetForegroundWindow sem
    enviar nenhuma tecla. Retorna True se conseguiu focar.
    """
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Definir argtypes para não truncar HWND (64-bit) em ints de 32-bit
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]

        try:
            titulo_pagina = (driver.title or '').strip().lower()
        except Exception:
            titulo_pagina = ''

        palavras_navegador = ['facebook', 'brave', 'chrome', 'chromium',
                              'edge', 'ixbrowser', 'ads', 'mozilla']

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        alvo = {'hwnd': None, 'hwnd_fallback': None}

        def _callback(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            titulo = buff.value.lower()
            # Prioridade 1: bate com o título exato da aba (ex.: "facebook")
            if titulo_pagina and titulo_pagina in titulo:
                alvo['hwnd'] = hwnd
                return False
            # Prioridade 2: qualquer janela de navegador (fallback)
            if alvo['hwnd_fallback'] is None:
                for p in palavras_navegador:
                    if p in titulo:
                        alvo['hwnd_fallback'] = hwnd
                        break
            return True

        user32.EnumWindows(EnumWindowsProc(_callback), 0)
        hwnd = alvo['hwnd'] or alvo['hwnd_fallback']
        if not hwnd:
            return False

        # SW_RESTORE = 9 (caso esteja minimizada)
        user32.ShowWindow(hwnd, 9)

        # Foreground SEM tecla ALT: anexa a fila de input da thread em foco à da
        # janela-alvo, o que libera o SetForegroundWindow entre processos. Assim
        # não tocamos no menu de 3 pontinhos do Chrome.
        hwnd_fg = user32.GetForegroundWindow()
        tid_fg = user32.GetWindowThreadProcessId(hwnd_fg, None) if hwnd_fg else 0
        tid_alvo = user32.GetWindowThreadProcessId(hwnd, None)
        tid_atual = kernel32.GetCurrentThreadId()

        anexou = []
        try:
            if tid_fg and tid_fg != tid_alvo:
                user32.AttachThreadInput(tid_fg, tid_alvo, True)
                anexou.append((tid_fg, tid_alvo))
            if tid_atual not in (tid_fg, tid_alvo):
                user32.AttachThreadInput(tid_atual, tid_alvo, True)
                anexou.append((tid_atual, tid_alvo))
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            for a, b in anexou:
                try:
                    user32.AttachThreadInput(a, b, False)
                except Exception:
                    pass
        time.sleep(0.25)
        return True
    except Exception as e:
        logger.info(f"[Login] Não foi possível focar a janela do navegador: {e}")
        return False


def _pressionar_esc_real():
    """
    Envia uma tecla ESC REAL para a janela em foco usando a Win32 API via
    ctypes (biblioteca padrão — SEMPRE disponível, mesmo se pyautogui não
    estiver instalado/empacotado). É assim que a bolha nativa do navegador
    ("Fazer login como ...") é fechada de forma confiável.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        VK_ESCAPE = 0x1B
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_ESCAPE, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception as e:
        logger.info(f"[Login] ESC via ctypes indisponível: {e}")
        return False


def _parse_cookie_pairs(cookie_raw):
    """Converte 'c_user=..;xs=..;fr=..' em dict {nome: valor}, PRESERVANDO os
    ':' que existem dentro do valor de 'xs'/'fr'. Decodifica base64 se for o
    caso."""
    s = (cookie_raw or '').strip()
    if not s:
        return {}
    # Detectar/decodificar base64 (quando não parece "nome=valor;...")
    try:
        import base64 as _b64
        primeiro = s.split(';')[0]
        if '=' not in primeiro and len(s) > 40:
            dec = _b64.b64decode(s).decode('utf-8', 'ignore')
            if 'c_user' in dec or 'xs=' in dec:
                s = dec
    except Exception:
        pass
    s = s.strip().rstrip(';')
    pares = {}
    atual = None
    for token in s.split(';'):
        token = token.strip()
        if not token:
            continue
        if '=' in token:
            nome, valor = token.split('=', 1)
            nome = nome.strip()
            pares[nome] = valor.strip()
            atual = nome
        elif atual:
            pares[atual] += ';' + token
    return pares


def _injetar_cookies_login(driver, perfil_data, callback_status=None):
    """
    Injeta os cookies do perfil DIRETAMENTE no contexto do navegador via
    Playwright (context.add_cookies), como GARANTIA/reforço à importação nativa
    do multilogin (AdsPower/IXBrowser) — que às vezes não aplica os cookies.

    Atributos corretos para o Facebook:
      - domain '.facebook.com', path '/', Secure
      - SameSite=None nos cookies de sessão (c_user, xs); Lax nos demais
      - expiração longa (~6 meses)

    Retorna a quantidade de cookies injetados (0 em falha). NÃO navega — o
    chamador navega depois para aplicar.
    """
    ctx = getattr(driver, 'context', None)
    if ctx is None:
        return 0

    # Fonte 1: cookie_json (lista no formato IXBrowser, já parseada pelo parser)
    cookies_src = []
    cookie_json = perfil_data.get('cookie_json', '') or ''
    if cookie_json:
        try:
            import json as _json
            data = _json.loads(cookie_json)
            if isinstance(data, list):
                cookies_src = [{'name': c.get('name', ''), 'value': c.get('value', '')}
                               for c in data if isinstance(c, dict)]
        except Exception:
            cookies_src = []
    # Fonte 2 (fallback): parsear o cookie_raw na hora
    if not cookies_src:
        pares = _parse_cookie_pairs(perfil_data.get('cookie_raw', '') or '')
        cookies_src = [{'name': k, 'value': v} for k, v in pares.items()]

    if not cookies_src:
        return 0

    expires = float(int(time.time()) + 180 * 24 * 3600)  # ~6 meses
    http_only = {'xs', 'fr', 'datr', 'sb'}
    samesite_none = {'c_user', 'xs'}

    pw_cookies = []
    nomes = set()
    for c in cookies_src:
        nome = (c.get('name') or '').strip()
        valor = c.get('value')
        if not nome or valor is None:
            continue
        nomes.add(nome)
        pw_cookies.append({
            'name': nome,
            'value': str(valor),
            'domain': '.facebook.com',
            'path': '/',
            'expires': expires,
            'httpOnly': nome in http_only,
            'secure': True,
            'sameSite': 'None' if nome in samesite_none else 'Lax',
        })
    # Garantir idioma pt-BR
    if 'locale' not in nomes:
        pw_cookies.append({
            'name': 'locale', 'value': 'pt_BR', 'domain': '.facebook.com',
            'path': '/', 'expires': expires, 'httpOnly': False,
            'secure': True, 'sameSite': 'Lax',
        })

    if not pw_cookies:
        return 0

    try:
        ctx.add_cookies(pw_cookies)
    except Exception as e:
        logger.warning("[Cookies] add_cookies falhou: %s", e)
        return 0

    logger.info("[Cookies] %d cookies injetados via Playwright (%s).",
                len(pw_cookies), ', '.join(sorted(nomes)))
    if callback_status:
        callback_status(f"Cookies injetados no navegador ({len(pw_cookies)}).")
    return len(pw_cookies)


def _esc_via_dom(driver):
    """
    Envia ESC apenas pelo DOM (body.send_keys(ESC)) — SEM roubar o foco do SO e
    SEM tocar no menu do navegador. Fecha modais in-DOM. Usado nas telas pós-
    login (2FA/checkpoint/trust/consent/home), onde NÃO há a bolha nativa
    "Fazer login como" — assim evitamos focar a janela à toa (o que fazia o menu
    de 3 pontinhos do Chrome piscar). Best-effort.
    """
    try:
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    except Exception:
        pass


def _dispensar_popup_navegador_login(driver):
    """
    Dispensa a bolha NATIVA do navegador "Fazer login como ..." (autofill do
    Chrome/Chromium), que é pintada por cima da página, FORA do DOM do
    Facebook. NÃO existe seletor HTML para ela — não adianta tentar "detectá-la"
    no código-fonte da página, pois ela é desenhada por JavaScript do próprio
    navegador, por fora do DOM.

    A ÚNICA forma confiável de fechá-la é um ESC REAL de teclado (exatamente o
    ESC manual que o usuário aperta): FOCAR a janela do navegador e enviar
    VK_ESCAPE via Win32/ctypes (sempre disponível). Por isso, mesmo em MODO
    SEGUNDO PLANO, este passo específico envia um ESC real — a bolha nativa não
    fecha por DOM. Reforço por pyautogui (quando existir) e por DOM no fim.
    Nunca lança exceção — é best-effort.
    """
    # PARALELO: NUNCA usar foco/ESC de nível-SO — em várias janelas de título
    # "Facebook", o SetForegroundWindow/ESC real cairia na janela do worker ERRADO
    # (foi a causa de uma janela travar enquanto a outra rodava). Em paralelo só
    # usamos as etapas por DOM/CDP (abaixo), que são por-driver e isoladas.
    if not _MODO_PARALELO:
        # 1) Garantir que a janela do navegador está em foco (senão o ESC real se
        #    perde para outra janela do SO).
        focou = _focar_janela_navegador(driver)

        # 2) ESC REAL via Win32/ctypes — é o que de fato fecha a bolha nativa
        #    "Fazer login como ..." (NÃO depende de pyautogui).
        time.sleep(0.2)
        ok_ctypes = _pressionar_esc_real()
        time.sleep(0.25)
        # Reforço: às vezes o primeiro ESC só ativa a janela
        _pressionar_esc_real()
        time.sleep(0.2)
        logger.info(f"[Login] ESC real enviado via ctypes={ok_ctypes} (janela focada={focou}).")

        # 3) ESC via pyautogui também, quando disponível (reforço extra)
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.press('esc')
            time.sleep(0.15)
        except Exception:
            pass
    else:
        # Em paralelo: ESC por CDP (per-driver) — vai para a PÁGINA do próprio
        # navegador, sem tocar no foco do SO nem em outras janelas.
        logger.info("[Login] Modo paralelo: pulando foco/ESC de nível-SO (usa só DOM/CDP).")
        try:
            driver.keyboard.press('Escape')
        except Exception:
            pass

    # 4) ESC via DOM (reforço — fecha modais in-DOM; não fecha a bolha nativa)
    try:
        body = driver.find_element(By.TAG_NAME, 'body')
        body.send_keys(Keys.ESCAPE)
    except Exception:
        pass

    # Clicar "Cancelar"/"Agora não" da bolha de conta salva, quando for in-DOM
    # (não loga na conta antiga e não exige foco do SO).
    try:
        driver.execute_script("""
            var alvos = ['cancelar', 'agora não', 'agora nao', 'cancel', 'not now'];
            var els = document.querySelectorAll('button, div[role="button"], span[role="button"], a[role="button"]');
            for (var i = 0; i < els.length; i++) {
                var t = (els[i].innerText || els[i].textContent || '').trim().toLowerCase();
                if (alvos.indexOf(t) !== -1) { els[i].click(); return true; }
            }
            return false;
        """)
    except Exception:
        pass


def _clicar_entrar_facebook(driver):
    """
    Dispara UM clique no botão ENTRAR do Facebook via JavaScript
    (arguments[0].click()). O clique JS aciona o handler do formulário no nível
    do DOM e ATRAVESSA a bolha nativa do navegador (que é só uma camada de UI
    do SO e não torna a página inerte) — assim o login é enviado com as
    credenciais que o BOT digitou. Retorna True se encontrou e clicou no botão.
    A lógica de retentativa/refill fica no chamador (onde as credenciais estão
    disponíveis), pois o ESC pode reverter o autofill e esvaziar os campos.
    """
    try:
        return bool(driver.execute_script("""
            var sels = ['button[name="login"]', '#loginbutton', 'button[type="submit"]'];
            for (var i = 0; i < sels.length; i++) {
                var el = document.querySelector(sels[i]);
                if (el) { el.click(); return true; }
            }
            // Fallback: elemento clicável com texto "Entrar"/"Log in"
            var els = document.querySelectorAll('button, div[role="button"], span[role="button"]');
            for (var j = 0; j < els.length; j++) {
                var t = (els[j].innerText || '').trim().toLowerCase();
                if (t === 'entrar' || t === 'log in' || t === 'login') { els[j].click(); return true; }
            }
            return false;
        """))
    except Exception as e:
        logger.warning(f"[Login] Erro ao clicar Entrar via JS: {e}")
        return False


def _tratar_confiar_dispositivo(driver, callback_status=None):
    """
    Trata a tela "You're logged in. Trust this device?" (pós-2FA), que NÃO
    avança sozinha — exige clique. Alguns perfis caem direto nela em vez do
    checkpoint "Automated Behavior".

    INDEPENDENTE DE IDIOMA:
      - Detecta a tela pela URL ('remember_browser'), que é igual em qualquer
        idioma (inglês, pt-BR, pt-PT, espanhol, hindi, indonésio, russo,
        chinês, japonês, vietnamita, etc.).
      - Clica no botão PRIMÁRIO pela POSIÇÃO (o de cima = "Trust this device"),
        sem depender do texto.
    É uma página do Facebook (no DOM), então o clique via JS funciona.
    Retorna True se clicou.
    """
    try:
        url = driver.current_url.lower()
        if 'remember_browser' not in url:
            return False

        if callback_status:
            callback_status("Tela 'Confiar neste dispositivo' detectada. Confirmando...")
        logger.info("[Login] Tela 'Trust this device' (remember_browser) detectada.")

        # Clica RÁPIDO, com retry interno curto (sem esperas longas) — antes
        # demorava e o usuário tinha que clicar manualmente.
        for tentativa in range(6):
            clicou = driver.execute_script("""
                function visivel(el) {
                    var r = el.getBoundingClientRect();
                    var s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 &&
                           s.visibility !== 'hidden' && s.display !== 'none' &&
                           s.opacity !== '0';
                }
                // CLIQUE REAL: o Facebook é React e frequentemente IGNORA um
                // .click() programático no <div role="button">. Disparamos a
                // sequência completa de eventos de ponteiro/mouse (como um clique
                // humano) no centro do elemento — isso aciona o handler do React.
                function clicarReal(el) {
                    if (!el) return false;
                    var r = el.getBoundingClientRect();
                    var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
                    var base = {bubbles:true, cancelable:true, view:window,
                                clientX:cx, clientY:cy, button:0, buttons:1};
                    var seq = ['pointerover','pointerenter','pointermove','pointerdown',
                               'mousedown','pointerup','mouseup','click'];
                    seq.forEach(function(tipo){
                        var ev;
                        try {
                            if (tipo.indexOf('pointer') === 0)
                                ev = new PointerEvent(tipo, base);
                            else
                                ev = new MouseEvent(tipo, base);
                        } catch(e) { ev = new MouseEvent(tipo, base); }
                        el.dispatchEvent(ev);
                    });
                    try { el.click(); } catch(e) {}  // reforço
                    return true;
                }
                function clicavel(el) {
                    return el.closest('[role="button"]') || el.closest('button')
                        || el.closest('a[role="button"]') || el.closest('a') || el;
                }
                // 1) PRIMÁRIO por TEXTO (vários idiomas) — "Trust this device"
                var textos = ['trust this device','trust device','confiar neste dispositivo',
                              'confiar neste aparelho','confiar no dispositivo','confiar',
                              'confiar en este dispositivo','confiar en este equipo',
                              'fiar-se neste dispositivo','approuver cet appareil',
                              'faire confiance à cet appareil','diesem gerät vertrauen',
                              'fidati di questo dispositivo','percayai perangkat ini',
                              'tin cậy thiết bị này','доверять этому устройству',
                              'このデバイスを信頼','信任此设备','信任這個裝置','이 기기 신뢰'];
                var els = document.querySelectorAll('a[role="button"], div[role="button"], button, span, div');
                for (var i = 0; i < els.length; i++) {
                    if (!visivel(els[i])) continue;
                    var t = (els[i].innerText || els[i].textContent || '').trim().toLowerCase();
                    if (t.length > 60) continue;  // evita pegar containers grandes
                    for (var j = 0; j < textos.length; j++) {
                        if (t.indexOf(textos[j]) !== -1) {
                            clicarReal(clicavel(els[i]));
                            return 'texto';
                        }
                    }
                }
                // 2) Fallback por POSIÇÃO: botão de ação do TOPO (o primário azul)
                var cands = [];
                for (var k = 0; k < els.length; k++) {
                    if (els[k].tagName === 'SPAN') continue;
                    if (els[k].getAttribute('role') !== 'button' && els[k].tagName !== 'BUTTON') continue;
                    if (!visivel(els[k])) continue;
                    var r2 = els[k].getBoundingClientRect();
                    if (r2.width >= 120 && r2.height >= 28 && r2.top > 110) {
                        cands.push({el: els[k], top: r2.top});
                    }
                }
                if (cands.length === 0) return false;
                cands.sort(function(a, b){ return a.top - b.top; });
                clicarReal(cands[0].el);  // o de cima = "Trust this device" (primário)
                return 'posicao';
            """)

            if clicou:
                logger.info("[Login] Botão 'Trust this device' clicado (via %s, tentativa %s).",
                            clicou, tentativa + 1)
                _delay_pagina(1.5, 3.0)
                # Se saiu da tela, sucesso
                if 'remember_browser' not in driver.current_url.lower():
                    return True
                # Senão tenta de novo no próximo ciclo
            else:
                # Página pode ainda estar renderizando — esperar um pouco
                time.sleep(0.7)

        # FALLBACK FINAL: clique NATIVO via Selenium (ActionChains) — um clique
        # real do SO, o mais confiável para o React do Facebook quando o
        # dispatch de eventos JS não "pega".
        try:
            botoes = driver.find_elements(
                By.XPATH, "//div[@role='button'] | //a[@role='button'] | //button")
            alvos_txt = ['confiar neste dispositivo', 'trust this device', 'trust device',
                         'confiar en este dispositivo', 'confiar neste aparelho', 'confiar']
            for b in botoes:
                try:
                    txt = (b.text or '').strip().lower()
                except Exception:
                    continue
                if not txt or len(txt) > 60:
                    continue
                if any(a in txt for a in alvos_txt):
                    try:
                        ActionChains(driver).move_to_element(b).pause(0.2).click(b).perform()
                    except Exception:
                        try:
                            b.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", b)
                    _delay_pagina(1.5, 3.0)
                    if 'remember_browser' not in driver.current_url.lower():
                        logger.info("[Login] 'Trust this device' confirmado via clique NATIVO Selenium.")
                        return True
                    break
        except Exception as _ne:
            logger.warning("[Login] Fallback nativo 'Trust this device' falhou: %s", _ne)

        logger.warning("[Login] Não foi possível confirmar 'Trust this device' após retries.")
        return False
    except Exception as e:
        logger.warning(f"[Login] Erro ao tratar 'Trust this device': {e}")
        return False


def _tratar_cookies_facebook(driver, callback_status=None):
    """
    Aceita o banner de cookies/permissões do Facebook, se presente.
    INDEPENDENTE DE IDIOMA: usa primeiro o atributo oficial 'data-cookiebanner'
    (igual em qualquer língua) e, como reforço, o texto de 'aceitar/allow' em
    vários idiomas. Best-effort — nunca quebra o fluxo.
    """
    try:
        clicado = driver.execute_script("""
            function vis(el){
                var r = el.getBoundingClientRect();
                var s = getComputedStyle(el);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
            }
            // 1) Atributos oficiais do banner de cookies do FB (idioma-independente)
            var b = document.querySelector('[data-cookiebanner="accept_button"]')
                 || document.querySelector('[data-testid="cookie-policy-manage-dialog-accept-button"]')
                 || document.querySelector('[data-cookiebanner="accept_only_essential_button"]');
            if (b && vis(b)) { b.click(); return true; }
            // 2) Texto multi-idioma de "aceitar cookies"
            var textos = ['allow all cookies','permitir todos os cookies','accept all cookies',
                          'cho phép tất cả cookie','cho phép tất cả',
                          'accept all','aceitar todos','allow all','permitir todos',
                          'aceptar todas','tout accepter','alle cookies erlauben',
                          'aceitar tudo','permitir cookies','aceptar todas las cookies'];
            var els = document.querySelectorAll('button, div[role="button"], a[role="button"]');
            for (var i=0;i<els.length;i++){
                if(!vis(els[i])) continue;
                var t=(els[i].innerText||'').trim().toLowerCase();
                for (var j=0;j<textos.length;j++){
                    if(t.indexOf(textos[j])!==-1){ els[i].click(); return true; }
                }
            }
            return false;
        """)
        if clicado:
            logger.info("[Login] Banner de cookies aceito.")
            if callback_status:
                callback_status("Cookies aceitos.")
            _delay_pagina(1.0, 2.0)
            return True
        return False
    except Exception as e:
        logger.info(f"[Login] Cookies: nada a tratar ({e}).")
        return False


def _tratar_dialogo_permitir_cookies(driver, callback_status=None):
    """
    Trata o diálogo "Allow the use of cookies by Facebook?" (flow=user_cookie_
    choice), que tem DOIS botões: "Allow all cookies" (azul, PRIMÁRIO) e
    "Decline optional cookies". Clica SEMPRE em "Allow all cookies" e EVITA
    explicitamente o de recusar.

    INDEPENDENTE DE IDIOMA: tenta, nesta ordem,
      1) o atributo oficial do FB '[data-cookiebanner="accept_button"]';
      2) o TEXTO "allow all cookies" em vários idiomas (nunca o de "decline");
      3) como último recurso, o botão PRIMÁRIO AZUL que NÃO seja o de recusar.
    Aguarda até sair do diálogo (URL muda / botões somem). Best-effort.
    """
    from server.page_state_manager import PageStateManager
    try:
        for tentativa in range(4):
            PageStateManager.wait_until_stable(driver, timeout=15, settle_time=1.0,
                                               f5_after=20, callback_status=callback_status)
            clicou = driver.execute_script("""
                function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                    var s=getComputedStyle(el);
                    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                function azul(el){ var bg=getComputedStyle(el).backgroundColor||'';
                    return bg.indexOf('8, 102, 255')!==-1 || bg.indexOf('24, 119, 242')!==-1
                        || bg.indexOf('0, 100, 224')!==-1 || bg.indexOf('11, 105, 255')!==-1; }
                // Textos a EVITAR (recusar cookies opcionais), multi-idioma
                var evitar = ['decline optional cookies','decline','recusar cookies opcionais',
                              'recusar','rechazar','refuser','only allow essential',
                              'permitir apenas essenciais','apenas essenciais',
                              'từ chối cookie không bắt buộc','từ chối'];
                function deveEvitar(t){ for(var e=0;e<evitar.length;e++){ if(t.indexOf(evitar[e])!==-1) return true; } return false; }
                // 1) Atributo oficial do banner de cookies do FB
                var b = document.querySelector('[data-cookiebanner="accept_button"]')
                     || document.querySelector('[data-testid="cookie-policy-manage-dialog-accept-button"]');
                if (b && vis(b)) { b.click(); return 'accept_button'; }
                var els = document.querySelectorAll('button, div[role="button"], a[role="button"], span[role="button"]');
                // 2) Por TEXTO "allow all cookies" (e NUNCA o de recusar). VI: 'Cho phép tất cả cookie'.
                var permitir = ['allow all cookies','permitir todos os cookies','permitir todos',
                                'allow all','aceitar todos os cookies','aceitar todos',
                                'permitir cookies','aceptar todas','tout accepter','aceitar tudo',
                                'cho phép tất cả cookie','cho phép tất cả'];
                for (var i=0;i<els.length;i++){ if(!vis(els[i])) continue;
                    var t=(els[i].innerText||'').trim().toLowerCase();
                    if(!t || deveEvitar(t)) continue;
                    for(var j=0;j<permitir.length;j++){ if(t.indexOf(permitir[j])!==-1){ els[i].click(); return t; } }
                }
                // 3) Botão PRIMÁRIO AZUL que NÃO seja o de recusar
                for (var k=0;k<els.length;k++){ if(!vis(els[k])) continue;
                    var tk=(els[k].innerText||'').trim().toLowerCase();
                    if(deveEvitar(tk)) continue;
                    if(azul(els[k])){ els[k].click(); return tk || 'botao_azul'; }
                }
                return false;
            """)
            if clicou:
                logger.info("[Cookies] Diálogo de cookies — clicado: '%s'.", clicou)
                if callback_status:
                    callback_status("Todos os cookies permitidos.")
                _delay_pagina(1.0, 2.0)
                # Saiu do diálogo? (URL deixou de ser o cookie_choice)
                url = (driver.current_url or '').lower()
                if 'user_cookie_choice' not in url and 'cookie_choice' not in url:
                    return True
            else:
                logger.info("[Cookies] Diálogo de cookies — nenhum botão reconhecível (tentativa %s).", tentativa + 1)
                time.sleep(1.0)
        return True
    except Exception as e:
        logger.warning("[Cookies] Erro ao tratar diálogo de permitir cookies: %s", e)
        return False


def _resolver_consentimentos_e_cookies(driver, callback_status=None, tentativas=4):
    """Resolve QUALQUER bloqueio de consentimento/cookies do FB que esteja na
    frente ANTES de prosseguir o fluxo: diálogo de cookies ('Permitir todos os
    cookies' / 'Cho phép tất cả cookie'), consentimento de privacidade (LGPD) e a
    assinatura 'ad_free_subscription' (escolhe GRÁTIS com anúncios). Idioma-indep.

    MOTIVO: essas telas surgem ao NAVEGAR (login, troca de idioma, abrir settings)
    e, se ficarem pendentes, TRAVAM o fluxo mais à frente. Por isso chamamos isto
    antes de cada etapa que navega. Loopa até a tela sair (ou esgotar tentativas).
    Best-effort — nunca quebra o fluxo."""
    for _ in range(max(1, tentativas)):
        # Navegador fechado (usuário/queda)? Sai NA HORA (não gasta as tentativas).
        if navegador_foi_fechado(driver):
            return
        try:
            url = (driver.current_url or '').lower()
        except Exception:
            url = ''
        agiu = False
        # 1) Consentimento de privacidade / ad_free_subscription / cookie_choice (por URL).
        if ('privacy/consent' in url or 'ad_free_subscription' in url
                or 'lgpd' in url or 'gdpr' in url):
            _tratar_consentimento_privacidade(driver, callback_status)
            agiu = True
        elif 'user_cookie_choice' in url or 'cookie_choice' in url:
            _tratar_dialogo_permitir_cookies(driver, callback_status)
            agiu = True
        else:
            # 2) Banner/diálogo de cookies sobreposto (sem mudar a URL).
            try:
                tem_cookie = bool(driver.execute_script(r"""
                    function vis(e){ if(!e) return false; var r=e.getBoundingClientRect();
                        var s=getComputedStyle(e); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; }
                    if (vis(document.querySelector('[data-cookiebanner="accept_button"]'))) return true;
                    if (vis(document.querySelector('[data-testid="cookie-policy-manage-dialog-accept-button"]'))) return true;
                    var t = (document.body && document.body.innerText || '').toLowerCase();
                    return t.indexOf('cho phép tất cả cookie')!==-1 || t.indexOf('allow all cookies')!==-1
                        || t.indexOf('permitir todos os cookies')!==-1
                        || t.indexOf('permitir o uso de cookies')!==-1
                        || t.indexOf('cho phép sử dụng cookie')!==-1;
                """))
            except Exception:
                tem_cookie = False
            if tem_cookie:
                _tratar_cookies_facebook(driver, callback_status)
                agiu = True
        if not agiu:
            break
        try:
            _delay_pagina(1.0, 2.0)
        except Exception:
            time.sleep(1.0)
    return True


def _aguardar_login_concluido(driver, callback_status=None, timeout=None, profile_id=None):
    if timeout is None:
        timeout = config_manager.get("timeouts.home", profile_id, 30)
    """
    [OBSOLETO/FALLBACK]
    Mantido apenas para retrocompatibilidade em chamadas antigas.
    A lógica principal de fluxo linear agora está embutida diretamente em
    `fazer_login_facebook` e na orquestração principal.
    """
    if callback_status:
        callback_status("Aguardando o Facebook redirecionar para o perfil...")

    start = time.time()
    segundos_no_form_login = 0.0
    ultimo_url_log = ''

    from server.page_state_manager import PageStateManager
    
    while time.time() - start < timeout:
        # 0. Navegador fechado (usuário/queda)? Sai NA HORA como não-logado —
        #    o chamador marca Erro/Falha e segue (não fica preso no polling).
        if navegador_foi_fechado(driver):
            logger.warning("[Login] Navegador foi fechado durante o login.")
            if callback_status:
                callback_status("Navegador foi fechado — login abortado.")
            return False
        # 1. Espera inteligente: Aguarda a página ficar estática antes de agir
        PageStateManager.wait_for_page_load(driver, timeout=2)

        # 1-b. CAPTCHA-ANYWHERE: muitos perfis (sobretudo por cookie) caem num
        #      reCAPTCHA logo após logar. Resolve NA HORA e continua o polling —
        #      antes isso caía como "unknown"/erro e o navegador fechava.
        if _tratar_captcha_se_preciso(driver, callback_status):
            continue

        # 2. Identifica exatamente em qual tela estamos
        tela_atual, detalhes = PageStateManager.identify_current_screen(driver)
        logger.info(f"[PageStateManager] Tela atual identificada: {tela_atual}")

        # 3. Checkpoint SEVERO (conta "possivelmente hackeada" / "confirme p/ desbloquear"
        #    / "Nhận mã qua email") = dead-end que só destrava com código no e-mail do
        #    perfil, que NÃO acessamos. ABORTA INCONDICIONALMENTE: fecha o perfil, marca
        #    falha e segue p/ o próximo — NÃO depende do 2º parecer do BlockDetector (se
        #    ele discordasse, o fluxo caía no loop perdendo tempo numa tela sem saída).
        if tela_atual == "checkpoint_severe":
            logger.error("[Login] checkpoint_severe (conta travada/hackeada — só destrava por e-mail). Abortando perfil.")
            try:
                callback_status and callback_status("🔒 Conta travada (checkpoint só destrava por e-mail) — fechando e seguindo.")
            except Exception:
                pass
            try:
                BlockDetector.handle_block("checkpoint_severe", "abort_profile", profile_id or "desconhecido", callback_status)
            except Exception:
                pass
            return False

        # 4. Tratar telas baseadas no estado identificado (Fluxo Sequencial)
        try:
            url = driver.current_url.lower()
            if url and url != ultimo_url_log:
                logger.info(f"[Login] Aguardando redirecionamento — URL atual: {driver.current_url}")
                ultimo_url_log = url
                
            if tela_atual == "email_code":
                # FB pediu CÓDIGO DE CONFIRMAÇÃO por e-mail (confirmemail.php).
                # Lê o código na caixa Outlook/Hotmail (aba ao lado) e digita.
                # Se resolver, reavalia a próxima tela; senão marca FALHA.
                # A leitura pode levar ~150s — ESTENDE a janela deste polling.
                timeout += 300
                logger.info("[Login] Tela de código por e-mail (confirmemail) — resolvendo via caixa de e-mail.")
                if _resolver_codigo_email_confirmemail(driver, callback_status):
                    continue
                logger.warning("[Login] Não consegui resolver o código por e-mail — marcando como FALHA.")
                if callback_status:
                    callback_status("Código por e-mail não resolvido — perfil marcado como erro.")
                return False

            if tela_atual == "2fa_screen":
                # O 2FA é tratado na orquestração principal (fazer_login_facebook -> _tratar_2fa)
                # Se cairmos aqui, retornamos False para que o fazer_login_facebook chame _tratar_2fa
                # A menos que seja um loop de verificação, onde ele só aguarda
                logger.info("[Login] Tela de 2FA detectada.")
                # Vamos deixar o polling aguardar, pois a orquestração pode estar processando
                pass
                
            elif tela_atual == "checkpoint_dismiss":
                # Checkpoint detectado, precisamos clicar no botão
                _tratar_aviso_comportamento_automatizado(driver, callback_status)
                # Depois de clicar, a página vai carregar, então voltamos ao topo do loop
                continue
                
            elif tela_atual == "login_popup":
                _dispensar_popup_navegador_login(driver)
                
            elif tela_atual == "login_form":
                segundos_no_form_login += 0.5
                if segundos_no_form_login >= 3:
                    logger.warning("[Login] Voltou para o formulário de login — login não concluído.")
                    if callback_status:
                        callback_status("Login não concluído (voltou para a tela de login).")
                    return False
                    
            elif tela_atual == "home":
                # Home detectada com sucesso!
                # Garantir que a home carregou 100% e está estática antes de seguir
                _esperar_pagina_carregar(driver, timeout=10)
                time.sleep(1.5)
                # Dispensar o diálogo "Remember Password / Lembrar senha"
                try:
                    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                    time.sleep(0.5)
                except Exception:
                    pass
                try:
                    _tratar_cookies_facebook(driver, callback_status)
                    _tratar_popup_ok_entendi(driver, callback_status)
                    _tratar_teen_account_interstitial(driver, callback_status)
                except Exception:
                    pass
                if callback_status:
                    callback_status("Login confirmado! Perfil carregado.")
                return True
                
            # Handlers secundários (sempre rodar por precaução)
            _tratar_confiar_dispositivo(driver, callback_status)
            # Interstitial pós-login (teen/graduation "você fez 18 anos, revise
            # as configurações"): a URL NÃO é "home", então precisa ser tratado
            # aqui no polling — senão o login trava nesta tela.
            _tratar_teen_account_interstitial(driver, callback_status)
            _tratar_cookies_facebook(driver, callback_status)
            
        except Exception as e:
            logger.warning(f"Erro ao processar tela atual: {e}")
            pass

        # Pequeno delay antes da próxima iteração do polling
        time.sleep(0.5)

    logger.warning("[Login] Timeout aguardando redirecionamento pós-login.")
    if callback_status:
        callback_status("Tempo esgotado aguardando o Facebook redirecionar.")
    # Última checagem best-effort (sem navegar)
    try:
        return bool(driver.execute_script("""
            if (document.querySelector('[role="feed"]')) return true;
            if (document.querySelector('[role="banner"] [role="navigation"]')) return true;
            var nav = document.querySelectorAll('[role="navigation"]');
            return nav.length > 0;
        """))
    except Exception:
        return False


def _ler_valor_input(driver, css):
    """Lê o .value atual de um input pelo seletor CSS (string, nunca None)."""
    try:
        v = driver.execute_script(
            "var el=document.querySelector(arguments[0]); return el ? (el.value||'') : '';",
            css,
        )
        return (v or '').strip()
    except Exception:
        return ''


def _esperar_autofill_terminar(driver, email_css, senha_css, timeout=6.0):
    """Espera o autofill do AdsPower PARAR de digitar antes de mexermos nos campos.

    Perfis criados até 2026-08-04 têm usuário/senha salvos na "conta da
    plataforma" do AdsPower — ao abrir o facebook.com, o JS DELE digita sozinho.
    Escrever por cima enquanto ele digita embaralha o campo: já apareceu o ID
    com 13 dígitos ('6157710199750') em vez dos 14 reais, e o login morria com
    'senha inválida'. Aqui só observamos: quando os dois campos ficam iguais em
    duas leituras seguidas, ele terminou e o campo é nosso.
    (Perfis NOVOS não têm mais essas credenciais salvas — nem digita, nem bolha.)
    """
    fim = time.time() + timeout
    anterior = None
    estaveis = 0
    while time.time() < fim:
        try:
            atual = (_ler_valor_input(driver, email_css),
                     _ler_valor_input(driver, senha_css))
        except Exception:
            return
        if atual == anterior:
            estaveis += 1
            if estaveis >= 2:                    # ~0.7s sem mudar
                if any(atual):
                    logger.info("[Login] Autofill do AdsPower terminou (campo já "
                                "preenchido) — sobrescrevendo com segurança.")
                return
        else:
            estaveis = 0
        anterior = atual
        time.sleep(0.35)
    logger.warning("[Login] Autofill ainda mexia nos campos após %.0fs — seguindo.", timeout)


def _digitar_devagar(driver, css, valor, label='campo'):
    """Apaga o campo e redigita PAUSADAMENTE, tecla a tecla (último recurso).

    Usado quando o preenchimento rápido não resultou em login: alguns formulários
    do Facebook só validam o que foi digitado com ritmo humano."""
    valor = (valor or '').strip()
    try:
        campo = driver.find_element(By.CSS_SELECTOR, css.split(',')[0].strip())
    except Exception:
        return False
    try:
        campo.click()
        _delay(0.1, 0.2)
        # limpeza real (Ctrl+A + Delete): `clear()` às vezes não dispara os
        # eventos que o React do Facebook escuta.
        campo.send_keys(Keys.CONTROL + 'a')
        campo.send_keys(Keys.DELETE)
        _delay(0.15, 0.3)
        for ch in valor:
            campo.send_keys(ch)
            time.sleep(random.uniform(0.06, 0.14))
    except Exception as e:
        logger.warning("[Login] Digitação pausada de '%s' falhou: %s", label, e)
        return False
    ok = _ler_valor_input(driver, css) == valor
    logger.info("[Login] '%s' redigitado pausadamente — conferido=%s", label, ok)
    return ok


def _preencher_campo_login(driver, css, valor, label='campo'):
    """
    Preenche um campo de login e GARANTE que o valor entrou. Tenta primeiro
    digitando (send_keys) e, se o campo ficar vazio/divergente (o que acontece
    quando a bolha do navegador rouba o foco), força o valor via JS.
    Retorna True somente se o valor final bater com o esperado.
    """
    valor = (valor or '').strip()
    campo = _esperar_clicavel(driver, By.CSS_SELECTOR, css, timeout=10)
    if not campo:
        logger.error(f"[Login] Campo '{label}' ({css}) não encontrado.")
        return False

    # Tentativa 1: digitação normal
    _digitar(campo, valor)
    _delay(0.2, 0.4)

    if _ler_valor_input(driver, css) == valor:
        return True

    # Tentativa 2: forçar via JS (native setter + eventos)
    logger.warning(f"[Login] '{label}' não preencheu via digitação. Forçando via JS...")
    try:
        driver.execute_script("""
            var el = document.querySelector(arguments[0]);
            if (!el) return;
            el.focus();
            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, arguments[1]);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        """, css, valor)
    except Exception as e:
        logger.warning(f"[Login] Erro ao forçar '{label}' via JS: {e}")
    _delay(0.2, 0.4)

    if _ler_valor_input(driver, css) == valor:
        return True

    # Tentativa 3: limpar e redigitar caractere a caractere após novo clique
    try:
        campo2 = driver.find_element(By.CSS_SELECTOR, css.split(',')[0].strip())
        _digitar(campo2, valor)
    except Exception:
        pass
    _delay(0.2, 0.4)

    ok = _ler_valor_input(driver, css) == valor
    if not ok:
        logger.error(f"[Login] FALHA ao preencher '{label}'. valor atual='{_ler_valor_input(driver, css)}'")
    return ok


def _obter_timestamp_corrigido():
    """
    Retorna um timestamp Unix CORRIGIDO pelo horário de rede, para gerar o
    código TOTP mesmo quando o relógio da máquina está dessincronizado (causa
    nº 1 de '2FA errado em todos os perfis'). Usa o cabeçalho HTTP 'Date' de um
    servidor confiável. Em caso de falha, cai no horário local.
    """
    for url in ('https://www.facebook.com', 'https://www.google.com'):
        try:
            import urllib.request
            import email.utils
            req = urllib.request.Request(url, method='HEAD',
                                         headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=6) as resp:
                date_hdr = resp.headers.get('Date')
            if date_hdr:
                dt = email.utils.parsedate_to_datetime(date_hdr)
                ts = dt.timestamp()
                logger.info(f"[2FA] Horário de rede obtido de {url}: offset={ts - time.time():.1f}s")
                return ts
        except Exception as e:
            logger.info(f"[2FA] Falha ao obter horário de {url}: {e}")
    return time.time()


def _gerar_codigo_2fa(tfa_secret):
    """
    Gera o código TOTP de 6 dígitos a partir do SEGREDO 2FA do Facebook.

    Robustez:
      - Se o valor já for um código de 6 dígitos, usa direto.
      - Limpa o segredo (remove espaços/hífens, deixa só base32 maiúsculo).
      - Corrige o relógio pelo horário de rede (evita '2FA errado').
      - Se o pyotp não estiver disponível, registra ERRO claro e retorna None
        (NUNCA digita o segredo cru como se fosse o código).

    Retorna o código (str de 6 dígitos) ou None se não for possível gerar.
    """
    if not tfa_secret:
        return None
    bruto = str(tfa_secret).strip()

    # Já é um código numérico (6-8 dígitos)? Usa direto.
    so_digitos = ''.join(ch for ch in bruto if ch.isdigit())
    if bruto.isdigit() and 6 <= len(bruto) <= 8:
        return bruto

    # Caso contrário, tratamos como SEGREDO base32 -> precisa do pyotp
    try:
        import pyotp
    except Exception as e:
        logger.critical(
            "[2FA] pyotp NÃO está disponível neste ambiente (%s). "
            "Não é possível gerar o código TOTP — o executável precisa ser "
            "recompilado com o pyotp incluído. Verifique o .spec (hiddenimports).",
            e,
        )
        return None

    # Limpar segredo: manter apenas caracteres base32 válidos, em maiúsculo
    import re as _re
    secret = _re.sub(r'[^A-Za-z2-7]', '', bruto).upper()
    if not secret:
        logger.error(f"[2FA] Segredo 2FA inválido após limpeza (bruto='{bruto}').")
        # Último recurso: se havia dígitos, devolve-os
        return so_digitos if 6 <= len(so_digitos) <= 8 else None

    try:
        totp = pyotp.TOTP(secret)
        ts = _obter_timestamp_corrigido()
        codigo = totp.at(ts)
        logger.info(f"[2FA] Código TOTP gerado (len_segredo={len(secret)}).")
        return codigo
    except Exception as e:
        logger.error(f"[2FA] Erro ao gerar TOTP: {e}")
        return None


def _aguardar_proxima_janela_totp():
    """
    Aguarda até o início da próxima janela TOTP (blocos de 30s) para que o
    próximo código gerado seja DIFERENTE do anterior. Limita a espera a ~31s.
    Usado entre tentativas quando o Facebook recusa o código.
    """
    try:
        ts = _obter_timestamp_corrigido()
        restante = 30 - (int(ts) % 30)
        if restante <= 1:
            restante = 30
        restante = min(restante + 1, 31)
        logger.info(f"[2FA] Aguardando {restante}s pela próxima janela TOTP...")
        time.sleep(restante)
    except Exception:
        time.sleep(30)


# ───────────────────────────────────────────────────────────────────────────
# Tela de CÓDIGO POR E-MAIL (confirmemail.php) — "Insira o código de confirmação"
# / "Nhập mã xác nhận".
#
# A resolução automática deste código (leitura no Hotmail/Outlook via IMAP e o
# fallback de login web no Outlook) foi REMOVIDA — não era confiável (IMAP com
# basic-auth bloqueado). A resolução via NAVEGADOR (aba ao lado) foi RE-HABILITADA
# em 2026-10-06 (server/outlook_login.py): a caixa é logada ANTES do fluxo do FB e
# o código é lido quando o confirmemail.php aparecer. Ver os handlers "email_code"
# em _aguardar_login_concluido, fazer_login_facebook e no loop de login por cookie,
# todos chamando _resolver_codigo_email_confirmemail().
# ───────────────────────────────────────────────────────────────────────────
# ⚠️ DESLIGADO (2026-10-06, pedido do dono): o login automático no Outlook/Hotmail
# estava ABRINDO a página da Microsoft (login.live.com / "Verifique seu email") e
# TRAVANDO ali, atrapalhando o fluxo do GS Creator. Enquanto não terminamos o login do
# e-mail com calma, este flag fica False: NÃO abre a caixa (pré-login) e NÃO tenta ler o
# código no confirmemail (volta ao comportamento antigo = marca falha e segue). Todo o
# código do leitor (server/outlook_login.py) continua no repositório, só desativado.
# Ligar de novo = pôr True (e reconfirmar o login ao vivo). Ver memória
# gs-creator-outlook-codigo-login-aba.
_EMAIL_LOGIN_OUTLOOK_ATIVO = False


def _digitar_codigo_confirmemail(driver, codigo, callback_status=None):
    """Digita o código no campo do confirmemail.php (input[name="code"]), envia e
    aguarda SAIR da tela de código. Retorna True se o código foi aceito."""
    try:
        campo = _esperar_qualquer(driver, [
            (By.CSS_SELECTOR, 'input[name="code"]'),
            (By.CSS_SELECTOR, 'input[autocomplete="one-time-code"]'),
            (By.CSS_SELECTOR, 'input[type="text"]'),
        ], timeout=8)
        if not campo:
            logger.warning("[EmailCode] Campo do código (confirmemail) não encontrado.")
            return False

        _digitar(campo, codigo)
        _delay(0.3, 0.5)
        # Garante o valor via setter nativo (React/FB)
        if _ler_valor_input(driver, 'input[name="code"]') != codigo:
            try:
                driver.execute_script("""
                    var el = document.querySelector('input[name="code"]')
                        || document.querySelector('input[autocomplete="one-time-code"]')
                        || document.querySelector('input[type="text"]');
                    if (el) {
                        el.focus();
                        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, arguments[0]);
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                    }
                """, codigo)
            except Exception:
                pass
        _delay(0.3, 0.5)

        # Enviar (Continuar/Continue/Enviar/Submit)
        btn = _esperar_qualquer(driver, [
            (By.CSS_SELECTOR, '#checkpointSubmitButton'),
            (By.CSS_SELECTOR, 'button[type="submit"]'),
            (By.XPATH, "//div[@role='button' and (.//span[normalize-space()='Continue'] or .//span[normalize-space()='Continuar'] or .//span[normalize-space()='Enviar'])]"),
            (By.XPATH, "//button[normalize-space()='Continue' or normalize-space()='Continuar' or normalize-space()='Enviar']"),
        ], timeout=5)
        if btn:
            _clicar(driver, btn)
        else:
            try:
                driver.execute_script("""
                    var alvos = ['continue','continuar','enviar','submit','confirmar','confirm'];
                    var els = document.querySelectorAll('button, div[role="button"], span[role="button"]');
                    for (var i=0;i<els.length;i++){
                        var t=(els[i].innerText||'').trim().toLowerCase();
                        for (var j=0;j<alvos.length;j++){ if(t===alvos[j]){ els[i].click(); return true; } }
                    }
                    return false;
                """)
            except Exception:
                pass
            try:
                campo.send_keys(Keys.RETURN)
            except Exception:
                pass

        # Aguarda SAIR da tela de email_code (código aceito) OU erro explícito.
        from server.page_state_manager import PageStateManager
        marcadores_erro = ['incorrect', 'invalid', 'incorreto', 'inválid', 'in");valid',
                           'não corresponde', 'try again', 'tente novamente',
                           'código incorreto', 'wrong code', 'verifique o código']
        fim = time.time() + 35
        while time.time() < fim:
            PageStateManager.wait_until_stable(driver, timeout=8, settle_time=0.8,
                                               f5_after=30, callback_status=None)
            try:
                tela, _ = PageStateManager.identify_current_screen(driver)
            except Exception:
                tela = ''
            if tela != "email_code" and 'confirmemail' not in (driver.current_url or '').lower():
                logger.info("[EmailCode] Código de e-mail ACEITO — saiu do confirmemail.")
                return True
            try:
                # FIX 2026-10-12: texto VISÍVEL (o page_source traz 'invalid'/'try
                # again' nos <script> do FB → "recusado" falso no 1º check).
                page = (driver.execute_script(
                    "return (document.body && document.body.innerText || '');") or '').lower()
                if any(m in page for m in marcadores_erro):
                    logger.warning("[EmailCode] Código de e-mail recusado pelo FB.")
                    return False
            except Exception:
                pass
            time.sleep(1.0)
        logger.warning("[EmailCode] Código enviado mas a tela não saiu do confirmemail.")
        return False
    except Exception as exc:
        logger.warning("[EmailCode] Falha ao digitar o código do confirmemail: %s", exc)
        return False


def _resolver_codigo_email_confirmemail(driver, callback_status=None):
    """Resolve a tela confirmemail.php lendo o código na caixa Outlook/Hotmail
    (aba ao lado) e digitando no FB. Retorna True se o código foi aceito.

    Só funciona para provedores que exigem navegador (hotmail/outlook/live).
    Para gsmails/domínios próprios o código é tratado pelo fluxo da API."""
    # DESLIGADO: não tenta ler o código pela caixa (evita abrir/travar na Microsoft).
    if not _EMAIL_LOGIN_OUTLOOK_ATIVO:
        return False
    try:
        from server import outlook_login
    except Exception as exc:
        logger.warning("[EmailCode] módulo outlook_login indisponível: %s", exc)
        return False

    email = getattr(driver, '_pm_fb_email', '') or ''
    senha_email = getattr(driver, '_pm_fb_email_senha', '') or ''
    if not email or not outlook_login.eh_email_outlook(email):
        logger.info("[EmailCode] e-mail do perfil não é Outlook/Hotmail (ou vazio) — não resolvo por navegador.")
        return False

    # Guarda a aba do FB para voltar depois de ler o código.
    try:
        fb_tab = driver.current_window_handle
    except Exception:
        fb_tab = None

    # Garante a caixa logada (o pré-login pode não ter rodado / sessão caiu).
    if not getattr(driver, '_outlook_tab', None):
        if callback_status:
            callback_status("Abrindo e logando o e-mail para ler o código...")
        outlook_login.abrir_e_logar(driver, email, senha_email, callback_status)
        try:
            if fb_tab and fb_tab in driver.window_handles:
                driver.switch_to.window(fb_tab)
        except Exception:
            pass

    if callback_status:
        callback_status("Aguardando o código de confirmação chegar no e-mail...")
    codigo = outlook_login.ler_codigo(driver, timeout=150, callback_status=callback_status)

    # Volta para a aba do FB (ler_codigo deixa a aba da caixa em foco).
    try:
        if fb_tab and fb_tab in driver.window_handles:
            driver.switch_to.window(fb_tab)
    except Exception:
        pass

    if not codigo:
        if callback_status:
            callback_status("Código por e-mail não chegou a tempo — perfil marcado como erro.")
        return False

    if callback_status:
        callback_status(f"Código {codigo} recebido no e-mail — enviando ao Facebook...")
    return _digitar_codigo_confirmemail(driver, codigo, callback_status)


_MAX_VOLTAS_LOGIN = 3   # voltas SEGUIDAS à tela inicial de login → descarta o perfil


def _volta_ao_login(driver, motivo, callback_status=None):
    """Conta UMA volta à tela inicial de login depois de enviar as credenciais (bounce
    pós-captcha, 'informações incorretas', form que não sai). O contador fica no DRIVER
    → sobrevive às novas chamadas do guardião de sessão. Na 3ª SEGUIDA descarta o perfil
    (pedido do dono 2026-10-13: perfil bugado que loga, passa o captcha e sempre volta
    ao login = loop infinito). Retorna True se o perfil foi descartado agora."""
    try:
        n = int(getattr(driver, '_login_voltas_form', 0) or 0) + 1
        driver._login_voltas_form = n
    except Exception:
        return False
    logger.warning("[Login] voltou à tela de login (%s) — %d/%d seguidas.", motivo, n, _MAX_VOLTAS_LOGIN)
    if n >= _MAX_VOLTAS_LOGIN:
        try:
            driver._login_descartado = True
        except Exception:
            pass
        _snap_login(driver, f'loop_login_{motivo}')
        logger.error("[Login] login voltou à tela inicial %dx seguidas — perfil DESCARTADO.", n)
        if callback_status:
            callback_status(f"⛔ Login voltou à tela inicial {n}x seguidas — não foi possível "
                            "logar no Facebook (perfil descartado).")
        return True
    if callback_status:
        callback_status(f"Facebook devolveu a tela de login ({n}/{_MAX_VOLTAS_LOGIN})...")
    return False


def fazer_login_facebook(driver, login, senha, tfa_code=None, callback_status=None,
                         email=None, senha_email=None):
    """Faz login no Facebook (ver _fazer_login_facebook). Ao logar, registra as
    credenciais no driver → o guardião de sessão re-loga sozinho se a Meta deslogar
    o perfil em QUALQUER etapa seguinte (reprocesso/reuso incluídos)."""
    # Perfil já DESCARTADO por loop de login (3 voltas seguidas à tela inicial): nunca
    # mais tenta — senão o guardião de sessão re-loga após cada navegação, eternamente.
    if getattr(driver, '_login_descartado', False):
        logger.warning("[Login] perfil já descartado por loop de login — não tento de novo.")
        if callback_status:
            callback_status("Não foi possível logar no Facebook (login volta sempre à tela inicial).")
        return False
    with _SessaoOcupada(driver):
        ok = _fazer_login_facebook(driver, login, senha, tfa_code, callback_status,
                                   email=email, senha_email=senha_email)
    if ok:
        try:
            driver._login_voltas_form = 0   # logou: zera as voltas seguidas
        except Exception:
            pass
    if ok and login and senha:
        try:
            from server import session_guard as _sg
            _sg.setar_credenciais(driver, login, senha, tfa_code or '', email or '', senha_email or '')
        except Exception:
            pass
    return ok


def _fazer_login_facebook(driver, login, senha, tfa_code=None, callback_status=None,
                          email=None, senha_email=None):
    """Faz login no Facebook.

    `email`/`senha_email`: mantidos por compatibilidade com os chamadores. A
    resolução automática do `confirmemail.php` (código por e-mail) foi REMOVIDA;
    se essa tela aparecer, o login falha e o perfil é marcado como erro."""
    try:
        # Guarda credenciais do e-mail no driver (compat.: outros fluxos ainda
        # leem esses atributos). Não são mais usadas para resolver confirmemail.
        try:
            driver._pm_fb_email = (email or getattr(driver, '_pm_fb_email', '') or '')
            driver._pm_fb_email_senha = (senha_email or getattr(driver, '_pm_fb_email_senha', '') or '')
        except Exception:
            pass
        if callback_status:
            callback_status("Acessando Facebook para login...")

        # OTIMIZAÇÃO: NÃO recarregar a página se JÁ estamos no formulário de
        # login (cookie expirado já caiu nele). Navegar de novo seria um F5
        # desnecessário — o usuário relatou "2 F5 antes de logar". Só navegamos
        # para /login/ quando ainda NÃO há o formulário visível.
        ja_no_form = False
        try:
            ja_no_form = bool(driver.execute_script("""
                function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                    var s=getComputedStyle(el);
                    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                return vis(document.querySelector('#email, input[name="email"]')) &&
                       vis(document.querySelector('#pass, input[name="pass"]'));
            """))
        except Exception:
            ja_no_form = False

        if not ja_no_form:
            driver.get("https://www.facebook.com/login/")
            _esperar_pagina_carregar(driver, timeout=10)
            _delay(0.4, 0.8)
        else:
            logger.info("[Login] Já no formulário de login — entrando direto (sem recarregar).")

        # ===============================================================
        # LOGIN POR CREDENCIAIS — RÁPIDO E DIRETO (1 envio, sem loop de 3x):
        #   1) Esperar o form e dispensar a bolha "Fazer login como" (via DOM)
        #   2) Preencher USUÁRIO e SENHA sobrescrevendo o autofill
        #   3) Clicar ENTRAR uma vez (JS atravessa a bolha) e aguardar por
        #      polling curto. Só refaz UMA vez se ainda estiver na tela de login.
        # ===============================================================
        email_css = '#email, input[name="email"]'
        senha_css = '#pass, input[name="pass"]'
        login_strip = (login or '').strip()
        senha_strip = (senha or '').strip()

        # PASSO 1: Esperar o campo de email e dispensar a bolha (DOM, sem foco)
        if not _esperar_clicavel(driver, By.CSS_SELECTOR, email_css, timeout=10):
            logger.error("[Login] Formulário de login não apareceu.")
            return False
        # Deixa o autofill do AdsPower TERMINAR antes de escrever (perfis antigos)
        # — escrever junto com ele trunca o ID e derruba o login.
        _esperar_autofill_terminar(driver, email_css, senha_css)
        _dispensar_popup_navegador_login(driver)

        # PASSO 2: Preencher usuário e senha (sobrescrevendo qualquer autofill)
        if callback_status:
            callback_status("Preenchendo usuário e senha...")
        _preencher_campo_login(driver, email_css, login, 'email/ID')
        _delay(0.15, 0.3)
        _preencher_campo_login(driver, senha_css, senha, 'senha')

        # Garantir que os campos ficaram corretos antes de enviar
        if _ler_valor_input(driver, email_css) != login_strip:
            _preencher_campo_login(driver, email_css, login, 'email/ID')
        if _ler_valor_input(driver, senha_css) != senha_strip:
            _preencher_campo_login(driver, senha_css, senha, 'senha')
        if _ler_valor_input(driver, email_css) != login_strip or \
           _ler_valor_input(driver, senha_css) != senha_strip:
            logger.error("[Login] Credenciais não permaneceram nos campos.")
            return False

        # PASSO 3: Fechar a bolha nativa com ESC REAL (ela pode reaparecer ao
        # focar a senha), reconferir os campos e clicar ENTRAR uma única vez.
        _dispensar_popup_navegador_login(driver)
        # O ESC só dispensa a bolha de autofill — os valores foram setados via JS
        # (native setter), então não são apagados; ainda assim reconferimos.
        if _ler_valor_input(driver, email_css) != login_strip:
            _preencher_campo_login(driver, email_css, login, 'email/ID')
        if _ler_valor_input(driver, senha_css) != senha_strip:
            _preencher_campo_login(driver, senha_css, senha, 'senha')

        if callback_status:
            callback_status("Clicando em Entrar...")

        # OTIMIZAÇÃO: Clica apenas uma vez sem loops de reenvio que causam problemas
        _clicar_entrar_facebook(driver)
        logger.info("[Login] ENTRAR clicado (envio único).")
        
        from server.page_state_manager import PageStateManager

        # ── PASSO 4: Aguardar a SAÍDA do formulário de login ──
        # A submissão pode demorar (4G lento). NÃO julgamos a próxima tela
        # enquanto o formulário de e-mail/senha ainda estiver visível — era esse
        # o bug que "fechava como erro" sem esperar a página carregar. Se o form
        # não sair em ~10s, reenviamos ENTRAR uma vez (a bolha nativa pode ter
        # bloqueado o 1º clique). Só desistimos se ele NUNCA sair.
        if callback_status:
            callback_status("Aguardando o Facebook processar o login...")

        def _form_login_visivel():
            try:
                return bool(driver.execute_script("""
                    function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                        var s=getComputedStyle(el);
                        return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                    return vis(document.querySelector('#email, input[name="email"]')) &&
                           vis(document.querySelector('#pass, input[name="pass"]'));
                """))
            except Exception:
                return False

        saiu_do_form = False
        reenviou = False
        inicio_saida = time.time()
        while time.time() - inicio_saida < 30:
            u = (driver.current_url or '').lower()
            if any(m in u for m in ('two_factor', 'two_step', 'checkpoint')):
                saiu_do_form = True
                break
            if not _form_login_visivel():
                saiu_do_form = True
                break
            # Reenvio único após ~10s ainda preso no formulário
            if not reenviou and (time.time() - inicio_saida) > 10:
                # Continua na tela de login: pode ter sido a bolha nativa
                # engolindo o clique, OU o valor colocado via JS que o formulário
                # não aceitou. Agora APAGA e REDIGITA PAUSADAMENTE (ritmo humano),
                # sempre com a bolha fechada, antes de clicar em Entrar de novo.
                logger.warning("[Login] Form ainda visível após 10s — redigitando "
                               "pausadamente e reenviando ENTRAR.")
                if callback_status:
                    callback_status("Login não passou — redigitando devagar e tentando de novo...")
                _dispensar_popup_navegador_login(driver)
                _digitar_devagar(driver, email_css, login, 'email/ID')
                _delay(0.2, 0.4)
                _digitar_devagar(driver, senha_css, senha, 'senha')
                # a bolha reaparece ao focar a senha → fecha DE NOVO antes do clique
                _dispensar_popup_navegador_login(driver)
                if _ler_valor_input(driver, email_css) != login_strip:
                    _preencher_campo_login(driver, email_css, login, 'email/ID')
                if _ler_valor_input(driver, senha_css) != senha_strip:
                    _preencher_campo_login(driver, senha_css, senha, 'senha')
                _clicar_entrar_facebook(driver)
                reenviou = True
            time.sleep(1.0)

        if not saiu_do_form:
            # (2026-10-14) NÃO conta p/ descarte: no log da 2.5 isto era o re-login do
            # guardião atropelado por navegação concorrente, não um perfil bugado.
            logger.error("[Login] Formulário de login não saiu — credenciais inválidas ou bloqueio.")
            if callback_status:
                callback_status("Login não concluído (continua na tela de login).")
            return False

        # ── PASSO 5: Loop de telas intermediárias até a HOME ──
        # Para CADA tela: aguarda carregar 100% e ficar ESTÁTICA (sem sleep
        # fixo; detecta a estabilização e dá F5 se o 4G travar), dispensa a bolha
        # nativa com ESC real e identifica a tela. Trata 2FA (digita código +
        # Continue) e Checkpoint (Dismiss) até chegar na Home — só então retorna
        # True para o fluxo seguir para o aquecimento/criação de BM.
        deadline = time.time() + 240  # janela total generosa para 4G lento
        _unknown_streak = 0           # telas "unknown" seguidas (p/ capturar snapshot)
        _cap_tentativas = 0           # quantas vezes caímos na tela de reCAPTCHA
        _relogin_pos_captcha = 0      # reenvios de credenciais após resolver captcha
        _tentou_home_direto = False   # já conferimos a sessão abrindo facebook.com?
        _2fa_sem_campo = 0            # two_step sem campo de código (transição p/ home)
        _auth_platform_voltas = 0     # passagens pela tela /auth_platform/afad/
        _pedido_invalido_voltas = 0   # erro 'Pedido inválido' (cookie/sessão expirada)
        _hacked_prot_voltas = 0       # insistências do aviso 'conta protegida' (/hacked-protection)
        _email_code_voltas = 0        # passagens pelo confirmemail (teto anti-loop)
        while time.time() < deadline:
            # 0) Navegador fechado (usuário/queda)? Sai NA HORA como não-logado.
            if navegador_foi_fechado(driver):
                logger.warning("[Login Linear] Navegador foi fechado durante o login.")
                if callback_status:
                    callback_status("Navegador foi fechado — login abortado.")
                return False
            # 1) Esperar a página estabilizar 100% (com F5 automático se demorar)
            PageStateManager.wait_until_stable(driver, timeout=40, settle_time=1.5,
                                               f5_after=25, callback_status=callback_status)
            # 2) ESC leve via DOM (fecha modais in-DOM) e aceitar o banner de
            #    cookies, caso apareça no meio da conexão. NÃO focamos a janela
            #    aqui: estas telas não têm a bolha nativa "Fazer login como", e
            #    focar à toa fazia o menu de 3 pontinhos do Chrome piscar.
            _esc_via_dom(driver)
            try:
                _tratar_cookies_facebook(driver, callback_status)
            except Exception:
                pass
            time.sleep(0.3)
            # 2-b) CAPTCHA-ANYWHERE: reCAPTCHA no meio do login credenciado →
            #      resolve e reavalia (evita cair como 'unknown'/erro).
            if _tratar_captcha_se_preciso(driver, callback_status):
                # O solve consome tempo real (CapSolver) — devolve janela ao loop.
                # CONTA como captcha: é por este caminho (captcha-anywhere) que a
                # tela do login costuma ser resolvida, e sem contar aqui a
                # recuperação pós-captcha (home direto / reenvio) não ligava e o
                # perfil morria em "voltou para a tela de login".
                _cap_tentativas += 1
                # TETO (FIX 2026-10-12): este caminho estendia o deadline a cada solve
                # sem checar o teto de captcha → captcha que volta sempre = loop eterno.
                if _cap_tentativas > 5:
                    logger.error("[Login Linear] reCAPTCHA reaparece sem parar (%d) — abortando.", _cap_tentativas)
                    if callback_status:
                        callback_status("reCAPTCHA não passou após várias tentativas — perfil marcado como erro.")
                    return False
                deadline = max(deadline, time.time() + 180)
                continue
            # 3) Identificar a tela atual
            tela_atual, _det = PageStateManager.identify_current_screen(driver)
            logger.info("[Login Linear] Tela identificada: %s | url=%s",
                        tela_atual, (driver.current_url or '')[:150])
            if tela_atual != 'unknown':
                _unknown_streak = 0

            # ── COOKIE/SESSÃO EXPIRADA → erro 'Pedido inválido' ──────────────
            # O perfil abre com cookie vencido, o Facebook tenta retomar a sessão
            # pela URL two_step_verification/authentication e ERRA com "não foi
            # possível validar sua solicitação — comece o fluxo de novo". Isso é
            # classificado como 2fa/captcha e o loop ficava preso. Trata ANTES de
            # tudo (menos a home): fecha o aviso, volta ao facebook.com/login e
            # loga com usuário+senha (o handler login_form reenvia as credenciais).
            if tela_atual != "home" and _erro_pedido_invalido(driver):
                _pedido_invalido_voltas += 1
                logger.info("[Login Linear] 'Pedido inválido' (cookie/sessão expirada) "
                            "%d/3 — recuperando via login credenciado. url=%s",
                            _pedido_invalido_voltas, (driver.current_url or '')[:150])
                if callback_status:
                    callback_status("Sessão/cookie expirados (Facebook: 'não foi possível "
                                    "validar a solicitação') — voltando ao facebook.com para "
                                    "logar com usuário e senha...")
                _fechar_dialogo_generico(driver)
                if _pedido_invalido_voltas >= 3:
                    _snap_login(driver, 'pedido_invalido_persistente')
                    logger.error("[Login Linear] 'Pedido inválido' persistiu (3x) — abortando.")
                    if callback_status:
                        callback_status("Erro 'Pedido inválido' persistente — perfil marcado como erro.")
                    return False
                try:
                    driver.get("https://www.facebook.com/login/")
                except Exception:
                    pass
                _delay_pagina(1.5, 2.6)
                _tentou_home_direto = True   # veio do erro: não perder tempo com home direto
                _relogin_pos_captcha = 0     # garante o reenvio das credenciais no login_form
                deadline = max(deadline, time.time() + 240)
                continue

            # Interstitial pós-login (teen/graduation: "você fez 18 anos, revise
            # as configurações"). A página tem o logo do FB e pode ser
            # mal-classificada como "home" — então tratamos ANTES de qualquer
            # branch, pela URL, clicando Review settings → Next → Done até sair.
            if 'teen-account-interstitial' in (driver.current_url or '').lower():
                if callback_status:
                    callback_status("Revisão de configurações (18 anos) detectada — avançando...")
                _tratar_teen_account_interstitial(driver, callback_status)
                continue

            if tela_atual == "home":
                # Dispensar o diálogo "Lembrar senha" que cobre a Home, sem
                # ativar o login por foto (que geraria a bolha "Fazer login como").
                _dispensar_lembrar_senha(driver)
                if callback_status:
                    callback_status("Login concluído com sucesso! Perfil carregado.")
                logger.info("[Login Linear] HOME alcançada: %s", driver.current_url)
                return True

            if tela_atual == "auth_platform":
                # Passagem pós-login (/auth_platform/afad/). Costuma redirecionar
                # sozinha; se travar, um Continuar/OK resolve. Depois de algumas
                # voltas, vamos direto para facebook.com.
                _auth_platform_voltas += 1
                if callback_status and _auth_platform_voltas == 1:
                    callback_status("Tela de autenticação da plataforma — aguardando o Facebook seguir...")
                logger.info("[Login Linear] auth_platform (%d) — aguardando redirecionar.",
                            _auth_platform_voltas)
                _avancar_apos_captcha(driver)
                if _auth_platform_voltas >= 4:
                    if _tentar_home_direto(driver, callback_status):
                        _dispensar_lembrar_senha(driver)
                        if callback_status:
                            callback_status("Login concluído com sucesso! Perfil carregado.")
                        return True
                    _snap_login(driver, 'auth_platform_travado')
                    logger.error("[Login Linear] auth_platform não saiu — abortando.")
                    if callback_status:
                        callback_status("Tela de autenticação da plataforma não avançou.")
                    return False
                time.sleep(3.0)
                continue

            if tela_atual == "cookie_consent":
                if callback_status:
                    callback_status("Diálogo de cookies detectado. Permitindo todos os cookies...")
                # Clica "Allow all cookies" (botão azul), evitando "Decline
                # optional cookies"; depois volta ao topo para aguardar a próxima
                # tela carregar 100%.
                _tratar_dialogo_permitir_cookies(driver, callback_status)
                continue

            if tela_atual == "privacy_consent":
                if callback_status:
                    callback_status("Consentimento de privacidade detectado. Avançando...")
                # Clica Get Started -> Accept and continue -> Close até sair do
                # fluxo; depois volta ao topo para aguardar a Home carregar 100%.
                _tratar_consentimento_privacidade(driver, callback_status)
                continue

            if tela_atual == "email_code":
                # FB pediu CÓDIGO DE CONFIRMAÇÃO por e-mail (confirmemail.php).
                # Lê o código na caixa Outlook/Hotmail (aba ao lado) e digita.
                # A leitura pode levar ~150s (e-mail demora); ESTENDE o deadline
                # para a espera não comer a janela do login e dar falso erro.
                # TETO (FIX 2026-10-12): cada volta estende o deadline — se o FB
                # pedir o código de novo em sequência, o loop nunca terminava.
                _email_code_voltas += 1
                if _email_code_voltas > 3:
                    _snap_login(driver, 'email_code_repetido')
                    logger.error("[Login Linear] confirmemail pedido %d× — abortando.", _email_code_voltas)
                    if callback_status:
                        callback_status("Facebook pediu código por e-mail repetidamente — perfil marcado como erro.")
                    return False
                deadline = max(deadline, time.time() + 240)
                logger.info("[Login Linear] Tela de código por e-mail (confirmemail) — resolvendo via caixa de e-mail.")
                if _resolver_codigo_email_confirmemail(driver, callback_status):
                    deadline = max(deadline, time.time() + 120)
                    continue
                logger.warning("[Login Linear] Não consegui resolver o código por e-mail — marcando como FALHA.")
                if callback_status:
                    callback_status("Código por e-mail não resolvido — perfil marcado como erro.")
                return False

            if tela_atual == "captcha":
                # Tela de reCAPTCHA no login (ex.: two_step_verification/
                # authentication mostrando "Não sou um robô"). RESOLVE via CapSolver
                # e volta ao topo do loop p/ aguardar a próxima tela (2FA/Home).
                # O solve do CapSolver leva de 20s a ~2min: ESTENDE o deadline do
                # loop para o tempo do captcha não comer a janela do login inteiro
                # (antes o perfil estourava o tempo logo depois de resolver).
                _cap_tentativas += 1
                if _cap_tentativas > 3:
                    logger.error("[Login Linear] reCAPTCHA insistente (%d tentativas) — abortando.", _cap_tentativas)
                    if callback_status:
                        callback_status("reCAPTCHA não passou após várias tentativas — perfil marcado como erro.")
                    return False
                deadline = max(deadline, time.time() + 300)
                if callback_status:
                    callback_status("reCAPTCHA detectado no login — resolvendo via CapSolver...")
                _r_cap = _resolver_captcha_login(driver, callback_status)
                if _r_cap == 'sem_token':
                    logger.error("[Login Linear] reCAPTCHA no login mas SEM token do CapSolver configurado.")
                    if callback_status:
                        callback_status("reCAPTCHA no login sem token CapSolver — configure o token na GUI.")
                    return False
                deadline = max(deadline, time.time() + 180)
                time.sleep(1.5)
                continue

            if tela_atual == "2fa_screen":
                # A `two_step_verification/authentication` costuma abrir com um
                # reCAPTCHA e SÓ DEPOIS pedir o código — e o widget do Google monta
                # 1-3s após a página, então a identificação pode ter vindo como
                # 2FA (pela URL) antes de o captcha existir no DOM. Sem campo de
                # código visível, esperamos o widget e mandamos pro CapSolver;
                # digitar o TOTP aqui só fazia o perfil morrer em "Não foi
                # possível logar" (log de 2026-08-08).
                if not _tem_campo_codigo_2fa(driver):
                    _cap_tentativas += 1
                    if _cap_tentativas > 3:
                        logger.error("[Login Linear] reCAPTCHA insistente na tela de 2FA — abortando.")
                        if callback_status:
                            callback_status("reCAPTCHA não passou após várias tentativas — perfil marcado como erro.")
                        return False
                    deadline = max(deadline, time.time() + 300)
                    _r_cap = _resolver_captcha_login(driver, callback_status,
                                                     aguardar_widget_seg=8)
                    if _r_cap == 'sem_token':
                        logger.error("[Login Linear] reCAPTCHA no login mas SEM token do CapSolver configurado.")
                        if callback_status:
                            callback_status("reCAPTCHA no login sem token CapSolver — configure o token na GUI.")
                        return False
                    if _r_cap != 'no_captcha':
                        deadline = max(deadline, time.time() + 180)
                        time.sleep(1.5)
                        continue
                    _cap_tentativas -= 1  # não era captcha: não conta tentativa

                    # Sem campo de código E sem captcha: a URL two_step_verification
                    # é só a TRANSIÇÃO — o Facebook costuma já estar renderizando a
                    # HOME logada aqui (provado por snapshot em 2026-08-08 04:16:39,
                    # onde o bot abortou por "2FA sem código" com o feed carregado
                    # na tela). Reavalia em vez de matar o perfil.
                    _2fa_sem_campo += 1
                    if _2fa_sem_campo <= 3:
                        logger.info("[Login Linear] two_step sem campo de código e sem "
                                    "captcha (%d/3) — reavaliando a tela.", _2fa_sem_campo)
                        time.sleep(2.0)
                        continue
                    if _tentar_home_direto(driver, callback_status):
                        _dispensar_lembrar_senha(driver)
                        if callback_status:
                            callback_status("Login concluído com sucesso! Perfil carregado.")
                        return True
                if callback_status:
                    callback_status("2FA detectada...")
                if not tfa_code:
                    # Antes de desistir: pode já estar logado (o FB renderiza a home
                    # ainda na URL do two_step).
                    if _tentar_home_direto(driver, callback_status):
                        _dispensar_lembrar_senha(driver)
                        if callback_status:
                            callback_status("Login concluído com sucesso! Perfil carregado.")
                        return True
                    _snap_login(driver, '2fa_sem_codigo')
                    if callback_status:
                        callback_status("2FA necessário mas código não disponível.")
                    return False
                # Digita o código e clica Continue. Se aceito, volta ao topo do
                # loop para AGUARDAR a próxima tela carregar 100% (Checkpoint/Home).
                if not _tratar_2fa(driver, tfa_code, callback_status):
                    return False
                continue

            if tela_atual == "trust_device":
                if callback_status:
                    callback_status("Tela 'Confiar neste dispositivo' detectada. Confirmando...")
                # Clica "Trust this device" (botão primário). Depois volta ao topo
                # para aguardar a próxima tela carregar 100% (Checkpoint/Home).
                _tratar_confiar_dispositivo(driver, callback_status)
                continue

            if tela_atual == "checkpoint_dismiss":
                # "Meta took steps to protect your account" (/hacked-protection):
                # dispensa por 'Back to Facebook'/X; se insistir, um F5 costuma
                # tirá-lo. Só depois cai no dispensador genérico de checkpoint.
                if 'hacked-protection' in (driver.current_url or '').lower():
                    if callback_status:
                        callback_status("Aviso 'Meta protegeu sua conta' — fechando e voltando ao Facebook...")
                    if not fechar_aviso_conta_protegida(driver, callback_status):
                        _hacked_prot_voltas += 1
                        if _hacked_prot_voltas >= 2:
                            logger.info("[Login Linear] Aviso 'conta protegida' insistente — F5 para dispensar.")
                            try:
                                driver.refresh()
                            except Exception:
                                pass
                            _delay_pagina(1.5, 2.5)
                    continue
                if callback_status:
                    callback_status("Checkpoint detectado. Clicando em Dismiss...")
                _tratar_aviso_comportamento_automatizado(driver, callback_status)
                continue

            if tela_atual == "checkpoint_severe":
                logger.error("[Login Linear] Bloqueio/checkpoint severo detectado.")
                if callback_status:
                    callback_status("Bloqueio/checkpoint severo detectado.")
                return False

            if tela_atual in ("login_form", "login_popup"):
                # ATENÇÃO: logo depois do reCAPTCHA o formulário de login PISCA na
                # tela enquanto o Facebook redireciona — e o bot abortava nesse
                # piscar, 2s após resolver o captcha (visto em 2026-08-08 03:40).
                # Agora: confirma que o form REALMENTE ficou (≈3s) e, se ficou
                # mesmo depois de um captcha, REENVIA as credenciais (o FB devolve
                # ao login pedindo para entrar de novo) em vez de matar o perfil.
                _form_ficou = True
                for _ in range(6):
                    time.sleep(0.5)
                    if not _form_login_visivel():
                        _form_ficou = False
                        break
                if not _form_ficou:
                    logger.info("[Login Linear] Form de login era transição (redirect) — seguindo.")
                    continue

                # Senha/usuário errados: o FB diz na tela. Aí reenviar é só perder
                # tempo — aborta na hora.
                if _erro_credencial_visivel(driver):
                    _snap_login(driver, 'credencial_invalida')
                    logger.error("[Login Linear] Facebook recusou as credenciais.")
                    if callback_status:
                        callback_status("Login não concluído (informações de login recusadas).")
                    return False

                # ⚠️ (2026-10-14) NÃO contar 'volta ao login' aqui: o form PISCA em transição
                # normal e o guardião re-loga com navegação concorrente — a v2.5 contava isso
                # e DESCARTOU 21 perfis bons (log do run 13/10). A volta só conta no FIM da
                # tentativa (recuperações da 2.4 esgotadas) e SÓ se houve captcha.

                # 1ª saída: abrir facebook.com direto. Se a sessão já foi criada
                # (acontece bastante), a home aparece e nada mais é preciso. Vale
                # com ou sem captcha antes — em 2026-08-08 05:07 uma conta caiu
                # aqui SEM captcha nenhum e era só bounce.
                if not _tentou_home_direto:
                    _tentou_home_direto = True
                    _tentar_home_direto(driver, callback_status)
                    deadline = max(deadline, time.time() + 180)
                    continue

                if _relogin_pos_captcha < 2:
                    _relogin_pos_captcha += 1
                    logger.info("[Login Linear] FB devolveu o formulário de login — "
                                "reenviando credenciais (%d/2).", _relogin_pos_captcha)
                    if callback_status:
                        callback_status("Facebook pediu o login de novo — reenviando...")
                    _dispensar_popup_navegador_login(driver)
                    _preencher_campo_login(driver, email_css, login, 'email/ID')
                    _delay(0.15, 0.3)
                    _preencher_campo_login(driver, senha_css, senha, 'senha')
                    _dispensar_popup_navegador_login(driver)
                    if _ler_valor_input(driver, email_css) != login_strip:
                        _preencher_campo_login(driver, email_css, login, 'email/ID')
                    if _ler_valor_input(driver, senha_css) != senha_strip:
                        _preencher_campo_login(driver, senha_css, senha, 'senha')
                    _clicar_entrar_facebook(driver)
                    deadline = max(deadline, time.time() + 240)
                    time.sleep(2.0)
                    continue

                _snap_login(driver, 'voltou_login')
                # Regra do dono (perfil bugado): login → CAPTCHA resolvido → volta ao login.
                # Conta 1 volta por TENTATIVA COMPLETA que terminou assim (home direto + 2
                # reenvios já feitos, como na 2.4); na 3ª seguida o perfil é descartado.
                if _cap_tentativas > 0:
                    _volta_ao_login(driver, 'captcha_volta_login', callback_status)
                logger.error("[Login Linear] Voltou para a tela de login. Falha.")
                if callback_status:
                    callback_status("Login não concluído (voltou para a tela de login).")
                return False

            # Interstitial pós-login (teen/graduation: "você fez 18 anos, revise
            # as configurações" → Review settings → Next → Done). A URL não é
            # "home" e cairia em "unknown" travando até o timeout — então o
            # atravessamos aqui e voltamos ao topo para aguardar a Home.
            if 'teen-account-interstitial' in (driver.current_url or '').lower():
                _tratar_teen_account_interstitial(driver, callback_status)
                continue

            # "unknown": pode ser a tela "Confiar neste dispositivo"
            # (remember_browser) ou uma tela intermediária ainda renderizando.
            # Tenta confirmar o dispositivo e segue aguardando a próxima tela.
            if _tratar_confiar_dispositivo(driver, callback_status):
                _unknown_streak = 0
                continue
            # Tela REALMENTE não identificada (após estabilizar). Captura um snapshot
            # para mapeá-la depois e criar o handler — só após 2 leituras seguidas
            # (evita capturar transições). A captura é deduplicada por assinatura.
            _unknown_streak += 1
            if _unknown_streak == 2:
                try:
                    from server.screen_capture import capturar_tela_desconhecida
                    capturar_tela_desconhecida(driver, contexto='login',
                                               motivo='tela_login_nao_identificada')
                except Exception:
                    pass
            time.sleep(1.5)

        # Última cartada antes de desistir: abrir facebook.com direto. Muita vez a
        # sessão JÁ existe e o que travou foi uma tela intermediária que não
        # redirecionou sozinha.
        if _tentar_home_direto(driver, callback_status):
            _dispensar_lembrar_senha(driver)
            logger.info("[Login Linear] Home alcançada pelo acesso direto a facebook.com.")
            if callback_status:
                callback_status("Login concluído com sucesso! Perfil carregado.")
            return True

        logger.error("[Login Linear] Não chegou na Home dentro do tempo limite.")
        if callback_status:
            callback_status("Tempo esgotado aguardando a Home do Facebook.")
        return False

    except Exception as e:
        logger.error(f"Erro no login: {e}")
        return False


def _na_tela_codigo_2fa(driver):
    """
    True SOMENTE se ainda estamos na tela de DIGITAR o código 2FA — ou seja, a
    URL é de two_factor/two_step E NÃO é a "remember_browser" (Trust this
    device, que já passou do código). É o sinal usado para decidir se o código
    foi aceito: assim que o Facebook ACEITA o código, ele MUDA a URL (para
    remember_browser, checkpoint ou home), então esta função passa a retornar
    False e NÃO geramos um novo código.
    """
    try:
        u = (driver.current_url or '').lower()
        if 'remember_browser' in u:
            return False
        return ('two_factor' in u or 'two_step' in u)
    except Exception:
        return False


def _tratar_2fa(driver, tfa_code, callback_status=None):
    """
    Trata a verificação 2FA (código do app autenticador).

    Robustez:
      - Gera o código TOTP com segredo limpo e HORÁRIO DE REDE (independe do
        relógio local). Se o pyotp faltar, registra erro claro e NÃO digita lixo.
      - Preenche o campo garantindo o valor (com fallback via JS).
      - Após clicar em Continue, AGUARDA a página SAIR da tela de código antes de
        julgar. Se saiu (código aceito) -> retorna True e NÃO gera novo código.
        Só gera novo código se PERMANECEU na tela de código (errado/expirado).
    """
    try:
        # 1. Aguarda a página ficar 100% estática antes de procurar os campos
        from server.page_state_manager import PageStateManager
        PageStateManager.wait_for_page_load(driver, timeout=5)
        
        if not tfa_code:
            logger.error("[2FA] Perfil sem segredo/código 2FA disponível.")
            return _aguardar_login_concluido(driver, callback_status, timeout=120)

        # Selectors ESPECÍFICOS do campo de código 2FA (preferência).
        campo_selectors_esp = [
            (By.CSS_SELECTOR, 'input[name="approvals_code"]'),
            (By.CSS_SELECTOR, '#approvals_code'),
            (By.CSS_SELECTOR, 'input[aria-label="Code"]'),
            (By.CSS_SELECTOR, 'input[aria-label="Código"]'),
            (By.CSS_SELECTOR, 'input[autocomplete="one-time-code"]'),
        ]
        code_css_esp = ('input[name="approvals_code"], #approvals_code, '
                        'input[aria-label="Code"], input[aria-label="Código"], '
                        'input[autocomplete="one-time-code"]')
        # Fallback GENÉRICO (input[type=tel]/[type=text]) usado SÓ quando a URL
        # confirma que é a tela de 2FA (two_factor/two_step): a tela de código
        # MODERNA às vezes NÃO tem name/aria-label/one-time-code, e sem estes o bot
        # não achava o campo e ficava em LOOP sem digitar → "não foi possível logar"
        # (bug 2026-08-14). Na URL de 2FA não existe campo de e-mail de login, então
        # o genérico é seguro aqui; fora dela (login), a GUARDA de URL abaixo impede.
        campo_selectors_gen = campo_selectors_esp + [
            (By.CSS_SELECTOR, 'input[inputmode="numeric"]'),
            (By.CSS_SELECTOR, 'input[type="tel"]'),
            (By.CSS_SELECTOR, 'input[type="text"]'),
        ]
        code_css_gen = code_css_esp + (', input[inputmode="numeric"], '
                                       'input[type="tel"], input[type="text"]')

        for tentativa in range(2):
            # ESC leve via DOM (sem focar a janela/menu): na tela de 2FA não há a
            # bolha nativa "Fazer login como" — preencher/clicar via JS atravessa
            # qualquer bolha de "Salvar senha?" do navegador.
            _esc_via_dom(driver)
            _delay(0.2, 0.4)

            # GUARDA: só digita se AINDA é a tela de código 2FA — URL genuína
            # (two_factor/two_step) OU o campo específico de código presente. Espelha
            # a MESMA lógica do page_state_manager (`tem_campo_2fa OR em_2fa_url`).
            # Se o FB reverteu para o LOGIN (sem campo 2FA e sem URL 2FA), NÃO digitar:
            # digitar agora jogaria o OTP no campo de e-mail do login e clicaria
            # "Entrar" (bug 2026-08-13). Retorna True p/ o loop externo reavaliar
            # (ele re-preenche login/senha no handler 'login_form').
            if not _na_tela_codigo_2fa(driver) and not _tem_campo_codigo_2fa(driver):
                logger.info("[2FA] Não é mais a tela de código (url=%s) — não digito o "
                            "OTP; deixo o loop externo reavaliar (re-login/home).",
                            driver.current_url)
                return True

            # Na tela de 2FA CONFIRMADA por URL (two_factor/two_step) usamos também os
            # selectors GENÉRICOS (o campo "Code" moderno pode não ter atributo
            # específico). Fora dela, só os específicos — a guarda acima já garante
            # que não estamos no login, então o genérico não pega o campo de e-mail.
            if _na_tela_codigo_2fa(driver):
                campo_selectors, code_css = campo_selectors_gen, code_css_gen
            else:
                campo_selectors, code_css = campo_selectors_esp, code_css_esp

            # Gerar SEMPRE um código fresco (corrigido pelo horário de rede)
            codigo = _gerar_codigo_2fa(tfa_code)
            if not codigo:
                logger.error("[2FA] Não foi possível gerar o código 2FA. Abortando.")
                if callback_status:
                    callback_status("Falha ao gerar código 2FA (pyotp/segredo).")
                return False

            campo_2fa = _esperar_qualquer(driver, campo_selectors, timeout=5)
            if not campo_2fa:
                # Sem campo de código e já fora da tela de código = código já
                # aceito / outra tela. Retorna True e deixa o loop externo do
                # fazer_login_facebook tratar a próxima tela (Trust device/Home).
                if not _na_tela_codigo_2fa(driver):
                    logger.info("[2FA] Campo ausente e já saiu da tela de código — seguindo fluxo.")
                    return True
                logger.warning("[2FA] Campo de código não encontrado; tentando novamente.")
                _delay(0.5, 1.0)
                continue

            if callback_status:
                callback_status(f"Digitando código 2FA (tentativa {tentativa + 1})...")

            # Preencher o campo GARANTINDO o valor
            _digitar(campo_2fa, codigo)
            _delay(0.3, 0.5)
            if _ler_valor_input(driver, code_css) != codigo:
                try:
                    driver.execute_script("""
                        var el = document.querySelector(arguments[0]);
                        if (el) {
                            el.focus();
                            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            setter.call(el, arguments[1]);
                            el.dispatchEvent(new Event('input', {bubbles:true}));
                            el.dispatchEvent(new Event('change', {bubbles:true}));
                        }
                    """, code_css, codigo)
                except Exception:
                    pass
            _delay(0.3, 0.5)

            # Clicar em Continue/Continuar (div[role=button] no 2FA moderno)
            btn = _esperar_qualquer(driver, [
                (By.CSS_SELECTOR, '#checkpointSubmitButton'),
                (By.CSS_SELECTOR, 'button[type="submit"]'),
                (By.XPATH, "//div[@role='button' and (.//span[normalize-space()='Continue'] or .//span[normalize-space()='Continuar'])]"),
                (By.XPATH, "//button[normalize-space()='Continue' or normalize-space()='Continuar']"),
            ], timeout=5)
            if btn:
                _clicar(driver, btn)
            else:
                clicou_js = False
                try:
                    clicou_js = driver.execute_script("""
                        var alvos = ['continue', 'continuar', 'enviar', 'submit', 'confirmar', 'confirm'];
                        var els = document.querySelectorAll('button, div[role="button"], span[role="button"]');
                        for (var i = 0; i < els.length; i++) {
                            var t = (els[i].innerText || '').trim().toLowerCase();
                            for (var j = 0; j < alvos.length; j++) {
                                if (t === alvos[j]) { els[i].click(); return true; }
                            }
                        }
                        return false;
                    """)
                except Exception:
                    clicou_js = False
                if not clicou_js:
                    try:
                        campo_2fa.send_keys(Keys.RETURN)
                    except Exception:
                        pass

            if callback_status:
                callback_status("Código 2FA enviado. Aguardando resposta do Facebook...")

            from server.page_state_manager import PageStateManager

            # ── Aguardar a página SAIR da tela de código ANTES de julgar ──
            # PONTO CRÍTICO: ao clicar Continue, a página de código continua
            # ESTÁTICA por um instante antes de o Facebook navegar para a próxima
            # tela (Trust device/Checkpoint/Home). Se julgássemos agora, a URL
            # ainda seria "two_factor" e o código (já aceito) seria tratado como
            # recusado -> gerava novo código em loop e o navegador fechava com
            # erro. Então AGUARDAMOS sair da tela de código (sucesso) OU surgir um
            # erro EXPLÍCITO (código errado/expirado). NUNCA gerar novo código se
            # já saiu da tela — o código foi aceito.
            marcadores_erro = [
                "doesn't match", 'does not match', "didn't match", 'incorrect',
                'invalid code', 'no coincide', 'incorrecto', 'inválid',
                'não corresponde', 'incorreto', 'código inválido', 'try again',
                'tente novamente', 'wrong code', 'check the code', 'verifique o código',
                'enter a valid', 'insira um código', 'código incorreto',
            ]
            saiu_da_tela = False
            erro_codigo = False
            fim_2fa = time.time() + 35  # janela generosa (4G lento)
            while time.time() < fim_2fa:
                # Espera curta por estabilização entre as checagens (sem F5 aqui:
                # o F5 fica a cargo do loop externo do fazer_login_facebook).
                PageStateManager.wait_until_stable(driver, timeout=8, settle_time=0.8,
                                                   f5_after=30, callback_status=None)
                if not _na_tela_codigo_2fa(driver):
                    saiu_da_tela = True
                    break
                # Ainda na tela de código -> só é recusa se houver erro EXPLÍCITO.
                # FIX 2026-10-12: lê o TEXTO VISÍVEL (innerText), não o page_source —
                # o HTML do FB embute JSON/i18n com 'try again'/'incorrect' etc. nos
                # <script>, o que dava "código recusado" falso logo no 1º check e
                # gerava código novo à toa (fonte de loop no 2FA).
                try:
                    page = (driver.execute_script(
                        "return (document.body && document.body.innerText || '');") or '').lower()
                    erro_codigo = any(m in page for m in marcadores_erro)
                except Exception:
                    erro_codigo = False
                if erro_codigo:
                    break
                time.sleep(1.0)

            if saiu_da_tela:
                logger.info("[2FA] Código ACEITO — saiu da tela de código (url=%s). NÃO gerar novo código.",
                            driver.current_url)
                # Deixa o loop externo tratar a próxima tela (Trust device/Home).
                return True

            # Permaneceu na tela de código -> errado/expirado -> limpar e tentar
            # outra vez com um código NOVO (próxima janela TOTP).
            logger.warning("[2FA] Código não aceito (tentativa %s/2, erro_detectado=%s).",
                           tentativa + 1, erro_codigo)
            if callback_status:
                callback_status("Código 2FA recusado/expirado. Gerando novo código...")

            try:
                driver.execute_script("""
                    var el = document.querySelector(arguments[0]);
                    if (el) {
                        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, '');
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                    }
                """, code_css)
            except Exception:
                pass

            if tentativa < 1:
                _aguardar_proxima_janela_totp()

        logger.error("[2FA] Esgotadas as tentativas de inserir o código 2FA.")
        return False
    except Exception as e:
        logger.error(f"Erro no 2FA: {e}")
        return False


# ============================================================================
# ALTERAR IDIOMA PARA PT-BR - SELETORES FIXOS + GEMINI FALLBACK
# ============================================================================

def _idioma_ja_ptbr(driver):
    """True se a UI do Facebook JÁ está em Português (Brasil). Sinal PRINCIPAL:
    <html lang> começando com 'pt' (pt-BR → lang="pt-BR", vietnamita → "vi",
    inglês → "en"). Secundário: textos-âncora de pt-BR na página. É o veredito
    confiável e independente do idioma anterior."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            var lang = (document.documentElement.getAttribute('lang') || '').toLowerCase();
            if (lang.indexOf('pt') === 0) return true;
            var b = (document.body ? (document.body.innerText || '') : '').toLowerCase();
            var anc = ['configurações','notificações','página inicial','criar','conta',
                       'idioma e região','informações','amigos','vídeo'];
            var h = 0; for (var i = 0; i < anc.length; i++) { if (b.indexOf(anc[i]) !== -1) h++; }
            return h >= 3;
        }"""))
    except Exception:
        return False


def _forcar_locale_ptbr(driver, callback_status=None, tentativas=4):
    """⚠️ DEPRECADO / NÃO USAR. Mantido só como referência.

    `?locale=pt_BR` + cookie `locale` apenas TRADUZEM a página temporariamente —
    a CONTA continua no idioma original (vietnamita/etc.). O usuário confirmou
    ao vivo que isso NÃO muda o idioma. Use `alterar_idioma_para_ptbr` (troca o
    "Idioma da conta" em settings, de forma PERMANENTE). Não chame esta função.

    Força a SESSÃO do Facebook para pt-BR de forma ROBUSTA e INDEPENDENTE do
    idioma atual da conta (vietnamita/inglês/etc.).

    Mecanismo: o cookie `locale` é quem controla o idioma da UI web (a conta
    comprada injeta locale=vi_VN → UI em vietnamita). Aqui SOBRESCREVEMOS o
    cookie `locale` para pt_BR (via Playwright context E via document.cookie, com
    redundância) e recarregamos com ?locale=pt_BR. Depois VERIFICAMOS pelo
    <html lang>. Retenta até `tentativas` vezes. Retorna True se confirmado."""
    for tentativa in range(1, int(tentativas) + 1):
        try:
            # 1) Cookie via Playwright context (mais confiável) — best-effort.
            try:
                ctx = getattr(driver, 'context', None)
                if ctx is not None and hasattr(ctx, 'add_cookies'):
                    ctx.add_cookies([
                        {'name': 'locale', 'value': 'pt_BR',
                         'domain': '.facebook.com', 'path': '/'},
                        {'name': 'locale', 'value': 'pt_BR',
                         'domain': '.business.facebook.com', 'path': '/'},
                    ])
            except Exception:
                pass
            # 2) Cookie via JS (locale NÃO é httpOnly — o cliente pode setar).
            try:
                driver.evaluate_page("""() => {
                    try {
                        var exp = new Date(Date.now() + 365*24*3600*1000).toUTCString();
                        document.cookie = 'locale=pt_BR; expires=' + exp + '; path=/; domain=.facebook.com';
                        document.cookie = 'locale=pt_BR; expires=' + exp + '; path=/';
                    } catch (e) {}
                    return true;
                }""")
            except Exception:
                pass
            # 3) Força o render em pt-BR (o param sobrepõe o idioma da conta).
            driver.get("https://www.facebook.com/?locale=pt_BR")
            _delay_pagina(2.0, 3.5)
            try:
                _esperar_pagina_carregar(driver, timeout=10)
            except Exception:
                pass
            # 4) Veredito.
            if _idioma_ja_ptbr(driver):
                logger.info("[Idioma] ✅ pt-BR CONFIRMADO via cookie locale (tentativa %d).",
                            tentativa)
                if callback_status:
                    callback_status("✅ Idioma pt-BR confirmado (locale).")
                return True
            logger.info("[Idioma] Ainda não pt-BR após cookie/locale (tentativa %d) — repetindo.",
                        tentativa)
        except Exception as e:
            logger.warning("[Idioma] _forcar_locale_ptbr tentativa %d: %s", tentativa, e)
        _delay_pagina(1.0, 2.0)
    return False


class _IdiomaExigeCodigo(Exception):
    """A troca do idioma da conta pediu reautenticação por CÓDIGO (WhatsApp/e-mail/
    SMS — "Check your WhatsApp messages / Enter the code we sent…"). Sem o código o
    FB não salva o idioma → desistimos da troca e o fluxo segue no idioma atual."""


# Detector idioma-agnóstico do pop-up de código de reautenticação. Sinais fortes:
# contato MASCARADO (+237 *******36 / a***@x.com), "WhatsApp" (marca não traduz),
# input de OTP (autocomplete one-time-code / inputmode numeric / maxlength ≤ 8) e a
# palavra "código" em vários idiomas. Ignora o próprio modal de idiomas (muitos radios).
_JS_REAUTH_CODIGO_IDIOMA = r"""() => {
    var url = (location.href || '').toLowerCase();
    if (/two_step_verification|auth_platform|\/checkpoint\//.test(url)) return 'url:' + url.slice(0, 120);
    function vis(el) {
        var r = el.getBoundingClientRect(); if (r.width <= 0 || r.height <= 0) return false;
        var s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none';
    }
    var dlgs = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
    for (var d = 0; d < dlgs.length; d++) {
        var dg = dlgs[d];
        if (!vis(dg)) continue;
        if (dg.querySelectorAll('[role="radio"], input[type="radio"]').length > 5) continue;
        var t = dg.innerText || '';
        var inputs = Array.prototype.filter.call(dg.querySelectorAll('input'), function (i) {
            var ty = (i.type || 'text').toLowerCase();
            return vis(i) && ['text', 'tel', 'number', 'password', 'search'].indexOf(ty) !== -1;
        });
        if (!inputs.length) continue;
        var otp = inputs.some(function (i) {
            return /one-time-code/i.test(i.autocomplete || '') || /numeric/i.test(i.inputMode || '')
                || (i.maxLength > 0 && i.maxLength <= 8);
        });
        var mascarado = /\*{3,}\s*\d{1,4}/.test(t) || /[^\s@]\*{2,}[^\s]*@/.test(t);
        var wa = /whatsapp/i.test(t);
        var kw = /\bcodes?\b|código|codice|mã |mã$|код|kode|kodu|\bkod\b|코드|コード|验证码|驗證碼|รหัส|कोड|کد|رمز/i.test(t);
        var score = (mascarado ? 2 : 0) + (wa ? 1 : 0) + (otp ? 1 : 0) + (kw ? 1 : 0);
        if (score >= 2) return 'dialog:' + t.replace(/\s+/g, ' ').slice(0, 140);
    }
    return '';
}"""


def _checar_reauth_codigo_idioma(driver, etapa=''):
    """Levanta `_IdiomaExigeCodigo` se o pop-up de código de reautenticação estiver
    na tela. Chamado em cada ponto da troca de idioma onde ele pode surgir."""
    try:
        achado = driver.evaluate_page(_JS_REAUTH_CODIGO_IDIOMA)
    except Exception:
        achado = ''
    if achado:
        raise _IdiomaExigeCodigo(f"{etapa}: {achado}")


def alterar_idioma_para_ptbr(driver, callback_status=None):
    """Wrapper: se a troca exigir código de reautenticação (WhatsApp/e-mail), NÃO
    insiste — sai do pop-up (navega p/ a home; não pede outro código) e segue o
    fluxo no idioma atual do perfil. Marca o driver p/ não tentar de novo na mesma
    sessão (a "garantia final" de idioma chamaria outra vez)."""
    if getattr(driver, '_gs_idioma_exige_codigo', False):
        logger.info("[Idioma] Troca já exigiu código nesta sessão — seguindo no idioma atual.")
        return True
    try:
        return _alterar_idioma_para_ptbr_impl(driver, callback_status)
    except _IdiomaExigeCodigo as e:
        logger.warning("[Idioma] Troca p/ pt-BR exige código de verificação (%s) — "
                       "pulando a troca; o fluxo segue no idioma atual do perfil.", e)
        if callback_status:
            callback_status("Troca de idioma pede código (WhatsApp/e-mail) — seguindo no idioma atual do perfil.")
        try:
            setattr(driver, '_gs_idioma_exige_codigo', True)
        except Exception:
            pass
        try:
            driver.get("https://www.facebook.com/")
            _delay_pagina(1.5, 2.5)
        except Exception:
            pass
        return True


def _alterar_idioma_para_ptbr_impl(driver, callback_status=None):
    """
    Altera o IDIOMA DA CONTA do Facebook para Português (Brasil) de forma
    PERMANENTE (não é tradução temporária da página).

    IMPORTANTE (lição do usuário): NÃO usar `?locale=pt_BR` na URL nem o cookie
    `locale` — isso só TRADUZ a página temporariamente e a CONTA continua no
    idioma original (ex.: vietnamita). O que muda de verdade é ir em
    `settings/?tab=language_and_region` → "Idioma da conta" e selecionar
    "Português (Brasil)" (radio + Salvar). Funciona seja qual for o idioma de
    origem porque casa pelo TEXTO do idioma-alvo, não do idioma atual.

    ORDEM:
    0. Se já está em pt-BR → nada a fazer.
    1. URL direta settings/?tab=language_and_region → modal "Idioma da conta".
    2. Fallback: clicar no link "Idioma da conta" na página → modal.
    3. Fallback: m.facebook.com/language/.
    4. Fallback: Gemini AI. NUNCA é fatal (o fluxo usa URLs diretas).
    """
    try:
        if callback_status:
            callback_status("Alterando idioma para Português (Brasil)...")

        # ===== PASSO 0: já está em pt-BR? =====
        if _idioma_ja_ptbr(driver):
            logger.info("[Idioma] Já está em pt-BR — nada a fazer.")
            return True

        # ===== MÉTODO 1: URL DIRETA — muda o IDIOMA DA CONTA (permanente) =====
        logger.info("[Idioma] Método 1: URL direta settings/?tab=language_and_region")
        driver.get("https://www.facebook.com/settings/?tab=language_and_region")
        _delay_pagina(2.5, 4.0)
        _esperar_pagina_carregar(driver, timeout=10)

        # Ao navegar, o FB pode interpor cookie/consentimento/ad_free (sobretudo em
        # contas em outro idioma) — resolve ANTES de mexer no modal de idioma; senão
        # o modal nunca abre e o fluxo trava.
        _resolver_consentimentos_e_cookies(driver, callback_status)
        _checar_reauth_codigo_idioma(driver, 'settings')

        # Verificar se carregou a página de configurações
        if 'settings' not in driver.current_url.lower():
            logger.warning("[Idioma] URL direta não carregou, tentando alternativa...")
            driver.get("https://www.facebook.com/settings?tab=language")
            _delay_pagina(2.5, 4.0)
            _esperar_pagina_carregar(driver, timeout=10)

        # PASSO 1: Encontrar e clicar no link/botão "Idioma da conta" / "Account language"
        # No layout atual, ao acessar a URL, pode já abrir o modal ou precisar clicar
        resultado_modal = _abrir_modal_idioma_e_selecionar_ptbr(driver, callback_status)
        
        if resultado_modal:
            logger.info("[Idioma] Sucesso via Método 1!")
            driver.get("https://www.facebook.com/")
            _delay_pagina(1.5, 2.5)
            return True

        # ===== MÉTODO 2: Clicar no link "Account language" na página =====
        logger.info("[Idioma] Método 2: Clicando em 'Account language' na página...")
        link_idioma = driver.execute_script("""
            var main = document.querySelector('[role="main"]') || document.body;
            var elements = main.querySelectorAll('div, span, a, [role="button"], [tabindex]');
            for (var i = 0; i < elements.length; i++) {
                var text = (elements[i].innerText || elements[i].textContent || '').trim();
                // Primeiro item clicável na seção principal (geralmente é "Idioma da conta")
                if (text.length > 3 && text.length < 80) {
                    var clickable = elements[i].closest('[role="button"], [tabindex="0"], a, [role="listitem"]');
                    if (clickable) {
                        var rect = clickable.getBoundingClientRect();
                        if (rect.width > 100 && rect.height > 20 && rect.y > 100) {
                            return clickable;
                        }
                    }
                }
            }
            return null;
        """)

        if link_idioma:
            _clicar(driver, link_idioma)
            _delay_pagina(1.5, 2.5)
            _checar_reauth_codigo_idioma(driver, 'metodo2')
            resultado_modal = _abrir_modal_idioma_e_selecionar_ptbr(driver, callback_status)
            if resultado_modal:
                logger.info("[Idioma] Sucesso via Método 2!")
                driver.get("https://www.facebook.com/")
                _delay_pagina(1.5, 2.5)
                return True

        # ===== MÉTODO 3: m.facebook.com/language/ =====
        logger.info("[Idioma] Método 3: Via m.facebook.com/language/...")
        driver.get("https://m.facebook.com/language/")
        _delay_pagina(2.0, 3.0)
        _esperar_pagina_carregar(driver)

        link_ptbr = driver.execute_script("""
            var links = document.querySelectorAll('a');
            for (var i = 0; i < links.length; i++) {
                var href = links[i].getAttribute('href') || '';
                var text = links[i].textContent || '';
                if (href.includes('loc=pt_BR') || href.includes('locale=pt_BR') ||
                    text.includes('Português (Brasil)') || text.includes('Portuguese (Brazil)')) {
                    return links[i];
                }
            }
            return null;
        """)

        if link_ptbr:
            _clicar(driver, link_ptbr)
            _delay_pagina(2.0, 3.0)
            _checar_reauth_codigo_idioma(driver, 'metodo3')
            lang = _detectar_idioma(driver)
            if lang == 'pt_BR':
                logger.info("[Idioma] Sucesso via Método 3!")
                driver.get("https://www.facebook.com/")
                _delay_pagina(1.5, 2.5)
                return True

        # ===== MÉTODO 4: GEMINI AI FALLBACK =====
        if _TEM_GEMINI:
            logger.info("[Idioma] Método 4: Gemini AI fallback...")
            if callback_status:
                callback_status("Usando IA para identificar elementos de idioma...")
            
            driver.get("https://www.facebook.com/settings/?tab=language_and_region")
            _delay_pagina(3.0, 4.0)
            _esperar_pagina_carregar(driver)
            _checar_reauth_codigo_idioma(driver, 'gemini')

            resultado_gemini = _alterar_idioma_via_gemini(driver, callback_status)
            _checar_reauth_codigo_idioma(driver, 'gemini-salvar')
            if resultado_gemini:
                logger.info("[Idioma] Sucesso via Gemini AI!")
                driver.get("https://www.facebook.com/")
                _delay_pagina(1.5, 2.5)
                return True

        logger.warning("[Idioma] Não foi possível alterar idioma. Continuando com multi-idioma.")
        driver.get("https://www.facebook.com/")
        _delay_pagina(1.5, 2.5)
        return True  # Não bloquear o fluxo

    except _IdiomaExigeCodigo:
        raise
    except Exception as e:
        logger.error(f"[Idioma] Erro crítico: {e}")
        return False


def _abrir_modal_idioma_e_selecionar_ptbr(driver, callback_status=None):
    """
    Encontra o modal de idioma (ou abre se necessário) e seleciona Português (Brasil).
    Baseado em seletores fixos extraídos da inspeção real do DOM.
    """
    try:
        # Verificar se o modal já está aberto
        modal = driver.execute_script("""
            return document.querySelector('[role="dialog"]') || 
                   document.querySelector('[aria-modal="true"]');
        """)

        if not modal:
            # Tentar clicar no primeiro item editável da página (seção de idioma)
            logger.info("[Idioma] Modal não aberto, procurando botão de edição...")
            
            # Seletor fixo: primeiro div[role="button"] ou link na área principal
            btn_edit = driver.execute_script("""
                var main = document.querySelector('[role="main"]') || document.body;
                
                // Procurar botão "Edit" / "Editar" em qualquer idioma
                var buttons = main.querySelectorAll('[role="button"], button, a[role="button"]');
                for (var i = 0; i < buttons.length; i++) {
                    var text = (buttons[i].innerText || '').trim();
                    var rect = buttons[i].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && text.length < 25 && text.length > 1) {
                        // Verificar se é um botão de edição (geralmente curto)
                        return buttons[i];
                    }
                }
                
                // Fallback: primeiro item clicável na seção principal
                var clickables = main.querySelectorAll('[tabindex="0"], [role="listitem"]');
                for (var i = 0; i < clickables.length; i++) {
                    var rect = clickables[i].getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 30 && rect.y > 100) {
                        return clickables[i];
                    }
                }
                return null;
            """)

            if btn_edit:
                _clicar(driver, btn_edit)
                _delay_pagina(1.5, 2.5)
            else:
                return False

        # Esperar modal abrir
        _delay_medio(0.5, 1.0)
        
        modal = driver.execute_script("""
            return document.querySelector('[role="dialog"]') || 
                   document.querySelector('[aria-modal="true"]');
        """)

        if not modal:
            logger.warning("[Idioma] Modal não abriu após clique")
            return False

        # O pop-up de código (WhatsApp/e-mail) também é um [role=dialog] com input —
        # sem esta checagem o "campo de busca" abaixo era o campo do CÓDIGO.
        _checar_reauth_codigo_idioma(driver, 'modal')
        logger.info("[Idioma] Modal de idioma detectado!")

        # ===== SELETOR FIXO: Campo de busca no modal =====
        # Baseado nos prints: input[type="text"] dentro do dialog
        campo_busca = driver.execute_script("""
            var dialog = document.querySelector('[role="dialog"]') || 
                         document.querySelector('[aria-modal="true"]');
            if (!dialog) return null;
            
            // Prioridade 1: input dentro de label no dialog
            var inputs = dialog.querySelectorAll('input[type="text"], input[type="search"], input:not([type])');
            for (var i = 0; i < inputs.length; i++) {
                var rect = inputs[i].getBoundingClientRect();
                if (rect.width > 50 && rect.height > 0 && !inputs[i].disabled) {
                    return inputs[i];
                }
            }
            
            // Prioridade 2: input com role textbox
            var textboxes = dialog.querySelectorAll('[role="textbox"], [contenteditable="true"]');
            for (var i = 0; i < textboxes.length; i++) {
                var rect = textboxes[i].getBoundingClientRect();
                if (rect.width > 50 && rect.height > 0) return textboxes[i];
            }
            
            return null;
        """)

        if campo_busca:
            logger.info("[Idioma] Campo de busca encontrado! Digitando 'Brasil'...")
            
            # Digitar "Brasil" para filtrar
            try:
                campo_busca.click()
                _delay(0.1, 0.2)
                campo_busca.clear()
                _delay(0.1, 0.2)
                for char in "Brasil":
                    campo_busca.send_keys(char)
                    _delay_digitacao()
                _delay_medio(1.0, 1.5)
            except:
                try:
                    driver.execute_script("""
                        var el = arguments[0];
                        el.focus();
                        var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeSetter.call(el, 'Brasil');
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    """, campo_busca)
                    _delay_medio(1.0, 1.5)
                except:
                    pass

            # Verificar se "Português (Brasil)" apareceu
            tem_resultado = driver.execute_script("""
                var text = document.body.innerText || '';
                return text.includes('Português (Brasil)') || text.includes('Portuguese (Brazil)');
            """)

            if not tem_resultado:
                logger.info("[Idioma] 'Brasil' não encontrou resultado, tentando 'Brazil'...")
                try:
                    campo_busca.click()
                    campo_busca.send_keys(Keys.CONTROL + "a")
                    campo_busca.send_keys(Keys.BACKSPACE)
                    _delay(0.1, 0.2)
                    for char in "Brazil":
                        campo_busca.send_keys(char)
                        _delay_digitacao()
                    _delay_medio(1.0, 1.5)
                except:
                    pass

            # Tentar também "Portugu" como busca universal
            tem_resultado2 = driver.execute_script("""
                var text = document.body.innerText || '';
                return text.includes('Português (Brasil)') || text.includes('Portuguese (Brazil)');
            """)
            
            if not tem_resultado2:
                logger.info("[Idioma] Tentando busca por 'Portugu'...")
                try:
                    campo_busca.click()
                    campo_busca.send_keys(Keys.CONTROL + "a")
                    campo_busca.send_keys(Keys.BACKSPACE)
                    _delay(0.1, 0.2)
                    for char in "Portugu":
                        campo_busca.send_keys(char)
                        _delay_digitacao()
                    _delay_medio(1.0, 1.5)
                except:
                    pass
        else:
            logger.warning("[Idioma] Campo de busca não encontrado, tentando selecionar direto...")

        # ===== SELETOR FIXO: Radio button "Português (Brasil)" =====
        sucesso = _clicar_radio_ptbr(driver)

        if sucesso:
            logger.info("[Idioma] Radio pt-BR selecionado!")
            _delay_medio(0.5, 1.0)
            _checar_reauth_codigo_idioma(driver, 'radio')

            # Clicar no botão de salvar/confirmar
            _clicar_botao_salvar_idioma(driver)
            _delay_pagina(2.0, 3.0)
            _checar_reauth_codigo_idioma(driver, 'salvar')

            # Verificar se mudou
            lang = _detectar_idioma(driver)
            if lang == 'pt_BR':
                return True
            
            # Mesmo sem confirmar via lang, se clicou no radio e salvou, considerar sucesso
            return True

        return False

    except _IdiomaExigeCodigo:
        raise
    except Exception as e:
        logger.warning(f"[Idioma] Erro no modal: {e}")
        return False


def _clicar_radio_ptbr(driver):
    """
    Clica no radio button de 'Português (Brasil)' no modal.
    Seletor fixo baseado na inspeção real do DOM.
    """
    try:
        # SELETOR FIXO: div[role="radio"] que contém texto "Português (Brasil)"
        ptbr = driver.execute_script("""
            var termos = ['Português (Brasil)', 'Portuguese (Brazil)', 'Portugués (Brasil)'];
            
            // Procurar em dialogs
            var containers = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
            if (containers.length === 0) containers = [document.body];
            
            for (var c = 0; c < containers.length; c++) {
                // Prioridade 1: Radio buttons com aria-checked
                var radios = containers[c].querySelectorAll('[role="radio"], [role="menuitemradio"]');
                for (var i = 0; i < radios.length; i++) {
                    var text = (radios[i].textContent || '').trim();
                    var parentText = radios[i].parentElement ? (radios[i].parentElement.textContent || '').trim() : '';
                    for (var j = 0; j < termos.length; j++) {
                        if (text.includes(termos[j]) || parentText.includes(termos[j])) {
                            return radios[i];
                        }
                    }
                }
                
                // Prioridade 2: Qualquer elemento que contenha o texto exato
                var spans = containers[c].querySelectorAll('span, div, label');
                for (var i = 0; i < spans.length; i++) {
                    var text = (spans[i].innerText || spans[i].textContent || '').trim();
                    for (var j = 0; j < termos.length; j++) {
                        if (text === termos[j] || text.startsWith(termos[j])) {
                            // Subir até encontrar o radio ou container clicável
                            var parent = spans[i].closest('[role="radio"], [role="menuitemradio"], [role="option"], [role="listitem"]');
                            if (parent) return parent;
                            // Tentar o pai direto
                            var p = spans[i].parentElement;
                            if (p) {
                                var radio = p.querySelector('[role="radio"], input[type="radio"]');
                                if (radio) return p;
                                // Subir mais um nível
                                if (p.parentElement) {
                                    radio = p.parentElement.querySelector('[role="radio"]');
                                    if (radio) return p.parentElement;
                                }
                            }
                            return spans[i];
                        }
                    }
                }
            }
            return null;
        """)

        if ptbr:
            logger.info("[Idioma] Encontrou 'Português (Brasil)', clicando...")
            _clicar(driver, ptbr)
            _delay(0.3, 0.5)

            # Verificar se ficou selecionado
            checked = driver.execute_script("""
                var el = arguments[0];
                if (el.getAttribute('aria-checked') === 'true') return true;
                var parent = el.closest('[aria-checked]');
                if (parent && parent.getAttribute('aria-checked') === 'true') return true;
                var radios = el.querySelectorAll('[aria-checked]');
                for (var i = 0; i < radios.length; i++) {
                    if (radios[i].getAttribute('aria-checked') === 'true') return true;
                }
                return false;
            """, ptbr)

            if not checked:
                # Tentar clicar novamente via JS
                driver.execute_script("arguments[0].click();", ptbr)
                _delay(0.3, 0.5)

            return True
        else:
            logger.warning("[Idioma] 'Português (Brasil)' não encontrado na lista")
            return False

    except Exception as e:
        logger.warning(f"[Idioma] Erro ao clicar radio: {e}")
        return False


def _clicar_botao_salvar_idioma(driver):
    """Clica no botão Salvar/Save após selecionar o idioma."""
    # Procurar botão de salvar em qualquer idioma
    btn = driver.execute_script("""
        var saveTexts = ['save','salvar','enregistrer','speichern','salva','guardar',
                        'сохранить','保存','저장','i-save','simpan','lưu','opslaan',
                        'حفظ','kaydet','zapisz','save changes','salvar alterações',
                        'zapisz zmiany','ok','confirm','confirmar',
                        // + idiomas (2026-10-12): HI/TH/BN/UK/MS/IT/RO/CS
                        'सहेजें','सेव करें','บันทึก','সংরক্ষণ','зберегти','simpan perubahan',
                        'salvează','uložit','tallenna','spara','lagre'];
        
        // Procurar em dialogs primeiro
        var containers = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
        if (containers.length === 0) containers = [document.querySelector('[role="main"]') || document.body];
        
        for (var c = 0; c < containers.length; c++) {
            var buttons = containers[c].querySelectorAll('button, [role="button"], div[role="button"]');
            for (var i = 0; i < buttons.length; i++) {
                var text = (buttons[i].innerText || '').trim().toLowerCase();
                var rect = buttons[i].getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                if (buttons[i].disabled || buttons[i].getAttribute('aria-disabled') === 'true') continue;
                
                for (var j = 0; j < saveTexts.length; j++) {
                    if (text === saveTexts[j] || text.includes(saveTexts[j])) {
                        return buttons[i];
                    }
                }
            }
            
            // Fallback: botão azul/primário no dialog
            for (var i = 0; i < buttons.length; i++) {
                var rect = buttons[i].getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                if (buttons[i].disabled) continue;
                var style = getComputedStyle(buttons[i]);
                var bg = style.backgroundColor;
                // + azul ATUAL do FB rgb(8,102,255) (antes só os azuis antigos →
                // em idioma sem texto na lista o Salvar nunca era clicado)
                if (bg.includes('24, 119, 242') || bg.includes('0, 100, 224') || bg.includes('rgb(24')
                    || bg.includes('8, 102, 255') || bg.includes('11, 105, 255')) {
                    return buttons[i];
                }
            }
        }
        return null;
    """)

    if btn:
        logger.info("[Idioma] Botão Salvar encontrado, clicando...")
        _clicar(driver, btn)
        _delay_pagina(2.0, 3.0)
        return True
    
    logger.warning("[Idioma] Botão Salvar não encontrado")
    return False


def _alterar_idioma_via_gemini(driver, callback_status=None):
    """Fallback: usa Gemini AI para alterar o idioma."""
    if not _TEM_GEMINI:
        return False

    try:
        if callback_status:
            callback_status("IA Gemini analisando página de idioma...")

        # Passo 1: Encontrar e clicar no campo de busca via Gemini
        campo = gemini_encontrar_campo_busca_idioma(driver)
        if not campo:
            campo = gemini_analisar_e_agir(driver, 
                "campo de busca/pesquisa de idiomas no modal ou página de configurações de idioma")
        
        if campo:
            try:
                campo.click()
                _delay(0.2, 0.3)
                campo.clear()
                for char in "Brasil":
                    campo.send_keys(char)
                    _delay_digitacao()
                _delay_medio(1.0, 1.5)
            except:
                pass

        # Passo 2: Encontrar e clicar em Português (Brasil)
        ptbr = gemini_encontrar_ptbr_opcao(driver)
        if not ptbr:
            ptbr = gemini_analisar_e_agir(driver,
                "opção 'Português (Brasil)' ou 'Portuguese (Brazil)' na lista de idiomas para selecionar")
        
        if ptbr:
            _clicar(driver, ptbr)
            _delay_medio(0.5, 1.0)

            # Passo 3: Salvar
            btn_salvar = gemini_encontrar_botao_salvar(driver)
            if btn_salvar:
                _clicar(driver, btn_salvar)
                _delay_pagina(2.0, 3.0)
            
            return True

        return False

    except Exception as e:
        logger.warning(f"[Gemini] Erro no fallback de idioma: {e}")
        return False


def _detectar_idioma(driver):
    """Detecta o idioma atual do Facebook."""
    try:
        lang = driver.execute_script("return document.documentElement.lang || ''")
        if lang:
            if 'pt' in lang.lower():
                return 'pt_BR'
        return lang or 'unknown'
    except:
        return 'unknown'


# ============================================================================
# DETECÇÃO DE TELA "SEM ACESSO AO META BUSINESS SUITE"
# ============================================================================

def _tratar_popups_login_facebook(driver, callback_status=None):
    """
    Trata os popups de login do Facebook de forma AGRESSIVA:
    1. 'Fazer login como' -> Clica em 'Fazer login'
    2. 'Faça login sem complicação' -> Clica em 'Ok, entendi'
    """
    def _tentar_clicar_agressivo():
        """Script JS para detectar e clicar em qualquer um dos botões de login/ok em qualquer contexto."""
        js_script = """
            function clicarAgressivo() {
                // Textos EXATOS para o botão "Fazer login" (não título "Fazer login como")
                var textosLoginExatos = ['fazer login', 'log in', 'continuar como', 'continue as', 'login'];
                var textosOk = ['ok, entendi', 'ok, i understand', 'entendi', 'ok', 'confirmar', 'confirm'];
                
                function dispararEventos(el) {
                    try {
                        el.focus();
                        // Tentar clique nativo primeiro
                        el.click();
                        // Depois disparar eventos sintéticos como reforço
                        var eventos = ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click'];
                        eventos.forEach(function(nome) {
                            try {
                                var ev;
                                if (nome.startsWith('pointer')) {
                                    ev = new PointerEvent(nome, {bubbles: true, cancelable: true, view: window, buttons: 1});
                                } else {
                                    ev = new MouseEvent(nome, {bubbles: true, cancelable: true, view: window, buttons: 1});
                                }
                                el.dispatchEvent(ev);
                            } catch(e) {}
                        });
                        return true;
                    } catch (e) {
                        try { el.click(); return true; } catch (e2) { return false; }
                    }
                }

                function buscar(doc) {
                    // PRIORIDADE 1: Popup "Fazer login como" - botão exato "Fazer login"
                    // Procura especificamente botões/divs com texto EXATAMENTE "Fazer login" ou "Log in"
                    var todosElementos = doc.querySelectorAll('button, div[role="button"]');
                    for (var i = 0; i < todosElementos.length; i++) {
                        var el = todosElementos[i];
                        // Usar innerText para pegar só o texto visível direto do elemento (sem filhos)
                        var textoEl = (el.innerText || '').trim().toLowerCase();
                        if (textoEl === 'fazer login' || textoEl === 'log in' || textoEl === 'login') {
                            if (dispararEventos(el)) return {clicou: true, tipo: 'fazer_login_popup'};
                        }
                    }

                    // PRIORIDADE 2: Seletores específicos de aria-label
                    var seletoresAria = [
                        'div[aria-label="Fazer login"]',
                        'div[aria-label="Log in"]',
                        'button[aria-label="Fazer login"]',
                        'button[aria-label="Log in"]'
                    ];
                    for (var s = 0; s < seletoresAria.length; s++) {
                        var el = doc.querySelector(seletoresAria[s]);
                        if (el) {
                            if (dispararEventos(el)) return {clicou: true, tipo: 'aria_login'};
                        }
                    }

                    // PRIORIDADE 3: Busca geral por texto (exclui textos que contenham "como" para evitar título)
                    var elementos = doc.querySelectorAll('button, div[role="button"], span[role="button"]');
                    for (var i = 0; i < elementos.length; i++) {
                        var el = elementos[i];
                        var texto = (el.innerText || el.textContent || '').trim().toLowerCase();
                        // Excluir elementos de título que contenham "fazer login como"
                        if (texto.includes('fazer login como') || texto.includes('log in as')) continue;
                        
                        for (var j = 0; j < textosLoginExatos.length; j++) {
                            if (texto === textosLoginExatos[j] || (texto.length < 20 && texto.includes(textosLoginExatos[j]))) {
                                if (dispararEventos(el)) return {clicou: true, tipo: 'login'};
                            }
                        }
                        
                        for (var j = 0; j < textosOk.length; j++) {
                            if (texto === textosOk[j] || (texto.length < 25 && texto.includes(textosOk[j]))) {
                                if (dispararEventos(el)) return {clicou: true, tipo: 'ok'};
                            }
                        }
                    }
                    
                    // PRIORIDADE 4: Seletores genéricos com verificação de texto
                    var seletores = [
                        'button[type="submit"]', 
                        'button._42ft', 
                        'button._4jy0',
                        '[data-testid="cookie-policy-manage-dialog-accept-button"]'
                    ];
                    for (var s = 0; s < seletores.length; s++) {
                        var el = doc.querySelector(seletores[s]);
                        if (el) {
                            var t = (el.innerText || el.textContent || '').trim().toLowerCase();
                            if (!t.includes('cancelar') && !t.includes('cancel') &&
                                (t.includes('login') || t.includes('log in') || t.includes('entendi') || t.includes('ok'))) {
                                if (dispararEventos(el)) return {clicou: true, tipo: 'seletor'};
                            }
                        }
                    }
                    
                    // PRIORIDADE 5: Iframes
                    var iframes = doc.querySelectorAll('iframe');
                    for (var i = 0; i < iframes.length; i++) {
                        try {
                            var frameDoc = iframes[i].contentDocument || iframes[i].contentWindow.document;
                            if (frameDoc) {
                                var res = buscar(frameDoc);
                                if (res.clicou) return res;
                            }
                        } catch (e) {}
                    }
                    return {clicou: false};
                }
                return buscar(document);
            }
            return clicarAgressivo();
        """
        try:
            return driver.execute_script(js_script)
        except:
            return {'clicou': False}

    try:
        # Loop de detecção por até 15 segundos antes de liberar para as credenciais
        start_time = time.time()
        clicou_em_algo = False
        
        if callback_status:
            callback_status("Monitorando popups de login (prioridade máxima)...")
            
        while time.time() - start_time < 15:
            res = _tentar_clicar_agressivo()
            if res.get('clicou'):
                clicou_em_algo = True
                msg = f"Popup de {res.get('tipo')} detectado e clicado!"
                if callback_status:
                    callback_status(msg)
                logger.info(f"[Login] {msg}")
                
                # Se clicou, espera um pouco para ver se aparece o próximo popup
                time.sleep(3)
                # Reinicia o timer para dar tempo ao segundo popup
                start_time = time.time() - 5 
            else:
                time.sleep(1.5)
                # Se já clicou em algo e agora não acha mais nada, pode ser que limpou a tela
                if clicou_em_algo:
                    break
                    
        return clicou_em_algo
    except Exception as e:
        logger.warning(f"Erro ao tratar popups de login: {e}")
        return False


def _tratar_aviso_comportamento_automatizado(driver, callback_status=None):
    """
    Detecta e clica no botão 'Dismiss' da tela 'We suspect automated behaviour
    on your account'.

    Robustez:
      - Detecta tanto 'behavior' (inglês EUA) quanto 'behaviour' (inglês UK) e
        a variante em português — antes só pegava 'behavior' e perdia a tela.
      - Também trata como checkpoint quando a URL é /checkpoint/ e há um único
        botão grande (clica nele, independente do idioma).
    """
    try:
        # 1. Aguarda a página ficar 100% estática antes de procurar os botões
        from server.page_state_manager import PageStateManager
        PageStateManager.wait_for_page_load(driver, timeout=5)

        url = driver.current_url.lower()
        page_source = driver.page_source.lower()

        # 'automated behavi' cobre behavior E behaviour; FR/ES incluídos.
        eh_aviso = (
            'automated behavi' in page_source or
            'comportamento automatizado' in page_source or
            'comportement automat' in page_source or
            'comportamiento automatizado' in page_source or
            'suspeitamos' in page_source or
            'suspectons' in page_source or
            'sospechamos' in page_source or
            # vietnamita: "...tài khoản của bạn có hành vi tự động" (comportamento automático)
            'hành vi tự động' in page_source or
            'hanh vi tu dong' in page_source
        )
        # FIX 2026-10-12: checkpoint REAL só pelo PATH (/checkpoint/). Antes
        # `'checkpoint' in url` casava o query `?checkpoint_src=` da HOME LOGADA
        # (pós "Confiar neste dispositivo") — e o fallback final clicava o 1º botão
        # curto da home (chamado em toda verificação de login e em
        # _detectar_tela_sem_acesso). Mesmo critério do page_state_manager.
        try:
            from server.page_state_manager import url_eh_checkpoint_real as _ck_real
            eh_checkpoint = _ck_real(url)
        except Exception:
            eh_checkpoint = '/checkpoint' in url.split('?', 1)[0]

        # FIX 2026-10-12: fora de checkpoint real, o texto do aviso tem que estar
        # VISÍVEL — o page_source traz JSON/i18n embutido (falso-positivo provado no
        # page_state_manager em 2026-10-05) e aqui viraria clique às cegas.
        if eh_aviso and not eh_checkpoint:
            try:
                eh_aviso = bool(driver.execute_script(r"""
                    var t = ((document.body && document.body.innerText) || '').toLowerCase();
                    var M = ['automated behavi','comportamento automatizado','comportement automat',
                             'comportamiento automatizado','suspeitamos','suspectons','sospechamos',
                             'hành vi tự động','hanh vi tu dong','seja automatizado','suspect automated'];
                    for (var i = 0; i < M.length; i++) { if (t.indexOf(M[i]) !== -1) return true; }
                    return false;
                """))
            except Exception:
                pass

        if not eh_aviso and not eh_checkpoint:
            return False

        # CONTA TRAVADA / "possivelmente hackeada" (mở khóa / hacked / unlock): BLOQUEIO
        # SEM SAÍDA (só destrava com código no e-mail do perfil, que NÃO acessamos). NÃO
        # clicar em "Bắt đầu/Começar" (entraria no fluxo e perderia tempo). Retorna False
        # p/ o chamador tratar como bloqueio (perfil descartado; site reaproveitado no
        # próximo perfil da fila, pois o domínio não chegou a ser usado).
        try:
            _travada = driver.execute_script(r"""
                try { var t=(document.body&&document.body.innerText||'').toLowerCase();
                  return t.indexOf('mở khóa')!==-1 || t.indexOf('có thể đã bị hack')!==-1 ||
                         t.indexOf('đã khóa tài khoản')!==-1 || t.indexOf('may have been hacked')!==-1 ||
                         t.indexOf('locked your account')!==-1 || t.indexOf('to unlock')!==-1 ||
                         t.indexOf('bloqueamos sua conta')!==-1 || t.indexOf('pode ter sido hackeada')!==-1 ||
                         t.indexOf('nhận mã qua email')!==-1;
                } catch(e){ return false; }
            """)
        except Exception:
            _travada = False
        if _travada:
            logger.warning("[Checkpoint] Conta TRAVADA/possível hack — bloqueio sem saída; NÃO clico (perfil descartado, site reaproveitado).")
            if callback_status:
                callback_status("🔒 Conta travada (possível hack) — bloqueio; descartando perfil.")
            return False

        if callback_status:
            callback_status("Checkpoint detectado. Clicando em 'Dismiss'...")
        logger.info("[Checkpoint] Aviso/checkpoint detectado (url=%s).", driver.current_url)

        # Clicar via JS: primeiro por texto (vários idiomas); se não achar,
        # clica no botão PRIMÁRIO/grande da tela (independe de idioma).
        clicado = driver.execute_script("""
            function visivel(el){
                var r = el.getBoundingClientRect();
                var s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
            }
            
            // 1. Tentar encontrar especificamente o botão azul "Dismiss" da tela de automated behavior
            var els = document.querySelectorAll('div[role="button"], button, span[role="button"]');
            // 'bỏ qua' (vietnamita) = Pular/Ignorar; alguns perfis vêm nesse idioma e o
            // botão que leva à página inicial não era clicado (relato do usuário 2026-07-08).
            var SKIP = ['dismiss','ignorar','ignorer','continuar','continue','continuer','ok',
                        'entendi','entendido','got it',"j'ai compris",'compris','aceptar',
                        'accepter','fechar','fermer','cerrar','descartar','rejeter',
                        'bo qua','skip','pular','saltar','omitir','lewati',
                        // esloveno: Opusti=Dispensar, V redu=OK, Nadaljuj=Continuar,
                        // Razumem=Entendi, Prekliči=Cancelar
                        'opusti','v redu','nadaljuj','razumem','preklici','prekliči',
                        // "Meta took steps to protect your account" (/hacked-protection):
                        'back to facebook','voltar para o facebook','voltar ao facebook'];
            // desacentua (remove combining marks U+0300..U+036F por char-code, sem
            // literais de diacrítico) p/ casar 'bỏ qua'/'bô qua' (vietnamita) etc.
            function semAcento(s){
                try {
                    var d = s.normalize('NFD'), out = '';
                    for (var k = 0; k < d.length; k++){
                        var c = d.charCodeAt(k);
                        if (c < 0x0300 || c > 0x036F) out += d[k];
                    }
                    return out;
                } catch(e){ return s; }
            }
            for (var i = 0; i < els.length; i++) {
                if (!visivel(els[i])) continue;
                var t = (els[i].innerText || '').trim().toLowerCase();
                var tn = semAcento(t);
                for (var s = 0; s < SKIP.length; s++) {
                    var alvo = SKIP[s], alvon = semAcento(alvo);
                    if (t === alvo || tn === alvon) { els[i].click(); return true; }
                }
            }
            
            // 2. Seletor direto do botão de checkpoint (se for um form)
            var sub = document.querySelector('#checkpointSubmitButton, button[type="submit"]');
            if (sub && visivel(sub)) { sub.click(); return true; }
            
            // 3. Procurar o botão primário azul (tem a cor rgb(8, 102, 255) ou similar)
            for (var k = 0; k < els.length; k++) {
                if (!visivel(els[k])) continue;
                var style = window.getComputedStyle(els[k]);
                var bg = style.backgroundColor;
                if (bg.includes('8, 102, 255') || bg.includes('24, 119, 242')) {
                    els[k].click();
                    return true;
                }
            }

            // 4. Fallback idioma-independente (2026-07-31): tela de aviso SEM campo de
            //    entrada e com um botão de ação curto → clica nele (dispensa). Mantém o
            //    handler consistente com a classificação checkpoint_dismiss quando o
            //    idioma é desconhecido (ex.: 'Opusti' esloveno). Dead-ends reais
            //    (hack/selfie/código) têm input OU já foram barrados como severe antes.
            var temInput = false;
            var inps = document.querySelectorAll('input[type="text"],input[type="password"],input[type="tel"],input[type="email"],input[type="file"],input[autocomplete="one-time-code"],input[name="approvals_code"],textarea');
            for (var q = 0; q < inps.length; q++){ if (visivel(inps[q])) { temInput = true; break; } }
            if (!temInput) {
                for (var m = 0; m < els.length; m++){ if (!visivel(els[m])) continue;
                    var tx = (els[m].innerText || '').trim();
                    if (tx.length > 0 && tx.length <= 40) { els[m].click(); return true; } }
            }

            return false;
        """)

        if clicado:
            logger.info("[Checkpoint] Botão 'Dismiss' clicado com sucesso.")
            _delay(0.5, 1.0) # Delay reduzido após o clique
            return True

        # Fallback Playwright/Selenium
        btn = _esperar_qualquer(driver, [
            (By.XPATH, "//button[contains(translate(text(),'DISMISS','dismiss'),'dismiss')]"),
            (By.XPATH, "//div[@role='button'][contains(translate(.,'DISMISS','dismiss'),'dismiss')]"),
            (By.CSS_SELECTOR, "#checkpointSubmitButton"),
            (By.CSS_SELECTOR, "button[type='submit']"),
        ], timeout=1) # Timeout super curto (1s) porque já tentamos via JS
        
        if btn:
            _clicar(driver, btn)
            logger.info("[Checkpoint] Botão 'Dismiss' clicado via fallback.")
            _delay(0.5, 1.0)
            return True
        return False
    except Exception as e:
        logger.warning(f"Erro ao tratar aviso de comportamento automatizado: {e}")
        return False


def _tratar_consentimento_privacidade(driver, callback_status=None):
    """
    Trata a sequência de telas de CONSENTIMENTO DE PRIVACIDADE (LGPD) que o
    Facebook às vezes exige logo após o login, na URL /privacy/consent/:
        1. "Required: Review your data settings"   -> Get Started
        2. "Activity information from ad partners"  -> Accept and continue
        3. "You're all set!"                        -> Close

    INDEPENDENTE DE IDIOMA: em cada etapa clica no botão PRIMÁRIO AZUL (Get
    Started / Accept and continue / Close são todos azuis; "Manage settings" é
    cinza e é EVITADO para não abrir o fluxo de ajustes). Avança etapa a etapa
    (aguardando cada uma carregar 100%) até SAIR do fluxo /privacy/consent/.
    Retorna True se concluiu (saiu do consentimento). Best-effort.
    """
    from server.page_state_manager import PageStateManager
    try:
        for etapa in range(8):
            # Navegador fechado (usuário/queda)? Sai NA HORA.
            if navegador_foi_fechado(driver):
                return False
            # Aguarda a etapa atual carregar 100% e ficar estática (sem F5 aqui:
            # são modais rápidos; o F5 fica a cargo do loop externo).
            PageStateManager.wait_until_stable(driver, timeout=20, settle_time=1.0,
                                               f5_after=25, callback_status=callback_status)
            url = (driver.current_url or '').lower()
            # Saiu do fluxo de consentimento -> concluído
            if 'privacy/consent' not in url and 'lgpd_migrated' not in url and \
               not ('/consent/' in url and 'privacy' in url):
                logger.info("[Privacy] Consentimento concluído (url=%s).", driver.current_url)
                return True

            if callback_status:
                callback_status(f"Consentimento de privacidade — avançando (etapa {etapa + 1})...")

            clicou = driver.execute_script("""
                function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                    var s=getComputedStyle(el);
                    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                function azul(el){ var bg=getComputedStyle(el).backgroundColor||'';
                    return bg.indexOf('8, 102, 255')!==-1 || bg.indexOf('24, 119, 242')!==-1
                        || bg.indexOf('0, 100, 224')!==-1 || bg.indexOf('11, 105, 255')!==-1; }
                // EVITAR (substring): ajustes E a opção PAGA "sem anúncios"/Assinar do
                // fluxo ad_free_subscription — NUNCA clicar nelas.
                var evitar = ['manage settings','gerenciar config','manage','gerenciar',
                              'more options','mais opções','mais opcoes','learn more','saiba mais',
                              'subscribe','assinar','assine','đăng ký','suscribir','suscríbete',
                              'sem anúncios','sem anuncios','without ads','sin anuncios',
                              'không có quảng cáo','không kèm quảng cáo','abonner','abonnement',
                              'quay lại','voltar','go back','regresar','retour',
                              'chuyển sang','switch to','mudar para','ít hơn','menos',
                              // NUNCA recusar cookies opcionais (o azul é "permitir/Cho phép").
                              'từ chối','tu choi','decline','recusar','rechazar','refuser',
                              'chỉ cookie cần thiết','apenas essenciais','only essential'];
                // PREFERENCIAL (substring): a opção GRÁTIS "com anúncios" (mantém grátis,
                // faz a tela não voltar). Tem prioridade sobre tudo.
                // VI: o radio grátis é "Dùng miễn phí kèm quảng cáo" (usa 'kèm', não 'có').
                var prefer = ['free with ads','use for free with ads','continue with ads',
                              'use facebook for free','com anúncios','com anuncios',
                              'gratuitamente com anúncios','grátis com anúncios','de graça com anúncios',
                              'có quảng cáo','miễn phí có quảng cáo','tiếp tục với quảng cáo',
                              'miễn phí kèm quảng cáo','kèm quảng cáo','dùng miễn phí',
                              'con anuncios','gratis con anuncios','avec des publicités','avec publicités'];
                // AVANÇAR o fluxo (texto exato, multi-idioma) — inclui 'bắt đầu' (VI).
                var alvos = ['get started','começar','comecar','bắt đầu','vamos começar','vamos comecar',
                             'accept and continue','aceitar e continuar','accept','aceitar',
                             'continue','continuar','tiếp tục','close','fechar','done','concluir',
                             'confirm','confirmar','ok',
                             // VI/PT/EN: concordar/confirmar do fluxo ad_free (Đồng ý / Xác nhận)
                             'đồng ý','xác nhận','concordo','concordar','agree','i agree',
                             'đã hiểu','entendi','got it','entendido',
                             // Cookies: permitir TODOS (azul) como alvo EXPLÍCITO (VI/PT/EN/ES)
                             'cho phép tất cả cookie','cho phép tất cả','allow all cookies',
                             'permitir todos os cookies','allow all','permitir todos','aceptar todas'];
                var els = document.querySelectorAll('div[role="button"], button, a[role="button"], span[role="button"], label, [role="radio"]');
                function tem(arr,t){ for(var e=0;e<arr.length;e++){ if(t.indexOf(arr[e])!==-1) return true; } return false; }
                // Já SELECIONADO? (radio marcado) — não re-clicar a opção grátis, senão
                // o loop nunca avança para 'Continuar/Tiếp tục' (fica preso na tela 2).
                function jaSel(el){
                    if(!el) return false;
                    if(el.getAttribute && el.getAttribute('aria-checked')==='true') return true;
                    var r = el.closest ? el.closest('[role="radio"]') : null;
                    if(r && r.getAttribute('aria-checked')==='true') return true;
                    var inp = el.querySelector ? el.querySelector('input[type="radio"]') : null;
                    if(inp && inp.checked) return true;
                    return false;
                }
                // 0) PREFERENCIAL: opção grátis com anúncios (substring), nunca evitar,
                //    e SÓ se ainda não estiver selecionada.
                for (var p=0;p<els.length;p++){ if(!vis(els[p])) continue;
                    var tp=(els[p].innerText||'').trim().toLowerCase();
                    if(!tp || tem(evitar,tp)) continue;
                    if(tem(prefer,tp) && !jaSel(els[p])){ els[p].click(); return 'free:'+tp.slice(0,40); }
                }
                // 1) Por TEXTO desejado EXATO (e que NÃO seja de evitar)
                for (var i=0;i<els.length;i++){ if(!vis(els[i])) continue;
                    var t=(els[i].innerText||'').trim().toLowerCase();
                    if(!t || tem(evitar,t)) continue;
                    for(var j=0;j<alvos.length;j++){ if(t===alvos[j]){ els[i].click(); return t; } }
                }
                // 2) Botão PRIMÁRIO AZUL (independe de idioma), evitando os de "evitar"
                for (var k=0;k<els.length;k++){ if(!vis(els[k])) continue;
                    var tk=(els[k].innerText||'').trim().toLowerCase();
                    if(tem(evitar,tk)) continue;
                    if(azul(els[k])){ els[k].click(); return tk || 'botao_azul'; }
                }
                return false;
            """)

            if clicou:
                logger.info("[Privacy] Etapa %s — clicado: '%s'.", etapa + 1, clicou)
                time.sleep(1.5)
            else:
                # Sem botão reconhecível — tenta ESC (fecha o modal) e segue
                logger.info("[Privacy] Nenhum botão reconhecível na etapa %s.", etapa + 1)
                try:
                    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                except Exception:
                    pass
                time.sleep(1.0)

        url = (driver.current_url or '').lower()
        saiu = ('privacy/consent' not in url and 'lgpd_migrated' not in url and
                not ('/consent/' in url and 'privacy' in url))
        if not saiu:
            logger.warning("[Privacy] Consentimento não concluído após 8 etapas (url=%s).", url)
        return saiu
    except Exception as e:
        logger.warning("[Privacy] Erro ao tratar consentimento de privacidade: %s", e)
        return False


def _dispensar_lembrar_senha(driver):
    """
    Dispensa o diálogo IN-DOM "Remember password / Lembrar senha" que aparece na
    Home logo após o login (botões OK / Not now). NÃO clica em OK (que ativaria o
    login por foto e a bolha "Fazer login como"); prefere "Not now/Agora não" e,
    como reforço, ESC. Idioma-independente. Best-effort.
    """
    try:
        driver.execute_script("""
            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                var s=getComputedStyle(el);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
            var alvos = ['not now','agora não','agora nao','ahora no','plus tard','jetzt nicht',
                         'non ora','sekarang tidak','không phải bây giờ','не сейчас','以后再说','나중에'];
            var els = document.querySelectorAll('div[role="button"], button, a[role="button"], span[role="button"]');
            for (var i=0;i<els.length;i++){ if(!vis(els[i])) continue;
                var t=(els[i].innerText||'').trim().toLowerCase();
                for (var j=0;j<alvos.length;j++){ if(t===alvos[j]){ els[i].click(); return true; } }
            }
            return false;
        """)
    except Exception:
        pass
    try:
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    except Exception:
        pass


def _detectar_tela_sem_acesso(driver):
    """Detecta se está na tela 'sem acesso ao Business Suite'."""
    try:
        # Antes de verificar falta de acesso, checar se há o aviso de 'Automated Behavior' bloqueando a vista
        _tratar_aviso_comportamento_automatizado(driver)

        url = driver.current_url.lower()
        if 'business.facebook.com' not in url:
            return False

        return driver.execute_script("""
            var body = (document.body.innerText || '').toLowerCase();
            var termos = [
                "can't access meta business suite", "cannot access meta business suite",
                "não é possível acessar o meta business suite",
                "hindi ma-access ang meta business suite",
                "no se puede acceder a meta business suite",
                "tidak dapat mengakses meta business suite",
                "không thể truy cập meta business suite",
                "walang access", "you don't have access", "você não tem acesso"
            ];
            for (var i = 0; i < termos.length; i++) {
                if (body.includes(termos[i])) return true;
            }
            
            // Verificar botão "Criar página do Facebook"
            var btns = document.querySelectorAll('a[role="button"], button, div[role="button"]');
            var btnTexts = ['create a facebook page', 'criar uma página do facebook',
                           'gumawa ng facebook page', 'buat halaman facebook'];
            for (var b = 0; b < btns.length; b++) {
                var t = (btns[b].innerText || '').trim().toLowerCase();
                for (var j = 0; j < btnTexts.length; j++) {
                    if (t.includes(btnTexts[j])) return true;
                }
            }
            return false;
        """) or False
    except:
        return False


def _detectar_bm_bloqueada(driver):
    """
    Detecta se a BM recém-criada está com restrições (banner vermelho).
    Ex: "Portfólio empresarial com restrições para anunciar"
    """
    try:
        url = driver.current_url.lower()
        if 'business.facebook.com' not in url:
            return False

        return driver.execute_script("""
            var body = (document.body.innerText || '').toLowerCase();
            var termos = [
                "restrições para anunciar",
                "restrictions on advertising",
                "restricted from advertising",
                "portfolio with restrictions",
                "portfólio empresarial com restrições",
                "business portfolio restricted",
                "can't run ads",
                "não é possível usar a empresa",
                "não é possível veicular anúncios",
                "account restricted",
                "conta restrita"
            ];
            for (var i = 0; i < termos.length; i++) {
                if (body.includes(termos[i])) return true;
            }
            // Detectar banner vermelho/laranja de restrição
            var banners = document.querySelectorAll('[role="alert"], [data-type="error"], [class*="error"], [class*="warning"], [class*="restriction"]');
            for (var b = 0; b < banners.length; b++) {
                var text = (banners[b].innerText || '').toLowerCase();
                for (var i = 0; i < termos.length; i++) {
                    if (text.includes(termos[i])) return true;
                }
            }
            return false;
        """) or False
    except:
        return False


def _bm_pagina_com_erro(driver):
    """
    Detecta se a página da BM recém-criada (business_home) caiu na tela de ERRO
    ("Estamos tendo problemas para concluir sua solicitação." / "Something went
    wrong" — multi-idioma) OU ficou praticamente EM BRANCO (SPA não renderizou).
    Nesses casos é preciso um F5 para recarregar completamente. Best-effort.
    """
    try:
        txt = driver.execute_script(
            "return (document.body && document.body.innerText || '').trim().toLowerCase();"
        ) or ''
        marcadores = [
            'estamos tendo problemas', 'problemas para concluir', 'tendo problemas',
            'something went wrong', 'sorry, something went wrong',
            "we're having trouble", 'having trouble completing', 'having trouble',
            "couldn't complete your request", 'could not complete your request',
            'algo deu errado', 'tente novamente mais tarde', 'try again later',
            'estamos com problemas', 'no pudimos completar', 'algo salió mal',
        ]
        for m in marcadores:
            if m in txt:
                return True
        # Página praticamente em branco (SPA não renderizou) -> também exige F5.
        try:
            n_nos = driver.execute_script("return document.querySelectorAll('*').length;") or 0
        except Exception:
            n_nos = 0
        if len(txt.strip()) < 5 and n_nos < 60:
            return True
        return False
    except Exception:
        return False


def _bm_pagina_carregada(driver):
    """
    True quando a página da BM (business_home) está REALMENTE renderizada — com
    o painel/menu visível (como no exemplo: "Página inicial", navegação lateral,
    cards de "Desempenho da conta de anúncios"/"Perfis") — e NÃO em branco/erro.
    Idioma-independente: usa os papéis ARIA do shell do Business + volume de DOM.
    """
    try:
        if _bm_pagina_com_erro(driver):
            return False
        return bool(driver.execute_script("""
            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                return r.width>0 && r.height>0; }
            // Shell do Business renderizado (nav lateral / topo / conteúdo principal).
            if (vis(document.querySelector('[role="navigation"]'))) return true;
            if (vis(document.querySelector('[role="banner"]'))) return true;
            if (vis(document.querySelector('[role="main"]'))) return true;
            // Reforço: conteúdo substancial (não é página em branco).
            var n = document.querySelectorAll('*').length;
            var txt = (document.body && document.body.innerText || '').trim();
            return n > 250 && txt.length > 80;
        """))
    except Exception:
        return False


def _obter_novo_email_tmail(driver, email_anterior=None, callback_status=None):
    """
    Fecha a aba TMail existente e abre uma nova para obter um email diferente.
    Garante que o email retornado seja diferente do anterior.
    """
    # E-MAIL PRÓPRIO DO SITE: se há uma conta nova do painel (2ª BM = site novo),
    # é ela que vale — já é naturalmente diferente da anterior.
    _modo_em = _resolver_modo_email()
    if _modo_em != 'raiz':
        _pre = _consumir_email_pre(driver, email_anterior)
        if _pre:
            if callback_status:
                callback_status(f"Email próprio do site: {_pre[0]}")
            return _pre
    # GSMAILS (API): gera um novo e-mail (naturalmente diferente). Sem abas.
    try:
        from server.gsmails_integration import gsmails_enabled, create_email
        if gsmails_enabled():
            for _ in range(3):
                conta = create_email(label="BM", base_nome=getattr(driver, "_empresa_razao", None),
                                     host=(None if _modo_em == 'raiz' else getattr(driver, "_site_host", None)),
                                     domain=_site_root_apex(driver))
                if conta and conta.get("address") and conta["address"] != email_anterior:
                    try:
                        if not hasattr(driver, "_gsmails_accounts"):
                            driver._gsmails_accounts = {}
                        driver._gsmails_accounts[conta["address"]] = conta
                        driver._gsmails_last = conta
                    except Exception:
                        pass
                    if callback_status:
                        callback_status(f"Novo email GSMAILS: {conta['address']}")
                    return conta["address"], "__GSMAILS_API__"
    except Exception as _e:
        logger.warning("[GSMAILS] _obter_novo_email_tmail — fallback p/ navegador: %s", _e)

    # Fechar aba TMail existente
    try:
        aba_atual = _localizar_aba_tmail(driver)
        if aba_atual:
            driver.switch_to.window(aba_atual)
            driver.close()
            # Limpar referência
            try:
                driver._tmail_handle = None
            except:
                pass
            driver.switch_to.window(driver.window_handles[0])
            _delay(0.5, 1.0)
    except:
        try:
            driver.switch_to.window(driver.window_handles[0])
        except:
            pass

    # Obter novo email (com retry para garantir email diferente)
    for tentativa in range(5):
        email_novo, aba_nova = obter_email_tmail(driver)
        if email_novo and email_novo != email_anterior:
            if callback_status:
                callback_status(f"Novo email TMail: {email_novo}")
            return email_novo, aba_nova
        # Se pegou o mesmo email, fechar e tentar de novo
        if aba_nova:
            try:
                driver.switch_to.window(aba_nova)
                driver.close()
                try:
                    driver._tmail_handle = None
                except:
                    pass
                driver.switch_to.window(driver.window_handles[0])
            except:
                try:
                    driver.switch_to.window(driver.window_handles[0])
                except:
                    pass
        _delay(1.0, 2.0)

    return None, None


# ============================================================================
# TMAIL - AUXILIARES PLAYWRIGHT
# ============================================================================

def _handle_atual(driver):
    """Obtém o handle atual de aba de forma compatível."""
    try:
        return driver.current_window_handle
    except Exception:
        handles = getattr(driver, 'window_handles', []) or []
        return handles[0] if handles else None


def _abrir_nova_aba(driver, url='about:blank'):
    """Abre nova aba de forma robusta em Selenium/Playwright."""
    handles_antes = list(getattr(driver, 'window_handles', []) or [])

    if hasattr(driver, 'open_new_tab'):
        try:
            handle = driver.open_new_tab(url or 'about:blank', switch=True, wait_networkidle=False)
            _delay(0.2, 0.4)
            return handle
        except Exception as e:
            logger.warning(f"Falha ao abrir nova aba via Playwright nativo: {e}")

    script = f"window.open({url!r}, '_blank');" if url else "window.open('', '_blank');"
    driver.execute_script(script)

    fim = time.time() + 8
    while time.time() < fim:
        handles = list(getattr(driver, 'window_handles', []) or [])
        novos = [h for h in handles if h not in handles_antes]
        if novos:
            try:
                driver.switch_to.window(novos[-1])
            except Exception:
                pass
            return novos[-1]
        time.sleep(0.2)

    handles = list(getattr(driver, 'window_handles', []) or [])
    if handles:
        try:
            driver.switch_to.window(handles[-1])
        except Exception:
            pass
        return handles[-1]
    return None


def _localizar_aba_tmail(driver):
    """Procura aba já aberta do TMail."""
    handle_original = _handle_atual(driver)
    for handle in list(getattr(driver, 'window_handles', []) or []):
        try:
            driver.switch_to.window(handle)
            _delay(0.05, 0.1)
            url = (driver.current_url or '').lower()
            if 'tmail' in url:
                return handle
        except Exception:
            continue
    if handle_original:
        try:
            driver.switch_to.window(handle_original)
        except Exception:
            pass
    return None


def _ir_para_aba_facebook(driver):
    """Volta para uma aba do Facebook/Business, priorizando a atual."""
    atual = _handle_atual(driver)
    try:
        url = (driver.current_url or '').lower()
        if 'facebook.com' in url or 'business.facebook.com' in url:
            return atual
    except Exception:
        pass

    for handle in list(getattr(driver, 'window_handles', []) or []):
        try:
            driver.switch_to.window(handle)
            url = (driver.current_url or '').lower()
            if 'facebook.com' in url or 'business.facebook.com' in url:
                return handle
        except Exception:
            continue

    handles = list(getattr(driver, 'window_handles', []) or [])
    if handles:
        try:
            driver.switch_to.window(handles[0])
            return handles[0]
        except Exception:
            return handles[0]
    return None


def _abrir_ou_reutilizar_aba_tmail(driver):
    """Reutiliza aba TMail existente ou abre uma nova."""
    aba_tmail = getattr(driver, '_tmail_handle', None)
    handles = set(getattr(driver, 'window_handles', []) or [])
    if aba_tmail and aba_tmail in handles:
        try:
            driver.switch_to.window(aba_tmail)
            return aba_tmail
        except Exception:
            pass

    aba_tmail = _localizar_aba_tmail(driver)
    if aba_tmail:
        try:
            driver._tmail_handle = aba_tmail
        except Exception:
            pass
        return aba_tmail

    aba_tmail = _abrir_nova_aba(driver, 'https://tmailsocial.site/')
    if aba_tmail:
        try:
            driver._tmail_handle = aba_tmail
        except Exception:
            pass
    return aba_tmail


def _extrair_email_tmail(driver, timeout=25):
    """Extrai o email temporário do TMail com espera robusta."""
    fim = time.time() + timeout
    while time.time() < fim:
        email = None

        for sel in ['.dropdown-toggle', '.email-address', '[class*="email"]',
                    '#email-address', '.address', 'input[readonly]', 'input[type="text"]']:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    texto = (el.text or '').strip() or (el.get_attribute('value') or '').strip()
                    if '@' in texto and '.' in texto and ' ' not in texto:
                        email = texto
                        break
                if email:
                    break
            except Exception:
                continue

        if not email:
            try:
                email = driver.execute_script("""
                    var inputs = document.querySelectorAll('input[readonly], input[type=\"text\"], input');
                    for (var i = 0; i < inputs.length; i++) {
                        var val = (inputs[i].value || '').trim();
                        if (val.includes('@') && val.includes('.') && !val.includes(' ')) return val;
                    }
                    var elements = document.querySelectorAll('button, span, div, p, a, td, li');
                    for (var i = 0; i < elements.length; i++) {
                        var text = (elements[i].textContent || '').trim();
                        if (text.includes('@') && text.includes('.') && text.length < 80 && !text.includes(' ')) {
                            var match = text.match(/[\\w.+-]+@[\\w.-]+\\.[a-zA-Z]+/);
                            if (match) return match[0];
                        }
                    }
                    return null;
                """)
            except Exception:
                email = None

        if not email:
            try:
                page_text = driver.execute_script("return document.body ? document.body.innerText : '';") or ''
                matches = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', page_text)
                if matches:
                    email = matches[0]
            except Exception:
                email = None

        if email:
            try:
                driver._tmail_email = email
            except Exception:
                pass
            return email

        time.sleep(0.5)

    return None


# ============================================================================
# OBTER EMAIL DO TMAIL.SOCIAL
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# E-MAIL DA BM = E-MAIL DO SITE (UNIFICADO, 2026-08-15) — 1 e-mail p/ tudo
# ─────────────────────────────────────────────────────────────────────────────
# RELIGADO (True). O painel agora cria o e-mail do site no **APEX da raiz** (a
# `criar_site` chama `gs_email_do_site` na hora, e as raízes do estoque têm
# apex_email=1 — ver memória gs-metodo-pro-max-email). Esse e-mail apex RECEBE
# (não é mais o subdomínio recusado que motivou o desligamento em 2026-08-10),
# então a BM passa a CONSUMIR o e-mail do site como `bm_email`:
#   → 1 único e-mail cria a BM, verifica (Método E-mail), vai no certificado, fica
#     salvo em Detalhes do Site e na observação do multilogin. Sem conta lixo.
# `_consumir_email_pre` lê `driver._email_pre` (setado do `email_pre` que o backend
# manda = e-mail+senha do site) e guarda em `_gsmails_accounts` (p/ o
# atualizar_contato_site achar a senha). Se por acaso não houver e-mail pré-criado,
# cai no `create_email(domain=raiz do site)` (fallback que também nasce no apex).
USAR_EMAIL_DO_SITE = True


def _consumir_email_pre(driver, email_anterior=None):
    """Devolve (address, "__GSMAILS_API__") da conta que o PAINEL já criou para o
    site desta BM, ou None se não houver (ou se for igual à `email_anterior`).

    DESLIGADO por `USAR_EMAIL_DO_SITE=False` — ver o bloco acima.

    O e-mail próprio do subdomínio nasce junto com o site, no painel. O bot só o
    USA — não cria.

    NÃO zera o atributo (2026-07-31): o e-mail é do SITE, não da tentativa. Se a
    página cair e o formulário for repreenchido (F5 / 'Página incompleta'), a BM
    tem de voltar com o MESMO endereço. Zerando, a 2ª passada ficava sem e-mail
    próprio, chamava create_email() — recusado, porque o subdomínio já tem dono —
    e caía no público @gspromax.com. Era exatamente o bug observado.

    Para uma BM NOVA o endereço também é novo, porque cada site novo traz o seu e
    `driver._email_pre` é redefinido a cada executar_automacao_perfil(). Quando se
    pede explicitamente um e-mail DIFERENTE do anterior, o guard de `email_anterior`
    devolve None e o chamador segue para o caminho normal."""
    if not USAR_EMAIL_DO_SITE:
        return None
    conta = getattr(driver, '_email_pre', None)
    if not (conta and conta.get('address')):
        return None
    if email_anterior and conta['address'] == email_anterior:
        return None
    try:
        if not hasattr(driver, '_gsmails_accounts'):
            driver._gsmails_accounts = {}
        driver._gsmails_accounts[conta['address']] = conta
        driver._gsmails_last = conta
    except Exception:
        pass
    logger.info("Email PRÓPRIO do site (criado pelo painel): %s", conta['address'])
    return conta['address'], "__GSMAILS_API__"


# 📧 FORÇA E-MAIL NO APEX/RAIZ (Pro Max E-mail): quando ligada, ignora o toggle do
# painel e SEMPRE gera o e-mail no domínio RAIZ (razaosocial@raiz.com). Necessário
# porque a Central de Segurança, ao enviar a BM para análise por e-mail, RECUSA o
# subdomínio (apaga o campo e usa só o apex). O backend liga por-run no fluxo E-mail.
_FORCAR_EMAIL_RAIZ = False


def set_forcar_email_raiz(v):
    """Liga/desliga o modo 'e-mail sempre na raiz/apex' para as próximas execuções.
    O backend chama isto por-run quando o fluxo é o Pro Max E-mail."""
    global _FORCAR_EMAIL_RAIZ
    _FORCAR_EMAIL_RAIZ = bool(v)


def _resolver_modo_email():
    """Modo de geração de e-mail (painel → Configurações → Gerador de E-mails):
    'subdominio' (padrão) usa o subdomínio do site (isola cada BM); 'raiz' força o
    apex/público (comportamento antigo); 'ambos' sorteia por BM. Resolvido na hora
    (o 'ambos' sorteia aqui). Fallback seguro = 'subdominio'.

    ⚠️ O fluxo Pro Max E-mail liga `set_forcar_email_raiz(True)` e aí o modo é SEMPRE
    'raiz' (o Facebook recusa subdomínio no envio da análise por e-mail)."""
    if _FORCAR_EMAIL_RAIZ:
        return 'raiz'
    try:
        from server import acesso
        modo = acesso.email_modo_geracao()
    except Exception:
        modo = 'subdominio'
    if modo == 'ambos':
        import random
        modo = random.choice(['subdominio', 'raiz'])
    return modo if modo in ('subdominio', 'raiz') else 'subdominio'


def _site_root_apex(driver):
    """Raiz (domínio registrável) do site desta BM — p/ criar o e-mail no APEX dela.
    É o domínio que a Meta usa na verificação por e-mail (📧 Pro Max E-mail), o que
    vai no certificado e o que fica salvo. Ex.: 'fulano.kiboracore.social' ->
    'kiboracore.social'. Retorna None se não houver site (cai na raiz pública)."""
    h = (getattr(driver, "_site_host", None) or "")
    h = str(h).strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
    if not h or "." not in h:
        return None
    parts = [p for p in h.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else None


def obter_email_tmail(driver):
    """Abre TMail e obtém email temporário."""
    # E-MAIL PRÓPRIO DO SITE (2026-07-31): se o painel já criou a conta no domínio
    # do site, é ELA que a BM usa. Só cai no create_email/navegador se não houver.
    _modo_em = _resolver_modo_email()
    # 'raiz' força o e-mail no APEX: pula o e-mail PRÓPRIO do site (subdomínio).
    if _modo_em != 'raiz':
        _pre = _consumir_email_pre(driver)
        if _pre:
            return _pre
    # GSMAILS (API): gera e-mail+senha sem abrir aba. Se falhar, cai no navegador.
    try:
        from server.gsmails_integration import gsmails_enabled, create_email
        if gsmails_enabled():
            conta = create_email(label="BM", base_nome=getattr(driver, "_empresa_razao", None),
                                 host=(None if _modo_em == 'raiz' else getattr(driver, "_site_host", None)),
                                 domain=_site_root_apex(driver))
            if conta and conta.get("address"):
                try:
                    if not hasattr(driver, "_gsmails_accounts"):
                        driver._gsmails_accounts = {}
                    driver._gsmails_accounts[conta["address"]] = conta
                    driver._gsmails_last = conta
                except Exception:
                    pass
                logger.info("Email GSMAILS obtido: %s (senha salva no painel)", conta["address"])
                return conta["address"], "__GSMAILS_API__"
    except Exception as _e:
        logger.warning("[GSMAILS] obter_email_tmail — fallback p/ navegador: %s", _e)

    janela_original = _handle_atual(driver)
    aba_tmail = None
    try:
        aba_tmail = _abrir_ou_reutilizar_aba_tmail(driver)
        if not aba_tmail:
            logger.error("Não foi possível abrir/reutilizar a aba do TMail")
            return None, None

        driver.switch_to.window(aba_tmail)

        try:
            url_atual = (driver.current_url or '').lower()
        except Exception:
            url_atual = ''

        if 'tmail' not in url_atual:
            driver.get("https://tmailsocial.site/")
            _delay_pagina(2.0, 3.5)
        else:
            _delay_pagina(1.0, 2.0)

        _esperar_pagina_carregar(driver)
        email = _extrair_email_tmail(driver, timeout=25)

        if email:
            logger.info(f"Email TMail obtido: {email}")
        else:
            logger.error("Não foi possível obter email do TMail")

        return email, aba_tmail

    except Exception as e:
        logger.error(f"Erro ao obter email TMail: {e}")
        return None, None
    finally:
        if janela_original and aba_tmail and janela_original != aba_tmail:
            try:
                driver.switch_to.window(janela_original)
            except Exception:
                pass


def obter_email_tmail_com_retry(driver, max_tentativas=3, callback_status=None):
    """Obtém email do TMail com retentativas."""
    for t in range(1, max_tentativas + 1):
        if callback_status:
            callback_status(f"Obtendo email TMail (tentativa {t}/{max_tentativas})...")

        email, aba = obter_email_tmail(driver)
        if email:
            return email, aba

        if t < max_tentativas:
            try:
                if aba:
                    driver.switch_to.window(aba)
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
            except:
                try:
                    driver.switch_to.window(driver.window_handles[0])
                except:
                    pass
            _delay_pagina(2.0, 3.0)

    return None, None


# ============================================================================
# CRIAR BM NO BUSINESS MANAGER
# ============================================================================

# URL do FORMULÁRIO de criação de portfólio empresarial (Business Manager). Abrir
# ESTA URL direto garante a tela de criação em QUALQUER modelo de perfil (novo ou
# antigo, qualquer país), evitando o redirect p/ `/latest/home?nav_ref=bm_home_redirect`
# que alguns perfis sofrem ao abrir `business.facebook.com/` e que o sistema não trata.
URL_CRIAR_BM = ("https://business.facebook.com/business/loginpage/"
                "?login_options[0]=FB&login_options[1]=IG&login_options[2]=SSO"
                "&config_ref=biz_login_tool_flavor_mbs&create_business_portfolio_for_bm=1")


def _abrir_form_criar_novo_portfolio(driver, callback_status=None):
    """Força abrir o formulário de um NOVO portfólio empresarial quando o perfil
    JÁ TEM uma BM (o FB redireciona a URL de criação p/ a BM existente). Clica em
    'Criar um portfólio empresarial' — direto se visível, ou abrindo o seletor de
    portfólio (dropdown no topo) e clicando lá. Retorna True se abriu o form."""
    textos = ['criar um portfólio empresarial', 'criar portfólio empresarial',
              'criar um portfólio de negócios', 'criar portfólio de negócios',
              'create a business portfolio', 'create business portfolio',
              'create your business portfolio', 'criar novo portfólio']

    def _tenta_clicar():
        # FIX 2026-10-12: o execute_script do playwright_compat EMBRULHA o script
        # num corpo de função `(function(__args){ var arguments=__args; <script> })`.
        # Antes o script era uma arrow `(textos)=>{...}` que NUNCA era invocada →
        # retornava undefined e este helper NUNCA clicava (reprocesso forcar_novo
        # sempre caía no fallback). Agora é corpo de função comum com arguments[0].
        try:
            return bool(driver.execute_script(r"""
                var textos = arguments[0] || [];
                function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                  var s=getComputedStyle(el); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';}
                var els=document.querySelectorAll('div[role="button"],button,a[role="button"],a,span[role="button"],[role="menuitem"]');
                for(var i=0;i<els.length;i++){ if(!vis(els[i])) continue;
                  var t=(els[i].innerText||'').trim().toLowerCase();
                  for(var j=0;j<textos.length;j++){ if(t.indexOf(textos[j])!==-1){ els[i].click(); return true; } } }
                // Fallback ESTRUTURAL (idioma-agnóstico): link de criação de portfólio
                // pelo href (a URL não é traduzida).
                var hs=document.querySelectorAll('a[href*="create_business_portfolio"],a[href*="business/create"],a[href*="createbusiness"]');
                for(var h=0;h<hs.length;h++){ if(vis(hs[h])){ hs[h].click(); return true; } }
                return false;
            """, textos))
        except Exception:
            return False

    # 1) botão direto (às vezes visível na home)
    if _tenta_clicar():
        time.sleep(2.0)
        return True
    # 2) abre o seletor de portfólio (topo) e tenta de novo
    try:
        # (mesmo FIX: corpo de função comum — a arrow nunca era invocada)
        driver.execute_script(r"""
            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
              var s=getComputedStyle(el); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';}
            var cand=document.querySelectorAll('[aria-haspopup="menu"],[aria-haspopup="listbox"],[aria-haspopup="dialog"],[role="combobox"],[aria-label*="portf" i],[aria-label*="portfolio" i]');
            for(var i=0;i<cand.length;i++){ if(vis(cand[i])){ cand[i].click(); return true; } }
            return false;
        """)
        time.sleep(1.6)
    except Exception:
        pass
    if _tenta_clicar():
        time.sleep(2.0)
        return True
    if callback_status:
        callback_status("Não achei o botão 'Criar um portfólio empresarial'.")
    return False


def _bm_limite_negocios(driver):
    """True quando o formulário de criação mostra 'Unable to Create Account / Você
    atingiu o limite do número de negócios que pode criar no momento'. É o TETO de
    BMs do perfil (a Meta permite ~2 por perfil). NÃO é bloqueio de UMA BM: é limite
    de QUANTIDADE — não adianta re-submeter nem tentar com outra empresa (loop
    infinito gerando emails à toa). O chamador deve PARAR de criar. (2026-07-25)"""
    try:
        return bool(driver.execute_script(r"""
            var t = ((document.body && document.body.innerText) || '').toLowerCase();
            return (
                t.indexOf('atingiu o limite do número de negócios') !== -1 ||
                t.indexOf('atingiu o limite do numero de negocios') !== -1 ||
                t.indexOf('limite do número de negócios que pode criar') !== -1 ||
                t.indexOf('limite do numero de negocios que pode criar') !== -1 ||
                t.indexOf('reached the limit of the number of businesses') !== -1 ||
                t.indexOf("you've reached the limit of the number of businesses") !== -1 ||
                (t.indexOf('unable to create account') !== -1 &&
                 (t.indexOf('limit') !== -1 || t.indexOf('limite') !== -1))
            );
        """))
    except Exception:
        return False


def _estado_envio_bm(driver, inputs, btn_submit):
    """Lê o estado do formulário de criação da BM DEPOIS do clique em Enviar:
      'fora'    → os campos sumiram (avançou de tela);
      'por_vez' → "Um usuário pode criar apenas uma conta comercial por vez" (a Meta
                  ainda processa o PRIMEIRO envio — re-enviar só piora);
      'ocupado' → botão com spinner/aria-busy/desabilitado/sem texto (requisição em voo);
      'erro'    → aviso de erro no formulário (alert/"unable to create");
      'parado'  → form intacto, botão habilitado e sem spinner (o clique não pegou)."""
    try:
        return driver.execute_script(r"""
            var btn = arguments[0], ins = Array.prototype.slice.call(arguments, 1);
            var vivo = false;
            for (var i = 0; i < ins.length; i++) {
                var el = ins[i];
                if (el && el.isConnected) { var r = el.getBoundingClientRect(); if (r.width > 0 && r.height > 0) { vivo = true; break; } }
            }
            if (!vivo) return 'fora';
            var box = null;
            for (var k = 0; k < ins.length && !box; k++) {
                if (ins[k] && ins[k].isConnected) box = ins[k].closest('[role="dialog"], [aria-modal="true"], form');
            }
            var t = (((box || document.body).innerText) || '').toLowerCase();
            if (t.indexOf('uma conta comercial por vez') !== -1 || t.indexOf('one business account at a time') !== -1
                || t.indexOf('one business at a time') !== -1 || t.indexOf('una cuenta comercial a la vez') !== -1
                || t.indexOf('una cuenta comercial por vez') !== -1)
                return 'por_vez';
            if (btn && btn.isConnected) {
                var ocupado = btn.getAttribute('aria-busy') === 'true' || btn.getAttribute('aria-disabled') === 'true'
                    || btn.disabled === true
                    || !!btn.querySelector('[role="progressbar"], [aria-busy="true"], [data-visualcompletion="loading-state"]')
                    || !((btn.innerText || '').trim());   // spinner substitui o rótulo
                if (ocupado) return 'ocupado';
            }
            if ((box && box.querySelector('[role="alert"]')) || t.indexOf('unable to create') !== -1
                || t.indexOf('não foi possível criar') !== -1 || t.indexOf('nao foi possivel criar') !== -1)
                return 'erro';
            return 'parado';
        """, btn_submit, *inputs) or 'parado'
    except Exception:
        return 'parado'


def criar_bm_facebook(driver, nome_bm, nome_completo, email_bm, callback_status=None,
                      profile_id=None, forcar_novo=False):
    """
    Cria uma Business Manager no Facebook.
    Retorna: True (sucesso), "EXISTE" (já existe), "LIMITE" (perfil no teto de BMs),
    False (falha)

    forcar_novo=True (usado pelo REPROCESSO): mesmo que o perfil já tenha uma BM,
    NÃO retorna "EXISTE" — força abrir o formulário de um NOVO portfólio.
    """
    try:
        if callback_status:
            callback_status("Acessando Business Manager...")

        # DIRETO NO FORMULÁRIO DE CRIAÇÃO: acessar `business.facebook.com/` fazia
        # alguns perfis (certos países) serem REDIRECIONADOS para
        # `/latest/home?nav_ref=bm_home_redirect&asset_id=...` — uma tela que o
        # sistema NÃO reconhece e que era erroneamente lida como "BM já existe" (o
        # `latest/home` batia no filtro abaixo). Indo DIRETO na URL do formulário
        # de criação, QUALQUER modelo de perfil (novo ou antigo) abre exatamente a
        # tela de criação esperada. Existência de BM já é checada antes por
        # `verificar_bm_existe` (PASSO 5), então aqui o objetivo é sempre CRIAR.
        driver.get(URL_CRIAR_BM)
        # Fluxo rigoroso: só age quando a tela do formulário está 100% estática.
        _pagina_estatica_pronta(driver, timeout=25)

        # CAPTCHA-ANYWHERE: o FB pode exibir reCAPTCHA ao abrir o formulário de
        # criação — resolve antes de procurar os botões.
        if _tratar_captcha_se_preciso(driver, callback_status):
            _pagina_estatica_pronta(driver, timeout=20)

        # Verifica se houve bloqueio ao tentar acessar o Business Manager
        is_blocked, block_type, action_needed = BlockDetector.check_for_blocks(driver)
        if is_blocked:
            logger.error(f"[BM] Bloqueio detectado ao acessar Business Manager: {block_type}")
            if action_needed in ["abort_profile", "pause_profile", "cooldown_profile"]:
                BlockDetector.handle_block(block_type, action_needed, profile_id or "desconhecido", callback_status)
                return False

        url = driver.current_url.lower()

        # BM EXISTENTE de verdade só quando há um business_id CONCRETO — e NUNCA na
        # home de REDIRECT (bm_home_redirect), que o FB dá p/ perfis SEM Business
        # Manager (essa tela NÃO é "BM criada/existente" → tem que CRIAR). Antes o
        # 'latest/home' sozinho era lido como EXISTE e o fluxo sempre errava aqui.
        if 'business_id=' in url and 'bm_home_redirect' not in url \
                and 'create_business_portfolio_for_bm' not in url \
                and not _detectar_tela_sem_acesso(driver):
            if forcar_novo:
                # REPROCESSO: o perfil JÁ tem BM e o FB redirecionou p/ ela. Em vez
                # de reusar (o bug: ficava esperando e-mail na BM antiga), força
                # abrir o formulário de um NOVO portfólio empresarial.
                logger.info("[BM] forcar_novo: BM existente — abrindo criação de NOVO portfólio.")
                if callback_status:
                    callback_status("Perfil já tem BM — criando um NOVO portfólio...")
                if not _abrir_form_criar_novo_portfolio(driver, callback_status):
                    # fallback: reforça a URL de criação (às vezes abre o form)
                    driver.get(URL_CRIAR_BM)
                _pagina_estatica_pronta(driver, timeout=20)
                if _tratar_captcha_se_preciso(driver, callback_status):
                    _pagina_estatica_pronta(driver, timeout=20)
            else:
                logger.info("BM já existe!")
                return "EXISTE"

        # Se caiu na tela "sem acesso", reforça a navegação p/ a URL de criação.
        if _detectar_tela_sem_acesso(driver):
            logger.info("Tela sem acesso detectada, reforçando URL de criação...")
            driver.get(URL_CRIAR_BM)
            _delay_pagina(1.5, 2.5)
            _esperar_pagina_carregar(driver, timeout=8)

        if callback_status:
            callback_status("Procurando formulário de criação...")

        # Clicar em "Create Account" / "Get Started" se necessário
        btn_criar = driver.execute_script("""
            var createTexts = ['create account','criar conta','create a business portfolio',
                              'criar um portfólio de negócios','criar um portfólio empresarial',
                              'criar portfólio empresarial','get started','começar',
                              'create business portfolio','gumawa ng business portfolio',
                              'buat portofolio bisnis','magsimula','mulai','create your business portfolio'];
            var buttons = document.querySelectorAll('button, [role="button"], a[role="button"], a');
            for (var i = 0; i < buttons.length; i++) {
                var text = (buttons[i].innerText || '').trim().toLowerCase();
                var rect = buttons[i].getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                for (var j = 0; j < createTexts.length; j++) {
                    if (text.includes(createTexts[j])) return buttons[i];
                }
            }
            return null;
        """)

        if btn_criar:
            _clicar(driver, btn_criar)
            # Confirma a transição p/ o formulário (tela estática) antes de seguir.
            _pagina_estatica_pronta(driver, timeout=15)

        if callback_status:
            callback_status("Preenchendo formulário...")

        campo_empresa, campo_nome, campo_email = _localizar_campos_criacao_bm(driver)

        if not (campo_empresa and campo_nome and campo_email):
            # FIX 2026-10-12: o modal pode ainda estar montando (4G/perfil lento).
            # Espera ESTRUTURAL (dialog com 3 inputs visíveis — idioma-agnóstico)
            # antes de recarregar a URL; só re-localiza se o modal apareceu.
            if _aguardar_popup_criacao_bm(driver, timeout=10):
                campo_empresa, campo_nome, campo_email = _localizar_campos_criacao_bm(driver)

        if not (campo_empresa and campo_nome and campo_email):
            # Última tentativa na URL direta e fallback por ordem visual
            driver.get("https://business.facebook.com/business/loginpage/?login_options[0]=FB&login_options[1]=IG&login_options[2]=SSO&config_ref=biz_login_tool_flavor_mbs&create_business_portfolio_for_bm=1")
            _delay_pagina(1.5, 2.5)
            _esperar_pagina_carregar(driver, timeout=8)
            campo_empresa, campo_nome, campo_email = _localizar_campos_criacao_bm(driver)

        inputs = []
        for el in (campo_empresa, campo_nome, campo_email):
            if el:
                inputs.append(el)

        if not inputs:
            logger.error("Nenhum campo encontrado no formulário")
            return False

        nome_bm_final = _gerar_nome_bm_valido(nome_bm, nome_completo, email_bm)
        nome_completo_final = _gerar_nome_pessoa_valido(nome_completo)
        email_bm_final = (email_bm or '').strip()

        logger.info("Campos BM localizados: empresa=%s nome=%s email=%s", bool(campo_empresa), bool(campo_nome), bool(campo_email))
        logger.info("Valores BM: empresa='%s' nome='%s' email='%s'", nome_bm_final, nome_completo_final, email_bm_final)

        # ── Preencher campos usando _preencher_input_humano (Digitação Realista mas Rápida) ──
        ok_empresa = _preencher_input_humano(driver, campo_empresa, nome_bm_final, 'nome_empresa') if campo_empresa else False
        _delay(0.1, 0.3)
        ok_nome = _preencher_input_humano(driver, campo_nome, nome_completo_final, 'nome_completo') if campo_nome else False
        _delay(0.1, 0.3)
        ok_email = _preencher_input_humano(driver, campo_email, email_bm_final, 'email_comercial') if campo_email else False

        # ── Fallback simplificado ──
        if not ok_empresa and campo_empresa:
            ok_empresa = _preencher_input_forte(driver, campo_empresa, nome_bm_final, 'empresa_forte')
        if not ok_nome and campo_nome:
            ok_nome = _preencher_input_forte(driver, campo_nome, nome_completo_final, 'nome_forte')
        if not ok_email and campo_email:
            ok_email = _preencher_input_forte(driver, campo_email, email_bm_final, 'email_forte')

        # ── Fallback posicional se algum campo falhou ──
        if not (ok_empresa and ok_nome and ok_email):
            logger.warning("Preenchimento incompleto: empresa=%s nome=%s email=%s", ok_empresa, ok_nome, ok_email)
            try:
                todos_inputs = driver.execute_script("""
                    var inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="email"], input:not([type])'));
                    return inputs.filter(function(el){
                        var r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && !el.disabled && (el.type || '').toLowerCase() !== 'hidden';
                    }).sort(function(a, b) {
                        return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
                    });
                """) or []
                if len(todos_inputs) >= 1 and not ok_empresa:
                    ok_empresa = _preencher_input_forte(driver, todos_inputs[0], nome_bm_final, 'nome_empresa_fallback')
                if len(todos_inputs) >= 2 and not ok_nome:
                    ok_nome = _preencher_input_forte(driver, todos_inputs[1], nome_completo_final, 'nome_completo_fallback')
                if len(todos_inputs) >= 3 and not ok_email:
                    ok_email = _preencher_input_forte(driver, todos_inputs[2], email_bm_final, 'email_comercial_fallback')
            except Exception as exc:
                logger.warning("Fallback por ordem visual falhou: %s", exc)

        if not (ok_empresa and ok_nome and ok_email):
            logger.error("Falha ao preencher formulario BM: empresa=%s nome=%s email=%s", ok_empresa, ok_nome, ok_email)
            return False

        if callback_status:
            callback_status("Enviando formulário...")

        _delay(0.5, 0.8)

        # Clicar Submit
        btn_submit = driver.execute_script("""
            // 1. button[type=submit]
            var submit = document.querySelector('button[type="submit"]');
            if (submit) {
                var rect = submit.getBoundingClientRect();
                if (rect.width > 0 && !submit.disabled) return submit;
            }
            
            // 2. Botão por texto
            var submitTexts = ['submit','enviar','soumettre','einreichen','invia',
                              'kirim','gửi','isumite','ipadala','gönder'];
            var buttons = document.querySelectorAll('button, [role="button"]');
            for (var i = 0; i < buttons.length; i++) {
                var text = (buttons[i].innerText || '').trim().toLowerCase();
                var rect = buttons[i].getBoundingClientRect();
                if (rect.width === 0) continue;
                if (buttons[i].disabled) continue;
                for (var j = 0; j < submitTexts.length; j++) {
                    if (text === submitTexts[j]) return buttons[i];
                }
            }

            // 2b. (FIX 2026-10-12) ESCOPO do próprio formulário: o container
            //     (dialog/form) que contém os inputs marcados data-bm-campo. O botão
            //     do form atual é "Criar/Create/Tạo/Создать..." (não "Enviar") —
            //     casa texto EXATO multi-idioma SÓ dentro do container do form.
            var campoRef = document.querySelector('[data-bm-campo="email"]')
                        || document.querySelector('[data-bm-campo="empresa"]');
            var box = campoRef ? campoRef.closest('[role="dialog"], [aria-modal="true"], form') : null;
            function okBtn(b){
                var r = b.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return false;
                if (b.disabled || b.getAttribute('aria-disabled') === 'true') return false;
                return true;
            }
            if (box) {
                var createTexts = ['create','criar','crear','créer','erstellen','crea','creëren',
                                   'tạo','создать','buat','gumawa','oluştur','बनाएँ','बनाएं',
                                   'next','avançar','próximo','proximo','continue','continuar',
                                   'siguiente','lanjut','tiếp','далее','devam','susunod'];
                var bb = box.querySelectorAll('button, [role="button"]');
                for (var i = 0; i < bb.length; i++) {
                    if (!okBtn(bb[i])) continue;
                    var tb = (bb[i].innerText || '').trim().toLowerCase();
                    for (var j = 0; j < createTexts.length; j++) {
                        if (tb === createTexts[j]) return bb[i];
                    }
                }
            }

            // 3. Botão azul primário (inclui o azul ATUAL do FB rgb(8,102,255)).
            //    Preferência: dentro do container do form, se houver.
            function azulBtn(b){
                var bg = getComputedStyle(b).backgroundColor || '';
                return bg.includes('24, 119, 242') || bg.includes('0, 100, 224') || bg.includes('rgb(24')
                    || bg.includes('8, 102, 255') || bg.includes('11, 105, 255');
            }
            var escopos = box ? [box.querySelectorAll('button, [role="button"]'), buttons] : [buttons];
            for (var e = 0; e < escopos.length; e++) {
                var lista = escopos[e];
                var candidates = [];
                for (var i = 0; i < lista.length; i++) {
                    if (!okBtn(lista[i])) continue;
                    if (azulBtn(lista[i])) {
                        candidates.push({el: lista[i], y: lista[i].getBoundingClientRect().y});
                    }
                }
                if (candidates.length > 0) {
                    candidates.sort(function(a,b) { return b.y - a.y; });
                    return candidates[0].el;
                }
            }

            // 4. (FIX 2026-10-12) Último recurso estrutural: o ÚLTIMO botão com texto
            //    do container do form (rodapé: [Cancelar][Criar] → o primário é o último).
            if (box) {
                var CANCEL = ['cancel','cancelar','annuler','abbrechen','annulla','hủy','huỷ',
                              'отмена','отменить','batal','iptal','kanselahin','रद्द','voltar',
                              'back','atrás','close','fechar','cerrar','đóng','tutup','закрыть'];
                var bb2 = box.querySelectorAll('button, [role="button"]');
                for (var i = bb2.length - 1; i >= 0; i--) {
                    if (!okBtn(bb2[i])) continue;
                    var t2 = (bb2[i].innerText || '').trim();
                    var t2l = t2.toLowerCase();
                    var al2 = (bb2[i].getAttribute('aria-label') || '').toLowerCase();
                    var ehCancel = false;
                    for (var c = 0; c < CANCEL.length; c++) {
                        if (t2l.indexOf(CANCEL[c]) !== -1 || al2.indexOf(CANCEL[c]) !== -1) { ehCancel = true; break; }
                    }
                    if (ehCancel) continue;
                    if (t2 && t2.length <= 40) return bb2[i];
                }
            }
            return null;
        """)

        # business_id ANTES do envio (FIX 2026-10-12): no forcar_novo o form abre por
        # cima da BM ANTIGA (URL latest/home?business_id=ANTIGO) — sem isto a checagem
        # por URL abaixo dava "BM criada" na hora, com o id da BM velha.
        try:
            _bid_antes = extrair_business_id_da_url((driver.current_url or '').lower())
        except Exception:
            _bid_antes = None

        def _url_indica_bm_nova(_u):
            """URL pós-envio prova BM NOVA: home/business_home (regra antiga) ou
            qualquer URL com business_id= fora do formulário — e, se já havia um
            business_id antes do envio, ele tem que ser DIFERENTE."""
            _u = (_u or '').lower()
            _bid_now = extrair_business_id_da_url(_u)
            if _bid_antes and _bid_now == _bid_antes:
                return False
            if _bid_antes and not _bid_now:
                return False
            if 'business_home' in _u or 'latest/home' in _u:
                return True
            return bool(_bid_now) and 'create_business_portfolio_for_bm' not in _u \
                and 'loginpage' not in _u

        # ── ENVIO ÚNICO (anti-clique-duplo, 2026-10-13) ─────────────────────────────
        # Bug do dono: em 4G/perfil lento o botão fica girando (spinner) por >12s; o
        # laço antigo via "ainda no formulário" e RE-ENVIAVA até 3x → a Meta recebia
        # 2+ pedidos de criação e respondia "Unable to Create Account — Um usuário pode
        # criar apenas uma conta comercial por vez". Agora: UM clique e ESPERA lendo o
        # estado do form (ocupado/por_vez/erro/fora). Re-envio só se o form ficou
        # PARADO (botão habilitado, sem spinner, sem erro) por 15s seguidos — no
        # máximo 1 vez, e NUNCA depois de a Meta acusar "uma conta por vez".
        if btn_submit:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_submit)
                _delay(0.15, 0.35)
                btn_submit.click()
            except Exception as _ce:
                # O clique pode ter PEGADO e só a espera pós-clique falhou: confere o
                # estado ANTES de qualquer fallback (senão vira clique duplo).
                _delay(0.8, 1.2)
                if _estado_envio_bm(driver, inputs, btn_submit) == 'parado':
                    logger.info("[BM] clique nativo falhou (%s) — 1 clique JS de fallback.", _ce)
                    try:
                        driver.execute_script("arguments[0].click();", btn_submit)
                    except Exception:
                        pass
        elif inputs:
            inputs[-1].send_keys(Keys.RETURN)
        else:
            return False

        _t0_envio = time.time()
        _ult_ativo = time.time()
        _reenvios = 0
        _t_por_vez = None
        _ult_st = None
        while time.time() - _t0_envio < 90:
            # TETO de BMs do perfil? ("Você atingiu o limite do número de negócios") —
            # não adianta re-submeter nem tentar outra empresa. Sinaliza LIMITE.
            if _bm_limite_negocios(driver):
                logger.warning("[BM] LIMITE de negócios atingido — perfil no teto de BMs.")
                if callback_status:
                    callback_status("⛔ Limite de BMs do perfil atingido (Meta) — não dá p/ criar mais.")
                return "LIMITE"
            try:
                if _url_indica_bm_nova(driver.current_url):
                    break
            except Exception:
                pass
            _st = _estado_envio_bm(driver, inputs, btn_submit)
            if _st != _ult_st:
                logger.info("[BM] estado do envio: %s (%.0fs)", _st, time.time() - _t0_envio)
                _ult_st = _st
            if _st == 'fora':
                break                                   # avançou de tela
            if _st == 'por_vez':
                # A Meta AINDA processa o 1º pedido: jamais re-enviar. Espera o
                # resultado (URL/popup) e deixa a validação final decidir.
                if _t_por_vez is None:
                    _t_por_vez = time.time()
                    if callback_status:
                        callback_status("⏳ Meta processando a criação da BM — aguardando (sem reenviar)...")
                if time.time() - _t_por_vez > 30:
                    break
                time.sleep(1.0)
                continue
            if _st == 'erro':
                break                                   # nunca re-dispara em cima de erro
            if _st == 'ocupado':
                _ult_ativo = time.time()                # requisição em voo: só espera
                time.sleep(0.7)
                continue
            # 'parado': o clique não pegou? Só depois de 15s parado, 1 única vez.
            if _t_por_vez is None and _reenvios < 1 and time.time() - _ult_ativo >= 15:
                _reenvios += 1
                logger.info("[BM] form PARADO 15s após o envio (botão habilitado, sem spinner) — "
                            "1 reenvio único.")
                try:
                    driver.execute_script(
                        "var b=arguments[0]; if(b && b.isConnected && b.getBoundingClientRect().width>0"
                        " && !b.disabled && b.getAttribute('aria-disabled')!=='true'){b.click();}", btn_submit)
                except Exception:
                    pass
                _ult_ativo = time.time()
            elif _reenvios >= 1 and time.time() - _ult_ativo >= 20:
                break                                   # não pegou de novo: validação final decide
            time.sleep(0.7)
        _pagina_estatica_pronta(driver, timeout=10)

        if callback_status:
            callback_status("Aguardando confirmação...")

        # Aguardar popup Done/Concluir. Tempos AUMENTADOS (2026-07-31): em 4G/perfis
        # lentos o popup demorava a montar e o loop de 5 curtas terminava antes.
        _delay_pagina(5.0, 8.0)

        btn_done = None
        _POPUP_TENTATIVAS = 8
        for tentativa in range(_POPUP_TENTATIVAS):
            if callback_status:
                callback_status(f"Aguardando popup... ({tentativa+1}/{_POPUP_TENTATIVAS})")

            # O aviso "Meta took steps to protect your account" (/hacked-protection)
            # pode cobrir o popup de conclusão — o loop só caçava "Done/OK" e girava à
            # toa com o aviso na frente (relato do dono 2026-09-27). Dispensa ele
            # (Back to Facebook / X, idioma-agnóstico) e re-checa se a BM já concluiu.
            try:
                if fechar_aviso_conta_protegida(driver, callback_status):
                    _cur = (driver.current_url or '').lower()
                    if _url_indica_bm_nova(_cur):
                        if not _detectar_tela_sem_acesso(driver):
                            logger.info("BM criada (URL após dispensar /hacked-protection)")
                            return True
                    continue
            except Exception:
                pass

            btn_done = driver.execute_script("""
                var doneTexts = ['done','concluído','concluir','terminé','fertig','fatto','listo',
                                'готово','完成','bitti','تم','selesai','tapos na','tapos','xong',
                                'ok','got it','entendi',
                                // + idiomas (2026-10-12): TR/JA/KO/HI/TH/PL/NL/RO/VI/ID/ES/FR
                                'tamam','完了','완료','हो गया','เสร็จสิ้น','เสร็จ','gotowe','klaar',
                                'gata','hoàn tất','xong rồi','oke','hecho','terminado','terminer',
                                'pronto','concluido'];
                
                var dialogs = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
                for (var d = 0; d < dialogs.length; d++) {
                    var buttons = dialogs[d].querySelectorAll('button, [role="button"]');
                    for (var i = 0; i < buttons.length; i++) {
                        var text = (buttons[i].innerText || '').trim().toLowerCase();
                        var rect = buttons[i].getBoundingClientRect();
                        if (rect.width === 0) continue;
                        for (var j = 0; j < doneTexts.length; j++) {
                            if (text === doneTexts[j]) return buttons[i];
                        }
                    }
                }
                
                var allBtns = document.querySelectorAll('button, [role="button"]');
                for (var i = 0; i < allBtns.length; i++) {
                    var text = (allBtns[i].innerText || '').trim().toLowerCase();
                    var rect = allBtns[i].getBoundingClientRect();
                    if (rect.width === 0) continue;
                    for (var j = 0; j < doneTexts.length; j++) {
                        if (text === doneTexts[j]) return allBtns[i];
                    }
                }
                return null;
            """)

            if btn_done:
                break

            # Verificar se já mudou de página (URL/business_id — idioma-agnóstico;
            # no forcar_novo exige business_id DIFERENTE do da BM antiga)
            cur_url = driver.current_url.lower()
            if _url_indica_bm_nova(cur_url):
                if not _detectar_tela_sem_acesso(driver):
                    logger.info("BM criada (detectado via URL)")
                    return True

            _delay_pagina(3.5, 5.0)

        if btn_done:
            logger.info("Botão Done encontrado!")
            _clicar(driver, btn_done)
            _delay_pagina(2.0, 3.0)
            _esperar_pagina_carregar(driver, timeout=10)
            return True

        # Verificar via conteúdo
        page = driver.page_source.lower()
        if 'was created' in page or 'foi criado' in page or 'foi criada' in page:
            if not _detectar_tela_sem_acesso(driver):
                return True

        # Validação final
        bm_ok = verificar_bm_existe(driver)
        return bm_ok

    except Exception as e:
        logger.error(f"Erro ao criar BM: {e}")
        return False


# ============================================================================
# CONFIRMAR EMAIL DA BM NO TMAIL
# ============================================================================

def confirmar_email_bm(driver, email_tmail, callback_status=None):
    """Confirma o email da BM no TMail."""
    # GSMAILS (API): se este e-mail foi gerado pela API, confirma pelo LINK que
    # chega via API (a inbox do navegador não enxerga a caixa do GSMAILS).
    try:
        accts = getattr(driver, "_gsmails_accounts", None) or {}
        if email_tmail in accts:
            from server.gsmails_integration import wait_fb_link
            if callback_status:
                callback_status("Aguardando e-mail de confirmação (GSMAILS, máx 25s)...")
            # Best-effort, máx ~25s (2026-07-07 — o usuário reclamou de esperar ~5min):
            # o daemon do GSMAILS entrega o link em <10s quando está saudável (e o
            # wait já faz polling → retorna NA HORA em que chega). Se não vier em 25s,
            # NÃO reenvia nem trava — segue o fluxo (a confirmação por código ainda é
            # re-tentada 1x na verificação; e o fluxo alternativo destrava a Central).
            link = wait_fb_link(email_tmail, timeout=25)
            if link:
                try:
                    _ir_para_aba_facebook(driver)
                except Exception:
                    pass
                if callback_status:
                    callback_status("Link de confirmação recebido — confirmando...")
                driver.get(link)
                _delay_pagina(5.0, 7.0)
                _esperar_pagina_carregar(driver, timeout=12)
                if callback_status:
                    callback_status("Email confirmado (GSMAILS)!")
                return True
            logger.warning("[GSMAILS] e-mail de confirmação não chegou no tempo para %s", email_tmail)
            if callback_status:
                callback_status("Email de confirmação não recebido (GSMAILS).")
            return False
    except Exception as _e:
        logger.warning("[GSMAILS] confirmar_email_bm — erro: %s", _e)

    try:
        if callback_status:
            callback_status("Verificando email de confirmação...")

        janela_fb = _ir_para_aba_facebook(driver)
        aba_tmail = _abrir_ou_reutilizar_aba_tmail(driver)
        if not aba_tmail:
            logger.error("Não foi possível localizar a aba do TMail para confirmação")
            return False

        ok = _aguardar_email_confirmacao(driver, aba_tmail, email_tmail=email_tmail, callback_status=callback_status)

        if janela_fb:
            try:
                driver.switch_to.window(janela_fb)
            except Exception:
                pass

        return ok

    except Exception as e:
        logger.error(f"Erro ao confirmar email: {e}")
        return False


def _aguardar_email_confirmacao(driver, aba_tmail, email_tmail=None, timeout_min=2, callback_status=None):
    """Aguarda e confirma email no TMail, preservando a aba/inbox já aberto."""
    try:
        driver.switch_to.window(aba_tmail)
        _delay(0.2, 0.4)

        try:
            url_atual = (driver.current_url or '').lower()
        except Exception:
            url_atual = ''

        if 'tmail' not in url_atual:
            driver.get("https://tmailsocial.site/")
            _delay_pagina(1.5, 2.5)
        else:
            # TMail atualiza em tempo real — NÃO fazer refresh, apenas aguardar
            _delay_pagina(0.5, 1.0)

        email_base = email_tmail or getattr(driver, '_tmail_email', None)
        if email_base:
            logger.info(f"Aguardando confirmação no TMail do email {email_base}")

        email_encontrado = False
        tempo_limite = time.time() + (timeout_min * 60)

        while time.time() < tempo_limite:
            if callback_status:
                restante = int(tempo_limite - time.time())
                callback_status(f"Aguardando email... ({restante}s)")

            email_el = driver.execute_script("""
                var keywords = ['facebook', 'meta', 'confirme', 'confirm', 'business', 'verify', 'portfolio'];
                var selectors = ['tr', 'li', '[role=\"row\"]', '.mail-item', '.message-item', '.inbox-item', 'a', 'div'];
                for (var s = 0; s < selectors.length; s++) {
                    var elements = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < elements.length; i++) {
                        var el = elements[i];
                        var rect = el.getBoundingClientRect();
                        if (rect.width < 40 || rect.height < 10) continue;
                        var text = (el.textContent || '').toLowerCase();
                        if (!text || text.length > 600) continue;
                        for (var j = 0; j < keywords.length; j++) {
                            if (text.includes(keywords[j])) return el;
                        }
                    }
                }
                return null;
            """)

            if email_el:
                logger.info("Email do Facebook detectado no TMail")
                try:
                    _clicar(driver, email_el)
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", email_el)
                    except Exception:
                        pass
                _delay_pagina(2.0, 3.0)

                aberto = False
                try:
                    aberto = bool(driver.execute_script("""
                        var body = (document.body && document.body.innerText || '').toLowerCase();
                        return body.includes('confirm') || body.includes('confirme') ||
                               body.includes('verify') || body.includes('verification') ||
                               body.includes('agora') || body.includes('portfolio');
                    """))
                except Exception:
                    aberto = False

                if aberto:
                    email_encontrado = True
                    break

            # TMail atualiza em tempo real — NÃO fazer refresh no loop.
            # Apenas aguardar: driver.refresh() reseta o carregamento
            # e impede que o email apareça.
            _delay_pagina(4.0, 6.0)

        if not email_encontrado:
            if callback_status:
                callback_status("Email não recebido no tempo limite")
            return False

        if callback_status:
            callback_status("Email aberto! Procurando confirmação...")

        _delay_pagina(1.5, 2.5)

        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        iframes = driver.find_elements(By.TAG_NAME, 'iframe')
        btn, link = _procurar_confirmacao(driver)

        if not btn and not link:
            for iframe in iframes:
                try:
                    driver.switch_to.frame(iframe)
                    _delay(0.2, 0.4)
                    btn, link = _procurar_confirmacao(driver)
                    if btn or link:
                        break
                except Exception:
                    pass
                finally:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass

        if link:
            if callback_status:
                callback_status("Link de confirmação encontrado!")
            driver.get(link)
            _delay_pagina(5.0, 7.0)
            _esperar_pagina_carregar(driver, timeout=12)
            if callback_status:
                callback_status("Email confirmado!")
            return True

        if btn:
            if callback_status:
                callback_status("Botão de confirmação encontrado!")
            _clicar(driver, btn)
            _delay_pagina(5.0, 7.0)
            if callback_status:
                callback_status("Email confirmado!")
            return True

        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        links = driver.find_elements(By.TAG_NAME, 'a')
        for l in links:
            try:
                href = l.get_attribute('href') or ''
                if 'business.facebook.com' in href or 'confirm' in href.lower() or 'verify' in href.lower():
                    driver.get(href)
                    _delay_pagina(5.0, 7.0)
                    if callback_status:
                        callback_status("Email confirmado via link!")
                    return True
            except Exception:
                continue

        if callback_status:
            callback_status("Botão de confirmação não encontrado")
        return False

    except Exception as e:
        logger.error(f"Erro ao confirmar email: {e}")
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False


def _procurar_confirmacao(driver):
    """Procura botão/link de confirmação no email."""
    resultado = driver.execute_script("""
        var textos = ['Confirmar agora','Confirm Now','Confirm now','Confirm Email',
                     'Verificar agora','Verify Now','Verify now','Verify Email',
                     'Confirmer maintenant','Jetzt bestätigen','Conferma ora',
                     'Confirmar ahora','Kumpirmahin ngayon','Konfirmasi sekarang','Xác nhận ngay'];
        
        var links = document.querySelectorAll('a');
        for (var i = 0; i < links.length; i++) {
            var text = links[i].textContent.trim();
            var href = links[i].getAttribute('href') || '';
            for (var j = 0; j < textos.length; j++) {
                if (text === textos[j] || text.toLowerCase() === textos[j].toLowerCase()) {
                    return {type:'link', href:href};
                }
            }
            if (href.includes('business.facebook.com') && (href.includes('confirm') || href.includes('verify'))) {
                return {type:'link', href:href};
            }
        }
        
        var buttons = document.querySelectorAll('button, [role="button"], input[type="button"]');
        for (var i = 0; i < buttons.length; i++) {
            var text = buttons[i].textContent.trim();
            for (var j = 0; j < textos.length; j++) {
                if (text === textos[j]) return {type:'button', element:buttons[i]};
            }
        }
        return null;
    """)

    if resultado:
        if resultado.get('type') == 'link' and resultado.get('href'):
            return None, resultado['href']
        elif resultado.get('element'):
            return resultado['element'], None
    return None, None


# ============================================================================
# VALIDAÇÃO PÓS-CRIAÇÃO DE BM
# ============================================================================

def verificar_bm_existe(driver, callback_status=None):
    """Verifica se a BM realmente existe."""
    try:
        driver.get("https://business.facebook.com/")
        _delay_pagina(2.5, 4.0)
        _esperar_pagina_carregar(driver, timeout=10)

        if _detectar_tela_sem_acesso(driver):
            return False

        url = driver.current_url.lower()
        page = driver.page_source.lower()

        # BM REALMENTE existente: a URL tem um business_id CONCRETO. Checa PRIMEIRO
        # (mesmo que a URL também tenha bm_home_redirect, se há business_id é uma BM
        # de verdade).
        if 'business_id=' in url:
            return True

        # O FB REDIRECIONA perfis SEM Business Manager para a home
        # (latest/home?nav_ref=bm_home_redirect&asset_id=...) — é o Meta Business
        # Suite de uma PÁGINA, SEM portfólio empresarial. NÃO é uma BM existente:
        # antes a navegação/sidebar dessa tela era lida como "BM existe" (pelo
        # 'latest/home' in url), o fluxo PULAVA a criação e SEMPRE dava erro. Aqui
        # retornamos False → o fluxo vai CRIAR a BM (criar_bm_facebook abre direto o
        # formulário via URL_CRIAR_BM). 'latest/home'/'business_home' SEM business_id
        # também NÃO provam BM.
        if 'bm_home_redirect' in url or 'latest/home' in url or 'business_home' in url:
            logger.info("[BM] Home/redirect SEM business_id — perfil sem Business Manager, vamos CRIAR.")
            return False

        indicadores = ['business home', 'página inicial do negócio', 'business settings',
                      'configurações do negócio', 'ad account', 'conta de anúncios',
                      'business portfolio', 'portfólio de negócios']

        # Indicadores negativos
        negativos = ["can't access", "cannot access", "não é possível acessar",
                    "hindi ma-access", "walang access", "you don't have access"]

        for neg in negativos:
            if neg in page:
                return False

        for ind in indicadores:
            if ind in page:
                return True

        # Verificar via JS
        return driver.execute_script("""
            var body = (document.body.innerText || '').toLowerCase();
            var negativos = ["can't access","walang access","you don't have access",
                           "não é possível acessar","gumawa ng facebook page","create a facebook page"];
            for (var i = 0; i < negativos.length; i++) {
                if (body.includes(negativos[i])) return false;
            }
            var url = window.location.href;
            if (url.includes('business.facebook.com') && !url.includes('loginpage')) {
                var nav = document.querySelector('[role="navigation"]');
                if (nav) return true;
                var sidebar = document.querySelector('[data-pagelet="BizNavSidebar"], [data-pagelet="LeftRail"]');
                if (sidebar) return true;
            }
            return false;
        """) or False

    except Exception as e:
        logger.error(f"Erro ao validar BM: {e}")
        return False


# ============================================================================
# UTILITÁRIOS DE EXTRAÇÃO
# ============================================================================

def extrair_business_id_da_url(url):
    """Extrai o business_id da URL do Facebook Business Manager."""
    match = re.search(r'business_id=(\d+)', url)
    if match:
        return match.group(1)
    return None

# ============================================================================
# FLUXO PRINCIPAL - MULTI-BM
# ============================================================================

def _extrair_debug_address(res_abrir):
    """Extrai (debugging_address, webdriver_path, ws) do retorno de
    abrir_navegador_func — cobre os formatos do IXBrowser e do AdsPower."""
    if not res_abrir:
        return '', '', ''
    debugging_address = res_abrir.get('debugging_address', '')
    webdriver_path = res_abrir.get('webdriver', '')
    ws = res_abrir.get('ws', '')
    # Fallback: se não veio no nível superior, tentar no sub-dict 'data'
    if not debugging_address:
        dados_raw = res_abrir.get('data', {})
        if isinstance(dados_raw, dict):
            debugging_address = dados_raw.get('debugging_address', '')
            if not webdriver_path:
                webdriver_path = dados_raw.get('webdriver', '')
            if not ws:
                ws_raw = dados_raw.get('ws', '')
                if isinstance(ws_raw, dict):
                    ws = ws_raw.get('puppeteer', '') or ws_raw.get('selenium', '') or ''
                elif isinstance(ws_raw, str):
                    ws = ws_raw
    # Extrair debugging_address do ws URL se necessário
    if not debugging_address and ws and isinstance(ws, str):
        match = re.search(r'ws://([^/]+)', ws)
        if match:
            debugging_address = match.group(1)
    return debugging_address, webdriver_path, ws


def _na_tela_de_login(driver):
    """Detecção RÁPIDA de cookie morto: True se a página atual é a tela de login
    do Facebook (URL com /login e formulário de email/senha visível)."""
    try:
        url = (driver.current_url or '').lower()
    except Exception:
        url = ''
    # Em checkpoint/2FA NÃO é a tela de login simples — deixa o fluxo seguir.
    if any(m in url for m in ('checkpoint', 'two_step', 'two_factor')):
        return False
    try:
        form = driver.find_elements(By.CSS_SELECTOR, '#email, input[name="email"], #pass, input[name="pass"]')
        form_visivel = any(el.is_displayed() for el in form) if form else False
    except Exception:
        form_visivel = False
    return form_visivel and ('login' in url or 'facebook.com' in url)


def _recuperar_nome_bm_apos_bloqueio(driver, bloqueadas_ids, good_bid, nome_real,
                                     callback_status=None):
    """Após uma BM BOA nascer (com nome FAKE) tendo havido BM(s) bloqueada(s):
    (1) renomeia CADA BM bloqueada para um nome fake aleatório — LIBERANDO o nome
    real que ela segurava; (2) dá o NOME REAL (razão social) à BM boa, no NOME DO
    PORTFÓLIO. Os DETALHES da empresa (razão social/endereço/CNPJ) NÃO são
    tocados aqui: a verificação preenche depois de verificar o domínio (ordem
    anti-restrição). Best-effort — só loga se algo falhar."""
    from server.verificacao_bm import _atualizar_nome_portfolio
    try:
        from server.verificacao_bm import _fechar_overlays_facebook
    except Exception:
        _fechar_overlays_facebook = None

    def _abrir_info(bid):
        driver.get(f"https://business.facebook.com/latest/settings/business_info?business_id={bid}")
        _delay_pagina(2.5, 4.0)
        try:
            _esperar_pagina_carregar(driver, timeout=12)
        except Exception:
            pass
        # Fecha coachmarks/tooltips ("Alternar entre perfis"/"Edite ferramentas")
        # que podem cobrir o botão Editar logo após entrar na BM.
        try:
            if _fechar_overlays_facebook:
                _fechar_overlays_facebook(driver)
        except Exception:
            pass

    # 1) LIBERA o nome real: renomeia a(s) bloqueada(s) p/ fake.
    for _bid in (bloqueadas_ids or []):
        if not _bid or _bid == good_bid:
            continue
        try:
            _n, _s, _fake = gerar_nome_brasileiro()
            if callback_status:
                callback_status(f"🔄 Liberando nome — renomeando BM bloqueada p/ '{_fake}'...")
            _abrir_info(_bid)
            _atualizar_nome_portfolio(driver, _fake, callback_status)
            _delay_medio()
        except Exception as e:
            logger.warning("[BM] falha ao renomear BM bloqueada %s: %s", _bid, e)

    # 2) Dá o NOME REAL à BM boa (nome do portfólio).
    if good_bid:
        try:
            if callback_status:
                callback_status(f"🏷️ Definindo nome real na BM boa: {str(nome_real)[:40]}")
            _abrir_info(good_bid)
            _atualizar_nome_portfolio(driver, nome_real, callback_status)
            _delay_medio()
        except Exception as e:
            logger.warning("[BM] falha ao dar nome real à BM boa %s: %s", good_bid, e)
    return True


def executar_automacao_perfil(profile_id, perfil_data, abrir_navegador_func, fechar_navegador_func,
                              adicionar_tags_func, callback_status=None, qtd_bm=1, captcha_api_key='',
                              skip_close=False, nome_bm_override='', seu_nome_override='',
                              parar_no_primeiro_sucesso=False, anexar_notas_func=None,
                              gate_criacao=None, forcar_criar_bm=False,
                              site_host='', empresa_razao='', email_pre=None):
    """
    Executa o fluxo completo de automação para um perfil (v9 TURBO):
    1. Abre navegador via IXBrowser
    2. Conecta Selenium
    3. Verifica login / Faz login
    4. Altera idioma para pt-BR (seletores fixos + Gemini fallback)
    5. Loop de criação de BMs (1 a 5 conforme configurado)
    6. Para cada BM: obtém email TMail, cria BM, confirma email
    7. Fecha navegador e adiciona tags
    
    Args:
        qtd_bm: Quantidade de BMs a criar (1 a 5, padrão 1)
        captcha_api_key: API key do CapSolver para resolver captchas (opcional)
        site_host: host do SITE da empresa já criada (ex.: 'razaosocial.raiz.com').
            Quando informado, o e-mail da BM nasce NO DOMÍNIO DO PRÓPRIO SITE
            (driver._site_host → gsmails_integration.create_email(host=...)).
            Vazio = e-mail no domínio público (gspromax.com), como sempre.
        empresa_razao: razão social da empresa, usada como base do local-part
            "corporativo" do e-mail quando o host não se aplica.
        email_pre: conta de e-mail JÁ CRIADA para este site, no formato
            {'address':…, 'password':…}. O PAINEL cria o e-mail próprio do
            subdomínio junto com o site, então o bot NÃO cria outro — apenas usa
            este. (A blindagem do gsmails só permite o 1º e-mail de cada
            subdomínio, e quem o criou foi o painel; tentar criar um 2º devolvia
            'subdominio_de_outro_usuario' e caía no público @gspromax.com.)
    """
    driver = None
    resultado = {
        "logado": False, "bm_criada": False, "bms_criadas": 0,
        "mensagem": "", "email_tmail": "", "email_confirmado": False
    }

    def _salvar_email_bm_nas_notas(email, confirmado):
        """Salva e-mail + senha da BM validada na observação/notas do multilogin
        (junto com os dados do perfil). Só para e-mails GSMAILS (que têm senha)
        e quando o e-mail foi confirmado. Best-effort, nunca quebra o fluxo."""
        try:
            if not confirmado or not email or not anexar_notas_func:
                return
            acc = (getattr(driver, '_gsmails_accounts', None) or {}).get(email)
            senha = acc.get('password', '') if acc else ''
            if not senha:
                return  # e-mail do navegador antigo (sem senha) — nada a salvar
            resultado['email_tmail'] = email
            resultado['email_senha'] = senha
            # Inclui o SITE/PROVEDOR do e-mail (onde o usuário loga com as
            # credenciais acima) — senão ele não sabe onde acessar a conta depois.
            linhas = [f"📧 Email BM: {email}", f"🔐 Senha Email BM: {senha}",
                      f"🌐 Acessar e-mail: {_URL_MAIL_DA_MARCA}/"]
            ok = anexar_notas_func(profile_id, linhas)
            logger.info("[GSMAILS] Email/senha da BM %s nas notas do perfil (%s).",
                        'salvos' if ok else 'NÃO salvos', email)
            if callback_status and ok:
                callback_status("Email/senha da BM salvos na observação do perfil.")
        except Exception as _e:
            logger.warning("[GSMAILS] Falha ao salvar email da BM nas notas: %s", _e)

    qtd_bm = max(1, min(5, int(qtd_bm)))  # Garantir entre 1 e 5

    # Captcha solver (CapSolver)
    if captcha_api_key:
        logger.info("[Captcha] API key CapSolver configurada — captcha será resolvido automaticamente se detectado")
    else:
        logger.info("[Captcha] Sem API key — se captcha for detectado, perfil será abortado")

    try:
        # ===== PASSO 1: Abrir navegador =====
        if callback_status:
            callback_status("Abrindo navegador...")

        res_abrir = abrir_navegador_func(profile_id)

        if not res_abrir or not res_abrir.get('sucesso'):
            # (res_abrir pode vir None → .get quebrava com AttributeError)
            resultado['mensagem'] = f"Falha ao abrir navegador: {(res_abrir or {}).get('mensagem', 'Erro')}"
            return resultado

        # Extrair dados de conexão do resultado (cobre IXBrowser e AdsPower)
        debugging_address, webdriver_path, ws = _extrair_debug_address(res_abrir)

        if not debugging_address:
            resultado['mensagem'] = "Endereço de debug não encontrado"
            return resultado

        if callback_status:
            callback_status(f"Conectando Playwright ({debugging_address})...")

        _delay_pagina(1.5, 2.5)

        # ===== PASSO 2: Conectar Playwright =====
        driver = conectar_selenium(debugging_address, webdriver_path)
        if not driver:
            resultado['mensagem'] = "Falha ao conectar Playwright"
            return resultado

        # Credenciais do E-MAIL no driver — usadas se o FB pedir CÓDIGO POR E-MAIL
        # (confirmemail.php) em QUALQUER caminho de login (cookie/credenciais) e no
        # re-login durante a verificação. (O login por cookie não passava por
        # fazer_login_facebook, então sem isto os handlers ficavam sem o e-mail.)
        try:
            driver._pm_fb_email = perfil_data.get('email', '') or ''
            driver._pm_fb_email_senha = perfil_data.get('senha_email', '') or ''
            # Token do CapSolver no driver → captcha-anywhere (resolve reCAPTCHA em
            # QUALQUER tela do fluxo, não só na Central de Segurança).
            driver._pm_captcha_token = captcha_api_key or ''
            # SITE da empresa (2026-07-31): o e-mail da BM nasce no domínio do
            # PRÓPRIO site (contato@razaosocial.raiz.com) em vez do gspromax.com.
            # Lido por obter_email_tmail/_obter_novo_email_tmail via getattr.
            # Host inapto (raiz sem MX etc.) → create_email cai no público sozinho.
            driver._site_host = site_host or ''
            # Razão social: base do local-part corporativo quando não há host.
            # (Antes NUNCA era definida — o gerador sempre caía no nome BR aleatório.)
            driver._empresa_razao = empresa_razao or ''
            # Conta de e-mail JÁ criada pelo painel para este site — consumida por
            # obter_email_tmail() em vez de chamar create_email().
            driver._email_pre = (dict(email_pre)
                                 if (email_pre and email_pre.get('address')) else None)
        except Exception:
            pass

        # ===== PASSO 2.5: PRÉ-LOGIN DO E-MAIL (Outlook/Hotmail) =====
        # Perfis SEM 2FA costumam exigir CÓDIGO POR E-MAIL para validar o acesso já
        # no login. Logamos a caixa numa ABA ao lado ANTES do fluxo do FB, para o
        # código ser lido em QUALQUER momento (login/verificação). Só para provedores
        # que exigem navegador (hotmail/outlook/live) — gsmails continua pela API.
        # Não-fatal: se não logar agora, tentamos de novo quando o FB pedir o código.
        try:
            from server import outlook_login
            _mail = perfil_data.get('email', '') or ''
            _mail_pw = perfil_data.get('senha_email', '') or ''
            if _EMAIL_LOGIN_OUTLOOK_ATIVO and _mail and _mail_pw and outlook_login.eh_email_outlook(_mail):
                if callback_status:
                    callback_status("Logando no e-mail (Outlook/Hotmail) em aba ao lado...")
                if outlook_login.abrir_e_logar(driver, _mail, _mail_pw, callback_status):
                    if callback_status:
                        callback_status("Caixa de e-mail acessível — pronta para receber códigos.")
                else:
                    if callback_status:
                        callback_status("Aviso: e-mail não logou agora (tento ler o código quando o FB pedir).")
        except Exception as _em:
            logger.warning("[Email] Pré-login do e-mail falhou (não fatal): %s", _em)

        # ===== PASSO 3: Verificar login / Navegar para Facebook =====
        if callback_status:
            callback_status("Acessando Facebook...")

        # Navegar primeiro para a página de login para garantir que os popups apareçam
        driver.get("https://www.facebook.com/login/")
        _delay_pagina(2.0, 3.5)
        _esperar_pagina_carregar(driver, timeout=10)

        tem_cookies = bool(perfil_data.get('cookie_raw', ''))
        logado = False

        # ── JÁ LOGADO? (ex.: REPROCESSO de um perfil ativo do AdsPower) ──
        # Se a sessão do navegador já está autenticada, NÃO tentamos logar de
        # novo. Sem esta checagem, um perfil SEM cookie_raw e SEM credenciais
        # (exatamente o caso do reprocesso) caía direto no login por credenciais
        # VAZIAS e falhava com "não foi possível logar" — mesmo já estando logado.
        try:
            if verificar_login_facebook(driver, timeout=8, callback_status=callback_status):
                logado = True
                if callback_status:
                    callback_status("Sessão já autenticada — pulando login.")
                logger.info("[Login] Sessão já logada detectada — login ignorado.")
        except Exception as _vl:
            logger.debug("[Login] verificar_login inicial falhou: %s", _vl)

        # ===== LOGIN =====
        # IMPORTANTE: NÃO tentamos "detectar/clicar" a bolha nativa
        # "Fazer login como ..." — ela é desenhada pelo Chrome FORA do DOM e não
        # existe no código-fonte da página. Ela é fechada com ESC REAL dentro do
        # fluxo de login (_dispensar_popup_navegador_login). Aqui apenas tentamos
        # entrar pelo cookie e, se ele estiver expirado, caímos no login por
        # credenciais (usuário + senha + Entrar).
        if not logado:
            if tem_cookies:
                if callback_status:
                    callback_status("Injetando cookies e verificando sessão...")

                # 1) Reinjeta os cookies direto no contexto (garante que estão
                #    aplicados, mesmo se a importação nativa do multilogin falhou).
                _injetar_cookies_login(driver, perfil_data, callback_status)

                # 2) Navega para a home com os cookies aplicados.
                try:
                    driver.get("https://www.facebook.com/")
                except Exception:
                    pass
                _delay_pagina(2.0, 3.0)

                # 3) Detecção RÁPIDA: se o cookie está morto, o Facebook cai
                #    direto na tela de login — identificamos na hora e já vamos
                #    pro login por credenciais, sem ficar esperando. Se NÃO está
                #    na tela de login, damos uma janela curta pro FB passar por
                #    eventuais checkpoints (Trust device / Dismiss) com cookie bom.
                # Detecção ultra-rápida de cookie expirado (sem esperar 18s)
                # Verifica na hora se caiu na tela de login
                
                # Aguarda página estática para ter certeza
                from server.page_state_manager import PageStateManager
                PageStateManager.wait_for_page_load(driver, timeout=5)
                
                tela_atual, _ = PageStateManager.identify_current_screen(driver)
                
                # Falha definitiva por confirmemail (código por e-mail) — quando True,
                # NÃO re-tenta login por usuário/senha (o navegador é fechado como erro).
                email_confirm_falhou = False
                if tela_atual == "login_form" or tela_atual == "login_popup" or "login" in driver.current_url.lower():
                    logger.info("[Login] Cookie expirado detectado imediatamente. Indo para login com credenciais.")
                    logado = False
                else:
                    # Se não for tela de login, tenta fluxo linear para lidar com 2FA/Checkpoint se necessário
                    # Se já for home, o loop resolve na primeira passada
                    logado = True
                    _home_confirmada = False  # FIX 2026-10-12: ver pós-loop
                    for _ in range(6):
                        PageStateManager.wait_for_page_load(driver, timeout=5)
                        tela, _ = PageStateManager.identify_current_screen(driver)
                        if tela == "home":
                            logado = True
                            _home_confirmada = True
                            break
                        elif tela == "checkpoint_severe":
                            # Conta travada/bloqueio real: NÃO é sessão boa. Antes caía
                            # no else (sleep) e, esgotado o loop, saía logado=True →
                            # o fluxo seguia p/ a BM numa conta bloqueada.
                            logger.warning("[Login] checkpoint_severe no login por cookie.")
                            logado = False
                            break
                        elif tela == "cookie_consent":
                            _tratar_dialogo_permitir_cookies(driver, callback_status)
                        elif tela == "privacy_consent":
                            _tratar_consentimento_privacidade(driver, callback_status)
                        elif tela == "email_code":
                            # FB pediu CÓDIGO DE CONFIRMAÇÃO por e-mail (confirmemail.php)
                            # no login por cookie. Lê o código na caixa Outlook/Hotmail
                            # (aba ao lado) e digita; se resolver, reavalia a próxima
                            # tela (home/trust_device); senão marca FALHA.
                            logger.info("[Login] Código por e-mail (confirmemail) no login por cookie — resolvendo via caixa.")
                            if _resolver_codigo_email_confirmemail(driver, callback_status):
                                continue
                            logger.warning("[Login] Código por e-mail não resolvido — marcando como FALHA.")
                            if callback_status:
                                callback_status("Código por e-mail não resolvido — perfil marcado como erro.")
                            logado = False
                            email_confirm_falhou = True
                            break
                        elif tela == "checkpoint_dismiss":
                            _tratar_aviso_comportamento_automatizado(driver, callback_status)
                        elif tela == "captcha":
                            # reCAPTCHA no login por COOKIE — resolve via CapSolver
                            # (antes este loop não tratava captcha e abortava o perfil).
                            if callback_status:
                                callback_status("reCAPTCHA detectado no login — resolvendo via CapSolver...")
                            _resolver_captcha_login(driver, callback_status)
                            time.sleep(1.5)
                        elif tela == "2fa_screen":
                            # Mesma URL do reCAPTCHA: sem campo de código visível,
                            # é captcha (widget ainda montando) — resolve antes de
                            # tentar digitar o TOTP.
                            if not _tem_campo_codigo_2fa(driver):
                                if _resolver_captcha_login(driver, callback_status) != 'no_captcha':
                                    time.sleep(1.5)
                                    continue
                            logado = _tratar_2fa(driver, perfil_data.get('tfa', ''), callback_status)
                            if not logado: break
                        elif tela == "trust_device":
                            _tratar_confiar_dispositivo(driver, callback_status)
                        elif tela == "login_form" or tela == "login_popup":
                            logado = False
                            break
                        else:
                            time.sleep(2)

                    # FIX 2026-10-12: esgotou as 6 passadas SEM ver a home (telas
                    # 'unknown'/'error'/auth_platform/2FA recém-aceito...) → antes saía
                    # logado=True às cegas. Confirma a sessão de forma ESTRUTURAL
                    # (feed/nav/Reels — idioma-agnóstico); se não confirmar, cai no
                    # login por credenciais (que trata todas as telas intermediárias).
                    if logado and not _home_confirmada:
                        try:
                            logado = bool(verificar_login_facebook(
                                driver, timeout=8, callback_status=callback_status))
                        except Exception as _vc:
                            logger.debug("[Login] confirmação pós-cookie falhou: %s", _vc)
                            logado = False
                        if not logado:
                            logger.info("[Login] Sessão por cookie NÃO confirmada — indo p/ credenciais.")

                if not logado and not email_confirm_falhou:
                    # Cookie inválido/expirado: logar JÁ com usuário/senha + 2FA,
                    # na MESMA sessão (sem reabrir navegador) — rápido e direto.
                    # (Se caiu por confirmemail, NÃO re-tenta: já é falha definitiva.)
                    if callback_status:
                        callback_status("Cookie inválido — logando com usuário/senha + 2FA...")
                    logado = fazer_login_facebook(driver, perfil_data.get('login', ''),
                        perfil_data.get('senha', ''), perfil_data.get('tfa', ''), callback_status,
                        email=perfil_data.get('email', ''),
                        senha_email=perfil_data.get('senha_email', ''))
            else:
                if callback_status:
                    callback_status("Fazendo login...")
                logado = fazer_login_facebook(driver, perfil_data.get('login', ''),
                    perfil_data.get('senha', ''), perfil_data.get('tfa', ''), callback_status,
                    email=perfil_data.get('email', ''),
                    senha_email=perfil_data.get('senha_email', ''))

        resultado['logado'] = logado

        if not logado:
            resultado['mensagem'] = "Não foi possível logar no Facebook"
            try:
                driver.quit()
            except:
                pass
            fechar_navegador_func(profile_id)
            return resultado

        # 🔐 GUARDIÃO DE SESSÃO (Onda 2): guarda as credenciais no driver para RE-LOGAR em
        # QUALQUER etapa a jusante (criação de BM / OAuth da WABA / verificação) se a Meta
        # deslogar o perfil no meio do fluxo — antes só a Central sabia re-logar.
        try:
            from server import session_guard as _sg
            _sg.setar_credenciais(
                driver,
                login=perfil_data.get('login', ''), senha=perfil_data.get('senha', ''),
                tfa=perfil_data.get('tfa', ''), email=perfil_data.get('email', ''),
                senha_email=perfil_data.get('senha_email', ''))
        except Exception:
            pass

        # CAPTCHA-ANYWHERE: logo após o login (por cookie ou credenciais) o FB
        # às vezes exibe um reCAPTCHA — resolve aqui antes de seguir o fluxo.
        _tratar_captcha_se_preciso(driver, callback_status)

        # ===== PASSO 3.5: Warm-up no feed (humanizacao) =====
        # OTIMIZAÇÃO: Warm-up reduzido drasticamente para não atrasar o fluxo
        # de criação da BM. Simula humano, mas muito mais rápido.
        try:
            from server.personality_profile import obter_personalidade
            from server.humanizacao_avancada import aquecer_perfil
            
            if callback_status:
                callback_status("Aquecimento rápido do perfil...")
                
            personalidade = obter_personalidade(profile_id)
            
            # Forçar tempos muito menores no objeto personalidade para esta execução
            if isinstance(personalidade, dict):
                personalidade['warmup_feed_seg'] = [3, 8] # 3 a 8 segundos no máximo
                personalidade['warmup_reels_seg'] = [0, 0] # Pula os reels
                
            # 1) Rola o feed rapidinho apenas para gerar atividade de sessão
            aquecer_perfil(driver, personalidade=personalidade,
                           callback_status=callback_status)
            
            # OTIMIZAÇÃO: Pulamos a função assistir_reels() para economizar até 70s
            # assistir_reels(driver, personalidade=personalidade, callback_status=callback_status)
            
        except Exception as _warm_exc:
            logger.debug('[Warmup] ignorado: %s', _warm_exc)

        # 🔐 GUARDIÃO DE SESSÃO (Onda 2): se a Meta deslogou o perfil durante o warm-up
        # (ou logo após o login), RE-LOGA agora — antes das navegações da criação da BM,
        # que senão cairiam na tela de login e falhariam. Barato quando logado (no-op).
        try:
            from server import session_guard as _sg
            _sg.garantir_sessao_fb(driver, callback_status)
        except Exception:
            pass

        # ===== PASSO 4: Alterar idioma para pt-BR =====
        # ANTES: resolve cookie/consentimento/ad_free pendente — senão a navegação
        # para settings (troca de idioma) trava nessas telas (e o resto do fluxo).
        _resolver_consentimentos_e_cookies(driver, callback_status)

        if callback_status:
            callback_status("Alterando idioma para Português (Brasil)...")

        alterar_idioma_para_ptbr(driver, callback_status)
        _delay_medio()

        # ── GARANTIA FINAL DE IDIOMA (antes de iniciar o fluxo) ──
        # A conta pode vir em qualquer idioma (vietnamita/inglês/etc.). Aqui
        # CONFIRMAMOS que a UI está em pt-BR e, se não estiver, RE-EXECUTAMOS a
        # troca de IDIOMA DA CONTA (settings → "Idioma da conta" → Português
        # (Brasil)) — NUNCA o cookie/locale (que só traduz a página e a conta
        # continua no idioma antigo). NUNCA descartamos um perfil bom só por
        # idioma — no pior caso seguimos (o fluxo usa URLs diretas), mas o
        # objetivo é garantir pt-BR PERMANENTE na conta, antes de criar a BM.
        try:
            if not _idioma_ja_ptbr(driver):
                logger.warning("[Idioma] Conta ainda não pt-BR antes do fluxo — re-executando troca do idioma da conta.")
                if callback_status:
                    callback_status("Garantindo idioma pt-BR antes de iniciar...")
                alterar_idioma_para_ptbr(driver, callback_status)
            else:
                logger.info("[Idioma] Confirmado pt-BR antes de iniciar o fluxo.")
        except Exception as _idg:
            logger.debug("[Idioma] garantia final ignorada: %s", _idg)

        # Tag de logado
        adicionar_tags_func(profile_id, ["💎 Perfil Logado 💎"])

        # ===== PASSO 5: Verificar BM existente =====
        # REPROCESSO (forcar_criar_bm): NÃO reusa a BM existente — o objetivo é
        # criar uma BM NOVA no mesmo perfil. Sem esta guarda, o perfil (que SEMPRE
        # tem BM no reprocesso) caía aqui e ficava confirmando e-mail na BM ANTIGA
        # em vez de criar outra. O short-circuit evita até chamar verificar_bm_existe.
        if not forcar_criar_bm and callback_status:
            callback_status("Verificando BM existente...")

        bm_ja_existe = (not forcar_criar_bm) and verificar_bm_existe(driver, callback_status)
        if bm_ja_existe:
            if callback_status:
                callback_status("BM já existente!")
            resultado['bm_criada'] = True
            resultado['bms_criadas'] = 1
            resultado['bm_ja_existia'] = True   # sinaliza p/ o backend RETOMAR pelo status

            # Capturar o business_id da BM já existente (p/ a retomada).
            _bid_exist = extrair_business_id_da_url(driver.current_url)
            if not _bid_exist:
                try:
                    for _h in driver.window_handles:
                        driver.switch_to.window(_h)
                        _bid_exist = extrair_business_id_da_url(driver.current_url)
                        if _bid_exist:
                            break
                except Exception:
                    pass
            resultado['business_id'] = _bid_exist or ''

            if _detectar_bm_bloqueada(driver):
                adicionar_tags_func(profile_id, ["💔 BM BLOQUEADA 💔"])
            else:
                adicionar_tags_func(profile_id, ["💎 1 BM CRIADA 💎"])

            # ── FLUXO COMPLETO / PRO MAX (skip_close): NÃO espera e-mail! A BM já
            #    existe — quem RETOMA é o backend (retomar_bm_para_analise), lendo o
            #    STATUS e seguindo o fluxo (domínio → restrição → WABA/Central →
            #    análise). Mantém o navegador ABERTO: o finally devolve o driver vivo
            #    (bm_criada=True, sem bm_bloqueada). NÃO setamos bm_bloqueada aqui —
            #    a restrição real é detectada na retomada (Contas de anúncios), e é lá
            #    que se decide criar BM nova / excluir o perfil.
            if skip_close:
                resultado['mensagem'] = ("BM já existente — retomando pelo status "
                                         "(sem esperar e-mail).")
                return resultado

            # ── FLUXO BÁSICO ('nao'): aqui confirmar o e-mail É o objetivo do nível,
            #    então mantém o comportamento antigo.
            email_check, aba_check = obter_email_tmail_com_retry(driver, max_tentativas=2, callback_status=callback_status)
            if email_check:
                resultado['email_tmail'] = email_check
                email_ok = confirmar_email_bm(driver, email_check, callback_status)
                resultado['email_confirmado'] = email_ok
                _salvar_email_bm_nas_notas(email_check, email_ok)
                resultado['mensagem'] = f"BM existente. Email {'confirmado' if email_ok else 'não confirmado'}."
            else:
                resultado['mensagem'] = "BM já existente."

            try:
                driver.quit()
            except:
                pass
            fechar_navegador_func(profile_id)
            return resultado

        # ===== ANTI-CASCATA: janela de criação segura (IP compartilhado) =====
        # Se várias abas dividem o mesmo IP (4G/sem proxy), NÃO deixamos a BM
        # nascer no mesmo instante em todas — isso é padrão de robô e o FB
        # derruba em cascata. O gate serializa a ENTRADA na criação com um
        # intervalo humano. Login/warm-up já rodaram em paralelo até aqui.
        if gate_criacao:
            try:
                gate_criacao(callback_status)
            except Exception as _ge:
                logger.debug("[Gate criação] ignorado: %s", _ge)

        # ===== PASSO 6: LOOP DE CRIAÇÃO DE BMs (com retry se bloqueada) =====
        bms_criadas = 0
        email_tmail_final = None
        bm_name_final = ''
        MAX_BMS_BLOQUEADAS = 5  # Perfil pode criar até 5 BMs; se todas bloqueadas → desiste
        bms_bloqueadas = 0
        bm_ok_sem_bloqueio = False
        email_usado_anterior = None

        # Contador de falhas de nome — para gerar novos nomes a cada retry
        _nome_rejeitado_count = 0

        # Modo entrega (fluxo 'imediata'): para apos 1 BM saudavel
        _parar_entrega = False

        # ── Recuperação de BLOQUEIO na criação (pedido do usuário) ──
        # Se a 1ª BM nasce com restrição/bloqueio, a PRÓXIMA é criada com NOME
        # FAKE (o gerador do fluxo básico) — senão a Meta recusa "nome já em uso"
        # (a BM bloqueada ainda segura o nome real). Guardamos os business_ids das
        # BMs bloqueadas p/ DEPOIS: renomeá-las para fake (LIBERA o nome real) e
        # dar o nome real à BM boa. Se TODAS bloquearem → descarta o perfil.
        _bms_bloqueadas_ids = []      # business_ids das BMs que nasceram bloqueadas
        _forcar_nome_fake = False     # próxima criação usa nome fake (após bloqueio)

        for bm_num in range(1, qtd_bm + 1):
            # Navegador fechado (usuário na mão / queda)? Aborta NA HORA como
            # Erro/Falha — não fica preso em 'Processando' com um navegador que
            # nem está mais aberto.
            if navegador_foi_fechado(driver):
                resultado['mensagem'] = "Navegador foi fechado durante a criação da BM."
                resultado['navegador_fechado'] = True
                return resultado
            # Se já criou uma BM e o usuário quer 2, garantir que estamos na tela de criação
            if bm_num > 1 and bms_criadas > 0:
                driver.get("https://business.facebook.com/overview")
                _delay_pagina(2.0, 4.0)
            if callback_status:
                callback_status(f"\n=== Criando BM {bm_num}/{qtd_bm} ===")

            logger.info(f"=== CRIANDO BM {bm_num}/{qtd_bm} ===")

            bm_criada_nesta_rodada = False

            # Tentativas de criação (inclui retries por bloqueio)
            MAX_TENTATIVAS = 3 + MAX_BMS_BLOQUEADAS  # 3 normais + 5 por bloqueio = 8 max
            for tentativa in range(1, MAX_TENTATIVAS + 1):

                # Navegador fechado no meio das tentativas? Aborta como Erro/Falha.
                if navegador_foi_fechado(driver):
                    resultado['mensagem'] = "Navegador foi fechado durante a criação da BM."
                    resultado['navegador_fechado'] = True
                    return resultado

                # Atingiu o limite de bloqueios — parar
                if bms_bloqueadas >= MAX_BMS_BLOQUEADAS:
                    logger.error(f"[BM {bm_num}] {MAX_BMS_BLOQUEADAS} BMs bloqueadas — desistindo")
                    if callback_status:
                        callback_status(f"[BM {bm_num}] ❌ {MAX_BMS_BLOQUEADAS} BMs bloqueadas — desistindo")
                    break

                if callback_status:
                    callback_status(f"[BM {bm_num}] Tentativa {tentativa} (bloqueadas: {bms_bloqueadas})")

                # Obter email TMail (novo se for retry por bloqueio)
                if email_usado_anterior:
                    if callback_status:
                        callback_status(f"[BM {bm_num}] Obtendo novo email diferente...")
                    email_tmail, aba_tmail = _obter_novo_email_tmail(driver, email_usado_anterior, callback_status)
                    email_usado_anterior = None  # Reset para não tentar novo de novo
                else:
                    email_tmail, aba_tmail = obter_email_tmail_com_retry(driver, max_tentativas=2, callback_status=callback_status)

                if not email_tmail:
                    _delay_pagina(3.0, 5.0)
                    continue

                if callback_status:
                    callback_status(f"[BM {bm_num}] Email: {email_tmail}")

                # Gerar nome e criar BM
                # nome_bm_override = razão social COMPLETA (campo "Nome da sua conta e empresa")
                # seu_nome_override = nome abreviado (campo "Seu nome")
                # Se nome foi rejeitado anteriormente, gerar novo nome
                if _nome_rejeitado_count == 0 and not _forcar_nome_fake and nome_bm_override:
                    # Primeira tentativa: usar razão social completa
                    nome_empresa_bm = nome_bm_override
                    nome_pessoa_bm = seu_nome_override if seu_nome_override else nome_bm_override
                elif _forcar_nome_fake or _nome_rejeitado_count > 0:
                    # Bloqueio anterior OU nome rejeitado → nome brasileiro aleatório
                    # (fake). A BM bloqueada segura o nome real; a nova nasce com
                    # nome fake e, se vier limpa, herda o nome real depois (evita o
                    # "nome já em uso" que a Meta devolvia ao recriar com o real).
                    nome, sobrenome, nome_completo = gerar_nome_brasileiro()
                    nome_empresa_bm = nome_completo
                    nome_pessoa_bm = nome_completo
                    _motivo_fake = 'após bloqueio' if _forcar_nome_fake else f'nome rejeitado {_nome_rejeitado_count}x'
                    logger.info(f"[BM {bm_num}] Nome fake ({_motivo_fake}): {nome_empresa_bm}")
                    if callback_status:
                        callback_status(f"[BM {bm_num}] Criando com nome fake ({_motivo_fake}): {nome_empresa_bm}")
                else:
                    nome, sobrenome, nome_completo = gerar_nome_brasileiro()
                    nome_empresa_bm = nome_completo
                    nome_pessoa_bm = nome_completo

                # Voltar para aba do Facebook
                try:
                    _ir_para_aba_facebook(driver)
                except Exception:
                    pass

                # FIX 2026-10-12: a partir da 2ª BM (bms_criadas>0) OU depois de uma BM
                # BLOQUEADA, o perfil JÁ TEM BM e a URL de criação redireciona p/ ela →
                # criar_bm_facebook devolvia "EXISTE" e o loop contava a MESMA BM de novo
                # (2ª BM fantasma / retry pós-bloqueio que nunca criava outra). Nesses
                # casos força abrir o formulário de um NOVO portfólio. (Falha simples
                # sem bloqueio mantém forcar_novo original: o "EXISTE" ali recupera uma
                # BM que nasceu mas cujo popup não foi detectado.)
                _forcar_novo_bm = bool(forcar_criar_bm or bms_criadas > 0 or _forcar_nome_fake)
                bm_resultado = criar_bm_facebook(driver, nome_empresa_bm, nome_pessoa_bm, email_tmail,
                                                 callback_status, forcar_novo=_forcar_novo_bm)

                if bm_resultado == "LIMITE":
                    # TETO de BMs do perfil atingido (a Meta permite ~2 por perfil).
                    # Cenário do usuário: já existem 2 BMs, AMBAS restritas na criação →
                    # não há o que entregar e não dá p/ criar mais. PARA o loop (não fica
                    # gerando email/tentativa à toa), COMPUTA como bloqueio e o backend
                    # FECHA o navegador e vai p/ o PRÓXIMO da fila. (2026-07-25)
                    logger.error(f"[BM {bm_num}] LIMITE de BMs do perfil atingido — "
                                 f"encerrando este perfil (bloqueadas: {bms_bloqueadas}).")
                    if callback_status:
                        callback_status(f"[BM {bm_num}] ⛔ Perfil no limite de BMs (Meta) — "
                                        f"encerrando e indo p/ o próximo.")
                    resultado['bm_bloqueada'] = True
                    resultado['limite_bm_atingido'] = True
                    resultado['mensagem'] = ('Perfil atingiu o limite de BMs da Meta '
                                             '(BMs existentes restritas) — nada a criar.')
                    break

                if bm_resultado == "EXISTE":
                    # BM já existente — verificar se está bloqueada
                    _delay_pagina(2.0, 3.0)
                    if _detectar_bm_bloqueada(driver):
                        bms_bloqueadas += 1
                        logger.warning(f"[BM {bm_num}] BM existente BLOQUEADA ({bms_bloqueadas}/{MAX_BMS_BLOQUEADAS})")
                        if callback_status:
                            callback_status(f"[BM {bm_num}] ⚠️ BM existente bloqueada!")
                        resultado['bm_bloqueada'] = True
                    else:
                        bm_ok_sem_bloqueio = True

                    bms_criadas += 1
                    email_tmail_final = email_tmail
                    bm_name_final = nome_empresa_bm
                    bm_criada_nesta_rodada = True
                    break

                if bm_resultado is True:
                    from server.page_state_manager import PageStateManager

                    # Ao clicar em Concluir, o Facebook REDIRECIONA para a BM
                    # criada (business_home com business_id). NÃO navegamos para
                    # outro lugar — isso dava um F5 que CORTAVA o carregamento.
                    # AGUARDAMOS a página RENDERIZAR COMPLETAMENTE (painel/menu
                    # visível como no exemplo: "Página inicial", nav lateral,
                    # cards). F5 SOMENTE se ela cair em BRANCO ou na tela de ERRO
                    # ("Estamos tendo problemas para concluir sua solicitação.").
                    if callback_status:
                        callback_status(f"[BM {bm_num}] Aguardando a BM criada carregar 100%...")

                    bm_carregada = False
                    f5_dados = 0
                    # Prazo AUMENTADO (2026-07-31): 90s → 150s. Dá mais tempo p/ a BM
                    # renderizar em 4G/perfis lentos antes de qualquer F5.
                    prazo_bm = time.time() + 150
                    while time.time() < prazo_bm:
                        # Espera estabilizar SEM F5 automático (f5_after > timeout):
                        # o F5 aqui é decidido só por nós, e só em branco/erro.
                        PageStateManager.wait_until_stable(driver, timeout=40, settle_time=1.5,
                                                           f5_after=60, callback_status=None)
                        if _bm_pagina_carregada(driver):
                            bm_carregada = True
                            break
                        # Em branco ou tela de erro -> F5 (máx 3) e aguarda render.
                        # Espera extra ANTES do F5: dá chance da página completar sozinha.
                        if _bm_pagina_com_erro(driver) and f5_dados < 3:
                            time.sleep(5)
                            if _bm_pagina_carregada(driver):
                                bm_carregada = True
                                break
                            f5_dados += 1
                            logger.info("[BM %s] Página em branco/erro — recarregando (F5 %s).",
                                        bm_num, f5_dados)
                            if callback_status:
                                callback_status(f"[BM {bm_num}] Página incompleta — recarregando (F5)...")
                            try:
                                driver.refresh()
                            except Exception:
                                pass
                            continue
                        time.sleep(2)

                    if bm_carregada:
                        time.sleep(2)  # margem extra: garante 100% renderizado
                        logger.info("[BM %s] Página da BM renderizada 100%%.", bm_num)
                    else:
                        logger.warning("[BM %s] BM não renderizou no tempo limite — seguindo mesmo assim.", bm_num)

                    # Página 100% carregada -> agora sim checar restrição/bloqueio.
                    if callback_status:
                        callback_status(f"[BM {bm_num}] Verificando se a BM tem restrição/bloqueio...")

                    if _detectar_bm_bloqueada(driver):
                        bms_bloqueadas += 1
                        logger.warning(f"[BM {bm_num}] BM recém-criada BLOQUEADA ({bms_bloqueadas}/{MAX_BMS_BLOQUEADAS})")
                        if callback_status:
                            callback_status(f"[BM {bm_num}] ⚠️ BM bloqueada! Tentando outra ({bms_bloqueadas}/{MAX_BMS_BLOQUEADAS})...")

                        # Guarda o business_id da BM bloqueada para renomeá-la
                        # depois (LIBERAR o nome real) quando uma BM limpa nascer.
                        try:
                            _bid_bloq = extrair_business_id_da_url(driver.current_url)
                            if _bid_bloq and _bid_bloq not in _bms_bloqueadas_ids:
                                _bms_bloqueadas_ids.append(_bid_bloq)
                        except Exception:
                            pass
                        # A PRÓXIMA BM deve nascer com NOME FAKE (a bloqueada segura
                        # o nome real → recriar com o real dá "nome já em uso").
                        _forcar_nome_fake = True

                        email_usado_anterior = email_tmail  # Forçar novo email na próxima

                        # Limpar aba TMail
                        try:
                            if aba_tmail:
                                driver.switch_to.window(aba_tmail)
                                driver.close()
                                try:
                                    driver._tmail_handle = None
                                except:
                                    pass
                                driver.switch_to.window(driver.window_handles[0])
                        except:
                            try:
                                driver.switch_to.window(driver.window_handles[0])
                            except:
                                pass
                        _delay_pagina(2.0, 3.0)
                        continue  # Retry com novo email

                    # BM criada e NÃO bloqueada!
                    bms_criadas += 1
                    email_tmail_final = email_tmail
                    bm_name_final = nome_empresa_bm
                    bm_ok_sem_bloqueio = True

                    # ── RECUPERAÇÃO DE NOME (pedido do usuário) ──
                    # Houve BM(s) bloqueada(s) antes → esta BM boa nasceu com NOME
                    # FAKE. Agora: (1) renomeia a(s) bloqueada(s) p/ um nome fake
                    # aleatório (LIBERA o nome real) e (2) dá o NOME REAL (razão
                    # social) a esta BM boa NO NOME DO PORTFÓLIO. Os DETALHES da
                    # empresa (razão social/endereço/CNPJ) NÃO são preenchidos aqui:
                    # a verificação faz isso DEPOIS de verificar o domínio (ordem
                    # anti-restrição) — preencher antes re-introduziria o bloqueio.
                    if _bms_bloqueadas_ids and nome_bm_override and nome_empresa_bm != nome_bm_override:
                        try:
                            _good_bid = extrair_business_id_da_url(driver.current_url)
                            _recuperar_nome_bm_apos_bloqueio(
                                driver, _bms_bloqueadas_ids, _good_bid,
                                nome_bm_override, callback_status)
                            bm_name_final = nome_bm_override
                            # Volta p/ a BM boa (a confirmação de email precisa dela).
                            if _good_bid:
                                driver.get(f"https://business.facebook.com/latest/home?business_id={_good_bid}")
                                _delay_pagina(2.0, 3.5)
                        except Exception as _re:
                            logger.warning("[BM] recuperação de nome pós-bloqueio falhou: %s", _re)

                    # Adicionar Tag de sucesso
                    tag_sucesso = f"💎 {bms_criadas} BM CRIADA 💎"
                    adicionar_tags_func(profile_id, [tag_sucesso])

                    # Confirmar email — REGISTRA o resultado para a contagem por
                    # nível (antes era descartado, então o sistema não sabia se o
                    # email foi confirmado e contava sucesso indevidamente).
                    if callback_status:
                        callback_status(f"[BM {bm_num}] ✅ BM sem bloqueio! Confirmando email...")
                    _email_ok = confirmar_email_bm(driver, email_tmail, callback_status)
                    resultado['email_confirmado'] = bool(_email_ok)
                    _salvar_email_bm_nas_notas(email_tmail, _email_ok)

                    bm_criada_nesta_rodada = True
                    # Modo entrega (fluxo 'imediata'): 1 BM saudavel basta —
                    # sinaliza para parar tambem o loop externo de BMs.
                    if parar_no_primeiro_sucesso:
                        _parar_entrega = True
                    break

                # Criar BM falhou (retornou False) — incrementar contador de rejeição e tentar com novo nome
                _nome_rejeitado_count += 1
                logger.warning(f"[BM {bm_num}] Criação falhou (tentativa {tentativa}), nome rejeitado {_nome_rejeitado_count}x")
                try:
                    if aba_tmail:
                        driver.switch_to.window(aba_tmail)
                        driver.close()
                        try:
                            driver._tmail_handle = None
                        except:
                            pass
                        driver.switch_to.window(driver.window_handles[0])
                except:
                    try:
                        driver.switch_to.window(driver.window_handles[0])
                    except:
                        pass
                _delay_pagina(3.0, 5.0)

            if not bm_criada_nesta_rodada:
                logger.warning(f"BM {bm_num} não foi criada")
                break

            # Modo entrega (fluxo 'imediata'): 1 BM saudavel basta — encerra o
            # loop externo para seguir direto a verificacao de dominio.
            if _parar_entrega:
                logger.info("[BM] Modo entrega: 1 BM criada com sucesso — encerrando loop de BMs")
                break

        # ===== RESULTADO FINAL =====
        if bms_criadas > 0:
            resultado['bm_criada'] = True
            resultado['bms_criadas'] = bms_criadas
            resultado['email_tmail'] = email_tmail_final or ''
            resultado['bm_name'] = bm_name_final or ''
            
            # Capturar business_id
            bid = extrair_business_id_da_url(driver.current_url)
            if not bid:
                try:
                    for handle in driver.window_handles:
                        driver.switch_to.window(handle)
                        bid = extrair_business_id_da_url(driver.current_url)
                        if bid: break
                except:
                    pass
            
            resultado['business_id'] = bid or ''

            if bms_bloqueadas > 0 and not bm_ok_sem_bloqueio:
                resultado['bm_bloqueada'] = True
                resultado['mensagem'] = f"⚠️ {bms_bloqueadas} BM(s) criada(s) porém BLOQUEADA(s)"
            else:
                resultado['mensagem'] = f"{bms_criadas} BM(s) criada(s) com sucesso!"
        else:
            resultado['bm_criada'] = False
            resultado['mensagem'] = "Logado, mas não foi possível criar BM"

    except Exception as e:
        logger.error(f"Erro na automação: {e}")
        resultado['mensagem'] = f"Erro: {str(e)}"
        
        # Verificar se o erro foi um bloqueio de perfil (checkpoint)
        try:
            url_atual = driver.current_url.lower()
            if 'checkpoint' in url_atual or 'disabled' in url_atual:
                adicionar_tags_func(profile_id, ["🚫 PERFIL BLOQUEADO 🚫"])
        except:
            pass

    finally:
        if skip_close and resultado.get('bm_criada') and not resultado.get('bm_bloqueada'):
            # Manter navegador aberto para verificação — retornar driver
            resultado['driver'] = driver
            resultado['_skip_close'] = True
        else:
            if callback_status:
                callback_status("Fechando navegador...")
            try:
                if driver:
                    driver.quit()
            except:
                pass
            try:
                fechar_navegador_func(profile_id)
            except:
                pass

    return resultado
