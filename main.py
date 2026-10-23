#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GS BM Creator - Criador de Business Manager Facebook
=====================================================
Importa perfis Facebook via painel GranaSocial ou arquivo .txt,
cria navegadores (IXBrowser / AdsPower) e automatiza criação de BM.
"""

import ctypes
import logging
import os
import sys

# BLINDAGEM DE ENCODING (2026-07-13): no app CONGELADO (PyInstaller/Windows) o stdout/
# stderr costuma ser cp1252 → print() de EMOJI (ex.: 🔄) levantava UnicodeEncodeError
# 'charmap' e derrubava threads inteiras (todos os perfis viravam "Erro fatal"). Força
# UTF-8 com errors='replace' já na entrada — nunca mais crasha por caractere.
for _std in ('stdout', 'stderr'):
    try:
        getattr(sys, _std).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import traceback
import warnings

# Suprimir DeprecationWarnings do paramiko/cryptography (TripleDES) antes de qualquer import
warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko.*')
warnings.filterwarnings('ignore', message='.*TripleDES.*')
warnings.filterwarnings('ignore', message='.*CryptographyDeprecation.*')

# Em Windows, o pywebview usa pythonnet/clr para hospedar o WinForms. Forçamos o
# runtime .NET FRAMEWORK (netfx) ANTES de qualquer import do webview/clr.
#
# POR QUÊ (causa do "Failed to resolve Python.Runtime.Loader.Initialize" em outras
# máquinas): sem isso, o pythonnet autodetecta o runtime e tenta o coreclr
# (.NET Core/5+), que NÃO existe numa máquina Windows limpa → falha ao inicializar
# o Python.Runtime.dll. Já o .NET Framework 4.x vem embutido em todo Windows 10/11,
# então netfx funciona em qualquer máquina, sem instalar nada.
#
# Além do env var (que o 'import clr' do pywebview respeita), CARREGAMOS o CLR
# explicitamente aqui — assim o runtime é fixado de forma determinística e não
# depende da autodetecção do pythonnet no app empacotado.
if os.name == 'nt':
    os.environ['PYTHONNET_RUNTIME'] = 'netfx'
    try:
        import pythonnet
        pythonnet.load('netfx')
    except Exception as _e:
        # Não aborta: o env var acima ainda orienta o 'import clr' do pywebview.
        try:
            logging.getLogger(__name__).warning(
                'Falha ao pré-carregar o CLR netfx (%s); seguindo via PYTHONNET_RUNTIME.', _e)
        except Exception:
            pass

from server.funcoes_janela import fechar, minimizar


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def runtime_base_dir():
    """Diretório persistente para logs quando estiver em executável."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath('.')


def configurar_logs():
    logs_dir = os.path.join(runtime_base_dir(), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, 'fb_profile_manager.log')

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '') == log_file for h in root.handlers):
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    def _handle_exception(exc_type, exc_value, exc_traceback):
        logging.getLogger(__name__).critical(
            'Erro não tratado na aplicação:\n%s',
            ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        )

    sys.excepthook = _handle_exception

    if hasattr(sys, 'unraisablehook'):
        def _handle_unraisable(unraisable):
            logging.getLogger(__name__).critical(
                'Erro irrecuperável:\n%s',
                ''.join(traceback.format_exception(
                    type(unraisable.exc_value),
                    unraisable.exc_value,
                    unraisable.exc_traceback,
                ))
            )
        sys.unraisablehook = _handle_unraisable

    return log_file


def mostrar_erro_fatal(mensagem):
    try:
        ctypes.windll.user32.MessageBoxW(0, mensagem, 'GS BM Creator - Erro', 0x10)
    except Exception:
        pass


LOG_FILE = configurar_logs()
logger = logging.getLogger(__name__)
logger.info('Aplicação iniciada. Logs em: %s', LOG_FILE)

from server.backend import (
    carregar_configuracoes,
    salvar_configuracoes,
    salvar_config_troca_ip,
    testar_tokens_sms,
    importar_perfis,
    listar_compras_disponiveis_api,
    importar_perfis_comprados,
    consultar_perfis_disponiveis,
    definir_browser_engine,
    verificar_browser,
    verificar_ixbrowser,
    autenticar_usuario,
    iniciar_processamento,
    obter_progresso,
    cancelar_processamento,
    pausar_processamento,
    continuar_processamento,
    exportar_falhas_login,
    exportar_falhas_fluxo,
    reembolsar_perfis_pendentes,
    obter_fila_verificacao,
    iniciar_verificacao_fila,
    cancelar_verificacao_fila,
    limpar_fila_verificadas,
    retentar_erros_fila,
    definir_auto_verificar,
    definir_recurso_com_texto,
    obter_saldo_coins_painel,
    obter_nivel_acesso,
    iniciar_reprocesso_verificacao,
    cancelar_reprocesso_verificacao,
    obter_reprocesso_status,
    reprocessar_pendentes_agora,
    iniciar_monitor_analise,
    cancelar_monitor_analise,
    obter_monitor_status,
    contar_bms_monitoraveis,
    listar_grupos_adspower,
)


def iniciar_interface():
    # Import tardio para registrar qualquer falha de carregamento do WebView2 no log.
    from webview import create_window, start

    # A janela abre por url= (o ARQUIVO), igual ao original. NAO usar html=:
    # passando o HTML como conteudo o Chromium bloqueia o CSS/JS locais e a UI
    # abre sem estilo nenhum. Os marcadores {{MARCA}} ja vem substituidos no
    # build (FB_Profile_Manager.spec), a partir de server/marca.py.
    from server import marca as _marca

    janela = create_window(
        title=_marca.MARCA,
        url=resource_path('client/index.html'),
        width=1100,
        height=750,
        frameless=True,
        # Mínimo BAIXO para permitir o MODO COMPACTO (GUI ~600x600 no canto ao
        # processar, com os navegadores ocupando o resto da tela).
        min_size=(380, 440),
    )

    janela.expose(
        fechar,
        minimizar,
        carregar_configuracoes,
        salvar_configuracoes,
        salvar_config_troca_ip,
        testar_tokens_sms,
        importar_perfis,
        listar_compras_disponiveis_api,
        importar_perfis_comprados,
        consultar_perfis_disponiveis,
        definir_browser_engine,
        verificar_browser,
        verificar_ixbrowser,
        autenticar_usuario,
        iniciar_processamento,
        obter_progresso,
        cancelar_processamento,
        pausar_processamento,
        continuar_processamento,
        exportar_falhas_login,
        exportar_falhas_fluxo,
        obter_fila_verificacao,
        iniciar_verificacao_fila,
        cancelar_verificacao_fila,
        limpar_fila_verificadas,
        retentar_erros_fila,
        definir_auto_verificar,
        definir_recurso_com_texto,
        obter_saldo_coins_painel,
        obter_nivel_acesso,
        iniciar_reprocesso_verificacao,
        cancelar_reprocesso_verificacao,
        obter_reprocesso_status,
        reprocessar_pendentes_agora,
        iniciar_monitor_analise,
        cancelar_monitor_analise,
        obter_monitor_status,
        contar_bms_monitoraveis,
        listar_grupos_adspower,
    )

    # Correção do arrasto da janela frameless: o pywebview repassa as coordenadas
    # do drag como FLOAT, e o SetWindowPos (Win32) exige INT — gerava
    # "ctypes.ArgumentError: argument 5: wrong type" (não-fatal, mas polui o log e
    # podia falhar o reposicionamento). Aqui forçamos x/y para inteiro.
    try:
        _orig_move = janela.move

        def _move_int(x, y, *a, **k):
            try:
                x = int(round(float(x)))
                y = int(round(float(y)))
            except Exception:
                pass
            try:
                return _orig_move(x, y, *a, **k)
            except Exception:
                # O SetWindowPos interno do pywebview/winforms ainda pode receber
                # cx/cy FLOAT (DPI scaling) ou um HWND inválido numa corrida →
                # 'ctypes.ArgumentError: argument 5: wrong type'. É 100% cosmético
                # (só reposiciona a janela frameless da GUI). SWALLOW: não relança
                # (senão explode dezenas de "Exception during on_script_notify" por
                # segundo com muitos workers) e não trava nada.
                return None

        janela.move = _move_int
    except Exception:
        pass

    start(debug=False)

    # App fechado — encerrar sessão e reembolsar coins de perfis não processados
    try:
        from server.backend import logout_usuario as _logout
        _logout()
    except Exception:
        pass
    try:
        reembolsar_perfis_pendentes()
    except Exception:
        pass


def _checar_auto_update():
    """Antes de abrir a GUI: se houver versão nova publicada na VPS, baixa e
    aplica (relança o app). Retorna True se uma atualização está sendo aplicada
    (o processo deve encerrar imediatamente)."""
    try:
        from server.atualizador import executar_fluxo_update_se_preciso, APP_VERSION
        logger.info('Verificando atualizações... (versão local %s)', APP_VERSION)
        if executar_fluxo_update_se_preciso():
            logger.info('Atualização em andamento — encerrando para o helper relançar.')
            return True
    except Exception as _e:
        # Falha na checagem NUNCA deve impedir a abertura do app.
        logger.warning('Auto-update ignorado (erro na checagem): %s', _e)
    return False


if __name__ == '__main__':
    try:
        # 1) Auto-atualização (só quando empacotado; silencioso/seguro se offline).
        if _checar_auto_update():
            sys.exit(0)
        # 2) Abre a interface normalmente.
        iniciar_interface()
    except SystemExit:
        raise
    except Exception:
        detalhes = traceback.format_exc()
        logger.critical('Falha fatal ao iniciar a interface.\n%s', detalhes)
        # RECUPERAÇÃO AUTOMÁTICA de falha TRANSITÓRIA na init do CLR/pythonnet
        # (netfx): "Failed to initialize Python.Runtime.dll" / NullReferenceException
        # em TypeManager.Initialize. Não é do nosso código — é um flake do pythonnet
        # ao carregar o .NET; um PROCESSO NOVO quase sempre resolve. Relançamos UMA
        # vez (guarda anti-loop via GSBM_RELAUNCH) antes de mostrar o erro ao usuário.
        _det_low = detalhes.lower()
        _erro_clr = ('python.runtime' in _det_low or 'pythonnet' in _det_low
                     or 'failed to initialize' in _det_low or 'clr' in _det_low)
        if _erro_clr and os.name == 'nt' and os.environ.get('GSBM_RELAUNCH') != '1':
            try:
                logger.warning('Erro transitório de CLR/pythonnet — relançando o app uma vez...')
                import subprocess
                _env = dict(os.environ)
                _env['GSBM_RELAUNCH'] = '1'
                subprocess.Popen([sys.executable] + sys.argv[1:] if getattr(sys, 'frozen', False)
                                 else [sys.executable] + sys.argv,
                                 env=_env,
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
                sys.exit(0)
            except Exception as _re:
                logger.warning('Falha ao relançar automaticamente: %s', _re)
        mostrar_erro_fatal(
            'Falha ao iniciar a interface do aplicativo.\n\n'
            'Verifique o arquivo de log em:\n'
            f'{LOG_FILE}\n\n'
            'Detalhe técnico resumido:\n'
            f'{detalhes.splitlines()[-1] if detalhes.splitlines() else "Erro desconhecido"}'
        )
        raise
