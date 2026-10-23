#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Módulo de acesso GS BM CREATOR PRO MAX - Versão 27.0 Enterprise Shield.
Integração Total com Blindagem de Domínio Raiz e Motor Polimórfico.
"""

from __future__ import annotations
import atexit
import hashlib
import json
import logging
import os
import random
import secrets
import socket
import sys
import threading
import time
import uuid
import warnings
import platform
from datetime import date, datetime, timedelta

# Suprimir warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko.*')
warnings.filterwarnings('ignore', message='.*TripleDES.*')

try:
    import requests as _requests
    _TEM_REQUESTS = True
except ImportError:
    _TEM_REQUESTS = False

logger = logging.getLogger(__name__)

# ── SEM CREDENCIAIS DE BANCO NO BINÁRIO (2026-08-12) ─────────────────────────
# A conexão MySQL direta foi REMOVIDA: a porta 3306 está fechada para a internet
# e a senha do banco NUNCA mais é embarcada no .exe. Toda operação passa pelo
# endpoint HTTPS abaixo (software_api.php), que fala com o MySQL local na VPS.

# Configurações de API v27.0
from server.marca import URL_API as _URL_DA_MARCA   # fonte unica: server/marca.py
_API_URL = _URL_DA_MARCA

# Mensagem única p/ QUALQUER falha de infraestrutura mostrada na GUI. NUNCA
# expõe host/porta/IP/stack — o detalhe técnico fica só no log local.
_ERR_CONEXAO_GENERICA = ('Não foi possível conectar ao servidor agora. '
                         'Verifique sua internet e tente novamente em instantes.')

# Cache de Sessão
_sessao_cache = {
    'usuario': '',
    'senha': '',
    'user_id': None,
    'autenticado': False,
    'role': 'user',
    'session_token': '',
    'machine_id': '',
    'coins': 0.0,
    'tokens': 0,
    'pode_importar_painel': False,
}

# Motor de Stealth v27.0
class GS_Stealth_Engine:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.user_agent = self._generate_ua()
        
    def _generate_ua(self):
        chrome_versions = ["124.0.0.0", "125.0.0.0", "126.0.0.0"]
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.choice(chrome_versions)} Safari/537.36"

    def get_headers(self):
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "X-GS-Session": self.session_id,
            "X-GS-Fingerprint": hashlib.sha256(f"{platform.node()}-{platform.processor()}".encode()).hexdigest(),
            "X-Entity-Isolated": "true"
        }

_stealth = GS_Stealth_Engine()

def _gerar_machine_id() -> str:
    try:
        from server.granasocial_db import gerar_hwid
        return gerar_hwid()
    except Exception:
        return hashlib.sha256(f"{platform.node()}-{platform.machine()}".encode()).hexdigest()

def _api_post(action: str, extra: dict = None, timeout: int = 60) -> dict:
    if not _TEM_REQUESTS:
        return {'sucesso': False, 'mensagem': 'requests não instalado.'}
    
    payload = {
        'username': _sessao_cache.get('usuario', ''),
        'password': _sessao_cache.get('senha', ''),
        'action': action
    }
    if extra:
        payload.update(extra)
        
    try:
        headers = _stealth.get_headers()
        resp = _requests.post(_API_URL, data=payload, headers=headers, timeout=timeout)
        data = resp.json()
        
        # Normalização v27.0
        if 'success' in data:
            data['sucesso'] = bool(data['success'])
        if 'message' in data:
            data['mensagem'] = data['message']
            
        return data
    except Exception as exc:
        logger.error(f'[API v27.0] Erro na ação {action}: {exc}')
        return {'sucesso': False, 'mensagem': _ERR_CONEXAO_GENERICA}

def validar_usuario(usuario, senha):
    try:
        from server.granasocial_db import autenticar
        res = autenticar(str(usuario).strip(), str(senha))

        if not res.get('sucesso'):
            return res.get('mensagem', 'Falha de autenticação.')

        u = res['usuario']
        # Sincroniza BMs ao PainelBR só para editor/admin — agora derivado do
        # `role` retornado pelo login (o lookup por MySQL direto foi removido
        # com o fechamento da porta 3306).
        pode_importar = str(u.get('role', '') or '').strip().lower() in ('editor', 'admin')
        
        _sessao_cache.update({
            'usuario': u['username'],
            'senha': senha,
            'user_id': u['id'],
            'autenticado': True,
            'role': u.get('role', 'user'),
            'session_token': secrets.token_hex(32),
            'machine_id': _gerar_machine_id(),
            'coins': float(u.get('coins', 0)),
            'tokens': int(u.get('tokens', 0)),
            'pode_importar_painel': bool(pode_importar),
            # Modo de geração de e-mail (painel → Configurações → Gerador de E-mails):
            # 'subdominio' (padrão) | 'raiz' | 'ambos' (sorteia).
            'email_modo_geracao': (lambda v: v if v in ('subdominio', 'raiz', 'ambos') else 'subdominio')(
                str(u.get('email_modo_geracao', 'subdominio') or 'subdominio').strip().lower()),
        })
        return True
    except Exception as exc:
        logger.exception(f'[Acesso] Erro no login: {exc}')
        return _ERR_CONEXAO_GENERICA

def criar_site_empresa(cnpj: str, callback_status=None, deve_continuar=None,
                       subdominio: str = '', dominio_raiz: str = '') -> dict:
    """
    Cria site blindado com PSL Simulation.
    Implementa a lógica de espera infinita por domínio raiz (onixaix.com).

    `subdominio`/`dominio_raiz`: quando informados (reservados p/ o e-mail de
    subdomínio da BM), o painel cria o site EXATAMENTE nesse subdomínio/raiz, para
    o e-mail bater com o site (blindagem). Vazio = comportamento padrão.
    """
    tentativas = 0
    while True:
        tentativas += 1
        if callback_status:
            callback_status(f"🛡️ Criando site blindado (v27.0)... [tentativa {tentativas}]")

        _payload = {'cnpj': cnpj}
        if subdominio:   _payload['subdominio'] = subdominio
        if dominio_raiz: _payload['dominio_raiz'] = dominio_raiz
        res = _api_post('criar_site', _payload, timeout=120)
        
        if res.get('sucesso'):
            return res
            
        msg = str(res.get('mensagem', '')).lower()
        sem_dominio = any(k in msg for k in ('dominio raiz', 'domínio raiz', 'estoque', 'nameservers'))
        
        if not sem_dominio:
            return res
            
        if deve_continuar and not deve_continuar():
            return {'sucesso': False, 'mensagem': 'Cancelado pelo usuário.'}
            
        if callback_status:
            callback_status("⏳ Aguardando domínio raiz blindado no estoque...")
            
        time.sleep(15)

def reservar_subdominio(cnpj: str) -> dict:
    """Reserva o subdomínio (raiz + nome da empresa) p/ o e-mail da BM nascer no
    subdomínio EXATO do site, SEM criar o site nem gastar token. Devolve
    {host, subdominio, dominio_raiz} ou {} em falha. O site diferido depois usa o
    MESMO subdomínio/raiz (create_site com esses campos) → e-mail = site."""
    try:
        res = _api_post('reservar_subdominio', {'cnpj': cnpj}, timeout=30)
        if res.get('sucesso'):
            _d = res.get('dados') if isinstance(res.get('dados'), dict) else res
            host = _d.get('host', '') or res.get('host', '')
            if host:
                return {'host': host,
                        'subdominio': _d.get('subdominio', '') or res.get('subdominio', ''),
                        'dominio_raiz': _d.get('dominio_raiz', '') or res.get('dominio_raiz', '')}
    except Exception as e:
        logger.warning('[Acesso] reservar_subdominio falhou: %s', e)
    return {}


def salvar_meta_tags_site(site_id, meta_tags: str, telefone: str = '') -> dict:
    return _api_post('salvar_meta_tags', {
        'site_id': int(site_id),
        'meta_tags': meta_tags,
        'telefone': telefone
    })

def buscar_empresas_ativas(tipo='aleatorio', cidade='', estado=''):
    return _api_post('buscar_empresas', {
        'tipo': tipo,
        'cidade': cidade,
        'estado': estado
    })

def obter_saldo_coins():
    if not esta_autenticado(): return 0.0
    try:
        from server.granasocial_db import obter_saldos
        saldos = obter_saldos(_sessao_cache['user_id'])
        _sessao_cache['coins'] = saldos['coins']
        _sessao_cache['tokens'] = saldos['tokens']
        return saldos['coins']
    except:
        return _sessao_cache['coins']

def esta_autenticado():
    return _sessao_cache.get('autenticado', False)

def logout_usuario():
    _sessao_cache.update({'autenticado': False, 'user_id': None})

# Funções Legadas e Compatibilidade
def marcar_perfil_usado(compra_id, perfil_index=0): return True
def obter_contagem_perfis(): return 0
def registrar_bm_criada(**kwargs):
    if not esta_autenticado() or not _sessao_cache.get('pode_importar_painel'):
        return {'sucesso': True, 'mensagem': 'Ignorado (painelbr não ativo)'}
    try:
        from server.painel_integration import registrar_bm_no_painel
        kwargs['username'] = _sessao_cache['usuario']
        return registrar_bm_no_painel(**kwargs)
    except:
        return {'sucesso': False}

def marcar_empresa_usada(cnpj, motivo=''):
    try:
        from server.granasocial_db import marcar_empresa_usada as _mu
        return _mu(cnpj, motivo)
    except:
        return {'sucesso': False}

def atualizar_contato_site(site_id, telefone='', email='', senha_email='', email_servidor=''):
    """Atualiza contato do site. Quando o e-mail é o da BM (apex/gsmails), passa
    também a SENHA dele — assim a página do site mostra o MESMO e-mail+senha que
    verificou a BM (o de subdomínio nunca recebe nada)."""
    return _api_post('atualizar_contato_site', {
        'site_id': site_id, 'telefone': telefone, 'email': email,
        'email_senha': senha_email, 'email_servidor': email_servidor,
    })

def debitar_token(quantidade=1, descricao=''):
    try:
        from server.granasocial_db import debitar_token as _dt
        res = _dt(_sessao_cache['user_id'], quantidade, descricao)
        if res.get('sucesso'): _sessao_cache['tokens'] = res['tokens']
        return res
    except:
        return {'sucesso': False}

def reembolsar_token(quantidade=1, descricao=''):
    try:
        from server.granasocial_db import creditar_token as _ct
        res = _ct(_sessao_cache['user_id'], quantidade, descricao)
        if res.get('sucesso'): _sessao_cache['tokens'] = res['tokens']
        return res
    except:
        return {'sucesso': False}


# ─────────────────────────────────────────────────────────────────────────────
# Funções exigidas pelo backend (server.backend importa TODAS de uma vez; se
# qualquer uma faltar, o `from server.acesso import (...)` levanta ImportError e
# o backend cai para STUBS — inclusive esta_autenticado() → sempre False, o que
# fazia a GUI pedir "Faça login antes de importar perfis" mesmo já logado).
# ─────────────────────────────────────────────────────────────────────────────

def obter_dados_sessao():
    return dict(_sessao_cache)


def obter_perfis_disponiveis():
    """Compatibilidade: importação remota de perfis foi desativada (usar .TXT)."""
    if not esta_autenticado():
        return {'sucesso': False, 'perfis': [], 'total': 0, 'mensagem': 'Não autenticado'}
    return {'sucesso': True, 'perfis': [], 'total': 0,
            'mensagem': 'Importação remota desativada: utilize apenas .TXT no Creator.'}


def consultar_coins_api():
    saldo = obter_saldo_coins()
    return {'sucesso': esta_autenticado(), 'coins': saldo, 'mensagem': f'Saldo: {saldo} coins'}


# Contas da EQUIPE (funcionários/administração) que usam o Creator SEM consumir
# NADA — nem coins, nem token de site, nem saldo de SMS. São os papéis 'admin' e
# 'editor' (2026-09-09, pedido do dono). A isenção de coins é aplicada aqui (o bot
# pula o débito); a de TOKEN de site e de SMS é aplicada no PAINEL (server-side),
# que também checa o papel do usuário e não debita para admin/editor.
USUARIOS_USO_LIVRE = {'alexandre06'}
ROLES_USO_LIVRE = {'admin', 'editor'}
# Planos: TODOS os planos ficaram disponíveis para TODOS os usuários (comuns pagam
# os valores; equipe é isenta). Mantido o nome da função por compatibilidade.
ROLES_PLANOS_GUPSHUP = {'admin', 'editor'}


def usuario_uso_livre() -> bool:
    """True se o usuário logado é da EQUIPE (admin/editor) e NÃO consome
    coins/tokens/SMS. Também cobre usernames especiais de USUARIOS_USO_LIVRE."""
    try:
        if not _sessao_cache.get('autenticado'):
            return False
        if str(_sessao_cache.get('role') or '').strip().lower() in ROLES_USO_LIVRE:
            return True
        return str(_sessao_cache.get('usuario') or '').strip().lower() in USUARIOS_USO_LIVRE
    except Exception:
        return False


def usuario_eh_admin() -> bool:
    """True SÓ para o papel 'admin' (o DONO). Editores e usuários comuns NÃO entram.
    Usado para liberar a importação de .txt PRÓPRIO (perfis de terceiros, sem exigir
    compra) EXCLUSIVAMENTE ao admin — editor e usuário comum só podem usar perfis
    COMPRADOS do GranaSocial (pedido do dono, 2026-10-08)."""
    try:
        if not _sessao_cache.get('autenticado'):
            return False
        return str(_sessao_cache.get('role') or '').strip().lower() == 'admin'
    except Exception:
        return False


def usuario_pode_planos_gupshup() -> bool:
    """TODOS os planos liberados para TODOS os usuários autenticados (2026-09-09).
    Comuns pagam os valores; a equipe (admin/editor) é isenta. O nome é histórico —
    hoje 'pode planos' = está autenticado. Os fluxos Gupshup seguem bloqueados p/
    TODOS por estarem em atualização (gate próprio no backend), independente disto."""
    try:
        return bool(_sessao_cache.get('autenticado'))
    except Exception:
        return False


def email_modo_geracao() -> str:
    """Modo de geração de e-mail escolhido pelo admin no painel (aba 'Gerador de
    E-mails'): 'subdominio' (padrão) | 'raiz' | 'ambos'. Vem no login."""
    m = str(_sessao_cache.get('email_modo_geracao', 'subdominio') or 'subdominio').strip().lower()
    return m if m in ('subdominio', 'raiz', 'ambos') else 'subdominio'


def debitar_coins(quantidade, descricao='', tipo='uso_bmcreator', referencia_id=None):
    """Debita coins do usuário logado em granasocial.users.coins."""
    if not esta_autenticado():
        return {'sucesso': False, 'coins': 0, 'debitado': 0, 'mensagem': 'Não autenticado'}
    if usuario_uso_livre():
        return {'sucesso': True, 'coins': float(_sessao_cache.get('coins') or 0),
                'debitado': 0, 'mensagem': 'Uso livre (sem consumo de coins)'}
    user_id = _sessao_cache.get('user_id')
    if not user_id:
        return {'sucesso': False, 'coins': 0, 'debitado': 0, 'mensagem': 'Sessão sem user_id'}
    try:
        from server.granasocial_db import debitar_coins as _gs_debit
        res = _gs_debit(int(user_id), float(quantidade or 0), tipo=tipo,
                        descricao=descricao or 'BM criada pelo Creator',
                        referencia_id=referencia_id)
        if res.get('sucesso'):
            _sessao_cache['coins'] = float(res.get('coins') or 0)
            return {'sucesso': True, 'coins': res['coins'],
                    'debitado': res.get('debitado', float(quantidade or 0)),
                    'transacao_id': res.get('transacao_id'), 'mensagem': 'Debitado com sucesso'}
        return {'sucesso': False,
                'coins': float(res.get('coins') or _sessao_cache.get('coins') or 0),
                'debitado': 0, 'mensagem': res.get('mensagem', 'Falha ao debitar')}
    except Exception as exc:
        logger.warning('[Acesso] Erro ao debitar coins: %s', exc)
        return {'sucesso': False, 'coins': 0, 'debitado': 0, 'mensagem': str(exc)}


def reembolsar_coin(quantidade=1, descricao='', tipo='reembolso_bmcreator', referencia_id=None):
    """Credita coins ao usuário logado em granasocial.users.coins."""
    if not esta_autenticado():
        return {'sucesso': False, 'coins': 0, 'reembolsado': 0, 'mensagem': 'Não autenticado'}
    user_id = _sessao_cache.get('user_id')
    if not user_id:
        return {'sucesso': False, 'coins': 0, 'reembolsado': 0, 'mensagem': 'Sessão sem user_id'}
    try:
        from server.granasocial_db import creditar_coins as _gs_credit
        res = _gs_credit(int(user_id), float(quantidade or 0), tipo=tipo,
                         descricao=descricao or 'Reembolso automático Creator',
                         referencia_id=referencia_id)
        if res.get('sucesso'):
            _sessao_cache['coins'] = float(res.get('coins') or 0)
            return {'sucesso': True, 'coins': res['coins'],
                    'reembolsado': res.get('creditado', float(quantidade or 0)),
                    'transacao_id': res.get('transacao_id'), 'mensagem': 'Reembolsado'}
        return {'sucesso': False,
                'coins': float(res.get('coins') or _sessao_cache.get('coins') or 0),
                'reembolsado': 0, 'mensagem': res.get('mensagem', 'Falha ao reembolsar')}
    except Exception as exc:
        logger.warning('[Acesso] Erro ao reembolsar coins: %s', exc)
        return {'sucesso': False, 'coins': 0, 'reembolsado': 0, 'mensagem': str(exc)}


def comprar_numero_sms(servico='fb', servidor_id=0):
    extra = {'servico': servico}
    if servidor_id:
        extra['servidor_id'] = int(servidor_id)
    res = _api_post('comprar_sms', extra)
    if res.get('sucesso') and 'ativacao_id' not in res and 'dados' in res:
        res.update(res.get('dados', {}))
    return res


def comprar_numero_verificacao_bm():
    return comprar_numero_sms(servico='fb')


def verificar_sms_recebido(ativacao_id) -> dict:
    return _api_post('verificar_sms', {'ativacao_id': int(ativacao_id)})


def cancelar_sms(ativacao_id) -> dict:
    return _api_post('cancelar_sms', {'ativacao_id': int(ativacao_id)})


def obter_detalhes_site(site_id) -> dict:
    """Obtém detalhes de um site empresarial via API (mapeia 'site' → 'empresa')."""
    res = _api_post('detalhes_site', {'site_id': int(site_id)})
    if res.get('sucesso') and 'site' in res and 'empresa' not in res:
        site = res['site']
        res['empresa'] = {
            'razao_social':  site.get('razao_social', ''),
            'nome_fantasia': site.get('nome_fantasia', ''),
            'cnpj':          site.get('cnpj', ''),
            'logradouro':    site.get('logradouro', ''),
            'numero':        site.get('numero', ''),
            'complemento':   site.get('complemento', ''),
            'bairro':        site.get('bairro', ''),
            'municipio':     site.get('municipio', ''),
            'uf':            site.get('uf', ''),
            'cep':           site.get('cep', ''),
            'telefone':      site.get('telefone', ''),
            'atividade':     site.get('atividade_principal', '') or site.get('atividade', ''),
            'categoria':     site.get('tipo_empresa', '') or site.get('categoria', ''),
            'url_completa':  site.get('url_completa', ''),
        }
    return res


def gerar_certificado_cnpj_pdf(site_id, telefone: str = '') -> dict:
    """Gera o Comprovante de Inscrição CNPJ (PDF) via API do painel (Dompdf).
    Retorna: {sucesso, pdf_bytes(bytes), is_mei(bool), mensagem}."""
    import base64 as _b64
    extra = {'site_id': int(site_id)}
    if telefone:
        extra['telefone'] = telefone
    res = _api_post('gerar_certificado_pdf', extra, timeout=90)
    out = {'sucesso': bool(res.get('sucesso')), 'pdf_bytes': b'',
           'is_mei': bool(res.get('is_mei')), 'mensagem': res.get('mensagem', '')}
    if out['sucesso']:
        b64 = res.get('pdf_base64', '') or ''
        try:
            out['pdf_bytes'] = _b64.b64decode(b64) if b64 else b''
        except Exception as exc:
            out['sucesso'] = False
            out['mensagem'] = f'PDF base64 inválido: {exc}'
        if out['sucesso'] and not out['pdf_bytes']:
            out['sucesso'] = False
            out['mensagem'] = out['mensagem'] or 'PDF vazio.'
    return out


def salvar_dns_txt_site(site_id, dns_value: str, telefone: str = '') -> dict:
    """Adiciona registro TXT DNS de verificação do Facebook (Cloudflare/cPanel na VPS)."""
    if 'facebook-domain-verification=' in dns_value:
        dns_value = dns_value.split('facebook-domain-verification=', 1)[-1].strip()
    return _api_post('adicionar_dns_txt',
                     {'site_id': int(site_id), 'dns_value': dns_value}, timeout=45)


def salvar_arquivo_verificacao_site(site_id, nome_arquivo: str, conteudo: str) -> dict:
    """Publica o arquivo HTML de verificação do Facebook na RAIZ do site (VPS/Nginx),
    acessível em https://<host>/<nome_arquivo>. Fallback de verificação de domínio."""
    return _api_post('salvar_arquivo_verificacao',
                     {'site_id': int(site_id), 'nome_arquivo': nome_arquivo,
                      'conteudo': conteudo}, timeout=45)
