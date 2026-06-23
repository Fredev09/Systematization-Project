(function () {
    const productsList = document.getElementById('vpProductsList');
    const addProductButton = document.getElementById('vpAddProduct');
    const totalPreview = document.getElementById('vpTotalPreview');
    const stockPreview = document.getElementById('vpStockPreview');

    const clienteRadios = Array.from(document.querySelectorAll('input[name="cliente_modo"]'));
    const clienteExistenteBox = document.getElementById('clienteExistenteBox');
    const clienteNuevoBox = document.getElementById('clienteNuevoBox');
    const clienteSelect = document.getElementById('cliente_id');
    const clienteSearch = document.getElementById('clienteSearch');
    const documentoCliente = document.getElementById('documento_cliente');
    const nombreCliente = document.getElementById('nombre_cliente');
    const apellidoCliente = document.getElementById('apellido_cliente');

    function actualizarClienteBox() {
        if (!clienteRadios.length || !clienteExistenteBox || !clienteNuevoBox) {
            return;
        }

        const seleccionado = clienteRadios.find(radio => radio.checked);
        const modo = seleccionado ? seleccionado.value : 'rapida';

        clienteExistenteBox.style.display = modo === 'existente' ? 'block' : 'none';
        clienteNuevoBox.style.display = modo === 'nuevo' ? 'block' : 'none';

        if (clienteSelect) {
            clienteSelect.required = modo === 'existente';
        }

        if (documentoCliente) {
            documentoCliente.required = modo === 'nuevo';
        }

        if (nombreCliente) {
            nombreCliente.required = modo === 'nuevo';
        }

        if (apellidoCliente) {
            apellidoCliente.required = modo === 'nuevo';
        }
    }

    function filtrarClientes() {
        if (!clienteSearch || !clienteSelect) {
            return;
        }

        const texto = clienteSearch.value.trim().toLowerCase();
        const opciones = Array.from(clienteSelect.options);

        opciones.forEach(function (option, index) {
            if (index === 0) {
                option.hidden = false;
                return;
            }

            const contenido = `${option.textContent || ''} ${option.dataset.search || ''}`.toLowerCase();
            option.hidden = texto && !contenido.includes(texto);
        });

        const opcionSeleccionada = clienteSelect.options[clienteSelect.selectedIndex];

        if (opcionSeleccionada && opcionSeleccionada.hidden) {
            clienteSelect.selectedIndex = 0;
        }
    }

    clienteRadios.forEach(function (radio) {
        radio.addEventListener('change', actualizarClienteBox);
    });

    if (clienteSearch) {
        clienteSearch.addEventListener('input', filtrarClientes);
    }

    actualizarClienteBox();
    filtrarClientes();

    if (!productsList || !addProductButton || !totalPreview || !stockPreview) {
        return;
    }

    const moneyFormatter = new Intl.NumberFormat('es-CO', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    });

    const numberFormatter = new Intl.NumberFormat('es-CO', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    });

    function formatoPesos(valor) {
        const numero = Number(valor || 0);
        return `$${moneyFormatter.format(Math.round(numero))}`;
    }

    function limpiarPrecio(valor) {
        if (!valor) {
            return 0;
        }

        valor = String(valor).trim();

        if (valor.includes(',') && valor.includes('.')) {
            valor = valor.replace(/\./g, '').replace(',', '.');
        } else if (valor.includes(',')) {
            valor = valor.replace(',', '.');
        }

        const precio = parseFloat(valor);

        return isNaN(precio) ? 0 : precio;
    }

    function getRows() {
        return Array.from(productsList.querySelectorAll('.vp-product-row'));
    }

    function updateRemoveButtons() {
        const rows = getRows();

        rows.forEach(function (row) {
            const removeButton = row.querySelector('.vp-remove-btn');

            if (removeButton) {
                removeButton.disabled = rows.length === 1;
            }
        });
    }

    function updatePreview() {
        const rows = getRows();

        let total = 0;
        let selectedProducts = 0;
        let stockMessage = 'Selecciona productos';
        let stockError = false;

        rows.forEach(function (row) {
            const select = row.querySelector('.vp-product-select');
            const input = row.querySelector('.vp-quantity-input');

            if (!select || !input) {
                return;
            }

            const option = select.options[select.selectedIndex];

            if (!option || !option.value) {
                return;
            }

            const price = limpiarPrecio(option.dataset.precio);
            const stock = Number(option.dataset.stock || 0);
            const quantity = Number(input.value || 0);

            input.setAttribute('max', String(stock));

            total += price * quantity;
            selectedProducts += 1;

            if (quantity > stock) {
                stockError = true;
                stockMessage = `Hay un producto que supera el stock. Máximo: ${numberFormatter.format(stock)}`;
            }
        });

        if (!stockError) {
            if (selectedProducts === 1) {
                stockMessage = '1 producto seleccionado';
            } else if (selectedProducts > 1) {
                stockMessage = `${selectedProducts} productos seleccionados`;
            }
        }

        totalPreview.textContent = formatoPesos(total);
        stockPreview.textContent = stockMessage;
    }

    function resetRow(row) {
        const select = row.querySelector('.vp-product-select');
        const input = row.querySelector('.vp-quantity-input');

        if (select) {
            select.selectedIndex = 0;
        }

        if (input) {
            input.value = 1;
            input.removeAttribute('max');
        }
    }

    function addRow() {
        const firstRow = productsList.querySelector('.vp-product-row');

        if (!firstRow) {
            return;
        }

        const newRow = firstRow.cloneNode(true);

        resetRow(newRow);
        productsList.appendChild(newRow);

        updateRemoveButtons();
        updatePreview();
    }

    productsList.addEventListener('change', function (event) {
        if (event.target.classList.contains('vp-product-select')) {
            updatePreview();
        }
    });

    productsList.addEventListener('input', function (event) {
        if (event.target.classList.contains('vp-quantity-input')) {
            updatePreview();
        }
    });

    productsList.addEventListener('click', function (event) {
        const removeButton = event.target.closest('.vp-remove-btn');

        if (!removeButton) {
            return;
        }

        const rows = getRows();

        if (rows.length <= 1) {
            return;
        }

        const row = removeButton.closest('.vp-product-row');

        if (row) {
            row.remove();
        }

        updateRemoveButtons();
        updatePreview();
    });

    addProductButton.addEventListener('click', addRow);

    updateRemoveButtons();
    updatePreview();
})();