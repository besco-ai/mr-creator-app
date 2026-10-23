@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Atualizar e Publicar

echo ==================================================
echo    ATUALIZAR E PUBLICAR
echo ==================================================
echo.
echo Este assistente faz TUDO sozinho:
echo   1) Sobe a versao        (server\version.py)
echo   2) Gera o aplicativo    (.exe, PyInstaller)
echo   3) Gera o instalador    (Inno Setup)
echo   4) Publica no CDN       (o app auto-atualiza ao abrir)
echo.
echo Nome, versao e enderecos vem da FONTE UNICA: server\marca.py
echo.

REM --- 0) Checagem basica ------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [ERRO] .venv nao encontrada. Rode antes: PREPARAR_AMBIENTE_X64.bat
  pause ^& exit /b 1
)

REM --- 1) Notas da versao (opcional) ------------------------------------
set "NOTAS="
set /p NOTAS=Notas desta versao (Enter para o padrao):

REM --- 2) Sobe o MINOR da versao e captura o novo numero ----------------
set "NOVA="
for /f "usebackq delims=" %%V in (`powershell -NoProfile -ExecutionPolicy Bypass -File "update_server\bump_version.ps1"`) do set "NOVA=%%V"
if not defined NOVA (
  echo [ERRO] Falha ao subir a versao em server\version.py
  pause ^& exit /b 1
)
if "!NOTAS!"=="" set "NOTAS=Atualizacao v!NOVA!"
echo.
echo Nova versao: !NOVA!
echo Notas......: !NOTAS!
echo.

REM --- 3) Gera o .exe (build x64) ---------------------------------------
echo [1/4] Gerando o aplicativo... pode levar alguns minutos, aguarde.
call GERAR_APP_X64.bat ^< nul
if errorlevel 1 (
  echo [ERRO] Falha ao gerar a build. Nada foi publicado.
  pause ^& exit /b 1
)

REM --- 4) Gera o SETUP (instalador Inno) --------------------------------
echo.
echo [2/4] Gerando o instalador (setup)...
call instalador\GERAR_SETUP_X64.bat ^< nul
if errorlevel 1 (
  echo [AVISO] Nao gerei o setup (Inno Setup 6 instalado?). Vou publicar como ZIP.
)

REM --- 5) Publica no CDN (setup se existir; senao zip) -----------------
REM A versao e os nomes vem da FONTE UNICA dentro do publicador (server/marca.py +
REM server/version.py), entao nada de versao vazia aqui. A publicacao sobe pela VPS
REM (chave SSH) e de la para o balde/CDN - nao usa senha.
for /f "usebackq tokens=2 delims='" %%V in (`findstr /r /c:"APP_VERSION *= *'" "server\version.py"`) do set "NOVA=%%V"
echo.
echo [3/4] Publicando v!NOVA! no CDN...
echo      (o upload do instalador ~200 MB pode levar alguns minutos - aguarde)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "update_server\publicar_update.ps1" -Notes "!NOTAS!"
set "PUBRC=!errorlevel!"

echo.
if not "!PUBRC!"=="0" (
  echo ==================================================
  echo  [ERRO] Falha ao publicar ^(codigo !PUBRC!^).
  echo  A build/setup foram gerados, mas o manifesto do CDN
  echo  pode NAO ter sido atualizado. Verifique a chave SSH/rede.
  echo ==================================================
) else (
  echo ==================================================
  echo  [OK] Versao !NOVA! publicada!
  echo  Quem abrir a versao antiga baixa sozinho.
  echo ==================================================
  echo.
  echo Lembrete: este pacote e so do APLICATIVO. Mudanca no painel
  echo ou no servico de e-mail nao entra aqui.
)

REM --- FIM: janela SEMPRE pausa aqui (sucesso ou erro), nunca fecha sozinha ---
echo.
echo ==================================================
echo  Terminou. Pressione qualquer tecla para fechar.
echo ==================================================
powershell -NoProfile -Command "$null=[System.Console]::ReadKey($true)" 2^>nul
exit /b !PUBRC!