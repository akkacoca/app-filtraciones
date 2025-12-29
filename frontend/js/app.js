const LS_QUERIES = "lm_queries";
const LS_LEAKS = "lm_leaks"; // demo fallback para leaks.html

function uid() {
  return "q_" + Math.random().toString(16).slice(2) + "_" + Date.now();
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/**
 * Backend API helpers
 */
async function apiGetJson(url) {
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  if (!r.ok) throw new Error(`${url} -> HTTP ${r.status}`);
  return await r.json();
}

async function apiPutJson(url, body) {
  const r = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${url} -> HTTP ${r.status}`);
  return data;
}

async function apiPost(url) {
  const r = await fetch(url, { method: "POST", headers: { "Accept": "application/json" } });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${url} -> HTTP ${r.status}`);
  return data;
}

/**
 * Local fallback (si backend no existe)
 */
function lsLoadQueries() {
  const raw = localStorage.getItem(LS_QUERIES);
  return raw ? JSON.parse(raw) : [];
}
function lsSaveQueries(qs) {
  localStorage.setItem(LS_QUERIES, JSON.stringify(qs));
}

function ensureDemoLeaksOnce() {
  if (localStorage.getItem(LS_LEAKS)) return;

  const now = new Date();
  const iso = (d) => d.toISOString();

  const demo = [
    {
      id: "l_1",
      status: "new",
      entityType: "domain",
      entity: "atalantago.com",
      foundAt: iso(new Date(now.getTime() - 2 * 60 * 60 * 1000)),
      summary: "Coincidencias en una fuente externa (demo).",
      details: { source: "demo-source", breach: "DemoBreach-2021", note: "Ejemplo (no real)." }
    },
    {
      id: "l_2",
      status: "new",
      entityType: "keyword",
      entity: "Atalanta",
      foundAt: iso(new Date(now.getTime() - 25 * 60 * 1000)),
      summary: "Nueva aparición relacionada con keyword (demo).",
      details: { source: "demo-source", breach: "DemoPaste-2023", note: "Ejemplo (no real)." }
    },
    {
      id: "l_3",
      status: "deleted",
      entityType: "domain",
      entity: "old-domain.example",
      foundAt: iso(new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000)),
      summary: "Marcada como eliminada (demo).",
      details: { source: "demo-source", breach: "OldDump-2019", note: "Ejemplo (no real)." }
    }
  ];

  localStorage.setItem(LS_LEAKS, JSON.stringify(demo));
}

/**
 * Normalización:
 * Backend espera: { queries: [ { q: "...", type: "domain|keyword|email|auto" } ] }
 * UI tiene: { id, name, type, value, createdAt }
 */
function uiToApiQueries(uiList) {
  return {
    queries: uiList.map(x => ({
      q: String(x.value || "").trim(),
      type: String(x.type || "auto").trim().toLowerCase() || "auto"
    }))
  };
}

function apiToUiQueries(apiPayload) {
  const list = Array.isArray(apiPayload?.queries) ? apiPayload.queries : [];
  // Nota: backend no guarda name/id/createdAt; en UI los regeneramos
  return list.map((x) => ({
    id: uid(),
    name: "",                       // opcional: no existe en backend
    type: x.type || "auto",
    value: x.q || "",
    createdAt: new Date().toISOString(),
  }));
}

let BACKEND_OK = true;
let CURRENT_QUERIES = [];

/**
 * Carga queries desde backend; si falla, usa localStorage
 */
async function loadQueries() {
  try {
    const data = await apiGetJson("/api/queries");
    BACKEND_OK = true;
    return apiToUiQueries(data);
  } catch (e) {
    BACKEND_OK = false;
    return lsLoadQueries();
  }
}

/**
 * Guarda queries en backend; si falla, usa localStorage
 */
async function saveQueries(qs) {
  if (BACKEND_OK) {
    const payload = uiToApiQueries(qs);
    await apiPutJson("/api/queries", payload);
    return;
  }
  // fallback
  lsSaveQueries(qs);
}

function setBanner(msg, kind = "info") {
  // kind: info|ok|warn|danger
  let el = document.getElementById("backendBanner");
  if (!el) {
    // Creamos un banner arriba sin tocar tu HTML
    el = document.createElement("div");
    el.id = "backendBanner";
    el.className = "item";
    el.style.borderLeft = "6px solid #888";
    el.style.marginBottom = "12px";
    const main = document.querySelector("main") || document.body;
    main.prepend(el);
  }
  const color =
    kind === "ok" ? "#1f9d55" :
    kind === "warn" ? "#f59e0b" :
    kind === "danger" ? "#dc2626" : "#3b82f6";

  el.style.borderLeftColor = color;
  el.innerHTML = `<div class="meta"><strong>${escapeHtml(msg)}</strong><small>${kind}</small></div>`;
}

function renderQueries() {
  const list = document.getElementById("queriesList");
  const qs = CURRENT_QUERIES;

  if (!qs.length) {
    list.innerHTML = `<div class="item"><div class="meta"><strong>Sin querys</strong><small>Crea una arriba</small></div></div>`;
    return;
  }

  list.innerHTML = "";
  for (const q of qs) {
    const el = document.createElement("div");
    el.className = "item";
    el.innerHTML = `
      <div class="meta">
        <strong>${escapeHtml(q.name || "(sin nombre)")}</strong>
        <small><span class="badge"><span class="dot ok"></span>${escapeHtml(q.type)}</span> &nbsp; ${escapeHtml(q.value)}</small>
      </div>
      <div class="row" style="gap:8px; flex-wrap:nowrap;">
        <button class="btn btn-danger" data-del="${q.id}">Borrar</button>
      </div>
    `;
    list.appendChild(el);
  }

  list.querySelectorAll("[data-del]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-del");
      CURRENT_QUERIES = CURRENT_QUERIES.filter(x => x.id !== id);
      try {
        await saveQueries(CURRENT_QUERIES);
        renderQueries();
      } catch (e) {
        alert(`No se pudo guardar: ${e.message || e}`);
      }
    });
  });
}

async function refreshQueries() {
  CURRENT_QUERIES = await loadQueries();
  renderQueries();

  if (BACKEND_OK) {
    setBanner("Backend conectado. Guardado en servidor (config/querys.json).", "ok");
  } else {
    setBanner("Backend NO disponible. Modo local (localStorage).", "warn");
  }
}

async function runNow() {
  try {
    await apiPost("/api/run-now");
    setBanner("Run-now enviado. El monitor debería ejecutar en breve.", "ok");
  } catch (e) {
    setBanner(`No se pudo enviar run-now: ${e.message || e}`, "danger");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  ensureDemoLeaksOnce();

  const btnAdd = document.getElementById("btnAddQuery");
  const btnClear = document.getElementById("btnClearQueries");

  // Botón opcional "Run now" si quieres sin tocar HTML:
  // Si existe un botón con id="btnRunNow" lo usa, si no, lo crea.
  let btnRun = document.getElementById("btnRunNow");
  if (!btnRun) {
    btnRun = document.createElement("button");
    btnRun.id = "btnRunNow";
    btnRun.className = "btn";
    btnRun.textContent = "Run now";
    // Lo metemos al lado del limpiar si existe
    const actionRow = btnClear?.parentElement || document.body;
    actionRow.appendChild(btnRun);
  }
  btnRun.addEventListener("click", runNow);

  btnAdd.addEventListener("click", async () => {
    const name = document.getElementById("qName").value.trim();
    const type = document.getElementById("qType").value;
    const value = document.getElementById("qValue").value.trim();

    if (!value) {
      alert("El campo 'Valor' es obligatorio.");
      return;
    }

    CURRENT_QUERIES.push({ id: uid(), name, type, value, createdAt: new Date().toISOString() });

    try {
      await saveQueries(CURRENT_QUERIES);
      document.getElementById("qName").value = "";
      document.getElementById("qValue").value = "";
      renderQueries();
      setBanner("Queries guardadas.", "ok");
    } catch (e) {
      alert(`No se pudo guardar: ${e.message || e}`);
    }
  });

  btnClear.addEventListener("click", async () => {
    if (!confirm("¿Borrar todas las querys?")) return;
    CURRENT_QUERIES = [];
    try {
      await saveQueries(CURRENT_QUERIES);
      renderQueries();
      setBanner("Queries borradas.", "ok");
    } catch (e) {
      alert(`No se pudo guardar: ${e.message || e}`);
    }
  });

  await refreshQueries();
});
