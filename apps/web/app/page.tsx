"use client";

import Link from "next/link";
import { AgentStory } from "./components/AgentStory";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, AUTH_CHANGED_EVENT, getToken, MeResponse } from "./lib/api";
export default function HomePage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const sync = () => {
      const token = getToken();
      if (!token) { setMe(null); setReady(true); return; }
      void api.me(token).then(setMe).catch(() => setMe(null)).finally(() => setReady(true));
    };
    sync(); window.addEventListener(AUTH_CHANGED_EVENT, sync);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, sync);
  }, []);

  useEffect(() => { if (me) router.replace("/dashboard"); }, [me, router]);

  if (!ready) return <div className="market-loading"><span /><p>Открываем маркетплейс...</p></div>;

  if (me) return <div className="card"><h1>Продолжим работу</h1><p>Выберите компанию и задачу в личном кабинете.</p><Link href="/dashboard" className="btn btn-primary">Открыть кабинет</Link></div>;

  return <div className="market-home"><AgentStory landing /></div>;
}
