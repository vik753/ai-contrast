# ADR 0011 — Parsing sandbox: one subprocess per file with OS limits

- Status: accepted (tech lead decision, 2026-10-21)
- Date: 2026-10-21
- Related: ADR 0004 (text extraction), ADR 0009 Layer 0, ADR 0010 (upload), threat model T4, T6

## Context

Stage 3 parses untrusted PDF, DOCX and text files. Parsers are complex and have had memory, CPU and recursion bugs (for example pdfminer recurses on the `Prev` chain without a guard). One bad file must not take down the server (512 MB RAM, one worker process, ADR 0010).

## Decision

- Every extraction runs in a **new Python subprocess**: `sys.executable -I -B -c <bootstrap> <app root> <memory bytes> <cpu seconds>`, in a new session (own process group), with a minimal environment (`LC_ALL=C.UTF-8` only; the server environment is never copied) and the working directory `/tmp`. With `-I` neither the working directory nor `PYTHONPATH` is on `sys.path`, so the bootstrap puts the app root first on `sys.path` and runs `app.extraction.worker`. The parent computes the app root from `app.__file__`, never from input or the environment. The worker imports only the extraction code (no FastAPI, settings or logging configuration).
- The parent writes one JSON header line (kind, size, text caps) and then the file bytes to the child's stdin, and reads one JSON object from its stdout: `{"result": ...}` or `{"error": "<code>"}` (only the codes the child may report). The parent validates it with the strict Pydantic models and checks kind, byte count and caps again. The child's stderr is read at the same time and thrown away: it is never logged, because it can contain contract text. Reading stdout, draining stderr and writing stdin run concurrently, so no pipe can deadlock.
- The child sets its own limits before it reads any input, with `resource.setrlimit` (soft and hard): address space (`RLIMIT_AS` = `EXTRACT_WORKER_MEMORY_MB`), CPU time (`RLIMIT_CPU` = `EXTRACT_WORKER_CPU_SECONDS`, hard limit one second later), file size 0 (`RLIMIT_FSIZE`: it writes no files), 32 open files (`RLIMIT_NOFILE`), no core dumps (`RLIMIT_CORE` = 0).
- The parent enforces a wall-clock deadline (`EXTRACT_WORKER_WALL_SECONDS` → `extraction_timeout`) and a cap on the result size (`EXTRACT_MAX_RESULT_BYTES`; reading stops at the cap → `extraction_failed`). A non-zero exit or a signal (CPU or memory limit included), invalid JSON or a reply outside the schema → `extraction_failed`. On every path that leaves the child running (error, timeout, cancellation of the request) the parent kills the whole process group with `SIGKILL`, then always waits for the child (no zombie) and reads the rest of its pipes so that they close. It never retries. The extraction slot is held while the child runs.
- A test-only hook (`AI_CONTRAST_WORKER_TEST_HOOK`) exists for the robustness tests. Only `run_extraction(..., test_hook=...)` sets it, in the child's minimal environment; the HTTP handler never passes it, and the server's own environment variable has no effect because the environment is never copied.
- The extraction kind comes only from the server's own detection of the same bytes in the same request (ADR 0010), never from the client.
- One subprocess per file (no worker pool): no state can leak between files, and memory is returned to the OS after every file. The start-up cost (about 0.2–0.5 s) is acceptable for this workload.
- Dependencies (approved by `security-reviewer` before use): no python-docx and no pdfplumber; the DOCX walker uses `defusedxml`, the PDF device uses `pdfminer.six`.

## Consequences

- A parser bug costs one request, not the server.
- Memory budget: 2 extraction slots × the child limit + the parent must stay under 512 MB. Measured in S3-T1 (Python 3.13, plain text, uvicorn with one worker):
  - parent peak RSS (`VmHWM`) during two concurrent 10 MiB uploads plus results of about 4 MB each: **100.5 MiB** (48 MiB idle);
  - child peak RSS: 63 MiB (2,000,000 ASCII characters, 19,800 blocks), 85 MiB (2,000,000 Cyrillic characters, UTF-8), **102 MiB** (10 MiB UTF-16 of non-BMP characters, rejected with `too_much_text`); the child cannot exceed its address-space limit of 192 MiB (`EXTRACT_WORKER_MEMORY_MB`);
  - worst case: 100.5 + 2 × 192 = **484.5 MiB < 512 MiB**. S3-T2 and S3-T3 measure again with DOCX and PDF parsers.
- `multiprocessing` is not used: it forks or pickles state and complicates limits.
