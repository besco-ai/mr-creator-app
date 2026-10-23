#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ETAPA EXTRA (PRO MAX) — Verificação de NEGÓCIO da BM (envia para análise)
=========================================================================
Passo final EXCLUSIVO do Plano 6 (Completo / Pro Max). Roda DEPOIS que o fluxo
Full (Gupshup) finalizou a conexão do WhatsApp Business. A partir daqui faz a
"Verificação da empresa" na Central de Segurança do Facebook, de forma 100%
automática (CapSolver resolve o captcha + número virtual do sms24h — token do
próprio usuário — recebe o SMS), e envia a BM para análise.

Passo a passo (replicando exatamente o fluxo manual validado):
  0.  (informativo) abre "Contas do WhatsApp".
  1.  GATE: abre "Contas de anúncios". Se a BM estiver BLOQUEADA para anunciar
      ("Você não pode usar este portfólio empresarial para anunciar") → NÃO segue.
  2.  Compra um número virtual (sms24h, token do usuário) que receberá o SMS.
  3.  "Informações da empresa" → Detalhes da empresa → Editar (2º) → troca o
      "Telefone comercial" pelo número comprado (+55...) → Salvar.
  4.  Central de Segurança → "Iniciar verificação" → "Começar".
  5.  País (Brasil) → Avançar.
  6.  Tipo da empresa: MEI → "Empresa individual"; LTDA → "Empresa privada".
  7.  "Tem registro" → Avançar.
  8.  Dados da empresa: CNPJ → Avançar.
  9.  Endereço (já preenchido) → Avançar.  | Contato (telefone/site) → Avançar.
  10. CAPTCHA (reCAPTCHA Enterprise) → CapSolver resolve → Avançar.
  11. Carregar documentos → "CNPJ" → gera o certificado (API/Dompdf, com o número
      comprado) → envia o PDF → "Sim" (documento inclui telefone) → Avançar.
  12. "Verificação de domínio" → Avançar → "Domínio verificado" → Avançar.
  13. "Mensagem de texto (SMS)" → Avançar → "Enviar SMS".
  14. Lê o código no sms24h (até 90s/tentativa, "Reenviar código" até 3x). Se não
      chegar, compra NOVO número e repete o fluxo (até 3 tentativas).
  15. Insere o código → Avançar → "Concluir". Status: "Em análise". FIM.

Usa o MESMO navegador anti-detect (PlaywrightDriver) e reaproveita os helpers de
clique/preenchimento/espera do etapa_full_datacrazy.
"""

import os
import re
import time
import random
import logging
import threading

logger = logging.getLogger(__name__)

# ISOLAÇÃO EM PARALELO (10 janelas): a geração+gravação do certificado é
# SERIALIZADA por este lock — só UM worker gera o certificado por vez. Sem isso,
# em massa simultânea, 2+ workers gerando ao mesmo tempo podiam cruzar o arquivo
# (uma baixava/enviava o certificado da outra → "não detectamos a razão social X
# nos documentos"). Combinado com o NOME DE ARQUIVO ÚNICO por BM (cert_<biz>_<site>.pdf).
# _LOCK_CERTIFICADO removido para performance


def _nome_arquivo_cert(business_id, site_id):
    """Nome de arquivo de certificado ÚNICO por BM (evita um worker sobrescrever/
    enviar o certificado de outro no modo paralelo)."""
    bid = re.sub(r'[^A-Za-z0-9]+', '', str(business_id or ''))[:24] or 'bm'
    sid = re.sub(r'[^A-Za-z0-9]+', '', str(site_id or ''))[:24] or 's'
    return f'cert_{bid}_{sid}.pdf'

# Helpers de navegação/clique/preenchimento (reuso da etapa DataCrazy/Turbo —
# o módulo Gupshup foi removido em 2026-10-05 junto com os fluxos antigos).
from server.etapa_full_datacrazy import (
    _handles, _switch, _esperar_estatico, _esperar_url, _switch_para_url,
    _click_seletor, _click_texto, _preencher, _existe_texto,
    _preencher_campo_por_rotulo, _visivel, _url_atual,
    _delay, _delay_curto, _delay_medio,
)

# Certificado (Dompdf via painel). O SMS é COMPRADO DIRETO no sms24h com o
# TOKEN do próprio usuário (não usa mais a compra de número do painel).
try:
    from server.acesso import (gerar_certificado_cnpj_pdf, atualizar_contato_site,
                               obter_detalhes_site)
    _TEM_ACESSO = True
except Exception as _e:  # pragma: no cover
    logger.warning("[ProMax] acesso (certificado) indisponível: %s", _e)
    _TEM_ACESSO = False
    def atualizar_contato_site(site_id, telefone='', email='', senha_email='', email_servidor=''):
        return {'sucesso': False, 'mensagem': 'acesso indisponível'}
    def obter_detalhes_site(site_id):
        return {'sucesso': False}

try:
    from server.capsolver_client import resolver_recaptcha, SITEKEY_FACEBOOK_PADRAO
except Exception:  # pragma: no cover
    SITEKEY_FACEBOOK_PADRAO = '6LdktRgnAAAAAFQ6icovYI2-masYLFjEFyzQzpix'
    def resolver_recaptcha(*a, **k):
        return {'sucesso': False, 'token': '', 'mensagem': 'capsolver_client ausente'}

try:
    from server.sms24h_client import (
        SMS24HClient, formatar_e164, formatar_nacional,
        SERVICE_FACEBOOK, COUNTRY_BRASIL, SERVICE_QUALQUER,
        criar_cliente as criar_cliente_sms, nome_do_provedor, PROVEDOR_PADRAO,
        PROVEDORES, tokens_configurados, preco_max_configurado,
    )
    _TEM_SMS24H = True
except Exception as _e:  # pragma: no cover
    logger.warning("[ProMax] sms24h_client indisponível: %s", _e)
    _TEM_SMS24H = False
    SERVICE_FACEBOOK, COUNTRY_BRASIL, SERVICE_QUALQUER = 'fb', '73', 'ot'
    SMS24HClient = None
    PROVEDOR_PADRAO = 'sms24h'
    PROVEDORES = {'sms24h': {}}
    criar_cliente_sms = None
    def nome_do_provedor(p):
        return 'SMS24h'
    def tokens_configurados():
        return {}
    def formatar_e164(n):
        d = ''.join(c for c in str(n or '') if c.isdigit())
        if d and not d.startswith('55'):
            d = '55' + d
        return '+' + d if d else ''
    def formatar_nacional(n):
        return str(n or '')


BASE = 'https://business.facebook.com/latest/settings'
SMS_TIMEOUT = 90          # (legado) janela antiga de leitura do SMS
# ── Espera do SMS (regra do dono: 5 envios / 300s por número) ──────────────
#   t=0     clica "Receber código"     → 1º envio (natural)
#   t=60s   sem código                 → reenvio (2º envio)
#   t=120s  sem código                 → reenvio (3º)
#   t=180s  sem código                 → reenvio (4º)
#   t=240s  sem código                 → reenvio (5º e ÚLTIMO)  [total: 5 envios]
#   t=300s  ainda sem código           → cancela o número e TROCA (número/provedor)
#
# ⚠️ O "muitos códigos de verificação recentemente" NÃO vem daqui (reenvio): vem da
# RAJADA de várias abas no MESMO IP clicando "Enviar SMS" quase juntas. Isso é tratado
# pelo GATE de envio por IP (COORD.sms_send_slot) — ver `sms_enviar` abaixo. (2026-08-30)
#
# Repete até SMS_MAX_NUMEROS_MESMO_PROV números NO MESMO provedor; esgotado, vai
# para o PRÓXIMO provedor da fila (se houver secundário); se só houver 1 provedor,
# continua comprando número nele (não há para onde trocar).
SMS_POLL_INTERVALO = 5        # consulta a API SEM PARAR, a cada 5s
SMS_REENVIO_INTERVALO = 60    # sem código por 60s → pede reenvio
SMS_REENVIOS = 4              # 4 reenvios (envio natural + 4 = 5 envios por número)
SMS_ESPERA_MAX = 300          # 5 min por número → cancela e TROCA (número/provedor)

# TETO DURO acoplado ao Watchdog (backend._WD_INATIVIDADE = 600s). Nenhuma espera de
# SMS pode passar disto: se passar, o Watchdog mata o navegador ANTES de o laço chegar
# no seu próprio teto — e aí o caminho gracioso (cancelar o número + estornar + trocar
# de número) nunca roda. Foi exatamente o que travava a aba por 10 min: o painel manda
# `timeout_segundos` de 1200s (padrão) a 1500s (SMSBower) e isso sobrescrevia os 300s.
# A margem de 60s cobre o cancelamento e o log do desfecho.  (2026-09-07)
SMS_TETO_WATCHDOG = 540
SMS_HB_INTERVALO = 30         # sinal de vida na espera (alimenta o _hb do Watchdog)
# Quando o usuário tem UM só provedor com token, não há para onde trocar: aí sim
# compra outro número no MESMO provedor, até este total de números.
SMS_MAX_NUMEROS_MESMO_PROV = 3
MAX_TENTATIVAS = SMS_MAX_NUMEROS_MESMO_PROV   # piso; a fila de provedores pode aumentar
# Teto de tentativas que falham por motivo ≠ SMS (tela presa, captcha, upload, telefone
# comercial, certificado...) numa mesma BM — trocar de número não resolve. (2026-10-12)
_MAX_FALHAS_NAO_SMS = 3

# ── ESTRATÉGIA DE SERVIÇO NA VERIFICAÇÃO DE BM — POR PROVEDOR (2026-08-12) ─────
# O código da verificação de BM chega em número BR que recebe QUALQUER remetente.
# Cada provedor expõe isso por um serviço diferente:
#   • sms24h / smsbower → números BR REAIS: o próprio serviço 'fb' entrega a BM
#     (o smsbower 'fb' Gold custa ~US$0,04 — barato E entrega; o sms24h ~R$0,80).
#   • tiger / grizzly / vak → o 'fb' é FILTRADO por remetente (só entrega o SMS de
#     criação de conta); o código da BM só chega no 'ot' (mais caro: Tiger US$0,122).
# Este mapa faz cada provedor comprar no serviço que ENTREGA a BM pelo MENOR custo,
# em vez de um serviço global. Provedor fora do mapa cai em SMS_SERVICO_BM_PADRAO.
# MODO SMS CENTRAL (2026-08-30): o GS Creator compra o número pelo SERVIÇO CENTRAL do
# painel (cobrado do saldo REAL do usuário, provedores OCULTOS). True = liga o modo
# painel (PanelSmsClient); False = comportamento legado (tokens locais na GUI).
_SMS_CENTRAL = True

SMS_SERVICO_BM = {
    'smsbower': 'fb',
    'sms24h':   'fb',
    'tiger':    'ot',
    'grizzly':  'ot',
    'vak':      'ot',
    'painel':   'fb',   # serviço central: pede 'fb'; o painel aplica o fb_service_id do admin
}
SMS_SERVICO_BM_PADRAO = 'ot'   # provedor desconhecido: 'ot' (não filtra) é a aposta segura

def _servico_bm_do_provedor(prov):
    """Serviço de SMS que entrega o código da BM para este provedor, pelo menor custo."""
    return SMS_SERVICO_BM.get(str(prov or '').strip().lower(), SMS_SERVICO_BM_PADRAO)
# Sentinela: a página SAIU da tela de código durante a espera do SMS (a Central
# reverteu p/ 'Ações necessárias'/'Iniciar'/'Em análise'). O chamador deve PARAR de
# esperar o SMS e deixar o state machine RE-CONDUZIR (não ficar preso 'Aguardando SMS').
_TELA_SAIU_DO_CODIGO = '__TELA_SAIU_DO_CODIGO__'


# ---------------------------------------------------------------------- #
# Utilidades
# ---------------------------------------------------------------------- #
def _so_digitos(s):
    return ''.join(c for c in str(s or '') if c.isdigit())


def _norm_razao(s):
    """Normaliza razão social p/ comparação robusta: sem acentos, maiúsculas,
    espaços colapsados, sem pontuação. Usado no GUARD anti-troca de certificado
    (a razão social do site_id TEM que bater com a de empresa_dados — regra nº 1)."""
    import unicodedata
    t = unicodedata.normalize('NFKD', str(s or ''))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = t.upper()
    t = ''.join(c if (c.isalnum() or c == ' ') else ' ' for c in t)
    return ' '.join(t.split())


def _cnpj_formatado(cnpj):
    d = _so_digitos(cnpj)
    if len(d) != 14:
        return str(cnpj or '')
    return f'{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}'


def _campo_cnpj_preenchido(driver, cnpj_fmt):
    """True se ALGUM input visível da tela já contém os dígitos do CNPJ (compara só
    dígitos, ignora a máscara). Usado p/ CONFIRMAR que o Tax ID/CNPJ entrou de fato
    antes de Avançar — na tela nova 'Add business details' (migração de BM) o campo às
    vezes não recebe o valor na 1ª tentativa e o Next fica desabilitado."""
    alvo = _so_digitos(cnpj_fmt)
    if len(alvo) < 8:
        return True  # sem CNPJ válido p/ conferir → não bloqueia
    try:
        return bool(driver.evaluate_page("""(alvo) => {
            const inputs = [...document.querySelectorAll('input,textarea')];
            for (const el of inputs) {
                const d = (el.value || '').replace(/\\D/g, '');
                if (d && d.indexOf(alvo) !== -1) return true;
            }
            return false;
        }""", alvo))
    except Exception:
        return False


# ---------------------------------------------------------------------- #
# Tela do CNPJ ("Adicionar dados da empresa"/"Add business details") — ESTRUTURAL
# ---------------------------------------------------------------------- #
# Anatomia (igual em QUALQUER idioma, mapeada pelo print real):
#   diálogo com 2-3 inputs de TEXTO  [Tax ID/CNPJ, Nome da empresa (pré-preenchido
#   com a razão social), Nome alternativo (opcional)], SEM radio, SEM combobox, SEM
#   input de arquivo, e um botão PRIMÁRIO azul (Avançar/Next/...).
# A detecção por TEXTO falhava fora do pt-BR: em inglês a descrição da tela diz "you
# can upload documents to verify..." e casava 'carregar_doc' ANTES de 'cnpj'; em
# idioma não mapeado não casava nada. Aqui a decisão é pela ESTRUTURA + DADOS (razão
# social / dígitos do CNPJ nos campos), nunca pelo idioma. (2026-10-05)
_SUFIXOS_RAZAO = {'LTDA', 'ME', 'MEI', 'EIRELI', 'EPP', 'SA', 'S', 'A', 'CIA'}


def _razao_nucleo(s):
    """Razão social normalizada SEM sufixos societários (p/ comparar com o campo)."""
    return ' '.join(p for p in _norm_razao(s).split() if p not in _SUFIXOS_RAZAO)


def _estrutura_dialogo_form(driver):
    """Raio-X ESTRUTURAL do diálogo de FORMULÁRIO em primeiro plano (o mais ao topo
    que tem campo). Marca cada input de texto com `data-gscz="<idx>"` (ordem do DOM)
    e devolve {nText, tipos, vals, nRadio, nCombo, nFile, nCheck} — ou None se não há
    diálogo com formulário. Zero dependência de idioma."""
    try:
        est = driver.evaluate_page(r"""() => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
            const SEL = 'input,select,textarea,[role="radio"],[role="combobox"],[role="textbox"],[role="listbox"]';
            const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(d => {
                const r=d.getBoundingClientRect(); return r.width>120 && r.height>120 && vis(d); });
            let d = null;
            for (let i = dlgs.length - 1; i >= 0; i--) {
                if (dlgs[i].querySelector(SEL)) { d = dlgs[i]; break; }
            }
            document.querySelectorAll('[data-gscz]').forEach(e => e.removeAttribute('data-gscz'));
            if (!d) return null;
            const TXT = ['', 'text', 'tel', 'number', 'search', 'url', 'email'];
            const txt = [...d.querySelectorAll('input,textarea')].filter(e => {
                const t = ((e.getAttribute('type') || '') + '').toLowerCase();
                if (!TXT.includes(t)) return false;
                if (e.getAttribute('role') === 'combobox') return false;
                if (e.getAttribute('aria-haspopup') === 'listbox') return false;
                return vis(e) && !e.disabled && !e.readOnly;
            });
            txt.forEach((e, i) => e.setAttribute('data-gscz', String(i)));
            const conta = sel => [...d.querySelectorAll(sel)].filter(vis).length;
            return {
                nText: txt.length,
                tipos: txt.map(e => ((e.getAttribute('type') || 'text') + '').toLowerCase()),
                vals: txt.map(e => (e.value || '') + ''),
                nRadio: conta('[role="radio"],input[type="radio"]'),
                nCheck: conta('[role="checkbox"],input[type="checkbox"]'),
                nCombo: conta('[role="combobox"],[aria-haspopup="listbox"],select,[role="listbox"]'),
                nFile: d.querySelectorAll('input[type="file"]').length,
            };
        }""")
    except Exception:
        return None
    # Só aceita o formato esperado (o driver-stub dos testes devolve outro dict).
    if not isinstance(est, dict) or 'nText' not in est:
        return None
    return est


def _eh_tela_cnpj_estrutural(driver, est):
    """True quando o diálogo em primeiro plano É a tela do Tax ID/CNPJ, decidido pela
    ESTRUTURA (2-3 inputs de texto puros, sem radio/combobox/arquivo) + DADOS (algum
    campo traz a razão social da empresa ou os dígitos do CNPJ). Idioma-agnóstico."""
    if not est:
        return False
    try:
        n = int(est.get('nText') or 0)
        if not (2 <= n <= 3):
            return False
        if est.get('nRadio') or est.get('nCombo') or est.get('nFile') or est.get('nCheck'):
            return False
        if any(t in ('tel', 'email', 'url') for t in (est.get('tipos') or [])):
            return False
        vals = [str(v or '') for v in (est.get('vals') or [])]
        if any(('@' in v or '://' in v or 'www.' in v.lower()) for v in vals):
            return False       # tela de contato (site/e-mail), não a do CNPJ
        cnpj = _so_digitos(getattr(driver, '_pm_cnpj', ''))
        razao = _razao_nucleo(getattr(driver, '_pm_razao', ''))
        for v in vals:
            if len(cnpj) >= 8 and cnpj in _so_digitos(v):
                return True
            nv = _razao_nucleo(v)
            if razao and len(nv) >= 4 and (nv in razao or razao in nv):
                return True
    except Exception:
        return False
    return False


# valor INTEIRO é uma URL/domínio (sem espaços) — "ABC COM.IND LTDA" não casa.
_RE_DOMINIO = re.compile(r'^\s*(https?://)?[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(/\S*)?\s*$', re.I)


def _eh_tela_contato_estrutural(est):
    """True quando o diálogo é a tela de CONTATO (Telefone + Site): exatamente 2 inputs
    de texto, sem radio/arquivo/checkbox, e um dos valores é URL/domínio."""
    if not est:
        return False
    try:
        if int(est.get('nText') or 0) != 2:
            return False
        if est.get('nRadio') or est.get('nFile') or est.get('nCheck'):
            return False
        return any(_RE_DOMINIO.search(str(v or '')) for v in (est.get('vals') or []))
    except Exception:
        return False


def _valor_campo_gscz(driver, idx):
    try:
        return str(driver.evaluate_page(
            """(i) => { const e = document.querySelector('[data-gscz="' + i + '"]');
                        return e ? (e.value || '') : ''; }""", str(idx)) or '')
    except Exception:
        return ''


def _digitar_campo_gscz(driver, idx, valor):
    """Preenche o input marcado `data-gscz=idx`: fill nativo (eventos React) e, se o
    valor não 'pegar', clique REAL + Ctrl+A + digitação tecla a tecla."""
    sel = f'input[data-gscz="{idx}"], textarea[data-gscz="{idx}"]'
    alvo = _so_digitos(valor) or str(valor)
    def _ok():
        v = _valor_campo_gscz(driver, idx)
        return (alvo in _so_digitos(v)) if _so_digitos(valor) else (v.strip() == str(valor).strip())
    try:
        _preencher(driver, sel, valor, timeout=5)
    except Exception:
        pass
    if _ok():
        return True
    try:
        for el in driver.query_selector_all(sel):
            if not _visivel(el):
                continue
            el.click(timeout=4000)
            driver.keyboard.press('Control+a')
            driver.keyboard.press('Delete')
            driver.keyboard.type(str(valor), delay=random.randint(35, 80))
            break
    except Exception as e:
        logger.debug("[ProMax] digitação do campo gscz=%s falhou: %s", idx, e)
    time.sleep(0.3)
    return _ok()


def _preencher_cnpj_central(driver, cnpj_fmt, razao, rotulos, status=None):
    """Preenche o Tax ID/CNPJ na tela 'Adicionar dados da empresa' de forma
    ESTRUTURAL e VERIFICADA (sem depender do rótulo/idioma): o campo do CNPJ é o 1º
    input de texto do diálogo cujo valor NÃO tem letras (o do nome vem com a razão
    social). Garante também o Nome da empresa (obrigatório p/ o Avançar habilitar).
    Retorna True só quando os dígitos do CNPJ estão DE FATO no campo."""
    alvo = _so_digitos(cnpj_fmt)
    for tent in range(4):
        est = _estrutura_dialogo_form(driver)
        vals = [str(v or '') for v in ((est or {}).get('vals') or [])]
        idx_cnpj = None
        for i, v in enumerate(vals):
            if len(alvo) >= 8 and alvo in _so_digitos(v):
                idx_cnpj = i
                break
        # TRAVA: jamais digitar o CNPJ fora da tela dele — com radio/arquivo, com campo
        # de URL/e-mail (tela de CONTATO: o 1º campo é o TELEFONE) ou input type=tel.
        if est and (any(_RE_DOMINIO.search(v) or '@' in v for v in vals)
                    or any(t in ('tel', 'email', 'url') for t in (est.get('tipos') or []))):
            logger.warning("[ProMax] passo 'cnpj' numa tela com campo de site/telefone — "
                           "NÃO preencho (é a tela de contato).")
            return False
        _form_puro = bool(est) and not (est.get('nRadio') or est.get('nFile'))
        if idx_cnpj is None and vals and _form_puro:
            # 1º campo sem letras (vazio ou só máscara/dígitos de outro documento).
            cand = next((i for i, v in enumerate(vals) if not any(c.isalpha() for c in v)), None)
            if cand is not None:
                if _digitar_campo_gscz(driver, cand, cnpj_fmt) or \
                        _digitar_campo_gscz(driver, cand, alvo):
                    idx_cnpj = cand
        if idx_cnpj is None and not vals:
            # Diálogo ainda sem inputs (skeleton) ou layout inesperado → rótulo (legado).
            _preencher_campo_por_rotulo(driver, rotulos, cnpj_fmt, timeout=6)
            if _campo_cnpj_preenchido(driver, cnpj_fmt):
                return True
        if idx_cnpj is not None:
            # Nome da empresa: o campo logo após o do CNPJ. Se a Meta o trouxe VAZIO, o
            # Avançar fica desabilitado em qualquer idioma → preenche com a razão social.
            try:
                prox = idx_cnpj + 1
                if razao and prox < len(vals) and not vals[prox].strip() \
                        and not any(_razao_nucleo(v) for j, v in enumerate(vals) if j != idx_cnpj):
                    _digitar_campo_gscz(driver, prox, razao)
            except Exception:
                pass
            return True
        if status:
            status(f"↻ Tax ID/CNPJ ainda vazio (tentativa {tent + 1}/4) — "
                   f"reesperando o campo renderizar e repreenchendo...")
        _delay_medio()
    return _campo_cnpj_preenchido(driver, cnpj_fmt)


def _primario_dialogo(driver, clicar=False):
    """Localiza o botão PRIMÁRIO (azul) do diálogo de formulário em primeiro plano —
    o 'Avançar/Next/Weiter/…' em qualquer idioma — pela COR, não pelo texto.
    Retorna None (não achou), 'desabilitado' ou 'habilitado'. Com clicar=True e
    habilitado, clica (mouse REAL no centro; fallback dispatch JS) e devolve 'clicado'.
    Só olha diálogo COM formulário: nunca toca no 'Deseja sair? → Sim, sair'."""
    try:
        info = driver.evaluate_page(r"""() => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
            const SEL = 'input,select,textarea,[role="radio"],[role="combobox"],[role="textbox"],[role="listbox"]';
            const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(d => {
                const r=d.getBoundingClientRect(); return r.width>120 && r.height>120 && vis(d); });
            let d = null;
            for (let i = dlgs.length - 1; i >= 0; i--) {
                if (dlgs[i].querySelector(SEL)) { d = dlgs[i]; break; }
            }
            document.querySelectorAll('[data-gscz-prim]').forEach(e => e.removeAttribute('data-gscz-prim'));
            if (!d) return null;
            const azul = el => {
                const m = (getComputedStyle(el).backgroundColor || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/);
                if (!m) return false;
                const R=+m[1], G=+m[2], B=+m[3], A = m[4] === undefined ? 1 : +m[4];
                return A > 0.5 && B > 180 && B > R + 40 && G < 170 && R < 120;
            };
            let melhor = null, mr = null, temDesab = false;
            for (const b of d.querySelectorAll('[role="button"],button')) {
                if (!vis(b)) continue;
                const r = b.getBoundingClientRect();
                if (r.width < 40 || r.height < 20) continue;
                // primário DESABILITADO perde o azul forte (fica azul-claro/cinza):
                if (b.getAttribute('aria-disabled') === 'true' || b.disabled === true) temDesab = true;
                let ehAzul = azul(b);
                if (!ehAzul) {
                    let k = 0;
                    for (const f of b.querySelectorAll('div,span')) {
                        if (k++ > 6) break;
                        const fr = f.getBoundingClientRect();
                        if (fr.width >= r.width * 0.8 && fr.height >= r.height * 0.8 && azul(f)) { ehAzul = true; break; }
                    }
                }
                if (!ehAzul) continue;
                // o primário fica embaixo/à direita: vence o mais abaixo, depois mais à direita
                if (!melhor || r.top > mr.top + 4 || (Math.abs(r.top - mr.top) <= 4 && r.left > mr.left)) {
                    melhor = b; mr = r;
                }
            }
            if (!melhor) return temDesab ? {des: true} : null;
            const des = melhor.getAttribute('aria-disabled') === 'true' || melhor.disabled === true
                        || !!melhor.closest('[aria-disabled="true"]');
            melhor.setAttribute('data-gscz-prim', '1');
            try { melhor.scrollIntoView({block: 'center'}); } catch (e) {}
            const r = melhor.getBoundingClientRect();
            return {des: des, x: r.left + r.width / 2, y: r.top + r.height / 2};
        }""")
    except Exception:
        return None
    if not isinstance(info, dict) or 'des' not in info:
        return None
    if info.get('des'):
        return 'desabilitado'
    if not clicar:
        return 'habilitado'
    try:
        driver.mouse.click(float(info['x']), float(info['y']))
    except Exception:
        try:
            driver.evaluate_page(r"""() => {
                const b = document.querySelector('[data-gscz-prim="1"]');
                if (!b) return false;
                const r = b.getBoundingClientRect();
                const o = {bubbles:true, cancelable:true, view:window,
                           clientX:r.left + r.width/2, clientY:r.top + r.height/2};
                for (const t of ['mouseover','mousedown','mouseup','click']) {
                    try { b.dispatchEvent(new MouseEvent(t, o)); } catch (e) {}
                }
                return true;
            }""")
        except Exception:
            return 'habilitado'
    logger.info("[ProMax] Clique ESTRUTURAL no botão primário (azul) do diálogo.")
    return 'clicado'


def _marcar_primeiro_radio_dialogo(driver):
    """Fallback idioma-agnóstico p/ telas de escolha: se NENHUM radio do diálogo do
    formulário está marcado, marca o 1º. Retorna True se há um radio marcado ao final."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
            const marcado = r => r.getAttribute('aria-checked') === 'true' || r.checked === true;
            const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
            for (let i = dlgs.length - 1; i >= 0; i--) {
                const rs = [...dlgs[i].querySelectorAll('[role="radio"],input[type="radio"]')];
                if (!rs.length) continue;
                if (rs.some(marcado)) return true;
                const r = rs[0];
                try { r.scrollIntoView({block: 'center'}); } catch (e) {}
                try { r.click(); } catch (e) {}
                if (!marcado(r)) {
                    try { (r.closest('label,[role="button"]') || r.parentElement).click(); } catch (e) {}
                }
                return marcado(r);
            }
            return false;
        }"""))
    except Exception:
        return False


def _digitos_nacionais(numero):
    """Dígitos NACIONAIS do telefone (sem +55), como o campo Telefone do FB espera.

    Ex.: '5528926918605' / '+5528926918605' -> '28926918605'."""
    d = _so_digitos(numero)
    if d.startswith('55') and len(d) >= 12:
        d = d[2:]
    return d


def _pasta_certificado():
    try:
        from server.backend import RUNTIME_DIR
        base = RUNTIME_DIR
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pasta = os.path.join(base, 'certificado')
    try:
        os.makedirs(pasta, exist_ok=True)
    except Exception:
        pass
    return pasta


def _apagar_arquivo(caminho):
    try:
        if caminho and os.path.isfile(caminho):
            os.remove(caminho)
    except Exception:
        pass


class _PerfilQueimado(BaseException):
    """Sinaliza um checkpoint DEAD-END (captcha de imagem 'Confirme que você é uma
    pessoa'): a conta caiu no checkpoint e não há como avançar. Subclasse de
    BaseException DE PROPÓSITO — assim os inúmeros `except Exception` do fluxo de
    verificação NÃO a engolem; ela sobe até o backend, que descarta o perfil.
    (Confirmado: não há `except:` nu no caminho da verificação.)"""
    pass


def _captcha_imagem_dead_end(driver):
    """Detecta o checkpoint de CAPTCHA de imagem ('Confirme que você é uma pessoa /
    Digite o texto da imagem / Enter the text you see'). É um DEAD-END: não há como
    resolver de forma confiável — a conta caiu no checkpoint. NÃO insistir/clicar;
    o perfil deve ser DESCARTADO (queimado)."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            try {
                var t = (document.body && document.body.innerText || '').toLowerCase();
                function nrm(s){ try { var d=s.normalize('NFD'), o=''; for (var i=0;i<d.length;i++){ var c=d.charCodeAt(i); if (c<0x300||c>0x36f) o+=d[i]; } return o; } catch(e){ return s; } }
                var n = nrm(t);
                return n.indexOf('digite o texto da imagem') !== -1
                    || n.indexOf('confirme que voce e uma pessoa') !== -1
                    || n.indexOf('nao consegue ler esse texto') !== -1
                    || n.indexOf('ouca o codigo') !== -1
                    || n.indexOf('enter the text you see') !== -1
                    || n.indexOf('enter the characters you see') !== -1
                    || n.indexOf('enter the characters in the') !== -1
                    || n.indexOf('escribe el texto de la imagen') !== -1
                    || (n.indexOf('security check') !== -1 && n.indexOf('image') !== -1)
                    || (n.indexOf('confirm you') !== -1 && n.indexOf('human') !== -1)
                    || (n.indexOf('confirm that you') !== -1 && (n.indexOf('human') !== -1 || n.indexOf('person') !== -1 || n.indexOf('real') !== -1));
            } catch(e){ return false; }
        }"""))
    except Exception:
        return False


def _tratar_interrupcao_fb(driver, destino=None):
    """Trata interrupções do Facebook que surgem ao navegar no business.facebook.com
    durante a verificação Pro Max:
      1. Checkpoint 'Suspeitamos que o comportamento da sua conta seja automatizado'
         → clica 'Ignorar'/'Dismiss'.
      1b. Tela de login do BUSINESS (business/loginpage 'Continuar com o Facebook', SEM
         inputs) → delega ao session_guard.restaurar_sessao (volta ao `destino`).
      2. Popup 'Fazer login como ...' (login rápido por cookie) → clica 'Fazer login'.
      3. Sessão caiu para o FORMULÁRIO de login → refaz o login completo (com 2FA).
    Credenciais e callback ficam em atributos do driver (setados na entrada da etapa).
    Retorna True se tratou alguma interrupção."""
    status = getattr(driver, '_pm_status', None)
    def _s(m):
        logger.info("[ProMax] %s", m)
        if status:
            try:
                status(m)
            except Exception:
                pass
    tratou = False
    try:
        url = (_url_atual(driver) or '').lower()
    except Exception:
        url = ''
    caminho = url.split('?', 1)[0]

    # 0-) Aviso "Meta protegeu sua conta" (/hacked-protection) — inclusive o "Not Found"
    #     cru (sem botão): o session_guard PULA essa URL, então a verificação trata aqui
    #     com a MESMA rotina do login (X/Back to Facebook; Not Found → facebook.com →
    #     Dismiss) e volta ao destino. (2026-10-13)
    try:
        if 'hacked-protection' in url:
            _s("🛡️ Aviso 'Meta protegeu sua conta' — dispensando e voltando ao fluxo...")
            from server.automacao_facebook import fechar_aviso_conta_protegida
            fechar_aviso_conta_protegida(driver, callback_status=(lambda m, *a: _s(m)))
            tratou = True
            if destino and 'hacked-protection' not in (_url_atual(driver) or '').lower():
                try:
                    driver.get(destino)
                    _esperar_estatico(driver, timeout=10)
                except Exception:
                    pass
            url = (_url_atual(driver) or '').lower()
            caminho = url.split('?', 1)[0]
    except Exception as e:
        logger.debug("[ProMax] hacked-protection handler: %s", e)

    # 0) Consentimento de privacidade / assinatura sem anúncios (ad_free_subscription)
    #    — FB redireciona p/ /privacy/consent/ (sobretudo após re-login). Clica a
    #    opção GRÁTIS com anúncios + avança até sair do fluxo. Idioma-independente
    #    (cobre VI: 'Bắt đầu' / 'Dùng miễn phí kèm quảng cáo' / 'Tiếp tục').
    try:
        if ('privacy/consent' in url or 'ad_free_subscription' in url
                or 'lgpd' in url or 'gdpr' in url):
            _s("🧩 Consentimento de privacidade/anúncios — resolvendo (grátis com anúncios)...")
            from server.automacao_facebook import _tratar_consentimento_privacidade
            _tratar_consentimento_privacidade(driver, callback_status=(lambda m, *a: _s(m)))
            tratou = True
            try:
                _esperar_estatico(driver, timeout=8)
            except Exception:
                pass
            url = (_url_atual(driver) or '').lower()
            caminho = url.split('?', 1)[0]
    except Exception as e:
        logger.debug("[ProMax] consentimento handler: %s", e)

    # 0b) Diálogo de cookies do FB (pode surgir em qualquer navegação). Aceita
    #     todos os cookies (botão azul), evitando 'recusar/Từ chối'. Idioma-indep.
    try:
        tem_cookie = bool(driver.evaluate_page(r"""() => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
            if (vis(document.querySelector('[data-cookiebanner="accept_button"]'))) return true;
            if (vis(document.querySelector('[data-testid="cookie-policy-manage-dialog-accept-button"]'))) return true;
            const txt = (document.body && document.body.innerText || '').toLowerCase();
            return txt.includes('cho phép tất cả cookie') || txt.includes('allow all cookies')
                || txt.includes('permitir todos os cookies');
        }"""))
        if tem_cookie:
            _s("🍪 Diálogo de cookies — permitindo todos...")
            from server.automacao_facebook import _tratar_cookies_facebook
            if _tratar_cookies_facebook(driver, callback_status=(lambda m, *a: _s(m))):
                tratou = True
                try:
                    _esperar_estatico(driver, timeout=6)
                except Exception:
                    pass
                url = (_url_atual(driver) or '').lower()
                caminho = url.split('?', 1)[0]
    except Exception as e:
        logger.debug("[ProMax] cookies handler: %s", e)

    # 1) Checkpoint "comportamento automatizado" (botão Ignorar/Dismiss).
    try:
        if '/checkpoint' in caminho or _existe_texto(
                driver, ['comportamento da sua conta seja automatizado',
                         'comportamento automatizado', 'automated behavi',
                         'suspeitamos'], timeout=1):
            # DEAD-END: captcha de imagem ("Confirme que você é uma pessoa / Digite o
            # texto da imagem"). NÃO dá p/ resolver — NÃO insistir/clicar. Marca o
            # perfil como QUEIMADO e ABORTA a verificação (o backend descarta o perfil).
            if _captcha_imagem_dead_end(driver):
                _s("🧩 Captcha de imagem no checkpoint — perfil QUEIMADO; descartando (não insisto).")
                try:
                    driver._pm_perfil_queimado = 'checkpoint_captcha'
                except Exception:
                    pass
                raise _PerfilQueimado()
            _s("🛡️ Checkpoint 'comportamento automatizado' — clicando 'Ignorar'...")
            from server.automacao_facebook import _tratar_aviso_comportamento_automatizado
            if _tratar_aviso_comportamento_automatizado(driver, None):
                tratou = True
                try:
                    _esperar_estatico(driver, timeout=8)
                except Exception:
                    pass
    except _PerfilQueimado:
        raise
    except Exception as e:
        logger.debug("[ProMax] checkpoint handler: %s", e)

    # 1b) Tela de login do BUSINESS (business.facebook.com/business/loginpage — botão
    #     'Continuar com o Facebook', SEM #email/#pass): o detector do formulário (passo
    #     3) NÃO a vê e o fluxo ficava girando numa página deslogada. Detecção ESTRUTURAL
    #     (idioma-agnóstica) e restauração delegadas ao session_guard, que clica
    #     'Continuar com o Facebook' (c_user vivo) ou refaz o login completo e volta ao
    #     destino. Roda ANTES do passo 2 p/ não clicar o 'Log in' da loginpage às cegas.
    try:
        from server import session_guard as _sg
        if _sg.estado_sessao(driver) == 'login_business':
            _s("🔐 Business deslogou (tela 'Continuar com o Facebook') — restaurando a sessão...")
            if _sg.restaurar_sessao(driver, destino=destino, callback_status=status):
                tratou = True
                try:
                    _esperar_estatico(driver, timeout=10)
                except Exception:
                    pass
            else:
                _s("⚠️ Não consegui restaurar a sessão do Business automaticamente.")
    except Exception as e:
        logger.debug("[ProMax] login_business handler: %s", e)

    # 2) Popup "Fazer login como ..." (login rápido) → clica "Fazer login".
    try:
        clicou = driver.evaluate_page(r"""() => {
            const vis = e => { const r=e.getBoundingClientRect(); return r.width>0&&r.height>0; };
            for (const e of document.querySelectorAll('div[role="button"],button,span,a')){
                if(!vis(e)) continue;
                const t=(e.innerText||'').trim().toLowerCase();
                if (t==='fazer login' || t==='log in'){ try{ e.click(); return true; }catch(x){} }
            }
            return false;
        }""")
        if clicou:
            _s("🔑 Popup 'Fazer login como' — clicando 'Fazer login'...")
            tratou = True
            try:
                _esperar_estatico(driver, timeout=10)
            except Exception:
                pass
    except Exception:
        pass

    # 3) Caiu no FORMULÁRIO de login (email+senha) → re-login completo (com 2FA).
    try:
        tem_form = bool(driver.evaluate_page(r"""() => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
            return vis(document.querySelector('#email, input[name="email"]')) &&
                   vis(document.querySelector('#pass, input[name="pass"]'));
        }"""))
    except Exception:
        tem_form = False
    if tem_form:
        fb_login = getattr(driver, '_pm_fb_login', '')
        fb_senha = getattr(driver, '_pm_fb_senha', '')
        fb_tfa = getattr(driver, '_pm_fb_tfa', '')
        fb_email = getattr(driver, '_pm_fb_email', '')
        fb_email_senha = getattr(driver, '_pm_fb_email_senha', '')
        if fb_login and fb_senha:
            _s("🔐 Sessão caiu — refazendo login no Facebook (com 2FA se houver)...")
            try:
                from server.automacao_facebook import fazer_login_facebook
                fazer_login_facebook(driver, fb_login, fb_senha, fb_tfa or None,
                                     callback_status=(lambda m, *a: _s(m)),
                                     email=fb_email, senha_email=fb_email_senha)
                tratou = True
                try:
                    _esperar_estatico(driver, timeout=10)
                except Exception:
                    pass
            except Exception as e:
                logger.warning("[ProMax] re-login falhou: %s", e)
        else:
            _s("⚠️ Sessão caiu, mas sem credenciais para re-login automático.")
    return tratou


def _ir_para(driver, url, esperar=None, timeout=40):
    """Navega e aguarda estabilizar; opcionalmente espera um fragmento na URL.
    Após estabilizar, trata interrupções do FB (checkpoint/re-login) e, se tratou
    algo, RE-NAVEGA para a URL alvo para retomar de onde estava."""
    try:
        driver.get(url)
    except Exception as e:
        logger.warning("[ProMax] goto falhou (%s): %s", url, e)
    if esperar:
        _esperar_url(driver, esperar, timeout=min(timeout, 25))
    _esperar_estatico(driver, timeout=timeout)
    # Trata checkpoint / queda de sessão que possam ter aparecido ao navegar.
    try:
        if _tratar_interrupcao_fb(driver, destino=url):
            # Re-navega para a URL alvo (o login/checkpoint redireciona p/ outro lugar).
            try:
                driver.get(url)
            except Exception:
                pass
            if esperar:
                _esperar_url(driver, esperar, timeout=min(timeout, 25))
            _esperar_estatico(driver, timeout=timeout)
    except Exception:
        pass


def _avancar(driver, timeout=15):
    """Clica em Avançar/Continuar/Next/Concluir (o que estiver visível).

    Usa clique ROBUSTO: tenta o `_click_texto` normal e, se falhar por causa do
    OVERLAY do React (data-visualcompletion="ignore", inset:0 → 'Texto não
    clicável'/'element intercepts pointer events'), cai para o JS-dispatch que
    dispara o evento direto no botão, ignorando o hit-test do overlay. Era a
    causa do fluxo da Central ficar BOUNCING entre passos (país → cnpj → país →
    ...) e VOLTAR ao início — o clique falhava e o passo não avançava limpo."""
    _txt = ['Avançar', 'Continuar', 'Next', 'Continue', 'Salvar', 'Siguiente']
    # Espera o pop-up ASSENTAR (campos carregados/estáveis) e clica com mouse REAL,
    # conferindo que o botão está habilitado e sem nada por cima. (2026-10-05)
    try:
        _aguardar_dialogo_pronto(driver, timeout=4)
        if _clicar_avancar_real(driver, _txt, esperar_habilitar=3):
            return True
    except Exception:
        pass
    # 🛡️ POP-UP DO FLUXO ABERTO + Avançar DESABILITADO = a tela ainda não está pronta
    # (opção não marcada / campo inválido). NÃO clica em NADA. Antes os fallbacks
    # procuravam 'Continue'/'Continuar' na PÁGINA INTEIRA e acertavam o botão do
    # FUNDO da Central ("Pick up where you left off → Continue"): abria o modal de
    # intro POR CIMA do de SMS, o loop clicava 'Get started' nele e a Meta devolvia
    # "Sorry, something went wrong" (relato do dono, 2026-10-13). Um humano não
    # consegue clicar atrás de um modal — o robô também não.
    if _avanco_dialogo_desabilitado(driver, _txt):
        logger.info("[ProMax] Avançar do pop-up DESABILITADO — não clico (nada fora do pop-up).")
        return False
    if _clicar_botao_robusto(driver, _txt, timeout=timeout):
        return True
    # Idioma NÃO mapeado (o botão não se chama Avançar/Next/...): clica o botão
    # PRIMÁRIO azul do diálogo do formulário pela ESTRUTURA/cor. (2026-10-05)
    return _primario_dialogo(driver, clicar=True) == 'clicado'


_JS_DLG_MODAIS = r"""
    const _visM = e => { if(!e) return false; const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
        return r.width>120 && r.height>120 && s.visibility!=='hidden' && s.display!=='none'; };
    const _SELF = 'input,select,textarea,[role="radio"],[role="combobox"],[role="textbox"],[role="listbox"]';
    // Diálogos visíveis, do FUNDO p/ o TOPO (ordem do DOM = ordem de empilhamento do FB).
    const dlgsVis = () => [...document.querySelectorAll('[role="dialog"]')].filter(_visM);
    // Há um pop-up do FLUXO (com campo/escolha) aberto? Então TODO clique fica dentro de pop-up.
    const temDlgForm = () => dlgsVis().some(d => d.querySelector(_SELF));
"""


def _ha_dialogo_form(driver) -> bool:
    """True se há um pop-up do fluxo (diálogo visível com campo/rádio) aberto."""
    try:
        return bool(driver.evaluate_page("() => {" + _JS_DLG_MODAIS + " return temDlgForm(); }"))
    except Exception:
        return False


def _fechar_intro_sobre_fluxo(driver) -> bool:
    """Pop-up SEM campo (intro "Verify <empresa> / Get started", landing) EMPILHADO POR
    CIMA de um pop-up do FLUXO já aberto (ex.: o de SMS): clicar 'Get started' nele abre
    um 2º assistente → "Sorry, something went wrong". Aqui fecha SÓ o de cima (X /
    aria-label Fechar/Close/Cerrar/…) e o fluxo retoma no de baixo. True se fechou."""
    try:
        r = driver.evaluate_page("() => {" + _JS_DLG_MODAIS + r"""
            const ds = dlgsVis();
            if (ds.length < 2) return 'um';
            const topo = ds[ds.length - 1];
            if (topo.querySelector(_SELF)) return 'topo_e_fluxo';
            if (!ds.slice(0, -1).some(d => d.querySelector(_SELF))) return 'sem_fluxo';
            const FECHAR = ['close','fechar','cerrar','fermer','schließen','chiudi','đóng','tutup',
                            'закрыть','kapat','dismiss'];
            const btns = [...topo.querySelectorAll('[role="button"],button')].filter(b => {
                const rr = b.getBoundingClientRect(); return rr.width > 1 && rr.height > 1; });
            let x = btns.find(b => FECHAR.includes(((b.getAttribute('aria-label')||'')+'').trim().toLowerCase()));
            if (!x) {
                // ícone sem texto no canto superior direito do pop-up
                const tr = topo.getBoundingClientRect();
                x = btns.find(b => { const rr = b.getBoundingClientRect();
                    return !(b.innerText||'').trim() && rr.top < tr.top + 80 && rr.left > tr.left + tr.width * 0.7; });
            }
            if (!x) return 'sem_x';
            x.click();
            return 'fechou';
        }""")
    except Exception:
        r = ''
    if r == 'fechou':
        logger.info("[ProMax] pop-up SEM campo empilhado sobre o fluxo — fechei SÓ ele (sem 'Get started').")
        return True
    return False


def _avanco_dialogo_desabilitado(driver, textos) -> bool:
    """True se há pop-up do fluxo aberto e o botão de avanço DELE (texto/aria-label, ou o
    primário azul) está DESABILITADO. Nesse estado não existe clique certo a dar."""
    alvos = [t.strip().lower() for t in textos]
    try:
        r = driver.evaluate_page("(alvos) => {" + _JS_DLG_MODAIS + r"""
            if (!temDlgForm()) return false;
            const norm = t => ((t||'')+'').replace(/\s+/g,' ').trim().toLowerCase();
            const d = dlgsVis().filter(x => x.querySelector(_SELF)).pop();
            let achou = false, habil = false;
            for (const b of d.querySelectorAll('[role="button"],button')) {
                if (b.getAttribute('aria-hidden') === 'true' || b.closest('[aria-hidden="true"]')) continue;
                const rr = b.getBoundingClientRect(); if (rr.width < 2 || rr.height < 2) continue;
                if (alvos.includes(norm(b.getAttribute('aria-label'))) || alvos.includes(norm(b.innerText))) {
                    achou = true;
                    if (!(b.getAttribute('aria-disabled') === 'true' || b.disabled === true)) habil = true;
                }
            }
            return achou && !habil;
        }""", alvos)
    except Exception:
        r = False
    if r:
        return True
    return _primario_dialogo(driver) == 'desabilitado'


def _clicar_botao_robusto(driver, textos, timeout=12):
    """Clique ROBUSTO para botões primários do React (ex.: 'Começar') que às vezes
    têm um OVERLAY por cima (div data-visualcompletion="ignore" style="inset:0")
    que faz o clique 'actionable' do Playwright FALHAR ('element intercepts pointer
    events') → o fluxo trava clicando no nada.

    Estratégia: (1) tenta o `_click_texto` normal (rápido); (2) FALLBACK em JS que
    acha o elemento por aria-label/texto EXATO, sobe até o [role="button"] e
    DISPARA os eventos direto nele (mouseover/down/up/click + .click()),
    IGNORANDO o hit-test do overlay. Retorna True se conseguiu disparar o clique."""
    # 🛡️ ESCOPO: com pop-up do fluxo aberto, o clique fica DENTRO dos pop-ups (topo →
    # fundo). Nunca no fundo da página (ex.: 'Continue' do card "Pick up where you left
    # off" atrás do modal de SMS → abria outro modal por cima → "something went wrong").
    _escopo = _ha_dialogo_form(driver)
    _sb = ('[role="dialog"] button, [role="dialog"] [role="button"], '
           '[role="dialog"] a[role="button"]') if _escopo else None
    if _click_texto(driver, textos, seletor_base=_sb, timeout=max(4, timeout // 2)):
        return True
    alvos = [t.strip().lower() for t in textos]
    try:
        ok = driver.evaluate_page(r"""([alvos, escopo]) => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
            const norm = t => ((t||'')+'').trim().toLowerCase();
            const usavel = b => b.getAttribute('aria-disabled') !== 'true' && b.disabled !== true
                                && b.getAttribute('aria-hidden') !== 'true' && !b.closest('[aria-hidden="true"]');
            // Raízes de busca: pop-ups visíveis do TOPO p/ o fundo (com escopo) ou a página.
            const raizes = escopo
                ? [...document.querySelectorAll('[role="dialog"]')].filter(d => {
                      const r = d.getBoundingClientRect(); return r.width > 120 && r.height > 120 && vis(d); }).reverse()
                : [document];
            let alvo = null;
            for (const raiz of raizes) {
                // 1) por aria-label OU texto exato num [role=button]/button.
                const btns = [...raiz.querySelectorAll('[role="button"],button,a[role="button"]')].filter(vis);
                for (const b of btns){
                    const al = norm(b.getAttribute && b.getAttribute('aria-label'));
                    const tx = norm(b.innerText);
                    if ((alvos.includes(al) || alvos.includes(tx)) && usavel(b)){ alvo = b; break; }
                }
                // 2) acha pelo texto curto e SOBE até o [role=button]/button.
                if (!alvo){
                    for (const e of [...raiz.querySelectorAll('span,div')].filter(vis)){
                        const tx = norm(e.innerText);
                        if (alvos.includes(tx) && tx.length <= 14){
                            const c = (e.closest && e.closest('[role="button"],button')) || e;
                            if (usavel(c)) { alvo = c; break; }
                        }
                    }
                }
                if (alvo) break;
            }
            if (!alvo) return false;
            try { alvo.scrollIntoView({block:'center'}); } catch(e){}
            const r = alvo.getBoundingClientRect();
            const opts = {bubbles:true, cancelable:true, view:window,
                          clientX:r.left + r.width/2, clientY:r.top + r.height/2};
            for (const t of ['mouseover','mousedown','mouseup','click']){
                try { alvo.dispatchEvent(new MouseEvent(t, opts)); } catch(e){}
            }
            return true;
        }""", [alvos, _escopo])
        if ok:
            logger.info("[ProMax] Clique robusto (JS dispatch) em %s.", textos)
        return bool(ok)
    except Exception as e:
        logger.debug("[ProMax] _clicar_botao_robusto JS falhou: %s", e)
        return False


def _pais_central_vazio(driver):
    """True se o campo País da Central ainda mostra o placeholder 'Selecionar um
    país' (vazio) — nesse caso o Avançar fica desabilitado até escolher Brasil."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
            const d = document.querySelector('[role="dialog"]') || document.body;
            const t = norm(d.innerText);
            // Se o texto do diálogo tem 'brasil' visível, o país JÁ está escolhido.
            if (t.indexOf('brasil') !== -1 || t.indexOf('brazil') !== -1) return false;
            return t.indexOf('selecionar um país') !== -1
                || t.indexOf('selecionar um pais') !== -1;
        }"""))
    except Exception:
        return False


def _pais_vazio_estrutural(driver):
    """Idioma-agnóstico: True SÓ quando o diálogo do País tem um [role=combobox] cujo
    texto NÃO contém 'bra' (Brasil/Brazil/Brésil/Brasilien...) E o botão primário está
    DESABILITADO. As duas provas juntas evitam re-selecionar um país já escolhido."""
    try:
        tem_cb = bool(driver.evaluate_page(r"""() => {
            const d = [...document.querySelectorAll('[role="dialog"]')]
                .filter(e => e.getBoundingClientRect().width > 0).pop();
            return !!(d && d.querySelector('[role="combobox"]'));
        }"""))
        if not tem_cb:
            return False
        from server.verificacao_bm import _pais_selecionado
        if _pais_selecionado(driver):
            return False
        return _primario_dialogo(driver) == 'desabilitado'
    except Exception:
        return False


def _selecionar_pais_brasil_central(driver):
    """Seleciona 'Brasil' no combo de País da Central (quando vier vazio)."""
    try:
        _click_texto(driver, ['Selecionar um país', 'Selecionar um pais', 'País', 'Country'],
                     seletor_base='[role="combobox"], [role="button"], button, div, span',
                     timeout=3)
        _delay_curto()
        _click_texto(driver, ['Brasil', 'Brazil'],
                     seletor_base='[role="option"], li[role="option"], li, div, span',
                     timeout=6)
        return True
    except Exception as e:
        logger.warning("[ProMax] Falha ao selecionar Brasil (país central): %s", e)
        return False


def _navegador_vivo(driver):
    """False se o navegador foi FECHADO (pelo usuário na mão ou caiu). Serve p/
    abortar a verificação NA HORA como Erro/Falha, em vez de ficar preso em
    'Processando' com um navegador que nem está mais aberto."""
    try:
        fn = getattr(driver, 'is_alive', None)
        if callable(fn):
            return bool(fn())
    except Exception:
        return False
    # Fallback (driver sem is_alive): leitura barata que quebra se estiver fechado.
    try:
        _ = list(getattr(driver, 'window_handles', []) or [])
        return True
    except Exception:
        return False


def _duplicar_aba_central(driver, business_id, status=None):
    """WORKAROUND do BUG do modal 'Ações necessárias' (Verificar empresa) que às
    vezes abre como SKELETON e FECHA sozinho — não abre (geralmente na 2ª tentativa
    de verificação; na 1ª quase sempre abre). Reproduz o que o usuário faz na mão:
    abre uma NOVA aba (clone) na MESMA URL do security_center, troca o foco pra ela
    e FECHA a aba antiga que ficou presa no bug. Na aba nova o clique volta a abrir
    o modal normalmente. Retorna True se conseguiu duplicar/trocar de aba."""
    def _s(m):
        logger.info("[ProMax] %s", m)
        if status:
            try:
                status(m)
            except Exception:
                pass
    try:
        try:
            antiga = driver.current_window_handle
        except Exception:
            _hs = list(getattr(driver, 'window_handles', []) or [])
            antiga = _hs[0] if _hs else None

        url_alvo = (_url_atual(driver) or '')
        if 'security_center' not in url_alvo:
            url_alvo = f"{BASE}/security_center?business_id={business_id}"

        handles_antes = list(getattr(driver, 'window_handles', []) or [])
        nova = None
        # 1) Preferir a API nativa do driver (Playwright), se existir.
        if hasattr(driver, 'open_new_tab'):
            try:
                nova = driver.open_new_tab(url_alvo, switch=True, wait_networkidle=False)
            except Exception:
                nova = None
        # 2) Fallback: window.open + descobre o novo handle.
        if not nova:
            try:
                driver.execute_script("window.open(arguments[0], '_blank');", url_alvo)
            except Exception:
                try:
                    driver.execute_script(f"window.open({url_alvo!r}, '_blank');")
                except Exception:
                    pass
            _fim = time.time() + 8
            while time.time() < _fim:
                _novos = [h for h in (getattr(driver, 'window_handles', []) or [])
                          if h not in handles_antes]
                if _novos:
                    nova = _novos[-1]
                    break
                time.sleep(0.2)
            if nova:
                try:
                    driver.switch_to.window(nova)
                except Exception:
                    pass

        # Garante que a aba nova está na URL certa (a API nativa já navega; o
        # fallback window.open com URL também — mas reforça por segurança).
        try:
            if 'security_center' not in (_url_atual(driver) or ''):
                driver.get(url_alvo)
        except Exception:
            pass
        try:
            _esperar_estatico(driver, timeout=25)
        except Exception:
            pass

        # Fecha a aba ANTIGA (presa no bug) — mantendo só a nova.
        try:
            if antiga and antiga != nova and antiga in (getattr(driver, 'window_handles', []) or []):
                driver.switch_to.window(antiga)
                driver.close()
        except Exception:
            pass
        # Volta o foco para a aba nova (ou a última que sobrou).
        try:
            _hs = list(getattr(driver, 'window_handles', []) or [])
            if nova and nova in _hs:
                driver.switch_to.window(nova)
            elif _hs:
                driver.switch_to.window(_hs[-1])
        except Exception:
            pass

        # Deixa a aba NOVA renderizar 100%. NÃO clicamos aqui: quem clica é a
        # máquina de estados (handler 'iniciar'/'acoes_necessarias'), com 1 clique
        # REAL + espera do modal abrir 100% antes do próximo passo. Assim não há
        # cliques concorrentes/spam (que era o que travava o FB no skeleton).
        try:
            _esperar_estatico(driver, timeout=15)
        except Exception:
            pass

        _s("🔁 Botão travado — abri em NOVA ABA; o fluxo segue com clique único e paciente.")
        return True
    except Exception as e:
        logger.warning("[ProMax] _duplicar_aba_central falhou: %s", e)
        return False


def _dispensar_coachmark(driver):
    """Fecha coachmarks/tooltips PROMOCIONAIS do FB que ficam SOBRE a tela do fluxo
    (ex.: 'As ferramentas de criação de conteúdo agora também estão no menu
    principal' + 'Entendi'). Só mexe em diálogos que NÃO são o modal do fluxo —
    ou seja, SEM campos de formulário e SEM marcadores do fluxo. Clica
    'Entendi/Got it/OK' ou, em último caso, o X de Fechar DESSE coachmark.
    NUNCA fecha o modal do fluxo (isso cancelaria a verificação). Retorna True
    se dispensou algo."""
    # Host do site DESTA empresa (setado por aba em _submeter_central): um diálogo que
    # mostra o domínio da empresa é tela do FLUXO (ex.: 'Domínio verificado'), nunca promo.
    try:
        _hosts = list(getattr(driver, '_pm_site_hosts', None) or [])
    except Exception:
        _hosts = []
    try:
        return bool(driver.evaluate_page(r"""(hosts) => {
            hosts = (hosts || []).map(h => ((h||'')+'').toLowerCase()).filter(h => h.length >= 4);
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
            // 🔒 GUARDA DO CAPTCHA: se há IFRAME do reCAPTCHA VISÍVEL, é a tela do
            // captcha ("Help us confirm it's you") — NUNCA dispensar (quem resolve é o
            // CapSolver). O checkbox fica no iframe, então o modal não tem <input> e
            // seu texto (em inglês) não casava o FLOW → era FECHADO por engano. (2026-10-07)
            const capIfr = [...document.querySelectorAll(
                'iframe[src*="recaptcha"],iframe[title*="reCAPTCHA"],iframe[title*="recaptcha"]')].some(vis);
            if (capIfr) return false;
            // Texto que SÓ aparece no modal do fluxo (se houver, NÃO é coachmark):
            const FLOW = ['avançar','avancar','continuar','começar','comecar','enviar sms',
                'iniciar verificação','iniciar verificacao','identificação fiscal','identificacao fiscal',
                'informações de contato','informacoes de contato','selecione','endereço da organização',
                'endereco da organizacao','não sou um robô','nao sou um robo','carregar documento',
                'verificação de domínio','verificacao de dominio','sua empresa tem registro',
                'insira o código','insira o codigo','digite o código','digite o codigo',
                // EN/ES do captcha (defesa extra além da guarda por iframe acima):
                'help us confirm it',"i'm not a robot",'confirm you are human',
                'confirma que eres t','ayúdanos a confirmar','ayudanos a confirmar',
                // EN/ES do ASSISTENTE (2026-10-12): sem isto, em conta EN uma tela do fluxo
                // SEM campo e ainda não mapeada caía aqui e o X 'Close' FECHAVA o assistente
                // → volta p/ 'Iniciar verificação' → Ações → País → ... (loop #3266 en_GB).
                'business verification','verify your business','verification method',
                'verified domain','domain verified','business domain','tax id',
                'contact information','organization address','organisation address',
                'send sms','enter the code','required actions','legitimate connection',
                'verificación de la empresa','verificar tu empresa','dominio verificado'];
            // Botões de NAVEGAÇÃO do assistente (texto/aria-label EXATO, multi-idioma):
            // diálogo com eles é passo do FLUXO → nunca clicar Fechar/Cancelar nele (só um
            // 'Entendi/Got it/Pular' explícito, que não existe no assistente).
            const NAV = ['avançar','avancar','voltar','next','back','siguiente','atrás','atras',
                'anterior','tiếp','tiếp tục','quay lại','далее','назад','продолжить',
                'berikutnya','lanjut','lanjutkan','kembali','आगे','वापस','जारी रखें',
                'weiter','zurück','suivant','retour','avanti','indietro','ileri','geri'];
            const SAFE_DISMISS = ['entendi','entendido','ok, entendi','ok entendi','got it',
                'dispensar','pular','skip'];
            // 'cancelar'/'cancel' = fica NO fluxo quando aparece o diálogo "Sair?/Sim,
            // sair/Cancelar" (interrompe o fluxo) — NUNCA clica 'Sair'/'Sim, sair' (sair
            // do fluxo). Cobre o travamento 'coachmark' do diálogo de saída. (2026-07-12)
            const DISMISS = ['entendi','entendido','ok, entendi','ok entendi','got it','ok',
                'dispensar','agora não','agora nao','pular','skip','cancelar','cancel'];
            const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
            for (const d of dlgs){
                const t = ((d.innerText)||'').toLowerCase();
                const temForm = !!d.querySelector('input,select,textarea,[role="radio"],[role="combobox"],[role="textbox"],[role="listbox"]');
                if (temForm) continue;                       // modal do fluxo — não toca
                if (FLOW.some(k => t.includes(k))) continue;  // tem texto do fluxo — não toca
                if (hosts.some(h => t.includes(h))) continue; // mostra o domínio da empresa — fluxo
                const btnsD = [...d.querySelectorAll('div[role="button"],button,a[role="button"]')].filter(vis);
                const temNav = btnsD.some(b => {
                    const bt=((b.innerText||'')+'').trim().toLowerCase();
                    const al=(((b.getAttribute&&b.getAttribute('aria-label'))||'')+'').trim().toLowerCase();
                    return NAV.includes(bt) || NAV.includes(al);
                });
                if (temNav){
                    // Provável passo do assistente em idioma/tela não mapeado: só dispensa por
                    // um botão explícito de 'entendi/pular'; NUNCA Fechar(X)/Cancelar.
                    for (const b of btnsD){
                        const bt=((b.innerText||'')+'').trim().toLowerCase();
                        if (SAFE_DISMISS.includes(bt)){ try{ b.click(); return true; }catch(x){} }
                    }
                    continue;
                }
                // É coachmark/promo. 1) botão de dispensar por TEXTO exato:
                for (const b of btnsD){
                    const bt=((b.innerText||'')+'').trim().toLowerCase();
                    if (DISMISS.includes(bt)){ try{ b.click(); return true; }catch(x){} }
                }
                // 2) senão, X de Fechar DESTE coachmark:
                for (const b of d.querySelectorAll('[aria-label],div[role="button"]')){
                    if(!vis(b)) continue;
                    const al=(((b.getAttribute&&b.getAttribute('aria-label'))||'')+'').trim().toLowerCase();
                    if (al==='fechar'||al==='close'||al==='dispensar'){ try{ b.click(); return true; }catch(x){} }
                }
            }
            return false;
        }""", _hosts))
    except Exception:
        return False


def _hosts_do_site(site_url):
    """Host do site da empresa (subdomínio completo) + domínios-pai (sem o TLD puro),
    em minúsculas — usados SÓ para reconhecer, por DADO (idioma-agnóstico), um diálogo
    do fluxo que exibe o domínio verificado. Ex.: 'a.b.com' → ['a.b.com', 'b.com']."""
    try:
        from urllib.parse import urlparse
        s = str(site_url or '').strip()
        if not s:
            return []
        if '://' not in s:
            s = 'https://' + s
        h = (urlparse(s).hostname or '').lower().strip('.')
        if h.startswith('www.'):
            h = h[4:]
        partes = [p for p in h.split('.') if p]
        if len(partes) < 2:
            return []
        _sld = {'com', 'net', 'org', 'gov', 'edu', 'co', 'ac', 'gob', 'nom', 'ind', 'eti', 'adv'}
        out = []
        for i in range(0, len(partes) - 1):
            c = '.'.join(partes[i:])
            # nunca um sufixo público ('com.br') nem algo curto demais (casaria texto à toa)
            if partes[i] in _sld or len(c) < 6:
                continue
            out.append(c)
        return out
    except Exception:
        return []


def _dialogo_dominio_sem_form(driver, hosts):
    """True se há um [role=dialog] VISÍVEL, SEM campo de formulário, cujo texto mostra o
    domínio DESTA empresa — é a tela 'Verifique com o domínio da empresa / Domínio
    verificado' em QUALQUER idioma (o texto não é mapeado, mas o DADO é nosso)."""
    if not hosts:
        return False
    try:
        return bool(driver.evaluate_page(r"""(hosts) => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>120 && r.height>120 && s.visibility!=='hidden' && s.display!=='none'; };
            const SEL = 'input,select,textarea,[role="radio"],[role="combobox"],[role="textbox"],[role="listbox"]';
            for (const d of [...document.querySelectorAll('[role="dialog"]')].filter(vis)) {
                if (d.querySelector(SEL)) continue;
                if (d.querySelector('iframe[src*="recaptcha"],iframe[title*="reCAPTCHA"]')) continue;
                const t = ((d.innerText || '') + '').toLowerCase();
                if (hosts.some(h => h && t.indexOf(h) !== -1)) return true;
            }
            return false;
        }""", list(hosts)))
    except Exception:
        return False


def _clicar_primario_dialogo_sem_form(driver, hosts):
    """Clica (mouse REAL) o botão PRIMÁRIO azul do diálogo SEM formulário que mostra o
    domínio da empresa — o 'Avançar/Next/Tiếp/Далее…' pela COR, não pelo texto. Usado só
    quando `_avancar` (texto + diálogo com form) não achou o botão. True se clicou."""
    if not hosts:
        return False
    try:
        info = driver.evaluate_page(r"""(hosts) => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
            const SEL = 'input,select,textarea,[role="radio"],[role="combobox"],[role="textbox"],[role="listbox"]';
            const azul = el => {
                const m = (getComputedStyle(el).backgroundColor || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/);
                if (!m) return false;
                const R=+m[1], G=+m[2], B=+m[3], A = m[4] === undefined ? 1 : +m[4];
                return A > 0.5 && B > 180 && B > R + 40 && G < 170 && R < 120;
            };
            const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(d => {
                const r = d.getBoundingClientRect(); return r.width>120 && r.height>120 && vis(d); });
            for (let i = dlgs.length - 1; i >= 0; i--) {
                const d = dlgs[i];
                if (d.querySelector(SEL)) continue;
                const t = ((d.innerText || '') + '').toLowerCase();
                if (!hosts.some(h => h && t.indexOf(h) !== -1)) continue;
                let melhor = null, mr = null;
                for (const b of d.querySelectorAll('[role="button"],button')) {
                    if (!vis(b)) continue;
                    const r = b.getBoundingClientRect();
                    if (r.width < 40 || r.height < 20) continue;
                    let ehAzul = azul(b);
                    if (!ehAzul) {
                        let k = 0;
                        for (const f of b.querySelectorAll('div,span')) {
                            if (k++ > 6) break;
                            const fr = f.getBoundingClientRect();
                            if (fr.width >= r.width * 0.8 && fr.height >= r.height * 0.8 && azul(f)) { ehAzul = true; break; }
                        }
                    }
                    if (!ehAzul) continue;
                    if (!melhor || r.top > mr.top + 4 || (Math.abs(r.top - mr.top) <= 4 && r.left > mr.left)) {
                        melhor = b; mr = r;
                    }
                }
                if (!melhor) return null;
                if (melhor.getAttribute('aria-disabled') === 'true' || melhor.disabled === true) return {des: true};
                try { melhor.scrollIntoView({block: 'center'}); } catch (e) {}
                const r = melhor.getBoundingClientRect();
                return {des: false, x: r.left + r.width / 2, y: r.top + r.height / 2};
            }
            return null;
        }""", list(hosts))
    except Exception:
        return False
    if not isinstance(info, dict) or info.get('des') or 'x' not in info:
        return False
    try:
        driver.mouse.click(float(info['x']), float(info['y']))
        logger.info("[ProMax] Clique ESTRUTURAL no primário do diálogo do domínio (sem form).")
        return True
    except Exception:
        return False


def _enviar_arquivo(driver, caminho, timeout=12):
    """Define o arquivo no <input type=file> (sem abrir o diálogo nativo do SO)."""
    fim = time.time() + timeout
    # Prioriza inputs que aceitam pdf.
    while time.time() < fim:
        try:
            inputs = driver.query_selector_all('input[type="file"]')
        except Exception:
            inputs = []
        # tenta primeiro os que aceitam pdf
        ordenados = []
        for el in inputs:
            try:
                acc = (el.get_attribute('accept') or '').lower()
            except Exception:
                acc = ''
            ordenados.append((0 if 'pdf' in acc else 1, el))
        ordenados.sort(key=lambda x: x[0])
        for _, el in ordenados:
            try:
                el.set_input_files(caminho)
                logger.info("[ProMax] Arquivo enviado ao input[type=file]: %s", caminho)
                return True
            except Exception as e:
                logger.debug("[ProMax] set_input_files falhou: %s", e)
        time.sleep(0.15)
    logger.warning("[ProMax] Nenhum input[type=file] aceitou o arquivo.")
    return False


def _remover_documentos_carregados(driver):
    """Remove QUALQUER documento já anexado na tela 'Carregar documentos'.

    A Meta só aceita 1 documento por seção e exibe o erro 'Você só pode carregar
    1 documento. Para adicionar outro documento, remova um dos já carregados.'.
    Quando o bot troca os dados (ex.: compra outro número e regenera o
    certificado numa nova tentativa), o certificado ANTIGO continua anexado na
    página — é preciso clicar no 'X' (⊗) ao lado do arquivo para removê-lo ANTES
    de enviar o novo. Sem isso, o 'Avançar' fica travado.

    Retorna a quantidade de documentos removidos (0 se a tela estava limpa)."""
    js = r"""() => {
        const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
            const s=getComputedStyle(e); return r.width>0 && r.height>0 &&
            s.visibility!=='hidden' && s.display!=='none'; };
        const isFileName = t => /\.(pdf|jpe?g|png)\b/i.test(t||'');
        const CHAVES = ['remover','remove','excluir','delete','apagar','descartar',
                        'fechar','close','dispensar','limpar','×','✕','⊗','x'];
        let removidos = 0;
        // Elementos visíveis que mostram um NOME de arquivo anexado (ex.: cert_x.pdf).
        const nomes = [...document.querySelectorAll('div,span,li,a,strong')].filter(e =>
            vis(e) && isFileName(e.innerText) && (e.innerText||'').length < 120);
        const vistos = new Set();
        for (const nome of nomes){
            // Sobe até o container da LINHA do arquivo (sem englobar a seção toda).
            let linha = nome;
            for (let i=0;i<5 && linha.parentElement;i++){
                const p = linha.parentElement;
                if ((p.innerText||'').length > 200) break;
                linha = p;
            }
            if (vistos.has(linha)) continue;
            vistos.add(linha);
            const cands = [...linha.querySelectorAll('[aria-label],[role="button"],button,svg,i,div,span')]
                .filter(vis);
            // 1) botão cujo aria-label/title/texto casa com 'remover/fechar/x'.
            let btn = null;
            for (const b of cands){
                const al  = (((b.getAttribute&&b.getAttribute('aria-label'))||'')+'').trim().toLowerCase();
                const tit = (((b.getAttribute&&b.getAttribute('title'))||'')+'').trim().toLowerCase();
                const txt = ((b.innerText||'')+'').trim().toLowerCase();
                if (CHAVES.some(k => al===k||tit===k||txt===k||(al&&al.includes(k))||(tit&&tit.includes(k)))){
                    btn = b; break;
                }
            }
            // 2) fallback: último controle clicável da linha (o ⊗ costuma ser o último à direita).
            if (!btn){
                const clic = cands.filter(b =>
                    b.getAttribute('role')==='button' || b.tagName==='BUTTON' ||
                    b.tagName==='SVG' || (b.getAttribute&&b.getAttribute('aria-label')));
                if (clic.length) btn = clic[clic.length-1];
            }
            if (btn){
                try{
                    const alvo = btn.closest('[role=button],button') || btn;
                    alvo.scrollIntoView({block:'center'});
                    alvo.click();
                    removidos++;
                }catch(e){}
            }
        }
        return removidos;
    }"""
    try:
        n = int(driver.evaluate_page(js) or 0)
    except Exception:
        n = 0
    if n:
        logger.info("[ProMax] Removidos %s documento(s) antigo(s) antes do upload.", n)
    return n


def _injetar_recaptcha(driver, token):
    """Injeta o token resolvido pelo CapSolver no widget reCAPTCHA do Facebook.

    O widget vive num iframe (fbsbx.com). Percorremos TODOS os frames da página
    setando o g-recaptcha-response e disparando os callbacks (successCallback do
    FB + callbacks do registry grecaptcha enterprise)."""
    js = r"""(token) => {
        let did = false;
        try {
            document.querySelectorAll(
                'textarea#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea[id^="g-recaptcha-response"]'
            ).forEach(function(ta){
                ta.value = token; ta.innerHTML = token;
                ta.style.display='';
                try{ ta.dispatchEvent(new Event('input',{bubbles:true})); }catch(e){}
                try{ ta.dispatchEvent(new Event('change',{bubbles:true})); }catch(e){}
                did = true;
            });
        } catch(e){}
        try {
            document.querySelectorAll('.g-recaptcha,[data-sitekey],[data-callback]').forEach(function(w){
                var cb = w.getAttribute && w.getAttribute('data-callback');
                if (cb && typeof window[cb] === 'function'){ try{ window[cb](token); did=true; }catch(e){} }
            });
        } catch(e){}
        try { if (typeof window.successCallback==='function'){ window.successCallback(token); did=true; } } catch(e){}
        try { if (window.parent && typeof window.parent.successCallback==='function'){ window.parent.successCallback(token); did=true; } } catch(e){}
        try {
            var cfg = window.___grecaptcha_cfg;
            if (cfg && cfg.clients){
                Object.keys(cfg.clients).forEach(function(k){
                    var c = cfg.clients[k];
                    Object.keys(c||{}).forEach(function(k2){
                        var o = c[k2];
                        if (o && typeof o==='object'){
                            Object.keys(o).forEach(function(k3){
                                var x = o[k3];
                                if (x && typeof x==='object' && typeof x.callback==='function'){
                                    try{ x.callback(token); did=true; }catch(e){}
                                }
                            });
                        }
                    });
                });
            }
        } catch(e){}
        return did;
    }"""
    page = getattr(driver, '_current_page', None)
    feito = False
    frames = []
    try:
        if page is not None:
            frames = list(page.frames)
    except Exception:
        frames = []
    for fr in frames:
        try:
            if fr.evaluate(js, token):
                feito = True
        except Exception:
            continue
    if not feito:
        # fallback: frame/página atual via wrapper
        try:
            feito = bool(driver.evaluate_page(js, token))
        except Exception:
            pass
    return feito


def _ler_sitekey(driver):
    """Lê o data-sitekey real do reCAPTCHA (percorre frames). Fallback: padrão FB."""
    js = "() => { var e=document.querySelector('[data-sitekey]'); return e? e.getAttribute('data-sitekey') : ''; }"
    page = getattr(driver, '_current_page', None)
    try:
        if page is not None:
            for fr in list(page.frames):
                try:
                    k = fr.evaluate(js)
                    if k:
                        return k
                except Exception:
                    continue
    except Exception:
        pass
    try:
        k = driver.evaluate_page(js)
        if k:
            return k
    except Exception:
        pass
    return SITEKEY_FACEBOOK_PADRAO


# ---------------------------------------------------------------------- #
# GATE — BM bloqueada para anunciar?
# ---------------------------------------------------------------------- #
# Mensagens de RESTRIÇÃO (o "cadeado") na tela 'Contas de anúncios'. São frases
# específicas da Meta — nenhuma delas aparece numa BM saudável (que mostra apenas
# 'Nenhuma conta de anúncios adicionada' ou a lista de contas).
_RESTRICAO_ANUNCIOS_TXT = [
    'você não pode usar este portfólio empresarial para anunciar',
    'voce nao pode usar este portfolio empresarial para anunciar',
    'não é possível usar a empresa',
    'nao e possivel usar a empresa',
    "you can't use this business portfolio to advertise",
    # Variantes do "cadeado" (2026-08-17) — a BM restrita nem sempre traz a frase
    # longa acima; às vezes só o rótulo curto de restrição/desativação.
    'este portfólio empresarial está restrito',
    'este portfolio empresarial esta restrito',
    'portfólio empresarial restrito',
    'portfolio empresarial restrito',
    'conta de anúncios desativada',
    'conta de anuncios desativada',
    'ad account disabled',
    'this business portfolio is restricted',
    'seu acesso à publicidade foi restrito',
    'seu acesso a publicidade foi restrito',
    'advertising access restricted',
]


def _bm_bloqueada_para_anuncios(driver, business_id, status):
    status("🔎 Verificando se a BM está liberada para anunciar...")
    _ir_para(driver, f"{BASE}/ad_accounts?business_id={business_id}",
             esperar=['ad_accounts'], timeout=35)
    _delay_medio()
    if _existe_texto(driver, _RESTRICAO_ANUNCIOS_TXT, timeout=8):
        status("⛔ BM BLOQUEADA para anúncios (restrição/cadeado) — não vamos enviar para análise.")
        return True
    return False


def _bm_bloqueada_apps(driver, business_id, status):
    """Confere a aba 'Apps' do portfólio DEPOIS de criar a conta de anúncios
    (pedido do usuário 2026-07-08 — fluxo GS Prime Plus). É o veredito definitivo:
      - "Você não pode usar este portfólio empresarial para anunciar" / "Não é
        possível usar a empresa ... para criar anúncios" → BM RESTRITA (True);
      - "Nenhum aplicativo adicionado" (ou lista de apps) → BM ATIVA (False).
    Retorna True se restrita/bloqueada. Best-effort: se a tela não for
    reconhecida, retorna False (não bloqueia o fluxo à toa)."""
    status("🔎 Conferindo a aba 'Apps' (BM ativa ou restrita?)...")
    _ir_para(driver, f"{BASE}/apps?business_id={business_id}",
             esperar=['/apps', 'settings/apps'], timeout=35)
    _delay_medio()
    bloq_txts = [
        'você não pode usar este portfólio empresarial para anunciar',
        'voce nao pode usar este portfolio empresarial para anunciar',
        'não é possível usar a empresa',
        'nao e possivel usar a empresa',
        "you can't use this business portfolio to advertise",
        'para criar anúncios', 'para criar anuncios',
    ]
    if _existe_texto(driver, bloq_txts, timeout=8):
        status("⛔ Aba 'Apps': BM RESTRITA para anunciar.")
        return True
    # ATIVA: aparece "Nenhum aplicativo adicionado" (ou a lista de apps) e o botão
    # 'Adicionar' — sem a mensagem de bloqueio.
    if _existe_texto(driver, ['nenhum aplicativo adicionado', 'no apps added',
                              'nenhum app adicionado'], timeout=4):
        status("✅ Aba 'Apps': BM ATIVA (sem bloqueio) — seguindo o fluxo.")
    return False


# ---------------------------------------------------------------------- #
# Trocar o telefone comercial da empresa
# ---------------------------------------------------------------------- #
def _clicar_editar_detalhes(driver, timeout=12):
    """Clica no botão 'Editar' da seção 'Detalhes da empresa' (o 2º 'Editar')."""
    js = r"""() => {
        const norm = s => (s||'').trim().toLowerCase();
        const _isEdit = t => t === 'editar' || t === 'edit' || t === 'editar detalles';
        const _isDet = t => t === 'detalhes da empresa' || t === 'business details'
                         || t === 'detalles del negocio' || t === 'detalles de la empresa';
        // 1) tenta achar o 'Editar/Edit' irmão do título "Detalhes da empresa/Business details"
        const heads = [...document.querySelectorAll('div,span,h2,h3,strong')]
            .filter(e => _isDet(norm(e.innerText)));
        for (const h of heads) {
            let node = h;
            for (let i=0;i<6 && node;i++){
                const cand = [...node.querySelectorAll('div[role=button],span[role=button],a,button')]
                    .find(b => _isEdit(norm(b.innerText)) && b.offsetParent !== null);
                if (cand){ cand.click(); return true; }
                node = node.parentElement;
            }
        }
        // 2) fallback: clica no 2º 'Editar/Edit' visível da página
        const editars = [...document.querySelectorAll('div[role=button],span[role=button],a,button')]
            .filter(b => _isEdit(norm(b.innerText)) && b.offsetParent !== null);
        if (editars.length >= 2){ editars[1].click(); return true; }
        if (editars.length === 1){ editars[0].click(); return true; }
        return false;
    }"""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            if driver.evaluate_page(js):
                logger.info("[ProMax] Cliquei em Editar (Detalhes da empresa).")
                _delay_medio()
                return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


def _definir_telefone_empresa(driver, business_id, telefone_e164, status):
    """Abre Informações da empresa, edita Detalhes e troca o Telefone comercial."""
    status(f"☎️ Definindo telefone comercial da empresa: {telefone_e164}")
    _ir_para(driver, f"{BASE}/business_info?business_id={business_id}",
             esperar=['business_info'], timeout=35)
    _delay_medio()
    if not _clicar_editar_detalhes(driver):
        status("⚠️ Não achei o botão 'Editar' de Detalhes da empresa.")
        return False
    # GRAVAÇÃO CONFERIDA (2026-10-05, regra do dono: a BM tem que ficar com o número
    # REAL comprado — o mesmo do certificado, do site e da Central). Antes: campo por
    # rótulo PT/EN, Salvar por texto e NENHUMA conferência → se o save falhasse em
    # silêncio a BM seguia com o número aleatório do cadastro inicial.
    for _tent in range(2):
        if _tent:
            status("↻ Telefone comercial não persistiu — regravando...")
        if not _gravar_telefone_empresa_dialogo(driver, telefone_e164, status):
            return False
        r = _telefone_empresa_persistiu(driver, business_id, telefone_e164)
        if r is True:
            status(f"✅ Telefone comercial atualizado e CONFERIDO na BM: {telefone_e164}")
            return True
        if r is None:
            # Não deu p/ reabrir/ler o diálogo (layout inesperado): o save foi aceito
            # (diálogo fechou, sem erro de validação) — segue, registrando a ressalva.
            status("✅ Telefone comercial salvo (não consegui reler p/ conferir).")
            return True
        # r is False → o diálogo reaberto mostra OUTRO número: regrava (já está aberto).
    status("⚠️ O Telefone comercial da BM não ficou com o número comprado.")
    return False


def _campo_telefone_empresa(driver):
    """Marca os campos do diálogo 'Editar detalhes da empresa' pela POSIÇÃO estrutural
    (idioma-agnóstico, `verificacao_bm._marcar_campos_detalhes`) e devolve o valor do
    campo Telefone — ou None se o campo não foi localizado."""
    try:
        from server.verificacao_bm import _marcar_campos_detalhes
        _marcar_campos_detalhes(driver)
    except Exception as e:
        logger.debug("[ProMax] _marcar_campos_detalhes indisponível: %s", e)
    try:
        return driver.evaluate_page(
            """() => { const e = document.querySelector('[role="dialog"] [data-detalhe-campo="telefone"]');
                       return e ? (e.value || '') : null; }""")
    except Exception:
        return None


def _dialogo_aberto(driver):
    try:
        return bool(driver.evaluate_page(
            """() => [...document.querySelectorAll('[role="dialog"]')].some(d => {
                const r = d.getBoundingClientRect();
                return r.width > 120 && r.height > 120 && !!d.querySelector('input'); })"""))
    except Exception:
        return False


def _gravar_telefone_empresa_dialogo(driver, telefone_e164, status):
    """Com o diálogo 'Editar detalhes da empresa' ABERTO: digita o telefone (real,
    ritmo humano, só se diferir), confere o campo, clica Salvar e espera o diálogo
    FECHAR. Retorna True se o save foi aceito."""
    alvo = _digitos_nacionais(telefone_e164)
    if len(alvo) < 10:
        status("⚠️ Sem número comprado válido p/ o Telefone comercial.")
        return False
    _existe_texto(driver, ['Editar detalhes da empresa', 'Telefone comercial',
                           'Edit business details', 'Business phone'], timeout=8)
    _aguardar_dialogo_pronto(driver, timeout=6)
    sel = '[role="dialog"] [data-detalhe-campo="telefone"]'
    atual = _campo_telefone_empresa(driver)
    if atual is None:
        # Layout inesperado: cai no preenchimento por rótulo (legado).
        if not _preencher_campo_por_rotulo(
                driver, ['telefone comercial', 'business phone', 'telefone', 'phone'],
                telefone_e164, timeout=10):
            status("⚠️ Não consegui preencher o Telefone comercial.")
            return False
    elif not _so_digitos(atual).endswith(alvo):
        _digitar_real(driver, sel, telefone_e164)
        lido = _so_digitos(_campo_telefone_empresa(driver))
        if not lido.endswith(alvo):
            # a máscara pode recusar o '+': tenta só os dígitos com DDI
            _digitar_real(driver, sel, _so_digitos(telefone_e164))
            lido = _so_digitos(_campo_telefone_empresa(driver))
        if not lido.endswith(alvo):
            status("⚠️ O campo Telefone comercial não aceitou o número comprado.")
            return False
    else:
        # Já está com o número comprado: nada a salvar (Salvar fica desabilitado).
        try:
            from server.verificacao_bm import _fechar_popup
            _fechar_popup(driver)
        except Exception:
            pass
        _delay_curto()
        return True
    _aguardar_dialogo_pronto(driver, timeout=5)
    time.sleep(random.uniform(0.8, 1.4))
    clicou = False
    try:
        from server.verificacao_bm import _clicar_botao_salvar
        clicou = bool(_clicar_botao_salvar(driver))
    except Exception as e:
        logger.debug("[ProMax] _clicar_botao_salvar: %s", e)
    if not clicou and not _click_texto(driver, ['Salvar', 'Save', 'Guardar'], timeout=8):
        status("⚠️ Não achei o botão Salvar do telefone.")
        return False
    # Espera o diálogo FECHAR (= a Meta aceitou o save).
    fim = time.time() + 15
    while time.time() < fim:
        if not _dialogo_aberto(driver):
            return True
        time.sleep(0.5)
    status("⚠️ O diálogo do Telefone comercial não fechou após Salvar (save não aceito).")
    try:
        from server.verificacao_bm import _fechar_popup
        _fechar_popup(driver)
    except Exception:
        pass
    return False


def _telefone_empresa_persistiu(driver, business_id, telefone_e164):
    """Confere se a BM FICOU com o número comprado: recarrega 'Informações da empresa',
    reabre 'Editar' e lê o campo Telefone. True = confere (fecha o diálogo);
    False = mostra outro número (deixa o diálogo ABERTO p/ regravar);
    None = não foi possível reler."""
    alvo = _digitos_nacionais(telefone_e164)
    try:
        _ir_para(driver, f"{BASE}/business_info?business_id={business_id}",
                 esperar=['business_info'], timeout=35)
        _delay_medio()
        if not _clicar_editar_detalhes(driver):
            return None
        fim = time.time() + 10
        while time.time() < fim and not _dialogo_aberto(driver):
            time.sleep(0.4)
        _aguardar_dialogo_pronto(driver, timeout=6)
        lido = _campo_telefone_empresa(driver)
        if lido is None:
            try:
                from server.verificacao_bm import _fechar_popup
                _fechar_popup(driver)
            except Exception:
                pass
            return None
        if _so_digitos(lido).endswith(alvo):
            try:
                from server.verificacao_bm import _fechar_popup
                _fechar_popup(driver)
            except Exception:
                pass
            _delay_curto()
            return True
        logger.warning("[ProMax] Telefone comercial na BM = %r, esperado terminar em %s", lido, alvo)
        return False
    except Exception as e:
        logger.debug("[ProMax] conferência do telefone comercial falhou: %s", e)
        return None


# ---------------------------------------------------------------------- #
# Pop-up da Central: campos e cliques REAIS + conferidos (2026-10-05)
# ---------------------------------------------------------------------- #
# Problema relatado pelo dono: na tela de contato a Meta acusava "número de telefone
# inválido", mas clicando Avançar NA MÃO passava. Causa: os campos eram gravados por
# evento SINTÉTICO (setter + dispatchEvent) e o Avançar era clicado logo em seguida —
# o Site era regravado em TODA passagem, então o clique sempre caía antes de a Meta
# terminar de carregar/validar os campos. O robô então ficava preso e trocava de número.
# Agora: digitação REAL (só quando o valor difere), espera o pop-up ASSENTAR, clique
# REAL de mouse conferido, e — se a Meta acusar erro com o número certo no campo —
# reclica (como o dono faz na mão) em vez de trocar de número.
_JS_DLG_FORM = r"""
    const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
        const s=getComputedStyle(e);
        return r.width>1 && r.height>1 && s.visibility!=='hidden' && s.display!=='none'; };
    const dlgForm = () => {
        const SEL = 'input,select,textarea,[role="radio"],[role="combobox"],[role="textbox"],[role="listbox"]';
        const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(d => {
            const r=d.getBoundingClientRect(); return r.width>120 && r.height>120 && vis(d); });
        for (let i = dlgs.length - 1; i >= 0; i--) if (dlgs[i].querySelector(SEL)) return dlgs[i];
        return null;
    };
"""


def _marcar_campos_contato(driver):
    """Marca no pop-up de contato o input do TELEFONE (`data-gsct="tel"`) e o do SITE
    (`data-gsct="site"`) e devolve {'tel': valor|None, 'site': valor|None}."""
    try:
        r = driver.evaluate_page("() => {" + _JS_DLG_FORM + r"""
            const norm = s => (s||'').toLowerCase();
            const d = dlgForm() || document;
            document.querySelectorAll('[data-gsct]').forEach(e => e.removeAttribute('data-gsct'));
            const inputs = [...d.querySelectorAll('input')].filter(e => vis(e) && !e.disabled
                && !['hidden','file','checkbox','radio'].includes((e.type||'').toLowerCase()));
            const rot = e => norm((e.getAttribute('aria-label')||'') + ' ' + (e.placeholder||''));
            const ehSite = e => { const t = rot(e), v = norm(e.value||'');
                return t.includes('site') || t.includes('url') || t.includes('http')
                    || v.includes('http') || v.includes('www') || /[a-z0-9-]+\.[a-z]{2,}/.test(v); };
            const ehTel = e => { const t = rot(e);
                return norm(e.type||'') === 'tel' || t.includes('telefone') || t.includes('phone'); };
            let tel = inputs.find(ehTel) || null;
            let site = inputs.find(e => e !== tel && !ehTel(e) && ehSite(e)) || null;
            if (!tel) tel = inputs.find(e => e !== site && !ehSite(e)) || null;
            // layout fixo [Telefone, Site]: sem pista de rótulo/valor, o site é o seguinte
            if (!site && tel) { const i = inputs.indexOf(tel); site = inputs[i + 1] || null; }
            if (tel) tel.setAttribute('data-gsct', 'tel');
            if (site) site.setAttribute('data-gsct', 'site');
            return {tel: tel ? (tel.value||'') : null, site: site ? (site.value||'') : null};
        }""")
        return r if isinstance(r, dict) else {}
    except Exception:
        return {}


def _digitar_real(driver, seletor, valor):
    """Digitação REAL num input: clique de verdade, Ctrl+A, Delete e tecla a tecla
    (dispara os mesmos eventos de um humano — o React/validação da Meta 'enxerga')."""
    try:
        for el in driver.query_selector_all(seletor):
            if not _visivel(el):
                continue
            try:
                el.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            # Ritmo HUMANO (pedido do dono 2026-10-05): clica no campo → pausa →
            # LIMPA → pausa (a Meta processa o campo vazio) → digita tecla a tecla →
            # pausa (a Meta formata/valida) antes de qualquer outra ação.
            el.click(timeout=4000)
            time.sleep(random.uniform(0.35, 0.7))
            driver.keyboard.press('Control+a')
            time.sleep(random.uniform(0.12, 0.25))
            driver.keyboard.press('Delete')
            time.sleep(random.uniform(0.5, 0.9))
            for ch in str(valor):
                driver.keyboard.type(ch)
                time.sleep(random.uniform(0.06, 0.16))
            time.sleep(random.uniform(0.6, 1.0))
            return True
    except Exception as e:
        logger.debug("[ProMax] _digitar_real(%s) falhou: %s", seletor, e)
    return False


def _aguardar_dialogo_pronto(driver, timeout=6):
    """Espera o pop-up do formulário ASSENTAR antes de clicar: sem spinner/aria-busy,
    valores dos campos ESTÁVEIS entre duas leituras (a Meta terminou de carregar/
    formatar telefone e site) e botão primário não-desabilitado. Retorna True quando
    assentou (ou não há pop-up de formulário); False no timeout."""
    js = "() => {" + _JS_DLG_FORM + r"""
        const d = dlgForm();
        if (!d) return null;
        const busy = [...d.querySelectorAll('[role="progressbar"],[aria-busy="true"]')].some(vis);
        const vals = [...d.querySelectorAll('input,textarea')].filter(vis).map(e => e.value||'').join('\u0001');
        const des = [...d.querySelectorAll('[role="button"][aria-disabled="true"],button[disabled]')]
            .filter(vis).map(b => (b.innerText||'').trim()).join('|');
        return {busy: busy, sig: vals + '\u0002' + des + '\u0002' + (d.innerText||'').length};
    }"""
    fim = time.time() + max(1.5, timeout)
    ant = None
    while time.time() < fim:
        try:
            cur = driver.evaluate_page(js)
        except Exception:
            cur = None
        if cur is None:
            return True
        if not isinstance(cur, dict) or 'sig' not in cur:
            return True          # driver-stub/inesperado → não bloqueia
        if not cur.get('busy') and ant is not None and cur.get('sig') == ant:
            return True
        ant = cur.get('sig')
        time.sleep(0.5)
    return False


def _clicar_avancar_real(driver, textos, esperar_habilitar=5):
    """Clique REAL (mouse do Playwright, nas coordenadas do centro) no botão de avanço
    do pop-up do formulário. Acha o botão pelo texto/aria-label EXATO dentro do pop-up
    (fallback: primário azul), espera ele HABILITAR, confere que o ponto do clique
    cai NO botão (nada por cima) e só então clica. Retorna True se clicou de fato."""
    alvos = [t.strip().lower() for t in textos]
    js = "(alvos) => {" + _JS_DLG_FORM + r"""
        const d = dlgForm();
        document.querySelectorAll('[data-gsav]').forEach(e => e.removeAttribute('data-gsav'));
        if (!d) return null;
        const norm = t => ((t||'')+'').replace(/\s+/g,' ').trim().toLowerCase();
        let b = null;
        for (const c of d.querySelectorAll('[role="button"],button')) {
            if (!vis(c)) continue;
            if (alvos.includes(norm(c.getAttribute('aria-label'))) || alvos.includes(norm(c.innerText))) b = c;
        }
        if (!b) return null;
        try { b.scrollIntoView({block: 'center'}); } catch (e) {}
        const r = b.getBoundingClientRect();
        const x = r.left + r.width / 2, y = r.top + r.height / 2;
        const topo = document.elementFromPoint(x, y);
        b.setAttribute('data-gsav', '1');
        return {des: b.getAttribute('aria-disabled') === 'true' || b.disabled === true,
                livre: !!topo && (b.contains(topo) || topo.contains(b)), x: x, y: y};
    }"""
    fim = time.time() + max(1, esperar_habilitar)
    info = None
    while True:
        try:
            info = driver.evaluate_page(js, alvos)
        except Exception:
            info = None
        if isinstance(info, dict) and 'x' in info and not info.get('des') and info.get('livre'):
            break
        if time.time() >= fim:
            break
        time.sleep(0.4)
    if not (isinstance(info, dict) and 'x' in info):
        return False
    if info.get('des'):
        logger.info("[ProMax] Avançar ainda DESABILITADO — não clico (campos incompletos/validando).")
        return False
    try:
        x = float(info['x']) + random.uniform(-6, 6)
        y = float(info['y']) + random.uniform(-3, 3)
        driver.mouse.move(x, y, steps=random.randint(6, 12))
        time.sleep(random.uniform(0.08, 0.2))
        driver.mouse.click(x, y)
        logger.info("[ProMax] Clique REAL (mouse) no botão de avanço do pop-up.")
        return True
    except Exception as e:
        logger.debug("[ProMax] clique real falhou: %s", e)
        return False


def _erro_telefone_invalido(driver):
    """True se o pop-up acusa TELEFONE inválido (campo com aria-invalid ou a frase de
    erro, PT/EN/ES)."""
    try:
        return bool(driver.evaluate_page("() => {" + _JS_DLG_FORM + r"""
            const d = dlgForm();
            if (!d) return false;
            const tel = d.querySelector('[data-gsct="tel"]');
            if (tel && tel.getAttribute('aria-invalid') === 'true') return true;
            const t = (d.innerText||'').toLowerCase();
            return ['número de telefone válido','numero de telefone valido','telefone válido',
                    'telefone inválido','telefone invalido','número inválido','numero invalido',
                    'número de telefone inválido','numero de telefone invalido',
                    'valid phone number','invalid phone','phone number is invalid',
                    "phone number isn't valid",'número de teléfono válido','teléfono no es válido']
                .some(k => t.includes(k));
        }"""))
    except Exception:
        return False


def _definir_telefone_contato(driver, telefone_nacional, status=None):
    """Na tela 'Adicionar dados da empresa' (Informações de contato): APAGA o que
    estiver no campo Telefone e digita o número comprado ATUAL (dígitos nacionais,
    ex.: '28926918605'). SEMPRE substitui — essencial nos retries, em que o número
    muda; senão o SMS vai para o número antigo."""
    num = _so_digitos(telefone_nacional)
    if not num:
        return False
    # 1º) DIGITAÇÃO REAL (2026-10-05): o setter sintético abaixo deixava a validação
    #     da Meta fora de sincronia ("número inválido" com o número certo no campo).
    try:
        campos = _marcar_campos_contato(driver)
        if campos.get('tel') is not None:
            atual = _so_digitos(campos.get('tel'))
            _ja_certo = bool(atual and atual.endswith(num) and len(atual) >= len(num))
            if not _ja_certo:
                _digitar_real(driver, 'input[data-gsct="tel"]', num)
                time.sleep(0.3)
            lido = _so_digitos(_marcar_campos_contato(driver).get('tel'))
            if lido and lido.endswith(num):
                if status:
                    status(f"☎️ Telefone de contato já está correto ({num}) — mantido." if _ja_certo
                           else f"☎️ Telefone de contato corrigido: {num}")
                return True
    except Exception as e:
        logger.debug("[ProMax] telefone contato (digitação real): %s", e)
    js = r"""(num) => {
        const norm = s => (s||'').toLowerCase();
        const inputs = [...document.querySelectorAll('input')].filter(e=>e.offsetParent!==null);
        let alvo = null;
        // 1) campo cujo type/rótulo/placeholder indica telefone
        for (const inp of inputs){
            const t = norm(inp.getAttribute('aria-label')||inp.placeholder||'');
            const tp = norm(inp.type||'');
            if (tp==='tel' || t.includes('telefone') || t.includes('phone')){ alvo = inp; break; }
        }
        // 2) fallback: 1º input que NÃO seja o do site (http/www/site)
        if (!alvo){
            for (const inp of inputs){
                const v = norm(inp.value||'');
                const t = norm(inp.placeholder||inp.getAttribute('aria-label')||'');
                if (t.includes('site')||t.includes('http')||v.includes('http')||v.includes('www')) continue;
                alvo = inp; break;
            }
        }
        if (!alvo) return false;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        try{ alvo.focus(); }catch(e){}
        setter.call(alvo, '');                       // apaga o antigo
        alvo.dispatchEvent(new Event('input',{bubbles:true}));
        setter.call(alvo, num);                      // digita o novo
        alvo.dispatchEvent(new Event('input',{bubbles:true}));
        alvo.dispatchEvent(new Event('change',{bubbles:true}));
        alvo.dispatchEvent(new Event('blur',{bubbles:true}));
        const v = (alvo.value||'').replace(/\D/g,'');
        return v === num;
    }"""
    ok = False
    for _ in range(3):
        try:
            ok = bool(driver.evaluate_page(js, num))
        except Exception as e:
            logger.debug("[ProMax] definir telefone contato: %s", e)
            ok = False
        if ok:
            break
        time.sleep(0.1)
    if status:
        if ok:
            status(f"☎️ Telefone de contato atualizado: {num}")
        else:
            status("⚠️ Não confirmei o telefone de contato (seguindo mesmo assim).")
    return ok


def _telefone_contato_exato(driver, telefone_nacional):
    """Conferência ESTRITA: o campo Telefone do pop-up de contato contém EXATAMENTE o
    número comprado (dígitos nacionais, com ou sem o DDI 55). Diferente de
    `_telefone_confere` (tolerante, devolve True se não conseguir ler), aqui qualquer
    dúvida = False — é a trava que impede enviar p/ análise com número que não seja o
    REAL comprado."""
    num = _so_digitos(telefone_nacional)
    if not num:
        return False
    try:
        lido = _so_digitos(_marcar_campos_contato(driver).get('tel'))
    except Exception:
        return False
    return lido in (num, '55' + num)


def _telefone_confere(driver, telefone_nacional):
    """Lê o campo Telefone da tela de contato e diz se os dígitos batem com o número
    comprado ATUAL. Usado para só RE-preencher o telefone quando a Meta o zerou/alterou
    (re-preencher à toa RE-DISPARA a consulta do CNPJ e prende o passo)."""
    num = _so_digitos(telefone_nacional)
    if not num:
        return True  # sem número esperado, não força re-preenchimento
    js = r"""() => {
        const norm = s => (s||'').toLowerCase();
        const inputs = [...document.querySelectorAll('input')].filter(e=>e.offsetParent!==null);
        for (const inp of inputs){
            const t = norm(inp.getAttribute('aria-label')||inp.placeholder||'');
            const tp = norm(inp.type||'');
            const v = norm(inp.value||'');
            if (t.includes('site')||t.includes('http')||v.includes('http')||v.includes('www')) continue;
            if (tp==='tel' || t.includes('telefone') || t.includes('phone')){
                return (inp.value||'').replace(/\D/g,'');
            }
        }
        // fallback: 1º input que não é site
        for (const inp of inputs){
            const t = norm(inp.getAttribute('aria-label')||inp.placeholder||'');
            const v = norm(inp.value||'');
            if (t.includes('site')||t.includes('http')||v.includes('http')||v.includes('www')) continue;
            return (inp.value||'').replace(/\D/g,'');
        }
        return null;
    }"""
    try:
        atual = driver.evaluate_page(js)
    except Exception:
        return True  # não conseguiu ler → não arrisca re-disparar a consulta
    if atual is None:
        return True
    atual = re.sub(r'\D', '', str(atual))
    # o campo pode não conter o DDI (55); confere pela terminação (dígitos nacionais).
    return bool(atual) and (atual.endswith(num) or num.endswith(atual))


def _definir_site_contato(driver, site_url, status=None):
    """No popup 'Adicionar dados da empresa' (contato) GARANTE que o campo SITE fique
    com o SUBDOMÍNIO COMPLETO (ex.: 'sub.raiz.com'), não o domínio RAIZ. A Meta às vezes
    pré-preenche a raiz — principalmente no RETRY após trocar o número — e o site da BM
    tem que bater com o subdomínio (é o site verificado/da empresa). SEMPRE substitui.
    Retorna True se garantiu o subdomínio no campo. (2026-08-15 — pedido do usuário.)"""
    su = re.sub(r'^https?://', '', (site_url or '').strip(), flags=re.I).rstrip('/')
    if not su or '.' not in su or su.count('.') < 2:
        # Só age se for um SUBDOMÍNIO (>= 2 pontos, ex.: sub.raiz.com). Raiz pura não força.
        return False
    # IDEMPOTENTE + DIGITAÇÃO REAL (2026-10-05): se o campo JÁ está com o subdomínio,
    # NÃO toca (regravar em toda passagem fazia o Avançar ser clicado no meio da
    # revalidação da Meta). Só redigita — de verdade — quando o valor difere.
    try:
        campos = _marcar_campos_contato(driver)
        if campos.get('site') is not None:
            v = re.sub(r'^https?://', '', str(campos.get('site') or '').strip().lower()).rstrip('/')
            if v == su.lower():
                return True
            _digitar_real(driver, 'input[data-gsct="site"]', 'https://' + su)
            time.sleep(0.3)
            v2 = str(_marcar_campos_contato(driver).get('site') or '').lower()
            if su.lower() in v2:
                if status:
                    status(f"🌐 Site de contato garantido (subdomínio completo): {su}")
                return True
    except Exception as e:
        logger.debug("[ProMax] site contato (digitação real): %s", e)
    js = r"""(alvo) => {
        const norm = s => (s||'').toLowerCase();
        const inputs = [...document.querySelectorAll('input')].filter(e=>e.offsetParent!==null);
        let campo = null;
        for (const inp of inputs){
            const t = norm(inp.getAttribute('aria-label')||inp.placeholder||'');
            const v = norm(inp.value||'');
            const tp = norm(inp.type||'');
            if (tp==='tel' || t.includes('telefone') || t.includes('phone')) continue; // pula telefone
            if (t.includes('site')||t.includes('website')||t.includes('url')||t.includes('http')
                || v.includes('http')||v.includes('www')||/[a-z0-9-]+\.[a-z]{2,}/.test(v)){
                campo = inp; break;
            }
        }
        if (!campo) return false;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        try{ campo.focus(); }catch(e){}
        setter.call(campo, '');
        campo.dispatchEvent(new Event('input',{bubbles:true}));
        setter.call(campo, 'https://' + alvo);
        campo.dispatchEvent(new Event('input',{bubbles:true}));
        campo.dispatchEvent(new Event('change',{bubbles:true}));
        campo.dispatchEvent(new Event('blur',{bubbles:true}));
        return norm(campo.value||'').includes(norm(alvo));
    }"""
    ok = False
    for _ in range(3):
        try:
            ok = bool(driver.evaluate_page(js, su))
        except Exception as e:
            logger.debug("[ProMax] definir site contato: %s", e)
            ok = False
        if ok:
            break
        time.sleep(0.1)
    if status and ok:
        status(f"🌐 Site de contato garantido (subdomínio completo): {su}")
    return ok


# ---------------------------------------------------------------------- #
# Seleção de opção em lista com RADIO (ex.: "Selecione o tipo da empresa")
# ---------------------------------------------------------------------- #
def _selecionar_opcao_radio(driver, titulo_alvo, timeout=10):
    """Marca a opção de uma lista com radio pelo TÍTULO (ex.: 'Empresa individual').

    Clicar só no texto NÃO marca o radio (que fica num elemento à parte na linha),
    deixando o 'Avançar' desabilitado. Aqui localizamos a LINHA que contém o título
    e clicamos no próprio radio (e na linha), confirmando que ficou marcado."""
    alvo = (titulo_alvo or '').strip().lower()
    js = r"""(alvo) => {
        const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
        const primeiraLinha = e => norm((e.innerText||'').split('\n')[0]);
        const els = [...document.querySelectorAll('div,span,strong,label,h3,h4,p')];
        let titulo = null;
        for (const e of els){
            const t = norm(e.innerText);
            if ((t === alvo || primeiraLinha(e) === alvo) && (e.innerText||'').length < 220){
                titulo = e; break;
            }
        }
        if (!titulo) return 'sem_titulo';
        let node = titulo;
        for (let i=0;i<8 && node;i++){
            const radio = node.querySelector('[role=radio],input[type=radio]');
            if (radio){
                try{ radio.scrollIntoView({block:'center'}); }catch(e){}
                try{ radio.click(); }catch(e){}
                try{ (titulo.closest('[role=button],label') || titulo).click(); }catch(e){}
                const marcado = radio.getAttribute('aria-checked')==='true'
                                || radio.getAttribute('data-checked')==='true'
                                || radio.checked === true;
                return marcado ? 'ok' : 'clicado';
            }
            node = node.parentElement;
        }
        return 'sem_radio';
    }"""
    fim = time.time() + timeout
    ultimo = ''
    while time.time() < fim:
        try:
            r = driver.evaluate_page(js, alvo)
        except Exception:
            r = ''
        ultimo = r
        if r in ('ok', 'clicado'):
            logger.info("[ProMax] Radio '%s' -> %s", alvo, r)
            return True
        time.sleep(0.1)
    logger.warning("[ProMax] Não marquei o radio '%s' (último: %s)", alvo, ultimo)
    return False


def _selecionar_opcao_radio_multi(driver, titulos, timeout=10):
    """Tenta marcar o rádio por VÁRIOS títulos possíveis (PT/EN/ES) — idioma-agnóstico.
    Retorna True no 1º que marcar."""
    if isinstance(titulos, str):
        titulos = [titulos]
    # 1ª passada rápida por todos os títulos; se nenhum, repete até o timeout.
    fim = time.time() + timeout
    while time.time() < fim:
        for t in titulos:
            if _selecionar_opcao_radio(driver, t, timeout=1):
                return True
        time.sleep(0.15)
    return False


def _marcar_radio_email(driver, timeout=8):
    """📧 Marca o rádio 'Email (Recomendado)' na tela de método da Central de forma
    ROBUSTA. O `_selecionar_opcao_radio('Email')` falhava porque o título vem como
    'Email  Recomendado' (badge na mesma linha) → não casava o `=== 'email'`. Aqui
    achamos o RÁDIO cuja LINHA menciona 'recomendado' OU ('email' + '@') OU a frase
    'confirmação para um email' — que é EXCLUSIVA da opção de e-mail. (2026-08-15)"""
    js = r"""(() => {
        const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
        const radios = [...document.querySelectorAll('[role=radio],input[type=radio]')];
        for (const radio of radios){
            let node = radio, txt = '';
            for (let i=0;i<8 && node;i++){ const t = norm(node.innerText||''); if (t.length>20){ txt=t; break; } node = node.parentElement; }
            const ehEmail = txt.indexOf('recomendado')!==-1 || txt.indexOf('recommended')!==-1
                         || txt.indexOf('recomendado')!==-1
                         || txt.indexOf('confirmação para um email')!==-1
                         || txt.indexOf('confirmacao para um email')!==-1
                         || txt.indexOf('confirmation to an email')!==-1
                         || txt.indexOf('a confirmation to an email')!==-1
                         || (txt.indexOf('email')!==-1 && txt.indexOf('@')!==-1)
                         || (txt.indexOf('e-mail')!==-1 && txt.indexOf('@')!==-1);
            if (ehEmail){
                try{ radio.scrollIntoView({block:'center'}); }catch(e){}
                try{ radio.click(); }catch(e){}
                const m = radio.getAttribute('aria-checked')==='true'
                       || radio.getAttribute('data-checked')==='true' || radio.checked===true;
                return m ? 'ok' : 'clicado';
            }
        }
        return 'sem_email';
    })()"""
    fim = time.time() + timeout
    ultimo = ''
    while time.time() < fim:
        try:
            r = driver.evaluate_page(js)
        except Exception:
            r = ''
        ultimo = r
        if r in ('ok', 'clicado'):
            logger.info("[ProMax/E-mail] radio Email marcado -> %s", r)
            return True
        time.sleep(0.15)
    logger.warning("[ProMax/E-mail] não marquei o radio Email (último: %s)", ultimo)
    return False


def _marcar_radio_dominio(driver, timeout=8):
    """🌐 Marca o rádio 'Verificação de domínio' na tela 'Confirmar conexão' de forma
    ROBUSTA. O `_selecionar_opcao_radio('Verificação de domínio')` falhava com
    'sem_titulo' porque a LINHA do rádio traz título + descrição (ex.: 'Verificação de
    domínio\\nUse o domínio que você já verificou…'), então o match EXATO nunca casava
    e o fluxo caía no SMS (que não chega nos números). Aqui achamos o RÁDIO cuja LINHA
    menciona 'domínio'/'dominio' (opção EXCLUSIVA de domínio nessa tela — as outras são
    SMS/ligação/WhatsApp) e o marcamos. Assim pulamos o SMS inteiro. (2026-09-16)"""
    js = r"""(() => {
        const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
        const radios = [...document.querySelectorAll('[role=radio],input[type=radio]')];
        for (const radio of radios){
            let node = radio, txt = '';
            for (let i=0;i<8 && node;i++){ const t = norm(node.innerText||''); if (t.length>8){ txt=t; break; } node = node.parentElement; }
            // idioma-agnóstico: linha que menciona domínio/domain e NÃO é SMS/ligação/WhatsApp
            const ehDominio = (txt.indexOf('domínio')!==-1 || txt.indexOf('dominio')!==-1
                               || txt.indexOf('domain')!==-1)
                           && txt.indexOf('mensagem de texto')===-1 && txt.indexOf('text message')===-1
                           && txt.indexOf('ligação')===-1 && txt.indexOf('ligacao')===-1
                           && txt.indexOf('phone call')===-1 && txt.indexOf('whatsapp')===-1
                           && txt.indexOf('mensaje de texto')===-1 && txt.indexOf('llamada')===-1;
            if (ehDominio){
                try{ radio.scrollIntoView({block:'center'}); }catch(e){}
                try{ radio.click(); }catch(e){}
                try{ (radio.closest('[role=button],label') || radio.parentElement || radio).click(); }catch(e){}
                const m = radio.getAttribute('aria-checked')==='true'
                       || radio.getAttribute('data-checked')==='true' || radio.checked===true;
                return m ? 'ok' : 'clicado';
            }
        }
        return 'sem_dominio';
    })()"""
    fim = time.time() + timeout
    ultimo = ''
    while time.time() < fim:
        try:
            r = driver.evaluate_page(js)
        except Exception:
            r = ''
        ultimo = r
        if r in ('ok', 'clicado'):
            logger.info("[ProMax] radio 'Verificação de domínio' marcado -> %s", r)
            return True
        time.sleep(0.15)
    logger.warning("[ProMax] não marquei o radio 'Verificação de domínio' (último: %s)", ultimo)
    return False


def _marcar_radio_sms(driver, timeout=4):
    """📱 Marca o rádio 'Mensagem de texto (SMS)' / 'Text message (SMS)' na tela
    'Confirmar conexão' de forma ESTRUTURAL e idioma-agnóstica.

    DOM real (en, provado ao vivo 2026-10-13): cada opção é um `div[role=button]` com
    título + descrição + `<input type=radio>` dentro. O fast-path só tentava rótulos
    em PORTUGUÊS com 10s de timeout cada → em inglês nada era marcado, o 'Next' ficava
    desabilitado e a aba girava ~19 min (12 voltas × ~95s) parada na tela.
    Aqui: rádio cuja LINHA tem o token 'sms' (pt/en/es/…) ou 'mensagem de texto'/
    'text message'/'mensaje de texto'; sem isso, e com 3 opções onde a 3ª é WhatsApp,
    usa a do MEIO (ordem fixa da Meta: Ligação / SMS / WhatsApp)."""
    js = r"""(() => {
        const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
        const vis = d => { const r=d.getBoundingClientRect(); const s=getComputedStyle(d);
            return r.width>120 && r.height>120 && s.visibility!=='hidden' && s.display!=='none'; };
        // Pode haver 2+ diálogos visíveis (provado ao vivo): usa o ÚLTIMO que tem rádios.
        const dlgs = [...document.querySelectorAll('[role=dialog]')].filter(vis)
                       .filter(d => d.querySelector('[role=radio],input[type=radio]'));
        const raiz = dlgs.length ? dlgs[dlgs.length-1] : document;
        const radios = [...raiz.querySelectorAll('[role=radio],input[type=radio]')];
        if (!radios.length) return 'sem_radio';
        const linha = r => r.closest('[role=button],label') || (() => {
            let n = r; for (let i=0;i<8 && n;i++){ if (norm(n.innerText).length>8) return n; n=n.parentElement; } return r; })();
        const marcado = r => r.getAttribute('aria-checked')==='true' || r.getAttribute('data-checked')==='true' || r.checked===true;
        const ehSms = t => /(^|[^a-z])sms([^a-z]|$)/.test(t) || t.indexOf('mensagem de texto')!==-1
                        || t.indexOf('text message')!==-1 || t.indexOf('mensaje de texto')!==-1;
        const ehOutro = t => t.indexOf('whatsapp')!==-1 || t.indexOf('ligação')!==-1 || t.indexOf('ligacao')!==-1
                          || t.indexOf('phone call')!==-1 || t.indexOf('llamada')!==-1;
        let alvo = radios.find(r => { const t = norm(linha(r).innerText); return ehSms(t) && t.indexOf('whatsapp')===-1; });
        if (!alvo && radios.length === 3 && norm(linha(radios[2]).innerText).indexOf('whatsapp')!==-1
                && !ehOutro(norm(linha(radios[1]).innerText)))
            alvo = radios[1];
        if (!alvo) return 'sem_sms';
        if (marcado(alvo)) return 'ok';
        try{ alvo.scrollIntoView({block:'center'}); }catch(e){}
        try{ alvo.click(); }catch(e){}
        if (!marcado(alvo)) { try{ linha(alvo).click(); }catch(e){} }
        return marcado(alvo) ? 'ok' : 'clicado';
    })()"""
    fim = time.time() + timeout
    ultimo = ''
    while time.time() < fim:
        try:
            r = driver.evaluate_page(js)
        except Exception:
            r = ''
        ultimo = r
        if r in ('ok', 'clicado'):
            logger.info("[ProMax] radio 'SMS' marcado -> %s", r)
            return True
        time.sleep(0.15)
    logger.warning("[ProMax] não marquei o radio 'SMS' (último: %s)", ultimo)
    return False


# ---------------------------------------------------------------------- #
# Seleção de opção em DROPDOWN/lista aberta (ex.: tipo de documento)
# ---------------------------------------------------------------------- #
def _selecionar_opcao_lista(driver, textos, timeout=8):
    """Clica numa opção de uma lista/dropdown ABERTO pelo título.

    As opções costumam ter título + selo ('Recomendado') + descrição (o mesmo
    texto repetido), então clicar pelo texto cru erra o alvo. Aqui localizamos a
    LINHA clicável (role=option/li) cujo TÍTULO casa e clicamos nela."""
    if isinstance(textos, str):
        textos = [textos]
    alvos = [t.strip().lower() for t in textos]
    js = r"""(alvos) => {
        const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
        const primeira = e => norm((e.innerText||'').split('\n')[0]);
        // `includes` além de `startsWith`: os RÓTULOS dos tipos de documento são nomes
        // próprios em português que a Meta grafa DIFERENTE por idioma (ex.: pt-BR
        // "Cadastro Nacional DE Pessoa JURÍDICA (CNPJ)" × en "...DA Pessoa JURIDICA
        // (CNPJ)") e ainda vêm com o selo "Recommended" colado. Matching por token
        // invariante ("(cnpj)") cobre todos os idiomas. Único chamador = tipo de doc,
        // então `includes` não causa falso-positivo. (2026-10-07)
        const casa = (txt) => alvos.some(a => txt===a || txt.startsWith(a) || txt.includes(a));
        // 1) prioriza elementos com role=option
        for (const e of document.querySelectorAll('[role=option]')){
            if (casa(primeira(e)) || casa(norm(e.innerText))){
                try{ e.scrollIntoView({block:'center'}); }catch(x){}
                try{ e.click(); return true; }catch(x){}
            }
        }
        // 2) fallback: elemento curto cujo título casa → sobe p/ container clicável
        for (const e of document.querySelectorAll('li,div,span,label')){
            if ((e.innerText||'').length < 160 && casa(primeira(e))){
                const c = e.closest('[role=option]') || e.closest('li') || e;
                try{ c.scrollIntoView({block:'center'}); }catch(x){}
                try{ c.click(); return true; }catch(x){}
            }
        }
        return false;
    }"""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            if driver.evaluate_page(js, alvos):
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------------- #
# Captcha
# ---------------------------------------------------------------------- #
def _aguardar_widget_recaptcha(driver, timeout=25):
    """Espera o widget do reCAPTCHA carregar 100% (iframe + textarea de resposta
    ou sitekey presentes) ANTES de pedir a solução/injetar — senão a injeção cai
    num widget ainda não montado e 'não confirma'."""
    js = r"""() => {
        const ta = document.querySelector('textarea[id^="g-recaptcha-response"], textarea[name="g-recaptcha-response"]');
        const ifr = document.querySelector('iframe[src*="recaptcha"], iframe[title*="reCAPTCHA"], iframe[title*="recaptcha"]');
        const sk = document.querySelector('[data-sitekey]');
        return !!(ta || ifr || sk);
    }"""
    fim = time.time() + timeout
    while time.time() < fim:
        ok = False
        try:
            ok = bool(driver.evaluate_page(js))
        except Exception:
            ok = False
        if not ok:
            page = getattr(driver, '_current_page', None)
            try:
                if page is not None:
                    for fr in list(page.frames):
                        try:
                            if fr.evaluate(js):
                                ok = True
                                break
                        except Exception:
                            continue
            except Exception:
                pass
        if ok:
            return True
        time.sleep(0.15)
    return False


def _resolver_captcha(driver, business_id, captcha_token, status):
    """Resolve o reCAPTCHA Enterprise via CapSolver e injeta o token. Só age se a
    tela do captcha estiver presente. Retorna True se resolveu (ou se não havia).

    """
    # Idioma-agnóstico PRIMEIRO: o IFRAME do reCAPTCHA visível confirma a tela em
    # qualquer idioma (EN/VI/RU/ID…). O texto é só reforço p/ PT/EN/ES.
    tem_captcha = _tem_recaptcha_visivel(driver) or _existe_texto(
        driver, ['ajude-nos a confirmar que é você', 'confirmar que é você',
                 'não sou um robô', 'nao sou um robo', "i'm not a robot",
                 # EN/ES
                 'help us confirm', 'confirm you are human',
                 'confirma que eres tú', 'confirma que eres tu'], timeout=3)
    if not tem_captcha:
        # widget ainda montando: dá uma 2ª chance pelo iframe
        if _aguardar_widget_recaptcha(driver, timeout=6) and _tem_recaptcha_visivel(driver):
            tem_captcha = True
    if not tem_captcha:
        return True  # sem captcha nesta tela
    # O captcha é resolvido no SERVIDOR (chave do admin) desde que o campo saiu da
    # GUI — nesse modo o token local é SEMPRE vazio e não deve abortar nada.
    try:
        from server.capsolver_client import token_necessario as _tok_nec
        _precisa_token = _tok_nec()
    except Exception:
        _precisa_token = True
    if not captcha_token and _precisa_token:
        status("❌ Sem token do CapSolver configurado — não dá para resolver o captcha.")
        return False
    # 1) ESPERA o widget do reCAPTCHA montar 100% antes de resolver/injetar.
    status("🤖 Captcha detectado — aguardando o widget carregar 100%...")
    _aguardar_widget_recaptcha(driver, timeout=25)
    try:
        _esperar_estatico(driver, timeout=10)
    except Exception:
        time.sleep(1.5)
    # 2) Lê o sitekey (já com o widget montado) e resolve no CapSolver. Tenta
    #    ENTERPRISE (padrão do FB) e, se falhar, o reCAPTCHA v2 NÃO-enterprise —
    #    alguns captchas do FB no fluxo caem no v2 normal e o enterprise devolve
    #    erro. Antes só tentava enterprise → "não resolvia na maioria das vezes".
    sitekey = _ler_sitekey(driver)
    url = f"{BASE}/security_center?business_id={business_id}"
    status("🤖 Resolvendo via CapSolver...")
    res = resolver_recaptcha(captcha_token, url, website_key=sitekey,
                             enterprise=True, timeout=180)
    if not res.get('sucesso'):
        status("🤖 Enterprise falhou — tentando reCAPTCHA v2 (não-enterprise)...")
        res = resolver_recaptcha(captcha_token, url, website_key=sitekey,
                                 enterprise=False, timeout=180)
    if not res.get('sucesso'):
        status(f"❌ CapSolver falhou: {res.get('mensagem', '')}")
        return False
    # 3) Injeta o token com RETENTATIVAS (o widget pode terminar de montar agora).
    #    Após injetar, CLICA no 'Avançar' e VERIFICA se saiu do captcha; se não,
    #    re-injeta (o botão só habilita quando o token entra no widget certo).
    token = res.get('token', '')
    injetou = False
    for _ti in range(8):
        if _injetar_recaptcha(driver, token):
            injetou = True
            # dá um empurrão no Avançar e checa se a tela mudou
            _avancar(driver, timeout=4)
            try:
                _esperar_estatico(driver, timeout=4)
            except Exception:
                pass
            if _detectar_tela_central(driver) != 'captcha':
                break
        time.sleep(1.2)
    if injetou:
        status("✅ Captcha resolvido e injetado.")
    else:
        status("⚠️ Token obtido; injeção não confirmou — tentando avançar mesmo assim.")
    _delay_medio()
    return True


def _esperar_sair_do_captcha(driver, status=None, timeout=25):
    """Após resolver o captcha + Avançar, AGUARDA a tela do captcha DESAPARECER
    antes do loop re-detectar. Sem isso o loop pegava o MESMO captcha (ainda em
    transição, já resolvido) e re-resolvia à toa (gasta tempo/CapSolver). Sai
    assim que a tela não for mais 'captcha' (ex.: 'Selecione sua empresa') ou no
    timeout. Retorna True se realmente saiu do captcha."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            _esperar_estatico(driver, timeout=4)
        except Exception:
            pass
        if _detectar_tela_central(driver) != 'captcha':
            if status:
                status("➡️ Captcha resolvido — próxima tela carregou.")
            return True
        time.sleep(1.0)
    return False


def _clicar_final_no_popup(driver, textos):
    """Se há um POPUP (role=dialog) aberto, clica o botão de FINALIZAR/avançar
    (Concluir/OK/Finalizar/...) DENTRO dele, via JS dispatch (à prova de overlay).
    NÃO toca em botões FORA de diálogo (evita clicar em algo do card estático da
    Central). Retorna True se clicou — usado p/ garantir que o 'Concluir' do popup
    'Informações enviadas' SEMPRE seja clicado antes de declarar sucesso."""
    alvos = [t.strip().lower() for t in textos]
    try:
        return bool(driver.evaluate_page(r"""(alvos) => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
            const dlgs=[...document.querySelectorAll('[role="dialog"]')].filter(vis);
            const dlg=dlgs.length?dlgs[dlgs.length-1]:null;
            if(!dlg) return false;
            const btns=[...dlg.querySelectorAll('[role="button"],button,a[role="button"],input[type="submit"]')].filter(vis);
            for(const b of btns){
                const t=((b.innerText||b.value||'')+'').trim().toLowerCase();
                if(alvos.includes(t)){
                    try{ b.click(); }catch(_){}
                    const r=b.getBoundingClientRect();
                    const o={bubbles:true,cancelable:true,view:window,clientX:r.left+r.width/2,clientY:r.top+r.height/2};
                    for(const ev of ['mousedown','mouseup','click']){ try{ b.dispatchEvent(new MouseEvent(ev,o)); }catch(_){} }
                    return true;
                }
            }
            return false;
        }""", alvos))
    except Exception:
        return False


def _marcar_e_enviar_requisitos(driver, status):
    """Trata o modal 'Resolver problemas' que às vezes surge NO FINAL do fluxo (logo
    após confirmar o código SMS que manda p/ análise): "Você precisa corrigir... seu
    envio poderá ser rejeitado / Não detectamos a razão social da sua empresa X nos seus
    documentos" + checkbox "Eu confirmo que meu envio atende aos requisitos" + botão
    "Enviar". SEM tratar, uma BM que só faltava ESTE clique virava erro/falha. Aqui:
    detecta o modal → MARCA o checkbox (habilita o 'Enviar', que fica azul) → clica
    'Enviar' → segue p/ 'Em análise'. Retorna True se o modal foi detectado (o chamador
    deve `continue` p/ re-checar). Pedido do usuário 2026-07-13."""
    try:
        eh = driver.evaluate_page(r"""() => {
            try {
              const _ds = [...document.querySelectorAll('[role="dialog"]')].filter(d => {
                  const r = d.getBoundingClientRect(); return r.width > 120 && r.height > 80; });
              const dlg = _ds.length ? _ds[_ds.length - 1] : null;   // pop-up do TOPO
              if (!dlg) return false;
              const t = ((dlg && dlg.innerText) || '').toLowerCase();
              return (
                t.indexOf('atende aos requisitos') !== -1 ||
                t.indexOf('envio poderá ser rejeitado') !== -1 ||
                t.indexOf('envio podera ser rejeitado') !== -1 ||
                (t.indexOf('não detectamos') !== -1 && t.indexOf('razão social') !== -1) ||
                (t.indexOf('nao detectamos') !== -1 && t.indexOf('razao social') !== -1) ||
                t.indexOf('resolver problemas') !== -1 ||
                // EN
                t.indexOf('meets the requirements') !== -1 ||
                t.indexOf('my submission meets') !== -1 ||
                t.indexOf('submission may be rejected') !== -1 ||
                t.indexOf('may be rejected') !== -1 ||
                (t.indexOf("we didn't detect") !== -1 && t.indexOf('business name') !== -1) ||
                (t.indexOf('we did not detect') !== -1 && t.indexOf('business name') !== -1) ||
                t.indexOf('resolve issues') !== -1 || t.indexOf('fix issues') !== -1 ||
                // ES
                t.indexOf('cumple con los requisitos') !== -1 ||
                t.indexOf('tu envío podría ser rechazado') !== -1
              );
            } catch(e){ return false; }
        }""")
    except Exception:
        eh = False
    if not eh:
        return False
    status("⚠️ Pop-up 'Resolver problemas' — marcando 'confirmo que meu envio atende aos "
           "requisitos' e enviando p/ análise...")
    # Pop-up do TOPO (pode haver outros abaixo) + checkbox dele. (2026-10-13) Antes: 1º
    # diálogo da página e o checkbox recebia DOIS cliques (.click() + dispatch 'click')
    # → marcava e DESMARCAVA na hora → 'Enviar/Submit' seguia desabilitado (travava).
    _JS_CB = r"""(acao) => {
        const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
            const s=getComputedStyle(e); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
        const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis)
            .filter(d => d.querySelector('input[type=checkbox],[role="checkbox"]'));
        const dlg = dlgs.length ? dlgs[dlgs.length - 1] : null;
        if (!dlg) return null;
        const cb = [...dlg.querySelectorAll('input[type=checkbox],[role="checkbox"]')].filter(vis)[0]
                || dlg.querySelector('input[type=checkbox],[role="checkbox"]');
        if (!cb) return null;
        const marcado = cb.getAttribute('aria-checked') === 'true' || cb.checked === true;
        if (acao === 'js' && !marcado) { try { cb.click(); } catch (e) {} }   // 1 clique só
        // alvo do clique real: o próprio checkbox (ou a linha/label dele, se oculto)
        let alvo = vis(cb) ? cb : (cb.closest('label,[role="button"]') || cb.parentElement);
        const r = alvo.getBoundingClientRect();
        return {marcado: cb.getAttribute('aria-checked') === 'true' || cb.checked === true,
                x: r.left + r.width / 2, y: r.top + r.height / 2};
    }"""
    _JS_ENVIAR = r"""(clicar) => {
        const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
            const s=getComputedStyle(e); return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
        const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
        const dlg = dlgs.length ? dlgs[dlgs.length - 1] : document;
        const NEG = ['voltar','back','cancelar','cancel','atrás','atras','fechar','close'];
        const ENV = ['enviar','submit','enviar para análise','enviar para analise','submit for review',
                     'send','enviar solicitud','gửi','отправить','kirim','soumettre','senden','invia'];
        const bs = [...dlg.querySelectorAll('div[role="button"],button,[role="button"]')]
            .filter(b => vis(b) && b.getAttribute('aria-hidden') !== 'true' && !b.closest('[aria-hidden="true"]'));
        let alvo = null;
        for (const b of bs) {
            const t = ((b.innerText || b.getAttribute('aria-label') || '') + '').trim().toLowerCase();
            if (!t || t.length > 28 || NEG.some(n => t === n)) continue;
            if (ENV.some(k => t === k || t.indexOf(k) !== -1)) { alvo = b; break; }
        }
        if (!alvo) return null;
        const des = alvo.getAttribute('aria-disabled') === 'true' || alvo.disabled === true;
        const r = alvo.getBoundingClientRect();
        return {des: des, x: r.left + r.width / 2, y: r.top + r.height / 2};
    }"""
    # 1) MARCA o checkbox: 1 clique REAL (mouse) e CONFERE; se não marcou, 1 clique JS.
    try:
        info = driver.evaluate_page(_JS_CB, 'ler')
    except Exception:
        info = None
    if isinstance(info, dict) and not info.get('marcado'):
        try:
            driver.mouse.move(float(info['x']), float(info['y']), steps=random.randint(5, 10))
            time.sleep(random.uniform(0.08, 0.2))
            driver.mouse.click(float(info['x']), float(info['y']))
        except Exception:
            pass
        time.sleep(0.6)
        try:
            info = driver.evaluate_page(_JS_CB, 'ler')
        except Exception:
            info = None
        if isinstance(info, dict) and not info.get('marcado'):
            try:
                info = driver.evaluate_page(_JS_CB, 'js')
            except Exception:
                info = None
    if isinstance(info, dict) and info.get('marcado'):
        status("☑️ 'Confirmo que meu envio atende aos requisitos' marcado.")
    # 2) ESPERA o Enviar/Submit HABILITAR e clica UMA vez (mouse real).
    env = None
    fim = time.time() + 6
    while time.time() < fim:
        try:
            env = driver.evaluate_page(_JS_ENVIAR, False)
        except Exception:
            env = None
        if isinstance(env, dict) and not env.get('des'):
            break
        time.sleep(0.4)
    if not (isinstance(env, dict) and not env.get('des')):
        logger.warning("[ProMax] 'Resolver problemas': Enviar/Submit não habilitou (checkbox: %s).",
                       (info or {}).get('marcado') if isinstance(info, dict) else None)
        return True   # é o pop-up; o chamador relê e tenta de novo na próxima volta
    try:
        txt_antes = driver.evaluate_page(
            r"""() => (((document.body && document.body.innerText) || '')+'').toLowerCase()""") or ''
    except Exception:
        txt_antes = ''
    try:
        driver.mouse.move(float(env['x']), float(env['y']), steps=random.randint(5, 10))
        time.sleep(random.uniform(0.08, 0.2))
        driver.mouse.click(float(env['x']), float(env['y']))
    except Exception:
        _click_texto(driver, ['Enviar', 'Submit', 'Submit for review', 'Send'], timeout=3)
    status("📨 'Resolver problemas' → Enviar/Submit clicado — aguardando a Meta...")
    _aguardar_popup_mudar(driver, txt_antes, timeout=12)   # anti-clique-duplo
    return True


def _aguardar_popup_mudar(driver, txt_antes, timeout=10):
    """Depois de clicar um botão de avanço/finalização, ESPERA a tela MUDAR de verdade
    (o innerText deixar de ser o de antes) ANTES de liberar o PRÓXIMO clique. Impede o
    re-clique no MESMO botão enquanto a Meta ainda processa — que era o que DUPLICAVA o
    envio ("problema ao salvar"/formulário empilhado) ao mandar p/ análise. Poll ~0,6s.
    (fix duplicação 2026-09-01) ⚠️ Opera só neste driver/aba; sem estado compartilhado."""
    base = ((txt_antes or '').strip())
    fim = time.time() + max(3, int(timeout))
    while time.time() < fim:
        try:
            if not _navegador_vivo(driver):
                return True
            agora = driver.evaluate_page(
                r"""() => (((document.body && document.body.innerText) || '')+'').toLowerCase()""") or ''
        except Exception:
            agora = ''
        if agora.strip() and agora.strip() != base:
            return True
        time.sleep(0.6)
    return False


def _aguardar_em_analise_final(driver, business_id, status, timeout=180):
    """Após confirmar o código SMS, conduz o popup até o estado ESTÁTICO de
    'Em análise' na Central de Segurança e SÓ retorna True quando esse estado
    estiver confirmado.

    CRÍTICO (pedido do usuário): fechar o navegador antes disso CANCELA o envio,
    obrigando a refazer tudo. O FB faz: spinner ('Processando seu envio' girando)
    → uma ou mais telas de popup com botão ('Concluir'/'Continuar'/'OK') →
    redireciona para o security_center com o card 'Verificação da empresa' exibindo
    'Agradecemos o envio das suas informações...' + 'Em análise'.

    Aqui: (1) esperamos o spinner; (2) vamos CLICANDO os botões que forem surgindo
    (nunca Cancelar/Voltar); (3) confirmamos o estado final estático antes de
    declarar sucesso."""
    # Texto que CONFIRMA o estado final estático (card de verificação enviado).
    conf_final = ['agradecemos o envio das suas informações',
                  'agradecemos o envio das suas informacoes', 'agradecemos o envio',
                  'status de verificação quando a análise',
                  'status de verificacao quando a analise',
                  'aproximadamente 2 dias', 'análise dos dados deverá levar',
                  'analise dos dados devera levar']
    em_analise = ['em análise', 'em analise', 'em revisão', 'em revisao',
                  'in review', 'under review', 'pending review']
    # Botões que AVANÇAM/FINALIZAM o popup até o card estático 'Em análise'.
    # Aqui o envio JÁ está COMMITADO (SMS confirmado), então 'Finalizar'/'Fechar'/
    # 'Close' são SEGUROS e fecham o popup de sucesso revelando a Central com
    # 'Em análise' (pedido do usuário). NUNCA clicar 'Cancelar'/'Voltar'.
    # Ordem: afirmativos primeiro; 'Fechar'/'Close' por último (preferência).
    botoes = ['Concluir', 'Concluído', 'Finalizar', 'Continuar', 'Continue',
              'OK', 'Ok', 'Done', 'Avançar', 'Próximo', 'Next', 'Entendi',
              'Got it', 'Fechar', 'Close']
    spinner_txt = ['processando seu envio', 'processing your submission',
                   'enviando suas informações', 'enviando suas informacoes',
                   'aguarde um momento', 'carregando']

    fim = time.time() + timeout
    while time.time() < fim:
        try:
            estado = driver.evaluate_page(r"""() => {
                return {txt: ((document.body && document.body.innerText) || '').toLowerCase(),
                        url: location.href.toLowerCase()};
            }""") or {}
        except Exception:
            estado = {}
        txt = estado.get('txt') or ''
        url = estado.get('url') or ''
        tem_conf = any(c in txt for c in conf_final)
        tem_em_analise = any(e in txt for e in em_analise)
        no_security = 'security_center' in url

        # 1) Spinner girando ('Processando seu envio') → NÃO fechar; espera 100%.
        if any(s in txt for s in spinner_txt):
            status("⏳ Processando envio — NÃO fechar; aguardando carregar 100%...")
            time.sleep(2.0)
            continue

        # 1-bis) Modal "Resolver problemas / Não detectamos a razão social" (surge
        #   às vezes NO FINAL, no lugar da tela esperada): marca a confirmação e
        #   clica 'Enviar' → envia p/ análise. Sem isso, a BM que só faltava este
        #   passo virava erro/falha (pedido do usuário 2026-07-13).
        if _marcar_e_enviar_requisitos(driver, status):
            _delay_medio()
            try:
                _esperar_estatico(driver, timeout=6)
            except Exception:
                pass
            continue

        # 2) Há um POPUP aberto com botão de finalizar (Concluir/OK/Finalizar/...)?
        #    CLICA SEMPRE — inclusive o 'Concluir' da tela "Informações enviadas /
        #    Agradecemos o envio". Só depois de o popup FECHAR é que declaramos
        #    sucesso (pedido do usuário). NUNCA retorna True com o popup aberto.
        if _clicar_final_no_popup(driver, botoes):
            status("✅ 'Informações enviadas' → clicando Concluir para finalizar...")
            # ESPERA a tela MUDAR de verdade antes de qualquer novo clique. Sem isto o
            # loop re-clicava no MESMO botão enquanto o backend processava e DUPLICAVA o
            # envio (o "clicando/duplicando demais ao enviar p/ análise" do usuário).
            _aguardar_popup_mudar(driver, txt, timeout=10)
            continue

        # 3) SEM popup pendente + confirmação/'Em análise' na Central → SUCESSO.
        if tem_conf or tem_em_analise:
            if not no_security:
                # confirmação já apareceu mas ainda não no security_center → navega
                # p/ o card estático (o envio JÁ foi feito; é seguro).
                try:
                    _ir_para(driver, f"{BASE}/security_center?business_id={business_id}",
                             esperar=['security_center'], timeout=30)
                except Exception:
                    pass
                time.sleep(1.5)
                continue
            try:
                _esperar_estatico(driver, timeout=6)
            except Exception:
                pass
            status("✅ Status 'Em análise' confirmado na Central de Segurança.")
            return True

        # 4) Fallback: botão de avançar FORA de diálogo (raro) — tenta seguir.
        if _click_texto(driver, botoes, timeout=2):
            status("➡️ Avançando popup pós-SMS...")
            _aguardar_popup_mudar(driver, txt, timeout=8)
            continue

        # 5) Nada reconhecível ainda → espera curta e re-checa.
        time.sleep(1.5)

    # Timeout: última tentativa de confirmar navegando à Central.
    try:
        _ir_para(driver, f"{BASE}/security_center?business_id={business_id}",
                 esperar=['security_center'], timeout=30)
    except Exception:
        pass
    return _existe_texto(driver, em_analise + ['agradecemos o envio'], timeout=15)


def _tem_recaptcha_visivel(driver) -> bool:
    """True se há um IFRAME do reCAPTCHA VISÍVEL na tela (o checkbox 'I'm not a
    robot' ou o desafio de imagem). 100% idioma-agnóstico — o widget é o mesmo em
    qualquer idioma. Usado p/ reconhecer a tela do captcha quando o texto não casa."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                const s=getComputedStyle(e);
                return r.width>40 && r.height>40 && s.visibility!=='hidden' && s.display!=='none'; };
            const ifr = document.querySelectorAll(
                'iframe[src*="recaptcha"], iframe[title*="reCAPTCHA"], iframe[title*="recaptcha"]');
            // nunca o badge do reCAPTCHA invisível (size=invisible) — não é a tela do captcha
            for (const f of ifr){ if (vis(f) && (f.getAttribute('src')||'').indexOf('size=invisible') === -1) return true; }
            return false;
        }""")) or _frame_recaptcha_visivel(driver)
    except Exception:
        return _frame_recaptcha_visivel(driver)


def _frame_recaptcha_visivel(driver) -> bool:
    """Fallback por FRAMES do Playwright (alcança iframe ANINHADO — captcha servido
    dentro de um iframe intermediário do FB, invisível ao querySelector do doc
    principal): frame anchor/bframe do reCAPTCHA, não-invisível, com caixa > 40px."""
    page = getattr(driver, '_current_page', None)
    if page is None:
        return False
    try:
        for fr in list(page.frames):
            u = (fr.url or '').lower()
            if 'recaptcha' not in u or 'size=invisible' in u:
                continue
            if '/anchor' not in u and '/bframe' not in u:
                continue
            try:
                bb = fr.frame_element().bounding_box()
            except Exception:
                bb = None
            if bb and bb.get('width', 0) > 40 and bb.get('height', 0) > 40:
                return True
    except Exception:
        pass
    return False


def _detectar_tela_central(driver):
    """Detecta a tela ATUAL da Central: TEXTO (`_detectar_tela_central_texto`) +
    correção ESTRUTURAL idioma-agnóstica para a tela do Tax ID/CNPJ. (2026-10-05)

      • Estrutura+dados dizem que É a tela do CNPJ → 'cnpj', mesmo que o texto tenha
        casado outra coisa (em inglês a descrição "you can upload documents to
        verify..." casava 'carregar_doc') ou nada (idioma não mapeado → None).
      • Texto disse 'cnpj' mas o diálogo NÃO tem campo de texto e tem radios → é uma
        tela de ESCOLHA que só menciona "tax id/registration number" (ex.: a de
        registro em inglês): 2 radios = 'registro', 3+ = 'tipo'. Antes o passo 'cnpj'
        ficava tentando preencher um campo que não existe até dar 'Preso no passo'."""
    passo = _detectar_tela_central_texto(driver)
    if passo in ('em_analise', 'sms_codigo', 'email_codigo', 'captcha'):
        return passo
    # reCAPTCHA VISÍVEL na tela e NENHUMA tela conhecida reconhecida pelo texto
    # (None) → é a tela do captcha, em QUALQUER idioma (cobre títulos novos). Só
    # quando o texto não achou nada, p/ não atropelar uma tela já identificada
    # (após resolver, o texto vira 'selecione_empresa' e este fallback não dispara).
    if passo in (None, 'coachmark') and _tem_recaptcha_visivel(driver):
        logger.info("[ProMax] tela reclassificada por IFRAME do reCAPTCHA → 'captcha'")
        return 'captcha'
    est = _estrutura_dialogo_form(driver)
    if not est:
        return passo
    # CONTATO pela estrutura: exatamente 2 inputs (Telefone, Site), sem radio/arquivo,
    # e um deles traz URL/domínio. Mesma descrição/título da tela do CNPJ → o texto
    # confunde (em inglês "upload documents" casa 'carregar_doc'; rótulo novo → None).
    if passo in (None, 'cnpj', 'carregar_doc') and _eh_tela_contato_estrutural(est):
        if passo is not None:
            logger.info("[ProMax] tela reclassificada pela ESTRUTURA: %r → 'contato'", passo)
        return 'contato'
    # 'carregar_doc' pelo texto SEM input de arquivo e com campos de texto = NÃO é a
    # tela de upload: é um passo de DADOS cuja descrição diz "you can upload documents
    # to verify this information" (frase comum a CNPJ/Endereço/Contato em inglês).
    # PROVADO AO VIVO (2026-10-05, conta #3266 en_GB): a tela de ENDEREÇO ("Add your
    # organisation address") virava 'carregar_doc' e o robô tentava anexar o
    # certificado nela. Upload de verdade SEMPRE tem <input type=file>.
    if passo == 'carregar_doc' and not est.get('nFile') and not est.get('nRadio') \
            and int(est.get('nText') or 0) >= 2:
        if _eh_tela_cnpj_estrutural(driver, est):
            novo = 'cnpj'
        elif int(est.get('nText') or 0) >= 4:
            novo = 'endereco'
        else:
            novo = None
        if novo:
            logger.info("[ProMax] tela reclassificada pela ESTRUTURA: 'carregar_doc' → %r "
                        "(%s campos de texto, sem input de arquivo)", novo, est.get('nText'))
            return novo
    if passo != 'cnpj' and _eh_tela_cnpj_estrutural(driver, est):
        if passo is not None:
            logger.info("[ProMax] tela reclassificada pela ESTRUTURA: %r → 'cnpj'", passo)
        return 'cnpj'
    if passo == 'cnpj' and not est.get('nText') and (est.get('nRadio') or 0) >= 2:
        novo = 'registro' if est.get('nRadio') == 2 else 'tipo'
        logger.info("[ProMax] tela 'cnpj' (texto) sem campo de texto e com %s radios → %r",
                    est.get('nRadio'), novo)
        return novo
    return passo


def _detectar_tela_central_texto(driver):
    """Detecta a tela ATUAL do fluxo da Central de Segurança pelo TEXTO VISÍVEL,
    escopado no DIÁLOGO em primeiro plano quando existe (evita casar texto do
    fundo — ex.: o botão 'Iniciar verificação' que continua atrás do modal).
    Retorna a chave do passo (string) ou None se não reconhecida.

    Ordem: do passo MAIS AVANÇADO para o menos — numa transição vence o estágio
    mais à frente. NUNCA agimos sem antes saber em QUE tela estamos."""
    try:
        info = driver.evaluate_page(r"""() => {
            const vis = d => { const r=d.getBoundingClientRect(); const s=getComputedStyle(d);
                return r.width>120 && r.height>120 && s.visibility!=='hidden' && s.display!=='none'; };
            const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
            // reCAPTCHA VISÍVEL dentro do diálogo (checkbox/desafio; nunca o badge
            // invisível) = tela do captcha em QUALQUER idioma. (2026-10-13)
            const temCap = d => [...d.querySelectorAll(
                    'iframe[src*="recaptcha"],iframe[title*="reCAPTCHA"],iframe[title*="recaptcha"]')]
                .some(f => { const r=f.getBoundingClientRect(); const s=getComputedStyle(f);
                    return r.width>40 && r.height>40 && s.visibility!=='hidden' && s.display!=='none'
                        && (f.getAttribute('src')||'').indexOf('size=invisible') === -1; });
            const info = dlgs.map(d => ({
                txt: (((d.innerText)||'')+'').toLowerCase(),
                // tem campo de formulário/escolha? então é o MODAL DO FLUXO (não coachmark)
                temForm: !!d.querySelector('input,select,textarea,[role="radio"],[role="combobox"],[role="textbox"],[role="listbox"]'),
                captcha: temCap(d),
            }));
            return { dialogs: info, body: (((document.body&&document.body.innerText)||'')+'').toLowerCase(),
                     lang: (document.documentElement.getAttribute('lang')||'').toLowerCase() };
        }""") or {}
    except Exception:
        info = {}
    dialogs = info.get('dialogs') or []
    body = info.get('body', '') or ''
    # Conta fora do pt: se o texto original não classificar, classifica a TRADUÇÃO pt-BR
    # (server/tradutor_tela) com as MESMAS listas — a Central em qualquer idioma.
    try:
        from server.tradutor_tela import precisa_traduzir as _prec_tr, traduzir_para_ptbr as _tr_pt
        _traduz = _prec_tr(info.get('lang', ''))
    except Exception:
        _traduz, _tr_pt = False, None

    # Classifica UM texto (de um diálogo) na chave do passo, do mais avançado ao
    # inicial. CRÍTICO: o modal de INTRO ("Verificar <empresa> / Ações necessárias"
    # + botão "Começar") LISTA "Carregar documentos" como um dos 3 itens — então tem
    # que ser detectado ANTES de 'carregar_doc' (que casa "carregar documentos"),
    # senão o bot pula o "Começar" e tenta anexar certificado fora de hora.
    def classify(txt):
        def tem(*frags):
            return any(f in txt for f in frags)
        # Pop-up "Resolver problemas / Resolve issues" (checkbox "confirmo que meu envio
        # atende aos requisitos" + Enviar/Submit). PRIMEIRO: o texto dele diz "upload a
        # document with the correct information" e casava 'carregar_doc' → o bot tentava
        # anexar/Avançar e travava (print do dono 2026-10-13).
        if tem('atende aos requisitos', 'meets the requirements', 'my submission meets',
               'cumple con los requisitos', 'envio poderá ser rejeitado', 'envio podera ser rejeitado',
               'submission may be rejected', 'resolve issues', 'resolver problemas',
               'tu envío podría ser rechazado', 'tu envio podria ser rechazado'):
            return 'requisitos'
        # Marcadores ÚNICOS do modal de intro:
        if tem('demonstrar que sua empresa é real', 'demonstrar que sua empresa e real',
               'você tem uma conexão legítima', 'voce tem uma conexao legitima',
               'uma conexão legítima com ela', 'uma conexao legitima com ela',
               'para a verificação, você precisará', 'para a verificacao, voce precisara',
               'ações necessárias', 'acoes necessarias',
               # EN
               'show that your business is real', 'that your business is real',
               'you have a legitimate connection', 'a legitimate connection to it',
               "to verify, you'll need", 'to verify, you will need',
               'required actions', 'action required', 'actions required',
               # ES
               'demostrar que tu empresa es real', 'acciones necesarias'):
            return 'acoes_necessarias'
        if tem('agradecemos o envio', 'analisar os detalhes da sua empresa',
               'processando seu envio', 'informações enviadas', 'informacoes enviadas',
               'em análise', 'em analise',
               # EN
               'thanks for submitting', 'thank you for submitting', 'thanks for your submission',
               "we're reviewing", 'we are reviewing', 'reviewing the details of your business',
               'information submitted', 'in review', 'under review', 'being reviewed',
               'processing your submission',
               # variantes que a TRADUÇÃO automática gera (conta VI/RU/ID… → pt/en)
               'thanks for sending', 'thank you for sending', 'obrigado por enviar',
               'obrigada por enviar', 'agradecemos por enviar', 'we are checking your',
               "we're checking your", 'estamos analisando', 'estamos revisando',
               # ES
               'gracias por el envío', 'gracias por el envio', 'en revisión', 'en revision',
               'estamos revisando'):
            return 'em_analise'
        # Tela do Tax ID/CNPJ pelo TÍTULO/rótulo exclusivo — ANTES de 'carregar_doc':
        # em inglês a descrição dela diz "you can upload documents to verify this
        # information" e casava 'upload documents' (→ tentava anexar certificado na
        # tela do CNPJ). A detecção estrutural cobre os demais idiomas. (2026-10-05)
        # ⚠️ NUNCA usar o TÍTULO ("Adicionar dados da empresa"/"Add business details"):
        # ele é o MESMO na tela de CONTATO (telefone/site) — a v1.85 usou e a tela de
        # contato virou 'cnpj' (CNPJ digitado no campo Telefone). Só o RÓTULO do campo.
        if tem('identificação fiscal da empresa', 'identificacao fiscal da empresa',
               'business tax id/registration number'):
            return 'cnpj'
        # Tela "Verifique com um documento e uma verificação de conexão" / "Não foi
        # possível encontrar sua empresa. Carregue documentos e confirme sua conexão"
        # (Meta não achou a empresa nos registros; oferece Email ou Verificação de
        # domínio). Regra do usuário: escolher DOMÍNIO e Avançar → vai p/ análise.
        # ⚠️ ANTES de 'carregar_doc'/'metodo'/'sms_codigo' (o texto casaria neles). (2026-07-12)
        if tem('não foi possível encontrar sua empresa', 'nao foi possivel encontrar sua empresa',
               'confirme sua conexão com', 'confirme sua conexao com',
               'confirmar sua conexão com', 'confirmar sua conexao com',
               'verifique com um documento e uma verificação de conexão',
               'verifique com um documento e uma verificacao de conexao',
               # EN
               "we couldn't find your business", 'we could not find your business',
               'confirm your connection with', 'confirm your connection to',
               'verify with a document and a connection verification',
               'a document and a connection', 'document and connection check',
               # ES
               'no pudimos encontrar tu empresa', 'confirma tu conexión con',
               'confirma tu conexion con'):
            return 'conexao_dominio'
        # 📧 Tela "Confirmar endereço de email" (Método Pro Max E-mail): digitar o e-mail
        # comercial (@dominio-do-site) p/ receber o código. (validado nos prints 2026-08-15)
        if tem('confirmar endereço de email', 'confirmar endereco de email',
               'seu email deve estar associado', 'email comercial',
               'confirm your email address', 'confirm email address'):
            return 'email_endereco'
        # 📧 Tela de DIGITAR o código do EMAIL — MESMO título do SMS ("Insira o código de
        # confirmação"), mas o subtítulo diz "enviamos para <...@...>" (tem @), não
        # "enviado para o número". PRECISA vir ANTES de 'sms_codigo' p/ não confundir.
        if (tem('insira o código que enviamos para', 'insira o codigo que enviamos para',
                'enter the code we sent to') and '@' in txt):
            return 'email_codigo'
        # sms_codigo: APENAS a tela de DIGITAR o código. NÃO usar o genérico "código de
        # confirmação" — ele aparece como TEXTO DE AJUDA na tela de Contato ("você
        # precisa poder receber um código de confirmação nesse número"), o que fazia o
        # bot pular para "Aguardando SMS" sem ter enviado o SMS. Exige 'insira/digite'
        # ou 'enviado'.
        if tem('insira o código de confirmação', 'insira o codigo de confirmacao',
               'digite o código de confirmação', 'digite o codigo de confirmacao',
               'insira o código', 'digite o código',
               'código enviado para o número', 'codigo enviado para o numero',
               'enter the confirmation code', 'enter the code we sent'):
            return 'sms_codigo'
        if tem('confirme o número do telefone', 'confirme o numero do telefone',
               'enviar sms', 'receber um sms',
               # EN
               'confirm your phone number', 'confirm the phone number',
               'send sms', 'send an sms', 'receive an sms', 'get a text message',
               'receive a text message',
               # ES
               'confirma tu número de teléfono', 'confirma tu numero de telefono',
               'enviar sms'):
            return 'sms_enviar'
        if tem('verifique com o domínio da empresa', 'verifique com o dominio da empresa',
               'domínio verificado', 'dominio verificado',
               # EN — inclui o título "Verify through business domain" e o texto
               # "The domain below has been verified..." / label "Verified domain"
               # (prints do dono em en_GB, 2026-10-07). Antes só tinha "verify WITH".
               'verify with your business domain', 'verify with the business domain',
               'verify through business domain', 'verify through your business domain',
               'domain verified', 'your domain is verified',
               'has been verified and can be used', 'verified domain',
               # ES
               'verifica con el dominio de la empresa', 'verifica a través del dominio'):
            return 'dominio_confirmar'
        if tem('ajude-nos a confirmar que é você', 'confirmar que é você',
               'confirmar que e voce', 'não sou um robô', 'nao sou um robo',
               "i'm not a robot",
               # EN — o TÍTULO "Help us confirm it's you" é o único texto do captcha
               # que fica NA PÁGINA (o "I'm not a robot" vive dentro do IFRAME do
               # reCAPTCHA, fora do body.innerText). Sem isto, em inglês a tela NÃO
               # virava 'captcha' e o _dispensar_coachmark FECHAVA o pop-up. Uso
               # 'help us confirm it' p/ cobrir apóstrofo reto e curvo (it's / it’s).
               'help us confirm it', 'help us confirm that it', 'help us confirm',
               'confirm you are human', 'confirm that you are human',
               # ES
               'ayúdanos a confirmar que eres tú', 'ayudanos a confirmar que eres tu',
               'confirma que eres tú', 'confirma que eres tu',
               'confirmar que eres tú', 'confirmar que eres tu'):
            return 'captcha'
        # Se a tela OFERECE "Verificação de domínio" como opção de MÉTODO, é a tela de
        # ESCOLHER MÉTODO (selecionar domínio) — NÃO a de upload de documento, mesmo que
        # cada opção mencione "carregue documentos". Prioriza método/domínio p/ não ficar
        # preso em 'carregar_doc' (causa nº1 de travamento). Só é upload DE VERDADE quando
        # pede "selecione um tipo de documento". (2026-07-12)
        if tem('verificação de domínio', 'verificacao de dominio', 'domain verification',
               'verificación de dominio', 'verificacion de dominio') \
                and not tem('selecione um tipo de documento', 'selecione o tipo de documento',
                            'select a document type', 'selecciona un tipo de documento'):
            return 'metodo'
        if tem('seu documento inclui o número de telefone', 'inclui o número de telefone',
               'carregar documentos', 'selecione um tipo de documento',
               'carregar documentos para confirmar',
               # EN
               'your document includes the phone number', 'includes the phone number',
               'upload documents', 'upload a document', 'select a document type',
               'upload documents to confirm',
               # ES
               'sube documentos', 'selecciona un tipo de documento',
               'tu documento incluye el número de teléfono'):
            return 'carregar_doc'
        if tem('selecione sua empresa', 'selecione a sua empresa',
               'minha empresa não está na lista', 'minha empresa nao esta na lista',
               "my business isn't listed", 'encontramos os seguintes itens nos registros',
               'registros públicos', 'registros publicos'):
            return 'selecione_empresa'
        if tem('verifique com um documento', 'escolha um método', 'escolha um metodo',
               'verificação de domínio', 'verificacao de dominio', 'mensagem de texto',
               # EN
               'verify with a document', 'choose a method', 'choose a verification method',
               'domain verification', 'text message',
               # ES
               'verifica con un documento', 'elige un método', 'elige un metodo',
               'mensaje de texto'):
            return 'metodo'
        if tem('informações de contato', 'informacoes de contato',
               'receber um código de confirmação', 'receber um codigo de confirmacao',
               'você precisa poder receber',
               # EN
               'contact information', 'contact info', 'receive a confirmation code',
               'you need to be able to receive', 'be able to receive a',
               # ES
               'información de contacto', 'informacion de contacto',
               'recibir un código de confirmación'):
            return 'contato'
        if tem('adicione o endereço da organização', 'adicione o endereco da organizacao',
               'endereço da organização', 'endereco da organizacao',
               # EN
               "add the organization's address", 'organization address',
               "organization's address", 'add your organization address',
               # EN-GB (grafia 'organisation' — conta #3266 en_GB, 2026-10-05)
               "add the organisation's address", 'organisation address',
               "organisation's address", 'add your organisation address',
               # ES
               'dirección de la organización', 'direccion de la organizacion',
               'agrega la dirección de la organización'):
            return 'endereco'
        if tem('identificação fiscal', 'identificacao fiscal',
               'número de registro da empresa', 'numero de registro da empresa',
               # EN
               'tax id', 'tax identification', 'business registration number',
               'registration number',
               # ES
               'identificación fiscal', 'identificacion fiscal',
               'número de registro de la empresa'):
            return 'cnpj'
        if tem('sua empresa tem registro oficial', 'tem registro oficial',
               # EN
               'is your business officially registered', 'officially registered',
               'has official registration', 'is your business registered',
               # ES
               'tu empresa tiene registro oficial', 'registro oficial'):
            return 'registro'
        if tem('selecione o tipo da sua empresa', 'esta empresa é de que tipo',
               'esta empresa e de que tipo',
               # EN
               'select your business type', 'what type of business is this',
               'what type of business', 'select the type of business',
               # ES
               'selecciona el tipo de tu empresa', 'qué tipo de empresa es'):
            return 'tipo'
        if tem('selecionar um país', 'selecionar um pais', 'localização da organização',
               'localizacao da organizacao',
               # EN
               'select a country', 'select a country/region', 'organization location',
               "organization's location", 'location of the organization',
               # EN-GB ('organisation')
               'organisation location', "organisation's location", 'location of the organisation',
               # ES
               'seleccionar un país', 'seleccionar un pais', 'ubicación de la organización'):
            return 'pais'
        if tem('iniciar verificação', 'iniciar verificacao',
               # EN
               'start verification', 'begin verification',
               # ES
               'iniciar verificación', 'iniciar verificacion'):
            return 'iniciar'
        return None

    # 1) Entre TODOS os diálogos abertos, o que classifica num passo conhecido vence
    #    (do topo/mais recente para o fundo). Isso ignora coachmarks/tooltips
    #    promocionais que ficam SOBRE o modal do fluxo (eles não classificam).
    for d in reversed(dialogs):
        # Captcha pela ESTRUTURA primeiro: o diálogo dele não tem campo de formulário
        # (só o iframe) e o texto varia por idioma → antes caía em 'coachmark' (VI/RU/
        # ID…) ou não casava em EN ("Help us confirm THAT it's you") e travava.
        if d.get('captcha'):
            return 'captcha'
        passo = classify(d.get('txt', '') or '')
        if not passo and _traduz and (d.get('txt') or '').strip():
            _trd = _tr_pt(d.get('txt') or '')
            if _trd:
                passo = classify(_trd)
                if passo:
                    logger.info("[ProMax] tela '%s' reconhecida pela TRADUÇÃO pt-BR (lang=%s)",
                                passo, info.get('lang', ''))
        if passo:
            return passo

    # 2) Há um diálogo COM FORMULÁRIO que não reconhecemos? É uma tela REAL do fluxo
    #    ainda desconhecida → None (o chamador captura para hardening). NÃO cair na
    #    detecção pela landing (o body também contém 'Iniciar verificação' ao fundo).
    tem_form = any(d.get('temForm') for d in dialogs)
    if tem_form:
        return None

    # 3) Diálogo(s) SEM formulário e que não classificam = coachmark/promo cobrindo a
    #    tela → manda o chamador DISPENSAR antes de seguir.
    if dialogs:
        return 'coachmark'

    # 4) Sem diálogo nenhum: landing do security_center ('Iniciar/Continuar') ou o
    #    card final 'Em análise'. Fora do pt, soma a tradução do [role=main].
    if _traduz:
        try:
            from server.tradutor_tela import traducao_primeiro_plano as _tpp
            _tb = _tpp(driver)
            if _tb:
                body = body + '\n' + _tb
        except Exception:
            pass

    def temb(*frags):
        return any(f in body for f in frags)
    if temb('agradecemos o envio', 'em análise', 'em analise',
            'thanks for submitting', 'thank you for submitting', 'in review', 'under review',
            'gracias por el envío', 'en revisión', 'en revision'):
        return 'em_analise'
    if temb('iniciar verificação', 'iniciar verificacao', 'envio pendente',
            'continue de onde parou',
            'start verification', 'begin verification', 'pending submission',
            'continue where you left off', 'iniciar verificación', 'iniciar verificacion'):
        return 'iniciar'
    return None


def _clicar_e_aguardar_saida(driver, textos, passo_atual, timeout_render=20, status=None):
    """Clica UMA ÚNICA VEZ no botão e ESPERA de forma INTELIGENTE a tela renderizar
    100% e SAIR de `passo_atual` (ex.: 'iniciar' → 'acoes_necessarias'), SEM
    re-clicar.

    Motivo (pedido do usuário): disparar vários cliques enquanto o pop-up ainda
    carrega (skeleton) é o que TRAVA o Facebook e prende no loop. Aqui o clique é
    REAL e ÚNICO (natural; robusto SÓ se o natural não achar o botão) e a espera é
    precisa: faz POLL até detectar a PRÓXIMA tela CONHECIDA — 'coachmark'/None
    (skeleton/carregando) NÃO conta como avanço, então esperamos o modal abrir de
    verdade. Retorna True se avançou, False se ficou preso (aí o chamador troca de
    aba, que funciona)."""
    # 1) UM clique REAL. Natural primeiro; robusto só se o natural não clicou.
    clicou = _click_texto(driver, textos, timeout=8)
    if not clicou:
        clicou = _clicar_botao_robusto(driver, textos, timeout=8)
    if not clicou:
        return False
    # 2) Deixa o clique registrar e a página COMEÇAR a renderizar (settle).
    try:
        _esperar_estatico(driver, timeout=10)
    except Exception:
        pass
    # 3) POLL PACIENTE: espera a PRÓXIMA tela CONHECIDA aparecer (modal 100%).
    #    Enquanto for skeleton/coachmark/None → continua esperando; NÃO re-clica.
    fim = time.time() + max(6, int(timeout_render))
    while time.time() < fim:
        try:
            _p = _detectar_tela_central(driver)
        except Exception:
            _p = None
        if _p and _p not in (passo_atual, 'coachmark'):
            if status:
                try:
                    status(f"✅ Tela '{_p}' renderizou 100% — seguindo o fluxo.")
                except Exception:
                    pass
            return True
        time.sleep(1.0)
    return False


# Passos de FORMULÁRIO da Central (clicam Avançar e podem duplicar submit se re-clicados
# antes da Meta entregar a próxima tela). O 'sms_*'/'email_*'/'captcha'/'iniciar'/
# 'acoes_necessarias' NÃO entram: têm espera própria (poll de SMS/e-mail, _clicar_e_aguardar_saida).
_PASSOS_FORM_CENTRAL = {'pais', 'tipo', 'registro', 'cnpj', 'endereco', 'contato',
                        'selecione_empresa', 'conexao_dominio', 'dominio_confirmar',
                        'preencha_dados', 'metodo', 'carregar_doc'}
_ESPERA_TRANSICAO_CENTRAL = 10  # s — tempo máximo esperando a Meta ENTREGAR a próxima tela
# Teto anti-loop do assistente (entradas NOVAS na tela, por submissão). Legítimo: 1ª
# passagem + reaberturas por erro/aba clonada (skeleton do 'Começar' clona até 3x).
_MAX_ENTRADAS_PAIS = 3
_MAX_ENTRADAS_ACOES = 6


def _aguardar_transicao_central(driver, passo_ref, timeout=_ESPERA_TRANSICAO_CENTRAL):
    """Espera a Central SAIR de `passo_ref` (a Meta ENTREGAR a próxima tela) ANTES de
    qualquer nova ação — comportamento HUMANO: clica uma vez, aguarda a resposta do
    servidor, e só então segue. NUNCA re-clica em cima da mesma tela enquanto o backend
    processa (era o que duplicava submit, empilhava formulário e gerava "problema ao
    salvar"/"Ocorreu um erro"). Poll ~0,6s. Retorna True se transicionou (ou o navegador
    morreu); False no timeout (aí a ação anterior não pegou e o chamador re-tenta 1x).

    ⚠️ ISOLAMENTO: opera SÓ no `driver` desta aba/worker; usa apenas variáveis locais.
    Nenhum estado é compartilhado entre abas — o fluxo de uma empresa/WABA jamais toca o
    de outra."""
    fim = time.time() + max(4, int(timeout))
    while time.time() < fim:
        try:
            if not _navegador_vivo(driver):
                return True
            if _detectar_tela_central(driver) != passo_ref:
                return True
        except Exception:
            pass
        time.sleep(0.6)
    return False


# Marcadores FORTES de erro de PÁGINA INTEIRA (o modal "something went wrong"), em
# PT/EN/ES. Propositalmente SEM os fracos ("please try again"/"tente novamente") p/ não
# confundir com erro de CAMPO legítimo (ex.: telefone inválido), que tem handler próprio.
_ERRO_PAGINA_FORTE = (
    'something went wrong', 'technical problem with this feature',
    "we're working on getting it fixed", 'were working on getting it fixed',
    'há um problema técnico com esse recurso', 'ha um problema tecnico com esse recurso',
    'problema técnico com esse recurso', 'problema tecnico com esse recurso',
    'estamos trabalhando para corrigir', 'ocorreu um erro', 'algo deu errado',
    'se produjo un error', 'algo salió mal', 'algo salio mal',
    'problema técnico con esta función',
)


def _sg_erro_meta(driver) -> bool:
    """True se a tela mostra o ERRO GENÉRICO de PÁGINA da Meta ('Sorry, something went
    wrong' / 'há um problema técnico com esse recurso'), em QUALQUER idioma (PT/EN/ES).
    Usa só marcadores FORTES — erro de campo (telefone inválido etc.) NÃO conta aqui."""
    try:
        t = (driver.evaluate_page(
            "() => (document.body && document.body.innerText || '').toLowerCase()") or '')
    except Exception:
        return False
    return any(m in t for m in _ERRO_PAGINA_FORTE)


def _fechar_modal_erro(driver) -> bool:
    """Fecha o modal de erro ('something went wrong') pelo X/OK/Fechar — idioma-agnóstico,
    mirando o DIÁLOGO MAIS RECENTE (o que está por cima). Não toca em outros elementos."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            function vis(el){ if(!el) return false; var r=el.getBoundingClientRect();
                var s=getComputedStyle(el);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; }
            var dialogs = document.querySelectorAll('[role="dialog"]');
            var scope = dialogs.length ? dialogs[dialogs.length-1] : document;
            // 1) botão X por aria-label (igualdade, p/ não pegar "Close account" etc.)
            var fechar = ['close','fechar','cerrar','dismiss','descartar','schließen','fermer'];
            var cand = scope.querySelectorAll('[aria-label], [role="button"], button, a');
            for (var i=0;i<cand.length;i++){
                var el=cand[i]; if(!vis(el)) continue;
                var al=(el.getAttribute('aria-label')||'').trim().toLowerCase();
                for (var j=0;j<fechar.length;j++){ if(al===fechar[j]){ el.click(); return true; } }
            }
            // 2) botão com texto OK/Entendi/Got it (igualdade do innerText)
            var ok = ['ok','entendi','got it','entendido','fechar','close','aceptar'];
            var btns = scope.querySelectorAll('button, div[role="button"], span[role="button"], a[role="button"]');
            for (var k=0;k<btns.length;k++){
                var b=btns[k]; if(!vis(b)) continue;
                var t=(b.innerText||'').trim().toLowerCase();
                for (var m=0;m<ok.length;m++){ if(t===ok[m]){ b.click(); return true; } }
            }
            return false;
        }"""))
    except Exception:
        return False


def _recuperar_erro_central(driver, business_id, status, streak):
    """Recuperação GRADUADA do erro genérico da Meta na Central, SEM clicar no fluxo
    por baixo (que empilha telas e perpetua o erro — relato do dono em contas EN):
      1ª-2ª vez: fecha o modal de erro (X/OK) e espera — a maioria é transitória.
      3ª-4ª vez: F5/backoff (session_guard).
      5ª+ vez:   reabre a Central do ZERO (re-navega) — reseta as telas empilhadas.
    O fluxo (máquina de estados) re-detecta onde parou; os dados da empresa já foram
    salvos, então re-navegar é seguro."""
    try:
        _fechar_modal_erro(driver)
    except Exception:
        pass
    time.sleep(1.2)
    if not _sg_erro_meta(driver):
        return
    if streak <= 4:
        try:
            from server import session_guard as _sg
            _sg.recuperar_erro_generico(driver, cap=2, callback_status=status)
        except Exception:
            pass
        time.sleep(1.2)
        if not _sg_erro_meta(driver):
            return
    # persistiu → reabre a Central limpa
    try:
        status("⟳ Erro persistente — reabrindo a Central do zero (sem empilhar telas)...")
    except Exception:
        pass
    try:
        _ir_para(driver, f"{BASE}/security_center?business_id={business_id}",
                 esperar=['security_center'], timeout=40)
        time.sleep(1.5)
    except Exception:
        pass


def _eh_bloqueio_dead_end(driver) -> bool:
    """True quando a aba caiu num BLOQUEIO SEM SAÍDA do Facebook: a tela de
    checkpoint "confirme que é você para desbloquear / sua conta pode ter sido
    hackeada" (botão 'Bắt đầu'/'Começar') OU o popup seguinte "Nhận mã qua email /
    Receber código por e-mail". Ambos só destravam com um código enviado ao E-MAIL
    do perfil (Hotmail/Outlook), que o sistema NÃO acessa — então NÃO adianta
    clicar (só perde 1-2 min por navegação, clicando 'Começar' e voltando). O
    chamador ABORTA como Erro/Bloqueio e segue p/ o próximo perfil da fila.

    Detecta por TEXTO (multi-idioma PT/EN/VI) combinado com o caminho /checkpoint/,
    evitando falso-positivo em telas normais da Central (que ficam em
    /latest/settings/security_center, sem 'mở khóa'/'desbloquear'/'hacked')."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            try {
                const t = ((document.body && document.body.innerText) || '').toLowerCase();
                const u = (location.href || '').toLowerCase();
                const emCheckpoint = u.indexOf('/checkpoint/') !== -1;
                // CONTA TRAVADA / possível hack / "confirme p/ desbloquear"
                const travada = (
                    t.indexOf('mở khóa') !== -1 || t.indexOf('có thể đã bị hack') !== -1 ||
                    t.indexOf('đã khóa tài khoản') !== -1 || t.indexOf('đây là tài khoản của bạn') !== -1 ||
                    t.indexOf('may have been hacked') !== -1 || t.indexOf('locked your account') !== -1 ||
                    t.indexOf('to unlock') !== -1 || t.indexOf('this is your account') !== -1 ||
                    t.indexOf('para desbloquear') !== -1 || t.indexOf('bloqueamos sua conta') !== -1 ||
                    t.indexOf('pode ter sido hackeada') !== -1
                );
                // popup seguinte: "receber código por e-mail" (só destrava por e-mail)
                const codEmail = (
                    t.indexOf('nhận mã qua email') !== -1 || t.indexOf('nhan ma qua email') !== -1 ||
                    t.indexOf('receber código por e-mail') !== -1 || t.indexOf('receber codigo por e-mail') !== -1 ||
                    t.indexOf('receber o código por email') !== -1 || t.indexOf('get a code by email') !== -1 ||
                    t.indexOf('get code via email') !== -1
                );
                return (emCheckpoint && (travada || codEmail)) ||
                       (travada && (t.indexOf('mở khóa') !== -1 || t.indexOf('unlock') !== -1 ||
                                    t.indexOf('desbloquear') !== -1));
            } catch (e) { return false; }
        }"""))
    except Exception:
        return False


def _eh_rate_limit_sms(driver) -> bool:
    """True SÓ na tela de RATE-LIMIT de SMS da Meta: "Você tentou muitos códigos de
    verificação recentemente." O limite é POR IP — trocar o IP do 4G reseta p/ TODOS
    os perfis do mesmo IP.

    ⚠️ ESTRITO de propósito: usa apenas a frase ESPECÍFICA "muitos códigos de
    verificação" (PT) / "too many verification codes" (EN). NÃO usar frases genéricas
    ("aguarde e tente novamente mais tarde", "try again later") — elas aparecem em
    MUITAS telas da Meta (certificado/domínio/erros transitórios) e davam
    falso-positivo, jogando o fluxo de volta p/ gerar um novo número de SMS à toa."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            try {
                const t = ((document.body && document.body.innerText) || '').toLowerCase();
                return (
                    (t.indexOf('muitos códigos de verificação') !== -1) ||
                    (t.indexOf('muitos codigos de verificacao') !== -1) ||
                    (t.indexOf('too many verification codes') !== -1) ||
                    (t.indexOf('too many login codes') !== -1)
                );
            } catch (e) { return false; }
        }"""))
    except Exception:
        return False


def _eh_tela_dominio_confirmar(driver) -> bool:
    """True SÓ na tela 'Verifique com o domínio da empresa' — o modal ESTÁVEL de
    confirmação ('O domínio abaixo foi verificado... / Domínio verificado' + botão
    Avançar). É a MESMA regra do passo 'dominio_confirmar' do _detectar_tela_central,
    mas isolada p/ um FAST-PATH: essa tela é lenta p/ ser reconhecida no loop normal
    (o bot fica 60-120s parado). Como ela NÃO faz bounce (diferente da sequência
    Ações/país que quebrava com 'detecta primeiro'), dá p/ clicar Avançar na hora.
    Escopado no DIÁLOGO visível em primeiro plano p/ não casar texto de fundo."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            try {
                const has = (s, f) => ((s||'').toLowerCase()).indexOf(f) !== -1;
                // Títulos da tela em PT/EN/ES (idioma-agnóstico)
                const T1s = ['verifique com o domínio da empresa','verifique com o dominio da empresa',
                             'verify with your business domain','verify with the business domain',
                             'verify through business domain','verify through your business domain',
                             'verificar através do domínio','verificar atraves do dominio',
                             'verifica con el dominio de la empresa','verifica a través del dominio'];
                const T2s = ['domínio verificado','dominio verificado','domain verified',
                             'your domain is verified','has been verified and can be used',
                             'verified domain','dominio verificado y se puede usar'];
                const anyHas = (s, arr) => arr.some(f => has(s, f));
                const dlgs = [...document.querySelectorAll('[role="dialog"]')];
                for (const d of dlgs) {
                    const r = d.getBoundingClientRect();
                    const s = getComputedStyle(d);
                    // Threshold menor (80): pega o modal mais cedo, ainda em animação.
                    if (r.width < 80 || r.height < 80 || s.visibility === 'hidden' || s.display === 'none') continue;
                    // [FAST] O aria-label do modal ja' vem setado ANTES do innerText
                    // renderizar (leitura de atributo = instantanea, sem forcar reflow).
                    // Detecta a tela mais cedo -> clica Avancar antes; innerText fica de fallback.
                    const al = (d.getAttribute('aria-label')) || '';
                    if (anyHas(al, T1s)) return true;
                    const t = (d.innerText) || '';
                    if (anyHas(t, T1s) || anyHas(t, T2s)) return true;
                }
                // FALLBACK (2026-07-25): a Meta às vezes renderiza esse modal FORA de um
                // [role=dialog] limpo (ou o role só aparece após o skeleton) → o loop
                // normal caía em 'sem_titulo' e ficava lento. Se o TÍTULO EXATO da tela
                // ('Verifique com o domínio da empresa') está no corpo E há um botão
                // 'Avançar' visível, é ELA — clica na hora. Título é específico o
                // bastante p/ não casar outra tela (não uso o genérico 'domínio verificado' aqui).
                const b = (document.body && document.body.innerText) || '';
                if (anyHas(b, T1s)) {
                    const temAvancar = [...document.querySelectorAll('div[role=button],button,span,a')]
                        .some(e => /avan[çc]ar|continuar|next|continue/i.test((e.innerText || '')) && e.offsetParent !== null);
                    if (temAvancar) return true;
                }
                return false;
            } catch (e) { return false; }
        }"""))
    except Exception:
        return False


_ERRO_CONSULTA_TXT = ['erro ao realizar a consulta', 'error performing',
                      'error al realizar la consulta', 'error performing the query',
                      'não foi possível concluir a solicitação', 'nao foi possivel concluir',
                      'tente novamente mais tarde']


def _waba_caiu_na_consulta(driver, business_id, status, r):
    """1º 'Erro ao realizar a consulta': confere NA HORA se a WABA foi DESABILITADA
    (prints do dono 2026-10-13: "Conta desabilitada" em Contas do WhatsApp e a Central
    passou a dizer "Sua organização não precisa ser verificada"). Desabilitada → preenche
    `r` (possivel_waba_desabilitada → loop externo: recurso/2ª BM) e devolve True. Viva →
    volta à Central (o fluxo retoma por "Envio pendente → Continuar") e devolve False."""
    status("🔎 'Erro ao realizar a consulta' — conferindo se a WABA foi desabilitada...")
    try:
        caiu = _conta_whatsapp_desabilitada(driver, business_id)
    except Exception:
        caiu = False
    if caiu:
        r['possivel_waba_desabilitada'] = True
        r['mensagem'] = ("'Erro ao realizar a consulta' — WABA DESABILITADA pela Meta "
                         "(conta não cumpre as diretrizes).")
        status('🔴 ' + r['mensagem'])
        return True
    status("✅ WABA ativa — o erro é transitório; voltando à Central e reavançando...")
    try:
        _ir_para(driver, f"{BASE}/security_center?business_id={business_id}",
                 esperar=['security_center'], timeout=40)
    except Exception:
        pass
    return False


def _erro_consulta_persistente(driver, business_id, status, r, streak):
    """'Erro ao realizar a consulta' PERSISTENTE (em qualquer passo: contato OU
    carregar_doc). Dois motivos com tratamento oposto (provado pelo dono 2026-08-29):
      (a) WABA DESABILITADA no meio do fluxo → a consulta falha sempre → aborta p/ 2ª BM;
      (b) IP 4G compartilhado QUEIMADO/throttled por N abas → WABA viva → troca IP 1x
          (proxy próprio da aba, senão coordenador global) + número NOVO + reinício.
    Preenche `r` (o chamador devolve r)."""
    status("🔎 'Erro ao realizar a consulta' persistente — conferindo se a WABA caiu...")
    if _conta_whatsapp_desabilitada(driver, business_id):
        r['possivel_waba_desabilitada'] = True
        r['mensagem'] = ("'Erro ao realizar a consulta' persistente "
                         f"({streak}x) + WABA desabilitada.")
        status('🔴 ' + r['mensagem'])
        return r
    try:
        _girou_local = False
        try:
            from server.proxy_rotate import girar_ip_da_aba
            _girou_local = girar_ip_da_aba(driver, motivo='IP queimado na consulta', status=status)
        except Exception as _e_loc:
            logger.warning('[Central] giro local do proxy falhou: %s', _e_loc)
        if not _girou_local:
            from server.ip_rotation_coordinator import COORD as _IPCOORD
            _res_ip = _IPCOORD.request('erro ao realizar a consulta (IP 4G queimado)')
            if _res_ip in ('solicitada', 'em_andamento'):
                status('🌐 Consulta falhando com WABA viva (IP queimado) — trocando IP 4G (1x) e reiniciando com número novo...')
                _IPCOORD.checkpoint(alive_fn=lambda: _navegador_vivo(driver))
            else:
                status('🔁 IP já trocado há pouco por outra aba — só número novo e reinício (sem nova troca de IP).')
    except Exception as _e_ip:
        logger.warning('[Central] coordenação de troca de IP (consulta) falhou: %s', _e_ip)
    r['sms_falhou'] = True
    r['mensagem'] = ("'Erro ao realizar a consulta' persistente com WABA viva "
                     "(IP 4G queimado) — IP trocado 1x + número novo + reinício.")
    status('🔁 ' + r['mensagem'])
    return r


def _aguardar_saida_conexao(driver, timeout=12):
    """Depois do Avançar na tela de conexão: espera ela SAIR (ou um erro aparecer) antes
    de qualquer nova ação — anti-clique-duplo. Poll ~0,6s."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            if not _navegador_vivo(driver) or not _eh_tela_conexao_dominio(driver) \
                    or _sg_erro_meta(driver):
                return True
        except Exception:
            return True
        time.sleep(0.6)
    return False


def _eh_tela_conexao_dominio(driver) -> bool:
    """True na tela 'Verifique com um documento e uma verificação de conexão' /
    'Não foi possível encontrar sua empresa' — detectada pelo aria-label do modal
    (instantâneo, disponível antes do innerText renderizar). FAST-PATH: como essa
    tela também é lenta p/ ser reconhecida no loop normal (skeleton), detectamos
    cedo e escolhemos o método (domínio → SMS) + Avançar sem esperar os ~8s do
    _esperar_estatico por volta. innerText fica de fallback."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            try {
                const dlgs = [...document.querySelectorAll('[role="dialog"]')];
                for (const d of dlgs) {
                    const r = d.getBoundingClientRect();
                    const s = getComputedStyle(d);
                    if (r.width < 120 || r.height < 120 || s.visibility === 'hidden' || s.display === 'none') continue;
                    const al = ((d.getAttribute('aria-label')) || '').toLowerCase();
                    if (al.indexOf('documento e uma verificação de conexão') !== -1 ||
                        al.indexOf('documento e uma verificacao de conexao') !== -1 ||
                        al.indexOf('a document and a connection verification') !== -1 ||
                        al.indexOf('a document and a connection') !== -1 ||
                        al.indexOf('document and connection check') !== -1) {
                        return true;
                    }
                    const t = ((d.innerText) || '').toLowerCase();
                    if (t.indexOf('não foi possível encontrar sua empresa') !== -1 ||
                        t.indexOf('nao foi possivel encontrar sua empresa') !== -1 ||
                        t.indexOf('verifique com um documento e uma verificação de conexão') !== -1 ||
                        t.indexOf('verifique com um documento e uma verificacao de conexao') !== -1 ||
                        t.indexOf("we couldn't find your business") !== -1 ||
                        t.indexOf('we could not find your business') !== -1 ||
                        t.indexOf('a document and a connection verification') !== -1 ||
                        t.indexOf('no pudimos encontrar tu empresa') !== -1) {
                        return true;
                    }
                }
                return false;
            } catch (e) { return false; }
        }"""))
    except Exception:
        return False


# ---------------------------------------------------------------------- #
# ---------------------------------------------------------------------- #
# Submissão completa na Central de Segurança (uma tentativa)
# ---------------------------------------------------------------------- #
def _slug_local_email(empresa_dados, bm_email):
    """Local-part do e-mail comercial (📧 Pro Max E-mail). Usa o local do `bm_email`
    se houver; senão deriva da RAZÃO SOCIAL (1º+2º nome, sem acento, minúsculo) —
    igual ao que um humano digita (ex.: 'Naiara Regina Pinto' -> 'naiararegina')."""
    import re as _re
    import unicodedata as _ud
    le = ''
    if bm_email and '@' in bm_email:
        le = bm_email.split('@', 1)[0].strip()
    if not le:
        raz = (empresa_dados.get('razao_social') or empresa_dados.get('nome_fantasia') or '').strip()
        raz = _ud.normalize('NFKD', raz).encode('ascii', 'ignore').decode('ascii')
        toks = _re.findall(r'[A-Za-z0-9]+', raz.lower())
        le = ''.join(toks[:2]) if toks else 'contato'
    le = _re.sub(r'[^a-z0-9._-]', '', le.lower()) or 'contato'
    return le[:40]


def _digitar_email_comercial(driver, empresa_dados, bm_email):
    """Tela 'Confirmar endereço de email': a Meta FIXA o domínio (@...) a partir do
    site da empresa e mostra num campo. Lê esse domínio, monta <local>@<dominio>,
    digita no campo editável (que vem pré-preenchido só com '@dominio') e retorna o
    e-mail completo. É NELE que o código chega no GSMAILS. Retorna '' se não achou."""
    local = _slug_local_email(empresa_dados, bm_email)
    js = ("(() => {"
          "  const vis = el => { if(!el) return false; const r=el.getBoundingClientRect(); const s=getComputedStyle(el);"
          "      return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };"
          "  const dlgs = [...document.querySelectorAll('[role=\"dialog\"]')].filter(vis);"
          "  const root = dlgs.length ? dlgs[dlgs.length-1] : document;"
          "  const inputs = [...root.querySelectorAll('input')].filter(vis);"
          "  let dom = '';"
          "  for (const el of inputs) { const v=((el.value||'')+''); const m=v.match(/@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}/); if(m){dom=m[0];break;} }"
          "  if(!dom){ const t=((root.innerText||'')+''); const m=t.match(/@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}/); if(m) dom=m[0]; }"
          "  if(!dom) return '';"
          "  let edit = root.querySelector('input[autocomplete=\"email\"]') || root.querySelector('input[inputmode=\"email\"]');"
          "  if(!edit || edit.readOnly || edit.disabled) edit = inputs.find(el => !el.readOnly && !el.disabled);"
          "  if(!edit) return '';"
          "  const full = %s + dom;"
          "  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
          "  edit.focus(); setter.call(edit, full);"
          "  edit.dispatchEvent(new Event('input',{bubbles:true}));"
          "  edit.dispatchEvent(new Event('change',{bubbles:true}));"
          "  return full;"
          "})()") % ("'" + local + "'")
    try:
        email = driver.evaluate_page(js)
    except Exception as e:
        logger.warning("[ProMax/E-mail] falha ao montar/digitar o e-mail comercial: %s", e)
        email = ''
    return str(email or '').strip()


def _email_da_tela(driver):
    """Extrai o e-mail exibido na tela ('...enviamos para <email>') — fallback p/ ler
    o código no GSMAILS caso o endereço não tenha ficado guardado."""
    try:
        return str(driver.evaluate_page(
            "(() => { const t=((document.body&&document.body.innerText)||'')+'';"
            " const m=t.match(/[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}/); return m?m[0]:''; })()"
        ) or '').strip()
    except Exception:
        return ''


def _submeter_central(driver, business_id, empresa_dados, tipo_empresa,
                      caminho_cert, sms, ativacao_id, captcha_token,
                      telefone_nacional, status,
                      metodo_verificacao='dominio', bm_email='', site_url=''):
    """Roda o fluxo do Central de Segurança até 'Em análise' como MÁQUINA DE
    ESTADOS: a cada ciclo (1) trata interrupções (cookies/consent/checkpoint),
    (2) ESPERA a página carregar 100% e estabilizar, (3) DETECTA qual tela está
    de fato na frente e (4) executa SÓ a ação daquela tela. Nunca pula passo nem
    clica às cegas — segue o fluxo conforme a tela atual.

    Verificação SEMPRE por DOMÍNIO (a verificação por e-mail foi removida em
    2026-07-31: a Meta valida o domínio no servidor e devolveu 500 ao forçar o
    subdomínio — ver histórico).

    Retorna dict: {em_analise, sms_falhou, bm_bloqueada, sms_usado, mensagem}.
    'sms_usado' = True SÓ quando o código do SMS foi realmente digitado/confirmado
    (a verificação por DOMÍNIO pode ir direto p/ análise sem consumir o SMS)."""
    r = {'em_analise': False, 'sms_falhou': False, 'bm_bloqueada': False,
         'acao_bloqueada': False, 'sms_usado': False, 'mensagem': ''}
    cnpj_fmt = _cnpj_formatado(empresa_dados.get('cnpj', ''))
    # Dados DESTA empresa p/ a detecção ESTRUTURAL da tela do CNPJ (por driver/aba —
    # não cruza dado entre abas).
    try:
        driver._pm_cnpj = _so_digitos(empresa_dados.get('cnpj', ''))
        driver._pm_razao = (empresa_dados.get('razao_social')
                            or empresa_dados.get('nome_fantasia') or '')
    except Exception:
        pass
    # Domínio DESTA empresa (por aba): reconhece pelo DADO, em qualquer idioma, a tela
    # 'Domínio verificado' (diálogo sem campo) e impede o _dispensar_coachmark de fechá-la.
    _hosts_site = _hosts_do_site(site_url or empresa_dados.get('url_completa', ''))
    try:
        driver._pm_site_hosts = _hosts_site
    except Exception:
        pass
    # Token '(cnpj)' PRIMEIRO: invariante em qualquer idioma (o rótulo muda de grafia,
    # mas sempre tem "(CNPJ)"). Única opção do dropdown que contém "cnpj" → sem ambiguidade.
    # Mantém as grafias completas PT/EN como reforço.
    _opcao_cnpj = ['(cnpj)',
                   'Cadastro Nacional de Pessoa Jurídica (CNPJ)',
                   'Cadastro Nacional da Pessoa Juridica (CNPJ)',
                   'Cadastro Nacional de Pessoa Jurídica',
                   'Cadastro Nacional da Pessoa Juridica']

    _ir_para(driver, f"{BASE}/security_center?business_id={business_id}",
             esperar=['security_center'], timeout=40)
    _delay_medio()

    _dominio_feito = False     # já selecionamos o método 'Verificação de domínio'?
    _por_email = (str(metodo_verificacao or 'dominio').strip().lower() == 'email')
    _email_feito = False       # 📧 já confirmamos o código do e-mail comercial?
    _email_addr = ''           # 📧 e-mail comercial usado (p/ ler o código no GSMAILS)
    _email_env_tent = 0        # 📧 nº de vezes que reenviamos/tentamos o código do e-mail
    _email_since_id = 0        # 📧 baseline: só aceito código de e-mail com id MAIOR (frescor)
    _doc_enviado = False       # já fizemos upload do certificado?
    _cap_unknown = False       # já capturamos snapshot de tela não identificada?
    _dup_central = 0           # nº de vezes que duplicamos a aba p/ destravar o modal
    _contato_feito = False     # já preenchemos o telefone na tela de contato?
    _dominio_fast = 0          # nº de vezes que o FAST-PATH do domínio tentou Avançar
    _conexao_fast = 0          # nº de vezes que o FAST-PATH da tela documento+conexão agiu
    _intro_sobre_fluxo = 0     # nº de voltas com pop-up de intro empilhado sobre o fluxo
    _erro_consulta_streak = 0  # nº de "Erro ao realizar a consulta" seguidos (WABA desabilitada?)
    _erro_salvar_streak = 0    # nº de "problema ao salvar suas alterações" seguidos (número queimado?)
    _acao_bloqueada_streak = 0 # nº de "Limitamos a frequência…" (bloqueio de ação do PERFIL) seguidos
    _erro_generico_streak = 0  # nº de "something went wrong"/erro genérico da Meta seguidos (idioma-agnóstico)
    _erro_generico_total = 0   # TOTAL de erros genéricos nesta submissão (NÃO zera — teto anti-loop)
    _ultimo_agido = None       # último passo em que AGIMOS (p/ esperar a transição antes de re-clicar)
    _entradas_pais = 0         # nº de vezes que o assistente (re)começou pelo País (anti-loop)
    _entradas_acoes = 0        # nº de vezes que caímos em 'Ações necessárias' (anti-loop)
    ultimo = None
    repete = 0
    none_streak = 0
    # Cronômetro por TELA: mede quanto tempo o fluxo passou em cada passo. É o que
    # deixa visível no log qualquer tela que volte a "congelar". (2026-07-31)
    _passo_log = None
    _passo_t0 = time.time()
    fim = time.time() + 480
    while time.time() < fim:
        # 0-a) Navegador foi FECHADO (usuário na mão / queda)? Aborta NA HORA como
        #      Erro/Falha — senão o loop ficaria preso em 'Processando' à toa.
        if not _navegador_vivo(driver):
            r['mensagem'] = 'Navegador foi fechado durante a verificação.'
            r['navegador_fechado'] = True
            status('❌ ' + r['mensagem'])
            return r
        # 0-a2) ERRO GENÉRICO DA META ("Sorry, something went wrong" / "há um problema
        #       técnico com esse recurso") — PRIMEIRA coisa checada, TODA volta, em
        #       QUALQUER idioma (PT/EN/ES) e INCLUSIVE como modal POR CIMA do fluxo.
        #       ⚠️ Causa raiz do travamento em contas ≠ pt-BR (print do dono): o erro
        #       sobe como modal, o bot detecta a tela de BAIXO e continua clicando →
        #       EMPILHA telas e o erro vira loop infinito. Aqui recupera (fecha modal/
        #       F5/reabre a Central) SEM clicar no fluxo, com teto de streak p/ não
        #       girar à toa. 100% LOCAL a esta aba/worker (não cruza dado entre abas).
        if _sg_erro_meta(driver):
            _erro_generico_streak += 1
            _erro_generico_total += 1
            status(f"⚠️ Erro genérico da Meta na Central (seguidas {_erro_generico_streak}x, "
                   f"total {_erro_generico_total}x) — recuperando SEM clicar no fluxo...")
            _recuperar_erro_central(driver, business_id, status, _erro_generico_streak)
            # TERMINAL → DESCANSO (pedido do dono 2026-10-08): "something went wrong" que
            # PERSISTE não se resolve martelando (recomprar número e re-submeter contra um
            # recurso quebrado só prende o navegador e trava a fila). Fecha, descansa o
            # perfil e deixa o reprocesso-ocioso reabrir depois (MESMA empresa, número NOVO).
            # Teto por streak (seguidas) OU por total (mesmo intercalado c/ falsas recuperações).
            if _erro_generico_streak >= 3 or _erro_generico_total >= 4:
                r['mensagem'] = ('Erro genérico da Meta persistente na Central '
                                 '("something went wrong") — perfil em descanso p/ reenvio depois.')
                r['erro_generico_persistente'] = True
                r['descansar'] = True
                status('🛌 ' + r['mensagem'])
                return r
            _delay_medio()
            continue
        else:
            _erro_generico_streak = 0
        # 0-b) CONTA BLOQUEADA pelo FB (checkpoint "confirme p/ desbloquear" /
        #      "possível hack" / popup "Nhận mã qua email / receber código por
        #      e-mail"): dead-end que só destrava com código no E-MAIL do perfil
        #      (Hotmail/Outlook), que NÃO acessamos. ABORTA NA HORA como BLOQUEIO —
        #      antes o bot ficava clicando 'Começar' e voltando por 1-2 min a cada
        #      navegação até o timeout. Erro/Bloqueio → fecha e vai p/ o próximo.
        if _eh_bloqueio_dead_end(driver):
            r['bm_bloqueada'] = True
            r['conta_bloqueada'] = True
            r['mensagem'] = ('Conta bloqueada pelo Facebook (confirme para desbloquear / '
                             'código por e-mail) — só destrava por e-mail; bloqueio sem saída.')
            status('🔒 ' + r['mensagem'])
            return r
        # 0-c) PONTO SEGURO p/ a TROCA FORÇADA de IP (coordenador): se OUTRO navegador
        #      caiu na tela de rate-limit de SMS e pediu troca de IP, este worker PARA
        #      aqui (tela estática) até a troca terminar — evita quebrar o fluxo no meio.
        #      No-op quando não há troca pendente. (A DETECÇÃO do rate-limit NÃO fica
        #      aqui: rodava a cada iteração e dava falso-positivo em telas de
        #      certificado/domínio → só é checada no passo 'sms_enviar', abaixo.)
        try:
            from server.ip_rotation_coordinator import COORD as _IPCOORD
            _IPCOORD.checkpoint(alive_fn=lambda: _navegador_vivo(driver))
        except Exception:
            pass
        # 0-c2) ERRO "Ocorreu um problema ao salvar suas alterações. Aguarde alguns
        #       minutos" em QUALQUER tela do wizard. Em geral é TRANSITÓRIO — some ao
        #       re-clicar Avançar (os fast-paths/handlers já re-tentam; deixa passar).
        #       Mas se PERSISTIR (streak alto), o NÚMERO virtual queimou (é virtual,
        #       recebeu muitos códigos recentemente / outros usaram) OU a WABA caiu.
        #       Aí decide: WABA desabilitada → recorrer + 2ª BM; WABA aprovada/restrita
        #       → cancela o número + compra outro + regenera empresa/cert/site + reinicia
        #       a verificação (sms_falhou). NÃO troca IP — é do NÚMERO, não do IP (com
        #       N abas simultâneas só ESTA deu o erro). (2026-07-25)
        if _existe_texto(driver, _ERRO_SALVAR_TXT, timeout=1):
            _erro_salvar_streak += 1
            if _erro_salvar_streak >= 8:
                status("🔎 'Problema ao salvar' persistente — conferindo se a WABA caiu...")
                if _conta_whatsapp_desabilitada(driver, business_id):
                    r['possivel_waba_desabilitada'] = True
                    r['mensagem'] = "'Problema ao salvar' persistente → WABA desabilitada."
                    status('🔴 ' + r['mensagem'])
                    return r
                r['sms_falhou'] = True
                r['mensagem'] = ("'Problema ao salvar' persistente (número virtual queimado) — "
                                 "cancelo o número, compro outro e reinicio a verificação.")
                status('🔁 ' + r['mensagem'])
                return r
        else:
            _erro_salvar_streak = 0
        # 0-c3) BLOQUEIO DE AÇÃO do PERFIL (anti-spam): "Limitamos a frequência com que
        #       você pode postar, comentar ou fazer outras coisas... para proteger a
        #       comunidade contra spam. Você pode tentar novamente mais tarde."
        #       ⭐ Provado pelo dono (2026-08-29): NÃO é IP (trocou no avião 10s), NÃO é
        #       número (SMS novo), NÃO é a BM (WABA fica APROVADA) — é um bloqueio TEMPORÁRIO
        #       do PERFIL. Trocar IP/número aqui só QUEIMA número em loop (o diagnóstico
        #       acha BM/WABA saudáveis e o loop externo re-compra número eternamente).
        #       Recuperação certa: descartar ESTA BM e seguir por uma 2ª BM no mesmo perfil.
        #       (streak p/ não descartar por um bloqueio de 1 frame; após confirmar, sinaliza.)
        if _existe_texto(driver, ['limitamos a frequência', 'limitamos a frequencia',
                                  'we limit how often you can',
                                  'proteger a comunidade contra spam',
                                  'protect our community from spam',
                                  'você está temporariamente bloqueado',
                                  'voce esta temporariamente bloqueado',
                                  "you're temporarily blocked",
                                  'temporarily restricted from'], timeout=1):
            _acao_bloqueada_streak += 1
            if _acao_bloqueada_streak >= 3:
                r['acao_bloqueada'] = True
                r['mensagem'] = ('Bloqueio de ação do PERFIL ("Limitamos a frequência…") '
                                 f'persistente ({_acao_bloqueada_streak}x) — IP/número não '
                                 'resolvem; descartar esta BM e seguir pela 2ª BM.')
                status('🚫 ' + r['mensagem'])
                return r
            status('⏳ Bloqueio de ação do perfil ("Limitamos a frequência…") — aguardando e reavaliando...')
            _delay_medio(); _delay_medio()
        else:
            _acao_bloqueada_streak = 0
        # 0-d) FAST-PATH da tela "Verifique com o domínio da empresa" (SÓ ela).
        #      É um modal ESTÁVEL de confirmação (domínio verificado → Avançar) e o
        #      ÚLTIMO gargalo do fluxo: no loop normal o bot fica 60-120s parado aqui
        #      (paga os ~8s do _esperar_estatico por volta + ciclos de skeleton). Como
        #      esta tela NÃO faz bounce (≠ da sequência Ações/país que quebrava com
        #      "detecta primeiro"), detectamos por texto e clicamos Avançar NA HORA.
        #      `_avancar` já espera o botão aparecer (clique robusto), então continua
        #      seguro; um cap de tentativas evita spin se não avançar (aí o loop normal
        #      assume). NÃO mexe em nenhuma outra tela — o resto segue esperar→detectar→agir.
        if _dominio_fast < 12 and _eh_tela_dominio_confirmar(driver):
            _dominio_fast += 1
            status("🌐 Domínio verificado → Avançar")
            _dominio_feito = True
            if not _avancar(driver):
                _clicar_primario_dialogo_sem_form(driver, _hosts_site)
            _delay_medio()
            continue
        # 0-e) FAST-PATH da tela "Verifique com um documento e uma verificação de
        #      conexão" ("Não foi possível encontrar sua empresa"): detectada pelo
        #      aria-label (instantâneo), executa a MESMA ação do passo 'conexao_dominio'
        #      (domínio → SMS → ligação/WhatsApp → Avançar) sem pagar os ~8s do
        #      _esperar_estatico por volta. Cap de tentativas + fall-through: se o radio
        #      ainda não renderizou, `_selecionar_opcao_radio` falha e o loop normal
        #      assume — nunca fica em spin. (2026-07-15)
        # 📧 No método por E-MAIL este fast-path (que escolhe DOMÍNIO) é PULADO — cai no
        # passo 'conexao_dominio' normal, que seleciona 'Email (Recomendado)' e depois SMS.
        if _conexao_fast < 12 and not _por_email and _eh_tela_conexao_dominio(driver):
            _conexao_fast += 1
            # ESTRUTURAL e idioma-agnóstico (domínio → SMS). Antes eram rótulos SÓ em
            # pt com 10s de timeout cada: em inglês nada marcava e a aba ficava ~19 min
            # presa com o 'Next' desabilitado. (2026-10-13)
            _sel_fast = False
            if _marcar_radio_dominio(driver, timeout=3):
                status("🔗 Confirmar conexão → Verificação de domínio")
                _dominio_feito = True
                _sel_fast = True
            elif _marcar_radio_sms(driver, timeout=3):
                status("🔗 Confirmar conexão → Mensagem de texto (SMS)")
                _sel_fast = True
            elif _selecionar_opcao_radio_multi(driver, ['Ligação telefônica', 'Mensagem do WhatsApp',
                                                        'Phone call', 'WhatsApp message'], timeout=2):
                status("🔗 Confirmar conexão → Ligação/WhatsApp")
                _sel_fast = True
            if not _sel_fast:
                # Rádios ainda montando: NÃO clica nada (sem opção o Next fica
                # desabilitado e qualquer clique seria fora do lugar) — relê na volta.
                status("⏳ Confirmar conexão: opções ainda carregando — aguardando...")
                _delay_medio()
                continue
            _delay_curto()
            # UM clique e espera a Meta ENTREGAR a próxima tela (sem re-clicar em cima).
            if _avancar(driver):
                _aguardar_saida_conexao(driver)
            _delay_curto()
            continue
        # 0/1/2) LEITURA RÁPIDA COM CONFIRMAÇÃO (2026-07-31)
        #
        # Antes: TODA volta pagava _tratar_interrupcao_fb + _esperar_estatico(20s)
        # ANTES de detectar. Como a Central é uma SPA que nunca fica 100% parada
        # (spinners/polling de fundo), essa espera ia quase sempre até o teto — o
        # fluxo ficava 1-3 min congelado em CADA tela, mesmo com o modal já na
        # frente e pronto para o clique.
        #
        # Agora: detecta na hora (1 evaluate_page, ~ms) e CONFIRMA com uma segunda
        # leitura curta. Duas leituras IGUAIS = modal assentado → pode agir. Isso
        # preserva a garantia anti-BOUNCE (nunca agir no meio da transição, que foi
        # o motivo do revert de 2026-07-14) por ~0,45s em vez de até 20s.
        # Se as leituras DIVEREM, a tela está trocando: não age, relê na volta
        # seguinte. O caminho lento (interrupções + espera + nova leitura) só é
        # pago quando a tela é DESCONHECIDA — que é justamente quando algo pode
        # estar cobrindo a tela real (cookie/consent/checkpoint).
        passo = _detectar_tela_central(driver)
        if passo is not None:
            time.sleep(0.45)
            if _detectar_tela_central(driver) != passo:
                continue                      # ainda transicionando
        else:
            try:
                _tratar_interrupcao_fb(
                    driver, destino=f"{BASE}/security_center?business_id={business_id}")
            except Exception:
                pass
            try:
                _esperar_estatico(driver, timeout=8)
            except Exception:
                pass
            passo = _detectar_tela_central(driver)
        # 'coachmark' (diálogo SEM campo, texto não mapeado) que mostra o DOMÍNIO desta
        # empresa = tela 'Verifique com o domínio / Domínio verificado' num idioma não
        # mapeado (VI/RU/ID/HI...). Reconhecida pelo DADO, não pelo texto. (2026-10-12)
        if passo == 'coachmark' and _dialogo_dominio_sem_form(driver, _hosts_site):
            logger.info("[ProMax] diálogo sem campo com o domínio da empresa → 'dominio_confirmar'")
            passo = 'dominio_confirmar'
        # 🛡️ 'Iniciar'/'Começar' com um pop-up do FLUXO já aberto NUNCA é a ação certa:
        # abriria um 2º assistente por cima (→ "Sorry, something went wrong"). Fecha só o
        # pop-up de intro empilhado (se houver) e relê; nunca clica Get started/Iniciar.
        if passo in ('iniciar', 'acoes_necessarias') and _ha_dialogo_form(driver):
            _intro_sobre_fluxo += 1
            if _fechar_intro_sobre_fluxo(driver):
                status("🛡️ Pop-up de intro abriu POR CIMA do fluxo — fechei só ele e retomo o de baixo.")
            else:
                logger.info("[ProMax] passo %r com pop-up do fluxo aberto — não clico Iniciar/Começar.", passo)
            if _intro_sobre_fluxo >= 6:
                # Pilha de pop-ups que não desfaz: recarrega a Central (o progresso fica
                # salvo na Meta como "Pending submission") em vez de clicar às cegas.
                status("🔄 Pop-ups empilhados — recarregando a Central (progresso salvo na Meta)...")
                _ir_para(driver, f"{BASE}/security_center?business_id={business_id}",
                         esperar=['security_center'], timeout=40)
                _intro_sobre_fluxo = 0
            _delay_medio()
            continue
        # Cronômetro: fecha o tempo da tela anterior quando o passo MUDA.
        if passo != _passo_log:
            _agora = time.time()
            if _passo_log is not None:
                logger.info('[ProMax] tela %r levou %.1fs', _passo_log, _agora - _passo_t0)
            _passo_log, _passo_t0 = passo, _agora
        # Central SEM pop-up dizendo "Sua organização NÃO precisa ser verificada": a BM perdeu
        # o que a qualificava — no caso real (prints do dono 2026-10-13) a WABA foi
        # DESABILITADA no meio do envio. Não gira até o timeout: confere a WABA já.
        if passo is None and none_streak >= 1 and not _ha_dialogo_form(driver) \
                and _existe_texto(driver, _CENTRAL_NEGATIVO_TXT, timeout=1):
            if _waba_caiu_na_consulta(driver, business_id, status, r):
                return r
            r['mensagem'] = ("Central diz que a organização NÃO precisa ser verificada "
                             "(WABA não está desabilitada) — nada a enviar nesta BM.")
            r['possivel_waba_desabilitada'] = True   # loop externo roda o diagnóstico completo
            status('🟡 ' + r['mensagem'])
            return r
        if passo is None:
            # RECUPERAÇÃO (Onda 2): uma tela não reconhecida pode ser o ERRO GENÉRICO da
            # Meta ("há um problema técnico com esse recurso") ou o perfil DESLOGADO (caiu
            # no login). Tenta recuperar ANTES de insistir — barato e só age quando é o caso.
            # Só a partir da 2ª volta (dá chance à detecção normal) e re-navega à Central.
            if none_streak >= 2:
                try:
                    from server import session_guard as _sg
                    if _sg.pagina_meta_com_erro(driver):
                        status("⟳ Erro genérico da Meta na Central — recarregando (F5/backoff)...")
                        _sg.recuperar_erro_generico(driver, cap=2, callback_status=status)
                        none_streak = 0
                        continue
                    if _sg._na_login(driver):
                        status("🔐 Central caiu na tela de login — voltando ao facebook.com e re-logando...")
                        _sg.garantir_sessao_fb(
                            driver, callback_status=status,
                            renavegar_para=f"{BASE}/security_center?business_id={business_id}")
                        none_streak = 0
                        continue
                except Exception:
                    pass
            # Pode ser um coachmark/tooltip do FB ("Entendi"/"Got it") cobrindo a
            # tela real — dispensa (são seguros, só fecham a dica).
            if not _dispensar_coachmark(driver):
                _click_texto(driver, ['Entendi', 'Got it', 'Entendido', 'Ok, entendi'],
                             timeout=2)
            none_streak += 1
            # Depois de algumas voltas sem reconhecer a tela, tenta DESTRAVAR clicando um
            # botão de AVANÇO primário e SEGURO ("Iniciar verificação"/"Continuar"), se
            # estiver visível — cobre telas com coachmark "Entendi" sobre a landing da
            # Central (causa de 'tela_central_nao_identificada'). Só age a partir da 4ª
            # volta (não atropela a detecção normal). (2026-07-12)
            # ⚠️ Clique "cego" de destravamento: só nas voltas 4 e 8 (NÃO toda volta).
            #    Antes era `>= 4` → disparava a cada loop e, em telas EN não
            #    classificadas, abria CAMADA SOBRE CAMADA de modal (relato do dono).
            #    Antes de clicar, confirma que NÃO há erro genérico na tela (o guarda
            #    do topo já trata, mas aqui é cinto-e-suspensório contra re-disparo).
            # 🛡️ NUNCA com pop-up do fluxo aberto (tela de formulário desconhecida): o
            # 'Continuar' achado seria o do FUNDO da Central → abre 2º assistente por cima.
            if none_streak in (4, 8) and not _sg_erro_meta(driver) and not _ha_dialogo_form(driver):
                _clicar_botao_robusto(driver, ['Iniciar verificação', 'Iniciar verificacao',
                                               'Continuar', 'Continue'], timeout=3)
            if none_streak == 5 and not _cap_unknown:
                try:
                    from server.screen_capture import capturar_tela_desconhecida
                    capturar_tela_desconhecida(driver, contexto='central_seguranca',
                                               motivo='tela_central_nao_identificada')
                except Exception:
                    pass
                _cap_unknown = True
            if none_streak >= 12:
                r['mensagem'] = 'Tela da Central de Segurança não reconhecida (timeout).'
                return r
            time.sleep(1.5)
            continue
        none_streak = 0
        if passo == ultimo:
            repete += 1
        else:
            repete = 0
            ultimo = passo
        # NÃO clonar a aba globalmente por "repetiu N vezes". Isso destruía o modal
        # ABERTO no meio do fluxo (ex.: 'pais'/'sms_enviar' só precisando de mais
        # algumas voltas de Avançar/aguardar) e REINICIAVA tudo desde a landing →
        # era a causa do BOUNCE (Iniciar→Ações→País→clone→Iniciar…) e do "após
        # 'Enviando SMS' voltou pra Central". Os passos de FORMULÁRIO re-tentam no
        # LUGAR (até 8 voltas). O clone da aba p/ o bug do modal-skeleton continua,
        # porém SÓ dentro dos handlers 'iniciar'/'acoes_necessarias' (onde de fato
        # o modal não abre) — nunca no meio do fluxo. (Comportamento do backup bom.)
        if repete > 8:
            try:
                from server.screen_capture import capturar_tela_desconhecida
                capturar_tela_desconhecida(driver, contexto='central_seguranca',
                                           motivo=f'preso_no_passo_{passo}')
            except Exception:
                pass
            r['mensagem'] = f'Preso no passo "{passo}" da Central.'
            return r

        # ⏳ ESPERA HUMANA / ANTI-CLIQUE-DUPLO (2026-08-29, pedido do dono): se JÁ agimos
        # nesta MESMA tela de FORMULÁRIO na volta anterior, a Meta ainda está processando
        # o Avançar → NÃO re-clica. Espera a Meta ENTREGAR a próxima tela; só re-age se,
        # passado o tempo, a tela realmente não mudou (o clique não pegou). Isso acaba com
        # os cliques duplicados, os formulários empilhados e os erros "problema ao salvar"/
        # "Ocorreu um erro" que vinham de FORÇAR a passagem de tela sem esperar o servidor.
        # 100% LOCAL a este driver/aba (variáveis locais) — não cruza dado/clique de outra
        # aba; o fluxo de cada empresa/WABA fica isolado. (não vale p/ SMS/e-mail/captcha,
        # que têm espera própria e não estão em _PASSOS_FORM_CENTRAL.)
        if passo in _PASSOS_FORM_CENTRAL and passo == _ultimo_agido:
            if _aguardar_transicao_central(driver, passo):
                continue   # transicionou → a próxima volta detecta a nova tela
        # 🔁 GUARDA ANTI-LOOP DO ASSISTENTE (2026-10-12): o assistente que fecha/reinicia
        # sozinho (Ações → País → ... → volta p/ Iniciar → Ações → País → ...) girava até o
        # timeout de 8min (log #3266 en_GB). Conta cada ENTRADA nova em 'pais' e em
        # 'acoes_necessarias'; passou do teto → encerra como TERMINAL (descanso), sem
        # recomprar número contra um assistente que não sai do lugar.
        if passo != _ultimo_agido:
            if passo == 'pais':
                _entradas_pais += 1
            elif passo == 'acoes_necessarias':
                _entradas_acoes += 1
            if _entradas_pais > _MAX_ENTRADAS_PAIS or _entradas_acoes > _MAX_ENTRADAS_ACOES:
                try:
                    from server.screen_capture import capturar_tela_desconhecida
                    capturar_tela_desconhecida(driver, contexto='central_seguranca',
                                               motivo='assistente_reiniciando_em_loop')
                except Exception:
                    pass
                r['mensagem'] = (f'Assistente da Central reiniciou em loop (País {_entradas_pais}x, '
                                 f'Ações {_entradas_acoes}x) — perfil em descanso p/ reenvio depois.')
                r['wizard_em_loop'] = True
                r['descansar'] = True
                status('🛌 ' + r['mensagem'])
                return r
        _ultimo_agido = passo

        # 3) AÇÃO específica da tela ATUAL (nunca de outra).
        if passo == 'coachmark':
            # Tooltip/coachmark promocional do FB cobrindo a tela do fluxo → dispensa
            # SEM tocar no modal do fluxo (senão cancela a verificação).
            _dispensar_coachmark(driver)
            _delay_curto()

        elif passo == 'iniciar':
            status("▶️ Central: Iniciar verificação...")
            # MESMO problema do "Começar": o botão 'Iniciar verificação' é um
            # div[role=button] do React que às vezes tem overlay por cima → o
            # clique 'actionable' do Playwright falha e fica clicando sem abrir.
            # Usa o clique robusto (JS dispatch) + verifica se a tela mudou.
            # O botão que abre o formulário muda de nome nas re-tentativas:
            # "Iniciar verificação" na 1ª; depois "Continuar"/"Mais informações"/etc.
            _iniciar = ['Iniciar verificação', 'Iniciar verificacao', 'Iniciar',
                        'Continuar', 'Mais informações', 'Mais informacoes',
                        'More information', 'Continue', 'Start verification', 'Start']
            # UM clique REAL e ESPERA INTELIGENTE: clica uma vez e aguarda o modal
            # 'Ações necessárias' renderizar 100% (poll até a próxima tela conhecida
            # aparecer) — SEM re-clicar enquanto carrega (isso travava o FB no
            # skeleton). Só se o modal NÃO abrir após a espera é que troca de aba
            # (nova aba no security_center + clique natural), que funciona sempre.
            _abriu = _clicar_e_aguardar_saida(driver, _iniciar, 'iniciar',
                                              timeout_render=20, status=status)
            if not _abriu and _dup_central < 3:
                _dup_central += 1
                status("🔁 Modal não abriu após esperar — abrindo em NOVA ABA e clicando naturalmente...")
                _duplicar_aba_central(driver, business_id, status)
            _delay_curto()

        elif passo == 'acoes_necessarias':
            status("📋 Central: Ações necessárias → Começar")
            _comecar = ['Começar', 'Comece', 'Start', 'Get started']
            # UM clique REAL + espera o formulário (país/tipo/etc.) renderizar 100%
            # antes de seguir. Sem re-clicar enquanto carrega. Se travar (skeleton),
            # abre em NOVA ABA e clica naturalmente.
            _avancou = _clicar_e_aguardar_saida(driver, _comecar, 'acoes_necessarias',
                                                timeout_render=18, status=status)
            if not _avancou and _dup_central < 3:
                _dup_central += 1
                status("🔁 'Começar' travado — abrindo em NOVA ABA e clicando naturalmente...")
                _duplicar_aba_central(driver, business_id, status)
            _delay_curto()

        elif passo == 'pais':
            status("🌎 País: Brasil → Avançar")
            # O País já vem 'Brasil' e o Avançar fica HABILITADO (azul), mas o
            # clique 'actionable' do Playwright falha por causa de um overlay
            # (data-visualcompletion="ignore", inset:0) → logava "Texto não
            # clicável" e o fluxo ficava PRESO/voltava a esta tela. Clique ROBUSTO
            # (JS dispatch) ignora o overlay, igual aos passos 'contato'/'iniciar'.
            if _pais_central_vazio(driver):
                # Raro: País veio vazio ('Selecionar um país') → seleciona Brasil.
                _selecionar_pais_brasil_central(driver)
                _delay_curto()
            elif _pais_vazio_estrutural(driver):
                # Idioma não mapeado: combobox do País SEM 'bra' e o primário DESABILITADO
                # → seleciona Brasil pela ESTRUTURA (método provado em conta EN, 2026-09-18).
                try:
                    from server.verificacao_bm import _selecionar_pais_brasil
                    _selecionar_pais_brasil(driver)
                except Exception as _e_p:
                    logger.debug("[ProMax] seleção estrutural do país falhou: %s", _e_p)
                    _selecionar_pais_brasil_central(driver)
                _delay_curto()
            # ⚠️ FIX loop #3266 (2026-10-12): antes ia DIRETO no _clicar_botao_robusto, cujo
            # 1º passo (_click_texto) falha no overlay ('Texto não clicável') e o 2º é um JS
            # dispatch (evento NÃO confiável) que no 2º assistente NÃO avança → a tela ficava
            # em 'pais' / voltava p/ 'Ações'. Agora usa o MESMO caminho dos outros passos:
            # `_avancar` = espera o pop-up assentar + clique REAL de mouse conferido (o ponto
            # cai no botão) → robusto → primário azul (idioma-agnóstico).
            _avancar(driver)
            _delay_medio()

        elif passo == 'tipo':
            if str(tipo_empresa).lower().startswith('mei') or 'individual' in str(tipo_empresa).lower():
                status("🏷️ Tipo: Empresa individual (MEI)")
                _tipos_mei = ['Empresa individual', 'Individual', 'Sole proprietor',
                              'Sole proprietorship', 'Empresa unipersonal']
                if not _selecionar_opcao_radio_multi(driver, _tipos_mei):
                    _click_texto(driver, _tipos_mei, timeout=6)
            else:
                status("🏷️ Tipo: Empresa privada (LTDA)")
                _tipos_priv = ['Empresa privada', 'Private company', 'Privately held company',
                               'Privately held', 'Empresa privada']
                if not _selecionar_opcao_radio_multi(driver, _tipos_priv):
                    _click_texto(driver, _tipos_priv, timeout=6)
            _delay_curto()
            _avancar(driver)
            _delay_medio()

        elif passo == 'registro':
            status("🧾 Registro: Tem registro")
            _reg_sim = ['Tem registro', 'Has registration', 'Is registered',
                        'Yes, my business is registered', "Yes, it's registered", 'Registered',
                        'Sí, está registrada', 'Tiene registro']
            if not _selecionar_opcao_radio_multi(driver, _reg_sim):
                if not _click_texto(driver, _reg_sim, timeout=6):
                    # Idioma não mapeado: "tem registro" é a 1ª opção da lista.
                    _marcar_primeiro_radio_dialogo(driver)
            _delay_curto()
            _avancar(driver)
            _delay_medio()

        elif passo == 'cnpj':
            status(f"🔢 CNPJ: {cnpj_fmt}")
            _rot_cnpj = ['identificação fiscal', 'numero de registro da empresa',
                         'número de registro da empresa', 'identificacao fiscal',
                         # EN (inclui a tela nova 'Add business details' da migração de BM:
                         #  campo "Business Tax ID/Registration Number")
                         'business tax id', 'tax id/registration', 'tax id',
                         'tax identification number', 'business registration number',
                         'registration number',
                         # ES
                         'identificación fiscal', 'identificacion fiscal',
                         'número de registro de la empresa']
            # PREENCHIMENTO ESTRUTURAL + VERIFICADO (2026-10-05): o campo é achado pela
            # POSIÇÃO/estrutura do diálogo (1º input sem letras; o do nome vem com a
            # razão social), não pelo rótulo — funciona em qualquer idioma. Só avança
            # quando os dígitos do CNPJ ENTRARAM no campo (até 4 tentativas); com o
            # campo vazio o Next fica DESABILITADO e o fluxo ficava preso aqui.
            _cnpj_ok = _preencher_cnpj_central(
                driver, cnpj_fmt,
                (empresa_dados.get('razao_social') or empresa_dados.get('nome_fantasia') or '').strip(),
                _rot_cnpj, status)
            if not _cnpj_ok:
                # Não avança com o campo vazio (Next desabilitado): deixa a próxima volta
                # do loop reavaliar a tela (o guard anti-duplo-clique + repete>8 cuidam
                # de não travar eternamente).
                status("⚠️ Tax ID/CNPJ não entrou no campo nesta passagem — reavaliando a tela.")
                _delay_medio()
                continue
            status(f"✅ Tax ID/CNPJ preenchido ({cnpj_fmt}).")
            _delay_curto()
            # Botão primário ainda desabilitado? O React não validou o campo → tira o
            # foco (Tab) p/ disparar a validação antes de clicar.
            if _primario_dialogo(driver) == 'desabilitado':
                try:
                    driver.keyboard.press('Tab')
                except Exception:
                    pass
                _delay_curto()
            # Primário AZUL do diálogo primeiro (idioma-agnóstico, instantâneo); texto
            # (Avançar/Next/...) só se a cor não identificar o botão.
            if _primario_dialogo(driver, clicar=True) != 'clicado':
                _avancar(driver)
            _delay_medio()

        elif passo == 'endereco':
            # Endereço geralmente já vem preenchido; preenche só o que estiver vazio.
            _preencher_endereco_se_vazio(driver, empresa_dados)
            _avancar(driver)
            _delay_medio()

        elif passo == 'contato':
            # TELEFONE = número comprado ATUAL. Preenche UMA ÚNICA VEZ: re-preencher
            # a cada volta RE-DISPARA a consulta do FB e mantém o erro (era a causa
            # do "Preso no passo contato"). O FB às vezes devolve "Erro ao realizar
            # a consulta" (falha TRANSITÓRIA do backend ao buscar o registro do CNPJ)
            # e FICA na mesma tela → basta aguardar e re-clicar Avançar (a consulta
            # re-roda e passa). NÃO re-preenche o telefone nessas re-tentativas.
            # 🔒 REGRA DO DONO (2026-10-05): nesta tela SÓ entra o número REAL comprado
            # no SMS (o mesmo do Telefone da BM, do certificado e do site). Sem número
            # comprado em mãos, NÃO avança com o que estiver no campo (poderia ser o
            # número aleatório do cadastro inicial da BM).
            if not _so_digitos(telefone_nacional):
                r['sms_falhou'] = True
                r['mensagem'] = ('Tela de contato sem número de SMS comprado em mãos — não envio '
                                 'com telefone que não seja o real; recomeço com número novo.')
                status('🔒 ' + r['mensagem'])
                return r
            if telefone_nacional:
                if not _contato_feito:
                    _definir_telefone_contato(driver, telefone_nacional, status)
                    _contato_feito = True
                    _delay_curto()
                elif not _telefone_confere(driver, telefone_nacional):
                    # A Meta zerou/alterou o Telefone nesta passagem (repasse/reenvio):
                    # recoloca o número comprado ATUAL — senão o SMS iria p/ o vazio/errado.
                    # (Só re-preenche quando NÃO confere, p/ não re-disparar a consulta à toa.)
                    status("☎️ Telefone de contato foi alterado — recolocando o número atual...")
                    _definir_telefone_contato(driver, telefone_nacional, status)
                    _delay_curto()
            # 🌐 SEMPRE garante o SUBDOMÍNIO completo no campo Site em CADA passagem por
            # esta tela — a Meta reverte p/ o domínio RAIZ em todo reenvio/repasse, não só
            # na 1ª vez. O 'Avançar' é re-clicado toda passagem, então re-aplicar o site é
            # seguro e idempotente. (2026-08-15 — pedido do usuário, provado por print.)
            _definir_site_contato(driver, site_url, status)
            if _existe_texto(driver, ['erro ao realizar a consulta', 'error performing',
                                      'não foi possível concluir a solicitação',
                                      'nao foi possivel concluir', 'tente novamente mais tarde'],
                             timeout=1):
                _erro_consulta_streak += 1
                # (2026-10-14) SEM conferência antecipada da WABA aqui: na 2.5 ela tirava o bot
                # do pop-up de contato no meio da consulta → o assistente reabria com o erro de
                # novo → streak chegava a 4 → número jogado fora (36 casos em 186 perfis; 0 na
                # 2.4). Comportamento da 2.4: reavança no lugar; ≥4 confere a WABA (abaixo).
                # "Erro ao realizar a consulta" é normalmente TRANSITÓRIO (re-avançar passa).
                # Quando PERSISTE, há DOIS motivos distintos e o tratamento é oposto:
                #   (a) WABA realmente DESABILITADA no meio do fluxo (cai de 'Aprovada' p/
                #       'Restricted' em <1min) → a consulta falha SEMPRE → abortar p/ 2ª BM.
                #   (b) IP compartilhado do 4G QUEIMADO/throttled por N abas simultâneas
                #       fazendo a consulta ao mesmo tempo → a Meta estrangula o IP e a
                #       consulta ao registro do CNPJ falha, MAS a WABA está VIVA.
                # ⭐ Provado pelo dono (2026-08-29): a WABA NÃO estava desabilitada — ao
                #    trocar o IP + número novo, foi p/ análise normalmente. Antes o bot
                #    abortava BM BOA como "WABA desabilitada". Agora DECIDE pelo estado real:
                #    confere se a WABA caiu; se NÃO caiu, é o caso (b) → troca IP 1x (como no
                #    rate-limit de SMS) + número novo + reinício, em vez de descartar a BM.
                if _erro_consulta_streak >= 4:
                    _erro_consulta_persistente(driver, business_id, status, r, _erro_consulta_streak)
                    return r
                status("↻ Central/contato: 'Erro ao realizar a consulta' (falha transitória do FB) — reesperando e reavançando...")
                _delay_medio()
                if _erro_consulta_streak >= 2:
                    _delay_medio()   # backoff: dá mais tempo p/ o registro/backend se recuperar
            else:
                _erro_consulta_streak = 0
            # Avançar REAL e CONFERIDO (2026-10-05). Tira o foco do campo (Tab → dispara
            # a validação do telefone/site), espera o pop-up ASSENTAR e só então clica.
            # Se a Meta acusar "telefone inválido" com o número CERTO no campo, é
            # validação fora de sincronia: reclica (sem re-preencher nem trocar de
            # número) — exatamente o que resolve quando se clica na mão.
            # 🔒 TRAVA DURA antes do clique: o campo Telefone tem que conter EXATAMENTE o
            # número comprado. Se não contiver, corrige (digitação real); se mesmo assim
            # não bater, NÃO clica — a próxima volta reavalia (repete>8 encerra).
            if not _telefone_contato_exato(driver, telefone_nacional):
                status("🔒 Telefone do pop-up ≠ número comprado — corrigindo antes de avançar...")
                _definir_telefone_contato(driver, telefone_nacional, status)
                if not _telefone_contato_exato(driver, telefone_nacional):
                    status("⚠️ Não confirmei o número comprado no campo — NÃO avanço; reavaliando a tela.")
                    _delay_medio()
                    continue
            _txt_av = ['Avançar', 'Continuar', 'Next', 'Continue', 'Siguiente']
            for _tent_av in range(3):
                if _tent_av == 0:
                    try:
                        driver.keyboard.press('Tab')
                    except Exception:
                        pass
                _aguardar_dialogo_pronto(driver, timeout=6)
                # Pausa humana: campos conferidos e assentados → só então o clique.
                time.sleep(random.uniform(1.0, 1.8))
                if not _clicar_avancar_real(driver, _txt_av):
                    if not _clicar_botao_robusto(driver, _txt_av, timeout=8):
                        _avancar(driver)
                if _aguardar_transicao_central(driver, 'contato', timeout=8):
                    break                              # a Meta entregou a próxima tela
                if _erro_telefone_invalido(driver) and (
                        not telefone_nacional or _telefone_confere(driver, telefone_nacional)):
                    status(f"↻ Meta acusou telefone inválido com o número certo no campo — "
                           f"reclicando Avançar ({_tent_av + 1}/3), sem trocar de número...")
                    _delay_medio()
                    continue
                break   # outro motivo (consulta/erro da Meta): o loop principal trata
            _delay_curto()

        elif passo == 'captcha':
            # reCAPTCHA Enterprise → CapSolver resolve + injeta; depois Avançar.
            if not _resolver_captcha(driver, business_id, captcha_token, status):
                r['mensagem'] = 'Falha no captcha.'
                return r
            _delay_curto()
            if _detectar_tela_central(driver) == 'captcha' or _existe_texto(
                    driver, ['confirmar que é você', 'não sou um robô',
                             'confirmar que e voce', 'nao sou um robo',
                             "i'm not a robot", 'confirm you are human',
                             'help us confirm', 'confirma que eres tú'], timeout=2):
                _avancar(driver)
            # Depois de resolver + Avançar, ESPERA a tela do captcha sair antes de
            # voltar ao loop — senão re-detecta o MESMO captcha (já resolvido) e
            # re-resolve à toa. O fluxo já estava correto; isso só evita o re-solve.
            _esperar_sair_do_captcha(driver, status, timeout=25)
            _delay_medio()

        elif passo == 'selecione_empresa':
            # Sempre 'Minha empresa não está na lista' (força UPLOAD do certificado).
            status("🏢 Registros públicos → 'Minha empresa não está na lista'")
            if not (_selecionar_opcao_radio(driver, 'Minha empresa não está na lista')
                    or _selecionar_opcao_radio(driver, 'Minha empresa nao esta na lista')
                    or _selecionar_opcao_radio(driver, "My business isn't listed")):
                _click_texto(driver, ['Minha empresa não está na lista',
                                      'Minha empresa nao esta na lista',
                                      "My business isn't listed"], timeout=6)
            _delay_curto()
            _avancar(driver)
            _delay_medio()

        elif passo == 'requisitos':
            # "Resolver problemas": marca a confirmação (1x, conferida) e clica Enviar/
            # Submit UMA vez, esperando a tela mudar → a próxima volta vê 'Em análise'.
            _marcar_e_enviar_requisitos(driver, status)
            _delay_curto()

        elif passo == 'carregar_doc':
            # ❗ "Erro ao realizar a consulta" NESTA tela (print do dono 2026-10-13: doc
            # anexado + "Sim" marcado + Avançar → erro). Antes só o passo 'contato' tratava
            # → aqui o bot reclicava Avançar em cima do erro até "Preso no passo". Mesmo
            # tratamento: transitório = espera humana com backoff e reavança 1x por volta;
            # persistente (≥4) = WABA caiu → 2ª BM; WABA viva → IP novo + número novo.
            if _existe_texto(driver, _ERRO_CONSULTA_TXT, timeout=1):
                _erro_consulta_streak += 1
                # Reavança NO LUGAR (sem sair do pop-up); ≥4 → decide pelo estado real da
                # WABA (desabilitada → 2ª BM; viva → IP + número novo). (2026-10-14)
                if _erro_consulta_streak >= 4:
                    _erro_consulta_persistente(driver, business_id, status, r, _erro_consulta_streak)
                    return r
                status(f"↻ Carregar documentos: 'Erro ao realizar a consulta' ({_erro_consulta_streak}/4, "
                       "falha transitória do FB) — aguardando e reavançando...")
                time.sleep(random.uniform(6, 10) * _erro_consulta_streak)   # backoff humano
                if _detectar_tela_central(driver) == 'carregar_doc':
                    if _avancar(driver):
                        _aguardar_transicao_central(driver, 'carregar_doc', timeout=12)
                continue
            _erro_consulta_streak = 0
            # Sub-pergunta "documento inclui o telefone? → Sim" surge na MESMA tela
            # após o upload. Trata-a se presente; senão faz o upload (uma vez só).
            if _existe_texto(driver, ['Seu documento inclui o número de telefone',
                                      'inclui o número de telefone',
                                      'inclui o telefone', 'inclui o numero de telefone',
                                      # EN — texto REAL "Did your document include your
                                      # business phone number?" (não "includes the phone
                                      # number", que era o padrão antigo e NÃO casava).
                                      'your document includes the phone number',
                                      'includes the phone number',
                                      'did your document include',
                                      'document include your business phone',
                                      'include your business phone number',
                                      'your business phone number',
                                      # ES
                                      'tu documento incluye el número de teléfono',
                                      'incluye tu número de teléfono',
                                      'incluye el número de teléfono'], timeout=2):
                status("☎️ Documento inclui o telefone? → Sim")
                _sim_opts = ['Sim', 'Yes', 'Sí', 'Si']
                if not _selecionar_opcao_radio_multi(driver, _sim_opts):
                    _click_texto(driver, _sim_opts, timeout=6)
                _delay_curto()
                _avancar(driver)
                _delay_medio()
            elif not _doc_enviado:
                # A Meta só aceita 1 documento por seção. Numa nova tentativa (outro
                # número + certificado regenerado) o certificado ANTIGO segue anexado
                # e trava o 'Avançar' com 'Você só pode carregar 1 documento'. Remove
                # o(s) antigo(s) de AMBAS as seções (razão social + telefone) ANTES de
                # enviar o novo — o upload fica idempotente: sempre 1 doc, o atual.
                if _remover_documentos_carregados(driver):
                    _delay_curto()
                status("📎 Documento: selecionando tipo 'CNPJ'...")
                _sel_doc_tipo = ['Selecione um tipo de documento', 'Select a document type',
                                 'Selecciona un tipo de documento']
                _click_texto(driver, _sel_doc_tipo, timeout=8)
                _delay_curto()
                if not _selecionar_opcao_lista(driver, _opcao_cnpj, timeout=8):
                    _click_texto(driver, _sel_doc_tipo, timeout=4)
                    _delay_curto()
                    _click_texto(driver, _opcao_cnpj,
                                 seletor_base='[role="option"], li, div, span', timeout=6)
                _delay_curto()
                status(f"📎 Enviando certificado ({os.path.basename(caminho_cert)})...")
                if not _enviar_arquivo(driver, caminho_cert):
                    r['mensagem'] = 'Falha ao anexar o certificado.'
                    return r
                _doc_enviado = True
                _delay_medio()
            else:
                # Já enviou e sem pergunta de telefone → segue.
                _avancar(driver)
                _delay_medio()

        elif passo == 'conexao_dominio':
            # Tela "Verifique com um documento e uma verificação de conexão" / "Não foi
            # possível encontrar sua empresa". 2 VARIANTES: (a) com "Verificação de
            # domínio" → seleciona DOMÍNIO (já verificado, confirma na hora, sem doc); (b)
            # SEM domínio, só Ligação/SMS/WhatsApp → seleciona SMS (o bot tem o número).
            # SEMPRE escolhe algo: domínio → SMS → ligação/WhatsApp → Avançar. (2026-07-13)
            # 📧 MÉTODO E-MAIL: seleciona 'Email (Recomendado)' — OBRIGATÓRIO antes do SMS.
            # Se o Email falhar, NÃO cai no SMS (bug 2026-08-15: caía no SMS na mesma
            # passada) — reavalia a tela e tenta de novo. Só depois do código do e-mail
            # confirmado (_email_feito) é que o SMS entra (próxima volta a esta tela).
            if _por_email and not _email_feito:
                if (_marcar_radio_email(driver)
                        or _selecionar_opcao_radio(driver, 'Email')
                        or _selecionar_opcao_radio(driver, 'E-mail')
                        or _click_texto(driver, ['Email', 'E-mail'], timeout=3)):
                    status("📧 Confirmar conexão → Email (Recomendado)")
                    _delay_curto()
                    _avancar(driver)
                    _delay_medio()
                else:
                    status("📧 Ainda não marquei o Email — reavaliando (NÃO caio no SMS).")
                    _delay_medio()
                continue
            _sel = False
            _dom_opts = ['Verificação de domínio', 'Verificacao de dominio',
                         'Domain verification', 'Verificación de dominio']
            _sms_opts = ['Mensagem de texto (SMS)', 'Mensagem de texto', 'Text message',
                         'Text message (SMS)', 'Mensaje de texto']
            _call_opts = ['Ligação telefônica', 'Mensagem do WhatsApp', 'Phone call',
                          'WhatsApp message', 'Llamada telefónica', 'Mensaje de WhatsApp']
            if not _sel and not _por_email and (
                    _marcar_radio_dominio(driver, timeout=4)
                    or _selecionar_opcao_radio_multi(driver, _dom_opts, timeout=2)
                    or _click_texto(driver, _dom_opts, timeout=3)):
                status("🔗 Confirmar conexão → Verificação de domínio")
                _dominio_feito = True
                _sel = True
            if not _sel and (_marcar_radio_sms(driver, timeout=3)
                             or _selecionar_opcao_radio_multi(driver, _sms_opts, timeout=2)
                             or _click_texto(driver, _sms_opts, timeout=3)):
                status("🔗 Confirmar conexão → Mensagem de texto (SMS)")
                _sel = True
            if not _sel and (_selecionar_opcao_radio_multi(driver, _call_opts, timeout=2)
                             or _click_texto(driver, _call_opts, timeout=3)):
                status("🔗 Confirmar conexão → Ligação/WhatsApp")
                _sel = True
            if not _sel:
                # último recurso: qualquer radio visível (não fica sem escolher)
                (_selecionar_opcao_radio(driver, 'domínio') or _selecionar_opcao_radio(driver, 'domain')
                 or _selecionar_opcao_radio(driver, 'SMS'))
            _delay_curto()
            _avancar(driver)
            _delay_medio()

        elif passo == 'metodo':
            # Tela "Escolha um método": DOMÍNIO primeiro (Método 7) OU 📧 EMAIL (Método 9),
            # depois SMS.
            # 📧 MÉTODO E-MAIL: Email é OBRIGATÓRIO antes do SMS. Se falhar, NÃO cai no
            # SMS — reavalia (continue).
            if _por_email and not _email_feito:
                if (_marcar_radio_email(driver)
                        or _selecionar_opcao_radio(driver, 'Email')
                        or _selecionar_opcao_radio(driver, 'E-mail')
                        or _click_texto(driver, ['Email', 'E-mail'], timeout=4)):
                    status("📧 Método: Email (Recomendado)")
                    _delay_curto()
                    _avancar(driver)
                    _delay_medio()
                else:
                    status("📧 Método: ainda não marquei o Email — reavaliando (NÃO caio no SMS).")
                    _delay_medio()
                continue
            _dom_opts_m = ['Verificação de domínio', 'Verificacao de dominio',
                           'Domain verification', 'Verificación de dominio']
            _sms_opts_m = ['Mensagem de texto (SMS)', 'Mensagem de texto', 'Text message',
                           'Text message (SMS)', 'Mensaje de texto']
            if not _por_email and not _dominio_feito and (_marcar_radio_dominio(driver, timeout=4)
                                       or _selecionar_opcao_radio_multi(driver, _dom_opts_m, timeout=2)
                                       or _click_texto(driver, _dom_opts_m, timeout=4)):
                status("🌐 Método: Verificação de domínio")
                _delay_curto()
                _avancar(driver)
                _delay_medio()
            else:
                status("📱 Método: Mensagem de texto (SMS)")
                if not (_marcar_radio_sms(driver, timeout=3)
                        or _selecionar_opcao_radio_multi(driver, _sms_opts_m, timeout=2)):
                    _click_texto(driver, _sms_opts_m, timeout=6)
                _delay_curto()
                _avancar(driver)
                _delay_medio()

        elif passo == 'dominio_confirmar':
            status("🌐 Domínio verificado → Avançar")
            _dominio_feito = True
            if not _avancar(driver):
                # Diálogo SEM campo + botão com texto não mapeado: primário azul (estrutural).
                _clicar_primario_dialogo_sem_form(driver, _hosts_site)
            _delay_medio()

        elif passo == 'email_endereco':
            # 📧 "Confirmar endereço de email": digita o e-mail comercial (@dominio do
            # site, FIXADO pela Meta) e clica "Enviar email". (validado nos prints 2026-08-15)
            _email_addr = _digitar_email_comercial(driver, empresa_dados, bm_email) or _email_addr
            if _email_addr:
                # 📧 FRESCOR: marca o id da última mensagem JÁ na caixa ANTES de pedir o
                # código. Depois só aceito id MAIOR → pega o e-mail que chega DEPOIS de
                # "Enviar email", nunca um código antigo (ex.: o da criação da conta).
                try:
                    from server.gsmails_integration import latest_msg_id
                    _base = latest_msg_id(_email_addr)
                    if _base and _base > _email_since_id:
                        _email_since_id = _base
                except Exception as _e:
                    logger.warning("[ProMax/E-mail] baseline id falhou: %s", _e)
                status(f"📧 E-mail comercial: {_email_addr} (baseline id={_email_since_id}) — enviando código...")
                _delay_curto()
                if not _clicar_botao_robusto(driver, ['Enviar email', 'Enviar e-mail',
                                                      'Send email', 'Send Email'], timeout=8):
                    _click_texto(driver, ['Enviar email', 'Enviar e-mail', 'Enviar'], timeout=6)
                _delay_medio()
            else:
                status("⚠️ E-mail: não achei o domínio/campo na tela — reavaliando.")
                _delay_medio()

        elif passo == 'email_codigo':
            # 📧 Lê o código do e-mail no GSMAILS (remetente facebookmail.com) e digita.
            # MESMO título do SMS, mas aqui o destino é o e-mail (a tela mostra o @).
            if not _email_addr:
                _email_addr = _email_da_tela(driver)
            status(f"📧 Aguardando código do e-mail em {_email_addr or '(GSMAILS)'}...")
            _cod = ''
            try:
                from server.gsmails_integration import wait_code
                if _email_addr:
                    # since_id = baseline: só o código que chegou DEPOIS de "Enviar email".
                    _cod = wait_code(_email_addr, 'facebookmail.com', timeout=120,
                                     since_id=_email_since_id) or ''
            except Exception as _e:
                logger.warning("[ProMax/E-mail] wait_code falhou: %s", _e)
            if not _cod:
                _email_env_tent += 1
                if _email_env_tent <= 2:
                    status("📧 Código do e-mail ainda não chegou — reenviando...")
                    if not _clicar_botao_robusto(driver, ['Reenviar código', 'Reenviar',
                                                          'Resend code', 'Resend'], timeout=6):
                        _click_texto(driver, ['Reenviar código', 'Reenviar', 'Resend code',
                                              'Resend'], timeout=5)
                    _delay_medio()
                    continue
                r['mensagem'] = 'Código do e-mail (verificação da empresa) não chegou.'
                status("❌ " + r['mensagem'])
                return r
            status(f"🔑 Código do e-mail: {_cod} — confirmando...")
            _preencher_campo_por_rotulo(
                driver, ['Código de confirmação', 'codigo de confirmacao',
                         'código', 'codigo', 'confirmation code'], _cod, timeout=10)
            _delay_curto()
            _avancar(driver)
            _delay_longo_seguro()
            _email_feito = True

        elif passo == 'sms_enviar':
            # RATE-LIMIT de SMS ("Você tentou muitos códigos de verificação
            # recentemente"): o limite é POR IP. FORÇA a troca de IP do 4G (mesmo com
            # rotação desativada) — o coordenador pausa os navegadores em tela estática,
            # troca 1x e libera. Depois marca sms_falhou p/ o loop externo CANCELAR o
            # número e reenviar com um número NOVO num IP NOVO. Checado SÓ AQUI (nesta
            # tela), não a cada iteração — senão dá falso-positivo. (2026-07-14)
            if _eh_rate_limit_sms(driver):
                # [FIX 2026-07-15] Com abas SIMULTÂNEAS, forçar a troca de IP a CADA aba que
                # mostrava o rate-limit criava um STORM coletivo (o 4G tem 1 IP p/ todos →
                # a run inteira parava a cada ~40s). Agora o IP troca só 1x: a 1ª aba dispara
                # a troca; as demais, dentro do COOLDOWN do coordenador, NÃO trocam de novo —
                # só REINICIAM o fluxo com número novo (o IP já está fresco; o rate-limit que
                # veem é resíduo da sessão antiga, de antes da troca).
                # [FIX 2026-07-15] Com abas SIMULTÂNEAS, forçar a troca de IP a CADA aba que
                # mostrava o rate-limit criava um STORM coletivo (o 4G tem 1 IP p/ todos →
                # a run inteira parava a cada ~40s). Agora o IP troca só 1x: a 1ª aba dispara
                # a troca; as demais, dentro do COOLDOWN do coordenador, NÃO trocam de novo —
                # só REINICIAM o fluxo com número novo (o IP já está fresco; o rate-limit que
                # veem é resíduo da sessão antiga, de antes da troca).
                # ⚠️ Confirmado pelo dono 2026-08-28: parar TODAS as abas é o certo (o
                # rate-limit é do IP, compartilhado). As abas que já estão AGUARDANDO o SMS
                # não são interrompidas no meio (o checkpoint fica no topo do loop; só param
                # depois do SMS chegar/esgotar) — se não chegar, trocam número junto na troca.
                _ip_off = False
                try:
                    from server.ip_rotation_coordinator import COORD as _IPCOORD
                    _res_ip = _IPCOORD.request('tela rate-limit SMS (muitos códigos)')
                    if _res_ip in ('solicitada', 'em_andamento'):
                        status('📵 Rate-limit de SMS — trocando IP 4G (1x) e reiniciando com número novo...')
                        _IPCOORD.checkpoint(alive_fn=lambda: _navegador_vivo(driver))
                    elif _res_ip == 'recente':
                        # IP já foi trocado há pouco por outra aba → NÃO troca de novo,
                        # só reinicia com número novo (o IP já está fresco).
                        status('🔁 IP já trocado há pouco — só troco o número e reinicio o fluxo (sem nova troca de IP).')
                    else:
                        # 'inativo' = 4G DESATIVADO na interface. O sistema NÃO troca o IP
                        # (por escolha do dono) — apenas segue com número novo. A troca de IP
                        # é MANUAL (o operador troca no aparelho/VPN, ou usa uma VPN que
                        # rotaciona sozinha). Aviso claro no terminal p/ ele agir se quiser.
                        _ip_off = True
                        status('⚠️ Rate-limit de SMS e 4G DESATIVADO — NÃO troco o IP (troque MANUALMENTE '
                               'no aparelho/VPN, ou use uma VPN que rotacione sozinha). Sigo com número novo.')
                except Exception as _e_ip:
                    logger.warning('[ProMax] coordenação de troca de IP falhou: %s', _e_ip)
                r['sms_falhou'] = True
                r['rate_limit'] = True  # p/ o loop externo contar reincidência → descanso
                if _ip_off:
                    r['mensagem'] = ('Rate-limit de SMS (muitos códigos) — 4G desativado: IP NÃO trocado '
                                     '(troca manual/VPN); reinício do fluxo com número novo.')
                else:
                    r['mensagem'] = ('Rate-limit de SMS (muitos códigos) — número novo + reinício '
                                     'do fluxo (IP trocado 1x; abas seguintes só reiniciam).')
                status('🔁 ' + r['mensagem'])
                return r
            # GATE ANTI-RAJADA POR IP (2026-08-30): várias abas no MESMO IP clicando
            # "Enviar SMS" quase juntas fazem a Meta acusar "muitos códigos de verificação
            # recentemente" ANTES mesmo de o código sair. O coordenador dá a esta aba um
            # SLOT escalonado (espaçamento mínimo entre envios no IP atual). Barato com 1 aba.
            try:
                from server.ip_rotation_coordinator import COORD as _IPCOORD
                _IPCOORD.sms_send_slot(alive_fn=lambda: _navegador_vivo(driver),
                                       status_fn=status)
            except Exception as _e_slot:
                logger.debug("[ProMax] sms_send_slot ignorado: %s", _e_slot)
            status("📨 Enviando SMS...")
            # "Enviar SMS" é div[role=button] do React — o clique 'natural' às vezes NÃO
            # registra (overlay/skeleton) e a tela fica presa (causa de travamento). Usa o
            # clique ROBUSTO (JS dispatch) e, se não achar, o texto. (2026-07-12)
            if not _clicar_botao_robusto(driver, ['Enviar SMS', 'Enviar código', 'Enviar',
                                                  'Send SMS', 'Send code', 'Send'], timeout=10):
                _click_texto(driver, ['Enviar SMS', 'Enviar'], timeout=8)
            _delay_medio()

        elif passo == 'sms_codigo':
            # Até 3 "desafios": pega o código, digita e Avança. Se o FB responder
            # "O desafio expirou. Inicie um novo." (o código venceu antes de
            # confirmar), NÃO desiste — pede um NOVO código (Reenviar no FB +
            # reenvio no provedor sms24h) e tenta de novo com um código fresco.
            _confirmou = False
            _tela_saiu = False
            for _desafio in range(1, 4):
                codigo = _aguardar_codigo_sms(driver, sms, ativacao_id, status)
                if codigo == _TELA_SAIU_DO_CODIGO:
                    # A Central reverteu a tela durante a espera → re-conduz (não fica preso).
                    _tela_saiu = True
                    break
                if not codigo:
                    r['sms_falhou'] = True
                    r['mensagem'] = 'SMS não chegou após as tentativas.'
                    return r
                # Se uma troca de IP começou entre o código chegar e o envio, PARA aqui
                # até o IP novo subir (não submete durante a queda de rede da troca).
                try:
                    from server.ip_rotation_coordinator import COORD as _IPCOORD
                    _IPCOORD.checkpoint(alive_fn=lambda: _navegador_vivo(driver))
                except Exception:
                    pass
                status(f"🔑 Código recebido: {codigo} — confirmando... (desafio {_desafio}/3)")
                _preencher_campo_por_rotulo(
                    driver, ['código de confirmação', 'codigo de confirmacao', 'código', 'codigo',
                             'confirmation code', 'enter the code', 'código de confirmación', 'code'],
                    codigo, timeout=10)
                _delay_curto()
                _avancar(driver)
                # UM clique e ESPERA o resultado real (sem re-clicar) — qualquer idioma.
                _res_cod = _resultado_codigo(driver, timeout=20)
                if _res_cod == 'erro_salvar':
                    # "Problema ao salvar" logo após o código. Às vezes é transitório:
                    # espera como um humano e confirma UMA vez. Se persistir, o código NÃO
                    # foi aceito → MESMO processo do "código incorreto" (pt-BR): volta ao
                    # contato, troca o número e pede outro código. (regra do dono 2026-10-13)
                    status("⚠️ Meta: 'problema ao salvar' após o código — aguardo e confirmo 1x...")
                    time.sleep(random.uniform(8, 12))
                    if _detectar_tela_central(driver) == 'sms_codigo':
                        _avancar(driver)
                        time.sleep(random.uniform(4, 6))
                        _res_cod = _resultado_codigo(driver, timeout=20)
                    else:
                        _res_cod = 'saiu'
                    if _res_cod in ('erro_salvar', 'incorreto'):
                        status("❌ Código NÃO aceito ('problema ao salvar' persistente, número "
                               "queimado) — volto ao contato, troco o número e peço outro código...")
                        _voltar_ate_contato(driver, status)
                        r['sms_falhou'] = True
                        r['codigo_incorreto'] = True
                        r['mensagem'] = ('Código não aceito pela Meta ("problema ao salvar") — número '
                                         'trocado, contato regravado e novo código solicitado.')
                        return r
                # DESAFIO/CÓDIGO EXPIROU? ("O desafio expirou. Inicie um novo.") →
                # solicita um NOVO código e repete (não desiste à toa).
                if _res_cod == 'expirou' or (_res_cod not in ('saiu', 'incorreto') and
                                             _existe_texto(driver, _CODIGO_EXPIROU_TXT, timeout=2)):
                    if _desafio >= 3:
                        break
                    status("⏱️ Código/desafio expirou — solicitando um NOVO código...")
                    if not _clicar_botao_robusto(driver, ['Reenviar código', 'Reenviar',
                                                          'Iniciar um novo', 'Enviar novamente',
                                                          'Resend code', 'Resend', 'Start a new one',
                                                          'Send again'], timeout=8):
                        _click_texto(driver, ['Reenviar código', 'Reenviar', 'Resend code',
                                              'Resend', 'Reenviar código'], timeout=6)
                    try:
                        sms.solicitar_reenvio(ativacao_id)
                    except Exception:
                        pass
                    _delay_medio()
                    continue
                # ❌ CÓDIGO INCORRETO ("O código de confirmação que você inseriu está
                # incorreto. Tente novamente.") — regra do dono (2026-10-06): o código que
                # chegou NÃO é desta tentativa (número reusado/queimado pelo provedor).
                # NÃO insiste no mesmo número: VOLTA até a tela de contato e devolve
                # sms_falhou+codigo_incorreto → o loop externo cancela o número, compra
                # OUTRO (mesmo provedor — ele entregou), regrava o contato com o número
                # novo, reenvia p/ análise e pede um código novo.
                if _res_cod == 'incorreto' or (_res_cod != 'saiu' and _codigo_incorreto_na_tela(driver)):
                    status("❌ Código do SMS INCORRETO (número queimado) — volto ao contato, "
                           "troco o número e peço outro código...")
                    _voltar_ate_contato(driver, status)
                    r['sms_falhou'] = True
                    r['codigo_incorreto'] = True
                    r['mensagem'] = ('Código do SMS incorreto — número trocado, contato regravado '
                                     'e novo código solicitado.')
                    return r
                _confirmou = True
                break
            # A tela SAIU do código no meio da espera (Central reverteu p/ 'Ações
            # necessárias'/'Iniciar'/'Em análise') → deixa o state machine re-detectar e
            # re-conduzir, em vez de ficar preso 'Aguardando SMS'.
            if _tela_saiu:
                _delay_curto()
                continue
            # CRÍTICO: espera o spinner + clica os botões + confirma 'Em análise'
            # ESTÁTICO antes do sucesso (fechar antes cancela o envio).
            if _confirmou and _aguardar_em_analise_final(driver, business_id, status, timeout=180):
                r['em_analise'] = True
                r['sms_usado'] = True   # o código do SMS foi digitado e confirmado
                r['mensagem'] = 'BM enviada para análise (Em análise) — confirmado na Central.'
                return r
            try:
                from server.screen_capture import capturar_tela_desconhecida
                capturar_tela_desconhecida(driver, contexto='central_seguranca',
                                           motivo='em_analise_final_nao_confirmado')
            except Exception:
                pass
            r['mensagem'] = 'Não confirmei o estado final "Em análise" na Central.'
            return r

        elif passo == 'em_analise':
            # Já chegou no estado final — confirma o estado estático e conclui.
            if _aguardar_em_analise_final(driver, business_id, status, timeout=120):
                r['em_analise'] = True
                r['mensagem'] = 'BM enviada para análise (Em análise) — confirmado na Central.'
                return r
            r['mensagem'] = 'Não confirmei o estado final "Em análise" na Central.'
            return r

    # Timeout geral do fluxo.
    r['mensagem'] = r.get('mensagem') or 'Fluxo da Central não concluído (timeout geral).'
    return r


_CODIGO_INCORRETO_TXT = [
    # PT
    'inseriu está incorreto', 'inseriu esta incorreto', 'está incorreto. tente novamente',
    'esta incorreto. tente novamente', 'código incorreto', 'codigo incorreto',
    'código de confirmação incorreto', 'codigo de confirmacao incorreto',
    # EN
    'code you entered is incorrect', 'incorrect code', 'incorrect confirmation code',
    'the code is incorrect', 'wrong code', "code you entered isn't correct",
    # ES
    'código incorrecto', 'codigo incorrecto', 'código que ingresaste es incorrecto',
]


_CODIGO_INCORRETO_TXT += [
    # EN (variações reais da Meta) + PT/ES extras
    "code isn't right", 'code is not right', "that code isn't", 'invalid code', 'code is invalid',
    "code isn't valid", 'code is not valid', "code doesn't match", 'code does not match',
    'código inválido', 'codigo invalido', 'código não é válido', 'codigo nao e valido',
    'código no es válido', 'codigo no es valido',
]

# "Ocorreu um problema ao SALVAR suas alterações. Aguarde alguns minutos" — em inglês a
# Meta escreve "There was a problem WHILE saving your changes" (≠ da lista antiga "problem
# saving your changes" → NUNCA casava em EN e o bot ficava preso na tela do código, print
# do dono 2026-10-13). Âncoras CURTAS p/ cobrir as variações; a tradução (via
# _existe_texto) cobre os demais idiomas.
_ERRO_SALVAR_TXT = [
    'problema ao salvar', 'problema ao guardar',
    'problem while saving', 'problem saving your changes', 'problem saving',
    'error saving your changes', 'error while saving',
    'problema al guardar', 'error al guardar',
]

_CODIGO_EXPIROU_TXT = [
    'o desafio expirou', 'desafio expirou', 'inicie um novo', 'challenge expired',
    'challenge has expired', 'code has expired', 'code expired', 'código expirou',
    'codigo expirou', 'código inválido ou expirou', 'codigo invalido ou expirou',
    'start a new one', 'el código caducó', 'el codigo caduco',
]


def _campo_codigo_invalido(driver) -> bool:
    """Sinal ESTRUTURAL (qualquer idioma): o campo do código no pop-up ficou
    aria-invalid="true" depois do envio."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            const ds = [...document.querySelectorAll('[role="dialog"]')].filter(d => {
                const r = d.getBoundingClientRect(); return r.width > 120 && r.height > 120; });
            const d = ds.filter(x => x.querySelector('input')).pop();
            if (!d) return false;
            return [...d.querySelectorAll('input')].some(i => i.getAttribute('aria-invalid') === 'true');
        }"""))
    except Exception:
        return False


def _codigo_incorreto_na_tela(driver):
    """True se a tela do código acusa CÓDIGO INCORRETO (qualquer idioma: texto PT/EN/ES,
    tradução, ou o campo marcado aria-invalid) — diferente de 'expirou' (tratado antes,
    que só pede reenvio no mesmo número)."""
    try:
        return _campo_codigo_invalido(driver) or bool(
            _existe_texto(driver, _CODIGO_INCORRETO_TXT, timeout=3))
    except Exception:
        return False


def _resultado_codigo(driver, timeout=20):
    """Depois do Avançar na tela do código: ESPERA (sem re-clicar) o resultado real.
    'saiu' (a tela mudou — p.ex. Em análise) | 'expirou' | 'incorreto' | 'erro_salvar'
    ("problema ao salvar" — o código NÃO foi aceito) | 'parado' (nada mudou no prazo)."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            if not _navegador_vivo(driver):
                return 'saiu'
            _p = _detectar_tela_central(driver)
            if _p and _p != 'sms_codigo':
                return 'saiu'
            if _existe_texto(driver, _CODIGO_EXPIROU_TXT, timeout=0.6):
                return 'expirou'
            if _campo_codigo_invalido(driver) or _existe_texto(driver, _CODIGO_INCORRETO_TXT, timeout=0.6):
                return 'incorreto'
            if _existe_texto(driver, _ERRO_SALVAR_TXT, timeout=0.6):
                return 'erro_salvar'
        except Exception:
            pass
        time.sleep(0.6)
    return 'parado'


def _voltar_ate_contato(driver, status=None, max_voltas=4):
    """Depois de um código INCORRETO: clica 'Voltar'/'Back' no pop-up até cair na tela
    de CONTATO (ou método) — assim a próxima tentativa regrava o telefone com o NÚMERO
    NOVO em vez de ficar na tela do código com o número velho. Se não houver 'Voltar',
    fecha o pop-up (X); a Central guarda o progresso e o fluxo reabre em 'Continuar'."""
    for _ in range(max_voltas):
        try:
            passo = _detectar_tela_central(driver)
        except Exception:
            passo = None
        if passo in ('contato', 'metodo'):
            return True
        if not (_clicar_botao_robusto(driver, ['Voltar', 'Back', 'Atrás', 'Anterior'], timeout=4)
                or _click_texto(driver, ['Voltar', 'Back'], timeout=3)):
            break
        _delay_medio()
    # Sem 'Voltar' utilizável: fecha o pop-up e deixa o state machine reabrir pelo
    # 'Continuar' da Central (progresso salvo) — a tela de contato volta a ser conduzida.
    try:
        _fechar_popup_suporte(driver)
    except Exception:
        pass
    if status:
        status("↩️ Pop-up do código fechado — o fluxo reabre pelo 'Continuar' com o número novo.")
    return False


def _delay_longo_seguro():
    try:
        _delay(3.0, 6.0)
    except Exception:
        time.sleep(0.8)


def _preencher_endereco_se_vazio(driver, empresa_dados):
    """Preenche os campos de endereço APENAS se estiverem vazios.

    O endereço normalmente JÁ vem preenchido (herdado de 'Informações da empresa').
    Regras: (a) NUNCA escrever no 'Complemento' (deve ficar em branco); (b) só
    preencher um campo se ele estiver vazio; (c) se tudo já estiver preenchido,
    não altera nada (o chamador só clica em Avançar)."""
    ed = empresa_dados or {}
    endereco = f"{ed.get('logradouro','')}, {ed.get('numero','')}".strip(', ').strip()
    dados = {
        'endereco': endereco,
        'cidade': ed.get('municipio', '') or ed.get('cidade', ''),
        'estado': ed.get('uf', '') or ed.get('estado', ''),
        'cep': ed.get('cep', ''),
    }
    js = r"""(d) => {
        const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
        // Campos que NUNCA devem ser preenchidos (deixar em branco):
        const PROIB = ['complemento','complement','apt','suite','unidade','opcional','optional'];
        const grupos = [
            {chave:'endereco', rot:['endereço','endereco','address','street']},
            {chave:'cidade',   rot:['cidade','city']},
            {chave:'estado',   rot:['estado','província','provincia','região','regiao','state','province']},
            {chave:'cep',      rot:['código postal','codigo postal','cep','postal','zip']},
        ];
        function rotuloDoInput(inp){
            let t = norm(inp.getAttribute('aria-label')||inp.placeholder||'');
            if (t) return t;
            if (inp.id){ const l=document.querySelector('label[for="'+inp.id+'"]'); if(l) return norm(l.innerText); }
            let node = inp.parentElement;
            for (let i=0;i<4 && node;i++){
                const cand=[...node.querySelectorAll('label,span,div')]
                    .map(e=>norm(e.innerText)).filter(x=>x && x.length<40);
                if (cand.length) return cand[0];
                node = node.parentElement;
            }
            return '';
        }
        let mexeu = 0;
        const inputs = [...document.querySelectorAll('input[type=text],input:not([type]),textarea')]
            .filter(e=>e.offsetParent!==null);
        for (const inp of inputs){
            const rot = rotuloDoInput(inp);
            if (!rot || PROIB.some(p=>rot.includes(p))) continue;   // pula Complemento etc.
            const g = grupos.find(g=>g.rot.some(r=>rot===r || rot.startsWith(r) || rot.includes(r)));
            if (!g) continue;
            const val = (d[g.chave]||'').trim();
            if (val && !inp.value){   // SÓ se estiver vazio
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                try{ setter.call(inp, val); }catch(e){ inp.value = val; }
                inp.dispatchEvent(new Event('input',{bubbles:true}));
                inp.dispatchEvent(new Event('change',{bubbles:true}));
                mexeu++;
            }
        }
        return mexeu;
    }"""
    try:
        n = driver.evaluate_page(js, dados)
        if n:
            logger.info("[ProMax] Endereço: preenchi %s campo(s) vazio(s).", n)
    except Exception as e:
        logger.debug("[ProMax] preencher endereço (se vazio): %s", e)


def _passo_fora_do_codigo(driver):
    """Retorna o passo SE a página SAIU da tela de código (a Central reverteu p/ intro/
    landing/análise/captcha). '' se ainda estamos na tela de código (ou indefinido).
    Usado p/ NÃO ficar preso 'Aguardando SMS' quando a tela muda no meio da espera."""
    try:
        p = _detectar_tela_central(driver)
    except Exception:
        return ''
    if p in ('acoes_necessarias', 'iniciar', 'em_analise', 'captcha'):
        return p
    return ''


def montar_fila_provedores(sms_provedor, tokens):
    """Ordem em que os provedores de SMS serão tentados. Devolve [(prov, token)].

    Regra do dono (2026-08-30, REFORÇADA): comprar EXATAMENTE no provedor ESCOLHIDO na
    interface — NUNCA cair em outro. Antes a fila incluía os demais como fallback (A→B→C)
    e, quando o escolhido dava NO_NUMBERS/erro transitório, PULAVA p/ outro provedor
    (o dono escolhia sms24h e o sistema comprava no smsbower). Agora a fila tem SÓ o
    escolhido: a não-entrega é transitória e REINSISTE nele (número não entregue é
    CANCELADO/reembolsado; o freio contra loop é a 2ª BM, não a troca de provedor).
      • token em BRANCO = provedor DESATIVADO.
      • Salvaguarda: se o escolhido não tiver token (não deveria — o backend seta o token
        primário), cai nos que tiverem (sms24h por último), só p/ não travar sem SMS.
    """
    prov_sel = str(sms_provedor or '').strip().lower()
    tokens = {str(k).strip().lower(): str(v or '').strip()
              for k, v in dict(tokens or {}).items()}

    tk_sel = tokens.get(prov_sel, '')
    if tk_sel:
        return [(prov_sel, tk_sel)]      # EXATAMENTE o escolhido — sem fallback p/ outros

    # Salvaguarda (escolhido sem token): usa os que tiverem, sms24h por último.
    demais = [p for p in PROVEDORES.keys() if p not in (prov_sel, 'sms24h')]
    demais.append('sms24h')
    fila = []
    for p in demais:
        tk = tokens.get(p, '')
        if tk and not any(f[0] == p for f in fila):
            fila.append((p, tk))
    return fila


def _aguardar_codigo_sms(driver, sms, ativacao_id, status):
    """Espera o SMS de UM número por no máximo 2 minutos.

    Regra (REESCRITA pelo usuário em 2026-08-04, depois de 10 perfis seguidos sem
    NENHUM código no Vak-SMS):
      • consulta a API CONTINUAMENTE (a cada ~5s) — o código pode chegar a qualquer
        instante e tem de ser capturado no ato;
      • clicar em "Receber código" já É o 1º envio (natural). Aos 60s sem código,
        pede **1 reenvio** — e só; insistir no mesmo número não entrega;
      • aos **120s**: cancela o número. Quem troca de PROVEDOR é o chamador.

    ⚠️ NUNCA soltar um número sem cancelar: se largamos um número vivo e o SMS
    chega depois, o provedor cobra a ativação e não estorna.

    Retorna: o código (str) · '' (desistiu, número já cancelado) ·
    _TELA_SAIU_DO_CODIGO (a Central saiu da tela de código — re-conduzir)."""
    if not (sms and ativacao_id):
        return ''

    inicio = time.time()
    ultimo_reenvio = inicio
    reenvios = 0
    cancelado = False
    # Teto de espera POR NÚMERO. O painel informa a validade do número por servidor
    # (SMSBower 1500s, demais 1200s), mas isso é a janela do PROVEDOR, não o quanto o
    # fluxo pode ficar parado: o Watchdog derruba a aba aos 600s. Antes esse valor
    # SOBRESCREVIA o SMS_ESPERA_MAX e o teto virava 1200-1500s > 600s do Watchdog, então
    # a aba era morta no braço e o "cancela + estorna + troca de número" nunca rodava.
    #
    # Agora a janela do provedor só pode ENCURTAR a espera (não faz sentido esperar mais
    # que a validade do número), nunca esticá-la além do que o fluxo aguenta.  (2026-09-07)
    _espera_max = SMS_ESPERA_MAX
    try:
        _tt = int(getattr(sms, '_ultimo_timeout', 0) or 0)
        if _tt > 0:
            _espera_max = min(_espera_max, _tt)
    except Exception:
        pass
    _espera_max = min(_espera_max, SMS_TETO_WATCHDOG)

    def _tentar_cancelar():
        """True se o provedor aceitou cancelar (número devolvido/estornado)."""
        try:
            return bool(sms.cancelar(ativacao_id))
        except Exception as e:
            logger.debug("[ProMax] cancelar %s: %s", ativacao_id, e)
            return False

    status(f"⏳ Aguardando SMS (consulta contínua · até {SMS_REENVIOS} reenvios a cada "
           f"{SMS_REENVIO_INTERVALO}s · troca de número aos {int(_espera_max)}s)...")

    _t_pausado = 0.0   # tempo total PARADO em troca de IP (não conta p/ o teto do número)
    # HEARTBEAT da espera. Depois do último reenvio o laço só fazia polling, SEM emitir
    # status() nenhum — e é o status() que atualiza o `_hb` que o Watchdog lê. Resultado:
    # aba saudável, apenas aguardando, era marcada como "travada (>10min sem avanço)" e
    # morta. Agora avisa o progresso a cada SMS_HB_INTERVALO.  (2026-09-07)
    _ultimo_hb = time.time()
    while True:
        # PAUSA NA TROCA DE IP (pedido do dono 2026-08-30): se há troca de IP pendente/
        # rolando, esta aba PARA aqui até o IP novo subir — mesmo aguardando SMS. O número
        # segue ativo (não cancela); o tempo parado é DESCONTADO do teto p/ não perder o
        # número por causa da pausa. Retoma o polling depois. No-op quando não há troca.
        try:
            from server.ip_rotation_coordinator import COORD as _IPCOORD
            if _IPCOORD.esta_pendente():
                status("⏸️ Troca de IP em andamento — pausando a espera do SMS até o IP novo subir...")
                _t0_pausa = time.time()
                _IPCOORD.checkpoint(alive_fn=lambda: _navegador_vivo(driver))
                _t_pausado += (time.time() - _t0_pausa)
        except Exception:
            pass

        decorrido = time.time() - inicio - _t_pausado

        # ── teto por número: cancela e devolve o controle p/ TROCAR DE NÚMERO/SERVIDOR ──
        if decorrido >= _espera_max:
            cancelado = _tentar_cancelar()
            status(f"⏱️ {int(decorrido)}s sem código — número "
                   f"{'CANCELADO (saldo devolvido)' if cancelado else 'não pôde ser cancelado'}"
                   f"; trocando de número.")
            return ''

        if not _navegador_vivo(driver):
            _tentar_cancelar()      # não deixa número pago para trás
            status('❌ Navegador foi fechado — abortando espera do SMS.')
            return ''

        _pv = _passo_fora_do_codigo(driver)
        if _pv:
            status(f"↩️ Tela saiu do código (→ '{_pv}') durante a espera — re-conduzindo o fluxo.")
            return _TELA_SAIU_DO_CODIGO

        # ── 1) consulta a API (curta, para o laço seguir respondendo) ──
        # O `t_poll` garante um piso de tempo por volta: se a chamada falhar na
        # hora (rede fora, erro do provedor), sem isso o laço giraria sem pausa
        # nenhuma martelando a API — e o teto de 5 min viraria milhares de
        # requisições em segundos.
        t_poll = time.time()
        try:
            r = sms.aguardar_codigo(ativacao_id, timeout=SMS_POLL_INTERVALO, intervalo=2)
        except Exception as e:
            logger.debug("[ProMax] aguardar_codigo erro: %s", e)
            r = {}
        _resto = SMS_POLL_INTERVALO - (time.time() - t_poll)
        if _resto > 0:
            time.sleep(_resto)
        if (r or {}).get('sucesso') and (r or {}).get('codigo'):
            status(f"📩 Código recebido em {int(time.time() - inicio)}s.")
            return str(r['codigo']).strip()

        # ── 1.5) sinal de vida p/ o Watchdog + visibilidade no terminal ──────────
        if time.time() - _ultimo_hb >= SMS_HB_INTERVALO:
            _ultimo_hb = time.time()
            status(f"⌛ {int(decorrido)}s sem código — aguardando "
                   f"({int(_espera_max - decorrido)}s até trocar de número).")

        # ── 2) aos 60s sem código: reenvio (até SMS_REENVIOS) ──────────────────
        if (reenvios < SMS_REENVIOS
                and time.time() - ultimo_reenvio >= SMS_REENVIO_INTERVALO):
            _pv2 = _passo_fora_do_codigo(driver)
            if _pv2:
                status(f"↩️ Tela saiu do código (→ '{_pv2}') — não reenvio, re-conduzindo.")
                return _TELA_SAIU_DO_CODIGO
            reenvios += 1
            status(f"🔁 {int(time.time() - inicio)}s sem SMS — pedindo reenvio "
                   f"({reenvios}º)...")
            # Reenvio TAMBÉM é pedido de código no IP compartilhado → passa pelo gate
            # anti-rajada (escalona entre abas do mesmo IP).
            try:
                from server.ip_rotation_coordinator import COORD as _IPCOORD
                _IPCOORD.sms_send_slot(alive_fn=lambda: _navegador_vivo(driver))
            except Exception:
                pass
            _click_texto(driver, ['Reenviar código', 'Reenviar', 'Resend code', 'Resend',
                                  'Reenviar código', 'Send again'], timeout=8)
            try:
                sms.solicitar_reenvio(ativacao_id)
            except Exception:
                pass
            ultimo_reenvio = time.time()


# ---------------------------------------------------------------------- #
# ENTRADA
# ---------------------------------------------------------------------- #
# Marcadores da Central de Segurança.
#  ESTRITO  = prova de que a empresa está QUALIFICADA (o botão que envia p/ análise).
#  NEGATIVO = prova do contrário ("Sua organização não precisa ser verificada" — é o
#             que a Central mostra quando NÃO há WABA/ativo que qualifique a BM).
#  FRACO    = pistas genéricas que também aparecem em cards de risco/segurança.
_CENTRAL_ESTRITO_TXT = [
    'iniciar verificação', 'iniciar verificacao',
    'qualificada para verificação', 'qualificada para verificacao',
    'continuar verificação', 'continuar verificacao',
    'start verification', 'continue verification',
    # verificação JÁ iniciada e pendente (run anterior interrompido): botão "Continuar"
    'envio pendente', 'continue de onde parou',
    'pending submission', 'continue where you left off',
    'iniciar verificación', 'envío pendiente',
]
_CENTRAL_NEGATIVO_TXT = [
    'não precisa ser verificada', 'nao precisa ser verificada',
    'não precisa ser verificado', 'nao precisa ser verificado',
    "doesn't need to be verified", 'does not need to be verified',
]
_CENTRAL_FRACO_TXT = [
    'começar', 'comece', 'ações necessárias', 'acoes necessarias',
    'get started', 'required actions', 'action required', 'empezar', 'acciones necesarias',
]


def _central_tem_botao_verificacao(driver, business_id):
    """True se a Central de Segurança mostra o botão de INICIAR/continuar a verificação
    da empresa (o que envia a BM p/ análise). Quando a WABA nasce DESABILITADA — ou
    quando NUNCA foi criada — esse botão NÃO aparece.

    (2026-08-17) FALSO POSITIVO corrigido: as pistas fracas ('Começar', 'Ações
    necessárias') existem nos cards de risco de QUALQUER Central, então a BM sem WABA
    era dada como qualificada e o fluxo entrava no loop de comprar SMS. Agora vale o
    marcador NEGATIVO ('Sua organização não precisa ser verificada'), que é a prova de
    que a empresa NÃO está qualificada."""
    try:
        _ir_para(driver, f"{BASE}/security_center?business_id={business_id}",
                 esperar=['security_center'], timeout=30)
        _esperar_estatico(driver, timeout=25)
    except Exception:
        pass
    # LEITURA PACIENTE (teste real 2026-10-05, #3266): o cartão "Business verification /
    # Start verification" renderiza DEPOIS do resto da Central (e some por alguns segundos
    # logo após alterar os dados da empresa). Uma leitura única dava "sem botão" com o
    # botão lá → o envio era abortado à toa. Agora relê por até ~40s (com 1 reload) antes
    # de concluir que não há botão. Marcador NEGATIVO continua decidindo na hora.
    t = ''
    for _volta in range(6):
        t = _texto_pagina_min(driver)
        if t:
            if any(k in t for k in _CENTRAL_ESTRITO_TXT):
                return True
            if any(k in t for k in _CENTRAL_NEGATIVO_TXT):
                logger.info("[ProMax] Central diz que a empresa NÃO precisa/não pode ser "
                            "verificada — sem botão de verificação.")
                return False
        if _volta == 2:
            try:
                _ir_para(driver, f"{BASE}/security_center?business_id={business_id}",
                         esperar=['security_center'], timeout=30)
                _esperar_estatico(driver, timeout=15)
            except Exception:
                pass
        else:
            time.sleep(6)
    if t:
        return any(k in t for k in _CENTRAL_FRACO_TXT)
    # Não deu p/ ler o texto: cai no teste antigo (mais tolerante).
    return _existe_texto(driver, _CENTRAL_ESTRITO_TXT + _CENTRAL_FRACO_TXT, timeout=8)


# ---------------------------------------------------------------------------
# RECURSO (Pedir análise) de WABA DESABILITADA por engano  (2026-07-25)
# ---------------------------------------------------------------------------
_BASE_FB = 'https://business.facebook.com'

# Texto do recurso. A WABA nova é desabilitada por engano (conta nunca usada);
# {nome} = razão social da BM, {waba_id} = ID da conta WhatsApp desativada.
_RECURSO_WABA_TEXTO = (
    "Solicito a revisão desta decisão. A conta do WhatsApp Business \"{nome}\" "
    "(ID: {waba_id}) foi desativada por engano. Trata-se de uma conta NOVA, "
    "recém-criada, que NUNCA foi utilizada — nenhuma mensagem foi enviada ou "
    "recebida, nenhuma conversa foi iniciada e nenhuma atividade comercial "
    "ocorreu. Não houve qualquer violação dos Termos de Serviço nem da Política "
    "Comercial do WhatsApp Business. Peço, respeitosamente, a reavaliação do caso "
    "e a restauração da conta. Obrigado."
)


def _fechar_popup_suporte(driver):
    """Fecha os popups PROMOCIONAIS (Meta AI/beta, 'Usernames are being rolled out'...)
    que abrem sobre a página de suporte — SEM clicar no CTA ('Start chat'/'Learn more'/
    'Iniciar'), que atrapalharia o recurso. Prefere 'Close'/'Fechar' e, senão, o X do
    topo (ícone sem texto). Idioma-agnóstico. Best-effort."""
    if _click_texto(driver, ['Fechar', 'Close', 'Agora não', 'Agora nao', 'Not now',
                             'Dispensar', 'Dismiss', 'Cerrar', 'Fermer'], timeout=2):
        _delay_curto()
        return True
    try:
        fechou = driver.evaluate_page(r"""() => {
            const vis = e => e && e.offsetParent !== null && e.getBoundingClientRect().width > 0;
            const dlgs = [...document.querySelectorAll('[role="dialog"]')]
                .filter(d => { const r = d.getBoundingClientRect(); return r.width > 120 && r.height > 120; });
            for (const d of dlgs) {
                const dr = d.getBoundingClientRect();
                // 1) botão com aria-label de FECHAR/dispensar (não é CTA)
                let x = [...d.querySelectorAll('[aria-label]')].find(b => vis(b)
                    && /close|fechar|cerrar|dismiss|descartar|fermer|schließen/i.test(b.getAttribute('aria-label') || ''));
                if (x) { x.click(); return true; }
                // 2) botão SEM texto (ícone X), pequeno, no topo-direito do modal.
                x = [...d.querySelectorAll('div[role=button],button')].filter(vis).find(b => {
                    const t = (b.innerText || '').trim(); const r = b.getBoundingClientRect();
                    return t.length === 0 && r.width < 64 && r.height < 64
                        && r.top < dr.top + 80 && r.right > dr.right - 80;
                });
                if (x) { x.click(); return true; }
            }
            return false;
        }""")
        if fechou:
            _delay_curto()
            return True
    except Exception:
        pass
    return False


def _preencher_textarea_recurso(driver, texto):
    """Preenche o textarea 'Insira qualquer detalhe...' do popup 'Pedir análise'
    (React-safe: native setter + eventos input/change). Retorna True se preencheu."""
    try:
        return bool(driver.evaluate_page(r"""(txt) => {
            const tas = [...document.querySelectorAll('textarea')].filter(e => e.offsetParent !== null);
            const ta = tas.find(e => /detalhe|análise|analise|review/i.test(e.placeholder||'')) || tas[0];
            if (!ta) return false;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
            setter.call(ta, txt);
            ta.dispatchEvent(new Event('input', {bubbles:true}));
            ta.dispatchEvent(new Event('change', {bubbles:true}));
            return true;
        }""", str(texto)))
    except Exception:
        return False


def recorrer_waba_desabilitada(driver, business_id, status=None, razao='', enviar_texto=True):
    """RECORRE (Pedir análise) uma conta WhatsApp (WABA) DESABILITADA por engano.

    Fluxo validado manualmente (2026-07-25) — reaproveita o navegador JÁ ABERTO/
    logado (NÃO fecha):
      1) abre o WhatsApp Manager (phone_numbers) da BM → tela 'Telefones' com a
         mensagem 'Conta desativada';
      2) segue o link 'Ver detalhes na Página Inicial do Suporte para Empresas'
         (href business-support-home/<biz>/<waba>) — navega na MESMA aba;
      3) fecha o popup promocional (X/'Fechar');
      4) clica 'Pedir análise' → preenche o texto do recurso (opcional) → 'Enviar';
      5) aguarda o botão 'OK' habilitar e clica → WABA fica EM ANÁLISE.

    Retorna True se enviou o recurso. Best-effort: nunca relança (não pode quebrar
    o fluxo do retry)."""
    def _s(m):
        if status:
            try:
                status(m)
            except Exception:
                pass

    bid = str(business_id or '').strip()
    if not bid:
        return False
    try:
        # ── LAÇO 30s / 5min (pedido do dono 2026-09-26): a WABA recém-desabilitada
        # cai na Página de Suporte, mas o botão 'Solicitar análise' ('Pedir análise'/
        # 'Request review') às vezes leva MINUTOS p/ a Meta liberar. Uma tentativa única
        # marcava "recorrida" SEM ter recorrido. Agora REABRE a página de suporte a cada
        # 30s por até 5min até o botão aparecer e ser clicado.
        import time as _t
        _fim_loop = _t.time() + 5 * 60
        _tent = 0
        _abriu_pedir = False
        while _t.time() < _fim_loop:
            _tent += 1
            _s(f"📝 Recurso: abrindo a Página de Suporte p/ 'Solicitar análise' (tentativa {_tent} · F5/30s até 5min)...")
            # 1) WhatsApp Manager (Telefones) da BM.
            _ir_para(driver, f"{_BASE_FB}/latest/whatsapp_manager/phone_numbers/?business_id={bid}",
                     esperar=['whatsapp_manager', 'phone_numbers'], timeout=35)
            _esperar_estatico(driver, timeout=16)
            # 2) segue o link de suporte (href business-support-home) na MESMA aba.
            _url_sup = None
            try:
                _url_sup = driver.evaluate_page(r"""() => {
                    const a = [...document.querySelectorAll('a[href*="business-support-home"]')]
                        .find(e => e.href && e.href.indexOf('business-support-home') !== -1);
                    return a ? a.href : null;
                }""")
            except Exception:
                pass
            if _url_sup:
                _ir_para(driver, _url_sup, esperar=['business-support-home'], timeout=35)
            else:
                if not _click_texto(driver, [
                        'Ver detalhes na Página Inicial do Suporte',
                        'Ver detalhes na Pagina Inicial do Suporte',
                        'Página Inicial do Suporte para Empresas',
                        'See details in Business Support Home', 'Business Support Home',
                        'See details', 'View details', 'Entrar em contato'], timeout=6):
                    _aid = ''
                    try:
                        _aid = driver.evaluate_page(r"""() => { const m=(location.search||'').match(/asset_id=(\d+)/); return m?m[1]:''; }""") or ''
                    except Exception:
                        pass
                    if _aid:
                        _ir_para(driver, f"{_BASE_FB}/business-support-home/{bid}/{_aid}/",
                                 esperar=['business-support-home'], timeout=35)
            _esperar_estatico(driver, timeout=16)
            # 3) fecha o popup promocional (se aparecer).
            _fechar_popup_suporte(driver)
            _delay_curto()
            # 4) tenta o botão 'Solicitar análise' / 'Pedir análise' / 'Request review'.
            if _clicar_botao_robusto(driver, ['Pedir análise', 'Pedir analise',
                                              'Solicitar análise', 'Solicitar analise',
                                              'Request review', 'Request a review'], timeout=8):
                _abriu_pedir = True
                break
            _restante = int(max(0, _fim_loop - _t.time()))
            _s(f"⏳ Recurso: 'Solicitar análise' ainda indisponível — reabrindo em 30s (faltam ~{_restante}s).")
            _t.sleep(min(30, max(1, _restante)))
        if not _abriu_pedir:
            _s("⚠️ Recurso: 'Solicitar análise' NÃO apareceu em 5min — recurso NÃO enviado.")
            return False
        _esperar_estatico(driver, timeout=12)

        # texto do recurso (opcional) — com o ID da WABA.
        if enviar_texto:
            try:
                _waba_id = ''
                try:
                    _waba_id = driver.evaluate_page(r"""() => {
                        const m = (location.pathname||'').match(/business-support-home\/\d+\/(\d+)/);
                        return m ? m[1] : '';
                    }""") or ''
                except Exception:
                    pass
                _txt = _RECURSO_WABA_TEXTO.format(nome=(razao or 'da empresa'),
                                                  waba_id=(_waba_id or bid))
                if _preencher_textarea_recurso(driver, _txt):
                    _s("✍️ Recurso: texto de contestação preenchido.")
            except Exception as _e:
                logger.warning('[Recurso] preencher texto falhou: %s', _e)

        # 5) ENVIAR o recurso: 'Enviar' (PT) / 'Submit' (EN) / 'Enviar solicitação'...
        #    Em inglês o diálogo 'Request review' usa **Submit**.
        #    ⚠️ NÃO chamar _fechar_popup_suporte aqui: o diálogo do recurso É um
        #    [role=dialog] e seria FECHADO por engano (bug 2026-09-26). O pop-up
        #    promocional já foi dispensado no laço, antes de abrir 'Request review'.
        if not _clicar_botao_robusto(driver, ['Enviar', 'Send', 'Submit', 'Enviar solicitação',
                                              'Enviar solicitacao', 'Send request', 'Enviar análise',
                                              'Enviar analise', 'Enviar avaliação'], timeout=12):
            _s("⚠️ Recurso: botão 'Enviar/Submit' não encontrado.")
            return False

        # aguarda o 'OK' habilitar e clica (o botão fica desabilitado alguns segundos).
        # Em inglês o diálogo final é "You'll hear from us soon" com **OK**.
        _fim = time.time() + 30
        _ok = False
        while time.time() < _fim:
            if _clicar_botao_robusto(driver, ['OK', 'Ok', 'Concluir', 'Done', 'Entendi', 'Got it'], timeout=3):
                _ok = True
                break
            time.sleep(1)
        _s("✅ Recurso enviado — WABA EM ANÁLISE (aguardando a Meta reavaliar)."
           if _ok else "✅ Recurso enviado (Pedir análise).")
        return True
    except Exception as e:
        logger.warning('[Recurso] recorrer_waba_desabilitada falhou: %s', e)
        try:
            _s("⚠️ Recurso: falha ao enviar (seguindo o fluxo mesmo assim).")
        except Exception:
            pass
        return False


_WABA_DESABILITADA_TXT = [
    'conta desabilitada', 'conta desativada', 'account disabled',
    'não cumpre as diretrizes', 'nao cumpre as diretrizes',
    'not follow our policies', 'não cumpre a política', 'nao cumpre a politica',
    # EN (tela 'Account status: Disabled' + motivo) — 2026-09-26
    "doesn't meet our policy guidelines", 'does not meet our policy guidelines',
    "doesn't meet our policies", 'does not meet our policies',
    "doesn't comply with our", 'not in compliance with our',
    # PT (e-mail/página: "atividades que não estão em conformidade com a Política Comercial")
    'não está em conformidade', 'nao esta em conformidade',
    'não estão em conformidade', 'nao estao em conformidade',
    # ES / palavras de "desabilitado" em outros idiomas
    'cuenta inhabilitada', 'cuenta deshabilitada', 'no cumple con nuestras',
    'conta desativada permanentemente', 'ha sido inhabilitada',
]

# Palavras que significam "desabilitado/desativado/restrito" em vários idiomas — usadas
# SÓ na página whatsapp_account (contexto inequívoco), junto do rótulo "Account status".
_STATUS_DESABILITADO_PALAVRAS = [
    'disabled', 'desabilitad', 'desativad', 'inhabilitad', 'deshabilitad',
    'desactivad',
]
_STATUS_ROTULO = [
    'account status', 'status da conta', 'estado da conta', 'estado de la cuenta',
    'estado de tu cuenta', 'statut du compte',
]
# Palavras de "restrito/restringido" (WABA RESTRITA, NÃO desabilitada). A restrição
# não DESATIVA a conta → o fluxo pode seguir direto p/ a análise, sem esperar o monitor
# (pedido do dono 2026-09-27). Usadas SÓ nesta página, junto do rótulo "Status da conta".
_STATUS_RESTRITA_PALAVRAS = [
    'restricted', 'restrict', 'restrita', 'restrito', 'restring', 'restringi',
]
_WABA_AUSENTE_TXT = [
    'nenhuma conta do whatsapp adicionada', 'nenhuma conta do whatsapp',
    'no whatsapp accounts', 'no whatsapp business accounts',
]


def _texto_pagina_min(driver):
    """innerText da página em minúsculas (barato; '' se não der para ler)."""
    try:
        t = (driver.evaluate_page(
            "() => (document.body && document.body.innerText) || ''") or '').lower()
    except Exception:
        return ''
    try:  # conta fora do pt: soma a tradução pt-BR do primeiro plano
        from server.tradutor_tela import com_traducao
        return com_traducao(driver, t)
    except Exception:
        return t


def _ler_estado_conta_whatsapp(driver, business_id, timeout=14):
    """Estado da conta do WhatsApp (WABA) do portfólio, lido em 'Contas do WhatsApp'.

    Retorna:
      'desabilitada' → a WABA existe mas a Meta derrubou ('Conta desabilitada /
                       não cumpre as diretrizes') → é BLOQUEIO (2ª BM).
      'restrita'     → status "Restricted/Restrita" — a WABA está restrita mas NÃO
                       desativada; NÃO é bloqueio → segue direto p/ a análise.
      'ausente'      → NÃO existe WABA nenhuma ('Nenhuma conta do WhatsApp
                       adicionada') → o CRM não criou; NÃO é bloqueio: dá para
                       criar a WABA e seguir (nunca gastar a 2ª BM por isso).
      'ok'           → existe ao menos uma WABA aparentemente saudável.
      'desconhecido' → a tela não carregou/não foi reconhecida — NUNCA decide nada.

    (2026-08-17) Antes só existia o teste 'desabilitada'; a WABA AUSENTE ficava
    indistinguível de 'tela não reconhecida' e o fluxo seguia comprando SMS numa BM
    que jamais teria o botão 'Iniciar verificação'.
    """
    try:
        _ir_para(driver, f"{BASE}/whatsapp_account/?business_id={business_id}",
                 esperar=['whatsapp_account'], timeout=25)
        _esperar_estatico(driver, timeout=20)
    except Exception:
        pass
    fim = time.time() + max(4, timeout)
    while time.time() < fim:
        try:  # pop-up "Updates to your account" (nova estrutura WhatsApp) sobre a lista
            from server.waba import dispensar_popup_atualizacao_whatsapp
            dispensar_popup_atualizacao_whatsapp(driver, tentativas=2)
        except Exception:
            pass
        t = _texto_pagina_min(driver)
        if t:
            if any(k in t for k in _WABA_DESABILITADA_TXT):
                return 'desabilitada'
            # Contextual (idioma-agnóstico): nesta página (whatsapp_account) o rótulo
            # "Account status"/"Status da conta" + uma palavra de desabilitado perto
            # ("Disabled"/"Desabilitado"/"Inhabilitada"...) = WABA caiu. Cobre
            # "Account status: Disabled" (EN) sem depender da frase-motivo. (2026-09-26)
            if (any(r in t for r in _STATUS_ROTULO)
                    and any(p in t for p in _STATUS_DESABILITADO_PALAVRAS)):
                return 'desabilitada'
            # Contextual: "Status da conta: Restricted/Restrita" — WABA RESTRITA (não
            # desabilitada). A restrição NÃO desativa a conta → o monitor não precisa
            # esperar; o fluxo segue direto p/ a análise (pedido do dono 2026-09-27).
            # Checada DEPOIS de 'desabilitada' (desabilitada tem prioridade).
            if (any(r in t for r in _STATUS_ROTULO)
                    and any(p in t for p in _STATUS_RESTRITA_PALAVRAS)):
                return 'restrita'
            if any(k in t for k in _WABA_AUSENTE_TXT):
                return 'ausente'
            if 'contas do whatsapp' in t or 'whatsapp accounts' in t:
                # A tela renderizou e não é a vazia → tem linha de conta na lista.
                try:
                    n = driver.evaluate_page(
                        """() => document.querySelectorAll('[role="row"],[role="listitem"]').length""")
                    if n and int(n) > 0:
                        return 'ok'
                except Exception:
                    pass
        time.sleep(0.5)
    return 'desconhecido'


def _estado_conta_whatsapp(driver, business_id, timeout=14):
    """Idem `_ler_estado_conta_whatsapp`, mas CONFIRMA o veredito 'ausente' com uma
    segunda leitura. Motivo: 'ausente' é caro (dispara re-execução do CRM) e a tela
    pode renderizar o estado vazio por um instante enquanto a lista carrega."""
    est = _ler_estado_conta_whatsapp(driver, business_id, timeout=timeout)
    if est != 'ausente':
        return est
    time.sleep(3)
    est2 = _ler_estado_conta_whatsapp(driver, business_id, timeout=timeout)
    if est2 != 'ausente':
        logger.info("[ProMax] 'Nenhuma conta do WhatsApp' era transitório — estado real: %s", est2)
    return est2


def _conta_whatsapp_desabilitada(driver, business_id):
    """True se a Conta do WhatsApp (WABA) está DESABILITADA — 'Conta desabilitada /
    não cumpre as diretrizes'. É a causa de a Central ficar sem o botão de verificação."""
    return _estado_conta_whatsapp(driver, business_id) == 'desabilitada'


def _diagnostico_bm(driver, business_id, status=None, checar_waba=True):
    """Por que esta BM não está verificando? Diagnóstico BARATO e SEGURO de rodar
    ENTRE tentativas (sem modal aberto). É o FREIO do loop infinito de SMS.

    Retorna {'restrita': bool, 'waba': 'ok'|'ausente'|'desabilitada'|'desconhecido'|'ignorado'}
    """
    def _s(m):
        if status:
            try:
                status(m)
            except Exception:
                pass

    diag = {'restrita': False, 'waba': 'ignorado'}
    try:
        diag['restrita'] = bool(_bm_bloqueada_para_anuncios(driver, business_id, _s))
    except Exception as e:
        logger.warning('[ProMax] diagnóstico (restrição) falhou: %s', e)
    if diag['restrita']:
        return diag          # restrição manda: nem precisa olhar a WABA
    if checar_waba:
        try:
            diag['waba'] = _estado_conta_whatsapp(driver, business_id)
        except Exception as e:
            logger.warning('[ProMax] diagnóstico (WABA) falhou: %s', e)
            diag['waba'] = 'desconhecido'
    return diag


def _popup_perfis_presente(driver):
    """True se o coachmark 'Alternar entre seus perfis de usuário' está na tela."""
    try:
        return bool(driver.evaluate_page(r"""() => {
            const t = ((document.body && document.body.innerText) || '').toLowerCase();
            return t.includes('alternar entre seus perfis')
                || t.includes('switch between your user profiles')
                || t.includes('alterne entre seus perfis');
        }"""))
    except Exception:
        return False


def _dispensar_popup_perfis(driver):
    """Fecha o coachmark 'Alternar entre seus perfis de usuário' que fica SOBRE o
    botão 'Adicionar' — o bot mexia a tela mas NÃO clicava (relato do usuário
    2026-07-08). Localiza a RAIZ do popup e clica em 'Concluir' (ou no X). VERIFICA
    que sumiu e re-tenta algumas vezes. Fallback Playwright no 'Concluir'."""
    if not _popup_perfis_presente(driver):
        return False
    for _ in range(4):
        try:
            driver.evaluate_page(r"""() => {
                const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
                const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
                                   return r.width>0 && r.height>0 && e.offsetParent!==null; };
                const alvos = ['alternar entre seus perfis','switch between your user profiles',
                               'alterne entre seus perfis'];
                // raiz = menor elemento visível que contém o texto-âncora
                let root=null, best=1e9;
                for (const el of document.querySelectorAll('div,section')){
                    if (!vis(el)) continue;
                    const t = norm(el.innerText);
                    if (alvos.some(a=>t.includes(a)) && t.length<best){ best=t.length; root=el; }
                }
                if (!root) return false;
                // sobe alguns níveis p/ englobar o X (às vezes fora do bloco de texto)
                let pop=root;
                for (let i=0;i<5 && pop.parentElement;i++){
                    const p=pop.parentElement;
                    if (norm(p.innerText).length > best+250) break;
                    pop=p;
                }
                // 1) botão 'Concluir'/'Done' do popup
                const conc=[...pop.querySelectorAll('div[role=button],button,span[role=button],a[role=button]')]
                    .find(b=>vis(b)&&['concluir','done','finish','ok','entendi','got it'].includes(norm(b.innerText)));
                if (conc){ conc.click(); return true; }
                // 2) X por aria-label
                const x=[...pop.querySelectorAll('[aria-label]')].find(b=>vis(b)&&
                    ['fechar','close','dispensar','dismiss'].some(k=>norm(b.getAttribute('aria-label')).includes(k)));
                if (x){ x.click(); return true; }
                // 3) botão SEM texto mais à direita/no topo (o X do canto)
                const cand=[...pop.querySelectorAll('[role=button],button,i')]
                    .filter(b=>vis(b)&&norm(b.innerText)==='')
                    .sort((a,b)=>{const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();
                                  return (rb.right-ra.right)||(ra.top-rb.top);});
                if (cand.length){ cand[0].click(); return true; }
                return false;
            }""")
        except Exception:
            pass
        _delay_curto()
        if not _popup_perfis_presente(driver):
            return True
    # Fallback Playwright: clique REAL no 'Concluir' (nesta tela só existe o do popup).
    if _popup_perfis_presente(driver):
        _click_texto(driver, ['Concluir', 'Done'], exato=True, timeout=3)
    return not _popup_perfis_presente(driver)


def _preencher_nome_conta_anuncios(driver, nome):
    """Preenche o campo 'Nome da conta de anúncios' DENTRO DO MODAL — NUNCA a busca
    da página ('Pesquisar por nome ou ID'), que era o BUG (o nome ia parar na busca).
    Localiza o input pela proximidade do rótulo (ou dentro do dialog), marca-o e usa
    o fill do Playwright (dispara eventos React). Retorna True se o valor foi aplicado."""
    try:
        marcou = driver.evaluate_page(r"""() => {
            const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
            document.querySelectorAll('input[data-gs-nome]').forEach(e=>e.removeAttribute('data-gs-nome'));
            const ehBusca = x => norm(x.placeholder).includes('pesquisar') || norm(x.getAttribute('aria-label')).includes('pesquisar');
            const bom = x => x.offsetParent!==null && !ehBusca(x) && (x.type==='text' || x.type==='' || !x.type);
            // 1) input logo abaixo do rótulo "Nome da conta de anúncios"
            const labs = [...document.querySelectorAll('span,div,label')]
                .filter(e => { const t=norm(e.innerText); return t==='nome da conta de anúncios' || t==='nome da conta de anuncios' || t==='ad account name'; });
            for (const lab of labs){
                let node = lab.parentElement;
                for (let i=0;i<6 && node;i++){
                    const inp = [...node.querySelectorAll('input')].find(bom);
                    if (inp){ inp.setAttribute('data-gs-nome','1'); return true; }
                    node = node.parentElement;
                }
            }
            // 2) fallback: 1º input de texto (não-busca) dentro de um dialog
            const dlg = document.querySelector('[role="dialog"]') || document;
            const inp = [...dlg.querySelectorAll('input')].find(bom);
            if (inp){ inp.setAttribute('data-gs-nome','1'); return true; }
            return false;
        }""")
        if not marcou:
            return False
        _preencher(driver, 'input[data-gs-nome="1"]', nome, timeout=8)
        val = driver.evaluate_page(r"""() => {
            const e = document.querySelector('input[data-gs-nome="1"]');
            return e ? (e.value||'') : '';
        }""")
        return bool(val and nome[:8].lower() in str(val).lower())
    except Exception as e:
        logger.debug("[ContaAnuncios] preencher nome falhou: %s", e)
        return False


def _marcar_checkbox_termos(driver):
    """Marca o checkbox 'Concordo com os Termos' da tela de confirmação (o botão
    'Criar conta de anúncios' só ativa depois)."""
    if _click_seletor(driver, 'input[type="checkbox"]:not([aria-checked="true"]), '
                              '[role="checkbox"][aria-checked="false"]', timeout=4):
        return True
    try:
        return bool(driver.evaluate_page(r"""() => {
            const cbs = [...document.querySelectorAll('input[type=checkbox], [role=checkbox]')]
                .filter(c => c.offsetParent !== null);
            for (const c of cbs){
                const marcado = c.getAttribute('aria-checked') === 'true' || c.checked === true;
                if (!marcado){ c.click(); return true; }
            }
            return false;
        }"""))
    except Exception:
        return False


def _detectar_tela_conta_anuncios(driver):
    """Detecta a tela ATUAL do fluxo de criar conta de anúncios (após 100% estática).
    Ordem do mais específico p/ o mais genérico. Retorna:
    'sucesso'|'confirmar'|'uso'|'detalhes'|'menu_add'|'lista'|None."""
    try:
        return driver.evaluate_page(r"""() => {
            const t = ((document.body && document.body.innerText) || '').toLowerCase();
            const has = (...xs) => xs.some(x => t.includes(x));
            if (has('você não pode usar este portfólio empresarial para anunciar',
                    'voce nao pode usar este portfolio empresarial para anunciar',
                    "you can't use this business portfolio to advertise",
                    'não é possível usar a empresa','nao e possivel usar a empresa')) return 'bloqueada';
            if (has('criada com sucesso','created successfully','conta de anúncios criada com sucesso')) return 'sucesso';
            if (has('confirme a conta de anúncios','confirme a conta de anuncios','confirm the ad account you')
                || (has('concordo com os') && has('criar conta de anúncios','criar conta de anuncios','create ad account'))) return 'confirmar';
            if (has('selecione quem usará','selecione quem usara','quem usará esta conta','who will use this ad account')) return 'uso';
            if ((has('nome da conta de anúncios','nome da conta de anuncios','ad account name'))
                && has('fuso horário','fuso horario','time zone','moeda','currency')) return 'detalhes';
            if (has('adicionar uma conta de anúncios','adicionar uma conta de anuncios','add an ad account')
                && has('criar uma nova conta de anúncios','criar uma nova conta de anuncios','create a new ad account')) return 'menu_add';
            if (has('contas de anúncios','contas de anuncios','ad accounts')) return 'lista';
            return null;
        }""")
    except Exception:
        return None


def _criar_conta_anuncios_para_liberar_verificacao(driver, business_id, empresa_dados, status):
    """Cria uma conta de anúncios como MÁQUINA DE ESTADOS ROBUSTA (reescrito do zero
    2026-07-08 a pedido do usuário — o fluxo antigo clicava às cegas, digitava o nome
    na BUSCA da página e falava 'criou' sem ter criado).

    A cada ciclo: (1) espera a página ficar 100% ESTÁTICA; (2) DISPENSA o popup
    'Alternar entre seus perfis' que cobria o 'Adicionar'; (3) DETECTA qual tela está
    na frente; (4) executa SÓ a ação daquela tela. Seletores dos prints do usuário:
    Adicionar → 'Criar uma nova conta de anúncios' (id=js_ax) → nome no campo do MODAL
    (id=js_bp, nunca a busca) → Avançar → 'Minha empresa' (padrão) → Avançar → aceitar
    termos (id=js_cv) → 'Criar conta de anúncios' → 'Concluir'.

    Retorna True SOMENTE se a tela 'Conta de anúncios criada com sucesso' apareceu."""
    nome_conta = (str((empresa_dados or {}).get('razao_social') or '').strip()
                  or str((empresa_dados or {}).get('nome_fantasia') or '').strip()
                  or ('Conta ' + str(business_id)[:10]))
    nome_conta = nome_conta[:50]
    try:
        _ir_para(driver, f"{BASE}/ad_accounts?business_id={business_id}",
                 esperar=['ad_accounts'], timeout=25)
    except Exception:
        pass

    _criado = False
    _nome_ok = False
    _ultimo = None
    _rep = 0
    fim = time.time() + 200
    while time.time() < fim:
        # 0) navegador fechado? aborta.
        if not _navegador_vivo(driver):
            status("❌ Navegador fechado durante a criação da conta de anúncios.")
            return False
        # 1) PÁGINA 100% ESTÁTICA antes de detectar/agir (nunca clica às cegas).
        try:
            _esperar_estatico(driver, timeout=20)
        except Exception:
            pass
        # 2) dispensa o popup 'Alternar entre seus perfis'/coachmarks (bloqueiam cliques).
        if _dispensar_popup_perfis(driver):
            _delay_curto()
        # 3) DETECTA a tela atual.
        tela = _detectar_tela_conta_anuncios(driver)
        if tela == _ultimo:
            _rep += 1
        else:
            _rep = 0
            _ultimo = tela
        if _rep > 9:
            try:
                from server.screen_capture import capturar_tela_desconhecida
                capturar_tela_desconhecida(driver, contexto='criar_conta_anuncios',
                                           motivo=f'preso_{tela}')
            except Exception:
                pass
            status(f"⚠️ Preso na tela '{tela}' da criação de conta de anúncios.")
            return _criado
        # 4) AÇÃO específica da tela ATUAL.
        if tela == 'bloqueada':
            # Hard-lock: "Você não pode usar este portfólio para anunciar" — a conta
            # de anúncios NÃO pode ser criada. Sai já (o chamador trata como bloqueio).
            status("⛔ Contas de anúncios BLOQUEADA — não dá p/ criar a conta aqui.")
            return False
        if tela == 'sucesso':
            _criado = True
            status("✅ Conta de anúncios criada com sucesso — clicando 'Concluir'.")
            if not _click_seletor(driver, '[data-surface*="create-ad-account-complete-step-done-button"]', timeout=8):
                _click_texto(driver, ['Concluir', 'Done', 'Finish'], timeout=8)
            _delay_medio()
            return True
        elif tela == 'confirmar':
            status("📝 Confirmar: aceitando os termos e criando a conta...")
            _marcar_checkbox_termos(driver)
            _delay_curto()
            if not _click_seletor(driver, '[data-surface*="add-asset-confirm-button"]', timeout=8):
                _click_texto(driver, ['Criar conta de anúncios', 'Criar conta de anuncios',
                                      'Create ad account'], timeout=8)
            _delay_medio()
        elif tela == 'uso':
            status("👤 Uso: 'Minha empresa' (padrão) → Avançar.")
            if not _click_seletor(driver, '[data-surface*="create-adaccount-usage-next-button"]', timeout=6):
                _click_texto(driver, ['Avançar', 'Avancar', 'Next'], timeout=8)
            _delay_medio()
        elif tela == 'detalhes':
            if not _nome_ok:
                _nome_ok = _preencher_nome_conta_anuncios(driver, nome_conta)
                if _nome_ok:
                    status(f"🧾 Detalhes: nome '{nome_conta}' preenchido (Fuso/Moeda padrão).")
                else:
                    status("↻ Detalhes: reencontrando o campo 'Nome da conta de anúncios'...")
            _delay_curto()
            # Avançar só habilita após o nome; se ainda não preencheu, o clique não
            # avança e o loop re-tenta o preenchimento (nunca fica clicando às cegas).
            if _nome_ok:
                if not _click_seletor(driver, '[data-surface*="create-adaccount-info-next-button"]', timeout=6):
                    _click_texto(driver, ['Avançar', 'Avancar', 'Next'], timeout=8)
            _delay_medio()
        elif tela == 'menu_add':
            status("➕ Menu: 'Criar uma nova conta de anúncios'.")
            if not _click_seletor(driver, '#js_ax', timeout=4):
                _click_texto(
                    driver,
                    ['Criar uma nova conta de anúncios', 'Criar uma nova conta de anuncios',
                     'Create a new ad account'],
                    seletor_base=('div[role="gridcell"], div[role="button"], [role="row"], '
                                  'div[role="listitem"], span, div, label'),
                    timeout=8)
            _delay_medio()
        elif tela == 'lista':
            status("➕ Contas de anúncios: clicando 'Adicionar'.")
            # O popup 'Alternar entre seus perfis' cobre o botão — dispensa PRIMEIRO
            # (verifica que sumiu) e só então clica; senão o clique não pega.
            _dispensar_popup_perfis(driver)
            _delay_curto()
            _ok = _click_texto(driver, ['Adicionar', 'Add'], exato=True, timeout=6)
            if not _ok:
                _ok = _click_seletor(driver, '[data-surface*="add-asset-by-asset-type"]', timeout=4)
            if not _ok:
                # Fallback: clique via JS direto no botão 'Adicionar' (o menu abre).
                try:
                    driver.evaluate_page(r"""() => {
                        const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
                        const b = [...document.querySelectorAll('div[role="button"],button,a[role="button"]')]
                            .find(x => x.offsetParent!==null && (norm(x.innerText)==='adicionar' || norm(x.innerText)==='add'));
                        if (b){ b.click(); return true; }
                        return false;
                    }""")
                except Exception:
                    pass
            _delay_medio()
        else:
            # tela ainda não reconhecida (carregando) — espera mais um pouco.
            _delay_curto()
    status("⚠️ Timeout no fluxo de criação de conta de anúncios.")
    return _criado


def executar_etapa_verificacao_negocio(driver, empresa_dados, business_id, site_id,
                                       callback_status=None, captcha_token='',
                                       tipo_empresa='mei', sms24h_token='',
                                       fb_login='', fb_senha='', fb_tfa='',
                                       fb_email='', fb_email_senha='', bm_email='',
                                       sem_waba=False, ignorar_restricao=False,
                                       bloquear_se_sem_botao=False,
                                       sms_provedor=PROVEDOR_PADRAO,
                                       sms_tokens=None, metodo_verificacao='dominio',
                                       site_url=''):
    """Executa a verificação de NEGÓCIO (envia a BM para análise).

    `ignorar_restricao=True` (GS Prime Plus, 2026-07-08): NÃO aborta pela restrição
    de anúncios — o usuário confirmou que a restrição de BM nova NÃO impede a
    verificação (costuma cair depois). O hard-lock real já é tratado antes (o
    chamador só chega aqui quando dá p/ criar a conta + tem 'Iniciar verificação').

    `bloquear_se_sem_botao=True` (Pro Max Gupshup/DataCrazy, 2026-07-25): após criar
    a WABA, se a Central de Segurança NÃO exibir 'Iniciar verificação' (nem destravar
    criando conta de anúncios), a WABA nasceu DESABILITADA → retorna bm_bloqueada=True
    + waba_desabilitada=True (sem gastar SMS/certificado). O backend usa esse sinal
    p/ criar a 2ª BM (nova empresa) e refazer o fluxo — cada perfil tem no máx 2 BMs.

    Returns dict {'sucesso','em_analise','bm_bloqueada','mensagem','tentativas'}.
    'sucesso' = chegou em "Em análise".

    `precisa_criar_waba=True` (2026-08-17): a BM NÃO tem conta do WhatsApp (WABA
    nunca criada) e NÃO está restrita → não é bloqueio e a 2ª BM não resolve. O
    chamador deve criar a WABA pelo MÉTODO ESCOLHIDO NA GUI (DataCrazy/Gupshup) e
    chamar esta função de novo. Enquanto isso NADA é gasto (sem SMS/certificado).

    O número/SMS é comprado DIRETO no sms24h com o `sms24h_token` do usuário.
    `fb_login`/`fb_senha`/`fb_tfa`: credenciais do perfil para RE-LOGIN automático
    caso a sessão caia ao navegar no business.facebook.com durante a verificação.

    A verificação da empresa é SEMPRE por DOMÍNIO (a opção por e-mail foi removida
    em 2026-07-31 — a Meta valida o domínio no servidor e devolvia 500 ao forçar o
    subdomínio no e-mail comercial).
    """
    def status(msg):
        logger.info("[ProMax] %s", msg)
        if callback_status:
            try:
                callback_status(msg)
            except Exception:
                pass

    # Disponibiliza credenciais + callback no driver para _ir_para/_tratar_interrupcao_fb
    # (re-login automático + checkpoint 'Ignorar' ao navegar).
    try:
        driver._pm_status = status
        driver._pm_fb_login = fb_login or ''
        driver._pm_fb_senha = fb_senha or ''
        driver._pm_fb_tfa = fb_tfa or ''
        # Mantém credenciais do e-mail (p/ a tela de código por e-mail no re-login);
        # não sobrescreve com vazio se já tiverem sido setadas no login inicial.
        driver._pm_fb_email = fb_email or getattr(driver, '_pm_fb_email', '') or ''
        driver._pm_fb_email_senha = fb_email_senha or getattr(driver, '_pm_fb_email_senha', '') or ''
    except Exception:
        pass

    res = {'sucesso': False, 'em_analise': False, 'bm_bloqueada': False,
           'mensagem': '', 'tentativas': 0}

    empresa_dados = empresa_dados or {}
    business_id = str(business_id or '').strip()
    if not business_id:
        res['mensagem'] = 'business_id ausente — não dá para verificar o negócio.'
        status('❌ ' + res['mensagem'])
        return res
    if not _TEM_ACESSO:
        res['mensagem'] = 'Integração do certificado (painel/Dompdf) indisponível.'
        status('❌ ' + res['mensagem'])
        return res
    # ── MODO SMS CENTRAL: número via painel, cobrado do saldo REAL do usuário ──
    _modo_painel = bool(_SMS_CENTRAL)
    _client_painel = None
    if _modo_painel:
        try:
            from server.panel_sms_client import PanelSmsClient
            _client_painel = PanelSmsClient(callback_status=status)
        except Exception as _e_pc:
            logger.error("[ProMax] PanelSmsClient indisponível (%s) — caindo no modo local.", _e_pc)
            _modo_painel = False

    if _modo_painel:
        _nome_prov = 'GS SMS'
        sms_provedor = 'painel'
    else:
        _nome_prov = nome_do_provedor(sms_provedor)
        if not (_TEM_SMS24H and str(sms24h_token or '').strip()):
            res['mensagem'] = (f'Token do {_nome_prov} ausente — informe o token na GUI '
                               f'para comprar o número de SMS.')
            status('❌ ' + res['mensagem'])
            return res

    # ── FILA DE PROVEDORES (fallback A → B → C) ───────────────────────────────
    # O provedor ESCOLHIDO na GUI é o primeiro; os demais que tiverem token entram
    # como reserva. Se o número de um não receber o SMS, a próxima tentativa compra
    # no PRÓXIMO provedor — em vez de insistir no mesmo pool que não entrega.
    # Motivo (medido em 2026-08-03): cada provedor tem UMA faixa de preço por
    # serviço/país (não dá para "comprar um número melhor" dentro do mesmo); o que
    # muda a taxa de entrega é o PROVEDOR. fb/Brasil: Tiger US$0,020 (24 mil),
    # Grizzly US$0,063 (18,4 mi), SMS24h ~R$0,80 (170 mil).
    if _modo_painel:
        # Serviço central = 1 "provedor" (o painel); o fallback entre servidores é
        # INTERNO ao PanelSmsClient (fonte oculta). A fila tem 1 entrada só.
        _fila = [('painel', 'painel')]

        def _cliente_da_vez(indice):
            return 'painel', 'GS SMS', _client_painel
    else:
        _tokens = dict(sms_tokens or tokens_configurados())
        _tokens.setdefault(sms_provedor, str(sms24h_token).strip())
        _fila = montar_fila_provedores(sms_provedor, _tokens)
        if not _fila:
            _fila = [(sms_provedor, str(sms24h_token).strip())]

        def _cliente_da_vez(indice):
            """Provedor da posição `indice` (0-based) da fila."""
            prov, tok = _fila[indice % len(_fila)]
            return prov, nome_do_provedor(prov), criar_cliente_sms(tok, prov)

    # Provedores QUEIMADOS nesta verificação: não entregaram o SMS, não tinham
    # saldo, deram erro ou estavam fora. Nunca voltam a ser tentados aqui.
    _prov_reprovados = {}

    def _proximo_provedor(idx_atual):
        """Próxima posição da fila ainda não reprovada (None se acabaram)."""
        for _k in range(1, len(_fila) + 1):
            _c = (idx_atual + _k) % len(_fila)
            if _fila[_c][0] not in _prov_reprovados:
                return _c
        return None

    # ── ÚLTIMO RECURSO: serviço 'ot' (qualquer SMS) ────────────────────────────
    # Por que existe: o código da CRIAÇÃO de conta chega normalmente, mas o da
    # VERIFICAÇÃO DA BM não chega em provedor nenhum. A explicação que bate com
    # isso é o FILTRO POR REMETENTE: ao vender o serviço 'fb', o provedor só
    # encaminha SMS cujo remetente ele reconhece como Facebook. O código da
    # verificação de negócio vem por outra rota/remetente → é descartado antes de
    # chegar à API. O serviço 'ot' ("qualquer outro serviço") é justamente o balde
    # dos remetentes NÃO reconhecidos.
    # Medido em 2026-08-04 (Tiger/Brasil): 'ot' US$0,122 · 15.430 números.
    # O serviço agora é decidido POR-PROVEDOR no ponto da compra (mapa SMS_SERVICO_BM
    # lá em cima): sms24h/smsbower usam 'fb' (números BR reais, entregam a BM barato);
    # tiger/grizzly/vak usam 'ot' (o 'fb' deles é filtrado por remetente). Por isso a
    # transição global fb→ot antiga fica DESLIGADA (_tentou_qualquer=True): cada
    # provedor já compra direto no serviço que entrega a BM — não há o que "escalar".
    _servico_sms = SERVICE_FACEBOOK   # base p/ logs; o efetivo vem de SMS_SERVICO_BM
    _tentou_qualquer = True

    # Com VÁRIOS provedores, cada número novo sai de um provedor DIFERENTE (uma
    # tentativa por provedor) — mais uma rodada com 'ot'. Com um só, repete nele
    # até SMS_MAX_NUMEROS_MESMO_PROV e ainda tenta o 'ot'.
    # Alto DE PROPÓSITO (2026-08-16): números que não entregam o código são CANCELADOS
    # (reembolsados), então reinsistir é BARATO. O fluxo deve rodar até o código chegar —
    # NÃO pausa por não-entrega. A BM barrada p/ anúncios é tratada à parte (→ 2ª BM), que
    # é o freio real contra loop numa BM que nunca verifica.
    _max_tent = max(60, len(_fila) * 15)

    if _modo_painel:
        _preco_max = 0
        sms = _client_painel
        status("📲 SMS via GS SMS (central) — número cobrado do seu SALDO (R$). "
               "Se um número não receber, troco de servidor automaticamente (fonte protegida).")
    else:
        if len(_fila) > 1:
            status("🔁 Ordem dos provedores de SMS: "
                   + " → ".join(nome_do_provedor(p) for p, _ in _fila))
        else:
            status(f"📌 Provedor fixo (escolha da interface): {nome_do_provedor(_fila[0][0])} — "
                   f"compro SÓ nele; se um número não entregar, cancelo e tento outro NELE MESMO "
                   f"(até {_max_tent}x), sem trocar de provedor.")

        _preco_max = preco_max_configurado()
        if _preco_max:
            status(f"💵 Teto por número: US$ {_preco_max:.4f} "
                   f"(libera as faixas melhores, não força o mais barato)")

        sms = criar_cliente_sms(_fila[0][1], _fila[0][0])
        try:
            _saldo = sms.saldo()
            if _saldo is not None:
                status(f"💳 Saldo {_nome_prov}: {sms.moeda} {_saldo}")
        except Exception:
            pass

    status("🚀 PRO MAX: iniciando verificação de negócio (envio para análise)...")

    # (informativo) abre Contas do WhatsApp
    try:
        _ir_para(driver, f"{BASE}/whatsapp_account/?business_id={business_id}",
                 esperar=['whatsapp_account'], timeout=25)
        from server.waba import dispensar_popup_atualizacao_whatsapp
        dispensar_popup_atualizacao_whatsapp(driver)
    except Exception:
        pass

    # GATE: BM bloqueada para anúncios? (GS Prime Plus IGNORA — a restrição de BM
    # nova não impede a verificação; o hard-lock real já foi tratado no chamador.)
    if not ignorar_restricao and _bm_bloqueada_para_anuncios(driver, business_id, status):
        res['bm_bloqueada'] = True
        res['mensagem'] = 'BM bloqueada para anúncios — verificação não iniciada.'
        return res

    # ⭐ CRIAR CONTA DE ANÚNCIOS p/ destravar a verificação na Central. Vale em 2 casos:
    #  (a) FLUXO SEM WABA (sem_waba=True): NUNCA houve WABA, então a Central não tem o
    #      botão — criar a conta de anúncios o faz aparecer (é o fluxo principal aqui).
    #  (b) WABA DESABILITADA: a WABA nasceu, mas veio desabilitada → o botão some; criar
    #      a conta de anúncios também destrava.
    # Só cria se o botão REALMENTE não está lá (senão segue o fluxo normal). As Contas de
    # anúncios já passaram sem restrição no gate acima.
    try:
        if not _central_tem_botao_verificacao(driver, business_id):
            # Estado REAL da WABA (ausente × desabilitada × ok). No fluxo sem_waba
            # (Método 8 / GS Prime Plus) a ausência é ESPERADA — não se checa.
            _estado_waba = 'ignorado' if sem_waba else _estado_conta_whatsapp(driver, business_id)
            _waba_desab = (_estado_waba == 'desabilitada')
            _precisa_conta = bool(sem_waba) or _waba_desab
            _tem_botao = False
            if _precisa_conta:
                # Cria a conta de anúncios (ATIVO) e CONFIRMA que o botão apareceu (até 2x).
                for _tent in range(1, 3):
                    status(f"🧩 Central sem 'Iniciar verificação' — criando conta de anúncios "
                           f"(ativo) p/ destravar (tentativa {_tent}/2)...")
                    _criar_conta_anuncios_para_liberar_verificacao(
                        driver, business_id, empresa_dados, status)
                    if _central_tem_botao_verificacao(driver, business_id):
                        _tem_botao = True
                        break
            # ⛔ Botão 'Iniciar verificação' AUSENTE na Central e nada destravou.
            if not _tem_botao:
                # ⭐ WABA NUNCA CRIADA (2026-08-17) — o caso do loop infinito.
                # 'Nenhuma conta do WhatsApp adicionada' + BM SEM restrição =
                # o CRM (DataCrazy/Gupshup) não criou a WABA. Sem WABA a Central
                # NUNCA mostra 'Iniciar verificação', então comprar número/gerar
                # certificado é queimar dinheiro em loop. NÃO é bloqueio (a 2ª BM
                # não resolve): devolvemos `precisa_criar_waba` para o chamador
                # acionar o MÉTODO ESCOLHIDO NA GUI e reentrar aqui.
                if (not sem_waba) and _estado_waba == 'ausente':
                    _restrita_agora = False
                    try:
                        _restrita_agora = _bm_bloqueada_para_anuncios(driver, business_id, status)
                    except Exception as _er0:
                        logger.warning('[ProMax] checagem de restrição (WABA ausente) falhou: %s', _er0)
                    if _restrita_agora:
                        res['bm_bloqueada'] = True
                        res['mensagem'] = ('BM RESTRITA para anúncios (cadeado) — bloqueada; '
                                           'backend deve criar a 2ª BM.')
                        status('🔴 ' + res['mensagem'])
                        return res
                    res['precisa_criar_waba'] = True
                    res['waba_ausente'] = True
                    res['sem_botao_verificacao'] = True
                    res['mensagem'] = ("Nenhuma conta do WhatsApp na BM (a WABA não foi criada) "
                                       "e a BM NÃO está restrita — vou criar a WABA pelo método "
                                       "escolhido e refazer a verificação. Nada de SMS/2ª BM aqui.")
                    status('🟡 ' + res['mensagem'])
                    return res
                if bloquear_se_sem_botao:
                    # ⚠️ ANTES de gastar a 2ª BM, CONFIRMA que existe bloqueio de
                    # verdade (2026-08-04). A 2ª BM é o último cartucho do perfil —
                    # a Meta só deixa ~2 por conta. Aconteceu de a Central ficar sem
                    # o botão porque a WABA NUNCA foi criada (o passo do CRM falhou:
                    # 'Nenhuma conta do WhatsApp adicionada'), com a BM 100% limpa —
                    # e o sistema queimava a 2ª BM à toa, criando duas BMs num perfil
                    # configurado para uma.
                    #   • WABA existe mas DESABILITADA → é bloqueio: 2ª BM (regra
                    #     do usuário de 2026-07-25).
                    #   • BM RESTRITA para anúncios     → é bloqueio: 2ª BM.
                    #   • Nenhum dos dois               → NÃO é bloqueio: falha de
                    #     fluxo. Reporta pendente e preserva a 2ª BM.
                    _restrita = False
                    try:
                        _restrita = _bm_bloqueada_para_anuncios(driver, business_id, status)
                    except Exception as _er:
                        logger.warning('[ProMax] re-checagem de restrição falhou: %s', _er)
                    # ⭐ REGRA DO DONO (2026-09-27, provada ao vivo): a RESTRIÇÃO de anúncios
                    # ("Você não pode usar este portfólio para anunciar") só é BLOQUEIO quando
                    # NÃO há WABA. Com a WABA criada (mesmo RESTRITA, não desabilitada) a
                    # análise funciona e a restrição some sozinha ao verificar → NUNCA 2ª BM
                    # por restrição. Só WABA DESABILITADA, ou restrição SEM WABA, vira bloqueio.
                    _waba_existe = _estado_waba in ('ok', 'restrita')
                    _eh_bloqueio = _waba_desab or (_restrita and not _waba_existe)
                    if not _eh_bloqueio:
                        res['sem_botao_verificacao'] = True
                        # Não é bloqueio: ou a BM está limpa, ou a WABA EXISTE (só restrita).
                        # Falha de fluxo (botão não apareceu) → confere/cria a WABA e reentra.
                        # Bounded (o chamador reentra no máximo 2x) e SEM gastar a 2ª BM.
                        if not sem_waba:
                            res['precisa_criar_waba'] = True
                        res['mensagem'] = (
                            "Central sem 'Iniciar verificação', mas NÃO é bloqueio (a WABA "
                            "existe — ainda que RESTRITA — ou a BM não está restrita). Falha de "
                            "fluxo: vou conferir/criar a WABA e reentrar (sem gastar a 2ª BM).")
                        status('⚠️ ' + res['mensagem'])
                        return res
                    res['bm_bloqueada'] = True
                    res['waba_desabilitada'] = bool(_waba_desab)
                    _motivo = ('WABA DESABILITADA' if _waba_desab else 'BM RESTRITA SEM WABA')
                    res['mensagem'] = (f"{_motivo} — Central sem 'Iniciar verificação'. "
                                       "BM bloqueada; backend deve tentar a 2ª BM.")
                    status('🔴 ' + res['mensagem'])
                    return res
                # sem_waba / GS Prime Plus: comportamento antigo — NÃO bloqueia (o
                # hard-lock real é tratado no chamador); só não gasta SMS/certificado.
                res['mensagem'] = ("Central sem 'Iniciar verificação' e a conta de anúncios "
                                   "não destravou o botão — não gastei SMS/certificado.")
                status('⛔ ' + res['mensagem'])
                return res
    except Exception as _e_alt:
        logger.warning("[ProMax] criar/confirmar conta de anúncios (destravar) ignorado: %s", _e_alt)

    ativacao_id = None
    caminho_cert = None
    _cert_guard_verificado = False  # GUARD anti-troca roda 1x só (dados não mudam)
    _idx_prov_atual = 0      # posição na fila; NUNCA volta para um reprovado
    _rate_limit_hits = 0     # nº de rate-limits de SMS ("muitos códigos") nesta BM → teto p/ descanso
    _falhas_nao_sms = 0      # nº de tentativas que falharam por motivo ≠ SMS (teto anti-loop)
    try:
        for tentativa in range(1, _max_tent + 1):
            res['tentativas'] = tentativa
            # Navegador fechado (usuário/queda)? Aborta NA HORA como Erro/Falha.
            if not _navegador_vivo(driver):
                res['mensagem'] = 'Navegador foi fechado durante a verificação.'
                res['navegador_fechado'] = True
                status('❌ ' + res['mensagem'])
                _cancelar_sms_silencioso(sms, ativacao_id)
                return res
            # TETO de falhas que NÃO são do SMS (tela presa/não reconhecida, captcha, upload,
            # telefone comercial, certificado...): trocar de número não resolve — após
            # _MAX_FALHAS_NAO_SMS encerra (descanso; o reprocesso reabre depois) em vez de
            # girar até _max_tent tentativas comprando número. (2026-10-12)
            if _falhas_nao_sms >= _MAX_FALHAS_NAO_SMS:
                res['descansar'] = True
                res['mensagem'] = ((res.get('mensagem') or 'Verificação não concluída')
                                   + f' — {_falhas_nao_sms} tentativas falharam sem ser por SMS; '
                                     'perfil em descanso p/ reenvio depois. (pendente)')
                status('🛌 ' + res['mensagem'])
                return res
            status(f"🧭 Tentativa {tentativa}/{_max_tent} de verificação.")

            # ── ⛑️ DIAGNÓSTICO ANTES DE GASTAR OUTRO NÚMERO (2026-08-17) ──────────
            # É o FREIO do loop infinito. A partir da 2ª tentativa, antes de comprar
            # mais um número, respondemos "esta BM ainda TEM como verificar?":
            #   • BM RESTRITA p/ anúncios (cadeado) → bloqueio: o backend cria a 2ª BM
            #     NA HORA (e, se o perfil já tiver 2, descarta como erro/bloqueio).
            #   • WABA DESABILITADA                 → bloqueio: 2ª BM (+ recurso).
            #   • WABA AUSENTE (nunca criada)       → NÃO é bloqueio: sai com
            #     `precisa_criar_waba` p/ o chamador rodar DataCrazy/Gupshup (o que o
            #     usuário escolheu na GUI) e reentrar aqui com a WABA no lugar.
            # Antes isso só era checado quando o SMS falhava (e a WABA ausente, nunca):
            # a aba ficava comprando número/gerando certificado para SEMPRE numa BM que
            # jamais teria o botão 'Iniciar verificação'.
            if tentativa >= 2:
                _diag = _diagnostico_bm(driver, business_id, status,
                                        checar_waba=(not sem_waba))
                if _diag.get('restrita'):
                    res['bm_bloqueada'] = True
                    res['mensagem'] = ('BM RESTRITA para anúncios (cadeado) — parei o ciclo de '
                                       'SMS; backend deve criar a 2ª BM agora.')
                    status('🔴 ' + res['mensagem'])
                    return res
                if _diag.get('waba') == 'desabilitada':
                    res['bm_bloqueada'] = True
                    res['waba_desabilitada'] = True
                    res['mensagem'] = ('WABA DESABILITADA (conta não cumpre as diretrizes) — '
                                       'bloqueada; backend deve criar a 2ª BM.')
                    status('🔴 ' + res['mensagem'])
                    return res
                if _diag.get('waba') == 'ausente':
                    res['precisa_criar_waba'] = True
                    res['waba_ausente'] = True
                    res['mensagem'] = ('Sem conta do WhatsApp na BM (WABA não criada) e BM sem '
                                       'restrição — parei de comprar número; vou criar a WABA '
                                       'pelo método escolhido e refazer a verificação.')
                    status('🟡 ' + res['mensagem'])
                    return res

            # ── O provedor da vez ────────────────────────────────────────────────
            # `_idx_prov_atual` é avançado ao FIM da tentativa que falhou, pulando
            # quem já foi reprovado. Não se usa `tentativa - 1`: a compra pode ter
            # girado a fila lá dentro (provedor sem saldo/offline), e voltar pelo
            # índice da tentativa faria o bot recomprar em quem já falhou.
            sms_provedor, _nome_prov, sms = _cliente_da_vez(_idx_prov_atual)
            if len(_fila) > 1:
                status(f"📶 Provedor desta tentativa: {_nome_prov}")
                try:
                    _sd = sms.saldo()
                    if _sd is not None:
                        status(f"💳 Saldo {_nome_prov}: {sms.moeda} {_sd}")
                except Exception:
                    pass

            # 1) compra número virtual NO PROVEDOR ESCOLHIDO na GUI (sms24h/Grizzly/
            #    Tiger), com o token do usuário. Se faltar SALDO ou NÚMERO, NÃO descarta
            #    o perfil: PAUSA o run e AGUARDA (o usuário recarrega e clica Continuar)
            #    — os próximos perfis teriam o MESMO erro, então pausar evita
            #    desperdiçá-los. O retry só ocorre ao Continuar (NÃO martela a API em
            #    segundos). Mesma estratégia do domínio. (2026-07-13)
            #    ⚠️ A mensagem SEMPRE mostra o provedor REAL (`_nome_prov`). Ela era fixa
            #    em "sms24h" e, com o Tiger selecionado, o log dizia que estava comprando
            #    no sms24h — parecia que o sistema ignorava a escolha. (2026-08-02)
            from server import pausa as _pausa
            status(f"🛒 Comprando número virtual ({_nome_prov} · Facebook/Brasil)...")
            compra = {}
            _falhas_transitorias = 0
            # ── TROCA DE PROVEDOR EM VEZ DE PAUSAR (2026-08-03) ─────────────────
            # Regra do usuário: "quando um servidor tiver com problema ou não der
            # para comprar ou erro, em vez de pausar tentar o PRÓXIMO provedor
            # disponível com token". Só pausa quando a FILA INTEIRA falhar — antes
            # bastava um provedor ruim (ex.: vak-sms com token expirado) para
            # travar as 8 abas, com os outros provedores abastecidos e ociosos.
            # NÃO herda os "não entregou o SMS" (_prov_reprovados): não-entrega NÃO é o
            # mesmo que "não consegue VENDER". Herdar fazia a pausa "SMS indisponível em
            # todos" disparar com a API CHEIA de saldo (o número era comprável, só o código
            # não chegou). `_falhos` rastreia SÓ falha de VENDA real (saldo/config).
            _falhos = {}
            _idx_prov = _idx_prov_atual         # posição atual na fila de provedores
            while True:
                if not _navegador_vivo(driver):
                    res['navegador_fechado'] = True
                    res['mensagem'] = 'Navegador foi fechado durante a compra do número.'
                    status('❌ ' + res['mensagem'])
                    return res
                # TETO DE PREÇO: com maxPrice o provedor pode entregar números das
                # faixas mais caras (que costumam ser as que entregam de verdade).
                # Vazio/0 = comportamento antigo (o provedor escolhe, quase sempre
                # o mais barato — que no fb/BR é justamente o que não recebe).
                # O teto de preço só vale para o serviço 'fb'. O 'ot' custa mais
                # (Tiger: US$0,122 contra US$0,020) — aplicar o mesmo teto ali
                # faria toda compra do último recurso falhar por preço.
                # SERVIÇO POR-PROVEDOR: cada provedor compra no serviço que entrega a
                # BM pelo menor custo (mapa SMS_SERVICO_BM). O teto de preço só faz
                # sentido no 'fb' (no 'ot' o número é de faixa única e mais cara).
                _svc = _servico_bm_do_provedor(sms_provedor)
                # O teto vale APENAS no 'fb' do SMSBower (lá existem várias faixas de
                # preço por número). ⚠️ CORREÇÃO 2026-08-30: o `maxPrice` é um TETO
                # (slider "máx $X" do site) — sozinho NÃO força número fresco; a API
                # entrega o mais barato ≤ teto, e o mais barato é o mais REUSADO/queimado
                # (Meta acusa "muitos códigos" nele). O que GARANTE número fresco é o
                # MIN price, que é config da CONTA smsbower ("Set up max/min price") e
                # vale p/ toda compra via API. Combo recomendado: min 0,10 na conta +
                # teto 0,12 aqui → cai na faixa fresca 0,10–0,12 (ex.: pool id 2738 @ 0,116).
                # O sms24h também é 'fb', mas é número BR real de faixa única e cara
                # (~US$0,145) e serve de ÚLTIMO recurso — aplicar o teto ali faria
                # toda compra do fallback falhar por preço.
                _prov_low = str(sms_provedor or '').strip().lower()
                _teto = (_preco_max or None) if (_svc == SERVICE_FACEBOOK and _prov_low == 'smsbower') else None
                compra = sms.comprar_numero(service=_svc,
                                            country=COUNTRY_BRASIL,
                                            max_price=_teto) or {}
                if compra.get('sucesso'):
                    break
                _cod = str(compra.get('codigo', '')).upper()
                _msgc = str(compra.get('mensagem', '')).lower()
                # ── CLASSIFICAÇÃO ROBUSTA (2026-08-16) — MESMA API em 2 PCs × 10 abas ──
                # SÓ dois casos tiram o provedor da jogada: (1) SEM SALDO real e (2) CONFIG
                # fatal (token/serviço inválido). TODO o resto — inclusive "SEM NÚMERO no
                # momento" (NO_NUMBERS), rate-limit, "too many requests", timeout, rede, SQL
                # do provedor — é TRANSITÓRIO sob carga em massa: os números esgotam e
                # LIBERAM em segundos. Nesses casos REINSISTIMOS no MESMO provedor (backoff
                # curto) — NUNCA rotacionamos por isso e JAMAIS pausamos. A compra que FALHA
                # não gasta saldo, então insistir é seguro e é o que garante rodar 24h com a
                # API cheia. ⚠️ Antes o NO_NUMBERS caía como "sem saldo" e disparava a pausa
                # "SMS indisponível em todos" com o provedor cheio de saldo (falso erro).
                _sem_saldo = (
                    _cod == 'NO_BALANCE'
                    or 'sem saldo' in _msgc or 'no balance' in _msgc
                    or 'insufficient' in _msgc or 'saldo insuficiente' in _msgc
                    or 'sem crédito' in _msgc or 'sem credito' in _msgc
                )
                _fatal_config = (
                    _cod in ('BAD_KEY', 'BAD_ACTION', 'BAD_SERVICE')
                    or 'inválido' in _msgc or 'invalido' in _msgc
                    or 'não configurado' in _msgc or 'nao configurado' in _msgc
                    or 'token' in _msgc
                )
                if not (_sem_saldo or _fatal_config):
                    # TRANSITÓRIO: reinsiste no MESMO provedor com backoff curto. A cada ~8
                    # tentativas, SE houver outro provedor com token, dá uma volta nele
                    # (melhora as chances sob concorrência) e depois retoma — SEM queimar
                    # ninguém e SEM pausar. Loop indefinido: números liberam e a compra
                    # falha é de graça.
                    _falhas_transitorias += 1
                    _jit = abs(hash(str(business_id))) % 4
                    _espera_t = min(15, 2 + (_falhas_transitorias % 6) + _jit)
                    _det = (compra.get('mensagem', '') or 'sem número no momento')[:50]
                    if len(_fila) > 1 and (_falhas_transitorias % 8 == 0):
                        _idx_prov = (_idx_prov + 1) % len(_fila)
                        sms_provedor, _nome_prov, sms = _cliente_da_vez(_idx_prov)
                        status(f'🔁 {_det} — dando uma volta em outro provedor: {_nome_prov}...')
                    else:
                        status(f'⏳ {_nome_prov}: {_det} — reinsistindo em {_espera_t}s '
                               f'(tentativa {_falhas_transitorias})...')
                    time.sleep(_espera_t)
                    continue

                # ── Provedor FORA por SALDO/CONFIG: gira para o PRÓXIMO com token ──────
                if _sem_saldo:
                    _motivo = 'sem SALDO'
                else:
                    _motivo = (compra.get('mensagem', '') or 'token/serviço inválido')[:60]
                _falhos[sms_provedor] = _motivo

                _prox = None
                for _k in range(1, len(_fila) + 1):
                    _cand = (_idx_prov + _k) % len(_fila)
                    if _fila[_cand][0] not in _falhos:
                        _prox = _cand
                        break

                if _prox is not None:
                    _idx_prov = _prox
                    _falhas_transitorias = 0
                    sms_provedor, _nome_prov, sms = _cliente_da_vez(_idx_prov)
                    status(f'🔁 Trocando de provedor — {_motivo}. Agora: {_nome_prov}.')
                    status(f'🛒 Comprando número virtual ({_nome_prov} · Facebook/Brasil)...')
                    continue

                # TODOS os provedores da fila falharam → aí sim PAUSA e aguarda o
                # usuário recarregar/corrigir (o perfil segue aberto, nada se perde).
                _resumo = ' · '.join(f'{nome_do_provedor(_p)}: {_m}'
                                     for _p, _m in _falhos.items())
                status(f'⏸️ Nenhum provedor de SMS conseguiu vender ({_resumo}) — PAUSADO. '
                       f'Recarregue/verifique e clique Continuar (o perfil segue aberto).')
                _pausa.set_pausado(True)
                if not _pausa.aguardar_se_pausado(status, motivo='(SMS indisponível em todos) '):
                    res['mensagem'] = 'Cancelado enquanto aguardava saldo/número de SMS.'
                    return res
                # Ao retomar, a fila inteira volta a valer (o usuário recarregou).
                _falhos.clear()
                _falhas_transitorias = 0
                _idx_prov = _idx_prov_atual
                sms_provedor, _nome_prov, sms = _cliente_da_vez(_idx_prov)
                status(f'▶️ Retomando — comprando número no {_nome_prov}...')
                continue
            if not compra.get('sucesso'):
                # (erro real já setou a mensagem) — aborta as tentativas.
                break
            # A compra pode ter GIRADO a fila (provedor sem saldo/offline/token
            # ruim). Fixa onde paramos e marca os que ficaram pelo caminho como
            # queimados, para nenhuma tentativa futura voltar neles.
            _idx_prov_atual = _idx_prov
            if len(_fila) > 1:
                _prov_reprovados.update(_falhos)
            ativacao_id = compra.get('id')
            numero = str(compra.get('numero', ''))
            e164 = formatar_e164(numero)
            nacional = formatar_nacional(numero)          # '(28) 92691-8605' (certificado)
            nacional_digitos = _digitos_nacionais(numero)  # '28926918605' (campo do FB)
            status(f"📞 Número: {e164} (ativação {ativacao_id})")

            # 2) define o telefone comercial da empresa
            if not _definir_telefone_empresa(driver, business_id, e164, status):
                _cancelar_sms_silencioso(sms, ativacao_id)
                res['mensagem'] = 'Não consegui definir o telefone comercial.'
                _falhas_nao_sms += 1
                continue

            # 2b) COERÊNCIA: atualiza o SITE com o número real + email da BM — o
            # mesmo número que virou o Telefone comercial da BM e vai no
            # certificado, e o email que verificou a BM. Assim, na análise, o
            # site bate 100% com os dados da empresa. Regenera preservando a meta
            # tag do FB. Best-effort — NÃO bloqueia o fluxo se falhar.
            try:
                if site_id and (nacional or bm_email):
                    status("🌐 Atualizando contato do site (número real + email da BM)...")
                    # Senha do e-mail apex (gsmails) que VERIFICOU a BM — para o site
                    # exibir o MESMO e-mail+senha (o de subdomínio nunca recebe nada).
                    _senha_apex = ''
                    try:
                        _accs = getattr(driver, '_gsmails_accounts', {}) or {}
                        _conta = _accs.get(bm_email) or getattr(driver, '_gsmails_last', None) or {}
                        if isinstance(_conta, dict):
                            _senha_apex = str(_conta.get('password') or '')
                    except Exception:
                        _senha_apex = ''
                    _rc_site = atualizar_contato_site(
                        site_id, telefone=nacional, email=(bm_email or ''),
                        senha_email=_senha_apex,
                        email_servidor=('https://mail.farm.mragencia.com' if _senha_apex else ''))
                    if _rc_site.get('sucesso'):
                        status("✅ Site coerente com a BM/certificado (contato atualizado).")
                    else:
                        status("⚠️ Update do site não confirmado: "
                               + str(_rc_site.get('mensagem', ''))[:70])
            except Exception as _ue:
                logger.warning("[ProMax] atualizar_contato_site falhou: %s", _ue)

            # 3) gera o certificado (com o número comprado).
            # ARQUIVO ÚNICO por BM + LOCK que serializa a geração/gravação: em
            # massa simultânea (10 janelas), garante que cada BM gere e grave o
            # SEU próprio certificado, uma por vez — sem uma baixar/enviar o da
            # outra (causa do erro "não detectamos a razão social X").
            # ⭐ GUARD ANTI-TROCA (regra nº 1, 2026-07-13): o certificado é gerado a
            #   partir do site_id; ele SÓ pode ser enviado se a razão social/CNPJ desse
            #   site bater com a de empresa_dados (a empresa desta BM). Em massa
            #   simultânea isso garante que NENHUMA aba use o certificado de outra —
            #   se por qualquer motivo os dados divergirem, ABORTA a tentativa (não
            #   manda o certificado errado p/ análise). Best-effort: se a API de
            #   detalhes falhar, segue (o nome de arquivo único + lock já isolam).
            try:
                _det = {} if _cert_guard_verificado else (obter_detalhes_site(site_id) or {})
                _det_emp = _det.get('empresa') or {}
                if _det.get('sucesso') and _det_emp:
                    _rz_site = _norm_razao(_det_emp.get('razao_social'))
                    _rz_emp = _norm_razao((empresa_dados or {}).get('razao_social'))
                    _cnpj_site = _so_digitos(_det_emp.get('cnpj'))
                    _cnpj_emp = _so_digitos((empresa_dados or {}).get('cnpj'))
                    _rz_bate = bool(_rz_site) and bool(_rz_emp) and (
                        _rz_site == _rz_emp or _rz_site in _rz_emp or _rz_emp in _rz_site)
                    _cnpj_bate = (not _cnpj_site or not _cnpj_emp or _cnpj_site == _cnpj_emp)
                    if not (_rz_bate and _cnpj_bate):
                        _cancelar_sms_silencioso(sms, ativacao_id)
                        res['bm_bloqueada'] = False
                        res['mensagem'] = ("🚫 GUARD anti-troca: certificado do site_id %s "
                                           "('%s' / CNPJ %s) NÃO bate com a empresa da BM "
                                           "('%s' / CNPJ %s). NÃO enviei — abortando p/ não "
                                           "mandar certificado de outra empresa." % (
                                               site_id, _det_emp.get('razao_social'), _cnpj_site,
                                               (empresa_dados or {}).get('razao_social'), _cnpj_emp))
                        status(res['mensagem'])
                        logger.error("[ProMax] %s", res['mensagem'])
                        return res
                    _cert_guard_verificado = True
                    status("🔒 Certificado confere: razão social/CNPJ do site == empresa da BM.")
            except Exception as _ge:
                logger.warning("[ProMax] guard anti-troca (detalhes_site) indisponível: %s", _ge)

            status("🧾 Gerando certificado CNPJ (com o número comprado)...")
            caminho_cert = os.path.join(_pasta_certificado(),
                                        _nome_arquivo_cert(business_id, site_id))
            salvar_erro = None
            cert = gerar_certificado_cnpj_pdf(site_id, telefone=nacional) or {}
            cert_ok = bool(cert.get('sucesso') and cert.get('pdf_bytes'))
            if cert_ok:
                try:
                    with open(caminho_cert, 'wb') as fh:
                        fh.write(cert['pdf_bytes'])
                except Exception as e:
                    salvar_erro = str(e)
            if not cert_ok:
                _cancelar_sms_silencioso(sms, ativacao_id)
                res['mensagem'] = f"Falha no certificado: {cert.get('mensagem','')}"
                status('❌ ' + res['mensagem'])
                _falhas_nao_sms += 1
                continue
            if salvar_erro:
                res['mensagem'] = f'Não consegui salvar o certificado: {salvar_erro}'
                status('❌ ' + res['mensagem'])
                _cancelar_sms_silencioso(sms, ativacao_id)
                _falhas_nao_sms += 1
                continue

            # 4) submete na Central de Segurança (passa o nº nacional p/ a tela de
            #    contato — apaga o antigo e digita o atual)
            sub = _submeter_central(driver, business_id, empresa_dados, tipo_empresa,
                                    caminho_cert, sms, ativacao_id, captcha_token,
                                    nacional_digitos, status,
                                    metodo_verificacao=metodo_verificacao, bm_email=bm_email,
                                    site_url=(site_url or empresa_dados.get('url_completa', '')))

            # limpa o PDF (não reaproveitar entre perfis/empresas)
            _apagar_arquivo(caminho_cert)
            caminho_cert = None

            # Navegador fechado durante a submissão? Aborta NA HORA (Erro/Falha).
            if sub.get('navegador_fechado'):
                res['navegador_fechado'] = True
                res['mensagem'] = sub.get('mensagem', 'Navegador foi fechado durante a verificação.')
                _cancelar_sms_silencioso(sms, ativacao_id)
                return res

            # ERRO GENÉRICO PERSISTENTE da Meta ("Sorry, something went wrong"): NÃO adianta
            # recomprar número e re-submeter contra um recurso quebrado — só prende o navegador
            # e trava a fila. TERMINAL → descanso: o backend fecha o navegador e marca 'erro'; o
            # reprocesso-ocioso reabre depois (MESMA empresa, número NOVO). (dono 2026-10-08)
            # Idem p/ o ASSISTENTE reiniciando em loop (Ações→País→…→Iniciar→Ações→País):
            # recomprar número não muda nada — TERMINAL → descanso. (2026-10-12)
            if sub.get('erro_generico_persistente') or sub.get('wizard_em_loop'):
                _cancelar_sms_silencioso(sms, ativacao_id)
                res['descansar'] = True
                res['mensagem'] = sub.get('mensagem',
                    'Erro genérico da Meta persistente — perfil em descanso p/ reenvio depois.')
                status('🛌 ' + res['mensagem'])
                return res

            if sub.get('bm_bloqueada'):
                res['bm_bloqueada'] = True
                res['mensagem'] = sub.get('mensagem', 'BM bloqueada.')
                _cancelar_sms_silencioso(sms, ativacao_id)
                return res

            if sub.get('em_analise'):
                if sub.get('sms_usado'):
                    # SMS realmente consumido (digitou o código) → finaliza a ativação.
                    _finalizar_sms_silencioso(sms, ativacao_id)
                else:
                    # ⭐ (pedido do usuário 2026-07-08) A BM foi p/ análise SÓ pelo
                    # DOMÍNIO — o SMS não foi usado. CANCELA o número (reembolsa); o
                    # número já cumpriu seu papel no certificado/telefone comercial.
                    _cancelar_sms_silencioso(sms, ativacao_id)
                    status('↩️ Análise aceita sem usar o SMS — número cancelado (padrão).')
                res['sucesso'] = True
                res['em_analise'] = True
                res['sms_usado'] = bool(sub.get('sms_usado'))
                res['mensagem'] = sub.get('mensagem', 'BM enviada para análise (Em análise).')
                status('🎉 ' + res['mensagem'])
                return res

            # BLOQUEIO DE AÇÃO do PERFIL ("Limitamos a frequência…"): a WABA fica APROVADA
            # e a BM saudável, então o diagnóstico não acha nada e o loop re-compraria
            # número eternamente. IP/número NÃO resolvem (é do perfil). Descarta ESTA BM
            # como bloqueada → o backend cria a 2ª BM no mesmo perfil. (2026-08-29, dono)
            if sub.get('acao_bloqueada'):
                _cancelar_sms_silencioso(sms, ativacao_id)
                res['bm_bloqueada'] = True
                res['acao_bloqueada'] = True
                res['mensagem'] = sub.get('mensagem',
                    'Bloqueio de ação do perfil ("Limitamos a frequência…") — descarto esta BM e sigo pela 2ª BM.')
                status('🚫 ' + res['mensagem'])
                return res

            # WABA DESABILITADA no meio do fluxo? (a Meta derruba a WABA nova → some o
            # botão 'Iniciar verificação' e a consulta do registro passa a falhar). É
            # SEGURO checar AQUI (entre tentativas, sem modal aberto). Se confirmado,
            # NÃO re-compra número: aborta como BLOQUEIO p/ o backend criar a 2ª BM —
            # antes o bot ficava recomprando número em loop infinito. Pula a checagem
            # quando o problema foi só o SMS não chegar (a WABA está OK). (2026-07-25)
            # É SEGURO diagnosticar AQUI (entre tentativas, sem modal aberto). Rodamos na
            # hora quando o próprio envio suspeitou da WABA (`possivel_waba_desabilitada`)
            # ou quando a falha NÃO foi só o SMS não chegar — assim não se perde um ciclo
            # inteiro (compra + certificado) antes do veredito. Os demais casos caem no
            # diagnóstico do topo da próxima tentativa.
            if sub.get('possivel_waba_desabilitada') or not sub.get('sms_falhou'):
                _diag = _diagnostico_bm(driver, business_id, status,
                                        checar_waba=(not sem_waba))
                if _diag.get('restrita'):
                    _cancelar_sms_silencioso(sms, ativacao_id)
                    res['bm_bloqueada'] = True
                    res['mensagem'] = ('BM RESTRITA para anúncios (cadeado) — bloqueada; backend '
                                       'deve criar a 2ª BM (não fico em loop de SMS).')
                    status('🔴 ' + res['mensagem'])
                    return res
                if _diag.get('waba') == 'desabilitada':
                    _cancelar_sms_silencioso(sms, ativacao_id)
                    res['bm_bloqueada'] = True
                    res['waba_desabilitada'] = True
                    res['mensagem'] = ('WABA DESABILITADA durante o envio (conta não cumpre as '
                                       'diretrizes da Meta) — bloqueada; backend deve tentar a 2ª BM.')
                    status('🔴 ' + res['mensagem'])
                    return res
                if _diag.get('waba') == 'ausente':
                    _cancelar_sms_silencioso(sms, ativacao_id)
                    res['precisa_criar_waba'] = True
                    res['waba_ausente'] = True
                    res['mensagem'] = ('A BM ficou SEM conta do WhatsApp (WABA não criada) e não '
                                       'está restrita — vou criar a WABA pelo método escolhido e '
                                       'refazer a verificação.')
                    status('🟡 ' + res['mensagem'])
                    return res

            # falhou — cancela o número (reembolsa) e tenta de novo (novo número)
            _cancelar_sms_silencioso(sms, ativacao_id)
            res['mensagem'] = sub.get('mensagem', 'Tentativa não concluída.')
            if sub.get('codigo_incorreto'):
                # CÓDIGO INCORRETO (2026-10-06, regra do dono): o provedor ENTREGOU (não é
                # reprovado) — o número é que veio queimado/reusado. Só troca o NÚMERO no
                # MESMO provedor e refaz contato (número novo) → certificado → SMS → código.
                status('🔁 Código incorreto — número cancelado; comprando OUTRO número e '
                       'refazendo contato + envio p/ análise + novo código...')
                continue
            if sub.get('sms_falhou'):
                # RATE-LIMIT DE SMS ("muitos códigos"): o sistema já troca número + IP 1x.
                # Se REINCIDIR (perfil/IP/números queimados), NÃO fica recomprando número à
                # toa — isola o perfil no DESCANSO e segue p/ o próximo da fila; o
                # reprocesso-ocioso reabre depois com número NOVO. (pedido do dono 2026-10-08)
                if sub.get('rate_limit'):
                    _rate_limit_hits += 1
                    if _rate_limit_hits >= 2:
                        res['descansar'] = True
                        res['mensagem'] = ('Rate-limit de SMS persistente (muitos códigos) após troca de '
                                           'número/IP — perfil em descanso p/ reenvio depois com número novo.')
                        status('🛌 ' + res['mensagem'])
                        return res
                # ── O PROVEDOR NÃO ENTREGOU → QUEIMA E TROCA (2026-08-04) ───────
                # Medido: 10 perfis no Vak-SMS, nenhum código, nem na 1ª nem nas
                # trocas. Se o pool de um provedor não recebe o SMS da Meta, ele
                # não vai receber no número seguinte — o que muda a entrega é o
                # PROVEDOR. Então o próximo número JAMAIS sai do mesmo.
                if len(_fila) > 1:
                    _prov_reprovados[sms_provedor] = 'não entregou o SMS'
                    _prox = _proximo_provedor(_idx_prov_atual)
                else:
                    # Um provedor só: repete nele até o limite de números; depois
                    # `None` faz cair no último recurso ('ot') logo abaixo.
                    _prox = (_idx_prov_atual
                             if tentativa < SMS_MAX_NUMEROS_MESMO_PROV else None)

                if _prox is None and not _tentou_qualquer:
                    # Todos falharam com 'fb' → ÚLTIMO RECURSO: serviço 'ot',
                    # que entrega SMS de remetente não reconhecido (a hipótese
                    # para o código da BM nunca chegar). Zera os reprovados: o
                    # provedor pode ter falhado no 'fb' e funcionar no 'ot'.
                    _tentou_qualquer = True
                    _servico_sms = SERVICE_QUALQUER
                    _prov_reprovados.clear()
                    _prox = 0
                    status("🎯 Nenhum provedor entregou com o serviço 'Facebook'. "
                           "ÚLTIMO RECURSO: comprando com o serviço 'qualquer SMS' "
                           "(ot) — recebe também os remetentes que o filtro do "
                           "serviço 'fb' descarta.")
                elif _prox is None:
                    # TODOS os provedores já não-entregaram nesta BM nesta rodada. NÃO
                    # desiste (regra do usuário: rodar até o código chegar): ZERA os
                    # reprovados e RECOMEÇA o ciclo comprando de novo — números não
                    # entregues são reembolsados, então reinsistir é barato. O freio real
                    # é a checagem de BM barrada p/ anúncios (acima → 2ª BM).
                    _prov_reprovados.clear()
                    _prox = _idx_prov_atual
                    status("🔄 Todos os provedores falharam a entrega nesta rodada — "
                           "recomeçando o ciclo (o código pode chegar num número novo).")
                elif len(_fila) > 1:
                    status(f"⚠️ {_nome_prov} não entregou o SMS — próximo número será "
                           f"comprado em {nome_do_provedor(_fila[_prox][0])}.")
                else:
                    status(f"⚠️ SMS não chegou — outro número no {_nome_prov} "
                           f"(sem outro provedor com token para trocar).")
                _idx_prov_atual = _prox
                continue
            # erro não relacionado a SMS: registra e tenta mais uma vez no máximo
            # (o teto `_MAX_FALHAS_NAO_SMS` no topo do laço garante isso — antes o comentário
            # prometia, mas o laço seguia até `_max_tent` (≥60) tentativas de ~8min cada).
            _falhas_nao_sms += 1
            status(f"⚠️ {res['mensagem']}")

        # esgotou as tentativas
        if not res['sucesso'] and not res['bm_bloqueada']:
            res['mensagem'] = (res.get('mensagem') or
                               'Verificação de negócio não concluída.') + ' (pendente)'
        return res
    finally:
        _apagar_arquivo(caminho_cert)


def _cancelar_sms_silencioso(sms, ativacao_id):
    try:
        if sms and ativacao_id:
            sms.cancelar(ativacao_id)
    except Exception:
        pass


def _finalizar_sms_silencioso(sms, ativacao_id):
    # SMS já foi usado com sucesso → marca a ativação como concluída (status=6).
    try:
        if sms and ativacao_id:
            sms.finalizar(ativacao_id)
    except Exception:
        pass
