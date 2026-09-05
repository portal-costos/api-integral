# Publicación en GitHub y Render — guía operativa

Este paquete contiene la versión acumulativa del portal con 20 fuentes, FAM EPEC y las correcciones finales de Boletín Oficial.

## Seguridad

No subas a GitHub ninguno de estos archivos:

- `.env` o `.env.local`
- `secrets/google-service-account.json`
- `datos_boletin_ersep/boletin_ersep.sqlite3`
- `.venv`

El `.gitignore` de este paquete ya los excluye.

## Configuración del servicio Render

- Runtime: Python 3
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/api/health`
- Root Directory: dejar vacío si `main.py` está en la raíz del repositorio.

## Variables obligatorias

- `APP_PASSWORD`: contraseña que usarán para entrar al portal.
- `JWT_SECRET`: texto aleatorio largo, distinto de la contraseña.
- `GSHEET_ID`: `1gF9d5ZBT1Rwa5yq9jJxiXgjwXke5jEAlCM-Qd99XDog`
- `GSHEET_WORKSHEET_NAME`: `Series originales`
- `GSHEET_GID`: `883561078`
- `GOOGLE_CREDENTIALS_FILE`: `/etc/secrets/google-service-account.json`

## Variables recomendadas

- `HEADER_ROW_1BASED`: `1`
- `CACHE_TTL`: `600`
- `SCRAPER_HTTP_TIMEOUT`: `60`
- `UPDATE_MONTHS`: `6`
- `UPDATE_INCLUDE_CURRENT_MONTH`: `false`
- `ARCA_RATES_CACHE_TTL`: `21600`
- `ARCA_HTTP_TIMEOUT`: `15`
- `MAX_UPLOAD_MB`: `50`
- `PYTHON_VERSION`: `3.13.14` (también está fijada en `.python-version`).

## Archivo secreto de Google

En Render, dentro de Environment > Secret Files:

- Filename: `google-service-account.json`
- Contents: pegar el contenido completo del JSON privado.

No subir ese JSON al repositorio.

## Persistencia del Boletín Oficial

El historial y las alertas se guardan en `datos_boletin_ersep/boletin_ersep.sqlite3`.
Para conservarlos entre reinicios y despliegues, agregar un Persistent Disk con este mount path:

`/opt/render/project/src/datos_boletin_ersep`

Sin disco, el portal funciona, pero los datos locales del Boletín pueden perderse en un reinicio o nuevo deploy.
