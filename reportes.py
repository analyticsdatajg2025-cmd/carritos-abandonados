# -*- coding: utf-8 -*-
"""
Reporte diario de pedidos Magento -> JSON por marca -> FTP.

Pasos:
  1. lee la bandeja de Gmail por IMAP y baja el adjunto del reporte del dia
  2. lo interpreta (tab o coma, utf-8 o windows-1252, cabeceras viejas o nuevas)
  3. baja el feed de productos y cruza cada SKU para enriquecer los items
  4. arma un JSON anidado por marca (lacuracao / efe)
  5. lo sube por FTP a la carpeta del servidor

Uso:
  python reportes.py                      todo el proceso
  python reportes.py --sin-correo         usa el archivo mas nuevo de descargas/
  python reportes.py --archivo ruta.csv   usa ese archivo
  python reportes.py --sin-ftp            no sube nada, solo deja el JSON local
  python reportes.py --solo-correo        solo baja el adjunto y termina
"""

import argparse
import email
import imaplib
import io
import json
import os
import re
import ssl
import sys
import time
import zipfile
from datetime import datetime, timezone
from email.header import decode_header, make_header
from ftplib import FTP, FTP_TLS
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"
DESCARGAS = BASE / "descargas"
SALIDA = BASE / "salida"
CACHE = BASE / "cache"


# ---------------------------------------------------------------- utilidades

def log(msg):
    print("[" + datetime.now().strftime("%H:%M:%S") + "] " + str(msg), flush=True)


def cargar_config():
    """config.json en la PC; en GitHub Actions no existe y se usa la plantilla + secretos."""
    ruta = CONFIG if CONFIG.exists() else BASE / "config.ejemplo.json"
    if not CONFIG.exists() and not os.environ.get("GITHUB_ACTIONS"):
        sys.exit("Falta " + str(CONFIG) + ". Copia config.ejemplo.json a config.json y completalo.")
    with open(ruta, encoding="utf-8") as f:
        cfg = json.load(f)
    # Los secretos del repo pisan lo del archivo (asi nunca viajan en git).
    for env, (bloque, clave) in {
        "GMAIL_USUARIO": ("correo", "usuario"),
        "GMAIL_PASSWORD": ("correo", "password"),
        "PUBLICAR_URL": ("publicar", "url"),
        "PUBLICAR_CLAVE": ("publicar", "clave"),
    }.items():
        if os.environ.get(env):
            cfg.setdefault(bloque, {})[clave] = os.environ[env]
    return cfg


def limpiar(v):
    """Texto listo para JSON: vacio, '-', 'NULL' y los espacios raros -> None.

    De paso repara los acentos rotos, que aparecen tanto en el reporte
    como en algunas descripciones del feed.
    """
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).replace(" ", " ").strip()
    if s in ("", "-", "--", "NULL", "null", "nan", "NaN", "None", "0000-00-00"):
        return None
    return reparar_texto(s)


def num(v):
    """Numero tolerante: '1,234.56', '1234,56', ' 499 ' -> float. Vacio -> None."""
    s = limpiar(v)
    if s is None:
        return None
    s = s.replace(" ", "").replace("S/", "").replace("PEN", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        entero, _, dec = s.rpartition(",")
        s = entero.replace(",", "") + "." + dec if len(dec) in (1, 2) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


MOJIBAKE = re.compile("[ÂÃ][-¿]")


def reparar_texto(s):
    """Arregla los acentos rotos (utf-8 leido como windows-1252).

    Repara trozo por trozo, no la cadena entera, para que un texto mezclado
    (una parte sana y otra rota) no se quede sin arreglar.
    """
    if not isinstance(s, str) or not MOJIBAKE.search(s):
        return s

    def arregla(m):
        try:
            return m.group(0).encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return m.group(0)

    return MOJIBAKE.sub(arregla, s)


# ------------------------------------------------------------------- correo

def bajar_adjunto(cfg):
    """Busca en Gmail el correo del reporte y guarda su adjunto en descargas/."""
    c = cfg["correo"]
    if not c.get("password"):
        sys.exit("Falta la contrasena de aplicacion en config.json -> correo.password")

    log("conectando a " + c["servidor"] + " como " + c["usuario"])
    imap = imaplib.IMAP4_SSL(c["servidor"], c.get("puerto", 993),
                             ssl_context=ssl.create_default_context())
    try:
        imap.login(c["usuario"], c["password"].replace(" ", ""))
    except imaplib.IMAP4.error as e:
        sys.exit(
            "Gmail rechazo el acceso: " + str(e) + "\n"
            "Repasa, en este orden:\n"
            "  1. que la contrasena de aplicacion sea de la cuenta " + c["usuario"] + "\n"
            "     (una contrasena de aplicacion solo sirve en la cuenta donde se creo)\n"
            "  2. que siga viva, en https://myaccount.google.com/apppasswords\n"
            "  3. que IMAP este activado, en Gmail > Configuracion > Reenvio y correo POP/IMAP"
        )
    imap.select(c.get("carpeta", "INBOX"))

    dias = max(1, int(c.get("dias_atras", 1)))
    desde = (datetime.now() - pd.Timedelta(days=dias - 1)).strftime("%d-%b-%Y")
    partes = ['(SINCE "' + desde + '")']
    if c.get("remitente"):
        partes.append('(FROM "' + c["remitente"] + '")')
    consulta = " ".join(partes)
    log("buscando: " + consulta)
    ok, datos = imap.search(None, consulta)
    ids = datos[0].split() if ok == "OK" else []
    if not ids:
        imap.logout()
        sys.exit("No hay correos que coincidan. Revisa correo.remitente y correo.dias_atras.")

    patron_asunto = re.compile(c.get("asunto_contiene", ""), re.I)
    patron_adj = re.compile(c.get("adjunto_patron", r"\.(csv|txt|xlsx|zip)$"), re.I)
    vistos = []

    for uid in reversed(ids):  # del mas nuevo al mas viejo
        ok, cruda = imap.fetch(uid, "(RFC822)")
        if ok != "OK":
            continue
        msg = email.message_from_bytes(cruda[0][1])
        asunto = str(make_header(decode_header(msg.get("Subject", ""))))
        vistos.append(asunto)
        if not patron_asunto.search(asunto):
            continue
        for parte in msg.walk():
            nombre = parte.get_filename()
            if not nombre:
                continue
            nombre = str(make_header(decode_header(nombre)))
            if not patron_adj.search(nombre):
                continue
            destino = DESCARGAS / (datetime.now().strftime("%Y-%m-%d") + "_" + nombre)
            destino.write_bytes(parte.get_payload(decode=True))
            log("correo: " + asunto)
            log("adjunto guardado: " + destino.name +
                " (" + format(destino.stat().st_size / 1e6, ".1f") + " MB)")
            imap.logout()
            return destino

    imap.logout()
    log("asuntos encontrados: " + " | ".join(vistos[:15]))
    sys.exit("Ningun correo traia un adjunto que calce. Revisa asunto_contiene y adjunto_patron.")


# ------------------------------------------------------- lectura del reporte

ALIAS = {
    "TIENDA": ["TIENDA"],
    "FECHA": ["FECHA_MOD", "FECHA_PED", "FECHA"],
    "HORA": ["HORA24_MOD", "HORA24", "HORA"],
    "PEDIDO": ["NUMERO_PEDIDO"],
    "STATUS": ["STATUS"],
    "ESTADO_WEB": ["ESTADO_WEB_PEDIDO"],
    "TOTAL": ["TOTAL_PEDIDO"],
    "TOT_MED_PAGO": ["TOT_MED_PAGO"],
    "MEDIO_PAGO": ["TIPO_MEDIO_PAGO"],
    "NOMBRE": ["NOMBRE_DESPACHO"],
    "MEMBER_ID": ["MEMBER_ID"],
    "TIP_DOC_CLI": ["TIP_DOC_CLI"],
    "DOC_CLI": ["DOCUMENTO_CLIENTE"],
    "CORREO": ["CORREO", "E-MAIL", "EMAIL"],
    "DIRECCION": ["DIRECCION", "DIRECCION DE ENTREGA"],
    "DISTRITO": ["DISTRITO"],
    "PROVINCIA": ["PROVINCIA"],
    "DEPARTAMENTO": ["DEPARTAMENTO"],
    "TELEFONO": ["TELEFONO"],
    "CELULAR": ["CELULAR"],
    "FECHA_DESPACHO": ["FECHA_DESPACHO"],
    "TIP_DOC": ["TIP_DOC"],
    "RUC": ["RUC"],
    "RAZON_SOCIAL": ["RAZON_SOCIAL"],
    "TOTAL_ANTES": ["TOTAL_PEDIDO_SIN_DESCUENTO", "TOTAL_PEDIDO_PRODUCTOS_ANTES",
                    "TOTAL_PEDIDO_PRODUCTOS"],
    "COSTO_DESPACHO": ["COSTO_DESPACHO_PEDIDO"],
    "DESCUENTO": ["DESCTO_PEDIDO"],
    "SKU": ["SKU_PRODUCTO"],
    "DESCRIPCION": ["DESCRIPCION_PRODUCTO"],
    "SKU_SELLER": ["SKU_SELLER"],
    "TIENDA_SELLER": ["NOMBRE_TIENDA_SELLER"],
    "RUC_SELLER": ["RUC_SELLER"],
    "ORIGEN": ["ORIGEN_PRODUCTO"],
    "LINEA_TOTAL": ["TOTALPRODUCT_LINEA"],
    "CANTIDAD": ["QUANTITY"],
    "LINEA_ENVIO": ["SHIPCHARGE_LINEA"],
    "LINEA_AJUSTE": ["TOTALADJUSTMENT_LINEA"],
    "VENDEDOR": ["VENDEDOR"],
    "PROMO1": ["COD_PROMOCION_1"],
    "PROMO2": ["COD_PROMOCION_2"],
    "PROMO3": ["COD_PROMOCION_3"],
    "TIPO_USUARIO": ["TIPO_USUARIO"],
    "TIPO_DESPACHO": ["TIPO_DESPACHO"],
    "COD_TIENDA_RET": ["COD_TIENDA_RETIRO"],
    "TIENDA_RET": ["TIENDA_RETIRO"],
    "CONSENTIMIENTO": ["CONSENTIMIENTO"],
    "USER_AGENT": ["USER_AGENT"],
    "URL_CARRITO": ["URL_NUEVO_CARRITO"],
    "URL_IMAGEN": ["URL_IMAGEN_PRODUCTO"],
}


def normaliza_cabecera(nombre):
    s = str(nombre).replace("﻿", "").strip().upper()
    return re.sub(r"\s+", " ", s)


def leer_reporte(ruta):
    """Devuelve un DataFrame de texto con las columnas renombradas a claves internas."""
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".zip":
        with zipfile.ZipFile(ruta) as z:
            interno = next(n for n in z.namelist()
                           if n.lower().endswith((".csv", ".txt", ".xlsx")))
            log("dentro del zip: " + interno)
            datos = z.read(interno)
            ruta = Path(interno)
    else:
        datos = ruta.read_bytes()

    if ruta.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(io.BytesIO(datos), dtype=str)
    else:
        codificacion = "latin-1"
        for enc in ("utf-8-sig", "utf-8", "cp1252"):
            try:
                datos.decode(enc)
                codificacion = enc
                break
            except UnicodeDecodeError:
                continue
        texto = datos.decode(codificacion, errors="replace")
        primera = texto.split("\n", 1)[0]
        sep = max(("\t", ";", ","), key=primera.count)
        log("codificacion " + codificacion + ", separador " + repr(sep))
        df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str,
                         keep_default_na=False, na_values=[""])

    df.columns = [normaliza_cabecera(c) for c in df.columns]
    # una cabecera repetida (DISTRITO, PROVINCIA... salen dos veces) se queda con la primera
    df = df.loc[:, ~df.columns.duplicated()]

    columnas, faltan = {}, []
    for clave, posibles in ALIAS.items():
        hallada = next((p for p in posibles if p in df.columns), None)
        if hallada:
            columnas[hallada] = clave
        else:
            faltan.append(clave)
    df = df[list(columnas)].rename(columns=columnas)
    for clave in faltan:
        df[clave] = None
    if faltan:
        log("columnas ausentes en el archivo (quedan vacias): " + ", ".join(faltan))

    df = df[df["PEDIDO"].map(limpiar).notna()]
    log("lineas de pedido leidas: " + format(len(df), ","))
    return df


# --------------------------------------------------------- feed de productos

def cargar_feeds(cfg):
    """Un par de indices de SKU por marca. feed.urls = {marca: url}; feed.url (viejo) vale para todas."""
    f = cfg["feed"]
    if not f.get("activo", True):
        return {}
    urls = f.get("urls") or {"*": f["url"]}
    indices = {}
    for marca, url in urls.items():
        try:
            indices[marca] = cargar_feed(url, marca, f)
        except Exception as e:  # sin feed el JSON igual sale, solo sin ficha
            log("feed de " + marca + " no disponible (" + str(e) + "); sigue sin cruce")
    return indices


def cargar_feed(url, marca, f):
    """Baja (o reusa del dia) un feed y devuelve dos indices de SKU."""
    destino = CACHE / ("feed_" + marca.strip("*") + "_" + datetime.now().strftime("%Y-%m-%d") + ".txt")
    horas = f.get("horas_cache", 12)
    if destino.exists() and (time.time() - destino.stat().st_mtime) < horas * 3600:
        log("feed en cache: " + destino.name)
    else:
        import urllib.request
        log("bajando feed: " + url)
        req = urllib.request.Request(url, headers={"User-Agent": "reportes-magento/1.0"})
        with urllib.request.urlopen(req, timeout=f.get("timeout", 180)) as r:
            destino.write_bytes(r.read())
        log("feed guardado: " + format(destino.stat().st_size / 1e6, ".1f") + " MB")

    with open(destino, encoding="utf-8-sig") as fh:
        primera = fh.readline()
    sep = "\t" if primera.count("\t") > primera.count(",") else ","
    feed = pd.read_csv(destino, sep=sep, dtype=str, encoding="utf-8-sig",
                       keep_default_na=False, na_values=[""], on_bad_lines="skip")
    feed.columns = [c.strip().lower() for c in feed.columns]
    log("productos en el feed de " + marca + ": " + format(len(feed), ","))

    def ficha(fila):
        precio = limpiar(fila.get("price"))
        monto, moneda = None, None
        if precio:
            trozos = precio.split()
            monto = num(trozos[0])
            moneda = trozos[1] if len(trozos) > 1 else "PEN"
        return {
            "title": limpiar(fila.get("title")),
            "link": limpiar(fila.get("link")),
            "price": monto,
            "currency": moneda,
            "availability": limpiar(fila.get("availability")),
            "image_link": limpiar(fila.get("image_link")),
            "brand": limpiar(fila.get("brand")),
            "condition": limpiar(fila.get("condition")),
            "google_product_category": limpiar(fila.get("google_product_category")),
            "product_type": limpiar(fila.get("product_type")),
            "feed_origin": limpiar(fila.get("custom_label_0")) or limpiar(fila.get("custom_label_4")),
            "description": limpiar(fila.get("description")),
        }

    exacto, suelto = {}, {}
    for fila in feed.to_dict("records"):
        sku = limpiar(fila.get("id"))
        if not sku:
            continue
        datos = ficha(fila)
        exacto.setdefault(sku.lower(), datos)
        suelto.setdefault(re.sub(r"[^a-z0-9]", "", sku.lower()), datos)
    return exacto, suelto


def buscar_producto(sku, indices, marca):
    """Primero en el feed de su marca; si no esta, en los demas (Skullcandy y otros no tienen feed)."""
    if not sku:
        return None, None
    k = sku.strip().lower()
    k2 = re.sub(r"[^a-z0-9]", "", k)
    orden = sorted(indices, key=lambda m: m not in (marca, "*"))
    for m in orden:
        exacto, suelto = indices[m]
        if k in exacto:
            return exacto[k], "exacta"
        if k2 and k2 in suelto:
            return suelto[k2], "aproximada"
    return None, None


# -------------------------------------------------------------- armado JSON

FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")


def a_iso(fecha, hora):
    f = limpiar(fecha)
    h = limpiar(hora) or "00:00:00"
    if not f:
        return None
    d = None
    for formato in FORMATOS_FECHA:
        try:
            d = datetime.strptime(f[:10], formato)
            break
        except ValueError:
            continue
    if d is None:
        return f
    trozos = (h.split()[0].split(":") + ["0", "0", "0"])[:3]
    try:
        d = d.replace(hour=int(trozos[0]), minute=int(trozos[1]), second=int(trozos[2]))
    except (ValueError, TypeError):
        pass
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def a_fecha(valor):
    f = limpiar(valor)
    if not f:
        return None
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(f[:10], formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return f


def marca_de(tienda, reglas, por_defecto):
    t = (limpiar(tienda) or "").upper()
    for prefijo, marca in reglas.items():
        if t.startswith(prefijo.upper()):
            return marca
    return por_defecto


def armar_pedidos(df, indices, cfg):
    reglas = cfg["marcas"]["reglas"]
    por_defecto = cfg["marcas"].get("por_defecto", "otros")
    pedidos, sin_ficha = {}, {}

    for fila in df.to_dict("records"):
        pid = limpiar(fila["PEDIDO"])
        sku = limpiar(fila["SKU"])
        marca = marca_de(fila["TIENDA"], reglas, por_defecto)
        producto, calce = buscar_producto(sku, indices, marca)
        if producto is None and sku:
            sin_ficha[sku] = sin_ficha.get(sku, 0) + 1

        item = {
            "sku": sku,
            "name": limpiar(fila["DESCRIPCION"]),
            "seller_sku": limpiar(fila["SKU_SELLER"]),
            "seller_name": limpiar(fila["TIENDA_SELLER"]),
            "seller_ruc": limpiar(fila["RUC_SELLER"]),
            "origin": limpiar(fila["ORIGEN"]),
            "quantity": num(fila["CANTIDAD"]),
            "line_total": num(fila["LINEA_TOTAL"]),
            "shipping_charge": num(fila["LINEA_ENVIO"]),
            "adjustment": num(fila["LINEA_AJUSTE"]),
            "pickup_store_code": limpiar(fila["COD_TIENDA_RET"]),
            "pickup_store_name": limpiar(fila["TIENDA_RET"]),
            "dispatch_type": limpiar(fila["TIPO_DESPACHO"]),
            "image_url": limpiar(fila["URL_IMAGEN"]) or (producto or {}).get("image_link"),
            "catalog": dict(producto, match=calce) if producto else {"match": None},
        }

        if pid in pedidos:
            pedidos[pid]["items"].append(item)
            if not pedidos[pid]["recover_cart_url"]:
                pedidos[pid]["recover_cart_url"] = limpiar(fila["URL_CARRITO"])
            continue

        promos = [limpiar(fila[c]) for c in ("PROMO1", "PROMO2", "PROMO3")]
        pedidos[pid] = {
            "order_id": pid,
            "store": limpiar(fila["TIENDA"]),
            "brand": marca,
            "modified_at": a_iso(fila["FECHA"], fila["HORA"]),
            "status": limpiar(fila["STATUS"]),
            "web_status": limpiar(fila["ESTADO_WEB"]),
            "document_type": limpiar(fila["TIP_DOC"]),
            "recover_cart_url": limpiar(fila["URL_CARRITO"]),
            "contact": {
                "full_name": limpiar(fila["NOMBRE"]),
                "email": limpiar(fila["CORREO"]),
                "phone": limpiar(fila["CELULAR"]) or limpiar(fila["TELEFONO"]),
                "member_id": limpiar(fila["MEMBER_ID"]),
                "doc_type": limpiar(fila["TIP_DOC_CLI"]),
                "doc_number": limpiar(fila["DOC_CLI"]),
                "accepts_marketing": limpiar(fila["CONSENTIMIENTO"]),
            },
            "shipping_address": {
                "address": limpiar(fila["DIRECCION"]),
                "district": limpiar(fila["DISTRITO"]),
                "province": limpiar(fila["PROVINCIA"]),
                "department": limpiar(fila["DEPARTAMENTO"]),
                "scheduled_date": a_fecha(fila["FECHA_DESPACHO"]),
            },
            "billing": {
                "ruc": limpiar(fila["RUC"]),
                "business_name": limpiar(fila["RAZON_SOCIAL"]),
            },
            "payment": {
                "method": limpiar(fila["MEDIO_PAGO"]),
                "amount_paid": num(fila["TOT_MED_PAGO"]),
            },
            "totals": {
                "grand_total": num(fila["TOTAL"]),
                "total_before_discount": num(fila["TOTAL_ANTES"]),
                "shipping_cost": num(fila["COSTO_DESPACHO"]),
                "discount": num(fila["DESCUENTO"]),
            },
            "meta": {
                "user_type": limpiar(fila["TIPO_USUARIO"]),
                "seller_flag": limpiar(fila["VENDEDOR"]),
                "promo_codes": [p for p in promos if p],
                "user_agent": limpiar(fila["USER_AGENT"]),
            },
            "items": [item],
        }

    lista = []
    for p in pedidos.values():
        p["item_count"] = len(p["items"])
        p["units"] = sum(i["quantity"] or 0 for i in p["items"])
        lista.append(p)
    lista.sort(key=lambda p: (p["modified_at"] or "", p["order_id"]), reverse=True)
    return lista, sin_ficha


# ------------------------------------------------------------------ escribir

def escribir(pedidos, sin_ficha, cfg, fecha):
    carpeta = SALIDA / fecha
    carpeta.mkdir(parents=True, exist_ok=True)
    indentado = 2 if cfg["salida"].get("legible", True) else None
    generados = []

    grupos = {}
    for p in pedidos:
        grupos.setdefault(p["brand"], []).append(p)

    for marca, lista in sorted(grupos.items()):
        ruta = carpeta / ("pedidos_" + marca + "_" + fecha + ".json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(lista, f, ensure_ascii=False, indent=indentado)
        items = sum(p["item_count"] for p in lista)
        cruzados = sum(1 for p in lista for i in p["items"] if i["catalog"].get("match"))
        pct = (cruzados / items * 100) if items else 0
        log(ruta.name + ": " + format(len(lista), ",") + " pedidos, " +
            format(items, ",") + " items, " + format(cruzados, ",") +
            " cruzados con el feed (" + format(pct, ".0f") + "%), " +
            format(ruta.stat().st_size / 1e6, ".1f") + " MB")
        generados.append(ruta)

    resumen = {
        "generado_el": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fecha_reporte": fecha,
        "pedidos": len(pedidos),
        "items": sum(p["item_count"] for p in pedidos),
        "por_marca": {
            m: {
                "pedidos": len(l),
                "items": sum(p["item_count"] for p in l),
                "venta": round(sum(p["totals"]["grand_total"] or 0 for p in l), 2),
            }
            for m, l in sorted(grupos.items())
        },
        "skus_sin_ficha_en_el_feed": len(sin_ficha),
        "top_skus_sin_ficha": sorted(sin_ficha.items(), key=lambda x: -x[1])[:50],
        "archivos": [r.name for r in generados],
    }
    ruta = carpeta / ("resumen_" + fecha + ".json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    generados.append(ruta)
    return generados, resumen


# ----------------------------------------------------------------------- FTP

def subir(archivos, cfg):
    c = cfg["ftp"]
    if not c.get("activo", True):
        log("subida al FTP desactivada en config.json")
        return
    if not c.get("password"):
        sys.exit("Falta la contrasena del FTP en config.json -> ftp.password")

    log("conectando al FTP " + c["servidor"] + " como " + c["usuario"])
    ftp = FTP_TLS(timeout=c.get("timeout", 120)) if c.get("tls", True) else FTP(timeout=c.get("timeout", 120))
    ftp.connect(c["servidor"], c.get("puerto", 21))
    ftp.login(c["usuario"], c["password"])
    if c.get("tls", True):
        ftp.prot_p()

    destino = c.get("carpeta", "/").strip("/")
    if destino:
        actual = ""
        for tramo in destino.split("/"):
            actual += "/" + tramo
            try:
                ftp.cwd(actual)
            except Exception:
                ftp.mkd(actual)
                ftp.cwd(actual)
    for ruta in archivos:
        with open(ruta, "rb") as f:
            ftp.storbinary("STOR " + ruta.name, f, blocksize=1 << 20)
        log("subido: /" + destino + "/" + ruta.name)
    ftp.quit()


# ------------------------------------------------------------- URL privada

def publicar(archivos, cfg, fecha):
    """Sube cada JSON al Worker de carritos. El resumen va al final: es el que da la fecha por completa."""
    c = cfg.get("publicar") or {}
    if not c.get("activo") or not c.get("url"):
        log("publicacion en la URL privada desactivada")
        return
    if not c.get("clave"):
        sys.exit("Falta la clave de subida (secreto PUBLICAR_CLAVE)")
    import urllib.request
    base = c["url"].rstrip("/")
    for ruta in sorted(archivos, key=lambda r: r.name.startswith("resumen_")):
        req = urllib.request.Request(
            base + "/subir/" + fecha + "/" + ruta.name, data=ruta.read_bytes(), method="PUT",
            headers={"Authorization": "Bearer " + c["clave"], "Content-Type": "application/json",
                     "User-Agent": "reportes-magento/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            log("publicado: " + ruta.name + " (" + str(r.status) + ")")


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Reporte diario Magento -> JSON -> FTP")
    ap.add_argument("--archivo", help="usa este archivo en vez de leer el correo")
    ap.add_argument("--sin-correo", action="store_true",
                    help="usa el archivo mas nuevo de descargas/")
    ap.add_argument("--sin-ftp", action="store_true", help="no sube nada")
    ap.add_argument("--solo-correo", action="store_true", help="solo baja el adjunto")
    ap.add_argument("--fecha", help="etiqueta de fecha AAAA-MM-DD (por defecto, hoy)")
    args = ap.parse_args()

    inicio = time.time()
    cfg = cargar_config()
    for d in (DESCARGAS, SALIDA, CACHE):
        d.mkdir(exist_ok=True)

    if args.archivo:
        origen = Path(args.archivo)
    elif args.sin_correo:
        candidatos = sorted([p for p in DESCARGAS.glob("*") if p.is_file()],
                            key=lambda p: p.stat().st_mtime)
        if not candidatos:
            sys.exit("No hay archivos en " + str(DESCARGAS))
        origen = candidatos[-1]
        log("usando el mas reciente de descargas/: " + origen.name)
    else:
        origen = bajar_adjunto(cfg)
        if args.solo_correo:
            return

    fecha = args.fecha or datetime.now().strftime("%Y-%m-%d")
    df = leer_reporte(origen)
    indices = cargar_feeds(cfg)
    pedidos, sin_ficha = armar_pedidos(df, indices, cfg)
    archivos, resumen = escribir(pedidos, sin_ficha, cfg, fecha)

    if not args.sin_ftp:
        subir(archivos, cfg)
        publicar(archivos, cfg, fecha)

    log("listo en " + format(time.time() - inicio, ".1f") + " s  |  " +
        format(resumen["pedidos"], ",") + " pedidos, " +
        format(resumen["items"], ",") + " items")


if __name__ == "__main__":
    main()
