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

    db_path = data_path / "invokeai.db"

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
    """Extract hash value from model path"""
    # InvokeAI stores models in folders named by their hash
    # Example: /path/to/models/sd-1/main/abc123def456/model.safetensors
    # The hash is typically the parent directory name
    path_obj = Path(path)

    # Get parent directory name (should be the hash)
    hash_value = path_obj.parent.name

    # If it looks like a hash (long alphanumeric string), return it
    if len(hash_value) > 8 and hash_value.isalnum():
        return hash_value

    return "N/A"


def get_models_from_db(db_path: Path) -> List[Dict]:
    """Retrieve all models from the database with metadata"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Query all models
    cursor.execute("SELECT id, type, path, name FROM models")
    rows = cursor.fetchall()

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

        # Extract hash from path
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
            'git_lfs': is_lfs_pointer
        })

    conn.close()
    return models


def main():
    """Main Streamlit application"""
    st.set_page_config(
        page_title="InvokeAI Model Cleanup",
        page_icon="🧹",
        layout="wide"
    )

    st.title("🧹 InvokeAI Model Cleanup")
    st.markdown("---")

    # Load configuration and database
    config = load_config()
    db_path = get_database_path(config)

    # Display database location
    st.info(f"📂 Database: `{db_path}`")

    # Load models
    with st.spinner("Loading models from database..."):
        models = get_models_from_db(db_path)

    st.success(f"✅ Loaded {len(models)} models")
    st.markdown("---")

    # Display models in a scrollable container
    st.subheader("Model List")

    # Create a container for the model list
    for idx, model in enumerate(models):
        with st.container():
            col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 2, 1, 1, 1])

            with col1:
                st.text(f"📦 {model['name']}")

            with col2:
                st.text(f"💾 {model['size_formatted']}")

            with col3:
                # Truncate hash if too long
                hash_display = model['hash'][:12] + "..." if len(model['hash']) > 15 else model['hash']
                st.text(f"🔑 {hash_display}")

            with col4:
                # In-place indicator
                if model['in_place']:
                    st.text("✅ In-place")
                else:
                    st.text("❌ Missing")

            with col5:
                # Symlink indicator
                if model['symlink']:
                    st.text("🔗 Link")
                else:
                    st.text("📄 File")

            with col6:
                # Git-LFS indicator
                if model['git_lfs']:
                    st.text("⚠️ LFS")
                else:
                    st.text("✅ OK")

            # Add separator
            if idx < len(models) - 1:
                st.markdown("---")

    # Instructions
    st.markdown("---")
    st.info("ℹ️ Press ESC or close the browser tab to exit")


if __name__ == "__main__":
    main()
