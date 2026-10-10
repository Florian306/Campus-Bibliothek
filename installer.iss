; Inno Setup Script for Campus-Bibliothek
; Produces a modern, professional Windows installer (Setup.exe) with Start Menu and Desktop shortcuts.

#define MyAppName "Campus-Bibliothek AI"
#define MyAppVersion "1.1.3"
#define MyAppPublisher "Florian"
#define MyAppURL "https://github.com/Florian306/Campus-Bibliothek"
#define MyAppExeName "Buchsortierer.exe"

[Setup]
; Basic Application Info
AppId={{E6F7A9D1-34F5-4A9B-9831-25D8F0C6091A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=Campus-Bibliothek-Setup
SetupIconFile=app_icon.ico
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern

; Visual design
WizardSmallImageFile=app_icon.png

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Buchsortierer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "app_icon.png"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
