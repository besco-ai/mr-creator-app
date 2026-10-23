# -*- coding: utf-8 -*-
"""Teste em DOM REAL (Chromium) do pop-up de CONTATO da Central: digitação real,
espera do pop-up assentar, clique real conferido e reclique no 'telefone inválido'.

O mock imita a Meta: cada alteração de campo abre uma janela de VALIDAÇÃO (900ms);
clicar Avançar dentro dela → erro 'Insira um número de telefone válido' (o bug)."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from playwright.sync_api import sync_playwright
from server import etapa_verificacao_negocio as E

E._delay_medio = lambda *a, **k: time.sleep(0.2)
E._delay_curto = lambda *a, **k: time.sleep(0.05)


class Drv:
    def __init__(self, page): self.p = page
    def evaluate_page(self, js, arg=None):
        return self.p.evaluate(js, arg) if arg is not None else self.p.evaluate(js)
    def query_selector_all(self, s): return self.p.query_selector_all(s)
    @property
    def mouse(self): return self.p.mouse
    @property
    def keyboard(self): return self.p.keyboard


def html(tel='', site='https://raiz.com', teimoso=0):
    return f"""<html><body style="margin:0;font-family:sans-serif">
<div role="dialog" id="dlg" style="position:fixed;left:300px;top:20px;width:550px;height:520px;background:#fff">
 <h2>Adicionar dados da empresa</h2><div id="erro" style="color:red"></div>
 <p>Informações de contato</p>
 <div role="combobox" style="display:inline-block;width:90px;height:40px">BR+55</div>
 <label>Telefone <input id="tel" type="text" value="{tel}"></label>
 <p>Você precisa poder receber um código de confirmação nesse número.</p>
 <label>Site <input id="site" type="text" value="{site}"></label>
 <div style="position:absolute;bottom:20px;right:20px;display:flex;gap:20px">
  <div role="button" style="width:80px;height:36px">Voltar</div>
  <div role="button" id="prim" style="position:relative;width:140px;height:36px;background:rgb(24,119,242);color:#fff">Avançar
    <div data-visualcompletion="ignore" style="position:absolute;inset:0"></div></div>
 </div></div>
<script>
let validandoAte = 0, cliques = 0, teimoso = {teimoso};
document.addEventListener('input', () => {{ validandoAte = Date.now() + 900; }});
document.getElementById('prim').addEventListener('click', (ev) => {{
  if (!ev.isTrusted) return;                       // só clique REAL conta
  cliques++; window.cliques = cliques;
  const tel = document.getElementById('tel').value.replace(/\\D/g,'');
  if (Date.now() < validandoAte || tel.length < 10 || teimoso-- > 0) {{
    document.getElementById('erro').innerText = 'Insira um número de telefone válido.'; return; }}
  window.enviado = {{tel: tel, site: document.getElementById('site').value}};
  document.getElementById('dlg').outerHTML =
    '<div role="dialog" style="position:fixed;left:300px;top:20px;width:550px;height:300px;background:#fff">' +
    '<h2>Ajude-nos a confirmar que é você</h2><input type="checkbox"> Não sou um robô</div>';
}});
</script></body></html>"""


falhas = 0
def chk(nome, cond, extra=''):
    global falhas
    if not cond: falhas += 1
    print(('✅' if cond else '❌'), nome, extra)


def passo_contato(d, tel, site):
    """Réplica fiel do trecho final do passo 'contato' do loop da Central."""
    E._definir_telefone_contato(d, tel, print)
    E._definir_site_contato(d, site, print)
    txt = ['Avançar', 'Continuar', 'Next', 'Continue', 'Siguiente']
    for t in range(3):
        if t == 0:
            d.keyboard.press('Tab')
        E._aguardar_dialogo_pronto(d, timeout=6)
        if not E._clicar_avancar_real(d, txt):
            E._clicar_botao_robusto(d, txt, timeout=8)
        if E._aguardar_transicao_central(d, 'contato', timeout=4):
            return True
        if E._erro_telefone_invalido(d) and E._telefone_confere(d, tel):
            print(f'   ↻ reclique {t + 1}/3')
            continue
        break
    return False


with sync_playwright() as pw:
    try:
        br = pw.chromium.launch(headless=True)
    except Exception:
        br = pw.chromium.launch(headless=True, channel='chrome')
    page = br.new_page(viewport={'width': 1150, 'height': 700})
    d = Drv(page)
    _sc = page.set_content
    def _novo(h):
        page.goto('about:blank'); _sc(h)
    page.set_content = _novo
    TEL, SITE = '61982536915', 'https://empresa.raiz.com'

    page.set_content(html())
    chk('detecta contato', E._detectar_tela_central(d) == 'contato')
    ok = passo_contato(d, TEL, SITE)
    env = page.evaluate('() => window.enviado || null')
    chk('campos vazios/raiz → digita, espera validar, 1 clique real e avança',
        ok and env and env['tel'] == TEL and env['site'] == SITE and page.evaluate('() => window.cliques') == 1,
        str(env))
    chk('próxima tela = captcha', E._detectar_tela_central(d) == 'captcha')

    page.set_content(html(tel=TEL, site=SITE))
    ok = passo_contato(d, TEL, SITE)
    chk('campos já corretos → não regrava nada e avança no 1º clique',
        ok and page.evaluate('() => window.cliques') == 1)

    page.set_content(html(tel='11900000000', site=SITE))
    ok = passo_contato(d, TEL, SITE)
    env = page.evaluate('() => window.enviado || null')
    chk('número antigo no campo → troca pelo atual', ok and env and env['tel'] == TEL, str(env))

    page.set_content(html(tel=TEL, site=SITE, teimoso=2))
    ok = passo_contato(d, TEL, SITE)
    chk("Meta acusa 'telefone inválido' 2x com número certo → reclica e passa (sem trocar nº)",
        ok and page.evaluate('() => window.cliques') == 3)

    # 🔒 trava estrita do número REAL comprado
    page.set_content(html(tel='11999990000', site=SITE))          # número FAKE no campo
    chk('trava: número fake no campo → NÃO confere', E._telefone_contato_exato(d, TEL) is False)
    E._definir_telefone_contato(d, TEL, None)
    chk('trava: após corrigir → confere exatamente o comprado', E._telefone_contato_exato(d, TEL) is True)
    page.set_content(html(tel='5', site=SITE))
    chk('trava: campo parcial ("5") NÃO passa (o confere tolerante passava)',
        E._telefone_contato_exato(d, TEL) is False)
    chk('trava: sem número comprado → nunca confere', E._telefone_contato_exato(d, '') is False)

    # EN: mesma tela, descrição com "upload documents" (casava 'carregar_doc')
    en = (html(tel='', site='https://raiz.com')
          .replace('Adicionar dados da empresa', 'Add business details')
          .replace('Informações de contato', "If there's no match, you can upload documents to verify this information.")
          .replace('Você precisa poder receber um código de confirmação nesse número.', 'Rufnummer')
          .replace('Telefone', 'Phone').replace('Site', 'Website'))
    page.set_content(en)
    chk('[EN] texto puro erra (carregar_doc) e a estrutura corrige p/ contato',
        E._detectar_tela_central(d) == 'contato', f'(texto={E._detectar_tela_central_texto(d)!r})')
    chk('[EN] passo cnpj NUNCA digita CNPJ na tela de contato',
        E._preencher_cnpj_central(d, '53.111.224/0001-37', 'Asp', ['tax id'], None) is False
        and page.evaluate("() => document.getElementById('tel').value") == '')

    # _avancar genérico: clique real, mesmo com overlay por cima do botão
    page.set_content(html(tel=TEL, site=SITE))
    chk('_avancar() = clique REAL (isTrusted) e avança',
        E._avancar(d, timeout=4) and E._aguardar_transicao_central(d, 'contato', timeout=3)
        and page.evaluate('() => window.cliques') == 1)
    br.close()

print('\nFALHAS:', falhas)
sys.exit(1 if falhas else 0)
