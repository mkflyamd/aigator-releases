; AI Gator — Inno Setup 6 installer script
; Build with: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss

#define AppName "AI Gator"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define AppVersion MyAppVersion
#define AppPublisher "AI Gator"
#define AppExeName "AIGator.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/mkflyamd/aigator-releases
DefaultDirName={userappdata}\AIGator
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=AIGatorInstaller
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesInstallIn64BitMode=x64os
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.py
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Tray launcher exe (compiled by Nuitka in build step)
Source: "AIGator.exe"; DestDir: "{app}"; Flags: ignoreversion

; Embedded Python runtime (set up by build.bat)
Source: "python_dist\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs

; Bundled portable Node.js runtime (set up by build.bat) — used by npx/node MCP
; servers, preferred at runtime over any system Node.
Source: "node_dist\*"; DestDir: "{app}\node"; Flags: ignoreversion recursesubdirs createallsubdirs

; Application source
Source: "..\web\*"; DestDir: "{app}\app\web"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "dev-overlay.js"
Source: "..\skills\*"; DestDir: "{app}\app\skills"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "..\tray\*"; DestDir: "{app}\tray"; Flags: ignoreversion recursesubdirs createallsubdirs

; Requirements file (single source of truth for dependencies)
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion

; Version file (read by OTA updater at runtime)
Source: "..\version.txt"; DestDir: "{app}\app"; Flags: ignoreversion

; Atlassian CLI binary (copy from installed location if present)
Source: "..\bin\atlassian.exe"; DestDir: "{app}\bin"; Flags: ignoreversion skipifsourcedoesntexist

; Code signing certificate (auto-imported into Trusted Publishers during install)
Source: "AIGator_CodeSign.cer"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Start Menu
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "AI Gator workspace assistant"
; Startup (auto-launch on login)
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"

[Run]
; Launch immediately after install
; Interactive install: optional "Launch" checkbox on Finish page
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
; Silent install (used by OTA): always relaunch so the browser tab can reconnect
Filename: "{app}\{#AppExeName}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[Dirs]
; Create logs dir so it survives uninstall (user data)
Name: "{userappdata}\AIGator\logs"
; Skills directory — always created so marketplace installs have a target
Name: "{app}\app\skills"

[Code]
procedure KillRunningApp();
var
  ResultCode: Integer;
begin
  // Kill tray launcher
  Exec('taskkill', '/F /T /IM AIGator.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Kill embedded Python (watchdog + uvicorn) filtered by install path
  Exec('powershell.exe',
    '-NonInteractive -ExecutionPolicy Bypass -Command ' +
    '"Get-Process python -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -like ''*AIGator*'' } | ' +
    'Stop-Process -Force -ErrorAction SilentlyContinue"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

function InitializeSetup(): Boolean;
var
  UninstallPath: String;
  ResultCode: Integer;
begin
  // Kill any running AI Gator processes first
  KillRunningApp();

  // Auto-uninstall previous version silently
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Gator_is1',
      'UninstallString', UninstallPath) then
  begin
    Exec(RemoveQuotes(UninstallPath), '/SILENT /NORESTART', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
    Sleep(1000);
  end;

  Result := True;
end;

procedure ImportCodeSigningCert();
var
  ResultCode: Integer;
  CertPath: String;
begin
  CertPath := ExpandConstant('{app}\AIGator_CodeSign.cer');
  if FileExists(CertPath) then
  begin
    // Import cert into current user's Trusted Publishers — no admin needed
    Exec('powershell.exe',
      '-NonInteractive -ExecutionPolicy Bypass -Command "Import-Certificate -FilePath ''' +
      CertPath + ''' -CertStoreLocation Cert:\CurrentUser\TrustedPublisher"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    ImportCodeSigningCert();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    KillRunningApp();

  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('AI Gator has been uninstalled. Your saved credentials and settings in ' +
           ExpandConstant('{%USERPROFILE}') + '\.config\teamspoc\ have been preserved.',
           mbInformation, MB_OK);
  end;
end;
