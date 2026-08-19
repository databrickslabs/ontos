#!/usr/bin/env python3
import shutil
from pathlib import Path


def cleanup_directory(directory: Path):
    """Recursively remove all contents of a directory"""
    if directory.exists():
        for item in directory.glob("**/*"):
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        # Remove the directory itself if it's not the root static directory
        if directory.name == "static":
            directory.mkdir(parents=True, exist_ok=True)
        else:
            directory.rmdir()

def copy_static_files():
    """Copy frontend build files to api/static directory"""
    # Source and destination directories
    build_dir = Path("build")
    static_dir = Path("api/static")

    # Ensure build directory exists
    if not build_dir.exists():
        print("Error: build directory not found. Please run 'npm run build' first.")
        return False

    # Create static directory if it doesn't exist
    static_dir.mkdir(parents=True, exist_ok=True)

    # Clean up existing static files recursively
    cleanup_directory(static_dir)

    # Copy new build files
    for item in build_dir.glob("**/*"):
        if item.is_file():
            # Calculate relative path from build_dir
            rel_path = item.relative_to(build_dir)
            # Create target directory if it doesn't exist
            target_dir = static_dir / rel_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            # Copy the file
            shutil.copy2(item, target_dir / rel_path.name)

    print("Successfully copied frontend build files to api/static")
    return True

if __name__ == "__main__":
    copy_static_files()
