const menuToggle = document.getElementById('menuToggle');
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('sidebarOverlay');

if (menuToggle && sidebar && overlay) {
    menuToggle.addEventListener('click', () => {
        sidebar.classList.add('active');
        overlay.classList.add('active');
    });

    overlay.addEventListener('click', () => {
        sidebar.classList.remove('active');
        overlay.classList.remove('active');
    });
}

const themeToggle = document.getElementById('themeToggle');
const themeIcon = themeToggle ? themeToggle.querySelector('i') : null;

function applyTheme(theme) {
    const isDark = theme === 'dark';

    document.documentElement.classList.toggle('dark-mode', isDark);
    document.documentElement.dataset.theme = theme;
    document.body.classList.toggle('dark-mode', isDark);

    if (themeIcon) {
        themeIcon.classList.toggle('bx-moon', !isDark);
        themeIcon.classList.toggle('bx-sun', isDark);
    }
}

const savedTheme = localStorage.getItem('theme') || window.SYSTEM_DEFAULT_THEME || 'dark';
applyTheme(savedTheme);

if (themeToggle && themeIcon) {
    themeToggle.addEventListener('click', () => {
        const currentTheme = document.body.classList.contains('dark-mode') ? 'dark' : 'light';
        const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';

        localStorage.setItem('theme', nextTheme);
        applyTheme(nextTheme);
    });
}

const btnExportar = document.getElementById('btnExportar');

if (btnExportar) {
    btnExportar.addEventListener('click', () => {
        const tabla = document.getElementById('tablaUsuarios');

        if (!tabla) return;

        let csv = [];
        const filas = tabla.querySelectorAll('tr');

        filas.forEach(fila => {
            const columnas = fila.querySelectorAll('th, td');
            let datos = [];

            columnas.forEach((columna, index) => {
                if (index !== columnas.length - 1) {
                    datos.push(`"${columna.innerText.trim().replace(/"/g, '""')}"`);
                }
            });

            csv.push(datos.join(','));
        });

        const archivo = new Blob([csv.join('\n')], {
            type: 'text/csv;charset=utf-8;'
        });

        const url = URL.createObjectURL(archivo);
        const enlace = document.createElement('a');

        enlace.href = url;
        enlace.download = 'usuarios_tonjeo.csv';
        enlace.click();

        URL.revokeObjectURL(url);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const btnActividad = document.getElementById('btnActividad');
    const actividadesOcultas = document.querySelectorAll('.hidden-activity');

    if (!btnActividad || actividadesOcultas.length === 0) {
        return;
    }

    btnActividad.addEventListener('click', () => {
        const abierto = btnActividad.dataset.estado === 'abierto';

        actividadesOcultas.forEach(actividad => {
            actividad.style.display = abierto ? 'none' : 'flex';
        });

        btnActividad.dataset.estado = abierto ? 'cerrado' : 'abierto';
        btnActividad.textContent = abierto ? 'Ver toda la actividad' : 'Ver menos';
    });
});