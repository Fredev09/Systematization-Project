/**
 * field-editor.js — ÚNICO editor de campos reutilizable por toda la plataforma.
 *
 * Este módulo maneja TODAS las interacciones del editor de campos:
 *   - Agregar / eliminar filas
 *   - Cambiar tipo → mostrar/ocultar containers (opciones, fórmula, relación)
 *   - Drag & drop (SortableJS) para reordenar
 *   - Serializar campos a JSON para envío
 *   - Actualizar contador de campos
 *
 * Cómo usar:
 *   1. Incluir este script después de SortableJS (si se necesita drag & drop)
 *   2. El contenedor debe tener id="camposContainer" o pasar containerId
 *   3. Los controles de tipo deben tener clase "campo-tipo"
 *   4. Llamar a FieldEditor.init(containerId, options)
 *
 * Ejemplo:
 *   FieldEditor.init('camposContainer', {
 *       sortable: true,
 *       onSerialize: function(fields) { ... },
 *       tiposDisponibles: {...}
 *   });
 *
 * @version 2.0.0 — Unified Field Editor
 */
(function (window, document) {
    'use strict';

    var FieldEditor = {
        version: '2.0.0',
        containers: {},
        _sortableInstances: {},

        /**
         * Inicializa el editor en un contenedor.
         * @param {string} containerId - ID del contenedor de campos
         * @param {Object} options - Opciones
         * @param {boolean} options.sortable - Habilitar drag & drop
         * @param {Function} options.onSerialize - Callback al serializar
         * @param {Object} options.tiposDisponibles - {codigo: "Código", ...}
         * @param {string} options.countBadgeId - ID del badge para contar campos
         * @param {string} options.identifierSelectId - ID del select de identificador
         */
        init: function (containerId, options) {
            options = options || {};
            var container = document.getElementById(containerId);
            if (!container) {
                console.warn('[FieldEditor] Container not found:', containerId);
                return;
            }

            var state = {
                container: container,
                containerId: containerId,
                sortable: options.sortable || false,
                onSerialize: options.onSerialize || null,
                tiposDisponibles: options.tiposDisponibles || null,
                countBadgeId: options.countBadgeId || 'field-count',
                identifierSelectId: options.identifierSelectId || 'identifier_field',
                index: container.querySelectorAll('.campo-fila').length
            };

            this.containers[containerId] = state;

            // Bind event listeners (delegated)
            if (!this._globalBound) {
                this._bindGlobalEvents();
                this._globalBound = true;
            }

            // Initialize visibility for existing rows
            this._actualizarVisibilidad(container);

            // Initialize sortable
            if (options.sortable && typeof Sortable !== 'undefined') {
                this._initSortable(containerId, state);
            }

            // Initialize add button
            var addBtn = container.closest('[data-editor]')
                ? container.closest('[data-editor]').querySelector('[data-action="add-field"]')
                : document.querySelector('[data-action="add-field"]');
            // Fallback: look for #agregarCampo
            if (!addBtn) {
                addBtn = document.getElementById('agregarCampo');
            }

            if (addBtn && !addBtn._fieldEditorBound) {
                var self = this;
                addBtn.addEventListener('click', function () {
                    self.addField(containerId);
                });
                addBtn._fieldEditorBound = true;
            }

            // Bind form submit serialization
            var form = container.closest('form');
            if (form && !form._fieldEditorBound) {
                form.addEventListener('submit', function (e) {
                    console.log('[FE] submit HANDLER START');
                    console.time('[FE] total_handler');

                    // ── Step 1: serialize ──
                    console.time('[FE] serialize');
                    var fields;
                    try {
                        fields = self.serialize(containerId);
                    } catch (serErr) {
                        console.error('[FE] serialize() CRASHED:', serErr);
                        console.error('[FE] stack:', serErr.stack);
                        fields = [];
                    }
                    console.timeEnd('[FE] serialize');
                    console.log('[FE] fields.length=' + (fields ? fields.length : 'null'));

                    if (!fields || fields.length === 0) {
                        console.log('[FE] ⚠️ fields empty — calling preventDefault');
                        if (fields && fields.length === 0) {
                            console.log('[FE] fields was empty array (not null)');
                        }
                        e.preventDefault();
                        alert('Debe haber al menos un campo.');
                        return;
                    }

                    // ── Step 2: JSON encode ──
                    console.time('[FE] JSON.stringify');
                    var jsonStr;
                    try {
                        jsonStr = JSON.stringify(fields);
                    } catch (jsonErr) {
                        console.error('[FE] JSON.stringify CRASHED:', jsonErr);
                        console.log('[FE] fields sample:', fields.slice(0, 2));
                        e.preventDefault();
                        alert('Error al serializar campos: ' + jsonErr.message);
                        return;
                    }
                    console.timeEnd('[FE] JSON.stringify');
                    console.log('[FE] jsonStr length=' + jsonStr.length);
                    console.log('[FE] jsonStr starts with: ' + jsonStr.substring(0, 100));

                    // ── Step 3: find hidden input ──
                    console.time('[FE] set_value');
                    var jsonInput = form.querySelector('[data-fields-json]') ||
                        document.getElementById('fields_json');
                    if (!jsonInput) {
                        console.error('[FE] ⚠️ jsonInput NOT FOUND');
                        console.error('[FE] querySelector [data-fields-json]:', form.querySelector('[data-fields-json]'));
                        console.error('[FE] getElementById fields_json:', document.getElementById('fields_json'));
                    } else {
                        console.log('[FE] jsonInput found: name=' + jsonInput.name + ' id=' + jsonInput.id);
                        jsonInput.value = jsonStr;
                        console.log('[FE] jsonInput.value length after set: ' + jsonInput.value.length);
                    }
                    console.timeEnd('[FE] set_value');

                    // ── Step 4: onSerialize callback ──
                    if (state.onSerialize) {
                        console.log('[FE] calling onSerialize callback');
                        state.onSerialize(fields);
                    }

                    // ── Step 5: HTML5 Validation Audit ──
                    console.log('');
                    console.log('╔═══════════════════════════════════════');
                    console.log('║ [FE-HTML5] VALIDATION AUDIT');
                    console.log('╚═══════════════════════════════════════');

                    // 5a: form.checkValidity()
                    var cv = form.checkValidity();
                    console.log('[FE-HTML5] form.checkValidity() = ' + cv);

                    // 5b: form.reportValidity() — muestra burbujas si hay inválidos
                    var rv = form.reportValidity();
                    console.log('[FE-HTML5] form.reportValidity() = ' + rv);
                    console.log('[FE-HTML5] (si ves burbujas de validación arriba, ese es el problema)');

                    // 5c: Listar todo elemento required que esté vacío
                    var requiredEmpty = [];
                    form.querySelectorAll('[required]').forEach(function(el) {
                        var val = '';
                        if (el.type === 'checkbox' || el.type === 'radio') {
                            val = el.checked ? '(checked)' : '';
                        } else {
                            val = (el.value || '').trim();
                        }
                        if (!val) {
                            var rect = el.getBoundingClientRect();
                            var visible = rect.width > 0 && rect.height > 0;
                            requiredEmpty.push({
                                name: el.name || el.id || '(unnamed)',
                                type: el.type || el.tagName,
                                visible: visible,
                                rect: (rect.width|0)+'x'+(rect.height|0)+' @('+(rect.left|0)+','+(rect.top|0)+')',
                                tag: el.tagName + (el.id ? '#'+el.id : '')
                            });
                        }
                    });
                    if (requiredEmpty.length > 0) {
                        console.log('[FE-HTML5] ⚠️ REQUIRED but EMPTY (' + requiredEmpty.length + '):');
                        requiredEmpty.forEach(function(r) {
                            console.log('  - name="' + r.name + '" type=' + r.type +
                                        ' visible=' + r.visible + ' size=' + r.rect + ' ' + r.tag);
                        });
                    } else {
                        console.log('[FE-HTML5] ✅ All required fields have values');
                    }

                    // 5d: Listar required que NO son visibles
                    var requiredHidden = [];
                    form.querySelectorAll('[required]').forEach(function(el) {
                        var rect = el.getBoundingClientRect();
                        var style = window.getComputedStyle(el);
                        var isHidden = rect.width === 0 || rect.height === 0 ||
                                      style.display === 'none' || style.visibility === 'hidden' ||
                                      el.type === 'hidden';
                        if (isHidden) {
                            requiredHidden.push({
                                name: el.name || el.id || '(unnamed)',
                                tag: el.tagName + (el.id ? '#'+el.id : ''),
                                display: style.display,
                                visibility: style.visibility,
                                rect: (rect.width|0)+'x'+(rect.height|0)
                            });
                        }
                    });
                    if (requiredHidden.length > 0) {
                        console.log('[FE-HTML5] ⚠️ REQUIRED but HIDDEN (' + requiredHidden.length + '):');
                        requiredHidden.forEach(function(r) {
                            console.log('  - name="' + r.name + '" ' + r.tag +
                                        ' display=' + r.display + ' visibility=' + r.visibility +
                                        ' rect=' + r.rect);
                        });
                    } else {
                        console.log('[FE-HTML5] ✅ No hidden required fields');
                    }

                    // 5e: Listar disabled inputs
                    var disabledInputs = form.querySelectorAll('input:disabled, select:disabled, textarea:disabled, button:disabled');
                    if (disabledInputs.length > 0) {
                        console.log('[FE-HTML5] ⚠️ DISABLED inputs (' + disabledInputs.length + '):');
                        disabledInputs.forEach(function(el) {
                            console.log('  - name="' + (el.name||el.id||'(unnamed)') + '" tag=' + el.tagName + (el.id ? '#'+el.id : ''));
                        });
                    } else {
                        console.log('[FE-HTML5] ✅ No disabled inputs');
                    }

                    // 5f: Verificar botón submit
                    var submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
                    if (submitBtn) {
                        console.log('[FE-HTML5] Submit button: tag=' + submitBtn.tagName +
                                    ' type=' + submitBtn.getAttribute('type') +
                                    ' form=' + (submitBtn.form ? submitBtn.form.id || '(has form)' : 'NULL') +
                                    ' disabled=' + submitBtn.disabled +
                                    ' name=' + (submitBtn.name || '(none)'));
                        // button.form === form ?
                        if (submitBtn.form !== form) {
                            console.log('[FE-HTML5] ❌ submitBtn.form !== form!');
                            console.log('[FE-HTML5]    submitBtn.form.id=' + (submitBtn.form ? submitBtn.form.id : 'null'));
                            console.log('[FE-HTML5]    form.id=' + form.id);
                        } else {
                            console.log('[FE-HTML5] ✅ submitBtn.form === form');
                        }
                    } else {
                        console.log('[FE-HTML5] ⚠️ NO submit button found in form!');
                    }

                    // 5g: Buscar formularios anidados
                    var nestedForms = form.querySelectorAll('form');
                    if (nestedForms.length > 0) {
                        console.log('[FE-HTML5] ❌ NESTED FORMS inside form (' + nestedForms.length + '):');
                        nestedForms.forEach(function(f) {
                            console.log('  - form id=' + (f.id||'(none)') + ' action=' + (f.action||'(self)'));
                        });
                    } else {
                        console.log('[FE-HTML5] ✅ No nested forms');
                    }

                    // 5h: Verificar atributos del formulario
                    console.log('[FE-HTML5] form.method=' + form.method);
                    console.log('[FE-HTML5] form.action=' + (form.getAttribute('action') || '(empty/self)'));
                    console.log('[FE-HTML5] form.enctype=' + (form.enctype || '(default)'));
                    console.log('[FE-HTML5] form.novalidate=' + (form.noValidate ? 'true' : 'false'));

                    // 5i: Listar todos los invalid events en el form
                    var invalidElements = form.querySelectorAll(':invalid');
                    if (invalidElements.length > 0) {
                        console.log('[FE-HTML5] ⚠️ :invalid elements (' + invalidElements.length + '):');
                        invalidElements.forEach(function(el) {
                            var rect = el.getBoundingClientRect();
                            var visible = rect.width > 0 && rect.height > 0;
                            console.log('  - name="' + (el.name||el.id||'(unnamed)') + '" tag=' + el.tagName +
                                        ' type=' + (el.type||'') +
                                        ' value="' + ((el.value||'').substring(0, 30)) + '"' +
                                        ' visible=' + visible +
                                        ' validationMessage="' + (el.validationMessage||'') + '"');
                        });
                    } else {
                        console.log('[FE-HTML5] ✅ No :invalid elements');
                    }

                    // 5j: Contar todos los form elements
                    var allControls = form.elements;
                    console.log('[FE-HTML5] form.elements.length=' + (allControls ? allControls.length : 'N/A'));
                    console.log('[FE-HTML5] END audit');

                    console.timeEnd('[FE] total_handler');
                    console.log('[FE] handler done — form will submit (defaultPrevented=' + e.defaultPrevented + ')');
                    console.log('[FE] ⬆ Si ves burbujas de validación HTML5 arriba, el navegador CANCELÓ el envío');
                });
                form._fieldEditorBound = true;
            }

            return this;
        },

        /**
         * Agrega una nueva fila de campo al contenedor.
         */
        addField: function (containerId) {
            var state = this.containers[containerId];
            if (!state) return;

            var container = state.container;
            var idx = state.index++;
            var html = this._buildFieldRow(idx, state);
            container.insertAdjacentHTML('beforeend', html);
            this._actualizarVisibilidad(container);
            this._updateCount(containerId);

            // Re-init sortable for new row
            if (state.sortable && this._sortableInstances[containerId]) {
                this._sortableInstances[containerId].destroy();
                this._initSortable(containerId, state);
            }
        },

        /**
         * Elimina una fila de campo con animación.
         */
        removeField: function (btn, containerId) {
            var state = this.containers[containerId];
            if (!state) return;

            var fila = btn.closest('.campo-fila');
            var container = state.container;
            if (container.querySelectorAll('.campo-fila').length <= 1) {
                alert('Debe haber al menos un campo.');
                return;
            }
            fila.style.transition = 'all 0.2s ease';
            fila.style.transform = 'scale(0.9)';
            fila.style.opacity = '0';
            var self = this;
            setTimeout(function () {
                fila.remove();
                self._updateCount(containerId);
            }, 200);
        },

        /**
         * Serializa todos los campos del contenedor a un array de objetos.
         * @returns {Array<Object>}
         */
        serialize: function (containerId) {
            console.time('[FE-ser] total');
            console.log('[FE-ser] ENTER containerId=' + containerId);

            var state = this.containers[containerId];
            if (!state) {
                console.warn('[FE-ser] ⚠️ state NOT FOUND for containerId=' + containerId);
                console.log('[FE-ser] available containers:', Object.keys(this.containers));
                console.timeEnd('[FE-ser] total');
                return [];
            }
            console.log('[FE-ser] state OK | containerId=' + containerId);

            var fields = [];
            var container = state.container;
            console.log('[FE-ser] container.id=' + (container.id || '(none)'));

            var filas = container.querySelectorAll('.campo-fila');
            console.log('[FE-ser] .campo-fila found: ' + filas.length);
            if (filas.length === 0) {
                console.warn('[FE-ser] ⚠️ NO .campo-fila elements in container');
                console.log('[FE-ser] container innerHTML (first 500):', container.innerHTML.substring(0, 500));
            }

            var _iterStart = performance.now();
            filas.forEach(function (fila, idx) {
                var _filaStart = performance.now();

                // ── Get name ──
                var nameInput = fila.querySelector('[name="campo_nombre"]');
                var nameInput2 = fila.querySelector('.field-name');
                var name = (nameInput || nameInput2)?.value?.trim() || '';
                if (idx === 0) {
                    console.log('[FE-ser] fila[0] nameInput=' + (nameInput ? 'FOUND' : 'null') +
                                ' nameInput2=' + (nameInput2 ? 'FOUND' : 'null') +
                                ' name="' + name + '"');
                }
                if (!name) {
                    if (idx === 0) console.log('[FE-ser] fila[0] SKIPPED (empty name)');
                    return;
                }

                // ── Get type ──
                var tipoSelect = fila.querySelector('[name="campo_tipo"]') ||
                                fila.querySelector('.field-type');
                var type = tipoSelect ? tipoSelect.value : 'texto';

                // ── Get options ──
                var optionsInput = fila.querySelector('[name="campo_opciones"]') ||
                                  fila.querySelector('.field-options');
                var optionsVal = optionsInput ? optionsInput.value : '';
                var options = optionsVal ? optionsVal.split(',').map(function (s) {
                    return s.trim();
                }).filter(function (s) { return s; }) : null;

                // ── Checkbox values ──
                var checked = function (sel) {
                    var el = fila.querySelector(sel);
                    return el ? el.checked : false;
                };

                // ── Build field object ──
                var field = {
                    name: name,
                    type: type,
                    required: checked('[name="campo_obligatorio"]') || checked('.field-required'),
                    unique: checked('[name="campo_unico"]') || checked('.field-unique'),
                    is_identifier: checked('[name="campo_identificador_principal"]') || checked('.field-identifier'),
                    visible: fila.querySelector('[name="campo_visible"]')
                        ? fila.querySelector('[name="campo_visible"]').checked
                        : (fila.querySelector('.field-visible') ? fila.querySelector('.field-visible').checked : true),
                    order: Array.from(container.children).indexOf(fila),
                    default_value: (fila.querySelector('[name="campo_default"]') ||
                                   fila.querySelector('.field-default'))?.value?.trim() || '',
                    max_length: (fila.querySelector('[name="campo_max_length"]') ||
                                fila.querySelector('.field-maxlength'))?.value?.trim() || '',
                    options: options,
                    descripcion: (fila.querySelector('[name="campo_descripcion"]'))?.value?.trim() || '',
                    formulario_destino_id: (fila.querySelector('[name="campo_formulario_destino"]'))?.value || null,
                    formula: (fila.querySelector('[name="campo_formula"]'))?.value?.trim() || null
                };

                fields.push(field);

                if (idx === 0) {
                    console.log('[FE-ser] fila[0] OK | name="' + name + '" type=' + type +
                                ' time=' + (performance.now() - _filaStart).toFixed(1) + 'ms');
                }
                if (idx === filas.length - 1 && filas.length > 1) {
                    console.log('[FE-ser] fila[' + idx + '] OK | name="' + name + '" type=' + type +
                                ' time=' + (performance.now() - _filaStart).toFixed(1) + 'ms');
                }
            });

            console.log('[FE-ser] DONE | fields.length=' + fields.length +
                        ' iter_time=' + (performance.now() - _iterStart).toFixed(1) + 'ms');
            console.timeEnd('[FE-ser] total');
            return fields;
        },

        // ── Internal methods ──

        _bindGlobalEvents: function () {
            var self = this;

            // Type change → visibility update
            document.addEventListener('change', function (e) {
                var target = e.target;
                if (target.classList.contains('campo-tipo') || target.classList.contains('field-type')) {
                    var container = target.closest('[id]')?.closest('#camposContainer') ||
                                    target.closest('#fields-container') ||
                                    target.closest('#camposContainer');
                    if (container) {
                        // Find which container this belongs to
                        for (var cid in self.containers) {
                            if (self.containers[cid].container === container ||
                                self.containers[cid].container.contains(target)) {
                                self._actualizarVisibilidad(container);
                                break;
                            }
                        }
                    }
                }
            });

            // Remove field button (delegated)
            document.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-action="remove-field"], .eliminar-campo');
                if (!btn) return;
                var container = btn.closest('#camposContainer') ||
                                btn.closest('#fields-container');
                if (!container) return;
                for (var cid in self.containers) {
                    if (self.containers[cid].container === container ||
                        self.containers[cid].container.contains(btn)) {
                        self.removeField(btn, cid);
                        break;
                    }
                }
            });
        },

        _buildFieldRow: function (idx, state) {
            var tipos = state.tiposDisponibles;
            var typeOptions = '';

            if (tipos) {
                // Use provided tipo map
                for (var code in tipos) {
                    typeOptions += '<option value="' + code + '">' + tipos[code] + '</option>\n';
                }
            } else {
                // Default types (complete set)
                typeOptions = [
                    {v: 'texto', l: 'Texto'}, {v: 'numero', l: 'Número'}, {v: 'moneda', l: 'Moneda'},
                    {v: 'porcentaje', l: 'Porcentaje'}, {v: 'fecha', l: 'Fecha'}, {v: 'hora', l: 'Hora'},
                    {v: 'fecha_hora', l: 'Fecha y hora'}, {v: 'booleano', l: 'Booleano'},
                    {v: 'lista', l: 'Lista desplegable'}, {v: 'email', l: 'Correo electrónico'},
                    {v: 'url', l: 'URL'}, {v: 'telefono', l: 'Teléfono'},
                    {v: 'documento', l: 'Documento'}, {v: 'codigo', l: 'Código'},
                    {v: 'codigo_barras', l: 'Código barras'}, {v: 'qr', l: 'QR'},
                    {v: 'textarea', l: 'Texto largo'}, {v: 'imagen', l: 'Imagen'},
                    {v: 'archivo', l: 'Archivo'}, {v: 'relacion', l: 'Relación'},
                    {v: 'calculado', l: 'Calculado'}, {v: 'color', l: 'Color'},
                    {v: 'ip', l: 'IP'}, {v: 'uuid', l: 'UUID'},
                    {v: 'geolocalizacion', l: 'Geolocalización'}, {v: 'duracion', l: 'Duración'},
                    {v: 'estado', l: 'Estado'}, {v: 'categoria', l: 'Categoría'},
                    {v: 'tags', l: 'Tags'}
                ].map(function (t) {
                    return '<option value="' + t.v + '">' + t.l + '</option>';
                }).join('\n');
            }

            return [
                '<div class="campo-fila row g-2 mb-2" data-index="' + idx + '">',
                '<div class="col-12 col-md-3">',
                '<input type="text" name="campo_nombre" class="form-control form-control-sm field-name" placeholder="Nombre del campo" required>',
                '</div>',
                '<div class="col-6 col-md-2">',
                '<select name="campo_tipo" class="form-select form-select-sm campo-tipo field-type">',
                typeOptions,
                '</select>',
                '<div class="campo-tipo-descripcion small text-muted mt-1" style="font-size:0.7rem; line-height:1.3; min-height:1.2rem;"></div>',
                '</div>',
                '<div class="col-6 col-md-2">',
                '<div class="form-check mt-2"><input type="checkbox" name="campo_obligatorio" class="form-check-input field-required" id="req_' + idx + '"><label class="form-check-label small" for="req_' + idx + '">Req</label></div>',
                '<div class="form-check mt-1"><input type="checkbox" name="campo_unico" class="form-check-input field-unique" id="uniq_' + idx + '"><label class="form-check-label small" for="uniq_' + idx + '">Único</label></div>',
                '<div class="form-check mt-1"><input type="checkbox" name="campo_visible" class="form-check-input field-visible" id="vis_' + idx + '" checked><label class="form-check-label small" for="vis_' + idx + '">Visible</label></div>',
                '</div>',
                '<div class="col-6 col-md-2">',
                '<input type="number" name="campo_orden" class="form-control form-control-sm" placeholder="Orden" min="0" value="0">',
                '<input type="number" name="campo_max_length" class="form-control form-control-sm field-maxlength mt-1" placeholder="Max">',
                '<input type="text" name="campo_default" class="form-control form-control-sm field-default mt-1" placeholder="Valor defecto">',
                '</div>',
                '<div class="col-10 col-md-2 campo-opciones-container" style="display:none;">',
                '<input type="text" name="campo_opciones" class="form-control form-control-sm field-options" placeholder="Op1, Op2, Op3">',
                '</div>',
                '<div class="col-10 col-md-2 campo-relacion-container" style="display:none;">',
                '<select name="campo_formulario_destino" class="form-select form-select-sm">',
                '<option value="">-- Formulario relacionado --</option>',
                '</select>',
                '</div>',
                '<div class="col-10 col-md-2 campo-formula-container" style="display:none;">',
                '<input type="text" name="campo_formula" class="form-control form-control-sm" placeholder="Ej: cantidad * precio">',
                '</div>',
                '<div class="col-10 col-md-2">',
                '<div class="form-check mt-2"><input type="checkbox" name="campo_identificador_principal" class="form-check-input field-identifier" id="id_' + idx + '"><label class="form-check-label small" for="id_' + idx + '">ID principal</label></div>',
                '</div>',
                '<div class="col-10 col-md-2" style="display:none;">',
                '<textarea name="campo_descripcion" class="form-control form-control-sm" placeholder="Descripción" rows="1"></textarea>',
                '</div>',
                '<div class="col-2 col-md-1 d-flex align-items-center">',
                '<button type="button" class="action-btn danger-btn eliminar-campo" data-action="remove-field" title="Eliminar campo"><i class="fas fa-times"></i></button>',
                '</div>',
                '</div>'
            ].join('\n');
        },

        _getTipoDescripcion: function (tipo) {
            var descs = {
                'texto': '',
                'textarea': 'Para observaciones largas.',
                'codigo': 'Para identificadores de negocio como PROD-001 o CLI-123.',
                'email': 'Correos electrónicos válidos.',
                'url': 'Enlaces web.',
                'telefono': 'Números telefónicos.',
                'documento': 'Números de identificación.',
                'numero': 'Cantidades numéricas.',
                'moneda': 'Para valores monetarios.',
                'porcentaje': 'Valores entre 0 y 100.',
                'duracion': 'Intervalos de tiempo.',
                'fecha': 'Para fechas en cualquiera de los formatos soportados.',
                'hora': 'Para horas del día.',
                'fecha_hora': 'Combinación de fecha y hora.',
                'booleano': 'Solo acepta Sí/No, True/False o 1/0.',
                'estado': 'Estado actual del registro.',
                'categoria': 'Clasificaciones.',
                'tags': 'Etiquetas o palabras clave.',
                'lista': 'Utilice este tipo cuando existan varias opciones posibles.',
                'codigo_barras': 'Códigos de barras EAN/UPC.',
                'qr': 'Códigos QR.',
                'color': 'Códigos de color.',
                'ip': 'Direcciones IP.',
                'uuid': 'Identificadores únicos.',
                'geolocalizacion': 'Coordenadas geográficas.',
                'imagen': 'Archivos de imagen.',
                'archivo': 'Archivos adjuntos.',
                'relacion': 'Conexión con otro formulario.',
                'calculado': 'Valor calculado automáticamente.'
            };
            return descs[tipo] || '';
        },

        _actualizarVisibilidad: function (container) {
            var self = this;
            container.querySelectorAll('.campo-fila').forEach(function (fila) {
                var select = fila.querySelector('.campo-tipo') || fila.querySelector('.field-type');
                if (!select) return;
                var val = select.value;

                // Toggle conditional containers
                var toggle = function (sel, show) {
                    var el = fila.querySelector(sel);
                    if (el) el.style.display = show ? '' : 'none';
                };

                toggle('.campo-opciones-container', val === 'lista');
                toggle('.campo-relacion-container', val === 'relacion');
                toggle('.campo-formula-container', val === 'calculado');

                // Update contextual description
                var descEl = fila.querySelector('.campo-tipo-descripcion');
                if (descEl) {
                    descEl.textContent = self._getTipoDescripcion(val);
                }

                // Calculated fields can't be required
                var reqCheck = fila.querySelector('[name="campo_obligatorio"]');
                if (reqCheck) {
                    var reqContainer = reqCheck.closest('.form-check');
                    if (reqContainer) {
                        if (val === 'calculado') {
                            reqCheck.checked = false;
                            reqContainer.style.display = 'none';
                        } else {
                            reqContainer.style.display = '';
                        }
                    }
                }
            });
        },

        _initSortable: function (containerId, state) {
            if (typeof Sortable === 'undefined') return;
            var self = this;
            this._sortableInstances[containerId] = new Sortable(state.container, {
                handle: '.drag-handle, .campo-fila',
                animation: 200,
                ghostClass: 'sortable-ghost',
                onEnd: function () {
                    self._updateCount(containerId);
                }
            });
        },

        _updateCount: function (containerId) {
            var state = this.containers[containerId];
            if (!state) return;
            var count = state.container.querySelectorAll('.campo-fila').length;
            var badge = document.getElementById(state.countBadgeId);
            if (badge) badge.textContent = count;
            // Update submit button text
            var form = state.container.closest('form');
            if (form) {
                var btn = form.querySelector('button[type="submit"]');
                if (btn) {
                    var baseText = btn.getAttribute('data-base-text') || 'Guardar';
                    btn.innerHTML = baseText + ' (' + count + ' campos)';
                }
            }
        }
    };

    // Export
    window.FieldEditor = FieldEditor;
})(window, document);
