document.documentElement.classList.add("js-enabled");

document.addEventListener("DOMContentLoaded", () => {
    const currentPath = window.location.pathname;
    const nav = document.getElementById("site-menu");
    const toggle = document.querySelector(".nav-toggle");
    const links = nav ? nav.querySelectorAll("a") : [];

    links.forEach((link) => {
        const linkPath = new URL(link.href).pathname;
        const isActive = linkPath === "/"
            ? currentPath === "/" && !link.hash
            : currentPath.startsWith(linkPath);

        if (isActive) {
            link.setAttribute("aria-current", "page");
        }
    });

    if (!nav || !toggle) {
        return;
    }

    const setMenuState = (isOpen) => {
        nav.classList.toggle("is-open", isOpen);
        toggle.setAttribute("aria-expanded", String(isOpen));
    };

    toggle.addEventListener("click", () => {
        setMenuState(!nav.classList.contains("is-open"));
    });

    links.forEach((link) => {
        link.addEventListener("click", () => {
            setMenuState(false);
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            setMenuState(false);
        }
    });
});
