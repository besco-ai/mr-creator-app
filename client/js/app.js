/**
 * {{MARCA}} - JavaScript Principal (v4.0)
 * =============================================
 * Interface com suporte a IXBrowser + AdsPower,
 * Interface com suporte a IXBrowser + AdsPower,
 * autenticação no painel MySQL e importação via .TXT.
    status.textContent = 'Conectando ao painel...';
 */

// ============================================
// ESTADO DA APLICAÇÃO
// ============================================

// FLUXO ÚNICO do GS Creator (2026-10-05): ⚡ Pro Max DataCrazy Turbo. O seletor
// de fluxo só tem esta opção; o backend normaliza qualquer outro valor p/ ela.
const FLUXO_UNICO = 'full_completo_datacrazy_meta';

let perfisImportados = [];
let processando = false;
let intervaloProgresso = null;
let intervaloFila = null;
let verificandoFila = false;
let filaVisivel = false;

// Estado do dashboard de execução ao vivo
let termLog = [];                  // linhas do terminal central
let ultimaMsgPorPerfil = {};       // indice -> última mensagem exibida (detecta mudança)
let statusAnteriorPorPerfil = {};  // indice -> último status (detecta transições p/ glow)

// ============================================
// DASHBOARD DE EXECUÇÃO — HELPERS
// ============================================

function inicializarSimultaneos() {
    const sel = document.getElementById('simultaneos_select');
    if (sel) {
        try {
            let salvo = localStorage.getItem('gsbm_simultaneos');
            // máximo atual = 10: quem tinha 11–20 salvo passa a 10 (não volta p/ 1)
            if (salvo && parseInt(salvo, 10) > 10) salvo = '10';
            if (salvo && sel.querySelector(`option[value="${salvo}"]`)) sel.value = salvo;
        } catch (e) {}
        sel.addEventListener('change', function() {
            try { localStorage.setItem('gsbm_simultaneos', sel.value); } catch (e) {}
        });
    }
    const oc = document.getElementById('oculto_select');
    if (oc) {
        try {
            const salvo = localStorage.getItem('gsbm_oculto');
            if (salvo && oc.querySelector(`option[value="${salvo}"]`)) oc.value = salvo;
        } catch (e) {}
        oc.addEventListener('change', function() {
            try { localStorage.setItem('gsbm_oculto', oc.value); } catch (e) {}
        });
    }
    // Método de verificação de domínio (persiste a escolha na GUI).
    const mv = document.getElementById('metodo_verificacao_select');
    if (mv) {
        try {
            const salvo = localStorage.getItem('gsbm_metodo_verif');
            if (salvo && mv.querySelector(`option[value="${salvo}"]`)) mv.value = salvo;
        } catch (e) {}
    }
}

function obterSimultaneos() {
    const sel = document.getElementById('simultaneos_select');
    let n = sel ? parseInt(sel.value, 10) : 1;
    if (isNaN(n) || n < 1) n = 1;
    if (n > 10) n = 10;
    return n;
}

function obterOculto() {
    const sel = document.getElementById('oculto_select');
    return (sel && sel.value === 'sim') ? 'sim' : 'nao';
}

function flashBorda(tipo) {
    const el = document.getElementById('border_glow');
    if (!el) return;
    const cls = tipo === 'erro' ? 'flash-err' : 'flash-ok';
    el.classList.remove('flash-ok', 'flash-err');
    // força reflow para reiniciar a animação mesmo em flashes consecutivos
    void el.offsetWidth;
    el.classList.add(cls);
    setTimeout(() => el.classList.remove(cls), 950);
}

function pushTerminal(wk, msg, tipo) {
    if (!msg) return;
    const agora = new Date();
    const hh = String(agora.getHours()).padStart(2, '0');
    const mm = String(agora.getMinutes()).padStart(2, '0');
    const ss = String(agora.getSeconds()).padStart(2, '0');
    termLog.push({ time: `${hh}:${mm}:${ss}`, wk: wk, msg: msg, tipo: tipo || 'info' });
    if (termLog.length > 200) termLog = termLog.slice(-200);
    renderTerminal();
}

function renderTerminal() {
    const body = document.getElementById('exec_terminal_body');
    if (!body) return;
    const proximoDoFim = (body.scrollTop + body.clientHeight >= body.scrollHeight - 24);
    const frag = document.createDocumentFragment();
    body.innerHTML = '';
    termLog.forEach(function(l, idx) {
        const div = document.createElement('div');
        div.className = 'term-line' + (l.tipo === 'ok' ? ' t-ok' : l.tipo === 'erro' ? ' t-err' : '') +
            (idx === termLog.length - 1 ? ' t-new' : '');
        const wkTxt = l.wk ? `[w${l.wk}]` : '';
        div.innerHTML = `<span class="t-time">${l.time}</span>` +
            (wkTxt ? `<span class="t-wk">${wkTxt}</span>` : '') +
            `<span class="t-msg">${escapeHtml(l.msg)}</span>`;
        frag.appendChild(div);
    });
    body.appendChild(frag);
    if (proximoDoFim) body.scrollTop = body.scrollHeight;
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

function setCard(id, valor) {
    const el = document.getElementById(id);
    if (el && el.textContent !== String(valor)) el.textContent = String(valor);
}

function renderWorkers(itensProc) {
    const wrap = document.getElementById('exec_workers');
    if (!wrap) return;
    if (!itensProc || itensProc.length === 0) { wrap.innerHTML = ''; return; }
    wrap.innerHTML = '';
    itensProc.forEach(function(p) {
        const perfil = perfisImportados[p.indice] || {};
        const login = perfil.login || ('Perfil ' + (p.indice + 1));
        const tile = document.createElement('div');
        tile.className = 'worker-tile wt-proc';
        const msg = (p.mensagem || p.status || 'Processando');
        tile.innerHTML =
            `<div class="worker-tile-top">` +
                `<span class="worker-tile-spinner"></span>` +
                `<span class="worker-tile-id">w${p.indice + 1}</span>` +
                `<span class="worker-tile-login">${escapeHtml(login)}</span>` +
            `</div>` +
            `<div class="worker-tile-msg">${escapeHtml(msg)}</div>`;
        wrap.appendChild(tile);
    });
}

function resetDashboardExecucao() {
    termLog = [];
    ultimaMsgPorPerfil = {};
    statusAnteriorPorPerfil = {};
    renderTerminal();
    const wrap = document.getElementById('exec_workers');
    if (wrap) wrap.innerHTML = '';
    ['card_ok_num', 'card_erro_num', 'card_recorrida_num', 'card_proc_num', 'card_aguard_num'].forEach(id => {
        const el = document.getElementById(id); if (el) el.textContent = '0';
    });
    ['bar_ok', 'bar_erro'].forEach(id => { const el = document.getElementById(id); if (el) el.style.width = '0%'; });
}

// ============================================
// INICIALIZAÇÃO
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    setTimeout(inicializar, 500);
});

async function inicializar() {
    try {
        const config = await pywebview.api.carregar_configuracoes();
        if (config) {
            document.getElementById('nome_grupo').value = config.nome_grupo || 'Facebook Profiles';
            document.getElementById('proxy_select').value = config.proxy || 'nao';
            document.getElementById('utilizar_4g_select').value = config.utilizar_4g || 'nao';
            { const _ijs = document.getElementById('ip_janela_select'); if (_ijs) _ijs.value = config.ip_janela_horas || '6';
              const _ims = document.getElementById('ip_max_ip_select'); if (_ims) _ims.value = config.ip_max_por_ip || '10'; }
            atualizarTrocaIpUI();
            document.getElementById('lista_proxy').value = config.lista_proxy || '';
            document.getElementById('proxy_tipo').value = config.proxy_tipo || 'http';
            if (config.qtd_bm) document.getElementById('qtd_bm_select').value = config.qtd_bm;

            // Novos campos
            document.getElementById('browser_engine').value = config.browser_engine || 'ixbrowser';
            document.getElementById('adspower_token').value = config.adspower_token || '';
            document.getElementById('adspower_url').value = config.adspower_url || 'http://local.adspower.net:50325';
            aplicarConfigSms(config);

            // Fluxo ÚNICO (Pro Max DataCrazy Turbo) — qualquer valor salvo antigo é ignorado.
            document.getElementById('verificar_bm_select').value = FLUXO_UNICO;
            document.getElementById('tipo_empresa_select').value = config.tipo_empresa || 'mei';
            // Mostra os campos do Pro Max (tipo de empresa, SMS, recurso da WABA).
            atualizarVisibilidadeVerificacao();
            // Aplica o nível de acesso (Turbo só p/ Editor/Admin).
            aplicarNivelAcesso();
            if (config.auto_verificar) {
                const chk = document.getElementById('auto_verificar_check');
                if (chk) chk.checked = (config.auto_verificar === 'sim');
            }
            // Recurso da WABA: 'sim' (com texto) / 'nao' (formulário em branco). Padrão 'sim'.
            {
                const rsel = document.getElementById('recurso_texto_select');
                if (rsel) rsel.value = (config.recurso_com_texto === 'nao') ? 'nao' : 'sim';
            }

            // Login
            if (config.usuario) {
                document.getElementById('login_usuario').value = config.usuario;
                document.getElementById('config_usuario').value = config.usuario;
            }
            if (config.senha) {
                document.getElementById('login_senha').value = config.senha;
            }
            if (config.lembrar_acesso) {
                document.getElementById('lembrar_acesso').checked = config.lembrar_acesso === 'sim';
            }

            if (config.painel_conectado !== undefined) {
                atualizarContadorPerfis(config.painel_conectado);
            }
        }
    } catch (e) {
        console.log('Erro ao carregar configurações:', e);
    }

    atualizarVisibilidadeProxy();
    atualizarVisibilidadeAdsPower();
    atualizarVisibilidadeVerificacao();
    inicializarSimultaneos();
    verificarConexaoBrowser();
    configurarEventos();
}

// ============================================
// EVENT LISTENERS
// ============================================

function configurarEventos() {
    // Fechar / Minimizar
    document.getElementById('btn_fechar').addEventListener('click', () => pywebview.api.fechar());
    document.getElementById('btn_minimizar').addEventListener('click', () => pywebview.api.minimizar());

    // Proxy toggle
    document.getElementById('proxy_select').addEventListener('change', atualizarVisibilidadeProxy);

    // Proxy import
    document.getElementById('btn_importar_proxy').addEventListener('click', () => document.getElementById('input_proxy_arquivo').click());
    document.getElementById('input_proxy_arquivo').addEventListener('change', function(e) {
        if (e.target.files.length > 0) importarProxyTXT(e.target.files[0]);
        this.value = '';
    });
    document.getElementById('lista_proxy').addEventListener('input', atualizarContagemProxy);

    // Browser engine toggle
    document.getElementById('browser_engine').addEventListener('change', function() {
        atualizarVisibilidadeAdsPower();
        verificarConexaoBrowser();
    });

    // Verificação BM toggle
    document.getElementById('verificar_bm_select').addEventListener('change', atualizarVisibilidadeVerificacao);

    // ── Modal dos provedores de SMS ───────────────────────────────────────────
    // Trocar o provedor tem de refletir na hora no campo oculto e na fila; era
    // essa dessincronia que mandava a chave de um provedor para o outro.
    { const _p = document.getElementById('sms_provedor');
      if (_p) _p.addEventListener('change', sincronizarSms); }
    SMS_ORDEM.forEach(p => {
        const el = document.getElementById('sms_token_' + p);
        if (el) el.addEventListener('input', sincronizarSms);
    });
    { const b = document.getElementById('btn_provedores_sms'); if (b) b.addEventListener('click', abrirModalSms); }
    { const b = document.getElementById('btn_fechar_modal_sms'); if (b) b.addEventListener('click', fecharModalSms); }
    { const b = document.getElementById('btn_salvar_sms'); if (b) b.addEventListener('click', salvarModalSms); }
    { const b = document.getElementById('btn_testar_sms'); if (b) b.addEventListener('click', testarTokensSms); }
    { const m = document.getElementById('modal_sms');
      if (m) m.addEventListener('click', e => { if (e.target === m) fecharModalSms(); }); }
    document.addEventListener('keydown', e => {
        const m = document.getElementById('modal_sms');
        if (e.key === 'Escape' && m && m.style.display !== 'none') fecharModalSms();
    });

    // Auto-verificar checkbox
    const autoChk = document.getElementById('auto_verificar_check');
    if (autoChk) {
        autoChk.addEventListener('change', async function() {
            const val = this.checked ? 'sim' : 'nao';
            try { await pywebview.api.definir_auto_verificar(val); } catch(e) {}
            if (this.checked) {
                mostrarSucesso('Auto-verificar ativado — o software verificará quando as BMs atingirem 2h');
            }
        });
    }

    // Recurso da WABA: COM texto (padrão) x EM BRANCO
    const recursoSel = document.getElementById('recurso_texto_select');
    if (recursoSel) {
        recursoSel.addEventListener('change', async function() {
            const val = this.value === 'nao' ? 'nao' : 'sim';
            try { await pywebview.api.definir_recurso_com_texto(val); } catch(e) {}
            mostrarSucesso(val === 'sim'
                ? 'Recurso da WABA: enviará COM texto de contestação'
                : 'Recurso da WABA: enviará o formulário EM BRANCO (sem texto)');
        });
    }

    // Importar arquivo .txt
    document.getElementById('btn_importar').addEventListener('click', () => document.getElementById('input_arquivo').click());
    document.getElementById('input_arquivo').addEventListener('change', function(e) {
        if (e.target.files.length > 0) lerArquivoTXT(e.target.files[0]);
    });

    // Iniciar / Cancelar
    document.getElementById('btn_iniciar').addEventListener('click', iniciarProcessamento);
    document.getElementById('btn_cancelar').addEventListener('click', cancelarProcessamento);
    { const _bp = document.getElementById('btn_pausar'); if (_bp) _bp.addEventListener('click', pausarProcessamento);
      const _bc = document.getElementById('btn_continuar'); if (_bc) _bc.addEventListener('click', continuarProcessamento); }

    // Exportar falhas (.txt) — bloqueios/login e BM incompleta
    { const _el = document.getElementById('btn_export_login'); if (_el) _el.addEventListener('click', () => exportarFalhas('login'));
      const _ef = document.getElementById('btn_export_fluxo'); if (_ef) _ef.addEventListener('click', () => exportarFalhas('fluxo')); }

    // Login
    document.getElementById('btn_login').addEventListener('click', realizarLogin);
    document.getElementById('login_senha').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') realizarLogin();
    });
    document.getElementById('login_usuario').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') document.getElementById('login_senha').focus();
    });

    // Fila de Verificação
    document.getElementById('btn_toggle_fila').addEventListener('click', toggleFilaVerificacao);
    document.getElementById('btn_verificar_fila').addEventListener('click', iniciarVerificacaoFila);
    document.getElementById('btn_cancelar_verificacao').addEventListener('click', cancelarVerificacaoFila);
    document.getElementById('btn_limpar_fila').addEventListener('click', limparFilaVerificadas);
    document.getElementById('btn_retentar_fila').addEventListener('click', retentarErrosFila);
    // (Removidos os recursos "Reaproveitar não concluídos" e "Monitor de Análise"
    //  da GUI — substituídos pelos botões de EXPORTAR falhas + reimportar.)

    // Importar Comprados (do painel)
    const btnComprados = document.getElementById('btn_importar_comprados');
    if (btnComprados) btnComprados.addEventListener('click', abrirModalComprados);
    const btnFecharModal = document.getElementById('btn_fechar_modal_comprados');
    if (btnFecharModal) btnFecharModal.addEventListener('click', fecharModalComprados);
    const btnRecarregar = document.getElementById('btn_recarregar_comprados');
    if (btnRecarregar) btnRecarregar.addEventListener('click', carregarComprasNoModal);
    const btnConfirmar = document.getElementById('btn_confirmar_importar_comprados');
    if (btnConfirmar) btnConfirmar.addEventListener('click', confirmarImportarComprados);

    // Reutilizar Perfis Logados (cria 1 BM nova em cada perfil do grupo)
    const btnReutilizar = document.getElementById('btn_reutilizar_logados');
    if (btnReutilizar) btnReutilizar.addEventListener('click', abrirModalReutilizar);
    const btnFecharReutilizar = document.getElementById('btn_fechar_modal_reutilizar');
    if (btnFecharReutilizar) btnFecharReutilizar.addEventListener('click', fecharModalReutilizar);
    const btnRecarregarGrupos = document.getElementById('btn_recarregar_grupos_reutilizar');
    if (btnRecarregarGrupos) btnRecarregarGrupos.addEventListener('click', carregarGruposReutilizar);
    const btnIniciarReutilizar = document.getElementById('btn_iniciar_reutilizar');
    if (btnIniciarReutilizar) btnIniciarReutilizar.addEventListener('click', iniciarReutilizarLogados);

    // Fila desativada a pedido do usuário
    // atualizarFilaVerificacao();
    // intervaloFila = setInterval(atualizarFilaVerificacao, 5000);
}

// ============================================
// LOGIN
// ============================================

async function realizarLogin() {
    const usuario = document.getElementById('login_usuario').value.trim();
    const senha = document.getElementById('login_senha').value.trim();
    const lembrarAcesso = document.getElementById('lembrar_acesso').checked ? 'sim' : 'nao';
    const status = document.getElementById('login_status');
    const btn = document.getElementById('btn_login');

    if (!usuario || !senha) {
        status.textContent = 'Preencha todos os campos';
        status.style.color = '#FF3366';
        return;
    }

    status.textContent = 'Verificando licença...';
    status.style.color = '#00D9FF';
    btn.disabled = true;

    try {
        const resultado = await pywebview.api.autenticar_usuario(usuario, senha, lembrarAcesso);

        if (resultado && typeof resultado === 'object' && resultado.sucesso) {
            status.textContent = 'Acesso autorizado!';
            status.style.color = '#00FF88';

            if (resultado.configs) {
                document.getElementById('nome_grupo').value = resultado.configs.nome_grupo || 'Facebook Profiles';
                document.getElementById('proxy_select').value = resultado.configs.proxy || 'nao';
                document.getElementById('utilizar_4g_select').value = resultado.configs.utilizar_4g || 'nao';
                atualizarTrocaIpUI();
                document.getElementById('lista_proxy').value = resultado.configs.lista_proxy || '';
                document.getElementById('proxy_tipo').value = resultado.configs.proxy_tipo || 'http';
                document.getElementById('browser_engine').value = resultado.configs.browser_engine || 'ixbrowser';
                document.getElementById('adspower_token').value = resultado.configs.adspower_token || '';
                document.getElementById('adspower_url').value = resultado.configs.adspower_url || 'http://local.adspower.net:50325';
                aplicarConfigSms(resultado.configs);
                if (resultado.configs.qtd_bm) document.getElementById('qtd_bm_select').value = resultado.configs.qtd_bm;

                // Fluxo ÚNICO (Pro Max DataCrazy Turbo).
                document.getElementById('verificar_bm_select').value = FLUXO_UNICO;
                document.getElementById('tipo_empresa_select').value = resultado.configs.tipo_empresa || 'mei';

                atualizarVisibilidadeProxy();
                atualizarVisibilidadeAdsPower();
                atualizarVisibilidadeVerificacao();
                // Aplica o nível de acesso (Turbo só p/ Editor/Admin).
                aplicarNivelAcesso();

                if (resultado.configs.painel_conectado !== undefined) {
                    atualizarContadorPerfis(resultado.configs.painel_conectado);
                }
            }

            document.getElementById('config_usuario').value = usuario;
            setTimeout(() => {
                document.getElementById('tela_login').style.display = 'none';
                verificarConexaoBrowser();
            }, 800);
            return;
        }

        const mensagem = (resultado && typeof resultado === 'object' && resultado.mensagem)
            ? resultado.mensagem
            : (typeof resultado === 'string' ? resultado : 'Erro de autenticação');

        status.textContent = mensagem;
        status.style.color = '#FF3366';
        btn.disabled = false;
    } catch (e) {
        console.error('Falha no login:', e);
        status.textContent = 'Erro ao conectar ao servidor';
        status.style.color = '#FF3366';
        btn.disabled = false;
    }
}

// ============================================
// PROXY / ADSPOWER VISIBILIDADE
// ============================================

function atualizarTrocaIpUI() {
    // 4G LIGADO  -> troca automática (cota por IP + rate-limit); mostra hint e os campos
    //               de janela/cota (só fazem sentido com 4G).
    // 4G DESLIGADO -> o sistema NÃO troca o IP: mostra o aviso de "troca manual/VPN" e
    //               esconde os campos de janela/cota (irrelevantes sem 4G).
    const usa4g = ((document.getElementById('utilizar_4g_select') || {}).value === 'sim');
    const hint = document.getElementById('ip_4g_hint');
    const hintManual = document.getElementById('ip_manual_hint');
    const janelaItem = document.getElementById('ip_janela_item');
    const maxItem = document.getElementById('ip_max_item');
    if (hint) hint.style.display = usa4g ? '' : 'none';
    if (hintManual) hintManual.style.display = usa4g ? 'none' : '';
    if (janelaItem) janelaItem.style.display = usa4g ? '' : 'none';
    if (maxItem) maxItem.style.display = usa4g ? '' : 'none';
}

function atualizarVisibilidadeProxy() {
    const proxyAtivo = document.getElementById('proxy_select').value === 'sim';
    document.querySelectorAll('.proxy-container').forEach(el => {
        el.classList.toggle('visivel', proxyAtivo);
    });
    if (proxyAtivo) atualizarContagemProxy();
}

function importarProxyTXT(arquivo) {
    const reader = new FileReader();
    reader.onload = function(e) {
        const conteudo = e.target.result.trim();
        if (!conteudo) return;

        const textarea = document.getElementById('lista_proxy');
        const linhas = conteudo.split('\n').map(l => l.trim()).filter(l => l.length > 0);

        // Se já está no formato IP:Porta:User:Pass, usar diretamente
        textarea.value = linhas.join('\n');
        atualizarContagemProxy();

        // Auto-ativar proxy se estava desativado
        const proxySelect = document.getElementById('proxy_select');
        if (proxySelect.value === 'nao') {
            proxySelect.value = 'sim';
            atualizarVisibilidadeProxy();
        }

        mostrarSucesso(`${linhas.length} proxy(s) importado(s) com sucesso`);
    };
    reader.readAsText(arquivo);
}

function atualizarContagemProxy() {
    const textarea = document.getElementById('lista_proxy');
    const el = document.getElementById('proxy_contagem');
    if (!el) return;

    const texto = textarea.value.trim();
    if (!texto) {
        el.textContent = '';
        return;
    }

    // Contar proxies (linhas não-vazias no formato compacto, ou blocos no formato antigo)
    const linhas = texto.split('\n').filter(l => l.trim().length > 0);
    const primeiraLinha = linhas[0] || '';
    let count = 0;

    if (primeiraLinha.includes(':')) {
        // Formato compacto: cada linha é um proxy
        count = linhas.length;
    } else {
        // Formato bloco: separados por linha em branco
        count = texto.split('\n\n').filter(b => b.trim().length > 0).length;
    }

    const perfisTotal = perfisImportados.length;
    let info = `${count} proxy(s) carregado(s)`;

    if (perfisTotal > 0) {
        if (count >= perfisTotal) {
            info += ` — 1:1 para ${perfisTotal} perfil(is) ✓`;
        } else if (count > 1) {
            const ratio = Math.ceil(perfisTotal / count);
            info += ` — ~${ratio} perfil(is) por proxy`;
        } else if (count === 1) {
            info += ` — mesmo proxy para todos os ${perfisTotal} perfil(is)`;
        }
    }

    el.textContent = info;
}

function atualizarVisibilidadeAdsPower() {
    const engine = document.getElementById('browser_engine').value;
    const tokenContainer = document.getElementById('adspower_token_container');
    const urlContainer = document.getElementById('adspower_url_container');
    if (tokenContainer) {
        tokenContainer.style.display = engine === 'adspower' ? 'flex' : 'none';
    }
    if (urlContainer) {
        urlContainer.style.display = engine === 'adspower' ? 'flex' : 'none';
    }
}

function atualizarVisibilidadeVerificacao() {
    const container = document.getElementById('tipo_empresa_container');
    const filaCard = document.getElementById('fila_verificacao_card');

    // Turbo é Pro Max: mostra tipo de empresa, SMS e recurso da WABA.
    // IMPORTANTE: usar 'flex' (não ''), pois a classe .verificacao-field tem
    // 'display:none' no CSS e venceria o .config-item ao limpar o inline style.
    if (container) container.style.display = 'flex';
    if (filaCard) filaCard.style.display = 'none';

    // Provedores de SMS: um botão só, que abre o modal com as chaves, o provedor
    // preferido e o teto de preço.
    const smsCont = document.getElementById('sms_config_container');
    if (smsCont) smsCont.style.display = 'flex';
    sincronizarSms();

    // ♻️ Recurso da WABA (COM texto x EM BRANCO): uma WABA pode desabilitar e
    // disparar o recurso na Meta.
    const recursoCont = document.getElementById('recurso_texto_container');
    if (recursoCont) recursoCont.style.display = 'flex';
}

// ============================================
// PROVEDORES DE SMS (modal único)
// ============================================
// Cada provedor tem A SUA chave, salva com a etiqueta dele. O antigo campo
// "Token SMS" (id sms24h_token) virou um input HIDDEN preenchido a partir do
// provedor escolhido — antes ele era digitado à mão e NÃO trocava junto com o
// seletor, então a chave do Tiger acabava indo para o Vak (BAD_KEY / "usuário
// não encontrado") e derrubava as abas. Agora não há como divergir.
const SMS_PROVEDORES = {
    smsbower:{ nome: 'SMSBower',    painel: 'smsbower.app/cabinet/profile' },
    tiger:   { nome: 'Tiger SMS',   painel: 'tiger-sms.com/pt/api' },
    vak:     { nome: 'Vak-SMS',     painel: 'vak-sms.com/api' },
    grizzly: { nome: 'Grizzly SMS', painel: 'grizzlysms.com/docs' },
    sms24h:  { nome: 'SMS24h',      painel: 'sms24h.org/api' },
};
// Ordem de exibição/varredura. SMSBower 1º: número BR REAL no serviço 'fb' Gold
// (~US$0,04) que ENTREGA o código da BM — comprovado 2026-08-12; sms24h por último (caro).
const SMS_ORDEM = ['smsbower', 'tiger', 'vak', 'grizzly', 'sms24h'];
// Provedores cuja chave o usuário APAGOU no modal. O backend ignora campo em
// branco de propósito (um salvar com a tela vazia já zerou os tokens uma vez);
// o '-' é o combinado para remover de verdade. Só entra aqui quem TINHA chave
// e ficou em branco — assim uma tela que não carregou nunca apaga nada.
let _smsRemovidos = new Set();
let _smsSalvos = {};

function smsToken(prov) {
    const el = document.getElementById('sms_token_' + prov);
    return el ? (el.value || '').trim() : '';
}

/* Ordem real em que os provedores serão tentados — mesma regra do backend
   (montar_fila_provedores): o escolhido primeiro, o sms24h sempre por último
   por ser ~20x mais caro, e quem está sem chave nem entra. */
function smsFila() {
    const sel = document.getElementById('sms_provedor');
    const escolhido = (sel && sel.value) || 'sms24h';
    const demais = SMS_ORDEM.filter(p => p !== escolhido && p !== 'sms24h');
    if (escolhido !== 'sms24h') demais.push('sms24h');
    return [escolhido].concat(demais).filter(p => smsToken(p));
}

/* Carrega as chaves salvas no modal e migra quem só tinha o campo antigo. */
function aplicarConfigSms(cfg) {
    cfg = cfg || {};
    SMS_ORDEM.forEach(p => {
        const el = document.getElementById('sms_token_' + p);
        if (el) el.value = cfg['sms_token_' + p] || '';
    });
    const sel = document.getElementById('sms_provedor');
    if (sel) sel.value = cfg.sms_provedor || 'sms24h';
    const pm = document.getElementById('sms_preco_max');
    if (pm) pm.value = cfg.sms_preco_max || '';

    // MIGRAÇÃO de quem vem da tela antiga: o "Token SMS" solto pertence ao
    // provedor que estava selecionado — grava na caixa dele se estiver vazia.
    const antigo = (cfg.sms24h_token || '').trim();
    const prov = (sel && sel.value) || 'sms24h';
    if (antigo && !smsToken(prov)) {
        const el = document.getElementById('sms_token_' + prov);
        if (el) el.value = antigo;
    }
    _smsRemovidos = new Set();
    _smsSalvos = {};
    SMS_ORDEM.forEach(p => { _smsSalvos[p] = smsToken(p); });
    sincronizarSms();
}

/* Espelha a chave do provedor escolhido no campo oculto e repinta os resumos. */
function sincronizarSms() {
    const sel = document.getElementById('sms_provedor');
    const prov = (sel && sel.value) || 'sms24h';
    const oculto = document.getElementById('sms24h_token');
    if (oculto) oculto.value = smsToken(prov);

    const salvos = SMS_ORDEM.filter(p => smsToken(p));
    const btn = document.getElementById('btn_provedores_sms');
    const resumo = document.getElementById('sms_resumo');
    const sub = document.getElementById('sms_resumo_sub');
    if (btn && resumo && sub) {
        if (salvos.length) {
            btn.classList.add('tem');
            resumo.textContent = `${salvos.length} provedor(es) · usando ${SMS_PROVEDORES[prov].nome}`;
            sub.textContent = salvos.map(p => SMS_PROVEDORES[p].nome).join(' · ');
        } else {
            btn.classList.remove('tem');
            resumo.textContent = 'Configurar provedores';
            sub.textContent = 'clique para colar as API KEYs';
        }
    }

    const fila = smsFila();
    const prev = document.getElementById('sms_fila_preview');
    if (prev) {
        if (!fila.length) {
            prev.textContent = 'Nenhuma chave preenchida — o Pro Max não consegue comprar o número.';
        } else {
            const nomes = fila.map(p => SMS_PROVEDORES[p].nome).join(' → ');
            const cauda = fila.length > 1 ? ' — troca de provedor quando o SMS não chega.'
                                          : ' — só este tem chave; sem para onde trocar.';
            prev.textContent = (smsToken(prov) ? '' : `⚠ ${SMS_PROVEDORES[prov].nome} está sem chave. `)
                             + 'Fila de compra: ' + nomes + cauda;
        }
    }
}

function abrirModalSms() {
    const m = document.getElementById('modal_sms');
    if (!m) return;
    const msg = document.getElementById('sms_modal_msg');
    if (msg) { msg.textContent = ''; msg.className = 'sms-msg'; }
    sincronizarSms();
    m.style.display = 'flex';
}

function fecharModalSms() {
    const m = document.getElementById('modal_sms');
    if (m) m.style.display = 'none';
}

async function salvarModalSms() {
    // Chave que EXISTIA e foi apagada = remoção explícita (o backend só apaga
    // com '-'). Campo que já estava vazio continua vazio, sem mandar nada.
    SMS_ORDEM.forEach(p => {
        if (!smsToken(p) && _smsSalvos[p]) _smsRemovidos.add(p);
        else _smsRemovidos.delete(p);
    });
    sincronizarSms();
    const msg = document.getElementById('sms_modal_msg');
    try {
        await salvarConfiguracoesAtuais();
        _smsRemovidos = new Set();
        SMS_ORDEM.forEach(p => { _smsSalvos[p] = smsToken(p); });
        const prov = (document.getElementById('sms_provedor') || {}).value || 'sms24h';
        if (msg) {
            if (!smsToken(prov)) {
                // Salvou, mas o run vai barrar: o preferido é quem compra o 1º número.
                msg.className = 'sms-msg err';
                msg.textContent = `⚠ Salvo, mas o provedor preferido (${SMS_PROVEDORES[prov].nome}) `
                                + 'está sem chave — escolha outro ou cole a API KEY dele.';
                return;
            }
            msg.className = 'sms-msg ok';
            msg.textContent = '✔ Provedores salvos.';
        }
        setTimeout(fecharModalSms, 600);
    } catch (e) {
        if (msg) { msg.className = 'sms-msg err'; msg.textContent = 'Erro ao salvar: ' + e; }
    }
}

/* Consulta o saldo de cada chave preenchida — separa "chave errada" de "sem
   saldo" antes de o run começar, que é quando isso custa perfil. */
async function testarTokensSms() {
    const msg = document.getElementById('sms_modal_msg');
    const tokens = {};
    SMS_ORDEM.forEach(p => { if (smsToken(p)) tokens[p] = smsToken(p); });
    if (!Object.keys(tokens).length) {
        if (msg) { msg.className = 'sms-msg err'; msg.textContent = '⚠ Cole ao menos uma API KEY.'; }
        return;
    }
    SMS_ORDEM.forEach(p => {
        const st = document.getElementById('sms_status_' + p);
        if (st) { st.className = 'sms-status'; st.textContent = tokens[p] ? 'consultando…' : ''; }
    });
    if (msg) { msg.className = 'sms-msg'; msg.textContent = 'Consultando os provedores…'; }
    try {
        const r = await pywebview.api.testar_tokens_sms(tokens);
        const res = (r && r.resultados) || {};
        SMS_ORDEM.forEach(p => {
            const st = document.getElementById('sms_status_' + p);
            if (!st || !tokens[p]) return;
            // Provedor sem entrada na resposta não pode ficar em "consultando…"
            // para sempre — isso lê como "ainda testando" e não é.
            const r1 = res[p] || { ok: false, texto: 'sem resposta' };
            st.className = 'sms-status ' + (r1.ok ? 'ok' : 'err');
            st.textContent = r1.texto || '';
        });
        if (msg) { msg.className = 'sms-msg'; msg.textContent = (r && r.mensagem) || ''; }
    } catch (e) {
        if (msg) { msg.className = 'sms-msg err'; msg.textContent = 'Falha ao consultar: ' + e; }
    }
}

/* Lê a tela inteira e persiste no backend. Usado pelo botão INICIAR e pelo
   modal de provedores — salvar as chaves não pode depender de iniciar um run. */
async function salvarConfiguracoesAtuais() {
    const v = id => (document.getElementById(id) || {}).value || '';
    const chk = id => { const e = document.getElementById(id); return (e && e.checked) ? 'sim' : 'nao'; };
    const prov = v('sms_provedor') || 'sms24h';
    // '-' apaga de verdade; campo vazio o backend PRESERVA de propósito (um
    // salvar com a tela em branco já zerou os tokens de todo mundo uma vez).
    const tk = p => (_smsRemovidos.has(p) ? '-' : smsToken(p));
    return pywebview.api.salvar_configuracoes(
        v('nome_grupo') || 'Facebook Profiles',
        v('proxy_select'), v('utilizar_4g_select'), v('lista_proxy'), v('proxy_tipo'),
        v('login_usuario'), v('login_senha'), chk('lembrar_acesso'),
        parseInt(v('qtd_bm_select')) || 1,
        v('browser_engine'), v('adspower_token'), v('captcha_token'), v('adspower_url'),
        FLUXO_UNICO, v('tipo_empresa_select'), chk('auto_verificar_check'),
        '', '',   // datacrazy_email/senha: o Turbo não usa o CRM (contrato posicional mantido)
        smsToken(prov), prov,
        tk('sms24h'), tk('grizzly'), tk('tiger'), tk('vak'), v('sms_preco_max'),
        tk('smsbower'),
        v('ip_janela_select') || '6', v('ip_max_ip_select') || '10'
    );
}

// Controle de acesso por NÍVEL: o Pro Max DataCrazy Turbo (único fluxo) é exclusivo
// de usuários 'admin'/'editor' — o backend também bloqueia server-side. Aqui só
// guardamos a permissão p/ avisar antes de iniciar. Chamado no carregamento e após o login.
let _podePlanoGupshup = false;   // nome mantido: é o campo `pode_planos_gupshup` da API do painel
async function aplicarNivelAcesso() {
    try {
        const res = await pywebview.api.obter_nivel_acesso();
        _podePlanoGupshup = !!(res && res.pode_planos_gupshup);
        const sel = document.getElementById('verificar_bm_select');
        if (sel) sel.title = _podePlanoGupshup ? '' : 'Exclusivo para usuários Editor/Admin';
    } catch (e) {
        // Em caso de erro, por segurança assume sem permissão (o backend decide).
        _podePlanoGupshup = false;
    }
}

// ============================================
// VERIFICAR CONEXÃO BROWSER
// ============================================

async function verificarConexaoBrowser() {
    const badge = document.getElementById('status_ix');
    const textEl = document.getElementById('status_ix_text');
    const engine = document.getElementById('browser_engine').value;
    const engineName = engine === 'adspower' ? 'AdsPower' : 'IXBrowser';

    try {
        // Configurar engine + URL + token antes de verificar
        if (engine === 'adspower') {
            const adspowerToken = document.getElementById('adspower_token').value;
            const adspowerUrl = document.getElementById('adspower_url').value;
            await pywebview.api.definir_browser_engine(engine, adspowerUrl, adspowerToken);
        } else {
            await pywebview.api.definir_browser_engine(engine, '', '');
        }

        const resultado = await pywebview.api.verificar_browser();
        if (resultado && resultado.conectado) {
            textEl.textContent = `${engineName}: Online`;
            badge.className = 'status-badge conectado';
            badge.title = resultado.mensagem || '';
        } else {
            const msg = (resultado && resultado.mensagem) || 'Offline';
            // Mostrar mensagem curta no badge, mensagem completa no tooltip
            if (msg.toLowerCase().includes('api key')) {
                textEl.textContent = `${engineName}: API Key`;
                badge.className = 'status-badge desconectado';
            } else {
                textEl.textContent = `${engineName}: Offline`;
                badge.className = 'status-badge desconectado';
            }
            badge.title = msg;
        }
    } catch (e) {
        textEl.textContent = `${engineName}: Offline`;
        badge.className = 'status-badge desconectado';
        badge.title = e.message || '';
    }
}

// ============================================
// PERFIS DISPONÍVEIS
// ============================================

function atualizarContadorPerfis(total) {
    const el = document.getElementById('perfis_count');
    if (el) {
        const conectado = total === true || total === 'true' || total === 'ON' || Number(total) > 0;
        el.textContent = conectado ? 'ON' : 'OFF';
        const badge = document.getElementById('perfis_badge');
        if (badge) {
            badge.classList.toggle('has-profiles', conectado);
        }
        if (conectado) atualizarSaldoCoins();
    }
}

async function atualizarSaldoCoins() {
    // Mostra o saldo de coins — a moeda de USO da ferramenta (cada método/plano
    // consome coins: 1/2/3/3/5). O token do site é cobrado à parte.
    // Unidade: "coin" para 1, "coins" para 2 ou mais.
    try {
        const res = await pywebview.api.obter_saldo_coins_painel();
        const badge = document.getElementById('tokens_badge');
        const valEl = document.getElementById('tokens_valor');
        const unidadeEl = document.getElementById('tokens_unidade');
        if (!badge || !valEl) return;
        if (res && res.sucesso) {
            const coinsNum = parseFloat(res.coins || 0) || 0;
            // Inteiro quando for valor cheio; senão 1 casa decimal.
            const coinsTxt = Number.isInteger(coinsNum) ? String(coinsNum) : coinsNum.toFixed(1);
            const unidade = (coinsNum === 1) ? 'coin' : 'coins';
            valEl.textContent = coinsTxt;
            if (unidadeEl) unidadeEl.textContent = unidade;
            badge.style.display = '';
            badge.title = `Saldo de coins: ${coinsTxt} — moeda de uso da ferramenta `
                + `(Pro Max DataCrazy Turbo: 2,5 coins por BM enviada p/ análise)`;
            badge.classList.toggle('tokens-low', coinsNum < 1);
        } else {
            badge.style.display = 'none';
        }
    } catch(e) {
        // silencioso
    }
}

// ============================================
// MODAL: IMPORTAR PERFIS COMPRADOS (do painel)
// ============================================

let comprasCache = [];

async function abrirModalComprados() {
    const modal = document.getElementById('modal_comprados');
    if (!modal) return;
    modal.style.display = 'flex';
    await carregarComprasNoModal();
}

function fecharModalComprados() {
    const modal = document.getElementById('modal_comprados');
    if (modal) modal.style.display = 'none';
}

async function carregarComprasNoModal() {
    const info = document.getElementById('modal_comprados_info');
    const lista = document.getElementById('modal_comprados_lista');
    const btnConfirmar = document.getElementById('btn_confirmar_importar_comprados');
    if (!info || !lista) return;

    info.textContent = 'Carregando compras...';
    lista.innerHTML = '';
    btnConfirmar.disabled = true;
    comprasCache = [];

    try {
        const res = await pywebview.api.listar_compras_disponiveis_api();
        if (!res || !res.sucesso) {
            info.textContent = (res && res.mensagem) || 'Falha ao carregar compras.';
            return;
        }
        comprasCache = res.compras || [];
        const disponiveis = comprasCache.filter(c => (c.disponiveis || 0) > 0);

        if (disponiveis.length === 0) {
            info.textContent = 'Você não tem perfis comprados disponíveis para importar.';
            return;
        }

        info.textContent = `${disponiveis.length} compra(s) com perfis disponíveis. Defina quantos importar de cada.`;
        disponiveis.forEach(c => lista.appendChild(criarLinhaCompra(c)));
        atualizarResumoModalComprados();
    } catch (e) {
        info.textContent = 'Erro ao consultar compras: ' + (e.message || e);
    }
}

function criarLinhaCompra(compra) {
    const row = document.createElement('div');
    row.className = 'modal-compra-row';
    row.dataset.compraId = String(compra.compra_id);
    row.dataset.disponiveis = String(compra.disponiveis);

    const txt = document.createElement('div');
    const titulo = document.createElement('div');
    titulo.className = 'modal-compra-titulo';
    titulo.textContent = compra.produto_nome || `Compra #${compra.compra_id}`;
    const meta = document.createElement('div');
    meta.className = 'modal-compra-meta';
    meta.textContent = `Compra #${compra.compra_id} • ${compra.criado_em || ''}`;
    txt.appendChild(titulo);
    txt.appendChild(meta);

    const disp = document.createElement('div');
    disp.className = 'modal-compra-disp';
    disp.textContent = `${compra.disponiveis} disp.`;

    const input = document.createElement('input');
    input.type = 'number';
    input.className = 'modal-compra-qtd';
    input.min = '0';
    input.max = String(compra.disponiveis);
    input.value = '0';
    input.addEventListener('input', () => {
        let n = parseInt(input.value, 10);
        if (isNaN(n) || n < 0) n = 0;
        if (n > compra.disponiveis) n = compra.disponiveis;
        input.value = String(n);
        row.classList.toggle('selecionada', n > 0);
        atualizarResumoModalComprados();
    });

    row.appendChild(document.createElement('span'));
    row.appendChild(txt);
    row.appendChild(disp);
    row.appendChild(input);
    return row;
}

function coletarSelecaoModalComprados() {
    const inputs = document.querySelectorAll('.modal-compra-row .modal-compra-qtd');
    const selecao = [];
    let total = 0;
    inputs.forEach(inp => {
        const row = inp.closest('.modal-compra-row');
        const cid = parseInt(row.dataset.compraId, 10);
        const qtd = parseInt(inp.value, 10) || 0;
        if (cid && qtd > 0) {
            selecao.push({ compra_id: cid, quantidade: qtd });
            total += qtd;
        }
    });
    return { selecao, total };
}

function atualizarResumoModalComprados() {
    const { total } = coletarSelecaoModalComprados();
    const resumo = document.getElementById('modal_comprados_resumo');
    const btn = document.getElementById('btn_confirmar_importar_comprados');
    if (resumo) resumo.textContent = `${total} perfil(is) selecionado(s)`;
    if (btn) btn.disabled = (total <= 0);
}

async function confirmarImportarComprados() {
    const { selecao, total } = coletarSelecaoModalComprados();
    if (total <= 0) return;

    const btn = document.getElementById('btn_confirmar_importar_comprados');
    btn.disabled = true;
    btn.textContent = 'Importando...';

    try {
        const res = await pywebview.api.importar_perfis_comprados(selecao);
        if (res && res.sucesso) {
            perfisImportados = res.perfis;
            renderizarTabela(perfisImportados);
            atualizarContadores(res.total, 0, 0);
            mostrarSucesso(`${res.total} perfis importados do painel`);
            document.getElementById('btn_iniciar').disabled = false;
            fecharModalComprados();
        } else {
            mostrarErro((res && res.erro) || 'Falha ao importar.');
        }
    } catch (e) {
        mostrarErro('Erro: ' + (e.message || e));
    } finally {
        btn.disabled = false;
        btn.textContent = 'Importar';
    }
}

// ============================================
// IMPORTAR ARQUIVO TXT
// ============================================

function lerArquivoTXT(arquivo) {
    const reader = new FileReader();

    reader.onload = async function(e) {
        try {
            const resultado = await pywebview.api.importar_perfis(e.target.result);

            if (resultado && resultado.sucesso) {
                perfisImportados = resultado.perfis;
                renderizarTabela(perfisImportados);
                atualizarContadores(resultado.total, 0, 0);
                document.getElementById('btn_iniciar').disabled = false;
                atualizarContagemProxy();

                let msg = resultado.mensagem || `${resultado.total} perfis importados com sucesso`;
                mostrarSucesso(msg);

                atualizarContadorPerfis(true);
            } else {
                mostrarErro(resultado ? resultado.erro : 'Erro ao importar perfis');
            }
        } catch (err) {
            mostrarErro('Erro ao processar arquivo: ' + err.message);
        }
    };

    reader.onerror = () => mostrarErro('Erro ao ler o arquivo');
    reader.readAsText(arquivo, 'UTF-8');
}

// ============================================
// RENDERIZAR TABELA
// ============================================

function renderizarTabela(perfis) {
    const tbody = document.getElementById('tabela_body');
    const tabela = document.getElementById('tabela_perfis');
    const vazio = document.getElementById('estado_vazio');

    if (!perfis || perfis.length === 0) {
        tabela.style.display = 'none';
        vazio.style.display = 'flex';
        return;
    }

    tabela.style.display = 'table';
    vazio.style.display = 'none';
    tbody.innerHTML = '';

    perfis.forEach(function(p, i) {
        const tr = document.createElement('tr');
        tr.id = 'perfil_row_' + i;

        tr.innerHTML = `
            <td>${p.numero}</td>
            <td class="login-col">${p.login}</td>
            <td>${p.email || '-'}</td>
            <td>${formatarTag(p.senha_email)}</td>
            <td>${formatarTag(p.tfa)}</td>
            <td>${formatarTag(p.cookie)}</td>
            <td>${formatarTag(p.token)}</td>
            <td>
                <div class="status-cell">
                    <span class="status-dot" id="dot_${i}" style="background-color: #3F3F46;"></span>
                    <span class="status-text" id="status_${i}">Aguardando</span>
                </div>
            </td>
        `;

        tbody.appendChild(tr);
    });
}

function formatarTag(valor) {
    if (valor === 'Sim') return '<span class="tag-sim">Sim</span>';
    return '<span class="tag-nao">-</span>';
}

// ============================================
// CONTADORES
// ============================================

function atualizarContadores(total, ok, erros, recorridas) {
    recorridas = recorridas || 0;
    document.getElementById('cnt_total').textContent = total;
    document.getElementById('cnt_ok').textContent = ok;
    document.getElementById('cnt_erro').textContent = erros;

    // Alimenta os cards do hero (visíveis também no estado ocioso).
    // 'Processando' é gerido em tempo real por atualizarProgresso.
    if (!processando) {
        setCard('card_ok_num', ok);
        setCard('card_erro_num', erros);
        setCard('card_recorrida_num', recorridas);
        setCard('card_proc_num', 0);
        setCard('card_aguard_num', Math.max(0, (total || 0) - ok - erros - recorridas));
        const total1 = total || 1;
        const bo = document.getElementById('bar_ok'), be = document.getElementById('bar_erro');
        const pctOk = Math.round((ok / total1) * 100), pctEr = Math.round((erros / total1) * 100);
        if (bo) bo.style.width = pctOk + '%';
        if (be) be.style.width = pctEr + '%';
        const po = document.getElementById('bar_ok_pct'); if (po) po.textContent = pctOk + '%';
        const pe = document.getElementById('bar_erro_pct'); if (pe) pe.textContent = pctEr + '%';
    }
}

// ============================================
// INICIAR PROCESSAMENTO
// ============================================

async function iniciarProcessamento() {
    if (processando) return;

    if (perfisImportados.length === 0) {
        mostrarErro('Importe perfis primeiro usando "Importar .TXT"');
        return;
    }

    // Setar engine antes de verificar
    const browserEngine = document.getElementById('browser_engine').value;
    const adspowerToken = document.getElementById('adspower_token').value;
    const adspowerUrl = document.getElementById('adspower_url').value;

    try {
        await pywebview.api.definir_browser_engine(browserEngine, adspowerUrl, adspowerToken);
    } catch(e) {}

    // Verificar conexão
    await verificarConexaoBrowser();
    const badge = document.getElementById('status_ix');
    if (badge.classList.contains('desconectado')) {
        const engineName = browserEngine === 'adspower' ? 'AdsPower' : 'IXBrowser';
        const errorDetail = badge.title || '';
        if (errorDetail.toLowerCase().includes('api key')) {
            mostrarErro(errorDetail);
        } else {
            mostrarErro(`${engineName} não está conectado. Abra o ${engineName} e tente novamente.`);
        }
        return;
    }

    // Coletar configurações
    const nomeGrupo = document.getElementById('nome_grupo').value || 'Facebook Profiles';
    const proxy = document.getElementById('proxy_select').value;
    const utilizar4g = document.getElementById('utilizar_4g_select').value;
    const listaProxy = document.getElementById('lista_proxy').value;
    const proxyTipo = document.getElementById('proxy_tipo').value;
    const usuario = document.getElementById('login_usuario').value;
    const senha = document.getElementById('login_senha').value;
    const lembrarAcesso = document.getElementById('lembrar_acesso').checked ? 'sim' : 'nao';
    const qtdBm = parseInt(document.getElementById('qtd_bm_select').value) || 1;
    // Captcha e SMS agora são SERVER-SIDE (chave do admin / serviço central do painel).
    // Estes campos não existem mais no cliente — passam vazios só para preservar o
    // contrato posicional das APIs (o backend/etapa ignoram no modo central).
    const captchaToken = (document.getElementById('captcha_token') || {}).value || '';
    const smsProvedor = (document.getElementById('sms_provedor') || {}).value || 'sms24h';
    const sms24hToken = smsToken(smsProvedor);
    // Fluxo ÚNICO: ⚡ Pro Max DataCrazy Turbo (Meta direto, sem CRM).
    const verificarBm = FLUXO_UNICO;
    const tipoEmpresa = document.getElementById('tipo_empresa_select').value;
    const autoVerificarChk = document.getElementById('auto_verificar_check');
    const autoVerificar = autoVerificarChk && autoVerificarChk.checked ? 'sim' : 'nao';
    // 🌐 Método de verificação do domínio no Meta (auto | metatag | dns | arquivo).
    const _mvSel = document.getElementById('metodo_verificacao_select');
    const metodoVerificacaoDominio = (_mvSel ? _mvSel.value : 'auto');

    // Controle de acesso: o Turbo é só para Editor/Admin (o backend também bloqueia).
    if (!_podePlanoGupshup) {
        alert('O Pro Max DataCrazy Turbo é exclusivo para usuários Editor/Admin.\n'
            + 'Peça a liberação do seu acesso no painel.');
        return;
    }

    // (Removido) Exigência de CapSolver e de chave de provedor de SMS no cliente:
    // agora o captcha é resolvido no SERVIDOR (chave do admin) e o número de SMS vem
    // do SERVIÇO CENTRAL do painel (cobrado do saldo real). O único requisito é o
    // usuário ter SALDO — validado server-side no momento da compra (pausa e pede
    // recarga se faltar). Nada a exigir aqui.

    // (Removido) Modos de rotação programada de IP: agora a troca do 4G é automática e
    // só ocorre no rate-limit de SMS da Meta. Nada a persistir aqui.

    // Salvar configurações (mesma rotina do modal — uma fonte só de verdade).
    try {
        await salvarConfiguracoesAtuais();
    } catch (e) {
        console.error('Erro ao salvar configs:', e);
    }

    // Iniciar
    try {
        const resultado = await pywebview.api.iniciar_processamento(
            nomeGrupo, proxy, utilizar4g, listaProxy, proxyTipo,
            usuario, senha, qtdBm,
            browserEngine, adspowerToken, captchaToken,
            verificarBm, tipoEmpresa, autoVerificar,
            obterSimultaneos(), obterOculto(),
            '', '', sms24hToken,          // datacrazy_email/senha: não usados (Turbo)
            smsProvedor, metodoVerificacaoDominio
        );

        if (resultado && resultado.sucesso) {
            processando = true;

            document.getElementById('btn_iniciar').style.display = 'none';
            document.getElementById('btn_cancelar').style.display = 'flex';
            { const _bp = document.getElementById('btn_pausar'); if (_bp) _bp.style.display = 'flex';
              const _bc = document.getElementById('btn_continuar'); if (_bc) _bc.style.display = 'none'; }
            document.getElementById('btn_importar').disabled = true;
            document.getElementById('barra_progresso_container').classList.add('ativo');

            // Dashboard de execução ao vivo
            resetDashboardExecucao();
            document.body.classList.add('proc-ativo');
            const painel = document.getElementById('painel_execucao');
            if (painel) painel.style.display = 'flex';
            window._ipEvVistos = new Set();   // zera o dedupe de eventos de IP a cada run
            pushTerminal(null, '🚀 Processamento iniciado — ' + obterSimultaneos() + ' navegador(es) simultâneo(s)', 'info');

            intervaloProgresso = setInterval(atualizarProgresso, 1000);
            mostrarSucesso('Processamento iniciado');
        } else {
            mostrarErro(resultado ? resultado.mensagem : 'Erro ao iniciar');
        }
    } catch (err) {
        mostrarErro('Erro: ' + err.message);
    }
}

// ============================================
// CANCELAR PROCESSAMENTO
// ============================================

async function cancelarProcessamento() {
    try {
        await pywebview.api.cancelar_processamento();
        mostrarErro('Cancelando — fechando navegadores e abortando...');
    } catch (e) {
        console.log('Erro ao cancelar:', e);
    }
}

async function pausarProcessamento() {
    try {
        await pywebview.api.pausar_processamento();
        const bp = document.getElementById('btn_pausar'); if (bp) bp.style.display = 'none';
        const bc = document.getElementById('btn_continuar'); if (bc) bc.style.display = 'flex';
        mostrarErro('⏸️ Pausado — clique Continuar para retomar.');
    } catch (e) { console.log('Erro ao pausar:', e); }
}

async function exportarFalhas(categoria) {
    try {
        const r = (categoria === 'login')
            ? await pywebview.api.exportar_falhas_login()
            : await pywebview.api.exportar_falhas_fluxo();
        if (r && r.sucesso) {
            mostrarSucesso(`✅ ${r.total} perfil(is) exportado(s).`);
        } else {
            mostrarErro((r && r.mensagem) ? r.mensagem : 'Nada para exportar.');
        }
    } catch (e) {
        console.log('Erro ao exportar falhas:', e);
        mostrarErro('Erro ao exportar a lista.');
    }
}

async function continuarProcessamento() {
    try {
        await pywebview.api.continuar_processamento();
        const bc = document.getElementById('btn_continuar'); if (bc) bc.style.display = 'none';
        const bp = document.getElementById('btn_pausar'); if (bp) bp.style.display = 'flex';
        mostrarSucesso('▶️ Retomando...');
    } catch (e) { console.log('Erro ao continuar:', e); }
}

// ============================================
// ATUALIZAR PROGRESSO
// ============================================

async function atualizarProgresso() {
    try {
        const prog = await pywebview.api.obter_progresso();
        if (!prog) return;

        atualizarContadores(prog.total, prog.concluidos, prog.erros, prog.recorridas);

        // 🌐 Eventos de troca de IP 4G (atual → novo): mostra no terminal, 1x cada.
        if (prog.ip_eventos && prog.ip_eventos.length) {
            window._ipEvVistos = window._ipEvVistos || new Set();
            prog.ip_eventos.forEach(function (ev) {
                const k = (ev.ts || '') + '|' + (ev.msg || '');
                if (!window._ipEvVistos.has(k)) {
                    window._ipEvVistos.add(k);
                    pushTerminal(null, ev.msg, 'info');
                }
            });
        }

        const total = prog.total || 1;
        const feitos = prog.concluidos + prog.erros;
        const pct = Math.round((feitos / total) * 100);
        document.getElementById('barra_progresso').style.width = pct + '%';
        document.getElementById('rodape_info').textContent = `Processando... ${feitos}/${total} (${pct}%)`;

        const itensProc = [];
        if (prog.progresso) {
            let coinDebitadoNovo = false;
            prog.progresso.forEach(function(p) {
                const dot = document.getElementById('dot_' + p.indice);
                const status = document.getElementById('status_' + p.indice);
                const row = document.getElementById('perfil_row_' + p.indice);

                if (dot) dot.style.backgroundColor = p.cor;
                if (status) {
                    if (p.mensagem && p.status !== 'Aguardando') {
                        status.textContent = p.status;
                        status.title = p.mensagem;
                        if (p.status === 'Processando') {
                            status.textContent = p.mensagem.length > 50 ? p.mensagem.substring(0, 47) + '...' : p.mensagem;
                        }
                    } else {
                        status.textContent = p.status;
                    }
                }

                if (row) {
                    row.classList.toggle('processando', p.status === 'Processando');
                }

                // Coletar itens em processamento (tiles de worker)
                if (p.status === 'Processando') itensProc.push(p);

                // Terminal central: registra quando a mensagem do perfil muda
                const msgAtual = p.mensagem || p.status || '';
                if (msgAtual && ultimaMsgPorPerfil[p.indice] !== msgAtual && p.status !== 'Aguardando') {
                    ultimaMsgPorPerfil[p.indice] = msgAtual;
                    const tipoLinha = (p.status === 'Erro') ? 'erro'
                                    : (p.status === 'Concluído') ? 'ok' : 'info';
                    pushTerminal(p.indice + 1, msgAtual, tipoLinha);
                }

                // Brilho de borda nas transições de status (verde=ok / vermelho=erro)
                if (statusAnteriorPorPerfil[p.indice] !== p.status) {
                    if (p.status === 'Concluído') flashBorda('ok');
                    else if (p.status === 'Erro') flashBorda('erro');
                    statusAnteriorPorPerfil[p.indice] = p.status;
                }

                // Detectar coin novo debitado
                if (p.coin_debitado && row && !row.dataset.coinRegistrado) {
                    row.dataset.coinRegistrado = '1';
                    coinDebitadoNovo = true;
                }
            });
            // Atualizar saldo sempre que houver novo débito
            if (coinDebitadoNovo) atualizarSaldoCoins();
        }

        // ----- Dashboard ao vivo: cards, barras duplas, tiles -----
        const nProc = itensProc.length;
        const nRec = prog.recorridas || 0;
        const nAguard = Math.max(0, (prog.total || 0) - prog.concluidos - prog.erros - nRec - nProc);
        setCard('card_ok_num', prog.concluidos);
        setCard('card_erro_num', prog.erros);
        setCard('card_recorrida_num', nRec);
        setCard('card_proc_num', nProc);
        setCard('card_aguard_num', nAguard);

        const pctOk = Math.round((prog.concluidos / total) * 100);
        const pctErr = Math.round((prog.erros / total) * 100);
        const barOk = document.getElementById('bar_ok');
        const barErr = document.getElementById('bar_erro');
        if (barOk) barOk.style.width = pctOk + '%';
        if (barErr) barErr.style.width = pctErr + '%';
        const pOk = document.getElementById('bar_ok_pct'); if (pOk) pOk.textContent = pctOk + '%';
        const pErr = document.getElementById('bar_erro_pct'); if (pErr) pErr.textContent = pctErr + '%';

        renderWorkers(itensProc);
        const sub = document.getElementById('exec_terminal_sub');
        if (sub) sub.textContent = `${nProc} ativo(s) · ${prog.concluidos} ok · ${prog.erros} erro(s)`
                 + (nRec ? ` · ${nRec} recorrida(s)` : '');

        // Pausar/Continuar durante a execução — reflete o estado REAL do backend
        // (ex.: pausou sozinho por SMS sem saldo).
        if (prog.processando) {
            const bp = document.getElementById('btn_pausar');
            const bc = document.getElementById('btn_continuar');
            if (bp) bp.style.display = prog.pausado ? 'none' : 'flex';
            if (bc) bc.style.display = prog.pausado ? 'flex' : 'none';
        }
        // Verificar se terminou
        if (!prog.processando) {
            processando = false;
            clearInterval(intervaloProgresso);
            intervaloProgresso = null;

            document.getElementById('btn_iniciar').disabled = false;
            document.getElementById('btn_iniciar').style.display = 'flex';
            document.getElementById('btn_cancelar').style.display = 'none';
            { const _bp = document.getElementById('btn_pausar'); if (_bp) _bp.style.display = 'none';
              const _bc = document.getElementById('btn_continuar'); if (_bc) _bc.style.display = 'none'; }
            document.getElementById('btn_importar').disabled = false;
            const _rec = prog.recorridas || 0;
            const _recTxt = _rec ? `, ${_rec} recorridas` : '';
            document.getElementById('rodape_info').textContent = `Concluído: ${prog.concluidos} OK, ${prog.erros} erros${_recTxt}`;

            // Encerrar dashboard de execução
            document.body.classList.remove('proc-ativo');
            const wrapW = document.getElementById('exec_workers');
            if (wrapW) wrapW.innerHTML = '';
            const subT = document.getElementById('exec_terminal_sub');
            if (subT) subT.textContent = `finalizado · ${prog.concluidos} ok · ${prog.erros} erro(s)` + (_rec ? ` · ${_rec} recorrida(s)` : '');
            pushTerminal(null, `🏁 Concluído — ${prog.concluidos} sucesso(s), ${prog.erros} erro(s)${_rec ? `, ${_rec} recorrida(s)` : ''}`,
                         prog.erros > 0 ? 'erro' : 'ok');
            flashBorda(prog.erros > 0 && prog.concluidos === 0 ? 'erro' : 'ok');

            if (prog.erros === 0 && prog.concluidos > 0) {
                mostrarSucesso(`Todos os ${prog.concluidos} perfis foram processados com sucesso!`);
            } else if (prog.concluidos > 0) {
                mostrarSucesso(`${prog.concluidos} perfis processados, ${prog.erros} com erro`);
            }

            // Atualizar saldo final após todos os débitos
            atualizarSaldoCoins();

            try {
                const check = await pywebview.api.consultar_perfis_disponiveis();
                if (check) atualizarContadorPerfis(check.conectado !== undefined ? check.conectado : check.total);
            } catch(e) {}
        }
    } catch (e) {
        console.log('Erro ao obter progresso:', e);
    }
}

// ============================================
// MENSAGENS
// ============================================

function mostrarSucesso(texto) {
    const el = document.getElementById('mensagem_sucesso');
    el.textContent = texto;
    el.classList.add('visivel');
    setTimeout(() => el.classList.remove('visivel'), 4000);
}

function mostrarErro(texto) {
    const el = document.getElementById('mensagem_erro');
    el.textContent = texto;
    el.classList.add('visivel');
    setTimeout(() => el.classList.remove('visivel'), 4000);
}

// ============================================
// FILA DE VERIFICAÇÃO DE BMs
// ============================================

function toggleFilaVerificacao() {
    filaVisivel = !filaVisivel;
    const card = document.getElementById('fila_verificacao_card');
    const btn = document.getElementById('btn_toggle_fila');
    card.style.display = filaVisivel ? 'block' : 'none';
    btn.classList.toggle('active', filaVisivel);
}

async function atualizarFilaVerificacao() {
    try {
        const fila = await pywebview.api.obter_fila_verificacao();
        if (!fila) return;

        // Atualizar badges
        document.getElementById('fila_aguardando_num').textContent = fila.aguardando || 0;
        document.getElementById('fila_prontas_num').textContent = fila.prontas || 0;
        document.getElementById('fila_verificadas_num').textContent = fila.verificadas || 0;
        document.getElementById('fila_erros_num').textContent = fila.erros || 0;

        // Mostrar/ocultar badge de erros
        const badgeErros = document.getElementById('fila_erros');
        badgeErros.style.display = (fila.erros || 0) > 0 ? 'flex' : 'none';

        // Botão retentar erros
        const btnRetentar = document.getElementById('btn_retentar_fila');
        btnRetentar.style.display = (fila.erros || 0) > 0 && !fila.verificacao_processando ? 'flex' : 'none';

        // Highlight do badge de prontas
        const badgeProntas = document.getElementById('fila_prontas');
        badgeProntas.classList.toggle('has-items', (fila.prontas || 0) > 0);

        // Botão verificar — ativar se tem prontas e não está processando
        const btnVerificar = document.getElementById('btn_verificar_fila');
        const btnCancelar = document.getElementById('btn_cancelar_verificacao');

        if (fila.verificacao_processando) {
            verificandoFila = true;
            btnVerificar.style.display = 'none';
            btnCancelar.style.display = 'flex';
        } else {
            if (verificandoFila) {
                // Acabou de terminar
                verificandoFila = false;
                const msg = fila.verificacao_mensagem || 'Verificação concluída';
                mostrarSucesso(msg);
            }
            btnVerificar.style.display = 'flex';
            btnCancelar.style.display = 'none';
            btnVerificar.disabled = (fila.prontas || 0) === 0;
        }

        // ── Modo REPROCESSAR (varre perfis do AdsPower) ──
        const btnReproc = document.getElementById('btn_reprocessar_fila');
        const btnCancReproc = document.getElementById('btn_cancelar_reprocesso');
        const reprocStatus = document.getElementById('reproc_status');
        if (btnReproc && btnCancReproc) {
            if (fila.reprocesso_processando) {
                btnReproc.style.display = 'none';
                btnCancReproc.style.display = 'flex';
                if (reprocStatus) {
                    const prog = fila.reprocesso_progresso || [];
                    const feitos = prog.filter(p => p.status === 'Concluído' || p.status === 'Erro').length;
                    reprocStatus.textContent = `♻️ ${feitos}/${prog.length} · ` +
                        `${fila.reprocesso_novas_bm||0} nova(s) · ${fila.reprocesso_ignoradas||0} ignorada(s) · ` +
                        `${fila.reprocesso_erros||0} erro(s) — ${fila.reprocesso_mensagem||''}`;
                }
            } else {
                if (reprocessando) {
                    // Acabou de terminar
                    reprocessando = false;
                    mostrarSucesso(fila.reprocesso_mensagem || 'Reprocesso concluído');
                    if (reprocStatus) reprocStatus.textContent = fila.reprocesso_mensagem || '';
                }
                btnCancReproc.style.display = 'none';
                btnReproc.style.display = 'flex';
                // Habilitado quando nada mais está rodando (NÃO depende da fila local).
                btnReproc.disabled = !!(fila.verificacao_processando ||
                                        document.getElementById('btn_cancelar').style.display === 'flex');
            }
        }

        // Mensagem informativa
        const infoEl = document.getElementById('fila_proxima_msg');
        const autoOn = false;  // auto-verificar removido (2026-10-13)
        if (fila.total === 0) {
            infoEl.textContent = 'Nenhuma BM na fila de verificação';
            infoEl.style.color = 'var(--text-muted)';
        } else if (fila.verificacao_processando) {
            infoEl.textContent = fila.verificacao_mensagem || 'Verificando...';
            infoEl.style.color = 'var(--primary)';
        } else if (fila.prontas > 0) {
            if (autoOn) {
                infoEl.textContent = `🤖 ${fila.prontas} BM(s) pronta(s) — verificação automática ativa`;
                infoEl.style.color = 'var(--success)';
            } else {
                infoEl.textContent = `${fila.prontas} BM(s) pronta(s) para verificar — clique "Verificar Prontas"`;
                infoEl.style.color = 'var(--primary)';
            }
        } else if (fila.proxima_pronta_min > 0) {
            const h = Math.floor(fila.proxima_pronta_min / 60);
            const m = fila.proxima_pronta_min % 60;
            const tempoStr = h > 0 ? `${h}h ${m}min` : `${m}min`;
            const autoTxt = autoOn ? ' — auto-verificação aguardando' : '';
            infoEl.textContent = `Próxima BM pronta em ~${tempoStr}${autoTxt}`;
            infoEl.style.color = 'var(--text-muted)';
        } else {
            infoEl.textContent = `${fila.aguardando} aguardando espera mínima de 2 horas`;
            infoEl.style.color = 'var(--text-muted)';
        }

        // Barra de progresso — verificação da fila OU reprocesso (o que estiver ativo)
        const progContainer = document.getElementById('fila_progresso_container');
        const progAtivo = fila.reprocesso_processando ? fila.reprocesso_progresso
                        : (fila.verificacao_processando ? fila.verificacao_progresso : null);
        if (progAtivo && progAtivo.length > 0) {
            progContainer.style.display = 'block';
            const total = progAtivo.length;
            const feitos = progAtivo.filter(p =>
                p.status === 'Concluído' || p.status === 'Erro'
            ).length;
            const pct = Math.round((feitos / total) * 100);
            document.getElementById('fila_progresso_fill').style.width = pct + '%';

            const prefixo = fila.reprocesso_processando ? '♻️ ' : '';
            const atual = progAtivo.find(p => p.status === 'Processando');
            if (atual) {
                document.getElementById('fila_progresso_texto').textContent =
                    `${prefixo}${feitos}/${total} — ${atual.mensagem || atual.bm_name || ''}`;
            } else {
                document.getElementById('fila_progresso_texto').textContent =
                    `${prefixo}${feitos}/${total} processados`;
            }
        } else if (!fila.verificacao_processando && !fila.reprocesso_processando) {
            progContainer.style.display = 'none';
        }

        // Mostrar/ocultar card baseado no toggle (abrir automaticamente se tiver itens e estava fechado)
        const card = document.getElementById('fila_verificacao_card');
        const btnToggle = document.getElementById('btn_toggle_fila');
        const totalFila = (fila.total || 0);

        // Atualizar badge no botão toggle
        const badge = document.getElementById('fila_toggle_badge');
        if (totalFila > 0 || fila.verificacao_processando) {
            badge.textContent = totalFila;
            badge.style.display = 'flex';
        } else {
            badge.style.display = 'none';
        }

        // Se começou a processar (verificação OU reprocesso), abrir automaticamente
        if ((fila.verificacao_processando || fila.reprocesso_processando) && !filaVisivel) {
            filaVisivel = true;
            card.style.display = 'block';
            btnToggle.classList.add('active');
        }

        // Respeitar estado do toggle
        card.style.display = filaVisivel ? 'block' : 'none';
        btnToggle.classList.toggle('active', filaVisivel);

    } catch (e) {
        console.log('Erro ao atualizar fila:', e);
    }
}

async function iniciarVerificacaoFila() {
    if (verificandoFila) return;

    try {
        // Configurar engine antes
        const browserEngine = document.getElementById('browser_engine').value;
        const adspowerToken = document.getElementById('adspower_token').value;
        const adspowerUrl = document.getElementById('adspower_url').value;
        try {
            await pywebview.api.definir_browser_engine(browserEngine, adspowerUrl, adspowerToken);
        } catch(e) {}

        const resultado = await pywebview.api.iniciar_verificacao_fila();
        if (resultado && resultado.sucesso) {
            verificandoFila = true;
            mostrarSucesso(resultado.mensagem || 'Verificação iniciada');
        } else {
            mostrarErro(resultado ? resultado.mensagem : 'Erro ao iniciar verificação');
        }
    } catch (e) {
        mostrarErro('Erro: ' + e.message);
    }
}

async function cancelarVerificacaoFila() {
    try {
        await pywebview.api.cancelar_verificacao_fila();
        mostrarErro('Cancelando verificação da fila...');
    } catch (e) {
        console.log('Erro ao cancelar verificação:', e);
    }
}

let reprocessando = false;

async function carregarGruposReprocesso() {
    try {
        const sel = document.getElementById('reproc_grupo');
        if (!sel) return;
        const r = await pywebview.api.listar_grupos_adspower();
        const grupos = (r && r.grupos) ? r.grupos : [];
        // Mantém "Todos os perfis" e adiciona os grupos
        sel.innerHTML = '<option value="">Todos os perfis</option>';
        grupos.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g.group_id;
            opt.textContent = g.group_name || ('Grupo ' + g.group_id);
            sel.appendChild(opt);
        });
    } catch (e) {
        console.log('Erro ao carregar grupos:', e);
    }
}

async function iniciarReprocesso() {
    if (reprocessando) return;
    const sel = document.getElementById('reproc_grupo');
    const grupo = sel ? sel.value : '';
    const nomeGrupo = sel && sel.selectedOptions.length ? sel.selectedOptions[0].textContent : 'Todos';
    // Modo REUTILIZAR PERFIL LOGADO: sempre cria BM nova (mesmo com BM já criada).
    const forcarNova = !!(document.getElementById('reproc_forcar_nova') || {}).checked;
    const okConfirm = confirm(forcarNova
        ? (`REUTILIZAR PERFIS LOGADOS do grupo "${nomeGrupo}": o software abre CADA perfil ` +
           '(mesmo os que já têm BM criada/ativa ou não usada) e SEMPRE cria uma BM NOVA ' +
           '+ empresa nova, enviando p/ análise pelo Pro Max DataCrazy Turbo. A BM nova ' +
           'já entra selecionada no fluxo.\n\n' +
           'Consome 1 empresa + SMS por perfil. Continuar?')
        : (`Reprocessar o grupo "${nomeGrupo}": o software abre cada perfil do AdsPower, ` +
           'descobre a BM, lê o status ao vivo e:\n\n' +
           '• Não verificada / rejeitada → cria BM NOVA + empresa nova e envia p/ análise\n' +
           '• Em análise há +24h (travada) → idem (cria BM nova)\n' +
           '• Verificada / Em análise recente → ignora e fecha\n\n' +
           'Criar BM nova consome 1 empresa + SMS por perfil. Continuar?'));
    if (!okConfirm) return;
    try {
        const browserEngine = document.getElementById('browser_engine').value;
        const adspowerToken = document.getElementById('adspower_token').value;
        const adspowerUrl = document.getElementById('adspower_url').value;
        try { await pywebview.api.definir_browser_engine(browserEngine, adspowerUrl, adspowerToken); } catch(e) {}

        const simSel = document.getElementById('simultaneos_select');
        const simult = simSel ? parseInt(simSel.value, 10) || 1 : 1;
        const resultado = await pywebview.api.iniciar_reprocesso_verificacao(grupo, 24, simult, forcarNova);
        if (resultado && resultado.sucesso) {
            reprocessando = true;
            mostrarSucesso(resultado.mensagem || 'Reprocesso iniciado');
            if (!intervaloReproc) intervaloReproc = setInterval(pollReprocesso, 1500);
        } else {
            mostrarErro(resultado ? resultado.mensagem : 'Erro ao iniciar reprocesso');
        }
    } catch (e) {
        mostrarErro('Erro: ' + e.message);
    }
}

async function cancelarReprocesso() {
    try {
        await pywebview.api.cancelar_reprocesso_verificacao();
        mostrarErro('Cancelando reprocesso...');
    } catch (e) {
        console.log('Erro ao cancelar reprocesso:', e);
    }
}

let intervaloReproc = null;

async function pollReprocesso() {
    try {
        const st = await pywebview.api.obter_reprocesso_status();
        if (!st) return;
        const btnReproc = document.getElementById('btn_reprocessar_fila');
        const btnCancReproc = document.getElementById('btn_cancelar_reprocesso');
        const reprocStatus = document.getElementById('reproc_status');
        const prog = st.progresso || [];
        const feitos = prog.filter(p => p.status === 'Concluído' || p.status === 'Erro').length;
        if (st.processando) {
            reprocessando = true;
            if (btnReproc) btnReproc.style.display = 'none';
            if (btnCancReproc) btnCancReproc.style.display = 'flex';
            if (reprocStatus) reprocStatus.textContent =
                `♻️ ${feitos}/${prog.length} · ${st.novas_bm||0} nova(s) · ` +
                `${st.ignoradas||0} ignorada(s) · 🗑️${st.excluidos||0} · ${st.erros||0} erro(s)\n${st.mensagem||''}`;
        } else {
            if (btnCancReproc) btnCancReproc.style.display = 'none';
            if (btnReproc) { btnReproc.style.display = 'flex'; btnReproc.disabled = false; }
            if (reprocessando) {
                reprocessando = false;
                mostrarSucesso(st.mensagem || 'Reprocesso concluído');
                if (reprocStatus) reprocStatus.textContent = st.mensagem || '';
            }
            if (intervaloReproc) { clearInterval(intervaloReproc); intervaloReproc = null; }
        }
    } catch (e) {
        console.log('poll reproc:', e);
    }
}

// ============================================
// REUTILIZAR PERFIS LOGADOS (cria 1 BM NOVA em cada perfil do grupo)
// ============================================
let reutilizando = false;
let intervaloReutilizar = null;

function abrirModalReutilizar() {
    const modal = document.getElementById('modal_reutilizar');
    if (!modal) return;
    const eng = (document.getElementById('browser_engine') || {}).value || 'adspower';
    const nome = document.getElementById('reutilizar_engine_nome');
    if (nome) nome.textContent = (eng === 'adspower') ? 'AdsPower' : 'IxBrowser';
    const resumo = document.getElementById('reutilizar_resumo');
    if (resumo) resumo.textContent = '';
    modal.style.display = 'flex';
    carregarGruposReutilizar();
}

function fecharModalReutilizar() {
    const modal = document.getElementById('modal_reutilizar');
    if (modal) modal.style.display = 'none';
}

async function carregarGruposReutilizar() {
    try {
        const eng = (document.getElementById('browser_engine') || {}).value || 'adspower';
        const tok = (document.getElementById('adspower_token') || {}).value || '';
        const url = (document.getElementById('adspower_url') || {}).value || '';
        try { await pywebview.api.definir_browser_engine(eng, url, tok); } catch(e) {}
        const sel = document.getElementById('reproc_grupo');
        if (!sel) return;
        sel.innerHTML = '<option value="">Todos os perfis</option>';
        const r = await pywebview.api.listar_grupos_adspower();
        const grupos = (r && r.grupos) ? r.grupos : [];
        grupos.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g.group_id;
            opt.textContent = g.group_name || ('Grupo ' + g.group_id);
            sel.appendChild(opt);
        });
    } catch (e) { console.log('carregarGruposReutilizar:', e); }
}

async function iniciarReutilizarLogados() {
    if (reutilizando) return;
    const sel = document.getElementById('reproc_grupo');
    const grupo = sel ? sel.value : '';
    const nomeGrupo = sel && sel.selectedOptions.length ? sel.selectedOptions[0].textContent : 'Todos';
    const okConfirm = confirm(
        `REUTILIZAR PERFIS LOGADOS do grupo "${nomeGrupo}": o software abre CADA perfil ` +
        '(mesmo os que já têm BM criada/ativa ou não usada) e SEMPRE cria uma BM NOVA ' +
        '+ empresa nova, enviando p/ análise pelo Pro Max DataCrazy Turbo. A BM nova ' +
        'já entra selecionada no fluxo.\n\nConsome 1 empresa + SMS por perfil. Continuar?'
    );
    if (!okConfirm) return;
    try {
        const eng = (document.getElementById('browser_engine') || {}).value || 'adspower';
        const tok = (document.getElementById('adspower_token') || {}).value || '';
        const url = (document.getElementById('adspower_url') || {}).value || '';
        try { await pywebview.api.definir_browser_engine(eng, url, tok); } catch(e) {}
        const simSel = document.getElementById('simultaneos_select');
        const simult = simSel ? parseInt(simSel.value, 10) || 1 : 1;
        // 4º argumento = forcar_nova_bm (sempre TRUE neste modo)
        const resultado = await pywebview.api.iniciar_reprocesso_verificacao(grupo, 24, simult, true);
        if (resultado && resultado.sucesso) {
            reutilizando = true;
            // Fecha o modal e mostra a INTERFACE PRINCIPAL (tabela de perfis +
            // terminal ao vivo + contadores), IGUAL ao fluxo de importação.
            fecharModalReutilizar();
            try {
                const _bc = document.getElementById('btn_cancelar'); if (_bc) _bc.style.display = 'flex';
                const _imp = document.getElementById('btn_importar'); if (_imp) _imp.disabled = true;
                const _bpc = document.getElementById('barra_progresso_container'); if (_bpc) _bpc.classList.add('ativo');
                if (typeof resetDashboardExecucao === 'function') resetDashboardExecucao();
                document.body.classList.add('proc-ativo');
                const painel = document.getElementById('painel_execucao'); if (painel) painel.style.display = 'flex';
                pushTerminal(null, '♻️ Reutilizar Perfis Logados — criando 1 BM nova em cada perfil do grupo', 'info');
            } catch (e) {}
            mostrarSucesso(resultado.mensagem || 'Reutilização iniciada');
            // Usa o MESMO poll do processamento normal (tabela + terminal).
            if (!intervaloProgresso) intervaloProgresso = setInterval(atualizarProgresso, 1000);
        } else {
            mostrarErro(resultado ? resultado.mensagem : 'Erro ao iniciar');
        }
    } catch (e) {
        mostrarErro('Erro: ' + e.message);
    }
}

async function pollReutilizar() {
    try {
        const st = await pywebview.api.obter_reprocesso_status();
        if (!st) return;
        const prog = st.progresso || [];
        const feitos = prog.filter(p => p.status === 'Concluído' || p.status === 'Erro').length;
        const resumo = document.getElementById('reutilizar_resumo');
        if (st.processando) {
            reutilizando = true;
            if (resumo) resumo.textContent =
                `♻️ ${feitos}/${prog.length} · ${st.novas_bm||0} BM nova(s) · ${st.erros||0} erro(s) — ${(st.mensagem||'').slice(0,60)}`;
        } else {
            if (reutilizando) {
                reutilizando = false;
                if (resumo) resumo.textContent = st.mensagem || 'Concluído';
                mostrarSucesso(st.mensagem || 'Reutilização concluída');
            }
            if (intervaloReutilizar) { clearInterval(intervaloReutilizar); intervaloReutilizar = null; }
        }
    } catch (e) { console.log('pollReutilizar:', e); }
}

// ============================================
// MONITOR DE ANÁLISE (substitui o Reprocessar)
// ============================================
let monitorando = false;
let intervaloMonitor = null;

async function carregarGruposMonitor() {
    try {
        const sel = document.getElementById('monitor_grupo');
        if (!sel) return;
        const r = await pywebview.api.listar_grupos_adspower();
        const grupos = (r && r.grupos) ? r.grupos : [];
        sel.innerHTML = '<option value="">Todos os perfis</option>';
        grupos.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g.group_id;
            opt.textContent = g.group_name || ('Grupo ' + g.group_id);
            sel.appendChild(opt);
        });
    } catch (e) {
        console.log('Erro ao carregar grupos (monitor):', e);
    }
}

async function atualizarQtdMonitor() {
    const el = document.getElementById('monitor_qtd');
    if (!el) return;
    try {
        el.textContent = '...';
        const n = await pywebview.api.contar_bms_monitoraveis(3);
        el.textContent = (n === null || n === undefined) ? '—' : String(n);
    } catch (e) {
        el.textContent = '—';
        console.log('Erro ao contar elegíveis:', e);
    }
}

function metodoWabaSelecionado() {
    // A WABA nasce sempre pelo Turbo (OAuth da Meta direto); o backend ignora o valor.
    return 'datacrazy';
}

async function iniciarMonitor() {
    if (monitorando) return;
    const sel = document.getElementById('monitor_grupo');
    const grupo = sel ? sel.value : '';
    const okConfirm = confirm(
        'Reaproveitar perfis NÃO CONCLUÍDOS: puxa os perfis do grupo AO VIVO do AdsPower e ' +
        'PULA os que já têm "BM EM ANALISE" ou "BM BLOQUEADA" na Observação. Nos demais:\n\n' +
        '• Sem BM → cria a BM e envia p/ análise\n' +
        '• BM existente (não restrita) → CONTINUA com ela (SMS novo → atualiza empresa/site/certificado → reenvia)\n' +
        '• BM restrita → cria uma 2ª BM; se as 2 restringirem → marca "BM BLOQUEADA" (mantém o perfil)\n\n' +
        'Continuar?'
    );
    if (!okConfirm) return;
    try {
        const browserEngine = document.getElementById('browser_engine').value;
        const adspowerToken = document.getElementById('adspower_token').value;
        const adspowerUrl = document.getElementById('adspower_url').value;
        try { await pywebview.api.definir_browser_engine(browserEngine, adspowerUrl, adspowerToken); } catch(e) {}

        const simSel = document.getElementById('simultaneos_select');
        const simult = simSel ? parseInt(simSel.value, 10) || 1 : 1;
        const resultado = await pywebview.api.iniciar_reprocesso_verificacao(grupo, 24, simult);
        if (resultado && resultado.sucesso) {
            monitorando = true;
            mostrarSucesso(resultado.mensagem || 'Monitor iniciado');
            if (!intervaloMonitor) intervaloMonitor = setInterval(pollMonitor, 1500);
        } else {
            mostrarErro(resultado ? resultado.mensagem : 'Erro ao iniciar o Monitor');
        }
    } catch (e) {
        mostrarErro('Erro: ' + e.message);
    }
}

async function cancelarMonitor() {
    try {
        await pywebview.api.cancelar_reprocesso_verificacao();
        mostrarErro('Cancelando o Reaproveitar...');
    } catch (e) {
        console.log('Erro ao cancelar monitor:', e);
    }
}

async function pollMonitor() {
    try {
        const st = await pywebview.api.obter_reprocesso_status();
        if (!st) return;
        const btnMonitor = document.getElementById('btn_monitorar');
        const btnCancMonitor = document.getElementById('btn_cancelar_monitor');
        const monitorStatus = document.getElementById('monitor_status');
        const prog = st.progresso || [];
        const feitos = prog.filter(p => p.status === 'Concluído' || p.status === 'Erro').length;
        if (st.processando) {
            monitorando = true;
            if (btnMonitor) btnMonitor.style.display = 'none';
            if (btnCancMonitor) btnCancMonitor.style.display = 'flex';
            if (monitorStatus) monitorStatus.textContent =
                `♻️ ${feitos}/${prog.length} · 💙${st.reenviadas||0} retomada(s) · 🆕${st.novas_bm||0} nova(s) · ` +
                `⚪${st.ignoradas||0} ignorada(s) · ${st.erros||0} erro(s)\n${st.mensagem||''}`;
        } else {
            if (btnCancMonitor) btnCancMonitor.style.display = 'none';
            if (btnMonitor) { btnMonitor.style.display = 'flex'; btnMonitor.disabled = false; }
            if (monitorando) {
                monitorando = false;
                mostrarSucesso(st.mensagem || 'Monitor concluído');
                if (monitorStatus) monitorStatus.textContent = st.mensagem || '';
                atualizarQtdMonitor();
            }
            if (intervaloMonitor) { clearInterval(intervaloMonitor); intervaloMonitor = null; }
        }
    } catch (e) {
        console.log('poll monitor:', e);
    }
}

async function limparFilaVerificadas() {
    try {
        const resultado = await pywebview.api.limpar_fila_verificadas();
        if (resultado && resultado.sucesso) {
            const removidos = resultado.removidos || 0;
            if (removidos > 0) {
                mostrarSucesso(`${removidos} BM(s) verificada(s) removida(s) da fila`);
            } else {
                mostrarSucesso('Nenhuma BM verificada para remover');
            }
            atualizarFilaVerificacao();
        }
    } catch (e) {
        console.log('Erro ao limpar fila:', e);
    }
}

async function retentarErrosFila() {
    try {
        const resultado = await pywebview.api.retentar_erros_fila();
        if (resultado && resultado.sucesso) {
            const movidos = resultado.movidos || 0;
            mostrarSucesso(`${movidos} BM(s) com erro movida(s) de volta para a fila`);
            atualizarFilaVerificacao();
        } else {
            mostrarErro(resultado ? resultado.mensagem : 'Erro ao retentar');
        }
    } catch (e) {
        console.log('Erro ao retentar erros:', e);
    }
}
