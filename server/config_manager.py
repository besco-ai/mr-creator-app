import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger("GS_BM_Creator.ConfigManager")

class ConfigManager:
    """
    Gerenciador de configurações dinâmicas para o GS_FB_BM_Creator.
    Permite carregar configurações globais e específicas por perfil.
    """
    
    DEFAULT_CONFIG = {
        "modo": "rapido", # Opções: rapido, seguro, humano
        "timeouts": {
            "padrao": 10,
            "login": 30,
            "2fa": 5,
            "home": 15,
            "bm_carregamento": 8
        },
        "warmup": {
            "ativo": True,
            "feed_segundos": [3, 8],
            "interacoes_max": 2
        },
        "retries": {
            "2fa_max": 2,
            "bm_max": 2,
            "element_max": 3
        },
        "anti_deteccao": {
            "delay_digitacao": [0.05, 0.15],
            "delay_clique": [0.2, 0.5]
        }
    }
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self.global_config_path = os.path.join(config_dir, "automacao_config.json")
        self._ensure_config_dir()
        self.global_config = self._load_global_config()
        
    def _ensure_config_dir(self):
        """Garante que o diretório de configuração existe."""
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
            logger.info(f"[ConfigManager] Diretório {self.config_dir} criado.")
            
    def _load_global_config(self) -> Dict[str, Any]:
        """Carrega a configuração global ou cria a padrão se não existir."""
        if os.path.exists(self.global_config_path):
            try:
                with open(self.global_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Mescla com default para garantir que todas as chaves existam
                    return self._merge_configs(self.DEFAULT_CONFIG, config)
            except Exception as e:
                logger.error(f"[ConfigManager] Erro ao carregar {self.global_config_path}: {e}")
                return self.DEFAULT_CONFIG.copy()
        else:
            self.save_global_config(self.DEFAULT_CONFIG)
            return self.DEFAULT_CONFIG.copy()
            
    def save_global_config(self, config: Dict[str, Any]):
        """Salva a configuração global."""
        try:
            with open(self.global_config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            self.global_config = config
            logger.info(f"[ConfigManager] Configuração global salva em {self.global_config_path}")
        except Exception as e:
            logger.error(f"[ConfigManager] Erro ao salvar config global: {e}")
            
    def get_profile_config(self, profile_id: str) -> Dict[str, Any]:
        """
        Retorna a configuração específica para um perfil.
        Se não existir, retorna a configuração global.
        """
        profile_config_path = os.path.join(self.config_dir, f"perfil_{profile_id}.json")
        
        if os.path.exists(profile_config_path):
            try:
                with open(profile_config_path, 'r', encoding='utf-8') as f:
                    profile_config = json.load(f)
                    # Mescla a global com a do perfil (perfil sobrescreve global)
                    merged = self._merge_configs(self.global_config, profile_config)
                    logger.info(f"[ConfigManager] Configuração específica carregada para perfil {profile_id}")
                    return merged
            except Exception as e:
                logger.error(f"[ConfigManager] Erro ao carregar config do perfil {profile_id}: {e}")
                return self.global_config.copy()
        
        return self.global_config.copy()
        
    def _merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Mescla dois dicionários de configuração recursivamente."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result
        
    def get(self, path: str, profile_id: str = None, default: Any = None) -> Any:
        """
        Obtém um valor de configuração usando um caminho separado por pontos.
        Ex: config.get("timeouts.2fa", "12345", 5)
        """
        config = self.get_profile_config(profile_id) if profile_id else self.global_config
        
        keys = path.split('.')
        current = config
        
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
                
        return current
