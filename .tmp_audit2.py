"""
Audit: demonstrate validation behavior BEFORE the fix.

Simulates the OLD _validar_valor_campo for tipo=relacion
(without the formulario_destino_id guard) to show exactly
why 50 of 55 rows were rejected and 5 passed.
"""
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
django.setup()

from apps.platform.dynamic_forms.models import Formulario, Campo, Registro

formulario = Formulario.objects.get(id=90)
campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by('orden'))

# Find the relacion field
relacion_campo = next(c for c in campos if c.tipo == 'relacion')
print(f"Campo relacion: {relacion_campo.nombre}")
print(f"  formulario_destino_id = {relacion_campo.formulario_destino_id}")
print(f"  unico = {relacion_campo.unico}")
print(f"  obligatorio = {relacion_campo.obligatorio}")
print()

# Simulate the OLD validator behavior for relacion
def _old_validar_relacion(campo, valor_raw):
    """Simulates the validator BEFORE the fix: always checks Registro.id."""
    if valor_raw.isdigit():
        ref_id = int(valor_raw)
        if not Registro.objects.filter(id=ref_id).exists():
            return (None, f'El registro #{ref_id} referenciado en "{campo.nombre}" no existe.')
    return (valor_raw, None)

# Test values 1 through 55
print("=== OLD BEHAVIOR: Testing values 1-55 against Registro.id ===")
pass_count = 0
fail_count = 0
pass_values = []
fail_values = []
for i in range(1, 56):
    val = str(i)
    _, error = _old_validar_relacion(relacion_campo, val)
    if error:
        fail_count += 1
        fail_values.append(val)
    else:
        pass_count += 1
        pass_values.append(val)

print(f"PASS: {pass_count} (values: {pass_values})")
print(f"FAIL: {fail_count} (values: {fail_values})")
print()

# Check which Registro IDs exist
print("=== Checking which IDs exist as Registro ===")
existing_ids = set(Registro.objects.filter(id__gte=1, id__lte=55).values_list('id', flat=True))
print(f"Registros existentes con id 1-55: {sorted(existing_ids)}")
print(f"Cantidad: {len(existing_ids)}")
print()

# Show the exact validator code that was responsible
print("=== RESPONSIBLE CODE (BEFORE FIX) ===")
print(f"File: apps/platform/dynamic_forms/validators.py")
print(f"Function: _validar_valor_campo()")
print(f"Lines 346-351:")
print()
print(f"    if campo.tipo == 'relacion':")
print(f"        if valor_raw.isdigit():")
print(f"            ref_id = int(valor_raw)")
print(f"            if not Registro.objects.filter(id=ref_id).exists():")
print(f"                return None, 'El registro #...'")
print(f"        return valor_raw, None")
print()
print("The fix added: `if campo.formulario_destino_id and valor_raw.isdigit():`")
print("which skips the Registro.id check when formulario_destino is NULL.")
