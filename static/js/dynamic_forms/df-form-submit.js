/========================================================================
// df-form-submit.js — Formulario de envío con patrón HTML5
//
// Busca todos los <form data-df-submit> en la página y adjunta un
// handler al evento `submit` que:
//   1. Ejecuta form.checkValidity() — si inválido, no hace nada
//   2. Si válido: deshabilita botón, muestra spinner
//   3. try/catch captura cualquier excepción y restaura el botón
//   4. pageshow (bfcache) restaura botones al volver atrás
//   5. [DIAG] console.time / console.timeEnd por formulario
// ========================================================================

(function () {
    'use strict';

    var diag = '[DF-Submit]';

    // ------------------------------------------------------------------
    // Restaurar botón a su estado original
    // ------------------------------------------------------------------
    function restoreButton(btn) {
        btn.disabled = false;
        var original = btn.getAttribute('data-original-html');
        if (original) {
            btn.innerHTML = original;
        }
    }

    // ------------------------------------------------------------------
    // Poner botón en estado "cargando"
    // ------------------------------------------------------------------
    function setLoading(btn) {
        var text = btn.getAttribute('data-loading-text') || 'Procesando...';
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ' + text;
    }

    // ------------------------------------------------------------------
    // Inicializar un formulario
    // ------------------------------------------------------------------
    function initForm(form) {
        var btn = form.querySelector('button[type="submit"]');
        if (!btn) {
            console.warn(diag, 'Form sin botón submit:', form.id || form.className);
            return;
        }

        // Guardar HTML original para restauración
        btn.setAttribute('data-original-html', btn.innerHTML);

        var formId = form.id || 'form-' + Math.random().toString(36).slice(2, 7);

        form.addEventListener('submit', function (e) {
            // ---- Doble envío — ya está deshabilitado
            if (btn.disabled) {
                console.warn(diag, '[' + formId + '] Double submit blocked');
                e.preventDefault();
                return;
            }

            // ---- Validación HTML5 nativa
            if (!form.checkValidity()) {
                console.log(diag, '[' + formId + '] checkValidity() = false —', form.validationMessage);
                return; // El navegador muestra los mensajes nativos
            }

            console.log(diag, '[' + formId + '] checkValidity() = true, submitting');
            console.time(diag + ' [' + formId + '] submit → response');

            try {
                setLoading(btn);
            } catch (err) {
                console.error(diag, '[' + formId + '] Error en submit handler:', err);
                restoreButton(btn);
            }
        });
    }

    // ------------------------------------------------------------------
    // pageshow — restaurar botones al volver de bfcache (Back)
    // ------------------------------------------------------------------
    window.addEventListener('pageshow', function (e) {
        if (e.persisted) {
            console.log(diag, 'Page restored from bfcache, resetting all buttons');
            document.querySelectorAll('form[data-df-submit]').forEach(function (form) {
                var btn = form.querySelector('button[type="submit"]');
                if (btn) {
                    restoreButton(btn);
                }
            });
        }
    });

    // ------------------------------------------------------------------
    // DOMContentLoaded — inicializar todos los formularios
    // ------------------------------------------------------------------
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            console.log(diag, 'Init on DOMContentLoaded');
            document.querySelectorAll('form[data-df-submit]').forEach(initForm);
        });
    } else {
        console.log(diag, 'DOM already ready, init now');
        document.querySelectorAll('form[data-df-submit]').forEach(initForm);
    }
})();
