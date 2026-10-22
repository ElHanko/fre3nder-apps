#!/usr/bin/env python3
"""Assemble explicit package sources without accessing a signing key."""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile


PRIVATE_KEY = re.compile(rb"^[ \t]*-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----[ \t]*\r?$", re.MULTILINE)
CACHES = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def checked_file(path):
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"package source must be a regular non-symlink file: {path}")
    if PRIVATE_KEY.search(path.read_bytes()):
        raise ValueError(f"private key in package source: {path}")


def validate_source(source):
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in CACHES for part in relative.parts) or path.suffix in (".pyc", ".pyo"):
            raise ValueError(f"cache in package source: {relative}")
        if path.is_symlink():
            raise ValueError(f"symlink in package source: {relative}")
        if not path.is_dir():
            checked_file(path)
    if not (source / "payload").is_dir():
        raise ValueError("package payload directory is missing")


@contextmanager
def package_stage(recipe, output, *, files=()):
    """Copy named recipe files, let the app prepare payload, then replace output."""
    recipe, output = Path(recipe), Path(output)
    if recipe.is_symlink() or not recipe.is_dir():
        raise ValueError("recipe must be a real directory")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ValueError("package destination must be a real directory")
    if output.resolve().is_relative_to(recipe.resolve()) or recipe.resolve().is_relative_to(output.resolve()):
        raise ValueError("package destination must be separate from the recipe")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fre3app-source-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        stage = temporary / "package"
        stage.mkdir()
        for name in ("manifest.toml.in", "service", *files):
            relative = PurePosixPath(name)
            if relative.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")) or "\\" in name:
                raise ValueError(f"unsafe recipe member: {name}")
            source = recipe
            for part in relative.parts:
                source = source / part
                if source.is_symlink():
                    raise ValueError(f"symlink in recipe member: {name}")
            checked_file(source)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        yield stage
        validate_source(stage)
        previous = temporary / "previous"
        if output.exists():
            output.rename(previous)
        try:
            os.replace(stage, output)
        except OSError:
            if previous.exists():
                previous.rename(output)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path, help="minimal package source fixture, e.g. apps/dummy")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with package_stage(args.recipe, args.output) as stage:
        payload = args.recipe / "payload"
        if payload.is_symlink() or not payload.is_dir():
            parser.error("payload must be a real directory")
        shutil.copytree(payload, stage / "payload", symlinks=True)
    print(args.output)


if __name__ == "__main__":
    main()
