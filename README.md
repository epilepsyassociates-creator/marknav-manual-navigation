# MarkNav Manual Navigation

Standalone T1 + FLAIR target marking pathway for manual target marking and DICOM navigation export.

This page is written for first-time users. If you are not technical, start at **Download** and follow the numbered steps.

## What MarkNav Does

MarkNav helps prepare MRI images for manual target marking:

1. You choose one patient MRI DICOM folder.
2. MarkNav finds the T1 and FLAIR series.
3. MarkNav converts them to NIfTI.
4. MarkNav aligns FLAIR onto T1.
5. ITK-SNAP opens automatically for manual target drawing.
6. After the target is saved, MarkNav exports DICOM for navigation.

No MATLAB is required.

## Download

Open the latest release page:

https://github.com/epilepsyassociates-creator/marknav-manual-navigation/releases/latest

Download this file:

```text
MarkNav_Manual_Navigation_CLEAN_SEQUENCED_20260425.zip
```

Direct download link:

https://github.com/epilepsyassociates-creator/marknav-manual-navigation/releases/download/v2026.04.25/MarkNav_Manual_Navigation_CLEAN_SEQUENCED_20260425.zip

## After Download

1. Unzip the file.
2. Open the folder named:

```text
MarkNav_RELEASE
```

3. First open:

```text
00_START_HERE_READ_ME_FIRST.txt
```

That file repeats the exact click sequence.

## macOS Pathway

Use these files inside `MarkNav_RELEASE`:

```text
01_macOS_INSTALL_dependencies.command
02_macOS_RUN_MarkNav.command
```

Step by step:

1. Double-click `01_macOS_INSTALL_dependencies.command`.
2. Wait until it says install complete.
3. Double-click `02_macOS_RUN_MarkNav.command`.
4. MarkNav opens.
5. Choose the patient MRI DICOM folder.
6. Choose or confirm the output folder.
7. Click `Prepare + Open ITK-SNAP`.
8. Draw the target in ITK-SNAP and save it.
9. Reopen MarkNav and click `Export DICOM`.

## Windows Pathway

Use these files inside `MarkNav_RELEASE`:

```text
01_Windows_INSTALL_dependencies.bat
02_Windows_RUN_MarkNav.bat
```

Step by step:

1. Double-click `01_Windows_INSTALL_dependencies.bat`.
2. Wait until it says install complete.
3. Double-click `02_Windows_RUN_MarkNav.bat`.
4. Follow the prompts in the command window.
5. Choose option `1` to prepare and open ITK-SNAP.
6. Draw the target in ITK-SNAP and save it.
7. Run MarkNav again.
8. Choose option `2` to export DICOM.

## What You Need Installed

MarkNav installs its Python dependencies automatically.

You still need ITK-SNAP installed separately.

Expected ITK-SNAP locations:

```text
macOS:
/Applications/ITK-SNAP.app

Windows:
Program Files / ITK-SNAP
```

If ITK-SNAP is installed somewhere else, set `ITKSNAP_EXE` to the full ITK-SNAP executable path.

## Files You Should Click

Use only these beginner-facing files:

```text
00_START_HERE_READ_ME_FIRST.txt
01_macOS_INSTALL_dependencies.command
02_macOS_RUN_MarkNav.command
01_Windows_INSTALL_dependencies.bat
02_Windows_RUN_MarkNav.bat
03_FULL_INSTRUCTIONS_AND_OUTPUTS.txt
```

## Files You Should Not Click

These are support files used by MarkNav:

```text
support_MarkNav_pipeline_DO_NOT_OPEN_DIRECTLY.py
support_DICOM_converter_DO_NOT_OPEN_DIRECTLY.py
support_python_requirements_DO_NOT_OPEN_DIRECTLY.txt
support_macOS_UI_binary_DO_NOT_OPEN_DIRECTLY
support_macOS_UI_source_DO_NOT_OPEN_DIRECTLY.swift
```

Leave them in the folder. Do not rename or delete them.

## Expected Output Files

Inside the patient output folder, MarkNav creates:

```text
T1.nii
FLAIR.nii
FLAIR_on_T1.nii
manual_target_mask.nii
README_MANUAL_NAVIGATION.txt
ITK_SNAP_NEXT_STEPS.txt
open_manual_segmentation.js
```

After export, DICOM files are created here:

```text
DICOM_FOR_NAVIGATION/T1_raw_DICOM
DICOM_FOR_NAVIGATION/FLAIR_on_T1_raw_DICOM
DICOM_FOR_NAVIGATION/T1_with_manual_target_DICOM
DICOM_FOR_NAVIGATION/FLAIR_with_manual_target_DICOM
```

## Safety Check

MarkNav will not export DICOM if:

```text
manual_target_mask.nii
```

is empty.

This is intentional. The neurologist must save a non-empty segmentation mask first.

## Common Problems

### macOS says the command file cannot be opened

Right-click the file and choose `Open`.

If macOS asks for confirmation, choose `Open` again.

### ITK-SNAP does not open

Install ITK-SNAP, then run MarkNav again.

If ITK-SNAP is installed in a custom location, set `ITKSNAP_EXE`.

### Export refuses to run

Open `manual_target_mask.nii` in ITK-SNAP and confirm the target was drawn and saved.

An empty mask will be rejected.

### I clicked a support file by mistake

Close it and go back to:

```text
00_START_HERE_READ_ME_FIRST.txt
```

## Release Checksum

SHA-256:

```text
bc955a4a64873cab450658715bcdab6270af4d0d566d67593da8ba5acff7a7e7
```

## Contact

For any assistance, please mail:

```text
epilepsyassociates@gmail.com
```

Or you know where to reach us.
