from __future__ import annotations

from dataclasses import asdict, fields as dc_fields
from datetime import datetime
from pathlib import Path
import re
import shutil
import zipfile

from zapret_hub.domain import InstalledMod
from zapret_hub.services.logging_service import LoggingManager
from zapret_hub.services.settings import SettingsManager
from zapret_hub.services.storage import StorageManager
from zapret_hub.services.orchestrator import zapret2_hub


class Zapret2ModsManager:
    """Zapret2 modifications — separate store + merge from classic Zapret mods.

    Layout:
      {work_root}/mods_zapret2/{id}/
        lists/*.txt   → merged into configs/zapret2/list-hub.txt / ipset-hub.txt
        *.lua         → copied into configs/zapret2/mod_lua/
        zapret-hub-mod.json
    Registry: data/installed_zapret2_mods.json
    Settings: enabled_zapret2_mod_ids
    """

    METADATA_FILENAME = "zapret-hub-mod.json"
    UNKNOWN_AUTHOR = "неизвестен"
    ALLOWED_SUFFIXES = {".txt", ".lua", ".bin"}
    BLOCKED_SUFFIXES = {
        ".exe",
        ".sys",
        ".dll",
        ".msi",
        ".scr",
        ".com",
        ".bat",
        ".cmd",
        ".ps1",
        ".vbs",
        ".js",
        ".jar",
    }
    JUNK_TXT_PREFIXES = ("readme", "license", "changelog", "copying", "authors")

    def __init__(
        self,
        storage: StorageManager,
        logging: LoggingManager,
        settings: SettingsManager,
    ) -> None:
        self.storage = storage
        self.logging = logging
        self.settings = settings
        mods2 = getattr(storage.paths, "mods_zapret2_dir", None)
        self.mods_dir = Path(mods2) if mods2 is not None else storage.paths.mods_dir.parent / "mods_zapret2"
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        self._installed_path = storage.paths.data_dir / "installed_zapret2_mods.json"
        if not self._installed_path.exists():
            self.storage.write_json(self._installed_path, [])
        self._cleanup_missing()

    def list_installed(self) -> list[InstalledMod]:
        raw = self.storage.read_json(self._installed_path, default=[]) or []
        allowed = {f.name for f in dc_fields(InstalledMod)}
        result: list[InstalledMod] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(InstalledMod(**{k: v for k, v in item.items() if k in allowed}))
            except Exception:
                continue
        return result

    def _save(self, installed: list[InstalledMod]) -> None:
        self.storage.write_json(self._installed_path, [asdict(item) for item in installed])

    def _sync_enabled(self, installed: list[InstalledMod] | None = None) -> None:
        items = installed if installed is not None else self.list_installed()
        self.settings.update(enabled_zapret2_mod_ids=sorted(item.id for item in items if item.enabled))

    def _cleanup_missing(self) -> None:
        installed = self.list_installed()
        valid = [item for item in installed if Path(item.path).exists()]
        if len(valid) != len(installed):
            self._save(valid)
            self._sync_enabled(valid)

    def _unique_id(self, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", (name or "mod").lower()).strip("-") or "mod"
        existing = {item.id for item in self.list_installed()}
        if base not in existing:
            return base
        idx = 2
        while f"{base}-{idx}" in existing:
            idx += 1
        return f"{base}-{idx}"

    def move(self, mod_id: str, direction: int) -> list[InstalledMod]:
        installed = self.list_installed()
        index = next((i for i, item in enumerate(installed) if item.id == mod_id), -1)
        if index < 0:
            return installed
        target = max(0, min(len(installed) - 1, index + int(direction)))
        if target == index:
            return installed
        item = installed.pop(index)
        installed.insert(target, item)
        self._save(installed)
        self.rebuild_merge()
        return installed

    def reorder(self, ordered_ids: list[str], *, rebuild: bool = True) -> list[InstalledMod]:
        installed = self.list_installed()
        by_id = {item.id: item for item in installed}
        requested: list[InstalledMod] = []
        seen: set[str] = set()
        for raw_id in ordered_ids:
            mod_id = str(raw_id or "")
            if not mod_id or mod_id in seen or mod_id not in by_id:
                continue
            requested.append(by_id[mod_id])
            seen.add(mod_id)
        ordered: list[InstalledMod] = []
        req_iter = iter(requested)
        for item in installed:
            if item.id in seen:
                ordered.append(next(req_iter))
            else:
                ordered.append(item)
        self._save(ordered)
        if rebuild:
            self.rebuild_merge()
        return ordered

    def create_empty(self, *, name: str, description: str = "", author: str = UNKNOWN_AUTHOR) -> InstalledMod:
        mod_id = self._unique_id(name or "zapret2-mod")
        target = self.mods_dir / mod_id
        (target / "lists").mkdir(parents=True, exist_ok=True)
        (target / "lists" / "list-general.txt").write_text("", encoding="utf-8")
        (target / "lists" / "ipset-all.txt").write_text("", encoding="utf-8")
        entry = InstalledMod(
            id=mod_id,
            version=datetime.utcnow().strftime("%Y.%m.%d"),
            path=str(target),
            name=name.strip() or mod_id,
            author=author.strip() or self.UNKNOWN_AUTHOR,
            description=description.strip(),
            enabled=False,
            source_type="zapret2_bundle",
            emoji="🧩",
        )
        installed = self.list_installed()
        installed.insert(0, entry)
        self._save(installed)
        self._sync_enabled(installed)
        self.logging.log("info", "Zapret2 mod created", mod_id=mod_id)
        return entry

    def update_metadata(
        self,
        mod_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        author: str | None = None,
        version: str | None = None,
        icon_url: str | None = None,
        marketplace_slug: str | None = None,
        source_url: str | None = None,
    ) -> InstalledMod:
        installed = self.list_installed()
        entry = next(item for item in installed if item.id == mod_id)
        if name is not None:
            entry.name = name
        if description is not None:
            entry.description = description
        if author is not None:
            entry.author = author
        if version is not None:
            entry.version = version
        if icon_url is not None:
            entry.icon_url = str(icon_url or "").strip()
        if marketplace_slug is not None:
            entry.marketplace_slug = str(marketplace_slug or "").strip()
        if source_url is not None:
            entry.source_url = str(source_url or "").strip()
        self._save(installed)
        self._write_metadata_file(entry)
        return entry

    def list_files(self, mod_id: str) -> list[dict[str, object]]:
        root = self._editable_mod_root(mod_id)
        records: list[dict[str, object]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name == self.METADATA_FILENAME:
                continue
            if not self._is_allowed_relative(path.relative_to(root)):
                continue
            records.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size})
        return records

    def read_file(self, mod_id: str, relative_path: str) -> str:
        return self._safe_mod_file(mod_id, relative_path, must_exist=True).read_text(encoding="utf-8", errors="ignore")

    def write_file(self, mod_id: str, relative_path: str, content: str) -> None:
        target = self._safe_mod_file(mod_id, relative_path, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.rebuild_merge()

    def delete_file(self, mod_id: str, relative_path: str) -> None:
        self._safe_mod_file(mod_id, relative_path, must_exist=True).unlink()
        self.rebuild_merge()

    def set_enabled(self, mod_id: str, enabled: bool) -> InstalledMod:
        installed = self.set_enabled_states({mod_id: enabled})
        return next(item for item in installed if item.id == mod_id)

    def set_enabled_states(self, states: dict[str, bool]) -> list[InstalledMod]:
        installed = self.list_installed()
        wanted = {str(mod_id): bool(enabled) for mod_id, enabled in states.items()}
        found: set[str] = set()
        changed: list[str] = []
        for entry in installed:
            if entry.id not in wanted:
                continue
            found.add(entry.id)
            enabled = wanted[entry.id]
            if bool(entry.enabled) == enabled:
                continue
            entry.enabled = enabled
            changed.append(entry.id)
        missing = set(wanted) - found
        if missing:
            raise KeyError(f"Unknown Zapret2 modifications: {', '.join(sorted(missing))}")
        self._save(installed)
        self._sync_enabled(installed)
        self.rebuild_merge()
        self.logging.log("info", "Zapret2 mod states changed", mod_ids=changed, count=len(changed))
        return installed

    def remove(self, mod_id: str) -> None:
        installed = [item for item in self.list_installed() if item.id != mod_id]
        self._save(installed)
        self._sync_enabled(installed)
        target = self.mods_dir / mod_id
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        self.rebuild_merge()
        self.logging.log("info", "Zapret2 mod removed", mod_id=mod_id)

    def _is_junk_txt(self, name: str) -> bool:
        stem = Path(name).stem.lower()
        return any(stem == prefix or stem.startswith(f"{prefix}.") or stem.startswith(f"{prefix}-") for prefix in self.JUNK_TXT_PREFIXES)

    def _is_allowed_relative(self, relative: Path) -> bool:
        if relative.is_absolute() or ".." in relative.parts:
            return False
        name = relative.name
        lowered = name.lower()
        if lowered == self.METADATA_FILENAME.lower():
            return True
        if "__pycache__" in relative.parts or ".git" in relative.parts:
            return False
        suffix = relative.suffix.lower()
        if suffix in self.BLOCKED_SUFFIXES:
            return False
        if suffix in {".lua", ".bin"}:
            return True
        if suffix == ".txt":
            return not self._is_junk_txt(name)
        return False

    def _extract_zip_filtered(self, source: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source, "r") as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                rel = Path(member.filename.replace("\\", "/"))
                if not self._is_allowed_relative(rel):
                    continue
                destination = target / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _copy_tree_filtered(self, source: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for file_path in source.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(source)
            if not self._is_allowed_relative(rel):
                continue
            destination = target / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, destination)

    def _unwrap_single_root(self, target: Path) -> None:
        children = [p for p in target.iterdir()]
        if len(children) == 1 and children[0].is_dir():
            nested = children[0]
            for item in nested.iterdir():
                shutil.move(str(item), str(target / item.name))
            shutil.rmtree(nested, ignore_errors=True)

    def import_from_path(self, path: str | Path) -> InstalledMod:
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(str(source))
        name = source.stem if source.is_file() else source.name
        mod_id = self._unique_id(name)
        target = self.mods_dir / mod_id
        if target.exists():
            shutil.rmtree(target)
        if source.is_file() and source.suffix.lower() == ".zip":
            self._extract_zip_filtered(source, target)
            self._unwrap_single_root(target)
        elif source.is_dir():
            self._copy_tree_filtered(source, target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            lists = target / "lists"
            lists.mkdir(exist_ok=True)
            if source.suffix.lower() == ".lua":
                shutil.copy2(source, target / source.name)
            elif source.suffix.lower() == ".txt":
                shutil.copy2(source, lists / source.name)
            else:
                raise ValueError("Unsupported Zapret 2 mod file type.")
        entry = InstalledMod(
            id=mod_id,
            version=datetime.utcnow().strftime("%Y.%m.%d"),
            path=str(target),
            name=name,
            author=self.UNKNOWN_AUTHOR,
            enabled=True,
            source_type="zapret2_bundle",
            emoji="📦",
        )
        installed = self.list_installed()
        installed.insert(0, entry)
        self._save(installed)
        self._sync_enabled(installed)
        self.rebuild_merge()
        self.logging.log("info", "Zapret2 mod imported", mod_id=mod_id, source=str(source))
        return entry

    def import_from_paths(self, paths: list[str] | list[Path]) -> InstalledMod:
        if not paths:
            raise ValueError("No files selected")
        first = Path(paths[0])
        name = first.stem if len(paths) == 1 else f"zapret2-mod-{datetime.utcnow().strftime('%H%M%S')}"
        mod_id = self._unique_id(name)
        target = self.mods_dir / mod_id
        lists = target / "lists"
        lists.mkdir(parents=True, exist_ok=True)
        for raw in paths:
            path = Path(raw)
            if not path.is_file():
                continue
            if path.suffix.lower() == ".lua":
                shutil.copy2(path, target / path.name)
            elif path.suffix.lower() == ".txt":
                shutil.copy2(path, lists / path.name)
            elif path.suffix.lower() == ".zip":
                self._extract_zip_filtered(path, target)
                self._unwrap_single_root(target)
            else:
                continue
        entry = InstalledMod(
            id=mod_id,
            version=datetime.utcnow().strftime("%Y.%m.%d"),
            path=str(target),
            name=name,
            author=self.UNKNOWN_AUTHOR,
            enabled=True,
            source_type="zapret2_bundle",
            emoji="📦",
        )
        installed = self.list_installed()
        installed.insert(0, entry)
        self._save(installed)
        self._sync_enabled(installed)
        self.rebuild_merge()
        return entry

    def export_mod(self, mod_id: str, target_dir: str | Path) -> Path:
        entry = next(item for item in self.list_installed() if item.id == mod_id)
        source = Path(entry.path)
        destination = Path(target_dir)
        if destination.suffix.lower() == ".zip":
            zip_path = destination
            zip_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            destination.mkdir(parents=True, exist_ok=True)
            zip_path = destination / f"{entry.id}-{entry.version}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in source.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(source)
                if not self._is_allowed_relative(rel):
                    continue
                archive.write(file_path, arcname=str(rel.as_posix()))
        return zip_path

    def rebuild_merge(self) -> None:
        # Registry order is the user-visible layer order and must stay deterministic.
        enabled = [item for item in self.list_installed() if item.enabled]
        roots = [Path(item.path) for item in enabled]
        zapret2_hub.merge_mod_overlays(self.storage.paths.configs_dir, roots)

    def _editable_mod_root(self, mod_id: str) -> Path:
        entry = next(item for item in self.list_installed() if item.id == mod_id)
        root = Path(entry.path).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Zapret 2 modification path not found: {root}")
        return root

    def _safe_mod_file(self, mod_id: str, relative_path: str, *, must_exist: bool) -> Path:
        root = self._editable_mod_root(mod_id)
        relative = Path(str(relative_path or "").strip().replace("\\", "/"))
        if not relative.name or relative.is_absolute() or ".." in relative.parts or not self._is_allowed_relative(relative):
            raise ValueError("Недопустимый файл модификации Zapret 2.")
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ValueError("Путь к файлу выходит за пределы модификации.")
        if must_exist and not target.exists():
            raise FileNotFoundError(str(relative))
        return target

    def _write_metadata_file(self, entry: InstalledMod) -> None:
        root = Path(entry.path)
        if not root.exists():
            return
        import json

        (root / self.METADATA_FILENAME).write_text(
            json.dumps(
                {
                    "schema": "zapret-hub-zapret2-mod-v1",
                    "id": entry.id,
                    "name": entry.name or entry.id,
                    "description": entry.description,
                    "author": entry.author or self.UNKNOWN_AUTHOR,
                    "version": entry.version,
                    "source_url": entry.source_url,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
