#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Valida AO VIVO as funções corrigidas de verificacao_bm.py contra o navegador
ixBrowser JÁ ABERTO (perfil #3185, conta em INGLÊS, business_id do arg).
Uso:
  python dc_test.py <debug_addr> <business_id> abrir      abre 'Editar detalhes'
  python dc_test.py <debug_addr> <business_id> pais       roda _selecionar_pais_brasil (estrutural)
  python dc_test.py <debug_addr> <business_id> marcar     roda _marcar_campos_detalhes + dump
  python dc_test.py <debug_addr> <business_id> fluxo      abrir+pais+marcar (relatório completo)
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass


def _abrir_dialogo(d, bid):
    from server import verificacao_bm as vb
    d.get(f"https://business.facebook.com/latest/settings/business_info?business_id={bid}")
    time.sleep(6)
    vb._fechar_overlays_facebook(d); time.sleep(1)
    vb._scroll_suave(d, 'baixo', 350); time.sleep(1)
    btn = vb._encontrar_botao_editar_detalhes(d)
    if not btn:
        vb._scroll_suave(d, 'baixo', 400); time.sleep(1)
        btn = vb._encontrar_botao_editar_detalhes(d)
    if not btn:
        botoes = vb._encontrar_botoes_editar(d)
        btn = botoes[-1] if botoes else None
    if not btn:
        print("SEM botao editar detalhes"); return False
    vb._clicar_humano(d, btn); time.sleep(2)
    ok = vb._aguardar_popup(d, timeout=10)
    print("popup aberto:", ok, "| correto:", vb._verificar_popup_detalhes(d) if ok else None)
    return ok


def main():
    addr, bid, cmd = sys.argv[1], sys.argv[2], sys.argv[3]
    from server.playwright_compat import conectar_playwright
    from server import verificacao_bm as vb
    d = conectar_playwright(addr)
    if d is None:
        print("driver None"); return

    if cmd in ("abrir", "fluxo"):
        if not _abrir_dialogo(d, bid):
            return

    if cmd in ("pais", "fluxo"):
        antes = vb._pais_selecionado(d)
        r = vb._selecionar_pais_brasil(d)
        depois = vb._pais_selecionado(d)
        val = d.evaluate_page("""() => { const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
            if(!dlg) return ''; const cb=dlg.querySelector('[role=combobox][aria-haspopup=listbox]')||dlg.querySelector('[role=combobox]');
            return cb?(cb.innerText||'').trim():''; }""")
        print(f"PAIS antes={antes} retorno={r} depois={depois} valor='{val}'")

    if cmd in ("marcar", "fluxo"):
        vb._marcar_campos_detalhes(d)
        dump = d.evaluate_page("""() => { const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
            if(!dlg) return {}; const o={}; const ni=dlg.querySelectorAll('input[type=text],input:not([type]),input[type=tel],input[type=url]').length;
            dlg.querySelectorAll('[data-detalhe-campo]').forEach(e=>{ o[e.getAttribute('data-detalhe-campo')]=(e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.value||'').slice(0,40); });
            return {n_inputs:ni, campos:o}; }""")
        print("MARCAR:", json.dumps(dump, ensure_ascii=False))

    if cmd == "preencher":
        # Roda o preencher_info_empresa REAL com dados BR reais (conta em INGLÊS).
        # Prova: país selecionado, 9 campos preenchidos, Save ATIVA e o dialog FECHA.
        empresa = {
            'razao_social': 'Comercio de Alimentos Bela Vista Ltda',
            'logradouro': 'Avenida Paulista',
            'numero': '1578',
            'bairro': 'Bela Vista',
            'municipio': 'Sao Paulo',
            'uf': 'SP',
            'cep': '01310-200',
            'telefone': '+5511993456789',
            'url_completa': 'https://belavista-alimentos.com.br',
            'cnpj': '11222333000181',
        }
        r = vb.preencher_info_empresa(d, bid, empresa,
                                      callback_status=lambda m: print("   ", m, flush=True))
        print("RESULT preencher_info_empresa:", json.dumps(r, ensure_ascii=False), flush=True)
        # estado final do dialog (fechou?) + valores dos campos
        fim = d.evaluate_page("""() => { const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
            if(!dlg) return {dialog:false}; const o={}; dlg.querySelectorAll('[data-detalhe-campo]').forEach(e=>o[e.getAttribute('data-detalhe-campo')]=(e.value||'').slice(0,30));
            const cb=dlg.querySelector('[role=combobox][aria-haspopup=listbox]'); return {dialog:true, pais:cb?(cb.innerText||'').trim():'', campos:o}; }""")
        print("ESTADO FINAL:", json.dumps(fim, ensure_ascii=False), flush=True)
        return

    if cmd == "salvarcheck":
        # apenas identifica o botão primário (sem clicar de verdade seria melhor,
        # mas aqui só reporta qual seria escolhido)
        info = d.evaluate_page(r"""() => { const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop();
            if(!dlg) return null; const vis=e=>{const r=e.getBoundingClientRect();return r.width>4&&r.height>4;};
            const isDis=e=>e.getAttribute('aria-disabled')==='true'||e.disabled===true;
            let btns=[...dlg.querySelectorAll('[role=button],button')].filter(vis);
            return btns.map(b=>({t:(b.innerText||'').slice(0,16),dis:isDis(b),bg:getComputedStyle(b).backgroundColor})); }""")
        print("BOTOES:", json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
