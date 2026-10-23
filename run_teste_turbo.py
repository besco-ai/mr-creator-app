#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Runner de TESTE REAL (1 conta, sem GUI) — usa o MESMO caminho da interface:
autenticar_usuario → importar_perfis (TXT ORIGINAL do painel, assinatura GS-SIG) →
iniciar_processamento com as configs SALVAS do usuário → polling de obter_progresso.

Uso:  python run_teste_turbo.py <caminho_do_txt> [verificar_bm] [minutos_max]
Log completo: logs/teste_<nome_do_txt>.log
"""
import sys, os, time, json, logging
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

txt = sys.argv[1]
metodo = sys.argv[2] if len(sys.argv) > 2 else ''
max_min = float(sys.argv[3]) if len(sys.argv) > 3 else 45

os.makedirs(os.path.join(BASE, 'logs'), exist_ok=True)
log_file = os.path.join(BASE, 'logs', 'teste_%s.log' % os.path.splitext(os.path.basename(txt))[0])
root = logging.getLogger(); root.setLevel(logging.INFO)
fh = logging.FileHandler(log_file, encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
root.addHandler(fh)

from server import backend as B

usuario = B._ler_config('usuario', '') or B._ler_config('ultimo_usuario_software', '')
senha = B._ler_config('senha', '', '')
print('usuario:', usuario, flush=True)
r = B.autenticar_usuario(usuario, senha, 'sim')
print('login:', json.dumps(r, ensure_ascii=False, default=str)[:200], flush=True)

with open(txt, 'r', encoding='utf-8', errors='replace', newline='') as f:
    conteudo = f.read()
imp = B.importar_perfis(conteudo)
print('importar:', json.dumps({k: v for k, v in (imp or {}).items() if k != 'perfis'},
                              ensure_ascii=False, default=str)[:300], flush=True)
if not B._estado.get('perfis'):
    print('SEM PERFIS — abortando'); sys.exit(2)
B._estado['perfis'] = B._estado['perfis'][:1]

c = B.carregar_configuracoes(usuario)
vb = metodo or c['verificar_bm']
print('config: engine=%s grupo=%s proxy=%s 4g=%s tipo=%s verificar_bm=%s sms=%s' % (
    c['browser_engine'], c['nome_grupo'], c['proxy'], c['utilizar_4g'], c['tipo_empresa'], vb,
    c['sms_provedor']), flush=True)

res = B.iniciar_processamento(
    c['nome_grupo'], c['proxy'], c['utilizar_4g'], c['lista_proxy'], c['proxy_tipo'],
    usuario=usuario, senha=senha, qtd_bm=1,
    browser_engine=c['browser_engine'], adspower_token=c['adspower_token'],
    captcha_token=c['captcha_token'], verificar_bm=vb, tipo_empresa=c['tipo_empresa'],
    auto_verificar=c['auto_verificar'], simultaneos=1, oculto='nao',
    datacrazy_email=c['datacrazy_email'], datacrazy_senha=c['datacrazy_senha'],
    sms24h_token=c['sms24h_token'], sms_provedor=c['sms_provedor'])
print('iniciar:', json.dumps(res, ensure_ascii=False, default=str)[:300], flush=True)

fim = time.time() + max_min * 60
ult = None
while time.time() < fim:
    p = B.obter_progresso()
    itens = p.get('progresso') or []
    snap = json.dumps([(i.get('status'), i.get('mensagem')) for i in itens], ensure_ascii=False, default=str)
    if snap != ult:
        ult = snap
        print(time.strftime('%H:%M:%S'), snap[:400], flush=True)
    if not p.get('processando') and itens:
        break
    time.sleep(3)
else:
    print('TIMEOUT do runner — parando', flush=True)
    try: B.parar_processamento()
    except Exception as e: print('parar:', e)
p = B.obter_progresso()
print('FINAL:', json.dumps({k: p.get(k) for k in ('processando', 'total', 'concluidos', 'erros')},
                           ensure_ascii=False), flush=True)
print('ITENS:', json.dumps(p.get('progresso'), ensure_ascii=False, default=str)[:1500], flush=True)
