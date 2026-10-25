import type { CSSProperties, ReactNode } from "react";

export type IconName = "bell" | "arrow" | "search" | "box" | "package" | "briefcase" | "layers" | "factory" | "building" | "shield" | "spark" | "check" | "sun" | "moon" | "menu" | "close" | "sliders" | "link" | "truck" | "mic" | "heart" | "grid" | "fabric" | "metal" | "chair" | "bricks" | "mail";

const paths: Record<IconName, ReactNode> = {
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" /></>,
  package: <><path d="m12 3 9 4.5v9L12 21l-9-4.5v-9L12 3Z" /><path d="m3 7.5 9 4.5 9-4.5M12 12v9M7.5 5.25l9 4.5" /></>,
  briefcase: <><rect x="3" y="7" width="18" height="14" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12l9 3 9-3M12 13v4" /></>,
  heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" />,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
  fabric: <><path d="M6 5h11a4 4 0 0 1 4 4v12H10"/><ellipse cx="8" cy="15" rx="6" ry="7"/><ellipse cx="8" cy="15" rx="3" ry="4"/><path d="M14 4h4a4 4 0 0 1 4 4v10"/></>,
  metal: <><path d="m12 2 8 5v10l-8 5-8-5V7l8-5Z"/><path d="m12 6 5 3v6l-5 3-5-3V9l5-3Z"/><circle cx="12" cy="12" r="2"/></>,
  chair: <><rect x="6" y="3" width="12" height="10" rx="2"/><path d="M5 14h14v4H5zM7 18l-2 4m12-4 2 4"/></>,
  bricks: <><path d="M8 2h8v6H8zM4 8h8v6H4zm8 0h8v6h-8zM1 14h7v7H1zm7 0h8v7H8zm8 0h7v7h-7z"/></>,
  mail: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></>,
  building: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 7h1m4 0h1M9 11h1m4 0h1M9 15h1m4 0h1M10 21v-3h4v3" /></>,
  mic: <><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4M8 22h8" /></>,
  arrow: <><path d="M5 12h14M12 5l7 7-7 7" /></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></>,
  box: <><path d="m12 3 9 5v8l-9 5-9-5V8l9-5Z M3 8l9 5 9-5 M12 13v8 M7.5 5.5l9 5" /></>,
  layers: <><path d="m12 3 10 5-10 5L2 8l10-5ZM2 12l10 5 10-5M2 16l10 5 10-5" /></>,
  factory: <><path d="M3 21V10l6 3V7l6 4V3h5l1 18H3ZM7 17h1m4 0h1m4 0h1" /></>,
  shield: <><path d="m12 3 8 3v6c0 4-4 7.5-8 9-4-1.5-8-5-8-9V6l8-3Z m-4 9 3 3 5-6" /></>,
  spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
  moon: <path d="M21 13a9 9 0 0 1-10-10A9 9 0 1 0 21 13Z" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  sliders: <><path d="M4 6h5m4 0h7M4 12h9m4 0h3M4 18h2m4 0h10" /><circle cx="11" cy="6" r="2" /><circle cx="15" cy="12" r="2" /><circle cx="8" cy="18" r="2" /></>,
  link: <><path d="m10 14 4-4m-5-1 3-3a4.24 4.24 0 0 1 6 6l-3 3m0 0-3 3a4.24 4.24 0 0 1-6-6l3-3" /></>,
  truck: <><path d="M3 5h12v12H3V5Zm12 5h4l3 4v3h-7" /><circle cx="7" cy="18" r="2" /><circle cx="18" cy="18" r="2" /></>,
};

export function Icon({ name, size = 20, className, style }: { name: IconName; size?: number; className?: string; style?: CSSProperties }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" className={className} style={style}>{paths[name]}</svg>;
}
