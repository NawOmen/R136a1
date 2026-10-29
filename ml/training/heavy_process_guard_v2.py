"""Case-insensitive full-width process guard v2; no process mutation."""
import os
import re
import shlex
import subprocess


def competing_processes(snapshot, own_pid):
    found = []
    for line in snapshot.splitlines():
        if not line.strip():
            continue
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            raise ValueError('Malformed full-width process inventory')
        pid, ppid, args = int(fields[0]), int(fields[1]), fields[2]
        original_args = args
        args = args.lower()
        if pid == own_pid:
            continue
        # macOS renders executable paths with spaces without shell quoting.
        # Match a real executable suffix, rather than assuming shlex[0] is it.
        backend = bool(re.search(r'(?:^|/)(?:llama-server|ollama_llama_server|mlx_lm\.server)(?:\s|$)', args))
        tokens = shlex.split(args)
        python = bool(re.match(r'^.*?/(?:python(?:\d+(?:\.\d+)*)?)(?:\s|$)', args)) or bool(tokens and re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', tokens[0]))
        script = any(re.fullmatch(r'(?:evaluate_gateway_\S+|start_\S*(?:session|controller)\S*|train_\S+|run_\S*(?:train|eval)\S*)\.py', os.path.basename(t)) for t in tokens)
        mlx = any(t.startswith(('mlx_lm.', 'mlx_whisper')) for t in tokens)
        runner = bool(re.search(r'(?:^|/)ollama\s+runner(?:\s|$)', args))
        if backend or runner or (python and (script or mlx)):
            found.append({'pid': pid, 'ppid': ppid, 'args': original_args})
    return found


def snapshot():
    return subprocess.check_output(['ps', '-axww', '-o', 'pid=,ppid=,args='], text=True)


def require_no_competitors():
    raw = snapshot()
    found = competing_processes(raw, os.getpid())
    if found:
        raise RuntimeError(f'Heavy process present: {found}')
    return raw
