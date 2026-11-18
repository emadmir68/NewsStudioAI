[Setup]
AppId={{8C5A2F2A-31E7-4A4E-A11D-000000000202}
AppName=News Studio AI
AppVersion=0.4.0
DefaultDirName={localappdata}\Programs\News Studio AI
DefaultGroupName=News Studio AI
OutputDir=..\installer-output
OutputBaseFilename=NewsStudioAI_0.4.0_Offline_Setup
Compression=lzma2/fast
SolidCompression=no
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Files]
Source: "..\dist\NewsStudioAI\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\vendor\ai\*"; DestDir: "{app}\ai"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\News Studio AI"; Filename: "{app}\NewsStudioAI.exe"
Name: "{autodesktop}\News Studio AI"; Filename: "{app}\NewsStudioAI.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "ایجاد میانبر روی دسکتاپ"; GroupDescription: "میانبرها:"

[Run]
Filename: "{app}\NewsStudioAI.exe"; Description: "اجرای News Studio AI"; Flags: postinstall nowait skipifsilent
