# Gerstep Interactive

Repositorio independiente del programa Windows: React/Vite, Python/aiohttp,
SQLite y herramientas de despliegue. Se puede copiar **solamente esta carpeta**
o descomprimir su ZIP. No necesita el repositorio TikTok padre, Tkinter, pygame,
TTS, sonidos ni automatizaciones del PC.

## Instalar en el VPS

Subí el ZIP, descomprimilo y entrá en la carpeta donde está `install`:

```bash
./install
```

Sin argumentos ni rutas de archivos Nginx. Si tu transferencia perdió el permiso
de ejecución, recuperalo con `chmod +x install`. El ZIP preparado conserva ese
permiso. El script solicita sudo cuando corresponde y abre un menú. Funciona con
Debian 12+, Ubuntu 22.04+ y distribuciones con dnf, Python 3.10+ y systemd. No es
un instalador para Windows ni para contenedores sin systemd.

Elegí **1 · Instalar / actualizar**. El menú solicita IP/dominio (predeterminado
`https://167.86.106.105`), contraseña privada y si querés el receptor de TikTok.
Luego muestra la configuración antes de aplicarla. Genera automáticamente las
claves, elige un puerto libre y prepara paquetes, entorno Python, Nginx y systemd.

React viene compilado y **Node no queda como servicio**. Si falta la compilación,
el instalador descarga un Node LTS oficial, verifica su SHA-256 y compila React.
No instala librerías gráficas, sintetizadores de voz ni procesos del escritorio.

El menú también permite:

- Ver el estado del backend y comprobar HTTPS.
- Reiniciar únicamente Gerstep.
- Cambiar la contraseña y cerrar sesiones administrativas anteriores.
- Exportar las claves para conectar el PC en un archivo privado.
- Activar/desactivar el receptor opcional de TikTok.
- Consultar incidencias y crear una copia consistente de SQLite.

Puede ejecutarse nuevamente desde la carpeta subida o desde la instalación:

```bash
cd /opt/gerstep-interactive
./install
```

El servicio sigue funcionando cuando cerrás SSH o el menú. Los indicadores de
progreso solo se animan en una terminal; `NO_COLOR=1` desactiva el color.

## HTTPS y otras aplicaciones Nginx

La instalación ocupa `/Gerstep/`. Detecta los archivos realmente cargados por
Nginx y selecciona el servidor de la IP/dominio; si hay varios candidatos,
presenta una selección en el menú. Añade su configuración, comprueba `nginx -t`
y recarga Nginx. Guarda los originales en `/var/backups/gerstep-interactive/`.
Ante un error o Ctrl+C restaura las configuraciones modificadas y el código
anterior, sin detener otras aplicaciones ni modificar sus directorios o cuentas
ACME. Solo Gerstep se detiene brevemente durante una actualización. Los paquetes
Python ya instalados permanecen; la copia de seguridad no recrea el entorno venv.

Si el HTTPS existente es válido para la IP, lo reutiliza. Si hace falta emitir
un certificado, pide un email y la aceptación de las condiciones de la CA.
Utiliza Certbot 5.4+ aislado y el desafío HTTP webroot: **el puerto 80 debe ser
accesible desde Internet**. No detiene Nginx para realizar ese desafío ni abre
el firewall del proveedor por su cuenta.

Los certificados IP de Let's Encrypt tienen validez de seis días; para los
certificados gestionados por Gerstep se activa un temporizador que comprueba
renovación cada hora y recarga si cambian los archivos. El HTTPS reutilizado
conserva la renovación externa existente. Certbot no
instala por sí mismo estos certificados en Nginx, por eso esa parte está en el
instalador. [Documentación oficial](https://letsencrypt.org/2026/03/11/shorter-certs-certbot).

Una IP normalmente llega sin SNI. En un HTTPS compartido, el instalador conserva
los certificados de los dominios con mapas basados en SNI y sirve el certificado
IP cuando no hay SNI. Sus copias de claves son accesibles solo por root y el
grupo de Nginx; el temporizador actualiza las copias cuando sus originales se
renuevan. Los clientes antiguos de otros dominios **sin SNI** recibirían el
certificado IP; para conservar también ese caso se requiere otra IP. Nginx debe
soportar certificados variables (1.15.9+); en versiones anteriores a 1.27.4
estos archivos se cargan en cada handshake; en las versiones nuevas el instalador
habilita una caché de ocho entradas. [Referencia oficial de Nginx](https://nginx.org/en/docs/http/ngx_http_ssl_module.html).

Configuraciones TLS con certificados múltiples/heredados/dinámicos o listeners
con direcciones específicas se rechazan si hace falta cambiar su TLS. El menú
informa del impedimento y restaura la configuración; no improvisa cambios sobre
otros sistemas. No desactiva la validación TLS ni sirve certificados autofirmados.

## Acceso privado y conexión al PC

Público: `https://167.86.106.105/Gerstep/`.
Administración: `https://167.86.106.105/Gerstep/login`, sin enlace público.
La contraseña del menú queda como hash PBKDF2, separada de las claves del programa.
Los secretos están en `/etc/gerstep-interactive.env`, con permisos root 0600.

Opción **5 · Exportar conexión** crea `/root/gerstep-pc-connection.json` (0600)
con `url`, `bridge_token` y `admin_api_token`. Transferí ese archivo privadamente
y pegá sus valores en los campos URL, token del programa y clave administrativa
del panel Interactive del PC. No publiques ese archivo. La contraseña humana
del login no es la clave API administrativa del programa.

El PC abre el WebSocket saliente y conserva su TTS, música, director y colas.
La web sigue funcionando si el PC se desconecta; el bot y la reproducción musical
requieren el programa conectado. No se reenvían voces obsoletas al reconectar.

## TikTok opcional

El menú instala TikTokLive solamente si activás el receptor. Es un adaptador
pequeño sin audio y sin importaciones del programa de escritorio. Omite eventos
de la conexión inicial, deduplica IDs y descarta eventos antiguos. Sin marcas
temporales fiables aplica tres segundos de sincronización; eso no garantiza
identificar un historial tardío sin timestamps. Reintenta con backoff y se
suspende cuando conecta el puente del PC para evitar dos fuentes simultáneas.

Los perfiles usan IDs numéricos estables, no apodos. El receptor local mantiene
niveles en la misma base SQLite; un comentario suma experiencia como máximo cada
30 segundos y los regalos multiplican el progreso con un límite por evento.
La web conserva el mayor progreso recibido al alternar fuentes; **no suma dos
historiales solapados**. Fusionar exactamente experiencia de PC y VPS sigue
pendiente. Los tops no recuperan donaciones anteriores ni eventos perdidos.
TikTokLive no es una API oficial de TikTok; la conexión real depende de TikTok,
el LIVE y la red del VPS, y no se verificó en estas pruebas offline.

## Comunidad, moderación y OBS

Los visitantes reciben `Anónimo[n]` y una identidad persistente cuyo token se
guarda en localStorage (hash en el servidor). El apodo es opcional. Cada encuesta
admite un voto web por IP; la misma identidad puede cambiar su opción. Una red
compartida comparte ese único voto; una VPN/red diferente puede eludir este
límite. Las IP se guardan como HMAC, no en claro. TikTok vota con `/encuesta n`,
identificado por ID estable: una sesión web no verifica identidad TikTok.

El administrador aprueba preguntas/propuestas/comandos/enlaces YouTube, controla
encuestas y sortea una **pregunta aprobada** con la ruleta. Esta selección no
reproduce voz automáticamente. Puede ver/exportar votantes, bloquear, suspender
interacciones, vaciar colas y registrar marcas de momentos destacados.
OBS: `/Gerstep/overlay`. No graba ni publica clips automáticamente.
La música usa el reproductor visible autorizado del PC; no descarga audio ni
elude DRM. El foco conserva únicamente una abstracción, sin acciones físicas.

Retención: preguntas 24 h, hasta 200 activas/2000 históricas; encuestas 100 y
24 h después del cierre; 50.000 votos por encuesta; identidades/perfiles/donantes
inactivos 30 días; regalos 50.000/30 días; marcas 500/7 días. El top global es
acumulado para los perfiles conservados. Nginx sobrescribe `X-Real-IP`; si añadís
otro proxy delante, hay que configurar explícitamente sus direcciones confiables.

## Desarrollo independiente

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
cd frontend
npm ci
npm test
npm run build
cd ..
python3 deploy/package.py
```

El paquete se genera en `release/gerstep-interactive.zip`, con `install` en su
raíz. Desarrollo local: completar `.env.example` y cargar sus valores como
variables de entorno; ejecutar `python -m backend.server`. Para HTTP local usar
`GERSTEP_DEVELOPMENT=1` y `GERSTEP_ORIGIN=http://127.0.0.1:9081`.
El backend no carga ni ejecuta archivos `.env` automáticamente.

Pruebas locales verifican HTTP/WebSocket, login, moderación, aislamiento,
preservación de datos, transacciones y configuraciones Nginx representativas.
**No se ha ejecutado el instalador en tu VPS ni emitido un certificado real.**
La configuración concreta de ese servidor se valida al ejecutar el menú.
