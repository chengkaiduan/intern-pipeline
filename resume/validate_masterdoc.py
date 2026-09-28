#!/usr/bin/env python3
"""Check masterdoc.yaml for the failures that lose data silently.

    python3 validate_masterdoc.py [masterdoc.yaml]

Exits non-zero on any error. Run it after every write-back.

The duplicate-key check is the important one: YAML resolves a repeated key by keeping the
last occurrence and discarding the rest, with no warning. A second `bullets:` block under
one experience silently deletes every bullet in the first.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pyyaml required: pip3 install pyyaml")


class DuplicateKeyError(Exception):
    pass


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses to silently drop a repeated mapping key.

    Subclassing SafeLoader keeps the safe constructor set — this cannot instantiate
    arbitrary Python objects the way yaml.Loader / unsafe_load can. The only override is
    the mapping constructor, which adds the duplicate check and nothing else.
    """


def _no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            mark = key_node.start_mark
            raise DuplicateKeyError(
                f"duplicate key '{key}' at line {mark.line + 1} — "
                f"YAML keeps only the last one, so the earlier block is being discarded"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def fact_keys(entry: dict) -> set[str]:
    """Facts are a list of single-key dicts: [{f0: "..."}, {f1: "..."}]."""
    keys: set[str] = set()
    for fact in entry.get("facts", []) or []:
        if isinstance(fact, dict):
            keys |= set(fact)
    return keys


def validate(path: Path) -> list[str]:
    errors: list[str] = []

    try:
        doc = yaml.load(path.read_text(encoding="utf-8"), Loader=StrictLoader)
    except DuplicateKeyError as exc:
        return [str(exc)]
    except yaml.YAMLError as exc:
        return [f"unparseable YAML: {exc}"]

    seen_bullet_ids: dict[str, str] = {}

    for section in ("experiences", "projects", "leadership"):
        for entry in doc.get(section, []) or []:
            entry_id = entry.get("id", "<no id>")
            facts = fact_keys(entry)

            for bullet in entry.get("bullets", []) or []:
                bullet_id = bullet.get("id", "<no id>")

                if not bullet.get("text"):
                    errors.append(f"{entry_id}/{bullet_id}: bullet has no text")

                if bullet_id in seen_bullet_ids:
                    errors.append(
                        f"{entry_id}/{bullet_id}: bullet id already used by "
                        f"{seen_bullet_ids[bullet_id]}"
                    )
                seen_bullet_ids[bullet_id] = entry_id

                unknown = set(bullet.get("source_facts", []) or []) - facts
                if unknown:
                    errors.append(
                        f"{entry_id}/{bullet_id}: source_facts reference unknown facts "
                        f"{sorted(unknown)}"
                    )

                if bullet.get("approved") and bullet.get("rejected"):
                    errors.append(f"{entry_id}/{bullet_id}: both approved and rejected")

    profile = doc.get("profile", {})
    for field in ("name", "email", "phone"):
        if not profile.get(field):
            errors.append(f"profile.{field} is missing")

    graduation = doc.get("education", {}).get("graduation", {})
    if "default" not in graduation:
        errors.append("education.graduation.default is missing")

    return errors


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "masterdoc.yaml"
    errors = validate(path)

    if errors:
        for error in errors:
            print(f"ERROR {error}")
        sys.exit(f"\n{len(errors)} problem(s) in {path}")

    print(f"{path.name} is valid")


if __name__ == "__main__":
    main()
