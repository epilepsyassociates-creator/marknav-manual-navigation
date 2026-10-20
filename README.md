# MarkNav Manual Navigation

MarkNav prepares MRI images for manual marking of a target already selected by the treating team, then exports that saved marking within derived DICOM images. It links image preparation, manual target drawing in ITK-SNAP and image export. It does not independently identify focal cortical dysplasia, determine the epileptogenic zone or recommend resection boundaries.

## Current source: v2026.10.20

The corrected Python workflow is available in the [v2026.10.20 source release](https://github.com/epilepsyassociates-creator/marknav-manual-navigation/releases/tag/v2026.10.20). Download its **Source code (zip)**, or [download the tagged repository ZIP](https://github.com/epilepsyassociates-creator/marknav-manual-navigation/archive/refs/tags/v2026.10.20.zip).

The versioned repository contains the complete workflow at its root:

- `MarkNav.py`
- `support_DICOM_converter_DO_NOT_OPEN_DIRECTLY.py`
- `requirements.txt`
- `README.md`
- `SHA256_v2026.10.20.txt`

This update provides Python source, not a rebuilt macOS or Windows installer. The April 2026 installer remains a separate historical package and does not contain these corrections.

### What changed

The corrected exporter checks the dimensions, spacing, origin and direction of the saved mask and aligned images against T1, as well as finite image/mask values and a nonempty, nonnegative target mask. It stages the four series before replacing previous outputs. A handled generation failure preserves the prior export. The derived series share a new study and frame of reference, with separate series and image identifiers.

These checks concern the transfer of a saved marking. Clinical target selection remains the treating team's decision. Registration accuracy, quantitative spatial accuracy, navigation-platform compatibility, clinical feasibility and clinical benefit have not been established by this descriptive workflow.

## What you need

- Python **3.10 or later** and an isolated Python environment.
- [ITK-SNAP](https://www.itksnap.org/download/snap/) installed separately for manual target marking.
- The three implementation files kept together: `MarkNav.py`, `support_DICOM_converter_DO_NOT_OPEN_DIRECTLY.py` and `requirements.txt`.

The Python requirements are NumPy, pydicom, SimpleITK and NiBabel. This source distribution does not automatically install them. Use the steps below. No MATLAB is required.

## Run the source workflow

Extract the v2026.10.20 repository ZIP. Open a terminal in the extracted folder containing `MarkNav.py` and `requirements.txt`. The examples below use placeholder paths; select your own MRI folder and a new output folder.

### macOS or Linux

Create an environment and install the requirements:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Prepare the images:

```sh
python MarkNav.py prepare --dicom "/path/to/MRI_DICOM" --output "/path/to/new_output"
```

### Windows PowerShell

Create an environment and install the requirements:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Prepare the images:

```powershell
.\.venv\Scripts\python.exe MarkNav.py prepare --dicom "C:\path\to\MRI_DICOM" --output "C:\path\to\new_output"
```

### Review and mark the target

1. MarkNav identifies candidate T1 and FLAIR series from DICOM metadata and converts them to NIfTI.
2. It rigidly aligns and resamples FLAIR onto the T1 grid, creates an empty mask, and opens ITK-SNAP when that application is found.
3. Review the selected series and their alignment. Acquisition names vary, so automatic series selection needs clinical review.
4. Draw the intended target in ITK-SNAP and save it as `manual_target_mask.nii` in the output folder.
5. Export the saved marking.

On macOS/Linux, in the activated environment:

```sh
python MarkNav.py export --output "/path/to/new_output"
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe MarkNav.py export --output "C:\path\to\new_output"
```

ITK-SNAP is normally located at `/Applications/ITK-SNAP.app` on macOS or under Program Files on Windows. If it is not found, set `ITKSNAP_EXE` to the full ITK-SNAP executable path. An exported image must still be checked on the intended viewing or navigation platform.

## Understand the exported images

Four series are written under `DICOM_FOR_NAVIGATION`:

| Folder | Contents |
| --- | --- |
| `T1_raw_DICOM` | Unmarked derived T1 images |
| `FLAIR_on_T1_raw_DICOM` | Unmarked derived FLAIR images on the T1 grid |
| `T1_with_manual_target_DICOM` | Derived T1 images with target voxels encoded at 4095 |
| `FLAIR_with_manual_target_DICOM` | Derived FLAIR-on-T1 images with target voxels encoded at 4095 |

Despite the historical `raw` folder names, these are regenerated images with normalized background intensities, not copies of the original scanner DICOM data. All positive mask labels are combined. A target color shown in ITK-SNAP is not preserved as a color segmentation, and the exporter does not create a separate DICOM SEG object or RT structure set. The original NIfTI mask remains available for editing. Original patient and study identifiers are not retained in the derived series.

Manual target selection does not remove the need for technical verification. Review the selected series, registration and saved marking, then check orientation and target position on the intended platform before clinical use. The workflow's clinical performance and successful import into a particular navigation platform remain to be established.

## April 2026 installer: historical version

The [v2026.04.25 release](https://github.com/epilepsyassociates-creator/marknav-manual-navigation/releases/tag/v2026.04.25) contains the original macOS/Windows launcher package:

`MarkNav_Manual_Navigation_CLEAN_SEQUENCED_20260425.zip`

That release asset and its original checksum file, `SHA256_CURRENT_RELEASE.txt`, remain unchanged. Despite that historical filename, its checksum applies to the April installer only. The earlier installer is distinct from the corrected source above and does not contain the current full-geometry input checks. Its original instructions remain inside that historical download.

## Source checksums

`SHA256_v2026.10.20.txt` records the hashes of the three implementation files. These identify the source files, not the compressed GitHub archive. The workflow source SHA256 is:

```text
0119a1ca5944cbc19c3e71ba6d7c0c84ba647423f29831e04ec4410ca9bf19bf
```

No license grant is added by this source update.

## Contact

For assistance: contact@gujaratepilepsy.com
