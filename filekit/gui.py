#!/usr/bin/env python3
r"""File Toolkit -- an Aura (QuickOpen design system) GUI on top of ``filekit``.

A single Aura window: the sidebar lists the tools (Bulk Rename, Find
Duplicates, Hash/Verify, Create/Extract Archive, Split/Join, Secure Delete,
Recycle Bin) and the main panel swaps to the selected tool.  Every operation
calls the tested core library (never re-implements file logic) and runs on a
background thread so the UI stays responsive; results are reported in the Aura
status bar (a message plus an "Open folder" button on success, or the
``FileKitError`` text -- never a traceback -- on failure).

Design goals baked in here (mirrors the QuickOpen house style):
  * built on the vendored ``filekit/aura.py`` design system, which layers the
    quickopen.ai look (deep space + light) over CustomTkinter.  Runtime deps:
    ``customtkinter`` (+ ``darkdetect``) -- declared in requirements.txt; the
    PyInstaller build adds ``--collect-all customtkinter``.
  * Importing this module does nothing.  Only :func:`main` builds a root
    window, and it degrades gracefully (prints a note, returns 0) with no
    display or with customtkinter missing.
  * Frozen-exe safe: bundled assets are resolved via ``sys._MEIPASS`` / the
    exe directory when ``sys.frozen`` is set -- never ``__file__``.
  * Destructive actions (delete duplicates, secure-delete, recycle) always ask
    for confirmation first (native ``askyesno`` dialogs).

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import threading

# NOTE: tkinter/customtkinter are imported lazily inside main()/build_app so
# that merely importing this module (e.g. during packaging or on a headless CI
# box) never fails.

APP_NAME = "File Toolkit"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "File Toolkit — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"
ACCENT = "#17914b"      # UI-accent registry (ui/aurakit/README.md)

ALL_FILES = [("All files", "*.*")]
ARCHIVE_TYPES = [("Archives", "*.zip *.7z"), ("ZIP", "*.zip"),
                 ("7z", "*.7z"), ("All files", "*.*")]

TOOL_DESCRIPTIONS = {
    "rename": "Rename many files at once — find/replace, regex, numbering, "
              "case, prefix/suffix, extension. Live preview; nothing changes "
              "until you click Apply.",
    "dedupe": "Scan a folder for byte-identical files (size pre-filter, then "
              "hash). Review the groups, then send the redundant copies to the "
              "Recycle Bin.",
    "hash": "Compute a SHA256SUMS manifest for a folder, or verify one and "
            "spot any tampered or missing files.",
    "archive": "Package files/folders into a .zip or an (optionally "
               "password-protected) .7z archive.",
    "extract": "Extract a .zip or .7z archive into a folder.",
    "split": "Break a large file into fixed-size parts (+ a manifest) so it "
             "fits on smaller media or uploads.",
    "join": "Reassemble parts back into the original file, verified against "
            "the manifest.",
    "shred": "Overwrite a file's bytes, then delete it. Best-effort only on "
             "SSDs/copy-on-write filesystems — see the note.",
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
# The app (built lazily; tkinter/customtkinter imported only inside build_app)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to live GUI imports.

    Kept inside a function so this module imports cleanly without a display
    (and without customtkinter installed).
    """
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import customtkinter as ctk

    from . import aura, guiconfig
    from .errors import FileKitError
    from .rename import RenameRule, plan_rename, apply_rename
    from .dedupe import find_duplicates, remove_duplicates
    from .hashing import write_sha256sums, verify_sums
    from .archive import zip_create, zip_extract, sevenz_create, sevenz_extract
    from .splitjoin import split_file, join_files
    from .securedelete import secure_delete, to_recycle

    # -- small reusable widgets ------------------------------------------

    class FileRow(ctk.CTkFrame):
        """A labelled path field + Browse button. ``mode`` picks the dialog."""

        def __init__(self, master, app, label, mode="open", filetypes=None,
                     on_change=None):
            super().__init__(master, fg_color="transparent")
            self.app = app
            self.mode = mode
            self.filetypes = filetypes or ALL_FILES
            self.var = tk.StringVar()
            ctk.CTkLabel(self, text=label, width=104, anchor="w",
                         font=aura.font()).pack(side="left")
            # labelled row -> no placeholder, so a textvariable is safe here
            aura.AuraEntry(self, textvariable=self.var).pack(
                side="left", fill="x", expand=True, padx=(6, 8))
            aura.AuraButton(self, "Browse…", kind="secondary", width=96,
                            command=self._browse).pack(side="left")
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

    class FileList(ctk.CTkFrame):
        """A multi-file listbox with Add / Add folder / Remove / Clear."""

        def __init__(self, master, app, filetypes=None, allow_dirs=True,
                     on_change=None, height=8):
            super().__init__(master, fg_color="transparent")
            self.app = app
            self.filetypes = filetypes or ALL_FILES
            self.on_change = on_change
            box = ctk.CTkFrame(self, fg_color="transparent")
            box.pack(fill="both", expand=True)
            self.listbox = tk.Listbox(box, height=height, activestyle="none",
                                      selectmode="extended", exportselection=False)
            sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
            self.listbox.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.listbox.pack(side="left", fill="both", expand=True)
            aura.track(self.listbox, "listbox")

            btns = ctk.CTkFrame(self, fg_color="transparent")
            btns.pack(fill="x", pady=(8, 0))
            aura.AuraButton(btns, "Add files…", command=self.add).pack(side="left")
            if allow_dirs:
                aura.AuraButton(btns, "Add folder…", kind="secondary",
                                command=self.add_folder).pack(side="left", padx=(8, 0))
            aura.AuraButton(btns, "Remove", kind="secondary",
                            command=self.remove).pack(side="left", padx=(8, 0))
            aura.AuraButton(btns, "Clear", kind="ghost",
                            command=self.clear).pack(side="left", padx=(8, 0))

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

    class App(aura.AuraApp):
        def __init__(self):
            super().__init__(
                title=WINDOW_TITLE, app_name=APP_NAME, accent=ACCENT,
                theme=guiconfig.get_theme(),
                icon_png=asset_path("file-toolkit.png"), version=APP_VERSION,
                tagline="offline file tools",
                on_theme_change=guiconfig.set_theme,
                size=(1080, 680), min_size=(900, 560))

            self._busy = False
            self._img_refs_gui = []    # keep PhotoImage refs alive
            self._history = []         # session output paths
            self._last_output_dir = None

            self._set_icon()
            self._build_menu()

            # indeterminate shimmer while a background op runs (header, right)
            self._progress = aura.ProgressBar(self.header_actions,
                                              mode="indeterminate", width=150)

            # success actions live in the Aura status bar
            self.openfolder_btn = aura.AuraButton(
                self.statusbar.actions, "Open folder", kind="secondary",
                height=30, command=self._open_last_folder)

            self.add_section("rename", "Bulk rename", "✎", self._panel_rename)
            self.add_section("dedupe", "Duplicates", "⊚", self._panel_dedupe)
            self.add_section("hash", "Hash / Verify", "▦", self._panel_hash)
            self.add_section("archive", "Create archive", "⛁",
                             self._panel_archive)
            self.add_section("extract", "Extract archive", "↧",
                             self._panel_extract)
            self.add_section("split", "Split file", "✂", self._panel_split)
            self.add_section("join", "Join files", "⇄", self._panel_join)
            self.add_section("shred", "Secure delete", "✳", self._panel_shred)
            self.add_section("trash", "Recycle Bin", "↻", self._panel_trash)
            self.add_section("about", "About", "ℹ", self._panel_about)
            self.show("rename")
            self.protocol("WM_DELETE_WINDOW", self.destroy)

        def show(self, sid):
            super().show(sid)
            # switching tools resets the result bar (matches the old app)
            if getattr(self, "statusbar", None) is not None:
                self._clear_result()

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("file-toolkit.ico")
                if ico and os.name == "nt":
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("file-toolkit.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs_gui.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- menu (native menus stay; theme lives in the sidebar toggle too)
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
            viewm.add_command(
                label="Toggle dark mode",
                command=lambda: self.set_theme(
                    "light" if self.theme == "dark" else "dark"))
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=lambda: self.show("about"))
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
            self.openfolder_btn.pack_forget()
            try:
                self._progress.pack(side="left", padx=(0, 4))
                self._progress.start()
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
                    self._progress.stop()
                    self._progress.pack_forget()
                except Exception:
                    pass
                if button is not None:
                    try:
                        button.state(["!disabled"])
                    except Exception:
                        pass
                if err is not None:
                    self._show_error(err)
                    return
                try:
                    on_ok(res)
                except Exception as ex:
                    self._show_error(f"Post-processing error: {ex}")

            threading.Thread(target=run, daemon=True).start()

        # ---- result bar helpers (thin wrappers over the Aura status bar)
        def _set_status(self, text, kind="idle"):
            self.set_status(text, kind)

        def _clear_result(self, keep_status=False):
            self.openfolder_btn.pack_forget()
            if not keep_status:
                self.set_status("Ready")

        def _show_error(self, message):
            self.openfolder_btn.pack_forget()
            self.set_error(message)

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
                self.openfolder_btn.pack(side="left")
            self.set_success(message)

        def _open_last_folder(self):
            if self._last_output_dir:
                open_in_file_manager(self._last_output_dir)

        def remember_input(self, path):
            if path:
                guiconfig.add_recent(path)
                self._fill_recent_menu()

        def _confirm(self, title, message):
            return messagebox.askyesno(title, message, icon="warning", parent=self)

        @staticmethod
        def _describe(parent, tool_id):
            aura.Caption(parent, TOOL_DESCRIPTIONS.get(tool_id, ""),
                         wraplength=760, justify="left").pack(
                anchor="w", pady=(0, 10))

        # =====================================================================
        # PANELS (lazy section builders)
        # =====================================================================

        # ---------- Bulk rename ----------
        def _panel_rename(self, parent):
            self._describe(parent, "rename")
            flist = FileList(parent, self, allow_dirs=False, height=5,
                             on_change=lambda: refresh())
            flist.pack(fill="x", pady=(0, 10))

            rulebox = aura.Card(parent, title="Rule", padding=12)
            rulebox.pack(fill="x", pady=(0, 10))

            def row(master):
                r = ctk.CTkFrame(master, fg_color="transparent")
                r.pack(fill="x", pady=3)
                return r

            def lab(master, text, w=64, **pack):
                ctk.CTkLabel(master, text=text, width=w, anchor="w",
                             font=aura.font()).pack(side="left", **pack)

            find_var = tk.StringVar()
            repl_var = tk.StringVar()
            regex_var = tk.BooleanVar(value=False)
            r = row(rulebox.body)
            lab(r, "Find")
            aura.AuraEntry(r, textvariable=find_var, width=160).pack(side="left")
            lab(r, "Replace", padx=(14, 6))
            aura.AuraEntry(r, textvariable=repl_var, width=160).pack(side="left")
            ctk.CTkCheckBox(r, text="regex", variable=regex_var,
                            font=aura.font()).pack(side="left", padx=12)

            prefix_var = tk.StringVar()
            suffix_var = tk.StringVar()
            r = row(rulebox.body)
            lab(r, "Prefix")
            aura.AuraEntry(r, textvariable=prefix_var, width=160).pack(side="left")
            lab(r, "Suffix", padx=(14, 6))
            aura.AuraEntry(r, textvariable=suffix_var, width=160).pack(side="left")

            case_var = tk.StringVar(value="(keep)")
            ext_var = tk.StringVar()
            r = row(rulebox.body)
            lab(r, "Case")
            aura.AuraCombo(r, variable=case_var, state="readonly", width=160,
                           values=["(keep)", "lower", "upper", "title",
                                   "capitalize"]).pack(side="left")
            lab(r, "New ext", padx=(14, 6))
            aura.AuraEntry(r, textvariable=ext_var, width=90).pack(side="left")

            num_var = tk.BooleanVar(value=False)
            start_var = tk.StringVar(value="1")
            pad_var = tk.StringVar(value="3")
            r = row(rulebox.body)
            ctk.CTkCheckBox(r, text="Number", variable=num_var,
                            font=aura.font()).pack(side="left")
            lab(r, "start", w=36, padx=(14, 2))
            ttk.Spinbox(r, from_=0, to=999999, textvariable=start_var,
                        width=6).pack(side="left")
            lab(r, "pad", w=28, padx=(14, 2))
            ttk.Spinbox(r, from_=0, to=12, textvariable=pad_var,
                        width=4).pack(side="left")
            aura.Caption(rulebox.body,
                         "Numbering fills a {n} token in prefix/suffix, or is "
                         "appended if there is none.").pack(anchor="w",
                                                            pady=(6, 0))

            # action row packed to the bottom FIRST so it can never be pushed
            # off-screen; the preview table then takes whatever is left.
            btns = ctk.CTkFrame(parent, fg_color="transparent")
            btns.pack(side="bottom", fill="x", pady=(8, 0))
            aura.AuraButton(btns, "Refresh preview", kind="secondary",
                            command=lambda: refresh()).pack(side="left")
            run = aura.AuraButton(btns, "Apply rename")
            run.pack(side="left", padx=8)

            table = ttk.Treeview(parent, columns=("old", "new"),
                                 show="headings", height=4)
            table.heading("old", text=aura.spaced("Current name"), anchor="w")
            table.heading("new", text=aura.spaced("New name"), anchor="w")
            table.column("old", width=280, anchor="w")
            table.column("new", width=280, anchor="w")
            table.pack(fill="both", expand=True)

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
            self._describe(parent, "dedupe")
            src = FileRow(parent, self, "Folder", mode="dir",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=(0, 8))
            scan = aura.AuraButton(parent, "Scan for duplicates")
            scan.pack(anchor="w", pady=(0, 8))

            # action row anchored at the bottom so the expanding tree can
            # never squash it off-screen
            btns = ctk.CTkFrame(parent, fg_color="transparent")
            btns.pack(side="bottom", fill="x", pady=(8, 0))

            tree = ttk.Treeview(parent, columns=("size",), show="tree headings",
                                height=6)
            tree.heading("#0", text=aura.spaced("File"), anchor="w")
            tree.heading("size", text=aura.spaced("Size"), anchor="w")
            tree.column("size", width=100, anchor="e")
            tree.pack(fill="both", expand=True)
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

            aura.AuraButton(btns, "Recycle duplicates (keep first)",
                            kind="danger",
                            command=lambda: remove("first")).pack(side="left")
            aura.AuraButton(btns, "Keep last instead", kind="secondary",
                            command=lambda: remove("last")).pack(
                side="left", padx=8)

        # ---------- Hash / verify ----------
        def _panel_hash(self, parent):
            self._describe(parent, "hash")
            box1 = aura.Card(parent, title="Write SHA256SUMS for a folder",
                             padding=12)
            box1.pack(fill="x", pady=(0, 10))
            src = FileRow(box1.body, self, "Folder", mode="dir",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=4)
            out = FileRow(box1.body, self, "Sums file", mode="save",
                          filetypes=[("Sums", "*SUMS SHA256SUMS *.sha256"),
                                     ("All files", "*.*")])
            out.pack(fill="x", pady=4)
            write = aura.AuraButton(box1.body, "Write checksums")
            write.pack(anchor="w", pady=(6, 2))

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

            box2 = aura.Card(parent, title="Verify a sums file", padding=12)
            box2.pack(fill="x", pady=(0, 10))
            vsrc = FileRow(box2.body, self, "Sums file", mode="open",
                           on_change=lambda v: self.remember_input(v))
            vsrc.pack(fill="x", pady=4)
            verify = aura.AuraButton(box2.body, "Verify")
            verify.pack(anchor="w", pady=(6, 2))

            body = ctk.CTkFrame(parent, fg_color="transparent")
            body.pack(fill="both", expand=True)
            txt = tk.Text(body, wrap="none", height=10)
            sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            txt.pack(side="left", fill="both", expand=True)
            aura.track(txt, "text")

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
        def _panel_archive(self, parent):
            self._describe(parent, "archive")
            flist = FileList(parent, self, allow_dirs=True)
            flist.pack(fill="both", expand=True, pady=(0, 10))

            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(r, text="Format", width=104, anchor="w",
                         font=aura.font()).pack(side="left")
            fmt_seg = aura.SegmentedControl(r, values=["ZIP", "7z"], width=140)
            fmt_seg.set("ZIP")
            fmt_seg.pack(side="left", padx=(6, 0))
            ctk.CTkLabel(r, text="7z password (optional)",
                         font=aura.font()).pack(side="left", padx=(18, 6))
            pw = tk.StringVar()
            aura.AuraEntry(r, textvariable=pw, show="•",
                           width=150).pack(side="left")

            out = FileRow(parent, self, "Save as", mode="save",
                          filetypes=ARCHIVE_TYPES)
            out.pack(fill="x", pady=(0, 8))
            run = aura.AuraButton(parent, "Create archive")
            run.pack(anchor="w", pady=(0, 4))

            def go():
                paths = flist.items()
                dest = out.get()
                if not paths:
                    self._show_error("Add at least one file or folder.")
                    return
                if not dest:
                    self._show_error("Choose an output file.")
                    return
                if fmt_seg.get() == "7z":
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
        def _panel_extract(self, parent):
            self._describe(parent, "extract")
            src = FileRow(parent, self, "Archive", mode="open",
                          filetypes=ARCHIVE_TYPES,
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=(0, 8))
            dest = FileRow(parent, self, "Extract to", mode="dir")
            dest.pack(fill="x", pady=(0, 8))
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(r, text="7z password", width=104, anchor="w",
                         font=aura.font()).pack(side="left")
            pw = tk.StringVar()
            aura.AuraEntry(r, textvariable=pw, show="•",
                           width=170).pack(side="left", padx=(6, 0))
            aura.Caption(parent,
                         "Leave the password blank for ZIP or unencrypted 7z."
                         ).pack(anchor="w", pady=(4, 0))
            run = aura.AuraButton(parent, "Extract")
            run.pack(anchor="w", pady=(10, 4))

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
            self._describe(parent, "split")
            src = FileRow(parent, self, "Input file", mode="open",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=(0, 8))
            dest = FileRow(parent, self, "Output folder", mode="dir")
            dest.pack(fill="x", pady=(0, 8))
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(r, text="Part size", width=104, anchor="w",
                         font=aura.font()).pack(side="left")
            size = tk.StringVar(value="10M")
            aura.AuraEntry(r, textvariable=size, width=110).pack(
                side="left", padx=(6, 0))
            aura.Caption(r, "e.g. 700M, 1G, 5000000").pack(
                side="left", padx=(10, 0))
            run = aura.AuraButton(parent, "Split file")
            run.pack(anchor="w", pady=(10, 4))

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
            self._describe(parent, "join")
            flist = FileList(parent, self, allow_dirs=False)
            flist.pack(fill="both", expand=True, pady=(0, 10))
            out = FileRow(parent, self, "Save as", mode="save")
            out.pack(fill="x", pady=(0, 8))
            run = aura.AuraButton(parent, "Join files")
            run.pack(anchor="w", pady=(0, 4))

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
        def _panel_shred(self, parent):
            self._describe(parent, "shred")
            src = FileRow(parent, self, "File", mode="open",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=(0, 8))
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(r, text="Passes", width=104, anchor="w",
                         font=aura.font()).pack(side="left")
            passes = tk.StringVar(value="1")
            ttk.Spinbox(r, from_=1, to=35, textvariable=passes,
                        width=5).pack(side="left", padx=(6, 0))
            aura.Caption(parent,
                         "Overwrites the file's bytes, then deletes it. NOTE: on "
                         "SSDs and copy-on-write/journaling filesystems (and with "
                         "backups or snapshots) this cannot guarantee the old data "
                         "is unrecoverable. Use full-disk encryption for real "
                         "assurance.", wraplength=680,
                         justify="left").pack(anchor="w", pady=(6, 4))
            run = aura.AuraButton(parent, "Overwrite & delete", kind="danger")
            run.pack(anchor="w", pady=(6, 4))

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
            self._describe(parent, "trash")
            src = FileRow(parent, self, "File / folder", mode="open",
                          on_change=lambda v: self.remember_input(v))
            src.pack(fill="x", pady=(0, 4))
            aura.Caption(parent,
                         "Moves the item to the OS Recycle Bin / Trash "
                         "(recoverable). Use Browse for a file, or paste a "
                         "folder path.", wraplength=680,
                         justify="left").pack(anchor="w", pady=(4, 6))
            run = aura.AuraButton(parent, "Send to Recycle Bin", kind="danger")
            run.pack(anchor="w", pady=(6, 4))

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

        # ---------- About ----------
        def _panel_about(self, parent):
            card = aura.Card(parent, title="About File Toolkit")
            card.pack(fill="x")
            aura.Heading(card.body, APP_NAME).pack(anchor="w")
            aura.Caption(card.body, f"Version {APP_VERSION}").pack(
                anchor="w", pady=(0, 10))
            ctk.CTkLabel(
                card.body, font=aura.font(), justify="left", anchor="w",
                wraplength=520,
                text="A fast, fully-offline batch file toolkit — bulk rename, "
                     "find duplicates, checksums, ZIP/7z archives, split/join "
                     "and secure delete.\n\n"
                     "100% AI-built, open source, published on QuickOpen. "
                     "Nothing is ever uploaded anywhere.").pack(anchor="w")
            aura.Caption(card.body,
                         "Licensed under Apache-2.0. Built on the Python "
                         "standard library plus py7zr (7z), send2trash "
                         "(Recycle Bin) and CustomTkinter (MIT).").pack(
                anchor="w", pady=(10, 4))
            aura.AuraButton(card.body, "Project page: quickopen.ai",
                            kind="ghost",
                            command=lambda: open_with_default_app(
                                PROJECT_URL)).pack(anchor="w", pady=(6, 0))

    return App


def main():
    """Entry point: build the root window and run. Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display (e.g. a server) or without customtkinter installed, it
    prints a friendly note and returns 0 instead of raising.
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
    except ImportError as exc:
        print(f"{APP_NAME}: the GUI needs the 'customtkinter' package "
              f"({exc}). Install it with:  pip install customtkinter")
        return 0
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
