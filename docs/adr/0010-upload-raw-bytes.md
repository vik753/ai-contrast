# ADR 0010 — Upload: one file per request, raw bytes, no multipart

- Status: accepted (tech lead decision, 2026-10-21)
- Date: 2026-10-21
- Related: ADR 0001 (stateless), ADR 0004 (text extraction), ADR 0008 (pseudonymization), threat model T3, T4, T6, T11

## Context

Stage 2 adds file upload. The usual FastAPI way is `multipart/form-data` with `UploadFile`. That needs a new dependency, `python-multipart`, whose parser has had several denial-of-service advisories. Starlette also spools every uploaded file above 1 MB to a temporary file on disk, but threat model T3 requires in-memory processing. Multipart part headers carry the file name, and ADR 0008 forbids file names in the server's text pipeline.

## Decision

- The browser sends **one file per request**: `POST /api/extract` with the raw file bytes as the body, `Content-Type: application/octet-stream` and a required `Content-Length`. There is no multipart, no form field and no file name in the URL, the headers or the body.
- The server reads the body into memory with a hard cap and counts the bytes while it reads. It never writes the file to disk and never uses `UploadFile`, `request.form()` or temporary files.
- No new dependency: `python-multipart` is not added.
- The server stays stateless and does not know which files belong to which contract. The browser groups the files into contracts (main text plus annexes, labels A, B, C) and sends the grouped, extracted text to later endpoints.
- Only `application/octet-stream` is accepted. A plain HTML form cannot send it, so every cross-site request needs a CORS preflight, which our CORS allowlist blocks.
- A server-wide limit on extractions in progress. Above it, the server answers `503` with the code `busy` and `Retry-After`. The browser sends at most two files at a time and retries `busy` with a capped delay.
- A global request-body limit for every route (pure ASGI middleware): a small limit for JSON routes, the file limit for `/api/extract`.

## Consequences

- File names never reach the server at all. This is stronger than ADR 0008 point 8.
- A multi-file upload makes several requests. This is acceptable for up to 25 files.
- Count limits (files per contract, contracts per analysis) are enforced by the browser at upload time and by the server on the analysis request (stage 9), not on the extract request.
- Per-IP rate limiting (T6 control 1) arrives with the free model at stage 6. It must be in place before deployment (stage 13).
