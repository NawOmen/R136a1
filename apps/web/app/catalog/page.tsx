"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, Company, getToken } from "../lib/api";
import { formatRub, formatUnits, marketplace, Product } from "../lib/marketplace";

export default function CatalogPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [myCompanies, setMyCompanies] = useState<Company[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Все категории");

  useEffect(() => {
    const initialQuery = new URLSearchParams(window.location.search).get("q") ?? "";
    setQuery(initialQuery);
    marketplace.getCatalog().then(setProducts).catch((err: unknown) => setError(err instanceof Error ? err.message : "Не удалось загрузить каталог.")).finally(() => setLoading(false));
    const token = getToken();
    if (token) void api.me(token).then((result) => setMyCompanies(result.companies)).catch(() => undefined);
  }, []);

  const categories = useMemo(() => ["Все категории", ...Array.from(new Set(products.map((product) => product.category))).sort()], [products]);
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru");
    return products.filter((product) => (category === "Все категории" || product.category === category) && (!normalized || `${product.name} ${product.category} ${product.subcategory ?? ""}`.toLocaleLowerCase("ru").includes(normalized)));
  }, [products, category, query]);

  function companyName(companyId: string): string {
    return myCompanies.find((company) => company.id === companyId)?.display_name ?? "Проверенный производитель";
  }

  return <div className="market-page">
    <header className="market-page__head"><div><span className="eyebrow">Рынок предложений</span><h1>Каталог товаров</h1><p>Готовая продукция российских производителей с оптовыми условиями</p></div><Link href="/needs/new" className="btn btn-primary">+ Разместить потребность</Link></header>
    <div className="catalog-toolbar"><label className="catalog-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Название товара или категория" aria-label="Поиск товаров" /></label><span className="result-count">{visible.length} {visible.length === 1 ? "товар" : "товаров"}</span></div>
    <nav className="category-rail category-rail--catalog" aria-label="Категории товаров">{categories.map((item) => <button type="button" className={category === item ? "active" : ""} onClick={() => setCategory(item)} key={item}>{item}</button>)}</nav>
    {error && <div className="alert alert-error">{error}</div>}
    {loading ? <div className="market-loading"><span /><p>Загружаем предложения...</p></div> : !error && visible.length === 0 ? <div className="empty-market"><span aria-hidden="true">⌕</span><div><b>Подходящих товаров пока нет</b><p>Измените запрос или создайте карточку потребности — производители смогут предложить условия.</p></div><Link className="btn btn-primary" href="/needs/new">Создать потребность</Link></div> : <div className="product-grid">{visible.map((product) => <Link className="market-product" href={`/catalog/${product.id}`} key={product.id}>
      <div className="market-product__visual">{product.images[0] ? <img src={marketplace.productImageUrl(product.images[0].id)} alt={product.name} /> : <span aria-hidden="true">{product.category.slice(0, 1)}</span>}<small>РОССИЯ</small></div>
      <div className="market-product__body"><strong className="market-price">{formatRub(product.price_rub)}</strong><span className="market-muted">за единицу · MOQ {formatUnits(product.moq_units)}</span><h2>{product.name}</h2><p>{product.category}{product.subcategory ? ` · ${product.subcategory}` : ""}</p><span className="market-supplier">★ {companyName(product.company_id)}</span>{product.price_tiers[0] && <span className="volume-price">От {formatUnits(product.price_tiers[0].min_units)} — {formatRub(product.price_tiers[0].unit_price_rub)}/шт.</span>}<span className="market-product__cta">Открыть товар</span></div>
    </Link>)}</div>}
  </div>;
}
