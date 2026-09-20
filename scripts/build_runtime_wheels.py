"""Reproduce the audited wheels for the managed local inference release."""
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

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build/runtime-wheels"
CATALOG = ROOT / "ai_workbench/core/models/runtimes"
DEFAULT_ROPE = '''def default_rope_parameters(config, device):
    # Transformers 5 delegates the default RoPE formula to each model.
    head_dim = getattr(config, "head_dim", None) or config.hidden_size // config.num_attention_heads
    dim = int(head_dim * getattr(config, "partial_rotary_factor", 1.0))
    inverse = 1.0 / (config.rope_theta ** (torch.arange(0, dim, 2, dtype=torch.int64).to(device=device, dtype=torch.float) / dim))
    return inverse, 1.0


def initialize_rope_buffers(module):
    # Transformers 5 materializes non-persistent buffers before _init_weights.
    # Qwen's custom initializers must restore the constructor's RoPE values.
    inverse, module.attention_scaling = module.rope_init_fn(module.config, module.inv_freq.device)
    module.register_buffer("inv_freq", inverse, persistent=False)
    module.original_inv_freq = module.inv_freq


'''
SPECS = {
    "chatterbox_tts": {
        "version": "0.1.7",
        "url": "https://files.pythonhosted.org/packages/54/37/11a7f06983bfd5ebba71eb2caa6660941b17b31f3c49d4a5fe9e1e804d31/chatterbox_tts-0.1.7-py3-none-any.whl",
        "sha256": "83782500e3ad4e7c919132e9d7eb8755f29f57c5bde5ec48c655ca23a4eb113c",
        "requirements": {
            'torch==2.6.0; python_version < "3.14"': 'torch==2.11.0+cu128; python_version < "3.14"',
            'torchaudio==2.6.0; python_version < "3.14"': 'torchaudio==2.11.0+cu128; python_version < "3.14"',
            "transformers==5.2.0": "transformers==5.16.1",
            "safetensors==0.5.3": "safetensors==0.8.0",
        },
    },
    "qwen_tts": {
        "version": "0.1.1",
        "url": "https://files.pythonhosted.org/packages/31/01/95f3ae26f5b7eb2105f69ad2c15af5a28b9ebdd1258a0b27541f5ebd6225/qwen_tts-0.1.1-py3-none-any.whl",
        "sha256": "11a290d8dabc7ef91a90c54478c8ab19b3edb1d85c0882313721892bdc4af15d",
        "requirements": {"transformers==4.57.3": "transformers==5.16.1"},
        "source_changes": [{
            "path": "qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py",
            "old": "@check_model_inputs()", "new": "@merge_with_config_defaults", "count": 1,
        }, {
            "path": "qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py",
            "old": "from transformers.utils.generic import check_model_inputs",
            "new": "from transformers.utils.generic import merge_with_config_defaults", "count": 1,
        }, {
            "path": "qwen_tts/core/models/configuration_qwen3_tts.py",
            "old": "        tie_word_embeddings=False,\n        rope_theta=10000,",
            "new": "        tie_word_embeddings=False,\n        pad_token_id=None,\n        rope_theta=10000,", "count": 2,
        }, {
            "path": "qwen_tts/core/models/configuration_qwen3_tts.py",
            "old": "            tie_word_embeddings=tie_word_embeddings,\n            **kwargs,",
            "new": "            tie_word_embeddings=tie_word_embeddings,\n            pad_token_id=pad_token_id,\n            **kwargs,", "count": 2,
        }, {
            "path": "qwen_tts/core/models/modeling_qwen3_tts.py",
            "old": "class Qwen3TTSTalkerRotaryEmbedding(nn.Module):",
            "new": DEFAULT_ROPE + "class Qwen3TTSTalkerRotaryEmbedding(nn.Module):", "count": 1,
        }, {
            "path": "qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py",
            "old": "class Qwen3TTSTokenizerV2DecoderRotatoryEmbedding(nn.Module):",
            "new": DEFAULT_ROPE + "class Qwen3TTSTokenizerV2DecoderRotatoryEmbedding(nn.Module):", "count": 1,
        }, *[{
            "path": path, "old": "self.rope_init_fn = ROPE_INIT_FUNCTIONS[self.rope_type]",
            "new": 'self.rope_init_fn = default_rope_parameters if self.rope_type == "default" else ROPE_INIT_FUNCTIONS[self.rope_type]',
            "count": count,
        } for path, count in (("qwen_tts/core/models/modeling_qwen3_tts.py", 2),
                              ("qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py", 1))],
        *[{
            "path": path, "old": '"input_embeds": inputs_embeds,',
            "new": '"inputs_embeds": inputs_embeds,', "count": 1,
        } for path in ("qwen_tts/core/models/modeling_qwen3_tts.py",
                       "qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py")],
        *[{
            "path": path, "old": '                "cache_position": cache_position,\n',
            "new": "", "count": 1,
        } for path in ("qwen_tts/core/models/modeling_qwen3_tts.py",
                       "qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py")],
        {
            "path": "qwen_tts/core/models/modeling_qwen3_tts.py",
            "old": "            input_embeds=inputs_embeds,\n            attention_mask=attention_mask,\n            cache_position=cache_position,",
            "new": "            inputs_embeds=inputs_embeds,\n            attention_mask=attention_mask,", "count": 1,
        }, {
            "path": "qwen_tts/core/models/modeling_qwen3_tts.py",
            "old": "    def _init_weights(self, module):\n",
            "new": "    def _init_weights(self, module):\n        if isinstance(module, (Qwen3TTSTalkerRotaryEmbedding, Qwen3TTSRotaryEmbedding)):\n            initialize_rope_buffers(module)\n            return\n", "count": 2,
        }, {
            "path": "qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py",
            "old": "class Qwen3TTSTokenizerV2CausalConvNet(nn.Module):",
            "new": "    def _init_weights(self, module):\n        if isinstance(module, Qwen3TTSTokenizerV2DecoderRotatoryEmbedding):\n            initialize_rope_buffers(module)\n        else:\n            super()._init_weights(module)\n\n\nclass Qwen3TTSTokenizerV2CausalConvNet(nn.Module):", "count": 1,
        }, {
            "path": "qwen_tts/core/models/modeling_qwen3_tts.py",
            "old": "                inputs_embeds = inputs_embeds + tts_pad_embed\n        if attention_mask is not None:",
            "new": "                inputs_embeds = inputs_embeds + tts_pad_embed\n        # Transformers 5 generation tracks position through the KV cache.\n        past_seen_tokens = past_key_values.get_seq_length() if past_key_values is not None else 0\n        cache_position = torch.arange(past_seen_tokens, past_seen_tokens + inputs_embeds.shape[1], device=inputs_embeds.device)\n        if attention_mask is not None:", "count": 1,
        }],
    },
}


SPECS["chatterbox_tts"]["patched_version"] = "0.1.7+workbench.2"
SPECS["qwen_tts"]["patched_version"] = "0.1.1+workbench.1"
SPECS["misaki"] = {
    "version": "0.9.4", "patched_version": "0.9.4+workbench.1",
    "url": "https://files.pythonhosted.org/packages/82/ec/0ee4110ddb54278b8f21c40a140370ae8f687036c4edf578316602697c56/misaki-0.9.4-py3-none-any.whl",
    "sha256": "90e2eeb169786c014c429e5058d2ea6bcd02d651f2a24450ba6c9ffc0f8da15a",
    "requirements": {},
    "source_changes": [{
        "path": "misaki/en.py",
        "old": "def __init__(self, version=None, trf=False, british=False, fallback=None, unk='❓'):",
        "new": "def __init__(self, nlp, version=None, british=False, fallback=None, unk='❓'):",
        "count": 1,
    }, {
        "path": "misaki/en.py",
        "old": "        name = f\"en_core_web_{'trf' if trf else 'sm'}\"\n        if not spacy.util.is_package(name):\n            spacy.cli.download(name)\n        components = ['transformer' if trf else 'tok2vec', 'tagger']\n        self.nlp = spacy.load(name, enable=components)",
        "new": "        # Workbench supplies an offline, explicitly loaded language model.\n        self.nlp = nlp",
        "count": 1,
    }],
}


def build(name, spec):
    source = OUTPUT / "upstream" / f"{name}-{spec['version']}-py3-none-any.whl"
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        with urllib.request.urlopen(spec["url"], timeout=30) as response:
            source.write_bytes(response.read())
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError(f"Unexpected upstream wheel: {name}")
    changes = spec.get("source_changes", [])
    version = spec["patched_version"]
    original_info = f"{name}-{spec['version']}.dist-info"
    info = f"{name}-{version}.dist-info"
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        files = {path.replace(original_info, info): archive.read(path) for path in archive.namelist()
                 if not path.endswith("/RECORD")}
    for change in changes:
        content = files[change["path"]].decode()
        if content.count(change["old"]) != change["count"]:
            raise ValueError(f"Unexpected source for patch: {change['path']}")
        files[change["path"]] = content.replace(change["old"], change["new"]).encode()
    metadata = BytesParser(policy=policy.compat32).parsebytes(files[info + "/METADATA"])
    requirements = metadata.get_all("Requires-Dist", [])
    if not set(spec["requirements"]) <= set(requirements):
        raise ValueError(f"Unexpected upstream requirements: {name}")
    metadata.replace_header("Version", version)
    metadata.replace_header("Requires-Python", "==3.12.*")
    del metadata["Requires-Dist"]
    for requirement in requirements:
        metadata["Requires-Dist"] = spec["requirements"].get(requirement, requirement)
    files[info + "/METADATA"] = metadata.as_bytes(policy=policy.compat32.clone(max_line_length=0, linesep="\n"))
    files[info + "/WORKBENCH_PATCH.json"] = (json.dumps({
        "upstream_url": spec["url"], "upstream_sha256": spec["sha256"], "version": version,
        "changes": spec["requirements"], "source_changes": changes,
    }, sort_keys=True, indent=2) + "\n").encode()
    record = StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for path, content in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        writer.writerow((path, "sha256=" + digest, len(content)))
    writer.writerow((info + "/RECORD", "", ""))
    files[info + "/RECORD"] = record.getvalue().encode()
    target = CATALOG / "wheels" / f"{name}-{version}-py3-none-any.whl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, content in sorted(files.items()):
            entry = zipfile.ZipInfo(path, date_time=(2026, 9, 20, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, content, compresslevel=9)
    print(json.dumps({"wheel": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}), flush=True)
    return version


if __name__ == "__main__":
    for name, spec in SPECS.items():
        build(name, spec)
