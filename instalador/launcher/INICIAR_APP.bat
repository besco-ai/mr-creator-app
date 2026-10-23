@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
rem Inicia o launcher SEM janela de console visivel (sem prompt de comando).
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%SCRIPT_DIR%primeira_execucao.ps1"
endlocal
exit
