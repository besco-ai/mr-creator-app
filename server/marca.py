#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MARCA E ENDERECOS DA INFRA — FONTE UNICA
=====================================================================
Tudo que e "marca" ou "endereco" do sistema sai daqui. Trocar a marca ou o
dominio no futuro = editar ESTE arquivo e reconstruir.

  - os modulos Python importam daqui (version, acesso, granasocial_db, ...);
  - o `FB_Profile_Manager.spec` (que e Python) tambem importa daqui, entao o
    nome do .exe e da pasta saem daqui tambem;
  - os scripts de build (.bat / .ps1) perguntam ao Python da .venv;
  - a UI (client/*.html|js) usa os marcadores {{MARCA}} {{AUTOR}} {{DOMINIO}}
    {{URL_MAIL}}, substituidos na hora de carregar a janela
    (`substituir_marcadores`).

NAO coloque segredo aqui: este arquivo e versionado e vai dentro do .exe.
"""

# ---- identidade -------------------------------------------------------------
MARCA        = 'MR Farm'                      # nome exibido (janela, UI, rodape)
MARCA_CURTA  = 'MR Farm'                      # nome curto (logs)
MARCA_SLUG   = 'MR_Farm'                      # nome de ARQUIVO: exe, instalador, pasta
AUTOR        = 'mragencia.com'                # campo "author"
EDICAO       = 'Enterprise Shield Edition'

# ---- enderecos da infra -----------------------------------------------------
DOMINIO      = 'farm.mragencia.com'
URL_API      = 'https://farm.mragencia.com/api/software_api.php'
URL_MAIL     = 'https://mail.farm.mragencia.com'
URL_CDN      = 'https://farm.mragencia.com/updates'
URL_MANIFESTO = URL_CDN + '/latest.json'


def versao_completa(versao: str) -> str:
    """Ex.: 'MR Farm v2.7 - Enterprise Shield Edition'."""
    return f'{MARCA} v{versao} - {EDICAO}'


def nome_pacote(versao: str, com_underscore: bool = True) -> str:
    """Nome do instalador publicado: MR_Farm_Setup_v2.7.exe."""
    sep = '_' if com_underscore else ' '
    return f'{MARCA_SLUG}{sep}Setup{sep}v{versao}.exe'


def substituir_marcadores(texto: str) -> str:
    """Troca os marcadores da UI pelos valores atuais."""
    return (texto
            .replace('{{MARCA}}', MARCA)
            .replace('{{MARCA_SLUG}}', MARCA_SLUG)
            .replace('{{AUTOR}}', AUTOR)
            .replace('{{DOMINIO}}', DOMINIO)
            .replace('{{URL_MAIL}}', URL_MAIL))
