#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A command-line tool for managing Draw Things data.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union

import questionary

# The data path for the Draw Things app.
DATA_PATH = Path.home() / "Library/Containers/com.liuliu.draw-things/Data"

# Undo functionality
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
                import json
                with open(self.undo_data_path, 'r') as f:
                    self.current_undo = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.current_undo = None

    def save_undo_data(self):
        """Save current undo data to persistent storage."""
        if self.current_undo:
            try:
                import json
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
            print("No undo operation available.")
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
                print(f"Unknown undo type: {undo_type}")
                return False

            # Clear undo data after successful undo
            self.current_undo = None
            self.undo_data_path.unlink(missing_ok=True)
            print("Undo operation completed successfully.")
            return True

        except Exception as e:
            print(f"Error during undo operation: {e}")
            return False

    def _undo_model_deletion(self):
        """Restore deleted model files."""
        models_path = DATA_PATH / "Documents" / "Models"
        restored_count = 0

        for model_file in self.current_undo['files']:
            model_path = models_path / model_file
            if model_path.exists():
                print(f"Model file {model_file} still exists, skipping.")
                continue

            backup_path = models_path / f".{model_file}.backup"
            if backup_path.exists():
                try:
                    shutil.move(str(backup_path), str(model_path))
                    restored_count += 1
                    print(f"Restored model: {model_file}")
                except OSError as e:
                    print(f"Failed to restore model {model_file}: {e}")
            else:
                print(f"Backup not found for model: {model_file}")

        print(f"Restored {restored_count} model files.")

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
                    print(f"Restored project database: {project_name}")

                    # Also restore shm and wal files if they exist
                    for ext in ['-shm', '-wal']:
                        backup_file = documents_path / f".{project_name}.sqlite3{ext}.backup"
                        if backup_file.exists():
                            shutil.move(str(backup_file), str(documents_path / f"{project_name}.sqlite3{ext}"))

                except OSError as e:
                    print(f"Failed to restore project {project_name}: {e}")
            else:
                print(f"Backup not found for project: {project_name}")

        print(f"Restored {restored_count} projects.")

    def _undo_image_deletion(self):
        """Restore deleted images by reinserting the data."""
        import base64
        project_name = self.current_undo['project']
        db_path = DATA_PATH / "Documents" / f"{project_name}.sqlite3"

        if not db_path.exists():
            # Try to create the project if it was deleted
            print(f"Project {project_name} database not found. Cannot restore images.")
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
                            print(f"Failed to restore tensor {name}: {e}")

                # Reinsert tensorhistorynode
                if 'tensorhistorynode' in backup_data:
                    for row_data_b64 in backup_data['tensorhistorynode']:
                        try:
                            # This is complex - we'd need to preserve all columns
                            # For now, skip this part as it's very schema-dependent
                            pass
                        except Exception as e:
                            print(f"Failed to restore tensor history: {e}")

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
                                print(f"Failed to restore {table} entry {rowid}: {e}")

                conn.commit()
                print(f"Attempted to restore image data for project '{project_name}'.")

        except sqlite3.Error as e:
            print(f"Database error during image restoration: {e}")

# Global undo manager instance (will be initialized with print function in main)
undo_manager = None


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


def delete_projects_interactive(data_path):
    """
    Interactively delete projects.
    """
    documents_path = data_path / "Documents"
    project_files = list(documents_path.glob("*.sqlite3"))

    if not project_files:
        print("No projects found.")
        return

    project_choices = []
    project_metadata = {}
    for project_file in project_files:
        project_name = project_file.stem
        try:
            db_path = project_file
            # .sqlite3-shm and .sqlite3-wal are temporary files used by SQLite for
            # transaction control and write-ahead logging. They should be deleted
            # with the main database file.
            shm_path = documents_path / f"{project_name}.sqlite3-shm"
            wal_path = documents_path / f"{project_name}.sqlite3-wal"

            # Calculate disk space
            total_size = db_path.stat().st_size
            if shm_path.exists():
                total_size += shm_path.stat().st_size
            if wal_path.exists():
                total_size += wal_path.stat().st_size

            # Get image count
            try:
                # Get image count
                with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM tensors")
                    image_count = cursor.fetchone()[0]
            except sqlite3.OperationalError as e:
                if "no such table: tensors" in str(e):
                    image_count = 0
                else:
                    raise  # Re-raise the exception if it's not the one we're looking for

            project_metadata[project_name] = {
                "size": total_size,
                "image_count": image_count,
            }
            project_choices.append(
                {
                    "name": (
                        f"{project_name:<40} "
                        f"({image_count:>4} images, {format_size(total_size):>10})"
                    ),
                    "value": project_name,
                    "checked": False,
                }
            )
        except (sqlite3.Error, FileNotFoundError) as e:
            project_metadata[project_name] = {"size": 0, "error": str(e)}
            project_choices.append(
                {
                    "name": f"{project_name:<40} (Error: {e})",
                    "value": project_name,
                    "checked": False,
                }
            )

    project_choices.append(
        {
            "name": "[q] Quit",
            "value": "quit",
            "checked": False,
        }
    )

    selected_projects = questionary.checkbox(
        "Select projects to delete:", choices=project_choices
    ).ask()

    if not selected_projects:
        print("No projects selected.")
        return

    if "quit" in selected_projects:
        print("Quitting.")
        return

    print("You have selected the following projects for deletion:")
    for project_name in selected_projects:
        print(f"- {project_name}")

    if questionary.confirm("Are you sure you want to delete these projects?").ask():
        total_space_freed = 0
        for project_name in selected_projects:
            total_space_freed += project_metadata[project_name].get("size", 0)
            for ext in [".sqlite3", ".sqlite3-shm", ".sqlite3-wal"]:
                project_file = documents_path / f"{project_name}{ext}"
                if project_file.exists():
                    try:
                        os.remove(project_file)
                        print(f"Deleted project file: {project_file.name}")
                    except OSError as e:
                        print(
                            f"Error deleting project file {project_file.name}: {e}",
                            file=sys.stderr,
                        )
        print("Deletion complete.")
        print(f"Total disk space freed: {format_size(total_space_freed)}")
    else:
        print("Deletion cancelled.")


def get_project_choices(data_path):
    """
    Get a list of project choices for questionary.
    """
    documents_path = data_path / "Documents"
    project_files = list(documents_path.glob("*.sqlite3"))
    project_choices = []
    if not project_files:
        return None
 
    for project_file in project_files:
        project_name = project_file.stem
        project_choices.append({"name": project_name, "value": project_file})
    return project_choices
 
 
def delete_images_interactive(data_path):
    """
    Interactively delete images from a project.
    """
    project_choices = get_project_choices(data_path)
    if not project_choices:
        print("No projects found.")
        return
 
    db_path_str = questionary.select(
        "Select a project to delete images from:", choices=project_choices
    ).ask()
 
    if not db_path_str:
        return
 
    db_path = Path(db_path_str)
 
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cursor = conn.cursor()
            # Pragma to make sure we can read the table names
            cursor.execute("PRAGMA journal_mode=OFF;")
            cursor.execute(
                "SELECT rowid, SUBSTR(p, 1, 200) FROM tensorhistorynode ORDER BY rowid"
            )
            images = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Error reading project database: {e}", file=sys.stderr)
        return
 
    if not images:
        print("No images found in this project.")
        return
 
    image_choices = [
        {"name": f"[{rowid}] {prompt}", "value": rowid, "checked": False}
        for rowid, prompt in images
    ]
 
    selected_images = questionary.checkbox(
        "Select images to delete (press space to select, enter to confirm):",
        choices=image_choices,
    ).ask()
 
    if not selected_images:
        print("No images selected.")
        return
 
    print("You have selected the following images for deletion:")
    for rowid in selected_images:
        print(f"- Image ID: {rowid}")
 
    if questionary.confirm("Are you sure you want to delete these images?").ask():
        # Use the updated non-interactive function
        delete_images_non_interactive(data_path, db_path.stem, selected_images, should_delete_project=False)
    else:
        print("Deletion cancelled.")
 
 
def delete_images_non_interactive(data_path, project_name, image_row_ids, should_delete_project=False):
    """
    Delete images from a project non-interactively.
    """
    db_path = data_path / "Documents" / f"{project_name}.sqlite3"
    if not db_path.exists():
        print(f"Error: Project '{project_name}' not found.", file=sys.stderr)
        return

    import base64

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

            # Backup tensorhistorynode (complex, will need refinement)
            # For now, we're only backing up essential data

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

            # Check if we deleted the last images and prompt for project deletion
            remaining_images = current_image_count - len(image_row_ids)
            if remaining_images <= 0:
                print(f"This was the last image(s) in project '{project_name}'.")
                if questionary.confirm(f"Would you also like to delete the entire project '{project_name}'?").ask():
                    # Delete the project
                    documents_path = data_path / "Documents"
                    deleted_project_files = []

                    for ext in [".sqlite3", ".sqlite3-shm", ".sqlite3-wal"]:
                        project_file = f"{project_name}{ext}"
                        project_path = documents_path / project_file
                        if project_path.exists():
                            os.remove(project_path)
                            deleted_project_files.append(project_file)
                            print(f"Deleted project file: {project_file}")

                    if deleted_project_files:
                        undo_manager.record_project_deletion([project_name])
                        print(f"Project '{project_name}' has been deleted.")
                    return  # Don't record image deletion since project was deleted

            # Record the image deletion for undo
            undo_manager.record_image_deletion(project_name, image_row_ids, backup_data)
            print(f"Deleted {len(image_row_ids)} images from project '{project_name}' successfully.")

    except sqlite3.Error as e:
        print(f"Error deleting images from database: {e}", file=sys.stderr)
 
 
def main():
    """
    Main function for the script.
    """
    # Global undo manager initialization will be done after args parsing
    global undo_manager

    parser = argparse.ArgumentParser(
        description="A command-line tool for managing Draw Things data."
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Suppress stdout output (used when called from GUI).",
    )
    parser.add_argument(
        "--delete-models",
        nargs="+",
        metavar="MODEL_FILE",
        help="Delete one or more model files (.ckpt).",
    )
    parser.add_argument(
        "--delete-projects",
        nargs="+",
        metavar="PROJECT_NAME",
        help="Delete one or more projects.",
    )
    parser.add_argument(
        "--delete-projects-interactive",
        action="store_true",
        help="Interactively delete projects.",
    )
    parser.add_argument(
        "--delete-images-interactive",
        action="store_true",
        help="Interactively delete images from a project.",
    )
    parser.add_argument(
        "--delete-images",
        nargs="+",
        metavar="PROJECT_NAME ROW_ID",
        help="Delete one or more images from a project. Provide the project name and then one or more image row_ids.",
    )
    parser.add_argument(
        "--undo",
        action="store_true",
        help="Undo the last deletion operation."
    )
    parser.add_argument(
        "--clear-undo-cache",
        action="store_true",
        help="Clear/delete the undo cache data."
    )
    args = parser.parse_args()

    # Helper function to print only if not silent
    def silent_print(*values, **kwargs):
        if not args.silent:
            print(*values, **kwargs)

    # Initialize undo manager with silent print function
    undo_manager = UndoManager(silent_print)
    undo_manager.load_undo_data()

    if args.clear_undo_cache:
        if undo_manager.undo_data_path.exists():
            undo_manager.undo_data_path.unlink()
            silent_print("Undo cache cleared.")
        else:
            silent_print("No undo cache found to clear.")
        return

    if args.undo:
        undo_manager.undo_last_operation()
        return

    if args.delete_projects_interactive:
        delete_projects_interactive(DATA_PATH)
        return
 
    if args.delete_images_interactive:
        delete_images_interactive(DATA_PATH)
        return
 
    if args.delete_images:
        if len(args.delete_images) < 2:
            print(
                "Error: --delete-images requires a project name and at least one image row_id.",
                file=sys.stderr,
            )
            return
        project_name = args.delete_images[0]
        image_row_ids_str = args.delete_images[1:]

        try:
            image_row_ids = [int(row_id) for row_id in image_row_ids_str]
            delete_images_non_interactive(DATA_PATH, project_name, image_row_ids, should_delete_project=False)
        except ValueError:
            print(
                "Error: Image row_ids must be integers.",
                file=sys.stderr,
            )
        return
 
    if args.delete_models:
        models_path = DATA_PATH / "Documents" / "Models"
        deleted_models = []

        for model_file in args.delete_models:
            if not model_file.endswith(".ckpt"):
                print(
                    f"Error: {model_file} is not a valid model file. Skipping.",
                    file=sys.stderr,
                )
                continue
            model_path = models_path / model_file
            if model_path.exists():
                try:
                    # Create backup before deletion
                    backup_path = models_path / f".{model_file}.backup"
                    shutil.copy2(str(model_path), str(backup_path))
                    os.remove(model_path)
                    deleted_models.append(model_file)
                    print(f"Deleted model: {model_file}")
                except OSError as e:
                    print(
                        f"Error deleting model {model_file}: {e}", file=sys.stderr
                    )
            else:
                print(
                    f"Error: Model file not found: {model_file}", file=sys.stderr
                )

        if deleted_models:
            undo_manager.record_model_deletion(deleted_models)

    if args.delete_projects:
        documents_path = DATA_PATH / "Documents"
        deleted_projects = []

        for project_name in args.delete_projects:
            base_project_path = documents_path / f"{project_name}.sqlite3"
            if not base_project_path.exists():
                print(f"Warning: Project {project_name} not found, skipping.")
                continue

            try:
                # Create backups for all project files before deletion
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
                        silent_print(f"Deleted project file: {project_file}")

                deleted_projects.append(project_name)

            except OSError as e:
                print(
                    f"Error deleting project {project_name}: {e}",
                    file=sys.stderr,
                )

        if deleted_projects:
            undo_manager.record_project_deletion(deleted_projects)


if __name__ == "__main__":
    main()
