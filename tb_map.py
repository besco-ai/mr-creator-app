#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mapeia AO VIVO o fluxo TURBO (OAuth Meta direto) que cria a WABA, na conta #3199
(AdsPower, idioma INGLÊS). Abre o formulário OAuth real e faz dump estrutural das
telas — para construir seletores idioma-agnósticos.

Uso:
  python tb_map.py <debug_addr> abrir            abre a URL do OAuth Turbo (aba nova) + dump
  python tb_map.py <debug_addr> dump             dump estrutural da tela/popup atual
  python tb_map.py <debug_addr> tabs
  python tb_map.py <debug_addr> shot
  python tb_map.py <debug_addr> js "<code>"
  python tb_map.py <debug_addr> click "<css>"
  python tb_map.py <debug_addr> clicktext "<txt>"
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratchpad")
os.makedirs(SCRATCH, exist_ok=True)

# dump estrutural: título, headings, TODOS os botões (texto+aria+role+data-*),
# inputs/combobox/radios, e se há popup/dialog. Foco em atributos ESTÁVEIS (idioma-neutros).
_JS_DUMP = r"""() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width>2 && r.height>2 && s.visibility!=='hidden' && s.display!=='none'; };
  const norm = s => (s||'').replace(/\s+/g,' ').trim();
  const scope = (() => {
    const dlgs = [...document.querySelectorAll('[role=dialog]')].filter(vis);
    return dlgs.length ? dlgs[dlgs.length-1] : document.body;
  })();
  const heads = [...scope.querySelectorAll('h1,h2,h3,[role=heading]')].filter(vis)
    .map(h=>norm(h.innerText)).filter(Boolean).slice(0,6);
  const btns = [...scope.querySelectorAll('[role=button],button,a[role=button],input[type=submit]')]
    .filter(vis).map(b=>({t:norm(b.innerText||b.value).slice(0,40),
      al:(b.getAttribute('aria-label')||'').slice(0,40),
      name:b.getAttribute('name')||'', tid:b.getAttribute('data-testid')||'',
      dis:b.getAttribute('aria-disabled')==='true'||b.disabled===true})).slice(0,25);
  const fields = [...scope.querySelectorAll('input,textarea,select,[role=combobox],[role=radio],[role=checkbox],[role=switch]')]
    .filter(vis).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',
      type:e.getAttribute('type')||'', name:e.getAttribute('name')||'',
      al:(e.getAttribute('aria-label')||'').slice(0,40), ph:(e.getAttribute('placeholder')||'').slice(0,30),
      haspop:e.getAttribute('aria-haspopup')||'', checked:e.getAttribute('aria-checked')||''})).slice(0,25);
  return { url: location.href.slice(0,90), title: document.title.slice(0,50),
    temDialog: !!document.querySelector('[role=dialog]'),
    headings: heads, n_btns: btns.length, botoes: btns, campos: fields,
    corpo: norm(scope.innerText).slice(0,300) };
}"""


def _drv(addr):
    from server.playwright_compat import conectar_playwright
    return conectar_playwright(addr)


def main():
    addr, cmd = sys.argv[1], sys.argv[2]
    d = _drv(addr)
    if d is None:
        print("driver None"); return
    args = sys.argv[3:]

    if cmd == "abrir":
        from server.etapa_full_datacrazy import _oauth_url_meta_datacrazy, _abrir_nova_aba, _esperar_estatico
        url = _oauth_url_meta_datacrazy()
        print("URL:", url[:80], flush=True)
        aba = _abrir_nova_aba(d, url)
        print("aba nova:", bool(aba), flush=True)
        try: _esperar_estatico(d, timeout=30)
        except Exception: pass
        time.sleep(4)
        print(json.dumps(d.evaluate_page(_JS_DUMP), ensure_ascii=False, indent=1), flush=True)
        return
    if cmd == "dump":
        print(json.dumps(d.evaluate_page(_JS_DUMP), ensure_ascii=False, indent=1), flush=True); return
    if cmd == "tabs":
        for i, pg in enumerate(d.context.pages):
            try: print(f"[{i}] {pg.url[:80]}")
            except Exception: print(f"[{i}] ?")
        return
    if cmd == "shot":
        pg = d._current_page
        fn = os.path.join(SCRATCH, f"tb_{int(time.time())}.png")
        pg.screenshot(path=fn); print("URL=", pg.url[:70]); print("PNG=", fn); return
    if cmd == "js":
        print(json.dumps(d.evaluate_page(args[0]), ensure_ascii=False, default=str)[:3000]); return
    if cmd == "click":
        el = d.query_selector(args[0])
        if not el: print("nao achei", args[0]); return
        el.click(); time.sleep(2); print("clicado", args[0]); return
    if cmd == "clicktext":
        alvo = args[0]
        xy = d.evaluate_page(r"""(alvo) => { const n=s=>(s||'').toLowerCase().trim(); const A=n(alvo);
          const c=[...document.querySelectorAll('[role=button],button,a[role=button],div[role=button]')].filter(e=>e.getBoundingClientRect().width>0);
          let el=c.find(e=>n(e.innerText)===A)||c.find(e=>n(e.innerText).indexOf(A)!==-1);
          if(!el) return null; el.scrollIntoView({block:'center'}); const r=el.getBoundingClientRect();
          return {x:r.x+r.width/2,y:r.y+r.height/2,t:(el.innerText||'').slice(0,30)}; }""", alvo)
        if not xy: print("texto nao achado:", alvo); return
        d.mouse.click(xy["x"], xy["y"]); time.sleep(3)
        print("clicado:", xy.get("t")); return
    print("cmd?", cmd)


if __name__ == "__main__":
    main()
