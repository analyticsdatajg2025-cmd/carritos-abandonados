# Estado — Carritos abandonados (reportes Magento)

## Objetivo
Cada día a las 8:00 (Lima), leer en Gmail el correo de «Carritos Abandonados», pasar
el CSV a JSON por pedido (cruzado con el feed de catálogo) y publicarlo en una URL
privada con clave, una por marca.

## Hecho
- 2026-10-12: montado el flujo automático: GitHub Actions (`carritos.yml`) corre
  `reportes.py` y sube el JSON a un Worker de Cloudflare (cuenta empresa) con KV.
  Probado en local con el CSV real del 16/09: efe 2 432 pedidos (81 % cruzado),
  lacuracao 3 010 (82 %), otros 215. Subida, 401 sin clave, panel e histórico OK.
- 2026-10-12: columnas nuevas del CSV: `recover_cart_url` (URL_NUEVO_CARRITO) por
  pedido e `image_url` por ítem; feed por marca (`feed.urls`).
- 2026-10-12: repo privado `elias-figueroa-trabajo/carritos-abandonados` (rama main
  limpia, un commit; el historial viejo solo queda local).
- FTP `ftp.hablamas.pe` caído (530): desactivado, lo reemplaza el Worker.

## Pendiente
1. El dueño carga los 4 secretos del repo: GMAIL_PASSWORD (contraseña de aplicación
   de analytics.data.jg.2025@gmail.com, IMAP activo), CLOUDFLARE_API_TOKEN (empresa:
   Workers + KV edit), CARRITOS_CLAVE_LECTURA, CARRITOS_CLAVE_SUBIDA.
2. Correr el workflow a mano con `que=ambos` y revisar el panel
   `https://carritos-abandonados.<subdominio>.workers.dev/?key=...`.
3. Confirmar remitente/asunto real del correo en `config.ejemplo.json` si no lo halla.
4. SKULLCANDY y MOTOCORP caen en `pedidos_otros`: decidir marca.

## Archivos clave
- `reportes.py` — correo → CSV → JSON → publicar (variables de entorno pisan config).
- `config.ejemplo.json` — config que usa Actions (sin secretos).
- `config.json` — local, **con contraseñas, fuera de git**.
- `worker/index.js` + `wrangler.toml` — Worker: panel, `/carritos/<marca>.json?key=`,
  `/estado.json`, PUT `/subir/...` con Bearer. Guarda 45 días.
- `.github/workflows/carritos.yml` — cron 13/14/15 UTC; despliega el Worker al tocar `worker/`.

## Decisiones / cuidado con
- El JSON lleva nombres, DNI, correos y teléfonos: **nunca público** (sin clave → 401).
- Cuenta Cloudflare empresa: se despliega solo desde Actions, nunca `wrangler deploy` local.
- El id del KV no está en el repo: el workflow lo busca/crea y reemplaza `KV_ID`.
- Feeds en `analyticsdatajg2025-cmd.github.io` (los de elias-figueroa-trabajo dan 404).
- `catalog` = `{"match": null}` cuando el SKU no está en el feed (marketplace).
- Prueba local: `worker/.dev.vars` (ignorado) + `wrangler dev --local`.
