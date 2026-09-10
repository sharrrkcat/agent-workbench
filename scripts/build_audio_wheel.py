"""Reproduce the versioned Chatterbox metadata patch for the Audio release."""
import base64
import csv
from email import policy
from email.parser import BytesParser
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import urllib.request
import zipfile

UPSTREAM_URL = "https://files.pythonhosted.org/packages/54/37/11a7f06983bfd5ebba71eb2caa6660941b17b31f3c49d4a5fe9e1e804d31/chatterbox_tts-0.1.7-py3-none-any.whl"
UPSTREAM_SHA256 = "83782500e3ad4e7c919132e9d7eb8755f29f57c5bde5ec48c655ca23a4eb113c"
VERSION = "0.1.7+workbench.1"
TARGET = Path(__file__).resolve().parents[1] / "ai_workbench/core/models/runtimes/wheels" / f"chatterbox_tts-{VERSION}-py3-none-any.whl"


def patched_wheel(raw):
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError("Upstream Chatterbox wheel checksum mismatch")
    original_info = "chatterbox_tts-0.1.7.dist-info"
    patched_info = f"chatterbox_tts-{VERSION}.dist-info"
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        files = {name.replace(original_info, patched_info): archive.read(name) for name in archive.namelist()
                 if not name.endswith("/RECORD")}
    metadata_path = patched_info + "/METADATA"
    metadata = BytesParser(policy=policy.compat32).parsebytes(files[metadata_path])
    metadata.replace_header("Version", VERSION)
    requirements = metadata.get_all("Requires-Dist", [])
    if "transformers==5.2.0" not in requirements:
        raise ValueError("Unexpected Chatterbox dependency metadata")
    del metadata["Requires-Dist"]
    for requirement in requirements:
        metadata["Requires-Dist"] = "transformers==4.57.3" if requirement == "transformers==5.2.0" else requirement
    files[metadata_path] = metadata.as_bytes(policy=policy.compat32.clone(max_line_length=0, linesep="\n"))
    files[patched_info + "/WORKBENCH_PATCH.json"] = (json.dumps({
        "upstream_url": UPSTREAM_URL, "upstream_sha256": UPSTREAM_SHA256,
        "version": VERSION, "changes": {"Requires-Dist": {"transformers==5.2.0": "transformers==4.57.3"}},
        "reference": "https://github.com/jamiepine/voicebox/tree/51f49dea198384b4eb6087b72c17057c6eb1c1cd",
        "source_changes": [],
    }, sort_keys=True, indent=2) + "\n").encode()
    record = StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, content in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(content)))
    writer.writerow((patched_info + "/RECORD", "", ""))
    files[patched_info + "/RECORD"] = record.getvalue().encode()
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 10, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, content, compresslevel=9)
    return output.getvalue()


def main():
    with urllib.request.urlopen(UPSTREAM_URL, timeout=60) as response:
        result = patched_wheel(response.read())
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(result)
    print(json.dumps({"path": str(TARGET), "sha256": hashlib.sha256(result).hexdigest(), "bytes": len(result)}))


if __name__ == "__main__":
    main()
