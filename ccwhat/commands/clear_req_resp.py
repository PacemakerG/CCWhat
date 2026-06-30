"""clear-req-resp subcommand — clean and parse proxy JSONL logs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ccwhat.parsers.sse_parser import parse_sse_record


def _process_file(input_path: Path, output_path: Path) -> tuple[int, int]:
    """Process a single JSONL file. Returns (processed, skipped) counts."""
    processed = 0
    skipped = 0

    with input_path.open(encoding="utf-8") as fin, \
         output_path.open("w", encoding="utf-8") as fout:
        for lineno, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                click.echo(
                    f"  Warning: {input_path.name}:{lineno} - invalid JSON, skipping ({exc})",
                    err=True,
                )
                skipped += 1
                continue

            if not raw.get("is_sse", False):
                skipped += 1
                continue

            try:
                record = parse_sse_record(raw)
            except (ValueError, KeyError) as exc:
                click.echo(
                    f"  Warning: {input_path.name}:{lineno} - parse error, skipping ({exc})",
                    err=True,
                )
                skipped += 1
                continue

            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            processed += 1

    return processed, skipped


@click.command("clear-req-resp")
@click.argument(
    "input",
    type=click.Path(exists=True, path_type=Path),
    metavar="INPUT",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Output path (single-file mode only). Defaults to <input>_parsed.jsonl.",
)
def clear_req_resp(input: Path, output: Path | None) -> None:
    """Clean and parse proxy JSONL logs into structured JSONL records.

    INPUT can be a single .jsonl file or a directory containing .jsonl files.
    Each SSE record is parsed into: timestamp, domain, method, url,
    claude_session_id, request_json, response_json.
    Non-SSE records are skipped.
    """
    if input.is_dir():
        if output is not None:
            click.echo(
                "Error: --output is not supported in directory mode.", err=True
            )
            sys.exit(1)

        jsonl_files = sorted(input.glob("*.jsonl"))
        if not jsonl_files:
            click.echo(f"No .jsonl files found in {input}", err=True)
            sys.exit(1)

        total_processed = total_skipped = 0
        for src in jsonl_files:
            # Skip already-parsed files
            if src.stem.endswith("_parsed"):
                continue
            dst = src.with_name(src.stem + "_parsed.jsonl")
            processed, skipped = _process_file(src, dst)
            click.echo(f"{src.name} -> {dst.name}  ({processed} records, {skipped} skipped)")
            total_processed += processed
            total_skipped += skipped

        click.echo(f"\nDone. Total: {total_processed} processed, {total_skipped} skipped.")

    else:
        # Single file mode
        if output is None:
            output = input.with_name(input.stem + "_parsed.jsonl")

        processed, skipped = _process_file(input, output)
        click.echo(f"{input.name} -> {output.name}  ({processed} records, {skipped} skipped)")
