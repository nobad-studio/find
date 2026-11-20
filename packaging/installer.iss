; Inno Setup 6 script for NOBAD Find. Build:  iscc /DMyAppVersion=0.1.0 packaging\installer.iss   (build.ps1 does this)
; Per-user install without admin rights: NOBAD Find runs as the normal user, so it installs like one, into
; %LOCALAPPDATA%\Programs\NOBAD Find, with a Start menu shortcut for this user only.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "NOBAD Find"
#define MyAppExe "NobadFind.exe"
; The Flutter UI, next to the engine (build.ps1 copies it into dist\NobadFind with its flutter_windows.dll and data\)
#define MyUiExe "nobad_find.exe"

[Setup]
AppId={{A8A5690D-F9AF-4028-8E58-6D29BA8ECF84}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=NOBAD
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoCompany=NOBAD
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\NOBAD Find
DisableDirPage=yes
DefaultGroupName=NOBAD Find
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist-installer
OutputBaseFilename=NobadFind-Setup-{#MyAppVersion}
SetupIconFile=nobadfind.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
DisableReadyPage=no
#ifdef SignBuild
SignTool=nobadsign
SignedUninstaller=yes
#endif

[InstallDelete]
; An upgrade starts from a clean engine folder: what an older version shipped and this one doesn't (0.8.0's pywebview,
; pythonnet and WebView2 loader files) must not stay behind. Everything in it is installed again below.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\NobadFind\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; AppUserModelID: "NOBAD.Find"
; No "start with Windows" option here: NOBAD Find has its own setting for that.

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; The in-app update runs this setup silently: NOBAD Find starts again by itself when it's done (0.9.0).
Filename: "{app}\{#MyAppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
; Runs after CurUninstallStepChanged(usUninstall) below has stopped NOBAD Find. It puts Windows Search back the way
; it was if NOBAD Find turned it off (Windows may ask for permission once) and removes NOBAD Find's own
; start-with-Windows entry. Uninstall waits for it.
Filename: "{app}\{#MyAppExe}"; Parameters: "--uninstall"; Flags: waituntilterminated; RunOnceId: "NobadFindUninstall"

[UninstallDelete]
; Anything created inside the program folder at run time (the folder itself goes too).
Type: filesandordirs; Name: "{app}"

[Code]
const
  INVALID_FILE_ATTRIBUTES = $FFFFFFFF;     // FILE_ATTRIBUTE_REPARSE_POINT is built into Inno Setup

function GetFileAttributes(lpFileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function GetCurrentProcessId: Cardinal;
  external 'GetCurrentProcessId@kernel32.dll stdcall';
function ProcessIdToSessionId(dwProcessId: Cardinal; var pSessionId: Cardinal): BOOL;
  external 'ProcessIdToSessionId@kernel32.dll stdcall';

// ---------------------------------------------------------------- stop NOBAD Find (install, upgrade, uninstall)
// Only the copies in this Windows session (this signed-in user's desktop), filtered by session number. A
// "USERNAME eq" filter makes taskkill look up the owner of every process and took about 30 s per call, which made
// setup and uninstall look stuck. taskkill is started directly, never through a shell. First a normal close
// request, then forced. Run twice to catch a copy started meanwhile. The UI (nobad_find.exe) runs outside the
// engine's job and may outlive it, so it is named too. The text-reading workers are NobadFind.exe as well, so the
// name catches them. Never /T (0.9.2): the in-app update starts this setup from NOBAD Find, so /T ended setup
// itself (a child of NobadFind.exe) before it copied anything, and the old version stayed.
procedure StopFind;
var
  rc: Integer;
  session: Cardinal;
  tk, args: String;
begin
  if not ProcessIdToSessionId(GetCurrentProcessId, session) then
    Exit;
  tk := ExpandConstant('{sys}\taskkill.exe');
  args := '/IM {#MyAppExe} /IM {#MyUiExe} /FI "SESSION eq ' + IntToStr(session) + '"';
  Exec(tk, args, '', SW_HIDE, ewWaitUntilTerminated, rc);
  Sleep(1200);
  Exec(tk, '/F ' + args, '', SW_HIDE, ewWaitUntilTerminated, rc);
  Sleep(500);
  Exec(tk, '/F ' + args, '', SW_HIDE, ewWaitUntilTerminated, rc);
end;

// ---------------------------------------------------------------- the version already installed (0.9.0)
// Read from this app's uninstall entry (per user). Upgrading keeps the index and settings; the same version can be
// installed again (repair); going back to an older version asks first, and the silent in-app update never does it.
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A8A5690D-F9AF-4028-8E58-6D29BA8ECF84}_is1';

var
  InstalledVer: String;

function InstalledVersion: String;
begin
  Result := '';
  if not RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', Result) then
    Result := '';
end;

// "0.8.5" -> each number in turn; missing numbers count as 0. -1, 0, 1 like a comparison.
function CompareVer(A, B: String): Integer;
var
  pa, pb, na, nb: Integer;
begin
  Result := 0;
  while (Result = 0) and ((A <> '') or (B <> '')) do
  begin
    pa := Pos('.', A); pb := Pos('.', B);
    if pa = 0 then begin na := StrToIntDef(A, 0); A := ''; end
    else begin na := StrToIntDef(Copy(A, 1, pa - 1), 0); Delete(A, 1, pa); end;
    if pb = 0 then begin nb := StrToIntDef(B, 0); B := ''; end
    else begin nb := StrToIntDef(Copy(B, 1, pb - 1), 0); Delete(B, 1, pb); end;
    if na < nb then Result := -1
    else if na > nb then Result := 1;
  end;
end;

function InitializeSetup: Boolean;
var
  c: Integer;
begin
  Result := True;
  InstalledVer := InstalledVersion;
  if InstalledVer = '' then
    Exit;                                       // a first install
  c := CompareVer(InstalledVer, '{#MyAppVersion}');
  if c > 0 then
  begin
    if WizardSilent then
    begin
      Result := False;                          // the in-app update never goes back to an older version
      Exit;
    end;
    Result := MsgBox('A newer NOBAD Find (' + InstalledVer + ') is installed.' + #13#10 + #13#10 +
      'Installing {#MyAppVersion} goes back to an older version. Your index and settings are kept, but an older ' +
      'version may not read everything the newer one wrote.' + #13#10 + #13#10 + 'Install the older version anyway?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end
  else if (c = 0) and not WizardSilent then
    Result := MsgBox('NOBAD Find {#MyAppVersion} is already installed.' + #13#10 + #13#10 +
      'Install it again to repair it? Your index and settings are kept.', mbConfirmation, MB_YESNO) = IDYES;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo,
  MemoGroupInfo, MemoTasksInfo: String): String;
begin
  if InstalledVer = '' then
    Result := 'Install NOBAD Find {#MyAppVersion}.'
  else if CompareVer(InstalledVer, '{#MyAppVersion}') < 0 then
    Result := 'Upgrade NOBAD Find ' + InstalledVer + ' to {#MyAppVersion}.' + NewLine +
      'Your search index and settings are kept. NOBAD Find is closed first if it is running.'
  else if CompareVer(InstalledVer, '{#MyAppVersion}') = 0 then
    Result := 'Repair NOBAD Find {#MyAppVersion} (install it again).' + NewLine +
      'Your search index and settings are kept.'
  else
    Result := 'Go back from NOBAD Find ' + InstalledVer + ' to {#MyAppVersion}.' + NewLine +
      'Your search index and settings are kept.';
  if MemoDirInfo <> '' then
    Result := Result + NewLine + NewLine + MemoDirInfo;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  StopFind;                          // so files in use never block an upgrade
end;

// True only for a real folder (not a link or junction that could point somewhere else).
function IsPlainDir(Path: String): Boolean;
var
  a: Cardinal;
begin
  a := GetFileAttributes(Path);
  Result := (a <> INVALID_FILE_ATTRIBUTES) and ((a and FILE_ATTRIBUTE_REPARSE_POINT) = 0) and DirExists(Path);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  base, data: String;
begin
  if CurUninstallStep = usUninstall then
    StopFind;                        // before [UninstallRun] runs NobadFind.exe --uninstall
  if CurUninstallStep = usPostUninstall then
  begin
    StopFind;
    base := ExpandConstant('{localappdata}\NOBAD');
    data := base + '\Find';
    if (not UninstallSilent) and IsPlainDir(base) and IsPlainDir(data) then
      if MsgBox('Also delete your NOBAD Find search index and settings?' + #13#10 + #13#10 +
          'They are in ' + data + '. Your own files are not touched.' + #13#10 +
          'Choose No to keep them for a later reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        // DelTree removes links and junctions inside the folder without following them.
        DelTree(data, True, True, True);
        RemoveDir(base);             // only when nothing else of NOBAD's is left in it
      end;
  end;
end;
