# Reporte — Proyecto 1, Uso de un protocolo existente

CC3067 Redes · Universidad del Valle de Guatemala

La especificación completa del servidor propio vive en [clinic-server.md](clinic-server.md); aquí se resume y se agrega el análisis de red.

---

## 1. Especificación de los servidores MCP desarrollados

### Servidor de la clínica

Un mismo servidor, dos transportes. La lógica no cambia entre uno y otro: solo
cambia cómo se enmarca cada mensaje.

| | stdio | HTTP |
| --- | --- | --- |
| Cómo se ejecuta | `python -m clinic_server` | `python -m clinic_server.http_server` |
| Quién lo lanza | El anfitrión, como subproceso | Render, como servicio web |
| Enmarcado | Un mensaje JSON por línea | Un mensaje JSON por cuerpo HTTP |
| Canal | `stdin` / `stdout` | `POST /mcp` |

**Datos del servidor**

| Campo | Valor |
| --- | --- |
| Nombre | `clinic-mcp-server` |
| Versión | `1.0.0` |
| Versión de protocolo | `2025-06-18` |
| Capacidades | `{"tools": {"listChanged": false}}` |

**Endpoints HTTP**

| Método | Ruta | Propósito |
| --- | --- | --- |
| `POST` | `/mcp` | Transporta un mensaje JSON-RPC en el cuerpo |
| `GET` | `/health` | Verificación de estado, devuelve la identidad del servidor |
| `GET` | `/` | Igual que `/health` |

Los códigos de estado se eligieron para que correspondan a las clases de
mensaje JSON-RPC, y por eso son legibles directamente en la captura:

| Código | Significado |
| --- | --- |
| `200` | Se respondió una solicitud; el cuerpo es la respuesta JSON-RPC |
| `202` | Se aceptó una notificación; no hay cuerpo, porque no se espera respuesta |
| `400` | El cuerpo no era JSON-RPC válido; se devuelve el error `-32700` |
| `404` | Ruta desconocida |

**Métodos del protocolo**

| Método | Tipo | Propósito |
| --- | --- | --- |
| `initialize` | solicitud → respuesta | Negocia versión y capacidades |
| `notifications/initialized` | notificación | Confirma que la sesión está viva |
| `tools/list` | solicitud → respuesta | Devuelve las seis herramientas y sus esquemas |
| `tools/call` | solicitud → respuesta | Ejecuta una herramienta |
| `ping` | solicitud → respuesta | Prueba de vida, devuelve `{}` |
| cualquier otro | solicitud → error | Error JSON-RPC `-32601` |

**Herramientas y parámetros**

| Herramienta | Parámetros obligatorios | Opcionales |
| --- | --- | --- |
| `list_specialties` | — | — |
| `find_doctors` | — | `specialty`, `name` |
| `get_availability` | `doctor_id`, `date` | — |
| `book_appointment` | `doctor_id`, `date`, `time`, `patient_name` | `reason` |
| `get_appointment` | `code` | — |
| `cancel_appointment` | `code` | — |

Los valores de retorno, los errores y ejemplos de JSON-RPC crudo están en
[clinic-server.md](clinic-server.md).

---

## 2. Análisis de la comunicación con Wireshark

Se hicieron dos capturas de la misma sesión MCP, porque cada una muestra algo
que la otra no puede:

| | Captura local | Captura remota |
| --- | --- | --- |
| Archivo | `captura-local-mcp.pcapng` | `captura-remota.pcapng` |
| Servidor | `127.0.0.1:8000` | `clinic-mcp-server.onrender.com:443` |
| Interfaz | Adapter for loopback traffic capture | Wi-Fi |
| Cifrado | Ninguno, el JSON se lee directo | TLS 1.3, descifrado con `SSLKEYLOGFILE` |
| Tramas totales | 133 (filtradas de 921) | 730 |
| Qué aporta | El JSON-RPC en texto plano | La ruta de red real: MAC, IP pública, TTL |

### Cómo se reprodujo

El script [`scripts/capture_session.py`](../scripts/capture_session.py) ejecuta
una sesión MCP fija y ordenada. No se usa el chatbot a propósito: el modelo
decide qué llamar y cuándo, lo que vuelve la captura difícil de leer. Con el
script, cada paquete tiene un lugar conocido en el protocolo.

```powershell
# Local
python -m clinic_server.http_server        # filtro: tcp port 8000
python scripts/capture_session.py

# Remota
$env:SSLKEYLOGFILE="...\tls-keys.log"      # filtro: host 216.24.57.7 and tcp port 443
python scripts/capture_session.py https://clinic-mcp-server.onrender.com/mcp
```

Para leer el tráfico remoto hay que definir `SSLKEYLOGFILE` **antes** de correr
el script: Python escribe ahí las llaves de sesión TLS, y Wireshark las usa en
*Edit → Preferences → Protocols → TLS → (Pre)-Master-Secret log filename*. Sin
ese paso, los paquetes aparecen como `Application Data` ilegible.

### Clasificación de los mensajes JSON-RPC

Esta es la correspondencia real entre paquetes de la captura remota y mensajes
del protocolo. La columna *trama* es el número de paquete en Wireshark.

| Trama | t (s) | Dirección | Puerto origen | Bytes | HTTP | Mensaje | Clase |
| ---: | ---: | --- | ---: | ---: | ---: | --- | --- |
| 165 | 14.10 | host → srv | 60649 | 239 | — | `initialize` | **sincronización** |
| 171 | 14.47 | srv → host | 443 | 81 | 200 | resultado `id=1` | respuesta |
| 185 | 14.66 | host → srv | 60650 | 130 | — | `notifications/initialized` | **sincronización** |
| 187 | 14.86 | srv → host | 443 | 847 | 202 | *(sin cuerpo)* | acuse, no respuesta |
| 202 | 15.04 | host → srv | 60651 | 134 | — | `tools/list` | solicitud |
| 208 | 15.25 | srv → host | 443 | 1289 | 200 | resultado `id=2` | respuesta |
| 222 | 15.38 | host → srv | 60652 | 194 | — | `tools/call` (`find_doctors`) | solicitud |
| 228 | 15.82 | srv → host | 443 | 105 | 200 | resultado `id=3` | respuesta |
| 241 | 15.95 | host → srv | 60653 | 215 | — | `tools/call` (`get_availability`) | solicitud |
| 245 | 16.20 | srv → host | 443 | 81 | 200 | resultado `id=4` | respuesta |
| 261 | 16.32 | host → srv | 60654 | 296 | — | `tools/call` (`book_appointment`) | solicitud |
| 264 | 16.51 | srv → host | 443 | 105 | 200 | resultado `id=5` | respuesta |
| 280 | 16.63 | host → srv | 60655 | 192 | — | `tools/call` (`get_appointment`) | solicitud |
| 291 | 16.82 | srv → host | 443 | 81 | 200 | resultado `id=6` | respuesta |
| 309 | 16.97 | host → srv | 60656 | 195 | — | `tools/call` (`cancel_appointment`) | solicitud |
| 317 | 17.15 | srv → host | 443 | 81 | 200 | resultado `id=7` | respuesta |
| 350 | 17.35 | host → srv | 60657 | 198 | — | `tools/call` (código inexistente) | solicitud |
| 356 | 17.53 | srv → host | 443 | 81 | 200 | resultado `id=8`, `isError` | respuesta |

**Las tres clases y cómo se reconocen**

| Clase | En el JSON | En la captura |
| --- | --- | --- |
| Sincronización | `initialize` (con `id`) y `notifications/initialized` (sin `id`) | Las dos primeras peticiones; la segunda es la única que recibe `202` |
| Solicitud | Tiene `method` **y** `id` | `POST /mcp` cuyo cuerpo lleva el nombre del método |
| Respuesta | Tiene `id` y `result` o `error`, sin `method` | Cuerpo del `200` que corresponde a ese `POST` |

La distinción está implementada en `mcp_host/jsonrpc.py`, en la función
`classify()`: si el mensaje trae `method`, es solicitud cuando tiene `id` y
notificación cuando no; si no trae `method`, es respuesta, y es error cuando
lleva el miembro `error`. La misma función alimenta el log del chatbot y la
tabla de arriba.

**La evidencia más limpia está en la trama 185.** Es el único mensaje sin
respuesta en toda la sesión, y el servidor contesta `202 Accepted` con
`Content-Length: 0`. Todos los demás reciben `200` con cuerpo. Ahí se ve, a
nivel de red, la diferencia que JSON-RPC hace entre una notificación y una
solicitud: la notificación no lleva `id`, así que no hay a qué responder.

Verificado en texto plano en la captura local, donde el cuerpo se lee sin
descifrar:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{...}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

### Qué ocurre en cada capa

**Capa de enlace (Ethernet / IEEE 802.11).** En la captura remota cada paquete
viaja en una trama Ethernet con la MAC de la computadora,
`a8:e2:91:e0:1e:8e`, y la del router, `18:34:af:86:fe:8e`. Vale la pena notar
que **la MAC de destino no es la del servidor en Render**: la dirección de
enlace solo tiene alcance dentro del segmento local, así que el destino es
siempre la puerta de enlace. Los tamaños de trama van de 54 bytes (un `ACK`
puro) a 1514, que es exactamente el MTU de 1500 más los 14 bytes de cabecera
Ethernet.

En la captura local no hay trama real: Wireshark reporta el tipo de enlace como
`null` porque el tráfico usa la interfaz de bucle invertido y nunca sale de la
máquina. Es una diferencia útil de señalar: la capa de enlace solo existe cuando
hay un medio físico que atravesar.

**Capa de red (IP).** La computadora usa la dirección privada `192.168.1.50` y
el servidor la pública `216.24.57.7`. El DNS de `clinic-mcp-server.onrender.com`
devuelve dos direcciones (`216.24.57.7` y `216.24.57.15`) porque Render
distribuye la carga; la sesión se estableció con la primera. El TTL delata la
distancia: los paquetes salientes llevan 128, el valor inicial de Windows,
mientras que los que regresan llegan con 53 y 57, es decir que atravesaron
alrededor de una decena de saltos. En la captura local ambas direcciones son
`127.0.0.1` y el TTL no se decrementa, porque no hay routers de por medio.

**Capa de transporte (TCP).** Aquí apareció el hallazgo más interesante, y
contradice lo que esperábamos. La sesión MCP intercambia 17 mensajes, y la
suposición razonable era que viajaran todos sobre una sola conexión TCP, ya que
el servidor habla HTTP/1.1 con `keep-alive`. **La captura demuestra lo
contrario: hay 9 paquetes `SYN`, es decir 9 conexiones TCP distintas**, una por
cada mensaje que espera respuesta. Se comprueba en el puerto efímero de origen,
que cambia en cada petición: 60649, 60650, 60651… hasta 60657. La captura local
muestra el mismo patrón con los puertos 63799 a 63807.

La causa está en el cliente, no en el servidor: `HttpTransport` usa
`urllib.request`, que no mantiene un pool de conexiones y envía
`Connection: close` en cada petición. El servidor ofrece reutilizar la conexión
y el cliente decide no hacerlo. Es un buen recordatorio de que `keep-alive` es
una negociación entre dos partes, y basta con que una la rechace para que no
ocurra.

Cada conexión negocia MSS de 1460 bytes y ventana inicial de 65535. El cierre
también es consistente con esa lectura: los 9 `FIN` los envía **el servidor**
`216.24.57.7`, no el cliente, porque es el cliente quien pidió `Connection:
close` y el servidor obedece cerrando en cuanto termina de responder. La
computadora contesta con 9 `RST`, que es como la pila de Windows finaliza un
socket ya cerrado en lugar de completar el apagado ordenado. El puerto de
destino identifica el servicio: 443 en Render, 8000 en local.

**Capa de aplicación (TLS + HTTP + JSON-RPC).** Sobre la conexión remota hay
tres protocolos apilados, y conviene nombrarlos por separado porque es la idea
central del proyecto:

- *TLS 1.3* cifra el canal. En el `Client Hello` se ve la extensión SNI con el
  nombre `clinic-mcp-server.onrender.com`, que es lo que permite a Render saber
  qué certificado presentar antes de que exista el túnel. La suite negociada es
  `0x1302`, es decir `TLS_AES_256_GCM_SHA384`.
- *HTTP/1.1* aporta el enmarcado: `POST /mcp`, `Content-Type: application/json`,
  `Content-Length`, y el código de estado que distingue respuesta de acuse.
- *JSON-RPC 2.0* es el contenido: `jsonrpc`, `id`, `method`, `params`, `result`.
- *MCP* no es un protocolo de red aparte. Es el vocabulario de métodos
  (`initialize`, `tools/list`, `tools/call`) acordado sobre JSON-RPC. En la
  captura no hay nada que diga "MCP": lo que se ve son mensajes JSON-RPC cuyos
  nombres de método pertenecen a ese vocabulario.

El tamaño de las respuestas cuenta su propia historia. La de `tools/list` ocupa
1289 bytes porque lleva los esquemas JSON de las seis herramientas, mientras que
la mayoría de las respuestas a `tools/call` caben en 81 bytes. Es el precio del
descubrimiento: se paga una vez al abrir la sesión y ya no se vuelve a pagar.

La sesión completa, desde el `initialize` hasta la última respuesta, tomó
**3.4 segundos** contra el servidor en Render. Contra el servidor local, los
mismos 17 mensajes tomaron **56 milisegundos**. Casi toda esa diferencia es
latencia de red y establecimiento de TLS, no procesamiento: el servidor hace
exactamente el mismo trabajo en ambos casos.

---

## 3. Conclusiones y comentarios (punto 10)

**MCP es más simple de lo que aparenta, y esa es su virtud.** Todo el protocolo
se sostiene sobre tres intercambios: un `initialize` que negocia versión y
capacidades, una notificación que confirma la sesión, y luego `tools/list` y
`tools/call`. Implementarlo a mano dejó claro que el valor no está en la
complejidad técnica sino en el acuerdo: cualquier servidor que hable ese
vocabulario funciona con cualquier anfitrión, sin adaptadores.

**La separación entre protocolo y transporte es lo que más se nota al
programarlo.** El servidor de la clínica corre sobre stdio y sobre HTTP sin que
cambie una sola línea de su lógica: lo único distinto es quién entrega los
bytes. Esa misma separación permitió que el cliente HTTP reutilizara íntegro el
código de sesión escrito para stdio.

**Un fallo de herramienta no es un fallo de protocolo.** Distinguir entre
`isError: true` en una respuesta exitosa y un error JSON-RPC `-32601` parecía un
detalle al principio, y resultó ser lo que permite que el modelo se corrija
solo: si el horario está ocupado, lee el mensaje y ofrece otro, en lugar de
romper la conversación.

**Cambiar de proveedor de LLM costó un módulo.** El proyecto empezó con la API
de Anthropic y terminó con Gemini. Como la capa MCP nunca supo qué modelo había
del otro lado, el cambio se limitó a `chat_engine.py`. Lo que sí costó trabajo
fue traducir los esquemas: los servidores MCP publican JSON Schema completo y
Gemini acepta apenas un subconjunto de OpenAPI, así que hubo que filtrar
palabras clave y colapsar `anyOf` en `nullable`.

**Dificultades encontradas.** El servidor Git oficial no expone `git_init` en
ninguna versión publicada, lo que obliga a crear el repositorio fuera de MCP.
Los servidores oficiales publican esquemas que un proveedor de LLM puede
rechazar, algo que no aparece en ningún tutorial. Y en Windows hubo dos
tropiezos de entorno: `npx` se instala como `npx.cmd` y `CreateProcess` no lo
encuentra sin la extensión, y la consola usa una página de códigos heredada que
convierte los acentos en basura si no se fuerza UTF-8.

**Lo que se aprendió sobre redes.** El proyecto vuelve tangible algo que suele
quedar abstracto: una "sesión" de aplicación no tiene nada que ver con una
conexión de transporte. Diecisiete mensajes MCP viajan sobre una sola conexión
TCP; la sesión la define el protocolo de aplicación, no el socket. Y al pasar de
stdio a HTTP se ve que el mismo diálogo puede transportarse por un pipe entre
procesos o por una red, sin que el protocolo se entere.
