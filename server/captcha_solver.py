#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CAPTCHA-ANYWHERE — resolve reCAPTCHA em QUALQUER tela do fluxo
=============================================================
Antes o CapSolver só era acionado na Central de Segurança. Mas muitos perfis
(sobretudo logando por COOKIE) caem num reCAPTCHA/desafio "confirme que é humano"
LOGO APÓS o login — e a versão antiga não tratava isso fora da Central, então
detectava como erro e FECHAVA o navegador sem concluir o fluxo.

Este módulo é genérico: detecta o widget do reCAPTCHA (em qualquer frame), lê o
sitekey real, resolve via CapSolver e injeta o token — funciona no login, na
criação da BM e em qualquer etapa. NÃO age quando não há widget de captcha (evita
falso-positivo em checkpoints/telas normais). O token da API do CapSolver vem do
driver (`driver._pm_captcha_token`, setado no início da automação).

Reaproveita o CapSolver client (server/capsolver_client.py).
"""

import time
import logging
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

try:
    from server.capsolver_client import resolver_recaptcha, SITEKEY_FACEBOOK_PADRAO
    _TEM_CAPSOLVER = True
except Exception:  # pragma: no cover
    _TEM_CAPSOLVER = False
    SITEKEY_FACEBOOK_PADRAO = '6LdktRgnAAAAAFQ6icovYI2-masYLFjEFyzQzpix'


# JS que detecta o WIDGET real do reCAPTCHA (iframe/textarea/sitekey). Só o
# widget conta como captcha — texto sozinho (ex.: "verificação de segurança" de
# um checkpoint) NÃO dispara o solve (evita gastar CapSolver à toa e injetar no
# nada).
_JS_TEM_WIDGET = r"""() => {
    try {
        const ta = document.querySelector('textarea[id^="g-recaptcha-response"], textarea[name="g-recaptcha-response"]');
        const ifr = document.querySelector('iframe[src*="recaptcha"], iframe[title*="reCAPTCHA"], iframe[title*="recaptcha"]');
        const sk = document.querySelector('[data-sitekey], .g-recaptcha');
        return !!(ta || ifr || sk);
    } catch (e) { return false; }
}"""

_JS_SITEKEY = "() => { var e=document.querySelector('[data-sitekey]'); return e ? e.getAttribute('data-sitekey') : ''; }"

# SRC de todos os iframes do reCAPTCHA (anchor/bframe). É daqui que sai o sitekey
# REAL (parâmetro `k=`) e se é Enterprise (`/recaptcha/enterprise/`) — a tela de
# login do FB renderiza o widget via JS, SEM `data-sitekey` no DOM, então ler só
# `[data-sitekey]` caía no sitekey padrão (o da Central de Segurança) e o token
# vinha para o sitekey ERRADO — o Facebook recusava e o perfil era abortado.
_JS_IFRAME_SRCS = r"""() => {
    try {
        return Array.from(document.querySelectorAll('iframe[src*="recaptcha"]'))
                    .map(function(f){ return f.src || ''; })
                    .filter(function(s){ return !!s; });
    } catch (e) { return []; }
}"""

# Último recurso: sitekey guardado na config interna do grecaptcha.
_JS_SITEKEY_CFG = r"""() => {
    try {
        var cfg = window.___grecaptcha_cfg;
        if (!cfg || !cfg.clients) return '';
        var achado = '';
        Object.keys(cfg.clients).forEach(function(k){
            var c = cfg.clients[k];
            Object.keys(c || {}).forEach(function(k2){
                var o = c[k2];
                if (o && typeof o === 'object') {
                    Object.keys(o).forEach(function(k3){
                        var v = o[k3];
                        if (typeof v === 'string' && v.length > 30 && v.indexOf('6L') === 0) achado = v;
                    });
                }
            });
        });
        return achado;
    } catch (e) { return ''; }
}"""

# Injeta o token em TODOS os widgets/frames e dispara os callbacks do FB/grecaptcha.
_JS_INJETAR = r"""(token) => {
    let did = false;
    try {
        document.querySelectorAll(
            'textarea#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea[id^="g-recaptcha-response"]'
        ).forEach(function(ta){
            ta.value = token; ta.innerHTML = token; ta.style.display='';
            try{ ta.dispatchEvent(new Event('input',{bubbles:true})); }catch(e){}
            try{ ta.dispatchEvent(new Event('change',{bubbles:true})); }catch(e){}
            did = true;
        });
    } catch(e){}
    try {
        document.querySelectorAll('.g-recaptcha,[data-sitekey],[data-callback]').forEach(function(w){
            var cb = w.getAttribute && w.getAttribute('data-callback');
            if (cb && typeof window[cb] === 'function'){ try{ window[cb](token); did=true; }catch(e){} }
        });
    } catch(e){}
    try { if (typeof window.successCallback==='function'){ window.successCallback(token); did=true; } } catch(e){}
    try { if (window.parent && typeof window.parent.successCallback==='function'){ window.parent.successCallback(token); did=true; } } catch(e){}
    try {
        // Varredura RECURSIVA (até 6 níveis) atrás do callback do widget. A busca
        // rasa de 3 níveis não achava o callback em algumas telas do FB, o token
        // ficava só no textarea e nada era submetido.
        var cfg = window.___grecaptcha_cfg;
        var vistos = [];
        function varrer(o, prof){
            if (!o || prof > 6 || typeof o !== 'object') return;
            if (vistos.indexOf(o) !== -1) return;
            vistos.push(o);
            for (var k in o){
                var v;
                try { v = o[k]; } catch(e){ continue; }
                if (k === 'callback' && typeof v === 'function'){
                    try { v(token); did = true; } catch(e){}
                } else if (v && typeof v === 'object'){
                    varrer(v, prof + 1);
                }
            }
        }
        if (cfg && cfg.clients) varrer(cfg.clients, 0);
    } catch(e){}
    return did;
}"""

# Diagnóstico: o que a página mostra logo depois da injeção. Serve para separar
# "token recusado pela Meta" de "token nunca submetido".
_JS_DIAG = r"""() => {
    try {
        var ta = document.querySelector('textarea[id^="g-recaptcha-response"], textarea[name="g-recaptcha-response"]');
        var ifr = document.querySelectorAll('iframe[src*="recaptcha"]');
        function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
            return r.width>10 && r.height>10; }
        var visiveis = 0;
        for (var i=0;i<ifr.length;i++){ if (vis(ifr[i])) visiveis++; }
        return {
            url: location.href.slice(0, 120),
            token_no_textarea: !!(ta && ta.value && ta.value.length > 20),
            iframes_recaptcha: ifr.length,
            iframes_visiveis: visiveis,
            tem_form_login: !!document.querySelector('#email, input[name="email"]'),
        };
    } catch (e) { return {erro: String(e)}; }
}"""


def _eval_page_e_frames(driver, js, arg=None):
    """Roda o JS (arrow-fn) na PAGE e em TODOS os frames. Retorna o 1º resultado
    truthy (ou False). Usa a API nativa do Playwright (wrapper `_current_page`)."""
    # 1) page principal (via wrapper)
    try:
        r = driver.evaluate_page(js, arg) if arg is not None else driver.evaluate_page(js)
        if r:
            return r
    except Exception:
        pass
    # 2) todos os frames
    page = getattr(driver, '_current_page', None)
    try:
        if page is not None:
            for fr in list(page.frames):
                try:
                    r = fr.evaluate(js, arg) if arg is not None else fr.evaluate(js)
                    if r:
                        return r
                except Exception:
                    continue
    except Exception:
        pass
    return False


def captcha_presente(driver):
    """True se há um WIDGET de reCAPTCHA na tela (qualquer frame)."""
    try:
        return bool(_eval_page_e_frames(driver, _JS_TEM_WIDGET))
    except Exception:
        return False


def _urls_recaptcha(driver):
    """URLs dos frames/iframes do reCAPTCHA presentes na tela (anchor e bframe).
    Lê primeiro pelos FRAMES do Playwright (funciona mesmo cross-origin) e
    complementa com os `src` dos iframes no DOM."""
    urls = []
    page = getattr(driver, '_current_page', None)
    try:
        if page is not None:
            for fr in list(page.frames):
                try:
                    u = fr.url or ''
                except Exception:
                    continue
                if 'recaptcha' in u and ('anchor' in u or 'bframe' in u):
                    urls.append(u)
    except Exception:
        pass
    try:
        srcs = _eval_page_e_frames(driver, _JS_IFRAME_SRCS)
        if isinstance(srcs, list):
            for u in srcs:
                if u and u not in urls:
                    urls.append(u)
    except Exception:
        pass
    return urls


def _info_widget(driver):
    """Descobre o SITEKEY REAL da tela atual, se é Enterprise e a action.

    Ordem: URL do iframe do reCAPTCHA (`k=`, o mais confiável) → `[data-sitekey]`
    no DOM → config interna do grecaptcha → sitekey padrão do Facebook.
    Retorna {'sitekey', 'enterprise', 'action', 'origem'}.
    """
    for u in _urls_recaptcha(driver):
        try:
            q = parse_qs(urlparse(u).query)
        except Exception:
            continue
        k = (q.get('k') or [''])[0]
        if not k:
            continue
        return {
            'sitekey': k,
            'enterprise': '/recaptcha/enterprise/' in u,
            'action': (q.get('sa') or [''])[0],
            'origem': 'iframe',
        }
    try:
        k = _eval_page_e_frames(driver, _JS_SITEKEY)
        if k:
            return {'sitekey': k, 'enterprise': True, 'action': '', 'origem': 'data-sitekey'}
    except Exception:
        pass
    try:
        k = _eval_page_e_frames(driver, _JS_SITEKEY_CFG)
        if k:
            return {'sitekey': k, 'enterprise': True, 'action': '', 'origem': 'grecaptcha_cfg'}
    except Exception:
        pass
    return {'sitekey': SITEKEY_FACEBOOK_PADRAO, 'enterprise': True, 'action': '',
            'origem': 'padrao'}


def _injetar(driver, token):
    try:
        return bool(_eval_page_e_frames(driver, _JS_INJETAR, token))
    except Exception:
        return False


def _url_atual(driver):
    try:
        return driver.current_url or ''
    except Exception:
        return ''


def _frame_por_url(driver, *marcas):
    """Devolve o FRAME do Playwright cuja URL contém todas as marcas.

    Usar `page.frames` (e não `page.frame_locator`) é essencial: na tela de login
    o widget do reCAPTCHA mora num iframe ANINHADO dentro de outro iframe do
    Facebook — o frame_locator só enxerga iframes do documento raiz e estourava
    "Timeout waiting for iframe[src*=recaptcha][src*=anchor]".
    """
    page = getattr(driver, '_current_page', None)
    if page is None:
        return None
    try:
        for fr in list(page.frames):
            try:
                u = (fr.url or '').lower()
            except Exception:
                continue
            if all(m in u for m in marcas):
                return fr
    except Exception:
        pass
    return None


def _desafio_aberto(driver):
    """True se o desafio de IMAGENS do reCAPTCHA (bframe) está visível."""
    fr = _frame_por_url(driver, 'recaptcha', 'bframe')
    if fr is None:
        return False
    try:
        return bool(fr.locator('#rc-imageselect, .rc-imageselect-challenge').first.is_visible(timeout=1500))
    except Exception:
        return False


def _clicar_checkbox_humano(driver, timeout=22):
    """Clica no "Não sou um robô" com um clique REAL do navegador do perfil.

    Por que isto vem ANTES do CapSolver: o token que o CapSolver devolve é
    gerado no IP DELE, e no login a Meta recusa (testado em 2026-08-08: token
    injetado 3x seguidas, o FB devolveu o formulário de login todas as vezes).
    Clicando aqui, o token nasce no IP e no fingerprint do próprio perfil — que
    é exatamente o caminho que funciona quando um humano resolve na mão.

    Retorna: 'marcado' (resolvido, token local) | 'desafio' (abriu as imagens)
             | 'timeout' | 'indisponivel'.
    """
    # O iframe do widget pode demorar a aparecer (o Google carrega depois da
    # página). Sem esperar de verdade, o clique falhava como 'indisponivel' e o
    # fluxo seguia por cima de um captcha que nem tinha terminado de montar.
    fr = None
    fim_frame = time.time() + 20
    while time.time() < fim_frame:
        fr = _frame_por_url(driver, 'recaptcha', 'anchor')
        if fr is not None:
            break
        time.sleep(0.5)
    if fr is None:
        logger.info("[Captcha] frame do checkbox não apareceu em 20s.")
        return 'indisponivel'
    try:
        cb = fr.locator('#recaptcha-anchor')
        cb.wait_for(state='visible', timeout=15000)
        # Espera o widget ficar PRONTO (o Google desenha o checkbox antes de
        # habilitá-lo; clicar cedo demais não registra).
        fim_pronto = time.time() + 10
        while time.time() < fim_pronto:
            try:
                if cb.get_attribute('aria-disabled') != 'true':
                    break
            except Exception:
                break
            time.sleep(0.4)
        try:
            cb.hover()
        except Exception:
            pass
        time.sleep(0.5)
        cb.click(timeout=8000)
    except Exception as e:
        logger.info("[Captcha] clique no checkbox não rolou: %s", e)
        return 'indisponivel'

    fim = time.time() + max(5, timeout)
    while time.time() < fim:
        try:
            if fr.locator('#recaptcha-anchor').get_attribute('aria-checked') == 'true':
                return 'marcado'
        except Exception:
            pass
        if _desafio_aberto(driver):
            return 'desafio'
        # A página pode ter navegado sozinha assim que o token saiu.
        if not captcha_presente(driver):
            return 'marcado'
        time.sleep(0.5)
    return 'timeout'


# PT/EN → código do Knowledge Graph que o reCAPTCHA usa nas perguntas. O widget
# do Facebook vem em português, e o classificador espera o código (ou o nome em
# inglês) — sem esta ponte a classificação erra a categoria.
_ALVOS = [
    (('faixa de pedestre', 'faixas de pedestres', 'crosswalk'), '/m/014xcs'),
    (('semáforo', 'semaforo', 'traffic light'), '/m/015qff'),
    (('ônibus', 'onibus', 'bus'), '/m/01bjv'),
    (('carro', 'carros', 'car'), '/m/0k4j'),
    (('bicicleta', 'bicicletas', 'bicycle'), '/m/0199g'),
    (('motocicleta', 'moto', 'motorcycle'), '/m/04_sv'),
    (('hidrante', 'fire hydrant'), '/m/01pns0'),
    (('chaminé', 'chamine', 'chimney'), '/m/01jk_4'),
    (('escada', 'escadas', 'stairs'), '/m/01lynh'),
    (('ponte', 'pontes', 'bridge'), '/m/015kr'),
    (('barco', 'barcos', 'boat'), '/m/019jd'),
    (('palmeira', 'palmeiras', 'palm tree'), '/m/0cdl1'),
    (('táxi', 'taxi'), '/m/0pg52'),
    (('trator', 'tractor'), '/m/013xlm'),
    (('caminhão', 'caminhao', 'truck'), '/m/07r04'),
    (('montanha', 'colina', 'mountain'), '/m/09d_r'),
]


def _codigo_do_alvo(texto):
    t = (texto or '').lower()
    for chaves, codigo in _ALVOS:
        for c in chaves:
            if c in t:
                return codigo, c
    return '', t.strip()[:40]


def resolver_desafio_imagens(driver, api_key, max_rodadas=6, callback_status=None):
    """Resolve o desafio de IMAGENS clicando nos quadradinhos no navegador do
    perfil — assim o token é gerado localmente e a Meta aceita.

    O CapSolver aqui só CLASSIFICA a grade (diz onde clicar). Retorna
    'resolvido' | 'falhou' | 'sem_desafio'.
    """
    from server.capsolver_client import classificar_grade
    import base64

    fr = _frame_por_url(driver, 'recaptcha', 'bframe')
    if fr is None:
        return 'sem_desafio'
    anchor = _frame_por_url(driver, 'recaptcha', 'anchor')
    vazias = 0  # rodadas seguidas em que o classificador não marcou nada

    for rodada in range(1, max(1, max_rodadas) + 1):
        # Já resolveu (o desafio fecha sozinho quando acerta)?
        try:
            if anchor is not None and \
                    anchor.locator('#recaptcha-anchor').get_attribute('aria-checked') == 'true':
                return 'resolvido'
        except Exception:
            pass
        if not _desafio_aberto(driver):
            return 'resolvido' if not captcha_presente(driver) else 'sem_desafio'

        # 1) Qual é o alvo desta rodada ("faixas de pedestres", "semáforos"...)
        try:
            desc = fr.locator('.rc-imageselect-desc-no-canonical, .rc-imageselect-desc').first
            texto = (desc.inner_text(timeout=4000) or '').replace('\n', ' ')
        except Exception:
            texto = ''
        codigo, nome = _codigo_do_alvo(texto)
        question = codigo or nome
        if not question:
            logger.warning("[Captcha] desafio sem alvo legível: %r", texto)
            return 'falhou'

        # 2) Foto da grade (o print sai do próprio navegador do perfil)
        # Preferimos a IMAGEM ORIGINAL servida pelo Google (o `payload` do
        # reCAPTCHA), baixada pelo próprio navegador. O screenshot da tela sai
        # redimensionado/recomprimido (287x289 em vez de 300x300) e o
        # classificador devolvia `hasObject:false` para tudo — inclusive em
        # quadrados com o objeto na cara (medido em 2026-08-08).
        png = None
        try:
            src = fr.locator('.rc-image-tile-wrapper img, img.rc-image-tile-33').first \
                    .get_attribute('src', timeout=4000)
            if src and 'payload' in src:
                page = getattr(driver, '_current_page', None)
                resp = page.request.get(src, timeout=15000)
                if resp.ok:
                    png = resp.body()
                    logger.info("[Captcha] usando o payload original do reCAPTCHA (%d bytes).",
                                len(png or b''))
        except Exception as e:
            logger.debug("[Captcha] payload original indisponível: %s", e)

        if not png:
            try:
                grade = fr.locator('#rc-imageselect-target, table').first
                png = grade.screenshot(timeout=8000)
            except Exception as e:
                logger.warning("[Captcha] não consegui fotografar a grade: %s", e)
                return 'falhou'

        # Guarda a foto enviada — sem ela não dá para saber se o problema foi o
        # enquadramento ou a classificação.
        try:
            import os
            pasta = os.path.join(os.getcwd(), 'logs', 'snaps_login')
            os.makedirs(pasta, exist_ok=True)
            with open(os.path.join(pasta, f"{time.strftime('%H%M%S')}_grade_r{rodada}.png"), 'wb') as f:
                f.write(png)
        except Exception:
            pass

        try:
            tiles = fr.locator('td.rc-imageselect-tile')
            n_tiles = tiles.count()
        except Exception:
            n_tiles = 0
        logger.info("[Captcha] desafio rodada %d — alvo=%r (%s) · %d quadrados",
                    rodada, texto.strip()[:60], question, n_tiles)

        # 3) CapSolver diz QUAIS clicar
        info_w = _info_widget(driver)
        url_pag = _url_atual(driver) or 'https://www.facebook.com/'
        r = classificar_grade(api_key, base64.b64encode(png).decode(), question,
                              website_url=url_pag, website_key=info_w.get('sitekey'))
        if not r.get('sucesso'):
            logger.warning("[Captcha] classificação falhou: %s", r.get('mensagem'))
            return 'falhou'
        indices = [i for i in r.get('indices') or [] if 0 <= i < max(n_tiles, 1)]

        # Fallback: a grade inteira não devolveu nada (acontece quando a API
        # responde no modo "single"). Manda quadrado por quadrado e pergunta
        # "tem o objeto?" — mais caro, mas é o que destrava o desafio.
        if not indices and n_tiles:
            logger.info("[Captcha] grade sem resultado — classificando quadrado a quadrado.")
            for i in range(n_tiles):
                try:
                    tile_png = tiles.nth(i).screenshot(timeout=5000)
                except Exception:
                    continue
                ri = classificar_grade(api_key, base64.b64encode(tile_png).decode(),
                                       question, website_url=url_pag,
                                       website_key=info_w.get('sitekey'))
                if ri.get('tem_objeto') or ri.get('indices'):
                    indices.append(i)

        logger.info("[Captcha] classificação → clicar em %s", indices)
        if not indices:
            # Rodada sem nenhum quadrado: pode ser legítimo, mas duas seguidas
            # significam que o classificador não está enxergando nada — insistir
            # só queima tempo e crédito. Confirma uma vez e, na segunda, desiste
            # para o fluxo cair no plano seguinte.
            vazias += 1
            try:
                fr.locator('#recaptcha-verify-button').click(timeout=5000)
            except Exception:
                pass
            time.sleep(2.5)
            if vazias >= 2:
                logger.warning("[Captcha] classificador não marcou nada em 2 rodadas — desistindo do desafio.")
                return 'falhou'
            continue
        vazias = 0

        # 4) Clicar nos quadradinhos (com ritmo humano)
        for i in indices:
            try:
                tiles.nth(i).click(timeout=5000)
                time.sleep(0.35 + (i % 3) * 0.12)
            except Exception as e:
                logger.debug("[Captcha] clique no tile %d falhou: %s", i, e)

        # 5) Verificar / Pular
        try:
            fr.locator('#recaptcha-verify-button').click(timeout=5000)
        except Exception as e:
            logger.debug("[Captcha] botão verificar não clicou: %s", e)
        time.sleep(2.5)

        if callback_status and rodada == 1:
            try:
                callback_status("Resolvendo o desafio de imagens do reCAPTCHA...")
            except Exception:
                pass

    # Última checagem depois das rodadas
    try:
        if anchor is not None and \
                anchor.locator('#recaptcha-anchor').get_attribute('aria-checked') == 'true':
            return 'resolvido'
    except Exception:
        pass
    return 'falhou'


def _diagnostico(driver):
    """Snapshot curto do estado da página (para o log)."""
    try:
        r = _eval_page_e_frames(driver, _JS_DIAG)
        return r or {}
    except Exception as e:
        return {'erro': str(e)}


def _avancou(driver, url_antes):
    """True quando a tela do captcha JÁ passou: a URL mudou (o FB auto-submete e
    redireciona) ou o widget sumiu da página."""
    try:
        if (_url_atual(driver) or '') != url_antes:
            return True
    except Exception:
        return True
    return not captcha_presente(driver)


def _esperar_avancar(driver, url_antes, segundos=25):
    fim = time.time() + max(1, segundos)
    while time.time() < fim:
        if _avancou(driver, url_antes):
            return True
        time.sleep(1.0)
    return False


def resolver_captcha_se_preciso(driver, callback_status=None, timeout=180,
                                aguardar_widget_seg=20, tentativas=2,
                                permitir_refresh=False):
    """Se houver um reCAPTCHA na tela ATUAL, resolve via CapSolver e injeta o
    token. Idempotente e seguro: se NÃO houver widget, retorna 'no_captcha' na
    hora (não faz nada). O token da API vem de `driver._pm_captcha_token`.

    Resolve com o SITEKEY REAL da tela (lido do iframe do reCAPTCHA) e só dá por
    resolvido depois de CONFIRMAR que a tela avançou (URL mudou / widget sumiu).
    Se o token não for aceito, tenta de novo (novo token) até `tentativas`.

    Retorna: 'no_captcha' | 'resolvido' | 'sem_token' | 'falhou'.
    """
    def _s(m):
        logger.info("[Captcha] %s", m)
        if callback_status:
            try:
                callback_status(m)
            except Exception:
                pass

    if not _TEM_CAPSOLVER:
        return 'no_captcha'

    # 1) Espera curta pelo widget montar (o captcha pode aparecer 1-2s depois da
    #    tela). Se não aparecer, não há captcha aqui.
    fim = time.time() + max(1, aguardar_widget_seg)
    tem = False
    while time.time() < fim:
        if captcha_presente(driver):
            tem = True
            break
        time.sleep(0.6)
    if not tem:
        return 'no_captcha'

    captcha_token = (getattr(driver, '_pm_captcha_token', '') or '').strip()
    # Modo central: o painel resolve com a chave do admin e o token local é vazio
    # por design — não pode abortar aqui (era o que matava o perfil no login).
    try:
        from server.capsolver_client import token_necessario as _tok_nec
        _precisa_token = _tok_nec()
    except Exception:
        _precisa_token = True
    if not captcha_token and _precisa_token:
        _s("Captcha detectado, mas SEM token do CapSolver configurado — não dá para resolver.")
        return 'sem_token'

    _s("🤖 reCAPTCHA detectado — resolvendo via CapSolver...")
    # 2) Deixa o widget assentar mais um pouco antes de ler o sitekey.
    time.sleep(1.2)

    # ── PLANO A: clique REAL no "Não sou um robô" ───────────────────────────
    # Token gerado no IP/fingerprint do próprio perfil. Quando o Google não pede
    # desafio (caso comum com perfil antidetect), o Facebook aceita na hora e o
    # login segue — sem gastar CapSolver.
    url_ini = _url_atual(driver) or 'https://www.facebook.com/'
    r_click = _clicar_checkbox_humano(driver)
    logger.info("[Captcha] clique no checkbox → %s", r_click)
    if r_click == 'marcado':
        if _esperar_avancar(driver, url_ini, segundos=15):
            _s("✅ Captcha passou no clique (sem desafio) — login seguindo.")
            return 'resolvido'
        _avancar_apos_captcha_local(driver)
        if _esperar_avancar(driver, url_ini, segundos=15):
            _s("✅ Captcha passou no clique — login seguindo.")
            return 'resolvido'
    elif r_click == 'desafio':
        # PLANO B: resolver as imagens AQUI, clicando no navegador do perfil.
        # O token sai do próprio Google para esta sessão — é o único que a Meta
        # aceita no login.
        _s("Desafio de imagens — resolvendo com o CapSolver (clique local)...")
        r_img = resolver_desafio_imagens(driver, captcha_token,
                                         callback_status=callback_status)
        logger.info("[Captcha] desafio de imagens → %s", r_img)
        if r_img == 'resolvido':
            _avancar_apos_captcha_local(driver)
            if _esperar_avancar(driver, url_ini, segundos=20):
                _s("✅ Captcha resolvido no navegador — login seguindo.")
                return 'resolvido'

    ultimo_erro = ''
    for tentativa in range(1, max(1, tentativas) + 1):
        if not captcha_presente(driver):
            _s("Captcha sumiu sozinho — seguindo o fluxo.")
            return 'resolvido'

        info = _info_widget(driver)
        sitekey = info['sitekey']
        url_antes = _url_atual(driver) or 'https://www.facebook.com/'
        logger.info("[Captcha] tentativa %d — sitekey=%s (origem=%s, enterprise=%s, action=%s)",
                    tentativa, sitekey, info['origem'], info['enterprise'],
                    info['action'] or '-')

        # Enterprise primeiro se a URL do widget disser que é (o FB no login usa
        # reCAPTCHA Enterprise); senão, tenta o v2 comum primeiro. O outro modo
        # entra como fallback.
        modos = [info['enterprise'], not info['enterprise']]
        res = {'sucesso': False, 'mensagem': 'sem tentativa'}
        for ent in modos:
            res = resolver_recaptcha(captcha_token, url_antes, website_key=sitekey,
                                     enterprise=ent,
                                     page_action=(info['action'] or None),
                                     timeout=timeout)
            if res.get('sucesso'):
                break

        if not res.get('sucesso'):
            ultimo_erro = res.get('mensagem', '')
            _s(f"❌ CapSolver falhou: {ultimo_erro}")
            continue

        token = res.get('token', '')
        injetou = False
        for _ in range(6):
            if _injetar(driver, token):
                injetou = True
                break
            time.sleep(1.2)
        logger.info("[Captcha] injeção did=%s | diag pós-injeção: %s",
                    injetou, _diagnostico(driver))
        # Dá ao Facebook um instante para processar o token antes de julgar a
        # tela (ele navega sozinho quando aceita).
        time.sleep(2.5)
        logger.info("[Captcha] diag +2.5s: %s", _diagnostico(driver))

        # 3) CONFIRMA que a tela avançou. O FB auto-submete quando o callback do
        #    grecaptcha recebe o token; quando não auto-submete, clicamos o botão.
        if _esperar_avancar(driver, url_antes, segundos=12):
            _s("✅ Captcha resolvido — login seguindo.")
            time.sleep(1.0)
            return 'resolvido'
        _avancar_apos_captcha_local(driver)
        if _esperar_avancar(driver, url_antes, segundos=20):
            _s("✅ Captcha resolvido — login seguindo.")
            time.sleep(1.0)
            return 'resolvido'
        ultimo_erro = 'token injetado mas a tela não avançou'
        _s(f"⚠️ {ultimo_erro} — tentando de novo...")
        # F5 aqui é PERIGOSO: na tela do two_step o `encrypted_context` é de uso
        # único — recarregar devolve o Facebook para a tela de usuário e senha.
        # Só recarrega quando a URL não carrega esse contexto.
        url_agora = (_url_atual(driver) or '').lower()
        contexto_unico = any(m in url_agora for m in
                             ('encrypted_context', 'two_step_verification',
                              'two_factor', '/checkpoint/'))
        if permitir_refresh and not contexto_unico:
            try:
                driver.refresh()
            except Exception:
                pass
        elif contexto_unico:
            logger.info("[Captcha] tela de contexto único — NÃO vou dar F5 "
                        "(recarregar volta para o login).")
        time.sleep(3.0)

    _s(f"❌ Não consegui passar do reCAPTCHA ({ultimo_erro}).")
    return 'falhou'


def _avancar_apos_captcha_local(driver):
    """Clica Continuar/Enviar/botão azul primário quando a tela do captcha não
    auto-submete após a injeção do token. Best-effort."""
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
            // Fallback idioma-independente: botão AZUL primário do Facebook.
            for(var k=0;k<els.length;k++){ if(!vis(els[k])) continue;
                var bg=getComputedStyle(els[k]).backgroundColor||'';
                if(bg.indexOf('8, 102, 255')!==-1 || bg.indexOf('24, 119, 242')!==-1){ els[k].click(); return true; } }
            return false;
        """))
    except Exception:
        return False
