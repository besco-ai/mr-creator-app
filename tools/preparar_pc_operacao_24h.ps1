<#
========================================================================
 PREPARAR PC PARA OPERACAO 24H - GS BM Creator
========================================================================
 Ajustes de SISTEMA OPERACIONAL para o bot rodar com N navegadores
 simultaneos por muitas horas sem que o Windows atrapalhe.

 Rode como ADMINISTRADOR. E idempotente: pode rodar quantas vezes quiser.

 O que faz:
   1) Energia (powercfg): DESLIGA a suspensao seletiva de USB em AC e DC
      (com ela ligada o Windows suspende o adaptador RNDIS e DERRUBA a
      ancoragem 4G no meio do lote), desativa PCIe ASPM, disco nunca
      desliga, e zera standby/hibernate/monitor no AC.
   2) Economia de energia OFF em CADA dispositivo USB (MSPower_DeviceEnable).
   3) Windows Defender: exclusoes de PASTA e de PROCESSO (o scan em tempo
      real dos perfis do AdsPower/Playwright custa MUITO I/O).
   4) Desktop heap (SharedSection) e cotas de handle GDI/USER. Precisa
      REINICIAR para valer.

 ATENCAO item 4: a chave SubSystems\Windows e lida pelo csrss.exe no boot.
 Um valor invalido IMPEDE O WINDOWS DE INICIAR. Por isso o script exporta
 a chave antes, le/grava via reg.exe (preservando REG_EXPAND_SZ e o
 %SystemRoot%) e so grava se o texto novo passar na validacao.

 OBS: este arquivo e 100% ASCII de proposito. O PowerShell 5.1 le .ps1 sem
 BOM como ANSI e acento/travessao quebram o parser.
========================================================================
#>

[CmdletBinding()]
param(
    # Nao mexer no registro (itens de boot) - so energia/USB/Defender.
    [switch]$PularRegistro,
    # Pasta do projeto a excluir no Defender. Padrao: a pasta acima de tools\.
    [string]$PastaProjeto = ""
)

$ErrorActionPreference = 'Continue'

function Titulo($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Ok($m)     { Write-Host "  [OK]    $m" -ForegroundColor Green }
function Aviso($m)  { Write-Host "  [AVISO] $m" -ForegroundColor Yellow }
function Erro($m)   { Write-Host "  [ERRO]  $m" -ForegroundColor Red }

# --- Administrador? -----------------------------------------------------
$id  = [Security.Principal.WindowsIdentity]::GetCurrent()
$pri = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $pri.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Erro "Rode este script como ADMINISTRADOR (botao direito > Executar como administrador)."
    exit 1
}

if ($PastaProjeto -eq "") { $PastaProjeto = Split-Path -Parent $PSScriptRoot }
$precisaReiniciar = $false

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " PREPARAR PC PARA OPERACAO 24H - GS BM Creator" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Projeto: $PastaProjeto"

# ========================================================================
# 1) ENERGIA (powercfg)
# ========================================================================
Titulo "1/4 Energia (powercfg)"

# GUIDs oficiais dos subgrupos/settings usados aqui.
$SUB_USB      = '2a737441-1930-4402-8d77-b2bebba308a3'   # Configuracoes USB
$SET_USB_SUSP = '48e6b7a6-50f5-4782-a5d4-53bb8f07e226'   # Suspensao seletiva USB
$SUB_PCI      = '501a4d13-42af-4429-9fd1-a8218c268e20'   # PCI Express
$SET_ASPM     = 'ee12f906-d277-404b-b6da-e5fa1a576df5'   # Gerenciamento de energia do estado do link
$SUB_DISCO    = '0012ee47-9041-4b5d-9b77-535fba8b1442'   # Disco rigido
$SET_DISCO_OFF= '6738e2c4-e8a5-4a42-b16a-e040e769756e'   # Desligar disco apos

function SetPower($sub, $setting, $valor, $rotulo) {
    # AC (na tomada) e DC (bateria) - o powercfg falha silencioso se o
    # setting nao existir naquele hardware; tratamos como aviso.
    & powercfg /SETACVALUEINDEX SCHEME_CURRENT $sub $setting $valor | Out-Null
    $rcAc = $LASTEXITCODE
    & powercfg /SETDCVALUEINDEX SCHEME_CURRENT $sub $setting $valor | Out-Null
    $rcDc = $LASTEXITCODE
    if ($rcAc -eq 0) { Ok "$rotulo (AC=$valor, DC=$valor)" }
    else { Aviso "$rotulo nao aplicado (setting ausente neste hardware)" }
}

# CRITICO: suspensao seletiva de USB DESABILITADA (indice 0).
SetPower $SUB_USB   $SET_USB_SUSP  0 "USB selective suspend DESABILITADO"
SetPower $SUB_PCI   $SET_ASPM      0 "PCIe ASPM desativado"
SetPower $SUB_DISCO $SET_DISCO_OFF 0 "Disco rigido nunca desliga"

& powercfg /CHANGE standby-timeout-ac 0   | Out-Null
& powercfg /CHANGE hibernate-timeout-ac 0 | Out-Null
& powercfg /CHANGE monitor-timeout-ac 0   | Out-Null
& powercfg /CHANGE disk-timeout-ac 0      | Out-Null
Ok "Standby / hibernate / monitor / disco = 0 (nunca) no AC"

& powercfg /SETACTIVE SCHEME_CURRENT | Out-Null
Ok "Plano de energia reaplicado"

# ========================================================================
# 2) ECONOMIA DE ENERGIA OFF EM CADA DISPOSITIVO USB
# ========================================================================
Titulo "2/4 Economia de energia por dispositivo USB"

try {
    $devs = Get-CimInstance -ClassName MSPower_DeviceEnable -Namespace root\wmi -ErrorAction Stop
    $mudou = 0; $jaOk = 0; $falhou = 0
    foreach ($d in $devs) {
        if ($d.Enable -eq $false) { $jaOk++; continue }
        try {
            Set-CimInstance -InputObject $d -Property @{ Enable = $false } -ErrorAction Stop
            $mudou++
        } catch { $falhou++ }
    }
    Ok "Dispositivos: $mudou desligados agora, $jaOk ja estavam, $falhou recusaram"
    if ($falhou -gt 0) { Aviso "Os que recusaram nao suportam o ajuste - normal." }
} catch {
    Aviso "Nao consegui ler MSPower_DeviceEnable: $($_.Exception.Message)"
}

# ========================================================================
# 3) WINDOWS DEFENDER - EXCLUSOES
# ========================================================================
Titulo "3/4 Windows Defender (exclusoes)"

$pastas = @(
    $PastaProjeto,
    (Join-Path $env:APPDATA   'adspower_global'),
    (Join-Path $env:LOCALAPPDATA 'ms-playwright'),
    'C:\Program Files\GS BM Creator'
)
$processos = @(
    'python.exe', 'pythonw.exe', 'GS BM Creator.exe',
    'AdsPower Global.exe', 'SunBrowser.exe', 'chrome.exe',
    'adb.exe', 'node.exe'
)

if (-not (Get-Command Add-MpPreference -ErrorAction SilentlyContinue)) {
    Aviso "Cmdlets do Defender indisponiveis (outro antivirus ativo?) - pulando."
} else {
    try {
        $atual = Get-MpPreference -ErrorAction Stop
        $pathsAtuais = @($atual.ExclusionPath)
        $procsAtuais = @($atual.ExclusionProcess)
    } catch {
        $pathsAtuais = @(); $procsAtuais = @()
    }
    foreach ($p in $pastas) {
        if ($pathsAtuais -contains $p) { Ok "pasta ja excluida: $p"; continue }
        try { Add-MpPreference -ExclusionPath $p -ErrorAction Stop; Ok "pasta excluida: $p" }
        catch { Aviso "falhou pasta $p : $($_.Exception.Message)" }
    }
    foreach ($p in $processos) {
        if ($procsAtuais -contains $p) { Ok "processo ja excluido: $p"; continue }
        try { Add-MpPreference -ExclusionProcess $p -ErrorAction Stop; Ok "processo excluido: $p" }
        catch { Aviso "falhou processo $p : $($_.Exception.Message)" }
    }
}

# ========================================================================
# 4) DESKTOP HEAP + COTAS DE HANDLE  (PRECISA REINICIAR)
# ========================================================================
Titulo "4/4 Desktop heap e cotas de handle (registro)"

if ($PularRegistro) {
    Aviso "-PularRegistro informado: nada foi alterado no registro."
} else {

$keySub  = 'HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\SubSystems'
$keyQuota= 'HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows'

# --- 4.0) BACKUP obrigatorio da chave antes de tocar em qualquer coisa ---
$dirBk = Join-Path $PSScriptRoot 'backup_registro'
if (-not (Test-Path $dirBk)) { New-Item -ItemType Directory -Path $dirBk -Force | Out-Null }
$carimbo = (Get-Date).ToString('yyyyMMdd_HHmmss')
$bkSub   = Join-Path $dirBk "SubSystems_$carimbo.reg"
$bkQuota = Join-Path $dirBk "WindowsQuotas_$carimbo.reg"
& reg export $keySub   "$bkSub"   /y | Out-Null
if ($LASTEXITCODE -ne 0) { Erro "Nao consegui exportar backup de SubSystems - ABORTANDO item 4."; $bkSub = $null }
& reg export $keyQuota "$bkQuota" /y | Out-Null

if ($bkSub) {
    Ok "Backup: $bkSub"

    # --- 4.1) LER o valor Windows via reg query -------------------------
    # ARMADILHA: Get-ItemProperty devolve %SystemRoot% JA EXPANDIDO e
    # Set-ItemProperty -Type MultiString TROCA o tipo do valor. Por isso
    # lemos e gravamos com reg.exe, que preserva o texto e o REG_EXPAND_SZ.
    $saida = & reg query $keySub /v Windows 2>$null
    $linha = $saida | Where-Object { $_ -match 'REG_EXPAND_SZ' } | Select-Object -First 1

    if (-not $linha) {
        Erro "Valor 'Windows' REG_EXPAND_SZ nao encontrado - nada alterado."
    } else {
        # Formato: "    Windows    REG_EXPAND_SZ    %SystemRoot%\system32\csrss.exe ..."
        $idx = $linha.IndexOf('REG_EXPAND_SZ')
        $atual = $linha.Substring($idx + 'REG_EXPAND_SZ'.Length).Trim()

        # ARMADILHA 2: -match em array NAO popula $Matches. Aqui $atual e
        # uma STRING unica, entao o regex abaixo e confiavel.
        $mm = [regex]::Match($atual, 'SharedSection=(\d+),(\d+),(\d+)')
        if (-not $mm.Success) {
            Erro "Nao achei SharedSection no valor atual - nada alterado."
        } elseif ([int]$mm.Groups[2].Value -ge 40960) {
            Ok "SharedSection ja esta em $($mm.Groups[2].Value) - nada a fazer."
        } else {
            $novo = [regex]::Replace(
                $atual,
                'SharedSection=(\d+),(\d+),(\d+)',
                { param($m) "SharedSection=$($m.Groups[1].Value),40960,$($m.Groups[3].Value)" },
                1)

            # --- 4.2) VALIDACAO ANTES DE GRAVAR (valor invalido = PC NAO liga) ---
            $valido = ($novo -match 'SharedSection=\d+,40960,\d+') -and ($novo -match 'csrss\.exe')
            if (-not $valido) {
                Erro "Texto novo NAO passou na validacao - ABORTADO, nada foi gravado."
                Write-Host "        gerado: $novo"
            } else {
                & reg add $keySub /v Windows /t REG_EXPAND_SZ /d "$novo" /f | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Erro "reg add falhou. Restaure com: reg import `"$bkSub`""
                } else {
                    # --- 4.3) CONFERENCIA pos-gravacao ---------------------
                    $conf  = & reg query $keySub /v Windows 2>$null
                    $lConf = $conf | Where-Object { $_ -match 'REG_EXPAND_SZ' } | Select-Object -First 1
                    $txt   = if ($lConf) { $lConf.Substring($lConf.IndexOf('REG_EXPAND_SZ') + 13).Trim() } else { "" }
                    $okTipo = [bool]$lConf
                    $okVars = ($txt -match '%SystemRoot%') -and ($txt -match 'SharedSection=1024,40960,768') -and ($txt -match 'csrss\.exe')
                    if ($okTipo -and $okVars) {
                        Ok "SharedSection -> 1024,40960,768 (tipo REG_EXPAND_SZ preservado)"
                        $precisaReiniciar = $true
                    } else {
                        Erro "CONFERENCIA FALHOU! Restaure JA: reg import `"$bkSub`""
                        Write-Host "        lido de volta: $txt"
                    }
                }
            }
        }
    }

    # --- 4.4) Cotas de handle GDI/USER -------------------------------------
    foreach ($q in @(@{n='GDIProcessHandleQuota';v=20000}, @{n='USERProcessHandleQuota';v=18000})) {
        $atualQ = $null
        $sq = & reg query $keyQuota /v $($q.n) 2>$null
        $lq = $sq | Where-Object { $_ -match 'REG_DWORD' } | Select-Object -First 1
        if ($lq -and ($lq -match '0x([0-9a-fA-F]+)')) { $atualQ = [Convert]::ToInt32($Matches[1], 16) }
        if ($atualQ -eq $q.v) { Ok "$($q.n) ja = $($q.v)"; continue }
        & reg add $keyQuota /v $($q.n) /t REG_DWORD /d $($q.v) /f | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok "$($q.n) = $($q.v) (era $atualQ)"; $precisaReiniciar = $true }
        else { Erro "Falha ao gravar $($q.n)" }
    }
}

}  # fim -PularRegistro

# ========================================================================
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " CONCLUIDO" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
if ($precisaReiniciar) {
    Write-Host " REINICIE O PC para o desktop heap / cotas valerem." -ForegroundColor Yellow
} else {
    Write-Host " Nenhuma alteracao de boot pendente." -ForegroundColor Green
}
Write-Host ""
