# GS Creator 2026 — app desktop (GS BM Creator)

Aplicativo desktop (Windows) que importa perfis Facebook do painel GranaSocial, cria
navegadores (iXBrowser / AdsPower) e automatiza a criação de Business Manager na Meta.

Fonte: migração do projeto original em `GS Creator 2026\` (backup). Este repositório
guarda **só o código** — nenhum binário, nenhum arquivo de sessão e **nenhuma
credencial**.

## Estrutura

| Caminho | O que é |
|---|---|
| `main.py` | Entrada do app (pywebview → `client/index.html`) |
| `server/` | Regras de negócio: backend, automação FB, BM, WABA, SMS, captcha, proxies, validador de `.txt` |
| `client/` | Interface (HTML/CSS/JS carregada pelo pywebview) |
| `admin_usuarios.py` | Ferramenta Tkinter de administração de usuários no MySQL |
| `MegaProxy/` | Utilitário em Go |
| `scratchpad/`, `dc_*.py`, `tb_*.py` | Scripts de teste/inspeção |
| `instalador/`, `update_server/` | Scripts de empacotamento (Inno Setup) e de publicação de update |

## Rodar

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Build do executável: `GERAR_APP_X64.bat` (PyInstaller, usa `FB_Profile_Manager.spec`).

## Credenciais (variáveis de ambiente)

O código **não** traz chave nenhuma. Configure no ambiente antes de rodar:

| Variável | Usada por | Observação |
|---|---|---|
| `GS_DB_HOST` / `GS_DB_PORT` / `GS_DB_USER` / `GS_DB_PASS` / `GS_DB_NAME` | `admin_usuarios.py` | acesso direto ao MySQL (admin) |
| `GSMAILS_API_KEY` | `server/gsmails_integration.py` | chave da API privada do gsmails |
| `GS_HMAC_KEY` | `server/gs_txt_validator.py` | **valor idêntico** ao `BMCREATOR_HMAC_KEY` do painel PHP |
| `GSMAILS_ENABLED`, `GSMAILS_BASE_URL` | `server/gsmails_integration.py` | opcionais |

> `GS_HMAC_KEY` é a chave que assina/valida os `.txt` (GS-SIG) entregues pelo painel.
> Sem ela, a validação de assinatura não funciona — defina o **mesmo** valor dos dois lados.

## O que ficou fora deste repositório

- `config/` — configuração de runtime e perfis locais (contém dados de sessão)
- `hl_session_full.json`, `conta_fb_*.txt` — cookies/sessões e contas
- `certificado/` — PDFs de verificação
- instaladores `*.exe`, `release/`, `_PORTATIL/`, `build/`, `dist/`, `.venv/`

> As 3 sementes de config que o `FB_Profile_Manager.spec` embalava
> (`automacao_config.json`, `perfil_EXEMPLO.json`, `perfil_SKIP_WARMUP.json`) viviam em
> `config/`, que fica fora do repo — o build as inclui só `if exists`, então a ausência
> não quebra o PyInstaller (o config operacional nasce ao lado do `.exe` no 1º run).

> A documentação interna do projeto (memória do autor original, 249 arquivos) **não** foi
> versionada: é um acervo de notas com credenciais vivas de fornecedores. Ficou arquivada
> fora do git em `C:\Users\samue\dev\gs-creator-docs-nogit\`.