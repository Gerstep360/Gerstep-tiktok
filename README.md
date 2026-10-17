# Gerstep Interactive

Repositorio independiente del programa Windows: React/Vite, Python/aiohttp,
SQLite y herramientas de despliegue. Se puede copiar **solamente esta carpeta**
o clonar este repositorio. No necesita el repositorio TikTok padre, Tkinter, pygame,
TTS, sonidos ni automatizaciones del PC.

## Instalar en el VPS

Cloná el repositorio independiente y ejecutá el menú:

```bash
git clone https://github.com/Gerstep360/Gerstep-tiktok.git
cd Gerstep-tiktok
./install
```

Sin argumentos ni rutas de archivos Nginx. Si tu transferencia perdió el permiso
de ejecución, recuperalo con `chmod +x install` o usá `bash ./install`.
El script solicita sudo cuando corresponde y abre un menú. Funciona con
Debian 12+, Ubuntu 22.04+ y distribuciones con dnf, Python 3.10+ y systemd. No es
un instalador para Windows ni para contenedores sin systemd.

Elegí **1 · Instalar / actualizar**. El menú solicita IP/dominio (predeterminado
`https://167.86.106.105`), contraseña privada y si querés el receptor de TikTok.
Luego muestra la configuración antes de aplicarla. Genera automáticamente las
claves, elige un puerto libre y prepara paquetes, entorno Python, Nginx y systemd.
La contraseña requiere **de 12 a 256 caracteres**; no aparece mientras la escribís.

Si tu menú todavía es una versión antigua que no actualiza Git, recibí esta
versión una vez con:

```bash
cd ~/app/Gerstep-tiktok
git fetch origin
git reset --hard origin/main
./install
```

Elegí la opción 1. El menú hace **`git fetch` y `git reset --hard` a `origin/main`**
automáticamente y reinicia su proceso para instalar el código recién descargado.
Esto sobrescribe las modificaciones locales versionadas del repositorio fuente.
Si falla el fetch, no ejecuta el reset ni detiene Gerstep. No hace `git clean`.
Se conserva la configuración de una instalación anterior.
Después basta con ejecutar `./install` y elegir la opción 1 para actualizar.
El servicio mantiene SQLite en `/opt/gerstep-interactive/data` y sus claves en
`/etc/gerstep-interactive.env`, fuera de la copia Git.

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

Puede ejecutarse nuevamente desde la copia Git o desde la instalación:

```bash
cd /opt/gerstep-interactive
./install
```

El instalador guarda la ruta de la copia Git para que también el menú de `/opt`
actualice desde allí. Esa carpeta debe seguir existiendo y estar fuera de `/opt/gerstep-interactive`.
Una instalación antigua sin esa ruta registrada debe actualizarse primero desde
la copia clonada. Si no hay copia Git, el menú informa que usará el código disponible.

El servicio sigue funcionando cuando cerrás SSH o el menú. Los indicadores de
progreso solo se animan en una terminal; `NO_COLOR=1` desactiva el color.

## HTTPS y otras aplicaciones Nginx

La instalación ocupa `/Gerstep/`. Detecta los archivos realmente cargados por
Nginx y selecciona el servidor de la IP/dominio; si hay varios candidatos,
presenta una selección en el menú. Añade su configuración, comprueba `nginx -t`
y recarga Nginx. Guarda los originales en `/var/backups/gerstep-interactive/`.
Las reglas `return`, `rewrite` o `if` del servidor se omiten únicamente para
`/Gerstep` y `/Gerstep/…`, para que un 404 o una redirección anterior no impidan
alcanzar el proxy. Las demás rutas conservan esas reglas. Esto también se repara
al actualizar una instalación que ya contiene el include de Gerstep.
Nginx ejecuta esas reglas antes de buscar el `location`;
[referencia oficial](https://nginx.org/en/docs/http/ngx_http_rewrite_module.html).
Si la comprobación pública falla, el menú identifica la URL y el estado HTTP;
no acepta una página HTML ni una redirección como prueba de funcionamiento.
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

Desde **login → Control → Descargar conexión para el PC** obtenés
`gerstep-pc-connection.json`. La descarga exige autenticación administrativa,
está limitada a tres por minuto y no se guarda en caché. La página pública
y la clave del puente no dan acceso al archivo.
En el programa Windows elegí **Interactive → Importar conexión VPS**:
carga la URL y ambas claves y conecta el puente sin copiarlas a mano.
Las claves quedan solamente en la sesión del PC. El panel Control muestra
por separado web activa, PC conectado y TikTok conectado en el PC.

También podés usar **5 · Exportar conexión** del instalador: crea
`/root/gerstep-pc-connection.json` (0600) con los mismos campos `url`,
`bridge_token` y `admin_api_token`. Transferilo privadamente e importalo.
No publiques ese archivo. La contraseña del login es independiente de las claves API.

El PC abre el WebSocket saliente y conserva su TTS, música, director y colas.
La web sigue funcionando si el PC se desconecta; el bot y la reproducción musical
requieren el programa conectado. No se reenvían voces obsoletas al reconectar.

## IA privada y sonidos del PC

La opción **9 · Configurar NVIDIA (IA privada)** de `./install` solicita la clave
sin mostrarla, la guarda en `/etc/gerstep-interactive.env` con permisos root
**0600** y reinicia únicamente Gerstep. Dejar la clave vacía conserva la actual.
Las pruebas del VPS tienen inicialmente un límite operativo de seis solicitudes
por minuto; ese valor no representa una cuota garantizada por NVIDIA.

Entrá por `/Gerstep/login` y abrí la pestaña **IA** del administrador. Su chat
usa `GET`/`POST /Gerstep/api/admin/ai`, exige autenticación administrativa y no
está disponible para visitantes, sesiones de espectadores ni la clave del puente.
Los comandos locales no consumen NVIDIA. Por defecto la prueba sólo muestra texto.
La casilla **Enviar voz y sonidos autorizados al programa** permite al administrador
enviar esa respuesta al PC conectado por el WebSocket existente, incluso sin
TikTok. Requiere el PC disponible, las interacciones habilitadas y ninguna parada
total. La respuesta inicial encolada no confirma que ya se haya escuchado: el PC
confirma selección, reproducción o error. Las entregas caducan y no se conservan
para otra sesión.

`ai_common` contiene cliente, cuotas, enrutamiento y contexto compartidos, sin
depender de TikTok, Tkinter, TTS ni módulos del escritorio. Carga la **skill Gerstep
V2 completa** y referencias originales seleccionadas por intención; no carga el
prompt mini ni exportaciones de conversaciones privadas. Los recursos ya están
incluidos en este repositorio independiente. El contexto inicial es de 16.000
tokens y el presupuesto operativo de 60.000 tokens/minuto. Las pruebas recientes
consumieron aproximadamente 8.600–9.700 tokens reales de entrada por solicitud:
la personalidad completa tiene un coste mayor y el presupuesto de tokens puede
agotarse antes que las seis solicitudes/minuto. No son cuotas garantizadas del
proveedor. Las variables `GERSTEP_AI_*` pueden ajustarse en el entorno privado;
los cambios requieren reiniciar Gerstep.

En turnos de voz elegibles, NVIDIA puede proponer una herramienta nativa
`queue_sound` dentro de la misma generación. Sólo admite IDs del catálogo fijo.
El backend valida la propuesta y el PC conserva autorización final por intención,
cooldown y estado. La IA no recibe claves del puente, no elige endpoints ni ejecuta
texto arbitrario. Puede no proponer ningún sonido; no se hace una segunda llamada
de IA únicamente para seleccionar el efecto.

Los efectos autorizados se transportan por dos endpoints privados:

- `POST /Gerstep/api/bridge/ai/actions`: clave Bearer exclusiva del programa.
- `POST /Gerstep/api/admin/ai/effect`: acción explícita del administrador, con
  sesión administrativa y origen web válido.

Sólo aceptan los IDs `laugh`, `baby_laugh`, `shock`, `fail`, `high_fail` y `meme`
que el PC anuncie como disponibles y habilitados; nunca rutas, scripts ni texto
generado como instrucciones ejecutables. El POST regresa por el WebSocket
existente como `ai_effect`, correlacionado mediante `action_id` y `turn_id`
opcional. El PC coordina el sonido con la voz de ese turno. Hay deduplicación,
cooldown compartido, cola limitada y cinco segundos de vigencia de transporte.
Si el PC está desconectado, en emergencia o sin efectos habilitados, se rechaza
la acción: no se almacena para reproducirla en otra sesión.

El envío administrativo de voz usa el mismo `POST /Gerstep/api/admin/ai` con
`send_to_live=true`. Después de la generación validada entrega `ai_response` por
el WebSocket, con diez segundos de vigencia para entrar al pipeline del PC. El
programa reutiliza su TTS y cola secuencial: primero voz, después efecto permitido,
después siguiente voz. El VPS no instala ni reproduce sonidos. La prueba privada
sin esa opción no activa reproducción.

Se verificaron herramientas nativas con NVIDIA y transporte HTTP/WebSocket local
con servicios de audio simulados. La prueba nativa forzó `queue_sound` sólo para
verificar el protocolo; producción usa selección automática opcional. Esto no
certifica audio acústico ni conexión con tu VPS de producción. La instalación
real requiere ejecutar el menú en tu servidor y actualizar también el PC.

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
La configuración principal (`backend.config.Config`) lee sólo variables del
entorno del proceso. Como excepción, `ai_common.config.AIConfig` puede leer el
`.env` local para la IA mediante un parser literal: no ejecuta ni interpola su
contenido, y las variables del proceso tienen prioridad. En producción systemd
carga el archivo privado `/etc/gerstep-interactive.env`.

Pruebas locales verifican HTTP/WebSocket, login, moderación, aislamiento,
preservación de datos, transacciones y configuraciones Nginx representativas.
La regresión del arranque sin encuesta/voto se verifica en un navegador Chromium
real con el probe opcional `tests/browser_probe.py`: configurar `BROWSER_BINARY`
con la ruta del ejecutable de Chrome/Edge y ejecutar ese archivo con Python.
Usa un perfil temporal, una base en memoria y loopback. También prueba votar,
recargar, cambiar/cerrar encuestas y ausencia de desbordamiento horizontal en
1280×800 y 390×844. No necesita Playwright ni dependencias nuevas de producción.
**No se ha ejecutado el instalador en tu VPS ni emitido un certificado real.**
La configuración concreta de ese servidor se valida al ejecutar el menú.
