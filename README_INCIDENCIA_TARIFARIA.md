# Módulo de Incidencia Tarifaria

Nueva herramienta integrada al portal de Costos y Tarifas para procesar una base de hogares de la Encuesta Permanente de Hogares (EPH) y estimar la incidencia de las tarifas de ACSA en siete zonales socioeconómicos.

## Acceso

Con la aplicación iniciada y la sesión autenticada:

- Menú principal → **Incidencia tarifaria**.
- URL directa: `/static/incidencia.html`.

## Entradas

### 21 parámetros zonales

Para cada Zonal 1 a Zonal 7 se cargan:

1. Porcentaje de usuarios.
2. Tarifa promedio con impuestos.
3. Tarifa promedio sin impuestos.

Los porcentajes se normalizan automáticamente si, por redondeo, no suman exactamente 100 %.

### Excel EPH

Las columnas mínimas son:

- `IPCF`: ingreso per cápita familiar.
- `ITF`: ingreso total familiar.
- `PONDIH`: ponderador específico de ingresos.

Columnas recomendadas:

- `IX_TOT`: integrantes del hogar.
- `CODUSU` y `NRO_HOGAR`: auditoría y detección de duplicados.
- `ANO4` y `TRIMESTRE`: identificación temporal.
- `AGLOMERADO`: permite conservar, por ejemplo, el código 13 de Gran Córdoba.
- `ADECIFR` y `ADECCFR`: deciles originales, como referencia.

La página inspecciona el archivo, permite elegir la hoja y mapear las columnas. También ofrece una plantilla descargable.

## Metodología

1. Filtra el aglomerado cuando se mapea esa columna.
2. Convierte IPCF, ITF y PONDIH a valores numéricos.
3. Excluye registros con datos esenciales inválidos o `PONDIH <= 0`.
4. Conserva hogares con `ITF = 0`, informándolos por separado.
5. Ordena hogares por IPCF ascendente; utiliza ITF y, si existen, CODUSU y NRO_HOGAR para desempatar.
6. Normaliza PONDIH y construye el percentil inicial, final y medio de cada registro.
7. Mantiene el supuesto socioeconómico `Zonal 1 < ... < Zonal 7`.
8. Construye los cortes zonales acumulando la participación normalizada de usuarios.
9. Divide el peso de un hogar cuando su intervalo atraviesa un corte zonal:

   `solape = max(0, min(fin_hogar, fin_zonal) - max(inicio_hogar, inicio_zonal))`

10. Calcula ITF medio, IPCF medio, miembros promedio, hogares sin ingreso, incidencias y percentiles.

## Dos indicadores de carga

- **Incidencia general:** tarifa del zonal dividida por el ITF medio imputado.
- **Carga media de hogares con ingreso positivo:** calcula tarifa/ITF para cada hogar y luego obtiene el promedio ponderado. Es más sensible a los hogares de ingresos bajos.

Los hogares con ITF menor o igual a cero no pueden integrar la segunda razón; se informan en una columna independiente.

## Salida

La web muestra:

- Indicadores generales.
- Resultados por zonal con y sin impuestos.
- Percentiles 0 a 100 de la EPH.
- Percentiles internos por zonal.
- Advertencias y metodología.

El botón **Descargar Excel completo** genera:

- `Resumen`
- `Resultados zonales`
- `Parámetros`
- `Percentiles EPH`
- `Percentiles por zonal`
- `Base procesada`
- `Metodología`

## API

- `GET /api/incidencia/health`
- `GET /api/incidencia/plantilla.xlsx`
- `POST /api/incidencia/inspect-excel`
- `POST /api/incidencia/calcular`
- `POST /api/incidencia/exportar.xlsx`

Todos los endpoints requieren el mismo token de autenticación del portal.

## Archivos incorporados

- `app/services/incidencia_engine.py`
- `app/routers/incidencia.py`
- `static/incidencia.html`
- `static/incidencia.css`
- `static/incidencia.js`
- `tests/test_incidencia_engine.py`
