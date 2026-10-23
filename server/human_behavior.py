#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Human Behavior Simulator - Anti-Detecção v2026
===============================================
Simula comportamento humano 100% realista para burlar detecção de bots do Facebook.

CARACTERÍSTICAS:
- Movimentos de mouse com Bézier curves (não lineares)
- Delays variáveis e naturais (Gaussian distribution)
- Scroll aleatório antes de clicar
- Hover effects realistas
- Digitação com velocidade humana variável
- Comportamento de navegação natural
- User-Agent rotativo
- Headers realistas
- Fingerprint spoofing
"""

import time
import random
import math
import logging
from typing import Tuple, List, Optional
# Suporte a Selenium (legado) e Playwright (atual)
try:
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys
except ImportError:
    ActionChains = None
    Keys = None

logger = logging.getLogger(__name__)


# ============================================================================
# DELAYS HUMANIZADOS - Distribuição Gaussiana
# ============================================================================

class HumanDelays:
    """Delays com distribuição natural (Gaussian) para parecer humano."""
    
    @staticmethod
    def micro_delay(min_ms=10, max_ms=50):
        """Delay entre teclas (10-50ms)."""
        delay = random.gauss((min_ms + max_ms) / 2, (max_ms - min_ms) / 4)
        delay = max(min_ms, min(max_ms, delay)) / 1000
        time.sleep(delay)
    
    @staticmethod
    def short_delay(min_s=0.1, max_s=0.5):
        """Delay curto para ações rápidas (100-500ms)."""
        delay = random.gauss((min_s + max_s) / 2, (max_s - min_s) / 4)
        delay = max(min_s, min(max_s, delay))
        time.sleep(delay)
    
    @staticmethod
    def medium_delay(min_s=0.5, max_s=1.5):
        """Delay médio para transições (500ms-1.5s)."""
        delay = random.gauss((min_s + max_s) / 2, (max_s - min_s) / 4)
        delay = max(min_s, min(max_s, delay))
        time.sleep(delay)
    
    @staticmethod
    def long_delay(min_s=1.5, max_s=3.5):
        """Delay longo para carregamento de página (1.5-3.5s)."""
        delay = random.gauss((min_s + max_s) / 2, (max_s - min_s) / 4)
        delay = max(min_s, min(max_s, delay))
        time.sleep(delay)
    
    @staticmethod
    def reading_delay(min_s=2.0, max_s=5.0):
        """Delay para "ler" conteúdo (2-5s)."""
        delay = random.gauss((min_s + max_s) / 2, (max_s - min_s) / 4)
        delay = max(min_s, min(max_s, delay))
        time.sleep(delay)
    
    @staticmethod
    def thinking_delay(min_s=0.5, max_s=2.0):
        """Delay para "pensar" antes de agir (500ms-2s)."""
        delay = random.gauss((min_s + max_s) / 2, (max_s - min_s) / 4)
        delay = max(min_s, min(max_s, delay))
        time.sleep(delay)


# ============================================================================
# MOVIMENTOS DE MOUSE HUMANIZADOS - Bézier Curves
# ============================================================================

class HumanMouseMovement:
    """Movimentos de mouse com curvas Bézier (não lineares)."""
    
    @staticmethod
    def bezier_curve(p0: Tuple[int, int], p3: Tuple[int, int], 
                     p1: Optional[Tuple[int, int]] = None,
                     p2: Optional[Tuple[int, int]] = None,
                     steps: int = 20) -> List[Tuple[int, int]]:
        """
        Gera pontos de uma curva Bézier cúbica.
        
        Args:
            p0: Ponto inicial
            p3: Ponto final
            p1: Ponto de controle 1 (aleatório se None)
            p2: Ponto de controle 2 (aleatório se None)
            steps: Número de passos
        
        Returns:
            Lista de pontos (x, y)
        """
        if p1 is None:
            p1 = (
                p0[0] + random.randint(-100, 100),
                p0[1] + random.randint(-100, 100)
            )
        if p2 is None:
            p2 = (
                p3[0] + random.randint(-100, 100),
                p3[1] + random.randint(-100, 100)
            )
        
        points = []
        for i in range(steps + 1):
            t = i / steps
            # Fórmula de Bézier cúbica
            x = (1-t)**3 * p0[0] + 3*(1-t)**2*t * p1[0] + 3*(1-t)*t**2 * p2[0] + t**3 * p3[0]
            y = (1-t)**3 * p0[1] + 3*(1-t)**2*t * p1[1] + 3*(1-t)*t**2 * p2[1] + t**3 * p3[1]
            points.append((int(x), int(y)))
        
        return points
    
    @staticmethod
    def move_to_element(driver, element, actions=None):
        """
        Move mouse para elemento com curva Bézier. Suporta Selenium e Playwright.
        """
        try:
            # Tentar obter posição atual do mouse injetada ou aleatória
            current_pos = (random.randint(0, 800), random.randint(0, 600))
            try:
                if hasattr(driver, 'evaluate_page'): # Playwright wrapper
                    pos = driver.evaluate_page('() => ({x: window._mouseX || 0, y: window._mouseY || 0})')
                    if pos.get('x'): current_pos = (pos['x'], pos['y'])
                elif hasattr(driver, 'execute_script'): # Selenium
                    pos = driver.execute_script('return {x: window._mouseX || 0, y: window._mouseY || 0}')
                    if pos.get('x'): current_pos = (pos['x'], pos['y'])
            except: pass

            # Obter posição do elemento
            target_pos = (0, 0)
            if hasattr(element, 'bounding_box'): # Playwright
                box = element.bounding_box()
                if box:
                    target_pos = (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            elif hasattr(element, 'location'): # Selenium
                loc = element.location
                size = element.size
                target_pos = (loc['x'] + size['width'] / 2, loc['y'] + size['height'] / 2)

            # Gerar curva Bézier
            points = HumanMouseMovement.bezier_curve(current_pos, target_pos, steps=random.randint(15, 25))
            
            # Mover mouse
            for point in points:
                if hasattr(driver, 'mouse'): # Playwright native
                    driver.mouse.move(point[0], point[1])
                elif hasattr(driver, 'move_mouse'): # Playwright wrapper
                    driver.mouse.move(point[0], point[1])
                elif actions: # Selenium
                    actions.move_by_offset(point[0] - current_pos[0], point[1] - current_pos[1])
                
                current_pos = point
                time.sleep(random.uniform(0.005, 0.015))
            
            # Atualizar posição global
            try:
                script = f'window._mouseX = {current_pos[0]}; window._mouseY = {current_pos[1]};'
                if hasattr(driver, 'evaluate_page'): driver.evaluate_page(f'() => {{ {script} }}')
                elif hasattr(driver, 'execute_script'): driver.execute_script(script)
            except: pass

            return actions
        except Exception as e:
            logger.warning(f"Erro ao mover mouse com Bézier: {e}")
            if actions and hasattr(actions, 'move_to_element'):
                actions.move_to_element(element)
            return actions


# ============================================================================
# COMPORTAMENTO DE DIGITAÇÃO HUMANIZADO
# ============================================================================

class HumanTyping:
    """Digitação com velocidade e padrões humanos."""
    
    @staticmethod
    def type_text(element, text: str, driver=None):
        """
        Digita texto com velocidade humana variável. Suporta Selenium e Playwright.
        """
        try:
            # Focar e limpar
            if hasattr(element, 'click'): element.click()
            HumanDelays.short_delay(0.2, 0.4)
            
            # Limpar campo (método robusto para React)
            try:
                if hasattr(element, 'evaluate'): # Playwright
                    element.evaluate("el => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); }")
                elif driver and hasattr(driver, 'execute_script'): # Selenium
                    driver.execute_script("arguments[0].value = '';", element)
            except: pass
            
            # Digitar com velocidade variável
            for i, char in enumerate(text):
                # Delays baseados no tipo de caractere
                delay_ms = random.randint(30, 90)
                if char.isupper(): delay_ms += random.randint(20, 50) # Shift demora mais
                if char in ".,!?;:": delay_ms += random.randint(40, 100) # Pontuação
                
                if hasattr(element, 'type'): # Playwright native
                    element.type(char, delay=delay_ms)
                elif hasattr(driver, 'keyboard') and hasattr(driver.keyboard, 'type'): # Playwright wrapper
                    driver.keyboard.type(char, delay=delay_ms)
                else: # Selenium fallback
                    element.send_keys(char)
                    time.sleep(delay_ms / 1000)
                
                # Pausas naturais (simulando pensamento ou erro/correção)
                if random.random() < 0.03: # 3% de chance de pausa longa
                    HumanDelays.thinking_delay(0.5, 1.2)
                elif i > 0 and i % random.randint(5, 10) == 0: # Pausa a cada 5-10 chars
                    HumanDelays.short_delay(0.1, 0.3)
            
            HumanDelays.short_delay(0.3, 0.6)
            logger.info(f"Texto digitado com sucesso: {text[:15]}...")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao digitar texto: {e}")
            return False


# ============================================================================
# COMPORTAMENTO DE NAVEGAÇÃO HUMANIZADO
# ============================================================================

class HumanNavigation:
    """Comportamento natural de navegação no site."""
    
    @staticmethod
    def random_scroll(driver, min_scroll=100, max_scroll=500):
        """
        Scroll aleatório na página (simula leitura).
        
        Args:
            driver: WebDriver
            min_scroll: Scroll mínimo em pixels
            max_scroll: Scroll máximo em pixels
        """
        try:
            scroll_amount = random.randint(min_scroll, max_scroll)
            direction = random.choice([-1, 1])  # Para cima ou para baixo
            
            driver.execute_script(f"window.scrollBy(0, {scroll_amount * direction});")
            HumanDelays.reading_delay(0.5, 2.0)
            logger.info(f"Scroll aleatório: {scroll_amount * direction}px")
            
        except Exception as e:
            logger.warning(f"Erro ao fazer scroll: {e}")
    
    @staticmethod
    def hover_random_elements(driver, count: int = 3):
        """
        Faz hover em elementos aleatórios (simula exploração).
        
        Args:
            driver: WebDriver
            count: Número de elementos para hover
        """
        try:
            elements = driver.find_elements("tag name", "button")
            elements += driver.find_elements("tag name", "a")
            
            if elements:
                selected = random.sample(elements, min(count, len(elements)))
                actions = ActionChains(driver)
                
                for element in selected:
                    try:
                        actions.move_to_element(element)
                        HumanDelays.short_delay(0.2, 0.5)
                    except:
                        pass
                
                actions.perform()
                logger.info(f"Hover em {len(selected)} elementos aleatórios")
        
        except Exception as e:
            logger.warning(f"Erro ao fazer hover: {e}")
    
    @staticmethod
    def click_human(driver, element):
        """
        Clica em um elemento com comportamento humano (scroll + move + click).
        """
        try:
            # 1. Scroll suave até o elemento
            if hasattr(element, 'scroll_into_view_if_needed'):
                element.scroll_into_view_if_needed()
            elif hasattr(driver, 'execute_script'):
                driver.execute_script("arguments[0].scrollIntoView({behavior:'smooth', block:'center'});", element)
            
            HumanDelays.short_delay(0.3, 0.6)

            # 2. Mover mouse até o elemento com curva Bézier
            HumanMouseMovement.move_to_element(driver, element)
            HumanDelays.micro_delay(50, 150)

            # 3. Clicar
            if hasattr(element, 'click'):
                element.click()
            
            HumanDelays.short_delay(0.2, 0.5)
            return True
        except Exception as e:
            logger.warning(f"Erro no clique humano: {e}")
            try:
                element.click()
                return True
            except:
                return False

    @staticmethod
    def random_clicks_before_action(driver, count: int = 1):
        """
        Clica em elementos aleatórios antes da ação principal.
        
        Args:
            driver: WebDriver
            count: Número de cliques aleatórios
        """
        try:
            for _ in range(count):
                elements = driver.find_elements("tag name", "span")
                if elements:
                    element = random.choice(elements)
                    try:
                        actions = ActionChains(driver)
                        actions.move_to_element(element)
                        HumanDelays.short_delay(0.1, 0.3)
                        actions.click()
                        actions.perform()
                        HumanDelays.medium_delay(0.3, 0.8)
                    except:
                        pass
        
        except Exception as e:
            logger.warning(f"Erro ao fazer cliques aleatórios: {e}")


# ============================================================================
# USER-AGENT E HEADERS REALISTAS
# ============================================================================

class HumanBrowserProfile:
    """Perfil de navegador realista para burlar detecção."""
    
    USER_AGENTS = [
        # Chrome Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        # Edge Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        # Firefox Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]
    
    @staticmethod
    def get_random_user_agent() -> str:
        """Retorna User-Agent aleatório."""
        return random.choice(HumanBrowserProfile.USER_AGENTS)
    
    @staticmethod
    def get_realistic_headers() -> dict:
        """Retorna headers realistas."""
        return {
            "User-Agent": HumanBrowserProfile.get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
    
    @staticmethod
    def inject_stealth_js(driver):
        """
        Injeta JavaScript para mascarar automação.
        
        Args:
            driver: WebDriver
        """
        stealth_js = """
        // Mascarar webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false,
        });
        
        // Mascarar plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        
        // Mascarar languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['pt-BR', 'pt', 'en-US', 'en'],
        });
        
        // Mascarar chrome
        window.chrome = {
            runtime: {}
        };
        
        // Mascarar permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // Mascarar timezone
        Date.prototype.getTimezoneOffset = function() {
            return -180; // GMT-3 (Brasil)
        };
        """
        
        try:
            driver.execute_script(stealth_js)
            logger.info("JavaScript de stealth injetado com sucesso")
        except Exception as e:
            logger.warning(f"Erro ao injetar stealth JS: {e}")


# ============================================================================
# DETECÇÃO DE CAPTCHA E VERIFICAÇÕES
# ============================================================================

class CaptchaDetection:
    """Detecta e identifica CAPTCHAs e verificações."""
    
    @staticmethod
    def detect_captcha(driver) -> bool:
        """
        Detecta se há CAPTCHA na página.
        
        Args:
            driver: WebDriver
        
        Returns:
            True se CAPTCHA detectado
        """
        captcha_indicators = [
            "recaptcha",
            "captcha",
            "hcaptcha",
            "challenge",
            "verify",
            "security_check",
        ]
        
        try:
            page_source = driver.page_source.lower()
            for indicator in captcha_indicators:
                if indicator in page_source:
                    logger.warning(f"CAPTCHA detectado: {indicator}")
                    return True
        except:
            pass
        
        return False
    
    @staticmethod
    def detect_security_check(driver) -> bool:
        """
        Detecta verificações de segurança do Facebook.
        
        Args:
            driver: WebDriver
        
        Returns:
            True se verificação detectada
        """
        security_indicators = [
            "security_check",
            "unusual_activity",
            "confirm_identity",
            "verify_account",
            "suspicious",
        ]
        
        try:
            page_source = driver.page_source.lower()
            for indicator in security_indicators:
                if indicator in page_source:
                    logger.warning(f"Verificação de segurança detectada: {indicator}")
                    return True
        except:
            pass
        
        return False
    
    @staticmethod
    def detect_disabled_account(driver) -> bool:
        """
        Detecta se conta foi desabilitada.
        
        Args:
            driver: WebDriver
        
        Returns:
            True se conta desabilitada
        """
        disabled_indicators = [
            "disabled",
            "deactivated",
            "suspended",
            "violat",
            "not available",
        ]
        
        try:
            page_source = driver.page_source.lower()
            for indicator in disabled_indicators:
                if indicator in page_source:
                    logger.error(f"Conta desabilitada detectada: {indicator}")
                    return True
        except:
            pass
        
        return False


# ============================================================================
# INTEGRAÇÃO COMPLETA
# ============================================================================

class HumanBehaviorSimulator:
    """Simulador completo de comportamento humano."""
    
    def __init__(self, driver):
        """
        Inicializa simulador.
        
        Args:
            driver: WebDriver
        """
        self.driver = driver
        self.delays = HumanDelays()
        self.mouse = HumanMouseMovement()
        self.typing = HumanTyping()
        self.navigation = HumanNavigation()
        self.profile = HumanBrowserProfile()
        self.captcha = CaptchaDetection()
        
        # Injetar stealth JS
        self.profile.inject_stealth_js(driver)
    
    def pre_action_behavior(self):
        """Comportamento antes de uma ação (scroll, hover, etc)."""
        if random.random() < 0.3:  # 30% de chance
            self.navigation.random_scroll(self.driver)
        
        if random.random() < 0.2:  # 20% de chance
            self.navigation.hover_random_elements(self.driver, count=2)
        
        self.delays.thinking_delay(0.3, 1.0)
    
    def post_action_behavior(self):
        """Comportamento após uma ação."""
        self.delays.medium_delay(0.5, 1.5)
        
        if random.random() < 0.15:  # 15% de chance
            self.navigation.random_scroll(self.driver)
    
    def check_security(self) -> bool:
        """
        Verifica se há problemas de segurança.
        
        Returns:
            True se seguro, False se detectado problema
        """
        if self.captcha.detect_captcha(self.driver):
            logger.error("CAPTCHA detectado - Abortar")
            return False
        
        if self.captcha.detect_security_check(self.driver):
            logger.error("Verificação de segurança detectada - Abortar")
            return False
        
        if self.captcha.detect_disabled_account(self.driver):
            logger.error("Conta desabilitada - Abortar")
            return False
        
        return True
