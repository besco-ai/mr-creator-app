#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""GS BM Creator PRO MAX - versao do app (usada pelo auto-updater).

APP_VERSION segue o esquema X.Y decimal desde a 2.0 (o update_server/bump_version.ps1
sobe: 2.0 -> 2.1 -> ... -> 2.9 -> 3.0). O server/atualizador.py importa daqui APP_VERSION,
UPDATE_MANIFEST_URL e APP_NOME; se qualquer um faltar, o import falha e o
atualizador cai no fallback '1.0' (era o bug que quebrava a checagem de versao).
"""

# FONTE UNICA de marca/endereco: server/marca.py
from server import marca as _marca

APP_VERSION = '2.7.4'
APP_NAME = _marca.MARCA
APP_NOME = _marca.MARCA_CURTA
EDITION = _marca.EDICAO
BUILD_DATE = '2026-10-23'
AUTHOR = _marca.AUTOR

# Manifest publico consultado pelo atualizador (CDN da infra nova).
UPDATE_MANIFEST_URL = _marca.URL_MANIFESTO


def get_full_version():
    return _marca.versao_completa(APP_VERSION)
