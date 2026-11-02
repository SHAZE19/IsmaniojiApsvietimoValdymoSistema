"use strict";
const $ = (id) => document.getElementById(id);
let user = null,
  activeView = "overview",
  selectedMode = "auto",
  controlDirty = false;
let lastState = null,
  eventRows = [],
  eventBusy = false,
  toastTimer;
const titles = {
  overview: "Apžvalga",
  cards: "NFC kortelės",
  users: "Vartotojai",
  events: "Įvykių istorija",
  settings: "Nustatymai",
};
const modes = {
  auto: "Automatinis",
  on: "Rankinis įjungimas",
  off: "Rankinis išjungimas",
};
const eventNames = {
  system: "Sistema",
  login: "Prisijungimas",
  login_denied: "Atmestas prisijungimas",
  user_created: "Vartotojas sukurtas",
  user_updated: "Vartotojo būsena",
  card_created: "Kortelė pridėta",
  card_updated: "Kortelės būsena",
  card_deleted: "Kortelė pašalinta",
  settings: "Nustatymai",
  lighting_command: "Valdymo komanda",
  lighting_actual: "Įrenginio būsena",
  nfc_granted: "Prieiga suteikta",
  nfc_denied: "Prieiga atmesta",
  motion: "Judesys",
};
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const dateTime = (value) =>
  value ? new Date(value * 1000).toLocaleString("lt-LT") : "Dar neužmegztas";

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").classList.toggle("error-toast", error);
  $("toast").hidden = false;
  toastTimer = setTimeout(() => ($("toast").hidden = true), 5000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "LightingApp",
      ...options.headers,
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/auth/login") showLogin();
    const detail = Array.isArray(data.detail)
      ? data.detail.map((x) => x.msg).join(". ")
      : data.detail;
    throw new Error(detail || "Nepavyko atlikti veiksmo");
  }
  return data;
}

function showLogin() {
  user = null;
  $("app-view").hidden = true;
  $("login-view").hidden = false;
}

async function enterApp(currentUser) {
  user = currentUser;
  $("user-name").textContent = user.display_name;
  $("avatar").textContent = user.display_name[0].toUpperCase();
  $("user-role").textContent =
    user.role === "admin" ? "Administratorius" : "Vartotojas";
  document
    .querySelectorAll(".admin-only")
    .forEach((el) => (el.hidden = user.role !== "admin"));
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  await navigate("overview");
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const button = e.submitter;
  button.disabled = true;
  $("login-error").textContent = "";
  try {
    const data = Object.fromEntries(new FormData(e.target));
    const currentUser = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    });
    e.target.reset();
    controlDirty = false;
    await enterApp(currentUser);
  } catch (error) {
    $("login-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

// Logout is also available on small screens, where the sidebar profile is hidden.
const mobileLogout = document.createElement("button");
mobileLogout.textContent = "Atsijungti";
mobileLogout.className = "nav-item";
mobileLogout.id = "mobile-logout";
document.querySelector(".sidebar nav").append(mobileLogout);
async function logout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
    showLogin();
  } catch (error) {
    toast(error.message, true);
  }
}
$("logout").addEventListener("click", logout);
mobileLogout.addEventListener("click", logout);

async function navigate(view) {
  if (!user || (view !== "overview" && user.role !== "admin")) return;
  activeView = view;
  document
    .querySelectorAll(".view")
    .forEach((el) => (el.hidden = el.id !== `view-${view}`));
  document
    .querySelectorAll(".nav-item[data-view]")
    .forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  $("breadcrumb").textContent = titles[view];
  try {
    if (view === "overview") await refreshState();
    if (view === "cards") await loadCards();
    if (view === "users") await loadUsers();
    if (view === "events") await loadEvents();
    if (view === "settings") {
      const data = await api("/api/settings");
      for (const name of [
        "dim_after_seconds",
        "off_after_seconds",
        "dim_brightness",
      ])
        $("settings-form").elements[name].value = data[name];
    }
  } catch (error) {
    toast(error.message, true);
  }
}
document
  .querySelectorAll("[data-view]")
  .forEach((el) =>
    el.addEventListener("click", () => navigate(el.dataset.view)),
  );

function setSelectedMode(mode) {
  selectedMode = mode;
  document
    .querySelectorAll("[data-mode]")
    .forEach((el) => el.classList.toggle("selected", el.dataset.mode === mode));
  $("mode-help").textContent =
    mode === "auto"
      ? "Automatiniame režime šviesą įjungia registruota NFC kortelė. Judesys pratęsia veikimo laiką."
      : mode === "on"
        ? "Šviesa veiks nuolat, kol pakeisite režimą arba nuskaitysite autorizuotą NFC kortelę."
        : "Šviesa išjungiama. Autorizuota NFC kortelė vėl įjungs automatinį režimą.";
}
document.querySelectorAll("[data-mode]").forEach((el) =>
  el.addEventListener("click", () => {
    controlDirty = true;
    setSelectedMode(el.dataset.mode);
  }),
);
$("brightness").addEventListener("input", (e) => {
  controlDirty = true;
  $("brightness-value").textContent = `${e.target.value}%`;
});
$("apply-lighting").addEventListener("click", async (e) => {
  e.currentTarget.disabled = true;
  try {
    const result = await api("/api/lighting", {
      method: "PUT",
      body: JSON.stringify({
        mode: selectedMode,
        brightness: Number($("brightness").value),
      }),
    });
    controlDirty = false;
    renderState(result);
    toast(
      result.online
        ? "Komanda išsiųsta įrenginiui"
        : "Komanda išsaugota. Laukiama įrenginio ryšio.",
    );
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("apply-lighting").disabled = false;
  }
});

function renderState(s) {
  lastState = s;
  const deviceName =
    s.device_source === "simulator" ? "Simuliatorius" : "Arduino";
  $("device-status").textContent = s.online
    ? `● ${deviceName} prisijungęs`
    : `○ ${deviceName} nepasiekiamas`;
  $("device-status").classList.toggle("online", s.online);
  $("mode-label").textContent = modes[s.mode];
  $("desired-brightness").textContent = s.desired_brightness;
  $("stage-label").textContent = {
    on: "Įjungta",
    dimmed: "Pritemdyta",
    off: "Išjungta",
  }[s.stage];
  const confirmed = s.online && s.actual_brightness === s.desired_brightness;
  $("confirmation").textContent = !s.online
    ? "Laukiama įrenginio ryšio"
    : confirmed
      ? `${deviceName} pritaikė komandą`
      : `Laukiama pakeitimo · dabar ${s.actual_brightness ?? "—"}%`;
  $("actual-caption").textContent = s.online
    ? `${deviceName} · praneštas ryškumas: ${s.actual_brightness ?? "—"}%`
    : "Įrenginys neprisijungęs";
  $("room-visual").classList.toggle(
    "is-lit",
    s.online && s.actual_brightness > 0,
  );
  $("motion-status").textContent = !s.online
    ? "Jutiklis nepasiekiamas"
    : s.motion
      ? "Aptiktas judesys"
      : "Judesio nėra";
  $("last-seen").textContent = dateTime(s.last_seen);
  $("last-card").textContent = s.last_card || "Dar nenuskaityta";
  $("countdown").textContent =
    s.remaining_seconds === null ? "—" : `${s.remaining_seconds} s`;
  $("automation-summary").textContent =
    `Be judesio po ${s.dim_after_seconds} s šviesa pritemsta iki ${s.dim_brightness}%, po ${s.off_after_seconds} s išsijungia.`;
  if (!controlDirty) {
    setSelectedMode(s.mode);
    $("brightness").value = s.brightness;
    $("brightness-value").textContent = `${s.brightness}%`;
  }
}

async function refreshState() {
  try {
    const result = await api("/api/lighting");
    renderState(result);
    $("connection-error").hidden = true;
  } catch (error) {
    $("connection-error").hidden = false;
    throw error;
  }
}
function emptyRow(columns, message) {
  return `<tr><td colspan="${columns}" class="empty">${escapeHTML(message)}</td></tr>`;
}
function status(enabled) {
  return `<span class="status${enabled ? "" : " disabled"}">${enabled ? "Aktyvi" : "Užblokuota"}</span>`;
}

async function loadCards() {
  const [cards, users] = await Promise.all([
    api("/api/cards"),
    api("/api/users"),
  ]);
  $("card-owner").innerHTML = users
    .filter((u) => u.enabled)
    .map(
      (u) => `<option value="${u.id}">${escapeHTML(u.display_name)}</option>`,
    )
    .join("");
  $("cards-body").innerHTML = cards.length
    ? cards
        .map(
          (c) =>
            `<tr><td>${escapeHTML(c.label)}</td><td><code>${escapeHTML(c.card_id)}</code></td><td>${escapeHTML(c.owner)}</td><td>${status(c.enabled)}</td><td><button class="secondary" data-card-toggle="${c.card_id}" data-enabled="${c.enabled ? 0 : 1}">${c.enabled ? "Blokuoti" : "Aktyvuoti"}</button><button class="secondary" data-card-delete="${c.card_id}">Pašalinti</button></td></tr>`,
        )
        .join("")
    : emptyRow(5, "Kortelių dar nėra. Užregistruokite pirmąją NFC kortelę.");
}

$("cards-body").addEventListener("click", async (e) => {
  const toggle = e.target.closest("[data-card-toggle]"),
    remove = e.target.closest("[data-card-delete]");
  try {
    if (toggle) {
      await api(`/api/cards/${toggle.dataset.cardToggle}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: toggle.dataset.enabled === "1" }),
      });
      await loadCards();
      toast("Kortelės būsena pakeista");
    }
    if (remove) {
      const dialog = $("confirm-dialog");
      dialog.returnValue = "cancel";
      dialog.showModal();
      dialog.addEventListener(
        "close",
        async () => {
          if (dialog.returnValue !== "delete") return;
          try {
            await api(`/api/cards/${remove.dataset.cardDelete}`, {
              method: "DELETE",
            });
            await loadCards();
            toast("Kortelė pašalinta");
          } catch (error) {
            toast(error.message, true);
          }
        },
        { once: true },
      );
    }
  } catch (error) {
    toast(error.message, true);
  }
});

async function loadUsers() {
  const users = await api("/api/users");
  $("users-body").innerHTML = users
    .map(
      (u) =>
        `<tr><td>${escapeHTML(u.display_name)}</td><td>${escapeHTML(u.username)}</td><td>${u.role === "admin" ? "Administratorius" : "Vartotojas"}</td><td>${status(u.enabled)}</td><td>${u.id === user.id ? "Jūsų paskyra" : `<button class="secondary" data-user-id="${u.id}" data-enabled="${u.enabled ? 0 : 1}">${u.enabled ? "Blokuoti" : "Aktyvuoti"}</button>`}</td></tr>`,
    )
    .join("");
}
$("users-body").addEventListener("click", async (e) => {
  const button = e.target.closest("[data-user-id]");
  if (!button) return;
  try {
    await api(`/api/users/${button.dataset.userId}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: button.dataset.enabled === "1" }),
    });
    await loadUsers();
    toast("Vartotojo būsena pakeista");
  } catch (error) {
    toast(error.message, true);
  }
});

for (const [id, path, reload] of [
  ["card-form", "/api/cards", loadCards],
  ["user-form", "/api/users", loadUsers],
  ["settings-form", "/api/settings", null],
]) {
  $(id).addEventListener("submit", async (e) => {
    e.preventDefault();
    const button = e.submitter;
    button.disabled = true;
    const data = Object.fromEntries(new FormData(e.target));
    for (const name of [
      "user_id",
      "dim_after_seconds",
      "off_after_seconds",
      "dim_brightness",
    ])
      if (name in data) data[name] = Number(data[name]);
    try {
      await api(path, {
        method: id === "settings-form" ? "PUT" : "POST",
        body: JSON.stringify(data),
      });
      if (reload) {
        e.target.reset();
        await reload();
      }
      toast(
        id === "settings-form" ? "Nustatymai išsaugoti" : "Įrašas sukurtas",
      );
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

async function loadEvents(append = false) {
  if (eventBusy) return;
  eventBusy = true;
  try {
    const params = new URLSearchParams({ limit: "50" });
    if ($("event-filter").value) params.set("kind", $("event-filter").value);
    if (append && eventRows.length)
      params.set("before_id", eventRows[eventRows.length - 1].id);
    const rows = await api(`/api/events?${params}`);
    eventRows = append ? eventRows.concat(rows) : rows;
    $("events-body").innerHTML = eventRows.length
      ? eventRows
          .map(
            (r) =>
              `<tr><td>${escapeHTML(dateTime(r.at))}</td><td>${escapeHTML(eventNames[r.kind] || r.kind)}</td><td>${escapeHTML(r.actor)}</td><td>${escapeHTML(r.detail)}</td></tr>`,
          )
          .join("")
      : emptyRow(4, "Šio tipo įvykių dar nėra.");
    $("more-events").hidden = rows.length < 50;
  } finally {
    eventBusy = false;
  }
}
$("event-filter").addEventListener("change", () =>
  loadEvents().catch((e) => toast(e.message, true)),
);
$("more-events").addEventListener("click", () =>
  loadEvents(true).catch((e) => toast(e.message, true)),
);
setInterval(async () => {
  $("clock").textContent = new Date().toLocaleDateString("lt-LT", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  if (!user || document.hidden) return;
  try {
    if (activeView === "overview") await refreshState();
    if (activeView === "events" && eventRows.length <= 50) await loadEvents();
  } catch (error) {
    /* Visible connection banner handles polling errors. */
  }
}, 3000);
api("/api/auth/me").then(enterApp).catch(showLogin);
