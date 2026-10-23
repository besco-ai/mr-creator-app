@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

call PREPARAR_AMBIENTE_X64.bat
if errorlevel 1 exit /b 1

call GERAR_APP_X64.bat
if errorlevel 1 exit /b 1

call instalador\GERAR_SETUP_X64.bat
if errorlevel 1 exit /b 1

echo.
echo [OK] Processo concluido.
echo Setup final gerado em: %cd%\release\setup
pause
