# -*- coding: utf-8 -*-

"""
Backend Principal - GS BM Creator (v4.0)
=========================================
Funções expostas ao JavaScript via PyWebView.
Suporte a IXBrowser + AdsPower.
Importação de perfis do painel GranaSocial + .txt.
Registro de BMs criadas via API web.
"""

import os
import json
import time
import threading
import logging
import subprocess
import atexit
from server.parser_perfis import parsear_conteudo_txt

# ============================================================================
# MÓDULOS DE BROWSER (IXBrowser + AdsPower)
# ============================================================================

from server import ixbrowser_api
from server import adspower_api

# ============================================================================
# AUTOMAÇÃO
# ============================================================================

from server.automacao_facebook import executar_automacao_perfil

# ============================================================================
# VERIFICAÇÃO DE BM (preencher empresa + domínio)
# ============================================================================

try:
    from server.verificacao_bm import (
        executar_verificacao_completa_bm,
        executar_verificacao_completo_datacrazy_pro_max,
    )
    _TEM_VERIFICACAO = True
except ImportError as e:
    logging.getLogger(__name__).warning(f"Módulo de verificação não disponível: {e}")
    _TEM_VERIFICACAO = False

# ============================================================================
# FILA DE VERIFICAÇÃO DE BM (agendamento 2h)
# ============================================================================

from server.bm_queue_manager import (
    adicionar_bm_na_fila,
    obter_resumo_fila,
    obter_bms_prontas,
    atualizar_status_bm,
    limpar_verificadas as _limpar_verificadas_queue,
    TEMPO_MINIMO_ESPERA,
)

# ============================================================================
# ACESSO E PAINEL (via API web)
# ============================================================================

try:
    from server.acesso import (
        validar_usuario,
        obter_perfis_disponiveis as _obter_perfis_api,
        marcar_perfil_usado,
        registrar_bm_criada,
        obter_contagem_perfis,
        obter_saldo_coins,
        consultar_coins_api,
        debitar_coins,
        reembolsar_coin,
        reembolsar_token,
        debitar_token,
        usuario_uso_livre,
        usuario_pode_planos_gupshup,
        usuario_eh_admin,
        obter_dados_sessao,
        esta_autenticado,
        logout_usuario,
        buscar_empresas_ativas,
        criar_site_empresa,
        reservar_subdominio,
        marcar_empresa_usada,
        salvar_meta_tags_site,
        comprar_numero_sms,
        comprar_numero_verificacao_bm,
        verificar_sms_recebido,
        cancelar_sms,
        obter_detalhes_site,
    )
    _TEM_ACESSO = True
except ImportError as e:
    logging.getLogger(__name__).warning(f"Módulo de acesso não disponível: {e}")
    _TEM_ACESSO = False
    def validar_usuario(u, s): return True
    def _obter_perfis_api(): return {'sucesso': False, 'perfis': [], 'total': 0}
    def marcar_perfil_usado(c, p=0): return False
    def registrar_bm_criada(**kw): return {'sucesso': False}
    def obter_contagem_perfis(): return 0
    def obter_saldo_coins(): return 0
    def consultar_coins_api(): return {'sucesso': False, 'coins': 0}
    def debitar_coins(q, d=''): return {'sucesso': False, 'coins': 0}
    def reembolsar_coin(q=1, d=''): return {'sucesso': False}
    def reembolsar_token(q=1, d=''): return {'sucesso': False}
    def debitar_token(q=1, d=''): return {'sucesso': False, 'tokens': 0}
    def usuario_uso_livre(): return False
    def usuario_pode_planos_gupshup(): return False
    def usuario_eh_admin(): return False
    def obter_dados_sessao(): return {}
    def esta_autenticado(): return False
    def logout_usuario(): pass
    def buscar_empresas_ativas(t='', c='', e=''): return {'sucesso': False, 'empresas': []}
    def criar_site_empresa(cnpj, callback_status=None, deve_continuar=None, subdominio='', dominio_raiz=''): return {'sucesso': False}
    def reservar_subdominio(cnpj): return {}
    def marcar_empresa_usada(cnpj, motivo=''): return {'sucesso': False}
    def salvar_meta_tags_site(sid, mt): return {'sucesso': False}
    def comprar_numero_sms(s='fb'): return {'sucesso': False}
    def comprar_numero_verificacao_bm(): return {'sucesso': False}
    def verificar_sms_recebido(aid): return {'sucesso': False}
    def cancelar_sms(aid): return {'sucesso': False}
    def obter_detalhes_site(sid): return {'sucesso': False}

logger = logging.getLogger(__name__)

# Registro LOCAL OCULTO de perfis criados/importados pela ferramenta (prova offline
# de posse p/ o portão das funções "Reutilizar Logados" / "Reprocessar por grupo").
try:
    from server import perfis_proprios as _perfis_proprios
except Exception as _e:  # nunca pode quebrar a importação do backend
    logging.getLogger(__name__).warning("perfis_proprios indisponível: %s", _e)
    _perfis_proprios = None

import sys

# ÚNICO FLUXO do GS Creator (2026-10-05, decisão do dono): ⚡ Pro Max DataCrazy Turbo.
# Básico/Padrão/Avançado/Gupshup/Pro Max DataCrazy (CRM)/E-mail/Sem WABA/GS Prime
# Plus/HighLevel foram REMOVIDOS do sistema. Qualquer valor vindo da GUI é
# normalizado para FLUXO_UNICO em iniciar_processamento.
FLUXO_UNICO = 'full_completo_datacrazy_meta'

COINS_POR_BM = 2.5  # Custo por BM entregue (= COINS_POR_METODO[FLUXO_UNICO]); usado no saldo da GUI

# Custo de USO da ferramenta em COINS (cobrado SOMENTE no marco de SUCESSO/entrega:
# BM enviada p/ análise). O token do site (criação do site do usuário) é cobrado
# À PARTE no servidor e NÃO entra aqui. Saldo exibido ao usuário = coins.
COINS_POR_METODO = {
    # ⚡ Pro Max DataCrazy Turbo: BM + empresa + site/domínio + WABA (OAuth da Meta
    # direto, sem CRM) + envio p/ análise na Central de Segurança.
    FLUXO_UNICO: 2.5,
}

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

# Diretórios de runtime persistentes
BASE_DIR = resource_path('')
RUNTIME_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else BASE_DIR
CONFIG_DIR = os.path.join(RUNTIME_DIR, 'config')
LOGS_DIR = os.path.join(RUNTIME_DIR, 'logs')

# Estado global
_estado = {
    'perfis': [],
    'processando': False,
    'progresso': [],
    'total': 0,
    'concluidos': 0,
    'erros': 0,
    'recorridas': 0,   # WABA desabilitada + recurso ENVIADO (não é erro; é desfecho próprio)
    'recurso_com_texto': True,  # True=envia recurso com texto de contestação; False=formulário EM BRANCO
    'cancelar': False,
    'pausado': False,
    'usuario_logado': '',
    'browser_engine': 'ixbrowser',  # 'ixbrowser' ou 'adspower'
    'perfis_cobrados': {},  # login -> True(pendente) | False(concluído permanente)
    'verificar_bm': 'nao',      # 'nao' | 'imediata' (intermediário) | 'full'
    'tipo_empresa': 'mei',          # 'mei' ou 'ltda' — tipo de empresa para Fábrica
    'auto_verificar': False,        # True = verificar automaticamente quando prontas (2h)
    '_auto_verif_thread_ativo': False,  # Controle interno do watcher thread
    'compra_ids_origem': [],        # compra_ids relacionados aos perfis em uso
    # Buffer de empresa/site reaproveitavel: quando a BM falha ANTES de ser
    # criada, mantemos a empresa+site para reuso no proximo perfil (evita
    # desperdicar o token consumido na criacao do site).
    # Formato: {'empresa_dados': dict, 'site_cache': dict,
    #           'nome_bm_override': str, 'seu_nome_override': str,
    #           'tentativas': int, 'criado_em': float}
    'empresa_buffer': None,
}

# Limites do buffer de empresa reaproveitavel
_EMPRESA_BUFFER_MAX_TENTATIVAS = 3
_EMPRESA_BUFFER_TTL_SEG = 60 * 30  # 30 min

# SITES PROVISÓRIOS (2026-09-27): no fluxo WABA-antes-do-site, a empresa é preenchida
# com UM destes sites reais grandes (sempre no ar) SÓ para criar a WABA. O site REAL da
# empresa é gerado e vinculado depois, quando a WABA fica Aprovada. Nunca é verificado
# por meta-tag (é só o campo "Site" da empresa até a WABA aprovar).
_SITES_PROVISORIOS = [
    'globo.com', 'uol.com.br', 'magazineluiza.com.br', 'mercadolivre.com.br',
    'casasbahia.com.br', 'americanas.com.br', 'submarino.com.br', 'terra.com.br',
    'ig.com.br', 'estadao.com.br',
]


def _site_provisorio_aleatorio():
    """Um site provisório do pool (host puro, sem esquema — igual ao url_completa)."""
    import random as _r
    return _r.choice(_SITES_PROVISORIOS)

# ── Concorrência (Fase 2: navegadores simultâneos) ──
# Lock para incrementos thread-safe dos contadores em _estado.
_lock_estado = threading.Lock()
# Lock para SERIALIZAR a criação/abertura de navegador na API do AdsPower/IXBrowser
# (abrir 1 por vez evita floodar a API quando há vários workers).
_lock_abertura = threading.Lock()
# Atraso entre o início de cada worker (abertura escalonada 1-por-vez).
_STAGGER_ABERTURA = 4.0  # segundos (reduzido 2026-07-13: abre as abas mais rápido)

# ── Gate ANTI-CASCATA de criação de BM (IP compartilhado) ──────────────────
# Quando várias abas dividem o MESMO IP (4G/ancoragem, ou sem pool de proxy) e
# criam BM no MESMO instante, o Facebook lê isso como robô e DERRUBA todas em
# cascata. Este gate SERIALIZA a ENTRADA na criação da BM entre essas abas,
# com um intervalo humano aleatório — assim nenhuma BM nasce no mesmo segundo
# que a outra no mesmo IP. Login/warm-up/verificação (a parte LONGA) seguem em
# paralelo; só o "momento de nascer a BM" é espaçado, então o custo de tempo é
# mínimo. Com 1 proxy por aba (IP próprio) o gate NÃO atua.
_lock_criacao_ip = threading.Lock()
_ts_ultima_criacao_ip = [0.0]     # holder mutável do último timestamp de criação
# Intervalo (jitter) humano entre criações no MESMO IP. AJUSTE AQUI o equilíbrio
# velocidade x indetectabilidade: menor = mais rápido, maior = mais seguro.
_GAP_CRIACAO_MESMO_IP = (5.0, 11.0)  # segundos (reduzido 2026-07-13 p/ agilidade)


def _gate_criacao_mesmo_ip(callback_status=None):
    """Espaça a ENTRADA na criação de BM entre abas que dividem o MESMO IP (4G/sem proxy).
    Só atua quando _estado['_ip_compartilhado'] é True.

    TICKET (2026-07-13): cada aba RESERVA seu slot atomicamente (lock BREVE) e ESPERA
    FORA do lock — assim as abas NÃO bloqueiam umas às outras (dormem EM PARALELO até o
    próprio slot), mantendo o espaçamento anti-cascata SEM o efeito 'uma depende da
    outra'. Antes, o lock era segurado durante todo o sleep (12-26s), serializando tudo.
    Tolerante a falhas — nunca quebra o fluxo."""
    try:
        if not _estado.get('_ip_compartilhado'):
            return
        import random as _rnd
        gap = _rnd.uniform(*_GAP_CRIACAO_MESMO_IP)
        # 1) RESERVA o slot (lock só p/ o cálculo atômico — instantâneo).
        with _lock_criacao_ip:
            agora = time.time()
            prox = max(agora, float(_ts_ultima_criacao_ip[0] or 0.0) + gap)
            _ts_ultima_criacao_ip[0] = prox
        # 2) ESPERA o próprio slot FORA do lock (não bloqueia as outras abas).
        espera = prox - time.time()
        if espera > 0 and not _estado.get('cancelar'):
            if callback_status:
                try:
                    callback_status(f"⏳ Janela de criação segura: ~{espera:.0f}s (anti-cascata, mesmo IP)...")
                except Exception:
                    pass
            _fim = time.time() + espera
            while time.time() < _fim and not _estado.get('cancelar'):
                time.sleep(min(0.5, max(0.0, _fim - time.time())))
    except Exception as _ge:
        logger.debug("[GateCriacao] ignorado: %s", _ge)


def _inc(chave, n=1):
    """Incremento thread-safe de um contador em _estado (concluidos/erros)."""
    with _lock_estado:
        _estado[chave] = _estado.get(chave, 0) + n


# Tamanho ALVO de cada janela na grade. Equilíbrio entre "ver várias" e
# CONFIABILIDADE: janelas maiores + DSF suave fazem o Facebook renderizar numa
# resolução desktop folgada, garantindo que todos os seletores sejam encontrados.
_JANELA_MAX_W = 900
_JANELA_MAX_H = 760
_JANELA_MIN_W = 560
_JANELA_MIN_H = 480
# DSF (--force-device-scale-factor): renderiza desktop numa janela pequena.
# DESATIVADO por padrão: ele interfere no MUI Autocomplete do Gupshup (a lista de
# países renderiza vazia / 'No options', pois o popper mede o DPR alterado). Com
# DSF off, a janela renderiza no TAMANHO FÍSICO real (que já é grande o bastante
# para o layout desktop). Coloque True só se quiser janelas bem menores.
_USAR_DSF = True
_TARGET_CSS_W = 1200
_DSF_MIN = 0.62

# CASCATA (fluxo FULL/Gupshup): o Gupshup quebra em janela pequena/DSF (render
# mobile + "No options" no seletor de país). Então, no Full, NUNCA encolhemos: cada
# navegador abre em TAMANHO DESKTOP e as janelas ficam SOBREPOSTAS em cascata
# (a automação não precisa vê-las; o progresso aparece nos cards da GUI).
_CASCATA_W = 1160
_CASCATA_H = 780

# INTERRUPTOR MESTRE da manipulação de janela (tiling/tamanho/posição/DSF).
# DESLIGADO por padrão: o Gupshup dá "No options" na lista de países sempre que a
# janela é manipulada (tamanho/posição/DSF) — reproduzido pelo usuário; com a
# JANELA ORIGINAL (padrão do fingerprint AdsPower/IXBrowser, sem nenhum arg de
# janela) o erro NÃO acontece. Com isto False, NUNCA passamos `janela` para o
# abrir_navegador → cada navegador abre no tamanho nativo do próprio perfil. Em
# paralelo as janelas podem se sobrepor (sem grade), mas o fluxo funciona. Mude
# para True só se quiser reativar o tiling em grade.
# REATIVADO: a opção Full (Gupshup) foi ocultada da GUI, então o bug de região do
# Gupshup não afeta mais o que os usuários usam (só Padrão/Intermediário). Voltamos
# à grade com DSF suave (janelas maiores, render desktop folgado, seletores
# confiáveis): 1-2→900×760 (DSF 0.75), 3-4→760×516 (0.63), 6→680×480 (0.62).
_MANIPULAR_JANELA = True


# Retângulo central reservado para a interface gráfica (preenchido por
# _calcular_grade_janelas). A GUI é movida para cá e fica sempre visível.
_GUI_RECT = None


def _metricas_tela():
    """Resolução útil da tela primária (adapta-se a qualquer monitor)."""
    sw, sh = 1920, 1080
    try:
        import ctypes
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        sw = int(user32.GetSystemMetrics(0)) or sw
        sh = int(user32.GetSystemMetrics(1)) or sh
    except Exception:
        pass
    return sw, sh


def _dsf_para(cell_w):
    if _USAR_DSF:
        return round(min(1.0, max(_DSF_MIN, cell_w / float(_TARGET_CSS_W))), 3)
    return 1.0


def _grade_cheia(n, area_w, area_h):
    """Grade que preenche a tela inteira (fallback quando há navegadores demais
    para caber EM VOLTA da GUI). Prefere nº PAR de colunas para que nenhuma
    janela fique exatamente no centro (onde a GUI flutua) totalmente coberta."""
    import math
    if n <= 2:
        alvo_w, alvo_h = 900, 760
    elif n <= 4:
        alvo_w, alvo_h = 760, 640
    elif n <= 6:
        alvo_w, alvo_h = 680, 560
    else:
        alvo_w, alvo_h = 620, 480
    alvo_w = max(_JANELA_MIN_W, min(_JANELA_MAX_W, alvo_w))
    alvo_h = max(_JANELA_MIN_H, min(_JANELA_MAX_H, alvo_h))
    cols = max(1, min(n, area_w // alvo_w))
    if cols >= 3 and cols % 2 == 1:
        cols -= 1                     # evita coluna central exata sob a GUI
    cols = max(1, cols)
    rows = max(1, math.ceil(n / cols))
    cell_w = max(_JANELA_MIN_W, min(alvo_w, area_w // cols))
    cell_h = max(360, min(alvo_h, area_h // rows))
    dsf = _dsf_para(cell_w)
    cells = []
    for k in range(n):
        r, c = divmod(k, cols)
        cells.append({'x': c * cell_w, 'y': r * cell_h,
                      'w': cell_w, 'h': cell_h, 'dsf': dsf})
    return cells


def _grade_cascata(n, sw, area_h):
    """Janelas em TAMANHO DESKTOP, sobrepostas em cascata (degraus). Para o fluxo
    FULL/Gupshup, que precisa de render desktop confiável: nunca encolhe abaixo do
    tamanho seguro, então o Facebook/Gupshup sempre renderiza desktop e os seletores
    funcionam. As janelas se sobrepõem — o acompanhamento é pelos cards da GUI."""
    W = min(_CASCATA_W, sw)
    H = min(_CASCATA_H, area_h)
    dx, dy = 48, 40
    cols = max(1, (sw - W) // dx + 1)
    rows = max(1, (area_h - H) // dy + 1)
    por_ciclo = max(1, cols * rows)
    cells = []
    for k in range(n):
        s = k % por_ciclo
        cx = (s % cols) * dx
        cy = (s // cols) * dy
        cells.append({'x': int(cx), 'y': int(cy), 'w': int(W), 'h': int(H), 'dsf': 1.0})
    return cells


def _calcular_grade_janelas(n, flow=None):
    """Layout INTELIGENTE e ADAPTÁVEL a qualquer resolução/monitor:
    coloca a INTERFACE GRÁFICA no CANTO INFERIOR DIREITO (perto do relógio do
    Windows) e dispõe os navegadores no espaço RESTANTE — uma área em "L"
    (faixa superior de largura total + coluna à esquerda da GUI). Sem
    sobreposição: GUI e navegadores ficam 100% visíveis e legíveis."""
    global _GUI_RECT
    import math
    sw, sh = _metricas_tela()
    area_h = max(_JANELA_MIN_H, sh - 48)   # desconta a barra de tarefas
    n = max(1, min(20, int(n)))  # até 20 navegadores simultâneos

    if n <= 1:
        _GUI_RECT = None
        cw = min(_JANELA_MAX_W, sw)
        ch = min(_JANELA_MAX_H, area_h)
        return [{'x': 0, 'y': 0, 'w': cw, 'h': ch, 'dsf': _dsf_para(cw)}]

    # GUI em TAMANHO LEGÍVEL no CANTO INFERIOR DIREITO — o MESMO de quando abre 1
    # aba (1100x750), independentemente de 1 ou 10 simultâneos. Antes encolhia
    # para 440-600 (modo compacto) e escondia o terminal/os números — pedido do
    # usuário p/ manter um tamanho bom e 100% visível. Cap p/ caber na tela.
    gui_w = min(1100, sw)
    gui_h = min(750, area_h)
    gx = max(0, sw - gui_w)
    gy = max(0, area_h - gui_h)
    _GUI_RECT = {'x': gx, 'y': gy, 'w': gui_w, 'h': gui_h}

    # (2026-07-09, pedido do usuário) TODOS OS FLUXOS abrem os navegadores em CASCATA
    # de tamanho DESKTOP — igual ao Pro Max DataCrazy. Antes, só FULL/Pro Max usavam a
    # cascata; o básico/imediata caíam no tiling PEQUENO (460×300 empilhadas), que é o
    # que aparecia "cascateado no canto". A cascata desktop é mais confiável p/ o render
    # (Facebook sempre desktop, seletores estáveis) e é o layout que o usuário quer em
    # todos os fluxos — o acompanhamento é pelos cards da GUI (canto inferior direito).
    _flow_l = str(flow or '').lower()
    return _grade_cascata(n, sw, area_h)

    _MINW, _MINH = 460, 300
    # Área em "L" (tudo menos o canto da GUI), em 2 retângulos sem sobreposição:
    #   TOP  = faixa cheia ACIMA da GUI (largura total da tela)
    #   LEFT = coluna à ESQUERDA da GUI (abaixo da faixa de cima)
    rects = []
    if gy >= _MINH:
        rects.append((0, 0, sw, gy))                 # TOP (largura total)
    if gx >= _MINW:
        rects.append((0, gy, gx, area_h - gy))       # LEFT (ao lado da GUI)
    if not rects:                                     # GUI muito grande → usa tudo
        rects.append((0, 0, sw, area_h))

    def _cap(r):
        _x, _y, w, h = r
        return max(1, w // _MINW) * max(1, h // _MINH)
    caps = [_cap(r) for r in rects]

    # Distribui n priorizando a coluna ESQUERDA (janelas mais altas) e depois a
    # faixa de cima. (LEFT é sempre o ÚLTIMO retângulo da lista quando existe.)
    ordem = sorted(range(len(rects)), key=lambda i: 0 if i == len(rects) - 1 else 1)
    aloc = [0] * len(rects)
    rem = n
    for i in ordem:
        take = min(rem, caps[i])
        aloc[i] = take
        rem -= take
    # Sobra (n > capacidade total): distribui adensando as regiões em rodízio.
    _j = 0
    while rem > 0:
        aloc[ordem[_j % len(ordem)]] += 1
        rem -= 1
        _j += 1

    cells = []
    for (x0, y0, w0, h0), k in zip(rects, aloc):
        if k <= 0:
            continue
        cols = max(1, min(k, w0 // _MINW))
        rows = max(1, math.ceil(k / cols))
        cw = max(_MINW, w0 // cols)
        ch = max(_MINH, h0 // rows)
        for idx in range(k):
            rr, cc = divmod(idx, cols)
            cells.append({'x': x0 + cc * cw, 'y': y0 + rr * ch,
                          'w': cw, 'h': ch, 'dsf': _dsf_para(cw)})
    return cells


def _achar_hwnd_gui():
    """HWND da janela da interface gráfica ('GS BM Creator')."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        achados = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(h, _l):
            if not user32.IsWindowVisible(h):
                return True
            ln = user32.GetWindowTextLengthW(h)
            if ln <= 0:
                return True
            buf = ctypes.create_unicode_buffer(ln + 1)
            user32.GetWindowTextW(h, buf, ln + 1)
            if 'GS BM Creator' in (buf.value or ''):
                achados.append(h)
                return False
            return True

        user32.EnumWindows(_cb, 0)
        return achados[0] if achados else None
    except Exception:
        return None


def _centralizar_gui_topmost():
    """Centraliza a GUI no espaço reservado e a deixa SEMPRE no topo (100%
    visível e ao vivo) SEM roubar o foco da automação (SWP_NOACTIVATE)."""
    try:
        if not _GUI_RECT:
            return
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = _achar_hwnd_gui()
        if not hwnd:
            return
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = wintypes.BOOL
        HWND_TOPMOST = -1
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        r = _GUI_RECT
        user32.SetWindowPos(hwnd, HWND_TOPMOST, int(r['x']), int(r['y']),
                            int(r['w']), int(r['h']), SWP_NOACTIVATE | SWP_SHOWWINDOW)
        logger.info("[Janelas] GUI centralizada (%sx%s @ %s,%s) e fixada no topo.",
                    r['w'], r['h'], r['x'], r['y'])
    except Exception as e:
        logger.debug("[Janelas] centralizar GUI falhou: %s", e)


def _restaurar_gui_topmost():
    """Ao fim do lote: tira a GUI do modo sempre-no-topo E volta ao tamanho
    NORMAL (1100x750) centralizada — o modo compacto era só durante o processo."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = _achar_hwnd_gui()
        if not hwnd:
            return
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = wintypes.BOOL
        HWND_NOTOPMOST = -2
        SWP_NOACTIVATE = 0x0010
        sw, sh = _metricas_tela()
        nw, nh = 1100, 750
        nx = max(0, (sw - nw) // 2)
        ny = max(0, (sh - 48 - nh) // 2)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, int(nx), int(ny), int(nw), int(nh),
                            SWP_NOACTIVATE)
    except Exception as e:
        logger.debug("[Janelas] restaurar GUI falhou: %s", e)


def _garantir_pastas():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)


def _obter_caminho_config(nome, usuario=''):
    _garantir_pastas()
    if usuario:
        user_dir = os.path.join(CONFIG_DIR, usuario)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, f'{nome}.txt')
    return os.path.join(CONFIG_DIR, f'{nome}.txt')


def _ler_config(nome, padrao='', usuario=''):
    caminho = _obter_caminho_config(nome, usuario)
    try:
        if os.path.exists(caminho):
            # utf-8-sig: descarta o BOM que o Bloco de Notas/PowerShell colocam ao
            # editar estes .txt à mão. Um BOM invisível no início de um TOKEN vira
            # "chave inválida" na API — erro caríssimo de diagnosticar.
            with open(caminho, 'r', encoding='utf-8-sig') as f:
                return f.read().strip().lstrip('﻿')
    except:
        pass
    if usuario and not os.path.exists(caminho):
        return _ler_config(nome, padrao, '')
    return padrao


def _ler_captcha_token(usuario=''):
    """API key do CapSolver COM FALLBACK para a config global.

    Armadilha real: o arquivo do usuário pode EXISTIR e estar VAZIO (campo em
    branco salvo pela GUI). Nesse caso `_ler_config` devolve '' e NÃO cai no
    global — o bot fica sem chave, não resolve o reCAPTCHA do login e aborta o
    perfil ("sem token CapSolver"). Aqui: usuário → global.
    """
    tok = (_ler_config('captcha_token', '', usuario) or '').strip()
    if not tok and usuario:
        tok = (_ler_config('captcha_token', '', '') or '').strip()
    if not tok:
        logger.warning('[Captcha] Nenhuma API key do CapSolver configurada '
                       '(usuário=%s) — reCAPTCHA no login NÃO será resolvido.',
                       usuario or 'global')
    return tok


def _salvar_config(nome, valor, usuario=''):
    caminho = _obter_caminho_config(nome, usuario)
    try:
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(str(valor))
    except Exception as e:
        logger.error(f"Erro ao salvar config {nome}: {e}")


# ════════════════════════════════════════════════════════════════════════════
# TROCA DE IP DO 4G — MODELO ÚNICO (só quando 4G ATIVADO e a Meta bate rate-limit)
# ────────────────────────────────────────────────────────────────────────────
# Regra (pedido do usuário 2026-07-18): existe UM só modelo de troca de IP.
#   • 4G DESATIVADO  -> o sistema NÃO troca IP (o usuário troca manualmente).
#   • 4G ATIVADO     -> a troca acontece SOMENTE quando a Meta mostra o rate-limit
#     de SMS ("você já solicitou muitos códigos, aguarde"). O limite é POR IP: 1
#     perfil que bate o limite "marca" o IP p/ todos. O coordenador (ip_rotation_
#     coordinator) PAUSA todas as abas em ponto seguro, espera ficarem estáticas e
#     só então chama trocar_ip_4g_adb() UMA vez; depois libera todas.
# A troca é OBRIGATÓRIA (não opcional) quando o 4G está ativo. O modo avião via
# broadcast é IGNORADO por muitos Androids modernos (só apps de sistema podem enviar
# android.intent.action.AIRPLANE_MODE) — nesses aparelhos o IP não mudava e o lote
# ficava preso no mesmo erro. Agora usamos VÁRIAS estratégias em ESCALADA e
# VERIFICAMOS o IP público a cada tentativa; só concluímos quando ele REALMENTE mudou
# e não é um IP queimado (usado nas últimas horas). Estratégias (dados móveis; NUNCA
# wi-fi): 1) 'cmd connectivity airplane-mode' + toggle de dados (Android 10+, sem root);
# 2) 'svc data' puro (reestabelece o PDP/IP na maioria); 3) settings+broadcast (legado);
# 4) via 'su' se houver root (broadcast realmente aplicado). Os IPs usados ficam num
# .json/.txt (CONFIG_DIR) congelados por _IP_CONGELAMENTO_HORAS.
# ════════════════════════════════════════════════════════════════════════════

# Janela em que um IP já usado é considerado "queimado" e deve ser evitado. É o PADRÃO;
# no início de cada run o `_processar_perfis` sobrescreve com a escolha do usuário
# (config 'ip_janela_horas': 1/3/6/12/24h — seletor na GUI). O log de IPs usados
# (ips_4g_usados.json em CONFIG_DIR) é PERSISTENTE: sobrevive a fechar/reabrir o bot, então
# um IP usado há menos que a janela continua congelado mesmo após reiniciar.
_IP_CONGELAMENTO_HORAS = 6.0
# Circuit-breaker: nº de trocas de IP que FALHARAM em sequência. Após N seguidas, o
# terminal avisa FORTE que o 4G não está entregando IP (cabo/ADB/VPN sobrepondo) — evita
# o operador achar que "está trocando" quando não está. (auditoria 24/7, 2026-08-30)
_IP_FALHAS_SEGUIDAS = 0
# Duração (aleatória) com o RÁDIO derrubado antes de reativar. Curto demais faz a
# operadora devolver o MESMO IP — 25-45s (crescendo a cada volta) força IP novo.
_IP_AVIAO_ON = (25, 45)
# Espera-base p/ a rede 4G reconectar e propagar o IP novo (com poll de verificação).
_IP_RECONEXAO = (30, 55)
# Máximo de tentativas (escalando entre estratégias) numa única troca.
_IP_MAX_TENTATIVAS = 8


def _arquivo_ips_usados():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except Exception:
        pass
    return os.path.join(CONFIG_DIR, 'ips_4g_usados.json')


def _carregar_ips_usados():
    """Lê a lista de IPs já usados: [{'ip':..., 'ts':epoch, 'quando':iso}, ...]."""
    try:
        with open(_arquivo_ips_usados(), 'r', encoding='utf-8') as f:
            dados = json.load(f)
            return dados if isinstance(dados, list) else []
    except Exception:
        return []


def _salvar_ips_usados(lista):
    """Persiste a lista (JSON = fonte da verdade) + espelha um .txt legível p/ conferência."""
    try:
        with open(_arquivo_ips_usados(), 'w', encoding='utf-8') as f:
            json.dump(lista, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("[4G] Falha ao salvar ips_4g_usados.json: %s", e)
    try:
        txt = os.path.join(CONFIG_DIR, 'ips_4g_usados.txt')
        with open(txt, 'w', encoding='utf-8') as f:
            f.write("# IPs 4G usados (queimados por %.0fh). Gerado pelo GS BM Creator.\n"
                    % _IP_CONGELAMENTO_HORAS)
            for it in lista:
                f.write("%s\t%s\n" % (it.get('quando', ''), it.get('ip', '')))
    except Exception:
        pass


def _registrar_ip_usado(ip):
    """Marca um IP como usado AGORA (queimado). Poda entradas fora da janela."""
    ip = (ip or '').strip()
    if not ip:
        return
    agora = time.time()
    limite = agora - _IP_CONGELAMENTO_HORAS * 3600.0
    lista = [it for it in _carregar_ips_usados()
             if float(it.get('ts', 0)) >= limite and it.get('ip') != ip]
    try:
        quando = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(agora))
    except Exception:
        quando = str(int(agora))
    lista.append({'ip': ip, 'ts': agora, 'quando': quando})
    _salvar_ips_usados(lista)


def _ip_esta_queimado(ip):
    """True se o IP foi usado dentro da janela de congelamento (últimas Xh)."""
    ip = (ip or '').strip()
    if not ip:
        return False
    limite = time.time() - _IP_CONGELAMENTO_HORAS * 3600.0
    for it in _carregar_ips_usados():
        if it.get('ip') == ip and float(it.get('ts', 0)) >= limite:
            return True
    return False


def _ip_publico_atual(timeout=8):
    """IP público de SAÍDA atual (com 4G ancorado = o IP do 4G). '' se não descobrir."""
    import urllib.request as _url
    for endpoint in ('https://api.ipify.org', 'https://icanhazip.com',
                     'https://ifconfig.me/ip', 'https://ipv4.icanhazip.com'):
        try:
            req = _url.Request(endpoint, headers={'User-Agent': 'curl/8.0'})
            with _url.urlopen(req, timeout=timeout) as resp:
                ip = resp.read().decode('utf-8', 'ignore').strip()
                # valida grosseiramente um IPv4
                partes = ip.split('.')
                if len(partes) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in partes):
                    return ip
        except Exception:
            continue
    return ''


def _adb_shell(args, timeout=25):
    """Roda 'adb shell <args>'. Retorna CompletedProcess ou None (adb ausente/erro)."""
    try:
        return subprocess.run(["adb", "shell"] + list(args),
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        logger.error("[4G] 'adb' não encontrado no PATH — instale o platform-tools/ADB.")
        return None
    except Exception as e:
        logger.debug("[4G] adb shell %s: %s", ' '.join(args), e)
        return None


def _adb_dispositivo_ok():
    """True se há um dispositivo ADB no estado 'device' (celular conectado/autorizado)."""
    try:
        r = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=15)
        if not r or r.returncode != 0:
            return False
        for linha in r.stdout.splitlines()[1:]:
            partes = linha.split()
            if len(partes) >= 2 and partes[1] == 'device':
                return True
        return False
    except FileNotFoundError:
        logger.error("[4G] 'adb' não encontrado no PATH — instale o platform-tools/ADB.")
        return False
    except Exception:
        return False


def _adb_tem_root():
    """True se o 'su' está disponível (root) — permite aplicar o broadcast de verdade."""
    r = _adb_shell(["su", "-c", "id"], timeout=8)
    return bool(r and r.returncode == 0 and 'uid=0' in (r.stdout or ''))


def _estrategias_troca_ip():
    """Lista de estratégias (nome, cmds_derrubar, cmds_reativar) em ordem de ESCALADA.
    Cada cmd é uma lista de args p/ 'adb shell'. Nenhuma mexe no wi-fi."""
    estr = [
        # 1) Android 10+: 'cmd connectivity airplane-mode' REALMENTE derruba o rádio
        #    (sem root, sem depender do broadcast). Junto com o toggle de dados, força
        #    a reconexão do PDP e um IP novo. É o método mais confiável hoje.
        ('cmd-airplane+data',
         [["cmd", "connectivity", "airplane-mode", "enable"], ["svc", "data", "disable"]],
         [["cmd", "connectivity", "airplane-mode", "disable"], ["svc", "data", "enable"]]),
        # 2) Toggle de DADOS puro: reestabelece o contexto de dados (novo IP) na maioria
        #    dos aparelhos, mesmo quando o modo avião não é aceito via ADB.
        ('svc-data',
         [["svc", "data", "disable"]],
         [["svc", "data", "enable"]]),
        # 3) Legado (Android antigo): settings + broadcast do modo avião.
        ('settings+broadcast',
         [["settings", "put", "global", "airplane_mode_on", "1"],
          ["am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "true"]],
         [["settings", "put", "global", "airplane_mode_on", "0"],
          ["am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "false"],
          ["svc", "data", "enable"]]),
    ]
    # 4) Com ROOT o broadcast é aplicado de verdade (aparelhos que ignoram o comum).
    if _adb_tem_root():
        estr.insert(0, ('su-airplane',
            [["su", "-c", "settings put global airplane_mode_on 1"],
             ["su", "-c", "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true"],
             ["su", "-c", "svc data disable"]],
            [["su", "-c", "settings put global airplane_mode_on 0"],
             ["su", "-c", "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false"],
             ["su", "-c", "svc data enable"]]))
    return estr


def _aguardar_reconexao_ip(timeout_total=70):
    """Faz poll do IP público até a rede 4G voltar (ou timeout). Retorna o IP ou ''."""
    fim = time.time() + timeout_total
    ip = ''
    while time.time() < fim:
        ip = _ip_publico_atual(timeout=6)
        if ip:
            return ip
        time.sleep(4)
    return ip


def _aplicar_estrategia(nome, derrubar, reativar, on):
    """Executa UMA estratégia: derruba o rádio, segura 'on's, reativa e garante dados."""
    logger.info("[4G] Estratégia '%s': derrubando o rádio por %ss (dados móveis; wi-fi intocado)...", nome, on)
    for cmd in derrubar:
        _adb_shell(cmd)
    time.sleep(on)
    for cmd in reativar:
        _adb_shell(cmd)
    # Rede de segurança: dados móveis SEMPRE ligados ao final (nunca wi-fi).
    _adb_shell(["svc", "data", "enable"])


def _emitir_ip_evento(msg):
    """Empurra uma linha de EVENTO DE IP para o terminal da GUI (canal GLOBAL, não por-worker)
    e para o log/console. Usada nas trocas de IP para o operador VER, ao vivo, o IP atual e o
    IP novo a cada troca (pedido do dono 2026-08-30). `obter_progresso` devolve `_estado['ip_eventos']`."""
    try:
        lst = _estado.setdefault('ip_eventos', [])
        lst.append({'ts': time.strftime('%H:%M:%S'), 'msg': str(msg)})
        if len(lst) > 40:
            del lst[:len(lst) - 40]
    except Exception:
        pass
    try:
        _atualizar_status_geral(msg)
    except Exception:
        pass


def trocar_ip_4g_adb():
    """Troca o IP do 4G/5G via ADB de forma ROBUSTA, VERIFICADA e OBRIGATÓRIA.

    A troca NÃO é opcional com o 4G ativo. Como alguns Androids ignoram o broadcast do
    modo avião, tentamos VÁRIAS estratégias em ESCALADA e VERIFICAMOS o IP público a
    cada tentativa: só retornamos True quando o IP REALMENTE mudou e não é um queimado.
    Se um método não muda o IP, escalamos p/ o próximo (com espera crescente).
    Retorna True só com a troca CONFIRMADA; False se não conseguiu (aí o coordenador
    NÃO liga o cooldown e a próxima aba com rate-limit tenta trocar de novo)."""
    import random as _rnd
    try:
        if not _adb_dispositivo_ok():
            logger.error("[4G] Nenhum celular ADB no estado 'device'. Reconecte o cabo USB e "
                         "autorize a depuração USB — sem isso o IP não pode ser trocado.")
            return False

        estrategias = _estrategias_troca_ip()
        logger.info("[4G] Troca OBRIGATÓRIA de IP — %d estratégia(s) disponível(is): %s",
                    len(estrategias), ', '.join(n for n, _, _ in estrategias))

        ip_antigo = _ip_publico_atual()
        if ip_antigo:
            logger.info("[4G] IP atual (queimado pela Meta): %s — trocando...", ip_antigo)
            _registrar_ip_usado(ip_antigo)
            _emitir_ip_evento(f"🌐 Trocando IP 4G — atual: {ip_antigo}")
        else:
            logger.warning("[4G] Não li o IP atual agora — seguirei trocando e verificando.")
            _emitir_ip_evento("🌐 Trocando IP 4G — (não consegui ler o IP atual)")

        for tentativa in range(1, _IP_MAX_TENTATIVAS + 1):
            nome, derrubar, reativar = estrategias[(tentativa - 1) % len(estrategias)]
            # A duração de rádio-desligado CRESCE a cada volta completa nas estratégias
            # (aparelho/operadora "teimoso" precisa de mais tempo p/ soltar o IP).
            on = _rnd.randint(*_IP_AVIAO_ON) + 10 * ((tentativa - 1) // len(estrategias))
            _aplicar_estrategia(nome, derrubar, reativar, on)
            espera = _rnd.randint(*_IP_RECONEXAO)
            logger.info("[4G] Rádio de volta — aguardando reconexão/propagação (até ~%ss)...", espera + 20)
            ip_novo = _aguardar_reconexao_ip(espera + 20)

            if not ip_novo:
                logger.warning("[4G] Sem internet 4G após '%s' (%s/%s) — escalando p/ outra estratégia.",
                               nome, tentativa, _IP_MAX_TENTATIVAS)
                continue
            if ip_antigo and ip_novo == ip_antigo:
                logger.warning("[4G] IP NÃO mudou (%s) com '%s' — escalando (%s/%s).",
                               ip_novo, nome, tentativa, _IP_MAX_TENTATIVAS)
                continue
            if _ip_esta_queimado(ip_novo):
                logger.warning("[4G] IP novo %s já usado nas últimas %.0fh (queimado) — trocando de novo (%s/%s).",
                               ip_novo, _IP_CONGELAMENTO_HORAS, tentativa, _IP_MAX_TENTATIVAS)
                _registrar_ip_usado(ip_novo)
                _emitir_ip_evento(f"↻ IP {ip_novo} congelado (usado < {_IP_CONGELAMENTO_HORAS:.0f}h) — buscando um limpo...")
                continue
            # Sucesso CONFIRMADO: IP diferente, legível e limpo.
            _registrar_ip_usado(ip_novo)
            logger.info("[4G] ✅ IP trocado e VERIFICADO: %s -> %s (estratégia '%s'). Liberando abas.",
                        ip_antigo or '?', ip_novo, nome)
            _emitir_ip_evento(f"✅ IP trocado: {ip_antigo or '?'} → {ip_novo}")
            globals()['_IP_FALHAS_SEGUIDAS'] = 0
            return True

        logger.error("[4G] ❌ NÃO consegui trocar o IP após %s tentativas em todas as estratégias. "
                     "O rádio deste aparelho pode não estar respondendo ao ADB — verifique o celular "
                     "(depuração USB, permissão de comandos). SEM cooldown: a próxima aba tentará de novo.",
                     _IP_MAX_TENTATIVAS)
        _emitir_ip_evento(f"⚠️ IP NÃO mudou (ainda {ip_antigo or '?'}) após {_IP_MAX_TENTATIVAS} tentativas — "
                          f"confira o 4G/ADB e se a SAÍDA é mesmo o 4G (VPN/Ethernet podem estar sobrepondo).")
        globals()['_IP_FALHAS_SEGUIDAS'] = int(globals().get('_IP_FALHAS_SEGUIDAS', 0)) + 1
        if globals()['_IP_FALHAS_SEGUIDAS'] >= 3:
            _emitir_ip_evento(f"🛑 A troca de IP FALHOU {globals()['_IP_FALHAS_SEGUIDAS']}x seguidas — o 4G NÃO "
                              f"está entregando IP novo. Verifique: cabo USB/depuração ADB, e DESLIGUE VPN "
                              f"(Surfshark)/garanta que a rota de saída é o 4G. Sem isso, o rate-limit vai persistir.")
        return False
    except Exception as e:
        logger.error("[4G] Erro ao trocar IP via ADB: %s", e)
        return False


# ============================================================================
# ABSTRAÇÃO DE BROWSER ENGINE
# ============================================================================

def _get_browser_module():
    """Retorna o módulo correto baseado no engine selecionado."""
    engine = _estado.get('browser_engine', 'ixbrowser')
    if engine == 'adspower':
        return adspower_api
    return ixbrowser_api


def verificar_browser():
    """Verifica se o browser engine selecionado está conectado."""
    try:
        mod = _get_browser_module()
        return mod.verificar_conexao()
    except Exception as e:
        return {"conectado": False, "mensagem": f"Erro: {str(e)}"}


# ============================================================================
# FUNÇÕES EXPOSTAS AO JAVASCRIPT
# ============================================================================

def carregar_configuracoes(usuario=''):
    """Carrega configurações salvas."""
    user = usuario or _estado['usuario_logado'] or _ler_config('ultimo_usuario_software', '')
    if not user:
        user = _ler_config('usuario', '')

    senha_salva = ''
    if user == _ler_config('usuario', ''):
        senha_salva = _ler_config('senha', '', '')

    painel_conectado = bool(_TEM_ACESSO and esta_autenticado())

    # Nível de acesso do usuário (role) + se pode usar os planos Gupshup (Lite/Pro).
    _sessao = obter_dados_sessao() if _TEM_ACESSO else {}
    _role = str(_sessao.get('role') or 'user').strip().lower()
    _pode_gupshup = bool(_TEM_ACESSO and usuario_pode_planos_gupshup())

    return {
        'role': _role,
        'pode_planos_gupshup': _pode_gupshup,
        'nome_grupo': _ler_config('nome_grupo', 'Facebook Profiles', user),
        'proxy': _ler_config('proxy', 'nao', user),
        'utilizar_4g': _ler_config('utilizar_4g', 'nao', user),
        'ip_janela_horas': _ler_config('ip_janela_horas', '6', user),
        'ip_max_por_ip': _ler_config('ip_max_por_ip', '10', user),
        'lista_proxy': _ler_config('lista_proxy', '', user),
        'proxy_tipo': _ler_config('proxy_tipo', 'http', user),
        'usuario': user,
        'senha': senha_salva,
        'lembrar_acesso': _ler_config('lembrar_acesso', 'sim', ''),
        'qtd_bm': _ler_config('qtd_bm', '1', user),
        'browser_engine': _ler_config('browser_engine', 'ixbrowser', user),
        'adspower_token': _ler_config('adspower_token', '', user),
        'adspower_url': _ler_config('adspower_url', 'http://local.adspower.net:50325', user),
        'captcha_token': _ler_config('captcha_token', '', user),
        'sms24h_token': _ler_config('sms24h_token', '', user),
        # Provedor de SMS escolhido: 'sms24h' | 'grizzly' | 'tiger'. O padrão mantém
        # o comportamento de quem já usava só o sms24h.
        'sms_provedor': _ler_config('sms_provedor', 'sms24h', user),
        # tokens de reserva do fallback A→B→C
        'sms_token_sms24h': _ler_config('sms_token_sms24h', '', user),
        'sms_token_grizzly': _ler_config('sms_token_grizzly', '', user),
        'sms_token_tiger': _ler_config('sms_token_tiger', '', user),
        'sms_token_vak': _ler_config('sms_token_vak', '', user),
        'sms_token_smsbower': _ler_config('sms_token_smsbower', '', user),
        'sms_preco_max': _ler_config('sms_preco_max', '0.12', user),
        'painel_conectado': painel_conectado,
        'verificar_bm': _ler_config('verificar_bm', 'nao', user),
        'tipo_empresa': _ler_config('tipo_empresa', 'mei', user),
        'auto_verificar': _ler_config('auto_verificar', 'nao', user),
        'datacrazy_email': _ler_config('datacrazy_email', '', user),
        'datacrazy_senha': _ler_config('datacrazy_senha', '', user),
        # Recurso da WABA desabilitada: 'sim' = envia com texto de contestação (padrão);
        # 'nao' = envia o formulário EM BRANCO (sem preencher nada).
        'recurso_com_texto': _ler_config('recurso_com_texto', 'sim', user),
    }


def salvar_config_troca_ip(modo='', navegadores='', minutos=''):
    """[DESATIVADO 2026-07-18] Os modos de rotação programada de IP ('lote',
    'navegadores', 'minutos') foram REMOVIDOS. Existe agora UM modelo único: com o 4G
    ATIVADO a troca ocorre SOMENTE no rate-limit de SMS da Meta (via coordenador); com
    o 4G desligado o sistema não troca IP. Mantido como no-op só p/ compatibilidade com
    front-ends antigos que ainda chamem esta API — não persiste mais nada."""
    return {'sucesso': True, 'modo': 'rate_limit', 'obsoleto': True}


def salvar_configuracoes(nome_grupo, proxy, utilizar_4g, lista_proxy, proxy_tipo,
                          usuario='', senha='', lembrar_acesso='sim', qtd_bm='1',
                          browser_engine='ixbrowser', adspower_token='', captcha_token='',
                          adspower_url='', verificar_bm='nao', tipo_empresa='mei',
                          auto_verificar='nao', datacrazy_email='', datacrazy_senha='',
                          sms24h_token='', sms_provedor='sms24h',
                          sms_token_sms24h='', sms_token_grizzly='', sms_token_tiger='',
                          sms_token_vak='', sms_preco_max='', sms_token_smsbower='',
                          ip_janela_horas='6', ip_max_por_ip='10'):
    """Salva configurações vinculadas ao usuário logado.

    Os `sms_token_*` são os tokens de RESERVA do fallback A→B→C (um por provedor).
    `ip_janela_horas` (1/3/6/12/24) = tempo que um IP fica congelado (não reusado);
    `ip_max_por_ip` = máx. de perfis por IP antes de trocar (modelo Cota por IP).
    """
    user = _estado['usuario_logado'] or usuario or _ler_config('ultimo_usuario_software', '')

    if user:
        _salvar_config('nome_grupo', nome_grupo, user)
        _salvar_config('proxy', proxy, user)
        _salvar_config('utilizar_4g', utilizar_4g, user)
        _salvar_config('ip_janela_horas', str(ip_janela_horas or '6'), user)
        _salvar_config('ip_max_por_ip', str(ip_max_por_ip or '10'), user)
        _salvar_config('lista_proxy', lista_proxy, user)
        _salvar_config('proxy_tipo', proxy_tipo, user)
        _salvar_config('qtd_bm', qtd_bm, user)
        _salvar_config('browser_engine', browser_engine, user)
        _salvar_config('adspower_token', adspower_token, user)
        _salvar_config('captcha_token', captcha_token, user)
        _salvar_config('sms24h_token', sms24h_token or '', user)
        _prov_sel = (sms_provedor or 'sms24h').strip().lower()
        _salvar_config('sms_provedor', _prov_sel, user)

        # ── tokens de RESERVA (fallback A→B→C) — um por provedor ───────────────
        # ⚠️ CAMPO VAZIO **NÃO APAGA** o token já salvo. Motivo real (2026-08-04):
        # a tela salvou com os campos de reserva em branco e zerou os tokens do
        # Tiger/Vak; o run seguinte ficou com UM provedor só na fila e, quando o
        # SMS não chegou, não tinha para onde trocar — exatamente o problema que
        # o fallback existe para resolver. Para REMOVER um token, mande '-'.
        _reservas = {'sms24h': sms_token_sms24h, 'grizzly': sms_token_grizzly,
                     'tiger': sms_token_tiger, 'vak': sms_token_vak,
                     'smsbower': sms_token_smsbower}
        for _p, _v in _reservas.items():
            _v = str(_v or '').strip()
            if _v == '-':
                _salvar_config(f'sms_token_{_p}', '', user)
            elif _v:
                _salvar_config(f'sms_token_{_p}', _v, user)
            # vazio → preserva o que já estava gravado

        # Espelha o token do campo principal no slot do provedor selecionado —
        # mas SÓ depois de CONFIRMAR na API que ele é mesmo daquele provedor.
        # ⚠️ Trocar o provedor na tela NÃO troca o campo principal: sem esta
        # validação, selecionar 'tiger' com a chave do Vak ainda no campo grava
        # a chave do Vak como se fosse do Tiger — e o provedor entra na fila
        # condenado a BAD_KEY. (aconteceu de verdade em 2026-08-04)
        _tok_princ = str(sms24h_token or '').strip()
        if _tok_princ and _ler_config(f'sms_token_{_prov_sel}', '', user) != _tok_princ:
            try:
                from server.sms24h_client import criar_cliente as _cc
                if _cc(_tok_princ, _prov_sel).token_valido() is False:
                    logger.warning('[SMS] Token do campo principal NÃO é do %s '
                                   '(a API recusou a chave) — não espelhei.', _prov_sel)
                else:
                    _salvar_config(f'sms_token_{_prov_sel}', _tok_princ, user)
            except Exception as _e:
                logger.debug('[SMS] validação do token principal falhou: %s', _e)
        _salvar_config('sms_preco_max', str(sms_preco_max or ''), user)
        if adspower_url:
            _salvar_config('adspower_url', adspower_url, user)
        _salvar_config('verificar_bm', verificar_bm or 'nao', user)
        _salvar_config('tipo_empresa', tipo_empresa or 'mei', user)
        _salvar_config('auto_verificar', auto_verificar or 'nao', user)
        # Credenciais do CRM DataCrazy (usadas só no fluxo 'full_datacrazy').
        _salvar_config('datacrazy_email', datacrazy_email or '', user)
        _salvar_config('datacrazy_senha', datacrazy_senha or '', user)
        _salvar_config('ultimo_usuario_software', user, '')
        # Disponibiliza no estado para o processamento (etapa extra DataCrazy).
        _estado['datacrazy_email'] = datacrazy_email or ''
        _estado['datacrazy_senha'] = datacrazy_senha or ''
        # Token do provedor de SMS (Pro Max): compra do número com saldo do usuário.
        _estado['sms24h_token'] = sms24h_token or ''
        _estado['sms_provedor'] = sms_provedor or 'sms24h'

    # Atualizar engine ativo
    _estado['browser_engine'] = browser_engine
    if browser_engine == 'adspower':
        if adspower_token:
            adspower_api.configurar_api_key(adspower_token)
        if adspower_url:
            adspower_api.configurar_url(adspower_url)

    # Dados de login
    _salvar_config('lembrar_acesso', lembrar_acesso, '')
    if lembrar_acesso == 'sim':
        if usuario: _salvar_config('usuario', usuario, '')
        if senha: _salvar_config('senha', senha, '')
    else:
        _salvar_config('usuario', '', '')
        _salvar_config('senha', '', '')

    return True


def testar_tokens_sms(tokens=None):
    """Consulta o saldo de cada API KEY do modal 'Provedores de SMS'.

    Existe para separar ANTES do run três coisas que em campo viram o MESMO
    sintoma ("o SMS não chegou"): chave errada (BAD_KEY), conta sem saldo e
    provedor fora do ar. Sem isto, só se descobria no meio da rodada — com o
    perfil já aberto e a BM já criada.

    Recebe {provedor: token} e devolve, por provedor, `ok` + um texto curto
    para a GUI pintar de verde/vermelho ao lado do campo.
    """
    try:
        from server.sms24h_client import (criar_cliente, nome_do_provedor,
                                          moeda_do_provedor, PROVEDORES)
    except Exception as e:                                  # pragma: no cover
        logger.warning('[SMS] cliente indisponível para o teste: %s', e)
        return {'sucesso': False, 'mensagem': 'Módulo de SMS indisponível.',
                'resultados': {}}

    tokens = {str(k).strip().lower(): str(v or '').strip()
              for k, v in dict(tokens or {}).items()
              if str(v or '').strip() and str(k).strip().lower() in PROVEDORES}
    if not tokens:
        return {'sucesso': False, 'mensagem': 'Nenhuma API KEY informada.',
                'resultados': {}}

    resultados, prontos = {}, []
    for prov, tok in tokens.items():
        nome = nome_do_provedor(prov)
        moeda = moeda_do_provedor(prov)
        try:
            cli = criar_cliente(tok, prov)
            saldo = cli.saldo()
            if saldo is None:
                # None do saldo é ambíguo: pode ser chave ruim OU rede fora.
                # `token_valido()` distingue (False = a API recusou a chave).
                valido = cli.token_valido()
                texto = 'chave inválida' if valido is False else 'sem resposta da API'
                resultados[prov] = {'ok': False, 'texto': texto}
            else:
                tem_saldo = saldo > 0
                resultados[prov] = {
                    'ok': tem_saldo,
                    'saldo': saldo,
                    'texto': f'{moeda} {saldo:.2f}' + ('' if tem_saldo else ' — sem saldo'),
                }
                if tem_saldo:
                    prontos.append(nome)
            logger.info('[SMS] teste %s: %s', nome, resultados[prov]['texto'])
        except Exception as e:
            logger.warning('[SMS] teste do token do %s falhou: %s', nome, e)
            resultados[prov] = {'ok': False, 'texto': 'erro ao consultar'}

    mensagem = (f"{len(prontos)} provedor(es) com saldo: {', '.join(prontos)}."
                if prontos else 'Nenhum provedor com saldo utilizável.')
    return {'sucesso': bool(prontos), 'mensagem': mensagem, 'resultados': resultados}


def autenticar_usuario(usuario, senha, lembrar_acesso='sim'):
    """Valida o usuário diretamente no banco do painel."""
    logger.info("Tentativa de login para o usuário '%s'", usuario)

    try:
        resultado = validar_usuario(usuario, senha)
        logger.info("Resultado bruto da validação para '%s': %r", usuario, resultado)

        if resultado is True:
            _estado['usuario_logado'] = usuario
            _salvar_config('ultimo_usuario_software', usuario, '')
            _salvar_config('lembrar_acesso', lembrar_acesso, '')

            if lembrar_acesso == 'sim':
                _salvar_config('usuario', usuario, '')
                _salvar_config('senha', senha, '')
            else:
                _salvar_config('usuario', '', '')
                _salvar_config('senha', '', '')

            configs = carregar_configuracoes(usuario)

            # Dados da sessão atual
            sessao = obter_dados_sessao() if _TEM_ACESSO else {}
            configs['painel_conectado'] = sessao.get('autenticado', True)
            configs['tier'] = sessao.get('tier', 'bronze')

            # Aplicar engine salvo
            engine = configs.get('browser_engine', 'ixbrowser')
            _estado['browser_engine'] = engine
            if engine == 'adspower':
                if configs.get('adspower_token'):
                    adspower_api.configurar_api_key(configs['adspower_token'])
                if configs.get('adspower_url'):
                    adspower_api.configurar_url(configs['adspower_url'])

            logger.info("Login concluído com sucesso para '%s'", usuario)
            return {"sucesso": True, "configs": configs}

        mensagem = str(resultado or 'Falha na autenticação')
        logger.warning("Login negado para '%s': %s", usuario, mensagem)
        return {"sucesso": False, "mensagem": mensagem}

    except Exception as e:
        logger.exception("Falha inesperada no login do usuário '%s': %s", usuario, e)
        return {"sucesso": False, "mensagem": f"Erro de conexão: {str(e)}"}


def _carregar_perfis_no_estado(perfis_list, compra_ids=None, origem='granasocial'):
    """Carrega a lista parseada de perfis no `_estado` global + monta a
    representacao publica para a UI. Reutilizado por importar_perfis (txt
    assinado) e por importar_perfis_comprados (API/DB)."""
    total = len(perfis_list)
    _estado['perfis'] = perfis_list
    _estado['total'] = total
    _estado['concluidos'] = 0
    _estado['erros'] = 0
    _estado['recorridas'] = 0
    _estado['progresso'] = []
    _estado['compra_ids_origem'] = sorted({int(c) for c in (compra_ids or []) if c})

    for i, p in enumerate(perfis_list):
        p['numero'] = str(i + 1).zfill(2)
        p.setdefault('origem', origem)
        _estado['progresso'].append({
            'indice': i, 'numero': p['numero'], 'login': p.get('login', ''),
            'status': 'Aguardando', 'cor': '#888888', 'mensagem': '',
            'compra_id': p.get('compra_id', 0),
            'coin_debitado': False,
            # AdsPower/ixBrowser user_id do navegador criado p/ este perfil. Fica
            # vazio até a abertura; usado pelos EXPORTS de falhas (marcador REABRIR
            # p/ reimportar e reabrir o MESMO navegador já logado, sem criar novo).
            'profile_id': '',
        })

    resultado = []
    for p in perfis_list:
        senha = p.get('senha') or ''
        resultado.append({
            'numero': p['numero'],
            'login': p.get('login', ''),
            'senha': (senha[:4] + '****') if len(senha) > 4 else senha,
            'email': p.get('email', ''),
            'senha_email': 'Sim' if p.get('senha_email') else '-',
            'tfa': 'Sim' if p.get('tfa') else '-',
            'cookie': 'Sim' if p.get('cookie_raw') else '-',
            'token': 'Sim' if p.get('token') else '-',
            'status': 'Aguardando',
            'origem': p.get('origem', origem),
        })
    return resultado


def importar_perfis(conteudo_txt):
    """Importa perfis a partir de um .txt.

    - SOMENTE ADMIN (o dono): pode importar um .txt PRÓPRIO (bruto, sem passar pelo
      painel GranaSocial) — parseia direto o formato
      uid|senha|2fa|email|email_senha|email_recuperacao.
    - EDITOR e Usuário COMUM: OBRIGADOS a usar .txt do GranaSocial (perfis COMPRADOS;
      validação em duas camadas: assinatura HMAC GS-SIG + lookup online dos compra_ids).
      Editor NÃO é mais isento (2026-10-08): não pode usar perfis de terceiros.
    """
    try:
        if not esta_autenticado():
            return {"sucesso": False, "perfis": [], "total": 0,
                    "erro": "Faca login antes de importar perfis."}

        _sessao_imp = obter_dados_sessao() or {}
        user_id = _sessao_imp.get('user_id')
        if not user_id:
            return {"sucesso": False, "perfis": [], "total": 0,
                    "erro": "Sessao sem identificador de usuario."}

        # ── SOMENTE ADMIN (o DONO): importa .txt PRÓPRIO (sem obrigatoriedade de
        # compra). EDITOR e USUÁRIO COMUM só podem usar perfis COMPRADOS do
        # GranaSocial — NÃO perfis de terceiros (pedido do dono, 2026-10-08:
        # "editor e o usuário comum só pode usar perfis comprados do grana social").
        # ⚠️ O gate ANTIGO usava usuario_pode_planos_gupshup(), que hoje retorna True
        # p/ QUALQUER autenticado (mudança 2026-09-09) → liberava .txt de terceiros
        # para TODOS, furando a limitação. Agora é usuario_eh_admin() (role == 'admin').
        try:
            _pode_txt_proprio = bool(_TEM_ACESSO and usuario_eh_admin())
        except Exception:
            _pode_txt_proprio = False
        if _pode_txt_proprio:
            try:
                from server.parser_perfis import parsear_conteudo_txt
                perfis_raw = parsear_conteudo_txt(conteudo_txt or '') or []
            except Exception as exc:
                logger.exception('[Backend] importar_perfis (admin) parse: %s', exc)
                return {"sucesso": False, "perfis": [], "total": 0,
                        "erro": f"Erro ao ler o .txt: {exc}"}
            if not perfis_raw:
                return {"sucesso": False, "perfis": [], "total": 0,
                        "erro": "Nenhum perfil reconhecido no .txt (formato esperado: "
                                "uid|senha|2fa|email|senha_email|email_recuperacao)."}
            resultado = _carregar_perfis_no_estado(
                perfis_raw, compra_ids=[], origem='txt_proprio')
            return {
                "sucesso": True,
                "perfis": resultado,
                "total": len(resultado),
                "mensagem": f"{len(resultado)} perfis importados (.txt próprio · admin)",
            }

        # Persistir temporariamente o conteudo num arquivo e validar via
        # `gs_txt_validator.validar_arquivo` (mantem uma unica implementacao).
        import tempfile
        try:
            tmpf = tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', delete=False, encoding='utf-8'
            )
            tmpf.write(conteudo_txt or '')
            tmpf.flush()
            tmp_path = tmpf.name
            tmpf.close()
        except Exception as exc:
            return {"sucesso": False, "perfis": [], "total": 0,
                    "erro": f"Falha ao processar arquivo: {exc}"}

        try:
            from server.gs_txt_validator import validar_arquivo
            val = validar_arquivo(tmp_path, int(user_id))
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        if not val.sucesso:
            return {"sucesso": False, "perfis": [], "total": 0,
                    "erro": val.mensagem}

        resultado = _carregar_perfis_no_estado(
            val.perfis, compra_ids=val.compra_ids, origem='granasocial_txt',
        )
        return {
            "sucesso": True,
            "perfis": resultado,
            "total": len(resultado),
            "mensagem": f"{len(resultado)} perfis importados com sucesso",
            "compra_ids": val.compra_ids,
        }
    except Exception as e:
        logger.exception('[Backend] importar_perfis: %s', e)
        return {"sucesso": False, "perfis": [], "total": 0, "erro": str(e)}


def listar_compras_disponiveis_api():
    """Lista as compras do usuario logado que ainda tem perfis disponiveis
    para importar (consumido pela UI de 'Importar perfis comprados')."""
    if not esta_autenticado():
        return {"sucesso": False, "compras": [], "mensagem": "Nao autenticado"}
    user_id = (obter_dados_sessao() or {}).get('user_id')
    if not user_id:
        return {"sucesso": False, "compras": [], "mensagem": "Sessao invalida"}
    try:
        from server.granasocial_db import listar_compras_disponiveis
        compras = listar_compras_disponiveis(int(user_id))
        return {"sucesso": True, "compras": compras, "total": len(compras)}
    except Exception as exc:
        logger.exception('[Backend] listar_compras_disponiveis: %s', exc)
        return {"sucesso": False, "compras": [], "mensagem": str(exc)}


def _parsear_dados_conta_compra(dados_raw):
    """Converte o campo `dados_conta` de uma compra em lista de perfis.

    A loja GranaSocial grava `dados_conta` como Base64 de um JSON:
        [{"uid","senha","cookies","token","email","2fa","extra"}, ...]
    Esta funcao decodifica esse formato e mapeia para o dict de perfil que o
    resto do Creator espera (mesmas chaves de parser_perfis._criar_perfil_vazio).
    Faz fallback para o parser de .TXT quando o conteudo nao for o JSON da loja
    (compatibilidade com formatos antigos).
    """
    import base64
    from server.parser_perfis import (
        converter_cookie_string_para_json, _criar_perfil_vazio,
    )

    if not dados_raw or not str(dados_raw).strip():
        return []
    texto = str(dados_raw).strip()

    # 1) Tentar como JSON direto; senao, decodificar Base64 e tentar de novo.
    arr = None
    for tentativa in (texto, None):
        candidato = tentativa
        if candidato is None:
            try:
                candidato = base64.b64decode(texto).decode('utf-8')
            except Exception:
                break
        try:
            obj = json.loads(candidato)
            arr = obj if isinstance(obj, list) else [obj]
            break
        except Exception:
            arr = None

    # 2) Nao e o JSON da loja -> usar o parser de .TXT (formato antigo).
    if arr is None:
        return parsear_conteudo_txt(texto) or []

    # 3) Mapear cada objeto da loja para o dict de perfil do Creator.
    perfis = []
    for i, item in enumerate(arr):
        if not isinstance(item, dict):
            continue
        p = _criar_perfil_vazio()
        p['login'] = str(item.get('uid') or item.get('login') or '').strip()
        p['senha'] = str(item.get('senha') or item.get('password') or '').strip()
        p['email'] = str(item.get('email') or '').strip()
        p['senha_email'] = str(item.get('senha_email')
                               or item.get('email_senha') or '').strip()
        p['tfa'] = str(item.get('2fa') or item.get('tfa') or '').strip()
        p['token'] = str(item.get('token') or '').strip()
        p['info_extra'] = str(item.get('extra') or item.get('info_extra') or '').strip()
        cookies_raw = item.get('cookies') or item.get('cookie') or ''
        if cookies_raw:
            p['cookie_raw'] = str(cookies_raw)
            try:
                p['cookie_json'] = converter_cookie_string_para_json(str(cookies_raw))
            except Exception:
                p['cookie_json'] = ''
        if p['login']:
            p['numero'] = str(len(perfis) + 1).zfill(2)
            perfis.append(p)

    return perfis


def importar_perfis_comprados(selecao):
    """Importa perfis comprados diretamente da DB granasocial.

    `selecao` deve ser uma lista de dicts:
       [{'compra_id': int, 'quantidade': int}, ...]
    A quantidade e limitada ao numero de perfis ainda nao importados da compra.
    """
    if not esta_autenticado():
        return {"sucesso": False, "perfis": [], "total": 0,
                "erro": "Faca login para importar perfis."}
    user_id = (obter_dados_sessao() or {}).get('user_id')
    if not user_id:
        return {"sucesso": False, "perfis": [], "total": 0,
                "erro": "Sessao sem identificador de usuario."}

    if not isinstance(selecao, list) or not selecao:
        return {"sucesso": False, "perfis": [], "total": 0,
                "erro": "Nenhuma compra selecionada."}

    try:
        from server.granasocial_db import (
            obter_perfis_compra, marcar_perfis_importados,
        )

        perfis_acumulados = []
        compra_ids = []
        for item in selecao:
            try:
                cid = int(item.get('compra_id') or 0)
                qtd = int(item.get('quantidade') or 0)
            except Exception:
                continue
            if cid <= 0 or qtd <= 0:
                continue

            res = obter_perfis_compra(int(user_id), cid)
            if not res.get('sucesso'):
                continue
            dados_raw = res.get('dados_conta') or ''
            try:
                perfis_compra = _parsear_dados_conta_compra(dados_raw)
            except Exception as exc:
                logger.warning('[Backend] parser compra %s: %s', cid, exc)
                continue

            # Limitar a quantidade pedida (1..len)
            qtd_efetiva = min(qtd, len(perfis_compra))
            selecionados = perfis_compra[:qtd_efetiva]
            for idx, p in enumerate(selecionados):
                p['compra_id'] = cid
                p['perfil_index'] = idx
                perfis_acumulados.append(p)

            if qtd_efetiva > 0:
                compra_ids.append(cid)
                marcar_perfis_importados(int(user_id), cid, range(qtd_efetiva))

        if not perfis_acumulados:
            return {"sucesso": False, "perfis": [], "total": 0,
                    "erro": "Nenhum perfil disponivel nas compras selecionadas."}

        # PORTÃO DE POSSE: registra os identificadores (login/e-mail) dos perfis
        # COMPRADOS no índice local oculto — assim "Reutilizar Logados"/"Reprocessar"
        # reconhecem o perfil como do GranaSocial mesmo antes de o navegador existir.
        try:
            if _perfis_proprios:
                for _pc in perfis_acumulados:
                    _perfis_proprios.registrar(
                        engine=_estado.get('browser_engine', 'adspower'),
                        login=_pc.get('login', '') or _pc.get('usuario', ''),
                        email=_pc.get('email', ''))
        except Exception:
            pass

        resultado = _carregar_perfis_no_estado(
            perfis_acumulados, compra_ids=compra_ids,
            origem='granasocial_api',
        )
        return {
            "sucesso": True,
            "perfis": resultado,
            "total": len(resultado),
            "mensagem": f"{len(resultado)} perfis importados do GranaSocial",
            "compra_ids": compra_ids,
        }
    except Exception as exc:
        logger.exception('[Backend] importar_perfis_comprados: %s', exc)
        return {"sucesso": False, "perfis": [], "total": 0, "erro": str(exc)}


def consultar_perfis_disponiveis():
    """Retorna o estado da conexão com o painel."""
    try:
        conectado = bool(_TEM_ACESSO and esta_autenticado())
        return {
            "total": 1 if conectado else 0,
            "conectado": conectado,
            "mensagem": "Conectado ao painel" if conectado else "Não autenticado",
        }
    except Exception as e:
        return {"total": 0, "conectado": False, "mensagem": str(e)}


def reembolsar_perfis_pendentes():
    """Mantido por compatibilidade; não há cobrança por coins nesta versão."""
    _estado['perfis_cobrados'].clear()
    return 0


# Registrar reembolso automático ao fechar o app
def _cleanup_atexit():
    # FIX (auditoria 24/7): fecha os navegadores do run ANTES de sair — se o app cai/fecha
    # no meio, os browsers ficavam abertos consumindo RAM/handles até reinício manual.
    try:
        _fechar_navegadores_do_run()
    except Exception:
        pass
    try:
        reembolsar_perfis_pendentes()
    except Exception:
        pass
    try:
        if _TEM_ACESSO:
            logout_usuario()
    except Exception:
        pass

atexit.register(_cleanup_atexit)


def verificar_ixbrowser():
    """Verifica se o browser engine selecionado está conectado."""
    return verificar_browser()


def obter_saldo_coins_painel():
    """Retorna saldos do usuario (granasocial): coins e tokens.

    A UI exibe COINS no header (moeda de USO da ferramenta — cada método consome
    coins). O token do site é cobrado à parte. Mantemos `saldo`/`custo_por_bm`
    por compat retroativa com chamadores antigos.
    """
    try:
        # Atualiza coins/tokens no cache da sessao
        coins = obter_saldo_coins()
        try:
            sessao = obter_dados_sessao() or {}
        except Exception:
            sessao = {}
        tokens = int(sessao.get('tokens') or 0)
        return {
            'sucesso': True,
            'saldo': float(coins or 0),
            'coins': float(coins or 0),
            'tokens': tokens,
            'custo_por_bm': COINS_POR_BM,
        }
    except Exception as e:
        logger.warning('[Saldo] Erro ao obter saldo: %s', e)
        return {'sucesso': False, 'saldo': 0.0, 'coins': 0.0, 'tokens': 0,
                'custo_por_bm': COINS_POR_BM}


def obter_nivel_acesso():
    """Retorna o nível de acesso do usuário logado para a UI:
      - role: 'admin' | 'editor' | 'user' (ou outro)
      - pode_planos_gupshup: True só para admin/editor (libera GPushup Lite/Pro).
    Usuários comuns só enxergam Básico, Padrão e Avançado (DataCrazy)."""
    try:
        _sessao = obter_dados_sessao() if _TEM_ACESSO else {}
        return {
            'sucesso': True,
            'role': str(_sessao.get('role') or 'user').strip().lower(),
            'pode_planos_gupshup': bool(_TEM_ACESSO and usuario_pode_planos_gupshup()),
        }
    except Exception as e:
        logger.warning('[Nível] Erro ao obter nível de acesso: %s', e)
        return {'sucesso': False, 'role': 'user', 'pode_planos_gupshup': False}


def obter_progresso():
    """Retorna o estado atual do processamento."""
    # [FIX 2026-07-19] A GUI troca o botão p/ 'Continuar' com base em 'pausado'. A pausa
    # AUTOMÁTICA (ex.: SMS sem saldo/número na etapa) seta só o flag do módulo `pausa`,
    # não o _estado['pausado'] — então o botão ficava em 'Pausar' e o usuário não via
    # como retomar (parecia "travado"). Reflete QUALQUER pausa (manual OU automática).
    _pausado = bool(_estado.get('pausado', False))
    try:
        from server import pausa as _pausa
        _pausado = _pausado or _pausa.is_pausado()
    except Exception:
        pass
    return {
        'processando': _estado['processando'],
        'pausado': _pausado,
        'progresso': _estado['progresso'],
        'total': _estado['total'],
        'concluidos': _estado['concluidos'],
        'erros': _estado['erros'],
        'recorridas': _estado.get('recorridas', 0),
        'ip_eventos': _estado.get('ip_eventos', [])
    }


def _categoria_falha(item):
    """Classifica um item de `_estado['progresso']` (só erros/avisos) em:
       'login' -> NÃO logou no Facebook (bloqueio / checkpoint / conta travada /
                  precisa código no e-mail Hotmail-Outlook / falha de navegador).
       'fluxo' -> LOGOU mas a BM não foi concluída/enviada p/ análise (incompleto,
                  bloqueada, não verificada, e-mail não confirmado).
       None    -> não é falha exportável (sucesso/aguardando/processando).
    Baseado no status + no texto da mensagem (ver mapa dos prefixos em
    _atualizar_progresso: 'Não foi possível logar no Facebook', 'incompleto',
    'BM não concluída', 'BM bloqueada', etc.)."""
    st = (item.get('status') or '')
    cor = (item.get('cor') or '')
    m = (item.get('mensagem') or '').lower()
    # Só falhas: status 'Erro' OU avisos laranja (#FF8800 = incompleto/e-mail não confirmado)
    if st != 'Erro' and cor.upper() != '#FF8800':
        return None
    # Categoria A: falha de LOGIN no Facebook (não passou da porta)
    login_sinais = (
        'não foi possível logar no facebook', 'nao foi possivel logar no facebook',
        'conta travada', 'checkpoint', 'código por e-mail', 'codigo por e-mail',
        'código no e-mail', 'confirmemail', 'desbloquear', 'possível hack', 'possivel hack',
        'falha ao abrir navegador', 'falha ao conectar', 'código por email', 'codigo por email',
    )
    if any(s in m for s in login_sinais):
        return 'login'
    # Categoria B: erro NO FLUXO da BM (logou, mas não enviou p/ análise)
    fluxo_sinais = (
        'incompleto', 'bm não concluída', 'bm nao concluida', 'bm bloqueada',
        'fluxo não concluído', 'fluxo nao concluido', 'não enviado p/ análise',
        'nao enviado p/ analise', 'email não confirmado', 'email nao confirmado',
        'empresa/site não criada', 'empresa/site nao criada', 'sem verificação',
        'sem verificacao', 'não verificad', 'nao verificad', 'pendente', 'waba não criada',
        'waba nao criada',
    )
    if any(s in m for s in fluxo_sinais):
        return 'fluxo'
    # Qualquer outro erro sem sinal claro: trata como fluxo (logou o suficiente p/ abrir).
    return 'fluxo'


def _linha_export_perfil(perfil, item):
    """Monta o bloco (formato de RÓTULOS, re-importável pelo parser) de um perfil
    p/ o .txt de falhas, com o marcador REABRIR:<profile_id> quando disponível."""
    def g(*chaves):
        for c in chaves:
            v = perfil.get(c)
            if v:
                return str(v)
        return ''
    login = g('login')
    senha = g('senha')
    tfa = g('tfa', 'twofa', '2fa')
    cookies = g('cookie_raw', 'cookies', 'cookie')
    token = g('token')
    email = g('email')
    senha_email = g('senha_email')
    profile_id = str(item.get('profile_id') or '')
    motivo = (item.get('mensagem') or '').strip()
    linhas = []
    if motivo:
        linhas.append(f"# MOTIVO: {motivo}")
    if profile_id:
        # Marcador lido no reimport: reabrir o MESMO navegador AdsPower (já logado),
        # em vez de criar um novo. (Suporte de leitura no parser é etapa à parte.)
        linhas.append(f"REABRIR: {profile_id}")
    linhas.append(f"Login: {login}")
    if senha:
        linhas.append(f"Senha: {senha}")
    if tfa:
        linhas.append(f"2FA: {tfa}")
    if cookies:
        linhas.append(f"Cookies: {cookies}")
    if token:
        linhas.append(f"Token: {token}")
    if email:
        linhas.append(f"Email: {email}")
    if senha_email:
        linhas.append(f"Senha Email: {senha_email}")
    return "\n".join(linhas)


def _exportar_falhas(categoria_alvo, titulo, nome_arquivo):
    """Filtra `_estado['progresso']` pela categoria e salva um .txt (diálogo Salvar).
    Retorna dict {sucesso, mensagem, total, arquivo}."""
    prog = _estado.get('progresso') or []
    perfis = _estado.get('perfis') or []
    blocos = []
    for item in prog:
        if _categoria_falha(item) != categoria_alvo:
            continue
        idx = item.get('indice', -1)
        perfil = perfis[idx] if 0 <= idx < len(perfis) else {}
        blocos.append(_linha_export_perfil(perfil, item))
    n = len(blocos)
    if n == 0:
        return {'sucesso': False, 'total': 0,
                'mensagem': 'Nenhum perfil nesta categoria para exportar.'}
    # Cada perfil vai num bloco separado por "--- Conta N ---" (o parser de RÓTULOS
    # divide os blocos por essas linhas; sem elas os perfis se fundiriam num só).
    partes = [f"--- Conta {k} ---\n{b}" for k, b in enumerate(blocos, 1)]
    conteudo = (f"# {titulo}\n# GS BM Creator — {n} perfil(is)\n"
                f"# (reimporte no software para retomar o fluxo destes perfis)\n\n"
                + "\n\n".join(partes) + "\n")
    # Diálogo "Salvar como" do pywebview.
    try:
        import webview
        win = webview.windows[0]
        destino = win.create_file_dialog(webview.SAVE_DIALOG, save_filename=nome_arquivo)
    except Exception as e:
        logger.error("[Export] Diálogo de salvar falhou: %s", e)
        return {'sucesso': False, 'total': n,
                'mensagem': f'Não foi possível abrir o diálogo de salvar: {e}'}
    if not destino:
        return {'sucesso': False, 'total': n, 'mensagem': 'Exportação cancelada.'}
    caminho = destino if isinstance(destino, str) else destino[0]
    try:
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write(conteudo)
    except Exception as e:
        logger.error("[Export] Erro ao salvar %s: %s", caminho, e)
        return {'sucesso': False, 'total': n, 'mensagem': f'Erro ao salvar o arquivo: {e}'}
    logger.info("[Export] %s perfil(is) exportado(s) para %s", n, caminho)
    return {'sucesso': True, 'total': n, 'arquivo': caminho,
            'mensagem': f'{n} perfil(is) exportado(s) para {caminho}'}


def exportar_falhas_login():
    """Botão A: contas que NÃO conseguiram logar no Facebook (bloqueio / checkpoint
    / conta travada / precisa código no e-mail Hotmail-Outlook)."""
    return _exportar_falhas(
        'login',
        'Contas SEM login no Facebook (bloqueio / checkpoint / codigo por e-mail)',
        'contas_bloqueio_login.txt')


def exportar_falhas_fluxo():
    """Botão B: perfis que logaram mas a BM NÃO foi enviada p/ análise (incompleto /
    bloqueada / não verificada). Para reimportar e retomar o fluxo."""
    return _exportar_falhas(
        'fluxo',
        'Perfis com BM incompleta (nao enviada para analise)',
        'perfis_bm_incompleta.txt')


def cancelar_processamento():
    """Cancela o run: ABORTA 100% — marca cancelar, ACORDA quem está pausado/esperando
    (SMS sem saldo / domínio) e FECHA os navegadores abertos do run. (2026-07-13)"""
    _estado['cancelar'] = True
    _estado['pausado'] = False
    # Também cancela o modo REUTILIZAR PERFIL LOGADO (roda pelo _estado_reprocesso),
    # já que ele usa o MESMO botão Cancelar/terminal da interface principal.
    try:
        _estado_reprocesso['cancelar'] = True
    except Exception:
        pass
    try:
        from server import pausa as _pausa
        _pausa.set_cancelar(True)
    except Exception:
        pass
    try:
        _fechar_navegadores_do_run()
    except Exception as e:
        logger.warning('[Cancelar] fechar navegadores: %s', e)
    return True


def pausar_processamento():
    """PAUSA o run: o dispatcher NÃO abre novos perfis e as esperas (SMS sem saldo/
    domínio) aguardam. O que já está aberto segue até um ponto seguro e então espera."""
    _estado['pausado'] = True
    try:
        from server import pausa as _pausa
        _pausa.set_pausado(True)
    except Exception:
        pass
    return {'sucesso': True, 'pausado': True, 'mensagem': 'Pausado — clique Continuar para retomar.'}


def continuar_processamento():
    """CONTINUA (despausa) o run — retoma a compra de SMS / abertura de perfis."""
    _estado['pausado'] = False
    try:
        from server import pausa as _pausa
        _pausa.set_pausado(False)
    except Exception:
        pass
    return {'sucesso': True, 'pausado': False, 'mensagem': 'Retomando...'}


def _fechar_navegadores_do_run():
    """Fecha (best-effort) os navegadores dos perfis do run atual — usado no Cancelar
    para abortar de verdade, sem deixar abas penduradas."""
    try:
        mod = _get_browser_module()
    except Exception:
        return
    _ids = set()
    for p in list(_estado.get('perfis') or []):
        if isinstance(p, dict):
            pid = (p.get('user_id') or p.get('profile_id') or p.get('id')
                   or p.get('profileId') or '')
            if pid:
                _ids.add(str(pid))
    # FIX (auditoria 24/7): os navegadores CRIADOS no run gravam o ID em
    # progresso[i]['profile_id'], NÃO no dict do perfil. Sem isto, Cancelar/atexit
    # não fechavam os navegadores recém-criados → órfãos acumulando (RAM/handles).
    for it in list(_estado.get('progresso') or []):
        if isinstance(it, dict):
            pid = it.get('profile_id') or ''
            if pid:
                _ids.add(str(pid))
    for pid in _ids:
        try:
            mod.fechar_navegador(pid)
        except Exception:
            pass


def definir_browser_engine(engine, adspower_url='', adspower_token=''):
    """Define o engine de browser: 'ixbrowser' ou 'adspower'."""
    if engine in ('ixbrowser', 'adspower'):
        _estado['browser_engine'] = engine
        if engine == 'adspower':
            if adspower_url:
                adspower_api.configurar_url(adspower_url)
            if adspower_token:
                adspower_api.configurar_api_key(adspower_token)
        logger.info("Browser engine alterado para: %s", engine)
        return {"sucesso": True, "engine": engine}
    return {"sucesso": False, "mensagem": "Engine inválido. Use 'ixbrowser' ou 'adspower'."}


def _gravar_relatorio_run():
    """Grava um RELATÓRIO COMPLETO do run (status + mensagem por perfil, totais,
    fluxo) em <RUNTIME_DIR>/relatorios_run/. Serve para diagnóstico pós-execução
    sem precisar narrar tela por tela: ao fim de cada run, o arquivo `ultimo_run.*`
    resume tudo (e os snapshots de telas novas ficam em telas_desconhecidas/).
    Best-effort — nunca quebra o fim do run."""
    try:
        prog = _estado.get('progresso', []) or []
        perfis = _estado.get('perfis', []) or []
        itens = []
        n_ok = n_err = n_outro = 0
        for idx, p in enumerate(prog):
            st = str(p.get('status', '') or '')
            login = perfis[idx].get('login', '') if idx < len(perfis) else ''
            itens.append({'indice': idx, 'login': login, 'status': st,
                          'mensagem': str(p.get('mensagem', '') or '')})
            if st == 'Concluído':
                n_ok += 1
            elif st == 'Erro':
                n_err += 1
            else:
                n_outro += 1
        relatorio = {
            'data': time.strftime('%Y-%m-%d %H:%M:%S'),
            'fluxo': _estado.get('verificar_bm', ''),
            'total': len(prog), 'concluidos': n_ok, 'erros': n_err,
            'outros': n_outro, 'cancelado': bool(_estado.get('cancelar')),
            'itens': itens,
            'pasta_telas_desconhecidas': os.path.join(RUNTIME_DIR, 'telas_desconhecidas'),
        }
        pasta = os.path.join(RUNTIME_DIR, 'relatorios_run')
        os.makedirs(pasta, exist_ok=True)
        nome = time.strftime('run_%Y%m%d_%H%M%S.json')
        for caminho in (os.path.join(pasta, nome), os.path.join(pasta, 'ultimo_run.json')):
            with open(caminho, 'w', encoding='utf-8') as fh:
                json.dump(relatorio, fh, ensure_ascii=False, indent=2)
        # versão TXT legível (resumo rápido)
        linhas = [f"RUN {relatorio['data']} | fluxo={relatorio['fluxo']} | "
                  f"OK={n_ok} ERRO={n_err} OUTRO={n_outro} TOTAL={len(prog)}",
                  "-" * 70]
        for it in itens:
            linhas.append(f"[{it['status']:<10}] {it['login']:<22} {it['mensagem']}")
        with open(os.path.join(pasta, 'ultimo_run.txt'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(linhas) + '\n')
        logger.info("[Relatorio] Run salvo (%d OK, %d erro): %s",
                    n_ok, n_err, os.path.join(pasta, 'ultimo_run.txt'))
    except Exception as e:
        logger.warning("[Relatorio] Falha ao gravar relatório do run: %s", e)


def _ativar_modo_paralelo(paralelo):
    """Liga/desliga o MODO PARALELO nos DOIS mecanismos de uma vez
    (automacao_facebook + playwright_compat) — para que N navegadores NÃO disputem
    o foco de janela do SO (bring_to_front/SetForegroundWindow/ESC físico). Se um
    ficar dessincronizado, o foco volta a ser roubado em paralelo — por isso LOGA a
    falha em vez de silenciar (o padrão antigo era `except: pass` duplicado)."""
    ok = True
    for _nome in ('automacao_facebook', 'playwright_compat'):
        try:
            _mod = __import__('server.' + _nome, fromlist=[_nome])
            if hasattr(_mod, 'set_modo_paralelo'):
                _mod.set_modo_paralelo(bool(paralelo))
        except Exception as _e:
            ok = False
            logger.warning('[Paralelo] set_modo_paralelo(%s) falhou em %s: %s',
                           paralelo, _nome, _e)
    return ok




def _painel_desfecho(business_id, desfecho, msg=''):
    """Best-effort: grava no painel (página "Minhas BMs") o desfecho do fluxo desta BM —
    bloqueada / recorrida / erro / checkpoint. 'enviada_analise' já é marcado pelo
    registrar_bm_em_analise. Nunca interrompe o worker."""
    if not business_id:
        return
    try:
        from server.painel_integration import reportar_desfecho
        reportar_desfecho(business_id, desfecho, msg)
    except Exception as _e:
        logger.debug('[Painel] desfecho %s não reportado: %s', desfecho, _e)


def _painel_registrar_em_analise(business_id, site_id='', site_url='', empresa_dados=None,
                                 profile_id='', fb_login=''):
    """Best-effort: mesma sequência do worker principal quando a BM vai p/ análise
    (status 'aguardando_verificacao' + registrar_bm_em_analise → creator_result=
    'enviada_analise' + carimbo do engine). Usado pelo REPROCESSO/REUTILIZAR — antes eles
    não reportavam nada e a BM continuava 'rejeitada'/'erro' no painel, voltando ao
    reprocesso-ocioso a cada ciclo (reenvio repetido de BM já em análise)."""
    if not business_id:
        return
    try:
        from server.painel_integration import (atualizar_status_bm_por_business_id,
                                               registrar_bm_em_analise, carimbar_engine_bm)
        try:
            atualizar_status_bm_por_business_id(business_id, 'aguardando_verificacao')
        except Exception as _e1:
            logger.debug('[Painel] status aguardando_verificacao %s: %s', business_id, _e1)
        registrar_bm_em_analise(business_id, site_id=site_id or '', site_url=site_url or '',
                                empresa_dados=empresa_dados or {},
                                profile_id=str(profile_id or ''), fb_login=fb_login or '')
        carimbar_engine_bm(business_id, _estado.get('browser_engine', ''), str(profile_id or ''))
    except Exception as _e:
        logger.warning('[Painel] registrar em análise (%s) falhou: %s', business_id, _e)


def iniciar_processamento(nome_grupo, proxy, utilizar_4g, lista_proxy, proxy_tipo,
                           usuario='', senha='', qtd_bm=1,
                           browser_engine='ixbrowser', adspower_token='', captcha_token='',
                           verificar_bm='nao', tipo_empresa='mei', auto_verificar='nao',
                           simultaneos=1, oculto='nao',
                           datacrazy_email='', datacrazy_senha='', sms24h_token='',
                           sms_provedor='', metodo_verificacao_dominio='auto'):
    """Inicia o processamento de criação de perfis + BMs (fluxo único: Turbo).

    `sms_provedor` ('sms24h' | 'grizzly' | 'tiger'): de qual API o número da
    verificação é comprado. Vazio = usa o que está salvo nas configurações.
    `datacrazy_email/senha` ficam só pela compatibilidade da config salva (o Turbo
    não usa o CRM).
    """
    if _estado['processando']:
        return {"sucesso": False, "mensagem": "Processamento já em andamento"}

    if not _estado['perfis']:
        return {"sucesso": False, "mensagem": "Nenhum perfil importado"}

    # Atualizar engine
    _estado['browser_engine'] = browser_engine
    # ── Reconciliador de TAGS em TEMPO REAL (sem abrir navegador) ──────────────
    # Enquanto o bot roda (multilogin aberto), um thread leve puxa o status das BMs
    # do painel a cada 3 min e troca a tag do perfil via API (EM ANALISE → VERIFICADA
    # 2K → PRECISA ATUALIZAR, etc.). Idempotente (não reinicia se já rodando).
    try:
        from server import tag_reconciler
        tag_reconciler.iniciar(
            get_engine=lambda: _estado.get('browser_engine', ''),
            get_mod=_get_browser_module,
            intervalo=180)
    except Exception as _tre:
        logger.debug('[TagRecon] não iniciou: %s', _tre)
    if browser_engine == 'adspower':
        if adspower_token:
            adspower_api.configurar_api_key(adspower_token)
        # Carregar URL salva
        user = _estado['usuario_logado'] or usuario
        saved_url = _ler_config('adspower_url', '', user)
        if saved_url:
            adspower_api.configurar_url(saved_url)

    # Salvar configurações
    salvar_configuracoes(nome_grupo, proxy, utilizar_4g, lista_proxy, proxy_tipo,
                          usuario, senha, _ler_config('lembrar_acesso', 'sim'),
                          str(qtd_bm), browser_engine, adspower_token, captcha_token,
                          adspower_url='', verificar_bm=verificar_bm,
                          tipo_empresa=tipo_empresa, auto_verificar=auto_verificar,
                          datacrazy_email=datacrazy_email, datacrazy_senha=datacrazy_senha,
                          sms24h_token=sms24h_token,
                          sms_provedor=(sms_provedor
                                        or _ler_config('sms_provedor', 'sms24h',
                                                       _estado.get('usuario_logado', ''))))

    # Credenciais do DataCrazy (config legada — o Turbo NÃO usa o CRM; mantidas no
    # _estado só porque a assinatura da etapa ainda as aceita).
    _estado['datacrazy_email'] = datacrazy_email or _estado.get('datacrazy_email', '') \
        or _ler_config('datacrazy_email', '', _estado.get('usuario_logado', ''))
    _estado['datacrazy_senha'] = datacrazy_senha or _estado.get('datacrazy_senha', '') \
        or _ler_config('datacrazy_senha', '', _estado.get('usuario_logado', ''))

    # Guardar captcha token no estado para uso no processamento. Se a GUI mandar
    # o campo EM BRANCO, cai na config do usuário e, por fim, na global — sem
    # isso o run inteiro rodava sem CapSolver e todo perfil que caísse no
    # reCAPTCHA do login era abortado.
    _estado['captcha_token'] = (captcha_token.strip() if captcha_token else '') \
        or _ler_captcha_token(_estado.get('usuario_logado', ''))
    # Token sms24h (Pro Max) no estado, defensivo mesmo sem persistência.
    _estado['sms24h_token'] = (sms24h_token.strip() if sms24h_token else '') \
        or _estado.get('sms24h_token', '') \
        or _ler_config('sms24h_token', '', _estado.get('usuario_logado', ''))
    # PROVEDOR DE SMS escolhido na tela (sms24h / grizzly / tiger). O token e o
    # provedor andam JUNTOS: usar a chave de um na API do outro devolve
    # "Token inválido"/BAD_KEY e o perfil se perde sem gastar nada.
    # Fallback na config salva — a GUI antiga não mandava este parâmetro no
    # iniciar (só no salvar), e o run inteiro comprava no sms24h com a chave do
    # Tiger. (corrigido 2026-08-02)
    _estado['sms_provedor'] = (str(sms_provedor).strip().lower()
                               or _ler_config('sms_provedor', 'sms24h',
                                              _estado.get('usuario_logado', ''))
                               or 'sms24h')
    logger.info("[SMS] Provedor ativo neste run: %s", _estado['sms_provedor'])

    # MÉTODO DE VERIFICAÇÃO DE DOMÍNIO (meta-tag | dns | arquivo | auto) escolhido na
    # GUI. 'auto' (padrão) = meta-tag e, se a Meta não confirmar, cai p/ DNS e arquivo.
    _mv = (str(metodo_verificacao_dominio).strip().lower()
           or _ler_config('metodo_verificacao_dominio', 'auto',
                          _estado.get('usuario_logado', ''))
           or 'auto')
    _estado['metodo_verificacao_dominio'] = _mv
    try:
        from server import verificacao_bm as _vbm
        _vbm.set_metodo_verificacao(_mv)
        _salvar_config('metodo_verificacao_dominio', _mv, _estado.get('usuario_logado', ''))
    except Exception as _e_mv:
        logger.debug("[Domínio] set_metodo_verificacao: %s", _e_mv)
    logger.info("[Domínio] Método de verificação neste run: %s", _mv)

    # FALLBACK A → B → C: registra o token de CADA provedor. Se o número do
    # primeiro não receber o SMS, a tentativa seguinte compra no próximo — insistir
    # no mesmo pool que não entrega só queima tempo (medido: cada provedor tem uma
    # única faixa de preço por serviço/país, então "número melhor" = OUTRO provedor).
    _usr = _estado.get('usuario_logado', '')
    _tokens_sms = {
        'sms24h':   _ler_config('sms_token_sms24h', '', _usr),
        'grizzly':  _ler_config('sms_token_grizzly', '', _usr),
        'tiger':    _ler_config('sms_token_tiger', '', _usr),
        'vak':      _ler_config('sms_token_vak', '', _usr),
        'smsbower': _ler_config('sms_token_smsbower', '', _usr),
    }
    # O token do campo ANTIGO ("Token SMS") vale para o provedor selecionado —
    # mas SÓ quando aquele provedor ainda não tem token próprio.
    # ⚠️ ARMADILHA REAL (2026-08-03): trocar o provedor na GUI NÃO troca o campo
    # antigo. Com 'vak' selecionado e o token do TIGER ainda no campo, o cliente
    # do vak-sms recebia a chave do Tiger → "Пользователь не найден" (HTTP 400) →
    # o fluxo lia isso como instabilidade e as 8 abas ficavam em retry até PAUSAR.
    _prov_sel = _estado['sms_provedor']
    if _estado['sms24h_token'] and not _tokens_sms.get(_prov_sel):
        _tokens_sms[_prov_sel] = _estado['sms24h_token']

    # PRÉ-VOO: valida cada token pelo saldo ANTES de começar. Um token errado/
    # expirado sai da fila aqui, com mensagem clara, em vez de virar "provedor
    # instável" no meio do run e travar as abas.
    try:
        from server.sms24h_client import criar_cliente as _criar_cli, nome_do_provedor as _nprov
        for _p, _tk in list(_tokens_sms.items()):
            if not str(_tk or '').strip():
                continue
            try:
                _cli = _criar_cli(_tk, _p)
                _ok = _cli.token_valido()
                _s = _cli.saldo() if _ok is not False else None
            except Exception:
                _ok, _s = None, None
            if _ok is False:
                # A API RECUSOU a chave — não é queda de rede. Sai da fila: se
                # ficasse, cada tentativa gastaria uma rodada só para falhar.
                _tokens_sms[_p] = ''
                logger.error('[SMS] %s: token INVÁLIDO (a API recusou a chave) — '
                             'removido da fila deste run.', _nprov(_p))
            elif _s is None:
                logger.warning('[SMS] %s: não consegui ler o saldo (rede/API) — '
                               'mantido na fila.', _nprov(_p))
            else:
                logger.info('[SMS] %s: token OK · saldo %s', _nprov(_p), _s)
                if _s <= 0:
                    logger.warning('[SMS] %s está SEM SALDO — o fluxo vai pular '
                                   'para o próximo provedor.', _nprov(_p))
    except Exception as _e:
        logger.debug('[SMS] pré-voo dos tokens ignorado: %s', _e)
    try:
        from server.sms24h_client import configurar_tokens, configurar_preco_max
        _ativos = configurar_tokens(_tokens_sms)
        # PADRÃO 0.12 (2026-08-30, decisão do dono): sem teto, a API entrega o número
        # MAIS BARATO — que é o mais reusado por todos e chega já "queimado" (Meta acusa
        # "muitos códigos" nele). Teto 0.12 LIBERA as faixas melhores (ex.: pool smsbower
        # id 2738 @ 0,116$, 404k em estoque) SEM forçar o caro: pega o bom quando o barato
        # está esgotado/queimado. Sobrescrevível na GUI (campo "Preço máx").
        _pmax = configurar_preco_max(_ler_config('sms_preco_max', '0.12', _usr))
        if _pmax:
            logger.info('[SMS] Teto por número: US$ %.4f (libera faixas melhores/frescas)', _pmax)
        if len(_ativos) > 1:
            logger.info("[SMS] Fallback disponível em: %s", ', '.join(_ativos.keys()))
    except Exception as _e:
        logger.warning("[SMS] Não configurei os tokens de fallback: %s", _e)

    # ── FLUXO ÚNICO (2026-10-05): ⚡ Pro Max DataCrazy Turbo ──────────────────
    # Todos os outros métodos (Básico, Padrão, Avançado, Gupshup Lite/Pro, Pro Max
    # Gupshup/DataCrazy-CRM/E-mail/Sem WABA, GS Prime Plus, HighLevel) foram
    # REMOVIDOS do sistema. Qualquer valor que a GUI/config antiga mande é
    # normalizado para o Turbo (com aviso no log se vier diferente).
    _vb = str(verificar_bm or '').strip().lower()
    if _vb and _vb != FLUXO_UNICO:
        logger.warning("[Fluxo] verificar_bm=%r não existe mais — usando o fluxo único %r.",
                       _vb, FLUXO_UNICO)
    _estado['verificar_bm'] = FLUXO_UNICO

    # ── Controle de acesso por NÍVEL (role) ────────────────────────────────
    # O Turbo é exclusivo de contas 'admin' ou 'editor'. Usuário comum que tentar
    # usá-lo (ex.: burlando a UI) é BLOQUEADO aqui antes de iniciar qualquer coisa.
    if _TEM_ACESSO and not usuario_pode_planos_gupshup():
        logger.warning("[Acesso] Usuário '%s' (comum) tentou usar o Pro Max DataCrazy Turbo — bloqueado.",
                       _estado.get('usuario_logado', '?'))
        return {"sucesso": False,
                "mensagem": ("O Pro Max DataCrazy Turbo é exclusivo para usuários "
                             "Editor/Admin. Peça a liberação do seu acesso no painel.")}

    _estado['tipo_empresa'] = tipo_empresa or 'mei'

    # Auto-verificar a fila de 2h: REMOVIDO (2026-10-13, pedido do dono). O watcher abria
    # navegador sozinho quando a lista acabava. Fora da lista o app não abre navegador.
    _estado['auto_verificar'] = False

    thread = threading.Thread(
        target=_processar_perfis,
        args=(nome_grupo, proxy, utilizar_4g, lista_proxy, proxy_tipo, int(qtd_bm)),
        kwargs={'simultaneos': int(simultaneos or 1), 'oculto': oculto},
        daemon=True
    )
    thread.start()
    return {"sucesso": True, "mensagem": "Processamento iniciado"}


def definir_auto_verificar(valor):
    """REMOVIDO (2026-10-13, pedido do dono): a verificação automática da fila abria o
    navegador sozinho com o app ocioso. Stub mantido porque o main.py expõe o nome."""
    _estado['auto_verificar'] = False
    return {'sucesso': False, 'auto_verificar': False}


def definir_recurso_com_texto(valor):
    """Liga/desliga o texto de contestação no recurso da WABA desabilitada. Exposto ao JS.

    'sim'/True  -> envia o recurso COM o texto de contestação (comportamento atual).
    'nao'/False -> envia o formulário EM BRANCO (Solicitar análise/Submit sem preencher nada).
    Persiste por usuário para sobreviver a reinícios."""
    com_texto = valor in ('sim', 'true', True, '1', 1)
    _estado['recurso_com_texto'] = com_texto
    try:
        user = _estado.get('usuario_logado') or _ler_config('ultimo_usuario_software', '')
        _salvar_config('recurso_com_texto', 'sim' if com_texto else 'nao', user)
    except Exception as e:
        logger.warning('[Recurso] persistir recurso_com_texto falhou: %s', e)
    logger.info('[Recurso] recurso_com_texto = %s', 'sim (com texto)' if com_texto else 'nao (em branco)')
    return {'sucesso': True, 'recurso_com_texto': com_texto}


def _gerar_tags_perfil(perfil):
    """Gera tags descritivas baseadas nos dados detectados do perfil."""
    tags = []

    # Tag do ID/Login
    login = perfil.get('login', '')
    if login:
        tags.append(f"🆔 {login}")

    # Tipo de email
    email = perfil.get('email', '')
    if email:
        dominio = email.split('@')[-1].lower() if '@' in email else ''
        if 'hotmail' in dominio or 'outlook' in dominio or 'live.com' in dominio:
            tags.append("📩 Hotmail")
        elif 'yahoo' in dominio:
            tags.append("📩 Yahoo")
        elif 'gmail' in dominio:
            tags.append("📩 Gmail")
        elif 'icloud' in dominio or 'me.com' in dominio:
            tags.append("📩 iCloud")
        else:
            tags.append("📧 Email")

    # Senha do email
    if perfil.get('senha_email'):
        tags.append("🔐 Senha Email")

    # 2FA
    if perfil.get('tfa'):
        tags.append("🔑 2FA")

    # Cookie
    if perfil.get('cookie_raw'):
        tags.append("🍪 Cookie")

    # Token
    if perfil.get('token'):
        tags.append("🎫 Token")

    return tags


def _parse_lista_proxy(lista_proxy):
    """Parseia lista de proxies suportando dois formatos:
    - Formato compacto: IP:Porta:Usuario:Senha (1 por linha)
    - Formato bloco: IP\\nPorta\\nUsuario\\nSenha (separados por linha em branco)
    Retorna lista de dicts com keys: ip, port, user, pass
    """
    texto = lista_proxy.strip()
    if not texto:
        return []

    proxies = []

    # Detectar formato: se primeira linha não-vazia contém ":" com 3+ partes, é formato compacto
    primeira_linha = ''
    for linha in texto.split('\n'):
        l = linha.strip()
        if l:
            primeira_linha = l
            break

    if primeira_linha.count(':') >= 1:
        # Tentar formato compacto IP:Porta:Usuario:Senha
        for linha in texto.split('\n'):
            l = linha.strip()
            if not l:
                continue
            partes = l.split(':')
            if len(partes) >= 2:
                # 5º campo em diante = URL de ROTAÇÃO de IP do proxy (opcional).
                # Religa com ':' pra não quebrar no 'https://' (que tem ':' e '//').
                # Ex.: host:porta:user:senha:https://megaproxy.online/r.php?t=TOKEN
                # Se vier sem esquema (ex.: 'dominio.com/r?x=1'), assume https://.
                # COM url => o GS Creator controla o IP (gira antes do navegador e no
                # meio do fluxo se precisar). SEM url => usa o AUTO do provedor.
                rot = ':'.join(partes[4:]).strip() if len(partes) >= 5 else ''
                if rot and not rot.lower().startswith(('http://', 'https://')):
                    rot = 'https://' + rot
                proxies.append({
                    'ip': partes[0].strip(),
                    'port': partes[1].strip(),
                    'user': partes[2].strip() if len(partes) >= 3 else '',
                    'pass': partes[3].strip() if len(partes) >= 4 else '',
                    'rot_url': rot,
                })

    # Se não conseguiu parsear como compacto, tentar formato bloco
    if not proxies:
        blocos = texto.split('\n\n')
        for bloco in blocos:
            linhas = bloco.strip().split('\n')
            if linhas and linhas[0].strip():
                _rotb = linhas[4].strip() if len(linhas) >= 5 else ''
                if _rotb and not _rotb.lower().startswith(('http://', 'https://')):
                    _rotb = 'https://' + _rotb
                proxies.append({
                    'ip': linhas[0].strip() if len(linhas) >= 1 else '',
                    'port': linhas[1].strip() if len(linhas) >= 2 else '',
                    'user': linhas[2].strip() if len(linhas) >= 3 else '',
                    'pass': linhas[3].strip() if len(linhas) >= 4 else '',
                    'rot_url': _rotb,
                })

    logger.info("[Proxy] Parseou %d proxies da lista", len(proxies))
    return proxies


def _empresa_buffer_valido():
    """True se ha empresa/site em buffer dentro do TTL e abaixo do limite
    de tentativas. Caso contrario, descarta o buffer e retorna False."""
    # Em modo paralelo (simultâneos>1) cada worker é independente — buffer desligado.
    if _estado.get('_buffer_off'):
        return False
    buf = _estado.get('empresa_buffer')
    if not buf:
        return False
    try:
        agora = time.time()
        idade = agora - float(buf.get('criado_em') or 0)
        tentativas = int(buf.get('tentativas') or 0)
        if idade > _EMPRESA_BUFFER_TTL_SEG or tentativas >= _EMPRESA_BUFFER_MAX_TENTATIVAS:
            logger.info('[EmpresaBuffer] descartado (idade=%.0fs tentativas=%d)',
                        idade, tentativas)
            _estornar_token_buffer(buf, f'descartado idade={idade:.0f}s tent={tentativas}')
            _estado['empresa_buffer'] = None
            return False
        return True
    except Exception:
        _estornar_token_buffer(_estado.get('empresa_buffer'), 'erro ao validar buffer')
        _estado['empresa_buffer'] = None
        return False


def _empresa_buffer_consumir():
    """BM criada com sucesso: a empresa em buffer foi efetivamente usada."""
    if _estado.get('empresa_buffer'):
        logger.info('[EmpresaBuffer] consumido (BM criada)')
    _estado['empresa_buffer'] = None


def _empresa_buffer_reter(empresa_dados, site_cache, nome_bm, seu_nome, token_held=False):
    """Armazena/atualiza empresa+site para reuso no proximo perfil.

    token_held=True indica que 1 token JA foi debitado por este site e segue
    'em hold' — ele NAO e estornado enquanto o site puder ser reusado; vira
    DEFINITIVO quando uma BM for verificada com sucesso usando este site, ou e
    estornado quando o buffer for descartado (expirado/sem mais perfis)."""
    buf = _estado.get('empresa_buffer')
    if buf and int(buf.get('tentativas') or 0) > 0:
        # Ja existe um buffer (a falha aconteceu em cima de um reuso):
        # incrementa tentativas mas mantem a empresa e o hold do token.
        buf['tentativas'] = int(buf.get('tentativas') or 0) + 1
        buf['token_held'] = bool(buf.get('token_held') or token_held)
        logger.info('[EmpresaBuffer] retido (tentativas=%d, token_held=%s)',
                    buf['tentativas'], buf['token_held'])
        return
    _estado['empresa_buffer'] = {
        'empresa_dados': dict(empresa_dados or {}),
        'site_cache': dict(site_cache or {}),
        'nome_bm_override': nome_bm or '',
        'seu_nome_override': seu_nome or '',
        'tentativas': 1,
        'token_held': bool(token_held),
        'criado_em': time.time(),
    }
    logger.info("[EmpresaBuffer] novo buffer ativo (site=%s, token_held=%s)",
                (site_cache or {}).get('url', ''), bool(token_held))


def _estornar_token_buffer(buf, motivo=''):
    """Devolve o token 'em hold' de um buffer que esta sendo DESCARTADO (a
    entrega nunca foi concluida em nenhum perfil). Idempotente/best-effort."""
    if not buf or not buf.get('token_held'):
        return
    if not _TEM_ACESSO:
        return
    try:
        _r = reembolsar_token(1, f'Estorno site (buffer descartado): {motivo}'[:120])
        if _r.get('sucesso'):
            logger.info('[EmpresaBuffer] token em hold ESTORNADO (buffer descartado: %s). Saldo: %s',
                        motivo, _r.get('tokens', '?'))
        else:
            logger.warning('[EmpresaBuffer] falha ao estornar token do buffer: %s',
                           _r.get('mensagem', ''))
    except Exception as _e:
        logger.warning('[EmpresaBuffer] erro ao estornar token do buffer: %s', _e)


def _processar_perfis(nome_grupo, proxy, utilizar_4g, lista_proxy, proxy_tipo, qtd_bm=1,
                      simultaneos=1, oculto='nao'):
    """Thread principal de processamento."""
    _estado['processando'] = True
    _estado['cancelar'] = False
    _estado['pausado'] = False
    try:
        from server import pausa as _pausa
        _pausa.reset()   # zera pausa/cancelar globais a cada run
    except Exception:
        pass
    _estado['empresa_buffer'] = None  # zera buffer a cada run
    # Anti-cascata: resetado a cada run; ativado só no modo IP compartilhado.
    _estado['_ip_compartilhado'] = False
    _ts_ultima_criacao_ip[0] = 0.0

    # ── IP INTELIGENTE (2026-08-29) — modelo "Cota por IP" (rolling) ──────────
    # Janela de congelamento do IP CONFIGURÁVEL pelo usuário (1/3/6/12/24h) + cota
    # máxima de perfis por IP. O log de IPs usados é PERSISTENTE (ips_4g_usados.json) e
    # o trocar_ip_4g_adb já rotaciona até achar um IP LIMPO (fora da janela). Aqui só
    # aplicamos a escolha do usuário e preparamos o contador da cota.
    global _IP_CONGELAMENTO_HORAS
    _u_cfg = _estado.get('usuario_logado') or _ler_config('ultimo_usuario_software', '') or ''
    try:
        _jan = float(_ler_config('ip_janela_horas', '6', _u_cfg) or 6)
        if _jan > 0:
            _IP_CONGELAMENTO_HORAS = _jan
    except Exception:
        pass
    try:
        _kmax = int(_ler_config('ip_max_por_ip', '10', _u_cfg) or 10)
    except Exception:
        _kmax = 10
    _estado['_ip_max_por_ip'] = max(1, _kmax)
    _estado['_ip_iniciados'] = 0     # perfis iniciados no IP atual (p/ a cota K)
    _estado['_ip_ciclo'] = 0         # último ciclo de rotação já contabilizado (zera a cota)
    _estado['ip_eventos'] = []       # linhas de evento de IP p/ o terminal (atual → novo)
    logger.info("[IP] Cota por IP: janela=%.0fh, no máximo %s perfil(is) por IP.",
                _IP_CONGELAMENTO_HORAS, _estado['_ip_max_por_ip'])

    # ── Fase 2: navegadores simultâneos (1–10) + modo oculto/headless ──
    _simultaneos = max(1, min(10, int(simultaneos or 1)))  # máximo atual: 10 (2026-10-13)
    _oculto = str(oculto or 'nao').lower() in ('sim', 'true', '1')
    # Em paralelo cada worker é INDEPENDENTE (gera própria empresa/site), então o
    # buffer de reuso de empresa entre perfis fica desligado.
    _estado['_buffer_off'] = (_simultaneos > 1)
    _estado['oculto'] = _oculto
    # ISOLAÇÃO PARALELA: avisa a automação do FB p/ DESLIGAR ações de nível-SO
    # (foco/ESC real) quando há 2+ navegadores — senão elas agiriam na janela do
    # worker errado (títulos "Facebook" iguais). Sequencial (=1) reativa o normal.
    # Liga/desliga ambos os mecanismos de uma vez (foco do FB + bring_to_front do
    # playwright): em paralelo NENHUMA ação de nível-SO roda — senão viraria
    # tempestade de ativação de janela e CONGELARIA o Windows.
    _ativar_modo_paralelo(_simultaneos > 1)
    # Grade de janelas: só quando a manipulação está LIGADA, VISÍVEL e com mais de
    # 1 navegador. Com _MANIPULAR_JANELA=False usamos a janela ORIGINAL do perfil
    # (evita o bug "No options" do Gupshup) — grade vazia → janela=None no abrir.
    _fluxo_grade = str(_estado.get('verificar_bm', 'nao') or 'nao').lower()
    _grade_cells = (_calcular_grade_janelas(_simultaneos, flow=_fluxo_grade)
                    if (_MANIPULAR_JANELA and _simultaneos > 1 and not _oculto) else [])
    logger.info("[Processamento] simultaneos=%s oculto=%s grade=%s",
                _simultaneos, _oculto, len(_grade_cells))

    # Janela visível + paralelo → centraliza a GUI e a deixa no topo (visível
    # ao vivo), com os navegadores dispostos EM VOLTA. Não rouba o foco.
    if _grade_cells and not _oculto and _simultaneos > 1:
        try:
            _centralizar_gui_topmost()
        except Exception:
            pass

    # Cooldown exponencial em falhas em cadeia (anti-detecao do FB)
    try:
        from server.humanizacao_avancada import CooldownEmCadeia
        _cooldown = CooldownEmCadeia()
    except Exception:
        _cooldown = None

    mod = _get_browser_module()
    engine_name = _estado.get('browser_engine', 'ixbrowser')
    logger.info("[Processamento] Iniciando com engine=%s, grupo='%s', %d perfis, proxy=%s",
                engine_name, nome_grupo, len(_estado['perfis']), proxy)

    try:
        conexao = mod.verificar_conexao()
        if not conexao.get('conectado'):
            msg = conexao.get('mensagem', 'Desconhecido')
            logger.error("[Processamento] Browser engine não conectado: %s", msg)
            _atualizar_status_geral(f"Erro: {engine_name} não conectado - {msg}")
            # Mostrar mensagem de erro detalhada para cada perfil
            for idx in range(len(_estado['perfis'])):
                _atualizar_progresso(idx, 'Erro', '#FF4444', msg)
                _inc('erros')
            _estado['processando'] = False
            return

        logger.info("[Processamento] Conexão verificada OK. Buscando/criando grupo '%s'...", nome_grupo)

        grupo_id = mod.obter_ou_criar_grupo(nome_grupo)
        if not grupo_id:
            logger.error("[Processamento] Falha ao obter/criar grupo: %s", nome_grupo)
            # Mensagem mais específica se for erro de auth
            erro_msg = f'Falha ao criar grupo "{nome_grupo}"'
            if engine_name == 'adspower':
                erro_msg += ' — Verifique a API Key do AdsPower'
            for idx in range(len(_estado['perfis'])):
                _atualizar_progresso(idx, 'Erro', '#FF4444', erro_msg)
                _inc('erros')
            _estado['processando'] = False
            return

        logger.info("[Processamento] Grupo obtido: ID=%s. Processando %d perfis...", grupo_id, len(_estado['perfis']))

        def _trabalhar(i, perfil, proxy_override=None, cell_idx=None, proxy_dict=None):
            # cell_idx: posição FIXA na grade (slot) — usada no modo CONCORRENTE
            # (rolling, sem 4G) p/ o novo perfil nascer no MESMO lugar do que fechou.
            # proxy_dict: o DICT do proxy desta aba (com 'rot_url'). Diferente de
            # proxy_override, que é o config já montado p/ o navegador. Guardamos o
            # dict para a rotação de IP NO MEIO do fluxo poder girar SÓ esta aba.
            if _estado['cancelar']:
                return

            # Cooldown crescente apos falhas em cadeia (humanizacao) — só no modo
            # SEQUENCIAL (o cooldown global compartilhado entre threads não se aplica).
            if _cooldown is not None and _simultaneos <= 1:
                try:
                    _cooldown.aplicar_se_necessario(
                        callback_status=lambda msg, _i=i: _atualizar_progresso(
                            _i, 'Aguardando', '#888888', msg)
                    )
                except Exception:
                    pass

            # 4G: NÃO há mais troca de IP proativa (por perfil / por lote / por tempo).
            # A troca acontece SOMENTE quando a Meta bate o rate-limit de SMS, via o
            # coordenador (ip_rotation_coordinator) — modelo único. Ver _processar_perfis.

            _atualizar_progresso(i, 'Processando', '#F2C94C', 'Criando perfil no navegador...')

            # Proxy: no PARALELO vem do pool (proxy_override, 1 por navegador ativo);
            # no SEQUENCIAL usa rotação cíclica 1:1.
            perfil_proxy = None
            # DICT do proxy desta aba (com 'rot_url'), p/ trocar o IP no MEIO do
            # fluxo girando SÓ esta aba — sem tocar nas outras.
            _proxy_da_aba = proxy_dict
            if proxy_override is not None:
                perfil_proxy = proxy_override
            elif proxy == 'sim' and lista_proxy:
                proxies_parsed = _parse_lista_proxy(lista_proxy)
                if proxies_parsed:
                    idx_proxy = i % len(proxies_parsed)
                    p = proxies_parsed[idx_proxy]
                    _proxy_da_aba = p
                    # URL de rotação => gira o IP ANTES de criar o navegador (1 IP por aba).
                    try:
                        from server import proxy_rotate
                        if proxy_rotate.tem_rotacao(p):
                            _atualizar_progresso(i, 'Aguardando', '#888888',
                                                 '🔁 Trocando IP do proxy antes de abrir o navegador...')
                            proxy_rotate.girar_ip(
                                p, status=lambda m, _i=i: _atualizar_progresso(_i, 'Aguardando', '#888888', m))
                    except Exception as _re:
                        logger.warning("[ProxyRotate] rotação pré-navegador (seq) falhou: %s", _re)
                    perfil_proxy = mod.montar_proxy_config(
                        p['ip'], p['port'], p['user'], p['pass'], proxy_tipo
                    )
                    logger.info("[Proxy] Perfil %d usando proxy %d/%d: %s:%s",
                                i + 1, idx_proxy + 1, len(proxies_parsed), p['ip'], p['port'])

            # Marcar perfil como usado se veio do painel
            compra_id = perfil.get('compra_id', 0)
            if compra_id and _TEM_ACESSO:
                marcar_perfil_usado(compra_id)

            # REIMPORT/REABRIR (marcador "REABRIR:" no .txt exportado de falhas): o
            # perfil JÁ foi usado e já tem um navegador no AdsPower LOGADO. Em vez de
            # CRIAR um novo (duplicaria o navegador e poderia perder a sessão logada),
            # REABRE o MESMO profile_id. O fluxo adiante abre esse navegador, detecta a
            # BM já existente (executar_automacao_perfil → bm_ja_existia) e RETOMA pelo
            # status (retomar_bm_para_analise → domínio/restrição → WABA/Central →
            # análise; se restrita, cria uma 2ª BM). (2026-07-14)
            _reabrir_id = str(perfil.get('reabrir_profile_id') or '').strip()
            if _reabrir_id:
                resultado = {'sucesso': True, 'profile_id': _reabrir_id}
                logger.info("[Processamento] Perfil %d/%d REABRINDO navegador existente "
                            "(profile_id=%s) — sem criar novo.",
                            i + 1, len(_estado['perfis']), _reabrir_id)
                _atualizar_progresso(i, 'Processando', '#F2C94C',
                                     '♻️ Reabrindo navegador já logado (retomar BM)...')
            else:
                # Abertura SEQUENCIAL (1-por-vez): serializa a criação do navegador na
                # API do AdsPower/IXBrowser para não floodar quando há vários workers.
                with _lock_abertura:
                    resultado = mod.criar_perfil(perfil, grupo_id, perfil_proxy)
                logger.info("[Processamento] Perfil %d/%d criar_perfil: sucesso=%s msg=%s",
                            i + 1, len(_estado['perfis']),
                            resultado.get('sucesso'), resultado.get('mensagem', '')[:80])
            if resultado['sucesso']:
                profile_id = resultado['profile_id']
                # Persiste o user_id do navegador no progresso p/ os EXPORTS de
                # falhas (marcador REABRIR — reimportar reabre o MESMO navegador).
                try:
                    if 0 <= i < len(_estado['progresso']):
                        _estado['progresso'][i]['profile_id'] = str(profile_id or '')
                except Exception:
                    pass
                # PORTÃO DE POSSE: marca ESTE navegador (e o login/e-mail do perfil) no
                # índice local oculto — foi a ferramenta que o criou a partir de um perfil
                # comprado/importado. Depois, "Reutilizar Logados"/"Reprocessar" só abrem
                # perfis que batem aqui ou no painel. Best-effort.
                try:
                    if _perfis_proprios:
                        _perfis_proprios.registrar(
                            engine=_estado.get('browser_engine', 'adspower'),
                            profile_id=str(profile_id or ''),
                            login=perfil.get('login', '') or perfil.get('usuario', ''),
                            email=perfil.get('email', ''))
                except Exception:
                    pass

                # ── Tags iniciais com dados detectados ──
                try:
                    tags_iniciais = _gerar_tags_perfil(perfil)
                    if tags_iniciais:
                        mod.adicionar_tags_perfil(profile_id, tags_iniciais)
                except Exception as e:
                    logger.warning("Erro ao adicionar tags iniciais: %s", e)

                try:
                    # ══════════════════════════════════════════════════════
                    # PRÉ-VERIFICAÇÃO: Criar empresa/site ANTES da BM
                    # para usar a razão social como nome da BM
                    # ══════════════════════════════════════════════════════
                    # ⚡ FLUXO ÚNICO: Pro Max DataCrazy Turbo (2026-10-05). Empresa + site
                    # + BM com razão social + domínio (meta-tag) + WABA pelo OAuth da Meta
                    # direto + envio p/ análise na Central de Segurança, com retry de 2ª BM.
                    _fluxo_bm = FLUXO_UNICO
                    # E-mail da BM no SUBDOMÍNIO do site (o modo 'raiz' era só do Pro Max
                    # E-mail, removido) — garante o padrão a cada run.
                    try:
                        from server import automacao_facebook as _af_mod
                        if hasattr(_af_mod, 'set_forcar_email_raiz'):
                            _af_mod.set_forcar_email_raiz(False)
                    except Exception:
                        pass
                    # ⭐ WABA-ANTES-DO-SITE (2026-09-27, pedido do dono): cria a WABA ANTES de
                    # gerar o site real e de verificar o domínio. Preenche a empresa com um
                    # SITE PROVISÓRIO (pool BR); só quando a WABA fica Aprovada/Restrita é que
                    # gera o site REAL, vincula na empresa (+ telefone) e verifica o domínio
                    # (meta-tag). Se a WABA nasce desabilitada → recorre e PARA, sem gastar
                    # site/domínio.
                    # ⛔ DESLIGADO (2026-09-28, decisão do dono): fica no fonte (gated) mas NÃO
                    # ativo — falta resolver o furo domínio×restrição (BM restrita não
                    # adiciona/verifica domínio). Reativar = True.
                    _fluxo_waba_antes_site = False
                    # _skip era usado para skip_close; mantemos para compatibilidade de lógica
                    _nome_bm_override = ''
                    _seu_nome_override = ''
                    _empresa_dados_cache = None
                    _site_cache = None
                    _pre_erro_msg = ''  # Guarda erro da pré-verificação
                    # Contabilidade de token (fluxo 'imediata'):
                    # criar_site debita 1 token (server-side). Mantemos o token
                    # APENAS se a entrega (dominio verificado) tiver sucesso.
                    # Em qualquer falha, estornamos o token deste perfil — assim
                    # o usuario so paga por dominios efetivamente entregues.
                    _token_gasto = False       # site criado e cobrado neste perfil?
                    _token_estornado = False   # ja devolvido?
                    # Empresa/site que tomou BLOQUEIO no FB: descartada de vez
                    # (estornada + marcada 'usado' + buffer limpo). Quando True,
                    # o _reter_ou_estornar NAO pode reter a empresa (ela esta
                    # queimada — reusa-la bloquearia os proximos perfis).
                    _empresa_bloqueada_descartada = False
                    # MÉTODO SEGURO (aging): BM criada foi ENFILEIRADA p/ verificação
                    # DIFERIDA (Passo 2). O token passa a ser responsabilidade da
                    # fila — este perfil NÃO estorna nem conta erro (a entrega será
                    # concluída/cobrada na verificação da fila, depois do descanso).
                    _enfileirou_aging = False

                    def _estornar_token_se_preciso(_motivo=''):
                        """Devolve o token do site deste perfil (idempotente)."""
                        nonlocal _token_gasto, _token_estornado
                        if not _token_gasto or _token_estornado:
                            return
                        if not _TEM_ACESSO:
                            return
                        try:
                            _r = reembolsar_token(
                                1, f'Estorno site (BM nao entregue): {_motivo}'[:120])
                            if _r.get('sucesso'):
                                _token_estornado = True
                                logger.info('[Token] Estornado 1 token (perfil %s): %s. Saldo: %s',
                                            profile_id, _motivo, _r.get('tokens', '?'))
                            else:
                                logger.warning('[Token] Falha ao estornar token (perfil %s): %s',
                                               profile_id, _r.get('mensagem', ''))
                        except Exception as _te:
                            logger.warning('[Token] Erro ao estornar token: %s', _te)

                    def _descartar_empresa_bloqueada(_motivo=''):
                        """BM tomou BLOQUEIO no FB DEPOIS de preencher empresa/site.
                        A empresa provavelmente está marcada/banida — NUNCA reusar:
                        1) ESTORNA o token do site (entrega bloqueada = não cobrar);
                        2) marca o CNPJ 'usado' no estoque (não volta a 'disponivel');
                        3) DESCARTA o buffer (não reusa a empresa/site no próximo
                           perfil — reusá-la bloquearia os próximos + cruzaria dados).
                        Idempotente."""
                        nonlocal _token_gasto, _token_estornado, _empresa_bloqueada_descartada
                        if _empresa_bloqueada_descartada:
                            return
                        _empresa_bloqueada_descartada = True
                        # 1) Estorna o token do site deste perfil.
                        _estornar_token_se_preciso(f'BM bloqueada: {_motivo}')
                        # 2) Queima a empresa no estoque (nunca reusar em novos perfis).
                        try:
                            _cnpj_burn = (_empresa_dados_cache or {}).get('cnpj', '')
                            if _TEM_ACESSO and _cnpj_burn:
                                _rb = marcar_empresa_usada(
                                    _cnpj_burn, f'BM bloqueada: {_motivo}'[:120])
                                logger.info('[Empresa] CNPJ %s marcado USADO por bloqueio '
                                            '(sucesso=%s afetadas=%s)', _cnpj_burn,
                                            _rb.get('sucesso'), _rb.get('afetadas'))
                        except Exception as _be:
                            logger.warning('[Empresa] falha ao marcar empresa usada '
                                           '(bloqueio): %s', _be)
                        # 3) Descarta o buffer — empresa/site bloqueado não se reusa.
                        if _estado.get('empresa_buffer'):
                            logger.info('[EmpresaBuffer] DESCARTADO por bloqueio '
                                        '(não reusar): %s', _motivo)
                        _estado['empresa_buffer'] = None

                    def _reter_ou_estornar(_motivo=''):
                        """Falha de ENTREGA (verificação não concluída SEM bloqueio),
                        mas o SITE continua válido para reuso. Se ainda há perfis na
                        fila, RETÉM o site no buffer carregando o token em hold (NÃO
                        estorna agora — evita criar/desperdiçar outro site e reusa o
                        token no próximo perfil até uma BM ser verificada). Se NÃO há
                        próximo perfil (ou o run foi cancelado), estorna agora.

                        IMPORTANTE: se a empresa foi DESCARTADA por bloqueio, NUNCA
                        retém (ela está queimada) — apenas garante o estorno."""
                        nonlocal _token_gasto, _token_estornado
                        if _empresa_bloqueada_descartada:
                            # Empresa queimada por bloqueio — não reter, só estornar.
                            _estornar_token_se_preciso(_motivo)
                            return
                        tem_proximo = ((i < len(_estado.get('perfis', [])) - 1)
                                       and not _estado.get('cancelar')
                                       and not _estado.get('_buffer_off'))
                        site_valido = bool(_site_cache and _site_cache.get('site_id'))
                        if tem_proximo and site_valido:
                            _empresa_buffer_reter(_empresa_dados_cache, _site_cache,
                                                  _nome_bm_override, _seu_nome_override,
                                                  token_held=_token_gasto)
                            # O token agora é responsabilidade do BUFFER — este perfil
                            # não estorna (senão estornaria + redebitaria no próximo).
                            _token_gasto = False
                            logger.info('[Token] Site retido p/ reuso no próximo perfil '
                                        '(token em hold): %s', _motivo)
                        else:
                            _estornar_token_se_preciso(_motivo)

                    def _cobrar_coins_uso(_motivo=''):
                        """Debita os COINS de USO do método atual (cobrado só no
                        marco de SUCESSO/entrega). O token do site é à parte. Uso
                        livre (admin/alexandre06) não é cobrado."""
                        if not _TEM_ACESSO:
                            return
                        if usuario_uso_livre():
                            logger.info('[Coins] Uso livre — %s coins NÃO debitados (perfil %s, %s).',
                                        COINS_POR_METODO.get(_fluxo_bm, 0), profile_id, _fluxo_bm)
                            return
                        _q = COINS_POR_METODO.get(_fluxo_bm, 0)
                        if _q <= 0:
                            return
                        try:
                            _r = debitar_coins(_q, f'Uso {_fluxo_bm} ({_q} coins): {_motivo}'[:120])
                            if _r.get('sucesso'):
                                try:
                                    _estado['progresso'][i]['coin_debitado'] = True
                                except Exception:
                                    pass
                                logger.info('[Coins] %s coins debitados (perfil %s, %s). Saldo: %s',
                                            _q, profile_id, _fluxo_bm, _r.get('coins', '?'))
                            else:
                                logger.warning('[Coins] Falha ao debitar %s coins (perfil %s): %s',
                                               _q, profile_id, _r.get('mensagem', ''))
                        except Exception as _ce:
                            logger.warning('[Coins] Erro ao debitar coins (perfil %s): %s',
                                           profile_id, _ce)

                    # Empresa/site sempre são preparados (o Turbo verifica a BM).
                    precisa_empresa = True
                    logger.info(
                        "[Fluxo] perfil %s | verificar_bm=%r precisa_empresa=%s "
                        "_TEM_VERIFICACAO=%s _TEM_ACESSO=%s tipo_empresa=%r",
                        i + 1, _fluxo_bm, precisa_empresa, _TEM_VERIFICACAO,
                        _TEM_ACESSO, _estado.get('tipo_empresa', 'mei'),
                    )
                    def _preparar_empresa_site(criar_site_agora=True):
                        """Gera (ou reusa) a empresa e, se `criar_site_agora`, TAMBÉM o site.

                        `criar_site_agora=True` (default, fluxos que deferem TUDO via callback
                        — sem_waba/gs_prime_plus): busca empresa + CRIA o site + debita token.
                        `criar_site_agora=False` (2026-07-25, demais fluxos completos): só
                        escolhe a empresa e monta o cache + nome da BM a partir do ESTOQUE
                        (buscar_empresas_ativas) — SEM criar o site nem debitar token. O site
                        é criado depois por `_criar_site_diferido()`, no passo do domínio, só
                        quando a BM nasce SEM restrição — evita desperdiçar domínio/subdomínio.
                        Retorna {empresa_dados, site_id, site_url} (site vazio quando diferido).
                        Levanta RuntimeError se não conseguir preparar (o chamador trata)."""
                        nonlocal _empresa_dados_cache, _site_cache, _nome_bm_override
                        nonlocal _seu_nome_override, _token_gasto
                        # Reaproveitar empresa+site do perfil anterior se valido —
                        # evita gastar outro token quando o perfil anterior falhou
                        # antes de criar a BM.
                        if _empresa_buffer_valido():
                            buf = _estado['empresa_buffer']
                            _empresa_dados_cache = dict(buf['empresa_dados'])
                            _site_cache = dict(buf['site_cache'])
                            _nome_bm_override = buf.get('nome_bm_override', '')
                            _seu_nome_override = buf.get('seu_nome_override', '')
                            # Este perfil REUSA o site ja pago: assume o token em
                            # hold (vira definitivo se a verificacao concluir aqui).
                            _token_gasto = bool(buf.get('token_held'))
                            _atualizar_progresso(
                                i, 'Processando', '#F2C94C',
                                f"♻️ Reusando empresa do perfil anterior: "
                                f"{_nome_bm_override[:40]} (tent. {buf.get('tentativas', 1)})"
                            )
                            logger.info(
                                "[EmpresaBuffer] reuso (tentativas=%s, site=%s)",
                                buf.get('tentativas'), _site_cache.get('url', ''),
                            )
                        else:
                            try:
                                tipo_emp = _estado.get('tipo_empresa', 'mei')

                                # 1) Buscar empresa na Fábrica
                                _atualizar_progresso(i, 'Processando', '#F2C94C',
                                                     f'🏢 Buscando empresa {tipo_emp.upper()} disponível...')
                                res_emp = buscar_empresas_ativas(tipo=tipo_emp)
                                if not res_emp.get('sucesso') or not res_emp.get('empresas'):
                                    _api_msg = str(res_emp.get('mensagem', '') or '')
                                    if res_emp.get('estoque_vazio'):
                                        _causa = f"Sem empresas {tipo_emp.upper()} no estoque do painel"
                                    elif res_emp.get('timeout'):
                                        _causa = ("API de empresas demorou demais (timeout) — "
                                                  "servidor lento. Tente novamente.")
                                    else:
                                        _causa = (f"Falha ao buscar empresa {tipo_emp.upper()}: "
                                                  f"{_api_msg[:80] or 'sem resposta'}")
                                    raise RuntimeError(_causa)
                                # 2) Criar site para a empresa. O site É criado com
                                # sucesso e o token é debitado (server-side) já no
                                # 1º CNPJ que funcionar. Só tentamos a PRÓXIMA empresa
                                # quando a criação FALHA de verdade (Cloudflare/API),
                                # caso em que NENHUM token foi cobrado. NUNCA tentamos
                                # outra empresa após um sucesso (evita debitar 2 tokens).
                                _empresas_estoque = res_emp.get('empresas') or []
                                res_site = None
                                empresa_raw = None
                                _ult_motivo = ''
                                for _idx_emp, _emp in enumerate(_empresas_estoque[:6]):
                                    _cnpj_emp = _emp.get('cnpj', '')
                                    if not _cnpj_emp:
                                        continue
                                    if not criar_site_agora:
                                        # SITE DIFERIDO: escolhe a empresa (p/ o NOME da BM)
                                        # SEM criar o site nem debitar token agora. O site é
                                        # criado depois (_criar_site_diferido), no passo do
                                        # domínio, só quando a BM nasce sem restrição.
                                        empresa_raw = _emp
                                        res_site = {}
                                        break
                                    _atualizar_progresso(i, 'Processando', '#F2C94C',
                                        f'🌐 Criando site da empresa (1 token)... '
                                        f'[tentativa {_idx_emp + 1}]')
                                    try:
                                        _r = criar_site_empresa(
                                            _cnpj_emp,
                                            callback_status=lambda m, _i=i: _atualizar_progresso(
                                                _i, 'Processando', '#F2C94C', m),
                                            deve_continuar=lambda: not _estado.get('cancelar', False))
                                    except Exception as _ce:
                                        _ult_motivo = f'exceção: {_ce}'
                                        logger.warning("[Verificação] Exceção criar_site (CNPJ %s): %s",
                                                       _cnpj_emp, _ce)
                                        continue
                                    if _r.get('sucesso'):
                                        res_site = _r
                                        empresa_raw = _emp
                                        if _r.get('endereco_incompleto'):
                                            logger.warning("[Verificação] Site criado com endereço incompleto "
                                                           "(CNPJ %s) — bot decidirá verificar/estornar.", _cnpj_emp)
                                        break
                                    # Falha real (Cloudflare/API) -> sem token cobrado -> próxima empresa.
                                    _ult_motivo = str(_r.get('mensagem', '') or 'sem resposta')
                                    logger.warning("[Verificação] Falha criar site (CNPJ %s): %s",
                                                   _cnpj_emp, _ult_motivo[:160])
                                    _atualizar_progresso(i, 'Processando', '#FF8800',
                                        f'⚠️ Falha ao criar site ({_ult_motivo[:50]}) — próxima empresa')

                                if criar_site_agora:
                                    if not res_site or not res_site.get('sucesso'):
                                        raise RuntimeError(
                                            f"Não foi possível criar o site no painel. "
                                            f"Último erro: {_ult_motivo[:120] or 'sem resposta da API'}")
                                    # Site criado com sucesso => 1 token foi debitado
                                    # (server-side). A partir daqui o token fica "em
                                    # hold" ate sabermos se a entrega teve sucesso.
                                    _token_gasto = True
                                    # Usar dados da empresa retornados pelo criar_site (já completos)
                                    empresa_api = res_site.get('empresa', {})
                                    _site_cache = {
                                        'site_id': res_site['site_id'],
                                        'url': res_site['url'],
                                        'subdominio': res_site.get('subdominio', ''),
                                        'dominio_raiz': res_site.get('dominio_raiz', ''),
                                        # E-MAIL PRÓPRIO DO SITE (2026-07-31): o PAINEL já cria a
                                        # conta no gsmails junto com o site e agora a devolve aqui.
                                        # O bot NÃO cria e-mail nenhum — só usa esta. (A blindagem
                                        # do gsmails só permite o 1º e-mail do subdomínio, e quem
                                        # o criou foi o painel.)
                                        'email': str(res_site.get('email', '') or ''),
                                        'email_senha': str(res_site.get('email_senha', '') or ''),
                                        'email_servidor': str(res_site.get('email_servidor', '') or ''),
                                    }
                                    # (2026-08-10) O perfil NÃO é mais abortado quando o site vem
                                    # sem e-mail próprio: a BM passou a usar as RAÍZES PÚBLICAS do
                                    # gsmails (fulano@raiz.com), então o e-mail do subdomínio virou
                                    # opcional — serve só ao bloco "Contato" do microsite. Abortar
                                    # aqui hoje derrubaria perfil bom por um dado que o fluxo não
                                    # usa mais. Fica o aviso no log para o e-mail do site não
                                    # parar de ser criado sem ninguém perceber.
                                    if not _site_cache['email']:
                                        logger.warning(
                                            '[Site] %s nasceu sem e-mail próprio (raiz %s). A BM '
                                            'segue com a raiz pública do gsmails.',
                                            _site_cache.get('url', '?'),
                                            _site_cache.get('dominio_raiz', '?'))
                                else:
                                    # SITE DIFERIDO: nenhuma empresa válida achada? aborta.
                                    if not empresa_raw:
                                        raise RuntimeError(
                                            'Estoque sem empresa com CNPJ/razão válidos para a BM.')
                                    empresa_api = {}       # sem dados do criar_site ainda
                                    _site_cache = None     # site criado depois (domínio)
                                    _token_gasto = False   # token só quando o site nascer

                                # Helper: Title Case (Meta não aceita MAIÚSCULO)
                                def _title_case(texto):
                                    if not texto:
                                        return ''
                                    preps = {'da', 'de', 'do', 'das', 'dos', 'e', 'em',
                                             'na', 'no', 'para', 'por', 'com'}
                                    partes = texto.strip().split()
                                    saida = []
                                    for idx, p in enumerate(partes):
                                        if idx > 0 and p.lower() in preps:
                                            saida.append(p.lower())
                                        else:
                                            # .title() (não .capitalize()) p/ '2559SW' -> '2559Sw'
                                            saida.append(p.title())
                                    return ' '.join(saida)

                                import re as _re
                                def _limpar_cnpj_prefixo(texto):
                                    """Remove blocos de dígitos/pontuação de CNPJ no INÍCIO e no
                                    FIM da razão social (ex.: '123456 Empresa Tal' ou
                                    'Empresa Tal 123456' → 'Empresa Tal'). Dígitos nas pontas são
                                    fragmentos de CNPJ e quebram a criação na Meta/Gupshup —
                                    descartamos, mantendo só o nome. (Números no MEIO do nome,
                                    ex.: 'Loja 24 Horas', são preservados.)"""
                                    if not texto:
                                        return ''
                                    t = str(texto)
                                    t = _re.sub(r'^[\s\d.\-/]+', '', t)   # início
                                    t = _re.sub(r'[\s\d.\-/]+$', '', t)   # fim
                                    return t.strip()

                                _empresa_dados_cache = {
                                    'razao_social': _title_case(_limpar_cnpj_prefixo(
                                        empresa_api.get('razao_social') or empresa_raw.get('razao_social') or '')),
                                    'nome_fantasia': _title_case(_limpar_cnpj_prefixo(
                                        empresa_api.get('nome_fantasia') or empresa_raw.get('nome_fantasia') or '')),
                                    'cnpj': empresa_api.get('cnpj') or empresa_raw.get('cnpj') or '',
                                    'logradouro': _title_case(
                                        empresa_api.get('logradouro') or empresa_raw.get('logradouro') or ''),
                                    'numero': _title_case(
                                        empresa_api.get('numero') or empresa_raw.get('numero') or ''),
                                    'complemento': _title_case(
                                        empresa_api.get('complemento') or empresa_raw.get('complemento') or ''),
                                    'bairro': _title_case(
                                        empresa_api.get('bairro') or empresa_raw.get('bairro') or ''),
                                    'municipio': _title_case(
                                        empresa_api.get('municipio') or empresa_raw.get('municipio') or ''),
                                    'uf': (empresa_api.get('uf') or empresa_raw.get('uf') or '').upper(),
                                    'cep': empresa_api.get('cep') or empresa_raw.get('cep') or '',
                                    'url_completa': empresa_api.get('url_completa') or res_site.get('url') or '',
                                    'telefone': empresa_api.get('telefone') or empresa_raw.get('telefone') or '',
                                    'atividade': _title_case(
                                        empresa_api.get('atividade') or empresa_raw.get('atividade') or ''),
                                    'categoria': empresa_api.get('categoria') or empresa_raw.get('categoria') or '',
                                }

                                if _site_cache and not _empresa_dados_cache.get('logradouro', '').strip():
                                    # (site DIFERIDO ainda não existe → _site_cache é None;
                                    #  o endereço vem do estoco/buscar e é enriquecido depois,
                                    #  em _criar_site_diferido, após criar o site.)
                                    logger.warning("[Verificação] Logradouro vazio na API externa — "
                                                   "buscando dados do site no banco...")
                                    try:
                                        _site_id = _site_cache.get('site_id')
                                        if _site_id:
                                            res_detalhes = obter_detalhes_site(_site_id)
                                            if res_detalhes.get('sucesso'):
                                                _emp_db = res_detalhes.get('empresa', {})
                                                _campos_endereco = [
                                                    'logradouro', 'numero', 'complemento',
                                                    'bairro', 'municipio', 'uf', 'cep',
                                                    'telefone',
                                                ]
                                                for _campo in _campos_endereco:
                                                    if (not _empresa_dados_cache.get(_campo, '').strip()
                                                            and _emp_db.get(_campo, '').strip()):
                                                        _val = _emp_db[_campo].strip()
                                                        if _campo in ('logradouro', 'complemento',
                                                                      'bairro', 'municipio'):
                                                            _val = _title_case(_val)
                                                        elif _campo == 'uf':
                                                            _val = _val.upper()
                                                        _empresa_dados_cache[_campo] = _val
                                    except Exception as _db_err:
                                        logger.warning("[Verificação] Erro ao buscar detalhes: %s", _db_err)

                                from server.verificacao_bm import gerar_nome_bm_abreviado
                                _raw_name = (_empresa_dados_cache['razao_social']
                                             or _empresa_dados_cache['nome_fantasia'])
                                _nomes_abreviados = gerar_nome_bm_abreviado(_raw_name)
                                import re as _re_bm
                                _sufixos_bm = r'\b(LTDA|ME|MEI|EIRELI|EPP|S/?A|S\.A\.)\b'
                                _nome_bm_override = _re_bm.sub(_sufixos_bm, '', _raw_name,
                                                               flags=_re_bm.IGNORECASE).strip()
                                _nome_bm_override = _re_bm.sub(r'[\s\-]+$', '', _nome_bm_override).strip()
                                _nome_bm_override = _re_bm.sub(r'\s{2,}', ' ', _nome_bm_override).strip()
                                if not _nome_bm_override:
                                    _nome_bm_override = _raw_name
                                _seu_nome_override = (_nomes_abreviados[0]
                                                      if _nomes_abreviados else _nome_bm_override)
                                _empresa_dados_cache['_nomes_bm_fallback'] = _nomes_abreviados
                                logger.info("[Verificação] Empresa preparada: BM='%s' | Site: %s",
                                            _nome_bm_override,
                                            (_site_cache or {}).get('url', '(site diferido — criado no passo do domínio)'))

                                _atualizar_progresso(i, 'Processando', '#F2C94C',
                                                     f'🏢 Empresa pronta: {_nome_bm_override[:40]}')
                            except Exception as pre_err:
                                logger.error("Erro ao preparar empresa/site: %s", pre_err, exc_info=True)
                                _pre_erro_msg = str(pre_err)[:80]
                                # FLUXO COMPLETO ('imediata'): a BM EXIGE dados REAIS de
                                # uma empresa com site gerado no painel. Se o site/empresa
                                # NÃO foi criado, NÃO abrimos o navegador nem criamos uma
                                # BM com dados fake — abortamos este perfil. O handler
                                # externo estorna o token (se algum foi cobrado), fecha o
                                # navegador e contabiliza o erro. (Este bloco só executa
                                # quando _fluxo_bm == 'imediata', então NUNCA degradamos
                                # para o fluxo fake 'nao'.)
                                _atualizar_progresso(i, 'Erro', '#FF4444',
                                    f'❌ Empresa/site não criada — perfil pulado (sem BM fake): {_pre_erro_msg}')
                                logger.warning(
                                    "[Fluxo imediata] Perfil %s ABORTADO: site/empresa não "
                                    "criada (%s). NÃO criando BM fake.", profile_id, _pre_erro_msg)
                                raise RuntimeError(
                                    f'Fluxo completo abortado — empresa/site não criada: {_pre_erro_msg}')
                        return {
                            'empresa_dados': _empresa_dados_cache,
                            'site_id': (_site_cache or {}).get('site_id', ''),
                            'site_url': (_site_cache or {}).get('url', ''),
                        }

                    # Subdomínio/raiz RESERVADOS p/ o e-mail da BM (preenchido antes da
                    # automação quando o modo é subdomínio). O site diferido usa os MESMOS.
                    _reserva_sub = {'sub': '', 'raiz': ''}

                    def _criar_site_diferido():
                        """Cria o SITE (subdomínio) da empresa JÁ escolhida por
                        _preparar_empresa_site(criar_site_agora=False). Chamado só DEPOIS que
                        a BM nasce SEM restrição (no passo do domínio) — evita gastar
                        domínio/subdomínio em BM que bloqueia na criação / perfil que não
                        loga. Debita 1 token (server-side). No-op se o site já existe (reuso
                        de buffer). Enriquece _empresa_dados_cache com a URL + endereço
                        faltante. Levanta RuntimeError se não conseguir criar (o chamador
                        aborta a verificação). Retorna {empresa_dados, site_id, site_url}."""
                        nonlocal _site_cache, _empresa_dados_cache, _token_gasto
                        # Já tem site (reuso de buffer do perfil anterior) → nada a fazer.
                        if _site_cache and _site_cache.get('site_id'):
                            return {
                                'empresa_dados': _empresa_dados_cache,
                                'site_id': _site_cache.get('site_id', ''),
                                'site_url': _site_cache.get('url', ''),
                            }
                        _cnpj = str((_empresa_dados_cache or {}).get('cnpj', '') or '').strip()
                        if not _cnpj:
                            raise RuntimeError('Empresa não preparada (sem CNPJ) — não dá p/ criar o site.')
                        # Cria o site do CNPJ ESCOLHIDO (mesma razão social da BM). Falha de
                        # criação é de domínio/API (independe do CNPJ) → retry transitório.
                        res_site = {}
                        _ult = ''
                        for _try in range(1, 4):
                            _atualizar_progresso(i, 'Processando', '#F2C94C',
                                f'🌐 Criando site da empresa (1 token) [tentativa {_try}/3]...')
                            try:
                                _r = criar_site_empresa(
                                    _cnpj,
                                    callback_status=lambda m, _i=i: _atualizar_progresso(
                                        _i, 'Processando', '#F2C94C', m),
                                    deve_continuar=lambda: not _estado.get('cancelar', False),
                                    # Mesmo subdomínio/raiz reservados p/ o e-mail da BM → e-mail = site.
                                    subdominio=_reserva_sub.get('sub', ''),
                                    dominio_raiz=_reserva_sub.get('raiz', ''))
                            except Exception as _ce:
                                _ult = f'exceção: {_ce}'
                                logger.warning("[SiteDiferido] Exceção criar_site (CNPJ %s): %s", _cnpj, _ce)
                                time.sleep(min(8, 2 + _try * 2))
                                continue
                            if _r.get('sucesso'):
                                res_site = _r
                                break
                            _ult = str(_r.get('mensagem', '') or 'sem resposta')
                            logger.warning("[SiteDiferido] Falha criar site (CNPJ %s): %s", _cnpj, _ult[:160])
                            time.sleep(min(8, 2 + _try * 2))
                        if not res_site or not res_site.get('sucesso'):
                            raise RuntimeError(
                                f"Não foi possível criar o site no painel (site diferido). "
                                f"Último erro: {_ult[:120] or 'sem resposta da API'}")
                        _token_gasto = True  # token debitado (server-side) — fica em hold
                        _site_cache = {
                            'site_id': res_site['site_id'],
                            'url': res_site['url'],
                            'subdominio': res_site.get('subdominio', ''),
                            'dominio_raiz': res_site.get('dominio_raiz', ''),
                            # E-mail próprio do site, criado pelo PAINEL junto com o site.
                            'email': str(res_site.get('email', '') or ''),
                            'email_senha': str(res_site.get('email_senha', '') or ''),
                            'email_servidor': str(res_site.get('email_servidor', '') or ''),
                        }
                        # Enriquece o cache: URL + endereço/telefone faltante (do criar_site
                        # e, se preciso, do banco via obter_detalhes_site — igual ao antigo).
                        _emp_api = res_site.get('empresa', {}) or {}
                        if _empresa_dados_cache is not None:
                            _empresa_dados_cache['url_completa'] = (
                                res_site.get('url') or _empresa_dados_cache.get('url_completa', ''))
                            for _k in ('logradouro', 'numero', 'complemento', 'bairro',
                                       'municipio', 'uf', 'cep', 'telefone', 'atividade'):
                                if (not str(_empresa_dados_cache.get(_k, '') or '').strip()
                                        and str(_emp_api.get(_k, '') or '').strip()):
                                    _empresa_dados_cache[_k] = _emp_api.get(_k)
                            if not str(_empresa_dados_cache.get('logradouro', '') or '').strip():
                                try:
                                    _det = obter_detalhes_site(_site_cache['site_id'])
                                    if _det.get('sucesso'):
                                        _emp_db = _det.get('empresa', {}) or {}
                                        for _campo in ('logradouro', 'numero', 'complemento',
                                                       'bairro', 'municipio', 'uf', 'cep', 'telefone'):
                                            if (not str(_empresa_dados_cache.get(_campo, '') or '').strip()
                                                    and str(_emp_db.get(_campo, '') or '').strip()):
                                                _empresa_dados_cache[_campo] = _emp_db[_campo].strip()
                                except Exception as _dberr:
                                    logger.warning("[SiteDiferido] obter_detalhes_site falhou: %s", _dberr)
                        logger.info("[SiteDiferido] Site criado (CNPJ %s): %s",
                                    _cnpj, _site_cache.get('url', ''))
                        return {
                            'empresa_dados': _empresa_dados_cache,
                            'site_id': _site_cache.get('site_id', ''),
                            'site_url': _site_cache.get('url', ''),
                        }

                    if precisa_empresa and _TEM_VERIFICACAO and _TEM_ACESSO:
                        # SITE NO INÍCIO (2026-07-31 — REVERTE o diferimento da v1.30):
                        # empresa + SITE são criados AGORA, ANTES do navegador, porque o
                        # E-MAIL da BM precisa nascer no domínio do PRÓPRIO site
                        # (contato@razaosocial.raiz.com) e o e-mail é criado lá dentro de
                        # executar_automacao_perfil, durante a criação da BM.
                        #
                        # Isto é SEGURO quanto ao limite X/30 do domínio-raiz: o painel só
                        # incrementa o contador em salvar_meta_tags (idempotente pela coluna
                        # tb_sites_empresariais.dominio_contado). BM que bloqueia ANTES de
                        # validar o domínio NÃO consome a cota da raiz. E o token do site
                        # não se perde: _reter_ou_estornar retém empresa+site no buffer para
                        # o PRÓXIMO perfil da fila (token em hold), ou estorna se não houver.
                        _preparar_empresa_site(criar_site_agora=True)

                    # Modo entrega — tenta ate 2 BMs no mesmo perfil (retry) e para
                    # no 1o sucesso.
                    _entrega = True
                    _qtd_efetiva = max(2, qtd_bm) if _entrega else qtd_bm

                    # Exibição: oculto (headless) ou janela posicionada na GRADE
                    # (organização lado a lado quando há vários simultâneos).
                    # No modo ROLLING (sem 4G) o slot é FIXO por worker (cell_idx) →
                    # o novo perfil nasce no MESMO lugar da grade do que fechou.
                    # Nos demais modos, cai no cálculo por índice (i % _simultaneos).
                    if _grade_cells:
                        _slot = cell_idx if (cell_idx is not None) else (i % _simultaneos)
                        _cell = _grade_cells[_slot % len(_grade_cells)]
                    else:
                        _cell = None

                    def _abrir_wrap(_pid, _hl=_oculto, _cl=_cell):
                        try:
                            return mod.abrir_navegador(_pid, headless=_hl, janela=_cl)
                        except TypeError:
                            # Módulo de browser antigo (sem parâmetro 'janela').
                            return mod.abrir_navegador(_pid, headless=_hl)

                    # ── E-MAIL DE SUBDOMÍNIO: reserva o subdomínio (raiz + nome da
                    #    empresa) p/ o e-mail da BM nascer EXATAMENTE no subdomínio do
                    #    site, SEM criar site/token. O site diferido usa o MESMO
                    #    (via _reserva_sub → _criar_site_diferido). Só no modo != 'raiz'
                    #    e quando ainda não há site. GSMAILS aceita qualquer subdomínio
                    #    de raiz wildcard.
                    #    ⚠️ FIX 2026-09-10: a reserva TAMBÉM roda p/ fluxos DEFERIDOS
                    #    (pro_max_sem_waba) — são justamente os que ainda não têm site e
                    #    mais precisam do host antecipado; antes o gate `not defere` os
                    #    pulava e o e-mail caía no apex/público (cruzando a raiz).
                    _site_host_arg = (_site_cache or {}).get('url', '')
                    if (not _site_host_arg):
                        try:
                            from server.acesso import email_modo_geracao as _emg
                            _modo_bm = _emg()
                        except Exception:
                            _modo_bm = 'subdominio'
                        if _modo_bm != 'raiz':
                            _cnpj_bm = str((_empresa_dados_cache or {}).get('cnpj', '') or '').strip()
                            if _cnpj_bm:
                                try:
                                    _rv = reservar_subdominio(_cnpj_bm)
                                    if _rv and _rv.get('host'):
                                        _site_host_arg = _rv['host']
                                        _reserva_sub['sub'] = _rv.get('subdominio', '')
                                        _reserva_sub['raiz'] = _rv.get('dominio_raiz', '')
                                        logger.info("[E-mail subdomínio] reservado %s p/ a BM (perfil %s).",
                                                    _site_host_arg, profile_id)
                                except Exception as _er:
                                    logger.warning("[E-mail subdomínio] reserva falhou: %s", _er)

                    res_automacao = executar_automacao_perfil(
                        profile_id=profile_id,
                        perfil_data=perfil,
                        abrir_navegador_func=_abrir_wrap,
                        fechar_navegador_func=mod.fechar_navegador,
                        adicionar_tags_func=mod.adicionar_tags_perfil,
                        anexar_notas_func=getattr(mod, 'anexar_notas_perfil', None),
                        callback_status=lambda msg: _atualizar_progresso(i, 'Processando', '#F2C94C', msg),
                        qtd_bm=_qtd_efetiva,
                        captcha_api_key=_estado.get('captcha_token', ''),
                        # Anti-cascata: serializa a ENTRADA na criação de BM entre
                        # abas que dividem o mesmo IP (self-gate: só atua quando
                        # _estado['_ip_compartilhado'] é True).
                        gate_criacao=_gate_criacao_mesmo_ip,
                        # Fluxo 'imediata' (completo): MANTÉM o navegador aberto após
                        # criar a BM/validar email para a verificação de empresa+domínio
                        # rodar NA MESMA sessão (a automação devolve o driver vivo).
                        # Sem isto o navegador fechava, res_automacao['driver'] vinha
                        # None e a verificação quebrava com "'NoneType' object has no
                        # attribute 'goto'". Fluxo 'nao': fecha normalmente.
                        skip_close=_entrega,
                        nome_bm_override=_nome_bm_override,
                        seu_nome_override=_seu_nome_override,
                        parar_no_primeiro_sucesso=_entrega,
                        # E-MAIL NO DOMÍNIO DO SITE (2026-07-31): o site já existe aqui
                        # (criado logo acima), então o e-mail da BM nasce em
                        # contato@<subdominio da empresa>. Fluxos que DEFEREM empresa/site
                        # (pro_max_sem_waba) ainda não têm site → vai vazio e o e-mail cai
                        # no domínio público (gspromax.com), como antes.
                        site_host=_site_host_arg,
                        empresa_razao=(_empresa_dados_cache or {}).get('razao_social', ''),
                        # E-mail PRÓPRIO do site, já criado pelo painel. A BM nasce
                        # com ele — o bot não cria e-mail nenhum.
                        email_pre={'address': (_site_cache or {}).get('email', ''),
                                   'password': (_site_cache or {}).get('email_senha', '')},
                    )

                    if res_automacao.get('navegador_fechado'):
                        # Navegador foi FECHADO (usuário na mão / queda) durante a
                        # automação → Erro/Falha limpo e segue para o próximo perfil.
                        _inc('erros')
                        _atualizar_progresso(i, 'Erro', '#FF4444',
                            f"❌ {res_automacao.get('mensagem', 'Navegador foi fechado.')}")
                        if _cooldown is not None:
                            try:
                                _cooldown.registrar_falha()
                            except Exception:
                                pass
                        _reter_ou_estornar('navegador fechado durante a automação')
                        try:
                            _drv_nf = res_automacao.get('driver')
                            if _drv_nf:
                                _drv_nf.quit()
                        except Exception:
                            pass
                        try:
                            mod.fechar_navegador(profile_id)
                        except Exception:
                            pass
                    elif res_automacao.get('logado'):
                        # Login/criação da BM OK — mas o SUCESSO só é contabilizado
                        # quando o FLUXO ESCOLHIDO conclui 100% (pontos de contagem
                        # abaixo). Para 'imediata'/'full' ainda faltam etapas
                        # (empresa+domínio / WABA), então aqui é só 'Processando'.
                        # business_id/bm_* inicializados AQUI (sempre definidos) —
                        # senão, com logado=True mas SEM bm_criada, o uso de
                        # business_id mais abaixo dava 'referenced before assignment'.
                        business_id = res_automacao.get('business_id', '') or ''
                        bm_name = res_automacao.get('bm_name', '')
                        bm_email = res_automacao.get('email_tmail', '')
                        status_msg = f"⏳ {res_automacao.get('mensagem', '')}"
                        _atualizar_progresso(i, 'Processando', '#F2C94C', status_msg)

                        # Sucesso — zerar contador de cooldown
                        if _cooldown is not None:
                            try:
                                _cooldown.registrar_sucesso()
                            except Exception:
                                pass

                        # ── Coin permanente: perfil processado com sucesso ──
                        login_ok = perfil.get('login', '')
                        if login_ok in _estado['perfis_cobrados']:
                            _estado['perfis_cobrados'][login_ok] = False

                        # Registrar BM via API web
                        if _TEM_ACESSO and res_automacao.get('bm_criada'):
                            bm_name = res_automacao.get('bm_name', '')
                            bm_email = res_automacao.get('email_tmail', '')
                            fb_login = perfil.get('login', '')
                            business_id = res_automacao.get('business_id', '')

                            if bm_email:
                                mod.atualizar_nome_perfil(profile_id, bm_email)

                            # Tags de status da BM
                            if res_automacao.get('bm_bloqueada'):
                                # BM criada mas bloqueada NA CRIAÇÃO: o domínio/site ainda
                                # NÃO foi adicionado ao perfil nem validado com a meta tag
                                # (a etapa de verificação nem começou) — ou seja, o site NÃO
                                # foi usado. Regra (2026-07-12): NÃO descartar; RETÉM a
                                # empresa/site p/ o PRÓXIMO perfil da fila (o bloqueio é do
                                # perfil/BM, não da empresa). Só estorna se não houver próximo
                                # perfil. O descarte definitivo (estorna + queima CNPJ) só
                                # acontece quando o domínio JÁ foi verificado (ver bloco da
                                # verificação, gated por dominio_verificado).
                                try:
                                    mod.adicionar_tags_perfil(profile_id, ["💔 BM BLOQUEADA 💔"])
                                except Exception:
                                    pass
                                # SITE NO INÍCIO (2026-07-31): o site JÁ existe, mas o domínio
                                # NÃO chegou a ser adicionado/validado na Meta — logo o painel
                                # NÃO contou o X/30 da raiz (só conta em salvar_meta_tags).
                                # _reter_ou_estornar RETÉM empresa+site (com o token em hold)
                                # p/ o PRÓXIMO perfil da fila, ou estorna se não houver próximo.
                                # Nada é desperdiçado: nem cota de domínio, nem token.
                                _reter_ou_estornar('BM bloqueada na criação (domínio não validado — cota intacta)')
                                logger.warning("[Perfil %s] BM bloqueada na criação — domínio NÃO validado; "
                                               "site retido p/ reuso (cota X/30 intacta)", profile_id)
                                _atualizar_progresso(i, 'Processando', '#FF8800',
                                    f"⚠️ BM 1 bloqueada na criação — domínio não validado (cota intacta); site reservado. Próximo perfil...")
                            else:
                                # BM criada sem bloqueio: empresa foi efetivamente
                                # consumida com sucesso, limpar buffer.
                                try:
                                    tag_list = ["💎 1 BM CRIADA 💎"]
                                    if bm_email:
                                        tag_list.insert(0, f"📧 {bm_email}")
                                    mod.adicionar_tags_perfil(profile_id, tag_list)
                                except Exception:
                                    pass
                                _empresa_buffer_consumir()

                            if not res_automacao.get('bm_bloqueada'):
                                res_reg = registrar_bm_criada(
                                    bm_name=bm_name,
                                    bm_email=bm_email,
                                    fb_login=fb_login,
                                    business_id=business_id,
                                    profile_id=str(profile_id),
                                    compra_id=compra_id,
                                )
                                # ── Custo do fluxo ──────────────────────────────────
                                # O USO da ferramenta é cobrado em COINS por método,
                                # SOMENTE no marco de SUCESSO/entrega (via
                                # _cobrar_coins_uso) — NÃO aqui na criação da BM. O
                                # token do site continua sendo debitado à parte
                                # (criar_site, server-side) nos fluxos que criam site.

                        # ══════════════════════════════════════════════════════
                        # FASE 1 CONCLUÍDA: BM criada + email validado
                        # Fluxo 'nao'       → apenas fecha o navegador.
                        # Fluxo 'imediata'  → verifica empresa + domínio agora,
                        #                     no mesmo navegador, antes de fechar.
                        # ══════════════════════════════════════════════════════
                        fluxo = _fluxo_bm
                        # E-MAIL best-effort (pedido do usuário 2026-07-07): NÃO trava o
                        # fluxo se o e-mail não confirmar em 60s. A confirmação é tentada
                        # dentro da verificação (preencher_info_empresa, 1 tentativa/60s,
                        # sem reenvio) e, se a WABA nascer desabilitada, o fluxo alternativo
                        # cria uma conta de anúncios e destrava a Central.
                        pode_verificar = (
                            fluxo == FLUXO_UNICO
                            and _TEM_VERIFICACAO
                            # EMPRESA já preparada; o SITE é criado no passo do domínio
                            # (_criar_site_diferido), então NÃO exigimos _site_cache aqui.
                            and _empresa_dados_cache
                            and not res_automacao.get('bm_bloqueada')
                            and business_id
                        )

                        if pode_verificar:
                            drv_verif = res_automacao.get('driver')
                            # Anexa o proxy DESTA aba ao driver: é assim que a
                            # verificação sabe QUAL proxy girar quando precisar de
                            # um IP novo no meio do fluxo (cada aba tem o seu
                            # MegaProxy/4G isolado, então a troca é local e não
                            # pausa as demais). Sem proxy com URL, fica None e o
                            # fluxo segue exatamente como antes.
                            try:
                                if drv_verif is not None and _proxy_da_aba:
                                    drv_verif._proxy = _proxy_da_aba
                            except Exception:
                                pass
                            verif_ok = False
                            verif_bloqueada = False
                            verif_queimada = False
                            verif_msg = ''
                            res_verif = {}   # default seguro (o descarte por checkpoint pode abortar antes da atribuição)
                            # Checkpoint DEAD-END (captcha de imagem) sobe como _PerfilQueimado
                            # (BaseException) — captura p/ DESCARTAR o perfil sem insistir.
                            try:
                                from server.etapa_verificacao_negocio import _PerfilQueimado
                            except Exception:
                                class _PerfilQueimado(BaseException):
                                    pass
                            try:
                                _atualizar_progresso(i, 'Processando', '#F2C94C',
                                    '🔎 Verificando empresa e domínio...')

                                # SITE DIFERIDO (2026-07-25): a BM nasceu SEM restrição (o gate
                                # pode_verificar exige not bm_bloqueada) → AGORA sim criamos o
                                # site (no passo do domínio, imediatamente antes de adicionar +
                                # validar o domínio com a meta tag). Só p/ fluxos NÃO-defer que
                                # ainda não têm site. Se falhar, propaga p/ o except (perfil vira
                                # erro; sem site não há domínio p/ validar). Assim não gastamos
                                # domínio/subdomínio em BM que bloqueou na criação.
                                if _fluxo_waba_antes_site and (_site_cache is None):
                                    # WABA-ANTES-DO-SITE: NÃO cria o site agora. Preenche a
                                    # empresa com um site PROVISÓRIO (pool BR). O site REAL é
                                    # gerado depois, SÓ se a WABA aprovar (via criar_site_func,
                                    # injetado nos kwargs abaixo).
                                    _site_prov = _site_provisorio_aleatorio()
                                    if _empresa_dados_cache is not None:
                                        _empresa_dados_cache['url_completa'] = _site_prov
                                    _atualizar_progresso(i, 'Processando', '#F2C94C',
                                        f'🌐 Site provisório "{_site_prov}" — criando a WABA ANTES do site real...')
                                elif _site_cache is None:
                                    _criar_site_diferido()

                                from server.gerar_numero import gerar_numero_aleatorio
                                from server.verificacao_bm import _gerar_variantes_telefone

                                numero_gerado = gerar_numero_aleatorio()
                                numero_sms = f'+{numero_gerado}'
                                # A empresa gerada já traz telefone; o negócio troca pelo
                                # número REAL do SMS.
                                if _empresa_dados_cache is not None:
                                    _empresa_dados_cache['telefone'] = numero_sms
                                variantes_tel = _gerar_variantes_telefone(numero_sms)

                                drv_verif.goto(
                                    f"https://business.facebook.com/latest/settings/"
                                    f"business_info?business_id={business_id}"
                                )
                                # Aguardar a página de "Informações da empresa" carregar
                                # 100% e ficar estática (em vez de um sleep fixo, que
                                # falha no 4G lento). F5 automático se travar.
                                try:
                                    from server.page_state_manager import PageStateManager
                                    PageStateManager.wait_until_stable(
                                        drv_verif, timeout=40, settle_time=1.5,
                                        f5_after=25, callback_status=None)
                                except Exception:
                                    time.sleep(5)
                                time.sleep(1)

                                def _cb_verif(msg, _i=i):
                                    _atualizar_progresso(_i, 'Processando', '#F2C94C', msg)

                                # Turbo: base + domínio + WABA (OAuth Meta direto) + análise.
                                _func_verif = executar_verificacao_completo_datacrazy_pro_max
                                _kwargs_verif = dict(
                                    driver=drv_verif,
                                    business_id=business_id,
                                    empresa_dados=_empresa_dados_cache,
                                    site_id=(_site_cache or {}).get('site_id', ''),
                                    site_url=(_site_cache or {}).get('url', ''),
                                    numero_telefone=numero_sms,
                                    salvar_meta_func=salvar_meta_tags_site,
                                    callback_status=_cb_verif,
                                    variantes_telefone=variantes_tel,
                                    # senha do perfil p/ reauth no OAuth da Meta
                                    senha_fb=perfil.get('senha', ''),
                                )
                                # ⭐ WABA-ANTES-DO-SITE (gated): o site real NÃO existe
                                # ainda (será gerado só se a WABA aprovar). Passa o CALLBACK que
                                # cria o site real sob demanda + garante o site PROVISÓRIO no
                                # campo Site (site_url) p/ a criação da WABA.
                                if _fluxo_waba_antes_site:
                                    _kwargs_verif['criar_site_func'] = _criar_site_diferido
                                    _kwargs_verif['waba_antes_site'] = True
                                    _kwargs_verif['site_url'] = (
                                        (_empresa_dados_cache or {}).get('url_completa', '')
                                        or _kwargs_verif.get('site_url', ''))
                                # Pro Max: precisa do token do CapSolver (captcha), do tipo
                                # da empresa (MEI -> Empresa individual / LTDA -> Empresa
                                # privada) e do token de SMS (compra do número) na
                                # verificação de negócio.
                                _kwargs_verif['captcha_token'] = _estado.get('captcha_token', '')
                                _kwargs_verif['tipo_empresa'] = _estado.get('tipo_empresa', 'mei')
                                _kwargs_verif['sms24h_token'] = _estado.get('sms24h_token', '')
                                # Provedor de SMS escolhido pelo usuário na GUI
                                # (sms24h / Grizzly / Tiger — mesmo protocolo).
                                _kwargs_verif['sms_provedor'] = _estado.get(
                                    'sms_provedor', 'sms24h')
                                # Credenciais p/ RE-LOGIN automático se a sessão cair
                                # ao navegar no business.facebook.com durante a análise.
                                _kwargs_verif['fb_login'] = perfil.get('login', '')
                                _kwargs_verif['fb_tfa'] = perfil.get('tfa', '')
                                # E-mail da BM p/ deixar o SITE coerente (número real
                                # + email da BM) quando comprar o número na Central.
                                _kwargs_verif['bm_email'] = bm_email or ''

                                # BLINDAGEM (2026-08-02): descarta kwargs que a função
                                # de verificação escolhida NÃO aceita.
                                # Incidente que motivou: o seletor de provedor de SMS
                                # passou a mandar `sms_provedor`, mas as 5 funções
                                # `executar_verificacao_*` do Pro Max não tinham o
                                # parâmetro → TypeError em TODO perfil, 0 sucesso e
                                # 100% de erro numa run inteira. Um kwarg novo jamais
                                # deve derrubar a run: avisamos no log e seguimos.
                                _kwargs_verif = _sanear_kwargs_verif(
                                    _func_verif, _kwargs_verif, _cb_verif)

                                if res_automacao.get('bm_ja_existia'):
                                    # ⭐ BM JÁ EXISTIA no perfil: NÃO recria do zero nem
                                    # espera e-mail — RETOMA pelo status (domínio →
                                    # restrição → WABA/Central → análise). Se restrita,
                                    # cria 1 BM nova; se a nova também restringir, exclui
                                    # o perfil e segue o próximo da fila.
                                    _rr = _resumir_bm_existente(
                                        mod, profile_id, perfil, business_id,
                                        _empresa_dados_cache, _site_cache, 'datacrazy',
                                        _estado.get('captcha_token', ''), _estado.get('tipo_empresa', 'mei'),
                                        _estado.get('sms24h_token', ''), _estado.get('datacrazy_email', ''),
                                        _estado.get('datacrazy_senha', ''), numero_sms, variantes_tel,
                                        bm_email or '', drv_verif, _cb_verif,
                                        sms_provedor=_estado.get('sms_provedor', 'sms24h'),
                                        metodo_verificacao='dominio', verificar_site=True)
                                    res_verif = {
                                        'sucesso': bool(_rr.get('sucesso')),
                                        'em_analise': bool(_rr.get('em_analise')),
                                        'bm_bloqueada': bool(_rr.get('bm_bloqueada')),
                                        'conexao_incompleta': False,
                                        'mensagem': _rr.get('mensagem', ''),
                                    }
                                    # No caso NÃO-restrito o helper deixa o drv_verif vivo
                                    # (o fechamento guarded lá embaixo o encerra). No caso
                                    # restrito ele já fechou/excluiu tudo; o quit/fechar
                                    # duplicado lá embaixo é inócuo (try/except).
                                else:
                                    # PRO MAX Turbo com RETRY de 2ª BM (pedido do usuário
                                    # 2026-07-25): se a WABA nascer DESABILITADA (Central
                                    # sem 'Iniciar verificação') ou a BM restringir, gera
                                    # nova empresa + 2ª BM e refaz. As 2 bloqueadas →
                                    # bloqueio → tag/erro/próximo da fila.
                                    res_verif = _pro_max_com_retry(
                                        mod, profile_id, perfil, business_id, _kwargs_verif,
                                        drv_verif, bm_email or '',
                                        _estado.get('tipo_empresa', 'mei'),
                                        _estado.get('captcha_token', ''), _cb_verif, _func_verif)
                                    business_id = res_verif.get('business_id', business_id) or business_id
                                    bm_email = res_verif.get('bm_email', bm_email) or bm_email
                                    drv_verif = res_verif.get('driver', drv_verif) or drv_verif
                                    if res_verif.get('empresa_dados'):
                                        _empresa_dados_cache = res_verif.get('empresa_dados')
                                    if res_verif.get('site_cache'):
                                        _site_cache = res_verif.get('site_cache')

                                verif_bloqueada = bool(res_verif.get('bm_bloqueada'))
                                verif_ok = bool(res_verif.get('sucesso'))
                                verif_msg = res_verif.get('mensagem', '') or ''
                            except _PerfilQueimado:
                                # Checkpoint dead-end (captcha de imagem): a conta caiu no
                                # checkpoint — perfil DESCARTADO (não insiste/clica).
                                verif_queimada = True
                                verif_msg = 'Checkpoint (captcha de imagem) — perfil queimado.'
                                logger.warning('[Perfil %s] Checkpoint captcha (dead-end) — descartando perfil.',
                                               profile_id)
                            except Exception as ve:
                                logger.exception('[Perfil %s] Erro na verificação imediata: %s',
                                                 profile_id, ve)
                                verif_msg = f'Exceção na verificação: {ve}'

                            if verif_queimada:
                                # Perfil queimado no checkpoint: conta ERRO, marca a tag e
                                # RETÉM o site p/ o próximo perfil (o domínio não chegou a
                                # ser consumido no fluxo travado — reaproveitável).
                                _inc('erros')
                                _painel_desfecho(business_id, 'checkpoint', verif_msg)
                                try:
                                    mod.adicionar_tags_perfil(profile_id, ["🧩 CHECKPOINT CAPTCHA 🧩"])
                                except Exception:
                                    pass
                                try:
                                    _reter_ou_estornar('checkpoint captcha (perfil queimado) — site reaproveitável')
                                except Exception:
                                    pass
                                _atualizar_progresso(i, 'Erro', '#FF4444',
                                    f"🧩 Checkpoint (captcha de imagem) — perfil descartado | {bm_email or ''}")
                            elif verif_bloqueada:
                                # WABA DESABILITADA com RECURSO ENVIADO ('Solicitar análise'/
                                # 'Submit') NÃO é bloqueio duro: é RECORRIDA — aguarda a
                                # reanálise da Meta (status definitivo chega pelo e-mail →
                                # GSMAILS→painel). Nesse caso a tag é "♻️ BM RECORRIDA" (já
                                # aplicada por _nota_recorridas), NUNCA "💔 BM BLOQUEADA 💔".
                                _eh_recorrida = bool(res_verif.get('recorrida'))
                                # RECORRIDA NÃO é erro: o fluxo concluiu até recorrer uma WABA
                                # desabilitada (recurso enviado). Conta no card próprio
                                # "Recorridas"; só bloqueio SEM recurso conta em "erros".
                                if _eh_recorrida:
                                    _inc('recorridas')
                                    _painel_desfecho(business_id, 'recorrida', verif_msg)
                                    try:
                                        # Convenção do usuário (coração amarelo). Idempotente:
                                        # se _nota_recorridas já aplicou, não duplica.
                                        mod.adicionar_tags_perfil(profile_id, ["💛 BM Recorrida 💛"])
                                    except Exception:
                                        pass
                                else:
                                    _inc('erros')
                                    _painel_desfecho(business_id, 'bloqueada', verif_msg)
                                    try:
                                        mod.adicionar_tags_perfil(profile_id, ["💔 BM BLOQUEADA 💔"])
                                    except Exception:
                                        pass
                                # Regra (2026-07-12): DESCARTAR vs RETER decidido pelo estado
                                # REAL do domínio (não pela etapa). Se a meta tag JÁ validou
                                # (dominio_verificado) e o bloqueio veio DEPOIS -> o site foi
                                # CONSUMIDO e é descartado junto ao perfil bloqueado (estorna
                                # token + queima o CNPJ). Se o domínio NÃO chegou a ser
                                # validado -> o site NÃO foi usado: RETÉM p/ o próximo perfil
                                # da fila (só estorna se não houver próximo).
                                if bool(res_verif.get('dominio_verificado')):
                                    _descartar_empresa_bloqueada('recorrida (WABA desabilitada, recurso enviado)'
                                                                 if _eh_recorrida else 'bloqueada após verificar o domínio')
                                    if _eh_recorrida:
                                        _atualizar_progresso(i, 'Recorrida', '#F0AD4E',
                                            f"♻️ BM RECORRIDA — recurso enviado; aguardando reanálise da Meta (status pelo e-mail) | {bm_email or ''}")
                                    else:
                                        _atualizar_progresso(i, 'Erro', '#FF4444',
                                            f"🚫 BM bloqueada (domínio já verificado → site descartado, token estornado) | {bm_email or ''}")
                                else:
                                    _reter_ou_estornar('bloqueada antes de verificar o domínio (site reaproveitável)')
                                    if _eh_recorrida:
                                        _atualizar_progresso(i, 'Recorrida', '#F0AD4E',
                                            f"♻️ BM RECORRIDA — recurso enviado; aguardando reanálise da Meta (status pelo e-mail) | {bm_email or ''}")
                                    else:
                                        _atualizar_progresso(i, 'Erro', '#FF4444',
                                            f"🚫 BM bloqueada antes de usar o site — reaproveitando no próximo perfil | {bm_email or ''}")
                            elif verif_ok:
                                _etapa_extra_ok = bool(res_verif.get('etapa_extra_ok'))
                                _em_analise = bool(res_verif.get('em_analise'))
                                # PRO MAX: só é SUCESSO se a BM foi enviada para análise
                                # (em_analise=True). Domínio verificado mas sem análise =
                                # fluxo NÃO concluído.
                                _full_incompleto = not _em_analise
                                try:
                                    mod.adicionar_tags_perfil(profile_id, [
                                        "✅ DOMINIO VERIFICADO ✅",
                                        f"🏢 {_empresa_dados_cache.get('razao_social', '')[:30]}",
                                        f"🌐 {_site_cache.get('url', '')}",
                                    ])
                                except Exception:
                                    pass
                                try:
                                    from server.painel_integration import atualizar_status_bm_por_business_id
                                    atualizar_status_bm_por_business_id(
                                        business_id, 'aguardando_verificacao')
                                except Exception as _pe:
                                    logger.warning('[VerifImediata] painelbr.site: %s', _pe)
                                # MONITOR DE ANÁLISE: quando a BM foi p/ análise na Central
                                # (Pro Max), grava site_id + empresa + relógio das 3h para o
                                # Monitor reabrir depois e criar WABA / reenviar.
                                if _em_analise:
                                    try:
                                        from server.painel_integration import registrar_bm_em_analise, carimbar_engine_bm
                                        registrar_bm_em_analise(
                                            business_id,
                                            site_id=(_site_cache or {}).get('site_id', ''),
                                            site_url=(_site_cache or {}).get('url', ''),
                                            empresa_dados=_empresa_dados_cache or {},
                                            profile_id=str(profile_id),
                                            fb_login=perfil.get('login', ''))
                                        # Carimba o ENGINE do perfil p/ a re-tag em tempo real
                                        # saber onde aplicar a tag sem abrir o navegador.
                                        carimbar_engine_bm(business_id,
                                                           _estado.get('browser_engine', ''),
                                                           str(profile_id))
                                    except Exception as _me:
                                        logger.warning('[Monitor] registrar_bm_em_analise: %s', _me)
                                # Uso livre (admin / alexandre06): devolve o
                                # token mesmo na entrega bem-sucedida.
                                if _TEM_ACESSO and usuario_uso_livre():
                                    _estornar_token_se_preciso('uso livre (admin/alexandre06)')

                                if _full_incompleto:
                                    # Conta ERRO: o nível FULL escolhido não concluiu
                                    # (WABA não criada / BM não enviada p/ análise).
                                    # Mantém o token do site — não cobra coins do método.
                                    _inc('erros')
                                    _msg_inc = (f"⚠️ Pro Max (Turbo) incompleto: não enviado p/ análise | {bm_email or ''}")
                                    logger.warning("[Perfil %s] Pro Max (Turbo) incompleto — BM não enviada p/ análise.",
                                                   profile_id)
                                    _painel_desfecho(business_id, 'erro', 'Não enviada p/ análise: ' + (verif_msg or ''))
                                    _atualizar_progresso(i, 'Erro', '#FF8800', _msg_inc)
                                else:
                                    _inc('concluidos')
                                    _atualizar_progresso(i, 'Concluído', '#00C74F',
                                        f"✅ BM criada e verificada (empresa + domínio) | {bm_email or ''}")
                                    logger.info("[Perfil %s] BM verificada imediatamente: %s",
                                                profile_id, bm_name)
                                    # Tags: BM enviada para análise (Turbo).
                                    if _em_analise:
                                        try:
                                            mod.adicionar_tags_perfil(profile_id, [
                                                "🟠 DATACRAZY CRIADA",
                                                "💙 BM EM ANALISE 💙",
                                            ])
                                        except Exception:
                                            pass
                                    # Custo de USO em COINS (só no sucesso). O token do
                                    # site é à parte.
                                    _cobrar_coins_uso(f'{bm_name or bm_email or ""}')
                            else:
                                _inc('erros')
                                _painel_desfecho(business_id, 'erro', verif_msg)
                                try:
                                    mod.adicionar_tags_perfil(profile_id,
                                                              ['⚠️ VERIFICAÇÃO PARCIAL'])
                                except Exception:
                                    pass
                                # Dominio NAO ficou verificado -> devolve o token.
                                # FIX (auditoria 2026-10-12): se o domínio JÁ foi validado nesta
                                # BM (ex.: falhou a etapa 2 'info da empresa' depois da meta-tag),
                                # o site está CONSUMIDO por ela (e o reprocesso volta nela com a
                                # MESMA empresa) → NUNCA reter p/ o próximo perfil (cruzaria a
                                # mesma empresa/domínio em 2 BMs). Mesma regra do ramo bloqueada.
                                if bool(res_verif.get('dominio_verificado')):
                                    _estornar_token_se_preciso(
                                        'verificacao nao concluida (dominio ja verificado nesta BM)')
                                else:
                                    _reter_ou_estornar('verificacao parcial/falhou')
                                _atualizar_progresso(i, 'Erro', '#FF8800',
                                    f"⚠️ Verificação não concluída (token estornado): {verif_msg[:50]} | {bm_email or ''}")

                            try:
                                if drv_verif: drv_verif.quit()
                            except Exception:
                                pass
                            try:
                                mod.fechar_navegador(profile_id)
                            except Exception:
                                pass

                        else:
                            # Apenas criar (fluxo 'nao', BM bloqueada na criação,
                            # ou falha na preparação da empresa).
                            # Se um token foi gasto (site criado) mas a verificação
                            # nao rodou, devolvemos o token (entrega nao concluida).
                            _reter_ou_estornar('verificacao nao executada')
                            if _pre_erro_msg:
                                _inc('erros')
                                _painel_desfecho(business_id, 'sem_verificacao', _pre_erro_msg)
                                _atualizar_progresso(i, 'Erro', '#FF4444',
                                    f'❌ BM não concluída (verificação abortada): {_pre_erro_msg[:60]} | {bm_email or ""}')
                                try:
                                    mod.adicionar_tags_perfil(profile_id, ['⚠️ SEM VERIFICAÇÃO'])
                                except Exception:
                                    pass
                            elif res_automacao.get('bm_bloqueada'):
                                _inc('erros')
                                _painel_desfecho(business_id, 'bloqueada', 'BM bloqueada na criação')
                                _atualizar_progresso(i, 'Erro', '#FF4444',
                                    f'🚫 BM bloqueada na criação | {bm_email or ""}')
                            else:
                                # Chegou aqui SEM verificar = fluxo NÃO concluído -> erro.
                                _inc('erros')
                                _painel_desfecho(business_id, 'sem_verificacao', 'Verificação não executada')
                                _atualizar_progresso(i, 'Erro', '#FF4444',
                                    f'❌ Fluxo não concluído (verificação não executada) | {bm_email or ""}')
                            drv = res_automacao.get('driver')
                            try:
                                if drv: drv.quit()
                            except Exception:
                                pass
                            try:
                                mod.fechar_navegador(profile_id)
                            except Exception:
                                pass
                    else:
                        _inc('erros')
                        erro_msg = res_automacao.get('mensagem', 'Erro')
                        _atualizar_progresso(i, 'Erro', '#FF4444', f"❌ {erro_msg}")

                        # Falha — incrementa cooldown para proximo perfil
                        if _cooldown is not None:
                            try:
                                _cooldown.registrar_falha()
                            except Exception:
                                pass

                        # Entrega nao concluida (BM nao criada / login falhou):
                        # devolve o token do site deste perfil. O proximo perfil
                        # gera empresa+site NOVOS (e debita novo token), mantendo
                        # o liquido em 1 token por entrega bem-sucedida.
                        _reter_ou_estornar(f'automacao falhou: {erro_msg[:40]}')

                        # ── Reembolsar coin do perfil que falhou ──
                        coin_debitado = _estado['progresso'][i].get('coin_debitado', False)
                        if coin_debitado and _TEM_ACESSO:
                            login_perfil = perfil.get('login', f'perfil_{i+1}')
                            res_reembolso = reembolsar_coin(
                                1, f"Reembolso automático - perfil {login_perfil} falhou: {erro_msg[:80]}"
                            )
                            if res_reembolso.get('sucesso'):
                                _estado['progresso'][i]['coin_debitado'] = False
                                if login_perfil in _estado['perfis_cobrados']:
                                    del _estado['perfis_cobrados'][login_perfil]
                                logger.info("Coin reembolsado para perfil %s (erro: %s)", login_perfil, erro_msg[:50])
                            else:
                                logger.warning("Falha ao reembolsar coin para perfil %s: %s",
                                               login_perfil, res_reembolso.get('mensagem', ''))

                except Exception as e:
                    _inc('erros')
                    _atualizar_progresso(i, 'Erro', '#FF4444', f"Erro: {str(e)}")

                    if _cooldown is not None:
                        try:
                            _cooldown.registrar_falha()
                        except Exception:
                            pass

                    # Excecao durante a automacao: se um token foi gasto (site
                    # criado), devolve-o — entrega nao concluida.
                    try:
                        _estornar_token_se_preciso(f'excecao: {str(e)[:40]}')
                    except Exception:
                        pass

                    # ── Reembolsar coin do perfil que deu exceção ──
                    coin_debitado = _estado['progresso'][i].get('coin_debitado', False)
                    if coin_debitado and _TEM_ACESSO:
                        login_perfil = perfil.get('login', f'perfil_{i+1}')
                        res_reembolso = reembolsar_coin(
                            1, f"Reembolso automático - perfil {login_perfil} exceção: {str(e)[:80]}"
                        )
                        if res_reembolso.get('sucesso'):
                            _estado['progresso'][i]['coin_debitado'] = False
                            if login_perfil in _estado['perfis_cobrados']:
                                del _estado['perfis_cobrados'][login_perfil]
                            logger.info("Coin reembolsado para perfil %s (exceção)", login_perfil)

                    # FIX (auditoria 24/7): esta era a ÚNICA chamada de fechar_navegador FORA
                    # de try/except. Se lançasse, no modo SEQUENCIAL a exceção subia e marcava
                    # TODOS os perfis restantes como erro — derrubava o run inteiro.
                    try:
                        mod.fechar_navegador(profile_id)
                    except Exception:
                        pass
            else:
                _inc('erros')
                _atualizar_progresso(i, 'Erro', '#FF4444', resultado['mensagem'])

                # ── Reembolsar coin se criação de perfil de browser falhou ──
                coin_debitado = _estado['progresso'][i].get('coin_debitado', False)
                if coin_debitado and _TEM_ACESSO:
                    login_perfil = perfil.get('login', f'perfil_{i+1}')
                    res_reembolso = reembolsar_coin(
                        1, f"Reembolso automático - falha criar perfil browser: {login_perfil}"
                    )
                    if res_reembolso.get('sucesso'):
                        _estado['progresso'][i]['coin_debitado'] = False
                        if login_perfil in _estado['perfis_cobrados']:
                            del _estado['perfis_cobrados'][login_perfil]
                        logger.info("Coin reembolsado para perfil %s (falha browser)", login_perfil)

        # ───────────────────────────────────────────────────────────────
        # ORQUESTRAÇÃO: sequencial (1) ou navegadores simultâneos (2–10)
        # ───────────────────────────────────────────────────────────────
        perfis_lista = _estado['perfis']
        _usa_4g = (utilizar_4g == 'sim')

        # COORDENADOR de TROCA DE IP (MODELO ÚNICO): a troca do 4G acontece SOMENTE
        # quando a Meta bate o rate-limit de SMS ("muitos códigos"). O coordenador pausa
        # TODAS as abas em ponto seguro, espera ficarem estáticas, troca o IP 1x
        # (verificado, com IPs queimados congelados) e libera todas. É ARMADO apenas com
        # o 4G ATIVADO — com o 4G desligado o sistema NÃO troca de IP (o usuário troca
        # manualmente). request() retorna 'inativo' quando não armado. Ver ip_rotation_coordinator.
        from server.ip_rotation_coordinator import COORD as _IPCOORD
        if _usa_4g:
            _IPCOORD.begin_run(trocar_ip_4g_adb)
            logger.info("[4G] Troca de IP ARMADA (rate-limit da Meta + COTA por IP).")
        else:
            logger.info("[4G] Desativado — o sistema NÃO troca IP (troca manual pelo usuário).")
        # GATE anti-rajada de envio de SMS por IP (independe do 4G: várias abas no MESMO
        # IP — 4G, Ethernet ou VPN — clicando "Enviar SMS" juntas disparam "muitos códigos".
        # O coordenador escalona os envios. Espaçamento configurável (padrão 16s).
        try:
            _gap = float(_ler_config('sms_ip_gap', '16', usuario=_estado.get('usuario_logado', '')) or 16)
            _IPCOORD.set_sms_gap(_gap)
            logger.info("[SMS] Gate anti-rajada por IP: espaçamento mínimo %.0fs entre envios.", _gap)
        except Exception as _e_gap:
            logger.debug("[SMS] set_sms_gap ignorado: %s", _e_gap)

        # ── IP INTELIGENTE — troca PROATIVA p/ um IP LIMPO antes de abrir qualquer aba.
        # (pedido do dono: "sempre que for lançar troca o IP anterior antes"). O
        # trocar_ip_4g_adb só confirma com um IP FORA da janela de congelamento.
        if _usa_4g:
            try:
                logger.info("[IP] Trocando para um IP LIMPO antes de iniciar o run...")
                _ok_ip0 = trocar_ip_4g_adb()
                _estado['_ip_ciclo'] = _IPCOORD.ciclo_atual()
                _estado['_ip_iniciados'] = 0
                logger.info("[IP] Início do run com IP limpo: %s.",
                            "confirmado" if _ok_ip0 else "NÃO confirmado (segue mesmo assim)")
            except Exception as _eip0:
                logger.warning("[IP] Troca proativa inicial falhou: %s", _eip0)

        # GUARDA DE COTA POR IP (rolling): conta perfis iniciados no IP atual; ao atingir
        # a cota (ou no rate-limit), pausa TODAS as abas, troca 1x p/ um IP limpo (coordenador)
        # e zera o contador. Escalona a carga → menos IP queimado, mantendo o ritmo. Só age
        # com o 4G ativo. Usada nos dois modos (sequencial e concorrente).
        import threading as _thr_ip
        _ip_cota_lock = _thr_ip.Lock()

        def _gate_ip_cota():
            if not _usa_4g:
                return
            _vivo = lambda: not _estado.get('cancelar')
            try:
                _IPCOORD.checkpoint(alive_fn=_vivo)   # há rotação em curso? não inicia no IP velho
            except Exception:
                pass
            _disparar = False
            with _ip_cota_lock:
                _c = _IPCOORD.ciclo_atual()
                if _c != _estado.get('_ip_ciclo'):    # o IP trocou (rate-limit/cota) → zera a cota
                    _estado['_ip_ciclo'] = _c
                    _estado['_ip_iniciados'] = 0
                _estado['_ip_iniciados'] = int(_estado.get('_ip_iniciados', 0)) + 1
                # FIX (M1, auditoria): NÃO zera o contador aqui de forma otimista — só depois
                # de CONFIRMAR que o IP realmente trocou (senão, com cooldown/falha, o contador
                # reinicia mas o IP continua o mesmo → a cota é furada por +K perfis).
                if _estado['_ip_iniciados'] > int(_estado.get('_ip_max_por_ip', 10)):
                    _disparar = True
            if _disparar:
                try:
                    _res = _IPCOORD.request(
                        "cota de %s perfil(is) por IP atingida" % _estado.get('_ip_max_por_ip'))
                    logger.info("[IP] Cota por IP atingida — rotação coordenada: %s", _res)
                    _IPCOORD.checkpoint(alive_fn=_vivo)   # espera a troca terminar antes de abrir
                    _c2 = _IPCOORD.ciclo_atual()
                    with _ip_cota_lock:
                        if _c2 != _estado.get('_ip_ciclo'):   # trocou de verdade → zera a cota
                            _estado['_ip_ciclo'] = _c2
                            _estado['_ip_iniciados'] = 1      # este perfil já conta no IP NOVO
                        # Se NÃO trocou (cooldown/'recente'/falha), mantém a contagem — a cota
                        # não é furada; a próxima passagem re-tentará a rotação quando possível.
                except Exception as _eg:
                    logger.warning("[IP] Falha ao coordenar rotação por cota: %s", _eg)

        # ── WATCHDOG (auditoria 24/7): mata aba CONGELADA-mas-conectada ──────────
        # O Playwright síncrono NÃO tem timeout em evaluate/execute_script; uma aba com
        # renderer travado bloqueia o worker PARA SEMPRE e o slot nunca volta → o pool
        # degrada a 0 e o run nunca termina. O watchdog mede o HEARTBEAT (_hb, atualizado
        # a cada status via _atualizar_progresso) e, se um worker ATIVO passar
        # _WD_INATIVIDADE sem avançar, FECHA o navegador dele — o worker destrava (os
        # checks _navegador_vivo falham → a chamada travada levanta ao cair o CDP), roda o
        # finally e DEVOLVE o slot. Só age em perfil realmente identificado (profile_id).
        _WD_INATIVIDADE = 600.0    # 10 min sem avanço → aba considerada travada
        _WD_TERMINAIS = ('Sucesso', 'Concluíd', 'Concluid', 'Erro', 'Cancelad',
                         'Em análise', 'Em analise', 'Bloquead')
        _wd_mortos = set()

        def _watchdog_loop():
            logger.info("[Watchdog] iniciado (inatividade máx %.0fs).", _WD_INATIVIDADE)
            while _estado.get('processando'):
                try:
                    agora = time.time()
                    for _pi, _it in enumerate(list(_estado.get('progresso') or [])):
                        if not isinstance(_it, dict):
                            continue
                        st = _it.get('status') or ''
                        if any(st.startswith(t) for t in _WD_TERMINAIS):
                            continue
                        pid = _it.get('profile_id') or ''
                        hb = _it.get('_hb') or 0
                        if not pid or not hb or pid in _wd_mortos:
                            continue
                        if (agora - hb) > _WD_INATIVIDADE:
                            _wd_mortos.add(pid)
                            _mins = int(_WD_INATIVIDADE / 60)
                            logger.error("[Watchdog] Worker %s (perfil %s) sem avanço há %.0fs "
                                         "— fechando o navegador p/ destravar o slot.",
                                         _pi + 1, pid, agora - hb)
                            try:
                                _emitir_ip_evento(f"🐕 Watchdog: perfil {_pi + 1} travado "
                                                  f"(>{_mins}min sem avanço) — reiniciando o navegador p/ liberar o slot.")
                            except Exception:
                                pass
                            try:
                                _atualizar_progresso(_pi, 'Erro', '#FF4444',
                                    f'Watchdog: aba travada (>{_mins}min sem avanço) — reiniciada.')
                            except Exception:
                                pass
                            try:
                                mod.fechar_navegador(str(pid))
                            except Exception:
                                pass
                except Exception as _ewd:
                    logger.debug("[Watchdog] %s", _ewd)
                for _ in range(15):     # ~30s, mas responde ao fim do run em ~2s
                    if not _estado.get('processando'):
                        break
                    time.sleep(2)
            logger.info("[Watchdog] encerrado.")

        try:
            import threading as _thr_wd
            _thr_wd.Thread(target=_watchdog_loop, daemon=True, name="gs-watchdog").start()
        except Exception as _e_wd:
            logger.warning("[Watchdog] não iniciado: %s", _e_wd)

        if _simultaneos <= 1:
            # SEQUENCIAL — comportamento idêntico ao anterior.
            for i in range(len(perfis_lista)):
                if _estado['cancelar']:
                    break
                _IPCOORD.register()
                try:
                    _gate_ip_cota()          # cota por IP: troca p/ IP limpo ao atingir o teto
                    _trabalhar(i, perfis_lista[i])
                finally:
                    _IPCOORD.unregister()
        else:
            import queue as _queue
            # Pool de proxies: 1 por navegador ativo; um proxy só é REUSADO depois
            # que o navegador que o usava encerra (devolvido na fila no finally).
            _proxies_pool = (_parse_lista_proxy(lista_proxy)
                             if (proxy == 'sim' and lista_proxy) else [])
            _fila_proxy = _queue.Queue()
            for _p in _proxies_pool:
                _fila_proxy.put(_p)

            # IP COMPARTILHADO entre abas => liga o gate anti-cascata de criação:
            #  • 4G/ancoragem: todas as abas saem pelo MESMO IP do celular;
            #  • sem pool de proxy: todas saem pelo IP da máquina.
            # Com 1 proxy por aba, cada uma tem IP próprio -> gate desligado.
            _estado['_ip_compartilhado'] = bool(_usa_4g or not _proxies_pool)
            logger.info("[AntiCascata] IP compartilhado=%s (4g=%s proxies=%d) -> "
                        "gate de criação %s", _estado['_ip_compartilhado'],
                        _usa_4g, len(_proxies_pool),
                        'ATIVO' if _estado['_ip_compartilhado'] else 'inativo')

            # ── MODO ÚNICO (com ou sem 4G): CONCORRENTE / ROLLING ──
            # NÃO espera o lote inteiro: mantém sempre _simultaneos navegadores
            # rodando; assim que UM finaliza/fecha, o PRÓXIMO da fila abre NA HORA.
            # Cada worker ocupa um SLOT fixo da grade (posição da janela); ao liberar,
            # o próximo perfil NASCE NO MESMO LUGAR do que fechou (mantém a ordem).
            #
            # A troca de IP do 4G NÃO acontece mais aqui de forma proativa (não há mais
            # 'lote'/'navegadores'/'minutos'). Com o 4G ATIVADO, ela ocorre SOMENTE
            # quando a Meta bate o rate-limit de SMS: o coordenador (_IPCOORD) pausa
            # TODAS as abas em ponto seguro, troca o IP 1x (verificado) e libera. Com o
            # 4G desligado, o sistema não troca de IP. Ver ip_rotation_coordinator.
            _fila_slots = _queue.Queue()
            for _s in range(_simultaneos):
                _fila_slots.put(_s)   # slot -> _grade_cells[slot] (posição na grade)

            def _exec_slot(idx, slot):
                proxy_cfg = None
                proxy_item = None
                if _proxies_pool:
                    proxy_item = _fila_proxy.get()  # bloqueia até liberar um proxy
                    # URL de rotação no proxy => o GS Creator gira o IP ANTES de criar o
                    # navegador (garante 1 IP FRESCO por proxy/aba). Os workers são threads,
                    # então os giros dos vários proxies acontecem em paralelo. Sem URL: AUTO.
                    try:
                        from server import proxy_rotate
                        if proxy_rotate.tem_rotacao(proxy_item):
                            _atualizar_progresso(idx, 'Aguardando', '#888888',
                                                 '🔁 Trocando IP do proxy antes de abrir o navegador...')
                            proxy_rotate.girar_ip(
                                proxy_item,
                                status=lambda m, _i=idx: _atualizar_progresso(_i, 'Aguardando', '#888888', m))
                    except Exception as _re:
                        logger.warning("[ProxyRotate] rotação pré-navegador falhou: %s", _re)
                    try:
                        proxy_cfg = mod.montar_proxy_config(
                            proxy_item['ip'], proxy_item['port'],
                            proxy_item['user'], proxy_item['pass'], proxy_tipo)
                    except Exception:
                        proxy_cfg = None
                _IPCOORD.register()
                try:
                    _gate_ip_cota()          # cota por IP: troca p/ IP limpo ao atingir o teto
                    _trabalhar(idx, perfis_lista[idx], proxy_override=proxy_cfg,
                               cell_idx=slot, proxy_dict=proxy_item)
                except Exception as _we:
                    logger.error("[Rolling] Worker %s erro: %s", idx + 1, _we, exc_info=True)
                    _inc('erros')
                    _atualizar_progresso(idx, 'Erro', '#FF4444',
                                         f'Erro no worker: {str(_we)[:60]}')
                finally:
                    _IPCOORD.unregister()
                    if proxy_item is not None:
                        _fila_proxy.put(proxy_item)   # devolve o proxy
                    _fila_slots.put(slot)             # libera a POSIÇÃO da grade

            # Dispatcher: para cada slot que fica LIVRE, dispara o próximo perfil
            # da lista naquele slot. _fila_slots.get() bloqueia até um worker
            # encerrar e devolver a posição → o próximo abre exatamente ali.
            _total = len(perfis_lista)
            _threads_all = []
            _disp = 0
            while _disp < _total and not _estado['cancelar']:
                try:
                    from server import pausa as _pausa_d
                    if not _pausa_d.aguardar_se_pausado(_atualizar_status_geral):
                        break
                except Exception:
                    pass
                slot = _fila_slots.get()   # espera uma posição da grade livre
                if _estado['cancelar']:
                    break
                idx = _disp
                _disp += 1
                t = threading.Thread(target=_exec_slot, args=(idx, slot), daemon=True)
                t.start()
                _threads_all.append(t)
                time.sleep(_STAGGER_ABERTURA)   # escalona a abertura inicial
            for t in _threads_all:
                t.join()  # aguarda todos os workers em andamento encerrarem

        _atualizar_status_geral("Concluído!")
    except Exception as e:
        logger.error("[Processamento] Erro fatal: %s", e, exc_info=True)
        # Marcar perfis restantes como erro
        for idx in range(len(_estado['perfis'])):
            if _estado['progresso'][idx]['status'] == 'Aguardando':
                _atualizar_progresso(idx, 'Erro', '#FF4444', f'Erro fatal: {str(e)[:60]}')
                _inc('erros')
    finally:
        # Encerra a coordenadora de troca forçada de IP (libera a thread).
        try:
            from server.ip_rotation_coordinator import COORD as _IPCOORD_END
            _IPCOORD_END.end_run()
        except Exception:
            pass
        # Tira a GUI do modo "sempre no topo" (volta ao normal ao fim do run).
        try:
            _restaurar_gui_topmost()
        except Exception:
            pass

        # ── Reembolsar perfis que ficaram sem processar (cancelamento/interrupção) ──
        pendentes = 0
        for idx, prog in enumerate(_estado['progresso']):
            if prog['status'] == 'Aguardando' and prog.get('coin_debitado', False):
                pendentes += 1
                login_p = _estado['perfis'][idx].get('login', '') if idx < len(_estado['perfis']) else ''
                if login_p and login_p in _estado['perfis_cobrados']:
                    del _estado['perfis_cobrados'][login_p]
                prog['coin_debitado'] = False

        if pendentes > 0 and _TEM_ACESSO:
            try:
                res_p = reembolsar_coin(
                    pendentes,
                    f"Reembolso: {pendentes} perfis não processados"
                )
                if res_p.get('sucesso'):
                    logger.info("Reembolsados %d coins (perfis não processados)", pendentes)
                else:
                    logger.warning("Falha ao reembolsar %d coins pendentes", pendentes)
            except Exception as re_err:
                logger.error("Erro ao reembolsar pendentes: %s", re_err)

        # ── Estornar token em hold de um buffer que sobrou (entrega nunca
        #    concluída): o site foi pago mas nenhuma BM foi verificada com ele. ──
        try:
            _buf_final = _estado.get('empresa_buffer')
            if _buf_final and _buf_final.get('token_held'):
                _estornar_token_buffer(_buf_final, 'fim do run sem entrega')
            _estado['empresa_buffer'] = None
        except Exception as _bf_err:
            logger.warning("Erro ao estornar token do buffer no fim do run: %s", _bf_err)

        # Relatório completo do run (status por perfil + totais) para diagnóstico.
        try:
            _gravar_relatorio_run()
        except Exception:
            pass

        _estado['processando'] = False
        # (2026-10-13, pedido do dono) REMOVIDO o reprocesso-ocioso: ao terminar a lista o
        # app NÃO abre mais navegador nenhum (AdsPower/ixBrowser) p/ reenviar BMs à análise.
        # Recuperar BM não enviada/não verificada vai virar uma versão PRÓPRIA. Com o app
        # ocioso só segue o tag_reconciler (troca a tag via API, sem abrir navegador).


# ============================================================================
# FILA DE VERIFICAÇÃO DE BM (agendamento 2h)
# ============================================================================

# Estado da verificação de fila (separado do processamento de criação)
_estado_verificacao = {
    'processando': False,
    'cancelar': False,
    'total': 0,
    'concluidos': 0,
    'erros': 0,
    'atual': '',
    'mensagem': '',
    'progresso_itens': [],  # Lista de {profile_id, bm_name, status, mensagem, cor}
}


def obter_fila_verificacao():
    """Retorna o resumo da fila de verificação para a UI."""
    resumo = obter_resumo_fila()
    resumo['verificacao_processando'] = _estado_verificacao['processando']
    resumo['verificacao_mensagem'] = _estado_verificacao.get('mensagem', '')
    resumo['verificacao_progresso'] = _estado_verificacao.get('progresso_itens', [])
    # Estado do modo REPROCESSAR (mesmo polling da UI)
    resumo['reprocesso_processando'] = _estado_reprocesso['processando']
    resumo['reprocesso_mensagem'] = _estado_reprocesso.get('mensagem', '')
    resumo['reprocesso_progresso'] = _estado_reprocesso.get('progresso_itens', [])
    resumo['reprocesso_reenviadas'] = _estado_reprocesso.get('reenviadas', 0)
    resumo['reprocesso_novas_bm'] = _estado_reprocesso.get('novas_bm', 0)
    resumo['reprocesso_ignoradas'] = _estado_reprocesso.get('ignoradas', 0)
    resumo['reprocesso_erros'] = _estado_reprocesso.get('erros', 0)
    resumo['reprocesso_excluidos'] = _estado_reprocesso.get('excluidos', 0)
    return resumo


def limpar_fila_verificadas():
    """Remove BMs já verificadas da fila."""
    removidos = _limpar_verificadas_queue()
    return {'sucesso': True, 'removidos': removidos}


def retentar_erros_fila():
    """Move BMs com status 'erro' de volta para 'aguardando' para retentar."""
    from server.bm_queue_manager import _carregar_fila, _salvar_fila, _lock
    movidos = 0
    with _lock:
        fila = _carregar_fila()
        for item in fila:
            if item.get('status') == 'erro':
                item['status'] = 'aguardando'
                item['mensagem'] = ''
                item['criado_em'] = time.time() - TEMPO_MINIMO_ESPERA  # já pronta imediatamente
                movidos += 1
        _salvar_fila(fila)
    logger.info("[FilaBM] %d BMs com erro movidas de volta para fila", movidos)
    return {'sucesso': True, 'movidos': movidos}


def cancelar_verificacao_fila():
    """Cancela o processamento da fila de verificação."""
    _estado_verificacao['cancelar'] = True
    return True


def iniciar_verificacao_fila():
    """
    Inicia a verificação das BMs que já passaram 2 horas na fila.
    Abre o navegador do perfil, preenche dados da empresa e verifica domínio.
    """
    if _estado_verificacao['processando']:
        return {"sucesso": False, "mensagem": "Verificação já em andamento"}

    prontas = obter_bms_prontas()
    if not prontas:
        return {"sucesso": False, "mensagem": "Nenhuma BM pronta para verificação (mínimo 2h de espera)"}

    thread = threading.Thread(
        target=_processar_fila_verificacao,
        args=(prontas,),
        daemon=True
    )
    thread.start()
    return {"sucesso": True, "mensagem": f"{len(prontas)} BMs serão verificadas", "total": len(prontas)}


def _processar_fila_verificacao(bms_prontas):
    """Thread que processa a fila de verificação — 1 navegador por vez, sequencial."""
    _estado_verificacao['processando'] = True
    _estado_verificacao['cancelar'] = False
    _estado_verificacao['total'] = len(bms_prontas)
    _estado_verificacao['concluidos'] = 0
    _estado_verificacao['erros'] = 0
    _estado_verificacao['progresso_itens'] = []

    for bm in bms_prontas:
        _estado_verificacao['progresso_itens'].append({
            'profile_id': bm['profile_id'],
            'bm_name': bm['bm_name'],
            'bm_email': bm.get('bm_email', ''),
            'status': 'Aguardando',
            'mensagem': '',
            'cor': '#3F3F46',
        })

    logger.info("[VerifFila] Iniciando verificação SEQUENCIAL de %d BMs prontas", len(bms_prontas))

    try:
        for idx, bm in enumerate(bms_prontas):
            if _estado_verificacao['cancelar']:
                logger.info("[VerifFila] Cancelado pelo usuário")
                break

            profile_id = bm['profile_id']
            business_id = bm['business_id']
            empresa_dados = bm.get('empresa_dados', {})
            site_cache = bm.get('site_cache', {})
            engine = bm.get('browser_engine', 'ixbrowser')

            _estado_verificacao['atual'] = bm.get('bm_name', profile_id)
            _estado_verificacao['mensagem'] = f"Verificando {idx+1}/{len(bms_prontas)}: {bm.get('bm_name', '')[:30]}"
            _estado_verificacao['progresso_itens'][idx]['status'] = 'Processando'
            _estado_verificacao['progresso_itens'][idx]['cor'] = '#F2C94C'
            _estado_verificacao['progresso_itens'][idx]['mensagem'] = 'Abrindo navegador...'

            # Marcar como verificando na fila
            atualizar_status_bm(profile_id, business_id, 'verificando', 'Em andamento...')

            # Selecionar módulo de browser
            if engine == 'adspower':
                mod = adspower_api
            else:
                mod = ixbrowser_api

            drv = None
            navegador_aberto = False

            try:
                # Verificar conexão antes de abrir
                conexao = mod.verificar_conexao()
                if not conexao.get('conectado'):
                    raise RuntimeError(f"Browser ({engine}) não conectado: {conexao.get('mensagem', '')}")

                # === ABRIR NAVEGADOR (1 por vez) ===
                logger.info("[VerifFila] Abrindo navegador para perfil %s (%d/%d)...",
                            profile_id, idx + 1, len(bms_prontas))
                _estado_verificacao['progresso_itens'][idx]['mensagem'] = 'Abrindo perfil no navegador...'

                res_abrir = mod.abrir_navegador(profile_id)
                if not res_abrir.get('sucesso'):
                    raise RuntimeError(f"Falha ao abrir perfil: {res_abrir.get('mensagem', '')}")

                navegador_aberto = True

                # === CONECTAR PLAYWRIGHT VIA CDP ===
                # abrir_navegador retorna info de conexão (debugging_address, ws),
                # não o driver direto. Precisamos conectar Playwright como faz executar_automacao_perfil.
                _estado_verificacao['progresso_itens'][idx]['mensagem'] = 'Conectando Playwright...'

                debugging_address = res_abrir.get('debugging_address', '')
                webdriver_path = res_abrir.get('webdriver', '')
                ws_url = res_abrir.get('ws', '')

                # Fallback: tentar sub-dict 'data'
                if not debugging_address:
                    dados_raw = res_abrir.get('data', {})
                    if isinstance(dados_raw, dict):
                        debugging_address = dados_raw.get('debugging_address', '')
                        if not webdriver_path:
                            webdriver_path = dados_raw.get('webdriver', '')
                        if not ws_url:
                            ws_raw = dados_raw.get('ws', '')
                            if isinstance(ws_raw, dict):
                                ws_url = ws_raw.get('puppeteer', '') or ws_raw.get('selenium', '') or ''
                            elif isinstance(ws_raw, str):
                                ws_url = ws_raw

                # Extrair debugging_address do ws URL se necessário
                if not debugging_address and ws_url and isinstance(ws_url, str):
                    import re as _re
                    _match = _re.search(r'ws://([^/]+)', ws_url)
                    if _match:
                        debugging_address = _match.group(1)

                if not debugging_address:
                    raise RuntimeError("Endereço de debug não encontrado após abrir navegador")

                logger.info("[VerifFila] Conectando Playwright ao %s...", debugging_address)

                # Aguardar o navegador inicializar completamente
                time.sleep(2)

                from server.automacao_facebook import conectar_selenium
                drv = conectar_selenium(debugging_address, webdriver_path)
                if not drv:
                    raise RuntimeError(f"Falha ao conectar Playwright ao navegador (debug={debugging_address})")
                # Guardião de sessão: se o perfil deslogar (FB ou Business loginpage), re-loga
                # com as credenciais da OBSERVAÇÃO do perfil e volta ao destino.
                try:
                    from server import session_guard as _sg
                    _sg.vincular_perfil(drv, profile_id, mod)
                except Exception:
                    pass

                logger.info("[VerifFila] Playwright conectado OK para perfil %s. Navegando ao BM...", profile_id)

                # Navegar para o Business Manager
                _estado_verificacao['progresso_itens'][idx]['mensagem'] = 'Navegando para Business Manager...'
                drv.goto(f"https://business.facebook.com/latest/settings/business_info?business_id={business_id}")
                time.sleep(5)

                # Gerar número de telefone
                from server.gerar_numero import gerar_numero_aleatorio
                numero_gerado = gerar_numero_aleatorio()
                numero_sms = f'+{numero_gerado}'
                empresa_dados['telefone'] = numero_sms

                from server.verificacao_bm import _gerar_variantes_telefone
                variantes_telefone = _gerar_variantes_telefone(numero_sms)

                _estado_verificacao['progresso_itens'][idx]['mensagem'] = f'📱 Tel: {numero_sms} | Verificando BM...'

                # Executar verificação completa
                def _cb_status(msg, _idx=idx):
                    _estado_verificacao['progresso_itens'][_idx]['mensagem'] = msg
                    _estado_verificacao['mensagem'] = f"[{_idx+1}/{len(bms_prontas)}] {msg[:60]}"

                res_verif = executar_verificacao_completa_bm(
                    driver=drv,
                    business_id=business_id,
                    empresa_dados=empresa_dados,
                    site_id=site_cache.get('site_id', ''),
                    site_url=site_cache.get('url', ''),
                    numero_telefone=numero_sms,
                    salvar_meta_func=salvar_meta_tags_site,
                    callback_status=_cb_status,
                    variantes_telefone=variantes_telefone,
                )

                if res_verif.get('bm_bloqueada'):
                    atualizar_status_bm(profile_id, business_id, 'erro',
                                        'BM bloqueada durante verificação')
                    _estado_verificacao['progresso_itens'][idx]['status'] = 'Erro'
                    _estado_verificacao['progresso_itens'][idx]['cor'] = '#FF4444'
                    _estado_verificacao['progresso_itens'][idx]['mensagem'] = '🚫 BM BLOQUEADA'
                    _estado_verificacao['erros'] += 1
                    try:
                        mod.adicionar_tags_perfil(profile_id, ["💔 BM BLOQUEADA 💔"])
                    except Exception:
                        pass
                    # Empresa bloqueada -> marca CNPJ 'usado' (nunca reusar em
                    # novos perfis; reusá-la bloquearia os próximos + cruzaria dados).
                    try:
                        _cnpj_blk = (empresa_dados or {}).get('cnpj', '')
                        if _TEM_ACESSO and _cnpj_blk:
                            marcar_empresa_usada(_cnpj_blk, 'BM bloqueada (verif. diferida)')
                    except Exception as _be:
                        logger.warning('[Empresa] marcar usada (verif diferida): %s', _be)

                elif res_verif.get('sucesso'):
                    atualizar_status_bm(profile_id, business_id, 'verificada',
                                        'BM verificada com sucesso')
                    _estado_verificacao['progresso_itens'][idx]['status'] = 'Concluído'
                    _estado_verificacao['progresso_itens'][idx]['cor'] = '#00C74F'
                    _estado_verificacao['progresso_itens'][idx]['mensagem'] = '✅ BM VERIFICADA'
                    _estado_verificacao['concluidos'] += 1
                    try:
                        mod.adicionar_tags_perfil(profile_id, [
                            "✅ DOMINIO VERIFICADO ✅",
                            f"🏢 {empresa_dados.get('razao_social', '')[:30]}",
                            f"🌐 {site_cache.get('url', '')}",
                        ])
                    except Exception:
                        pass
                    # Atualizar painelbr.site → status 'aguardando_verificacao' (empresa+domínio concluídos)
                    try:
                        from server.painel_integration import atualizar_status_bm_por_business_id
                        atualizar_status_bm_por_business_id(business_id, 'aguardando_verificacao')
                        logger.info('[VerifFila] painelbr.site → aguardando_verificacao para business_id=%s', business_id)
                    except Exception as _pe:
                        logger.warning('[VerifFila] Erro ao atualizar painelbr.site: %s', _pe)
                else:
                    msg_parcial = res_verif.get('mensagem', 'Verificação parcial')
                    atualizar_status_bm(profile_id, business_id, 'erro', msg_parcial)
                    _estado_verificacao['progresso_itens'][idx]['status'] = 'Erro'
                    _estado_verificacao['progresso_itens'][idx]['cor'] = '#FF8800'
                    _estado_verificacao['progresso_itens'][idx]['mensagem'] = f'⚠️ {msg_parcial[:50]}'
                    _estado_verificacao['erros'] += 1

            except Exception as e:
                logger.error("[VerifFila] Erro ao verificar BM %s: %s", profile_id, e, exc_info=True)
                atualizar_status_bm(profile_id, business_id, 'erro', str(e)[:100])
                _estado_verificacao['progresso_itens'][idx]['status'] = 'Erro'
                _estado_verificacao['progresso_itens'][idx]['cor'] = '#FF4444'
                _estado_verificacao['progresso_itens'][idx]['mensagem'] = f'❌ {str(e)[:50]}'
                _estado_verificacao['erros'] += 1

            finally:
                # === SEMPRE FECHAR NAVEGADOR antes de ir para o próximo ===
                if drv:
                    try:
                        logger.info("[VerifFila] Fechando driver do perfil %s...", profile_id)
                        drv.quit()
                    except Exception as eq:
                        logger.warning("[VerifFila] Erro ao fechar driver: %s", eq)

                if navegador_aberto:
                    try:
                        logger.info("[VerifFila] Fechando navegador do perfil %s via API...", profile_id)
                        mod.fechar_navegador(profile_id)
                    except Exception as ef:
                        logger.warning("[VerifFila] Erro ao fechar navegador via API: %s", ef)

                    # Esperar navegador fechar de verdade
                    time.sleep(3)
                    logger.info("[VerifFila] Navegador do perfil %s fechado.", profile_id)

            # Pausa entre perfis para não sobrecarregar
            if idx < len(bms_prontas) - 1 and not _estado_verificacao['cancelar']:
                logger.info("[VerifFila] Aguardando 5s antes do próximo perfil...")
                time.sleep(5)

    except Exception as e:
        logger.error("[VerifFila] Erro fatal: %s", e, exc_info=True)
    finally:
        _estado_verificacao['processando'] = False
        total_ok = _estado_verificacao['concluidos']
        total_err = _estado_verificacao['erros']
        _estado_verificacao['mensagem'] = f"Concluído: {total_ok} verificadas, {total_err} erros"
        logger.info("[VerifFila] Finalizado: %d OK, %d erros", total_ok, total_err)


# ============================================================================
# MODO REPROCESSAR — varre a fila (status != verificada), lê o status AO VIVO e:
#   verificada / em análise (<Xh)  -> ignora e fecha
#   em análise (>=Xh, travada)     -> cria NOVA BM + NOVA empresa e envia p/ análise
#   não verificada / rejeitada     -> REENVIA a Central de Segurança (análise)
# Pareado com o fix do charset (o re-crawl agora acha a razão social acentuada).
# ============================================================================

_estado_reprocesso = {
    'processando': False, 'cancelar': False, 'total': 0,
    'reenviadas': 0, 'novas_bm': 0, 'ignoradas': 0, 'erros': 0, 'excluidos': 0,
    'mensagem': '', 'progresso_itens': [], 'atual': '',
}


def obter_reprocesso_status():
    """Estado do reprocesso para a UI."""
    return {
        'processando': _estado_reprocesso['processando'],
        'mensagem': _estado_reprocesso.get('mensagem', ''),
        'progresso': _estado_reprocesso.get('progresso_itens', []),
        'reenviadas': _estado_reprocesso.get('reenviadas', 0),
        'novas_bm': _estado_reprocesso.get('novas_bm', 0),
        'ignoradas': _estado_reprocesso.get('ignoradas', 0),
        'erros': _estado_reprocesso.get('erros', 0),
        'excluidos': _estado_reprocesso.get('excluidos', 0),
        'total': _estado_reprocesso.get('total', 0),
    }


def cancelar_reprocesso_verificacao():
    """Cancela o reprocesso em andamento."""
    _estado_reprocesso['cancelar'] = True
    return True


def listar_grupos_adspower():
    """Lista os grupos do browser ATIVO (AdsPower OU IxBrowser) para o seletor do
    modo Reutilizar Perfis Logados / Reprocessar."""
    try:
        engine = _estado.get('browser_engine', 'adspower')
        mod = adspower_api if engine == 'adspower' else ixbrowser_api
        if hasattr(mod, 'listar_grupos'):
            grupos = mod.listar_grupos() or []
            return {'sucesso': True, 'grupos': grupos, 'engine': engine}
    except Exception as e:
        logger.warning('[Reproc] listar_grupos: %s', e)
    return {'sucesso': False, 'grupos': []}


# Trava do reprocesso-ocioso (2026-10-12). O reprocesso-ocioso foi REMOVIDO em
# 2026-10-13 (nada mais o dispara); a trava fica só porque o modo manual a consulta.
_lock_reproc_auto = threading.Lock()


def reprocessar_pendentes_agora(simultaneos=1):
    """REMOVIDO (2026-10-13, pedido do dono): o app NÃO reabre navegador sozinho para
    reenviar BMs à análise. Mantido só como stub porque o main.py expõe o nome à GUI.
    A recuperação de BMs não enviadas/não verificadas será uma versão própria."""
    return {'sucesso': False, 'mensagem': 'Reprocesso automático removido desta versão.'}


# Mensagem única mostrada quando um perfil NÃO é do GranaSocial. NUNCA revela COMO a
# ferramenta sabe (índice local/painel) — só informa a regra (pedido do dono, 2026-10-08).
_MSG_PERFIL_NAO_COMPRADO = ('Somente perfis comprados diretamente no painel do '
                            'GranaSocial podem ser utilizados no GS Creator.')


def _perfil_eh_proprio(engine, profile_id='', login='', email='', _cache=None):
    """PORTÃO DE POSSE (2026-10-08): True se o perfil é do GranaSocial.
      - admin           → sempre True (isento);
      - índice LOCAL    → bate profile_id OU login/e-mail que a ferramenta registrou;
      - PAINEL do user  → ix_profile_id/bm_email/fb_login nas BMs/compras do usuário.
    Falha de rede SEM sinal local → NÃO libera (False). O reprocesso automático das BMs
    próprias (lista do painel) não passa por aqui — já vem filtrado por user_id."""
    try:
        if usuario_eh_admin():
            return True
    except Exception:
        pass
    pid = str(profile_id or '').strip()
    if _cache is not None and pid and pid in _cache:
        return _cache[pid]

    resultado = False
    try:
        if _perfis_proprios and (_perfis_proprios.contem(engine, pid)
                                 or _perfis_proprios.contem_identificador(login, email)):
            resultado = True
        else:
            try:
                from server.painel_integration import perfil_pertence_ao_usuario
                r = perfil_pertence_ao_usuario(profile_id=pid, bm_email=email,
                                               fb_login=login, engine=engine)
            except Exception:
                r = None
            if r is True:
                resultado = True
                try:  # cacheia offline p/ as próximas vezes
                    if _perfis_proprios:
                        _perfis_proprios.registrar(engine=engine, profile_id=pid,
                                                   login=login, email=email)
                except Exception:
                    pass
            # r is False → não é do usuário; r is None → rede caiu → não libera
    except Exception as e:
        logger.warning('[Posse] verificação falhou (%s) — perfil tratado como não-próprio.', e)
        resultado = False

    if _cache is not None and pid:
        _cache[pid] = resultado
    return resultado


def _filtrar_perfis_proprios(engine, perfis):
    """Separa a lista do scan (reuso/reprocesso por grupo) em (permitidos, bloqueados).
    Extrai login da observação (remark) p/ casar com o painel/índice local."""
    permitidos, bloqueados = [], 0
    _cache = {}
    for _p in perfis:
        pid = str(_p.get('user_id') or _p.get('profile_id') or '').strip()
        try:
            _cred = _parse_credenciais_remark(_p.get('remark') or _p.get('note') or '')
        except Exception:
            _cred = {}
        _login = (_cred.get('login') or _p.get('login')
                  or _p.get('name') or _p.get('profile_name') or '')
        _email = _p.get('email') or ''
        if _perfil_eh_proprio(engine, pid, _login, _email, _cache=_cache):
            permitidos.append(_p)
        else:
            bloqueados += 1
            logger.info('[Posse] perfil %s ignorado (não é do GranaSocial).', pid or '?')
    return permitidos, bloqueados


def iniciar_reprocesso_verificacao(grupo_id='', horas_analise=24, simultaneos=1,
                                   forcar_nova_bm=False):
    """Inicia o modo Reprocessar: varre os perfis do AdsPower do GRUPO escolhido,
    abre cada um, descobre a BM ao vivo, lê o status e:
      verificada / em análise (<Xh) -> ignora;
      não verificada / rejeitada / em análise (>=Xh) -> cria BM nova + empresa nova.

    `forcar_nova_bm=True` (REUTILIZAR PERFIL LOGADO): NÃO pula perfis já concluídos
    e, em cada perfil do grupo, SEMPRE cria uma BM nova + envia p/ análise (mesmo que
    já tenha BM ativa/não usada). Usa a mesma automação/verificação dos fluxos.
    """
    if _estado_reprocesso['processando'] or _lock_reproc_auto.locked():
        return {'sucesso': False, 'mensagem': 'Reprocesso já em andamento'}
    if _estado['processando'] or _estado_verificacao['processando']:
        return {'sucesso': False, 'mensagem': 'Aguarde o processamento/verificação atual terminar'}

    engine = _estado.get('browser_engine', 'adspower')
    mod = adspower_api if engine == 'adspower' else ixbrowser_api
    if not hasattr(mod, 'listar_perfis'):
        return {'sucesso': False, 'mensagem': f'Listagem de perfis não suportada no engine {engine} (use AdsPower).'}

    try:
        conex = mod.verificar_conexao()
        if not conex.get('conectado'):
            return {'sucesso': False, 'mensagem': f'{engine} não conectado: {conex.get("mensagem","")}'}
    except Exception as e:
        return {'sucesso': False, 'mensagem': f'Erro ao checar {engine}: {e}'}

    # Coleta TODOS os perfis do grupo (pagina de 100 em 100).
    perfis = []
    try:
        _pg = 1
        while True:
            lote = mod.listar_perfis(grupo_id=(str(grupo_id) or None), page=_pg, limit=100) or []
            if not lote:
                break
            # REAPROVEITAR NÃO CONCLUÍDOS (2026-07-13): pula quem JÁ está concluído/morto
            # pelo marcador na OBSERVAÇÃO (remark) — "BM EM ANALISE" (já enviado p/ análise)
            # ou "BM BLOQUEADA" (as 2 BMs vieram restritas). Assim nem ABRE esses (economiza
            # tempo) e vai direto nos perfis não concluídos. Fonte AO VIVO do AdsPower →
            # se o usuário editar/apagar um perfil, não quebra.
            for _p in lote:
                # No modo REUTILIZAR PERFIL LOGADO processa TODOS (mesmo os já com
                # "BM EM ANALISE"): sempre há espaço p/ criar mais uma BM.
                if not forcar_nova_bm:
                    _rmk = str((_p.get('remark') or '')).upper()
                    if ('BM EM ANALISE' in _rmk or 'BM EM ANÁLISE' in _rmk
                            or 'BM BLOQUEADA' in _rmk):
                        continue   # já concluído/morto → não reabre
                perfis.append(_p)
            if len(lote) < 100:
                break
            _pg += 1
            if _pg > 50:  # trava de segurança (5000 perfis)
                break
    except Exception as e:
        return {'sucesso': False, 'mensagem': f'Erro ao listar perfis: {e}'}

    if not perfis:
        return {'sucesso': False, 'mensagem': 'Nenhum perfil encontrado nesse grupo do AdsPower.'}

    # ── PORTÃO DE POSSE (2026-10-08) ─────────────────────────────────────────────
    # Só abre perfis COMPRADOS do GranaSocial (índice local oculto OU painel do próprio
    # usuário). Admin é isento. Os de terceiros adicionados à mão no AdsPower são
    # ignorados — e a mensagem NÃO revela como a ferramenta sabe.
    perfis, _bloqueados = _filtrar_perfis_proprios(engine, perfis)
    if not perfis:
        return {'sucesso': False, 'mensagem': _MSG_PERFIL_NAO_COMPRADO, 'bloqueados': _bloqueados}

    try:
        _hrs = float(horas_analise or 24)
    except Exception:
        _hrs = 24.0
    try:
        _sim = max(1, min(10, int(simultaneos or 1)))
    except Exception:
        _sim = 1
    # MODO REUTILIZAR: espelha os perfis na INTERFACE PRINCIPAL (tabela + terminal
    # ao vivo), igual à importação — o worker atualiza _estado['progresso'] em tempo real.
    if forcar_nova_bm:
        _perfis_ui = []
        for _p in perfis:
            _pid = _p.get('user_id') or _p.get('profile_id') or ''
            _nm = str(_p.get('name') or _p.get('profile_name') or _p.get('remark') or _pid or '').strip()
            _perfis_ui.append({'login': _nm or str(_pid), 'senha': '', 'email': '',
                               'profile_id': _pid, 'origem': 'reuso_logado'})
        _carregar_perfis_no_estado(_perfis_ui, origem='reuso_logado')
        for _i, _p in enumerate(perfis):
            try:
                _estado['progresso'][_i]['profile_id'] = _p.get('user_id') or _p.get('profile_id') or ''
            except Exception:
                pass

    # Liga a flag JÁ (antes da thread): um 2º clique no intervalo até a thread ligá-la
    # disparava 2 reprocessos do mesmo grupo (mesmo perfil aberto 2×).
    _estado_reprocesso['processando'] = True
    threading.Thread(target=_processar_reprocesso,
                     args=(perfis, engine, _hrs, _sim, bool(forcar_nova_bm)),
                     daemon=True).start()
    _modo = 'REUTILIZAR (sempre BM nova)' if forcar_nova_bm else 'reprocesso'
    _msg = f'{len(perfis)} perfil(is) em {_modo} ({_sim} simultâneo(s))'
    if _bloqueados:
        _msg += f'. {_bloqueados} perfil(is) ignorado(s) — ' + _MSG_PERFIL_NAO_COMPRADO
    return {'sucesso': True, 'mensagem': _msg,
            'total': len(perfis), 'bloqueados': _bloqueados}


def _reproc_extrair_debug(res_abrir):
    """Extrai (debugging_address, webdriver_path) do retorno de abrir_navegador —
    mesma lógica robusta do fluxo da fila de verificação."""
    debugging_address = res_abrir.get('debugging_address', '')
    webdriver_path = res_abrir.get('webdriver', '')
    ws_url = res_abrir.get('ws', '')
    if not debugging_address:
        dados_raw = res_abrir.get('data', {})
        if isinstance(dados_raw, dict):
            debugging_address = dados_raw.get('debugging_address', '')
            if not webdriver_path:
                webdriver_path = dados_raw.get('webdriver', '')
            if not ws_url:
                ws_raw = dados_raw.get('ws', '')
                if isinstance(ws_raw, dict):
                    ws_url = ws_raw.get('puppeteer', '') or ws_raw.get('selenium', '') or ''
                elif isinstance(ws_raw, str):
                    ws_url = ws_raw
    if not debugging_address and ws_url and isinstance(ws_url, str):
        import re as _re
        _m = _re.search(r'ws://([^/]+)', ws_url)
        if _m:
            debugging_address = _m.group(1)
    return debugging_address, webdriver_path


def _reproc_title_case(texto):
    """Title Case igual ao do certificado da Receita: iniciais maiúsculas, resto
    minúsculo, preposições minúsculas no meio. Usa .title() por palavra (não
    .capitalize()) p/ tratar tokens alfanuméricos — ex.: '2559SW' -> '2559Sw'."""
    if not texto:
        return ''
    preps = {'da', 'de', 'do', 'das', 'dos', 'e', 'em', 'na', 'no', 'para', 'por', 'com'}
    out = []
    for idx, p in enumerate(str(texto).strip().split()):
        out.append(p.lower() if (idx > 0 and p.lower() in preps) else p.title())
    return ' '.join(out)


def _reproc_limpar_cnpj(texto):
    if not texto:
        return ''
    import re as _re
    t = _re.sub(r'^[\s\d.\-/]+', '', str(texto))
    t = _re.sub(r'[\s\d.\-/]+$', '', t)
    return t.strip()


def _reproc_preparar_empresa(tipo_emp, cb):
    """SÓ escolhe a empresa (nome/CNPJ/endereço) do estoque — SEM criar o site nem
    debitar token. Retorna empresa_dados (com cnpj) p/ criar a BM com a razão social.
    O site é criado logo em seguida por _reproc_criar_site(), ANTES de criar a 2ª BM
    (2026-07-31) — o e-mail da BM precisa nascer no domínio do site novo. A cota X/30
    da raiz só é consumida quando o domínio é validado na Meta, então uma 2ª BM que
    bloqueie na criação não desperdiça cota.
    (Split de _reproc_preparar_empresa_site — 2026-07-25.)"""
    if cb:
        cb(f'🏢 Buscando empresa {str(tipo_emp).upper()} disponível...')
    res_emp = buscar_empresas_ativas(tipo=tipo_emp)
    if not res_emp.get('sucesso') or not res_emp.get('empresas'):
        raise RuntimeError(f"Sem empresa {str(tipo_emp).upper()} disponível: "
                           f"{str(res_emp.get('mensagem', '') or 'estoque vazio')[:80]}")
    empresa_raw = next((e for e in (res_emp.get('empresas') or [])
                        if e.get('cnpj') and (e.get('razao_social') or e.get('nome_fantasia'))), None)
    if not empresa_raw:
        raise RuntimeError('Estoque sem empresa com CNPJ/razão válidos para a BM.')

    def g(k):
        return (empresa_raw or {}).get(k) or ''
    empresa_dados = {
        'razao_social': _reproc_title_case(_reproc_limpar_cnpj(g('razao_social'))),
        'nome_fantasia': _reproc_title_case(_reproc_limpar_cnpj(g('nome_fantasia'))),
        'cnpj': g('cnpj'),
        'logradouro': _reproc_title_case(g('logradouro')),
        'numero': g('numero'),
        'complemento': _reproc_title_case(g('complemento')),
        'bairro': _reproc_title_case(g('bairro')),
        'municipio': _reproc_title_case(g('municipio')),
        'uf': (g('uf') or '').upper(),
        'cep': g('cep'),
        'url_completa': '',   # sem site ainda (criado depois)
        'telefone': g('telefone'),
        'atividade': _reproc_title_case(g('atividade')),
    }
    return empresa_dados


def _reproc_criar_site(empresa_dados, cb):
    """Cria o SITE do CNPJ de `empresa_dados` (1 token, server-side) e enriquece o
    endereço/URL faltante. Retorna site_cache. Levanta RuntimeError se falhar.
    Chamado ANTES de criar a 2ª BM (2026-07-31), para que o e-mail dela nasça no
    domínio deste site."""
    cnpj = str((empresa_dados or {}).get('cnpj', '') or '').strip()
    if not cnpj:
        raise RuntimeError('Empresa sem CNPJ — não dá p/ criar o site.')
    res_site = None
    ult = ''
    for _try in range(1, 4):
        if cb:
            cb(f'🌐 Criando site da empresa (1 token) [tentativa {_try}/3]...')
        try:
            _r = criar_site_empresa(cnpj, callback_status=cb,
                                    deve_continuar=lambda: not _estado.get('cancelar', False))
        except Exception as ce:
            ult = f'exceção: {ce}'
            time.sleep(min(8, 2 + _try * 2))
            continue
        if _r.get('sucesso'):
            res_site = _r
            break
        ult = str(_r.get('mensagem', '') or 'sem resposta')
        time.sleep(min(8, 2 + _try * 2))
    if not res_site or not res_site.get('sucesso'):
        raise RuntimeError(f"Não consegui criar o site (último erro: {ult[:100]})")
    emp_api = res_site.get('empresa', {}) or {}
    site_cache = {
        'site_id': res_site['site_id'], 'url': res_site['url'],
        'subdominio': res_site.get('subdominio', ''),
        'dominio_raiz': res_site.get('dominio_raiz', ''),
        # E-mail próprio do site (criado pelo PAINEL junto com o site) — a 2ª BM
        # nasce com o e-mail do SEU próprio domínio, não do site da 1ª.
        'email': str(res_site.get('email', '') or ''),
        'email_senha': str(res_site.get('email_senha', '') or ''),
        'email_servidor': str(res_site.get('email_servidor', '') or ''),
    }
    # Mesma GARANTIA da 1ª BM: sem e-mail próprio do subdomínio não seguimos. Cair no
    # público (@gspromax.com) inviabilizaria a verificação por e-mail — a Meta aceita
    # uma empresa por domínio-raiz, e a raiz pública é compartilhada por todos.
    if not site_cache['email']:
        raise RuntimeError(
            'Site da 2ª BM criado mas SEM e-mail próprio (o painel não devolveu '
            f"email/email_senha). Verifique o MX da raiz {site_cache.get('dominio_raiz', '?')}.")
    if empresa_dados is not None:
        empresa_dados['url_completa'] = res_site.get('url') or empresa_dados.get('url_completa', '')
        # O endereço vem do CNPJ em MAIÚSCULAS. No CERTIFICADO/site (painel) fica
        # maiúsculo (igual à Receita) — isso NÃO é tocado aqui. Mas o que é digitado
        # na BM (este empresa_dados) vai em Title Case: iniciais maiúsculas e resto
        # minúsculo, como um humano digitaria (ex.: 'AV AMERICA' -> 'Av America').
        _tc = {'logradouro', 'numero', 'complemento', 'bairro', 'municipio', 'atividade'}
        for _k in ('logradouro', 'numero', 'complemento', 'bairro',
                   'municipio', 'uf', 'cep', 'telefone', 'atividade'):
            if (not str(empresa_dados.get(_k, '') or '').strip()
                    and str(emp_api.get(_k, '') or '').strip()):
                _v = str(emp_api.get(_k) or '')
                if _k == 'uf':
                    _v = _v.upper()
                elif _k in _tc:
                    _v = _reproc_title_case(_v)
                empresa_dados[_k] = _v
    return site_cache


def _reproc_preparar_empresa_site(tipo_emp, cb):
    """Composição EMPRESA + SITE juntos (fluxo Reprocessar). Retorna
    (empresa_dados, site_cache). Mantida p/ compat; os fluxos de RETRY da 2ª BM
    usam _reproc_preparar_empresa() + _reproc_criar_site() separados (site diferido)."""
    empresa_dados = _reproc_preparar_empresa(tipo_emp, cb)
    site_cache = _reproc_criar_site(empresa_dados, cb)
    return empresa_dados, site_cache


def _parse_credenciais_remark(remark):
    """Extrai login/senha/2fa da OBSERVAÇÃO (remark) do perfil (AdsPower/IxBrowser).
    Formato gravado pelos apis: '🆔 Login: <login>', '🔐 Senha: <senha>', '🔑 2FA: <tfa>'
    (também aceita sem emoji e rótulos alternativos). Usado no REUTILIZAR p/ RE-LOGAR
    quando a sessão (cookie) expirou e o perfil cai na tela de usuário/senha.
    Retorna {'login','senha','tfa'} (ausentes = '')."""
    import re as _re
    txt = str(remark or '')

    def _g(*rotulos):
        for rot in rotulos:
            m = _re.search(rot + r'\s*[:：]\s*([^\r\n]+)', txt, _re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ''

    return {
        'login': _g('Login', 'ID', r'Usu[aá]rio', 'User', 'UID'),
        'senha': _g('Senha', 'Password', 'Pass', 'Pwd'),
        'tfa': _g('2FA', 'TOTP', '2fa secret', 'Secret'),
    }


def _reproc_checkpoint_morto(drv, cb=None):
    """True se o perfil está num checkpoint SEM SAÍDA (não automatizável):
    - captcha de IMAGEM ("Digite o texto da imagem" / "Confirme que você é uma pessoa"), ou
    - SELFIE de vídeo ("Confirme sua identidade" / "selfie de vídeo").
    Se estiver na tela "Confirme que você é humano" (só um botão Continuar), CLICA
    Continuar e reavalia — pois é ela que leva ao captcha de imagem/selfie."""
    def _t():
        try:
            return (drv.evaluate_page("() => (document.body && document.body.innerText) || ''") or '').lower()
        except Exception:
            return ''
    def _u():
        try:
            return (drv.current_url or '').lower()
        except Exception:
            return ''
    _SELFIE = ['selfie de vídeo', 'selfie de video', 'confirme sua identidade',
               'pessoa real com uma selfie', 'iniciar selfie', 'video selfie',
               'confirm your identity', 'real person with a video selfie']
    _IMG = ['digite o texto da imagem', 'texto da imagem', 'type the text in the image',
            'enter the text you see', 'digite o texto']

    def _morto(txt):
        return any(k in txt for k in _SELFIE) or any(k in txt for k in _IMG)

    t = _t()
    if _morto(t):
        return True
    u = _u()
    if 'checkpoint' in u and ('é humano' in t or 'e humano' in t or "you're human" in t
                              or 'you are human' in t or 'confirme que você é humano' in t):
        if cb:
            cb('Checkpoint "confirme que você é humano" — clicando Continuar...')
        try:
            drv.evaluate_page(r"""() => {
                function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                  var s=getComputedStyle(el); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';}
                var alvos=['continuar','continue','continuer'];
                var els=document.querySelectorAll('div[role="button"],button,a[role="button"],span[role="button"]');
                for(var i=0;i<els.length;i++){ if(!vis(els[i])) continue;
                  var x=(els[i].innerText||'').trim().toLowerCase();
                  for(var j=0;j<alvos.length;j++){ if(x===alvos[j]){ els[i].click(); return true; } } }
                return false;
            }""")
        except Exception:
            pass
        time.sleep(4)
        if _morto(_t()):
            return True
    return False


def _processar_reprocesso(perfis, engine='adspower', horas_analise=24.0, simultaneos=1,
                          forcar_nova_bm=False):
    """Thread do reprocesso — varre perfis do AdsPower com N navegadores em PARALELO.
    Abre o perfil, DESCOBRE a BM ao vivo, lê o status e:
      verificada -> ignora; qualquer outro status -> cria BM nova + empresa nova.

    `forcar_nova_bm=True` (modo REUTILIZAR PERFIL LOGADO): ignora a BM existente e o
    status — SEMPRE cria uma BM NOVA no perfil (mesmo que já tenha BM ativa/não usada)
    e envia p/ análise. A BM nova já vira a selecionada nos fluxos (DataCrazy/Gupshup),
    porque o `business_id` novo é o usado dentro do `_reproc_criar_nova_bm`.
    """
    simultaneos = max(1, min(10, int(simultaneos or 1)))
    _estado_reprocesso.update(processando=True, cancelar=False, total=len(perfis),
                              reenviadas=0, novas_bm=0, ignoradas=0, erros=0, excluidos=0,
                              progresso_itens=[], mensagem='Iniciando reprocesso...')
    # No modo REUTILIZAR, liga o 'processando' da interface principal p/ a GUI
    # mostrar o terminal ao vivo + contadores (igual à importação/processamento).
    if forcar_nova_bm:
        _estado['processando'] = True
        _estado['pausado'] = False
    for p in perfis:
        _estado_reprocesso['progresso_itens'].append({
            'profile_id': p.get('user_id') or p.get('profile_id') or '',
            'bm_name': p.get('name') or p.get('profile_name') or '',
            'status': 'Aguardando', 'mensagem': '', 'cor': '#3F3F46',
        })

    user = _estado.get('usuario_logado', '')
    captcha_token = _estado.get('captcha_token') or _ler_captcha_token(user)
    sms24h_token = _estado.get('sms24h_token') or _ler_config('sms24h_token', '', user)
    tipo_empresa = _estado.get('tipo_empresa') or _ler_config('tipo_empresa', 'mei', user) or 'mei'
    datacrazy_email = _estado.get('datacrazy_email') or _ler_config('datacrazy_email', '', user)
    datacrazy_senha = _estado.get('datacrazy_senha') or _ler_config('datacrazy_senha', '', user)

    # Provedor de SMS escolhido na GUI (ex.: smsbower). Sem isto, a criação da BM
    # nova caía no default 'sms24h' e ignorava o provedor selecionado na tela.
    sms_provedor = (str(_estado.get('sms_provedor', '') or '').strip().lower()
                    or _ler_config('sms_provedor', 'sms24h', user) or 'sms24h')

    mod = adspower_api if engine == 'adspower' else ixbrowser_api

    from server.verificacao_bm import (
        ler_status_verificacao_ao_vivo, _gerar_variantes_telefone,
        executar_verificacao_completo_datacrazy_pro_max)
    from server.automacao_facebook import (
        conectar_selenium, executar_automacao_perfil, extrair_business_id_da_url)
    from server.gerar_numero import gerar_numero_aleatorio
    # Checkpoint DEAD-END sobe como BaseException (ver except no _proc_um).
    try:
        from server.etapa_verificacao_negocio import _PerfilQueimado as _PerfilQueimadoReproc
    except Exception:
        class _PerfilQueimadoReproc(BaseException):
            pass

    # Em paralelo, o afb entra em modo paralelo (não rouba foco de janela).
    # Liga os DOIS mecanismos de modo paralelo (foco do FB + bring_to_front do
    # playwright) — em paralelo NENHUMA ação de nível-SO roda (senão N navegadores
    # disputariam a janela e congelariam o Windows).
    _ativar_modo_paralelo(simultaneos > 1)

    _clock = threading.Lock()   # protege contadores compartilhados

    def _inc(chave):
        with _clock:
            _estado_reprocesso[chave] = _estado_reprocesso.get(chave, 0) + 1

    def _espelhar_ui(i, st, cor, msg):
        """No modo REUTILIZAR PERFIL LOGADO, espelha o progresso na INTERFACE
        PRINCIPAL (mesma tabela + terminal ao vivo da importação): atualiza
        _estado['progresso'][i] e recalcula os contadores concluidos/erros."""
        if not forcar_nova_bm:
            return
        try:
            prog = _estado.get('progresso', [])
            if 0 <= i < len(prog):
                if st is not None:
                    prog[i]['status'] = st
                if cor is not None:
                    prog[i]['cor'] = cor
                if msg is not None:
                    prog[i]['mensagem'] = str(msg)
                if st in ('Concluído', 'Erro'):
                    _estado['concluidos'] = sum(1 for x in prog if x.get('status') == 'Concluído')
                    _estado['erros'] = sum(1 for x in prog if x.get('status') == 'Erro')
        except Exception:
            pass

    logger.info("[Reproc] Iniciando reprocesso de %d perfil(is) [%s] com %d simultâneo(s)",
                len(perfis), engine, simultaneos)

    def _proc_um(idx, p):
        profile_id = p.get('user_id') or p.get('profile_id') or ''
        # Credenciais da OBSERVAÇÃO (remark) do perfil — p/ RE-LOGAR automaticamente
        # se a sessão (cookie) tiver expirado e o perfil cair na tela de usuário/senha.
        # Os perfis reutilizados têm sempre Login/Senha/2FA na observação.
        _cred = _parse_credenciais_remark(p.get('remark') or p.get('note') or '')
        perfil_data = {'login': _cred['login'], 'senha': _cred['senha'], 'tfa': _cred['tfa']}

        def _set(st, cor, msg, _i=idx):
            it = _estado_reprocesso['progresso_itens'][_i]
            it['status'] = st; it['cor'] = cor; it['mensagem'] = msg
            _estado_reprocesso['mensagem'] = f"[{_i+1}/{len(perfis)}] {msg[:60]}"
            _espelhar_ui(_i, st, cor, msg)

        def _cb(msg, _i=idx):
            _estado_reprocesso['progresso_itens'][_i]['mensagem'] = str(msg)
            _estado_reprocesso['mensagem'] = f"[{_i+1}/{len(perfis)}] {str(msg)[:60]}"
            _espelhar_ui(_i, None, None, str(msg))

        if not profile_id:
            _set('Erro', '#FF4444', '❌ Perfil sem ID'); _inc('erros'); return

        _set('Processando', '#F2C94C', 'Abrindo navegador...')
        drv = None
        navegador_aberto = False
        business_id = ''   # definido já aqui p/ o handler de checkpoint (except abaixo)
        try:
            res_abrir = mod.abrir_navegador(profile_id)
            if not res_abrir.get('sucesso'):
                raise RuntimeError(f"Falha ao abrir perfil: {res_abrir.get('mensagem','')}")
            navegador_aberto = True
            dbg, wpath = _reproc_extrair_debug(res_abrir)
            if not dbg:
                raise RuntimeError("Endereço de debug não encontrado")
            time.sleep(2)
            drv = conectar_selenium(dbg, wpath)
            if not drv:
                raise RuntimeError("Falha ao conectar Playwright")
            try:
                from server import session_guard as _sg
                _sg.vincular_perfil(drv, profile_id, mod, perfil_data)
            except Exception:
                pass

            # ── CHECKPOINT SEM SAÍDA (captcha de imagem / selfie) -> EXCLUI perfil ──
            _cb('Verificando checkpoint da conta...')
            try:
                drv.goto("https://www.facebook.com/")
                try:
                    from server.page_state_manager import PageStateManager
                    PageStateManager.wait_until_stable(drv, timeout=25, settle_time=1.2,
                                                       f5_after=18, callback_status=None)
                except Exception:
                    time.sleep(4)
            except Exception:
                pass
            if _reproc_checkpoint_morto(drv, _cb):
                _cb('🗑️ Checkpoint sem saída — fechando e excluindo o perfil...')
                try:
                    drv.quit()
                except Exception:
                    pass
                drv = None
                try:
                    mod.fechar_navegador(profile_id)  # AdsPower não deleta perfil ABERTO
                except Exception:
                    pass
                navegador_aberto = False
                time.sleep(2)
                _excluir = getattr(mod, 'deletar_perfil', None)
                _ok_del = bool(_excluir and _excluir(profile_id))
                _set('Concluído' if _ok_del else 'Erro',
                     '#9B59FF' if _ok_del else '#FF8800',
                     '🗑️ Perfil EXCLUÍDO (checkpoint selfie/captcha)' if _ok_del
                     else '⚠️ Checkpoint sem saída — falha ao excluir perfil')
                _inc('excluidos')
                return

            # ── MODO "REUTILIZAR PERFIL LOGADO" (sempre criar BM nova) ──
            # Ignora a BM existente e o status: fecha o driver de checagem e cria
            # uma BM NOVA (empresa/site novos) no perfil já logado, enviando p/
            # análise. Vale mesmo p/ perfil com BM ativa/não usada — sempre há
            # espaço p/ mais uma. A nova BM já é a selecionada nos fluxos (o
            # business_id novo é o usado no DataCrazy/Gupshup dentro do helper).
            if forcar_nova_bm:
                # GARANTE a SESSÃO antes de gastar empresa/site/SMS: perfil LOGADO
                # segue para criar a BM; se o COOKIE expirou, RE-LOGA com as
                # credenciais da OBSERVAÇÃO (login/senha/2FA). Só sem conseguir logar
                # é que vira erro (não desperdiça recursos criando na conta deslogada).
                _cb('🔓 Conferindo a sessão do perfil (Feed/Reels)...')
                _logado = False
                try:
                    from server.automacao_facebook import (
                        verificar_login_facebook, fazer_login_facebook)
                    _logado = verificar_login_facebook(drv, timeout=8, callback_status=_cb)
                    if (not _logado and perfil_data.get('login')
                            and perfil_data.get('senha')):
                        _cb('🔑 Sessão expirada — relogando com usuário/senha (+2FA) da observação...')
                        _logado = fazer_login_facebook(
                            drv, perfil_data.get('login', ''), perfil_data.get('senha', ''),
                            perfil_data.get('tfa') or None, _cb)
                except Exception as _le:
                    logger.warning('[Reproc] verificação/login do perfil falhou: %s', _le)
                    _logado = False
                if not _logado:
                    _set('Erro', '#FF8800',
                         '⚠️ Perfil não logado (cookie expirado e sem/errada credencial na observação).')
                    _inc('erros')
                    return

                _cb('🆕 Reutilizar perfil logado — criando BM NOVA (sempre)...')
                try:
                    drv.quit()
                except Exception:
                    pass
                drv = None
                ok_nova = _reproc_criar_nova_bm(
                    mod, profile_id, perfil_data, tipo_empresa,
                    captcha_token, sms24h_token, datacrazy_email, datacrazy_senha,
                    executar_automacao_perfil,
                    executar_verificacao_completo_datacrazy_pro_max,
                    _gerar_variantes_telefone, gerar_numero_aleatorio, _cb,
                    sms_provedor=sms_provedor)
                # E-MAIL: a 1ª BM foi descartada e a 2ª nasceu com e-mail NOVO. Troca o
                # e-mail nos DADOS (nome) e na OBSERVAÇÃO do perfil para o novo.
                _novo_email = ok_nova.get('novo_email', '') or ''
                if _novo_email:
                    try:
                        _sub = getattr(mod, 'substituir_email_perfil', None)
                        if _sub:
                            _sub(profile_id, _novo_email)
                    except Exception as _es:
                        logger.warning('[Reproc] troca de e-mail falhou: %s', _es)
                # TAG: define pelo DESFECHO REAL da 2ª BM (SUBSTITUI a antiga, não empilha).
                if ok_nova.get('sucesso'):
                    _tag_desfecho = "💙 BM EM ANALISE 💙"
                    _set('Concluído', '#00C74F', f'✅ BM nova enviada p/ análise | {_novo_email}')
                    _inc('novas_bm')
                elif ok_nova.get('bm_bloqueada'):
                    _tag_desfecho = "💔 BM BLOQUEADA 💔"
                    _set('Erro', '#FF4444', f"🚫 2ª BM bloqueada | {_novo_email}")
                    _inc('erros')
                else:
                    _tag_desfecho = "⚠️ NÃO ENVIADA"
                    _set('Erro', '#FF8800', f"⚠️ BM nova não concluída: {ok_nova.get('mensagem','')[:40]}")
                    _inc('erros')
                try:
                    _def = getattr(mod, 'definir_tag_desfecho_perfil', None)
                    if _def:
                        _def(profile_id, _tag_desfecho)
                    else:
                        mod.adicionar_tags_perfil(profile_id, [_tag_desfecho])
                except Exception as _et:
                    logger.warning('[Reproc] troca de tag falhou: %s', _et)
                return

            # ── DESCOBRE a BM ao vivo (business_id) ──
            # FIX (auditoria 2026-10-12): no reprocesso-ocioso a BM a reprocessar vem do
            # PAINEL (business_id exato). Antes ele era descartado e a BM era "descoberta"
            # pela /latest/home — que abre a ÚLTIMA BM usada: num perfil com 2 BMs o bot
            # reprocessava a BM ERRADA. Com o id do painel, vai direto na BM certa.
            _cb('Descobrindo a BM do perfil...')
            business_id = str(p.get('_business_id') or '').strip()
            for _url in (() if business_id else
                         ("https://business.facebook.com/latest/home",
                          "https://business.facebook.com/latest/settings/business_info")):
                try:
                    drv.goto(_url)
                except Exception:
                    continue
                try:
                    from server.page_state_manager import PageStateManager
                    PageStateManager.wait_until_stable(drv, timeout=30, settle_time=1.2,
                                                       f5_after=20, callback_status=None)
                except Exception:
                    time.sleep(5)
                business_id = extrair_business_id_da_url(drv.current_url or '')
                if business_id:
                    break
            if not business_id:
                _set('Concluído', '#6B7280', '⚪ Sem BM neste perfil — ignorado')
                _inc('ignoradas'); return

            # ── LÊ o status ao vivo ──
            _cb('Lendo status de verificação...')
            info = ler_status_verificacao_ao_vivo(drv, business_id, _cb)
            st = info.get('status')

            # REGRA (2026-07-13): SÓ ignora se VERIFICADA. Qualquer outro status →
            # CONTINUA a BM existente (retomar) se ela tiver site+empresa no painel e NÃO
            # estiver restrita; só cria BM NOVA se restrita.
            if st == 'verificada':
                # Grava o status REAL no painel (igual ao Monitor) — senão uma BM marcada
                # 'erro'/'rejeitada' lá voltava ao reprocesso-ocioso a cada ciclo.
                try:
                    from server.painel_integration import atualizar_status_analise
                    atualizar_status_analise(business_id, 'verificada')
                except Exception as _pv:
                    logger.debug('[Reproc] status verificada no painel: %s', _pv)
                _set('Concluído', '#00C74F', '✅ Já verificada — ignorada')
                _inc('ignoradas'); return

            _rotulo = {'em_analise': 'Em análise', 'nao_verificada': 'Não verificada',
                       'rejeitada': 'Rejeitada'}.get(st, 'Não verificada')

            # ── CONTINUAR a BM EXISTENTE (retomar) ──
            # Se a BM já tem SITE + empresa no painel e NÃO está restrita: NÃO recria do
            # zero → retoma (compra SMS novo → atualiza empresa/site/certificado → reenvia
            # p/ análise). RESTRITA → cria 1 BM nova; se a NOVA também restringir, o
            # _resumir marca "💔 BM BLOQUEADA 💔" e MANTÉM o perfil. Sem registro no painel
            # (não dá p/ retomar) → cai no fallback de criar BM nova.
            _bmp = None
            try:
                from server.painel_integration import buscar_bm_por_business_id
                _bmp = buscar_bm_por_business_id(business_id)
            except Exception as _bpe:
                logger.warning('[Reproc] buscar_bm_por_business_id falhou: %s', _bpe)
            if _bmp and str(_bmp.get('site_url') or '').strip():
                _cb(f'♻️ {_rotulo} — CONTINUANDO a BM existente (SMS novo → empresa/site/cert → análise)...')
                _empresa_ret = {'cnpj': _bmp.get('cnpj', '') or '',
                                'razao_social': _bmp.get('razao_social', '') or ''}
                _site_ret = {'site_id': _bmp.get('site_id', '') or '', 'url': _bmp.get('site_url', '') or ''}
                _num_ret = f"+{gerar_numero_aleatorio()}"
                _empresa_ret['telefone'] = _num_ret
                _var_ret = _gerar_variantes_telefone(_num_ret)
                _metodo_ret = 'datacrazy'   # Turbo (OAuth da Meta direto)
                try:
                    _rr = _resumir_bm_existente(
                        mod, profile_id, perfil_data, business_id, _empresa_ret, _site_ret,
                        _metodo_ret, captcha_token, tipo_empresa, sms24h_token,
                        datacrazy_email, datacrazy_senha, _num_ret, _var_ret,
                        _bmp.get('bm_email', '') or '', drv, _cb, sms_provedor=sms_provedor)
                except Exception as _rex:
                    logger.exception('[Reproc] retomar BM existente falhou: %s', _rex)
                    _rr = {'em_analise': False, 'bm_bloqueada': False, 'mensagem': str(_rex)}
                # FIX (auditoria 2026-10-12): NÃO zera o `drv` aqui. No caso NÃO-restrito o
                # _resumir_bm_existente deixa o driver VIVO; com `drv = None` o finally não
                # dava quit() e a instância do Playwright (processo node) VAZAVA a cada perfil
                # reprocessado. No caso restrito ele já fez quit() — o 2º quit é inócuo.
                _bid_rr = str(_rr.get('business_id') or business_id)
                if _rr.get('em_analise'):
                    _set('Concluído', '#00C74F', '💙 Retomada — enviada p/ análise')
                    _inc('reenviadas')
                    # Painel: BM de volta em análise (sai da lista rejeitada/erro do reprocesso).
                    _painel_registrar_em_analise(_bid_rr, site_id=_site_ret.get('site_id', ''),
                                                 site_url=_site_ret.get('url', ''),
                                                 empresa_dados=_empresa_ret, profile_id=profile_id,
                                                 fb_login=perfil_data.get('login', ''))
                    try:
                        mod.adicionar_tags_perfil(profile_id, ["💙 BM EM ANALISE 💙", "♻️ REPROCESSADA"])
                    except Exception:
                        pass
                elif _rr.get('bm_bloqueada'):
                    _set('Erro', '#FF4444', '🔴 BM bloqueada (perfil mantido)')
                    _inc('erros')
                    # WABA desabilitada NÃO é 'bloqueada' no painel (lá é "WABA caiu / sem
                    # recurso" ou 'recorrida') — só reporta bloqueio real da BM.
                    if not _rr.get('waba_desabilitada'):
                        _painel_desfecho(_bid_rr, 'bloqueada', str(_rr.get('mensagem', ''))[:200])
                else:
                    _set('Erro', '#FF8800', f"⚠️ Retomada não concluída: {str(_rr.get('mensagem',''))[:45]}")
                    _inc('erros')
                    # Renova o creator_result_at → o reprocesso-ocioso só tenta de novo após
                    # o descanso (2h), em vez de reabrir a mesma BM a cada ciclo.
                    _painel_desfecho(_bid_rr, 'erro', str(_rr.get('mensagem', ''))[:200])
                return

            # ── FALLBACK: sem site no painel → cria BM nova + empresa nova ──
            _cb(f'♻️ {_rotulo} — sem site no painel; criando BM nova + empresa nova...')
            try:
                drv.quit()
            except Exception:
                pass
            drv = None
            ok_nova = _reproc_criar_nova_bm(
                mod, profile_id, perfil_data, tipo_empresa,
                captcha_token, sms24h_token, datacrazy_email, datacrazy_senha,
                executar_automacao_perfil,
                executar_verificacao_completo_datacrazy_pro_max,
                _gerar_variantes_telefone, gerar_numero_aleatorio, _cb,
                sms_provedor=sms_provedor)
            if ok_nova.get('sucesso'):
                _set('Concluído', '#00C74F', '✅ BM nova enviada p/ análise')
                _inc('novas_bm')
                try:
                    mod.adicionar_tags_perfil(profile_id, ["💙 BM EM ANALISE 💙", "♻️ REPROCESSADA"])
                except Exception:
                    pass
            else:
                _set('Erro', '#FF8800', f"⚠️ BM nova não concluída: {ok_nova.get('mensagem','')[:45]}")
                _inc('erros')

        except _PerfilQueimadoReproc:
            # FIX (auditoria 2026-10-12): o checkpoint DEAD-END (captcha de imagem) sobe como
            # _PerfilQueimado (BaseException) — o `except Exception` não o pegava: o item
            # ficava preso em 'Processando' e a THREAD do worker morria (com 1 simultâneo,
            # o resto da fila do reprocesso era abandonado em silêncio).
            logger.warning('[Reproc] Perfil %s: checkpoint captcha (dead-end) — descartado.', profile_id)
            _set('Erro', '#FF4444', '🧩 Checkpoint (captcha de imagem) — perfil descartado'); _inc('erros')
            try:
                mod.adicionar_tags_perfil(profile_id, ["🧩 CHECKPOINT CAPTCHA 🧩"])
            except Exception:
                pass
            _painel_desfecho(business_id, 'checkpoint', 'Checkpoint captcha de imagem (reprocesso)')
        except Exception as e:
            logger.error("[Reproc] Erro no perfil %s: %s", profile_id, e, exc_info=True)
            _set('Erro', '#FF4444', f'❌ {str(e)[:50]}'); _inc('erros')
        finally:
            if drv:
                try:
                    drv.quit()
                except Exception:
                    pass
            if navegador_aberto:
                try:
                    mod.fechar_navegador(profile_id)
                except Exception:
                    pass
                time.sleep(2)

    # ── Pool de N workers: cada thread puxa o próximo índice e processa ──
    _next = [0]

    def _worker():
        while True:
            if _estado_reprocesso['cancelar']:
                return
            with _clock:
                i = _next[0]
                if i >= len(perfis):
                    return
                _next[0] += 1
            try:
                _proc_um(i, perfis[i])
            except Exception as e:
                logger.error("[Reproc] worker idx %s falhou: %s", i, e, exc_info=True)
            # respiro entre perfis do MESMO worker (escalona as aberturas)
            if not _estado_reprocesso['cancelar']:
                time.sleep(2)

    try:
        threads = [threading.Thread(target=_worker, daemon=True) for _ in range(simultaneos)]
        for t in threads:
            t.start()
            time.sleep(1.0)  # escalona o arranque dos workers (evita rajada de aberturas)
        for t in threads:
            t.join()
    except Exception as e:
        logger.error("[Reproc] Erro fatal no pool: %s", e, exc_info=True)
    finally:
        _estado_reprocesso['processando'] = False
        if forcar_nova_bm:
            _estado['processando'] = False   # libera a interface principal
        _estado_reprocesso['mensagem'] = (
            f"Concluído: {_estado_reprocesso['novas_bm']} BM(s) nova(s), "
            f"{_estado_reprocesso['ignoradas']} ignoradas, "
            f"{_estado_reprocesso.get('excluidos', 0)} excluídos, "
            f"{_estado_reprocesso['erros']} erros")
        logger.info("[Reproc] %s", _estado_reprocesso['mensagem'])


def _reproc_criar_nova_bm(mod, profile_id, perfil_data, tipo_empresa,
                          captcha_token, sms24h_token, datacrazy_email, datacrazy_senha,
                          executar_automacao_perfil,
                          executar_verificacao_completo_datacrazy_pro_max,
                          _gerar_variantes_telefone, gerar_numero_aleatorio, cb,
                          sms_provedor='sms24h'):
    """Cria uma NOVA BM no perfil + puxa nova empresa/site e envia p/ análise.
    Usado quando a BM antiga está 'Em análise' há >= limiar (travada)."""
    drv2 = None
    try:
        # 1) empresa + site novos (1 token debitado server-side)
        empresa_dados, site_cache = _reproc_preparar_empresa_site(tipo_empresa, cb)
        # E-mail da 2ª BM (novo): o do site; depois é sobrescrito pelo e-mail real da BM.
        _novo_email = (site_cache or {}).get('email', '') or ''

        # 2) cria a BM (executar_automacao_perfil reabre/reconecta o navegador)
        cb('🆕 Criando nova BM no perfil...')
        res_auto = executar_automacao_perfil(
            profile_id=profile_id, perfil_data=perfil_data,
            abrir_navegador_func=mod.abrir_navegador,
            fechar_navegador_func=mod.fechar_navegador,
            adicionar_tags_func=mod.adicionar_tags_perfil,
            anexar_notas_func=getattr(mod, 'anexar_notas_perfil', None),
            callback_status=cb, qtd_bm=1, captcha_api_key=captcha_token,
            skip_close=True, nome_bm_override=empresa_dados.get('razao_social', ''),
            parar_no_primeiro_sucesso=True, forcar_criar_bm=True,
            site_host=(site_cache or {}).get('url', ''),
            empresa_razao=empresa_dados.get('razao_social', ''),
            email_pre={'address': (site_cache or {}).get('email', ''),
                       'password': (site_cache or {}).get('email_senha', '')})

        if res_auto.get('navegador_fechado'):
            return {'sucesso': False, 'mensagem': 'Navegador fechado durante a criação'}
        if not res_auto.get('bm_criada'):
            return {'sucesso': False, 'mensagem': res_auto.get('mensagem', 'BM não criada')}
        if res_auto.get('bm_bloqueada'):
            return {'sucesso': False, 'bm_bloqueada': True, 'novo_email': _novo_email,
                    'mensagem': 'Nova BM nasceu bloqueada'}

        new_bid = res_auto.get('business_id', '') or ''
        drv2 = res_auto.get('driver')
        bm_email = res_auto.get('email_tmail', '')
        if bm_email:
            _novo_email = bm_email
        if not new_bid or not drv2:
            return {'sucesso': False, 'novo_email': _novo_email,
                    'mensagem': 'business_id/driver ausente após criar BM'}

        # 3) verificação Pro Max Turbo (envia p/ análise): a WABA nasce pelo OAuth da
        # Meta direto (link do app DataCrazy). NUNCA cair na criação NATIVA do Business
        # Suite ("Adicionar → Criar conta do WhatsApp"), que pede reCAPTCHA e o bot
        # não passa (fix 2026-09-10).
        numero_sms = f'+{gerar_numero_aleatorio()}'
        empresa_dados['telefone'] = numero_sms
        variantes = _gerar_variantes_telefone(numero_sms)
        func = executar_verificacao_completo_datacrazy_pro_max
        kwargs = dict(
            driver=drv2, business_id=new_bid, empresa_dados=empresa_dados,
            site_id=site_cache.get('site_id', ''), site_url=site_cache.get('url', ''),
            numero_telefone=numero_sms, salvar_meta_func=salvar_meta_tags_site,
            callback_status=cb, variantes_telefone=variantes,
            senha_fb=perfil_data.get('senha', ''), captcha_token=captcha_token,
            tipo_empresa=tipo_empresa, sms24h_token=sms24h_token,
            sms_provedor=(sms_provedor or 'sms24h'),
            fb_login=perfil_data.get('login', ''), fb_tfa=perfil_data.get('tfa', ''),
            bm_email=bm_email or '',
            datacrazy_email=datacrazy_email, datacrazy_senha=datacrazy_senha)
        res_v = func(**kwargs)

        if res_v.get('em_analise'):
            # registra a nova BM na fila/painel
            try:
                if _TEM_ACESSO:
                    registrar_bm_criada(
                        bm_name=res_auto.get('bm_name', ''), bm_email=bm_email,
                        fb_login=perfil_data.get('login', ''), business_id=new_bid,
                        profile_id=str(profile_id), compra_id=0)
            except Exception as _re:
                logger.warning('[Reproc] registrar_bm_criada: %s', _re)
            # Painel: registra o ENVIO p/ análise (site/empresa/perfil/engine) — igual ao
            # worker principal. Sem isto a BM nova do Reprocessar/Reutilizar nunca entrava
            # no Monitor nem na página Minhas BMs com o perfil vinculado.
            _painel_registrar_em_analise(new_bid, site_id=(site_cache or {}).get('site_id', ''),
                                         site_url=(site_cache or {}).get('url', ''),
                                         empresa_dados=empresa_dados, profile_id=profile_id,
                                         fb_login=perfil_data.get('login', ''))
            return {'sucesso': True, 'em_analise': True, 'business_id': new_bid,
                    'novo_email': _novo_email}
        return {'sucesso': False, 'bm_bloqueada': bool(res_v.get('bm_bloqueada')),
                'novo_email': _novo_email,
                'mensagem': res_v.get('mensagem', 'não enviada p/ análise')}
    except Exception as e:
        logger.error('[Reproc] nova BM falhou: %s', e, exc_info=True)
        return {'sucesso': False, 'mensagem': str(e)[:80]}
    finally:
        if drv2:
            try:
                drv2.quit()
            except Exception:
                pass


def _resumir_bm_existente(mod, profile_id, perfil, business_id, empresa_dados, site_cache,
                          metodo, captcha_token, tipo_empresa, sms24h_token,
                          datacrazy_email, datacrazy_senha, numero_sms, variantes_tel,
                          bm_email, drv_verif, cb, sms_provedor='sms24h',
                          metodo_verificacao='dominio', verificar_site=True):
    """RETOMA uma BM JÁ EXISTENTE pelo STATUS (sem esperar e-mail):
      - retomar_bm_para_analise: re-publica o site no template atual + verifica o
        DOMÍNIO → checa RESTRIÇÃO (Contas de anúncios) → se tem WABA vai direto p/ a
        Central, senão roda o Turbo (OAuth da Meta) → envia p/ ANÁLISE.
      - Se a BM estiver RESTRITA: cria UMA BM NOVA (mesmos dados) e retoma nela; se a
        NOVA também ficar restrita/bloqueada → fecha + EXCLUI o perfil e segue o próximo.
    Retorna {'sucesso','em_analise','bm_bloqueada','excluido','business_id','mensagem'}.
    """
    from server.verificacao_bm import retomar_bm_para_analise
    from server.automacao_facebook import executar_automacao_perfil

    def _retomar(bid, drv):
        # `site_cache`/`empresa_dados` podem chegar vazios quando a retomada acontece
        # sem o site ter sido preparado nesta run — sem a guarda, `.get()` num None
        # estourava e virava "Exceção na retomada" (perfil perdido por nada).
        _sc = site_cache or {}
        return retomar_bm_para_analise(
            driver=drv, business_id=bid, empresa_dados=empresa_dados or {},
            site_id=_sc.get('site_id', ''), site_url=_sc.get('url', ''),
            salvar_meta_func=salvar_meta_tags_site, metodo=metodo, callback_status=cb,
            captcha_token=captcha_token, tipo_empresa=tipo_empresa, sms24h_token=sms24h_token,
            sms_provedor=sms_provedor, metodo_verificacao=metodo_verificacao,
            verificar_site=verificar_site,
            datacrazy_email=datacrazy_email, datacrazy_senha=datacrazy_senha,
            senha_fb=perfil.get('senha', ''), fb_login=perfil.get('login', ''),
            fb_tfa=perfil.get('tfa', ''), bm_email=bm_email or '', numero_telefone=numero_sms)

    cb('♻️ BM já existente — retomando pelo status (sem esperar e-mail)...')
    try:
        r = _retomar(business_id, drv_verif)
    except Exception as e:
        logger.exception('[Retomar] BM existente %s falhou: %s', business_id, e)
        return {'sucesso': False, 'em_analise': False, 'bm_bloqueada': False,
                'excluido': False, 'business_id': business_id, 'mensagem': f'Exceção na retomada: {e}'}

    # NÃO restrita → é o resultado final (análise/bloqueio/domínio-não-verificado).
    if not r.get('bm_restrita'):
        return {'sucesso': bool(r.get('sucesso')), 'em_analise': bool(r.get('em_analise')),
                'bm_bloqueada': bool(r.get('bm_bloqueada')),
                'waba_desabilitada': bool(r.get('waba_desabilitada')),
                'descansar': bool(r.get('descansar')),
                'dominio_nao_verificado': bool(r.get('dominio_nao_verificado')),
                'excluido': False, 'business_id': business_id, 'mensagem': r.get('mensagem', '')}

    # RESTRITA em Contas de anúncios → cria UMA BM NOVA (mesmos dados) e retoma nela.
    cb('🚫 BM restrita (Contas de anúncios) — criando uma BM NOVA no mesmo perfil...')
    try:
        if drv_verif:
            drv_verif.quit()
    except Exception:
        pass
    try:
        res_auto = executar_automacao_perfil(
            profile_id=profile_id, perfil_data=perfil,
            abrir_navegador_func=mod.abrir_navegador, fechar_navegador_func=mod.fechar_navegador,
            adicionar_tags_func=mod.adicionar_tags_perfil,
            anexar_notas_func=getattr(mod, 'anexar_notas_perfil', None),
            callback_status=cb, qtd_bm=1, captcha_api_key=captcha_token, skip_close=True,
            nome_bm_override=empresa_dados.get('razao_social', ''),
            parar_no_primeiro_sucesso=True, forcar_criar_bm=True,
            site_host=(site_cache or {}).get('url', ''),
            empresa_razao=empresa_dados.get('razao_social', ''),
            email_pre={'address': (site_cache or {}).get('email', ''),
                       'password': (site_cache or {}).get('email_senha', '')})
    except Exception as e:
        logger.exception('[Retomar] criar BM nova falhou: %s', e)
        return {'sucesso': False, 'bm_bloqueada': False, 'excluido': False,
                'business_id': business_id, 'mensagem': f'Falha ao criar BM nova: {e}'}

    if res_auto.get('navegador_fechado'):
        return {'sucesso': False, 'bm_bloqueada': False, 'excluido': False,
                'business_id': business_id, 'mensagem': 'Navegador fechado ao criar BM nova'}
    new_bid = res_auto.get('business_id', '') or ''
    drv2 = res_auto.get('driver')
    if not res_auto.get('bm_criada') or not new_bid or not drv2:
        return {'sucesso': False, 'bm_bloqueada': False, 'excluido': False,
                'business_id': business_id, 'mensagem': res_auto.get('mensagem', 'BM nova não criada')}
    new_email = res_auto.get('email_tmail', '') or bm_email

    # A BM nova nasceu bloqueada? = também restrita → exclui o perfil, segue.
    _nova_bloqueada = bool(res_auto.get('bm_bloqueada'))
    if not _nova_bloqueada:
        try:
            r2 = _retomar(new_bid, drv2)
        except Exception as e:
            logger.exception('[Retomar] retomar BM nova falhou: %s', e)
            r2 = {'bm_bloqueada': True, 'mensagem': f'Exceção na retomada da BM nova: {e}'}
        _nova_bloqueada = bool(r2.get('bm_restrita') or r2.get('bm_bloqueada'))
    else:
        r2 = {'bm_bloqueada': True, 'mensagem': 'BM nova nasceu bloqueada'}

    try:
        if drv2:
            drv2.quit()
    except Exception:
        pass

    if _nova_bloqueada:
        # 2ª BM TAMBÉM restrita/bloqueada. Pedido do usuário (2026-07-13): NÃO EXCLUIR o
        # perfil — MARCAR "💔 BM BLOQUEADA 💔" na Observação (AdsPower espelha no remark;
        # ixBrowser marca a tag) e fechar o navegador, MANTENDO o perfil. Assim o filtro
        # de "reaproveitar não concluídos" pula esse perfil nas próximas rodadas.
        cb('🔴 2ª BM também restrita — marcando "BM BLOQUEADA" e MANTENDO o perfil...')
        try:
            mod.adicionar_tags_perfil(profile_id, ["💔 BM BLOQUEADA 💔"])
        except Exception:
            pass
        try:
            mod.fechar_navegador(profile_id)
        except Exception:
            pass
        return {'sucesso': False, 'em_analise': False, 'bm_bloqueada': True,
                'excluido': False, 'business_id': new_bid,
                'mensagem': '2ª BM também restrita — marcado "BM BLOQUEADA" (perfil mantido).'}

    return {'sucesso': bool(r2.get('sucesso')), 'em_analise': bool(r2.get('em_analise')),
            'bm_bloqueada': bool(r2.get('bm_bloqueada')),
            'waba_desabilitada': bool(r2.get('waba_desabilitada')),
            'descansar': bool(r2.get('descansar')),
            'dominio_nao_verificado': bool(r2.get('dominio_nao_verificado')),
            'excluido': False, 'business_id': new_bid, 'mensagem': r2.get('mensagem', '')}




def _sanear_kwargs_verif(func_verif, kwargs, callback_status=None):
    """Remove de `kwargs` o que `func_verif` não aceita, avisando no log.

    Por que existe: o backend monta um dicionário único de kwargs para SETE funções
    de verificação diferentes. Quando uma delas ganha um parâmetro novo e as irmãs
    não, todo perfil que cai na irmã morre com `TypeError: ... got an unexpected
    keyword argument`. Foi assim que o `sms_provedor` zerou uma run inteira
    (0 sucesso / 100% erro) em 2026-08-02. Perder um parâmetro opcional é infinitamente
    melhor do que perder a run — e o aviso deixa o descompasso visível para corrigir.
    """
    import inspect
    try:
        params = inspect.signature(func_verif).parameters
    except (TypeError, ValueError):
        return kwargs
    # se a função tem **kwargs, ela aceita qualquer coisa
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    sobrando = [k for k in kwargs if k not in params]
    if sobrando:
        nome = getattr(func_verif, '__name__', str(func_verif))
        aviso = (f"[compat] {nome} não aceita {', '.join(sorted(sobrando))} — "
                 f"parâmetro(s) ignorado(s) para não derrubar o perfil.")
        logger.warning(aviso)
        if callback_status:
            try:
                callback_status(f"⚠️ {aviso}")
            except Exception:
                pass
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    return kwargs


def _pro_max_com_retry(mod, profile_id, perfil, business_id, kwargs_verif,
                       drv_verif, bm_email, tipo_empresa, captcha_token, cb, func_verif):
    """PRO MAX Turbo com RETRY de 2ª BM (pedido do usuário 2026-07-25).

    Roda a verificação Pro Max na BM atual (func_verif = executar_verificacao_completo_
    datacrazy_pro_max). Se a BM BLOQUEAR — em especial quando a WABA nasce
    DESABILITADA (Central sem 'Iniciar verificação' → waba_desabilitada=True) ou a BM
    restringe na criação — gera OUTRA empresa/site (OUTRO domínio), cria a 2ª BM e
    REFAZ o fluxo. Cada perfil tem no MÁXIMO 2 BMs: se a 2ª também bloquear, retorna
    bm_bloqueada=True (o chamador marca erro, fecha o navegador e segue o próximo da
    fila). Bloqueio de CONTA (checkpoint/hack) NÃO é retentado — a 2ª BM não resolve.

    Retorna res_verif com business_id/bm_email/driver/empresa_dados/site_cache FINAIS.
    Espelha _gs_prime_plus_com_retry (mesma mecânica, keyed em bm_bloqueada)."""
    from server.automacao_facebook import executar_automacao_perfil

    def _marca_final(res, bid, email, drv, emp=None, site=None):
        res['business_id'] = bid
        res['bm_email'] = email
        res['driver'] = drv
        if emp is not None:
            res['empresa_dados'] = emp
        if site is not None:
            res['site_cache'] = site
        return res

    # RECURSO (Pedir análise) de WABA DESABILITADA + contagem de BMs recorridas
    # (pedido do usuário 2026-07-25). A WABA nova cai por engano (conta nunca usada);
    # antes de desistir, RECORREMOS na página de suporte da Meta.
    from server.etapa_verificacao_negocio import recorrer_waba_desabilitada as _recorrer_waba
    recorridas = 0
    # Escolha do dono (GUI): recurso COM texto de contestação (padrão) ou EM BRANCO.
    try:
        _user_rc = _estado.get('usuario_logado') or _ler_config('ultimo_usuario_software', '')
        _com_texto = _ler_config('recurso_com_texto', 'sim', _user_rc).strip().lower() in ('sim', 'true', '1')
    except Exception:
        _com_texto = bool(_estado.get('recurso_com_texto', True))
    cb('📝 Recurso: enviando COM texto de contestação.' if _com_texto
       else '📄 Recurso: enviando o formulário EM BRANCO (sem texto).')

    def _recorrer_bm(drv, biz, rz):
        nonlocal recorridas
        try:
            if _recorrer_waba(drv, biz, cb, razao=(rz or ''), enviar_texto=_com_texto):
                recorridas += 1
                cb(f'♻️ Recurso enviado (BM {biz}) — total de BMs recorridas: {recorridas}.')
        except Exception as _er:
            logger.warning('[Pro Max retry] recurso (recorrer WABA) falhou: %s', _er)

    def _nota_recorridas():
        # Tag de DESFECHO na convenção do usuário (coração colorido em volta do nome,
        # igual "💚 Waba Ativa 💚" / "💙 BM EM ANALISE 💙" / "💔 BM BLOQUEADA 💔"):
        # a tag da recorrida é "💛 BM Recorrida 💛" (amarelo). Antes o código aplicava
        # "♻️ BM RECORRIDA", que criava uma tag DUPLICADA fora do padrão (2026-09-26).
        if recorridas <= 0:
            return
        _tag = '💛 2 BM Recorridas 💛' if recorridas >= 2 else '💛 BM Recorrida 💛'
        _fn = getattr(mod, 'anexar_notas_perfil', None)
        if _fn:
            try:
                _fn(profile_id, [_tag])
            except Exception:
                pass
        try:
            mod.adicionar_tags_perfil(profile_id, [_tag])
        except Exception:
            pass

    # 1ª tentativa — BM atual.
    res_verif = _marca_final(func_verif(**kwargs_verif), business_id, bm_email, drv_verif)
    # Só tenta a 2ª BM em BLOQUEIO recuperável (WABA desabilitada / restrição da BM).
    # Bloqueio de CONTA (checkpoint/hack) não se resolve com 2ª BM → não retenta.
    if not res_verif.get('bm_bloqueada') or res_verif.get('conta_bloqueada'):
        return res_verif

    cb('🔴 1ª BM bloqueada (WABA desabilitada/restrição).')
    # RECORRE a WABA desabilitada ANTES de criar a 2ª BM — reaproveita o navegador
    # JÁ ABERTO/logado (Pedir análise na página de suporte da Meta). Só quando foi a
    # WABA que desabilitou; restrição de CRIAÇÃO não tem WABA p/ recorrer.
    if res_verif.get('waba_desabilitada'):
        # RECORRE (loop 30s/5min p/ o botão 'Solicitar análise') e PARA aqui — NÃO cria
        # 2ª WABA no mesmo perfil (nasceria e cairia igual; pedido do dono 2026-09-26).
        # O status DEFINITIVO (restaurada/permanece desabilitada) chega depois pelo
        # e-mail da Meta no GSMAILS → painelbr (conector automático).
        _recorrer_bm(drv_verif, business_id,
                     (kwargs_verif.get('empresa_dados') or {}).get('razao_social', ''))
        _nota_recorridas()
        _metp = 'datacrazy_turbo'
        try:
            from server.painel_integration import reportar_waba_status
            _edr = kwargs_verif.get('empresa_dados') or {}
            reportar_waba_status(business_id, metodo=_metp, waba_status='desabilitada',
                                 recorrida=bool(recorridas > 0), bm_email=bm_email,
                                 cnpj=_edr.get('cnpj', ''), razao_social=_edr.get('razao_social', ''),
                                 fb_login=(perfil or {}).get('login', ''), profile_id=str(profile_id or ''))
        except Exception as _pe:
            logger.warning('[Pro Max retry] reporte painel (recorrida) falhou: %s', _pe)
        res_verif['recorrida'] = bool(recorridas > 0)
        res_verif['sem_segunda_bm'] = True
        cb('♻️ WABA recorrida (recurso enviado) — sem criar 2ª BM. Status definitivo virá pelo e-mail da Meta (GSMAILS→painel).'
           if recorridas > 0 else
           '⚠️ Recurso NÃO enviado (Solicitar análise/Submit não completou) — sem 2ª BM; acompanhe pelo e-mail da Meta.')
        return res_verif

    # BLOQUEIO SEM WABA (restrição de criação, sem WABA p/ recorrer): mantém a 2ª BM.
    cb('🧩 Gerando OUTRO domínio e criando a 2ª BM...')
    try:
        if drv_verif:
            drv_verif.quit()
    except Exception:
        pass

    # 1) EMPRESA NOVA + SITE NOVO para a 2ª BM (2026-07-31). A 2ª BM é uma entidade
    #    completamente nova: razão social nova, domínio novo E E-MAIL NOVO — o e-mail
    #    nasce no domínio do site novo, então o site precisa existir ANTES de criar a
    #    BM (o e-mail é gerado dentro de executar_automacao_perfil).
    #    A cota X/30 da raiz só é consumida quando o domínio for validado na Meta
    #    (salvar_meta_tags no painel) — 2ª BM que bloquear na criação não gasta cota.
    site2 = None
    try:
        empresa2 = _reproc_preparar_empresa(tipo_empresa, cb)
    except Exception as e:
        logger.exception('[Pro Max retry] nova empresa falhou: %s', e)
        res_verif['mensagem'] = (res_verif.get('mensagem', '') + f' | Nova empresa falhou: {e}')
        res_verif['driver'] = None
        return res_verif
    try:
        site2 = _reproc_criar_site(empresa2, cb)
    except Exception as e:
        logger.exception('[Pro Max retry] site da 2ª BM falhou: %s', e)
        res_verif['mensagem'] = (res_verif.get('mensagem', '') + f' | Site da 2ª BM falhou: {e}')
        res_verif['driver'] = None
        return res_verif

    # 2) 2ª BM com a RAZÃO SOCIAL nova e E-MAIL no domínio do SITE NOVO.
    try:
        res_auto = executar_automacao_perfil(
            profile_id=profile_id, perfil_data=perfil,
            abrir_navegador_func=mod.abrir_navegador, fechar_navegador_func=mod.fechar_navegador,
            adicionar_tags_func=mod.adicionar_tags_perfil,
            anexar_notas_func=getattr(mod, 'anexar_notas_perfil', None),
            callback_status=cb, qtd_bm=1, captcha_api_key=captcha_token, skip_close=True,
            nome_bm_override=empresa2.get('razao_social', ''),
            parar_no_primeiro_sucesso=True, forcar_criar_bm=True,
            site_host=site2.get('url', ''),
            empresa_razao=empresa2.get('razao_social', ''),
            email_pre={'address': site2.get('email', ''),
                       'password': site2.get('email_senha', '')})
    except Exception as e:
        logger.exception('[Pro Max retry] criar 2ª BM falhou: %s', e)
        res_verif['mensagem'] = (res_verif.get('mensagem', '') + f' | Falha ao criar 2ª BM: {e}')
        res_verif['driver'] = None
        return res_verif

    if res_auto.get('navegador_fechado'):
        res_verif['navegador_fechado'] = True
        res_verif['driver'] = None
        res_verif['mensagem'] = 'Navegador fechado ao criar a 2ª BM (Pro Max).'
        return res_verif
    new_bid = res_auto.get('business_id', '') or ''
    drv2 = res_auto.get('driver')
    # ⛔ LIMITE DA META: o perfil JÁ tem 2 BMs (a Meta não deixa criar a 3ª) e nenhuma
    # verificou → não há o que tentar. FECHA, descarta e conta erro/bloqueio NA HORA,
    # em vez de seguir tentando (2026-08-17, pedido do usuário).
    if res_auto.get('limite_bm_atingido'):
        cb('🔴 O perfil já tem 2 BMs (limite da Meta) e nenhuma verificou — '
           'descartando como erro/bloqueio; próximo da fila.')
        try:
            if drv2:
                drv2.quit()
        except Exception:
            pass
        r = {'sucesso': False, 'em_analise': False, 'bm_bloqueada': True,
             'limite_bm_atingido': True,
             'waba_desabilitada': bool(res_verif.get('waba_desabilitada')),
             'mensagem': ('Perfil no limite de 2 BMs e nenhuma verificou — descartado '
                          '(erro/bloqueio).')}
        _nota_recorridas()
        return _marca_final(r, new_bid or business_id, bm_email, None)
    if not res_auto.get('bm_criada') or not new_bid or not drv2:
        res_verif['driver'] = drv2
        res_verif['mensagem'] = (res_verif.get('mensagem', '') + ' | 2ª BM não criada.')
        return res_verif
    new_email = res_auto.get('email_tmail', '') or bm_email

    # 2ª BM já NASCEU bloqueada (restrição na criação) → as 2 bloquearam.
    # LIMITE DA META (perfil já com 2 BMs): não há 3ª — descarta NA HORA como
    # erro/bloqueio e segue o próximo da fila (nada de ficar insistindo).
    if res_auto.get('bm_bloqueada') or res_auto.get('limite_bm_atingido'):
        if res_auto.get('limite_bm_atingido'):
            cb('🔴 O perfil já tem 2 BMs (limite da Meta) e nenhuma verificou — '
               'descartando como erro/bloqueio; próximo da fila.')
            _msg_fim = ('Perfil no limite de 2 BMs e nenhuma verificou — descartado '
                        '(erro/bloqueio).')
        else:
            cb('🔴 2ª BM também nasceu bloqueada — marcando bloqueio; próximo da fila.')
            _msg_fim = 'As 2 BMs do perfil bloquearam (2ª nasceu restrita).'
        try:
            if drv2:
                drv2.quit()
        except Exception:
            pass
        r = {'sucesso': False, 'em_analise': False, 'bm_bloqueada': True,
             'limite_bm_atingido': bool(res_auto.get('limite_bm_atingido')),
             'waba_desabilitada': bool(res_verif.get('waba_desabilitada')),
             'mensagem': _msg_fim}
        # BM#1 foi recorrida (se WABA desabilitou) → Observação "BM RECORRIDA".
        _nota_recorridas()
        return _marca_final(r, new_bid, new_email, None, empresa2, site2)

    # 3) refaz o fluxo Pro Max na 2ª BM com a empresa/site nova (site2 já criado
    #    no passo 1, antes da BM, para que o e-mail nascesse no domínio dele).
    kwargs2 = dict(kwargs_verif)
    kwargs2['driver'] = drv2
    kwargs2['business_id'] = new_bid
    kwargs2['bm_email'] = new_email
    kwargs2['empresa_dados'] = empresa2
    kwargs2['site_id'] = site2.get('site_id', '')
    kwargs2['site_url'] = site2.get('url', '')
    # 2ª BM: o site REAL (site2) JÁ foi criado no passo 1 (o e-mail nasceu no domínio
    # dele) → DESLIGA o modo WABA-antes-do-site, senão o pro_max ignoraria site2 e
    # criaria OUTRO site pelo callback da 1ª BM. A 2ª BM usa o fluxo normal.
    kwargs2['waba_antes_site'] = False
    kwargs2.pop('criar_site_func', None)
    res2 = _marca_final(func_verif(**kwargs2), new_bid, new_email, drv2, empresa2, site2)
    if res2.get('bm_bloqueada'):
        # 2ª BM também caiu. Se foi a WABA que desabilitou, RECORRE nela também
        # (reaproveita drv2 aberto) → total "2 BM RECORRIDAS".
        if res2.get('waba_desabilitada'):
            _rec_antes = recorridas
            _recorrer_bm(drv2, new_bid, empresa2.get('razao_social', ''))
            # FIX (auditoria 2026-10-12): recurso REAL enviado na 2ª BM → é RECORRIDA
            # (aguarda a Meta), igual à 1ª BM — antes caía no chamador como "💔 BLOQUEADA"
            # e o painel nunca recebia recorrida=1 desta BM.
            if recorridas > _rec_antes:
                res2['recorrida'] = True
                try:
                    from server.painel_integration import reportar_waba_status
                    reportar_waba_status(new_bid, metodo='datacrazy_turbo', waba_status='desabilitada',
                                         recorrida=True, bm_email=new_email,
                                         cnpj=empresa2.get('cnpj', ''),
                                         razao_social=empresa2.get('razao_social', ''),
                                         fb_login=(perfil or {}).get('login', ''),
                                         profile_id=str(profile_id or ''))
                except Exception as _pe:
                    logger.warning('[Pro Max retry] reporte painel (recorrida 2ª BM) falhou: %s', _pe)
        cb('🔴 2ª BM também bloqueada — as 2 bloquearam; próximo da fila.')
    # Observação final: "BM RECORRIDA" (só a 1ª) ou "2 BM RECORRIDAS".
    _nota_recorridas()
    return res2


# ============================================================================
# MONITOR DE ANÁLISE (2026-07-08) — substitui o Reprocessar. Lê do painel as BMs
# enviadas p/ análise há >= N horas (status='aguardando_verificacao'), reabre cada
# perfil do AdsPower e, pelo status de verificação AO VIVO:
#   Verificada     -> cria a WABA (Turbo, OAuth da Meta) + tag 💚 BM VERIFICADA 💚
#   Não verificada -> reenvia p/ análise (novo nº + cert + site + Central) + 💙💙
#   Em análise     -> ignora (re-checa na próxima rodada)
# Roda com N navegadores em PARALELO (igual ao Reprocessar).
# ============================================================================

_estado_monitor = {
    'processando': False, 'cancelar': False, 'total': 0,
    'verificadas': 0, 'waba_ok': 0, 'waba_pendente': 0, 'reenviadas': 0,
    'em_analise': 0, 'erros': 0, 'mensagem': '', 'progresso_itens': [],
}


def obter_monitor_status():
    """Estado do Monitor de Análise para a UI."""
    return {
        'processando': _estado_monitor['processando'],
        'mensagem': _estado_monitor.get('mensagem', ''),
        'progresso': _estado_monitor.get('progresso_itens', []),
        'verificadas': _estado_monitor.get('verificadas', 0),
        'waba_ok': _estado_monitor.get('waba_ok', 0),
        'waba_pendente': _estado_monitor.get('waba_pendente', 0),
        'reenviadas': _estado_monitor.get('reenviadas', 0),
        'em_analise': _estado_monitor.get('em_analise', 0),
        'erros': _estado_monitor.get('erros', 0),
        'total': _estado_monitor.get('total', 0),
    }


def cancelar_monitor_analise():
    """Cancela o Monitor em andamento."""
    _estado_monitor['cancelar'] = True
    return True


def contar_bms_monitoraveis(horas=3.0):
    """Total elegível (>= `horas` em análise) — p/ o card da GUI."""
    try:
        from server.painel_integration import contar_bms_para_monitorar
        user = _estado.get('usuario_logado', '')
        return int(contar_bms_para_monitorar(username=user, horas=horas))
    except Exception as e:
        logger.warning('[Monitor] contar elegíveis falhou: %s', e)
        return 0


def _mon_razao_da_pagina(raw):
    """Fallback p/ BMs antigas sem razão social no painel: extrai a razão social do
    texto da página 'Informações da empresa'."""
    try:
        import re as _re
        m = _re.search(r'raz[ãa]o social da empresa\s*[\r\n]+\s*(.+)', raw or '', _re.IGNORECASE)
        if m:
            return m.group(1).strip()[:120]
    except Exception:
        pass
    return ''


def _ler_status_waba(drv, business_id):
    """Lê o 'Status da conta' da WABA em Contas do WhatsApp:
    'aprovada' | 'desabilitada' | 'pendente' | '' (não encontrado)."""
    try:
        drv.goto(f"https://business.facebook.com/latest/settings/whatsapp_account/?business_id={business_id}")
        try:
            from server.page_state_manager import PageStateManager
            PageStateManager.wait_until_stable(drv, timeout=30, settle_time=1.2,
                                               f5_after=20, callback_status=None)
        except Exception:
            time.sleep(4)
        try:
            from server.waba import dispensar_popup_atualizacao_whatsapp
            dispensar_popup_atualizacao_whatsapp(drv)
        except Exception:
            pass
        t = (drv.evaluate_page("() => (document.body && document.body.innerText) || ''") or '').lower()
        if 'desabilitada' in t or 'desativada' in t or 'disabled' in t or 'flagged' in t:
            return 'desabilitada'
        if 'aprovada' in t or 'approved' in t or 'conectada' in t or 'connected' in t:
            return 'aprovada'
        if 'pendente' in t or 'em análise' in t or 'em analise' in t or 'pending' in t or 'in review' in t:
            return 'pendente'
        return ''
    except Exception:
        return ''


def iniciar_monitor_analise(grupo_id='', metodo_waba='datacrazy', horas_analise=3.0, simultaneos=1):
    """Inicia o Monitor: lê do painel as BMs enviadas p/ análise há >= `horas_analise`
    e, reabrindo cada perfil, cria a WABA (verificada) ou reenvia (não verificada).
    `metodo_waba` é ignorado (a WABA nasce sempre pelo Turbo — OAuth da Meta direto);
    fica na assinatura só pela compatibilidade da chamada da GUI. (`grupo_id`
    reservado p/ filtro futuro.)"""
    del grupo_id, metodo_waba
    if _estado_monitor['processando']:
        return {'sucesso': False, 'mensagem': 'Monitor já em andamento'}
    if (_estado['processando'] or _estado_verificacao['processando']
            or _estado_reprocesso['processando']):
        return {'sucesso': False, 'mensagem': 'Aguarde o processamento atual terminar'}

    engine = _estado.get('browser_engine', 'adspower')
    mod = adspower_api if engine == 'adspower' else ixbrowser_api
    try:
        conex = mod.verificar_conexao()
        if not conex.get('conectado'):
            return {'sucesso': False, 'mensagem': f'{engine} não conectado: {conex.get("mensagem","")}'}
    except Exception as e:
        return {'sucesso': False, 'mensagem': f'Erro ao checar {engine}: {e}'}

    try:
        _hrs = float(horas_analise or 3)
    except Exception:
        _hrs = 3.0
    try:
        from server.painel_integration import listar_bms_para_monitorar
        user = _estado.get('usuario_logado', '')
        elegiveis = listar_bms_para_monitorar(username=user, horas=_hrs, limite=2000)
    except Exception as e:
        return {'sucesso': False, 'mensagem': f'Erro ao ler a fila do painel: {e}'}
    # só as que têm profile_id vinculado (dá p/ reabrir no AdsPower)
    elegiveis = [e for e in (elegiveis or []) if str(e.get('profile_id') or '').strip()]
    if not elegiveis:
        return {'sucesso': False,
                'mensagem': f'Nenhuma BM elegível (enviada há >= {_hrs:.0f}h com perfil vinculado).'}
    try:
        _sim = max(1, min(10, int(simultaneos or 1)))
    except Exception:
        _sim = 1
    _mw = 'datacrazy'
    threading.Thread(target=_processar_monitor_analise,
                     args=(elegiveis, engine, _mw, _sim), daemon=True).start()
    return {'sucesso': True, 'total': len(elegiveis),
            'mensagem': f'{len(elegiveis)} BM(s) no Monitor (Turbo, {_sim} simultâneo(s))'}


def _processar_monitor_analise(elegiveis, engine='adspower', metodo_waba='datacrazy', simultaneos=1):
    """Thread do Monitor — reabre cada perfil (N em paralelo), lê o status ao vivo e
    age: verificada->WABA / não verificada->reenvia / em análise->ignora."""
    simultaneos = max(1, min(10, int(simultaneos or 1)))
    _estado_monitor.update(processando=True, cancelar=False, total=len(elegiveis),
                           verificadas=0, waba_ok=0, waba_pendente=0, reenviadas=0,
                           em_analise=0, erros=0, progresso_itens=[],
                           mensagem='Iniciando Monitor de Análise...')
    for e in elegiveis:
        _estado_monitor['progresso_itens'].append({
            'profile_id': e.get('profile_id', ''),
            'bm_name': e.get('razao_social') or e.get('business_id', ''),
            'status': 'Aguardando', 'mensagem': '', 'cor': '#3F3F46',
        })

    user = _estado.get('usuario_logado', '')
    captcha_token = _estado.get('captcha_token') or _ler_captcha_token(user)
    sms24h_token = _estado.get('sms24h_token') or _ler_config('sms24h_token', '', user)
    tipo_empresa = _estado.get('tipo_empresa') or _ler_config('tipo_empresa', 'mei', user) or 'mei'
    datacrazy_email = _estado.get('datacrazy_email') or _ler_config('datacrazy_email', '', user)
    datacrazy_senha = _estado.get('datacrazy_senha') or _ler_config('datacrazy_senha', '', user)
    # Provedor de SMS escolhido na GUI (mesmo fix do Reprocessar): sem isto o reenvio do
    # Monitor comprava SEMPRE no provedor padrão, ignorando o selecionado na tela.
    sms_provedor = (str(_estado.get('sms_provedor', '') or '').strip().lower()
                    or _ler_config('sms_provedor', 'sms24h', user) or 'sms24h')

    mod = adspower_api if engine == 'adspower' else ixbrowser_api
    from server.verificacao_bm import ler_status_verificacao_ao_vivo
    from server.automacao_facebook import conectar_selenium
    from server.etapa_verificacao_negocio import executar_etapa_verificacao_negocio
    from server.painel_integration import atualizar_status_analise
    # Checkpoint DEAD-END sobe como BaseException (ver except no _mon_um).
    try:
        from server.etapa_verificacao_negocio import _PerfilQueimado as _PerfilQueimadoMon
    except Exception:
        class _PerfilQueimadoMon(BaseException):
            pass
    # Liga os DOIS mecanismos de modo paralelo (foco do FB + bring_to_front do
    # playwright) — em paralelo NENHUMA ação de nível-SO roda (senão N navegadores
    # disputariam a janela e congelariam o Windows).
    _ativar_modo_paralelo(simultaneos > 1)

    _clock = threading.Lock()

    def _inc(k):
        with _clock:
            _estado_monitor[k] = _estado_monitor.get(k, 0) + 1

    def _mon_um(idx, item):
        profile_id = str(item.get('profile_id') or '')
        business_id = str(item.get('business_id') or '')
        site_id = str(item.get('site_id') or '')
        site_url = str(item.get('site_url') or '')
        empresa = {'razao_social': item.get('razao_social') or '', 'cnpj': item.get('cnpj') or ''}
        bm_email = item.get('bm_email') or ''

        def _set(stt, cor, msg, _i=idx):
            it = _estado_monitor['progresso_itens'][_i]
            it['status'] = stt; it['cor'] = cor; it['mensagem'] = msg
            _estado_monitor['mensagem'] = f"[{_i+1}/{len(elegiveis)}] {msg[:60]}"

        def _cb(msg, _i=idx):
            _estado_monitor['progresso_itens'][_i]['mensagem'] = str(msg)
            _estado_monitor['mensagem'] = f"[{_i+1}/{len(elegiveis)}] {str(msg)[:60]}"

        if not profile_id or not business_id:
            _set('Erro', '#FF4444', '❌ Sem profile/business_id'); _inc('erros'); return

        drv = None
        aberto = False
        try:
            _set('Processando', '#F2C94C', 'Abrindo navegador...')
            res_abrir = mod.abrir_navegador(profile_id)
            if not res_abrir.get('sucesso'):
                raise RuntimeError(res_abrir.get('mensagem', 'falha ao abrir perfil'))
            aberto = True
            dbg, wpath = _reproc_extrair_debug(res_abrir)
            if not dbg:
                raise RuntimeError('endereço de debug ausente')
            time.sleep(2)
            drv = conectar_selenium(dbg, wpath)
            if not drv:
                raise RuntimeError('falha ao conectar Playwright')
            try:
                drv._pm_status = _cb
            except Exception:
                pass
            try:
                from server import session_guard as _sg
                _sg.vincular_perfil(drv, profile_id, mod)
            except Exception:
                pass

            _set('Processando', '#F2C94C', '🔎 Lendo status de verificação...')
            info = ler_status_verificacao_ao_vivo(drv, business_id, _cb)
            st = info.get('status')

            # ── VERIFICADA → cria a WABA ──
            if st == 'verificada':
                _set('Processando', '#00C74F', '💚 Verificada — criando WABA (Turbo)...')
                if not empresa['razao_social']:
                    empresa['razao_social'] = _mon_razao_da_pagina(info.get('raw', ''))
                try:
                    from server.etapa_full_datacrazy import executar_etapa_full_datacrazy
                    rw = executar_etapa_full_datacrazy(
                        drv, empresa, senha_fb='', site_url=site_url, callback_status=_cb,
                        datacrazy_email=datacrazy_email, datacrazy_senha=datacrazy_senha,
                        business_id=business_id)
                except Exception as ex:
                    rw = {'sucesso': False, 'mensagem': str(ex)}
                waba = _ler_status_waba(drv, business_id) if rw.get('sucesso') else 'pendente'
                if not waba:
                    waba = 'aprovada' if rw.get('sucesso') else 'pendente'
                atualizar_status_analise(business_id, 'verificada', waba_status=waba)
                try:
                    # 2026-10-12: o MULTILOGIN leva SÓ o CICLO da BM (💚 VERIFICADA). O status
                    # da WABA (aprovada/desabilitada/pendente) NÃO vira tag do perfil — fica
                    # apenas no painel web (Minhas BMs), já reportado acima via
                    # atualizar_status_analise(..., waba_status=waba).
                    mod.adicionar_tags_perfil(profile_id, ["💚 BM VERIFICADA 💚"])
                except Exception:
                    pass
                if rw.get('sucesso') and waba != 'desabilitada':
                    _inc('waba_ok')
                else:
                    _inc('waba_pendente')
                _inc('verificadas')
                _set('Concluído', '#00C74F', f'💚 Verificada — WABA: {waba}')
                return

            # ── NÃO VERIFICADA / REJEITADA → reenvia p/ análise ──
            if st in ('nao_verificada', 'rejeitada'):
                if not site_id:
                    _set('Erro', '#FF8800',
                         '⚠️ Não verificada, mas SEM site_id (BM antiga) — não dá p/ reenviar')
                    _inc('erros'); return
                _set('Processando', '#F2C94C', '💙 Não verificada — reenviando p/ análise...')
                rvn = executar_etapa_verificacao_negocio(
                    driver=drv, empresa_dados=empresa, business_id=business_id, site_id=site_id,
                    callback_status=_cb, captcha_token=captcha_token, tipo_empresa=tipo_empresa,
                    sms24h_token=sms24h_token, bm_email=bm_email, sem_waba=True, ignorar_restricao=True,
                    sms_provedor=sms_provedor)
                if rvn.get('em_analise'):
                    atualizar_status_analise(business_id, 'em_analise')
                    try:
                        mod.adicionar_tags_perfil(profile_id, ["💙💙 BM EM ANALISE 💙💙"])
                    except Exception:
                        pass
                    _inc('reenviadas')
                    _set('Concluído', '#00C74F', '💙💙 Reenviada p/ análise')
                else:
                    _inc('erros')
                    _set('Erro', '#FF8800', f"⚠️ Reenvio não concluído: {rvn.get('mensagem','')[:40]}")
                return

            # ── EM ANÁLISE / desconhecido → ignora (re-checa depois) ──
            _inc('em_analise')
            _set('Concluído', '#6B7280', '⏳ Ainda em análise — re-checa depois')
        except _PerfilQueimadoMon:
            # FIX (auditoria 2026-10-12): checkpoint DEAD-END (BaseException) escapava do
            # `except Exception` → item preso em 'Processando' + thread do worker morta.
            logger.warning('[Monitor] perfil %s: checkpoint captcha (dead-end) — descartado.', profile_id)
            _inc('erros')
            _set('Erro', '#FF4444', '🧩 Checkpoint (captcha de imagem) — perfil descartado')
            try:
                mod.adicionar_tags_perfil(profile_id, ["🧩 CHECKPOINT CAPTCHA 🧩"])
            except Exception:
                pass
            _painel_desfecho(business_id, 'checkpoint', 'Checkpoint captcha de imagem (monitor)')
        except Exception as ex:
            logger.error('[Monitor] perfil %s: %s', profile_id, ex, exc_info=True)
            _inc('erros')
            _set('Erro', '#FF4444', f'❌ {str(ex)[:50]}')
        finally:
            try:
                if drv:
                    drv.quit()
            except Exception:
                pass
            try:
                if aberto:
                    mod.fechar_navegador(profile_id)
            except Exception:
                pass

    # Pool paralelo (idêntico ao Reprocessar).
    _next = [0]
    _lk = threading.Lock()

    def _worker():
        while True:
            if _estado_monitor['cancelar']:
                return
            with _lk:
                i = _next[0]
                if i >= len(elegiveis):
                    return
                _next[0] += 1
            try:
                _mon_um(i, elegiveis[i])
            except Exception as ex:
                logger.error('[Monitor] worker idx %s: %s', i, ex, exc_info=True)
            if not _estado_monitor['cancelar']:
                time.sleep(2)

    try:
        threads = [threading.Thread(target=_worker, daemon=True) for _ in range(simultaneos)]
        for t in threads:
            t.start()
            time.sleep(1.0)
        for t in threads:
            t.join()
    except Exception as e:
        logger.error('[Monitor] Erro fatal no pool: %s', e, exc_info=True)
    finally:
        _estado_monitor['processando'] = False
        _estado_monitor['mensagem'] = (
            f"Concluído: {_estado_monitor['verificadas']} verificada(s) "
            f"(WABA ok {_estado_monitor['waba_ok']}/pend {_estado_monitor['waba_pendente']}), "
            f"{_estado_monitor['reenviadas']} reenviada(s), "
            f"{_estado_monitor['em_analise']} em análise, {_estado_monitor['erros']} erro(s)")
        logger.info('[Monitor] %s', _estado_monitor['mensagem'])


def _atualizar_progresso(indice, status, cor, mensagem):
    if 0 <= indice < len(_estado['progresso']):
        _estado['progresso'][indice]['status'] = status
        _estado['progresso'][indice]['cor'] = cor
        _estado['progresso'][indice]['mensagem'] = mensagem
        # HEARTBEAT (auditoria 24/7): marca o último AVANÇO deste worker. O watchdog usa
        # isto para detectar aba CONGELADA-mas-conectada (renderer travado) e matá-la,
        # liberando o slot. Cada status = um sinal de vida.
        _estado['progresso'][indice]['_hb'] = time.time()


def _atualizar_status_geral(mensagem):
    # NUNCA pode crashar: no app CONGELADO (PyInstaller/Windows) o sys.stdout costuma ser
    # cp1252 e print() de EMOJI (ex.: 🔄) levantava UnicodeEncodeError 'charmap', que
    # derrubava a thread INTEIRA do processamento (todos os perfis viravam "Erro fatal").
    try:
        print(f"[Sistema] {mensagem}")
    except Exception:
        try:
            print(("[Sistema] " + str(mensagem)).encode('ascii', 'replace').decode('ascii'))
        except Exception:
            pass

