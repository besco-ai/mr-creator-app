#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Painel administrativo de usuarios — GS BM Creator
==================================================
Interface grafica (Tkinter) para gerenciar a tabela `users` do banco
GranaSocial usado pelo modulo `server/acesso.py`.

Recursos:
  * Listar / pesquisar usuarios
  * Adicionar novo usuario (com hash SHA-256 da senha)
  * Editar usuario (username, senha, role, tier, validade, saldo, bloqueio)
  * Remover usuario
  * Resetar licenca/dispositivo (limpa machine_id + session_token,
    permitindo logar em outro computador)
  * Estender validade da licenca em N dias
  * Bloquear / desbloquear conta

Banco: credenciais lidas de variaveis de ambiente (ver README.md).
Execute com:  python admin_usuarios.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox, simpledialog, ttk

try:
    import mysql.connector
except ImportError:
    print('ERRO: o pacote mysql-connector-python nao esta instalado.')
    print('Instale com:  pip install mysql-connector-python')
    sys.exit(1)


# ── Conexao com o banco (credenciais vem do ambiente — ver README.md) ──────
DB_HOST = os.environ.get('GS_DB_HOST', '127.0.0.1')
DB_PORT = int(os.environ.get('GS_DB_PORT', '3306'))
DB_USER = os.environ.get('GS_DB_USER', '')
DB_PASS = os.environ.get('GS_DB_PASS', '')
DB_NAME = os.environ.get('GS_DB_NAME', 'granasocial')
DB_CHARSET = 'utf8mb4'


def _connect():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset=DB_CHARSET,
        collation='utf8mb4_unicode_ci',
        autocommit=False,
        connection_timeout=10,
    )


def _sha256(senha: str) -> str:
    return hashlib.sha256((senha or '').encode('utf-8')).hexdigest()


def _fmt_data(valor):
    if valor in (None, ''):
        return ''
    if isinstance(valor, datetime):
        return valor.strftime('%Y-%m-%d %H:%M')
    if isinstance(valor, date):
        return valor.strftime('%Y-%m-%d')
    return str(valor)


def _parse_data(texto: str):
    """Aceita 'YYYY-MM-DD' ou vazio. Retorna date|None ou levanta ValueError."""
    texto = (texto or '').strip()
    if not texto:
        return None
    return datetime.strptime(texto, '%Y-%m-%d').date()


# ── DAO ─────────────────────────────────────────────────────────────────────
class UsersDAO:

    COLUNAS_BASE = [
        'id', 'username', 'role', 'current_tier', 'is_blocked',
        'license_expiry', 'balance_available', 'machine_id',
        'session_token', 'session_at', 'last_login',
    ]

    def listar(self, busca: str = ''):
        conn = _connect()
        try:
            cur = conn.cursor(dictionary=True)
            if busca:
                cur.execute(
                    f"SELECT {', '.join(self.COLUNAS_BASE)} FROM users "
                    "WHERE username LIKE %s OR id = %s "
                    "ORDER BY id DESC LIMIT 500",
                    (f'%{busca}%', busca if busca.isdigit() else 0),
                )
            else:
                cur.execute(
                    f"SELECT {', '.join(self.COLUNAS_BASE)} FROM users "
                    "ORDER BY id DESC LIMIT 500"
                )
            return cur.fetchall()
        finally:
            conn.close()

    def obter(self, user_id: int):
        conn = _connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"SELECT {', '.join(self.COLUNAS_BASE)} FROM users WHERE id = %s LIMIT 1",
                (user_id,),
            )
            return cur.fetchone()
        finally:
            conn.close()

    def criar(self, username, senha, role, tier, license_expiry, balance, is_blocked):
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password, role, current_tier, "
                "license_expiry, balance_available, is_blocked, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
                (username, _sha256(senha), role, tier,
                 license_expiry, float(balance or 0), int(bool(is_blocked))),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def atualizar(self, user_id, username, senha, role, tier,
                  license_expiry, balance, is_blocked):
        """Se `senha` for vazio, NAO altera a senha existente."""
        conn = _connect()
        try:
            cur = conn.cursor()
            if senha:
                cur.execute(
                    "UPDATE users SET username=%s, password=%s, role=%s, "
                    "current_tier=%s, license_expiry=%s, balance_available=%s, "
                    "is_blocked=%s WHERE id=%s",
                    (username, _sha256(senha), role, tier, license_expiry,
                     float(balance or 0), int(bool(is_blocked)), user_id),
                )
            else:
                cur.execute(
                    "UPDATE users SET username=%s, role=%s, current_tier=%s, "
                    "license_expiry=%s, balance_available=%s, is_blocked=%s "
                    "WHERE id=%s",
                    (username, role, tier, license_expiry,
                     float(balance or 0), int(bool(is_blocked)), user_id),
                )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def remover(self, user_id):
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def resetar_licenca(self, user_id):
        """Limpa o vinculo de dispositivo -> libera novo login.

        IMPORTANTE: o login (server.granasocial_db.autenticar) checa a coluna
        `hwid`. Por isso o reset precisa limpar `hwid` (e `hostname`) tambem,
        alem de `machine_id`/`session_token`/`session_at`. Limpar so o
        `machine_id` NAO desbloqueia o login.
        """
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET hwid=NULL, hostname=NULL, machine_id=NULL, "
                "session_token=NULL, session_at=NULL WHERE id=%s",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def estender_licenca(self, user_id, dias: int):
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT license_expiry FROM users WHERE id=%s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return 0
            atual = row[0]
            if isinstance(atual, datetime):
                atual = atual.date()
            if not atual or atual < date.today():
                atual = date.today()
            novo = atual + timedelta(days=int(dias))
            cur.execute(
                "UPDATE users SET license_expiry=%s WHERE id=%s",
                (novo, user_id),
            )
            conn.commit()
            return novo
        finally:
            conn.close()

    def alternar_bloqueio(self, user_id):
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET is_blocked = IF(is_blocked=1, 0, 1) "
                "WHERE id=%s",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


# ── Dialogo de edicao/criacao ───────────────────────────────────────────────
class UserDialog(tk.Toplevel):

    def __init__(self, master, titulo, dados=None):
        super().__init__(master)
        self.title(titulo)
        self.resizable(False, False)
        self.configure(padx=14, pady=10)
        self.transient(master)
        self.grab_set()

        self.resultado = None
        dados = dados or {}
        self._editando = bool(dados.get('id'))

        linha = 0

        ttk.Label(self, text='Username:').grid(row=linha, column=0, sticky='e', pady=4)
        self.e_user = ttk.Entry(self, width=30)
        self.e_user.insert(0, dados.get('username', '') or '')
        self.e_user.grid(row=linha, column=1, pady=4, sticky='w')
        linha += 1

        rotulo_senha = 'Nova senha (vazio = manter):' if self._editando else 'Senha:'
        ttk.Label(self, text=rotulo_senha).grid(row=linha, column=0, sticky='e', pady=4)
        self.e_senha = ttk.Entry(self, width=30, show='*')
        self.e_senha.grid(row=linha, column=1, pady=4, sticky='w')
        linha += 1

        ttk.Label(self, text='Role:').grid(row=linha, column=0, sticky='e', pady=4)
        self.cb_role = ttk.Combobox(
            self, width=27, state='readonly',
            values=['user', 'admin', 'manager'],
        )
        self.cb_role.set(dados.get('role', 'user') or 'user')
        self.cb_role.grid(row=linha, column=1, pady=4, sticky='w')
        linha += 1

        ttk.Label(self, text='Tier:').grid(row=linha, column=0, sticky='e', pady=4)
        self.cb_tier = ttk.Combobox(
            self, width=27, state='readonly',
            values=['bronze', 'silver', 'gold', 'platinum', 'diamond'],
        )
        self.cb_tier.set(dados.get('current_tier', 'bronze') or 'bronze')
        self.cb_tier.grid(row=linha, column=1, pady=4, sticky='w')
        linha += 1

        ttk.Label(self, text='Validade (YYYY-MM-DD):').grid(
            row=linha, column=0, sticky='e', pady=4)
        self.e_validade = ttk.Entry(self, width=30)
        self.e_validade.insert(0, _fmt_data(dados.get('license_expiry')))
        self.e_validade.grid(row=linha, column=1, pady=4, sticky='w')
        linha += 1

        ttk.Label(self, text='Saldo (coins):').grid(row=linha, column=0, sticky='e', pady=4)
        self.e_saldo = ttk.Entry(self, width=30)
        self.e_saldo.insert(0, str(dados.get('balance_available', 0) or 0))
        self.e_saldo.grid(row=linha, column=1, pady=4, sticky='w')
        linha += 1

        self.v_bloq = tk.BooleanVar(value=bool(dados.get('is_blocked')))
        ttk.Checkbutton(self, text='Conta bloqueada', variable=self.v_bloq).grid(
            row=linha, column=1, pady=4, sticky='w')
        linha += 1

        frm_btn = ttk.Frame(self)
        frm_btn.grid(row=linha, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(frm_btn, text='Salvar', command=self._salvar).pack(side='left', padx=6)
        ttk.Button(frm_btn, text='Cancelar', command=self.destroy).pack(side='left', padx=6)

        self.e_user.focus_set()
        self.bind('<Return>', lambda _e: self._salvar())
        self.bind('<Escape>', lambda _e: self.destroy())

    def _salvar(self):
        username = self.e_user.get().strip()
        senha = self.e_senha.get()
        if not username:
            messagebox.showwarning('Atencao', 'Informe o username.', parent=self)
            return
        if not self._editando and not senha:
            messagebox.showwarning('Atencao', 'Informe a senha.', parent=self)
            return
        try:
            validade = _parse_data(self.e_validade.get())
        except ValueError:
            messagebox.showerror(
                'Erro', 'Validade invalida. Use YYYY-MM-DD ou deixe vazio.',
                parent=self)
            return
        try:
            saldo = float((self.e_saldo.get() or '0').replace(',', '.'))
        except ValueError:
            messagebox.showerror('Erro', 'Saldo invalido.', parent=self)
            return

        self.resultado = {
            'username': username,
            'senha': senha,
            'role': self.cb_role.get() or 'user',
            'tier': self.cb_tier.get() or 'bronze',
            'license_expiry': validade,
            'balance': saldo,
            'is_blocked': self.v_bloq.get(),
        }
        self.destroy()


# ── Janela principal ────────────────────────────────────────────────────────
class AdminApp(tk.Tk):

    COLUNAS = [
        ('id',                'ID',         60),
        ('username',          'Usuario',   160),
        ('role',              'Role',       90),
        ('current_tier',      'Tier',       90),
        ('is_blocked',        'Bloq.',      55),
        ('license_expiry',    'Validade',  100),
        ('balance_available', 'Saldo',      80),
        ('machine_id',        'Machine ID', 180),
        ('last_login',        'Ultimo login', 140),
    ]

    def __init__(self):
        super().__init__()
        self.title('GS BM Creator - Admin de Usuarios')
        self.geometry('1180x600')
        self.minsize(950, 480)

        self.dao = UsersDAO()
        self._dados_cache = {}  # id -> dict completo

        self._montar_toolbar()
        self._montar_tabela()
        self._montar_status()

        self.after(80, self._carregar)

    # -------- UI building --------
    def _montar_toolbar(self):
        bar = ttk.Frame(self, padding=(8, 8, 8, 4))
        bar.pack(fill='x')

        ttk.Label(bar, text='Buscar:').pack(side='left')
        self.e_busca = ttk.Entry(bar, width=28)
        self.e_busca.pack(side='left', padx=(4, 6))
        self.e_busca.bind('<Return>', lambda _e: self._carregar())
        ttk.Button(bar, text='Filtrar', command=self._carregar).pack(side='left')
        ttk.Button(bar, text='Atualizar (F5)', command=self._carregar).pack(
            side='left', padx=(6, 0))

        sep = ttk.Separator(bar, orient='vertical')
        sep.pack(side='left', fill='y', padx=10)

        ttk.Button(bar, text='+ Novo usuario', command=self._novo).pack(side='left')
        ttk.Button(bar, text='Editar', command=self._editar).pack(side='left', padx=4)
        ttk.Button(bar, text='Remover', command=self._remover).pack(side='left')

        sep2 = ttk.Separator(bar, orient='vertical')
        sep2.pack(side='left', fill='y', padx=10)

        ttk.Button(
            bar, text='Resetar licenca/dispositivo',
            command=self._resetar_licenca,
        ).pack(side='left')
        ttk.Button(
            bar, text='Estender +30 dias',
            command=lambda: self._estender_licenca(30),
        ).pack(side='left', padx=4)
        ttk.Button(
            bar, text='Estender N dias...',
            command=self._estender_licenca_custom,
        ).pack(side='left')
        ttk.Button(
            bar, text='Bloquear / Desbloquear',
            command=self._alternar_bloqueio,
        ).pack(side='left', padx=(8, 0))

        self.bind('<F5>', lambda _e: self._carregar())
        self.bind('<Delete>', lambda _e: self._remover())

    def _montar_tabela(self):
        frm = ttk.Frame(self, padding=(8, 4, 8, 4))
        frm.pack(fill='both', expand=True)

        cols = [c[0] for c in self.COLUNAS]
        self.tree = ttk.Treeview(frm, columns=cols, show='headings', selectmode='browse')
        for chave, titulo, largura in self.COLUNAS:
            self.tree.heading(chave, text=titulo)
            anchor = 'e' if chave in ('id', 'balance_available') else 'w'
            self.tree.column(chave, width=largura, anchor=anchor, stretch=False)

        vsb = ttk.Scrollbar(frm, orient='vertical', command=self.tree.yview)
        hsb = ttk.Scrollbar(frm, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        self.tree.bind('<Double-1>', lambda _e: self._editar())

        self.tree.tag_configure('blocked', foreground='#a00000')
        self.tree.tag_configure('expirado', foreground='#a05a00')

    def _montar_status(self):
        self.status = tk.StringVar(value='Pronto.')
        bar = ttk.Frame(self, padding=(8, 4, 8, 6))
        bar.pack(fill='x')
        ttk.Label(bar, textvariable=self.status, anchor='w').pack(fill='x')

    # -------- helpers --------
    def _selecao(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Atencao', 'Selecione um usuario primeiro.')
            return None
        return int(sel[0])

    def _async(self, func, callback=None):
        """Executa `func()` em thread e dispara `callback(result, exc)` na UI."""
        def alvo():
            erro = None
            res = None
            try:
                res = func()
            except Exception as exc:  # noqa: BLE001
                erro = exc
            if callback:
                self.after(0, lambda: callback(res, erro))

        threading.Thread(target=alvo, daemon=True).start()

    # -------- acoes --------
    def _carregar(self):
        busca = self.e_busca.get().strip()
        self.status.set('Carregando...')
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._dados_cache.clear()

        def feito(rows, erro):
            if erro:
                self.status.set(f'Erro: {erro}')
                messagebox.showerror('Erro', f'Falha ao listar usuarios:\n{erro}')
                return
            hoje = date.today()
            for r in rows or []:
                uid = int(r['id'])
                self._dados_cache[uid] = r
                expiry = r.get('license_expiry')
                if isinstance(expiry, datetime):
                    expiry = expiry.date()
                tags = ()
                if int(r.get('is_blocked') or 0):
                    tags = ('blocked',)
                elif expiry and expiry < hoje:
                    tags = ('expirado',)

                self.tree.insert(
                    '', 'end', iid=str(uid),
                    values=(
                        uid,
                        r.get('username') or '',
                        r.get('role') or '',
                        r.get('current_tier') or '',
                        'sim' if int(r.get('is_blocked') or 0) else '-',
                        _fmt_data(expiry),
                        f"{float(r.get('balance_available') or 0):.2f}",
                        (r.get('machine_id') or '')[:24],
                        _fmt_data(r.get('last_login')),
                    ),
                    tags=tags,
                )
            self.status.set(f'{len(rows or [])} usuario(s) carregado(s).')

        self._async(lambda: self.dao.listar(busca), feito)

    def _novo(self):
        dlg = UserDialog(self, 'Novo usuario')
        self.wait_window(dlg)
        if not dlg.resultado:
            return
        d = dlg.resultado
        self.status.set('Criando usuario...')

        def feito(res, erro):
            if erro:
                messagebox.showerror('Erro', f'Falha ao criar usuario:\n{erro}')
                self.status.set('Erro.')
                return
            self.status.set(f'Usuario criado (id={res}).')
            self._carregar()

        self._async(
            lambda: self.dao.criar(
                d['username'], d['senha'], d['role'], d['tier'],
                d['license_expiry'], d['balance'], d['is_blocked'],
            ),
            feito,
        )

    def _editar(self):
        uid = self._selecao()
        if not uid:
            return
        dados = self._dados_cache.get(uid) or self.dao.obter(uid)
        if not dados:
            messagebox.showerror('Erro', 'Usuario nao encontrado.')
            return
        dlg = UserDialog(self, f'Editar usuario #{uid}', dados)
        self.wait_window(dlg)
        if not dlg.resultado:
            return
        d = dlg.resultado
        self.status.set('Atualizando usuario...')

        def feito(_res, erro):
            if erro:
                messagebox.showerror('Erro', f'Falha ao atualizar:\n{erro}')
                self.status.set('Erro.')
                return
            self.status.set('Usuario atualizado.')
            self._carregar()

        self._async(
            lambda: self.dao.atualizar(
                uid, d['username'], d['senha'], d['role'], d['tier'],
                d['license_expiry'], d['balance'], d['is_blocked'],
            ),
            feito,
        )

    def _remover(self):
        uid = self._selecao()
        if not uid:
            return
        nome = (self._dados_cache.get(uid) or {}).get('username', '')
        if not messagebox.askyesno(
            'Confirmar',
            f'Remover definitivamente o usuario #{uid} ({nome})?\n'
            'Esta acao nao pode ser desfeita.',
        ):
            return

        def feito(_res, erro):
            if erro:
                messagebox.showerror('Erro', f'Falha ao remover:\n{erro}')
                return
            self.status.set(f'Usuario {nome} removido.')
            self._carregar()

        self.status.set('Removendo...')
        self._async(lambda: self.dao.remover(uid), feito)

    def _resetar_licenca(self):
        uid = self._selecao()
        if not uid:
            return
        nome = (self._dados_cache.get(uid) or {}).get('username', '')
        if not messagebox.askyesno(
            'Confirmar',
            f'Resetar licenca/dispositivo do usuario {nome} (#{uid})?\n\n'
            'Isto vai LIMPAR o machine_id e o session_token, permitindo que '
            'ele faca login em outro computador.',
        ):
            return

        def feito(_res, erro):
            if erro:
                messagebox.showerror('Erro', f'Falha ao resetar licenca:\n{erro}')
                return
            self.status.set(f'Licenca/dispositivo de {nome} resetada.')
            messagebox.showinfo(
                'OK',
                f'Licenca resetada. {nome} ja pode logar em outro dispositivo.',
            )
            self._carregar()

        self.status.set('Resetando licenca...')
        self._async(lambda: self.dao.resetar_licenca(uid), feito)

    def _estender_licenca(self, dias: int):
        uid = self._selecao()
        if not uid:
            return

        def feito(novo, erro):
            if erro:
                messagebox.showerror('Erro', f'Falha ao estender:\n{erro}')
                return
            if not novo:
                messagebox.showwarning('Atencao', 'Usuario nao atualizado.')
                return
            self.status.set(f'Validade atualizada para {novo.isoformat()}.')
            self._carregar()

        self.status.set('Estendendo licenca...')
        self._async(lambda: self.dao.estender_licenca(uid, dias), feito)

    def _estender_licenca_custom(self):
        uid = self._selecao()
        if not uid:
            return
        dias = simpledialog.askinteger(
            'Estender licenca',
            'Quantos dias adicionar a validade?',
            minvalue=1, maxvalue=3650, parent=self,
        )
        if not dias:
            return
        self._estender_licenca(dias)

    def _alternar_bloqueio(self):
        uid = self._selecao()
        if not uid:
            return

        def feito(_res, erro):
            if erro:
                messagebox.showerror('Erro', f'Falha:\n{erro}')
                return
            self.status.set('Estado de bloqueio alternado.')
            self._carregar()

        self.status.set('Alternando bloqueio...')
        self._async(lambda: self.dao.alternar_bloqueio(uid), feito)


def main():
    app = AdminApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
