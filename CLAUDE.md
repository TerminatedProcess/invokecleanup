# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

InvokeAI Model Cleanup is a Streamlit web application for managing and cleaning up InvokeAI's models database. It provides a visual interface to identify problematic models (missing files, orphaned entries, git-lfs pointers, duplicates) and perform bulk operations like deletion or in-place import preparation.

**Target Platform**: Garuda Linux (Arch-based) with Python 3.12

## Quick Start

```fish
source .envrc        # Activate virtual environment
run                  # Start Streamlit app (localhost:8501)
stop                 # Stop Streamlit app
```

## Configuration

**config.yaml** - Single configuration file:
```yaml
invokeai_data_path: /mnt/llm/hub/invokeai_data
```

The app expects this directory structure under `invokeai_data_path`:
- `databases/invokeai.db` - SQLite database
- `models/` - Model files organized by UUID folders
- `review/` - Created by app for deleted models (safe review before permanent deletion)
- `in-place/` - Created by app for in-place import symlinks

## Development Environment

### Virtual Environment

- **Activate**: `source .envrc`
- **Create new**: `mkenv` (uses uv with Python 3.12.10)
- **Remove**: `rmenv`
- **Install deps**: `install`

### Aliases (from .salias)

| Alias | Command | Purpose |
|-------|---------|---------|
| `run` | `streamlit run app.py` | Start the web UI |
| `stop` | `pkill -f streamlit` | Stop the web UI |
| `mkenv` | `mkuv $ENV_NAME 3.12.10` | Create virtual environment |
| `rmenv` | `rm -rf .envrc $ENV_NAME uv.lock` | Remove environment |
| `install` | `uv pip install -r requirements.txt` | Install dependencies |

## Dependencies

From requirements.txt:
- `streamlit` - Web UI framework
- `pyyaml` - Configuration parsing
- `streamlit-aggrid` - Interactive data grid
- `pyperclip` - Clipboard support

Also uses (from standard library or transitive):
- `sqlite3` - Database access
- `pandas` - Data manipulation (via streamlit-aggrid)

## Architecture

### app.py Structure

| Lines | Function | Purpose |
|-------|----------|---------|
| 14-24 | `load_config()` | Load and validate config.yaml |
| 27-41 | `get_database_path()` | Resolve database path from config |
| 44-58 | `format_size()` | Format bytes to M/G display |
| 61-75 | `is_git_lfs_pointer()` | Detect incomplete LFS downloads |
| 78-86 | `get_file_size()` | Safe file size getter |
| 89-111 | `extract_hash_from_path()` | Extract UUID from model path |
| 114-134 | `scan_models_folder()` | Scan filesystem for model files |
| 137-232 | `get_models_from_db()` | Load models with filesystem cross-reference |
| 235-290 | `perform_inplace_import()` | Create symlinks for re-import |
| 293-359 | `perform_duplicate_removal()` | Remove duplicate models (keep oldest) |
| 362-458 | `perform_deletion()` | Delete models and move files to review |
| 461-744 | `main()` | Streamlit UI and interaction logic |

### Model Categories

| Category | Description | Action Available |
|----------|-------------|------------------|
| **Total** | All models in database | View only |
| **OK** | Valid models with files present | View only |
| **Missing** | DB entry exists but file missing | Delete, In-place import |
| **Orphaned** | File exists but no DB entry | Delete, In-place import |
| **LFS** | Git-LFS pointer files (incomplete downloads) | Delete, In-place import |
| **Duplicates** | Same BLAKE3 hash as another model | Remove duplicates |
| **In-place** | Models imported via in-place (no UUID folder) | Delete, In-place import |

### Data Flow

1. **Startup**: Load config.yaml, connect to invokeai.db
2. **Scan**: Query all models from DB, scan models/ folder for orphans
3. **Cross-reference**: Match DB entries to filesystem, detect issues
4. **Display**: Show categorized models in AgGrid with clickable filters
5. **Action**: User selects category and action, app modifies DB and moves files

### Key Implementation Details

- **UUID detection**: Models stored in `models/{uuid}/model.safetensors` format
- **In-place detection**: Models with `hash == 'N/A'` are in-place imports (external files)
- **Duplicate detection**: Uses BLAKE3 content hash from DB (not UUID)
- **Safe deletion**: Files moved to `review/` folder, not permanently deleted
- **Clipboard**: Click row to copy model name (uses pyperclip)

## File Structure

```
invokecleanup/
├── app.py                        # Main Streamlit application
├── config.yaml                   # InvokeAI data path configuration
├── requirements.txt              # Python dependencies
├── CLAUDE.md                     # This file
├── .salias                       # Shell aliases (run, stop, etc.)
├── .envrc                        # Virtual environment activation
├── .venv/                        # Python virtual environment
└── invokecleanup.fish-old-ignore # Deprecated CLI version (ignore)
```

## Common Modifications

### Adding a New Model Category

1. Add count calculation in `main()` around line 498-506
2. Add filter button in the columns section (lines 509-538)
3. Add filter logic in the filtering section (lines 541-554)
4. Add action handling if needed (lines 693-740)

### Changing Deletion Behavior

Modify `perform_deletion()` (lines 362-458):
- Change destination folder: modify `review_folder` variable
- Skip file moving: remove the shutil.move calls
- Add logging: insert logging calls in the try block

### Adding New Model Metadata

1. Add column to SQL query in `get_models_from_db()` (line 143)
2. Add to model dict (lines 185-201)
3. Add column to table_data in `main()` (lines 566-592)
4. Configure column in GridOptionsBuilder (lines 608-611)
