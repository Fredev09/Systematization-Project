const togglePassword = document.getElementById("togglePassword");
const passwordInput = document.getElementById("password");

if (togglePassword && passwordInput) {
    togglePassword.addEventListener("click", () => {
        const isPassword = passwordInput.type === "password";

        passwordInput.type = isPassword ? "text" : "password";

        togglePassword.innerHTML = isPassword
            ? "<i class='bx bx-hide'></i>"
            : "<i class='bx bx-show'></i>";

        togglePassword.setAttribute(
            "aria-label",
            isPassword ? "Ocultar contraseña" : "Mostrar contraseña"
        );
    });
}

const themeToggle = document.getElementById("themeToggle");
const savedTheme = localStorage.getItem("tema");

function updateThemeIcon() {
    if (!themeToggle) {
        return;
    }

    const icon = themeToggle.querySelector("i");
    const isDark = document.body.classList.contains("dark-mode");

    if (icon) {
        icon.className = isDark ? "bx bx-sun" : "bx bx-moon";
    }
}

if (savedTheme === "oscuro") {
    document.body.classList.add("dark-mode");
}

if (savedTheme === "claro") {
    document.body.classList.remove("dark-mode");
}

updateThemeIcon();

if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        const isDark = document.body.classList.toggle("dark-mode");

        localStorage.setItem("tema", isDark ? "oscuro" : "claro");

        updateThemeIcon();
    });
}