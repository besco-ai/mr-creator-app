"""
Rotação de IP de proxy CONTROLADA pelo GS Creator (via URL de rotação).

Formato do proxy com rotação: host:porta:user:senha:URL_DE_ROTACAO
  ex.: proxy.megaproxy.online:31001:mp1b717ed4:497d2de9c48c7cf2:https://megaproxy.online/r.php?t=TOKEN

COM url => o GS Creator gira o IP ANTES de criar o navegador (1 IP por proxy/aba)
e NO MEIO do fluxo se precisar. SEM url => o provedor usa o AUTO dele.

Funciona com QUALQUER provedor: basta a URL que, ao ser acessada, troca o IP.
Confirmamos a troca medindo o IP de saída PELO PRÓPRIO PROXY (api.ipify) antes/depois.
"""
import time
import logging

logger = logging.getLogger(__name__)

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


def _proxy_url(proxy: dict) -> str:
    u = (proxy.get('user') or '').strip()
    p = (proxy.get('pass') or '').strip()
    host = (proxy.get('ip') or '').strip()
    port = (proxy.get('port') or '').strip()
    if not host or not port:
        return ''
    auth = f"{u}:{p}@" if u else ''
    return f"http://{auth}{host}:{port}"


def ip_externo_via_proxy(proxy: dict, timeout: int = 12) -> str:
    """IP de saída visto POR FORA, passando pelo proxy. '' se falhar."""
    if requests is None:
        return ''
    pu = _proxy_url(proxy)
    if not pu:
        return ''
    for alvo in ('https://api.ipify.org', 'http://api.ipify.org'):
        try:
            r = requests.get(alvo, proxies={'http': pu, 'https': pu}, timeout=timeout)
            if r.ok and r.text.strip():
                return r.text.strip()
        except Exception:
            continue
    return ''


def tem_rotacao(proxy: dict) -> bool:
    return bool(proxy and (proxy.get('rot_url') or '').strip())


def girar_ip_da_aba(driver, motivo: str = '', status=None, timeout: int = 45) -> bool:
    """Troca o IP DESTA aba, isoladamente, pela URL de rotação do proxy dela.

    Cada aba do GS Creator roda atrás de um MegaProxy próprio — um device 4G/5G
    com chip dedicado. Então a troca é LOCAL: não pausa as outras abas, não passa
    pelo coordenador global e não depende do "Auto" do painel do MegaProxy (que
    troca por tempo e pode cair no meio de uma etapa, atrapalhando o fluxo).

    O proxy vem anexado ao driver (`driver._proxy`) na criação do navegador.
    Retorna True se girou de fato. Se esta aba NÃO tem proxy com URL de rotação
    (ex.: modo 4G compartilhado por ADB), devolve False para o chamador cair no
    comportamento antigo — nada muda para quem não usa URL.
    """
    proxy = getattr(driver, '_proxy', None)
    if not tem_rotacao(proxy):
        return False
    if status:
        rot = (proxy.get('ip') or '?')
        status(f"🌐 Trocando o IP DESTA aba pelo proxy {rot}"
               + (f" ({motivo})" if motivo else "") + "...")
    try:
        ok = girar_ip(proxy, status=status, timeout=timeout, medir=True)
    except Exception as e:                                   # nunca derruba o fluxo
        logger.warning('[ProxyRotate] giro isolado da aba falhou: %s', e)
        return False
    if ok:
        logger.info('[ProxyRotate] IP da aba trocado (%s) — motivo: %s',
                    proxy.get('user') or proxy.get('ip'), motivo or '-')
    return bool(ok)


def girar_ip(proxy: dict, status=None, timeout: int = 45, medir: bool = True) -> bool:
    """Aciona a URL de rotação e espera o IP MUDAR de verdade (confirmado pelo IP
    externo via proxy). Retorna True se confirmou a troca (ou se respondeu num IP
    novo). Best-effort: nunca lança — em falha, loga e devolve False p/ o chamador
    decidir. ⚠️ Opera só neste proxy; sem estado compartilhado entre abas."""
    url = (proxy or {}).get('rot_url', '').strip()
    if not url or requests is None:
        return False

    def _s(m):
        if status:
            try:
                status(m)
            except Exception:
                pass

    ip0 = ip_externo_via_proxy(proxy) if medir else ''
    _s(f"🔁 Trocando IP do proxy (URL de rotação){f' — IP atual {ip0}' if ip0 else ''}...")
    try:
        requests.get(url, timeout=15)
    except Exception as e:
        logger.warning("[ProxyRotate] URL de rotação falhou (%s) — sigo aguardando o IP mudar.", e)

    if not medir:
        # sem medição: dá o tempo do ciclo de rádio (modo avião ~18s) e segue.
        time.sleep(min(25, max(8, timeout)))
        return True

    fim = time.time() + max(15, int(timeout))
    time.sleep(6)  # deixa o rádio começar a cair antes de medir
    ultimo = ''
    while time.time() < fim:
        ipn = ip_externo_via_proxy(proxy)
        ultimo = ipn or ultimo
        if ipn and ip0 and ipn != ip0:
            _s(f"✅ IP trocado: {ip0} → {ipn}")
            return True
        if ipn and not ip0:
            _s(f"✅ Proxy respondendo no IP {ipn} após rotação.")
            return True
        time.sleep(3)
    _s(f"⚠️ Não confirmei a troca de IP (último visto: {ultimo or '—'}) — seguindo mesmo assim.")
    return False
