document.addEventListener("DOMContentLoaded", () => {
    const currentPath = window.location.pathname;
    const links = document.querySelectorAll(".site-nav a");

    links.forEach((link) => {
        const linkPath = new URL(link.href).pathname;
        const isActive =
            linkPath === currentPath ||
            (linkPath !== "/" && currentPath.startsWith(linkPath));

        if (isActive) {
            link.setAttribute("aria-current", "page");
        }
    });
});
