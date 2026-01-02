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
    # InvokeAI stores models in folders named by their UUID
    # Example: /path/to/models/e3e73746-d2b6-4a26-b775-aeb4e945d0a3/model.safetensors
    # The UUID is the parent directory name
    path_obj = Path(path)

    # Get parent directory name (should be the UUID)
    hash_value = path_obj.parent.name

    # If it looks like a UUID or hash (allows alphanumeric and hyphens)
    if len(hash_value) > 8 and all(c.isalnum() or c == '-' for c in hash_value):
        return hash_value

    return "N/A"


def scan_models_folder(models_path: Path) -> Dict[str, Path]:
    """Scan the models folder and return a dict of {uuid: file_path}"""
    models_on_disk = {}

    if not models_path.exists():
        return models_on_disk

    # Each model is in a UUID-named folder
    for uuid_folder in models_path.iterdir():
        if uuid_folder.is_dir():
            # Find model files in this folder (safetensors, ckpt, etc.)
            for model_file in uuid_folder.iterdir():
                if model_file.is_file():
                    # Store the UUID and the file path
                    models_on_disk[uuid_folder.name] = model_file
                    break  # Only take the first file per folder

    return models_on_disk


def get_models_from_db(db_path: Path, models_path: Path) -> List[Dict]:
    """Retrieve all models from the database and cross-reference with filesystem"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Query all models
    cursor.execute("SELECT id, type, path, name FROM models")
    rows = cursor.fetchall()

    # Scan the models folder
    models_on_disk = scan_models_folder(models_path)

    models = []
    for row in rows:
        model_id, model_type, model_path, model_name = row

        path_obj = Path(model_path)

        # Get file size
        file_size = get_file_size(path_obj)

        # Check if it's a symbolic link
        is_symlink = path_obj.is_symlink() if path_obj.exists() else False

        # Check if file exists (in-place)
        in_place = path_obj.exists() and path_obj.is_file()

        # Check if it's a git-lfs pointer
        is_lfs_pointer = is_git_lfs_pointer(path_obj)

        # Extract hash (UUID) from path
        hash_value = extract_hash_from_path(model_path)

        models.append({
            'id': model_id,
            'name': model_name,
            'type': model_type,
            'path': model_path,
            'size': file_size,
            'size_formatted': format_size(file_size),
            'hash': hash_value,
            'in_place': in_place,
            'symlink': is_symlink,
            'git_lfs': is_lfs_pointer,
            'in_db': True,
            'on_disk': hash_value in models_on_disk
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
            'in_place': True,
            'symlink': is_symlink,
            'git_lfs': is_lfs_pointer,
            'in_db': False,
            'on_disk': True
        })

    return models


def main():
    """Main Streamlit application"""
    st.set_page_config(
        page_title="InvokeAI Model Cleanup",
        page_icon="🧹",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

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
    missing_files = sum(1 for m in models if m['in_db'] and not m['on_disk'])
    orphaned_files = sum(1 for m in models if not m['in_db'])
    lfs_pointers = sum(1 for m in models if m['git_lfs'])
    ok_models = sum(1 for m in models if m['in_db'] and m['on_disk'] and not m['git_lfs'])

    # Display compact summary with clickable buttons
    col1, col2, col3, col4, col5 = st.columns(5)

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

    # Filter models based on selected filter
    if st.session_state.filter == 'ok':
        filtered_models = [m for m in models if m['in_db'] and m['on_disk'] and not m['git_lfs']]
    elif st.session_state.filter == 'missing':
        filtered_models = [m for m in models if m['in_db'] and not m['on_disk']]
    elif st.session_state.filter == 'orphaned':
        filtered_models = [m for m in models if not m['in_db']]
    elif st.session_state.filter == 'lfs':
        filtered_models = [m for m in models if m['git_lfs']]
    else:  # total
        filtered_models = models

    # Show filter info
    if st.session_state.filter != 'total':
        st.caption(f"Showing {len(filtered_models)} of {total_models} models - Click a row to copy model name")
    else:
        st.caption(f"Showing all {total_models} models - Click a row to copy model name")

    # Display models with AgGrid for better interaction
    import pandas as pd
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
    import pyperclip

    # Prepare data for table
    table_data = []
    for model in filtered_models:
        # Format status indicators
        name = model['name']
        if not model['in_db']:
            name = f"🗑️ {name}"

        if not model['in_db']:
            status = "⚠️ Not in DB"
        elif not model['on_disk']:
            status = "❌ Missing"
        elif model['in_place']:
            status = "✅ OK"
        else:
            status = "⚠️ Check"

        symlink = "🔗" if model['symlink'] else "📄"
        lfs = "⚠️" if model['git_lfs'] else "✅"

        # Truncate hash
        hash_display = model['hash'][:12] + "..." if len(model['hash']) > 15 else model['hash']

        table_data.append({
            'Model': name,
            'Size': model['size_formatted'],
            'Hash': hash_display,
            'Status': status,
            'Type': symlink,
            'LFS': lfs,
            '_model_name': model['name']  # Hidden column for copying
        })

    df = pd.DataFrame(table_data)

    # Configure AgGrid
    gb = GridOptionsBuilder.from_dataframe(df[['Model', 'Size', 'Hash', 'Status', 'Type', 'LFS']])
    gb.configure_selection(selection_mode='single', use_checkbox=False)
    gb.configure_grid_options(domLayout='normal', rowHeight=35)
    gridOptions = gb.build()

    # Display grid
    grid_response = AgGrid(
        df[['Model', 'Size', 'Hash', 'Status', 'Type', 'LFS']],
        gridOptions=gridOptions,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        height=650,
        theme='streamlit',
        enable_enterprise_modules=False,
        allow_unsafe_jscode=False
    )

    # Handle row selection and copy to clipboard
    if grid_response['selected_rows'] is not None and len(grid_response['selected_rows']) > 0:
        selected_idx = grid_response['selected_rows'][0]['_selectedRowNodeInfo']['nodeRowIndex']
        model_name = table_data[selected_idx]['_model_name']
        try:
            pyperclip.copy(model_name)
            st.toast("✓ Copied", icon="✅")
        except:
            st.toast(f"Copied: {model_name}", icon="✅")


if __name__ == "__main__":
    main()
