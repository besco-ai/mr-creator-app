#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRIAÇÃO DE WABA DIRETO NO META BUSINESS SUITE (sem DataCrazy/Gupshup)
=====================================================================
Cria a conta do WhatsApp Business (WABA) pela PRÓPRIA interface da Meta, em
'Configurações → Contas → Contas do WhatsApp'. É o caminho alternativo para
quando o CRM (DataCrazy/Gupshup) não consegue criar a WABA — sem ele o fluxo
Pro Max não tem o que enviar para análise e o perfil (e os domínios) se perdem.

Fluxo implementado (mapeado pelo usuário em 2026-07-31):
  1. 'Contas do WhatsApp' → botão 'Adicionar'
  2. opção 'Crie uma conta para se conectar à Plataforma do WhatsApp Business.'
  3. modal 'Criar uma conta do WhatsApp Business':
       • Nome de exibição — já vem com a razão social do portfólio
       • Categoria → rolar até o FIM da lista → 'Outro'
       • reCAPTCHA 'Não sou um robô' → CapSolver
       • 'Continuar'
  4. chegou em 'Escolha o número que deseja usar' → **WABA CRIADA**
     (não seguimos para o número: a WABA já existe, que é o que precisamos)
  5. fecha o modal (X) + F5 → a WABA aparece na lista e a Central de Segurança
     passa a exibir 'Iniciar verificação'

Módulo INDEPENDENTE de propósito: só depende do driver e do captcha_solver, para
poder ser plugado em qualquer fluxo. Uso típico:

    from server.waba import criar_waba, waba_existe

    if not waba_existe(driver, business_id):
        res = criar_waba(driver, business_id, callback_status=cb)
        if res['ok']:
            ...  # segue p/ a Central de Segurança (Iniciar verificação)
"""
from __future__ import annotations

import time
import logging

logger = logging.getLogger(__name__)

BASE_FB = "https://business.facebook.com"

# Rótulos da opção do menu 'Adicionar' que cria uma WABA NOVA. A Meta alterna
# entre o título e a descrição, então casamos os dois.
_OPCAO_CRIAR = (
    'Crie uma conta para se conectar à Plataforma do WhatsApp Business',
    'Crie uma conta para se conectar a Plataforma do WhatsApp Business',
    'Crie uma nova conta do WhatsApp Business',
    'Create a new WhatsApp Business account',
    # Outros idiomas (2026-10-12) — conta fora do pt/en nunca achava a opção e o
    # último recurso morria aqui. Só o VERBO "criar conta" (o menu também tem
    # "adicionar conta existente"/"solicitar acesso", que NÃO podem casar).
    'Create an account to connect to the WhatsApp Business Platform',
    'Crear una cuenta', 'Crea una cuenta', 'Tạo tài khoản', 'Создать аккаунт',
    'Создайте аккаунт', 'Buat akun', 'Créer un compte', 'Crea un account',
    'Hesap oluştur', 'Utwórz konto', 'Створити обліковий запис', 'Gumawa ng account',
    'खाता बनाएँ', 'खाता बनाएं',
)

# 'Adicionar' em outros idiomas (botão da lista 'Contas do WhatsApp'). ⚠️ O casamento
# de _clicar_texto é por SUBSTRING — por isso fica de fora o VI 'Thêm' (casaria 'Xem
# thêm' = 'Ver mais', que vem antes no DOM).
_ROTULOS_ADICIONAR = ('Adicionar', 'Add', 'Agregar', 'Añadir', 'Добавить', 'Tambahkan',
                      'जोड़ें', 'Ajouter', 'Hinzufügen', 'Aggiungi', 'Ekle', 'Dodaj',
                      'Додати', 'Magdagdag', 'เพิ่ม', 'إضافة', '添加', '追加', '추가')

# 'Continuar' em outros idiomas (botão do modal de criação).
_ROTULOS_CONTINUAR = ('Continuar', 'Continue', 'Tiếp tục', 'Продолжить', 'Lanjutkan',
                      'जारी रखें', 'Continuer', 'Weiter', 'Continua', 'Devam', 'Dalej',
                      'Продовжити', 'Magpatuloy', 'ดำเนินการต่อ', 'متابعة', '继续', '続ける', '계속')

# JS: botão PRIMÁRIO (fundo AZUL da Meta) do diálogo em primeiro plano — sinal
# ESTRUTURAL idioma-agnóstico p/ o 'Continuar' quando o rótulo não casa.
# modo 'estado' → true/false (habilitado?) ou null se não achou; modo 'clicar' → bool.
_JS_PRIMARIO_DIALOGO = r"""(modo) => {
    const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
    const azul = el => { try {
        const m = (getComputedStyle(el).backgroundColor || '').match(/rgba?\(([^)]+)\)/);
        if (!m) return false;
        const p = m[1].split(',').map(x => parseFloat(x));
        const a = p.length > 3 ? p[3] : 1;
        return a > 0.5 && p[2] >= 170 && (p[2] - p[0]) >= 100 && (p[2] - p[1]) >= 40;
    } catch (e) { return false; } };
    const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
    if (!dl.length) return null;
    const raiz = dl[dl.length - 1];
    let prim = null;
    for (const b of raiz.querySelectorAll('[role="button"],button,[type="submit"]')) {
        if (!vis(b) || !(b.innerText || '').trim()) continue;
        if (!(azul(b) || [...b.querySelectorAll('*')].slice(0, 8).some(azul))) continue;
        if (prim && b.contains(prim)) continue;
        prim = b;   // o último (rodapé) e o mais interno
    }
    if (!prim) return null;
    const dis = prim.getAttribute('aria-disabled') === 'true' || prim.disabled === true
             || prim.getAttribute('disabled') !== null;
    if (modo === 'estado') return !dis;
    if (dis) return false;
    try { prim.scrollIntoView({ block: 'center' }); } catch (e) {}
    try { prim.click(); return true; } catch (e) { return false; }
}"""

# Texto que confirma o SUCESSO: é a etapa seguinte do wizard (escolher número).
# Chegar aqui significa que a WABA já nasceu — não precisamos do número.
_SUCESSO = (
    'escolha o número que deseja usar', 'escolha o numero que deseja usar',
    'usar somente um nome de exibição', 'usar somente um nome de exibicao',
    'adicionar um novo número', 'adicionar um novo numero',
    'choose the number you want to use',
)


# --------------------------------------------------------------------------- #
# Helpers de DOM (autocontidos, para o módulo ser portátil)
# --------------------------------------------------------------------------- #
def _s(callback_status, msg):
    logger.info("[WABA] %s", msg)
    if callback_status:
        try:
            callback_status(msg)
        except Exception:
            pass


def _texto_pagina(driver) -> str:
    try:
        t = (driver.evaluate_page(
            "() => (document.body && document.body.innerText || '').toLowerCase()") or '')
    except Exception:
        return ''
    # Conta fora do pt: soma a tradução pt-BR do primeiro plano → as frases PT dos
    # detectores (_SUCESSO, waba_existe, restrição, recurso…) valem em qualquer idioma.
    try:
        from server.tradutor_tela import com_traducao
        return com_traducao(driver, t)
    except Exception:
        return t


def _tem_texto(driver, textos, timeout=8) -> bool:
    """True se algum dos textos aparece na página (polling curto)."""
    alvos = [t.lower() for t in (textos if isinstance(textos, (list, tuple)) else [textos])]
    fim = time.time() + timeout
    while time.time() < fim:
        t = _texto_pagina(driver)
        if any(a in t for a in alvos):
            return True
        time.sleep(0.25)
    return False


def _clicar_texto(driver, textos, timeout=10, dentro_dialogo=False, rotulo='') -> bool:
    """Clica no elemento clicável cujo texto (ou aria-label) casa. Sobe do nó de
    texto até um ancestral clicável (role=button/menuitem/link), que é como a Meta
    monta os controles — clicar no <span> puro muitas vezes não dispara nada.

    Robusto: também casa por `aria-label` (o botão 'Adicionar' da Meta às vezes tem
    o rótulo só no aria-label, com o texto visível num filho). Ao esgotar o tempo,
    LOGA os controles visíveis da tela — é o que revela por que não achou."""
    alvos = [t.lower() for t in (textos if isinstance(textos, (list, tuple)) else [textos])]
    js = r"""(args) => {
        const alvos = args.alvos, soDialogo = args.soDialogo, diag = args.diag;
        const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
        const vis = el => {
            const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
        };
        let raiz = document;
        if (soDialogo) {
            const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
            if (dl.length) raiz = dl[dl.length - 1];
        }
        const clicaveis = '[role="button"],[role="menuitem"],[role="link"],button,a';
        const casa = (s) => alvos.some(a => s === a || s.startsWith(a) || s.includes(a));
        // 1) tenta pelos CONTROLES clicáveis (aria-label OU texto) — mais preciso.
        for (const el of raiz.querySelectorAll(clicaveis)) {
            if (!vis(el)) continue;
            const al = norm(el.getAttribute('aria-label'));
            const t = norm(el.innerText);
            if ((al && casa(al)) || (t && t.length <= 240 && casa(t))) {
                try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
                try { el.click(); if (!diag) return true; } catch (e) {}
                if (!diag) return true;
            }
        }
        // 2) fallback: qualquer elemento cujo texto casa → sobe p/ o clicável.
        if (!diag) {
            for (const el of raiz.querySelectorAll('div,span,a,button,label')) {
                if (!vis(el)) continue;
                const t = norm(el.innerText);
                if (!t || t.length > 240 || !casa(t)) continue;
                const alvo = el.closest(clicaveis) || el;
                try { alvo.scrollIntoView({ block: 'center' }); } catch (e) {}
                try { alvo.click(); return true; } catch (e) {}
                try { el.click(); return true; } catch (e) {}
            }
            return false;
        }
        // modo DIAGNÓSTICO: devolve os controles visíveis (rótulo/texto curto).
        const vistos = [];
        for (const el of raiz.querySelectorAll(clicaveis)) {
            if (!vis(el)) continue;
            const al = (el.getAttribute('aria-label') || '').trim();
            const t = (el.innerText || '').trim().slice(0, 40);
            const rot = al || t;
            if (rot) vistos.push(rot);
        }
        return { diag: true, url: location.href, vistos: vistos.slice(0, 25) };
    }"""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            if driver.evaluate_page(js, {'alvos': alvos, 'soDialogo': bool(dentro_dialogo), 'diag': False}):
                return True
        except Exception as e:
            logger.debug('[WABA] _clicar_texto(%s): %s', rotulo or alvos, e)
        time.sleep(0.3)
    # Esgotou: colhe o diagnóstico (o que a tela realmente tinha).
    try:
        d = driver.evaluate_page(js, {'alvos': alvos, 'soDialogo': bool(dentro_dialogo), 'diag': True})
        if isinstance(d, dict):
            logger.warning("[WABA] '%s' não encontrado. URL=%s | controles: %r",
                           rotulo or (alvos[0] if alvos else '?'), d.get('url'), d.get('vistos'))
    except Exception:
        pass
    return False


def _definir_nome_exibicao(driver, nome: str) -> bool:
    """Escreve o nome de exibição no input CONTROLADO do React.

    O campo já vem preenchido com o nome do portfólio; atribuir `.value` direto
    não cola (o React re-renderiza por cima). Usamos o setter NATIVO + reset do
    `_valueTracker`, a mesma técnica do resto do projeto."""
    js = r"""(nome) => {
        const vis = el => {
            const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 40 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
        const raiz = dl.length ? dl[dl.length - 1] : document;
        const el = [...raiz.querySelectorAll('input')].find(i => {
            const t = (i.type || 'text').toLowerCase();
            return (t === 'text' || t === 'email') && !i.disabled && !i.readOnly && vis(i);
        });
        if (!el) return false;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        try { if (el._valueTracker) el._valueTracker.setValue(''); } catch (e) {}
        el.focus();
        setter.call(el, nome);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.blur();
        return (el.value || '') === nome;
    }"""
    try:
        return bool(driver.evaluate_page(js, nome))
    except Exception:
        return False


def _selecionar_categoria(driver, alvo='Outro', timeout=20) -> bool:
    """Abre o combobox 'Categoria', ROLA ATÉ O FIM da lista e marca a opção.

    'Outro' é o ÚLTIMO item e só é renderizado depois da rolagem (lista virtual/
    com scroll próprio) — por isso rolamos o container antes de procurar."""
    alvo_l = alvo.strip().lower()

    # 1) abre o combobox
    abrir = r"""() => {
        const vis = el => {
            const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
        const raiz = dl.length ? dl[dl.length - 1] : document;
        const cb = [...raiz.querySelectorAll('[role="combobox"],select')].filter(vis)[0];
        if (!cb) return false;
        try { cb.scrollIntoView({ block: 'center' }); } catch (e) {}
        cb.click();
        return true;
    }"""
    try:
        if not driver.evaluate_page(abrir):
            return False
    except Exception:
        return False
    time.sleep(0.6)

    # 2) rola a lista até o fim e clica na opção
    escolher = r"""(alvo) => {
        const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
        const vis = el => {
            const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
        };
        // container rolável que contém as opções
        const opts = [...document.querySelectorAll('[role="option"],[role="radio"]')].filter(vis);
        if (!opts.length) return 'sem_opcoes';
        let box = opts[0].parentElement;
        for (let i = 0; i < 6 && box; i++) {
            if (box.scrollHeight > box.clientHeight + 10) break;
            box = box.parentElement;
        }
        if (box) { try { box.scrollTop = box.scrollHeight; } catch (e) {} }
        const todas = [...document.querySelectorAll('[role="option"],[role="radio"]')].filter(vis);
        // casa exato; se não achar, usa a ÚLTIMA (que é 'Outro' na lista da Meta)
        let alvoEl = todas.find(o => norm(o.innerText) === alvo)
                  || todas.find(o => norm(o.innerText).startsWith(alvo));
        if (!alvoEl && todas.length) alvoEl = todas[todas.length - 1];
        if (!alvoEl) return 'nao_achou';
        try { alvoEl.scrollIntoView({ block: 'center' }); } catch (e) {}
        try { alvoEl.click(); } catch (e) {}
        const linha = alvoEl.closest('[role="option"],label,[role="button"]') || alvoEl;
        try { linha.click(); } catch (e) {}
        return norm(alvoEl.innerText) || 'ok';
    }"""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            r = driver.evaluate_page(escolher, alvo_l)
        except Exception:
            r = ''
        if r and r not in ('sem_opcoes', 'nao_achou'):
            logger.info("[WABA] Categoria escolhida: %r", r)
            return True
        time.sleep(0.5)
    return False


def _remover_site_do_modal(driver, callback_status=None) -> bool:
    """Expande 'Mostrar mais opções' e APAGA o campo 'Site · Opcional' do modal da
    WABA (usado quando o usuário escolhe NÃO vincular o site na WABA).

    A Meta pré-preenche o Site com o domínio da BM, mas o campo é OPCIONAL — a
    conta é criada mesmo sem ele. Apagar isola ainda mais o domínio-raiz do WhatsApp
    (o site fica só na verificação por domínio, não amarrado à WABA)."""
    _clicar_texto(driver, ['Mostrar mais opções', 'Mostrar mais opcoes',
                           'Show more options', 'Mais opções', 'Mais opcoes'],
                  timeout=6, dentro_dialogo=True)
    time.sleep(0.5)
    js = r"""() => {
        const vis = el => {
            const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 40 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
        const raiz = dl.length ? dl[dl.length - 1] : document;
        // O campo Site é o input type=url (ou o que tem 'http' no valor / rótulo 'Site').
        let el = [...raiz.querySelectorAll('input')].find(i =>
            (i.type || '').toLowerCase() === 'url' && vis(i) && !i.disabled && !i.readOnly);
        if (!el) {
            for (const lab of raiz.querySelectorAll('label,div,span')) {
                const t = ((lab.innerText) || '').toLowerCase();
                if (t.indexOf('site') === -1) continue;
                const i = lab.querySelector('input');
                if (i && vis(i) && !i.disabled && !i.readOnly) { el = i; break; }
            }
        }
        if (!el) el = [...raiz.querySelectorAll('input')].find(i =>
            /https?:\/\//i.test(i.value || '') && vis(i) && !i.disabled && !i.readOnly);
        if (!el) return 'sem_campo';
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        try { if (el._valueTracker) el._valueTracker.setValue('x'); } catch (e) {}
        el.focus();
        setter.call(el, '');                       // apaga o site pré-preenchido
        el.dispatchEvent(new Event('input',  { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.blur();
        return (el.value || '') === '' ? 'limpo' : ('resta:' + el.value);
    }"""
    try:
        r = driver.evaluate_page(js)
    except Exception as e:
        logger.warning('[WABA] limpar site falhou: %s', e)
        return False
    logger.info('[WABA] campo Site -> %s', r)
    _s(callback_status, '🚫 Site removido da WABA (não vinculado).')
    return r == 'limpo'


def _resolver_captcha(driver, callback_status=None, captcha_token='') -> bool:
    """Resolve o reCAPTCHA 'Não sou um robô' do modal via CapSolver.
    Retorna True se resolveu OU se não havia captcha na tela."""
    try:
        if captcha_token:
            # o solver lê o token daqui
            driver._pm_captcha_token = captcha_token
    except Exception:
        pass
    try:
        from server.captcha_solver import resolver_captcha_se_preciso
    except Exception as e:
        _s(callback_status, f'⚠️ CapSolver indisponível: {e}')
        return False
    try:
        r = resolver_captcha_se_preciso(driver, callback_status=callback_status,
                                        timeout=180, aguardar_widget_seg=20)
    except Exception as e:
        logger.warning('[WABA] captcha: %s', e)
        return False
    logger.info('[WABA] captcha -> %s', r)
    return r in ('no_captcha', 'resolvido')


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def _url_atual(driver) -> str:
    try:
        return (driver.current_url or '').lower()
    except Exception:
        try:
            return (driver.evaluate_page("() => location.href") or '').lower()
        except Exception:
            return ''


# Pop-up INFORMATIVO da Meta (2026-10) em Configurações → Contas do WhatsApp:
# "Updates to your account / We've updated the account structure for WhatsApp Business
# Platform… Messaging account…" com paginação "1 de 2" + Avançar e um X. Fica sobre a
# lista e atrapalha leitura de status/Adicionar. Detecção: dialog VISÍVEL, SEM campo de
# formulário/captcha, que cita "WhatsApp" e tem paginação "N de M" ou texto da nova
# estrutura. Marca o X (aria-label "Fechar/Close" multi-idioma, senão o botão-ícone do
# canto superior direito) com data-gs-upd-x; se não houver X, marca o botão de avanço.
_JS_POPUP_ATUALIZACAO_WA = r"""() => {
    const vis = e => { if (!e) return false; const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
    document.querySelectorAll('[data-gs-upd-x]').forEach(e => e.removeAttribute('data-gs-upd-x'));
    if ((location.pathname || '').indexOf('/dialog/oauth') !== -1) return '';
    const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis).reverse();
    for (const d of dlgs) {
        if (d.querySelector('input,select,textarea,[role="combobox"],[role="radio"],[role="textbox"],[role="listbox"],iframe[src*="recaptcha"]')) continue;
        const raw = d.innerText || '', t = raw.toLowerCase();
        if (t.indexOf('whatsapp') === -1) continue;
        const pager = /(^|\n)\s*\d\s*(de|of|\/|из|dari|của|trên|sur|von|di|z|จาก|من|中的)\s*\d\s*($|\n)/i.test(raw);
        const kws = ['messaging account', 'conta de mensagens', 'conta de mensagem', 'cuenta de mensajes',
                     'updates to your account', 'atualizações na sua conta', 'atualizações da sua conta',
                     'atualizacoes na sua conta', 'account structure', 'estrutura da conta',
                     'estructura de la cuenta', 'actualizaciones de tu cuenta'];
        if (!pager && !kws.some(k => t.indexOf(k) !== -1)) continue;
        const CLOSE = ['close', 'fechar', 'cerrar', 'đóng', 'закрыть', 'tutup', 'बंद', 'fermer', 'schließen',
                       'chiudi', 'kapat', 'zamknij', 'закрити', 'isara', 'ปิด', 'إغلاق', '关闭', '關閉', '閉じる', '닫기'];
        const btns = [...d.querySelectorAll('[role="button"],button,[aria-label]')].filter(vis);
        let alvo = btns.find(b => { const a = (b.getAttribute('aria-label') || '').trim().toLowerCase();
            return a && a.length <= 30 && CLOSE.some(c => a === c || a.indexOf(c) === 0); });
        if (!alvo) {
            const dr = d.getBoundingClientRect();
            alvo = btns.filter(b => !(b.innerText || '').trim()).find(b => { const r = b.getBoundingClientRect();
                return r.top < dr.top + 90 && r.left > dr.left + dr.width * 0.6 && r.width < 72; });
        }
        let modo = 'x';
        if (!alvo) {  // sem X: avança o carrossel (último botão com texto, habilitado)
            const nav = btns.filter(b => (b.innerText || '').trim() && b.getAttribute('aria-disabled') !== 'true' && !b.disabled);
            alvo = nav[nav.length - 1]; modo = 'nav';
        }
        if (!alvo) return '';
        alvo.setAttribute('data-gs-upd-x', '1');
        return modo + ':' + raw.replace(/\s+/g, ' ').slice(0, 80);
    }
    return '';
}"""


def dispensar_popup_atualizacao_whatsapp(driver, tentativas=4) -> bool:
    """Fecha o pop-up "Updates to your account" (nova estrutura WhatsApp account /
    Messaging account) se estiver na tela. Idempotente e barato (1 evaluate quando não
    há pop-up). Retorna True se fechou algo. Nunca levanta."""
    fechou = False
    for _ in range(max(1, int(tentativas))):
        try:
            achado = driver.evaluate_page(_JS_POPUP_ATUALIZACAO_WA) or ''
        except Exception:
            achado = ''
        if not achado:
            break
        logger.info("[WABA] pop-up 'atualização da conta WhatsApp' → fechando (%s)", achado[:90])
        try:
            driver.locator('[data-gs-upd-x="1"]').first.click(timeout=4000)
        except Exception:
            try:
                driver.evaluate_page("() => { const b = document.querySelector('[data-gs-upd-x=\"1\"]'); if (b) b.click(); }")
            except Exception:
                pass
        fechou = True
        time.sleep(0.8)
    return fechou


def _ir_para_contas_whatsapp(driver, business_id, callback_status=None, timeout=30) -> bool:
    """Navega para 'Contas do WhatsApp' e SÓ retorna True quando a URL é
    whatsapp_account E a página assentou (o botão 'Adicionar' aparece ou a lista
    renderizou). Sem isso, o clique em 'Adicionar' rodava contra a página anterior
    (business_info/ad_accounts) e falhava em silêncio — causa do 'Adicionar não
    encontrado' com a WABA nunca criada."""
    alvo = f"{BASE_FB}/latest/settings/whatsapp_account?business_id={business_id}"
    for tentativa in range(2):
        if 'whatsapp_account' not in _url_atual(driver):
            try:
                driver.goto(alvo)
            except Exception:
                try:
                    driver.get(alvo)
                except Exception:
                    pass
        # Espera assentar: URL certa + (texto da página OU botão Adicionar montado).
        fim = time.time() + timeout
        while time.time() < fim:
            if 'whatsapp_account' in _url_atual(driver):
                dispensar_popup_atualizacao_whatsapp(driver)
                t = _texto_pagina(driver)
                pronto = ('contas do whatsapp' in t or 'whatsapp accounts' in t
                          or 'nenhuma conta do whatsapp' in t)
                try:
                    tem_add = bool(driver.evaluate_page(r"""(rot) => {
                        const vis = el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                            return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
                        for (const el of document.querySelectorAll('[role="button"],button,div[role="button"]')) {
                            if (!vis(el)) continue;
                            const s = ((el.getAttribute('aria-label')||'') + ' ' + (el.innerText||'')).toLowerCase();
                            if (s.indexOf('adicionar')!==-1 || s.indexOf('add')!==-1) return true;
                            // 'Adicionar' em outros idiomas (conta fora do pt/en nunca "assentava")
                            if (rot.some(r => s.indexOf(r) !== -1)) return true;
                        }
                        return false;
                    }""", [r.lower() for r in _ROTULOS_ADICIONAR]))
                except Exception:
                    tem_add = False
                if pronto or tem_add:
                    return True
            time.sleep(0.4)
        # deu timeout — força re-navegação numa 2ª tentativa
    logger.warning("[WABA] não consegui assentar em Contas do WhatsApp (url=%s)", _url_atual(driver))
    return False


def _sitekey_do_widget(driver) -> str:
    """Lê o sitekey do reCAPTCHA VISÍVEL do modal (o 'Não sou um robô'). Prioriza o
    iframe do anchor (src tem ?k=SITEKEY) — mais preciso que um data-sitekey qualquer
    da página, que pode ser de outro widget e devolver um token que o modal rejeita."""
    js = r"""() => {
        for (const f of document.querySelectorAll('iframe[src*="recaptcha"]')) {
            const m = (f.src || '').match(/[?&]k=([^&]+)/);
            if (m) return decodeURIComponent(m[1]);
        }
        for (const e of document.querySelectorAll('[data-sitekey]')) {
            const r = e.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return e.getAttribute('data-sitekey');
        }
        const any = document.querySelector('[data-sitekey]');
        return any ? any.getAttribute('data-sitekey') : '';
    }"""
    try:
        return driver.evaluate_page(js) or ''
    except Exception:
        return ''


def _continuar_habilitado(driver) -> bool:
    """True se o botão 'Continuar' do modal está HABILITADO — o sinal (acessível no
    doc principal) de que o captcha foi ACEITO. O checkbox do reCAPTCHA fica num
    iframe cross-origin do Google, então não dá para ler o aria-checked dele daqui;
    o estado do 'Continuar' é o proxy confiável."""
    js = r"""() => {
        const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
        const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
        const raiz = dl.length ? dl[dl.length - 1] : document;
        for (const el of raiz.querySelectorAll('[role="button"],button,[type="submit"]')) {
            if (!vis(el)) continue;
            const t = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
            if (t.includes('continuar') || t.includes('continue')) {
                const dis = el.getAttribute('aria-disabled') === 'true'
                         || el.disabled === true || el.getAttribute('disabled') !== null;
                return !dis;
            }
        }
        return null;   // nenhum botão com rótulo PT/EN → o Python tenta os outros sinais
    }"""
    try:
        r = driver.evaluate_page(js)
        if r is not None:
            return bool(r)
    except Exception:
        return False
    # Conta em outro idioma (2026-10-12): sem rótulo 'continuar/continue' isto devolvia
    # SEMPRE False → o captcha era re-resolvido 3x (custo CapSolver) e a WABA falhava.
    # 1) rótulo traduzido; 2) botão PRIMÁRIO (azul) do diálogo — estrutural.
    try:
        r = driver.evaluate_page(r"""(rot) => {
            const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
            const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
            const raiz = dl.length ? dl[dl.length - 1] : document;
            for (const el of raiz.querySelectorAll('[role="button"],button,[type="submit"]')) {
                if (!vis(el)) continue;
                const t = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
                if (rot.some(x => t.includes(x))) {
                    return !(el.getAttribute('aria-disabled') === 'true'
                             || el.disabled === true || el.getAttribute('disabled') !== null);
                }
            }
            return null;
        }""", [x.lower() for x in _ROTULOS_CONTINUAR])
        if r is not None:
            return bool(r)
        return bool(driver.evaluate_page(_JS_PRIMARIO_DIALOGO, 'estado'))
    except Exception:
        return False


def _resolver_e_confirmar_captcha(driver, callback_status, captcha_token,
                                  tentativas=3, timeout=180) -> bool:
    """Resolve o reCAPTCHA v2 CHECKBOX ('Não sou um robô') do modal da WABA e
    CONFIRMA que foi aceito (o 'Continuar' habilita).

    Tipo REAL (medido no DOM/texto da tela, 2026-07-31): a tela diz "Usamos o produto
    reCAPTCHA ENTERPRISE do Google" e há o checkbox "Não sou um robô" → é reCAPTCHA v2
    ENTERPRISE CHECKBOX. CapSolver: ReCaptchaV2EnterpriseTaskProxyLess (enterprise=True).
    Resolver como v2 normal (enterprise=False) FALHOU 3x — tipo errado.

    Diferença p/ o captcha da Central (Enterprise INVISIBLE): lá injetar o token
    basta. Aqui é CHECKBOX: injetar sozinho não marca o checkbox e FORÇAR o
    'Continuar' só REABRE o desafio. Então: resolvemos ENTERPRISE com o sitekey do
    widget, injetamos + disparamos o callback (inclui grecaptcha.enterprise), e
    VERIFICAMOS se o 'Continuar' habilitou. Se não, re-resolvemos com token FRESCO."""
    try:
        from server.capsolver_client import resolver_recaptcha
        # REUSA a injeção COMPROVADA da Central (resolve 100%): ela injeta o callback
        # em TODOS os frames — inclusive DENTRO do iframe cross-origin do reCAPTCHA,
        # onde o checkbox é marcado. O _injetar do captcha_solver PARAVA no 1º frame
        # (o doc principal), nunca chegando ao iframe do reCAPTCHA — por isso o
        # checkbox não marcava e o 'Continuar' não habilitava. Era ESTA a diferença.
        from server.etapa_verificacao_negocio import (
            _injetar_recaptcha, _aguardar_widget_recaptcha)
    except Exception as e:
        logger.warning('[WABA] captcha helpers indisponíveis: %s', e)
        return False
    tok_api = (captcha_token or getattr(driver, '_pm_captcha_token', '') or '').strip()
    if _continuar_habilitado(driver):
        return True                       # sem captcha nesta tela / já aceito
    # Modo central: o painel resolve com a chave do admin (token local vazio).
    try:
        from server.capsolver_client import token_necessario as _tok_nec
        _precisa_token = _tok_nec()
    except Exception:
        _precisa_token = True
    if not tok_api and _precisa_token:
        _s(callback_status, '❌ Sem token do CapSolver — não dá p/ resolver o captcha da WABA.')
        return False
    url = _url_atual(driver) or 'https://business.facebook.com/'
    for tent in range(1, tentativas + 1):
        # Espera o widget do reCAPTCHA montar 100% (igual à Central).
        try:
            _aguardar_widget_recaptcha(driver, timeout=25)
        except Exception:
            time.sleep(1.5)
        sk = _sitekey_do_widget(driver)
        _s(callback_status, f'🤖 Resolvendo captcha da WABA (Enterprise, tentativa {tent}/{tentativas})...')
        # reCAPTCHA v2 ENTERPRISE checkbox → enterprise=True. Só cai p/ v2 normal se falhar.
        res = resolver_recaptcha(tok_api, url, website_key=sk or None,
                                 enterprise=True, timeout=timeout)
        if not res.get('sucesso'):
            res = resolver_recaptcha(tok_api, url, website_key=sk or None,
                                     enterprise=False, timeout=timeout)
        if not res.get('sucesso'):
            logger.warning('[WABA] CapSolver falhou (tent %s): %s', tent, res.get('mensagem', ''))
            continue
        token = res.get('token', '')
        # Injeta em TODOS os frames (padrão da Central), com retentativas, e checa se
        # o 'Continuar' habilitou a cada volta.
        fim = time.time() + 30
        while time.time() < fim:
            _injetar_recaptcha(driver, token)      # <-- injeção multi-frame (a que funciona)
            if _continuar_habilitado(driver):
                _s(callback_status, '✅ Captcha aceito — Continuar liberado.')
                return True
            time.sleep(1.5)
        logger.info('[WABA] token injetado (multi-frame) mas Continuar não habilitou — re-resolvendo (tent %s).', tent)
    return _continuar_habilitado(driver)


def _forcar_continuar(driver, callback_status=None, timeout=45) -> bool:
    """Clica 'Continuar' no modal da WABA e GARANTE o avanço.

    Problema real (2026-07-31): o CapSolver resolve e injeta o token do reCAPTCHA,
    mas no modal da WABA o checkbox 'Não sou um robô' às vezes NÃO marca visualmente
    e o React mantém o 'Continuar' DESABILITADO (aria-disabled). O fluxo ficava ~3min
    preso esperando a próxima tela.

    BYPASS: a cada volta (1) re-dispara os callbacks do reCAPTCHA (o token já está no
    textarea g-recaptcha-response — só falta o widget/React 'aceitá-lo'); (2) remove
    aria-disabled/disabled do botão 'Continuar'; (3) dispara a sequência REAL de
    eventos pointer/mouse (pointerdown→mousedown→pointerup→mouseup→click), que o React
    reconhece mesmo quando o .click() simples é ignorado. Para quando a tela AVANÇA
    (aparece a etapa do número = WABA criada)."""
    js = r"""() => {
        const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
        const vis = el => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
        // 1) RE-DISPARA os callbacks do reCAPTCHA com o token já presente no textarea.
        try {
            const ta = document.querySelector('textarea[name="g-recaptcha-response"],textarea#g-recaptcha-response,textarea[id^="g-recaptcha-response"]');
            const tok = ta && ta.value ? ta.value : '';
            if (tok) {
                const cfg = window.___grecaptcha_cfg;
                if (cfg && cfg.clients) {
                    Object.keys(cfg.clients).forEach(k => { const c = cfg.clients[k];
                        Object.keys(c || {}).forEach(k2 => { const o = c[k2];
                            if (o && typeof o === 'object') Object.keys(o).forEach(k3 => { const x = o[k3];
                                if (x && typeof x === 'object' && typeof x.callback === 'function') {
                                    try { x.callback(tok); } catch (e) {} } }); }); });
                }
                document.querySelectorAll('[data-callback]').forEach(w => {
                    const cb = w.getAttribute('data-callback');
                    if (cb && typeof window[cb] === 'function') { try { window[cb](tok); } catch (e) {} } });
            }
        } catch (e) {}
        // 2) acha o botão 'Continuar' no diálogo em primeiro plano.
        const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
        const raiz = dl.length ? dl[dl.length - 1] : document;
        let btn = null;
        for (const el of raiz.querySelectorAll('[role="button"],button,[type="submit"]')) {
            if (!vis(el)) continue;
            const t = norm(el.innerText) + ' ' + norm(el.getAttribute('aria-label'));
            if (t.includes('continuar') || t.includes('continue')) { btn = el; break; }
        }
        if (!btn) return 'sem_botao';
        const estavaDisabled = (btn.getAttribute('aria-disabled') === 'true'
                                || btn.disabled === true || btn.getAttribute('disabled') !== null);
        // 3) FORÇA: remove disabled do botão e de ancestrais próximos.
        let node = btn;
        for (let i = 0; i < 3 && node; i++) {
            try { node.removeAttribute('aria-disabled'); } catch (e) {}
            try { node.removeAttribute('disabled'); } catch (e) {}
            try { node.disabled = false; } catch (e) {}
            node = node.parentElement;
        }
        // 4) sequência REAL de eventos (o React escuta pointer/mouse).
        try { btn.scrollIntoView({ block: 'center' }); } catch (e) {}
        const ptr = t => { try { btn.dispatchEvent(new PointerEvent(t, { bubbles: true, cancelable: true })); } catch (e) {} };
        const mou = t => { try { btn.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })); } catch (e) {} };
        try { btn.focus(); } catch (e) {}
        ptr('pointerover'); ptr('pointerenter'); ptr('pointerdown'); mou('mousedown');
        ptr('pointerup'); mou('mouseup'); mou('click');
        try { btn.click(); } catch (e) {}
        return estavaDisabled ? 'forcado' : 'clicado';
    }"""
    fim = time.time() + timeout
    ja_forcou = False
    while time.time() < fim:
        # Já avançou para a etapa do número? então a WABA nasceu.
        if _tem_texto(driver, list(_SUCESSO), timeout=1):
            return True
        try:
            r = driver.evaluate_page(js)
        except Exception as e:
            logger.debug('[WABA] forçar continuar: %s', e)
            r = ''
        if r == 'forcado' and not ja_forcou:
            _s(callback_status, '⏩ Continuar travado (captcha) — forçando o avanço...')
            ja_forcou = True
        elif r == 'sem_botao':
            logger.debug('[WABA] botão Continuar ainda não renderizou.')
        time.sleep(1.2)
    # Última verificação
    return _tem_texto(driver, list(_SUCESSO), timeout=2)


def waba_existe(driver, business_id, timeout=25) -> bool:
    """True se o portfólio JÁ tem alguma conta do WhatsApp. Evita criar 2 WABAs."""
    if not _ir_para_contas_whatsapp(driver, business_id, timeout=timeout):
        return False
    fim = time.time() + timeout
    while time.time() < fim:
        t = _texto_pagina(driver)
        if 'nenhuma conta do whatsapp adicionada' in t or 'no whatsapp accounts' in t:
            return False
        if 'contas do whatsapp' in t and 'nenhuma conta' not in t:
            # a lista renderizou e não está vazia
            try:
                n = driver.evaluate_page(
                    """() => document.querySelectorAll('[role="row"],[role="listitem"]').length""")
                if n and int(n) > 0:
                    return True
            except Exception:
                pass
        time.sleep(0.5)
    return False


def criar_waba(driver, business_id, nome_exibicao='', categoria='Outro',
               callback_status=None, captcha_token='', timeout_total=240,
               usar_site=True) -> dict:
    """Cria a WABA pelo Meta Business Suite. Retorna:
        {'ok': bool, 'ja_existia': bool, 'mensagem': str}

    `nome_exibicao` vazio = mantém o que a Meta já preencheu (a razão social do
    portfólio), que é o comportamento desejado na maioria dos fluxos.

    `usar_site` (toggle da UI 'Usar site na WABA'):
      True  (padrão) → mantém o Site que a Meta pré-preenche (domínio da BM).
      False → expande 'Mostrar mais opções' e APAGA o campo Site. Como o Site é
              opcional, a WABA é criada sem ele — isola mais o domínio-raiz do
              WhatsApp (o site fica só na verificação por domínio).
    """
    res = {'ok': False, 'ja_existia': False, 'mensagem': ''}
    t0 = time.time()

    # 0) já existe? então não há o que fazer.
    if waba_existe(driver, business_id):
        res.update(ok=True, ja_existia=True, mensagem='WABA já existia no portfólio.')
        _s(callback_status, '✅ WABA já existe neste portfólio.')
        return res

    # 1) GARANTE a tela 'Contas do WhatsApp' (o botão 'Adicionar' só existe nela) e
    #    então clica em 'Adicionar' → 'Crie uma conta...'.
    _s(callback_status, '🟢 Criando WABA pelo Meta Business Suite...')
    if not _ir_para_contas_whatsapp(driver, business_id, callback_status):
        res['mensagem'] = "Não consegui abrir 'Contas do WhatsApp'."
        return res
    if not _clicar_texto(driver, list(_ROTULOS_ADICIONAR), timeout=20, rotulo='Adicionar'):
        res['mensagem'] = "Botão 'Adicionar' não encontrado em Contas do WhatsApp."
        return res
    time.sleep(1.0)
    if not _clicar_texto(driver, list(_OPCAO_CRIAR), timeout=15, rotulo='Crie uma conta WABA'):
        res['mensagem'] = "Opção 'Crie uma nova conta do WhatsApp Business' não encontrada."
        return res

    # 2) modal 'Criar uma conta do WhatsApp Business'. Texto PT/EN OU sinal estrutural
    #    idioma-agnóstico: diálogo visível com a MARCA 'WhatsApp' (não se traduz) e um
    #    campo editável (o Nome de exibição). (2026-10-12)
    _js_modal = r"""() => {
        const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
        const dl = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
        if (!dl.length) return false;
        const raiz = dl[dl.length - 1];
        if (((raiz.innerText || '').toLowerCase()).indexOf('whatsapp') === -1) return false;
        return [...raiz.querySelectorAll('input')].some(i =>
            vis(i) && !i.disabled && ['text', 'email', ''].includes((i.type || '').toLowerCase()));
    }"""
    _modal_ok = False
    _t_modal = time.time()
    _fim_modal = _t_modal + 25
    while time.time() < _fim_modal and not _modal_ok:
        if _tem_texto(driver, ['criar uma conta do whatsapp business',
                               'create a whatsapp business account'], timeout=1):
            _modal_ok = True
            break
        # estrutural só depois de dar ~5s ao texto PT/EN (não muda o caminho PT/EN,
        # em que o título aparece em 1-3s)
        if time.time() - _t_modal >= 5:
            try:
                _modal_ok = bool(driver.evaluate_page(_js_modal))
            except Exception:
                _modal_ok = False
        if not _modal_ok:
            time.sleep(0.4)
    if not _modal_ok:
        res['mensagem'] = 'O modal de criação da WABA não abriu.'
        return res
    _s(callback_status, '📝 Modal aberto — preenchendo os detalhes...')
    time.sleep(0.8)

    if nome_exibicao:
        if _definir_nome_exibicao(driver, nome_exibicao):
            logger.info('[WABA] Nome de exibição definido: %s', nome_exibicao)
        else:
            logger.warning('[WABA] Não consegui definir o nome — mantendo o da Meta.')

    # 3) Categoria → 'Outro'. REUSA a função MADURA do DataCrazy (mesmo modal do
    #    WhatsApp Business): abre a combobox por PROXIMIDADE do rótulo 'Categoria'
    #    (a combobox vem vazia, sem texto interno — achá-la por texto falhava),
    #    rola a lista até 'Outro' (último item) e confirma. Com fallbacks + dump de
    #    diagnóstico. Minha _selecionar_categoria fica só como último recurso.
    cat_ok = False
    try:
        from server.etapa_full_datacrazy import _selecionar_categoria_outro
        cat_ok = bool(_selecionar_categoria_outro(driver, timeout=25))
    except Exception as e:
        logger.warning('[WABA] _selecionar_categoria_outro (DataCrazy) falhou: %s', e)
    if not cat_ok:
        logger.info('[WABA] categoria via DataCrazy não confirmou — tentando fallback próprio.')
        cat_ok = _selecionar_categoria(driver, categoria)
    if not cat_ok:
        res['mensagem'] = f"Não consegui selecionar a categoria '{categoria}'."
        return res
    _s(callback_status, f'🏷️ Categoria: {categoria}')
    time.sleep(0.5)

    # 3b) Toggle 'Usar site na WABA' = Não → remove o Site (é opcional).
    if not usar_site:
        _remover_site_do_modal(driver, callback_status)
        time.sleep(0.4)

    # 4) reCAPTCHA v2 CHECKBOX ('Não sou um robô'). Resolve e CONFIRMA que o widget
    #    aceitou (o 'Continuar' habilita) — re-resolvendo com token fresco se preciso.
    #    NÃO forçamos o clique: forçar reabre o desafio de imagem (medido no teste).
    if not _resolver_e_confirmar_captcha(driver, callback_status, captcha_token):
        res['mensagem'] = ("Captcha da WABA não foi aceito (o 'Continuar' não habilitou). "
                           "O token do CapSolver não marcou o 'Não sou um robô'.")
        return res
    time.sleep(0.6)

    # 5) 'Continuar' — agora HABILITADO (captcha aceito). Clique normal.
    _s(callback_status, '⏭️ Confirmando criação da WABA (Continuar)...')
    if not _clicar_texto(driver, list(_ROTULOS_CONTINUAR), timeout=15,
                         dentro_dialogo=True, rotulo='Continuar'):
        # fallback ESTRUTURAL idioma-agnóstico: botão primário (azul) habilitado do modal
        _clicou_prim = False
        try:
            _clicou_prim = bool(driver.evaluate_page(_JS_PRIMARIO_DIALOGO, 'clicar'))
        except Exception:
            _clicou_prim = False
        if not _clicou_prim:
            res['mensagem'] = "Botão 'Continuar' não pôde ser clicado."
            return res

    # 6) chegou em 'Escolha o número que deseja usar' = WABA CRIADA.
    if not _tem_texto(driver, list(_SUCESSO),
                      timeout=max(30, int(timeout_total - (time.time() - t0)))):
        res['mensagem'] = ("Não cheguei na tela 'Escolha o número' — a WABA pode não "
                           "ter sido criada.")
        return res
    _s(callback_status, '✅ WABA criada (tela de escolha do número alcançada).')

    # 7) fecha o modal e recarrega para a lista/Central refletirem a WABA nova
    _clicar_texto(driver, ['Fechar', 'Close', '✕', 'X'], timeout=5, dentro_dialogo=True)
    try:
        driver.evaluate_page(
            """() => { const b=[...document.querySelectorAll('[aria-label]')]
                 .find(e=>/fechar|close/i.test(e.getAttribute('aria-label')||''));
                 if(b) b.click(); }""")
    except Exception:
        pass
    time.sleep(1.0)
    try:
        driver.refresh()
    except Exception:
        pass
    time.sleep(2.5)

    if waba_existe(driver, business_id):
        res.update(ok=True, mensagem='WABA criada e confirmada na lista.')
        _s(callback_status, '✅ WABA confirmada em Contas do WhatsApp.')
    else:
        # o wizard chegou ao fim; às vezes a lista demora a indexar.
        res.update(ok=True, mensagem=('WABA criada (tela de número alcançada), mas a lista '
                                      'ainda não refletiu — seguir e checar a Central.'))
        _s(callback_status, '⚠️ WABA criada, mas a lista ainda não atualizou.')
    return res


def central_tem_iniciar_verificacao(driver, business_id, timeout=30) -> bool:
    """True se a Central de Segurança já exibe 'Iniciar verificação' — o sinal de
    que a WABA destravou a verificação e o fluxo pode seguir para a análise."""
    try:
        driver.goto(f"{BASE_FB}/latest/settings/security_center?business_id={business_id}")
    except Exception:
        try:
            driver.get(f"{BASE_FB}/latest/settings/security_center?business_id={business_id}")
        except Exception:
            return False
    return _tem_texto(driver, ['iniciar verificação', 'iniciar verificacao',
                               'start verification', 'continuar verificação',
                               'continuar verificacao'], timeout=timeout)
