@echo off
setlocal
cd /d "%~dp0"
title Gerar Setup x64

REM Compila o instalador Inno (setup_x64.iss) -> gera
REM ..\release\setup\<Nome>_Setup_x64.exe (que o publicar_update.ps1 publica no CDN).
REM O nome, a versao e o autor vem da FONTE UNICA:
REM   server/marca.py + server/version.py  ->  instalador\_marca.iss (gerado aqui)

set "PY=..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERRO] .venv nao encontrada. Rode PREPARAR_AMBIENTE_X64.bat antes.
  exit /b 1
)

REM 1) gera o _marca.iss (valores da fonte unica) e le o slug para os caminhos
"%PY%" gerar_marca_iss.py
if errorlevel 1 (
  echo [ERRO] Falha ao gerar _marca.iss a partir de server/marca.py.
  exit /b 1
)

set "NOME="
for /f "usebackq delims=" %%i in (`"%PY%" ..\ler_marca.py`) do set "NOME=%%i"
if not defined NOME (
  echo [ERRO] Nao consegui ler o nome em server/marca.py.
  exit /b 1
)

REM 2) Inno Setup
rem Inno pode estar instalado POR USUARIO (winget) ou para todos os usuarios
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo [ERRO] Inno Setup 6 nao encontrado ^(ISCC.exe^). Instale o Inno Setup 6.
  exit /b 1
)

if not exist "..\release\app\x64\%NOME%\%NOME%.exe" (
  echo [ERRO] Build do app nao encontrada em ..\release\app\x64\%NOME%. Rode GERAR_APP_X64.bat antes.
  exit /b 1
)

echo Gerando o instalador com o Inno Setup (%NOME%)...
"%ISCC%" "setup_x64.iss"
if errorlevel 1 (
  echo [ERRO] Falha ao gerar o setup com o ISCC.
  exit /b 1
)

if not exist "..\release\setup\%NOME%_Setup_x64.exe" (
  echo [ERRO] O ISCC rodou mas o setup nao apareceu em ..\release\setup\.
  exit /b 1
)

echo [OK] Setup gerado: ..\release\setup\%NOME%_Setup_x64.exe
exit /b 0