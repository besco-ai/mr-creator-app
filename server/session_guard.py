# -*- coding: utf-8 -*-
"""Guardião de sessão do Facebook — GENÉRICO e compartilhado por TODOS os fluxos.

Se a Meta deslogar o perfil no MEIO de qualquer etapa (criação de BM, OAuth da WABA,
verificação, monitor, reprocesso), o bot caía numa tela de login e falhava em silêncio.
Este módulo DETECTA isso e RE-LOGA sozinho, voltando para o destino de onde estava.

Telas de "deslogado" cobertas (detecção ESTRUTURAL — independe do idioma da conta):
  • `login_fb`       — formulário e-mail/senha do facebook.com (cookie morto), em
                       qualquer URL (/, /login, login.php, device-based...).
  • `login_business` — `business.facebook.com/business/loginpage/?next=...`: a tela
                       "Entrar nas ferramentas comerciais da Meta" com os botões
                       "Continuar com o Facebook / Instagram". NÃO tem input nenhum,
                       por isso o detector antigo (só #email/#pass) nunca disparava
                       (print do dono 2026-10-12: deslogou ao criar a BM e o fluxo
                       ficou parado nessa tela). Qualquer URL `latest/...` do Business
                       deslogado redireciona p/ ela com `next=<destino>` (provado ao vivo).

Integração automática: `playwright_compat.PlaywrightDriver.get/goto/refresh` e
`PageStateManager.wait_until_stable/wait_ready_fast` chamam `auto_restaurar(driver)`
depois de cada navegação/espera. Só age quando o driver tem credenciais (ou um provedor
de credenciais) registrados — `setar_credenciais` / `vincular_perfil`. Custo quando logado:
1 leitura de URL + 1 evaluate (~ms).

Também expõe:
  • `pagina_meta_com_erro(driver)`  — erro GENÉRICO da Meta.
  • `esperar_conteudo_ou_f5(...)`   — TELA BRANCA/skeleton estável-porém-vazio → F5.

⚠️ ISOLAMENTO: opera SÓ no `driver` passado (por-aba/worker); NENHUM estado global.
Credenciais em `driver._fb_login/_fb_senha/_fb_tfa/_fb_email/_fb_email_senha`.
Imports de `automacao_facebook` são LAZY (dentro das funções) p/ evitar import circular.
"""
import re
import time
import logging
from urllib.parse import urlparse, parse_qs, unquote

logger = logging.getLogger("GS_BM_Creator.SessionGuard")

# Teto anti-loop: no máximo N restaurações por janela de tempo por driver. Uma conta que
# desloga sem parar (sessão invalidada pela Meta / senha trocada) não pode prender o worker.
_MAX_RESTAURACOES_JANELA = 4
_JANELA_RESTAURACOES_S = 20 * 60

_MARCADORES_ERRO_META = (
    # PT-BR
    'há um problema técnico com esse recurso', 'ha um problema tecnico com esse recurso',
    'problema técnico com esse recurso', 'problema tecnico com esse recurso',
    'ocorreu um erro', 'algo deu errado', 'atualize a página', 'atualize a pagina',
    'estamos trabalhando para corrigir', 'tente novamente mais tarde',
    # EN (texto EXATO do print do dono: "Sorry, something went wrong / We're sorry,
    # there's a technical problem with this feature. We're working on getting it fixed.")
    'something went wrong', 'technical problem with this feature',
    "we're working on getting it fixed", 'were working on getting it fixed',
    'please try again', 'reload the page', 'try again later',
    # ES
    'se produjo un error', 'algo salió mal', 'algo salio mal',
    'problema técnico con esta función', 'inténtalo de nuevo',
    # VI / ID / RU / HI / TR / FR / DE / IT / TL (contas em qualquer idioma)
    'đã xảy ra lỗi', 'có lỗi xảy ra', 'terjadi kesalahan', 'ada yang salah',
    'что-то пошло не так', 'произошла ошибка', 'कुछ गलत हो गया',
    'bir şeyler ters gitti', "une erreur s'est produite", 'un problème est survenu',
    'etwas ist schiefgelaufen', 'qualcosa è andato storto', 'nagkaproblema',
)

# Telas de contexto ÚNICO que o guardião NUNCA deve atropelar (o próprio fluxo trata):
# OAuth da WABA (popup/aba do DataCrazy), checkpoint, 2FA, captcha.
_URL_NAO_MEXER = (
    'dialog/oauth', '/dialog/', 'skip_api_login', 'api_key=', 'app_id=',
    'checkpoint', 'two_step', 'two_factor', 'two-factor', 'auth_platform',
    'recaptcha', 'captcha', 'confirmemail', 'hacked-protection',
)

# JS estrutural (sem texto traduzido): classifica a tela atual.
_JS_ESTADO = r"""() => {
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect();
      const s = getComputedStyle(e);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const host = (location.hostname || '').toLowerCase();
  const path = (location.pathname || '').toLowerCase();
  const out = {estado: 'ok', host: host};
  if (host.indexOf('facebook.com') === -1) return out;
  // 1) formulário e-mail/senha do facebook.com (qualquer URL, qualquer idioma)
  const em = document.querySelector('#email, input[name="email"]');
  const pw = document.querySelector('#pass, input[name="pass"]');
  if (vis(em) && vis(pw)) { out.estado = 'login_fb'; return out; }
  // 2) tela de login do Business (loginpage com "Continuar com o Facebook/Instagram")
  const naLoginBiz = path.indexOf('/business/loginpage') === 0 ||
                     (host.indexOf('business.') === 0 && (path.indexOf('/login') === 0));
  if (naLoginBiz) {
    const editaveis = Array.from(document.querySelectorAll(
        'input:not([type="hidden"]):not([type="search"]):not([type="checkbox"]):not([type="radio"]),textarea'))
        .filter(vis);
    const botoes = Array.from(document.querySelectorAll('[role="button"],button')).filter(vis);
    const txt = b => (b.innerText || '').toLowerCase();
    // "Facebook"/"Instagram" são MARCAS — não traduzem em nenhum idioma.
    const bFb = botoes.find(b => txt(b).indexOf('facebook') !== -1 && txt(b).length < 80);
    const bIg = botoes.find(b => txt(b).indexOf('instagram') !== -1 && txt(b).length < 80);
    const temNext = /[?&]next=/.test(location.search || '');
    if (!editaveis.length && ((bFb && bIg) || temNext)) {
      out.estado = 'login_business';
      out.tem_botao_fb = !!bFb;
    }
  }
  return out;
}"""

# Clica (por coordenada — clique CONFIÁVEL) no "Continuar com o Facebook".
_JS_BOTAO_FB = r"""() => {
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect();
      const s = getComputedStyle(e);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const botoes = Array.from(document.querySelectorAll('[role="button"],button')).filter(vis);
  const txt = b => (b.innerText || '').toLowerCase();
  let alvo = botoes.find(b => txt(b).indexOf('facebook') !== -1 && txt(b).length < 80);
  if (!alvo) {
    // fallback estrutural: 1º botão (mais alto) que tem ícone — a ordem é FB, IG.
    const comIcone = botoes.filter(b => b.querySelector('i,svg,img'))
                           .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    alvo = comIcone[0];
  }
  if (!alvo) return null;
  alvo.scrollIntoView({block: 'center'});
  const r = alvo.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2};
}"""


# ───────────────────────────── utilitários básicos ─────────────────────────────

def _vivo(driver):
    try:
        if hasattr(driver, 'is_alive'):
            return bool(driver.is_alive())
    except Exception:
        return False
    try:
        return driver is not None and driver.current_url is not None
    except Exception:
        return False


def _url(driver):
    try:
        return driver.current_url or ''
    except Exception:
        return ''


def _status(cb, msg):
    if cb:
        try:
            cb(msg)
        except Exception:
            pass


def _cb_do_driver(driver, callback_status=None):
    return callback_status or getattr(driver, '_pm_status', None)


def estado_sessao(driver):
    """'ok' | 'login_fb' | 'login_business'. Estrutural (idioma-agnóstico)."""
    try:
        r = driver.evaluate_page(_JS_ESTADO) or {}
        return str(r.get('estado') or 'ok')
    except Exception:
        return 'ok'


def _tem_cookie_sessao_fb(driver):
    """True se o contexto ainda tem o cookie de sessão do FB (`c_user`). Sem ele o
    'Continuar com o Facebook' cairia no login — vai direto pro re-login completo."""
    try:
        ctx = getattr(driver, 'context', None)
        if ctx is None:
            return None
        for c in ctx.cookies(['https://www.facebook.com', 'https://business.facebook.com']):
            if c.get('name') == 'c_user' and c.get('value'):
                return True
        return False
    except Exception:
        return None


def _destino_do_next(url):
    """Extrai o destino original do `next=` da tela de login (o lugar de onde caímos)."""
    try:
        q = parse_qs(urlparse(url).query)
        nxt = (q.get('next') or [''])[0]
        nxt = unquote(nxt) if nxt and '%' in nxt else nxt
        if nxt.startswith('http') and 'facebook.com' in nxt and 'loginpage' not in nxt:
            return nxt
    except Exception:
        pass
    return ''


def _url_de_login(u):
    u = (u or '').lower()
    return ('loginpage' in u or '/login' in u or 'login.php' in u)


def _na_login(driver):
    """Compat (usado pela Central): está em QUALQUER tela de login (FB ou Business)?"""
    u = _url(driver).lower()
    if any(m in u for m in ('checkpoint', 'two_step', 'two_factor')):
        return False
    return estado_sessao(driver) in ('login_fb', 'login_business')


def _reload(driver):
    try:
        driver.get(driver.current_url)
        return True
    except Exception:
        try:
            driver.refresh()
            return True
        except Exception:
            return False


# ─────────────────────────── erro genérico / tela branca ───────────────────────────

def pagina_meta_com_erro(driver):
    """True se a tela mostra o erro GENÉRICO da Meta (recurso com problema técnico etc.)."""
    try:
        t = (driver.evaluate_page(
            "() => (document.body && document.body.innerText || '').toLowerCase()") or '')
    except Exception:
        return False
    return any(m in t for m in _MARCADORES_ERRO_META)


def recuperar_erro_generico(driver, cap=3, callback_status=None):
    """Se a tela é o erro genérico da Meta, dá F5/backoff até `cap`. True se saiu do erro."""
    for i in range(1, int(cap) + 1):
        if not _vivo(driver):
            return False
        if not pagina_meta_com_erro(driver):
            return True
        _status(callback_status, f"⟳ Erro genérico da Meta — recarregando ({i}/{cap})...")
        _reload(driver)
        time.sleep(min(2 + i * 2, 8))  # backoff 4s, 6s, 8s...
    return not pagina_meta_com_erro(driver)


def esperar_conteudo_ou_f5(driver, verifica_fn, cap=3, espera=8.0, callback_status=None):
    """Espera o CONTEÚDO ESPERADO aparecer (verifica_fn(driver) -> bool); se não vier no
    tempo, dá F5 e repete até `cap` vezes. True se apareceu."""
    for tentativa in range(1, int(cap) + 1):
        fim = time.time() + float(espera)
        while time.time() < fim:
            if not _vivo(driver):
                return False
            try:
                if verifica_fn(driver):
                    return True
            except Exception:
                pass
            time.sleep(0.6)
        if tentativa < cap:
            _status(callback_status,
                    f"⟳ Tela em branco/sem o conteúdo esperado — F5 ({tentativa}/{cap - 1})...")
            _reload(driver)
            time.sleep(2)
    return False


# ───────────────────────────── credenciais ─────────────────────────────

def setar_credenciais(driver, login='', senha='', tfa='', email='', senha_email=''):
    """Guarda no driver as credenciais do FB desta aba e LIGA o guardião automático.
    Chamar logo após o login inicial. Best-effort (nunca quebra)."""
    try:
        driver._fb_login = login or getattr(driver, '_fb_login', '') or ''
        driver._fb_senha = senha or getattr(driver, '_fb_senha', '') or ''
        driver._fb_tfa = tfa or getattr(driver, '_fb_tfa', '') or ''
        driver._fb_email = email or getattr(driver, '_fb_email', '') or ''
        driver._fb_email_senha = senha_email or getattr(driver, '_fb_email_senha', '') or ''
        driver._sess_relogin = 0
        # A Central (etapa_verificacao_negocio) lê _pm_fb_* — mantém em sincronia.
        for a, v in (('_pm_fb_login', driver._fb_login), ('_pm_fb_senha', driver._fb_senha),
                     ('_pm_fb_tfa', driver._fb_tfa), ('_pm_fb_email', driver._fb_email),
                     ('_pm_fb_email_senha', driver._fb_email_senha)):
            if v and not getattr(driver, a, ''):
                setattr(driver, a, v)
        if driver._fb_login and driver._fb_senha:
            driver._sg_auto = True
    except Exception:
        pass


def parse_credenciais_observacao(texto):
    """login/senha/2FA/e-mail da OBSERVAÇÃO (remark/note) gravada pelos apis do
    multilogin ('🆔 Login:', '🔐 Senha:', '📧 Email:', '🔐 Senha Email:', '🔑 2FA:')."""
    txt = str(texto or '')

    def _g(*rotulos):
        for rot in rotulos:
            m = re.search(r'(?:^|[\s\W])' + rot + r'\s*[:：]\s*([^\r\n]+)', txt, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ''

    return {
        'login': _g('Login', 'UID', r'Usu[aá]rio', 'User', 'ID'),
        'senha': _g('Senha', 'Password', 'Pass', 'Pwd'),
        'tfa': _g('2FA', 'TOTP', '2fa secret', 'Secret'),
        'email': _g('Email', 'E-mail'),
        'senha_email': _g('Senha Email', 'Senha E-mail', 'Email Password'),
    }


def vincular_perfil(driver, profile_id='', mod=None, perfil_data=None):
    """Liga o guardião num driver aberto FORA do fluxo principal (reprocesso, monitor de
    análise, fila de verificação). Usa `perfil_data` se tiver login/senha; senão registra
    um provedor LAZY que lê a observação do perfil (`mod.obter_perfil`) só quando precisar
    re-logar (zero custo se a sessão nunca cair)."""
    try:
        pd = perfil_data or {}
        if pd.get('login') and pd.get('senha'):
            setar_credenciais(driver, pd.get('login', ''), pd.get('senha', ''),
                              pd.get('tfa', ''), pd.get('email', ''), pd.get('senha_email', ''))
            return
        if profile_id and mod is not None and hasattr(mod, 'obter_perfil'):
            def _prov(_pid=str(profile_id), _mod=mod):
                p = _mod.obter_perfil(_pid) or {}
                return parse_credenciais_observacao(p.get('remark') or p.get('note') or '')
            driver._sg_cred_provider = _prov
            driver._sg_auto = True
    except Exception:
        pass


def _garantir_credenciais(driver):
    if getattr(driver, '_fb_login', '') and getattr(driver, '_fb_senha', ''):
        return True
    prov = getattr(driver, '_sg_cred_provider', None)
    if not prov:
        # Central pode ter setado só _pm_fb_*.
        if getattr(driver, '_pm_fb_login', '') and getattr(driver, '_pm_fb_senha', ''):
            setar_credenciais(driver, driver._pm_fb_login, driver._pm_fb_senha,
                              getattr(driver, '_pm_fb_tfa', ''), getattr(driver, '_pm_fb_email', ''),
                              getattr(driver, '_pm_fb_email_senha', ''))
            return True
        return False
    try:
        c = prov() or {}
    except Exception as e:
        logger.warning("[SessionGuard] provedor de credenciais falhou: %s", e)
        c = {}
    if c.get('login') and c.get('senha'):
        setar_credenciais(driver, c['login'], c['senha'], c.get('tfa', ''),
                          c.get('email', ''), c.get('senha_email', ''))
        return True
    return False


def _pode_restaurar(driver):
    """Teto anti-loop por janela de tempo."""
    agora = time.time()
    hist = [t for t in (getattr(driver, '_sg_hist', None) or []) if agora - t < _JANELA_RESTAURACOES_S]
    if len(hist) >= _MAX_RESTAURACOES_JANELA:
        try:
            driver._sg_sessao_instavel = True
        except Exception:
            pass
        return False
    hist.append(agora)
    try:
        driver._sg_hist = hist
    except Exception:
        pass
    return True


# ───────────────────────────── restauração ─────────────────────────────

def _continuar_com_facebook(driver, cb):
    """Na tela de login do Business com `c_user` vivo: clica 'Continuar com o Facebook'
    e espera sair da loginpage. True se saiu para uma tela logada."""
    try:
        pos = driver.evaluate_page(_JS_BOTAO_FB)
    except Exception:
        pos = None
    if not pos:
        return False
    _status(cb, "🔐 Business deslogou — clicando 'Continuar com o Facebook'...")
    try:
        driver.mouse.click(float(pos['x']), float(pos['y']))
    except Exception:
        return False
    fim = time.time() + 20
    while time.time() < fim:
        time.sleep(1.0)
        if not _vivo(driver):
            return False
        u = _url(driver).lower()
        if 'loginpage' in u:
            continue
        # Pode ter aberto um diálogo de confirmação/escolha de conta — se for o form
        # de senha, quem resolve é o re-login completo.
        return estado_sessao(driver) == 'ok'
    return False


def _relogin_completo(driver, cb):
    """facebook.com → (bounce?) → login por credenciais (2FA/captcha/checkpoint)."""
    try:
        from server.automacao_facebook import fazer_login_facebook, verificar_login_facebook
    except Exception as e:
        logger.error("[SessionGuard] import de login falhou: %s", e)
        return False
    try:
        driver.get("https://www.facebook.com/")
        time.sleep(2)
    except Exception:
        pass
    try:
        if verificar_login_facebook(driver, timeout=8, callback_status=cb):
            return True
    except Exception:
        pass
    _status(cb, "🔑 Sessão expirada — logando de novo com usuário/senha (+2FA)...")
    try:
        return bool(fazer_login_facebook(
            driver, driver._fb_login, driver._fb_senha, getattr(driver, '_fb_tfa', '') or None, cb,
            email=getattr(driver, '_fb_email', '') or None,
            senha_email=getattr(driver, '_fb_email_senha', '') or None))
    except Exception as e:
        logger.error("[SessionGuard] fazer_login_facebook falhou: %s", e)
        return False


def restaurar_sessao(driver, destino=None, callback_status=None):
    """Núcleo: se a aba está em QUALQUER tela de login, restaura a sessão e volta ao
    `destino` (ou ao `next=` da tela de login / última URL logada). True = sessão OK."""
    cb = _cb_do_driver(driver, callback_status)
    if not _vivo(driver):
        return False
    est = estado_sessao(driver)
    if est == 'ok':
        return True
    if getattr(driver, '_sg_busy', False):
        return False
    # Perfil DESCARTADO por loop de login (voltou à tela inicial 3x seguidas): não
    # re-loga mais — era o que mantinha o loop infinito após cada navegação.
    if getattr(driver, '_login_descartado', False):
        _status(cb, "⛔ Não foi possível logar no Facebook (login volta sempre à tela inicial).")
        return False
    if not _garantir_credenciais(driver):
        _status(cb, "⚠️ Perfil deslogou no meio do fluxo, mas não há login/senha para re-logar.")
        logger.warning("[SessionGuard] tela de login (%s) sem credenciais no driver.", est)
        return False
    if not _pode_restaurar(driver):
        _status(cb, f"⛔ Sessão caiu {_MAX_RESTAURACOES_JANELA}x em {_JANELA_RESTAURACOES_S // 60}min "
                    "— conta instável, abortando o perfil.")
        return False

    url_login = _url(driver)
    alvo = (destino if destino and not _url_de_login(destino) else '') \
        or _destino_do_next(url_login) or getattr(driver, '_sg_ultima_url', '') or ''
    logger.warning("[SessionGuard] deslogado (%s) em %s — restaurando; destino=%s",
                   est, url_login[:120], alvo[:120])

    driver._sg_busy = True
    try:
        ok = False
        for _passo in range(3):
            if not _vivo(driver):
                return False
            est = estado_sessao(driver)
            if est == 'ok' and not _url_de_login(_url(driver)):
                ok = True
                break
            if est == 'login_business' and _tem_cookie_sessao_fb(driver) is not False:
                if _continuar_com_facebook(driver, cb):
                    ok = True
                    break
                # não saiu → cai no re-login completo abaixo
            _status(cb, "🔐 Perfil deslogou — voltando ao facebook.com e refazendo o login...")
            if not _relogin_completo(driver, cb):
                continue
            if not alvo:
                ok = True
                break
            try:
                driver.get(alvo)
                time.sleep(1.5)
            except Exception:
                pass
            # Business pode pedir o 'Continuar com o Facebook' de novo (agora com c_user):
            # a próxima volta do laço resolve.
        if ok and alvo:
            u = _url(driver)
            if alvo.split('#')[0].rstrip('/') != u.split('#')[0].rstrip('/'):
                try:
                    driver.get(alvo)
                    time.sleep(1.2)
                except Exception:
                    pass
            if estado_sessao(driver) == 'login_business' and _continuar_com_facebook(driver, cb):
                pass
        ok = ok and estado_sessao(driver) == 'ok'
        if ok:
            driver._sess_relogin = 0
            _status(cb, "✅ Sessão restaurada — retomando de onde parou.")
        else:
            _status(cb, "⛔ Não consegui restaurar a sessão do Facebook.")
        return ok
    finally:
        driver._sg_busy = False


def auto_restaurar(driver, destino=None):
    """Gancho AUTOMÁTICO (chamado pelo driver após cada navegação e pelas esperas de
    página). Barato quando logado; nunca levanta exceção."""
    try:
        if not getattr(driver, '_sg_auto', False) or getattr(driver, '_sg_busy', False):
            return True
        u = _url(driver)
        ul = u.lower()
        if 'facebook.com' not in ul:
            return True
        if any(m in ul for m in _URL_NAO_MEXER):
            return True
        est = estado_sessao(driver)
        if est == 'ok':
            if not _url_de_login(u):
                driver._sg_ultima_url = u
            return True
        return restaurar_sessao(driver, destino=destino)
    except Exception as e:
        logger.debug("[SessionGuard] auto_restaurar ignorado: %s", e)
        return True


def garantir_sessao_fb(driver, callback_status=None, renavegar_para=None, max_relogin=3):
    """API antiga (Central/automacao): se a aba caiu em QUALQUER tela de login, RE-LOGA e
    re-navega para `renavegar_para`. True se a sessão está OK (ou foi restaurada)."""
    try:
        if not _vivo(driver):
            return False
        if estado_sessao(driver) == 'ok':
            return True
    except Exception:
        return True
    return restaurar_sessao(driver, destino=renavegar_para, callback_status=callback_status)
