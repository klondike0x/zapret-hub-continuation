--[[
  Zapret Hub — YouTube / Discord bypass seed for winws2 (Zapret 2).
  Catalogs mirror Flowseal + youtubediscord/zapret2-youtube-discord lists.
  Packet desync is applied by Hub orchestrator Lua and hostlist/ipset files.
]]

HUB_BYPASS_YOUTUBE_DISCORD = true
HUB_BYPASS_YOUTUBE_DISCORD_VERSION = "2"

-- Domain catalog (hostlist files are authoritative; this mirrors them for Lua).
HUB_BYPASS_DOMAINS = {
  "dis.gd",
  "discord.com",
  "discord.gg",
  "discord.media",
  "discordapp.com",
  "discordapp.io",
  "discordapp.net",
  "discordcdn.com",
  "discordstatus.com",
  "discords.com",
  "cdn.discordapp.com",
  "media.discordapp.net",
  "gateway.discord.gg",
  "images-ext-1.discordapp.net",
  "images-ext-2.discordapp.net",
  "dl.discordapp.net",
  "stable.dl2.discordapp.net",
  "status.discord.com",
  "latency.discord.media",
  "updates.discord.com",
  "discord-attachments-uploads-prd.storage.googleapis.com",
  "youtube.com",
  "youtubekids.com",
  "youtu.be",
  "ytimg.com",
  "googlevideo.com",
  "youtube-nocookie.com",
  "ggpht.com",
  "gvt1.com",
  "youtube.googleapis.com",
  "youtubei.googleapis.com",
  "yt3.googleusercontent.com",
  "manifest.googlevideo.com",
  "redirector.googlevideo.com",
  "jnn-pa.googleapis.com",
}

HUB_BYPASS_NETWORKS = {
  "149.154.167.0/24",
  "173.194.0.0/16",
}

if type(print) == "function" then
  print(string.format(
    "[Zapret Hub] YouTube/Discord bypass Lua ready (domains=%d networks=%d)",
    #HUB_BYPASS_DOMAINS,
    #HUB_BYPASS_NETWORKS
  ))
end
