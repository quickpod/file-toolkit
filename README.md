# File Toolkit

A fast, **offline**, **100% open-source** batch file utility toolkit for Windows. Nothing is uploaded anywhere. Built entirely by AI with human testing and guidance, and published on [QuickOpen](https://quickopen.ai/projects/file-toolkit).

> **100% AI-built and open source.** Apache-2.0.

## What it does

Bulk rename with patterns and regex (with preview), find and remove duplicate files by content hash, compute and verify checksums for whole folders (SHA256SUMS), create and extract ZIP and 7z archives, split large files into parts and rejoin them, and securely wipe files. Batch-first with safe previews; nothing leaves your machine.

## Install

Download **`FileToolkit-Setup.exe`** from the [QuickOpen page](https://quickopen.ai/projects/file-toolkit) or the [GitHub release](https://github.com/quickpod/file-toolkit/releases/latest) and double-click it. It installs per-user, adds Desktop and Start Menu shortcuts, and can optionally trust the QuickOpen Root CA. Authenticode-signed by the QuickOpen Code Signing CA — verify at [quickopen.ai/trust](https://quickopen.ai/trust).

## Run from source

```sh
pip install -r requirements.txt
python file_toolkit_app.py          # GUI
python -m filekit --help    # CLI
```


## Features

- **Bulk rename** — find/replace, regex (`re.sub`), a `{n}` sequence counter with padding/start, case transforms, prefix/suffix and extension changes. A pure *preview* (`plan_rename`) shows every change before anything happens; *apply* detects collisions and safely handles swaps/chains.
- **Find duplicates** — groups byte-identical files by content (fast size pre-filter, then SHA-256), then removes all but one per group, to the Recycle Bin by default.
- **Checksums** — hash any file, write a `SHA256SUMS` manifest for a whole folder, and verify one later (spotting tampered *and* missing files). The manifest is `sha256sum -c` compatible.
- **Archives** — create and extract ZIP and 7z, with an optional password (encrypted header) for 7z, and list archive contents.
- **Split / join** — break a large file into fixed-size parts plus a manifest, then rejoin them with an exact size/hash check.
- **Secure delete** — overwrite-then-remove a file (with an honest note that SSDs and copy-on-write filesystems limit the guarantee), or send a file/folder to the Recycle Bin.
- **Safe by default** — every destructive path previews or dry-runs first, both in the GUI (with a confirmation dialog) and the CLI.

Everything runs fully offline on your machine. The GUI is pure-stdlib tkinter with a sidebar, dark mode and threaded operations; the only runtime dependencies are `py7zr` (7z) and `send2trash` (Recycle Bin).

## CLI examples

```sh
# Bulk rename — preview first (default is safe; nothing changes)
python -m filekit rename *.jpg --prefix "holiday_" --number --number-pad 3
python -m filekit rename *.jpg --prefix "holiday_" --number --apply   # do it

# Regex rename
python -m filekit rename *.png --find "IMG_(\d+)" --replace "photo-\1" --regex --apply

# Find duplicates (dry run), then remove redundant copies to the Recycle Bin
python -m filekit dedupe ./Downloads
python -m filekit dedupe ./Downloads --apply            # keep first of each group

# Checksums for a folder, then verify later
python -m filekit hash ./release -o SHA256SUMS
python -m filekit verify ./release/SHA256SUMS

# Archives
python -m filekit zip ./src -o src.zip
python -m filekit 7z ./src -o src.7z --password hunter2
python -m filekit un7z src.7z -d ./out --password hunter2

# Split a big file into 700 MB parts, then rejoin
python -m filekit split bigfile.iso --size 700M -d ./parts
python -m filekit join "./parts/bigfile.iso.*" -o bigfile.iso

# Delete
python -m filekit secure-delete secret.key --yes    # overwrite then remove
python -m filekit trash old-report.pdf              # to the Recycle Bin
```

## License

Apache-2.0 — see [LICENSE](LICENSE). A 100% AI-built project published on QuickOpen.
