#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AdsPower API - Módulo de Integração (v1.0)
==========================================
Gerencia criação de perfis, cookies, notas e tags no AdsPower.
Usa a API local em http://local.adspower.net:50325/api/v1/

Espelha as mesmas funções do ixbrowser_api.py para permitir
troca transparente entre IXBrowser e AdsPower.
"""

import json
import logging
import os
import time
import threading
import requests
import requests.adapters

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

BASE_URL = "http://local.adspower.net:50325"
API_TIMEOUT = 30
RETRY_DELAY = 3
MAX_RETRIES = 5

# A Local API do AdsPower limita a ~1 requisição/segundo ("Too many request per
# second"). Throttle GLOBAL (thread-safe) garante o intervalo mínimo entre TODAS
# as chamadas — sem isso as tags/notas/etc. falham silenciosamente em rajada.
_MIN_INTERVALO_REQ = 1.15
_throttle_lock = threading.Lock()
_ultima_req_ts = [0.0]


def _throttle_adspower():
    """Bloqueia até passar _MIN_INTERVALO_REQ desde a última requisição.

    ⚠️ REVERTIDO (2026-08-16): a versão "reserva + sleep fora do lock" (v1.48) tinha
    DRIFT ACUMULADO — sob carga de N workers as reservas se empilhavam (alvo = última
    reserva + 1,15s) e passavam MINUTOS à frente do relógio real; as chamadas de API do
    AdsPower ficavam presas nesse sleep e, como `criar_perfil` roda DENTRO de
    `_lock_abertura`, um worker travado segurava o lock e CONGELAVA a abertura de todos os
    outros navegadores (fluxo em massa parava do nada). Esta versão original NÃO acumula:
    cada chamada espera no máximo 1,15s desde a ÚLTIMA conclusão real. É o que rodava 24h
    de forma estável. A Local API do AdsPower aceita ~1 req/s — este teto é obrigatório."""
    with _throttle_lock:
        agora = time.monotonic()
        espera = _MIN_INTERVALO_REQ - (agora - _ultima_req_ts[0])
        if espera > 0:
            time.sleep(espera)
        _ultima_req_ts[0] = time.monotonic()

# Caminhos conhecidos do local_api do AdsPower (para auto-detecção de URL)
_LOCAL_API_PATHS = [
    os.path.join(os.environ.get('APPDATA', ''), 'adspower_global', 'cwd_global', 'source', 'local_api'),
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'adspower_global', 'cwd_global', 'source', 'local_api'),
]

# Etiquetas padrão
ETIQUETA_LOGADO = "💎 Perfil Logado 💎"
ETIQUETA_NAO_LOGADO = "Perfil Não Logado"
ETIQUETA_BM_CRIADA = "💎 1 BM CRIADA 💎"

# ============================================================================
# FINGERPRINT BASE (conforme documentação oficial AdsPower)
# ============================================================================

FINGERPRINT_BASE = {
    'automatic_timezone': '0',
    'timezone': 'America/Sao_Paulo',
    'language_switch': '0',
    'language': ['pt-BR', 'pt', 'en-US', 'en'],
    'screen_resolution': '1920_1080',
    'webrtc': 'disabled',
    'canvas': '1',
    'webgl_image': '1',
    'webgl': '3',
    'audio': '1',
    'do_not_track': 'default',
    'hardware_concurrency': '8',
    'device_memory': '8',
    'flash': 'block',
    'scan_port_type': '1',
    'media_devices': '1',
    'client_rects': '1',
    'device_name_switch': '1',
    'fonts': ['all'],
    'browser_kernel_config': {'version': 'ua_auto', 'type': 'chrome'},
    'random_ua': {'ua_browser': ['chrome'], 'ua_system_version': ['Windows 10']},
}

# ============================================================================
# SESSÃO HTTP
# ============================================================================

_sessao = None
_api_key = ''


def _auto_detectar_url():
    """Tenta detectar a URL do AdsPower a partir do arquivo local_api."""
    global BASE_URL
    for path in _LOCAL_API_PATHS:
        try:
            if os.path.isfile(path):
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if content.startswith('http'):
                    url = content.rstrip('/')
                    logger.info("[AdsPower] URL auto-detectada de %s: %s", path, url)
                    BASE_URL = url
                    return url
        except Exception:
            pass
    return None


def configurar_api_key(key):
    """Define a API key do AdsPower."""
    global _api_key
    _api_key = key.strip() if key else ''
    logger.info("[AdsPower] API Key configurada: %s***", _api_key[:8] if len(_api_key) > 8 else '(vazia)')


def configurar_url(url):
    """Define a URL base da API local do AdsPower (ex: http://local.adspower.net:50325)."""
    global BASE_URL
    if url and url.strip():
        BASE_URL = url.strip().rstrip('/')
        logger.info("[AdsPower] URL configurada: %s", BASE_URL)
    else:
        # Tentar auto-detectar
        detected = _auto_detectar_url()
        if not detected:
            BASE_URL = "http://local.adspower.net:50325"
            logger.info("[AdsPower] URL padrão: %s", BASE_URL)


def _obter_sessao():
    global _sessao
    if _sessao is None:
        _sessao = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=3, pool_connections=10, pool_maxsize=10)
        _sessao.mount('http://', adapter)
        _sessao.mount('https://', adapter)
    return _sessao


def _erro_transitorio_adspower(msg):
    """True p/ erros do AdsPower que são instabilidade da nuvem/rede deles (não
    do pedido): vale esperar e tentar de novo."""
    m = str(msg or '').lower()
    return any(s in m for s in ('not working well', 'try again later',
                                'server is busy', 'network error', 'timed out'))


def _fazer_requisicao(endpoint, params=None, method='GET', json_data=None, max_retries=MAX_RETRIES):
    """Faz requisição à API do AdsPower com autenticação."""
    sessao = _obter_sessao()
    url = f"{BASE_URL}{endpoint}"
    req_params = dict(params or {})
    headers = {}

    # Incluir API key se configurada
    if _api_key:
        headers['Authorization'] = f'Bearer {_api_key}'

    for tentativa in range(max_retries):
        try:
            _throttle_adspower()  # respeita ~1 req/seg do AdsPower
            if method == 'GET':
                response = sessao.get(url, params=req_params, headers=headers, timeout=API_TIMEOUT)
            else:
                response = sessao.post(url, json=json_data or {}, params=req_params, headers=headers, timeout=API_TIMEOUT)

            if response.status_code == 200:
                try:
                    data = response.json()
                    code = data.get('code', 0) if isinstance(data, dict) else 0
                    msg = data.get('msg', '') if isinstance(data, dict) else ''

                    # Tratar erros de autenticação imediatamente (sem retry)
                    if code == -1:
                        msg_lower = msg.lower()
                        if 'require api-key' in msg_lower:
                            logger.error(
                                "[AdsPower API] AUTENTICAÇÃO NECESSÁRIA em %s. "
                                "Vá em AdsPower → Automação → API → clique 'Gerar' para obter a API Key "
                                "e cole no campo 'API KEY ADSPOWER' no GS BM Creator.",
                                endpoint
                            )
                            return data  # Retorna sem retry
                        if 'api key mismatch' in msg_lower:
                            logger.error(
                                "[AdsPower API] API KEY INCORRETA em %s. "
                                "A chave informada não corresponde. "
                                "Vá em AdsPower → Automação → API → clique 'Gerar' ou 'Resetar' e copie a nova API Key.",
                                endpoint
                            )
                            return data  # Retorna sem retry

                    # Rate-limit do AdsPower → AGUARDA e RETENTA (não retorna erro).
                    if code == -1 and ('too many request' in msg.lower()
                                       or 'per second' in msg.lower()):
                        if tentativa < max_retries - 1:
                            time.sleep(1.3)
                            continue
                    # Falha TRANSITÓRIA da nuvem do AdsPower ("The server is not
                    # working well, please check the network or try again later"):
                    # o cliente local não conseguiu falar com o servidor deles —
                    # típico no pico de abertura de vários workers. Retenta com
                    # backoff. EXCETO /user/create: ali o perfil pode ter sido
                    # criado mesmo com o erro, e o retry (com checagem anti-
                    # duplicação) é feito em criar_perfil(). (2026-10-13)
                    if (code == -1 and _erro_transitorio_adspower(msg)
                            and not endpoint.endswith('/user/create')):
                        if tentativa < max_retries - 1:
                            _esp = min(3 * (tentativa + 1), 12)
                            logger.warning("[AdsPower API] %s instável (%s) — retentando em %ss "
                                           "(%d/%d)", endpoint, msg[:60], _esp, tentativa + 1, max_retries)
                            time.sleep(_esp)
                            continue
                    if code != 0:
                        logger.warning("[AdsPower API] %s retornou code=%s msg=%s", endpoint, code, msg)
                    return data
                except (ValueError, json.JSONDecodeError) as je:
                    logger.error("[AdsPower API] Resposta não-JSON de %s: %s", endpoint, response.text[:200])
                    if tentativa < max_retries - 1:
                        time.sleep(RETRY_DELAY)
                        continue
            else:
                logger.warning("[AdsPower API] %s HTTP %s: %s", endpoint, response.status_code, response.text[:200])
                if tentativa < max_retries - 1:
                    time.sleep(RETRY_DELAY)
                    continue
        except (requests.ConnectionError, requests.Timeout) as ce:
            logger.warning("[AdsPower API] Conexão falhou %s (tentativa %d/%d): %s", endpoint, tentativa + 1, max_retries, ce)
            if tentativa < max_retries - 1:
                time.sleep(RETRY_DELAY)
                continue
        except Exception as e:
            logger.error("[AdsPower API] Erro inesperado %s: %s", endpoint, e)
            if tentativa < max_retries - 1:
                time.sleep(RETRY_DELAY)
                continue
    logger.error("[AdsPower API] Todas as tentativas falharam para %s", endpoint)
    return None


# ============================================================================
# VERIFICAÇÃO DE CONEXÃO
# ============================================================================

def verificar_conexao():
    """Verifica se o AdsPower está rodando e se a API Key é válida."""
    try:
        # 1) Verificar se AdsPower está rodando via /status (não precisa de auth)
        res = _fazer_requisicao('/status', max_retries=2)
        if not res or res.get('code') != 0:
            logger.warning("[AdsPower] Não conectado em %s", BASE_URL)
            return {"conectado": False, "mensagem": f"AdsPower não respondeu em {BASE_URL}. Verifique se está aberto."}

        logger.info("[AdsPower] Status OK em %s", BASE_URL)

        # 2) Verificar se API Key funciona tentando listar grupos
        res2 = _fazer_requisicao('/api/v1/group/list', params={'page': 1, 'page_size': 1}, max_retries=1)
        if res2 and isinstance(res2, dict):
            code = res2.get('code', -1)
            msg = res2.get('msg', '')

            if code == 0:
                # Tudo ok — API e auth funcionam
                logger.info("[AdsPower] API Key válida, conexão completa em %s", BASE_URL)
                return {"conectado": True, "mensagem": "AdsPower conectado", "url": BASE_URL}

            # Erros de autenticação
            msg_lower = msg.lower()
            if 'require api-key' in msg_lower:
                if _api_key:
                    # Tem key mas não foi aceita? Não deveria acontecer
                    logger.error("[AdsPower] API Key necessária mas header não aceito")
                    return {
                        "conectado": False,
                        "mensagem": "AdsPower exige API Key. Vá em AdsPower → Automação → API → Gerar e cole no campo API KEY."
                    }
                else:
                    logger.error("[AdsPower] API Key necessária mas não configurada")
                    return {
                        "conectado": False,
                        "mensagem": "AdsPower exige API Key. Vá em AdsPower → Automação → API → clique 'Gerar', copie a key e cole no campo 'API KEY ADSPOWER'."
                    }

            if 'api key mismatch' in msg_lower:
                logger.error("[AdsPower] API Key incorreta!")
                return {
                    "conectado": False,
                    "mensagem": "API Key incorreta! Vá em AdsPower → Automação → API → clique 'Resetar', copie a nova key e cole no campo 'API KEY ADSPOWER'."
                }

            # Outro erro — mas o AdsPower está rodando
            logger.warning("[AdsPower] Resposta inesperada: code=%s msg=%s", code, msg)
            return {"conectado": True, "mensagem": f"AdsPower conectado (aviso: {msg})", "url": BASE_URL}

        # Sem resposta no group/list mas /status OK — considerar conectado com aviso
        logger.info("[AdsPower] Conectado via /status mas API não confirmada")
        return {"conectado": True, "mensagem": "AdsPower conectado (verificação parcial)", "url": BASE_URL}

    except Exception as e:
        logger.error("[AdsPower] Exceção ao verificar conexão: %s", e)
        return {"conectado": False, "mensagem": f"Erro ao conectar em {BASE_URL}: {str(e)}"}


# ============================================================================
# GRUPOS
# ============================================================================

def _is_auth_error(res):
    """Verifica se a resposta é um erro de autenticação."""
    if not res or not isinstance(res, dict):
        return False
    msg = (res.get('msg', '') or '').lower()
    return res.get('code') == -1 and ('require api-key' in msg or 'api key mismatch' in msg)

def obter_ou_criar_grupo(nome_grupo):
    """Obtém o ID de um grupo pelo nome, ou cria se não existir."""
    nome_grupo = (nome_grupo or '').strip()
    if not nome_grupo:
        logger.error("[AdsPower] Nome do grupo vazio!")
        return None

    # ── Função auxiliar para buscar em lista de grupos ──
    def _buscar_na_lista(grupos_list):
        if not grupos_list:
            return None
        for grupo in grupos_list:
            if not isinstance(grupo, dict):
                continue
            gname = (grupo.get('group_name') or '').strip()
            if gname.lower() == nome_grupo.lower():
                return grupo.get('group_id')
        return None

    # ── 1) Buscar por nome (parâmetro group_name) ──
    try:
        res = _fazer_requisicao('/api/v1/group/list', params={
            'group_name': nome_grupo, 'page': 1, 'page_size': 100
        })
        # Abortar imediatamente se erro de autenticação
        if _is_auth_error(res):
            logger.error("[AdsPower] Falha de autenticação ao buscar grupo. Verifique a API Key.")
            return None
        if res and res.get('code') == 0:
            data = res.get('data', {})
            grupos = data.get('list', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            logger.info("[AdsPower] Busca grupo '%s': %d grupos retornados", nome_grupo, len(grupos) if grupos else 0)
            # Log dos nomes retornados para debug
            if grupos:
                nomes = [g.get('group_name', '?') for g in grupos if isinstance(g, dict)]
                logger.info("[AdsPower] Nomes dos grupos: %s", nomes[:20])
            gid = _buscar_na_lista(grupos)
            if gid:
                logger.info("[AdsPower] Grupo '%s' encontrado: ID=%s", nome_grupo, gid)
                return gid
    except Exception as e:
        logger.warning("[AdsPower] Erro na busca por nome: %s", e)

    # ── 2) Buscar todos (sem filtro) — fallback ──
    try:
        time.sleep(1)  # Rate limit
        res_all = _fazer_requisicao('/api/v1/group/list', params={'page': 1, 'page_size': 2000})
        if res_all and res_all.get('code') == 0:
            data = res_all.get('data', {})
            grupos = data.get('list', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            logger.info("[AdsPower] Busca geral: %d grupos retornados", len(grupos) if grupos else 0)
            if grupos:
                nomes = [g.get('group_name', '?') for g in grupos if isinstance(g, dict)]
                logger.info("[AdsPower] Todos os grupos: %s", nomes[:50])

            # Busca exata
            gid = _buscar_na_lista(grupos)
            if gid:
                logger.info("[AdsPower] Grupo '%s' encontrado (busca geral): ID=%s", nome_grupo, gid)
                return gid

            # Busca parcial (contém o nome) — para nomes com espaços extras ou caracteres especiais
            for grupo in (grupos or []):
                if not isinstance(grupo, dict):
                    continue
                gname = (grupo.get('group_name') or '').strip()
                if gname and (nome_grupo.lower() in gname.lower() or gname.lower() in nome_grupo.lower()):
                    gid = grupo.get('group_id')
                    logger.info("[AdsPower] Grupo encontrado por match parcial: '%s' ≈ '%s' ID=%s", nome_grupo, gname, gid)
                    return gid
    except Exception as e:
        logger.warning("[AdsPower] Erro na busca geral: %s", e)

    # ── 3) Criar grupo ──
    logger.info("[AdsPower] Grupo '%s' não encontrado em nenhuma busca, criando...", nome_grupo)
    time.sleep(1)  # Rate limit
    res = _fazer_requisicao('/api/v1/group/create', method='POST', json_data={"group_name": nome_grupo})
    if res and res.get('code') == 0:
        data = res.get('data', {})
        gid = data.get('group_id') if isinstance(data, dict) else data
        logger.info("[AdsPower] Grupo '%s' criado: ID=%s", nome_grupo, gid)
        return gid

    # ── 4) Se criação falhou (possível grupo já existente ou rate limit), buscar novamente ──
    msg_erro = (res.get('msg', '') if res else '').lower()
    logger.info("[AdsPower] Criação falhou com msg='%s'. Tentando buscar grupo existente...", msg_erro)
    time.sleep(1)  # Rate limit
    res_retry = _fazer_requisicao('/api/v1/group/list', params={'page': 1, 'page_size': 2000})
    if res_retry and res_retry.get('code') == 0:
        data = res_retry.get('data', {})
        grupos = data.get('list', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        gid = _buscar_na_lista(grupos)
        if gid:
            logger.info("[AdsPower] Grupo '%s' encontrado após retry: ID=%s", nome_grupo, gid)
            return gid
        # Último recurso: retornar primeiro grupo que contenha o nome
        for grupo in (grupos or []):
            if isinstance(grupo, dict):
                gname = (grupo.get('group_name') or '').strip()
                if nome_grupo.lower() in gname.lower():
                    gid = grupo.get('group_id')
                    logger.info("[AdsPower] Grupo match parcial após retry: '%s' ≈ '%s' ID=%s", nome_grupo, gname, gid)
                    return gid

    logger.error("[AdsPower] Falha definitiva ao obter/criar grupo '%s'. Resposta: %s", nome_grupo, res)
    return None


# ============================================================================
# CRIAÇÃO DE PERFIL
# ============================================================================

def buscar_perfil_por_nome(nome_perfil):
    """Procura um perfil EXISTENTE pelo nome exato (ex.: 'FB_61577034343504').

    O filtro `user_name` da API do AdsPower é por APROXIMAÇÃO (devolve qualquer
    nome que contenha o texto), então a conferência exata é feita aqui.
    Devolve o dict do perfil (o mais recente, se houver repetidos) ou None."""
    nome_perfil = str(nome_perfil or '').strip()
    if not nome_perfil:
        return None
    try:
        res = _fazer_requisicao('/api/v1/user/list',
                                params={'page': 1, 'page_size': 100,
                                        'user_name': nome_perfil})
        lista = ((res or {}).get('data') or {}).get('list') or []
        exatos = [p for p in lista if str(p.get('name', '')).strip() == nome_perfil]
        if not exatos:
            return None
        exatos.sort(key=lambda p: str(p.get('created_time') or ''), reverse=True)
        return exatos[0]
    except Exception as e:
        logger.warning("[AdsPower] Busca por '%s' falhou: %s", nome_perfil, e)
        return None


def criar_perfil(perfil_data, grupo_id, proxy_config=None):
    """
    Cria um perfil no AdsPower com todos os dados do perfil Facebook.
    Compatível com a mesma interface do ixbrowser_api.criar_perfil().

    ⚠️ REAPROVEITA o perfil que já existir com o mesmo nome (`FB_<login>`) em vez
    de criar outro. Sem isso, reimportar uma conta para RETOMAR o fluxo (BM já
    criada, faltando mandar p/ análise) criava um perfil duplicado — e, com a
    cota do AdsPower cheia, nem criava: "the number of imported accounts exceeds
    the limit of 602". O perfil antigo ainda tem a sessão logada e as notas com
    e-mail/senha da BM, então reaproveitar é também o caminho mais rápido.
    (2026-08-03)
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

        nome_perfil = f"FB_{login}" if login else f"Perfil_{numero}"

        # ── REAPROVEITAMENTO: já existe um perfil com este nome? ───────────────
        existente = buscar_perfil_por_nome(nome_perfil)
        if existente and existente.get('user_id'):
            pid = existente['user_id']
            logger.info("[AdsPower] Perfil '%s' JÁ EXISTE (ID=%s, grupo '%s') — "
                        "reaproveitando em vez de criar outro.",
                        nome_perfil, pid, existente.get('group_name', '?'))
            return {
                "sucesso": True,
                "profile_id": pid,
                "reaproveitado": True,
                "mensagem": f"Perfil {nome_perfil} já existia no AdsPower — reaproveitado (retomando o fluxo)"
            }

        # ── Notas detalhadas (remark) ENXUTAS (pedido do usuário) ──
        # SÓ os dados de acesso: Login / Senha / Email / Senha Email. NÃO entram
        # Cookie, Token, Email Recuperação, Token Email nem "Info Extra" (que traz
        # data de criação + token Microsoft + uuid = lixo que poluía a observação).
        # Esses dados continuam em perfil_data p/ o bot usar; só não aparecem aqui.
        # O '💙 BM EM ANALISE 💙' entra como CABEÇALHO quando a BM vai p/ análise
        # (ver adicionar_tags_perfil) e Email/Senha da BM são anexados no fluxo.
        notas_linhas = []
        if login: notas_linhas.append(f"🆔 Login: {login}")
        if senha: notas_linhas.append(f"🔐 Senha: {senha}")
        if email: notas_linhas.append(f"📧 Email: {email}")
        if senha_email: notas_linhas.append(f"🔐 Senha Email: {senha_email}")
        if tfa: notas_linhas.append(f"🔑 2FA: {tfa}")
        texto_notas = '\n'.join(notas_linhas)

        # Fingerprint (conforme docs oficiais da API)
        fp = dict(FINGERPRINT_BASE)

        # Tags iniciais (login, email) — passamos no create porque o user_tag
        # do create funciona de forma consistente em todas as versoes do AdsPower
        # (ao contrario do update, que ignora silenciosamente em algumas).
        tags_iniciais = []
        if login:
            tags_iniciais.append(f"🆔 {login}")
        if email:
            tags_iniciais.append(f"📧 {email}")

        # ⚠️ `username`/`password` NÃO são mais enviados (2026-08-04).
        # Preenchendo a "conta da plataforma" do AdsPower, o JavaScript DELE
        # digita usuário/senha sozinho ao abrir o facebook.com e ainda mostra a
        # bolha nativa "Fazer login como <ID>". Isso corria contra a digitação do
        # bot: os dois escrevendo no mesmo campo truncavam o ID (visto em campo:
        # '6157710199750' com 13 dígitos em vez dos 14 de '61577101997500') e o
        # perfil morria em "Não foi possível logar no Facebook" / senha inválida.
        # Agora quem preenche é só o bot, sem bolha e sem concorrência.
        # As credenciais continuam visíveis na OBSERVAÇÃO do perfil (remark), e a
        # chave 2FA continua no campo `fakey` — essa não atrapalha, não digita
        # nada sozinha e é útil para o usuário gerar o código na mão.
        payload = {
            'name': nome_perfil,
            'group_id': str(grupo_id),
            'domain_name': 'facebook.com',
            'open_urls': ['https://www.facebook.com'],
            'remark': texto_notas,
            'fingerprint_config': fp,
            'browser_args': {
                'disable-blink-features': 'AutomationControlled',
                'disable-infobars': '1',
                'no-sandbox': '1',
                'lang': 'pt-BR'
            }
        }
        if tags_iniciais:
            payload['user_tag'] = ",".join(tags_iniciais)
            payload['tags'] = tags_iniciais

        # 2FA nativo do AdsPower (campo fakey)
        if tfa:
            payload['fakey'] = tfa

        # Cookies
        if cookie_json:
            cookie_com_locale = _adicionar_cookies_locale(cookie_json)
            payload['cookie'] = cookie_com_locale

        # Proxy (OBRIGATÓRIO conforme docs — usar no_proxy se não houver)
        if proxy_config:
            payload['user_proxy_config'] = proxy_config
        else:
            payload['user_proxy_config'] = {'proxy_soft': 'no_proxy'}

        # Deduplicação: permitir duplicação
        payload['repeat_config'] = [0]

        logger.info("[AdsPower] Criando perfil '%s' no grupo %s...", nome_perfil, grupo_id)

        # Criar — com retry p/ a instabilidade da nuvem do AdsPower ("The server
        # is not working well..."). Antes de cada nova tentativa confere se o
        # perfil NÃO nasceu mesmo assim (o erro pode vir depois do commit no
        # servidor deles) — senão o retry duplicaria o navegador. (2026-10-13)
        res = None
        for _tent in range(4):
            res = _fazer_requisicao('/api/v1/user/create', method='POST', json_data=payload)
            if not (res and res.get('code') == -1 and _erro_transitorio_adspower(res.get('msg'))):
                break
            if _tent == 3:
                break
            _esp = (5, 10, 20)[_tent]
            logger.warning("[AdsPower] create '%s' instável (%s) — nova tentativa em %ss (%d/4)",
                           nome_perfil, str(res.get('msg'))[:60], _esp, _tent + 1)
            time.sleep(_esp)
            existente = buscar_perfil_por_nome(nome_perfil)
            if existente and existente.get('user_id'):
                logger.info("[AdsPower] Perfil '%s' nasceu apesar do erro (ID=%s) — usando-o.",
                            nome_perfil, existente['user_id'])
                return {"sucesso": True, "profile_id": existente['user_id'],
                        "mensagem": f"Perfil {nome_perfil} criado no AdsPower"}
        if not res:
            logger.error("[AdsPower] Nenhuma resposta ao criar perfil '%s'", nome_perfil)
            return {"sucesso": False, "profile_id": None, "mensagem": "Sem resposta da API ao criar perfil"}

        if res.get('code') == 0:
            data = res.get('data', {})
            profile_id = data.get('id') if isinstance(data, dict) else data
            if profile_id:
                logger.info("[AdsPower] Perfil '%s' criado com sucesso: ID=%s", nome_perfil, profile_id)
                return {
                    "sucesso": True,
                    "profile_id": profile_id,
                    "mensagem": f"Perfil {nome_perfil} criado no AdsPower"
                }

        msg_erro = res.get('msg', 'Erro desconhecido')
        logger.error("[AdsPower] Falha ao criar perfil '%s': code=%s msg=%s", nome_perfil, res.get('code'), msg_erro)
        # A mensagem crua do AdsPower ("...exceeds the limit of 602...") não diz o
        # que fazer — e a LIXEIRA é a pegadinha: perfil apagado continua ocupando
        # a cota até ser excluído definitivamente.
        _m = str(msg_erro).lower()
        if 'exceeds the limit' in _m or 'delete some accounts' in _m:
            msg_erro = (f'cota de perfis do AdsPower cheia ({msg_erro}). Apague perfis '
                        f'antigos E ESVAZIE A LIXEIRA do AdsPower — perfis na lixeira '
                        f'continuam ocupando a cota.')
        elif _erro_transitorio_adspower(msg_erro):
            msg_erro = (f'AdsPower sem conexão com o servidor dele após 4 tentativas '
                        f'({msg_erro}). Verifique a internet/VPN do PC e se o AdsPower '
                        f'está logado; o perfil pode ser reprocessado.')
        return {"sucesso": False, "profile_id": None, "mensagem": f"Erro: {msg_erro}"}
    except Exception as e:
        return {"sucesso": False, "profile_id": None, "mensagem": f"Exceção: {str(e)}"}


def _converter_cookie_para_adspower(cookie_obj):
    """Converte um cookie do formato IXBrowser para o formato AdsPower."""
    ads_cookie = {
        'domain': cookie_obj.get('domain', '.facebook.com'),
        'name': cookie_obj.get('name', ''),
        'value': cookie_obj.get('value', ''),
        'path': cookie_obj.get('path', '/'),
        'secure': cookie_obj.get('secure', True),
        'sameSite': cookie_obj.get('sameSite', cookie_obj.get('same_site', 'unspecified')),
    }
    # httpOnly: IXBrowser usa http_only, AdsPower usa httpOnly
    if 'httpOnly' in cookie_obj:
        ads_cookie['httpOnly'] = cookie_obj['httpOnly']
    elif 'http_only' in cookie_obj:
        ads_cookie['httpOnly'] = cookie_obj['http_only']
    else:
        ads_cookie['httpOnly'] = False
    # expirationDate: IXBrowser usa expiration_time, AdsPower usa expirationDate
    if 'expirationDate' in cookie_obj:
        ads_cookie['expirationDate'] = int(cookie_obj['expirationDate'])
    elif 'expiration_time' in cookie_obj:
        try:
            ads_cookie['expirationDate'] = int(cookie_obj['expiration_time'])
        except (ValueError, TypeError):
            ads_cookie['expirationDate'] = int(time.time()) + 365 * 24 * 3600
    else:
        ads_cookie['expirationDate'] = int(time.time()) + 365 * 24 * 3600
    # Corrigir sameSite se veio como "-1" ou valor inválido
    if ads_cookie['sameSite'] in ('-1', '-1', None, ''):
        ads_cookie['sameSite'] = 'unspecified'
    return ads_cookie


def _adicionar_cookies_locale(cookie_json_str):
    """Adiciona cookie locale pt_BR e converte para formato AdsPower."""
    try:
        now_ts = int(time.time())
        exp_ts = now_ts + 365 * 24 * 3600

        locale_cookie = {
            "domain": ".facebook.com",
            "name": "locale",
            "value": "pt_BR",
            "path": "/",
            "secure": True,
            "httpOnly": False,
            "expirationDate": exp_ts,
            "sameSite": "unspecified"
        }

        if cookie_json_str and isinstance(cookie_json_str, str) and cookie_json_str.strip():
            try:
                cookies = json.loads(cookie_json_str)
                if isinstance(cookies, list):
                    # Converter cada cookie para formato AdsPower
                    ads_cookies = [_converter_cookie_para_adspower(c) for c in cookies if isinstance(c, dict)]
                    # Adicionar/atualizar locale
                    has_locale = any(c.get('name') == 'locale' for c in ads_cookies)
                    if not has_locale:
                        ads_cookies.append(locale_cookie)
                    else:
                        for c in ads_cookies:
                            if c.get('name') == 'locale':
                                c['value'] = 'pt_BR'
                    return json.dumps(ads_cookies, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("[AdsPower API] Cookie não é JSON válido: %s", str(e)[:80])

        return json.dumps([locale_cookie], ensure_ascii=False)
    except Exception as e:
        logger.error("[AdsPower API] Erro ao adicionar cookies locale: %s", e)
        return cookie_json_str or ''


# ============================================================================
# ATUALIZAR PERFIL
# ============================================================================

def atualizar_cookies_perfil(profile_id, cookie_json):
    """Atualiza os cookies de um perfil."""
    try:
        cookie_com_locale = _adicionar_cookies_locale(cookie_json)
        res = _fazer_requisicao('/api/v1/user/update', method='POST', json_data={
            'user_id': str(profile_id),
            'cookie': cookie_com_locale
        })
        return bool(res and res.get('code') == 0)
    except Exception as e:
        logger.error("[AdsPower API] Erro ao atualizar cookies: %s", e)
    return False


def atualizar_notas_perfil(profile_id, notas):
    """Atualiza as notas (remark) de um perfil."""
    try:
        res = _fazer_requisicao('/api/v1/user/update', method='POST', json_data={
            'user_id': str(profile_id),
            'remark': notas
        })
        return bool(res and res.get('code') == 0)
    except Exception as e:
        logger.error("[AdsPower API] Erro ao atualizar notas: %s", e)
    return False


def anexar_notas_perfil(profile_id, linhas):
    """Anexa linhas à observação (remark) SEM apagar o que já existe.
    Só grava se conseguir LER a observação atual (evita sobrescrever/perder
    dados). Ignora linhas já presentes. `linhas` = lista de strings."""
    try:
        res = _fazer_requisicao('/api/v1/user/list', params={'user_id': str(profile_id)})
        if not res or res.get('code') != 0:
            logger.warning("[AdsPower API] Não li a observação atual de %s — não anexo (evita perda).", profile_id)
            return False
        data = res.get('data', {})
        lista = data.get('list', []) if isinstance(data, dict) else []
        if not lista or not isinstance(lista[0], dict):
            return False
        atual = str(lista[0].get('remark') or '')
        novas = [l for l in linhas if l and l not in atual]
        if not novas:
            return True
        combinado = (atual + ('\n' if atual else '') + '\n'.join(novas)).strip()
        return atualizar_notas_perfil(profile_id, combinado)
    except Exception as e:
        logger.error("[AdsPower API] Erro ao anexar notas: %s", e)
        return False


def adicionar_tag_perfil(profile_id, nome_tag):
    """Adiciona uma tag ao perfil."""
    return adicionar_tags_perfil(profile_id, [nome_tag])


def _obter_tags_atuais(profile_id):
    """Lê as tags REAIS do perfil via /api/v1/user/list.

    No AdsPower 8.x o campo é 'fbcc_user_tag' = lista de objetos
    {name, color, id} (descoberto por inspeção ao vivo da API). Versões antigas
    usavam 'user_tag'/'tags' (str|list). Retorna lista de NOMES (dedup, ordem)."""
    try:
        res = _fazer_requisicao('/api/v1/user/list',
                                params={'user_id': str(profile_id)})
        if not res or res.get('code') != 0:
            return []
        data = res.get('data', {})
        lista = data.get('list', []) if isinstance(data, dict) else []
        if not lista:
            return []
        item = lista[0] if isinstance(lista[0], dict) else {}
        # AdsPower 8.x: fbcc_user_tag = [{'name':..., 'color':..., 'id':...}, ...]
        fbcc = item.get('fbcc_user_tag')
        if isinstance(fbcc, list) and fbcc:
            nomes = []
            for t in fbcc:
                if isinstance(t, dict):
                    nome = str(t.get('name') or '').strip()
                    if nome:
                        nomes.append(nome)
                elif str(t).strip():
                    nomes.append(str(t).strip())
            if nomes:
                return _tags_dedup(nomes)
        # Legado (versões antigas).
        for campo in ('user_tag', 'tags'):
            val = item.get(campo)
            if not val:
                continue
            if isinstance(val, list):
                return [str(t).strip() for t in val if str(t).strip()]
            if isinstance(val, str):
                return [t.strip() for t in val.split(',') if t.strip()]
        return []
    except Exception as exc:
        logger.debug("[AdsPower API] Nao consegui ler tags atuais de %s: %s",
                     profile_id, exc)
        return []


def obter_perfil(profile_id):
    """Lê UM perfil (dict completo, inclui 'remark') via /api/v1/user/list. {} se falhar.
    Usado no reprocesso automático p/ recuperar as credenciais (remark) do perfil."""
    try:
        res = _fazer_requisicao('/api/v1/user/list', params={'user_id': str(profile_id)})
        if not res or res.get('code') != 0:
            return {}
        data = res.get('data', {})
        lista = data.get('list', []) if isinstance(data, dict) else []
        if lista and isinstance(lista[0], dict):
            it = dict(lista[0])
            it.setdefault('profile_id', it.get('user_id') or str(profile_id))
            return it
    except Exception as exc:
        logger.debug("[AdsPower API] obter_perfil %s: %s", profile_id, exc)
    return {}


def _tags_dedup(seq):
    """Deduplica preservando ordem (case-insensitive)."""
    vistos = set()
    out = []
    for t in seq:
        t = str(t).strip()
        if not t:
            continue
        chave = t.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(t)
    return out


# ============================================================================
# TAGS REAIS (AdsPower API v2) — descoberto por inspeção ao vivo em 2026-09-02
# ============================================================================
# A v1 NÃO seta tag: /api/v1/user/update aceita 'user_tag'/'tags'/'fbcc_user_tag',
# responde code=0 'Success' e ignora silenciosamente (comprovado nas 7 variações).
# O caminho REAL é a v2, cujo nome de campo é 'profile_tag_ids' (não 'tags'):
#
#   POST /api/v2/browser-profile/update
#        {"profile_id": "<id>", "profile_tag_ids": ["<tagId>", ...],
#         "tags_update_type": "1" (substitui tudo) | "2" (acrescenta)}
#
#   POST /api/v2/browser-tags/list    {"page": 1, "limit": 200}
#   POST /api/v2/browser-tags/create  {"tags": [{"name": "...", "color": "..."}]}
#
# As tags são um CATÁLOGO com id próprio: o perfil referencia o ID, não o nome.
# Por isso é preciso resolver nome→id (e criar a tag se ainda não existir).
_TAG_CORES_VALIDAS = ('darkBlue', 'blue', 'purple', 'red', 'yellow',
                      'orange', 'green', 'lightGreen')
_TAG_CACHE = {}            # nome.casefold() -> id
_TAG_CACHE_TS = [0.0]
_TAG_CACHE_TTL = 300.0
_tag_lock = threading.Lock()


# Só as tags de DESFECHO chegam ao perfil (pedido do dono, 2026-09-02): UMA tag,
# no fim do processamento. As intermediárias que o fluxo espalhava — "1 BM CRIADA",
# "Perfil Logado", "DATACRAZY CRIADA", "WABA GUPSHUP CRIADA", "SEM WABA",
# "GS PRIME PLUS", "E-MAIL", "VERIFICAÇÃO PARCIAL", "SEM VERIFICAÇÃO",
# "REUTILIZADO", "REPROCESSADA" — são descartadas AQUI, num ponto só, em vez de
# caçar dezenas de chamadas espalhadas pelo fluxo (menos risco de quebrar algo).
_TAGS_DESFECHO = ('EM ANALISE', 'EM ANÁLISE', 'PERFIL BLOQUEADO', 'BM BLOQUEADA',
                  # RECORRIDA também é DESFECHO: WABA desabilitada com recurso enviado.
                  # Sem isto a tag "♻️ BM RECORRIDA" era DESCARTADA como intermediária
                  # e nunca entrava no perfil (bug 2026-09-26).
                  'RECORRIDA', 'RECORRIDAS',
                  # ── STATUS REAL pós-análise da Meta (2026-10-08) ──────────────────
                  # Estas eram DESCARTADAS por este filtro → a tag de VERIFICADA/Waba/
                  # tier/rejeitada NUNCA entrava no perfil (o Monitor "aplicava" mas
                  # adicionar_tags_perfil jogava fora). Agora são DESFECHO e também são
                  # reconhecidas por definir_tag_desfecho_perfil (troca limpa, sem
                  # empilhar: EM ANALISE → VERIFICADA 2K → REJEITADA, etc.).
                  # 'VERIFICADA' (fem.) NÃO casa "VERIFICAÇÃO PARCIAL" nem "DOMINIO
                  # VERIFICADO" (masc.), então os intermediários seguem descartados.
                  'VERIFICADA', 'VERIFICOU',
                  'WABA ATIVA', 'WABA APROVADA', 'WABA DESABILITADA',
                  'WABA PENDENTE', 'WABA RESTRITA',
                  'REJEITAD', 'PRECISA ATUALIZAR', 'ATUALIZAR BM', 'NAO VERIFICADA',
                  'NÃO VERIFICADA',
                  'TIER 2K', 'TIER 10K', 'TIER 100K', 'TIER ILIMITADA',
                  'BM 2K', 'BM 10K', 'BM 100K', 'BM ILIMITADA', 'ILIMITADA',
                  'BM ERRO', 'ERRO NO ENVIO')


def _e_tag_de_desfecho(nome):
    """True se a tag é um RESULTADO final do perfil (as únicas que vão para o perfil)."""
    n = (nome or '').upper()
    return any(p in n for p in _TAGS_DESFECHO)


def _tag_cor_sugerida(nome):
    """Cor coerente com o significado da tag (o catálogo do usuário já segue isso)."""
    n = (nome or '').upper()
    if 'BLOQUEAD' in n or 'FALHA' in n or 'ERRO' in n:
        return 'red'
    if 'ANALISE' in n or 'ANÁLISE' in n:
        return 'darkBlue'
    # Tiers (subiu o limite) = SUCESSO → VERDE, como pediu o dono (✅ BM 2K/10K/100K/ILIMITADA ✅).
    if ('BM 2K' in n or 'BM 10K' in n or 'BM 100K' in n or 'ILIMITADA' in n
            or 'TIER' in n):
        return 'green'
    if 'VERIFICADA' in n or 'APROVAD' in n or 'SUCESSO' in n:
        return 'green'
    if 'RECORRID' in n or 'NÃO VERIFICOU' in n or 'NAO VERIFICOU' in n:
        return 'orange'
    if 'CRIADA' in n:
        return 'blue'
    return 'darkBlue'


def _tags_catalogo(forcar=False):
    """Catálogo de tags do AdsPower como {nome.casefold(): id}. Cacheado 5 min."""
    with _tag_lock:
        agora = time.monotonic()
        if not forcar and _TAG_CACHE and (agora - _TAG_CACHE_TS[0]) < _TAG_CACHE_TTL:
            return dict(_TAG_CACHE)

    mapa = {}
    pagina = 1
    while pagina <= 20:
        res = _fazer_requisicao('/api/v2/browser-tags/list', method='POST',
                                json_data={'page': pagina, 'limit': 200})
        if not res or res.get('code') != 0:
            break
        data = res.get('data') or {}
        itens = data.get('list') if isinstance(data, dict) else data
        if not isinstance(itens, list) or not itens:
            break
        for t in itens:
            if not isinstance(t, dict):
                continue
            nome = str(t.get('name') or '').strip()
            tid = str(t.get('id') or '').strip()
            if nome and tid:
                mapa[nome.casefold()] = tid
        if len(itens) < 200:
            break
        pagina += 1

    if mapa:
        with _tag_lock:
            _TAG_CACHE.clear()
            _TAG_CACHE.update(mapa)
            _TAG_CACHE_TS[0] = time.monotonic()
    return dict(mapa or _TAG_CACHE)


def _tag_id_ou_criar(nome):
    """Resolve o id da tag pelo nome; cria no catálogo se ainda não existir.

    Só cria quando o catálogo foi lido COM SUCESSO. Sem essa checagem, uma falha
    de leitura (rate-limit, v2 ausente) seria interpretada como "a tag não existe"
    e criaria uma cópia a cada chamada, entupindo o catálogo do usuário."""
    nome = (nome or '').strip()[:50]
    if not nome:
        return None
    cat = _tags_catalogo()
    tid = cat.get(nome.casefold())
    if tid:
        return tid
    if not cat:
        # Catálogo não pôde ser lido — NÃO cria (evita duplicar tag a cada chamada).
        logger.warning("[AdsPower API] Catálogo de tags indisponível; "
                       "não vou criar '%s' às cegas.", nome)
        return None
    cor = _tag_cor_sugerida(nome)
    if cor not in _TAG_CORES_VALIDAS:
        cor = 'darkBlue'
    res = _fazer_requisicao('/api/v2/browser-tags/create', method='POST',
                            json_data={'tags': [{'name': nome, 'color': cor}]})
    if not res or res.get('code') != 0:
        logger.warning("[AdsPower API] Não consegui criar a tag '%s': %s",
                       nome, (res or {}).get('msg'))
        return None
    logger.info("[AdsPower API] Tag '%s' criada no catálogo (cor %s).", nome, cor)
    return _tags_catalogo(forcar=True).get(nome.casefold())


def adicionar_tags_perfil(profile_id, lista_tags):
    """Aplica tags REAIS ao perfil do AdsPower (chip colorido, não a Observação).

    Usa a API v2 (`profile_tag_ids` + `tags_update_type=2`, que ACRESCENTA sem
    apagar as tags que já estão no perfil). Resolve nome→id pelo catálogo e cria
    a tag se ela ainda não existir.

    A Observação NÃO é mais usada para status (pedido do usuário, 2026-09-02): ela
    fica só com os dados do perfil (Login/Senha/Email/2FA). Antes, como a v1 não
    setava tag, o status era espelhado como 1ª linha do remark — desnecessário
    agora que a tag real funciona. Se a v2 falhar, registra o erro e retorna False
    em vez de sujar a Observação."""
    try:
        novas = _tags_dedup(lista_tags or [])
        # Descarta as tags intermediárias — só o DESFECHO fica no perfil.
        descartadas = [t for t in novas if not _e_tag_de_desfecho(t)]
        novas = [t for t in novas if _e_tag_de_desfecho(t)]
        if descartadas:
            logger.debug("[AdsPower API] Tags intermediárias ignoradas: %s", descartadas)
        if not novas:
            return True

        atuais = _obter_tags_atuais(profile_id)
        atuais_lc = {t.casefold() for t in atuais}
        faltando = [t for t in novas if t.casefold() not in atuais_lc]
        if not faltando:
            return True

        # 1) Caminho real (v2): resolve/cria os ids e ACRESCENTA ao perfil.
        ids = [i for i in (_tag_id_ou_criar(t) for t in faltando) if i]
        if ids:
            res = _fazer_requisicao('/api/v2/browser-profile/update', method='POST',
                                    json_data={'profile_id': str(profile_id),
                                               'profile_tag_ids': ids,
                                               'tags_update_type': '2'})
            if res and res.get('code') == 0:
                depois = {t.casefold() for t in _obter_tags_atuais(profile_id)}
                if all(t.casefold() in depois for t in faltando):
                    logger.info("[AdsPower API] Tags %s aplicadas no perfil %s.",
                                faltando, profile_id)
                    return True
                logger.warning("[AdsPower API] v2 respondeu OK mas a tag não entrou "
                               "no perfil %s — usando a Observação.", profile_id)
            else:
                logger.warning("[AdsPower API] /api/v2/browser-profile/update falhou: %s",
                               (res or {}).get('msg'))

        # 2) Não deu: registra e SAI. A Observação não recebe mais status —
        #    ela é só dos dados do perfil (Login/Senha/Email/2FA).
        logger.error("[AdsPower API] Não consegui aplicar as tags %s no perfil %s "
                     "(a Observação não é mais usada como espelho).",
                     faltando, profile_id)
        return False
    except Exception as e:
        logger.error("[AdsPower API] Erro ao adicionar tags: %s", e)
    return False


def _prefixar_cabecalho_observacao(profile_id, cabecalho):
    """Coloca `cabecalho` (ex.: '💙 BM EM ANALISE 💙') como PRIMEIRA linha da
    Observação (remark), sem duplicar e sem perder o que já existe. Só grava se
    conseguir LER a observação atual (evita sobrescrever/perder dados)."""
    cab = (cabecalho or '').strip()
    if not cab:
        return False
    try:
        res = _fazer_requisicao('/api/v1/user/list', params={'user_id': str(profile_id)})
        if not res or res.get('code') != 0:
            logger.warning("[AdsPower API] Não li a observação de %s — não prefixo (evita perda).", profile_id)
            return False
        data = res.get('data', {})
        lista = data.get('list', []) if isinstance(data, dict) else []
        if not lista or not isinstance(lista[0], dict):
            return False
        atual = str(lista[0].get('remark') or '').strip()
        # Remove ocorrências anteriores do cabeçalho (em qualquer linha) p/ não duplicar.
        linhas = [l for l in atual.split('\n') if l.strip() and l.strip() != cab]
        combinado = (cab + ('\n' + '\n'.join(linhas) if linhas else '')).strip()
        if combinado == atual:
            return True
        return atualizar_notas_perfil(profile_id, combinado)
    except Exception as e:
        logger.error("[AdsPower API] Erro ao prefixar cabeçalho na Observação: %s", e)
        return False


def atualizar_nome_perfil(profile_id, novo_nome):
    """Renomeia um perfil."""
    try:
        res = _fazer_requisicao('/api/v1/user/update', method='POST', json_data={
            'user_id': str(profile_id),
            'name': novo_nome
        })
        return bool(res and res.get('code') == 0)
    except Exception as e:
        logger.error("[AdsPower API] Erro ao renomear: %s", e)
    return False


def definir_tag_desfecho_perfil(profile_id, nova_tag):
    """SUBSTITUI a tag de DESFECHO do perfil pela `nova_tag`: remove as tags de
    desfecho antigas (ex.: 'NÃO VERIFICOU') e coloca a nova, mantendo as tags que
    NÃO são de desfecho. Usado no Reutilizar Logados — a 2ª BM tem um resultado novo
    (análise/bloqueada/erro) e a tag antiga não vale mais (não pode EMPILHAR).

    Usa `tags_update_type='1'` (SUBSTITUI todas) com o conjunto desejado completo.
    Se a v2 falhar, retorna False (não suja nada)."""
    try:
        nova = (nova_tag or '').strip()
        if not nova:
            return False
        atuais = _obter_tags_atuais(profile_id)  # nomes
        manter = [t for t in atuais if not _e_tag_de_desfecho(t)]
        desejadas = _tags_dedup(manter + [nova])
        ids = [i for i in (_tag_id_ou_criar(t) for t in desejadas) if i]
        if not ids:
            logger.warning("[AdsPower API] definir_tag_desfecho: sem ids p/ %s.", desejadas)
            return False
        res = _fazer_requisicao('/api/v2/browser-profile/update', method='POST',
                                json_data={'profile_id': str(profile_id),
                                           'profile_tag_ids': ids,
                                           'tags_update_type': '1'})  # 1 = SUBSTITUI
        if res and res.get('code') == 0:
            logger.info("[AdsPower API] Tag de desfecho do perfil %s definida como '%s' (antigas de desfecho removidas).",
                        profile_id, nova)
            return True
        logger.warning("[AdsPower API] definir_tag_desfecho_perfil falhou: %s", (res or {}).get('msg'))
        return False
    except Exception as e:
        logger.error("[AdsPower API] Erro em definir_tag_desfecho_perfil: %s", e)
        return False


def substituir_email_perfil(profile_id, email_novo, email_antigo=''):
    """Troca o e-mail do perfil (no NOME e na OBSERVAÇÃO) pelo `email_novo`. Usado no
    Reutilizar Logados: a 1ª BM foi descartada e a 2ª nasceu com um e-mail NOVO — os
    dados do perfil precisam refletir o e-mail em uso. Só grava se conseguir LER o
    perfil (evita perda). Substitui o `email_antigo` onde aparecer; se não for
    informado, extrai o 1º e-mail do nome/observação."""
    try:
        email_novo = (email_novo or '').strip()
        if not email_novo or '@' not in email_novo:
            return False
        res = _fazer_requisicao('/api/v1/user/list', params={'user_id': str(profile_id)})
        if not res or res.get('code') != 0:
            logger.warning("[AdsPower API] Não li o perfil %s — não troco o e-mail (evita perda).", profile_id)
            return False
        data = res.get('data', {})
        lista = data.get('list', []) if isinstance(data, dict) else []
        if not lista or not isinstance(lista[0], dict):
            return False
        item = lista[0]
        nome_atual = str(item.get('name') or '')
        remark_atual = str(item.get('remark') or '')
        antigo = (email_antigo or '').strip()
        if not antigo:
            import re as _re
            m = _re.search(r'[^\s;,<>]+@[^\s;,<>]+', nome_atual) or _re.search(r'[^\s;,<>]+@[^\s;,<>]+', remark_atual)
            if m:
                antigo = m.group(0).strip()
        ok = True
        # NOME: se contém o e-mail antigo, troca; senão, se o nome INTEIRO é um e-mail, define o novo.
        novo_nome = nome_atual
        if antigo and antigo in nome_atual:
            novo_nome = nome_atual.replace(antigo, email_novo)
        elif '@' in nome_atual and ' ' not in nome_atual.strip():
            novo_nome = email_novo
        if novo_nome != nome_atual:
            ok = atualizar_nome_perfil(profile_id, novo_nome) and ok
        # OBSERVAÇÃO: troca o e-mail antigo onde aparecer (linha "Email:" etc.).
        if antigo and antigo in remark_atual:
            novo_remark = remark_atual.replace(antigo, email_novo)
            if novo_remark != remark_atual:
                ok = atualizar_notas_perfil(profile_id, novo_remark) and ok
        logger.info("[AdsPower API] E-mail do perfil %s trocado: %s -> %s.", profile_id, antigo or '?', email_novo)
        return ok
    except Exception as e:
        logger.error("[AdsPower API] Erro em substituir_email_perfil: %s", e)
        return False


# ============================================================================
# ABRIR / FECHAR NAVEGADOR
# ============================================================================

def deletar_perfil(profile_id):
    """Exclui PERMANENTEMENTE um perfil do AdsPower (vai p/ a lixeira/removido).
    Usado p/ descartar perfis com checkpoint sem saída (captcha de imagem/selfie).
    Endpoint: POST /api/v1/user/delete {'user_ids': [...]}. Retorna True se OK."""
    try:
        res = _fazer_requisicao('/api/v1/user/delete', method='POST', json_data={
            'user_ids': [str(profile_id)]
        })
        ok = bool(res and res.get('code') == 0)
        if ok:
            logger.info("[AdsPower] Perfil %s EXCLUÍDO.", profile_id)
        else:
            logger.warning("[AdsPower] Falha ao excluir perfil %s: %s",
                           profile_id, (res or {}).get('msg', ''))
        return ok
    except Exception as e:
        logger.warning("[AdsPower] Exceção ao excluir perfil %s: %s", profile_id, e)
        return False


def remover_proxy(profile_id):
    """Remove proxy do perfil."""
    try:
        res = _fazer_requisicao('/api/v1/user/update', method='POST', json_data={
            'user_id': str(profile_id),
            'user_proxy_config': {
                'proxy_soft': 'no_proxy'
            }
        })
        return bool(res and res.get('code') == 0)
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
    Abre o navegador de um perfil AdsPower e retorna dados de conexão.
    Compatível com a interface do ixbrowser_api.abrir_navegador().

    janela: dict opcional {x, y, w, h} para POSICIONAR/dimensionar a janela
            (organização em grade quando há vários simultâneos). Ignorado em headless.
    """
    try:
        # Fechar sessão existente
        try:
            fechar_navegador(profile_id)
            time.sleep(1.5)
        except Exception:
            pass

        _largs = ['--disable-notifications', '--lang=pt-BR']
        if _ACEITAR_COOKIES_TERCEIROS:
            # Mantém cookies de terceiros (necessário p/ o Auth0 do Gupshup).
            _largs.append('--disable-features=TrackingProtection3pcd')
        if janela and not headless:
            try:
                _x = int(janela.get('x', 0)); _y = int(janela.get('y', 0))
                _w = int(janela.get('w', 0)); _h = int(janela.get('h', 0))
                if _w > 200 and _h > 200:
                    _largs.append(f'--window-position={_x},{_y}')
                    _largs.append(f'--window-size={_w},{_h}')
                # Janela pequena renderizando em resolução desktop (layout normal).
                _dsf = janela.get('dsf')
                if _dsf and float(_dsf) < 0.999:
                    _largs.append(f'--force-device-scale-factor={_dsf}')
            except Exception:
                pass

        params = {
            'user_id': str(profile_id),
            'open_tabs': '1',
            'ip_tab': '0',
            'launch_args': json.dumps(_largs),
        }
        if headless:
            params['headless'] = '1'

        logger.info("[AdsPower] Abrindo navegador para perfil %s...", profile_id)

        res = _fazer_requisicao('/api/v1/browser/start', params=params)

        if res and res.get('code') == 0:
            data = res.get('data', {})
            ws = data.get('ws', {})
            ws_url = ws.get('puppeteer', '') if isinstance(ws, dict) else str(ws)
            debug_port = data.get('debug_port', '')
            debug_address = ''

            # Obter selenium debug address direto da API
            if isinstance(ws, dict) and ws.get('selenium'):
                debug_address = ws['selenium']
            elif ws_url:
                # Fallback: extrair host:port do ws URL
                # ws://127.0.0.1:XXXXX/devtools/browser/UUID
                try:
                    parts = ws_url.replace('ws://', '').split('/')
                    host_port = parts[0]
                    debug_address = host_port
                    if not debug_port and ':' in host_port:
                        debug_port = host_port.split(':')[1]
                except Exception:
                    pass

            webdriver_path = data.get('webdriver', '')

            logger.info("[AdsPower] Navegador aberto: profile=%s, ws=%s, debug=%s, webdriver=%s",
                       profile_id, ws_url[:60] if ws_url else '', debug_address, webdriver_path[:60] if webdriver_path else '')

            return {
                "sucesso": True,
                "debugging_address": debug_address,
                "debugging_port": debug_port,
                "webdriver": webdriver_path,
                "ws": ws_url,
                "data": data,
                "mensagem": "Navegador aberto no AdsPower"
            }

        msg = res.get('msg', 'Falha ao abrir navegador') if res else 'Sem resposta da API'
        logger.warning("[AdsPower] Falha ao abrir navegador perfil %s: %s", profile_id, msg)
        if retry_without_proxy and ('proxy' in msg.lower() or 'ECONNREFUSED' in msg):
            logger.info("[AdsPower API] Proxy falhou para perfil %s. Removendo proxy...", profile_id)
            remover_proxy(profile_id)
            time.sleep(1.5)
            return abrir_navegador(profile_id, headless=headless, retry_without_proxy=False, janela=janela)

        return {"sucesso": False, "debugging_address": '', "webdriver": '', "ws": '', "data": {}, "mensagem": msg}
    except Exception as e:
        return {"sucesso": False, "debugging_address": '', "webdriver": '', "ws": '', "data": {}, "mensagem": str(e)}


def fechar_navegador(profile_id):
    """Fecha o navegador de um perfil."""
    try:
        res = _fazer_requisicao('/api/v1/browser/stop', params={'user_id': str(profile_id)})
        return bool(res and res.get('code') == 0)
    except Exception:
        return False


# ============================================================================
# LISTAR PERFIS
# ============================================================================

def listar_grupos():
    """Lista os grupos do AdsPower: [{'group_id','group_name'}, ...]."""
    try:
        res = _fazer_requisicao('/api/v1/group/list', params={'page': 1, 'page_size': 2000})
        if res and res.get('code') == 0:
            data = res.get('data', {})
            grupos = data.get('list', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            out = []
            for g in (grupos or []):
                if isinstance(g, dict) and g.get('group_id') is not None:
                    out.append({'group_id': str(g.get('group_id')),
                                'group_name': g.get('group_name', '') or ''})
            return out
    except Exception as e:
        logger.warning("[AdsPower] Erro ao listar grupos: %s", e)
    return []


def listar_perfis(grupo_id=None, page=1, limit=100):
    """Lista perfis do AdsPower."""
    params = {'page': page, 'page_size': limit}
    if grupo_id:
        params['group_id'] = str(grupo_id)

    res = _fazer_requisicao('/api/v1/user/list', params=params)
    if res and res.get('code') == 0:
        data = res.get('data', {})
        perfis = data.get('list', []) if isinstance(data, dict) else data
        return perfis
    return []


# ============================================================================
# MONTAR PROXY CONFIG
# ============================================================================

def montar_proxy_config(proxy_ip='', proxy_porta='', proxy_usuario='', proxy_senha='', proxy_tipo='http'):
    """Monta a configuração de proxy para o AdsPower."""
    if not proxy_ip or not proxy_porta:
        return None

    return {
        'proxy_soft': 'other',
        'proxy_type': proxy_tipo,
        'proxy_host': str(proxy_ip).strip(),
        'proxy_port': str(proxy_porta).strip(),
        'proxy_user': str(proxy_usuario).strip() if proxy_usuario else '',
        'proxy_password': str(proxy_senha).strip() if proxy_senha else ''
    }
