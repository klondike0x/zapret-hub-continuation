from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zapret_hub.services.orchestrator.noise import filter_learnable_hosts, is_infra_noise_host


@dataclass(frozen=True, slots=True)
class TunerStep:
    kind: str
    value: str
    reason: str
    label_ru: str
    label_en: str


_OVERBLOCK_SYMPTOMS = frozenset({"suspect_overblock", "tls_fail", "http_block", "tcp_timeout"})
_MISS_SYMPTOMS = frozenset({"external_miss"})
# Confirmed connectivity failures that may justify strategy cutovers (never service_detected).
_STRATEGY_SYMPTOMS = frozenset({"tcp_timeout", "tls_fail", "http_block", "suspect_overblock", "external_miss"})
# Real gaming stacks that need GameFilter / Gaming Set. Stock Discord/YouTube are
# hostlist services — Auto must not treat them as reasons to widen WinDivert.
_GAMING_SERVICES = frozenset(
    {"gaming", "fortnite", "epic-games", "ubisoft", "riot-games", "battle-net"}
)


def _is_protected_catalog_host(host: str) -> bool:
    from zapret_hub.services.service_rules import is_stock_catalog_host

    return is_stock_catalog_host(host)


def _is_stock_service(service_id: str) -> bool:
    from zapret_hub.services.service_rules import is_stock_service

    return is_stock_service(service_id)


def _mod_looks_relevant(mod: Any, *, services: list[str], process: str = "") -> bool:
    blob = " ".join(
        [
            str(getattr(mod, "id", "") or ""),
            str(getattr(mod, "name", "") or ""),
            str(getattr(mod, "description", "") or ""),
            " ".join(str(x) for x in (getattr(mod, "general_scripts", None) or [])),
        ]
    ).lower()
    process_l = (process or "").lower()
    service_set = {str(item) for item in services}
    if "fortnite" in service_set or "fortnite" in process_l:
        if any(token in blob for token in ("fortnite", "epic", "alt9", "alt 9")):
            return True
    if service_set & _GAMING_SERVICES or any(s in process_l for s in ("fortnite", "shooter", "steam", "epic")):
        if any(token in blob for token in ("gaming", "game", "fortnite", "ubisoft", "discord", "youtube", "social")):
            return True
    # Any zapret_bundle with generals is a candidate when services already enabled but failing.
    scripts = list(getattr(mod, "general_scripts", None) or [])
    source = str(getattr(mod, "source_type", "") or "")
    return bool(scripts) and source == "zapret_bundle"


def _prefer_alt9(name: str) -> int:
    lower = name.lower()
    if "alt9.1.1" in lower:
        return 0
    if "alt9.1" in lower:
        return 1
    if "alt9" in lower:
        return 2
    return 9


class SmartTuner:
    """Symptom × context × knowledge × mods ordered plan (cheap → expensive)."""

    def plan(
        self,
        *,
        symptom: str,
        domain: str = "",
        ip: str = "",
        process: str = "",
        proto: str = "",
        service_ids: list[str] | None = None,
        selected_services: set[str] | None = None,
        current: dict[str, Any] | None = None,
        knowledge_winner: dict[str, Any] | None = None,
        known_conflict: dict[str, Any] | None = None,
        ranked_generals: list[tuple[str, float]] | None = None,
        trusted_general: str = "",
        domain_in_merged: bool = False,
        max_steps: int = 8,
        winner_symptom: str = "",
        winner_app: str = "",
        installed_mods: list[Any] | None = None,
        mod_generals: list[dict[str, str]] | None = None,
        enabled_mod_ids: set[str] | None = None,
        domains: list[str] | None = None,
        ips: list[str] | None = None,
        domains_missing: list[str] | None = None,
    ) -> list[TunerStep]:
        current = current or {}
        selected = selected_services or set()
        services = list(service_ids or [])
        service_set = set(services)
        enabled_mods = enabled_mod_ids or set()
        available_mods = {
            str(getattr(item, "id", "") or ""): item
            for item in (installed_mods or [])
            if str(getattr(item, "id", "") or "")
        }
        available_mod_ids = set(available_mods)
        steps: list[TunerStep] = []
        seen: set[tuple[str, str]] = set()

        def add(step: TunerStep) -> None:
            key = (step.kind, step.value)
            if key in seen:
                return
            seen.add(key)
            steps.append(step)

        batch_domains: list[str] = []
        for item in list(domains or []) + ([domain] if domain else []):
            cleaned = str(item or "").strip().lower().rstrip(".")
            if cleaned and cleaned not in batch_domains and not is_infra_noise_host(cleaned):
                batch_domains.append(cleaned)
        batch_ips: list[str] = []
        for item in list(ips or []) + ([ip] if ip else []):
            cleaned = str(item or "").strip()
            if not cleaned:
                continue
            if "/" not in cleaned:
                cleaned = f"{cleaned}/32"
            if cleaned not in batch_ips:
                batch_ips.append(cleaned)

        # service_detected = "this app is running, enable its service once".
        # Never escalate to GameFilter / Gaming Set / mods / generals from that alone.
        detection_only = symptom == "service_detected"

        # 0) Knowledge priors only when same symptom/app context.
        use_winner = False
        if knowledge_winner and not detection_only:
            same_symptom = not winner_symptom or winner_symptom == symptom
            same_app = not winner_app or not process or winner_app.lower() in process.lower()
            use_winner = bool(same_symptom and same_app)
        if use_winner and knowledge_winner:
            for field, kind in (
                ("gaming_set", "gaming_set"),
                ("game_filter", "game_filter"),
                ("ipset", "ipset"),
                ("general", "general"),
            ):
                value = str(knowledge_winner.get(field, "") or "").strip()
                if value and value != str(current.get(kind, "") or ""):
                    add(
                        TunerStep(
                            kind=kind,
                            value=value,
                            reason="knowledge_winner",
                            label_ru="Применяю проверенную настройку",
                            label_en="Applying a known-good setting",
                        )
                    )
            for mod_id in knowledge_winner.get("mods") or []:
                if str(mod_id) in available_mod_ids and str(mod_id) not in enabled_mods:
                    add(
                        TunerStep(
                            kind="enable_mod",
                            value=str(mod_id),
                            reason=(
                                "knowledge_marketplace_mod"
                                if str(getattr(available_mods[str(mod_id)], "marketplace_slug", "") or "").strip()
                                else "knowledge_user_mod"
                            ),
                            label_ru=f"Включаю модификацию {mod_id}",
                            label_en=f"Enabling modification {mod_id}",
                        )
                    )
            for service_id in knowledge_winner.get("services") or []:
                if str(service_id) not in selected:
                    add(
                        TunerStep(
                            kind="enable_service",
                            value=str(service_id),
                            reason="knowledge_winner",
                            label_ru=f"Включаю сервис {service_id}",
                            label_en=f"Enabling service {service_id}",
                        )
                    )

        # 1) List learn — one step for all domains / all IPs (cutover writes once).
        if symptom in _MISS_SYMPTOMS or detection_only:
            if domains_missing is not None:
                to_add_domains = filter_learnable_hosts([d for d in domains_missing if d])
            elif not domain_in_merged:
                to_add_domains = list(batch_domains)
            else:
                primary = domain.strip().lower().rstrip(".") if domain else ""
                to_add_domains = [d for d in batch_domains if d != primary]
            # Dedupe while preserving order.
            seen_d: set[str] = set()
            unique_domains: list[str] = []
            for item in to_add_domains:
                if item in seen_d:
                    continue
                seen_d.add(item)
                unique_domains.append(item)
            if unique_domains:
                preview = unique_domains[0] if len(unique_domains) == 1 else f"{len(unique_domains)} доменов"
                add(
                    TunerStep(
                        kind="add_domain",
                        value="\n".join(unique_domains),
                        reason="external_miss" if not detection_only else "service_detected",
                        label_ru=f"Добавляю {preview} в списки",
                        label_en=f"Adding {preview} to lists",
                    )
                )
            # Skip random CDN IP seeding for detection / miss unless a real app failure.
            if batch_ips and not detection_only and symptom in _MISS_SYMPTOMS:
                preview_ip = batch_ips[0] if len(batch_ips) == 1 else f"{len(batch_ips)} адресов"
                add(
                    TunerStep(
                        kind="add_ip",
                        value="\n".join(batch_ips),
                        reason="external_miss",
                        label_ru=f"Добавляю {preview_ip}",
                        label_en=f"Adding {preview_ip}",
                    )
                )
        # 2) Service enable + one-shot catalog seed.
        # Stock services are already applied by Hub materialization — Auto only
        # layers NEW domains/IPs on top. Never re-seed Cloudflare CIDRs etc.
        from zapret_hub.services.orchestrator import zapret2_hub

        for service_id in services:
            just_enabled = service_id not in selected
            if just_enabled:
                add(
                    TunerStep(
                        kind="enable_service",
                        value=service_id,
                        reason="mapper",
                        label_ru=f"Включаю доступ к {service_id}",
                        label_en=f"Enabling access for {service_id}",
                    )
                )
            # Stock catalogs are frozen under Auto — skip bulk seed/re-seed.
            if _is_stock_service(service_id) and not just_enabled:
                continue
            if _is_stock_service(service_id):
                # First enable of a stock service: domains only (classic merge
                # handles lists). Skip IP harvest — Cloudflare CIDRs break Discord.
                harvested = zapret2_hub.harvest_service_domains([service_id])
                configs_hint = str(current.get("configs_dir") or "")
                if configs_hint:
                    harvested = zapret2_hub.missing_domains(Path(configs_hint), harvested)
                harvested = filter_learnable_hosts(harvested)
                if harvested:
                    preview = harvested[0] if len(harvested) == 1 else f"{len(harvested)} доменов"
                    add(
                        TunerStep(
                            kind="add_domain",
                            value="\n".join(harvested),
                            reason="service_seed",
                            label_ru=f"Добавляю каталог {service_id}: {preview}",
                            label_en=f"Seeding {service_id} catalog: {preview}",
                        )
                    )
                continue
            should_seed = just_enabled or symptom in {
                "service_detected",
                "external_miss",
                "tcp_timeout",
                "tls_fail",
                "suspect_overblock",
                "http_block",
            }
            if not should_seed:
                continue
            harvested = zapret2_hub.harvest_service_domains([service_id])
            harvested_ips = [] if detection_only else zapret2_hub.harvest_service_ips([service_id])
            configs_hint = str(current.get("configs_dir") or "")
            if configs_hint:
                harvested = zapret2_hub.missing_domains(Path(configs_hint), harvested)
                harvested_ips = zapret2_hub.missing_ips(Path(configs_hint), harvested_ips)
            harvested = filter_learnable_hosts(harvested)
            if harvested:
                preview = harvested[0] if len(harvested) == 1 else f"{len(harvested)} доменов"
                add(
                    TunerStep(
                        kind="add_domain",
                        value="\n".join(harvested),
                        reason="service_seed",
                        label_ru=f"Добавляю каталог {service_id}: {preview}",
                        label_en=f"Seeding {service_id} catalog: {preview}",
                    )
                )
            if harvested_ips:
                preview_ip = harvested_ips[0] if len(harvested_ips) == 1 else f"{len(harvested_ips)} адресов"
                add(
                    TunerStep(
                        kind="add_ip",
                        value="\n".join(harvested_ips),
                        reason="service_seed",
                        label_ru=f"Добавляю IP {service_id}: {preview_ip}",
                        label_en=f"Seeding {service_id} IPs: {preview_ip}",
                    )
                )

        if detection_only:
            return steps[: max(1, max_steps)]

        # 3) Conflict / overblock.
        if known_conflict:
            fix = str(known_conflict.get("fix_gaming_set") or known_conflict.get("gaming_set") or "").strip()
            if fix:
                add(
                    TunerStep(
                        kind="gaming_set",
                        value=fix,
                        reason="known_conflict",
                        label_ru=str(known_conflict.get("message_ru") or "Исправляю конфликт настроек"),
                        label_en=str(known_conflict.get("message_en") or "Fixing a settings conflict"),
                    )
                )

        if symptom in _OVERBLOCK_SYMPTOMS and domain and domain_in_merged:
            # Never Auto-exclude stock catalog hosts (Discord/YouTube/CF/…).
            if not _is_protected_catalog_host(domain) and not is_infra_noise_host(domain):
                add(
                    TunerStep(
                        kind="exclude_domain",
                        value=domain,
                        reason="over_block",
                        label_ru=f"Исключаю {domain} из агрессивной обработки",
                        label_en=f"Excluding {domain} from aggressive handling",
                    )
                )

        # 4) Game filter — only for real UDP/gaming failures, never for stock HTTPS.
        if proto == "udp" and (service_set & _GAMING_SERVICES or "fortnite" in service_set):
            game_mode = str(current.get("game_filter", "disabled") or "disabled")
            if game_mode in {"disabled", "tcp"}:
                add(
                    TunerStep(
                        kind="game_filter",
                        value="tcpudp" if game_mode == "tcp" else "udp",
                        reason="udp_fail",
                        label_ru="Включаю игровой режим для UDP",
                        label_en="Enabling gaming mode for UDP",
                    )
                )

        # 5) IPSet any — Fortnite only. Never widen to "any" for Discord/YouTube/CF.
        if "fortnite" in service_set and str(current.get("ipset", "loaded")) != "any":
            add(
                TunerStep(
                    kind="ipset",
                    value="any",
                    reason="coverage",
                    label_ru="Расширяю охват IP-фильтрации",
                    label_en="Widening IP filtering coverage",
                )
            )

        # 6) Gaming set priors — gaming/fortnite only, not stock Discord HTTPS.
        if (service_set & _GAMING_SERVICES) or known_conflict:
            current_set = str(current.get("gaming_set", "stun-wide-base") or "stun-wide-base")
            if proto == "udp" and current_set != "udp-first":
                add(
                    TunerStep(
                        kind="gaming_set",
                        value="udp-first",
                        reason="udp_heavy",
                        label_ru="Ставлю Gaming Set с приоритетом UDP",
                        label_en="Switching Gaming Set to UDP-first",
                    )
                )
            if current_set == "stun-wide-base" and (symptom in _OVERBLOCK_SYMPTOMS or known_conflict):
                add(
                    TunerStep(
                        kind="gaming_set",
                        value="stun-wide-base-local-exclude",
                        reason="stun_local_conflict",
                        label_ru="Пробую Gaming Set с исключением локальных сетей",
                        label_en="Trying Gaming Set with local excludes",
                    )
                )

        # 7) Enable relevant mods when services alone are not enough / already selected.
        services_already_on = bool(service_set) and service_set.issubset(selected)
        need_mods = services_already_on or symptom in _OVERBLOCK_SYMPTOMS or symptom in _MISS_SYMPTOMS
        if need_mods and installed_mods:
            for mod in installed_mods:
                mod_id = str(getattr(mod, "id", "") or "")
                if not mod_id or mod_id in enabled_mods:
                    continue
                if not _mod_looks_relevant(mod, services=services, process=process):
                    continue
                if str(getattr(mod, "source_type", "") or "") not in {"zapret_bundle", "zapret2_bundle", ""}:
                    # Prefer zapret_bundle; still allow if has general scripts.
                    if not list(getattr(mod, "general_scripts", None) or []):
                        continue
                add(
                    TunerStep(
                        kind="enable_mod",
                        value=mod_id,
                        reason=(
                            "marketplace_mod"
                            if str(getattr(mod, "marketplace_slug", "") or "").strip()
                            else "user_mod"
                        ),
                        label_ru=f"Подключаю модификацию «{getattr(mod, 'name', mod_id)}»",
                        label_en=f"Enabling modification “{getattr(mod, 'name', mod_id)}”",
                    )
                )

        # 8) Generals / Lua strategies — LAST RESORT only after lists/services, and only
        # for confirmed failure symptoms. Never chase CDN PTR noise with strategy swaps.
        allow_strategy = symptom in _STRATEGY_SYMPTOMS
        list_fix_pending = any(s.kind in {"add_domain", "add_ip"} for s in steps)
        # Soft HTTPS domain learning: lists first, strategy later if still broken.
        # UDP/gaming failures may need strategy in the same plan (Fortnite voice etc.).
        soft_list_miss = (
            symptom == "external_miss"
            and list_fix_pending
            and not domain_in_merged
            and proto != "udp"
            and not (service_set & _GAMING_SERVICES)
            and "fortnite" not in service_set
        )
        if soft_list_miss:
            allow_strategy = False
        if not allow_strategy:
            return steps[: max(1, max_steps)]

        generals: list[str] = []
        if trusted_general:
            generals.append(trusted_general)
        for general_id, _score in ranked_generals or []:
            if general_id not in generals:
                generals.append(general_id)

        mod_general_ids: list[str] = []
        for option in mod_generals or []:
            option_id = str(option.get("id") or "")
            bundle_id = str(option.get("bundle_id") or "")
            name = str(option.get("name") or "")
            if not option_id:
                continue
            # Zapret2 Lua strategies use bundle_id == "zapret2".
            if bundle_id == "zapret2":
                mod_general_ids.append(option_id)
                continue
            if bundle_id in {"base", "unified-general"}:
                if "fortnite" in service_set and "alt9" in name.lower() and bundle_id == "base":
                    mod_general_ids.append(option_id)
                continue
            if bundle_id in enabled_mods or any(
                s.kind == "enable_mod" and s.value == bundle_id for s in steps
            ):
                mod_general_ids.append(option_id)
            elif _mod_looks_relevant(
                type(
                    "M",
                    (),
                    {
                        "id": bundle_id,
                        "name": name,
                        "description": "",
                        "general_scripts": [name],
                        "source_type": "zapret_bundle",
                    },
                )(),
                services=services,
                process=process,
            ):
                mod_general_ids.append(option_id)

        mod_general_ids.sort(key=lambda gid: _prefer_alt9(gid.rsplit("|", 1)[-1]))
        for option_id in mod_general_ids:
            if option_id not in generals:
                generals.append(option_id)

        current_general = str(current.get("general", "") or "")
        added_generals = 0
        for general_id in generals:
            if not general_id or general_id == current_general:
                continue
            label = general_id.rsplit("|", 1)[-1]
            add(
                TunerStep(
                    kind="general",
                    value=general_id,
                    reason="ranked_or_mod_general",
                    label_ru=f"Пробую стратегию {label}",
                    label_en=f"Trying strategy {label}",
                )
            )
            added_generals += 1
            if added_generals >= 2:  # was 3 — fewer aimless strategy swaps
                break

        return steps[: max(1, max_steps)]


def plan_attempts(incident: dict | None = None) -> list[dict]:
    data = incident or {}
    steps = SmartTuner().plan(
        symptom=str(data.get("symptom") or "external_miss"),
        domain=str(data.get("domain") or ""),
        ip=str(data.get("ip") or ""),
        process=str(data.get("process") or ""),
        proto=str(data.get("proto") or ""),
        service_ids=list(data.get("services") or []),
    )
    return [{"kind": s.kind, "value": s.value, "reason": s.reason} for s in steps]
