from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_api_process_has_no_in_process_inference_dependencies():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for dependency in ("llama-cpp-python", "torch", "transformers", "sentence-transformers", "onnxruntime", "diffusers"):
        assert dependency not in project
    assert "httpx-sse" in project


def test_old_model_modules_are_removed():
    for module in ("inference/stateless.py", "knowledge_models.py", "llm_config.py",
                   "llm_service.py", "embedding.py", "multimodal_profiles.py", "vision_profiles.py",
                   "font_assets.py", "rerank.py"):
        assert not (ROOT / "ai_workbench/core" / module).exists()

    assert not (ROOT / "scripts/download_knowledge_model.py").exists()
