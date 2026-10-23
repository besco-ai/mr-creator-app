"""
Estado GLOBAL de PAUSA/CANCELAMENTO da execução — módulo leve e SEM dependências
(evita import circular entre backend.py e as etapas). Fonte da verdade única para:

  - PAUSAR/CONTINUAR o fluxo (manual pelo usuário OU automático quando o SMS fica sem
    saldo/sem número — em vez de descartar perfis bons, o fluxo PAUSA e aguarda).
  - CANCELAR (aborta 100%: acorda quem está pausado/esperando e o backend fecha os
    navegadores abertos).

Qualquer módulo faz: `from server import pausa` e usa `pausa.aguardar_se_pausado(...)`.
"""
import time
import logging

logger = logging.getLogger("GS_BM_Creator.Pausa")

_flags = {'pausado': False, 'cancelar': False}


def reset():
    """Zera as flags no início de um run."""
    _flags['pausado'] = False
    _flags['cancelar'] = False


def set_pausado(v: bool):
    _flags['pausado'] = bool(v)
    logger.info("[Pausa] pausado=%s", _flags['pausado'])


def is_pausado() -> bool:
    return bool(_flags['pausado'])


def set_cancelar(v: bool):
    _flags['cancelar'] = bool(v)
    if v:
        # Cancelar SEMPRE despausa (para acordar quem está esperando e ele ver o cancel).
        _flags['pausado'] = False
    logger.info("[Pausa] cancelar=%s", _flags['cancelar'])


def is_cancelar() -> bool:
    return bool(_flags['cancelar'])


def aguardar_se_pausado(status_cb=None, motivo='') -> bool:
    """BLOQUEIA enquanto estiver PAUSADO (checando em fatias curtas). Sai quando o
    usuário clica Continuar (despausa) OU quando é CANCELADO.
    Retorna True se pode seguir; False se foi CANCELADO (o chamador deve abortar)."""
    _avisou = False
    while _flags['pausado'] and not _flags['cancelar']:
        if status_cb and not _avisou:
            try:
                status_cb(f'⏸️ PAUSADO {motivo}— clique em Continuar para retomar.')
            except Exception:
                pass
            _avisou = True
        time.sleep(2)
    return not _flags['cancelar']
