# ADR 0011 — Parsing sandbox: one subprocess per file with OS limits

- Status: accepted (tech lead decision, 2026-10-21)
- Date: 2026-10-21
- Related: ADR 0004 (text extraction), ADR 0009 Layer 0, ADR 0010 (upload), threat model T4, T6

## Context

Stage 3 parses untrusted PDF, DOCX and text files. Parsers are complex and have had memory, CPU and recursion bugs (for example pdfminer recurses on the `Prev` chain without a guard). One bad file must not take down the server (512 MB RAM, one worker process, ADR 0010).

## Decision

- Every extraction runs in a **new Python subprocess**: `sys.executable -I -m app.extraction.worker`, with a minimal environment and the working directory `/tmp`.
- The parent writes the file bytes and the detected kind to the child's stdin and reads one JSON result from its stdout. The child's stderr is read and thrown away: it is never logged, because it can contain contract text.
- The child sets its own limits before it reads any input, with `resource.setrlimit`: address space (`RLIMIT_AS`), CPU time (`RLIMIT_CPU`), file size 0 (`RLIMIT_FSIZE`: it writes no files), a small number of open files (`RLIMIT_NOFILE`), no core dumps (`RLIMIT_CORE`).
- The parent enforces a wall-clock deadline and a cap on the result size. On a timeout, a crash, a limit hit or an oversized result it kills the child and answers with an error code. It never retries.
- The extraction kind comes only from the server's own detection of the same bytes in the same request (ADR 0010), never from the client.
- One subprocess per file (no worker pool): no state can leak between files, and memory is returned to the OS after every file. The start-up cost (about 0.2–0.5 s) is acceptable for this workload.
- Dependencies (approved by `security-reviewer` before use): no python-docx and no pdfplumber; the DOCX walker uses `defusedxml`, the PDF device uses `pdfminer.six`.

## Consequences

- A parser bug costs one request, not the server.
- Memory budget: 2 extraction slots × the child limit + the parent must stay under 512 MB. The child limit is a setting and is measured with real files in stage 3.
- `multiprocessing` is not used: it forks or pickles state and complicates limits.
