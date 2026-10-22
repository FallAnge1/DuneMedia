; Установщик для Windows (Inno Setup 6). Собирается в CI:
;   iscc /DAppVersion=0.1.0 build\installer.iss
; Ставится в папку пользователя без прав администратора. Данные программы (%APPDATA%\VideoArchive)
; при удалении не трогаются: настройки и вход в Telegram сохранятся при переустановке.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6E0B8E5A-4F7B-4C5E-9F7A-2D1C0B9A8E11}
AppName=Видеоархив — загрузчик
AppVersion={#AppVersion}
AppPublisher=Видеоархив
DefaultDirName={localappdata}\Programs\VideoArchive
DefaultGroupName=Видеоархив
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=VideoArchive-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\VideoArchive.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\VideoArchive\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Видеоархив — загрузчик"; Filename: "{app}\VideoArchive.exe"
Name: "{group}\Удалить загрузчик"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Видеоархив — загрузчик"; Filename: "{app}\VideoArchive.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VideoArchive.exe"; Description: "Запустить загрузчик"; Flags: nowait postinstall skipifsilent
