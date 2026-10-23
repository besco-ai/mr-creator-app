# Auto-atualização do aplicativo

O app checa, **no start (antes de abrir a GUI)**, se há uma versão mais nova publicada e, se
houver, **baixa, valida o SHA-256, aplica e se relança**. O usuário roda sempre a versão nova,
sem receber nada à mão.

## De onde vem cada coisa (FONTE ÚNICA)

| O quê | Onde |
|---|---|
| Nome, autor, domínio e endereços (API, e-mail, CDN) | **`server/marca.py`** |
| Versão | **`server/version.py`** (`APP_VERSION`) |
| Manifesto (o arquivo que o app lê) | `https://farm.mragencia.com/updates/latest.json` |
| Pacote do app | `https://farm.mragencia.com/updates/<slug>...` |
| Quem baixa e aplica | `server/atualizador.py` (chamado pelo `main.py`) |

⇒ trocar marca ou domínio = **editar `server/marca.py` e reconstruir**. Nada de sair
procurando nome/endereço pelo código.

## Publicar uma versão nova

1. `server/version.py` → `APP_VERSION = 'X.Y'` (o `ATUALIZAR_E_PUBLICAR.bat` sobe sozinho).
2. Gere o app e o instalador (`GERAR_TUDO_X64.bat`).
3. Publique (na pasta `update_server/`):
   ```powershell
   .\publicar_update.ps1 -Notes "novidades da versão"
   ```
4. Pronto: quem abrir a versão antiga baixa e aplica sozinho.

> O `-Versao` deixou de existir como parâmetro: a versão vem de `server/version.py`, e o nome
> vem de `server/marca.py` — assim não existe publicar com versão vazia ou nome trocado.

## Como a publicação sobe

```
publicar_update.ps1
   ├── lê nome/versão/endereços da FONTE ÚNICA (pelo Python da .venv)
   ├── escolhe o pacote (o SETUP do Inno; senão o onedir em .zip)
   ├── calcula o SHA-256 e gera o latest.json  (UTF-8 SEM BOM)
   ├── scp  ->  VPS (chave SSH; não usa senha)
   └── rclone (remote `r2`) -> balde  ->  servido em https://farm.mragencia.com/updates/
```

## Formato do manifest (`latest.json`)

```json
{
  "version": "2.7",
  "mandatory": true,
  "url": "https://farm.mragencia.com/updates/MR_Farm_Setup_v2.7.exe?v=2.7",
  "sha256": "<sha-256 do pacote>",
  "notes": "texto das novidades"
}
```

- `version`: comparada com a local — **maior** = atualiza.
- `sha256`: integridade; o cliente valida antes de aplicar.
- `?v=<versão>`: chave de cache própria (evita servir um objeto parcial/velho cacheado).
- `mandatory`: reservado para política de obrigatoriedade futura.

## Segurança / o que não fazer

- A publicação usa **chave SSH** (`~/.ssh/infra_vps`) — **não existe** senha em arquivo
  (`.senha_vps.txt`) neste fluxo; não crie esse arquivo.
- **Nunca** versione o `latest.json` gerado nem a chave SSH.
- O pacote e o manifesto **não** passam por servidor de terceiro: sobem pela nossa VPS, direto
  para o nosso balde.
- O `.zip` do onedir (quando usado) traz os arquivos na **raiz** e a atualização aplica por cima
  **sem** apagar `logs/` nem as configurações do usuário.