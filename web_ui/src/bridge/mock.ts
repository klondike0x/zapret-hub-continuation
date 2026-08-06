import type {
  AppState,
  CommandName,
  Commands,
  ComponentId,
  EventName,
  Events,
  FileEntry,
  LogEntry,
  MarketplaceCard,
  MarketplaceProject,
  Mod,
  Notification,
  RuntimeId,
  ZapretHubBridge,
} from "./types";

// -------- initial state --------
const nowMinus = (m: number) => Date.now() - m * 60_000;

const services = [
  { id: "cloudflare", name: "Cloudflare", description: "Cloudflare edge & workers", category: "cdn" },
  { id: "discord", name: "Discord", description: "Voice & text chat", category: "social" },
  { id: "youtube", name: "YouTube", description: "Video streaming", category: "media" },
  { id: "telegram", name: "Telegram", description: "Messenger", category: "social" },
  { id: "gaming", name: "Gaming", description: "Battle.net / Steam / Riot", category: "games" },
  { id: "clouds", name: "Clouds", description: "AWS / GCP / Azure", category: "cloud" },
  { id: "ai", name: "AI", description: "OpenAI / Anthropic / Gemini", category: "ai" },
  { id: "ubisoft", name: "Ubisoft", description: "Ubisoft Connect", category: "games" },
];

const components: Record<ComponentId, import("./types").ComponentInfo> = {
  zapret: {
    id: "zapret",
    name: "Zapret",
    version: "0.71.1",
    status: "on",
    description: "Локальная обработка трафика через winws.exe",
    config: "Strategy: general-alt · Ports: 80,443",
    externalUrl: "https://github.com/bol-van/zapret",
    meta: { PID: "1428", Uptime: "12m" },
  },
  zapret2: {
    id: "zapret2",
    name: "Zapret2",
    version: "1.2.0",
    status: "off",
    description: "Альтернативная локальная обработка трафика",
    config: "Strategy: fake-split · Ports: 443",
    externalUrl: "https://example.com/zapret2",
  },
  "goshkow-vpn": {
    id: "goshkow-vpn",
    name: "goshkow VPN",
    version: "0.9.3",
    status: "off",
    description: "WireGuard-based VPN",
    config: "Endpoint: nl-01 · MTU: 1420",
    externalUrl: "https://goshkow.example",
  },
  "tg-ws-proxy": {
    id: "tg-ws-proxy",
    name: "TG WS Proxy",
    version: "0.4.0",
    status: "off",
    enabled: false,
    description: "WebSocket proxy для Telegram",
    config: "Host: 127.0.0.1:8443",
  },
  "xbox-dns": {
    id: "xbox-dns",
    name: "DNS",
    version: "0.2.1",
    status: "off",
    enabled: false,
    description: "Системные DNS-серверы с выбором провайдера",
    config: "Servers: 1.1.1.1, 9.9.9.9",
  },
};

const initialFiles: FileEntry[] = [
  { kind: "domains", name: "domains.txt", content: "youtube.com\ndiscord.com\ntelegram.org\n", updatedAt: nowMinus(20) },
  { kind: "exclusions", name: "exclusions.txt", content: "internal.corp\nlocal.dev\n", updatedAt: nowMinus(60) },
  { kind: "ip-lists", name: "ip-lists.txt", content: "1.1.1.1\n8.8.8.8\n", updatedAt: nowMinus(120) },
  { kind: "ip-exclusions", name: "ip-exclusions.txt", content: "192.168.0.0/16\n10.0.0.0/8\n", updatedAt: nowMinus(240) },
  { kind: "general", name: "general.cfg", content: "# General config\nmode=auto\nlog_level=info\n", updatedAt: nowMinus(15) },
  { kind: "hosts", name: "hosts", content: "127.0.0.1 localhost\n", updatedAt: nowMinus(600) },
  { kind: "advanced", name: "advanced.editor", content: "// Advanced strategy DSL\nstrategy \"main\" {\n  fake-split ttl=6;\n}\n", updatedAt: nowMinus(5) },
];

const initialMods: Mod[] = [
  {
    id: "m1",
    name: "YouTube+",
    author: "community",
    description: "Улучшенные стратегии для YouTube",
    enabled: true,
    compatibleFiles: ["domains", "general"],
    source: "github",
    createdAt: nowMinus(1440),
  },
  {
    id: "m2",
    name: "Discord Voice Fix",
    author: "goshkow",
    description: "Фикс голосовых чатов Discord",
    enabled: false,
    compatibleFiles: ["ip-lists", "general"],
    source: "zip",
    createdAt: nowMinus(2880),
  },
];

const mockMarketplace: MarketplaceProject[] = [
  {
    id: 1,
    slug: "youtube-flow",
    title: "YouTube Flow",
    summary: "YouTube без ограничений и лишних настроек.",
    author: "goshkow",
    iconUrl: "",
    projectUrl: "https://goshkow.com/zapret-hub/marketplace/projects/youtube-flow",
    apiUrl: "",
    downloadUrl: "",
    compatibility: "zapret",
    categories: ["Соцсети"],
    license: "MIT",
    downloads: 128400,
    downloadsCompact: "128.4K",
    likes: 3180,
    favorites: 1912,
    followers: 640,
    comments: 27,
    featured: true,
    updatedAt: Math.floor(Date.now() / 1000) - 86400,
    publishedAt: Math.floor(Date.now() / 1000) - 86400 * 30,
    bodyHtml: "<h2>Возможности</h2><ul><li>Простая установка</li><li>Автоматические обновления</li></ul>",
    versions: [{ id: 11, version: "1.0.0", changelog: "Первый релиз", size: 12000, sha256: "", downloads: 1000, compatibility: "zapret" }],
  },
  {
    id: 2,
    slug: "discord-bridge",
    title: "Discord Bridge",
    summary: "Стабильный Discord голос и медиа.",
    author: "goshkow",
    iconUrl: "",
    projectUrl: "https://goshkow.com/zapret-hub/marketplace/projects/discord-bridge",
    apiUrl: "",
    downloadUrl: "",
    compatibility: "zapret2",
    categories: ["Игры", "Соцсети"],
    license: "MIT",
    downloads: 84200,
    downloadsCompact: "84.2K",
    likes: 2104,
    favorites: 980,
    followers: 310,
    comments: 12,
    featured: false,
    updatedAt: Math.floor(Date.now() / 1000) - 3600 * 8,
    publishedAt: Math.floor(Date.now() / 1000) - 86400 * 14,
    bodyHtml: "<p>Оптимизация Discord для Zapret 2.</p>",
    versions: [{ id: 21, version: "2.1.0", changelog: "Улучшения стабильности", size: 18000, sha256: "", downloads: 500, compatibility: "zapret2" }],
  },
];

const initialLogs: LogEntry[] = Array.from({ length: 20 }, (_, i) => ({
  id: `l${i}`,
  source: (["app", "zapret", "vpn", "tg", "zapret2"] as const)[i % 5],
  level: (["info", "info", "warn", "info", "error"] as const)[i % 5],
  message: [
    "Application started",
    "Zapret worker spawned pid=1428",
    "Strategy applied: general-alt",
    "TG WS proxy idle",
    "VPN handshake pending",
  ][i % 5],
  ts: nowMinus(40 - i * 2),
}));

const initialState: AppState = {
  runtime: { active: "zapret", order: ["zapret", "goshkow-vpn", "zapret2", "none"], status: "on" },
  services: { available: services, selected: ["youtube", "discord", "telegram"] },
  components,
  mods: initialMods,
  mods2: [],
  files: initialFiles,
  files2: [
    { kind: "domains", name: "list-hub.txt", content: "youtube.com\ndiscord.com\n", updatedAt: nowMinus(5) },
    { kind: "exclusions", name: "list-exclude.txt", content: "", updatedAt: nowMinus(5) },
    { kind: "ip-lists", name: "ipset-hub.txt", content: "173.194.0.0/16\n", updatedAt: nowMinus(5) },
    { kind: "advanced", name: "list-auto.txt", content: "", updatedAt: nowMinus(5) },
    { kind: "general", name: "hub-strategy.lua", content: 'HUB_STRATEGY = "balanced"\n', updatedAt: nowMinus(5) },
    { kind: "hosts", name: "hub-orchestrator.lua", content: "-- hub\n", updatedAt: nowMinus(5) },
  ],
  logs: initialLogs,
  settings: {
    autoStart: true,
    minimizeToTray: true,
    autoRunComponents: false,
    trayNotification: true,
    checkUpdates: true,
    checkModUpdates: true,
    checkComponentUpdates: true,
    windowsNotifications: true,
    notificationsEnabled: true,
    hardwareAcceleration: true,
    soundsEnabled: true,
    soundsClickEnabled: true,
    soundsVolume: "normal",
    sidebarCollapsed: false,
    quickAccessWidget: "analysis",
    scrollModeSwitch: true,
    uiScale: "1",
    discordRpcEnabled: true,
    discordRpcClientId: "1530470595710685314",
    discordRpcStatus: { state: "ok", error: "", connected: "1" },
    zapret: {
      ipsetMode: "loaded",
      gameFilterMode: "disabled",
      gamingSet: "stun-wide-base",
      udpExclusions: "",
      selectedGeneral: "general|general (ALT12).bat",
      controlMode: "manual",
      trustedGeneral: "",
      generals: [
        { id: "general|general (ALT12).bat", name: "general (ALT12).bat" },
        { id: "general|general (ALT11).bat", name: "general (ALT11).bat" },
      ],
    },
    zapret2: { controlMode: "manual", tcpPorts: "80,443", udpPorts: "443", rawFilter: "", luaStrategy: "", strategyId: "balanced", youtubeDiscordBypass: true },
    vpn: {
      subscriptionUrl: "",
      subscriptionState: "empty",
      selectedServerId: "auto",
      servers: [],
      tunEnabled: true,
      routingMode: "global",
      systemProxyMode: "pac",
      processes: "",
      processesExcludeMode: false,
    },
    tg: { host: "127.0.0.1", port: 1443, secret: "", dcIp: "4:149.154.167.220", cfProxyEnabled: true, cfProxyPriority: true, cfProxyDomain: "", fakeTlsDomain: "", bufferKb: 256, poolSize: 4 },
    dns: { profile: "xbox" },
    theme: "night",
  },
  notifications: [
    { id: "n1", title: "Zapret запущен", body: "Стратегия general-alt применена", ts: nowMinus(3), read: false, level: "success" },
    { id: "n2", title: "Обновление доступно", body: "Zapret 0.72.0", ts: nowMinus(30), read: false, level: "info" },
  ],
  orchestrator: {
    mode: "manual",
    status: "idle",
    statusText: "Вручную",
    isAuto: false,
    running: false,
    zapretActive: true,
  },
  onboarding: { completed: false, isUpdate: false, forceOpen: false },
  ui: { locale: "ru", theme: "night", hasValidVpnKey: false },
};

// -------- mock adapter --------
export function createMockBridge(): ZapretHubBridge {
  let state: AppState = structuredClone(initialState);
  const listeners = new Map<EventName, Set<(p: unknown) => void>>();

  const emit = <E extends EventName>(event: E, payload: Events[E]) => {
    listeners.get(event)?.forEach((cb) => cb(payload as unknown));
  };
  const pushState = () => emit("state.changed", state);

  type MockDlJob = {
    jobId: string;
    slug: string;
    status: string;
    title: string;
    iconUrl: string;
    compatibility: string;
    progress: number;
    bytesDone: number;
    bytesTotal: number;
    message: string;
  };
  let mockDlQueue: MockDlJob[] = [];
  const mockDlPaused = new Set<string>();
  let mockDlBusy = false;

  const mockQueueSnapshot = (): Events["marketplace.queue"] => {
    const active = mockDlQueue.find((j) => j.status === "downloading" || j.status === "installing");
    const overall = active?.bytesTotal
      ? Math.max(0, Math.min(1, active.bytesDone / active.bytesTotal))
      : active
        ? Math.max(0, active.progress)
        : mockDlQueue.length
          ? 0
          : 0;
    return {
      busy: mockDlBusy,
      activeSlug: active?.slug || "",
      overallProgress: overall,
      pending: mockDlQueue.map((j) => j.slug),
      items: mockDlQueue.map((j) => ({ ...j })),
    };
  };
  const emitQueue = () => emit("marketplace.queue", mockQueueSnapshot());
  const pumpMockDownloads = () => {
    if (mockDlBusy) return;
    const next = mockDlQueue.find((j) => j.status === "queued" && !mockDlPaused.has(j.jobId));
    if (!next) return;
    mockDlBusy = true;
    next.status = "downloading";
    next.progress = 0.05;
    next.bytesDone = 5;
    emit("marketplace.download-progress", { ...next, pending: mockDlQueue.map((j) => j.slug) });
    emitQueue();
    let step = 0;
    const tick = () => {
      if (!mockDlQueue.some((j) => j.jobId === next.jobId)) {
        mockDlBusy = false;
        pumpMockDownloads();
        return;
      }
      if (mockDlPaused.has(next.jobId)) {
        next.status = "paused";
        mockDlBusy = false;
        emit("marketplace.download-progress", { ...next, pending: mockDlQueue.map((j) => j.slug) });
        emitQueue();
        pumpMockDownloads();
        return;
      }
      step += 1;
      next.bytesDone = Math.min(100, 5 + step * 20);
      next.progress = next.bytesDone / 100;
      if (next.bytesDone >= 100) {
        next.status = "installing";
        next.progress = 0.95;
        emit("marketplace.download-progress", { ...next, pending: mockDlQueue.map((j) => j.slug) });
        emitQueue();
        window.setTimeout(() => {
          next.status = "done";
          next.progress = 1;
          mockDlQueue = mockDlQueue.filter((j) => j.jobId !== next.jobId);
          mockDlBusy = false;
          const project = mockMarketplace.find((item) => item.slug === next.slug);
          if (project) {
            const mod: Mod = {
              id: `mp-${next.slug}`,
              name: project.title,
              version: project.versions?.[0]?.version || "1.0.0",
              enabled: true,
              description: project.summary,
              author: project.author,
              compatibleFiles: ["domains", "general"],
              source: "custom",
              createdAt: Date.now(),
              marketplaceSlug: next.slug,
              iconUrl: project.iconUrl,
              sourceUrl: project.projectUrl,
            };
            if (project.compatibility === "zapret2") {
              const mods2 = state.mods2 || [];
              if (!mods2.some((m) => m.marketplaceSlug === next.slug)) state.mods2 = [...mods2, mod];
            } else if (!state.mods.some((m) => m.marketplaceSlug === next.slug)) {
              state.mods = [...state.mods, mod];
            }
            pushState();
          }
          emit("marketplace.download-progress", {
            ...next,
            pending: mockDlQueue.map((j) => j.slug),
            mods: structuredClone(state.mods),
            mods2: structuredClone(state.mods2 || []),
          });
          emit("toast.show", { id: `mp-${next.slug}`, message: `Модификация «${next.title}» установлена.`, kind: "success" });
          emitQueue();
          pumpMockDownloads();
        }, 350);
        return;
      }
      emit("marketplace.download-progress", { ...next, pending: mockDlQueue.map((j) => j.slug) });
      emitQueue();
      window.setTimeout(tick, 280);
    };
    window.setTimeout(tick, 280);
  };

  // periodic mock log to demonstrate live tail
  if (typeof window !== "undefined") {
    setInterval(() => {
      if (state.runtime.status !== "on") return;
      const entry: LogEntry = {
        id: `l${Date.now()}`,
        source: (["app", "zapret", "vpn", "tg"] as const)[Math.floor(Math.random() * 4)],
        level: Math.random() > 0.85 ? "warn" : "info",
        message: [
          "heartbeat ok",
          "packet inspected",
          "strategy tick",
          "connection kept-alive",
          "cache hit",
        ][Math.floor(Math.random() * 5)],
        ts: Date.now(),
      };
      state.logs = [...state.logs.slice(-199), entry];
      emit("logs.append", entry);
    }, 2500);
  }

  const applyMutex = (id: RuntimeId) => {
    // Zapret and Zapret2/VPN mutually exclusive at component level
    if (id === "zapret") {
      state.components.zapret.status = "on";
      state.components.zapret2.status = "off";
      state.components["goshkow-vpn"].status = "off";
    } else if (id === "zapret2") {
      state.components.zapret2.status = "on";
      state.components.zapret.status = "off";
      state.components["goshkow-vpn"].status = "off";
    } else {
      state.components["goshkow-vpn"].status = "on";
      state.components.zapret.status = "off";
      state.components.zapret2.status = "off";
    }
  };

  const call = async <K extends CommandName>(
    cmd: K,
    payload: Commands[K]["in"],
  ): Promise<Commands[K]["out"]> => {
    // small artificial latency
    await new Promise((r) => setTimeout(r, 60));
    switch (cmd) {
      case "state.get":
        return structuredClone(state) as Commands[K]["out"];
      case "marketplace.installed":
        return { mods: structuredClone(state.mods), mods2: structuredClone(state.mods2 || []) } as Commands[K]["out"];
      case "window.minimize":
      case "window.close":
        console.log("[mock bridge]", cmd);
        return undefined as Commands[K]["out"];
      case "runtime.select": {
        const p = payload as Commands["runtime.select"]["in"];
        state.runtime.active = p.id;
        applyMutex(p.id);
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "runtime.power": {
        const p = payload as Commands["runtime.power"]["in"];
        state.runtime.status = p.on ? "on" : "off";
        if (p.on) applyMutex(state.runtime.active);
        else {
          state.components.zapret.status = "off";
          state.components.zapret2.status = "off";
          state.components["goshkow-vpn"].status = "off";
        }
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "app.check-updates": {
        emit("toast.show", {
          id: "app-update-check",
          message: "You are up to date (mock).",
          kind: "success",
        });
        return undefined as Commands[K]["out"];
      }
      case "app.apply-update": {
        console.log("[mock bridge] app.apply-update", payload);
        return undefined as Commands[K]["out"];
      }
      case "component.toggle": {
        const p = payload as Commands["component.toggle"]["in"];
        state.components[p.id].status = p.on ? "on" : "off";
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "tg.connect":
      case "onboarding.cancel":
        return undefined as Commands[K]["out"];
      case "component.check-update": {
        const p = payload as Commands["component.check-update"]["in"];
        const versions =
          p.id === "zapret" ? [
            { version: "1.10.0", publishedAt: "2026-07-22T05:18:59Z", recommended: true, current: state.components.zapret.version === "1.10.0" },
            { version: "1.9.9c", publishedAt: "2026-06-15T12:00:00Z", recommended: false, current: state.components.zapret.version === "1.9.9c" },
            { version: "1.9.9b", publishedAt: "2026-06-14T17:46:35Z", recommended: false, current: state.components.zapret.version === "1.9.9b" },
            { version: "1.9.9a", publishedAt: "2026-06-01T10:00:00Z", recommended: false, current: false },
          ]
          : p.id === "zapret2" ? [
            { version: "1.0.3", publishedAt: "2026-07-20T12:00:00Z", recommended: true, current: state.components.zapret2.version === "1.0.3" },
            { version: "1.0.2", publishedAt: "2026-06-16T13:00:43Z", recommended: false, current: state.components.zapret2.version === "1.0.2" },
            { version: "1.0.1", publishedAt: "2026-06-10T12:00:00Z", recommended: false, current: state.components.zapret2.version === "1.0.1" },
            { version: "1.0", publishedAt: "2026-06-01T12:00:00Z", recommended: false, current: false },
          ]
          : p.id === "tg-ws-proxy" ? [
            { version: "1.8.1", publishedAt: "2026-07-01T12:00:00Z", recommended: true, current: state.components["tg-ws-proxy"].version === "1.8.1" },
            { version: "1.8.0", publishedAt: "2026-06-20T12:00:00Z", recommended: false, current: state.components["tg-ws-proxy"].version === "1.8.0" },
            { version: "1.7.3", publishedAt: "2026-05-10T12:00:00Z", recommended: false, current: false },
          ]
          : undefined;
        const latestVersion = versions?.[0]?.version || (p.id === "zapret2" ? "master" : "latest");
        setTimeout(() => emit("component.update-check", {
          requestId: p.requestId,
          id: p.id,
          available: state.components[p.id].version !== latestVersion,
          currentVersion: state.components[p.id].version,
          latestVersion,
          recommendedVersion: versions?.find((item) => item.recommended)?.version || latestVersion,
          versions,
        }), 450);
        return undefined as Commands[K]["out"];
      }
      case "component.install-update": {
        const p = payload as Commands["component.install-update"]["in"];
        state.components[p.id].status = "updating";
        emit("component.update-result", { id: p.id, status: "started" });
        pushState();
        setTimeout(() => {
          state.components[p.id].status = "on";
          state.components[p.id].version = p.version || (p.id === "zapret2" ? "1.0.3" : p.id === "zapret" ? "1.10.0" : p.id === "tg-ws-proxy" ? "1.8.1" : "latest");
          pushState();
          emit("component.update-result", { id: p.id, status: "success", version: state.components[p.id].version });
        }, 900);
        return undefined as Commands[K]["out"];
      }
      case "dns.select-profile": {
        const p = payload as Commands["dns.select-profile"]["in"];
        state.settings.dns.profile = p.profile;
        state.components["xbox-dns"].config = p.profile.toUpperCase();
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "services.set": {
        const p = payload as Commands["services.set"]["in"];
        state.services.selected = p.selected;
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "settings.apply": {
        const p = payload as Commands["settings.apply"]["in"];
        const { locale, theme, modeOrder, ...rest } = p.patch;
        state.settings = {
          ...state.settings,
          ...rest,
          ...(theme ? { theme } : {}),
          ...(rest.zapret ? { zapret: { ...state.settings.zapret, ...rest.zapret } } : {}),
        };
        if (rest.zapret?.controlMode) {
          const mode = rest.zapret.controlMode;
          state.orchestrator = {
            ...state.orchestrator,
            mode,
            isAuto: mode === "auto",
            status: mode === "auto" ? "ok" : "idle",
            statusText: mode === "auto" ? "Авто · работает" : "Вручную",
          };
        }
        if (locale) state.ui.locale = locale;
        if (theme) state.ui.theme = theme;
        if (modeOrder) state.runtime.order = modeOrder;
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "orchestrator.status":
        return structuredClone(state.orchestrator) as Commands[K]["out"];
      case "orchestrator.setMode": {
        const p = payload as Commands["orchestrator.setMode"]["in"];
        const mode = p.mode === "auto" ? "auto" : "manual";
        if (p.backend === "zapret2") state.settings.zapret2.controlMode = mode;
        else state.settings.zapret.controlMode = mode;
        state.orchestrator = {
          ...state.orchestrator,
          mode,
          isAuto: mode === "auto",
          status: mode === "auto" ? "ok" : "idle",
          statusText: mode === "auto" ? "Авто · работает" : "Вручную",
          running: mode === "auto",
        };
        emit("orchestrator.status", structuredClone(state.orchestrator));
        pushState();
        return structuredClone(state.orchestrator) as Commands[K]["out"];
      }
      case "orchestrator.resetAuto": {
        emit("toast.show", {
          id: "orchestrator-reset-auto",
          message: "Auto mode cache was reset.",
          kind: "success",
        });
        return { ok: true, overlay: true, knowledge: true, memory: true } as Commands[K]["out"];
      }
      case "orchestrator.bootstrap": {
        state.settings.zapret.controlMode = "auto";
        state.orchestrator = {
          ...state.orchestrator,
          mode: "auto",
          isAuto: true,
          status: "tuning",
          statusText: "Подбираю конфигурацию…",
          detail: "youtube.com",
          running: true,
        };
        emit("orchestrator.status", structuredClone(state.orchestrator));
        pushState();
        setTimeout(() => {
          state.orchestrator = {
            ...state.orchestrator,
            status: "ok",
            statusText: "Авто · работает",
            detail: "",
            running: true,
          };
          if (!state.services.selected.includes("youtube")) state.services.selected = [...state.services.selected, "youtube"];
          if (!state.services.selected.includes("discord")) state.services.selected = [...state.services.selected, "discord"];
          emit("orchestrator.status", structuredClone(state.orchestrator));
          emit("orchestrator.bootstrap", { ok: true, stage: 1, deferred: true });
          pushState();
        }, 1600);
        return { started: true } as Commands[K]["out"];
      }
      case "files.load": {
        const p = payload as Commands["files.load"]["in"];
        const f = state.files.find((x) => x.kind === p.kind && (!p.name || x.name === p.name));
        if (!f) throw new Error("file not found");
        return structuredClone(f) as Commands[K]["out"];
      }
      case "files.save": {
        const p = payload as Commands["files.save"]["in"];
        const i = state.files.findIndex((x) => x.kind === p.kind && x.name === p.name);
        const entry: FileEntry = { kind: p.kind, name: p.name, content: p.content, updatedAt: Date.now() };
        if (i >= 0) state.files[i] = entry;
        else state.files.push(entry);
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "files.rename": {
        const p = payload as Commands["files.rename"]["in"];
        const f = state.files.find((x) => x.kind === p.kind && x.name === p.from);
        if (f) f.name = p.to;
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "files.create": {
        const p = payload as Commands["files.create"]["in"];
        const entry: FileEntry = { kind: p.kind, name: p.name, content: "", updatedAt: Date.now() };
        state.files.push(entry);
        pushState();
        return structuredClone(entry) as Commands[K]["out"];
      }
      case "files.list": {
        const p = payload as Commands["files.list"]["in"];
        return state.files.filter((x) => x.kind === p.kind) as Commands[K]["out"];
      }
      case "mods.import": {
        const p = payload as Commands["mods.import"]["in"];
        const mod: Mod = {
          id: `m${Date.now()}`,
          name: p.ref ?? `Imported ${p.source}`,
          enabled: false,
          compatibleFiles: ["general"],
          source: p.source,
          createdAt: Date.now(),
        };
        state.mods.push(mod);
        pushState();
        return structuredClone(mod) as Commands[K]["out"];
      }
      case "mods.create": {
        const p = payload as Commands["mods.create"]["in"];
        const mod: Mod = {
          id: `m${Date.now()}`,
          name: p.name,
          enabled: false,
          compatibleFiles: [],
          source: "custom",
          createdAt: Date.now(),
        };
        state.mods.push(mod);
        pushState();
        return structuredClone(mod) as Commands[K]["out"];
      }
      case "mods.toggle": {
        const p = payload as Commands["mods.toggle"]["in"];
        const m = state.mods.find((x) => x.id === p.id);
        if (m) m.enabled = p.on;
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "mods.edit": {
        const p = payload as Commands["mods.edit"]["in"];
        const m = state.mods.find((x) => x.id === p.id);
        if (m) Object.assign(m, p.patch);
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "mods.export":
        console.log("[mock] export mod", payload);
        return undefined as Commands[K]["out"];
      case "mods.delete": {
        const p = payload as Commands["mods.delete"]["in"];
        state.mods = state.mods.filter((x) => x.id !== p.id);
        pushState();
        return { mods: state.mods, mods2: state.mods2 || [] } as Commands[K]["out"];
      }
      case "logs.clear": {
        const p = payload as Commands["logs.clear"]["in"];
        state.logs = p.source ? state.logs.filter((l) => l.source !== p.source) : [];
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "logs.get":
        return structuredClone(state.logs) as Commands[K]["out"];
      case "logs.export":
      case "logs.copy":
        console.log("[mock]", cmd, payload);
        return undefined as Commands[K]["out"];
      case "notifications.dismiss": {
        const p = payload as Commands["notifications.dismiss"]["in"];
        state.notifications = state.notifications.filter((n) => n.id !== p.id);
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "notifications.markRead": {
        const p = payload as Commands["notifications.markRead"]["in"];
        state.notifications = state.notifications.map((n) =>
          !p.id || n.id === p.id ? { ...n, read: true } : n,
        );
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "onboarding.complete": {
        const p = (payload || {}) as Commands["onboarding.complete"]["in"];
        if (p && typeof p === "object") {
          if (p.mode) state.runtime.active = p.mode;
          if (Array.isArray(p.selected)) state.services.selected = p.selected.map(String);
          if (p.dismiss === false) {
            pushState();
            return undefined as Commands[K]["out"];
          }
        }
        state.onboarding.completed = true;
        pushState();
        return undefined as Commands[K]["out"];
      }
      case "onboarding.configure":
        setTimeout(() => emit("onboarding.progress", { current: 2, total: 5, overallCurrent: 1, overallTotal: 8, name: "general (ALT12).bat" }), 250);
        setTimeout(() => emit("onboarding.progress", { current: 1, total: 5, overallCurrent: 2, overallTotal: 8, name: "general (ALT11).bat" }), 700);
        setTimeout(() => emit("onboarding.configuration", { status: "success", name: "general (ALT11).bat", passed: 4, total: 4 }), 1200);
        return undefined as Commands[K]["out"];
      case "component.configure":
      case "component.open-external":
        console.log("[mock]", cmd, payload);
        return undefined as Commands[K]["out"];
      case "marketplace.list": {
        const p = (payload || {}) as Commands["marketplace.list"]["in"];
        let list = mockMarketplace.map((item) => {
          const { bodyHtml: _b, versions: _v, ...card } = item;
          return card as MarketplaceCard;
        });
        const q = String(p.q || "").trim().toLowerCase();
        if (q) {
          list = list.filter(
            (item) =>
              item.title.toLowerCase().includes(q) ||
              item.summary.toLowerCase().includes(q) ||
              item.slug.toLowerCase().includes(q),
          );
        }
        if (p.compatibility) list = list.filter((item) => item.compatibility === p.compatibility);
        if (p.category) list = list.filter((item) => item.categories.includes(String(p.category)));
        const limit = Math.max(1, Math.min(50, Number(p.limit || 5)));
        const page = Math.max(1, Number(p.page || 1));
        const pages = Math.max(1, Math.ceil(list.length / limit));
        const start = (page - 1) * limit;
        return {
          ok: true,
          projects: list.slice(start, start + limit),
          total: list.length,
          page,
          pages,
          categories: ["Игры", "Программы", "Соцсети"],
        } as Commands[K]["out"];
      }
      case "marketplace.get": {
        const slug = String((payload as Commands["marketplace.get"]["in"])?.slug || "");
        const project = mockMarketplace.find((item) => item.slug === slug);
        if (!project) throw new Error("Project not found");
        return { ok: true, project: structuredClone(project) } as Commands[K]["out"];
      }
      case "marketplace.download": {
        const p = payload as Commands["marketplace.download"]["in"];
        const slug = String(p.slug || "");
        if (!slug) throw new Error("invalid_slug");
        if (mockDlQueue.some((j) => j.slug === slug && j.status !== "done" && j.status !== "error" && j.status !== "cancelled")) {
          return { queued: true, alreadyQueued: true, slug, pending: mockDlQueue.map((j) => j.slug), jobId: mockDlQueue.find((j) => j.slug === slug)?.jobId } as Commands[K]["out"];
        }
        const job = {
          jobId: `mock-${Date.now()}-${slug}`,
          slug,
          status: "queued",
          title: String(p.title || slug),
          iconUrl: String(p.iconUrl || ""),
          compatibility: String(p.compatibility || ""),
          progress: 0,
          bytesDone: 0,
          bytesTotal: 100,
          message: String(p.title || slug),
        };
        mockDlQueue.push(job);
        emitQueue();
        emit("marketplace.download-progress", { ...job, pending: mockDlQueue.map((j) => j.slug) });
        pumpMockDownloads();
        return { queued: true, slug, jobId: job.jobId, pending: mockDlQueue.map((j) => j.slug) } as Commands[K]["out"];
      }
      case "marketplace.remove": {
        const slug = String((payload as Commands["marketplace.remove"]["in"])?.slug || "");
        const removed = [...state.mods, ...(state.mods2 || [])]
          .filter((mod) => mod.marketplaceSlug === slug)
          .map((mod) => mod.id);
        state.mods = state.mods.filter((mod) => mod.marketplaceSlug !== slug);
        state.mods2 = (state.mods2 || []).filter((mod) => mod.marketplaceSlug !== slug);
        pushState();
        return { ok: true, slug, removed, mods: state.mods, mods2: state.mods2 || [] } as Commands[K]["out"];
      }
      case "marketplace.queue":
        return mockQueueSnapshot() as Commands[K]["out"];
      case "marketplace.cancel": {
        const p = payload as Commands["marketplace.cancel"]["in"];
        const slug = String(p?.slug || "");
        const jobId = String(p?.jobId || "");
        mockDlQueue = mockDlQueue.filter((j) => {
          const match = (jobId && j.jobId === jobId) || (slug && j.slug === slug);
          if (match) emit("marketplace.download-progress", { ...j, status: "cancelled", pending: [] });
          return !match;
        });
        mockDlPaused.clear();
        emitQueue();
        pumpMockDownloads();
        return mockQueueSnapshot() as Commands[K]["out"];
      }
      case "marketplace.pause": {
        const p = payload as Commands["marketplace.pause"]["in"];
        const slug = String(p?.slug || "");
        const job = mockDlQueue.find((j) => j.jobId === p?.jobId || j.slug === slug);
        if (job) {
          mockDlPaused.add(job.jobId);
          job.status = "paused";
          emit("marketplace.download-progress", { ...job, pending: mockDlQueue.map((j) => j.slug) });
          emitQueue();
        }
        return mockQueueSnapshot() as Commands[K]["out"];
      }
      case "marketplace.resume": {
        const p = payload as Commands["marketplace.resume"]["in"];
        const slug = String(p?.slug || "");
        const job = mockDlQueue.find((j) => j.jobId === p?.jobId || j.slug === slug);
        if (job) {
          mockDlPaused.delete(job.jobId);
          job.status = "queued";
          emit("marketplace.download-progress", { ...job, pending: mockDlQueue.map((j) => j.slug) });
          emitQueue();
          pumpMockDownloads();
        }
        return mockQueueSnapshot() as Commands[K]["out"];
      }
      case "marketplace.reorder-queue": {
        const p = payload as Commands["marketplace.reorder-queue"]["in"];
        const ordered = (p?.orderedSlugs || []).map(String);
        const active = mockDlQueue.filter((j) => j.status === "downloading" || j.status === "installing");
        const rest = mockDlQueue.filter((j) => j.status === "queued" || j.status === "paused");
        const bySlug = new Map(rest.map((j) => [j.slug, j]));
        const next = [...active];
        for (const slug of ordered) {
          const job = bySlug.get(slug);
          if (job) {
            next.push(job);
            bySlug.delete(slug);
          }
        }
        for (const job of bySlug.values()) next.push(job);
        mockDlQueue = next;
        emitQueue();
        return mockQueueSnapshot() as Commands[K]["out"];
      }
      case "marketplace.open-url":
        console.log("[mock] open-url", payload);
        return undefined as Commands[K]["out"];
      case "mods.reorder":
      case "mods2.reorder": {
        const p = payload as { orderedIds?: string[] };
        const key = cmd === "mods2.reorder" ? "mods2" : "mods";
        const current = (key === "mods2" ? state.mods2 : state.mods) || [];
        const byId = new Map(current.map((m) => [m.id, m]));
        const ordered: typeof current = [];
        for (const id of p.orderedIds || []) {
          const item = byId.get(id);
          if (item) ordered.push(item);
        }
        for (const item of current) {
          if (!ordered.includes(item)) ordered.push(item);
        }
        if (key === "mods2") state.mods2 = ordered;
        else state.mods = ordered;
        pushState();
        return undefined as Commands[K]["out"];
      }
      default:
        return undefined as Commands[K]["out"];
    }
  };

  const subscribe = <E extends EventName>(event: E, cb: (p: Events[E]) => void) => {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event)!.add(cb as (p: unknown) => void);
    return () => {
      listeners.get(event)?.delete(cb as (p: unknown) => void);
    };
  };

  return { call, subscribe };
}
