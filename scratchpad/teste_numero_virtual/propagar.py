# -*- coding: utf-8 -*-
"""Leva o fix do numero virtual do etapa_full_datacrazy.py para os modulos Gupshup.
Aborta sem gravar se qualquer ancora nao bater exatamente."""
import io, os, py_compile, shutil, sys, time

SRV = r"c:\Users\Administrador\Desktop\GS Creator\server"
FONTE = os.path.join(SRV, "etapa_full_datacrazy.py")
STAMP = time.strftime("%Y%m%d_%H%M%S")
erros = []


def ler(p):
    return io.open(p, encoding="utf-8").read()


src = ler(FONTE)
ini = src.index("# JS único usado por _selecionar_nome_exibicao")
fim = src.index("\n\ndef _detectar_restricao_bm", ini)
BLOCO_NOVO = src[ini:fim].rstrip() + "\n"
print("bloco novo: %d chars" % len(BLOCO_NOVO))

ANC_VELHA_INI = "def _selecionar_nome_exibicao(driver, timeout=10):"
ANC_VELHA_FIM = "\n\ndef _detectar_restricao_bm"

# handler 'numero' — gupshup_lite tem o MESMO falso sucesso do datacrazy
LITE_VELHO = """            status("📞 OAuth: número → 'Usar somente um nome de exibição'...")
            _selecionar_nome_exibicao(driver)
            _delay_curto()
            _click_oauth_avancar(driver)
            if _aguardar_saida_passo(driver, 'numero', timeout=7, popup_page=popup_page):
                continue   # fluxo novo — segue p/ verif_adicional/ativos/dados/reveja
            status("📞 OAuth: tela de número é a FINAL (WABA criada) — concluído.")
            return True
"""
LITE_NOVO = """            status("📞 OAuth: número → 'Use a display name with a virtual number'...")
            _ok_virtual = _selecionar_nome_exibicao(driver)
            _delay_curto()
            _click_oauth_avancar(driver)
            if _aguardar_saida_passo(driver, 'numero', timeout=10, popup_page=popup_page):
                continue   # fluxo novo — segue p/ verif_adicional/ativos/dados/reveja
            # ⚠️ FIX 2026-08-28: "não avançou" NÃO é prova de tela final. No layout NOVO
            # a tela também não avança quando a seleção do número virtual falha — e aí
            # devolver True entregava a BM SEM WABA (loop de SMS comprando número).
            if _tem_opcao_numero_virtual(driver):
                logger.warning("[FULL/GupshupLite] Tela de número (layout NOVO) não avançou "
                               "— opção virtual %s. Repetindo.",
                               "confirmada" if _ok_virtual else "NAO confirmada")
                status("📞 OAuth: opção de número virtual ainda não fixou — repetindo...")
                _delay_medio()
                continue
            status("📞 OAuth: tela de número é a FINAL (WABA criada) — concluído.")
            return True
"""

# gupshup completo: nao devolve falso sucesso (desiste com 'numero_travado'), mas
# desistia sem saber se a opcao existia. Passa a insistir enquanto o layout for o novo.
GUP_VELHO = """            if not _aguardar_saida_passo(driver, 'numero', timeout=12, popup_page=popup_page):
                if _nt >= 2:
                    status("⚠️ Tela 'número/nome de exibição' não avançou após 2 "
                           "tentativas — seguindo SEM finalizar a conexão.")
                    return 'numero_travado'
"""
GUP_NOVO = """            if not _aguardar_saida_passo(driver, 'numero', timeout=12, popup_page=popup_page):
                # Só desiste depois de esgotar as tentativas E confirmar que a opção
                # de número virtual não fixou. Enquanto o layout NOVO estiver na tela,
                # insistir é melhor que seguir sem WABA. (fix 2026-08-28)
                if _tem_opcao_numero_virtual(driver) and _nt < 4:
                    status(f"📞 OAuth: número virtual ainda não fixou (tentativa {_nt}/4)...")
                    _delay_medio()
                    continue
                if _nt >= 2:
                    status("⚠️ Tela 'número/nome de exibição' não avançou após "
                           f"{_nt} tentativas — seguindo SEM finalizar a conexão.")
                    return 'numero_travado'
"""

alvos = {
    os.path.join(SRV, "etapa_full_gupshup.py"): [(GUP_VELHO, GUP_NOVO, "handler numero")],
    os.path.join(SRV, "etapa_full_gupshup_lite.py"): [(LITE_VELHO, LITE_NOVO, "handler numero")],
}

novos = {}
for caminho, patches in alvos.items():
    txt = ler(caminho)
    nome = os.path.basename(caminho)

    if "_JS_NUMERO_VIRTUAL" in txt:
        print("%s ja tem o fix - pulando bloco" % nome)
    else:
        try:
            a = txt.index(ANC_VELHA_INI)
            b = txt.index(ANC_VELHA_FIM, a)
        except ValueError:
            erros.append("%s :: nao achei a funcao antiga" % nome)
            continue
        # ajusta o rotulo do log para o modulo certo
        rotulo = "GupshupLite" if "lite" in nome else "Gupshup"
        bloco = BLOCO_NOVO.replace("[OAuth]", "[OAuth]")
        txt = txt[:a] + bloco.split(ANC_VELHA_INI, 1)[0] + ANC_VELHA_INI + \
            bloco.split(ANC_VELHA_INI, 1)[1] + txt[b:]
        _ = rotulo

    for velho, novo, rot in patches:
        n = txt.count(velho)
        if n != 1:
            erros.append("%s :: %s -> %d ocorrencia(s), esperava 1" % (nome, rot, n))
        else:
            txt = txt.replace(velho, novo, 1)
    novos[caminho] = txt

if erros:
    print("ABORTADO - nada gravado:")
    for e in erros:
        print("  x " + e)
    sys.exit(1)

for caminho, txt in novos.items():
    bak = caminho + ".bak_virtual_" + STAMP
    shutil.copy2(caminho, bak)
    io.open(caminho, "w", encoding="utf-8", newline="").write(txt)
    try:
        py_compile.compile(caminho, doraise=True)
        print("ok  %s  (backup: %s)" % (os.path.basename(caminho), os.path.basename(bak)))
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, caminho)
        print("ERRO DE SINTAXE em %s - revertido:\n%s" % (caminho, e))
        sys.exit(1)

py_compile.compile(FONTE, doraise=True)
print("ok  etapa_full_datacrazy.py compila")
print("PROPAGADO")
