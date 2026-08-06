(() => {
  const root = document.querySelector("#app");
  let bridge = null;
  let lastRenderedPage = "";
  let state = {
    locale: "ru",
    page: "confirm",
    installPath: "",
    version: "3.0.0",
    progress: 0,
    status: "",
    error: "",
  };

  const L = (ru, en) => state.locale === "ru" ? ru : en;
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const call = (command, payload = {}) => new Promise((resolve, reject) => {
    if (!bridge) return reject(new Error("Bridge is unavailable"));
    bridge.call(command, JSON.stringify(payload), (raw) => {
      const result = JSON.parse(raw || "{}");
      if (result.error) reject(new Error(result.error));
      else resolve(result.value);
    });
  });

  const stepIndex = () => (state.page === "done" ? 2 : state.page === "progress" ? 1 : 0);
  const stepsBar = () => {
    const active = stepIndex();
    return `<div class="steps">${[0, 1, 2].map((index) => {
      const cls = index < active ? "done" : index === active ? "active" : "";
      return `<div class="step-dot ${cls}"></div>`;
    }).join("")}</div>`;
  };

  const doneMarkSvg = `<div class="done-mark" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 16 16" fill="none"><path d="M3.2 8.6l2.4 2.5l7.2-6.2" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg></div>`;

  const frame = (content, buttons) => `
    <div class="window">
      <header class="titlebar" data-drag>
        <div class="brand">
          <img src="../ui_assets/icons/app.png" alt="">
          <span>Zapret Hub</span>
          <small>${L("Удаление", "Uninstall")}</small>
        </div>
        <div class="window-controls">
          <button class="window-button" data-command="window.minimize" aria-label="Minimize"><svg width="12" height="12"><rect x="2" y="6" width="8" height="1" fill="currentColor"/></svg></button>
          <button class="window-button close" data-command="window.close" aria-label="Close"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3"><path d="M3 3l6 6M9 3l-6 6"/></svg></button>
        </div>
      </header>
      ${content}
      <footer class="footer">${buttons}</footer>
    </div>`;

  const btn = (label, action, cls = "") => `<button class="button ${cls}" data-action="${action}">${label}</button>`;

  const patchProgressDom = () => {
    const bar = root.querySelector(".progress-value");
    const statusEl = root.querySelector(".progress-status");
    const numberEl = root.querySelector(".progress-number");
    if (!bar || !statusEl || !numberEl) return false;
    const pct = Math.max(0, Math.min(100, Number(state.progress) || 0));
    bar.style.width = `${pct}%`;
    statusEl.textContent = state.status || L("Подготовка…", "Preparing…");
    numberEl.textContent = `${Math.round(pct)}%`;
    return true;
  };

  const confirmPage = () => frame(`
    <main class="view">
      ${stepsBar()}
      <div class="page-head">
        <h1>${L("Удалить Zapret Hub?", "Remove Zapret Hub?")}</h1>
        <p>${L("Будут удалены приложение, данные, ярлыки и запись в Параметрах Windows. Отменить нельзя.", "This removes the app, data, shortcuts, and the Windows Settings entry. This cannot be undone.")}</p>
      </div>
      <section class="panel">
        <div class="row"><span class="row-label">${L("Папка установки", "Install folder")}</span><span class="row-value strong">${esc(state.installPath)}</span></div>
        <div class="row"><span class="row-label">${L("Данные", "User data")}</span><span class="row-value">%LOCALAPPDATA%\\Zapret_Hub</span></div>
        <div class="row"><span class="row-label">${L("Также", "Also")}</span><span class="row-value">${L("ярлыки, автозапуск, реестр", "shortcuts, autostart, registry")}</span></div>
      </section>
      ${state.error ? `<div class="error">${esc(state.error)}</div>` : ""}
    </main>`, btn(L("Отмена", "Cancel"), "window.close") + btn(L("Удалить", "Remove"), "uninstall.start", "danger"));

  const progressPage = () => {
    const pct = Math.max(0, Math.min(100, Number(state.progress) || 0));
    return frame(`
    <main class="view view-progress">
      ${stepsBar()}
      <div class="page-head">
        <h1>${L("Удаление…", "Removing…")}</h1>
        <p>${L("Не закрывайте окно до завершения.", "Do not close this window until finished.")}</p>
      </div>
      <div class="progress-block">
        <div class="progress-track"><div class="progress-value" style="width:${pct}%"></div></div>
        <div class="progress-meta">
          <div class="progress-status">${esc(state.status || L("Подготовка…", "Preparing…"))}</div>
          <div class="progress-number">${Math.round(pct)}%</div>
        </div>
      </div>
      ${state.error ? `<div class="error">${esc(state.error)}</div>` : ""}
    </main>`, `<button class="button" disabled>${L("Удаление…", "Removing…")}</button>`);
  };

  const donePage = () => frame(`
    <main class="view">
      ${stepsBar()}
      <div class="page-head">
        ${doneMarkSvg}
        <h1 style="margin-top:10px">${L("Zapret Hub удалён", "Zapret Hub removed")}</h1>
        <p>${L("Приложение и связанные данные удалены с этого компьютера.", "The app and related data have been removed from this computer.")}</p>
      </div>
    </main>`, btn(L("Закрыть", "Close"), "window.close", "primary"));

  function render() {
    if (state.page === "progress") root.innerHTML = progressPage();
    else if (state.page === "done") root.innerHTML = donePage();
    else root.innerHTML = confirmPage();
    lastRenderedPage = state.page;
  }

  const refresh = () => {
    if (state.page === "progress" && lastRenderedPage === "progress" && patchProgressDom()) return;
    render();
  };

  root.addEventListener("pointerdown", (event) => {
    if (event.button === 0 && event.target.closest("[data-drag]") && !event.target.closest("button")) call("window.startDrag");
  });
  root.addEventListener("click", async (event) => {
    const element = event.target.closest("[data-action],[data-command]");
    if (!element) return;
    const action = element.dataset.action || element.dataset.command;
    try {
      if (action === "uninstall.start") {
        state.page = "progress";
        state.progress = 0;
        state.status = L("Остановка процессов…", "Stopping processes…");
        state.error = "";
        render();
        await call("uninstall.start");
        return;
      }
      await call(action);
    } catch (error) {
      state.error = error.message;
      state.page = "confirm";
      render();
    }
  });

  const connect = async (channelBridge) => {
    bridge = channelBridge;
    bridge.event.connect((name, raw) => {
      const payload = JSON.parse(raw || "{}");
      if (name === "progress") {
        state.progress = payload.value ?? state.progress;
        if (payload.status) state.status = payload.status;
      } else if (name === "done") {
        state.page = "done";
        state.progress = 100;
        state.status = L("Готово", "Done");
        state.error = "";
      } else if (name === "error") {
        state.error = payload.message;
        state.page = "confirm";
      }
      refresh();
    });
    state = { ...state, ...(await call("state.get")) };
    document.documentElement.lang = state.locale;
    render();
  };

  if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {
    new QWebChannel(qt.webChannelTransport, async (channel) => {
      await connect(channel.objects.uninstallerBridge);
    });
  } else {
    const listeners = [];
    connect({
      event: { connect: (listener) => listeners.push(listener) },
      call: (command, raw, callback) => {
        let value = null;
        if (command === "state.get") {
          value = {
            locale: "ru",
            page: "confirm",
            installPath: "C:\\Program Files\\Zapret Hub",
            version: "3.0.0",
            progress: 0,
            status: "",
            error: "",
          };
        } else if (command === "uninstall.start") {
          setTimeout(() => listeners.forEach((l) => l("progress", JSON.stringify({ value: 40, status: "Removing…" }))), 200);
          setTimeout(() => listeners.forEach((l) => l("done", "{}")), 700);
        }
        callback(JSON.stringify({ value }));
      },
    });
  }
})();
