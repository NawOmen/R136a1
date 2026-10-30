"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

/** Bring errors from a user's action into view, including an unchanged repeat. */
export default function ErrorFocus() {
  const pathname = usePathname();
  useEffect(() => {
    const main = document.getElementById("main-content");
    if (!main) return;
    let armed = false;
    let frame = 0;
    let alive = true;
    const reveal = () => {
      if (!alive || !armed) return;
      // A modal makes the rest of the page inert: its error must win over
      // an older page banner, which cannot receive focus while the dialog is open.
      const modal = main.querySelector<HTMLDialogElement>("dialog[open]");
      const scope = modal ?? main;
      const target = Array.from(scope.querySelectorAll<HTMLElement>('.alert-error,[role="alert"]'))
        .find(node => node.textContent?.trim() && node.getClientRects().length && !node.closest('[hidden],[aria-hidden="true"]'));
      if (!target) return;
      armed = false;
      target.classList.add("alert", "alert-error", "error-focus-target");
      target.setAttribute("role", "alert");
      target.tabIndex = -1;
      const header = document.querySelector(".site-header")?.getBoundingClientRect();
      target.style.scrollMarginTop = `${modal ? 20 : Math.max(0, header?.bottom ?? 0) + 20}px`;
      target.focus({ preventScroll: true });
      // Error recovery must not keep scrolling while the user starts the next
      // action (WebKit can otherwise move a button between pointer down/up).
      target.scrollIntoView({ block: "start", behavior: "instant" });
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { frame = requestAnimationFrame(reveal); });
    };
    const action = (event: Event) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest("button,input[type=submit]");
      if (event.type === "click" && (!button || button.matches(":disabled") || button.hasAttribute("aria-expanded"))) return;
      armed = true;
      schedule();
    };
    const interrupt = () => {
      // A successful action can leave no error to reveal. Editing afterwards
      // must not turn a field's validation hint into a delayed focus jump.
      armed = false;
      cancelAnimationFrame(frame);
    };
    const observer = new MutationObserver(schedule);
    observer.observe(main, { childList: true, subtree: true, characterData: true });
    main.addEventListener("click", action, true);
    main.addEventListener("submit", action, true);
    main.addEventListener("pointerdown", interrupt, true);
    main.addEventListener("focusin", interrupt, true);
    main.addEventListener("keydown", interrupt, true);
    main.addEventListener("input", interrupt, true);
    main.addEventListener("change", interrupt, true);
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      main.removeEventListener("click", action, true);
      main.removeEventListener("submit", action, true);
      main.removeEventListener("pointerdown", interrupt, true);
      main.removeEventListener("focusin", interrupt, true);
      main.removeEventListener("keydown", interrupt, true);
      main.removeEventListener("input", interrupt, true);
      main.removeEventListener("change", interrupt, true);
    };
  }, [pathname]);
  return null;
}
