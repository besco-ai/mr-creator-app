# -*- coding: utf-8 -*-
"""Extrai o _JS_NUMERO_VIRTUAL do modulo Python e grava como .js para o teste.
Assim o teste roda EXATAMENTE o codigo que vai para producao, nao uma copia."""
import io, os, re, sys

alvo = sys.argv[1]
saida = sys.argv[2]
src = io.open(alvo, encoding='utf-8').read()
m = re.search(r'_JS_NUMERO_VIRTUAL\s*=\s*r"""(.*?)"""', src, re.S)
if not m:
    print('NAO ACHEI _JS_NUMERO_VIRTUAL em', alvo)
    sys.exit(1)
js = m.group(1)
io.open(saida, 'w', encoding='utf-8').write(js)
print('ok  %s -> %s  (%d chars)' % (os.path.basename(alvo), os.path.basename(saida), len(js)))
