from pathlib import Path
import base64
import json

from fastapi.testclient import TestClient
from sqlmodel import Session as DbSession, create_engine

from ai_workbench.api.main import create_app
from ai_workbench.core.attachments import save_attachment_from_upload
from ai_workbench.core.settings import DEFAULT_COMMAND_RESULT_CONTEXT_INSTRUCTION, DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION, DEFAULT_SESSION_TITLE_PROMPT, DEFAULT_WEB_CONTEXT_PROMPT
from ai_workbench.core.settings import DEFAULT_CODE_FONT_FAMILY, DEFAULT_MESSAGE_FONT_FAMILY, DEFAULT_UI_FONT_FAMILY
from ai_workbench.core.settings import AppSettingsStore
from ai_workbench.db.models import AppMetadataRecord
from ai_workbench.core.schema.run import RunStatus
from scripts.cleanup_attachments import main as cleanup_main
from tests.test_api import create_session
from tests.test_prompt_agent_execution import FakeLLMRuntime, PromptRuntimeFixture, run


TXT_DATA_URL = "data:text/plain;base64,aGVsbG8="


def test_general_settings_get_patch_validate_and_persist(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'settings.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))

    response = client.get("/api/settings/general")
    assert response.status_code == 200
    assert response.json()["max_file_size_mb"] == 10
    assert response.json()["persist_streaming_message_deltas"] is False
    assert response.json()["auto_generate_session_titles"] is True
    assert response.json()["session_title_backend"] == "utility_llm"
    assert response.json()["session_title_model_profile_id"] is None
    assert response.json()["session_title_unload_after_generation"] is False
    assert response.json()["session_title_prompt"] == DEFAULT_SESSION_TITLE_PROMPT
    assert response.json()["session_title_prompt_default"] == DEFAULT_SESSION_TITLE_PROMPT
    assert response.json()["session_title_max_input_chars"] == 1200
    assert response.json()["group_transcript_system_instruction"] is None
    assert response.json()["command_result_context_instruction"] is None
    assert response.json()["resource_status_panel_enabled"] is False
    assert response.json()["resource_status_show_tokens"] is True
    assert response.json()["appearance_font_ui_family"] == DEFAULT_UI_FONT_FAMILY
    assert response.json()["appearance_font_message_family"] == DEFAULT_MESSAGE_FONT_FAMILY
    assert response.json()["appearance_font_code_family"] == DEFAULT_CODE_FONT_FAMILY
    assert response.json()["appearance_font_ui_source"] == "system"
    assert response.json()["appearance_font_message_source"] == "system"
    assert response.json()["appearance_font_code_source"] == "system"
    assert response.json()["appearance_font_ui_system_name"] == "Inter"
    assert response.json()["appearance_font_message_system_name"] == "Inter"
    assert response.json()["appearance_font_code_system_name"] == "ui-monospace"
    assert response.json()["appearance_font_ui_custom_id"] is None
    assert response.json()["appearance_font_message_custom_id"] is None
    assert response.json()["appearance_font_code_custom_id"] is None
    assert response.json()["appearance_font_ui_custom_family_id"] is None
    assert response.json()["appearance_font_message_custom_family_id"] is None
    assert response.json()["appearance_font_code_custom_family_id"] is None
    assert response.json()["core_memory_content"] == ""
    assert response.json()["core_memory_enabled_for_prompt_agents"] is True
    assert response.json()["core_memory_enabled_for_script_agents"] is False
    assert response.json()["web_context_enabled"] is False
    assert response.json()["web_context_max_results"] == 5
    assert response.json()["web_context_context_budget_chars"] == 4000
    assert response.json()["web_context_prompt"] == DEFAULT_WEB_CONTEXT_PROMPT
    assert response.json()["web_context_prompt_default"] == DEFAULT_WEB_CONTEXT_PROMPT
    assert response.json()["web_context_fetch_pages_enabled"] is False
    assert response.json()["web_context_fetch_max_pages"] == 2
    assert response.json()["web_context_fetch_timeout_seconds"] == 5
    assert response.json()["web_context_fetch_max_bytes"] == 1048576
    assert response.json()["web_context_page_excerpt_chars"] == 2000
    assert response.json()["web_context_total_page_excerpt_chars"] == 6000
    assert response.json()["web_context_candidate_judge_enabled"] is False
    assert response.json()["web_context_candidate_judge_max_candidates"] == 8
    assert response.json()["web_context_candidate_judge_min_relevance"] == "medium"
    assert response.json()["web_context_candidate_judge_max_selected"] == 5
    assert response.json()["intent_routing_enabled"] is False
    assert response.json()["intent_routing_default_for_prompt_agents"] is False
    assert response.json()["intent_routing_mode"] == "shadow"
    assert "intent_routing_high_confidence_threshold" not in response.json()
    assert "intent_routing_low_confidence_threshold" not in response.json()
    assert response.json()["intent_routing_semantic_intent_min_score"] == 0.5
    assert response.json()["intent_routing_semantic_intent_min_margin"] == 0.03
    assert response.json()["intent_routing_semantic_kb_min_score"] == 0.45
    assert response.json()["intent_routing_semantic_agent_min_score"] == 0.45
    assert response.json()["intent_routing_semantic_command_min_score"] == 0.45
    assert response.json()["intent_routing_auto_route_safe_intents"] is False
    assert response.json()["intent_routing_confirm_uncertain"] is True
    assert response.json()["intent_routing_embedding_model_profile_id"] is None
    assert "intent_routing_embedding_model_path" not in response.json()
    assert response.json()["intent_routing_utility_llm_backend"] == "transformers"
    assert response.json()["intent_routing_utility_llm_model_profile_id"] is None
    assert response.json()["intent_routing_utility_llm_model_path"] == ""
    assert response.json()["intent_routing_utility_llm_context_size"] == 4096
    assert response.json()["intent_routing_utility_llm_gpu_layers"] == 0
    assert response.json()["intent_routing_utility_llm_threads"] is None
    assert response.json()["intent_routing_device"] == "auto"
    assert response.json()["intent_routing_chat_examples"] == ""
    assert response.json()["intent_routing_image_generation_examples"] == ""
    assert response.json()["intent_routing_knowledge_query_examples"] == ""
    assert response.json()["intent_routing_agent_route_examples"] == ""
    assert response.json()["intent_routing_command_like_examples"] == ""
    assert response.json()["group_transcript_system_instruction_default"] == DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION
    assert response.json()["group_transcript_system_instruction_effective"] == DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION
    assert response.json()["command_result_context_instruction_default"] == DEFAULT_COMMAND_RESULT_CONTEXT_INSTRUCTION
    assert response.json()["command_result_context_instruction_effective"] == DEFAULT_COMMAND_RESULT_CONTEXT_INSTRUCTION

    patched = client.patch(
        "/api/settings/general",
        json={
            "max_file_size_mb": 20,
            "send_text_file_attachments_to_llm": False,
            "persist_streaming_message_deltas": True,
            "auto_generate_session_titles": False,
            "session_title_backend": "specified_model_profile",
            "session_title_model_profile_id": "title-profile",
            "session_title_unload_after_generation": True,
            "session_title_prompt": "Title from {user_input}",
            "session_title_max_input_chars": 500,
            "group_transcript_system_instruction": "Group override for {agent_name}",
            "command_result_context_instruction": "Command override for {command}",
            "resource_status_panel_enabled": True,
            "resource_status_show_tokens": False,
            "resource_status_ram_display_mode": "value",
            "appearance_font_ui_family": "Arial, sans-serif",
            "appearance_font_message_family": "Georgia, serif",
            "appearance_font_code_family": "Cascadia Mono, monospace",
            "appearance_font_ui_source": "system",
            "appearance_font_message_source": "custom_family",
            "appearance_font_code_source": "custom_file",
            "appearance_font_ui_system_name": "Arial",
            "appearance_font_message_system_name": "Georgia",
            "appearance_font_code_system_name": "Cascadia Mono",
            "appearance_font_ui_custom_id": "aaaaaaaaaaaaaaaa",
            "appearance_font_message_custom_id": None,
            "appearance_font_code_custom_id": "bbbbbbbbbbbbbbbb",
            "appearance_font_ui_custom_family_id": None,
            "appearance_font_message_custom_family_id": "cccccccccccccccc",
            "appearance_font_code_custom_family_id": None,
            "core_memory_content": "Remember local preferences.",
            "core_memory_enabled_for_prompt_agents": False,
            "core_memory_enabled_for_script_agents": True,
            "web_context_enabled": True,
            "web_context_max_results": 7,
            "web_context_context_budget_chars": 6000,
            "web_context_prompt": "Use web citations like [W1].",
            "web_context_fetch_pages_enabled": True,
            "web_context_fetch_max_pages": 4,
            "web_context_fetch_timeout_seconds": 8,
            "web_context_fetch_max_bytes": 2000000,
            "web_context_page_excerpt_chars": 3000,
            "web_context_total_page_excerpt_chars": 9000,
            "web_context_candidate_judge_enabled": True,
            "web_context_candidate_judge_max_candidates": 10,
            "web_context_candidate_judge_min_relevance": "high",
            "web_context_candidate_judge_max_selected": 4,
            "intent_routing_enabled": True,
            "intent_routing_default_for_prompt_agents": True,
            "intent_routing_mode": "auto",
            "intent_routing_semantic_intent_min_score": 0.6,
            "intent_routing_semantic_intent_min_margin": 0.04,
            "intent_routing_semantic_kb_min_score": 0.5,
            "intent_routing_semantic_agent_min_score": 0.51,
            "intent_routing_semantic_command_min_score": 0.52,
            "intent_routing_auto_route_safe_intents": True,
            "intent_routing_confirm_uncertain": False,
            "intent_routing_embedding_model_profile_id": "embedding-profile-1",
            "intent_routing_utility_llm_backend": "llama_cpp",
            "intent_routing_utility_llm_model_profile_id": "utility-profile",
            "intent_routing_utility_llm_context_size": 8192,
            "intent_routing_utility_llm_gpu_layers": -1,
            "intent_routing_utility_llm_threads": 4,
            "intent_routing_utility_llm_model_path": "utility_llms/qwen3-0.6b/Qwen3-0.6B-Q4_K_M.gguf",
            "intent_routing_device": "cpu",
            "intent_routing_chat_examples": "keep chatting",
            "intent_routing_image_generation_examples": "paint a castle",
            "intent_routing_knowledge_query_examples": "ask the docs",
            "intent_routing_agent_route_examples": "send to translator",
            "intent_routing_command_like_examples": "free resources",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["max_file_size_mb"] == 20
    assert patched.json()["send_text_file_attachments_to_llm"] is False
    assert patched.json()["persist_streaming_message_deltas"] is True
    assert patched.json()["auto_generate_session_titles"] is False
    assert patched.json()["session_title_backend"] == "specified_model_profile"
    assert patched.json()["session_title_model_profile_id"] == "title-profile"
    assert patched.json()["session_title_unload_after_generation"] is True
    assert patched.json()["session_title_prompt"] == "Title from {user_input}"
    assert patched.json()["session_title_max_input_chars"] == 500
    assert patched.json()["group_transcript_system_instruction"] == "Group override for {agent_name}"
    assert patched.json()["group_transcript_system_instruction_effective"] == "Group override for {agent_name}"
    assert patched.json()["command_result_context_instruction"] == "Command override for {command}"
    assert patched.json()["command_result_context_instruction_effective"] == "Command override for {command}"
    assert patched.json()["resource_status_panel_enabled"] is True
    assert patched.json()["resource_status_show_tokens"] is False
    assert patched.json()["resource_status_ram_display_mode"] == "value"
    assert patched.json()["appearance_font_ui_family"] == "Arial, sans-serif"
    assert patched.json()["appearance_font_message_family"] == "Georgia, serif"
    assert patched.json()["appearance_font_code_family"] == "Cascadia Mono, monospace"
    assert patched.json()["appearance_font_ui_source"] == "system"
    assert patched.json()["appearance_font_message_source"] == "custom_family"
    assert patched.json()["appearance_font_code_source"] == "custom_file"
    assert patched.json()["appearance_font_ui_system_name"] == "Arial"
    assert patched.json()["appearance_font_message_system_name"] == "Georgia"
    assert patched.json()["appearance_font_code_system_name"] == "Cascadia Mono"
    assert patched.json()["appearance_font_ui_custom_id"] == "aaaaaaaaaaaaaaaa"
    assert patched.json()["appearance_font_message_custom_id"] is None
    assert patched.json()["appearance_font_code_custom_id"] == "bbbbbbbbbbbbbbbb"
    assert patched.json()["appearance_font_message_custom_family_id"] == "cccccccccccccccc"
    assert patched.json()["core_memory_content"] == "Remember local preferences."
    assert patched.json()["core_memory_enabled_for_prompt_agents"] is False
    assert patched.json()["core_memory_enabled_for_script_agents"] is True
    assert patched.json()["web_context_enabled"] is True
    assert patched.json()["web_context_max_results"] == 7
    assert patched.json()["web_context_context_budget_chars"] == 6000
    assert patched.json()["web_context_prompt"] == "Use web citations like [W1]."
    assert patched.json()["web_context_fetch_pages_enabled"] is True
    assert patched.json()["web_context_fetch_max_pages"] == 4
    assert patched.json()["web_context_fetch_timeout_seconds"] == 8
    assert patched.json()["web_context_fetch_max_bytes"] == 2000000
    assert patched.json()["web_context_candidate_judge_enabled"] is True
    assert patched.json()["web_context_candidate_judge_max_candidates"] == 10
    assert patched.json()["web_context_candidate_judge_min_relevance"] == "high"
    assert patched.json()["web_context_candidate_judge_max_selected"] == 4
    assert patched.json()["web_context_page_excerpt_chars"] == 3000
    assert patched.json()["web_context_total_page_excerpt_chars"] == 9000
    assert patched.json()["intent_routing_enabled"] is True
    assert patched.json()["intent_routing_default_for_prompt_agents"] is True
    assert patched.json()["intent_routing_mode"] == "auto"
    assert "intent_routing_high_confidence_threshold" not in patched.json()
    assert "intent_routing_low_confidence_threshold" not in patched.json()
    assert patched.json()["intent_routing_semantic_intent_min_score"] == 0.6
    assert patched.json()["intent_routing_semantic_intent_min_margin"] == 0.04
    assert patched.json()["intent_routing_semantic_kb_min_score"] == 0.5
    assert patched.json()["intent_routing_semantic_agent_min_score"] == 0.51
    assert patched.json()["intent_routing_semantic_command_min_score"] == 0.52
    assert patched.json()["intent_routing_auto_route_safe_intents"] is True
    assert patched.json()["intent_routing_confirm_uncertain"] is False
    assert patched.json()["intent_routing_embedding_model_profile_id"] == "embedding-profile-1"
    assert "intent_routing_embedding_model_path" not in patched.json()
    assert patched.json()["intent_routing_utility_llm_backend"] == "llama_cpp"
    assert patched.json()["intent_routing_utility_llm_model_profile_id"] == "utility-profile"
    assert patched.json()["intent_routing_utility_llm_model_path"] == "utility_llms/qwen3-0.6b/Qwen3-0.6B-Q4_K_M.gguf"
    assert patched.json()["intent_routing_utility_llm_context_size"] == 8192
    assert patched.json()["intent_routing_utility_llm_gpu_layers"] == -1
    assert patched.json()["intent_routing_utility_llm_threads"] == 4
    assert patched.json()["intent_routing_device"] == "cpu"
    assert patched.json()["intent_routing_chat_examples"] == "keep chatting"
    assert patched.json()["intent_routing_image_generation_examples"] == "paint a castle"
    assert patched.json()["intent_routing_knowledge_query_examples"] == "ask the docs"
    assert patched.json()["intent_routing_agent_route_examples"] == "send to translator"
    assert patched.json()["intent_routing_command_like_examples"] == "free resources"

    patched_hf = client.patch(
        "/api/settings/general",
        json={
            "intent_routing_utility_llm_backend": "transformers",
            "intent_routing_utility_llm_model_path": "utility_llms/Qwen3-0.6B",
        },
    )
    assert patched_hf.status_code == 200
    assert patched_hf.json()["intent_routing_utility_llm_backend"] == "transformers"
    assert patched_hf.json()["intent_routing_utility_llm_model_profile_id"] == "utility-profile"
    assert patched_hf.json()["intent_routing_utility_llm_model_path"] == "utility_llms/Qwen3-0.6B"

    patched_profile = client.patch(
        "/api/settings/general",
        json={
            "intent_routing_utility_llm_backend": "model_profile",
            "intent_routing_utility_llm_model_profile_id": None,
        },
    )
    assert patched_profile.status_code == 200
    assert patched_profile.json()["intent_routing_utility_llm_backend"] == "model_profile"
    assert patched_profile.json()["intent_routing_utility_llm_model_profile_id"] is None
    assert patched_profile.json()["intent_routing_utility_llm_model_path"] == "utility_llms/Qwen3-0.6B"

    reset = client.patch(
        "/api/settings/general",
        json={"group_transcript_system_instruction": "", "command_result_context_instruction": None},
    )
    assert reset.status_code == 200
    assert reset.json()["group_transcript_system_instruction"] is None
    assert reset.json()["group_transcript_system_instruction_effective"] == DEFAULT_GROUP_TRANSCRIPT_SYSTEM_INSTRUCTION
    assert reset.json()["command_result_context_instruction"] is None
    assert reset.json()["command_result_context_instruction_effective"] == DEFAULT_COMMAND_RESULT_CONTEXT_INSTRUCTION

    assert client.patch("/api/settings/general", json={"unknown": 1}).status_code == 422
    assert client.patch("/api/settings/general", json={"max_file_size_mb": 0}).status_code == 422
    assert client.patch("/api/settings/general", json={"session_title_max_input_chars": 99}).status_code == 422
    assert client.patch("/api/settings/general", json={"session_title_backend": "main_llm"}).status_code == 422
    assert client.patch("/api/settings/general", json={"session_title_unload_after_generation": "yes"}).status_code == 422
    assert client.patch("/api/settings/general", json={"session_title_prompt": "   "}).status_code == 422
    assert client.patch("/api/settings/general", json={"resource_status_ram_display_mode": "raw"}).status_code == 422
    assert client.patch("/api/settings/general", json={"appearance_font_ui_family": ""}).status_code == 422
    assert client.patch("/api/settings/general", json={"appearance_font_ui_family": None}).status_code == 422
    assert client.patch("/api/settings/general", json={"appearance_font_ui_system_name": ""}).status_code == 422
    assert client.patch("/api/settings/general", json={"appearance_font_ui_source": "remote"}).status_code == 422
    assert client.patch("/api/settings/general", json={"appearance_font_ui_custom_id": 42}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_mode": "unsafe"}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_device": "metal"}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_utility_llm_backend": "openai"}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_utility_llm_context_size": 128}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_utility_llm_gpu_layers": 201}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_utility_llm_threads": 0}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_utility_llm_model_path": "../qwen"}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_utility_llm_model_path": "llms/Qwen3-0.6B"}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_utility_llm_backend": "llama_cpp", "intent_routing_utility_llm_model_path": "utility_llms/model.gguf"}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_utility_llm_backend": "transformers", "intent_routing_utility_llm_model_path": "utility_llms/qwen3/model.gguf"}).status_code == 422
    assert client.patch("/api/settings/general", json={"intent_routing_low_confidence_threshold": 0.95}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_enabled": "yes"}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_max_results": 0}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_max_results": 11}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_fetch_pages_enabled": "yes"}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_fetch_max_pages": 0}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_fetch_max_pages": 6}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_fetch_timeout_seconds": 0}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_fetch_timeout_seconds": 21}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_fetch_max_bytes": 99999}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_fetch_max_bytes": 5000001}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_page_excerpt_chars": 499}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_page_excerpt_chars": 8001}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_total_page_excerpt_chars": 999}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_total_page_excerpt_chars": 20001}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_candidate_judge_enabled": "yes"}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_candidate_judge_max_candidates": 0}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_candidate_judge_max_candidates": 13}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_candidate_judge_min_relevance": "extreme"}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_candidate_judge_max_selected": 0}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_candidate_judge_max_selected": 11}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_context_budget_chars": 499}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_context_budget_chars": 20001}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_prompt": "   "}).status_code == 422
    assert client.patch("/api/settings/general", json={"web_context_prompt": "x" * 4001}).status_code == 422

    restarted = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    assert restarted.get("/api/settings/general").json()["max_file_size_mb"] == 20
    assert restarted.get("/api/settings/general").json()["persist_streaming_message_deltas"] is True
    assert restarted.get("/api/settings/general").json()["auto_generate_session_titles"] is False
    assert restarted.get("/api/settings/general").json()["session_title_backend"] == "specified_model_profile"
    assert restarted.get("/api/settings/general").json()["session_title_model_profile_id"] == "title-profile"
    assert restarted.patch("/api/settings/general", json={"session_title_model_profile_id": None}).json()["session_title_model_profile_id"] is None
    assert restarted.get("/api/settings/general").json()["session_title_unload_after_generation"] is True
    assert restarted.get("/api/settings/general").json()["session_title_prompt"] == "Title from {user_input}"
    assert restarted.get("/api/settings/general").json()["group_transcript_system_instruction"] is None
    assert restarted.get("/api/settings/general").json()["resource_status_panel_enabled"] is True
    assert restarted.get("/api/settings/general").json()["appearance_font_ui_family"] == "Arial, sans-serif"
    assert restarted.patch("/api/settings/general", json={"appearance_font_ui_custom_id": None}).json()["appearance_font_ui_custom_id"] is None
    assert restarted.patch("/api/settings/general", json={"appearance_font_message_custom_family_id": None}).json()["appearance_font_message_custom_family_id"] is None
    assert restarted.get("/api/settings/general").json()["core_memory_content"] == "Remember local preferences."
    assert restarted.get("/api/settings/general").json()["web_context_enabled"] is True
    assert restarted.patch("/api/settings/general", json={"web_context_max_results": 3}).json()["web_context_max_results"] == 3
    assert restarted.get("/api/settings/general").json()["web_context_context_budget_chars"] == 6000
    assert restarted.get("/api/settings/general").json()["web_context_prompt"] == "Use web citations like [W1]."
    assert restarted.get("/api/settings/general").json()["web_context_fetch_pages_enabled"] is True
    assert restarted.get("/api/settings/general").json()["web_context_fetch_max_pages"] == 4
    assert restarted.get("/api/settings/general").json()["web_context_fetch_timeout_seconds"] == 8
    assert restarted.get("/api/settings/general").json()["web_context_fetch_max_bytes"] == 2000000
    assert restarted.get("/api/settings/general").json()["web_context_page_excerpt_chars"] == 3000
    assert restarted.get("/api/settings/general").json()["web_context_total_page_excerpt_chars"] == 9000
    assert restarted.get("/api/settings/general").json()["web_context_candidate_judge_enabled"] is True
    assert restarted.get("/api/settings/general").json()["web_context_candidate_judge_max_candidates"] == 10
    assert restarted.get("/api/settings/general").json()["web_context_candidate_judge_min_relevance"] == "high"
    assert restarted.get("/api/settings/general").json()["web_context_candidate_judge_max_selected"] == 4
    assert restarted.get("/api/settings/general").json()["intent_routing_enabled"] is True
    assert restarted.get("/api/settings/general").json()["intent_routing_embedding_model_profile_id"] == "embedding-profile-1"
    assert restarted.get("/api/settings/general").json()["intent_routing_semantic_intent_min_score"] == 0.6
    assert restarted.get("/api/settings/general").json()["intent_routing_semantic_kb_min_score"] == 0.5
    assert restarted.patch("/api/settings/general", json={"intent_routing_embedding_model_profile_id": None}).json()["intent_routing_embedding_model_profile_id"] is None
    assert restarted.get("/api/settings/general").json()["intent_routing_utility_llm_backend"] == "model_profile"
    assert restarted.get("/api/settings/general").json()["intent_routing_utility_llm_model_profile_id"] is None
    assert restarted.get("/api/settings/general").json()["intent_routing_utility_llm_model_path"] == "utility_llms/Qwen3-0.6B"
    assert restarted.get("/api/settings/general").json()["intent_routing_device"] == "cpu"
    assert restarted.get("/api/settings/general").json()["intent_routing_chat_examples"] == "keep chatting"
    assert restarted.get("/api/settings/general").json()["intent_routing_image_generation_examples"] == "paint a castle"
    assert restarted.get("/api/settings/general").json()["intent_routing_knowledge_query_examples"] == "ask the docs"
    assert restarted.get("/api/settings/general").json()["intent_routing_agent_route_examples"] == "send to translator"
    assert restarted.get("/api/settings/general").json()["intent_routing_command_like_examples"] == "free resources"


def test_general_settings_ignores_legacy_embedding_path_in_stored_json(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'legacy-settings.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    engine = create_engine(db_url)
    with DbSession(engine) as session:
        session.add(
            AppMetadataRecord(
                key="app_settings",
                value=json.dumps(
                    {
                        "intent_routing_enabled": True,
                        "intent_routing_embedding_model_profile_id": "profile-id",
                        "intent_routing_embedding_model_path": "embeddings/legacy-path",
                        "intent_routing_high_confidence_threshold": 0.99,
                        "intent_routing_low_confidence_threshold": 0.01,
                        "appearance_font_ui_family": '"Segoe UI", sans-serif',
                        "appearance_font_code_family": "Cascadia Mono, monospace",
                        "appearance_font_message_custom_id": "dddddddddddddddd",
                    }
                ),
            )
        )
        session.commit()

    response = client.get("/api/settings/general")
    patched = client.patch("/api/settings/general", json={"intent_routing_embedding_model_path": "embeddings/new-ignored"})

    assert response.status_code == 200
    assert response.json()["intent_routing_enabled"] is True
    assert response.json()["intent_routing_embedding_model_profile_id"] == "profile-id"
    assert response.json()["appearance_font_ui_system_name"] == "Segoe UI"
    assert response.json()["appearance_font_code_system_name"] == "Cascadia Mono"
    assert response.json()["appearance_font_message_source"] == "custom_file"
    assert "intent_routing_embedding_model_path" not in response.json()
    assert "intent_routing_high_confidence_threshold" not in response.json()
    assert "intent_routing_low_confidence_threshold" not in response.json()
    assert patched.status_code == 422


def test_font_assets_scan_and_secure_serving(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'fonts.db'}"))
    fonts_dir = Path(client.app.state.runtime_state.repo_root) / "data" / "assets" / "fonts"
    font_file = fonts_dir / "pytest-demo-font.woff2"
    ignored_file = fonts_dir / "pytest-not-a-font.txt"
    family_dir = fonts_dir / "pytest-family"
    family_dir.mkdir(exist_ok=True)
    (family_dir / "MyFont-Light.ttf").write_bytes(b"light")
    (family_dir / "MyFont-BoldItalic.ttf").write_bytes(b"bold-italic")
    (family_dir / "MyFont-ExtraLightItalic.ttf").write_bytes(b"extra-light-italic")
    (family_dir / "ignored.txt").write_text("nope", encoding="utf-8")
    font_file.write_bytes(b"font-bytes")
    ignored_file.write_text("not a font", encoding="utf-8")
    try:
        response = client.get("/api/assets/fonts")
        assert response.status_code == 200
        assert "files" in response.json()
        assert "families" in response.json()
        fonts = [item for item in response.json()["files"] if item["filename"].startswith("pytest-")]
        assert len(fonts) == 1
        font = fonts[0]
        assert font["filename"] == "pytest-demo-font.woff2"
        assert font["display_name"] == "pytest demo font"
        assert font["extension"] == ".woff2"
        assert font["size_bytes"] == len(b"font-bytes")
        assert font["css_family"].startswith("AW Local Font ")
        assert font["url"] == f"/api/assets/fonts/{font['id']}"

        served = client.get(font["url"])
        assert served.status_code == 200
        assert served.content == b"font-bytes"
        assert served.headers["content-type"].startswith("font/woff2")

        families = [item for item in response.json()["families"] if item["display_name"] == "pytest family"]
        assert len(families) == 1
        family = families[0]
        assert family["css_family"].startswith("AW Local Font Family ")
        faces = {(face["file"], face["weight"], face["style"], face["registered_weight"]) for face in family["faces"]}
        assert ("MyFont-Light.ttf", 300, "normal", "250 349") in faces
        assert ("MyFont-BoldItalic.ttf", 700, "italic", "650 749") in faces
        assert ("MyFont-ExtraLightItalic.ttf", 200, "italic", "150 249") in faces

        face = next(item for item in family["faces"] if item["file"] == "MyFont-BoldItalic.ttf")
        served_face = client.get(face["url"])
        assert served_face.status_code == 200
        assert served_face.content == b"bold-italic"
        assert client.get(f"/api/assets/font-families/{family['id']}/..%2Fsecret.ttf").status_code == 404

        assert client.get("/api/assets/fonts/../secret").status_code == 404
        assert client.get("/api/assets/fonts/C:%5Csecret").status_code == 404
        assert client.get("/api/assets/fonts/not-a-font").status_code == 404
    finally:
        font_file.unlink(missing_ok=True)
        ignored_file.unlink(missing_ok=True)
        for child in family_dir.iterdir():
            child.unlink(missing_ok=True)
        family_dir.rmdir()


def test_font_family_manifest_supports_variable_weight_ranges(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'font-family.db'}"))
    fonts_dir = Path(client.app.state.runtime_state.repo_root) / "data" / "assets" / "fonts"
    family_dir = fonts_dir / "pytest-variable"
    family_dir.mkdir(exist_ok=True)
    (family_dir / "Variable.woff2").write_bytes(b"variable")
    (family_dir / "Italic.woff2").write_bytes(b"italic")
    (family_dir / "font.json").write_text(
        json.dumps(
            {
                "family": "Pytest Variable",
                "display_name": "Pytest Variable",
                "faces": [
                    {"file": "Variable.woff2", "weight": "100 900", "style": "normal"},
                    {"file": "Italic.woff2", "weight": 400, "style": "italic"},
                    {"file": "../escape.woff2", "weight": 700, "style": "normal"},
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        response = client.get("/api/assets/fonts")
        assert response.status_code == 200
        family = next(item for item in response.json()["families"] if item["display_name"] == "Pytest Variable")
        faces = {(face["file"], face["weight"], face["style"], face["registered_weight"]) for face in family["faces"]}
        assert ("Variable.woff2", "100 900", "normal", "100 900") in faces
        assert ("Italic.woff2", 400, "italic", "350 449") in faces
        assert all(face["file"] != "../escape.woff2" for face in family["faces"])
    finally:
        for child in family_dir.iterdir():
            child.unlink(missing_ok=True)
        family_dir.rmdir()


def test_message_upload_limits_use_general_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), use_memory=True))
    session = create_session(client)
    client.patch("/api/settings/general", json={"max_image_size_mb": 1, "max_file_size_mb": 1, "max_attachments_per_message": 1})
    large_payload = base64.b64encode(b"x" * (2 * 1024 * 1024)).decode("ascii")

    too_large_image = {
        "id": "image",
        "type": "image",
        "mime_type": "image/svg+xml",
        "name": "image.svg",
        "size": 2 * 1024 * 1024,
        "data_url": f"data:image/svg+xml;base64,{large_payload}",
    }
    image_response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "x", "attachments": [too_large_image]})
    assert image_response.status_code == 400
    assert "Maximum size is 1 MB" in image_response.json()["error"]["message"]

    too_large_file = {
        "id": "file",
        "type": "file",
        "mime_type": "text/plain",
        "name": "note.txt",
        "size": 2 * 1024 * 1024,
        "data_url": f"data:text/plain;base64,{large_payload}",
    }
    file_response = client.post(f"/api/sessions/{session['session_id']}/messages", json={"content": "x", "attachments": [too_large_file]})
    assert file_response.status_code == 400
    assert "Maximum size is 1 MB" in file_response.json()["error"]["message"]

    count_response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "x", "attachments": [{**too_large_file, "size": 5}, {**too_large_file, "id": "file-2", "size": 5}]},
    )
    assert count_response.status_code == 400
    assert "At most 1 attachments" in count_response.json()["error"]["message"]


def test_prompt_file_context_uses_general_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    llm = FakeLLMRuntime(response="ok")
    fixture = PromptRuntimeFixture(llm=llm)
    settings = AppSettingsStore()
    fixture.agent_runner.app_settings_store = settings
    session = fixture.sessions.create_session(default_agent_id="chat")
    first = save_attachment_from_upload("a.txt", "text/plain", b"a" * 2048)
    second = save_attachment_from_upload("b.txt", "text/plain", b"b" * 2048)

    settings.patch({"max_file_context_per_file_kb": 1, "max_total_file_context_per_message_kb": 1})
    result = run(fixture.runtime.handle_input(session, "summarize", attachments=[first, second]))
    sent = _last_non_title_user_content(llm)
    metadata = fixture.runs.get_run(result.run_id).metadata["file_context"]
    assert metadata["enabled"] is True
    assert metadata["files_sent"] == 1
    assert metadata["total_chars"] == 1024
    assert "Truncated: true" in sent

    settings.patch({"send_text_file_attachments_to_llm": False})
    result = run(fixture.runtime.handle_input(session, "again", attachments=[first]))
    sent = _last_non_title_user_content(llm)
    metadata = fixture.runs.get_run(result.run_id).metadata["file_context"]
    assert "file context is disabled" in sent
    assert "aaaa" not in sent
    assert metadata["enabled"] is False
    assert metadata["files_sent"] == 0


def _last_non_title_user_content(llm: FakeLLMRuntime) -> str:
    for call in reversed(llm.calls):
        content = call["messages"][-1]["content"]
        if not str(content).startswith("Generate a short title"):
            return content
    raise AssertionError("no prompt agent call found")


def test_data_storage_stats_scan_and_cleanup(monkeypatch, tmp_path: Path) -> None:
    attachments_dir = tmp_path / "attachments"
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(attachments_dir))
    db_url = f"sqlite:///{tmp_path / 'workbench.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    state = client.app.state.runtime_state
    session = state.sessions.create_session()
    referenced = attachments_dir / "files" / "11111111-1111-1111-1111-111111111111.txt"
    orphan = attachments_dir / "files" / "22222222-2222-2222-2222-222222222222.txt"
    outside = tmp_path / "outside.txt"
    referenced.parent.mkdir(parents=True)
    referenced.write_text("keep", encoding="utf-8")
    orphan.write_text("delete", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    state.messages.add_message(
        session_id=session.session_id,
        role="user",
        content="attached",
        metadata={"attachments": [{"id": "keep", "uri": f"local://attachments/{referenced.name}", "type": "file"}]},
    )

    stats = client.get("/api/data/storage-stats")
    assert stats.status_code == 200
    assert stats.json()["database"]["size_bytes"] >= 0
    assert stats.json()["attachments"]["count"] == 2
    assert stats.json()["attachments"]["orphan_count"] == 1

    scan = client.post("/api/data/attachments/scan-orphans")
    assert scan.status_code == 200
    assert scan.json()["orphans"][0]["id"] == orphan.name

    rejected = client.post("/api/data/attachments/cleanup-orphans", json={"confirm": False})
    assert rejected.status_code == 400
    cleaned = client.post("/api/data/attachments/cleanup-orphans", json={"confirm": True})
    assert cleaned.status_code == 200
    assert cleaned.json()["deleted_count"] == 1
    assert referenced.exists()
    assert not orphan.exists()
    assert outside.exists()


def test_diagnostics_returns_runtime_sections_and_masks_secrets(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    (tmp_path / "attachments" / "files").mkdir(parents=True)
    db_url = f"sqlite:///{tmp_path / 'diagnostics.db'}"
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=db_url))
    client.patch("/api/capability-configs/llm", json={"user_config": {"api_key": "secret-token", "model": "local-model"}})

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert {"backend", "database", "attachments", "event_bus", "runs", "llm", "capabilities"}.issubset(payload)
    assert payload["backend"]["version"] == "0.1.0-alpha"
    assert payload["database"]["status"] == "ok"
    assert payload["database"]["schema_version"] == "1"
    assert payload["attachments"]["status"] == "ok"
    assert payload["attachments"]["writable"] is True
    assert payload["event_bus"]["subscriber_count"] == 0
    assert payload["llm"]["default_resolved"]["api_key_set"] is True
    assert payload["llm"]["default_resolved"]["model_id"] == "local-model"
    assert "secret-token" not in str(payload)


def test_diagnostics_recent_failures_are_limited_and_truncated(tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'failures.db'}"))
    state = client.app.state.runtime_state
    session = state.sessions.create_session()
    long_error = "x" * 500
    for index in range(7):
        run_record = state.runs.create_run(kind="agent", target_id="chat", session_id=session.session_id)
        state.runs.update_status(run_record.run_id, RunStatus.FAILED, error=f"{index}:{long_error}")

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert runs["recent_failed_count"] == 7
    assert len(runs["recent_failures"]) == 5
    assert all(len(item["message"]) <= 300 for item in runs["recent_failures"])
    assert all(item["error_code"] == "RUN_FAILED" for item in runs["recent_failures"])


def test_diagnostics_does_not_call_llm_model_listing(monkeypatch, tmp_path: Path) -> None:
    class NoModelListingRuntime(FakeLLMRuntime):
        def list_models(self, model_config=None):
            raise AssertionError("diagnostics must not call /models")

    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    (tmp_path / "attachments").mkdir()
    client = TestClient(create_app(llm_runtime=NoModelListingRuntime(), use_memory=True))

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    assert "llm" in response.json()


def test_diagnostics_subitem_failure_returns_degraded_not_500(monkeypatch, tmp_path: Path) -> None:
    client = TestClient(create_app(llm_runtime=FakeLLMRuntime(), database_url=f"sqlite:///{tmp_path / 'degraded.db'}"))

    def fail_sessions():
        raise RuntimeError("database offline\nprivate stack")

    monkeypatch.setattr(client.app.state.runtime_state.sessions, "list_sessions", fail_sessions)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"]["status"] == "degraded"
    assert any("database offline" in warning for warning in payload["warnings"])
    assert "private stack" not in str(payload)


def test_cleanup_attachments_script_still_runs(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    orphan = tmp_path / "attachments" / "files" / "33333333-3333-3333-3333-333333333333.txt"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("orphan", encoding="utf-8")

    assert cleanup_main(["--database-url", f"sqlite:///{tmp_path / 'missing.db'}"]) == 0
    assert "orphan count: 1" in capsys.readouterr().out
    assert cleanup_main(["--database-url", f"sqlite:///{tmp_path / 'missing.db'}", "--apply"]) == 0
    assert not orphan.exists()
