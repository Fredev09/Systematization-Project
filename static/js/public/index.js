window.addEventListener("scroll", () => {
    const navbar = document.querySelector(".navbar");

    if (navbar) {
        if (window.scrollY > 40) {
            navbar.classList.add("navbar-scroll");
        } else {
            navbar.classList.remove("navbar-scroll");
        }
    }
});

const animatedElements = document.querySelectorAll(
    ".producto-card, .coleccion-card, .mini-card, .valor-item, .stats-box, .contacto-card"
);

const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
        if (entry.isIntersecting) {
            entry.target.classList.add("show-animation");
        }
    });
}, {
    threshold: 0.15
});

animatedElements.forEach((element) => {
    observer.observe(element);
});

const buttons = document.querySelectorAll(
    ".btn-principal, .btn-claro, .btn-cta, .btn-sistema"
);

buttons.forEach((button) => {
    button.addEventListener("mouseenter", () => {
        button.style.transform = "translateY(-3px) scale(1.02)";
    });

    button.addEventListener("mouseleave", () => {
        button.style.transform = "";
    });
});

window.addEventListener("scroll", () => {
    const scrolled = window.scrollY;

    const shapeOne = document.querySelector(".shape-one");
    const shapeTwo = document.querySelector(".shape-two");

    if (shapeOne) {
        shapeOne.style.transform = `translateY(${scrolled * 0.15}px)`;
    }

    if (shapeTwo) {
        shapeTwo.style.transform = `translateY(${scrolled * -0.12}px)`;
    }
});

document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener("click", function (e) {
        e.preventDefault();

        const target = document.querySelector(this.getAttribute("href"));

        if (target) {
            target.scrollIntoView({
                behavior: "smooth"
            });
        }
    });
});

const themeToggle = document.getElementById("themeToggle");

function cambiarIconoTema() {
    if (!themeToggle) {
        return;
    }

    const icono = themeToggle.querySelector("i");

    if (!icono) {
        return;
    }

    if (document.documentElement.classList.contains("dark-mode")) {
        icono.className = "bi bi-sun";
    } else {
        icono.className = "bi bi-moon-stars";
    }
}

const temaGuardado = localStorage.getItem("theme");

if (temaGuardado === "dark") {
    document.documentElement.classList.add("dark-mode");
}

cambiarIconoTema();

if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        const isDark = document.documentElement.classList.toggle("dark-mode");

        localStorage.setItem("theme", isDark ? "dark" : "light");

        cambiarIconoTema();
    });
}