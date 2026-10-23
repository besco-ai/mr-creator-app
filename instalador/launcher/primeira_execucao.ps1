$ErrorActionPreference = 'Stop'

function Write-LauncherLog($message) {
    try {
        $base = Split-Path -Parent $PSCommandPath
        $logs = Join-Path (Split-Path -Parent $base) 'logs'
        New-Item -ItemType Directory -Force -Path $logs | Out-Null
        $logFile = Join-Path $logs 'launcher.log'
        Add-Content -Path $logFile -Value ("$(Get-Date -Format s) " + $message)
    } catch {}
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$launcherDir = Split-Path -Parent $PSCommandPath
$baseDir = Split-Path -Parent $launcherDir
# [FIX 2026-07-17] O executavel do app se chama 'GS BM Creator.exe' (nome novo). O
# launcher antigo procurava 'GS_FB Creator.exe' -> dava "nao encontrado" no atalho.
# O nome do exe vem do build (marca vem de server/marca.py no build); aqui nao
# ha Python no cliente, entao NAO se cita marca: procura o .exe do app.
$appExe = Join-Path $baseDir 'app.exe'
# Blindagem contra rename futuro: se o nome mudar, acha o UNICO .exe do app na pasta
# (ignora o unins*.exe do desinstalador do Inno) -> nunca mais quebra por nome.
if (-not (Test-Path $appExe)) {
    $cand = Get-ChildItem -Path $baseDir -Filter '*.exe' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike 'unins*.exe' } | Select-Object -First 1
    if ($cand) { $appExe = $cand.FullName }
}

function Get-DotNetRelease {
    try {
        $item = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release -ErrorAction Stop
        return [int]$item.Release
    } catch { return 0 }
}

function Test-WebView2Installed {
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
        'HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
        'HKCU:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    )
    foreach ($path in $paths) {
        try {
            $pv = (Get-ItemProperty -Path $path -Name pv -ErrorAction Stop).pv
            if ($pv -and $pv -ne '0.0.0.0') { return $true }
        } catch {}
    }
    return $false
}

function Test-VCRedistInstalled {
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
    )
    foreach ($path in $paths) {
        try {
            $installed = (Get-ItemProperty -Path $path -Name Installed -ErrorAction Stop).Installed
            if ($installed -eq 1) { return $true }
        } catch {}
    }
    return $false
}

function Ensure-Download($url, $dest) {
    if (-not (Test-Path $dest)) {
        Write-LauncherLog "Baixando $url para $dest"
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    }
}

if (-not (Test-Path $appExe)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('Executavel do aplicativo nao encontrado.', 'Aplicativo') | Out-Null
    exit 1
}

# ---------------------------------------------------------------------------
# Pre-requisitos do Windows (.NET 4.8, WebView2, VC++ Redist).
# A leitura do registro NAO precisa de admin. So elevamos (UAC) se REALMENTE
# faltar algo para instalar — assim, no caso normal, o app abre direto, sem
# prompt de comando e sem UAC.
#
# IMPORTANTE: este launcher NAO abre/instala NENHUM multilogin (IXBrowser ou
# AdsPower). O usuario abre o multilogin de sua escolha por conta propria; o
# app conecta na API do que estiver configurado apenas quando for usar.
# ---------------------------------------------------------------------------
$precisaDotNet  = (Get-DotNetRelease) -lt 528040
$precisaWebView = -not (Test-WebView2Installed)
$precisaVC      = -not (Test-VCRedistInstalled)
$precisaInstalar = $precisaDotNet -or $precisaWebView -or $precisaVC

if ($precisaInstalar -and -not (Test-Admin)) {
    Write-LauncherLog 'Pre-requisitos ausentes; solicitando elevacao para instalar.'
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', ('"' + $PSCommandPath + '"')
    ) -WorkingDirectory $launcherDir
    exit
}

if ($precisaInstalar) {
    $tempDir = Join-Path $env:TEMP 'GSFB_Redist'
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

    if ($precisaDotNet) {
        $dotNetInstaller = Join-Path $tempDir 'NDP48-x86-x64-AllOS-ENU.exe'
        Ensure-Download 'https://go.microsoft.com/fwlink/?linkid=2088631' $dotNetInstaller
        Write-LauncherLog 'Instalando .NET Framework 4.8'
        Start-Process -FilePath $dotNetInstaller -ArgumentList '/q /norestart' -Wait
    }

    if ($precisaWebView) {
        $wvInstaller = Join-Path $tempDir 'MicrosoftEdgeWebView2Setup.exe'
        Ensure-Download 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' $wvInstaller
        Write-LauncherLog 'Instalando Microsoft Edge WebView2 Runtime'
        Start-Process -FilePath $wvInstaller -ArgumentList '/silent /install' -Wait
    }

    if ($precisaVC) {
        $vcInstaller = Join-Path $tempDir 'VC_redist.x64.exe'
        Ensure-Download 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vcInstaller
        Write-LauncherLog 'Instalando Visual C++ Redistributable x64'
        Start-Process -FilePath $vcInstaller -ArgumentList '/install /quiet /norestart' -Wait
    }
}

Write-LauncherLog ('Abrindo ' + (Split-Path -Leaf $appExe))
Start-Process -FilePath $appExe -WorkingDirectory $baseDir
