"""Build and bundle the Windows x64 DLSS component with MSVC and Windows SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime_components/dlss5nr"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vs-root", type=Path, help="Visual Studio installation containing VC/Tools/MSVC")
    parser.add_argument("--sdk-root", type=Path, help="Windows Kits/10 directory")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This component requires the Windows x64 MSVC toolchain")
    program_files = Path(os.environ["ProgramFiles(x86)"])
    vs_root = args.vs_root
    if vs_root is None:
        vswhere = program_files / "Microsoft Visual Studio/Installer/vswhere.exe"
        vs_root = Path(subprocess.check_output([vswhere, "-latest", "-products", "*", "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip())
    toolset = sorted((vs_root / "VC/Tools/MSVC").iterdir(), key=lambda p: tuple(map(int, p.name.split("."))))[-1]
    sdk = args.sdk_root or program_files / "Windows Kits/10"
    sdk_version = sorted((sdk / "Include").iterdir(), key=lambda p: tuple(map(int, p.name.split("."))))[-1].name
    compiler = toolset / "bin/Hostx64/x64/cl.exe"
    environment = {**os.environ,
        "PATH": str(compiler.parent) + os.pathsep + os.environ["PATH"],
        "INCLUDE": os.pathsep.join(map(str, [toolset / "include", *(sdk / "Include" / sdk_version / p for p in ("ucrt", "shared", "um", "winrt"))])),
        "LIB": os.pathsep.join(map(str, [toolset / "lib/x64", *(sdk / "Lib" / sdk_version / p / "x64" for p in ("ucrt", "um"))]))}
    build = ROOT / "build/dlss5nr-component"
    build.mkdir(parents=True, exist_ok=True)
    native = {}
    for stem, filename, optimization, libraries in (
        ("caller_shim", "nvngx.dll_comfy.dll", "/Od", []),
        ("dlss5nr_bridge", "dlss5nr_bridge.dll", "/O2", ["d3d12.lib", "dxgi.lib", "ole32.lib"]),
    ):
        target = build / filename
        subprocess.run([compiler, "/nologo", "/std:c++17", "/EHsc", "/MT", "/LD", optimization,
            SOURCE / "native" / (stem + ".cpp"), "/Fo" + str(build / (stem + ".obj")),
            "/link", "/OUT:" + str(target), "/IMPLIB:" + str(build / (stem + ".lib")), *libraries],
            env=environment, cwd=build, check=True)
        native[filename] = target
    manifest = {"component_id": "dlss5nr", "version": "0.1.1", "platform": "windows", "architecture": "x86_64",
        "protocol_version": 1, "python_version": "3.12.11", "entries": {"worker": "worker/server.py", "engine": "worker/engine.py",
        "bridge": "native/dlss5nr_bridge.dll", "caller": "native/caller/nvngx.dll_comfy.dll"}}
    files = {"worker/server.py": SOURCE / "server.py", "worker/engine.py": SOURCE / "engine.py", "LICENSE": SOURCE / "LICENSE",
        "NOTICE.md": SOURCE / "NOTICE.md", "native/dlss5nr_bridge.dll": native["dlss5nr_bridge.dll"],
        "native/caller/nvngx.dll_comfy.dll": native["nvngx.dll_comfy.dll"]}
    bundle = ROOT / "ai_workbench/core/models/runtimes/bundled"
    bundle.mkdir(parents=True, exist_ok=True)
    archive = bundle / "dlss5nr-0.1.1-windows-x86_64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        contents = {name: path.read_bytes() for name, path in files.items()}
        contents["installation.json"] = json.dumps(manifest, separators=(",", ":")).encode()
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, data)
    release = {"manifest": manifest, "archive": archive.name, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    (bundle / "dlss5nr.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    print(f"Bundled {archive.name} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
