#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Driver de mapeamento AO VIVO do fluxo DataCrazy Pro Max Turbo (bot desktop).
Cria/abre o perfil AdsPower do .txt, conecta Playwright, e roda 1 comando por vez.
O objetivo: mapear SELETORES FIXOS (independentes de idioma) do diálogo
"Editar detalhes da empresa", da verificação de domínio e da criação da WABA.

Uso:
  python dc_map.py setup <caminho.txt>        cria+abre o perfil, imprime WS e profile_id
  python dc_map.py <ws> tabs
  python dc_map.py <ws> login                  estado de login (c_user)
  python dc_map.py <ws> goto <url> [urlsub]
  python dc_map.py <ws> shot [urlsub]
  python dc_map.py <ws> dumpdlg [urlsub]       DUMP estrutural do [role=dialog] aberto
  python dc_map.py <ws> js "<code>" [urlsub]
  python dc_map.py <ws> click "<css>" [urlsub]
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratchpad")
os.makedirs(SCRATCH, exist_ok=True)


def _pick(ctx, urlsub=""):
    pages = [p for p in ctx.pages if not (p.url or "").startswith("chrome-extension")]
    if urlsub:
        for p in pages:
            if urlsub.lower() in (p.url or "").lower():
                return p
    return pages[-1] if pages else ctx.pages[-1]


# DUMP estrutural do diálogo: lista TODOS os campos com atributos ESTÁVEIS
# (aria-*, role, type, autocomplete, name, data-*), a posição/ordem no DOM, o
# rótulo associado e se é combobox/select/input. É a base p/ escolher seletores
# que não dependem do TEXTO (idioma).
_JS_DUMPDLG = r"""() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
  const dlg = dlgs[dlgs.length - 1];
  if (!dlg) return { erro: 'sem dialog' };
  const attrs = el => { const o = {}; for (const a of el.attributes) {
    if (/^(aria-|data-|role|type|name|autocomplete|inputmode|placeholder|value|contenteditable|tabindex)/.test(a.name))
      o[a.name] = (a.value || '').slice(0, 60); } return o; };
  const rotulo = el => {
    // label[for], aria-labelledby, texto do container-linha
    let lb = '';
    if (el.id) { const l = dlg.querySelector('label[for="'+CSS.escape(el.id)+'"]'); if (l) lb = norm(l.innerText); }
    if (!lb && el.getAttribute('aria-labelledby')) { const l = document.getElementById(el.getAttribute('aria-labelledby')); if (l) lb = norm(l.innerText); }
    if (!lb) { let p = el; for (let i=0;i<4 && p;i++){ p = p.parentElement; if (p){ const t = norm(p.innerText); if (t && t.length < 60){ lb = t; break; } } } }
    return lb.slice(0, 50);
  };
  const campos = [];
  const sel = 'input, textarea, select, [role="combobox"], [role="textbox"], [contenteditable="true"], [role="listbox"], [role="button"][aria-haspopup]';
  [...dlg.querySelectorAll(sel)].filter(vis).forEach((el, i) => {
    campos.push({ i, tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '',
      label: rotulo(el), attrs: attrs(el),
      rect: (() => { const r = el.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })() });
  });
  const botoes = [...dlg.querySelectorAll('[role="button"], button')].filter(vis).map(b => ({
    txt: norm(b.innerText).slice(0, 30), attrs: attrs(b),
    disabled: b.getAttribute('aria-disabled') === 'true' || b.disabled === true }));
  return { titulo: norm(dlg.querySelector('h1,h2,[role=heading]') ? dlg.querySelector('h1,h2,[role=heading]').innerText : '').slice(0,60),
           n_campos: campos.length, campos, botoes };
}"""


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    if sys.argv[1] == "setup":
        from server import parser_perfis
        txt = sys.argv[2]
        engine = sys.argv[3] if len(sys.argv) > 3 else "adspower"
        if engine == "ixbrowser":
            from server import ixbrowser_api as api
        else:
            from server import adspower_api as api
            try:
                tok = open(r"C:\Users\Administrador\Desktop\GS BM CREATOR PRO MAX\config\Christian\adspower_token.txt", encoding="utf-8").read().strip()
                if hasattr(api, "configurar_api_key"): api.configurar_api_key(tok)
            except Exception as e:
                print("token adspower:", e)
        perfis = parser_perfis.parsear_arquivo_txt(txt)
        if not perfis:
            print("txt sem perfil"); return
        p = perfis[0]
        gid = 0
        try:
            if engine == "ixbrowser":
                gid = api.obter_ou_criar_grupo("GSProMax")
            else:
                for g in (api.listar_grupos() or []):
                    if (g.get("group_name") or "").lower() == "gspromax":
                        gid = g.get("group_id"); break
        except Exception as e:
            print("grupo:", e)
        r = api.criar_perfil(p, gid, None)
        print("criar_perfil:", {k: r.get(k) for k in ("sucesso", "profile_id", "reaproveitado", "mensagem")})
        pid = r.get("profile_id")
        if not pid:
            return
        o = api.abrir_navegador(pid, headless=False)
        print("abrir:", {k: o.get(k) for k in ("sucesso", "ws", "debugging_address", "mensagem")})
        print("PROFILE_ID=", pid)
        print("WS=", o.get("ws") or ("http://" + o.get("debugging_address", "")))
        return

    ws = sys.argv[1]; cmd = sys.argv[2] if len(sys.argv) > 2 else "tabs"
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        endpoint = ws if ws.startswith(("ws://", "http://")) else f"http://{ws}"
        browser = pw.chromium.connect_over_cdp(endpoint, timeout=30000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        args = sys.argv[3:]
        if cmd == "tabs":
            for i, pg in enumerate(ctx.pages):
                try: print(f"[{i}] {pg.url[:80]}  ::  {pg.title()[:50]}")
                except Exception: print(f"[{i}] {pg.url[:80]}")
            return
        if cmd == "login":
            pg = _pick(ctx, args[0] if args else "facebook")
            cu = [c for c in ctx.cookies() if c["name"] == "c_user"]
            print("url:", pg.url[:70]); print("c_user:", cu[0]["value"] if cu else "(sem login)")
            return
        if cmd == "goto":
            pg = _pick(ctx, args[1] if len(args) > 1 else "")
            pg.goto(args[0], wait_until="domcontentloaded", timeout=60000); time.sleep(3)
            print("url:", pg.url[:80]); print("title:", pg.title()[:60]); return
        if cmd == "shot":
            pg = _pick(ctx, args[0] if args else "")
            fn = os.path.join(SCRATCH, f"dc_{int(time.time())}.png")
            pg.screenshot(path=fn); print("URL=", pg.url[:70]); print("PNG=", fn); return
        if cmd == "kbd":
            pg = _pick(ctx, args[1] if len(args) > 1 else "")
            pg.keyboard.type(args[0], delay=80); time.sleep(1.2); print("digitado:", args[0]); return
        if cmd == "press":
            pg = _pick(ctx, args[1] if len(args) > 1 else "")
            for k in args[0].split(","):
                pg.keyboard.press(k.strip()); time.sleep(0.4)
            print("press:", args[0]); return
        if cmd == "esc":
            pg = _pick(ctx, args[0] if args else "")
            pg.keyboard.press("Escape"); time.sleep(1); print("esc"); return
        if cmd == "clicksurface":
            # mouse REAL no elemento cujo data-surface TERMINA em <suffix>
            pg = _pick(ctx, args[1] if len(args) > 1 else "")
            suf = args[0]
            xy = pg.evaluate(r"""(suf) => { const els=[...document.querySelectorAll('[data-surface]')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;});
              const el=els.find(e=>(e.getAttribute('data-surface')||'').endsWith(suf)); if(!el)return null; el.scrollIntoView({block:'center'});
              const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2,ds:el.getAttribute('data-surface').slice(-40)}; }""", suf)
            if not xy: print("surface nao achado:", suf); return
            pg.mouse.click(xy["x"], xy["y"]); time.sleep(3)
            print("clicado surface:", xy.get("ds")); return
        if cmd == "dumpdlg":
            pg = _pick(ctx, args[0] if args else "")
            print(json.dumps(pg.evaluate(_JS_DUMPDLG), ensure_ascii=False, indent=1)); return
        if cmd == "js":
            pg = _pick(ctx, args[1] if len(args) > 1 else "")
            print(json.dumps(pg.evaluate(args[0]), ensure_ascii=False, default=str)[:3000]); return
        if cmd == "click":
            pg = _pick(ctx, args[1] if len(args) > 1 else "")
            el = pg.query_selector(args[0])
            if not el: print("nao achei", args[0]); return
            el.click(); time.sleep(2); print("clicado", args[0]); return
        if cmd == "clicktext":
            # clique REAL (mouse) no 1º [role=button]/button/a cujo texto CONTÉM o alvo
            pg = _pick(ctx, args[1] if len(args) > 1 else "")
            alvo = args[0]
            xy = pg.evaluate(r"""(alvo) => { const n=s=>(s||'').toLowerCase().trim();
              const A=n(alvo); const c=[...document.querySelectorAll('[role=button],button,a[role=button],div[role=button]')].filter(e=>e.getBoundingClientRect().width>0);
              let el=c.find(e=>n(e.innerText)===A)||c.find(e=>n(e.innerText).indexOf(A)!==-1)||c.find(e=>n(e.getAttribute('aria-label')||'').indexOf(A)!==-1);
              if(!el) return null; el.scrollIntoView({block:'center'}); const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2,t:(el.innerText||'').slice(0,30)}; }""", alvo)
            if not xy: print("texto nao achado:", alvo); return
            pg.mouse.click(xy["x"], xy["y"]); time.sleep(3)
            print("clicado:", xy.get("t"), "| url:", pg.url[:60]); return
        print("cmd?", cmd)
    finally:
        pw.stop()


if __name__ == "__main__":
    main()
