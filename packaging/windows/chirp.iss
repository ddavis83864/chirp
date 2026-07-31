; Inno Setup script for the CHIRP Windows Community Edition installer.
;
; Built via build-windows.ps1 (which passes /DChirpVersion=<X.Y.Z> and
; /DChirpSourceDir=<path to the validated PyInstaller dist\CHIRP bundle> on
; the ISCC command line) -- do not compile this script directly with a
; hand-picked source directory, since build-windows.ps1 is what guarantees
; the installer packages the exact same validated bundle as the portable
; ZIP.
;
; Per-user install by design: PrivilegesRequiredOverridesAllowed lets a
; user pick machine-wide if they explicitly want it and have admin rights,
; but the default (and the only thing CI silent-installs and tests) is a
; per-user install under {localappdata}\Programs\CHIRP, matching this
; project's "no admin rights required for normal install" requirement.

#ifndef ChirpVersion
  #define ChirpVersion "0.0.0"
#endif
#ifndef ChirpSourceDir
  #define ChirpSourceDir "..\..\dist\CHIRP"
#endif
#ifndef ChirpRepoRoot
  #define ChirpRepoRoot "..\.."
#endif

#define ChirpAppName "CHIRP"
#define ChirpAppId "{{B6C6B6F0-6B0C-4C7B-9C1E-DDAVIS83864CHIRPWIN}}"
#define ChirpPublisher "ddavis83864/chirp (community fork, unofficial)"
#define ChirpURL "https://github.com/ddavis83864/chirp"

[Setup]
AppId={#ChirpAppId}
AppName={#ChirpAppName} (Community Edition, unsigned)
AppVersion={#ChirpVersion}
AppVerName={#ChirpAppName} {#ChirpVersion} Community Edition (unsigned)
AppPublisher={#ChirpPublisher}
AppPublisherURL={#ChirpURL}
AppSupportURL={#ChirpURL}/issues
AppUpdatesURL={#ChirpURL}/releases
VersionInfoVersion={#ChirpVersion}
VersionInfoDescription=CHIRP Community Edition installer (unsigned)
DefaultDirName={autopf}\CHIRP
; Per-user default: DefaultDirName above only applies for a machine-wide
; run; for the default (lowest-privilege) install Inno resolves
; {autopf} to the per-user Programs dir automatically once
; PrivilegesRequired=lowest is set, which lands under
; %LOCALAPPDATA%\Programs\CHIRP as required.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
DisableProgramGroupPage=yes
DefaultGroupName=CHIRP
OutputDir={#ChirpRepoRoot}\dist-installer
OutputBaseFilename=CHIRP-windows-v{#ChirpVersion}-x86_64-setup
SetupIconFile={#ChirpRepoRoot}\chirp\share\chirp.ico
UninstallDisplayIcon={app}\CHIRP.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; No PATH changes, no services, no scheduled tasks, no startup entries --
; this script deliberately contains no [Registry] Run-key entries, no
; [Tasks]-driven PATH edits, and no Windows service registration.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#ChirpSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ChirpRepoRoot}\COPYING"; DestDir: "{app}"; DestName: "LICENSE"; Flags: ignoreversion
Source: "{#ChirpRepoRoot}\THIRD_PARTY_LICENSES.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#ChirpRepoRoot}\packaging\windows\README-Windows.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CHIRP"; Filename: "{app}\CHIRP.exe"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,CHIRP}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CHIRP"; Filename: "{app}\CHIRP.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\CHIRP.exe"; Description: "{cm:LaunchProgram,CHIRP}"; Flags: nowait postinstall skipifsilent

; Deliberately no [UninstallDelete] entries covering the user's config
; directory (normally under {userappdata}\..\.chirp on Windows via
; CHIRP's own os.path.expanduser('~')-based default, i.e. the user's home
; profile, not this app's install directory) or any radio image/CSV files
; a user may have saved elsewhere -- the uninstaller therefore only ever
; removes what [Files] installed under {app}, matching the requirement
; to preserve user settings, radio images, and logs on uninstall.

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
