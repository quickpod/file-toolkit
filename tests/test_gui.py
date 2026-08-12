"""The GUI must import cleanly and degrade gracefully with no display."""

import os


def test_gui_imports_clean():
    from filekit import gui
    assert hasattr(gui, "main")
    assert hasattr(gui, "build_app")


def test_gui_main_headless_returns_zero(monkeypatch):
    # Ensure no display so main() takes the graceful-degradation path.
    monkeypatch.delenv("DISPLAY", raising=False)
    from filekit import gui
    assert gui.main() == 0


def test_asset_path_returns_none_or_str():
    from filekit import gui
    # a name that certainly does not exist
    assert gui.asset_path("definitely-not-here.xyz") is None
    # the real icon should resolve from source checkout
    p = gui.asset_path("file-toolkit.png")
    assert p is None or os.path.exists(p)
