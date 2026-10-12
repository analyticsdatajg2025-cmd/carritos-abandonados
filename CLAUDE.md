# Reportes Magento — especificación

Proyecto de trabajo (no es de la marca Dum Figueroa). Convierte el reporte
diario de pedidos de Magento que llega por correo en JSON por marca, enriquecido
con el feed de productos de la web, y lo deja en un FTP.

## Qué es

La Curacao y EFE corren sobre el mismo Magento. Todos los días llega a
`elias.figueroa.trabajo@gmail.com` un correo de «Reportes Magento» con el
reporte de pedidos como adjunto. Un tercero lo pide en JSON, en una carpeta del
servidor, todos los días.

## Restricciones

- **Python con pandas**, sin dependencias fuera de la librería estándar
  (`imaplib`, `ftplib`, `urllib` vienen con Python). No instalar nada nuevo sin
  justificarlo aquí.
- **Todo en un archivo**, `reportes.py`. Es un programa, no una librería.
- **Las contraseñas viven solo en `config.json`**, que no se comparte, no se
  pega en una respuesta y no se sube a ningún lado. `config.ejemplo.json` es el
  que sí se puede mostrar: va con los campos en blanco.
- **Rápido**: el reporte tiene miles de líneas y el feed 16 000 productos. El
  cruce se hace con diccionarios en memoria, nunca con un bucle sobre el feed
  por cada línea. Referencia medida: 1,8 s para 7 796 líneas.
- **Nada se borra**: cada corrida escribe en `salida/AAAA-MM-DD/`, no pisa días
  anteriores. `descargas/` y `cache/` se pueden vaciar a mano sin romper nada.

## Cómo está armado

`reportes.py`, en este orden:

1. `bajar_adjunto` — IMAP a Gmail (`imap.gmail.com:993`, SSL). Busca por
   `SINCE` de hoy y `FROM` el remitente del config, filtra por asunto y por
   nombre de adjunto, y guarda el más nuevo en `descargas/`.
2. `leer_reporte` — detecta codificación (`utf-8-sig`, `utf-8`, `cp1252`,
   `latin-1`) y separador (tabulación, `;`, `,`), lee todo como texto y renombra
   las columnas con el diccionario `ALIAS`. `ALIAS` existe porque el reporte
   cambió de cabeceras: el viejo traía `FECHA_PED` y subpedidos, el nuevo trae
   `FECHA_MOD` y no. Una columna que falte queda vacía, no rompe. Acepta `.csv`,
   `.txt`, `.xlsx` y `.zip`.
3. `cargar_feed` — baja `google_curacao.txt` (tabulado, UTF‑8, 16 000 filas) y
   arma dos índices: uno por SKU exacto en minúsculas y otro sin guiones ni
   puntos, para el calce aproximado. Se cachea en `cache/` por horas.
   **El mismo feed sirve para las dos marcas**: `efe.com.pe/media/feed/...`
   devuelve byte por byte el mismo archivo.
4. `armar_pedidos` — agrupa las líneas por `NUMERO_PEDIDO` y arma el JSON
   anidado. La marca sale de `TIENDA` por prefijo, según `marcas.reglas`.
5. `escribir` — un archivo por marca más `resumen_*.json`.
6. `subir` — `ftplib.FTP_TLS` (explícito, como el `ftpes://` del WinSCP), crea la
   carpeta destino si no existe y sube los archivos.

## Detalles que costaron y no hay que volver a descubrir

- **El archivo llega en UTF‑8 limpio.** Lo que se ve como «PresiÃ³n» es Excel
  abriendo UTF‑8 sin BOM como Windows‑1252. Aun así `reparar_texto` arregla
  mojibake, porque el propio feed trae descripciones mal codificadas de origen
  («refrigeraciÃ³n»).
- **`reparar_texto` vive dentro de `limpiar`**, no en un bucle sobre el
  DataFrame. En pandas 3.0 las columnas de texto ya no tienen dtype `object`,
  así que un `if df[col].dtype == object` nunca se cumple y la reparación no
  corría. Además, así también se repara el feed.
- **La reparación es por trozo** (regex `MOJIBAKE` + `sub`), no sobre la cadena
  entera: un texto con una parte sana y otra rota falla al reencodear completo.
- **Cabeceras repetidas**: el formato viejo trae `DISTRITO`, `PROVINCIA`,
  `DEPARTAMENTO` y `TELEFONO` dos veces (datos del cliente y del consignatario).
  Se conserva la primera (`df.columns.duplicated()`).
- **Los SKU de seller no están en el feed.** Un `catalog.match` nulo en una
  línea con `seller_name` es lo esperado, no un error. El cruce ronda el 90 %.
- **`TIENDA` trae más de dos marcas**: además de `LACURACAO*` y `EFE*` aparecen
  `SKULLCANDY`, `MOTOCORP` y `MOTOCORP KIOSKO 1`. Van a `pedidos_otros` hasta
  que el dueño diga otra cosa.

## Esquema de salida

Sigue el JSON que el dueño ya venía usando (`Escritorio\ARCHIVOS\salida.json`):
`order_id`, `store`, `modified_at`, `status`, `web_status`, `document_type`,
`contact`, `shipping_address`, `billing`, `payment`, `totals`, `meta`, `items`,
`item_count`. Añadidos de esta versión: `brand`, `units` y, en cada ítem,
`catalog` con la ficha del feed y `catalog.match` (`exacta`, `aproximada` o
`null`).

Si hay que cambiar el esquema, se cambia aquí primero y se avisa a quien recibe
el JSON.
