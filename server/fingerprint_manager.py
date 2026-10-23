#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fingerprint Manager - Gerador de Fingerprints Únicos v2026
===========================================================
Cria fingerprints únicos para cada perfil com:
- PT-BR como idioma padrão
- São Paulo como timezone (GMT-3)
- Dados realistas e variados
"""

import random
import string
import uuid
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class FingerprintGenerator:
    """Gera fingerprints únicos e realistas para cada perfil."""
    
    # Resoluções de tela comuns
    SCREEN_RESOLUTIONS = [
        (1920, 1080),
        (1366, 768),
        (1440, 900),
        (1536, 864),
        (1680, 1050),
        (2560, 1440),
        (1024, 768),
        (1280, 720),
    ]
    
    # Profundidades de cor
    COLOR_DEPTHS = [24, 32]
    
    # Navegadores e versões
    BROWSERS = [
        {
            "name": "Chrome",
            "versions": ["120.0.0.0", "119.0.0.0", "118.0.0.0", "117.0.0.0"],
            "engine": "Blink"
        },
        {
            "name": "Edge",
            "versions": ["120.0.0.0", "119.0.0.0", "118.0.0.0"],
            "engine": "Blink"
        },
        {
            "name": "Firefox",
            "versions": ["121.0", "120.0", "119.0"],
            "engine": "Gecko"
        },
    ]
    
    # Sistemas operacionais
    OS_INFO = [
        {"name": "Windows 10", "version": "10.0"},
        {"name": "Windows 11", "version": "10.0"},
    ]
    
    # GPUs comuns
    GPUS = [
        "ANGLE (Intel HD Graphics 630)",
        "ANGLE (NVIDIA GeForce GTX 1050)",
        "ANGLE (AMD Radeon RX 580)",
        "ANGLE (Intel UHD Graphics 630)",
        "ANGLE (NVIDIA GeForce RTX 3060)",
    ]
    
    # Plugins simulados
    PLUGINS = [
        "Chrome PDF Plugin",
        "Chrome PDF Viewer",
        "Native Client Executable",
        "Shockwave Flash",
    ]
    
    @staticmethod
    def generate_unique_fingerprint(profile_id: str) -> Dict:
        """
        Gera fingerprint único para um perfil.
        
        Args:
            profile_id: ID do perfil (para seed determinístico)
        
        Returns:
            Dicionário com fingerprint completo
        """
        # Seed determinístico baseado no profile_id
        random.seed(hash(profile_id) % (2**32))
        
        browser = random.choice(FingerprintGenerator.BROWSERS)
        os_info = random.choice(FingerprintGenerator.OS_INFO)
        resolution = random.choice(FingerprintGenerator.SCREEN_RESOLUTIONS)
        
        fingerprint = {
            # Identificadores únicos
            "fingerprint_id": str(uuid.uuid4()),
            "profile_id": profile_id,
            "created_at": datetime.now().isoformat(),
            
            # Navegador
            "browser": {
                "name": browser["name"],
                "version": random.choice(browser["versions"]),
                "engine": browser["engine"],
                "user_agent": FingerprintGenerator._generate_user_agent(browser, os_info),
            },
            
            # Sistema Operacional
            "os": {
                "name": os_info["name"],
                "version": os_info["version"],
                "platform": "Win32",
            },
            
            # Tela
            "screen": {
                "width": resolution[0],
                "height": resolution[1],
                "color_depth": random.choice(FingerprintGenerator.COLOR_DEPTHS),
                "pixel_depth": random.choice(FingerprintGenerator.COLOR_DEPTHS),
                "device_pixel_ratio": random.choice([1, 1.25, 1.5, 2]),
            },
            
            # Idioma e Localização (SEMPRE PT-BR E SÃO PAULO)
            "language": {
                "language": "pt-BR",  # Português Brasil
                "languages": ["pt-BR", "pt", "en-US", "en"],
                "timezone": "America/Sao_Paulo",  # São Paulo
                "timezone_offset": -180,  # GMT-3 (São Paulo)
            },
            
            # Hardware
            "hardware": {
                "cores": random.choice([2, 4, 6, 8, 12, 16]),
                "memory": random.choice([4, 8, 16, 32]),
                "gpu": random.choice(FingerprintGenerator.GPUS),
            },
            
            # Plugins
            "plugins": FingerprintGenerator._generate_plugins(),
            
            # Canvas fingerprint
            "canvas": {
                "fingerprint": FingerprintGenerator._generate_canvas_fingerprint(),
                "webgl": FingerprintGenerator._generate_webgl_fingerprint(),
            },
            
            # Cookies e Storage
            "storage": {
                "local_storage": True,
                "session_storage": True,
                "indexed_db": True,
                "open_database": True,
            },
            
            # Permissões
            "permissions": {
                "notifications": "default",
                "geolocation": "prompt",
                "camera": "prompt",
                "microphone": "prompt",
            },
            
            # Features
            "features": {
                "webgl": True,
                "webrtc": True,
                "service_worker": True,
                "payment_request": True,
                "credential_management": True,
            },
        }
        
        logger.info(f"Fingerprint único gerado para perfil {profile_id}")
        return fingerprint
    
    @staticmethod
    def _generate_user_agent(browser: Dict, os_info: Dict) -> str:
        """Gera User-Agent realista."""
        if browser["name"] == "Chrome":
            return f"Mozilla/5.0 ({os_info['name']}; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser['version']} Safari/537.36"
        elif browser["name"] == "Edge":
            return f"Mozilla/5.0 ({os_info['name']}; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser['version']} Safari/537.36 Edg/{browser['version']}"
        elif browser["name"] == "Firefox":
            return f"Mozilla/5.0 ({os_info['name']}; Win64; x64; rv:{browser['version']}) Gecko/20100101 Firefox/{browser['version']}"
        return ""
    
    @staticmethod
    def _generate_plugins() -> List[Dict]:
        """Gera lista de plugins simulados."""
        plugins = []
        for plugin in random.sample(FingerprintGenerator.PLUGINS, random.randint(2, 4)):
            plugins.append({
                "name": plugin,
                "description": f"{plugin} plugin",
                "version": f"{random.randint(1, 10)}.{random.randint(0, 9)}.{random.randint(0, 9)}",
            })
        return plugins
    
    @staticmethod
    def _generate_canvas_fingerprint() -> str:
        """Gera canvas fingerprint único."""
        # Simula hash do canvas
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(32))
    
    @staticmethod
    def _generate_webgl_fingerprint() -> Dict:
        """Gera WebGL fingerprint."""
        return {
            "vendor": random.choice(["Google Inc.", "NVIDIA Corporation", "AMD"]),
            "renderer": random.choice([
                "ANGLE (Intel HD Graphics 630)",
                "ANGLE (NVIDIA GeForce GTX 1050)",
                "ANGLE (AMD Radeon RX 580)",
            ]),
            "version": "WebGL 1.0",
            "shading_language_version": "WebGL GLSL ES 1.0",
        }
    
    @staticmethod
    def get_pt_br_timezone_config() -> Dict:
        """
        Retorna configuração de timezone para São Paulo (PT-BR).
        
        Returns:
            Dicionário com configurações de timezone
        """
        return {
            "timezone": "America/Sao_Paulo",
            "timezone_offset": -180,  # GMT-3
            "timezone_name": "Brasília Time",
            "timezone_abbreviation": "BRT",
            "is_dst": False,
            "language": "pt-BR",
            "locale": "pt_BR",
            "date_format": "dd/MM/yyyy",
            "time_format": "HH:mm:ss",
            "decimal_separator": ",",
            "thousands_separator": ".",
        }
    
    @staticmethod
    def inject_fingerprint_js(driver, fingerprint: Dict) -> bool:
        """
        Injeta fingerprint no navegador via JavaScript.
        
        Args:
            driver: WebDriver
            fingerprint: Dicionário com fingerprint
        
        Returns:
            True se injetado com sucesso
        """
        try:
            # Injetar configurações de timezone
            tz_config = FingerprintGenerator.get_pt_br_timezone_config()
            
            js_code = f"""
            // Injetar fingerprint
            window.__FINGERPRINT__ = {json.dumps(fingerprint)};
            
            // Mascarar timezone (São Paulo - GMT-3)
            Date.prototype.getTimezoneOffset = function() {{
                return {tz_config['timezone_offset']};
            }};
            
            // Mascarar idioma (PT-BR)
            Object.defineProperty(navigator, 'language', {{
                get: () => 'pt-BR'
            }});
            
            Object.defineProperty(navigator, 'languages', {{
                get: () => ['pt-BR', 'pt', 'en-US', 'en']
            }});
            
            // Mascarar resolução de tela
            Object.defineProperty(window, 'screen', {{
                get: () => ({{
                    width: {fingerprint['screen']['width']},
                    height: {fingerprint['screen']['height']},
                    colorDepth: {fingerprint['screen']['color_depth']},
                    pixelDepth: {fingerprint['screen']['pixel_depth']},
                    devicePixelRatio: {fingerprint['screen']['device_pixel_ratio']},
                }})
            }});
            
            // Mascarar hardware
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {fingerprint['hardware']['cores']}
            }});
            
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => {fingerprint['hardware']['memory']}
            }});
            
            // Mascarar plugins
            Object.defineProperty(navigator, 'plugins', {{
                get: () => [1, 2, 3, 4, 5]
            }});
            
            // Mascarar WebGL
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) {{
                    return '{fingerprint['canvas']['webgl']['vendor']}';
                }}
                if (parameter === 37446) {{
                    return '{fingerprint['canvas']['webgl']['renderer']}';
                }}
                return getParameter.call(this, parameter);
            }};
            """
            
            driver.execute_script(js_code)
            logger.info(f"Fingerprint injetado com sucesso (PT-BR, São Paulo)")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao injetar fingerprint: {e}")
            return False


class FingerprintCache:
    """Cache de fingerprints para reutilização."""
    
    def __init__(self):
        """Inicializa cache."""
        self.cache: Dict[str, Dict] = {}
    
    def get_or_create(self, profile_id: str) -> Dict:
        """
        Obtém fingerprint do cache ou cria novo.
        
        Args:
            profile_id: ID do perfil
        
        Returns:
            Fingerprint do perfil
        """
        if profile_id not in self.cache:
            self.cache[profile_id] = FingerprintGenerator.generate_unique_fingerprint(profile_id)
            logger.info(f"Fingerprint criado e cacheado para {profile_id}")
        else:
            logger.info(f"Fingerprint recuperado do cache para {profile_id}")
        
        return self.cache[profile_id]
    
    def clear(self):
        """Limpa cache."""
        self.cache.clear()
        logger.info("Cache de fingerprints limpo")
    
    def save_to_file(self, filepath: str):
        """Salva cache em arquivo JSON."""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
            logger.info(f"Cache de fingerprints salvo em {filepath}")
        except Exception as e:
            logger.error(f"Erro ao salvar cache: {e}")
    
    def load_from_file(self, filepath: str):
        """Carrega cache de arquivo JSON."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.cache = json.load(f)
            logger.info(f"Cache de fingerprints carregado de {filepath}")
        except Exception as e:
            logger.warning(f"Erro ao carregar cache: {e}")


# Instância global de cache
_fingerprint_cache = FingerprintCache()


def get_fingerprint(profile_id: str) -> Dict:
    """
    Obtém fingerprint único para um perfil.
    
    Args:
        profile_id: ID do perfil
    
    Returns:
        Fingerprint do perfil
    """
    return _fingerprint_cache.get_or_create(profile_id)


def inject_fingerprint(driver, profile_id: str) -> bool:
    """
    Injeta fingerprint no navegador.
    
    Args:
        driver: WebDriver
        profile_id: ID do perfil
    
    Returns:
        True se injetado com sucesso
    """
    fingerprint = get_fingerprint(profile_id)
    return FingerprintGenerator.inject_fingerprint_js(driver, fingerprint)
