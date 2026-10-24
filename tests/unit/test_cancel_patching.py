"""Cancelling while the patch tool runs kills it at once and restores the target."""

import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from adapters.g3mtool_adapter import G3MToolManager
from services.mod_operation_executor import (
    ModOperationCancelledError,
    ModOperationExecutor,
)
from services.mod_operation_support import create_g3mtool_patcher
from utils.mod.operation_plan import ModOperationPlan, PlannedModOperation


def test_cancel_during_a_running_patch_restores_the_target(tmp_path, monkeypatch):
    source, target = tmp_path / "p.xdelta", tmp_path / "data.win"
    source.write_bytes(b"p")
    target.write_bytes(b"original")
    cancelled = threading.Event()

    def slow_tool(self, *_args, **_kwargs):
        return self._run([sys.executable, "-c", "import time; time.sleep(60)"])

    monkeypatch.setattr(G3MToolManager, "xpatch_apply", slow_tool)
    monkeypatch.setattr(G3MToolManager, "is_available", lambda self: True)
    monkeypatch.setattr(G3MToolManager, "refresh_executable", lambda self: "tool")
    patcher = create_g3mtool_patcher(Mock(local_config={}), is_cancelled=cancelled.is_set)
    operation = PlannedModOperation(0, (), "patch", source, False, target, False, None, None, mod_id="m")
    threading.Timer(0.5, cancelled.set).start()
    started = time.monotonic()

    with pytest.raises(ModOperationCancelledError):
        ModOperationExecutor(tmp_path / "journal", patcher=patcher).execute(
            ModOperationPlan((operation,), ()), is_cancelled=cancelled.is_set
        )

    assert time.monotonic() - started < 10
    assert Path(target).read_bytes() == b"original"
