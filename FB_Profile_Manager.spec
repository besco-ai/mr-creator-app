# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import site
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs, collect_all

project_dir = Path(SPECPATH)
block_cipher = None

# FONTE UNICA de marca/endereco: server/marca.py (trocar marca = editar la)
import sys as _sys
_sys.path.insert(0, str(project_dir))
from server import marca as _marca

hiddenimports = []
hiddenimports += collect_submodules('playwright')
hiddenimports += collect_submodules('pyee')
hiddenimports += collect_submodules('greenlet')
hiddenimports += collect_submodules('webview')
hiddenimports += collect_submodules('mysql')
hiddenimports += collect_submodules('mysql.connector')
hiddenimports += collect_submodules('clr_loader')
hiddenimports += collect_submodules('cffi')
hiddenimports += collect_submodules('certifi')
hiddenimports += [
    'clr',
    'pythonnet',
    'mysql.connector',
    'mysql.connector.pooling',
    'mysql.connector.plugins',
    '_cffi_backend',
    'clr_loader.ffi',
    'clr_loader.netfx',
    'server.ixbrowser_runtime',
    'server.playwright_compat',
    'server.captcha_solver',
]

# A UI usa os marcadores da fonte unica ({{MARCA}}, {{AUTOR}}, {{DOMINIO}},
# {{URL_MAIL}}). Eles sao substituidos AQUI, no build, para o app rodar igual ao
# original: a janela abre por url= (arquivo). Se o HTML fosse passado como
# CONTEUDO (html=), o Chromium bloquearia o CSS/JS locais e a UI abriria sem
# estilo. Substituir no build mantem a marca em um lugar so (server/marca.py).
import shutil as _shutil
_client_build = project_dir / 'build' / 'client_marca'
_shutil.rmtree(_client_build, ignore_errors=True)
# dirs_exist_ok: a pasta do projeto esta dentro do OneDrive, que as vezes segura
# arquivo antigo e faz o rmtree acima falhar em silencio. Assim a copia nao quebra.
_shutil.copytree(project_dir / 'client', _client_build, dirs_exist_ok=True)
for _p in _client_build.rglob('*'):
    if _p.is_file() and _p.suffix.lower() in ('.html', '.js', '.css'):
        _t = _p.read_text(encoding='utf-8')
        _n = _marca.substituir_marcadores(_t)
        if _n != _t:
            _p.write_text(_n, encoding='utf-8')

_datas = [
    (str(_client_build), 'client'),
]

# ---------------------------------------------------------------------------
# SEGURANCA (2026-07-25): NAO empacotar a pasta config/ INTEIRA.
# A pasta config/ do dev contem SEGREDOS que iam parar no _internal/config de
# TODO cliente (extrair o onedir e ler e trivial):
#   - config/database.php  -> DB_PASS prod, BlackcatPay sk_live_/pk_live_,
#                             Cloudflare Global API Key, FTP_PASS, HMAC GS-SIG
#   - config/senha.txt, usuario.txt, lembrar_acesso.txt
#   - config/<Usuario>/*   -> adspower_token, captcha_token, sms24h_token,
#                             datacrazy_senha, lista_proxy (dados do dev)
# O config OPERACIONAL fica AO LADO do .exe (backend.RUNTIME_DIR =
# dirname(sys.executable)), criado limpo no 1o run — NAO e este _internal/config.
# Portanto embarcamos SOMENTE templates NAO-secretos (defaults de comportamento).
_config_seed = [
    'automacao_config.json',
    'perfil_EXEMPLO.json',
    'perfil_SKIP_WARMUP.json',
]
for _cf in _config_seed:
    _cfp = project_dir / 'config' / _cf
    if _cfp.exists():
        _datas.append((str(_cfp), 'config'))

_datas += collect_data_files('webview', include_py_files=False)
_datas += collect_data_files('pythonnet', include_py_files=False)
_datas += collect_data_files('clr_loader', include_py_files=False)
_datas += collect_data_files('cffi', include_py_files=False)

_binaries = []
_binaries += collect_dynamic_libs('pythonnet')
_binaries += collect_dynamic_libs('clr_loader')
_binaries += collect_dynamic_libs('cffi')

_playwright_datas, _playwright_bins, _playwright_hidden = collect_all('playwright')
_datas += _playwright_datas
_binaries += _playwright_bins
hiddenimports += _playwright_hidden

_pyee_datas, _pyee_bins, _pyee_hidden = collect_all('pyee')
_datas += _pyee_datas
_binaries += _pyee_bins
hiddenimports += _pyee_hidden

_greenlet_datas, _greenlet_bins, _greenlet_hidden = collect_all('greenlet')
_datas += _greenlet_datas
_binaries += _greenlet_bins
hiddenimports += _greenlet_hidden

_mysql_datas, _mysql_bins, _mysql_hidden = collect_all('mysql')
_datas += _mysql_datas
_binaries += _mysql_bins
hiddenimports += _mysql_hidden

_cffi_datas, _cffi_bins, _cffi_hidden = collect_all('cffi')
_datas += _cffi_datas
_binaries += _cffi_bins
hiddenimports += _cffi_hidden

_clr_datas, _clr_bins, _clr_hidden = collect_all('clr_loader')
_datas += _clr_datas
_binaries += _clr_bins
hiddenimports += _clr_hidden

# ---------------------------------------------------------------------------
# CRÍTICO p/ login do Facebook: 2FA (pyotp) e ESC/automação (pyautogui).
# Sem esses módulos no executável, o bot digita o segredo cru como código 2FA
# (erro em todos os perfis) e não consegue remover a bolha "Fazer login".
# Cada pacote é coletado com try/except para não quebrar o build se faltar.
# ---------------------------------------------------------------------------
for _pkg in ('pyotp', 'pyautogui', 'pyscreeze', 'pytweening', 'mouseinfo',
             'pygetwindow', 'pyperclip', 'pymsgbox', 'pyrect', 'PIL', 'numpy'):
    try:
        _p_datas, _p_bins, _p_hidden = collect_all(_pkg)
        _datas += _p_datas
        _binaries += _p_bins
        hiddenimports += _p_hidden
    except Exception:
        pass

hiddenimports += ['pyotp', 'pyautogui', 'pyscreeze', 'PIL', 'PIL.Image']

site_candidates = []
try:
    site_candidates.extend(site.getsitepackages())
except Exception:
    pass
try:
    site_candidates.append(site.getusersitepackages())
except Exception:
    pass

seen = set()
for base in site_candidates:
    if not base:
        continue
    webview_pkg = Path(base) / 'webview'
    lib_dir = webview_pkg / 'lib'
    if lib_dir.exists():
        for item in lib_dir.rglob('*'):
            if item.is_file():
                rel_parent = (Path('webview') / item.parent.relative_to(webview_pkg)).as_posix()
                key = (str(item), rel_parent)
                if key not in seen:
                    _datas.append((str(item), rel_parent))
                    seen.add(key)


a = Analysis(
    ['main.py'],
    pathex=[str(project_dir)],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=_marca.MARCA_SLUG,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project_dir / 'logo.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=_marca.MARCA_SLUG,
    contents_directory='.',
)
