// Catálogo digital: tarjetas de vidrio teñidas con la paleta de cada especie, inclinación 3D y carga perezosa.
import { api, catBadge, debounce, esc, fmt, state, store } from "../core.js";
import { getPeriod, onPeriod, periodParams } from "../charts/period.js";
import { openSpecies } from "./species.js";

export const title = "Catálogo de especies";
let io = null, cleanup = [];
const PAGE = 36;

export async function mount(el, params = {}) {
  if (!state.wsId) { el.innerHTML = `<div class="empty glass">Crea o selecciona un área de interés.</div>`; return; }
  const f = { q: "", threat: "", tax_class: "", flag: "", sort: "records", ...store.get("catalog.filters", {}), ...params };
  el.innerHTML = `
    <div class="cat-toolbar glass">
      <label class="search"><span aria-hidden="true">⌕</span><span class="sr-only">Buscar</span>
        <input id="q" placeholder="Nombre científico, común o familia…" value="${esc(f.q)}"></label>
      <select id="threat" aria-label="Amenaza">
        <option value="">Todas las categorías</option><option value="threatened">Amenazadas (nacional o global)</option>
        <option value="national">Amenazadas Res. 0126/2024</option>
        ${["CR", "EN", "VU", "NT", "DD", "LC"].map((c) => `<option value="${c}">${c}</option>`).join("")}
      </select>
      <select id="tax_class" aria-label="Clase"><option value="">Todas las clases</option></select>
      <select id="flag" aria-label="Atributo"><option value="">Cualquier atributo</option><option value="cites">CITES</option>
        <option value="exotic">Exóticas</option><option value="invasive">Invasoras</option><option value="new_in_2024">Nuevas en lista 2024</option></select>
      <select id="sort" aria-label="Orden"><option value="records">Más registros</option><option value="threat">Mayor amenaza</option>
        <option value="aoo">Mayor AOO</option><option value="trend">Mayor tendencia</option><option value="recent">Más recientes</option><option value="name">A–Z</option>
        <option value="period" data-p>Más registros en el periodo</option></select>
      <span class="chip" id="count">…</span>
    </div>
    <div class="period-banner glass" id="catPeriod" hidden></div>
    <div class="cards" id="cards"></div>
    <div class="load-more"><button class="btn" id="more" hidden>Cargar más especies</button></div>`;
  const $ = (id) => el.querySelector(`#${id}`);
  ["threat", "flag", "sort"].forEach((k) => { $(k).value = f[k] || ""; });
  let offset = 0, total = 0, facetsLoaded = false;

  io = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting) { io.unobserve(en.target); hydrate(en.target); }
  }), { rootMargin: "300px" });

  let token = 0;
  async function load(reset) {
    const t = ++token;
    const p = getPeriod();
    // Opciones que solo tienen sentido con un periodo activo
    $("sort").querySelectorAll("[data-p]").forEach((o) => { o.hidden = !p?.active; o.disabled = !p?.active; });
    const q = { ...f };
    // Con un periodo activo solo se listan las especies registradas en él
    delete q.presence;
    if (p?.active) q.presence = "period";
    else if (q.sort === "period") q.sort = "records";
    if (reset) { offset = 0; }
    store.set("catalog.filters", { threat: f.threat, sort: f.sort, flag: f.flag });
    const res = await api.species(state.wsId, { ...q, ...periodParams(p), limit: PAGE, offset });
    if (t !== token) return;
    if (reset) $("cards").innerHTML = "";
    total = res.total;
    const ps = res.period;
    $("catPeriod").hidden = !ps;
    if (ps) {
      $("catPeriod").innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>
        <span>Periodo <b>${esc(p.label)}</b>: ${fmt.n(ps.species)} especies con registros y ${fmt.n(ps.records)} registros.</span>`;
    }
    if (!facetsLoaded) {
      $("tax_class").innerHTML += Object.entries(res.facets.tax_class).map(([c, n]) => `<option value="${esc(c)}">${esc(c)} (${n})</option>`).join("");
      $("tax_class").value = f.tax_class || ""; facetsLoaded = true;
    }
    $("count").textContent = `${fmt.n(total)} especies`;
    res.items.forEach((sp, i) => $("cards").appendChild(card(sp, i, p?.active ? p : null)));
    offset += res.items.length;
    $("more").hidden = offset >= total;
    if (!res.items.length && reset) $("cards").innerHTML = `<div class="empty">Sin especies para estos filtros.</div>`;
  }

  const reload = debounce(() => load(true), 280);
  $("q").oninput = (e) => { f.q = e.target.value; reload(); };
  ["threat", "tax_class", "flag", "sort"].forEach((k) => { $(k).onchange = (e) => { f[k] = e.target.value; load(true); }; });
  const off = onPeriod(() => load(true));
  cleanup.push(off);
  $("more").onclick = () => load(false);
  $("cards").onclick = (e) => { const c = e.target.closest(".sp-card"); if (c) openSpecies(c.dataset.sp); };
  $("cards").onkeydown = (e) => { if (e.key === "Enter") { const c = e.target.closest(".sp-card"); if (c) openSpecies(c.dataset.sp); } };

  // Inclinación 3D + reflejo que sigue al cursor
  const move = (e) => {
    const c = e.target.closest(".sp-card"); if (!c) return;
    const r = c.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    c.style.transform = `rotateX(${(0.5 - y) * 10}deg) rotateY(${(x - 0.5) * 12}deg) translateZ(0)`;
    c.style.setProperty("--mx", `${x * 100}%`); c.style.setProperty("--my", `${y * 100}%`);
  };
  const leave = (e) => { const c = e.target.closest?.(".sp-card"); if (c && !c.contains(e.relatedTarget)) c.style.transform = ""; };
  $("cards").addEventListener("mousemove", move);
  $("cards").addEventListener("mouseout", leave);
  cleanup.push(() => { $("cards")?.removeEventListener("mousemove", move); });

  await load(true);
}

function card(sp, i, p = null) {
  const el = document.createElement("article");
  el.className = "sp-card";
  el.tabIndex = 0;
  el.dataset.sp = sp.species;
  el.dataset.key = sp.gbif_key || "";
  el.dataset.cat = sp.threat_national || sp.threat_global || "";
  el.style.animationDelay = `${(i % 12) * 35}ms`;
  el.setAttribute("aria-label", `${sp.common_name || sp.species}`);
  el.innerHTML = `
    <div class="glare"></div>
    <div class="photo"><img alt="" loading="lazy"></div>
    <div class="badges">${catBadge(sp.threat_national, "Col")}${catBadge(sp.threat_global, "IUCN")}${sp.cites ? `<span class="badge"><span class="code" style="background:#fff">C</span>CITES ${esc(sp.cites)}</span>` : ""}</div>
    <div class="body">
      <div class="common">${esc(sp.common_name || sp.species)}</div>
      <div class="sci">${esc(sp.species)}</div>
      <div class="fam">${esc(sp.tax_class || "")} · ${esc(sp.family || "")}</div>
      <div class="stats">
        ${p ? `<div><b>${fmt.compact(sp.n_period)}</b><span>en ${esc(p.label)}</span></div>
        <div><b>${fmt.compact(sp.n_records)}</b><span>todos los años</span></div>
        <div><b>${sp.last_year || "—"}</b><span>último</span></div>`
        : `<div><b>${fmt.compact(sp.n_records)}</b><span>registros</span></div>
        <div><b>${sp.aoo_km2 != null ? fmt.compact(sp.aoo_km2) : "—"}</b><span>AOO km²</span></div>
        <div><b>${sp.last_year || "—"}</b><span>último</span></div>`}
      </div>
    </div>
    <div class="swatch"></div>`;
  if (sp.media) paint(el, sp.media); else io.observe(el);
  return el;
}

async function hydrate(el) {
  try {
    const m = await api.media(el.dataset.sp, { gbif_key: el.dataset.key || undefined, category: el.dataset.cat || undefined });
    paint(el, m);
  } catch { /* sin foto: se mantiene la paleta neutra */ }
}

function paint(el, m) {
  const p = m.palette || {};
  el.style.setProperty("--c1", p.vibrant || "#3b4a63");
  el.style.setProperty("--c2", p.secondary || "#6b7a93");
  el.style.setProperty("--cd", p.dark || "#0d1422");
  el.style.setProperty("--cl", p.light || "#dfe6f2");
  el.querySelector(".swatch").innerHTML = [p.vibrant, p.secondary, ...(p.swatches || []).slice(0, 3)].filter(Boolean).map((c) => `<i style="background:${c}"></i>`).join("");
  const img = el.querySelector("img");
  if (m.thumb) { img.onload = () => img.classList.add("loaded"); img.src = m.thumb; img.alt = el.dataset.sp; }
  else img.remove();
}

export function unmount() { io?.disconnect(); io = null; cleanup.forEach((fn) => fn()); cleanup = []; }
