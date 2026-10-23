#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Leitor de e-mail Outlook/Hotmail POR NAVEGADOR (aba ao lado), para o GS Creator.

POR QUE NAVEGADOR E NÃO IMAP (provado ao vivo 2026-10-06):
    A Microsoft DESLIGOU o Basic Auth em TODAS as contas consumer
    (hotmail/outlook/live). O servidor IMAP responde `LOGINDISABLED` e só aceita
    `AUTH=XOAUTH2` — login com e-mail+senha é recusado no protocolo. OAuth2
    exigiria app no Azure + consentimento interativo num navegador logado por
    conta, o que destrói a premissa "só e-mail e senha". Logo, a ÚNICA conexão
    que funciona com e-mail+senha é abrir a caixa numa ABA do próprio perfil.
    (ver memória gs-outlook-imap-basic-auth-morto / gs-fb-prime-outlook-provedor)

USO NO FLUXO:
    - abrir_e_logar(driver, email, senha, cb): ANTES do login do FB, abre uma aba
      ao lado, garante a sessão da caixa e VOLTA para a aba original. Guarda o
      handle em driver._outlook_tab. Perfis sem 2FA costumam pedir código por
      e-mail para validar o acesso — com a caixa já logada, lemos na hora.
    - ler_codigo(driver, timeout, cb): troca para a aba da caixa, varre
      Prioritários/Outros + Lixo Eletrônico (e faz busca), extrai o código de
      confirmação do Facebook e volta para a aba do FB.

Depende só da API do PlaywrightDriver (open_new_tab/switch_to/execute_script/get).
"""

from __future__ import annotations

import re
import time
import logging

from server.playwright_compat import By

logger = logging.getLogger(__name__)

MAILBOX_URL = "https://outlook.live.com/mail/0/"

# Marcas de domínio Microsoft consumer que EXIGEM navegador (basic-auth desligado).
# gsmails e domínios próprios continuam pela API (gsmails_integration) — não aqui.
_MARCAS_MICROSOFT = ("hotmail", "outlook", "live.com", "live.com.br",
                     "msn.com", "windowslive", "passport.com")


def eh_email_outlook(email: str) -> bool:
    """True se o e-mail é de um provedor Microsoft consumer (precisa de navegador)."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    dominio = e.split("@", 1)[1]
    return any(marca in dominio for marca in _MARCAS_MICROSOFT)


# ── JS: ler as linhas da lista de mensagens (aria-label traz remetente+assunto+prévia) ──
_JS_LER_LINHAS = r"""
try {
  var out = [];
  var seen = {};
  var rows = document.querySelectorAll('div[role="option"], div[role="listitem"], [data-convid], [aria-label][tabindex]');
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var lab = (r.getAttribute && r.getAttribute('aria-label')) || '';
    var txt = (r.innerText || '').replace(/\s+/g, ' ').trim();
    var full = (lab + ' || ' + txt).trim();
    if (!full || full.length < 4) continue;
    if (seen[full]) continue;
    seen[full] = 1;
    out.push(full);
    if (out.length >= 40) break;
  }
  return out;
} catch (e) { return []; }
"""

# ── JS: texto do painel de leitura (e-mail aberto) ──
_JS_LER_PAINEL = r"""
try {
  var sels = ['[role="document"]', '.allowTextSelection', 'div[aria-label][role="region"]',
              '#ConversationReadingPaneContainer', '.wide-content-host'];
  for (var s = 0; s < sels.length; s++) {
    var el = document.querySelector(sels[s]);
    if (el && el.innerText && el.innerText.length > 20) {
      return el.innerText.replace(/\s+/g, ' ').trim();
    }
  }
  return (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 4000);
} catch (e) { return ''; }
"""


def _js_clicar_texto(driver, textos) -> bool:
    """Clica no 1º elemento clicável cujo texto bate com um dos `textos` (case-insensitive)."""
    try:
        return bool(driver.execute_script(r"""
            var alvos = arguments[0].map(function(t){ return t.toLowerCase(); });
            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                var s=getComputedStyle(el);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
            var els = document.querySelectorAll(
                'button, a, div[role="button"], span[role="button"], div[role="treeitem"], ' +
                'div[role="tab"], [role="menuitem"], input[type="submit"]');
            for (var i=0;i<els.length;i++){
                var el = els[i];
                if (!vis(el)) continue;
                var t = ((el.innerText||el.value||el.getAttribute('aria-label')||'')+'').trim().toLowerCase();
                if (!t) continue;
                for (var j=0;j<alvos.length;j++){
                    if (t === alvos[j] || t.indexOf(alvos[j]) !== -1){ el.click(); return true; }
                }
            }
            return false;
        """, list(textos)))
    except Exception:
        return False


def _tela_caixa(driver) -> bool:
    """True se estamos DENTRO da caixa (lista de mensagens / botão de nova mensagem)."""
    try:
        return bool(driver.execute_script(r"""
            var u = location.href.toLowerCase();
            if (u.indexOf('outlook.live.com/mail') === -1 &&
                u.indexOf('outlook.office') === -1) return false;
            // tem lista de mensagens OU botão "Nova mensagem"/"New mail"?
            if (document.querySelector('div[role="option"], div[role="listbox"]')) return true;
            var btns = document.querySelectorAll('button, div[role="button"]');
            for (var i=0;i<btns.length;i++){
                var t=(btns[i].innerText||btns[i].getAttribute('aria-label')||'').toLowerCase();
                if (t.indexOf('nova mensagem')!==-1 || t.indexOf('new mail')!==-1 ||
                    t.indexOf('new message')!==-1 || t.indexOf('novo email')!==-1) return true;
            }
            return false;
        """))
    except Exception:
        return False


# Seletores de login (cobre login.microsoftonline.com E login.live.com).
EMAIL_CSS = ('input[type="email"], input[name="loginfmt"], #i0116, '
             'input[name="email"], input[placeholder*="Email"], input[placeholder*="email"]')
PWD_CSS = 'input[type="password"], input[name="passwd"], #i0118'


def _visivel(driver, css) -> bool:
    try:
        return bool(driver.execute_script(r"""
            var el = document.querySelector(arguments[0]);
            if(!el) return false;
            var r=el.getBoundingClientRect(); var s=getComputedStyle(el);
            return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
        """, css))
    except Exception:
        return False


def _valor_campo(driver, css) -> str:
    try:
        return (driver.execute_script(
            "var e=document.querySelector(arguments[0]);return e?(e.value||''):'';", css) or "")
    except Exception:
        return ""


def _tela_login(driver) -> bool:
    return _visivel(driver, EMAIL_CSS) or _visivel(driver, PWD_CSS)


def _desafio_humano(driver) -> bool:
    """Human challenge da Microsoft (press-and-hold/Arkose) — não automatizável aqui."""
    try:
        return bool(driver.execute_script(r"""
            var t=(document.body&&document.body.innerText||'').toLowerCase();
            if (t.indexOf('pressione e segure')!==-1 || t.indexOf('press and hold')!==-1 ||
                t.indexOf('ajude-nos a confirmar')!==-1 || t.indexOf('help us confirm')!==-1) return true;
            if (document.querySelector('iframe[src*="fpt.live.com"], div#human, iframe[src*="arkoselabs"]')) return true;
            return false;
        """))
    except Exception:
        return False


def _preencher(driver, css, valor) -> bool:
    try:
        ok = driver.execute_script(r"""
            var el = document.querySelector(arguments[0]);
            if (!el) return false;
            el.focus();
            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            setter.call(el, arguments[1]);
            el.dispatchEvent(new Event('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            return true;
        """, css, valor)
        return bool(ok)
    except Exception:
        return False


def _digitar_campo(driver, css, valor) -> bool:
    """Digita VALOR no campo via DIGITAÇÃO REAL (a validação da Microsoft não
    aceita só value-setter JS) e CONFIRMA que o valor entrou. Retorna True só se
    o campo ficou com o valor esperado."""
    alvo = (valor or "").strip()
    try:
        el = driver.find_element(By.CSS_SELECTOR, css)
    except Exception:
        return False
    # foca + limpa
    try:
        el.click()
        time.sleep(0.2)
    except Exception:
        pass
    try:
        el.clear()
    except Exception:
        pass
    # digitação real (handle.type)
    try:
        el.send_keys(alvo)
    except Exception:
        pass
    time.sleep(0.3)
    if _valor_campo(driver, css).strip() == alvo:
        return True
    # fallback: value-setter JS + eventos
    _preencher(driver, css, alvo)
    time.sleep(0.2)
    return _valor_campo(driver, css).strip() == alvo


# Campo do CÓDIGO de segurança (account.live.com/identity/confirm e similares).
SECCODE_CSS = ('input[name="otc"], #iOttText, #idTxtBx_OTC_Password, '
               'input[placeholder="Código"], input[placeholder="Code"], '
               'input[inputmode="numeric"]')

_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_RE_SECCODE = re.compile(
    r"(?:security code|c[óo]digo de seguran[çc]a|c[óo]digo)\D{0,12}(\d{4,8})", re.I)


def _texto_pagina(driver) -> str:
    try:
        return (driver.execute_script(
            "return (document.body&&document.body.innerText||'').toLowerCase();") or "")
    except Exception:
        return ""


def _marcar_input_visivel(driver) -> bool:
    """Marca (data-gsfill) o 1º input de texto VISÍVEL, vazio e editável. Para
    telas onde há um único campo relevante (código de segurança / parte oculta)."""
    try:
        return bool(driver.execute_script(r"""
            var ins = document.querySelectorAll('input');
            for (var i=0;i<ins.length;i++){ var el=ins[i];
                var ty=(el.type||'').toLowerCase();
                if(ty==='hidden'||ty==='submit'||ty==='button'||ty==='checkbox'||ty==='radio'||ty==='password') continue;
                if(el.readOnly||el.disabled) continue;
                var r=el.getBoundingClientRect(); var s=getComputedStyle(el);
                if(r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'){
                    el.setAttribute('data-gsfill','1'); return true; }
            }
            return false;
        """))
    except Exception:
        return False


def _desmarcar_input(driver):
    try:
        driver.execute_script(
            "var e=document.querySelector('input[data-gsfill]'); if(e) e.removeAttribute('data-gsfill');")
    except Exception:
        pass


def _digitar_input_visivel(driver, valor) -> bool:
    if not _marcar_input_visivel(driver):
        return False
    ok = _digitar_campo(driver, 'input[data-gsfill="1"]', valor)
    _desmarcar_input(driver)
    return ok


def _extrair_email_recuperacao(texto, email_outlook):
    """Acha o e-mail de recuperação (diferente do próprio Outlook) no texto da tela."""
    outlook = (email_outlook or "").strip().lower()
    for m in _RE_EMAIL.finditer(texto or ""):
        e = m.group(0).strip().lower()
        if e and e != outlook:
            return e
    return None


def _tratar_protecao_conta(driver, local_outlook, cb=None) -> bool:
    """Tela 'Ajude-nos a proteger sua conta' (atividade incomum). Seleciona a opção
    de e-mail, preenche a parte oculta (= local-part do Outlook) e clica 'Enviar
    código'. Retorna True se avançou para a tela de código."""
    # 1) seleciona o 1º radio (Email para ...), se ainda não marcado
    try:
        driver.execute_script(r"""
            var rs = document.querySelectorAll('input[type=radio]');
            if (rs.length){
                var alvo = rs[0];
                for (var i=0;i<rs.length;i++){
                    var lab = (rs[i].closest('label') || rs[i].parentElement);
                    var t = (lab && lab.innerText || '').toLowerCase();
                    if (t.indexOf('email')!==-1 || t.indexOf('e-mail')!==-1){ alvo = rs[i]; break; }
                }
                if (!alvo.checked){ alvo.click(); }
            }
        """)
    except Exception:
        pass
    time.sleep(1.2)
    # 2) preenche a parte oculta (o input que aparece após selecionar)
    if _marcar_input_visivel(driver):
        _digitar_campo(driver, 'input[data-gsfill="1"]', local_outlook)
        _desmarcar_input(driver)
        time.sleep(0.4)
    # 3) Enviar código
    if cb:
        cb("Pedindo código de segurança ao e-mail de recuperação...")
    if not _js_clicar_texto(driver, ["enviar código", "enviar codigo", "send code", "próximo", "proximo", "next"]):
        _clicar_id(driver, "idSIButton9")
    time.sleep(2.5)
    return True


def _ler_codigo_recuperacao(driver, recovery_email, login_tab, cb=None, timeout=120):
    """Abre o e-mail de RECUPERAÇÃO (temp-mail web, ex.: fviainboxes.com) numa aba,
    lê o 'security code' da Microsoft, fecha a aba e VOLTA para a aba de login.
    Retorna o código ou None. Best-effort — depende do provedor do recovery."""
    if not recovery_email or "@" not in recovery_email:
        return None
    local, dom = recovery_email.split("@", 1)
    if cb:
        cb(f"Lendo código de segurança no e-mail de recuperação ({dom})...")
    temp_tab = None
    try:
        temp_tab = driver.open_new_tab("https://" + dom, switch=True)
        time.sleep(3.0)
        # preenche o endereço (local-part) e pede a caixa
        if _digitar_input_visivel(driver, local):
            time.sleep(0.4)
            _js_clicar_texto(driver, ["get email", "gerar", "generate", "create", "criar",
                                      "ver caixa", "acessar", "go"])
            time.sleep(2.5)

        fim = time.time() + timeout
        ultimo_reload = time.time()
        while time.time() < fim:
            # 1) tenta achar o código no texto já visível
            try:
                corpo = (driver.execute_script(
                    "return (document.body&&document.body.innerText||'');") or "")
            except Exception:
                corpo = ""
            m = _RE_SECCODE.search(corpo)
            if m:
                cod = m.group(1)
                logger.info("[Outlook] Código de recuperação lido: %s", cod)
                return cod
            # 2) abre a mensagem do CÓDIGO (prioriza 'security code' sobre a de
            #    'unusual sign-in', que não traz código) e relê o corpo
            try:
                abriu = driver.execute_script(r"""
                    function tenta(chaves){
                        var els = document.querySelectorAll('*');
                        for (var i=0;i<els.length;i++){
                            var el = els[i];
                            if (el.children && el.children.length>3) continue;
                            var t = (el.innerText||'').toLowerCase();
                            if (!t || t.length>=120) continue;
                            for (var k=0;k<chaves.length;k++){
                                if (t.indexOf(chaves[k])!==-1){ el.click(); return true; }
                            }
                        }
                        return false;
                    }
                    // 1º as que TÊM código; só depois as genéricas da Microsoft
                    if (tenta(['security code','código de segurança','codigo de seguranca',
                               'código de segurança da conta','personal microsoft account security'])) return true;
                    return tenta(['microsoft account','conta microsoft']);
                """)
            except Exception:
                abriu = False
            if abriu:
                time.sleep(1.8)
                try:
                    corpo = (driver.execute_script(
                        "return (document.body&&document.body.innerText||'');") or "")
                except Exception:
                    corpo = ""
                m = _RE_SECCODE.search(corpo)
                if m:
                    cod = m.group(1)
                    logger.info("[Outlook] Código de recuperação lido (corpo): %s", cod)
                    return cod
            # recarrega a caixa a cada 15s
            if time.time() - ultimo_reload > 15:
                try:
                    driver.get("https://" + dom)
                    time.sleep(2.0)
                    if _digitar_input_visivel(driver, local):
                        _js_clicar_texto(driver, ["get email", "gerar", "generate", "create", "criar"])
                        time.sleep(2.0)
                except Exception:
                    pass
                ultimo_reload = time.time()
            time.sleep(2.0)
        logger.warning("[Outlook] Código de recuperação não chegou em %ss.", timeout)
        return None
    except Exception as exc:
        logger.warning("[Outlook] Falha ao ler o e-mail de recuperação: %s", exc)
        return None
    finally:
        # fecha a aba temp e volta para a aba de login
        try:
            if temp_tab and temp_tab in driver.window_handles:
                driver.switch_to.window(temp_tab)
                driver.close()
        except Exception:
            pass
        try:
            if login_tab and login_tab in driver.window_handles:
                driver.switch_to.window(login_tab)
        except Exception:
            pass


def _logar_microsoft(driver, email, senha, cb=None, teto_s=260) -> bool:
    """Máquina de estados do login Microsoft → caixa Outlook. Cobre o fluxo COMPLETO
    medido ao vivo (2026-10-06): e-mail → 'Use sua senha' → senha → 'Ajude-nos a
    proteger' (código no e-mail de recuperação) → código de segurança → termos →
    chave de acesso (Cancelar) → 'Continuar conectado?' (Sim) → caixa.
    Best-effort e idioma-agnóstica; só avança com o campo CONFIRMADO preenchido."""
    local_outlook = (email or "").split("@", 1)[0]
    login_tab = None
    try:
        login_tab = driver.current_window_handle
    except Exception:
        login_tab = None
    fim = time.time() + teto_s
    ult = ""
    tent_email = tent_senha = tent_protect = tent_seccode = 0
    recovery_email = None
    while time.time() < fim:
        if _tela_caixa(driver):
            return True
        if _desafio_humano(driver):
            logger.warning("[Outlook] Human challenge da Microsoft — não automatizável; abortando.")
            if cb:
                cb("E-mail exige desafio 'pressione e segure' da Microsoft — resolva na aba se quiser.")
            return False

        try:
            u = (driver.current_url or "").lower()
        except Exception:
            u = ""
        t = _texto_pagina(driver)

        # 1) "Continuar conectado?" → Sim
        if any(k in t for k in ("continuar conectado", "stay signed in", "permanecer conectado")):
            if not _clicar_id(driver, "idSIButton9"):
                _js_clicar_texto(driver, ["sim", "yes"])
            time.sleep(2.0)
            continue

        # 2) Chave de acesso / passkey (fido/create) → Cancelar (não configurar)
        if ("fido/create" in u or "chave de acesso" in t or "configurando sua chave" in t
                or "passkey" in t or "windows hello" in t):
            if not _js_clicar_texto(driver, ["cancelar", "cancel", "agora não", "pular",
                                             "skip for now", "mais tarde", "ignorar"]):
                _clicar_id(driver, "idBtn_Back")
            time.sleep(2.0)
            continue

        # 3) "Estamos atualizando os nossos termos" → Avançar/Aceitar
        if ("tou/accrue" in u or "atualizando os nossos termos" in t
                or "atualizamos o contrato" in t or "updating our terms" in t):
            if not _js_clicar_texto(driver, ["avançar", "aceitar", "accept", "next", "continuar"]):
                _clicar_id(driver, "idSIButton9")
            time.sleep(2.2)
            continue

        # 4) "Digite o código de segurança" → lê no e-mail de recuperação e digita
        if ("digite o código de segurança" in t or "código de segurança" in t
                or "security code" in t) and _visivel(driver, SECCODE_CSS):
            tent_seccode += 1
            if tent_seccode > 2:
                logger.warning("[Outlook] Código de segurança não resolvido após %d tentativas.", tent_seccode)
                return False
            rec = recovery_email or _extrair_email_recuperacao(t, email)
            if not rec:
                logger.warning("[Outlook] Não achei o e-mail de recuperação na tela de código.")
                return False
            codigo = _ler_codigo_recuperacao(driver, rec, login_tab, cb)
            if not codigo:
                if cb:
                    cb("Não consegui ler o código do e-mail de recuperação.")
                return False
            # já de volta na aba de login
            if _digitar_input_visivel(driver, codigo):
                time.sleep(0.4)
                if not _js_clicar_texto(driver, ["próximo", "proximo", "next", "verificar", "verify"]):
                    _clicar_id(driver, "iVerifyCodeAction") or _clicar_id(driver, "idSIButton9")
                time.sleep(3.0)
            continue

        # 5) "Ajude-nos a proteger sua conta" (atividade incomum)
        if ("identity/confirm" in u or "ajude-nos a proteger" in t
                or "detectamos algo incomum" in t or "help us protect" in t
                or "proteger sua conta" in t):
            tent_protect += 1
            if tent_protect > 3:
                logger.warning("[Outlook] Tela de proteção não avançou após %d tentativas.", tent_protect)
                return False
            recovery_email = recovery_email or _extrair_email_recuperacao(t, email)
            _tratar_protecao_conta(driver, local_outlook, cb)
            continue

        # 6) "Verifique seu email" (passwordless) → clicar 'Use sua senha'
        if ("verifique seu email" in t or "verify your email" in t or "use sua senha" in t
                or "use your password" in t
                or ("enviaremos um código" in t and "senha" in t)):
            if _js_clicar_texto(driver, ["use sua senha", "use your password", "usar senha"]):
                time.sleep(2.0)
                continue

        # 7) SENHA
        if _visivel(driver, PWD_CSS):
            if tent_senha >= 4:
                logger.warning("[Outlook] Senha não aceita após %d tentativas.", tent_senha)
                return False
            tent_senha += 1
            if _digitar_campo(driver, PWD_CSS, senha):
                time.sleep(0.4)
                _clicar_proximo(driver)
                time.sleep(2.6)
            else:
                time.sleep(1.0)
            continue

        # 8) E-MAIL (tela inicial 'Entrar'); evita confundir com telas especiais
        if _visivel(driver, EMAIL_CSS) and "identity/confirm" not in u:
            if tent_email >= 5:
                logger.warning("[Outlook] E-mail não avançou após %d tentativas.", tent_email)
                return False
            tent_email += 1
            if _digitar_campo(driver, EMAIL_CSS, email):
                time.sleep(0.4)
                _clicar_proximo(driver)
                time.sleep(2.6)
            else:
                time.sleep(1.0)
            continue

        # 9) Upsell passwordless / "simplifique" → pular
        if any(k in t for k in ("simplifique", "sem senha", "break free from passwords",
                                "agora não", "skip for now", "mais tarde")):
            if not _js_clicar_texto(driver, ["agora não", "pular", "skip for now",
                                             "mais tarde", "não, obrigado", "no thanks", "ignorar"]):
                _clicar_id(driver, "idBtn_Back")
            time.sleep(1.8)
            continue

        # nada reconhecido: espera a página mexer
        if u != ult:
            ult = u
        time.sleep(1.2)
    return _tela_caixa(driver)


def _clicar_proximo(driver) -> bool:
    if _clicar_id(driver, "idSIButton9"):
        return True
    return _js_clicar_texto(driver, ["avançar", "próximo", "next", "entrar", "sign in"])


def _clicar_id(driver, el_id) -> bool:
    try:
        return bool(driver.execute_script(r"""
            var el = document.getElementById(arguments[0]);
            if (el){ el.click(); return true; } return false;
        """, el_id))
    except Exception:
        return False


def abrir_e_logar(driver, email, senha, callback_status=None) -> bool:
    """Abre a caixa Outlook/Hotmail numa ABA ao lado, garante a sessão e VOLTA
    para a aba original. Guarda o handle em driver._outlook_tab. Não-fatal."""
    if not email or not senha:
        return False
    orig = None
    try:
        orig = driver.current_window_handle
    except Exception:
        orig = None
    try:
        handle = getattr(driver, "_outlook_tab", None)
        if handle and handle in driver.window_handles:
            driver.switch_to.window(handle)
            driver.get(MAILBOX_URL)
        else:
            handle = driver.open_new_tab(MAILBOX_URL, switch=True)
            driver._outlook_tab = handle
        time.sleep(2.5)

        if _tela_caixa(driver):
            ok = True
        else:
            if callback_status:
                callback_status("Entrando no e-mail (Outlook/Hotmail)...")
            ok = _logar_microsoft(driver, email, senha, callback_status)

        if ok:
            logger.info("[Outlook] Caixa logada e pronta: %s", email)
        else:
            logger.warning("[Outlook] Não consegui garantir a sessão da caixa: %s", email)
        return ok
    except Exception as exc:
        logger.warning("[Outlook] abrir_e_logar falhou (não fatal): %s", exc)
        return False
    finally:
        # SEMPRE volta para a aba original (o fluxo do FB continua nela).
        try:
            if orig and orig in driver.window_handles:
                driver.switch_to.window(orig)
        except Exception:
            pass


# Padrões de código do FB: 5-8 dígitos, com ou sem prefixo FB-.
_RE_FBCODE = re.compile(r"(?:FB[\-\s]?)?(\d{5,8})")
_RE_HORA = re.compile(r"\b\d{1,2}:\d{2}\b")
_CHAVES_FB = ("facebook", "código de confirmação", "codigo de confirmacao",
              "confirmation code", "código do facebook", "codigo do facebook",
              "security code", "código de segurança", "fb-")


def _extrair_codigo(texto: str):
    """Extrai o código de confirmação de um trecho de texto (linha ou corpo)."""
    if not texto:
        return None
    baixo = texto.lower()
    if not any(k in baixo for k in _CHAVES_FB):
        return None
    # remove horários (13:45) para não confundir com código
    limpo = _RE_HORA.sub(" ", texto)
    for m in _RE_FBCODE.finditer(limpo):
        cod = m.group(1)
        # ignora anos soltos (ex.: 2026) sem contexto de código
        if len(cod) == 4:
            continue
        return cod
    return None


def ler_codigo(driver, timeout=150, callback_status=None):
    """Troca para a aba da caixa, varre Prioritários/Outros + Lixo, extrai o código
    de confirmação do Facebook. Retorna a string do código (ou None). NÃO volta a
    aba sozinho — o chamador restaura a aba do FB."""
    handle = getattr(driver, "_outlook_tab", None)
    if not handle:
        logger.warning("[Outlook] ler_codigo sem aba da caixa — nada a ler.")
        return None
    try:
        if handle not in driver.window_handles:
            logger.warning("[Outlook] aba da caixa não existe mais.")
            return None
        driver.switch_to.window(handle)
    except Exception as exc:
        logger.warning("[Outlook] não consegui focar a aba da caixa: %s", exc)
        return None

    if not _tela_caixa(driver):
        # sessão pode ter caído — tenta re-logar com as credenciais guardadas
        email = getattr(driver, "_pm_fb_email", "") or ""
        senha = getattr(driver, "_pm_fb_email_senha", "") or ""
        if email and senha:
            _logar_microsoft(driver, email, senha, callback_status)

    fim = time.time() + timeout
    ultimo_reload = 0.0
    abas = ["prioritarios", "outros", "lixo"]
    while time.time() < fim:
        # recarrega a caixa periodicamente (push nem sempre entrega na hora)
        if time.time() - ultimo_reload > 15:
            try:
                driver.get(MAILBOX_URL)
                time.sleep(2.0)
            except Exception:
                pass
            ultimo_reload = time.time()

        for aba in abas:
            try:
                if aba == "outros":
                    _js_clicar_texto(driver, ["outros", "other"])
                    time.sleep(1.0)
                elif aba == "prioritarios":
                    _js_clicar_texto(driver, ["prioritários", "prioritarios", "focado", "focused"])
                    time.sleep(1.0)
                elif aba == "lixo":
                    _js_clicar_texto(driver, ["lixo eletrônico", "lixo eletronico",
                                              "junk email", "junk", "spam"])
                    time.sleep(1.5)
            except Exception:
                pass

            # 1) lê as linhas (assunto/prévia costumam conter o código)
            try:
                linhas = driver.execute_script(_JS_LER_LINHAS) or []
            except Exception:
                linhas = []
            for linha in linhas:
                cod = _extrair_codigo(linha)
                if cod:
                    logger.info("[Outlook] Código do FB encontrado na lista: %s", cod)
                    if callback_status:
                        callback_status(f"Código lido no e-mail: {cod}")
                    return cod

            # 2) abre o 1º e-mail que mencione o Facebook e lê o corpo
            try:
                abriu = driver.execute_script(r"""
                    var rows = document.querySelectorAll('div[role="option"]');
                    for (var i=0;i<rows.length;i++){
                        var t = ((rows[i].getAttribute('aria-label')||'')+' '+(rows[i].innerText||'')).toLowerCase();
                        if (t.indexOf('facebook')!==-1 || t.indexOf('fb-')!==-1){ rows[i].click(); return true; }
                    }
                    return false;
                """)
            except Exception:
                abriu = False
            if abriu:
                time.sleep(1.5)
                try:
                    corpo = driver.execute_script(_JS_LER_PAINEL) or ""
                except Exception:
                    corpo = ""
                cod = _extrair_codigo(corpo)
                if cod:
                    logger.info("[Outlook] Código do FB encontrado no corpo: %s", cod)
                    if callback_status:
                        callback_status(f"Código lido no e-mail: {cod}")
                    return cod

        # volta pra Caixa de Entrada antes do próximo ciclo
        try:
            _js_clicar_texto(driver, ["caixa de entrada", "inbox"])
        except Exception:
            pass
        time.sleep(2.0)

    logger.warning("[Outlook] Código do FB não chegou em %ss.", timeout)
    return None
