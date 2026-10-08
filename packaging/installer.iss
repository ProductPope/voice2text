; Inno Setup script - per-user install, no administrator rights needed.
; Build: iscc /DVersion=1.0.0 packaging\installer.iss  (after PyInstaller)

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6E0C3A4D-7C1B-4F1E-9B57-D1C7A170E001}
AppName=dictAItor
AppVersion={#Version}
AppPublisher=dictAItor contributors
AppPublisherURL=https://github.com/ProductPope/voice2text
DefaultDirName={localappdata}\Programs\dictAItor
DefaultGroupName=dictAItor
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=dictaitor-setup-{#Version}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
SetupIconFile=dictaitor.ico
UninstallDisplayIcon={app}\dictAItor.exe

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Uruchamiaj dictAItor razem z Windows / Start with Windows"; Flags: unchecked
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "..\dist\dictAItor\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\dictAItor"; Filename: "{app}\dictAItor.exe"
Name: "{autodesktop}\dictAItor"; Filename: "{app}\dictAItor.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "dictAItor"; ValueData: """{app}\dictAItor.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\dictAItor.exe"; Description: "{cm:LaunchProgram,dictAItor}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM dictAItor.exe /F"; Flags: runhidden; RunOnceId: "StopApp"
