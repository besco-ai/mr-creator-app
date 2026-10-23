#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Camada de compatibilidade Playwright para substituir Selenium.
Mantém a maior parte da API usada pelo projeto, conectando ao IXBrowser via CDP.
"""

from __future__ import annotations

import time
import logging
from typing import Any, List, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

logger = logging.getLogger(__name__)

# Quando True, chamamos page.bring_to_front() a cada troca de aba — assim a ABA
# que a automação está USANDO fica visível em tempo real (o usuário acompanha o
# preenchimento da BM, a volta para o e-mail de confirmação, etc.), em vez de a
# automação trabalhar numa aba oculta enquanto outra aba aparece na frente.
# bring_to_front() ativa a aba DENTRO da janela do navegador do perfil
# (AdsPower/IXBrowser), seguindo o que estiver em uso no momento.
TRAZER_PARA_FRENTE = True

# ── MODO PARALELO ─────────────────────────────────────────────────────────────
# CAUSA DE TRAVAMENTO TOTAL DO WINDOWS (mouse e teclado morrem, navegadores
# congelados, sem BSOD): page.bring_to_front() é Page.bringToFront do CDP, que no
# Chromium chama Activate() no WebContents — ou seja, ele NÃO ativa só a aba, ele
# traz a JANELA do navegador para o primeiro plano do SO.
#
# Com 1 navegador isso é inofensivo. Com N navegadores simultâneos vira uma
# TEMPESTADE DE ATIVAÇÃO: N processos Chrome disputando o foreground várias vezes
# por segundo. O foreground manager do win32k serializa isso na fila de entrada
# do desktop — a fila nunca termina uma troca antes da próxima chegar e o input
# do usuário (mouse/teclado) para de ser entregue. O sistema inteiro congela.
#
# Fica pior na etapa OAuth (DataCrazy/Gupshup) porque ela abre popup, adota a
# popup, volta para a aba original e fecha a popup — 3 a 4 ativações de janela em
# poucos segundos, por worker.
#
# Em paralelo NÃO trazemos nada para frente: a automação é toda por DOM/CDP e não
# precisa de foco. Setado pelo backend, igual ao automacao_facebook.set_modo_paralelo.
_MODO_PARALELO = False


def set_modo_paralelo(ativo):
    """Liga/desliga o modo paralelo (chamado pelo backend quando simultâneos>1).
    Em paralelo, NENHUM bring_to_front() é executado."""
    global _MODO_PARALELO
    _MODO_PARALELO = bool(ativo)
    logger.info("[Janelas] Modo paralelo %s — bring_to_front() %s.",
                "LIGADO" if _MODO_PARALELO else "desligado",
                "SUPRIMIDO" if _MODO_PARALELO else "ativo")


def modo_paralelo_ativo():
    return _MODO_PARALELO


def trazer_para_frente(page):
    """bring_to_front() seguro: respeita TRAZER_PARA_FRENTE e o modo paralelo.

    USE SEMPRE ESTA FUNÇÃO — nunca chame page.bring_to_front() direto, senão a
    janela é ativada mesmo em paralelo e o congelamento volta. Retorna True se
    realmente trouxe a janela para frente."""
    if not TRAZER_PARA_FRENTE or _MODO_PARALELO or page is None:
        return False
    try:
        page.bring_to_front()
        return True
    except Exception:
        return False


# Timeout de navegação (goto/reload). ANTES era 45000ms (45s) — com internet LENTA
# a página demorava mais que isso p/ o 'domcontentloaded' e o goto ESTOURAVA,
# virando ERRO/FALHA mesmo estando só CARREGANDO. Agora é generoso (120s) e, se
# mesmo assim estourar, NÃO tratamos como erro: a página provavelmente ainda está
# carregando e as esperas seguintes (wait_until_stable) cuidam de aguardar ficar
# pronta. Só é erro real quando o navegador fecha/cai (aí as ops levantam exceção).
NAV_TIMEOUT_MS = 120000


class TimeoutException(Exception):
    pass


class NoSuchElementException(Exception):
    pass


class ElementClickInterceptedException(Exception):
    pass


class StaleElementReferenceException(Exception):
    pass


class WebDriverException(Exception):
    pass


class By:
    CSS_SELECTOR = 'css selector'
    TAG_NAME = 'tag name'
    XPATH = 'xpath'


class Keys:
    CONTROL = '\ue009'
    DELETE = '\ue017'
    RETURN = '\ue006'
    BACKSPACE = '\ue003'


class ChromeOptions:
    def __init__(self):
        self.experimental_options = {}
        self.arguments = []

    def add_experimental_option(self, name, value):
        self.experimental_options[name] = value

    def add_argument(self, arg):
        self.arguments.append(arg)


class Service:
    def __init__(self, executable_path=None):
        self.executable_path = executable_path


class ActionChains:
    def __init__(self, driver):
        self.driver = driver
        self._actions = []

    def move_to_element(self, element):
        self._actions.append(('move', element))
        return self

    def click(self, element=None):
        self._actions.append(('click', element))
        return self

    def perform(self):
        for action, element in self._actions:
            if action == 'click' and element:
                element.click()
        self._actions = []
        return True


class _EC:
    @staticmethod
    def presence_of_element_located(locator):
        by, value = locator
        def _predicate(driver):
            try:
                el = driver.find_element(by, value)
                return el
            except Exception:
                return False
        return _predicate

    @staticmethod
    def element_to_be_clickable(locator):
        by, value = locator
        def _predicate(driver):
            try:
                el = driver.find_element(by, value)
                return el if el.is_displayed() else False
            except Exception:
                return False
        return _predicate


EC = _EC()


class WebDriverWait:
    def __init__(self, driver, timeout, poll_frequency=0.2):
        self.driver = driver
        self.timeout = timeout
        self.poll_frequency = poll_frequency

    def until(self, method):
        end = time.time() + self.timeout
        last_exc = None
        while time.time() < end:
            # Navegador fechado (usuário/queda)? Sai NA HORA em vez de gastar o
            # timeout inteiro — evita acumular vários waits de 10s com o navegador
            # que nem está mais aberto.
            try:
                _alive = getattr(self.driver, 'is_alive', None)
                if callable(_alive) and not _alive():
                    raise TimeoutException('Navegador foi fechado')
            except TimeoutException:
                raise
            except Exception:
                pass
            try:
                value = method(self.driver)
                if value:
                    return value
            except Exception as exc:
                last_exc = exc
            time.sleep(self.poll_frequency)
        if last_exc:
            raise TimeoutException(str(last_exc))
        raise TimeoutException('Timeout aguardando condição')


def _normalize_cdp_endpoint(debugging_address: str) -> str:
    addr = (debugging_address or '').strip()
    if not addr:
        raise WebDriverException('Endereço CDP vazio')
    if addr.startswith('ws://') or addr.startswith('wss://') or addr.startswith('http://') or addr.startswith('https://'):
        return addr
    return f'http://{addr}'


def _selector(by: str, value: str) -> str:
    if by == By.CSS_SELECTOR:
        return value
    if by == By.TAG_NAME:
        return value
    if by == By.XPATH:
        return f'xpath={value}'
    raise WebDriverException(f'Selector não suportado: {by}')


class PlaywrightElementWrapper:
    def __init__(self, driver: 'PlaywrightDriver', handle):
        self._driver = driver
        self._handle = handle
        self.parent = driver

    def __bool__(self):
        return True

    def click(self):
        try:
            self._handle.scroll_into_view_if_needed(timeout=5000)
            self._handle.click(timeout=5000)
            return True
        except Exception:
            try:
                self._handle.evaluate('(el) => el.click()')
                return True
            except Exception as exc:
                raise ElementClickInterceptedException(str(exc))

    def clear(self):
        try:
            self._handle.fill('')
            return True
        except Exception:
            try:
                self._handle.evaluate("""
                (el) => {
                  if ('value' in el) el.value = '';
                  if (el.isContentEditable) el.textContent = '';
                  el.dispatchEvent(new Event('input', {bubbles: true}));
                  el.dispatchEvent(new Event('change', {bubbles: true}));
                }
                """)
                return True
            except Exception as exc:
                raise WebDriverException(str(exc))

    def send_keys(self, text):
        page = self._driver._current_page
        try:
            self._handle.focus()
        except Exception:
            pass

        if text == Keys.DELETE:
            page.keyboard.press('Delete')
            return True
        if text == Keys.BACKSPACE:
            page.keyboard.press('Backspace')
            return True
        if text == Keys.RETURN:
            page.keyboard.press('Enter')
            return True
        if isinstance(text, str) and text.startswith(Keys.CONTROL) and len(text) > 1:
            remainder = text[1:]
            if remainder:
                page.keyboard.press(f'Control+{remainder.upper()}')
                return True
        try:
            self._handle.type(str(text), delay=20)
            return True
        except Exception:
            try:
                page.keyboard.type(str(text), delay=20)
                return True
            except Exception as exc:
                raise WebDriverException(str(exc))

    def is_displayed(self):
        try:
            return bool(self._handle.is_visible())
        except Exception:
            try:
                return bool(self._handle.evaluate("""
                (el) => {
                  const r = el.getBoundingClientRect();
                  const s = getComputedStyle(el);
                  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                }
                """))
            except Exception:
                return False

    @property
    def text(self):
        try:
            return self._handle.inner_text()
        except Exception:
            try:
                return self._handle.text_content() or ''
            except Exception:
                return ''

    def get_attribute(self, name):
        try:
            return self._handle.get_attribute(name)
        except Exception:
            return None


class _SwitchTo:
    def __init__(self, driver: 'PlaywrightDriver'):
        self._driver = driver

    def window(self, handle):
        self._driver._switch_to_page(handle)

    def frame(self, frame_element: PlaywrightElementWrapper):
        frame = frame_element._handle.content_frame()
        if not frame:
            raise NoSuchElementException('Iframe sem conteúdo acessível')
        self._driver._current_frame = frame
        return frame

    def default_content(self):
        self._driver._current_frame = None


# Tetos GLOBAIS de tempo (ms). Sem eles, QUALQUER chamada do Playwright pode
# pendurar para sempre: o worker some do log e só o Watchdog o mata, 600s depois,
# perdendo o perfil inteiro (13 de 30 perfis num run — diagnóstico 2026-09-03).
# O padrão do Playwright já é 30s, mas ele NÃO se aplica a connect_over_cdp nem
# às chamadas de contexto/página feitas antes de configurarmos o contexto.
CDP_CONNECT_TIMEOUT_MS = 45_000     # conectar ao navegador do AdsPower/IxBrowser
DEFAULT_ACTION_TIMEOUT_MS = 45_000  # click, fill, wait_for_selector...
DEFAULT_NAV_TIMEOUT_MS = 90_000     # goto / reload (4G e proxy são lentos)


class PlaywrightDriver:
    def __init__(self, debugging_address: str):
        endpoint = _normalize_cdp_endpoint(debugging_address)
        self._playwright = sync_playwright().start()
        # timeout EXPLÍCITO: era aqui que o worker travava indefinidamente quando o
        # CDP aceitava a porta mas não respondia (navegador subindo/proxy lento).
        try:
            self.browser = self._playwright.chromium.connect_over_cdp(
                endpoint, timeout=CDP_CONNECT_TIMEOUT_MS)
        except Exception:
            # não deixa o playwright vazando se a conexão falhar
            try:
                self._playwright.stop()
            except Exception:
                pass
            raise
        if self.browser.contexts:
            self.context = self.browser.contexts[0]
        else:
            self.context = self.browser.new_context()
        # Teto para TODAS as operações seguintes (vale para o contexto inteiro:
        # qualquer page criada depois herda). É o que garante que uma tela travada
        # vire exceção tratável em ~45s em vez de silêncio até o Watchdog.
        try:
            self.context.set_default_timeout(DEFAULT_ACTION_TIMEOUT_MS)
            self.context.set_default_navigation_timeout(DEFAULT_NAV_TIMEOUT_MS)
        except Exception:
            pass
        if self.context.pages:
            self._current_page = self.context.pages[0]
        else:
            self._current_page = self.context.new_page()
        self._current_frame = None
        self.switch_to = _SwitchTo(self)

    def _target(self):
        return self._current_frame or self._current_page

    def _page_handle(self, page) -> str:
        return f'pw-{id(page)}'

    def _switch_to_page(self, handle: str):
        for page in self.context.pages:
            if self._page_handle(page) == handle:
                self._current_page = page
                self._current_frame = None
                trazer_para_frente(page)
                return
        raise NoSuchElementException(f'Aba não encontrada: {handle}')

    def is_alive(self) -> bool:
        """True se o navegador AINDA está aberto/conectado. Retorna False quando o
        usuário FECHA o navegador na mão (a conexão CDP cai) ou não há mais
        nenhuma aba — assim o bot detecta na hora e aborta o perfil como
        Erro/Falha, em vez de ficar preso em 'Processando' com um navegador que
        nem está mais aberto."""
        try:
            if not self.browser.is_connected():
                return False
        except Exception:
            return False
        try:
            # Sem nenhuma aba/página => navegador efetivamente fechado.
            return len(self.context.pages) > 0
        except Exception:
            return False

    @property
    def window_handles(self) -> List[str]:
        return [self._page_handle(page) for page in self.context.pages]

    @property
    def current_window_handle(self) -> str:
        return self._page_handle(self._current_page)

    def open_new_tab(self, url: str = 'about:blank', switch: bool = True, wait_networkidle: bool = False):
        page = self.context.new_page()
        trazer_para_frente(page)
        if switch:
            self._current_page = page
            self._current_frame = None
        target_url = (url or '').strip() or 'about:blank'
        try:
            page.goto(target_url, wait_until='domcontentloaded', timeout=NAV_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.warning("[nav] open_new_tab: goto >%.0fs (internet lenta) — seguindo.", NAV_TIMEOUT_MS / 1000)
        if wait_networkidle:
            try:
                page.wait_for_load_state('networkidle', timeout=8000)
            except Exception:
                pass
        return self._page_handle(page)

    @property
    def current_url(self):
        return self._current_page.url

    @property
    def page_source(self):
        try:
            return self._target().content()
        except Exception:
            return self._current_page.content()

    def get(self, url):
        self._current_frame = None
        # Internet LENTA: NÃO falha se o 'domcontentloaded' passar do timeout — a
        # página ainda está carregando (não é erro). As esperas seguintes aguardam
        # ficar pronta. Erro REAL (navegador fechado/queda) levanta outra exceção.
        try:
            self._current_page.goto(url, wait_until='domcontentloaded', timeout=NAV_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.warning("[nav] get: goto >%.0fs (internet lenta) — seguindo; a espera de página cuida.", NAV_TIMEOUT_MS / 1000)
        try:
            self._current_page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            pass
        self._guardiao_sessao(url)

    def _guardiao_sessao(self, destino=None):
        """GUARDIÃO DE SESSÃO automático: se a navegação caiu em QUALQUER tela de login
        do Facebook/Business (perfil deslogado no meio do fluxo), re-loga e volta ao
        destino. No-op sem credenciais registradas (session_guard.setar_credenciais /
        vincular_perfil) e durante o próprio re-login (_sg_busy)."""
        if not getattr(self, '_sg_auto', False) or getattr(self, '_sg_busy', False):
            return
        try:
            from server import session_guard as _sg
            _sg.auto_restaurar(self, destino=destino)
        except Exception as exc:
            logger.debug('[nav] guardião de sessão ignorado: %s', exc)

    # ── Native Playwright API (usada por verificacao_bm.py) ──

    def goto(self, url, **kwargs):
        """Playwright-native navigation (alias para get com mais controle)."""
        self._current_frame = None
        kwargs.setdefault('wait_until', 'domcontentloaded')
        kwargs.setdefault('timeout', NAV_TIMEOUT_MS)
        try:
            self._current_page.goto(url, **kwargs)
        except PlaywrightTimeoutError:
            logger.warning("[nav] goto: >%.0fs (internet lenta) — seguindo.", kwargs.get('timeout', NAV_TIMEOUT_MS) / 1000)
        try:
            self._current_page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            pass
        self._guardiao_sessao(url)

    def query_selector(self, selector):
        """Retorna ElementHandle nativo do Playwright (ou None)."""
        return self._target().query_selector(selector)

    def query_selector_all(self, selector):
        """Retorna lista de ElementHandle nativos do Playwright."""
        return self._target().query_selector_all(selector)

    def wait_for_selector(self, selector, **kwargs):
        """Espera por um seletor e retorna ElementHandle nativo."""
        return self._target().wait_for_selector(selector, **kwargs)

    def text_content(self, selector):
        """Retorna text_content de um seletor (Playwright-native)."""
        try:
            el = self._target().query_selector(selector)
            if el:
                return el.text_content()
        except Exception:
            pass
        return None

    def wait_for_load_state(self, state='load', **kwargs):
        """Espera por um estado de carregamento da página."""
        self._current_page.wait_for_load_state(state, **kwargs)

    def evaluate_page(self, expression, arg=None):
        """Executa evaluate direto na page (Playwright-native)."""
        if arg is not None:
            return self._current_page.evaluate(expression, arg)
        return self._current_page.evaluate(expression)

    def locator(self, selector):
        """Retorna Locator nativo do Playwright."""
        return self._target().locator(selector)

    @property
    def mouse(self):
        """Acesso ao mouse nativo do Playwright."""
        return self._current_page.mouse

    @property
    def keyboard(self):
        """Acesso ao keyboard nativo do Playwright."""
        return self._current_page.keyboard

    def refresh(self):
        self._current_frame = None
        try:
            self._current_page.reload(wait_until='domcontentloaded', timeout=NAV_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.warning("[nav] refresh: reload >%.0fs (internet lenta) — seguindo.", NAV_TIMEOUT_MS / 1000)
        self._guardiao_sessao()

    def close(self):
        page = self._current_page
        try:
            page.close()
        except Exception:
            pass
        pages = self.context.pages
        if pages:
            self._current_page = pages[0]
        self._current_frame = None

    def quit(self):
        self._current_frame = None
        try:
            self._playwright.stop()
        except Exception:
            pass

    def find_elements(self, by, value):
        target = self._target()
        selector = _selector(by, value)
        try:
            if by == By.XPATH:
                handles = target.locator(selector).element_handles()
            else:
                handles = target.query_selector_all(selector)
            return [PlaywrightElementWrapper(self, h) for h in handles]
        except Exception:
            return []

    def find_element(self, by, value):
        els = self.find_elements(by, value)
        if not els:
            raise NoSuchElementException(f'Elemento não encontrado: {by}={value}')
        return els[0]

    def execute_script(self, script: str, *args):
        target = self._target()
        payload = []
        for arg in args:
            if isinstance(arg, PlaywrightElementWrapper):
                payload.append(arg._handle)
            else:
                payload.append(arg)
        expr = f"(function(__args){{ var arguments = __args; {script}\n }})"
        try:
            handle = target.evaluate_handle(expr, payload)
            return self._convert_result(handle)
        except PlaywrightTimeoutError as exc:
            raise TimeoutException(str(exc))
        except Exception as exc:
            raise WebDriverException(str(exc))

    def _convert_result(self, handle):
        if handle is None:
            return None
        try:
            elem = handle.as_element()
            if elem:
                return PlaywrightElementWrapper(self, elem)
        except Exception:
            pass
        try:
            return handle.json_value()
        except Exception:
            pass
        try:
            props = handle.get_properties()
        except Exception:
            return None
        if not props:
            return None
        try:
            is_array = bool(handle.evaluate('obj => Array.isArray(obj)'))
        except Exception:
            is_array = False
        if is_array:
            items = []
            for key, value in props.items():
                if str(key).isdigit():
                    items.append((int(key), self._convert_result(value)))
            items.sort(key=lambda x: x[0])
            return [item for _, item in items]
        result = {}
        for key, value in props.items():
            if key in ('__proto__',):
                continue
            result[key] = self._convert_result(value)
        return result


def conectar_playwright(debugging_address: str, webdriver_path: Optional[str] = None):
    del webdriver_path
    try:
        return PlaywrightDriver(debugging_address)
    except Exception as exc:
        logger.error('[Playwright] Falha ao conectar via CDP %s: %s', debugging_address, exc)
        return None
