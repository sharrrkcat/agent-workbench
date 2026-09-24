"""Offline runtime preparation preserves shared dependency-cache files."""
import ast
import os

import pytest

from ai_workbench.workers.patch_transformers import patch_transformers


UPSTREAM = '''from ...utils import (
    is_torch_available,
    logging,
)


if is_torch_available():
    from ...generation import GenerationMixin


def add_generation_mixin_to_remote_model(model_class):
    has_custom_generate_in_class = hasattr(model_class, "generate")
    has_custom_prepare_inputs = hasattr(model_class, "prepare_inputs_for_generation")
    if has_custom_generate_in_class or has_custom_prepare_inputs:
        model_class_with_generation_mixin = type(
            model_class.__name__, (model_class, GenerationMixin), {**model_class.__dict__}
        )
        return model_class_with_generation_mixin
    return model_class
'''


def installation(tmp_path, version="5.16.1"):
    site_packages = tmp_path / "env/Lib/site-packages"
    metadata = site_packages / f"transformers-{version}.dist-info/METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(f"Name: transformers\nVersion: {version}\n", encoding="utf-8")
    source = site_packages / "transformers/models/auto/auto_factory.py"
    source.parent.mkdir(parents=True)
    return site_packages, source


def test_patch_breaks_cache_hard_link_and_repeated_application_does_not_write(tmp_path):
    site_packages, source = installation(tmp_path)
    cached = tmp_path / "cached_auto_factory.py"
    cached.write_text(UPSTREAM, encoding="utf-8")
    os.link(cached, source)
    assert os.path.samefile(source, cached)
    assert patch_transformers(site_packages) is True
    assert cached.read_text(encoding="utf-8") == UPSTREAM
    assert not os.path.samefile(source, cached)
    contents, stat = source.read_bytes(), source.stat()
    tree = ast.parse(contents)
    assert all(not isinstance(node, ast.If) for node in tree.body)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    branch = next(node for node in function.body if isinstance(node, ast.If))
    assert isinstance(branch.body[0], ast.ImportFrom) and branch.body[0].module == "generation"
    assert patch_transformers(site_packages) is False
    assert source.read_bytes() == contents
    assert source.stat().st_mtime_ns == stat.st_mtime_ns
    assert source.stat().st_ino == stat.st_ino
    assert not list(source.parent.glob(".auto_factory-*.tmp"))


def test_patch_rejects_unexpected_version_without_writing(tmp_path):
    site_packages, source = installation(tmp_path, "5.17.0")
    source.write_text(UPSTREAM, encoding="utf-8")
    with pytest.raises(ValueError, match="requires Transformers 5.16.1"):
        patch_transformers(site_packages)
    assert source.read_text(encoding="utf-8") == UPSTREAM


@pytest.mark.parametrize("contents", [UPSTREAM.replace("    logging,", "    logging,\n    is_torch_available,"),
    UPSTREAM.replace("if is_torch_available():", "if True:"),
    UPSTREAM.replace("    is_torch_available,\n", "")])
def test_patch_rejects_unexpected_or_partial_source_without_writing(tmp_path, contents):
    site_packages, source = installation(tmp_path)
    source.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="source layout"):
        patch_transformers(site_packages)
    assert source.read_text(encoding="utf-8") == contents


def test_patch_rejects_source_outside_runtime(tmp_path):
    from tests.test_runtime_maintenance import link_directory
    site_packages, source = installation(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / source.name).write_text(UPSTREAM, encoding="utf-8")
    source.parent.rmdir()
    link_directory(source.parent, outside)
    with pytest.raises(ValueError, match="escapes"):
        patch_transformers(site_packages)
    assert (outside / source.name).read_text(encoding="utf-8") == UPSTREAM
