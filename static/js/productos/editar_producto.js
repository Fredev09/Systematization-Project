document.addEventListener('DOMContentLoaded', () => {
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

    function obtenerSrcImagenSeguro(src) {
        if (!src || typeof src !== 'string') {
            return null;
        }

        const valor = src.trim();

        if (!valor) {
            return null;
        }

        // Permitir URLs de objetos (imágenes subidas con FileReader)
        if (valor.startsWith('blob:')) {
            return valor;
        }

        // Permitir rutas relativas (ej. /media/imagen.jpg) y devolverlas canonizadas
        if (valor.startsWith('/')) {
            return new URL(valor, window.location.origin).toString();
        }

        // Validar URLs HTTP/HTTPS y devolverlas canonizadas
        try {
            const parsed = new URL(valor, window.location.origin);

            // Solo permitir HTTP o HTTPS (rechazar javascript:, data:, etc.)
            if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
                return null;
            }

            return parsed.toString();
        } catch (e) {
            // Si no es una URL válida, rechazarla
            return null;
        }
    }

    function pintarConImagen(src) {
        if (!imagePreview || !imagePreviewBox || !imagePreviewText || !imagePreviewIcon) {
            return;
        }

        const srcSeguro = obtenerSrcImagenSeguro(src);
        if (!srcSeguro) {
            pintarSinImagen();
            return;
        }

        imagePreview.src = srcSeguro;
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

    mostrarVistaPrevia();
});
