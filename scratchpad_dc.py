import sys, json
sys.path.insert(0, r"C:\Users\Administrador\Desktop\GS Creator")
from server import parser_perfis
perfis = parser_perfis.parsear_arquivo_txt(r"C:\Users\Administrador\Desktop\GS Creator\conta_fb_3185.txt")
p = perfis[0] if perfis else {}
print("chaves:", list(p.keys()))
for k,v in p.items():
    if v: print(f"{k}: {str(v)[:70]}")