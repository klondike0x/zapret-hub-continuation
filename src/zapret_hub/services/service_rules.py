from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ServiceRule:
    list_general: tuple[str, ...] = field(default_factory=tuple)
    list_exclude: tuple[str, ...] = field(default_factory=tuple)
    list_google: tuple[str, ...] = field(default_factory=tuple)
    ipset_all: tuple[str, ...] = field(default_factory=tuple)
    ipset_exclude: tuple[str, ...] = field(default_factory=tuple)
    hosts: tuple[str, ...] = field(default_factory=tuple)
    extra_lists: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)
    extra_list_files: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    bin_overlay_dir: str = ""
    winws_args: tuple[str, ...] = field(default_factory=tuple)
    test_targets: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    # Critical hosts for Auto health checks. Prefer CDN/update/API paths that can
    # fail while a marketing homepage still answers (false-green).
    health_hosts: tuple[str, ...] = field(default_factory=tuple)
    # Mapper-only CIDRs (do NOT merge into classic ipset-all.txt). Use when an IP
    # identity must prefer this service over a broader CDN rule without enabling
    # classic ipset DPI that double-handles hostlist HTTPS.
    identity_networks: tuple[str, ...] = field(default_factory=tuple)


# Stock services always present for new clients and when Auto is on.
# Telegram stays opt-in (separate TG WS Proxy path).
AUTO_DEFAULT_SERVICE_IDS: tuple[str, ...] = (
    "cloudflare",
    "discord",
    "youtube",
    "gaming",
    "clouds",
)


def host_from_target(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.upper().startswith("PING:"):
        raw = raw.split(":", 1)[1].strip()
    if "://" in raw:
        host = urlparse(raw).hostname or ""
    else:
        host = raw.split("/", 1)[0].split(":", 1)[0]
    return host.strip("[]").lower().rstrip(".")


def health_hosts_for(service_id: str) -> tuple[str, ...]:
    """Hosts that must succeed before Auto treats a service as healthy."""
    rule = SERVICE_RULES.get(service_id)
    if rule is None:
        return ()
    if rule.health_hosts:
        return rule.health_hosts
    hosts: list[str] = []
    for _name, value in rule.test_targets:
        host = host_from_target(value)
        if host and host not in hosts:
            hosts.append(host)
        if len(hosts) >= 3:
            break
    return tuple(hosts)


def merge_auto_default_services(selected: list[str] | set[str] | tuple[str, ...] | None) -> list[str]:
    """Ensure stock defaults are present; keep other selected services (e.g. Telegram)."""
    from zapret_hub.services.service_catalog import SERVICE_PRESETS

    current = [str(item).strip() for item in (selected or []) if str(item).strip()]
    merged = list(dict.fromkeys([*AUTO_DEFAULT_SERVICE_IDS, *current]))
    allowed = {preset.id for preset in SERVICE_PRESETS}
    return [item for item in merged if item in allowed]


def is_stock_service(service_id: str) -> bool:
    return str(service_id or "").strip() in AUTO_DEFAULT_SERVICE_IDS


def is_stock_catalog_host(host: str) -> bool:
    """True if host belongs to any stock service catalog (never Auto-exclude these)."""
    cleaned = (host or "").strip().lower().rstrip(".")
    if not cleaned:
        return False
    for sid in AUTO_DEFAULT_SERVICE_IDS:
        rule = SERVICE_RULES.get(sid)
        if rule is None:
            continue
        catalog = {str(x).strip().lower().rstrip(".") for x in rule.list_general if x}
        catalog |= {str(x).strip().lower().rstrip(".") for x in rule.list_google if x}
        catalog |= {str(x).strip().lower().rstrip(".") for x in rule.health_hosts if x}
        catalog |= {host_from_target(v) for _n, v in rule.test_targets if host_from_target(v)}
        if cleaned in catalog or any(cleaned == c or cleaned.endswith("." + c) for c in catalog if c):
            return True
    return False


_GAMING_LIST_FILES: tuple[tuple[str, str], ...] = (
    ("list-general.txt", "sample_data/default_services/gaming/lists/list-general.txt"),
    ("list-google.txt", "sample_data/default_services/gaming/lists/list-google.txt"),
    ("list-exclude.txt", "sample_data/default_services/gaming/lists/list-exclude.txt"),
    ("list-exclude-user.txt", "sample_data/default_services/gaming/lists/list-exclude-user.txt"),
    ("ipset-all.txt", "sample_data/default_services/gaming/lists/ipset-all.txt"),
    ("ipset-exclude.txt", "sample_data/default_services/gaming/lists/ipset-exclude.txt"),
    ("ipset-exclude-user.txt", "sample_data/default_services/gaming/lists/ipset-exclude-user.txt"),
    ("ipset-local-exclude.txt", "sample_data/default_services/gaming/lists/ipset-local-exclude.txt"),
    ("list-general-user.txt", "sample_data/default_services/gaming/lists/list-general-user.txt"),
)

_UBISOFT_LIST_FILES: tuple[tuple[str, str], ...] = (
    ("list-general.txt", "sample_data/default_services/ubisoft/lists/list-general.txt"),
    ("list-google.txt", "sample_data/default_services/ubisoft/lists/list-google.txt"),
    ("list-exclude.txt", "sample_data/default_services/ubisoft/lists/list-exclude.txt"),
    ("ipset-all.txt", "sample_data/default_services/ubisoft/lists/ipset-all.txt"),
    ("ipset-exclude.txt", "sample_data/default_services/ubisoft/lists/ipset-exclude.txt"),
)


SERVICE_RULES: dict[str, ServiceRule] = {
    "cloudflare": ServiceRule(
        list_general=(
            "cloudflare.com",
            "cloudflare-dns.com",
            "cloudflare-ech.com",
            "cloudflare-gateway.com",
            "cloudflareinsights.com",
            "cloudflarestream.com",
            "cloudflarewarp.com",
            "one.one.one.one",
        ),
        ipset_all=(
            "1.1.1.0/24",
            "1.0.0.0/24",
            "104.16.0.0/13",
            "104.24.0.0/14",
            "108.162.192.0/18",
            "131.0.72.0/22",
            "141.101.64.0/18",
            "162.158.0.0/15",
            "172.64.0.0/13",
            "173.245.48.0/20",
            "188.114.96.0/20",
            "190.93.240.0/20",
            "197.234.240.0/22",
            "198.41.128.0/17",
        ),
        test_targets=(("Cloudflare", "https://www.cloudflare.com"), ("Cloudflare DNS", "PING:1.1.1.1")),
    ),
    "discord": ServiceRule(
        list_general=(
            "discord.com",
            "discord.gg",
            "discord.media",
            "discordapp.com",
            "discordapp.net",
            "discordcdn.com",
            "discordstatus.com",
            "gateway.discord.gg",
            "cdn.discordapp.com",
            "media.discordapp.net",
            "images-ext-1.discordapp.net",
            "images-ext-2.discordapp.net",
            "dl.discordapp.net",
            "status.discord.com",
            "latency.discord.media",
            "updates.discord.com",
        ),
        # Discord first requests a signed Google Storage URL and then uploads the
        # bytes there. Keeping that hop outside of DPI avoids attachment retries
        # and a mixed Discord/GCP route during uploads.
        list_exclude=("discord-attachments-uploads-prd.storage.googleapis.com",),
        # Hostlist-only for classic Zapret (same as 2.1.2). Putting Discord CF
        # ranges into ipset-all activates a second 443 desync on top of hostlist
        # and stalls Update.exe / "Checking for updates".
        identity_networks=("162.159.128.0/20",),
        test_targets=(
            ("Discord Updates", "https://updates.discord.com"),
            ("Discord", "https://discord.com"),
            ("Discord Gateway", "https://gateway.discord.gg"),
            ("Discord CDN", "https://cdn.discordapp.com"),
        ),
        health_hosts=("updates.discord.com", "discord.com"),
    ),
    "youtube": ServiceRule(
        list_general=(
            "googlevideo.com",
            "ggpht.com",
            "gvt1.com",
            "i.ytimg.com",
            "manifest.googlevideo.com",
            "redirector.googlevideo.com",
            "video.google.com",
            "withyoutube.com",
            "youtu.be",
            "youtube.com",
            "youtube-nocookie.com",
            "youtube.googleapis.com",
            "youtubei.googleapis.com",
            "yt3.googleusercontent.com",
            "ytimg.com",
        ),
        list_google=("googlevideo.com", "ggpht.com", "gvt1.com", "youtube.com", "youtu.be", "ytimg.com"),
        test_targets=(
            ("YouTube Video Redirect", "https://redirector.googlevideo.com"),
            ("YouTube 204", "https://www.youtube.com/generate_204"),
            ("YouTube", "https://www.youtube.com"),
        ),
        health_hosts=("redirector.googlevideo.com", "www.youtube.com"),
    ),
    "telegram-desktop": ServiceRule(),
    "clouds": ServiceRule(
        list_general=(
            "amazonaws.com",
            "awsstatic.com",
            "cloudfront.net",
            "b-cdn.net",
            "bunny.net",
            "bunnycdn.com",
            "ovh.net",
            "ovhcloud.com",
            "akamaized.net",
            "edgekey.net",
            "edgesuite.net",
            "fastly.net",
            "fastlylb.net",
            "fastly-edge.com",
            "cdn77.com",
            "cdn77.org",
        ),
        ipset_exclude=(
            "0.0.0.0/8",
            "10.0.0.0/8",
            "127.0.0.0/8",
            "192.168.0.0/16",
            "185.71.66.225",
            "185.71.67.221",
        ),
        extra_list_files=(("ipset-all.txt", "sample_data/default_services/clouds/lists/ipset-all.txt"),),
        test_targets=(
            ("Amazon AWS", "https://aws.amazon.com"),
            ("Bunny CDN", "https://bunny.net"),
            ("OVHcloud", "https://www.ovhcloud.com"),
        ),
    ),
    "gaming": ServiceRule(
        list_general=(
            "ext-twitch.tv",
            "jtvnw.net",
            "live-video.net",
            "ttvnw.net",
            "twitch.tv",
            "twitchcdn.net",
            "twitchsvc.net",
        ),
        extra_list_files=_GAMING_LIST_FILES,
        bin_overlay_dir="sample_data/default_services/gaming/bin",
        winws_args=(
            "--new",
            "--filter-tcp={game_tcp}",
            "--ipset={lists}\\ipset-all.txt",
            "--ipset-exclude={lists}\\ipset-exclude.txt",
            "--ipset-exclude={lists}\\ipset-exclude-user.txt",
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-any-protocol=1",
            "--dpi-desync-cutoff=n4",
            "--dpi-desync-split-seqovl=664",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-repeats=8",
            "--dpi-desync-split-seqovl-pattern={bin}\\tls_clienthello_max_ru.bin",
            "--dpi-desync-fake-tls={bin}\\stun.bin",
            "--dpi-desync-fake-tls={bin}\\tls_clienthello_max_ru.bin",
            "--dpi-desync-fake-http={bin}\\tls_clienthello_max_ru.bin",
            "--new",
            "--filter-udp={game_udp}",
            "--ipset={lists}\\ipset-all.txt",
            "--ipset-exclude={lists}\\ipset-exclude.txt",
            "--ipset-exclude={lists}\\ipset-exclude-user.txt",
            "--dpi-desync=fake",
            "--dpi-desync-repeats=10",
            "--dpi-desync-any-protocol=1",
            "--dpi-desync-fake-unknown-udp={bin}\\quic_initial_dbankcloud_ru.bin",
            "--dpi-desync-cutoff=n4",
            "--new",
            "--filter-udp=80,443,3478-3497,42377-62133,{game_udp}",
            "--ipset={lists}\\ipset-all.txt",
            "--hostlist-exclude={lists}\\list-exclude.txt",
            "--hostlist-exclude={lists}\\list-exclude-user.txt",
            "--ipset-exclude={lists}\\ipset-exclude.txt",
            "--ipset-exclude={lists}\\ipset-exclude-user.txt",
            "--dpi-desync=fake",
            "--dpi-desync-repeats=11",
            "--dpi-desync-fake-quic={bin}\\quic_initial_www_google_com.bin",
            "--new",
            "--filter-tcp=80,443,3478-3497,42377-62133,{game_tcp}",
            "--ipset={lists}\\ipset-all.txt",
            "--hostlist-exclude={lists}\\list-exclude.txt",
            "--hostlist-exclude={lists}\\list-exclude-user.txt",
            "--ipset-exclude={lists}\\ipset-exclude.txt",
            "--ipset-exclude={lists}\\ipset-exclude-user.txt",
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-split-seqovl=664",
            "--dpi-desync-split-pos=1",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-repeats=8",
            "--dpi-desync-split-seqovl-pattern={bin}\\tls_clienthello_max_ru.bin",
            "--dpi-desync-fake-tls={bin}\\stun.bin",
            "--dpi-desync-fake-tls={bin}\\tls_clienthello_max_ru.bin",
            "--dpi-desync-fake-http={bin}\\tls_clienthello_max_ru.bin",
            "--new",
            "--filter-udp=3478-3497,42377-62133",
            "--filter-l7=stun",
            "--dpi-desync=fake",
            "--dpi-desync-fake-stun={bin}\\quic_initial_www_google_com.bin",
            "--dpi-desync-repeats=6",
            "--new",
            "--filter-tcp=3478-3497,42377-62133",
            "--filter-l7=stun",
            "--dpi-desync=fake",
            "--dpi-desync-fake-tls={bin}\\tls_clienthello_max_ru.bin",
            "--dpi-desync-repeats=6",
        ),
        test_targets=(
            ("Gaming", "https://store.steampowered.com"),
            ("Epic Games", "https://www.epicgames.com"),
            ("Roblox", "https://www.roblox.com"),
        ),
    ),
    "ai": ServiceRule(),
    "ubisoft": ServiceRule(
        list_general=("ubisoft.com", "ubi.com", "uplay.com", "ubisoftconnect.com"),
        extra_list_files=_UBISOFT_LIST_FILES,
        test_targets=(("Ubisoft", "https://www.ubisoft.com"), ("Ubisoft Connect", "https://connect.ubisoft.com")),
    ),
    "epic-games": ServiceRule(
        list_general=("epicgames.com", "epicgames.dev", "epicgamescdn.com", "unrealengine.com", "akamaized.net", "cloudfront.net"),
        list_exclude=("easy.ac", "easyanticheat.net", "easyanticheat.com"),
        test_targets=(("Epic Games", "https://www.epicgames.com"),),
    ),
    "battle-net": ServiceRule(
        list_general=("battle.net", "blizzard.com", "blizzard.net", "blz-contentstack.com", "blzddist1-a.akamaihd.net"),
        test_targets=(("Battle.net", "https://www.battle.net"),),
    ),
    "fortnite": ServiceRule(
        list_general=(
            "account-public-service-prod03.ol.epicgames.com",
            "launcherwaitingroom-public-service-prod06.ol.epicgames.com",
            "launcher-public-service-prod06.ol.epicgames.com",
            "www.epicgames.com",
            "launcher-website-prod07.ol.epicgames.com",
            "tracking.epicgames.com",
            "accounts.launcher-website-prod07.ol.epicgames.com",
            "accounts.epicgames.com",
            "cdn1.unrealengine.com",
            "cdn2.unrealengine.com",
            "datarouter.ol.epicgames.com",
            "entitlement-public-service-prod08.ol.epicgames.com",
            "orderprocessor-public-service-ecomprod01.ol.epicgames.com",
            "catalog-public-service-prod06.ol.epicgames.com",
            "friends-public-service-prod06.ol.epicgames.com",
            "lightswitch-public-service-prod06.ol.epicgames.com",
            "accountportal-website-prod07.ol.epicgames.com",
            "ut-public-service-prod10.ol.epicgames.com",
            "epicgames-download1.akamaized.net",
            "download.epicgames.com",
            "download2.epicgames.com",
            "download3.epicgames.com",
            "download4.epicgames.com",
            "egdownload.fastly-edge.com",
            "fortnite-vod.akamaized.net",
            "static-assets-prod.epicgames.com",
            "store-site-backend-static.ak.epicgames.com",
            "store-content.ak.epicgames.com",
            "library-service.live.use1a.on.epicgames.com",
            "datastorage-public-service-liveegs.live.use1a.on.epicgames.com",
            "fastly-download.epicgames.com",
            "store.epicgames.com",
            "launcher.store.epicgames.com",
            "js.hcaptcha.com",
        ),
        test_targets=(
            ("Fortnite Account", "https://account-public-service-prod03.ol.epicgames.com"),
            ("Fortnite Launcher", "https://launcher-public-service-prod06.ol.epicgames.com"),
            ("Epic Downloads", "https://download.epicgames.com"),
            ("Epic Games Store", "https://store.epicgames.com"),
            ("Epic Fastly CDN", "https://fastly-download.epicgames.com"),
            ("Unreal CDN", "https://cdn1.unrealengine.com"),
        ),
        health_hosts=("download.epicgames.com", "launcher-public-service-prod06.ol.epicgames.com"),
    ),
    "warframe": ServiceRule(
        list_general=(
            "warframe.com",
            "api.warframe.com",
            "content.warframe.com",
            "origin.warframe.com",
            "nexus.warframe.com",
            "forums.warframe.com",
            "digitalextremes.com",
        ),
        # Digital Extremes documents UDP 4950/4955 as the default game ports.
        # Selecting this service enables the generic game TCP/UDP profile, so
        # players that changed the two in-game ports are covered as well.
        test_targets=(
            ("Warframe", "https://www.warframe.com"),
            ("Warframe API", "https://api.warframe.com"),
        ),
        health_hosts=("www.warframe.com", "api.warframe.com"),
    ),
    "spotify": ServiceRule(
        list_general=(
            "spotify.com",
            "scdn.co",
            "spotifycdn.com",
            "open.spotify.com",
            "api.spotify.com",
            "accounts.spotify.com",
            "gew1-spclient.spotify.com",
            "login5.spotify.com",
            "spclient.wg.spotify.com",
            "api-partner.spotify.com",
            "apresolve.spotify.com",
            "appresolve.spotify.com",
        ),
        test_targets=(
            ("Spotify Resolve", "https://apresolve.spotify.com"),
            ("Spotify", "https://open.spotify.com"),
        ),
        health_hosts=("apresolve.spotify.com", "open.spotify.com"),
    ),
    "reddit": ServiceRule(
        list_general=("reddit.com", "redd.it", "redditmedia.com", "redditstatic.com", "redditinc.com"),
        test_targets=(("Reddit", "https://www.reddit.com"),),
    ),
    "x-twitter": ServiceRule(
        list_general=("x.com", "api.x.com", "twitter.com", "api.tweetdeck.com", "twimg.com", "pbs.twimg.com", "video.twimg.com", "t.co"),
        test_targets=(
            ("X API", "https://api.x.com"),
            ("X", "https://x.com"),
            ("Twitter CDN", "https://pbs.twimg.com"),
        ),
        health_hosts=("api.x.com", "x.com"),
    ),
    "github": ServiceRule(
        list_general=(
            "github.com",
            "githubusercontent.com",
            "raw.githubusercontent.com",
            "githubassets.com",
            "github.io",
            "objects.githubusercontent.com",
            "codeload.github.com",
        ),
        test_targets=(
            ("GitHub Codeload", "https://codeload.github.com"),
            ("GitHub Raw", "https://raw.githubusercontent.com"),
            ("GitHub", "https://github.com"),
        ),
        health_hosts=("codeload.github.com", "github.com"),
    ),
    "riot-games": ServiceRule(
        list_general=("riotgames.com", "riotcdn.net", "pvp.net", "auth.riotgames.com", "clientconfig.rpg.riotgames.com"),
        test_targets=(("Riot Games", "https://www.riotgames.com"),),
    ),
    "league-of-legends": ServiceRule(
        list_general=("leagueoflegends.com", "lolstatic.com", "lolesports.com", "riotcdn.net", "pvp.net"),
        ipset_all=("3.64.0.0/12", "18.156.0.0/14", "18.165.180.0/22", "35.156.0.0/14", "44.224.0.0/11", "99.83.128.0/20"),
        extra_lists=(("ipset-lol.txt", ("3.64.0.0/12", "18.156.0.0/14", "18.165.180.0/22", "35.156.0.0/14", "44.224.0.0/11", "99.83.128.0/20")),),
        winws_args=("--new", "--filter-tcp=2099", "--ipset={lists}/ipset-lol.txt", "--dpi-desync=syndata"),
        test_targets=(("League of Legends", "https://www.leagueoflegends.com"),),
    ),
    "figma": ServiceRule(
        list_general=("figma.com", "www.figma.com", "figma.net", "figma-alpha-api.s3.us-west-2.amazonaws.com"),
        ipset_all=("18.66.0.0/16", "52.222.0.0/15", "54.230.0.0/16", "108.138.0.0/15", "143.204.0.0/16", "199.232.0.0/16", "205.251.192.0/18"),
        test_targets=(("Figma", "https://www.figma.com"),),
    ),
    "netflix": ServiceRule(
        list_general=("netflix.com", "nflxvideo.net", "nflximg.net", "nflxso.net", "nflxext.com", "fast.com"),
        test_targets=(
            ("Netflix CDN", "https://assets.nflxext.com"),
            ("Netflix", "https://www.netflix.com"),
        ),
        health_hosts=("assets.nflxext.com", "www.netflix.com"),
    ),
    "facebook": ServiceRule(
        list_general=("facebook.com", "fbcdn.net", "fbsbx.com", "accountkit.com", "facebookauth.com", "facebook.net", "fb.com", "fb.me"),
        test_targets=(("Facebook", "https://www.facebook.com"),),
    ),
}
