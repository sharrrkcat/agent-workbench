# DLSS NR component

The native bridge, caller helper and color-channel interpretation derive from
lisitskyaa/ComfyUI-DLSS5-NR v0.3.1, commit
`41dcdfa593cb61b6a98c65bb8ed27606260bb598`, under the accompanying MIT license.
The Cogita adaptation removes temporal/Optical Flow support and separates the
manually supplied NR resource, packaged caller helper and writable work paths.
Each still image initializes the output/backbuffer from its own RGB input before
native evaluation, preventing intensity compositing from reusing another image.
The helper retains its upstream filename because NR validates its caller module.

This archive contains no NVIDIA NR resource, display driver, models or ComfyUI
dependency. Supply `nvngx_dlssnr.dll` separately in the processor model directory.
Windows x64, D3D12 and a compatible NVIDIA driver/resource combination are required.

Build with `uv run python scripts/build_dlss_component.py` from the repository
root. MSVC and a Windows SDK are build dependencies only. End-user installation
uses the application-bundled archive and existing Local Runtime Python/NumPy/Pillow.
