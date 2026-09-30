"""Runtime wheel boundaries: inference-only sources and reproducible artifact edits."""
import ast
from email.parser import BytesParser
import hashlib
import zipfile

import pytest

from scripts import build_runtime_wheels as builder


def test_audio_wheels_exclude_unsupported_imports_and_entrypoints():
    forbidden = {'gradio', 'pre_commit', 'onnx', 'sox'}
    for name in ('chatterbox_tts', 'qwen_tts', 's3tokenizer'):
        spec = builder.SPECS[name]
        with zipfile.ZipFile(builder.CATALOG / 'wheels' / f"{name}-{spec['patched_version']}-py3-none-any.whl") as wheel:
            for path in wheel.namelist():
                assert 'tokenizer_25hz/' not in path
                if not path.endswith('.py'):
                    continue
                source = wheel.read(path).decode('utf-8')
                tree = ast.parse(source, filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        assert not forbidden & {alias.name.split('.')[0] for alias in node.names}, path
                    elif isinstance(node, ast.ImportFrom):
                        assert (node.module or '').split('.')[0] not in forbidden, path
                    elif isinstance(node, ast.FunctionDef) and name == 's3tokenizer':
                        assert node.name not in {'onnx2torch', 'onnx2torch_v3', '_rename_weights',
                                                 'init_from_onnx', '_download', 'load_model', 'available_models'}
                if name == 'qwen_tts':
                    assert 'Qwen3TTSTokenizerV1' not in source and 'qwen3_tts_tokenizer_25hz' not in source
            if name in {'qwen_tts', 's3tokenizer'}:
                assert not any(path.endswith('/entry_points.txt') for path in wheel.namelist())
            if name == 's3tokenizer':
                assert 's3tokenizer/cli.py' not in wheel.namelist()
            if name == 'chatterbox_tts':
                tokenizer = wheel.read('chatterbox/models/tokenizers/tokenizer.py').decode()
                assert 'import pykakasi' in tokenizer and 'from spacy_pkuseg import pkuseg' in tokenizer


@pytest.fixture
def wheel_source(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, 'OUTPUT', tmp_path / 'build')
    monkeypatch.setattr(builder, 'CATALOG', tmp_path / 'catalog')
    source = builder.OUTPUT / 'upstream/example-1.0-py3-none-any.whl'
    source.parent.mkdir(parents=True)
    removed = b'def demo(): pass\n'
    with zipfile.ZipFile(source, 'w') as wheel:
        wheel.writestr('example/__init__.py', 'from .demo import demo\nvalue = 1\n')
        wheel.writestr('example/demo.py', removed)
        wheel.writestr('example-1.0.dist-info/METADATA',
                       'Metadata-Version: 2.1\nName: example\nVersion: 1.0\nRequires-Python: >=3.10\n'
                       'Requires-Dist: gradio\nRequires-Dist: numpy\n')
        wheel.writestr('example-1.0.dist-info/RECORD', '')
    return {'version': '1.0', 'patched_version': '1.0+workbench.1', 'url': 'https://runtime.test/example.whl',
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'requirements': {},
            'removed_requirements': ['gradio'],
            'removed_files': {'example/demo.py': hashlib.sha256(removed).hexdigest()},
            'source_changes': [{'path': 'example/__init__.py', 'old': 'from .demo import demo\n',
                                'new': '', 'count': 1}]}


def test_wheel_removals_are_reproducible_and_preserve_required_dependencies(wheel_source):
    builder.build('example', wheel_source)
    target = builder.CATALOG / 'wheels/example-1.0+workbench.1-py3-none-any.whl'
    original = target.read_bytes()
    builder.build('example', wheel_source)
    assert target.read_bytes() == original
    with zipfile.ZipFile(target) as wheel:
        assert 'example/demo.py' not in wheel.namelist()
        assert wheel.read('example/__init__.py') == b'value = 1\n'
        metadata = BytesParser().parsebytes(wheel.read('example-1.0+workbench.1.dist-info/METADATA'))
        assert metadata.get_all('Requires-Dist') == ['numpy']


@pytest.mark.parametrize('field', ['removed_files', 'removed_requirements'])
def test_wheel_removal_rejects_unexpected_upstream_content(wheel_source, field):
    wheel_source[field] = ({'example/demo.py': '0' * 64} if field == 'removed_files' else ['missing'])
    with pytest.raises(ValueError, match='Unexpected'):
        builder.build('example', wheel_source)
