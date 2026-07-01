#!/usr/bin/env python3
"""Convert a Nexacro SSV timetable response into the CSV used by the app.

The source format separates records with ASCII Record Separator (0x1E) and
fields with ASCII Unit Separator (0x1F). The typed SSV column declarations are
converted to plain CSV column names. Embedded line breaks are converted to
spaces because the timetable app expects one physical line per CSV record.

Example:
    python3 convert_timetable.py pasted-text.txt schedule_next.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


RECORD_SEPARATOR = "\x1e"
FIELD_SEPARATOR = "\x1f"
DEFAULT_DATASET = "dsGrdMain"


class SSVFormatError(ValueError):
    """Raised when the input is not a valid timetable SSV response."""


def _parameter_value(record: str, parameter_name: str) -> Optional[str]:
    """Return a typed SSV parameter value, such as ErrorCode:int=0."""
    if "=" not in record:
        return None

    declaration, value = record.split("=", 1)
    name = declaration.split(":", 1)[0]
    return value if name == parameter_name else None


def _column_name(declaration: str) -> str:
    """Remove an SSV type declaration from a header field."""
    return declaration.split(":", 1)[0]


def _app_safe_field(value: str) -> str:
    """Keep a CSV field on one physical line for the browser-side parser."""
    return " ".join(value.splitlines()) if "\n" in value or "\r" in value else value


def parse_ssv(text: str, dataset_name: str = DEFAULT_DATASET) -> Tuple[List[str], List[List[str]]]:
    """Extract one dataset from an SSV response.

    Returns:
        A pair containing the ordered column names and data rows.
    """
    text = text.removeprefix("\ufeff").rstrip("\r\n")
    records = text.split(RECORD_SEPARATOR)

    if not records or records[0].strip() != "SSV:UTF-8":
        raise SSVFormatError("input does not start with the 'SSV:UTF-8' signature")

    for record in records[1:]:
        error_code = _parameter_value(record, "ErrorCode")
        if error_code is not None and error_code != "0":
            error_message = next(
                (
                    value
                    for candidate in records[1:]
                    if (value := _parameter_value(candidate, "ErrorMsg")) is not None
                ),
                "unknown server error",
            )
            raise SSVFormatError(
                f"source response reports ErrorCode={error_code}: {error_message}"
            )

    dataset_markers = {
        record.removeprefix("Dataset:"): index
        for index, record in enumerate(records)
        if record.startswith("Dataset:")
    }
    if dataset_name not in dataset_markers:
        available = ", ".join(sorted(dataset_markers)) or "none"
        raise SSVFormatError(
            f"dataset '{dataset_name}' was not found; available datasets: {available}"
        )

    marker_index = dataset_markers[dataset_name]
    header_index = marker_index + 1
    if header_index >= len(records):
        raise SSVFormatError(f"dataset '{dataset_name}' has no header")

    header = [_column_name(field) for field in records[header_index].split(FIELD_SEPARATOR)]
    if not header or header[0] != "_RowType_":
        raise SSVFormatError(
            f"dataset '{dataset_name}' header does not begin with '_RowType_'"
        )
    if any(not column for column in header):
        raise SSVFormatError(f"dataset '{dataset_name}' contains an empty column name")
    if len(set(header)) != len(header):
        raise SSVFormatError(f"dataset '{dataset_name}' contains duplicate column names")

    rows: List[List[str]] = []
    for record_index in range(header_index + 1, len(records)):
        record = records[record_index]
        if record.startswith("Dataset:"):
            break
        if record == "":
            continue

        fields = record.split(FIELD_SEPARATOR)
        if len(fields) != len(header):
            raise SSVFormatError(
                f"dataset '{dataset_name}' row {len(rows) + 1} has "
                f"{len(fields)} fields; expected {len(header)}"
            )
        rows.append(fields)

    if not rows:
        raise SSVFormatError(f"dataset '{dataset_name}' contains no rows")

    return header, rows


def convert_file(
    input_path: Path,
    output_path: Path,
    dataset_name: str = DEFAULT_DATASET,
    include_bom: bool = False,
) -> Tuple[int, int]:
    """Convert an SSV file and return its row and column counts."""
    if input_path.resolve() == output_path.resolve():
        raise SSVFormatError("input and output paths must be different")

    text = input_path.read_text(encoding="utf-8-sig")
    header, rows = parse_ssv(text, dataset_name)

    encoding = "utf-8-sig" if include_bom else "utf-8"
    with output_path.open("w", encoding=encoding, newline="") as output_file:
        writer = csv.writer(output_file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows([_app_safe_field(value) for value in row] for row in rows)

    return len(rows), len(header)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Nexacro SSV timetable data to app-compatible CSV."
    )
    parser.add_argument("input", type=Path, help="input SSV text file")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="output CSV path (default: input path with a .csv suffix)",
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"SSV dataset to convert (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--bom",
        action="store_true",
        help="write a UTF-8 BOM for spreadsheet compatibility",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_path = args.output or args.input.with_suffix(".csv")

    try:
        row_count, column_count = convert_file(
            args.input,
            output_path,
            dataset_name=args.dataset,
            include_bom=args.bom,
        )
    except (OSError, UnicodeError, SSVFormatError) as error:
        parser.exit(1, f"error: {error}\n")

    print(
        f"Converted {row_count} rows and {column_count} columns "
        f"from '{args.dataset}' to {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
