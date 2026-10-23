<#
========================================================================
 PUBLICAR UPDATE — MR Farm
========================================================================
 Publica a build no servidor e atualiza o `latest.json`.

 TUDO que e nome, versao e endereco vem da FONTE UNICA:
     server/marca.py     (nome, slug, autor, URL_API, URL_MAIL, URL_CDN)
     server/version.py   (APP_VERSION)

 FLUXO de uma nova versao:
   1. Edite server/version.py   ->  APP_VERSION = 'X.Y'
   2. Gere o .exe/.setup:  GERAR_TUDO_X64.bat
   3. Rode (na pasta update_server/):
          .\publicar_update.ps1 -Notes "novidades da versao"
   4. Pronto: o manifesto no servidor aponta para a versao nova.

 COMO SOBE: copia o pacote e o `latest.json` direto para o VPS via SCP.
 O VPS serve os arquivos em https://farm.mragencia.com/updates/.
========================================================================
#>
param(
    [string]$Notes = "",
    [bool]  $Mandatory = $true,

    [ValidateSet('auto','setup','zip')]
    [string]$Formato = "auto",

    [string]$Vps    = "2.24.86.116",
    [string]$Key    = "$env:USERPROFILE\.ssh\infra_vps",
    [string]$WebRoot = "/home/granasocial/htdocs/granasocial.tech/updates"
)

$ErrorActionPreference = "Stop"
function Info($m){ Write-Host "[publicar] $m" -ForegroundColor Cyan }
function Erro($m){ Write-Host "[ERRO] $m" -ForegroundColor Red }

$raiz = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Erro "Nao achei a .venv em '$raiz'. Rode PREPARAR_AMBIENTE_X64.bat antes."
    exit 1
}

# ---- valores da FONTE UNICA -------------------------------------------------
function _daFonte([string]$expr) {
    $v = & $py -c "import sys; sys.path.insert(0, r'$raiz'); from server import marca, version; print($expr)"
    if ($LASTEXITCODE -ne 0 -or -not $v) { Erro "Falha lendo a marca/versao de server/marca.py."; exit 1 }
    return ([string]($v | Select-Object -First 1)).Trim()
}
$versao  = _daFonte "version.APP_VERSION"
$slug    = _daFonte "marca.MARCA_SLUG"
$baseUrl = _daFonte "marca.URL_CDN"
$nomeFixo = "${slug}_Setup.exe"
Info "Versao $versao  |  pacote '$slug'  |  URL $baseUrl"
Info "Link fixo: $baseUrl/$nomeFixo  (sempre a ultima versao)"

# ---- o pacote ---------------------------------------------------------------
$setup    = Join-Path $raiz "release\setup\$($slug)_Setup_x64.exe"
$buildDir = Join-Path $raiz "release\app\x64\$slug"
$temSetup = Test-Path $setup
if ($Formato -eq 'setup' -and -not $temSetup) {
    Erro "Setup exigido mas nao encontrado: $setup  (rode instalador\GERAR_SETUP_X64.bat)"; exit 1
}
$usarSetup = ($Formato -eq 'setup') -or ($Formato -eq 'auto' -and $temSetup)

$tmp = Join-Path $env:TEMP ("publicar_" + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

if ($usarSetup) {
    $pacoteNome = "$($slug)_Setup_v$versao.exe"
    $pacote     = Join-Path $tmp $pacoteNome
    Info "Formato: SETUP. Copiando o instalador -> $pacoteNome"
    Copy-Item -LiteralPath $setup -Destination $pacote -Force
} else {
    $exe = Join-Path $buildDir "$slug.exe"
    if (-not (Test-Path $exe)) {
        Erro "Build do app nao encontrada em '$buildDir'  (rode GERAR_APP_X64.bat)"; exit 1
    }
    $pacoteNome = "$($slug)_v$versao.zip"
    $pacote     = Join-Path $tmp $pacoteNome
    Info "Formato: ZIP (onedir). Compactando '$buildDir' ..."
    Compress-Archive -Path (Join-Path $buildDir '*') -DestinationPath $pacote -CompressionLevel Optimal
}
$mb = [math]::Round((Get-Item $pacote).Length / 1MB, 1)
Info "Pacote: $pacoteNome ($mb MB)"

# ---- SHA-256 e manifesto ----------------------------------------------------
$sha = (Get-FileHash -Path $pacote -Algorithm SHA256).Hash.ToLower()
Info "SHA-256: $sha"

$manifest = [ordered]@{
    version   = $versao
    mandatory = [bool]$Mandatory
    url       = "$baseUrl/$pacoteNome`?v=$versao"
    sha256    = $sha
    notes     = $Notes
}
$json = Join-Path $tmp "latest.json"
[System.IO.File]::WriteAllText($json, ($manifest | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))
Info "latest.json gerado:"; Get-Content $json | Write-Host

# ---- sobe direto para o VPS (sem R2/CDN) ------------------------------------
$alvo   = "root@$Vps"
$sshOpt = @("-i", $Key, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new")

Info "Enviando pacote e manifesto para a VPS ($Vps)..."
& scp @sshOpt $pacote "${alvo}:$WebRoot/$pacoteNome"
if ($LASTEXITCODE -ne 0) { Erro "Falha no envio do pacote."; exit 1 }

& scp @sshOpt $pacote "${alvo}:$WebRoot/$nomeFixo"
if ($LASTEXITCODE -ne 0) { Erro "Falha no envio da copia com nome fixo."; exit 1 }

& scp @sshOpt $json "${alvo}:$WebRoot/latest.json"
if ($LASTEXITCODE -ne 0) { Erro "Falha no envio do latest.json."; exit 1 }

Info "Conferindo via HTTP..."
$remoto = @"
set -e
chown -R granasocial:granasocial '$WebRoot/'
echo '--- arquivos ---'
ls -lh '$WebRoot/'
echo '--- HTTP ---'
curl -sS -o /dev/null -w 'latest.json: %{http_code}\n' "$baseUrl/latest.json"
curl -sS -o /dev/null -w '${nomeFixo}: %{http_code}\n' "$baseUrl/$nomeFixo"
"@
& ssh @sshOpt $alvo $remoto
if ($LASTEXITCODE -ne 0) { Erro "Falha na conferencia HTTP."; exit 1 }

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
Info "OK! v$versao publicado."
Info "Manifesto : $baseUrl/latest.json"
Info "Pacote    : $baseUrl/$pacoteNome"
Info "Link fixo : $baseUrl/$nomeFixo   (sempre a ultima versao)"
Info "SHA-256   : $sha"
