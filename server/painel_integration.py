#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Integração do Creator com o painel GranaSocial — VIA HTTPS (2026-08-12).

Antes conectava no MySQL direto (porta 3306, fechada na blindagem). Agora todas
as operações passam pelo endpoint HTTPS `api/software_api.php` (actions `painel_*`),
que roda na VPS e fala com o MySQL local. As assinaturas foram mantidas idênticas.
Autenticação = username/password da sessão ativa (via granasocial_db._api).
"""

import logging
import re

logger = logging.getLogger(__name__)

DESABILITAR_GRAVACAO_PERFIS_MYSQL = False

COINS_POR_BM = 2.5   # Custo fixo por BM criada


def _api(action, extra=None, timeout=60):
    """Encaminha para o cliente HTTP central (mesma infra/credenciais do login)."""
    try:
        from server.granasocial_db import _api as _gs_api
        return _gs_api(action, extra or {}, timeout=timeout)
    except Exception as exc:
        logger.warning('[Painel] chamada HTTP %s falhou: %s', action, exc)
        return {'sucesso': False}


def obter_usuario_painel(username):
    """Busca os dados do usuário no painel (id, role, tier, balance_available)."""
    resp = _api('painel_usuario')
    if resp.get('sucesso') and isinstance(resp.get('usuario'), dict):
        return resp['usuario']
    return None


def obter_saldo_coins_usuario(username):
    """Retorna o saldo (balance_available) do usuário no painel."""
    user = obter_usuario_painel(username)
    if user:
        return float(user.get('balance_available') or 0)
    return 0.0


def descontar_coins_bm(username, coins_amount=2.5, descricao=''):
    """Debita coins (balance_available) por BM criada. Retorna True se OK."""
    resp = _api('painel_descontar_coins', {
        'coins': float(coins_amount or 0),
        'descricao': descricao or 'BM criada pelo Creator',
    })
    ok = bool(resp.get('sucesso'))
    if ok:
        logger.info("[Painel] %s coins debitados de '%s'", coins_amount, username)
    else:
        logger.warning("[Painel] descontar_coins falhou p/ '%s': %s", username, resp.get('mensagem', ''))
    return ok


def reembolsar_coins_bm(username, coins_amount=2.5, descricao=''):
    """Reembolsa coins ao usuário por BM que falhou. Retorna True se OK."""
    resp = _api('painel_reembolsar_coins', {
        'coins': float(coins_amount or 0),
        'descricao': descricao or 'Reembolso automático Creator',
    })
    ok = bool(resp.get('sucesso'))
    if ok:
        logger.info("[Painel] %s coins reembolsados p/ '%s'", coins_amount, username)
    return ok


def atualizar_status_bm_por_business_id(business_id, novo_status):
    """Atualiza status de uma BM no painel pelo business_id."""
    resp = _api('painel_status_bm_business', {
        'business_id': str(business_id), 'status': str(novo_status),
    })
    return bool(resp.get('sucesso')) and int(resp.get('afetadas') or 0) > 0


# ============================================================================
# MONITOR DE ANÁLISE — mesmas colunas do painel (aguardando_verificacao,
# analysis_started_at, verified_at, rejected_at, check_count, waba_status).
# ============================================================================

def registrar_bm_em_analise(business_id, site_id='', site_url='', empresa_dados=None,
                            profile_id='', metodo_waba='', fb_login=''):
    """Marca o ENVIO p/ análise (analysis_started_at=NOW) + guarda site_id/CNPJ/razão
    (+ perfil: ix_profile_id/fb_login, se ainda vazios — coluna "Perfil" de Minhas BMs)."""
    if DESABILITAR_GRAVACAO_PERFIS_MYSQL:
        return False
    ed = empresa_dados or {}
    resp = _api('painel_bm_em_analise', {
        'business_id': str(business_id),
        'site_id': str(site_id or ''),
        'site_url': str(site_url or ''),
        'cnpj': str(ed.get('cnpj', '') or ''),
        'razao_social': str(ed.get('razao_social', '') or ''),
        'profile_id': str(profile_id or ''),
        'fb_login': str(fb_login or ''),
    })
    ok = bool(resp.get('sucesso')) and int(resp.get('afetadas') or 0) > 0
    logger.info("[Painel] BM %s → em análise (site_id=%s) — ok=%s", business_id, site_id, ok)
    return ok


def listar_bms_para_monitorar(username='', horas=3.0, limite=500):
    """Fila do Monitor: BMs 'aguardando_verificacao' enviadas há >= `horas`.
    Se `username` informado, filtra pelas BMs do usuário logado."""
    try:
        _min = int(float(horas or 3) * 60)
    except Exception:
        _min = 180
    resp = _api('painel_listar_monitorar', {
        'minutos': _min,
        'limite': int(limite),
        'filtrar_user': bool(username),
    })
    if resp.get('sucesso'):
        return list(resp.get('bms') or [])
    return []


def contar_bms_para_monitorar(username='', horas=3.0):
    """Só o total elegível (>= N horas em análise) — p/ o card da GUI."""
    return len(listar_bms_para_monitorar(username=username, horas=horas, limite=100000))


def buscar_bm_por_business_id(business_id):
    """Dados da BM (bm_records) por business_id — p/ RETOMAR uma BM existente."""
    resp = _api('painel_buscar_bm_business', {'business_id': str(business_id)})
    if resp.get('sucesso') and isinstance(resp.get('bm'), dict):
        return resp['bm']
    return None


def reportar_waba_status(business_id, metodo='', waba_status='', recorrida=False,
                         bm_email='', cnpj='', razao_social='', fb_login='', profile_id=''):
    """Reporta ao painel (bm_records) o resultado do MONITOR pós-criação da WABA dos
    fluxos Pro Max DataCrazy (Turbo/Completo). Faz UPSERT por business_id:
      - metodo: 'datacrazy_turbo' | 'datacrazy_completo' (categoriza no painel);
      - waba_status: 'aprovada' | 'desabilitada';
      - recorrida=True → admin_status='recorrida' (WABA caiu e foi recorrida).
    Também grava bm_email/cnpj/razao (ESSENCIAL: o conector GSMAILS→painel casa o
    e-mail da Meta com a BM pelo `bm_email`). Best-effort: nunca quebra o fluxo."""
    if DESABILITAR_GRAVACAO_PERFIS_MYSQL or not business_id:
        return False
    try:
        resp = _api('painel_waba_status', {
            'business_id': str(business_id),
            'metodo': str(metodo or ''),
            'waba_status': str(waba_status or ''),
            'recorrida': '1' if recorrida else '0',
            'bm_email': str(bm_email or ''),
            'cnpj': str(cnpj or ''),
            'razao_social': str(razao_social or ''),
            # perfil (coluna "Perfil" da página Minhas BMs) — gravado só se vazio no painel
            'fb_login': str(fb_login or ''),
            'ix_profile_id': str(profile_id or ''),
        })
        ok = bool(resp.get('sucesso'))
        logger.info("[Painel] WABA %s → metodo=%s status=%s recorrida=%s (ok=%s)",
                    business_id, metodo, waba_status, recorrida, ok)
        return ok
    except Exception as exc:
        logger.warning("[Painel] reportar_waba_status falhou: %s", exc)
        return False


def carimbar_engine_bm(business_id, engine, profile_id=''):
    """Grava no painel qual ENGINE (adspower|ixbrowser) é o perfil desta BM — para a
    re-tag em TEMPO REAL saber onde aplicar a tag sem abrir o navegador. Best-effort."""
    if DESABILITAR_GRAVACAO_PERFIS_MYSQL or not business_id or not engine:
        return False
    try:
        resp = _api('painel_set_engine', {
            'business_id': str(business_id),
            'engine': str(engine)[:16],
            'ix_profile_id': str(profile_id or ''),
        }, timeout=30)
        return bool(resp.get('sucesso'))
    except Exception as exc:
        logger.warning("[Painel] carimbar_engine_bm falhou: %s", exc)
        return False


def listar_bms_reprocessar(limit=200, descanso_horas=2):
    """Puxa do painel as BMs do usuário que precisam ser REENVIADAS para análise
    (reprocesso automático quando o GS Creator está ocioso):
      - motivo 'rejeitada'          → não verificou / precisa + informações
      - motivo 'recorrida_aprovada' → WABA caiu, recorreu e foi RESTAURADA (reenviar)
      - motivo 'erro'               → envio não concluiu; já descansou `descanso_horas`
    Cada item traz business_id, bm_email, fb_login, profile_id, engine, site_id,
    site_url, cnpj, razao_social, meta_status, status, admin_status, waba_status, motivo.
    Retorna lista (vazia em erro)."""
    try:
        resp = _api('painel_bms_reprocessar', {
            'limit': int(limit or 200),
            'descanso_horas': int(descanso_horas or 2),
        }, timeout=45)
        if bool(resp.get('sucesso')):
            return list(resp.get('bms') or [])
    except Exception as exc:
        logger.warning("[Painel] listar_bms_reprocessar falhou: %s", exc)
    return []


def listar_bms_tags(engine=''):
    """Puxa o status atual das BMs do usuário (com perfil vinculado) para RECONCILIAR
    a tag do multilogin em tempo real. Filtra por engine quando informado. Cada item:
    business_id, profile_id, engine, status, meta_status, waba_status,
    bm_limit_category, is_restricted, admin_status, updated_ts. Lista (vazia em erro)."""
    try:
        resp = _api('painel_bms_tags', {'engine': str(engine or '')}, timeout=45)
        if bool(resp.get('sucesso')):
            return list(resp.get('bms') or [])
    except Exception as exc:
        logger.warning("[Painel] listar_bms_tags falhou: %s", exc)
    return []


def perfil_pertence_ao_usuario(profile_id='', bm_email='', fb_login='', engine=''):
    """PORTÃO DE POSSE (2026-10-08) — pergunta ao painel se ESTE perfil é do usuário
    logado. O servidor casa por ix_profile_id (+engine), bm_email OU fb_login nas BMs
    do próprio usuário E nas compras dele (tb_fb_compras). Retorna:
      True  = é um perfil comprado/registrado do GranaSocial;
      False = não bate em nada → NÃO é do GranaSocial;
      None  = falha de rede (o chamador decide; NÃO libera às cegas)."""
    try:
        resp = _api('painel_perfil_proprio', {
            'profile_id': str(profile_id or ''),
            'bm_email': str(bm_email or ''),
            'fb_login': str(fb_login or ''),
            'engine': str(engine or ''),
        }, timeout=30)
        if not resp.get('sucesso'):
            return None
        return bool(resp.get('pertence'))
    except Exception as exc:
        logger.warning('[Painel] perfil_pertence_ao_usuario falhou: %s', exc)
        return None


def reportar_desfecho(business_id, desfecho, mensagem=''):
    """Página "Minhas BMs" (painel, 2026-10-06): grava o DESFECHO do fluxo desta BM
    no GS Creator — 'enviada_analise' | 'bloqueada' | 'recorrida' | 'erro' |
    'checkpoint' | 'sem_verificacao' (+ mensagem curta). Só a BM do próprio usuário
    (o servidor confere user_id). Best-effort: nunca quebra o fluxo."""
    if DESABILITAR_GRAVACAO_PERFIS_MYSQL or not business_id or not desfecho:
        return False
    try:
        resp = _api('painel_bm_desfecho', {
            'business_id': str(business_id),
            'desfecho': str(desfecho),
            'mensagem': str(mensagem or '')[:255],
        }, timeout=30)
        ok = bool(resp.get('sucesso'))
        logger.info("[Painel] desfecho BM %s = %s (ok=%s)", business_id, desfecho, ok)
        return ok
    except Exception as exc:
        logger.warning("[Painel] reportar_desfecho falhou: %s", exc)
        return False


def atualizar_status_analise(business_id, status_analise, waba_status=None):
    """Grava o resultado do Monitor: verificada/rejeitada/nao_verificada/em_analise
    (+ opcional waba_status). Reusa as colunas do painel."""
    if DESABILITAR_GRAVACAO_PERFIS_MYSQL:
        return False
    extra = {'business_id': str(business_id), 'status_analise': str(status_analise)}
    if waba_status is not None:
        extra['waba_status'] = str(waba_status or '')
    resp = _api('painel_status_analise', extra)
    return bool(resp.get('sucesso')) and int(resp.get('afetadas') or 0) > 0


def obter_valor_por_bm(tier):
    """Retorna o valor fixo atual configurado no painel (system_config)."""
    del tier
    resp = _api('painel_valor_bm')
    if resp.get('sucesso'):
        try:
            return float(resp.get('valor'))
        except Exception:
            return 5.0
    return 5.0


def registrar_bm_no_painel(username, profile_name='', bm_name='', bm_email='', fb_login='', business_id='', ix_profile_id='', ix_profile_title='', ix_profile_tags=''):
    """Registra uma BM criada na tabela bm_records do painel GranaSocial."""
    if DESABILITAR_GRAVACAO_PERFIS_MYSQL:
        logger.info("[Painel] Modo teste: BM não gravada. username=%r bm_name=%r", username, bm_name)
        return {'sucesso': True, 'mensagem': 'Modo teste ativo: gravação no painel desabilitada',
                'bm_id': None, 'value_per_bm': 0}

    resp = _api('painel_registrar_bm', {
        'profile_name': profile_name, 'bm_name': bm_name, 'bm_email': bm_email,
        'fb_login': fb_login, 'business_id': business_id, 'ix_profile_id': ix_profile_id,
        'ix_profile_title': ix_profile_title, 'ix_profile_tags': ix_profile_tags,
    })
    if resp.get('sucesso'):
        bm_id = resp.get('bm_id')
        logger.info("[Painel] BM #%s registrada para '%s'", bm_id, username)
        return {'sucesso': True, 'mensagem': f'BM #{bm_id} registrada no painel',
                'bm_id': bm_id, 'value_per_bm': resp.get('value_per_bm', 0)}
    return {'sucesso': False, 'mensagem': resp.get('mensagem') or 'Erro ao registrar BM'}


def registrar_perfil_logado(username, profile_name='', fb_login=''):
    """Registra no log de atividades que um perfil foi logado."""
    if DESABILITAR_GRAVACAO_PERFIS_MYSQL:
        logger.info("[Painel] Modo teste: login de perfil não gravado. username=%r", username)
        return {'sucesso': True, 'mensagem': 'Modo teste ativo: activity_logs desabilitado'}
    _api('painel_perfil_logado', {'profile_name': profile_name, 'fb_login': fb_login})
    return None


def extrair_dados_bm(mensagem_resultado):
    """Extrai nome da BM e email da mensagem de resultado (local, sem DB)."""
    bm_name = ''
    bm_email = ''
    match_nome = re.search(r"BM '([^']+)'", mensagem_resultado)
    if match_nome:
        bm_name = match_nome.group(1)
    match_email = re.search(r'[\w.-]+@[\w.-]+\.\w+', mensagem_resultado)
    if match_email:
        bm_email = match_email.group(0)
    return bm_name, bm_email


def obter_bms_pendentes_checagem(username, limit=10):
    """BMs 'em_processamento' pendentes de checagem."""
    del username
    resp = _api('painel_bms_pendentes', {'limit': int(limit or 10)})
    if resp.get('sucesso'):
        return list(resp.get('bms') or [])
    return []


def atualizar_status_bm_no_painel(bm_id, status):
    """Atualiza o status da BM (bm_records) por id interno."""
    resp = _api('painel_status_bm_id', {'bm_id': int(bm_id), 'status': str(status)})
    return bool(resp.get('sucesso')) and int(resp.get('afetadas') or 0) > 0
