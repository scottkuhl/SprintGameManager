<<<<<<< HEAD
# Sprint Game Manager (SGM)

Desktop GUI for managing Intellivision Sprint Console ROMs and assets in a single folder, per `instructions.md`.

## Setup

# SprintGameManager

Desktop GUI for managing Intellivision Sprint Console ROMs and assets for sideloading on the console, per `instructions.md`.

## Setup

```powershell
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## Build standalone EXE (Windows)

```powershell
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-build.txt
./build_exe.ps1
```

Output: `dist\SprintGameManager.exe`

## App config

On first run, the app creates `sgm.ini` in the current working directory (project root by default). It stores settings like `LastGameFolder` and expected image resolutions.
