# Offline reference vocabulary

`o200k_base.tiktoken` is the OpenAI tiktoken reference vocabulary from
https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken.
Its upstream SHA-256 is
`446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`.

The application reads this bundled resource directly. It does not invoke a
network or cache loader at runtime. Provider counts are estimates, not the
provider's native tokenizer or its reported usage. No model weights are included.
