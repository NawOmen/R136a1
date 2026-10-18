export type Theme = "light" | "dark";
export const THEME_CHANGED_EVENT = "porukam:theme-changed";

export function savedTheme(): Theme {
  return window.localStorage.getItem("porukam-theme") === "light" ? "light" : "dark";
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  window.localStorage.setItem("porukam-theme", theme);
  window.dispatchEvent(new Event(THEME_CHANGED_EVENT));
}
