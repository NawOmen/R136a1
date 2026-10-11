"use client";

// Общий хук сессии: текущий пользователь и его компании (GET /auth/me),
// а также селектор компании по праву «Покупаю» / «Продаю».

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, Company, getToken, User } from "./api";

export interface MeState {
  user: User | null;
  companies: Company[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

export function useMe(): MeState {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);

  const reload = useCallback(async () => {
    const current = ++generation.current;
    const token = getToken();
    if (!token) {
      setUser(null); setCompanies([]); setLoading(false);
      router.replace("/login");
      return;
    }
    try {
      const result = await api.me(token);
      if (generation.current !== current) return;
      setUser(result.user);
      setCompanies(result.companies);
      setError(null);
    } catch (err) {
      if (generation.current !== current) return;
      setUser(null); setCompanies([]);
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить данные аккаунта.");
    } finally {
      if (generation.current === current) setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void reload();
    return () => { generation.current += 1; };
  }, [reload]);

  return { user, companies, loading, error, reload };
}

// ---------- Селекторы компаний по правам ----------

export type CompanyPermission = "can_buy" | "can_sell";

export function companiesWith(companies: Company[], permission: CompanyPermission): Company[] {
  return companies.filter((company) => company.membership?.[permission] === true);
}

export function firstCompanyWith(companies: Company[], permission: CompanyPermission): Company | null {
  return companiesWith(companies, permission)[0] ?? null;
}

// Селектор компании с нужным правом: первая доступная по умолчанию,
// при нескольких — выбор через select на странице.
export function useCompanySelector(permission: CompanyPermission) {
  const me = useMe();
  const available = useMemo(() => companiesWith(me.companies, permission), [me.companies, permission]);
  const [companyId, setCompanyId] = useState<string>("");

  useEffect(() => {
    if (!me.loading && !available.some((company) => company.id === companyId)) {
      setCompanyId(available[0]?.id ?? "");
    }
  }, [me.loading, available, companyId]);

  const company = available.find((item) => item.id === companyId) ?? null;
  return { ...me, available, company, companyId, setCompanyId };
}
