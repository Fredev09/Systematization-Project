document.addEventListener('DOMContentLoaded', () => {
    const btnCrearCategoria = document.getElementById('btnCrearCategoria');
    const nuevaCategoriaBox = document.getElementById('nuevaCategoriaBox');
    const nuevaCategoriaInput = document.getElementById('nueva_categoria');
    const categoriaMensaje = document.getElementById('categoriaMensaje');
    const categoriaSelect = document.querySelector('select[name="categoria"]');

    if (btnCrearCategoria && nuevaCategoriaBox && nuevaCategoriaInput && categoriaSelect) {
        btnCrearCategoria.addEventListener('click', async () => {
            const estaOculto = nuevaCategoriaBox.classList.contains('d-none');

            if (estaOculto) {
                nuevaCategoriaBox.classList.remove('d-none');
                nuevaCategoriaInput.focus();
                btnCrearCategoria.textContent = '';
                const iconCheck = document.createElement('i');
                iconCheck.className = 'bx bx-check';
                btnCrearCategoria.appendChild(iconCheck);
                btnCrearCategoria.appendChild(document.createTextNode(' Guardar categoría'));
                return;
            }

            const nombreCategoria = nuevaCategoriaInput.value.trim();

            if (!nombreCategoria) {
                categoriaMensaje.textContent = 'Escribe el nombre de la categoría.';
                categoriaMensaje.className = 'category-message error';
                return;
            }

            try {
                const response = await fetch(crearCategoriaUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        nombre: nombreCategoria
                    })
                });

                const data = await response.json();

                if (data.success) {
                    const option = document.createElement('option');
                    option.value = data.id;
                    option.textContent = data.nombre;
                    option.selected = true;

                    categoriaSelect.appendChild(option);

                    nuevaCategoriaInput.value = '';
                    nuevaCategoriaBox.classList.add('d-none');
                    categoriaMensaje.textContent = '';
                    btnCrearCategoria.textContent = '';
                    const iconPlus = document.createElement('i');
                    iconPlus.className = 'bx bx-plus';
                    btnCrearCategoria.appendChild(iconPlus);
                    btnCrearCategoria.appendChild(document.createTextNode(' Crear categoría'));
                } else {
                    categoriaMensaje.textContent = data.error || 'No se pudo crear la categoría.';
                    categoriaMensaje.className = 'category-message error';
                }
            } catch (error) {
                categoriaMensaje.textContent = 'Error al conectar con el servidor.';
                categoriaMensaje.className = 'category-message error';
            }
        });
    }

    const imagenInput = document.querySelector('input[name="imagen"]');
    const imagenUrlInput = document.querySelector('input[name="imagen_url"]');
    const imagePreview = document.getElementById('imagePreview');
    const imagePreviewBox = document.getElementById('imagePreviewBox');
    const imagePreviewText = document.getElementById('imagePreviewText');
    const imagePreviewIcon = document.getElementById('imagePreviewIcon');

    let objectUrlActual = null;
    const imagenInicial = imagePreview ? imagePreview.getAttribute('src') : '';

    function limpiarObjectUrl() {
        if (objectUrlActual) {
            URL.revokeObjectURL(objectUrlActual);
            objectUrlActual = null;
        }
    }

    function esSrcImagenSeguro(src) {
        if (!src || typeof src !== 'string') {
            return false;
        }

        const valor = src.trim();

        if (!valor) {
            return false;
        }

        if (valor.startsWith('blob:')) {
            return true;
        }

        if (valor.startsWith('/')) {
            return true;
        }

        try {
            const parsed = new URL(valor, window.location.origin);
            return parsed.protocol === 'http:' || parsed.protocol === 'https:';
        } catch (e) {
            return false;
        }
    }

    function pintarConImagen(src) {
        if (!imagePreview || !imagePreviewBox || !imagePreviewText || !imagePreviewIcon) {
            return;
        }

        if (!esSrcImagenSeguro(src)) {
            pintarSinImagen();
            return;
        }

        imagePreview.src = src;
        imagePreview.style.display = 'block';
        imagePreviewText.style.display = 'none';
        imagePreviewIcon.style.display = 'none';
        imagePreviewBox.classList.add('has-image');
    }

    function pintarSinImagen() {
        if (!imagePreview || !imagePreviewBox || !imagePreviewText || !imagePreviewIcon) {
            return;
        }

        imagePreview.removeAttribute('src');
        imagePreview.style.display = 'none';
        imagePreviewText.style.display = 'block';
        imagePreviewIcon.style.display = 'flex';
        imagePreviewBox.classList.remove('has-image');
    }

    function mostrarVistaPrevia() {
        if (!imagePreview || !imagePreviewBox || !imagePreviewText || !imagePreviewIcon) {
            return;
        }

        const archivo = imagenInput && imagenInput.files ? imagenInput.files[0] : null;
        const urlEscrita = imagenUrlInput ? imagenUrlInput.value.trim() : '';

        limpiarObjectUrl();

        if (archivo) {
            objectUrlActual = URL.createObjectURL(archivo);
            pintarConImagen(objectUrlActual);
            return;
        }

        if (urlEscrita) {
            pintarConImagen(urlEscrita);
            return;
        }

        if (imagenInicial) {
            pintarConImagen(imagenInicial);
            return;
        }

        pintarSinImagen();
    }

    if (imagePreview) {
        imagePreview.addEventListener('error', () => {
            pintarSinImagen();
            imagePreviewText.textContent = 'No se pudo cargar la imagen. Revisa la URL o sube un archivo.';
        });
    }

    if (imagenInput) {
        imagenInput.addEventListener('change', mostrarVistaPrevia);
    }

    if (imagenUrlInput) {
        imagenUrlInput.addEventListener('input', mostrarVistaPrevia);
    }

    const usarTallasMultiples = document.getElementById('usarTallasMultiples');
    const sizeVariantsBox = document.getElementById('sizeVariantsBox');
    const sizeVariantsList = document.getElementById('sizeVariantsList');
    const addSizeVariant = document.getElementById('addSizeVariant');
    const singleSizeField = document.querySelector('.single-size-field');
    const singleStockField = document.querySelector('.single-stock-field');
    const tallaPrincipal = document.querySelector('[name="talla"]');
    const stockPrincipal = document.querySelector('[name="stock"]');

    function getSizeRows() {
        return sizeVariantsList ? Array.from(sizeVariantsList.querySelectorAll('.size-variant-row')) : [];
    }

    function updateSizeRemoveButtons() {
        const rows = getSizeRows();

        rows.forEach((row) => {
            const removeButton = row.querySelector('.size-remove-btn');

            if (removeButton) {
                removeButton.disabled = rows.length === 1;
            }
        });
    }

    function updateSizeMode() {
        if (!usarTallasMultiples || !sizeVariantsBox) {
            return;
        }

        const activo = usarTallasMultiples.checked;
        sizeVariantsBox.style.display = activo ? 'block' : 'none';

        if (singleSizeField) {
            singleSizeField.style.display = activo ? 'none' : 'block';
        }

        if (singleStockField) {
            singleStockField.style.display = activo ? 'none' : 'block';
        }

        if (tallaPrincipal) {
            tallaPrincipal.disabled = activo;
            tallaPrincipal.required = !activo;
        }

        if (stockPrincipal) {
            stockPrincipal.disabled = activo;
            stockPrincipal.required = !activo;
        }

        getSizeRows().forEach((row) => {
            const talla = row.querySelector('.size-select');
            const stock = row.querySelector('.size-stock');

            if (talla) {
                talla.disabled = !activo;
                talla.required = activo;
            }

            if (stock) {
                stock.disabled = !activo;
                stock.required = activo;
            }
        });
    }

    function addSizeRow() {
        const firstRow = sizeVariantsList ? sizeVariantsList.querySelector('.size-variant-row') : null;

        if (!firstRow) {
            return;
        }

        const newRow = firstRow.cloneNode(true);
        const talla = newRow.querySelector('.size-select');
        const stock = newRow.querySelector('.size-stock');

        if (talla) {
            talla.selectedIndex = 0;
        }

        if (stock) {
            stock.value = '';
        }

        sizeVariantsList.appendChild(newRow);
        updateSizeRemoveButtons();
        updateSizeMode();
    }

    if (usarTallasMultiples) {
        usarTallasMultiples.addEventListener('change', updateSizeMode);
    }

    if (addSizeVariant) {
        addSizeVariant.addEventListener('click', addSizeRow);
    }

    if (sizeVariantsList) {
        sizeVariantsList.addEventListener('click', (event) => {
            const button = event.target.closest('.size-remove-btn');

            if (!button || getSizeRows().length <= 1) {
                return;
            }

            const row = button.closest('.size-variant-row');

            if (row) {
                row.remove();
            }

            updateSizeRemoveButtons();
            updateSizeMode();
        });
    }

    updateSizeRemoveButtons();
    updateSizeMode();

    mostrarVistaPrevia();
});

function getCookie(name) {
    let cookieValue = null;

    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');

        for (let cookie of cookies) {
            cookie = cookie.trim();

            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }

    return cookieValue;
}