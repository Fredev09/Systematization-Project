    document.addEventListener('DOMContentLoaded', function () {
        const form = document.querySelector('.config-form');
        const themeSelect = document.getElementById('id_tema_defecto');
        const themeIcon = document.querySelector('#themeToggle i');

        function applySelectedTheme(theme, persist) {
            const selectedTheme = theme === 'light' ? 'light' : 'dark';
            const isDark = selectedTheme === 'dark';

            document.documentElement.classList.toggle('dark-mode', isDark);
            document.documentElement.dataset.theme = selectedTheme;
            document.body.classList.toggle('dark-mode', isDark);
            window.SYSTEM_DEFAULT_THEME = selectedTheme;

            if (themeIcon) {
                themeIcon.classList.toggle('bx-moon', !isDark);
                themeIcon.classList.toggle('bx-sun', isDark);
            }

            if (persist) {
                localStorage.setItem('theme', selectedTheme);
            }
        }

        if (themeSelect) {
            themeSelect.addEventListener('change', function () {
                applySelectedTheme(themeSelect.value, false);
            });
        }

        if (form && themeSelect) {
            form.addEventListener('submit', function () {
                if (form.dataset.confirmado === 'true') {
                    applySelectedTheme(themeSelect.value, true);
                }
            });
        }
    });