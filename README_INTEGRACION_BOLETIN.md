# Integración del Monitor del Boletín Oficial — Portal CyT ERSeP

## 1. Alcance

Esta versión incorpora al portal web de Costos y Tarifas una nueva herramienta denominada **Boletín Oficial**. El módulo migra exclusivamente la lógica de monitoreo documental del archivo `.pyw`; no contiene ni reutiliza componentes Tkinter.

La herramienta permite:

- recorrer el archivo anual del Boletín Oficial de Córdoba, mes por mes;
- analizar los PDF de la Primera Sección;
- identificar resoluciones generales del ERSeP;
- extraer prestadora, texto completo y bloque `RESUELVE`;
- detectar aprobaciones tarifarias, rectificaciones, rechazos, prórrogas y convocatorias a audiencia pública;
- aplicar alertas por cooperativa o prestadora;
- guardar caché de PDF y evitar reprocesamientos;
- comparar cada resolución con el historial mediante SHA-256;
- clasificar cada detección como `NUEVO`, `MODIFICADO` o `SIN CAMBIOS`;
- exportar resultados en Excel, CSV, JSON o TXT preparado para analizar con un chat o LLM.

## 2. Seguridad y archivos privados

El ZIP entregado **no incluye**:

- `.env.local`;
- `secrets/google-service-account.json`;
- valores de `APP_PASSWORD`, `JWT_SECRET` o credenciales de Google.

Antes de iniciar esta versión, copiá esos dos archivos privados desde tu proyecto anterior, manteniendo la misma estructura:

```text
Proyecto_CyT_Portal_Corregido_Fechas_V4_BOLETIN/
├── .env.local
└── secrets/
    └── google-service-account.json
```

No copies las credenciales dentro de `static`, ni las pegues en JavaScript.

## 3. Cómo arrancar

### Opción recomendada

1. Descomprimí el ZIP.
2. Copiá `.env.local` y la credencial privada desde el proyecto anterior.
3. Ejecutá `PROBAR_AQUI.bat
- `INICIAR_UVICORN.ps1`: auxiliar de arranque robusto para PowerShell.`.
4. El script:
   - localiza Python;
   - crea o reutiliza `.venv`;
   - instala dependencias faltantes;
   - compila todos los `.py`;
   - verifica JavaScript si Node.js está disponible;
   - ejecuta las pruebas del Boletín;
   - importa `main.py`;
   - inicia Uvicorn en `http://127.0.0.1:8000`;
   - mantiene abierta la ventana si ocurre un error.

El detalle técnico queda en `arranque_portal.log`.

### Arranque manual

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

## 4. Cómo ingresar

Ingresá en:

```text
http://127.0.0.1:8000
```

Usá la contraseña definida en `APP_PASSWORD` dentro de `.env.local`. El mecanismo de autenticación no cambió: el frontend continúa almacenando el JWT en `localStorage` bajo la clave `cyt-token`.

## 5. Cómo usar el monitoreo

1. Desde el menú principal, abrí **Boletín Oficial**.
2. En la pestaña **Monitoreo**, elegí el año.
3. Los términos tarifarios se muestran como campos de solo lectura. Por defecto se incluyen:
   - tarifaria;
   - cuadro tarifario;
   - incremento;
   - aumento;
   - cargo tarifario;
   - audiencia pública.
4. Opcionalmente activá:
   - **Procesar todos**: vuelve a descargar documentos ya vistos, procesa todas las resoluciones ERSeP y muestra también los registros sin cambios;
   - **Incluir todas las resoluciones ERSeP**: no exige coincidencia con una alerta activa;
   - **Mostrar también registros sin cambios**.
5. Presioná **Iniciar monitoreo de alertas**.
6. El frontend consulta el progreso sin mantener bloqueada la solicitud inicial.
7. Las tarjetas muestran **Fecha del Boletín**, resolución, expediente, prestadora, estado, novedad, alertas, términos y el primer párrafo como vista previa. Si no se detecta el expediente aparece **Expediente no identificado**.
8. Desde **Ver detalle** se puede:
   - abrir el PDF oficial;
   - descargarlo mediante el backend autenticado;
   - copiar expediente, resolución, Fecha del Boletín, enlace y prestadora;
   - copiar la resolución completa;
   - copiar únicamente el bloque `RESUELVE`;
   - extraer nuevamente el documento completo y detectar anexos;
   - obtener conjuntamente los metadatos, términos tarifarios y texto de anexos.
9. Para procesar las novedades con una IA sin API:
   - usá **Guardar TXT para IA**; o
   - usá **Copiar TXT completo** y pegalo en el chat elegido.

El botón **Detener** solicita una interrupción segura. Todo lo procesado hasta ese momento permanece registrado.

## 6. Alertas

La pestaña **Alertas** permite crear, editar, pausar, reactivar o eliminar alertas.

Cada alerta contiene:

- un alias visible;
- una o más palabras o frases exactas; en la interfaz cada alternativa se une con la palabra **O**;
- estado activo o pausado.

El botón **+ Añadir término** agrega alternativas sin obligar al usuario a escribir separadores técnicos. Internamente se conserva `|` como separador seguro. Si se vuelve a cargar un alias existente, se actualiza el mismo registro y se incrementa su versión; no se crea un duplicado.

El botón **Importar alertas** admite `.xlsx` y `.csv`. La plantilla usa exactamente dos columnas:

- `ALIAS`;
- `PALABRAS CLAVES`.

Dentro de `PALABRAS CLAVES`, las alternativas se separan con `|`. Antes de confirmar se informan filas válidas, incompletas, posiblemente duplicadas y la cantidad total que se incorporará. Al finalizar se muestran las cantidades creadas, actualizadas y rechazadas.

Cuando la base está vacía se crean automáticamente:

- Aguas Cordobesas S.A.;
- COOPI;
- Cooperativa de Trabajo Sudeste Ltda.

Conviene usar frases suficientemente específicas. Por ejemplo:

```text
Aguas de Capilla del Monte | Cooperativa de Aguas de Capilla del Monte
```

El motor descarta expresiones excesivamente genéricas como `cooperativa`, `limitada` o `servicios públicos`, evitando falsos positivos masivos.

## 7. Historial y SQLite

La base se crea automáticamente en:

```text
datos_boletin_ersep/boletin_ersep.sqlite3
```

Contiene:

- alertas;
- versiones de alertas;
- ejecuciones y progreso;
- publicaciones;
- cambios detectados;
- caché de PDF;
- resultados por ejecución;
- errores individuales.

La pestaña **Historial** permite filtrar por año, estado, prestadora, alerta, expediente y texto, abrir el detalle, copiar los datos y exportar JSON o Excel.

La vista previa nunca reemplaza el documento. Ante cualquier diferencia, prevalece siempre el PDF oficial completo.

### Respaldo

Con el servidor detenido, copiá:

```text
datos_boletin_ersep/boletin_ersep.sqlite3
```

Si existen archivos auxiliares `-wal` o `-shm`, copialos junto con la base o detené correctamente Uvicorn antes de respaldar.

### Restauración

1. Cerrá el portal.
2. Reemplazá `boletin_ersep.sqlite3` por la copia respaldada.
3. Volvé a iniciar `PROBAR_AQUI.bat`.

## 8. Arquitectura

```text
app/
├── boletin_models.py       # modelos Pydantic y validaciones
├── boletin_repository.py   # SQLite, delta, caché, historial y alertas
├── boletin_service.py      # scraping, PDF, regex, estados y trabajos en hilo
└── boletin_routes.py       # endpoints FastAPI y exportaciones

static/
├── boletin.html
├── boletin.css
└── boletin.js
```

`main.py` solamente registra el router:

```python
app.include_router(create_boletin_router(require_auth, BASE_DIR, HTTP_TIMEOUT))
```

## 9. Endpoints disponibles

Todos requieren el mismo JWT del portal:

```text
GET    /api/boletin/health
GET    /api/boletin/alertas
POST   /api/boletin/alertas
PUT    /api/boletin/alertas/{alerta_id}
PATCH  /api/boletin/alertas/{alerta_id}/estado
DELETE /api/boletin/alertas/{alerta_id}
GET    /api/boletin/alertas/importacion/plantilla
POST   /api/boletin/alertas/importacion/vista-previa
POST   /api/boletin/alertas/importacion/confirmar
POST   /api/boletin/monitorear
GET    /api/boletin/monitoreo/{run_id}
POST   /api/boletin/monitoreo/{run_id}/detener
GET    /api/boletin/monitoreo/{run_id}/resultados
GET    /api/boletin/historial/filtros
GET    /api/boletin/historial
GET    /api/boletin/publicaciones/{publicacion_id}
GET    /api/boletin/publicaciones/{publicacion_id}/pdf
POST   /api/boletin/publicaciones/{publicacion_id}/extraer-completo
POST   /api/boletin/publicaciones/{publicacion_id}/obtener-informacion-completa
GET    /api/boletin/publicaciones/{publicacion_id}/anexos/{annex_index}/pdf
GET    /api/boletin/exportar
```

## 10. PDF escaneado y OCR

PyMuPDF extrae texto únicamente cuando el PDF tiene una capa textual utilizable. Si el documento contiene muy poco texto, el sistema lo registra como:

```text
PDF posiblemente escaneado o con capa textual insuficiente; revisar manualmente.
```

No se agregó Tesseract ni OCR obligatorio. La advertencia y la separación entre servicio y repositorio dejan preparado el módulo para incorporar un proveedor OCR en el futuro.

## 11. Diagnóstico de errores

### PyMuPDF no disponible

Ejecutá:

```bat
.venv\Scripts\python.exe -m pip install pymupdf
```

O volvé a ejecutar `PROBAR_AQUI.bat`.

### El monitoreo no devuelve resultados

Revisá:

- que existan alertas activas;
- que los aliases sean frases presentes realmente en la resolución;
- que los términos regulatorios no sean demasiado restrictivos;
- la opción **Incluir todas las resoluciones ERSeP**;
- la pestaña Historial, por si los registros fueron clasificados `SIN CAMBIOS` y no se mostraron en la ejecución.

### Muchos falsos positivos

Editá la alerta y reemplazá palabras sueltas por nombres completos. No uses aliases como `agua`, `servicio`, `cooperativa` o `limitada`.

### Error al descargar un PDF

El backend únicamente acepta URLs HTTPS pertenecientes a `boletinoficial.cba.gov.ar`. Revisá el mensaje del panel y `arranque_portal.log`.

### Google Sheets no carga

La integración del Boletín es independiente de Google Sheets. Revisá `.env.local`, la ruta configurada en `GOOGLE_CREDENTIALS_FILE` y la existencia de la credencial. No cambies esa ruta dentro del código.

### Ejecución interrumpida por cierre del portal

Al reiniciar, las ejecuciones que quedaron `RUNNING` se marcan `INTERRUPTED`. Iniciá un nuevo monitoreo; la caché y el historial previo se conservan.

## 12. Pruebas incluidas

`tests/test_boletin.py` valida:

- extracción de resoluciones simuladas;
- extracción de prestadora;
- extracción de `RESUELVE`;
- detección de estado;
- coincidencia de alertas específicas;
- estabilidad y cambio del hash;
- clasificación `NUEVO`, `SIN CAMBIOS` y `MODIFICADO`;
- contador de verificaciones;
- CRUD de alertas;
- respuesta de `/api/boletin/health`.

Para ejecutarlas manualmente:

```bat
.venv\Scripts\python.exe -m pytest -q tests\test_boletin.py
```

## 13. Compatibilidad preservada

No se modificaron las reglas funcionales existentes para:

- interpretación argentina de fechas con `dayfirst=True`;
- períodos mensuales representados por el primer día;
- selección predeterminada Desde/Hasta;
- lectura autenticada de Google Sheets;
- cálculo del ICC;
- cálculo del IPC Córdoba;
- conservación de celdas cuando una fuente aún no publicó datos;
- ARCA, Evolución, Cumpleaños y Generador de Informes Técnicos.

## 14. Archivos creados

```text
README_INTEGRACION_BOLETIN.md
app/boletin_models.py
app/boletin_repository.py
app/boletin_routes.py
app/boletin_service.py
datos_boletin_ersep/.gitkeep
static/boletin.css
static/boletin.html
static/boletin.js
tests/test_boletin.py
```

## 15. Archivos modificados

```text
.gitignore
PROBAR_AQUI.bat
main.py
requirements-dev.txt
requirements.txt
static/index.html
static/script.js
```
