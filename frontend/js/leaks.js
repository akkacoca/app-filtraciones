const LS_LEAKS = "lm_leaks";

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtDate(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString("es-ES", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit"
    });
  } catch {
    return iso;
  }
}

async function apiGetLeaks() {
  const r = await fetch("/api/leaks", { headers: { "Accept": "application/json" } });
  if (!r.ok) throw new Error(`/api/leaks -> HTTP ${r.status}`);
  const data = await r.json();
  return data.items || [];
}

// Fallback local
function loadLeaksLocal() {
  const raw = localStorage.getItem(LS_LEAKS);
  return raw ? JSON.parse(raw) : [];
}

function matchesSearch(leak, q) {
  if (!q) return true;
  const hay = [
    leak.entityType,
    leak.entity,
    leak.status,
    leak.summary,
    leak.details?.source,
    leak.details?.breach,
    leak.details?.snapshot_file
  ].filter(Boolean).join(" ").toLowerCase();
  return hay.includes(q.toLowerCase());
}

function leakCard(leak) {
  const dotClass = leak.status === "new" ? "ok" : (leak.status === "deleted" ? "danger" : "warn");
  const src = leak.details?.source ? ` • ${leak.details.source}` : "";
  const dt = leak.details?.breach_date ? ` • ${leak.details.breach_date}` : "";

  const header = `
    <div class="acc-head">
      <div style="display:flex;flex-direction:column;gap:4px;">
        <strong>${escapeHtml(leak.entityType)}: ${escapeHtml(leak.entity)}</strong>
        <small>
          <span class="badge"><span class="dot ${dotClass}"></span>${escapeHtml(leak.status)}</span>
          &nbsp; • &nbsp; ${fmtDate(leak.foundAt)} ${escapeHtml(src)} ${escapeHtml(dt)}
        </small>
      </div>
      <small>Ver detalles ▾</small>
    </div>
  `;

  const body = `
    <div class="acc-body" style="display:none;">
      <div style="margin-bottom:10px;">
        <div class="badge"><span class="dot warn"></span> Resumen</div>
        <div style="margin-top:6px;">${escapeHtml(leak.summary || "-")}</div>
      </div>

      <div class="badge"><span class="dot ok"></span> Datos</div>
      <pre style="margin-top:8px;">${escapeHtml(JSON.stringify(leak.details || {}, null, 2))}</pre>
    </div>
  `;

  const wrapper = document.createElement("div");
  wrapper.className = "accordion";
  wrapper.innerHTML = header + body;

  const head = wrapper.querySelector(".acc-head");
  const bodyEl = wrapper.querySelector(".acc-body");
  head.addEventListener("click", () => {
    const open = bodyEl.style.display === "block";
    bodyEl.style.display = open ? "none" : "block";
  });

  return wrapper;
}

function setBanner(msg, kind = "info") {
  let el = document.getElementById("backendBanner");
  if (!el) {
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

async function loadLeaks() {
  try {
    const items = await apiGetLeaks();
    setBanner("Backend conectado. Mostrando leaks reales (snapshots).", "ok");
    return items;
  } catch (e) {
    setBanner("Backend NO disponible. Mostrando leaks demo (localStorage).", "warn");
    return loadLeaksLocal();
  }
}

async function render() {
  const status = document.getElementById("statusFilter").value; // all | new | deleted
  const search = document.getElementById("searchText").value.trim();

  const leaks = (await loadLeaks())
    .filter(l => matchesSearch(l, search))
    .sort((a, b) => (new Date(b.foundAt)) - (new Date(a.foundAt)));

  const groupNew = document.getElementById("groupNew");
  const groupDeleted = document.getElementById("groupDeleted");
  const groupAll = document.getElementById("groupAll");

  groupNew.innerHTML = "";
  groupDeleted.innerHTML = "";
  groupAll.innerHTML = "";

  const visible = (l) => status === "all" ? true : l.status === status;

  const newItems = leaks.filter(l => l.status === "new" && visible(l));
  const delItems = leaks.filter(l => l.status === "deleted" && visible(l));
  const allItems = leaks.filter(l => visible(l));

  const fillList = (container, items, emptyText) => {
    if (!items.length) {
      container.innerHTML = `<div class="item"><div class="meta"><strong>${emptyText}</strong><small>Prueba a cambiar el filtro o la búsqueda</small></div></div>`;
      return;
    }
    for (const l of items) container.appendChild(leakCard(l));
  };

  fillList(groupNew, newItems, "Sin filtraciones nuevas");
  fillList(groupDeleted, delItems, "Sin filtraciones eliminadas");
  fillList(groupAll, allItems, "Sin filtraciones");
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("statusFilter").addEventListener("change", () => render());
  document.getElementById("searchText").addEventListener("input", () => render());
  render();
});
