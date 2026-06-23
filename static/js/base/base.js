(function () {
    try {
        const root = document.documentElement;
        const defaultTheme =
            root.dataset.defaultTheme || 'dark';

        const savedTheme =
            localStorage.getItem('theme') || defaultTheme;

        window.SYSTEM_DEFAULT_THEME = defaultTheme;

        root.classList.add('theme-loading');
        root.dataset.theme = savedTheme;
        root.classList.toggle('dark-mode', savedTheme === 'dark');

        document.addEventListener('DOMContentLoaded', () => {
            document.body.classList.toggle(
                'dark-mode',
                savedTheme === 'dark'
            );
        });

        window.addEventListener('load', () => {
            root.classList.remove('theme-loading');
        });

    } catch (error) {
        document.documentElement.classList.add(
            'theme-loading',
            'dark-mode'
        );

        document.documentElement.dataset.theme = 'dark';
        window.SYSTEM_DEFAULT_THEME = 'dark';
    }
})();