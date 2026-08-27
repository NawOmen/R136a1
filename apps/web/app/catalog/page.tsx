"use client";

// Публичный каталог товаров (GET /products). Доступен без входа;
// «Создать потребность» ведёт в форму, которая при необходимости попросит войти.

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Company, getToken } from "../lib/api";
import {
  formatCharacteristics,
  formatRub,
  formatUnits,
  marketplace,
  Product,
} from "../lib/marketplace";

export default function CatalogPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [myCompanies, setMyCompanies] = useState<Company[]>([]);

  useEffect(() => {
    marketplace
      .getCatalog()
      .then(setProducts)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Не удалось загрузить каталог."),
      )
      .finally(() => setLoading(false));

    // Если пользователь вошёл — показываем названия его компаний как продавцов.
    const token = getToken();
    if (token) {
      api
        .me(token)
        .then((result) => setMyCompanies(result.companies))
        .catch(() => {
          // каталог остаётся публичным
        });
    }
  }, []);

  function companyName(companyId: string): string {
    const mine = myCompanies.find((company) => company.id === companyId);
    if (mine) return mine.display_name;
    return `Компания ${companyId.slice(0, 8)}`;
  }

  if (loading) return <p className="hint">Загрузка каталога...</p>;

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Каталог товаров</h1>
        <Link href="/needs/new" className="btn btn-primary btn-sm">
          Создать потребность
        </Link>
      </div>
      <p className="subtitle">Публичный каталог производителей</p>

      {error && <div className="alert alert-error">{error}</div>}

      {!error && products.length === 0 ? (
        <p className="hint">В каталоге пока нет опубликованных товаров.</p>
      ) : (
        <ul className="company-list">
          {products.map((product) => (
            <li key={product.id} className="card">
              <div className="company-row">
                <div>
                  <div className="company-item__name">{product.name}</div>
                  <div className="company-meta">Категория: {product.category}</div>
                  <div className="company-meta">Продавец: {companyName(product.company_id)}</div>
                </div>
                <span className="badge badge-verified">{formatRub(product.price_rub)}</span>
              </div>
              <p className="hint mode-hint">{formatCharacteristics(product.characteristics)}</p>
              <p className="hint mode-hint">
                Мин. заказ: {formatUnits(product.moq_units)} · Срок: {product.lead_time_days} дн.
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
