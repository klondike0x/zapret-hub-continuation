(() => {
  const root = document.querySelector("#app");
  let bridge = null;
  let progressWatch = null;
  let installStartedAt = 0;
  let connectWatchFired = false;
  let snapshotPollBusy = false;
  let lastRenderedPage = "";
  let lastFailed = false;
  const CONNECT_WATCHDOG_MS = 15000;
  const SNAPSHOT_POLL_MS = 500;
  let state = {
    locale: "ru",
    mode: "install",
    page: "welcome",
    installed: false,
    selectedAction: "update",
    selectedPath: "",
    resolvedPath: "",
    progress: 0,
    status: "",
    version: "3.0.0",
    remoteVersion: "",
    createDesktop: true,
    createStartMenu: true,
    launchAfter: true,
    error: "",
    failed: false,
    termsText: "",
    termsAccepted: false,
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

  const clearProgressWatch = () => {
    if (progressWatch) {
      clearInterval(progressWatch);
      progressWatch = null;
    }
    snapshotPollBusy = false;
  };

  const connectTimeoutMessage = () => L(
    "Не удалось подключиться к goshkow.com за 15 секунд. Проверьте сеть и попробуйте снова.",
    "Could not connect to goshkow.com within 15 seconds. Check the network and try again."
  );

  const stillConnecting = (snap) => {
    const progress = Number(snap?.progress ?? state.progress ?? 0);
    const phase = String(snap?.phase || "");
    const status = String(snap?.status || state.status || "");
    if (progress >= 6) return false;
    if (phase === "connecting") return true;
    if (phase === "downloading" || phase === "installing" || phase === "done") return false;
    return /подключ|connect|метаданн|metadata|запуск загрузки|starting download|запрос|requesting/i.test(status) || progress < 6;
  };

  /** Both flows have four steps; only a fresh install requires agreement acceptance. */
  const totalSteps = () => 4;

  const stepIndex = () => {
    // Fresh: welcome → agreement → path → progress/done.
    // Existing: welcome → maintenance → path|confirm|uninstall → progress/done.
    if (state.page === "welcome") return 0;
    if (state.page === "agreement") return 1;
    if (state.page === "maintenance") return 1;
    if (state.page === "path" || state.page === "confirm" || state.page === "uninstall") {
      return 2;
    }
    if (state.page === "progress" || state.page === "done") {
      return 3;
    }
    return 0;
  };

  const stepsBar = () => {
    const active = stepIndex();
    const count = totalSteps();
    return `<div class="steps">${Array.from({ length: count }, (_, index) => {
      const cls = index < active ? "done" : index === active ? "active" : "";
      return `<div class="step-dot ${cls}"></div>`;
    }).join("")}</div>`;
  };

  const applySnapshot = (snap) => {
    if (!snap || typeof snap !== "object") return { progressChanged: false, pageChanged: false };
    let progressChanged = false;
    let pageChanged = false;
    const nextProgress = Number(snap.progress);
    if (Number.isFinite(nextProgress) && nextProgress !== state.progress) {
      state.progress = nextProgress;
      progressChanged = true;
    }
    if (typeof snap.status === "string" && snap.status && snap.status !== state.status) {
      state.status = snap.status;
      progressChanged = true;
    }
    if (snap.done) {
      clearProgressWatch();
      if (state.page !== "done") {
        state.page = "done";
        state.progress = 100;
        state.status = L("Готово", "Done");
        state.error = "";
        state.failed = false;
        pageChanged = true;
      }
      return { progressChanged, pageChanged };
    }
    if (snap.failed || snap.error) {
      const message = String(snap.error || snap.status || L("Неизвестная ошибка.", "Unknown error."));
      if (!state.failed || state.error !== message) {
        state.failed = true;
        state.error = message;
        state.status = message;
        state.page = "progress";
        pageChanged = true;
      }
      clearProgressWatch();
      return { progressChanged, pageChanged };
    }
    if (snap.phase === "aborted") {
      clearProgressWatch();
      const nextPage = state.selectedAction === "remove" ? "uninstall" : "path";
      if (state.page !== nextPage) {
        state.page = nextPage;
        state.progress = 0;
        state.status = "";
        state.error = "";
        state.failed = false;
        pageChanged = true;
      }
      return { progressChanged, pageChanged };
    }
    return { progressChanged, pageChanged };
  };

  const patchProgressDom = () => {
    const bar = root.querySelector(".progress-value");
    const statusEl = root.querySelector(".progress-status");
    const numberEl = root.querySelector(".progress-number");
    if (!bar || !statusEl || !numberEl) return false;
    const pct = Math.max(0, Math.min(100, Number(state.progress) || 0));
    bar.style.width = `${pct}%`;
    statusEl.textContent = state.status || L("Подготовка…", "Preparing…");
    numberEl.textContent = `${Math.round(pct)}%`;
    const errorSlot = root.querySelector("[data-progress-error]");
    if (errorSlot) {
      if (state.error && state.failed) {
        errorSlot.hidden = false;
        errorSlot.textContent = state.error;
      } else {
        errorSlot.hidden = true;
        errorSlot.textContent = "";
      }
    }
    return true;
  };

  /** Full remount only on page / failure chrome changes — never on progress ticks. */
  const refresh = ({ force = false } = {}) => {
    const pageChanged = state.page !== lastRenderedPage;
    const failedChanged = state.failed !== lastFailed;
    if (!force && state.page === "progress" && !state.failed && !pageChanged && !failedChanged) {
      if (patchProgressDom()) return;
    }
    if (!force && state.page === "progress" && state.failed && !pageChanged && failedChanged === false && lastRenderedPage === "progress" && lastFailed) {
      if (patchProgressDom()) return;
    }
    render();
  };

  const enforceConnectWatchdog = async () => {
    if (connectWatchFired || state.failed || state.page !== "progress") return false;
    if (!stillConnecting()) return false;
    if (!installStartedAt || (Date.now() - installStartedAt) < CONNECT_WATCHDOG_MS) return false;
    connectWatchFired = true;
    state.failed = true;
    state.error = connectTimeoutMessage();
    state.status = state.error;
    clearProgressWatch();
    try { await call("install.abort"); } catch (_) {}
    return true;
  };

  const pollSnapshotOnce = async () => {
    if (snapshotPollBusy || state.page !== "progress") return;
    snapshotPollBusy = true;
    try {
      const snap = await call("install.snapshot");
      const { progressChanged, pageChanged } = applySnapshot(snap);
      const timedOut = await enforceConnectWatchdog();
      if (pageChanged || timedOut || state.failed) {
        refresh({ force: pageChanged || timedOut || state.failed });
      } else if (progressChanged) {
        refresh();
      }
    } catch (_) {
      const timedOut = await enforceConnectWatchdog();
      if (timedOut) refresh({ force: true });
    } finally {
      snapshotPollBusy = false;
    }
  };

  const armProgressWatch = () => {
    clearProgressWatch();
    installStartedAt = Date.now();
    connectWatchFired = false;
    progressWatch = setInterval(() => {
      if (state.page !== "progress") {
        clearProgressWatch();
        return;
      }
      pollSnapshotOnce();
    }, SNAPSHOT_POLL_MS);
    pollSnapshotOnce();
  };

  const frame = (content, buttons = "") => `
    <div class="window">
      <header class="titlebar" data-drag>
        <div class="brand">
          <img src="../ui_assets/icons/app.png" alt="">
          <span>Zapret Hub</span>
          <small>${L("Установщик", "Installer")}</small>
        </div>
        <div class="window-controls">
          <button class="window-button" data-command="window.minimize" aria-label="Minimize"><svg width="12" height="12"><rect x="2" y="6" width="8" height="1" fill="currentColor"/></svg></button>
          <button class="window-button close" data-command="window.close" aria-label="Close"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3"><path d="M3 3l6 6M9 3l-6 6"/></svg></button>
        </div>
      </header>
      ${content}
      ${buttons ? `<footer class="footer">${buttons}</footer>` : `<footer class="footer"></footer>`}
    </div>`;

  const btn = (label, action, cls = "", disabled = false) => `<button class="button ${cls}" data-action="${action}" ${disabled ? "disabled" : ""}>${label}</button>`;

  function render() {
    let body = "";
    let buttons = "";
    if (state.page === "welcome") {
      ({ body, buttons } = welcomePage());
    } else if (state.page === "agreement") {
      ({ body, buttons } = agreementPage());
    } else if (state.page === "maintenance") {
      ({ body, buttons } = maintenancePage());
    } else if (state.page === "path") {
      ({ body, buttons } = pathPage());
    } else if (state.page === "confirm") {
      ({ body, buttons } = confirmPage());
    } else if (state.page === "progress") {
      ({ body, buttons } = progressPage());
    } else if (state.page === "uninstall") {
      ({ body, buttons } = uninstallPage());
    } else {
      ({ body, buttons } = donePage(state.selectedAction === "remove"));
    }
    root.innerHTML = frame(body, buttons);
    lastRenderedPage = state.page;
    lastFailed = state.failed;
  }

  const welcomePage = () => ({
    body: `
      <main class="view welcome-view">
        ${stepsBar()}
        <div class="welcome-center">
          <h1>${L("Установщик Zapret Hub", "Zapret Hub Installer")}</h1>
          <p>${L(
            "Zapret Hub — инструмент управления сетевыми подключениями, DNS и совместимыми компонентами.",
            "Zapret Hub manages network connections, DNS settings, and compatible components."
          )}</p>
          <div class="meta-quiet">${L("Установщик", "Installer")} ${esc(state.version)}${state.remoteVersion ? ` · ${L("на сайте", "online")} ${esc(state.remoteVersion)}` : ""}</div>
        </div>
      </main>`,
    buttons: btn(L("Далее", "Next"), "welcome.next", "primary"),
  });

  const agreementPage = () => ({
    body: `
      <main class="view agreement-view">
        ${stepsBar()}
        <div class="page-head">
          <h2>${L("Пользовательское соглашение", "Terms of use")}</h2>
          <p>${L("Прочитайте условия перед продолжением установки.", "Read the terms before continuing.")}</p>
        </div>
        <pre class="terms-document">${esc(state.termsText || L("Текст соглашения недоступен. Закройте установщик и загрузите его заново из официального источника.", "The terms could not be loaded. Close the installer and download it again from the official source."))}</pre>
        <label class="terms-accept">
          <input id="terms-accepted" type="checkbox" ${state.termsAccepted ? "checked" : ""}>
          <span>${L("Я прочитал(а) и принимаю пользовательское соглашение", "I have read and accept the terms of use")}</span>
        </label>
      </main>`,
    buttons: btn(L("Назад", "Back"), "back") + btn(L("Далее", "Next"), "agreement.next", "primary", !state.termsAccepted || !state.termsText),
  });

  const maintenancePage = () => {
    const choices = [
      ["update", L("Обновить", "Update"), L("Обновить файлы, сохранив настройки и данные.", "Update files while keeping settings and data.")],
      ["reinstall", L("Переустановить", "Reinstall"), L("Удалить текущую копию и поставить заново.", "Remove the current copy and install fresh.")],
      ["remove", L("Удалить", "Remove"), L("Полностью убрать приложение с компьютера.", "Completely remove the app from this computer.")],
    ];
    return {
      body: `
        <main class="view">
          ${stepsBar()}
          <div class="page-head">
            <h2>${L("Уже установлено", "Already installed")}</h2>
            <p>${L("Выберите, что сделать с найденной установкой.", "Choose what to do with the existing installation.")}</p>
          </div>
          <div class="maintenance-grid">${choices.map(([id, title, description]) => `<button class="choice ${state.selectedAction === id ? "active" : ""}" data-select-action="${id}"><strong>${title}</strong><span>${description}</span></button>`).join("")}</div>
        </main>`,
      buttons: btn(L("Назад", "Back"), "back") + btn(L("Далее", "Next"), "maintenance.next", "primary"),
    };
  };

  const pathPage = () => ({
    body: `
      <main class="view">
        ${stepsBar()}
        <div class="page-head">
          <h2>${L(state.selectedAction === "update" ? "Папка обновления" : "Папка установки", state.selectedAction === "update" ? "Update folder" : "Install folder")}</h2>
          <p>${L("Можно оставить путь по умолчанию или выбрать другую папку.", "Keep the default path or choose another folder.")}</p>
        </div>
        <div class="path-block">
          <div class="path-label">${L("Папка", "Folder")}</div>
          <div class="path-row">
            <input class="path-input" id="install-path" value="${esc(state.selectedPath)}" spellcheck="false">
            ${btn(L("Обзор", "Browse"), "path.browse")}
          </div>
          <div class="resolved">${L("Будет установлено в", "Will install to")} <strong>${esc(state.resolvedPath)}</strong></div>
          <div class="options">
            <label class="option"><input id="opt-desktop" type="checkbox" ${state.createDesktop ? "checked" : ""}>${L("Ярлык на рабочем столе", "Desktop shortcut")}</label>
            <label class="option"><input id="opt-start" type="checkbox" ${state.createStartMenu ? "checked" : ""}>${L("Ярлык в меню Пуск", "Start Menu shortcut")}</label>
            <label class="option"><input id="opt-launch" type="checkbox" ${state.launchAfter ? "checked" : ""}>${L("Запустить после установки", "Launch after install")}</label>
          </div>
        </div>
        ${state.error ? `<div class="error">${esc(state.error)}</div>` : ""}
      </main>`,
    buttons: btn(L("Назад", "Back"), "back") + btn(L(state.selectedAction === "update" ? "Обновить" : "Установить", state.selectedAction === "update" ? "Update" : "Install"), "install.prepare", "primary"),
  });

  const confirmPage = () => ({
    body: `
      <main class="view">
        ${stepsBar()}
        <div class="page-head">
          <h1>${L("Переустановить Zapret Hub?", "Reinstall Zapret Hub?")}</h1>
          <p>${L("Текущие файлы приложения в папке установки будут заменены. Это действие нельзя отменить.", "Application files in the install folder will be replaced. This cannot be undone.")}</p>
        </div>
        <div class="confirm-note">${L("Настройки и пользовательские данные можно сохранить на предыдущем шаге, выбрав «Обновить» вместо переустановки.", "To keep settings and user data, go back and choose Update instead of Reinstall.")}</div>
        <div class="confirm-path">${esc(state.resolvedPath || state.selectedPath)}</div>
        ${state.error ? `<div class="error">${esc(state.error)}</div>` : ""}
      </main>`,
    buttons: btn(L("Назад", "Back"), "back") + btn(L("Переустановить", "Reinstall"), "install.confirm", "danger"),
  });

  const progressPage = () => {
    const title = state.failed
      ? L("Ошибка", "Error")
      : state.selectedAction === "remove"
        ? L("Удаление…", "Removing…")
        : state.selectedAction === "update"
          ? L("Обновление…", "Updating…")
          : L("Установка…", "Installing…");
    const subtitle = state.failed
      ? L("Операция остановлена. Можно повторить попытку или закрыть установщик.", "Operation stopped. You can retry or close the installer.")
      : L("Подождите немного — установка скоро завершится.", "Please wait — this will finish shortly.");
    const buttons = state.failed
      ? (state.selectedAction === "remove"
          ? btn(L("Назад", "Back"), "progress.back")
          : btn(L("Повторить", "Retry"), "progress.retry", "primary") + btn(L("Назад", "Back"), "progress.back"))
        + btn(L("Закрыть", "Close"), "window.close", "danger")
      : btn(L("Отмена", "Cancel"), "window.close", "danger");
    const pct = Math.max(0, Math.min(100, Number(state.progress) || 0));
    return {
      body: `
        <main class="view view-progress" data-page="progress">
          ${stepsBar()}
          <div class="page-head">
            <h1>${title}</h1>
            <p>${subtitle}</p>
          </div>
          <div class="progress-block">
            <div class="progress-track"><div class="progress-value" style="width:${pct}%"></div></div>
            <div class="progress-meta">
              <div class="progress-status">${esc(state.status || L("Подготовка…", "Preparing…"))}</div>
              <div class="progress-number">${Math.round(pct)}%</div>
            </div>
          </div>
          <div class="error" data-progress-error ${state.error && state.failed ? "" : "hidden"}>${esc(state.error || "")}</div>
        </main>`,
      buttons,
    };
  };

  const donePage = (removed) => ({
    body: `
      <main class="view">
        ${stepsBar()}
        <div class="page-head">
          <div class="done-mark" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 16 16" fill="none"><path d="M3.2 8.6l2.4 2.5l7.2-6.2" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
          <h1 style="margin-top:12px">${removed ? L("Zapret Hub удалён", "Zapret Hub removed") : L("Готово", "Done")}</h1>
          <p>${removed
            ? L("Приложение удалено с этого компьютера.", "The app has been removed from this computer.")
            : L("Zapret Hub готов к работе.", "Zapret Hub is ready to use.")}</p>
        </div>
        ${removed ? "" : `<div class="checks">
          <label class="check"><input id="desktop-shortcut" type="checkbox" ${state.createDesktop ? "checked" : ""}>${L("Ярлык на рабочем столе", "Desktop shortcut")}</label>
          <label class="check"><input id="start-shortcut" type="checkbox" ${state.createStartMenu ? "checked" : ""}>${L("Ярлык в меню Пуск", "Start Menu shortcut")}</label>
          <label class="check"><input id="launch-after" type="checkbox" ${state.launchAfter ? "checked" : ""}>${L("Запустить сейчас", "Launch now")}</label>
        </div>`}
      </main>`,
    buttons: btn(removed ? L("Закрыть", "Close") : L("Готово", "Finish"), removed ? "window.close" : "finish", "primary"),
  });

  const uninstallPage = () => ({
    body: `
      <main class="view">
        ${stepsBar()}
        <div class="page-head">
          <h1>${L("Удалить Zapret Hub?", "Remove Zapret Hub?")}</h1>
          <p>${L("Приложение, данные и ярлыки будут удалены. Отменить нельзя.", "The app, data, and shortcuts will be removed. This cannot be undone.")}</p>
        </div>
        <div class="confirm-path">${esc(state.resolvedPath || state.selectedPath)}</div>
        ${state.error ? `<div class="error">${esc(state.error)}</div>` : ""}
      </main>`,
    buttons: btn(L("Назад", "Back"), "back") + btn(L("Удалить", "Remove"), "uninstall.start", "danger"),
  });

  async function refreshPreview(value) {
    try {
      const preview = await call("path.preview", { path: value });
      state.selectedPath = preview.selectedPath;
      state.resolvedPath = preview.resolvedPath;
      render();
      const input = document.querySelector("#install-path");
      if (input) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
    } catch (error) {
      state.error = error.message;
      render();
    }
  }

  const syncPathOptions = () => {
    const desktop = document.querySelector("#opt-desktop");
    const start = document.querySelector("#opt-start");
    const launch = document.querySelector("#opt-launch");
    if (desktop) state.createDesktop = desktop.checked;
    if (start) state.createStartMenu = start.checked;
    if (launch) state.launchAfter = launch.checked;
  };

  const beginInstall = async () => {
    state.page = "progress";
    state.progress = 0;
    state.status = L("Запуск загрузки с goshkow.com…", "Starting download from goshkow.com…");
    state.error = "";
    state.failed = false;
    render();
    armProgressWatch();
    await call("install.start", {
      path: state.selectedPath,
      action: state.selectedAction,
      desktop: state.createDesktop,
      startMenu: state.createStartMenu,
      launchAfter: state.launchAfter,
    });
    await pollSnapshotOnce();
  };

  root.addEventListener("pointerdown", (event) => {
    if (event.button === 0 && event.target.closest("[data-drag]") && !event.target.closest("button")) call("window.startDrag");
  });
  root.addEventListener("input", (event) => {
    if (event.target.id === "terms-accepted") {
      state.termsAccepted = event.target.checked;
      render();
      return;
    }
    if (event.target.id === "install-path") {
      clearTimeout(window.__pathTimer);
      const value = event.target.value;
      window.__pathTimer = setTimeout(() => refreshPreview(value), 180);
      return;
    }
    if (["opt-desktop", "opt-start", "opt-launch", "desktop-shortcut", "start-shortcut", "launch-after"].includes(event.target.id)) {
      if (event.target.id === "desktop-shortcut" || event.target.id === "opt-desktop") state.createDesktop = event.target.checked;
      if (event.target.id === "start-shortcut" || event.target.id === "opt-start") state.createStartMenu = event.target.checked;
      if (event.target.id === "launch-after" || event.target.id === "opt-launch") state.launchAfter = event.target.checked;
    }
  });
  root.addEventListener("click", async (event) => {
    const selected = event.target.closest("[data-select-action]");
    if (selected) {
      state.selectedAction = selected.dataset.selectAction;
      render();
      return;
    }
    const element = event.target.closest("[data-action],[data-command]");
    if (!element) return;
    const action = element.dataset.action || element.dataset.command;
    try {
      if (action === "welcome.next") {
        state.page = state.installed ? "maintenance" : "agreement";
      } else if (action === "back" || action === "progress.back") {
        clearProgressWatch();
        try { await call("install.abort"); } catch (_) {}
        if (state.page === "uninstall" && state.installed) state.page = "maintenance";
        else if (state.page === "confirm") state.page = "path";
        else if (state.page === "progress") {
          state.page = state.selectedAction === "remove" ? "uninstall" : state.selectedAction === "reinstall" ? "confirm" : "path";
        }
        else if (state.page === "path" && state.installed) state.page = "maintenance";
        else if (state.page === "path") state.page = "agreement";
        else state.page = "welcome";
        state.error = "";
        state.failed = false;
      } else if (action === "progress.retry") {
        await beginInstall();
        return;
      } else if (action === "maintenance.next") {
        state.page = state.selectedAction === "remove" ? "uninstall" : "path";
      } else if (action === "agreement.next") {
        if (!state.termsAccepted || !state.termsText) return;
        state.page = state.installed ? "maintenance" : "path";
      } else if (action === "path.browse") {
        syncPathOptions();
        const preview = await call("folder.choose", { path: state.selectedPath });
        if (preview) Object.assign(state, preview);
      } else if (action === "install.prepare") {
        syncPathOptions();
        if (state.selectedAction === "reinstall") {
          state.page = "confirm";
          state.error = "";
        } else {
          await beginInstall();
          return;
        }
      } else if (action === "install.confirm") {
        await beginInstall();
        return;
      } else if (action === "uninstall.start") {
        state.selectedAction = "remove";
        state.page = "progress";
        state.progress = 0;
        state.status = L("Остановка процессов…", "Stopping processes…");
        state.error = "";
        state.failed = false;
        render();
        armProgressWatch();
        await call("uninstall.start");
        await pollSnapshotOnce();
        return;
      } else if (action === "finish") {
        const desktop = document.querySelector("#desktop-shortcut")?.checked ?? state.createDesktop;
        const startMenu = document.querySelector("#start-shortcut")?.checked ?? state.createStartMenu;
        const launchAfter = document.querySelector("#launch-after")?.checked ?? state.launchAfter;
        await call("install.finish", { desktop, startMenu, launchAfter });
        return;
      } else if (action === "window.close") {
        clearProgressWatch();
        try { await call("install.abort"); } catch (_) {}
        await call("window.close");
        return;
      } else {
        await call(action);
        return;
      }
      render();
    } catch (error) {
      state.error = error.message;
      state.failed = true;
      if (state.page === "progress") {
        clearProgressWatch();
      } else {
        state.page = state.selectedAction === "remove" ? "uninstall" : state.selectedAction === "reinstall" ? "confirm" : "path";
      }
      render();
    }
  });

  const bindBridgeEvents = (channelBridge) => {
    // Optional: bridgeEvent often does not reach WebEngine; snapshot polling is the source of truth.
    const signal = channelBridge.bridgeEvent || channelBridge.event;
    if (!signal || typeof signal.connect !== "function") return;
    signal.connect((name, raw) => {
      const payload = JSON.parse(raw || "{}");
      let result = { progressChanged: false, pageChanged: false };
      if (name === "progress") {
        result = applySnapshot({
          progress: payload.value ?? state.progress,
          status: payload.status || state.status,
          phase: Number(payload.value ?? state.progress) < 6 ? "connecting" : "downloading",
          bytesDownloaded: payload.bytesDownloaded,
          bytesTotal: payload.bytesTotal,
        });
      } else if (name === "done") {
        result = applySnapshot({ done: true, progress: 100, status: L("Готово", "Done") });
      } else if (name === "aborted") {
        result = applySnapshot({ phase: "aborted" });
      } else if (name === "error") {
        result = applySnapshot({ failed: true, error: payload.message || L("Неизвестная ошибка.", "Unknown error.") });
      }
      if (result.pageChanged || state.failed) refresh({ force: true });
      else if (result.progressChanged) refresh();
    });
  };

  const connect = async (channelBridge) => {
    bridge = channelBridge;
    bindBridgeEvents(channelBridge);
    state = { ...state, ...(await call("state.get")), failed: false };
    document.documentElement.lang = state.locale;
    render();
  };

  if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {
    new QWebChannel(qt.webChannelTransport, async (channel) => {
      await connect(channel.objects.installerBridge);
    });
  } else {
    const listeners = [];
    let mockSnap = {
      phase: "idle",
      status: "",
      progress: 0,
      error: "",
      bytesDownloaded: 0,
      bytesTotal: 0,
      failed: false,
      done: false,
      running: false,
    };
    const mockBridge = {
      bridgeEvent: { connect: (listener) => listeners.push(listener) },
      call: (command, raw, callback) => {
        const payload = JSON.parse(raw || "{}");
        let value = null;
        if (command === "state.get") {
          value = {
            locale: new URLSearchParams(location.search).get("lang") === "en" ? "en" : "ru",
            mode: "install",
            page: "welcome",
            installed: new URLSearchParams(location.search).get("installed") === "1",
            selectedAction: "update",
            selectedPath: "C:\\Program Files",
            resolvedPath: "C:\\Program Files\\Zapret Hub",
            progress: 0,
            status: "",
            version: "3.0.0",
            remoteVersion: "2.1.2",
            createDesktop: true,
            createStartMenu: true,
            launchAfter: true,
            error: "",
            termsText: "ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ ZAPRET HUB\n\nТестовый текст соглашения для предпросмотра установщика.",
          };
        } else if (command === "install.snapshot") {
          value = { ...mockSnap };
        } else if (command === "path.preview") {
          value = { selectedPath: payload.path, resolvedPath: payload.path.endsWith("Zapret Hub") ? payload.path : `${payload.path}\\Zapret Hub` };
        } else if (command === "folder.choose") {
          value = { selectedPath: "C:\\Program Files", resolvedPath: "C:\\Program Files\\Zapret Hub" };
        } else if (command === "install.start" || command === "uninstall.start") {
          mockSnap = {
            phase: "connecting",
            status: "Запрос метаданных goshkow.com…",
            progress: 2,
            error: "",
            bytesDownloaded: 0,
            bytesTotal: 40 * 1024 * 1024,
            failed: false,
            done: false,
            running: true,
          };
          setTimeout(() => {
            mockSnap = { ...mockSnap, phase: "downloading", progress: 28, status: "Скачивание 12 / 40 MB", bytesDownloaded: 12 * 1024 * 1024 };
          }, 250);
          setTimeout(() => {
            mockSnap = { ...mockSnap, phase: "installing", progress: 72, status: "Копирование файлов…" };
          }, 500);
          setTimeout(() => {
            mockSnap = { ...mockSnap, phase: "done", progress: 100, status: "Готово", done: true, running: false };
          }, 850);
          value = { ...mockSnap };
        } else if (command === "install.abort") {
          mockSnap = { ...mockSnap, running: false, phase: mockSnap.failed ? "error" : "aborted" };
          value = { ...mockSnap };
        }
        callback(JSON.stringify({ value }));
      },
    };
    connect(mockBridge);
  }
})();
