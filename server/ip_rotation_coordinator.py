"""Coordenador de TROCA FORÇADA de IP 4G no meio do fluxo (pausa sincronizada).

Motivo (pedido do usuário 2026-07-14): quando um perfil cai na tela de rate-limit
de SMS da Meta ("Você tentou muitos códigos de verificação recentemente. Aguarde e
tente novamente mais tarde."), o limite é POR IP — trocar o IP do 4G reseta o limite
para TODOS os perfis que compartilham aquele IP. Mesmo com a rotação automática
DESATIVADA, essa tela OBRIGA a troca (senão o lote inteiro fica dando erro).

⚠️ Confirmado pelo dono 2026-08-28: PARAR todas as abas e trocar o IP É o certo —
o rate-limit é do IP (cota de códigos esgotada); como todas as abas saem pelo MESMO
IP, se uma bateu o limite as demais também vão bater. As abas que JÁ pediram o código
e estão AGUARDANDO o SMS não são interrompidas no meio (o checkpoint fica no topo do
loop; elas só param depois de o SMS chegar ou a espera esgotar) — se o código não
chegar, entram na troca de IP + número novo junto com as demais. (Reverteu a
tentativa por-aba da v1.55, que estava errada.)

Como funciona (barreira com thread coordenadora + TIMEOUT de segurança):
  - Cada worker chama register()/unregister() ao entrar/sair (delimita os ativos).
  - Cada worker chama checkpoint() em pontos SEGUROS (tela estática, entre navegações).
    Se há rotação pendente/rolando, o worker PARA ali até a rotação terminar.
  - O worker que caiu na tela de rate-limit chama request().
  - Uma thread coordenadora (run_coordinator) espera TODOS os ativos pararem
    (ou um TIMEOUT — nunca trava o lote), faz UMA troca de IP e libera todos.

O TIMEOUT é a rede de segurança: se algum worker demorar a chegar num checkpoint
(ex.: preso numa chamada de rede longa), a rotação acontece mesmo assim após o
tempo — quem estava no meio de algo pode ter um erro transitório, que o retry do
próprio fluxo (F5/re-navegar) resolve. Melhor isso que deadlock.
"""

import threading
import time
import random
import logging

logger = logging.getLogger("GS_BM_Creator.IPCoord")

# Segundos que a coordenadora espera TODOS pararem antes de rotacionar assim mesmo.
# Pedido do usuário (2026-07-18): ANTES do modo avião, TODAS as abas devem estar
# estáticas/paradas — por isso a espera é generosa. O timeout é só a rede de segurança
# contra deadlock (se um navegador travar de vez, rotaciona mesmo assim e o fluxo se
# recompõe: número novo + F5/reabrir a aba). Ver etapa_verificacao_negocio.
# É maior que a espera máxima do SMS (SMS_ESPERA_MAX=120s) de propósito: dá tempo das
# abas que JÁ estão aguardando o SMS terminarem a espera antes da troca de IP.
_TIMEOUT_DRENO = 180.0

# COOLDOWN: depois de UMA troca de IP, ignora novas solicitações por este tempo. Evita
# o "storm" coletivo quando várias abas mostram o rate-limit em sequência logo após a
# troca — elas só reiniciam com número novo (o IP já está fresco; o rate-limit que veem
# é resíduo da sessão antiga, de antes da troca). Pedido do usuário 2026-07-15.
_COOLDOWN_TROCA = 150.0

# GATE DE ENVIO DE SMS POR IP (anti-rajada de "muitos códigos"). Diagnóstico do dono
# (2026-08-30): o erro "Você tentou muitos códigos de verificação recentemente" aparece
# na PRÓPRIA tela de enviar (antes de qualquer código sair) porque VÁRIAS ABAS no MESMO
# IP clicam "Enviar SMS" quase simultaneamente → rajada de pedidos de código no mesmo IP.
# Este gate dá a cada aba um SLOT ESCALONADO: garante um espaçamento mínimo entre dois
# envios QUAISQUER no IP atual (fila de tickets). Ver `sms_send_slot`.
_SMS_GATE_GAP = 16.0     # segundos mínimos entre dois "Enviar SMS" no MESMO IP
_SMS_GATE_JITTER = 3.0   # ruído aleatório (±) p/ não ficar um padrão perfeitamente periódico


class _Coordenador:
    def __init__(self):
        self._cv = threading.Condition()
        self._ativo = False        # há um run em andamento?
        self._pendente = False     # rotação solicitada, aguardando dreno
        self._rotacionando = False # troca de IP em execução
        self._n_ativos = 0         # workers registrados
        self._n_parados = 0        # workers atualmente no checkpoint (parados)
        self._ciclo = 0            # incrementa a cada rotação concluída
        self._ultima_troca_ts = 0.0  # timestamp da última troca concluída (p/ cooldown)
        self._rotate_fn = None     # função que troca o IP (injetada)
        self._stop = False
        self._thread = None
        self._sms_lock = threading.Lock()  # serializa a RESERVA de slot de envio de SMS
        self._sms_prox_ts = 0.0    # instante em que o PRÓXIMO envio de SMS pode ocorrer (IP atual)
        self._sms_gap = _SMS_GATE_GAP

    # ---- ciclo de vida do run -------------------------------------------- #
    def begin_run(self, rotate_fn):
        """Inicia a coordenadora para um run. Idempotente."""
        with self._cv:
            self._rotate_fn = rotate_fn
            self._ativo = True
            self._stop = False
            self._pendente = False
            self._rotacionando = False
            self._n_ativos = 0
            self._n_parados = 0
            self._ultima_troca_ts = 0.0  # run novo: 1ª troca pode acontecer na hora
            self._sms_prox_ts = 0.0      # run novo: 1º envio de SMS pode acontecer na hora
            if self._thread and self._thread.is_alive():
                return
        t = threading.Thread(target=self._run_coordinator, daemon=True,
                             name="ip-rotation-coordinator")
        with self._cv:
            self._thread = t
        t.start()
        logger.info("[IPCoord] Coordenadora de troca forçada de IP iniciada.")

    def end_run(self):
        with self._cv:
            self._ativo = False
            self._stop = True
            self._pendente = False
            self._cv.notify_all()

    # ---- API dos workers -------------------------------------------------- #
    def register(self):
        with self._cv:
            if not self._ativo:
                return
            self._n_ativos += 1
            self._cv.notify_all()

    def unregister(self):
        with self._cv:
            if self._n_ativos > 0:
                self._n_ativos -= 1
            self._cv.notify_all()

    def request(self, motivo=""):
        """Um worker caiu na tela que OBRIGA troca de IP. Retorna o que o worker deve fazer:
          'solicitada'   → troca marcada AGORA (chame checkpoint e espere terminar);
          'em_andamento' → já há troca pendente/rolando (chame checkpoint e espere);
          'recente'      → IP foi trocado há POUCO (dentro do cooldown) por outra aba:
                           NÃO troca de novo — o worker só reinicia com número novo
                           (o rate-limit visto é resíduo da sessão antiga);
          'inativo'      → coordenadora não está ativa.
        O cooldown evita o "storm" coletivo: várias abas caindo no rate-limit em
        sequência logo após 1 troca fazem SÓ 1 troca de IP; as demais reiniciam."""
        with self._cv:
            if not self._ativo:
                return 'inativo'
            if self._pendente or self._rotacionando:
                return 'em_andamento'
            agora = time.time()
            if self._ultima_troca_ts > 0 and (agora - self._ultima_troca_ts) < _COOLDOWN_TROCA:
                logger.info("[IPCoord] Rate-limit em outra aba, mas IP trocado há %ss "
                            "(cooldown %ss) — NÃO troca de novo; worker reinicia com "
                            "número novo. %s", int(agora - self._ultima_troca_ts),
                            int(_COOLDOWN_TROCA), motivo)
                return 'recente'
            self._pendente = True
            logger.warning("[IPCoord] Troca FORÇADA de IP solicitada. %s", motivo)
            self._cv.notify_all()
            return 'solicitada'

    def checkpoint(self, alive_fn=None):
        """Ponto SEGURO: se há rotação pendente/rolando, PARA aqui até terminar.
        `alive_fn` (opcional) → False encerra a espera (ex.: navegador fechado)."""
        with self._cv:
            if not self._ativo or not (self._pendente or self._rotacionando):
                return
            ciclo_inicial = self._ciclo
            self._n_parados += 1
            self._cv.notify_all()
            try:
                while (self._ativo and (self._pendente or self._rotacionando)
                       and self._ciclo == ciclo_inicial and not self._stop):
                    self._cv.wait(timeout=2.0)
                    if alive_fn is not None:
                        try:
                            if not alive_fn():
                                break
                        except Exception:
                            pass
            finally:
                if self._n_parados > 0:
                    self._n_parados -= 1
                self._cv.notify_all()

    def esta_pendente(self):
        with self._cv:
            return self._pendente or self._rotacionando

    def ciclo_atual(self):
        """Nº de rotações de IP já concluídas neste run. Muda a cada troca — o backend
        usa p/ ZERAR o contador de 'perfis por IP' (cota) quando o IP trocou (por
        rate-limit OU pela própria cota). Leitura barata, sem bloquear o run."""
        with self._cv:
            return self._ciclo

    def set_sms_gap(self, segundos):
        """Ajusta (no run) o espaçamento mínimo entre envios de SMS no mesmo IP."""
        try:
            v = float(segundos)
            if v >= 0:
                self._sms_gap = v
        except Exception:
            pass

    def sms_send_slot(self, alive_fn=None, status_fn=None):
        """GATE anti-rajada: chame ANTES de clicar "Enviar SMS" (pedir código à Meta).

        Cada aba reserva um SLOT escalonado — garante ≥ `_sms_gap` segundos entre dois
        envios QUAISQUER no IP atual (fila de tickets), com pequeno jitter. Assim N abas
        no MESMO IP NÃO disparam o envio simultaneamente (causa do "muitos códigos de
        verificação recentemente"). A RESERVA é serial (lock curto); a ESPERA é fora do
        lock → cada aba dorme só até a SUA vez, sem travar as outras.

        Barato quando há 1 aba (ts no passado → envia na hora). `alive_fn`→False aborta a
        espera. Retorna os segundos que esperou (0 se foi imediato)."""
        gap = float(self._sms_gap or 0.0)
        if gap <= 0:
            return 0.0
        agora = time.time()
        with self._sms_lock:
            base = max(agora, self._sms_prox_ts)
            jitter = random.uniform(0, _SMS_GATE_JITTER) if _SMS_GATE_JITTER > 0 else 0.0
            meu_slot = base + jitter
            # o PRÓXIMO envio (de outra aba) só pode vir 1 gap depois do MEU slot.
            self._sms_prox_ts = meu_slot + gap
        espera_total = meu_slot - time.time()
        if espera_total <= 0.05:
            return 0.0
        if status_fn:
            try:
                status_fn(f"⏸️ Aguardando slot de envio de SMS ({int(espera_total)}s) — "
                          f"escalonando p/ não estourar o limite do IP compartilhado...")
            except Exception:
                pass
        fim = meu_slot
        while True:
            resta = fim - time.time()
            if resta <= 0:
                break
            if alive_fn is not None:
                try:
                    if not alive_fn():
                        break
                except Exception:
                    pass
            time.sleep(min(resta, 1.0))
        return max(0.0, espera_total)

    def _reset_sms_gate(self):
        """Zera a fila de envios de SMS (IP mudou ou run novo): o IP fresco começa já."""
        with self._sms_lock:
            self._sms_prox_ts = 0.0

    # ---- thread coordenadora --------------------------------------------- #
    def _run_coordinator(self):
        with self._cv:
            while not self._stop:
                if not self._pendente:
                    self._cv.wait(timeout=1.0)
                    continue
                # Espera TODOS os ativos pararem (ou timeout de segurança).
                prazo = time.time() + _TIMEOUT_DRENO
                while (self._pendente and not self._stop
                       and self._n_parados < self._n_ativos
                       and time.time() < prazo):
                    self._cv.wait(timeout=1.0)
                if self._stop:
                    break
                if not self._pendente:
                    continue
                if self._n_parados < self._n_ativos:
                    logger.warning("[IPCoord] Dreno por TIMEOUT (%s/%s parados) — "
                                   "rotacionando assim mesmo.", self._n_parados, self._n_ativos)
                else:
                    logger.info("[IPCoord] Todos os %s worker(s) parados — trocando IP.",
                                self._n_ativos)
                # Rotaciona (solta o lock — a troca pode demorar: várias estratégias).
                self._rotacionando = True
                self._pendente = False
                fn = self._rotate_fn
                self._cv.release()
                _ok = False
                try:
                    if fn:
                        # rotate_fn retorna True só com a troca de IP CONFIRMADA.
                        _ok = fn() is not False
                    else:
                        logger.error("[IPCoord] rotate_fn ausente — rotação ignorada.")
                except Exception as e:
                    logger.error("[IPCoord] Erro na troca de IP: %s", e)
                finally:
                    self._cv.acquire()
                self._rotacionando = False
                self._ciclo += 1  # SEMPRE libera os workers (não os deixa congelados)
                self._reset_sms_gate()  # IP novo → zera a fila de envios de SMS (começa já)
                if _ok:
                    self._ultima_troca_ts = time.time()  # inicia o COOLDOWN (evita storm)
                    logger.info("[IPCoord] Troca de IP CONFIRMADA — liberando workers (ciclo %s). "
                                "Cooldown de %ss: próximas abas com rate-limit só reiniciam.",
                                self._ciclo, int(_COOLDOWN_TROCA))
                else:
                    # Troca NÃO confirmada: NÃO liga o cooldown — a próxima aba que cair no
                    # rate-limit vai FORÇAR nova tentativa de troca (em vez de só reiniciar
                    # com o mesmo IP e ficar presa no erro).
                    self._ultima_troca_ts = 0.0
                    logger.error("[IPCoord] Troca de IP NÃO confirmada — liberando workers (ciclo %s) "
                                 "SEM cooldown; a próxima aba com rate-limit tentará trocar de novo.",
                                 self._ciclo)
                self._cv.notify_all()


# Singleton do processo.
COORD = _Coordenador()
