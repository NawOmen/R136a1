"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getToken } from "./lib/api";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    router.replace(getToken() ? "/dashboard" : "/login");
  }, [router]);

  return <p className="hint">Перенаправление...</p>;
}
