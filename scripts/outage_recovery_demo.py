"""Prove a genuine process kill/restart recovery from a DIAGNOSING checkpoint.

Run ``python scripts/outage_recovery_demo.py``.  The parent launches a worker,
waits until it has persisted DIAGNOSING, terminates that OS process, creates a
fresh workflow instance, loads that checkpoint, and continues the graph.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graphs.outage import OutageWorkflow
from shared.checkpointing import CheckpointStore, load_checkpoint

DB = ROOT / 'db' / 'nexlink.db'
THREAD = 'crash-proof-demo'

def tool(name, args):
    return {'ok': True, 'status': 'physical fault' if name == 'get_equipment_diagnostics' else 'ok'}

def worker() -> None:
    graph = OutageWorkflow(CheckpointStore(DB), tool)
    state = graph.advance(graph.start('crash-proof', 1, ['no internet'], THREAD), pause_after='DIAGNOSING')
    print(f'CHECKPOINT_READY state={state["current_state"]} checkpoint={state["checkpoint_id"]}', flush=True)
    while True:
        time.sleep(1)

def demonstrate() -> None:
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker'], stdout=subprocess.PIPE, text=True)
    assert child.stdout is not None
    try:
        ready = child.stdout.readline().strip()
        if not ready.startswith('CHECKPOINT_READY'):
            raise RuntimeError(f'worker did not reach recovery point: {ready!r}')
        print(ready)
    finally:
        child.terminate()
        child.wait(timeout=10)
    print(f'PROCESS_KILLED exit_code={child.returncode}')

    # New store + new graph instance represent a completely restarted process.
    state = load_checkpoint(CheckpointStore(DB), THREAD)
    if not state:
        raise RuntimeError('checkpoint was not persisted')
    print(f'RESTART_LOADED state={state["current_state"]} checkpoint={state["checkpoint_id"]}')
    resumed = OutageWorkflow(CheckpointStore(DB), tool).advance(state)
    print(f'RESUMED_TO state={resumed["current_state"]} checkpoint={resumed["checkpoint_id"]}')

if __name__ == '__main__':
    worker() if '--worker' in sys.argv else demonstrate()
