"""
ExcelImportService — Importación de Excel a Dynamic Forms.

Reutiliza al máximo las validaciones y creación del sistema existente:
- DynamicService.validar_completo() para pre-validación sin escribir BD.
- DynamicService.crear() para escritura con hooks, fórmulas y validaciones.
- DynamicService.actualizar() para modo upsert.
- openpyxl para lectura de archivos .xlsx (dependencia ya instalada).

Flujo típico:
    1. leer_excel(archivo) → encabezados, filas
    2. detectar_columnas(encabezados, formulario) → mapeo sugerido
    3. previsualizar(formulario, filas, mapeo) → preview_rows
    4. importar(formulario, filas_validas, mapeo, usuario) → resultado
"""

import logging
import re
from django.db import transaction
from openpyxl import load_workbook

from .services_dynamic import DynamicService as DS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalización de nombres de columna
# ---------------------------------------------------------------------------

def _normalizar(nombre):
    """Normaliza un string para comparación flexible: minúsculas, sin acentos, sin espacios extra."""
    nombre = nombre.lower().strip()
    nombre = re.sub(r'[áàäâã]', 'a', nombre)
    nombre = re.sub(r'[éèëê]', 'e', nombre)
    nombre = re.sub(r'[íìïî]', 'i', nombre)
    nombre = re.sub(r'[óòöôõ]', 'o', nombre)
    nombre = re.sub(r'[úùüû]', 'u', nombre)
    nombre = re.sub(r'[ñ]', 'n', nombre)
    nombre = re.sub(r'[^a-z0-9_]', '', nombre)
    return nombre


# ---------------------------------------------------------------------------
# Fase 2: Lectura de Excel
# ---------------------------------------------------------------------------


def leer_excel(archivo):
    """
    Lee un archivo .xlsx y retorna sus datos como estructura plana.

    Args:
        archivo: UploadedFile o BytesIO con contenido .xlsx

    Returns:
        (encabezados, filas)
        - encabezados: list[str] — nombres de columna de la primera fila
        - filas: list[dict] — cada fila como {nombre_columna: valor_str}

    Raises:
        ValueError: Si el archivo no es válido o está vacío.
    """
    try:
        wb = load_workbook(archivo, read_only=True, data_only=True)
    except Exception as e:
        raise ValueError(f'No se pudo leer el archivo Excel: {e}')

    ws = wb.active
    if ws is None:
        raise ValueError('El archivo Excel no tiene hojas de cálculo.')

    filas_iter = ws.iter_rows(values_only=True)

    try:
        raw_headers = next(filas_iter)
    except StopIteration:
        raise ValueError('El archivo Excel está vacío.')

    if not raw_headers:
        raise ValueError('La primera fila (encabezados) está vacía.')

    encabezados = [str(h).strip() if h is not None else '' for h in raw_headers]

    # Ignorar columnas sin encabezado
    indices_validos = [i for i, h in enumerate(encabezados) if h]

    if not indices_validos:
        raise ValueError('No se encontraron encabezados de columna en la primera fila.')

    encabezados_filtrados = [encabezados[i] for i in indices_validos]

    filas = []
    for row in filas_iter:
        # Omitir filas completamente vacías
        if all(cell is None or str(cell).strip() == '' for cell in row):
            continue
        fila_dict = {}
        for i in indices_validos:
            val = row[i] if i < len(row) else None
            if val is not None:
                # Convertir números a string sin decimales si es entero
                if isinstance(val, float) and val == int(val):
                    val = str(int(val))
                else:
                    val = str(val).strip()
            fila_dict[encabezados[i]] = val if val else ''
        filas.append(fila_dict)

    wb.close()

    if not filas:
        raise ValueError('El archivo Excel no contiene datos (solo encabezados).')

    return encabezados_filtrados, filas


# ---------------------------------------------------------------------------
# Fase 4: Detección y corrección de mapeo de columnas
# ---------------------------------------------------------------------------


def detectar_columnas(encabezados, formulario):
    """
    Detecta automáticamente la correspondencia entre columnas del Excel
    y campos del formulario, usando normalización de nombres.

    Args:
        encabezados: list[str] — nombres de columna del Excel
        formulario: Formulario — formulario destino

    Returns:
        dict {indice_columna: nombre_campo}
        - indice_columna: int (posición en encabezados)
        - nombre_campo: str (nombre del campo en el formulario)
    """
    campos_activos = {c.nombre for c in DS._campos_activos(formulario)}
    campos_normalizados = {_normalizar(c): c for c in campos_activos}

    mapeo = {}
    for idx, encabezado in enumerate(encabezados):
        normalizado = _normalizar(encabezado)
        if normalizado in campos_normalizados:
            mapeo[idx] = campos_normalizados[normalizado]
        else:
            # Búsqueda parcial: si el encabezado contiene el nombre del campo
            for n_norm, n_orig in campos_normalizados.items():
                if normalizado in n_norm or n_norm in normalizado:
                    mapeo[idx] = n_orig
                    break

    return mapeo


def construir_mapeo_completo(encabezados, formulario, mapeo_usuario=None):
    """
    Construye el mapeo definitivo combinando detección automática
    y correcciones del usuario.

    Args:
        encabezados: list[str]
        formulario: Formulario
        mapeo_usuario: dict {indice: nombre_campo} opcional con correcciones

    Returns:
        dict {indice_columna: nombre_campo}
        list[str] — campos del formulario sin mapear
    """
    auto_mapeo = detectar_columnas(encabezados, formulario)

    if mapeo_usuario:
        auto_mapeo.update(mapeo_usuario)

    campos_activos = {c.nombre for c in DS._campos_activos(formulario)
                      if c.tipo not in ('calculado', 'imagen', 'archivo')}

    mapeados = set(auto_mapeo.values())
    sin_mapear = [c for c in campos_activos if c not in mapeados]

    return auto_mapeo, sin_mapear


# ---------------------------------------------------------------------------
# Fase 3: Pre-visualización (validación sin escribir BD)
# ---------------------------------------------------------------------------


def previsualizar(formulario, encabezados, filas, mapeo):
    """
    Valida todas las filas del Excel contra el formulario destino
    SIN escribir en la base de datos.

    Args:
        formulario: Formulario — formulario destino
        encabezados: list[str] — nombres de columna originales del Excel
        filas: list[dict] — datos del Excel (cada fila como dict)
        mapeo: dict {indice_columna: nombre_campo}

    Returns:
        list[dict] — una entrada por fila:
            - fila_idx: int (0-based)
            - valores: dict {nombre_campo: valor}
            - valida: bool
            - errores: list[str]
    """
    resultados = []

    for fila_idx, fila in enumerate(filas):
        valores_dict = {}

        for col_idx, nombre_campo in mapeo.items():
            if col_idx < len(encabezados):
                enc = encabezados[col_idx]
                valores_dict[nombre_campo] = fila.get(enc, '')

        # Validar con el servicio existente
        errores = DS.validar_completo(formulario, valores_dict)

        resultados.append({
            'fila_idx': fila_idx,
            'valores': dict(valores_dict),
            'valida': len(errores) == 0,
            'errores': errores,
        })

    return resultados


# ---------------------------------------------------------------------------
# Fase 5: Importación definitiva
# ---------------------------------------------------------------------------


def importar(formulario, preview_rows, usuario=None):
    """
    Importa las filas pre-validadas usando DynamicService.crear().

    Args:
        formulario: Formulario — formulario destino
        preview_rows: list[dict] — resultado de previsualizar()
        usuario: User opcional

    Returns:
        dict con:
            - creados: int — registros creados exitosamente
            - errores: list[dict] — filas que fallaron
                - fila_idx: int
                - valores: dict
                - error: str
    """
    creados = 0
    errores = []

    for row in preview_rows:
        try:
            with transaction.atomic():
                registro = DS.crear(
                    formulario.nombre,
                    row['valores'],
                    usuario=usuario,
                )
                creados += 1
        except Exception as e:
            logger.exception(f'Error importando fila #{row["fila_idx"] + 1}: {e}')
            errores.append({
                'fila_idx': row['fila_idx'],
                'valores': row['valores'],
                'error': str(e),
            })

    return {
        'creados': creados,
        'errores': errores,
        'total': len(preview_rows),
    }
