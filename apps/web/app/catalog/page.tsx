"use client";

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { LoadingText } from "../components/motion/LoadingText";
const MotionLink = motion.create(Link);
import { ProductPlaceholder } from "../components/ProductPlaceholder";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { scaledMoney } from "../lib/money";
import { ProductAvailability } from "../components/ProductAvailability";
import { formatRub, formatUnits, catalogUnit, isVisibleCategory, marketplace, Product } from "../lib/marketplace";

function priceValue(value: string): bigint | null {
  if (!value.trim()) return null;
  try { const price = scaledMoney(value.replace(/\s/g, "")); return price >= BigInt(0) ? price : null; } catch { return null; }
}

export default function CatalogPage() {
  const reduced = useReducedMotion();
  const categoryRail = useRef<HTMLElement>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Все категории");
  const [priceMin, setPriceMin] = useState("");
  const [priceMax, setPriceMax] = useState("");
  const [inStock, setInStock] = useState(false);
  const [leadTime, setLeadTime] = useState("");
  const [sort, setSort] = useState("newest");
  const minimum = priceValue(priceMin);
  const maximum = priceValue(priceMax);
  const priceError = (priceMin.trim() && minimum === null) || (priceMax.trim() && maximum === null)
    ? "Введите неотрицательную цену в рублях."
    : minimum !== null && maximum !== null && minimum > maximum ? "Цена «от» должна быть не больше цены «до»." : "";
  const filtersActive = Boolean(query || category !== "Все категории" || priceMin || priceMax || inStock || leadTime || sort !== "newest");
  const resetFilters = () => { setQuery(""); setCategory("Все категории"); setPriceMin(""); setPriceMax(""); setInStock(false); setLeadTime(""); setSort("newest"); categoryRail.current?.scrollTo({ left: 0, behavior: "instant" }); };

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

  const availableProducts = useMemo(() => products.filter(product => isVisibleCategory(product.category)), [products]);
  const categories = useMemo(() => ["Все категории", ...Array.from(new Set(availableProducts.map((product) => product.category))).sort()], [availableProducts]);
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru");
    const filtered = availableProducts.filter((product) => {
      if (category !== "Все категории" && product.category !== category) return false;
      if (normalized && !`${product.name} ${product.category} ${product.subcategory ?? ""}`.toLocaleLowerCase("ru").includes(normalized)) return false;
      if (inStock && (product.available_stock_units == null || product.available_stock_units < product.moq_units)) return false;
      if (leadTime && product.lead_time_days > Number(leadTime)) return false;
      const price = scaledMoney(product.price_rub);
      return Boolean(priceError) || ((minimum === null || price >= minimum) && (maximum === null || price <= maximum));
    });
    return filtered.sort((a, b) => {
      if (sort === "price-asc" || sort === "price-desc") {
        const left = scaledMoney(a.price_rub), right = scaledMoney(b.price_rub);
        return (left < right ? -1 : left > right ? 1 : 0) * (sort === "price-desc" ? -1 : 1);
      }
      if (sort === "lead") return a.lead_time_days - b.lead_time_days;
      return 0; // API order is newest first; stable sorting preserves it.
    });
  }, [availableProducts, category, query, inStock, leadTime, sort, minimum, maximum, priceError]);


  return <div className="market-page commercial-catalog">
    <header className="catalog-heading"><h1>Каталог товаров</h1><p>Если нужного нет, опишите потребность в разделе <Link href="/ai-procurement">«Закупки с ИИ»</Link>.</p></header>
    <div className="catalog-toolbar"><label className="catalog-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Название товара или категория" aria-label="Поиск товаров" /></label><span className="result-count" role="status">{loading ? "Загружаем предложения..." : error && products.length === 0 ? "Предложения не загружены" : `${visible.length} ${visible.length % 10 === 1 && visible.length % 100 !== 11 ? "товар" : visible.length % 10 >= 2 && visible.length % 10 <= 4 && !(visible.length % 100 >= 12 && visible.length % 100 <= 14) ? "товара" : "товаров"}`}</span></div>
    <nav ref={categoryRail} className="category-rail category-rail--catalog" aria-label="Категории товаров">{categories.map((item) => <motion.button whileTap={reduced ? undefined : { scale: .97 }} transition={{ type: "spring", stiffness: 420, damping: 32 }} type="button" className={category === item ? "active" : ""} aria-pressed={category === item} onClick={() => setCategory(item)} key={item}>{item}</motion.button>)}</nav>
    <details className="catalog-filters"><summary>Фильтры и сортировка{filtersActive && <span>Есть выбранные условия</span>}</summary><div className="catalog-filter-panel" role="group" aria-label="Фильтры товаров">
      <fieldset className="catalog-price-filter"><legend>Цена за единицу, ₽</legend><div><input inputMode="decimal" aria-label="Цена от, ₽" aria-invalid={Boolean(priceError)} aria-describedby={priceError ? "catalog-price-error" : undefined} placeholder="От" value={priceMin} onChange={event => setPriceMin(event.target.value)} /><span aria-hidden="true">—</span><input inputMode="decimal" aria-label="Цена до, ₽" aria-invalid={Boolean(priceError)} aria-describedby={priceError ? "catalog-price-error" : undefined} placeholder="До" value={priceMax} onChange={event => setPriceMax(event.target.value)} /></div></fieldset>
      <label className="catalog-select-filter"><span>Срок производства</span><select value={leadTime} onChange={event => setLeadTime(event.target.value)}><option value="">Любой</option><option value="7">До 7 дней</option><option value="14">До 14 дней</option><option value="30">До 30 дней</option></select></label>
      <label className="catalog-select-filter"><span>Сортировка</span><select value={sort} onChange={event => setSort(event.target.value)}><option value="newest">Сначала новые</option><option value="price-asc">Сначала дешевле</option><option value="price-desc">Сначала дороже</option><option value="lead">По сроку производства</option></select></label>
      <div className="catalog-filter-actions"><label><input type="checkbox" checked={inStock} onChange={event => setInStock(event.target.checked)} />Только в наличии</label><button type="button" className="btn btn-secondary btn-sm" disabled={!filtersActive} onClick={resetFilters}>Сбросить фильтры</button></div>
      {priceError && <p id="catalog-price-error" className="catalog-filter-error" role="alert">{priceError}</p>}
    </div></details>
    {error && <div className="alert alert-error" role="alert">{error}{products.length > 0 && " Показаны последние загруженные предложения; актуальные условия уточняются."} <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadCatalog()}>Повторить загрузку</button></div>}
    {loading && products.length === 0 ? <div className="market-loading"><span className="market-loading__spinner" aria-hidden="true" /><LoadingText text="Загружаем предложения…" /></div> : !error && visible.length === 0 ? <div className="empty-market"><span aria-hidden="true">⌕</span><div><b>Подходящих товаров пока нет</b><p>Измените фильтры или создайте потребность — производители смогут предложить условия.</p></div><div className="actions"><Link className="btn btn-primary" href="/needs/new">Создать потребность</Link></div></div> : <div className="product-grid catalog-result-grid">{visible.map((product) => <MotionLink layout={reduced ? false : "position"} initial={{ opacity: .65 }} animate={{ opacity: 1 }} whileHover={reduced ? undefined : { y: -3 }} whileTap={reduced ? undefined : { scale: .99 }} transition={{ layout: { type: "spring", stiffness: 310, damping: 34 }, opacity: { duration: reduced ? 0 : .22 }, y: { duration: .2 } }} className="market-product" href={`/catalog/${product.id}`} key={product.id}>
      <div className="market-product__visual"><div className="market-product__availability"><ProductAvailability product={product}/></div>{product.images[0] ? <img src={marketplace.productImageUrl(product.images[0].id)} alt={product.name} loading="lazy" decoding="async" /> : <ProductPlaceholder />}</div>
      <div className="market-product__body"><strong className="market-price"><small>от </small>{formatRub(product.price_rub, 12)}</strong><span className="market-muted">за {catalogUnit(product.characteristics)} · от {formatUnits(product.moq_units, catalogUnit(product.characteristics))}</span><h2>{product.name}</h2><p>{product.category}{product.subcategory ? ` · ${product.subcategory}` : ""}</p><div className="product-trust-row"><span className="market-supplier"><svg viewBox="0 0 20 20" width="15" height="15" fill="none" aria-hidden="true"><path d="m10 2 6 2v5c0 4-6 8-6 8s-6-4-6-8V4l6-2Z" stroke="currentColor" strokeWidth="1.5"/><path d="m7 9 2 2 4-4" stroke="currentColor" strokeWidth="1.5"/></svg>Проверенный производитель</span></div>{product.price_tiers[0] && <span className="volume-price">От {formatUnits(product.price_tiers[0].min_units, catalogUnit(product.characteristics))} — {formatRub(product.price_tiers[0].unit_price_rub)}/{catalogUnit(product.characteristics)}</span>}{product.quantity_conversion && <span className="market-muted">1 {product.quantity_conversion.from_unit} = {product.quantity_conversion.factor} {product.quantity_conversion.to_unit}</span>}<span className="market-product__cta">Подробнее <span aria-hidden="true">↗</span></span></div>
    </MotionLink>)}</div>}
  </div>;
}
