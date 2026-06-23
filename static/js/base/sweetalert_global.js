document.addEventListener("DOMContentLoaded", async function () {
    const mensajes = Array.from(document.querySelectorAll(".django-message-data"));

    if (!mensajes.length || typeof Swal === "undefined") {
        return;
    }

    for (const mensaje of mensajes) {
        const texto = mensaje.dataset.text || "";
        const tipo = mensaje.dataset.type || "info";

        let titulo = "Informacion";
        let icono = "info";

        if (tipo.includes("success")) {
            titulo = "Operacion exitosa";
            icono = "success";
        } else if (tipo.includes("error")) {
            titulo = "Ocurrio un error";
            icono = "error";
        } else if (tipo.includes("warning")) {
            titulo = "Atencion";
            icono = "warning";
        }

        await Swal.fire({
            title: titulo,
            text: texto,
            icon: icono,
            confirmButtonText: "Aceptar",
            confirmButtonColor: "#d41472"
        });
    }
});
