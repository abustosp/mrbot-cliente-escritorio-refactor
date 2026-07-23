"""
Generación de reportes HTML individuales y general para Control de Monotributistas.
Utiliza Chart.js vía CDN para gráficos interactivos.
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from mrbot_app.control_monotributistas import (
    obtener_categoria,
    obtener_max_ingresos_categoria,
    preparar_datos_individuales,
)

# ─── Paleta de colores (misma filosofía que mrbot-erp) ────────────────
COLOR_VENTAS = "rgba(0, 123, 255, 0.85)"    # azul
COLOR_VENTAS_BORDE = "rgb(0, 123, 255)"
COLOR_COMPRAS = "rgba(220, 53, 69, 0.85)"   # rojo
COLOR_COMPRAS_BORDE = "rgb(220, 53, 69)"
COLOR_EXCEDIDO = "rgba(255, 193, 7, 0.9)"   # amarillo
COLOR_ACTUAL = "rgba(40, 167, 69, 0.9)"     # verde
COLOR_FONDO_GRAFICO = "#f8f9fa"


# ═══════════════════════════════════════════════════════════════════════
#  TEMPLATE: HTML individual por contribuyente
# ═══════════════════════════════════════════════════════════════════════

def _html_header(title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f4f6f9; color: #212529; padding: 20px; }}
.container {{ max-width: 1150px; margin: 0 auto; }}

/* Header estilo ERP */
.header {{ background: linear-gradient(135deg, #002060 0%, #003d99 100%);
          color: #fff; padding: 22px 28px; border-radius: 8px; margin-bottom: 20px;
          box-shadow: 0 2px 6px rgba(0,0,0,0.12); }}
.header h1 {{ font-size: 1.35rem; margin: 0 0 3px 0; font-weight: 600; }}
.header .meta {{ font-size: 0.88rem; opacity: 0.88; }}
.header .categoria-badge {{ display: inline-block; margin-top: 6px;
    padding: 4px 12px; border-radius: 20px; font-weight: 600; font-size: 0.85rem; }}
.badge-excedido {{ background: #dc3545; color: #fff; }}
.badge-normal {{ background: #28a745; color: #fff; }}
.badge-advertencia {{ background: #ffc107; color: #212529; }}
.badge-cat-excedido {{ background: #000; color: #fff; }}

/* Card-outline estilo AdminLTE / ERP */
.card {{ background: #fff; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        margin-bottom: 18px; border-top: 3px solid #dee2e6; overflow: hidden; }}
.card-header {{ padding: 10px 16px; border-bottom: 1px solid #e9ecef; }}
.card-header h3 {{ font-size: 0.92rem; font-weight: 600; color: #495057; margin: 0; }}
.card-body {{ padding: 14px 16px; }}
.card-info {{ border-top-color: #17a2b8; }}
.card-success {{ border-top-color: #28a745; }}
.card-warning {{ border-top-color: #ffc107; }}
.card-danger {{ border-top-color: #dc3545; }}
.card-primary {{ border-top-color: #007bff; }}

/* Sistema de grillas simple (sin Bootstrap) */
.row {{ display: flex; flex-wrap: wrap; margin: 0 -9px 0 -9px; }}
.row > * {{ padding: 0 9px; }}
.col-md-12 {{ flex: 0 0 100%; max-width: 100%; }}
.col-md-6 {{ flex: 0 0 50%; max-width: 50%; }}
@media (max-width: 768px) {{
    .col-md-6 {{ flex: 0 0 100%; max-width: 100%; }}
}}

.chart-container {{ position: relative; min-height: 220px; }}

/* Termómetro */
.thermometer-wrapper {{ padding: 8px 0; }}
.thermometer-label {{ display: flex; justify-content: space-between; font-size: 0.82rem; margin-bottom: 4px; color: #6c757d; }}
.thermometer-track {{ height: 24px; background: #e9ecef; border-radius: 12px; overflow: hidden; position: relative; }}
.thermometer-fill {{ height: 100%; border-radius: 12px; transition: width 0.8s ease;
                    background: linear-gradient(90deg, #28a745, #ffc107 65%, #dc3545 85%); }}
.thermometer-marker {{ position: absolute; top: -3px; width: 3px; height: 30px;
                       background: #002060; border-radius: 2px; }}
.marker-label {{ position: absolute; top: -16px; transform: translateX(-50%);
                font-size: 0.68rem; font-weight: 700; color: #002060; }}

/* Tablas */
.table-section {{ background: #fff; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                  padding: 14px 16px; margin-bottom: 18px; border-top: 3px solid #6c757d; }}
.table-section h3 {{ font-size: 0.92rem; font-weight: 600; color: #495057;
                     margin-bottom: 10px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ background: #e9ecef; color: #495057; font-weight: 600; padding: 7px 10px; text-align: left;
      border-bottom: 2px solid #dee2e6; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #e9ecef; }}
tr:hover td {{ background: #f8f9fa; }}
tfoot td {{ background: #f1f3f5; font-weight: 600; }}
.text-right {{ text-align: right; }}
.text-center {{ text-align: center; }}
.monto {{ font-variant-numeric: tabular-nums; }}
.footer {{ text-align: center; color: #6c757d; font-size: 0.78rem; margin-top: 20px; padding: 10px; }}

/* Alerta compras > ventas */
.alert {{ padding: 8px 12px; border-radius: 4px; font-size: 0.82rem; margin-bottom: 10px; }}
.alert-warning {{ background: #fff3cd; border: 1px solid #ffc107; color: #856404; }}
@media print {{
    body {{ background: #fff; padding: 8px; }}
    .header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .card, .table-section {{ break-inside: avoid; }}
}}
</style>
</head>
<body>
<div class="container">"""


def _html_footer() -> str:
    now = datetime.now().strftime('%d/%m/%Y %H:%M')
    return f"""
<div class="footer">Generado por mrbot · Control Monotributistas · {now}</div>
</div>
</body>
</html>"""


def _badge_class(categoria: str, pct: float) -> str:
    if categoria == "Excedido":
        return "badge-excedido"
    if pct >= 90:
        return "badge-excedido"
    if pct >= 70:
        return "badge-advertencia"
    return "badge-normal"


def _format_pesos(valor: float) -> str:
    if abs(valor) >= 1_000_000:
        return f"$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def generar_html_individual(datos: Dict[str, Any]) -> str:
    """Genera el HTML completo para un contribuyente individual."""
    cliente = datos["cliente"]
    cuit = datos["cuit"]
    categoria = datos["categoria"]
    limite = datos["limite_categoria"]
    pct = datos["pct_limite"]
    total_v = datos["total_ventas"]
    total_c = datos["total_compras"]
    fecha_desde = datos.get("fecha_desde", "")
    fecha_hasta = datos.get("fecha_hasta", "")
    series_v = datos["series_ventas"]
    series_c = datos["series_compras"]

    # Compute accumulated series
    ventas_acum = []
    compras_acum = []
    meses_set = set()
    for s in series_v:
        meses_set.add(s["mes"])
    for s in series_c:
        meses_set.add(s["mes"])
    ventas_map = {s["mes"]: s["total"] for s in series_v}
    compras_map = {s["mes"]: s["total"] for s in series_c}

    running_v = 0
    running_c = 0
    for mes in sorted(meses_set):
        running_v += ventas_map.get(mes, 0)
        running_c += compras_map.get(mes, 0)
        ventas_acum.append({"mes": mes, "total": round(running_v, 2)})
        compras_acum.append({"mes": mes, "total": round(running_c, 2)})

    series_v_json = json.dumps(series_v, default=str)
    series_c_json = json.dumps(series_c, default=str)
    ventas_acum_json = json.dumps(ventas_acum, default=str)
    compras_acum_json = json.dumps(compras_acum, default=str)
    escala = json.dumps(datos["escala_categorias"], default=str)

    # Desglose por contraparte (clientes/proveedores)
    contrapartes_v_json = json.dumps(datos.get("contrapartes_ventas", []), default=str)
    contrapartes_c_json = json.dumps(datos.get("contrapartes_compras", []), default=str)

    badge = _badge_class(categoria, pct)
    badge_text = f"Categoría {categoria}" if categoria != "Excedido" else "Excedido"

    # Build monthly table rows from mes keys
    meses_set = set()
    for s in datos.get("series_ventas", []):
        meses_set.add(s["mes"])
    for s in datos.get("series_compras", []):
        meses_set.add(s["mes"])
    ventas_map = {s["mes"]: s["total"] for s in datos.get("series_ventas", [])}
    compras_map = {s["mes"]: s["total"] for s in datos.get("series_compras", [])}

    table_rows = ""
    for mes in sorted(meses_set):
        v = ventas_map.get(mes, 0)
        c = compras_map.get(mes, 0)
        table_rows += f"""<tr>
    <td>{mes}</td>
    <td class="text-right monto">{_format_pesos(v)}</td>
    <td class="text-right monto">{_format_pesos(c)}</td>
    <td class="text-right monto">{_format_pesos(v - c)}</td>
</tr>"""

    limite_str = _format_pesos(limite) if limite > 0 else "—"
    pct_str = f"{pct:.1f}%" if limite > 0 else "—"

    return _html_header(f"Reporte {cliente} · Monotributo") + f"""
<div class="header">
    <h1>{cliente}</h1>
    <p class="meta">
        CUIT {cuit} · Período: {fecha_desde} a {fecha_hasta} ·
        Ventas totales: {_format_pesos(total_v)} ·
        Compras totales: {_format_pesos(total_c)}
    </p>
    <div>
        <span class="categoria-badge {badge}">{badge_text} · Límite: {limite_str}</span>
        <span class="categoria-badge badge-normal" style="margin-left:8px">{pct_str} del límite</span>
    </div>
</div>

<!-- Fila 1: Evolución Mensual -->
<div class="row">
    <div class="col-md-12">
        <div class="card card-info card-outline">
            <div class="card-header"><h3 class="card-title">📊 Compras vs Ventas · Evolución Mensual</h3></div>
            <div class="card-body"><div class="chart-container"><canvas id="chartMensual"></canvas></div></div>
        </div>
    </div>
</div>

<!-- Fila 2: Escala + Termómetro -->
<div class="row">
    <div class="col-md-6">
        <div class="card card-success card-outline">
            <div class="card-header"><h3 class="card-title">📈 Escala de Categorías</h3></div>
            <div class="card-body"><div class="chart-container"><canvas id="chartCategorias"></canvas></div></div>
        </div>
    </div>
    <div class="col-md-6">
        <div class="card card-warning card-outline">
            <div class="card-header"><h3 class="card-title">🌡️ Progreso del Límite</h3></div>
            <div class="card-body">
                <div class="thermometer-wrapper">
                    <div class="thermometer-label">
                        <span>$ 0</span>
                        <span><strong>{_format_pesos(total_v)}</strong></span>
                        <span>{limite_str}</span>
                    </div>
                    <div class="thermometer-track">
                        <div class="thermometer-fill" style="width:{min(pct, 100):.1f}%"></div>
                        <div class="thermometer-marker" style="left:{min(pct, 100):.1f}%">
                            <span class="marker-label">{pct_str}</span>
                        </div>
                    </div>
                    <p style="margin-top:10px;font-size:0.82rem;color:#6c757d;">
                        {f"⚠️ Has consumido el <strong>{pct_str}</strong> del límite de {limite_str} (Categoría {categoria})."
                         if categoria != "Excedido" else
                         f"❌ Has <strong>excedido</strong> el límite máximo de categoría."}
                        {f" Te recomendamos evaluar una recategorización."
                         if pct >= 70 and categoria != "Excedido" else ""}
                    </p>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Fila 3: Acumulado -->
<div class="row">
    <div class="col-md-12">
        <div class="card card-info card-outline">
            <div class="card-header"><h3 class="card-title">📈 Compras vs Ventas · Acumulado</h3></div>
            <div class="card-body">
                {f"""<div class="alert alert-warning">⚠️ Las <strong>compras</strong> superan a las <strong>ventas</strong> en este período. Diferencia: {_format_pesos(abs(total_c - total_v))}</div>""" if total_c > total_v else ""}
                <div class="chart-container"><canvas id="chartAcumulado"></canvas></div>
            </div>
        </div>
    </div>
</div>

<!-- Fila 4: Doughnuts incidencia -->
<div class="row">
    <div class="col-md-6">
        <div class="card card-danger card-outline">
            <div class="card-header"><h3 class="card-title">🛒 Ventas por Cliente · Incidencia</h3></div>
            <div class="card-body"><div class="chart-container"><canvas id="chartVentasContrapartes"></canvas></div></div>
        </div>
    </div>
    <div class="col-md-6">
        <div class="card card-primary card-outline">
            <div class="card-header"><h3 class="card-title">📦 Compras por Proveedor · Incidencia</h3></div>
            <div class="card-body"><div class="chart-container"><canvas id="chartComprasContrapartes"></canvas></div></div>
        </div>
    </div>
</div>

<div class="table-section">
    <h3>📋 Detalle Mensual</h3>
    <table>
        <thead>
            <tr><th>Período</th><th class="text-right">Ventas (Emitidos)</th><th class="text-right">Compras (Recibidos)</th><th class="text-right">Diferencia</th></tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
        <tfoot>
            <tr style="font-weight:600;background:#e9ecef;">
                <td><strong>Totales</strong></td>
                <td class="text-right">{_format_pesos(total_v)}</td>
                <td class="text-right">{_format_pesos(total_c)}</td>
                <td class="text-right">{_format_pesos(total_v - total_c)}</td>
            </tr>
        </tfoot>
    </table>
</div>

<script>
const seriesVentas = {series_v_json};
const seriesCompras = {series_c_json};
const ventasAcum = {ventas_acum_json};
const comprasAcum = {compras_acum_json};
const contrapartesVentas = {contrapartes_v_json};
const contrapartesCompras = {contrapartes_c_json};
const escalaCategorias = {escala};
const totalVentas = {total_v};
const totalCompras = {total_c};
const limiteCategoria = {limite};
const pctLimite = {pct};
const categoriaActual = '{categoria}';

// ─── Alinear series por período ────────────────────────────────────────
function alignPeriodos(ventas, compras) {{
    const periodos = [...new Set([...ventas.map(d=>d.mes), ...compras.map(d=>d.mes)])].sort();
    const vMap = {{}}, cMap = {{}};
    ventas.forEach(d => vMap[d.mes] = d.total);
    compras.forEach(d => cMap[d.mes] = d.total);
    return {{
        labels: periodos,
        ventas: periodos.map(p => vMap[p] || 0),
        compras: periodos.map(p => cMap[p] || 0),
    }};
}}

// ─── Gráfico Mensual (barras) ──────────────────────────────────────────
const al = alignPeriodos(seriesVentas, seriesCompras);
new Chart(document.getElementById('chartMensual'), {{
    type: 'bar',
    data: {{
        labels: al.labels,
        datasets: [
            {{ label: 'Ventas (Emitidos)', data: al.ventas,
               backgroundColor: '{COLOR_VENTAS}',
               borderColor: '{COLOR_VENTAS_BORDE}', borderWidth: 1 }},
            {{ label: 'Compras (Recibidos)', data: al.compras,
               backgroundColor: '{COLOR_COMPRAS}',
               borderColor: '{COLOR_COMPRAS_BORDE}', borderWidth: 1 }},
        ]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'top' }},
                   tooltip: {{ callbacks: {{
                       label: ctx => ctx.dataset.label + ': $ ' + Number(ctx.parsed.y).toLocaleString('es-AR', {{minimumFractionDigits:2}})
                   }} }} }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ beginAtZero: true,
                  ticks: {{ callback: v => '$ ' + Number(v).toLocaleString('es-AR') }} }}
        }}
    }}
}});

// ─── Gráfico de Categorías ────────────────────────────────────────────
const catLabels = escalaCategorias.map(d => 'Cat. ' + d.categoria);
const catLimites = escalaCategorias.map(d => d.limite);
const ingresosActual = totalVentas;

new Chart(document.getElementById('chartCategorias'), {{
    type: 'bar',
    data: {{
        labels: catLabels,
        datasets: [
            {{ label: 'Límite por categoría', data: catLimites,
               backgroundColor: catLimites.map(l => l >= ingresosActual ? 'rgba(0,123,255,0.5)' : 'rgba(220,53,69,0.5)'),
               borderColor: catLimites.map(l => l >= ingresosActual ? 'rgb(0,123,255)' : 'rgb(220,53,69)'),
               borderWidth: 1 }},
            {{ label: 'Tus ingresos', data: catLimites.map(() => ingresosActual),
               type: 'line', fill: false,
               borderColor: 'rgb(40,167,69)',
               borderDash: [6, 3],
               borderWidth: 2,
               pointRadius: 0,
               pointHitRadius: 0 }},
        ]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: {{ legend: {{ position: 'top' }},
                   tooltip: {{ callbacks: {{
                       label: ctx => '$ ' + ctx.parsed.x.toLocaleString('es-AR', {{minimumFractionDigits:2}})
                   }} }} }},
        scales: {{
            x: {{ beginAtZero: true,
                  ticks: {{ callback: v => '$ ' + (v/1000000).toFixed(1) + 'M' }} }}
        }}
    }}
}});

// ─── Gráfico Acumulado ────────────────────────────────────────────────
const acumLabels = ventasAcum.map(d => d.mes);
const maxAcumVal = Math.max(
    ...ventasAcum.map(d => d.total),
    ...comprasAcum.map(d => d.total)
);
// Categorías cuyo límite entra en el rango visible del gráfico
const catLimitsVisible = escalaCategorias.filter(
    d => d.limite <= maxAcumVal * 1.25
);
const catLineDatasets = catLimitsVisible.map(function(entry) {{
    var lim = entry.limite;
    var cat = entry.categoria;
    var isCurrent = cat === categoriaActual;
    return {{
        label: 'Cat. ' + cat + ' ($ ' + lim.toLocaleString('es-AR') + ')',
        data: acumLabels.map(function() {{ return lim; }}),
        type: 'line',
        fill: false,
        borderColor: isCurrent ? 'rgb(255, 193, 7)' : 'rgba(108, 117, 125, 0.5)',
        borderWidth: isCurrent ? 3 : 1,
        borderDash: isCurrent ? [] : [5, 5],
        pointRadius: 0,
        pointHitRadius: 0,
    }};
}});

new Chart(document.getElementById('chartAcumulado'), {{
    type: 'line',
    data: {{
        labels: acumLabels,
        datasets: [
            {{ label: 'Ventas acumuladas (Emitidos)', data: ventasAcum.map(d => d.total),
               borderColor: 'rgb(0,123,255)', backgroundColor: 'rgba(0,123,255,0.10)',
               fill: true, tension: 0.3, pointRadius: 3, borderWidth: 2 }},
            {{ label: 'Compras acumuladas (Recibidos)', data: comprasAcum.map(d => d.total),
               borderColor: 'rgb(220,53,69)', backgroundColor: 'rgba(220,53,69,0.10)',
               fill: true, tension: 0.3, pointRadius: 3, borderWidth: 2 }},
            ...catLineDatasets,
        ]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'top' }},
                   tooltip: {{ callbacks: {{
                       label: ctx => ctx.dataset.label + ': $ ' + Number(ctx.parsed.y).toLocaleString('es-AR', {{minimumFractionDigits:2}})
                   }} }} }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ beginAtZero: true,
                  ticks: {{ callback: v => '$ ' + Number(v).toLocaleString('es-AR') }} }}
        }}
    }}
}});

// ─── Paleta para doughnuts (estilo ERP) ───────────────────────────────
const DOUGHNUT_COLORS_V = ['#007bff','#1a8bff','#339cff','#4dacff','#66bdff','#80cdff','#99ddff','#b3eeff'];
const DOUGHNUT_COLORS_C = ['#dc3545','#e35d6a','#e4666b','#ea7f7c','#ed918d','#f0a39e','#f3b5af','#f6c7c0'];

function renderDoughnut(canvasId, data, colors) {{
    if (!data || data.length === 0) {{
        document.getElementById(canvasId).parentNode.innerHTML =
            '<p style="text-align:center;color:#6c757d;padding:40px 0;">Sin datos</p>';
        return;
    }}
    const labels = data.map(d => d.nombre + ' (' + d.porcentaje + '%)');
    const values = data.map(d => d.total);
    const bgColors = data.map((_, i) => colors[i % colors.length]);
    new Chart(document.getElementById(canvasId), {{
        type: 'doughnut',
        data: {{
            labels,
            datasets: [{{ data: values, backgroundColor: bgColors, borderWidth: 1 }}]
        }},
        options: {{
            responsive: true, maintainAspectRatio: false,
            plugins: {{
                legend: {{ position: 'right', labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }},
                tooltip: {{
                    callbacks: {{
                        label: ctx => {{
                            const d = data[ctx.dataIndex];
                            return d.nombre + ': $ ' + Number(d.total).toLocaleString('es-AR', {{minimumFractionDigits:2}}) + ' (' + d.porcentaje + '%)';
                        }}
                    }}
                }}
            }}
        }}
    }});
}}

renderDoughnut('chartVentasContrapartes', contrapartesVentas, DOUGHNUT_COLORS_V);
renderDoughnut('chartComprasContrapartes', contrapartesCompras, DOUGHNUT_COLORS_C);
</script>
""" + _html_footer()


# ═══════════════════════════════════════════════════════════════════════
#  TEMPLATE: Reporte general
# ═══════════════════════════════════════════════════════════════════════

def _cat_color(categoria: str) -> str:
    """Retorna un color hex desde celeste claro (A) a azul oscuro (K).
    Excedido → negro."""
    if categoria == "Excedido" or not categoria:
        return "#000000"
    idx = "ABCDEFGHIJK".find(categoria)
    if idx < 0:
        return "#6c757d"
    lightness = 85 - idx * (65 / max(len("ABCDEFGHIJK") - 1, 1))
    return f"hsl(210, 70%, {lightness:.0f}%)"


def generar_html_general(todos_los_datos: List[Dict[str, Any]]) -> str:
    """Genera el HTML del reporte general con tabla resumen y gráficos."""
    total_contribuyentes = len(todos_los_datos)
    total_ventas_global = sum(d["total_ventas"] for d in todos_los_datos)
    total_compras_global = sum(d["total_compras"] for d in todos_los_datos)
    excedidos = sum(1 for d in todos_los_datos if d["categoria"] == "Excedido")

    # Infer date range from first contribuyente with data
    fecha_desde = ""
    fecha_hasta = ""
    for d in todos_los_datos:
        if d.get("fecha_desde"):
            fecha_desde = d["fecha_desde"]
            fecha_hasta = d.get("fecha_hasta", "")
            break

    # Category distribution
    cat_dist = {}
    for d in todos_los_datos:
        cat = d["categoria"]
        cat_dist[cat] = cat_dist.get(cat, 0) + 1
    cat_labels = sorted(cat_dist.keys(), key=lambda c: (
        "ABCDEFGHIJK".index(c) if c in "ABCDEFGHIJK" else 99
    ))
    cat_counts = [cat_dist[c] for c in cat_labels]
    cat_colors = [_cat_color(c) if c != "Excedido" else "#000000" for c in cat_labels]

    datos_json = json.dumps([{
        "cliente": d["cliente"],
        "cuit": d["cuit"],
        "total_ventas": d["total_ventas"],
        "total_compras": d["total_compras"],
        "categoria": d["categoria"],
        "categoria_compras": d.get("categoria_compras", ""),
        "limite_categoria": d["limite_categoria"],
        "pct_limite": d["pct_limite"],
    } for d in todos_los_datos], default=str)

    # Table rows
    table_rows = ""
    for idx, d in enumerate(todos_los_datos):
        badge = _badge_class(d["categoria"], d["pct_limite"])
        badge_txt = d["categoria"] if d["categoria"] != "Excedido" else "Excedido"
        limite_str = _format_pesos(d["limite_categoria"]) if d["limite_categoria"] > 0 else "—"
        pct_str = f"{d['pct_limite']:.1f}%" if d["limite_categoria"] > 0 else "—"
        compras_superan = d["total_compras"] > d["total_ventas"] and d.get("categoria_compras", "") != d["categoria"]
        cat_color = _cat_color(d["categoria"])
        cat_text_color = "#fff" if d["categoria"] == "Excedido" else "#fff"
        badge_inline = f'background:{cat_color};color:#fff;font-size:0.75rem;padding:2px 10px;border-radius:20px;font-weight:600;display:inline-block;'
        if compras_superan:
            cat_comp = d.get("categoria_compras", "")
            cat_comp_color = _cat_color(cat_comp)
            badge_comp_inline = f'background:{cat_comp_color};color:#fff;font-size:0.75rem;padding:2px 10px;border-radius:20px;font-weight:600;display:inline-block;'
            categ_col = f'<span style="{badge_inline}">{badge_txt}</span><span style="margin:0 4px;">⚠️</span><span style="{badge_comp_inline}">{cat_comp}</span>'
        else:
            categ_col = f'<span style="{badge_inline}">{badge_txt}</span>'
        archivo_html = d.get("archivo_html", "")
        cliente_link = f'<a href="reportes_individuales/{archivo_html}" style="color:#007bff;text-decoration:none;" target="_blank" rel="noopener">{d["cliente"]}</a>' if archivo_html else d["cliente"]
        table_rows += f"""<tr>
    <td>{cliente_link}</td>
    <td>{d["cuit"]}</td>
    <td class="text-right monto">{_format_pesos(d["total_ventas"])}</td>
    <td class="text-right monto">{_format_pesos(d["total_compras"])}</td>
    <td class="text-center">{categ_col}</td>
    <td class="text-right">{limite_str}</td>
    <td class="text-center">{pct_str}</td>
</tr>"""

    return _html_header("Reporte General · Control Monotributistas") + f"""
<div class="header">
    <h1>Reporte General · Control Monotributistas</h1>
    <p class="meta">
        {total_contribuyentes} contribuyentes · Período: {fecha_desde} a {fecha_hasta} ·
        Ventas totales: {_format_pesos(total_ventas_global)} ·
        Compras totales: {_format_pesos(total_compras_global)} ·
        {excedidos} excedido(s)
    </p>
</div>

<div class="chart-grid">
    <div class="chart-card chart-full">
        <h3>📊 Distribución de Categorías</h3>
        <div class="chart-container" style="min-height:200px;">
            <canvas id="chartDistribucion"></canvas>
        </div>
    </div>
</div>

<div class="table-section">
    <h3>📋 Resumen de Contribuyentes</h3>
    <div style="overflow-x:auto;">
    <table>
        <thead>
            <tr>
                <th>Contribuyente</th>
                <th>CUIT</th>
                <th class="text-right">Ventas</th>
                <th class="text-right">Compras</th>
                <th class="text-center">Categoría</th>
                <th class="text-right">Límite</th>
                <th class="text-center">% Límite</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    </div>
</div>

<script>
const todosDatos = {datos_json};
const catDistLabels = {json.dumps(cat_labels)};
const catDistCounts = {json.dumps(cat_counts)};
const catDistColors = {json.dumps(cat_colors[:len(cat_labels)])};

new Chart(document.getElementById('chartDistribucion'), {{
    type: 'bar',
    data: {{
        labels: catDistLabels,
        datasets: [{{
            label: 'Contribuyentes',
            data: catDistCounts,
            backgroundColor: catDistColors,
            borderColor: catDistColors.map(c => c),
            borderWidth: 1,
        }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
            legend: {{ display: false }},
            tooltip: {{ callbacks: {{
                label: ctx => ctx.parsed.y + ' contribuyente' + (ctx.parsed.y !== 1 ? 's' : '')
            }} }}
        }},
        scales: {{
            x: {{ grid: {{ display: false }} }},
            y: {{ beginAtZero: true, ticks: {{ stepSize: 1 }} }}
        }}
    }}
}});
</script>
""" + _html_footer()


# ═══════════════════════════════════════════════════════════════════════
#  ORQUESTADOR
# ═══════════════════════════════════════════════════════════════════════

def exportar_reportes_html(
    consolidado: pd.DataFrame,
    categorias: pd.DataFrame,
    output_dir: str,
    fecha_inicial: Optional[pd.Timestamp] = None,
    fecha_final: Optional[pd.Timestamp] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> List[str]:
    """
    Genera reportes HTML individuales (uno por contribuyente) y un reporte general.

    Args:
        consolidado: DataFrame con datos procesados (salida de generar_reporte_control).
        categorias: DataFrame con 'Categoria' e 'Ingresos brutos' (escala).
        output_dir: Directorio donde guardar los HTMLs.
        fecha_inicial: Fecha de inicio del período (filtra el consolidado).
        fecha_final: Fecha de fin del período (filtra el consolidado).
        log_fn: Función de logging.

    Returns:
        Lista de rutas absolutas de los archivos generados.
    """
    os.makedirs(output_dir, exist_ok=True)
    individual_dir = os.path.join(output_dir, "reportes_individuales")
    os.makedirs(individual_dir, exist_ok=True)

    # Filtrar por rango de fechas si se proporcionó
    if fecha_inicial is not None and fecha_final is not None and 'Fecha' in consolidado.columns:
        fec_orig = consolidado['Fecha']
        # Asegurar datetime para comparación
        if not pd.api.types.is_datetime64_any_dtype(consolidado['Fecha']):
            consolidado['Fecha'] = pd.to_datetime(consolidado['Fecha'], errors='coerce')
        mask = (consolidado['Fecha'] >= fecha_inicial) & (consolidado['Fecha'] <= fecha_final)
        consolidado = consolidado[mask].copy()
        consolidado['Fecha'] = fec_orig  # restore original type
        if consolidado.empty:
            if log_fn:
                log_fn("No hay datos en el rango de fechas especificado para reportes HTML.")
            return []

    fecha_desde_str = fecha_inicial.strftime('%d/%m/%Y') if fecha_inicial is not None else ''
    fecha_hasta_str = fecha_final.strftime('%d/%m/%Y') if fecha_final is not None else ''

    # Get unique clients
    if 'Cliente' not in consolidado.columns or consolidado.empty:
        if log_fn:
            log_fn("No hay datos de contribuyentes para generar reportes HTML.")
        return []

    unique_clients = consolidado[['Cliente', 'Fin CUIT']].drop_duplicates()
    rutas_generadas: List[str] = []
    todos_los_datos: List[Dict[str, Any]] = []

    for _, row in unique_clients.iterrows():
        cliente = str(row['Cliente'])
        cuit = str(int(row['Fin CUIT'])) if pd.notna(row['Fin CUIT']) else ""

        # Sanitize filename
        safe_name = re.sub(r'[^\w\-]', '_', cliente)[:80]
        safe_cuit = re.sub(r'[^\d]', '', cuit)[:11]
        filename = f"{safe_cuit}_{safe_name}.html" if safe_cuit else f"{safe_name}.html"

        datos = preparar_datos_individuales(consolidado, categorias, cliente, cuit)
        datos["fecha_desde"] = fecha_desde_str
        datos["fecha_hasta"] = fecha_hasta_str
        datos["archivo_html"] = filename  # para vínculo desde el reporte general
        todos_los_datos.append(datos)
        filepath = os.path.join(individual_dir, filename)

        try:
            html_content = generar_html_individual(datos)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            rutas_generadas.append(filepath)
            if log_fn:
                log_fn(f"Reporte individual generado: {filename}")
        except Exception as e:
            if log_fn:
                log_fn(f"Error generando reporte para {cliente}: {e}")

    # General report
    if todos_los_datos:
        general_path = os.path.join(output_dir, "reporte_general.html")
        try:
            html_general = generar_html_general(todos_los_datos)
            with open(general_path, 'w', encoding='utf-8') as f:
                f.write(html_general)
            rutas_generadas.append(general_path)
            if log_fn:
                log_fn(f"Reporte general generado: {general_path}")
        except Exception as e:
            if log_fn:
                log_fn(f"Error generando reporte general: {e}")

    return rutas_generadas
