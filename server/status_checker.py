#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de Checagem de Status de BMs - FB Profile Manager
=======================================================
Automatiza a verificação de status (Verificada, Em Análise, Rejeitada)
diretamente no navegador IXBrowser, navegando pelas URLs de 
Contas do WhatsApp e Central de Segurança.
"""

import time
import os
import logging
import re
from server.playwright_compat import (
    conectar_playwright, ChromeOptions, Service, By, WebDriverWait, EC,
    TimeoutException, NoSuchElementException,
)

logger = logging.getLogger(__name__)

# Mapeamento de status do Facebook para o Painel
STATUS_MAPPING = {
    'verificada': 'verificada',
    'verified': 'verificada',
    'verificado': 'verificada',
    'em análise': 'em_analise',
    'em analise': 'em_analise',
    'in review': 'em_analise',
    'verificando': 'em_analise',
    'verifying': 'em_analise',
    'em verificação': 'em_analise',
    'rejeitada': 'rejeitada',
    'rejected': 'rejeitada',
    'rejeitado': 'rejeitada',
    'denied': 'rejeitada',
}

def conectar_selenium_existente(debugging_address, webdriver_path):
    """Conecta ao IXBrowser usando Playwright/CDP."""
    del webdriver_path
    try:
        logger.info(f"[StatusChecker] Conectando Playwright em {debugging_address}")
        return conectar_playwright(debugging_address)
    except Exception as e:
        logger.error(f"[StatusChecker] Não foi possível conectar Playwright. Debug={debugging_address} Erro={e}")
        return None


def verificar_status_bm_no_navegador(driver, business_id, callback_status=None):
    """
    Navega pelas URLs do Facebook e identifica o status da BM.
    Tenta primeiro Contas do WhatsApp, depois Central de Segurança.
    """
    status_encontrado = None
    
    # URLs para checagem
    urls = [
        f"https://business.facebook.com/latest/settings/whatsapp_account/?business_id={business_id}",
        f"https://business.facebook.com/latest/settings/security_center?business_id={business_id}"
    ]
    
    for url in urls:
        try:
            tipo = "WhatsApp" if "whatsapp" in url else "Segurança"
            if callback_status:
                callback_status(f"Checando status via {tipo}...")
            
            logger.info(f"[StatusChecker] Navegando para {url}")
            driver.get(url)
            
            # Aguardar carregamento (Facebook é pesado)
            time.sleep(5)
            try:  # pop-up "Updates to your account" (nova estrutura WhatsApp)
                from server.waba import dispensar_popup_atualizacao_whatsapp
                dispensar_popup_atualizacao_whatsapp(driver)
            except Exception:
                pass
            
            # Tentar encontrar o texto de status
            # O status geralmente está próximo ao texto "Verificação da empresa"
            try:
                # XPath genérico para encontrar o status próximo ao label
                elementos = driver.find_elements(By.XPATH, "//*[contains(text(), 'Verificação da empresa')]/following-sibling::*")
                
                # Se não encontrar por sibling, tenta buscar em toda a página por palavras-chave
                if not elementos:
                    page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                else:
                    page_text = " ".join([el.text.lower() for el in elementos])
                
                logger.info(f"[StatusChecker] Texto capturado na página ({tipo}): {page_text[:100]}...")
                
                # Verificar palavras-chave de status
                for fb_status, panel_status in STATUS_MAPPING.items():
                    if fb_status in page_text:
                        status_encontrado = panel_status
                        logger.info(f"[StatusChecker] Status identificado: {fb_status} -> {panel_status}")
                        break
                
                if status_encontrado:
                    break # Encontrou, não precisa checar a outra URL
                    
            except Exception as e:
                logger.warning(f"[StatusChecker] Erro ao ler elementos na URL {tipo}: {e}")
                
        except Exception as e:
            logger.error(f"[StatusChecker] Erro ao navegar para {url}: {e}")
            
    return status_encontrado

def processar_checagem_bm(bm_data, abrir_navegador_func, fechar_navegador_func, callback_status=None):
    """
    Fluxo completo para uma BM: abre navegador, checa status, fecha navegador.
    """
    profile_id = bm_data.get('ix_profile_id') or bm_data.get('profile_name')
    business_id = bm_data.get('business_id') or bm_data.get('fb_login')
    
    if not profile_id or not business_id:
        return None
    
    driver = None
    try:
        if callback_status:
            callback_status(f"Abrindo perfil {profile_id}...")
            
        # 1. Abrir navegador via IXBrowser API
        res_open = abrir_navegador_func(profile_id)
        if not res_open.get('sucesso'):
            logger.error(f"[StatusChecker] Falha ao abrir perfil {profile_id}: {res_open.get('mensagem')}")
            return None
            
        # 2. Conectar Selenium
        driver = conectar_selenium_existente(res_open['debugging_address'], res_open['webdriver'])
        if not driver:
            return None
            
        # 3. Verificar status
        status = verificar_status_bm_no_navegador(driver, business_id, callback_status)
        return status
        
    except Exception as e:
        logger.error(f"[StatusChecker] Erro no processamento da BM {business_id}: {e}")
        return None
    finally:
        if driver:
            try: driver.quit()
            except: pass
        try:
            fechar_navegador_func(profile_id)
        except:
            pass
