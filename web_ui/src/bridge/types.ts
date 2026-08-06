// Zapret Hub bridge contract — shared with Python side.
export type RuntimeId = "zapret" | "goshkow-vpn" | "zapret2" | "none";
export type ComponentId = "zapret" | "zapret2" | "goshkow-vpn" | "tg-ws-proxy" | "xbox-dns";
export type Locale = "ru" | "en";
export type RuntimeStatus = "off" | "starting" | "stopping" | "on" | "error";
export type ComponentStatus = "off" | "on" | "starting" | "stopping" | "error" | "updating";

export type FileKind =
  | "domains"
  | "exclusions"
  | "ip-lists"
  | "ip-exclusions"
  | "general"
  | "hosts"
  | "advanced";

export type LogSource = "app" | "zapret" | "zapret2" | "vpn" | "tg";

export interface Service {
  id: string;
  name: string;
  description: string;
  category?: string;
}

export interface ComponentInfo {
  id: ComponentId;
  name: string;
  version: string;
  status: ComponentStatus;
  /** Whether the component is enabled to follow main power (aux) / selected. */
  enabled?: boolean;
  description: string;
  config: string; // human-readable summary line
  externalUrl?: string;
  meta?: Record<string, string>;
}

export interface Mod {
  id: string;
  name: string;
  author?: string;
  description?: string;
  enabled: boolean;
  compatibleFiles: FileKind[];
  source: "folder" | "zip" | "files" | "github" | "custom";
  createdAt: number;
  iconUrl?: string;
  marketplaceSlug?: string;
  sourceUrl?: string;
  version?: string;
  compatibility?: "zapret" | "zapret2";
  runtime?: "zapret2";
  updateAvailable?: boolean;
  latestVersion?: string;
  updateChangelog?: string;
  versionId?: number | null;
  diskSize?: number;
}

export type MarketplaceUpdateItem = {
  slug: string;
  title: string;
  author?: string;
  summary?: string;
  iconUrl?: string;
  projectUrl?: string;
  compatibility?: string;
  currentVersion?: string;
  latestVersion: string;
  changelog?: string;
  versionId?: number | null;
  modId?: string;
};

export interface FileEntry {
  kind: FileKind;
  name: string;
  content: string;
  updatedAt: number;
}

export interface LogEntry {
  id: string;
  source: LogSource;
  level: "info" | "warn" | "error" | "debug";
  message: string;
  ts: number;
}

export interface Notification {
  id: string;
  title: string;
  body?: string;
  ts: number;
  read: boolean;
  level: "info" | "warn" | "error" | "success";
}

export interface Settings {
  autoStart: boolean;
  minimizeToTray: boolean;
  autoRunComponents: boolean;
  trayNotification: boolean;
  checkUpdates: boolean;
  checkModUpdates: boolean;
  checkComponentUpdates: boolean;
  windowsNotifications: boolean;
  notificationsEnabled: boolean;
  hardwareAcceleration: boolean;
  soundsEnabled: boolean;
  soundsClickEnabled: boolean;
  soundsVolume: "normal" | "louder" | "quieter";
  sidebarCollapsed: boolean;
  quickAccessWidget: "analysis" | "logs";
  scrollModeSwitch: boolean;
  uiScale: "0.75" | "1" | "1.25";
  discordRpcEnabled?: boolean;
  discordRpcClientId?: string;
  discordRpcStatus?: { state?: string; error?: string; connected?: string };
  zapret: {
    ipsetMode: string;
    gameFilterMode: string;
    gamingSet: string;
    udpExclusions: string;
    selectedGeneral: string;
    controlMode: "manual" | "auto";
    trustedGeneral?: string;
    generals: { id: string; name: string }[];
  };
  zapret2: {
    controlMode: "manual" | "auto";
    tcpPorts: string;
    udpPorts: string;
    rawFilter: string;
    luaStrategy: string;
    strategyId?: string;
    youtubeDiscordBypass?: boolean;
  };
  vpn: {
    subscriptionUrl: string;
    subscriptionState: string;
    selectedServerId: string;
    servers: { id: string; name: string }[];
    tunEnabled: boolean;
    routingMode: string;
    systemProxyMode: string;
    processes: string;
    processesExcludeMode: boolean;
  };
  tg: {
    host: string;
    port: number;
    secret: string;
    dcIp: string;
    cfProxyEnabled: boolean;
    cfProxyPriority: boolean;
    cfProxyDomain: string;
    fakeTlsDomain: string;
    bufferKb: number;
    poolSize: number;
  };
  dns: {
    profile: "dhcp" | "xbox" | "cloudflare" | "adguard" | "google" | "yandex";
  };
  theme: string;
}

export interface ComponentReleaseVersion {
  version: string;
  tag?: string;
  publishedAt?: string;
  prerelease?: boolean;
  recommended?: boolean;
  current?: boolean;
}

export interface ComponentUpdateCheck {
  requestId: string;
  id: ComponentId;
  available: boolean;
  currentVersion: string;
  latestVersion: string;
  recommendedVersion?: string;
  versions?: ComponentReleaseVersion[];
  error?: string;
}

export interface OrchestratorStatus {
  mode: "manual" | "auto";
  status: string;
  statusText: string;
  /** Friendly domain/app hint while tuning (not raw knobs). */
  detail?: string;
  isAuto: boolean;
  running?: boolean;
  zapretActive?: boolean;
  busy?: boolean;
  phase?: string;
  /** Active bypass backend the orchestrator is driving. */
  backend?: "zapret" | "zapret2";
}

/** Result of orchestrator.bootstrap (onboarding Auto path). */
export interface OrchestratorBootstrapResult {
  ok?: boolean;
  started?: boolean;
  mode?: "manual" | "auto";
  trustedGeneral?: string;
  services?: string[];
  ipset?: string;
  stage?: number;
  deferred?: boolean;
  error?: string;
}

export interface AppState {
  runtime: { active: RuntimeId; order: RuntimeId[]; status: RuntimeStatus };
  services: { available: Service[]; selected: string[] };
  components: Record<ComponentId, ComponentInfo>;
  mods: Mod[];
  mods2?: Mod[];
  files: FileEntry[];
  files2?: FileEntry[];
  logs: LogEntry[];
  settings: Settings;
  notifications: Notification[];
  orchestrator: OrchestratorStatus;
  onboarding: { completed: boolean; isUpdate: boolean; forceOpen?: boolean; initialMode?: RuntimeId };
  ui: { locale: Locale; theme: string; hasValidVpnKey: boolean };
}

// ---------- Commands (typed IN → OUT) ----------
export type Commands = {
  "ui.ready": { in: void; out: void };
  "state.get": { in: void; out: AppState };
  "window.minimize": { in: void; out: void };
  "window.startDrag": { in: void; out: void };
  "window.edit": { in: { action: "cut" | "copy" | "paste" | "select-all" }; out: void };
  "window.close": { in: void; out: void };
  "onboarding.open": { in: { mode: RuntimeId }; out: void };
  "runtime.select": { in: { id: RuntimeId; keepPower?: boolean }; out: void };
  "runtime.power": { in: { on: boolean }; out: void };
  "component.toggle": { in: { id: ComponentId; on: boolean }; out: void };
  "component.check-update": { in: { id: ComponentId; requestId: string }; out: void };
  "component.install-update": { in: { id: ComponentId; version?: string }; out: void };
  "component.check-updates-all": { in: void; out: void };
  "component.install-updates-all": { in: { ids: ComponentId[] }; out: void };
  "component.configure": { in: { id: ComponentId; patch: Record<string, unknown> }; out: void };
  "component.open-external": { in: { id: ComponentId }; out: void };
  "tg.connect": { in: void; out: void };
  "app.check-updates": { in: void; out: void };
  "app.apply-update": { in: { scheduleNextLaunch?: boolean }; out: void };
  "zapret.rebuild-runtime": { in: void; out: void };
  "vpn.refresh-subscription": { in: void; out: void };
  "vpn.import-subscription": { in: { url: string }; out: { subscriptionState: string } };
  "vpn.select-server": { in: { id: string }; out: void };
  "dns.select-profile": { in: { profile: Settings["dns"]["profile"] }; out: void };
  "clipboard.read": { in: void; out: string };
  "services.set": { in: { selected: string[] }; out: void };
  "settings.apply": { in: { patch: Partial<Settings> & { locale?: Locale; theme?: string; modeOrder?: RuntimeId[] } }; out: void };
  "files.load": { in: { kind: FileKind; name?: string }; out: FileEntry };
  "files.save": { in: { kind: FileKind; name: string; content: string }; out: void };
  "files.rename": { in: { kind: FileKind; from: string; to: string }; out: void };
  "files.create": { in: { kind: FileKind; name: string }; out: FileEntry };
  "files.list": { in: { kind: FileKind }; out: FileEntry[] };
  "files2.load": { in: { kind: FileKind; name?: string }; out: FileEntry };
  "files2.save": { in: { kind: FileKind; name: string; content: string }; out: void };
  "files2.rename": { in: { kind: FileKind; from: string; to: string }; out: void };
  "files2.create": { in: { kind: FileKind; name: string }; out: FileEntry };
  "files2.list": { in: { kind: FileKind }; out: FileEntry[] };
  "mods.import": { in: { source: Mod["source"]; ref?: string }; out: Mod };
  "mods.create": { in: { name: string }; out: Mod };
  "mods.toggle": { in: { id: string; on: boolean }; out: void };
  "mods.edit": { in: { id: string; patch: Partial<Mod> }; out: void };
  "mods.export": { in: { id: string }; out: void };
  "mods.delete": { in: { id: string }; out: { mods: Mod[]; mods2: Mod[] } };
  "mods.reorder": { in: { orderedIds: string[] }; out: void };
  "mods.files": { in: { id: string }; out: Array<{ path: string; size: number }> };
  "mods.file-read": { in: { id: string; path: string }; out: string };
  "mods.file-write": { in: { id: string; path: string; content: string }; out: void };
  "mods.file-delete": { in: { id: string; path: string }; out: void };
  "mods2.import": { in: { source: Mod["source"]; ref?: string }; out: Mod };
  "mods2.create": { in: { name: string }; out: Mod };
  "mods2.toggle": { in: { id: string; on: boolean }; out: void };
  "mods2.edit": { in: { id: string; patch: Partial<Mod> }; out: void };
  "mods2.export": { in: { id: string }; out: void };
  "mods2.delete": { in: { id: string }; out: { mods: Mod[]; mods2: Mod[] } };
  "mods2.reorder": { in: { orderedIds: string[] }; out: void };
  "mods2.files": { in: { id: string }; out: Array<{ path: string; size: number }> };
  "mods2.file-read": { in: { id: string; path: string }; out: string };
  "mods2.file-write": { in: { id: string; path: string; content: string }; out: void };
  "mods2.file-delete": { in: { id: string; path: string }; out: void };
  "logs.clear": { in: { source?: LogSource }; out: void };
  "logs.export": { in: { source?: LogSource }; out: void };
  "logs.copy": { in: { source?: LogSource }; out: void };
  "logs.get": { in: void; out: LogEntry[] };
  "marketplace.list": {
    in: {
      q?: string;
      compatibility?: "" | "zapret" | "zapret2";
      category?: string;
      sort?: "relevance" | "popular" | "downloads" | "updated" | "newest";
      page?: number;
      limit?: number;
      refresh?: boolean;
    };
    out: MarketplaceListResult;
  };
  "marketplace.get": { in: { slug: string }; out: MarketplaceProjectResult };
  "marketplace.image": { in: { url: string }; out: { url: string; dataUrl: string } };
  "marketplace.installed": { in: void; out: { mods: Mod[]; mods2: Mod[] } };
  "marketplace.download": {
    in: {
      slug: string;
      versionId?: number | null;
      title?: string;
      compatibility?: string;
      author?: string;
      summary?: string;
      iconUrl?: string;
      projectUrl?: string;
      marketplaceVersion?: string;
      latestVersion?: string;
      allowUpdate?: boolean;
      update?: boolean;
    };
    out: {
      queued: boolean;
      slug: string;
      jobId?: string;
      modId?: string;
      alreadyInstalled?: boolean;
      alreadyQueued?: boolean;
      updating?: boolean;
      pending: string[];
    };
  };
  "marketplace.remove": {
    in: { slug: string };
    out: { ok: boolean; slug: string; removed: string[]; mods: Mod[]; mods2: Mod[] };
  };
  "marketplace.queue": { in: void; out: MarketplaceQueueStatus };
  "marketplace.cancel": { in: { slug?: string; jobId?: string }; out: MarketplaceQueueStatus };
  "marketplace.pause": { in: { slug?: string; jobId?: string }; out: MarketplaceQueueStatus };
  "marketplace.resume": { in: { slug?: string; jobId?: string }; out: MarketplaceQueueStatus };
  "marketplace.reorder-queue": { in: { orderedSlugs: string[] }; out: MarketplaceQueueStatus };
  "marketplace.repair-covers": { in: void; out: void };
  "marketplace.open-url": { in: { url: string }; out: void };
  "marketplace.check-updates": {
    in: void;
    out: { ok: boolean; updates: MarketplaceUpdateItem[]; notify: MarketplaceUpdateItem[] };
  };
  "marketplace.updates-status": { in: void; out: { ok: boolean; updates: MarketplaceUpdateItem[] } };
  "marketplace.dismiss-updates": {
    in: { updates?: { slug: string; latestVersion?: string; version?: string }[] };
    out: { ok: boolean; dismissals: Record<string, string> };
  };
  "notifications.dismiss": { in: { id: string }; out: void };
  "notifications.markRead": { in: { id?: string }; out: void };
  "onboarding.complete": {
    in: { mode?: RuntimeId; selected?: string[]; dismiss?: boolean } | void;
    out: void;
  };
  "onboarding.configure": { in: { selected?: string[] } | void; out: void };
  "onboarding.cancel": { in: void; out: void };
  "orchestrator.status": { in: void; out: OrchestratorStatus };
  "orchestrator.setMode": { in: { mode: "manual" | "auto"; backend?: "zapret" | "zapret2" }; out: OrchestratorStatus };
  /** Clear Auto overlay + knowledge so Auto can learn from scratch. Battle lists stay intact. */
  "orchestrator.resetAuto": {
    in: { backend?: "zapret" | "zapret2" } | void;
    out: { started: boolean } | { ok: boolean; overlay?: boolean; knowledge?: boolean; memory?: boolean; error?: string };
  };
  /** Auto onboarding bootstrap (YT+Discord probes, trusted general). Backend runs async. */
  "orchestrator.bootstrap": {
    in: { youtube?: boolean; discord?: boolean } | void;
    out: { started: boolean } | OrchestratorBootstrapResult;
  };
};

export type CommandName = keyof Commands;

// ---------- Events (server-pushed) ----------
export type Events = {
  "state.changed": AppState;
  "runtime.status": { status: RuntimeStatus; active?: RuntimeId };
  "logs.append": LogEntry;
  "notification.new": Notification;
  "toast.show": { id: string; message: string; kind?: "info" | "success" | "error" | "warn" };
  "toast.dismiss": { id: string };
  "onboarding.progress": { current: number; total: number; name: string; overallCurrent?: number; overallTotal?: number };
  "onboarding.configuration": { status: "success" | "error"; name: string; passed?: number; total?: number; error?: string };
  "component.update-check": ComponentUpdateCheck;
  "component.update-result": {
    id: ComponentId;
    status: "started" | "success" | "up-to-date" | "error";
    version?: string;
    error?: string;
  };
  "component.updates-available": { updates: Array<{ id: ComponentId; name: string; currentVersion: string; latestVersion: string }> };
  "orchestrator.status": OrchestratorStatus;
  /** Fired when Auto bootstrap finishes (success or deferred Stage-1 stub). */
  "orchestrator.bootstrap": OrchestratorBootstrapResult;
  /**
   * Expected orchestrator event names (backend / Stage 4+):
   * - orchestrator.conflict — only when a real conflict is classified
   * - orchestrator.longPick — optional server-side long-tune notify (UI also timers locally)
   * Backend may also push friendly copy via toast.show / notification.new.
   */
  "orchestrator.conflict": {
    messageRu: string;
    messageEn: string;
    domain?: string;
    app?: string;
  };
  "orchestrator.longPick": {
    domain?: string;
    messageRu?: string;
    messageEn?: string;
  };
  "app.update-available": {
    currentVersion: string;
    latestVersion: string;
    currentDigest?: string;
    latestDigest?: string;
    changelog: string;
    htmlUrl: string;
    isHotfix?: boolean;
    demo?: boolean;
  };
  "app.update-progress": {
    phase: "download" | "verify" | "extract" | "ready";
    percent: number;
    downloadedBytes?: number;
    totalBytes?: number;
    messageRu: string;
    messageEn: string;
  };
  "vpn.setup-required": {
    reason?: string;
  };
  "marketplace.navigate": {
    action: string;
    slug: string;
    versionId?: string;
  };
  "marketplace.download-progress": {
    jobId?: string;
    slug: string;
    status: string;
    message?: string;
    title?: string;
    iconUrl?: string;
    compatibility?: string;
    progress?: number;
    bytesDone?: number;
    bytesTotal?: number;
    error?: string;
    pending?: string[];
    modId?: string;
    mods?: Mod[];
    mods2?: Mod[];
  };
  "marketplace.queue": MarketplaceQueueStatus;
  "marketplace.mods-changed": { mods: Mod[]; mods2: Mod[] };
  "marketplace.result": {
    requestId: string;
    ok: boolean;
    command?: string;
    value?: unknown;
    error?: string;
  };
  "marketplace.updates-available": {
    updates: MarketplaceUpdateItem[];
  };
};

export type MarketplaceCompatibility = "zapret" | "zapret2";

export type MarketplaceDownloadStatus =
  | "queued"
  | "starting"
  | "downloading"
  | "paused"
  | "installing"
  | "done"
  | "error"
  | "cancelled";

export interface MarketplaceQueueItem {
  jobId: string;
  slug: string;
  status: MarketplaceDownloadStatus | string;
  message?: string;
  title?: string;
  iconUrl?: string;
  compatibility?: string;
  progress?: number;
  bytesDone?: number;
  bytesTotal?: number;
  error?: string;
}

export interface MarketplaceQueueStatus {
  busy: boolean;
  activeSlug?: string;
  overallProgress?: number;
  pending: string[];
  items: MarketplaceQueueItem[];
  installRevision?: number;
  lastCompleted?: {
    revision: number;
    slug: string;
    modId?: string;
    compatibility?: string;
  };
}

export interface MarketplaceCard {
  id: number;
  slug: string;
  title: string;
  summary: string;
  author: string;
  iconUrl: string;
  projectUrl: string;
  apiUrl: string;
  downloadUrl: string;
  compatibility: MarketplaceCompatibility;
  categories: string[];
  license: string;
  downloads: number;
  downloadsCompact: string;
  likes: number;
  favorites: number;
  followers: number;
  comments: number;
  featured: boolean;
  updatedAt: number;
  publishedAt: number;
  latestVersionSize?: number;
}

export interface MarketplaceVersion {
  id: number;
  version: string;
  changelog: string;
  size: number;
  sha256: string;
  downloads: number;
  publishedAt?: number | string | null;
  compatibility: string;
}

export interface MarketplaceProject extends MarketplaceCard {
  body?: string;
  bodyHtml?: string;
  links?: { label?: string; url?: string }[];
  versions?: MarketplaceVersion[];
  dependencies?: unknown[];
  screenshots?: { url?: string; caption?: string }[];
  commentItems?: unknown[];
}

export interface MarketplaceListResult {
  ok: boolean;
  projects: MarketplaceCard[];
  total: number;
  page: number;
  pages: number;
  categories: string[];
}

export interface MarketplaceProjectResult {
  ok: boolean;
  project: MarketplaceProject;
}

export type EventName = keyof Events;

export interface ZapretHubBridge {
  call<K extends CommandName>(cmd: K, payload: Commands[K]["in"]): Promise<Commands[K]["out"]>;
  subscribe<E extends EventName>(event: E, cb: (payload: Events[E]) => void): () => void;
}

declare global {
  interface Window {
    zapretHubBridge?: ZapretHubBridge;
  }
}
