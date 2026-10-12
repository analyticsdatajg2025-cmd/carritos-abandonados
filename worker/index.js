// Carritos abandonados: guarda el JSON diario (lo sube GitHub Actions) y lo sirve con clave.
//
//   GET  /?key=K                          panel para ver como va
//   GET  /carritos/<marca>.json?key=K     lo ultimo de esa marca (URL fija, como un feed)
//   GET  /carritos/<fecha>/<marca>.json?key=K
//   GET  /estado.json?key=K               resumen del ultimo dia + fechas guardadas
//   PUT  /subir/<fecha>/<archivo>.json    solo con Authorization: Bearer <SUBIDA_CLAVE>
//
// El JSON lleva nombres, DNI, correos y telefonos: nada se sirve sin clave y cada dia se borra
// solo a los DIAS_GUARDA dias.

const DIAS_GUARDA = 45;
const FECHA = /^\d{4}-\d{2}-\d{2}$/;
const MARCA = /^[a-z0-9_-]{1,40}$/;

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const ruta = url.pathname.replace(/\/+$/, "") || "/";

    if (req.method === "PUT" && ruta.startsWith("/subir/")) return subir(req, env, ruta);
    if (req.method !== "GET" && req.method !== "HEAD") return texto("Metodo no permitido", 405);

    const clave = url.searchParams.get("key") || (req.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
    if (!env.LECTURA_CLAVE || !igual(clave, env.LECTURA_CLAVE)) return texto("Falta la clave (?key=...)", 401);

    if (ruta === "/") return panel(env, clave);
    if (ruta === "/estado.json") return json(await estado(env));

    let m = ruta.match(/^\/carritos\/([a-z0-9_-]+)\.json$/);
    if (m) {
      const ultima = await env.CARRITOS.get("ultima");
      return archivo(env, ultima, m[1]);
    }
    m = ruta.match(/^\/carritos\/(\d{4}-\d{2}-\d{2})\/([a-z0-9_-]+)\.json$/);
    if (m) return archivo(env, m[1], m[2]);

    return texto("No existe", 404);
  },
};

async function subir(req, env, ruta) {
  const token = (req.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!env.SUBIDA_CLAVE || !igual(token, env.SUBIDA_CLAVE)) return texto("No autorizado", 401);
  const [, , fecha, nombre] = ruta.split("/");
  if (!FECHA.test(fecha || "")) return texto("Fecha invalida", 400);

  const cuerpo = await req.text();
  try { JSON.parse(cuerpo); } catch { return texto("No es JSON", 400); }
  const ttl = { expirationTtl: DIAS_GUARDA * 86400 };

  let m = (nombre || "").match(/^pedidos_([a-z0-9_-]+)_\d{4}-\d{2}-\d{2}\.json$/);
  if (m && MARCA.test(m[1])) {
    await env.CARRITOS.put("f/" + fecha + "/" + m[1], cuerpo, ttl);
    return json({ ok: true, guardado: fecha + "/" + m[1] });
  }
  if (/^resumen_\d{4}-\d{2}-\d{2}\.json$/.test(nombre || "")) {
    // El resumen llega al final: recien ahi la fecha pasa a ser «la ultima».
    await env.CARRITOS.put("f/" + fecha + "/resumen", cuerpo, ttl);
    const fechas = JSON.parse((await env.CARRITOS.get("fechas")) || "[]").filter((f) => f !== fecha);
    fechas.unshift(fecha);
    fechas.sort().reverse();
    await env.CARRITOS.put("fechas", JSON.stringify(fechas.slice(0, DIAS_GUARDA)));
    const ultima = await env.CARRITOS.get("ultima");
    if (!ultima || fecha >= ultima) await env.CARRITOS.put("ultima", fecha);
    return json({ ok: true, ultima: fecha });
  }
  return texto("Nombre de archivo no reconocido", 400);
}

async function archivo(env, fecha, marca) {
  if (!fecha || !FECHA.test(fecha) || !MARCA.test(marca)) return texto("Todavia no hay datos", 404);
  const cuerpo = await env.CARRITOS.get("f/" + fecha + "/" + marca);
  if (!cuerpo) return texto("No hay datos de " + marca + " para " + fecha, 404);
  return new Response(cuerpo, {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "private, no-store",
      "X-Fecha-Reporte": fecha,
      "X-Robots-Tag": "noindex",
    },
  });
}

async function estado(env) {
  const ultima = await env.CARRITOS.get("ultima");
  const fechas = JSON.parse((await env.CARRITOS.get("fechas")) || "[]");
  const resumen = ultima ? JSON.parse((await env.CARRITOS.get("f/" + ultima + "/resumen")) || "null") : null;
  return { ultima, hoy_lima: hoyLima(), al_dia: ultima === hoyLima(), resumen, fechas };
}

async function panel(env, clave) {
  const e = await estado(env);
  const r = e.resumen || { por_marca: {} };
  const base = "/carritos/";
  const k = "?key=" + encodeURIComponent(clave);
  const marcas = Object.entries(r.por_marca || {});
  const filas = marcas.map(([m, d]) => `<tr><td>${esc(m)}</td><td class="n">${fmt(d.pedidos)}</td><td class="n">${fmt(d.items)}</td><td class="n">S/ ${fmt(Math.round(d.venta))}</td><td><a href="${base}${esc(m)}.json${k}">JSON</a> <button data-u="${base}${esc(m)}.json${k}">Copiar URL</button></td></tr>`).join("");
  const hist = e.fechas.map((f) => `<li>${esc(f)} · ${["lacuracao", "efe", "otros"].map((m) => `<a href="${base}${f}/${m}.json${k}">${m}</a>`).join(" · ")}</li>`).join("");
  const sello = e.al_dia ? `<span class="ok">Al día</span>` : `<span class="mal">Sin el reporte de hoy</span>`;

  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>Carritos abandonados</title>
<style>
:root{--bg:#f7f7f5;--tx:#1d1d1b;--mu:#6b6b66;--ln:#e2e2dc;--ok:#1f7a3a;--mal:#b3261e;--ac:#2556c4}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--tx:#ecebe6;--mu:#9b9a93;--ln:#2c2c29;--ok:#5cc27a;--mal:#ff8a80;--ac:#8fb0ff}}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}p{color:var(--mu);margin:0 0 20px}
table{width:100%;border-collapse:collapse;margin:8px 0 24px}td,th{padding:8px 6px;border-bottom:1px solid var(--ln);text-align:left}
.n{text-align:right;font-variant-numeric:tabular-nums}a{color:var(--ac)}
button{font:inherit;font-size:13px;border:1px solid var(--ln);background:transparent;color:var(--tx);border-radius:6px;padding:2px 8px;cursor:pointer}
.ok,.mal{font-weight:600;padding:2px 10px;border-radius:99px;border:1px solid currentColor}.ok{color:var(--ok)}.mal{color:var(--mal)}
ul{padding-left:18px;color:var(--mu)}.tw{overflow-x:auto}
</style></head><body><main>
<h1>Carritos abandonados</h1>
<p>${sello} · último reporte: <b>${esc(e.ultima || "—")}</b> · generado ${esc(r.generado_el || "—")} (UTC) · ${fmt(r.pedidos || 0)} pedidos · ${fmt(r.skus_sin_ficha_en_el_feed || 0)} SKU sin ficha en el feed</p>
<div class="tw"><table><thead><tr><th>Marca</th><th class="n">Carritos</th><th class="n">Ítems</th><th class="n">Monto</th><th>URL fija</th></tr></thead><tbody>${filas || "<tr><td colspan=5>Todavía no llegó ningún reporte.</td></tr>"}</tbody></table></div>
<h2 style="font-size:16px">Días guardados (${DIAS_GUARDA} como máximo)</h2><ul>${hist || "<li>—</li>"}</ul>
</main><script>
document.addEventListener("click",e=>{const u=e.target.dataset&&e.target.dataset.u;if(!u)return;navigator.clipboard.writeText(location.origin+u).then(()=>{e.target.textContent="Copiada"})});
</script></body></html>`;
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "private, no-store" } });
}

function hoyLima() {
  return new Date(Date.now() - 5 * 3600e3).toISOString().slice(0, 10); // Peru: UTC-5 fijo
}
function igual(a, b) {
  if (typeof a !== "string" || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (n) => Number(n || 0).toLocaleString("es-PE");
const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "private, no-store" } });
const texto = (t, s) => new Response(t, { status: s, headers: { "Content-Type": "text/plain; charset=utf-8" } });
