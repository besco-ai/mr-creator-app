@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo =============================================
echo   Build do app x64 (nome vem de server/marca.py)
echo =============================================

if not exist ".venv\Scripts\python.exe" (
  echo [ERRO] A .venv nao foi encontrada.
  echo Execute antes: PREPARAR_AMBIENTE_X64.bat
  pause
  exit /b 1
)

.\.venv\Scripts\python.exe -c "import struct, sys; bits=struct.calcsize('P')*8; print(bits); sys.exit(0 if bits==64 else 1)"

rem Nome do app/pacote vem da FONTE UNICA (server/marca.py)
set "NOME="
for /f "usebackq delims=" %%i in (`".venv\Scripts\python.exe" ler_marca.py`) do set "NOME=%%i"
if not defined NOME (
  echo [ERRO] Nao consegui ler o nome em server/marca.py. Rode PREPARAR_AMBIENTE_X64.bat antes.
  exit /b 1
)
if errorlevel 1 (
  echo [ERRO] A .venv atual nao e 64-bit.
  pause
  exit /b 1
)

if exist "build\pyinstaller_x64" rmdir /s /q "build\pyinstaller_x64"
if exist "dist\%NOME%" rmdir /s /q "dist\%NOME%"
if exist "release\app\x64\%NOME%" rmdir /s /q "release\app\x64\%NOME%"
rem Limpa tambem as pastas com o nome ANTIGO (GS_FB Creator), se existirem.
if exist "dist\%NOME%" rmdir /s /q "dist\%NOME%"
if exist "release\app\x64\%NOME%" rmdir /s /q "release\app\x64\%NOME%"

mkdir "build\pyinstaller_x64" >nul 2>nul
mkdir "release\app\x64" >nul 2>nul

.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath "dist" --workpath "build\pyinstaller_x64" "FB_Profile_Manager.spec"
if errorlevel 1 (
  echo [ERRO] Falha ao gerar a build x64.
  pause
  exit /b 1
)

if exist "instalador\launcher\INICIAR_APP.bat" copy /y "instalador\launcher\INICIAR_APP.bat" "dist\%NOME%\INICIAR_APP.bat" >nul
if exist "instalador\launcher\primeira_execucao.ps1" copy /y "instalador\launcher\primeira_execucao.ps1" "dist\%NOME%\primeira_execucao.ps1" >nul

robocopy "dist\%NOME%" "release\app\x64\%NOME%" /MIR >nul
rem ATENCAO: robocopy retorna 0-7 em SUCESSO (1 = arquivos copiados). So 8+ e erro.
if errorlevel 8 (
  echo [ERRO] Falha ao copiar a build para release\app\x64.
  pause
  exit /b 1
)

echo.
echo [OK] Build x64 pronta em:
echo %cd%\release\app\x64\%NOME%
pause
rem IMPORTANTE: zera o errorlevel (o robocopy deixa 1 mesmo em sucesso). Sem isto
rem o GERAR_TUDO_X64.bat acha que falhou e nao chama o GERAR_SETUP.
exit /b 0
