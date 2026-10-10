#!/usr/bin/env python3
"""Build a text-only, allowlisted EYEPQC submission review bundle.

Only Git-tracked source/document files and explicitly approved supplemental
files are eligible. Binary files are excluded by suffix before their contents
are opened. The archive contains a non-self-referential content manifest; the
adjacent evidence index hashes every ZIP entry and the ZIP itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import subprocess
import sys
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "build" / "delivery_20261010"
BUNDLE_NAME = "submission_bundle_current_20261010.zip"
MANIFEST_MEMBER = "META/content_manifest.json"
INDEX_NAME = "evidence_index_current_20261010.json"

TEXT_SUFFIXES = {
    ".c", ".h", ".inc", ".s", ".sv", ".v", ".vh", ".xdc", ".ld",
    ".py", ".ps1", ".tcl", ".md", ".rst", ".txt", ".json", ".toml",
    ".yaml", ".yml", ".xml", ".csv", ".license",
}
MEDIA_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".mp4", ".mov", ".avi", ".mkv", ".wav", ".mp3", ".flac", ".m4a",
}
DENIED_PARTS = {
    "build", "captures", "g7_runs", ".venv", "venv", "__pycache__",
    "secrets", "private", "localkeys",
}
DENIED_NAME_MARKERS = (
    "localkey", "local_key", "privatekey", "private_key", "privkey", "seed",
)
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_BYTES = 128 * 1024 * 1024

# Public NIST KAT files are known test payloads, not product provisioning
# material. These exact paths are intentionally eligible for the bundle.
PUBLIC_KAT_FILES = {
    "data/kat/nist_gcm.json",
    "data/kat/nist_mlkem512.json",
    "data/kat/sources.json",
}

PUBLIC_REPORT_FILES = {
    "report/acceptance_matrix_20261009.md",
    "report/benchmark_summary_20261009.md",
    "report/benchmark_summary_20261009.json",
    "report/competition_submission.md",
    "report/demo_software_ready.md",
    "report/g0_acceptance.md",
    "report/g7_candidate006d_acceptance_20261010.md",
    "report/g7_candidate006d_acceptance_20261010.json",
    "report/goal_gap_audit.md",
    "report/keccak_accel.md",
    "report/keccak_board_benchmark_20261010.md",
    "report/keccak_board_benchmark_20261010.json",
    "report/parallel_B_20261009.md",
    "report/parallel_C_20261009.md",
    "report/progress.md",
    "report/security_gap_audit.md",
    "report/software_ready.md",
    "report/next_stage_plan.md",
    "report/github_sync_20261010.md",
}

# These new files are intentionally included before they are committed.
DEFAULT_SUPPLEMENTAL_FILES = {
    "report/production_security_plan_20261010.md",
    "report/submission_delivery_plan_20261010.md",
    "report/keccak_board_benchmark_20261010.md",
    "report/keccak_board_benchmark_20261010.json",
    "prj/prepare_submission_bundle.py",
    "sim/tb/test_submission_bundle.py",
    "prj/parse_keccak_board_benchmark.py",
    "prj/test_parse_keccak_board_benchmark.py",
    "prj/run_keccak_board_benchmark.py",
    "prj/run_keccak_benchmark_jtag.tcl",
}

EVIDENCE_STATUS = [
    {
        "id": "candidate006d_camera_reset",
        "status": "passed_limited_scope",
        "evidence": "report/g7_candidate006d_acceptance_20261010.json",
        "scope": "受控 PL camera-reset/PWDN 故障后恢复，20/20；不代表物理传感器拔除。",
    },
    {
        "id": "candidate006d_routing_stall",
        "status": "passed_limited_scope",
        "evidence": "report/g7_candidate006d_acceptance_20261010.json",
        "scope": "受控 PL routing-stall/software-deadline 恢复，20/20；不代表硬件 DMA timeout IRQ。",
    },
    {
        "id": "candidate006d_pc_exit_dtr",
        "status": "pending",
        "evidence": "report/competition_submission.md",
        "scope": "最终 candidate006d 同构建 20 次尚未验收。",
    },
    {
        "id": "candidate006d_physical_usb_unplug",
        "status": "pending",
        "evidence": "report/competition_submission.md",
        "scope": "最终 candidate006d 同构建 20 次尚未验收。",
    },
    {
        "id": "g0_sd_reset_cold_start",
        "status": "pending",
        "evidence": "report/g0_acceptance.md",
        "scope": "SD 独立启动、物理复位和 30 分钟断电冷启动未完成。",
    },
    {
        "id": "production_security",
        "status": "not_passed",
        "evidence": "report/production_security_plan_20261010.md",
        "scope": "可信板端熵源、生产 provisioning 与全域清零均未闭环。",
    },
    {
        "id": "competition_requirements",
        "status": "not_provided",
        "evidence": "report/submission_delivery_plan_20261010.md",
        "scope": "正式规则、模板、命名、容量和截止时间未提供。",
    },
    {
        "id": "keccak_board_benefit",
        "status": "functional_passed_no_speedup",
        "evidence": "report/keccak_board_benchmark_20261010.json",
        "scope": "route4k 板测的 3 次 firmware_hw 启动均完成 tcId 76 KAT；96/96 hardware dispatch，timeout 为 96/96 fallback 且 STATUS 清零读回。硬件比软件慢 8.57%-8.68%（均值 8.62%）；不覆盖全部 84 个板上向量、不证明全域清零、未集成 006d 视频。",
    },
]


class BundleError(RuntimeError):
    """Raised when an input or output violates the bundle policy."""


def normalize_repo_path(value: str) -> str:
    """Return a safe repository-relative POSIX path or reject traversal."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise BundleError("empty or invalid repository path")
    normalized = value.replace("\\", "/")
    win = PureWindowsPath(value)
    posix = PurePosixPath(normalized)
    if win.is_absolute() or win.drive or posix.is_absolute():
        raise BundleError(f"absolute path is forbidden: {value!r}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise BundleError(f"path traversal or non-canonical path: {value!r}")
    if posix.as_posix() != normalized:
        raise BundleError(f"non-canonical path: {value!r}")
    return normalized


def is_forbidden_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    parts = [part.lower() for part in path.parts]
    if any(part in DENIED_PARTS for part in parts):
        return True
    if path.suffix.lower() in MEDIA_SUFFIXES:
        return True
    filename = path.name.lower()
    return any(marker in filename for marker in DENIED_NAME_MARKERS)


def is_public_candidate(relative_path: str) -> bool:
    """Apply the exact repository roots/extensions/report allowlist."""
    path = PurePosixPath(relative_path)
    if relative_path in DEFAULT_SUPPLEMENTAL_FILES:
        return not is_forbidden_path(relative_path)
    suffix = path.suffix.lower()
    known_license = path.name.upper() == "LICENSE"
    if is_forbidden_path(relative_path) or (suffix not in TEXT_SUFFIXES and not known_license):
        return False
    parts = path.parts
    if relative_path in PUBLIC_KAT_FILES:
        return True
    if relative_path in PUBLIC_REPORT_FILES:
        return True
    if parts[0] in {"src", "prj", "sim", "doc", "board", "skill"}:
        if parts[0] == "sim" and parts[1:2] == ("vectors",):
            return suffix == ".json"
        if parts[0] == "board":
            return suffix in {".md", ".xdc"}
        if parts[0] == "doc":
            return suffix in {".md", ".rst", ".txt"}
        if parts[0] == "skill":
            return suffix in {".md", ".py", ".txt"}
        return True
    if relative_path in {
        "README.md", "requirements.txt", "run_demo.ps1", "run_g7_batch.ps1",
        "run_g7_recovery.ps1", "run_g7_usb_unplug.ps1",
    }:
        return True
    return False


def is_explicit_extra_candidate(relative_path: str) -> bool:
    """Allow one CLI-named future report/parser without widening defaults."""
    path = PurePosixPath(relative_path)
    if is_forbidden_path(relative_path) or path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    if path.parts[0] == "report":
        return path.suffix.lower() in {".md", ".json"}
    if path.parts[0] == "prj":
        return path.suffix.lower() in {".py", ".md", ".json", ".tcl"} or path.name.upper() == "LICENSE"
    return False


def git_tracked_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    )
    paths = set()
    for raw in result.stdout.split(b"\0"):
        if raw:
            paths.add(normalize_repo_path(os.fsdecode(raw)))
    return paths


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_allowed_text(root: Path, relative_path: str) -> bytes:
    relative_path = normalize_repo_path(relative_path)
    if is_forbidden_path(relative_path):
        raise BundleError(f"forbidden path: {relative_path}")
    if (PurePosixPath(relative_path).suffix.lower() not in TEXT_SUFFIXES
            and PurePosixPath(relative_path).name.upper() != "LICENSE"):
        raise BundleError(f"non-text file type is not read: {relative_path}")
    candidate = root.joinpath(*PurePosixPath(relative_path).parts)
    if candidate.is_symlink():
        raise BundleError(f"symlink input is forbidden: {relative_path}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise BundleError(f"input escapes repository root: {relative_path}") from exc
    size = resolved.stat().st_size
    if size > MAX_FILE_BYTES:
        raise BundleError(f"text file exceeds size limit: {relative_path}")
    data = resolved.read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError(f"allowlisted text file is not UTF-8: {relative_path}") from exc
    return data


def selected_paths(root: Path, includes: list[str]) -> tuple[list[str], set[str], set[str]]:
    tracked = git_tracked_paths(root)
    supplemental = set(DEFAULT_SUPPLEMENTAL_FILES)
    extra_includes = set()
    for supplied in includes:
        normalized = normalize_repo_path(supplied)
        supplemental.add(normalized)
        extra_includes.add(normalized)

    selected = {path for path in tracked if is_public_candidate(path)}
    for path in supplemental:
        if not is_public_candidate(path) and not (path in extra_includes and is_explicit_extra_candidate(path)):
            raise BundleError(f"supplemental path is outside policy: {path}")
        if not root.joinpath(*PurePosixPath(path).parts).is_file():
            raise BundleError(f"supplemental file is missing: {path}")
        selected.add(path)
    if not selected:
        raise BundleError("no eligible files selected")
    if selected & {MANIFEST_MEMBER, INDEX_NAME}:
        raise BundleError("generated metadata cannot be selected as source")
    return sorted(selected), tracked, supplemental


def git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def deterministic_zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def verify_zip(bundle_path: Path, expected: dict[str, str]) -> dict[str, str]:
    actual = {}
    with ZipFile(bundle_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise BundleError("ZIP contains duplicate paths")
        for name in names:
            safe_name = normalize_repo_path(name)
            if safe_name != name or is_forbidden_path(name):
                raise BundleError(f"forbidden ZIP entry: {name}")
            actual[name] = sha256_bytes(archive.read(name))
        if set(actual) != set(expected):
            raise BundleError("ZIP entry set does not match expected manifest")
        for name, digest in expected.items():
            if actual[name] != digest:
                raise BundleError(f"ZIP SHA-256 mismatch: {name}")
        embedded = json.loads(archive.read(MANIFEST_MEMBER))
        for entry in embedded["files"]:
            if actual.get(entry["path"]) != entry["sha256"]:
                raise BundleError(f"embedded manifest mismatch: {entry['path']}")
    return actual


def build_bundle(root: Path, output_dir: Path, includes: list[str]) -> tuple[Path, Path]:
    root = root.resolve(strict=True)
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(root / "build")
    except ValueError as exc:
        raise BundleError("output must stay under the ignored build/ directory") from exc

    paths, tracked, explicit_files = selected_paths(root, includes)
    payload: dict[str, bytes] = {}
    for relative_path in paths:
        if relative_path not in tracked and relative_path not in explicit_files:
            raise BundleError(f"untracked source is not explicitly allowlisted: {relative_path}")
        payload[relative_path] = read_allowed_text(root, relative_path)
    total = sum(map(len, payload.values()))
    if total > MAX_BUNDLE_BYTES:
        raise BundleError("selected text files exceed bundle size limit")

    head = git_head(root)
    uncommitted_paths = []
    for relative_path, current_data in sorted(payload.items()):
        if relative_path not in tracked:
            uncommitted_paths.append(relative_path)
            continue
        worktree_blob = subprocess.run(
            ["git", "hash-object", f"--path={relative_path}", "--stdin"],
            cwd=root, input=current_data, check=True, capture_output=True,
        ).stdout.strip()
        head_blob = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative_path}"], cwd=root,
            check=True, capture_output=True,
        ).stdout.strip()
        if worktree_blob != head_blob:
            uncommitted_paths.append(relative_path)
    payload_entries = [
        {"path": name, "size_bytes": len(data), "sha256": sha256_bytes(data)}
        for name, data in sorted(payload.items())
    ]
    content_manifest = {
        "schema_version": 1,
        "source_head": head,
        "source_head_role": "base_revision_only",
        "source_content_origin": "working_tree",
        "included_uncommitted_paths": uncommitted_paths,
        "working_tree_bytes_note": "payload hashes preserve raw working-tree bytes; canonical Git comparison normalizes configured checkout line endings",
        "selection_policy": "git-tracked text sources/docs plus explicit report/supplemental allowlists",
        "excluded_without_reading": ["build/", "data/captures/", "report/g7_runs/", ".venv/", "binary/media suffixes"],
        "files": payload_entries,
    }
    manifest_data = json_bytes(content_manifest)
    all_entry_bytes = {**payload, MANIFEST_MEMBER: manifest_data}
    expected = {name: sha256_bytes(data) for name, data in all_entry_bytes.items()}

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / BUNDLE_NAME
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr(deterministic_zip_info(name), data)
        archive.writestr(deterministic_zip_info(MANIFEST_MEMBER), manifest_data)

    verified = verify_zip(bundle_path, expected)
    if verified != expected:
        raise BundleError("post-write ZIP verification failed")
    bundle_sha = sha256_bytes(bundle_path.read_bytes())
    evidence_index = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_head": head,
        "source_head_role": "base_revision_only",
        "source_content_origin": "working_tree",
        "included_uncommitted_paths": uncommitted_paths,
        "working_tree_bytes_note": "payload hashes preserve raw working-tree bytes; canonical Git comparison normalizes configured checkout line endings",
        "bundle": BUNDLE_NAME,
        "bundle_sha256": bundle_sha,
        "zip_entry_count": len(verified),
        "zip_entries": [
            {"path": name, "sha256": digest, "size_bytes": len(all_entry_bytes[name])}
            for name, digest in sorted(verified.items())
        ],
        "evidence_status": EVIDENCE_STATUS,
        "limitations": [
            "原始 captures、report/g7_runs 与 build 产物未纳入；本索引不能替代这些原始证据。",
            "公开 NIST KAT 是测试向量，不是生产私钥或 provisioning 输入。",
            "只读取允许后缀的 UTF-8 文本；被排除的二进制和媒体不会被打开或扫描。",
            "比赛规则未提供，包为本地审阅草稿，不宣称满足正式赛方提交要求。",
        ],
    }
    index_path = output_dir / INDEX_NAME
    index_path.write_bytes(json_bytes(evidence_index))
    return bundle_path, index_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--include", action="append", default=[], metavar="REPO_PATH",
        help="explicitly allow one additional source/report path for a later rerun",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        bundle, index = build_bundle(ROOT, args.output_dir, args.include)
    except (BundleError, OSError, subprocess.CalledProcessError) as exc:
        print(f"SUBMISSION_BUNDLE_FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"SUBMISSION_BUNDLE_OK path={bundle.relative_to(ROOT).as_posix()}")
    print(f"EVIDENCE_INDEX path={index.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
