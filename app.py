#!/usr/bin/env python3
"""
InvokeAI Model Cleanup - Streamlit UI
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional, Dict, List
import streamlit as st
import yaml


def load_config() -> Dict:
    """Load configuration from config.yaml"""
    config_file = Path(__file__).parent / "config.yaml"
    if not config_file.exists():
        st.error(f"Configuration file not found: {config_file}")
        st.stop()

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    return config


def get_database_path(config: Dict) -> Path:
    """Get the path to the invokeai.db file"""
    data_path = Path(config.get('invokeai_data_path', ''))

    if not data_path.exists():
        st.error(f"InvokeAI data path does not exist: {data_path}")
        st.stop()

    db_path = data_path / "databases" / "invokeai.db"

    if not db_path.exists():
        st.error(f"Database file not found: {db_path}")
        st.stop()

    return db_path


def format_size(size_bytes: int) -> str:
    """Format size in bytes to M or G format"""
    if size_bytes == 0:
        return "0M"

    # Convert to megabytes
    size_mb = size_bytes / (1024 * 1024)

    # If less than 1024 MB, show in MB
    if size_mb < 1024:
        return f"{int(size_mb)}M"
    else:
        # Convert to gigabytes
        size_gb = size_mb / 1024
        return f"{int(size_gb)}G"


def is_git_lfs_pointer(file_path: Path) -> bool:
    """Check if a file is a git-lfs pointer file"""
    if not file_path.exists() or not file_path.is_file():
        return False

    # Git-LFS pointer files are always small (< 1KB)
    if file_path.stat().st_size >= 1024:
        return False

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline()
            return "version https://git-lfs.github.com" in first_line
    except:
        return False


def get_file_size(file_path: Path) -> int:
    """Get file size in bytes, returns 0 if file doesn't exist"""
    if not file_path.exists():
        return 0

    try:
        return file_path.stat().st_size
    except:
        return 0


def extract_hash_from_path(path: str) -> str:
    """Extract hash/UUID from model path"""
    # InvokeAI stores models in two formats:
    # 1. File path: uuid/model.safetensors (ControlNets, LoRAs)
    # 2. Folder path: uuid (diffusers-format main models)
    import re

    path_obj = Path(path)

    # Check if path looks like a file (has extension) or folder
    if path_obj.suffix:
        # File path - UUID is the parent directory
        hash_value = path_obj.parent.name
    else:
        # Folder path - UUID is the path itself (last component)
        hash_value = path_obj.name

    # Validate UUID format: 8-4-4-4-12 hexadecimal pattern
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if re.match(uuid_pattern, hash_value, re.IGNORECASE):
        return hash_value

    return "N/A"


def scan_models_folder(models_path: Path) -> Dict[str, Path]:
    """Scan the models folder and return a dict of {uuid: file_path}"""
    models_on_disk = {}

    # Valid model file extensions
    MODEL_EXTENSIONS = {'.safetensors', '.pth', '.pt', '.gguf'}

    if not models_path.exists():
        return models_on_disk

    # Each model is in a UUID-named folder
    for uuid_folder in models_path.iterdir():
        if uuid_folder.is_dir():
            # Find model files in this folder (only valid extensions)
            for model_file in uuid_folder.iterdir():
                if model_file.is_file() and model_file.suffix.lower() in MODEL_EXTENSIONS:
                    # Store the UUID and the file path
                    models_on_disk[uuid_folder.name] = model_file
                    break  # Only take the first model file per folder

    return models_on_disk


def get_models_from_db(db_path: Path, models_path: Path) -> List[Dict]:
    """Retrieve all models from the database and cross-reference with filesystem"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Query all models with hash for duplicate detection
    cursor.execute("SELECT id, type, path, name, hash FROM models")
    rows = cursor.fetchall()

    # Scan the models folder
    models_on_disk = scan_models_folder(models_path)

    # Build hash map for duplicate detection
    hash_counts = {}
    for row in rows:
        model_hash = row[4] if len(row) > 4 else None
        if model_hash:
            hash_counts[model_hash] = hash_counts.get(model_hash, 0) + 1

    models = []
    for row in rows:
        model_id, model_type, model_path, model_name, model_hash = row

        # Handle both absolute and relative paths
        path_obj = Path(model_path)
        if not path_obj.is_absolute():
            # Relative path - prepend models folder
            path_obj = models_path / model_path

        # Get file size
        file_size = get_file_size(path_obj)

        # Check if it's a symbolic link
        is_symlink = path_obj.is_symlink() if path_obj.exists() else False

        # Check if model exists (in-place)
        # Could be a file (ControlNet, LoRA) or folder (diffusers main model)
        in_place = path_obj.exists() and (path_obj.is_file() or path_obj.is_dir())

        # Check if it's a git-lfs pointer
        is_lfs_pointer = is_git_lfs_pointer(path_obj)

        # Extract hash (UUID) from path
        hash_value = extract_hash_from_path(model_path)

        # Check if this is a duplicate (same content hash as another model)
        is_duplicate = model_hash and hash_counts.get(model_hash, 0) > 1

        models.append({
            'id': model_id,
            'name': model_name,
            'type': model_type,
            'path': model_path,
            'size': file_size,
            'size_formatted': format_size(file_size),
            'hash': hash_value,
            'content_hash': model_hash,  # BLAKE3 hash for duplicate detection
            'in_place': in_place,
            'symlink': is_symlink,
            'git_lfs': is_lfs_pointer,
            'in_db': True,
            'on_disk': hash_value in models_on_disk,
            'is_duplicate': is_duplicate
        })

        # Remove from disk dict so we can find orphans later
        if hash_value in models_on_disk:
            models_on_disk.pop(hash_value)

    conn.close()

    # Add orphaned files (on disk but not in DB)
    for uuid, file_path in models_on_disk.items():
        file_size = get_file_size(file_path)
        is_symlink = file_path.is_symlink()
        is_lfs_pointer = is_git_lfs_pointer(file_path)

        models.append({
            'id': f'orphan-{uuid}',
            'name': file_path.name,
            'type': 'orphaned',
            'path': str(file_path),
            'size': file_size,
            'size_formatted': format_size(file_size),
            'hash': uuid,
            'content_hash': None,
            'in_place': True,
            'symlink': is_symlink,
            'git_lfs': is_lfs_pointer,
            'in_db': False,
            'on_disk': True,
            'is_duplicate': False
        })

    return models


def perform_inplace_import(models_to_import: List[Dict], db_path: Path, data_path: Path):
    """Prepare models for in-place import by creating symlinks and removing DB entries"""
    from datetime import datetime

    inplace_folder = data_path / "in-place"
    inplace_folder.mkdir(exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    imported_count = 0
    errors = []

    for model in models_to_import:
        try:
            # Get the real path (resolve symlinks)
            model_path = Path(model['path'])

            # Check if path exists
            if not model_path.exists():
                errors.append(f"{model['name']}: Path does not exist")
                continue

            if model_path.is_symlink():
                real_path = model_path.resolve()
            else:
                real_path = model_path

            # Use model name for symlink, handle duplicates by adding counter
            base_name = model['name']
            symlink_path = inplace_folder / base_name
            counter = 1
            while symlink_path.exists():
                name_parts = base_name.rsplit('.', 1)
                if len(name_parts) == 2:
                    symlink_path = inplace_folder / f"{name_parts[0]}_{counter}.{name_parts[1]}"
                else:
                    symlink_path = inplace_folder / f"{base_name}_{counter}"
                counter += 1

            # Create symlink (adds to existing in-place folder)
            symlink_path.symlink_to(real_path)

            # Only delete from database after successful symlink creation
            if not model['id'].startswith('orphan-'):
                cursor.execute("DELETE FROM models WHERE id = ?", (model['id'],))

            imported_count += 1

        except Exception as e:
            errors.append(f"{model['name']}: {str(e)}")

    conn.commit()
    conn.close()

    return imported_count, errors


def perform_duplicate_removal(duplicate_models: List[Dict], db_path: Path, data_path: Path):
    """Remove duplicate models, keeping one based on priority rules"""
    import shutil
    from datetime import datetime
    from collections import defaultdict

    review_folder = data_path / "review"
    review_folder.mkdir(exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Group duplicates by BLAKE3 hash
    groups = defaultdict(list)
    for model in duplicate_models:
        if model['content_hash']:
            groups[model['content_hash']].append(model)

    removed_count = 0
    kept_count = 0
    errors = []

    for content_hash, models_in_group in groups.items():
        try:
            # Priority rules:
            # 1. Keep non-in-place files (UUID-based models)
            # 2. If multiple non-in-place, keep first one
            # 3. If all in-place, keep first one

            non_inplace = [m for m in models_in_group if m['hash'] != 'N/A']
            inplace = [m for m in models_in_group if m['hash'] == 'N/A']

            if non_inplace:
                # Keep first non-in-place, remove rest
                to_keep = non_inplace[0]
                to_remove = non_inplace[1:] + inplace
            else:
                # All in-place, keep first
                to_keep = inplace[0]
                to_remove = inplace[1:]

            kept_count += 1

            # Remove duplicates
            for model in to_remove:
                model_path = Path(model['path'])

                # Determine what to move (file or folder)
                if model['hash'] != 'N/A':
                    # UUID-based model - move the UUID folder
                    folder_to_move = data_path / "models" / model['hash']
                else:
                    # In-place model - move the actual file/folder
                    folder_to_move = model_path

                # Move to review folder with timestamp
                if folder_to_move.exists():
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    dest_name = f"{folder_to_move.name}_{timestamp}"
                    dest_path = review_folder / dest_name

                    shutil.move(str(folder_to_move), str(dest_path))

                # Delete from database
                if not model['id'].startswith('orphan-'):
                    cursor.execute("DELETE FROM models WHERE id = ?", (model['id'],))

                removed_count += 1

        except Exception as e:
            errors.append(f"Hash {content_hash[:16]}...: {str(e)}")

    conn.commit()
    conn.close()

    return kept_count, removed_count, errors


def perform_deletion(models_to_delete: List[Dict], filter_type: str, db_path: Path, data_path: Path):
    """Delete models by moving files to review folder and removing DB entries"""
    import shutil
    from datetime import datetime

    review_folder = data_path / "review"
    review_folder.mkdir(exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    deleted_count = 0
    moved_count = 0
    error_count = 0

    # For duplicates, group by BLAKE3 hash and keep only the first one
    if filter_type == 'duplicates':
        # Group models by content hash
        hash_groups = {}
        for model in models_to_delete:
            content_hash = model.get('content_hash')
            if content_hash:
                if content_hash not in hash_groups:
                    hash_groups[content_hash] = []
                hash_groups[content_hash].append(model)

        # For each group, skip the first (keep it), delete the rest
        models_to_actually_delete = []
        for content_hash, group in hash_groups.items():
            if len(group) > 1:
                # Keep first, delete rest
                models_to_actually_delete.extend(group[1:])
    else:
        models_to_actually_delete = models_to_delete

    # Process deletions
    for model in models_to_actually_delete:
        try:
            model_id = model['id']
            model_path = model['path']

            # Skip orphaned models (not in DB)
            if not model['in_db']:
                # Just move the file/folder
                path_obj = Path(model_path)
                if path_obj.exists():
                    dest_name = f"{path_obj.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    dest_path = review_folder / dest_name
                    shutil.move(str(path_obj), str(dest_path))
                    moved_count += 1
                continue

            # Delete from database
            cursor.execute("DELETE FROM models WHERE id = ?", (model_id,))

            if cursor.rowcount > 0:
                deleted_count += 1

                # Move file/folder to review
                # Handle both relative and absolute paths
                path_obj = Path(model_path)
                if not path_obj.is_absolute():
                    # Relative path - prepend models folder
                    models_path = data_path / "models"
                    path_obj = models_path / model_path

                if path_obj.exists():
                    # Determine what to move (file or parent folder)
                    if path_obj.is_file():
                        # For files in UUID folders, move the entire UUID folder
                        if path_obj.parent.name != 'models':
                            item_to_move = path_obj.parent
                        else:
                            item_to_move = path_obj
                    else:
                        # Folder (diffusers format)
                        item_to_move = path_obj

                    # Create unique name with timestamp
                    dest_name = f"{item_to_move.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    dest_path = review_folder / dest_name

                    shutil.move(str(item_to_move), str(dest_path))
                    moved_count += 1

        except Exception as e:
            error_count += 1
            st.error(f"Error deleting {model.get('name', 'unknown')}: {str(e)}")

    conn.commit()
    conn.close()

    # Show results
    st.success(f"✓ Deleted {deleted_count} database entries")
    st.success(f"✓ Moved {moved_count} files/folders to review")
    if error_count > 0:
        st.warning(f"⚠ {error_count} errors occurred")


def main():
    """Main Streamlit application"""
    st.set_page_config(
        page_title="InvokeAI Model Cleanup",
        page_icon="🧹",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

    # Compact header styling
    st.markdown("""
        <style>
        /* Reduce top padding */
        .block-container {
            padding-top: 2.75rem;
            padding-bottom: 0rem;
        }
        /* Reduce space between elements */
        div[data-testid="stVerticalBlock"] > div {
            gap: 0.5rem;
        }
        </style>
    """, unsafe_allow_html=True)

    # Initialize session state for filter
    if 'filter' not in st.session_state:
        st.session_state.filter = 'total'

    # Load configuration and database
    config = load_config()
    db_path = get_database_path(config)
    data_path = Path(config.get('invokeai_data_path', ''))
    models_path = data_path / "models"

    # Load models
    models = get_models_from_db(db_path, models_path)

    # Calculate statistics
    total_models = len(models)
    missing_files = sum(1 for m in models if m['in_db'] and not m['in_place'] and not m['git_lfs'])
    orphaned_files = sum(1 for m in models if not m['in_db'])
    lfs_pointers = sum(1 for m in models if m['git_lfs'])
    duplicate_models = sum(1 for m in models if m['is_duplicate'])
    # In-place models: UUID shows "In-place" (hash == 'N/A')
    inplace_models = sum(1 for m in models if m['in_db'] and m['hash'] == 'N/A')
    ok_models = sum(1 for m in models if m['in_db'] and m['in_place'] and not m['git_lfs'] and not m['is_duplicate'])

    # Display compact summary with clickable buttons
    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

    with col1:
        if st.button(f"📊 Total\n{total_models}", use_container_width=True, type="primary" if st.session_state.filter == 'total' else "secondary"):
            st.session_state.filter = 'total'
            st.rerun()
    with col2:
        if st.button(f"✅ OK\n{ok_models}", use_container_width=True, type="primary" if st.session_state.filter == 'ok' else "secondary"):
            st.session_state.filter = 'ok'
            st.rerun()
    with col3:
        if st.button(f"❌ Missing\n{missing_files}", use_container_width=True, type="primary" if st.session_state.filter == 'missing' else "secondary"):
            st.session_state.filter = 'missing'
            st.rerun()
    with col4:
        if st.button(f"🗑️ Orphaned\n{orphaned_files}", use_container_width=True, type="primary" if st.session_state.filter == 'orphaned' else "secondary"):
            st.session_state.filter = 'orphaned'
            st.rerun()
    with col5:
        if st.button(f"⚠️ LFS\n{lfs_pointers}", use_container_width=True, type="primary" if st.session_state.filter == 'lfs' else "secondary"):
            st.session_state.filter = 'lfs'
            st.rerun()
    with col6:
        if st.button(f"🔄 Duplicates\n{duplicate_models}", use_container_width=True, type="primary" if st.session_state.filter == 'duplicates' else "secondary"):
            st.session_state.filter = 'duplicates'
            st.rerun()
    with col7:
        if st.button(f"🔗 In-place\n{inplace_models}", use_container_width=True, type="primary" if st.session_state.filter == 'inplace' else "secondary"):
            st.session_state.filter = 'inplace'
            st.rerun()

    # Filter models based on selected filter
    if st.session_state.filter == 'ok':
        filtered_models = [m for m in models if m['in_db'] and m['in_place'] and not m['git_lfs'] and not m['is_duplicate']]
    elif st.session_state.filter == 'missing':
        filtered_models = [m for m in models if m['in_db'] and not m['in_place'] and not m['git_lfs']]
    elif st.session_state.filter == 'orphaned':
        filtered_models = [m for m in models if not m['in_db']]
    elif st.session_state.filter == 'lfs':
        filtered_models = [m for m in models if m['git_lfs']]
    elif st.session_state.filter == 'duplicates':
        filtered_models = [m for m in models if m['is_duplicate']]
    elif st.session_state.filter == 'inplace':
        filtered_models = [m for m in models if m['in_db'] and m['hash'] == 'N/A']
    else:  # total
        filtered_models = models

    # Show filter info (compact)
    caption_text = f"Showing {len(filtered_models)} of {total_models} models" if st.session_state.filter != 'total' else f"Showing all {total_models} models"
    st.markdown(f"<p style='margin:0; padding:0; font-size:0.8rem; color:gray;'>{caption_text} - Click a row to copy model name</p>", unsafe_allow_html=True)

    # Display models with AgGrid for better interaction
    import pandas as pd
    from st_aggrid import AgGrid, GridOptionsBuilder
    import pyperclip

    # Prepare data for table
    table_data = []
    for model in filtered_models:
        # Format status indicators
        name = model['name']
        if not model['in_db']:
            name = f"🗑️ {name}"
        elif model['is_duplicate']:
            name = f"🔄 {name}"

        # UUID (folder hash) - full value or "In-place" for external models
        uuid_display = model['hash'] if model['hash'] != 'N/A' else 'In-place'

        # BLAKE3 content hash - remove 'blake3:' prefix, show full hash
        content_hash = model.get('content_hash', '')
        if content_hash and content_hash.startswith('blake3:'):
            blake3_display = content_hash[7:]  # Remove 'blake3:' prefix
        else:
            blake3_display = "N/A"

        table_data.append({
            'Model': name,
            'Size': model['size_formatted'],
            'UUID': uuid_display,
            'BLAKE3': blake3_display,
            '_model_name': model['name'],  # Hidden column for copying
            '_size_bytes': model['size']  # Hidden column for proper sorting
        })

    df = pd.DataFrame(table_data)

    # Sort by size (largest first) for initial display, if dataframe is not empty
    if len(df) > 0:
        df = df.sort_values('_size_bytes', ascending=False)

    # Configure AgGrid
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_selection(selection_mode='single', use_checkbox=False)
    gb.configure_grid_options(domLayout='normal', rowHeight=35)
    gb.configure_column('_model_name', hide=True)  # Hide the copy helper column
    gb.configure_column('_size_bytes', hide=True)  # Hide the numeric size column

    # Configure columns
    gb.configure_column('Model', sortable=True, minWidth=200)
    gb.configure_column('Size', sortable=True, width=100)
    gb.configure_column('UUID', sortable=True, width=200)
    gb.configure_column('BLAKE3', sortable=True, width=200)

    gridOptions = gb.build()

    # Display grid
    grid_response = AgGrid(
        df,
        gridOptions=gridOptions,
        update_on=['selectionChanged'],
        height=650,
        theme='streamlit',
        enable_enterprise_modules=False,
        allow_unsafe_jscode=False
    )

    # Handle row selection and copy to clipboard
    if grid_response['selected_rows'] is not None:
        selected_df = pd.DataFrame(grid_response['selected_rows'])
        if len(selected_df) > 0:
            model_name = selected_df.iloc[0]['_model_name']
            try:
                pyperclip.copy(model_name)
                st.toast("✓ Copied", icon="✅")
            except Exception as e:
                st.toast(f"Copied: {model_name}", icon="✅")

    # Footer with Actions dropdown and GO button (compact)
    # Initialize action state
    if 'selected_action' not in st.session_state:
        st.session_state.selected_action = None

    # Confirmation dialog
    if st.session_state.get('show_action_confirm', False):
        action_type = st.session_state.selected_action

        if action_type == 'delete':
            st.warning(f"⚠️ You are about to delete {len(filtered_models)} models from the {st.session_state.filter} category.")
            st.info("Files will be moved to /mnt/llm/hub/invokeai_data/review for later review.")
        elif action_type == 'inplace':
            st.warning(f"⚠️ You are about to prepare {len(filtered_models)} models for in-place import.")
            st.info("Symlinks will be created in /mnt/llm/hub/invokeai_data/in-place and DB entries will be removed. Then use InvokeAI's scan folder feature on the in-place folder.")
        elif action_type == 'remove_duplicates':
            st.warning(f"⚠️ You are about to remove duplicate models.")
            st.info("For each duplicate set: keeps non-in-place models (if any), otherwise keeps first one. Others moved to review folder.")

        col1, col2, col3 = st.columns([1, 1, 3])
        with col1:
            if st.button("✓ Confirm", type="primary"):
                # Perform action
                if action_type == 'delete':
                    perform_deletion(filtered_models, st.session_state.filter, db_path, data_path)
                    st.success(f"Deleted {len(filtered_models)} models")
                elif action_type == 'inplace':
                    imported_count, errors = perform_inplace_import(filtered_models, db_path, data_path)
                    if errors:
                        st.error(f"Imported {imported_count} models with {len(errors)} errors")
                        for err in errors[:5]:  # Show first 5 errors
                            st.text(err)
                    else:
                        st.success(f"Prepared {imported_count} models for import in /mnt/llm/hub/invokeai_data/in-place")
                elif action_type == 'remove_duplicates':
                    kept_count, removed_count, errors = perform_duplicate_removal(filtered_models, db_path, data_path)
                    if errors:
                        st.error(f"Kept {kept_count} unique models, removed {removed_count} duplicates with {len(errors)} errors")
                        for err in errors[:5]:  # Show first 5 errors
                            st.text(err)
                    else:
                        st.success(f"Kept {kept_count} unique models, removed {removed_count} duplicates")

                st.session_state.show_action_confirm = False
                st.session_state.selected_action = None
                st.rerun()
        with col2:
            if st.button("✗ Cancel", type="secondary"):
                st.session_state.show_action_confirm = False
                st.session_state.selected_action = None
                st.rerun()
    else:
        # Actions dropdown + GO button
        col1, col2, col3 = st.columns([2, 1, 4])

        # Determine available actions based on filter
        has_models = len(filtered_models) > 0
        is_total = st.session_state.filter == 'total'
        is_ok = st.session_state.filter == 'ok'

        with col1:
            if is_total or is_ok or not has_models:
                # Total and OK filters: No actions available
                actions = ["No actions available"]
                action = st.selectbox("Actions", actions, label_visibility="collapsed", disabled=True)
            else:
                # Build actions list based on filter
                if st.session_state.filter == 'duplicates':
                    # Duplicates: Remove duplicates only
                    actions = [f"Remove duplicates"]
                elif st.session_state.filter == 'inplace':
                    # In-place: In-place import OR Delete
                    actions = [f"In-place import ({len(filtered_models)} models)", f"Delete ({len(filtered_models)} models)"]
                else:
                    # Missing, Orphaned, LFS: In-place import OR Delete
                    actions = [f"In-place import ({len(filtered_models)} models)", f"Delete ({len(filtered_models)} models)"]

                action = st.selectbox("Actions", actions, label_visibility="collapsed")

        with col2:
            go_disabled = is_total or is_ok or not has_models
            if st.button("GO", type="primary", disabled=go_disabled, use_container_width=True):
                # Determine which action was selected
                if "In-place import" in action:
                    st.session_state.selected_action = 'inplace'
                elif "Delete" in action:
                    st.session_state.selected_action = 'delete'
                elif "Remove duplicates" in action:
                    st.session_state.selected_action = 'remove_duplicates'
                st.session_state.show_action_confirm = True
                st.rerun()

        with col3:
            if not is_total and not is_ok and has_models:
                if st.session_state.filter == 'duplicates':
                    st.caption("Intelligently remove duplicate models")
                elif st.session_state.filter == 'inplace':
                    st.caption("In-place import or delete in-place models")
                else:
                    st.caption("In-place import or delete models")
            elif not has_models and not is_total and not is_ok:
                st.caption(f"No {st.session_state.filter} models found")
            else:
                st.caption("Select a filter to see available actions")


if __name__ == "__main__":
    main()
