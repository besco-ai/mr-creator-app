# -*- coding: utf-8 -*-
"""Teste em DOM REAL (Chromium) da tela do CNPJ da Central em EN / DE / PT + telas vizinhas."""
import sys, os
sys.path.insert(0, r"C:\Users\Administrador\Desktop\GS Creator")
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from playwright.sync_api import sync_playwright
from server import etapa_verificacao_negocio as E

E._delay_medio = lambda *a, **k: None
E._delay_curto = lambda *a, **k: None


class Drv:
    def __init__(self, page): self.p = page
    def evaluate_page(self, js, arg=None):
        return self.p.evaluate(js, arg) if arg is not None else self.p.evaluate(js)
    def query_selector_all(self, s): return self.p.query_selector_all(s)
    @property
    def mouse(self): return self.p.mouse
    @property
    def keyboard(self): return self.p.keyboard


BASE = """<html><body style="margin:0;font-family:sans-serif">
<div>Start verification — landing atrás do modal</div>
<input id="fundo" placeholder="busca da pagina (fora do dialogo)">
%s
<script>
function sync(){ const t=document.getElementById('tax'), n=document.getElementById('nome'), b=document.getElementById('prim');
  if(!t||!b) return; const ok=t.value.replace(/\\D/g,'').length===14 && n.value.trim().length>0;
  b.setAttribute('aria-disabled', ok?'false':'true'); b.style.background = ok?'rgb(24,119,242)':'rgb(160,200,250)'; }
document.addEventListener('input', sync); sync();
function prox(){ const b=document.getElementById('prim'); if(b.getAttribute('aria-disabled')==='true') return;
  document.getElementById('dlg').outerHTML='<div id="feito">AVANCOU</div>'; }
</script></body></html>"""

def dlg_cnpj(titulo, desc, rot_tax, rot_nome, rot_alt, voltar, avancar, nome='Asp Representacao Ltda'):
    return BASE % f"""
<div role="dialog" id="dlg" style="position:fixed;left:300px;top:20px;width:550px;height:640px;background:#fff">
 <div role="button" aria-label="x" style="width:30px;height:30px">←</div><h2>{titulo}</h2>
 <p>{desc}</p>
 <label><span>{rot_tax}</span><input id="tax" type="text" value=""></label><br>
 <label><span>{rot_nome}</span><input id="nome" type="text" value="{nome}"></label><br>
 <label><input id="alt" type="text" placeholder="{rot_alt}" value=""></label><br>
 <div style="position:absolute;bottom:20px;right:20px;display:flex;gap:20px">
  <div role="button" style="color:rgb(24,119,242);width:80px;height:36px">{voltar}</div>
  <div role="button" id="prim" onclick="prox()" style="width:140px;height:36px;color:#fff">{avancar}</div>
 </div></div>"""

EN = dlg_cnpj("Add business details",
    "We'll use these details to look up an official record of your business to confirm that it's real. If there's no match, you can upload documents to verify this information.",
    "Business Tax ID/Registration Number", "Business name", "Alternative business name (optional)", "Back", "Next")
DE = dlg_cnpj("Unternehmensdetails hinzufügen",
    "Wir verwenden diese Angaben, um einen offiziellen Eintrag zu suchen. Andernfalls kannst du Dokumente hochladen.",
    "Steuernummer/Handelsregisternummer", "Name des Unternehmens", "Alternativer Name (optional)", "Zurück", "Weiter")
VI = dlg_cnpj("Thêm thông tin doanh nghiệp", "Chúng tôi sẽ dùng thông tin này.",
    "Mã số thuế", "Tên doanh nghiệp", "Tên khác (không bắt buộc)", "Quay lại", "Tiếp")
DE_NOME_VAZIO = dlg_cnpj("Unternehmensdetails hinzufügen", "x", "Steuernummer", "Name", "Alt", "Zurück", "Weiter", nome='')
PT = dlg_cnpj("Adicionar dados da empresa", "Usaremos estes dados para procurar um registro oficial.",
    "Identificação Fiscal da Empresa/Número de Registro da Empresa", "Nome da empresa", "Nome comercial alternativo (opcional)", "Voltar", "Avançar")

REG_EN = BASE % """
<div role="dialog" id="dlg" style="position:fixed;left:300px;top:20px;width:550px;height:400px;background:#fff">
 <h2>Business registration</h2><p>Does your business have a tax ID or registration number?</p>
 <div><div role="radio" aria-checked="false" onclick="this.setAttribute('aria-checked','true')" style="width:20px;height:20px"></div><span>It does</span></div>
 <div><div role="radio" aria-checked="false" onclick="this.setAttribute('aria-checked','true')" style="width:20px;height:20px"></div><span>It does not</span></div>
 <div role="button" id="prim" style="width:140px;height:36px;background:rgb(24,119,242)">Next</div></div>"""
DOC_PT = BASE % """
<div role="dialog" id="dlg" style="position:fixed;left:300px;top:20px;width:550px;height:400px;background:#fff">
 <h2>Carregar documentos</h2><p>Selecione um tipo de documento</p>
 <div role="combobox" style="width:200px;height:30px">Selecione um tipo de documento</div><input type="file" style="display:none">
 <div role="button" id="prim" style="width:140px;height:36px;background:rgb(24,119,242)">Avançar</div></div>"""
CONTATO_EN = BASE % """
<div role="dialog" id="dlg" style="position:fixed;left:300px;top:20px;width:550px;height:400px;background:#fff">
 <h2>Contact information</h2><p>You need to be able to receive a confirmation code at this number.</p>
 <input type="text" value="11987654321"><input type="text" value="https://asp.exemplo.com">
 <div role="button" id="prim" style="width:140px;height:36px;background:rgb(24,119,242)">Next</div></div>"""
SAIR = BASE % """
<div role="dialog" id="dlg" style="position:fixed;left:300px;top:200px;width:550px;height:190px;background:#fff">
 <h2>Deseja sair?</h2><p>Se você sair agora, perderá seu progresso.</p>
 <div role="button" style="width:90px;height:36px">Cancelar</div>
 <div role="button" id="prim" style="width:140px;height:36px;background:rgb(24,119,242)">Sim, sair</div></div>"""

CNPJ = '53.111.224/0001-37'
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
    d = Drv(page)
    d._pm_cnpj = '53111224000137'
    d._pm_razao = 'ASP REPRESENTACAO LTDA'

    for nome, html in (('EN', EN), ('DE', DE), ('VI', VI), ('PT', PT), ('DE nome vazio', DE_NOME_VAZIO)):
        page.set_content(html)
        passo_txt = E._detectar_tela_central_texto(d)
        passo = E._detectar_tela_central(d)
        if nome == 'DE nome vazio':
            # sem razão no campo a estrutura não decide; o handler é testado direto
            print(f'   [{nome}] texto={passo_txt!r} final={passo!r} (esperado None: sem dado p/ decidir)')
        else:
            chk(f'[{nome}] detecta cnpj', passo == 'cnpj', f'(texto puro={passo_txt!r})')
        ok = E._preencher_cnpj_central(d, CNPJ, 'Asp Representacao Ltda', ['tax id'], print)
        v = page.evaluate("() => [tax.value, nome.value, alt.value, fundo.value]")
        chk(f'[{nome}] CNPJ no campo certo', ok and E._so_digitos(v[0]) == '53111224000137' and v[2] == '' and v[3] == '', str(v))
        chk(f'[{nome}] nome preenchido', bool(v[1].strip()), v[1])
        chk(f'[{nome}] primário habilitado', E._primario_dialogo(d) == 'habilitado')
        r = E._primario_dialogo(d, clicar=True)
        page.wait_for_timeout(200)
        chk(f'[{nome}] clique estrutural avançou', r == 'clicado' and page.query_selector('#feito') is not None)

    page.set_content(DE)
    chk('[DE] primário DESABILITADO c/ campo vazio (não clica)', E._primario_dialogo(d, clicar=True) == 'desabilitado'
        and page.query_selector('#feito') is None)
    page.set_content(DE); page.fill('#tax', CNPJ)
    chk('[DE] _avancar() cai no primário estrutural', E._avancar(d, timeout=2) and page.wait_for_timeout(200) is None
        and page.query_selector('#feito') is not None)

    page.set_content(REG_EN)
    chk('[EN registro c/ "tax id"] texto diz cnpj', E._detectar_tela_central_texto(d) == 'cnpj')
    chk('[EN registro c/ "tax id"] final = registro', E._detectar_tela_central(d) == 'registro')
    chk('[EN registro] 1º radio marcado', E._marcar_primeiro_radio_dialogo(d)
        and page.evaluate("() => document.querySelectorAll('[role=radio]')[0].getAttribute('aria-checked')") == 'true')
    page.set_content(DOC_PT)
    chk('[PT upload] continua carregar_doc', E._detectar_tela_central(d) == 'carregar_doc')
    page.set_content(CONTATO_EN)
    chk('[EN contato] continua contato', E._detectar_tela_central(d) == 'contato')
    page.set_content(SAIR)
    chk('[Deseja sair?] primário NÃO é tocado', E._primario_dialogo(d, clicar=True) is None)
    br.close()

print('\nFALHAS:', falhas)
sys.exit(1 if falhas else 0)
