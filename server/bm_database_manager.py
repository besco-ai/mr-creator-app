#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BM Database Manager - Gerenciador de BMs no MySQL v2026
========================================================
Gerencia registro, atualização e sincronização de BMs no banco de dados.
Status: "Aguardando verificação" para análise manual no painel web.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import mysql.connector
from mysql.connector import Error

logger = logging.getLogger(__name__)


class BMDatabaseManager:
    """Gerencia BMs no banco de dados MySQL."""
    
    # Status possíveis
    STATUS_AWAITING_VERIFICATION = "AGUARDANDO_VERIFICACAO"
    STATUS_VERIFIED = "VERIFICADA"
    STATUS_REJECTED = "REJEITADA"
    STATUS_PENDING = "PENDENTE"
    STATUS_APPROVED = "APROVADA"
    STATUS_SOLD = "VENDIDA"
    STATUS_CANCELLED = "CANCELADA"
    
    def __init__(self, host: str, user: str, password: str, database: str):
        """
        Inicializa gerenciador de BMs.
        
        Args:
            host: Host do MySQL
            user: Usuário do MySQL
            password: Senha do MySQL
            database: Nome do banco de dados
        """
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.connection = None
        self.connect()
    
    def connect(self) -> bool:
        """
        Conecta ao banco de dados MySQL.
        
        Returns:
            True se conectado com sucesso
        """
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci',
                autocommit=True
            )
            logger.info(f"Conectado ao MySQL: {self.database}")
            return True
        except Error as e:
            logger.error(f"Erro ao conectar ao MySQL: {e}")
            return False
    
    def disconnect(self):
        """Desconecta do banco de dados."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logger.info("Desconectado do MySQL")
    
    def register_bm(self, user_id: int, profile_id: str, email: str, 
                    tag_status: str, valor_bm: float = 2.50) -> Optional[int]:
        """
        Registra nova BM no banco de dados com status "Aguardando verificação".
        
        Args:
            user_id: ID do usuário
            profile_id: ID do perfil Facebook
            email: Email da BM (Tmail.Social)
            tag_status: Tag de status (ex: "Perfil: 10256 | BM: FB_61576442120781")
            valor_bm: Valor da BM (padrão 2.50)
        
        Returns:
            ID da BM registrada, ou None se erro
        """
        try:
            cursor = self.connection.cursor()
            
            query = """
            INSERT INTO bms (user_id, profile_id, email, tag_status, valor_bm, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            """
            
            values = (
                user_id,
                profile_id,
                email,
                tag_status,
                valor_bm,
                self.STATUS_AWAITING_VERIFICATION  # Status: Aguardando verificação
            )
            
            cursor.execute(query, values)
            bm_id = cursor.lastrowid
            
            logger.info(f"BM registrada com sucesso: ID={bm_id}, Profile={profile_id}, Email={email}")
            cursor.close()
            return bm_id
            
        except Error as e:
            logger.error(f"Erro ao registrar BM: {e}")
            return None
    
    def update_bm_status(self, bm_id: int, status: str, notes: str = "") -> bool:
        """
        Atualiza status de uma BM.
        
        Args:
            bm_id: ID da BM
            status: Novo status
            notes: Notas adicionais
        
        Returns:
            True se atualizado com sucesso
        """
        try:
            cursor = self.connection.cursor()
            
            query = "UPDATE bms SET status = %s, updated_at = NOW() WHERE id = %s"
            cursor.execute(query, (status, bm_id))
            
            if cursor.rowcount > 0:
                logger.info(f"Status da BM {bm_id} atualizado para {status}")
                cursor.close()
                return True
            else:
                logger.warning(f"BM {bm_id} não encontrada")
                cursor.close()
                return False
                
        except Error as e:
            logger.error(f"Erro ao atualizar status da BM: {e}")
            return False
    
    def get_bms_awaiting_verification(self, user_id: Optional[int] = None) -> List[Dict]:
        """
        Obtém BMs aguardando verificação.
        
        Args:
            user_id: ID do usuário (opcional, para filtrar por usuário)
        
        Returns:
            Lista de BMs aguardando verificação
        """
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            if user_id:
                query = """
                SELECT * FROM bms 
                WHERE status = %s AND user_id = %s
                ORDER BY created_at DESC
                """
                cursor.execute(query, (self.STATUS_AWAITING_VERIFICATION, user_id))
            else:
                query = """
                SELECT * FROM bms 
                WHERE status = %s
                ORDER BY created_at DESC
                """
                cursor.execute(query, (self.STATUS_AWAITING_VERIFICATION,))
            
            bms = cursor.fetchall()
            logger.info(f"Recuperadas {len(bms)} BMs aguardando verificação")
            cursor.close()
            return bms
            
        except Error as e:
            logger.error(f"Erro ao obter BMs aguardando verificação: {e}")
            return []
    
    def get_bm_by_profile_id(self, profile_id: str) -> Optional[Dict]:
        """
        Obtém BM pelo ID do perfil.
        
        Args:
            profile_id: ID do perfil Facebook
        
        Returns:
            Dicionário com dados da BM, ou None se não encontrada
        """
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            query = "SELECT * FROM bms WHERE profile_id = %s LIMIT 1"
            cursor.execute(query, (profile_id,))
            
            bm = cursor.fetchone()
            cursor.close()
            return bm
            
        except Error as e:
            logger.error(f"Erro ao obter BM por profile_id: {e}")
            return None
    
    def get_bm_by_email(self, email: str) -> Optional[Dict]:
        """
        Obtém BM pelo email.
        
        Args:
            email: Email da BM
        
        Returns:
            Dicionário com dados da BM, ou None se não encontrada
        """
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            query = "SELECT * FROM bms WHERE email = %s LIMIT 1"
            cursor.execute(query, (email,))
            
            bm = cursor.fetchone()
            cursor.close()
            return bm
            
        except Error as e:
            logger.error(f"Erro ao obter BM por email: {e}")
            return None
    
    def get_user_bms_summary(self, user_id: int) -> Dict:
        """
        Obtém resumo de BMs do usuário.
        
        Args:
            user_id: ID do usuário
        
        Returns:
            Dicionário com resumo (total, aguardando, verificadas, etc)
        """
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            query = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) as aguardando,
                SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) as verificadas,
                SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) as aprovadas,
                SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) as vendidas,
                SUM(valor_bm) as valor_total
            FROM bms
            WHERE user_id = %s
            """
            
            cursor.execute(query, (
                self.STATUS_AWAITING_VERIFICATION,
                self.STATUS_VERIFIED,
                self.STATUS_APPROVED,
                self.STATUS_SOLD,
                user_id
            ))
            
            summary = cursor.fetchone()
            cursor.close()
            
            # Converter None para 0
            if summary:
                for key in summary:
                    if summary[key] is None:
                        summary[key] = 0
            
            return summary or {}
            
        except Error as e:
            logger.error(f"Erro ao obter resumo de BMs: {e}")
            return {}
    
    def batch_register_bms(self, user_id: int, bms_data: List[Dict]) -> Tuple[int, int]:
        """
        Registra múltiplas BMs em lote.
        
        Args:
            user_id: ID do usuário
            bms_data: Lista de dicionários com dados das BMs
                    [{profile_id, email, tag_status, valor_bm}, ...]
        
        Returns:
            Tupla (total_registradas, total_erros)
        """
        registered = 0
        errors = 0
        
        try:
            cursor = self.connection.cursor()
            
            query = """
            INSERT INTO bms (user_id, profile_id, email, tag_status, valor_bm, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            """
            
            for bm in bms_data:
                try:
                    values = (
                        user_id,
                        bm.get('profile_id'),
                        bm.get('email', ''),
                        bm.get('tag_status', ''),
                        bm.get('valor_bm', 2.50),
                        self.STATUS_AWAITING_VERIFICATION
                    )
                    
                    cursor.execute(query, values)
                    registered += 1
                    
                except Exception as e:
                    logger.warning(f"Erro ao registrar BM {bm.get('profile_id')}: {e}")
                    errors += 1
            
            cursor.close()
            logger.info(f"Lote registrado: {registered} BMs, {errors} erros")
            return registered, errors
            
        except Error as e:
            logger.error(f"Erro ao registrar lote de BMs: {e}")
            return 0, len(bms_data)
    
    def verify_bm(self, bm_id: int, verified_by_user_id: int) -> bool:
        """
        Marca BM como verificada (análise manual concluída).
        
        Args:
            bm_id: ID da BM
            verified_by_user_id: ID do usuário que verificou
        
        Returns:
            True se verificada com sucesso
        """
        try:
            cursor = self.connection.cursor()
            
            query = """
            UPDATE bms 
            SET status = %s, updated_at = NOW() 
            WHERE id = %s
            """
            
            cursor.execute(query, (self.STATUS_VERIFIED, bm_id))
            
            # Registrar log de verificação
            self._log_bm_action(bm_id, "verificada", verified_by_user_id)
            
            logger.info(f"BM {bm_id} verificada por usuário {verified_by_user_id}")
            cursor.close()
            return True
            
        except Error as e:
            logger.error(f"Erro ao verificar BM: {e}")
            return False
    
    def reject_bm(self, bm_id: int, rejected_by_user_id: int, reason: str = "") -> bool:
        """
        Marca BM como rejeitada.
        
        Args:
            bm_id: ID da BM
            rejected_by_user_id: ID do usuário que rejeitou
            reason: Motivo da rejeição
        
        Returns:
            True se rejeitada com sucesso
        """
        try:
            cursor = self.connection.cursor()
            
            query = """
            UPDATE bms 
            SET status = %s, updated_at = NOW() 
            WHERE id = %s
            """
            
            cursor.execute(query, (self.STATUS_REJECTED, bm_id))
            
            # Registrar log de rejeição
            self._log_bm_action(bm_id, f"rejeitada: {reason}", rejected_by_user_id)
            
            logger.info(f"BM {bm_id} rejeitada por usuário {rejected_by_user_id}")
            cursor.close()
            return True
            
        except Error as e:
            logger.error(f"Erro ao rejeitar BM: {e}")
            return False
    
    def _log_bm_action(self, bm_id: int, action: str, user_id: int):
        """
        Registra ação em log de BM.
        
        Args:
            bm_id: ID da BM
            action: Ação realizada
            user_id: ID do usuário
        """
        try:
            cursor = self.connection.cursor()
            
            # Tentar inserir em bm_check_log se existir
            try:
                query = """
                INSERT INTO bm_check_log (bm_id, user_id, action, created_at)
                VALUES (%s, %s, %s, NOW())
                """
                cursor.execute(query, (bm_id, user_id, action))
            except:
                # Se tabela não existir, apenas registrar em log
                logger.info(f"Ação BM {bm_id}: {action}")
            
            cursor.close()
        except Exception as e:
            logger.warning(f"Erro ao registrar ação em log: {e}")


# Instância global (será inicializada pelo backend)
_bm_manager: Optional[BMDatabaseManager] = None


def initialize_bm_manager(host: str, user: str, password: str, database: str) -> bool:
    """
    Inicializa gerenciador global de BMs.
    
    Args:
        host: Host do MySQL
        user: Usuário do MySQL
        password: Senha do MySQL
        database: Nome do banco de dados
    
    Returns:
        True se inicializado com sucesso
    """
    global _bm_manager
    try:
        _bm_manager = BMDatabaseManager(host, user, password, database)
        return _bm_manager.connection is not None
    except Exception as e:
        logger.error(f"Erro ao inicializar BM manager: {e}")
        return False


def get_bm_manager() -> Optional[BMDatabaseManager]:
    """Obtém instância global do gerenciador de BMs."""
    return _bm_manager
