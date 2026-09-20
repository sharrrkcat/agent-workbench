"""Run with the installed inference Python to check Qwen checkpoint RoPE buffers."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
import torch
from qwen_tts.core.models.configuration_qwen3_tts import Qwen3TTSTalkerConfig, Qwen3TTSTalkerCodePredictorConfig
from qwen_tts.core.models.modeling_qwen3_tts import Qwen3TTSTalkerModel, Qwen3TTSTalkerCodePredictorModel
from qwen_tts.core.tokenizer_12hz.configuration_qwen3_tts_tokenizer_v2 import Qwen3TTSTokenizerV2DecoderConfig
from qwen_tts.core.tokenizer_12hz.modeling_qwen3_tts_tokenizer_v2 import Qwen3TTSTokenizerV2DecoderTransformerModel


def main():
    small = dict(hidden_size=16, intermediate_size=32, num_attention_heads=2, num_key_value_heads=2,
                 num_hidden_layers=1, max_position_embeddings=32)
    talker = Qwen3TTSTalkerConfig(**small, head_dim=8, vocab_size=32, text_vocab_size=32, text_hidden_size=16,
        rope_scaling={"rope_type": "default", "mrope_section": [1, 1, 2], "interleaved": True})
    predictor = Qwen3TTSTalkerCodePredictorConfig(**small, head_dim=8, vocab_size=32, num_code_groups=2)
    decoder = Qwen3TTSTokenizerV2DecoderConfig(**small, latent_dim=16, sliding_window=16)
    results = []
    with TemporaryDirectory(prefix="workbench-qwen-rope-") as directory:
        for name, cls, config, kwargs in [
            ("talker", Qwen3TTSTalkerModel, talker, {}),
            ("predictor", Qwen3TTSTalkerCodePredictorModel, predictor, {"embedding_dim": 16}),
            ("tokenizer", Qwen3TTSTokenizerV2DecoderTransformerModel, decoder, {}),
        ]:
            model = cls(config, **kwargs).eval()
            positions = torch.arange(3).reshape(1, 3)
            if name == "talker":
                positions = positions.unsqueeze(0).expand(3, -1, -1)
            inputs = torch.zeros(1, 3, 16)
            expected = model.rotary_emb(inputs, positions)
            assert torch.count_nonzero(expected[1]) > 0
            path = Path(directory) / name
            model.save_pretrained(path)
            loaded = cls.from_pretrained(path, config=config, local_files_only=True, **kwargs).eval()
            actual = loaded.rotary_emb(inputs, positions)
            for before, after in zip(expected, actual):
                torch.testing.assert_close(before, after, rtol=0, atol=0)
            assert torch.count_nonzero(actual[1]) > 0
            results.append({"module": name, "checkpoint_round_trip": "passed", "nonzero_position_encoding": "passed"})
    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
