#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Imprime o SLUG da marca — usado pelos .bat do build para nomear exe/pasta/instalador.

Existe porque `for /f` do cmd embaralha a linha quando ela mistura aspas do caminho
com aspas de dentro do codigo Python. Chamando este arquivo, a linha do .bat fica
curta e sem aspas internas.

FONTE UNICA: server/marca.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from server import marca  # noqa: E402

print(marca.MARCA_SLUG)