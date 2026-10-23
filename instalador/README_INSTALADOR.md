# Instalador x64 com bootstrap automático

Este pacote foi ajustado para:
- instalar .NET Framework 4.8
- instalar WebView2 Runtime
- instalar Visual C++ Redistributable x64
- iniciar o IXBrowser automaticamente se ele já estiver instalado
- opcionalmente instalar o IXBrowser se você colocar o instalador oficial em `instalador/redist/IXBrowserSetup.exe` antes de gerar o setup

Atalhos do Windows passam a abrir o launcher, não o .exe direto.
