# -*- coding: utf-8 -*-
"""Teste em DOM REAL (Chromium) da gravação CONFERIDA do Telefone comercial da BM
(`_definir_telefone_empresa`): digita, salva, recarrega, reabre e confere.
O mock persiste em localStorage e pode simular um save que FALHA EM SILÊNCIO."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from playwright.sync_api import sync_playwright
from server import etapa_verificacao_negocio as E

E._delay_medio = lambda *a, **k: time.sleep(0.2)
E._delay_curto = lambda *a, **k: time.sleep(0.05)
URL = 'https://mock.local/info'


class Drv:
    def __init__(self, page): self.p = page
    def evaluate_page(self, js, arg=None):
        return self.p.evaluate(js, arg) if arg is not None else self.p.evaluate(js)
    def query_selector_all(self, s): return self.p.query_selector_all(s)
    def query_selector(self, s): return self.p.query_selector(s)
    @property
    def mouse(self): return self.p.mouse
    @property
    def keyboard(self): return self.p.keyboard


HTML = """<html><body style="margin:0;font-family:sans-serif">
<h3>Detalhes da empresa</h3><div role="button" id="ed" onclick="abrir()">Editar</div>
<div id="host"></div>
<script>
const CAMPOS = ['razao','end','end2','cidade','estado','cep','tel','site','cnpj'];
const PAD = {razao:'Asp Representacao Ltda', end:'Rua A 10', end2:'Sala 2', cidade:'Brasilia', estado:'DF',
             cep:'70000-000', tel:'+5511999990000', site:'https://asp.raiz.com', cnpj:'53.111.224/0001-37'};
const ler = () => Object.assign({}, PAD, JSON.parse(localStorage.getItem('bm') || '{}'));
function abrir(){
  const v = ler();
  document.getElementById('host').innerHTML =
   '<div role="dialog" style="position:fixed;left:250px;top:10px;width:600px;height:660px;background:#fff">' +
   '<h2>Editar detalhes da empresa</h2>' +
   CAMPOS.slice(0,2).map(c => '<input type="text" id="'+c+'" value="'+v[c]+'"><br>').join('') +
   '<div role="combobox" aria-haspopup="listbox" style="width:200px;height:28px">Brasil</div>' +
   CAMPOS.slice(2).map(c => '<input type="text" id="'+c+'" value="'+v[c]+'"><br>').join('') +
   '<div style="position:absolute;bottom:15px;right:15px;display:flex;gap:16px">' +
   '<div role="button" style="width:90px;height:36px" onclick="fechar()">Cancelar</div>' +
   '<div role="button" id="sv" aria-disabled="true" style="width:120px;height:36px;background:rgb(160,200,250)" onclick="salvar(event)">Salvar</div>' +
   '</div></div>';
  document.querySelector('[role=dialog]').addEventListener('input', () => {
    const b = document.getElementById('sv'); b.setAttribute('aria-disabled','false'); b.style.background='rgb(24,119,242)'; });
}
function fechar(){ document.getElementById('host').innerHTML = ''; }
function salvar(ev){
  if (!ev.isTrusted || document.getElementById('sv').getAttribute('aria-disabled') === 'true') return;
  window.saves = (window.saves||0) + 1;
  localStorage.setItem('saves', String(+(localStorage.getItem('saves')||0) + 1));
  const falhas = +(localStorage.getItem('falhar') || 0);
  if (falhas > 0) localStorage.setItem('falhar', String(falhas - 1));          // falha SILENCIOSA
  else { const o = {}; CAMPOS.forEach(c => o[c] = document.getElementById(c).value); localStorage.setItem('bm', JSON.stringify(o)); }
  fechar();
}
</script></body></html>"""

falhas = 0
def chk(nome, cond, extra=''):
    global falhas
    if not cond: falhas += 1
    print(('✅' if cond else '❌'), nome, extra)

with sync_playwright() as pw:
    try:
        br = pw.chromium.launch(headless=True)
    except Exception:
        br = pw.chromium.launch(headless=True, channel='chrome')
    page = br.new_page(viewport={'width': 1150, 'height': 700})
    page.route('https://mock.local/**', lambda r: r.fulfill(status=200, content_type='text/html', body=HTML))
    d = Drv(page)
    E._ir_para = lambda drv, url, **k: page.goto(URL)
    REAL = '+5561982536915'
    tel_salvo = lambda: E._so_digitos(page.evaluate("() => (JSON.parse(localStorage.getItem('bm')||'{}').tel) || ''"))
    def reset(falhar=0, bm=None):
        page.goto(URL)
        page.evaluate("(a) => { localStorage.clear(); localStorage.setItem('falhar', String(a[0])); if (a[1]) localStorage.setItem('bm', a[1]); }",
                      [falhar, bm])

    reset()
    ok = E._definir_telefone_empresa(d, '1', REAL, print)
    chk('BM com número FAKE → grava o REAL, salva e confere', ok and tel_salvo() == '5561982536915', tel_salvo())
    chk('diálogo fechado ao final', not E._dialogo_aberto(d))
    chk('demais campos intactos', page.evaluate("() => JSON.parse(localStorage.getItem('bm')).razao") == 'Asp Representacao Ltda')

    reset(falhar=1)
    ok = E._definir_telefone_empresa(d, '1', REAL, print)
    chk('save falha em SILÊNCIO na 1ª → detecta, regrava e confere',
        ok and tel_salvo() == '5561982536915' and page.evaluate("() => localStorage.getItem('saves')") == '2')

    reset(falhar=5)
    ok = E._definir_telefone_empresa(d, '1', REAL, print)
    chk('save NUNCA persiste → retorna False (não segue com número fake na BM)', ok is False)

    reset(bm='{"tel":"+5561982536915"}')
    ok = E._definir_telefone_empresa(d, '1', REAL, print)
    chk('BM já com o número real → não regrava (0 saves) e confere',
        ok and page.evaluate("() => localStorage.getItem('saves')") is None)
    br.close()

print('\nFALHAS:', falhas)
sys.exit(1 if falhas else 0)
