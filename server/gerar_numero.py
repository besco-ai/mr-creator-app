#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gerador de Números de Telefone Brasileiros (Fake mas Válidos)
=============================================================
Gera números de celular brasileiros com formato válido para preencher
o campo "Telefone comercial" na verificação de BM do Facebook.

Os números são gerados aleatoriamente com DDDs reais e formato 9XXXX-XXXX.
No futuro, o número pode ser substituído manualmente pelo real.
"""

from random import choice, randint


# DDDs brasileiros mais comuns (capitais e grandes cidades)
DDDS_BRASIL = [
    "11",  # São Paulo - SP
    "12",  # São José dos Campos - SP
    "16",  # Ribeirão Preto - SP
    "19",  # Campinas - SP
    "21",  # Rio de Janeiro - RJ
    "31",  # Belo Horizonte - MG
    "34",  # Uberlândia - MG
    "38",  # Montes Claros - MG
    "41",  # Curitiba e Região - PR
    "51",  # Porto Alegre e Região - RS
    "61",  # Brasília e Região - DF
    "62",  # Goiânia e Região - GO
    "71",  # Salvador e Região - BA
]


def gerar_numero_aleatorio():
    """Gera um número de celular brasileiro aleatório no formato 55DDXXXXXXXXX.

    O número segue o padrão real brasileiro:
    - Código do país: 55
    - DDD: 2 dígitos de uma capital/grande cidade
    - Número: 9 + 8 dígitos (celular)

    Returns:
        str: Número no formato '55DD9XXXXXXXX' (ex: '5511997100000')
    """
    return f'55{choice(DDDS_BRASIL)}9{randint(97100000, 99999999)}'
