#!/usr/bin/env python3
"""MarkNav manual navigation pipeline without MATLAB/SPM.

This standalone pathway uses SimpleITK for DICOM import, rigid FLAIR-to-T1
registration, NIfTI writing, and navigation DICOM export. ITK-SNAP is still
used for the neurologist's manual target marking step.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
from collections.abc import Callable
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import SimpleITK as sitk
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, UID, generate_uid


MARKNAV_VERSION = "2026.10.20"
GEOMETRY_SPACING_ATOL_MM = 1e-6
GEOMETRY_ORIGIN_ATOL_MM = 1e-5
GEOMETRY_DIRECTION_ATOL = 1e-6


def find_itksnap() -> Path | None:
    override = os.environ.get("ITKSNAP_EXE") or os.environ.get("ITK_SNAP_EXE")
    if override and Path(override).is_file():
        return Path(override)
    candidates: list[Path] = []
    if platform.system() == "Windows":
        for env_name in ["ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"]:
            base = os.environ.get(env_name)
            if base:
                candidates.extend(
                    [
                        Path(base) / "ITK-SNAP" / "bin" / "ITK-SNAP.exe",
                        Path(base) / "ITK-SNAP" / "ITK-SNAP.exe",
                        Path(base) / "itksnap" / "bin" / "ITK-SNAP.exe",
                    ]
                )
    elif platform.system() == "Darwin":
        candidates.append(Path("/Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP"))
    else:
        found = shutil.which("itksnap") or shutil.which("ITK-SNAP")
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("ITK-SNAP") or shutil.which("itksnap")
    return Path(found) if found else None


ITK_SNAP_BIN = find_itksnap()


def log(message: str) -> None:
    print(message, flush=True)


def sanitize(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return text.strip("._-") or "series"


def quote(path: Path | str) -> str:
    return "'" + str(path).replace("'", "'\"'\"'") + "'"


def launch_detached(args: list[Path | str]) -> None:
    if platform.system() == "Windows":
        subprocess.Popen([str(arg) for arg in args], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        return
    cmd = "nohup " + " ".join(quote(arg) for arg in args) + " >/dev/null 2>&1 &"
    subprocess.run(cmd, shell=True, check=False)


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise RuntimeError(f"{label} not found: {path}")
    return path


def require_dir(path: Path, label: str) -> Path:
    if not path.is_dir():
        raise RuntimeError(f"{label} not found: {path}")
    return path


def first_number(value) -> float:
    if value is None:
        return math.nan
    if isinstance(value, (list, tuple)):
        if not value:
            return math.nan
        value = value[0]
    try:
        return float(value)
    except Exception:
        return math.nan


def entry_text(entry: dict, key: str) -> str:
    return str(entry.get(key, "") or "")


def keyword_score(blob: str, keys: list[str], weights: list[float]) -> float:
    return float(sum(weight for key, weight in zip(keys, weights) if key in blob))


def score_entry(entry: dict, kind: str) -> float:
    blob = " ".join(
        [
            entry_text(entry, "textBlob"),
            entry_text(entry, "metadataBlob"),
            entry_text(entry, "niiPath"),
            entry_text(entry, "description"),
            entry_text(entry, "protocol"),
        ]
    ).lower()
    modality = entry_text(entry, "modality").lower()
    depth = first_number(entry.get("depth"))
    score = depth * 0.1 if math.isfinite(depth) else 0.0
    if kind == "t1":
        if modality != "mr":
            return -math.inf
        if any(word in blob for word in ["flair", "dwi", "adc", "swi"]):
            score -= 250
        score += keyword_score(
            blob,
            ["mprage", "mp rage", "bravo", "fspgr", "spgr", "t1", "gre_fsp", "3d", "sag", "iso"],
            [160, 160, 120, 100, 90, 80, 75, 35, 20, 20],
        )
        if depth >= 96:
            score += 90
        elif depth < 16:
            score -= 300
        return score if score >= 60 else -math.inf
    if kind == "flair":
        if modality != "mr":
            return -math.inf
        if "flair" not in blob and "t2" not in blob:
            return -math.inf
        score += keyword_score(blob, ["flair", "t2", "space", "cube", "mx3d", "3d", "sag", "iso"], [200, 20, 30, 30, 40, 30, 15, 15])
        score += keyword_score(blob, ["mprage", "bravo", "fspgr", "spgr", "dwi", "adc", "swi"], [-160, -140, -140, -120, -140, -140, -100])
        if depth >= 96:
            score += 90
        elif depth < 16:
            score -= 300
        return score if score >= 80 else -math.inf
    return -math.inf


def choose_entry(entries: list[dict], kind: str) -> dict:
    ranked = sorted(((score_entry(entry, kind), entry) for entry in entries), key=lambda item: item[0], reverse=True)
    if not ranked or not math.isfinite(ranked[0][0]):
        raise RuntimeError(f"Could not identify a {kind.upper()} series.")
    return ranked[0][1]


def run_converter(dicom_folder: Path, output_dir: Path, root: Path) -> list[dict]:
    tmp_dir = output_dir / "__itk_import_tmp__"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    converter = root / "support_DICOM_converter_DO_NOT_OPEN_DIRECTLY.py"
    if not converter.is_file():
        converter = root / "itk_dicom_convert.py"
    converter = require_file(converter, "ITK DICOM converter")
    cmd = [sys.executable, str(converter), "--input", str(dicom_folder), "--output", str(tmp_dir)]
    log("Converting DICOM series with SimpleITK...")
    subprocess.run(cmd, check=True)
    manifest_path = tmp_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    if not entries:
        raise RuntimeError(f"No converted DICOM series found in manifest: {manifest_path}")
    return entries


def copy_image(input_path: Path, output_path: Path, pixel_id=sitk.sitkFloat32) -> sitk.Image:
    image = sitk.ReadImage(str(input_path), pixel_id)
    sitk.WriteImage(image, str(output_path), False)
    return image


def register_flair_to_t1(t1: sitk.Image, flair: sitk.Image) -> sitk.Image:
    log("Coregistering/reslicing FLAIR onto T1 with SimpleITK...")
    fixed = sitk.Cast(t1, sitk.sitkFloat32)
    moving = sitk.Cast(flair, sitk.sitkFloat32)
    initial = sitk.CenteredTransformInitializer(
        fixed,
        moving,
        sitk.Euler3DTransform(),
        sitk.CenteredTransformInitializerFilter.GEOMETRY,
    )
    registration = sitk.ImageRegistrationMethod()
    registration.SetMetricAsMattesMutualInformation(numberOfHistogramBins=50)
    registration.SetMetricSamplingStrategy(registration.RANDOM)
    registration.SetMetricSamplingPercentage(0.10)
    registration.SetInterpolator(sitk.sitkLinear)
    registration.SetOptimizerAsRegularStepGradientDescent(
        learningRate=2.0,
        minStep=1e-4,
        numberOfIterations=200,
        gradientMagnitudeTolerance=1e-6,
    )
    registration.SetOptimizerScalesFromPhysicalShift()
    registration.SetShrinkFactorsPerLevel([4, 2, 1])
    registration.SetSmoothingSigmasPerLevel([2, 1, 0])
    registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    registration.SetInitialTransform(initial, inPlace=False)
    transform = registration.Execute(fixed, moving)
    return sitk.Resample(moving, fixed, transform, sitk.sitkLinear, 0.0, sitk.sitkFloat32)


def create_empty_mask(t1: sitk.Image, mask_path: Path) -> None:
    mask = sitk.Image(t1.GetSize(), sitk.sitkUInt8)
    mask.CopyInformation(t1)
    sitk.WriteImage(mask, str(mask_path), False)


def write_itksnap_script(script_path: Path) -> None:
    script_path.write_text(
        "\n".join(
            [
                "engine.sleep(2500);",
                'var zoomAction = engine.findChild(mainwin, "actionZoomToFitInAllViews");',
                "if (zoomAction) zoomAction.trigger();",
                "engine.sleep(250);",
                'var paintAction = engine.findChild(mainwin, "actionPaintbrush");',
                "if (paintAction) paintAction.trigger();",
                "engine.sleep(500);",
                'var paintInspector = engine.findChild(mainwin, "btnPaintbrushInspector");',
                "if (paintInspector) paintInspector.click();",
                "engine.sleep(250);",
                'var paintPanel = engine.findChild(mainwin, "pagePaintbrushTool");',
                "var paintRoot = paintPanel ? paintPanel : mainwin;",
                'var brushSpin = engine.findChild(paintRoot, "inBrushSizeSpinbox");',
                'var brushSlider = engine.findChild(paintRoot, "inBrushSizeSlider");',
                'var brush3d = engine.findChild(paintRoot, "chkVolumetric");',
                'var brushIso = engine.findChild(paintRoot, "chkIsotropic");',
                "if (brushSpin) brushSpin.value = 3;",
                "if (brushSlider) brushSlider.value = 3;",
                "if (brush3d) brush3d.checked = true;",
                "if (brushIso) brushIso.checked = true;",
                "engine.sleep(28800000);",
                "",
            ]
        ),
        encoding="utf-8",
    )


def open_manual_itksnap(output_dir: Path) -> None:
    if ITK_SNAP_BIN is None or not ITK_SNAP_BIN.is_file():
        log("ITK-SNAP not found. Set ITKSNAP_EXE to the full path of ITK-SNAP.exe if needed.")
        return
    script = output_dir / "open_manual_segmentation.js"
    write_itksnap_script(script)
    cmd = [
        str(ITK_SNAP_BIN),
        "-g",
        str(output_dir / "T1.nii"),
        "-o",
        str(output_dir / "FLAIR_on_T1.nii"),
        "-s",
        str(output_dir / "manual_target_mask.nii"),
        "--cwd",
        str(output_dir),
        "--test",
        str(script),
    ]
    launch_detached([Path(arg) if arg.startswith("/") else arg for arg in cmd])
    log("Opened ITK-SNAP for manual target marking.")


def write_next_steps(output_dir: Path, dicom_folder: Path) -> None:
    (output_dir / "README_MANUAL_NAVIGATION.txt").write_text(
        f"""MarkNav Manual Navigation Standalone Pipeline

Input DICOM folder:
  {dicom_folder}

Manual step:
  ITK-SNAP opens as T1 main image + FLAIR overlay.
  Save the segmentation to manual_target_mask.nii in this folder.

DICOM outputs after export:
  DICOM_FOR_NAVIGATION/T1_raw_DICOM
  DICOM_FOR_NAVIGATION/FLAIR_on_T1_raw_DICOM
  DICOM_FOR_NAVIGATION/T1_with_manual_target_DICOM
  DICOM_FOR_NAVIGATION/FLAIR_with_manual_target_DICOM

Verify orientation, registration, opacity, and target location on the navigation workstation before intraoperative use.
""",
        encoding="utf-8",
    )
    (output_dir / "ITK_SNAP_NEXT_STEPS.txt").write_text(
        f"""ITK-SNAP manual marking steps

1. Confirm the images loaded correctly:
   - Main image should be T1.nii.
   - Overlay/layer should be FLAIR_on_T1.nii.
   - Segmentation should be manual_target_mask.nii.

2. Use the paintbrush tool on the left toolbar.
   - The pipeline attempts to preselect paintbrush mode with 3D + Isotropic enabled.
   - Brush size is reduced to 3 for small target marking.
   - Active label should be Label 1.
   - Paint over should be All labels.

3. Mark only the intended surgical/resection target.

4. Save the segmentation before leaving ITK-SNAP:
   File > Save Segmentation
   It must save to:
   {output_dir / "manual_target_mask.nii"}

5. Return to the standalone launcher and choose Export DICOM.
   Export refuses to run if manual_target_mask.nii is still empty.
""",
        encoding="utf-8",
    )


def prepare(dicom_folder: Path, output_dir: Path, root: Path) -> None:
    require_dir(dicom_folder, "Patient MRI DICOM folder")
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = run_converter(dicom_folder, output_dir, root)
    t1_entry = choose_entry(entries, "t1")
    flair_entry = choose_entry(entries, "flair")
    log(f"Selected T1: {t1_entry.get('description')} | {t1_entry.get('protocol')}")
    log(f"Selected FLAIR: {flair_entry.get('description')} | {flair_entry.get('protocol')}")
    t1 = copy_image(Path(t1_entry["niiPath"]), output_dir / "T1.nii")
    flair = copy_image(Path(flair_entry["niiPath"]), output_dir / "FLAIR.nii")
    flair_on_t1 = register_flair_to_t1(t1, flair)
    sitk.WriteImage(flair_on_t1, str(output_dir / "FLAIR_on_T1.nii"), False)
    create_empty_mask(t1, output_dir / "manual_target_mask.nii")
    write_next_steps(output_dir, dicom_folder)
    open_manual_itksnap(output_dir)
    log(f"Prepared standalone manual navigation folder: {output_dir}")


def validate_geometry(image: sitk.Image, label: str) -> None:
    """Require a finite scalar 3-D physical grid suitable for slice export."""
    if image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1:
        raise RuntimeError(f"{label} must be a scalar 3-D image")
    if any(size <= 0 for size in image.GetSize()):
        raise RuntimeError(f"{label} has an empty image dimension")
    spacing = np.asarray(image.GetSpacing(), dtype=float)
    origin = np.asarray(image.GetOrigin(), dtype=float)
    direction = np.asarray(image.GetDirection(), dtype=float).reshape(3, 3)
    if not np.all(np.isfinite(spacing)) or np.any(spacing <= 0):
        raise RuntimeError(f"{label} spacing must be finite and positive")
    if not np.all(np.isfinite(origin)) or not np.all(np.isfinite(direction)):
        raise RuntimeError(f"{label} origin and direction must be finite")
    if not np.allclose(direction.T @ direction, np.eye(3),
                       atol=GEOMETRY_DIRECTION_ATOL, rtol=0):
        raise RuntimeError(f"{label} direction must be orthonormal")
    if not np.isclose(abs(float(np.linalg.det(direction))), 1.0,
                      atol=GEOMETRY_DIRECTION_ATOL, rtol=0):
        raise RuntimeError(f"{label} direction is not an invertible orthonormal grid")


def validate_same_geometry(image: sitk.Image, reference: sitk.Image, label: str) -> None:
    """Compare the complete physical grid; tolerances are absolute only."""
    validate_geometry(reference, "Reference image")
    validate_geometry(image, label)
    checks = [
        ("size", image.GetSize() == reference.GetSize()),
        ("spacing", np.allclose(image.GetSpacing(), reference.GetSpacing(),
                                atol=GEOMETRY_SPACING_ATOL_MM, rtol=0)),
        ("origin", np.allclose(image.GetOrigin(), reference.GetOrigin(),
                               atol=GEOMETRY_ORIGIN_ATOL_MM, rtol=0)),
        ("direction", np.allclose(image.GetDirection(), reference.GetDirection(),
                                  atol=GEOMETRY_DIRECTION_ATOL, rtol=0)),
    ]
    for component, matches in checks:
        if not matches:
            raise RuntimeError(f"{label} {component} does not match the reference image grid")


def validate_nifti_finite(image_path: Path, label: str) -> None:
    """Inspect on-disk NIfTI values before a reader can sanitize NaN/Inf."""
    if not image_path.name.lower().endswith((".nii", ".nii.gz")):
        return
    try:
        values = np.asanyarray(nib.load(str(image_path)).dataobj)
    except Exception as error:
        raise RuntimeError(f"{label} NIfTI data could not be inspected: {error}") from error
    if not np.all(np.isfinite(values)):
        raise RuntimeError(f"{label} contains nonfinite NIfTI values")


def validated_image(image_path: Path, label: str) -> sitk.Image:
    require_file(image_path, label)
    validate_nifti_finite(image_path, label)
    image = sitk.ReadImage(str(image_path))
    validate_geometry(image, label)
    data = sitk.GetArrayViewFromImage(image)
    if not np.all(np.isfinite(data)):
        raise RuntimeError(f"{label} contains nonfinite image pixels")
    float_image = sitk.Cast(image, sitk.sitkFloat32)
    if not np.all(np.isfinite(sitk.GetArrayViewFromImage(float_image))):
        raise RuntimeError(f"{label} is outside the supported finite float32 pixel range")
    return float_image


def validated_mask(mask_path: Path, reference: sitk.Image | None = None) -> sitk.Image:
    require_file(mask_path, "Manual target mask")
    validate_nifti_finite(mask_path, "Manual target mask")
    image = sitk.ReadImage(str(mask_path))
    validate_geometry(image, "Manual target mask")
    if reference is not None:
        validate_same_geometry(image, reference, "Manual target mask")
    data = sitk.GetArrayViewFromImage(image)
    if not np.all(np.isfinite(data)):
        raise RuntimeError("Manual target mask contains nonfinite labels")
    if np.any(data < 0):
        raise RuntimeError("Manual target mask labels must be zero or positive")
    if not np.any(data > 0):
        raise RuntimeError(f"Manual target mask is empty. Draw/save the target in ITK-SNAP before exporting: {mask_path}")
    return image


def nonempty_mask(mask_path: Path) -> None:
    validated_mask(mask_path)


def volume_window(data: np.ndarray) -> tuple[float, float]:
    finite = data[np.isfinite(data) & (data > 0)]
    if finite.size:
        lo = float(np.percentile(finite, 1))
        hi = float(np.percentile(finite, 99.5))
    else:
        lo, hi = 0.0, 1.0
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def normalize_to_uint16(data: np.ndarray, lo: float, hi: float) -> np.ndarray:
    span = float(hi) - float(lo)
    if not math.isfinite(span) or span <= 0:
        return np.zeros(data.shape, dtype=np.uint16)
    # Float64 arithmetic avoids overflow/cancellation for large finite inputs.
    scaled = np.clip((data.astype(np.float64) - float(lo)) / span, 0, 1)
    return np.round(scaled * 2400).astype(np.uint16)


def export_series(image_path: Path, mask_path: Path | None, output_dir: Path,
                  description: str, marked: bool, series_number: int, *,
                  study_uid: str | None = None,
                  frame_uid: str | None = None) -> None:
    # Complete input validation precedes deletion of any existing output files.
    image = validated_image(image_path, "Export image")
    image_arr = sitk.GetArrayFromImage(image)
    lo, hi = volume_window(image_arr)
    mask_arr = None
    if marked and mask_path is None:
        raise RuntimeError("A marked series requires a manual target mask")
    if mask_path is not None:
        mask_img = validated_mask(mask_path, image)
        mask_arr = sitk.GetArrayFromImage(mask_img) > 0
    study_uid = str(study_uid) if study_uid is not None else generate_uid()
    frame_uid = str(frame_uid) if frame_uid is not None else generate_uid()
    if not UID(study_uid).is_valid or not UID(frame_uid).is_valid:
        raise RuntimeError("Study and frame identifiers must be valid DICOM UIDs")
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise RuntimeError("DICOM output must be a directory, not a link or file")
    if output_dir.exists():
        for old in output_dir.glob("*.dcm"):
            old.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    series_uid = generate_uid()
    direction = np.array(image.GetDirection(), dtype=float).reshape(3, 3)
    row_direction = direction[:, 0]
    col_direction = direction[:, 1]
    slice_direction = direction[:, 2]
    spacing = image.GetSpacing()

    for k in range(image_arr.shape[0]):
        out = normalize_to_uint16(image_arr[k], lo, hi)
        if marked and mask_arr is not None:
            out[mask_arr[k]] = np.uint16(4095)
        file_meta = FileMetaDataset()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds = Dataset()
        ds.file_meta = file_meta
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.PatientName = "ManualNav^Derived"
        ds.PatientID = "ManualNav"
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.FrameOfReferenceUID = frame_uid
        ds.Modality = "MR"
        ds.StudyID = "ManualNav"
        ds.SeriesNumber = series_number
        ds.SeriesDescription = description
        ds.ProtocolName = description
        ds.Manufacturer = "MarkNav SimpleITK Standalone"
        ds.SoftwareVersions = MARKNAV_VERSION
        ds.DerivationDescription = "Manual navigation DICOM derived from T1/FLAIR NIfTI and ITK-SNAP manual target mask"
        ds.InstanceNumber = k + 1
        ds.Rows, ds.Columns = out.shape
        ds.PixelSpacing = [float(spacing[1]), float(spacing[0])]
        ds.SliceThickness = float(spacing[2])
        ds.SpacingBetweenSlices = float(spacing[2])
        ds.ImageOrientationPatient = [float(v) for v in np.concatenate([row_direction, col_direction])]
        position = image.TransformIndexToPhysicalPoint((0, 0, k))
        ds.ImagePositionPatient = [float(v) for v in position]
        ds.SliceLocation = float(np.dot(np.array(position, dtype=float), slice_direction))
        ds.BurnedInAnnotation = "YES" if marked else "NO"
        ds.WindowCenter = 1800
        ds.WindowWidth = 3600
        ds.RescaleSlope = 1
        ds.RescaleIntercept = 0
        ds.ContentDate = time.strftime("%Y%m%d")
        ds.ContentTime = time.strftime("%H%M%S")
        ds.StudyDate = ds.ContentDate
        ds.StudyTime = ds.ContentTime
        ds.ImageType = ["DERIVED", "SECONDARY"]
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.PixelData = out.astype(np.uint16).tobytes()
        ds.save_as(str(output_dir / f"{sanitize(description)}_{k + 1:04d}.dcm"), write_like_original=False)

    write_open_helper(output_dir)
    log(f"Created {description} DICOM ({image_arr.shape[0]} slices): {output_dir}")


def write_open_helper(dicom_dir: Path) -> None:
    first = next(iter(sorted(dicom_dir.glob("*.dcm"))), None)
    if first is None:
        return
    if platform.system() == "Windows":
        helper = dicom_dir / "OPEN_THIS_SERIES_IN_ITK_SNAP.bat"
        itk = str(ITK_SNAP_BIN) if ITK_SNAP_BIN is not None else "ITK-SNAP.exe"
        helper.write_text(
            f'@echo off\r\nset "SERIES_DIR=%~dp0"\r\nstart "" "{itk}" -g "%SERIES_DIR%{first.name}" --cwd "%SERIES_DIR%."\r\n',
            encoding="utf-8",
        )
    else:
        helper = dicom_dir / "OPEN_THIS_SERIES_IN_ITK_SNAP.command"
        itk = ITK_SNAP_BIN if ITK_SNAP_BIN is not None else Path("ITK-SNAP")
        helper.write_text(
            '#!/bin/zsh\nSERIES_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"\n'
            f'nohup {quote(itk)} -g "$SERIES_DIR/{first.name}" --cwd "$SERIES_DIR" >/dev/null 2>&1 &\n',
            encoding="utf-8",
        )
        helper.chmod(0o755)
    (dicom_dir / "README_OPEN_SERIES.txt").write_text(
        "This folder is one DICOM series. Open it by running:\n  OPEN_THIS_SERIES_IN_ITK_SNAP.command on macOS/Linux\n  OPEN_THIS_SERIES_IN_ITK_SNAP.bat on Windows\n",
        encoding="utf-8",
    )


def open_dicom_in_itksnap(dicom_dir: Path) -> None:
    first = next(iter(sorted(dicom_dir.glob("*.dcm"))), None)
    if first is None or ITK_SNAP_BIN is None or not ITK_SNAP_BIN.is_file():
        log("ITK-SNAP not found; DICOM export is complete but was not opened automatically.")
        return
    launch_detached([ITK_SNAP_BIN, "-g", first, "--cwd", dicom_dir])
    log(f"Opened completed navigation DICOM in ITK-SNAP: {dicom_dir}")


def export(output_dir: Path) -> None:
    """Preflight, stage and commit a complete four-series export as one set."""
    t1_path = output_dir / "T1.nii"
    flair_path = output_dir / "FLAIR_on_T1.nii"
    mask_path = output_dir / "manual_target_mask.nii"
    t1 = validated_image(t1_path, "T1.nii")
    flair = validated_image(flair_path, "FLAIR_on_T1.nii")
    validate_same_geometry(flair, t1, "FLAIR_on_T1.nii")
    validated_mask(mask_path, t1)
    dicom_root = output_dir / "DICOM_FOR_NAVIGATION"
    if dicom_root.is_symlink() or (dicom_root.exists() and not dicom_root.is_dir()):
        raise RuntimeError("Existing DICOM output must be a directory, not a link or file")

    stage = Path(tempfile.mkdtemp(prefix=".DICOM_FOR_NAVIGATION.staging-", dir=output_dir))
    backup = output_dir / f".DICOM_FOR_NAVIGATION.backup-{uuid4().hex}"
    old_moved = False
    committed = False
    study_uid, frame_uid = generate_uid(), generate_uid()
    series = [
        (t1_path, None, "T1_raw_DICOM", "ManualNav T1 raw", False, 9510),
        (flair_path, None, "FLAIR_on_T1_raw_DICOM", "ManualNav FLAIR raw", False, 9520),
        (t1_path, mask_path, "T1_with_manual_target_DICOM", "ManualNav T1 target", True, 9530),
        (flair_path, mask_path, "FLAIR_with_manual_target_DICOM", "ManualNav FLAIR target", True, 9540),
    ]
    try:
        for image_path, target_path, folder, description, marked, number in series:
            export_series(image_path, target_path, stage / folder, description,
                          marked, number, study_uid=study_uid, frame_uid=frame_uid)
        if dicom_root.exists():
            dicom_root.rename(backup)
            old_moved = True
        try:
            stage.rename(dicom_root)
        except Exception:
            if old_moved:
                if dicom_root.exists():
                    shutil.rmtree(dicom_root)
                backup.rename(dicom_root)
                old_moved = False
            raise
        committed = True
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        # A failed export must leave the original directory in its original place.
        if not committed and old_moved:
            if dicom_root.exists():
                shutil.rmtree(dicom_root)
            backup.rename(dicom_root)
        if committed and backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError:
                log(f"Export is complete; retained prior-output backup: {backup}")
    try:
        open_dicom_in_itksnap(dicom_root / "T1_with_manual_target_DICOM")
    except Exception as error:
        log(f"DICOM export is complete but the viewer could not be opened: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="MarkNav manual navigation standalone pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--dicom", required=True)
    prepare_parser.add_argument("--output", required=True)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.command == "prepare":
        prepare(Path(args.dicom).expanduser().resolve(), Path(args.output).expanduser().resolve(), root)
    elif args.command == "export":
        export(Path(args.output).expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
