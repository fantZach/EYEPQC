"""Current-user and SYSTEM only: fail closed before writing private material."""
import os
from pathlib import Path
import subprocess


def private_acl(path, *, protect=False):
    path = Path(path)
    if os.name != 'nt':
        if protect:
            path.chmod(0o700)
        if path.stat().st_mode & 0o077:
            raise PermissionError('private permissions are too broad')
        return
    # The literal path is environment data, never executable PowerShell text.
    script = r'''
$ErrorActionPreference = 'Stop'
$path = $env:PC_TEST_TLS_PRIVATE
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$system = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
if ($env:PC_TEST_TLS_PROTECT -eq '1') {
    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($identity in @($sid, $system)) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    [System.IO.Directory]::SetAccessControl($path, $acl)
}
$isdir = [System.IO.Directory]::Exists($path)
$actual = if ($isdir) { [System.IO.Directory]::GetAccessControl($path) } else { [System.IO.File]::GetAccessControl($path) }
$rules = @($actual.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
if ($rules.Count -ne 2 -or $actual.GetOwner([System.Security.Principal.SecurityIdentifier]) -ne $sid) {
    throw 'Private ACL owner/rules mismatch'
}
foreach ($rule in $rules) {
    if ($rule.IdentityReference -notin @($sid, $system) -or
        $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl') {
        throw 'Private ACL grants unexpected access'
    }
}
if ($isdir -and -not $actual.AreAccessRulesProtected) {
    throw 'Private directory inherits access'
}
'''
    env = dict(os.environ, PC_TEST_TLS_PRIVATE=str(path.resolve()),
               PC_TEST_TLS_PROTECT='1' if protect else '0')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-Command', script], env=env, capture_output=True, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise PermissionError('Windows private ACL verification failed')
