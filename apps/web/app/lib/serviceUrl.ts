export function serviceUrl(configured: string | undefined, port: number): string {
  if (typeof window !== "undefined") {
    if (window.location.protocol === "https:") {
      const paths: Record<number, string> = { 8001: "/gateway", 8002: "/marketplace", 8003: "/llm" };
      if (paths[port]) return paths[port];
    }
    const hostname = window.location.hostname;
    if (!configured || configured.includes("localhost") || configured.includes("127.0.0.1")) {
      return `${window.location.protocol}//${hostname}:${port}`;
    }
  }
  return configured || `http://localhost:${port}`;
}
