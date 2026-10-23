#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Funções de controle da janela PyWebView.
"""

import sys
from webview import windows


def fechar():
    """Fecha a aplicação."""
    try:
        windows[0].destroy()
    except:
        sys.exit(0)


def minimizar():
    """Minimiza a janela."""
    try:
        windows[0].minimize()
    except:
        pass
