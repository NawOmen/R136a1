export function serviceUrl(configured: string | undefined, port: number): string {
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    if (!configured || configured.includes("localhost") || configured.includes("127.0.0.1")) {
      return `${window.location.protocol}//${hostname}:${port}`;
    }
  }
  return configured || `http://localhost:${port}`;
}
