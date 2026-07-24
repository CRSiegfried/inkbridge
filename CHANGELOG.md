# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-23

Initial public release.

- Markdown-to-tickable-PDF compose: render a Markdown document (checkboxes,
  choice rows, capture fields, ...) to a row-grid PDF plus an input-area
  manifest.
- Private-cloud dispatch/collect round trip: push a composed document to a
  Supernote Manta, poll for a hand-inked response, and pull it back.
- Mark readback and semantic answer resolution against the compose
  manifest, down to per-cell blank/ANSWERED/AMBIGUOUS decisions and
  question-level results.
- Composite ink overlay: reconstruct the combined page (decoded ink over
  the rendered base page) into a single image for VLM consumption.
- PDF merge/chaining, standalone of the device round trip.
- An MCP server exposing the core round-trip as tools for LLM agents.
- An agent-facing `--json` output contract and exit-code taxonomy across
  every command, so agents can branch on outcomes without parsing prose.

[0.1.0]: https://github.com/CRSiegfried/inkbridge/releases/tag/v0.1.0
