#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Testa _detectar_tela_central com telas em INGLÊS (e PT/ES) via driver-stub.
Prova que a detecção idioma-agnóstica classifica cada tela da Central."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in ("stdout", "stderr"):
    try: getattr(sys, _f).reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from server import etapa_verificacao_negocio as E


class StubDriver:
    def __init__(self, dialogs, body=""):
        self._dialogs = dialogs
        self._body = body.lower()
    def evaluate_page(self, *a, **k):
        return {"dialogs": [{"txt": d.lower(), "temForm": True} for d in self._dialogs],
                "body": self._body}


# (texto de tela EN, passo esperado)
CASOS = [
    ("Required actions\nShow that your business is real and that you have a legitimate connection to it. To verify, you'll need...", "acoes_necessarias"),
    ("Thanks for submitting\nWe're reviewing the details of your business. Your information is in review.", "em_analise"),
    ("We couldn't find your business\nConfirm your connection with a document and a connection verification.", "conexao_dominio"),
    ("Confirm your phone number\nWe'll send you an SMS with a code.", "sms_enviar"),
    ("Verify with your business domain\nThe domain below is verified. Domain verified.", "dominio_confirmar"),
    ("Choose a verification method\nDomain verification\nText message", "metodo"),
    ("Your document includes the phone number?\nUpload documents\nSelect a document type", "carregar_doc"),
    ("Contact information\nYou need to be able to receive a confirmation code at this number.", "contato"),
    ("Add the organization's address\nOrganization address", "endereco"),
    ("Tax ID\nBusiness registration number", "cnpj"),
    ("Is your business officially registered?", "registro"),
    ("Select your business type\nWhat type of business is this?", "tipo"),
    ("Select a country\nOrganization location", "pais"),
    ("Start verification", "iniciar"),
    ("Enter the confirmation code\nWe sent a code to your phone.", "sms_codigo"),
    ("Enter the code we sent to a@b.com", "email_codigo"),
    ("Confirm your email address\nYour email must be associated with your business", "email_endereco"),
    ("Select your business\nMy business isn't listed\nWe found the following in public records", "selecione_empresa"),
    # ES
    ("Acciones necesarias\nDemostrar que tu empresa es real", "acoes_necessarias"),
    ("Gracias por el envío\nEn revisión", "em_analise"),
]

ok = 0
for txt, esperado in CASOS:
    got = E._detectar_tela_central(StubDriver([txt]))
    marca = "✅" if got == esperado else "❌"
    if got == esperado: ok += 1
    print(f"{marca} esperado={esperado:20s} obtido={got}")
print(f"\n{ok}/{len(CASOS)} telas classificadas corretamente")
