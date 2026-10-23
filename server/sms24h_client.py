#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cliente SMS24H — Números Virtuais / SMS (v1.0)
==============================================
Compra um número virtual e lê o código SMS para a verificação de NEGÓCIO da BM
(Plano 6 · Completo/Pro Max). O número é usado como "Telefone comercial" da
empresa no Facebook e recebe o SMS de confirmação da Central de Segurança.

Protocolo: compatível com SMS-Activate (mesmo da página PHP do painel).
Endpoint base: https://api.sms24h.org/stubs/handler_api

O usuário informa o TOKEN (api_key) do sms24h na GUI (campo "Token SMS (sms24h)").

Fluxo típico de uso:
    cli = SMS24HClient(api_key)
    compra = cli.comprar_numero(service='fb', country='73')   # 73 = Brasil
    # -> {'sucesso': True, 'id': '124248528', 'numero': '5573924576507', ...}
    codigo = cli.aguardar_codigo(compra['id'], timeout=90)
    # -> {'sucesso': True, 'codigo': '992203'}
    # se não chegar: cli.solicitar_reenvio(id) e aguardar de novo (até 3x)
    cli.finalizar(compra['id'])                                # encerra a ativação
"""

import logging
import re
import time

import requests

logger = logging.getLogger(__name__)

# Endpoint padrão (handler compatível SMS-Activate). Pode ser sobrescrito.
DEFAULT_API_URL = 'https://api.sms24h.org/stubs/handler_api'

# --------------------------------------------------------------------------- #
# PROVEDORES DE SMS
# --------------------------------------------------------------------------- #
# Os três falam o MESMO protocolo (SMS-Activate), então muda só a URL e a moeda.
# Preços do Facebook/Brasil medidos em 2026-08-02:
#     Tiger    US$ 0,020  (24 mil números)   ← mais barato
#     Grizzly  US$ 0,063  (18,5 mi números)
#     SMS24h   R$  0,80
# O usuário escolhe na GUI qual usar; o token é o daquele provedor.
PROVEDORES = {
    'sms24h': {
        'nome': 'SMS24h',
        'url': 'https://api.sms24h.org/stubs/handler_api',
        'moeda': 'R$',
        'painel': 'https://sms24h.org/api',
    },
    'grizzly': {
        'nome': 'Grizzly SMS',
        'url': 'https://api.grizzlysms.com/stubs/handler_api.php',
        'moeda': 'US$',
        'painel': 'https://grizzlysms.com/docs',
    },
    'tiger': {
        'nome': 'Tiger SMS',
        'url': 'https://api.tiger-sms.com/stubs/handler_api.php',
        'moeda': 'US$',
        'painel': 'https://tiger-sms.com/pt/api',
    },
    # SMSBower — protocolo SMS-Activate (handler_api). Preços BR medidos 2026-08-12:
    #   fb US$0,218 (1,27 mi números) · ot US$0,668 (1 mi). Números BR reais; a
    #   aposta é o serviço que entregue o código da BM (testar fb x ot em produção).
    'smsbower': {
        'nome': 'SMSBower',
        'url': 'https://smsbower.online/stubs/handler_api.php',
        'moeda': 'US$',
        'painel': 'https://smsbower.app/cabinet/profile',
    },
    # ⚠️ vak-sms NÃO fala o protocolo SMS-Activate — tem API REST própria
    # (getNumber/getSmsCode/setStatus, JSON). Por isso `criar_cliente` devolve o
    # VakSmsClient para ele, com a MESMA interface do SMS24HClient.
    # Medido em 2026-08-03: fb/Brasil US$ 0,04 · 30.191 números.
    'vak': {
        'nome': 'Vak-SMS',
        'url': 'https://vak-sms.com/api/',
        'moeda': 'US$',
        'painel': 'https://vak-sms.com/api',
        'dialeto': 'vak',
    },
}
PROVEDOR_PADRAO = 'sms24h'          # mantém o comportamento de quem já usava

# ── Tokens por provedor (fallback A → B → C) ───────────────────────────────
# Guardados no módulo, definidos UMA vez no início do run pelo backend. É de
# propósito: passar isto por parâmetro exigiria mexer na assinatura de 7 funções
# da cadeia (verificacao_bm → etapa_verificacao_negocio) e em todos os call sites
# — foi exatamente esse tipo de mudança que derrubou 100% de uma rodada com
# "unexpected keyword argument 'sms_provedor'" (2026-08-02).
_TOKENS = {}


def configurar_tokens(tokens):
    """Registra {provedor: token} para o run atual (só os não-vazios)."""
    global _TOKENS
    _TOKENS = {str(k).strip().lower(): str(v).strip()
               for k, v in dict(tokens or {}).items()
               if str(v or '').strip() and str(k).strip().lower() in PROVEDORES}
    return dict(_TOKENS)


def tokens_configurados():
    return dict(_TOKENS)


# ── Preço máximo por número (teto de compra) ───────────────────────────────
# Os provedores vendem o MESMO serviço/país em VÁRIAS faixas de preço (a vitrine
# do Tiger mostra fb/BR de US$0,02 a US$0,106; Grizzly de 0,04 a 0,07; vak-sms de
# 0,04 a 3,00). A API não lista as faixas — o controle é o `maxPrice` no getNumber
# (é o que o slider "máx. $X" do site faz). Teto MAIOR = pool maior, incluindo os
# números caros, que costumam ser os que realmente entregam.
# 0/None = comportamento antigo (o provedor decide, normalmente o mais barato).
_PRECO_MAX = 0.0


def configurar_preco_max(valor):
    global _PRECO_MAX
    try:
        _PRECO_MAX = max(0.0, float(str(valor).replace(',', '.') or 0))
    except Exception:
        _PRECO_MAX = 0.0
    return _PRECO_MAX


def preco_max_configurado():
    return _PRECO_MAX


def url_do_provedor(provedor):
    """URL do handler_api do provedor (cai no sms24h se vier vazio/desconhecido)."""
    return PROVEDORES.get(str(provedor or '').strip().lower(),
                          PROVEDORES[PROVEDOR_PADRAO])['url']


def nome_do_provedor(provedor):
    return PROVEDORES.get(str(provedor or '').strip().lower(),
                          PROVEDORES[PROVEDOR_PADRAO])['nome']


def moeda_do_provedor(provedor):
    return PROVEDORES.get(str(provedor or '').strip().lower(),
                          PROVEDORES[PROVEDOR_PADRAO])['moeda']


def criar_cliente(token, provedor=PROVEDOR_PADRAO):
    """Fábrica: devolve um cliente já apontado para o provedor escolhido.

    É por aqui que o resto do sistema deve criar o cliente — adicionar um provedor
    do MESMO protocolo é só acrescentar uma entrada em PROVEDORES. Provedores com
    dialeto próprio (ex.: vak-sms) ganham uma classe com a MESMA interface, e o
    resto do sistema não precisa saber a diferença."""
    p = str(provedor or '').strip().lower()
    if (PROVEDORES.get(p, {}).get('dialeto') or '') == 'vak':
        return VakSmsClient(token, provedor=p)
    return SMS24HClient(token, api_url=url_do_provedor(provedor),
                        provedor=provedor)


# Serviço Facebook e país Brasil no protocolo SMS-Activate.
SERVICE_FACEBOOK = 'fb'
COUNTRY_BRASIL = '73'
# 'ot' = "qualquer outro serviço". O provedor FILTRA por remetente: um número
# comprado como 'fb' só recebe SMS de remetentes reconhecidos como Facebook. O
# código da verificação de NEGÓCIO da Meta vem por outra rota e é descartado —
# por isso o SMS chega na criação da conta e não chega na BM. O 'ot' é o balde
# dos remetentes não reconhecidos. (medido 2026-08-04: Tiger/BR US$0,122 · 15.430)
SERVICE_QUALQUER = 'ot'

HTTP_TIMEOUT = 30


class SMS24HClient:
    """Cliente fino para o handler_api (protocolo SMS-Activate).

    Serve para QUALQUER provedor compatível — sms24h, Grizzly SMS e Tiger SMS.
    O nome da classe ficou por compatibilidade com o código existente; prefira
    `criar_cliente(token, provedor)` para instanciar."""

    def __init__(self, api_key, api_url=DEFAULT_API_URL, provedor=PROVEDOR_PADRAO):
        self.api_key = (api_key or '').strip()
        self.api_url = (api_url or DEFAULT_API_URL).strip()
        self.provedor = str(provedor or PROVEDOR_PADRAO).strip().lower()
        self.nome_provedor = nome_do_provedor(self.provedor)
        self.moeda = moeda_do_provedor(self.provedor)
        self._sessao = requests.Session()

    # ------------------------------------------------------------------ #
    # Requisição base
    # ------------------------------------------------------------------ #
    def _req(self, action, extra=None, timeout=HTTP_TIMEOUT):
        """Faz GET no handler_api e retorna a STRING bruta da resposta.

        O protocolo SMS-Activate responde em texto simples:
        'ACCESS_NUMBER:ID:NUMERO', 'STATUS_OK:CODIGO', 'NO_NUMBERS', etc.
        """
        params = {'api_key': self.api_key, 'action': action}
        if extra:
            params.update(extra)
        try:
            resp = self._sessao.get(self.api_url, params=params, timeout=timeout)
            texto = (resp.text or '').strip()
            logger.debug("[%s] %s -> %s", self.nome_provedor, action, texto[:120])
            return texto
        except Exception as exc:
            logger.error("[%s] Erro na chamada %s: %s", self.nome_provedor, action, exc)
            return ''

    # ------------------------------------------------------------------ #
    # Saldo
    # ------------------------------------------------------------------ #
    def saldo(self):
        """Retorna o saldo da conta (float) ou None se falhar."""
        r = self._req('getBalance')
        # Formato: ACCESS_BALANCE:12.34
        if r.startswith('ACCESS_BALANCE:'):
            try:
                return float(r.split(':', 1)[1].replace(',', '.'))
            except Exception:
                return None
        return None

    def token_valido(self):
        """True/False/None — None = indeterminado (rede fora, API instável).

        Serve para NÃO confundir 'chave errada' com 'internet caiu': só o False
        autoriza descartar o token; no None mantemos o provedor na fila."""
        r = (self._req('getBalance') or '').upper()
        if r.startswith('ACCESS_BALANCE'):
            return True
        if 'BAD_KEY' in r or 'NO_KEY' in r or 'WRONG_KEY' in r:
            return False
        return None

    # ------------------------------------------------------------------ #
    # Comprar número
    # ------------------------------------------------------------------ #
    def comprar_numero(self, service=SERVICE_FACEBOOK, country=COUNTRY_BRASIL,
                       operator='any', max_price=None):
        """Solicita um número virtual.

        Returns dict:
            {'sucesso': bool, 'id': str, 'numero': str, 'mensagem': str}
        `numero` vem COM o código do país (ex.: '5573924576507').
        """
        if not self.api_key:
            return {'sucesso': False, 'id': '', 'numero': '',
                    'mensagem': f'Token do {self.nome_provedor} não configurado.'}

        extra = {'service': service, 'country': str(country)}
        if operator and operator != 'any':
            extra['operator'] = operator
        if max_price:
            extra['maxPrice'] = str(max_price)

        r = self._req('getNumber', extra)

        if r.startswith('ACCESS_NUMBER:'):
            partes = r.split(':')
            # ACCESS_NUMBER:ID:NUMERO
            if len(partes) >= 3:
                _id = partes[1].strip()
                numero = partes[2].strip()
                logger.info("[SMS24H] Número comprado: id=%s numero=%s", _id, numero)
                return {'sucesso': True, 'id': _id, 'numero': numero,
                        'mensagem': 'Número comprado.'}

        # Erros conhecidos do protocolo.
        _p = self.nome_provedor
        mapa = {
            'NO_NUMBERS': f'Sem números disponíveis no {_p} para o serviço/país agora.',
            'NO_BALANCE': f'Saldo insuficiente no {_p}.',
            'BAD_KEY': f'Token (api_key) do {_p} inválido.',
            'BAD_ACTION': f'Ação inválida no {_p}.',
            'BAD_SERVICE': f'Serviço inválido no {_p}.',
            'ERROR_SQL': f'Erro interno (SQL) no provedor {_p}.',
            'SERVICE_UNAVAILABLE_REGION': f'{_p}: serviço indisponível nesta região.',
            'BANNED': f'Conta do {_p} banida.',
        }
        msg = mapa.get(r, f'Falha ao comprar número: {r or "sem resposta"}')
        logger.warning("[SMS24H] comprar_numero falhou: %s", msg)
        # 'codigo' = código cru do protocolo (ex.: NO_BALANCE/NO_NUMBERS) p/ o chamador
        # decidir PAUSAR e aguardar (sem saldo/sem número) em vez de descartar o perfil.
        return {'sucesso': False, 'id': '', 'numero': '', 'mensagem': msg,
                'codigo': (str(r).strip().upper() if r else '')}

    # ------------------------------------------------------------------ #
    # Status / código
    # ------------------------------------------------------------------ #
    def consultar_status(self, activation_id):
        """Consulta o status bruto da ativação (getStatus)."""
        return self._req('getStatus', {'id': str(activation_id)})

    def aguardar_codigo(self, activation_id, timeout=90, intervalo=5):
        """Faz polling do SMS até `timeout` segundos.

        Returns dict {'sucesso': bool, 'codigo': str, 'mensagem': str}
        Respostas: STATUS_WAIT_CODE (aguardando), STATUS_WAIT_RETRY:cod
        (já houve 1 código, esperando reenvio), STATUS_OK:cod (chegou),
        STATUS_CANCEL (cancelada).
        """
        inicio = time.time()
        while time.time() - inicio < timeout:
            r = self.consultar_status(activation_id)
            if r.startswith('STATUS_OK:'):
                codigo = r.split(':', 1)[1].strip()
                logger.info("[%s] Código recebido (id=%s): %s",
                            self.nome_provedor, activation_id, codigo)
                return {'sucesso': True, 'codigo': codigo,
                        'mensagem': 'Código recebido.'}
            # 🔥 STATUS_WAIT_RETRY:<codigo> — O CÓDIGO ESTÁ AQUI DENTRO.
            # É o que o provedor devolve quando um SMS JÁ CHEGOU e nós pedimos
            # reenvio: o número depois dos dois-pontos é o ÚLTIMO código recebido.
            # Antes isto era tratado como "ainda esperando" e o código era jogado
            # fora — o bot dizia "SMS não chegou", comprava outro número e o antigo
            # ficava PAGO (com código entregue não há estorno). Foi exatamente o caso
            # do 95641 no painel do Grizzly. (2026-08-02)
            if r.startswith('STATUS_WAIT_RETRY:'):
                codigo = r.split(':', 1)[1].strip()
                if codigo and codigo.isdigit():
                    logger.info("[%s] Código recuperado de STATUS_WAIT_RETRY (id=%s): %s",
                                self.nome_provedor, activation_id, codigo)
                    return {'sucesso': True, 'codigo': codigo,
                            'mensagem': 'Código recebido (após pedido de reenvio).'}
            if r == 'STATUS_CANCEL':
                return {'sucesso': False, 'codigo': '',
                        'mensagem': 'Ativação cancelada pelo provedor.'}
            # STATUS_WAIT_CODE / STATUS_WAIT_RESEND -> segue aguardando
            time.sleep(intervalo)
        return {'sucesso': False, 'codigo': '',
                'mensagem': f'SMS não chegou em {timeout}s.'}

    # ------------------------------------------------------------------ #
    # setStatus: reenviar / finalizar / cancelar
    # ------------------------------------------------------------------ #
    def _set_status(self, activation_id, status):
        return self._req('setStatus', {'id': str(activation_id),
                                        'status': str(status)})

    def solicitar_reenvio(self, activation_id):
        """Pede um NOVO código (status=3). Use entre tentativas de SMS.

        Retorna True se o provedor aceitou (ACCESS_RETRY_GET).
        """
        r = self._set_status(activation_id, 3)
        ok = r.startswith('ACCESS_RETRY_GET') or r == 'ACCESS_RETRY_GET'
        logger.info("[SMS24H] Reenvio (id=%s) -> %s", activation_id, r)
        return ok

    def finalizar(self, activation_id):
        """Marca a ativação como concluída (status=6)."""
        r = self._set_status(activation_id, 6)
        return r.startswith('ACCESS_ACTIVATION')

    def cancelar(self, activation_id):
        """Cancela a ativação (status=8) — devolve o número/saldo se possível."""
        r = self._set_status(activation_id, 8)
        return r.startswith('ACCESS_CANCEL')


# ---------------------------------------------------------------------- #
# Helpers de formatação de número (BR)
# ---------------------------------------------------------------------- #
def formatar_e164(numero):
    """Garante o formato +55XXXXXXXXXXX a partir do número do provedor.

    O sms24h devolve o número COM código do país (ex.: '5573924576507').
    O campo 'Telefone comercial' do Facebook aceita +<país><ddd><numero>.
    """
    so_digitos = ''.join(ch for ch in str(numero or '') if ch.isdigit())
    if not so_digitos:
        return ''
    if not so_digitos.startswith('55'):
        so_digitos = '55' + so_digitos
    return '+' + so_digitos


def separar_ddd_numero(numero):
    """Retorna (ddd, numero_local) a partir de um número BR com/sem +55.

    Ex.: '5573924576507' -> ('73', '924576507')  (DDD 73 + 9 dígitos)
    Útil para preencher o telefone no certificado: '(73) 92457-6507'.
    """
    d = ''.join(ch for ch in str(numero or '') if ch.isdigit())
    if d.startswith('55') and len(d) >= 12:
        d = d[2:]
    if len(d) >= 10:
        return d[:2], d[2:]
    return '', d


def formatar_nacional(numero):
    """Formata como '(DD) XXXXX-XXXX' / '(DD) XXXX-XXXX' (telefone do certificado)."""
    ddd, local = separar_ddd_numero(numero)
    if not ddd or not local:
        return str(numero or '')
    if len(local) == 9:
        return f'({ddd}) {local[:5]}-{local[5:]}'
    if len(local) == 8:
        return f'({ddd}) {local[:4]}-{local[4:]}'
    return f'({ddd}) {local}'


# ---------------------------------------------------------------------- #
# ADAPTADOR vak-sms.com — API REST própria, MESMA interface do SMS24HClient
# ---------------------------------------------------------------------- #
class VakSmsClient:
    """Cliente do vak-sms.com falando a MESMA interface dos demais provedores.

    O vak-sms NÃO usa o protocolo SMS-Activate; a API é REST/JSON. Mapeamento
    (confirmado sondando a API em 2026-08-03):

        comprar_numero      -> GET getNumber/?service=fb&country=br[&price=]
                               -> {"tel": 5511..., "idNum": "..."}  |  {"error":"noMoney"}
        consultar_status    -> GET getSmsCode/?idNum=  -> {"smsCode": "1234"} ou null
        solicitar_reenvio   -> GET setStatus/?idNum=&status=send
        finalizar           -> GET setStatus/?idNum=&status=end
        cancelar            -> GET setStatus/?idNum=&status=bad
        saldo               -> GET getBalance/         -> {"balance": 0}

    Os códigos são `service='fb'` e `country='br'` (NÃO o '73' do SMS-Activate) —
    a tradução acontece aqui dentro, então o chamador continua passando os mesmos
    SERVICE_FACEBOOK/COUNTRY_BRASIL de sempre.
    """

    BASE = 'https://vak-sms.com/api/'
    # traduz os códigos do protocolo SMS-Activate para os do vak-sms
    _PAISES = {'73': 'br', 'br': 'br'}
    _SERVICOS = {'fb': 'fb'}

    def __init__(self, api_key, provedor='vak'):
        self.api_key = str(api_key or '').strip()
        self.provedor = provedor
        self.nome_provedor = nome_do_provedor(provedor)
        self.moeda = moeda_do_provedor(provedor)
        self.api_url = self.BASE

    # ------------------------------------------------------------------ #
    # ⚠️ O vak-sms tem DOIS formatos de erro (medido em 2026-08-03):
    #   a) erro de negócio  → HTTP 200 {"error":"noMoney"|"noNumber"|"noService"}
    #   b) erro de PLATAFORMA → HTTP 4xx e um envelope do gateway SEM o campo
    #      `error`, com o erro de verdade ANINHADO dentro de `message`:
    #      {"statusCode":400,"message":"UserApiService error: {\"error\":\"Пользователь
    #       не найден\"}","code":"UserNotFound",...}
    # Só o formato (a) era tratado — no (b) `d.get('error')` dava None e o erro
    # virava "desconhecido", classificado como INSTABILIDADE. Resultado real: com
    # o token errado/expirado o fluxo ficava em retry infinito → PAUSA, em vez de
    # dizer "token inválido" e pular para o próximo provedor.
    _CODIGOS_GATEWAY = {
        'usernotfound': 'apiKeyNotFound',
        'unauthorized': 'apiKeyNotFound',
        'forbidden': 'apiKeyNotFound',
        'toomanyrequests': 'rateLimit',
    }

    @classmethod
    def _erro_do_gateway(cls, d):
        """Extrai o erro real do envelope de erro do gateway."""
        msg = str(d.get('message') or '')
        m = re.search(r'"error"\s*:\s*"([^"]+)"', msg)
        if m:
            bruto = m.group(1).strip()
            # a API mistura idiomas ("Пользователь не найден" = usuário não
            # encontrado); o `code` é estável, então ele manda.
            cod = cls._CODIGOS_GATEWAY.get(str(d.get('code') or '').lower())
            return cod or bruto
        cod = str(d.get('code') or '').lower()
        return cls._CODIGOS_GATEWAY.get(cod, cod or f"http_{d.get('statusCode')}")

    def _req(self, metodo, params=None):
        """GET no endpoint e devolve o JSON decodificado (ou {'error': ...})."""
        if requests is None:
            return {'error': 'requests_indisponivel'}
        p = dict(params or {})
        p['apiKey'] = self.api_key
        try:
            r = requests.get(self.BASE + metodo + '/', params=p, timeout=30,
                             headers={'User-Agent': 'Mozilla/5.0'})
        except Exception as e:
            logger.warning('[%s] %s falhou: %s', self.nome_provedor, metodo, e)
            return {'error': 'rede'}
        try:
            d = r.json() if r.content else {}
        except Exception:
            logger.warning('[%s] %s devolveu não-JSON (HTTP %s): %s',
                           self.nome_provedor, metodo, r.status_code,
                           (r.text or '')[:150])
            return {'error': f'http_{r.status_code}'}
        if isinstance(d, dict) and 'error' not in d and 'statusCode' in d:
            erro = self._erro_do_gateway(d)
            logger.warning('[%s] %s -> erro de plataforma HTTP %s (%s): %s',
                           self.nome_provedor, metodo, r.status_code, erro,
                           str(d.get('message'))[:150])
            d = dict(d, error=erro)
        return d if isinstance(d, dict) else {'error': 'resposta_inesperada'}

    def _pais(self, country):
        return self._PAISES.get(str(country or '').strip().lower(), 'br')

    def _servico(self, service):
        return self._SERVICOS.get(str(service or '').strip().lower(), str(service or 'fb'))

    # ------------------------------------------------------------------ #
    def saldo(self):
        d = self._req('getBalance')
        try:
            return float(d.get('balance')) if 'balance' in d else None
        except Exception:
            return None

    def token_valido(self):
        """True/False/None — None = indeterminado (rede/API). Ver SMS24HClient."""
        d = self._req('getBalance') or {}
        if 'balance' in d:
            return True
        if str(d.get('error') or '') == 'apiKeyNotFound':
            return False
        return None

    def estoque(self, service='fb', country='73'):
        """(quantidade, preço) disponíveis — útil p/ diagnóstico."""
        d = self._req('getCountNumber', {'service': self._servico(service),
                                         'country': self._pais(country), 'price': 'true'})
        serv = self._servico(service)
        return d.get(serv), d.get('price')

    def comprar_numero(self, service='fb', country='73', operator='any', max_price=None):
        if not self.api_key:
            return {'sucesso': False, 'id': '', 'numero': '',
                    'mensagem': f'Token do {self.nome_provedor} não configurado.'}
        p = {'service': self._servico(service), 'country': self._pais(country)}
        if max_price:
            # O vak-sms aceita escolher a FAIXA DE PREÇO, mas exige o valor com
            # EXATAMENTE 2 CASAS DECIMAIS. Medido em 2026-08-03:
            #   price=0.80 / 1 / 3 / 0.01 -> compra normal
            #   price=0.8 (1 casa) e price=0.106 (3 casas) -> {"error":"noService"}
            # `str(float)` produzia justamente '0.1'/'0.106' — o teto de preço da
            # GUI (compartilhado com Tiger/Grizzly) derrubava TODA compra no vak
            # com um erro que parecia "serviço inválido".
            try:
                p['price'] = f'{float(str(max_price).replace(",", ".")):.2f}'
            except Exception:
                pass
        if operator and operator != 'any':
            p['operator'] = operator
        d = self._req('getNumber', p)

        # Teto de preço recusado? Ele é uma PREFERÊNCIA, não um requisito —
        # repete sem o teto em vez de falhar a compra.
        if str(d.get('error') or '') == 'noService' and 'price' in p:
            logger.warning('[%s] price=%s recusado (noService) — repetindo sem teto.',
                           self.nome_provedor, p['price'])
            p.pop('price', None)
            d = self._req('getNumber', p)

        if d.get('tel') and d.get('idNum'):
            numero = ''.join(ch for ch in str(d['tel']) if ch.isdigit())
            logger.info('[%s] Número comprado: id=%s numero=%s',
                        self.nome_provedor, d['idNum'], numero)
            return {'sucesso': True, 'id': str(d['idNum']), 'numero': numero,
                    'mensagem': 'Número comprado.'}

        erro = str(d.get('error') or 'desconhecido')
        if erro == 'desconhecido':
            # Não deveria acontecer — registra o corpo CRU para o próximo
            # diagnóstico não depender de sondar a API de novo.
            logger.warning('[%s] getNumber sem tel e sem error: %r', self.nome_provedor, d)
        _p = self.nome_provedor
        mapa = {
            'noMoney': f'Saldo insuficiente no {_p}.',
            'noNumber': f'Sem números disponíveis no {_p} para o serviço/país agora.',
            'noService': f'Serviço inválido no {_p}.',
            'badService': f'Serviço inválido no {_p}.',
            'noCountry': f'País inválido no {_p}.',
            'apiKeyNotFound': f'Token (api_key) do {_p} inválido ou expirado.',
            'badStatus': f'Status inválido no {_p}.',
            'rateLimit': f'{_p} limitou as requisições (rate limit).',
            'rede': f'{_p} sem resposta (rede).',
        }
        # NO_BALANCE/NO_NUMBERS/BAD_KEY: mantemos os códigos que o fluxo já conhece,
        # para a classificação de erro do chamador continuar valendo sem mudanças.
        codigo = {'noMoney': 'NO_BALANCE', 'noNumber': 'NO_NUMBERS',
                  'apiKeyNotFound': 'BAD_KEY', 'badService': 'BAD_SERVICE',
                  'noService': 'BAD_SERVICE'}.get(erro, erro.upper())
        return {'sucesso': False, 'id': '', 'numero': '', 'codigo': codigo,
                'mensagem': mapa.get(erro, f'{_p}: {erro}')}

    def consultar_status(self, activation_id):
        """Devolve no formato do protocolo SMS-Activate, p/ o fluxo não mudar."""
        d = self._req('getSmsCode', {'idNum': str(activation_id)})
        cod = d.get('smsCode')
        if cod:
            return 'STATUS_OK:' + str(cod).strip()
        if str(d.get('error') or '') in ('idNumNotFound', 'badData'):
            return 'STATUS_CANCEL'
        return 'STATUS_WAIT_CODE'

    def aguardar_codigo(self, activation_id, timeout=90, intervalo=5):
        inicio = time.time()
        while time.time() - inicio < timeout:
            r = self.consultar_status(activation_id)
            if r.startswith('STATUS_OK:'):
                return {'sucesso': True, 'codigo': r.split(':', 1)[1].strip(),
                        'mensagem': 'Código recebido.'}
            if r == 'STATUS_CANCEL':
                return {'sucesso': False, 'codigo': '',
                        'mensagem': 'Ativação cancelada/expirada.'}
            time.sleep(intervalo)
        return {'sucesso': False, 'codigo': '',
                'mensagem': f'SMS não chegou em {timeout}s.'}

    def _set_status(self, activation_id, status):
        d = self._req('setStatus', {'idNum': str(activation_id), 'status': status})
        return not d.get('error')

    def solicitar_reenvio(self, activation_id):
        ok = self._set_status(activation_id, 'send')
        logger.info('[%s] Reenvio (id=%s) -> %s', self.nome_provedor, activation_id, ok)
        return ok

    def finalizar(self, activation_id):
        return self._set_status(activation_id, 'end')

    def cancelar(self, activation_id):
        """`bad` = devolve o número e estorna (quando ainda dentro do prazo)."""
        return self._set_status(activation_id, 'bad')
