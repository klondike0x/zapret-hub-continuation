from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import re
import shutil
import tempfile
import zipfile
import random

from zapret_hub import __version__
from zapret_hub.domain import InstalledMod, ModIndexItem
from zapret_hub.services.github_network import GitHubNetworkClient
from zapret_hub.services.logging_service import LoggingManager
from zapret_hub.services.merge import MergeEngine
from zapret_hub.services.settings import SettingsManager
from zapret_hub.services.storage import StorageManager
from zapret_hub.services.files import validate_general_script_content


class ModsManager:
    METADATA_FILENAME = "zapret-hub-mod.json"
    UNKNOWN_AUTHOR = "неизвестен"
    ALLOWED_MOD_SUFFIXES = {".txt", ".ps1", ".bat"}
    BIN_SUFFIXES = {".bin"}
    _EMOJI_CHOICES = ["✨", "🪄", "🔥", "⚡", "🧩", "🎮", "🌐", "🛡️", "🚀", "💎", "📦", "🧪"]
    def __init__(
        self,
        storage: StorageManager,
        logging: LoggingManager,
        merge: MergeEngine,
        settings: SettingsManager,
        *,
        processes: object | None = None,
    ) -> None:
        self.storage = storage
        self.logging = logging
        self.merge = merge
        self.settings = settings
        recovery = getattr(processes, "with_github_connectivity_recovery", None)
        self.github = GitHubNetworkClient(logging, recovery_runner=recovery if callable(recovery) else None)
        self._installed_path = self.storage.paths.data_dir / "installed_mods.json"
        if not self._installed_path.exists():
            self.storage.write_json(self._installed_path, [])
        self._cleanup_missing_installed_mods()
        self._cleanup_installed_duplicate_generals()

    def fetch_index(self, *, refresh_remote: bool = False) -> list[ModIndexItem]:
        settings = self.settings.get()
        if refresh_remote and settings.mods_index_url:
            try:
                payload = self.github.github_json(settings.mods_index_url, timeout=10, purpose="mods-index")
                self.storage.write_json(self.storage.paths.cache_dir / "mods_index.json", payload)
                self.logging.log("info", "Mods index refreshed from URL", url=settings.mods_index_url)
            except Exception as error:
                self.logging.log("warning", "Failed to refresh mods index from URL", url=settings.mods_index_url, error=str(error))
        raw = self.storage.read_json(self.storage.paths.cache_dir / "mods_index.json", default=[]) or []
        return [ModIndexItem(**item) for item in raw]

    def list_installed(self) -> list[InstalledMod]:
        raw = self.storage.read_json(self._installed_path, default=[]) or []
        from dataclasses import fields as dc_fields

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
        self.storage.write_json(self._installed_path, [asdict(entry) for entry in installed])
        self.merge.rebuild()
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
        # Keep relative slots of untouched mods (custom vs bundled pages
        # often send only their subset).
        ordered: list[InstalledMod] = []
        req_iter = iter(requested)
        for item in installed:
            if item.id in seen:
                ordered.append(next(req_iter))
            else:
                ordered.append(item)
        self.storage.write_json(self._installed_path, [asdict(entry) for entry in ordered])
        if rebuild:
            self.merge.rebuild()
        return ordered

    def _cleanup_missing_installed_mods(self) -> None:
        """Remove stale registry entries left behind by interrupted deletions."""
        installed = self.list_installed()
        valid = [item for item in installed if Path(item.path).exists()]
        if len(valid) == len(installed):
            return
        self.storage.write_json(self._installed_path, [asdict(item) for item in valid])
        self.settings.update(enabled_mod_ids=sorted(item.id for item in valid if item.enabled))
        self.logging.log("warning", "Removed stale modification entries", removed=len(installed) - len(valid))

    def set_emoji(self, mod_id: str, emoji: str) -> InstalledMod:
        installed = self.list_installed()
        entry = next(item for item in installed if item.id == mod_id)
        entry.emoji = emoji.strip() or entry.emoji
        self.storage.write_json(self._installed_path, [asdict(item) for item in installed])
        return entry

    def update_metadata(
        self,
        mod_id: str,
        *,
        name: str,
        description: str,
        author: str,
        version: str,
        icon_url: str | None = None,
        source_url: str | None = None,
    ) -> InstalledMod:
        if mod_id == "unified-by-goshkow":
            raise ValueError("Hub is bundled and cannot be edited.")
        installed = self.list_installed()
        entry = next(item for item in installed if item.id == mod_id)
        entry.name = name.strip() or entry.name or mod_id
        entry.description = description.strip()
        entry.author = author.strip() or entry.author or self.UNKNOWN_AUTHOR
        entry.version = version.strip() or entry.version or datetime.utcnow().strftime("%Y.%m.%d")
        if icon_url is not None:
            entry.icon_url = str(icon_url or "").strip()
        if source_url is not None:
            entry.source_url = str(source_url or "").strip()
        self.storage.write_json(self._installed_path, [asdict(item) for item in installed])
        self._write_mod_metadata_file(entry)
        self.logging.log("info", "Mod metadata updated", mod_id=mod_id)
        return entry

    def create_empty(self, *, name: str, description: str = "", author: str = UNKNOWN_AUTHOR) -> InstalledMod:
        mod_id = self._unique_mod_id(name or "custom-mod")
        target_dir = self.storage.paths.mods_dir / mod_id
        (target_dir / "lists").mkdir(parents=True, exist_ok=True)
        (target_dir / "utils").mkdir(parents=True, exist_ok=True)
        (target_dir / "lists" / "list-general.txt").write_text("", encoding="utf-8")
        installed = self.list_installed()
        entry = InstalledMod(
            id=mod_id,
            version=datetime.utcnow().strftime("%Y.%m.%d"),
            path=str(target_dir),
            name=name.strip() or mod_id,
            author=author.strip() or self.UNKNOWN_AUTHOR,
            description=description.strip(),
            enabled=False,
            source_type="zapret_bundle",
            general_scripts=[],
            emoji=random.choice(self._EMOJI_CHOICES),
        )
        installed.insert(0, entry)
        self.storage.write_json(self._installed_path, [asdict(item) for item in installed])
        self._write_mod_metadata_file(entry)
        self.logging.log("info", "Empty mod created", mod_id=mod_id)
        return entry

    def list_files(self, mod_id: str) -> list[dict[str, object]]:
        root = self._editable_mod_root(mod_id)
        records: list[dict[str, object]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name == self.METADATA_FILENAME:
                continue
            if "__pycache__" in path.parts or ".git" in path.parts:
                continue
            if not self._is_supported_mod_file(path):
                continue
            records.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size})
        return records

    def read_file(self, mod_id: str, relative_path: str) -> str:
        return self._safe_mod_file(mod_id, relative_path, must_exist=True).read_text(encoding="utf-8", errors="ignore")

    def write_file(self, mod_id: str, relative_path: str, content: str) -> None:
        target = self._safe_mod_file(mod_id, relative_path, must_exist=False)
        validate_general_script_content(target, content)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._refresh_general_scripts(mod_id)
        self.merge.rebuild()

    def delete_file(self, mod_id: str, relative_path: str) -> None:
        target = self._safe_mod_file(mod_id, relative_path, must_exist=True)
        target.unlink()
        self._refresh_general_scripts(mod_id)
        self.merge.rebuild()

    def install(self, mod_id: str) -> InstalledMod:
        item = next(entry for entry in self.fetch_index() if entry.id == mod_id)
        target_dir = self.storage.paths.mods_dir / mod_id
        target_dir.mkdir(parents=True, exist_ok=True)
        payload_path = target_dir / "payload.json"
        if not payload_path.exists():
            self.storage.write_json(
                payload_path,
                {
                    "rules": [f"{mod_id}-rule"],
                    "metadata": {"installed_from": item.source_url},
                },
            )

        installed = self.list_installed()
        existing = next((entry for entry in installed if entry.id == mod_id), None)
        if existing:
            existing.version = item.version
            existing.path = str(target_dir)
            result = existing
        else:
            result = InstalledMod(id=mod_id, version=item.version, path=str(target_dir), enabled=False)
            installed.append(result)

        self.storage.write_json(self._installed_path, [asdict(entry) for entry in installed])
        self.logging.log("info", "Mod installed", mod_id=mod_id, version=item.version)
        return result

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
            raise KeyError(f"Unknown modifications: {', '.join(sorted(missing))}")
        self.storage.write_json(self._installed_path, [asdict(item) for item in installed])
        enabled_ids = {item.id for item in installed if item.enabled}
        self.settings.update(enabled_mod_ids=sorted(enabled_ids))
        self.merge.rebuild()
        self.logging.log("info", "Mod states changed", mod_ids=changed, count=len(changed))
        return installed

    def remove(self, mod_id: str) -> None:
        installed = [item for item in self.list_installed() if item.id != mod_id]
        self.storage.write_json(self._installed_path, [asdict(item) for item in installed])
        enabled_ids = {item.id for item in installed if item.enabled}
        self.settings.update(enabled_mod_ids=sorted(enabled_ids))
        target_dir = self.storage.paths.mods_dir / mod_id
        if target_dir.exists():
            self.storage.create_backup(target_dir, "pre-remove-mod")
            shutil.rmtree(target_dir)
        self.merge.rebuild()
        self.logging.log("info", "Mod removed", mod_id=mod_id)

    def export_mod(self, mod_id: str, target_dir: str) -> Path:
        entry = next(item for item in self.list_installed() if item.id == mod_id)
        source_dir = Path(entry.path)
        if not source_dir.exists():
            raise FileNotFoundError(f"Modification path not found: {source_dir}")
        destination = Path(target_dir)
        if destination.suffix.lower() == ".zip":
            destination.parent.mkdir(parents=True, exist_ok=True)
            zip_path = destination
        else:
            destination.mkdir(parents=True, exist_ok=True)
            zip_path = destination / f"{entry.id}-{entry.version or __version__}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in source_dir.rglob("*"):
                if path.name == "__pycache__" or ".git" in path.parts:
                    continue
                if path.is_dir():
                    continue
                if path.name == self.METADATA_FILENAME:
                    continue
                if not self._is_supported_mod_file(path):
                    continue
                archive.write(path, path.relative_to(source_dir))
            archive.writestr(self.METADATA_FILENAME, self._metadata_json(entry))
        self.logging.log("info", "Mod exported", mod_id=mod_id, target=str(zip_path))
        return zip_path

    def import_from_path(self, source_path: str) -> InstalledMod:
        return self.import_from_paths([source_path])

    def import_from_paths(self, source_paths: list[str], suggested_name: str | None = None) -> InstalledMod:
        valid_sources = [Path(item) for item in source_paths if item]
        if not valid_sources:
            raise ValueError("Nothing was selected for import.")

        for source in valid_sources:
            if not source.exists():
                raise FileNotFoundError(f"Path not found: {source}")

        with tempfile.TemporaryDirectory(prefix="zapret_hub_mod_") as temp_dir:
            staged_root = Path(temp_dir) / "staged"
            staged_root.mkdir(parents=True, exist_ok=True)
            for source in valid_sources:
                self._stage_source_for_import(source, staged_root)

            fallback_name = suggested_name or next((item.stem if item.is_file() else item.name for item in valid_sources), "mod")
            return self._import_staged_bundle(staged_root, suggested_name=fallback_name)

    def import_from_github(self, repo_url: str) -> InstalledMod:
        owner, repo, api_url = self._normalize_github_repo(repo_url)
        if owner.lower() == "flowseal" and repo.lower() == "zapret-discord-youtube":
            raise ValueError("Оригинальный репозиторий Flowseal уже встроен в приложение и не может быть добавлен как модификация.")

        self.logging.log("info", "GitHub mod import started", repo=repo, owner=owner)
        repo_info = self.github.github_json(api_url, timeout=15, purpose="github-mod-metadata")
        if not isinstance(repo_info, dict):
            raise ValueError("GitHub repository metadata is invalid.")

        zip_url = str(repo_info.get("zipball_url") or "").strip()
        repo_name = str(repo_info.get("name") or repo).strip() or repo
        description = str(repo_info.get("description") or "").strip()
        author = str((repo_info.get("owner") or {}).get("login") or owner).strip() or owner
        if not zip_url:
            raise ValueError("GitHub repository metadata does not contain a zipball URL.")

        with tempfile.TemporaryDirectory(prefix="zapret_hub_github_") as temp_dir:
            zip_path = Path(temp_dir) / f"{repo_name}.zip"
            self.github.github_download(zip_url, zip_path, timeout=30, purpose="github-mod-download")
            return self._import_from_github_zip(zip_path, repo_name, author, description, repo_url)

    def _import_from_github_zip(
        self,
        zip_path: Path,
        repo_name: str,
        author: str,
        description: str,
        repo_url: str,
    ) -> InstalledMod:
        with tempfile.TemporaryDirectory(prefix="zapret_hub_github_unzip_") as temp_dir:
            temp_root = Path(temp_dir) / "unzipped"
            temp_root.mkdir(parents=True, exist_ok=True)
            self._extract_zip_filtered(zip_path, temp_root)
            entry = self._import_staged_bundle(
                temp_root,
                suggested_name=repo_name,
                display_name=repo_name,
                author=author,
                description=description,
                source_url=repo_url,
            )
        return entry

    def _import_staged_bundle(
        self,
        staged_root: Path,
        *,
        suggested_name: str,
        display_name: str | None = None,
        author: str = UNKNOWN_AUTHOR,
        description: str = "",
        source_url: str = "",
    ) -> InstalledMod:
        metadata = self._read_staged_metadata(staged_root)
        if metadata:
            suggested_name = str(metadata.get("name") or suggested_name)
            display_name = str(metadata.get("name") or display_name or suggested_name)
            author = str(metadata.get("author") or author or self.UNKNOWN_AUTHOR)
            description = str(metadata.get("description") or description)
            source_url = str(metadata.get("source_url") or source_url)
        general_sources, list_sources, bin_sources, utils_sources = self._collect_import_candidates(staged_root)
        general_scripts = self._dedupe_general_names(sorted(general_sources))
        if bin_sources and not self._bin_sources_are_modified(bin_sources):
            bin_sources = {}
        if not general_scripts and not list_sources and not bin_sources:
            raise ValueError(
                "Не найдено ни одного совместимого general-файла, списка или измененного bin. Добавьте .bat-конфиг, .txt-листы Zapret или модифицированный bin."
            )

        mod_id = self._unique_mod_id(suggested_name)
        target_dir = self.storage.paths.mods_dir / mod_id
        self._materialize_mod_bundle(
            target_dir=target_dir,
            general_sources={name: general_sources[name] for name in general_scripts if name in general_sources},
            list_sources=list_sources,
            bin_sources=bin_sources,
            utils_sources=utils_sources,
        )

        installed = self.list_installed()
        entry = InstalledMod(
            id=mod_id,
            version=str(metadata.get("version") or datetime.utcnow().strftime("%Y.%m.%d")) if metadata else datetime.utcnow().strftime("%Y.%m.%d"),
            path=str(target_dir),
            name=display_name or suggested_name,
            author=author or self.UNKNOWN_AUTHOR,
            description=description or self._build_bundle_description(general_scripts, list_sources),
            source_url=source_url,
            enabled=True,
            source_type="zapret_bundle",
            general_scripts=general_scripts,
            emoji="🪄" if mod_id == "unified-by-goshkow" else random.choice(self._EMOJI_CHOICES),
        )
        installed.insert(0, entry)
        self.storage.write_json(self._installed_path, [asdict(item) for item in installed])
        self._write_mod_metadata_file(entry)

        enabled_ids = {item.id for item in installed if item.enabled}
        self.settings.update(enabled_mod_ids=sorted(enabled_ids))
        self.merge.rebuild()
        self.logging.log("info", "Zapret bundle imported", mod_id=mod_id, path=str(target_dir), generals=general_scripts, source=source_url or "local")
        return entry

    def _build_bundle_description(self, general_scripts: list[str], list_sources: dict[str, list[Path]]) -> str:
        parts: list[str] = []
        if general_scripts:
            parts.append(f"General: {len(general_scripts)}")
        if list_sources:
            parts.append(f"Lists: {len(list_sources)}")
        return " | ".join(parts)

    def _metadata_json(self, entry: InstalledMod) -> str:
        payload = {
            "schema": "zapret-hub-mod-v1",
            "id": entry.id,
            "name": entry.name or entry.id,
            "description": entry.description,
            "author": entry.author or self.UNKNOWN_AUTHOR,
            "version": entry.version,
            "source_url": entry.source_url,
            "source_type": entry.source_type,
            "emoji": entry.emoji,
        }
        import json

        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _write_mod_metadata_file(self, entry: InstalledMod) -> None:
        root = Path(entry.path)
        if not root.exists():
            return
        (root / self.METADATA_FILENAME).write_text(self._metadata_json(entry), encoding="utf-8")

    def _read_staged_metadata(self, root: Path) -> dict[str, object]:
        for candidate in root.rglob(self.METADATA_FILENAME):
            if not candidate.is_file():
                continue
            try:
                import json

                payload = json.loads(candidate.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}
        return {}

    def _editable_mod_root(self, mod_id: str) -> Path:
        if mod_id == "unified-by-goshkow":
            raise ValueError("Hub is bundled and cannot be edited.")
        entry = next(item for item in self.list_installed() if item.id == mod_id)
        root = Path(entry.path)
        if not root.exists():
            raise FileNotFoundError(f"Modification path not found: {root}")
        return root

    def _safe_mod_file(self, mod_id: str, relative_path: str, *, must_exist: bool) -> Path:
        root = self._editable_mod_root(mod_id).resolve()
        rel = str(relative_path or "").strip().replace("\\", "/")
        if not self._is_supported_mod_path(rel):
            raise ValueError("Modification files can only be .txt, .ps1, .bat, or safe bin/*.bin files.")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise ValueError("Invalid modification file path.")
        target = (root / rel).resolve()
        if root not in target.parents and target != root:
            raise ValueError("Modification file path escapes the mod folder.")
        if must_exist and not target.exists():
            raise FileNotFoundError(f"Modification file not found: {rel}")
        return target

    def _refresh_general_scripts(self, mod_id: str) -> None:
        installed = self.list_installed()
        entry = next(item for item in installed if item.id == mod_id)
        root = Path(entry.path)
        entry.general_scripts = sorted(
            script.name for script in root.glob("*.bat") if script.is_file() and not script.name.lower().startswith("service")
        )
        self.storage.write_json(self._installed_path, [asdict(item) for item in installed])

    def _materialize_mod_bundle(
        self,
        *,
        target_dir: Path,
        general_sources: dict[str, Path],
        list_sources: dict[str, list[Path]],
        bin_sources: dict[str, Path],
        utils_sources: dict[str, Path],
    ) -> None:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        lists_target = target_dir / "lists"
        utils_target = target_dir / "utils"
        lists_target.mkdir(parents=True, exist_ok=True)
        utils_target.mkdir(parents=True, exist_ok=True)

        for name, script in general_sources.items():
            shutil.copy2(script, target_dir / name)

        for name, source in utils_sources.items():
            shutil.copy2(source, utils_target / name)

        for name, sources in list_sources.items():
            merged: list[str] = []
            seen: set[str] = set()
            for source in sources:
                for raw in source.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = raw.strip()
                    if not line or line in seen:
                        continue
                    seen.add(line)
                    merged.append(line)
            (lists_target / name).write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")

        if bin_sources:
            bin_target = target_dir / "bin"
            bin_target.mkdir(parents=True, exist_ok=True)
            for name, source in bin_sources.items():
                shutil.copy2(source, bin_target / name)

    def _stage_source_for_import(self, source: Path, staged_root: Path) -> None:
        if source.is_dir():
            target = staged_root / source.name
            if target.exists():
                target = staged_root / f"{source.name}_{datetime.utcnow().strftime('%H%M%S%f')}"
            self._copy_tree_filtered(source, target)
            return

        if source.suffix.lower() == ".zip":
            unpack_dir = staged_root / f"{source.stem}_{datetime.utcnow().strftime('%H%M%S%f')}"
            unpack_dir.mkdir(parents=True, exist_ok=True)
            self._extract_zip_filtered(source, unpack_dir)
            return

        if self._is_supported_mod_file(source):
            shutil.copy2(source, staged_root / source.name)

    def _collect_import_candidates(self, root: Path) -> tuple[dict[str, Path], dict[str, list[Path]], dict[str, Path], dict[str, Path]]:
        general_sources: dict[str, Path] = {}
        list_sources: dict[str, list[Path]] = {}
        bin_sources: dict[str, Path] = {}
        utils_sources: dict[str, Path] = {}

        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if not self._is_supported_mod_file(file_path):
                continue
            lowered = file_path.name.lower()
            suffix = file_path.suffix.lower()
            parent_lower = file_path.parent.name.lower()

            if parent_lower == "bin" and suffix in self.BIN_SUFFIXES:
                bin_sources.setdefault(file_path.name, file_path)
                continue

            if suffix == ".bat" and not lowered.startswith("service"):
                if lowered not in general_sources:
                    general_sources[file_path.name] = file_path
                continue

            if suffix == ".txt":
                if lowered.startswith(("readme", "license", "changelog")):
                    continue
                if parent_lower == "lists" or lowered.startswith(("list-", "ipset", "hosts")):
                    list_sources.setdefault(file_path.name, []).append(file_path)
                    continue
                if self._looks_like_runtime_list(file_path):
                    list_sources.setdefault(file_path.name, []).append(file_path)
                    continue

            if suffix == ".ps1" or parent_lower == "utils":
                utils_sources.setdefault(file_path.name, file_path)

        return general_sources, list_sources, bin_sources, utils_sources

    def _is_supported_mod_file(self, path: Path) -> bool:
        if path.name == self.METADATA_FILENAME:
            return True
        if path.parent.name.lower() == "bin" and path.suffix.lower() in self.BIN_SUFFIXES:
            return True
        return path.suffix.lower() in self.ALLOWED_MOD_SUFFIXES

    def _is_supported_mod_path(self, relative_path: str) -> bool:
        path = Path(str(relative_path or "").replace("\\", "/"))
        if path.name == self.METADATA_FILENAME:
            return False
        if "bin" in [part.lower() for part in path.parts] and path.suffix.lower() in self.BIN_SUFFIXES:
            return True
        return path.suffix.lower() in self.ALLOWED_MOD_SUFFIXES

    def _copy_tree_filtered(self, source: Path, target: Path) -> None:
        for file_path in source.rglob("*"):
            if not file_path.is_file() or not self._is_supported_mod_file(file_path):
                continue
            if "__pycache__" in file_path.parts or ".git" in file_path.parts:
                continue
            rel = file_path.relative_to(source)
            destination = target / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, destination)

    def _extract_zip_filtered(self, source: Path, target: Path) -> None:
        with zipfile.ZipFile(source, "r") as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                rel = Path(member.filename.replace("\\", "/"))
                if rel.is_absolute() or ".." in rel.parts:
                    continue
                if rel.name != self.METADATA_FILENAME and not self._is_supported_mod_path(rel.as_posix()):
                    continue
                destination = target / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _looks_like_runtime_list(self, file_path: Path) -> bool:
        try:
            sample = file_path.read_text(encoding="utf-8", errors="ignore")[:4096]
        except Exception:
            return False
        if not sample.strip():
            return False
        return any(marker in sample.lower() for marker in (".com", ".gg", ".ru", ".net", "/", ":"))

    def _bin_sources_are_modified(self, bin_sources: dict[str, Path]) -> bool:
        base_bin = self.storage.paths.runtime_dir / "zapret-discord-youtube" / "bin"
        if not base_bin.exists():
            return bool(bin_sources)
        for name, source in bin_sources.items():
            base_file = base_bin / name
            if not base_file.exists():
                return True
            try:
                if source.stat().st_size != base_file.stat().st_size:
                    return True
                if source.read_bytes() != base_file.read_bytes():
                    return True
            except Exception:
                return True
        return False

    def _dedupe_general_names(self, names: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for name in names:
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(name)
        return result

    def _normalize_github_repo(self, repo_url: str) -> tuple[str, str, str]:
        raw = repo_url.strip()
        if not raw:
            raise ValueError("Ссылка на GitHub пустая.")
        if raw.endswith(".git"):
            raw = raw[:-4]
        parsed = urlparse(raw)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("Поддерживаются только обычные ссылки на GitHub-репозитории.")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("Не удалось распознать owner/repo в ссылке GitHub.")
        owner, repo = parts[0], parts[1]
        return owner, repo, f"https://api.github.com/repos/{owner}/{repo}"

    def _detect_zapret_bundle_root(self, root: Path) -> Path:
        if self._looks_like_zapret_bundle(root):
            return root
        for child in root.iterdir():
            if child.is_dir() and self._looks_like_zapret_bundle(child):
                return child
        raise ValueError("Selected source does not look like a zapret bundle (service.bat/bin/lists not found).")

    def _looks_like_zapret_bundle(self, path: Path) -> bool:
        return (path / "service.bat").exists() and (path / "bin").is_dir() and (path / "lists").is_dir()

    def _scan_general_scripts(self, bundle_root: Path, skip_base_duplicates: bool = False) -> list[str]:
        scripts: list[str] = []
        base_names = self._base_general_names() if skip_base_duplicates else set()
        for script in bundle_root.glob("*.bat"):
            name = script.name.lower()
            if name.startswith("service"):
                continue
            if name in base_names:
                continue
            scripts.append(script.name)
        return sorted(scripts)

    def _base_general_names(self) -> set[str]:
        base_root = self.storage.paths.runtime_dir / "zapret-discord-youtube"
        names: set[str] = set()
        if not base_root.exists():
            return names
        for script in base_root.glob("*.bat"):
            lowered = script.name.lower()
            if lowered.startswith("service"):
                continue
            names.add(lowered)
        return names

    def _cleanup_installed_duplicate_generals(self) -> None:
        installed = self.list_installed()
        changed = False
        for item in installed:
            if item.source_type != "zapret_bundle":
                continue
            bundle = Path(item.path)
            if not bundle.exists():
                continue
            normalized = sorted(
                {
                    script.name
                    for script in bundle.glob("*.bat")
                    if script.is_file() and not script.name.lower().startswith("service")
                }
            )
            if sorted(item.general_scripts) != normalized:
                item.general_scripts = normalized
                changed = True
        if changed:
            self.storage.write_json(self._installed_path, [asdict(item) for item in installed])

    def _unique_mod_id(self, name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower() or "mod"
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"{slug}-{stamp}"
