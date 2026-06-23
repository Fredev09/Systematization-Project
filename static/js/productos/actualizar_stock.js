document.addEventListener("DOMContentLoaded", function () {
    const stockActualElement = document.getElementById("stockActual");
    const cantidadInput = document.getElementById("cantidad");
    const stockNuevoElement = document.getElementById("stockNuevo");
    const tipoInputs = document.querySelectorAll("input[name='tipo']");
    const guardarAjuste = document.getElementById("guardarAjuste");
    const stockErrorMessage = document.getElementById("stockErrorMessage");
    const motivoSelect = document.getElementById("motivo");

    if (!stockActualElement || !cantidadInput || !stockNuevoElement || !tipoInputs.length || !motivoSelect) {
        return;
    }

    const stockActual = Number(stockActualElement.dataset.stock || 0);

    const motivosPorTipo = {
        entrada: [
            { valor: "compra_proveedor", texto: "Compra a proveedor" },
            { valor: "devolucion_cliente", texto: "Devolución de cliente" },
            { valor: "correccion_manual", texto: "Corrección positiva" }
        ],
        salida: [
            { valor: "venta_manual", texto: "Venta manual" },
            { valor: "producto_danado", texto: "Producto dañado" },
            { valor: "perdida", texto: "Pérdida" },
            { valor: "robo", texto: "Robo" },
            { valor: "devolucion_proveedor", texto: "Devolución a proveedor" }
        ],
        correccion: [
            { valor: "conteo_fisico", texto: "Conteo físico" },
            { valor: "correccion_manual", texto: "Corrección manual" }
        ]
    };

    function obtenerTipoSeleccionado() {
        const seleccionado = document.querySelector("input[name='tipo']:checked");
        return seleccionado ? seleccionado.value : "entrada";
    }

    function cargarMotivos() {
        const tipoSeleccionado = obtenerTipoSeleccionado();
        const motivos = motivosPorTipo[tipoSeleccionado] || [];

        motivoSelect.innerHTML = "";

        const opcionInicial = document.createElement("option");
        opcionInicial.value = "";
        opcionInicial.textContent = "Sin motivo";
        motivoSelect.appendChild(opcionInicial);

        motivos.forEach(function (motivo) {
            const option = document.createElement("option");
            option.value = motivo.valor;
            option.textContent = motivo.texto;
            motivoSelect.appendChild(option);
        });
    }

    function mostrarErrorStock(mostrar) {
        if (stockErrorMessage) {
            stockErrorMessage.classList.toggle("show", mostrar);
        }

        if (guardarAjuste) {
            guardarAjuste.disabled = mostrar;
        }

        stockNuevoElement.classList.toggle("stock-negative", mostrar);
    }

    function calcularStock() {
        const cantidad = Number(cantidadInput.value || 0);
        const tipoSeleccionado = obtenerTipoSeleccionado();

        let resultado = stockActual;
        let error = false;

        if (tipoSeleccionado === "entrada") {
            resultado = stockActual + cantidad;
        } else if (tipoSeleccionado === "salida") {
            resultado = stockActual - cantidad;
            error = cantidad > stockActual;
        } else if (tipoSeleccionado === "correccion") {
            resultado = cantidad;
        }

        stockNuevoElement.textContent = resultado;
        mostrarErrorStock(error);
    }

    tipoInputs.forEach(function (input) {
        input.addEventListener("change", function () {
            cargarMotivos();
            calcularStock();
        });
    });

    cantidadInput.addEventListener("input", calcularStock);

    cargarMotivos();
    calcularStock();
});
