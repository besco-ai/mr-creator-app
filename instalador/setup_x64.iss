; Nome/versao/autor/exe vem da FONTE UNICA (gerado por gerar_marca_iss.py)
#include "_marca.iss"

[Setup]
AppId={{A3B8C9D2-7F41-4E6A-B5D8-2C9E1F3A4B5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
; UsePreviousAppDir=no: SEMPRE instala em {autopf}\<slug>, IGNORANDO um
; caminho antigo/errado gravado no registro (ex.: o bug do updater 1.5 que
; instalou em C:\Program). Garante que a reinstalacao manual va pro lugar
; certo mesmo com o registro poluido. (O auto-update passa /DIR explicito, entao
; isto nao afeta o OTA.)
UsePreviousAppDir=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release\setup
OutputBaseFilename={#MyAppSlug}_Setup_x64
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Instalacao POR USUARIO (sem UAC): a pasta {app} fica gravavel, que e o que o app
; precisa — ele GRAVA logs/ e config/ dentro dela. Com PrivilegesRequired=admin em
; Program Files o app quebrava com "Acesso negado" (WinError 5) na primeira linha.
; OverridesAllowed=commandline: quem precisar de instalacao para todos os usuarios
; roda com /ALLUSERS, sem abrir dialogo.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile=..\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
; NAO empacotar dados de RUNTIME (logs/config/contas) — alem de nao pertencerem ao
; instalador, o arquivo de log fica TRAVADO quando o app esta rodando a partir da pasta
; de build (ISCC falhava com "arquivo ja esta sendo usado por outro processo").
Source: "..\release\app\x64\{#MyAppSlug}\*"; DestDir: "{app}"; Excludes: "logs\*,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "launcher\*"; DestDir: "{app}\launcher"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "redist\NDP48-x86-x64-AllOS-ENU.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "redist\MicrosoftEdgeWebView2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "redist\VC_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
#ifexist "redist\IXBrowserSetup.exe"
Source: "redist\IXBrowserSetup.exe"; DestDir: "{app}\instalador\redist"; Flags: ignoreversion
#endif

[Dirs]
; A pasta do app tem de ser GRAVAVEL pelo usuario: o app cria logs/ e config/
; ali dentro (main.configurar_logs e backend.RUNTIME_DIR). Instalando "por usuario"
; ja e gravavel; esta linha cobre o caso de instalar para todos os usuarios.
Name: "{app}"; Permissions: users-modify

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\launcher\INICIAR_APP.bat"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\launcher\INICIAR_APP.bat"; Tasks: desktopicon

[Run]
Filename: "{tmp}\NDP48-x86-x64-AllOS-ENU.exe"; Parameters: "/q /norestart"; StatusMsg: "Instalando .NET Framework 4.8..."; Flags: runhidden waituntilterminated; Check: NeedsDotNet48
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Instalando Microsoft Edge WebView2 Runtime..."; Flags: runhidden waituntilterminated; Check: NeedsWebView2
Filename: "{tmp}\VC_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando Visual C++ Redistributable x64..."; Flags: runhidden waituntilterminated; Check: NeedsVCRedist
Filename: "{app}\launcher\INICIAR_APP.bat"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2ClientGuid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function GetDotNetRelease(var Release: Cardinal): Boolean;
begin
  Result := False;
  if IsWin64 then begin
    Result := RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release);
    if Result then exit;
  end;
  Result := RegQueryDWordValue(HKLM32, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release);
end;

function NeedsDotNet48: Boolean;
var
  Release: Cardinal;
begin
  if GetDotNetRelease(Release) then
    Result := Release < 528040
  else
    Result := True;
end;

function RegistryHasWebView2(RootKey: Integer; SubKey: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, SubKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function NeedsWebView2: Boolean;
begin
  Result := True;
  if RegistryHasWebView2(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid) or
     RegistryHasWebView2(HKCU64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid) or
     RegistryHasWebView2(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid) or
     RegistryHasWebView2(HKCU64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid) or
     RegistryHasWebView2(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid) or
     RegistryHasWebView2(HKCU32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid) then
    Result := False;
end;

function NeedsVCRedist: Boolean;
var
  Installed: Cardinal;
begin
  Result := True;
  if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1) then begin
    Result := False;
    exit;
  end;
  if RegQueryDWordValue(HKLM32, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1) then
    Result := False;
end;
