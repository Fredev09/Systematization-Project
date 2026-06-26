# Limitaciones del modelo EAV (Dynamic Forms)

## ¿Qué es EAV?

El sistema de Dynamic Forms implementa un modelo **Entity-Attribute-Value (EAV)** para
permitir la creación dinámica de formularios sin migraciones. En lugar de tablas fijas
como `Producto(id, nombre, precio, stock)` se usan 4 tablas:

- `Formulario` → define un tipo de registro (ej: "Productos")
- `Campo` → define un atributo (ej: "nombre", "precio")
- `Registro` → una fila concreta (ej: "Vestido Floral")
- `ValorCampo` → el valor de un atributo para un registro

Cada valor vive en una fila separada de `ValorCampo`, lo que permite flexibilidad
total pero introduce limitaciones de rendimiento y consulta.

---

## 1. Consultas lentas identificadas

### 1.1 Filtrado por múltiples campos

```python
# LENTO: JOIN por cada campo filtrado
Registro.objects.filter(
    formulario=form,
    valores__campo=campo_nombre, valores__valor="Buscar",
    valores__campo=campo_stock, valores__valor__gte=5,
)
```

Cada filtro adicional agrega un `INNER JOIN` a `ValorCampo`. Con 4-5 filtros
la consulta puede tener 5+ JOINs.

**Solución actual**: `DynamicService.filtrar()` encadena filtros con subconsultas.
Alternativa: cargar todos los valores en memoria con `cargar_valores_mapa()` y
filtrar en Python (útil para conjuntos pequeños, <1000 registros).

### 1.2 Agregaciones (SUM, COUNT, GROUP BY)

```sql
-- Hipotético: sumar total de ventas agrupado por producto
SELECT vc2.valor, SUM(CAST(vc1.valor AS numeric))
FROM registros r
JOIN valores_campo vc1 ON vc1.registro_id = r.id  -- el campo 'total'
JOIN valores_campo vc2 ON vc2.registro_id = r.id  -- el campo 'producto'
WHERE r.formulario_id = X
  AND vc1.campo_id = A
  AND vc2.campo_id = B
GROUP BY vc2.valor;
```

Los CAST a numérico y los múltiples JOIN hacen que agregaciones como
`top()`, `sumar()` y agrupaciones sean **~5-10x más lentas** que en un
modelo relacional fijo.

**Solución actual**: `DynamicService.top()` y `sumar()` hacen la agregación
en Python después de cargar todos los valores. Esto funciona para catálogos
pequeños (<5000 registros) pero escala mal.

### 1.3 Búsqueda textual (LIKE / icontains)

```python
# Búsqueda en todos los campos de texto
Registro.objects.filter(
    valores__campo__in=campos_texto,
    valores__valor__icontains="texto"
).distinct()
```

`DISTINCT` y `LIKE %%` en múltiples campos es inherentemente lento,
especialmente sin índices textuales.

### 1.4 Count + carga de valores

```python
# Dos consultas donde una bastaría
total = DS.contar('Ventas')  # COUNT(*)
valores = DS.cargar_valores_mapa(registros)  # SELECT con JOIN
```

---

## 2. Limitaciones funcionales

### 2.1 Sin integridad referencial real

Las relaciones entre formularios (ej: `Ventas.producto → Productos`)
se implementan como campos tipo `relacion` que almacenan un ID en texto.
No hay `FOREIGN KEY` a nivel BD, por lo que:

- Un registro referenciado puede eliminarse sin advertencia
- Se pueden insertar IDs inválidos
- No hay `CASCADE` ni `PROTECT` automático

### 2.2 Tipos de datos débiles

Todos los valores se almacenan como `TextField` en `ValorCampo.valor`.
No hay validación de tipos a nivel BD:
- Los números se almacenan como strings
- Las fechas se almacenan como strings
- Los booleanos se almacenan como "Sí"/"No"

La conversión se hace en Python, lo que añade overhead y riesgo de errores.

### 2.3 Campos calculados en segundo pase

Los campos tipo `calculado` se evalúan después de guardar los valores
normales. Esto significa:

- No se pueden usar en validaciones del mismo paso
- Dependen del orden de evaluación (se evalúan secuencialmente)
- Si una fórmula depende de otro campo calculado, puede dar resultados
  inconsistentes si el orden no es el esperado

### 2.4 Sin transacciones entre hooks y creador

Aunque el hook post_crear se ejecuta dentro de `transaction.atomic()`,
el `Registro` ya fue creado. Si el hook falla, el registro queda huérfano
(la transacción hace rollback, así que esto es seguro en teoría, pero
complejo de depurar).

### 2.5 Sin check constraints ni unique constraints compuestos

- La unicidad se verifica en Python (no a nivel BD)
- No se pueden definir unique constraints de múltiples campos

---

## 3. Recomendaciones de mitigación

### 3.1 Para conjuntos de datos grandes (>10,000 registros)

1. **Materializar vistas**: Crear tablas auxiliares que reflejen los datos
   EAV en formato relacional plano mediante triggers o jobs periódicos.
2. **Caché**: Cachear los resultados de `top()`, `sumar()` y `_stats_ventas()`
   con Redis o cache de Django.
3. **Índices**: Agregar índices compuestos en `ValorCampo(campo_id, valor)`.
   Esta migración debe hacerse manualmente (ver migración XX).

### 3.2 Para búsqueda textual

1. Usar `SearchVector` de PostgreSQL si está disponible.
2. Limitar la búsqueda a campos específicos en lugar de buscar en todos.
3. Agregar paginación con límites estrictos.

### 3.3 Para migración gradual a modelo híbrido

Para formularios de alto rendimiento (ej: Ventas), considerar un modelo
híbrido donde los campos críticos (fecha, total, producto_id) se almacenen
como columnas reales en `Registro`, y los atributos variables queden en EAV.

---

## 4. Comparación de rendimiento estimada

| Operación | Modelo relacional | Modelo EAV (actual) | Diferencia |
|-----------|-------------------|---------------------|------------|
| SELECT by PK | ~1ms | ~2ms | 2x |
| Listado 100 rows | ~3ms | ~15ms (con wrappers) | 5x |
| Filtro por 2 campos | ~5ms | ~25ms | 5x |
| SUM agrupado | ~10ms | ~80ms (en Python) | 8x |
| Búsqueda textual | ~15ms | ~50ms | 3x |
| Crear registro | ~5ms | ~20ms (con hooks) | 4x |

*Nota: Mediciones aproximadas con ~1000 registros. La diferencia crece
logarítmicamente con el tamaño del dataset.*

---

## 5. Próximos pasos para optimización

1. [ ] Agregar índices a `ValorCampo(campo_id, valor)` con varchar_pattern_ops
2. [ ] Implementar caché de 5 minutos para estadísticas del dashboard
3. [ ] Evaluar modelo híbrido para Ventas (campos críticos como columnas)
4. [ ] Agregar migración de datos desde legacy a dynamic_forms
5. [ ] Implementar validación de integridad referencial a nivel aplicación
6. [ ] Agregar límites de seguridad a queries (ej: max 1000 resultados en top)
7. [ ] Profiling con Django Debug Toolbar para identificar cuellos de botella
