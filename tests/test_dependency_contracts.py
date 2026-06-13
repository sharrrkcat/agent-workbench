from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _toml_array_block(text: str, key: str) -> str:
    start = text.index(f"{key} = [")
    end = text.index("\n]", start) + 2
    return text[start:end]


def test_florence2_local_runtime_dependencies_are_declared_and_documented() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "contracts" / "stateless-inference.md").read_text(encoding="utf-8")

    for extra_name in ("knowledge", "knowledge-cuda128"):
        extra = _toml_array_block(pyproject, extra_name)
        for dependency in (
            '"torch>=2.2"',
            '"torchvision>=0.17"',
            '"transformers>=4.40"',
            '"einops>=0.8"',
            '"timm>=1.0"',
            '"Pillow>=10"',
        ):
            assert dependency in extra

    assert "{ index = \"pytorch-cu128\", extra = \"knowledge-cuda128\" }" in pyproject
    assert "url = \"https://download.pytorch.org/whl/cu128\"" in pyproject
    assert "explicit = true" in pyproject
    assert "{ extra = \"knowledge\" }" in pyproject
    assert "{ extra = \"knowledge-cuda128\" }" in pyproject

    flat_contract = " ".join(contract.split())
    assert "Florence2 custom model code requires" in contract
    assert "`einops`, `timm`, `Pillow`, `torch`, and `torchvision`" in flat_contract
    assert "metadata.trust_remote_code=true" in contract
    assert "/api/inference/vision-models/{profile_id_or_alias}/preflight" in contract
    assert "manually installed CUDA wheel" in flat_contract
    assert "uv sync --extra knowledge" in contract
    assert "uv sync --extra knowledge-cuda128" in contract
    assert "CUDA 12.8" in contract
