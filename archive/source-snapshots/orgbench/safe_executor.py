"""Hard process limits around the restricted AST evaluator (not native Python).

The child is isolated from Python site/cwd imports, receives a minimal
environment, and installs a 256MiB process-memory limit before reading input.
This is defense in depth for generated code, not a production arbitrary-code
sandbox. Candidate source is still interpreted, never exec/eval/compiled.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading


MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
STDOUT_LIMIT_BYTES = 256 * 1024
STDERR_LIMIT_BYTES = 16 * 1024
INPUT_LIMIT_BYTES = 2 * 1024 * 1024
HARD_TIMEOUT_SECONDS = 5.0


class SafeExecutionError(ValueError):
    pass


class SafeExecutorInfrastructureError(SafeExecutionError):
    """Worker setup/IPC failure, distinct from a candidate resource failure."""


def _memory_limit():
    """Fail closed if the worker cannot install the required memory bound."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise SafeExecutorInfrastructureError("Unable to create Windows memory-limit job")
        info = EXTENDED()
        # PROCESS_MEMORY | ACTIVE_PROCESS(1) | KILL_ON_JOB_CLOSE
        info.BasicLimitInformation.LimitFlags = 0x100 | 0x8 | 0x2000
        info.BasicLimitInformation.ActiveProcessLimit = 1
        info.ProcessMemoryLimit = MEMORY_LIMIT_BYTES
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise SafeExecutorInfrastructureError("Unable to set Windows job memory bound")
        if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
            raise SafeExecutorInfrastructureError("Unable to assign worker to Windows memory-limit job")
        # Keep the job handle alive until the OS tears down this child. Explicit
        # CloseHandle would trigger KILL_ON_JOB_CLOSE while replying to parent.
        return job
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    return True


def run_isolated(request: dict, *, timeout_s: float = HARD_TIMEOUT_SECONDS,
                 stdout_limit: int = STDOUT_LIMIT_BYTES):
    """Run one IPC operation with hard kill and bounded pipe readers."""
    if not 0 < timeout_s <= 30 or not 1 <= stdout_limit <= STDOUT_LIMIT_BYTES:
        raise SafeExecutionError("Invalid worker limits")
    try:
        wire = json.dumps(request, ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError):
        raise SafeExecutionError("Worker input must be finite JSON") from None
    if len(wire) > INPUT_LIMIT_BYTES:
        raise SafeExecutionError("Worker input exceeds 2MiB limit")
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        process = subprocess.Popen([sys.executable, "-I", "-S", str(Path(__file__).resolve()), "--worker"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env, **options)
    except OSError as exc:
        raise SafeExecutorInfrastructureError(f"Worker process startup failed ({type(exc).__name__})") from None
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    overflow = threading.Event()

    def reader(stream, name, limit):
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                if len(captured[name]) + len(chunk) > limit:
                    overflow.set()
                    process.kill()
                    break
                captured[name].extend(chunk)
        except (OSError, ValueError):
            pass
        finally:
            stream.close()

    def writer():
        try:
            process.stdin.write(wire)
            process.stdin.close()
        except (OSError, ValueError):
            pass

    threads = [threading.Thread(target=reader, args=(process.stdout, "stdout", stdout_limit), daemon=True),
               threading.Thread(target=reader, args=(process.stderr, "stderr", STDERR_LIMIT_BYTES), daemon=True),
               threading.Thread(target=writer, daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait(timeout=2)
    finally:
        for thread in threads:
            thread.join(timeout=.5)
    if timed_out:
        raise SafeExecutionError(f"Isolated worker hard timeout ({timeout_s:g}s)")
    if overflow.is_set():
        raise SafeExecutionError("Isolated worker output limit exceeded")
    if process.returncode != 0:
        if process.returncode == 2:
            raise SafeExecutorInfrastructureError("Isolated worker startup failed")
        raise SafeExecutionError("Isolated worker terminated (memory/resource/runtime limit)")
    try:
        envelope = json.loads(captured["stdout"])
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SafeExecutorInfrastructureError("Isolated worker returned invalid IPC JSON") from None
    if not isinstance(envelope, dict):
        raise SafeExecutorInfrastructureError("Isolated worker returned invalid IPC envelope")
    if envelope.get("executor_infrastructure_error") is True:
        raise SafeExecutorInfrastructureError(str(envelope.get("error", "Worker infrastructure failed"))[:1000])
    if envelope.get("memory_limit_enforced") is not True:
        raise SafeExecutorInfrastructureError("Isolated worker resource policy not verified")
    if envelope.get("ok") is not True:
        raise SafeExecutionError(str(envelope.get("error", "Isolated execution failed"))[:1000])
    return envelope.get("result")


def _worker():
    memory_enforced = False
    candidate_error_type = None
    try:
        job = _memory_limit()
        memory_enforced = bool(job)
        if not memory_enforced:
            raise SafeExecutorInfrastructureError("Worker memory policy was not installed")
        raw = sys.stdin.buffer.read(INPUT_LIMIT_BYTES + 1)
        if len(raw) > INPUT_LIMIT_BYTES:
            raise SafeExecutorInfrastructureError("Worker input limit exceeded")
        try:
            request = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise SafeExecutorInfrastructureError("Worker received invalid IPC JSON") from None
        if not isinstance(request, dict):
            raise SafeExecutorInfrastructureError("Worker input must be an object")
        # -I/-S removed cwd/site packages; expose only this trusted repository
        # location to the worker, never a model-controlled module search path.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from orgbench import code_tasks
        candidate_error_type = code_tasks.CandidateError
        if request.get("operation") == "policy":
            result = {"process_memory_limit_bytes": MEMORY_LIMIT_BYTES,
                      "memory_limit_enforced": bool(job),
                      "python_isolated": sys.flags.isolated,
                      "python_no_site": sys.flags.no_site,
                      "stdout_limit_bytes": STDOUT_LIMIT_BYTES,
                      "environment_has_api_secrets": any("ANTHROPIC" in k or "OPENAI" in k for k in os.environ)}
        elif request.get("operation") == "run":
            result = code_tasks._run_candidate_local(request.get("source"), request.get("payload"))
        elif request.get("operation") == "test":
            result = code_tasks._test_source_local(request.get("answer"), request.get("cases", []),
                                                  public=request.get("public") is True)
        else:
            raise SafeExecutorInfrastructureError("Unsupported worker operation")
        envelope = {"ok": True, "result": result, "memory_limit_enforced": bool(job)}
    except Exception as exc:
        # CandidateError messages are controlled by our evaluator. Do not echo
        # generic exception details, environment values, tracebacks or files.
        is_candidate = (candidate_error_type is not None and isinstance(exc, candidate_error_type))
        resource_failure = isinstance(exc, (MemoryError, RecursionError))
        infrastructure = isinstance(exc, SafeExecutorInfrastructureError) or not (is_candidate or resource_failure)
        message = str(exc)[:1000] if isinstance(exc, (SafeExecutionError, ValueError)) else type(exc).__name__
        envelope = {"ok": False, "error": message, "memory_limit_enforced": memory_enforced,
                    "executor_infrastructure_error": infrastructure}
    output = json.dumps(envelope, ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(output) > STDOUT_LIMIT_BYTES:
        output = b'{"ok":false,"error":"Worker output limit exceeded","memory_limit_enforced":true}'
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("Internal isolated AST worker only")
    _worker()
