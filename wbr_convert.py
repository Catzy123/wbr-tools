# wbr <-> yaml converter for totk sword trails, just drag files onto the exe
# raw .wbr only, decompress .zs files first

import argparse
import json
import struct
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

import yaml

NAME_LEN = 0x40
HEADER_LEN = NAME_LEN + 12  # name, start, end, segment count
SEGMENT = struct.Struct("<12f")

# segment layout in the file
FIELDS = ("equip_pos", "equip_rot", "swing_base_pos", "swing_base_rot")

Dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@dataclass
class BlurEntry:
    name: str
    start_frame: int
    end_frame: int
    segments: list  # 12 floats each, see FIELDS


def read_wbr(path):
    data = path.read_bytes()
    entries = []
    try:
        (count,) = struct.unpack_from("<I", data, 0)
        for offset in struct.unpack_from(f"<{count}I", data, 4):
            name = data[offset:offset + NAME_LEN].split(b"\0", 1)[0].decode("utf-8", "ignore")
            start, end, seg_count = struct.unpack_from("<3I", data, offset + NAME_LEN)
            first = offset + HEADER_LEN
            segments = [SEGMENT.unpack_from(data, first + i * SEGMENT.size) for i in range(seg_count)]
            entries.append(BlurEntry(name, start, end, segments))
    except struct.error:
        raise ValueError("not a wbr file (or it's cut off)") from None
    return entries


def write_wbr(path, entries):
    table = bytearray(struct.pack("<I", len(entries)))
    body = bytearray()
    data_start = 4 + 4 * len(entries)
    for entry in entries:
        name = entry.name.encode("utf-8")
        if len(name) >= NAME_LEN:
            raise ValueError(f"name too long, max {NAME_LEN - 1} bytes: {entry.name}")
        table += struct.pack("<I", data_start + len(body))
        body += name.ljust(NAME_LEN, b"\0")
        body += struct.pack("<3I", entry.start_frame, entry.end_frame, len(entry.segments))
        for seg in entry.segments:
            body += SEGMENT.pack(*seg)
    # write to a temp file first so a crash can't leave half a wbr behind
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(table + body)
    tmp.replace(path)


def drop_duplicates(entries):
    seen = set()
    unique = []
    for entry in entries:
        key = (entry.name, entry.start_frame, entry.end_frame, tuple(entry.segments))
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique


def entry_to_yaml(entry):
    return {
        "anim_name": entry.name,
        "start_frame": entry.start_frame,
        "end_frame": entry.end_frame,
        "segments": [
            {field: list(seg[i * 3:i * 3 + 3]) for i, field in enumerate(FIELDS)}
            for seg in entry.segments
        ],
    }


def entry_from_yaml(data, index):
    where = f"entry {index}"
    try:
        name = str(data["anim_name"])
        where = name
        start, end = int(data["start_frame"]), int(data["end_frame"])
        segments = []
        for n, seg in enumerate(data["segments"]):
            where = f"{name} segment {n}"
            values = []
            for field in FIELDS:
                vec = seg[field]
                if len(vec) != 3:
                    raise ValueError(f"{field} needs 3 numbers")
                values += (float(v) for v in vec)
            segments.append(tuple(values))
    except KeyError as exc:
        raise ValueError(f"{where}: missing {exc}") from None
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where}: {exc}") from None
    if start < 0 or end < 0:
        raise ValueError(f"{name}: frames can't be negative")
    return BlurEntry(name, start, end, segments)


def convert(path, output=None):
    if path.name.lower().endswith(".zs"):
        raise ValueError("this is still .zs, decompress it first")
    suffix = path.suffix.lower()

    if suffix == ".wbr":
        entries = read_wbr(path)
        unique = drop_duplicates(entries)
        output = output or path.with_suffix(".yaml")
        text = yaml.dump(
            [entry_to_yaml(entry) for entry in unique],
            Dumper=Dumper, sort_keys=False, default_flow_style=None, width=4096,
        )
        output.write_text(text, encoding="utf-8")
        dupes = len(entries) - len(unique)
        note = f", removed {dupes} dupes" if dupes else ""
        print(f"{path.name} -> {output.name} ({len(unique)} entries{note})")

    elif suffix in (".yaml", ".yml", ".json"):
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text) if suffix == ".json" else yaml.load(text, Loader=Loader)
        if isinstance(data, dict):
            data = data.get("entries")
        if not isinstance(data, list):
            raise ValueError("should be a list of entries")
        entries = [entry_from_yaml(item, i) for i, item in enumerate(data)]
        output = output or path.with_suffix(".wbr")
        write_wbr(output, entries)
        print(f"{path.name} -> {output.name} ({len(entries)} entries)")

    else:
        raise ValueError("needs a .wbr, .yaml or .json")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="WBR Convert", description="wbr <-> yaml for totk sword trails")
    parser.add_argument("files", nargs="*", type=Path, help="files to convert")
    parser.add_argument("-o", "--output", type=Path, help="where to save it (one file only)")
    args = parser.parse_args(argv)

    if not args.files:
        parser.print_help()
        return 2
    if args.output and len(args.files) > 1:
        parser.error("-o only works with one file")

    failed = False
    for path in args.files:
        try:
            convert(path, args.output)
        except (ValueError, OSError, yaml.YAMLError) as exc:
            print(f"{path.name}: {exc}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    # exe window closes right away otherwise, so you'd never see the error
    if code and getattr(sys, "frozen", False):
        try:
            input("\npress enter to close")
        except EOFError:
            pass
    sys.exit(code)
