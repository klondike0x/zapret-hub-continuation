import { uiAssetUrl } from "@/lib/assets";

const SERVICE_ICON_FILES: Record<string, string> = {
  cloudflare: "cloudflare.svg",
  discord: "discord.svg",
  youtube: "youtube.svg",
  "telegram-desktop": "telegram.svg",
  telegram: "telegram.svg",
  gaming: "gaming.svg",
  clouds: "clouds.svg",
  ai: "ai.svg",
  ubisoft: "ubisoft.svg",
  "epic-games": "epicgames.svg",
  "battle-net": "battledotnet.svg",
  fortnite: "fortnite.svg",
  spotify: "spotify.svg",
  reddit: "reddit.svg",
  "x-twitter": "x.svg",
  github: "github.svg",
  "riot-games": "riotgames.svg",
  "league-of-legends": "leagueoflegends.svg",
  figma: "figma.svg",
  netflix: "netflix.svg",
  facebook: "facebook.svg",
};

export function serviceIconUrl(id: string) {
  return uiAssetUrl(`service_icons/${SERVICE_ICON_FILES[id] ?? "clouds.svg"}`);
}

export function serviceIconNeedsContrast(id: string) {
  return ["gaming", "ai", "ubisoft", "epic-games", "x-twitter", "github"].includes(id);
}
