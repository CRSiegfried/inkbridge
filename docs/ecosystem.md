# Ecosystem survey

Prior art `inkbridge` builds on, as of 2026-07. Verify current status before
depending on anything here — this is a snapshot, not a guarantee.

## Parsing / conversion

- **[supernotelib](https://pypi.org/project/supernotelib/)**
  ([jya-dev/supernote-tool](https://github.com/jya-dev/supernote-tool)) —
  Python, Apache-2.0. The canonical `.note` → PNG/PDF (vector+raster)/SVG/TXT
  converter. No official `.note` spec exists; this parser *is* the de facto
  spec. `inkbridge` depends on this directly for reading notebooks. It also
  reads and decodes `.pdf.mark` (the PDF-annotation sidecar) natively —
  same container family — confirmed on real Manta hardware (see
  Analysis 0003 (unpublished) finding 5), so no
  separate `.mark` reader is needed.
- **[supernote_pdf](https://github.com/RohanGautam/supernote_pdf)** — Rust
  (crates.io). Fast batch `.note` → PDF, optimized for archival speed. Worth
  revisiting if `supernotelib` conversion becomes a bottleneck.

## Cloud / transport

- **[sncloud](https://pypi.org/project/sncloud/)**
  ([julianprester/sncloud](https://github.com/julianprester/sncloud)) —
  Python, Apache-2.0. Unofficial Supernote Cloud client with real `put()`
  upload support plus `ls`/`get`. No delete/move/rename yet. Candidate for
  `inkbridge push`/`pull`.
- **[supernote-cli](https://pypi.org/project/supernote-cli/)**
  ([borismus/supernote-cli](https://github.com/borismus/supernote-cli)) —
  Python, MIT. CLI with an `upload` command (S3-signed flow) and
  `annotation`/`notebook` extraction. Its transcription is **local-Ollama-only**
  (raw HTTP to an Ollama daemon, default `qwen3-vl:8b`; no cloud/OpenAI/Claude
  path) — accurate but slow, and the feature is early (v0.3.1 as of 2026-07, no
  unit tests over the OCR path). The image→text step is a standalone
  `ocr_image(PIL.Image) -> str`, i.e. cleanly separable from `.note` parsing, so
  it maps onto a per-region crop; but it's thin enough (a resize + one prompt +
  one POST) that inkbridge is better served by its own provider-agnostic VLM call
  on a `composite` crop, borrowing supernote-cli's prompt as prior art rather than
  importing it. Closest existing project to the "agentic peripheral" framing this
  repo is going for — worth reading its upload implementation closely.
- **[supernote-cloud-python](https://github.com/bwhitman/supernote-cloud-python)**
  — Python, older, appears less maintained.
- **[supernote-cloud-api](https://github.com/adrianba/supernote-cloud-api)**
  — TypeScript, MIT, abandoned Dec 2022, read-only (no upload). Reference
  only.
- **[supernote-sync](https://github.com/jbchouinard/supernote-sync)** —
  Python. Unlike the others here (all *Cloud* clients), this drives the
  device-local **Browse & Access** HTTP server directly: port 8089, a
  directory listing (HTML page with an embedded JSON `fileList` carrying
  per-file `date` + `size`), download, and limited upload. The de-facto
  reference for Browse & Access, which otherwise has no published API — see
  Analysis 0001 (unpublished) finding 5.
  It's an undocumented, firmware-fragile HTML scrape, so treat it as a
  starting point to validate against a real device, not a stable contract.
- The four Cloud clients above all hit the same endpoint
  (`POST /api/file/list/query` → `userFileVOList`), whose per-file response
  includes `md5`, `updateTime`/`createTime`, and `size` — enough to detect a
  changed file without downloading it (confirmed by reading their source;
  see Analysis 0001 (unpublished) finding
  4). `allenporter/supernote`'s `UserFileVO` model documents the field
  semantics most fully.

## Self-hosted / agent-facing

- **[supernote](https://pypi.org/project/supernote/)**
  ([allenporter/supernote](https://github.com/allenporter/supernote)) —
  Python, Apache-2.0. The most mature project here: a self-hosted "Private
  Cloud" server reimplementing Ratta's sync protocol, plus **an MCP server
  for Claude/Gemini/ChatGPT**, AI synthesis, and semantic search. Read this
  before building `inkbridge`'s own MCP layer — it may be better to build on
  top of it than to duplicate it.
- **[supernote-obsidian-plugin](https://github.com/philips/supernote-obsidian-plugin)**
  — TypeScript, MIT. `.note` → PNG/Markdown export plus live screen-mirror
  capture into Obsidian. Not directly reusable (Obsidian plugin runtime) but
  a useful reference for the screen-mirror capture path.
- **[sugoi-supernote](https://github.com/dwongdev/sugoi-supernote)** —
  awesome-list aggregator: root guides, sync tools, community automations.
  Good jump-off point when a new need comes up.

## Device facts (for context)

Manta = Ratta's flagship 10.7" tablet (~$459, released ~late 2024/early
2025): Rockchip RK3566, 4GB RAM, 32GB storage + microSD, E Ink Carta 1300
(1920×2560), dual-band WiFi, BT 5.0, USB-C. Runs an Android-based, locked-down
OS fork ("Chauvet"). Connectivity: **Browse & Access** (device-hosted WiFi
HTTP server on port 8089, no *official* API spec but already
reverse-engineered by `supernote-sync` above), **Supernote Cloud** sync, USB
mass-storage/MTP, and ADB (closed by default, unlockable; no official SSH).
See
[Browse & Access docs](https://support.supernote.com/en_US/Tools-Features/wi-fi-transfer)
and the root guide in `sugoi-supernote` if device-level access becomes
necessary.

## The actual gap

No existing project closes the full agent↔device loop (agent pushes a
document, human annotates, agent reads the result back programmatically).
That is what `inkbridge` adds — everything else above is reused, not rebuilt.

## Licensing notes

- `inkbridge` itself is MIT.
- `supernotelib`, `sncloud`, `supernote` (allenporter) are Apache-2.0;
  `supernote-cli` is MIT. All are license-compatible to import directly as
  Python dependencies. (License-OK is not the same as worth-it: the survey
  above recommends borrowing `supernote-cli`'s transcription prompt as prior
  art rather than importing its thin OCR path — an engineering call, not a
  licensing one.)
