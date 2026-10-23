#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migração IDEMPOTENTE do Monitor de Análise (2026-07-08).
Adiciona SÓ as colunas que faltam em bm_records (MySQL 8, ALGORITHM=INSTANT).
Seguro rodar quantas vezes quiser: checa SHOW COLUMNS e só cria o que não existe.
Uso:  python server/sql/migrar_monitor_analise.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from server.acesso import _connect_db

# coluna -> definição (nullable, sem default → INSTANT em MySQL 8)
NOVAS = [
    ("site_id",      "VARCHAR(64)  NULL"),
    ("site_url",     "VARCHAR(255) NULL"),
    ("cnpj",         "VARCHAR(32)  NULL"),
    ("razao_social", "VARCHAR(255) NULL"),
    ("waba_status",  "VARCHAR(24)  NULL"),
]


def main():
    conn = _connect_db()
    cur = conn.cursor()
    cur.execute("SHOW COLUMNS FROM bm_records")
    existentes = {r[0] for r in cur.fetchall()}
    print("Colunas existentes:", len(existentes))
    add = [(c, d) for (c, d) in NOVAS if c not in existentes]
    if not add:
        print("Nada a fazer - todas as colunas ja existem. OK")
        cur.close(); conn.close(); return
    for c, d in add:
        sql = f"ALTER TABLE bm_records ADD COLUMN {c} {d}, ALGORITHM=INSTANT"
        print("Executando:", sql)
        cur.execute(sql)
    conn.commit()
    # verifica
    cur.execute("SHOW COLUMNS FROM bm_records")
    depois = {r[0] for r in cur.fetchall()}
    faltou = [c for c, _ in NOVAS if c not in depois]
    print("Adicionadas:", [c for c, _ in add])
    print("Verificacao - faltando:", faltou or "nenhuma (OK)")
    cur.close(); conn.close()


if __name__ == "__main__":
    main()
