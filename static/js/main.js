document.documentElement.classList.add("js-enabled");

document.addEventListener("DOMContentLoaded", () => {
    const currentPath = window.location.pathname;
    const nav = document.getElementById("site-menu");
    const toggle = document.querySelector(".nav-toggle");
    const links = nav ? nav.querySelectorAll("a") : [];
    const posterImages = document.querySelectorAll("[data-poster-image]");

    posterImages.forEach((image) => {
        const poster = image.closest("[data-poster]");
        const placeholder = poster
            ? poster.querySelector("[data-poster-placeholder]")
            : null;

        const showImage = () => {
            image.hidden = false;
            image.classList.add("is-loaded");
            if (placeholder) {
                placeholder.hidden = true;
            }
        };

        const showPlaceholder = () => {
            image.hidden = true;
            image.classList.remove("is-loaded");
            if (placeholder) {
                placeholder.hidden = false;
            }
        };

        image.addEventListener("load", showImage, { once: true });
        image.addEventListener("error", showPlaceholder, { once: true });

        if (image.complete) {
            if (image.naturalWidth > 0) {
                showImage();
            } else {
                showPlaceholder();
            }
        }
    });

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
