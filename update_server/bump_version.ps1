<#
========================================================================
 BUMP VERSION — GS BM Creator
========================================================================
 Sobe APP_VERSION em server/version.py (2.0 -> 2.1 ... 2.9 -> 3.0) e
 imprime SOMENTE a nova versao (para o .bat capturar).
 Preserva o arquivo em UTF-8 sem BOM (mantem os acentos dos comentarios).
========================================================================
#>
$ErrorActionPreference = 'Stop'

$verFile = Join-Path $PSScriptRoot '..\server\version.py'
if (-not (Test-Path $verFile)) { Write-Error "version.py nao encontrado: $verFile"; exit 1 }

$content = Get-Content -Raw -LiteralPath $verFile
$m = [regex]::Match($content, "APP_VERSION\s*=\s*'([0-9]+)\.([0-9]+)'")
if (-not $m.Success) { Write-Error "APP_VERSION nao encontrado em version.py"; exit 1 }

$major = [int]$m.Groups[1].Value
$minor = [int]$m.Groups[2].Value + 1
# Esquema decimal (desde a 2.0): minor vai de 0 a 9; depois do X.9 vem (X+1).0.
# 2.0 -> 2.1 -> ... -> 2.9 -> 3.0. O legado 1.102 tambem cai aqui -> 2.0.
if ($minor -gt 9) { $major += 1; $minor = 0 }
$nova  = "$major.$minor"

$novo = [regex]::Replace(
    $content,
    "APP_VERSION\s*=\s*'[0-9]+\.[0-9]+'",
    "APP_VERSION = '$nova'",
    1)

# Grava sem BOM para nao quebrar o parsing do Python.
[System.IO.File]::WriteAllText($verFile, $novo, (New-Object System.Text.UTF8Encoding($false)))

# Saida capturada pelo .bat (apenas a versao).
Write-Output $nova
