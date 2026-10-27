"""Tolerant recipe parsing."""

from __future__ import annotations

from pathlib import Path

from staged_recipes_submit.parsing import parse_recipe


def _write(tmp_path: Path, text: str | bytes, name: str = "recipe.yaml") -> Path:
    path = tmp_path / name
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def test_reads_a_v1_recipe_with_context_templating(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "context:\n  version: '2.1.0'\n  name: numpy\n"
        "package:\n  name: ${{ name }}\n  version: ${{ version }}\n",
    )
    metadata = parse_recipe(path)
    assert metadata.error is None
    assert (metadata.name, metadata.version) == ("numpy", "2.1.0")


def test_reads_a_v0_recipe(tmp_path: Path) -> None:
    path = _write(tmp_path, "package:\n  name: pkg\n  version: 1.0\n", name="meta.yaml")
    metadata = parse_recipe(path)
    assert (metadata.name, metadata.version, metadata.error) == ("pkg", "1.0", None)


def test_no_package_section_is_reported(tmp_path: Path) -> None:
    metadata = parse_recipe(_write(tmp_path, "build:\n  number: 0\n"))
    assert metadata.document is not None
    assert metadata.name is None
    assert metadata.error == "recipe.yaml has no 'package' section"


def test_invalid_yaml_is_reported(tmp_path: Path) -> None:
    metadata = parse_recipe(_write(tmp_path, "package: [unclosed\n"))
    assert metadata.error is not None
    assert metadata.error.startswith("recipe.yaml is not valid YAML")


def test_non_mapping_document_is_reported(tmp_path: Path) -> None:
    assert parse_recipe(_write(tmp_path, "- just\n- a list\n")).error == (
        "recipe.yaml must contain a mapping at the top level"
    )


def test_empty_document_is_reported(tmp_path: Path) -> None:
    assert parse_recipe(_write(tmp_path, "")).error == "recipe.yaml is empty"


def test_non_utf8_document_is_reported(tmp_path: Path) -> None:
    assert parse_recipe(_write(tmp_path, b"\xff\xfe\x00binary")).error == (
        "recipe.yaml is not valid UTF-8"
    )


def test_unreadable_document_is_reported(tmp_path: Path) -> None:
    metadata = parse_recipe(tmp_path / "missing.yaml")
    assert metadata.error is not None
    assert "cannot be read" in metadata.error


def test_unresolved_templates_are_kept_verbatim(tmp_path: Path) -> None:
    metadata = parse_recipe(
        _write(tmp_path, "package:\n  name: pkg\n  version: ${{ undefined }}\n")
    )
    assert metadata.version == "${{ undefined }}"
