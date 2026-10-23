# -*- coding: utf-8 -*-

"""
BM Queue Manager — Fila de BMs aguardando verificação
======================================================
Gerencia a fila de BMs criadas que aguardam o período mínimo de
espera (2 horas) antes de serem verificadas (empresa + domínio).

Persistência em JSON para sobreviver a reinicializações do software.
"""

import json
import os
import time
import logging
import threading

logger = logging.getLogger(__name__)

# Caminho do arquivo de fila — na pasta config/ ao lado do executável
_QUEUE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config')
_QUEUE_FILE = os.path.join(_QUEUE_DIR, 'bm_verificacao_fila.json')

# Tempo mínimo de espera em segundos (2 horas)
TEMPO_MINIMO_ESPERA = 2 * 60 * 60  # 7200 segundos

# Lock para acesso thread-safe
_lock = threading.Lock()


def _garantir_diretorio():
    """Garante que o diretório da fila existe."""
    os.makedirs(_QUEUE_DIR, exist_ok=True)


def _carregar_fila():
    """Carrega a fila do arquivo JSON."""
    try:
        if os.path.exists(_QUEUE_FILE):
            with open(_QUEUE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as e:
        logger.error("[FilaBM] Erro ao carregar fila: %s", e)
    return []


def _salvar_fila(fila):
    """Salva a fila no arquivo JSON."""
    try:
        _garantir_diretorio()
        with open(_QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(fila, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("[FilaBM] Erro ao salvar fila: %s", e)


def adicionar_bm_na_fila(dados):
    """
    Adiciona uma BM criada à fila de verificação.

    Args:
        dados (dict): Deve conter:
            - profile_id: ID do perfil no browser (IXBrowser/AdsPower)
            - business_id: ID do Business Manager no Facebook
            - bm_name: Nome da BM
            - bm_email: Email usado na BM
            - fb_login: Login do Facebook
            - empresa_dados: Dict com dados da empresa (razão social, endereço, etc.)
            - site_cache: Dict com dados do site (site_id, url, etc.)
            - nome_bm_override: Nome da BM (para "Nome da conta")
            - seu_nome_override: Nome abreviado (para "Seu nome")
            - compra_id: ID da compra (para coins)
            - browser_engine: 'ixbrowser' ou 'adspower'
            - usuario: Usuário logado
    """
    with _lock:
        fila = _carregar_fila()

        # Verificar se já existe na fila (mesmo profile_id + business_id)
        for item in fila:
            if (item.get('profile_id') == dados.get('profile_id') and
                item.get('business_id') == dados.get('business_id')):
                logger.info("[FilaBM] BM já existe na fila: profile=%s bid=%s",
                            dados.get('profile_id'), dados.get('business_id'))
                return False

        entrada = {
            'profile_id': dados.get('profile_id', ''),
            'business_id': dados.get('business_id', ''),
            'bm_name': dados.get('bm_name', ''),
            'bm_email': dados.get('bm_email', ''),
            'fb_login': dados.get('fb_login', ''),
            'empresa_dados': dados.get('empresa_dados', {}),
            'site_cache': dados.get('site_cache', {}),
            'nome_bm_override': dados.get('nome_bm_override', ''),
            'seu_nome_override': dados.get('seu_nome_override', ''),
            'compra_id': dados.get('compra_id', 0),
            'browser_engine': dados.get('browser_engine', 'ixbrowser'),
            'usuario': dados.get('usuario', ''),
            'criado_em': time.time(),
            'criado_em_str': time.strftime('%d/%m/%Y %H:%M:%S'),
            'status': 'aguardando',  # aguardando | verificando | verificada | erro
            'verificado_em': None,
            'mensagem': '',
        }

        fila.append(entrada)
        _salvar_fila(fila)
        logger.info("[FilaBM] BM adicionada à fila: profile=%s bm=%s (total: %d)",
                     entrada['profile_id'], entrada['bm_name'], len(fila))
        return True


def obter_fila_completa():
    """Retorna toda a fila com status calculado."""
    with _lock:
        fila = _carregar_fila()

    agora = time.time()
    resultado = []

    for item in fila:
        criado = item.get('criado_em', 0)
        tempo_passado = agora - criado
        tempo_restante = max(0, TEMPO_MINIMO_ESPERA - tempo_passado)
        pronta = tempo_restante <= 0

        resultado.append({
            **item,
            'tempo_passado_seg': int(tempo_passado),
            'tempo_restante_seg': int(tempo_restante),
            'pronta_para_verificar': pronta and item.get('status') == 'aguardando',
        })

    return resultado


def obter_resumo_fila():
    """Retorna resumo da fila para a UI."""
    fila = obter_fila_completa()

    total = len(fila)
    aguardando = sum(1 for f in fila if f.get('status') == 'aguardando')
    prontas = sum(1 for f in fila if f.get('pronta_para_verificar'))
    verificadas = sum(1 for f in fila if f.get('status') == 'verificada')
    erros = sum(1 for f in fila if f.get('status') == 'erro')
    verificando = sum(1 for f in fila if f.get('status') == 'verificando')

    # Calcular tempo até a próxima BM ficar pronta
    proxima_pronta_seg = 0
    for item in fila:
        if item.get('status') == 'aguardando' and not item.get('pronta_para_verificar'):
            restante = item.get('tempo_restante_seg', 0)
            if proxima_pronta_seg == 0 or restante < proxima_pronta_seg:
                proxima_pronta_seg = restante

    return {
        'total': total,
        'aguardando': aguardando,
        'prontas': prontas,
        'verificadas': verificadas,
        'erros': erros,
        'verificando': verificando,
        'proxima_pronta_min': int(proxima_pronta_seg / 60) if proxima_pronta_seg > 0 else 0,
        'itens': fila,
    }


def obter_bms_prontas():
    """Retorna apenas as BMs que já passaram 2 horas e estão prontas."""
    fila = obter_fila_completa()
    return [f for f in fila if f.get('pronta_para_verificar')]


def atualizar_status_bm(profile_id, business_id, status, mensagem=''):
    """
    Atualiza o status de uma BM na fila.

    Args:
        status: 'aguardando' | 'verificando' | 'verificada' | 'erro'
    """
    with _lock:
        fila = _carregar_fila()
        for item in fila:
            if (item.get('profile_id') == profile_id and
                item.get('business_id') == business_id):
                item['status'] = status
                item['mensagem'] = mensagem
                if status == 'verificada':
                    item['verificado_em'] = time.time()
                break
        _salvar_fila(fila)


def remover_bm_da_fila(profile_id, business_id):
    """Remove uma BM específica da fila."""
    with _lock:
        fila = _carregar_fila()
        fila_nova = [f for f in fila if not (
            f.get('profile_id') == profile_id and
            f.get('business_id') == business_id)]
        _salvar_fila(fila_nova)
        removidos = len(fila) - len(fila_nova)
        if removidos:
            logger.info("[FilaBM] Removida BM: profile=%s bid=%s", profile_id, business_id)
        return removidos > 0


def limpar_verificadas():
    """Remove todas as BMs já verificadas da fila."""
    with _lock:
        fila = _carregar_fila()
        fila_nova = [f for f in fila if f.get('status') != 'verificada']
        _salvar_fila(fila_nova)
        removidos = len(fila) - len(fila_nova)
        logger.info("[FilaBM] Removidas %d BMs verificadas da fila", removidos)
        return removidos
