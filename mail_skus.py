# -*- coding: utf-8 -*-
"""
Arma un correo HTML de prueba con varios productos, a dos columnas, solo escritorio.

Uso:
    set MAGENTO_TOKEN=xxxxx
    set MAGENTO_SCOPE=default     (opcional: "default" = EFE, "all" = global)
    python mail_skus.py CH10 OTRO-SKU MAS-SKU

Deja el resultado en salida/mail_skus.html y lo abre en el navegador.
El token nunca se guarda en disco: sale de la variable de entorno MAGENTO_TOKEN.
"""
import os
import sys
import json
import html
import urllib.parse
import urllib.request
import webbrowser

DOMINIO = os.environ.get("MAGENTO_DOMINIO", "https://mcstaging.efe.com.pe")
# Scope de tienda: los precios cambian segun el website.
#   "default" -> precios de EFE (coinciden con efe.com.pe)
#   "all"     -> valores globales (coinciden con lacuracao.pe, pero muchos SKU salen sin precio)
# El code de la tienda de La Curacao no se puede consultar con el token de staging.
SCOPE = os.environ.get("MAGENTO_SCOPE", "default")
MEDIA = DOMINIO + "/media/catalog/product"
COLUMNAS = 2
ANCHO = 600  # px, solo escritorio


def traer(skus, token):
    p = {
        "searchCriteria[filter_groups][0][filters][0][field]": "sku",
        "searchCriteria[filter_groups][0][filters][0][value]": ",".join(skus),
        "searchCriteria[filter_groups][0][filters][0][condition_type]": "in",
        "fields": "items[sku,name,price,custom_attributes]",
    }
    url = DOMINIO + "/rest/" + SCOPE + "/V1/products?" + urllib.parse.urlencode(p)
    pedido = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(pedido, timeout=30) as r:
        datos = json.load(r)
    por_sku = {}
    for it in datos.get("items", []):
        attrs = {a["attribute_code"]: a["value"] for a in it.get("custom_attributes", [])}
        por_sku[it["sku"]] = {
            "sku": it["sku"],
            "nombre": it.get("name", ""),
            "precio": it.get("price"),
            "sin_precio": it.get("price") is None,
            "oferta": attrs.get("special_price"),
            "imagen": attrs.get("image", ""),
            "marca": attrs.get("efe_marca", ""),
        }
    return [por_sku[s] for s in skus if s in por_sku], [s for s in skus if s not in por_sku]


def soles(v):
    try:
        return "S/ {:,.2f}".format(float(v))
    except (TypeError, ValueError):
        return ""


def celda(p):
    e = html.escape
    img = MEDIA + p["imagen"] if p["imagen"] else ""
    precio = soles(p["precio"])
    oferta = soles(p["oferta"])
    if oferta and p["oferta"] and float(p["oferta"]) < float(p["precio"]):
        bloque_precio = (
            '<span style="color:#888;text-decoration:line-through;font-size:13px;">%s</span>'
            '&nbsp;<span style="color:#c00;font-size:18px;font-weight:bold;">%s</span>' % (precio, oferta)
        )
    else:
        bloque_precio = '<span style="font-size:18px;font-weight:bold;">%s</span>' % precio
    return """
      <td width="%d" valign="top" style="padding:12px;">
        <table width="100%%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e5e5e5;">
          <tr><td align="center" style="padding:16px;">
            %s
          </td></tr>
          <tr><td style="padding:0 16px 16px 16px;font-family:Arial,Helvetica,sans-serif;">
            <div style="font-size:11px;color:#999;text-transform:uppercase;">%s</div>
            <div style="font-size:14px;line-height:19px;color:#222;height:57px;overflow:hidden;">%s</div>
            <div style="font-size:11px;color:#bbb;margin:6px 0;">SKU %s</div>
            <div>%s</div>
          </td></tr>
        </table>
      </td>""" % (
        ANCHO // COLUMNAS,
        '<img src="%s" width="220" style="display:block;border:0;" alt="%s">' % (e(img), e(p["nombre"])) if img else '&nbsp;',
        e(p["marca"] or ""),
        e(p["nombre"]),
        e(p["sku"]),
        bloque_precio,
    )


def armar(productos):
    filas = []
    for i in range(0, len(productos), COLUMNAS):
        grupo = productos[i:i + COLUMNAS]
        celdas = "".join(celda(p) for p in grupo)
        while len(grupo) < COLUMNAS:
            celdas += '<td width="%d">&nbsp;</td>' % (ANCHO // COLUMNAS)
            grupo.append(None)
        filas.append("<tr>%s</tr>" % celdas)
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>Prueba productos</title></head>
<body style="margin:0;padding:24px 0;background:#f4f4f4;">
<table width="%d" cellpadding="0" cellspacing="0" border="0" align="center" style="background:#ffffff;">
  <tr><td style="padding:24px;font-family:Arial,Helvetica,sans-serif;font-size:20px;font-weight:bold;color:#222;border-bottom:1px solid #e5e5e5;">
    Productos seleccionados
  </td></tr>
  <tr><td style="padding:12px;">
    <table width="100%%" cellpadding="0" cellspacing="0" border="0">%s</table>
  </td></tr>
  <tr><td style="padding:20px 24px;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#999;border-top:1px solid #e5e5e5;">
    Correo de prueba. Precios y stock sujetos a confirmacion.
  </td></tr>
</table>
</body></html>""" % (ANCHO, "".join(filas))


def main():
    skus = [s.strip().upper() for s in sys.argv[1:] if s.strip()]
    if not skus:
        print("Uso: python mail_skus.py SKU1 SKU2 SKU3")
        return 1
    token = os.environ.get("MAGENTO_TOKEN")
    if not token:
        print("Falta la variable de entorno MAGENTO_TOKEN")
        return 1
    productos, faltan = traer(skus, token)
    print("Scope de tienda: %s  (%s)" % (SCOPE, DOMINIO))
    if faltan:
        print("No se encontraron: " + ", ".join(faltan))
    mudos = [p["sku"] for p in productos if p["sin_precio"]]
    if mudos:
        print("Sin precio en este scope: %s  (probar con MAGENTO_SCOPE=%s)"
              % (", ".join(mudos), "default" if SCOPE == "all" else "all"))
    if not productos:
        return 1
    destino = os.path.join(os.path.dirname(os.path.abspath(__file__)), "salida", "mail_skus.html")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(armar(productos))
    print("Listo: %s (%d productos)" % (destino, len(productos)))
    webbrowser.open("file:///" + destino.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
