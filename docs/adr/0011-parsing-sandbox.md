# ADR 0011 — Parsing sandbox: one subprocess per file with OS limits

- Status: accepted (tech lead decision, 2026-10-21)
- Date: 2026-10-21
- Related: ADR 0004 (text extraction), ADR 0009 Layer 0, ADR 0010 (upload), threat model T4, T6

## Context

Stage 3 parses untrusted PDF, DOCX and text files. Parsers are complex and have had memory, CPU and recursion bugs (for example pdfminer recurses on the `Prev` chain without a guard). One bad file must not take down the server (512 MB RAM, one worker process, ADR 0010).

## Decision

- Every extraction runs in a **new Python subprocess**: `sys.executable -I -B -c <bootstrap> <app root> <memory bytes> <cpu seconds>`, in a new session (own process group), with a minimal environment (`LC_ALL=C.UTF-8` only; the server environment is never copied) and the working directory `/tmp`. With `-I` neither the working directory nor `PYTHONPATH` is on `sys.path`, so the bootstrap puts the app root first on `sys.path` and runs `app.extraction.worker`. The parent computes the app root from `app.__file__`, never from input or the environment. The worker imports only the extraction code (no FastAPI, settings or logging configuration).
- The parent writes one JSON header line (kind, size, text caps) and then the file bytes to the child's stdin, and reads one JSON object from its stdout: `{"result": ...}` or `{"error": "<code>"}` (only the codes the child may report). The parent validates it with the strict Pydantic models and checks kind, byte count and caps again. The child's stderr is read at the same time and thrown away: it is never logged, because it can contain contract text. Reading stdout, draining stderr and writing stdin run concurrently, so no pipe can deadlock.
- The child sets its own limits before it reads any input, with `resource.setrlimit` (soft and hard): address space (`RLIMIT_AS` = `EXTRACT_WORKER_MEMORY_MB`), CPU time (`RLIMIT_CPU` = `EXTRACT_WORKER_CPU_SECONDS`, hard limit one second later), file size 0 (`RLIMIT_FSIZE`: it writes no files), 32 open files (`RLIMIT_NOFILE`), no new processes (`RLIMIT_NPROC` = 0: `fork` fails, because the container user is not root), no core dumps (`RLIMIT_CORE` = 0). The bootstrap appends the app root to `sys.path` (after the standard library and site-packages), so no file in the app root can shadow a standard module.
- The parent enforces a wall-clock deadline (`EXTRACT_WORKER_WALL_SECONDS` → `extraction_timeout`) and a cap on the result size (`EXTRACT_MAX_RESULT_BYTES`; reading stops at the cap → `extraction_failed`). A non-zero exit or a signal (CPU or memory limit included), invalid JSON or a reply outside the schema → `extraction_failed`. On every path that leaves the child running (error, timeout, cancellation of the request) the parent kills the whole process group with `SIGKILL`, then always waits for the child (no zombie) and reads the rest of its pipes so that they close. If the child cannot be started (`OSError`), the answer is `extraction_failed`, logged as a code without a traceback. It never retries. The extraction slot is held while the child runs and until the last byte of the response is sent: the response is sent in 64 KiB chunks under a deadline (`EXTRACT_SEND_TIMEOUT_SECONDS`, 30 s); a client that does not read is cut off and the slot is freed (threat model T6 control 9). uvicorn runs with `--limit-concurrency 32`.
- A test-only hook (`AI_CONTRAST_WORKER_TEST_HOOK`) exists for the robustness tests. Only `run_extraction(..., test_hook=...)` sets it, in the child's minimal environment; the HTTP handler never passes it, and the server's own environment variable has no effect because the environment is never copied.
- The extraction kind comes only from the server's own detection of the same bytes in the same request (ADR 0010), never from the client.
- One subprocess per file (no worker pool): no state can leak between files, and memory is returned to the OS after every file. The start-up cost (about 0.2–0.5 s) is acceptable for this workload.
- Dependencies (approved by `security-reviewer` before use): no python-docx and no pdfplumber; the DOCX walker uses `defusedxml`, the PDF device uses `pdfminer.six`.

## Consequences

- A parser bug costs one request, not the server.
- Memory budget: 2 extraction slots × the child limit + the parent must stay under 512 MB. Measured in S3-T1 review round 1 (Python 3.13, plain text, uvicorn with one worker, caps: result 4 MiB, text 1,000,000 characters):
  - parent idle RSS: 47 MiB;
  - parent peak RSS (`VmHWM`), two clients that upload 999,990 non-BMP characters (3.9 MB UTF-8, result 4.0 MB, just under the 4 MiB cap) and never read the response, held until the send deadline cut them off: **74 MiB**;
  - parent peak RSS, two concurrent requests repeated three times (one result at the cap of non-BMP characters, one 10 MiB UTF-16 file of non-BMP characters rejected with `too_much_text`): **84.2 MiB**;
  - child peak RSS: 51 MiB (result at the cap of non-BMP characters), 58 MiB (10 MiB UTF-16 of non-BMP characters); the child cannot exceed its address-space limit of 192 MiB (`EXTRACT_WORKER_MEMORY_MB`);
  - worst case: 84.2 + 2 × 192 = **468.2 MiB < 512 MiB**. S3-T2 and S3-T3 measure again with DOCX and PDF parsers.
- A connection that was cut off can keep its unsent bytes in the server's write buffer until the peer closes it; chunked sending keeps this to about one chunk (64 KiB) plus the transport high-water mark per connection, and `--limit-concurrency 32` caps the number of connections.
- `multiprocessing` is not used: it forks or pickles state and complicates limits.
