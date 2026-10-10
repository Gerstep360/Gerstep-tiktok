# Gerstep Interactive · VPS

React + Vite, Python/aiohttp y SQLite. La web se sirve bajo
`https://167.86.106.105/Gerstep/`. El programa Windows se conecta al VPS por
WebSocket saliente; el VPS no abre conexiones hacia tu PC.

## Instalación

Requiere Linux con systemd, Nginx ya instalado, Python 3.10+ y soporte `venv`.
La distribución determina cómo instalar esos paquetes. El ZIP preparado incluye
React compilado; **no hace falta Node en el VPS**.

1. Sube `artifacts/gerstep-interactive-vps.zip` y descomprímelo en una carpeta nueva.
2. Desde esa carpeta ejecuta:

```bash
sudo bash vps/install.sh /etc/nginx/sites-available/TU_SITIO_HTTPS
```

El archivo debe contener un único bloque HTTPS con
`server_name 167.86.106.105`. El instalador añade un `include`, hace una copia
`.gerstep-backup`, ejecuta `nginx -t` y restaura ese archivo si la validación falla.
Conserva los otros bloques y ubicaciones. Si tu configuración usa otro
`server_name` o un bloque por defecto, ejecuta sin argumento:

```bash
sudo bash vps/install.sh
```

Después añade **dentro del bloque HTTPS elegido**, sin sustituirlo:

```nginx
include /etc/nginx/snippets/gerstep-interactive.conf;
```

Valida con `sudo nginx -t` y recarga Nginx. La ruta `/Gerstep` redirige a
`/Gerstep/`; las otras aplicaciones siguen usando sus rutas actuales.

Se instala en `/opt/gerstep-interactive`, con usuario de servicio independiente,
base en `data/`, puerto loopback 9081 y servicio `gerstep-interactive`. Si ese
puerto está ocupado, la instalación inicial puede elegir otro:

```bash
sudo GERSTEP_PORT=9082 bash vps/install.sh /etc/nginx/sites-available/TU_SITIO_HTTPS
```

No se detienen servicios ajenos. En actualizaciones se conserva el puerto y los
secretos del archivo existente. Una validación fallida puede dejar los snippets
nuevos en disco; no se recarga una configuración inválida. El instalador no
reconfigura tu certificado ni instala automáticamente paquetes del sistema.

## Acceso y conexión

Abre `/Gerstep/login` directamente para entrar al panel. La web pública no
incluye un enlace administrativo. La contraseña del panel es el valor
`GERSTEP_ADMIN_TOKEN`, distinto de `GERSTEP_BRIDGE_TOKEN` y de la clave de firma.
El instalador genera los tres y los guarda en `/etc/gerstep-interactive.env`,
solo accesible por root. Consulta ese archivo de forma privada; no lo incluyas
en logs, capturas, repositorios o solicitudes del chat.

En el programa Windows, abre **Gerstep Interactive**, introduce
`https://167.86.106.105/Gerstep` y el `GERSTEP_BRIDGE_TOKEN`, y pulsa **Conectar web**.
Para moderar desde el programa introduce también la contraseña administrativa
independiente. Estas credenciales quedan en memoria durante la sesión.
Conecta TikTok y reanuda el presentador para habilitar respuestas del bot.

El panel permite aprobar, rechazar, seleccionar para OBS, responder personalmente,
enviar una respuesta breve al bot, crear/cerrar encuestas, elegir una pregunta
aprobada con la ruleta, bloquear sesiones, suspender la web y exportar marcas.
La ruleta no reproduce voz automáticamente.
Las encuestas incluyen un registro privado de votantes, con nombre, identidad,
opción y fuente. El panel muestra los 200 más recientes; la exportación NDJSON
descarga todos los votos conservados de esa encuesta por bloques de 500, sin
cargar toda la lista en RAM. La página pública no expone ese registro.

## Identidad y votos

Al entrar se crea `Anónimo[n]` sin exigir un apodo. El visitante puede elegir un
nombre o volver a ser anónimo. El servidor emite un token aleatorio; el navegador
lo conserva en localStorage y recibe una cookie HttpOnly. La base guarda el
hash del token. Cambiar el apodo no cambia la identidad ni los votos.

Cada encuesta admite **un voto web por IP**. Se puede cambiar la opción desde
la misma identidad sin añadir votos. Una segunda identidad en esa IP no puede
votar de nuevo. Los apoyos y límites de propuestas también consideran la IP.
No se guardan IPs en claro: se usa HMAC con una clave privada del servidor.
Nginx sobrescribe `X-Real-IP`; no pongas otro proxy delante sin adaptar esa
configuración a sus direcciones de confianza.

Una red compartida tiene un voto web total por encuesta. Cambiar de red/VPN puede
evadir el criterio por IP; no equivale a verificar una persona. TikTok no entrega
IPs: `/encuesta n` registra un voto por ID estable de TikTok. Sin vincular cuentas
no se puede demostrar que un votante web y uno de TikTok sean la misma persona.
El apodo web tampoco verifica un donante ni acredita su perfil de TikTok.

Retención: identidades inactivas 30 días; preguntas 24 h, hasta 200 pendientes y
2000 registros históricos; encuestas hasta 100 y 24 h tras cierre; 50.000 votos
por encuesta; marcas hasta 500/7 días. Regalos deduplicados hasta 50.000/30 días;
donantes y perfiles web se retiran tras 30 días de inactividad. El top global es
acumulado para esos perfiles conservados, no un ranking móvil exacto de 30 días.

## TikTok directo en el VPS (opcional)

Por defecto el PC es la fuente de eventos. Para usar la recepción independiente:

```bash
sudo /opt/gerstep-interactive/.venv/bin/pip install -r /opt/gerstep-interactive/vps/backend/requirements-collector.txt
```

Configura `GERSTEP_COLLECT_TIKTOK=1` y `GERSTEP_TIKTOK_USERNAME` en el archivo
privado y reinicia **solo** el servicio de Gerstep. El receptor reutiliza el
adaptador existente, no genera audio y se suspende cuando conecta el PC.
Su acceso real a TikTok depende del servicio, del LIVE y de la red del VPS;
no se ha probado una conexión real en este entorno.

El top de niveles sincroniza cada 30 s los perfiles existentes del PC. El receptor
opcional conserva sus propios perfiles cuando el PC no está conectado. La web
mantiene el mayor progreso recibido por ID; no suma dos historiales que podrían
solaparse. Fusionar exactamente la experiencia ganada en dos bases durante
desconexiones queda pendiente. Los tops de regalos deduplican los eventos recibidos,
pero no recuperan donaciones previas a la instalación ni eventos perdidos sin fuente
conectada. Cada conexión manual del PC inicia una sesión de stream distinta; las
reconexiones automáticas conservan la misma sesión.

## HTTPS con una IP

El instalador reutiliza tu bloque HTTPS y su certificado. El puente mantiene la
validación TLS activada. Un certificado para un dominio diferente no sirve para
`167.86.106.105`.

Let's Encrypt permite certificados para IP con validez corta; Certbot 5.4+ admite
`webroot`. Debes disponer de un directorio que tu Nginx sirva por HTTP en el puerto
80 para los desafíos ACME. Prueba primero con `--staging`, cuyo certificado no es
de confianza; después solicita el certificado de producción sin ese argumento.
No uses `standalone` para detener el Nginx que sirve las otras aplicaciones.
[Instrucciones oficiales de Certbot y certificados IP](https://letsencrypt.org/2026/03/11/shorter-certs-certbot).

```bash
sudo certbot certonly --preferred-profile shortlived --webroot \
  --webroot-path /RUTA_WEBROOT_EXISTENTE --ip-address 167.86.106.105
```

Selecciona las rutas del certificado emitido en tu bloque HTTPS y configura la
renovación automática con recarga de Nginx tras una renovación correcta. Los
certificados IP descritos por esa guía duran seis días. El instalador de Gerstep
no sustituye certificados que puedan compartir otras aplicaciones.

## OBS, música y operación

Añade `/Gerstep/overlay` como fuente de navegador en OBS, por ejemplo 1920×1080.
Solo se muestran preguntas seleccionadas y encuestas activas. El overlay local
`http://127.0.0.1:8765/overlay` también recibe la pregunta seleccionada.
Las marcas JSON contienen época UTC y segundos desde la primera conexión de esa
sesión, que puede diferir del comienzo de una grabación en OBS. No graban ni
publican clips. OBS ofrece un búfer de repetición con guardado por atajo:
[guía oficial de OBS](https://obsproject.com/kb/OBS-Studio-Overview).

Las solicitudes musicales aceptan enlaces de YouTube y pasan por moderación.
Activa música tanto en el panel web como en el PC. La reproducción usa el
reproductor visible ya existente del PC, con su cola y ducking; el VPS no descarga
audio, no elude DRM y no retransmite un reproductor oculto. Los permisos del
contenido y de retransmisión corresponden al catálogo que autorices.
El foco permanece como API abstracta, sin acciones físicas desde la web.

```bash
sudo systemctl status gerstep-interactive
sudo journalctl -u gerstep-interactive --since '10 minutes ago'
sudo systemctl restart gerstep-interactive
```

Los logs registran tipos de error, sin cuerpos de mensajes ni credenciales.
La web conserva su funcionamiento si el PC cae; el bot solo funciona mientras
Gerstep LIVE esté conectado. Los trabajos de voz anteriores no se reenvían al
reconectar. Si se pierde el puente, el PC sigue procesando su LIVE.

Para reconstruir React en desarrollo: `cd vps/frontend`, `npm ci`, `npm run build`.
La evidencia local y las limitaciones se describen en
`docs/GERSTEP_INTERACTIVE.md`. **El VPS real y el certificado no se han desplegado
ni comprobado desde este entorno.**
