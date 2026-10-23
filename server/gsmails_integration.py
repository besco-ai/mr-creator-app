"""
Integração GSMAILS (TMail v2) — API privada para o GS BM Creator
================================================================
Substitui o TMail por navegador (aba do webmail antigo) por chamadas diretas à
API privada do painel GSMAILS:

  • create_email() → gera e-mail + senha (já salvos no banco do GSMAILS; o
    usuário pode depois logar em gsmails.com com esse e-mail/senha).
  • wait_fb_link() → aguarda o e-mail de confirmação da BM e extrai o LINK
    "Confirmar agora" (a verificação de e-mail da BM é por link).
  • wait_code() → aguarda um CÓDIGO (Facebook/Instagram/qualquer rede).

Tudo é tolerante a falha: se a API não responder, o chamador faz fallback para
o fluxo antigo (navegador). Entrega é sub-segundo (daemon IMAP no servidor).

Para LIGAR/DESLIGAR: GSMAILS_ENABLED (constante abaixo) ou variável de ambiente
GSMAILS_ENABLED=0/1. Base/Key também por env (GSMAILS_BASE_URL/GSMAILS_API_KEY).
"""
from __future__ import annotations
import os
import re
import time
import random
import unicodedata
import logging

logger = logging.getLogger("GS_BM_Creator.GSMAILS")

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

# ── Configuração ────────────────────────────────────────────────────────────
GSMAILS_ENABLED  = os.getenv("GSMAILS_ENABLED", "1") not in ("0", "false", "False", "")
from server.marca import URL_MAIL as _URL_MAIL_DA_MARCA   # fonte unica: server/marca.py
GSMAILS_BASE_URL = os.getenv("GSMAILS_BASE_URL", _URL_MAIL_DA_MARCA)
GSMAILS_API_KEY  = os.getenv("GSMAILS_API_KEY", "")
_API = GSMAILS_BASE_URL.rstrip("/") + "/api/gscreator.php"

# User-Agent próprio é OBRIGATÓRIO (o Cloudflare bloqueia UA de bibliotecas).
_HEADERS = {
    "Authorization": f"Bearer {GSMAILS_API_KEY}",
    "User-Agent": f"GSCreator/1.0 (+{_URL_MAIL_DA_MARCA})",
    "Accept": "application/json",
}


def gsmails_enabled() -> bool:
    """True se a integração via API está ligada e utilizável."""
    return bool(GSMAILS_ENABLED and requests is not None)


def _post(action: str, read_timeout: int = 20, **params):
    params["action"] = action
    params["api_key"] = GSMAILS_API_KEY
    try:
        r = requests.post(_API, data=params, headers=_HEADERS, timeout=read_timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("[GSMAILS] %s falhou: %s", action, e)
        return None


def ping() -> bool:
    d = _post("ping")
    return bool(d and d.get("ok"))


# ── Geração de local-part realista/corporativo ──────────────────────────────
# E-mails antes saíam estilo "raptorphantom4919" (gerador aleatório do servidor).
# Agora montamos um local-part com cara de pessoa real/empresa: nome + sobrenome
# (usando a RAZÃO SOCIAL quando disponível) e, se já existir, acrescentamos info
# extra (número) para garantir unicidade — fica mais real e corporativo.
_PRIMEIROS = [
    "bruno", "carla", "diego", "fernanda", "gustavo", "juliana", "rafael", "mariana",
    "thiago", "patricia", "felipe", "aline", "rodrigo", "camila", "leonardo", "beatriz",
    "andre", "larissa", "marcelo", "vanessa", "eduardo", "tatiane", "vinicius", "priscila",
    "ricardo", "amanda", "daniel", "renata", "gabriel", "leticia", "fabio", "carolina",
]
_SOBRENOMES = [
    "silva", "souza", "oliveira", "santos", "pereira", "almeida", "ferreira", "costa",
    "rodrigues", "gomes", "martins", "araujo", "ribeiro", "carvalho", "lima", "barbosa",
    "rocha", "dias", "nunes", "mendes", "cardoso", "teixeira", "moraes", "correia",
]
_STOP_NOME = {"da", "de", "do", "das", "dos", "e", "ltda", "mei", "eireli", "me", "epp", "sa", "ss"}


def _ascii_letras(txt: str) -> str:
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", t.lower())


def _local_corporativo(base_nome: str | None = None, tentativa: int = 0) -> str:
    """Monta um local-part realista. Usa partes da razão social quando fornecida;
    senão gera um nome BR plausível. `tentativa`>0 acrescenta número (mais info)
    para garantir unicidade quando o local já existe."""
    tokens: list[str] = []
    if base_nome:
        cru = re.sub(r"\d+", " ", base_nome)
        for p in re.split(r"\s+", cru.strip()):
            pl = _ascii_letras(p)
            if pl and pl not in _STOP_NOME:
                tokens.append(pl)
            if len(tokens) >= 2:
                break
    if len(tokens) < 2:
        tokens = [random.choice(_PRIMEIROS), random.choice(_SOBRENOMES)]
    sep = random.choice([".", ".", ""])  # tende ao ponto (mais corporativo)
    base = (tokens[0] + sep + tokens[1])[:40]
    if tentativa == 0:
        suf = random.choice(["", "", str(random.randint(1, 99))])
    else:
        suf = str(random.randint(100, 9999))
    local = (base + suf).strip(".")
    local = re.sub(r"\.{2,}", ".", local)
    return local[:48]


def create_email(label: str | None = None, base_nome: str | None = None,
                 host: str | None = None, domain: str | None = None) -> dict | None:
    """Gera e-mail + senha (salvos no painel). Retorna {address,password,token}
    ou None em falha.

    `host` — subdomínio do site. **IGNORADO desde 2026-08-10** (parâmetro mantido
      só para não mexer nas 5 chamadas). O e-mail da BM passou a nascer numa RAIZ
      PÚBLICA do gsmails (`fulano@raiz.com`), não mais no subdomínio do site.

      Por que mudou: o endereço do subdomínio prendia o e-mail ao site — e só o
      1º endereço de cada subdomínio podia ser criado (o resto batia em
      `subdominio_de_outro_usuario` e caía no @gspromax.com). Agora o gsmails
      publica as raízes .com fora de serviço como bases públicas no apex, então
      há dezenas de domínios livres e o rodízio distribui a carga que antes se
      concentrava numa raiz só. Para reverter: `USAR_EMAIL_DO_SITE=True` em
      automacao_facebook.py e restaurar o bloco `domain=host` aqui.

    O servidor sorteia a raiz a cada chamada (tm_settings.domain_mode='random');
    o local-part continua realista/corporativo via `base_nome`/razão social."""
    if not gsmails_enabled():
        return None

    def _ok(d):
        if d and d.get("ok") and d.get("address"):
            logger.info("[GSMAILS] e-mail gerado: %s", d["address"])
            return {"address": d["address"], "password": d.get("password", ""),
                    "token": d.get("token", "")}
        return None

    # ── 🛡️ E-MAIL DE SUBDOMÍNIO (REATIVADO 2026-09-09): se `host` for um subdomínio
    #    VÁLIDO (razaosocial.raiz — 2+ pontos), cria o e-mail EXATAMENTE nele. O GSMAILS
    #    aceita qualquer subdomínio de uma raiz wildcard (testado ao vivo), então o
    #    e-mail da BM = o e-mail do site → isola cada entidade e NÃO cruza a raiz entre
    #    várias BMs. A trava antiga ('subdominio_de_outro_usuario' / só 1 por subdomínio)
    #    não vale mais. Se por acaso recusar, cai no apex/pública abaixo.
    _host = (host or '').strip().lower()
    _host = re.sub(r'^https?://', '', _host).split('/')[0].strip('.')
    if _host and _host.count('.') >= 2:
        for tentativa in range(3):
            params = {"local": _local_corporativo(base_nome, tentativa), "domain": _host}
            if label:
                params["label"] = label
            res = _ok(_post("create_email", **params))
            if res:
                return res
        logger.info("[GSMAILS] subdomínio '%s' indisponível — tentando apex/pública.", _host)

    # ── 📧 COERÊNCIA (Método Pro Max E-mail): se `domain` (o APEX da RAIZ DO SITE)
    #    for dado, cria o e-mail NELE. É o domínio que a Meta usa na verificação por
    #    e-mail, o que vai no CERTIFICADO e o que é SALVO p/ o usuário — tudo alinhado.
    #    Só vinga se a raiz tem apex_email=1 (pool do método); se recusar, cai na raiz
    #    pública sorteada (fallback abaixo). (2026-08-15)
    if domain:
        for tentativa in range(3):
            params = {"local": _local_corporativo(base_nome, tentativa), "domain": domain}
            if label:
                params["label"] = label
            res = _ok(_post("create_email", **params))
            if res:
                return res
        logger.info("[GSMAILS] apex da raiz do site '%s' indisponível — raiz pública.", domain)

    # ── Raiz pública sorteada pelo servidor, com local-part corporativo ─────
    # Tenta nomes corporativos (com unicidade incremental).
    for tentativa in range(5):
        params = {"local": _local_corporativo(base_nome, tentativa)}
        if label:
            params["label"] = label
        res = _ok(_post("create_email", **params))
        if res:
            return res
        logger.info("[GSMAILS] local '%s' indisponível/inválido — novo nome.", params["local"])

    # Fallback: deixa o servidor gerar um local aleatório.
    params = {}
    if label:
        params["label"] = label
    return _ok(_post("create_email", **params))


# Palavras-chave que costumam anteceder um OTP (multi-plataforma/idioma).
_OTP_KW = (
    'one time password', 'one-time password', 'otp', 'validate your email',
    'verification code', 'verify your email', 'código de confirmação',
    'codigo de confirmacao', 'confirmation code', 'seu código', 'seu codigo',
    'código', 'codigo', 'code', 'senha de uso único', 'senha de uso unico',
)


def extract_otp(html: str = "", text: str = "") -> str | None:
    """Extrai um código OTP (4-8 dígitos) do corpo de um e-mail. Robusto a formatos
    variados (Gupshup 'One Time Password ... 465158', Facebook, etc.). Evita pegar
    IDs longos (ex.: 'Customer ID: 4000358753') exigindo bloco de 4-8 dígitos
    isolado e priorizando a proximidade de uma palavra-chave de OTP."""
    raw = (text or "")
    if html:
        raw += "\n" + re.sub(r'<[^>]+>', ' ', html)
    raw = raw.replace('&nbsp;', ' ').replace('&zwnj;', ' ')
    raw = re.sub(r'https?://\S+', ' ', raw)   # remove URLs (não pegar dígitos de ?mid=)
    raw = re.sub(r'\s+', ' ', raw)
    # 🚫 Remove o RODAPÉ de endereço da Meta ANTES de extrair. O CEP "94025" de
    # "Menlo Park, CA 94025" tem 5 dígitos IGUAL a um código de criação de conta —
    # a distinção é pelo CONTEXTO (rodapé), não pelo tamanho. Espelha o mx01.
    raw = re.sub(r'\bmeta platforms\b.*$', ' ', raw, flags=re.I)
    raw = re.sub(r'\bmenlo park,?\s*[a-z]{2}\s*\d{4,5}\b', ' ', raw, flags=re.I)
    raw = re.sub(r'\b1 meta way\b', ' ', raw, flags=re.I)
    raw = re.sub(r'\bca\s+9\d{4}\b', ' ', raw, flags=re.I)
    # Código ADJACENTE a uma frase de código (antes OU depois) — 4-8 dígitos (o de
    # CRIAÇÃO DE CONTA é 5: "95148 é seu código de confirmação").
    for pat in (
        r'(\d{4,8})\s*(?:[ée]\s+o?\s*seu\s+c[oó]digo|is your\b.{0,25}\bcode)',
        r'(?:c[oó]digo\s+de\s+(?:confirma[cç][aã]o|verifica[cç][aã]o)|'
        r'(?:confirmation|verification)\s+code|c[oó]digo|\bcode\b|otp|pin)[\s:#=.-]{0,4}(\d{4,8})\b',
        r'(?<![A-Za-z0-9])(\d{4,8})(?=\s*(?:n[aã]o\s+compartilh|do not share))',
        r'\bFB[-\s]?(\d{4,8})\b',
    ):
        m = re.search(pat, raw, re.I)
        if m:
            return m.group(1)
    # Fallback: 4-8 dígitos NÃO colado a letra/dígito ANTES (ignora número dentro de
    # e-mail/palavra tipo "striker9272@"); permite colado DEPOIS ("95148Não").
    m = re.search(r'(?<![A-Za-z0-9])(\d{4,8})(?!\d)', raw)
    if m:
        return m.group(1)
    return None


def latest_msg_id(address: str) -> int:
    """Maior id de mensagem JÁ na caixa de `address` (0 se vazia). Serve de BASELINE:
    o fluxo captura isto ANTES de pedir o código e depois só aceita id > baseline —
    assim pega SÓ o e-mail que chegou DEPOIS da solicitação, nunca um antigo."""
    if not gsmails_enabled():
        return 0
    try:
        d = _post("messages", read_timeout=20, address=address)
        if d and d.get("ok"):
            ids = [int(m.get("id", 0) or 0) for m in (d.get("messages") or [])]
            return max(ids) if ids else 0
    except Exception as e:
        logger.warning("[GSMAILS] latest_msg_id falhou: %s", e)
    return 0


def _otp_from_messages(address: str, from_filter: str = "", since_id: int = 0) -> str | None:
    """Busca as mensagens do `address` e extrai o OTP LOCALMENTE (a extração
    server-side às vezes não reconhece o formato — ex.: OTP da Gupshup). Pega o
    código mesmo que o servidor não o tenha reconhecido.

    `since_id`>0: considera SÓ mensagens com id maior (frescor — ignora códigos
    antigos que já estavam na caixa antes de solicitar)."""
    d = _post("messages", read_timeout=25, address=address)
    if not (d and d.get("ok")):
        return None
    msgs = d.get("messages", []) or []
    ff = (from_filter or "").lower()

    def _varrer(usar_filtro):
        for m in msgs:
            if since_id:
                try:
                    if int(m.get("id", 0) or 0) <= since_id:
                        continue
                except Exception:
                    pass
            if usar_filtro and ff:
                meta = ((m.get("from", "") or "") + " " + (m.get("subject", "") or "")).lower()
                if ff not in meta:
                    continue
            code = extract_otp(m.get("body_html", ""), m.get("body_text", ""))
            if code:
                return code
        return None

    return _varrer(True) or _varrer(False)


def wait_code(address: str, from_filter: str = "", timeout: int = 120,
              since_id: int = 0) -> str | None:
    """Aguarda um código (OTP) chegar para `address`. Retorna o código ou None.
    `since_id`>0 → SÓ aceita e-mail com id maior (frescor: pega o que chega DEPOIS
    de solicitar, nunca um código antigo já na caixa). since_id=0 = qualquer.

    Faz POLLING interleaved: (1) `wait_code` server-side (extração no servidor) e,
    se não vier, (2) FALLBACK que baixa as mensagens e EXTRAI O OTP LOCALMENTE — isso
    pega códigos que o servidor não reconhece (ex.: OTP da Gupshup, formatos novos)."""
    if not gsmails_enabled():
        return None
    deadline = time.time() + max(5, timeout)
    while time.time() < deadline:
        _rem = max(5, int(deadline - time.time()))
        # (1) servidor — bloqueia curto (até ~12s) p/ poder intercalar o fallback.
        params = {"address": address, "timeout": min(_rem, 12), "since_id": since_id}
        if from_filter:
            params["from"] = from_filter
        d = _post("wait_code", read_timeout=min(_rem, 12) + 15, **params)
        code = d.get("code") if d else None
        if code:
            return code
        # (2) fallback LOCAL — baixa as mensagens e extrai o OTP aqui.
        try:
            code = _otp_from_messages(address, from_filter, since_id=since_id)
        except Exception as _e:
            logger.warning("[GSMAILS] fallback messages/otp falhou: %s", _e)
            code = None
        if code:
            logger.info("[GSMAILS] OTP extraído LOCALMENTE p/ %s", address)
            return code
        time.sleep(1)
    return None


def _clean_url(u: str) -> str:
    return (u or "").strip().rstrip(').,;"\'>')


def extract_confirmation_link(html: str, text: str = "") -> str | None:
    """Extrai o link de confirmação ('Confirmar agora') do corpo do e-mail.
    Estratégia robusta: pega o href do botão de confirmação do Facebook/Meta."""
    b = (html or "")
    b = b.replace("&amp;", "&").replace("&#x2F;", "/").replace("&#47;", "/").replace("&#x3D;", "=")

    # 1) Todos os href do corpo HTML
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', b, re.IGNORECASE)
    fb_hrefs = [h for h in hrefs
                if any(d in h.lower() for d in ("facebook.com", "fb.com", "meta.com", "facebookmail.com"))]
    # 1a) prioriza links que cheiram a confirmação
    for kw in ("confirm", "set_email", "setemail", "security", "verify", "/n/", "email", "business"):
        for h in fb_hrefs:
            if kw in h.lower():
                return _clean_url(h)
    # 1b) qualquer href do Facebook/Meta
    if fb_hrefs:
        return _clean_url(fb_hrefs[0])

    # 2) Fallback: URL solta no HTML ou no texto puro
    for body in (b, text or ""):
        m = re.search(r'https?://[^\s"\'<>]*?(?:facebook\.com|fb\.com|meta\.com)[^\s"\'<>]*', body, re.IGNORECASE)
        if m:
            return _clean_url(m.group(0))
    return None


def wait_fb_link(address: str, timeout: int = 150) -> str | None:
    """Aguarda o e-mail de confirmação da BM e devolve o LINK de confirmação.
    Varre TODAS as mensagens da conta (pega o e-mail mesmo que já tenha chegado
    antes desta chamada — corrige a corrida de since_id). Daemon-aware/instantâneo."""
    if not gsmails_enabled():
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = _post("messages", read_timeout=25, address=address)
        if d and d.get("ok"):
            for m in d.get("messages", []):
                link = extract_confirmation_link(m.get("body_html", ""), m.get("body_text", ""))
                if link:
                    logger.info("[GSMAILS] link de confirmação extraído para %s", address)
                    return link
        time.sleep(2)
    logger.warning("[GSMAILS] link de confirmação NÃO encontrado p/ %s em %ss", address, timeout)
    return None
