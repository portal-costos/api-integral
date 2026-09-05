# API Estadísticas Integrada — prueba local

Esta versión reúne:

- WebApp de indicadores económicos;
- actualización automática de Google Sheets;
- tablas, variaciones y evolución;
- autenticación JWT compartida;
- módulo ARCA web con tasas descargadas desde ARCA;
- respaldo local de tasas si la fuente oficial no responde;
- cálculo individual con detalle por tramos;
- inspección de Excel, selección de hoja y mapeo de columnas;
- exportación de un Excel con resultados, tasas, resumen y detalle.

## Importante sobre las credenciales

El ZIP no contiene claves privadas. No agregues el JSON de Google al repositorio ni lo envíes por chat. Para ejecución local, `configure_local.py` copia tu credencial a `secrets/google-service-account.json`, que está excluido por `.gitignore`.

Si utilizaste una clave que fue expuesta anteriormente, reemplazala por una nueva en Google Cloud antes de usar esta aplicación.

## Requisitos

- Windows 10/11, macOS o Linux.
- Python 3.11.
- Conexión a internet para consultar Google Drive, INDEC, BCRA, IPC Córdoba y ARCA.

## Instalación en Windows

1. Descomprimí el proyecto.
2. Abrí PowerShell o CMD dentro de la carpeta.
3. Ejecutá:

```bat
setup_local.bat
```

4. Configurá la aplicación con tu JSON de Google:

```bat
.venv\Scripts\python.exe configure_local.py --credentials "C:\ruta\a\tu-cuenta-servicio.json" --password "TU_CLAVE_LOCAL"
```

El script genera `.env.local`, una clave JWT aleatoria y una copia privada del JSON dentro de `secrets/`.

5. Iniciá:

```bat
start_local.bat
```

6. Abrí:

```text
http://127.0.0.1:8000
```

## Instalación manual

```bash
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Después:

```bash
pip install -r requirements.txt
python configure_local.py --credentials "/ruta/cuenta-servicio.json" --password "TU_CLAVE_LOCAL"
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

## Prueba funcional recomendada

### 1. Acceso

Ingresá en `http://127.0.0.1:8000` con la contraseña elegida en `configure_local.py`.

### 2. Indicadores

- Seleccioná dos o tres índices.
- Elegí un rango de meses.
- Probá `Ver tabla de datos filtrados` y `Calcular variaciones`.
- Entrá en `Evolución` y generá un gráfico.

### 3. Actualización automática

Presioná `Actualizar Índices Automáticamente`.

El proceso necesita que:

- el ID de la hoja sea correcto;
- la cuenta de servicio tenga acceso de edición;
- la pestaña se llame como `GSHEET_WORKSHEET_NAME`;
- los encabezados coincidan con los mapeos del backend.

Antes de la primera prueba, hacé una copia de la hoja. La actualización escribe en los últimos seis meses.

### 4. ARCA individual

- Entrá mediante el botón `%`.
- Revisá el estado de las tasas.
- Ingresá vencimiento, pago e importe.
- Ejecutá el cálculo y revisá los tramos.

Si ARCA no responde, la pantalla muestra una advertencia y usa el respaldo local.

### 5. ARCA con Excel

- Usá `ejemplo_arca.xlsx`.
- Elegí `Procesar Excel`.
- Seleccioná el archivo y presioná `Inspeccionar archivo`.
- Confirmá la hoja `Obligaciones` y el mapeo sugerido.
- Presioná `Procesar y descargar Excel final`.

El libro descargado contiene:

- `Intereses ARCA`;
- `Tasas usadas`;
- `Resumen`;
- `Detalle por tramos`.

## Endpoints útiles

```text
GET  /api/health
GET  /docs
POST /api/login
POST /api/actualizar-indices
GET  /api/arca/tasas
POST /api/arca/calcular
POST /api/arca/inspect-excel
POST /api/arca/procesar-excel
```

Todos los endpoints funcionales, salvo `/api/login` y `/api/health`, requieren el token JWT generado al iniciar sesión.

## Solución de problemas

### `APP_PASSWORD no configurada`

No existe `.env.local`. Ejecutá `configure_local.py`.

### `Falta GOOGLE_CREDENTIALS_JSON o GOOGLE_CREDENTIALS_FILE`

La aplicación puede leer la hoja pública, pero no actualizarla. Ejecutá `configure_local.py --credentials ...`.

### `403` de Google Sheets

Compartí la hoja con el correo `client_email` de la cuenta de servicio y otorgale permiso de editor.

### ARCA usa respaldo local

La fuente oficial no respondió o cambió su HTML. El cálculo continúa, pero la pantalla lo advierte. Compará la tasa más reciente con el sitio oficial antes de usar el resultado administrativamente.

### Error con `.xls`

Verificá que `xlrd` esté instalado mediante `pip install -r requirements.txt`.

## Ejecución de pruebas

```bash
pytest -q
```

Las pruebas no modifican Google Sheets ni requieren credenciales reales.

## Incidencia tarifaria

La versión integrada incorpora el módulo disponible en:

- `http://127.0.0.1:8000/static/incidencia.html`

También se accede desde el menú principal. La herramienta recibe 21 parámetros zonales y un Excel EPH, permite mapear columnas, calcula percentiles e incidencia y exporta un Excel completo. La documentación específica está en `README_INCIDENCIA_TARIFARIA.md`.
