const togglePassword = document.getElementById("togglePassword");
const passwordInput = document.getElementById("password");

if (togglePassword && passwordInput) {
    togglePassword.addEventListener("click", () => {
        const isPassword = passwordInput.type === "password";

        passwordInput.type = isPassword ? "text" : "password";

        togglePassword.textContent = '';
        const toggleIcon = document.createElement('i');
        toggleIcon.className = isPassword ? 'bx bx-hide' : 'bx bx-show';
        togglePassword.appendChild(toggleIcon);

        togglePassword.setAttribute(
            "aria-label",
            isPassword ? "Ocultar contraseña" : "Mostrar contraseña"
        );
    });
}

const themeToggle = document.getElementById("themeToggle");
const savedTheme = localStorage.getItem("theme");

function updateThemeIcon() {
    if (!themeToggle) {
        return;
    }

    const icon = themeToggle.querySelector("i");
    const isDark = document.documentElement.classList.contains("dark-mode");

    if (icon) {
        icon.className = isDark ? "bx bx-sun" : "bx bx-moon";
    }
}

if (savedTheme === "dark") {
    document.documentElement.classList.add("dark-mode");
}

updateThemeIcon();

if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        const isDark = document.documentElement.classList.toggle("dark-mode");

        localStorage.setItem("theme", isDark ? "dark" : "light");

        updateThemeIcon();
    });
}