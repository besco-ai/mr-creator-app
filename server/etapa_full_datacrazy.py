#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ETAPA DA WABA — Pro Max DataCrazy TURBO (OAuth da Meta direto)
==============================================================
Passo que cria a conta do WhatsApp Business (WABA) na BM do perfil. Roda DEPOIS
que a base concluiu (empresa preenchida + domínio verificado via meta tag).
Abre o link do OAuth/embedded-signup do app DataCrazy na Meta DIRETO numa aba
nova e conduz o OAuth até "Confirmar" (é o Confirmar que cria a WABA).

Desde 2026-10-05 o Turbo é o ÚNICO fluxo do GS Creator: o login no CRM DataCrazy
(Método 7), o Gupshup e o HighLevel foram removidos. Este módulo também fornece
os HELPERS genéricos (cliques por texto, preenchimento, abas/popup OAuth,
TMail/OTP, esperas) usados por `etapa_verificacao_negocio`.

A automação usa o MESMO navegador anti-detect (PlaywrightDriver). Como os
seletores de CRM/Facebook são instáveis (classes hash mudam), usamos cascata:
data-testid → placeholder/aria → TEXTO do botão (clique por texto). Os textos
de botão são a âncora mais estável.

Reaproveita os helpers de TMail de automacao_facebook (mesma aba/inbox).
"""

import re
import time
import random
import logging

logger = logging.getLogger(__name__)


# ⚡ TURBO (Meta direto): link do OAuth/embedded-signup do app DataCrazy na Meta.
# Abrir este link DIRETO no navegador já cai no formulário do WhatsApp (mesmo que
# o "Entrar com o Facebook" do CRM abriria) — então pulamos o login no CRM. O
# app_id/config_id são do app DataCrazy (estáveis); o `cbt` é um timestamp e é
# REFRESCADO a cada uso (um cbt velho pode dar "não foi possível validar sua
# solicitação"). Se um dia a Meta trocar o app/config do DataCrazy, basta atualizar
# esta URL (capturar de novo o link do "Entrar com o Facebook" do CRM).
OAUTH_URL_META_DATACRAZY = (
    "https://www.facebook.com/v22.0/dialog/oauth?app_id=5731926666869940"
    "&cbt=1788963679225"
    "&channel_url=https%3A%2F%2Fstaticxx.facebook.com%2Fx%2Fconnect%2Fxd_arbiter%2F%3Fversion%3D46%23cb%3Dfb0f88e51f5e27fac%26domain%3Dcrm.datacrazy.io%26is_canvas%3Dfalse%26origin%3Dhttps%253A%252F%252Fcrm.datacrazy.io%252Ffc47e1a66919d2db5%26relation%3Dopener"
    "&client_id=5731926666869940&config_id=1040713481320750&display=popup"
    "&domain=crm.datacrazy.io&e2e=%7B%7D"
    "&extras=%7B%22version%22%3A%22v3%22%2C%22featureType%22%3A%22%22%7D"
    "&fallback_redirect_uri=https%3A%2F%2Fcrm.datacrazy.io%2Fconfig%2Finstances"
    "&locale=pt_BR&logger_id=fd05212ee9efcaab4&origin=1&override_default_response_type=true"
    "&redirect_uri=https%3A%2F%2Fstaticxx.facebook.com%2Fx%2Fconnect%2Fxd_arbiter%2F%3Fversion%3D46%23cb%3Df1a9543853e49bd5e%26domain%3Dcrm.datacrazy.io%26is_canvas%3Dfalse%26origin%3Dhttps%253A%252F%252Fcrm.datacrazy.io%252Ffc47e1a66919d2db5%26relation%3Dopener%26frame%3Dfc285c4c9e23d9bea"
    "&response_type=code&sdk=joey&version=v22.0"
)


def _oauth_url_meta_datacrazy():
    """Devolve a URL do OAuth com o `cbt` atualizado para AGORA (ms). Evita o erro
    'não foi possível validar sua solicitação' que um `cbt` velho pode causar."""
    import re
    agora_ms = str(int(time.time() * 1000))
    return re.sub(r'cbt=\d+', 'cbt=' + agora_ms, OAUTH_URL_META_DATACRAZY, count=1)


def _trazer_para_frente(page):
    """bring_to_front() SEGURO — não faz nada quando há N navegadores em paralelo.

    Chamar page.bring_to_front() direto ativa a JANELA do navegador no SO. Com
    vários workers, a etapa OAuth (abre popup → adota → volta → fecha) vira uma
    tempestade de ativação de janelas e CONGELA o Windows inteiro (mouse/teclado
    param). Ver playwright_compat.trazer_para_frente."""
    try:
        from server.playwright_compat import trazer_para_frente as _tpf
        return _tpf(page)
    except Exception:
        return False


# Reuso dos helpers de TMail / abas já existentes no projeto.
try:
    from server.automacao_facebook import (
        _abrir_nova_aba,
        _localizar_aba_tmail,
        _abrir_ou_reutilizar_aba_tmail,
        obter_email_tmail,
    )
    _TEM_TMAIL = True
except Exception as _imp_exc:  # pragma: no cover
    logger.warning("[FULL/DataCrazy] Falha ao importar helpers TMail: %s", _imp_exc)
    _TEM_TMAIL = False

try:
    from server.gerar_numero import gerar_numero_aleatorio
except Exception:  # pragma: no cover
    def gerar_numero_aleatorio():
        return f'5511997{random.randint(100000, 999999)}'


# ============================================================================
# DELAYS HUMANIZADOS
# ============================================================================

def _delay(min_s=0.1, max_s=0.4):
    media = (min_s + max_s) / 2
    desvio = (max_s - min_s) / 4
    t = max(min_s, min(max_s, random.gauss(media, desvio)))
    time.sleep(t)


def _delay_curto():
    _delay(0.05, 0.15)


def _delay_medio():
    _delay(0.2, 0.5)


def _delay_longo():
    _delay(0.5, 1.2)


# ============================================================================
# HELPERS DE NAVEGAÇÃO / ABAS
# ============================================================================

def _url_atual(driver):
    try:
        return (driver.current_url or '').lower()
    except Exception:
        return ''


def _handles(driver):
    try:
        return list(getattr(driver, 'window_handles', []) or [])
    except Exception:
        return []


def _switch(driver, handle):
    try:
        driver.switch_to.window(handle)
        return True
    except Exception:
        return False


def _esperar_estatico(driver, timeout=40, settle=0.8, callback=None):
    """Espera RÁPIDA e sem F5 (ver PageStateManager.wait_ready_fast) — os helpers
    de clique/preenchimento já fazem polling do alvo, então não estabilizamos 100%."""
    try:
        from server.page_state_manager import PageStateManager
        return PageStateManager.wait_ready_fast(driver, timeout=timeout, settle=min(settle, 0.35))
    except Exception:
        time.sleep(min(timeout, 2))
        return True


def _esperar_url(driver, fragmentos, timeout=40):
    """Espera a URL da aba ATUAL conter um dos fragmentos."""
    if isinstance(fragmentos, str):
        fragmentos = [fragmentos]
    fragmentos = [f.lower() for f in fragmentos]
    fim = time.time() + timeout
    while time.time() < fim:
        u = _url_atual(driver)
        if any(f in u for f in fragmentos):
            return True
        time.sleep(0.1)
    return False


def _switch_para_url(driver, fragmentos, timeout=30):
    """Procura entre as abas abertas uma cuja URL contenha um dos fragmentos e
    troca para ela. Retorna o handle ou None."""
    if isinstance(fragmentos, str):
        fragmentos = [fragmentos]
    fragmentos = [f.lower() for f in fragmentos]
    fim = time.time() + timeout
    while time.time() < fim:
        for h in _handles(driver):
            if not _switch(driver, h):
                continue
            u = _url_atual(driver)
            if any(f in u for f in fragmentos):
                return h
        time.sleep(0.15)
    return None


def _esperar_nova_janela(driver, handles_antes, timeout=30):
    """Espera surgir uma nova aba/janela (ex.: popup OAuth do Facebook) e
    retorna seu handle, trocando o foco para ela."""
    antes = set(handles_antes or [])
    fim = time.time() + timeout
    while time.time() < fim:
        atuais = _handles(driver)
        novos = [h for h in atuais if h not in antes]
        if novos:
            h = novos[-1]
            _switch(driver, h)
            return h
        time.sleep(0.1)
    return None


def _descobrir_popup_via_cdp(driver, frags):
    """Enumera TODOS os targets do navegador via sessão CDP de nível browser e
    força o attach do target da popup OAuth.

    Em navegadores anti-detect (ex.: SunBrowser) a popup do embedded signup abre
    como JANELA SEPARADA cujo target o Playwright NÃO auto-anexa — então ela
    nunca aparece em browser.contexts[].pages. Aqui usamos Target.getTargets para
    encontrá-la mesmo assim e Target.attachToTarget(flatten) para forçar o
    Playwright a materializar a Page no contexto correspondente (o chamador
    re-varre browser.contexts logo depois). Retorna True se encontrou o target."""
    try:
        browser = getattr(driver, 'browser', None)
        if not browser:
            return False
        cdp = getattr(driver, '_cdp_browser_session', None)
        if cdp is None:
            cdp = browser.new_browser_cdp_session()
            driver._cdp_browser_session = cdp
            try:
                cdp.send('Target.setDiscoverTargets', {'discover': True})
            except Exception:
                pass
        infos = cdp.send('Target.getTargets').get('targetInfos', [])
    except Exception as e:
        logger.debug("[FULL/DataCrazy] CDP getTargets falhou: %s", e)
        return False
    achou = False
    paginas_url = []
    for ti in infos:
        try:
            if ti.get('type') != 'page':
                continue
            u = (ti.get('url') or '').lower()
            paginas_url.append(u[:80])
            if any(f in u for f in frags) or ('facebook.com' in u and 'oauth' in u):
                tid = ti.get('targetId')
                logger.info("[FULL/DataCrazy] CDP achou target da popup OAuth: %s (%s)",
                            u[:80], tid)
                try:
                    cdp.send('Target.attachToTarget', {'targetId': tid, 'flatten': True})
                except Exception as e:
                    logger.debug("[FULL/DataCrazy] attachToTarget falhou: %s", e)
                achou = True
        except Exception:
            continue
    if not achou and not getattr(driver, '_cdp_diag_logged', False):
        driver._cdp_diag_logged = True
        logger.info("[FULL/DataCrazy] CDP: targets 'page' atuais = %s", paginas_url)
    return achou


def _adotar_popup_oauth(driver, timeout=35):
    """Detecta e ADOTA a janela popup do OAuth do Facebook (dialog/oauth) que o
    embedded signup do Gupshup abre. Em navegadores anti-detect a popup pode
    estar em OUTRO BrowserContext do Playwright — então varremos TODOS os
    contexts/pages do browser, não só o contexto padrão (window_handles).

    Quando encontra, aponta driver._current_page (e driver.context) para a popup
    para que os helpers (query_selector/evaluate_page) passem a operar nela.

    Retorna (page_popup, ctx_anterior, page_anterior) ou (None, ctx, page)."""
    frags = ['dialog/oauth', '/v17.0/dialog', '/dialog/oauth', 'business_login']
    ctx_anterior = getattr(driver, 'context', None)
    page_anterior = getattr(driver, '_current_page', None)
    fim = time.time() + timeout
    while time.time() < fim:
        # Força o attach de targets de popup que o Playwright não auto-anexou
        # (popup OAuth aberta como janela separada em navegador anti-detect).
        _descobrir_popup_via_cdp(driver, frags)
        try:
            browser = getattr(driver, 'browser', None)
            contexts = list(browser.contexts) if browser else []
        except Exception:
            contexts = []
        if ctx_anterior is not None and ctx_anterior not in contexts:
            contexts.append(ctx_anterior)
        for ctx in contexts:
            try:
                paginas = list(ctx.pages)
            except Exception:
                paginas = []
            for page in paginas:
                try:
                    u = (page.url or '').lower()
                except Exception:
                    u = ''
                if any(f in u for f in frags) or ('facebook.com' in u and 'oauth' in u):
                    try:
                        driver.context = ctx
                    except Exception:
                        pass
                    driver._current_page = page
                    driver._current_frame = None
                    _trazer_para_frente(page)
                    logger.info("[FULL/DataCrazy] Popup OAuth adotada: %s", u[:80])
                    return page, ctx_anterior, page_anterior
        time.sleep(0.1)
    logger.warning("[FULL/DataCrazy] Popup OAuth NÃO encontrada em nenhum contexto")
    return None, ctx_anterior, page_anterior


def _fechar_aba(driver, handle, voltar_para=None):
    """Fecha uma aba específica e volta o foco para `voltar_para` (ou 1ª aba)."""
    try:
        if handle and handle in _handles(driver):
            _switch(driver, handle)
            driver.close()
    except Exception:
        pass
    destino = voltar_para if (voltar_para and voltar_para in _handles(driver)) else None
    if not destino:
        hs = _handles(driver)
        destino = hs[0] if hs else None
    if destino:
        _switch(driver, destino)
    return destino


# ============================================================================
# HELPERS DE ELEMENTO (Playwright ElementHandle nativo)
# ============================================================================

def _visivel(el):
    try:
        return bool(el and el.is_visible())
    except Exception:
        return False


def _texto_el(el):
    try:
        t = (el.inner_text() or '').strip()
        if t:
            return t
    except Exception:
        pass
    try:
        return (el.get_attribute('value') or '').strip()
    except Exception:
        return ''


def _click_seletor(driver, seletor, timeout=12):
    """Clica no 1º elemento visível que casa o seletor CSS. Retorna bool."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            for el in driver.query_selector_all(seletor):
                if _visivel(el):
                    try:
                        el.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    _delay_curto()
                    el.click(timeout=5000)
                    logger.info("[FULL/DataCrazy] Clique OK no seletor: %s", seletor)
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    logger.warning("[FULL/DataCrazy] Seletor não clicável: %s", seletor)
    return False


def _click_texto(driver, textos, seletor_base=None, exato=False, timeout=15):
    """Clica no elemento VISÍVEL que MELHOR casa um dos `textos`.

    IMPORTANTE: nunca casa um CONTAINER cujo texto apenas "contém" o alvo (ex.:
    um div que agrega 'Continue with Google/GitHub/Facebook'), o que faria o
    clique cair no botão errado. Para isso usamos ranking por qualidade do match
    (exato > começa-com > contém-curto) e desempate pelo MENOR texto (o elemento
    folha mais específico, nunca o wrapper)."""
    if isinstance(textos, str):
        textos = [textos]
    alvos = [t.strip().lower() for t in textos]
    if not seletor_base:
        seletor_base = ('button, [role="button"], a, input[type="submit"], '
                        'div[role="button"], span[role="button"], label')
    inicio = time.time()
    fim = inicio + timeout
    # Conta fora do pt (2026-10-13): se o rótulo não aparecer rápido, tenta casar pela
    # TRADUÇÃO pt-BR dos clicáveis visíveis (server/tradutor_tela) — 1x por chamada.
    _tr_tentado = exato
    while time.time() < fim:
        if not _tr_tentado and time.time() - inicio >= min(2.5, timeout / 2.0):
            _tr_tentado = True
            try:
                from server.tradutor_tela import clicar_por_traducao
                # Só seletores de "clicável"; os genéricos (div/span/li) pegariam texto
                # solto → nesse caso usa o conjunto padrão de clicáveis do tradutor.
                _partes = [p.strip() for p in seletor_base.split(',')]
                _sb = None if any(p in ('div', 'span', 'li', '*', '') for p in _partes) else seletor_base
                if clicar_por_traducao(driver, textos, _sb):
                    return True
            except Exception:
                pass
        try:
            cands = driver.query_selector_all(seletor_base)
        except Exception:
            cands = []
        melhor = None  # (rank, len_txt, el, txt)
        for el in cands:
            if not _visivel(el):
                continue
            txt = _texto_el(el).lower().strip()
            if not txt or len(txt) > 80:
                continue
            rank = None
            for alvo in alvos:
                if txt == alvo:
                    rank = 0
                    break
            if rank is None and not exato:
                for alvo in alvos:
                    if txt.startswith(alvo):
                        rank = 1
                        break
            if rank is None and not exato:
                # 'contém' só se o texto NÃO for muito maior que o alvo —
                # evita casar containers que agregam vários botões.
                for alvo in alvos:
                    if alvo in txt and len(txt) <= len(alvo) + 18:
                        rank = 2
                        break
            if rank is None:
                continue
            cand = (rank, len(txt), el, txt)
            if melhor is None or (cand[0], cand[1]) < (melhor[0], melhor[1]):
                melhor = cand
        if melhor:
            el, txt = melhor[2], melhor[3]
            try:
                el.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            _delay_curto()
            try:
                el.click(timeout=5000)
                logger.info("[FULL/DataCrazy] Clique OK por texto: '%s'", txt[:40])
                return True
            except Exception as e:
                logger.debug("[FULL/DataCrazy] click falhou em '%s': %s", txt[:30], e)
        time.sleep(0.1)
    logger.warning("[FULL/DataCrazy] Texto não clicável: %s", textos)
    return False


def _preencher(driver, seletor, valor, timeout=12, limpar=True):
    """Preenche um input (fill nativo do Playwright — dispara eventos React)."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            for el in driver.query_selector_all(seletor):
                if _visivel(el):
                    try:
                        el.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    _delay_curto()
                    try:
                        if limpar:
                            el.fill('')
                            _delay(0.1, 0.3)
                        el.fill(str(valor))
                    except Exception:
                        # Fallback: clicar + teclado
                        el.click()
                        driver.keyboard.press('Control+a')
                        driver.keyboard.press('Delete')
                        driver.keyboard.type(str(valor), delay=random.randint(30, 80))
                    logger.info("[FULL/DataCrazy] Campo preenchido (%s): '%s'",
                                seletor, str(valor)[:40])
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    logger.warning("[FULL/DataCrazy] Campo não preenchido: %s", seletor)
    return False


def _existe_texto(driver, textos, timeout=10):
    """True se algum dos textos aparece (visível) na página atual."""
    if isinstance(textos, str):
        textos = [textos]
    alvos = [t.lower() for t in textos]
    inicio = time.time()
    fim = inicio + timeout
    _tr_tentado = False
    while time.time() < fim:
        try:
            achou = driver.evaluate_page(
                """(alvos) => {
                    var t = (document.body && (document.body.innerText||'')) || '';
                    t = t.toLowerCase();
                    for (var i=0;i<alvos.length;i++){ if (t.indexOf(alvos[i])!==-1) return true; }
                    return false;
                }""", alvos)
            if achou:
                return True
        except Exception:
            pass
        # Conta fora do pt (2026-10-13): confere também a TRADUÇÃO pt-BR do primeiro
        # plano (1x por chamada, após um instante) — as frases PT casam em qualquer idioma.
        if not _tr_tentado and time.time() - inicio >= min(1.5, timeout / 2.0):
            _tr_tentado = True
            try:
                from server.tradutor_tela import traducao_primeiro_plano
                _trd = traducao_primeiro_plano(driver)
                if _trd and any(a in _trd for a in alvos):
                    return True
            except Exception:
                pass
        time.sleep(0.1)
    return False


# ============================================================================
# SANITIZAÇÃO
# ============================================================================

def _nome_app(razao_social):
    """Nome único do app WhatsApp: sem espaços nem caracteres especiais."""
    base = razao_social or 'Empresa'
    base = re.sub(r'[^A-Za-z0-9]', '', base)
    if not base:
        base = 'Empresa'
    # Gupshup exige nome único — acrescenta sufixo curto para evitar colisão.
    base = base[:28]
    sufixo = str(random.randint(100, 999))
    return f"{base}{sufixo}"[:32]


def _nome_exibicao_waba(razao_social):
    """Nome de conta / nome de exibição do WhatsApp Business (telas do novo layout
    do Gupshup). Diferente de _nome_app: aqui PODE ter espaços (é o nome legível
    da empresa), apenas limpa caracteres estranhos e limita o tamanho."""
    base = (razao_social or 'Empresa').strip()
    # mantém letras (com acento), números e espaços; remove o resto
    base = re.sub(r'[^\w\sÀ-ÿ]', ' ', base, flags=re.UNICODE)
    base = re.sub(r'\s+', ' ', base).strip()
    if not base:
        base = 'Empresa'
    return base[:75]


def _selecionar_opcao_novo_numero(driver):
    """Tela 'Selecione sua configuração' (novo layout): marca a opção
    'Insira um novo número de telefone do WhatsApp para começar'. Clica no radio
    do CARD correto, subindo do título até o contêiner que contém o input radio."""
    try:
        return bool(driver.evaluate_page("""() => {
            const norm = s => (s || '').toLowerCase();
            const alvos = [
                'insira um novo número de telefone do whatsapp',
                'insira um novo numero de telefone do whatsapp',
                'start with a new whatsapp',
                'enter a new whatsapp phone number'
            ];
            const els = [...document.querySelectorAll('div,span,strong,p,label,h3,h4')];
            for (const el of els) {
                const t = norm(el.innerText);
                if (t.length > 220) continue;
                if (!alvos.some(a => t.includes(a))) continue;
                let node = el;
                for (let i = 0; i < 7 && node; i++) {
                    const radio = node.querySelector &&
                        node.querySelector('input[type=radio],[role=radio]');
                    if (radio) { radio.click(); return true; }
                    node = node.parentElement;
                }
                el.click();
                return true;
            }
            return false;
        }"""))
    except Exception as e:
        logger.debug("[FULL/DataCrazy] _selecionar_opcao_novo_numero falhou: %s", e)
        return False


def _preencher_campo_por_rotulo(driver, rotulos, valor, timeout=10):
    """Preenche um input localizado pelo seu RÓTULO visível (aria-label, label[for],
    placeholder ou texto do contêiner imediato). Usado nas telas novas do Gupshup
    (Nome da conta / Nome de exibição do WABA). Se não achar pelo rótulo, cai para
    preenchimento por ORDEM (1º input de texto ainda vazio do diálogo)."""
    alvos = [r.lower() for r in (rotulos if isinstance(rotulos, list) else [rotulos])]
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            achou = bool(driver.evaluate_page("""(alvos) => {
                const norm = s => (s || '').toLowerCase();
                document.querySelectorAll('[data-gsfill]').forEach(e => e.removeAttribute('data-gsfill'));
                const inputs = [...document.querySelectorAll(
                    'input[type=text],input:not([type]),input[type=tel],textarea')]
                    .filter(el => { const r = el.getBoundingClientRect();
                                    return r.width > 1 && r.height > 1 && !el.disabled; });
                const rotulosDe = (el) => {
                    const c = [];
                    if (el.getAttribute('aria-label')) c.push(el.getAttribute('aria-label'));
                    if (el.placeholder) c.push(el.placeholder);
                    if (el.id) { const l = document.querySelector('label[for="' + el.id + '"]');
                                 if (l) c.push(l.innerText); }
                    let p = el.parentElement, hop = 0;
                    while (p && hop < 3) {
                        const tt = (p.innerText || '');
                        if (tt && tt.length < 90) c.push(tt);
                        p = p.parentElement; hop++;
                    }
                    return c.map(norm);
                };
                for (const el of inputs) {
                    const rots = rotulosDe(el);
                    if (alvos.some(a => rots.some(r => r.includes(a)))) {
                        el.setAttribute('data-gsfill', '1');
                        return true;
                    }
                }
                return false;
            }""", alvos))
        except Exception:
            achou = False
        if achou:
            ok = _preencher(driver, 'input[data-gsfill="1"], textarea[data-gsfill="1"]',
                            valor, timeout=6)
            try:
                driver.evaluate_page(
                    "() => document.querySelectorAll('[data-gsfill]')"
                    ".forEach(e => e.removeAttribute('data-gsfill'))")
            except Exception:
                pass
            if ok:
                return True
        time.sleep(0.1)

    # Fallback: preenche o 1º input de texto AINDA VAZIO e visível do diálogo.
    try:
        marcou = bool(driver.evaluate_page("""() => {
            document.querySelectorAll('[data-gsfill]').forEach(e => e.removeAttribute('data-gsfill'));
            const inputs = [...document.querySelectorAll(
                'input[type=text],input:not([type]),input[type=tel],textarea')]
                .filter(el => { const r = el.getBoundingClientRect();
                                return r.width > 1 && r.height > 1 && !el.disabled && !el.value; });
            if (inputs.length) { inputs[0].setAttribute('data-gsfill', '1'); return true; }
            return false;
        }"""))
        if marcou:
            ok = _preencher(driver, 'input[data-gsfill="1"], textarea[data-gsfill="1"]',
                            valor, timeout=5)
            driver.evaluate_page(
                "() => document.querySelectorAll('[data-gsfill]')"
                ".forEach(e => e.removeAttribute('data-gsfill'))")
            return ok
    except Exception:
        pass
    return False


# ============================================================================
# TMAIL — email + leitura do OTP da Gupshup
# ============================================================================

def _obter_email_tmail(driver):
    """Retorna (email, handle_aba) de um email temporário TMail (reaproveita a
    aba existente, se houver)."""
    if not _TEM_TMAIL:
        return None, None
    try:
        email, aba = obter_email_tmail(driver)
        return email, aba
    except Exception as e:
        logger.warning("[FULL/DataCrazy] Erro ao obter email TMail: %s", e)
        return None, None


def _texto_pagina_e_frames(driver):
    """Concatena o innerText da página atual MAIS o de todos os iframes.

    Essencial para o TMail: o CORPO do email (onde está o OTP) é renderizado
    DENTRO de um <iframe>, então document.body.innerText da página principal
    NÃO contém o código. O Playwright consegue avaliar JS em qualquer frame
    (inclusive cross-origin), então varremos page.frames."""
    partes = []
    try:
        t = driver.evaluate_page(
            "() => (document.body && document.body.innerText) || ''")
        if t:
            partes.append(t)
    except Exception:
        pass
    page = getattr(driver, '_current_page', None)
    if page is not None:
        try:
            for fr in page.frames:
                try:
                    t = fr.evaluate(
                        "() => (document.body && document.body.innerText) || ''")
                    if t:
                        partes.append(t)
                except Exception:
                    continue
        except Exception:
            pass
    return "\n".join(partes)


def _ler_otp_gupshup(driver, aba_tmail, timeout=120, callback=None):
    """Aguarda o email da Gupshup no TMail e extrai o código OTP de 6 dígitos.
    Retorna a string do código ou None."""
    if not aba_tmail:
        return None
    fim = time.time() + timeout
    ja_abriu = False
    ultima_reabertura = time.time()
    while time.time() < fim:
        if callback:
            callback(f"⏳ Aguardando OTP da Gupshup no email... ({int(fim - time.time())}s)")
        if not _switch(driver, aba_tmail):
            time.sleep(0.25)
            continue
        if 'tmail' not in _url_atual(driver):
            try:
                driver.get("https://tmailsocial.site/")
                _delay_medio()
            except Exception:
                pass

        # 1) Abrir o email da Gupshup (assunto contém "verify your email" /
        #    remetente devsupport@gupshup.io) se ainda não estiver aberto.
        try:
            email_el = driver.evaluate_page(
                """() => {
                    var sel = ['tr','li','[role="row"]','a','div','td'];
                    var kw = ['gupshup','verify your email','whatsapp access'];
                    for (var s=0;s<sel.length;s++){
                        var els = document.querySelectorAll(sel[s]);
                        for (var i=0;i<els.length;i++){
                            var el = els[i];
                            var r = el.getBoundingClientRect();
                            if (r.width<40 || r.height<10) continue;
                            var t = (el.textContent||'').toLowerCase();
                            if (!t || t.length>500) continue;
                            for (var j=0;j<kw.length;j++){
                                if (t.indexOf(kw[j])!==-1){ el.setAttribute('data-otp-mail','1'); return true; }
                            }
                        }
                    }
                    return false;
                }""")
            # Abre o email se ainda não abriu, ou re-tenta a cada ~20s caso o
            # corpo (iframe) não tenha carregado.
            if email_el and (not ja_abriu or (time.time() - ultima_reabertura) > 20):
                alvo = driver.query_selector('[data-otp-mail="1"]')
                if alvo:
                    try:
                        alvo.click(timeout=4000)
                        ja_abriu = True
                        ultima_reabertura = time.time()
                        _delay_medio()
                    except Exception:
                        try:
                            driver.evaluate_page(
                                "() => { var e=document.querySelector('[data-otp-mail=\\\"1\\\"]'); if(e) e.click(); }")
                            ja_abriu = True
                            ultima_reabertura = time.time()
                            _delay_medio()
                        except Exception:
                            pass
        except Exception:
            pass

        # 2) Extrair 6 dígitos do corpo. O corpo do email fica DENTRO de um
        #    iframe no TMail, então lemos página + todos os frames.
        corpo = _texto_pagina_e_frames(driver)
        codigo = _extrair_otp(corpo)
        if codigo:
            logger.info("[FULL/DataCrazy] OTP Gupshup capturado: %s", codigo)
            return codigo

        time.sleep(0.8)
    logger.warning("[FULL/DataCrazy] OTP Gupshup NÃO recebido no tempo limite")
    return None


def _extrair_otp(texto):
    """Extrai um código de 6 dígitos do texto do email."""
    if not texto:
        return None
    baixo = texto.lower()
    # Preferir 6 dígitos próximos de palavras-chave de OTP.
    for kw in ('one time password', 'otp', 'validate your email', 'verification', 'código', 'codigo'):
        idx = baixo.find(kw)
        if idx != -1:
            janela = texto[idx: idx + 200]
            m = re.search(r'\b(\d{6})\b', janela)
            if m:
                return m.group(1)
    # Fallback: primeiro 6 dígitos isolados do corpo.
    m = re.search(r'\b(\d{6})\b', texto)
    return m.group(1) if m else None


# ============================================================================
# COMBOBOX MUI (região) e COMBOBOX FB (categoria)
# ============================================================================

# O autocomplete de região da Gupshup tem um data-testid próprio (âncora estável).
_REGIAO_TESTID = '[data-testid="onboarding-div-local-storage-autocomplete"]'


def _regiao_ja_brazil(driver):
    """True se a região selecionada já é Brazil. O país NÃO fica no value do input
    (que é vazio) — aparece como BANDEIRA/adornment; então verificamos a bandeira
    (img alt/src/title), emoji 🇧🇷 e qualquer texto 'Brazil/Brasil' no box."""
    try:
        return bool(driver.evaluate_page("""() => {
            const box = document.querySelector('[data-testid="onboarding-div-local-storage-autocomplete"]');
            const scope = box || document;
            const t = ((box ? box.innerText : '') + '').toLowerCase();
            if (t.indexOf('brazil') !== -1 || t.indexOf('brasil') !== -1) return true;
            if ((box ? box.innerText : '').indexOf('\\uD83C\\uDDE7\\uD83C\\uDDF7') !== -1) return true; // 🇧🇷
            const flags = scope.querySelectorAll('img, [class*="flag"], [class*="Flag"]');
            for (const im of flags) {
                const s = (((im.getAttribute && (im.getAttribute('src')||'')) || '') + ' ' +
                           ((im.getAttribute && (im.getAttribute('alt')||'')) || '') + ' ' +
                           ((im.getAttribute && (im.getAttribute('title')||'')) || '') + ' ' +
                           (im.className || '')).toLowerCase();
                if (s.indexOf('brazil') !== -1 || s.indexOf('brasil') !== -1) return true;
                if (s.indexOf('/br.') !== -1 || s.indexOf('-br.') !== -1 ||
                    s.indexOf('flag-br') !== -1 || s.indexOf('fi-br') !== -1 ||
                    s.indexOf('_br') !== -1 || /[^a-z]br[^a-z]/.test(s)) return true;
            }
            return false;
        }"""))
    except Exception:
        return False


def _id_bandeira_regiao(driver):
    """Identificador da BANDEIRA/país atualmente exibido no seletor de região
    (src/alt/title/classe da imagem da bandeira). Serve para detectar a MUDANÇA
    US -> BR de forma confiável (o país não fica no value do input)."""
    try:
        return (driver.evaluate_page("""() => {
            const box = document.querySelector('[data-testid="onboarding-div-local-storage-autocomplete"]');
            if (!box) return '';
            const im = box.querySelector('img, [class*="flag"], [class*="Flag"]');
            if (im) {
                const a = (im.getAttribute && (im.getAttribute('src') || im.getAttribute('alt') ||
                           im.getAttribute('title') || im.getAttribute('aria-label') || '')) || '';
                return (a + ' ' + (im.className || '')).trim().toLowerCase();
            }
            return (box.innerText || '').trim().toLowerCase();
        }""") or '')
    except Exception:
        return ''


def _abrir_seletor_regiao(driver):
    """Clica/abre o autocomplete de região pelo data-testid (âncora estável).
    Fallbacks: input com valor de país, ou combobox perto do rótulo (EN/PT)."""
    for sel in (_REGIAO_TESTID + ' input[role="combobox"]',
                _REGIAO_TESTID + ' input',
                _REGIAO_TESTID):
        try:
            el = driver.query_selector(sel)
            if el and _visivel(el):
                el.scroll_into_view_if_needed(timeout=2000)
                el.click(timeout=4000)
                return True
        except Exception:
            continue
    # Fallback: combobox perto do rótulo "Region/Região/Local Storage" (EN/PT).
    try:
        return bool(driver.evaluate_page("""() => {
            const terms = ['local storage region','storage region','select the region',
                           'choose your local','region','região','regiao'];
            const conts = [...document.querySelectorAll('div,section,form,label,fieldset')];
            for (const c of conts) {
                const t = (c.innerText || '').toLowerCase();
                if (!t || t.length > 300) continue;
                if (terms.some(x => t.indexOf(x) !== -1)) {
                    const ctrl = c.querySelector(
                        '[role="combobox"],input[role="combobox"],[role="button"],button,select,input');
                    if (ctrl) { ctrl.scrollIntoView({block:'center'}); ctrl.click(); return true; }
                }
            }
            return false;
        }"""))
    except Exception:
        return False


def _contar_opcoes_regiao(driver):
    """Quantas opções (países) estão renderizadas no dropdown do autocomplete."""
    try:
        return int(driver.evaluate_page(
            "() => document.querySelectorAll('[role=\"option\"], li[role=\"option\"]').length") or 0)
    except Exception:
        return 0


def _achar_opcao_brazil(driver):
    """Retorna o ElementHandle da opção 'Brazil'/'Brasil' visível na lista, ou None."""
    try:
        for el in driver.query_selector_all('[role="option"], li[role="option"], li'):
            if not _visivel(el):
                continue
            t = _texto_el(el).strip().lower()
            if t == 'brazil' or t == 'brasil' or t.startswith('brazil') or t.startswith('brasil'):
                return el
    except Exception:
        pass
    return None


def _selecionar_regiao_brazil(driver, timeout=35):
    """Troca a 'Local Storage Region' de US para BR de forma SEGURA e robusta:
      1. Abre o autocomplete (data-testid).
      2. ESPERA a lista de países carregar (é assíncrona — digitar antes disso
         gera 'No options').
      3. Digita 'Brazil' e ESPERA a opção 'Brazil' aparecer (poll, recupera de
         'No options' limpando e re-tentando).
      4. CLICA na opção 'Brazil' DA LISTA (clique direto — NÃO usa Enter).
      5. AGUARDA a BANDEIRA mudar de US para BR de fato.
    Só retorna True quando a bandeira virou BR (clicar 'Next' antes trava a tela
    de forma irrecuperável)."""
    if _regiao_ja_brazil(driver):
        return True
    fim = time.time() + timeout
    while time.time() < fim:
        if not _abrir_seletor_regiao(driver):
            time.sleep(0.15)
            continue
        flag_antes = _id_bandeira_regiao(driver)  # bandeira atual (US)
        _delay_curto()

        # 2) Esperar a lista de países CARREGAR (assíncrona) antes de filtrar.
        _fim_load = time.time() + 10
        while time.time() < _fim_load and _contar_opcoes_regiao(driver) < 2:
            time.sleep(0.1)

        # 3) Digitar 'Brazil' e esperar a opção aparecer (recupera de 'No options').
        op_brazil = None
        for _tent in range(3):
            try:
                driver.keyboard.press('Control+a')
                driver.keyboard.press('Delete')
                _delay(0.1, 0.3)
                driver.keyboard.type('Brazil', delay=random.randint(60, 110))
            except Exception:
                pass
            _fim_op = time.time() + 7
            while time.time() < _fim_op:
                op_brazil = _achar_opcao_brazil(driver)
                if op_brazil:
                    break
                time.sleep(0.1)
            if op_brazil:
                break
            # 'No options': limpa, espera a lista voltar e tenta de novo.
            try:
                driver.keyboard.press('Control+a')
                driver.keyboard.press('Delete')
            except Exception:
                pass
            time.sleep(0.7)

        if not op_brazil:
            logger.warning("[FULL/DataCrazy] Opção 'Brazil' não apareceu na lista (No options) — reabrindo.")
            time.sleep(0.2)
            continue

        # 4) Clicar a opção 'Brazil' DA LISTA (clique direto, sem Enter).
        try:
            op_brazil.scroll_into_view_if_needed(timeout=2000)
            _delay_curto()
            op_brazil.click(timeout=4000)
        except Exception as e:
            logger.debug("[FULL/DataCrazy] clique na opção Brazil falhou: %s", e)
            time.sleep(0.15)
            continue

        # 5) AGUARDAR a bandeira mudar US -> BR antes de dar por concluído.
        fim_flag = time.time() + 12
        while time.time() < fim_flag:
            if _regiao_ja_brazil(driver):
                logger.info("[FULL/DataCrazy] Região: bandeira confirmada BR.")
                _delay_curto()
                return True
            atual = _id_bandeira_regiao(driver)
            if atual and flag_antes and atual != flag_antes:
                logger.info("[FULL/DataCrazy] Região: bandeira mudou ('%s' -> '%s').",
                            flag_antes[:24], atual[:24])
                _delay_curto()
                return True
            time.sleep(0.1)
        logger.warning("[FULL/DataCrazy] Bandeira NÃO mudou para BR após clicar 'Brazil' — repetindo.")
        time.sleep(0.15)
    logger.warning("[FULL/DataCrazy] NÃO foi possível confirmar a bandeira BR.")
    return False


def _voltar_dashboard_gupshup(driver):
    """Volta a aba atual para o Dashboard do WhatsApp da Gupshup, descartando o
    modal de onboarding do app atual.

    Usado quando um app TRAVA na seleção de região (bug intermitente do Gupshup):
    a correção confiável é abandonar esse app e criar OUTRO. O app travado fica
    apenas listado no dashboard, sem efeito no fluxo. Retorna True se chegou ao
    dashboard."""
    try:
        # Garante foco na aba da Gupshup antes de recarregar.
        _switch_para_url(driver, ['apps.gupshup.io'], timeout=10)
        driver.execute_script(
            "window.location.href='https://apps.gupshup.io/whatsapp/dashboard';")
    except Exception as e:
        logger.debug("[FULL/DataCrazy] navegação p/ dashboard falhou: %s", e)
    ok = bool(_esperar_url(driver, ['whatsapp/dashboard'], timeout=25))
    # O dashboard tem polling contínuo e não "assenta" — settle curto basta.
    _esperar_estatico(driver, timeout=8, settle=0.6)
    _delay_medio()
    return ok


def _erro_auth_gupshup(driver):
    """True se aparecer o toast de erro de SESSÃO/TOKEN do Gupshup
    ('Authentication Failed' / 'Something went wrong').

    Causa-raiz do bug da região: quando esse erro dispara, a chamada de backend
    que popula a 'Local Storage Region' falha e a lista vira 'No options' — não dá
    para selecionar Brazil nem avançar. O reload (F5) renova o token e resolve.
    NÃO é resolução/tamanho de janela (a lista carrega normal quando o token está
    válido — confirmado pelo usuário)."""
    return _existe_texto(driver, ['authentication failed', 'something went wrong'],
                         timeout=1)


def _pagina_sorry_oauth(driver):
    """True se a popup do OAuth do Facebook abriu com 'Sorry, something went wrong'
    ('Desculpe, algo deu errado'). Geralmente é a conexão que caiu/estava instável
    BEM na hora da abertura → a popup não carregou 100%. Fechar e reabrir resolve."""
    return _existe_texto(driver,
                         ['sorry, something went wrong',
                          "we're working on getting this fixed",
                          'desculpe, algo deu errado',
                          'estamos trabalhando para corrigir isso',
                          # MULTI-IDIOMA (2026-10-12): conta fora do pt/en caía em "tela
                          # não reconhecida" e abortava com False em vez de REABRIR o link.
                          # Só frases de DESCULPA + erro (específicas da página de erro da
                          # Meta) — nunca "erro" solto, que casaria aviso inline do wizard.
                          'lo sentimos, se produjo un error', 'lo sentimos, algo salió mal',
                          'lo sentimos, algo salio mal',
                          'rất tiếc, đã xảy ra lỗi', 'rất tiếc, có lỗi xảy ra',
                          'извините, произошла ошибка', 'извините, что-то пошло не так',
                          'maaf, terjadi kesalahan', 'maaf, ada yang salah',
                          'क्षमा करें, कुछ गलत हो गया',
                          "désolé, une erreur s'est produite", 'désolé, un problème est survenu',
                          'üzgünüz, bir şeyler ters gitti',
                          'leider ist ein fehler aufgetreten',
                          'spiacenti, si è verificato un errore',
                          'przepraszamy, wystąpił błąd',
                          'вибачте, сталася помилка'],
                         timeout=1)


def _reabrir_go_live(driver):
    """Recupera de 'Authentication Failed'/'Something went wrong': dá F5 no
    dashboard (renova o token de sessão da Gupshup) e reabre 'Begin Go Live' do
    app mais recente (topo da lista). Retorna True se o modal de região reabriu."""
    try:
        driver.refresh()
    except Exception:
        try:
            driver.execute_script("window.location.reload();")
        except Exception:
            pass
    _esperar_url(driver, ['whatsapp/dashboard'], timeout=25)
    # Dashboard tem polling contínuo e não "assenta" — settle curto basta.
    _esperar_estatico(driver, timeout=8, settle=0.6)
    _delay_medio()
    _click_texto(driver, ['Begin Go Live'],
                 seletor_base='button, [role="button"], span, div', timeout=15) or \
        _click_seletor(driver, 'img[alt="arrow-link-icon"]', timeout=8)
    _delay_longo()
    return bool(_existe_texto(driver, ['how do you want to create',
                                       'local storage region'], timeout=20))


def _relogar_gupshup(driver, senha_fb=None):
    """RE-LOGIN completo no Gupshup para obter um TOKEN DE SESSÃO NOVO (Auth0).

    Por que NÃO basta um F5: o Gupshup loga via Auth0 e o token de acesso é curto;
    a renovação SILENCIOSA do token usa iframe + cookie de TERCEIROS, que os
    navegadores anti-detect/Chrome bloqueiam → 'Authentication Failed'. Um F5 pode
    até PIORAR (a Auth0 perde a sessão no reload). Já um re-login por NAVEGAÇÃO
    TOP-LEVEL (login.gupshup.io → Continue with Facebook) passa pelo /authorize em
    contexto de PRIMEIRA parte e emite um token NOVO mesmo com 3p-cookies
    bloqueados. Retorna True se voltou ao dashboard."""
    try:
        _switch_para_url(driver, ['gupshup.io'], timeout=10)
        driver.execute_script(
            "window.location.href='https://login.gupshup.io/u/login';")
    except Exception as e:
        logger.debug("[FULL/DataCrazy] navegação p/ login falhou: %s", e)
    _esperar_estatico(driver, timeout=20, settle=0.6)
    _delay_medio()
    # Se a sessão Auth0/FB ainda é válida, a página de login pode já redirecionar
    # sozinha para o dashboard. Senão, clicamos em Continue with Facebook.
    if 'apps.gupshup.io' not in _url_atual(driver):
        _clicou = _click_seletor(
            driver,
            'form[data-provider="facebook"] button[type="submit"], '
            'button[data-provider="facebook"], '
            '[data-provider="facebook"][type="submit"]', timeout=15)
        if not _clicou:
            _click_texto(driver, ['Continue with Facebook', 'Continuar com o Facebook'],
                         seletor_base='span.c17890ef2, button[data-provider="facebook"], '
                                      'span, button', exato=True, timeout=10)
        _delay_longo()
        # Reauth de senha (se aparecer).
        if _existe_texto(driver, ['insira sua senha', 'enter your password',
                                  'insira novamente sua senha'], timeout=8):
            if senha_fb:
                _preencher(driver, 'input[name="pass"], input[type="password"]',
                           senha_fb, timeout=10)
                _delay_curto()
            _click_seletor(driver, 'input[data-testid="sec_ac_button"], button[name="login"], '
                                   'input[type="submit"]', timeout=8) or \
                _click_texto(driver, ['Continuar', 'Continue', 'Entrar', 'Log In'], timeout=8)
            _delay_longo()
        # Consentimento "Continuar como X".
        if _existe_texto(driver, ['continuar como', 'continue as', 'editar acesso',
                                  'solicitando acesso'], timeout=8):
            _click_texto(driver, ['Continuar como', 'Continue as'],
                         seletor_base='[role="button"], div[role="button"], button, span, div',
                         timeout=10) or \
                _click_texto(driver, ['Continuar', 'Continue'], timeout=8)
            _delay_longo()
    # Garante dashboard.
    if not _esperar_url(driver, ['apps.gupshup.io'], timeout=45):
        _switch_para_url(driver, ['apps.gupshup.io'], timeout=20)
    _esperar_estatico(driver, timeout=8, settle=0.6)
    _delay_medio()
    return 'apps.gupshup.io' in _url_atual(driver)


def _recuperar_auth_e_go_live(driver, senha_fb=None):
    """Recupera de 'Authentication Failed' (token Auth0 expirado): RE-LOGA para
    obter token novo e reabre 'Begin Go Live' do app mais recente (topo da lista).
    Retorna True se o modal de região reabriu."""
    if not _relogar_gupshup(driver, senha_fb):
        return False
    _click_texto(driver, ['Begin Go Live'],
                 seletor_base='button, [role="button"], span, div', timeout=15) or \
        _click_seletor(driver, 'img[alt="arrow-link-icon"]', timeout=8)
    _delay_longo()
    return bool(_existe_texto(driver, ['how do you want to create',
                                       'local storage region'], timeout=20))


def _abrir_combobox_categoria(driver, timeout=8):
    """Abre EXCLUSIVAMENTE a combobox de Categoria — nunca a de Portfólio
    empresarial ou País.

    IMPORTANTE: na tela "Crie um perfil do WhatsApp Business" a combobox vem
    VAZIA (sem placeholder de texto DENTRO dela — só o rótulo 'Categoria' e o
    help text 'Selecione a categoria...' ficam FORA). Por isso NÃO dá para achá-la
    pelo texto interno: localizamos por (1) proximidade do RÓTULO 'Categoria',
    (2) combobox única no diálogo, e só então (3) por texto/aria como fallback."""
    if _click_texto(driver, ['Escolha uma categoria de negócios',
                             'Escolha uma categoria de negocios',
                             'Choose a business category'],
                    seletor_base='[role="combobox"], div[role="combobox"], button, div, span',
                    timeout=2):
        return True
    # Estratégia principal: por POSIÇÃO (rótulo 'Categoria') ou combobox única.
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            r = driver.evaluate_page(r"""() => {
                const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
                const vis = e => { const r=e.getBoundingClientRect();
                    const s=getComputedStyle(e);
                    return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
                const combos = [...document.querySelectorAll(
                    '[role="combobox"],[aria-haspopup="listbox"],div[role="button"][aria-expanded],'
                    + 'label[role="combobox"]')].filter(vis);
                if (!combos.length) return '';
                // 1) por proximidade do rótulo 'Categoria'/'Category'
                const labs = [...document.querySelectorAll('span,label,div,strong,h3,h4,p')]
                    .filter(e => vis(e) && !e.querySelector('*')
                                 && (norm(e.innerText)==='categoria' || norm(e.innerText)==='category'));
                if (labs.length) {
                    const lab = labs[labs.length-1];           // a do passo atual (mais à frente)
                    const lr = lab.getBoundingClientRect();
                    let best=null, bestd=1e9;
                    for (const c of combos) {
                        const cr=c.getBoundingClientRect();
                        const dy = cr.top - lr.bottom;          // combobox ABAIXO do rótulo
                        if (dy > -8 && dy < 220) {
                            const d = Math.abs(dy) + Math.abs(cr.left - lr.left);
                            if (d < bestd) { bestd=d; best=c; }
                        }
                    }
                    if (best) { best.scrollIntoView({block:'center'}); best.click(); return 'rotulo'; }
                }
                // 2) combobox ÚNICA visível no diálogo -> é a de categoria
                if (combos.length === 1) {
                    combos[0].scrollIntoView({block:'center'}); combos[0].click(); return 'unica';
                }
                // 3) fallback por texto/aria
                for (const c of combos) {
                    const t = norm((c.innerText||'') + ' ' + (c.getAttribute('aria-label')||''));
                    if (t.includes('categoria') || t.includes('category')
                        || t.includes('escolha uma categoria')) {
                        c.scrollIntoView({block:'center'}); c.click(); return 'aria';
                    }
                }
                return '';
            }""")
            if r:
                logger.info("[FULL/DataCrazy] Combobox de categoria aberta via '%s'.", r)
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def _categoria_ja_selecionada(driver):
    """True se a combobox de categoria já exibe 'Outro' como valor selecionado.

    Robusto a caracteres invisíveis (zero-width space) que o FB injeta junto ao
    texto do combobox: em vez de igualdade exata, exige que o texto CONTENHA
    'outro'/'other', seja CURTO (≤8 chars sem espaços — exclui frases como
    'criar outros') e não seja o placeholder ('escolha uma categoria')."""
    try:
        return bool(driver.evaluate_page("""() => {
            const cbs = document.querySelectorAll('[role="combobox"], [role="button"], button, input');
            for (const cb of cbs) {
                const s = ((cb.value || cb.innerText || '') + '').toLowerCase();
                // pula o PLACEHOLDER/rótulo em qualquer idioma (escolha/choose/categoria/category/elegir/seleccion)
                if (s.indexOf('escolha') !== -1 || s.indexOf('categoria') !== -1
                    || s.indexOf('choose') !== -1 || s.indexOf('category') !== -1
                    || s.indexOf('categor') !== -1 || s.indexOf('elegir') !== -1
                    || s.indexOf('selecc') !== -1) continue;
                const compact = s.replace(/\\s/g, '');
                if ((s.indexOf('outro') !== -1 || s.indexOf('other') !== -1) && compact.length <= 8) {
                    return true;
                }
            }
            return false;
        }"""))
    except Exception:
        return False


def _lista_categoria_aberta(driver):
    """True se a lista de categorias está ABERTA (há opções 'radio'/option de
    categoria visíveis no DOM). Sinal: existe uma opção visível cujo texto é uma
    categoria conhecida ('Outro'/'Automotivo'/'Educação'...) OU há >=3 radios
    curtos visíveis. Usado para confirmar que o clique de abertura funcionou."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
            const vis = e => { const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
            const conhecidas = ['outro','other','automotivo','educação','educacao',
                'entretenimento','restaurante','serviços profissionais','serviced profissionais'];
            const opts = [...document.querySelectorAll('[role="option"],[role="radio"],li[role="option"]')]
                .filter(vis);
            let curtos = 0;
            for (const o of opts) {
                const t = norm(o.innerText);
                if (conhecidas.includes(t)) return true;
                if (t && t.length>0 && t.length<40) curtos++;
            }
            return curtos >= 3;
        }"""))
    except Exception:
        return False


# Categoria: em PT existe "Outro"; em INGLÊS a lista NÃO tem "Other" (17 categorias
# curadas: Automotive, Education, ...). A categoria é só campo OBRIGATÓRIO p/ habilitar o
# Avançar — não precisa ser "Outro". Preferimos Outro/Other; se não houver, escolhemos
# uma categoria NEUTRA (evitando as restritas: gambling/álcool/remédio/governo/saúde/
# finanças) ou a 1ª opção. Sucesso = a combobox passa a mostrar um VALOR (não placeholder).
_CATEGORIA_PRIORIDADE = ['outro', 'other', 'others', 'otro', 'otra',
                         'professional services', 'serviços profissionais', 'servicos profissionais',
                         'education', 'educação', 'educacao',
                         'event planning and service', 'clothing and apparel',
                         'food and grocery', 'automotive']

_JS_CATEGORIA = r"""(arg) => {
    const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
    const vis = e => { const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
        return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
    const dlg = document.querySelector('[role="dialog"]') || document;
    const PH = ['escolha uma categoria','choose a business category','choose a category',
                'selecione a categoria','categoria de neg','business category',
                'elegir una categor','seleccione la categor','selecciona una categor'];
    const isPH = t => PH.some(p => t.includes(p));
    // combobox que NÃO é a de categoria (país / portfólio / código de país "US +1")
    const naoCat = t => t.includes('portfolio') || t.includes('portfólio')
        || t.includes('country') || t.includes('país') || t.includes('pais')
        || /\+\d/.test(t) || /^[a-z]{2}\s*\+/.test(t);
    const combos = [...dlg.querySelectorAll('[role="combobox"],[aria-haspopup="listbox"]')].filter(vis);
    const acharCat = () => {
        let c = combos.find(e => isPH(norm(e.innerText || e.value || '')));
        if (c) return c;
        const labs = [...dlg.querySelectorAll('span,label,div,strong,p,h3,h4')]
            .filter(e => vis(e) && !e.querySelector('*')
                && (norm(e.innerText)==='category' || norm(e.innerText)==='categoria'));
        if (labs.length){ const lr=labs[labs.length-1].getBoundingClientRect();
            let best=null,bd=1e9; for(const cc of combos){ const cr=cc.getBoundingClientRect();
                const dy=cr.top-lr.bottom; if(dy>-8&&dy<220){ const d=Math.abs(dy)+Math.abs(cr.left-lr.left);
                    if(d<bd){bd=d;best=cc;} } } if(best) return best; }
        return null;
    };
    const cat = acharCat();
    const modo = arg.modo, prio = arg.prio || [];
    if (modo === 'valor'){
        if (!cat) return false;
        const t = norm(cat.innerText || cat.value || '');
        return !!t && !isPH(t) && !naoCat(t) && t.length < 45;
    }
    // modo 'pick': garante a lista aberta e escolhe.
    const listaAberta = () => [...document.querySelectorAll('[role="listbox"],[role="menu"]')].filter(vis).length>0;
    if (!listaAberta() && cat){ try{ cat.scrollIntoView({block:'center'}); }catch(e){} try{ cat.click(); }catch(e){} }
    const opts = () => [...document.querySelectorAll('[role="option"],[role="radio"],li[role="option"]')].filter(vis);
    const os = opts();
    if (!os.length) return 'abriu';
    const clicar = el => { try{ el.scrollIntoView({block:'center'}); }catch(e){}
        try{ el.click(); return true; }catch(e){}
        try{ const r=el.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
            for(const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
                el.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,clientX:x,clientY:y})); return true; }catch(e){}
        return false; };
    // 1) prioridade (Outro/Other primeiro; depois neutras conhecidas)
    for (const p of prio){
        const o = os.find(e => norm(e.innerText)===p) || os.find(e => norm(e.innerText).includes(p));
        if (o){ clicar(o); return 'clicou'; }
    }
    // 2) fallback: 1ª categoria NÃO restrita (evita gambling/álcool/remédio/governo/saúde/finanças)
    const restrita = t => t.includes('gambling') || t.includes('alcohol') || t.includes('álcool')
        || t.includes('alcool') || t.includes('drug') || t.includes('remédio') || t.includes('remedio')
        || t.includes('government') || t.includes('governo') || t.includes('medical') || t.includes('health')
        || t.includes('saúde') || t.includes('saude') || t.includes('finance') || t.includes('bank')
        || t.includes('finanç') || t.includes('financ') || t.includes('banco');
    const neutra = os.find(e => { const t=norm(e.innerText); return t && t.length>1 && !restrita(t); });
    const alvo = neutra || os[0];
    if (alvo){ clicar(alvo); return 'clicou'; }
    return 'abriu';
}"""


def _categoria_tem_valor(driver):
    """True se a combobox de Categoria já mostra um VALOR (não o placeholder) — idioma-agnóstico."""
    try:
        return bool(driver.evaluate_page(_JS_CATEGORIA, {'modo': 'valor', 'prio': []}))
    except Exception:
        return False


def _selecionar_categoria_outro(driver, timeout=25):
    """Seleciona uma categoria na combobox do OAuth do FB — IDIOMA-AGNÓSTICO (2026-09-23).

    Em pt-BR existe 'Outro' (era a escolha fixa). Em INGLÊS a lista NÃO tem 'Other'
    (17 categorias curadas) — exigir 'Outro' travava o passo 'dados' em loop e a WABA
    NUNCA nascia fora do pt-BR. A categoria é só campo OBRIGATÓRIO p/ habilitar o
    Avançar. Preferimos Outro/Other; se não houver, uma categoria NEUTRA (evitando as
    restritas) ou a 1ª opção. Sucesso = a combobox passa a mostrar um VALOR (não o
    placeholder), verificado por `_categoria_tem_valor` (idioma-agnóstico)."""
    if _categoria_tem_valor(driver):
        return True

    # 1. Abrir a combobox e CONFIRMAR que a lista de categorias apareceu.
    aberta = False
    for tentativa in range(3):
        if not _abrir_combobox_categoria(driver, timeout=6):
            logger.warning("[FULL/DataCrazy] Combobox de categoria não localizada (tent. %s).",
                           tentativa + 1)
            _delay_medio()
            continue
        fim_open = time.time() + 4
        while time.time() < fim_open:
            if _lista_categoria_aberta(driver):
                aberta = True
                break
            time.sleep(0.3)
        if aberta:
            break
        _delay_curto()
    if not aberta:
        logger.warning("[FULL/DataCrazy] Lista de categorias não abriu após 3 tentativas.")
        return False
    _delay_medio()

    # 2. Escolher Outro/Other; senão categoria neutra; verificar pelo VALOR da combobox.
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            r = driver.evaluate_page(_JS_CATEGORIA, {'modo': 'pick', 'prio': _CATEGORIA_PRIORIDADE})
        except Exception as e:
            logger.debug("[FULL/DataCrazy] pick categoria: %s", e)
            r = ''
        _delay_curto()
        if _categoria_tem_valor(driver):
            logger.info("[FULL/DataCrazy] Categoria selecionada (r=%s).", r)
            return True
        # rola p/ renderizar mais opções; reabre se a lista fechou.
        try:
            driver.evaluate_page("""() => {
                const conts = [...document.querySelectorAll('[role="listbox"], ul, div')]
                    .filter(l => l.scrollHeight > l.clientHeight + 20);
                conts.forEach(l => { l.scrollTop = Math.min(l.scrollTop + 240, l.scrollHeight); });
            }""")
        except Exception:
            pass
        if not _lista_categoria_aberta(driver):
            _abrir_combobox_categoria(driver, timeout=3)
        time.sleep(0.15)

    return _categoria_tem_valor(driver)


def _dump_diagnostico_categoria(driver):
    """Quando a seleção de 'Outro' falha, grava a ESTRUTURA exata do DOM da
    categoria (comboboxes visíveis + rótulos + opções de listbox + inputs) em
    telas_desconhecidas/diagnostico_categoria_outro.jsonl + screenshot — pra eu
    criar/ajustar o handler determinístico na próxima iteração. Best-effort."""
    try:
        dados = driver.evaluate_page(r"""() => {
            const norm = s => (s||'').replace(/\s+/g,' ').trim();
            const vis = e => { const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
            const rect = e => { const r=e.getBoundingClientRect();
                return {x:Math.round(r.left), y:Math.round(r.top),
                        w:Math.round(r.width), h:Math.round(r.height)}; };
            const combos = [...document.querySelectorAll(
                '[role="combobox"],[aria-haspopup="listbox"],div[role="button"][aria-expanded]')]
                .filter(vis).slice(0,12).map(c => ({
                    tag: c.tagName.toLowerCase(),
                    role: c.getAttribute('role')||'',
                    aria: norm(c.getAttribute('aria-label')||''),
                    haspopup: c.getAttribute('aria-haspopup')||'',
                    expanded: c.getAttribute('aria-expanded')||'',
                    texto: norm(c.innerText).slice(0,80),
                    rect: rect(c),
                }));
            const labels = [...document.querySelectorAll('span,label,div,strong,h3,h4,p')]
                .filter(e => vis(e) && !e.querySelector('*')
                             && /categor|outro|other/i.test(e.innerText||''))
                .slice(0,15).map(e => ({texto: norm(e.innerText).slice(0,80), rect: rect(e)}));
            const opcoes = [...document.querySelectorAll('[role="option"],[role="radio"],li,[role="menuitem"]')]
                .filter(vis).slice(0,40).map(e => norm(e.innerText).slice(0,60))
                .filter(t => t);
            const inputs = [...document.querySelectorAll('input,textarea')]
                .filter(vis).slice(0,12).map(e => ({
                    aria: norm(e.getAttribute('aria-label')||''),
                    ph: norm(e.placeholder||''),
                    val: norm(e.value||'').slice(0,40),
                    expanded: e.getAttribute('aria-expanded')||'',
                }));
            return {url: location.href, combos, labels, opcoes, inputs};
        }""") or {}
        from server.screen_capture import salvar_diagnostico
        salvar_diagnostico('categoria_outro', dados, tirar_screenshot=driver)
    except Exception as e:
        logger.debug("[FULL/DataCrazy] dump diagnóstico categoria falhou: %s", e)


# ============================================================================
# MÁQUINA DE ESTADOS DO OAUTH (embedded signup do Facebook)
# ============================================================================

def _texto_oauth(driver):
    """innerText (lowercase) da página atual do OAuth, para detectar a tela."""
    try:
        return (driver.evaluate_page(
            "() => (document.body && document.body.innerText) || ''") or '').lower()
    except Exception:
        return ''


def _oauth_signup_concluido(driver, popup_page=None):
    """True se o embedded signup CONCLUIU com sucesso: a popup do OAuth FECHOU ou
    navegou p/ a página terminal de fechamento (dialog/close_window com connect=1) — o
    estado após 'Concluir', quando a WABA JÁ foi criada. `connect=1` é o marcador de
    sucesso (um cancelamento não o traz). Idioma-agnóstico (só URL/estado da popup)."""
    try:
        if popup_page is not None and popup_page.is_closed():
            return True
    except Exception:
        pass
    try:
        u = (driver.evaluate_page("() => location.href") or '').lower()
        if 'close_window' in u and ('connect=1' in u or 'connect%3d1' in u):
            return True
    except Exception:
        pass
    return False


def _detectar_passo_oauth(driver, traduzir=True):
    """Identifica em QUAL tela do OAuth estamos pelo HEADING VISÍVEL NO VIEWPORT.

    CRÍTICO: o diálogo do FB mantém TODOS os passos do wizard no DOM (carrossel),
    então document.body.innerText contém o texto de telas que ainda não estão na
    frente — isso fazia o detector 'pular' (ex.: ver 'categoria de negócios' da
    tela de dados enquanto ainda na tela de ativos). Por isso só consideramos um
    marcador quando o ELEMENTO que o contém está de fato dentro do viewport.

    A ordem vai do passo MAIS avançado para o menos — se dois marcadores
    estiverem visíveis numa transição, vence o estágio mais à frente."""
    try:
        passo = driver.evaluate_page(_JS_PASSO_OAUTH)
    except Exception:
        return None
    if passo or not traduzir:
        return passo
    # Conta fora do pt (2026-10-13): traduz SÓ os textos curtos VISÍVEIS no viewport
    # (o carrossel guarda os outros passos no DOM) e casa as MESMAS frases dos passos.
    try:
        from server.tradutor_tela import precisa_traduzir, traduzir_lote, idioma_pagina
        if not precisa_traduzir(idioma_pagina(driver)):
            return None
        textos = driver.evaluate_page(_JS_TEXTOS_VIEWPORT_OAUTH) or []
        if not textos:
            return None
        trads = traduzir_lote(textos[:40])
        if not trads:
            return None
        passo = driver.evaluate_page(_JS_PASSO_OAUTH, [t.lower() for t in trads])
        if passo:
            logger.info("[FULL/DataCrazy] OAuth: passo '%s' reconhecido pela TRADUÇÃO pt-BR.", passo)
        return passo
    except Exception:
        return None


# Textos curtos (≤200) DENTRO do viewport — mesmos critérios do detector de passo.
_JS_TEXTOS_VIEWPORT_OAUTH = r"""() => {
    const vw = window.innerWidth || document.documentElement.clientWidth;
    const vh = window.innerHeight || document.documentElement.clientHeight;
    const inView = (el) => { const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return false;
        const cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
        return cx > 0 && cx < vw && cy > 0 && cy < vh; };
    const out = [], vistos = new Set();
    for (const el of document.querySelectorAll('h1,h2,h3,h4,label,strong,p,span,div')) {
        const t = ((el.innerText || '') + '').trim().replace(/\s+/g, ' ');
        if (!t || t.length > 200 || vistos.has(t) || !inView(el)) continue;
        // só folhas/quase-folhas (evita repetir o texto do pai que agrega os filhos)
        if (el.children.length > 3) continue;
        vistos.add(t); out.push(t);
        if (out.length >= 40) break;
    }
    return out;
}"""

_JS_PASSO_OAUTH = """(extra) => {
            const steps = [
                ['conectada', ['sua conta está conectada','sua conta esta conectada',
                               'account is connected','assets successfully created',
                               'ativos criados com sucesso','reservamos este número de telefone',
                               'reservamos este numero de telefone']],
                // NOVO (2026-08-20): tela de ESPERA logo após 'Confirmar' — a Meta está
                // criando os ativos (a WABA nasce AQUI). Não é erro nem tela travada:
                // basta aguardar (ou clicar 'Tentar novamente' se ficar parada).
                ['conectando', ['conectando sua conta','conectando a sua conta',
                                'isso pode levar alguns instantes','connecting your account',
                                'this may take a few moments','this might take a few moments']],
                ['reveja', ['reveja o que você vai compartilhar','reveja o que voce vai compartilhar',
                            "you're sharing",'review the information','reveja as informações',
                            'analise a solicitação de acesso','analise a solicitacao de acesso',
                            'solicitação de acesso do gupshup','solicitacao de acesso do gupshup',
                            'está solicitando acesso a','esta solicitando acesso a',
                            'is requesting access to']],
                ['criar_perfil', ['crie um perfil do whatsapp business',
                                  'este perfil mostrará','este perfil mostrara',
                                  'nome da conta do whatsapp business',
                                  'create a whatsapp business profile']],
                ['criar_conta', ['crie ou selecione sua conta do whatsapp business',
                                 'esta conta do whatsapp business pertencerá',
                                 'esta conta do whatsapp business pertencera',
                                 'create or select your whatsapp business account']],
                ['preencha_dados', ['preencha os dados da empresa',
                                    'selecione um portfólio empresarial',
                                    'selecione um portfolio empresarial',
                                    'fill in your business details',
                                    'fill in business details',
                                    'enter your business details']],
                ['config', ['selecione sua configuração','selecione sua configuracao',
                            'como você quer realizar a integração',
                            'como voce quer realizar a integracao',
                            'insira um novo número de telefone do whatsapp para começar',
                            'insira um novo numero de telefone do whatsapp para comecar',
                            'select your configuration']],
                ['dados', ['insira os dados da empresa','dados da empresa para os novos',
                           'escolha uma categoria','categoria de negócios','categoria de negocios',
                           'business category']],
                ['ativos', ['selecione os ativos de negócios','selecione os ativos de negocios',
                            'selecione os ativos','select your business assets',
                            'select business assets','select the business assets',
                            'business assets to share','ativos de negócios para compartilhar',
                            'ativos para compartilhar']],
                // NOVO FLUXO (2026-08-15): "Verificação adicional necessária" aparece
                // logo após escolher "usar somente um nome de exibição" na tela de número.
                ['verif_adicional', ['verificação adicional necessária','verificacao adicional necessaria',
                                     'verificação adicional é necessária','verificacao adicional e necessaria',
                                     'additional verification required','additional verification needed']],
                // 'numero' agora vem ANTES de ativos/dados no novo fluxo (não é mais o
                // passo terminal) — fica com prioridade BAIXA p/ que ativos/dados vençam
                // numa transição em que os dois estejam visíveis.
                ['numero', ['adicione seu número','adicione seu numero','add a phone number',
                            'add your whatsapp phone number',
                            'choose how you want to be identified',
                            'escolha como você quer ser identificado',
                            'escolha como voce quer ser identificado',
                            'usar somente um nome','use only a display name',
                            'usar um número virtual','usar um numero virtual',
                            'use a display name with a virtual number',
                            'número de telefone existente','numero de telefone existente',
                            "you don't have any existing phone number"]],
                ['conecte', ['conecte sua conta','connect your account',
                             'conecte sua conta a datacrazy','permissões que você compartilhará',
                             'permissoes que voce compartilhara']],
                ['continuar_como', ['continuar como','continue as',
                                    'gupshup receberá seu nome','gupshup recebera seu nome',
                                    'gupshup will receive your name',
                                    'novas contas não serão aprovadas',
                                    'novas contas nao serao aprovadas']],
            ];
            // Modo TRADUÇÃO: `extra` = textos do viewport já traduzidos p/ pt-BR.
            if (Array.isArray(extra)) {
                for (const [key, frases] of steps)
                    for (const t of extra)
                        for (const f of frases)
                            if (t && t.includes(f)) return key;
                return null;
            }
            const vw = window.innerWidth || document.documentElement.clientWidth;
            const vh = window.innerHeight || document.documentElement.clientHeight;
            const inView = (el) => {
                const r = el.getBoundingClientRect();
                if (r.width < 1 || r.height < 1) return false;
                // exige o CENTRO do elemento dentro do viewport — estável durante
                // a animação de slide entre telas (não pega a tela que só começou
                // a entrar pela borda).
                const cx = (r.left + r.right) / 2;
                const cy = (r.top + r.bottom) / 2;
                return cx > 0 && cx < vw && cy > 0 && cy < vh;
            };
            const els = document.querySelectorAll('h1,h2,h3,h4,div,span,strong,label,p');
            for (const [key, frases] of steps) {
                for (const el of els) {
                    const t = (el.innerText || '').toLowerCase();
                    if (!t || t.length > 200) continue;   // pula contêineres grandes
                    for (const f of frases) {
                        if (t.includes(f) && inView(el)) return key;
                    }
                }
            }
            return null;
        }"""


def _aguardar_saida_passo(driver, passo, timeout=14, popup_page=None):
    """Aguarda a tela SAIR de `passo` — ou seja, detectar um passo DIFERENTE e
    conhecido (transição real) ou a popup fechar. Leituras transitórias 'None'
    NÃO contam como avanço (evita falso-positivo de 'pulou etapa')."""
    fim = time.time() + timeout
    _ult_tr = 0.0
    while time.time() < fim:
        if popup_page is not None:
            try:
                if popup_page.is_closed():
                    return True
            except Exception:
                # is_closed() levantou = popup detached; NÃO conta como transição real.
                # Segue lendo o conteúdo do driver (a decisão final de sucesso é do loop
                # principal, já endurecido). Evita falso 'avançou de passo'.
                popup_page = None
        # polling rápido: tradução (conta fora do pt) no máx. a cada 1,5s
        _tr = time.time() - _ult_tr >= 1.5
        if _tr:
            _ult_tr = time.time()
        atual = _detectar_passo_oauth(driver, traduzir=_tr)
        if atual is not None and atual != passo:
            return True
        time.sleep(0.15)
    return False


def _esperar_estavel_oauth(driver, popup_page=None, timeout=20, settle=0.6):
    """Espera a popup do OAuth carregar 100% e ficar ESTÁTICA antes de detectar a
    tela — em vez de delay fixo. Assim, mesmo quando a tela carrega rápido (ou
    devagar), só seguimos quando ela está realmente pronta e parada.

    IMPORTANTE: NÃO dá F5 aqui (f5_after gigante) — recarregar a janela do OAuth
    no meio do fluxo resetaria o assistente e perderia o progresso."""
    pg = popup_page or getattr(driver, '_current_page', None)
    if pg is not None:
        try:
            pg.wait_for_load_state('domcontentloaded', timeout=int(timeout * 1000))
        except Exception:
            pass
        # NÃO esperamos 'networkidle': páginas do FB têm rede contínua e nunca
        # ficam idle — quem detecta "carregou 100% e estática" é o wait_until_stable
        # abaixo (estabilização do DOM), não o tráfego de rede.
    try:
        from server.page_state_manager import PageStateManager
        PageStateManager.wait_until_stable(
            driver, timeout=timeout, settle_time=settle,
            f5_after=10 ** 6, callback_status=None)
    except Exception:
        time.sleep(min(timeout, max(settle, 0.6)))


def _aguardar_avancar_oauth_habilitado(driver, timeout=8):
    """Espera o botão de avanço do OAuth ficar HABILITADO (ignora as cópias ocultas
    aria-hidden que a Meta duplica). True se habilitou; False no timeout."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            st = driver.evaluate_page(r"""() => {
                const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
                const alvos = ['avançar','avancar','next','continuar','continue','siguiente','tiếp',
                               'далее','berikutnya','lanjut','suivant','weiter','avanti','ileri','dalej'];
                const bs = [...document.querySelectorAll('div[role="button"],button,[role="button"]')]
                    .filter(b => vis(b) && b.getAttribute('aria-hidden') !== 'true' && !b.closest('[aria-hidden="true"]'))
                    .filter(b => { const t = (b.innerText || '').trim().toLowerCase();
                                   return alvos.some(a => t === a || (t.includes(a) && t.length <= a.length + 18)); });
                if (!bs.length) return 'sem';
                return bs.some(b => b.getAttribute('aria-disabled') !== 'true' && !b.disabled) ? 'on' : 'off';
            }""")
        except Exception:
            st = 'sem'
        if st in ('on', 'sem'):
            return True
        time.sleep(0.4)
    return False


def _click_oauth_avancar(driver, timeout=12):
    """Clica Avançar/Next/Continuar do diálogo OAuth. (1) clique natural; (2) FALLBACK
    ROBUSTO por JS dispatch no botão de avanço VISÍVEL e HABILITADO do diálogo. Motivo
    (2026-07-13): o Avançar do FB é um div[role=button] React que às vezes tem overlay e
    o clique natural NÃO registra — prendendo o fluxo nas telas 'Preencha os dados'/
    'Selecione os ativos' (causava 'não alcançou a etapa de número/nome')."""
    if _click_texto(
            driver, ['Avançar', 'Next', 'Continuar', 'Continue'],
            seletor_base='[role="button"], div[role="button"], button, span, div',
            timeout=timeout):
        return True
    try:
        if bool(driver.evaluate_page(r"""() => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
            // PT/EN + outros idiomas (2026-10-12): conta fora do pt/en não tinha rótulo
            // nenhum aqui e o Avançar nunca era clicado.
            const alvos = ['avançar','avancar','next','continuar','continue',
                           'siguiente','tiếp tục','tiếp','далее','продолжить','berikutnya',
                           'selanjutnya','lanjutkan','lanjut','आगे बढ़ें','अगला','जारी रखें',
                           'suivant','continuer','weiter','avanti','continua','ileri','i̇leri',
                           'devam','dalej','kontynuuj','далі','продовжити','susunod',
                           'magpatuloy','ถัดไป','ดำเนินการต่อ','التالي','متابعة','下一步',
                           '继续','繼續','次へ','続ける','다음','계속'];
            const dlg = document.querySelector('[role="dialog"]') || document;
            const bs = [...dlg.querySelectorAll('div[role="button"],button,[role="button"]')].filter(vis);
            for (const b of bs){
                const t = ((b.innerText||'')+'').trim().toLowerCase();
                // 'contém' só em rótulo CURTO (botão), nunca num card/parágrafo clicável.
                if (!alvos.some(a => t===a || (t.includes(a) && t.length <= a.length + 18))) continue;
                if (b.getAttribute('aria-disabled')==='true' || b.disabled) continue;
                try {
                    const r=b.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
                    for (const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
                        b.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,view:window,clientX:x,clientY:y}));
                    return true;
                } catch(e){ try{ b.click(); return true; }catch(_){} }
            }
            return false;
        }""")):
            return True
    except Exception:
        pass
    # (3) FALLBACK ESTRUTURAL idioma-agnóstico: botão PRIMÁRIO (azul) habilitado do
    #     diálogo, respeitando a lista negra (nunca Cancelar/Voltar/Não permitir).
    return bool(_avancar_tela_desconhecida(driver, so_primario=True))


def _avancar_tela_desconhecida(driver, so_primario=False):
    """PLANO B para tela do OAuth NÃO reconhecida (2026-08-20).

    A Meta muda o embedded signup com frequência (o dono já caiu em variações novas
    do wizard: número virtual -> ativos -> dados -> Reveja -> Conectando -> Concluir).
    Quando o detector não sabe QUAL é a tela, em vez de girar até abortar, tentamos
    seguir em frente clicando o botão de AVANÇO VISÍVEL e HABILITADO do diálogo,
    obedecendo uma ORDEM de preferência e uma LISTA NEGRA (nunca Cancelar/Voltar/
    Não permitir/Adicionar forma de pagamento/Sair — isso mataria o fluxo ou geraria
    custo). Retorna o rótulo clicado ('' se não achou nada seguro).

    MULTI-IDIOMA (2026-10-12): as listas eram só PT/EN — numa conta em vietnamita/
    russo/indonésio/hindi/espanhol... nenhum botão casava, o plano B nunca clicava e o
    fluxo abortava após 12 voltas. Agora (1) os rótulos cobrem os idiomas principais e
    (2) há um FALLBACK ESTRUTURAL idioma-agnóstico: o botão PRIMÁRIO do diálogo (fundo
    AZUL da Meta, #0866FF/#1877F2) habilitado e fora da lista negra.
    `so_primario=True` pula a busca por rótulo e usa só o fallback estrutural."""
    js = r"""(soPrimario) => {
        const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
            const s=getComputedStyle(e);
            if (r.width<1||r.height<1||s.visibility==='hidden'||s.display==='none') return false;
            const vw = window.innerWidth||document.documentElement.clientWidth;
            const vh = window.innerHeight||document.documentElement.clientHeight;
            const cx=(r.left+r.right)/2, cy=(r.top+r.bottom)/2;
            return cx>0 && cx<vw && cy>0 && cy<vh; };
        // ordem = preferência (avançar primeiro, 'ok' por último)
        const ordem = ['avançar','avancar','next','continuar','continue',
                       // avançar/continuar em outros idiomas (ES/VI/RU/ID/HI/FR/DE/IT/TR/PL/UK/TL/TH/AR/ZH/JA/KO)
                       'siguiente','tiếp tục','tiếp','далее','продолжить','berikutnya','selanjutnya',
                       'lanjutkan','lanjut','आगे बढ़ें','अगला','जारी रखें','suivant','continuer',
                       'weiter','avanti','continua','ileri','i̇leri','devam','dalej','kontynuuj',
                       'далі','продовжити','susunod','magpatuloy','ถัดไป','ดำเนินการต่อ',
                       'التالي','متابعة','下一步','继续','繼續','次へ','続ける','다음','계속',
                       'confirmar','confirm','concluir','concluído','concluido','done','finish',
                       'xác nhận','подтвердить','konfirmasi','पुष्टि करें','confirmer','bestätigen',
                       'conferma','onayla','potwierdź','підтвердити','kumpirmahin','ยืนยัน','تأكيد',
                       '确认','確認','확인',
                       'listo','finalizar','hoàn tất','xong','готово','selesai','हो गया','terminé',
                       'terminer','fertig','fatto','bitti','gotowe','tapos na','เสร็จสิ้น','完成','完了','완료',
                       'começar','comecar','get started','empezar','comenzar','bắt đầu','начать',
                       'mulai','शुरू करें','commencer','los geht','inizia','başla','zacznij','почати',
                       'tentar novamente','try again','reintentar','thử lại','повторить','coba lagi',
                       'फिर से कोशिश करें','réessayer','erneut versuchen','riprova','tekrar dene',
                       'spróbuj ponownie','спробувати ще раз','ok'];
        const bloq = ['cancelar','cancel','voltar','back','não permitir','nao permitir',
                      "don't allow",'dont allow','sair','log out','sign out','desconect',
                      'adicionar forma de pagamento','add payment','forma de pagamento',
                      'excluir','remover','delete','remove','denunciar','report',
                      'adicione outra conta','add another account','entrar em outra',
                      'saiba mais','learn more','política de privacidade','politica de privacidade',
                      'termos','terms',
                      // recusar / outra conta / não é você (PT/EN)
                      'recusar','decline','reject','not you','não é você','nao e voce',
                      'switch account','trocar de conta','usar outra conta','use another account',
                      // cancelar / voltar / não permitir / recusar / sair em outros idiomas
                      'hủy','quay lại','trở lại','không cho phép','từ chối','đăng xuất',
                      'отмена','отменить','назад','не разрешать','отклонить','выйти',
                      'batal','kembali','jangan izinkan','tolak','keluar',
                      'रद्द','वापस','अनुमति न दें','लॉग आउट',
                      'annuler','retour','ne pas autoriser','refuser','déconnexion',
                      'abbrechen','zurück','nicht erlauben','ablehnen','abmelden',
                      'annulla','indietro','non consentire','rifiuta','esci',
                      'iptal','geri','izin verme','reddet','çıkış',
                      'anuluj','wstecz','nie zezwalaj','odrzuć','wyloguj',
                      'скасувати','не дозволяти','відхилити',
                      'kanselahin','bumalik',
                      'ยกเลิก','ย้อนกลับ','ไม่อนุญาต','ออกจากระบบ',
                      'إلغاء','رجوع','عدم السماح','رفض','تسجيل الخروج',
                      '取消','返回','不允许','拒绝','退出','キャンセル','戻る','許可しない','ログアウト',
                      '취소','뒤로','허용 안 함','거부','로그아웃',
                      'volver','atrás','rechazar','no permitir','cerrar sesión'];
        const dlg = document.querySelector('[role="dialog"]') || document;
        const bs = [...dlg.querySelectorAll('div[role="button"],button,[role="button"],a[role="button"]')]
                   .filter(vis);
        const desab = b => b.getAttribute('aria-disabled')==='true' || b.disabled;
        let melhor = null;  // [posicao_na_ordem, tamanho_do_texto, el, rotulo]
        if (!soPrimario) {
            for (const b of bs){
                const t = ((b.innerText||'')+'').trim().toLowerCase();
                if (!t || t.length > 60) continue;
                if (bloq.some(x => t.includes(x))) continue;
                if (desab(b)) continue;
                // Token latino CURTO ('ok') só casa como PALAVRA inteira — por substring
                // ele casava dentro de "facebook"/"book" e clicava o botão errado.
                const casa = a => {
                    if (a.length <= 3 && /^[a-z]+$/.test(a))
                        return t === a || new RegExp('(^|[^a-z])' + a + '([^a-z]|$)').test(t);
                    return t===a || t.startsWith(a) || (t.includes(a) && t.length <= a.length + 18);
                };
                const i = ordem.findIndex(casa);
                if (i < 0) continue;
                const cand = [i, t.length, b, t];
                if (!melhor || cand[0] < melhor[0] || (cand[0]===melhor[0] && cand[1] < melhor[1]))
                    melhor = cand;
            }
        }
        if (!melhor) {
            // FALLBACK ESTRUTURAL (idioma-agnóstico): botão PRIMÁRIO = fundo AZUL da Meta
            // (#0866FF / #1877F2 / #4267B2) no próprio botão ou num filho direto do layout.
            const azul = el => { try {
                const m = (getComputedStyle(el).backgroundColor||'').match(/rgba?\(([^)]+)\)/);
                if (!m) return false;
                const p = m[1].split(',').map(x => parseFloat(x));
                const a = p.length > 3 ? p[3] : 1;
                return a > 0.5 && p[2] >= 170 && (p[2]-p[0]) >= 100 && (p[2]-p[1]) >= 40;
            } catch(e){ return false; } };
            const temAzul = b => azul(b) || [...b.querySelectorAll('*')].slice(0, 8).some(azul);
            let prim = null;
            for (const b of bs){
                const t = ((b.innerText||'')+'').trim().toLowerCase();
                if (!t || t.length > 60) continue;
                if (bloq.some(x => t.includes(x))) continue;
                if (desab(b)) continue;
                if (!temAzul(b)) continue;
                // pega o MAIS INTERNO (evita o wrapper) e, entre botões distintos, o
                // mais abaixo/à direita (rodapé do diálogo = ação de avanço).
                if (prim && prim.contains(b)) { prim = b; continue; }
                if (prim && b.contains(prim)) continue;
                const r = b.getBoundingClientRect(), rp = prim && prim.getBoundingClientRect();
                if (!prim || r.bottom > rp.bottom + 2 || (Math.abs(r.bottom-rp.bottom) <= 2 && r.right > rp.right))
                    prim = b;
            }
            if (prim) melhor = [99, 0, prim, 'primario:' + ((prim.innerText||'')+'').trim().toLowerCase()];
        }
        if (!melhor) return '';
        const b = melhor[2];
        try {
            const r=b.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
            for (const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
                b.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,view:window,clientX:x,clientY:y}));
        } catch(e){ try{ b.click(); }catch(_){ return ''; } }
        return melhor[3];
    }"""
    try:
        return driver.evaluate_page(js, bool(so_primario)) or ''
    except Exception as e:
        logger.debug("[FULL/DataCrazy] avanço genérico falhou: %s", e)
        return ''


# JS único usado por _selecionar_nome_exibicao() e _tem_opcao_numero_virtual().
#
# Reescrito 2026-08-28 depois de o fluxo travar em loop na tela de número. Os dois
# defeitos da versão anterior, ambos provados pelos prints do dono:
#
#  1) Casava com QUALQUER div/span contendo "display name"/"nome de exibição" e com
#     texto < 160 chars. O elemento que ENVOLVE as duas opções do dropdown tem ~110
#     chars e casava primeiro → o clique caía no contêiner da lista, a opção nunca
#     fixava e o "Avançar" seguia desabilitado para sempre.
#     → Agora só clica em FOLHA (elemento que bate e não contém outro que bata) e o
#       discriminador é a palavra "virtual", que só existe na opção certa.
#
#  2) Devolvia sucesso assim que um clique acontecia, sem conferir NADA.
#     → Agora só devolve sucesso quando o campo Telefone realmente passa a exibir a
#       opção do número virtual (ou o aviso "Verificação adicional necessária" toma
#       o lugar do placeholder), que é o que habilita o Avançar.
#
# modo 'existe'    → a tela oferece número virtual? (separa layout NOVO de layout
#                    ANTIGO terminal, para não declarar sucesso sem WABA)
# modo 'selecionar'→ 'ja' | 'ok' | 'clicou' | 'abriu' | ''
_JS_NUMERO_VIRTUAL = r"""(modo) => {
    const norm = s => (s||'').toLowerCase().replace(/\s+/g,' ').trim();
    const vis = e => { if(!e) return false;
        const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
    const dlg = document.querySelector('[role="dialog"]') || document;

    // Opção ERRADA (a default): fala em número existente / criar um novo.
    const NAO = ['numero de telefone existente','número de telefone existente',
                 'crie um novo','crie um nov','no existing phone','create a new'];
    const ehPlaceholder = t => NAO.some(p => t.includes(p));

    // Opção CERTA: sempre tem "virtual" (a tela é PT mas a opção vem em EN).
    // + "virtual" em outros idiomas (2026-10-12): VI 'số ảo', RU/UK 'виртуальн'/'віртуальн',
    //   HI 'वर्चुअल', FR 'virtuel', DE 'virtuell', TR 'sanal numara', ZH/JA/KO, TH, AR.
    //   (ES/IT já casam 'número virtual'/'numero virtual(e)'; ID = 'nomor virtual'.)
    //   NÃO incluir 'virtual' solto: casaria texto de ajuda no PT/EN e mudaria o 'selecionado'.
    const VIRT = ['nomor virtual', 'số ảo', 'виртуальн', 'віртуальн', 'वर्चुअल', 'virtuel', 'virtuell',
                  'sanal numara', '虚拟', '虛擬', '仮想', 'バーチャル', '가상', 'เสมือน', 'افتراضي'];
    const ehVirtual = t => !ehPlaceholder(t) && (
          t.includes('virtual number') || t.includes('numero virtual') ||
          t.includes('número virtual')  || (t.includes('display name') && t.includes('virtual')) ||
          t.includes('somente um nome de exib') || t.includes('use only a display name') ||
          VIRT.some(v => t.includes(v)));

    const universo = () => [...dlg.querySelectorAll(
        '[role="option"],[role="radio"],[role="combobox"],li,label,div,span,input,select')].filter(vis);

    // SÓ FOLHAS: bate no critério e não contém outro elemento que também bate.
    const folhas = pred => {
        const bate = universo().filter(e => {
            const t = norm(e.innerText || e.textContent || e.value || '');
            return t && t.length < 200 && pred(t); });
        return bate.filter(e => !bate.some(o => o !== e && e.contains(o)));
    };

    // Layout NOVO (print do dono): as opções são RADIO buttons ("Usar somente um nome
    // de exibição" / "Adicionar um novo número"), não um dropdown. O texto do radio fica
    // SEMPRE visível — então "texto visível" NÃO é "selecionado"; o que vale é o radio
    // estar MARCADO (checked/aria-checked).
    const radios = () => [...dlg.querySelectorAll('input[type="radio"],[role="radio"]')].filter(vis);
    const labelTexto = r => {
        let lab = r.closest('label');
        if (!lab && r.id) { try { lab = dlg.querySelector('label[for="'+
            ((window.CSS&&CSS.escape)?CSS.escape(r.id):r.id)+'"]'); } catch(e){} }
        if (!lab) lab = r.closest('[role="radio"]') || r.parentElement;
        return norm((lab && (lab.innerText || lab.textContent)) || '');
    };
    // + sinal ESTRUTURAL idioma-agnóstico: o radio do número virtual tem value
    //   'virtual_number' (mesmo atributo que o fallback Python já usa).
    const radioVirtual = () => radios().find(r => {
        const t = labelTexto(r); return t && ehVirtual(t) && !ehPlaceholder(t); })
        || radios().find(r => /virtual/i.test((r.value || '') + ' ' + ((r.getAttribute && r.getAttribute('value')) || '')))
        || null;
    const radioChecked = r => { if (!r) return false;
        if (r.checked === true) return true;
        if (r.getAttribute && r.getAttribute('aria-checked') === 'true') return true;
        const w = r.closest && r.closest('[role="radio"]');
        return !!(w && w.getAttribute('aria-checked') === 'true'); };

    const listaAberta = () =>
        [...document.querySelectorAll('[role="listbox"],[role="menu"]')].filter(vis).length > 0;

    // Com a lista FECHADA, ver o texto da opção virtual na tela = o campo Telefone
    // está exibindo aquele valor, ou seja, a escolha fixou.
    const selecionado = () => {
        // Layout RADIO: só está selecionado se o radio certo estiver MARCADO.
        const rv = radioVirtual();
        if (rv) return radioChecked(rv);
        // Layout DROPDOWN (antigo): opção visível com a lista fechada = valor fixado.
        if (listaAberta()) return false;
        if (folhas(ehVirtual).length) return true;
        if (folhas(ehPlaceholder).length) return false;   // ainda no valor default
        const corpo = norm((document.body && document.body.innerText) || '');
        return corpo.includes('verificação adicional') || corpo.includes('verificacao adicional')
            || corpo.includes('additional verification');
    };

    if (modo === 'existe') {
        if (radioVirtual() || selecionado() || folhas(ehVirtual).length) return true;
        return folhas(ehPlaceholder).length > 0;
    }

    if (selecionado()) return 'ja';

    // 0) Layout RADIO (print do dono): marca o radio "Usar somente um nome de exibição".
    {
        const rv = radioVirtual();
        if (rv) {
            const alvo = rv.closest('label,[role="radio"]') || rv;
            try { alvo.scrollIntoView({block:'center'}); } catch(e) {}
            try { rv.click(); } catch(e) {}
            if (!radioChecked(rv)) { try { alvo.click(); } catch(e) {} }
            if (!radioChecked(rv)) {
                try { const b = alvo.getBoundingClientRect(), x = b.left+b.width/2, y = b.top+b.height/2;
                    for (const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
                        alvo.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,clientX:x,clientY:y}));
                } catch(e) {}
            }
            return radioChecked(rv) ? 'ok' : 'clicou';
        }
    }

    const clicar = el => {
        const alvo = el.closest('[role="option"],[role="radio"],label,li') || el;
        try { alvo.scrollIntoView({block:'center'}); } catch(e) {}
        try { alvo.click(); return true; } catch(e) {}
        try {
            const r = alvo.getBoundingClientRect(), x = r.left+r.width/2, y = r.top+r.height/2;
            for (const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
                alvo.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,clientX:x,clientY:y}));
            return true;
        } catch(e) {}
        return false;
    };

    // 1) <select> nativo
    for (const sel of dlg.querySelectorAll('select')) {
        for (const op of sel.options) {
            if (ehVirtual(norm(op.textContent))) {
                sel.value = op.value;
                sel.dispatchEvent(new Event('input',{bubbles:true}));
                sel.dispatchEvent(new Event('change',{bubbles:true}));
                return selecionado() ? 'ok' : 'clicou';
            } } }

    // 2) opção do número virtual já visível → clica nela
    let alvo = folhas(ehVirtual);
    if (alvo.length && clicar(alvo[0])) return selecionado() ? 'ok' : 'clicou';

    // 3) abre o dropdown do TELEFONE. Só se a lista NÃO estiver aberta — senão o
    //    clique fecharia a lista, e o placeholder também é uma opção lá dentro
    //    (clicar nele escolheria justamente a opção errada).
    if (!listaAberta()) {
        const bloq = t => t.includes('adicione outra conta') || t.includes('add another account') ||
                          t.includes('desconect') || t.includes('log out') || t.includes('sign out') ||
                          t.includes('avançar') || t.includes('avancar') || t.includes('voltar') ||
                          t.includes('next') || t.includes('back') || t.includes('confirm');
        const ph = folhas(t => ehPlaceholder(t) && !bloq(t));
        if (ph.length) {
            const abrir = ph[0].closest('[role="combobox"],[role="button"],button,label') || ph[0];
            try { abrir.scrollIntoView({block:'center'}); } catch(e) {}
            try { abrir.click(); } catch(e) {}

            // 3b) o dropdown tem campo "Search term": filtra por 'virtual' e sobra 1.
            const busca = [...document.querySelectorAll(
                'input[type="text"],input[type="search"],input:not([type])')].filter(vis)[0];
            if (busca) {
                try {
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    setter.call(busca, 'virtual');
                    busca.dispatchEvent(new Event('input', {bubbles:true}));
                } catch(e) {}
            }
            alvo = folhas(ehVirtual);
            if (alvo.length && clicar(alvo[0])) return selecionado() ? 'ok' : 'clicou';
            return 'abriu';   // opções ainda renderizando; o Python re-tenta
        }
    }
    return '';
}"""


def _selecionar_nome_exibicao(driver, timeout=10):
    """Seleciona 'Use a display name with a virtual number instead' (usar número VIRTUAL)
    na tela de número. A opção fica DENTRO do dropdown 'Telefone' (placeholder 'Você não
    tem nenhum número... Crie um novo').
    ⚠️ FIX 2026-08-16 (provado por print): a versão antiga abria o PRIMEIRO combobox da
    página — que é o SELETOR DE CONTA no topo-direito (avatar → 'Adicione outra conta') —
    e clicava no lugar errado. Agora achamos o dropdown certo pelo TEXTO do placeholder do
    Telefone, BLOQUEANDO o seletor de conta/botões de navegação, abrimos e escolhemos a
    opção do número virtual (loop abrir→escolher, pois as opções renderizam async)."""
    js = _JS_NUMERO_VIRTUAL
    fim = time.time() + timeout
    ultimo = ''
    while time.time() < fim:
        try:
            r = driver.evaluate_page(js, 'selecionar')
        except Exception as e:
            logger.debug("[OAuth] selecionar numero virtual: %s", e)
            r = ''
        ultimo = r or ultimo
        # 'ja'/'ok' = opção CONFIRMADA no campo Telefone (única saída de sucesso).
        if r in ('ja', 'ok'):
            return True
        # 'abriu'  = dropdown aberto, opções ainda renderizando
        # 'clicou' = clicou mas a confirmação não veio (React ainda processando)
        time.sleep(0.4)
    logger.warning("[OAuth] numero virtual NAO confirmado (ultimo estado=%r)", ultimo)
    # fallback: seletor de input conhecido
    return _click_seletor(driver, 'input[value="virtual_number"], input[name="js_4o"]', timeout=2)


def _tem_opcao_numero_virtual(driver):
    """A tela de número oferece a opção de NÚMERO VIRTUAL? (ou seja, é o layout NOVO)

    Serve para separar dois casos que antes eram confundidos e custavam uma BM:
      • layout NOVO travado  → a opção existe mas não conseguimos selecionar. NÃO é
        sucesso: a WABA ainda não nasceu.
      • layout ANTIGO terminal → não existe opção nenhuma; a tela de número é o fim
        do fluxo e a WABA já foi criada antes.
    """
    try:
        return bool(driver.evaluate_page(_JS_NUMERO_VIRTUAL, 'existe'))
    except Exception:
        return False


def _detectar_restricao_bm(driver):
    """Detecta a mensagem de BM/conta WhatsApp RESTRITA na tela atual (popup ou
    aba). Cobre a restrição do WABA (Gupshup/embedded signup) E a restrição de
    portfólio para anunciar — em qualquer uma o onboarding não conclui."""
    try:
        return bool(driver.evaluate_page("""() => {
            const t = ((document.body && document.body.innerText) || '').toLowerCase();
            const termos = [
                'sua conta do whatsapp business está restrita',
                'sua conta do whatsapp business esta restrita',
                'conta do whatsapp business está restrita',
                'conta do whatsapp business esta restrita',
                'whatsapp business account is restricted',
                'está restrita no momento',
                'esta restrita no momento',
                'não pode usar este portfólio empresarial para anunciar',
                'nao pode usar este portfolio empresarial para anunciar',
                'portfólio empresarial com restrições para anunciar',
                'portfolio empresarial com restricoes para anunciar',
                'restrições para anunciar',
                'restricoes para anunciar',
                "you can't use this business portfolio",
                'business portfolio restricted',
                'account restricted'
            ];
            for (const x of termos) { if (t.indexOf(x) !== -1) return true; }
            return false;
        }"""))
    except Exception:
        return False


def _preencher_nomes_perfil_waba(driver, nome):
    """Preenche 'Nome da conta' E 'Nome de exibição' do WhatsApp Business de forma
    React-safe (setter nativo + eventos).

    IMPORTANTE: a WABA tem que ter EXATAMENTE a RAZÃO SOCIAL. O FB às vezes
    PRÉ-PREENCHE esses campos com o nome do TITULAR da conta (ex.: 'Andre Costa'),
    que não tem relação com a empresa. Por isso SOBRESCREVEMOS sempre que o valor
    atual for diferente da razão social (antes só preenchíamos se vazio → ficava o
    nome errado). Retorna True se o 'Nome da conta' ficou preenchido."""
    js = r"""(nome) => {
        const norm = s => (s||'').toLowerCase();
        const setVal = (inp, v) => {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            try{ inp.focus(); }catch(e){}
            setter.call(inp, ''); inp.dispatchEvent(new Event('input',{bubbles:true}));
            setter.call(inp, v);  inp.dispatchEvent(new Event('input',{bubbles:true}));
            inp.dispatchEvent(new Event('change',{bubbles:true}));
            inp.dispatchEvent(new Event('blur',{bubbles:true}));
        };
        const difere = (inp, v) => (inp.value||'').trim().toLowerCase() !== (v||'').trim().toLowerCase();
        const rotuloDe = (inp) => {
            const c = [];
            if (inp.getAttribute('aria-label')) c.push(inp.getAttribute('aria-label'));
            if (inp.placeholder) c.push(inp.placeholder);
            if (inp.id){ const l=document.querySelector('label[for="'+inp.id+'"]'); if(l) c.push(l.innerText); }
            let p=inp.parentElement, hop=0;
            while(p && hop<4){ const t=(p.innerText||''); if(t && t.length<140) c.push(t); p=p.parentElement; hop++; }
            return norm(c.join(' | '));
        };
        const inputs = [...document.querySelectorAll('input[type=text],input:not([type]),textarea')]
            .filter(e=>{const r=e.getBoundingClientRect(); return r.width>1&&r.height>1&&!e.disabled;});
        let conta=null, exib=null;
        for (const inp of inputs){
            const r = rotuloDe(inp);
            if (!conta && (r.includes('nome da conta') || r.includes('account name'))) { conta=inp; continue; }
            if (!exib && (r.includes('nome de exib') || r.includes('display name'))) { exib=inp; continue; }
        }
        // SOBRESCREVE com a razão social (não confia no pré-preenchido do FB).
        if (conta && difere(conta, nome)) setVal(conta, nome);
        if (exib && difere(exib, nome)) setVal(exib, nome);
        return !!(conta && (conta.value||'').trim().length>0);
    }"""
    ok = False
    for _ in range(4):
        try:
            ok = bool(driver.evaluate_page(js, nome))
        except Exception:
            ok = False
        if ok:
            break
        time.sleep(0.15)
    return ok


def _preencher_nome_negocio(driver, nome):
    """Na tela 'Insira os dados da empresa para os novos ativos' (passo 'dados') e
    'Preencha os dados da empresa' (passo 'preencha_dados'), o FB PRÉ-PREENCHE o
    campo 'Nome' com o nome do TITULAR da conta FB (ex.: 'Andre Costa'), que NÃO tem
    relação com a empresa. SOBRESCREVE com a RAZÃO SOCIAL (nome do negócio/portfólio
    e da WABA). React-safe. Não toca em Site/Categoria/País/Fuso. Retorna True se
    achou e ajustou o campo Nome."""
    js = r"""(nome) => {
        const norm = s => (s||'').toLowerCase();
        const setVal = (inp, v) => {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            try{ inp.focus(); }catch(e){}
            setter.call(inp, ''); inp.dispatchEvent(new Event('input',{bubbles:true}));
            setter.call(inp, v);  inp.dispatchEvent(new Event('input',{bubbles:true}));
            inp.dispatchEvent(new Event('change',{bubbles:true}));
            inp.dispatchEvent(new Event('blur',{bubbles:true}));
        };
        const rotuloDe = (inp) => {
            const c = [];
            if (inp.getAttribute('aria-label')) c.push(inp.getAttribute('aria-label'));
            if (inp.placeholder) c.push(inp.placeholder);
            if (inp.id){ const l=document.querySelector('label[for="'+inp.id+'"]'); if(l) c.push(l.innerText); }
            let p=inp.parentElement, hop=0;
            while(p && hop<4){ const t=(p.innerText||''); if(t && t.length<160) c.push(t); p=p.parentElement; hop++; }
            return norm(c.join(' | '));
        };
        const inputs = [...document.querySelectorAll('input[type=text],input:not([type]),textarea')]
            .filter(e=>{const r=e.getBoundingClientRect(); return r.width>1&&r.height>1&&!e.disabled;});
        for (const inp of inputs){
            const r = rotuloDe(inp);
            // campo "Nome/Name" do negócio (PT/EN/ES): tem 'nome'|'name'|'nombre' e NÃO é
            // conta/exibição/site/url/fuso/categoria/país/endereço (em qualquer idioma).
            const temNome = r.includes('nome') || r.includes('name') || r.includes('nombre');
            const ehExcluido =
                   r.includes('nome da conta') || r.includes('account name')
                || r.includes('nome de exib') || r.includes('display name') || r.includes('nombre visible')
                || r.includes('site') || r.includes('website') || r.includes('url')
                || r.includes('fuso') || r.includes('time zone') || r.includes('timezone') || r.includes('huso')
                || r.includes('categoria') || r.includes('category') || r.includes('categor')
                || r.includes('país') || r.includes('pais') || r.includes('country')
                || r.includes('endereço') || r.includes('endereco') || r.includes('address') || r.includes('direcc')
                || r.includes('user') || r.includes('usuario') || r.includes('usuário')
                || r.includes('phone') || r.includes('telefone') || r.includes('mail');
            if (temNome && !ehExcluido) {
                if ((inp.value||'').trim().toLowerCase() !== (nome||'').trim().toLowerCase())
                    setVal(inp, nome);
                return true;
            }
        }
        return false;
    }"""
    ok = False
    for _ in range(3):
        try:
            ok = bool(driver.evaluate_page(js, nome))
        except Exception:
            ok = False
        if ok:
            break
        time.sleep(0.1)
    return ok


def _confirmar_sugestao_nome_exibicao(driver):
    """Na tela 'Crie um perfil', ao digitar o NOME DE EXIBIÇÃO o FB abre um dropdown
    de SUGESTÃO que fica SOBRE o seletor de categoria — impedindo escolher 'Outro' e
    deixando o Avançar inativo. Aqui clicamos na 1ª sugestão (confirma o nome e fecha
    o dropdown); se não houver, dispensamos com Escape."""
    js = r"""() => {
        const vis = e => { const r=e.getBoundingClientRect();
            return r.width>0 && r.height>0 && (e.innerText||'').trim().length>0; };
        // itens de sugestão típicos do dropdown de autocomplete
        const opts = [...document.querySelectorAll(
            '[role="option"], ul[role="listbox"] li, div[role="listbox"] [role="option"], '
            + 'div[role="listbox"] div')].filter(vis);
        // pega a 1ª sugestão curta (um nome, não um container grande)
        for (const o of opts){
            if ((o.innerText||'').length < 120){ try{ o.click(); return true; }catch(e){} }
        }
        // SEM sugestão (layout 2): NÃO usar Escape (fecharia a popup do OAuth).
        // Dá um clique neutro num heading do diálogo só para tirar o foco do campo
        // e dispensar qualquer autocomplete — sem fechar o modal.
        const h = document.querySelector('[role="dialog"] h1, [role="dialog"] h2, [role="dialog"] h3, h2, h3');
        if (h){ try{ h.click(); }catch(e){} }
        return false;
    }"""
    try:
        return bool(driver.evaluate_page(js))
    except Exception:
        return False


def _resolver_cookie_consent_oauth(driver, status=None):
    """Resolve a tela de COOKIE que surge DENTRO do popup do OAuth
    (flow=user_cookie_choice_v2 → "Permitir que o Facebook use cookies?"), que NÃO
    é um passo do embedded signup. Sem isto o OAuth fica com passo=None e dá timeout
    (~5 min) sem alcançar a tela de número. Clica "Permitir todos os cookies"
    (multi-idioma), NUNCA "Recusar". Idioma-independente. Retorna True se agiu."""
    try:
        txt = _texto_oauth(driver)
    except Exception:
        txt = ''
    url = _url_atual(driver)
    # Só age se for o DIÁLOGO de cookies. Detecta por TEXTO **ou pela URL** —
    # `/dialog/cookie_consent/` é o marcador mais confiável (independe de idioma e
    # de mudanças de redação da Meta).
    marcadores = ['permitir que o facebook use cookies', 'allow the use of cookies',
                  'permitir o uso de cookies', 'cho phép sử dụng cookie của facebook',
                  'permitir todos os cookies', 'allow all cookies', 'cho phép tất cả cookie',
                  # variante NOVA (vista em 2026-08-03): "...cookies e tecnologias
                  # semelhantes inseridos em OUTROS APPS E SITES?" — botões
                  # 'Cancelar' e 'Permitir' (sem "todos os cookies").
                  'tecnologias semelhantes', 'similar technologies',
                  'cookies e tecnologias', 'cookies and similar']
    # URL é o marcador idioma-agnóstico: `/dialog/cookie_consent/` (v22) e o fluxo
    # `user_cookie_choice_v2` (variante clássica) — este último antes só era pego pelo
    # TEXTO PT/EN/VI e travava contas em outros idiomas (2026-10-12).
    _url_cookie = ('cookie_consent' in url) or ('cookie_choice' in url)
    if not (_url_cookie or (txt and any(m in txt for m in marcadores))):
        return False

    # 1) variante clássica: "Permitir TODOS os cookies".
    if _click_texto(driver, ['Permitir todos os cookies', 'Allow all cookies',
                             'Cho phép tất cả cookie', 'Aceitar todos os cookies',
                             'Permitir todos', 'Allow all', 'Aceitar tudo',
                             # outros idiomas (ES/RU/ID/FR/DE/IT/TR/PL)
                             'Permitir todas las cookies', 'Разрешить все файлы cookie',
                             'Разрешить все cookie', 'Izinkan semua cookie',
                             'Autoriser tous les cookies', 'Alle Cookies erlauben',
                             'Consenti tutti i cookie', 'Tüm çerezlere izin ver',
                             'Zezwól na wszystkie pliki cookie'],
                    seletor_base='[role="button"], button, div[role="button"], a, span',
                    timeout=8):
        if status:
            status("🍪 OAuth: permitindo cookies do Facebook...")
        logger.info("[FULL/DataCrazy] Cookie dialog no OAuth resolvido (Permitir todos).")
        return True

    # 2) variante NOVA (/v22.0/dialog/cookie_consent): só existem 'Cancelar' e
    #    'Permitir'. ⚠️ `exato=True` é OBRIGATÓRIO — sem ele o texto 'Permitir'
    #    casaria também **'Não permitir'**, e o fluxo NEGARIA o consentimento,
    #    travando o OAuth. Jamais incluir 'Cancelar'/'Recusar' nesta lista.
    if _click_texto(driver, ['Permitir', 'Allow', 'Aceitar', 'Accept',
                             # 'Permitir' em outros idiomas — SEMPRE exato (nunca casa a
                             # forma negativa: 'Không cho phép', 'Не разрешать', ...)
                             'Cho phép', 'Разрешить', 'Izinkan', 'अनुमति दें', 'Autoriser',
                             'Erlauben', 'Consenti', 'İzin ver', 'Zezwól', 'Дозволити',
                             'Payagan', 'อนุญาต', 'سماح', 'السماح', '允许', '許可', '허용'],
                    seletor_base='[role="button"], button, div[role="button"], a, span',
                    exato=True, timeout=8):
        if status:
            status("🍪 OAuth: consentimento de cookies (Permitir)...")
        logger.info("[FULL/DataCrazy] Cookie consent NOVO (dialog v22) resolvido: Permitir.")
        return True
    # 3) FALLBACK ESTRUTURAL (idioma-agnóstico), SÓ quando a URL confirma o diálogo de
    #    cookies: botão PRIMÁRIO azul (o 'Permitir'); a lista negra do plano B impede
    #    clicar Cancelar/Recusar/Não permitir em qualquer idioma.
    if _url_cookie:
        _rot = _avancar_tela_desconhecida(driver, so_primario=True)
        if _rot:
            if status:
                status("🍪 OAuth: consentimento de cookies (botão primário)...")
            logger.info("[FULL/DataCrazy] Cookie consent resolvido pelo botão primário: %s", _rot[:40])
            return True
    return False


def _selecionar_pais_brasil_oauth(driver):
    """Seleciona 'Brazil'/'Brasil' na combobox de PAÍS do passo 'dados' do OAuth —
    IDIOMA-AGNÓSTICO. A lista é virtualizada e alfabética (clique direto NÃO alcança
    'Brazil'). Abre a combobox, digita 'Bra' no campo de BUSCA (input[role=combobox]
    que surge dentro do dropdown, com a lupa) — filtra p/ Brazil/Brasil/Brésil — e
    clica a opção. Provado AO VIVO em conta INGLÊS (2026-09-23)."""
    _click_texto(driver, ['Selecione um país', 'Selecione um pais', 'Select a country',
                          'Select a country/region', 'Seleccione un país', 'Selecciona un país'],
                 seletor_base='[role="combobox"], div[role="combobox"], button, div, span',
                 timeout=4)
    _delay_curto()
    ok = False
    fim = time.time() + 10
    while time.time() < fim and not ok:
        # digita 'Bra' no campo de busca do dropdown (input[role=combobox] / [type=search])
        try:
            driver.evaluate_page(r"""() => {
                const vis=e=>{const r=e.getBoundingClientRect();return r.width>1&&r.height>1;};
                let inp=[...document.querySelectorAll('input[role="combobox"],input[type="search"]')].filter(vis)[0];
                if(!inp){ inp=[...document.querySelectorAll('[role="dialog"] input[type="text"],[role="listbox"] input')].filter(vis).pop(); }
                if(inp){ const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                    try{inp.focus();}catch(e){} setter.call(inp,'Bra'); inp.dispatchEvent(new Event('input',{bubbles:true})); }
            }""")
        except Exception:
            pass
        _delay_curto()
        # clica a opção Brazil/Brasil/Brésil
        try:
            ok = bool(driver.evaluate_page(r"""() => {
                const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();
                const vis=e=>{const r=e.getBoundingClientRect();return r.width>1&&r.height>1;};
                const o=[...document.querySelectorAll('[role="option"],li[role="option"],li')].filter(vis)
                    .find(e=>{const t=norm(e.innerText); return t==='brazil'||t==='brasil'||t==='brésil'||t==='bresil';});
                if(o){ o.scrollIntoView({block:'center'});
                    try{o.click();}catch(e){ const r=o.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
                        for(const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
                            o.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,clientX:x,clientY:y})); }
                    return true; }
                return false;
            }"""))
        except Exception:
            ok = False
        if not ok:
            # fallback teclado: ArrowDown + Enter (com o filtro em 'Brazil', é a 1ª opção)
            try:
                driver.keyboard.press('ArrowDown'); _delay_curto(); driver.keyboard.press('Enter')
            except Exception:
                pass
            _delay_curto()
        # confirma pelo valor da combobox
        try:
            ok = bool(driver.evaluate_page(r"""() => {
                const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();
                for(const c of document.querySelectorAll('[role="combobox"]')){ const t=norm(c.innerText||c.value||'');
                    if(t==='brazil'||t==='brasil'||t==='brésil'||t==='bresil') return true; }
                return false;
            }"""))
        except Exception:
            pass
    logger.info("[FULL/DataCrazy] País Brasil selecionado (OAuth dados): %s", ok)
    return ok


def _preencher_dados_extra_oauth(driver, site_url, status):
    """Passo 'dados' (Insira os dados da empresa para os novos ativos): o botão
    AVANÇAR só HABILITA quando País + Site (e Fuso horário) estão preenchidos.
    A Meta às vezes deixa esses campos VAZIOS — aí o bot selecionava só a
    categoria, clicava Avançar (desabilitado) e ficava PRESO no loop.

    Este helper preenche os campos QUE ESTIVEREM VAZIOS:
      • País = Brasil
      • Site = domínio verificado da empresa (o mesmo usado na verificação)
      • Fuso horário = (GMT-03:00) America/Sao Paulo
    Cada campo é independente e best-effort (nunca quebra o fluxo)."""
    # ---- PAÍS = Brasil (combobox pesquisável: abre → digita 'Bra' no campo de busca
    #      → escolhe Brazil/Brasil). A lista é virtualizada/alfabética — clique direto
    #      NÃO alcança 'Brazil' (fica lá embaixo). IDIOMA-AGNÓSTICO. ----
    try:
        pais_vazio = bool(driver.evaluate_page(r"""() => {
            const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
            for (const e of document.querySelectorAll('div,span,button,[role="combobox"]')) {
                const r=e.getBoundingClientRect(); if(r.width<1||r.height<1) continue;
                const t = norm(e.innerText);
                if (t==='selecione um país' || t==='selecione um pais'
                    || t==='select a country' || t==='seleccione un país'
                    || t==='seleccione un pais' || t==='selecciona un país'
                    || t==='select a country/region') return true;
            }
            return false;
        }"""))
        if pais_vazio:
            status("🌍 OAuth (dados): País vazio → selecionando Brasil...")
            _selecionar_pais_brasil_oauth(driver)
            _delay_curto()
    except Exception as e:
        logger.warning("[FULL/DataCrazy] dados/país: %s", e)

    # ---- E-MAIL (obrigatório no layout NOVO em inglês; a Meta deixa vazio) ----
    # Best-effort: preenche com contato@<domínio do site> se o campo estiver vazio.
    try:
        _email_biz = ''
        _host = re.sub(r'^https?://', '', (site_url or '')).split('/')[0].strip()
        if _host:
            _email_biz = 'contato@' + _host
        if _email_biz:
            email_vazio = bool(driver.evaluate_page(r"""() => {
                const vis=e=>{const r=e.getBoundingClientRect();return r.width>1&&r.height>1&&!e.disabled;};
                const em=[...document.querySelectorAll('input[type=email]')].filter(vis)[0];
                return !!(em && !(em.value||'').trim());
            }"""))
            if email_vazio:
                status("📧 OAuth (dados): E-mail vazio → preenchendo e-mail comercial...")
                driver.evaluate_page(r"""(v) => {
                    const vis=e=>{const r=e.getBoundingClientRect();return r.width>1&&r.height>1&&!e.disabled;};
                    const em=[...document.querySelectorAll('input[type=email]')].filter(vis)[0];
                    if(em){ const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                        try{em.focus();}catch(e){} setter.call(em,''); em.dispatchEvent(new Event('input',{bubbles:true}));
                        setter.call(em,v); em.dispatchEvent(new Event('input',{bubbles:true}));
                        em.dispatchEvent(new Event('change',{bubbles:true})); em.dispatchEvent(new Event('blur',{bubbles:true})); }
                }""", _email_biz)
                _delay_curto()
    except Exception as e:
        logger.warning("[FULL/DataCrazy] dados/email: %s", e)

    # ---- SITE/Website = domínio verificado (só se vazio). O campo é `input[type=url]`
    #      no layout novo (inglês) — a busca antiga só olhava type=text e PULAVA, deixando
    #      o Website vazio+inválido e o Avançar desabilitado. Agora inclui type=url e
    #      preenche direto (React-safe), com fallback por rótulo. ----
    try:
        if site_url:
            preencheu = bool(driver.evaluate_page(r"""(v) => {
                const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
                const vis = el => { const r=el.getBoundingClientRect();
                    return r.width>1 && r.height>1 && !el.disabled; };
                const ins = [...document.querySelectorAll(
                    'input[type=url],input[type=text],input:not([type]),textarea')].filter(vis);
                const setVal = (el,val) => { const setter=Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype,'value').set;
                    try{el.focus();}catch(e){} setter.call(el,''); el.dispatchEvent(new Event('input',{bubbles:true}));
                    setter.call(el,val); el.dispatchEvent(new Event('input',{bubbles:true}));
                    el.dispatchEvent(new Event('change',{bubbles:true})); el.dispatchEvent(new Event('blur',{bubbles:true})); };
                // 1) o input type=url é o campo Website (layout novo)
                let alvo = ins.find(el => (el.type||'').toLowerCase()==='url' && !(el.value||'').trim());
                // 2) senão, por rótulo/contexto 'site'/'website'
                if (!alvo) {
                    alvo = ins.find(el => {
                        let ctx = norm((el.getAttribute('aria-label')||'')+' '+(el.placeholder||''));
                        let p=el.parentElement,h=0;
                        while(p&&h<3){const tt=(p.innerText||''); if(tt.length<90) ctx+=' '+norm(tt); p=p.parentElement;h++;}
                        return (ctx.indexOf('site')!==-1 || ctx.indexOf('website')!==-1) && !(el.value||'').trim();
                    });
                }
                if (alvo){ setVal(alvo, v); return true; }
                return false;
            }""", site_url))
            if preencheu:
                status("🌐 OAuth (dados): Site vazio → preenchido com o domínio da empresa.")
                _delay_curto()
            else:
                # fallback final por rótulo (caso o input não seja url nem casável acima)
                _preencher_campo_por_rotulo(driver, ['site', 'website'], site_url, timeout=6)
                _delay_curto()
    except Exception as e:
        logger.warning("[FULL/DataCrazy] dados/site: %s", e)

    # ---- FUSO HORÁRIO = America/Sao Paulo (só se o placeholder estiver visível) ----
    try:
        fuso_vazio = bool(driver.evaluate_page(r"""() => {
            const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
            for (const e of document.querySelectorAll('div,span,button,[role="combobox"]')) {
                const r=e.getBoundingClientRect(); if(r.width<1||r.height<1) continue;
                const t = norm(e.innerText);
                if (t==='selecione um fuso horário' || t==='selecione um fuso horario'
                    || t==='selecione o fuso horário' || t==='select a time zone') return true;
            }
            return false;
        }"""))
        if fuso_vazio:
            status("🕒 OAuth (dados): Fuso vazio → America/Sao Paulo...")
            _click_texto(driver, ['Selecione um fuso horário', 'Selecione um fuso horario',
                                  'Select a time zone'],
                         seletor_base='[role="combobox"], div[role="combobox"], button, div, span',
                         timeout=3)
            _delay_curto()
            _click_texto(driver, ['(GMT-03:00) America/Sao Paulo', 'America/Sao Paulo',
                                  'América/São Paulo', 'Sao Paulo', 'São Paulo'],
                         seletor_base='[role="option"], li[role="option"], li, div, span',
                         timeout=6)
            _delay_curto()
    except Exception as e:
        logger.warning("[FULL/DataCrazy] dados/fuso: %s", e)


def _selecionar_portfolio_oauth(driver, business_id, razao='', status=None):
    """Na tela 'Selecione os ativos de negócios', seleciona o PORTFÓLIO da BM NOVA
    pelo business_id (aparece como 'Identificação: <id>' no dropdown). No REPROCESSO
    o perfil tem 2+ BMs e o dropdown vem na ANTIGA por padrão — sem selecionar a
    nova, a conta WhatsApp fica em 'Selecione...' e o Avançar não habilita.
    Retorna True se selecionou. Se business_id vazio, não faz nada (mantém default)."""
    bid = str(business_id or '').strip()
    if not bid:
        return False

    def _s(m):
        if status:
            try:
                status(m)
            except Exception:
                pass

    import json as _json

    def _valor_combo():
        """Texto atual do seletor de Portfólio (p/ confirmar a seleção)."""
        try:
            return str(driver.evaluate_page("""(() => {
                const cb = document.querySelector('[role="combobox"],[aria-haspopup="listbox"]');
                return cb ? (cb.innerText || cb.textContent || '') : '';
            })()""") or '')
        except Exception:
            return ''

    def _clicar_opcao_contendo(texto):
        """Clica, via DOM, a OPÇÃO da lista cujo texto contém `texto` (business_id
        ou razão). Mais confiável que heurística de texto p/ achar 'Identificação: <id>'."""
        js = """(() => {
            const alvo = %s;
            if (!alvo) return false;
            const sel = '[role="option"],[role="menuitemradio"],[role="menuitem"],[role="radio"],li';
            for (const o of document.querySelectorAll(sel)) {
                const t = (o.innerText || o.textContent || '').trim();
                if (t && t.indexOf(alvo) !== -1) {
                    (o.closest('[role="option"],[role="menuitemradio"],[role="menuitem"],li') || o).click();
                    return true;
                }
            }
            return false;
        })()""" % _json.dumps(str(texto))
        try:
            return bool(driver.evaluate_page(js))
        except Exception:
            return False

    # 0) Idempotente: se o combo JÁ mostra o business_id, nada a fazer.
    if bid and bid in _valor_combo():
        _s("✅ OAuth: portfólio da BM nova já selecionado.")
        return True
    # 0b) Idempotente DE VERDADE (2026-10-13): o combo mostra o NOME do portfólio, não o
    # id → o check acima NUNCA casava e cada volta do passo 'ativos' REABRIA e
    # re-selecionava o portfólio — o que ZERA a "Conta do WhatsApp" já escolhida → loop
    # até abortar ("não foi possível enviar para verificação"). Se já selecionamos ESTE
    # business_id nesta popup e o combo não está vazio, não mexe mais.
    _pf_chave = f"{bid}|{id(getattr(driver, '_current_page', None))}"   # por POPUP (página)
    try:
        _v = _valor_combo().strip()
        # Só pula se o combo AINDA mostra o MESMO texto de quando selecionamos (se a Meta
        # trocou p/ "Create a Business portfolio" ao escolher a conta WA, re-seleciona).
        if (getattr(driver, '_gs_pf_bid_ok', '') == _pf_chave and _v
                and _v == getattr(driver, '_gs_pf_txt', '')):
            return True
    except Exception:
        pass

    _s("🏢 OAuth: selecionando o Portfólio da BM nova...")
    # 1) abre o dropdown de "Portfólio empresarial" (1º combobox visível da tela).
    if not _click_seletor(driver, '[role="combobox"], [aria-haspopup="listbox"]', timeout=6):
        _s("⚠️ OAuth: não abri o seletor de portfólio.")
        return False
    _delay_curto()
    # 2) clica a opção que contém o business_id (Identificação: <id>) — DOM primeiro,
    #    depois a heurística de texto como reforço.
    ok = _clicar_opcao_contendo(bid) or _click_texto(
        driver, [bid],
        seletor_base='[role="option"], div[role="option"], li, [role="menuitem"], div, span',
        timeout=6)
    # 3) fallback: pela razão social (nome do portfólio da BM nova).
    if not ok and razao:
        ok = _clicar_opcao_contendo(razao) or _click_texto(
            driver, [razao],
            seletor_base='[role="option"], div[role="option"], li, [role="menuitem"], div, span',
            timeout=5)
    _delay_curto()
    # 4) Sucesso = clicamos a OPÇÃO que contém o business_id. Tenta confirmar pela
    #    leitura do combo; se a leitura não bater, NÃO desiste — o clique na opção do
    #    id é a fonte confiável (o texto do combo é instável). ⚠️ NUNCA usar Escape
    #    aqui: Escape FECHA A POPUP inteira do OAuth (bug 2026-08-14 → fluxo abortava
    #    e caía como "BM não concluída").
    if ok:
        try:
            time.sleep(0.6)                    # combo re-renderiza com o nome escolhido
            driver._gs_pf_bid_ok = _pf_chave   # não re-seleciona nesta popup (zeraria a conta WA)
            driver._gs_pf_txt = _valor_combo().strip()
        except Exception:
            pass
        if bid in _valor_combo():
            _s("✅ OAuth: portfólio da BM nova selecionado (confirmado).")
        else:
            _s("✅ OAuth: portfólio da BM nova selecionado.")
        return True
    # Não achou a opção do id (lista ainda montando). Recolhe o dropdown SEM Escape
    # (reclica o próprio combobox) e sinaliza p/ o chamador tentar na próxima volta.
    _s("⚠️ OAuth: opção do portfólio da BM nova ainda não apareceu — tentando de novo.")
    try:
        _click_seletor(driver, '[role="combobox"], [aria-haspopup="listbox"]', timeout=2)
    except Exception:
        pass
    return False


# Tela 'Selecione os ativos' (layout 2026-10): além do Portfólio há o combo "Conta do
# WhatsApp / WhatsApp account" que vem VAZIO ("Selecione uma conta do WhatsApp") e
# deixa o Avançar DESABILITADO. Abre o combo → lista "Este portfólio" → radio
# "Criar uma conta do WhatsApp / Create a WhatsApp account".
# Marca o combo da conta WhatsApp com data-gs-wa-combo (p/ clique REAL do Playwright).
# Retorna 'ok' (já preenchido), 'vazio' (marcado, precisa abrir) ou '' (não há combo).
_JS_MARCAR_COMBO_WA = r"""(estrito) => {
    const vw = window.innerWidth || document.documentElement.clientWidth;
    const vh = window.innerHeight || document.documentElement.clientHeight;
    const inView = e => { const r = e.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return false;
        const cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
        return cx > 0 && cx < vw && cy > 0 && cy < vh; };
    document.querySelectorAll('[data-gs-wa-combo]').forEach(e => e.removeAttribute('data-gs-wa-combo'));
    const cbs = [...document.querySelectorAll('[role="combobox"],[aria-haspopup="listbox"]')].filter(inView);
    if (!cbs.length) return '';
    const txt = e => ((e.innerText || e.textContent || '') + ' ' + (e.getAttribute('aria-label') || '')
                      + ' ' + (e.getAttribute('placeholder') || '')).toLowerCase();
    // rótulo do campo (label/heading logo acima do combo) — "Conta do WhatsApp"
    const rotulo = e => { let n = e, s = '';
        for (let i = 0; i < 4 && n; i++) { n = n.parentElement; if (n) { s = (n.innerText || '').toLowerCase(); if (s.indexOf('whatsapp') !== -1) return s; } }
        return s; };
    let cb = cbs.find(e => txt(e).indexOf('whatsapp') !== -1)
          || cbs.find(e => rotulo(e).indexOf('whatsapp') !== -1 && txt(e).indexOf('whatsapp') !== -1);
    // ordem fixa da tela de ativos: Portfólio, Conta do WhatsApp. Em tela NÃO identificada
    // (estrito) não chuta: lá pode haver combos de categoria/país.
    if (!cb && !estrito && cbs.length >= 2) cb = cbs[1];
    if (!cb) return '';
    const t = txt(cb);
    // VAZIO = placeholder "Selecione…/Select…" (vários idiomas) OU o Avançar desabilitado.
    const ph = ['selecione','selecionar','select','seleccion','chọn','выбер','pilih','चुन','sélection',
                'auswählen','seleziona','seç','wybierz','เลือก','اختر','选择','選擇','選択','선택'];
    // VAZIO = só o PLACEHOLDER ("Selecione…/Select…" em vários idiomas). (2026-10-13) Saiu
    // a regra "há botão desabilitado no diálogo": a Meta DUPLICA botões ocultos
    // (aria-hidden, sempre aria-disabled) → toda leitura dava 'vazio' mesmo com a conta
    // escolhida, o bot reabria o combo e girava até abortar.
    // Só o texto VISÍVEL (ou o valor do input) — o aria-label pode seguir "Select a
    // WhatsApp account" mesmo DEPOIS da escolha.
    const inp = cb.querySelector('input');
    const visivel = ((cb.innerText || '').trim() || (inp && inp.value) || (inp && inp.placeholder) || '').toLowerCase();
    const ph2 = ph.concat(['escolh','choose','elige','elegir','wähle','choisir','scegli']);
    const vazio = !visivel || ph2.some(p => visivel.indexOf(p) !== -1);
    cb.setAttribute('data-gs-wa-combo', '1');
    if (!vazio) return 'ok';
    return 'vazio';
}"""

# Texto atual do combo da conta WhatsApp (marcado por _JS_MARCAR_COMBO_WA).
_JS_TEXTO_COMBO_WA = r"""() => {
    const cb = document.querySelector('[data-gs-wa-combo="1"]');
    if (!cb) return null;
    const inp = cb.querySelector('input');
    return ((cb.innerText || '').trim() || (inp && inp.value) || '').trim().toLowerCase();
}"""

# Marca a opção "Criar uma conta do WhatsApp" na lista aberta (data-gs-wa-opt). Idioma-
# agnóstico: verbo "criar" em vários idiomas; senão o ÚLTIMO radio da lista (a Meta põe
# o "Criar…" no fim da seção "Este portfólio"). Nunca a caixa de busca.
_JS_MARCAR_OPCAO_CRIAR_WA = r"""() => {
    const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
    document.querySelectorAll('[data-gs-wa-opt]').forEach(e => e.removeAttribute('data-gs-wa-opt'));
    const sel = '[role="option"],[role="menuitemradio"],[role="radio"],[role="menuitem"],li,label';
    // LISTA DESTE COMBO (2026-10-13): 1º a que o combo controla (aria-controls/owns); senão
    // a ÚLTIMA lista/menu VISÍVEL (a que acabou de abrir). Antes pegava a 1ª [role=listbox]
    // do DOM (podia ser a do PORTFÓLIO, oculta) e caía no documento inteiro.
    const cb = document.querySelector('[data-gs-wa-combo="1"]');
    let box = null;
    if (cb) {
        for (const a of ['aria-controls', 'aria-owns']) {
            const id = cb.getAttribute(a) || (cb.querySelector('[' + a + ']') || {getAttribute: () => ''}).getAttribute(a);
            const el = id ? document.getElementById(id) : null;
            if (el && vis(el)) { box = el; break; }
        }
    }
    if (!box) {
        const ls = [...document.querySelectorAll('[role="listbox"],[role="menu"]')]
            .filter(e => vis(e) && e.getAttribute('aria-hidden') !== 'true');
        box = ls.length ? ls[ls.length - 1] : null;
    }
    const raiz = box || document;
    // Linhas com RADIO sem role de opção (div/[role=button] + <input type=radio>), como as
    // da Central: sobe do radio até o 1º ancestral com texto curto (o rótulo da linha).
    const linhasRadio = [...raiz.querySelectorAll('input[type="radio"],[role="radio"]')].map(r => {
        let n = r;
        for (let i = 0; i < 6 && n; i++) {
            const t = (n.innerText || '').trim();
            if (t && t.length < 90) return n;
            n = n.parentElement;
        }
        return null;
    }).filter(Boolean);
    const ops = [...new Set([...raiz.querySelectorAll(sel)].concat(linhasRadio))].filter(vis)
        .filter(o => !cb || !cb.contains(o))
        .filter(o => { const t = (o.innerText || '').trim(); return t && t.length < 90 && !o.querySelector('input[type="text"],input[type="search"]'); });
    const verbos = ['criar','create','crear','tạo','созда','buat','बनाएँ','बनाएं','बनाए','créer','erstellen',
                    'crea ','oluştur','utwórz','створ','gumawa','สร้าง','إنشاء','创建','建立','作成','만들기'];
    let alvo = ops.find(o => { const t = o.innerText.toLowerCase();
        return t.indexOf('whatsapp') !== -1 && verbos.some(v => t.indexOf(v) !== -1); })
        || ops.find(o => verbos.some(v => o.innerText.toLowerCase().indexOf(v) !== -1));
    const selecionaveis = ops.filter(o => o.matches('[role="radio"],[role="menuitemradio"],[role="option"]')
                                      || o.querySelector('input[type="radio"],[role="radio"]'))
        // sem duplicata pai/filho da MESMA linha (fica o mais interno)
        .filter((o, _, arr) => !arr.some(x => x !== o && o.contains(x)));
    // BM NOVA não tem conta WhatsApp: a lista só tem o "Criar…" → opção ÚNICA = ela.
    if (!alvo && box && selecionaveis.length === 1) alvo = selecionaveis[0];
    if (!alvo) alvo = selecionaveis[selecionaveis.length - 1];
    if (!alvo) return '';
    const linha = alvo.closest('[role="option"],[role="menuitemradio"],[role="menuitem"],li,[role="button"],label');
    if (linha && (!box || box.contains(linha)) && (linha.innerText || '').trim().length < 90) alvo = linha;
    alvo.setAttribute('data-gs-wa-opt', '1');
    try { alvo.scrollIntoView({block: 'nearest'}); } catch (e) {}
    const r = alvo.getBoundingClientRect();
    return JSON.stringify({rot: (alvo.innerText || '').trim().slice(0, 80),
                           x: r.left + r.width / 2, y: r.top + r.height / 2});
}"""

# Fallback de clique na opção marcada (JS dispatch completo, 1 clique).
_JS_CLICAR_OPCAO_WA = r"""() => {
    const o = document.querySelector('[data-gs-wa-opt="1"]');
    if (!o) return false;
    const r = o.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    for (const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
        o.dispatchEvent(new MouseEvent(ev, {bubbles: true, cancelable: true, view: window, clientX: x, clientY: y}));
    return true;
}"""


def _selecionar_conta_whatsapp_oauth(driver, status=None, estrito=False):
    """Garante a "Conta do WhatsApp" na tela de ativos: se o combo está vazio, abre e
    escolhe "Criar uma conta do WhatsApp". Retorna True se o combo ficou preenchido (ou
    não existe nesta variação da tela). Best-effort, nunca levanta, NUNCA Escape (fecha
    a popup do OAuth) — recolhe a lista reclicando o combo. `estrito`: só age em combo
    que cite "WhatsApp" (p/ tela não identificada)."""
    def _s(m):
        if status:
            try:
                status(m)
            except Exception:
                pass
    import json as _json

    def _estado():
        try:
            return driver.evaluate_page(_JS_MARCAR_COMBO_WA, bool(estrito)) or ''
        except Exception:
            return ''

    def _txt_combo():
        try:
            return driver.evaluate_page(_JS_TEXTO_COMBO_WA)
        except Exception:
            return None

    def _lista_aberta():
        try:
            return bool(driver.evaluate_page(r"""() => {
                const cb = document.querySelector('[data-gs-wa-combo="1"]');
                if (cb && cb.getAttribute('aria-expanded') === 'true') return true;
                return [...document.querySelectorAll('[role="listbox"],[role="menu"]')].some(e => {
                    const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 &&
                        e.getAttribute('aria-hidden') !== 'true'; });
            }"""))
        except Exception:
            return False

    def _confirmou(txt_antes):
        """Selecionou = o combo saiu do placeholder (texto mudou e não é mais 'vazio')."""
        fim_c = time.time() + 4
        while time.time() < fim_c:
            if _estado() == 'ok':
                t = _txt_combo()
                if t is None or t != txt_antes:
                    return True
            time.sleep(0.3)
        return False

    if _estado() != 'vazio':
        return True
    txt_antes = _txt_combo()
    _s("📱 OAuth: Conta do WhatsApp → 'Criar uma conta do WhatsApp'...")
    # 1) abre o combo (1 clique real) e espera a LISTA dele aparecer.
    try:
        _ja_aberto = bool(driver.evaluate_page(
            "() => { const c = document.querySelector('[data-gs-wa-combo=\"1\"]');"
            " return !!c && c.getAttribute('aria-expanded') === 'true'; }"))
    except Exception:
        _ja_aberto = False
    if not _ja_aberto:
        if not _click_seletor(driver, '[data-gs-wa-combo="1"]', timeout=5):
            return False
    info = None
    fim = time.time() + 6
    while time.time() < fim and not info:
        try:
            raw = driver.evaluate_page(_JS_MARCAR_OPCAO_CRIAR_WA) or ''
            info = _json.loads(raw) if raw else None
        except Exception:
            info = None
        if not info:
            time.sleep(0.4)
    if not info:
        logger.warning("[FULL/DataCrazy] OAuth: opção 'Criar conta do WhatsApp' não encontrada.")
        if _lista_aberta():
            try:
                _click_seletor(driver, '[data-gs-wa-combo="1"]', timeout=2)  # recolhe SEM Escape
            except Exception:
                pass
        return False
    rot = info.get('rot', '')
    # 2) UM clique REAL (mouse) na opção; confere pelo combo.
    try:
        x, y = float(info['x']), float(info['y'])
        driver.mouse.move(x, y, steps=random.randint(5, 10))
        time.sleep(random.uniform(0.08, 0.2))
        driver.mouse.click(x, y)
    except Exception:
        _click_seletor(driver, '[data-gs-wa-opt="1"]', timeout=3)
    ok = _confirmou(txt_antes)
    # 3) Não pegou e a lista segue aberta → 1 clique JS de fallback (sem repetir o real).
    if not ok and _lista_aberta():
        try:
            driver.evaluate_page(_JS_CLICAR_OPCAO_WA)
        except Exception:
            pass
        ok = _confirmou(txt_antes)
    if ok:
        logger.info("[FULL/DataCrazy] OAuth: Conta do WhatsApp → '%s' (confirmado no combo).", rot)
        _s("✅ OAuth: Conta do WhatsApp selecionada (criar nova).")
        return True
    logger.warning("[FULL/DataCrazy] OAuth: cliquei '%s' mas o combo não confirmou.", rot)
    if _lista_aberta():
        try:
            _click_seletor(driver, '[data-gs-wa-combo="1"]', timeout=2)  # recolhe SEM Escape
        except Exception:
            pass
    return False


# Tela de LOGIN/REAUTH do Facebook DENTRO da aba do OAuth (login.php?skip_api_login=1&
# api_key=...&next=<dialog/oauth>). O session_guard PULA de propósito URLs de OAuth (não
# pode navegar p/ fora do wizard), então quem resolve é o próprio fluxo — no lugar, sem
# sair da aba. Detecção ESTRUTURAL (campo de senha visível num host facebook.com),
# idioma-agnóstica: 'login' = e-mail+senha; 'senha' = só senha (reauth).
_JS_LOGIN_NO_OAUTH = r"""() => {
    const vis = e => { if (!e) return false; const r = e.getBoundingClientRect();
        const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
    const host = (location.hostname || '').toLowerCase();
    if (host.indexOf('facebook.com') === -1) return '';
    const pw = [...document.querySelectorAll('input[name="pass"],input[type="password"]')].filter(vis)[0];
    if (!pw) return '';
    const em = [...document.querySelectorAll('#email,input[name="email"]')].filter(vis)[0];
    return em ? 'login' : 'senha';
}"""


def _login_no_popup_oauth(driver, senha_fb='', status=None):
    """Se a aba do OAuth caiu no LOGIN/REAUTH do Facebook, preenche as credenciais do
    driver NO LUGAR (sem navegar) e envia; trata o 2FA (TOTP) se a Meta pedir.
    Retorna True se agiu (o chamador re-detecta a tela), False se não era login ou se
    faltam credenciais. Best-effort — nunca levanta."""
    try:
        modo = driver.evaluate_page(_JS_LOGIN_NO_OAUTH) or ''
    except Exception:
        modo = ''
    if not modo:
        return False
    login = (getattr(driver, '_fb_login', '') or getattr(driver, '_pm_fb_login', '') or '')
    senha = (senha_fb or getattr(driver, '_fb_senha', '') or getattr(driver, '_pm_fb_senha', '') or '')
    tfa = (getattr(driver, '_fb_tfa', '') or getattr(driver, '_pm_fb_tfa', '') or '')
    if not senha or (modo == 'login' and not login):
        logger.warning("[FULL/DataCrazy] OAuth caiu no login do FB (%s) mas o driver não tem "
                       "credenciais — não dá p/ relogar no lugar.", modo)
        return False
    if status:
        try:
            status("🔑 OAuth: Facebook pediu login dentro do formulário — relogando no lugar...")
        except Exception:
            pass
    u_antes = _url_atual(driver)
    try:
        if modo == 'login':
            _preencher(driver, '#email, input[name="email"]', login, timeout=6)
            _delay_curto()
        _preencher(driver, 'input[name="pass"], input[type="password"]', senha, timeout=6)
        _delay_curto()
        # Botão de envio por ATRIBUTO (idioma-agnóstico); fallback = Enter no campo de
        # senha (submete o form). NUNCA Escape (fecharia a popup do OAuth).
        if not _click_seletor(driver, 'button[name="login"], #loginbutton, '
                                      'input[data-testid="sec_ac_button"]', timeout=4):
            try:
                driver.keyboard.press('Enter')
            except Exception:
                pass
    except Exception as e:
        logger.warning("[FULL/DataCrazy] login no OAuth falhou: %s", e)
        return True
    # Espera sair do formulário (URL muda ou o campo de senha some).
    fim = time.time() + 25
    while time.time() < fim:
        time.sleep(0.8)
        try:
            ainda = driver.evaluate_page(_JS_LOGIN_NO_OAUTH) or ''
        except Exception:
            ainda = ''
        u = _url_atual(driver)
        if not ainda or (u and u != u_antes):
            break
    # 2FA (two_step/two_factor): reaproveita o tratador MADURO do login (TOTP com
    # horário de rede, guarda contra digitar no campo errado). Opera na aba atual.
    u = _url_atual(driver)
    if tfa and ('two_step' in u or 'two_factor' in u or 'approvals_code' in u):
        try:
            from server.automacao_facebook import _tratar_2fa
            _tratar_2fa(driver, tfa, status)
        except Exception as e:
            logger.warning("[FULL/DataCrazy] 2FA no OAuth falhou: %s", e)
    return True


def _preencher_tela_desconhecida_oauth(driver, business_id, razao, site_url, status,
                                       tentar_portfolio=True):
    """Tela do OAuth NÃO reconhecida (ex.: conta em idioma sem marcadores): antes do
    avanço genérico, aplica SÓ ações ESTRUTURAIS e IDEMPOTENTES que o fluxo PT/EN faz nas
    telas equivalentes — senão o Avançar segue desabilitado e o plano B não tem o que
    clicar (2026-10-12):
      • número virtual: só se a tela OFERECE a opção (radio/option de número virtual);
      • portfólio da BM nova: pelo business_id (número — não depende de idioma);
      • Website/E-mail VAZIOS: input[type=url] / input[type=email] (atributo).
    Best-effort; nunca levanta."""
    try:
        # Só mexe no número se a OPÇÃO VIRTUAL está de fato NA TELA (radio com value
        # 'virtual*' ou rótulo curto com "número virtual" em algum idioma, dentro do
        # viewport). NÃO basta o `_tem_opcao_numero_virtual` (ele também aceita o
        # placeholder 'create a new...', que existe em outras telas e faria o seletor
        # digitar 'virtual' no 1º input de texto).
        opcao_virtual_na_tela = bool(driver.evaluate_page(r"""() => {
            const vw = window.innerWidth || document.documentElement.clientWidth;
            const vh = window.innerHeight || document.documentElement.clientHeight;
            const inView = e => { const r = e.getBoundingClientRect();
                if (r.width < 1 || r.height < 1) return false;
                const cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
                return cx > 0 && cx < vw && cy > 0 && cy < vh; };
            for (const r of document.querySelectorAll('input[type="radio"],[role="radio"]')) {
                const v = ((r.value || '') + ' ' + ((r.getAttribute && r.getAttribute('value')) || '')).toLowerCase();
                const alvo = r.closest('label,[role="radio"]') || r.parentElement || r;
                if (v.indexOf('virtual') !== -1 && inView(alvo)) return true;
            }
            const V = ['virtual number', 'número virtual', 'numero virtual', 'nomor virtual', 'số ảo',
                       'виртуальн', 'віртуальн', 'वर्चुअल', 'numéro virtuel', 'virtuelle nummer',
                       'sanal numara', '虚拟号码', '虛擬號碼', '仮想番号', '가상 번호', 'หมายเลขเสมือน'];
            for (const e of document.querySelectorAll('label,[role="radio"],[role="option"],span,div')) {
                const t = (e.innerText || '').toLowerCase();
                if (!t || t.length > 160) continue;
                if (V.some(x => t.indexOf(x) !== -1) && inView(e)) return true;
            }
            return false;
        }"""))
        if opcao_virtual_na_tela:
            _selecionar_nome_exibicao(driver, timeout=4)
    except Exception:
        pass
    if tentar_portfolio and business_id:
        try:
            tem_combo = bool(driver.evaluate_page(r"""() => {
                const vis = e => { const r = e.getBoundingClientRect();
                    return r.width > 1 && r.height > 1; };
                const dlg = document.querySelector('[role="dialog"]') || document;
                return [...dlg.querySelectorAll('[role="combobox"],[aria-haspopup="listbox"]')]
                    .filter(vis).length > 0;
            }"""))
            if tem_combo:
                _selecionar_portfolio_oauth(driver, business_id, razao, status)
        except Exception:
            pass
    # Combo "Conta do WhatsApp" vazio (tela de ativos num idioma sem marcadores).
    _selecionar_conta_whatsapp_oauth(driver, status, estrito=True)
    try:
        _host = re.sub(r'^https?://', '', (site_url or '')).split('/')[0].strip()
        driver.evaluate_page(r"""(a) => {
            const vis = e => { const r = e.getBoundingClientRect();
                return r.width > 1 && r.height > 1 && !e.disabled && !e.readOnly; };
            const setVal = (el, v) => { const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                try { el.focus(); } catch (e) {}
                setter.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.dispatchEvent(new Event('blur', {bubbles: true})); };
            const dlg = document.querySelector('[role="dialog"]') || document;
            if (a.site) { const u = [...dlg.querySelectorAll('input[type=url]')]
                    .filter(e => vis(e) && !(e.value || '').trim())[0]; if (u) setVal(u, a.site); }
            if (a.email) { const m = [...dlg.querySelectorAll('input[type=email]')]
                    .filter(e => vis(e) && !(e.value || '').trim())[0]; if (m) setVal(m, a.email); }
        }""", {'site': site_url or '', 'email': ('contato@' + _host) if _host else ''})
    except Exception:
        pass


def _rodar_fluxo_oauth(driver, razao, status, popup_page=None, timeout_total=420,
                       site_url='', business_id='', senha_fb=''):
    """Conduz o fluxo OAuth do embedded signup como uma MÁQUINA DE ESTADOS.

    A cada volta: detecta a tela atual, executa a ação daquela tela e só prossegue
    quando a tela MUDA de fato. Se a tela não mudar (ex.: categoria não selecionada
    e Avançar desabilitado), repete a ação no próximo ciclo — nunca 'pula' etapa.
    Retorna True quando a conta é conectada (ou a popup fecha), False se travar."""
    fim = time.time() + timeout_total
    ultimo = None
    repeticoes = 0
    _none_streak = 0   # telas do OAuth não identificadas seguidas (p/ capturar snapshot)
    _cat_dump_feito = False  # dump diagnóstico da categoria só 1x por run
    _pf_falhas = 0     # falhas seguidas ao selecionar o portfólio da BM nova (aborta em vez de criar na BM errada)
    _wa_falhas = 0     # falhas seguidas ao escolher "Criar uma conta do WhatsApp" na tela de ativos
    _pf_trocas = 0     # vezes que o portfólio mudou sozinho ao escolher a conta WA (re-seleção)
    try:
        driver._gs_pf_bid_ok = ''   # nova execução do OAuth: esquece a seleção anterior
        driver._gs_pf_txt = ''
    except Exception:
        pass
    _login_tent = 0    # relogins NO LUGAR dentro da aba do OAuth (teto anti-loop)
    _cookie_n = 0      # vezes que o diálogo de cookies foi "resolvido" (teto anti-loop)
    _pf_desc = 0       # tentativas de portfólio em tela NÃO reconhecida (teto: cada uma custa ~15s)
    while time.time() < fim:
        # Popup fechou sozinha após conectar = OAuth concluído.
        if popup_page is not None:
            try:
                if popup_page.is_closed():
                    logger.info("[FULL/DataCrazy] Popup OAuth fechada — fluxo concluído.")
                    return True
            except Exception:
                # FIX falso-sucesso (auditoria 24/7): ler is_closed() que LEVANTA = popup
                # detached/quebrada, NÃO prova de conexão. Antes retornava True (WABA fantasma).
                # Largamos a ref e deixamos a máquina de estados decidir pelo conteúdo do driver.
                logger.warning("[FULL/DataCrazy] is_closed() da popup falhou — seguindo pelo "
                               "conteúdo do driver (sem declarar sucesso).")
                popup_page = None

        # Espera a tela carregar 100% e ficar ESTÁTICA antes de detectar/agir
        # (em vez de delay fixo) — evita detectar uma tela ainda renderizando ou
        # "pular" a tela final por ela ter carregado rápido demais.
        _esperar_estavel_oauth(driver, popup_page, timeout=18, settle=0.6)

        # Popup abriu com "Sorry, something went wrong" (não carregou 100% — conexão
        # instável na abertura). Sinaliza ao chamador p/ FECHAR e REABRIR (retry).
        if _pagina_sorry_oauth(driver):
            logger.warning("[FULL/DataCrazy] OAuth abriu com 'Sorry' — sinalizando retry ao chamador.")
            return 'sorry'

        # LOGIN/REAUTH do Facebook DENTRO da aba do OAuth (sessão caiu no meio): o
        # session_guard não mexe em URL de OAuth, então relogamos NO LUGAR (estrutural,
        # qualquer idioma). Teto de 2 p/ não martelar senha errada. (2026-10-12)
        if _login_tent < 2 and _login_no_popup_oauth(driver, senha_fb, status):
            _login_tent += 1
            _none_streak = 0
            _esperar_estavel_oauth(driver, popup_page, timeout=15, settle=0.6)
            continue

        # Cookie/consentimento DENTRO do popup do OAuth (user_cookie_choice_v2) —
        # NÃO é passo do signup; se não resolver, o OAuth trava e dá timeout.
        # Teto anti-loop (2026-10-12): este `continue` não passava por nenhum guard — se o
        # diálogo reaparecesse/o clique não pegasse, girava até o timeout total (7 min).
        if _cookie_n < 6 and _resolver_cookie_consent_oauth(driver, status):
            _cookie_n += 1
            _none_streak = 0
            _esperar_estavel_oauth(driver, popup_page, timeout=12, settle=0.6)
            continue

        # Restrição de BM/conta WhatsApp em QUALQUER tela: aborta a etapa e
        # sinaliza ao backend (que trata como bloqueio -> retry com 2ª BM / erro).
        if _detectar_restricao_bm(driver):
            logger.warning("[FULL/DataCrazy] BM/conta WhatsApp RESTRITA detectada — abortando etapa.")
            status("🚫 OAuth: conta/BM restrita — abortando esta BM.")
            return 'restrita'

        # ✅ SUCESSO TERMINAL: após 'Concluir', a popup do OAuth fecha ou navega p/
        # dialog/close_window?...&connect=1 (a WABA já foi criada). Essa página NÃO é um
        # passo do wizard — sem isto o fluxo ficava girando em "tela não reconhecida" e
        # ABORTAVA com False MESMO tendo criado a WABA (falso-negativo). (2026-09-23)
        if _oauth_signup_concluido(driver, popup_page):
            status("✅ OAuth: embedded signup concluído (WABA criada; popup fechando).")
            return True

        passo = _detectar_passo_oauth(driver)
        if passo is None:
            # Tela do OAuth não reconhecida (após estabilizar). Captura snapshot
            # após algumas leituras seguidas (evita transições) p/ criar o handler.
            _none_streak += 1
            # ROBUSTEZ: se a tela ficar irreconhecível por MUITAS voltas seguidas,
            # ABORTA (libera o navegador) em vez de girar até o timeout de 5 min —
            # cada volta custa ~18s de espera. (2026-08-14)
            if _none_streak >= 12:
                logger.warning("[FULL/DataCrazy] OAuth preso em tela não reconhecida "
                               "(%sx) — abortando p/ não segurar o navegador.", _none_streak)
                return False
            if _none_streak == 4:
                try:
                    from server.screen_capture import capturar_tela_desconhecida
                    capturar_tela_desconhecida(driver, contexto='oauth_datacrazy',
                                               motivo='passo_oauth_nao_identificado')
                except Exception:
                    pass
            # PLANO B (2026-08-20): tela não reconhecida NÃO é motivo p/ desistir —
            # a Meta troca o wizard direto. Tenta SEGUIR EM FRENTE pelo botão de
            # avanço (Avançar/Confirmar/Concluir…), nunca por Cancelar/Voltar.
            if _none_streak >= 2:
                # Antes do avanço genérico: ações ESTRUTURAIS idempotentes (número
                # virtual / portfólio por business_id / Website+E-mail vazios) — numa
                # conta em idioma sem marcadores o Avançar só habilita com elas.
                _preencher_tela_desconhecida_oauth(
                    driver, business_id, razao, site_url, status,
                    tentar_portfolio=(_pf_desc < 3))
                if business_id:
                    _pf_desc += 1
                _rot = _avancar_tela_desconhecida(driver)
                if _rot:
                    logger.info("[FULL/DataCrazy] Tela desconhecida — avanço genérico "
                                "clicou '%s'.", _rot[:30])
                    status(f"🧭 OAuth: tela nova não mapeada → seguindo por '{_rot[:24]}'...")
                    _delay_curto()
            continue
        _none_streak = 0

        if passo == ultimo:
            repeticoes += 1
        else:
            repeticoes = 0
            ultimo = passo
        if repeticoes > 6:
            logger.warning("[FULL/DataCrazy] Preso no passo OAuth '%s' (%sx) — abortando fluxo.",
                           passo, repeticoes)
            return False

        if passo == 'continuar_como':
            # Tela de consentimento "Continuar como <nome>?" (clica o botão AZUL
            # 'Continuar como ...', nunca 'Cancelar' nem 'Entrar em outra conta').
            status("👤 OAuth: Continuar como (consentimento)...")
            _click_texto(driver, ['Continuar como', 'Continue as'],
                         seletor_base='[role="button"], div[role="button"], button, span, div',
                         timeout=12)

        elif passo == 'conecte':
            # Tela "Conecte sua conta a Datacrazy" (permissões). O botão pode ser
            # "Começar" (DataCrazy) OU "Continuar"/"Continue" — tenta todos.
            status("🔗 OAuth: Conectar conta → Começar/Continuar...")
            _click_texto(driver, ['Começar', 'Comece', 'Get started', 'Get Started',
                                  'Continuar', 'Continue', 'Avançar', 'Next'],
                         seletor_base='[role="button"], div[role="button"], button, span, div',
                         timeout=12)

        elif passo == 'ativos':
            status("🏢 OAuth: Selecionar ativos (portfólio da BM nova) → Avançar...")
            # Seleciona o PORTFÓLIO da BM nova (reprocesso tem 2+ BMs; o default vem
            # na antiga → conta WhatsApp fica 'Selecione...' e o Avançar não habilita).
            _pf_ok = _selecionar_portfolio_oauth(driver, business_id, razao, status)
            if business_id and not _pf_ok and _pf_falhas < 3:
                # Lista do dropdown ainda montando: espera e tenta de novo (SEM abortar
                # e SEM fechar a popup). Após poucas voltas, PROSSEGUE mesmo assim — se
                # o Avançar não habilitar por falta do portfólio, o guard de 'repeticoes'
                # trata o travamento honestamente, sem matar o fluxo. (fix 2026-08-14:
                # o abort fatal + Escape estava fechando a popup e finalizando cedo.)
                _pf_falhas += 1
                _delay_medio()
                continue
            _pf_falhas = 0
            _delay_curto()
            # Layout 2026-10: combo "Conta do WhatsApp" vazio trava o Avançar → escolhe
            # "Criar uma conta do WhatsApp". Retenta poucas voltas; depois prossegue.
            if not _selecionar_conta_whatsapp_oauth(driver, status) and _wa_falhas < 3:
                _wa_falhas += 1
                _delay_medio()
                continue
            _wa_falhas = 0
            # 🛡️ A escolha da conta WA NÃO pode ter trocado o PORTFÓLIO (print do dono
            # 2026-10-13: combo virou "Create a Business portfolio" → a WABA nasceria num
            # portfólio NOVO, fora da BM em verificação). Mudou → re-seleciona e refaz a
            # conta WA na próxima volta, sem clicar Next.
            if business_id and getattr(driver, '_gs_pf_txt', ''):
                try:
                    _pf_agora = str(driver.evaluate_page(
                        "() => { const c = document.querySelector('[role=\"combobox\"],[aria-haspopup=\"listbox\"]');"
                        " return c ? (c.innerText || c.textContent || '').trim() : ''; }") or '')
                except Exception:
                    _pf_agora = driver._gs_pf_txt
                if _pf_agora and _pf_agora != driver._gs_pf_txt and _pf_trocas < 3:
                    _pf_trocas += 1
                    status("⚠️ OAuth: o portfólio mudou ao escolher a conta WhatsApp — "
                           "re-selecionando o portfólio da BM...")
                    _delay_curto()
                    continue
            # Espera a Meta HABILITAR o Avançar (valida a escolha) antes do clique único.
            _aguardar_avancar_oauth_habilitado(driver, timeout=8)
            _delay_curto()
            if _click_oauth_avancar(driver):
                _aguardar_saida_passo(driver, 'ativos', timeout=14)

        elif passo == 'dados':
            # Nome do negócio = RAZÃO SOCIAL (FB pré-preenche com o titular da conta).
            _preencher_nome_negocio(driver, _nome_exibicao_waba(razao))
            _delay_curto()
            status("🗂️ OAuth: Selecionando categoria 'Outro'...")
            _cat_ok = _selecionar_categoria_outro(driver, timeout=25)
            # CRÍTICO: preencher País/Site/Fuso VAZIOS — senão o Avançar fica
            # DESABILITADO e o fluxo trava neste passo (loop → aborta). A Meta
            # às vezes deixa esses campos em branco mesmo com a categoria OK.
            _preencher_dados_extra_oauth(driver, site_url, status)
            if _cat_ok:
                _delay_curto()
                _click_oauth_avancar(driver)
            else:
                # Não conseguiu a categoria: NÃO clica Avançar (ficaria preso/pularia
                # a etapa). Repete a seleção no próximo ciclo. Dump diagnóstico 1x.
                if not _cat_dump_feito:
                    _dump_diagnostico_categoria(driver)
                    _cat_dump_feito = True
                logger.warning("[FULL/DataCrazy] Categoria 'Outro' ainda não confirmada — repetindo.")
                _delay_medio()
                continue

        elif passo == 'config':
            # NOVO LAYOUT: "Selecione sua configuração" — escolhe iniciar com um
            # NOVO número (a opção que leva ao 'Usar somente um nome de exibição'
            # adiante, igual ao fluxo antigo).
            status("⚙️ OAuth: Config → 'Inserir novo número'...")
            if not _selecionar_opcao_novo_numero(driver):
                # fallback: 1º radio do diálogo
                _click_seletor(driver,
                               '[role="dialog"] input[type="radio"], [role="radio"]', timeout=5)
            _delay_curto()
            _click_oauth_avancar(driver)

        elif passo == 'preencha_dados':
            # LAYOUT 2: "Preencha os dados da empresa" — Portfólio empresarial,
            # Nome, Site e País (Brasil) já vêm PRÉ-PREENCHIDOS. O Nome pode vir com
            # o titular da conta (ex.: 'Andre Costa') → sobrescreve com a RAZÃO SOCIAL.
            # ⭐ FIX (2026-07-25): quando o perfil tem 2+ BMs (RETRY da 2ª BM após a 1ª
            #    ser bloqueada), o "Portfólio empresarial" vem PRÉ-SELECIONADO na 1ª BM
            #    (a bloqueada). Sem trocar p/ a BM certa (business_id), a WABA nasceria
            #    na BM errada/bloqueada → o fluxo não continua e conta como erro/falha,
            #    mesmo a 2ª BM estando SEM restrição. Força a seleção do portfólio da BM
            #    correta ANTES de preencher o nome. (Provado por print: dropdown mostra
            #    'Identificação: <business_id>'.) No caso de 1 BM só, seleciona a mesma
            #    que já vem por padrão (idempotente).
            status("🏢 OAuth: Dados da empresa → garantindo portfólio da BM certa...")
            _pf_ok = _selecionar_portfolio_oauth(driver, business_id, razao, status)
            if business_id and not _pf_ok and _pf_falhas < 3:
                # Mesma lógica do passo 'ativos': espera a lista montar e tenta de novo,
                # SEM abortar/fechar a popup; depois prossegue best-effort.
                _pf_falhas += 1
                _delay_medio()
                continue
            _pf_falhas = 0
            _delay_curto()
            _preencher_nome_negocio(driver, _nome_exibicao_waba(razao))
            _delay_curto()
            _click_oauth_avancar(driver)

        elif passo == 'criar_conta':
            # NOVO LAYOUT: "Crie ou selecione sua conta do WhatsApp Business".
            # Os dropdowns já vêm como "Criar uma conta..." / "Criar um novo
            # perfil...", que é exatamente o que queremos — só avança.
            status("🗂️ OAuth: Conta WABA (padrão) → Avançar...")
            _delay_curto()
            _click_oauth_avancar(driver)

        elif passo == 'criar_perfil':
            # NOVO LAYOUT: "Crie um perfil do WhatsApp Business" — preenche o nome
            # da conta + nome de exibição (razão social) e a categoria 'Outro'.
            status("🏷️ OAuth: Criando perfil WABA (nome + categoria)...")
            _nome_conta = _nome_exibicao_waba(razao)
            # Preenche Nome da conta + Nome de exibição (React-safe, com verificação).
            if not _preencher_nomes_perfil_waba(driver, _nome_conta):
                # fallback pelo rótulo (layouts antigos)
                _preencher_campo_por_rotulo(
                    driver, ['nome da conta do whatsapp business', 'nome da conta',
                             'whatsapp business account name', 'account name'],
                    _nome_conta, timeout=8)
                _preencher_campo_por_rotulo(
                    driver, ['nome de exibição do whatsapp business', 'nome de exibição',
                             'nome de exibicao', 'display name'],
                    _nome_conta, timeout=6)
            _delay_curto()
            # Confirma/dispensa a SUGESTÃO do nome de exibição (senão o dropdown
            # cobre o seletor de categoria e o Avançar não ativa).
            _confirmar_sugestao_nome_exibicao(driver)
            _delay_curto()
            _cat_ok = _selecionar_categoria_outro(driver, timeout=20)
            # Garante o Nome da conta (pode ter ficado vazio) ANTES de avançar.
            _preencher_nomes_perfil_waba(driver, _nome_conta)
            if _cat_ok:
                _delay_curto()
                _click_oauth_avancar(driver)
            else:
                if not _cat_dump_feito:
                    _dump_diagnostico_categoria(driver)
                    _cat_dump_feito = True
                logger.warning("[FULL/DataCrazy] Categoria (criar_perfil) ainda não "
                               "confirmada — repetindo.")
                _delay_medio()
                continue

        elif passo == 'numero':
            # A tela de número tem DOIS destinos e precisamos decidir RÁPIDO:
            #  (a) NOVO fluxo — ao escolher "usar um nome de exibição" a popup AVANÇA
            #      p/ Verif. adicional -> Ativos -> Dados -> Reveja (WABA criada nesses
            #      passos);
            #  (b) TERMINAL — a WABA JÁ foi criada antes e esta é a ÚLTIMA tela: basta
            #      CONCLUIR (fechar a popup) e seguir p/ a BM.
            # Selecionamos a opção, clicamos Avançar e damos uma espera CURTA: se avançar,
            # é (a) e o loop segue; se NÃO avançar rápido, é (b) TERMINAL -> conclui JÁ.
            # (fix 2026-08-16: antes ficava ~40s tentando 3x -> "demorando demais p/
            # entender que é a última tela, fechar e ir p/ a BM".)
            status("📞 OAuth: número → 'Use a display name with a virtual number'...")
            _ok_virtual = _selecionar_nome_exibicao(driver)
            _delay_curto()
            _click_oauth_avancar(driver)
            if _aguardar_saida_passo(driver, 'numero', timeout=10, popup_page=popup_page):
                continue   # (a) fluxo novo — segue p/ verif_adicional/ativos/dados/reveja
            # ⚠️ FIX 2026-08-28: aqui estava o pior bug do fluxo. "Não avançou em 7s"
            # era tratado como (b) TELA FINAL e devolvia SUCESSO — mas quando o layout
            # é o NOVO e a seleção do número virtual falhou, a tela também não avança.
            # Resultado: BM entregue SEM WABA → `precisa_criar_waba` → loop infinito de
            # SMS comprando número. Agora só é "tela final" quando a tela REALMENTE não
            # oferece número virtual (layout antigo); no layout novo, insiste e, se não
            # ceder, o guard de repetições aborta com FALHA honesta.
            if _tem_opcao_numero_virtual(driver):
                logger.warning("[FULL/DataCrazy] Tela de número (layout NOVO) não avançou "
                               "— opção virtual %s. Repetindo.",
                               "confirmada" if _ok_virtual else "NAO confirmada")
                status("📞 OAuth: opção de número virtual ainda não fixou — repetindo...")
                _delay_medio()
                continue
            status("📞 OAuth: tela de número é a FINAL (WABA criada) — concluído.")
            return True

        elif passo == 'verif_adicional':
            # NOVO FLUXO: tela informativa "Verificação adicional necessária" (o nome
            # já foi revisado pela Meta) — só Avançar/Continuar.
            # ⚠️ Esse aviso aparece DENTRO da própria tela de número quando a opção
            # "Use a display name with a virtual number instead" é escolhida. Se o
            # Avançar não habilitou (opção não fixou de verdade), re-seleciona antes
            # de tentar de novo — senão o passo repete até abortar.
            status("🔎 OAuth: 'Verificação adicional necessária' → Avançar...")
            if repeticoes >= 1:
                _selecionar_nome_exibicao(driver, timeout=6)
                _delay_curto()
            _click_oauth_avancar(driver)

        elif passo == 'reveja':
            # NOVO FLUXO (2026-08-20): CONFIRMAR. Provado pelo passo a passo manual do
            # dono: no layout novo a WABA NÃO nasce em ativos/dados — ela só é criada
            # quando 'Confirmar' é clicado (tela "Conectando sua conta" → "Assets
            # successfully created"). Parar em 'Reveja' (comportamento v1.47) deixava a
            # BM SEM conta do WhatsApp → loop de SMS/`precisa_criar_waba`.
            # Se, mesmo confirmando, a tela não sair (layout antigo em que 'Reveja' já
            # era terminal), mantemos o comportamento anterior: sucesso.
            status("📝 OAuth: 'Reveja o que você vai compartilhar' → Confirmar (cria a WABA)...")
            if not _click_texto(driver, ['Confirmar', 'Confirm',
                                         # tela PT/EN detectada mas botão em outro idioma
                                         'Xác nhận', 'Подтвердить', 'Konfirmasi', 'पुष्टि करें',
                                         'Confirmer', 'Bestätigen', 'Conferma', 'Onayla',
                                         'Potwierdź', 'Підтвердити', 'Kumpirmahin'],
                                seletor_base='[role="button"], div[role="button"], button, span, div',
                                timeout=12):
                _avancar_tela_desconhecida(driver)
            if _aguardar_saida_passo(driver, 'reveja', timeout=25, popup_page=popup_page):
                continue
            if repeticoes >= 2:
                status("✅ OAuth: 'Reveja' não avançou após confirmar — tratando como "
                       "concluído (WABA conferida depois na Meta).")
                return True
            continue

        elif passo == 'conectando':
            # NOVO (2026-08-20): "Conectando sua conta — isso pode levar alguns
            # instantes...". É AQUI que a Meta cria os ativos (WABA). Só esperar; se
            # a tela empacar, clica 'Tentar novamente'.
            status("⏳ OAuth: 'Conectando sua conta' — a Meta está criando a WABA...")
            if _aguardar_saida_passo(driver, 'conectando', timeout=40, popup_page=popup_page):
                continue
            _click_texto(driver, ['Tentar novamente', 'Try again', 'Reintentar', 'Thử lại',
                                  'Повторить попытку', 'Coba lagi', 'Réessayer',
                                  'Erneut versuchen', 'Riprova', 'Tekrar dene'],
                         seletor_base='[role="button"], div[role="button"], button, span, div',
                         timeout=6)
            if repeticoes >= 2:
                logger.warning("[FULL/DataCrazy] 'Conectando sua conta' não saiu após "
                               "várias esperas — assumindo concluído.")
                return True
            continue

        elif passo == 'conectada':
            status("🎉 OAuth: Conta conectada → Concluir...")
            # A tela final "Sua conta está conectada a Gupshup" tem o botão
            # "Concluir" (pode também aparecer como "Continuar para a configuração
            # de recursos" em variações). 'Concluir' vem primeiro.
            _click_texto(driver, ['Concluir', 'Continuar para a configuração de recursos',
                                  'Continue to feature setup', 'Finalizar', 'Concluído',
                                  'Done', 'Finish', 'Continuar', 'OK',
                                  'Listo', 'Hoàn tất', 'Xong', 'Готово', 'Selesai', 'हो गया',
                                  'Terminé', 'Fertig', 'Bitti', 'Gotowe', 'Tapos na'],
                         seletor_base='[role="button"], div[role="button"], button, span, div',
                         timeout=12)
            # Concluído quando a popup fecha ou a tela sai de 'conectada'.
            if _aguardar_saida_passo(driver, 'conectada', timeout=15, popup_page=popup_page):
                return True
            # Só desiste após MAIS tentativas reais de clicar 'Concluir' (antes
            # desistia cedo demais sem ter clicado no botão certo).
            if repeticoes >= 4:
                logger.warning("[FULL/DataCrazy] 'Concluir' não fechou a popup após várias "
                               "tentativas — assumindo concluído.")
                return True
            continue

        # Aguarda a tela MUDAR antes de re-detectar (gate anti-pulo de etapa).
        _aguardar_saida_passo(driver, passo, timeout=14, popup_page=popup_page)
        _delay_curto()

    logger.warning("[FULL/DataCrazy] Tempo total do fluxo OAuth esgotado.")
    return False


# ============================================================================
# PREENCHIMENTO DOS BOXES DE OTP
# ============================================================================

def _preencher_otp_boxes(driver, codigo):
    """Preenche os 6 boxes do OTP na popup da Gupshup."""
    if not codigo or len(codigo) < 6:
        return False
    # Tenta achar inputs dedicados (maxlength=1) dentro do dialog.
    inputs = []
    for sel in ('[role="dialog"] input[maxlength="1"]',
                'input[maxlength="1"]',
                '[role="dialog"] input',
                'input[type="text"], input[type="tel"], input[type="number"]'):
        try:
            cand = [el for el in driver.query_selector_all(sel) if _visivel(el)]
        except Exception:
            cand = []
        if len(cand) >= 6:
            inputs = cand[:6]
            break
        if cand and not inputs:
            inputs = cand
    if len(inputs) >= 6:
        try:
            for i, ch in enumerate(codigo[:6]):
                el = inputs[i]
                try:
                    el.click(timeout=2000)
                except Exception:
                    pass
                try:
                    el.fill(ch)
                except Exception:
                    driver.keyboard.type(ch)
                _delay(0.1, 0.25)
            return True
        except Exception as e:
            logger.warning("[FULL/DataCrazy] Erro ao preencher boxes OTP: %s", e)
    # Fallback: focar o primeiro input e digitar tudo (auto-advance).
    try:
        if inputs:
            inputs[0].click(timeout=2000)
        driver.keyboard.type(codigo[:6], delay=random.randint(60, 120))
        return True
    except Exception as e:
        logger.warning("[FULL/DataCrazy] Fallback OTP falhou: %s", e)
        return False


# ============================================================================
# FLUXO PRINCIPAL
# ============================================================================

def executar_etapa_full_datacrazy(driver, empresa_dados, senha_fb,
                                  site_url='', callback_status=None,
                                  datacrazy_email='', datacrazy_senha='',
                                  business_id='', modo_meta_direto=True):
    """
    Etapa da WABA do fluxo **Pro Max DataCrazy Turbo** (único fluxo do GS Creator
    desde 2026-10-05): abre o link do OAuth/embedded-signup da Meta (app DataCrazy)
    DIRETO numa aba nova — sem login no CRM — e conduz o OAuth até a WABA nascer.

    Passo a passo (após o domínio já verificado):
      1.  Abre nova aba no link `_oauth_url_meta_datacrazy()` (cbt refrescado).
      2.  Reauth de senha do Facebook, se o formulário pedir.
      3.  Conduz o OAuth (`_rodar_fluxo_oauth`), que cobre os DOIS layouts do popup
          do Facebook (principal ~90% e secundário ~10%).
      4.  SUCESSO em DOIS layouts: (a) fluxo antigo — alcançar a tela "Adicione seu
          número" (WABA já criada, terminal); (b) NOVO fluxo (2026-08-15/2026-08-20) —
          na tela de número escolhe "Use a display name with a virtual number instead"
          e AVANÇA por Verificação adicional -> Ativos -> Dados (categoria 'Outro') ->
          "Reveja o que você vai compartilhar" -> **Confirmar** -> "Conectando sua
          conta" -> "Sua conta está conectada / Assets successfully created" ->
          **Concluir**. É o Confirmar que CRIA a WABA nesse layout (comprovado no
          passo a passo manual do dono, 2026-08-18) — parar em 'Reveja' deixava a BM
          sem conta do WhatsApp.
      4b. Tela NÃO reconhecida: em vez de abortar, tenta seguir pelo botão de avanço
          (`_avancar_tela_desconhecida`), nunca por Cancelar/Voltar/pagamento.
      5.  'Sorry, something went wrong' no OAuth → reabre o link (até 3x).

    Args:
        driver: PlaywrightDriver conectado ao perfil anti-detect.
        empresa_dados: dict com ao menos 'razao_social'.
        senha_fb: senha do perfil do Facebook (reauth, se o FB pedir no popup).
        site_url: URL do site gerado (informativo).
        callback_status: callable(str) para status na UI.
        datacrazy_email/datacrazy_senha/modo_meta_direto: mantidos só por
            compatibilidade de assinatura (o CRM não é mais usado).

    Returns:
        dict {'sucesso': bool, 'mensagem': str, 'phone_number': str, 'waba_id': str,
              'bm_bloqueada': bool}
    """
    res = {'sucesso': False, 'mensagem': '', 'phone_number': '', 'waba_id': '',
           'bm_bloqueada': False}

    def status(msg):
        logger.info("[FULL/DataCrazy] %s", msg)
        if callback_status:
            try:
                callback_status(msg)
            except Exception:
                pass

    razao = (empresa_dados or {}).get('razao_social') or 'Empresa'
    aba_fb_principal = None
    try:
        aba_fb_principal = driver.current_window_handle
    except Exception:
        pass

    # ⛔ GUARD (2026-07-25): NÃO criar WABA num portfólio (BM) que JÁ tem uma WABA
    # DESABILITADA. Quando a Meta desativa uma WABA, ela contamina o PORTFÓLIO
    # INTEIRO → qualquer WABA nova criada ali JÁ NASCE desabilitada. Isso evitava o
    # bug de criar uma 2ª WABA na MESMA BM banida (o certo é criar OUTRA BM/portfólio,
    # o que o backend faz via _pro_max_com_retry ao receber bm_bloqueada). O certo é
    # a BM-alvo estar LIMPA (0 WABA) antes de criar.
    if business_id:
        try:
            from server.etapa_verificacao_negocio import _conta_whatsapp_desabilitada
            if _conta_whatsapp_desabilitada(driver, str(business_id)):
                res['bm_bloqueada'] = True
                res['precisa_nova_bm'] = True
                res['mensagem'] = ('BM já tem WABA DESABILITADA — portfólio contaminado. '
                                   'NÃO criei outra WABA aqui (nasceria morta); precisa de BM nova.')
                status('🔴 ' + res['mensagem'])
                return res
        except Exception as _eg:
            logger.warning('[FULL/DataCrazy] guard WABA-desabilitada (BM contaminada) falhou: %s', _eg)

    popup_page = None
    aba_dc = None
    ctx_orig = getattr(driver, 'context', None)
    pagina_dc = getattr(driver, '_current_page', None)
    _pagina_orig = pagina_dc   # aba de ONDE viemos (pagina_dc vira a aba do OAuth no loop)
    try:
        # ══════════════════════════════════════════════════════════════════
        # ⚡ TURBO (Meta direto): abre o link do OAuth da Meta numa aba nova
        # (já é o formulário do WhatsApp) e conduz o OAuth (_rodar_fluxo_oauth).
        # Sem login no CRM, sem navegar até Conexões.
        # ══════════════════════════════════════════════════════════════════
        _url_meta = _oauth_url_meta_datacrazy()
        oauth_ok = None
        for _sorry_try in range(1, 4):
            status(f"⚡ Turbo: abrindo o formulário da Meta DIRETO (tentativa {_sorry_try}/3)...")
            aba_dc = _abrir_nova_aba(driver, _url_meta)
            if not aba_dc:
                res['mensagem'] = 'Falha ao abrir a aba do OAuth da Meta (Turbo).'
                return res
            _esperar_estatico(driver, timeout=30)
            _delay_longo()
            popup_page = getattr(driver, '_current_page', None)
            pagina_dc = popup_page
            ctx_orig = getattr(driver, 'context', None)
            # Login/Reauth do Facebook DENTRO da aba (estrutural: campo de senha visível
            # num host facebook.com — qualquer idioma). Preenche NO LUGAR com as
            # credenciais do driver (+2FA) sem sair da aba do OAuth. (2026-10-12)
            _login_no_popup_oauth(driver, senha_fb, status)
            # Reauth de senha do Facebook, se o formulário pedir (detecção antiga PT/EN,
            # mantida como reforço — se o estrutural já resolveu, o texto não aparece mais).
            if _existe_texto(driver, ['insira sua senha', 'enter your password',
                                      'insira novamente sua senha'], timeout=4):
                status("🔑 OAuth: reautenticando senha do Facebook...")
                if senha_fb:
                    _preencher(driver, 'input[name="pass"], input[type="password"]',
                               senha_fb, timeout=10)
                    _delay_curto()
                _click_seletor(driver, 'input[data-testid="sec_ac_button"], '
                                       'button[name="login"], input[type="submit"]', timeout=8) or \
                    _click_texto(driver, ['Continuar', 'Continue', 'Entrar', 'Log In'], timeout=8)
                _delay_longo()
            status(f"📲 Turbo: conduzindo OAuth do Facebook ({_sorry_try}/3)...")
            oauth_ok = _rodar_fluxo_oauth(driver, razao, status, popup_page=popup_page,
                                          timeout_total=420, site_url=site_url,
                                          business_id=business_id, senha_fb=senha_fb)
            if oauth_ok != 'sorry':
                break
            status(f"⚠️ OAuth abriu com 'Sorry' — reabrindo o link ({_sorry_try}/3)...")
            try:
                if aba_dc and aba_dc in _handles(driver) and aba_dc != aba_fb_principal:
                    _fechar_aba(driver, aba_dc, voltar_para=aba_fb_principal)
            except Exception:
                pass
            _delay_medio()
        if oauth_ok == 'sorry':
            res['sorry_oauth'] = True
            res['mensagem'] = "OAuth (Turbo/Meta direto) abriu com 'Sorry' 3x."
            status("🔁 " + res['mensagem'])
            return res
        if oauth_ok == 'restrita':
            res['bm_bloqueada'] = True
            res['mensagem'] = 'Conta/BM restrita no OAuth (Turbo) — bloqueada.'
            status("🚫 " + res['mensagem'])
            return res
        if oauth_ok:
            res['sucesso'] = True
            res['mensagem'] = ('✅ WABA criada pelo link DIRETO da Meta (Turbo) — '
                               'OAuth concluído (número/nome → Confirmar → conta conectada).')
            status(res['mensagem'])
        else:
            res['mensagem'] = 'Fluxo OAuth (Turbo) não alcançou a etapa de número/nome de exibição.'
            status("⚠️ " + res['mensagem'])
        return res

    except Exception as e:
        logger.error("[FULL/DataCrazy] Erro na etapa extra: %s", e, exc_info=True)
        res['mensagem'] = f'Erro na etapa DataCrazy: {e}'
        return res
    finally:
        # Fecha a popup OAuth (se aberta) e restaura contexto/aba originais.
        try:
            if popup_page and not popup_page.is_closed():
                popup_page.close()
        except Exception:
            pass
        try:
            if ctx_orig is not None:
                driver.context = ctx_orig
            # FIX (2026-10-12): `pagina_dc` é a própria aba do OAuth (acabou de ser
            # FECHADA acima) — restaurar ela deixava o driver apontando p/ uma página
            # morta quando o switch p/ a aba principal logo abaixo não pegava. Prefere a
            # aba de origem quando a do OAuth já fechou.
            _restaurar = pagina_dc
            try:
                if _restaurar is not None and _restaurar.is_closed() and _pagina_orig is not None \
                        and not _pagina_orig.is_closed():
                    _restaurar = _pagina_orig
            except Exception:
                pass
            if _restaurar is not None:
                driver._current_page = _restaurar
            driver._current_frame = None
        except Exception:
            pass
        # FECHA a aba do DataCrazy — não precisa ficar aberta depois do OAuth. Ao fechá-la,
        # o navegador daquele perfil passa a exibir a aba principal (tab 1) sozinho, sem
        # precisar de bring_to_front (que CONGELA o Windows com N navegadores — só usamos
        # o _trazer_para_frente SEGURO/no-op). Assim o operador vê o fluxo na aba 1 sem
        # clicar, e não sobram abas do DataCrazy acumulando. (2026-08-29, pedido do dono)
        try:
            if aba_dc and aba_dc in _handles(driver) and aba_dc != aba_fb_principal:
                _fechar_aba(driver, aba_dc, voltar_para=aba_fb_principal)
        except Exception:
            pass
        # Volta o foco para a aba principal do Facebook/Business, se existir.
        try:
            if aba_fb_principal and aba_fb_principal in _handles(driver):
                _switch(driver, aba_fb_principal)
            else:
                _switch_para_url(driver, ['business.facebook.com', 'facebook.com'], timeout=5)
            pg = getattr(driver, '_current_page', None)
            if pg is not None:
                _trazer_para_frente(pg)   # SEGURO: no-op quando há N navegadores (anti-freeze)
        except Exception:
            pass
