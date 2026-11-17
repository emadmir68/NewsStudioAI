[Setup]
AppId={{8C5A2F2A-31E7-4A4E-A11D-000000000202}
AppName=News Studio AI
AppVersion=0.3.0
DefaultDirName={localappdata}\Programs\News Studio AI
DefaultGroupName=News Studio AI
OutputDir=..\installer-output
OutputBaseFilename=NewsStudioAI_Setup_0.3.0
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Files]
Source: "..\dist\NewsStudioAI\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\News Studio AI"; Filename: "{app}\NewsStudioAI.exe"
Name: "{autodesktop}\News Studio AI"; Filename: "{app}\NewsStudioAI.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "ایجاد میانبر روی دسکتاپ"; GroupDescription: "میانبرها:"

[Run]
Filename: "{app}\NewsStudioAI.exe"; Description: "اجرای News Studio AI"; Flags: postinstall nowait
