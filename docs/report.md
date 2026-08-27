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

### Cómo reproducir la captura

El script [`scripts/capture_session.py`](../scripts/capture_session.py) ejecuta
una sesión MCP fija y ordenada. No se usa el chatbot a propósito: el modelo
decide qué llamar y cuándo, lo que vuelve la captura difícil de leer. Con el
script, cada paquete tiene un lugar conocido en el protocolo.

```powershell
# 1. Levantar el servidor (local, texto plano)
python -m clinic_server.http_server

# 2. En Wireshark: capturar en la interfaz correspondiente con el filtro
#    tcp.port == 8000 && http

# 3. Ejecutar la sesión
python scripts/capture_session.py
```

Contra el servidor desplegado se usa la URL remota:

```powershell
python scripts/capture_session.py https://<servicio>.onrender.com/mcp
```

### Clasificación de los mensajes JSON-RPC 

Esta es la salida real del script contra el servidor.

```
  #  dirección  clase         método                     rol
  1  host->srv  request       initialize                 sincronización (abre la sesión, negocia la versión)
  2  srv->host  response      initialize                 respuesta a initialize
  3  host->srv  notification  notifications/initialized  sincronización (confirma que la sesión está viva)
  4  host->srv  request       tools/list                 solicitud (descubrimiento)
  5  srv->host  response      tools/list                 respuesta a tools/list
  6  host->srv  request       tools/call                 solicitud (invocación)
  7  srv->host  response      tools/call                 respuesta a tools/call
 ... (se repite el par solicitud/respuesta por cada herramienta invocada)
 17  srv->host  response      tools/call                 respuesta a tools/call
```

**Cómo se distinguen las tres clases**, tanto en el código como en Wireshark:

| Clase | Cómo se reconoce en el JSON | Qué se ve en HTTP |
| --- | --- | --- |
| Sincronización | `initialize` con `id`; `notifications/initialized` sin `id` | `POST` que responde `200`; y `POST` que responde `202` sin cuerpo |
| Solicitud | Tiene `method` **y** `id` | `POST /mcp` con el método en el cuerpo |
| Respuesta | Tiene `id` y `result` (o `error`), sin `method` | Cuerpo del `200` que corresponde a ese `POST` |

La distinción está implementada en `mcp_host/jsonrpc.py`, en la función
`classify()`: si el mensaje trae `method` es solicitud cuando tiene `id` y
notificación cuando no; si no trae `method`, es respuesta, y es error cuando
lleva el miembro `error`. La misma función alimenta el log del chatbot y la
tabla de arriba.

El detalle importante para la captura: **la notificación es el único mensaje sin
respuesta**. En el enmarcado HTTP eso se ve como el único `POST` que devuelve
`202` con `Content-Length: 0`, mientras que todos los demás devuelven `200` con
cuerpo. Es la evidencia visual más limpia de que JSON-RPC distingue entre
solicitudes y notificaciones.

### Qué ocurre en cada capa 

*Esta sección se completa con los valores de tu captura; la estructura y lo que
hay que buscar en cada capa es lo que sigue.*

**Capa de enlace (Ethernet / IEEE 802.11).** Cada paquete viaja dentro de una
trama con MAC de origen y destino. Si la captura es contra `127.0.0.1`, no hay
trama real: Windows usa la interfaz de bucle invertido (Npcap "Adapter for
loopback traffic") y Wireshark muestra un encabezado nulo, porque el paquete
nunca sale de la máquina. Contra el servidor remoto sí hay trama: la MAC de
destino **no** es la del servidor en Render, sino la del router de salida, ya
que la dirección de enlace solo tiene alcance dentro del segmento local. El MTU
típico de 1500 bytes es lo que obliga a fragmentar las respuestas grandes, como
la de `tools/list`.

**Capa de red (IP).** Direcciones IP de origen y destino, y el campo TTL. Contra
el servidor local ambas son `127.0.0.1`. Contra Render, el destino es la IP
pública que resuelve el DNS de `onrender.com` — conviene notar que Render está
detrás de un balanceador, así que la IP que se ve no es la del contenedor. El
TTL decreciente evidencia los saltos intermedios. Aquí no hay noción de
"sesión": IP solo entrega paquetes sueltos.

**Capa de transporte (TCP).** Es donde aparece la sesión. La captura debe
mostrar el saludo de tres vías (`SYN`, `SYN-ACK`, `ACK`) **una sola vez**,
aunque la sesión MCP intercambie 17 mensajes: el servidor usa HTTP/1.1 con
`keep-alive`, así que todos los mensajes viajan sobre la misma conexión TCP. Eso
se comprueba viendo que el puerto efímero de origen no cambia entre un `POST` y
el siguiente. Se observan además los `ACK` de cada segmento, la ventana de
recepción, y al final el cierre con `FIN`/`ACK`. El puerto de destino identifica
el servicio: 8000 en local, 443 en Render.

**Capa de aplicación (HTTP + JSON-RPC).** Dos protocolos apilados, y conviene
nombrarlos por separado porque es la idea central del proyecto:

- *HTTP* aporta el enmarcado: método `POST`, ruta `/mcp`, `Content-Type:
  application/json`, `Content-Length`, y el código de estado.
- *JSON-RPC 2.0* es el contenido: `jsonrpc`, `id`, `method`, `params`, `result`.
- *MCP* no es un protocolo de red aparte; es el vocabulario de métodos
  (`initialize`, `tools/list`, `tools/call`) acordado sobre JSON-RPC.

En la captura local, `Follow > HTTP Stream` muestra el JSON completo en texto
plano. Contra Render el tráfico va sobre TLS: se verá el handshake
(`Client Hello`, `Server Hello`, certificado) y luego `Application Data`
cifrado. Para leer el JSON hay que descifrarlo, definiendo la variable de
entorno `SSLKEYLOGFILE` antes de correr el script y apuntando Wireshark a ese
archivo en *Preferences > Protocols > TLS > (Pre)-Master-Secret log filename*.

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
