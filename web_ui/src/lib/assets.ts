export function uiAssetUrl(path: string) {
  const normalized = path.replace(/^\/+/, "");
  return window.location.protocol === "file:" ? `../../ui_assets/${normalized}` : `/${normalized}`;
}
