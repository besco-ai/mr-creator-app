import logging
import time
from typing import Dict, Tuple, Any

logger = logging.getLogger("GS_BM_Creator.BlockDetector")

class BlockDetector:
    """
    Detector inteligente de bloqueios do Facebook.
    Identifica checkpoints, bloqueios permanentes e verificações de identidade
    para evitar desperdício de tempo e tentativas inúteis.
    """
    
    # Padrões de URL que indicam bloqueios. OBS: "checkpoint" NÃO entra aqui como
    # substring — o query `checkpoint_src` da HOME logada (após "Confiar neste
    # dispositivo") contém "checkpoint" e dava falso-positivo. O checkpoint REAL é
    # tratado à parte, pelo CAMINHO /checkpoint/ (ver _url_eh_checkpoint_real).
    BLOCK_URLS = [
        "disabled",
        "restricted",
        "suspended"
    ]

    @staticmethod
    def _url_eh_checkpoint_real(url) -> bool:
        """True só para o checkpoint REAL (path /checkpoint/), não p/ checkpoint_src."""
        u = (url or '').lower()
        caminho = u.split('?', 1)[0].split('#', 1)[0]
        return '/checkpoint' in caminho
    
    # Seletores que indicam tipos específicos de bloqueio
    BLOCK_SELECTORS = {
        "conta_desativada": [
            "//div[contains(text(), 'conta foi desativada')]",
            "//div[contains(text(), 'account has been disabled')]",
            "//h2[contains(text(), 'You Can\\'t Use Facebook')]"
        ],
        "verificacao_identidade": [
            "//div[contains(text(), 'Carregue um documento')]",
            "//div[contains(text(), 'Upload A Photo Of Yourself')]",
            "//div[contains(text(), 'Confirme sua identidade')]"
        ],
        "limite_atingido": [
            "//div[contains(text(), 'limite de tentativas')]",
            "//div[contains(text(), 'too many times')]",
            "//div[contains(text(), 'tente novamente mais tarde')]"
        ]
    }
    
    @classmethod
    def check_for_blocks(cls, driver, driver_helper=None) -> Tuple[bool, str, str]:
        """
        Verifica se há algum bloqueio na página atual.
        Retorna: (is_blocked, block_type, action_needed)
        """
        try:
            current_url = driver.current_url.lower()

            # 1. Verificação rápida por URL (checkpoint REAL pelo path; demais por substring)
            is_block_url = (cls._url_eh_checkpoint_real(current_url)
                            or any(keyword in current_url for keyword in cls.BLOCK_URLS))

            if not is_block_url:
                return False, "", ""
                
            logger.warning(f"[BlockDetector] URL suspeita detectada: {current_url}")
            
            # 2. Verificação profunda por elementos na página
            page_source = driver.page_source.lower()
            
            # Verificar conta desativada (bloqueio permanente)
            if "conta foi desativada" in page_source or "disabled" in page_source:
                logger.error("[BlockDetector] 🚨 CONTA DESATIVADA detectada!")
                return True, "conta_desativada", "abort_profile"
                
            # Verificar upload de documento (checkpoint severo)
            if "documento de identidade" in page_source or "upload a photo" in page_source:
                logger.error("[BlockDetector] 🚨 VERIFICAÇÃO DE IDENTIDADE detectada!")
                return True, "verificacao_identidade", "pause_profile"
                
            # Verificar limite de tentativas (bloqueio temporário)
            if "limite" in page_source or "too many times" in page_source:
                logger.warning("[BlockDetector] ⚠️ LIMITE ATINGIDO detectado!")
                return True, "limite_atingido", "cooldown_profile"
                
            # Se tem a URL de checkpoint REAL mas não é um dos severos acima,
            # pode ser o aviso de "Comportamento Automatizado" que podemos pular
            if cls._url_eh_checkpoint_real(current_url):
                if "comportamento automatizado" in page_source or "automated behaviour" in page_source:
                    logger.info("[BlockDetector] Aviso de comportamento automatizado detectado (pulável).")
                    return False, "aviso_automatizado", "dismiss"

                # Se o "checkpoint" na verdade traz um reCAPTCHA, NÃO é bloqueio:
                # o captcha-anywhere (CapSolver) resolve e o fluxo segue. Sem isto,
                # muitos perfis com captcha pós-login eram abortados aqui.
                if ("recaptcha" in page_source or "g-recaptcha" in page_source
                        or "data-sitekey" in page_source or "not a robot" in page_source
                        or "não sou um robô" in page_source or "nao sou um robo" in page_source):
                    logger.info("[BlockDetector] Checkpoint com reCAPTCHA — tratando como captcha (CapSolver resolve).")
                    return False, "captcha", "solve"

                # Outro tipo de checkpoint desconhecido
                logger.warning("[BlockDetector] Checkpoint desconhecido detectado.")
                return True, "checkpoint_desconhecido", "pause_profile"
                
            return False, "", ""
            
        except Exception as e:
            logger.error(f"[BlockDetector] Erro ao verificar bloqueios: {e}")
            return False, "", ""
            
    @classmethod
    def handle_block(cls, block_type: str, action_needed: str, profile_id: str, callback_status=None):
        """
        Executa a ação apropriada baseada no tipo de bloqueio.
        """
        if action_needed == "abort_profile":
            msg = f"❌ Perfil {profile_id} bloqueado permanentemente (Conta Desativada). Abortando."
            logger.error(msg)
            if callback_status:
                callback_status(msg, "erro")
            return False
            
        elif action_needed == "pause_profile":
            msg = f"⚠️ Perfil {profile_id} requer verificação manual (Documento/Selfie). Pausando."
            logger.warning(msg)
            if callback_status:
                callback_status(msg, "aviso")
            return False
            
        elif action_needed == "cooldown_profile":
            msg = f"⏳ Perfil {profile_id} atingiu limite de ações. Necessário aguardar 24h."
            logger.warning(msg)
            if callback_status:
                callback_status(msg, "aviso")
            return False
            
        return True
