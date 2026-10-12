# Reportes Magento — pedidos diarios a JSON

Toma el reporte de pedidos que llega todos los días por correo, lo convierte en
JSON separado por marca (La Curacao y EFE), le pega la ficha de cada producto
sacada del feed de la web, y lo sube al FTP.

## Antes de la primera corrida: dos contraseñas

Abre `config.json` y llena estos dos campos. Nadie más los ve: el archivo se
queda en tu computadora y el programa nunca los imprime.

1. **`correo.password`** — contraseña de aplicación de Gmail (no la de tu cuenta).
   - Necesitas verificación en 2 pasos activa.
   - Se saca en <https://myaccount.google.com/apppasswords>: le pones un nombre
     (por ejemplo «reportes magento») y Google te da 16 letras.
   - Va sin espacios: `abcdefghijklmnop`.
   - Si la cuenta es de la empresa y el botón no aparece, el administrador tiene
     bloqueadas las contraseñas de aplicación; avísame y lo paso a la API de Gmail.
2. **`ftp.password`** — la contraseña de `test@hablamas.pe` en `ftp.hablamas.pe`.
   Es la que en `FTp_hablamas.bat` dice `TU_CONTRASEÑA_AQUI`.

## Cómo se usa

Doble clic en **`Generar reporte.bat`**, o desde la consola:

```bash
python reportes.py
```

Variantes:

| Comando | Qué hace |
|---|---|
| `python reportes.py` | todo: correo → JSON → FTP |
| `python reportes.py --sin-ftp` | genera el JSON pero no sube nada |
| `python reportes.py --sin-correo` | usa el archivo más nuevo de `descargas/` |
| `python reportes.py --archivo "C:\ruta\reporte.csv"` | usa ese archivo |
| `python reportes.py --solo-correo` | solo baja el adjunto y para |
| `python reportes.py --fecha 2026-09-15` | etiqueta los archivos con otra fecha |

## Qué genera

En `salida/AAAA-MM-DD/`:

- `pedidos_lacuracao_AAAA-MM-DD.json`
- `pedidos_efe_AAAA-MM-DD.json`
- `pedidos_otros_AAAA-MM-DD.json` — SKULLCANDY y MOTOCORP, que salen en el mismo
  reporte pero no son ninguna de las dos marcas
- `resumen_AAAA-MM-DD.json` — pedidos, ítems y venta por marca, más los SKU que
  no se encontraron en el feed

Los cuatro archivos se suben al FTP, a la carpeta indicada en `config.json`
(por defecto `/reportes`). Si la carpeta no existe, el programa la crea.

## Cómo se ve un pedido

Una línea por producto del reporte se convierte en un pedido con sus ítems
adentro. Cada ítem trae además un bloque `catalog` con lo que dice el feed de la
web: título oficial, enlace, precio de lista, stock, imagen, marca, categoría de
Google y árbol de categorías.

```json
{
  "order_id": "3002008048",
  "store": "LACURACAO KIOSKO 2",
  "brand": "lacuracao",
  "modified_at": "2026-07-15T12:04:08Z",
  "contact": { "full_name": "...", "email": "...", "doc_number": "..." },
  "shipping_address": { "district": "Los Aquijes", "province": "Ica" },
  "totals": { "grand_total": 1049.36, "discount": -0.0 },
  "items": [
    {
      "sku": "55U65",
      "name": "TV iFFALCON 55\" 4K Ultra HD Google TV 55U65 by TCL",
      "quantity": 1.0,
      "line_total": 925.97,
      "dispatch_type": "RET",
      "pickup_store_name": "LA CURACAO Ica",
      "catalog": {
        "title": "TV iFFALCON 55\" 4K Ultra HD Google TV 55U65 by TCL",
        "link": "https://www.lacuracao.pe/tv-iffalcon-55u65-55u65.html",
        "price": 1099.0,
        "availability": "In Stock",
        "brand": "iFFALCON",
        "product_type": "Tecnología > Televisores > Smart TV",
        "match": "exacta"
      }
    }
  ],
  "item_count": 1,
  "units": 1.0
}
```

Cuando el SKU no está en el feed, `catalog` queda en `{"match": null}`. Pasa
sobre todo con productos de marketplace (los que traen `seller_name`), que no
entran al feed de Google.

## Qué se probó (2026-09-16)

- Reporte real de 5,3 MB (`Reporte_Ventas_Diarias (2).csv`, formato de cabeceras
  antiguo): 7 796 líneas → 6 052 pedidos en **1,8 segundos**. Cruce con el feed:
  **90 % de los ítems**.
- Muestra con el formato de cabeceras nuevo (el del correo de hoy, separado por
  tabulaciones y con fechas `16/09/2026`): fechas bien convertidas, dos líneas
  del mismo pedido fusionadas en un pedido de 2 ítems, tienda de retiro y datos
  del seller correctos.
- Acentos: el archivo llega en UTF‑8 limpio. Lo que ves como «PresiÃ³n» al
  abrirlo en Excel es Excel, no el archivo. Aun así el programa repara acentos
  rotos si algún día llega en otra codificación; verificado: 0 secuencias rotas
  en la salida, contra 16 en la primera versión.
- **FTP: probado de punta a punta.** Conecta a `ftp.hablamas.pe` con TLS
  explícito, crea `/reportes` y sube los cuatro archivos. Verificado listando
  la carpeta en el servidor. Ojo: `/reportes` está en la raíz de la cuenta,
  **fuera de `public_html`**, y así debe quedarse: el JSON lleva nombres, DNI,
  correos y direcciones de clientes, y dentro de `public_html` cualquiera con
  el enlace podría descargarlo.
- **Correo: no funciona todavía.** Gmail responde `Invalid credentials` con la
  contraseña de aplicación cargada. Probé las tres variantes (con espacios,
  sin espacios y en mayúsculas) y las tres fallan, así que no es un problema
  de formato. Lo más probable es que esa contraseña se haya creado en otra
  cuenta de Google: una contraseña de aplicación solo sirve en la cuenta donde
  nació. Mientras tanto, bajando el adjunto a mano y corriendo
  `python reportes.py --sin-correo` el resto del proceso funciona completo.

## Lo que falta

- [x] Las dos contraseñas ya están en `config.json`. La del FTP funciona.
- [ ] Arreglar el acceso a Gmail: decir de qué cuenta salió la contraseña de
      aplicación, o generar una nueva en la cuenta que recibe el reporte.
- [ ] Decidir qué se hace con SKULLCANDY y MOTOCORP: hoy van a `pedidos_otros`.
      Si quieren en un archivo de La Curacao, se agrega la regla en
      `config.json → marcas.reglas`.
- [ ] Si lo quieren automático todos los días, se programa con el Programador de
      tareas de Windows apuntando a `Generar reporte.bat`.
