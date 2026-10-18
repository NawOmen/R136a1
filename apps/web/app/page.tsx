"use client";

import Link from "next/link";
import { AgentStory } from "./components/AgentStory";
import { ProductPlaceholder } from "./components/ProductPlaceholder";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, AUTH_CHANGED_EVENT, getToken, MeResponse } from "./lib/api";
import { formatRub, formatUnits, itemUnit, marketplace, Product } from "./lib/marketplace";

function ProductShowcase({ products, loading, error, onRetry }: { products: Product[]; loading: boolean; error: boolean; onRetry: () => void }) {
  const featured: Product[] = [];
  const shownCategories = new Set<string>();
  for (const product of products) {
    if (!shownCategories.has(product.category)) {
      featured.push(product);
      shownCategories.add(product.category);
    }
    if (featured.length === 4) break;
  }
  for (const product of products) {
    if (featured.length === 4) break;
    if (!featured.some((item) => item.id === product.id)) featured.push(product);
  }
  return <section className="market-section">
    <div className="section-heading"><div><span className="eyebrow">Готовые предложения</span><h2>Товары российских производителей</h2></div><Link href="/catalog">Открыть весь каталог <span>→</span></Link></div>
    {error && <div className="alert alert-error" role="alert">Не удалось загрузить предложения.{products.length > 0 && " Показаны последние загруженные данные."} <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>Повторить загрузку</button></div>}
    {loading && products.length === 0 ? <p className="hint" role="status">Загружаем предложения...</p> : products.length ? <div className="product-grid product-grid--showcase">{featured.map((product) => <Link className="market-product" href={`/catalog/${product.id}`} key={product.id}>
      <div className="market-product__visual">{product.images[0] ? <img src={marketplace.productImageUrl(product.images[0].id)} alt={product.name} /> : <ProductPlaceholder />}<small>РОССИЯ</small></div>
      <div className="market-product__body"><strong className="market-price">{formatRub(product.price_rub, 12)}</strong><span className="market-muted">за {itemUnit(product.characteristics)} · от {formatUnits(product.moq_units, itemUnit(product.characteristics))}</span><h3>{product.name}</h3><span className="market-supplier">✓ Проверенный производитель</span><span className="market-product__cta">Подробнее</span></div>
    </Link>)}</div> : !error ? <div className="empty-market"><span aria-hidden="true">◫</span><div><b>Предложений пока нет</b><p>После добавления товаров здесь появятся актуальные предложения производителей.</p></div><Link className="btn btn-primary" href="/catalog">Перейти в каталог</Link></div> : null}
  </section>;
}

export default function HomePage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const router = useRouter();
  const [products, setProducts] = useState<Product[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState(false);
  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true); setCatalogError(false);
    try { setProducts(await marketplace.getCatalog()); }
    catch { setCatalogError(true); }
    finally { setCatalogLoading(false); }
  }, []);
  const [ready, setReady] = useState(false);
  const availableCategories = Array.from(new Set(products.map((product) => product.category))).slice(0, 8);

  useEffect(() => {
    void loadCatalog();
    const sync = () => {
      const token = getToken();
      if (!token) { setMe(null); setReady(true); return; }
      void api.me(token).then(setMe).catch(() => setMe(null)).finally(() => setReady(true));
    };
    sync(); window.addEventListener(AUTH_CHANGED_EVENT, sync);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, sync);
  }, [loadCatalog]);

  useEffect(() => { if (me) router.replace("/dashboard"); }, [me, router]);

  if (!ready) return <div className="market-loading"><span /><p>Открываем маркетплейс...</p></div>;

  if (me) return <div className="card"><h1>Продолжим работу</h1><p>Выберите компанию и задачу в личном кабинете.</p><Link href="/dashboard" className="btn btn-primary">Открыть кабинет</Link></div>;

  return <div className="market-home"><AgentStory landing>
    {availableCategories.length > 0 && <nav className="category-rail" aria-label="Категории каталога">{availableCategories.map((category) => <Link href={`/catalog?q=${encodeURIComponent(category)}`} key={category}>{category}</Link>)}</nav>}
    <ProductShowcase products={products} loading={catalogLoading} error={catalogError} onRetry={() => void loadCatalog()} />
  </AgentStory></div>;
}
