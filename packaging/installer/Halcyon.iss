#define MyAppName "Halcyon"
#define MyAppVersion "1.2.2"
#define MyAppPublisher "Halcyon"
#define MyAppExeName "Halcyon.exe"

[Setup]
AppId={{9F03E2D9-9E47-4F0F-9C6F-2D1A1C3A4A7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
OutputDir=..\..\dist\installer
OutputBaseFilename=Halcyon-Setup
SetupIconFile=..\..\assets\halcyon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce
Name: "assoc\video"; Description: "Register video formats (.mp4, .mkv, .avi, .mov, .webm, .wmv)"; GroupDescription: "File associations / Open With:"; Flags: checkedonce
Name: "assoc\audio"; Description: "Register audio formats (.mp3, .flac, .wav, .aac, .ogg, .m4a)"; GroupDescription: "File associations / Open With:"; Flags: checkedonce
Name: "assoc\playlist"; Description: "Register playlist formats (.m3u, .m3u8, .pls)"; GroupDescription: "File associations / Open With:"; Flags: checkedonce
Name: "context\playfiles"; Description: "Add 'Play with Halcyon' to file right-click menu"; GroupDescription: "Right-click menus:"; Flags: checkedonce
Name: "context\queuefiles"; Description: "Add 'Add to Halcyon Queue' to file right-click menu"; GroupDescription: "Right-click menus:"; Flags: checkedonce
Name: "context\playfolders"; Description: "Add 'Play with Halcyon' to folder right-click menu"; GroupDescription: "Right-click menus:"; Flags: checkedonce
Name: "autoplay"; Description: "Register Halcyon for Windows AutoPlay media prompts"; GroupDescription: "Windows integration:"; Flags: checkedonce

[Files]
Source: "..\..\dist\main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: ShouldInstallVCRedist
Source: "..\redist\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: ShouldInstallWebView2

[Icons]
Name: "{group}\Halcyon"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Halcyon Help"; Filename: "{app}\README.md"
Name: "{group}\Uninstall Halcyon"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Halcyon"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ Runtime..."; Flags: waituntilterminated; Check: ShouldInstallVCRedist
Filename: "{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Parameters: "/install /silent"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; Flags: waituntilterminated; Check: ShouldInstallWebView2
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Halcyon now"; Flags: nowait postinstall skipifsilent

[Registry]
; App Paths lets Windows locate Halcyon.exe and helps Open With / Choose default app.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#MyAppExeName}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey

; RegisteredApplications + Capabilities makes Halcyon appear in Windows Default Apps.
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Halcyon"; ValueData: "Software\Halcyon\Capabilities"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "Halcyon"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Halcyon\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Halcyon media player"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Halcyon\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey

; ProgIDs used by Open With / Default Apps.
Root: HKA; Subkey: "Software\Classes\Halcyon.MediaFile"; ValueType: string; ValueName: ""; ValueData: "Halcyon media file"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Halcyon.MediaFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Halcyon.MediaFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --play ""%1"""; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Halcyon.PlaylistFile"; ValueType: string; ValueName: ""; ValueData: "Halcyon playlist"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Halcyon.PlaylistFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Halcyon.PlaylistFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --play ""%1"""; Flags: uninsdeletekey

; Open With registration for the executable.
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Halcyon"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --play ""%1"""; Flags: uninsdeletekey

; Video extensions.
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mp4"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mkv"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".avi"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mov"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".webm"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wmv"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.mp4\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.mkv\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.avi\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.mov\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.webm\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.wmv\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\video; Flags: uninsdeletevalue

; Audio extensions.
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mp3"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".flac"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wav"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".aac"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ogg"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m4a"; ValueData: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.aac\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.ogg\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.m4a\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.MediaFile"; Tasks: assoc\audio; Flags: uninsdeletevalue

; Playlist extensions.
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m3u"; ValueData: "Halcyon.PlaylistFile"; Tasks: assoc\playlist; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m3u8"; ValueData: "Halcyon.PlaylistFile"; Tasks: assoc\playlist; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Halcyon\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pls"; ValueData: "Halcyon.PlaylistFile"; Tasks: assoc\playlist; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.m3u\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.PlaylistFile"; Tasks: assoc\playlist; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.m3u8\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.PlaylistFile"; Tasks: assoc\playlist; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.pls\OpenWithProgids"; ValueType: none; ValueName: "Halcyon.PlaylistFile"; Tasks: assoc\playlist; Flags: uninsdeletevalue

; SupportedTypes makes Halcyon visible in the Open With picker for these types.
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mp4"; ValueData: ""; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mkv"; ValueData: ""; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".avi"; ValueData: ""; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mov"; ValueData: ""; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".webm"; ValueData: ""; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".wmv"; ValueData: ""; Tasks: assoc\video; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mp3"; ValueData: ""; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".flac"; ValueData: ""; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".wav"; ValueData: ""; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".aac"; ValueData: ""; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".ogg"; ValueData: ""; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".m4a"; ValueData: ""; Tasks: assoc\audio; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".m3u"; ValueData: ""; Tasks: assoc\playlist; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".m3u8"; ValueData: ""; Tasks: assoc\playlist; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".pls"; ValueData: ""; Tasks: assoc\playlist; Flags: uninsdeletevalue

; Right-click menus.
Root: HKA; Subkey: "Software\Classes\*\shell\Halcyon.Play"; ValueType: string; ValueName: ""; ValueData: "Play with Halcyon"; Tasks: context\playfiles; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\*\shell\Halcyon.Play"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Tasks: context\playfiles; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\*\shell\Halcyon.Play\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --play ""%1"""; Tasks: context\playfiles; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\*\shell\Halcyon.Queue"; ValueType: string; ValueName: ""; ValueData: "Add to Halcyon Queue"; Tasks: context\queuefiles; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\*\shell\Halcyon.Queue"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Tasks: context\queuefiles; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\*\shell\Halcyon.Queue\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --queue ""%1"""; Tasks: context\queuefiles; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\shell\Halcyon.Play"; ValueType: string; ValueName: ""; ValueData: "Play with Halcyon"; Tasks: context\playfolders; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\shell\Halcyon.Play"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#MyAppExeName},0"; Tasks: context\playfolders; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\shell\Halcyon.Play\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --play ""%1"""; Tasks: context\playfolders; Flags: uninsdeletekey

; AutoPlay integration.
Root: HKA; Subkey: "Software\Classes\Halcyon.AutoPlay"; ValueType: string; ValueName: ""; ValueData: "Halcyon AutoPlay handler"; Tasks: autoplay; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Halcyon.AutoPlay\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --play ""%1"""; Tasks: autoplay; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers\Handlers\HalcyonPlayMedia"; ValueType: string; ValueName: "Action"; ValueData: "Play media with Halcyon"; Tasks: autoplay; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers\Handlers\HalcyonPlayMedia"; ValueType: string; ValueName: "DefaultIcon"; ValueData: "{app}\{#MyAppExeName},0"; Tasks: autoplay; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers\Handlers\HalcyonPlayMedia"; ValueType: string; ValueName: "InvokeProgID"; ValueData: "Halcyon.AutoPlay"; Tasks: autoplay; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers\Handlers\HalcyonPlayMedia"; ValueType: string; ValueName: "InvokeVerb"; ValueData: "open"; Tasks: autoplay; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers\Handlers\HalcyonPlayMedia"; ValueType: string; ValueName: "Provider"; ValueData: "Halcyon"; Tasks: autoplay; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers\EventHandlers\PlayMusicFilesOnArrival"; ValueType: none; ValueName: "HalcyonPlayMedia"; Tasks: autoplay; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers\EventHandlers\PlayVideoFilesOnArrival"; ValueType: none; ValueName: "HalcyonPlayMedia"; Tasks: autoplay; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers\EventHandlers\MixedContentOnArrival"; ValueType: none; ValueName: "HalcyonPlayMedia"; Tasks: autoplay; Flags: uninsdeletevalue

[Code]
function IsVCRedistInstalled: Boolean;
var
  Installed: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1);
  if not Result then
    Result := RegQueryDWordValue(HKLM32, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1);
end;

function IsWebView2Installed: Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
  if not Result then
    Result := RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
  if not Result then
    Result := RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function ShouldInstallVCRedist: Boolean;
begin
  Result := not IsVCRedistInstalled;
end;

function ShouldInstallWebView2: Boolean;
begin
  Result := not IsWebView2Installed;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('Do you want to delete your saved Halcyon settings, cache and playback history?'#13#10#13#10 +
              'Choose No to keep your data for future installs.', mbConfirmation, MB_YESNO) = IDYES then
    begin
      DataDir := ExpandConstant('{userappdata}\Halcyon');
      if DirExists(DataDir) then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
