#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SISTEMA DE AUTO-ATUALIZAÇÃO (cliente)
=====================================
No START do app (antes de abrir a GUI), consulta o manifest publicado na VPS
(no CDN da infra nova). Se houver uma versão MAIOR que a local:

  1. Baixa o pacote .zip da nova versão (com barra de progresso).
  2. Valida o SHA-256 (se informado no manifest).
  3. Extrai para uma pasta temporária.
  4. Lança um HELPER (.bat) DESTACADO que: aguarda o app fechar, copia os
     arquivos novos por cima da instalação (robocopy, SEM apagar logs/config do
     usuário), relança o app na versão nova e se autodestrói.
  5. Encerra o app atual (o helper relança a versão nova).

Regras de segurança:
  - Só roda quando EMPACOTADO (PyInstaller onedir: sys.frozen). Em dev (rodando
    do código) NÃO atualiza.
  - Se a checagem/download FALHAR (offline, VPS fora do ar), NÃO trava o usuário:
    apenas loga e segue abrindo a versão atual. (A obrigatoriedade real é "se há
    update e dá pra baixar, aplica antes de abrir".)
  - robocopy nunca usa /PURGE/MIR → arquivos do usuário (config/logs) sobrevivem.
"""

import os
import sys
import json
import hashlib
import logging
import tempfile
import subprocess

logger = logging.getLogger(__name__)

try:
    import requests
    _TEM_REQUESTS = True
except Exception:  # pragma: no cover
    _TEM_REQUESTS = False

try:
    from server.version import APP_VERSION, UPDATE_MANIFEST_URL, APP_NOME
except Exception:  # pragma: no cover
    APP_VERSION = '1.0'
    UPDATE_MANIFEST_URL = __import__('server.marca', fromlist=['x']).URL_MANIFESTO
    APP_NOME = 'GS BM Creator'


# ============================================================================
# VERSÃO
# ============================================================================

def _parse_versao(v):
    """'1.2.3' -> (1,2,3). Robusto a sufixos/strings inválidas."""
    partes = []
    for x in str(v or '').strip().split('.'):
        x = ''.join(ch for ch in x if ch.isdigit())
        partes.append(int(x) if x else 0)
    return tuple(partes) or (0,)


def versao_maior(remota, local):
    """True se `remota` > `local` (comparação numérica por componente)."""
    a, b = _parse_versao(remota), _parse_versao(local)
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def obter_versao_local():
    return APP_VERSION


def esta_empacotado():
    """True quando rodando como executável (PyInstaller)."""
    return bool(getattr(sys, 'frozen', False))


# ============================================================================
# MANIFEST
# ============================================================================

def verificar_atualizacao(timeout=8):
    """Consulta o manifest e retorna um dict, ou None em caso de falha.

    dict: {disponivel, versao, versao_local, url, sha256, notes, mandatory}
    """
    if not _TEM_REQUESTS:
        logger.warning('[Update] requests indisponível — checagem desativada.')
        return None
    try:
        r = requests.get(UPDATE_MANIFEST_URL, timeout=timeout,
                         headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
        r.raise_for_status()
        m = r.json()
    except Exception as e:
        logger.warning('[Update] Falha ao consultar manifest (%s): %s',
                       UPDATE_MANIFEST_URL, e)
        return None
    versao_remota = str(m.get('version') or '').strip()
    if not versao_remota:
        logger.warning('[Update] Manifest sem campo "version".')
        return None
    info = {
        'disponivel': versao_maior(versao_remota, APP_VERSION),
        'versao': versao_remota,
        'versao_local': APP_VERSION,
        'url': str(m.get('url') or '').strip(),
        'sha256': str(m.get('sha256') or '').strip().lower(),
        'notes': str(m.get('notes') or '').strip(),
        'mandatory': bool(m.get('mandatory', True)),
    }
    logger.info('[Update] local=%s remota=%s disponivel=%s',
                APP_VERSION, versao_remota, info['disponivel'])
    return info


# ============================================================================
# DOWNLOAD + APLICAÇÃO
# ============================================================================

def _install_dir():
    """Diretório da instalação (onde está o .exe do onedir PyInstaller)."""
    return os.path.dirname(os.path.abspath(sys.executable))


def _exe_name():
    return os.path.basename(sys.executable)


def baixar_pacote(url, sha256='', progress_cb=None, timeout=60):
    """Baixa o .zip da atualização para um arquivo temporário. Valida SHA-256 se
    informado. Retorna o caminho do arquivo ou None em caso de falha.

    progress_cb(baixado_bytes, total_bytes) — opcional, para barra de progresso.
    """
    if not _TEM_REQUESTS or not url:
        return None
    # A extensão do pacote define como será aplicado: .exe = SETUP (Inno, reinstala
    # com permissões/elevação); .zip = onedir (robocopy por cima). Detecta pela URL.
    _url_limpa = url.lower().split('?')[0]
    ext = '.exe' if _url_limpa.endswith('.exe') else '.zip'
    # Nome de arquivo LIMPO (sem espaços/parênteses) — o nome antigo
    # 'gsbm_update_(1, 3).exe' vinha de um f-string de tupla e complicava o
    # quoting do caminho no helper de instalação.
    destino = os.path.join(tempfile.gettempdir(), f'gsbm_update{ext}')
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total = int(r.headers.get('Content-Length') or 0)
            baixado = 0
            h = hashlib.sha256()
            with open(destino, 'wb') as f:
                for chunk in r.iter_content(chunk_size=262144):
                    if not chunk:
                        continue
                    f.write(chunk)
                    h.update(chunk)
                    baixado += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(baixado, total)
                        except Exception:
                            pass
        if sha256:
            calc = h.hexdigest().lower()
            if calc != sha256:
                logger.error('[Update] SHA-256 não confere (esperado=%s obtido=%s).',
                             sha256, calc)
                try:
                    os.remove(destino)
                except Exception:
                    pass
                return None
        logger.info('[Update] Pacote baixado: %s (%s bytes)', destino, baixado)
        return destino
    except Exception as e:
        logger.error('[Update] Falha no download: %s', e)
        return None


def aplicar_atualizacao(zip_path, callback=None):
    """Extrai o pacote e lança o helper .bat que substitui os arquivos e relança
    o app. Retorna True se o helper foi iniciado (o chamador DEVE encerrar o app).

    O .zip deve conter os arquivos do onedir na RAIZ (ex.: 'GS BM Creator.exe',
    '_internal/...'), espelhando a pasta de instalação.
    """
    import zipfile
    if not zip_path or not os.path.isfile(zip_path):
        return False
    install = _install_dir()
    exe = _exe_name()
    extract_dir = os.path.join(tempfile.gettempdir(),
                               f'gsbm_update_extract_{os.getpid()}')
    try:
        if callback:
            callback('Extraindo atualização...')
        # Limpa extração anterior, se houver.
        if os.path.isdir(extract_dir):
            import shutil
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(extract_dir)
    except Exception as e:
        logger.error('[Update] Falha ao extrair pacote: %s', e)
        return False

    # Se o zip tiver UMA única subpasta raiz (ex.: 'GS BM Creator/'), usa ela como
    # origem real (alguns zips embrulham tudo numa pasta).
    try:
        itens = [os.path.join(extract_dir, n) for n in os.listdir(extract_dir)]
        if len(itens) == 1 and os.path.isdir(itens[0]):
            extract_dir = itens[0]
    except Exception:
        pass

    bat_path = os.path.join(tempfile.gettempdir(),
                            f'gsbm_update_{os.getpid()}.bat')
    # robocopy SEM /PURGE/MIR: copia/atualiza os arquivos novos, mas NÃO apaga
    # arquivos exclusivos do destino (config/logs do usuário sobrevivem).
    # /XD logs: nunca toca na pasta de logs (evita lock).
    conteudo_bat = f"""@echo off
chcp 65001 >nul
title Atualizando {APP_NOME}...
echo Aguardando o {APP_NOME} fechar para aplicar a atualizacao...
:waitloop
tasklist /fi "imagename eq {exe}" 2>nul | find /i "{exe}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
echo Aplicando arquivos da nova versao...
robocopy "{extract_dir}" "{install}" /E /IS /IT /R:3 /W:2 /XD logs >nul
echo Reiniciando o {APP_NOME}...
start "" "{os.path.join(install, exe)}"
rmdir /s /q "{extract_dir}" >nul 2>&1
del "%~f0" >nul 2>&1
"""
    try:
        # .bat em cp1252 para o cmd.exe interpretar acentos corretamente.
        with open(bat_path, 'w', encoding='cp1252', errors='replace') as f:
            f.write(conteudo_bat)
    except Exception as e:
        logger.error('[Update] Falha ao escrever helper de atualização: %s', e)
        return False

    try:
        if callback:
            callback('Reiniciando para concluir a atualização...')
        # Lança o .bat DESTACADO (sobrevive ao fechamento do app).
        DETACHED = 0x00000008  # DETACHED_PROCESS
        NEWGRP = 0x00000200    # CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(['cmd', '/c', bat_path],
                         creationflags=DETACHED | NEWGRP,
                         close_fds=True,
                         cwd=tempfile.gettempdir())
        logger.info('[Update] Helper de atualização iniciado: %s', bat_path)
        return True
    except Exception as e:
        logger.error('[Update] Falha ao iniciar helper de atualização: %s', e)
        return False


def aplicar_atualizacao_setup(setup_path, callback=None):
    """Aplica a atualização RODANDO O SETUP (Inno) de forma VISÍVEL e SEM UAC.

    É o caminho correto quando o app está instalado em Program Files (o robocopy
    sem admin não consegue sobrescrever) e/ou quando é preciso (re)garantir
    redistribuíveis (.NET/WebView2/VC++), atalhos e registro.

    IMPORTANTE (fix): antes o helper era um .bat DESTACADO/SEM JANELA que rodava o
    setup em /VERYSILENT e CONFIAVA na auto-elevação interna do Inno. Nessa forma
    o prompt do UAC quase nunca vinha para a frente → o setup NÃO instalava, o app
    relançava na versão antiga e ficava BAIXANDO A CADA ABERTURA (loop). Agora o
    helper é um .ps1 com JANELA VISÍVEL que roda o setup via
    `Start-Process -Verb RunAs -Wait` (mesmo padrão do launcher) — isso força o
    UAC em PRIMEIRO PLANO, espera a instalação terminar, registra o código de
    retorno em logs\\update.log e só então relança o app.

    Lança o helper DESTACADO e retorna True (o chamador DEVE encerrar o app).
    """
    if not setup_path or not os.path.isfile(setup_path):
        return False
    install = _install_dir()
    exe = _exe_name()
    exe_full = os.path.join(install, exe)
    # Relança preferencialmente pelo launcher (que prepara ambiente/permissões),
    # caindo para o .exe direto se o launcher não existir. SEM aspas: o
    # Start-Process -FilePath trata caminho com espaços.
    launcher = os.path.join(install, 'launcher', 'INICIAR_GS_FB_Creator.bat')
    relaunch = launcher if os.path.isfile(launcher) else exe_full
    logdir = os.path.join(install, 'logs')

    # Template PS1 com TOKENS (evita conflito de chaves {} do f-string com o
    # PowerShell). Substituímos os tokens depois.
    ps_template = r'''
$ErrorActionPreference = 'SilentlyContinue'
$exe      = "@@EXE@@"
$setup    = "@@SETUP@@"
$install  = "@@INSTALL@@"
$relaunch = "@@RELAUNCH@@"
$logdir   = "@@LOGDIR@@"

function Log($m) {
    try {
        if ($logdir) {
            New-Item -ItemType Directory -Force -Path $logdir | Out-Null
            Add-Content -Path (Join-Path $logdir 'update.log') -Value ("$(Get-Date -Format s) [update] $m")
        }
    } catch {}
}

Write-Host ("Atualizando " + $exe + " - aguarde...") -ForegroundColor Cyan
Log "Helper de SETUP iniciado. Aguardando o app fechar."
$proc = [System.IO.Path]::GetFileNameWithoutExtension($exe)
$fim = (Get-Date).AddSeconds(150)
while (Get-Process -Name $proc -ErrorAction SilentlyContinue) {
    if ((Get-Date) -gt $fim) { Log "Timeout aguardando o app fechar - seguindo mesmo assim."; break }
    Start-Sleep -Seconds 1
}
Start-Sleep -Milliseconds 800

Write-Host "Instalando a nova versao. Aguarde..." -ForegroundColor Yellow
Log ("Diretorio de instalacao: " + $install)
$rc = -1
try {
    # CRITICO: o -ArgumentList precisa ser UMA STRING com o /DIR entre ASPAS. No
    # PowerShell 5.1, passar um ARRAY faz o Start-Process NAO colocar aspas nos
    # itens com espaco -> o Inno recebia '/DIR=C:\Program' (cortado no espaco de
    # 'Program Files') e instalava em C:\Program (pasta errada) -> loop infinito.
    $argline = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /NOCANCEL /DIR="' + $install + '"'
    # SEM -Verb RunAs: o app e instalado POR USUARIO (PrivilegesRequired=lowest),
    # entao o setup roda sem UAC. Com RunAs o Windows pedia confirmacao a cada
    # atualizacao (heranca de quando o app instalava em Program Files).
    $p = Start-Process -FilePath $setup -ArgumentList $argline -PassThru -Wait
    $rc = $p.ExitCode
} catch {
    Log ("Falha ao instalar: " + $_.Exception.Message)
    Write-Host "Falha na instalacao. Tente rodar o instalador manualmente." -ForegroundColor Red
}
Log ("Instalador finalizou rc=" + $rc)

try { Start-Process -FilePath $relaunch } catch { Log ("Falha ao relancar: " + $_.Exception.Message) }
try { Remove-Item -LiteralPath $setup -Force -ErrorAction SilentlyContinue } catch {}
try { Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue } catch {}
'''
    conteudo_ps = (ps_template
                   .replace('@@EXE@@', exe)
                   .replace('@@SETUP@@', setup_path)
                   .replace('@@INSTALL@@', install)
                   .replace('@@RELAUNCH@@', relaunch)
                   .replace('@@LOGDIR@@', logdir))

    ps_path = os.path.join(tempfile.gettempdir(), f'gsbm_setup_{os.getpid()}.ps1')
    try:
        # UTF-8 com BOM: garante que o PowerShell leia acentos corretamente.
        with open(ps_path, 'w', encoding='utf-8-sig', errors='replace') as f:
            f.write(conteudo_ps)
    except Exception as e:
        logger.error('[Update] Falha ao escrever helper de setup (ps1): %s', e)
        return False

    try:
        if callback:
            callback('Instalando a nova versão...')
        # JANELA VISÍVEL (CREATE_NEW_CONSOLE) para o usuário ver o progresso e o
        # UAC vir para a frente. NEW_PROCESS_GROUP p/ sobreviver ao fechamento do app.
        CREATE_NEW_CONSOLE = 0x00000010
        NEWGRP = 0x00000200
        subprocess.Popen(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps_path],
            creationflags=CREATE_NEW_CONSOLE | NEWGRP,
            close_fds=True,
            cwd=tempfile.gettempdir())
        logger.info('[Update] Helper de SETUP (ps1, elevado/visível) iniciado: %s', ps_path)
        return True
    except Exception as e:
        logger.error('[Update] Falha ao iniciar helper de setup: %s', e)
        return False


# ============================================================================
# SPLASH (tkinter) — progresso opcional durante o download
# ============================================================================

def _baixar_com_splash(info):
    """Baixa o pacote exibindo uma janelinha de progresso (tkinter). Retorna o
    caminho do zip ou None. Se tkinter não existir, baixa sem UI."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return baixar_pacote(info['url'], info.get('sha256', ''))

    estado = {'zip': None, 'erro': False}
    root = tk.Tk()
    root.title(f'{APP_NOME} — Atualização')
    root.geometry('420x150')
    root.resizable(False, False)
    try:
        root.attributes('-topmost', True)
    except Exception:
        pass

    lbl = tk.Label(root, text=f'Nova versão {info["versao"]} disponível.\nBaixando atualização...',
                   font=('Segoe UI', 10), justify='center')
    lbl.pack(pady=(18, 8))
    barra = ttk.Progressbar(root, orient='horizontal', length=360, mode='determinate')
    barra.pack(pady=4)
    pct = tk.Label(root, text='0%', font=('Segoe UI', 9))
    pct.pack()

    def _cb(baixado, total):
        try:
            if total > 0:
                v = int(baixado * 100 / total)
                barra['value'] = v
                pct.config(text=f'{v}%')
            else:
                barra.config(mode='indeterminate')
                barra.start(12)
            root.update_idletasks()
            root.update()
        except Exception:
            pass

    def _worker():
        estado['zip'] = baixar_pacote(info['url'], info.get('sha256', ''), progress_cb=_cb)
        if not estado['zip']:
            estado['erro'] = True
        try:
            root.after(200, root.destroy)
        except Exception:
            pass

    # Baixa na MESMA thread via after (mantém o Tk responsivo o suficiente; o
    # download é rápido e _cb chama update()). Simples e sem threads/Tk cross-thread.
    root.after(300, _worker)
    try:
        root.mainloop()
    except Exception:
        pass
    return estado['zip']


# ============================================================================
# ANTI-LOOP: se um update para a MESMA versão foi tentado várias vezes e o app
# continua na versão antiga (instalador falhou/instalou no lugar errado), PARA de
# tentar e abre a versão atual — senão o app fica baixando/reinstalando sem fim.
# ============================================================================

def _marker_path():
    return os.path.join(tempfile.gettempdir(), 'gsbm_update_attempts.json')


def _tentativas_para(versao):
    """Quantas vezes JÁ tentamos atualizar para `versao` (marcador em %TEMP%)."""
    try:
        with open(_marker_path(), 'r', encoding='utf-8') as f:
            d = json.load(f)
        if str(d.get('versao')) == str(versao):
            return int(d.get('count', 0))
    except Exception:
        pass
    return 0


def _registrar_tentativa(versao):
    """Incrementa o contador de tentativas para `versao` (zera se mudou)."""
    n = _tentativas_para(versao) + 1
    try:
        with open(_marker_path(), 'w', encoding='utf-8') as f:
            json.dump({'versao': str(versao), 'count': n}, f)
    except Exception:
        pass
    return n


def _limpar_tentativas():
    try:
        os.remove(_marker_path())
    except Exception:
        pass


# ============================================================================
# ORQUESTRADOR (chamado pelo main.py no start)
# ============================================================================

def executar_fluxo_update_se_preciso():
    """Verifica e, se houver versão nova, baixa e aplica (relança o app).

    Retorna True se uma atualização ESTÁ SENDO APLICADA (o chamador deve encerrar
    o processo imediatamente). Retorna False para seguir abrindo a versão atual.
    """
    # Só atualiza quando empacotado (em dev não faz sentido sobrescrever arquivos).
    if not esta_empacotado():
        logger.info('[Update] Ambiente de desenvolvimento — auto-update ignorado.')
        return False
    try:
        info = verificar_atualizacao()
    except Exception as e:
        logger.warning('[Update] Erro inesperado na checagem: %s', e)
        return False
    if not info or not info.get('disponivel'):
        _limpar_tentativas()   # estamos atualizados → zera o marcador
        return False
    if not info.get('url'):
        logger.warning('[Update] Versão nova %s sem URL de pacote — ignorando.',
                       info.get('versao'))
        return False

    # ANTI-LOOP: se já tentamos 2x atualizar para esta MESMA versão e o app
    # continua na antiga (instalador falhou/instalou no lugar errado), PARA de
    # tentar e abre a versão atual — evita o loop "baixa/instala/reabre" infinito.
    _MAX_TENTATIVAS = 2
    _ja = _tentativas_para(info['versao'])
    if _ja >= _MAX_TENTATIVAS:
        logger.error('[Update] Update para %s já tentado %dx sem sucesso — '
                     'ABRINDO a versão atual (instale manualmente). Anti-loop.',
                     info['versao'], _ja)
        return False

    logger.info('[Update] Atualização %s disponível (tentativa %d) — baixando e aplicando.',
                info['versao'], _ja + 1)
    zip_path = _baixar_com_splash(info)
    if not zip_path:
        # Não conseguiu baixar: NÃO trava o usuário, segue na versão atual.
        logger.warning('[Update] Download falhou — abrindo versão atual.')
        return False

    # Marca a tentativa ANTES de aplicar (se der loop, o contador cresce e o
    # anti-loop acima corta na próxima abertura).
    _registrar_tentativa(info['versao'])

    # .exe = SETUP (Inno, reinstala elevado com permissões); .zip = onedir
    # (robocopy por cima). A escolha segue a extensão do pacote baixado.
    if zip_path.lower().endswith('.exe'):
        aplicado = aplicar_atualizacao_setup(zip_path)
    else:
        aplicado = aplicar_atualizacao(zip_path)
    if aplicado:
        return True  # caller deve sair; o helper relança a versão nova
    logger.warning('[Update] Falha ao aplicar — abrindo versão atual.')
    return False
