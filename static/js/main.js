document.documentElement.classList.add("js-enabled");

document.addEventListener("DOMContentLoaded", () => {
    const menu = document.querySelector("[data-site-menu]");
    const menuToggle = document.querySelector("[data-menu-toggle]");
    const navLinks = menu ? menu.querySelectorAll("a") : [];
    const posterImages = document.querySelectorAll("[data-poster-image]");

    posterImages.forEach((image) => {
        const poster = image.closest("[data-poster]");
        const placeholder = poster
            ? poster.querySelector("[data-poster-placeholder]")
            : null;

        const showImage = () => {
            image.classList.add("is-loaded");
            if (placeholder) {
                placeholder.hidden = true;
            }
        };

        const showPlaceholder = () => {
            image.classList.remove("is-loaded");
            if (placeholder) {
                placeholder.hidden = false;
            }
        };

        image.removeAttribute("hidden");
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

    const setMenuState = (isOpen, returnFocus = false) => {
        if (!menu || !menuToggle) {
            return;
        }
        const wasOpen = menu.classList.contains("is-open");
        menu.classList.toggle("is-open", isOpen);
        menuToggle.setAttribute("aria-expanded", String(isOpen));
        menuToggle.setAttribute("aria-label", isOpen ? "Закрыть меню" : "Открыть меню");
        document.body.classList.toggle("menu-open", isOpen);
        if (!isOpen && wasOpen && returnFocus) {
            menuToggle.focus();
        }
    };

    if (menu && menuToggle) {
        menuToggle.addEventListener("click", () => {
            setMenuState(!menu.classList.contains("is-open"));
        });

        navLinks.forEach((link) => {
            link.addEventListener("click", () => setMenuState(false));
        });

        const desktopMenu = window.matchMedia("(min-width: 961px)");
        const closeMenuOnDesktop = (event) => {
            if (event.matches) {
                setMenuState(false);
            }
        };
        desktopMenu.addEventListener?.("change", closeMenuOnDesktop);
    }

    const headerPopover = document.querySelector("[data-contact-popover]");
    const headerTrigger = headerPopover
        ? headerPopover.querySelector("[data-contact-trigger]")
        : null;
    const headerPanel = headerPopover
        ? headerPopover.querySelector("[data-contact-panel]")
        : null;

    const setHeaderContacts = (isOpen, returnFocus = false) => {
        if (!headerTrigger || !headerPanel) {
            return;
        }
        headerTrigger.setAttribute("aria-expanded", String(isOpen));
        headerPanel.hidden = !isOpen;
        if (isOpen) {
            headerPanel.querySelector("a")?.focus();
        } else if (returnFocus) {
            headerTrigger.focus();
        }
    };

    if (headerTrigger && headerPanel) {
        headerTrigger.addEventListener("click", () => {
            setHeaderContacts(headerPanel.hidden);
        });
    }

    const floating = document.querySelector("[data-floating-contact]");
    const floatingTrigger = floating
        ? floating.querySelector("[data-floating-trigger]")
        : null;
    const floatingPanel = floating
        ? floating.querySelector("[data-floating-panel]")
        : null;
    const floatingClose = floating
        ? floating.querySelector("[data-floating-close]")
        : null;

    const setFloatingContacts = (isOpen, returnFocus = false) => {
        if (!floatingTrigger || !floatingPanel) {
            return;
        }
        floatingTrigger.setAttribute("aria-expanded", String(isOpen));
        floatingPanel.hidden = !isOpen;
        if (isOpen) {
            floatingPanel.querySelector("a, button")?.focus();
        } else if (returnFocus) {
            floatingTrigger.focus();
        }
    };

    if (floatingTrigger && floatingPanel) {
        floatingTrigger.addEventListener("click", () => {
            setFloatingContacts(floatingPanel.hidden);
        });
        floatingClose?.addEventListener("click", () => {
            setFloatingContacts(false, true);
        });
    }

    document.addEventListener("click", (event) => {
        if (
            menu
            && menuToggle
            && menu.classList.contains("is-open")
            && !menu.contains(event.target)
            && !menuToggle.contains(event.target)
        ) {
            setMenuState(false);
        }
        if (headerPopover && !headerPopover.contains(event.target)) {
            setHeaderContacts(false);
        }
        if (floating && !floating.contains(event.target)) {
            setFloatingContacts(false);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") {
            return;
        }
        if (menu?.classList.contains("is-open")) {
            setMenuState(false, true);
        }
        if (headerPanel && !headerPanel.hidden) {
            setHeaderContacts(false, true);
        }
        if (floatingPanel && !floatingPanel.hidden) {
            setFloatingContacts(false, true);
        }
    });

    const filters = document.querySelector("[data-competition-filters]");
    const competitionCards = Array.from(
        document.querySelectorAll("[data-competition-card]")
    );

    if (filters && competitionCards.length > 0) {
        const search = filters.querySelector("[data-filter-search]");
        const statusButtons = Array.from(
            filters.querySelectorAll("[data-status-value]")
        );
        const count = document.querySelector("[data-filter-count]");
        const empty = document.querySelector("[data-filter-empty]");
        let selectedStatus = "all";

        const normalize = (value) => value
            .toLocaleLowerCase("ru")
            .replace(/\s+/g, " ")
            .trim();

        const applyFilters = () => {
            const query = normalize(search?.value || "");
            let visibleCount = 0;

            competitionCards.forEach((card) => {
                const matchesSearch = !query
                    || normalize(card.dataset.search || "").includes(query);
                const matchesStatus = selectedStatus === "all"
                    || card.dataset.status === selectedStatus;
                const isVisible = matchesSearch && matchesStatus;
                card.hidden = !isVisible;
                if (isVisible) {
                    card.classList.add("is-revealed");
                    visibleCount += 1;
                }
            });

            if (count) {
                count.textContent = String(visibleCount);
            }
            if (empty) {
                empty.hidden = visibleCount !== 0;
            }
        };

        search?.addEventListener("input", applyFilters);

        statusButtons.forEach((button) => {
            button.addEventListener("click", () => {
                selectedStatus = button.dataset.statusValue || "all";
                statusButtons.forEach((item) => {
                    const isActive = item === button;
                    item.classList.toggle("is-active", isActive);
                    item.setAttribute("aria-pressed", String(isActive));
                });
                applyFilters();
            });
        });

        filters.addEventListener("reset", () => {
            window.setTimeout(() => {
                selectedStatus = "all";
                statusButtons.forEach((button) => {
                    const isActive = button.dataset.statusValue === "all";
                    button.classList.toggle("is-active", isActive);
                    button.setAttribute("aria-pressed", String(isActive));
                });
                applyFilters();
            }, 0);
        });
    }

    const stickyCta = document.querySelector("[data-sticky-cta]");
    const primaryEventCta = document.querySelector(".event-actions .button.primary");

    if (stickyCta && primaryEventCta) {
        const setStickyCtaState = (shouldShow) => {
            stickyCta.classList.toggle("is-visible", shouldShow);
            document.body.classList.toggle("has-sticky-cta", shouldShow);
        };

        const updateStickyCta = () => {
            setStickyCtaState(
                primaryEventCta.getBoundingClientRect().bottom <= 0
            );
        };
        let stickyUpdateFrame = null;
        const scheduleStickyCtaUpdate = () => {
            if (stickyUpdateFrame !== null) {
                return;
            }
            stickyUpdateFrame = window.requestAnimationFrame(() => {
                stickyUpdateFrame = null;
                updateStickyCta();
            });
        };

        updateStickyCta();
        window.addEventListener("scroll", scheduleStickyCtaUpdate, { passive: true });
        window.addEventListener("resize", updateStickyCta);
    }

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const revealItems = Array.from(document.querySelectorAll("[data-reveal]"));
    const reveal = (item) => item.classList.add("is-revealed");

    if (reducedMotion || typeof window.IntersectionObserver !== "function") {
        revealItems.forEach(reveal);
    } else {
        const heroRevealItems = revealItems.filter(
            (item) => item.dataset.reveal === "hero"
        );
        const scrollRevealItems = revealItems.filter(
            (item) => item.dataset.reveal !== "hero"
        );
        const revealObserver = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    reveal(entry.target);
                    revealObserver.unobserve(entry.target);
                }
            });
        }, { rootMargin: "0px 0px -8%", threshold: 0.08 });

        scrollRevealItems.forEach((item) => revealObserver.observe(item));
        heroRevealItems.forEach(reveal);
    }
});
