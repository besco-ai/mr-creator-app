#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Roda o _rodar_fluxo_oauth REAL (criação da WABA via OAuth Turbo/Meta direto) na
conta #3199 (AdsPower, INGLÊS), para PROVAR/consertar a criação da WABA sem depender
de idioma. Abre um OAuth fresco e conduz o fluxo real do bot.
Uso:
  python tb_run.py <debug_addr> waba "<Razao Social>" [business_id] [site_url]
  python tb_run.py <debug_addr> passo         só detecta o passo atual (debug)
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass


def _drv(addr):
    from server.playwright_compat import conectar_playwright
    return conectar_playwright(addr)


def main():
    addr, cmd = sys.argv[1], sys.argv[2]
    d = _drv(addr)
    if d is None:
        print("driver None"); return
    import server.etapa_full_datacrazy as E

    if cmd == "passo":
        print("passo atual:", E._detectar_passo_oauth(d)); return

    if cmd == "num":
        print("passo:", E._detectar_passo_oauth(d), flush=True)
        print("tem_opcao_numero_virtual (existe):", E._tem_opcao_numero_virtual(d), flush=True)
        print("JS('existe'):", d.evaluate_page(E._JS_NUMERO_VIRTUAL, 'existe'), flush=True)
        r = E._selecionar_nome_exibicao(d, timeout=12)
        print("_selecionar_nome_exibicao:", r, flush=True)
        print("JS('selecionar') agora:", d.evaluate_page(E._JS_NUMERO_VIRTUAL, 'selecionar'), flush=True)
        # avança e checa saída
        E._click_oauth_avancar(d)
        import time as _t; _t.sleep(2)
        print("passo apos avancar:", E._detectar_passo_oauth(d), flush=True)
        return

    if cmd == "cat":
        print("abrir_combobox_categoria:", E._abrir_combobox_categoria(d, timeout=8), flush=True)
        import time as _t; _t.sleep(2)
        print("lista_categoria_aberta:", E._lista_categoria_aberta(d), flush=True)
        dump = d.evaluate_page(r"""() => { const norm=s=>(s||'').replace(/\s+/g,' ').trim();
            const opts=[...document.querySelectorAll('[role=option],[role=radio],li[role=option]')].filter(e=>e.getBoundingClientRect().width>0);
            const lbs=[...document.querySelectorAll('[role=listbox],[role=menu]')].filter(e=>e.getBoundingClientRect().width>0);
            return {n_listbox:lbs.length, n_opts:opts.length, primeiros:opts.map(o=>norm(o.innerText).slice(0,28)).filter(Boolean).slice(0,6),
                    ultimos:opts.map(o=>norm(o.innerText).slice(0,28)).filter(Boolean).slice(-6)}; }""")
        import json as _j; print("dump:", _j.dumps(dump, ensure_ascii=False), flush=True)
        print("selecionar_categoria_outro:", E._selecionar_categoria_outro(d, timeout=20), flush=True)
        print("categoria_ja_selecionada:", E._categoria_ja_selecionada(d), flush=True)
        return

    if cmd == "extra":
        def status(m): print("   ·", m, flush=True)
        E._preencher_dados_extra_oauth(d, sys.argv[3] if len(sys.argv) > 3 else "", status)
        import time as _t; _t.sleep(1)
        dump = d.evaluate_page(r"""() => { const norm=s=>(s||'').replace(/\s+/g,' ').trim();
            const dlg=[...document.querySelectorAll('[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).pop()||document.body;
            const combos=[...dlg.querySelectorAll('[role=combobox]')].filter(e=>e.getBoundingClientRect().width>0).map(c=>norm(c.innerText).slice(0,35));
            const next=[...dlg.querySelectorAll('[role=button],button')].filter(e=>e.getBoundingClientRect().width>0).find(b=>/next|avan|continu/i.test(b.innerText||''));
            return {combos, next_dis: next?(next.getAttribute('aria-disabled')==='true'||next.disabled):null}; }""")
        import json as _j; print("apos extra:", _j.dumps(dump, ensure_ascii=False), flush=True)
        return

    if cmd == "catlist":
        print("abrir:", E._abrir_combobox_categoria(d, timeout=8), flush=True)
        import time as _t; _t.sleep(2)
        allops = d.evaluate_page(r"""() => { const norm=s=>(s||'').replace(/\s+/g,' ').trim();
            const seen=new Set(); const push=arr=>{const lb=[...document.querySelectorAll('[role=listbox]')].filter(e=>e.getBoundingClientRect().width>0).pop();
              [...document.querySelectorAll('[role=option],[role=radio]')].filter(e=>e.getBoundingClientRect().width>0).forEach(o=>{const t=norm(o.innerText).slice(0,30); if(t)seen.add(t);});
              if(lb){lb.scrollTop=Math.min(lb.scrollTop+300, lb.scrollHeight);} };
            for(let i=0;i<12;i++){ push(); }
            return [...seen]; }""")
        import json as _j; print("TODAS AS CATEGORIAS:", _j.dumps(allops, ensure_ascii=False), flush=True)
        return

    if cmd == "dados":
        nome = sys.argv[3] if len(sys.argv) > 3 else "Comercio Bela Vista"
        print("passo:", E._detectar_passo_oauth(d), flush=True)
        print("_preencher_nome_negocio:", E._preencher_nome_negocio(d, nome), flush=True)
        print("_selecionar_categoria_outro:", E._selecionar_categoria_outro(d, timeout=20), flush=True)
        import time as _t; _t.sleep(1)
        E._click_oauth_avancar(d); _t.sleep(3)
        print("passo apos avancar:", E._detectar_passo_oauth(d), flush=True)
        return

    if cmd == "waba":
        razao = sys.argv[3] if len(sys.argv) > 3 else "Comercio Bela Vista"
        business_id = sys.argv[4] if len(sys.argv) > 4 else ""
        site_url = sys.argv[5] if len(sys.argv) > 5 else ""
        # fecha abas extras (deixa só a principal do FB) p/ começar limpo
        try:
            pages = list(d.context.pages)
            for pg in pages[1:]:
                try:
                    if "oauth" in (pg.url or "").lower() or "connect" in (pg.url or "").lower():
                        pg.close()
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(1)
        url = E._oauth_url_meta_datacrazy()
        print("abrindo OAuth:", url[:70], flush=True)
        aba = E._abrir_nova_aba(d, url)
        print("aba nova:", bool(aba), flush=True)
        try: E._esperar_estatico(d, timeout=30)
        except Exception: pass
        time.sleep(3)
        popup = getattr(d, "_current_page", None)

        def status(m):
            print("   ·", m, flush=True)

        # reauth de senha, se pedir
        try:
            if E._existe_texto(d, ['insira sua senha', 'enter your password'], timeout=3):
                status("reauth de senha…")
                E._preencher(d, 'input[name="pass"], input[type="password"]', "2t36SRD62Fy3ol9Nhn", timeout=8)
                E._click_texto(d, ['Continuar', 'Continue', 'Log In'], timeout=6)
                time.sleep(3)
        except Exception:
            pass

        print(">>> passo inicial:", E._detectar_passo_oauth(d), flush=True)
        r = E._rodar_fluxo_oauth(d, razao, status, popup_page=popup,
                                 timeout_total=480, site_url=site_url, business_id=business_id)
        print("RESULT _rodar_fluxo_oauth:", repr(r), flush=True)
        print("passo final:", E._detectar_passo_oauth(d), flush=True)
        try:
            u = d.evaluate_page("() => location.href")
            print("url final:", (u or "")[:90], flush=True)
        except Exception:
            pass
        return


if __name__ == "__main__":
    main()
