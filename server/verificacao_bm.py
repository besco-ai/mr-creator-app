#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de Verificação Completa de BM (v2.0 — 2026)
====================================================
Após a criação da BM e confirmação do email, este módulo:
1. Acessa "Informações da empresa" no Facebook Business
2. Verifica popup "Informações do portfólio" (Nome da empresa + Página principal)
3. Preenche detalhes da empresa (razão social, endereço, cidade, estado, CEP, telefone, site, CNPJ)
4. Adiciona domínio e verifica via Meta Tag
5. Usa número virtual SMS para telefone comercial

Estratégia de Seletores:
- Os IDs do Facebook (js_XX) são DINÂMICOS e mudam a cada sessão
- Usa cascata: aria-label → placeholder → label adjacente → posição no DOM
- XPaths fornecidos servem como referência de estrutura, não como seletor fixo

Requer:
- PlaywrightDriver conectado ao Facebook Business (com native API)
- Dados da empresa gerados via API GranaSocial (Fábrica de Empresas)
- business_id extraído da URL da BM criada
"""

import re
import time
import logging
import random
import math

logger = logging.getLogger(__name__)


# ============================================================================
# MÉTODO DE VERIFICAÇÃO DE DOMÍNIO (escolhido pelo usuário na GUI) — 2026-09-30
# ----------------------------------------------------------------------------
# O Facebook aceita 3 métodos p/ verificar o domínio, todos com o MESMO código:
#   • 'metatag' → <meta name="facebook-domain-verification" content="CODE"> no <head>
#   • 'dns'     → registro TXT  facebook-domain-verification=CODE  (Cloudflare)
#   • 'arquivo' → arquivo HTML servido na raiz do site
# 'auto' (padrão) = tenta meta-tag e, se a Meta não confirmar, cai para DNS e depois
# arquivo automaticamente (é o que resolve "a meta tag não está verificando agora").
# A GUI manda a escolha; o backend chama set_metodo_verificacao() antes de rodar.
_METODOS_VALIDOS = ('auto', 'metatag', 'dns', 'arquivo')
_METODO_VERIFICACAO = 'auto'


def set_metodo_verificacao(metodo: str) -> str:
    """Define o método de verificação de domínio para o fluxo inteiro."""
    global _METODO_VERIFICACAO
    m = (metodo or 'auto').strip().lower()
    # normaliza sinônimos vindos da GUI (tolera espaços/variações: "dns txt", "meta tag"…)
    if m in _METODOS_VALIDOS:
        pass
    elif 'dns' in m or 'txt' in m:
        m = 'dns'
    elif 'arquiv' in m or 'file' in m or 'html' in m or 'upload' in m:
        m = 'arquivo'
    elif 'meta' in m or 'tag' in m:
        m = 'metatag'
    else:
        m = 'auto'
    _METODO_VERIFICACAO = m
    logger.info("[Domínio] método de verificação = %s", m)
    return m


def get_metodo_verificacao() -> str:
    return _METODO_VERIFICACAO


# ============================================================================
# DELAYS HUMANIZADOS (distribuição Gaussiana para comportamento natural)
# ============================================================================

def _delay(min_s=0.3, max_s=0.7):
    """Delay humanizado com distribuição gaussiana. Valores reduzidos ~2026-08-14
    p/ ACELERAR o fluxo (roda dezenas de vezes por perfil) mantendo um tick mínimo
    p/ o React estabilizar. Base era 0.5–1.2."""
    media = (min_s + max_s) / 2
    desvio = (max_s - min_s) / 4
    t = random.gauss(media, desvio)
    t = max(min_s, min(max_s, t))
    time.sleep(t)


def _delay_curto():
    _delay(0.15, 0.4)


def _delay_medio():
    _delay(0.4, 0.8)


def _delay_longo():
    _delay(0.5, 1.0)


def _delay_digitacao():
    """Delay entre caracteres (30-90ms)."""
    time.sleep(random.uniform(0.03, 0.09))


def _delay_leitura():
    """Delay simulando leitura da tela. Era 2–4s FIXO (maior ofensor de lentidão);
    reduzido p/ 1–2s — continua natural mas corta ~50% desses pontos por perfil."""
    _delay(1.0, 2.0)


# ============================================================================
# COMPORTAMENTO HUMANO (mouse, scroll, cliques naturais)
# ============================================================================

def _mover_mouse_humano(driver, x, y):
    """Move o mouse com curva Bézier para parecer humano."""
    try:
        steps = random.randint(8, 15)
        current_x = random.randint(100, 600)
        current_y = random.randint(100, 400)

        try:
            pos = driver.evaluate_page('() => ({x: window._mouseX || 0, y: window._mouseY || 0})')
            if pos.get('x'):
                current_x = pos['x']
            if pos.get('y'):
                current_y = pos['y']
        except Exception:
            pass

        ctrl_x = (current_x + x) / 2 + random.randint(-50, 50)
        ctrl_y = (current_y + y) / 2 + random.randint(-30, 30)

        for i in range(1, steps + 1):
            t = i / steps
            bx = (1 - t) ** 2 * current_x + 2 * (1 - t) * t * ctrl_x + t ** 2 * x
            by = (1 - t) ** 2 * current_y + 2 * (1 - t) * t * ctrl_y + t ** 2 * y
            driver.mouse.move(bx, by)
            time.sleep(random.uniform(0.008, 0.025))

        driver.evaluate_page(f'() => {{ window._mouseX = {x}; window._mouseY = {y}; }}')
    except Exception:
        pass


def _scroll_suave(driver, direcao='baixo', pixels=None):
    """Scroll suave simulando humano."""
    try:
        if pixels is None:
            pixels = random.randint(100, 300) if direcao == 'baixo' else random.randint(-300, -100)
        elif direcao == 'cima':
            pixels = -abs(pixels)

        steps = random.randint(3, 6)
        per_step = pixels / steps
        for _ in range(steps):
            driver.mouse.wheel(0, per_step)
            time.sleep(random.uniform(0.05, 0.12))
    except Exception:
        pass


def _clicar_humano(driver, elemento):
    """Clica em um elemento com comportamento humano (scroll + move + click)."""
    try:
        box = elemento.bounding_box()
        if box:
            try:
                viewport = driver.evaluate_page('() => ({h: window.innerHeight, s: window.scrollY})')
                vh = viewport.get('h', 800)
                ey = box['y']
                if ey > vh * 0.8:
                    _scroll_suave(driver, 'baixo', int(ey - vh * 0.4))
                    _delay(0.3, 0.6)
            except Exception:
                pass

            cx = box['x'] + box['width'] * random.uniform(0.2, 0.8)
            cy = box['y'] + box['height'] * random.uniform(0.3, 0.7)
            _mover_mouse_humano(driver, cx, cy)
            _delay(0.1, 0.3)

        elemento.click()
    except Exception:
        try:
            elemento.click()
        except Exception:
            pass


# ============================================================================
# HELPERS DE INPUT (compatíveis com React/Facebook via Playwright native)
# ============================================================================

def _limpar_e_digitar(driver, elemento, valor, nome_campo='campo'):
    """
    Limpa um input e preenche com valor.
    Usa React Native Setter para garantir que o Facebook registra o valor
    no state interno do React (sem isso, o botão Salvar fica desabilitado).

    Fallback: digitar char-by-char se o setter falhar.
    """
    if not elemento or not valor:
        return False

    valor = str(valor).strip()

    for tentativa in range(3):
        try:
            # Scroll + focus
            try:
                elemento.scroll_into_view_if_needed()
            except Exception:
                pass
            _delay(0.1, 0.3)

            # Clicar no campo
            _clicar_humano(driver, elemento)
            _delay(0.3, 0.6)

            # === Método 1: React Native Setter ===
            try:
                elemento.evaluate("""(el, val) => {
                    el.focus();
                    try {
                        var setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, '');
                        setter.call(el, val);
                    } catch(e) {
                        el.value = '';
                        el.value = val;
                    }
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    el.dispatchEvent(new Event('blur', {bubbles: true}));
                }""", valor)
            except Exception:
                pass

            _delay(0.3, 0.5)

            # Verificar se preencheu
            val_atual = ''
            try:
                val_atual = elemento.evaluate('el => el.value || ""') or ''
            except Exception:
                pass

            if val_atual.strip().lower() == valor.strip().lower():
                logger.info("[Verificação] Campo '%s' preenchido (setter): '%s'",
                            nome_campo, val_atual[:40])
                return True

            # === Método 2: Limpar + digitar char-by-char ===
            _clicar_humano(driver, elemento)
            _delay(0.2, 0.4)

            # Limpar campo existente
            driver.keyboard.press('Control+a')
            _delay(0.1, 0.2)
            driver.keyboard.press('Backspace')
            _delay(0.1, 0.2)

            # Digitar caractere por caractere
            for idx, char in enumerate(valor):
                driver.keyboard.type(char, delay=random.randint(25, 85))
                if idx > 0 and idx % random.randint(4, 8) == 0:
                    time.sleep(random.uniform(0.08, 0.2))

            _delay(0.3, 0.5)

            # Disparar eventos React manualmente
            try:
                elemento.evaluate("""el => {
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""")
            except Exception:
                pass

            # Verificar
            try:
                val_final = elemento.evaluate('el => el.value || ""') or ''
                if val_final.strip():
                    logger.info("[Verificação] Campo '%s' preenchido (type): '%s'",
                                nome_campo, val_final[:40])
                    return True
            except Exception:
                pass

        except Exception as e:
            logger.warning("[Verificação] Tentativa %d para '%s': %s",
                           tentativa + 1, nome_campo, e)
        _delay(0.2, 0.5)

    logger.error("[Verificação] Falhou ao preencher '%s' com '%s'", nome_campo, valor[:30])
    return False


def _verificar_erro_validacao_telefone(driver):
    """Verifica se há mensagem de erro de validação no campo de telefone.
    Retorna True se há erro visível ('Insira um número de telefone válido', etc.)."""
    try:
        tem_erro = driver.evaluate_page("""() => {
            var dialog = document.querySelector('[role="dialog"]');
            var container = dialog || document;
            var textos = container.querySelectorAll('span, div, p');
            for (var i = 0; i < textos.length; i++) {
                var t = (textos[i].innerText || textos[i].textContent || '').trim().toLowerCase();
                if (t.indexOf('número de telefone válido') !== -1 ||
                    t.indexOf('numero de telefone valido') !== -1 ||
                    t.indexOf('valid phone number') !== -1 ||
                    t.indexOf('insira um número') !== -1 ||
                    t.indexOf('enter a valid') !== -1 ||
                    t.indexOf('telefone inválido') !== -1 ||
                    t.indexOf('invalid phone') !== -1) {
                    return true;
                }
            }
            /* Verificar se o input de telefone tem borda vermelha/erro */
            var telInput = container.querySelector('[data-detalhe-campo="telefone"]');
            if (telInput) {
                var parent = telInput.parentElement;
                for (var d = 0; d < 4 && parent; d++) {
                    var style = window.getComputedStyle(parent);
                    var borderColor = style.borderColor || '';
                    if (borderColor.indexOf('rgb(224, 36, 36)') !== -1 ||
                        borderColor.indexOf('rgb(255, 0, 0)') !== -1 ||
                        borderColor.indexOf('#e02424') !== -1 ||
                        parent.getAttribute('aria-invalid') === 'true') {
                        return true;
                    }
                    parent = parent.parentElement;
                }
                /* Verificar aria-invalid no próprio input */
                if (telInput.getAttribute('aria-invalid') === 'true') return true;
            }
            return false;
        }""")
        return bool(tem_erro)
    except Exception:
        return False


def _limpar_campo_completamente(driver, elemento):
    """Limpa um campo de input completamente usando múltiplas estratégias."""
    try:
        # Focar e selecionar tudo
        _clicar_humano(driver, elemento)
        _delay(0.2, 0.4)
        
        # Estratégia 1: Ctrl+A + Delete
        driver.keyboard.press('Control+a')
        _delay(0.1, 0.2)
        driver.keyboard.press('Delete')
        _delay(0.1, 0.2)

        # Verificar se limpou
        val = elemento.evaluate('el => el.value || ""') or ''
        if val.strip():
            # Estratégia 2: Triple-click + Backspace
            _clicar_humano(driver, elemento)
            _delay(0.1, 0.2)
            driver.keyboard.press('Home')
            _delay(0.05, 0.1)
            driver.keyboard.down('Shift')
            driver.keyboard.press('End')
            driver.keyboard.up('Shift')
            _delay(0.1, 0.2)
            driver.keyboard.press('Backspace')
            _delay(0.1, 0.2)

        # Verificar novamente
        val = elemento.evaluate('el => el.value || ""') or ''
        if val.strip():
            # Estratégia 3: React setter com valor vazio + backspace manual
            try:
                elemento.evaluate("""el => {
                    try {
                        var setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, '');
                    } catch(e) {
                        el.value = '';
                    }
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""")
            except Exception:
                pass
            _delay(0.1, 0.2)
            # Backspace residual
            for _ in range(30):
                driver.keyboard.press('Backspace')
                time.sleep(0.02)

        return True
    except Exception as e:
        logger.warning("[Verificação] Erro ao limpar campo: %s", e)
        return False


def _digitar_telefone_no_campo(driver, elemento, numero, metodo='react'):
    """Digita um número de telefone em um campo usando o método especificado.

    Métodos disponíveis:
      - 'react': React Native Setter (mais rápido, pode falhar com validação)
      - 'keyboard': Digita char-by-char via keyboard (mais confiável)
      - 'keyboard_fast': Digita via keyboard.type (intermediário)
      - 'paste': Cola via clipboard (mais rápido, pode não funcionar)

    Returns:
        bool: True se o valor foi preenchido (independente de validação)
    """
    try:
        if metodo == 'react':
            # React Native Setter
            elemento.evaluate("""(el, val) => {
                el.focus();
                try {
                    var setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, val);
                } catch(e) {
                    el.value = val;
                }
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                /* Disparar também eventos que o Facebook pode escutar */
                el.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true}));
                el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
                el.dispatchEvent(new Event('blur', {bubbles: true}));
                el.dispatchEvent(new Event('focus', {bubbles: true}));
            }""", numero)
            _delay(0.3, 0.5)

        elif metodo == 'keyboard':
            # Digitar caractere por caractere com delays humanizados
            _clicar_humano(driver, elemento)
            _delay(0.2, 0.4)
            for idx, char in enumerate(numero):
                driver.keyboard.type(char, delay=random.randint(30, 90))
                if idx > 0 and idx % random.randint(3, 6) == 0:
                    time.sleep(random.uniform(0.1, 0.25))
            _delay(0.3, 0.5)
            # Disparar eventos React
            try:
                elemento.evaluate("""el => {
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""")
            except Exception:
                pass

        elif metodo == 'keyboard_fast':
            _clicar_humano(driver, elemento)
            _delay(0.2, 0.4)
            driver.keyboard.type(numero, delay=random.randint(25, 60))
            _delay(0.3, 0.5)
            try:
                elemento.evaluate("""el => {
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""")
            except Exception:
                pass

        elif metodo == 'paste':
            # Inserir via execCommand (simula paste)
            _clicar_humano(driver, elemento)
            _delay(0.2, 0.4)
            try:
                elemento.evaluate("""(el, val) => {
                    el.focus();
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, val);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""", numero)
            except Exception:
                # Fallback: keyboard fast
                driver.keyboard.type(numero, delay=random.randint(25, 60))
            _delay(0.3, 0.5)

        # Verificar se o valor ficou
        _delay(0.2, 0.4)
        val = ''
        try:
            val = elemento.evaluate('el => el.value || ""') or ''
        except Exception:
            pass

        if val.strip():
            logger.info("[Telefone] Valor digitado OK (%s): '%s'", metodo, val[:25])
            return True
        else:
            logger.warning("[Telefone] Valor não preencheu (%s)", metodo)
            return False

    except Exception as e:
        logger.warning("[Telefone] Erro ao digitar (%s): %s", metodo, e)
        return False


def _preencher_telefone_robusto(driver, campo_telefone, variantes_telefone, callback_status=None):
    """Preenche o campo de telefone comercial usando o seletor exato do Facebook.

    O input do Facebook tem estas características (2026):
      - type="text" (NÃO é type="tel")
      - data-detalhe-campo="telefone" (marcado pelo nosso JS)
      - aria-invalid="true" quando vazio ou inválido
      - Classes dinâmicas: xjbqb8w x972fbf x10w94by x1qhh985 ...
      - Validação React que rejeita formatos incorretos

    Estratégia:
      1. Focar o campo clicando nele
      2. Limpar qualquer valor existente
      3. Usar React Native Input Value Setter para definir o valor
      4. Disparar eventos React (input, change, blur) para acionar validação
      5. Verificar se aria-invalid mudou para "false"
      6. Se ainda inválido, tentar próxima variante

    Args:
        driver: PlaywrightDriver
        campo_telefone: ElementHandle do campo de telefone
        variantes_telefone: lista de strings com variantes do número
        callback_status: callback para progresso

    Returns:
        dict: {'sucesso': bool, 'formato_aceito': str, 'mensagem': str}
    """
    if not campo_telefone:
        return {'sucesso': False, 'mensagem': 'Campo de telefone não encontrado'}

    if not variantes_telefone:
        return {'sucesso': False, 'mensagem': 'Nenhuma variante de telefone fornecida'}

    total_tentativas = 0

    for idx_var, variante in enumerate(variantes_telefone):
        total_tentativas += 1

        if callback_status:
            callback_status(
                f"📱 Tentativa {total_tentativas}/{len(variantes_telefone)}: {variante}")

        logger.info("[Telefone] Tentativa %d/%d — formato='%s'",
                    total_tentativas, len(variantes_telefone), variante)

        try:
            # ============================================================
            # MÉTODO PRINCIPAL: React Native Setter + dispatchEvent
            # Este é o ÚNICO método que funciona 100% com o React do Facebook.
            # O Facebook escuta por 'input' event com bubbles:true.
            # ============================================================

            resultado_js = driver.evaluate_page(f"""() => {{
                // Localizar o campo de telefone pelo seletor exato
                var campo = document.querySelector('[data-detalhe-campo="telefone"]');
                if (!campo) {{
                    // Fallback: buscar dentro do dialog
                    var dialog = document.querySelector('[role="dialog"]');
                    if (dialog) {{
                        var inputs = dialog.querySelectorAll('input[type="text"], input:not([type])');
                        // O campo de telefone geralmente é o 7º input (índice 6)
                        // Verificar também por aria-label ou contexto
                        for (var i = 0; i < inputs.length; i++) {{
                            var nearTxt = '';
                            var p = inputs[i].parentElement;
                            for (var d = 0; d < 5 && p && p !== dialog; d++) {{
                                nearTxt += ' ' + (p.innerText || '').toLowerCase();
                                p = p.parentElement;
                            }}
                            if (nearTxt.indexOf('telefone') !== -1 || nearTxt.indexOf('phone') !== -1) {{
                                campo = inputs[i];
                                break;
                            }}
                        }}
                        // Se ainda não encontrou, usar posição 6 (7º input)
                        if (!campo && inputs.length >= 7) {{
                            campo = inputs[6];
                        }}
                    }}
                }}
                if (!campo) return {{ok: false, erro: 'campo_nao_encontrado'}};

                // 1. Focar o campo
                campo.focus();

                // 2. Limpar valor existente via React Native Setter
                try {{
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    nativeInputValueSetter.call(campo, '');
                    campo.dispatchEvent(new Event('input', {{bubbles: true}}));
                }} catch(e) {{
                    campo.value = '';
                }}

                // 3. Definir o novo valor via React Native Setter
                var valor = '{variante}';
                try {{
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    nativeInputValueSetter.call(campo, valor);
                }} catch(e) {{
                    campo.value = valor;
                }}

                // 4. Disparar eventos React na ordem correta
                campo.dispatchEvent(new Event('input', {{bubbles: true}}));
                campo.dispatchEvent(new Event('change', {{bubbles: true}}));

                // 5. Simular blur para acionar validação
                campo.dispatchEvent(new Event('blur', {{bubbles: true}}));

                // 6. Verificar resultado
                var valorFinal = campo.value || '';
                var ariaInvalid = campo.getAttribute('aria-invalid');

                return {{
                    ok: true,
                    valor: valorFinal,
                    ariaInvalid: ariaInvalid
                }};
            }}""")

            if not resultado_js or not resultado_js.get('ok'):
                logger.warning("[Telefone] JS falhou para '%s': %s",
                               variante, resultado_js)
                continue

            valor_no_campo = resultado_js.get('valor', '')
            logger.info("[Telefone] Valor definido: '%s' | aria-invalid: %s",
                        valor_no_campo, resultado_js.get('ariaInvalid'))

            if not valor_no_campo.strip():
                logger.warning("[Telefone] Campo ficou vazio após setter — '%s'", variante)
                continue

            # Aguardar React processar a validação
            _delay(1.0, 2.0)

            # Re-verificar aria-invalid após delay (React pode demorar a validar)
            try:
                aria_state = campo_telefone.evaluate(
                    'el => el.getAttribute("aria-invalid")') or ''
            except Exception:
                # Se o elemento ficou stale, buscar novamente
                try:
                    campo_telefone = driver.query_selector('[data-detalhe-campo="telefone"]')
                    aria_state = campo_telefone.evaluate(
                        'el => el.getAttribute("aria-invalid")') or '' if campo_telefone else 'true'
                except Exception:
                    aria_state = 'unknown'

            logger.info("[Telefone] Após delay — aria-invalid: '%s'", aria_state)

            # Se aria-invalid é "false" ou null, o Facebook aceitou!
            if aria_state != 'true':
                logger.info("[Telefone] ✅ ACEITO pelo Facebook: '%s'", variante)
                return {
                    'sucesso': True,
                    'formato_aceito': variante,
                    'mensagem': f'Telefone aceito: {variante}'
                }

            # Verificar também pela mensagem de erro visível
            tem_erro_visivel = _verificar_erro_validacao_telefone(driver)
            if not tem_erro_visivel:
                # Sem mensagem de erro mesmo com aria-invalid=true?
                # Pode ser que o campo ainda esteja valid (aria-invalid pode ser stale)
                logger.info("[Telefone] ✅ Sem erro visível — aceitando '%s'", variante)
                return {
                    'sucesso': True,
                    'formato_aceito': variante,
                    'mensagem': f'Telefone aceito (sem erro visível): {variante}'
                }

            logger.warning("[Telefone] ❌ Rejeitado: '%s' (aria-invalid=true + erro visível)",
                           variante)

        except Exception as e:
            logger.warning("[Telefone] Erro na tentativa %d: %s", total_tentativas, e)

    # Se todas as variantes falharam, tentar ÚLTIMO RECURSO:
    # digitar via keyboard char-by-char (o mais básico possível)
    logger.warning("[Telefone] Todas variantes rejeitadas — último recurso: keyboard char-by-char")
    if callback_status:
        callback_status("📱 Última tentativa: digitação manual...")

    for variante in variantes_telefone[:3]:  # Tentar apenas as 3 primeiras
        try:
            total_tentativas += 1

            # Clicar no campo
            try:
                campo_telefone = driver.query_selector('[data-detalhe-campo="telefone"]')
            except Exception:
                pass

            if not campo_telefone:
                break

            _clicar_humano(driver, campo_telefone)
            _delay(0.3, 0.5)

            # Ctrl+A + Delete para limpar
            driver.keyboard.press('Control+a')
            _delay(0.1, 0.2)
            driver.keyboard.press('Delete')
            _delay(0.2, 0.4)

            # Digitar caractere por caractere
            for char in variante:
                driver.keyboard.type(char, delay=random.randint(40, 100))
            _delay(0.5, 1.0)

            # Tab para blur
            driver.keyboard.press('Tab')
            _delay(1.0, 2.0)

            # Verificar resultado
            try:
                val = campo_telefone.evaluate('el => el.value || ""') or ''
                aria = campo_telefone.evaluate('el => el.getAttribute("aria-invalid")') or ''
            except Exception:
                campo_telefone = driver.query_selector('[data-detalhe-campo="telefone"]')
                if campo_telefone:
                    val = campo_telefone.evaluate('el => el.value || ""') or ''
                    aria = campo_telefone.evaluate('el => el.getAttribute("aria-invalid")') or ''
                else:
                    continue

            if val.strip() and aria != 'true':
                logger.info("[Telefone] ✅ Aceito via keyboard: '%s'", variante)
                return {
                    'sucesso': True,
                    'formato_aceito': variante,
                    'mensagem': f'Telefone aceito (keyboard): {variante}'
                }

            if val.strip():
                # Tem valor mas inválido — verificar se erro é visível
                tem_erro = _verificar_erro_validacao_telefone(driver)
                if not tem_erro:
                    logger.info("[Telefone] ✅ Sem erro visível (keyboard): '%s'", variante)
                    return {
                        'sucesso': True,
                        'formato_aceito': variante,
                        'mensagem': f'Telefone aceito (keyboard, sem erro): {variante}'
                    }

        except Exception as e:
            logger.warning("[Telefone] Erro keyboard para '%s': %s", variante, e)

    logger.error("[Telefone] Todas as %d tentativas falharam", total_tentativas)
    return {
        'sucesso': False,
        'mensagem': f'Nenhuma variante aceita após {total_tentativas} tentativas'
    }


def _encontrar_input_por_contexto(driver, labels, placeholders=None):
    """
    Encontra um input pelo contexto (aria-label, placeholder, label adjacente).
    Retorna o ElementHandle nativo ou None.

    Estratégia multi-nível:
    1. aria-label exato
    2. placeholder
    3. Label/span adjacente no DOM
    """
    # 1. Tentar por aria-label
    for label in labels:
        try:
            el = driver.query_selector(f'input[aria-label="{label}"]')
            if el:
                return el
            el = driver.query_selector(f'input[aria-label*="{label}"]')
            if el:
                return el
        except Exception:
            pass

    # 2. Tentar por placeholder
    all_placeholders = placeholders or labels
    for ph in all_placeholders:
        try:
            el = driver.query_selector(f'input[placeholder="{ph}"]')
            if el:
                return el
            el = driver.query_selector(f'input[placeholder*="{ph}"]')
            if el:
                return el
        except Exception:
            pass

    # 3. Tentar via texto do label adjacente no DOM
    try:
        all_inputs = driver.query_selector_all(
            '[role="dialog"] input[type="text"], [role="dialog"] input:not([type])')
        if not all_inputs:
            all_inputs = driver.query_selector_all('input[type="text"], input:not([type])')

        for inp in all_inputs:
            try:
                context = inp.evaluate('''el => {
                    let info = {
                        placeholder: (el.placeholder || "").toLowerCase(),
                        ariaLabel: (el.getAttribute("aria-label") || "").toLowerCase(),
                        parentText: ""
                    };
                    let p = el.parentElement;
                    for (let i = 0; i < 5 && p; i++) {
                        let lbl = p.querySelector("label, span");
                        if (lbl && lbl.textContent.trim().length > 0
                            && lbl.textContent.trim().length < 60) {
                            info.parentText = lbl.textContent.trim().toLowerCase();
                            break;
                        }
                        p = p.parentElement;
                    }
                    return info;
                }''')

                for label in labels:
                    ll = label.lower()
                    if (ll in context.get('ariaLabel', '') or
                            ll in context.get('placeholder', '') or
                            ll in context.get('parentText', '')):
                        return inp
            except Exception:
                continue
    except Exception:
        pass

    return None


def _encontrar_input_por_indice_no_modal(driver, indice):
    """Encontra um input pela posição (índice) dentro do modal/dialog."""
    try:
        inputs = driver.query_selector_all(
            '[role="dialog"] input[type="text"], [role="dialog"] input:not([type])')
        if not inputs:
            inputs = driver.query_selector_all(
                'form input[type="text"], form input:not([type])')
        if inputs and indice < len(inputs):
            return inputs[indice]
    except Exception:
        pass
    return None


# ============================================================================
# NOME DA BM — Abreviação Inteligente
# ============================================================================

def gerar_nome_bm_abreviado(razao_social):
    """
    Gera nome abreviado para BM a partir da razão social.
    Retorna lista de tentativas em ordem de preferência:

    "Luciana Helena Rodrigues da Cruz" ->
      1. "Luciana H. R. da Cruz"   (abreviado com pontos)
      2. "Luciana H R da Cruz"     (abreviado sem pontos)
      3. "Luciana Cruz"            (primeiro + último sobrenome)

    Remove sufixos empresariais como LTDA, MEI, ME, EIRELI, S/A, etc.
    """
    if not razao_social:
        return [razao_social or '']

    # Limpar sufixos empresariais
    sufixos = r'\b(LTDA|ME|MEI|EIRELI|EPP|S/?A|S\.A\.|SOCIEDADE\s+LIMITADA|EMPRESA\s+INDIVIDUAL)\b'
    nome = re.sub(sufixos, '', razao_social, flags=re.IGNORECASE).strip()
    nome = re.sub(r'[\s\-]+$', '', nome).strip()
    nome = re.sub(r'\s{2,}', ' ', nome)

    if not nome:
        return [razao_social]

    partes = nome.split()
    if len(partes) <= 2:
        return [nome]

    preps = {'da', 'de', 'do', 'das', 'dos', 'e'}

    primeiro = partes[0]

    # Encontrar o último sobrenome que não é preposição
    idx_ultimo = len(partes) - 1
    while idx_ultimo > 0 and partes[idx_ultimo].lower() in preps:
        idx_ultimo -= 1
    ultimo = partes[idx_ultimo]

    # Partes do meio (entre primeiro e último sobrenome)
    meio = partes[1:idx_ultimo]

    # Preposições logo antes do último sobrenome
    i = idx_ultimo - 1
    while i > 0 and partes[i].lower() in preps:
        i -= 1
    preps_finais = [p for p in partes[i + 1:idx_ultimo] if p.lower() in preps]

    # Versão 1: Abreviado com pontos - "Luciana H. R. da Cruz"
    medio_abrev_dots = []
    for p in meio:
        if p.lower() in preps:
            continue
        medio_abrev_dots.append(f"{p[0].upper()}.")

    v1_partes = [primeiro] + medio_abrev_dots
    if preps_finais:
        v1_partes += [p.lower() for p in preps_finais]
    v1_partes.append(ultimo)
    v1 = ' '.join(v1_partes)

    # Versão 2: Abreviado sem pontos - "Luciana H R da Cruz"
    medio_abrev_no_dots = []
    for p in meio:
        if p.lower() in preps:
            continue
        medio_abrev_no_dots.append(p[0].upper())

    v2_partes = [primeiro] + medio_abrev_no_dots
    if preps_finais:
        v2_partes += [p.lower() for p in preps_finais]
    v2_partes.append(ultimo)
    v2 = ' '.join(v2_partes)

    # Versão 3: Primeiro + último SEM preposições - "Luciana Cruz"
    v3 = f"{primeiro} {ultimo}"

    resultado = []
    for v in [v1, v2, v3]:
        v_limpo = v.strip()[:48].strip()
        if v_limpo and v_limpo not in resultado:
            resultado.append(v_limpo)

    return resultado if resultado else [razao_social[:48]]


def _gerar_nome_titlecase(texto):
    """
    Title Case PT-BR para o NOME DA BM: 1ª letra de cada palavra MAIÚSCULA e o
    resto minúsculo, com preposições (de/do/da/dos/das/e...) minúsculas.
    Ex.: "LUIZ FERNANDO DE SANTANA" -> "Luiz Fernando de Santana".
    O Facebook REJEITA nomes TODOS em maiúsculo — por isso normalizamos sempre.
    """
    if not texto:
        return ''
    preps = {'da', 'de', 'do', 'das', 'dos', 'e', 'em', 'na', 'no', 'a', 'o'}
    out = []
    for idx, p in enumerate(str(texto).strip().split()):
        pl = p.lower()
        if idx > 0 and pl in preps:
            out.append(pl)
        else:
            out.append(pl[:1].upper() + pl[1:])
    return ' '.join(out).strip()


def _candidatos_nome_portfolio(razao_social):
    """Gera os nomes candidatos p/ o portfólio, do MAIS COMPLETO ao mais curto
    (pedido do usuário: 'se a Meta não aceitar vai abreviando'):
      1) razão social completa (Title Case)
      2) primeiro + último nome principal  (ex.: 'Vinicius Oliveira')
      3) primeiro + segundo nome principal
      4) só o primeiro nome
    Ignora preposições (de/do/da...) ao escolher as palavras 'principais'."""
    base = _gerar_nome_titlecase(razao_social)
    if not base:
        return []
    preps = {'da', 'de', 'do', 'das', 'dos', 'e', 'em', 'na', 'no', 'a', 'o'}
    principais = [p for p in base.split() if p.lower() not in preps]
    cands = []

    def add(x):
        x = (x or '').strip()
        if x and len(x) >= 2 and x not in cands:
            cands.append(x)

    add(base)
    if len(principais) >= 2:
        add(f"{principais[0]} {principais[-1]}")
        add(f"{principais[0]} {principais[1]}")
    add(principais[0] if principais else base.split()[0])
    return cands[:4]


def _dialogo_editar_portfolio_aberto(driver):
    """True se o popup 'Editar informações do portfólio' ainda está aberto (usado
    p/ detectar rejeição: se após Salvar ele CONTINUA aberto, a Meta não aceitou o
    nome). Fechou = nome aceito."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            const d = document.querySelector('[role="dialog"]');
            if (!d) return false;
            const t = (d.innerText||'').toLowerCase();
            return t.includes('editar informações do portfólio') ||
                   t.includes('editar informacoes do portfolio') ||
                   t.includes('nome da empresa') ||
                   t.includes('foto do portfólio') || t.includes('foto do portfolio') ||
                   t.includes('edit business portfolio') || t.includes('business name');
        }"""))
    except Exception:
        return False


def _atualizar_nome_portfolio(driver, razao_social, callback_status=None):
    """
    Abre o PRIMEIRO botão 'Editar' (Informações do portfólio empresarial) e
    ajusta o 'Nome da empresa' para a RAZÃO SOCIAL em Title Case (1ª maiúscula,
    resto minúsculo — o Facebook rejeita tudo em maiúsculo). Se a Meta NÃO aceitar
    o nome (o popup continua aberto após Salvar), tenta ABREVIAÇÕES cada vez mais
    curtas (razão completa → 1º+último → 1º+2º → só 1º). Deixa 'Página principal'
    em branco. Best-effort: NÃO quebra o fluxo se algo falhar. Retorna True se
    conseguiu salvar algum dos nomes.
    """
    candidatos = _candidatos_nome_portfolio(razao_social)
    if not candidatos:
        return False
    try:
        if callback_status:
            callback_status(f"✏️ Ajustando nome da BM para: {candidatos[0]}")

        botoes = _encontrar_botoes_editar(driver)
        if not botoes:
            logger.warning("[Verificação] Nenhum botão Editar para o nome do portfólio.")
            return False

        # O 1º Editar (mais acima) = "Informações do portfólio" (nome da BM).
        _clicar_humano(driver, botoes[0])
        if not _aguardar_popup(driver, timeout=10):
            logger.warning("[Verificação] Popup 'Informações do portfólio' não abriu.")
            return False
        _delay_medio()

        for idx, nome in enumerate(candidatos):
            campo = _encontrar_input_por_contexto(
                driver,
                labels=['nome da empresa', 'nome do portfólio', 'nome do portfolio',
                        'business name', 'portfolio name', 'company name'],
                placeholders=['nome da empresa', 'business name'],
            )
            if not campo:
                # FALLBACK ESTRUTURAL (idioma-agnóstico): o 1º input de texto do
                # diálogo "Informações do portfólio" é o campo Nome da empresa.
                try:
                    driver.evaluate_page("""() => {
                        document.querySelectorAll('[data-nome-portfolio]').forEach(e=>e.removeAttribute('data-nome-portfolio'));
                        const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
                        if(!dlg) return;
                        const inp=[...dlg.querySelectorAll('input[type=text],input:not([type])')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0&&!el.disabled;})
                            .sort((a,b)=>a.getBoundingClientRect().top-b.getBoundingClientRect().top)[0];
                        if(inp) inp.setAttribute('data-nome-portfolio','1');
                    }""")
                    campo = driver.query_selector('[data-nome-portfolio="1"]')
                except Exception:
                    campo = None
            if not campo:
                logger.warning("[Verificação] Campo 'Nome da empresa' não encontrado.")
                break

            if idx > 0 and callback_status:
                callback_status(f"✂️ Meta não aceitou — tentando abreviar: {nome}")
            _limpar_e_digitar(driver, campo, nome, 'nome da empresa')
            _delay_curto()

            if not _clicar_botao_salvar(driver):
                # Salvar desabilitado (nome vazio/igual?) — tenta a próxima variante.
                logger.info("[Verificação] Salvar (nome) não acionou p/ '%s' — próxima.", nome)
                continue

            # Aceito = o popup FECHA. Rejeitado = continua aberto (com erro inline).
            _fim = time.time() + 5
            while time.time() < _fim:
                if not _dialogo_editar_portfolio_aberto(driver):
                    logger.info("[Verificação] Nome da BM salvo: '%s'.", nome)
                    return True
                time.sleep(0.1)
            logger.info("[Verificação] Meta não aceitou o nome '%s' — abreviando.", nome)

        logger.warning("[Verificação] Nenhuma variante do nome foi aceita.")
        _fechar_popup(driver)
        return False
    except Exception as e:
        logger.warning("[Verificação] Erro ao ajustar nome do portfólio: %s", e)
        try:
            _fechar_popup(driver)
        except Exception:
            pass
        return False


# ============================================================================
# FECHAR OVERLAYS / POPUPS QUE BLOQUEIAM A PÁGINA
# ============================================================================

def _fechar_overlays_facebook(driver):
    """
    Fecha popups/overlays do Facebook que bloqueiam os botões Editar.

    Popups comuns:
    - "Edite quais ferramentas você vê neste painel" (com botão Avançar)
    - "Alternar entre seus perfis de usuário" (com botão Concluir)
    - Banners de cookies / consentimento
    - Popups de introdução / tour guiado
    """
    textos_fechar = [
        'concluir', 'avançar', 'got it', 'ok', 'entendi', 'pular',
        'skip', 'dismiss', 'close', 'fechar', 'não agora', 'not now',
        'maybe later', 'talvez depois', 'done', 'next',
    ]

    fechados = 0

    # Fase 1: Fechar popups com botões de texto (Concluir, Avançar, etc.)
    for _ in range(5):  # Até 5 popups empilhados
        try:
            encontrou = driver.evaluate_page("""(textos) => {
                /* Procurar botões visíveis com texto de fechar */
                var buttons = document.querySelectorAll(
                    '[role="button"], button, [role="dialog"] [role="button"]');
                for (var i = 0; i < buttons.length; i++) {
                    var btn = buttons[i];
                    var rect = btn.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    var txt = (btn.innerText || '').trim().toLowerCase();
                    for (var j = 0; j < textos.length; j++) {
                        if (txt === textos[j]) {
                            btn.click();
                            return txt;
                        }
                    }
                }
                return null;
            }""", textos_fechar)

            if encontrou:
                fechados += 1
                logger.info("[Verificação] Overlay fechado: '%s'", encontrou)
                _delay(0.8, 1.5)
            else:
                break
        except Exception:
            break

    # Fase 2: Fechar botões X (close) em overlays/tooltips
    try:
        close_btns = driver.evaluate_page("""() => {
            var closed = 0;
            /* Botões com aria-label Close/Fechar */
            var xBtns = document.querySelectorAll(
                '[aria-label="Close"], [aria-label="Fechar"], ' +
                '[aria-label="Dismiss"], [aria-label="Dispensar"]');
            for (var x = 0; x < xBtns.length; x++) {
                var r = xBtns[x].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    xBtns[x].click();
                    closed++;
                }
            }

            /* Tooltips / popover close buttons (ícone X genérico) */
            var svgBtns = document.querySelectorAll(
                '[data-testid="close-button"], ' +
                '[class*="dismiss"], [class*="close-btn"]');
            for (var s = 0; s < svgBtns.length; s++) {
                var sr = svgBtns[s].getBoundingClientRect();
                if (sr.width > 0 && sr.height > 0) {
                    svgBtns[s].click();
                    closed++;
                }
            }
            return closed;
        }""")
        if close_btns and close_btns > 0:
            fechados += close_btns
            _delay(0.5, 1.0)
    except Exception:
        pass

    # Fase 3: Escape como último recurso
    if fechados == 0:
        try:
            driver.keyboard.press('Escape')
            _delay(0.3, 0.6)
        except Exception:
            pass

    if fechados > 0:
        logger.info("[Verificação] Total de overlays fechados: %d", fechados)


# ============================================================================
# FLUXO 1: INFORMAÇÕES DA EMPRESA (popup Informações do portfólio + Detalhes)
# ============================================================================

def _email_pendente_confirmacao(driver):
    """True se a página business_info mostra 'Confirm email address' (e-mail da
    BM ainda PENDENTE de confirmação)."""
    try:
        return bool(driver.evaluate_page("""() => {
            const t = (document.body.innerText || '').toLowerCase();
            return t.includes('confirm email address') || t.includes('confirme o endere')
                || t.includes('confirmar endere') || t.includes('confirme seu e-mail');
        }"""))
    except Exception:
        return False


def _email_pendente_endereco(driver):
    """Extrai o e-mail (da BM) associado ao 'Confirm email address' na página."""
    try:
        return (driver.evaluate_page(r"""() => {
            const body = document.body.innerText || '';
            const idx = body.search(/confirm email address|confirme o endere/i);
            const trecho = idx > 0 ? body.slice(Math.max(0, idx - 220), idx) : body;
            const re = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;
            const m = trecho.match(re) || body.match(re);
            return m ? m[0] : '';
        }""") or '').strip()
    except Exception:
        return ''


def _pedir_codigo_confirmacao_email(driver):
    """Faz o FB ENVIAR o código de confirmação do e-mail e ABRIR a popup do código.

    Usa CLIQUES REAIS (Playwright/CDP, trusted) — os menus/itens do FB ignoram
    cliques SINTÉTICOS (isTrusted=false), por isso o JS-dispatch parava no menu
    aberto sem enviar. Só retorna True quando a popup (campo de 6 dígitos) abre."""
    def _popup_ok(n=6):
        for _ in range(int(n)):
            _delay_curto()
            if _popup_codigo_aberto(driver):
                return True
        return False
    def _clicar_real(textos):
        # Clique REAL (trusted) por texto via `_clicar_botao` (tenta [role=button]
        # e, no fallback, o locator de texto do Playwright → pega até [role=menuitem]).
        # É o que faz o FB ACEITAR o clique (o dispatch JS sintético era ignorado).
        for _t in textos:
            try:
                if _clicar_botao(driver, _t):
                    return True
            except Exception:
                pass
        return False
    try:
        # CAMINHO A — clique REAL na pílula/botão "Confirmar endereço de email"
        # (abre a popup do código + envia o código). Direto e confiável.
        if _clicar_real(['Confirmar endereço de email', 'Confirmar endereco de email',
                         'Confirm email address', 'Confirme o endereço de e-mail']):
            if _popup_ok():
                return True
        # CAMINHO B — abre o menu "..." e clica o item com CLIQUE REAL (trusted).
        abriu = driver.evaluate_page("""() => {
            function vis(el){ if(!el) return false; const r=el.getBoundingClientRect();
                const s=getComputedStyle(el);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; }
            const botoes = Array.from(document.querySelectorAll('[role="button"][aria-haspopup="menu"]')).filter(vis);
            let alvo=null;
            for(const b of botoes){
                const lbl=((b.getAttribute('aria-label')||'')+' '+(b.innerText||'')).toLowerCase();
                if(lbl.includes('update email')||(lbl.includes('atualizar')&&lbl.includes('mail'))){ alvo=b; break; }
            }
            if(!alvo){
                const all=Array.from(document.querySelectorAll('*'));
                const pill=all.find(e=>/confirm email address|confirme o endere/i.test(e.textContent||'')&&vis(e)&&e.children.length<3);
                if(pill){ let c=pill; for(let i=0;i<6&&c;i++){ c=c.parentElement;
                    const b=c&&c.querySelector('[role="button"][aria-haspopup="menu"]');
                    if(b&&vis(b)){ alvo=b; break; } } }
            }
            if(!alvo) return false;
            try{ alvo.scrollIntoView({block:'center'}); }catch(e){}
            alvo.click(); return true;
        }""")
        if not abriu:
            return False
        _delay_medio()
        # Clique REAL (trusted) no item do menu — é o que DISPARA o envio no FB.
        if _clicar_real(['Receber código de confirmação', 'Receber codigo de confirmacao',
                         'Get confirmation code', 'Obter código de confirmação']):
            if _popup_ok():
                return True
        # Fallback: JS-dispatch no item (caso o clique real não ache o alvo).
        clicou = driver.evaluate_page("""() => {
            function vis(el){ if(!el) return false; const r=el.getBoundingClientRect();
                const s=getComputedStyle(el);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; }
            const itens = Array.from(document.querySelectorAll('[role="menuitem"], [role="menuitemradio"], [role="button"], div, span')).filter(vis);
            // do MAIS específico (texto curto) pro container, p/ pegar o ITEM e não
            // um wrapper que engloba o menu inteiro.
            itens.sort((a,b)=>((a.innerText||'').length)-((b.innerText||'').length));
            for(const it of itens){
                const t=(it.innerText||'').trim().toLowerCase();
                if(t==='get confirmation code' || t==='obter código de confirmação'
                   || t==='receber código de confirmação' || t==='receber codigo de confirmacao'
                   || (t.includes('confirmation code') && t.length<44)
                   || ((t.includes('código de confirma')||t.includes('codigo de confirma')) && t.length<44)){
                    // Clique ROBUSTO: itens de menu do React do FB muitas vezes só
                    // disparam com a sequência mousedown/mouseup/click (o .click()
                    // puro NÃO abria a popup → o bot parava no menu aberto).
                    try{ it.scrollIntoView({block:'center'}); }catch(_){}
                    const r=it.getBoundingClientRect();
                    const opts={bubbles:true,cancelable:true,view:window,clientX:r.left+r.width/2,clientY:r.top+r.height/2};
                    for(const ev of ['mouseover','mousedown','mouseup','click']){ try{ it.dispatchEvent(new MouseEvent(ev,opts)); }catch(_){} }
                    try{ it.click(); }catch(_){}
                    return true;
                }
            }
            return false;
        }""")
        if clicou and _popup_ok():
            return True
        # FALLBACK: clicar direto no botão/pílula visível 'Confirmar endereço de
        # email' / 'Confirm email address' (abre o mesmo popup de código).
        clicou2 = driver.evaluate_page("""() => {
            function vis(el){ if(!el) return false; const r=el.getBoundingClientRect();
                const s=getComputedStyle(el);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; }
            const alvos=['confirmar endereço de email','confirmar endereco de email',
                         'confirm email address','confirme o endereço de e-mail',
                         'confirme o endereco de e-mail'];
            const els=[...document.querySelectorAll('[role="button"], a, span, div')].filter(vis);
            els.sort((a,b)=>((a.innerText||'').length)-((b.innerText||'').length));
            for(const e of els){ const t=((e.innerText||'')+'').trim().toLowerCase();
                if(alvos.includes(t) || (t.length<=30 && alvos.some(a=>t.includes(a)))){
                    try{ e.click(); }catch(_){}
                    const r=e.getBoundingClientRect();
                    const opts={bubbles:true,cancelable:true,view:window,clientX:r.left+r.width/2,clientY:r.top+r.height/2};
                    for(const ev of ['mousedown','mouseup','click']){ try{ e.dispatchEvent(new MouseEvent(ev,opts)); }catch(_){} }
                    return true;
                }
            }
            return false;
        }""")
        return bool(clicou2)
    except Exception as e:
        logger.warning("[Email código] pedir código falhou: %s", e)
        return False


def _popup_codigo_aberto(driver):
    """True se o popup 'Enter confirmation code' / 'Código de confirmação' está
    aberto (tem o campo de 6 dígitos visível)."""
    try:
        return bool(driver.evaluate_page("""() => {
            function vis(el){ if(!el) return false; const r=el.getBoundingClientRect();
                const s=getComputedStyle(el);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; }
            const dlgs=[...document.querySelectorAll('[role="dialog"]')].filter(vis);
            for(const d of dlgs){
                const t=(d.innerText||'').toLowerCase();
                const temCampo=!!d.querySelector('input[autocomplete="one-time-code"], input[inputmode="numeric"], input[type="text"], input:not([type])');
                if(temCampo && (t.includes('confirmation code')||t.includes('código de confirma')||t.includes('codigo de confirma')||t.includes('6 dígitos')||t.includes('6 digitos')||t.includes('6-digit'))) return true;
            }
            return false;
        }"""))
    except Exception:
        return False


def _reenviar_codigo_no_popup(driver):
    """Com o popup de código ABERTO, clica em 'Reenviar código' (resend) DENTRO
    dele para o FB mandar um novo código — sem reabrir o menu '...'. Dispara o
    clique por JS (ignora overlay). Retorna True se clicou."""
    try:
        return bool(driver.evaluate_page("""() => {
            function vis(el){ if(!el) return false; const r=el.getBoundingClientRect();
                const s=getComputedStyle(el);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; }
            const dlgs=[...document.querySelectorAll('[role="dialog"]')].filter(vis);
            const dlg=dlgs.length?dlgs[dlgs.length-1]:null;
            if(!dlg) return false;
            const txt=(dlg.innerText||'').toLowerCase();
            if(!(txt.includes('confirmation code')||txt.includes('código de confirma')||txt.includes('codigo de confirma')||txt.includes('6 dígitos')||txt.includes('6 digitos'))) return false;
            const alvos=['reenviar código','reenviar codigo','reenviar','resend code','resend','enviar novamente','send again'];
            const els=[...dlg.querySelectorAll('[role="button"], a, span, div')].filter(vis);
            // do MAIS específico (texto curto exato) pro container
            els.sort((a,b)=>((a.innerText||'').length)-((b.innerText||'').length));
            for(const e of els){ const t=((e.innerText||'')+'').trim().toLowerCase();
                if(alvos.includes(t) || (t.length<=18 && alvos.some(a=>t.includes(a)))){
                    try{ e.click(); }catch(_){}
                    const r=e.getBoundingClientRect();
                    const opts={bubbles:true,cancelable:true,view:window,clientX:r.left+r.width/2,clientY:r.top+r.height/2};
                    for(const ev of ['mousedown','mouseup','click']){ try{ e.dispatchEvent(new MouseEvent(ev,opts)); }catch(_){} }
                    return true;
                }
            }
            return false;
        }"""))
    except Exception as e:
        logger.warning("[Email código] reenviar no popup falhou: %s", e)
        return False


def _digitar_codigo_confirmacao(driver, codigo):
    """Digita o código no diálogo de confirmação e clica em confirmar/enviar."""
    try:
        _delay_medio()
        el = driver.query_selector(
            '[role="dialog"] input[autocomplete="one-time-code"], '
            '[role="dialog"] input[inputmode="numeric"], '
            '[role="dialog"] input[type="text"], '
            '[role="dialog"] input:not([type])')
        if not el:
            el = driver.query_selector('input[autocomplete="one-time-code"], input[inputmode="numeric"]')
        if el:
            _limpar_e_digitar(driver, el, codigo, 'código de confirmação')
            _delay_medio()
        driver.evaluate_page("""() => {
            const dlg=document.querySelector('[role="dialog"]')||document;
            const btns=Array.from(dlg.querySelectorAll('[role="button"], button'));
            const ok=['confirm','confirmar','submit','enviar','done','concluir','verify',
                      'verificar','continue','continuar','save','salvar','ok'];
            for(const b of btns){ const t=(b.innerText||'').trim().toLowerCase();
                if(ok.includes(t)){ b.click(); return true; } }
            return false;
        }""")
        return True
    except Exception as e:
        logger.warning("[Email código] digitar código falhou: %s", e)
        return False


def confirmar_email_bm_via_codigo(driver, callback_status=None, max_tentativas=3):
    """Se o e-mail da BM está PENDENTE (selo 'Confirm email address') na página
    business_info, confirma via 'Get confirmation code': pede o código, lê no
    GSMAILS e digita. Tenta até `max_tentativas`. Best-effort — se não der em
    nenhuma das tentativas, retorna False e o fluxo SEGUE normalmente."""
    try:
        if not _email_pendente_confirmacao(driver):
            return True  # já confirmado / sem pendência
        email_addr = _email_pendente_endereco(driver)
        if not email_addr:
            return False
        try:
            from server.gsmails_integration import gsmails_enabled, wait_code
        except Exception:
            return False
        if not gsmails_enabled():
            return False

        for tent in range(1, max_tentativas + 1):
            if callback_status:
                callback_status(f"✉️ Confirmando e-mail da BM por código ({tent}/{max_tentativas})...")
            # 1ª vez: abre o menu '...' → 'Get confirmation code' (abre o popup e
            # ENVIA o 1º código). Tentativas seguintes: se o popup ainda está
            # aberto, clica 'Reenviar código' DENTRO dele (sem reabrir o menu, que
            # fica ATRÁS do popup); só reabre pelo menu se o popup tiver fechado.
            if tent == 1:
                if not _pedir_codigo_confirmacao_email(driver):
                    logger.info("[Email código] 'Get confirmation code' não encontrado — segue fluxo.")
                    return False
            else:
                if _popup_codigo_aberto(driver) and _reenviar_codigo_no_popup(driver):
                    if callback_status:
                        callback_status("🔁 Reenviando código de confirmação do e-mail...")
                    _delay_medio()
                elif not _pedir_codigo_confirmacao_email(driver):
                    logger.info("[Email código] não consegui pedir/reenviar o código — segue fluxo.")
                    return False
            # Espera CURTA pelo código a cada tentativa: MÁX ~20s por reenvio
            # (pedido do usuário 2026-07-07). O daemon do GSMAILS entrega em tempo
            # real quando saudável e o wait faz polling (retorna NA HORA em que
            # chega). Se não vier em 20s, a próxima volta do laço clica 'Reenviar
            # código'; esgotando as 3 tentativas, PULA e segue o fluxo.
            codigo = wait_code(email_addr, from_filter="facebook", timeout=14)
            if not codigo:
                codigo = wait_code(email_addr, from_filter="", timeout=6)
            if codigo:
                _digitar_codigo_confirmacao(driver, codigo)
                _delay_longo()
                if not _email_pendente_confirmacao(driver):
                    if callback_status:
                        callback_status("✅ E-mail da BM confirmado por código!")
                    return True
            # NÃO fecha o popup entre tentativas — o 'Reenviar código' precisa dele
            # aberto. Só dá uma pausa e tenta de novo (reenviar/digitar).
            _delay_medio()
        if callback_status:
            callback_status("⚠️ E-mail não confirmado em 3 tentativas — seguindo o fluxo.")
        return False
    except Exception as e:
        logger.warning("[Email código] erro geral: %s", e)
        try:
            _fechar_overlays_facebook(driver)
        except Exception:
            pass
        return False


def preencher_info_empresa(driver, business_id, empresa_dados, callback_status=None,
                           variantes_telefone=None):
    """
    Preenche as informações da empresa no Facebook Business Manager.

    NÃO abre o popup "Informações do portfólio" (1º Editar) — ao criar a BM
    o nome da empresa já fica correto, e a "Página principal" não precisa de valor.

    Abre DIRETAMENTE o popup "Editar detalhes da empresa" (botão Editar
    na seção "Detalhes da empresa") e preenche:
      - Razão social (Nome legal)
      - País: Brasil
      - Endereço (rua + número)
      - Cidade
      - Estado (UF)
      - CEP
      - Telefone  ← React Native Setter com variantes
      - Site (URL)
      - CNPJ (Número de identificação fiscal / EIN)

    O telefone é preenchido com método robusto (React Native Setter + variantes)
    porque o botão Salvar SÓ ATIVA quando TODOS os campos estão preenchidos.

    Args:
        variantes_telefone: Lista de variantes de formato do telefone.

    Returns:
        dict: {'sucesso': bool, 'mensagem': str}
    """
    if callback_status:
        callback_status("📋 Acessando informações da empresa...")

    try:
        # ===== NAVEGAR para a página de informações =====
        url_info = (
            f"https://business.facebook.com/latest/settings/business_info"
            f"?business_id={business_id}"
        )
        driver.goto(url_info)
        _esperar_pagina(driver, 30)
        _delay_longo()

        # Aguardar que a seção "Detalhes da empresa" esteja visível na página
        _aguardar_elemento(driver, '[role="button"]', timeout=20,
                           descricao='Botões da página business_info')
        _delay_leitura()

        # ===== FECHAR popups/overlays que bloqueiam os botões =====
        _fechar_overlays_facebook(driver)
        _delay_medio()

        # ===== CONFIRMAR E-MAIL DA BM (se pendente) via 'Get confirmation code' =====
        # BEST-EFFORT (pedido do usuário 2026-07-07): pede o código e REENVIA até 3x,
        # esperando no MÁXIMO ~20s por reenvio. Se não chegar nas 3, NÃO erra/trava —
        # SEGUE o fluxo de verificação normalmente. (Se a WABA nascer desabilitada por
        # falta do e-mail, o fluxo alternativo cria uma conta de anúncios e destrava a
        # Central — ver executar_etapa_verificacao_negocio.) Se já está confirmado, ok.
        try:
            confirmar_email_bm_via_codigo(driver, callback_status, max_tentativas=3)
            _delay_medio()
            _fechar_overlays_facebook(driver)
            _delay_curto()
        except Exception as _e:
            logger.warning("[Email código] etapa best-effort falhou: %s", _e)

        # ================================================================
        # 1º EDITAR: ajustar o NOME DA BM = Razão Social em Title Case
        # (1ª letra maiúscula, resto minúsculo — FB rejeita tudo maiúsculo).
        # ================================================================
        razao_social = empresa_dados.get('razao_social', '')
        if razao_social:
            _atualizar_nome_portfolio(driver, razao_social, callback_status)
            _delay_medio()
            # Reabrir/garantir a página estável e fechar overlays antes do 2º Editar
            _fechar_overlays_facebook(driver)
            _delay_curto()

        # ================================================================
        # 2º EDITAR: "Editar detalhes da empresa" (razão social + país +
        # endereço + cidade + estado + CEP + telefone + site + CNPJ).
        # ================================================================
        if callback_status:
            callback_status("🏢 Localizando botão 'Editar detalhes da empresa'...")

        # Scroll para garantir que a seção "Detalhes da empresa" está visível
        _scroll_suave(driver, 'baixo', 350)
        _delay_medio()

        btn_detalhes = _encontrar_botao_editar_detalhes(driver)

        if not btn_detalhes:
            # Se não encontrou, fazer mais scroll e tentar novamente
            _scroll_suave(driver, 'baixo', 400)
            _delay_medio()
            btn_detalhes = _encontrar_botao_editar_detalhes(driver)

        if not btn_detalhes:
            # Fallback: pegar o ÚLTIMO botão "Editar" (é sempre o de "Detalhes da empresa")
            # A página tem até 4 botões Editar; o correto é o último (mais abaixo na página)
            botoes = _encontrar_botoes_editar(driver)
            if botoes:
                btn_detalhes = botoes[-1]  # Último botão = Detalhes da empresa

        if not btn_detalhes:
            logger.error("[Verificação] Botão 'Editar detalhes da empresa' não encontrado")
            return {'sucesso': False, 'mensagem': 'Botão Editar detalhes não encontrado'}

        logger.info("[Verificação] Botão Editar detalhes encontrado — clicando")
        _clicar_humano(driver, btn_detalhes)
        _delay_medio()
        _delay_leitura()

        # Verificar se abriu edição inline do nome (ERRADO) em vez de popup
        _inline_nome_aberto = driver.evaluate_page("""() => {
            // Se não há dialog mas há input com Cancelar/Salvar inline,
            // o clique ativou o editor de nome do portfólio (errado)
            var dialog = document.querySelector('[role="dialog"]');
            if (dialog) return false;  // popup abriu — ok
            var body = (document.body.innerText || '').toLowerCase();
            var temNomePortfolio = body.indexOf('nome do portfólio') !== -1
                || body.indexOf('portfolio name') !== -1
                || body.indexOf('nome do portfolio') !== -1;
            // Verificar se apareceu Cancelar + Salvar inline (sem dialog)
            var btns = document.querySelectorAll('[role="button"]');
            var temCancelar = false, temSalvar = false;
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].innerText || '').trim().toLowerCase();
                if (t === 'cancelar' || t === 'cancel') temCancelar = true;
                if (t === 'salvar' || t === 'save') temSalvar = true;
            }
            return temCancelar && temSalvar && !dialog;
        }""")

        if _inline_nome_aberto:
            logger.warning("[Verificação] Clicou no editor inline de nome do portfólio (ERRADO) — cancelando")
            # Clicar Cancelar para fechar o editor inline do nome
            try:
                driver.evaluate_page("""() => {
                    var btns = document.querySelectorAll('[role="button"]');
                    for (var i = 0; i < btns.length; i++) {
                        var t = (btns[i].innerText || '').trim().toLowerCase();
                        if (t === 'cancelar' || t === 'cancel') {
                            btns[i].click();
                            return true;
                        }
                    }
                    return false;
                }""")
            except Exception:
                pass
            _delay_medio()

            # Scroll mais para baixo e tentar o último botão Editar (= Detalhes)
            _scroll_suave(driver, 'baixo', 500)
            _delay_medio()

            # Tentar novamente com a função principal (que usa data-surface)
            btn_detalhes = _encontrar_botao_editar_detalhes(driver)
            if not btn_detalhes:
                # Fallback: último botão Editar
                botoes = _encontrar_botoes_editar(driver)
                if botoes:
                    btn_detalhes = botoes[-1]  # Último = Detalhes da empresa

            if btn_detalhes:
                logger.info("[Verificação] Tentando 2º botão Editar após cancelar inline")
                _clicar_humano(driver, btn_detalhes)
                _delay_medio()
                _delay_leitura()

        popup_aberto = _aguardar_popup(driver, timeout=10)

        if not popup_aberto:
            # Tentar clicar de novo
            _clicar_humano(driver, btn_detalhes)
            _delay_medio()
            popup_aberto = _aguardar_popup(driver, timeout=8)

        if not popup_aberto:
            logger.error("[Verificação] Popup de detalhes não abriu")
            return {'sucesso': False, 'mensagem': 'Popup de detalhes da empresa não abriu'}

        # Verificar se é o popup CORRETO ("Editar detalhes da empresa")
        popup_correto = _verificar_popup_detalhes(driver)
        if not popup_correto:
            logger.warning("[Verificação] Popup aberto mas não é 'Editar detalhes' — fechando e tentando outro")
            _fechar_popup(driver)
            _delay_medio()

            # Tentar próximo botão Editar
            botoes = _encontrar_botoes_editar(driver)
            if botoes:
                for btn in reversed(botoes):
                    _clicar_humano(driver, btn)
                    _delay_medio()
                    popup_aberto = _aguardar_popup(driver, timeout=6)
                    if popup_aberto and _verificar_popup_detalhes(driver):
                        popup_correto = True
                        break
                    if popup_aberto:
                        _fechar_popup(driver)
                        _delay_curto()

        if not popup_correto:
            return {'sucesso': False, 'mensagem': 'Não encontrou popup Editar detalhes da empresa'}

        if callback_status:
            callback_status("🏢 Preenchendo detalhes da empresa...")

        res_detalhes = _preencher_detalhes_empresa(driver, empresa_dados, callback_status,
                                                   variantes_telefone=variantes_telefone)
        # Se a função abortou (ex.: endereço REAL ausente), NÃO tentar salvar com
        # dados incompletos/fake — propaga a falha para estornar o token.
        if isinstance(res_detalhes, dict) and not res_detalhes.get('sucesso', True):
            return res_detalhes
        _delay_medio()

        if callback_status:
            callback_status("💾 Salvando detalhes da empresa...")

        # Tentar salvar até 3 vezes, verificando se o popup fechou
        for tentativa_salvar in range(3):
            salvou = _clicar_botao_salvar(driver)
            if not salvou:
                logger.warning("[Verificação] Botão Salvar não encontrado (tentativa %d)",
                               tentativa_salvar + 1)
                _delay_curto()
                continue

            _delay_longo()

            # Verificar se o popup fechou (indicando que o save foi bem-sucedido).
            # IDIOMA-AGNÓSTICO: o diálogo "Editar detalhes" é reconhecido pela ESTRUTURA
            # — tem o combobox de País (aria-haspopup=listbox) OU inputs marcados com
            # data-detalhe-campo. Não depende de texto ("razão social"/"endereço").
            popup_ainda_aberto = False
            try:
                popup_ainda_aberto = bool(driver.evaluate_page("""() => {
                    const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
                    if(!dlg) return false;
                    const temPais = !!dlg.querySelector('[role=combobox][aria-haspopup=listbox]');
                    const temCampos = dlg.querySelectorAll('[data-detalhe-campo]').length >= 2;
                    // um input de texto editável ainda presente também indica o form aberto
                    const temInputs = dlg.querySelectorAll('input[type=text],input:not([type]),textarea').length >= 3;
                    return temPais || temCampos || temInputs;
                }"""))
                if popup_ainda_aberto:
                    logger.warning("[Verificação] Popup ainda aberto após salvar — "
                                   "pode haver erro de validação")
            except Exception:
                pass

            if not popup_ainda_aberto:
                if callback_status:
                    callback_status("✅ Detalhes da empresa salvos com sucesso!")
                return {'sucesso': True, 'mensagem': 'Informações da empresa preenchidas'}

            # Popup ainda aberto — verificar se há erros de validação
            if callback_status:
                callback_status(f"⚠️ Popup não fechou — re-tentando salvar ({tentativa_salvar + 2}/3)...")
            _delay_medio()

        # Se chegou aqui, popup não fechou mas botão foi clicado
        logger.warning("[Verificação] Popup não fechou após 3 tentativas de salvar")
        return {'sucesso': True, 'mensagem': 'Campos preenchidos, popup não confirmou save'}

    except Exception as e:
        logger.error("[Verificação] Erro ao preencher info empresa: %s", e, exc_info=True)
        return {'sucesso': False, 'mensagem': f'Erro: {str(e)}'}


# ============================================================================
# HELPERS: Localizar botões e popups
# ============================================================================

def _encontrar_botoes_editar(driver):
    """
    Encontra todos os botões 'Editar' na página de Business Info.
    Retorna lista de ElementHandles ordenados por posição vertical.
    """
    botoes = []

    # Estratégia 1: role="button" com texto "Editar"
    try:
        candidatos = driver.query_selector_all('[role="button"]')
        for btn in candidatos:
            try:
                txt = (btn.text_content() or '').strip()
                if txt.lower() in ['editar', 'edit']:
                    botoes.append(btn)
            except Exception:
                continue
    except Exception:
        pass

    # Estratégia 2: span/div clicáveis com texto Editar
    if not botoes:
        try:
            candidatos = driver.query_selector_all('span, div')
            for el in candidatos:
                try:
                    txt = (el.text_content() or '').strip()
                    if txt.lower() in ['editar', 'edit']:
                        is_clickable = el.evaluate('''el => {
                            let style = window.getComputedStyle(el);
                            return style.cursor === "pointer" ||
                                   el.getAttribute("role") === "button" ||
                                   el.closest("[role='button']") !== null ||
                                   el.closest("a") !== null;
                        }''')
                        if is_clickable:
                            botoes.append(el)
                except Exception:
                    continue
        except Exception:
            pass

    # Ordenar por posição Y (top)
    if len(botoes) > 1:
        try:
            botoes_com_pos = []
            for btn in botoes:
                try:
                    box = btn.bounding_box()
                    y = box['y'] if box else 9999
                    botoes_com_pos.append((y, btn))
                except Exception:
                    botoes_com_pos.append((9999, btn))
            botoes_com_pos.sort(key=lambda x: x[0])
            botoes = [b for _, b in botoes_com_pos]
        except Exception:
            pass

    return botoes


def _encontrar_botao_editar_detalhes(driver):
    """
    Encontra o botão "Editar" específico da seção "Detalhes da empresa".

    A página business_info tem MÚLTIPLOS botões "Editar" (até 4):
      1º — Nome do portfólio empresarial (edição inline, sem popup)
      2º — Linha do portfólio com "Configurações da empresa" / "Excluir"
      3º — "Página principal: nenhuma" (popup errado)
      4º — "Detalhes da empresa" ← ESTE é o correto

    ESTRATÉGIA PRIMÁRIA: usar o atributo data-surface do Facebook que
    contém "edit-business-details" para identificar o botão exato.

    FALLBACK: Pegar o botão "Editar" que está na mesma linha vertical
    do texto "Detalhes da empresa".

    Marca o botão com data-btn-detalhes="1" e localiza via query_selector.
    Retorna: ElementHandle do botão ou None.
    """
    try:
        # Limpar marca anterior
        driver.evaluate_page("""() => {
            document.querySelectorAll('[data-btn-detalhes]').forEach(function(el) {
                el.removeAttribute('data-btn-detalhes');
            });
        }""")
    except Exception:
        pass

    # ═══════════════════════════════════════════════════════════════
    # ESTRATÉGIA 1: data-surface contendo "edit-business-details"
    # (seletor exato do DOM do Facebook — mais confiável)
    # ═══════════════════════════════════════════════════════════════
    try:
        resultado = driver.evaluate_page("""() => {
            // Procurar o span wrapper com data-surface contendo "edit-business-details"
            var surfaces = document.querySelectorAll('[data-surface*="edit-business-details"]');
            for (var s = 0; s < surfaces.length; s++) {
                // Dentro deste wrapper, encontrar o botão "Editar"/"Edit"
                var btns = surfaces[s].querySelectorAll('[role="button"]');
                for (var b = 0; b < btns.length; b++) {
                    var txt = (btns[b].innerText || '').trim().toLowerCase();
                    if (txt === 'editar' || txt === 'edit') {
                        var rect = btns[b].getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            btns[b].setAttribute('data-btn-detalhes', '1');
                            return true;
                        }
                    }
                }
                // Fallback: qualquer div clicável com texto "Editar" dentro do surface
                var divs = surfaces[s].querySelectorAll('div');
                for (var d = 0; d < divs.length; d++) {
                    var t = (divs[d].innerText || '').trim().toLowerCase();
                    if (t === 'editar' || t === 'edit') {
                        var parent = divs[d].closest('[role="button"]') || divs[d];
                        parent.setAttribute('data-btn-detalhes', '1');
                        return true;
                    }
                }
            }
            return false;
        }""")

        if resultado:
            btn = driver.query_selector('[data-btn-detalhes="1"]')
            if btn:
                logger.info("[Verificação] Botão Editar detalhes encontrado via data-surface")
                return btn
    except Exception as exc:
        logger.warning("[Verificação] Falha data-surface: %s", exc)

    # ═══════════════════════════════════════════════════════════════
    # ESTRATÉGIA 2: Botão "Editar" na mesma linha horizontal que
    # o texto "Detalhes da empresa" (mesmo Y ± 50px)
    # ═══════════════════════════════════════════════════════════════
    try:
        resultado = driver.evaluate_page("""() => {
            // Achar o heading "Detalhes da empresa" / "Company details"
            var headings = document.querySelectorAll('span, div, h2, h3, strong');
            var detalhesY = -1;
            for (var h = 0; h < headings.length; h++) {
                var txt = (headings[h].innerText || '').trim().toLowerCase();
                if (txt === 'detalhes da empresa' || txt === 'company details' ||
                    txt === 'business details') {
                    var rect = headings[h].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        detalhesY = rect.top;
                        break;
                    }
                }
            }
            if (detalhesY < 0) return false;

            // Achar o botão "Editar" mais próximo verticalmente
            var buttons = document.querySelectorAll('[role="button"]');
            var closest = null;
            var closestDist = Infinity;
            for (var b = 0; b < buttons.length; b++) {
                var bt = (buttons[b].innerText || '').trim().toLowerCase();
                if (bt === 'editar' || bt === 'edit') {
                    var rect = buttons[b].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        var dist = Math.abs(rect.top - detalhesY);
                        if (dist < closestDist && dist < 80) {
                            closestDist = dist;
                            closest = buttons[b];
                        }
                    }
                }
            }
            if (closest) {
                closest.setAttribute('data-btn-detalhes', '1');
                return true;
            }
            return false;
        }""")

        if resultado:
            btn = driver.query_selector('[data-btn-detalhes="1"]')
            if btn:
                logger.info("[Verificação] Botão Editar detalhes encontrado via proximidade ao heading")
                return btn
    except Exception as exc:
        logger.warning("[Verificação] Falha proximidade heading: %s", exc)

    # ═══════════════════════════════════════════════════════════════
    # ESTRATÉGIA 3: Último botão "Editar" na página
    # (o botão de "Detalhes da empresa" é sempre o último "Editar")
    # ═══════════════════════════════════════════════════════════════
    try:
        resultado = driver.evaluate_page("""() => {
            var buttons = document.querySelectorAll('[role="button"]');
            var editBtns = [];
            for (var b = 0; b < buttons.length; b++) {
                var bt = (buttons[b].innerText || '').trim().toLowerCase();
                if (bt === 'editar' || bt === 'edit') {
                    var rect = buttons[b].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        editBtns.push({el: buttons[b], y: rect.top});
                    }
                }
            }
            if (editBtns.length === 0) return false;

            // Ordenar por Y descendente — o último é o de "Detalhes da empresa"
            editBtns.sort(function(a, b) { return b.y - a.y; });
            editBtns[0].el.setAttribute('data-btn-detalhes', '1');
            return true;
        }""")

        if resultado:
            btn = driver.query_selector('[data-btn-detalhes="1"]')
            if btn:
                logger.info("[Verificação] Botão Editar detalhes encontrado como último Editar")
                return btn
    except Exception as exc:
        logger.warning("[Verificação] Falha último botão: %s", exc)

    return None


def _verificar_popup_detalhes(driver):
    """
    Verifica se o popup aberto é o "Editar detalhes da empresa"
    (e não "Informações do portfólio").

    O popup correto tem campos como: Razão social, País, Endereço, Cidade, CEP.
    O popup ERRADO tem apenas: Nome da empresa + Página principal.
    """
    # MÉTODO ESTRUTURAL (idioma-agnóstico): o diálogo "Editar detalhes" tem o
    # combobox de País (aria-haspopup=listbox) E vários inputs de texto (>=5).
    # O diálogo ERRADO (Informações do portfólio) tem ~2 inputs e NÃO tem o
    # combobox de País. Não depende de "razão social"/"cep"/"legal name".
    try:
        info = driver.evaluate_page("""() => {
            var dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(function(e){var r=e.getBoundingClientRect();return r.width>0&&r.height>0;});
            var dialog = dlgs[dlgs.length-1];
            if (!dialog) return {correto: false, motivo: 'sem dialog'};
            var temCombobox = !!dialog.querySelector('[role="combobox"][aria-haspopup="listbox"]');
            var inputs = [...dialog.querySelectorAll('input[type="text"], input:not([type]), input[type="tel"], input[type="url"], select')]
                .filter(function(el){var r=el.getBoundingClientRect();var t=(el.type||'').toLowerCase();
                    return r.width>0 && r.height>0 && t!=='hidden' && t!=='checkbox' && t!=='radio' && t!=='file';});
            var nInputs = inputs.length;
            // texto só como sinal SECUNDÁRIO negativo (identificar o portfólio errado)
            var txt = (dialog.innerText || '').toLowerCase();
            var ehPortfolio = txt.indexOf('foto do portfólio') !== -1
                || txt.indexOf('portfolio photo') !== -1
                || (nInputs <= 3 && !temCombobox);
            var correto = (temCombobox || nInputs >= 5) && !ehPortfolio;
            return {correto: correto, temCombobox: temCombobox, nInputs: nInputs, ehPortfolio: ehPortfolio};
        }""")
        if isinstance(info, dict):
            logger.info("[Verificação] Popup (estrutural): correto=%s combobox=%s inputs=%s portfolio=%s",
                        info.get('correto'), info.get('temCombobox'), info.get('nInputs'), info.get('ehPortfolio'))
            return bool(info.get('correto', False))
    except Exception as exc:
        logger.warning("[Verificação] Erro ao verificar popup: %s", exc)

    # Fallback final: contar inputs (detalhes tem 5+, portfólio tem ~2)
    try:
        count = driver.evaluate_page("""() => {
            var dialog = document.querySelector('[role="dialog"]');
            if (!dialog) return 0;
            var inputs = dialog.querySelectorAll('input[type="text"], input:not([type]), input[type="tel"], input[type="url"], select');
            return inputs.length;
        }""")
        if isinstance(count, (int, float)) and count >= 5:
            logger.info("[Verificação] Popup tem %d inputs — provavelmente detalhes", count)
            return True
    except Exception:
        pass

    return False


def _aguardar_popup(driver, timeout=10):
    """Aguarda um popup/dialog aparecer na tela."""
    try:
        driver.wait_for_selector('[role="dialog"]', timeout=timeout * 1000)
        _delay(0.5, 1.0)
        return True
    except Exception:
        try:
            driver.wait_for_selector('[aria-modal="true"]', timeout=3000)
            return True
        except Exception:
            pass
        try:
            overlay = driver.query_selector(
                'div[class*="modal"], div[class*="dialog"], div[class*="overlay"]')
            if overlay:
                return True
        except Exception:
            pass
    return False


def _fechar_popup(driver):
    """Fecha o popup atual (Cancelar, X, ou Escape)."""
    try:
        botoes = driver.query_selector_all('[role="dialog"] [role="button"]')
        for btn in botoes:
            txt = (btn.text_content() or '').strip().lower()
            if txt in ['cancelar', 'cancel', 'fechar', 'close']:
                btn.click()
                _delay_curto()
                return True
    except Exception:
        pass

    try:
        close_btn = driver.query_selector(
            '[role="dialog"] [aria-label="Close"], '
            '[role="dialog"] [aria-label="Fechar"]')
        if close_btn:
            close_btn.click()
            _delay_curto()
            return True
    except Exception:
        pass

    try:
        driver.keyboard.press('Escape')
        _delay_curto()
        return True
    except Exception:
        pass

    return False


def _verificar_nome_empresa_preenchido(driver):
    """
    Verifica se o campo 'Nome da empresa' no popup já tem valor preenchido.
    Se já tem a razão social, retorna True (não precisa salvar).
    """
    try:
        inputs = driver.query_selector_all(
            '[role="dialog"] input[type="text"], [role="dialog"] input:not([type])')
        for inp in inputs:
            try:
                ctx = inp.evaluate('''el => {
                    let val = el.value || "";
                    let label = (el.getAttribute("aria-label") || "").toLowerCase();
                    let ph = (el.placeholder || "").toLowerCase();
                    let parentLabel = "";
                    let p = el.parentElement;
                    for (let i = 0; i < 5 && p; i++) {
                        let lbl = p.querySelector("label, span");
                        if (lbl && lbl.textContent.trim().length > 2
                            && lbl.textContent.trim().length < 50) {
                            parentLabel = lbl.textContent.trim().toLowerCase();
                            break;
                        }
                        p = p.parentElement;
                    }
                    return {value: val, label: label, placeholder: ph, parentLabel: parentLabel};
                }''')

                is_nome = False
                for key in ['label', 'placeholder', 'parentLabel']:
                    txt = ctx.get(key, '')
                    if any(t in txt for t in [
                        'nome da empresa', 'business name', 'nome do portfólio',
                        'portfolio name'
                    ]):
                        is_nome = True
                        break

                if is_nome:
                    valor = (ctx.get('value', '') or '').strip()
                    if valor and len(valor) > 2:
                        logger.info("[Verificação] Nome da empresa já preenchido: '%s'", valor)
                        return True
                    return False
            except Exception:
                continue

        # Fallback: verificar primeiro input do popup
        if inputs:
            try:
                val = inputs[0].evaluate('el => el.value || ""') or ''
                if val.strip() and len(val.strip()) > 2:
                    logger.info("[Verificação] Primeiro input do popup tem valor: '%s'", val)
                    return True
            except Exception:
                pass
    except Exception as e:
        logger.error("[Verificação] Erro ao verificar nome empresa: %s", e)

    return False


# ============================================================================
# PREENCHER DETALHES DA EMPRESA (formulário completo)
# ============================================================================

def _preencher_detalhes_empresa(driver, empresa_dados, callback_status=None,
                                variantes_telefone=None):
    """
    Preenche todos os campos do formulário "Editar detalhes da empresa".

    Usa detecção em lote: um único JS marca todos os inputs do popup com
    data-detalhe-campo, depois preenche cada campo via query_selector.

    O campo de telefone recebe tratamento ESPECIAL via React Native Setter +
    checagem de aria-invalid, pois o Facebook valida o telefone em tempo real
    e o botão Salvar só ativa quando TODOS os campos (incluindo telefone)
    estão preenchidos corretamente.

    Ordem dos campos conforme Facebook Business (2026):
    1. Razão social (Nome legal da empresa)
    2. País -> Selecionar "Brasil" (dropdown, NÃO é input)
    3. Endereço (logradouro + número)
    4. Endereço (continuação) -> PULAR
    5. Cidade
    6. Estado (UF)
    7. CEP
    8. Telefone  ← React Native Setter + variantes
    9. Site
    10. CNPJ (Número de identificação fiscal / EIN)

    Args:
        driver: PlaywrightDriver
        empresa_dados: dict com dados da empresa
        callback_status: callback para progresso
        variantes_telefone: lista de variantes de formato do telefone
    """

    razao = empresa_dados.get('razao_social', '')
    logradouro = empresa_dados.get('logradouro', '')
    numero = empresa_dados.get('numero', '')
    bairro = empresa_dados.get('bairro', '')
    cidade = empresa_dados.get('municipio', '')
    estado = empresa_dados.get('uf', '')
    cep = empresa_dados.get('cep', '')
    telefone = empresa_dados.get('telefone', '')
    url_site = empresa_dados.get('url_completa', '')
    cnpj = empresa_dados.get('cnpj', '')

    # Montar endereço: logradouro + número (DADOS REAIS da Receita).
    # NUNCA inventar endereço fake ("Centro", "Centro de <cidade>", só a cidade,
    # etc.) — a Meta REJEITA a verificação quando o endereço não bate com o
    # registro oficial do CNPJ. Se não houver um logradouro real, ABORTAMOS a
    # etapa: é melhor falhar (e estornar o token) do que entregar uma BM que
    # será rejeitada por endereço falso. O logradouro real deve vir do painel.
    logradouro = (logradouro or '').strip()
    bairro = (bairro or '').strip()
    endereco = ''
    if logradouro:
        endereco = f"{logradouro}, {numero}" if numero else logradouro
    elif bairro:
        # Bairro é um componente REAL do endereço (não é fake). Aceitável como
        # logradouro quando a Receita não traz a rua, mas o bairro é verdadeiro.
        endereco = f"{bairro}, {numero}" if numero else bairro
        logger.warning("[Verificação] Logradouro vazio — usando BAIRRO real como endereço: %s", endereco)

    if not endereco.strip():
        # Sem logradouro/bairro reais -> dados incompletos. NÃO preenchemos fake.
        logger.error("[Verificação] Endereço REAL ausente (sem logradouro/bairro). "
                     "Abortando para não criar BM com endereço falso (CNPJ=%s).", cnpj)
        if callback_status:
            callback_status("❌ Endereço real ausente nos dados da empresa — abortando verificação.")
        return {'sucesso': False, 'mensagem': 'Endereço real ausente (dados incompletos do CNPJ).'}

    # Formatar telefone
    # Telefone REAL brasileiro: se a API não trouxe um celular válido (ou veio
    # vazio/curto), gera um número BR válido (DDD real + 9 + 8 dígitos). O botão
    # Salvar do Facebook só ATIVA quando o telefone está preenchido e válido.
    _tel_digitos = re.sub(r'[^\d]', '', telefone or '')
    if _tel_digitos.startswith('55'):
        _tel_nac = _tel_digitos[2:]
    else:
        _tel_nac = _tel_digitos
    if len(_tel_nac) < 10:  # sem número válido -> gerar um real
        try:
            from server.gerar_numero import gerar_numero_aleatorio
            telefone = f"+{gerar_numero_aleatorio()}"
            # Variantes antigas (do número inválido) ficam obsoletas -> regenerar
            # a partir do novo número mais abaixo (são geradas se vierem vazias).
            variantes_telefone = None
            logger.warning("[Verificação] Telefone ausente/inválido na API — gerado BR válido: %s", telefone)
        except Exception as _e_tel:
            logger.error("[Verificação] Falha ao gerar telefone BR: %s", _e_tel)

    if telefone and not telefone.startswith('+'):
        tel_limpo = re.sub(r'[^\d]', '', telefone)
        if tel_limpo.startswith('55'):
            telefone = f"+{tel_limpo}"
        elif len(tel_limpo) >= 10:
            telefone = f"+55{tel_limpo}"

    cnpj_formatado = _formatar_cnpj(cnpj)

    if url_site and not url_site.startswith('http'):
        url_site = f"https://{url_site}"

    logger.info("[Verificação] Preenchendo detalhes: razao=%s, cidade=%s, uf=%s, tel=%s",
                razao[:30] if razao else '', cidade, estado,
                telefone[:20] if telefone else 'VAZIO')

    # ===== FASE 1: Selecionar País Brasil PRIMEIRO =====
    # (Antes de preencher campos, pois o dropdown cobre os inputs quando aberto)
    if callback_status:
        callback_status("🌍 Selecionando país Brasil...")
    _selecionar_pais_brasil(driver)
    _delay_medio()

    # ===== FASE 2: Marcar todos os campos do popup com data-detalhe-campo =====
    _marcar_campos_detalhes(driver)

    # ===== FASE 3: Preencher cada campo por data-detalhe-campo =====
    # IMPORTANTE: O telefone é preenchido SEPARADO com método robusto (React Setter)
    # Todos os outros campos usam _limpar_e_digitar normal.
    campos_valores = [
        ('razao',    razao,           'razão social'),
        ('endereco', endereco,        'endereço'),
        ('cidade',   cidade,          'cidade'),
        ('estado',   estado,          'estado'),
        ('cep',      '',              'CEP'),       # formatação abaixo
        # TELEFONE será preenchido DEPOIS com método especial
        ('site',     url_site,        'site'),
        ('cnpj',     cnpj_formatado,  'CNPJ'),
    ]

    # Formatar CEP
    if cep:
        cep_limpo = re.sub(r'[^\d]', '', cep)
        if len(cep_limpo) == 8:
            cep_fmt = f"{cep_limpo[:5]}-{cep_limpo[5:]}"
        else:
            cep_fmt = cep_limpo
        for i, (nome, val, lbl) in enumerate(campos_valores):
            if nome == 'cep':
                campos_valores[i] = ('cep', cep_fmt, 'CEP')
                break

    for nome_campo, valor, label_log in campos_valores:
        if not valor:
            logger.info("[Verificação] Campo '%s' sem valor — pulando", nome_campo)
            continue
        if callback_status and label_log:
            callback_status(f"📝 Preenchendo {label_log}...")
        try:
            campo = driver.query_selector(f'[data-detalhe-campo="{nome_campo}"]')
            if campo:
                _limpar_e_digitar(driver, campo, valor, nome_campo)
                _delay_curto()
                driver.keyboard.press('Tab')
                _delay(0.3, 0.6)
                logger.info("[Verificação] Campo '%s' preenchido com '%s'",
                            nome_campo, valor[:30])
            else:
                logger.warning("[Verificação] Campo '%s' NÃO ENCONTRADO no popup — "
                               "valor seria '%s'", nome_campo, valor[:30])
        except Exception as exc:
            logger.warning("[Verificação] Erro ao preencher '%s': %s", nome_campo, exc)

    # ===== FASE 4: Preencher TELEFONE com método robusto (React Native Setter) =====
    # O telefone PRECISA estar preenchido para o botão Salvar ser ativado!
    # Usa _preencher_telefone_robusto que testa variantes e verifica aria-invalid.
    telefone_aceito = False
    if telefone or variantes_telefone:
        if callback_status:
            callback_status("📱 Preenchendo telefone comercial...")

        # Gerar variantes se não fornecidas
        if not variantes_telefone:
            variantes_telefone = _gerar_variantes_telefone(telefone)

        # Localizar campo de telefone
        campo_tel = driver.query_selector('[data-detalhe-campo="telefone"]')
        if not campo_tel:
            # Fallback: buscar por contexto
            campo_tel = _encontrar_input_por_contexto(
                driver,
                ['Telefone', 'Phone', 'Telefone comercial', 'Business phone'],
                ['Telefone da empresa n°', 'Phone number', 'Insira um número']
            )
        if not campo_tel:
            # Fallback posicional: 7º input dentro do dialog (índice 6)
            try:
                inputs = driver.query_selector_all(
                    '[role="dialog"] input[type="text"], '
                    '[role="dialog"] input:not([type])')
                inputs_visiveis = []
                for inp in inputs:
                    try:
                        box = inp.bounding_box()
                        if box and box['width'] > 0 and box['height'] > 0:
                            inputs_visiveis.append(inp)
                    except Exception:
                        inputs_visiveis.append(inp)
                if len(inputs_visiveis) >= 7:
                    campo_tel = inputs_visiveis[6]
                elif len(inputs_visiveis) >= 6:
                    campo_tel = inputs_visiveis[5]
            except Exception:
                pass

        if campo_tel:
            resultado_tel = _preencher_telefone_robusto(
                driver, campo_tel, variantes_telefone, callback_status)
            telefone_aceito = resultado_tel.get('sucesso', False)
            if telefone_aceito:
                logger.info("[Verificação] ✅ Telefone aceito: %s",
                            resultado_tel.get('formato_aceito', ''))
            else:
                logger.warning("[Verificação] ⚠️ Telefone não aceito: %s",
                               resultado_tel.get('mensagem', ''))
        else:
            logger.warning("[Verificação] Campo de telefone NÃO ENCONTRADO no popup")
    else:
        logger.warning("[Verificação] Sem número de telefone — campo ficará vazio")

    _delay_medio()
    logger.info("[Verificação] Todos os campos de detalhes preenchidos (telefone_aceito=%s)",
                telefone_aceito)


def _marcar_campos_detalhes(driver):
    """
    Executa JS que identifica cada input do popup "Editar detalhes da empresa"
    pelo label/texto próximo e marca com data-detalhe-campo.

    Campos marcados:
      razao, endereco, endereco2, cidade, estado, cep, telefone, site, cnpj
    """
    try:
        driver.evaluate_page("""() => {
            /* Limpar marcas anteriores */
            document.querySelectorAll('[data-detalhe-campo]').forEach(function(el) {
                el.removeAttribute('data-detalhe-campo');
            });

            var dialog = document.querySelector('[role="dialog"]');
            if (!dialog) return;

            /* Coletar todos os text inputs visíveis no popup, ordenados por Y */
            var inputs = Array.from(dialog.querySelectorAll(
                'input[type="text"], input:not([type]), input[type="tel"], input[type="url"]'
            )).filter(function(el) {
                var r = el.getBoundingClientRect();
                var t = (el.type || '').toLowerCase();
                return r.width > 0 && r.height > 0 && !el.disabled
                    && t !== 'hidden' && t !== 'checkbox' && t !== 'radio' && t !== 'file';
            }).sort(function(a, b) {
                return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
            });

            if (inputs.length === 0) return;

            /* Função: pegar texto descritivo próximo de um input
               Sobe até 5 níveis, coleta texto de irmãos SEM inputs */
            function nearText(el) {
                var txt = '';
                var ariaL = (el.getAttribute('aria-label') || '').trim();
                if (ariaL) txt += ' ' + ariaL;

                var ph = (el.getAttribute('placeholder') || '').trim();
                if (ph) txt += ' ' + ph;

                var p = el.parentElement;
                for (var depth = 0; depth < 6 && p && p !== dialog; depth++) {
                    var children = p.children;
                    for (var c = 0; c < children.length; c++) {
                        var child = children[c];
                        if (child === el || child.contains(el)) continue;
                        if (child.querySelector && child.querySelector('input')) continue;
                        var t = (child.innerText || child.textContent || '').trim();
                        if (t.length > 2 && t.length < 150) {
                            txt += ' ' + t;
                        }
                    }
                    if (txt.trim().length > 8) break;
                    p = p.parentElement;
                }
                return txt.toLowerCase();
            }

            /* Regras de classificação por texto próximo */
            var rules = [
                {campo: 'razao',    termos: ['razão social', 'razao social', 'legal business', 'legal name', 'nome comercial', 'documentos oficiais']},
                {campo: 'endereco', termos: ['endereço', 'endereco', 'address', 'logradouro', 'rua']},
                {campo: 'endereco2',termos: ['continuação', 'continuacao', 'address line 2', 'complemento', 'apt']},
                {campo: 'cidade',   termos: ['cidade', 'city', 'município', 'municipio']},
                {campo: 'estado',   termos: ['estado', 'state', 'província', 'provincia', 'região', 'regiao', 'uf']},
                {campo: 'cep',      termos: ['cep', 'código postal', 'codigo postal', 'zip', 'postal code']},
                {campo: 'telefone', termos: ['telefone', 'phone', 'celular', 'número de telefone']},
                {campo: 'site',     termos: ['site', 'website', 'url do site']},
                {campo: 'cnpj',     termos: ['identificação fiscal', 'identificacao fiscal', 'tax id', 'ein', 'cnpj', 'tax identification']},
            ];

            var classified = {};

            /* Ordem ESTRUTURAL dos inputs de texto no diálogo "Editar detalhes"
               (o combobox de País NÃO é <input>, então não entra na contagem):
               razao(0), endereco(1), endereco2(2), cidade(3), estado(4),
               cep(5), telefone(6), site(7), cnpj(8).
               Essa ordem é IDÊNTICA em qualquer idioma. */
            var posMap = ['razao', 'endereco', 'endereco2', 'cidade', 'estado',
                          'cep', 'telefone', 'site', 'cnpj'];

            /* MÉTODO PRIMÁRIO (idioma-agnóstico): mapeamento POSICIONAL direto
               quando a contagem de inputs corresponde ao layout conhecido
               (9 = com complemento; 8 = sem complemento). Não depende de texto. */
            if (inputs.length === 9) {
                for (var q = 0; q < posMap.length; q++) classified[posMap[q]] = inputs[q];
            } else if (inputs.length === 8) {
                /* sem endereco2 (complemento) */
                var pm8 = ['razao','endereco','cidade','estado','cep','telefone','site','cnpj'];
                for (var q2 = 0; q2 < pm8.length; q2++) classified[pm8[q2]] = inputs[q2];
            } else {
                /* Layout inesperado -> Fase 1: classificar por texto próximo */
                for (var i = 0; i < inputs.length; i++) {
                    var el = inputs[i];
                    var ctx = nearText(el);
                    for (var r = 0; r < rules.length; r++) {
                        var rule = rules[r];
                        if (classified[rule.campo]) continue;
                        for (var t = 0; t < rule.termos.length; t++) {
                            if (ctx.indexOf(rule.termos[t]) !== -1) { classified[rule.campo] = el; break; }
                        }
                        if (classified[rule.campo]) break;
                    }
                }
                /* Fase 2: preencher os que faltam por posição */
                var usedInputs = new Set();
                for (var key in classified) usedInputs.add(classified[key]);
                var remaining = inputs.filter(function(el) { return !usedInputs.has(el); });
                var remIdx = 0;
                for (var p = 0; p < posMap.length && remIdx < remaining.length; p++) {
                    if (!classified[posMap[p]]) { classified[posMap[p]] = remaining[remIdx]; remIdx++; }
                }
            }

            /* Marcar os inputs com data-detalhe-campo */
            for (var campo in classified) {
                if (classified[campo]) {
                    classified[campo].setAttribute('data-detalhe-campo', campo);
                }
            }
        }""")
    except Exception as exc:
        logger.warning("[Verificação] Erro ao marcar campos do popup: %s", exc)


def _formatar_cnpj(cnpj):
    """Formata CNPJ: 12345678000199 -> 12.345.678/0001-99"""
    if not cnpj:
        return ''
    numeros = re.sub(r'[^\d]', '', cnpj)
    if len(numeros) == 14:
        return (f"{numeros[:2]}.{numeros[2:5]}.{numeros[5:8]}"
                f"/{numeros[8:12]}-{numeros[12:14]}")
    return cnpj


def _pais_selecionado(driver) -> bool:
    """True se o combobox de País do diálogo já mostra um valor (contém 'bra' —
    Brasil/Brazil/Brésil/Brasilien...). Independente de idioma."""
    try:
        v = driver.evaluate_page("""() => {
            const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
            if(!dlg) return '';
            const cb=dlg.querySelector('[role=combobox][aria-haspopup=listbox]')||dlg.querySelector('[role=combobox]');
            return cb ? (cb.innerText||cb.textContent||'').trim() : '';
        }""") or ""
        return "bra" in v.lower() or "bré" in v.lower() or "brá" in v.lower()
    except Exception:
        return False


def _selecionar_pais_brasil(driver):
    """
    Seleciona 'Brasil' no combobox de País — INDEPENDENTE DE IDIOMA (2026-09-18).

    Mapeado AO VIVO numa conta em INGLÊS (business_id 1472628078031325): o País é o
    ÚNICO `[role="combobox"][aria-haspopup="listbox"]` do diálogo "Editar detalhes"
    (posição 1, logo após o Nome legal). NÃO depende do rótulo "País"/"Country".
    Método provado: clicar o combobox → digitar "Bra" (prefixo comum a Brazil/Brasil/
    Brésil/Brasilien/Brazilië) → ArrowDown + Enter → o combobox passa a mostrar o país.
    Verifica o resultado e faz 2 estratégias de reforço antes de cair no método antigo.
    """
    try:
        # ── MÉTODO NOVO (estrutural, idioma-agnóstico) ──────────────────────────
        for tentativa in range(2):
            # 1) achar o combobox do País pela ESTRUTURA e clicar por coordenada REAL
            xy = driver.evaluate_page("""() => {
                const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
                if(!dlg) return null;
                const cb=dlg.querySelector('[role=combobox][aria-haspopup=listbox]')||dlg.querySelector('[role=combobox]');
                if(!cb) return null;
                cb.scrollIntoView({block:'center'});
                const r=cb.getBoundingClientRect();
                return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
            }""")
            if not xy:
                break  # sem combobox → cai no método antigo (por rótulo)
            try:
                driver.mouse.click(xy["x"], xy["y"])
            except Exception:
                # fallback: clique via elementFromPoint
                driver.evaluate_page("(p)=>{const e=document.elementFromPoint(p.x,p.y); if(e) e.click();}", xy)
            _delay(0.6, 1.1)
            # 2) digitar o prefixo comum e escolher por teclado (sem depender do texto exato)
            termo = "Bra" if tentativa == 0 else "Brazil"
            try:
                driver.keyboard.type(termo, delay=random.randint(50, 110))
            except Exception:
                try: driver.keyboard.type(termo)
                except Exception: pass
            _delay(0.7, 1.3)
            try:
                driver.keyboard.press("ArrowDown"); _delay(0.2, 0.4)
                driver.keyboard.press("Enter")
            except Exception:
                pass
            _delay(0.5, 0.9)
            if _pais_selecionado(driver):
                logger.info("[Verificação] País selecionado (estrutural, termo=%s)", termo)
                return True
            # não pegou por teclado → tenta clicar a 1ª opção que contenha 'bra'
            clicou = driver.evaluate_page("""() => {
                const lb=[...document.querySelectorAll('[role=listbox]')].filter(e=>e.getBoundingClientRect().width>0).pop();
                if(!lb) return false;
                const op=[...lb.querySelectorAll('[role=option]')].find(o=>/bra/i.test(o.innerText||''));
                if(!op) return false; op.scrollIntoView({block:'center'});
                const r=op.getBoundingClientRect(); window.__opxy=[Math.round(r.x+r.width/2),Math.round(r.y+r.height/2)];
                return true;
            }""")
            if clicou:
                try:
                    p = driver.evaluate_page("()=>window.__opxy")
                    driver.mouse.click(p[0], p[1])
                    _delay(0.5, 0.9)
                    if _pais_selecionado(driver):
                        logger.info("[Verificação] País selecionado (estrutural, clique na opção)")
                        return True
                except Exception:
                    pass
        if _pais_selecionado(driver):
            return True
        logger.info("[Verificação] Método estrutural do País não confirmou — tentando por rótulo (legado)")

        # ===== LEGADO: Encontrar o dropdown de País via rótulo texto =====
        encontrou = driver.evaluate_page("""() => {
            /* Limpar marca anterior */
            document.querySelectorAll('[data-pais-dropdown]').forEach(function(el) {
                el.removeAttribute('data-pais-dropdown');
            });

            var dialog = document.querySelector('[role="dialog"]');
            if (!dialog) return false;

            /* Procurar label/span com texto "País" ou "Country" */
            var labels = dialog.querySelectorAll('span, label, div');
            for (var i = 0; i < labels.length; i++) {
                var txt = (labels[i].innerText || '').trim();
                if (txt.length > 1 && txt.length < 20 &&
                    (txt.toLowerCase() === 'país' || txt.toLowerCase() === 'country' ||
                     txt.toLowerCase() === 'pais')) {
                    /* Encontrou o label — procurar o dropdown próximo */
                    var parent = labels[i].parentElement;
                    for (var d = 0; d < 6 && parent && parent !== dialog; d++) {
                        /* Procurar um elemento clicável (combobox, select, div com seta) */
                        var clickable = parent.querySelector(
                            '[role="combobox"], [role="listbox"], select, ' +
                            '[aria-haspopup], [aria-expanded]');
                        if (clickable) {
                            clickable.setAttribute('data-pais-dropdown', '1');
                            return true;
                        }
                        /* Se o próprio parent tem role de botão ou select */
                        var sibs = parent.querySelectorAll('[role="button"]');
                        for (var s = 0; s < sibs.length; s++) {
                            var sibRect = sibs[s].getBoundingClientRect();
                            if (sibRect.width > 50 && sibRect.height > 20) {
                                sibs[s].setAttribute('data-pais-dropdown', '1');
                                return true;
                            }
                        }
                        parent = parent.parentElement;
                    }
                    break;
                }
            }

            /* Fallback: procurar qualquer combobox/select no dialog */
            var combos = dialog.querySelectorAll(
                '[role="combobox"], [aria-haspopup="listbox"], select');
            for (var c = 0; c < combos.length; c++) {
                var r = combos[c].getBoundingClientRect();
                if (r.width > 50 && r.height > 20) {
                    combos[c].setAttribute('data-pais-dropdown', '1');
                    return true;
                }
            }
            return false;
        }""")

        dropdown = None
        if encontrou:
            dropdown = driver.query_selector('[data-pais-dropdown="1"]')

        if not dropdown:
            # Fallback direto por aria-label
            for sel in [
                '[role="dialog"] [aria-label*="País"]',
                '[role="dialog"] [aria-label*="Country"]',
                '[role="dialog"] [role="combobox"]',
                '[role="dialog"] select',
            ]:
                dropdown = driver.query_selector(sel)
                if dropdown:
                    break

        if not dropdown:
            logger.warning("[Verificação] Dropdown de País não encontrado")
            return False

        # Clicar no dropdown para abrir a lista
        _clicar_humano(driver, dropdown)
        _delay_medio()
        _delay(0.5, 1.0)

        # ===== Procurar campo de pesquisa que aparece após abrir o dropdown =====
        search_input = None
        for sel in [
            '[role="dialog"] input[type="search"]',
            '[role="dialog"] input[placeholder*="Pesquisar"]',
            '[role="dialog"] input[placeholder*="Search"]',
            '[role="dialog"] input[placeholder*="Buscar"]',
            'input[type="search"]',
            'input[aria-label*="Pesquisar"]',
            'input[aria-label*="Search"]',
        ]:
            try:
                search_input = driver.query_selector(sel)
                if search_input:
                    break
            except Exception:
                continue

        if search_input:
            logger.info("[Verificação] Campo de pesquisa do País encontrado — digitando 'Brasil'")
            # Usar keyboard.type direto (NÃO usar React setter — o search input
            # do dropdown do Facebook é um componente custom que filtra por eventos de teclado)
            try:
                search_input.click()
                _delay(0.3, 0.5)
                search_input.focus() if hasattr(search_input, 'focus') else None
            except Exception:
                pass
            _delay(0.2, 0.4)
            try:
                driver.keyboard.type('Brasil', delay=random.randint(40, 100))
            except Exception:
                try:
                    driver.keyboard.type('Brasil')
                except Exception as ke:
                    logger.warning("[Verificação] Falha ao digitar no search: %s", ke)
            _delay_medio()
            _delay(0.8, 1.5)
        else:
            logger.warning("[Verificação] Campo de pesquisa do País NÃO encontrado — tentando digitar direto")
            # Mesmo sem encontrar o input, tentar digitar (o foco pode já estar no campo)
            try:
                driver.keyboard.type('Brasil', delay=random.randint(40, 100))
                _delay_medio()
            except Exception:
                pass

        # ===== Selecionar "Brasil" na lista filtrada =====
        # Tentar vários seletores que o Facebook usa
        opcao = None

        # 1. role=option com texto Brasil
        try:
            opcao = driver.query_selector('[role="option"]:has-text("Brasil")')
        except Exception:
            pass
        if not opcao:
            try:
                opcao = driver.query_selector('[role="option"]:has-text("Brazil")')
            except Exception:
                pass

        # 2. Radio button / label com Brasil
        if not opcao:
            try:
                opcao = driver.query_selector('[role="radio"]:has-text("Brasil")')
            except Exception:
                pass

        # 3. Buscar em todos os elementos da lista
        if not opcao:
            try:
                candidatos = driver.query_selector_all(
                    '[role="dialog"] [role="option"], '
                    '[role="dialog"] [role="radio"], '
                    '[role="dialog"] [role="menuitem"], '
                    '[role="dialog"] label, '
                    '[role="dialog"] li, '
                    '[role="dialog"] div[role="button"]')
                for op in candidatos:
                    try:
                        txt = (op.text_content() or '').strip()
                        if txt.lower() in ['brasil', 'brazil']:
                            opcao = op
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        # 4. Buscar span com texto exato Brasil e clicar nele
        if not opcao:
            try:
                spans = driver.query_selector_all('[role="dialog"] span')
                for span in spans:
                    try:
                        txt = (span.text_content() or '').strip()
                        if txt.lower() in ['brasil', 'brazil']:
                            opcao = span
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if opcao:
            _clicar_humano(driver, opcao)
            _delay_curto()
            logger.info("[Verificação] País Brasil selecionado com sucesso")
            return True

        # Fallback: <select> nativo
        try:
            selects = driver.query_selector_all('[role="dialog"] select')
            for sel in selects:
                options = sel.query_selector_all('option')
                for opt in options:
                    txt = (opt.text_content() or '').strip()
                    if txt.lower() in ['brasil', 'brazil']:
                        sel.select_option(label=txt)
                        _delay_curto()
                        logger.info("[Verificação] País Brasil selecionado via <select>")
                        return True
        except Exception:
            pass

        logger.warning("[Verificação] Não conseguiu selecionar país Brasil")
        return False

    except Exception as e:
        logger.error("[Verificação] Erro ao selecionar país: %s", e)
        return False


def _clicar_botao_salvar(driver):
    """Clica no botão 'Salvar'/'Save' do popup — INDEPENDENTE DE IDIOMA.

    MÉTODO PRIMÁRIO (estrutural): o botão de salvar é o botão PRIMÁRIO do rodapé
    do diálogo — habilitado, com fundo azul do Facebook (#0866FF/#1877F2), e o
    ÚLTIMO botão de ação (à direita, depois do Cancelar). Não depende do texto
    "Salvar"/"Save"/"Enregistrer"/"Speichern"/"Guardar"...
    FALLBACK: substring matching por texto (legado).
    """
    # ── PRIMÁRIO: botão primário azul, habilitado, último do rodapé ──────────
    try:
        clicou_xy = driver.evaluate_page(r"""() => {
            const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
            if(!dlg) return null;
            const vis=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
                return r.width>4&&r.height>4&&s.visibility!=='hidden'&&s.display!=='none';};
            const isDis=e=>e.getAttribute('aria-disabled')==='true'||e.disabled===true;
            // botões de ação do diálogo, ordenados por posição X (esquerda->direita)
            let btns=[...dlg.querySelectorAll('[role=button],button')].filter(vis).filter(e=>!isDis(e));
            // excluir o "X"/fechar (canto sup. direito, pequeno e sem largura de texto)
            btns=btns.filter(e=>{const r=e.getBoundingClientRect(); return !(r.width<60 && r.top < dlg.getBoundingClientRect().top+70);});
            if(!btns.length) return null;
            const blueOf=e=>{const s=getComputedStyle(e);const bg=s.backgroundColor||'';
                const m=bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/); if(!m) return false;
                const R=+m[1],G=+m[2],B=+m[3]; return B>180 && B>R+40 && G<160 && R<120;};
            // APENAS o botão PRIMÁRIO azul habilitado (o Save). NUNCA cair em
            // "rightmost button" — isso poderia clicar em Cancel e DESCARTAR tudo.
            // Se o Save estiver desabilitado (azul-claro), blueOf o rejeita -> null
            // -> o fallback de texto (que também checa disabled) decide com segurança.
            const alvo=btns.filter(blueOf).sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left).pop();
            if(!alvo) return null;
            alvo.scrollIntoView({block:'center'});
            const r=alvo.getBoundingClientRect();
            return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), t:(alvo.innerText||'').slice(0,20)};
        }""")
        if clicou_xy:
            try:
                driver.mouse.click(clicou_xy["x"], clicou_xy["y"])
            except Exception:
                driver.evaluate_page("(p)=>{const e=document.elementFromPoint(p.x,p.y); if(e) e.click();}", clicou_xy)
            logger.info("[Verificação] Botão Salvar (estrutural) clicado: '%s'", clicou_xy.get("t"))
            _delay_curto()
            return True
    except Exception as _e:
        logger.debug("[Verificação] Salvar estrutural falhou: %s", _e)

    # ── FALLBACK: por texto (legado) ────────────────────────────────────────
    textos_salvar = ['salvar', 'save', 'enviar', 'submit', 'atualizar', 'update',
                     'guardar', 'enregistrer', 'speichern', 'salva', 'opslaan', 'zapisz']

    def _texto_match(txt):
        """Verifica se algum texto de salvar está contido no texto do botão."""
        txt = txt.strip().lower()
        if not txt or len(txt) > 30:
            return False
        for t in textos_salvar:
            if t in txt:
                return True
        return False

    # No dialog — priorizar botão visível com texto Salvar
    try:
        botoes = driver.query_selector_all('[role="dialog"] [role="button"]')
        for btn in botoes:
            try:
                txt = (btn.text_content() or '').strip().lower()
                if _texto_match(txt):
                    # Verificar se o botão NÃO está desabilitado
                    disabled = btn.evaluate('el => el.getAttribute("aria-disabled") === "true" || el.disabled')
                    if disabled:
                        logger.warning("[Verificação] Botão Salvar encontrado mas DESABILITADO")
                        continue
                    _clicar_humano(driver, btn)
                    _delay_curto()
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # Fora do dialog (footer fixo do Facebook)
    try:
        botoes = driver.query_selector_all('[role="button"]')
        for btn in botoes:
            try:
                txt = (btn.text_content() or '').strip().lower()
                if _texto_match(txt):
                    disabled = btn.evaluate('el => el.getAttribute("aria-disabled") === "true" || el.disabled')
                    if disabled:
                        continue
                    _clicar_humano(driver, btn)
                    _delay_curto()
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # Por span interno (último recurso)
    try:
        spans = driver.query_selector_all('[role="dialog"] span')
        for span in spans:
            try:
                txt = (span.text_content() or '').strip().lower()
                if txt in textos_salvar:
                    span.click()
                    _delay_curto()
                    return True
            except Exception:
                continue
    except Exception:
        pass

    logger.warning("[Verificação] Não encontrou botão Salvar (ou estava desabilitado)")
    return False


# ============================================================================
# HELPERS DE NAVEGAÇÃO
# ============================================================================

def _esperar_pagina(driver, timeout=15):
    """Espera a página carregar completamente.
    1. networkidle (rede parar)
    2. load (DOM pronto)
    3. Verificar estabilidade do DOM (sem spinners/loading)
    """
    try:
        driver.wait_for_load_state('networkidle', timeout=timeout * 1000)
    except Exception:
        try:
            driver.wait_for_load_state('load', timeout=8000)
        except Exception:
            _delay_medio()

    # Esperar spinners/loading desaparecerem
    for _ in range(10):
        try:
            tem_loading = driver.evaluate_page("""() => {
                var spinners = document.querySelectorAll(
                    '[role="progressbar"], [data-testid="loading"], ' +
                    '[class*="loading"], [class*="spinner"], ' +
                    '[aria-label="Carregando"], [aria-label="Loading"]');
                for (var i = 0; i < spinners.length; i++) {
                    var r = spinners[i].getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) return true;
                }
                return false;
            }""")
            if not tem_loading:
                break
        except Exception:
            break
        time.sleep(0.25)

    # F5 se a página do Business caiu em ERRO ("Estamos tendo problemas para
    # concluir sua solicitação." / "Something went wrong") ou em BRANCO — senão
    # o fluxo seguiria numa página quebrada e "pularia" etapas. Reload + espera.
    for _tent in range(2):
        if not _pagina_business_com_erro(driver):
            break
        logger.warning("[Verificação] Página com erro/branco — recarregando (F5).")
        try:
            driver.refresh()
        except Exception:
            try:
                driver.get(driver.current_url)
            except Exception:
                pass
        try:
            driver.wait_for_load_state('networkidle', timeout=timeout * 1000)
        except Exception:
            _delay_medio()
        time.sleep(2)


def _pagina_business_com_erro(driver):
    """Detecta a página de erro do Business ("Estamos tendo problemas..." /
    "Something went wrong") ou página praticamente em branco, que exigem F5."""
    try:
        return bool(driver.evaluate_page("""() => {
            var txt = (document.body && document.body.innerText || '').trim().toLowerCase();
            var marcadores = ['estamos tendo problemas','problemas para concluir','tendo problemas',
                'something went wrong','sorry, something went wrong',"we're having trouble",
                'having trouble','algo deu errado','tente novamente mais tarde','try again later',
                'no pudimos completar','algo salió mal'];
            for (var i=0;i<marcadores.length;i++){ if(txt.indexOf(marcadores[i])!==-1) return true; }
            var n = document.querySelectorAll('*').length;
            return (txt.length < 5 && n < 60);
        }""")) or False
    except Exception:
        return False


def _aguardar_elemento(driver, seletor, timeout=15, descricao=''):
    """Aguarda um elemento aparecer na página com retry.
    Retorna o ElementHandle ou None."""
    desc = descricao or seletor
    logger.info("[Verificação] Aguardando elemento: %s (timeout=%ds)", desc, timeout)

    # Primeiro tentar wait_for_selector nativo
    try:
        driver.wait_for_selector(seletor, timeout=timeout * 1000)
        el = driver.query_selector(seletor)
        if el:
            return el
    except Exception:
        pass

    # Fallback: polling manual
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            el = driver.query_selector(seletor)
            if el:
                return el
        except Exception:
            pass
        time.sleep(0.25)

    logger.warning("[Verificação] Elemento '%s' não encontrado após %ds", desc, timeout)
    return None


def _clicar_botao(driver, texto, timeout=5000):
    """Clica em um botão pelo texto visível."""
    try:
        botoes = driver.query_selector_all('[role="button"]')
        for btn in botoes:
            try:
                txt = (btn.text_content() or '').strip()
                if txt.lower() == texto.lower() or texto.lower() in txt.lower():
                    _clicar_humano(driver, btn)
                    return True
            except Exception:
                continue
    except Exception:
        pass

    try:
        loc = driver.locator(f'text="{texto}"')
        loc.first.click(timeout=timeout)
        return True
    except Exception:
        pass

    return False


# ============================================================================
# FLUXO 2: PREENCHER TELEFONE COMERCIAL
# ============================================================================

def preencher_telefone_comercial(driver, business_id, numero_telefone,
                                  callback_status=None, variantes_telefone=None):
    """Preenche o telefone comercial nos detalhes da empresa.

    Usa o seletor exato do input do Facebook:
      [data-detalhe-campo="telefone"] (marcado pelo nosso JS _marcar_campos_detalhes)
    
    O input do Facebook (2026) tem estas características:
      - <input type="text" data-detalhe-campo="telefone" aria-invalid="true|false" ...>
      - Classes: xjbqb8w x972fbf x10w94by x1qhh985 ...
      - Validação React que define aria-invalid
      - Mensagem de erro: "Insira um número de telefone válido."

    Fluxo:
      1. Navegar para business_info
      2. Abrir popup "Editar detalhes da empresa"
      3. Marcar campos com data-detalhe-campo
      4. Localizar campo via [data-detalhe-campo="telefone"]
      5. Preencher com variantes até Facebook aceitar (aria-invalid="false")
      6. SÓ DEPOIS de preencher com sucesso, clicar em Salvar

    Args:
        driver: PlaywrightDriver
        business_id: ID da BM
        numero_telefone: Número principal (fallback se variantes não fornecidas)
        callback_status: Callback para progresso
        variantes_telefone: Lista de variantes de formato do número.
    """
    if callback_status:
        callback_status(f"📱 Preenchendo telefone comercial: {numero_telefone}")

    try:
        # Gerar variantes se não foram fornecidas
        if not variantes_telefone:
            variantes_telefone = _gerar_variantes_telefone(numero_telefone)

        logger.info("[Telefone Comercial] Número: %s | Variantes: %s",
                    numero_telefone, variantes_telefone)

        url_info = (
            f"https://business.facebook.com/latest/settings/business_info"
            f"?business_id={business_id}"
        )
        driver.goto(url_info)
        _esperar_pagina(driver, 30)
        _delay_longo()

        # Aguardar que a página tenha pelo menos botões carregados
        _aguardar_elemento(driver, '[role="button"]', timeout=20,
                           descricao='botões da página business_info (telefone)')
        _delay_curto()

        # Fechar overlays que bloqueiam botões
        _fechar_overlays_facebook(driver)
        _delay_medio()

        # Scroll para ver a seção de detalhes
        _scroll_suave(driver, 'baixo', 350)
        _delay_medio()

        # Encontrar botão "Editar" da seção "Detalhes da empresa"
        btn_detalhes = _encontrar_botao_editar_detalhes(driver)
        if not btn_detalhes:
            _scroll_suave(driver, 'baixo', 400)
            _delay_medio()
            btn_detalhes = _encontrar_botao_editar_detalhes(driver)

        if not btn_detalhes:
            botoes = _encontrar_botoes_editar(driver)
            if botoes and len(botoes) >= 3:
                btn_detalhes = botoes[2]
            elif botoes:
                btn_detalhes = botoes[-1]

        if not btn_detalhes:
            return {'sucesso': False, 'mensagem': 'Não encontrou botão Editar'}

        _clicar_humano(driver, btn_detalhes)
        _delay_medio()

        popup = _aguardar_popup(driver, timeout=15)
        if not popup:
            _clicar_humano(driver, btn_detalhes)
            _delay_medio()
            popup = _aguardar_popup(driver, timeout=10)

        if not popup:
            return {'sucesso': False, 'mensagem': 'Popup de detalhes não abriu'}

        # Verificar se é o popup correto
        popup_correto = _verificar_popup_detalhes(driver)
        if not popup_correto:
            logger.warning("[Telefone Comercial] Popup incorreto — tentando outro botão")
            _fechar_popup(driver)
            _delay_medio()
            botoes = _encontrar_botoes_editar(driver)
            if botoes:
                for btn in reversed(botoes):
                    _clicar_humano(driver, btn)
                    _delay_medio()
                    popup = _aguardar_popup(driver, timeout=6)
                    if popup and _verificar_popup_detalhes(driver):
                        popup_correto = True
                        break
                    if popup:
                        _fechar_popup(driver)
                        _delay_curto()

        if not popup_correto:
            return {'sucesso': False, 'mensagem': 'Não encontrou popup Editar detalhes (telefone)'}

        # Aguardar inputs do popup carregarem
        _aguardar_elemento(driver, '[role="dialog"] input', timeout=10,
                           descricao='inputs do popup de detalhes (telefone)')
        _delay_medio()

        # Marcar campos com data-detalhe-campo (mesmo JS que usa _preencher_detalhes_empresa)
        _marcar_campos_detalhes(driver)
        _delay_curto()

        # ============================================================
        # LOCALIZAR O CAMPO DE TELEFONE PELO SELETOR EXATO
        # Seletor: [data-detalhe-campo="telefone"]
        # ============================================================
        campo = driver.query_selector('[data-detalhe-campo="telefone"]')

        if not campo:
            # Fallback: buscar input com contexto "telefone" no dialog
            logger.warning("[Telefone Comercial] Seletor exato não encontrou — usando fallback")
            campo = _encontrar_input_por_contexto(
                driver,
                ['Telefone', 'Phone', 'Telefone comercial', 'Business phone'],
                ['Telefone da empresa n°', 'Phone number', 'Insira um número']
            )

        if not campo:
            # Fallback posicional: 7º input dentro do dialog (índice 6)
            try:
                inputs = driver.query_selector_all(
                    '[role="dialog"] input[type="text"], '
                    '[role="dialog"] input:not([type])')
                # Filtrar apenas inputs visíveis
                inputs_visiveis = []
                for inp in inputs:
                    try:
                        box = inp.bounding_box()
                        if box and box['width'] > 0 and box['height'] > 0:
                            inputs_visiveis.append(inp)
                    except Exception:
                        inputs_visiveis.append(inp)

                if len(inputs_visiveis) >= 7:
                    campo = inputs_visiveis[6]
                    logger.info("[Telefone Comercial] Campo por posição: 7º input (de %d)",
                                len(inputs_visiveis))
                elif len(inputs_visiveis) >= 6:
                    campo = inputs_visiveis[5]
                    logger.info("[Telefone Comercial] Campo por posição: 6º input (de %d)",
                                len(inputs_visiveis))
            except Exception:
                pass

        if not campo:
            logger.error("[Telefone Comercial] Campo de telefone NÃO encontrado")
            _fechar_popup(driver)
            return {'sucesso': False, 'mensagem': 'Campo de telefone não encontrado'}

        logger.info("[Telefone Comercial] Campo encontrado — iniciando preenchimento")

        # ============================================================
        # PREENCHER TELEFONE COM VARIANTES (SEM CLICAR SALVAR AINDA)
        # ============================================================
        if callback_status:
            callback_status("📱 Preenchendo telefone...")

        resultado = _preencher_telefone_robusto(
            driver, campo, variantes_telefone, callback_status)

        if resultado.get('sucesso'):
            formato_aceito = resultado.get('formato_aceito', '')
            logger.info("[Telefone Comercial] Telefone preenchido: '%s'", formato_aceito)

            # Verificar que o valor realmente está no campo antes de salvar
            _delay(0.5, 1.0)
            try:
                campo_check = driver.query_selector('[data-detalhe-campo="telefone"]')
                val_check = campo_check.evaluate('el => el.value || ""') if campo_check else ''
                logger.info("[Telefone Comercial] Valor no campo antes de salvar: '%s'", val_check)
                if not val_check or not val_check.strip():
                    logger.warning("[Telefone Comercial] Campo vazio antes de salvar!")
            except Exception:
                pass

            # ============================================================
            # SÓ AGORA CLICAR EM SALVAR
            # ============================================================
            _delay_medio()
            if callback_status:
                callback_status(f"💾 Salvando com telefone: {formato_aceito}...")

            salvou = False
            for tentativa_salvar in range(3):
                _clicar_botao_salvar(driver)
                _delay_longo()
                _delay_medio()

                # Verificar se o popup fechou
                popup_aberto = False
                try:
                    dialog = driver.query_selector('[role="dialog"]')
                    if dialog:
                        txt = (dialog.text_content() or '').lower()
                        if 'razão social' in txt or 'razao social' in txt or 'endereço' in txt:
                            # Popup ainda aberto — verificar se erro de telefone
                            if _verificar_erro_validacao_telefone(driver):
                                logger.warning("[Telefone Comercial] Erro de validação pós-save")
                                # Tentar outra variante
                                fmt_aceito = resultado.get('formato_aceito', '')
                                variantes_rest = [v for v in variantes_telefone if v != fmt_aceito]
                                if variantes_rest:
                                    campo2 = driver.query_selector('[data-detalhe-campo="telefone"]')
                                    if campo2:
                                        resultado2 = _preencher_telefone_robusto(
                                            driver, campo2, variantes_rest, callback_status)
                                        if resultado2.get('sucesso'):
                                            resultado = resultado2
                                            continue
                                break
                            popup_aberto = True
                except Exception:
                    pass

                if not popup_aberto:
                    salvou = True
                    break

                if callback_status:
                    callback_status(f"⚠️ Re-tentando salvar ({tentativa_salvar + 2}/3)...")
                _delay_medio()

            if salvou:
                if callback_status:
                    callback_status(
                        f"✅ Telefone comercial salvo: {resultado.get('formato_aceito', '')}")
                logger.info("[Telefone Comercial] ✅ Salvo: %s", resultado.get('formato_aceito', ''))
                return {'sucesso': True,
                        'mensagem': f"Telefone salvo: {resultado.get('formato_aceito', '')}"}
            else:
                logger.warning("[Telefone Comercial] Popup não fechou — pode ter salvo")
                _fechar_popup(driver)
                return {'sucesso': True,
                        'mensagem': 'Telefone preenchido, popup não confirmou save'}
        else:
            logger.error("[Telefone Comercial] Nenhuma variante aceita")
            _fechar_popup(driver)
            return {'sucesso': False,
                    'mensagem': resultado.get('mensagem', 'Nenhuma variante aceita')}

    except Exception as e:
        logger.error("[Telefone Comercial] Erro: %s", e, exc_info=True)
        return {'sucesso': False, 'mensagem': f'Erro: {str(e)}'}


def _gerar_variantes_telefone(numero):
    """Gera variantes de formato a partir de um número de telefone.
    Usado quando variantes não são fornecidas pela API."""
    if not numero:
        return []

    import re as _re
    num_digitos = _re.sub(r'[^\d]', '', str(numero))

    if not num_digitos or len(num_digitos) < 10:
        return [numero] if numero else []

    variantes = []

    # Normalizar: garantir que começa com 55
    if num_digitos.startswith('55') and len(num_digitos) >= 12:
        num_sem_pais = num_digitos[2:]
    elif len(num_digitos) in (10, 11):
        num_sem_pais = num_digitos
        num_digitos = '55' + num_digitos
    else:
        num_sem_pais = num_digitos

    # Extrair DDD e número local
    ddd = num_sem_pais[:2] if len(num_sem_pais) >= 10 else ''
    num_local = num_sem_pais[2:] if len(num_sem_pais) >= 10 else num_sem_pais

    # 1. Internacional com +
    variantes.append(f"+{num_digitos}")
    # 2. Apenas dígitos completos
    variantes.append(num_digitos)
    # 3. Local com DDD
    variantes.append(num_sem_pais)
    # 4. Formatado BR
    if ddd and len(num_local) >= 8:
        if len(num_local) == 9:
            variantes.append(f"({ddd}) {num_local[:5]}-{num_local[5:]}")
        else:
            variantes.append(f"({ddd}) {num_local[:4]}-{num_local[4:]}")
    # 5. Internacional formatado
    if ddd and len(num_local) >= 8:
        if len(num_local) == 9:
            variantes.append(f"+55 {ddd} {num_local[:5]}-{num_local[5:]}")
        else:
            variantes.append(f"+55 {ddd} {num_local[:4]}-{num_local[4:]}")
    # 6. Com número original se diferente
    if numero and numero not in variantes:
        variantes.append(numero)

    # Remover duplicatas
    seen = set()
    unicas = []
    for v in variantes:
        if v not in seen:
            seen.add(v)
            unicas.append(v)

    return unicas


# ============================================================================
# FLUXO 3: ADICIONAR E VERIFICAR DOMÍNIO
# ============================================================================

def _dialog_dominio_aberto(driver):
    """True se o dialog de adicionar domínio realmente abriu (mostra as opções
    'Criar um domínio'/'Solicitar acesso' ou já tem um campo de input). Usado
    para CONFIRMAR que o clique em 'Adicionar' surtiu efeito antes de prosseguir."""
    try:
        return bool(driver.evaluate_page("""() => {
            const dlg = document.querySelector('[role="dialog"]');
            if (!dlg) return false;
            const t = (dlg.innerText || '').toLowerCase();
            return t.indexOf('criar um domínio') !== -1
                || t.indexOf('criar um dominio') !== -1
                || t.indexOf('create a domain') !== -1
                || t.indexOf('solicitar acesso') !== -1
                || t.indexOf('request access') !== -1
                || (dlg.querySelector('input') !== null);
        }"""))
    except Exception:
        return False


def adicionar_e_verificar_dominio(driver, business_id, dominio, site_id,
                                   salvar_meta_func, callback_status=None,
                                   telefone_site=''):
    """
    Adiciona um domínio ao Business Manager e verifica via Meta Tag.

    Fluxo:
    1. Navegar para Settings > Domains
    2. Clicar "Adicionar"
    3. Selecionar "Criar um domínio"
    4. Digitar o domínio
    5. Clicar "Adicionar"
    6. Extrair meta tag de verificação
    7. Salvar meta tag no site via API (+ atualizar telefone do site)
    8. Aguardar propagação
    9. Clicar "Verificar domínio"
    10. Confirmar verificação

    Args:
        telefone_site: Se fornecido, atualiza o telefone do site ao salvar meta tags

    Returns:
        dict: {'sucesso': bool, 'mensagem': str, 'verificado': bool}
    """
    if callback_status:
        callback_status(f"🌐 Adicionando domínio: {dominio}")

    try:
        # ===== PASSO 1: Navegar para página de domínios =====
        url_dominios = (
            f"https://business.facebook.com/latest/settings/domains"
            f"?business_id={business_id}"
        )
        driver.goto(url_dominios)
        _esperar_pagina(driver, 30)
        _delay_longo()

        # Aguardar que a página de domínios carregue completamente
        _aguardar_elemento(driver, '[role="button"]', timeout=20,
                           descricao='botões da página de domínios')
        _delay_leitura()

        # ===== CHECK BLOQUEIO 1: Logo após carregar página de domínios =====
        if detectar_bm_bloqueada_verificacao(driver):
            logger.warning("[Domínio] BM BLOQUEADA detectada na página de domínios!")
            if callback_status:
                callback_status("🚫 BM BLOQUEADA — não adianta verificar domínio")
            return {'sucesso': False, 'mensagem': 'BM bloqueada na página de domínios',
                    'verificado': False, 'bm_bloqueada': True}

        # Fechar overlays que possam bloquear
        _fechar_overlays_facebook(driver)
        _delay_curto()

        # ===== PASSO 2: Clicar "Adicionar" e GARANTIR que o dialog abriu =====
        # Princípio: só avança quando CONFIRMA que chegou na próxima tela (o dialog).
        # Se o clique não pegou / a bolha "Salvar endereço?" do navegador
        # interceptou / a conexão oscilou e voltou na MESMA tela, dá F5 e refaz o
        # clique — repete até o dialog realmente abrir.
        dialog_aberto = False
        for _tent_add in range(1, 4):
            if callback_status:
                callback_status(f"➕ Clicando em Adicionar domínio... (tentativa {_tent_add})")

            # Dispensa a bolha nativa do navegador ("Salvar endereço?") e overlays
            # do Facebook que possam interceptar o clique.
            try:
                driver.keyboard.press('Escape')
            except Exception:
                pass
            _fechar_overlays_facebook(driver)
            _delay_curto()

            add_clicou = _clicar_botao(driver, "Adicionar", timeout=8000)
            if not add_clicou:
                add_clicou = _clicar_botao(driver, "Add", timeout=4000)
            if not add_clicou:
                try:
                    btn_add = driver.query_selector(
                        '[aria-label="Adicionar"], [aria-label="Add"]')
                    if btn_add:
                        _clicar_humano(driver, btn_add)
                        add_clicou = True
                except Exception:
                    pass

            # VERIFICAÇÃO: o dialog abriu de fato? (chegou no próximo passo)
            _fim_dlg = time.time() + 12
            while time.time() < _fim_dlg:
                if _dialog_dominio_aberto(driver):
                    dialog_aberto = True
                    break
                time.sleep(0.15)
            if dialog_aberto:
                break

            # Não abriu -> F5 (recarrega a tela de domínios) e tenta de novo.
            logger.warning("[Domínio] Dialog NÃO abriu após clicar 'Adicionar' "
                           "(tentativa %s) — dando F5 e refazendo.", _tent_add)
            if callback_status:
                callback_status("🔄 Dialog não abriu — atualizando (F5) e refazendo o clique...")
            try:
                driver.goto(url_dominios)
            except Exception:
                try:
                    driver.refresh()
                except Exception:
                    pass
            _esperar_pagina(driver, 30)
            _aguardar_elemento(driver, '[role="button"]', timeout=20,
                               descricao='botões da página de domínios (pós-F5)')
            _fechar_overlays_facebook(driver)
            _delay_curto()

        if not dialog_aberto:
            return {'sucesso': False,
                    'mensagem': 'Dialog de adicionar domínio não abriu (após F5/retentativas)',
                    'verificado': False}

        # ===== PASSO 3: Selecionar "Criar um domínio" =====
        # IMPORTANTE: O popup mostra 2 opções:
        #   1. "Criar um domínio" — Você precisa de um novo domínio para sua empresa.
        #   2. "Solicitar acesso a um domínio" — Sua empresa precisa usar este ativo em nome de outra.
        # É OBRIGATÓRIO clicar em "Criar um domínio" PRIMEIRO para que o campo
        # de input do domínio apareça. Sem clicar, o campo NÃO existe no popup.
        if callback_status:
            callback_status("📝 Selecionando 'Criar um domínio'...")
        _delay_medio()
        _delay_leitura()  # Aguardar o conteúdo do popup carregar completamente

        criar_clicou = False

        # Estratégia 1: Buscar elemento clicável com texto "Criar um domínio"
        # O popup do Facebook usa divs/spans clicáveis, não radio buttons tradicionais
        try:
            # Buscar todos os elementos no dialog que podem ser clicáveis
            resultado_criar = driver.evaluate_page("""() => {
                var dialog = document.querySelector('[role="dialog"]');
                if (!dialog) return {encontrou: false};

                // Buscar TODOS os elementos que contêm "Criar um domínio" ou "Create a domain"
                var allElements = dialog.querySelectorAll('div, span, label, a, li, p');
                for (var i = 0; i < allElements.length; i++) {
                    var el = allElements[i];
                    var txt = (el.innerText || el.textContent || '').trim().toLowerCase();

                    // Texto deve conter "criar um domínio" mas NÃO ser um texto muito longo
                    // (para não pegar o container pai que tem os 2 textos)
                    if (txt.length > 5 && txt.length < 100 &&
                        (txt.indexOf('criar um domínio') !== -1 ||
                         txt.indexOf('criar um dominio') !== -1 ||
                         txt.indexOf('create a domain') !== -1)) {

                        // Verificar se NÃO contém "solicitar acesso" (seria o container pai)
                        if (txt.indexOf('solicitar acesso') !== -1 ||
                            txt.indexOf('request access') !== -1) {
                            continue;
                        }

                        el.setAttribute('data-criar-dominio', '1');
                        return {encontrou: true, texto: txt.substring(0, 60)};
                    }
                }
                return {encontrou: false};
            }""")

            if resultado_criar and resultado_criar.get('encontrou'):
                el_criar = driver.query_selector('[data-criar-dominio="1"]')
                if el_criar:
                    logger.info("[Domínio] Encontrou 'Criar um domínio': %s",
                                resultado_criar.get('texto', ''))
                    _clicar_humano(driver, el_criar)
                    criar_clicou = True
        except Exception as exc:
            logger.warning("[Domínio] Erro na busca JS por 'Criar um domínio': %s", exc)

        # Estratégia 2: Buscar via query_selector com :has-text
        if not criar_clicou:
            try:
                for seletor in [
                    '[role="dialog"] div:has-text("Criar um domínio")',
                    '[role="dialog"] span:has-text("Criar um domínio")',
                    '[role="dialog"] div:has-text("Create a domain")',
                ]:
                    try:
                        el = driver.query_selector(seletor)
                        if el:
                            _clicar_humano(driver, el)
                            criar_clicou = True
                            logger.info("[Domínio] Clicou 'Criar um domínio' via seletor: %s", seletor)
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        # Estratégia 3: Buscar diretamente por spans/labels
        if not criar_clicou:
            try:
                opcoes = driver.query_selector_all(
                    '[role="dialog"] [role="radio"], '
                    '[role="dialog"] [role="option"], '
                    '[role="dialog"] label, '
                    '[role="dialog"] span')
                for op in opcoes:
                    txt = (op.text_content() or '').strip().lower()
                    if any(t in txt for t in [
                        'criar um domínio', 'create a domain', 'criar domínio'
                    ]):
                        # Verificar que não é o container com as 2 opções
                        if 'solicitar acesso' not in txt:
                            _clicar_humano(driver, op)
                            criar_clicou = True
                            break
            except Exception:
                pass

        # Estratégia 4: Clicar no primeiro item/opção do popup (geralmente é "Criar")
        if not criar_clicou:
            try:
                radios = driver.query_selector_all(
                    '[role="dialog"] input[type="radio"]')
                for radio in radios:
                    label_txt = radio.evaluate('''el => {
                        let label = el.closest("label");
                        return label ? label.textContent.trim() : "";
                    }''')
                    if 'criar' in (label_txt or '').lower():
                        _clicar_humano(driver, radio)
                        criar_clicou = True
                        break
            except Exception:
                pass

        if not criar_clicou:
            logger.error("[Domínio] NÃO conseguiu clicar em 'Criar um domínio' — "
                         "tentando continuar mesmo assim")

        # AGUARDAR após clicar em "Criar um domínio" para o campo de input aparecer
        # Este é o ponto crítico: sem esta espera, o campo de input NÃO existe
        _delay_medio()
        _delay_longo()  # Dar tempo extra para o Facebook renderizar o campo de input

        # ===== CHECK BLOQUEIO 2: Dentro do dialog — verificar se a mensagem
        # de bloqueio está visível ATRÁS do dialog =====
        if detectar_bm_bloqueada_verificacao(driver):
            logger.warning("[Domínio] BM BLOQUEADA detectada dentro do dialog de domínio!")
            if callback_status:
                callback_status("🚫 BM BLOQUEADA — cancelando adição de domínio")
            # Fechar o dialog antes de retornar
            try:
                _clicar_botao_no_dialog(driver, ['Cancelar', 'Cancel'])
            except Exception:
                pass
            return {'sucesso': False, 'mensagem': 'BM bloqueada durante adição de domínio',
                    'verificado': False, 'bm_bloqueada': True}

        # ===== PASSO 4: Digitar o domínio =====
        if callback_status:
            callback_status(f"⌨️ Digitando domínio: {dominio}")

        # Aguardar que o campo de input esteja disponível no dialog
        # Após clicar em "Criar um domínio", o Facebook renderiza um novo campo
        try:
            _aguardar_elemento(driver, '[role="dialog"] input[type="text"], '
                               '[role="dialog"] input:not([type])',
                               timeout=15,
                               descricao='campo de domínio (após clicar Criar)')
        except Exception:
            # Se não encontrou por seletor específico, tentar genérico
            _aguardar_elemento(driver, '[role="dialog"] input', timeout=10,
                               descricao='campo de domínio no dialog')
        _delay_curto()
        _delay_medio()  # Espera extra para React renderizar

        dominio_limpo = dominio.replace('https://', '').replace(
            'http://', '').rstrip('/')
        preencheu = False

        campo = _encontrar_input_por_contexto(
            driver,
            ['Seu domínio', 'Your domain', 'Domínio', 'Domain'],
            ['exemplo.com', 'example.com', 'exemplo.com ou exemplo.com.br']
        )

        if campo:
            preencheu = _limpar_e_digitar(driver, campo, dominio_limpo, 'dominio')
        else:
            try:
                dialog_inputs = driver.query_selector_all(
                    '[role="dialog"] input[type="text"], '
                    '[role="dialog"] input:not([type])')
                if dialog_inputs:
                    preencheu = _limpar_e_digitar(
                        driver, dialog_inputs[-1], dominio_limpo, 'dominio_fallback')
            except Exception:
                pass

        if not preencheu:
            return {'sucesso': False, 'mensagem': 'Não encontrou campo de domínio',
                    'verificado': False}

        # Aguardar React processar o valor digitado
        _delay_medio()

        # ===== PASSO 5: Clicar em "Adicionar" (dentro do popup) =====
        if callback_status:
            callback_status("➕ Confirmando adição do domínio...")

        salvou = _clicar_botao_no_dialog(driver, ['Adicionar', 'Add'])
        if not salvou:
            _clicar_botao(driver, "Adicionar", timeout=5000)

        _delay_longo()
        _esperar_pagina(driver, 20)
        _delay_longo()

        # Aguardar que a página de verificação do domínio carregue
        # (após adicionar, Facebook mostra a meta tag de verificação)
        _aguardar_elemento(driver, 'body', timeout=15,
                           descricao='página pós-adição de domínio')
        _delay_medio()

        # ===== CHECK BLOQUEIO 3: Após adicionar domínio, antes de extrair meta =====
        if detectar_bm_bloqueada_verificacao(driver):
            logger.warning("[Domínio] BM BLOQUEADA detectada após adicionar domínio!")
            if callback_status:
                callback_status("🚫 BM BLOQUEADA — domínio adicionado mas BM restrita")
            return {'sucesso': False, 'mensagem': 'BM bloqueada após adicionar domínio',
                    'verificado': False, 'bm_bloqueada': True}

        # ===== PASSO 6: Selecionar aba "Meta Tag" (caso Facebook mostre DNS por padrão) =====
        if callback_status:
            callback_status("🏷️ Selecionando método Meta Tag...")

        _tentar_selecionar_aba_meta_tag(driver)
        _delay_medio()

        # ===== PASSO 7: Extrair Meta Tag =====
        if callback_status:
            callback_status("🔍 Extraindo Meta Tag de verificação...")

        _delay_longo()

        meta_tag = _extrair_meta_tag(driver)

        if not meta_tag:
            # Segunda tentativa com mais espera
            _delay_longo()
            _delay_medio()
            meta_tag = _extrair_meta_tag(driver)

        if not meta_tag:
            # Terceira tentativa: scroll + espera
            _scroll_suave(driver, 'baixo', 300)
            _delay_longo()
            meta_tag = _extrair_meta_tag(driver)

        if not meta_tag:
            # Quarta tentativa: recarregar seção (pode ser que o conteúdo
            # seja lazy-loaded)
            _scroll_suave(driver, 'cima', 300)
            _delay_medio()
            _scroll_suave(driver, 'baixo', 200)
            _delay_longo()
            meta_tag = _extrair_meta_tag(driver)

        # ===== FALLBACK: DNS TXT (quando Meta Tag não está disponível) =====
        if not meta_tag:
            if callback_status:
                callback_status("⚠️ Meta Tag não encontrada — tentando DNS TXT como fallback...")

            # Tentar clicar aba DNS TXT no Facebook
            _tentar_selecionar_aba_dns_txt(driver)
            _delay_medio()

            dns_txt_valor = _extrair_dns_txt_verification(driver)

            if dns_txt_valor and salvar_meta_func:
                if callback_status:
                    callback_status(f"🔤 DNS TXT extraído: {dns_txt_valor[:40]}...")

                # Tentar salvar via função dedicada (se disponível)
                try:
                    import server.acesso as _acesso_mod
                    if hasattr(_acesso_mod, 'salvar_dns_txt_site'):
                        res_dns = _acesso_mod.salvar_dns_txt_site(site_id, dns_txt_valor, telefone_site)
                        if res_dns.get('sucesso'):
                            if callback_status:
                                callback_status("✅ DNS TXT adicionado! Aguardando propagação (30s)...")
                            _delay(15, 20)
                            _delay(12, 15)

                            # Tentar verificar após DNS TXT
                            for _t in range(1, 4):
                                _clicar_botao(driver, 'Verificar domínio', timeout=8000) or \
                                _clicar_botao(driver, 'Verify domain', timeout=4000)
                                _delay(15, 20)
                                if _verificar_status_dominio(driver):
                                    if callback_status:
                                        callback_status(f"✅ Domínio verificado via DNS TXT! ({_t}ª tentativa)")
                                    return {'sucesso': True, 'mensagem': 'Domínio verificado via DNS TXT!',
                                            'verificado': True}
                                if _t < 3:
                                    _delay(10, 15)
                except Exception as _dns_err:
                    logger.warning("[Domínio] Erro no fallback DNS TXT: %s", _dns_err)

            return {
                'sucesso': True,
                'mensagem': f'Domínio adicionado — meta tag não extraída{(", DNS TXT: " + dns_txt_valor) if dns_txt_valor else ""}',
                'verificado': False,
                'dns_txt': dns_txt_valor or '',
            }

        if callback_status:
            callback_status(f"✅ Meta tag extraída: {meta_tag[:60]}...")

        # ===== PASSO 7: Salvar meta tag no site via API =====
        if callback_status:
            callback_status("💾 Salvando meta tag no site...")

        resultado_meta = salvar_meta_func(site_id, meta_tag, telefone_site)
        if not resultado_meta.get('sucesso'):
            logger.error("[Verificação] Falha ao salvar meta tag: %s",
                         resultado_meta.get('mensagem'))
            return {
                'sucesso': False,
                'mensagem': f'Falha salvar meta tag: {resultado_meta.get("mensagem")}',
                'verificado': False,
            }

        if callback_status:
            callback_status("✅ Meta tag salva no site! Aguardando propagação...")

        # O microsite JÁ está no ar (a meta tag é servida na hora), então não
        # adianta dormir muito — o crawler da Meta busca on-demand ao clicar em
        # "Verificar domínio", e as 3 tentativas abaixo já dão margem. Curto.
        _delay(6, 9)

        # ===== PASSO 8: Verificar domínio =====
        # ANTES de clicar em "Verificar domínio", checar se já está verificado
        if callback_status:
            callback_status("🔍 Verificando se domínio já está verificado...")

        ja_verificado = _verificar_status_dominio(driver)
        if ja_verificado:
            if callback_status:
                callback_status("✅ Domínio já estava verificado!")
            return {
                'sucesso': True,
                'mensagem': 'Domínio já verificado',
                'verificado': True,
            }

        # MÉTODO FIXADO PELO USUÁRIO: se escolheu DNS ou ARQUIVO, verifica direto por
        # ele (sem depender da meta-tag). Se não confirmar, ainda cai na meta-tag abaixo
        # como rede de segurança.
        if _METODO_VERIFICACAO in ('dns', 'arquivo'):
            if callback_status:
                callback_status(f"🔀 Método fixo: verificando por {_METODO_VERIFICACAO.upper()} (sem meta-tag).")
            _fbfix = _verificar_dominio_fallbacks(driver, site_id, meta_tag, telefone_site,
                                                  callback_status, metodos=(_METODO_VERIFICACAO,))
            if _fbfix and _fbfix.get('verificado'):
                return _fbfix

        # Até 3 tentativas de verificar
        for tentativa in range(1, 4):
            if callback_status:
                callback_status(f"🔄 Clicando 'Verificar domínio' ({tentativa}ª tentativa)...")

            _delay_curto()

            # ============================================================
            # CLICAR NO BOTÃO "Verificar domínio" usando múltiplas estratégias
            # O botão do Facebook tem:
            #   - data-surface contendo "verify-domain-button"
            #   - role="button" com texto "Verificar domínio"
            #   - Texto direto via innerText
            # ============================================================
            verificou_click = False

            # Estratégia 1: Buscar via data-surface (seletor mais confiável)
            try:
                btn_verify = driver.query_selector('[data-surface*="verify-domain"]')
                if btn_verify:
                    # Scroll para garantir que o botão está visível
                    try:
                        btn_verify.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    _delay(0.3, 0.5)
                    _clicar_humano(driver, btn_verify)
                    verificou_click = True
                    logger.info("[Domínio] Clicou Verificar via data-surface")
            except Exception as exc:
                logger.warning("[Domínio] data-surface falhou: %s", exc)

            # Estratégia 2: Buscar via JS — encontrar botão com texto exato
            if not verificou_click:
                try:
                    clicou_js = driver.evaluate_page("""() => {
                        // Buscar todos role=button
                        var btns = document.querySelectorAll('[role="button"]');
                        for (var i = 0; i < btns.length; i++) {
                            var txt = (btns[i].innerText || '').trim().toLowerCase();
                            if (txt === 'verificar dom\u00ednio' || txt === 'verificar dominio' ||
                                txt === 'verify domain') {
                                // Scroll into view
                                btns[i].scrollIntoView({block: 'center'});
                                // Click
                                btns[i].click();
                                return true;
                            }
                        }
                        // Fallback: buscar divs/spans com texto e clicar
                        var els = document.querySelectorAll('div, span');
                        for (var j = 0; j < els.length; j++) {
                            var t = (els[j].innerText || '').trim().toLowerCase();
                            // Texto exato (não substring) para evitar clicar no container
                            if ((t === 'verificar dom\u00ednio' || t === 'verificar dominio' ||
                                 t === 'verify domain') && els[j].offsetWidth > 0) {
                                els[j].scrollIntoView({block: 'center'});
                                els[j].click();
                                return true;
                            }
                        }
                        return false;
                    }""")
                    if clicou_js:
                        verificou_click = True
                        logger.info("[Domínio] Clicou Verificar via JS click")
                except Exception as exc:
                    logger.warning("[Domínio] JS click falhou: %s", exc)

            # Estratégia 3: _clicar_botao genérico
            if not verificou_click:
                verificou_click = _clicar_botao(driver, "Verificar dom\u00ednio", timeout=10000)
            if not verificou_click:
                verificou_click = _clicar_botao(driver, "Verify domain", timeout=5000)

            # Estratégia 4: aria-label
            if not verificou_click:
                try:
                    btn = driver.query_selector(
                        '[aria-label*="Verificar"], [aria-label*="Verify"]')
                    if btn:
                        try:
                            btn.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        _delay(0.3, 0.5)
                        _clicar_humano(driver, btn)
                        verificou_click = True
                except Exception:
                    pass

            if not verificou_click:
                logger.warning("[Domínio] Botão Verificar não encontrado (tentativa %d)",
                               tentativa)
                # Scroll para baixo para tentar encontrar o botão
                _scroll_suave(driver, 'baixo', 400)
                _delay_medio()
                continue

            # ============================================================
            # POLL do status (em vez de dormir 15-18s cego): o Facebook confirma a
            # meta tag em ~4-8s; verificamos a cada ~2s e SEGUIMOS NA HORA em que
            # aparecer "Verified" (teto de 16s por tentativa).
            # ============================================================
            if callback_status:
                callback_status(f"⏳ Aguardando a Meta confirmar o domínio ({tentativa}ª tentativa)...")
            verificado = False
            _fim_poll = time.time() + 16
            while time.time() < _fim_poll:
                _delay(1.5, 2.5)
                if _verificar_status_dominio(driver):
                    verificado = True
                    break

            if verificado:
                if callback_status:
                    callback_status(
                        f"✅ Domínio VERIFICADO com sucesso! ({tentativa}ª tentativa)")
                return {
                    'sucesso': True,
                    'mensagem': f'Domínio verificado ({tentativa}ª tentativa)',
                    'verificado': True,
                }

            # Checar mensagem "já foi verificado por outra empresa" = sucesso
            try:
                page_text = (driver.text_content('body') or '').lower()
                if ('j\u00e1 foi verificado' in page_text or
                    'ja foi verificado' in page_text or
                    'already been verified' in page_text):
                    if callback_status:
                        callback_status("✅ Domínio verificado (por outra empresa)!")
                    return {
                        'sucesso': True,
                        'mensagem': 'Domínio verificado (por outra empresa)',
                        'verificado': True,
                    }
            except Exception:
                pass

            if tentativa < 3:
                espera = 10 + (tentativa * 5)
                if callback_status:
                    callback_status(
                        f"⏳ Aguardando {espera}s antes da próxima tentativa...")
                _delay(espera, espera + 3)

        # META-TAG NÃO CONFIRMOU → fallback automático (DNS e depois ARQUIVO HTML),
        # a menos que o usuário tenha FIXADO só meta-tag na GUI. É o que resolve
        # "a Meta não está verificando via meta tag agora" (2026-09-30).
        if _METODO_VERIFICACAO != 'metatag':
            _fb = _verificar_dominio_fallbacks(driver, site_id, meta_tag, telefone_site,
                                               callback_status, metodos=('dns', 'arquivo'))
            if _fb and _fb.get('verificado'):
                return _fb

        if callback_status:
            callback_status("⚠️ Domínio adicionado mas verificação pendente (meta-tag/DNS/arquivo)")
        return {
            'sucesso': True,
            'mensagem': 'Domínio adicionado, verificação pendente',
            'verificado': False,
        }

    except Exception as e:
        logger.error("[Verificação] Erro ao adicionar/verificar domínio: %s",
                     e, exc_info=True)
        return {'sucesso': False, 'mensagem': f'Erro: {str(e)}', 'verificado': False}


def _clicar_botao_no_dialog(driver, textos):
    """Clica em um botão dentro do dialog com um dos textos fornecidos."""
    try:
        botoes = driver.query_selector_all('[role="dialog"] [role="button"]')
        for btn in botoes:
            txt = (btn.text_content() or '').strip().lower()
            for texto in textos:
                if txt == texto.lower() or texto.lower() in txt:
                    _clicar_humano(driver, btn)
                    return True
    except Exception:
        pass

    for texto in textos:
        if _clicar_botao(driver, texto, timeout=3000):
            return True

    return False


def _tentar_selecionar_aba_meta_tag(driver):
    """
    Clica na aba/opção 'Meta Tag HTML' no Facebook se não estiver selecionada.
    O Facebook pode mostrar 'DNS TXT Record' como padrão em algumas contas.
    """
    try:
        clicou = driver.evaluate_page("""() => {
            var termos = [
                'meta tag html', 'html meta tag', 'meta tag', 'html tag',
                'metatag', 'tag html', 'tag meta'
            ];
            var els = document.querySelectorAll(
                '[role="tab"], [role="radio"], [role="option"], [role="button"], ' +
                'div, span, label, li'
            );
            for (var i = 0; i < els.length; i++) {
                var txt = (els[i].innerText || els[i].textContent || '').trim().toLowerCase();
                if (txt.length < 5 || txt.length > 60) continue;
                for (var t = 0; t < termos.length; t++) {
                    if (txt.indexOf(termos[t]) !== -1) {
                        els[i].scrollIntoView({block: 'center'});
                        els[i].click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        if clicou:
            logger.info("[Domínio] Aba Meta Tag clicada com sucesso")
    except Exception as exc:
        logger.warning("[Domínio] Erro ao clicar aba Meta Tag: %s", exc)


def _tentar_selecionar_aba_dns_txt(driver):
    """Clica na aba 'DNS TXT Record' no Facebook para exibir o valor do registro DNS."""
    try:
        driver.evaluate_page("""() => {
            var termos = [
                'dns', 'txt record', 'registro txt', 'dns txt', 'txt dns',
                'registro dns', 'dns record'
            ];
            var els = document.querySelectorAll(
                '[role="tab"], [role="radio"], [role="option"], [role="button"], ' +
                'div, span, label, li'
            );
            for (var i = 0; i < els.length; i++) {
                var txt = (els[i].innerText || els[i].textContent || '').trim().toLowerCase();
                if (txt.length < 2 || txt.length > 60) continue;
                for (var t = 0; t < termos.length; t++) {
                    if (txt.indexOf(termos[t]) !== -1) {
                        els[i].scrollIntoView({block: 'center'});
                        els[i].click();
                        return true;
                    }
                }
            }
            return false;
        }""")
    except Exception as exc:
        logger.warning("[Domínio] Erro ao clicar aba DNS TXT: %s", exc)


def _extrair_dns_txt_verification(driver):
    """
    Extrai o valor do registro TXT DNS de verificação do Facebook.
    O registro TXT tem o formato: facebook-domain-verification=XXXXXX
    Retorna apenas o HASH de verificação (parte após '=').
    """
    try:
        page_text = driver.text_content('body') or ''

        # Padrão 1: facebook-domain-verification=HASH (registro TXT raw)
        m = re.search(r'facebook-domain-verification=([a-zA-Z0-9_-]{10,})', page_text)
        if m:
            return m.group(1)

        # Padrão 2: "facebook-domain-verification" seguido do hash em elemento separado
        for sel in ['code', 'pre', 'span', 'div', 'p', 'td']:
            try:
                elements = driver.query_selector_all(sel)
                for el in elements:
                    txt = el.text_content() or ''
                    if 'facebook-domain-verification' in txt.lower():
                        m2 = re.search(r'facebook-domain-verification=([a-zA-Z0-9_-]{10,})', txt)
                        if m2:
                            return m2.group(1)
                        # Ou só o hash (se `=` já foi mostrado antes)
                        m3 = re.search(r'\b([a-zA-Z0-9]{20,64})\b', txt)
                        if m3:
                            return m3.group(1)
            except Exception:
                continue
    except Exception as exc:
        logger.error("[Domínio] Erro ao extrair DNS TXT: %s", exc)
    return None


def _codigo_da_meta_tag(meta_tag: str) -> str:
    """Extrai só o CODE de '<meta ... content="CODE" />' (o mesmo p/ DNS e arquivo)."""
    if not meta_tag:
        return ''
    m = re.search(r'content=["\']([^"\']+)["\']', meta_tag)
    if m:
        return m.group(1).strip()
    # já pode vir como o código puro
    m2 = re.search(r'\b([a-z0-9]{20,64})\b', meta_tag)
    return m2.group(1) if m2 else ''


def _clicar_verificar_dominio(driver) -> bool:
    """Clica 'Verificar domínio' (várias estratégias)."""
    try:
        b = driver.query_selector('[data-surface*="verify-domain"]')
        if b:
            try: b.scroll_into_view_if_needed()
            except Exception: pass
            _clicar_humano(driver, b); return True
    except Exception:
        pass
    try:
        ok = driver.evaluate_page("""() => {
            var alvo=['verificar domínio','verificar dominio','verify domain'];
            var els=document.querySelectorAll('[role="button"],div,span');
            for (var i=0;i<els.length;i++){var t=(els[i].innerText||'').trim().toLowerCase();
              if(alvo.indexOf(t)!==-1 && els[i].offsetWidth>0){els[i].scrollIntoView({block:'center'});els[i].click();return true;}}
            return false; }""")
        if ok: return True
    except Exception:
        pass
    return _clicar_botao(driver, "Verificar domínio", timeout=8000) or \
           _clicar_botao(driver, "Verify domain", timeout=4000)


def _poll_dominio_verificado(driver, timeout=18) -> bool:
    fim = time.time() + timeout
    while time.time() < fim:
        _delay(1.5, 2.5)
        if _verificar_status_dominio(driver):
            return True
    return False


def _tentar_selecionar_aba_arquivo(driver):
    """Clica na aba 'Carregar arquivo HTML' / 'Upload HTML file' no Meta."""
    try:
        driver.evaluate_page("""() => {
            var termos=['carregar arquivo','upload','arquivo html','html file','carregar html','file upload'];
            var els=document.querySelectorAll('[role="tab"],[role="radio"],[role="option"],[role="button"],div,span,label,li');
            for (var i=0;i<els.length;i++){var t=(els[i].innerText||els[i].textContent||'').trim().toLowerCase();
              if(t.length<3||t.length>60)continue;
              for(var k=0;k<termos.length;k++){ if(t.indexOf(termos[k])!==-1){els[i].scrollIntoView({block:'center'});els[i].click();return true;} }}
            return false; }""")
    except Exception as exc:
        logger.warning("[Domínio] aba arquivo: %s", exc)


def _extrair_arquivo_verificacao(driver, code: str):
    """Nome + conteúdo do arquivo HTML de verificação do Meta.
    O arquivo do FB chama-se '<code>.html' e o conteúdo é o próprio código de
    verificação. Se a página mostrar um nome diferente, usamos o que estiver na tela."""
    nome = f"{code}.html" if code else ''
    conteudo = code or ''
    try:
        page = driver.text_content('body') or ''
        m = re.search(r'([A-Za-z0-9_\-]+\.html)', page)
        if m:
            nome = m.group(1)
    except Exception:
        pass
    if not nome or not conteudo:
        return None
    return {'nome': nome, 'conteudo': conteudo}


def _verificar_dominio_fallbacks(driver, site_id, meta_tag, telefone_site,
                                 callback_status=None, metodos=('dns', 'arquivo')):
    """Meta-tag não confirmou → tenta os métodos alternativos na ordem dada.
    Devolve dict de sucesso {'sucesso','verificado','mensagem','metodo'} ou None."""
    import server.acesso as _acesso
    code = _codigo_da_meta_tag(meta_tag)

    def _s(msg):
        if callback_status:
            callback_status(msg)

    for metodo in metodos:
        try:
            if metodo == 'dns':
                if not code:
                    continue
                _s("🌐 Verificando por DNS TXT (Cloudflare)...")
                r = _acesso.salvar_dns_txt_site(site_id, code, telefone_site) \
                    if hasattr(_acesso, 'salvar_dns_txt_site') else {'sucesso': False}
                if not r.get('sucesso'):
                    _s(f"⚠️ DNS TXT não pôde ser criado: {r.get('mensagem', '')}")
                    continue
                _s("✅ TXT criado — aguardando propagação e confirmando...")
                _tentar_selecionar_aba_dns_txt(driver)
                _delay_medio()
                for t in range(1, 4):
                    _delay(14, 20)
                    _clicar_verificar_dominio(driver)
                    if _poll_dominio_verificado(driver, 18):
                        _s(f"✅ Domínio VERIFICADO via DNS TXT! ({t}ª tentativa)")
                        return {'sucesso': True, 'verificado': True,
                                'mensagem': 'Verificado via DNS TXT', 'metodo': 'dns'}

            elif metodo == 'arquivo':
                _s("📄 Verificando por ARQUIVO HTML na raiz...")
                _tentar_selecionar_aba_arquivo(driver)
                _delay_medio()
                arq = _extrair_arquivo_verificacao(driver, code)
                if not arq:
                    _s("⚠️ Não consegui montar o arquivo de verificação.")
                    continue
                r = _acesso.salvar_arquivo_verificacao_site(site_id, arq['nome'], arq['conteudo']) \
                    if hasattr(_acesso, 'salvar_arquivo_verificacao_site') else {'sucesso': False}
                if not r.get('sucesso'):
                    _s(f"⚠️ Arquivo não pôde ser publicado: {r.get('mensagem', '')}")
                    continue
                _s("✅ Arquivo publicado na raiz — confirmando...")
                for t in range(1, 4):
                    _delay(6, 10)
                    _clicar_verificar_dominio(driver)
                    if _poll_dominio_verificado(driver, 16):
                        _s(f"✅ Domínio VERIFICADO via arquivo HTML! ({t}ª tentativa)")
                        return {'sucesso': True, 'verificado': True,
                                'mensagem': 'Verificado via arquivo HTML', 'metodo': 'arquivo'}
        except Exception as e:
            logger.warning("[Domínio] fallback %s falhou: %s", metodo, e)
    return None


def _extrair_meta_tag(driver):
    """Extrai a meta tag de verificação do Facebook da página atual."""
    try:
        page_text = driver.text_content('body') or ''

        match = re.search(
            r'<meta\s+name=["\']facebook-domain-verification["\']\s+'
            r'content=["\']([^"\']+)["\']',
            page_text
        )
        if match:
            val = match.group(1)
            return f'<meta name="facebook-domain-verification" content="{val}" />'

        for sel in ['code', 'pre', 'span', 'div', 'p']:
            try:
                elements = driver.query_selector_all(sel)
                for el in elements:
                    txt = el.text_content() or ''
                    if 'facebook-domain-verification' in txt:
                        m = re.search(
                            r'<meta\s+name=["\']facebook-domain-verification["\']\s+'
                            r'content=["\']([^"\']+)["\']',
                            txt
                        )
                        if m:
                            return (f'<meta name="facebook-domain-verification" '
                                    f'content="{m.group(1)}" />')

                        m2 = re.search(r'content=["\']([a-z0-9]+)["\']', txt)
                        if m2:
                            return (f'<meta name="facebook-domain-verification" '
                                    f'content="{m2.group(1)}" />')
            except Exception:
                continue

        try:
            steps = driver.query_selector_all('li, p, div, span')
            for step in steps:
                txt = step.text_content() or ''
                if ('metatag' in txt.lower() or 'meta tag' in txt.lower()) \
                        and 'content=' in txt:
                    m3 = re.search(r'content=["\']([a-z0-9]+)["\']', txt)
                    if m3:
                        return (f'<meta name="facebook-domain-verification" '
                                f'content="{m3.group(1)}" />')
        except Exception:
            pass

        return None

    except Exception as e:
        logger.error("[Verificação] Erro ao extrair meta tag: %s", e)
        return None


def _verificar_status_dominio(driver):
    """Verifica se o domínio foi verificado com sucesso.

    Usa os seletores exatos do Facebook para detectar o status:
      - Verificado: role="status" com data-sscoverage-ignore contendo texto "Verified"
      - Não verificado: mesmo elemento com texto "Not Verified"
      - Badge div com texto exato "Verified" vs "Not Verified"

    Returns:
        True se o domínio está verificado
    """
    try:
        resultado = driver.evaluate_page("""() => {
            // ============================================================
            // ESTRATÉGIA 1 (MAIS PRECISA): Buscar role="status" com data-sscoverage-ignore
            // HTML verificado: <div aria-atomic="true" aria-live="polite" role="status"
            //   class="..." data-sscoverage-ignore="true">Verified</div>
            // HTML não verificado: mesmo mas com texto "Not Verified"
            // ============================================================
            var statusEls = document.querySelectorAll('[role="status"][data-sscoverage-ignore]');
            for (var i = 0; i < statusEls.length; i++) {
                var txt = (statusEls[i].textContent || '').trim();
                var txtLower = txt.toLowerCase();
                if (txtLower === 'verified') {
                    return {verificado: true, motivo: 'role_status_verified', texto: txt};
                }
                if (txtLower === 'not verified') {
                    return {verificado: false, motivo: 'role_status_not_verified', texto: txt};
                }
            }

            // ============================================================
            // ESTRATÉGIA 2: Buscar role="status" sem data-sscoverage-ignore
            // ============================================================
            var statusEls2 = document.querySelectorAll('[role="status"]');
            for (var j = 0; j < statusEls2.length; j++) {
                var txt2 = (statusEls2[j].textContent || '').trim();
                var txt2Lower = txt2.toLowerCase();
                if (txt2Lower === 'verified') {
                    return {verificado: true, motivo: 'role_status_verified_2', texto: txt2};
                }
                if (txt2Lower === 'not verified') {
                    return {verificado: false, motivo: 'role_status_not_verified_2', texto: txt2};
                }
            }

            // ============================================================
            // ESTRATÉGIA 3: Buscar divs/spans com texto EXATO "Verified" ou "Not Verified"
            // O badge do Facebook usa classes x1vvvo52 xw23nyj x63nzvj etc.
            // ============================================================
            var allEls = document.querySelectorAll('div, span');
            for (var k = 0; k < allEls.length; k++) {
                var el = allEls[k];
                // Pegar só o texto direto do elemento (sem filhos)
                var directText = '';
                for (var n = 0; n < el.childNodes.length; n++) {
                    if (el.childNodes[n].nodeType === 3) { // TEXT_NODE
                        directText += el.childNodes[n].textContent;
                    }
                }
                directText = directText.trim().toLowerCase();

                // Apenas considerar elementos com texto curto (badge)
                if (directText.length > 20) continue;

                if (directText === 'not verified' || directText === 'não verificado' ||
                    directText === 'nao verificado') {
                    return {verificado: false, motivo: 'badge_not_verified', texto: directText};
                }
                if (directText === 'verified' || directText === 'verificado') {
                    return {verificado: true, motivo: 'badge_verified', texto: directText};
                }
            }

            // ============================================================
            // ESTRATÉGIA 4: Buscar texto "já foi verificado" (por outra empresa)
            // ============================================================
            var bodyText = (document.body.innerText || '').toLowerCase();
            if (bodyText.indexOf('já foi verificado') !== -1 ||
                bodyText.indexOf('ja foi verificado') !== -1 ||
                bodyText.indexOf('already been verified') !== -1 ||
                bodyText.indexOf('already verified') !== -1) {
                return {verificado: true, motivo: 'ja_verificado_outra_empresa'};
            }

            return {verificado: false, motivo: 'nenhum_indicador_encontrado'};
        }""")

        if resultado and resultado.get('verificado'):
            logger.info("[Domínio] ✅ Verificado! Motivo: %s",
                        resultado.get('motivo', 'desconhecido'))
            return True
        else:
            logger.info("[Domínio] ❌ Não verificado. Motivo: %s",
                        resultado.get('motivo', 'desconhecido') if resultado else 'sem_resultado')
            return False

    except Exception as e:
        logger.error("[Verificação] Erro ao verificar status: %s", e)
        return False


# ============================================================================
# DETECÇÃO DE BM BLOQUEADA (VERIFICAÇÃO)
# ============================================================================

def detectar_bm_bloqueada_verificacao(driver):
    """
    Detecta se a BM está bloqueada/restrita para anunciar.
    Procura pelos textos e elementos visuais que o Facebook mostra
    quando um portfólio empresarial tem restrições.

    Textos conhecidos (pt-BR e en):
      - "Você não pode usar este portfólio empresarial para anunciar"
      - "Não é possível usar a empresa X para criar anúncios"
      - "Portfólio empresarial com restrições para anunciar"
      - "You can't use this business portfolio to advertise"
      - "restrictions on advertising"

    Returns:
        bool: True se bloqueio detectado
    """
    try:
        return driver.evaluate_page("""() => {
            var body = (document.body.innerText || '').toLowerCase();
            var termos = [
                'não pode usar este portfólio empresarial para anunciar',
                'nao pode usar este portfolio empresarial para anunciar',
                'não é possível usar a empresa',
                'nao e possivel usar a empresa',
                'portfólio empresarial com restrições para anunciar',
                'portfolio empresarial com restricoes para anunciar',
                'restrições para anunciar',
                'restricoes para anunciar',
                'não é possível veicular anúncios',
                'nao e possivel veicular anuncios',
                "you can't use this business portfolio",
                "can't use this business portfolio to advertise",
                'restrictions on advertising',
                'restricted from advertising',
                'business portfolio restricted',
                'account restricted'
            ];
            for (var i = 0; i < termos.length; i++) {
                if (body.indexOf(termos[i]) !== -1) return true;
            }
            // Detectar heading com role="heading" e texto de bloqueio
            var headings = document.querySelectorAll('[role="heading"]');
            for (var h = 0; h < headings.length; h++) {
                var txt = (headings[h].innerText || '').toLowerCase();
                for (var i = 0; i < termos.length; i++) {
                    if (txt.indexOf(termos[i]) !== -1) return true;
                }
            }
            // Detectar banner de restrição (vermelho/laranja no topo)
            var alerts = document.querySelectorAll('[role="alert"], [data-type="error"]');
            for (var a = 0; a < alerts.length; a++) {
                var t = (alerts[a].innerText || '').toLowerCase();
                for (var i = 0; i < termos.length; i++) {
                    if (t.indexOf(termos[i]) !== -1) return true;
                }
            }
            return false;
        }""") or False
    except Exception as exc:
        logger.warning("[Verificação] Erro ao detectar bloqueio BM: %s", exc)
        return False


def checar_restricao_contas_anuncios(driver, business_id, callback_status=None,
                                     momento=''):
    """NAVEGA até a página de CONTAS DE ANÚNCIOS do portfólio e verifica se há
    RESTRIÇÃO ("Você não pode usar este portfólio empresarial para anunciar").

    É a página DEFINITIVA da restrição de anúncios — checar aqui (navegando de
    fato) é mais confiável do que só ler a página atual. Usado como "portão"
    depois de verificar o domínio e depois de preencher a empresa: só segue o
    fluxo se a conta estiver LIMPA.

    Retorna True se a BM estiver RESTRITA; False se estiver limpa (ou em erro de
    navegação — best-effort, não trava o fluxo por falha de rede)."""
    try:
        if callback_status:
            _m = f" ({momento})" if momento else ""
            callback_status(f"🔎 Checando restrição em Contas de anúncios{_m}...")
        url = (f"https://business.facebook.com/latest/settings/ad_accounts"
               f"?business_id={business_id}")
        driver.goto(url)
        _esperar_pagina(driver, 20)
        _delay_medio()
        restrita = detectar_bm_bloqueada_verificacao(driver)
        if restrita:
            logger.warning("[Restrição] BM RESTRITA em Contas de anúncios (%s).", momento)
        else:
            logger.info("[Restrição] SEM restrição em Contas de anúncios (%s).", momento)
        return restrita
    except Exception as exc:
        logger.warning("[Restrição] Falha ao checar Contas de anúncios (%s): %s",
                       momento, exc)
        return False


def _waba_existe_na_bm(driver, business_id):
    """True se a BM JÁ TEM uma conta do WhatsApp (WABA) — estado 'ok' ou 'restrita'.

    Usado p/ decidir se uma restrição de anúncios deve BLOQUEAR ou não (regra do dono
    2026-09-27, provada ao vivo): COM a WABA criada a análise funciona mesmo com a BM
    restrita p/ anúncios → segue; SEM WABA a restrição impede CRIAR a WABA → BM nova.
    Só é chamada QUANDO uma restrição foi detectada (a navegação extra não pesa no
    caminho feliz)."""
    try:
        from server.etapa_verificacao_negocio import _estado_conta_whatsapp
        if _estado_conta_whatsapp(driver, business_id) in ('ok', 'restrita'):
            return True
    except Exception:
        pass
    try:
        return bool(_central_tem_iniciar_verificacao(driver, business_id))
    except Exception:
        return False


# ============================================================================
# AQUECIMENTO DO SITE (anti-cache de MISS da Meta)
# ============================================================================

def _aquecer_site_para_verificacao(site_url, razao_social='', callback_status=None,
                                   tentativas=6, intervalo=5.0):
    """Garante que o microsite responde HTTP 200 ANTES de expor o site à Meta.

    POR QUE: a Meta crawleia o site no instante em que o domínio/empresa é
    verificado. Se o site ainda não subiu/propagou naquele momento, a Meta
    registra o MISS e o CACHEIA -> a BM volta "não verificada" mesmo com o site
    correto depois. Aquecer (esperar 200 + razão social presente) antes de
    verificar elimina esse falso-negativo de timing.

    Best-effort: NUNCA derruba o fluxo. Se não confirmar, loga e segue (o
    servidor já entrega charset=utf-8; isto é só uma rede de segurança de timing).
    Retorna True se confirmou o site no ar.
    """
    import urllib.request
    import ssl
    import unicodedata

    if not site_url:
        return False
    url = site_url.strip()
    if not url.startswith('http'):
        url = 'https://' + url
    url = url.rstrip('/') + '/'

    def _norm(s):
        s = unicodedata.normalize('NFKD', s or '')
        s = ''.join(c for c in s if not unicodedata.combining(c))
        return s.upper()

    alvo = _norm(razao_social)
    # tokens significativos p/ tolerar sufixos (LTDA, ME, EIRELI): 2 primeiras palavras
    tokens = [t for t in alvo.split() if len(t) >= 3][:2]

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/125.0 Safari/537.36')

    for tent in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': ua})
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                status = getattr(resp, 'status', None) or resp.getcode()
                if status == 200:
                    corpo = _norm(resp.read().decode('utf-8', errors='replace'))
                    nome_ok = (alvo and alvo in corpo) or \
                              (tokens and all(t in corpo for t in tokens))
                    if nome_ok:
                        logger.info("[Aquecer] Site 200 + razão social OK (%s)", url)
                        if callback_status:
                            callback_status("🔥 Site no ar e com a razão social — pronto p/ verificar")
                        return True
                    # 200 mas nome ainda não visível: dá mais 1 tentativa e aceita
                    if tent >= 2:
                        logger.info("[Aquecer] Site 200 (razão social não confirmada) — seguindo (%s)", url)
                        if callback_status:
                            callback_status("🔥 Site no ar — seguindo p/ verificação")
                        return True
                    logger.info("[Aquecer] 200 mas razão social ainda não visível, retry %d", tent)
                else:
                    logger.info("[Aquecer] HTTP %s (tent %d/%d) — %s", status, tent, tentativas, url)
        except Exception as exc:
            logger.info("[Aquecer] tentativa %d/%d falhou: %s", tent, tentativas, exc)
        if tent < tentativas:
            if callback_status:
                callback_status(f"⏳ Aguardando o site subir/propagar ({tent}/{tentativas})...")
            time.sleep(intervalo)

    logger.warning("[Aquecer] Site não confirmado no ar após %d tentativas (%s) — seguindo mesmo assim",
                   tentativas, url)
    if callback_status:
        callback_status("⚠️ Site não confirmado no ar — seguindo (servidor entrega charset correto)")
    return False


# ============================================================================
# LEITURA DO STATUS DE VERIFICAÇÃO AO VIVO (para o modo Reprocessar)
# ============================================================================

_MESES_STATUS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7,
    'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'fev': 2, 'abr': 4, 'mai': 5, 'ago': 8, 'set': 9, 'out': 10, 'dez': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6, 'july': 7,
    'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4, 'maio': 5,
    'junho': 6, 'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10,
    'novembro': 11, 'dezembro': 12,
}


def _idade_horas_submitted(texto):
    """Extrai a data de envio ('Submitted on …' / 'Enviado em …') do texto da
    página e retorna a idade em HORAS (desde a meia-noite daquele dia). None se
    não achar. Conservador: como a data não traz hora, conta a partir da 0h."""
    import datetime as _dt
    if not texto:
        return None
    t = texto
    m = None
    # EN: "Submitted on Jul 05, 2026" / "Submitted on July 5, 2026"
    m = re.search(r'(?:submitted on|enviado em)\s+([A-Za-zçÇ]{3,12})\.?\s+(\d{1,2}),?\s+(\d{4})',
                  t, re.IGNORECASE)
    dia = mes = ano = None
    if m:
        mes = _MESES_STATUS.get(m.group(1).strip('.').lower())
        dia = int(m.group(2)); ano = int(m.group(3))
    if not (dia and mes and ano):
        # PT: "Enviado em 05 de jul de 2026" / "5 de julho de 2026"
        m = re.search(r'(?:enviado em|submitted on)\s+(\d{1,2})\s+de\s+([A-Za-zçÇ]{3,12})\.?\s+de\s+(\d{4})',
                      t, re.IGNORECASE)
        if m:
            dia = int(m.group(1)); mes = _MESES_STATUS.get(m.group(2).strip('.').lower()); ano = int(m.group(3))
    if not (dia and mes and ano):
        # numérico: "05/07/2026" próximo de submitted/enviado
        m = re.search(r'(?:submitted on|enviado em)\s+(\d{1,2})/(\d{1,2})/(\d{4})', t, re.IGNORECASE)
        if m:
            dia = int(m.group(1)); mes = int(m.group(2)); ano = int(m.group(3))
    if not (dia and mes and ano):
        return None
    try:
        d = _dt.datetime(ano, mes, dia)
        delta = _dt.datetime.now() - d
        return max(0.0, delta.total_seconds() / 3600.0)
    except Exception:
        return None


def ler_status_verificacao_ao_vivo(driver, business_id, callback_status=None):
    """Lê o STATUS de verificação da empresa DIRETO da página (modo Reprocessar).

    Retorna dict:
      {'status': 'verificada'|'em_analise'|'nao_verificada'|'rejeitada'|'desconhecido',
       'idade_horas': float|None,   # desde 'Submitted on/Enviado em', se houver
       'raw': str}

    Regra de decisão do chamador:
      verificada / em_analise(<24h) -> ignora;
      em_analise(>=24h) -> nova BM;
      nao_verificada / rejeitada -> reenviar a Central.
    """
    res = {'status': 'desconhecido', 'idade_horas': None, 'raw': ''}
    try:
        driver.goto(f"https://business.facebook.com/latest/settings/"
                    f"business_info?business_id={business_id}")
    except Exception as exc:
        logger.warning("[StatusVivo] goto falhou: %s", exc)
        return res
    # aguarda a página assentar
    try:
        from server.page_state_manager import PageStateManager
        PageStateManager.wait_until_stable(driver, timeout=35, settle_time=1.2,
                                           f5_after=22, callback_status=None)
    except Exception:
        time.sleep(5)
    time.sleep(0.25)

    try:
        texto = driver.evaluate_page(r"""() => {
            return (document.body && document.body.innerText) || '';
        }""") or ''
    except Exception as exc:
        logger.warning("[StatusVivo] leitura do texto falhou: %s", exc)
        return res

    res['raw'] = texto[:4000]
    low = texto.lower()
    res['idade_horas'] = _idade_horas_submitted(texto)

    # ORDEM IMPORTA: "não verificada" contém "verificada" -> checar negativos 1º.
    negativos = [
        'não verificada', 'nao verificada', 'not verified',
        'informações adicionais são necessárias', 'informacoes adicionais',
        'precisa de mais informações', 'precisa de mais informacoes',
        'more information', 'additional information',
        'não foi possível verificar', 'nao foi possivel verificar',
        'unable to verify',
    ]
    rejeitados = ['rejeitada', 'rejeitado', 'rejected', 'recusada', 'negada', 'denied']
    em_analise = [
        'em análise', 'em analise', 'in review', 'under review', 'pending review',
        'em revisão', 'em revisao', 'em verificação', 'em verificacao',
        'verificação pendente', 'verificacao pendente', 'analisando',
    ]
    verificada = ['empresa verificada', 'negócio verificado', 'negocio verificado',
                  'business verified', 'verification complete', 'conta verificada']

    def _tem(lst):
        return any(k in low for k in lst)

    if _tem(negativos):
        res['status'] = 'nao_verificada'
    elif _tem(rejeitados):
        res['status'] = 'rejeitada'
    elif _tem(em_analise):
        res['status'] = 'em_analise'
    elif _tem(verificada):
        res['status'] = 'verificada'
    else:
        # heurística final: "verificada" isolado (sem "não" antes) na seção de status
        m = re.search(r'status de verifica[çc][ãa]o[^.]{0,80}', low)
        janela = m.group(0) if m else low[:400]
        if 'verificada' in janela and 'não' not in janela and 'nao' not in janela:
            res['status'] = 'verificada'
        else:
            res['status'] = 'desconhecido'

    if callback_status:
        _idade = f" (enviada há ~{res['idade_horas']:.0f}h)" if res['idade_horas'] else ''
        callback_status(f"🔎 Status lido: {res['status']}{_idade}")
    logger.info("[StatusVivo] business_id=%s -> %s idade=%s", business_id,
                res['status'], res['idade_horas'])
    return res


# ============================================================================
# FLUXO COMPLETO: VERIFICAÇÃO DA BM
# ============================================================================

def executar_verificacao_completa_bm(driver, business_id, empresa_dados,
                                      site_id, site_url, numero_telefone,
                                      salvar_meta_func, callback_status=None,
                                      variantes_telefone=None, senha_fb=None,
                                      verificar_site=True):
    """
    Executa o fluxo completo de verificação da BM:

    (senha_fb é aceito por compatibilidade com a assinatura do fluxo FULL —
     o intermediário não usa, mas permite a chamada unificada no backend.)

    ORDEM ANTI-RESTRIÇÃO (invertida em 04/07/2026):
    1. Adiciona e verifica o DOMÍNIO (meta tag) PRIMEIRO — vira ativo confiável.
    2. SÓ ENTÃO preenche as informações da empresa (incluindo telefone) em UMA
       SÓ abertura de popup + Salvar. Preencher a empresa com o domínio já
       verificado dá CREDIBILIDADE e evita a restrição de portfólio (o inverso
       — empresa antes, site não verificado — fazia o FB restringir).

    Args:
        variantes_telefone: Lista de variantes do número fornecidas pela API.
                            Se None, gera a partir de numero_telefone.

    Returns:
        dict com resultado completo
    """
    resultado = {
        'sucesso': False,
        'info_preenchida': False,
        'telefone_preenchido': False,
        'dominio_adicionado': False,
        'dominio_verificado': False,
        'bm_bloqueada': False,
        'mensagem': '',
    }

    try:
        # ===== PRÉ-CHECK: Verificar se a BM já está bloqueada =====
        if detectar_bm_bloqueada_verificacao(driver):
            logger.warning("[Verificação] BM BLOQUEADA detectada antes de iniciar verificação!")
            if callback_status:
                callback_status("🚫 BM BLOQUEADA — portfólio com restrições para anunciar")
            resultado['bm_bloqueada'] = True
            resultado['mensagem'] = 'BM bloqueada — portfólio com restrições para anunciar'
            return resultado

        # ===== AQUECER O SITE antes de expor à Meta (anti-cache de MISS) =====
        # Espera o microsite responder HTTP 200 (+ razão social presente) ANTES
        # de submeter o domínio/empresa à verificação. Evita que a Meta crawleie
        # um site ainda não-propagado, registre o MISS e o cacheie -> "não
        # verificada" mesmo com o site correto. Best-effort (nunca bloqueia).
        try:
            _aquecer_site_para_verificacao(
                site_url,
                empresa_dados.get('razao_social', ''),
                callback_status,
            )
        except Exception as _exc_aq:
            logger.info("[Verificação] aquecimento do site ignorado: %s", _exc_aq)

        # ═══════════════════════════════════════════════════════════════════
        # ORDEM CRÍTICA (anti-restrição) — DOMÍNIO PRIMEIRO, EMPRESA DEPOIS.
        # ---------------------------------------------------------------------
        # DESCOBERTA EMPÍRICA (04/07/2026): preencher os dados da empresa com o
        # site AINDA NÃO verificado faz o Facebook RESTRINGIR o portfólio (o
        # padrão "identidade empresarial + site não verificado" cheira a
        # farm/spam). Se o domínio já é um ATIVO VERIFICADO quando os dados da
        # empresa são preenchidos, o FB dá CREDIBILIDADE e NÃO restringe.
        # Testado manualmente: perfil NOVO, mesmo domínio .website — na ordem
        # invertida (domínio verificado 1º) NÃO deu bloqueio. Por isso aqui:
        #   ETAPA 1 = adiciona + verifica o domínio (meta tag)
        #   ETAPA 2 = preenche a empresa (já com o domínio verificado)
        # ═══════════════════════════════════════════════════════════════════

        # ===== ETAPA 1: Adicionar e verificar domínio (PRIMEIRO) =====
        if callback_status:
            callback_status("🌐 ETAPA 1/2: Adicionando e verificando domínio (antes da empresa)...")

        dominio_limpo = site_url.replace('https://', '').replace(
            'http://', '').rstrip('/')

        if verificar_site:
            res_dom = adicionar_e_verificar_dominio(
                driver, business_id, dominio_limpo, site_id,
                salvar_meta_func, callback_status,
                telefone_site=numero_telefone
            )
        else:
            # 📧 Pro Max E-mail com 'Verificar o Site = NÃO': NÃO adiciona/verifica o
            # domínio por meta-tag. O site vai só na info da empresa (ETAPA 2, campo
            # Site) e o portão da análise é por E-MAIL+SMS (validado ao vivo: a Meta
            # aceita a análise sem domínio — a aba Domínios fica vazia). Stub p/ os
            # checks abaixo seguirem sem bloquear.
            res_dom = {'sucesso': False, 'verificado': False, 'bm_bloqueada': False}
            if callback_status:
                callback_status("↷ Verificar Site = NÃO — pulei a meta-tag; site vai só na empresa.")

        resultado['dominio_adicionado'] = res_dom.get('sucesso', False)
        resultado['dominio_verificado'] = res_dom.get('verificado', False)

        # ===== CHECK: BM bloqueada DETECTADA durante etapa de domínio =====
        if res_dom.get('bm_bloqueada'):
            logger.warning("[Verificação] BM BLOQUEADA retornada pela função de domínio!")
            if callback_status:
                callback_status("🚫 BM BLOQUEADA detectada durante verificação de domínio")
            resultado['bm_bloqueada'] = True
            resultado['mensagem'] = 'BM bloqueada — detectada durante verificação de domínio'
            return resultado

        # ===== CHECK PÓS-ETAPA 1a: bloqueio na própria página de domínios =====
        if detectar_bm_bloqueada_verificacao(driver):
            logger.warning("[Verificação] BM BLOQUEADA detectada na página de domínios!")
            if callback_status:
                callback_status("🚫 BM BLOQUEADA detectada na página de domínios")
            resultado['bm_bloqueada'] = True
            resultado['mensagem'] = 'BM bloqueada — detectada na página de domínios'
            return resultado

        # ===== CHECK PÓS-ETAPA 1b: PORTÃO em CONTAS DE ANÚNCIOS =====
        # Navega até Contas de anúncios (página definitiva da restrição) e só
        # segue p/ preencher a empresa se a conta estiver LIMPA.
        if checar_restricao_contas_anuncios(driver, business_id, callback_status,
                                            'após verificar domínio'):
            # Restrição de anúncios só BLOQUEIA se NÃO houver WABA (regra do dono
            # 2026-09-27, provada ao vivo): com a WABA criada a análise funciona mesmo
            # com a BM restrita p/ anúncios → segue. Sem WABA → nasce restrita → nova BM.
            if _waba_existe_na_bm(driver, business_id):
                if callback_status:
                    callback_status("ℹ️ Restrição de anúncios, mas a WABA já existe — "
                                    "a análise funciona; seguindo.")
            else:
                resultado['bm_bloqueada'] = True
                resultado['mensagem'] = 'BM restrita (Contas de anúncios) SEM WABA — nova BM'
                return resultado

        if resultado['dominio_verificado']:
            logger.info("[Verificação] Domínio VERIFICADO antes da empresa — ativo "
                        "confiável; seguindo p/ dados da empresa (credibilidade).")
        else:
            logger.warning("[Verificação] Domínio adicionado mas NÃO verificado — "
                           "seguindo p/ empresa assim mesmo (best-effort).")

        # Aguardar entre etapas
        _delay_longo()
        _delay_medio()

        # ===== ETAPA 2: Preencher empresa (DEPOIS, com domínio já verificado) =====
        # O botão Salvar do Facebook SÓ ativa quando TODOS os campos estão
        # preenchidos, incluindo o telefone — tudo no mesmo popup.
        if callback_status:
            callback_status("📋 ETAPA 2/2: Preenchendo informações da empresa + telefone...")

        # Garantir que o telefone está nos dados da empresa
        if numero_telefone and not empresa_dados.get('telefone'):
            empresa_dados['telefone'] = numero_telefone

        # Gerar variantes de telefone se não fornecidas
        if not variantes_telefone and numero_telefone:
            variantes_telefone = _gerar_variantes_telefone(numero_telefone)

        res_info = preencher_info_empresa(
            driver, business_id, empresa_dados, callback_status,
            variantes_telefone=variantes_telefone)
        resultado['info_preenchida'] = res_info.get('sucesso', False)
        # Se a empresa foi salva, o telefone também foi (está no mesmo save)
        resultado['telefone_preenchido'] = resultado['info_preenchida']

        if not resultado['info_preenchida']:
            resultado['mensagem'] = (
                f"Falha etapa 2 (info empresa + telefone): {res_info.get('mensagem')}")
            return resultado

        # Aguardar
        _delay_longo()
        _delay_medio()

        # ===== CHECK PÓS-ETAPA 2a: bloqueio na própria página =====
        if detectar_bm_bloqueada_verificacao(driver):
            logger.warning("[Verificação] BM BLOQUEADA detectada após preencher dados!")
            if callback_status:
                callback_status("🚫 BM BLOQUEADA após preenchimento — portfólio restrito")
            resultado['bm_bloqueada'] = True
            resultado['mensagem'] = 'BM bloqueada após preencher dados da empresa'
            return resultado

        # ===== CHECK PÓS-ETAPA 2b: PORTÃO em CONTAS DE ANÚNCIOS =====
        # Navega de novo até Contas de anúncios e confirma que continua LIMPA
        # antes de seguir p/ o WABA (DataCrazy/Gupshup) e a análise.
        if checar_restricao_contas_anuncios(driver, business_id, callback_status,
                                            'após preencher empresa'):
            # Idem: só bloqueia se NÃO houver WABA (com WABA a análise funciona restrita).
            if _waba_existe_na_bm(driver, business_id):
                if callback_status:
                    callback_status("ℹ️ Restrição de anúncios, mas a WABA já existe — "
                                    "a análise funciona; seguindo.")
            else:
                resultado['bm_bloqueada'] = True
                resultado['mensagem'] = 'BM restrita (Contas de anúncios) SEM WABA — nova BM'
                return resultado

        # 📧 No método por E-MAIL com 'Verificar o Site = NÃO' o site NÃO passa pela
        # meta-tag — o sucesso da BASE é só a EMPRESA preenchida (o portão real é
        # e-mail+SMS na Central). Sem este `or not verificar_site`, sucesso=False
        # abortava o fluxo logo após preencher a empresa com "Falha na verificação:
        # None" (o stub de res_dom não tem 'mensagem'). Bug do toggle NÃO (2026-08-15).
        resultado['sucesso'] = (resultado['info_preenchida']
                                and (resultado['dominio_adicionado'] or not verificar_site))

        if not verificar_site:
            resultado['mensagem'] = ("✅ Empresa preenchida (site só adicionado, sem meta-tag "
                                     "— análise por e-mail+SMS).")
        elif resultado['dominio_verificado']:
            resultado['mensagem'] = \
                "✅ Verificação completa: empresa preenchida + domínio verificado!"
        elif resultado['dominio_adicionado']:
            resultado['mensagem'] = "⚠️ Domínio adicionado mas verificação pendente"
        else:
            resultado['mensagem'] = \
                f"Falha na verificação: {res_dom.get('mensagem')}"

        return resultado

    except Exception as e:
        logger.error("[Verificação] Erro no fluxo completo: %s", e, exc_info=True)
        resultado['mensagem'] = f'Erro: {str(e)}'
        return resultado


# ══════════════════════════════════════════════════════════════════════════════
# GARANTIA DE WABA  (2026-08-17 — pedido do usuário)
# ------------------------------------------------------------------------------
# SEM conta do WhatsApp (WABA) na BM, a Central de Segurança NUNCA mostra o botão
# 'Iniciar verificação' — logo a BM NÃO tem como ir para análise. O OAuth (Turbo)
# às vezes "conclui" sem ter criado a WABA (o embedded signup muda de
# layout e a tela terminal engana o detector). Quando isso acontecia, o fluxo ia
# para a Central assim mesmo e ficava em LOOP INFINITO comprando número de SMS e
# gerando certificado — sem chance nenhuma de verificar.
#
# Regra agora: WABA ausente + BM sem restrição = NÃO é bloqueio (a 2ª BM não
# resolve). Aciona-se o Turbo de novo (e, em último caso, o nativo) e CONFIRMA-SE
# na tela 'Contas do WhatsApp' que a conta existe, antes de reentrar na verificação.
# ══════════════════════════════════════════════════════════════════════════════
def garantir_waba_criada(driver, business_id, empresa_dados, metodo='datacrazy',
                         senha_fb='', site_url='', callback_status=None,
                         datacrazy_email='', datacrazy_senha='', captcha_token='',
                         tentativas=2, fallback_direto=True, usar_site_waba=True):
    """Garante que o portfólio TENHA uma conta do WhatsApp (WABA).

    `metodo`: 'datacrazy' (Turbo — link direto da Meta) | 'direto' (nativo no
    Business Suite, `server/waba.py`).
    Faz até `tentativas` passadas no método escolhido, CONFERINDO na Meta ('Contas do
    WhatsApp') depois de cada uma — não confia no "sucesso" devolvido pelo OAuth. Se
    ainda assim não existir e `fallback_direto`, cria a WABA direto no Meta Business
    Suite (server/waba.py) como ÚLTIMO recurso (o objetivo é a BM verificar).

    Retorna {'ok','criada','bm_bloqueada','waba_desabilitada','metodo_usado','mensagem'}.
    WABA DESABILITADA no portfólio → bm_bloqueada=True (portfólio contaminado: o certo
    é BM nova, não uma 2ª WABA na mesma BM).
    """
    def _st(m):
        logger.info('[WABA garantir] %s', m)
        if callback_status:
            try:
                callback_status(m)
            except Exception:
                pass

    from server.etapa_verificacao_negocio import _estado_conta_whatsapp

    res = {'ok': False, 'criada': False, 'bm_bloqueada': False,
           'waba_desabilitada': False, 'metodo_usado': '', 'mensagem': ''}
    _met = str(metodo or 'datacrazy').lower()
    if _met.startswith('dir') or _met.startswith('waba'):
        _met = 'direto'
    else:
        _met = 'datacrazy'

    def _estado():
        try:
            return _estado_conta_whatsapp(driver, business_id)
        except Exception as e:
            logger.warning('[WABA garantir] leitura do estado falhou: %s', e)
            return 'desconhecido'

    est = _estado()
    if est in ('ok', 'restrita'):
        # 'restrita' = a WABA EXISTE (só está restrita, não desativada) → nada a criar.
        res.update(ok=True, mensagem='WABA já existe no portfólio.')
        _st('✅ A BM já tem conta do WhatsApp — nada a criar.')
        return res
    if est == 'desabilitada':
        res.update(bm_bloqueada=True, waba_desabilitada=True,
                   mensagem='WABA DESABILITADA no portfólio — precisa de BM nova.')
        _st('🔴 ' + res['mensagem'])
        return res

    def _rodar_metodo(_m):
        """Executa UMA passada do método. Retorna o dict do executor (ou {})."""
        if _m == 'direto':
            from server.waba import criar_waba
            r = criar_waba(
                driver, business_id,
                nome_exibicao=((empresa_dados or {}).get('razao_social', '')
                               or (empresa_dados or {}).get('nome_fantasia', '')),
                categoria='Outro', callback_status=callback_status,
                captcha_token=captcha_token, usar_site=bool(usar_site_waba)) or {}
            return {'sucesso': bool(r.get('ok')), 'mensagem': r.get('mensagem', '')}
        from server.etapa_full_datacrazy import executar_etapa_full_datacrazy
        return executar_etapa_full_datacrazy(
            driver=driver, empresa_dados=empresa_dados, senha_fb=senha_fb,
            site_url=site_url, callback_status=callback_status,
            datacrazy_email=datacrazy_email, datacrazy_senha=datacrazy_senha,
            business_id=business_id) or {}

    _nome = {'datacrazy': 'Turbo (OAuth da Meta)', 'direto': 'Business Suite (nativo)'}
    _ordem = [_met] * max(1, int(tentativas or 1))
    if fallback_direto and _met != 'direto':
        _ordem.append('direto')   # último recurso: cria a WABA direto no Business Suite

    for _i, _m in enumerate(_ordem, start=1):
        _ultimo_recurso = (_m == 'direto' and _met != 'direto')
        if _ultimo_recurso:
            _st('🆘 O CRM não criou a WABA — ÚLTIMO RECURSO: criando direto no '
                'Meta Business Suite.')
        else:
            _st(f"🧩 BM sem conta do WhatsApp — criando a WABA via "
                f"{_nome.get(_m, _m)} (tentativa {_i}/{len(_ordem)})...")
        try:
            rw = _rodar_metodo(_m)
        except Exception as e:
            logger.error('[WABA garantir] %s falhou: %s', _m, e, exc_info=True)
            rw = {'mensagem': f'exceção: {e}'}
        if rw.get('bm_bloqueada') or rw.get('precisa_nova_bm'):
            res.update(bm_bloqueada=True,
                       waba_desabilitada=bool(rw.get('waba_desabilitada')),
                       metodo_usado=_m,
                       mensagem=(rw.get('mensagem') or 'BM bloqueada ao criar a WABA.'))
            _st('🔴 ' + res['mensagem'])
            return res
        # NÃO confia no "sucesso" do CRM: confere na Meta se a conta existe mesmo.
        est = _estado()
        if est in ('ok', 'restrita'):
            res.update(ok=True, criada=True, metodo_usado=_m,
                       mensagem=f'WABA criada via {_nome.get(_m, _m)}.')
            _st('✅ ' + res['mensagem'])
            return res
        if est == 'desabilitada':
            res.update(bm_bloqueada=True, waba_desabilitada=True, metodo_usado=_m,
                       mensagem='WABA nasceu DESABILITADA — precisa de BM nova.')
            _st('🔴 ' + res['mensagem'])
            return res
        _st(f"⚠️ Ainda sem conta do WhatsApp na BM após {_nome.get(_m, _m)} "
            f"({str(rw.get('mensagem', ''))[:60]}).")

    res['mensagem'] = 'Não consegui criar a WABA nesta BM (todas as tentativas falharam).'
    _st('❌ ' + res['mensagem'])
    return res


def _verificacao_negocio_com_waba(kwargs_vn, criar_waba_cb, callback_status=None,
                                  max_ciclos=2):
    """Roda a verificação de negócio (Central → análise) e, se ela avisar que a BM
    está SEM WABA (`precisa_criar_waba`), CRIA a WABA pelo método escolhido e REENTRA.

    Sem isto, a etapa da Central voltava "pendente" (ou, pior, ficava em loop de SMS)
    numa BM que só precisava de uma WABA. `criar_waba_cb()` deve devolver o dict de
    `garantir_waba_criada`."""
    from server.etapa_verificacao_negocio import executar_etapa_verificacao_negocio

    def _st(m):
        if callback_status:
            try:
                callback_status(m)
            except Exception:
                pass

    res_vn = executar_etapa_verificacao_negocio(**kwargs_vn) or {}
    ciclo = 0
    while res_vn.get('precisa_criar_waba') and ciclo < max_ciclos:
        ciclo += 1
        _st(f"🔁 Verificação parada por falta de WABA — criando a conta do WhatsApp "
            f"e refazendo (ciclo {ciclo}/{max_ciclos}).")
        try:
            rw = criar_waba_cb() or {}
        except Exception as e:
            logger.error('[Pro Max] garantir WABA falhou: %s', e, exc_info=True)
            rw = {'mensagem': f'exceção: {e}'}
        if rw.get('bm_bloqueada'):
            res_vn['bm_bloqueada'] = True
            res_vn['waba_desabilitada'] = bool(rw.get('waba_desabilitada'))
            res_vn['precisa_criar_waba'] = False
            res_vn['mensagem'] = ((res_vn.get('mensagem', '') or '') + ' | '
                                  + str(rw.get('mensagem', 'BM bloqueada na WABA')))
            return res_vn
        if not rw.get('ok'):
            res_vn['mensagem'] = ((res_vn.get('mensagem', '') or '') + ' | '
                                  + str(rw.get('mensagem', 'WABA não criada')))
            return res_vn
        res_vn = executar_etapa_verificacao_negocio(**kwargs_vn) or {}
    return res_vn






def _monitorar_waba_estavel(driver, business_id, callback_status=None,
                            minutos=5, intervalo=30):
    """Monitor pós-criação da WABA (pedido do usuário 2026-09-26).

    Assim que a WABA nasce, confirma a ESTABILIDADE por `minutos` relendo o status
    real na Meta a cada `intervalo`s. A releitura (`_estado_conta_whatsapp`) NAVEGA
    para a página `.../settings/whatsapp_account/?business_id=...` — ou seja, é um F5
    de fato a cada ciclo.

    Retorna:
      'desabilitada' → em ALGUM ciclo o status foi "Conta desabilitada" (para o loop
                       na hora → o chamador recorre + aplica a tag "BM Recorrida");
      'restrita'     → status "Restricted/Restrita" (NÃO desativa) → para o loop na
                       hora e segue DIRETO p/ a análise (pedido do dono 2026-09-27);
      'aprovada'     → ficou estável (Aprovada) durante os `minutos` inteiros → o
                       chamador pode seguir p/ a análise.

    Estados transitórios ('ausente'/'desconhecido') NÃO derrubam o monitor (a Meta às
    vezes demora a materializar a conta logo após criar) — só 'desabilitada' aborta.
    """
    # ⛔ LOOP DE ESPERA DESATIVADO (2026-10-03, pedido do dono): NÃO espera mais até
    # 5min (300s) relendo o status p/ confirmar "Aprovada" — era lento por BM. Agora é
    # UMA leitura imediata do status e segue:
    #   'desabilitada' → recorre + tag; 'restrita' → direto p/ análise; senão 'aprovada'.
    # (Desabilitação pós-análise ainda é refletida pelo conector GSMAILS→painel.)
    try:
        from server.etapa_verificacao_negocio import _estado_conta_whatsapp
    except Exception as _e:
        logger.warning("[Monitor WABA] import _estado_conta_whatsapp falhou: %s", _e)
        return 'aprovada'  # sem como monitorar → não bloqueia o fluxo

    if not business_id:
        return 'aprovada'

    try:
        est = _estado_conta_whatsapp(driver, str(business_id)) or 'desconhecido'
    except Exception as _e:
        logger.debug("[Monitor WABA] leitura única falhou: %s", _e)
        est = 'desconhecido'

    if callback_status:
        try:
            callback_status(f"✅ Status da WABA após criar: {est.upper()} "
                            f"(sem espera de 5min — pedido do dono).")
        except Exception:
            pass

    if est == 'desabilitada':
        logger.warning("[Monitor WABA] BM %s nasceu 'Conta desabilitada' (leitura única).",
                       business_id)
        return 'desabilitada'
    if est == 'restrita':
        logger.info("[Monitor WABA] BM %s RESTRITA (leitura única) — direto p/ análise.",
                    business_id)
        return 'restrita'
    # 'ok'/'ausente'/'desconhecido' → segue DIRETO p/ a análise (sem esperar).
    logger.info("[Monitor WABA] BM %s status=%s — seguindo direto p/ análise (sem loop de 5min).",
                business_id, est)
    return 'aprovada'


def executar_verificacao_completo_datacrazy_pro_max(
        driver, business_id, empresa_dados, site_id, site_url, numero_telefone,
        salvar_meta_func, callback_status=None, variantes_telefone=None,
        senha_fb=None, captcha_token='', tipo_empresa='mei', sms24h_token='',
        datacrazy_email='', datacrazy_senha='', fb_login='', fb_tfa='', bm_email='',
        sms_provedor='sms24h', verificar_site=True, metodo_verificacao='dominio',
        criar_site_func=None, waba_antes_site=False):
    """
    Fluxo COMPLETO · PRO MAX · DataCrazy (Plano 7) — 15 coins.

    Base + domínio + WABA pelo OAuth da Meta direto (Turbo) e, em seguida, a
    ETAPA EXTRA FINAL (Central de Segurança → envia a BM para análise). O número
    da análise vem do provedor de SMS central.

    PORTÃO DA ANÁLISE (`metodo_verificacao`):
      'dominio' (Método 7, padrão) → verifica a empresa por DOMÍNIO (meta-tag).
      'email'   (📧 Método 9, Pro Max E-mail) → verifica por E-MAIL (recomendado
                pela Meta, código lido no GSMAILS) + SMS.
    `verificar_site` (só faz sentido no metodo_verificacao='email'):
      True  → ainda verifica o site por meta-tag ANTES (como o Método 7).
      False → NÃO verifica o site por meta-tag; só adiciona o site na info da
              empresa e vai direto p/ WABA + análise por e-mail+SMS.

    Retorna o dict do Full/DataCrazy, acrescido de:
      'pro_max': True, 'pro_max_ok': bool, 'em_analise': bool,
      'verificacao_negocio': dict
    """
    # ===== ETAPAS 1-3: base + domínio + DataCrazy (até número/nome de exibição) =
    # ⭐ WABA-ANTES-DO-SITE (2026-09-27): a base roda com verificar_site=FALSE (empresa
    # com o site PROVISÓRIO no campo Site, SEM verificar domínio) — assim a WABA nasce
    # ANTES de gastar o site real/domínio. O domínio real é verificado DEPOIS, só se a
    # WABA aprovar (bloco WABA-first mais abaixo). O E-MAIL da BM (email_tmail) é
    # independente do site, então a confirmação de e-mail continua funcionando.
    _verificar_site_base = False if waba_antes_site else verificar_site
    resultado = executar_verificacao_full_datacrazy(
        driver, business_id, empresa_dados, site_id, site_url, numero_telefone,
        salvar_meta_func, callback_status, variantes_telefone, senha_fb,
        datacrazy_email, datacrazy_senha, verificar_site=_verificar_site_base)

    resultado['pro_max'] = True
    resultado['pro_max_ok'] = False
    resultado['em_analise'] = False
    resultado['conexao_incompleta'] = False

    if resultado.get('bm_bloqueada'):
        return resultado
    # ⛔ PORTÃO ANTI-GASTO (mantido): sem a BASE concluída — empresa preenchida e, no
    # portão por DOMÍNIO, meta-tag validada — NÃO se cria WABA nem se gasta SMS/
    # certificado (a análise seria rejeitada). 📧 Pro Max E-mail com 'Verificar o
    # Site = NÃO' não exige domínio (o portão é e-mail+SMS).
    if not resultado.get('sucesso'):
        resultado['mensagem'] = (resultado.get('mensagem', '')
                                 + ' | Base não concluída — pulei WABA/análise (nada gasto).')
        return resultado
    if verificar_site and not waba_antes_site and not resultado.get('dominio_verificado'):
        resultado['mensagem'] = (resultado.get('mensagem', '')
                                 + ' | Domínio NÃO verificado — pulei WABA/análise p/ não '
                                   'gastar à toa.')
        return resultado

    # ⭐ GARANTIA DE WABA (2026-08-17 — pedido do usuário). O DataCrazy "conclui" ao
    # alcançar a tela de número/'Reveja', mas com o layout novo do embedded signup
    # isso NÃO prova que a WABA nasceu. O veredito é a Meta: se 'Contas do WhatsApp'
    # estiver vazia, rodamos o DataCrazy de novo (e, em último caso, criamos a WABA
    # direto) ANTES de gastar SMS/certificado. Sem WABA a Central nunca mostra
    # 'Iniciar verificação' → era o loop infinito de compra de número.
    def _garantir_waba():
        # tentativas=1: o fluxo base JÁ rodou o DataCrazy — aqui é a re-tentativa
        # (mais o último recurso direto na Meta), não uma bateria nova.
        return garantir_waba_criada(
            driver, business_id, empresa_dados, metodo='datacrazy',
            senha_fb=(senha_fb or ''), site_url=site_url,
            callback_status=callback_status,
            datacrazy_email=datacrazy_email, datacrazy_senha=datacrazy_senha,
            captcha_token=captcha_token, tentativas=1)

    _rw = _garantir_waba()
    if _rw.get('bm_bloqueada'):
        resultado['bm_bloqueada'] = True
        resultado['waba_desabilitada'] = bool(_rw.get('waba_desabilitada'))
        resultado['mensagem'] = (resultado.get('mensagem', '')
                                 + ' | Pro Max DataCrazy: '
                                 + _rw.get('mensagem', 'BM bloqueada (WABA)'))
        return resultado
    if not _rw.get('ok'):
        resultado['mensagem'] = (resultado.get('mensagem', '')
                                 + ' | Pro Max DataCrazy: BM sem conta do WhatsApp e não '
                                   'consegui criar — análise não iniciada (nada gasto).')
        return resultado
    resultado['etapa_extra_ok'] = True

    # ════════════════════════════════════════════════════════════════
    # MONITOR PÓS-CRIAÇÃO DA WABA (2026-09-26 — pedido do usuário)
    # ════════════════════════════════════════════════════════════════
    # Assim que a WABA nasce, CONFIRMA a estabilidade ANTES de gastar SMS/certificado
    # na análise: relê o status na Meta (F5) a cada 30s por 5 min. Se ficar "Aprovada"
    # os 5 min → segue p/ a análise. Se cair p/ "Conta desabilitada" → NÃO envia p/
    # análise; marca waba_desabilitada → o _pro_max_com_retry RECORRE (Pedir análise) +
    # aplica a tag "♻️ BM RECORRIDA" no AdsPower e cria a 2ª BM.
    # metodo p/ o painel: Turbo (Meta direto) vs Completo (via CRM) — lido da flag global.
    _metodo_painel = 'datacrazy_turbo'

    _mon = _monitorar_waba_estavel(driver, business_id, callback_status,
                                   minutos=5, intervalo=30)
    if _mon == 'desabilitada':
        resultado['bm_bloqueada'] = True
        resultado['waba_desabilitada'] = True
        resultado['waba_monitor'] = 'desabilitada'
        resultado['mensagem'] = (resultado.get('mensagem', '')
                                 + ' | Monitor pós-criação: WABA caiu p/ "Conta desabilitada" '
                                   'em <5min — NÃO enviei p/ análise; recorrendo + tag BM Recorrida.')
        try:
            # Só marca 'desabilitada' AQUI — o status 'recorrida' é gravado DEPOIS,
            # somente se o recurso (Solicitar análise) for enviado de fato no backend.
            from server.painel_integration import reportar_waba_status
            _ed = empresa_dados or {}
            reportar_waba_status(business_id, metodo=_metodo_painel,
                                 waba_status='desabilitada', recorrida=False,
                                 bm_email=bm_email, cnpj=_ed.get('cnpj', ''),
                                 razao_social=_ed.get('razao_social', ''),
                                 fb_login=fb_login or '')
        except Exception as _pe:
            logger.warning('[Monitor WABA] reporte painel (desabilitada) falhou: %s', _pe)
        if callback_status:
            callback_status('🔴 Monitor WABA: "Conta desabilitada" — acionando recurso + tag BM Recorrida.')
        return resultado
    # 'restrita' e 'aprovada' seguem IGUAL p/ a análise (restrita não desativa). A
    # diferença é só o status reportado ao painel e a mensagem no terminal.
    _waba_reporte = 'restrita' if _mon == 'restrita' else 'aprovada'
    resultado['waba_monitor'] = _waba_reporte
    try:
        from server.painel_integration import reportar_waba_status
        _ed2 = empresa_dados or {}
        reportar_waba_status(business_id, metodo=_metodo_painel, waba_status=_waba_reporte,
                             bm_email=bm_email, cnpj=_ed2.get('cnpj', ''),
                             razao_social=_ed2.get('razao_social', ''),
                             fb_login=fb_login or '')
    except Exception as _pe:
        logger.warning('[Monitor WABA] reporte painel (%s) falhou: %s', _waba_reporte, _pe)
    if callback_status:
        callback_status('🟠 Status WABA: RESTRITA (não desativa) — seguindo para análise.'
                        if _mon == 'restrita' else
                        '🟢 Status WABA: Aprovada — seguindo DIRETO para análise (sem espera de 5min).')

    # ════════════════════════════════════════════════════════════════
    # WABA-FIRST (2026-09-27) — SÓ AGORA gera o SITE REAL + verifica o domínio
    # ════════════════════════════════════════════════════════════════
    # A WABA está APROVADA/RESTRITA (o ramo 'desabilitada' já retornou ANTES, sem gerar
    # site). Agora: (1) gera o site REAL da empresa (criar_site_func — debita 1 token e
    # cria o e-mail próprio do site); (2) re-preenche Informações da empresa com o site
    # REAL (campo Site) + telefone; (3) adiciona o domínio e verifica por meta-tag
    # (consome a cota X/30 SÓ agora). Se o domínio não verificar, PARA antes da análise.
    if waba_antes_site and criar_site_func:
        try:
            if callback_status:
                callback_status("🌐 WABA OK — gerando o SITE REAL da empresa e vinculando "
                                "(Informações da empresa + telefone)...")
            _rs = criar_site_func() or {}
            site_id = _rs.get('site_id', '') or site_id
            site_url = _rs.get('site_url', '') or site_url
            resultado['site_id'] = site_id
            resultado['site_url'] = site_url
        except Exception as _cse:
            logger.error('[WABA-first] criar site real falhou: %s', _cse)
            resultado['mensagem'] = (resultado.get('mensagem', '')
                                     + f' | WABA aprovada mas falha ao gerar o site real: {_cse}')
            return resultado
        # (2) re-preenche a empresa com o SITE REAL (o campo Site do url_completa já foi
        #     atualizado pelo criar_site_func) + telefone.
        try:
            _vt = variantes_telefone or _gerar_variantes_telefone(numero_telefone)
            preencher_info_empresa(driver, business_id, empresa_dados, callback_status,
                                   variantes_telefone=_vt)
        except Exception as _pe:
            logger.warning('[WABA-first] re-preencher empresa (site real) falhou: %s', _pe)
        # (3) verifica o DOMÍNIO por meta-tag (só no portão 'dominio'; consome X/30 agora).
        if metodo_verificacao != 'email' and verificar_site:
            _dom = (site_url or '').replace('https://', '').replace('http://', '').rstrip('/')
            try:
                _rd = adicionar_e_verificar_dominio(driver, business_id, _dom, site_id,
                                                    salvar_meta_func, callback_status,
                                                    telefone_site=numero_telefone) or {}
            except Exception as _de:
                logger.error('[WABA-first] verificar domínio falhou: %s', _de)
                _rd = {}
            resultado['dominio_adicionado'] = bool(_rd.get('sucesso'))
            resultado['dominio_verificado'] = bool(_rd.get('verificado'))
            if not resultado.get('dominio_verificado'):
                resultado['mensagem'] = (resultado.get('mensagem', '')
                                         + ' | WABA aprovada, mas o DOMÍNIO não verificou — NÃO '
                                           'enviei p/ análise (site já criado; reprocessar).')
                if callback_status:
                    callback_status('⚠️ Domínio não verificou após a WABA — parei antes da análise '
                                    '(site já criado; reprocessar depois).')
                return resultado

    # ════════════════════════════════════════════════════════════════
    # ETAPA EXTRA FINAL (PRO MAX) — Verificação de negócio → análise
    # ════════════════════════════════════════════════════════════════
    try:
        res_vn = _verificacao_negocio_com_waba(dict(
            driver=driver,
            empresa_dados=empresa_dados,
            business_id=business_id,
            site_id=site_id,
            callback_status=callback_status,
            captcha_token=captcha_token,
            tipo_empresa=tipo_empresa,
            sms24h_token=sms24h_token,
            sms_provedor=sms_provedor,
            fb_login=fb_login, fb_senha=senha_fb or '', fb_tfa=fb_tfa,
            bm_email=bm_email,
            # 🌐 Site (subdomínio completo) p/ garantir o campo Site do contato no retry.
            site_url=site_url,
            # 📧 PORTÃO DA ANÁLISE: 'dominio' (Método 7) ou 'email' (Método 9 — Pro Max
            # E-mail: seleciona 'Email (Recomendado)', lê o código no GSMAILS, depois SMS).
            metodo_verificacao=metodo_verificacao,
            # Pro Max WABA · DataCrazy (2026-07-25): idem Gupshup — pula o gate de
            # 'Contas de anúncios' e usa a Central de Segurança; sem 'Iniciar
            # verificação' = WABA desabilitada → bloqueia p/ o backend tentar a 2ª BM.
            ignorar_restricao=True,
            bloquear_se_sem_botao=True,
        ), _garantir_waba, callback_status)
        resultado['verificacao_negocio'] = res_vn
        if res_vn.get('bm_bloqueada'):
            resultado['bm_bloqueada'] = True
            resultado['waba_desabilitada'] = bool(res_vn.get('waba_desabilitada'))
            resultado['mensagem'] = (resultado.get('mensagem', '')
                                     + ' | Pro Max DataCrazy: ' + res_vn.get('mensagem', 'BM bloqueada'))
        elif res_vn.get('em_analise'):
            resultado['pro_max_ok'] = True
            resultado['em_analise'] = True
            resultado['mensagem'] = (resultado.get('mensagem', '')
                                     + ' | ' + res_vn.get('mensagem', 'BM em análise'))
        else:
            resultado['mensagem'] = (resultado.get('mensagem', '')
                                     + ' | Pro Max DataCrazy pendente: '
                                     + res_vn.get('mensagem', ''))
            # Sinais TERMINAIS da Central (v1.100): descanso (erro genérico persistente /
            # rate-limit reincidente) e navegador fechado. Antes eram descartados aqui e o
            # backend não tinha como classificar o desfecho (só via texto da mensagem).
            for _flag in ('descansar', 'navegador_fechado', 'rate_limit'):
                if res_vn.get(_flag):
                    resultado[_flag] = True
    except Exception as e:
        logger.error("[Verificação PRO MAX DataCrazy] Erro na etapa de negócio: %s", e,
                     exc_info=True)
        resultado['mensagem'] = (resultado.get('mensagem', '')
                                 + f' | Pro Max DataCrazy falhou: {e}')

    return resultado




# ============================================================================
# RETOMAR (v1.13): pega uma BM JÁ EXISTENTE (perfil reimportado que não concluiu)
# e leva até "Em análise" — SEM esperar e-mail. Reusa as etapas já existentes.
# ============================================================================

def _central_tem_iniciar_verificacao(driver, business_id):
    """True se a Central de Segurança já tem o botão 'Iniciar verificação'/'Começar'
    disponível (= a WABA/caso de uso já foi criado antes, DataCrazy/Gupshup já
    passou). Se NÃO tiver, é preciso rodar o DataCrazy/Gupshup ANTES p/ criar a WABA."""
    try:
        driver.goto(f"https://business.facebook.com/latest/settings/security_center?business_id={business_id}")
    except Exception:
        pass
    try:
        from server.page_state_manager import PageStateManager
        PageStateManager.wait_until_stable(driver, timeout=30, settle_time=1.2,
                                           f5_after=20, callback_status=None)
    except Exception:
        time.sleep(5)
    try:
        return bool(driver.evaluate_page(r"""() => {
            const t = ((document.body && document.body.innerText) || '').toLowerCase();
            const alvos = ['iniciar verificação','iniciar verificacao','start verification',
                           'continuar verificação','continuar verificacao','continue verification',
                           'ações necessárias','acoes necessarias','começar','comecar'];
            for (const a of alvos) { if (t.includes(a)) return true; }
            return false;
        }"""))
    except Exception:
        return False


def retomar_bm_para_analise(driver, business_id, empresa_dados, site_id, site_url,
                            salvar_meta_func, metodo='datacrazy', callback_status=None,
                            captcha_token='', tipo_empresa='mei', sms24h_token='',
                            datacrazy_email='', datacrazy_senha='',
                            senha_fb='', fb_login='', fb_tfa='', fb_email='',
                            fb_email_senha='', bm_email='', numero_telefone='',
                            sms_provedor='sms24h', metodo_verificacao='dominio',
                            verificar_site=True):
    """Retoma uma BM existente e a leva até 'Em análise' (SEM esperar e-mail):
      1) verifica o DOMÍNIO (extrai a meta tag e valida; se já verificado, segue);
      2) checa RESTRIÇÃO em Contas de anúncios — se restrita -> retorna bm_restrita
         (o chamador cria uma BM NOVA e re-invoca esta função nela);
      3) Central: se já tem 'Iniciar verificação' (WABA existe) -> submete direto;
         se NÃO -> roda o Turbo (cria a WABA), re-checa restrição e submete.
    Retorna {'sucesso','em_analise','bm_restrita','bm_bloqueada','mensagem'}.

    `metodo`: 'datacrazy' (Turbo) | 'waba_direto' (nativo no Business Suite).
    `sms_provedor`: provedor escolhido na GUI p/ comprar o número da análise.
    """
    def status(msg):
        logger.info("[Retomar] %s", msg)
        if callback_status:
            try:
                callback_status(msg)
            except Exception:
                pass

    res = {'sucesso': False, 'em_analise': False, 'bm_restrita': False,
           'bm_bloqueada': False, 'mensagem': ''}
    business_id = str(business_id or '').strip()
    if not business_id:
        res['mensagem'] = 'business_id ausente — não dá p/ retomar.'
        return res

    from server.etapa_verificacao_negocio import (
        _bm_bloqueada_para_anuncios, executar_etapa_verificacao_negocio)

    # ── 1) DOMÍNIO: extrai a meta tag e verifica (se já verificado, segue). ──
    # 📧 Pro Max E-mail com verificar_site=NÃO PULA esta etapa: o portão é e-mail+SMS.
    rd = {}
    if verificar_site:
        status("🌐 Retomar: verificando o domínio (meta tag)...")
        dominio_limpo = (site_url or '').replace('https://', '').replace('http://', '').rstrip('/')
        try:
            rd = adicionar_e_verificar_dominio(driver, business_id, dominio_limpo, site_id,
                                               salvar_meta_func, callback_status,
                                               telefone_site=numero_telefone) or {}
            if isinstance(rd, dict) and rd.get('bm_bloqueada'):
                res['bm_bloqueada'] = True
                res['mensagem'] = 'BM bloqueada na verificação de domínio.'
                return res
        except Exception as e:
            logger.warning("[Retomar] verificação de domínio falhou: %s", e)

        # ⛔ PORTÃO ANTI-GASTO: só avança (criar WABA / enviar à análise) se o domínio
        # estiver REALMENTE VERIFICADO. Sem verificação, a Meta NÃO aceita a análise lá
        # na frente — criar WABA/SMS/certificado seria gasto à toa. Então PARA aqui.
        # (No método por E-MAIL a análise NÃO depende de domínio → este gate não roda.)
        if metodo_verificacao != 'email' and not (isinstance(rd, dict) and rd.get('verificado')):
            res['dominio_nao_verificado'] = True
            res['mensagem'] = ('Domínio NÃO verificado — parei ANTES de criar a WABA/enviar '
                               'à análise (evita gasto à toa; sem domínio a Meta rejeita).')
            status('⛔ ' + res['mensagem'])
            return res

    # ── 1b) DADOS DA EMPRESA NA BM = EMPRESA DESTE RUN (2026-10-05, teste real #3266) ──
    # Ao retomar, a empresa/site deste run pode NÃO ser a que estava gravada na BM
    # (perfil reimportado recebe empresa+site NOVOS). Antes o Retomar ia direto p/ a
    # Central: a BM ficava com razão social/endereço/CNPJ da empresa ANTIGA e o
    # certificado/site/CNPJ enviados eram da NOVA → dados que não batem (regra do dono:
    # BM, certificado e site têm que ser a MESMA empresa). Regrava os detalhes da BM
    # com a empresa atual (idempotente quando já é a mesma). Sem isso, NÃO envia.
    try:
        if numero_telefone and not empresa_dados.get('telefone'):
            empresa_dados['telefone'] = numero_telefone
        status("📋 Retomar: alinhando os dados da BM com a empresa deste envio...")
        _ri = preencher_info_empresa(
            driver, business_id, empresa_dados, callback_status,
            variantes_telefone=_gerar_variantes_telefone(empresa_dados.get('telefone') or '')) or {}
    except Exception as _e_info:
        logger.error("[Retomar] preencher_info_empresa falhou: %s", _e_info, exc_info=True)
        _ri = {'sucesso': False, 'mensagem': str(_e_info)}
    if not _ri.get('sucesso'):
        res['info_nao_preenchida'] = True
        res['mensagem'] = ('Não consegui gravar os dados da empresa atual na BM existente — '
                           'NÃO envio p/ análise com dados que não batem: '
                           + str(_ri.get('mensagem', ''))[:120])
        status('⛔ ' + res['mensagem'])
        return res

    # ── 2) A WABA JÁ EXISTE? ──
    # Se a WABA já foi criada, uma restrição em "Contas de anúncios" NÃO impede o envio
    # p/ análise (PROVADO ao vivo 2026-09-27: BM com WABA restrita foi p/ análise normal,
    # "Informações enviadas / Em análise"). A restrição SÓ importa quando NÃO há WABA —
    # aí a BM nasceu restrita e a restrição impede CRIAR a WABA → precisa de BM nova.
    try:
        from server.etapa_verificacao_negocio import _estado_conta_whatsapp as _est_wa
        _waba_ja_existe = (_est_wa(driver, business_id) in ('ok', 'restrita')
                           or _central_tem_iniciar_verificacao(driver, business_id))
    except Exception:
        _waba_ja_existe = _central_tem_iniciar_verificacao(driver, business_id)
    if not _waba_ja_existe:
        if _bm_bloqueada_para_anuncios(driver, business_id, status):
            res['bm_restrita'] = True
            res['mensagem'] = ('BM nasceu restrita (sem WABA) — a restrição impede criar a '
                               'WABA; criar BM nova.')
            return res
    else:
        status('ℹ️ WABA já existe — restrição de anúncios NÃO impede a análise; seguindo p/ o envio.')

    # WABA garantida pelo método escolhido (2026-08-17) — usada tanto no passo 3
    # quanto na REENTRADA, caso a Central acuse 'BM sem conta do WhatsApp'.
    def _garantir_waba():
        return garantir_waba_criada(
            driver, business_id, empresa_dados, metodo=metodo,
            senha_fb=(senha_fb or ''), site_url=site_url,
            callback_status=callback_status,
            datacrazy_email=datacrazy_email, datacrazy_senha=datacrazy_senha,
            captcha_token=captcha_token, tentativas=1)

    # ── 3) Central: a WABA já existe (botão 'Iniciar verificação')? ──
    if _central_tem_iniciar_verificacao(driver, business_id):
        status("🔐 Central com 'Iniciar verificação' (WABA já existe) — submetendo direto.")
    else:
        # E-MAIL (best-effort, máx ~60s, SEM reenvio) antes de criar a WABA. Se não
        # confirmar, SEGUE assim mesmo (o fluxo alternativo destrava a Central se a WABA
        # nascer desabilitada). Se já está confirmado, ok.
        status("✉️ Confirmando e-mail da BM (best-effort) antes da WABA...")
        try:
            driver.goto(f"https://business.facebook.com/latest/settings/business_info?business_id={business_id}")
            try:
                from server.page_state_manager import PageStateManager
                PageStateManager.wait_until_stable(driver, timeout=30, settle_time=1.2,
                                                   f5_after=20, callback_status=None)
            except Exception:
                time.sleep(0.8)
        except Exception:
            pass
        try:
            confirmar_email_bm_via_codigo(driver, callback_status, max_tentativas=3)
        except Exception as _e:
            logger.warning("[Retomar] confirmar e-mail (best-effort) falhou: %s", _e)
        status(f"🧩 Sem WABA — rodando {metodo} p/ criar a conta WhatsApp Business...")
        try:
            from server.etapa_full_datacrazy import executar_etapa_full_datacrazy
            rw = executar_etapa_full_datacrazy(driver, empresa_dados, senha_fb,
                                               site_url=site_url, callback_status=callback_status,
                                               datacrazy_email=datacrazy_email,
                                               datacrazy_senha=datacrazy_senha,
                                               business_id=business_id)
        except Exception as e:
            logger.error("[Retomar] %s falhou: %s", metodo, e, exc_info=True)
            rw = {}
        if isinstance(rw, dict) and rw.get('bm_bloqueada'):
            res['bm_bloqueada'] = True
            res['mensagem'] = f'{metodo}: BM/conta bloqueada.'
            return res
        # Restrição de anúncios DEPOIS de criar a WABA NÃO aborta mais (2026-09-27): com
        # a WABA criada a análise funciona mesmo restrita. O gate real agora é a
        # EXISTÊNCIA da WABA logo abaixo (_garantir_waba): sem WABA → não envia; com
        # WABA (ok/restrita) → segue p/ o envio.
        # CONFIRMA na Meta que a WABA existe mesmo (o CRM "conclui" sem criar às
        # vezes). Se não existir, insiste no método escolhido antes de gastar SMS.
        _rw2 = _garantir_waba()
        if _rw2.get('bm_bloqueada'):
            res['bm_bloqueada'] = True
            res['waba_desabilitada'] = bool(_rw2.get('waba_desabilitada'))
            res['mensagem'] = _rw2.get('mensagem', f'{metodo}: BM/conta bloqueada.')
            return res
        if not _rw2.get('ok'):
            res['mensagem'] = ('BM sem conta do WhatsApp e não consegui criar — '
                               'não enviei p/ análise (nada gasto). '
                               + str(_rw2.get('mensagem', '')))
            return res

    # ── 4) Submete a Central (envia p/ análise) — reusa a etapa do Pro Max. ──
    status("🚀 Central de Segurança — enviando a BM para análise...")
    rc = _verificacao_negocio_com_waba(dict(
        driver=driver, empresa_dados=empresa_dados, business_id=business_id, site_id=site_id,
        callback_status=callback_status, captcha_token=captcha_token, tipo_empresa=tipo_empresa,
        sms24h_token=sms24h_token, sms_provedor=sms_provedor, fb_login=fb_login, fb_senha=senha_fb, fb_tfa=fb_tfa,
        fb_email=fb_email, fb_email_senha=fb_email_senha, bm_email=bm_email,
        metodo_verificacao=metodo_verificacao, site_url=site_url),
        _garantir_waba, callback_status)
    res['em_analise'] = bool(rc.get('em_analise') or rc.get('sucesso'))
    res['sucesso'] = res['em_analise']
    res['bm_bloqueada'] = bool(rc.get('bm_bloqueada'))
    # Propaga os sinais de desfecho (antes perdidos): WABA desabilitada (p/ o chamador
    # poder recorrer/classificar) e descanso/navegador fechado (terminais da Central).
    for _flag in ('waba_desabilitada', 'descansar', 'navegador_fechado'):
        if rc.get(_flag):
            res[_flag] = True
    res['mensagem'] = rc.get('mensagem', '') or res['mensagem']
    return res






def executar_verificacao_full_datacrazy(driver, business_id, empresa_dados,
                                        site_id, site_url, numero_telefone,
                                        salvar_meta_func, callback_status=None,
                                        variantes_telefone=None, senha_fb=None,
                                        datacrazy_email='', datacrazy_senha='',
                                        verificar_site=True):
    """
    Fluxo FULL · DataCrazy Turbo — base do Pro Max DataCrazy Turbo.

    1) Faz TUDO que o fluxo intermediário faz (empresa + domínio via meta tag) —
       REUTILIZANDO executar_verificacao_completa_bm (bugfixes valem p/ todos).
    2) ETAPA EXTRA — cria a WABA pelo OAuth da Meta direto (etapa_full_datacrazy,
       Turbo) ligada à BM do perfil. Roda no MESMO navegador, em abas novas.
       Requer a senha do perfil do Facebook (reauth).

    Custo: 2 tokens (1 do site; +1 da etapa extra, debitado pelo backend SOMENTE
    quando resultado['etapa_extra_ok'] == True).

    Retorna o MESMO dict do fluxo intermediário, acrescido de:
      'full': True, 'etapa_extra_ok': bool, 'datacrazy': dict
    """
    # ===== ETAPAS 1-2: idênticas ao fluxo intermediário (reuso) =====
    resultado = executar_verificacao_completa_bm(
        driver, business_id, empresa_dados, site_id, site_url,
        numero_telefone, salvar_meta_func, callback_status, variantes_telefone,
        verificar_site=verificar_site)

    resultado['full'] = True
    resultado['etapa_extra_ok'] = False

    # Se a base falhou/bloqueou, não roda a etapa extra (e não cobra o 2º token).
    if not resultado.get('sucesso') or resultado.get('bm_bloqueada'):
        return resultado
    # ⛔ PORTÃO ANTI-GASTO (pedido do usuário): SÓ roda a etapa extra (WABA —
    # DataCrazy/Gupshup) se o DOMÍNIO foi REALMENTE VERIFICADO. Sem verificação, a
    # análise FINAL rejeita (o método precisa confirmar via domínio/site) e gastamos
    # WABA + SMS + certificado à toa. Então PARA aqui em vez de avançar.
    # ⚠️ EXCEÇÃO (📧 Pro Max E-mail, verificar_site=NÃO): o portão da análise é
    # E-MAIL+SMS, não domínio — então NÃO exigimos domínio verificado (validado ao
    # vivo 2026-08-15: BM foi p/ análise só com e-mail+SMS, aba Domínios vazia).
    if verificar_site and not resultado.get('dominio_verificado'):
        resultado['mensagem'] = (resultado.get('mensagem', '')
            + ' | Domínio NÃO verificado — pulei a etapa extra (WABA) p/ não gastar à toa.')
        return resultado

    # ════════════════════════════════════════════════════════════════
    # ETAPA EXTRA (FULL · DataCrazy) — Onboarding no CRM DataCrazy
    # ----------------------------------------------------------------
    # Roda DEPOIS que o domínio foi verificado. Só marca etapa_extra_ok=True
    # (liberando a cobrança do 2º token no backend) quando o onboarding
    # concluir com sucesso.
    # ════════════════════════════════════════════════════════════════
    try:
        from server.etapa_full_datacrazy import executar_etapa_full_datacrazy
        # Garante que a etapa da WABA tenha site_id/site_url no empresa_dados p/
        # registrar/associar corretamente.
        try:
            if isinstance(empresa_dados, dict):
                if site_id and not empresa_dados.get('site_id'): empresa_dados['site_id'] = site_id
                if site_url and not empresa_dados.get('site_url'): empresa_dados['site_url'] = site_url
                if site_url and not empresa_dados.get('url_completa'):
                    empresa_dados['url_completa'] = str(site_url).replace('https://', '').replace('http://', '').split('/')[0]
        except Exception:
            pass
        res_dc = executar_etapa_full_datacrazy(
            driver=driver,
            empresa_dados=empresa_dados,
            senha_fb=senha_fb,
            site_url=site_url,
            callback_status=callback_status,
            datacrazy_email=datacrazy_email,
            datacrazy_senha=datacrazy_senha,
            business_id=business_id,
        )
        resultado['datacrazy'] = res_dc
        if res_dc.get('sucesso'):
            resultado['etapa_extra_ok'] = True
            resultado['mensagem'] = (resultado.get('mensagem', '')
                                     + ' | ' + res_dc.get('mensagem', 'DataCrazy OK'))
        elif res_dc.get('bm_bloqueada'):
            resultado['bm_bloqueada'] = True
            resultado['mensagem'] = (resultado.get('mensagem', '')
                                     + ' | DataCrazy: ' + res_dc.get('mensagem', 'conta/BM restrita'))
        else:
            # Outra falha (inclusive 'Sorry' 3x no OAuth — a própria etapa já re-tenta
            # o link): não há CRM alternativo; a garantia de WABA (garantir_waba_criada)
            # ainda insiste no Turbo e, em último caso, cria a WABA nativa.
            resultado['mensagem'] = (resultado.get('mensagem', '')
                                     + ' | etapa extra (DataCrazy) pendente: '
                                     + res_dc.get('mensagem', ''))
    except Exception as e:
        logger.error("[Verificação FULL/DataCrazy] Erro na etapa extra: %s", e, exc_info=True)
        resultado['mensagem'] = (resultado.get('mensagem', '')
                                 + f' | etapa extra (DataCrazy) falhou: {e}')

    return resultado



