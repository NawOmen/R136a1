export type Theme = "light" | "dark";
export const THEME_CHANGED_EVENT = "porukam:theme-changed";

export function savedTheme(): Theme {
  try { return window.localStorage.getItem("porukam-theme") === "dark" ? "dark" : "light"; }
  catch { return document.documentElement.dataset.theme === "dark" ? "dark" : "light"; }
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try { window.localStorage.setItem("porukam-theme", theme); } catch { /* Keep session theme if browser storage is unavailable. */ }
  window.dispatchEvent(new Event(THEME_CHANGED_EVENT));
}
