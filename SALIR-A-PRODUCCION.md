# Salir a producción — Reportes Magento

Cinco pasos. Cada uno dice **cómo se comprueba** que quedó hecho.
El programa funciona: lee el reporte, lo cruza con el feed (90% de los ítems) y
la subida al FTP está probada. Lo que no entra es el correo.

## 1. Arreglar el acceso a Gmail
La contraseña de aplicación que hay no funciona, y lo más probable es que se haya
creado **en otra cuenta de Google** distinta a la que recibe el reporte diario.

- En la cuenta que **sí** recibe el correo: activar la verificación en dos pasos
  y generar una contraseña de aplicación nueva para «Correo».
- Ponerla en `config.json`. **Ese archivo no entra a git** y no se pega en un
  chat.
- **Se comprueba así**: el programa corre y descarga el adjunto del día sin que
  nadie lo baje a mano.

## 2. Correr un día completo de punta a punta
- Ejecutar el programa con el correo del día.
- **Se comprueba así**: sale un JSON por marca, con una cantidad de pedidos que
  cuadra con el Excel del correo, y aparece en el FTP.

## 3. Comprobar dónde queda el JSON
El JSON lleva **nombre, DNI, correo y dirección de clientes**. La carpeta
`/reportes` del FTP tiene que estar **fuera de `public_html`**.

- **Se comprueba así**: pedir en el navegador la URL pública del JSON y recibir
  404 o 403. Si se descarga, hay que moverlo antes de seguir.

## 4. Que corra solo todos los días
Hoy alguien tiene que lanzarlo.

- Programador de tareas de Windows, a una hora en que la PC esté prendida y
  después de que llegue el correo.
- **Se comprueba así**: tres días seguidos con JSON nuevo en el FTP sin que
  nadie toque nada.

## 5. Avisar cuando falle
Si un día no llega el correo o cambia el formato del Excel, hoy nadie se
enteraría.

- **Se comprueba así**: se borra a propósito el adjunto de un día y queda
  registro del fallo en algún sitio que alguien mire (un log con fecha ya
  alcanza; un correo de aviso es mejor).

---

Cuando los cinco estén comprobados, se actualiza `ESTADO.md` y la fila de
**Reportes Magento** en `../CLAUDE.md`.
