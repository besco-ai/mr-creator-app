#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Escreve `_marca.iss` (os #define do Inno) a partir da FONTE UNICA.
Chamado pelo instalador\\GERAR_SETUP_X64.bat antes de compilar o setup.

Por que gerar um arquivo em vez de passar por /D: o ISCC nao lida bem com
valor de /D que tem espaco/acento ("Got Agência"), e o nome exibido tem os dois.
Assim a marca continua saindo de server/marca.py, sem gambiarra de aspas.

Uso (da pasta instalador/):  ..\\.venv\\Scripts\\python.exe gerar_marca_iss.py
"""
import sys
import pathlib

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ))

from server import marca          # noqa: E402  (FONTE UNICA)
from server import version        # noqa: E402

SAIDA = AQUI / '_marca.iss'

conteudo = f'''\
; ARQUIVO GERADO por instalador/gerar_marca_iss.py — NAO EDITE A MAO.
; Os valores vem de server/marca.py e server/version.py (fonte unica).
#define MyAppName "{marca.MARCA}"
#define MyAppPublisher "{marca.AUTOR}"
#define MyAppVersion "{version.APP_VERSION}"
#define MyAppSlug "{marca.MARCA_SLUG}"
#define MyAppExeName "{marca.MARCA_SLUG}.exe"
'''

SAIDA.write_text(conteudo, encoding='utf-8')
print(f'[gerar_marca_iss] {SAIDA.name} gerado: {marca.MARCA} v{version.APP_VERSION} ({marca.MARCA_SLUG})')