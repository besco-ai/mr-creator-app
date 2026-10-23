#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cliente CapSolver — resolução de reCAPTCHA (v1.0)
=================================================
Resolve o captcha "Ajude-nos a confirmar que é você" que o Facebook exibe na
verificação de NEGÓCIO (Central de Segurança). Confirmado em produção que é o
**reCAPTCHA Enterprise** (servido em iframe fbsbx.com, sitekey
6LdktRgnAAAAAFQ6icovYI2-masYLFjEFyzQzpix, api.js do Google).

O usuário informa a API key do CapSolver na GUI (campo "Token API Captcha
(CapSolver)" — já existente, `captcha_token`).

API (https://docs.capsolver.com):
  POST /createTask     {clientKey, task:{type, websiteURL, websiteKey, ...}}
  POST /getTaskResult  {clientKey, taskId}  -> solution.gRecaptchaResponse
  POST /getBalance     {clientKey}

A INJEÇÃO do token na página é feita pela etapa (que tem o driver). Aqui só
obtemos o token (gRecaptchaResponse).
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

API_BASE = 'https://api.capsolver.com'
HTTP_TIMEOUT = 30

# Sitekey fixo observado na tela do Facebook (fallback caso a leitura do DOM
# falhe). A etapa tenta SEMPRE ler o data-sitekey real antes de usar este.
SITEKEY_FACEBOOK_PADRAO = '6LdktRgnAAAAAFQ6icovYI2-masYLFjEFyzQzpix'


class CapSolverError(Exception):
    pass


class CapSolverClient:
    def __init__(self, api_key):
        self.api_key = (api_key or '').strip()
        self._sessao = requests.Session()

    def _post(self, path, payload, timeout=HTTP_TIMEOUT):
        url = f'{API_BASE}{path}'
        try:
            resp = self._sessao.post(url, json=payload, timeout=timeout)
            return resp.json()
        except Exception as exc:
            logger.error('[CapSolver] Erro em %s: %s', path, exc)
            return {'errorId': 1, 'errorDescription': str(exc)}

    # ------------------------------------------------------------------ #
    def saldo(self):
        """Retorna o saldo da conta CapSolver (float) ou None."""
        r = self._post('/getBalance', {'clientKey': self.api_key})
        if r and r.get('errorId') == 0:
            try:
                return float(r.get('balance') or 0)
            except Exception:
                return None
        return None

    # ------------------------------------------------------------------ #
    def resolver_recaptcha(self, website_url, website_key=None,
                           enterprise=True, page_action=None,
                           timeout=180, intervalo=4):
        """Resolve um reCAPTCHA v2 (Enterprise por padrão) e devolve o token.

        Args:
            website_url: URL da página onde o captcha aparece
                         (ex.: 'https://business.facebook.com/...').
            website_key: data-sitekey. Se None, usa o padrão do Facebook.
            enterprise:  True → ReCaptchaV2EnterpriseTaskProxyLess;
                         False → ReCaptchaV2TaskProxyLess.
            page_action: ação (enterprise), opcional.
            timeout:     tempo máximo de espera pela solução.

        Returns dict {'sucesso': bool, 'token': str, 'mensagem': str}
        """
        if not self.api_key:
            return {'sucesso': False, 'token': '',
                    'mensagem': 'API key do CapSolver não configurada.'}

        site_key = (website_key or '').strip() or SITEKEY_FACEBOOK_PADRAO
        tipo = ('ReCaptchaV2EnterpriseTaskProxyLess' if enterprise
                else 'ReCaptchaV2TaskProxyLess')

        task = {
            'type': tipo,
            'websiteURL': website_url,
            'websiteKey': site_key,
        }
        if enterprise and page_action:
            # A ação vai em `pageAction` (top-level). NÃO em enterprisePayload['s']:
            # o `s` do CapSolver é um TOKEN adicional que alguns sites injetam na
            # página — mandar a action ali produz um token que o Facebook recusa.
            # A action real do login do FB é `fb_login_recaptcha` (lida do `sa=`
            # da URL do iframe).
            task['pageAction'] = page_action

        criar = self._post('/createTask', {
            'clientKey': self.api_key,
            'task': task,
        })

        if not criar or criar.get('errorId') != 0:
            desc = (criar or {}).get('errorDescription', 'erro desconhecido')
            logger.warning('[CapSolver] createTask falhou: %s', desc)
            return {'sucesso': False, 'token': '',
                    'mensagem': f'createTask: {desc}'}

        task_id = criar.get('taskId')
        if not task_id:
            return {'sucesso': False, 'token': '',
                    'mensagem': 'createTask sem taskId.'}

        logger.info('[CapSolver] Task criada (%s) — aguardando solução...', task_id)

        inicio = time.time()
        # Primeira leitura só depois de alguns segundos (o solve leva tempo).
        time.sleep(min(8, timeout))
        while time.time() - inicio < timeout:
            res = self._post('/getTaskResult', {
                'clientKey': self.api_key,
                'taskId': task_id,
            })
            if not res:
                time.sleep(intervalo)
                continue
            if res.get('errorId') not in (0, None):
                desc = res.get('errorDescription', 'erro')
                logger.warning('[CapSolver] getTaskResult erro: %s', desc)
                return {'sucesso': False, 'token': '',
                        'mensagem': f'getTaskResult: {desc}'}
            status = res.get('status')
            if status == 'ready':
                sol = res.get('solution', {}) or {}
                token = (sol.get('gRecaptchaResponse')
                         or sol.get('token') or '')
                if token:
                    logger.info('[CapSolver] Captcha resolvido (%d chars).',
                                len(token))
                    return {'sucesso': True, 'token': token,
                            'mensagem': 'Captcha resolvido.'}
                return {'sucesso': False, 'token': '',
                        'mensagem': 'Solução sem token.'}
            # status == 'processing' / 'idle' → continua aguardando
            time.sleep(intervalo)

        return {'sucesso': False, 'token': '',
                'mensagem': f'CapSolver não resolveu em {timeout}s.'}


    # ------------------------------------------------------------------ #
    def classificar_grade(self, image_b64, question, website_url=None,
                          website_key=None):
        """Classificação de IMAGEM do desafio do reCAPTCHA (grade 3x3 / 4x4).

        Diferente de `resolver_recaptcha`: aqui o CapSolver NÃO gera token — ele
        só diz QUAIS quadradinhos clicar. Quem clica é o nosso navegador, então o
        token nasce no IP e no fingerprint do PRÓPRIO perfil. É por isso que este
        caminho existe: o token proxyless do `resolver_recaptcha` é recusado pela
        Meta na tela de login (testado em 2026-08-08 — o Facebook devolvia o
        formulário de login toda vez).

        `question`: código do Knowledge Graph ('/m/014xcs') ou o nome em inglês.
        Retorna {'sucesso': bool, 'indices': [int], 'mensagem': str}.
        """
        if not self.api_key:
            return {'sucesso': False, 'indices': [],
                    'mensagem': 'API key do CapSolver não configurada.'}

        task = {
            'type': 'ReCaptchaV2Classification',
            'image': image_b64,
            'question': question,
        }
        # Opcionais que a doc recomenda para melhorar a precisão.
        if website_url:
            task['websiteURL'] = website_url
        if website_key:
            task['websiteKey'] = website_key

        r = self._post('/createTask', {
            'clientKey': self.api_key,
            'task': task,
        }, timeout=60)

        if not r or r.get('errorId') not in (0, None):
            desc = (r or {}).get('errorDescription', 'erro desconhecido')
            return {'sucesso': False, 'indices': [], 'mensagem': desc}

        sol = r.get('solution') or {}
        logger.info('[CapSolver] classificação resposta: %s', str(sol)[:300])
        objetos = sol.get('objects')
        if objetos is None:
            objetos = sol.get('box') or []
        objetos = list(objetos or [])

        # Pela doc, `objects` no modo "multi" é a lista de ÍNDICES dos quadrados
        # a clicar. Só quando vem uma lista de booleans é máscara posição-a-posição
        # (NÃO tratar [0,1] de índices como máscara — marcaria o quadrado errado).
        if objetos and all(isinstance(v, bool) for v in objetos):
            indices = [i for i, v in enumerate(objetos) if v]
        else:
            indices = [int(v) for v in objetos if isinstance(v, (int, float))]
        return {'sucesso': True, 'indices': indices, 'mensagem': 'ok',
                'tipo': sol.get('type', ''), 'tem_objeto': bool(sol.get('hasObject')),
                'bruto': sol}


# ── CAPTCHA CENTRAL (2026-08-30) ───────────────────────────────────────────
# True = o captcha é resolvido no SERVIDOR (chave CapSolver do ADMIN, oculta do
# cliente, GRÁTIS). O `api_key` passado pelos call-sites é IGNORADO neste modo.
# False = comportamento legado (chave local do usuário). Os 3 call-sites usam os
# ATALHOS abaixo, então rotear aqui cobre todos SEM mexer neles.
_CAPTCHA_CENTRAL = True


def token_necessario():
    """False quando o captcha é resolvido no SERVIDOR (chave do admin).

    Depois que o campo do CapSolver saiu da GUI e a resolução migrou para o painel,
    o token LOCAL passou a ser sempre vazio — mas vários call-sites ainda tinham um
    gate `if not captcha_token: aborta` ANTES de chamar o solver. Resultado: o bot
    chegava no captcha e desistia sem nem tentar (o painel resolveria de graça), e
    o fluxo voltava ao início em loop. Os gates agora consultam esta função.
    """
    return not _CAPTCHA_CENTRAL


def _painel_captcha(action, extra):
    """POST na software_api (creds da sessão). Import lazy p/ evitar circular."""
    try:
        from server import acesso
        return acesso._api_post(action, extra, timeout=60) or {}
    except Exception as e:
        logger.error('[CapSolver/painel] %s falhou: %s', action, e)
        return {'sucesso': False, 'mensagem': str(e)}


def _resolver_recaptcha_painel(website_url, website_key=None, enterprise=True,
                               page_action=None, timeout=180):
    site_key = (website_key or '').strip() or SITEKEY_FACEBOOK_PADRAO
    extra = {'tipo': 'recaptcha', 'website_url': website_url,
             'website_key': site_key, 'enterprise': '1' if enterprise else '0'}
    if page_action:
        extra['page_action'] = page_action
    criar = _painel_captcha('captcha_criar', extra)
    if not criar.get('sucesso'):
        return {'sucesso': False, 'token': '',
                'mensagem': criar.get('mensagem', 'CapSolver (painel) createTask falhou.')}
    task_id = criar.get('task_id')
    if not task_id:
        return {'sucesso': False, 'token': '', 'mensagem': 'CapSolver (painel) sem task_id.'}
    logger.info('[CapSolver/painel] Task %s — aguardando...', task_id)
    inicio = time.time()
    time.sleep(min(8, timeout))
    while time.time() - inicio < timeout:
        res = _painel_captcha('captcha_status', {'task_id': task_id})
        if res.get('sucesso'):
            if res.get('estado') == 'ready':
                token = res.get('token') or ''
                if token:
                    logger.info('[CapSolver/painel] Resolvido (%d chars).', len(token))
                    return {'sucesso': True, 'token': token, 'mensagem': 'Captcha resolvido.'}
                return {'sucesso': False, 'token': '', 'mensagem': 'Solução sem token.'}
            # estado == 'processing' → continua aguardando
        else:
            return {'sucesso': False, 'token': '',
                    'mensagem': res.get('mensagem', 'CapSolver (painel) erro.')}
        time.sleep(4)
    return {'sucesso': False, 'token': '',
            'mensagem': f'CapSolver (painel) não resolveu em {timeout}s.'}


def _classificar_grade_painel(image_b64, question, website_url=None, website_key=None):
    extra = {'tipo': 'grade', 'image': image_b64, 'question': question}
    if website_url:
        extra['website_url'] = website_url
    if website_key:
        extra['website_key'] = website_key
    res = _painel_captcha('captcha_criar', extra)
    if res.get('sucesso'):
        return {'sucesso': True, 'indices': list(res.get('indices') or []),
                'mensagem': 'ok', 'tipo': res.get('tipo', ''),
                'tem_objeto': bool(res.get('tem_objeto'))}
    return {'sucesso': False, 'indices': [],
            'mensagem': res.get('mensagem', 'CapSolver (painel) erro.')}


def classificar_grade(api_key, image_b64, question, website_url=None,
                      website_key=None):
    """Atalho funcional — no modo central resolve no painel (api_key ignorado)."""
    if _CAPTCHA_CENTRAL:
        return _classificar_grade_painel(image_b64, question,
                                         website_url=website_url, website_key=website_key)
    return CapSolverClient(api_key).classificar_grade(
        image_b64, question, website_url=website_url, website_key=website_key)


def resolver_recaptcha(api_key, website_url, website_key=None, enterprise=True,
                       page_action=None, timeout=180):
    """Atalho funcional — no modo central resolve no painel (api_key ignorado)."""
    if _CAPTCHA_CENTRAL:
        return _resolver_recaptcha_painel(website_url, website_key=website_key,
                                          enterprise=enterprise, page_action=page_action,
                                          timeout=timeout)
    return CapSolverClient(api_key).resolver_recaptcha(
        website_url, website_key=website_key, enterprise=enterprise,
        page_action=page_action, timeout=timeout)
