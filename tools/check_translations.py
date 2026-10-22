"""Check catalog coverage, placeholders and compiled files without editing sources.

Run ``python tools/check_translations.py`` with Django and GNU gettext installed.
Extraction runs in a disposable copy of the application. DomainError literals
are included separately because they are translated at the exception boundary.
"""

import ast
import gettext
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def message_keys(path: Path) -> set[str]:
    """Read singular message/context keys, including multiline PO strings."""
    keys: set[str] = set()
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
        fields: dict[str, str] = {}
        active = ""
        for line in block.splitlines():
            if line.startswith(("msgid ", "msgctxt ")):
                active, value = line.split(" ", 1)
                fields[active] = ast.literal_eval(value)
            elif line.startswith('"') and active:
                fields[active] += ast.literal_eval(line)
            else:
                active = ""
        if fields.get("msgid"):
            keys.add(
                (fields["msgctxt"] + "\x04" if "msgctxt" in fields else "")
                + fields["msgid"]
            )
    return keys


def check(root: Path) -> None:
    """Fail on missing/fuzzy messages, format errors or stale compiled catalogs."""
    app = root / "commentail"
    required: set[str] = set()
    for path in app.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DomainError"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                required.add(node.args[0].value)
    with tempfile.TemporaryDirectory(prefix="commentail-translations-") as directory:
        work = Path(directory)
        shutil.copytree(
            app, work / "app", ignore=shutil.ignore_patterns("locale", "__pycache__")
        )
        (work / "app/locale").mkdir()
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "django",
                "makemessages",
                "-l",
                "en",
                "--no-wrap",
                "--no-location",
            ],
            cwd=work / "app",
            check=True,
            env={
                key: value
                for key, value in os.environ.items()
                if key != "DJANGO_SETTINGS_MODULE"
            },
        )
        required |= message_keys(work / "app/locale/en/LC_MESSAGES/django.po")
        for po in sorted((app / "locale").glob("*/LC_MESSAGES/django.po")):
            locale = po.parents[1].name
            compiled = work / f"{locale}.mo"
            subprocess.run(
                ["msgfmt", "--check", str(po), "-o", str(compiled)], check=True
            )
            if compiled.read_bytes() != po.with_suffix(".mo").read_bytes():
                raise ValueError(f"{locale}: stale compiled catalog")
            with compiled.open("rb") as stream:
                catalog = gettext.GNUTranslations(stream)
            source_keys = message_keys(po)
            for key in required | source_keys:
                if "\x04" in key:
                    context, message = key.split("\x04", 1)
                    translated = catalog.pgettext(context, message)
                else:
                    message = key
                    translated = catalog.gettext(message)
                # Identical translations (e.g. German Name) are valid, but the
                # key must actually exist; gettext fallback cannot prove that.
                if key not in catalog._catalog:
                    raise ValueError(f"{locale}: missing or fuzzy translation: {key!r}")
                source_slots = re.findall(r"%\([^)]+\)[a-zA-Z]", message)
                target_slots = re.findall(r"%\([^)]+\)[a-zA-Z]", translated)
                if sorted(source_slots) != sorted(target_slots):
                    raise ValueError(f"{locale}: changed placeholders: {key!r}")
            print(
                f"{locale}: {len(source_keys)} complete messages; compiled catalog matches"
            )
        print(f"Required source messages: {len(required)}")


if __name__ == "__main__":
    check(Path(__file__).resolve().parent.parent)
