"""Apply the pinned Transformers import adjustment during installation or offline maintenance."""
from importlib.metadata import Distribution
from pathlib import Path
import sysconfig
import tempfile


VERSION = "5.16.1"
TORCH_IMPORT = "    is_torch_available,\n"
GENERATION_IMPORT = "\nif is_torch_available():\n    from ...generation import GenerationMixin\n\n"
BRANCH = "    if has_custom_generate_in_class or has_custom_prepare_inputs:\n"
LAZY_BRANCH = BRANCH + "        from ...generation import GenerationMixin\n\n"


def patch_transformers(site_packages: Path) -> bool:
    site_packages = site_packages.resolve()
    distribution = next(Distribution.discover(name="transformers", path=[str(site_packages)]), None)
    if distribution is None or distribution.version != VERSION:
        raise ValueError(f"The import adjustment requires Transformers {VERSION} in {site_packages}")
    source = site_packages / "transformers/models/auto/auto_factory.py"
    if not source.resolve().is_relative_to(site_packages):
        raise ValueError("Transformers source escapes the runtime site-packages directory")
    contents = source.read_text(encoding="utf-8")
    if (contents.count(LAZY_BRANCH) == 1 and TORCH_IMPORT not in contents
            and GENERATION_IMPORT not in contents
            and contents.count("from ...generation import GenerationMixin") == 1):
        return False
    if (any(contents.count(part) != 1 for part in (TORCH_IMPORT, GENERATION_IMPORT, BRANCH))
            or LAZY_BRANCH in contents
            or contents.count("from ...generation import GenerationMixin") != 1):
        raise ValueError(f"Unexpected Transformers {VERSION} auto_factory.py source layout")
    contents = contents.replace(TORCH_IMPORT, "", 1).replace(GENERATION_IMPORT, "\n", 1)
    contents = contents.replace(BRANCH, LAZY_BRANCH, 1)
    # uv hard-links sources to its cache. Replacing this entry keeps the cached wheel source intact.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=source.parent,
                                     prefix=".auto_factory-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(contents)
    try:
        temporary.replace(source)
    finally:
        temporary.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    changed = patch_transformers(Path(sysconfig.get_path("purelib")))
    print("Transformers import adjustment applied." if changed else "Transformers import adjustment already applied.")
