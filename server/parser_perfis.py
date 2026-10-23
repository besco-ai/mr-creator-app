#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Parser de Perfis - Importação de arquivos .txt (v24 - Novo Formato)
====================================================================
Suporta múltiplos formatos de entrada:

FORMATO 1 - Pipe inline (uma linha, múltiplas contas coladas):
  ID|SENHA|COOKIES|TOKEN|EMAIL|SENHA_EMAIL[ID|SENHA|COOKIES|TOKEN|EMAIL|SENHA_EMAIL...]
  Nota: entre contas, a SENHA_EMAIL e o próximo ID ficam colados sem separador.

FORMATO 2 - Com rótulos (multi-linha):
  Login: 61576574048182
  Senha: datHGxXCmj10
  2FA: 3LHAGJMRHNKVNRC66TVC6KOQXVKBSEIG
  Email: dat4qphpsvusq@dropinboxes.com
  Cookie: c_user=...;xs=...;fr=...;datr=...;
  Token: EAAAAUaZA8jlABO...

FORMATO 3 - Com rótulos (variante sem 2FA):
  Login: 61582758405847
  Senha: BQzyGWQK
  Email: chickieadams@hotmail.com
  Senha do Email: qE8mhrEPUE
  Cookies: c_user=...; xs=...; fr=...; datr=...
  Token: EAAAAUaZA8jlABQ...

FORMATO 4 - Pipe separado por linhas:
  ID|SENHA|COOKIES|TOKEN|EMAIL|SENHA_EMAIL
  (uma conta por linha)

FORMATO 5 - Dois pontos separados por linhas:
  ID:SENHA:EMAIL:COOKIES:TOKEN

FORMATO 6 - Pipe inline com 2FA (contas coladas, email no final):
  ID|SENHA|2FA|COOKIES|TOKEN|EMAIL[próximo_ID|SENHA|2FA|COOKIES|TOKEN|EMAIL...]
  Nota: O email do último campo fica colado com o ID da próxima conta.
  Campos: ID(14-16 dígitos) | SENHA(curta) | 2FA(32 chars upper) | COOKIES(c_user=...) | TOKEN(EAAA...) | EMAIL(@...)

- Cookies em formato string ou Base64
"""

import re
import json
import time
import base64

# Domínios de email que costumam ter senha separada
_EMAIL_COM_SENHA = {
    'hotmail.com', 'hotmail.com.br', 'outlook.com', 'outlook.com.br',
    'live.com', 'msn.com', 'yahoo.com', 'yahoo.com.br',
    'aol.com', 'icloud.com', 'me.com', 'mail.com',
    'protonmail.com', 'zoho.com', 'gmx.com', 'yandex.com',
}

def _email_tem_senha_separada(email):
    """Verifica se o email é de um provedor que costuma ter senha separada (Hotmail, Outlook, etc.)."""
    if not email or '@' not in email:
        return False
    dominio = email.split('@')[-1].lower().strip()
    return dominio in _EMAIL_COM_SENHA


def parsear_arquivo_txt(caminho_arquivo):
    """Lê um arquivo .txt e retorna lista de perfis."""
    with open(caminho_arquivo, 'r', encoding='utf-8') as f:
        conteudo = f.read()
    return parsear_conteudo_txt(conteudo)


def parsear_conteudo_txt(conteudo):
    """
    Versão inteligente que detecta múltiplos formatos de entrada.
    Retorna lista de dicts com os dados de cada perfil.
    """
    if not conteudo or not conteudo.strip():
        return []

    conteudo = conteudo.strip()

    # =========================================================================
    # DETECÇÃO DE FORMATO
    # =========================================================================

    # Verificar se é formato com rótulos (Login:, UID:, Senha:, etc.)
    if re.search(r'(?i)\b(Login|UID|ID)\s*:', conteudo):
        return _parsear_formato_rotulos(conteudo)

    # Verificar se contém pipes (formato pipe)
    if '|' in conteudo:
        return _parsear_formato_pipe(conteudo)

    # Verificar se é formato com dois pontos como separador
    # (pelo menos 3 ":" numa linha, sem ser rótulo)
    linhas = [l.strip() for l in conteudo.split('\n') if l.strip()]
    for linha in linhas:
        if linha.count(':') >= 3 and not re.search(r'(?i)(Login|UID|ID|Senha|Email|Cookie|Token)\s*:', linha):
            return _parsear_formato_dois_pontos(conteudo)

    # Fallback: tentar pipe ou valores soltos
    return _parsear_formato_valores_soltos(conteudo)


# =============================================================================
# FORMATO PIPE (inline ou por linha)
# =============================================================================

def _parsear_formato_pipe(conteudo):
    """
    Parseia formato pipe. Detecta automaticamente se é:
    - Formato 6: ID|SENHA|2FA|COOKIES|TOKEN|EMAIL (contas coladas, email+ID grudados)
    - Formato 1: ID|SENHA|COOKIES|TOKEN|EMAIL|SENHA_EMAIL (contas coladas)
    - Novos formatos inline híbridos com 2 contas no mesmo .txt
    - Formato 4: Uma conta por linha
    """
    linhas = [l.strip() for l in conteudo.split('\n') if l.strip()]

    # Primeiro, tentar um parser genérico multicontas.
    perfis_genericos = _parsear_pipe_generico_multicontas(conteudo)
    ids_encontrados = re.findall(r'(?<!\d)\d{14,16}(?!\d)', conteudo)
    if perfis_genericos and (len(perfis_genericos) > 1 or len(perfis_genericos) >= len(ids_encontrados)):
        return perfis_genericos

    if _detectar_formato_6(conteudo):
        perfis = []
        for linha in linhas:
            perfis.extend(_parsear_formato_6_inline(linha))
        return perfis

    if len(ids_encontrados) > 1 and len(linhas) <= len(ids_encontrados):
        perfis = []
        for linha in linhas:
            perfis.extend(_parsear_pipe_inline(linha))
        return perfis

    perfis = []
    for linha in linhas:
        if linha.startswith('---') or linha.startswith('===') or linha.upper().startswith('PERFIL'):
            continue
        perfil = _parsear_uma_conta_pipe(linha.split('|'))
        if perfil and perfil['login']:
            perfil['numero'] = str(len(perfis) + 1).zfill(2)
            perfis.append(perfil)

    return perfis


def _detectar_formato_6(conteudo):
    """
    Detecta se o conteúdo é do Formato 6: ID|SENHA|2FA|COOKIES|TOKEN|EMAIL
    
    Heurística: procura o padrão característico onde após um ID de 14-16 dígitos,
    vem uma senha curta, depois um código 2FA (alfanumérico upper 16-64 chars),
    depois cookies com c_user=, depois token EAAA..., depois email@domínio.
    """
    # Padrão: ID(dígitos) | texto_curto | UPPER_ALNUM(16-64) | c_user=... | EAAA... | ...@...
    # Verificar se existe o padrão: dígitos|texto|UPPER_ALNUM_LONGO|c_user=
    padrao = re.search(
        r'\d{14,16}\|[^|]{3,20}\|[A-Z0-9]{16,64}\|c_user=',
        conteudo
    )
    return padrao is not None


def _parsear_formato_6_inline(linha):
    """
    Parseia Formato 6: ID|SENHA|2FA|COOKIES|TOKEN|EMAIL (contas coladas)
    
    Estratégia robusta:
    1. Dividir por pipe
    2. Identificar âncoras: IDs (dígitos 14-16), Cookies (c_user=), Tokens (EAAA)
    3. O email fica colado com o próximo ID no final: "email@dom.comNEXT_ID"
    4. Agrupar em contas de 6 campos cada
    """
    partes = linha.split('|')
    if not partes:
        return []

    # =========================================================================
    # ESTRATÉGIA: Usar regex para separar as contas pelo padrão de email+ID
    # O email termina com domínio (.com, .work, etc.) e o próximo ID começa
    # imediatamente com dígitos de 14-16 chars.
    # =========================================================================
    
    # Primeiro, reconstruir a linha e usar regex para separar contas
    # Padrão de separação: email@domínio.tld seguido de ID de 14-16 dígitos
    # Ex: "xvv2inapyc@fviadropinbox.com61576261272602"
    
    # Separar as contas usando o padrão: @domínio.tldDIGITOS como ponto de corte
    # Inserir um separador especial entre email e próximo ID
    linha_processada = re.sub(
        r'(@[a-zA-Z0-9._-]+\.[a-zA-Z]{2,})(\d{14,16})',
        r'\1|||SEPARADOR_CONTA|||\2',
        linha
    )
    
    # Agora dividir por nosso separador especial
    blocos_conta = linha_processada.split('|||SEPARADOR_CONTA|||')
    
    perfis = []
    
    for bloco in blocos_conta:
        bloco = bloco.strip()
        if not bloco:
            continue
        
        partes_bloco = [p.strip() for p in bloco.split('|') if p.strip()]
        if not partes_bloco:
            continue
        
        perfil = _criar_perfil_vazio()
        
        # Classificar cada parte e atribuir
        campos_atribuidos = {
            'login': False, 'senha': False, 'tfa': False,
            'cookie': False, 'token': False, 'email': False
        }
        
        for parte in partes_bloco:
            parte = parte.strip()
            if not parte:
                continue
            
            # ID Facebook (14-16 dígitos puros)
            if parte.isdigit() and 14 <= len(parte) <= 16 and not campos_atribuidos['login']:
                perfil['login'] = parte
                campos_atribuidos['login'] = True
                continue
            
            # Cookies (contém c_user=)
            if ('c_user=' in parte or ('xs=' in parte and 'datr=' in parte)) and not campos_atribuidos['cookie']:
                perfil['cookie_raw'] = parte
                perfil['cookie_json'] = converter_cookie_string_para_json(parte)
                campos_atribuidos['cookie'] = True
                continue
            
            # Token Facebook (começa com EAAA)
            if parte.startswith('EAAA') and not campos_atribuidos['token']:
                match = re.search(r'(EAAA[a-zA-Z0-9]+ZDZD)', parte)
                perfil['token'] = match.group(1) if match else parte
                campos_atribuidos['token'] = True
                continue
            
            # Email (contém @ e .)
            if '@' in parte and '.' in parte and not campos_atribuidos['email']:
                perfil['email'] = parte
                campos_atribuidos['email'] = True
                continue
            
            # 2FA (alfanumérico maiúsculo, 16-64 chars) - ANTES da senha
            if (16 <= len(parte) <= 64 and parte.isalnum() and parte.isupper() 
                and not campos_atribuidos['tfa']):
                perfil['tfa'] = parte
                campos_atribuidos['tfa'] = True
                continue
            
            # Base64 cookies
            if _is_base64_cookies(parte) and not campos_atribuidos['cookie']:
                perfil['cookie_raw'] = parte
                perfil['cookie_json'] = converter_cookie_string_para_json(parte)
                campos_atribuidos['cookie'] = True
                continue
            
            # Senha (primeiro texto curto não classificado)
            if not campos_atribuidos['senha'] and 3 <= len(parte) <= 64:
                perfil['senha'] = parte
                campos_atribuidos['senha'] = True
                continue
            
            # Senha do email (se já tem senha e email - especialmente Hotmail/Outlook)
            if campos_atribuidos['senha'] and not perfil['senha_email']:
                if campos_atribuidos['email'] and _email_tem_senha_separada(perfil['email']):
                    perfil['senha_email'] = parte
                    continue
                elif campos_atribuidos['email']:
                    perfil['senha_email'] = parte
                    continue
        
        # Verificar se o perfil tem pelo menos login
        if perfil['login']:
            perfil['numero'] = str(len(perfis) + 1).zfill(2)
            perfis.append(perfil)
    
    return perfis


# =============================================================================
# PARSER PIPE GENÉRICO MULTICONTAS (novos formatos inline)
# =============================================================================

def _parsear_pipe_generico_multicontas(conteudo):
    """Separa e parseia formatos pipe inline com múltiplas contas coladas."""
    if '|' not in conteudo:
        return []

    blocos = _separar_blocos_pipe_multicontas(conteudo)
    perfis = []
    for bloco in blocos:
        perfil = _parsear_bloco_pipe_generico(bloco)
        if perfil and perfil.get('login'):
            perfil['numero'] = str(len(perfis) + 1).zfill(2)
            perfis.append(perfil)
    return perfis


def _separar_blocos_pipe_multicontas(conteudo):
    """Insere separadores seguros entre contas coladas e retorna os blocos."""
    texto = conteudo.strip()
    if not texto:
        return []

    separador = '\n<<<SEPARADOR_CONTA>>>\n'
    padroes = [
        (r'(EAAA[a-zA-Z0-9]+ZDZD)(\d{14,16}\|)', r'\1' + separador + r'\2'),
        (r'([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(\d{14,16}\|)', r'\1' + separador + r'\2'),
        (r'(\|\|)(\d{14,16}\|)', r'\1' + separador + r'\2'),
    ]
    for pat, repl in padroes:
        texto = re.sub(pat, repl, texto)

    # Separar senhas/senhas de email grudadas ao próximo ID, sem mexer em email/cookie/token.
    def _split_senha_id(match):
        prefixo = match.group(1)
        sufixo = match.group(2)
        if ('c_user=' in prefixo or 'xs=' in prefixo or prefixo.startswith('EAAA') or '@' in prefixo):
            return match.group(0)
        return prefixo + separador + sufixo

    texto = re.sub(r'(?<![=@])([^|]{4,120}?)(\d{14,16}\|)', _split_senha_id, texto)

    blocos = []
    for bloco in texto.split(separador):
        bloco = bloco.strip().strip('|').strip()
        if re.search(r'(?<!\d)\d{14,16}(?!\d)', bloco):
            blocos.append(bloco)
    return blocos
    return blocos


def _parsear_bloco_pipe_generico(bloco):
    """Parseia um único bloco pipe usando classificação flexível dos campos."""
    partes = [p.strip() for p in bloco.split('|') if p.strip() != '']
    if not partes:
        return None

    perfil = _criar_perfil_vazio()
    extras = []

    for parte in partes:
        if not perfil['login'] and parte.isdigit() and 14 <= len(parte) <= 16:
            perfil['login'] = parte
            continue

        if ('c_user=' in parte or ('xs=' in parte and 'datr=' in parte) or _is_base64_cookies(parte)) and not perfil['cookie_raw']:
            perfil['cookie_raw'] = parte
            perfil['cookie_json'] = converter_cookie_string_para_json(parte)
            continue

        if parte.startswith('EAAA') and not perfil['token']:
            match = re.search(r'(EAAA[a-zA-Z0-9]+ZDZD)', parte)
            perfil['token'] = match.group(1) if match else parte
            continue

        if '@' in parte and '.' in parte and not perfil['email']:
            perfil['email'] = parte
            continue

        if 16 <= len(parte) <= 64 and parte.isalnum() and parte.isupper() and not perfil['tfa']:
            perfil['tfa'] = parte
            continue

        if re.match(r'^[0-9a-f-]{36}$', parte, re.I) and not perfil['token_email']:
            perfil['token_email'] = parte
            continue

        # Alguns lotes trazem senha_email + token_email unidos no mesmo campo
        # Ex.: senhaMuitoLonga---9e5f94bc-e8a4-4e73-b8be-63364c29d753
        match_token_embutido = re.search(r'^(.*?)([0-9a-f-]{36})$', parte, re.I)
        if match_token_embutido and (('---' in parte) or len(parte) > 80):
            prefixo = match_token_embutido.group(1).rstrip('- ').strip()
            uuid = match_token_embutido.group(2)
            if prefixo and not perfil['senha_email']:
                perfil['senha_email'] = prefixo
            if not perfil['token_email']:
                perfil['token_email'] = uuid
            continue

        if re.match(r'^\d{4,6}$', parte) or re.search(r'\d{1,2}/[A-Za-zÀ-ÿ]{3}', parte) or re.search(r'\d{1,2}:\d{2}:\d{2}$', parte):
            extras.append(parte)
            continue

        if not perfil['senha'] and 3 <= len(parte) <= 256:
            perfil['senha'] = parte
            continue

        if not perfil['senha_email'] and 1 <= len(parte) <= 512:
            # Se email é de provedor com senha, aceitar agressivamente
            if perfil['email'] and _email_tem_senha_separada(perfil['email']):
                perfil['senha_email'] = parte
                continue
            # (antes: `campos_atribuidos.get('senha')` — nome inexistente → NameError que
            # derrubava o parse da linha inteira). A intenção é "a senha do FB já foi lida".
            elif perfil['email'] and perfil.get('senha') and 4 <= len(parte) <= 128:
                perfil['senha_email'] = parte
                continue

        extras.append(parte)

    if extras:
        perfil['info_extra'] = ' | '.join(extras[:10])

    return perfil if perfil['login'] else None


# =============================================================================
# FORMATO PIPE INLINE ORIGINAL (Formato 1)
# =============================================================================

def _parsear_pipe_inline(linha):
    """
    Parseia uma linha com múltiplas contas coladas por pipe.

    Formato: ID|SENHA|COOKIES|TOKEN|EMAIL|SENHA_EMAIL[NEXT_ID|...]

    O problema: entre contas, SENHA_EMAIL e NEXT_ID ficam colados.
    Estratégia: usar os cookies (c_user=) e tokens (EAAA) como âncoras
    para identificar os limites de cada conta.
    """
    partes = [p.strip() for p in linha.split('|')]
    if not partes:
        return []

    # Classificar cada parte
    classificadas = []
    for p in partes:
        classificadas.append({
            'valor': p,
            'tipo': _classificar_parte(p)
        })

    # Agora agrupar em contas.
    # Cada conta segue o padrão: ID, SENHA, COOKIES, TOKEN, EMAIL, SENHA_EMAIL
    # Mas a SENHA_EMAIL pode estar colada com o próximo ID.
    perfis = []
    i = 0

    while i < len(classificadas):
        perfil = _criar_perfil_vazio()

        # Passo 1: Encontrar o ID (pode estar colado no final da parte anterior)
        parte_atual = classificadas[i]['valor']
        tipo_atual = classificadas[i]['tipo']

        if tipo_atual == 'ID_FB':
            perfil['login'] = parte_atual
            i += 1
        elif tipo_atual == 'SENHA_MAIS_ID':
            # O ID está colado no final - extrair
            match = re.search(r'(\d{14,16})$', parte_atual)
            if match:
                perfil['login'] = match.group(1)
                i += 1
            else:
                i += 1
                continue
        else:
            # Tentar extrair ID do final da string (caso esteja colado)
            match = re.search(r'(\d{14,16})$', parte_atual)
            if match:
                perfil['login'] = match.group(1)
                i += 1
            else:
                i += 1
                continue

        # Passo 2: Coletar os campos seguintes até encontrar outro ID ou fim
        campos_conta = []
        while i < len(classificadas):
            prox_tipo = classificadas[i]['tipo']
            prox_valor = classificadas[i]['valor']

            # Se encontramos um novo ID puro, é a próxima conta
            if prox_tipo == 'ID_FB':
                break

            # Se encontramos algo que termina com ID (senha_email+id colados)
            if prox_tipo == 'SENHA_MAIS_ID':
                # Extrair a parte antes do ID como senha_email
                match = re.search(r'^(.+?)(\d{14,16})$', prox_valor)
                if match:
                    campos_conta.append({
                        'valor': match.group(1),
                        'tipo': 'SENHA_EMAIL_EXTRAIDA'
                    })
                # Não avançar i - será processado como início da próxima conta
                break

            campos_conta.append(classificadas[i])
            i += 1

        # Passo 3: Atribuir campos à conta
        _atribuir_campos_pipe(perfil, campos_conta)

        if perfil['login']:
            perfil['numero'] = str(len(perfis) + 1).zfill(2)
            perfis.append(perfil)

    return perfis


def _classificar_parte(parte):
    """Classifica o tipo de uma parte separada por pipe."""
    p = parte.strip()
    if not p:
        return 'VAZIO'

    # ID puro do Facebook (14-16 dígitos)
    if p.isdigit() and 14 <= len(p) <= 16:
        return 'ID_FB'

    # Cookies (contém c_user= ou xs=)
    if 'c_user=' in p or ('xs=' in p and 'datr=' in p):
        return 'COOKIES'

    # Token Facebook (começa com EAAA)
    if p.startswith('EAAA'):
        return 'TOKEN'

    # Email
    if '@' in p and '.' in p:
        return 'EMAIL'

    # Base64 cookies
    if _is_base64_cookies(p):
        return 'COOKIES_B64'

    # Verificar se termina com um ID do Facebook (senha_email + próximo ID colados)
    match = re.search(r'^(.+?)(\d{14,16})$', p)
    if match:
        prefixo = match.group(1)
        sufixo = match.group(2)
        # Garantir que o prefixo não é vazio e parece uma senha
        # e que o sufixo parece um ID (14-16 dígitos)
        if len(prefixo) >= 4 and len(sufixo) >= 14:
            return 'SENHA_MAIS_ID'

    # Texto genérico (senha, senha_email, 2FA, etc.)
    return 'TEXTO'


def _atribuir_campos_pipe(perfil, campos):
    """
    Atribui campos coletados a um perfil no formato pipe.
    Ordem esperada: SENHA, COOKIES, TOKEN, EMAIL, SENHA_EMAIL
    Mas também aceita ordens diferentes baseado no tipo detectado.
    """
    # Primeiro, atribuir por tipo detectado
    senha_candidatos = []

    for campo in campos:
        valor = campo['valor'].strip()
        tipo = campo['tipo']

        if tipo == 'COOKIES' or tipo == 'COOKIES_B64':
            if not perfil['cookie_raw']:
                perfil['cookie_raw'] = valor
                perfil['cookie_json'] = converter_cookie_string_para_json(valor)
        elif tipo == 'TOKEN':
            if not perfil['token']:
                # Extrair token limpo (até ZDZD)
                match = re.search(r'(EAAA[a-zA-Z0-9]+ZDZD)', valor)
                perfil['token'] = match.group(1) if match else valor
        elif tipo == 'EMAIL':
            if not perfil['email']:
                perfil['email'] = valor
        elif tipo == 'SENHA_EMAIL_EXTRAIDA':
            perfil['senha_email'] = valor
        else:
            # Texto genérico - pode ser senha, senha_email, 2FA
            senha_candidatos.append(valor)

    # Atribuir senhas na ordem em que aparecem
    for candidato in senha_candidatos:
        # Verificar se é 2FA (alfanumérico maiúsculo, 16-64 chars)
        if 16 <= len(candidato) <= 64 and candidato.isalnum() and candidato.isupper():
            if not perfil['tfa']:
                perfil['tfa'] = candidato
                continue

        # UUID (token de email)
        if re.match(r'^[0-9a-f-]{36}$', candidato, re.I):
            if not perfil['token_email']:
                perfil['token_email'] = candidato
                continue

        # Senha (primeira disponível)
        if not perfil['senha']:
            perfil['senha'] = candidato
        elif not perfil['senha_email']:
            # Se o email é Hotmail/Outlook/Yahoo etc., aceitar qualquer restante como senha do email
            if perfil['email'] and _email_tem_senha_separada(perfil['email']):
                perfil['senha_email'] = candidato
            elif perfil['email']:
                perfil['senha_email'] = candidato


def _parsear_uma_conta_pipe(partes_raw):
    """Parseia uma única conta a partir de partes já separadas por pipe."""
    perfil = _criar_perfil_vazio()
    partes = [p.strip() for p in partes_raw if p.strip()]

    for parte in partes:
        _identificar_campo(parte, perfil)

    return perfil


# =============================================================================
# FORMATO COM RÓTULOS (Login: xxx, Senha: xxx, etc.)
# =============================================================================

def _parsear_formato_rotulos(conteudo):
    """
    Parseia formato com rótulos (Login:, Senha:, Email:, etc.)
    Suporta múltiplos perfis separados por linhas de traço ou "PERFIL XX".
    """
    perfis = []

    # Garantir que separador no início do arquivo também seja capturado
    # (sem isso, "--- Conta 1 ---\n..." no início não tem \n precedente)
    conteudo_norm = '\n' + conteudo if not conteudo.startswith('\n') else conteudo

    # Dividir em blocos de perfil
    # Separadores: linhas de traços (opcionalmente com texto como "--- Conta 1 ---"),
    # "PERFIL XX", "Conta XX", ou linhas em branco duplas
    blocos = re.split(
        r'(?:\n\s*-{3,}[^\n]*-{0,}\s*\n|\n\s*={3,}[^\n]*={0,}\s*\n|\n\s*(?:PERFIL|Conta)\s+\d+[^\n]*\n|\n\s*\n\s*\n)',
        conteudo_norm, flags=re.IGNORECASE
    )

    for bloco in blocos:
        bloco = bloco.strip()
        if not bloco:
            continue

        # Pular linhas que são apenas separadores como "PERFIL XX" ou "--- Conta X ---"
        if re.match(r'^(?:PERFIL|Conta)\s+\d+.*$', bloco.strip(), re.IGNORECASE):
            continue
        if re.match(r'^-{3,}.*$', bloco.strip()):
            continue

        perfil = _criar_perfil_vazio()

        # Extrair campos com rótulos
        for chave in ['Login', 'UID', 'ID', 'Senha do Email', 'Senha', 'Email de Recuperação',
                       'Email Recuperação', 'Email', '2FA', 'Cookie', 'Cookies',
                       'Token do Email', 'Token', 'REABRIR', 'Informações Extras', 'Info Extra']:
            # Buscar "Chave: valor" na linha
            match = re.search(rf'(?i)(?:^|\n)\s*{re.escape(chave)}\s*:\s*(.+?)(?:\n|$)', bloco)
            if match:
                valor = match.group(1).strip()
                if valor:
                    _atribuir_campo_rotulo(chave.lower(), valor, perfil)

        if perfil['login']:
            perfil['numero'] = str(len(perfis) + 1).zfill(2)
            perfis.append(perfil)

    return perfis


def _atribuir_campo_rotulo(chave, valor, perfil):
    """Atribui valor a um campo do perfil baseado na chave do rótulo."""
    if 'login' in chave or chave in ('uid', 'id'):
        perfil['login'] = valor
    elif 'senha do email' in chave:
        perfil['senha_email'] = valor
    elif 'senha' in chave:
        perfil['senha'] = valor
    elif 'email' in chave and 'recupera' in chave:
        perfil['email_recuperacao'] = valor
    elif 'email' in chave and 'token' not in chave and 'senha' not in chave:
        perfil['email'] = valor
    elif '2fa' in chave:
        perfil['tfa'] = valor
    elif 'cookie' in chave:
        perfil['cookie_raw'] = valor
        perfil['cookie_json'] = converter_cookie_string_para_json(valor)
    elif 'token do email' in chave:
        perfil['token_email'] = valor
    elif 'reabrir' in chave:
        # Marcador do export de falhas: profile_id do navegador AdsPower já criado e
        # LOGADO. O worker REABRE esse navegador (não cria novo) e RETOMA a BM.
        perfil['reabrir_profile_id'] = valor
        perfil['reutilizar'] = True
    elif 'token' in chave:
        perfil['token'] = valor
    elif 'informações extras' in chave or 'info extra' in chave:
        perfil['info_extra'] = valor


# =============================================================================
# FORMATO DOIS PONTOS (ID:SENHA:EMAIL:...)
# =============================================================================

def _parsear_formato_dois_pontos(conteudo):
    """Parseia formato com dois pontos como separador (uma conta por linha)."""
    perfis = []
    linhas = [l.strip() for l in conteudo.split('\n') if l.strip()]

    for linha in linhas:
        if linha.startswith('---') or linha.startswith('==='):
            continue

        perfil = _criar_perfil_vazio()
        partes = [p.strip() for p in linha.split(':') if p.strip()]

        for parte in partes:
            _identificar_campo(parte, perfil)

        if perfil['login']:
            perfil['numero'] = str(len(perfis) + 1).zfill(2)
            perfis.append(perfil)

    return perfis


# =============================================================================
# FORMATO VALORES SOLTOS
# =============================================================================

def _parsear_formato_valores_soltos(conteudo):
    """Parseia formato com valores separados por espaço, tab ou vírgula."""
    perfis = []
    linhas = [l.strip() for l in conteudo.split('\n') if l.strip()]

    for linha in linhas:
        if linha.startswith('---') or linha.startswith('===') or linha.upper().startswith('PERFIL'):
            continue

        perfil = _criar_perfil_vazio()
        partes = [p.strip() for p in re.split(r'[\s\t,]+', linha) if p.strip()]

        for parte in partes:
            _identificar_campo(parte, perfil)

        if perfil['login']:
            perfil['numero'] = str(len(perfis) + 1).zfill(2)
            perfis.append(perfil)

    return perfis


# =============================================================================
# IDENTIFICAÇÃO GENÉRICA DE CAMPOS
# =============================================================================

def _identificar_campo(parte, perfil):
    """Identifica automaticamente o tipo de campo pelo conteúdo."""
    parte = parte.strip()
    if not parte:
        return

    # ID Facebook (14-16 dígitos puros)
    if parte.isdigit() and 14 <= len(parte) <= 16:
        if not perfil['login']:
            perfil['login'] = parte
        return

    # Email
    if '@' in parte and '.' in parte and not perfil['email']:
        perfil['email'] = parte
        return

    # Cookies (Bruto ou Base64)
    if 'c_user=' in parte or ('xs=' in parte and 'datr=' in parte) or _is_base64_cookies(parte):
        if not perfil['cookie_raw']:
            perfil['cookie_raw'] = parte
            perfil['cookie_json'] = converter_cookie_string_para_json(parte)
        return

    # Token FB (começa com EAAA)
    if parte.startswith('EAAA'):
        if not perfil['token']:
            match = re.search(r'(EAAA[a-zA-Z0-9]+ZDZD)', parte)
            perfil['token'] = match.group(1) if match else parte
        return

    # 2FA (Alfanumérico maiúsculo, 16-64 chars)
    if 16 <= len(parte) <= 64 and parte.isalnum() and parte.isupper():
        if not perfil['tfa']:
            perfil['tfa'] = parte
            return

    # UUID (Token de Email)
    if re.match(r'^[0-9a-f-]{36}$', parte, re.I):
        if not perfil['token_email']:
            perfil['token_email'] = parte
            return

    # Senha (se não for nada acima)
    if not perfil['senha'] and 4 <= len(parte) <= 64:
        perfil['senha'] = parte
        return

    # Senha do Email (se já tem senha e email)
    # Detecção agressiva para Hotmail/Outlook/Yahoo etc.
    if perfil['senha'] and not perfil['senha_email'] and 1 <= len(parte) <= 256:
        # Se tem email de provedor com senha separada, qualquer texto restante é senha do email
        if perfil['email'] and _email_tem_senha_separada(perfil['email']):
            perfil['senha_email'] = parte
            return
        # Se tem email genérico, aceitar se parece senha (4-64 chars sem @ sem =)
        if perfil['email'] and 4 <= len(parte) <= 64 and '@' not in parte and '=' not in parte:
            perfil['senha_email'] = parte
            return


# =============================================================================
# UTILITÁRIOS
# =============================================================================

def _criar_perfil_vazio():
    """Cria um dicionário de perfil vazio com todos os campos."""
    return {
        'numero': '',
        'login': '',
        'senha': '',
        'email': '',
        'senha_email': '',
        'token_email': '',
        'info_extra': '',
        'tfa': '',
        'cookie_raw': '',
        'cookie_json': '',
        'token': '',
        'email_recuperacao': ''
    }


def _is_base64_cookies(s):
    """Verifica se a string é um cookie codificado em Base64."""
    if not s or len(s) < 20:
        return False
    try:
        decoded = base64.b64decode(s).decode('utf-8')
        return decoded.strip().startswith('[') and '"name":' in decoded
    except:
        return False


def converter_cookie_string_para_json(cookie_str):
    """
    Converte uma string de cookies para o formato JSON aceito pelo IXBrowser.

    Usa o formato de campos correto da API IXBrowser v2:
    - creation_time, expiration_time, last_access_time (strings timestamp)
    - http_only (não httpOnly)
    - same_site: "-1" (não sameSite)
    - source_scheme, source_port, is_host_cookie, priority, same_party
    """
    if not cookie_str:
        return ''

    # Se for Base64, decodificar primeiro
    if _is_base64_cookies(cookie_str):
        try:
            return base64.b64decode(cookie_str).decode('utf-8')
        except:
            pass

    cookies = []

    # Limpar e separar cookies
    cookie_str = cookie_str.strip().rstrip(';')

    # Separar por ';' mas respeitar valores que contêm ';' dentro
    pares = [p.strip() for p in cookie_str.split(';') if p.strip()]

    # Reagrupar pares que foram separados incorretamente
    cookies_dict = {}
    current_name = None
    current_value = None

    for par in pares:
        if '=' in par:
            # Novo cookie
            if current_name:
                cookies_dict[current_name] = current_value
            nome, valor = par.split('=', 1)
            current_name = nome.strip()
            current_value = valor.strip()
        else:
            # Continuação do valor anterior (separado por ;)
            if current_name:
                current_value += ';' + par

    # Adicionar o último
    if current_name:
        cookies_dict[current_name] = current_value

    # Definir propriedades de segurança por cookie
    cookie_security = {
        'c_user': {'secure': True, 'http_only': False},
        'xs': {'secure': True, 'http_only': True},
        'fr': {'secure': True, 'http_only': True},
        'datr': {'secure': True, 'http_only': True},
        'sb': {'secure': True, 'http_only': True},
        'presence': {'secure': True, 'http_only': False},
        'wd': {'secure': True, 'http_only': False},
    }

    now_str = str(int(time.time()))
    # Expiração: 1 ano a partir de agora
    exp_str = str(int(time.time()) + 365 * 24 * 3600)

    for nome, valor in cookies_dict.items():
        security = cookie_security.get(nome, {'secure': True, 'http_only': False})

        cookie_obj = {
            "creation_time": now_str,
            "domain": ".facebook.com",
            "name": nome,
            "value": valor,
            "path": "/",
            "expiration_time": exp_str,
            "last_access_time": now_str,
            "secure": security['secure'],
            "http_only": security['http_only'],
            "same_site": "-1",
            "priority": "1",
            "same_party": False,
            "source_scheme": "2",
            "source_port": "443",
            "is_host_cookie": False
        }

        cookies.append(cookie_obj)

    if not cookies:
        return ''

    # ===== MELHORIA v23: Adicionar cookie locale pt_BR automaticamente =====
    # Garantir que o Facebook seja aberto em Português (Brasil)
    tem_locale = any(c.get('name') == 'locale' for c in cookies)
    if not tem_locale:
        cookies.append({
            "creation_time": now_str,
            "domain": ".facebook.com",
            "name": "locale",
            "value": "pt_BR",
            "path": "/",
            "expiration_time": exp_str,
            "last_access_time": now_str,
            "secure": True,
            "http_only": False,
            "same_site": "-1",
            "priority": "1",
            "same_party": False,
            "source_scheme": "2",
            "source_port": "443",
            "is_host_cookie": False
        })
    else:
        # Se já tem locale, garantir que é pt_BR
        for c in cookies:
            if c.get('name') == 'locale':
                c['value'] = 'pt_BR'
                break

    return json.dumps(cookies, ensure_ascii=False)
