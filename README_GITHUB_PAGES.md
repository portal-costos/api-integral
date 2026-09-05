# GitHub Pages como frontend + Render como backend

Esta versión separa la interfaz estática de la API sin romper el despliegue actual de Render.

## Arquitectura

- **Frontend:** carpeta `docs/`, publicada con GitHub Pages.
- **Backend:** FastAPI en `https://api-estadisticas.onrender.com`.
- **Configuración del frontend:** `docs/config.js`.
- **Backend legado:** `static/` se conserva temporalmente para que Render siga pudiendo servir la interfaz anterior durante la transición.

## 1. Subir esta versión a GitHub

Repositorio objetivo: `portal-costos/api-integral`.

Subir el proyecto completo a ese repositorio. No subir `.env`, `.env.local`, credenciales de Google ni bases SQLite privadas.

## 2. Activar GitHub Pages

En GitHub:

1. `Settings`
2. `Pages`
3. `Build and deployment` -> `Deploy from a branch`
4. Branch: `main`
5. Folder: `/docs`
6. Guardar.

GitHub publicará `docs/index.html` y el resto de las páginas con rutas relativas.

La URL esperada del frontend es:

```text
https://portal-costos.github.io/api-integral/
```

El nombre del repositorio no está hardcodeado en las rutas internas.

## 3. Configurar CORS en Render

En Render -> servicio `api-estadisticas` -> `Environment`, cargar:

```text
CORS_ORIGINS=https://portal-costos.github.io
```

CORS trabaja con el **origin**, no con la ruta del repositorio. Para este proyecto el origin correcto es `https://portal-costos.github.io`; **no** debe incluir `/api-integral/`.

La aplicación ya admite `GET`, `POST` y `OPTIONS`, además de los encabezados `Authorization` y `Content-Type`.

## 4. Backend del frontend

`docs/config.js` contiene:

```js
API_BASE_URL: "https://api-estadisticas.onrender.com"
```

Si algún día cambia Render, alcanza con modificar esa línea. No hay claves ni secretos en el frontend.

## 5. Prueba funcional

Desde la URL de GitHub Pages:

1. Iniciar sesión.
2. Abrir Índices y cargar las series.
3. Probar tabla/variaciones/evolución.
4. Abrir ARCA.
5. Abrir Incidencia.
6. Abrir Informes.
7. Abrir Boletín y Transporte.

Si el login funciona pero una página devuelve error CORS, revisar `CORS_ORIGINS` en Render.

## Próxima etapa

Una vez validada esta separación, el chatbot por reglas puede agregarse íntegramente en `docs/` y usar los endpoints estadísticos existentes, sin API de IA.
