import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('apps/platform/document_intelligence/templates/document_intelligence/document_upload.html', 'r', encoding='utf-8') as f:
    content = f.read()

old = '    {# Editor principal #}'
new_block = (
    '    {# --- Relations info box --- #}\n'
    '        <div class="card shadow-sm border-0 rounded-4 mb-3" style="border-left: 4px solid #6366f1 !important;">\n'
    '            <div class="card-body py-3 px-4">\n'
    '                <div class="d-flex align-items-start gap-3">\n'
    '                    <div style="font-size: 1.5rem; line-height: 1;">&#128279;</div>\n'
    '                    <div>\n'
    '                        <strong class="d-block mb-1">Relaciones entre formularios</strong>\n'
    '                        <p class="text-muted small mb-0">\n'
    '                            La inteligencia artificial no crea relaciones autom&aacute;ticamente para evitar errores en los datos.\n'
    '                            Si alg&uacute;n campo debe relacionarse con otro formulario\n'
    '                            (Clientes, Productos, Almacenes, etc.), puedes configurarlo desde el\n'
    '                            editor de campos despu&eacute;s de crear el formulario.\n'
    '                        </p>\n'
    '                    </div>\n'
    '                </div>\n'
    '            </div>\n'
    '        </div>\n'
    '\n'
    '    {# Editor principal #}'
)

if old in content:
    content = content.replace(old, new_block, 1)
    with open('apps/platform/document_intelligence/templates/document_intelligence/document_upload.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: Added relations info box to template')
else:
    print('FAILED: old string not found')
    idx = content.find('Editor principal')
    if idx >= 0:
        start = max(0, idx - 10)
        print(f'Context: {repr(content[start:idx+30])}')
