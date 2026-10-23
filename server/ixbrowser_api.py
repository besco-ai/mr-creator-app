#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
IXBrowser API v2 - Módulo de Integração (v23 - Fingerprint Reforçado)
=====================================================================
Gerencia criação de perfis, cookies, notas, 2FA e tags no IXBrowser.
Usa a API local v2 em http://127.0.0.1:53200/api/v2/

MELHORIAS v23:
- FINGERPRINT REFORÇADO: Sempre Windows 10 + TimeZone São Paulo + Full HD + PT-BR
- COOKIES COM LOCALE: Adiciona cookies de locale pt_BR e timezone automaticamente
- RESOLUÇÃO FIXA: 1920x1080 (Full HD)
- IDIOMA: pt-br forçado no fingerprint
"""

import requests
import json
import time
import socket
import logging
import urllib3

logger = logging.getLogger("GS_BM_Creator.IXBrowser")

# ============================================================================
# FORÇAR IPv4
# ============================================================================

_original_create_connection = urllib3.util.connection.create_connection


def _create_connection_ipv4_only(address, *args, **kwargs):
    host, port = address
    try:
        ipv4_addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        if ipv4_addresses:
            ipv4_host = ipv4_addresses[0][4][0]
            return _original_create_connection((ipv4_host, port), *args, **kwargs)
    except socket.gaierror:
        pass
    return _original_create_connection(address, *args, **kwargs)


urllib3.util.connection.create_connection = _create_connection_ipv4_only

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

BASE_URL = "http://127.0.0.1:53200"
API_TIMEOUT = 30
RETRY_DELAY = 3
MAX_RETRIES = 5

# Etiquetas padrão
ETIQUETA_LOGADO = "💎 Perfil Logado 💎"
ETIQUETA_NAO_LOGADO = "Perfil Não Logado"
ETIQUETA_BM_CRIADA = "💎 1 BM CRIADA 💎"

# ============================================================================
# FINGERPRINT BASE - Windows 10 + TimeZone São Paulo + Full HD + PT-BR
# ============================================================================

FINGERPRINT_BASE = {
    # Sistema Operacional: Windows 10
    'ua_type': 1,                    # 1 = Gerar automaticamente baseado no SO
    'platform': 'Windows',           # Plataforma Windows
    'system_version': '10',          # Windows 10 sempre
    
    # Idioma: Português (Brasil)
    'language_type': '2',            # 2 = Personalizado
    'language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',  # Accept-Language completo
    
    # Timezone: São Paulo (UTC-3)
    'timezone_type': '2',            # 2 = Personalizado
    'timezone': 'America/Sao_Paulo', # Timezone de São Paulo
    
    # Resolução: Full HD 1920x1080
    'resolving_power_type': '2',     # 2 = Personalizado
    'resolving_power': '1920,1080',  # Full HD fixo
    
    # WebRTC: Desabilitado para evitar leak de IP real
    'webrtc': '3',                   # 3 = Desabilitado
    
    # Canvas/WebGL: Noise para evitar fingerprint único
    'webgl_image': '1',              # 1 = Noise
    'canvas_type': '1',              # 1 = Noise
    'webgl_data_type': '1',          # 1 = Noise
    
    # Audio: Noise
    'audio_context': '1',            # 1 = Noise
    
    # Hardware: Noise
    'media_equipment': '1',          # 1 = Noise
    'client_rects': '1',             # 1 = Noise
    'speech_voices': '1',            # 1 = Noise
    'device_name_source': '1',       # 1 = Noise
    'font_type': '1',                # 1 = Noise
    
    # Hardware specs realistas para Windows 10
    'hardware_concurrency': '8',     # 8 cores (comum em PCs modernos)
    'device_memory': '8',            # 8 GB RAM (comum)
}

# Cookies extras para forçar locale pt_BR e timezone São Paulo
COOKIES_LOCALE_PTBR = [
    {
        "creation_time": "",
        "domain": ".facebook.com",
        "name": "locale",
        "value": "pt_BR",
        "path": "/",
        "expiration_time": "",
        "last_access_time": "",
        "secure": True,
        "http_only": False,
        "same_site": "-1",
        "priority": "1",
        "same_party": False,
        "source_scheme": "2",
        "source_port": "443",
        "is_host_cookie": False
    },
    {
        "creation_time": "",
        "domain": ".facebook.com",
        "name": "datr",
        "value": "",
        "path": "/",
        "expiration_time": "",
        "last_access_time": "",
        "secure": True,
        "http_only": True,
        "same_site": "-1",
        "priority": "1",
        "same_party": False,
        "source_scheme": "2",
        "source_port": "443",
        "is_host_cookie": False
    }
]


# ============================================================================
# SESSÃO HTTP
# ============================================================================

_sessao = None


def _obter_sessao():
    global _sessao
    if _sessao is None:
        _sessao = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=3, pool_connections=10, pool_maxsize=10)
        _sessao.mount('http://', adapter)
        _sessao.mount('https://', adapter)
    return _sessao


def _fazer_requisicao(endpoint, payload=None, max_retries=MAX_RETRIES):
    """Faz requisição POST à API v2 do IXBrowser."""
    sessao = _obter_sessao()
    for tentativa in range(max_retries):
        try:
            response = sessao.post(
                f"{BASE_URL}{endpoint}",
                json=payload or {},
                timeout=API_TIMEOUT
            )
            if response.status_code == 200:
                return response.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            if tentativa < max_retries - 1:
                time.sleep(RETRY_DELAY)
                continue
        except Exception as e:
            print(f"[IXBrowser API] Erro: {e}")
            if tentativa < max_retries - 1:
                time.sleep(RETRY_DELAY)
                continue
    return None


def _obter_fingerprint():
    """
    Retorna configuração de fingerprint reforçada:
    - Windows 10
    - TimeZone São Paulo (America/Sao_Paulo)
    - Full HD (1920x1080)
    - Idioma PT-BR
    """
    config = dict(FINGERPRINT_BASE)
    return config


def _adicionar_cookies_locale(cookie_json_str):
    """
    Adiciona cookies de locale pt_BR aos cookies existentes.
    Garante que o Facebook será aberto em Português (Brasil).
    """
    try:
        now_str = str(int(time.time()))
        exp_str = str(int(time.time()) + 365 * 24 * 3600)
        
        # Se já tem cookies, adicionar locale
        if cookie_json_str:
            try:
                cookies = json.loads(cookie_json_str)
                if isinstance(cookies, list):
                    # Verificar se já tem cookie locale
                    tem_locale = False
                    for cookie in cookies:
                        if cookie.get('name') == 'locale':
                            cookie['value'] = 'pt_BR'
                            tem_locale = True
                            break
                    
                    if not tem_locale:
                        # Adicionar cookie locale
                        locale_cookie = {
                            "creation_time": now_str,
                            "domain": ".facebook.com",
                            "name": "locale",
                            "value": "pt_BR",
                            "path": "/",
                            "expiration_time": exp_str,
                            "last_access_time": now_str,
                            "secure": True,
                            "http_only": False,
                            "same_site": "-1",
                            "priority": "1",
                            "same_party": False,
                            "source_scheme": "2",
                            "source_port": "443",
                            "is_host_cookie": False
                        }
                        cookies.append(locale_cookie)
                    
                    return json.dumps(cookies, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        
        # Se não tem cookies, criar apenas o locale
        locale_cookie = {
            "creation_time": now_str,
            "domain": ".facebook.com",
            "name": "locale",
            "value": "pt_BR",
            "path": "/",
            "expiration_time": exp_str,
            "last_access_time": now_str,
            "secure": True,
            "http_only": False,
            "same_site": "-1",
            "priority": "1",
            "same_party": False,
            "source_scheme": "2",
            "source_port": "443",
            "is_host_cookie": False
        }
        return json.dumps([locale_cookie], ensure_ascii=False)
        
    except Exception as e:
        print(f"[IXBrowser API] Erro ao adicionar cookies locale: {e}")
        return cookie_json_str or ''


# ============================================================================
# VERIFICAÇÃO DE CONEXÃO
# ============================================================================

def verificar_conexao():
    """Verifica se o IXBrowser ja esta rodando (NAO lanca automaticamente).

    O usuario e quem decide qual engine usar (IXBrowser ou AdsPower) e e
    quem abre o navegador. O software apenas checa o status e devolve
    'conectado': False com mensagem clara quando o IX nao esta aberto.
    """
    try:
        res = _fazer_requisicao('/api/v2/group-list', {"page": 1, "limit": 1}, max_retries=2)
        if res and res.get('error', {}).get('code') == 0:
            return {"conectado": True, "mensagem": "IXBrowser conectado"}
        return {
            "conectado": False,
            "mensagem": "IXBrowser não está rodando — abra o IXBrowser manualmente.",
        }
    except Exception as e:
        return {"conectado": False, "mensagem": f"Erro: {str(e)}"}


# ============================================================================
# GRUPOS
# ============================================================================

def listar_grupos():
    """Lista os grupos do IXBrowser: [{'group_id','group_name'}, ...].
    Usado pelo seletor do modo Reutilizar Perfis Logados."""
    try:
        res = _fazer_requisicao('/api/v2/group-list', {"page": 1, "limit": 2000})
        if res and res.get('error', {}).get('code') == 0:
            data = res.get('data', {})
            grupos = data if isinstance(data, list) else data.get('data', [])
            out = []
            for g in (grupos or []):
                if isinstance(g, dict) and g.get('id') is not None:
                    out.append({'group_id': str(g.get('id')),
                                'group_name': g.get('title', '') or g.get('group_name', '') or ''})
            return out
    except Exception as e:
        logger.warning("[IXBrowser] Erro ao listar grupos: %s", e)
    return []


def obter_ou_criar_grupo(nome_grupo):
    """Obtém o ID de um grupo pelo nome, ou cria se não existir."""
    res = _fazer_requisicao('/api/v2/group-list', {"page": 1, "limit": 100})
    if res and res.get('error', {}).get('code') == 0:
        data = res.get('data', {})
        grupos = data if isinstance(data, list) else data.get('data', [])
        for grupo in grupos:
            if grupo.get('title', '').lower() == nome_grupo.lower():
                return grupo.get('id')

    # Criar grupo
    res = _fazer_requisicao('/api/v2/group-create', {"group_name": nome_grupo})
    if res and res.get('error', {}).get('code') == 0:
        return res.get('data')

    return None


# ============================================================================
# CRIAÇÃO DE PERFIL
# ============================================================================

def criar_perfil(perfil_data, grupo_id, proxy_config=None):
    """
    Cria um perfil no IXBrowser com todos os dados do perfil Facebook.
    
    MELHORIAS v23:
    - Fingerprint sempre Windows 10 + São Paulo + Full HD + PT-BR
    - Cookies com locale pt_BR adicionado automaticamente
    """
    try:
        login = perfil_data.get('login', '')
        senha = perfil_data.get('senha', '')
        email = perfil_data.get('email', '')
        senha_email = perfil_data.get('senha_email', '')
        tfa = perfil_data.get('tfa', '')
        cookie_json = perfil_data.get('cookie_json', '')
        token = perfil_data.get('token', '')
        token_email = perfil_data.get('token_email', '')
        info_extra = perfil_data.get('info_extra', '')
        email_recuperacao = perfil_data.get('email_recuperacao', '')
        numero = perfil_data.get('numero', '')

        # Nome do perfil: Login do Facebook
        nome_perfil = f"FB_{login}" if login else f"Perfil_{numero}"

        # ── Notas detalhadas com emojis ──
        notas_linhas = []
        if login:
            notas_linhas.append(f"🆔 Login: {login}")
        if senha:
            notas_linhas.append(f"🔐 Senha: {senha}")
        if email:
            notas_linhas.append(f"📧 Email: {email}")
        if senha_email:
            notas_linhas.append(f"🔐 Senha Email: {senha_email}")
        if email_recuperacao:
            notas_linhas.append(f"📧 Email Recuperação: {email_recuperacao}")
        if token_email:
            notas_linhas.append(f"🔑 Token Email: {token_email}")
        if info_extra:
            notas_linhas.append(f"📝 Info Extra: {info_extra}")
        if tfa:
            notas_linhas.append(f"🔑 2FA: {tfa}")
        # Token de acesso (EAAA...) é descartável e NÃO entra na observação:
        # o login automático usa o cookie, nunca o token. Mantemos apenas os
        # dados úteis (login, senha, 2FA, email, senha do email, token do email).
        if cookie_json:
            notas_linhas.append("🍪 Cookie: ✅")
        texto_notas = '\n'.join(notas_linhas)

        # Montar payload de criação com fingerprint reforçado
        fingerprint = _obter_fingerprint()

        payload = {
            'site_id': 11,  # Facebook
            'name': nome_perfil,
            'note': texto_notas,
            'group_id': int(grupo_id),
            'username': login,
            'password': senha,
            'fingerprint_config': fingerprint
        }

        # Adicionar 2FA se disponível
        if tfa:
            payload['tfa_secret'] = tfa

        # Adicionar cookies com locale pt_BR
        # SEMPRE adiciona cookie locale, mesmo que não tenha outros cookies
        if cookie_json:
            # Adicionar locale pt_BR aos cookies existentes
            cookie_com_locale = _adicionar_cookies_locale(cookie_json)
            payload['cookie'] = cookie_com_locale
        else:
            # Mesmo sem cookies de sessão, adicionar cookie locale
            cookie_locale_only = _adicionar_cookies_locale('')
            if cookie_locale_only:
                payload['cookie'] = cookie_locale_only

        # Adicionar proxy apenas quando informado.
        # Sem proxy (IP direto / 4G): NÃO enviar proxy_config no payload.
        # Enviar qualquer proxy_mode sem proxy_id causa "Proxy id cannot be empty".
        if proxy_config:
            payload['proxy_config'] = proxy_config

        # Criar perfil
        res = _fazer_requisicao('/api/v2/profile-create', payload)

        if not res:
            return {"sucesso": False, "profile_id": None, "mensagem": "Sem resposta da API"}

        error_code = res.get('error', {}).get('code', -1)

        if error_code == 0:
            profile_id = res.get('data')
            if isinstance(profile_id, dict):
                profile_id = profile_id.get('id')

            if profile_id:
                return {
                    "sucesso": True,
                    "profile_id": profile_id,
                    "mensagem": f"Perfil {nome_perfil} criado com sucesso (Win10/SP/FHD/PT-BR)"
                }

        msg_erro = res.get('error', {}).get('message', 'Erro desconhecido')
        return {"sucesso": False, "profile_id": None, "mensagem": f"Erro: {msg_erro}"}

    except Exception as e:
        return {"sucesso": False, "profile_id": None, "mensagem": f"Exceção: {str(e)}"}


def atualizar_cookies_perfil(profile_id, cookie_json):
    """Atualiza os cookies de um perfil já criado (com locale pt_BR)."""
    try:
        # Adicionar locale pt_BR aos cookies
        cookie_com_locale = _adicionar_cookies_locale(cookie_json)
        
        res = _fazer_requisicao('/api/v2/profile-update-cookies', {
            'profile_id': int(profile_id),
            'cookie': cookie_com_locale
        })
        if res and res.get('error', {}).get('code') == 0:
            return True
    except Exception as e:
        print(f"[IXBrowser API] Erro ao atualizar cookies: {e}")
    return False


def atualizar_notas_perfil(profile_id, notas):
    """Atualiza as notas de um perfil."""
    try:
        res = _fazer_requisicao('/api/v2/profile-update', {
            'profile_id': int(profile_id),
            'note': notas
        })
        if res and res.get('error', {}).get('code') == 0:
            return True
    except Exception as e:
        print(f"[IXBrowser API] Erro ao atualizar notas: {e}")
    return False


def anexar_notas_perfil(profile_id, linhas):
    """Anexa linhas à observação (note) SEM apagar o que já existe.
    Só grava se conseguir LER a observação atual (evita perda de dados)."""
    try:
        res = _fazer_requisicao('/api/v2/profile-list', {'page': 1, 'limit': 1, 'profile_id': int(profile_id)})
        if not res or res.get('error', {}).get('code') != 0:
            print(f"[IXBrowser API] Não li a observação atual de {profile_id} — não anexo (evita perda).")
            return False
        data = res.get('data', {})
        perfis = data if isinstance(data, list) else data.get('data', [])
        item = None
        for p in (perfis or []):
            if isinstance(p, dict) and str(p.get('profile_id')) == str(profile_id):
                item = p
                break
        if item is None:
            print(f"[IXBrowser API] Perfil {profile_id} não encontrado — não anexo.")
            return False
        atual = str(item.get('note') or '')
        novas = [l for l in linhas if l and l not in atual]
        if not novas:
            return True
        combinado = (atual + ('\n' if atual else '') + '\n'.join(novas)).strip()
        return atualizar_notas_perfil(profile_id, combinado)
    except Exception as e:
        print(f"[IXBrowser API] Erro ao anexar notas: {e}")
        return False


def adicionar_tag_perfil(profile_id, nome_tag):
    """Adiciona uma tag ao perfil (compatibilidade com versão anterior)."""
    return adicionar_tags_perfil(profile_id, [nome_tag])


# Só as tags de DESFECHO chegam ao perfil (pedido do dono, 2026-09-02): UMA tag,
# no fim. As intermediárias ("1 BM CRIADA", "Perfil Logado", "DATACRAZY CRIADA",
# "WABA GUPSHUP CRIADA", "VERIFICAÇÃO PARCIAL", "REUTILIZADO"…) são descartadas
# aqui, no mesmo critério do AdsPower, para os dois navegadores ficarem iguais.
_TAGS_DESFECHO = ('EM ANALISE', 'EM ANÁLISE', 'PERFIL BLOQUEADO', 'BM BLOQUEADA',
                  # RECORRIDA é DESFECHO (WABA desabilitada + recurso enviado) — bug 2026-09-26.
                  'RECORRIDA', 'RECORRIDAS',
                  # STATUS REAL pós-análise da Meta (2026-10-08): antes DESCARTADAS aqui.
                  # Mesma lista do AdsPower para os dois engines ficarem iguais.
                  'VERIFICADA', 'VERIFICOU',
                  'WABA ATIVA', 'WABA APROVADA', 'WABA DESABILITADA',
                  'WABA PENDENTE', 'WABA RESTRITA',
                  'REJEITAD', 'PRECISA ATUALIZAR', 'ATUALIZAR BM', 'NAO VERIFICADA',
                  'NÃO VERIFICADA',
                  'TIER 2K', 'TIER 10K', 'TIER 100K', 'TIER ILIMITADA',
                  'BM 2K', 'BM 10K', 'BM 100K', 'BM ILIMITADA', 'ILIMITADA',
                  'BM ERRO', 'ERRO NO ENVIO')


def _e_tag_de_desfecho(nome):
    """True se a tag é um RESULTADO final do perfil."""
    n = (nome or '').upper()
    return any(p in n for p in _TAGS_DESFECHO)


def adicionar_tags_perfil(profile_id, lista_tags):
    """
    Adiciona múltiplas tags ao perfil — só as de DESFECHO (ver _TAGS_DESFECHO).
    """
    try:
        lista_tags = [t for t in (lista_tags or []) if _e_tag_de_desfecho(t)]
        if not lista_tags:
            return True
        res = _fazer_requisicao('/api/v2/profile-update', {
            'profile_id': int(profile_id),
            'tag': lista_tags
        })
        if res and res.get('error', {}).get('code') == 0:
            print(f"[IXBrowser API] Tags adicionadas ao perfil {profile_id}: {lista_tags}")
            return True
        else:
            msg = res.get('error', {}).get('message', 'Erro desconhecido') if res else 'Sem resposta'
            print(f"[IXBrowser API] Erro ao adicionar tags: {msg}")
    except Exception as e:
        print(f"[IXBrowser API] Erro ao adicionar tags: {e}")
    return False


def obter_perfil(profile_id):
    """Lê UM perfil (dict completo, inclui 'note') via profile-list. {} se falhar.
    Usado no reprocesso automático p/ recuperar as credenciais (note) do perfil."""
    try:
        res = _fazer_requisicao('/api/v2/profile-list',
                                {'page': 1, 'limit': 1, 'profile_id': int(profile_id)})
        if not res or res.get('error', {}).get('code') != 0:
            return {}
        data = res.get('data', {})
        perfis = data if isinstance(data, list) else data.get('data', [])
        for p in (perfis or []):
            if isinstance(p, dict) and str(p.get('profile_id')) == str(profile_id):
                it = dict(p)
                it.setdefault('remark', it.get('note') or '')
                return it
    except Exception as e:
        print(f"[IXBrowser API] obter_perfil {profile_id}: {e}")
    return {}


def _obter_tags_atuais(profile_id):
    """Lê as tags atuais do perfil via profile-list (nomes). [] se não conseguir."""
    try:
        res = _fazer_requisicao('/api/v2/profile-list',
                                {'page': 1, 'limit': 1, 'profile_id': int(profile_id)})
        if not res or res.get('error', {}).get('code') != 0:
            return []
        data = res.get('data', {})
        perfis = data if isinstance(data, list) else data.get('data', [])
        for p in (perfis or []):
            if isinstance(p, dict) and str(p.get('profile_id')) == str(profile_id):
                tg = p.get('tag') if p.get('tag') is not None else p.get('tags')
                if isinstance(tg, list):
                    return [str(t).strip() for t in tg if str(t).strip()]
                if isinstance(tg, str) and tg.strip():
                    return [x.strip() for x in tg.split(',') if x.strip()]
                return []
    except Exception as e:
        print(f"[IXBrowser API] Erro ao ler tags de {profile_id}: {e}")
    return []


def definir_tag_desfecho_perfil(profile_id, nova_tag):
    """SUBSTITUI a tag de DESFECHO do perfil pela `nova_tag`, mantendo as tags que
    NÃO são de desfecho. Espelha a função homônima do AdsPower — essencial para a
    troca LIMPA de status em tempo real (EM ANALISE → VERIFICADA 2K → REJEITADA)
    sem EMPILHAR tags. Só grava se conseguir LER as tags atuais (evita perda).
    `/api/v2/profile-update` com `tag` SUBSTITUI a lista inteira de tags do perfil."""
    try:
        nova = (nova_tag or '').strip()
        if not nova:
            return False
        atuais = _obter_tags_atuais(profile_id)
        manter = [t for t in atuais if not _e_tag_de_desfecho(t)]
        # dedup preservando ordem
        desejadas, vistos = [], set()
        for t in (manter + [nova]):
            k = t.strip().lower()
            if t.strip() and k not in vistos:
                vistos.add(k); desejadas.append(t.strip())
        res = _fazer_requisicao('/api/v2/profile-update',
                                {'profile_id': int(profile_id), 'tag': desejadas})
        if res and res.get('error', {}).get('code') == 0:
            print(f"[IXBrowser API] Tag de desfecho de {profile_id} definida como '{nova}' "
                  f"(antigas de desfecho removidas).")
            return True
        msg = res.get('error', {}).get('message', '?') if res else 'sem resposta'
        print(f"[IXBrowser API] definir_tag_desfecho_perfil falhou: {msg}")
        return False
    except Exception as e:
        print(f"[IXBrowser API] Erro em definir_tag_desfecho_perfil: {e}")
        return False


def atualizar_nome_perfil(profile_id, novo_nome):
    """Renomeia um perfil."""
    try:
        res = _fazer_requisicao('/api/v2/profile-update', {
            'profile_id': int(profile_id),
            'name': novo_nome
        })
        if res and res.get('error', {}).get('code') == 0:
            return True
    except Exception as e:
        print(f"[IXBrowser API] Erro ao renomear: {e}")
    return False


# ============================================================================
# ABRIR / FECHAR NAVEGADOR
# ============================================================================


def remover_proxy(profile_id):
    """Remove o proxy customizado do perfil e volta para IP real da máquina."""
    try:
        res = _fazer_requisicao('/api/v2/profile-update', {
            'profile_id': int(profile_id),
            'proxy_config': {
                'proxy_mode': 2,
                'proxy_type': 'http',
                'proxy_ip': '0.0.0.0',
                'proxy_port': '0',
                'proxy_user': '',
                'proxy_password': ''
            }
        }, max_retries=2)
        return bool(res and res.get('error', {}).get('code') == 0)
    except Exception:
        return False


# ACEITAR COOKIES DE TERCEIROS: o login do Gupshup é via Auth0 e a renovação do
# token de sessão usa cookies de TERCEIROS. O Chrome moderno bloqueia esses
# cookies (feature 'TrackingProtection3pcd'), o que causa 'Authentication Failed'
# no onboarding (lista de regiões vazia / Next não avança). Desligar essa feature
# mantém os 3p-cookies funcionando. É um flag de COMPORTAMENTO (não mexe em
# janela/fingerprint). Coloque False para reverter.
# DESATIVADO: não resolveu o 'Authentication Failed' do Gupshup — voltamos ao
# navegador ORIGINAL (sem nenhum flag extra de cookie).
_ACEITAR_COOKIES_TERCEIROS = False


def abrir_navegador(profile_id, headless=False, retry_without_proxy=True, janela=None):
    """
    Abre o navegador de um perfil e retorna dados de conexão.
    Correção v6:
      - fecha sessão órfã antes de abrir.
      - se o proxy falhar, remove o proxy e reabre com IP real.

    janela: dict opcional {x, y, w, h} para POSICIONAR/dimensionar a janela
            (organização em grade). Ignorado em headless.
    """
    try:
        try:
            fechar_navegador(profile_id)
            time.sleep(1.5)
        except Exception:
            pass

        # Argumentos para simular humano e evitar detecção
        args = [
            '--disable-notifications',
            '--lang=pt-BR',
            '--no-sandbox',
            '--disable-infobars',
        ]
        if _ACEITAR_COOKIES_TERCEIROS:
            # Mantém cookies de terceiros (necessário p/ o Auth0 do Gupshup).
            args.append('--disable-features=TrackingProtection3pcd')
        if janela and not headless:
            try:
                _x = int(janela.get('x', 0)); _y = int(janela.get('y', 0))
                _w = int(janela.get('w', 0)); _h = int(janela.get('h', 0))
                if _w > 200 and _h > 200:
                    args.append(f'--window-position={_x},{_y}')
                    args.append(f'--window-size={_w},{_h}')
                else:
                    args.append('--start-maximized')
                # Janela pequena renderizando em resolução desktop (layout normal).
                _dsf = janela.get('dsf')
                if _dsf and float(_dsf) < 0.999:
                    args.append(f'--force-device-scale-factor={_dsf}')
            except Exception:
                args.append('--start-maximized')
        else:
            args.extend(['--window-size=1920,1080', '--start-maximized'])
        if headless:
            args.extend(['--headless=new', '--disable-gpu'])

        res = _fazer_requisicao('/api/v2/profile-open', {
            'profile_id': int(profile_id),
            'args': args,
            'cookies_backup': False,
            'load_profile_info_page': False
        })

        if res:
            error_code = res.get('error', {}).get('code', -1)
            if error_code == 0 or error_code == 2001:
                data = res.get('data', {})
                ws = data.get('ws', '')
                debugging_address = data.get('debugging_address', '')
                debugging_port = data.get('debugging_port', '')
                webdriver_path = data.get('webdriver', '')

                return {
                    "sucesso": True,
                    "debugging_address": debugging_address,
                    "debugging_port": debugging_port,
                    "webdriver": webdriver_path,
                    "ws": ws,
                    "data": data,
                    "mensagem": "Navegador aberto (Win10/SP/FHD/PT-BR)"
                }

        msg = res.get('error', {}).get('message', 'Falha ao abrir navegador') if res else 'Sem resposta da API'
        if retry_without_proxy and ('ECONNREFUSED' in msg or 'proxy' in msg.lower()):
            print(f"[IXBrowser API] Proxy falhou para o perfil {profile_id}. Removendo proxy e reabrindo...")
            remover_proxy(profile_id)
            time.sleep(1.5)
            return abrir_navegador(profile_id, headless=headless, retry_without_proxy=False, janela=janela)

        return {"sucesso": False, "debugging_address": '', "webdriver": '', "ws": '', "data": {}, "mensagem": msg}
    except Exception as e:
        return {"sucesso": False, "debugging_address": '', "webdriver": '', "ws": '', "data": {}, "mensagem": str(e)}


def fechar_navegador(profile_id):
    """Fecha o navegador de um perfil."""
    try:
        res = _fazer_requisicao('/api/v2/profile-close', {
            'profile_id': int(profile_id)
        }, max_retries=2)
        return bool(res and res.get('error', {}).get('code') == 0)
    except:
        return False


# ============================================================================
# LISTAR PERFIS
# ============================================================================

def listar_perfis(grupo_id=None, page=1, limit=100):
    """Lista perfis do IXBrowser."""
    payload = {"page": page, "limit": limit}
    if grupo_id:
        payload["group_id"] = int(grupo_id)

    res = _fazer_requisicao('/api/v2/profile-list', payload)
    if res and res.get('error', {}).get('code') == 0:
        data = res.get('data', {})
        perfis = data if isinstance(data, list) else data.get('data', [])
        return perfis
    return []


# ============================================================================
# MONTAR PROXY CONFIG
# ============================================================================

def montar_proxy_config(proxy_ip='', proxy_porta='', proxy_usuario='', proxy_senha='', proxy_tipo='http'):
    """Monta a configuração de proxy para criação de perfil."""
    if not proxy_ip or not proxy_porta:
        return None

    return {
        'proxy_mode': 2,
        'proxy_type': proxy_tipo,
        'proxy_ip': str(proxy_ip).strip(),
        'proxy_port': str(proxy_porta).strip(),
        'proxy_user': str(proxy_usuario).strip() if proxy_usuario else '',
        'proxy_password': str(proxy_senha).strip() if proxy_senha else ''
    }
