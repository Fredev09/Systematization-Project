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
                    var fields = self.serialize(containerId);
                    if (fields.length === 0) {
                        e.preventDefault();
                        alert('Debe haber al menos un campo.');
                        return;
                    }
                    // Set JSON hidden input
                    var jsonInput = form.querySelector('[data-fields-json]') ||
                        document.getElementById('fields_json');
                    if (jsonInput) {
                        jsonInput.value = JSON.stringify(fields);
                    }
                    if (state.onSerialize) {
                        state.onSerialize(fields);
                    }
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
            var state = this.containers[containerId];
            if (!state) return [];

            var fields = [];
            var container = state.container;

            container.querySelectorAll('.campo-fila').forEach(function (fila) {
                var name = (fila.querySelector('[name="campo_nombre"]') ||
                           fila.querySelector('.field-name'))?.value?.trim() || '';
                if (!name) return;

                var tipoSelect = fila.querySelector('[name="campo_tipo"]') ||
                                fila.querySelector('.field-type');
                var type = tipoSelect ? tipoSelect.value : 'texto';

                var optionsInput = fila.querySelector('[name="campo_opciones"]') ||
                                  fila.querySelector('.field-options');
                var optionsVal = optionsInput ? optionsInput.value : '';
                var options = optionsVal ? optionsVal.split(',').map(function (s) {
                    return s.trim();
                }).filter(function (s) { return s; }) : null;

                // Get checkbox values (handles both name= and class= approaches)
                var checked = function (sel) {
                    var el = fila.querySelector(sel);
                    return el ? el.checked : false;
                };

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
            });

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

        _actualizarVisibilidad: function (container) {
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
