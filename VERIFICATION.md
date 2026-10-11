# Verificación del repositorio independiente

Comprobaciones realizadas en desarrollo (Windows, Python 3.12):

| Comprobación | Resultado |
| --- | --- |
| Suite propia `python -m unittest discover -s tests -v` | 25 pruebas pasan. |
| ZIP extraído fuera del proyecto, entorno nuevo con solo requisitos aiohttp | Las mismas 25 pruebas pasan. Sin Gerstep LIVE, TikTokLive ni pygame instalados. |
| Login con hash de contraseña y claves independientes | HTTP real: contraseña válida entra; la clave API no se acepta como contraseña humana. |
| Envío → aprobación → actualización WebSocket | Servidor real local; también se sirve React compilado. |
| Solicitud YouTube | Validador independiente, sin módulos del PC; no descarga contenido. |
| Perfil del receptor opcional | ID estable tras renombrado, cooldown de comentarios, regalos deduplicados. |
| Adaptador TikTok | Cliente simulado: listeners únicos, descarte de duplicados/historial y cierre de HTTP. Sin acceso real a TikTok. |
| Instalador | Planes con systemd/Nginx simulados: instalación y recuperación tras fallo. Copias de código, conservación de datos y claves. |
| Parser/configuración Nginx | Mantiene otros bloques; inserción idempotente; HTTP ACME atraviesa redirecciones. |
| Nginx 1.30.5 para Windows real en loopback | `nginx -t`, TLS IP sin SNI, dominio con SNI, caché de certificados, HTTP y WebSocket pasan. Certificados de laboratorio. |
| React | Compilación de producción y cuatro pruebas SSR pasan. JS 252,41 kB (78,08 gzip), CSS 22,36 kB (5,67 gzip). |
| `bash -n install` | Sintaxis válida. |
| Paquete | ZIP sin datos, secretos, `.git`, `node_modules` ni código del escritorio; permiso Unix 0755 para `install`. |

El binario Nginx de prueba se obtuvo de su
[sitio oficial](https://nginx.org/en/download.html). El probe reproducible está
en `tests/nginx_probe.py`: utiliza los ejecutables indicados mediante
`NGINX_BINARY` y `OPENSSL_BINARY`, certificados temporales, loopback y puertos
libres. No instala servicios ni contacta al VPS.

Pendiente: instalación real en Linux/systemd, paquetes de su distribución,
permisos de los workers/SELinux cuando corresponda, configuración concreta de
Nginx, desafío ACME por Internet, renovación pública, conexión auténtica con
TikTok y ejecución prolongada en ese hardware. No se afirma que el VPS esté
desplegado. La revisión visual de la página en móvil/desktop también sigue
pendiente; SSR no sustituye renderizado en un navegador.
