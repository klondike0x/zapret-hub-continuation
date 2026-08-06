from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServicePreset:
    id: str
    title_ru: str
    title_en: str
    description_ru: str
    description_en: str
    icon_file: str
    accent: str
    short_description_ru: str = ""
    short_description_en: str = ""


SERVICE_PRESETS: tuple[ServicePreset, ...] = (
    ServicePreset("cloudflare", "Cloudflare", "Cloudflare", "CDN, DNS, WARP и серверная инфраструктура", "CDN, DNS, WARP, and edge infrastructure", "cloudflare.svg", "#f38020", "CDN, DNS, Warp и серверы", "CDN, DNS, WARP, and servers"),
    ServicePreset("discord", "Discord", "Discord", "Голосовой чат, сообщения и медиа Discord", "Voice chat, messaging, and Discord media", "discord.svg", "#5865f2", "Голосовой чат, сообщения и медиа", "Voice chat, messages, and media"),
    ServicePreset("youtube", "YouTube", "YouTube", "Видео, превью, Shorts и CDN Google", "Video playback, thumbnails, Shorts, and Google CDN", "youtube.svg", "#ff0033"),
    ServicePreset("telegram-desktop", "Telegram", "Telegram", "Десктопное приложение Telegram для ПК", "Telegram desktop app for PC", "telegram.svg", "#26a5e4", "Десктопное приложение Telegram", "Telegram desktop app"),
    ServicePreset("gaming", "Gaming", "Gaming", "Настройки совместимости для игровых сервисов", "Compatibility settings for gaming services", "gaming.svg", "#64d488", "Большинство игровых сервисов", "Most gaming services"),
    ServicePreset("clouds", "Clouds", "Clouds", "Amazon CDN, CloudFront, BunnyCDN, OVH SAS и другие облачные CDN", "Amazon CDN, CloudFront, BunnyCDN, OVH SAS, and other cloud CDNs", "clouds.svg", "#66c0f4", "Amazon, Cloudfront, Bunny и другие", "Amazon, CloudFront, Bunny, and others"),
    ServicePreset("ai", "Нейросети", "Neural Networks", "ChatGPT, Claude, Gemini и Copilot", "ChatGPT, Claude, Gemini, and Copilot", "ai.svg", "#10a37f", "ChatGPT, Claude, Gemini, Copilot", "ChatGPT, Claude, Gemini, Copilot"),
    ServicePreset("ubisoft", "Ubisoft", "Ubisoft", "Ubisoft Connect, магазин, авторизация, загрузки и игровые сервисы", "Ubisoft Connect, store, auth, downloads, and game services", "ubisoft.svg", "#7a7dff", "Ubisoft Connect, магазин и игры", "Ubisoft Connect, store, and games"),
    ServicePreset("epic-games", "Epic Games", "Epic Games", "Магазин, лаунчер, загрузки и сервисы Epic", "Store, launcher, downloads, and Epic services", "epicgames.svg", "#eef2f8", "Магазин, лаунчер, загрузки и сервисы", "Store, launcher, downloads, and services"),
    ServicePreset("battle-net", "Battle.net", "Battle.net", "Лаунчер, игры Blizzard и загрузка контента", "Launcher, Blizzard games, and content delivery", "battledotnet.svg", "#148eff"),
    ServicePreset("fortnite", "Fortnite", "Fortnite", "Матчмейкинг, лаунчер, загрузки и сервисы Epic", "Matchmaking, launcher, downloads, and Epic services", "fortnite.svg", "#7c5cff", "Матчмейкинг, лаунчер, загрузки и сервисы", "Matchmaking, launcher, downloads, and services"),
    ServicePreset("warframe", "Warframe", "Warframe", "Чат, сессии и сетевая игра Warframe", "Warframe chat, sessions, and multiplayer", "gaming.svg", "#d6b668", "Чат и сетевая игра", "Chat and multiplayer"),
    ServicePreset("spotify", "Spotify", "Spotify", "Веб-плеер, авторизация и музыкальный CDN", "Web player, auth, and music delivery CDN", "spotify.svg", "#1ed760", "Веб-плеер и авторизация", "Web player and auth"),
    ServicePreset("reddit", "Reddit", "Reddit", "Форумы, медиа, API и статические файлы Reddit", "Communities, media, API, and Reddit static files", "reddit.svg", "#ff4500", "Форумы, медиа, API и файлы Reddit", "Forums, media, API, and Reddit files"),
    ServicePreset("x-twitter", "X / Twitter", "X / Twitter", "Лента, медиа, API и короткие ссылки X", "Timeline, media, API, and X short links", "x.svg", "#f2f6ff"),
    ServicePreset("github", "GitHub", "GitHub", "Сайт, raw-файлы, ассеты и GitHub Pages", "Website, raw files, assets, and GitHub Pages", "github.svg", "#f0f6fc"),
    ServicePreset("riot-games", "Riot Games", "Riot Games", "Клиент Riot, авторизация и игровые сервисы", "Riot client, authentication, and game services", "riotgames.svg", "#d32936", "Клиент, авторизация и игровые сервисы", "Client, auth, and game services"),
    ServicePreset("league-of-legends", "LOL", "LOL", "Клиент League и игровые серверы Riot", "League client and Riot game servers", "leagueoflegends.svg", "#c89b3c"),
    ServicePreset("figma", "Figma", "Figma", "Файлы, макеты и CDN Figma", "Files, projects, and Figma CDN", "figma.svg", "#a259ff"),
    ServicePreset("netflix", "Netflix", "Netflix", "Стриминг, постеры и CDN Netflix", "Streaming, artwork, and Netflix CDN", "netflix.svg", "#e50914"),
    ServicePreset("facebook", "Facebook", "Facebook", "Лента, вход, медиа и CDN Facebook", "Feed, login, media, and Facebook CDN", "facebook.svg", "#1877f2"),
)


SERVICE_PRESET_IDS = {item.id for item in SERVICE_PRESETS}

FORTNITE_GENERAL_PRIORITY = (
    "general (ALT9).bat",
    "general (ALT9.1.1).bat",
    "general (ALT9.1).bat",
)

UBISOFT_GENERAL_PRIORITY = (
    "general (Ubisoft).bat",
)


def prioritize_generals_for_services(
    options: list[dict[str, str]],
    selected_service_ids: list[str] | tuple[str, ...] | set[str],
) -> list[dict[str, str]]:
    selected = {str(item) for item in selected_service_ids}
    if "fortnite" not in selected and "ubisoft" not in selected:
        return list(options)

    prioritized: list[dict[str, str]] = []
    used: set[str] = set()
    wanted_order: list[str] = []
    if "fortnite" in selected:
        wanted_order.extend(FORTNITE_GENERAL_PRIORITY)
    for wanted in wanted_order:
        for option in options:
            if str(option.get("name", "")).strip().lower() != wanted.lower():
                continue
            option_id = str(option.get("id", "") or "")
            if not option_id or option_id in used:
                continue
            candidate = dict(option)
            if wanted in FORTNITE_GENERAL_PRIORITY:
                candidate["ipset_mode"] = "any"
                candidate["game_mode"] = "tcpudp"
            prioritized.append(candidate)
            used.add(option_id)
            break

    remaining: list[dict[str, str]] = []
    ubisoft_candidates: list[dict[str, str]] = []
    for option in options:
        option_id = str(option.get("id", "") or "")
        if not option_id or option_id in used:
            continue
        candidate = dict(option)
        if (
            "ubisoft" in selected
            and str(candidate.get("name", "")).strip().lower() in {item.lower() for item in UBISOFT_GENERAL_PRIORITY}
        ):
            ubisoft_candidates.append(candidate)
        else:
            remaining.append(candidate)
        used.add(option_id)
    if ubisoft_candidates:
        insert_at = max(1, len(remaining) // 2)
        prioritized.extend(remaining[:insert_at])
        prioritized.extend(ubisoft_candidates)
        prioritized.extend(remaining[insert_at:])
        return prioritized
    prioritized.extend(remaining)
    return prioritized
