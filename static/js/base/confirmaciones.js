document.addEventListener("DOMContentLoaded", function () {
    const formularios = document.querySelectorAll("form.confirm-form");

    formularios.forEach(function (formulario) {
        formulario.addEventListener("submit", function (event) {
            if (formulario.dataset.confirmado === "true") {
                return;
            }

            if (!formulario.checkValidity()) {
                formulario.reportValidity();
                return;
            }

            event.preventDefault();

            const titulo = formulario.dataset.confirmTitle || "¿Confirmar acción?";
            const texto = formulario.dataset.confirmText || "Se guardarán los cambios.";
            const icono = formulario.dataset.confirmIcon || "question";
            const textoBoton = formulario.dataset.confirmButton || "Sí, continuar";
            const textoCarga = formulario.dataset.loadingText || "Guardando...";

            Swal.fire({
                title: titulo,
                text: texto,
                icon: icono,
                showCancelButton: true,
                confirmButtonText: textoBoton,
                cancelButtonText: "Cancelar",
                confirmButtonColor: "#d41472",
                cancelButtonColor: "#6c757d",
                reverseButtons: true
            }).then(function (resultado) {
                if (resultado.isConfirmed) {
                    formulario.dataset.confirmado = "true";

                    const boton = formulario.querySelector("button[type='submit']:not(.no-loader)");

                    if (boton) {
                        boton.classList.add("btn-loading");
                        boton.disabled = true;

                        boton.innerHTML = `
                            <span class="btn-spinner"></span>
                            <span>${textoCarga}</span>
                        `;
                    }

                    formulario.requestSubmit();
                }
            });
        });
    });
});