"""Offline tests for run_g7_batch.ps1 source-root and evidence-path handling."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "run_g7_batch.ps1"
WORKSPACE = ROOT / "build/vitis/g6_auto_recovery_20261009_candidate006d"


def find_powershell() -> str:
    for executable in ("pwsh", "powershell"):
        found = shutil.which(executable)
        if found:
            return found
    raise unittest.SkipTest("PowerShell is unavailable")


class G7BatchHostSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.powershell = find_powershell()
        if not RUNNER.is_file():
            raise unittest.SkipTest("G7 batch runner is unavailable")
        if not (WORKSPACE / "g6_usb_manifest.json").is_file():
            raise unittest.SkipTest("candidate006d build artifacts are unavailable")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="eyepqc g7 host source ")
        self.temp_root = Path(self.temp.name)
        self.host_root = self.temp_root / "isolated host source root with spaces"
        for relative in ("src/host", "data/captures", "report"):
            (self.host_root / relative).mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "src/host/g6_board.py", self.host_root / "src/host/g6_board.py")

        self.workspace = self.temp_root / "workspace with spaces"
        (self.workspace / "g6_usb/build").mkdir(parents=True)
        shutil.copy2(WORKSPACE / "g6_usb_manifest.json", self.workspace / "g6_usb_manifest.json")
        shutil.copy2(WORKSPACE / "g6_usb/build/g6_usb.elf", self.workspace / "g6_usb/build/g6_usb.elf")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_runner(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        command = [
            self.powershell,
            "-NoProfile",
            "-File",
            str(RUNNER),
            "-Workspace",
            str(self.workspace),
            "-HostSourceRoot",
            str(self.host_root),
            *arguments,
        ]
        return subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                              capture_output=True, timeout=120)

    def mock_runs(self) -> list[Path]:
        return sorted((self.host_root / "report/g7_runs").glob("g7_batch_mock_*"))

    def test_dry_run_resolves_isolated_paths_with_spaces(self) -> None:
        previous_root_runs = set((ROOT / "report/g7_runs").glob("g7_batch_mock_*"))
        result = self.run_runner("-DryRun", "-Attempts", "20")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("isolated host source root with spaces", result.stdout)
        self.assertIn("workspace with spaces", result.stdout)
        self.assertEqual(self.mock_runs(), [])
        self.assertEqual(set((ROOT / "report/g7_runs").glob("g7_batch_mock_*")), previous_root_runs)

    def test_dry_run_keeps_legacy_default_workspace(self) -> None:
        result = subprocess.run(
            [self.powershell, "-NoProfile", "-File", str(RUNNER), "-DryRun"],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("workspace=" + str(ROOT / "build/vitis/usbfix3_20261007"), result.stdout)
        self.assertIn("hostsource=" + str(ROOT), result.stdout)

    def test_mock_twenty_writes_only_to_host_source_root(self) -> None:
        result = self.run_runner("-Mock", "-Attempts", "20")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        runs = self.mock_runs()
        self.assertEqual(len(runs), 1)
        summary = json.loads((runs[0] / "batch_summary.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(summary["status"], "mock_complete")
        self.assertEqual(summary["attempts_passed"], 20)
        self.assertTrue(os.path.samefile(Path(summary["host_source_root"]), self.host_root))
        self.assertTrue(os.path.samefile(Path(summary["workspace"]), self.workspace))
        self.assertEqual(len(list(runs[0].glob("trial_*_try*.json"))), 20)
        self.assertEqual(list((ROOT / "report/g7_runs").glob(runs[0].name)), [])

    def test_mock_failure_stops_at_injected_trial(self) -> None:
        result = self.run_runner("-Mock", "-Attempts", "20", "-MockFailAt", "3")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        runs = self.mock_runs()
        self.assertEqual(len(runs), 1)
        summary = json.loads((runs[0] / "batch_summary.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["attempts_passed"], 2)
        self.assertEqual(summary["current_trial"], 3)
        self.assertEqual(len(list(runs[0].glob("trial_*_try*.json"))), 3)

    def test_fewer_than_two_frames_fails_before_any_trial_is_counted(self) -> None:
        result = self.run_runner("-Mock", "-Attempts", "20", "-MockFramesBeforeKill", "1")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        runs = self.mock_runs()
        self.assertEqual(len(runs), 1)
        summary = json.loads((runs[0] / "batch_summary.json").read_text(encoding="utf-8-sig"))
        trial = json.loads((runs[0] / "trial_01_try01.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(summary["attempts_passed"], 0)
        self.assertEqual(trial["status"], "failed")
        self.assertEqual(trial["stage"], "minimum_verified_frame_gate")
        self.assertEqual(trial["kill_after_verified_frames"], 1)

    def test_invalid_host_source_root_is_rejected_before_creating_evidence(self) -> None:
        missing = self.temp_root / "missing isolated root"
        result = subprocess.run(
            [self.powershell, "-NoProfile", "-File", str(RUNNER), "-Workspace", str(self.workspace),
             "-HostSourceRoot", str(missing), "-DryRun"],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())

    def test_result_marker_scope_and_windows_argument_quoting(self) -> None:
        captures = self.host_root / "data/captures"
        result_file = captures / "capture with spaces" / "result.json"
        result_file.parent.mkdir(parents=True)
        result_file.write_text("{}", encoding="utf-8")
        marker_log = self.temp_root / "receiver stdout with spaces.log"
        marker_log.write_text(f"G6_RUN_RESULT path={result_file}\n", encoding="utf-8")
        echo_script = self.temp_root / "argument echo with spaces.py"
        echo_script.write_text(
            "import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8"
        )
        output = self.temp_root / "argument echo output.json"
        helper_script = self.temp_root / "invoke extracted runner helpers.ps1"
        helper_script.write_text(
            r'''$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'runner parse failed'}
foreach($functionName in @('ConvertTo-WindowsArgument','Join-WindowsArguments','Get-RunResultMarker')) {
    $node=$ast.Find({param($candidate) $candidate -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $candidate.Name -eq $functionName},$true)
    if(!$node){throw "function not found: $functionName"}
    Invoke-Expression $node.Extent.Text
}
$hostSourceRoot=[IO.Path]::GetFullPath($args[1])
$markerResult=Get-RunResultMarker $args[2] 1
if([IO.Path]::GetFullPath($markerResult) -ne [IO.Path]::GetFullPath($args[3])){throw 'marker path mismatch'}
$nativeArgs=@($args[4], 'alpha beta', 'C:\tail slash\')
$process=Start-Process -FilePath $args[5] -ArgumentList (Join-WindowsArguments $nativeArgs) -WorkingDirectory $args[6] -RedirectStandardOutput $args[7] -PassThru -Wait -WindowStyle Hidden
if($process.ExitCode -ne 0){throw "argument echo failed: $($process.ExitCode)"}
''',
            encoding="utf-8",
        )
        result = subprocess.run(
            [self.powershell, "-NoProfile", "-File", str(helper_script), str(RUNNER),
             str(self.host_root), str(marker_log), str(result_file), str(echo_script),
             str(ROOT / ".venv/Scripts/python.exe"), str(self.temp_root), str(output)],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), ["alpha beta", "C:\\tail slash\\"])


if __name__ == "__main__":
    unittest.main()
