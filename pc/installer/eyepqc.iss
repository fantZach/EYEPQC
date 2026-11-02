#ifndef AppExecutable
  #error AppExecutable must identify the explicitly built CLI
#endif
#ifndef OutputDirectory
  #error OutputDirectory must be set by build_installer.ps1
#endif
#ifndef AppVersion
  #error AppVersion must match the explicitly built CLI
#endif
#ifndef AppNumericVersion
  #error AppNumericVersion must be set by build_installer.ps1
#endif

[Setup]
#ifdef FixtureRoot
AppId={{BC45B197-2603-498A-B857-C58A97E11DC0}
AppName=EYEPQC PC Installer Fixture
DefaultDirName={#FixtureRoot}\bin
OutputBaseFilename=EYEPQC-Setup-{#AppVersion}-fixture
#else
AppId={{9B9AF3F4-737E-48FD-B6A3-6B0A82BA6A7D}
AppName=EYEPQC PC
DefaultDirName={localappdata}\EYEPQC\pc\bin
OutputBaseFilename=EYEPQC-Setup-{#AppVersion}
#endif
AppVersion={#AppVersion}
AppPublisher=EYEPQC
VersionInfoVersion={#AppNumericVersion}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableDirPage=yes
UsePreviousAppDir=no
DisableProgramGroupPage=yes
DefaultGroupName=EYEPQC
OutputDir={#OutputDirectory}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
RestartIfNeededByRun=no
UninstallDisplayIcon={app}\eyepqc.exe
UninstallDisplayName=EYEPQC PC {#AppVersion} (user data retained)
SetupLogging=yes
ChangesEnvironment=yes

[Files]
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppExecutable}"; DestDir: "{app}"; DestName: "eyepqc.exe"; Flags: ignoreversion
Source: "{#AppExecutable}"; DestName: "eyepqc-bootstrap.exe"; Flags: dontcopy

[Icons]
#ifndef FixtureRoot
Name: "{group}\EYEPQC command prompt"; Filename: "{cmd}"; Parameters: "/K """"{app}\eyepqc.exe"" --help"""; WorkingDir: "{app}"
Name: "{group}\Uninstall EYEPQC (keep user data)"; Filename: "{uninstallexe}"
#endif

[Code]
var
  InstallationMode: TInputOptionWizardPage;
  SourcePage: TInputFileWizardPage;
  DataPrepared: Boolean;

#include "user_path.iss"

procedure InitializeWizard;
begin
  InstallationMode := CreateInputOptionPage(wpSelectDir,
    'Installation mode', 'Program installation does not require runtime credentials.',
    'No services are started or stopped. Existing settings and data are retained.', True, False);
  InstallationMode.Add('Install program only (new PC or upgrade; configure after installation)');
  InstallationMode.Add('Import existing trusted runtime materials as well');
  InstallationMode.SelectedValueIndex := 0;
  if (ExpandConstant('{param:SOURCECONFIG|}') <> '') or
     (ExpandConstant('{param:IMPORTCURRENT|0}') = '1') then
    InstallationMode.SelectedValueIndex := 1;
  SourcePage := CreateInputFilePage(InstallationMode.ID,
    'Import existing runtime materials',
    'Keep account database and private keys in your Windows user directory.',
    'Leave this blank to import your current EYEPQC settings. Alternatively select a trusted old configuration JSON.' + #13#10 +
    'Exactly six referenced runtime files are copied; no passwords, CA signing keys or board keys are bundled.' + #13#10 +
    'An incomplete import blocks installation; choose program-only mode if materials are not ready. Existing data is never overwritten. Uninstall keeps data and settings.');
  SourcePage.Add('Existing configuration (optional):', 'EYEPQC configuration|*.json', 'json');
  SourcePage.Values[0] := ExpandConstant('{param:SOURCECONFIG|}');
  DataPrepared := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = SourcePage.ID) and (InstallationMode.SelectedValueIndex = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  Arguments: String;
begin
  Result := '';
  if DataPrepared then Exit;
  ReadUserPath;
  if InstallationMode.SelectedValueIndex = 0 then
  begin
    DataPrepared := True;
    Exit;
  end;
  Arguments := 'install-data';
  if SourcePage.Values[0] <> '' then
    Arguments := Arguments + ' --config ' + AddQuotes(SourcePage.Values[0]);
  ExtractTemporaryFile('eyepqc-bootstrap.exe');
  if not Exec(ExpandConstant('{tmp}\eyepqc-bootstrap.exe'), Arguments, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Result := 'Could not run the offline material importer. No application files were installed.'
  else if ExitCode <> 0 then
    Result := 'Runtime material import failed. No application files were installed.' + #13#10 +
      'Go Back and select a valid old configuration whose six files exist: accounts.json, pairing.json, server-chain.pem, server-key.pem, id_ed25519, tunnel_known_hosts.' + #13#10 +
      'Existing data/settings are preserved. Partial data, damaged inputs, unsafe permissions or missing OpenSSH Client must be fixed before retrying.'
  else
    DataPrepared := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then RegisterUserPath;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then UnregisterUserPath;
end;
