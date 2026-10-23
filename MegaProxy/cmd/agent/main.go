// MegaProxy Agent v2 — roda no celular. Autentica por token (AUTH -> OK), abre o
// túnel reverso e, por stream, ou DISCA o alvo pela 4G, ou executa #ROTATE (cicla o
// rádio p/ trocar o IP móvel). O IP de saída é o IP móvel do aparelho. Código próprio.
package main

import (
	"bufio"
	"context"
	"flag"
	"io"
	"log"
	"net"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/hashicorp/yamux"
)

var rotateCmd string

// ============================ DESEMPENHO DO TÚNEL ============================
// O gargalo do túnel NÃO é o rádio: é a janela do yamux. Throughput máximo de um
// stream = janela / RTT (produto banda×latência). Com o default de 256 KB e um
// RTT típico de celular→gateway (50–80 ms), o teto fica em ~26–41 Mbps — foi
// exatamente o que medimos (10–30 Mbps) num 5G que entrega ~1 Gbps direto.
// Com 16 MB de janela o teto sobe para a casa dos Gbps e o limite volta a ser o rádio.
const (
	streamWindow = 16 << 20 // 16 MB de janela por stream (era 256 KB)
	copyBuf      = 512 << 10 // 512 KB por syscall de cópia (era 32 KB)
)

func yamuxCfg() *yamux.Config {
	cfg := yamux.DefaultConfig()
	cfg.MaxStreamWindowSize = streamWindow
	cfg.EnableKeepAlive = true
	cfg.KeepAliveInterval = 15 * time.Second
	cfg.ConnectionWriteTimeout = 30 * time.Second
	cfg.LogOutput = io.Discard
	return cfg
}

// tuneTCP: desliga o algoritmo de Nagle (latência) e mantém o keepalive.
//
// ⚠️ NÃO chamar SetReadBuffer/SetWriteBuffer aqui. No Linux isso vira
// SO_RCVBUF/SO_SNDBUF, que (a) é TETADO por net.core.rmem_max/wmem_max — 208 KB
// no padrão da VPS — e (b) DESLIGA o auto-tuning do TCP, que sozinho cresceria
// até net.ipv4.tcp_rmem[max] (6 MB). Pedir 8 MB entregava 208 KB fixos e
// derrubava o throughput: a janela do yamux não adianta nada se o TCP embaixo
// só segura 208 KB em voo. Quem dimensiona os buffers é o kernel (sysctl).
func tuneTCP(c net.Conn) {
	tc, ok := c.(*net.TCPConn)
	if !ok {
		return
	}
	_ = tc.SetNoDelay(true)
	_ = tc.SetKeepAlive(true)
	_ = tc.SetKeepAlivePeriod(30 * time.Second)
}

// copyBig: cópia com buffer grande. io.Copy usa 32 KB, o que gera syscalls demais
// em link rápido. Passamos o buffer explícito, mas SEM envolver dst/src em
// wrappers: assim, quando o par implementa ReadFrom/WriteTo (ex.: TCPConn no
// Linux, que pode usar splice/zero-copy), o Go continua escolhendo esse caminho —
// que é mais rápido que copiar em userspace. O buffer vale para o resto.
func copyBig(dst io.Writer, src io.Reader) (int64, error) {
	buf := make([]byte, copyBuf)
	return io.CopyBuffer(dst, src, buf)
}

// halfClose: sinaliza fim de escrita sem derrubar a leitura (essencial p/ HTTP).
// Só age em quem REALMENTE suporta half-close (TCPConn). Em quem não suporta
// (o stream do yamux não tem CloseWrite) NÃO fecha nada: um Close() ali mataria
// o stream inteiro e cortaria a resposta em trânsito. Quem fecha é o defer.
func halfClose(c net.Conn) {
	type cw interface{ CloseWrite() error }
	if x, ok := c.(cw); ok {
		_ = x.CloseWrite()
	}
}

// No Android o /etc/resolv.conf aponta p/ ::1 (sem servidor) e o resolver puro-Go falha
// ("lookup ... on [::1]:53: connection refused"). Forçamos DNS público p/ TODAS as resoluções
// (gateway e alvos do proxy). A consulta sai pela rede do aparelho (4G).
func init() {
	dnsServers := []string{"1.1.1.1:53", "8.8.8.8:53", "1.0.0.1:53"}
	net.DefaultResolver = &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, address string) (net.Conn, error) {
			d := net.Dialer{Timeout: 5 * time.Second}
			var err error
			for _, s := range dnsServers {
				var c net.Conn
				if c, err = d.DialContext(ctx, "udp", s); err == nil {
					return c, nil
				}
			}
			return nil, err
		},
	}
}

func main() {
	gw := flag.String("gw", "2.25.147.134:30000", "endereço de controle do gateway")
	token := flag.String("token", "", "token do dispositivo (obrigatório)")
	// comando de rotação de IP (default: ciclo de dados móveis; alternativa: airplane).
	rc := flag.String("rotate", "svc data disable; sleep 8; svc data enable", "comando shell p/ trocar o IP")
	flag.Parse()
	rotateCmd = *rc
	log.SetOutput(os.Stdout)
	log.SetPrefix("[agent] ")
	log.SetFlags(log.LstdFlags | log.Lmsgprefix)
	if *token == "" {
		log.Fatal("faltou -token")
	}
	for {
		if err := run(*gw, *token); err != nil {
			log.Printf("sessão caiu: %v", err)
		}
		time.Sleep(3 * time.Second)
	}
}

func run(gw, token string) error {
	c, err := net.DialTimeout("tcp", gw, 15*time.Second)
	if err != nil {
		return err
	}
	defer c.Close()
	if _, err := c.Write([]byte("AUTH " + token + "\n")); err != nil {
		return err
	}
	c.SetReadDeadline(time.Now().Add(10 * time.Second))
	resp, err := bufio.NewReader(c).ReadString('\n')
	if err != nil {
		return err
	}
	if strings.TrimSpace(resp) != "OK" {
		log.Printf("gateway recusou: %s", strings.TrimSpace(resp))
		time.Sleep(10 * time.Second)
		return nil
	}
	c.SetReadDeadline(time.Time{})
	tuneTCP(c) // socket do túnel: NoDelay + buffers grandes
	sess, err := yamux.Server(c, yamuxCfg())
	if err != nil {
		return err
	}
	defer sess.Close()
	log.Printf("conectado ao gateway %s", gw)
	for {
		st, err := sess.Accept()
		if err != nil {
			return err
		}
		go handleStream(st)
	}
}

func handleStream(st net.Conn) {
	defer st.Close()
	br := bufio.NewReader(st)
	first, err := br.ReadString('\n')
	if err != nil {
		return
	}
	first = strings.TrimSpace(first)

	if first == "#ROTATE" {
		// Modo APP (Android): seccomp do sandbox mata fork/exec (SIGSYS). Então NÃO
		// rodamos shell — só emitimos o sinal e QUEM troca o IP é o app (acessibilidade → Modo Avião).
		if rotateCmd == "@signal" {
			log.Printf("__MP_ROTATE__")
			return
		}
		log.Printf("rotacionando IP...")
		// roda detachado do stream; o processo do agente sobrevive à queda da conexão
		// (que o próprio ciclo de rádio causa) e reconecta com o IP novo.
		go func() {
			out, _ := exec.Command("sh", "-c", rotateCmd).CombinedOutput()
			log.Printf("rotate: %s", strings.TrimSpace(string(out)))
		}()
		return
	}

	// senão, é um alvo host:port → disca pela 4G
	target := first
	if target == "" || !strings.Contains(target, ":") {
		return
	}
	outc, err := net.DialTimeout("tcp", target, 20*time.Second)
	if err != nil {
		log.Printf("falha ao discar %s: %v", target, err)
		return
	}
	defer outc.Close()
	tuneTCP(outc) // conexão de saída pela 4G/5G também tunada

	// Semântica ORIGINAL (libera na 1ª direção que termina). O ganho de velocidade
	// vem da janela do yamux e dos buffers — mexer no fechamento junto foi o que
	// derrubou o throughput.
	done := make(chan struct{}, 2)
	go func() { // cliente -> alvo
		copyBig(outc, br)
		halfClose(outc) // outc é TCP: avisa fim de upload ao alvo
		done <- struct{}{}
	}()
	go func() { // alvo -> cliente
		copyBig(st, outc)
		done <- struct{}{}
	}()
	<-done
}
