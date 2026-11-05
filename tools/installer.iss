; Programma di installazione di JT (Inno Setup 6). Lo lancia tools\build.py: non serve aprirlo a mano.
; Installa per l'utente (senza diritti di amministratore) in %LOCALAPPDATA%\Programs\JTools.
; Log, chiave Azure e ultime scelte non stanno li': stanno in %LOCALAPPDATA%\JTools (vedi jt\config.py, Paths).
[Setup]
AppId={{6B0F1C58-4A57-4B53-9E0C-4A5D0B7A2C11}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\JTools
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=JTools-Setup-{#AppVersion}
SetupIconFile={#SourceDir}\Graphics\icons\bubbles.ico
UninstallDisplayIcon={app}\JTools.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento sul desktop"; Flags: unchecked

[Files]
; Data\azure_services.json e' il modello: alla prima partenza JT lo copia in %LOCALAPPDATA%\JTools, dove si compila la chiave
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "Data\azure_services.json"; Flags: recursesubdirs ignoreversion
Source: "{#SourceDir}\Data\azure_services.json"; DestDir: "{app}\Data"; Flags: onlyifdoesntexist

[Icons]
Name: "{autoprograms}\JTools"; Filename: "{app}\JTools.exe"
Name: "{autoprograms}\JTools - log e impostazioni"; Filename: "{localappdata}\JTools"
Name: "{autodesktop}\JTools"; Filename: "{app}\JTools.exe"; Tasks: desktopicon

[Run]
#ifdef WithTestDb
Filename: "{app}\JT-TestDB.exe"; Description: "Crea un database Oracle di prova (chiede host, SID e utente)"; Flags: postinstall skipifsilent unchecked
#endif
Filename: "{app}\JTools.exe"; Description: "Avvia JTools"; Flags: nowait postinstall skipifsilent

; i log e le impostazioni stanno in %LOCALAPPDATA%\JTools e restano anche dopo la disinstallazione
