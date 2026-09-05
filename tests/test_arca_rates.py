from pathlib import Path

from app.services.arca_rates import cargar_tasas_respaldo, rate_metadata

BASE = Path(__file__).resolve().parents[1]


def test_respaldo_tiene_tasa_vigente_desde_julio_2025():
    df = cargar_tasas_respaldo(BASE / "data" / "arca_rates_fallback.json")
    metadata = rate_metadata(df)
    assert metadata["count"] > 30
    assert metadata["latest"]["desde"] == "01/07/2025"
    assert metadata["latest"]["resarcitorio_mensual"] == 2.75


def test_parser_tabla_html_basica():
    from app.services.arca_rates import extraer_tasas_de_tablas_html
    html = """
    <table>
      <tr><th>Desde</th><th>Hasta</th><th>Norma</th><th>Res mensual</th><th>Res diario</th><th>Pun mensual</th><th>Pun diario</th></tr>
      <tr><td>01/07/2025</td><td>31/12/2999</td><td>R (MEC) 823/2025</td><td>2.75</td><td>0.091667</td><td>3.5</td><td>0.116667</td></tr>
    </table>
    """
    df = extraer_tasas_de_tablas_html(html)
    assert len(df) == 1
    assert df.iloc[0]["Resarcitorio mensual"] == 2.75
    assert df.iloc[0]["Norma"] == "R (MEC) 823/2025"
