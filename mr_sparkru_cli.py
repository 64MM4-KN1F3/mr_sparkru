#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A command-line tool for managing Draw Things data.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

import questionary
import mr_sparkru_core



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
                        f"({image_count:>4} images, {mr_sparkru_core.format_size(total_size):>10})"
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
        # Create undo manager for interactive operations
        undo_manager = mr_sparkru_core.UndoManager(print)
        undo_manager.load_undo_data()

        deleted_projects = mr_sparkru_core.delete_projects(selected_projects, undo_manager, print)
        total_space_freed = sum(project_metadata[project_name].get("size", 0) for project_name in deleted_projects)
        print("Deletion complete.")
        print(f"Total disk space freed: {mr_sparkru_core.format_size(total_space_freed)}")
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
        # Create undo manager for interactive operations
        undo_manager = mr_sparkru_core.UndoManager(print)
        undo_manager.load_undo_data()

        mr_sparkru_core.delete_images(db_path.stem, selected_images, undo_manager)
    else:
        print("Deletion cancelled.")
 
 

 
 
def main():
    """
    Main function for the script.
    """
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
    undo_manager = mr_sparkru_core.UndoManager(silent_print)
    undo_manager.load_undo_data()

    if args.clear_undo_cache:
        mr_sparkru_core.clear_undo_cache()
        silent_print("Undo cache cleared.")
        return

    if args.undo:
        undo_manager.undo_last_operation()
        return

    if args.delete_projects_interactive:
        delete_projects_interactive(mr_sparkru_core.DATA_PATH)
        return

    if args.delete_images_interactive:
        delete_images_interactive(mr_sparkru_core.DATA_PATH)
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
            mr_sparkru_core.delete_images(project_name, image_row_ids, undo_manager)
        except ValueError:
            print(
                "Error: Image row_ids must be integers.",
                file=sys.stderr,
            )
        return

    if args.delete_models:
        mr_sparkru_core.delete_models(args.delete_models, undo_manager)

    if args.delete_projects:
        mr_sparkru_core.delete_projects(args.delete_projects, undo_manager, silent_print)


if __name__ == "__main__":
    main()
