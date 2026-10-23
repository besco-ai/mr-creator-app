#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import socket
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)
IX_PORT = 53200


def api_respondendo(host='127.0.0.1', port=IX_PORT, timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def obter_caminhos_possiveis_ixbrowser():
    candidatos = []
    env_local = os.environ.get('LOCALAPPDATA', '')
    env_pf = os.environ.get('ProgramFiles', '')
    env_pf86 = os.environ.get('ProgramFiles(x86)', '')
    for raiz in filter(None, [env_local, env_pf, env_pf86]):
        candidatos.extend([
            Path(raiz) / 'IXBrowser' / 'IXBrowser.exe',
            Path(raiz) / 'Programs' / 'IXBrowser' / 'IXBrowser.exe',
            Path(raiz) / 'IXBrowser' / 'Application' / 'IXBrowser.exe',
        ])
    return candidatos


def encontrar_executavel_ixbrowser():
    for caminho in obter_caminhos_possiveis_ixbrowser():
        if caminho.exists():
            return str(caminho)
    return ''


def iniciar_ixbrowser(timeout=25):
    if api_respondendo():
        return True, 'IXBrowser já estava respondendo na API local.'

    exe = encontrar_executavel_ixbrowser()
    if not exe:
        return False, 'IXBrowser.exe não encontrado nas pastas padrão.'

    try:
        logger.info('Iniciando IXBrowser automaticamente: %s', exe)
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return False, f'Falha ao iniciar IXBrowser: {e}'

    limite = time.time() + timeout
    while time.time() < limite:
        if api_respondendo():
            return True, 'IXBrowser iniciado e API local disponível.'
        time.sleep(1)

    return False, 'IXBrowser foi iniciado, mas a API local 127.0.0.1:53200 não respondeu a tempo.'


def garantir_ixbrowser_rodando(timeout=25):
    if api_respondendo():
        return {'ok': True, 'mensagem': 'IXBrowser conectado'}
    ok, msg = iniciar_ixbrowser(timeout=timeout)
    return {'ok': ok, 'mensagem': msg}
