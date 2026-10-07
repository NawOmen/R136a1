/** Explicit service endpoints keep their ports; defaults support a LAN hostname. */
export function serviceUrl(configured: string | undefined, port: number): string {
  if (configured) {
    if (typeof window === "undefined") return configured.replace(/\/$/, "");
    const url = new URL(configured, window.location.origin);
    const loopback = (host: string) => host === "localhost" || host === "127.0.0.1" || host === "[::1]";
    if (loopback(url.hostname) && window.location.protocol === "https:" && !loopback(window.location.hostname)) {
      const paths: Record<number, string> = { 8001: "/gateway", 8002: "/marketplace", 8003: "/llm" };
      if (paths[port]) return paths[port];
    }
    if (loopback(url.hostname) && !loopback(window.location.hostname)) url.hostname = window.location.hostname;
    return url.toString().replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    if (window.location.protocol === "https:") {
      const paths: Record<number, string> = { 8001: "/gateway", 8002: "/marketplace", 8003: "/llm" };
      if (paths[port]) return paths[port];
    }
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
  }
  return `http://localhost:${port}`;
}
