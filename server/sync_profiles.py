#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sincronizador de Perfis IXBrowser -> Painel GranaSocial
=======================================================
Este script permite que perfis já existentes no IXBrowser sejam
enviados para o painel de gestão com status 'aguardando_verificacao'.
"""

import os
import sys
import logging
import re

# Adicionar o diretório base ao path para importar os módulos do servidor
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.ixbrowser_api import listar_perfis, obter_ou_criar_grupo, verificar_conexao
from server.painel_integration import registrar_bm_no_painel, obter_usuario_painel

# Configuração de Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def extrair_login_das_notas(notas):
    """Tenta extrair o login do Facebook das notas do perfil."""
    if not notas:
        return None
    
    # Tenta encontrar "Login: XXXXX"
    match = re.search(r'Login:\s*([^\n\r]+)', notas)
    if match:
        return match.group(1).strip()
    
    # Tenta encontrar um ID numérico longo (comum em logins de FB)
    match_id = re.search(r'(\d{10,})', notas)
    if match_id:
        return match_id.group(1).strip()
        
    return None

def sincronizar_grupo(username_painel, nome_grupo):
    """Sincroniza todos os perfis de um grupo específico do IXBrowser."""
    logger.info(f"Iniciando sincronização para o usuário '{username_painel}' no grupo '{nome_grupo}'...")
    
    # 1. Verificar conexão com IXBrowser
    conexao = verificar_conexao()
    if not conexao.get('conectado'):
        logger.error(f"Erro: {conexao.get('mensagem')}")
        return False

    # 2. Verificar se o usuário existe no painel
    user_painel = obter_usuario_painel(username_painel)
    if not user_painel:
        logger.error(f"Erro: Usuário '{username_painel}' não encontrado no painel GranaSocial.")
        return False

    # 3. Obter ID do grupo
    grupo_id = obter_ou_criar_grupo(nome_grupo)
    if not grupo_id:
        logger.error(f"Erro: Grupo '{nome_grupo}' não encontrado no IXBrowser.")
        return False

    # 4. Listar perfis do grupo
    perfis = listar_perfis(grupo_id=grupo_id, limit=500)
    if not perfis:
        logger.warning(f"Nenhum perfil encontrado no grupo '{nome_grupo}'.")
        return True

    logger.info(f"Encontrados {len(perfis)} perfis no grupo. Iniciando processamento...")

    sucesso = 0
    falha = 0
    ja_existia = 0

    for perfil in perfis:
        profile_id = str(perfil.get('id'))
        profile_name = perfil.get('name', '')
        notas = perfil.get('note', '')
        
        # Tentar obter o login do FB (fb_login)
        fb_login = extrair_login_das_notas(notas) or perfil.get('username', '')
        
        if not fb_login:
            logger.warning(f"Perfil '{profile_name}' (ID: {profile_id}) não possui login identificado nas notas. Pulando...")
            falha += 1
            continue

        logger.info(f"Sincronizando Perfil: {profile_name} (FB: {fb_login})...")
        
        # Registrar no painel
        # Nota: registrar_bm_no_painel já lida com a inserção na tabela bm_records
        resultado = registrar_bm_no_painel(
            username=username_painel,
            profile_name=profile_name,
            bm_name=profile_name,
            bm_email='',
            fb_login=fb_login,
            ix_profile_id=profile_id,
            ix_profile_title=profile_name,
            ix_profile_tags=''
        )

        if resultado.get('sucesso'):
            logger.info(f"  [OK] Perfil sincronizado com sucesso! ID Interno: {resultado.get('bm_id')}")
            sucesso += 1
        else:
            msg = resultado.get('mensagem', 'Erro desconhecido')
            if "Duplicate entry" in msg or "já existe" in msg.lower():
                logger.info(f"  [AVISO] Perfil já estava registrado no painel.")
                ja_existia += 1
            else:
                logger.error(f"  [ERRO] Falha ao registrar: {msg}")
                falha += 1

    logger.info("==================================================")
    logger.info(f"Sincronização concluída!")
    logger.info(f"Total de perfis processados: {len(perfis)}")
    logger.info(f"Sucesso (Novos): {sucesso}")
    logger.info(f"Já existiam: {ja_existia}")
    logger.info(f"Falhas: {falha}")
    logger.info("==================================================")
    
    return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 sync_profiles.py <usuario_painel> <nome_grupo_ixbrowser>")
        sys.exit(1)
    
    user = sys.argv[1]
    grupo = sys.argv[2]
    sincronizar_grupo(user, grupo)
