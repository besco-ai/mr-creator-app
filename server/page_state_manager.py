import time
import logging
from typing import Tuple

logger = logging.getLogger("GS_BM_Creator.PageStateManager")


def _navegador_fechado(driver) -> bool:
    """True se o navegador foi FECHADO (usuário na mão / queda). Usado dentro dos
    loops de espera p/ SAIR NA HORA em vez de rodar o timeout inteiro (40s) à toa
    com o navegador que nem está mais aberto — reduz o delay de detecção p/ <1s."""
    try:
        fn = getattr(driver, 'is_alive', None)
        if callable(fn):
            return not fn()
    except Exception:
        return True
    return False


def _guardiao_sessao(driver):
    """Após cada espera de página: se o perfil caiu numa tela de login (FB ou Business),
    o session_guard re-loga e volta ao destino. No-op sem credenciais / durante re-login.
    Cobre os cliques que deslogam (a navegação via driver.get já tem o próprio gancho)."""
    if not getattr(driver, '_sg_auto', False) or getattr(driver, '_sg_busy', False):
        return
    try:
        from server import session_guard as _sg
        _sg.auto_restaurar(driver)
    except Exception:
        pass


def url_eh_checkpoint_real(url) -> bool:
    """True só para checkpoint REAL — o CAMINHO /checkpoint/ — e NÃO para o query
    param `checkpoint_src` (que o Facebook adiciona à HOME logada depois de
    'Confiar neste dispositivo': web.facebook.com/?checkpoint_src=any). Olhamos
    apenas o path (antes do '?'/'#'), evitando o falso-positivo de bloqueio."""
    u = (url or '').lower()
    caminho = u.split('?', 1)[0].split('#', 1)[0]
    return '/checkpoint' in caminho

class PageStateManager:
    """
    Gerenciador de estado da página.
    Garante que a página carregou 100% antes de agir e identifica
    exatamente em qual tela o Facebook está.
    """
    
    @staticmethod
    def wait_for_page_load(driver, timeout=30) -> bool:
        """
        Aguarda a página ficar completamente estática (readyState == complete).
        Útil para conexões 4G lentas.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Navegador fechado? Sai NA HORA (não gasta o timeout inteiro).
            if _navegador_fechado(driver):
                logger.warning("[PageStateManager] Navegador fechado — abortando espera de carga.")
                return False
            try:
                state = driver.execute_script("return document.readyState")
                if state == "complete":
                    # Dá um tempinho extra para scripts React renderizarem
                    time.sleep(0.25)
                    return True
            except Exception:
                pass
            time.sleep(0.1)
            
        logger.warning(f"[PageStateManager] Timeout aguardando página carregar ({timeout}s)")
        return False

    @staticmethod
    def _nao_pode_recarregar(driver) -> bool:
        """True quando dar F5 na tela ATUAL destrói o que está em andamento.

        São telas de contexto único: o `encrypted_context` do two_step, o
        checkpoint e qualquer tela com o widget do reCAPTCHA na frente. Recarregar
        qualquer uma delas devolve o usuário para a tela de login.
        """
        try:
            url = (driver.current_url or '').lower()
        except Exception:
            return True  # sem conseguir ler a URL, o seguro é NÃO recarregar
        if any(m in url for m in ('encrypted_context', 'two_step_verification',
                                  'two_factor', '/checkpoint/', 'recaptcha')):
            return True
        try:
            return bool(driver.execute_script("""
                try {
                  var f = document.querySelectorAll('iframe[src*="recaptcha"]');
                  for (var i=0;i<f.length;i++){
                    var r = f[i].getBoundingClientRect();
                    if (r.width > 10 && r.height > 10) return true;
                  }
                  return false;
                } catch(e){ return false; }
            """))
        except Exception:
            return False

    @staticmethod
    def wait_until_stable(driver, timeout=40, settle_time=1.5, f5_after=25,
                          callback_status=None) -> bool:
        """
        Aguarda a página carregar 100% (readyState == 'complete') E ficar
        ESTÁTICA — sem mudanças relevantes no DOM — por `settle_time` segundos
        seguidos. Em vez de um sleep fixo, DETECTA a estabilização (essencial
        para 4G lento, onde o tempo de carga varia muito).

        Se a página NÃO estabilizar dentro de `f5_after` segundos (página
        pendurada / 4G muito lento), dá um F5 (refresh) e reinicia a contagem.
        Desiste após `timeout` segundos no total.

        Retorna True se a página ficou estática; False se estourou o timeout.
        """
        start = time.time()
        ultimo_refresh = start
        ultimo_tamanho = -1
        estavel_desde = None
        # Assentamento MUITO menor: agir assim que a tela para de crescer, sem
        # esperar 1.2-1.5s à toa (os helpers de clique já fazem polling do alvo).
        settle_time = min(float(settle_time), 0.5)

        while time.time() - start < timeout:
            # Navegador fechado? Sai NA HORA (não gasta o timeout de 40s à toa).
            if _navegador_fechado(driver):
                logger.warning("[PageStateManager] Navegador fechado — abortando espera de estabilização.")
                return False
            try:
                pronto = driver.execute_script("return document.readyState") == "complete"
            except Exception:
                pronto = False

            tamanho = -1
            if pronto:
                try:
                    tamanho = driver.execute_script(
                        "return document.getElementsByTagName('*').length;"
                    )
                except Exception:
                    tamanho = -1

            # "Sem mudança": as páginas do Meta (SPA) NUNCA param 100% — têm
            # polling de fundo (presença, anúncios, lazy-load) que muda dezenas de
            # nós o tempo todo. Com tolerância de 3 nós ela NUNCA estabilizava e
            # rodava o timeout inteiro + F5 (o real motivo da lentidão). Tolerância
            # RELATIVA (~1.5% dos nós, mínimo 20) = "não está mais crescendo de
            # verdade" → detecta em 1-2s em vez de 30-40s.
            _tol = max(20, int(tamanho * 0.015)) if tamanho > 0 else 20
            if pronto and tamanho >= 0 and ultimo_tamanho >= 0 and abs(tamanho - ultimo_tamanho) <= _tol:
                if estavel_desde is None:
                    estavel_desde = time.time()
                elif time.time() - estavel_desde >= settle_time:
                    _guardiao_sessao(driver)
                    return True
            else:
                estavel_desde = None
            ultimo_tamanho = tamanho

            # NUNCA dar F5 numa tela de CONTEXTO ÚNICO (captcha / two_step com
            # `encrypted_context` / checkpoint). O widget do reCAPTCHA fica
            # animando o DOM, então a página nunca "estabiliza"; aos 25s vinha o
            # F5, o contexto criptografado morria e o Facebook devolvia a tela de
            # usuário e senha — exatamente o "ele não espera o captcha carregar e
            # volta pro login" relatado em 2026-08-08. Aqui a espera continua,
            # só sem recarregar.
            if PageStateManager._nao_pode_recarregar(driver):
                time.sleep(0.35)
                continue

            # F5 se travou muito tempo sem estabilizar (4G lento / página presa)
            if (time.time() - ultimo_refresh) >= f5_after:
                if callback_status:
                    callback_status("Página lenta — atualizando (F5) e aguardando carregar...")
                logger.info("[PageStateManager] Página não estabilizou em %ss — dando F5.", f5_after)
                try:
                    driver.refresh()
                except Exception:
                    try:
                        driver.get(driver.current_url)
                    except Exception:
                        pass
                ultimo_refresh = time.time()
                estavel_desde = None
                ultimo_tamanho = -1

            time.sleep(0.1)

        logger.warning("[PageStateManager] wait_until_stable estourou %ss sem estabilizar.", timeout)
        return False

    @staticmethod
    def wait_ready_fast(driver, timeout=8, settle=0.35) -> bool:
        """Espera RÁPIDA e ANTI-DESPERDÍCIO: a página só precisa estar CARREGADA
        (readyState 'complete') e parar de crescer por `settle` segundos — NÃO
        esperamos o DOM ficar 100% estático (páginas Meta têm polling de fundo que
        nunca "para") e NUNCA damos F5 (um refresh no meio de um wizard reseta o
        modal e DOBRA o tempo).

        Por que é seguro ser agressivo: os helpers de clique/preenchimento
        (_click_texto/_preencher/_existe_texto) já fazem POLLING do alvo e agem no
        INSTANTE em que ele aparece — então não é preciso estabilizar a tela antes,
        basta ela estar utilizável. `timeout` é um TETO curto: se não carregar a
        tempo, retorna True mesmo assim e o próximo helper segue tentando.
        """
        tmax = max(1.0, min(float(timeout), 8.0))   # teto agressivo (readyState vem em 1-3s)
        fim = time.time() + tmax
        estavel_desde = None
        ultimo = -1
        while time.time() < fim:
            if _navegador_fechado(driver):
                return False
            try:
                pronto = driver.execute_script("return document.readyState") == "complete"
            except Exception:
                pronto = False
            if pronto:
                try:
                    tam = driver.execute_script("return document.getElementsByTagName('*').length;")
                except Exception:
                    tam = -1
                # tolera o ruído de render dinâmico do React (<=6 nós)
                if ultimo >= 0 and tam >= 0 and abs(tam - ultimo) <= 6:
                    if estavel_desde is None:
                        estavel_desde = time.time()
                    elif time.time() - estavel_desde >= settle:
                        _guardiao_sessao(driver)
                        return True
                else:
                    estavel_desde = None
                ultimo = tam
            time.sleep(0.2)
        _guardiao_sessao(driver)
        return True

    @staticmethod
    def identify_current_screen(driver) -> Tuple[str, dict]:
        """
        Identifica exatamente em qual tela o usuário está.
        Retorna o nome da tela e elementos relevantes.
        """
        try:
            url = driver.current_url.lower()
            page_source = driver.page_source.lower()
            
            # 1. Tela de Login com Popup "Fazer login como"
            try:
                popup = driver.execute_script("""
                    return document.evaluate(
                        "//div[@role='dialog']//span[contains(text(), 'Fazer login como') or contains(text(), 'Log in as')]",
                        document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    ).singleNodeValue != null;
                """)
                if popup:
                    return "login_popup", {}
            except Exception:
                pass
                
            # 2. Tela de Login Normal — detectada pelo FORMULÁRIO visível
            #    (e-mail + senha), INDEPENDENTE da URL. Quando o cookie expira, o
            #    Facebook cai no login em URLs que NÃO contêm "/login" (ex.:
            #    web.facebook.com/?_rdc=1&_rdr#), então NÃO dá para confiar só na
            #    URL — confiamos na presença real dos campos no DOM.
            try:
                tem_form_login = driver.execute_script("""
                    function vis(el){
                        if(!el) return false;
                        var r = el.getBoundingClientRect();
                        var s = window.getComputedStyle(el);
                        return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
                    }
                    var email = document.querySelector('#email, input[name="email"]');
                    var pass = document.querySelector('#pass, input[name="pass"]');
                    return vis(email) && vis(pass);
                """)
            except Exception:
                tem_form_login = False
            if tem_form_login:
                return "login_form", {}

            # 2-bis-0. CONTA TRAVADA / "possivelmente hackeada" -> BLOQUEIO (dead-end).
            #     Ex.: "hãy xác nhận rằng đây là tài khoản của bạn để mở khóa" / "có thể
            #     đã bị hack" / "Nhận mã qua email" (só destrava com código no e-mail do
            #     perfil, que NÃO acessamos). Classifica como checkpoint_severe p/ ABORTAR
            #     NA HORA (não perder tempo clicando "Bắt đầu"/"Começar") — o site/empresa
            #     é reaproveitado no próximo perfil da fila.
            try:
                eh_conta_travada = driver.execute_script(r"""
                    try {
                      var t = (document.body && document.body.innerText || '').toLowerCase();
                      var u = (location.href||'').toLowerCase();
                      var noCheckpoint = u.indexOf('/checkpoint/') !== -1;
                      var locked = (
                        t.indexOf('để mở khóa') !== -1 || t.indexOf('mở khóa') !== -1 ||
                        t.indexOf('có thể đã bị hack') !== -1 || t.indexOf('đã khóa tài khoản') !== -1 ||
                        t.indexOf('may have been hacked') !== -1 || t.indexOf('locked your account') !== -1 ||
                        t.indexOf('to unlock') !== -1 || t.indexOf('para desbloquear') !== -1 ||
                        t.indexOf('bloqueamos sua conta') !== -1 || t.indexOf('pode ter sido hackeada') !== -1 ||
                        t.indexOf('đây là tài khoản của bạn') !== -1 || t.indexOf('this is your account') !== -1 ||
                        t.indexOf('nhận mã qua email') !== -1
                      );
                      // SELFIE / identidade por vídeo = dead-end (não automatizável). Sem
                      // input, cairia no fallback permissivo de 'dismiss' e abriria a
                      // câmera — por isso classificamos como severe AQUI, antes.
                      var selfie = (
                        t.indexOf('selfie de vídeo') !== -1 || t.indexOf('selfie de video') !== -1 ||
                        t.indexOf('video selfie') !== -1 || t.indexOf('confirme sua identidade') !== -1 ||
                        t.indexOf('confirm your identity') !== -1 ||
                        t.indexOf('pessoa real com uma selfie') !== -1 ||
                        t.indexOf('real person with a video selfie') !== -1 ||
                        t.indexOf('iniciar selfie') !== -1
                      );
                      if (selfie) return true;
                      return (noCheckpoint && locked) || (locked && (t.indexOf('mở khóa')!==-1 || t.indexOf('unlock')!==-1));
                    } catch(e){ return false; }
                """)
            except Exception:
                eh_conta_travada = False
            if eh_conta_travada:
                return "checkpoint_severe", {}

            # 2-bis. Tela de CÓDIGO POR E-MAIL (confirmemail.php): "Insira o código
            #     de confirmação" / "Nhập mã xác nhận". O FB mandou um código de
            #     5-8 dígitos para o e-mail do perfil. Detecta pela URL
            #     (idioma-independente) OU pelo campo name="code" + ausência de
            #     campos de senha. VEM ANTES do 2FA porque o campo de código pode
            #     ter autocomplete=one-time-code e seria mal classificado como 2FA.
            if 'confirmemail' in url or 'confirm_email' in url:
                return "email_code", {}
            try:
                eh_code_email = driver.execute_script("""
                    function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                        var s=getComputedStyle(el);
                        return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                    // campo específico do confirmemail (name="code") e SEM senha/2FA
                    var code = document.querySelector('input[name="code"]');
                    var ap   = document.querySelector('input[name="approvals_code"], #approvals_code');
                    var pass = document.querySelector('#pass, input[name="pass"], input[type="password"]');
                    if (!vis(code) || vis(ap) || vis(pass)) return false;
                    // confirma contexto de e-mail/confirmação no texto da página
                    var t = (document.body && document.body.innerText || '').toLowerCase();
                    return t.indexOf('@') !== -1 && (
                        t.indexOf('código de confirmação') !== -1 ||
                        t.indexOf('codigo de confirmacao') !== -1 ||
                        t.indexOf('confirmation code') !== -1 ||
                        t.indexOf('mã xác nhận') !== -1 ||
                        t.indexOf('enviamos') !== -1 || t.indexOf('enviado') !== -1 ||
                        t.indexOf('we sent') !== -1 || t.indexOf('gửi đến') !== -1);
                """)
            except Exception:
                eh_code_email = False
            if eh_code_email:
                return "email_code", {}

            # 2-ter. reCAPTCHA ("Não sou um robô") — TEM PRIORIDADE sobre tudo o
            #     que vem abaixo. A tela `two_step_verification/authentication`
            #     muitas vezes é SÓ um reCAPTCHA: pela URL ela caía como
            #     '2fa_screen', o bot digitava o código TOTP num campo que não
            #     existe e o perfil morria em "Não foi possível logar" (visto no
            #     log de 2026-08-08). Um /checkpoint/ com captcha também caía no
            #     Dismiss genérico. Enquanto houver widget de reCAPTCHA VISÍVEL e
            #     AINDA NÃO RESOLVIDO na tela, a tela é 'captcha' — quem resolve é
            #     o CapSolver; depois o loop reavalia e trata 2FA/checkpoint.
            try:
                tem_recaptcha = driver.execute_script("""
                    try {
                      function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                        var s=getComputedStyle(el);
                        return r.width>10 && r.height>10 && s.visibility!=='hidden' && s.display!=='none'; }
                      // Já resolvido (token no textarea)? Então não é mais tela de captcha.
                      var ta = document.querySelector('textarea[id^="g-recaptcha-response"], textarea[name="g-recaptcha-response"]');
                      if (ta && ta.value && ta.value.length > 20) return false;
                      // iframe VISÍVEL do reCAPTCHA (checkbox "Não sou um robô" ou desafio).
                      var ifrs=document.querySelectorAll('iframe[src*="recaptcha"],iframe[title*="reCAPTCHA"],iframe[title*="recaptcha"]');
                      for(var i=0;i<ifrs.length;i++){ if(vis(ifrs[i])) return true; }
                      // widget .g-recaptcha / [data-sitekey] VISÍVEL.
                      var w=document.querySelectorAll('.g-recaptcha,[data-sitekey]');
                      for(var j=0;j<w.length;j++){ if(vis(w[j])) return true; }
                      return false;
                    } catch(e){ return false; }
                """)
            except Exception:
                tem_recaptcha = False
            if tem_recaptcha:
                return "captcha", {}

            # Sinal FORTE de 2FA: campo de código realmente visível no DOM.
            # (NÃO confiamos em "2fa"/"login_code" no page_source: o HTML do
            #  checkpoint "comportamento automatizado" contém esses textos em
            #  scripts e dava falso-positivo de 2FA — o sistema ficava preso
            #  "detectando 2FA" sem nunca clicar em Dismiss.)
            try:
                tem_campo_2fa = driver.execute_script("""
                    function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                        var s=getComputedStyle(el);
                        return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                    return vis(document.querySelector('input[name="approvals_code"], #approvals_code, input[autocomplete="one-time-code"]'));
                """)
            except Exception:
                tem_campo_2fa = False

            # 3. CHECKPOINT "Comportamento automatizado" (botão Dismiss) — vem
            #    ANTES do 2FA. Detecta por TEXTO multi-idioma ('automated behavi'
            #    cobre behavior/behaviour) OU, de forma INDEPENDENTE DE IDIOMA,
            #    por uma página /checkpoint/ que tem um botão de ação (Dismiss/
            #    OK/Continuar) e NENHUM campo de entrada — exatamente o caso da
            #    tela "We suspect automated behavior on your account". Ao clicar,
            #    o Facebook redireciona direto para a Home logada.
            if not tem_campo_2fa:
                # Texto do aviso em vários idiomas (EN/PT/FR/ES). 'automated behavi'
                # cobre behavior/behaviour; 'comportement/comportamiento automat'
                # cobrem FR/ES. Só o texto já basta p/ tratar como Dismiss.
                eh_aviso_texto = ('automated behavi' in page_source or
                                  'comportamento automatizado' in page_source or
                                  'comportement automat' in page_source or
                                  'comportamiento automatizado' in page_source or
                                  'suspeitamos' in page_source or
                                  'suspect automated' in page_source or
                                  'suspectons' in page_source or
                                  'sospechamos' in page_source or
                                  # inglês genérico "suspicious behaviour/activity"
                                  'suspicious behavi' in page_source or
                                  'suspicious activity' in page_source or
                                  # esloveno: "V tvojem računu sumimo na sumljivo vedenje"
                                  # (= suspeitamos de comportamento suspeito). Botão "Opusti".
                                  'sumljivo vedenje' in page_source or
                                  'sumimo na sumljivo' in page_source or
                                  # "Meta took steps to protect your account" (/hacked-protection):
                                  # aviso RECUPERÁVEL — botão "Back to Facebook"/"Voltar para o
                                  # Facebook" dispensa e segue. Detecta por URL (à prova de idioma)
                                  # + textos EN/PT. NÃO é o checkpoint de "possível hack" (que pede
                                  # código por e-mail e é dead-end) — este só precisa dispensar.
                                  '/hacked-protection' in url or
                                  'took steps to protect your account' in page_source or
                                  'protegemos a sua conta' in page_source or
                                  'protegemos sua conta' in page_source or
                                  'logged you out from suspicious devices' in page_source or
                                  'desconectamos você dos dispositivos' in page_source or
                                  'desconectamos voce dos dispositivos' in page_source)
                if eh_aviso_texto and not ('/hacked-protection' in url
                                           or url_eh_checkpoint_real(url)):
                    # FALSO-POSITIVO REAL (teste ao vivo 2026-10-05, conta #3266 em
                    # inglês): `page_source` inclui o JSON embutido da HOME (notificações
                    # tipo "we logged you out from suspicious devices", anúncios etc.).
                    # A home LOGADA era classificada como 'checkpoint_dismiss' e o login
                    # ficava em loop "Checkpoint detectado. Clicando em Dismiss..." para
                    # sempre. Fora de URL de checkpoint, o aviso só vale se o texto está
                    # VISÍVEL: num diálogo, ou no corpo de uma página que NÃO é a home
                    # (sem feed/compositor).
                    try:
                        eh_aviso_texto = bool(driver.execute_script("""
                            var M = ['automated behavi','comportamento automatizado','comportement automat',
                                     'comportamiento automatizado','suspeitamos','suspect automated','suspectons',
                                     'sospechamos','suspicious behavi','suspicious activity','sumljivo vedenje',
                                     'sumimo na sumljivo','took steps to protect your account','protegemos a sua conta',
                                     'protegemos sua conta','logged you out from suspicious devices',
                                     'desconectamos você dos dispositivos','desconectamos voce dos dispositivos'];
                            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                                var s=getComputedStyle(el);
                                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                            function tem(t){ t=(t||'').toLowerCase(); for (var i=0;i<M.length;i++){ if(t.indexOf(M[i])!==-1) return true; } return false; }
                            var dl = document.querySelectorAll('[role="dialog"]');
                            for (var i=0;i<dl.length;i++){ if (vis(dl[i]) && tem(dl[i].innerText)) return true; }
                            var ehHome = !!document.querySelector('[role="feed"]')
                                || !!document.querySelector('[role="banner"] [role="navigation"], [role="banner"] input[type="search"]');
                            if (ehHome) return false;
                            return tem(document.body ? document.body.innerText : '');
                        """))
                    except Exception:
                        pass
                if eh_aviso_texto:
                    return "checkpoint_dismiss", {}
                if url_eh_checkpoint_real(url):
                    try:
                        # INDEPENDENTE DE IDIOMA: é a tela de aviso "Dismiss" quando
                        # NÃO há campo de entrada (texto/senha/código/UPLOAD de arquivo)
                        # e existe um botão de ação (palavra conhecida OU o botão azul
                        # primário). Assim "Ignorer" (FR), "Ignorar" (ES) etc. também
                        # são dispensados, em vez de caírem como checkpoint severo.
                        tem_botao_dismiss = driver.execute_script("""
                            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                                var s=getComputedStyle(el);
                                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                            // Campo de entrada visível (inclui UPLOAD de arquivo p/ NÃO
                            // confundir com checkpoint de identidade) => NÃO é Dismiss.
                            var inputs = document.querySelectorAll('input[type="text"], input[type="password"], input[type="tel"], input[type="email"], input[type="file"], input[autocomplete="one-time-code"], input[name="approvals_code"], textarea');
                            for (var q=0; q<inputs.length; q++){ if (vis(inputs[q])) return false; }
                            var alvos = ['dismiss','dispensar','ignorar','ignorer','ok','continue',
                                         'continuar','continuer','entendi','entendido','got it',
                                         "j'ai compris",'compris','entendido','aceptar','accepter',
                                         'fechar','fermer','cerrar','descartar','rejeter',
                                         // esloveno: Opusti=Dispensar, V redu=OK, Prekliči=Cancelar
                                         'opusti','v redu','preklici','prekliči','nadaljuj','razumem'];
                            var els = document.querySelectorAll('div[role="button"], button, span[role="button"], a[role="button"]');
                            for (var i=0; i<els.length; i++){ if(!vis(els[i])) continue;
                                var t=(els[i].innerText||'').trim().toLowerCase();
                                for (var j=0; j<alvos.length; j++){ if(t===alvos[j]) return true; } }
                            // Fallback idioma-independente: botão AZUL primário do FB.
                            for (var k=0; k<els.length; k++){ if(!vis(els[k])) continue;
                                var bg = getComputedStyle(els[k]).backgroundColor||'';
                                if (bg.indexOf('8, 102, 255')!==-1 || bg.indexOf('24, 119, 242')!==-1) return true; }
                            // Fallback FINAL (2026-07-31): tela /checkpoint/ SEM campo de
                            // entrada (já garantido acima) e com QUALQUER botão de ação
                            // visível e curto (<= 40 chars) → tratamos como Dispensar e
                            // TENTAMOS clicar. É seguro: dead-ends reais (hack/selfie/código)
                            // têm input OU já foram classificados como severe ANTES daqui.
                            // Assim qualquer idioma (esloveno etc.) é dispensado em vez de
                            // abortar o perfil por engano. O clique + reavaliação do loop
                            // confirma se redirecionou p/ a Home antes de declarar bloqueio.
                            for (var m=0; m<els.length; m++){ if(!vis(els[m])) continue;
                                var tx=(els[m].innerText||'').trim();
                                if (tx.length>0 && tx.length<=40) return true; }
                            return false;
                        """)
                    except Exception:
                        tem_botao_dismiss = False
                    if tem_botao_dismiss:
                        return "checkpoint_dismiss", {}

            # (a detecção do reCAPTCHA subiu para o item 2-ter, ANTES do
            #  checkpoint e do 2FA — ver comentário lá em cima.)

            # 4. Tela de 2FA — pelo CAMPO de código visível OU URL genuína de 2FA
            #    (two_factor/two_step), excluindo "remember_browser" (Trust this
            #    device), que contém "two_factor" mas já passou do código.
            em_2fa_url = (('two_factor' in url or 'two_step' in url) and 'remember_browser' not in url)
            if tem_campo_2fa or em_2fa_url:
                return "2fa_screen", {}

            # 5. Tela de Checkpoint Severo (Bloqueio) — só checkpoint REAL (path
            #    /checkpoint/), NÃO o query `checkpoint_src` da home logada.
            if url_eh_checkpoint_real(url) or "/disabled" in url or "/restricted" in url:
                return "checkpoint_severe", {}

            # 5a-bis. Diálogo "Allow the use of cookies by Facebook?" (escolha de
            #     cookies). É um /privacy/consent/ com flow=user_cookie_choice e
            #     dois botões: "Allow all cookies" (azul, PRIMÁRIO) e "Decline
            #     optional cookies". Precisa de tratamento DEDICADO — clicar em
            #     "Allow all cookies" — diferente do consentimento LGPD abaixo.
            #     Detecta pela URL (idioma-independente) OU pelos botões no DOM.
            if 'user_cookie_choice' in url or 'cookie_choice' in url:
                return "cookie_consent", {}
            try:
                tem_dialogo_cookies = driver.execute_script("""
                    function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                        var s=getComputedStyle(el);
                        return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
                    if (document.querySelector('[data-cookiebanner="accept_button"]')) return true;
                    var alvos = ['allow all cookies','permitir todos os cookies',
                                 'decline optional cookies','recusar cookies opcionais'];
                    var els = document.querySelectorAll('button, div[role="button"], a[role="button"], span[role="button"]');
                    for (var i=0;i<els.length;i++){ if(!vis(els[i])) continue;
                        var t=(els[i].innerText||'').trim().toLowerCase();
                        for (var j=0;j<alvos.length;j++){ if(t.indexOf(alvos[j])!==-1) return true; } }
                    return false;
                """)
            except Exception:
                tem_dialogo_cookies = False
            if tem_dialogo_cookies:
                return "cookie_consent", {}

            # 5b. Consentimento de privacidade (LGPD): sequência "Review your
            #     data settings" -> Get Started -> Accept and continue -> Close.
            #     Sinal forte e idioma-independente = a URL /privacy/consent/.
            if 'privacy/consent' in url or 'lgpd_migrated' in url or \
               ('/consent/' in url and 'privacy' in url):
                return "privacy_consent", {}

            # 5c. "You're logged in. Trust this device?" (pós-2FA) — a URL contém
            #     remember_browser. EXIGE clique no botão primário ("Trust this
            #     device") e NÃO é a home. Idioma-independente (via URL).
            if 'remember_browser' in url:
                return "trust_device", {}

            # 5d. Tela de plataforma pós-login (`/auth_platform/afad/?apc=...`).
            #     É uma PASSAGEM: tem banner/navigation e por isso era classificada
            #     como "home" — o fluxo dava o login por concluído e ia criar a BM
            #     em cima de uma tela que não é a home, ficando em loop
            #     "Acessando Business Manager / Preenchendo formulário" até falhar
            #     (visto em 2026-08-08 05:21). Tratada como tela própria: o loop
            #     de login espera ela redirecionar sozinha.
            if 'auth_platform' in url:
                return "auth_platform", {}

            # 6. Home do Facebook (Logado com sucesso). Aceita o query
            #    `checkpoint_src` (home pós-"Confiar neste dispositivo"); só exclui
            #    o checkpoint REAL (path /checkpoint/) e a tela de login.
            if "facebook.com" in url and ("login" not in url and not url_eh_checkpoint_real(url)):
                # Verifica se há elementos típicos da home
                try:
                    is_home = driver.execute_script("""
                        return document.querySelector('[role="feed"]') != null ||
                               document.querySelector('[role="banner"]') != null ||
                               document.querySelector('[role="navigation"]') != null ||
                               document.querySelector('[aria-label="Facebook"]') != null ||
                               document.querySelector('input[type="search"], [role="search"]') != null ||
                               document.querySelector('[aria-label="Your profile"], [aria-label="Seu perfil"]') != null ||
                               document.querySelector('svg[aria-label="Home"], svg[aria-label="Página inicial"]') != null;
                    """)
                    if is_home:
                        return "home", {}
                except Exception:
                    pass
                    
            return "unknown", {"url": url}
            
        except Exception as e:
            logger.error(f"[PageStateManager] Erro ao identificar tela: {e}")
            return "error", {}
