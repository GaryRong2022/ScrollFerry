#define AppVersion "1.0.2"
[Setup]
AppId={{A64A051F-A89D-41CA-A72D-57CC73F8735F}
AppName=ScrollFerry 舷渡
AppVersion={#AppVersion}
AppPublisher=ScrollFerry
DefaultDirName={localappdata}\Programs\ScrollFerry
DefaultGroupName=ScrollFerry
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableDirPage=no
DisableProgramGroupPage=no
OutputDir=..\dist\installer
OutputBaseFilename=ScrollFerry-Setup-{#AppVersion}-x64
SetupIconFile=..\build\logo.ico
UninstallDisplayIcon={app}\ScrollFerry.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\ScrollFerry\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ScrollFerry"; Filename: "{app}\ScrollFerry.exe"
Name: "{autodesktop}\ScrollFerry"; Filename: "{app}\ScrollFerry.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ScrollFerry.exe"; Description: "Launch ScrollFerry"; Flags: nowait postinstall skipifsilent
