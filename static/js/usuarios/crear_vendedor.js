document.addEventListener("DOMContentLoaded", () => {
    const toggleButtons = document.querySelectorAll(".toggle-password");

    toggleButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const targetId = button.getAttribute("data-target");
            const input = document.getElementById(targetId);
            const icon = button.querySelector("i");

            if (!input || !icon) return;

            if (input.type === "password") {
                input.type = "text";
                icon.classList.remove("bx-show");
                icon.classList.add("bx-hide");
                button.setAttribute("aria-label", "Ocultar contraseña");
            } else {
                input.type = "password";
                icon.classList.remove("bx-hide");
                icon.classList.add("bx-show");
                button.setAttribute("aria-label", "Mostrar contraseña");
            }
        });
    });
});