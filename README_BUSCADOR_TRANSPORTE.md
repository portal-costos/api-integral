# Buscador automático de resoluciones de la Secretaría de Transporte

Este módulo se agregó como una herramienta independiente del buscador ERSeP. No utiliza alertas, cooperativas ni palabras clave ingresadas por el usuario.

## Acceso

Desde el menú principal, abrir **Resoluciones de Transporte**. La pantalla también puede abrirse directamente en:

`/static/transporte.html`

## Funcionamiento

1. Recorre los doce meses del año elegido en el archivo oficial del Boletín Oficial de la Provincia de Córdoba.
2. Procesa únicamente los PDF de la 1.ª Sección.
3. Extrae la capa de texto de cada PDF con PyMuPDF.
4. Detecta cuerpos normativos del tipo `Resolución N ...` o `Resolución General N ...`.
5. Considera una resolución como propia de Transporte cuando encuentra una cabecera institucional inmediata `SECRETARÍA DE TRANSPORTE` o la fórmula de autoridad `EL SECRETARIO/A DE TRANSPORTE ... RESUELVE`.
6. Descarta las apariciones del sumario y las menciones incidentales a la Secretaría dentro de normas de otros organismos.
7. Guarda cada resolución en una base SQLite independiente y la clasifica como `NUEVO`, `MODIFICADO` o `SIN CAMBIOS`.

## Archivos agregados

- `app/transporte_models.py`: modelo de entrada de la búsqueda.
- `app/transporte_service.py`: descarga, extracción, identificación y clasificación.
- `app/transporte_routes.py`: API FastAPI, historial, detalle y exportaciones.
- `static/transporte.html`: interfaz del módulo.
- `static/transporte.js`: lógica de la interfaz.
- `tests/test_transporte.py`: pruebas del detector.

## Base de datos

Se crea automáticamente en:

`datos_boletin_transporte/boletin_transporte.sqlite3`

La base es independiente de `datos_boletin_ersep` y no carga alertas predeterminadas.

## API

- `GET /api/transporte/health`
- `POST /api/transporte/monitorear`
- `GET /api/transporte/monitoreo/{run_id}`
- `POST /api/transporte/monitoreo/{run_id}/detener`
- `GET /api/transporte/monitoreo/{run_id}/resultados`
- `GET /api/transporte/historial`
- `GET /api/transporte/historial/filtros`
- `GET /api/transporte/publicaciones/{id}`
- `GET /api/transporte/publicaciones/{id}/pdf`
- `GET /api/transporte/exportar`

Ejemplo de inicio de búsqueda:

```json
{
  "anio": 2026,
  "revalidar_pdfs": false,
  "mostrar_sin_cambios": false
}
```

## Exportaciones

El historial puede exportarse a Excel o JSON. Cada ejecución también puede generar un TXT preparado para análisis con un modelo de lenguaje.

## Verificación

Las pruebas específicas se ejecutan con:

```bash
pytest -q tests/test_transporte.py
```
