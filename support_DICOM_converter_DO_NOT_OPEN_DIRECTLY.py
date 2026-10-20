#!/usr/bin/env python3
"""Convert recursively discovered DICOM series to NIfTI using SimpleITK.

This is intended as a fallback for compressed, enhanced, or otherwise awkward
DICOM exports that SPM and dcm2niix may reject. It writes one NIfTI per DICOM
series when possible, falling back to single-object conversion only for series
that cannot be stacked.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
import re
import sys
from pathlib import Path

import pydicom
import SimpleITK as sitk


def sanitize(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    text = text.strip("._-")
    return text or "series"


def first_number(value) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    try:
        return int(value)
    except Exception:
        try:
            return float(value)
        except Exception:
            return None


def dicom_text(ds, name: str) -> str:
    return str(getattr(ds, name, "") or "").strip()


def dicom_number(ds, name: str) -> float | int | None:
    return first_number(getattr(ds, name, None))


def series_key(ds) -> str:
    uid = dicom_text(ds, "SeriesInstanceUID")
    if uid:
        return f"uid:{uid}"
    parts = [
        dicom_text(ds, "StudyInstanceUID"),
        dicom_text(ds, "SeriesDescription"),
        dicom_text(ds, "ProtocolName"),
        str(dicom_number(ds, "SeriesNumber") or ""),
    ]
    return "series:" + "|".join(parts)


def vector3(value):
    try:
        values = [float(x) for x in value]
    except Exception:
        return None
    if len(values) != 3 or any(not math.isfinite(x) for x in values):
        return None
    return values


def orientation_normal(ds):
    try:
        values = [float(x) for x in getattr(ds, "ImageOrientationPatient")]
    except Exception:
        return None
    if len(values) != 6 or any(not math.isfinite(x) for x in values):
        return None
    row = values[:3]
    col = values[3:]
    normal = [
        row[1] * col[2] - row[2] * col[1],
        row[2] * col[0] - row[0] * col[2],
        row[0] * col[1] - row[1] * col[0],
    ]
    if not any(abs(x) > 1e-6 for x in normal):
        return None
    return normal


def slice_position(ds):
    normal = orientation_normal(ds)
    position = vector3(getattr(ds, "ImagePositionPatient", []))
    if normal is None or position is None:
        return None
    return sum(normal[i] * position[i] for i in range(3))


def sorted_series_items(items):
    enriched = []
    have_positions = True
    for path, ds in items:
        position = slice_position(ds)
        instance = dicom_number(ds, "InstanceNumber")
        if position is None:
            have_positions = False
        enriched.append((path, ds, position, instance))
    if have_positions:
        enriched.sort(key=lambda item: (item[2], item[3] if item[3] is not None else 0, str(item[0])))
    else:
        enriched.sort(key=lambda item: (item[3] if item[3] is not None else 10**9, str(item[0])))
    return [(path, ds) for path, ds, _, _ in enriched]


def build_entry(dicom_paths: list[Path], output_path: Path, ds, image):
    size = list(image.GetSize())
    while len(size) < 3:
        size.append(1)
    image_type = getattr(ds, "ImageType", [])
    if isinstance(image_type, str):
        image_type = [image_type]
    image_type = [str(x).strip() for x in image_type]
    description = str(getattr(ds, "SeriesDescription", "") or "").strip()
    protocol = str(getattr(ds, "ProtocolName", "") or "").strip()
    modality = str(getattr(ds, "Modality", "") or "").strip()
    metadata_blob = " ".join(
        [p for p in [description, protocol, modality, " ".join(image_type)] if p]
    ).lower()
    entry = {
        "key": series_key(ds),
        "niiPath": str(output_path),
        "sourcePath": str(dicom_paths[0]),
        "numberOfDicomFiles": len(dicom_paths),
        "description": description,
        "protocol": protocol,
        "modality": modality,
        "seriesNumber": first_number(getattr(ds, "SeriesNumber", None)),
        "depth": int(size[2]),
        "nVolumes": 1,
        "numberOfFrames": first_number(getattr(ds, "NumberOfFrames", None)),
        "rows": first_number(getattr(ds, "Rows", None)),
        "columns": first_number(getattr(ds, "Columns", None)),
        "imageType": image_type,
        "metadataBlob": metadata_blob,
    }
    text_parts = [
        output_path.stem,
        description,
        protocol,
        modality,
        " ".join(image_type),
    ]
    entry["textBlob"] = " ".join([p for p in text_parts if p]).lower()
    return entry


def write_series(items, output_root: Path, series_index: int):
    items = sorted_series_items(items)
    dicom_paths = [path for path, _ in items]
    ds = items[0][1]
    description = dicom_text(ds, "SeriesDescription")
    protocol = dicom_text(ds, "ProtocolName")
    series_number = dicom_number(ds, "SeriesNumber")
    stem = sanitize(
        f"{series_index:04d}__{series_number or 'NA'}__{description or protocol or dicom_paths[0].stem}"
    )
    output_path = output_root / f"{stem}.nii"

    if len(dicom_paths) > 1:
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames([str(path) for path in dicom_paths])
        image = reader.Execute()
    else:
        image = sitk.ReadImage(str(dicom_paths[0]))

    sitk.WriteImage(image, str(output_path), False)
    return build_entry(dicom_paths, output_path, ds, image)


def write_single_object(dicom_path: Path, ds, output_root: Path, object_index: int):
    image = sitk.ReadImage(str(dicom_path))
    description = dicom_text(ds, "SeriesDescription")
    protocol = dicom_text(ds, "ProtocolName")
    series_number = dicom_number(ds, "SeriesNumber")
    stem = sanitize(f"{object_index:04d}__{series_number or 'NA'}__{description or protocol or dicom_path.stem}")
    output_path = output_root / f"{stem}.nii"
    sitk.WriteImage(image, str(output_path), False)
    return build_entry([dicom_path], output_path, ds, image)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_root = Path(args.input).expanduser().resolve()
    output_root = Path(args.output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    manifest_path = output_root / "manifest.json"
    entries = []
    failures = []
    series_groups = defaultdict(list)

    dicom_paths = sorted(
        p for p in input_root.rglob("*") if p.is_file() and not p.name.startswith(".")
    )

    for dicom_path in dicom_paths:
        try:
            ds = pydicom.dcmread(str(dicom_path), stop_before_pixels=True, force=True)
        except Exception as exc:
            failures.append({"file": str(dicom_path), "reason": f"pydicom header read failed: {exc}"})
            continue

        if not hasattr(ds, "SOPClassUID"):
            continue

        series_groups[series_key(ds)].append((dicom_path, ds))

    object_index = 0
    for series_index, items in enumerate(series_groups.values(), start=1):
        try:
            entries.append(write_series(items, output_root, series_index))
        except Exception as exc:
            failures.append({
                "file": str(items[0][0]),
                "reason": f"SimpleITK series stack failed for {len(items)} object(s): {exc}",
            })
            for dicom_path, ds in items:
                object_index += 1
                try:
                    entries.append(write_single_object(dicom_path, ds, output_root, object_index))
                except Exception as single_exc:
                    failures.append({
                        "file": str(dicom_path),
                        "reason": f"SimpleITK single-object fallback failed: {single_exc}",
                    })

    payload = {"entries": entries, "failures": failures}
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if entries:
        print(f"Converted {len(entries)} DICOM series to NIfTI in {output_root}")
        if failures:
            print(f"Skipped {len(failures)} DICOM object(s) that SimpleITK could not read", file=sys.stderr)
        return 0

    print("No readable DICOM objects were converted", file=sys.stderr)
    if failures:
        for failure in failures[:10]:
            print(f"- {failure['file']}: {failure['reason']}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
