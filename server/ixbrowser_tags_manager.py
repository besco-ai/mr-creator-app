#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
IXBrowser Tags Manager - Gerenciador de Tags no IXBrowser v2026
================================================================
Atualiza tags dos perfis no IXBrowser após criação de BM.
Tags: logado, bm_criada, aguardando_verificacao
"""

import logging
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class IXBrowserTagsManager:
    """Gerencia tags de perfis no IXBrowser."""
    
    # Tags padrão
    TAG_LOGGED_IN = "logado"
    TAG_BM_CREATED = "bm_criada"
    TAG_AWAITING_VERIFICATION = "aguardando_verificacao"
    TAG_VERIFIED = "verificada"
    TAG_REJECTED = "rejeitada"
    TAG_APPROVED = "aprovada"
    TAG_SOLD = "vendida"
    
    def __init__(self, ixbrowser_api_url: str, ixbrowser_api_key: str = ""):
        """
        Inicializa gerenciador de tags.
        
        Args:
            ixbrowser_api_url: URL da API do IXBrowser
            ixbrowser_api_key: Chave de API (opcional)
        """
        self.api_url = ixbrowser_api_url.rstrip('/')
        self.api_key = ixbrowser_api_key
        self.session = requests.Session()
        
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            })
    
    def add_tag_to_profile(self, profile_id: str, tag: str) -> bool:
        """
        Adiciona tag a um perfil no IXBrowser.
        
        Args:
            profile_id: ID do perfil no IXBrowser
            tag: Tag a adicionar
        
        Returns:
            True se adicionada com sucesso
        """
        try:
            # Endpoint para adicionar tag
            endpoint = f"{self.api_url}/profiles/{profile_id}/tags"
            
            payload = {
                "tag": tag,
                "timestamp": datetime.now().isoformat()
            }
            
            response = self.session.post(endpoint, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                logger.info(f"Tag '{tag}' adicionada ao perfil {profile_id}")
                return True
            else:
                logger.warning(f"Erro ao adicionar tag: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao adicionar tag ao perfil: {e}")
            return False
    
    def remove_tag_from_profile(self, profile_id: str, tag: str) -> bool:
        """
        Remove tag de um perfil no IXBrowser.
        
        Args:
            profile_id: ID do perfil no IXBrowser
            tag: Tag a remover
        
        Returns:
            True se removida com sucesso
        """
        try:
            # Endpoint para remover tag
            endpoint = f"{self.api_url}/profiles/{profile_id}/tags/{tag}"
            
            response = self.session.delete(endpoint, timeout=10)
            
            if response.status_code in [200, 204]:
                logger.info(f"Tag '{tag}' removida do perfil {profile_id}")
                return True
            else:
                logger.warning(f"Erro ao remover tag: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao remover tag do perfil: {e}")
            return False
    
    def set_profile_tags(self, profile_id: str, tags: List[str]) -> bool:
        """
        Define tags de um perfil (substitui todas).
        
        Args:
            profile_id: ID do perfil no IXBrowser
            tags: Lista de tags
        
        Returns:
            True se definidas com sucesso
        """
        try:
            # Endpoint para definir tags
            endpoint = f"{self.api_url}/profiles/{profile_id}/tags"
            
            payload = {
                "tags": tags,
                "timestamp": datetime.now().isoformat()
            }
            
            response = self.session.put(endpoint, json=payload, timeout=10)
            
            if response.status_code in [200, 201]:
                logger.info(f"Tags definidas para perfil {profile_id}: {tags}")
                return True
            else:
                logger.warning(f"Erro ao definir tags: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao definir tags do perfil: {e}")
            return False
    
    def get_profile_tags(self, profile_id: str) -> Optional[List[str]]:
        """
        Obtém tags de um perfil.
        
        Args:
            profile_id: ID do perfil no IXBrowser
        
        Returns:
            Lista de tags, ou None se erro
        """
        try:
            # Endpoint para obter tags
            endpoint = f"{self.api_url}/profiles/{profile_id}/tags"
            
            response = self.session.get(endpoint, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                tags = data.get('tags', [])
                logger.info(f"Tags recuperadas para perfil {profile_id}: {tags}")
                return tags
            else:
                logger.warning(f"Erro ao obter tags: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao obter tags do perfil: {e}")
            return None
    
    def mark_bm_created(self, profile_id: str, email: str = "") -> bool:
        """
        Marca perfil como tendo BM criada.
        
        Args:
            profile_id: ID do perfil no IXBrowser
            email: Email da BM (Tmail.Social)
        
        Returns:
            True se marcado com sucesso
        """
        try:
            tags = [
                self.TAG_LOGGED_IN,
                self.TAG_BM_CREATED,
                self.TAG_AWAITING_VERIFICATION
            ]
            
            # Adicionar email como tag se fornecido
            if email:
                tags.append(f"email:{email}")
            
            return self.set_profile_tags(profile_id, tags)
            
        except Exception as e:
            logger.error(f"Erro ao marcar BM como criada: {e}")
            return False
    
    def mark_bm_verified(self, profile_id: str) -> bool:
        """
        Marca BM como verificada.
        
        Args:
            profile_id: ID do perfil no IXBrowser
        
        Returns:
            True se marcado com sucesso
        """
        try:
            # Obter tags atuais
            current_tags = self.get_profile_tags(profile_id) or []
            
            # Remover tag de aguardando verificação
            if self.TAG_AWAITING_VERIFICATION in current_tags:
                current_tags.remove(self.TAG_AWAITING_VERIFICATION)
            
            # Adicionar tag de verificada
            if self.TAG_VERIFIED not in current_tags:
                current_tags.append(self.TAG_VERIFIED)
            
            return self.set_profile_tags(profile_id, current_tags)
            
        except Exception as e:
            logger.error(f"Erro ao marcar BM como verificada: {e}")
            return False
    
    def mark_bm_rejected(self, profile_id: str, reason: str = "") -> bool:
        """
        Marca BM como rejeitada.
        
        Args:
            profile_id: ID do perfil no IXBrowser
            reason: Motivo da rejeição
        
        Returns:
            True se marcado com sucesso
        """
        try:
            # Obter tags atuais
            current_tags = self.get_profile_tags(profile_id) or []
            
            # Remover tags de processamento
            for tag in [self.TAG_BM_CREATED, self.TAG_AWAITING_VERIFICATION]:
                if tag in current_tags:
                    current_tags.remove(tag)
            
            # Adicionar tag de rejeitada
            if self.TAG_REJECTED not in current_tags:
                current_tags.append(self.TAG_REJECTED)
            
            # Adicionar motivo se fornecido
            if reason:
                current_tags.append(f"rejected_reason:{reason}")
            
            return self.set_profile_tags(profile_id, current_tags)
            
        except Exception as e:
            logger.error(f"Erro ao marcar BM como rejeitada: {e}")
            return False
    
    def mark_bm_approved(self, profile_id: str) -> bool:
        """
        Marca BM como aprovada.
        
        Args:
            profile_id: ID do perfil no IXBrowser
        
        Returns:
            True se marcado com sucesso
        """
        try:
            # Obter tags atuais
            current_tags = self.get_profile_tags(profile_id) or []
            
            # Remover tag de aguardando verificação
            if self.TAG_AWAITING_VERIFICATION in current_tags:
                current_tags.remove(self.TAG_AWAITING_VERIFICATION)
            
            # Remover tag de verificada se existir
            if self.TAG_VERIFIED in current_tags:
                current_tags.remove(self.TAG_VERIFIED)
            
            # Adicionar tag de aprovada
            if self.TAG_APPROVED not in current_tags:
                current_tags.append(self.TAG_APPROVED)
            
            return self.set_profile_tags(profile_id, current_tags)
            
        except Exception as e:
            logger.error(f"Erro ao marcar BM como aprovada: {e}")
            return False
    
    def mark_bm_sold(self, profile_id: str, buyer_info: str = "") -> bool:
        """
        Marca BM como vendida.
        
        Args:
            profile_id: ID do perfil no IXBrowser
            buyer_info: Informações do comprador
        
        Returns:
            True se marcado com sucesso
        """
        try:
            # Obter tags atuais
            current_tags = self.get_profile_tags(profile_id) or []
            
            # Remover tags anteriores
            for tag in [self.TAG_APPROVED, self.TAG_VERIFIED]:
                if tag in current_tags:
                    current_tags.remove(tag)
            
            # Adicionar tag de vendida
            if self.TAG_SOLD not in current_tags:
                current_tags.append(self.TAG_SOLD)
            
            # Adicionar informações do comprador se fornecidas
            if buyer_info:
                current_tags.append(f"buyer:{buyer_info}")
            
            return self.set_profile_tags(profile_id, current_tags)
            
        except Exception as e:
            logger.error(f"Erro ao marcar BM como vendida: {e}")
            return False
    
    def batch_update_tags(self, profiles_tags: List[Dict]) -> Tuple[int, int]:
        """
        Atualiza tags de múltiplos perfis em lote.
        
        Args:
            profiles_tags: Lista de dicionários {profile_id, tags}
        
        Returns:
            Tupla (sucesso, erros)
        """
        success = 0
        errors = 0
        
        for item in profiles_tags:
            profile_id = item.get('profile_id')
            tags = item.get('tags', [])
            
            if self.set_profile_tags(profile_id, tags):
                success += 1
            else:
                errors += 1
        
        logger.info(f"Atualização em lote: {success} sucesso, {errors} erros")
        return success, errors


# Instância global (será inicializada pelo backend)
_tags_manager: Optional[IXBrowserTagsManager] = None


def initialize_tags_manager(ixbrowser_api_url: str, ixbrowser_api_key: str = "") -> bool:
    """
    Inicializa gerenciador global de tags.
    
    Args:
        ixbrowser_api_url: URL da API do IXBrowser
        ixbrowser_api_key: Chave de API (opcional)
    
    Returns:
        True se inicializado com sucesso
    """
    global _tags_manager
    try:
        _tags_manager = IXBrowserTagsManager(ixbrowser_api_url, ixbrowser_api_key)
        logger.info("Tags manager inicializado com sucesso")
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar tags manager: {e}")
        return False


def get_tags_manager() -> Optional[IXBrowserTagsManager]:
    """Obtém instância global do gerenciador de tags."""
    return _tags_manager
