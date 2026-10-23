@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo =============================================
echo   GS BM Creator - Preparar Ambiente x64
echo =============================================

where python >nul 2>nul
if errorlevel 1 (
  echo [ERRO] Python nao encontrado no PATH.
  echo Instale o Python 3.10.11 x64 e abra novamente o terminal.
  pause
  exit /b 1
)

python -c "import struct, sys; bits=struct.calcsize('P')*8; print(bits); sys.exit(0 if bits==64 else 1)"
if errorlevel 1 (
  echo [ERRO] O Python ativo nao e 64-bit.
  echo Selecione um Python 64-bit no VS Code e tente novamente.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Criando .venv x64...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERRO] Falha ao criar a .venv.
    pause
    exit /b 1
  )
)

echo Atualizando pip e instalando dependencias...
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
  echo [ERRO] Falha ao atualizar pip.
  pause
  exit /b 1
)

rem Instala EXATAMENTE as versoes do requirements.txt (interop pythonnet/.NET e
rem sensivel a versao) + o PyInstaller (ferramenta de build). Sem --upgrade para
rem que os pins "==" do requirements.txt sejam respeitados.
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo [ERRO] Falha ao instalar dependencias.
  pause
  exit /b 1
)

echo.
echo [OK] Ambiente x64 pronto.
echo Venv: %cd%\.venv
pause
exit /b 0
