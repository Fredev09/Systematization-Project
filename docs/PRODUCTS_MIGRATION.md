# Products Migration: Legacy → Dynamic Forms

## Architecture

### Origin System
- **Modelos**: `apps/legacy/productos/models.py` (`Producto`, `Categoria`, `MovimientoInventario`)
- **Vistas legacy**: `apps/legacy/productos/views.py` (16 funciones, 741 líneas)
- **Vistas activas**: `apps/legacy/productos/views_dynamic.py` (8 vistas, 1362 líneas)
- **Wrappers**: `apps/legacy/productos/wrappers.py` (`DynamicProductWrapper`, `DynamicMovimientoInventarioWrapper`, `DynamicVentaWrapper`, `DynamicClienteWrapper`)

### Target System
- **DynamicService**: `apps/platform/dynamic_forms/services_dynamic.py` (~20 métodos estáticos públicos)
- **Formularios base**: `Productos` (12 campos), `MovimientosInventario` (7 campos)
- **Campos Productos**: nombre(texto), precio(numero), stock(numero), categoria(lista), descripcion(textarea), sku(texto), talla(lista), color(texto), imagen(imagen), imagen_url(url), stock_minimo(numero), activo(booleano)
- **Campos MovimientosInventario**: producto(relacion), tipo(lista), cantidad(numero), motivo(lista), stock_anterior(numero), stock_nuevo(numero), observacion(textarea)

### Mapping Producto legacy → Dynamic

| Campo legacy | Campo dinámico | Notas |
|---|---|---|
| `nombre` | `nombre` | Directo |
| `categoria` | `categoria` | Se sincronizan nombres desde `Categoria` legacy |
| `talla` | `talla` | Normalizado: 'Única' → 'Unica' |
| `color` | `color` | Directo |
| `precio` | `precio` | Convertido a string |
| `stock` | `stock` | Convertido a string |
| `imagen` | `imagen_url` | Se usa URL de Cloudinary (no se migran archivos) |
| `imagen_url` | `imagen_url` | Directo |
| - | `sku` | `LEGACY-{id}` para trazabilidad |
| - | `descripcion` | Vacío (no existía en legacy) |
| - | `stock_minimo` | Desde `ConfiguracionTienda.stock_minimo_alerta` |
| - | `activo` | Siempre 'Sí' |

### Mapping MovimientoInventario legacy → Dynamic

| Campo legacy | Campo dinámico | Notas |
|---|---|---|
| `producto_id` | `producto` | ID del Registro dinámico |
| `tipo` | `tipo` | Directo |
| `motivo` | `motivo` | Se agrega 'Inventario inicial' a opciones |
| `cantidad` | `cantidad` | Convertido a string |
| `stock_anterior` | `stock_anterior` | Convertido a string |
| `stock_nuevo` | `stock_nuevo` | Convertido a string |
| `observacion` | `observacion` | Incluye referencia al ID legacy |

## Strategy

### Identity tracing
Cada producto migrado se identifica mediante el campo `sku` con formato `LEGACY-{id}` donde `{id}` es el `Producto.id` legacy. Esto permite:
- **Primera ejecución**: crea productos dinámicos con SKU=LEGACY-{id}
- **Re-ejecución**: busca por SKU → actualiza en vez de duplicar

### Idempotency
- Productos: `ValorCampo.objects.get(campo=sku_campo, valor='LEGACY-{id}')` → si existe, actualiza; si no, crea
- Categorías: `dict.fromkeys(opciones_actuales + categorias_legacy + ['Otros'])` → siempre el mismo resultado
- Movimientos iniciales: verifica si ya existe un MovimientoInventario con `motivo='Inventario inicial'` para ese producto

### Error handling
- Errores individuales no abortan la migración completa
- Cada producto se procesa en un bloque try/except
- Estadísticas al final: creados, actualizados, errores, omitidos

## Management Command

**Archivo**: `apps/platform/dynamic_forms/management/commands/migrar_productos_dynamic.py`

### Uso

```bash
# Migrar productos (crea los que faltan, actualiza los existentes)
python manage.py migrar_productos_dynamic

# Validar sin escribir
python manage.py migrar_productos_dynamic --dry-run

# Re-migrar forzado (elimina y recrea productos existentes)
python manage.py migrar_productos_dynamic --force
```

### Flujo interno (5 pasos)

```
[1/5] Verificar requisitos
  - Formulario Productos existe
  - Formulario MovimientosInventario existe
  - Todos los campos requeridos existen
  - Hay productos legacy que migrar

[2/5] Sincronizar categorías
  - Lee Categoria.objects.all() → nombres
  - Merge con opciones dinámicas actuales + 'Otros'
  - Actualiza Campo.opciones si cambió

[3/5] Migrar productos (por cada producto legacy)
  - Construye valores_dict con mapeo
  - Busca por SKU=LEGACY-{id}
  - Si existe → DS.actualizar()
  - Si no → DS.crear()

[3b/5] Crear movimientos iniciales faltantes
  - Detecta productos migrados sin MovimientoInventario inicial
  - Crea movimiento tipo 'Entrada' con motivo 'Inventario inicial'
  - Agrega 'Inventario inicial' a opciones de motivo si no existe

[4/5] Validaciones post-migración
  - Cobertura: productos migrados / productos legacy
  - Productos sin migrar
  - Categorías en uso vs disponibles
  - Productos sin imagen

[5/5] Reporte final
```

## Rollback

Si la migración falla parcialmente:

1. **Productos ya creados**: se pueden identificar por `sku` empezando con `LEGACY-`. Para revertir:
   ```python
   from apps.platform.dynamic_forms.models import *
   Campo.objects.get(formulario__nombre='Productos', nombre='sku')
   ValorCampo.objects.filter(campo=campo_sku, valor__startswith='LEGACY-').delete()
   ```
2. **Categorías**: las opciones modificadas en `Campo.opciones` se pueden restaurar desde el seed original
3. **Movimientos iniciales**: se eliminan junto con los Registros de productos (cascade)
4. **Datos legacy**: NO se modifican — `Producto`, `Categoria`, `MovimientoInventario` permanecen intactos

## Pasos de ejecución para migración completa

```bash
# 0. Sincronizar esquema (solo una vez)
python manage.py migrate dynamic_forms 0004
python manage.py migrate dynamic_forms 0005

# 1. Sembrar formularios base
python manage.py sembrar_formularios_base

# 2. Asignar hook de ventas
python manage.py asignar_hook_ventas

# 3. Validar en seco
python manage.py migrar_productos_dynamic --dry-run

# 4. Migrar productos
python manage.py migrar_productos_dynamic

# 5. Verificar idempotencia (segunda ejecución debe reportar 0 creados)
python manage.py migrar_productos_dynamic
```

## Validaciones realizadas

| Validación | Cómo |
|---|---|
| Cobertura de migración | `total_migrados / total_legacy * 100` |
| Idempotencia | Segunda ejecución: 0 creados, N actualizados |
| Categorías en uso vs disponibles | `set(valores_usados) - set(opciones_dinamicas)` |
| Productos sin imagen | Registros sin `imagen` ni `imagen_url` |
| SKUs no-legacy | Productos con `sku` propio (no `LEGACY-`) |
| Movimientos iniciales | Verifica existencia de MovimientoInventario por producto |

## Limitaciones

- **Imágenes**: No se migran archivos físicos. Las imágenes de Cloudinary se referencian por URL en `imagen_url`. El campo `imagen` (subida de archivo) queda vacío para productos migrados.
- **Venta FK**: El modelo `Venta` legacy tiene `ForeignKey(Producto, on_delete=PROTECT)` que impide eliminar la tabla `Producto` hasta que se migren las ventas. La migración de productos **no toca** este constraint.
- **MovimientoInventario FK**: Tiene FK a `Producto` (CASCADE). Los movimientos iniciales creados por la migración usan el sistema dinámico (`Registro`/`ValorCampo`), no el modelo legacy.
- **Tallas con acentos**: Los productos legacy tienen `talla='Única'` (con acento), pero las opciones dinámicas usan `'Unica'` (sin acento). La migración normaliza automáticamente.
- **`mostrar_agotados_catalogo`**: Esta lógica solo existe en `catalogo_publico` legacy. Al migrar el catálogo, debe replicarse en la vista dinámica.

## Riesgos encontrados y resueltos

| Riesgo | Estado | Solución |
|---|---|---|
| `creado_por_id` NOT NULL bloquea seed | ✅ Resuelto | Migración 0005 (RunSQL) |
| Columna `unico` no existe | ✅ Resuelto | Migración 0004 |
| Cloudinary no soporta `.path()` | ✅ Resuelto | Usar `imagen_final_url` en `imagen_url` |
| Talla 'Única' no coincide con opciones | ✅ Resuelto | Normalización de acentos |
| 'Inventario inicial' no está en motivo opciones | ✅ Resuelto | Sincronización automática en paso 3b |

## Trabajo pendiente (después de migración de productos)

### Inmediato
1. Migrar `catalogo_publico` → vista dinámica (Fase 6)
2. Migrar categorías (`agregar_categoria`, `crear_categoria`) → gestión de opciones dinámicas
3. Eliminar código legacy huérfano (Fase 7)

### Mediano plazo
4. Migrar modelo `Venta` legacy → Dynamic Forms (eliminar FK a `Producto`)
5. Migrar `Cliente` legacy → Dynamic Forms
6. Eliminar modelos legacy: `Categoria`, `Producto`, `MovimientoInventario`, `Venta`, `Cliente`
7. Eliminar `apps/legacy/` completo o reestructurar

### Largo plazo
8. Evaluar rendimiento de queries EAV vs legado
9. Migrar templates legacy a nueva interfaz si es necesario
10. Eliminar wrappers si los templates se actualizan para consumir EAV directamente
