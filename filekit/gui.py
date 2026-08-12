#!/usr/bin/env python3
r"""File Toolkit -- a pure-stdlib tkinter GUI on top of the ``filekit`` API.

A single main window: a left sidebar of tools (Bulk Rename, Find Duplicates,
Hash/Verify, Archive, Split/Join, Secure Delete) and a main panel that swaps to
the selected tool.  Every operation calls the tested core library (never
re-implements file logic) and runs on a background thread so the UI stays
responsive; results are reported inline (a message plus an "Open folder" button
on success, or the ``FileKitError`` text -- never a traceback -- on failure).

Design goals baked in here:
  * pure standard-library tkinter/ttk -- NO third-party GUI deps.  Dark mode is
    a ttk-style + palette swap; "drag and drop" is an explicit "Add files..."
    button (real OS DnD would need a dependency this app avoids).
  * Importing this module does nothing.  Only :func:`main` builds a root window,
    and it degrades gracefully (prints a note, returns 0) with no display.
  * Frozen-exe safe: bundled assets are resolved via ``sys._MEIPASS`` / the exe
    directory when ``sys.frozen`` is set -- never ``__file__``.
  * Destructive actions (delete duplicates, secure-delete, recycle) always ask
    for confirmation first.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import threading

# NOTE: tkinter is imported lazily inside main()/build_app so that merely
# importing this module (e.g. during packaging or on a headless CI box) never
# fails.

APP_NAME = "File Toolkit"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "File Toolkit — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"

ALL_FILES = [("All files", "*.*")]
ARCHIVE_TYPES = [("Archives", "*.zip *.7z"), ("ZIP", "*.zip"),
                 ("7z", "*.7z"), ("All files", "*.*")]

PALETTES = {
    "light": {
        "bg": "#f5f7fa", "surface": "#ffffff", "text": "#141820",
        "muted": "#5b6472", "primary": "#2f5fe0", "primary_hi": "#2450c8",
        "entry": "#ffffff", "border": "#d5dae2", "sel": "#2f5fe0",
        "sel_fg": "#ffffff", "trough": "#e2e7ef", "ok": "#1f7a3d",
        "err": "#c0392b",
    },
    "dark": {
        "bg": "#0f1115", "surface": "#1a1e24", "text": "#f1f3f7",
        "muted": "#9aa4b2", "primary": "#5b86f7", "primary_hi": "#7098ff",
        "entry": "#1a1e24", "border": "#2a2f38", "sel": "#5b86f7",
        "sel_fg": "#0f1115", "trough": "#2a2f38", "ok": "#5bd68a",
        "err": "#ff6b5e",
    },
}

# (category, [(tool_id, label), ...]) -- tool_id maps to a _panel_<id> method.
TOOL_TREE = [
    ("Rename", [("bulkrename", "Bulk rename")]),
    ("Duplicates", [("dedupe", "Find duplicates")]),
    ("Checksums", [("hashverify", "Hash / Verify")]),
    ("Archive", [("archivecreate", "Create archive"),
                 ("archiveextract", "Extract archive")]),
    ("Split / Join", [("split", "Split file"),
                      ("join", "Join files")]),
    ("Delete", [("securedelete", "Secure delete"),
                ("trash", "Send to Recycle Bin")]),
]

TOOL_DESCRIPTIONS = {
    "bulkrename": "Rename many files at once — find/replace, regex, numbering, "
                  "case, prefix/suffix, extension. Live preview; nothing changes "
                  "until you click Apply.",
    "dedupe": "Scan a folder for byte-identical files (size pre-filter, then "
              "hash). Review the groups, then send the redundant copies to the "
              "Recycle Bin.",
    "hashverify": "Compute a SHA256SUMS manifest for a folder, or verify one and "
                  "spot any tampered or missing files.",
    "archivecreate": "Package files/folders into a .zip or an (optionally "
                     "password-protected) .7z archive.",
    "archiveextract": "Extract a .zip or .7z archive into a folder.",
    "split": "Break a large file into fixed-size parts (+ a manifest) so it fits "
             "on smaller media or uploads.",
    "join": "Reassemble parts back into the original file, verified against the "
            "manifest.",
    "securedelete": "Overwrite a file's bytes, then delete it. Best-effort only "
                    "on SSDs/copy-on-write filesystems — see the note.",
    "trash": "Move a file or folder to the Recycle Bin (recoverable).",
}


# ---------------------------------------------------------------------------
# Asset / frozen handling
# ---------------------------------------------------------------------------
def asset_path(name):
    """Locate a bundled asset from source OR a PyInstaller one-file build.

    For a frozen exe we look only at ``sys._MEIPASS`` and the executable's own
    directory (never ``__file__``).  From source we also consult the package
    dir, the repo root and the CWD.  Returns an absolute path or ``None``.
    """
    roots = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        roots += [here, os.path.dirname(here), os.getcwd()]
    for root in roots:
        candidate = os.path.join(root, name)
        if os.path.exists(candidate):
            return candidate
    return None


def human_size(num_bytes):
    """Human-readable byte size (re-uses the core helper when available)."""
    try:
        from .common import human_size as _hs
        return _hs(num_bytes)
    except Exception:
        size = float(num_bytes or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024.0 or unit == "TB":
                return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024.0
        return f"{size:.1f}TB"


def open_in_file_manager(path):
    """Best-effort 'reveal in file manager', guarded on every platform."""
    try:
        folder = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        if hasattr(os, "startfile"):          # Windows
            os.startfile(folder)              # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", folder])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        return False


def open_with_default_app(path):
    """Open a file/URL with the OS default application, guarded."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)                # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The app (built lazily; tkinter imported only inside build_app/main)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to a live tkinter import.

    Kept inside a function so this module imports cleanly without a display.
    """
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    from . import guiconfig
    from .errors import FileKitError
    from .rename import RenameRule, plan_rename, apply_rename
    from .dedupe import find_duplicates, remove_duplicates
    from .hashing import write_sha256sums, verify_sums
    from .archive import zip_create, zip_extract, sevenz_create, sevenz_extract
    from .splitjoin import split_file, join_files
    from .securedelete import secure_delete, to_recycle

    FONT = "Segoe UI"

    # -- small reusable widgets ------------------------------------------

    class FileRow(ttk.Frame):
        """A labelled path field + Browse button. ``mode`` picks the dialog."""

        def __init__(self, master, app, label, mode="open", filetypes=None,
                     on_change=None):
            super().__init__(master, style="TFrame")
            self.app = app
            self.mode = mode
            self.filetypes = filetypes or ALL_FILES
            self.var = tk.StringVar()
            ttk.Label(self, text=label, width=14, anchor="w").pack(side="left")
            ttk.Entry(self, textvariable=self.var).pack(
                side="left", fill="x", expand=True, padx=(0, 6))
            ttk.Button(self, text="Browse…", command=self._browse,
                       width=10).pack(side="left")
            if on_change:
                self.var.trace_add("write", lambda *_: on_change(self.var.get()))

        def _browse(self):
            if self.mode == "dir":
                p = filedialog.askdirectory(title="Choose a folder")
            elif self.mode == "save":
                p = filedialog.asksaveasfilename(title="Save as",
                                                 filetypes=self.filetypes)
            else:
                p = filedialog.askopenfilename(title="Choose a file",
                                               filetypes=self.filetypes)
            if p:
                self.var.set(p)

        def get(self):
            return self.var.get().strip()

        def set(self, value):
            self.var.set(value or "")

    class FileList(ttk.Frame):
        """A multi-file listbox with Add / Add folder / Remove / Clear."""

        def __init__(self, master, app, filetypes=None, allow_dirs=True,
                     on_change=None):
            super().__init__(master, style="TFrame")
            self.app = app
            self.filetypes = filetypes or ALL_FILES
            self.on_change = on_change
            box = ttk.Frame(self, style="TFrame")
            box.pack(fill="both", expand=True)
            self.listbox = tk.Listbox(box, height=8, activestyle="none",
                                      selectmode="extended", exportselection=False)
            sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
            self.listbox.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.listbox.pack(side="left", fill="both", expand=True)
            app.track(self.listbox, "listbox")

            btns = ttk.Frame(self, style="TFrame")
            btns.pack(fill="x", pady=(6, 0))
            ttk.Button(btns, text="Add files…", command=self.add,
                       style="Accent.TButton").pack(side="left")
            if allow_dirs:
                ttk.Button(btns, text="Add folder…",
                           command=self.add_folder).pack(side="left", padx=4)
            ttk.Button(btns, text="Remove", command=self.remove).pack(side="left", padx=4)
            ttk.Button(btns, text="Clear", command=self.clear).pack(side="left")

        def _changed(self):
            if self.on_change:
                try:
                    self.on_change()
                except Exception:
                    pass

        def add(self):
            paths = filedialog.askopenfilenames(title="Add files",
                                                filetypes=self.filetypes)
            for p in paths:
                self.listbox.insert("end", p)
            if paths:
                self.app.remember_input(paths[0])
                self._changed()

        def add_folder(self):
            d = filedialog.askdirectory(title="Add a folder")
            if d:
                self.listbox.insert("end", d)
                self.app.remember_input(d)
                self._changed()

        def remove(self):
            for i in reversed(self.listbox.curselection()):
                self.listbox.delete(i)
            self._changed()

        def clear(self):
            self.listbox.delete(0, "end")
            self._changed()

        def items(self):
            return list(self.listbox.get(0, "end"))

    # -- the main window --------------------------------------------------

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(WINDOW_TITLE)
            self.geometry("1080x680")
            self.minsize(900, 560)

            self.theme = guiconfig.get_theme()
            self._busy = False
            self._panels = {}          # tool_id -> built frame (lazy)
            self._current = None
            self._tracked = []         # (tk_widget, role) for manual re-theming
            self._img_refs = []        # keep PhotoImage refs alive
            self._history = []         # session output paths

            self._set_icon()
            self._build_menu()
            self._build_layout()
            self._apply_theme()
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            self.after(50, self._select_first_tool)

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("file-toolkit.ico")
                if ico:
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("file-toolkit.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- theming
        def track(self, widget, role):
            self._tracked.append((widget, role))

        def _pal(self):
            return PALETTES[self.theme]

        def _apply_theme(self):
            p = self._pal()
            style = ttk.Style(self)
            try:
                style.theme_use("clam")
            except Exception:
                pass
            self.configure(bg=p["bg"])
            style.configure(".", background=p["bg"], foreground=p["text"],
                            fieldbackground=p["entry"], bordercolor=p["border"],
                            font=(FONT, 10))
            style.configure("TFrame", background=p["bg"])
            style.configure("Sidebar.TFrame", background=p["surface"])
            style.configure("TLabel", background=p["bg"], foreground=p["text"])
            style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
            style.configure("Header.TLabel", background=p["bg"], foreground=p["text"],
                            font=(FONT, 15, "bold"))
            style.configure("Sub.TLabel", background=p["bg"], foreground=p["muted"],
                            font=(FONT, 10))
            style.configure("Brand.TLabel", background=p["surface"],
                            foreground=p["text"], font=(FONT, 12, "bold"))
            style.configure("Ok.TLabel", background=p["bg"], foreground=p["ok"])
            style.configure("Err.TLabel", background=p["bg"], foreground=p["err"])
            style.configure("Status.TLabel", background=p["surface"],
                            foreground=p["muted"])
            style.configure("TButton", background=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], focuscolor=p["surface"],
                            padding=(10, 5))
            style.map("TButton",
                      background=[("active", p["trough"]), ("disabled", p["bg"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Accent.TButton", background=p["primary"],
                            foreground="#ffffff", padding=(12, 6))
            style.map("Accent.TButton",
                      background=[("active", p["primary_hi"]),
                                  ("disabled", p["border"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Danger.TButton", background=p["err"],
                            foreground="#ffffff", padding=(12, 6))
            style.map("Danger.TButton",
                      background=[("active", p["err"]), ("disabled", p["border"])])
            style.configure("Toggle.TButton", background=p["surface"],
                            foreground=p["text"], padding=(8, 4))
            for name in ("TEntry", "TSpinbox"):
                style.configure(name, fieldbackground=p["entry"], foreground=p["text"],
                                insertcolor=p["text"], bordercolor=p["border"])
            style.configure("TCombobox", fieldbackground=p["entry"],
                            foreground=p["text"], background=p["surface"],
                            arrowcolor=p["text"])
            style.map("TCombobox", fieldbackground=[("readonly", p["entry"])],
                      foreground=[("readonly", p["text"])])
            style.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
            style.map("TCheckbutton", background=[("active", p["bg"])])
            style.configure("TRadiobutton", background=p["bg"], foreground=p["text"])
            style.map("TRadiobutton", background=[("active", p["bg"])])
            style.configure("TLabelframe", background=p["bg"], foreground=p["text"],
                            bordercolor=p["border"])
            style.configure("TLabelframe.Label", background=p["bg"],
                            foreground=p["muted"])
            style.configure("Treeview", background=p["surface"],
                            fieldbackground=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], rowheight=22)
            style.map("Treeview", background=[("selected", p["primary"])],
                      foreground=[("selected", p["sel_fg"])])
            style.configure("Sidebar.Treeview", background=p["surface"],
                            fieldbackground=p["surface"])
            style.configure("TScrollbar", background=p["surface"],
                            troughcolor=p["bg"], bordercolor=p["border"],
                            arrowcolor=p["text"])
            style.configure("TSeparator", background=p["border"])

            for widget, role in list(self._tracked):
                try:
                    if role == "listbox":
                        widget.configure(bg=p["surface"], fg=p["text"],
                                         selectbackground=p["primary"],
                                         selectforeground=p["sel_fg"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"],
                                         borderwidth=0)
                    elif role == "text":
                        widget.configure(bg=p["surface"], fg=p["text"],
                                         insertbackground=p["text"],
                                         selectbackground=p["primary"],
                                         selectforeground=p["sel_fg"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"],
                                         borderwidth=0)
                except Exception:
                    pass

        def toggle_theme(self):
            self.theme = "dark" if self.theme == "light" else "light"
            guiconfig.set_theme(self.theme)
            self._apply_theme()
            self._theme_btn.configure(
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")

        # ---- menu
        def _build_menu(self):
            bar = tk.Menu(self)
            filem = tk.Menu(bar, tearoff=0)
            self._recent_menu = tk.Menu(filem, tearoff=0)
            filem.add_cascade(label="Recent files & folders", menu=self._recent_menu)
            self._fill_recent_menu()
            filem.add_separator()
            filem.add_command(label="Exit", command=self.destroy)
            bar.add_cascade(label="File", menu=filem)

            viewm = tk.Menu(bar, tearoff=0)
            viewm.add_command(label="Toggle dark mode", command=self.toggle_theme)
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=self._about)
            helpm.add_command(label="Open project page (quickopen.ai)",
                              command=lambda: open_with_default_app(PROJECT_URL))
            bar.add_cascade(label="Help", menu=helpm)
            self.configure(menu=bar)

        def _fill_recent_menu(self):
            self._recent_menu.delete(0, "end")
            recent = guiconfig.get_recent()
            if not recent:
                self._recent_menu.add_command(label="(none)", state="disabled")
                return
            for path in recent:
                exists = os.path.exists(path)
                label = path if exists else path + "   (missing)"
                self._recent_menu.add_command(
                    label=label, state="normal" if exists else "disabled",
                    command=(lambda pp=path: open_in_file_manager(pp)))
            self._recent_menu.add_separator()
            self._recent_menu.add_command(label="Clear list",
                                          command=self._clear_recent)

        def _clear_recent(self):
            guiconfig.clear_recent()
            self._fill_recent_menu()

        # ---- layout
        def _build_layout(self):
            top = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 8))
            top.pack(fill="x", side="top")
            ttk.Label(top, text="File Toolkit", style="Brand.TLabel").pack(side="left")
            ttk.Label(top, style="Status.TLabel",
                      text="  offline · open source · by QuickOpen").pack(side="left")
            self._theme_btn = ttk.Button(
                top, style="Toggle.TButton", command=self.toggle_theme,
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")
            self._theme_btn.pack(side="right")

            body = ttk.Frame(self, style="TFrame")
            body.pack(fill="both", expand=True)

            side = ttk.Frame(body, style="Sidebar.TFrame", width=220)
            side.pack(side="left", fill="y")
            side.pack_propagate(False)
            self.nav = ttk.Treeview(side, show="tree", selectmode="browse",
                                    style="Sidebar.Treeview")
            self.nav.pack(fill="both", expand=True, padx=6, pady=6)
            self._nav_ids = {}
            for cat, tools in TOOL_TREE:
                cid = self.nav.insert("", "end", text=cat, open=True, tags=("cat",))
                for tid, label in tools:
                    iid = self.nav.insert(cid, "end", text="   " + label)
                    self._nav_ids[iid] = tid
            self.nav.tag_configure("cat", font=(FONT, 10, "bold"))
            self.nav.bind("<<TreeviewSelect>>", self._on_nav_select)

            main = ttk.Frame(body, style="TFrame", padding=(16, 12))
            main.pack(side="left", fill="both", expand=True)

            head = ttk.Frame(main, style="TFrame")
            head.pack(fill="x")
            self.title_lbl = ttk.Label(head, text="Welcome", style="Header.TLabel")
            self.title_lbl.pack(anchor="w")
            self.desc_lbl = ttk.Label(head, text="", style="Sub.TLabel",
                                      wraplength=720, justify="left")
            self.desc_lbl.pack(anchor="w", pady=(2, 8))
            ttk.Separator(main).pack(fill="x")

            self.container = ttk.Frame(main, style="TFrame")
            self.container.pack(fill="both", expand=True, pady=(10, 8))

            bar = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 6))
            bar.pack(fill="x", side="bottom")
            self.status_lbl = ttk.Label(bar, text="Ready", style="Status.TLabel",
                                        width=16, anchor="w")
            self.status_lbl.pack(side="left")
            self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
            self.openfolder_btn = ttk.Button(bar, text="Open folder",
                                             command=self._open_last_folder)
            self.result_lbl = ttk.Label(bar, text="", style="Status.TLabel",
                                        anchor="w", wraplength=640, justify="left")
            self.result_lbl.pack(side="left", fill="x", expand=True, padx=8)
            self._last_output_dir = None

        def _select_first_tool(self):
            for iid in self._nav_ids:
                self.nav.selection_set(iid)
                self.nav.see(iid)
                break

        def _on_nav_select(self, _e=None):
            sel = self.nav.selection()
            if not sel:
                return
            tid = self._nav_ids.get(sel[0])
            if not tid:
                return  # a category row
            self._show_tool(tid)

        def _show_tool(self, tool_id):
            if self._current is not None:
                self._current.pack_forget()
            panel = self._panels.get(tool_id)
            if panel is None:
                panel = ttk.Frame(self.container, style="TFrame")
                builder = getattr(self, "_panel_" + tool_id, None)
                if builder:
                    builder(panel)
                else:
                    ttk.Label(panel, text="Not implemented.").pack()
                self._panels[tool_id] = panel
                self._apply_theme()
            panel.pack(fill="both", expand=True)
            self._current = panel
            title, desc = self._tool_meta(tool_id)
            self.title_lbl.configure(text=title)
            self.desc_lbl.configure(text=desc)
            self._clear_result()

        def _tool_meta(self, tool_id):
            for _cat, tools in TOOL_TREE:
                for tid, label in tools:
                    if tid == tool_id:
                        return label, TOOL_DESCRIPTIONS.get(tid, "")
            return tool_id, ""

        # ---- background operation runner
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            """Run ``work()`` off the UI thread; call ``on_ok(result)`` back on it.

            Errors are shown inline (FileKitError message, or a generic note),
            never a traceback.  ``button`` is disabled while running; a second
            op is refused while one is in flight.
            """
            if self._busy:
                self._show_error("Please wait — an operation is already running.")
                return
            self._busy = True
            if button is not None:
                try:
                    button.state(["disabled"])
                except Exception:
                    pass
            self._set_status(busy, kind="working")
            self._clear_result(keep_status=True)
            try:
                self.progress.pack(side="left", padx=6)
                self.progress.start(12)
            except Exception:
                pass

            def run():
                try:
                    res, err = work(), None
                except FileKitError as ex:
                    res, err = None, str(ex)
                except Exception as ex:  # never leak a traceback
                    res, err = None, f"Unexpected error: {ex}"
                self.after(0, lambda: finish(res, err))

            def finish(res, err):
                self._busy = False
                try:
                    self.progress.stop()
                    self.progress.pack_forget()
                except Exception:
                    pass
                if button is not None:
                    try:
                        button.state(["!disabled"])
                    except Exception:
                        pass
                if err is not None:
                    self._set_status("error", kind="err")
                    self._show_error(err)
                    return
                self._set_status("done", kind="ok")
                try:
                    on_ok(res)
                except Exception as ex:
                    self._show_error(f"Post-processing error: {ex}")

            threading.Thread(target=run, daemon=True).start()

        # ---- result bar helpers
        def _set_status(self, text, kind="idle"):
            p = self._pal()
            color = {"working": p["primary"], "ok": p["ok"], "err": p["err"]}.get(
                kind, p["muted"])
            self.status_lbl.configure(text=text, foreground=color)

        def _clear_result(self, keep_status=False):
            self.result_lbl.configure(text="")
            self.openfolder_btn.pack_forget()
            if not keep_status:
                self._set_status("Ready")

        def _show_error(self, message):
            self.result_lbl.configure(text="✕ " + message,
                                      foreground=self._pal()["err"])
            self.openfolder_btn.pack_forget()

        def report_success(self, message, outputs=None):
            outputs = outputs or []
            for o in outputs:
                if o:
                    self._history.append(o)
                    guiconfig.add_recent(o)
            self._fill_recent_menu()
            if outputs:
                first = outputs[0]
                self._last_output_dir = (
                    first if os.path.isdir(first)
                    else os.path.dirname(os.path.abspath(first)))
                self.openfolder_btn.pack(side="right")
            self.result_lbl.configure(text="✓ " + message,
                                      foreground=self._pal()["ok"])
            self._set_status("done", kind="ok")

        def _open_last_folder(self):
            if self._last_output_dir:
                open_in_file_manager(self._last_output_dir)

        def remember_input(self, path):
            if path:
                guiconfig.add_recent(path)
                self._fill_recent_menu()

        def _confirm(self, title, message):
            return messagebox.askyesno(title, message, icon="warning", parent=self)

        # ---- About
        def _about(self):
            win = tk.Toplevel(self)
            win.title("About File Toolkit")
            win.configure(bg=self._pal()["bg"])
            win.resizable(False, False)
            frm = ttk.Frame(win, style="TFrame", padding=18)
            frm.pack(fill="both", expand=True)
            ttk.Label(frm, text="File Toolkit", style="Header.TLabel").pack(anchor="w")
            ttk.Label(frm, text=f"Version {APP_VERSION}",
                      style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
            ttk.Label(frm, style="TLabel", justify="left", wraplength=400,
                      text="A fast, fully-offline batch file toolkit — bulk "
                           "rename, find duplicates, checksums, ZIP/7z archives, "
                           "split/join and secure delete.\n\n"
                           "100% AI-built, open source, published on QuickOpen.\n"
                           "Nothing is ever uploaded anywhere.").pack(anchor="w")
            ttk.Label(frm, style="Sub.TLabel", justify="left", wraplength=400,
                      text="Licensed under Apache-2.0. Built on the Python standard "
                           "library plus py7zr (7z) and send2trash (Recycle Bin)."
                      ).pack(anchor="w", pady=(8, 4))
            link = ttk.Label(frm, text="Project page: quickopen.ai",
                             style="Ok.TLabel", cursor="hand2")
            link.pack(anchor="w", pady=(4, 10))
            link.bind("<Button-1>", lambda e: open_with_default_app(PROJECT_URL))
            ttk.Button(frm, text="Close", command=win.destroy).pack(anchor="e")
            win.transient(self)
            win.grab_set()

        # =====================================================================
        # PANELS
        # =====================================================================

        # ---------- Bulk rename ----------
        def _panel_bulkrename(self, parent):
            ttk.Label(parent, text="Add files, set a rule, preview, then Apply:",
                      style="TLabel").pack(anchor="w")
            flist = FileList(parent, self, allow_dirs=False,
                             on_change=lambda: refresh())
            flist.pack(fill="x", pady=6)

            rulebox = ttk.Labelframe(parent, text="Rule", padding=8)
            rulebox.pack(fill="x", pady=6)

            def row(master):
                r = ttk.Frame(master, style="TFrame")
                r.pack(fill="x", pady=2)
                return r

            find_var = tk.StringVar()
            repl_var = tk.StringVar()
            regex_var = tk.BooleanVar(value=False)
            r = row(rulebox)
            ttk.Label(r, text="Find", width=10).pack(side="left")
            ttk.Entry(r, textvariable=find_var, width=18).pack(side="left")
            ttk.Label(r, text="Replace").pack(side="left", padx=(10, 4))
            ttk.Entry(r, textvariable=repl_var, width=18).pack(side="left")
            ttk.Checkbutton(r, text="regex", variable=regex_var).pack(side="left", padx=8)

            prefix_var = tk.StringVar()
            suffix_var = tk.StringVar()
            r = row(rulebox)
            ttk.Label(r, text="Prefix", width=10).pack(side="left")
            ttk.Entry(r, textvariable=prefix_var, width=18).pack(side="left")
            ttk.Label(r, text="Suffix").pack(side="left", padx=(10, 4))
            ttk.Entry(r, textvariable=suffix_var, width=18).pack(side="left")

            case_var = tk.StringVar(value="(keep)")
            ext_var = tk.StringVar()
            r = row(rulebox)
            ttk.Label(r, text="Case", width=10).pack(side="left")
            ttk.Combobox(r, textvariable=case_var, state="readonly", width=12,
                         values=["(keep)", "lower", "upper", "title", "capitalize"]
                         ).pack(side="left")
            ttk.Label(r, text="New ext").pack(side="left", padx=(10, 4))
            ttk.Entry(r, textvariable=ext_var, width=10).pack(side="left")

            num_var = tk.BooleanVar(value=False)
            start_var = tk.StringVar(value="1")
            pad_var = tk.StringVar(value="3")
            r = row(rulebox)
            ttk.Checkbutton(r, text="Number", variable=num_var).pack(side="left")
            ttk.Label(r, text="start").pack(side="left", padx=(10, 2))
            ttk.Spinbox(r, from_=0, to=999999, textvariable=start_var,
                        width=6).pack(side="left")
            ttk.Label(r, text="pad").pack(side="left", padx=(10, 2))
            ttk.Spinbox(r, from_=0, to=12, textvariable=pad_var, width=4).pack(side="left")
            ttk.Label(rulebox, style="Muted.TLabel",
                      text="Numbering fills a {n} token in prefix/suffix, or is "
                           "appended if there is none.").pack(anchor="w", pady=(4, 0))

            table = ttk.Treeview(parent, columns=("old", "new"), show="headings",
                                 height=8)
            table.heading("old", text="Current name")
            table.heading("new", text="New name")
            table.column("old", width=280)
            table.column("new", width=280)
            table.pack(fill="both", expand=True, pady=6)

            def build_rule():
                pad = int(pad_var.get() or 0)
                start = int(start_var.get() or 0)
                case = None if case_var.get() == "(keep)" else case_var.get()
                return RenameRule(
                    find=find_var.get(), replace=repl_var.get(),
                    regex=regex_var.get(), case=case,
                    prefix=prefix_var.get(), suffix=suffix_var.get(),
                    number=num_var.get(), number_start=start, number_pad=pad,
                    new_ext=(ext_var.get().strip() or None))

            def refresh(*_):
                table.delete(*table.get_children())
                files = flist.items()
                if not files:
                    return
                try:
                    plan = plan_rename(files, build_rule())
                except FileKitError as ex:
                    self._show_error(str(ex))
                    return
                self._clear_result()
                for old, new in plan:
                    table.insert("", "end", values=(os.path.basename(old),
                                                     os.path.basename(new)))

            for v in (find_var, repl_var, prefix_var, suffix_var, case_var,
                      ext_var, num_var, start_var, pad_var, regex_var):
                v.trace_add("write", refresh)

            btns = ttk.Frame(parent, style="TFrame")
            btns.pack(fill="x", pady=4)
            ttk.Button(btns, text="Refresh preview", command=refresh).pack(side="left")
            run = ttk.Button(btns, text="Apply rename", style="Accent.TButton")
            run.pack(side="left", padx=8)

            def go():
                files = flist.items()
                if not files:
                    self._show_error("Add at least one file.")
                    return
                try:
                    plan = plan_rename(files, build_rule())
                except FileKitError as ex:
                    self._show_error(str(ex))
                    return
                changed = [(o, n) for o, n in plan if o != n]
                if not changed:
                    self._show_error("The rule doesn't change any names.")
                    return
                if not self._confirm(
                        "Apply rename",
                        f"Rename {len(changed)} file(s) on disk now?"):
                    return
                self._bg(lambda: apply_rename(plan),
                         lambda applied: (self.report_success(
                             f"Renamed {len(applied)} file(s).",
                             [applied[0][1]] if applied else None),
                             refresh()),
                         button=run)

            run.configure(command=go)

        # ---------- Find duplicates ----------
        def _panel_dedupe(self, parent):
            src = FileRow(parent, self, "Folder", mode="dir",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=4)
            scan = ttk.Button(parent, text="Scan for duplicates",
                              style="Accent.TButton")
            scan.pack(anchor="w", pady=4)

            tree = ttk.Treeview(parent, columns=("size",), show="tree headings",
                                height=12)
            tree.heading("#0", text="File")
            tree.heading("size", text="Size")
            tree.column("size", width=100, anchor="e")
            tree.pack(fill="both", expand=True, pady=6)
            self._dedupe_groups = []

            def do_scan():
                folder = src.get()
                if not folder:
                    self._show_error("Choose a folder to scan.")
                    return

                def ok(groups):
                    self._dedupe_groups = groups
                    tree.delete(*tree.get_children())
                    dupes = sum(len(g) - 1 for g in groups)
                    for i, g in enumerate(groups, 1):
                        size = human_size(os.path.getsize(g[0]))
                        gid = tree.insert("", "end",
                                          text=f"Group {i} — {len(g)} copies",
                                          values=(size,), open=True)
                        for p in g:
                            tree.insert(gid, "end", text=p, values=(size,))
                    self.report_success(
                        f"Found {len(groups)} group(s), {dupes} redundant file(s).")
                self._bg(lambda: find_duplicates(folder), ok, button=scan)

            scan.configure(command=do_scan)

            def remove(keep):
                if not self._dedupe_groups:
                    self._show_error("Scan first.")
                    return
                dupes = sum(len(g) - 1 for g in self._dedupe_groups)
                if not dupes:
                    self._show_error("No duplicates to remove.")
                    return
                if not self._confirm(
                        "Remove duplicates",
                        f"Send {dupes} redundant file(s) to the Recycle Bin?\n"
                        f"(keeping the {keep} of each group)"):
                    return
                groups = self._dedupe_groups
                self._bg(
                    lambda: remove_duplicates(groups, keep=keep, to_trash=True),
                    lambda removed: (self.report_success(
                        f"Sent {len(removed)} file(s) to the Recycle Bin."),
                        do_scan()))

            btns = ttk.Frame(parent, style="TFrame")
            btns.pack(fill="x")
            ttk.Button(btns, text="Recycle duplicates (keep first)",
                       style="Danger.TButton",
                       command=lambda: remove("first")).pack(side="left")
            ttk.Button(btns, text="Keep last instead",
                       command=lambda: remove("last")).pack(side="left", padx=8)

        # ---------- Hash / verify ----------
        def _panel_hashverify(self, parent):
            box1 = ttk.Labelframe(parent, text="Write SHA256SUMS for a folder",
                                  padding=8)
            box1.pack(fill="x", pady=6)
            src = FileRow(box1, self, "Folder", mode="dir",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=4)
            out = FileRow(box1, self, "Sums file", mode="save",
                          filetypes=[("Sums", "*SUMS SHA256SUMS *.sha256"),
                                     ("All files", "*.*")])
            out.pack(fill="x", pady=4)
            write = ttk.Button(box1, text="Write checksums", style="Accent.TButton")
            write.pack(anchor="w", pady=4)

            def do_write():
                folder, dest = src.get(), out.get()
                if not folder:
                    self._show_error("Choose a folder.")
                    return
                if not dest:
                    dest = os.path.join(folder, "SHA256SUMS")
                self._bg(lambda: (write_sha256sums(folder, dest), dest)[1],
                         lambda d: self.report_success(
                             f"Wrote checksums → {d}", [d]), button=write)

            write.configure(command=do_write)

            box2 = ttk.Labelframe(parent, text="Verify a sums file", padding=8)
            box2.pack(fill="x", pady=6)
            vsrc = FileRow(box2, self, "Sums file", mode="open",
                           on_change=lambda v: self.remember_input(v))
            vsrc.pack(fill="x", pady=4)
            verify = ttk.Button(box2, text="Verify", style="Accent.TButton")
            verify.pack(anchor="w", pady=4)

            body = ttk.Frame(parent, style="TFrame")
            body.pack(fill="both", expand=True, pady=6)
            txt = tk.Text(body, wrap="none", height=10)
            sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            txt.pack(side="left", fill="both", expand=True)
            self.track(txt, "text")

            def do_verify():
                sf = vsrc.get()
                if not sf:
                    self._show_error("Choose a sums file.")
                    return

                def ok(results):
                    txt.delete("1.0", "end")
                    okc = sum(1 for r in results if r["status"] == "ok")
                    for r in results:
                        if r["status"] != "ok":
                            txt.insert("end",
                                       f"{r['status'].upper():8} {r['path']}\n")
                    bad = len(results) - okc
                    txt.insert("1.0", f"{okc}/{len(results)} OK, {bad} problem(s)\n\n")
                    if bad:
                        self._show_error(f"{bad} file(s) failed or missing.")
                    else:
                        self.report_success(f"All {okc} file(s) verified OK.")
                self._bg(lambda: verify_sums(sf), ok, button=verify)

            verify.configure(command=do_verify)

        # ---------- Create archive ----------
        def _panel_archivecreate(self, parent):
            ttk.Label(parent, text="Add files/folders, choose a format, then create:",
                      style="TLabel").pack(anchor="w")
            flist = FileList(parent, self, allow_dirs=True)
            flist.pack(fill="both", expand=True, pady=6)

            r = ttk.Frame(parent, style="TFrame")
            r.pack(fill="x", pady=4)
            ttk.Label(r, text="Format", width=14, anchor="w").pack(side="left")
            fmt = tk.StringVar(value="zip")
            ttk.Radiobutton(r, text="ZIP", value="zip", variable=fmt).pack(side="left")
            ttk.Radiobutton(r, text="7z", value="7z", variable=fmt).pack(side="left", padx=8)
            ttk.Label(r, text="7z password (optional)").pack(side="left", padx=(16, 4))
            pw = tk.StringVar()
            ttk.Entry(r, textvariable=pw, show="•", width=16).pack(side="left")

            out = FileRow(parent, self, "Save as", mode="save",
                          filetypes=ARCHIVE_TYPES)
            out.pack(fill="x", pady=4)
            run = ttk.Button(parent, text="Create archive", style="Accent.TButton")
            run.pack(anchor="w", pady=6)

            def go():
                paths = flist.items()
                dest = out.get()
                if not paths:
                    self._show_error("Add at least one file or folder.")
                    return
                if not dest:
                    self._show_error("Choose an output file.")
                    return
                if fmt.get() == "7z":
                    if not dest.lower().endswith(".7z"):
                        dest += ".7z"
                    password = pw.get() or None
                    work = lambda: sevenz_create(paths, dest, password=password)
                else:
                    if not dest.lower().endswith(".zip"):
                        dest += ".zip"
                    work = lambda: zip_create(paths, dest)
                self._bg(work, lambda o: self.report_success(
                    f"Created {o} ({human_size(os.path.getsize(o))})", [o]),
                    button=run)

            run.configure(command=go)

        # ---------- Extract archive ----------
        def _panel_archiveextract(self, parent):
            src = FileRow(parent, self, "Archive", mode="open",
                          filetypes=ARCHIVE_TYPES,
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=4)
            dest = FileRow(parent, self, "Extract to", mode="dir")
            dest.pack(fill="x", pady=4)
            r = ttk.Frame(parent, style="TFrame")
            r.pack(fill="x", pady=4)
            ttk.Label(r, text="7z password", width=14, anchor="w").pack(side="left")
            pw = tk.StringVar()
            ttk.Entry(r, textvariable=pw, show="•", width=18).pack(side="left")
            ttk.Label(parent, style="Muted.TLabel",
                      text="Leave the password blank for ZIP or unencrypted 7z."
                      ).pack(anchor="w")
            run = ttk.Button(parent, text="Extract", style="Accent.TButton")
            run.pack(anchor="w", pady=6)

            def go():
                arc, d = src.get(), dest.get()
                if not arc or not d:
                    self._show_error("Choose an archive and a destination folder.")
                    return
                if arc.lower().endswith(".7z"):
                    password = pw.get() or None
                    work = lambda: sevenz_extract(arc, d, password=password)
                else:
                    work = lambda: zip_extract(arc, d)
                self._bg(work, lambda names: self.report_success(
                    f"Extracted {len(names)} item(s) → {d}", [d]), button=run)

            run.configure(command=go)

        # ---------- Split ----------
        def _panel_split(self, parent):
            src = FileRow(parent, self, "Input file", mode="open",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=4)
            dest = FileRow(parent, self, "Output folder", mode="dir")
            dest.pack(fill="x", pady=4)
            r = ttk.Frame(parent, style="TFrame")
            r.pack(fill="x", pady=4)
            ttk.Label(r, text="Part size", width=14, anchor="w").pack(side="left")
            size = tk.StringVar(value="10M")
            ttk.Entry(r, textvariable=size, width=12).pack(side="left")
            ttk.Label(r, style="Muted.TLabel",
                      text="  e.g. 700M, 1G, 5000000").pack(side="left")
            run = ttk.Button(parent, text="Split file", style="Accent.TButton")
            run.pack(anchor="w", pady=6)

            def go():
                inp, d, sz = src.get(), dest.get(), size.get()
                if not inp or not d:
                    self._show_error("Choose an input file and an output folder.")
                    return
                from .common import parse_size
                try:
                    nbytes = parse_size(sz)
                except FileKitError as ex:
                    self._show_error(str(ex))
                    return
                self._bg(lambda: split_file(inp, nbytes, d),
                         lambda parts: self.report_success(
                             f"Wrote {len(parts)} part(s) → {d}", [d]),
                         button=run)

            run.configure(command=go)

        # ---------- Join ----------
        def _panel_join(self, parent):
            ttk.Label(parent, text="Add the parts (in order) and choose the output:",
                      style="TLabel").pack(anchor="w")
            flist = FileList(parent, self, allow_dirs=False)
            flist.pack(fill="both", expand=True, pady=6)
            out = FileRow(parent, self, "Save as", mode="save")
            out.pack(fill="x", pady=4)
            run = ttk.Button(parent, text="Join files", style="Accent.TButton")
            run.pack(anchor="w", pady=6)

            def go():
                parts = flist.items()
                dest = out.get()
                if not parts:
                    self._show_error("Add the parts to join.")
                    return
                if not dest:
                    self._show_error("Choose an output file.")
                    return
                self._bg(lambda: join_files(sorted(parts), dest),
                         lambda o: self.report_success(
                             f"Joined → {o} ({human_size(os.path.getsize(o))})", [o]),
                         button=run)

            run.configure(command=go)

        # ---------- Secure delete ----------
        def _panel_securedelete(self, parent):
            src = FileRow(parent, self, "File", mode="open",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=4)
            r = ttk.Frame(parent, style="TFrame")
            r.pack(fill="x", pady=4)
            ttk.Label(r, text="Passes", width=14, anchor="w").pack(side="left")
            passes = tk.StringVar(value="1")
            ttk.Spinbox(r, from_=1, to=35, textvariable=passes, width=5).pack(side="left")
            ttk.Label(parent, style="Muted.TLabel", justify="left", wraplength=680,
                      text="Overwrites the file's bytes, then deletes it. NOTE: on "
                           "SSDs and copy-on-write/journaling filesystems (and with "
                           "backups or snapshots) this cannot guarantee the old data "
                           "is unrecoverable. Use full-disk encryption for real "
                           "assurance.").pack(anchor="w", pady=(4, 4))
            run = ttk.Button(parent, text="Overwrite & delete",
                             style="Danger.TButton")
            run.pack(anchor="w", pady=6)

            def go():
                inp = src.get()
                if not inp:
                    self._show_error("Choose a file.")
                    return
                try:
                    n = int(passes.get())
                except ValueError:
                    self._show_error("Passes must be a whole number.")
                    return
                if not self._confirm(
                        "Secure delete",
                        f"Permanently overwrite and delete:\n{inp}\n\n"
                        "This cannot be undone. Continue?"):
                    return
                self._bg(lambda: secure_delete(inp, passes=n),
                         lambda p: (self.report_success(
                             f"Securely deleted {os.path.basename(p)}."),
                             src.set("")), button=run)

            run.configure(command=go)

        # ---------- Trash ----------
        def _panel_trash(self, parent):
            src = FileRow(parent, self, "File / folder", mode="open",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=4)
            ttk.Label(parent, style="Muted.TLabel",
                      text="Moves the item to the OS Recycle Bin / Trash "
                           "(recoverable). Use Browse for a file, or paste a folder "
                           "path.").pack(anchor="w", pady=(2, 6))
            run = ttk.Button(parent, text="Send to Recycle Bin",
                             style="Danger.TButton")
            run.pack(anchor="w", pady=6)

            def go():
                inp = src.get()
                if not inp:
                    self._show_error("Choose a file or folder.")
                    return
                if not self._confirm(
                        "Send to Recycle Bin",
                        f"Move to the Recycle Bin?\n{inp}"):
                    return
                self._bg(lambda: to_recycle(inp),
                         lambda p: (self.report_success(
                             f"Sent to the Recycle Bin: {os.path.basename(p)}."),
                             src.set("")), button=run)

            run.configure(command=go)

    return App


def main():
    """Entry point: build the root window and run. Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display (e.g. a server) it prints a friendly note and returns 0.
    """
    try:
        import tkinter as tk
    except Exception as exc:
        print(f"{APP_NAME}: a graphical environment with tkinter is required "
              f"to run the GUI ({exc}).")
        return 0

    try:
        App = build_app()
        app = App()
    except tk.TclError as exc:
        print(f"{APP_NAME}: no graphical display available — cannot start the "
              f"GUI here ({exc}). This app is intended for the Windows desktop.")
        return 0
    except Exception as exc:
        print(f"{APP_NAME}: could not start the GUI ({exc}).")
        return 1

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
