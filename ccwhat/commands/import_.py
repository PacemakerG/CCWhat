"""import subcommand — import a portable diagnostic package and optionally open the viewer."""

from __future__ import annotations

import json
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

import click


_IMPORTS_DIR = Path.home() / "Downloads" / "ccwhat-imports"
_RAW_IMPORTS_DIR = Path.home() / "Downloads" / "ccwhat-imports" / "raw-req-resp"
_MANIFEST_FILENAME = "manifest.json"
_PACKAGE_ROOT = "ccwhat-export"
_LEGACY_PACKAGE_ROOT = "deep-ai-analysis-export"
_SESSION_ID_RE = re.compile(r"[0-9a-f-]{36}")


def _find_package_root(base: Path) -> Path:
    """Return the package root dir, accepting both ccwhat-export/ and legacy roots."""
    if (base / _MANIFEST_FILENAME).exists():
        return base
    for root_name in (_PACKAGE_ROOT, _LEGACY_PACKAGE_ROOT):
        candidate = base / root_name
        if candidate.is_dir() and (candidate / _MANIFEST_FILENAME).exists():
            return candidate
    raise click.ClickException(
        f"No manifest.json found in {base}. "
        "This doesn't look like a valid ccwhat diagnostic package."
    )


def _read_manifest(package_dir: Path) -> dict:
    manifest_path = package_dir / _MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise click.ClickException(f"Failed to read manifest.json: {exc}") from exc
    return manifest


def _validate_session_id(session_id: str) -> str:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise click.ClickException(f"Invalid sessionId in manifest.json: {session_id!r}")
    return session_id


def _safe_child_name(value: str, field_name: str) -> str:
    path = Path(value)
    if path.is_absolute() or path.name != value or value in {"", ".", ".."}:
        raise click.ClickException(f"Invalid {field_name} in manifest.json: {value!r}")
    if "/" in value or "\\" in value:
        raise click.ClickException(f"Invalid {field_name} in manifest.json: {value!r}")
    return value


def _safe_extract_tar(tar: tarfile.TarFile, dest: Path) -> None:
    dest_resolved = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if target != dest_resolved and dest_resolved not in target.parents:
            raise click.ClickException(f"Unsafe path in archive: {member.name}")
        if member.issym() or member.islnk():
            raise click.ClickException(f"Unsupported link in archive: {member.name}")
    tar.extractall(dest)


def _manifest_sessions(package_dir: Path, manifest: dict) -> list[dict[str, str | Path]]:
    if isinstance(manifest.get("sessions"), list):
        sessions = manifest["sessions"]
        if not sessions:
            raise click.ClickException("manifest.json sessions list is empty.")

        result: list[dict[str, str | Path]] = []
        seen: set[str] = set()
        for item in sessions:
            if not isinstance(item, dict):
                raise click.ClickException("manifest.json sessions entries must be objects.")
            if "sessionId" not in item or "projectDir" not in item:
                raise click.ClickException("manifest.json session entry is missing required fields.")

            session_id = _validate_session_id(str(item["sessionId"]))
            if session_id in seen:
                raise click.ClickException(f"Duplicate sessionId in manifest.json: {session_id}")
            seen.add(session_id)

            result.append({
                "session_id": session_id,
                "project_dir": _safe_child_name(str(item["projectDir"]), "projectDir"),
                "source_dir": package_dir / "sessions" / session_id,
            })
        return result

    if "sessionId" not in manifest or "projectDir" not in manifest:
        raise click.ClickException(
            "manifest.json is missing required fields (sessions or sessionId/projectDir)."
        )

    session_id = _validate_session_id(str(manifest["sessionId"]))
    return [{
        "session_id": session_id,
        "project_dir": _safe_child_name(str(manifest["projectDir"]), "projectDir"),
        "source_dir": package_dir,
    }]


def _remove_existing_import(session: dict[str, str | Path]) -> None:
    session_id = str(session["session_id"])
    project_dir_name = str(session["project_dir"])
    dest_project = _IMPORTS_DIR / project_dir_name
    session_log = dest_project / f"{session_id}.jsonl"
    if session_log.exists():
        session_log.unlink()

    session_dir = dest_project / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)

    raw_dir = _RAW_IMPORTS_DIR / session_id
    if raw_dir.exists():
        shutil.rmtree(raw_dir)


def _has_existing_import(session: dict[str, str | Path]) -> bool:
    session_id = str(session["session_id"])
    project_dir_name = str(session["project_dir"])
    dest_session_log = _IMPORTS_DIR / project_dir_name / f"{session_id}.jsonl"
    return (
        dest_session_log.exists()
        or (_IMPORTS_DIR / project_dir_name / session_id).exists()
        or (_RAW_IMPORTS_DIR / session_id).exists()
    )


def _import_session(session: dict[str, str | Path]) -> None:
    session_id = str(session["session_id"])
    project_dir_name = str(session["project_dir"])
    package_session_dir = Path(session["source_dir"])
    dest_project = _IMPORTS_DIR / project_dir_name
    dest_project.mkdir(parents=True, exist_ok=True)

    main_log_src = package_session_dir / "claude-logs" / "main-session.jsonl"
    if not main_log_src.exists():
        raise click.ClickException(f"main-session.jsonl not found in package: {main_log_src}")
    shutil.copy2(main_log_src, dest_project / f"{session_id}.jsonl")

    subagents_src = package_session_dir / "claude-logs" / "subagents"
    if subagents_src.is_dir():
        dest_subagents = dest_project / session_id / "subagents"
        dest_subagents.mkdir(parents=True, exist_ok=True)
        for f in subagents_src.iterdir():
            if f.is_file():
                shutil.copy2(f, dest_subagents / f.name)

    req_resp_src = package_session_dir / "req-resp"
    if req_resp_src.is_dir():
        dest_raw = _RAW_IMPORTS_DIR / session_id
        dest_raw.mkdir(parents=True, exist_ok=True)
        for f in req_resp_src.iterdir():
            if f.is_file():
                shutil.copy2(f, dest_raw / f.name)


def _import_package(sessions: list[dict[str, str | Path]]) -> None:
    for session in sessions:
        _import_session(session)


def _find_free_port(start: int, attempts: int = 10) -> int:
    import socket
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise click.ClickException(f"No free port found in range {start}–{start + attempts - 1}.")


def _open_viewer(port: int = 7789) -> None:
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from viewer.server import run_server as _run_server

    free_port = _find_free_port(port)
    if free_port != port:
        click.echo(f"Port {port} already in use, using {free_port} instead.")

    click.echo(f"Starting viewer at http://127.0.0.1:{free_port}/claude-log.html")
    click.echo("Press Ctrl+C to stop.")
    _run_server(free_port, _IMPORTS_DIR, _RAW_IMPORTS_DIR)


@click.command("import")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--open", "open_viewer", is_flag=True, help="Open the viewer in the browser after import.")
@click.option("--force", is_flag=True, help="Overwrite existing imported session without prompting.")
def import_(path: Path, open_viewer: bool, force: bool) -> None:
    """Import a portable diagnostic package (tar.gz or extracted directory)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        if path.is_file() and tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as tar:
                _safe_extract_tar(tar, tmp_path)
            package_dir = _find_package_root(tmp_path)
        elif path.is_dir():
            package_dir = _find_package_root(path)
        else:
            raise click.ClickException(f"{path} is not a tar.gz file or a directory.")

        manifest = _read_manifest(package_dir)
        sessions = _manifest_sessions(package_dir, manifest)

        existing_sessions = [session for session in sessions if _has_existing_import(session)]
        if existing_sessions:
            if not force:
                click.echo(
                    f"Package contains {len(sessions)} session(s); "
                    f"{len(existing_sessions)} existing import(s) will be overwritten."
                )
                click.echo(f"Import root: {_IMPORTS_DIR}")
                if not click.confirm("Overwrite existing imported data?", default=False):
                    click.echo("Import cancelled.")
                    return
            for session in existing_sessions:
                _remove_existing_import(session)

        _import_package(sessions)

    click.echo(f"Imported {len(sessions)} session(s).")
    click.echo(f"Location: {_IMPORTS_DIR}")

    if open_viewer:
        _open_viewer()
