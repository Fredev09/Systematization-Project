"""
Audit script: trace validation for form 90
"""
import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
django.setup()

from apps.platform.dynamic_forms.models import Formulario, Campo, ImportLog, Registro, ValorCampo
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

formulario = Formulario.objects.get(id=90)
campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by('orden'))

print("=== FORMULARIO ===")
print(f"id={formulario.id} nombre={formulario.nombre}")
print()

print("=== CAMPOS ===")
for c in campos:
    print(f"  {c.nombre} | tipo={c.tipo} | obligatorio={c.obligatorio} | unico={c.unico} | formulario_destino_id={c.formulario_destino_id}")
print()

# Check ImportLog for this form
logs = ImportLog.objects.filter(formulario_id=90).order_by('-id')[:5]
print(f"=== IMPORT LOGS ({len(logs)}) ===")
for l in logs:
    rj = l.resultado_json or {}
    errs = rj.get('errores', []) if isinstance(rj, dict) else []
    print(f"id={l.id} file={l.file_name} rows={l.total_rows} creados={l.creados} errors={l.errores_count}")
    if errs and len(errs) > 0:
        print(f"  First 3 errors: {errs[:3]}")
    print(f"  resultado_json keys: {list(rj.keys())[:10] if isinstance(rj, dict) else 'not dict'}")
    print()

# Check existing registros
regs = Registro.objects.filter(formulario_id=90).order_by('-fecha_creacion')[:10]
print(f"=== REGISTROS ({len(regs)}) ===")
for r in regs:
    print(f"  id={r.id} fecha={r.fecha_creacion}")
print()

# Simulate validation for 55 sample rows with values 1-55
print("=== SIMULATE VALIDATION ===")
# Build valores_dict for a typical row
# The headers from the form
headers = [c.nombre for c in campos]
print(f"Headers: {headers}")

# Sample row data (same shape as Excel row)
sample_values = {
    'SKU (Único)': 'TEST-001',
    'Nombre Producto': 'Test Product',
    'Precio Público': '100',
    'Stock Actual': '50',
    'Fecha de Ingreso': '2026-01-01',
    'Activo (Booleano)': 'Sí',
    'Email de Contacto': 'test@test.com',
    'URL Ficha': 'http://test.com',
    'Teléfono de Soporte': '3001234567',
    'Descripción Larga': 'test description',
    'Categoría': 'Blusa',
    'ID Relación Almacén': '1',
    'Proveedor Oficial': 'Test Proveedor',
}

# Run validacion for the sample row
print("\n--- Row with 'ID Relacion Almacen' = '1' ---")
errors = DS.validar_completo(formulario, sample_values)
print(f"Errors: {errors}")
print()

# Check which validation step fails
print("=== STEP-BY-STEP VALIDATION ===")

# Step 1: obligatorios
print("\n--- 1. OBLIGATORIOS ---")
err_obl = DS.validar_campos_obligatorios(formulario, sample_values)
print(f"Result: {err_obl}")
print(f"PASS: {len(err_obl) == 0}")

# Step 2: tipos
print("\n--- 2. TIPOS ---")
err_tip = DS.validar_tipos(formulario, sample_values)
print(f"Result: {err_tip}")
print(f"PASS: {len(err_tip) == 0}")
if err_tip:
    for e in err_tip:
        print(f"  ERROR: {e}")

# Step 3: unicidad (for preview, excluir_registro_id=None)
print("\n--- 3. UNICIDAD ---")
err_uni = []
for campo in campos:
    if campo.unico:
        valor = sample_values.get(campo.nombre, '').strip()
        if valor:
            try:
                DS.validar_unicidad(formulario, campo.nombre, valor, None)
                print(f"  UNICITY OK: {campo.nombre}='{valor}'")
            except Exception as e:
                err_uni.append(str(e))
print(f"Result: {err_uni}")
print(f"PASS: {len(err_uni) == 0}")

# Also test with values 6-55 (where many would fail the Registro.id check)
print("\n\n=== TEST VALUES 1 THROUGH 55 ===")
fail_counts = {}
for i in range(1, 56):
    vals = dict(sample_values)
    vals['ID Relación Almacén'] = str(i)
    errors = DS.validar_completo(formulario, vals)
    if errors:
        for e in errors:
            fail_counts[e] = fail_counts.get(e, 0) + 1

print(f"\n--- ERROR BREAKDOWN ({sum(fail_counts.values())} total errors across 55 rows) ---")
for err, count in sorted(fail_counts.items(), key=lambda x: -x[1]):
    print(f"  [{count:2d}x] {err}")

# Show first 10 rejected rows
print("\n\n=== FIRST 10 REJECTED ROWS ===")
rejected = 0
for i in range(1, 56):
    vals = dict(sample_values)
    vals['ID Relación Almacén'] = str(i)
    errors = DS.validar_completo(formulario, vals)
    if errors and rejected < 10:
        print(f"\n--- Row {i} (ID Relación Almacén = '{i}') ---")
        print(f"valores_dict: {vals}")
        print(f"Errors: {errors}")
        rejected += 1
