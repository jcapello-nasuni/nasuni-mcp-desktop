# Nasuni MCP Desktop Server Overview

This repository packages a Nasuni-aware Model Context Protocol (MCP) server that lets desktop MCP clients (Claude Desktop, Cursor, custom tooling) browse and retrieve data from a Nasuni SMB share that is already mounted on the user's machine. The project delivers the server runtime (`mcp/server.py`), extension packaging metadata (`manifest.json`, `nasuni-mcp-desktop-solution.dxt`), and supporting utilities for packaging and observability.

---

## High-Level Architecture

- **Entry point (`mcp/server.py`)** – Instantiates a `FastMCP` server named *Nasuni File Storage Server*, loads configuration, configures logging, and exposes six MCP tools (`folder_contents`, `file_metadata`, `file_contents`, `file_contents_base64`, `image_file_contents`, `file_file_contents_as_text`). Each tool delegates to a shared `FileSystem` service.
- **Configuration (`app/config.py`)** – Builds the runtime `Config` object from environment variables, optional `.env` files, and CLI arguments (currently only `--exclude_folders`). Core settings include `FILE_SYSTEM_PATH`, per-request size ceilings, logging destination & level, and ignore lists.
- **Logging setup (`app/__init__.py`)** – Configures a per-run logger named `nasuni_file_system`, wiring either a file handler or a null handler depending on configuration.
- **File system facade (`app/file_system.py`)** – Wraps Python’s `os` operations to ensure path sanitisation, enforce folder exclusions, and apply read/return size limits before accessing the underlying NAS-mounted share. It also enriches metadata using `hachoir`.
- **Domain models (`app/models.py`)** – Defines Pydantic models for folders, files, metadata, and collections returned to MCP clients. Models precompute convenience flags such as `is_supported_image` and `supports_text_extraction`.
- **Utilities (`app/utils.py`)** – Houses helpers for PDF/DOCX text extraction (via `pypdf`, `python-docx`) and thumbnail generation (`Pillow`). Also enforces payload length checks before data is returned.
- **Packaging & tooling**
  - `manifest.json` describes the MCP extension bundle, parameter prompts, and how the server is launched (using `uv run` against the `mcp` directory).
  - `build_dxt.sh` collects runtime assets into a temporary directory and invokes `@anthropic-ai/dxt pack` to create the distributable `.dxt`.
  - `scripts/process_traffic.py` is an auxiliary GitHub analytics helper unrelated to the server runtime; it pulls repository traffic metrics via the GitHub API and stores CSV snapshots.

---

## Runtime Flow

1. **Startup**
   1. `server.py` constructs a `Config` instance, which loads configuration from environment variables (`FILE_SYSTEM_PATH` is mandatory), optional `.env` files, and `--exclude_folders` CLI arguments supplied by the DXT manifest.
   2. `init_logger()` applies logging settings, defaulting to a silent configuration unless a destination file or log level is supplied.
   3. `get_file_system_client()` validates that `FILE_SYSTEM_PATH` is set and instantiates `FileSystem`.
   4. A `FastMCP` server is created and MCP tools are registered as thin wrappers around `FileSystem` methods and helper utilities.

2. **Request handling**
   - Every tool call resolves the requested path relative to the configured root. `_build_path()` in `FileSystem` canonicalises and normalises the path, preventing traversal outside the share by comparing `os.path.commonpath`.
   - If the path or any parent folder is listed in `config.exclude_folders`, `_require_path_is_in_excluded_folder()` rejects the request.
   - Size checks are applied according to each tool’s intent:
     - `SizeLimitKind.RETURN` guards direct downloads (`file_contents`, `file_contents_base64`).
     - `SizeLimitKind.READ` permits fetching larger source files when additional processing (e.g., thumbnailing) occurs before returning a smaller payload.
   - `folder_contents()` enumerates directories via `os.scandir`, short-circuiting once `max_scan_items` is reached. Returned metadata flags files that exceed the configured return size.
   - `file_metadata()` feeds the absolute path to `hachoir` for rich metadata extraction and wraps the results in the `FileMetadata` model.
   - `file_file_contents_as_text()` hydrates binary documents into text using the appropriate extractor, then validates that the final text payload respects `max_return_file_size`.
   - `image_file_contents()` optionally resizes images and always returns a `FastMCP.Image` object with the correct format.

3. **Error handling**
   - Calls raise `ValueError` when limits are exceeded, directories are supplied to file-only endpoints, or unsupported file types (e.g., non-PNG/JPEG images) are requested.
   - Missing or invalid configuration surfaces during startup via `ValueError` (e.g., unset `FILE_SYSTEM_PATH`).

---

## Configuration Surface

Configuration is primarily driven through environment variables (mapped from `manifest.json` user prompts):

| Setting | Purpose | Notes |
| --- | --- | --- |
| `FILE_SYSTEM_PATH` | Absolute root of the mounted Nasuni share | Required |
| `MAX_SCAN_ITEMS` | Maximum entries returned by `folder_contents` | Default: 1000 (manifest) / 10000 (code fallback) |
| `MAX_RETURN_FILE_SIZE` | Largest payload (bytes) the server will send to the client | Default: 1 MiB |
| `MAX_READ_FILE_SIZE` | Largest source file (bytes) the server will read | Default: 20 MiB |
| `LOG_DESTINATION` | File path for logs | Empty string disables logging |
| `LOG_LEVEL` | Optional override for logging level | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `EXCLUDE_FOLDERS` | Comma-separated list or CLI-provided array of absolute paths beneath the root to block | Provided as repeated `--exclude_folders` in manifest |
| `SNAPSHOT_FOLDER_NAME` | Name of the hidden directory that exposes snapshots | Default: `.snapshot`; blank disables snapshot tooling |
| `INCLUDE_SNAPSHOT_ROOT` | Whether `.snapshot` should appear in normal `folder_contents` responses | Default: `false` |

Because MCP tools communicate via relative paths (using `/` delimiters), all file-system access is sandboxed to the configured root. Any attempt to traverse outside is rejected pre-emptively.

---

## MCP Tools Exposed

All tools operate on relative paths from `FILE_SYSTEM_PATH`:

- `folder_contents(path: str = "", snapshot_id: str | None = None) -> FolderContents` – Lists subfolders and files, flagging oversized items via the `is_too_large` field. Optional `snapshot_id` reads from a historical snapshot.
- `file_metadata(path: str, snapshot_id: str | None = None) -> FileMetadata` – Returns `FileItem` context plus extracted metadata (dimensions, encoding, etc.) sourced from `hachoir`, optionally from a snapshot version.
- `file_contents(path: str, snapshot_id: str | None = None) -> str` – Streams text-friendly files as UTF-8 (with replacement for invalid characters). Works against snapshots when `snapshot_id` is provided.
- `file_contents_base64(path: str, snapshot_id: str | None = None) -> str` – Returns raw bytes encoded in Base64, useful for binary artefacts pulled from live data or snapshots.
- `image_file_contents(path: str, thumb_width: int = 0, snapshot_id: str | None = None) -> Image` – Serves PNG/JPEG images, optionally resized, while honouring both read and return caps and supporting snapshots.
- `file_file_contents_as_text(path: str, snapshot_id: str | None = None) -> str` – Extracts text from PDFs/DOCX; for other formats, behaves like `file_contents`. Works with snapshot payloads.
- `list_snapshots(path: str = "") -> SnapshotList` – Returns available snapshot directories (e.g., `.snapshot/2025_11_7_19.44GMT`) and flags whether the target path exists in each.

Each tool relies on Pydantic models for validation/serialization, making responses predictable for MCP clients.

---

## Packaging & Distribution

- `manifest.json` configures the MCP extension bundle. It instructs clients to launch the server via `uv run --directory ${__dirname} server.py`, injecting user-specified configuration values as environment variables and `--exclude_folders` arguments.
- `build_dxt.sh` assembles the `mcp` directory, `manifest.json`, `icon.png`, and `.dxtignore` into a temporary directory, runs `@anthropic-ai/dxt pack`, and outputs `nasuni-mcp-server.dxt`. The repository includes a prebuilt `nasuni-mcp-desktop-solution.dxt`.
- `pyproject.toml` pins runtime dependencies (`mcp`, `pypdf`, `python-docx`, `pillow`, `hachoir`) and requires Python 3.11+.

---

## Security, Limits, and Observability

- **Sandboxing** – `_build_path()` enforces that all resolved paths remain inside the configured root using `os.path.commonpath`.
- **Size constraints** – Distinct limits for “read” and “return” contexts mitigate excessive memory usage while allowing post-processing (e.g., thumbnails) when safe.
- **Exclusion lists** – `exclude_folders` supports hiding sensitive directories; enforcement happens before any disk access.
- **Logging** – Disabled by default to avoid unintended disk writes; enabling requires specifying `LOG_DESTINATION` and optionally `LOG_LEVEL`.
- **Error surfacing** – The server raises explicit `ValueError`s that MCP clients can surface back to users for actionable feedback.

---

## Snapshot-Based Version Navigation

The runtime now supports environments where Nasuni exposes historical versions via a hidden `.snapshot` directory:

- `FileSystem` can resolve paths within snapshot directories while reusing existing sandboxing and exclusion logic.
- New Pydantic models (`SnapshotSummary`, `SnapshotList`) describe snapshot availability and whether a given path exists in each snapshot.
- MCP tools accept an optional `snapshot_id` argument to read historical data, and a new `list_snapshots` tool enumerates available snapshots for any path.

These primitives offer immediate snapshot navigation for desktop mounts. They can also serve as the foundation for a future API-driven implementation that surfaces richer version metadata directly from the Nasuni control plane.

---

## Ancillary Assets

- `README.md` – Provides user-facing setup instructions (macOS Homebrew + UV installation, MCP client configuration samples, and tool descriptions).
- `LICENSE` – Captures repository licensing terms.
- `scripts/process_traffic.py` – Optional analytics helper for gathering GitHub traffic metrics into CSVs (requires `REPO` and `GH_TOKEN` environment variables).

---

With this architecture map, you have a reference for how the current MCP server interfaces with local Nasuni SMB mounts and where to integrate a version-aware experience in subsequent iterations.

