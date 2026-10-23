#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Validador de arquivos .txt provenientes do GranaSocial.
======================================================================
Defesa em DUAS camadas:

  1) HMAC-SHA256 anexado na ULTIMA linha do arquivo.
     Formato:
       # GS-SIG:v1:<usuario_id>:<compra_ids_csv>:<gerado_em_iso>:<hmac_hex>
     O HMAC e calculado sobre:
         usuario_id | compra_ids_csv | gerado_em_iso | sha256(conteudo_sem_sig)
     usando a chave secreta `_HMAC_KEY`. A chave PRECISA ser igual a usada
     pelo painel PHP no momento da geracao do .txt (constante PHP
     `BMCREATOR_HMAC_KEY` ou equivalente).

  2) Verificacao online: cada `compra_id` listado e consultado na
     `granasocial.tb_fb_compras`. Falha se algum:
        - nao existir,
        - nao pertencer ao usuario logado,
        - estiver em status != 'concluida'.

A camada (2) e o que torna a falsificacao impossivel mesmo se a chave
HMAC vazasse — sem uma compra concluida no banco, o software recusa.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Chave HMAC compartilhada com o painel granasocial — NUNCA embutida no codigo.
# Defina GS_HMAC_KEY no ambiente com o MESMO valor do painel PHP (BMCREATOR_HMAC_KEY).
_HMAC_KEY = os.environ.get('GS_HMAC_KEY', '').encode('utf-8')
if not _HMAC_KEY:
    logger.warning('GS_HMAC_KEY nao definida: a assinatura GS-SIG dos .txt nao sera validada.')

_RE_SIG = re.compile(
    r'^\s*#\s*GS-SIG\s*:\s*v1\s*:\s*(\d+)\s*:\s*([\d,\s]*)\s*:\s*([^\s:]+)\s*:\s*([0-9a-fA-F]{64})\s*$'
)


class ValidacaoResultado:
    """Resultado da validacao do arquivo .txt."""

    __slots__ = ('sucesso', 'mensagem', 'perfis', 'compra_ids',
                 'usuario_id_assinatura', 'gerado_em')

    def __init__(self, sucesso=False, mensagem='', perfis=None,
                 compra_ids=None, usuario_id_assinatura=None, gerado_em=None):
        self.sucesso = sucesso
        self.mensagem = mensagem
        self.perfis = perfis or []
        self.compra_ids = compra_ids or []
        self.usuario_id_assinatura = usuario_id_assinatura
        self.gerado_em = gerado_em

    def as_dict(self) -> Dict[str, Any]:
        return {
            'sucesso': self.sucesso,
            'mensagem': self.mensagem,
            'perfis': self.perfis,
            'compra_ids': self.compra_ids,
            'usuario_id_assinatura': self.usuario_id_assinatura,
            'gerado_em': self.gerado_em,
        }


def _ler_arquivo(caminho: str) -> str:
    """Le o arquivo respeitando encoding (utf-8 com fallback latin-1)."""
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        with open(caminho, 'r', encoding='latin-1') as f:
            return f.read()


def _extrair_assinatura(texto: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Procura a linha de assinatura GS-SIG. Retorna (parsed, conteudo_sem_sig).

    A linha de assinatura DEVE ser a ultima linha nao-vazia do arquivo.
    """
    linhas = texto.splitlines()
    # Procurar de tras para frente — a primeira nao-vazia deve ser a sig
    idx_sig = None
    for i in range(len(linhas) - 1, -1, -1):
        if linhas[i].strip():
            idx_sig = i
            break
    if idx_sig is None:
        return None, texto

    m = _RE_SIG.match(linhas[idx_sig])
    if not m:
        return None, texto

    usuario_id = int(m.group(1))
    compra_ids = sorted({int(x) for x in m.group(2).split(',') if x.strip().isdigit()})
    gerado_em = m.group(3)
    hmac_recebido = m.group(4).lower()

    # Conteudo sem a linha de assinatura (mantendo quebra final)
    conteudo_sem_sig = '\n'.join(linhas[:idx_sig]).rstrip() + '\n'

    return ({
        'usuario_id': usuario_id,
        'compra_ids': compra_ids,
        'gerado_em': gerado_em,
        'hmac': hmac_recebido,
    }, conteudo_sem_sig)


def _calcular_hmac(usuario_id: int, compra_ids: List[int],
                   gerado_em: str, conteudo: str) -> str:
    conteudo_sha = hashlib.sha256(
        conteudo.encode('utf-8', errors='replace')
    ).hexdigest()
    payload = '|'.join([
        str(usuario_id),
        ','.join(str(c) for c in compra_ids),
        gerado_em,
        conteudo_sha,
    ]).encode('utf-8')
    return hmac.new(_HMAC_KEY, payload, hashlib.sha256).hexdigest()


def validar_arquivo(caminho: str, user_id_logado: int) -> ValidacaoResultado:
    """Validacao completa do .txt comprado no granasocial.

    Args:
        caminho: caminho absoluto do arquivo .txt
        user_id_logado: id do usuario autenticado na sessao atual

    Retorna ValidacaoResultado.sucesso == True somente se:
      * arquivo legivel
      * tem assinatura GS-SIG v1 valida (HMAC bate)
      * usuario_id na assinatura == usuario logado
      * todos compra_ids existem em tb_fb_compras com status='concluida'
        e pertencem ao usuario
      * parser conseguiu extrair >= 1 perfil
    """
    if not caminho or not os.path.exists(caminho):
        return ValidacaoResultado(sucesso=False,
                                  mensagem='Arquivo nao encontrado.')

    try:
        texto = _ler_arquivo(caminho)
    except Exception as exc:
        return ValidacaoResultado(sucesso=False,
                                  mensagem=f'Falha ao ler arquivo: {exc}')

    sig, conteudo_sem_sig = _extrair_assinatura(texto)
    if not sig:
        return ValidacaoResultado(
            sucesso=False,
            mensagem=(
                'Este arquivo nao e um .txt valido '
                '(assinatura GS-SIG nao encontrada). '
                'Apenas perfis comprados no painel sao aceitos.'
            ),
        )

    hmac_esperado = _calcular_hmac(
        sig['usuario_id'], sig['compra_ids'], sig['gerado_em'], conteudo_sem_sig
    )
    if not hmac.compare_digest(hmac_esperado, sig['hmac']):
        logger.warning(
            '[GS-TXT] HMAC invalido (usuario_id_arq=%s, gerado_em=%s)',
            sig['usuario_id'], sig['gerado_em'],
        )
        return ValidacaoResultado(
            sucesso=False,
            mensagem=(
                'Assinatura do arquivo invalida — pode ter sido editado '
                'apos a compra. Baixe o .txt original novamente no painel.'
            ),
        )

    if int(sig['usuario_id']) != int(user_id_logado):
        return ValidacaoResultado(
            sucesso=False,
            mensagem=(
                'Este arquivo .txt pertence a outra conta GranaSocial. '
                'Faca login com a conta que efetuou a compra.'
            ),
            usuario_id_assinatura=sig['usuario_id'],
        )

    # Camada 2: verificacao online dos compra_ids
    if sig['compra_ids']:
        try:
            from server.granasocial_db import verificar_compras_status
            encontradas = verificar_compras_status(int(user_id_logado), sig['compra_ids'])
        except Exception as exc:
            logger.exception('[GS-TXT] Verificacao online falhou: %s', exc)
            return ValidacaoResultado(
                sucesso=False,
                mensagem=(
                    'Nao foi possivel verificar as compras online. '
                    'Verifique sua conexao e tente novamente.'
                ),
            )

        nao_concluidas = []
        ausentes = []
        for cid in sig['compra_ids']:
            if cid not in encontradas:
                ausentes.append(cid)
            elif encontradas[cid] != 'concluida':
                nao_concluidas.append((cid, encontradas[cid]))

        if ausentes:
            return ValidacaoResultado(
                sucesso=False,
                mensagem=(
                    f'Compras nao encontradas para sua conta: '
                    f'{", ".join(str(c) for c in ausentes[:5])}'
                ),
            )
        if nao_concluidas:
            primeiras = ', '.join(f'#{c}({s})' for c, s in nao_concluidas[:5])
            return ValidacaoResultado(
                sucesso=False,
                mensagem=f'Compras nao concluidas: {primeiras}',
            )

    # Parse dos perfis usando o parser existente
    try:
        from server.parser_perfis import parsear_conteudo_txt
        perfis = parsear_conteudo_txt(conteudo_sem_sig) or []
    except Exception as exc:
        logger.exception('[GS-TXT] Parser falhou: %s', exc)
        return ValidacaoResultado(
            sucesso=False, mensagem=f'Erro ao parsear perfis: {exc}',
        )

    if not perfis:
        return ValidacaoResultado(
            sucesso=False,
            mensagem='Nenhum perfil reconhecido dentro do arquivo.',
        )

    return ValidacaoResultado(
        sucesso=True,
        mensagem=f'{len(perfis)} perfil(is) validados',
        perfis=perfis,
        compra_ids=sig['compra_ids'],
        usuario_id_assinatura=sig['usuario_id'],
        gerado_em=sig['gerado_em'],
    )


def gerar_assinatura(usuario_id: int, compra_ids: List[int],
                     gerado_em: str, conteudo_sem_sig: str) -> str:
    """Util para gerar a linha de assinatura (uso em scripts/testes locais).

    O painel PHP de geracao deve replicar EXATAMENTE este formato e algoritmo.
    """
    cids = sorted({int(c) for c in compra_ids})
    h = _calcular_hmac(int(usuario_id), cids, gerado_em, conteudo_sem_sig)
    cids_csv = ','.join(str(c) for c in cids)
    return f'# GS-SIG:v1:{int(usuario_id)}:{cids_csv}:{gerado_em}:{h}'
