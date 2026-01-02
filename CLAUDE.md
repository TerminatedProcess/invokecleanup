# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains `invokecleanup.fish`, a Fish shell function for cleaning up InvokeAI's models database. It identifies and removes invalid model entries based on multiple criteria (missing files, broken symlinks, unknown types, empty folders, git-lfs pointer files) and optionally moves the associated model folders to a `deleted-models` directory.

**Target Platform**: Garuda Linux (Arch-based) with Fish shell

## Development Environment

### Virtual Environment

The project uses `uv` for Python virtual environment management, though the main script is pure Fish shell.

- **Activate environment**: `source .envrc` (automatically activates `.venv`)
- **Environment setup**: Handled by `.envrc` and `.salias`
- **Python version**: 3.12.10

### Environment Management Aliases

From `.salias`:
- `rmenv` - Remove virtual environment and related files
- `mkenv` - Create new uv environment with Python 3.12.10
- `install` - Install/upgrade pip in the environment

## Testing the Function

### Prerequisites

You need an InvokeAI installation with:
- `invokeai.db` SQLite database in the working directory
- Model files referenced in the database

### Running the Function

1. **Load the function into your Fish shell**:
   ```fish
   source invokecleanup.fish
   ```

2. **Run with different modes**:
   ```fish
   # Scan all models for issues
   invokecleanup

   # Find only models with type 'unknown'
   invokecleanup --unknowns

   # Filter models by name (case-insensitive)
   invokecleanup "sdxl"
   ```

3. **Interactive confirmation**: The function will show a summary and ask for confirmation before making any deletions

### Test Database Setup

To test without a real InvokeAI installation, you can create a minimal test database:

```fish
# Create a test database
sqlite3 invokeai.db "CREATE TABLE models (id TEXT PRIMARY KEY, type TEXT, path TEXT, name TEXT)"

# Add some test entries
sqlite3 invokeai.db "INSERT INTO models VALUES ('test-1', 'unknown', '/nonexistent/path', 'Test Model 1')"
sqlite3 invokeai.db "INSERT INTO models VALUES ('test-2', 'lora', '/another/missing', 'Test Model 2')"
```

## Code Architecture

### Main Flow

1. **Argument parsing** (lines 6-14): Determines operation mode (`--unknowns` flag or filter string)
2. **Database validation** (lines 20-24): Checks for `invokeai.db` in current directory
3. **Model scanning** (lines 38-150): Two paths:
   - Fast path for `--unknowns`: Direct SQL query for type='unknown'
   - Full scan: Iterates through all models (or filtered subset) with multiple checks
4. **Git-LFS detection** (lines 87-100): Identifies incomplete downloads (pointer files < 1KB)
5. **Validation checks** (lines 102-141): Progressive checks for invalidity
6. **Interactive summary** (lines 191-231): Groups by reason, shows examples, requests confirmation
7. **Deletion execution** (lines 234-277): Removes DB records and moves folders to `deleted-models/`

### Validation Checks (in order)

1. **Git-LFS pointer detection**: Files < 1KB starting with "version https://git-lfs.github.com" (informational, not deleted)
2. **Name filter match**: If filter string provided, matches against model name
3. **Unknown type**: Model type is 'unknown'
4. **Path existence**: Model path doesn't exist
5. **Broken symlink**: Symlink target doesn't exist
6. **Empty parent folder**: Model's parent directory is empty

### Key Implementation Details

- **Database**: Uses `sqlite3` CLI for all database operations (SELECT, DELETE)
- **Temporary files**: Creates three temp files for tracking:
  - `$temp_to_delete`: Models marked for deletion
  - `$temp_summary`: Reasons for deletion (for counting)
  - `$temp_lfs_pointers`: Git-LFS pointer files (informational only)
- **Progress indicators**: Shows progress every 50 models during full scans
- **Folder management**: Uses `dirname` and `basename` to extract folder paths, moves entire model folders (not individual files)
- **Timestamp handling**: Adds timestamp to destination folder if it already exists

## Dependencies

- **Fish shell**: Required (v3.0+)
- **sqlite3**: For database queries
- **Standard Unix tools**: `stat`, `head`, `cut`, `grep`, `wc`, `sort`, `uniq`, `dirname`, `basename`, `mktemp`, `date`, `mv`
- **Fish built-ins**: `string`, `math`, `set_color`, `read`

## Common Modifications

### Adding New Validation Checks

Add new checks in the validation section (lines 115-141) following this pattern:

```fish
if test -z "$reason"
    # Your check condition here
    if test <condition>
        set reason "Your reason description"
    end
end
```

### Changing Database Schema

If InvokeAI changes its schema, update the SQL queries:
- Line 41-42: SELECT query for --unknowns mode
- Line 62: SELECT query for filtered models
- Line 65: SELECT query for all models
- Line 246: DELETE query

### Modifying Deletion Behavior

The deletion logic (lines 234-277) can be modified to:
- Skip folder moving: Comment out lines 252-275
- Change destination: Modify `$DELETED_DIR` variable (line 18)
- Add database backup: Add backup step before deletions

## Installation for System-Wide Use

To make this function available system-wide:

1. Copy to Fish functions directory:
   ```fish
   cp invokecleanup.fish ~/.config/fish/functions/
   ```

2. Or source it in your `config.fish`:
   ```fish
   echo "source /home/dev/work/media/invokecleanup/invokecleanup.fish" >> ~/.config/fish/config.fish
   ```

3. Reload Fish configuration:
   ```fish
   source ~/.config/fish/config.fish
   ```
