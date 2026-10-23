# -*- coding: utf-8 -*-
"""Cliente de SMS CENTRAL do GranaSocial — drop-in do cliente local (sms24h_client).

O GS Creator deixa de comprar SMS DIRETO nos provedores (tokens na GUI) e passa a
pedir o número ao serviço CENTRAL do painel (`software_api.php` actions comprar_sms/
verificar_sms/reenviar_sms/cancelar_sms), cobrado do SALDO REAL do usuário (R$).

⚠️ FONTE OCULTA: o painel devolve só um `servidor_id` OPACO (nunca o nome do provedor).
O fallback entre servidores (estratégia top-N do admin) é INTERNO aqui: a cada compra
BEM-SUCEDIDA o servidor usado entra em `_excluidos`, então a PRÓXIMA compra (quando o
número não entrega o SMS e o bot re-compra) sai de OUTRO servidor. Esgotados todos,
zera e recomeça do 1º.

Interface espelha a do SMS24HClient para ser plugado sem mexer no fluxo:
  comprar_numero(service,country,operator,max_price) -> {'sucesso','id','numero',...}
  aguardar_codigo(activation_id,timeout,intervalo)   -> {'sucesso','codigo'} | {}
  solicitar_reenvio(activation_id)
  cancelar(activation_id) -> bool
  saldo() -> None    (o painel já mostra o saldo; não bloqueia o fluxo)
"""
import logging

logger = logging.getLogger("GS_BM_Creator.PanelSMS")


class PanelSmsClient:
    def __init__(self, callback_status=None):
        self.moeda = 'R$'
        self.nome_provedor = 'GS SMS'
        self._callback = callback_status
        self._excluidos = []          # servidores já usados NESTA verificação (fallback top-N)
        self._ultimo_timeout = 1200   # timeout (s) do último número, informado pelo painel

    # ------------------------------------------------------------------ #
    def _post(self, action, extra=None):
        from server import acesso
        return acesso._api_post(action, extra or {}) or {}

    def saldo(self):
        return None

    def comprar_numero(self, service='fb', country='73', operator='any', max_price=None):
        extra = {'servico': str(service or 'fb')}
        if self._excluidos:
            extra['excluir_servidores'] = ','.join(str(x) for x in self._excluidos)
        res = self._post('comprar_sms', extra)
        ativ = res.get('ativacao_id')
        if res.get('sucesso') and ativ:
            sid = int(res.get('servidor_id') or 0)
            if sid and sid not in self._excluidos:
                self._excluidos.append(sid)   # próximo número sai de OUTRO servidor (fallback)
            self._ultimo_timeout = int(res.get('timeout_segundos') or 1200)
            return {
                'sucesso': True,
                'id': str(ativ),
                'numero': str(res.get('numero') or ''),
                'mensagem': res.get('mensagem', 'Número comprado.'),
                'servidor_id': sid,
                'timeout_segundos': self._ultimo_timeout,
                'novo_saldo': res.get('novo_saldo'),
            }

        # ── FALHAS → mapeadas para os códigos que o fluxo do bot já entende ──
        # Saldo do USUÁRIO insuficiente → NO_BALANCE (o fluxo PAUSA e pede recarga).
        if res.get('saldo_insuficiente'):
            return {'sucesso': False, 'id': '', 'numero': '', 'codigo': 'NO_BALANCE',
                    'mensagem': res.get('mensagem', 'Saldo insuficiente — recarregue o saldo.')}
        # Todos os servidores já tentados nesta verificação → zera e reinsiste do 1º
        # (número novo pode liberar). Trata como transitório (NO_NUMBERS).
        if res.get('sem_servidores'):
            self._excluidos = []
            return {'sucesso': False, 'id': '', 'numero': '', 'codigo': 'NO_NUMBERS',
                    'mensagem': res.get('mensagem', 'Sem número no momento — reinsistindo.')}
        # Erro de um servidor específico (NO_NUMBERS / rede / provedor sem saldo):
        # exclui esse servidor e devolve TRANSITÓRIO → o fluxo reinsiste e o próximo
        # número sai de outro servidor. (NO_BALANCE aqui = saldo do PROVEDOR, não do
        # usuário → não pausa o usuário; o admin repõe o provedor.)
        sid = int(res.get('servidor_id') or 0)
        if sid and sid not in self._excluidos:
            self._excluidos.append(sid)
        cod = str(res.get('provedor_erro') or '').upper()
        if not cod or 'NO_BALANCE' in cod:
            cod = 'NO_NUMBERS'
        return {'sucesso': False, 'id': '', 'numero': '', 'codigo': cod,
                'mensagem': res.get('mensagem', 'Sem número no momento.')}

    def aguardar_codigo(self, activation_id, timeout=5, intervalo=2):
        """UMA consulta ao painel (o laço/anti-flood fica no chamador _aguardar_codigo_sms)."""
        try:
            res = self._post('verificar_sms', {'ativacao_id': int(activation_id)})
        except Exception as e:
            logger.debug("[PanelSMS] verificar_sms erro: %s", e)
            return {}
        if res.get('sucesso') and res.get('sms_status') == 'recebido' and res.get('codigo'):
            return {'sucesso': True, 'codigo': str(res.get('codigo')).strip()}
        return {}

    def solicitar_reenvio(self, activation_id):
        try:
            return self._post('reenviar_sms', {'ativacao_id': int(activation_id)})
        except Exception:
            return {}

    def cancelar(self, activation_id):
        try:
            res = self._post('cancelar_sms', {'ativacao_id': int(activation_id)})
            return bool(res.get('sucesso'))
        except Exception:
            return False

    def finalizar(self, activation_id):
        return True

    # compat: alguns pontos leem .consultar_status; não é usado no fluxo do painel.
    def consultar_status(self, activation_id):
        return {}
