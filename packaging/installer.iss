#define AppVersion "2.1.3"
[Setup]
AppId={{A64A051F-A89D-41CA-A72D-57CC73F8735F}
AppName=舷渡 ScrollFerry
AppVersion={#AppVersion}
AppPublisher=舷渡 ScrollFerry
DefaultDirName={localappdata}\Programs\ScrollFerry
DefaultGroupName=舷渡 ScrollFerry
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
Name: "{group}\舷渡 ScrollFerry"; Filename: "{app}\ScrollFerry.exe"
Name: "{autodesktop}\舷渡 ScrollFerry"; Filename: "{app}\ScrollFerry.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ScrollFerry.exe"; Description: "启动 舷渡 ScrollFerry"; Flags: nowait postinstall skipifsilent
