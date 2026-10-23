// MegaProxy Gateway v2 — multi-device. Cada celular (agente) autentica por TOKEN,
// ganha uma credencial de proxy (user:pass) na porta única de proxy, tem tráfego
// medido e pode ter o IP rotacionado. Um API de CONTROLE (admin) deixa o painel do
// MegaGrana criar/listar/rotacionar/remover devices. Código próprio.
package main

import (
	"bufio"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/hashicorp/yamux"
)

type Device struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Token     string `json:"token"`      // o agente usa no AUTH
	ProxyUser string `json:"proxy_user"` // credencial de proxy (username)
	ProxyPass string `json:"proxy_pass"`
	BytesIn   int64  `json:"bytes_in"`
	BytesOut  int64  `json:"bytes_out"`
	CreatedAt int64  `json:"created_at"`

	// runtime (não persistido)
	sess   *yamux.Session `json:"-"`
	online bool           `json:"-"`
	lastIP string         `json:"-"`
}

type Registry struct {
	mu   sync.RWMutex
	byID map[string]*Device
	byTk map[string]*Device
	byPU map[string]*Device
	path string
}

func newRegistry(path string) *Registry {
	r := &Registry{byID: map[string]*Device{}, byTk: map[string]*Device{}, byPU: map[string]*Device{}, path: path}
	r.load()
	return r
}
func (r *Registry) load() {
	b, err := os.ReadFile(r.path)
	if err != nil {
		return
	}
	var list []*Device
	if json.Unmarshal(b, &list) != nil {
		return
	}
	for _, d := range list {
		r.byID[d.ID] = d
		r.byTk[d.Token] = d
		r.byPU[d.ProxyUser] = d
	}
	log.Printf("registry: %d device(s) carregado(s)", len(list))
}
func (r *Registry) save() {
	list := make([]*Device, 0, len(r.byID))
	for _, d := range r.byID {
		list = append(list, d)
	}
	b, _ := json.MarshalIndent(list, "", "  ")
	tmp := r.path + ".tmp"
	os.WriteFile(tmp, b, 0600)
	os.Rename(tmp, r.path)
}
func randHex(n int) string { b := make([]byte, n); rand.Read(b); return fmt.Sprintf("%x", b) }

func (r *Registry) create(name string) *Device {
	r.mu.Lock()
	defer r.mu.Unlock()
	d := &Device{
		ID: randHex(8), Name: name, Token: randHex(20),
		ProxyUser: "mp" + randHex(4), ProxyPass: randHex(8), CreatedAt: time.Now().Unix(),
	}
	r.byID[d.ID] = d
	r.byTk[d.Token] = d
	r.byPU[d.ProxyUser] = d
	r.save()
	return d
}
func (r *Registry) del(id string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	d := r.byID[id]
	if d == nil {
		return false
	}
	if d.sess != nil {
		d.sess.Close()
	}
	delete(r.byID, id)
	delete(r.byTk, d.Token)
	delete(r.byPU, d.ProxyUser)
	r.save()
	return true
}
func (r *Registry) byToken(t string) *Device  { r.mu.RLock(); defer r.mu.RUnlock(); return r.byTk[t] }
func (r *Registry) byProxyUser(u string) *Device { r.mu.RLock(); defer r.mu.RUnlock(); return r.byPU[u] }
func (r *Registry) byId(id string) *Device     { r.mu.RLock(); defer r.mu.RUnlock(); return r.byID[id] }

var reg *Registry

func main() {
	ctrl := flag.String("ctrl", ":30000", "porta de controle (agentes dialam)")
	proxy := flag.String("proxy", ":31001", "porta única de proxy (clientes, com user:pass)")
	admin := flag.String("admin", "127.0.0.1:32000", "API de controle p/ o painel")
	adminKey := flag.String("adminkey", "changeme-admin", "chave da API de controle")
	store := flag.String("store", "/root/MegaProxy/devices.json", "arquivo do registro de devices")
	flag.Parse()
	log.SetPrefix("[gw] ")
	log.SetFlags(log.LstdFlags | log.Lmsgprefix)
	reg = newRegistry(*store)

	go serveAdmin(*admin, *adminKey)
	go serveProxy(*proxy)
	serveControl(*ctrl)
}

// ================= AGENTES (túnel reverso) =================
func serveControl(addr string) {
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("control listen: %v", err)
	}
	log.Printf("control em %s", addr)
	for {
		c, err := ln.Accept()
		if err != nil {
			continue
		}
		go handleAgent(c)
	}
}
func handleAgent(c net.Conn) {
	_ = c.SetReadDeadline(time.Now().Add(10 * time.Second))
	line, err := bufio.NewReader(c).ReadString('\n')
	if err != nil {
		c.Close()
		return
	}
	tok := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(line), "AUTH "))
	d := reg.byToken(tok)
	if d == nil {
		c.Write([]byte("ERR token invalido\n"))
		c.Close()
		return
	}
	c.Write([]byte("OK\n"))
	_ = c.SetReadDeadline(time.Time{})
	tuneTCP(c) // socket do túnel: NoDelay + buffers grandes
	sess, err := yamux.Client(c, yamuxCfg())
	if err != nil {
		c.Close()
		return
	}
	ip := c.RemoteAddr().String()
	if h, _, e := net.SplitHostPort(ip); e == nil {
		ip = h
	}
	d.sess = sess
	d.online = true
	d.lastIP = ip
	log.Printf("device ONLINE %s (%s) ip=%s", d.ID, d.Name, ip)
	<-sess.CloseChan()
	if d.sess == sess {
		d.sess = nil
		d.online = false
	}
	log.Printf("device OFFLINE %s", d.ID)
}

// ================= CLIENTES (proxy HTTP com auth) =================
func serveProxy(addr string) {
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("proxy listen: %v", err)
	}
	log.Printf("proxy em %s", addr)
	for {
		c, err := ln.Accept()
		if err != nil {
			continue
		}
		go handleClient(c)
	}
}
// resolveHP resolve o HOST de "host:port" p/ IP no lado do gateway (VPS), pra o agente
// NÃO precisar de DNS no telefone — muitas redes móveis bloqueiam DNS externo (UDP 53).
// Prefere IPv4 (saída pelo IPv4 4G do aparelho). Fallback: devolve o host original.
func resolveHP(hp string) string {
	host, port, err := net.SplitHostPort(hp)
	if err != nil {
		return hp
	}
	if net.ParseIP(host) != nil {
		return hp
	}
	ips, err := net.LookupHost(host)
	if err != nil || len(ips) == 0 {
		return hp
	}
	for _, ip := range ips {
		if strings.Contains(ip, ".") {
			return net.JoinHostPort(ip, port)
		}
	}
	return net.JoinHostPort(ips[0], port)
}

func handleClient(c net.Conn) {
	defer c.Close()
	br := bufio.NewReader(c)
	reqLine, err := br.ReadString('\n')
	if err != nil {
		return
	}
	parts := strings.Fields(reqLine)
	if len(parts) < 3 {
		return
	}
	method, target, ver := parts[0], parts[1], parts[2]
	var headers []string
	var auth string
	for {
		h, err := br.ReadString('\n')
		if err != nil {
			return
		}
		if strings.HasPrefix(strings.ToLower(h), "proxy-authorization:") {
			auth = strings.TrimSpace(h[len("proxy-authorization:"):])
		} else {
			headers = append(headers, h) // repassa os demais (tira o Proxy-Authorization)
		}
		if strings.TrimSpace(h) == "" {
			break
		}
	}

	d := authDevice(auth)
	if d == nil {
		c.Write([]byte("HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm=\"MegaProxy\"\r\n\r\n"))
		return
	}
	if d.sess == nil {
		c.Write([]byte("HTTP/1.1 502 Bad Gateway\r\n\r\ndispositivo offline\r\n"))
		return
	}
	st, err := d.sess.Open()
	if err != nil {
		c.Write([]byte("HTTP/1.1 502 Bad Gateway\r\n\r\n"))
		return
	}
	defer st.Close()

	if strings.EqualFold(method, "CONNECT") {
		hp := target
		if !strings.Contains(hp, ":") {
			hp += ":443"
		}
		fmt.Fprintf(st, "%s\n", resolveHP(hp))
		c.Write([]byte("HTTP/1.1 200 Connection Established\r\n\r\n"))
		pipeMeter(c, br, st, d)
		return
	}
	u := strings.TrimPrefix(target, "http://")
	hp := u
	path := "/"
	if s := strings.IndexByte(u, '/'); s >= 0 {
		hp = u[:s]
		path = u[s:]
	}
	if !strings.Contains(hp, ":") {
		hp += ":80"
	}
	fmt.Fprintf(st, "%s\n", resolveHP(hp))
	fmt.Fprintf(st, "%s %s %s\r\n", method, path, ver)
	for _, h := range headers {
		st.Write([]byte(h))
	}
	pipeMeter(c, br, st, d)
}
func authDevice(authHeader string) *Device {
	f := strings.Fields(authHeader)
	if len(f) != 2 || !strings.EqualFold(f[0], "Basic") {
		return nil
	}
	raw, err := base64.StdEncoding.DecodeString(f[1])
	if err != nil {
		return nil
	}
	up := strings.SplitN(string(raw), ":", 2)
	if len(up) != 2 {
		return nil
	}
	d := reg.byProxyUser(up[0])
	if d == nil || d.ProxyPass != up[1] {
		return nil
	}
	return d
}
// ============================ DESEMPENHO DO TÚNEL ============================
// Ver a nota no agent: o teto de banda de um stream é janela/RTT. O default do
// yamux (256 KB) limitava o link a ~26–41 Mbps mesmo com 5G de ~1 Gbps.
const (
	streamWindow = 16 << 20  // 16 MB de janela por stream (era 256 KB)
	copyBufSize  = 512 << 10 // 512 KB por syscall de cópia (era 32 KB)
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

// ⚠️ NÃO chamar SetReadBuffer/SetWriteBuffer: vira SO_RCVBUF/SO_SNDBUF, é tetado
// por net.core.rmem_max/wmem_max (208 KB no padrão) e DESLIGA o auto-tuning do
// TCP. Pedir 8 MB entregava 208 KB fixos e estrangulava o túnel. Buffer é papel
// do kernel — ver /etc/sysctl.d/99-megaproxy.conf.
func tuneTCP(c net.Conn) {
	tc, ok := c.(*net.TCPConn)
	if !ok {
		return
	}
	_ = tc.SetNoDelay(true)
	_ = tc.SetKeepAlive(true)
	_ = tc.SetKeepAlivePeriod(30 * time.Second)
}

// Buffer explícito SEM wrappers: preserva os caminhos otimizados do Go
// (ReadFrom/WriteTo, splice no Linux) quando disponíveis.
func copyBig(dst io.Writer, src io.Reader) (int64, error) {
	buf := make([]byte, copyBufSize)
	return io.CopyBuffer(dst, src, buf)
}

// halfClose: só sinaliza fim de escrita em quem REALMENTE suporta half-close
// (TCPConn). Para os demais (ex.: stream do yamux, que não tem CloseWrite),
// NÃO fecha nada — chamar Close() ali derrubaria o stream inteiro e cortaria a
// resposta em trânsito. Quem fecha é o defer do chamador, no fim.
func halfClose(c net.Conn) {
	type cw interface{ CloseWrite() error }
	if x, ok := c.(cw); ok {
		_ = x.CloseWrite()
	}
}

func pipeMeter(c net.Conn, br *bufio.Reader, st net.Conn, d *Device) {
	tuneTCP(c)
	// Semântica IDÊNTICA à original (libera na 1ª direção que termina). O ganho
	// de velocidade vem da janela do yamux e dos buffers, NÃO daqui — misturar as
	// duas mudanças foi o que causou a regressão de throughput.
	done := make(chan struct{}, 2)
	go func() { n, _ := copyBig(st, br); atomic.AddInt64(&d.BytesOut, n); done <- struct{}{} }()
	go func() { n, _ := copyBig(c, st); atomic.AddInt64(&d.BytesIn, n); done <- struct{}{} }()
	<-done
}

// ================= API DE CONTROLE (painel MegaGrana) =================
func serveAdmin(addr, key string) {
	mux := http.NewServeMux()
	guard := func(h http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("X-Admin-Key") != key {
				http.Error(w, "forbidden", 403)
				return
			}
			h(w, r)
		}
	}
	mux.HandleFunc("/devices", guard(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			var body struct{ Name string `json:"name"` }
			json.NewDecoder(r.Body).Decode(&body)
			if body.Name == "" {
				body.Name = "Dispositivo"
			}
			d := reg.create(body.Name)
			writeJSON(w, deviceView(d))
			return
		}
		reg.mu.RLock()
		out := make([]map[string]any, 0, len(reg.byID))
		for _, d := range reg.byID {
			out = append(out, deviceView(d))
		}
		reg.mu.RUnlock()
		writeJSON(w, out)
	}))
	mux.HandleFunc("/device/rotate", guard(func(w http.ResponseWriter, r *http.Request) {
		d := reg.byId(r.URL.Query().Get("id"))
		if d == nil {
			http.Error(w, "not found", 404)
			return
		}
		if d.sess == nil {
			writeJSON(w, map[string]any{"ok": false, "msg": "device offline"})
			return
		}
		st, err := d.sess.Open()
		if err != nil {
			writeJSON(w, map[string]any{"ok": false, "msg": err.Error()})
			return
		}
		fmt.Fprint(st, "#ROTATE\n")
		st.Close()
		writeJSON(w, map[string]any{"ok": true, "msg": "rotação solicitada"})
	}))
	mux.HandleFunc("/device/delete", guard(func(w http.ResponseWriter, r *http.Request) {
		ok := reg.del(r.URL.Query().Get("id"))
		writeJSON(w, map[string]any{"ok": ok})
	}))
	log.Printf("admin API em %s", addr)
	http.ListenAndServe(addr, mux)
}
func deviceView(d *Device) map[string]any {
	return map[string]any{
		"id": d.ID, "name": d.Name, "token": d.Token,
		"proxy_user": d.ProxyUser, "proxy_pass": d.ProxyPass,
		"online": d.online, "ip": d.lastIP,
		"bytes_in": atomic.LoadInt64(&d.BytesIn), "bytes_out": atomic.LoadInt64(&d.BytesOut),
		"created_at": d.CreatedAt,
	}
}
func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}
