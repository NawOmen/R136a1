"use client";

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { ProductPlaceholder } from "../components/ProductPlaceholder";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ProductAvailability } from "../components/ProductAvailability";
import { formatRub, formatUnits, catalogUnit, marketplace, Product } from "../lib/marketplace";

export default function CatalogPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Все категории");

  const loadCatalog = useCallback(async () => {
    setLoading(true); setError(null);
    try { setProducts(await marketplace.getCatalog()); }
    catch (err) { setError(err instanceof Error ? russianMessage(err.message) : "Не удалось загрузить каталог."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const initialQuery = new URLSearchParams(window.location.search).get("q") ?? "";
    setQuery(initialQuery);
    void loadCatalog();
  }, [loadCatalog]);

  const categories = useMemo(() => ["Все категории", ...Array.from(new Set(products.map((product) => product.category))).sort()], [products]);
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru");
    return products.filter((product) => (category === "Все категории" || product.category === category) && (!normalized || `${product.name} ${product.category} ${product.subcategory ?? ""}`.toLocaleLowerCase("ru").includes(normalized)));
  }, [products, category, query]);

  return <div className="market-page">
    <header className="market-page__head"><div><span className="eyebrow">Рынок предложений</span><h1>Каталог товаров</h1><p>Готовая продукция российских производителей с оптовыми условиями</p></div><Link href="/needs/new" className="btn btn-primary">+ Разместить потребность</Link></header>
    <div className="catalog-toolbar"><label className="catalog-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Название товара или категория" aria-label="Поиск товаров" /></label><span className="result-count" role="status">{loading ? "Загружаем предложения..." : error && products.length === 0 ? "Предложения не загружены" : `${visible.length} ${visible.length % 10 === 1 && visible.length % 100 !== 11 ? "товар" : visible.length % 10 >= 2 && visible.length % 10 <= 4 && !(visible.length % 100 >= 12 && visible.length % 100 <= 14) ? "товара" : "товаров"}`}</span></div>
    <nav className="category-rail category-rail--catalog" aria-label="Категории товаров">{categories.map((item) => <button type="button" className={category === item ? "active" : ""} aria-pressed={category === item} onClick={() => setCategory(item)} key={item}>{item}</button>)}</nav>
    {error && <div className="alert alert-error" role="alert">{error}{products.length > 0 && " Показаны последние загруженные предложения; актуальные условия уточняются."} <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadCatalog()}>Повторить загрузку</button></div>}
    {loading && products.length === 0 ? <div className="market-loading"><span /><p>Загружаем предложения...</p></div> : !error && visible.length === 0 ? <div className="empty-market"><span aria-hidden="true">⌕</span><div><b>Подходящих товаров пока нет</b><p>Измените запрос или создайте карточку потребности — производители смогут предложить условия.</p></div><Link className="btn btn-primary" href="/needs/new">Создать потребность</Link></div> : <div className="product-grid catalog-result-grid">{visible.map((product) => <Link className="market-product" href={`/catalog/${product.id}`} key={product.id}>
      <div className="market-product__visual"><div className="market-product__availability"><ProductAvailability product={product}/></div>{product.images[0] ? <img src={marketplace.productImageUrl(product.images[0].id)} alt={product.name} loading="lazy" decoding="async" /> : <ProductPlaceholder />}</div>
      <div className="market-product__body"><strong className="market-price"><small>от </small>{formatRub(product.price_rub, 12)}</strong><span className="market-muted">за {catalogUnit(product.characteristics)} · от {formatUnits(product.moq_units, catalogUnit(product.characteristics))}</span><h2>{product.name}</h2><p>{product.category}{product.subcategory ? ` · ${product.subcategory}` : ""}</p><div className="product-trust-row"><span className="market-supplier"><svg viewBox="0 0 20 20" width="15" height="15" fill="none" aria-hidden="true"><path d="m10 2 6 2v5c0 4-6 8-6 8s-6-4-6-8V4l6-2Z" stroke="currentColor" strokeWidth="1.5"/><path d="m7 9 2 2 4-4" stroke="currentColor" strokeWidth="1.5"/></svg>Проверенный производитель</span></div>{product.price_tiers[0] && <span className="volume-price">От {formatUnits(product.price_tiers[0].min_units, catalogUnit(product.characteristics))} — {formatRub(product.price_tiers[0].unit_price_rub)}/{catalogUnit(product.characteristics)}</span>}{product.quantity_conversion && <span className="market-muted">1 {product.quantity_conversion.from_unit} = {product.quantity_conversion.factor} {product.quantity_conversion.to_unit}</span>}<span className="market-product__cta">Открыть товар</span></div>
    </Link>)}</div>}
  </div>;
}
