// Fixture builds exercise the same code without writing the real Environment key.
const
#ifdef FixtureRoot
  EnvironmentKey = 'Software\EYEPQC\InstallerFixture\Environment';
  OwnershipKey = 'Software\EYEPQC\InstallerFixture\PathOwnership';
#else
  EnvironmentKey = 'Environment';
  OwnershipKey = 'Software\EYEPQC\pc\InstallerPath';
#endif

function ExpandEnvironmentStrings(Source, Destination: String; Size: Cardinal): Cardinal;
  external 'ExpandEnvironmentStringsW@kernel32.dll stdcall';

function NormalizedPathEntry(Value: String): String;
var
  Buffer: String;
  Count: Cardinal;
begin
  SetLength(Buffer, 32768);
  Count := ExpandEnvironmentStrings(Trim(Value), Buffer, 32768);
  if (Count = 0) or (Count > 32768) then RaiseException('PATH entry expansion failed.');
  SetLength(Buffer, Count - 1);
  Result := Trim(Buffer);
  if (Length(Result) >= 2) and (Result[1] = '"') and (Result[Length(Result)] = '"') then
    Result := Copy(Result, 2, Length(Result) - 2);
  StringChangeEx(Result, '/', '\', True);
  while (Length(Result) > 3) and (Result[Length(Result)] = '\') do
    Delete(Result, Length(Result), 1);
  Result := Uppercase(Result);
end;

function ReadUserPath: String;
begin
  Result := '';
  if RegValueExists(HKCU, EnvironmentKey, 'Path') and
     not RegQueryStringValue(HKCU, EnvironmentKey, 'Path', Result) then
    RaiseException('Current user PATH is not a readable string; it was not changed.');
end;

function FindPathEntry(Value, Entry: String; Exact: Boolean; var EntryStart, EntryEnd: Integer): Integer;
var
  Start, Finish: Integer;
  Part: String;
begin
  Result := 0;
  Start := 1;
  while Start <= Length(Value) do begin
    Finish := Start;
    while (Finish <= Length(Value)) and (Value[Finish] <> ';') do Inc(Finish);
    Part := Copy(Value, Start, Finish - Start);
    if ((Exact and (Part = Entry)) or
        (not Exact and (NormalizedPathEntry(Part) = NormalizedPathEntry(Entry)))) then begin
      Inc(Result);
      EntryStart := Start;
      EntryEnd := Finish;
    end;
    Start := Finish + 1;
  end;
end;

procedure ClearPathOwnership;
begin
  RegDeleteValue(HKCU, OwnershipKey, 'Entry');
  RegDeleteValue(HKCU, OwnershipKey, 'Before');
  RegDeleteValue(HKCU, OwnershipKey, 'After');
  RegDeleteValue(HKCU, OwnershipKey, 'OriginallyPresent');
  RegDeleteValue(HKCU, OwnershipKey, 'SeparatorAdded');
  RegDeleteKeyIfEmpty(HKCU, OwnershipKey);
end;

procedure RegisterUserPath;
var
  Before, After, Entry: String;
  Start, Finish: Integer;
  Present, SeparatorAdded: Cardinal;
begin
  Before := ReadUserPath;
  Entry := ExpandConstant('{app}');
  if FindPathEntry(Before, Entry, False, Start, Finish) > 0 then Exit;
  Present := 0;
  if RegValueExists(HKCU, EnvironmentKey, 'Path') then Present := 1;
  SeparatorAdded := 0;
  After := Before;
  if (After <> '') and (After[Length(After)] <> ';') then begin
    After := After + ';';
    SeparatorAdded := 1;
  end;
  After := After + Entry;
  if Length(After) > 32767 then RaiseException('Current user PATH would be too long.');
  // Keep ownership across upgrades; pre-existing equivalent entries are never claimed.
  if not (RegWriteStringValue(HKCU, OwnershipKey, 'Entry', Entry) and
          RegWriteStringValue(HKCU, OwnershipKey, 'Before', Before) and
          RegWriteStringValue(HKCU, OwnershipKey, 'After', After) and
          RegWriteDWordValue(HKCU, OwnershipKey, 'OriginallyPresent', Present) and
          RegWriteDWordValue(HKCU, OwnershipKey, 'SeparatorAdded', SeparatorAdded)) then begin
    ClearPathOwnership;
    RaiseException('Could not record current user PATH ownership.');
  end;
  // Refuse an observed concurrent edit rather than overwriting it.
  if (ReadUserPath <> Before) or not RegWriteStringValue(HKCU, EnvironmentKey, 'Path', After) then begin
    ClearPathOwnership;
    RaiseException('Could not safely update current user PATH.');
  end;
end;

procedure UnregisterUserPath;
var
  Value, Entry, Before, After: String;
  Start, Finish: Integer;
  Present, SeparatorAdded: Cardinal;
  Changed: Boolean;
begin
  if not RegQueryStringValue(HKCU, OwnershipKey, 'Entry', Entry) or
     (Entry <> ExpandConstant('{app}')) then Exit;
  // Missing/damaged ownership never authorizes deleting user configuration.
  if not (RegQueryStringValue(HKCU, OwnershipKey, 'Before', Before) and
          RegQueryStringValue(HKCU, OwnershipKey, 'After', After) and
          RegQueryDWordValue(HKCU, OwnershipKey, 'OriginallyPresent', Present) and
          RegQueryDWordValue(HKCU, OwnershipKey, 'SeparatorAdded', SeparatorAdded)) then Exit;
  Value := ReadUserPath;
  Changed := False;
  if Value = After then begin
    if Present = 0 then Changed := RegDeleteValue(HKCU, EnvironmentKey, 'Path')
    else Changed := RegWriteStringValue(HKCU, EnvironmentKey, 'Path', Before);
  end else if FindPathEntry(Value, Entry, True, Start, Finish) = 1 then begin
    if Finish <= Length(Value) then Delete(Value, Start, Finish - Start + 1)
    else if (Start > 1) and (SeparatorAdded = 1) then Delete(Value, Start - 1, Finish - Start + 1)
    else Delete(Value, Start, Finish - Start);
    Changed := RegWriteStringValue(HKCU, EnvironmentKey, 'Path', Value);
  end else begin
    Log('Owned PATH entry changed, removed or duplicated; preserving current user PATH.');
    ClearPathOwnership;
    Exit;
  end;
  if Changed then ClearPathOwnership
  else RaiseException('Could not remove the owned current user PATH entry.');
end;
