"""Local training data loader that never opens a holdout split.

The dataset builder is injected; importing this module does not import MLX.
"""
import json
from pathlib import Path


def load_train_valid_only(args, tokenizer, dataset_builder):
    if not getattr(args, 'train', False) or getattr(args, 'test', False):
        raise ValueError('This loader supports training only; holdout evaluation requires a separate frozen run')
    if getattr(args, 'hf_dataset', False):
        raise ValueError('Only pinned local train/valid data are supported')
    directory = Path(args.data)
    if not directory.is_dir():
        raise ValueError('Local data directory is required; no network dataset fallback')
    datasets = []
    for split in ('train', 'valid'):
        path = directory / (split + '.jsonl')
        with path.open(encoding='utf-8') as stream:
            rows = [json.loads(line) for line in stream]
        if not rows:
            raise ValueError(f'{split} data must not be empty')
        datasets.append(dataset_builder(rows, tokenizer, args))
    return datasets[0], datasets[1], []


def cpu_checks():
    import tempfile
    from types import SimpleNamespace
    from unittest.mock import patch
    checks = []
    with tempfile.TemporaryDirectory(prefix='porukam-train-valid-loader-') as tmp:
        directory = Path(tmp)
        (directory / 'train.jsonl').write_text('{"messages": []}\n', encoding='utf-8')
        (directory / 'valid.jsonl').write_text('{"messages": []}\n', encoding='utf-8')
        # This deliberately invalid sentinel must never be opened or parsed.
        (directory / 'test.jsonl').write_text('FORBIDDEN_HOLDOUT_SENTINEL', encoding='utf-8')
        args = SimpleNamespace(train=True, test=False, hf_dataset=False, data=str(directory))
        original_open = Path.open
        opened = []

        def guarded_open(path, *pos, **kw):
            opened.append(path.name)
            assert path.name in {'train.jsonl', 'valid.jsonl'}, 'Holdout file access'
            return original_open(path, *pos, **kw)

        built = []

        def builder(rows, tokenizer, configuration):
            assert tokenizer is None and configuration is args
            built.append(rows)
            return rows

        with patch.object(Path, 'open', guarded_open):
            train, valid, test = load_train_valid_only(args, None, builder)
        assert opened == ['train.jsonl', 'valid.jsonl'] and test == [] and len(built) == 2
        checks.extend(['only_train_valid_opened', 'invalid_holdout_sentinel_not_parsed',
                       'builder_gets_original_tokenizer_and_config', 'empty_test_returned'])
        for key, value in [('test', True), ('train', False), ('hf_dataset', True)]:
            bad = SimpleNamespace(**vars(args))
            setattr(bad, key, value)
            with patch.object(Path, 'open', side_effect=AssertionError('No reads before refusal')):
                try:
                    load_train_valid_only(bad, None, builder)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f'{key} not refused')
            checks.append(key + '_refused_before_file_read')
        empty = SimpleNamespace(**vars(args))
        empty.data = str(directory / 'missing')
        try:
            load_train_valid_only(empty, None, builder)
        except ValueError:
            checks.append('missing_local_directory_no_network_fallback')
        else:
            raise AssertionError('Missing directory accepted')
        (directory / 'train.jsonl').write_text('', encoding='utf-8')
        try:
            load_train_valid_only(args, None, builder)
        except ValueError:
            checks.append('empty_train_refused')
        else:
            raise AssertionError('Empty train accepted')
        (directory / 'train.jsonl').write_text('{"messages": []}\n', encoding='utf-8')
        (directory / 'valid.jsonl').write_text('', encoding='utf-8')
        try:
            load_train_valid_only(args, None, builder)
        except ValueError:
            checks.append('empty_valid_refused')
        else:
            raise AssertionError('Empty valid accepted')
    return checks


if __name__ == '__main__':
    print(json.dumps({'checks': cpu_checks(), 'mlx_imported': False, 'model_loaded': False}))
