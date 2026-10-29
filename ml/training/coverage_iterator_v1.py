"""One immutable scheduled train pass; no model imports or source-data mutation."""
import json
from pathlib import Path


def make_coverage_iterator(original, schedule, rows, trace_path):
    assert len(schedule) == len(rows)
    assert sorted(x['row_index'] for x in schedule) == list(range(len(rows)))
    assert len({r['case_id'] for r in rows}) == len(rows)
    for step, entry in enumerate(schedule, 1):
        assert entry['step'] == step
        assert entry['case_id'] == rows[entry['row_index']]['case_id']
    started = False

    def iterator(dataset, batch_size, max_seq_length, loop=False, seed=None, comm_group=None):
        nonlocal started
        if not loop:
            yield from original(dataset=dataset, batch_size=batch_size,
                                max_seq_length=max_seq_length, loop=loop,
                                seed=seed, comm_group=comm_group)
            return
        assert not started, 'A second train pass is forbidden'
        started = True
        assert batch_size == 1 and len(dataset) == len(rows)
        assert comm_group is None or (comm_group.size() == 1 and comm_group.rank() == 0)
        assert not Path(trace_path).exists(), 'Training trace must be new'
        for entry in schedule:
            index = entry['row_index']
            assert dataset._data[index] == rows[index], 'Dataset index binding changed'
            item = dataset[index]
            assert len(item[0]) <= max_seq_length, 'Token truncation forbidden'

            class OneRow:
                def __len__(self):
                    return 1

                def __getitem__(self, index):
                    assert index == 0
                    return item

            batches = original(dataset=OneRow(), batch_size=1,
                               max_seq_length=max_seq_length, loop=False,
                               seed=None, comm_group=comm_group)
            batch = next(batches)
            try:
                next(batches)
            except StopIteration:
                pass
            else:
                raise AssertionError('Expected exactly one batch')
            with Path(trace_path).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({**entry, 'event': 'batch_issued',
                                         'tokens': len(item[0])}, ensure_ascii=False) + '\n')
            yield batch
    return iterator


def cpu_checks():
    import tempfile
    rows = [{'case_id': f'train-{i}'} for i in range(6)]
    schedule = [{'step': j+1, 'row_index': i, 'case_id': rows[i]['case_id'],
                 'bank': 'a' if i % 2 else 'b'} for j, i in enumerate([3, 1, 5, 2, 0, 4])]
    class FakeDataset:
        _data = rows
        def __len__(self): return len(rows)
        def __getitem__(self, i): return ([i+10]*3, 1)
    def original(dataset, **kw):
        for i in range(len(dataset)): yield dataset[i]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'trace.jsonl'
        iterator = make_coverage_iterator(original, schedule, rows, path)
        batches = list(iterator(FakeDataset(), 1, 10, loop=True))
        assert [b[0][0]-10 for b in batches] == [3, 1, 5, 2, 0, 4]
        trace = [json.loads(s) for s in path.read_text().splitlines()]
        assert [r['case_id'] for r in trace] == [s['case_id'] for s in schedule]
        assert len({r['row_index'] for r in trace}) == 6
        try: list(iterator(FakeDataset(), 1, 10, loop=True))
        except AssertionError: pass
        else: raise AssertionError('Second pass allowed')
        before = path.read_bytes()
        assert len(list(iterator(FakeDataset(), 1, 10, loop=False))) == 6
        assert before == path.read_bytes(), 'Validation logged as training'
    return ['scheduled_order_preserved', 'each_train_row_once', 'trace_id_binding',
            'second_pass_refused', 'validation_delegated_without_trace', 'no_data_mutation']

if __name__ == '__main__':
    print(json.dumps({'checks': cpu_checks(), 'model_loaded': False}))
