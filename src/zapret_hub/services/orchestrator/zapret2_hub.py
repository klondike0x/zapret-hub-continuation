from __future__ import annotations

import json
from pathlib import Path
import shutil

from zapret_hub.services.service_rules import SERVICE_RULES


LIST_HUB = "list-hub.txt"
LIST_AUTO = "list-auto.txt"
LIST_EXCLUDE = "list-exclude.txt"
IPSET_HUB = "ipset-hub.txt"
LUA_ORCHESTRATOR = "hub-orchestrator.lua"
LUA_STRATEGY = "hub-strategy.lua"
LUA_TARGETS = "hub-targets.lua"

# Curated strategy ids — rewritten into hub-strategy.lua; winws2 restart required.
# balanced/multisplit = Flowseal-safe Discord TLS; syndata = youtubediscord Default v5.
STRATEGY_IDS = ("balanced", "fake_heavy", "multisplit", "syndata")

# Seed lists adapted from Flowseal zapret-discord-youtube + Hub catalogs.
# In real winws2 filtering uses hostlist/ipset files; Lua keeps the same catalog for docs/sync.

# Flowseal list-general Discord section (ported for Zapret2 hostlists).
FLOWSEAL_DISCORD_DOMAINS: tuple[str, ...] = (
    # Flowseal list-general + youtubediscord/zapret2-youtube-discord lists/discord.txt
    "dis.gd",
    "discord-attachments-uploads-prd.storage.googleapis.com",
    "discord.app",
    "discord.co",
    "discord.com",
    "discord.design",
    "discord.dev",
    "discord.gift",
    "discord.gifts",
    "discord.gg",
    "discord.media",
    "discord.me",
    "discord.new",
    "discord.st",
    "discord.store",
    "discord.status",
    "discord.tools",
    "discord-activities.com",
    "discordactivities.com",
    "discordapp.com",
    "discordapp.io",
    "discordapp.net",
    "discordcdn.com",
    "discordmerch.com",
    "discordpartygames.com",
    "discords.com",
    "discordsays.com",
    "discordsez.com",
    "discordstatus.com",
    "cdn.discordapp.com",
    "media.discordapp.net",
    "gateway.discord.gg",
    "updates.discord.com",
    "status.discord.com",
    "latency.discord.media",
    "dl.discordapp.net",
    "stable.dl2.discordapp.net",
    "images-ext-1.discordapp.net",
    "images-ext-2.discordapp.net",
)

# youtubediscord/zapret2-youtube-discord lists/youtube.txt (core).
YOUTUBE_SEED_DOMAINS: tuple[str, ...] = (
    "youtube.com",
    "youtubekids.com",
    "youtu.be",
    "yt.be",
    "ytimg.com",
    "googlevideo.com",
    "youtube-nocookie.com",
    "ggpht.com",
    "gvt1.com",
    "youtube.googleapis.com",
    "youtubei.googleapis.com",
    "youtubeembeddedplayer.googleapis.com",
    "yt3.googleusercontent.com",
    "lh3.googleusercontent.com",
    "manifest.googlevideo.com",
    "redirector.googlevideo.com",
    "jnn-pa.googleapis.com",
    "youtube-ui.l.google.com",
    "yt-video-upload.l.google.com",
    "wide-youtube.l.google.com",
    "ytimg.l.google.com",
    "googleadservices.com",
)

BYPASS_SEED_DOMAINS: tuple[str, ...] = (
    # Discord (Flowseal + youtubediscord lists)
    *FLOWSEAL_DISCORD_DOMAINS,
    # YouTube / Google video
    *YOUTUBE_SEED_DOMAINS,
    # Common companions
    "instagram.com",
    "cdninstagram.com",
    "twitch.tv",
    "jtvnw.net",
    "telegram.org",
    "t.me",
    "web.telegram.org",
    "tiktok.com",
    "tiktokcdn.com",
)

BYPASS_SEED_NETWORKS: tuple[str, ...] = (
    "149.154.167.0/24",  # Telegram
    "173.194.0.0/16",  # Google/YouTube
    # Do NOT seed Discord Cloudflare CIDR (162.159.128.0/20): ipset desync on that
    # range breaks Discord updates — same rule as classic Zapret / cutover Auto.
)

# bol-van / Flowseal Discord capture (WinDivert + profile filters).
DISCORD_MEDIA_TCP_PORTS = "2053,2083,2087,2096,8443"
DISCORD_VOICE_UDP_PORTS = "19294-19344,50000-50100"
DISCORD_HOSTLIST_DOMAINS = ",".join(FLOWSEAL_DISCORD_DOMAINS)

# Cloudflare parent that covers Discord CDN. ipset desync on these ranges
# breaks Discord HTTPS/updates (Flowseal + Hub classic already strip them).
DISCORD_BREAKING_IPSETS: frozenset[str] = frozenset(
    {
        "162.158.0.0/15",
        "162.159.128.0/20",
    }
)
DISCORD_IPSET_EXCLUDE_IP = "162.158.0.0/15,162.159.128.0/20"

_HUB_ORCHESTRATOR_LUA = r'''--[[
  Zapret Hub orchestrator Lua for winws2 (bol-van zapret2).

  Discord / YouTube stack combines:
    - Flowseal zapret-discord-youtube (voice UDP ACTIVE_DISCORD_UDP ×6, media multisplit)
    - youtubediscord/zapret2-youtube-discord Default v5 (send+syndata for Discord TLS,
      googlevideo multisplit sniext, youtube tls_max fake+multidisorder)
    - bol-van official IP discovery (zero fake ×2)

  Strategy (HUB_STRATEGY) switches Discord TLS / YouTube helpers:
    balanced   → Flowseal Discord TLS (multisplit) + Flowseal voice  [default/safe]
    multisplit → same Flowseal Discord TLS helpers
    syndata    → youtubediscord Default v5 send+syndata Discord TLS
    fake_heavy → general ALT style fake+fakedsplit (tcp_ts)
]]

HUB_ORCHESTRATOR_VERSION = 5

local function _strategy()
  return (HUB_STRATEGY and tostring(HUB_STRATEGY)) or "balanced"
end

local function _ensure_arg(desync)
  if type(desync.arg) ~= "table" then
    desync.arg = {}
  end
  return desync.arg
end

function hub_tls(ctx, desync)
  local arg = _ensure_arg(desync)
  local s = _strategy()
  if s == "fake_heavy" then
    arg.blob = arg.blob or "tls_google"
    arg.tcp_md5 = ""
    arg.repeats = arg.repeats or 11
    arg.tls_mod = arg.tls_mod or "rnd,dupsid,rndsni"
    return fake(ctx, desync)
  elseif s == "multisplit" then
    arg.pos = arg.pos or "1"
    arg.seqovl = arg.seqovl or "681"
    arg.seqovl_pattern = arg.seqovl_pattern or "tls_google"
    return multisplit(ctx, desync)
  end
  arg.blob = arg.blob or "tls_google"
  arg.tcp_md5 = ""
  arg.tcp_ts = arg.tcp_ts or "-10000"
  arg.repeats = arg.repeats or 6
  arg.tls_mod = arg.tls_mod or "rnd,rndsni,dupsid"
  return fake(ctx, desync)
end

function hub_tls_b(ctx, desync)
  local arg = _ensure_arg(desync)
  local s = _strategy()
  if s == "fake_heavy" then
    arg.pos = arg.pos or "1,midsld"
    return multidisorder(ctx, desync)
  elseif s == "multisplit" then
    arg.blob = arg.blob or "tls_google"
    arg.tcp_md5 = ""
    arg.tls_mod = arg.tls_mod or "rnd,dupsid"
    return fake(ctx, desync)
  end
  arg.pos = arg.pos or "1"
  arg.seqovl = arg.seqovl or "681"
  arg.seqovl_pattern = arg.seqovl_pattern or "tls_google"
  return multisplit(ctx, desync)
end

function hub_http(ctx, desync)
  local arg = _ensure_arg(desync)
  local s = _strategy()
  if s == "fake_heavy" then
    arg.blob = arg.blob or "fake_default_http"
    arg.tcp_md5 = ""
    arg.repeats = arg.repeats or 6
    return fake(ctx, desync)
  elseif s == "multisplit" then
    arg.pos = arg.pos or "1"
    return multisplit(ctx, desync)
  end
  arg.blob = arg.blob or "fake_default_http"
  arg.tcp_md5 = ""
  return fake(ctx, desync)
end

function hub_http_b(ctx, desync)
  local arg = _ensure_arg(desync)
  if _strategy() == "fake_heavy" then
    arg.tcp_md5 = ""
    return fakedsplit(ctx, desync)
  end
  arg.blob = arg.blob or "fake_default_http"
  arg.tcp_md5 = ""
  return fake(ctx, desync)
end

function hub_quic(ctx, desync)
  local arg = _ensure_arg(desync)
  local s = _strategy()
  arg.blob = arg.blob or "quic_google"
  if s == "fake_heavy" then
    arg.repeats = arg.repeats or 11
  else
    arg.repeats = arg.repeats or 6
  end
  return fake(ctx, desync)
end

-- Flowseal voice: dpi-desync-fake-discord=ACTIVE_DISCORD_UDP.bin repeats=6
-- Registered as --blob=discord_udp=@ACTIVE_DISCORD_UDP.bin; fallback quic_google.
function hub_discord(ctx, desync)
  local arg = _ensure_arg(desync)
  arg.blob = arg.blob or "discord_udp"
  arg.repeats = arg.repeats or 6
  return fake(ctx, desync)
end

-- bol-van official IP-discovery-only (50-discord-media / preset2).
function hub_discord_ipdisc(ctx, desync)
  local arg = _ensure_arg(desync)
  arg.blob = arg.blob or "0x00000000000000000000000000000000"
  arg.repeats = arg.repeats or 2
  return fake(ctx, desync)
end

-- Flowseal discord.media: multisplit ONLY (seqovl=681, pos=1, google TLS pattern).
function hub_discord_media(ctx, desync)
  local arg = _ensure_arg(desync)
  arg.pos = arg.pos or "1"
  arg.seqovl = arg.seqovl or "681"
  arg.seqovl_pattern = arg.seqovl_pattern or "tls_google"
  return multisplit(ctx, desync)
end

-- Community (#131) extra fake before/after media multisplit when strategy is aggressive.
function hub_discord_media_fake(ctx, desync)
  local arg = _ensure_arg(desync)
  arg.blob = arg.blob or "tls_google"
  arg.tcp_ts = arg.tcp_ts or "-10000"
  arg.tcp_seq = arg.tcp_seq or "400"
  arg.repeats = arg.repeats or 8
  return fake(ctx, desync)
end

-- Flowseal Discord HTTPS (list-general path): multisplit with 4pda pattern (seqovl=568).
function hub_discord_https(ctx, desync)
  local arg = _ensure_arg(desync)
  arg.pos = arg.pos or "1"
  arg.seqovl = arg.seqovl or "568"
  arg.seqovl_pattern = arg.seqovl_pattern or "tls_4pda"
  return multisplit(ctx, desync)
end

-- youtubediscord Default v5 / general ALT Discord TLS helpers (used when strategy flips).
function hub_discord_fake_ts(ctx, desync)
  local arg = _ensure_arg(desync)
  arg.blob = arg.blob or "tls_google"
  arg.tcp_ts = arg.tcp_ts or "-600000"
  arg.repeats = arg.repeats or 6
  return fake(ctx, desync)
end

function hub_discord_fakedsplit(ctx, desync)
  local arg = _ensure_arg(desync)
  arg.pattern = arg.pattern or "0x00"
  arg.tcp_ts = arg.tcp_ts or "-600000"
  arg.repeats = arg.repeats or 6
  return fakedsplit(ctx, desync)
end

-- YouTube (youtubediscord Default v5): fake tls_max + multidisorder seqovl=681.
function hub_youtube(ctx, desync)
  local arg = _ensure_arg(desync)
  local s = _strategy()
  if s == "multisplit" then
    arg.pos = arg.pos or "1"
    arg.seqovl = arg.seqovl or "681"
    arg.seqovl_pattern = arg.seqovl_pattern or "tls_google"
    return multisplit(ctx, desync)
  elseif s == "fake_heavy" then
    arg.blob = arg.blob or "tls_google"
    arg.tcp_ts = arg.tcp_ts or "-600000"
    arg.repeats = arg.repeats or 6
    return fake(ctx, desync)
  end
  arg.blob = arg.blob or "tls_max"
  arg.badsum = true
  arg.repeats = arg.repeats or 8
  return fake(ctx, desync)
end

function hub_youtube_b(ctx, desync)
  local arg = _ensure_arg(desync)
  local s = _strategy()
  if s == "fake_heavy" then
    arg.pattern = arg.pattern or "0x00"
    arg.tcp_ts = arg.tcp_ts or "-600000"
    arg.repeats = arg.repeats or 6
    return fakedsplit(ctx, desync)
  elseif s == "multisplit" then
    return hub_tls_b(ctx, desync)
  end
  arg.pos = arg.pos or "1"
  arg.seqovl = arg.seqovl or "681"
  arg.seqovl_pattern = arg.seqovl_pattern or "tls_max"
  return multidisorder(ctx, desync)
end

-- googlevideo.com (Default v5): multisplit at sniext+1 / midsld.
function hub_googlevideo(ctx, desync)
  local arg = _ensure_arg(desync)
  local s = _strategy()
  if s == "fake_heavy" then
    arg.blob = arg.blob or "tls_google"
    arg.tcp_ts = arg.tcp_ts or "-600000"
    arg.repeats = arg.repeats or 6
    return fake(ctx, desync)
  end
  arg.pos = arg.pos or "sniext+1,midsld"
  arg.seqovl = arg.seqovl or "652"
  return multisplit(ctx, desync)
end
'''


def zapret2_lists_dir(configs_dir: Path) -> Path:
    return Path(configs_dir) / "zapret2"


def ensure_zapret2_lists(configs_dir: Path) -> dict[str, Path]:
    root = zapret2_lists_dir(configs_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "hub": root / LIST_HUB,
        "auto": root / LIST_AUTO,
        "exclude": root / LIST_EXCLUDE,
        "ipset": root / IPSET_HUB,
        "lua_orch": root / LUA_ORCHESTRATOR,
        "lua_strategy": root / LUA_STRATEGY,
        "lua_targets": root / LUA_TARGETS,
    }
    for key in ("hub", "auto", "exclude", "ipset"):
        path = paths[key]
        if not path.exists():
            path.write_text("", encoding="utf-8")
    write_hub_orchestrator_lua(paths["lua_orch"])
    write_hub_targets_lua(paths["lua_targets"])
    return paths


def _list_entries(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return set()
    return {
        row.strip().lower()
        for row in lines
        if row.strip() and not row.lstrip().startswith("#")
    }


def missing_domains(configs_dir: Path, domains: list[str]) -> list[str]:
    paths = ensure_zapret2_lists(configs_dir)
    existing = _list_entries(paths["hub"]) | _list_entries(paths["auto"])
    out: list[str] = []
    seen: set[str] = set()
    for item in domains:
        key = str(item or "").strip().lower().rstrip(".")
        if not key or key in seen or key in existing:
            continue
        seen.add(key)
        out.append(key)
    return out


def missing_ips(configs_dir: Path, ips: list[str]) -> list[str]:
    paths = ensure_zapret2_lists(configs_dir)
    existing = _list_entries(paths["ipset"])
    out: list[str] = []
    seen: set[str] = set()
    for item in ips:
        key = str(item or "").strip()
        if not key or key.lower() in seen or key.lower() in existing:
            continue
        seen.add(key.lower())
        out.append(key)
    return out


def hub_lists_initialized(configs_dir: Path, *, min_domains: int = 5) -> bool:
    paths = ensure_zapret2_lists(configs_dir)
    return len(_list_entries(paths["hub"])) >= min_domains


def write_hub_orchestrator_lua(path: Path, *, force: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    desired = _HUB_ORCHESTRATOR_LUA.lstrip("\n")
    if not force and path.exists():
        try:
            if path.read_text(encoding="utf-8") == desired:
                return path
        except Exception:
            pass
        # Refresh generated copies when the Lua API contract changes.
        try:
            current = path.read_text(encoding="utf-8", errors="ignore")
            if (
                "HUB_ORCHESTRATOR_VERSION = 5" in current
                and "function hub_tls" in current
                and "function hub_discord" in current
                and "function hub_discord_media" in current
                and "function hub_discord_https" in current
                and "function hub_youtube" in current
                and "function hub_googlevideo" in current
            ):
                return path
        except Exception:
            pass
    path.write_text(desired, encoding="utf-8")
    return path


def write_hub_targets_lua(path: Path, *, force: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not force and path.exists():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Refresh when Flowseal Discord catalog markers are missing.
            if (
                "HUB_TARGET_DOMAINS" in text
                and "HUB_TARGET_NETWORKS" in text
                and "discordapp.io" in text
                and "youtubekids.com" in text
                and "stable.dl2.discordapp.net" in text
            ):
                return path
        except Exception:
            pass
    domain_lines = ",\n    ".join(f'"{d}"' for d in BYPASS_SEED_DOMAINS)
    net_lines = ",\n    ".join(f'"{n}"' for n in BYPASS_SEED_NETWORKS)
    path.write_text(
        "-- Generated by Zapret Hub from bypass-youtube-discord.lua catalogs.\n"
        "-- Matching is done via hostlist/ipset files; this table is for Lua helpers/debug.\n"
        "HUB_TARGET_DOMAINS = {\n"
        f"    {domain_lines}\n"
        "}\n"
        "HUB_TARGET_NETWORKS = {\n"
        f"    {net_lines}\n"
        "}\n",
        encoding="utf-8",
    )
    return path


def write_hub_strategy_lua(configs_dir: Path, strategy_id: str) -> Path:
    sid = strategy_id if strategy_id in STRATEGY_IDS else "balanced"
    paths = ensure_zapret2_lists(configs_dir)
    path = paths["lua_strategy"]
    path.write_text(
        "-- Generated by Zapret Hub orchestrator. Do not edit by hand.\n"
        f'HUB_STRATEGY = "{sid}"\n',
        encoding="utf-8",
    )
    return path


def prepare_zapret2_runtime_files(configs_dir: Path, strategy_id: str) -> dict[str, Path]:
    paths = ensure_zapret2_lists(configs_dir)
    write_hub_orchestrator_lua(paths["lua_orch"], force=False)
    write_hub_targets_lua(paths["lua_targets"])
    write_hub_strategy_lua(configs_dir, strategy_id)
    sanitize_zapret2_discord_ipset(configs_dir)
    return paths


def _append_unique(path: Path, lines: list[str]) -> list[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if path.exists():
        existing = [row.rstrip() for row in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
    seen = {row.strip().lower() for row in existing if row.strip() and not row.lstrip().startswith("#")}
    added: list[str] = []
    for line in lines:
        key = line.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        existing.append(line.strip())
        added.append(line.strip())
    if added:
        path.write_text("\n".join(existing) + ("\n" if existing else ""), encoding="utf-8")
    return added


def add_domains(configs_dir: Path, domains: list[str]) -> list[str]:
    """Service / seed domains → permanent hub list (kept in Manual)."""
    paths = ensure_zapret2_lists(configs_dir)
    cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
    return _append_unique(paths["hub"], cleaned)


def add_auto_domains(configs_dir: Path, domains: list[str], *, reason: str = "learn") -> list[str]:
    """Auto-learned domains → overlay diff (never mutates list-hub battle copy)."""
    from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

    cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
    return AutoOverlayStore(configs_dir).add_domains(cleaned, reason=reason)


def add_ips(configs_dir: Path, ips: list[str]) -> list[str]:
    paths = ensure_zapret2_lists(configs_dir)
    cleaned = [
        item.strip()
        for item in ips
        if item and item.strip() and item.strip().lower() not in DISCORD_BREAKING_IPSETS
    ]
    added = _append_unique(paths["ipset"], cleaned)
    strip_discord_breaking_ipsets(paths["ipset"])
    return added


def add_auto_ips(configs_dir: Path, ips: list[str], *, reason: str = "learn") -> list[str]:
    from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

    cleaned = [item.strip() for item in ips if item and item.strip()]
    return AutoOverlayStore(configs_dir).add_ips(cleaned, reason=reason)


def exclude_domains(configs_dir: Path, domains: list[str]) -> list[str]:
    paths = ensure_zapret2_lists(configs_dir)
    cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
    return _append_unique(paths["exclude"], cleaned)


def exclude_auto_domains(configs_dir: Path, domains: list[str], *, reason: str = "over_block") -> list[str]:
    from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

    cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
    return AutoOverlayStore(configs_dir).exclude_domains(cleaned, reason=reason)


def materialize_auto_lists(configs_dir: Path, target_dir: Path) -> dict[str, Path]:
    """Materialize zapret2 lists with Auto overlay applied (runtime copy only)."""
    from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore
    from zapret_hub.services.orchestrator.learner import strip_auto_overlay

    src = ensure_zapret2_lists(configs_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for key in ("hub", "exclude", "ipset", "auto", "lua_orch", "lua_strategy", "lua_targets"):
        source = src[key]
        dest = target_dir / source.name
        if key in {"hub", "exclude", "ipset"}:
            text = ""
            if source.exists():
                try:
                    text = strip_auto_overlay(source.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    text = ""
            dest.write_text(text, encoding="utf-8")
        elif key == "auto":
            dest.write_text("", encoding="utf-8")
        else:
            if source.exists():
                try:
                    dest.write_text(source.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
                except Exception:
                    dest.write_text("", encoding="utf-8")
            else:
                dest.write_text("", encoding="utf-8")
        out[key] = dest
    # Apply Auto overlay into the runtime copy (hub/exclude/ipset/auto views).
    store = AutoOverlayStore(configs_dir)
    # Map classic apply onto zapret2 filenames via a fake lists dir layout.
    lists_view = target_dir / "_classic_view"
    lists_view.mkdir(parents=True, exist_ok=True)
    (lists_view / "list-general-user.txt").write_text("", encoding="utf-8")
    (lists_view / "list-exclude-user.txt").write_text("", encoding="utf-8")
    (lists_view / "ipset-all-user.txt").write_text("", encoding="utf-8")
    # Seed view from hub/exclude/ipset so removals can hit service-adjacent user rows.
    try:
        (lists_view / "list-general.txt").write_text(out["hub"].read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        (lists_view / "list-exclude.txt").write_text(out["exclude"].read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        (lists_view / "ipset-all.txt").write_text(out["ipset"].read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    except Exception:
        pass
    store.apply_to_lists_dir(lists_view)
    # Fold classic-view Auto adds into zapret2 files.
    try:
        auto_domains = [
            row.strip()
            for row in (lists_view / "list-general-user.txt").read_text(encoding="utf-8", errors="ignore").splitlines()
            if row.strip() and not row.lstrip().startswith("#")
        ]
        auto_excludes = [
            row.strip()
            for row in (lists_view / "list-exclude-user.txt").read_text(encoding="utf-8", errors="ignore").splitlines()
            if row.strip() and not row.lstrip().startswith("#")
        ]
        auto_ips = [
            row.strip()
            for row in (lists_view / "ipset-all-user.txt").read_text(encoding="utf-8", errors="ignore").splitlines()
            if row.strip() and not row.lstrip().startswith("#")
        ]
        # Removals already applied to list-general/ipset views — write back.
        out["hub"].write_text((lists_view / "list-general.txt").read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        out["exclude"].write_text(
            (lists_view / "list-exclude.txt").read_text(encoding="utf-8", errors="ignore"),
            encoding="utf-8",
        )
        out["ipset"].write_text((lists_view / "ipset-all.txt").read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        if auto_domains:
            _append_unique(out["auto"], auto_domains)
        if auto_excludes:
            _append_unique(out["exclude"], auto_excludes)
        if auto_ips:
            _append_unique(out["ipset"], auto_ips)
    except Exception:
        pass
    return out


def materialize_manual_lists(configs_dir: Path, target_dir: Path) -> dict[str, Path]:
    """Copy zapret2 lists for Manual start without Auto-learned overlays."""
    from zapret_hub.services.orchestrator.learner import strip_auto_overlay

    src = ensure_zapret2_lists(configs_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for key in ("hub", "exclude", "ipset", "auto", "lua_orch", "lua_strategy", "lua_targets"):
        source = src[key]
        dest = target_dir / source.name
        if key in {"hub", "exclude", "ipset"}:
            text = ""
            if source.exists():
                try:
                    text = strip_auto_overlay(source.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    text = ""
            dest.write_text(text, encoding="utf-8")
        elif key == "auto":
            # Manual never feeds hostlist-auto; keep an empty stub for path stability.
            dest.write_text("", encoding="utf-8")
        else:
            if source.exists():
                try:
                    dest.write_text(source.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
                except Exception:
                    dest.write_text("", encoding="utf-8")
            else:
                dest.write_text("", encoding="utf-8")
        out[key] = dest
    return out


def seed_bypass_catalog(configs_dir: Path, *, only_missing: bool = True) -> dict[str, list[str]]:
    """Append bypass-youtube-discord.lua catalogs without wiping existing entries."""
    domains = list(BYPASS_SEED_DOMAINS)
    ips = list(BYPASS_SEED_NETWORKS)
    if only_missing:
        domains = missing_domains(configs_dir, domains)
        ips = missing_ips(configs_dir, ips)
    return {
        "domains": add_domains(configs_dir, domains) if domains else [],
        "ips": add_ips(configs_dir, ips) if ips else [],
    }


def seed_service_lists(
    configs_dir: Path, service_ids: list[str], *, only_missing: bool = True
) -> dict[str, list[str]]:
    domains = harvest_service_domains(service_ids)
    ips = harvest_service_ips(service_ids, include_bypass_seeds=True)
    if only_missing:
        domains = missing_domains(configs_dir, domains)
        ips = missing_ips(configs_dir, ips)
    return {
        "domains": add_domains(configs_dir, domains) if domains else [],
        "ips": add_ips(configs_dir, ips) if ips else [],
    }


def harvest_service_domains(service_ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    extras = list(BYPASS_SEED_DOMAINS) if any(s in {"youtube", "discord"} for s in service_ids) else []
    for service_id in service_ids:
        rule = SERVICE_RULES.get(service_id)
        items = list(rule.list_general or ()) + list(rule.list_google or ()) if rule else []
        for item in items:
            host = str(item).strip().lower().rstrip(".")
            if not host or host in seen:
                continue
            seen.add(host)
            out.append(host)
    for host in extras:
        key = host.strip().lower().rstrip(".")
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def harvest_service_ips(service_ids: list[str], *, include_bypass_seeds: bool = False) -> list[str]:
    """Collect service IP catalogs.

    Classic Zapret must not seed Discord/YouTube CDN CIDRs into ipset-all*: that
    enables a second 443 desync on top of hostlists and breaks Discord updates.
    Zapret2 hub lists can still take non-Discord BYPASS_SEED_NETWORKS via include_bypass_seeds.
    """
    out: list[str] = []
    seen: set[str] = set()
    selected = {str(item) for item in service_ids}
    # Always drop Discord-breaking Cloudflare parents when Discord is in the set
    # (or when seeding the YT/Discord bypass catalog).
    ban = set(DISCORD_BREAKING_IPSETS) if ("discord" in selected or include_bypass_seeds) else set()
    extras = (
        list(BYPASS_SEED_NETWORKS)
        if include_bypass_seeds and any(s in {"youtube", "discord"} for s in selected)
        else []
    )
    for service_id in service_ids:
        rule = SERVICE_RULES.get(service_id)
        if rule is None:
            continue
        # Discord is hostlist-only — never harvest its identity CDN into ipset.
        if str(service_id) == "discord":
            continue
        for item in rule.ipset_all or ():
            value = str(item).strip()
            if not value or value in seen:
                continue
            if value.lower() in ban:
                continue
            # Cloudflare + Discord: same parent-range kill as classic Zapret.
            if "discord" in selected and str(service_id) == "cloudflare":
                if value.lower() in DISCORD_BREAKING_IPSETS:
                    continue
            seen.add(value)
            out.append(value)
    for value in extras:
        if value not in seen and value.lower() not in ban:
            seen.add(value)
            out.append(value)
    return out


def strip_discord_breaking_ipsets(*paths: Path) -> int:
    """Remove Cloudflare/Discord CDN parents from ipset files. Returns removed count."""
    ban = {item.lower() for item in DISCORD_BREAKING_IPSETS}
    removed = 0
    for path in paths:
        if path is None or not Path(path).is_file():
            continue
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        kept: list[str] = []
        changed = 0
        for line in lines:
            key = line.strip().lower()
            if key and not key.startswith("#") and key in ban:
                changed += 1
                continue
            kept.append(line.rstrip())
        if changed:
            Path(path).write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            removed += changed
    return removed


def sanitize_zapret2_discord_ipset(configs_dir: Path, *, runtime_dir: Path | None = None) -> int:
    """Keep Discord hostlist-only under Zapret2: scrub breaking CIDRs from hub ipsets."""
    configs = Path(configs_dir)
    paths: list[Path] = []
    try:
        paths.append(ensure_zapret2_lists(configs)["ipset"])
    except Exception:
        paths.append(configs / "zapret2" / IPSET_HUB)
    if runtime_dir is not None:
        root = Path(runtime_dir) / "zapret2"
        paths.extend(
            [
                root / "lists_auto" / IPSET_HUB,
                root / "lists_manual" / IPSET_HUB,
            ]
        )
    return strip_discord_breaking_ipsets(*paths)


def sanitize_classic_discord_pollution(configs_dir: Path) -> dict[str, int]:
    """Strip Auto-seeded CDN CIDRs and protected service hosts from battle lists.

    Older Hub builds wrote BYPASS_SEED_NETWORKS into ipset-all-user.txt and could
    exclude discord.com after failed probes — both break Discord HTTPS vs 2.1.2.
    Also scrubs Zapret2 ipset-hub.txt (Cloudflare 162.158.0.0/15 covers Discord).
    """
    from zapret_hub.services.orchestrator.auto_overlay import is_service_protected_host
    from zapret_hub.services.service_rules import AUTO_DEFAULT_SERVICE_IDS

    configs = Path(configs_dir)
    removed_ips = 0
    removed_excludes = 0

    # Classic user overlay: stock service CIDRs must not live in ipset-all-user.
    classic_ban = {str(item).strip().lower() for item in BYPASS_SEED_NETWORKS}
    classic_ban |= {str(item).strip().lower() for item in DISCORD_BREAKING_IPSETS}
    for rule in SERVICE_RULES.values():
        for item in getattr(rule, "identity_networks", ()) or ():
            classic_ban.add(str(item).strip().lower())
    for sid in AUTO_DEFAULT_SERVICE_IDS:
        rule = SERVICE_RULES.get(sid)
        if rule is None:
            continue
        for item in rule.ipset_all or ():
            classic_ban.add(str(item).strip().lower())
        for _name, entries in rule.extra_lists or ():
            if "ipset" in str(_name).lower():
                for item in entries:
                    classic_ban.add(str(item).strip().lower())

    for ipset_path in (configs / "ipset-all-user.txt", configs / "ipset-all.txt"):
        if not ipset_path.is_file():
            continue
        try:
            lines = ipset_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        kept: list[str] = []
        changed = 0
        for line in lines:
            key = line.strip().lower()
            if key and not key.startswith("#") and key in classic_ban:
                changed += 1
                continue
            kept.append(line.rstrip())
        if changed:
            ipset_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            removed_ips += changed

    # Zapret2 hub: only Discord-breaking Cloudflare parents (keep other CF ranges).
    removed_ips += sanitize_zapret2_discord_ipset(configs)

    exclude_paths = [configs / "list-exclude-user.txt", configs / "list-exclude.txt"]
    try:
        exclude_paths.append(ensure_zapret2_lists(configs)["exclude"])
    except Exception:
        pass
    for exclude_path in exclude_paths:
        if not Path(exclude_path).is_file():
            continue
        try:
            lines = Path(exclude_path).read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        kept_ex: list[str] = []
        changed = 0
        for line in lines:
            host = line.strip().lower().rstrip(".")
            if host and not host.startswith("#") and is_service_protected_host(host):
                changed += 1
                continue
            kept_ex.append(line.rstrip())
        if changed:
            Path(exclude_path).write_text("\n".join(kept_ex) + ("\n" if kept_ex else ""), encoding="utf-8")
            removed_excludes += changed

    return {"ips": removed_ips, "excludes": removed_excludes}


def bundle_winws_root(winws2_path: Path) -> Path:
    return Path(winws2_path).resolve().parent


def zapret2_asset_roots(winws2_path: Path | None = None, runtime_root: Path | None = None) -> list[Path]:
    """Roots that may contain lua/ and windivert filters (release + win-bundle layouts)."""
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = Path(path).resolve()
        except OSError:
            resolved = Path(path)
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    if winws2_path is not None:
        parent = Path(winws2_path).resolve().parent
        add(parent)
        # Official release: .../binaries/windows-x86_64/winws2.exe → tree root
        if parent.name.lower() in {"windows-x86_64", "win64", "windows"} and parent.parent.name.lower() == "binaries":
            add(parent.parent.parent)
        # Win-bundle: .../zapret-winws/winws2.exe → bundle root one level up
        if parent.name.lower() == "zapret-winws":
            add(parent.parent)
    add(runtime_root)
    return roots


def _filter_file(asset_roots: Path | list[Path], name: str) -> Path | None:
    roots = asset_roots if isinstance(asset_roots, list) else [asset_roots]
    for root in roots:
        for candidate in (
            Path(root) / "windivert.filter" / name,
            Path(root) / "init.d" / "windivert.filter.examples" / name,
            Path(root) / "zapret-winws" / "windivert.filter" / name,
        ):
            if candidate.is_file():
                return candidate
    return None


def _fake_file(asset_roots: Path | list[Path], name: str) -> Path | None:
    roots = asset_roots if isinstance(asset_roots, list) else [asset_roots]
    for root in roots:
        for candidate in (
            Path(root) / "files" / "fake" / name,
            Path(root) / "fake" / name,
            Path(root) / "zapret-winws" / "files" / "fake" / name,
            Path(root) / "bin" / name,  # Flowseal zapret-discord-youtube/bin
            Path(root) / name,
        ):
            if candidate.is_file():
                return candidate
    return None


def _winws2_blob_path(path: Path) -> str:
    """Format a filesystem path for winws2 --blob name:@file.

    Docs: ``--blob=<item_name>:[+ofs]@<filename>|0xHEX``.
    The first ``:`` separates name from value, so Windows ``C:\\...`` after a wrong
    ``name=@C:\\...`` (equals) was parsed as identifier ``name=@C``. Use colon
    syntax and prefer ``/cygdrive/<drive>/...`` so the value itself has no ``:``.
    """
    resolved = Path(path).resolve()
    try:
        drive = resolved.drive  # e.g. "C:"
        if len(drive) == 2 and drive[1] == ":":
            rest = resolved.as_posix()
            # "C:/Users/..." → "/cygdrive/c/Users/..."
            if rest[1:3] == ":/":
                return f"/cygdrive/{drive[0].lower()}{rest[2:]}"
            # Fallback: strip drive and join
            parts = resolved.parts
            if parts:
                return "/cygdrive/" + drive[0].lower() + "/" + "/".join(parts[1:])
    except Exception:
        pass
    return resolved.as_posix()


def _blob_args(
    asset_roots: Path | list[Path],
    *,
    flowseal_bin: Path | None = None,
) -> list[str]:
    """Register named blobs (bol-van: ``--blob=name:@file``).

    Includes Flowseal ACTIVE_DISCORD_UDP.bin as discord_udp and 4pda TLS pattern.
    """
    roots: list[Path] = []
    if flowseal_bin is not None:
        roots.append(Path(flowseal_bin))
    if isinstance(asset_roots, list):
        roots.extend(asset_roots)
    else:
        roots.append(asset_roots)

    mapping = (
        ("quic_google", "quic_initial_www_google_com.bin"),
        ("quic2", "quic_2.bin"),
        ("tls_google", "tls_clienthello_www_google_com.bin"),
        ("tls_4pda", "tls_clienthello_4pda_to.bin"),
        ("tls_max", "tls_clienthello_max_ru.bin"),
        ("discord_udp", "ACTIVE_DISCORD_UDP.bin"),
        ("fake_stun", "stun.bin"),
        ("stun_pat", "stun.bin"),
    )
    out: list[str] = []
    for blob_name, filename in mapping:
        path = _fake_file(roots, filename)
        if path is not None:
            out.append(f"--blob={blob_name}:@{_winws2_blob_path(path)}")
    # If Flowseal Discord UDP missing, voice still works via quic_google alias below
    # in profile lua (hub_discord falls back only if discord_udp registered — ensure
    # a second registration of discord_udp → quic bin when ACTIVE_* absent).
    if not any(item.startswith("--blob=discord_udp:") for item in out):
        quic = _fake_file(roots, "quic_initial_www_google_com.bin")
        if quic is not None:
            out.append(f"--blob=discord_udp:@{_winws2_blob_path(quic)}")
    if not any(item.startswith("--blob=tls_4pda:") for item in out):
        google = _fake_file(roots, "tls_clienthello_www_google_com.bin")
        if google is not None:
            out.append(f"--blob=tls_4pda:@{_winws2_blob_path(google)}")
    if not any(item.startswith("--blob=tls_max:") for item in out):
        google = _fake_file(roots, "tls_clienthello_www_google_com.bin")
        if google is not None:
            out.append(f"--blob=tls_max:@{_winws2_blob_path(google)}")
    if not any(item.startswith("--blob=quic2:") for item in out):
        quic = _fake_file(roots, "quic_initial_www_google_com.bin")
        if quic is not None:
            out.append(f"--blob=quic2:@{_winws2_blob_path(quic)}")
    return out


def _strip_port_tokens(ports: str, drop: str) -> str:
    """Remove comma-separated port tokens from a ports string (keep order)."""
    drop_set = {part.strip() for part in str(drop or "").split(",") if part.strip()}
    kept: list[str] = []
    seen: set[str] = set()
    for part in str(ports or "").split(","):
        token = part.strip()
        if not token or token in drop_set or token in seen:
            continue
        seen.add(token)
        kept.append(token)
    return ",".join(kept) if kept else "80,443"


def find_bundle_lua(asset_roots: Path | list[Path], filename: str) -> Path | None:
    roots = asset_roots if isinstance(asset_roots, list) else [asset_roots]
    for root in roots:
        for candidate in (
            Path(root) / "lua" / filename,
            Path(root) / filename,
            Path(root) / "zapret-winws" / "lua" / filename,
        ):
            if candidate.is_file():
                return candidate
    return None


def build_default_profile_args(
    *,
    lists: dict[str, Path],
    asset_roots: Path | list[Path] | None = None,
    bundle_root: Path | None = None,
    tcp_ports: str,
    strategy_id: str = "balanced",
    include_hostlist_auto: bool = True,
    flowseal_bin: Path | None = None,
) -> list[str]:
    """Filter/desync profiles; lua-init files must already be on the command line.

    Discord/YouTube stack =
      Flowseal voice + youtubediscord Default v5 Discord TLS/YouTube + bol-van IP disc.

    Profiles (order matters — first match wins):
      1) IP discovery (zero fake)
      2) Flowseal voice UDP (ACTIVE_DISCORD_UDP ×6)
      3) updates.discord.com + discord.media + Discord hostlist (syndata / multisplit / fake)
      4) googlevideo.com + youtube hostlist domains
      5) General HTTP/TLS/QUIC (Discord CDN parents excluded from ipset)
    """
    strategy = (strategy_id or "balanced").strip() or "balanced"
    aggressive = strategy == "fake_heavy"
    # Default balanced stays Flowseal-safe (starts reliably). Opt into syndata explicitly.
    use_syndata = strategy == "syndata"
    use_multisplit_discord = strategy in {"balanced", "multisplit"}
    roots: list[Path]
    if asset_roots is not None:
        roots = asset_roots if isinstance(asset_roots, list) else [asset_roots]
    elif bundle_root is not None:
        roots = [bundle_root]
    else:
        roots = []
    hub = str(lists["hub"])
    auto = str(lists["auto"])
    exclude = str(lists["exclude"])
    ipset = str(lists["ipset"])
    hostlist_args = [
        f"--hostlist={hub}",
        f"--hostlist-exclude={exclude}",
        f"--ipset={ipset}",
        f"--ipset-exclude-ip={DISCORD_IPSET_EXCLUDE_IP}",
    ]
    if include_hostlist_auto:
        hostlist_args.insert(1, f"--hostlist-auto={auto}")
    auto_args = (
        [
            "--hostlist-auto-fail-threshold=2",
            "--hostlist-auto-fail-time=60",
        ]
        if include_hostlist_auto
        else []
    )

    general_tcp = _strip_port_tokens(tcp_ports, DISCORD_MEDIA_TCP_PORTS)
    if "443" not in general_tcp.split(","):
        general_tcp = _strip_port_tokens(f"{general_tcp},443", "")

    # Discord media ports + 443 for HTTPS profiles (youtubediscord Default v5).
    discord_tcp = f"80,443,{DISCORD_MEDIA_TCP_PORTS}"
    youtube_domains = ",".join(YOUTUBE_SEED_DOMAINS)

    args: list[str] = [
        # youtubediscord Default v5 cache knobs (helps syndata/hostname Discord path).
        "--ctrack-disable=0",
        "--ipcache-lifetime=8400",
        "--ipcache-hostname=1",
    ]
    args.extend(_blob_args(roots, flowseal_bin=flowseal_bin))
    for name in (
        "windivert_part.discord_media.txt",
        "windivert_part.stun.txt",
        "windivert_part.quic_initial_ietf.txt",
        "windivert_part.wireguard.txt",
    ):
        path = _filter_file(roots, name)
        if path is not None:
            args.append(f"--wf-raw-part=@{path}")

    def _discord_tls_desyncs() -> list[str]:
        if use_syndata:
            # Default v5: send ×3 + syndata(tls_google) + syndata
            return [
                "--lua-desync=send:repeats=3",
                "--lua-desync=syndata:blob=tls_google",
                "--ipcache-hostname",
                "--lua-desync=syndata",
            ]
        if use_multisplit_discord:
            return ["--lua-desync=hub_discord_https"]
        return [
            "--lua-desync=hub_discord_fake_ts",
            "--lua-desync=hub_discord_fakedsplit",
        ]

    def _discord_media_desyncs() -> list[str]:
        if use_syndata:
            return [
                "--lua-desync=send:repeats=3",
                "--lua-desync=syndata:blob=tls_google",
                "--ipcache-hostname",
                "--lua-desync=syndata",
            ]
        if use_multisplit_discord:
            out = []
            if aggressive:
                out.append("--lua-desync=hub_discord_media_fake")
            out.append("--lua-desync=hub_discord_media")
            return out
        return [
            "--lua-desync=hub_discord_fake_ts",
            "--lua-desync=hub_discord_fakedsplit",
        ]

    # --- Discord + YouTube FIRST, then general ---
    args.extend(
        [
            # 1) bol-van / youtubediscord IP discovery.
            "--filter-l7=discord,stun",
            "--payload=discord_ip_discovery,stun",
            "--lua-desync=hub_discord_ipdisc",
            "--new",
            # 2) Flowseal voice UDP — ACTIVE_DISCORD_UDP ×6 (all discord/stun on voice ports).
            f"--filter-udp={DISCORD_VOICE_UDP_PORTS}",
            "--filter-l7=discord,stun",
            "--lua-desync=hub_discord",
            "--new",
            # 3) updates.discord.com (youtubediscord Default v5 dedicated profile).
            "--filter-tcp=443",
            "--filter-l7=tls",
            "--hostlist-domains=updates.discord.com",
            "--out-range=-d10",
            "--payload=tls_client_hello",
            *_discord_tls_desyncs(),
            "--new",
            # 4) discord.media (+ media TCP ports).
            f"--filter-tcp={discord_tcp}",
            "--filter-l7=tls",
            "--hostlist-domains=discord.media",
            "--out-range=-d10",
            "--payload=tls_client_hello",
            *_discord_media_desyncs(),
            "--new",
            # 5) Remaining Discord HTTPS hostlist-domains.
            "--filter-tcp=443",
            "--filter-l7=tls",
            f"--hostlist-domains={DISCORD_HOSTLIST_DOMAINS}",
            "--out-range=-d10",
            "--payload=tls_client_hello",
            *_discord_tls_desyncs(),
            "--new",
            # 6) googlevideo.com (Default v5 multisplit sniext).
            "--filter-tcp=80,443",
            "--filter-l7=tls",
            "--hostlist-domains=googlevideo.com",
            "--out-range=-d8",
            "--payload=tls_client_hello",
            "--lua-desync=hub_googlevideo",
            "--new",
            # 7) YouTube hostlist domains (Default v5 tls_max / strategy variants).
            "--filter-tcp=80,443",
            "--filter-l7=tls",
            f"--hostlist-domains={youtube_domains}",
            "--out-range=-d8",
            "--payload=tls_client_hello",
            "--lua-desync=hub_youtube",
            "--lua-desync=hub_youtube_b",
            "--new",
            # 8) General HTTP
            "--filter-tcp=80",
            "--filter-l7=http",
            *hostlist_args,
            *auto_args,
            "--out-range=-d10",
            "--payload=http_req",
            "--lua-desync=hub_http",
            "--lua-desync=hub_http_b",
            "--new",
            # 9) General TLS (no Discord media ports; CDN parents excluded from ipset).
            f"--filter-tcp={general_tcp}",
            "--filter-l7=tls",
            *hostlist_args,
            *auto_args,
            "--out-range=-d10",
            "--payload=tls_client_hello",
            "--lua-desync=hub_tls",
            "--lua-desync=hub_tls_b",
            "--new",
            # 10) QUIC
            "--filter-udp=443",
            "--filter-l7=quic",
            *hostlist_args,
            *auto_args,
            "--payload=quic_initial",
            "--lua-desync=hub_quic",
            "--new",
            # 11) WireGuard
            "--filter-l7=wireguard",
            "--payload=wireguard_initiation,wireguard_cookie",
            "--lua-desync=fake:blob=0x00000000000000000000000000000000:repeats=2",
        ]
    )
    return args


def next_strategy_id(current: str) -> str:
    current = (current or "balanced").strip() or "balanced"
    if current not in STRATEGY_IDS:
        return STRATEGY_IDS[0]
    idx = STRATEGY_IDS.index(current)
    return STRATEGY_IDS[(idx + 1) % len(STRATEGY_IDS)]


def describe_strategy(strategy_id: str, *, language: str = "ru") -> str:
    labels = {
        "balanced": ("Сбалансированная Lua", "Balanced Lua"),
        "fake_heavy": ("Агрессивный fake", "Aggressive fake"),
        "multisplit": ("Multisplit Lua", "Multisplit Lua"),
        "syndata": ("Syndata Discord (YT/DC)", "Syndata Discord (YT/DC)"),
    }
    ru, en = labels.get(strategy_id, (strategy_id, strategy_id))
    return ru if str(language).startswith("ru") else en


def strategy_generals() -> list[dict[str, str]]:
    return [
        {"id": sid, "bundle_id": "zapret2", "name": describe_strategy(sid, language="en")}
        for sid in STRATEGY_IDS
    ]


_MOD_OVERLAY_START = "# --- zapret-hub-mod-overlays ---"
_MOD_OVERLAY_END = "# --- end zapret-hub-mod-overlays ---"
_ACTIVE_MOD_PROFILE = "active-mod-profile.json"


def find_mod_profile(mod_root: Path) -> Path | None:
    """Find the default profile used by a complete Zapret2 package."""
    root = Path(mod_root)
    for candidate in (
        root / "profiles" / "general.txt",
        root / "profiles" / "Default v5.txt",
        root / "general.txt",
    ):
        if candidate.is_file():
            return candidate.resolve()
    profiles = root / "profiles"
    if profiles.is_dir():
        candidates = sorted(
            (
                path
                for path in profiles.glob("*.txt")
                if path.is_file() and ("general" in path.stem.lower() or "default" in path.stem.lower())
            ),
            key=lambda path: path.name.lower(),
        )
        if candidates:
            return candidates[0].resolve()
    return None


def active_mod_profile(configs_dir: Path) -> Path | None:
    marker = zapret2_lists_dir(configs_dir) / _ACTIVE_MOD_PROFILE
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        profile = Path(str(payload.get("profile") or "")).resolve()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return profile if profile.is_file() else None


_PROFILE_FILE_OPTIONS = {
    "--hostlist",
    "--hostlist-exclude",
    "--hostlist-auto",
    "--ipset",
    "--ipset-exclude",
    "--ipset-auto",
}


def build_mod_profile_args(profile: Path) -> list[str]:
    """Parse a winws2 profile and resolve package-relative asset paths."""
    profile = Path(profile).resolve()
    root = profile.parent.parent if profile.parent.name.lower() == "profiles" else profile.parent
    root = root.resolve()

    def resolve_asset(raw: str) -> str:
        relative = raw.lstrip("@").replace("\\", "/")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError(f"Zapret2 profile references a path outside its package: {raw}") from error
        if not candidate.is_file():
            raise FileNotFoundError(f"Zapret2 profile asset is missing: {relative}")
        return str(candidate)

    args: list[str] = []
    for raw_line in profile.read_text(encoding="utf-8-sig", errors="strict").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("--"):
            raise ValueError(f"Unsupported Zapret2 profile line: {line}")
        option, separator, value = line.partition("=")
        if separator:
            if value.startswith("@"):
                value = f"@{resolve_asset(value)}"
            elif option in _PROFILE_FILE_OPTIONS:
                value = resolve_asset(value)
            elif option == "--blob" and ":@" in value:
                blob_name, asset = value.split(":@", 1)
                value = f"{blob_name}:@{resolve_asset(asset)}"
            line = f"{option}={value}"
        args.append(line)
    if not args:
        raise ValueError(f"Zapret2 profile is empty: {profile}")
    return args


def _strip_mod_overlay(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == _MOD_OVERLAY_START:
            skipping = True
            continue
        if stripped == _MOD_OVERLAY_END:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "\n".join(out).rstrip() + ("\n" if out else "")


def _collect_mod_list_lines(mod_root: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (domains, excludes, ips) from a Zapret2 mod folder."""
    domains: list[str] = []
    excludes: list[str] = []
    ips: list[str] = []
    lists_dir = mod_root / "lists"
    roots = [lists_dir] if lists_dir.is_dir() else []
    roots.append(mod_root)
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.txt")):
            name = path.name.lower()
            try:
                rows = [
                    row.strip()
                    for row in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if row.strip() and not row.lstrip().startswith("#")
                ]
            except Exception:
                continue
            if "exclude" in name:
                excludes.extend(rows)
            elif "ipset" in name or name.startswith("ip"):
                ips.extend(rows)
            else:
                domains.extend(rows)
    return domains, excludes, ips


def merge_mod_overlays(configs_dir: Path, mod_roots: list[Path]) -> dict[str, object]:
    """Merge enabled Zapret2 mod lists/lua into Hub configs/zapret2 (separate from classic)."""
    paths = ensure_zapret2_lists(configs_dir)
    all_domains: list[str] = []
    all_excludes: list[str] = []
    all_ips: list[str] = []
    seen_d: set[str] = set()
    seen_e: set[str] = set()
    seen_i: set[str] = set()
    lua_copied: list[str] = []
    selected_profile: Path | None = None

    mod_lua_root = paths["hub"].parent / "mod_lua"
    if mod_lua_root.exists():
        shutil.rmtree(mod_lua_root, ignore_errors=True)
    mod_lua_root.mkdir(parents=True, exist_ok=True)

    for mod_root in mod_roots:
        root = Path(mod_root)
        if not root.is_dir():
            continue
        if selected_profile is None:
            selected_profile = find_mod_profile(root)
        domains, excludes, ips = _collect_mod_list_lines(root)
        for item in domains:
            key = item.lower()
            if key in seen_d:
                continue
            seen_d.add(key)
            all_domains.append(item)
        for item in excludes:
            key = item.lower()
            if key in seen_e:
                continue
            seen_e.add(key)
            all_excludes.append(item)
        for item in ips:
            key = item.lower()
            if key in seen_i:
                continue
            seen_i.add(key)
            all_ips.append(item)
        for lua in sorted(root.rglob("*.lua")):
            if not lua.is_file():
                continue
            # Keep nested paths unique and stable for --lua-init.
            rel = lua.relative_to(root).as_posix().replace("/", "__")
            target = mod_lua_root / f"{root.name}__{rel}"
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(lua.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
                lua_copied.append(str(target.name))
            except Exception:
                continue

    profile_marker = paths["hub"].parent / _ACTIVE_MOD_PROFILE
    if selected_profile is None:
        profile_marker.unlink(missing_ok=True)
    else:
        profile_marker.write_text(
            json.dumps({"profile": str(selected_profile)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _rewrite(path: Path, overlay_lines: list[str]) -> None:
        base = ""
        if path.exists():
            try:
                base = _strip_mod_overlay(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                base = ""
        if not overlay_lines:
            path.write_text(base, encoding="utf-8")
            return
        block = "\n".join([_MOD_OVERLAY_START, *overlay_lines, _MOD_OVERLAY_END, ""])
        path.write_text((base.rstrip() + "\n\n" if base.strip() else "") + block, encoding="utf-8")

    _rewrite(paths["hub"], all_domains)
    _rewrite(paths["exclude"], all_excludes)
    _rewrite(paths["ipset"], all_ips)
    return {
        "domains": len(all_domains),
        "excludes": len(all_excludes),
        "ips": len(all_ips),
        "lua": lua_copied,
        "mods": len(mod_roots),
        "profile": str(selected_profile or ""),
    }
