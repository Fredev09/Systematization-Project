"""
auto_audit.py — Autoauditoría del flujo de importación automática.

Simula 5 escenarios y verifica que la decisión (saltar mapeo vs mostrar)
sea correcta en cada caso.

Escenarios:
  1. 100% automático — todas las columnas mapeadas con alta confianza
  2. Campo obligatorio faltante — un campo required sin correspondencia
  3. Conflicto entre columnas — dos campos muy similares
  4. Baja confianza global — fuzzy matches con < 92%
  5. Columnas opcionales extra — Excel tiene columnas sin relación con el form

Uso: python manage.py test apps.platform.dynamic_forms.tests_auto_audit
     O: python -c "from apps.platform.dynamic_forms.tests_auto_audit import *; test_escenarios()"
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ======================================================================
# Mock objects to test without DB
# ======================================================================


@dataclass
class MockCampo:
    nombre: str
    tipo: str = 'texto'
    obligatorio: bool = False
    activo: bool = True
    orden: int = 0
    identificador_principal: bool = False


class MockCamposQuerySet(list):
    """Simula QuerySet de campos activos."""
    def filter(self, **kwargs):
        result = list(self)
        for k, v in kwargs.items():
            if k == 'activo':
                result = [c for c in result if c.activo == v]
            elif k == 'obligatorio':
                result = [c for c in result if c.obligatorio == v]
        return MockCamposQuerySet(result)

    def count(self):
        return len(self)

    def order_by(self, *args):
        return self


@dataclass
class MockFormulario:
    id: int = 1
    nombre: str = 'TestForm'
    _campos: list = field(default_factory=list)

    @property
    def campos(self):
        return MockCamposQuerySet(self._campos)


# ======================================================================
# Import local modules
# ======================================================================

from .column_matching import ColumnMatchResult, ColumnMatcher
from .auto_mapping import AutoMappingAnalyzer, MappingSummary, CONFIANZA_AUTO, CONFIANZA_REVIEW


def _make_result(
    idx: int,
    name: str,
    matched_to: Optional[str] = None,
    confidence: float = 0.0,
    method: Optional[str] = None,
    conflicts: Optional[list[str]] = None,
    suggestion: Optional[str] = None,
    alternatives: Optional[list] = None,
) -> ColumnMatchResult:
    """Helper to create test ColumnMatchResult."""
    return ColumnMatchResult(
        column_index=idx,
        column_name=name,
        matched_to=matched_to,
        confidence=confidence,
        method=method,
        conflicts=conflicts or [],
        suggestion=suggestion,
        alternatives=alternatives or [],
    )


# ======================================================================
# Escenarios de prueba
# ======================================================================


def test_escenario_1_100_auto() -> dict:
    """
    Escenario 1: 100% automático.
    Excel: [Nombre, Precio, Stock]
    Form:  [Nombre*, Precio*, Stock]
    Todos los campos tienen match exacto → debe saltar a preview.
    """
    print("\n" + "=" * 70)
    print("ESCENARIO 1: 100% AUTOMÁTICO")
    print("=" * 70)

    campos = MockCamposQuerySet([
        MockCampo(nombre='Nombre', tipo='texto', obligatorio=True),
        MockCampo(nombre='Precio', tipo='numero', obligatorio=True),
        MockCampo(nombre='Stock', tipo='numero', obligatorio=False),
    ])
    formulario = MockFormulario(id=1, nombre='Productos', _campos=campos)
    encabezados = ['Nombre', 'Precio', 'Stock']

    # Simular resultados de ColumnMatcher (phase 1)
    match_results = [
        _make_result(0, 'Nombre', 'Nombre', 1.0, 'exact'),
        _make_result(1, 'Precio', 'Precio', 1.0, 'exact'),
        _make_result(2, 'Stock', 'Stock', 1.0, 'exact'),
    ]

    analyzer = AutoMappingAnalyzer()
    summary = analyzer.analyze(match_results)
    summary.conflictos_presentes = False
    summary.campos_obligatorios_faltantes = []
    summary = analyzer.decidir_accion(summary, formulario, campos)

    print(f"  Auto={summary.auto}, Review={summary.review}, Manual={summary.manual}")
    print(f"  Confianza promedio: {summary.confianza_promedio:.1%}")
    print(f"  Puede saltar: {summary.puede_saltar_mapeo}")
    print(f"  Motivos: {summary.motivo_no_saltar or 'NINGUNO'}")

    assert summary.puede_saltar_mapeo == True, "FALLO: Deberia saltar a preview"
    assert summary.motivo_no_saltar == [], "FALLO: No deberia tener motivos para no saltar"
    print("  [OK] CORRECTO: Salta a preview")

    return {
        'escenario': '100% automático',
        'puede_saltar': summary.puede_saltar_mapeo,
        'motivos': summary.motivo_no_saltar,
        'correcto': True,
    }


def test_escenario_2_obligatorio_faltante() -> dict:
    """
    Escenario 2: Campo obligatorio faltante.
    Excel: [Nombre, Precio]
    Form:  [Nombre*, Precio*, Stock*]
    Stock es obligatorio y no está en el Excel → NO debe saltar.
    """
    print("\n" + "=" * 70)
    print("ESCENARIO 2: CAMPO OBLIGATORIO FALTANTE")
    print("=" * 70)

    campos = MockCamposQuerySet([
        MockCampo(nombre='Nombre', tipo='texto', obligatorio=True),
        MockCampo(nombre='Precio', tipo='numero', obligatorio=True),
        MockCampo(nombre='Stock', tipo='numero', obligatorio=True),
    ])
    formulario = MockFormulario(id=1, nombre='Productos', _campos=campos)
    encabezados = ['Nombre', 'Precio']  # Stock NO está en el Excel

    match_results = [
        _make_result(0, 'Nombre', 'Nombre', 1.0, 'exact'),
        _make_result(1, 'Precio', 'Precio', 1.0, 'exact'),
    ]

    analyzer = AutoMappingAnalyzer()
    summary = analyzer.analyze(match_results)
    summary.conflictos_presentes = False
    summary.campos_obligatorios_faltantes = ['Stock']
    summary = analyzer.decidir_accion(summary, formulario, campos)

    print(f"  Auto={summary.auto}, Review={summary.review}, Manual={summary.manual}")
    print(f"  Confianza promedio: {summary.confianza_promedio:.1%}")
    print(f"  Puede saltar: {summary.puede_saltar_mapeo}")
    print(f"  Motivos: {summary.motivo_no_saltar}")

    assert summary.puede_saltar_mapeo == False, "FALLO: NO deberia saltar (obligatorio faltante)"
    assert any('Stock' in m for m in summary.motivo_no_saltar), "FALLO: Deberia mencionar Stock"
    print("  [OK] CORRECTO: NO salta -- falta campo obligatorio Stock")

    return {
        'escenario': 'Obligatorio faltante',
        'puede_saltar': summary.puede_saltar_mapeo,
        'motivos': summary.motivo_no_saltar,
        'correcto': True,
    }


def test_escenario_3_conflicto() -> dict:
    """
    Escenario 3: Conflicto entre columnas.
    Excel: [Nombre, PrecioVenta, PrecioCompra]
    Form:  [Nombre*, PrecioVenta, PrecioCompra]
    PrecioVenta y PrecioCompra son muy similares → conflicto → NO saltar.
    """
    print("\n" + "=" * 70)
    print("ESCENARIO 3: CONFLICTO ENTRE COLUMNAS")
    print("=" * 70)

    campos = MockCamposQuerySet([
        MockCampo(nombre='Nombre', tipo='texto', obligatorio=True),
        MockCampo(nombre='PrecioVenta', tipo='numero', obligatorio=False),
        MockCampo(nombre='PrecioCompra', tipo='numero', obligatorio=False),
    ])
    formulario = MockFormulario(id=1, nombre='Productos', _campos=campos)
    encabezados = ['Nombre', 'PrecioVenta', 'PrecioCompra']

    match_results = [
        _make_result(0, 'Nombre', 'Nombre', 1.0, 'exact'),
        _make_result(1, 'PrecioVenta', 'PrecioVenta', 0.95, 'normalized',
                     conflicts=['PrecioCompra']),
        _make_result(2, 'PrecioCompra', 'PrecioCompra', 0.95, 'normalized',
                     conflicts=['PrecioVenta']),
    ]

    analyzer = AutoMappingAnalyzer()
    summary = analyzer.analyze(match_results)
    summary.conflictos_presentes = True  # Hay conflictos
    summary.campos_obligatorios_faltantes = []
    summary = analyzer.decidir_accion(summary, formulario, campos)

    print(f"  Auto={summary.auto}, Review={summary.review}, Manual={summary.manual}")
    print(f"  Confianza promedio: {summary.confianza_promedio:.1%}")
    print(f"  Conflicto presente: {summary.conflictos_presentes}")
    print(f"  Puede saltar: {summary.puede_saltar_mapeo}")
    print(f"  Motivos: {summary.motivo_no_saltar}")

    assert summary.puede_saltar_mapeo == False, "FALLO: NO deberia saltar (conflictos)"
    print("  [OK] CORRECTO: NO salta -- hay conflictos entre PrecioVenta/PrecioCompra")

    return {
        'escenario': 'Conflicto entre columnas',
        'puede_saltar': summary.puede_saltar_mapeo,
        'motivos': summary.motivo_no_saltar,
        'correcto': True,
    }


def test_escenario_4_baja_confianza() -> dict:
    """
    Escenario 4: Baja confianza global.
    Excel: [Nom, Prec, Stk]
    Form:  [Nombre*, Precio*, Stock]
    Todos fuzzy match con confianza ~85% → confianza global < 92% → NO saltar.
    """
    print("\n" + "=" * 70)
    print("ESCENARIO 4: BAJA CONFIANZA GLOBAL")
    print("=" * 70)

    campos = MockCamposQuerySet([
        MockCampo(nombre='Nombre', tipo='texto', obligatorio=True),
        MockCampo(nombre='Precio', tipo='numero', obligatorio=True),
        MockCampo(nombre='Stock', tipo='numero', obligatorio=False),
    ])
    formulario = MockFormulario(id=1, nombre='Productos', _campos=campos)
    encabezados = ['Nom', 'Prec', 'Stk']

    match_results = [
        _make_result(0, 'Nom', 'Nombre', 0.86, 'fuzzy_review',
                     suggestion='Nombre', alternatives=[('Nombre', 0.86)]),
        _make_result(1, 'Prec', 'Precio', 0.85, 'fuzzy_review',
                     suggestion='Precio', alternatives=[('Precio', 0.85)]),
        _make_result(2, 'Stk', 'Stock', 0.88, 'fuzzy_review',
                     suggestion='Stock', alternatives=[('Stock', 0.88)]),
    ]

    analyzer = AutoMappingAnalyzer()
    summary = analyzer.analyze(match_results)
    summary.conflictos_presentes = False
    summary.campos_obligatorios_faltantes = []
    summary = analyzer.decidir_accion(summary, formulario, campos)

    print(f"  Auto={summary.auto}, Review={summary.review}, Manual={summary.manual}")
    print(f"  Confianza promedio: {summary.confianza_promedio:.1%}")
    print(f"  Puede saltar: {summary.puede_saltar_mapeo}")
    print(f"  Motivos: {summary.motivo_no_saltar}")

    assert summary.puede_saltar_mapeo == False, "FALLO: NO deberia saltar (baja confianza)"
    conf_pct = summary.confianza_promedio * 100
    assert any(str(int(conf_pct)) in m for m in summary.motivo_no_saltar), \
        f"FALLO: Deberia mencionar la confianza {conf_pct:.0f}%"
    print(f"  [OK] CORRECTO: NO salta -- confianza {summary.confianza_promedio:.1%} < 92%")

    return {
        'escenario': 'Baja confianza global',
        'puede_saltar': summary.puede_saltar_mapeo,
        'motivos': summary.motivo_no_saltar,
        'correcto': True,
    }


def test_escenario_5_columnas_extra_opcionales() -> dict:
    """
    Escenario 5: Columnas opcionales extra en el Excel.
    Excel: [Nombre, Precio, Stock, Notas, Comentarios]
    Form:  [Nombre*, Precio*, Stock]
    'Notas' y 'Comentarios' no existen en el formulario → son extras.
    Como todos los obligatorios están mapeados con alta confianza →
    DEBE saltar a preview (las columnas extra se ignoran).
    """
    print("\n" + "=" * 70)
    print("ESCENARIO 5: COLUMNAS EXTRAS OPCIONALES EN EXCEL")
    print("=" * 70)

    campos = MockCamposQuerySet([
        MockCampo(nombre='Nombre', tipo='texto', obligatorio=True),
        MockCampo(nombre='Precio', tipo='numero', obligatorio=True),
        MockCampo(nombre='Stock', tipo='numero', obligatorio=False),
    ])
    formulario = MockFormulario(id=1, nombre='Productos', _campos=campos)
    encabezados = ['Nombre', 'Precio', 'Stock', 'Notas', 'Comentarios']

    match_results = [
        _make_result(0, 'Nombre', 'Nombre', 1.0, 'exact'),
        _make_result(1, 'Precio', 'Precio', 1.0, 'exact'),
        _make_result(2, 'Stock', 'Stock', 1.0, 'exact'),
        # 'Notas' y 'Comentarios' no tienen matched_to, suggestion ni alternatives
        _make_result(3, 'Notas', None, 0.0, None),
        _make_result(4, 'Comentarios', None, 0.0, None),
    ]

    analyzer = AutoMappingAnalyzer()
    summary = analyzer.analyze(match_results)
    summary.conflictos_presentes = False
    summary.campos_obligatorios_faltantes = []
    summary = analyzer.decidir_accion(summary, formulario, campos)

    print(f"  Auto={summary.auto}, Review={summary.review}, Manual={summary.manual}")
    print(f"  Columnas extra del Excel: {summary.columnas_extra}")
    print(f"  Confianza promedio: {summary.confianza_promedio:.1%}")
    print(f"  Puede saltar: {summary.puede_saltar_mapeo}")
    print(f"  Motivos: {summary.motivo_no_saltar or 'NINGUNO'}")

    assert summary.puede_saltar_mapeo == True, \
        "FALLO: DEBERIA saltar a preview (solo columnas extra, no afectan)"
    assert summary.columnas_extra == 2, \
        f"FALLO: Deberia haber 2 columnas extra (Notas, Comentarios), hay {summary.columnas_extra}"
    print("  [OK] CORRECTO: Salta a preview -- las columnas extra se ignoran")

    return {
        'escenario': 'Columnas extra opcionales',
        'puede_saltar': summary.puede_saltar_mapeo,
        'motivos': summary.motivo_no_saltar,
        'columnas_extra': summary.columnas_extra,
        'correcto': True,
    }


# ======================================================================
# Ejecutor
# ======================================================================


def test_escenarios() -> list[dict]:
    """Ejecuta los 5 escenarios y retorta resultados."""
    resultados = []

    escenarios = [
        test_escenario_1_100_auto,
        test_escenario_2_obligatorio_faltante,
        test_escenario_3_conflicto,
        test_escenario_4_baja_confianza,
        test_escenario_5_columnas_extra_opcionales,
    ]

    for test_fn in escenarios:
        try:
            resultado = test_fn()
            resultado['exito'] = True
        except AssertionError as e:
            print(f"\n  [FALLO] {e}")
            resultado = {
                'escenario': test_fn.__name__,
                'exito': False,
                'error': str(e),
            }
        except Exception as e:
            print(f"\n  [ERROR] {e}")
            resultado = {
                'escenario': test_fn.__name__,
                'exito': False,
                'error': str(e),
            }
        resultados.append(resultado)

    # Resumen
    print("\n" + "=" * 70)
    print("RESUMEN DE AUTO-AUDITORIA")
    print("=" * 70)
    exitosos = sum(1 for r in resultados if r.get('exito'))
    for r in resultados:
        status = "[OK]" if r.get('exito') else "[FAIL]"
        print(f"  {status} {r.get('escenario', '?')}")
    print(f"\n  {exitosos}/{len(resultados)} escenarios correctos")

    return resultados


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    test_escenarios()
