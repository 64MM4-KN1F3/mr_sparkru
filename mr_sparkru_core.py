#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Core shared functionality for Mr. Sparkru data management operations.
"""
import os
import shutil
import sqlite3
import json
import base64
from pathlib import Path
from typing import Dict, List, Optional, Union


# Data path for the Draw Things app
DATA_PATH = Path.home() / "Library/Containers/com.liuliu.draw-things/Data"


def format_size(size_bytes):
    """
    Format a size in bytes into a human-readable string.
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    if size_bytes < 1024**3:
        return f"{size_bytes / 1024 ** 2:.2f} MB"
    return f"{size_bytes / 1024 ** 3:.2f} GB"


class UndoManager:
    """Simple single-level undo system for deletions."""

    def __init__(self, print_function=None):
        self.undo_data_path = Path.home() / ".mr_sparkru_undo.json"
        self.current_undo: Optional[Dict] = None
        self.print_function = print_function or print

    def has_pending_undo(self) -> bool:
        """Check if there's an undo operation available."""
        return self.current_undo is not None

    def load_undo_data(self):
        """Load undo data from persistent storage."""
        if self.undo_data_path.exists():
            try:
                with open(self.undo_data_path, 'r') as f:
                    self.current_undo = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.current_undo = None

    def save_undo_data(self):
        """Save current undo data to persistent storage."""
        if self.current_undo:
            try:
                with open(self.undo_data_path, 'w') as f:
                    json.dump(self.current_undo, f)
            except OSError:
                pass  # Silently fail if we can't save

    def record_model_deletion(self, model_files: List[str]):
        """Record a model deletion operation for undo."""
        self.current_undo = {
            'type': 'models',
            'files': model_files
        }
        self.save_undo_data()

    def record_project_deletion(self, project_names: List[str]):
        """Record a project deletion operation for undo."""
        self.current_undo = {
            'type': 'projects',
            'names': project_names
        }
        self.save_undo_data()

    def record_image_deletion(self, project_name: str, image_rowids: List[int], deleted_data: Dict):
        """Record an image deletion operation for undo."""
        self.current_undo = {
            'type': 'images',
            'project': project_name,
            'rowids': image_rowids,
            'data': deleted_data  # dict with 'tensors', 'thumbnail,' etc. data as base64
        }
        self.save_undo_data()

    def undo_last_operation(self) -> bool:
        """Perform the undo operation. Returns True if successful."""
        if not self.current_undo:
            self.print_function("No undo operation available.")
            return False

        undo_type = self.current_undo['type']

        try:
            if undo_type == 'models':
                self._undo_model_deletion()
            elif undo_type == 'projects':
                self._undo_project_deletion()
            elif undo_type == 'images':
                self._undo_image_deletion()
            else:
                self.print_function(f"Unknown undo type: {undo_type}")
                return False

            # Clear undo data after successful undo
            self.current_undo = None
            self.undo_data_path.unlink(missing_ok=True)
            self.print_function("Undo operation completed successfully.")
            return True

        except Exception as e:
            self.print_function(f"Error during undo operation: {e}")
            return False

    def _undo_model_deletion(self):
        """Restore deleted model files."""
        models_path = DATA_PATH / "Documents" / "Models"
        restored_count = 0

        for model_file in self.current_undo['files']:
            model_path = models_path / model_file
            if model_path.exists():
                self.print_function(f"Model file {model_file} still exists, skipping.")
                continue

            backup_path = models_path / f".{model_file}.backup"
            if backup_path.exists():
                try:
                    shutil.move(str(backup_path), str(model_path))
                    restored_count += 1
                    self.print_function(f"Restored model: {model_file}")
                except OSError as e:
                    self.print_function(f"Failed to restore model {model_file}: {e}")
            else:
                self.print_function(f"Backup not found for model: {model_file}")

        self.print_function(f"Restored {restored_count} model files.")

    def _undo_project_deletion(self):
        """Restore deleted project files."""
        documents_path = DATA_PATH / "Documents"
        restored_count = 0

        for project_name in self.current_undo['names']:
            # Look for backup files
            base_backup = documents_path / f".{project_name}.sqlite3.backup"
            if base_backup.exists():
                try:
                    shutil.move(str(base_backup), str(documents_path / f"{project_name}.sqlite3"))
                    restored_count += 1
                    self.print_function(f"Restored project database: {project_name}")

                    # Also restore shm and wal files if they exist
                    for ext in ['-shm', '-wal']:
                        backup_file = documents_path / f".{project_name}.sqlite3{ext}.backup"
                        if backup_file.exists():
                            shutil.move(str(backup_file), str(documents_path / f"{project_name}.sqlite3{ext}"))

                except OSError as e:
                    self.print_function(f"Failed to restore project {project_name}: {e}")
            else:
                self.print_function(f"Backup not found for project: {project_name}")

        self.print_function(f"Restored {restored_count} projects.")

    def _undo_image_deletion(self):
        """Restore deleted images by reinserting the data."""
        project_name = self.current_undo['project']
        db_path = DATA_PATH / "Documents" / f"{project_name}.sqlite3"

        if not db_path.exists():
            # Try to create the project if it was deleted
            self.print_function(f"Project {project_name} database not found. Cannot restore images.")
            return

        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Decode and reinsert the backed up data
                backup_data = self.current_undo['data']

                # Reinsert tensors
                if 'tensors' in backup_data:
                    for name, data_b64 in backup_data['tensors'].items():
                        try:
                            data = base64.b64decode(data_b64)
                            cursor.execute(
                                "INSERT INTO tensors (name, data) VALUES (?, ?)",
                                (name, data)
                            )
                        except Exception as e:
                            self.print_function(f"Failed to restore tensor {name}: {e}")

                # Reinsert tensorhistorynode
                if 'tensorhistorynode' in backup_data:
                    for row_data_b64 in backup_data['tensorhistorynode']:
                        try:
                            # This is complex - we'd need to preserve all columns
                            # For now, skip this part as it's very schema-dependent
                            pass
                        except Exception as e:
                            self.print_function(f"Failed to restore tensor history: {e}")

                # Reinsert thumbnails
                for table in ['thumbnailhistorynode', 'thumbnailhistoryhalfnode']:
                    if table in backup_data:
                        for rowid, data_b64 in backup_data[table].items():
                            try:
                                data = base64.b64decode(data_b64)
                                cursor.execute(
                                    f"INSERT OR REPLACE INTO {table} (rowid, p) VALUES (?, ?)",
                                    (int(rowid), data)
                                )
                            except Exception as e:
                                self.print_function(f"Failed to restore {table} entry {rowid}: {e}")

                conn.commit()
                self.print_function(f"Attempted to restore image data for project '{project_name}'.")

        except sqlite3.Error as e:
            self.print_function(f"Database error during image restoration: {e}")


def clear_undo_cache():
    """Clear the undo cache data."""
    undo_data_path = Path.home() / ".mr_sparkru_undo.json"
    if undo_data_path.exists():
        undo_data_path.unlink()


def delete_models(model_files: List[str], undo_manager: Optional[UndoManager] = None) -> List[str]:
    """
    Delete one or more model files non-interactively.
    Returns list of successfully deleted models.
    """
    models_path = DATA_PATH / "Documents" / "Models"
    deleted_models = []

    for model_file in model_files:
        if not model_file.endswith((".ckpt", ".safetensors")):
            print(f"Warning: {model_file} may not be a valid model file. Processing anyway.")

        model_path = models_path / model_file
        if model_path.exists():
            try:
                # Create backup before deletion if undo manager provided
                if undo_manager:
                    backup_path = models_path / f".{model_file}.backup"
                    shutil.copy2(str(model_path), str(backup_path))

                os.remove(model_path)
                deleted_models.append(model_file)
                print(f"Deleted model: {model_file}")
            except OSError as e:
                print(f"Error deleting model {model_file}: {e}")
        else:
            print(f"Model file not found: {model_file}")

    if deleted_models and undo_manager:
        undo_manager.record_model_deletion(deleted_models)

    return deleted_models


def delete_projects(project_names: List[str], undo_manager: Optional[UndoManager] = None, silent_print=None) -> List[str]:
    """
    Delete one or more projects non-interactively.
    Returns list of successfully deleted projects.
    """
    documents_path = DATA_PATH / "Documents"
    deleted_projects = []
    _print = silent_print or print

    for project_name in project_names:
        base_project_path = documents_path / f"{project_name}.sqlite3"
        if not base_project_path.exists():
            _print(f"Warning: Project {project_name} not found, skipping.")
            continue

        try:
            # Create backups for all project files before deletion
            if undo_manager:
                for ext in [".sqlite3", ".sqlite3-shm", ".sqlite3-wal"]:
                    project_file = f"{project_name}{ext}"
                    project_path = documents_path / project_file
                    if project_path.exists():
                        backup_path = documents_path / f".{project_file}.backup"
                        shutil.copy2(str(project_path), str(backup_path))

            # Delete the actual files
            for ext in [".sqlite3", ".sqlite3-shm", ".sqlite3-wal"]:
                project_file = f"{project_name}{ext}"
                project_path = documents_path / project_file
                if project_path.exists():
                    os.remove(project_path)

            deleted_projects.append(project_name)

        except OSError as e:
            print(f"Error deleting project {project_name}: {e}")

    if deleted_projects and undo_manager:
        undo_manager.record_project_deletion(deleted_projects)

    return deleted_projects


def delete_images(project_name: str, image_row_ids: List[int], undo_manager: Optional[UndoManager] = None) -> bool:
    """
    Delete images from a project non-interactively.
    Returns True if successful.
    """
    db_path = DATA_PATH / "Documents" / f"{project_name}.sqlite3"
    if not db_path.exists():
        print(f"Error: Project '{project_name}' not found.", file=sys.stderr)
        return False

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Get current image count to check if we're deleting the last images
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnailhistoryhalfnode'")
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*) FROM thumbnailhistoryhalfnode")
                current_image_count = cursor.fetchone()[0]
            else:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnailhistorynode'")
                if cursor.fetchone():
                    cursor.execute("SELECT COUNT(*) FROM thumbnailhistorynode")
                    current_image_count = cursor.fetchone()[0]
                else:
                    current_image_count = 0

            # Create backup data for undo functionality
            backup_data = {}

            # Backup tensors
            tensor_keys = [f"tensor_history_{rowid}" for rowid in image_row_ids]
            placeholders = ','.join('?' for _ in tensor_keys)
            cursor.execute(f"SELECT name, data FROM tensors WHERE name IN ({placeholders})", tensor_keys)
            tensors_backup = {}
            for name, data in cursor.fetchall():
                tensors_backup[name] = base64.b64encode(data).decode('ascii')
            backup_data['tensors'] = tensors_backup

            # Backup thumbnails
            rowids_tuple = tuple(image_row_ids)
            thumbnails_backup = {}
            for table in ['thumbnailhistorynode', 'thumbnailhistoryhalfnode']:
                cursor.execute(f"SELECT rowid, p FROM {table} WHERE rowid IN ({','.join('?' for _ in rowids_tuple)})", rowids_tuple)
                table_backup = {}
                for rowid, p_data in cursor.fetchall():
                    table_backup[str(rowid)] = base64.b64encode(p_data).decode('ascii')
                if table_backup:
                    thumbnails_backup[table] = table_backup
            backup_data.update(thumbnails_backup)

            # Perform the deletions
            cursor.execute(
                f"DELETE FROM tensorhistorynode WHERE rowid IN ({','.join('?' for _ in rowids_tuple)})",
                rowids_tuple,
            )

            cursor.execute(
                f"DELETE FROM thumbnailhistorynode WHERE rowid IN ({','.join('?' for _ in rowids_tuple)})",
                rowids_tuple,
            )
            cursor.execute(
                f"DELETE FROM thumbnailhistoryhalfnode WHERE rowid IN ({','.join('?' for _ in rowids_tuple)})",
                rowids_tuple,
            )

            cursor.execute(
                f"DELETE FROM tensors WHERE name IN ({placeholders})",
                tensor_keys,
            )

            conn.commit()

            # Record the image deletion for undo
            if undo_manager:
                undo_manager.record_image_deletion(project_name, image_row_ids, backup_data)

            print(f"Deleted {len(image_row_ids)} images from project '{project_name}' successfully.")
            return True

    except sqlite3.Error as e:
        print(f"Error deleting images from database: {e}", file=sys.stderr)
        return False
