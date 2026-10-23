// Roda o _JS_NUMERO_VIRTUAL real (extraido do .py) contra DOMs que reproduzem os
// prints do dono, com jsdom. Sem navegador, sem Meta, sem gastar SMS.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const SRC = fs.readFileSync(process.argv[2], 'utf8');

let ok = 0, falhou = 0;
function checa(nome, real, esperado) {
  const bom = String(real) === String(esperado);
  if (bom) { ok++; console.log(`  OK   ${nome}  -> ${real}`); }
  else { falhou++; console.log(`  FALHA ${nome}  -> obteve ${real}, esperava ${esperado}`); }
}

function montar(html) {
  const dom = new JSDOM(`<body>${html}</body>`,
    { pretendToBeVisual: true, runScripts: 'outside-only' });
  const win = dom.window;
  // jsdom nao faz layout: todo elemento mede 0x0 e nosso vis() reprovaria tudo.
  win.Element.prototype.getBoundingClientRect = function () {
    const escondido = this.getAttribute && this.getAttribute('data-oculto') === '1';
    const n = escondido ? 0 : 100;
    return { width: n, height: n ? 20 : 0, left: 0, top: 0, right: n, bottom: 20 };
  };
  win.Element.prototype.scrollIntoView = function () {};
  const fn = win.eval('(' + SRC + ')');
  return { win, doc: win.document, fn };
}

// Tela de numero do LAYOUT NOVO. React simulado: clicar no combobox abre a lista;
// clicar na opcao virtual fecha a lista, troca o valor do campo e mostra o aviso.
function telaNova({ jaAberta = false } = {}) {
  const html = `
    <div role="button" id="trapConta">Adicione outra conta</div>
    <div role="dialog">
      <h2>Adicione seu número de telefone do WhatsApp</h2>
      <p>Choose how you want to be identified when sending messages.</p>
      <label>Telefone</label>
      <div role="combobox" id="combo"><span id="comboTxt">Você não tem nenhum número de telefone existente. Crie um novo</span></div>
      <div id="slotLista"></div>
      <div id="aviso"></div>
      <div role="button" id="avancar" aria-disabled="true">Avançar</div>
      <div role="button" id="voltar">Voltar</div>
    </div>`;
  const ctx = montar(html);
  const d = ctx.doc;

  function abrirLista() {
    d.getElementById('slotLista').innerHTML = `
      <div role="listbox" id="lista">
        <input type="text" id="busca" placeholder="Search term">
        <div id="wrapper">
          <div role="option" id="op1"><span>Você não tem nenhum número de telefone existente. Crie um novo</span></div>
          <div role="option" id="op2"><span>Use a display name with a virtual number instead</span></div>
        </div>
      </div>`;
    d.getElementById('op1').addEventListener('click', () => { ctx.escolhaErrada = true; fechar(); });
    d.getElementById('op2').addEventListener('click', () => {
      ctx.escolhaCerta = true;
      d.getElementById('comboTxt').textContent = 'Use a display name with a virtual number instead';
      d.getElementById('aviso').textContent = 'Verificação adicional necessária';
      d.getElementById('avancar').setAttribute('aria-disabled', 'false');
      fechar();
    });
  }
  function fechar() { d.getElementById('slotLista').innerHTML = ''; }

  d.getElementById('combo').addEventListener('click', abrirLista);
  if (jaAberta) abrirLista();
  return ctx;
}

console.log('\n=== 1) Tela de numero, layout NOVO (print 02) ===');
{
  const ctx = telaNova();
  checa('existe opcao virtual?', ctx.fn('existe'), true);
  // 1a volta: abre o dropdown
  const r1 = ctx.fn('selecionar');
  checa('1a volta abre a lista', ['abriu', 'ok'].includes(r1), true);
  // 2a volta (o Python re-tenta a cada 0,4s): escolhe a opcao certa
  // jsdom clica sincrono (1a volta ja resolve -> 2a responde 'ja'); no navegador o
  // React renderiza async ('abriu' -> 'ok'). Os dois sao sucesso para o Python.
  const r2 = ctx.fn('selecionar');
  checa('2a volta confirma', ['ok', 'ja'].includes(r2), true);
  checa('clicou na opcao CERTA', !!ctx.escolhaCerta, true);
  checa('NAO clicou na opcao errada', !!ctx.escolhaErrada, false);
  checa('Avancar habilitou', ctx.doc.getElementById('avancar').getAttribute('aria-disabled'), 'false');
  checa('idempotente (3a volta)', ctx.fn('selecionar'), 'ja');
}

console.log('\n=== 2) Dropdown JA aberto (print 03) — a armadilha do wrapper ===');
{
  const ctx = telaNova({ jaAberta: true });
  const r = ctx.fn('selecionar');
  checa('escolhe direto', r, 'ok');
  checa('clicou na opcao CERTA', !!ctx.escolhaCerta, true);
  checa('NAO clicou no wrapper/opcao errada', !!ctx.escolhaErrada, false);
}

console.log('\n=== 3) Ja selecionado (print 04) ===');
{
  const ctx = montar(`
    <div role="dialog">
      <h2>Adicione seu número de telefone do WhatsApp</h2>
      <label>Telefone</label>
      <div role="combobox"><span>Use a display name with a virtual number instead</span></div>
      <div>Verificação adicional necessária</div>
      <div role="button">Avançar</div>
    </div>`);
  checa('reconhece como ja selecionado', ctx.fn('selecionar'), 'ja');
  checa('existe = true', ctx.fn('existe'), true);
}

console.log('\n=== 4) Layout ANTIGO terminal (sem opcao virtual) ===');
{
  const ctx = montar(`
    <div role="dialog">
      <h2>Adicione seu número de telefone do WhatsApp</h2>
      <p>Sua conta esta pronta.</p>
      <div role="button">Concluir</div>
    </div>`);
  checa('existe = false (tela e terminal)', ctx.fn('existe'), false);
  checa('selecionar nao acha nada', ctx.fn('selecionar'), '');
}

console.log('\n=== 5) Armadilha: seletor de conta no topo, sem campo Telefone ===');
{
  const ctx = montar(`
    <div role="button" id="trapConta">Adicione outra conta</div>
    <div role="dialog">
      <h2>Selecione os ativos de negócios</h2>
      <div role="button">Avançar</div>
    </div>`);
  let clicou = false;
  ctx.doc.getElementById('trapConta').addEventListener('click', () => { clicou = true; });
  ctx.fn('selecionar');
  checa('NAO tocou no seletor de conta', clicou, false);
  checa('existe = false', ctx.fn('existe'), false);
}

console.log(`\n${ok} passaram, ${falhou} falharam\n`);
process.exit(falhou ? 1 : 0);
