# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Project scaffolding: uv, Python 3.12, src layout, Makefile, pre-commit, GitHub Actions CI
  (lint, types, architecture, tests, dependency audit, secret scan).
- Domain models `Article`, `Chunk` and `Hit`, with invariants and the `MasdarError` hierarchy.
- `ArabicNormalizer`: configurable, idempotent Arabic normalization for retrieval.
- ADRs 0001–0004, plus the architecture, research, learning and interview docs.
