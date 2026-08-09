import sys

from PyInstaller.utils.hooks import collect_all, copy_metadata

engine_data, engine_binaries, engine_hidden = collect_all("cyberdrop_dl")
engine_data += copy_metadata("cyberdrop-dl-patched", recursive=True)
gui_data, gui_binaries, gui_hidden = collect_all("customtkinter")
gui_hidden += ["PIL._tkinter_finder"]
gui_data += [
    ("assets/drophound-icon.png", "assets"),
]
platform_icon = (
    "assets/drophound.ico"
    if sys.platform == "win32"
    else "assets/drophound.icns"
    if sys.platform == "darwin"
    else "assets/drophound-icon.png"
)

gui_analysis = Analysis(
    ["cyberdrop_desk/__main__.py"],
    pathex=["."],
    binaries=gui_binaries,
    datas=gui_data,
    hiddenimports=gui_hidden,
)
gui_pyz = PYZ(gui_analysis.pure)
gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="DropHound",
    icon=platform_icon,
    console=False,
    upx=False,
    disable_windowed_traceback=False,
)
gui_collect = COLLECT(
    gui_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    strip=False,
    upx=False,
    name="DropHound",
)
if sys.platform == "darwin":
    gui_bundle = BUNDLE(
        gui_collect,
        name="DropHound.app",
        icon=platform_icon,
        bundle_identifier="app.drophound.desktop",
        info_plist={
            "CFBundleShortVersionString": "0.6.1",
            "CFBundleVersion": "0.6.1",
            "NSHighResolutionCapable": True,
        },
    )

engine_analysis = Analysis(
    ["engine_launcher.py"],
    pathex=["."],
    binaries=engine_binaries,
    datas=engine_data,
    hiddenimports=engine_hidden,
)
engine_pyz = PYZ(engine_analysis.pure)
engine_exe = EXE(
    engine_pyz,
    engine_analysis.scripts,
    engine_analysis.binaries,
    engine_analysis.datas,
    [],
    name="DropHoundEngine",
    icon=platform_icon,
    console=True,
    strip=False,
    upx=False,
)
