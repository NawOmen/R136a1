"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { formatCharacteristics, formatRub, formatUnits, marketplace, PriceIndexPoint, PublicProductDetail } from "../../lib/marketplace";

export default function ProductDetailPage() {
  const params = useParams(); const id = typeof params.id === "string" ? params.id : "";
  const [product, setProduct] = useState<PublicProductDetail | null>(null); const [index, setIndex] = useState<PriceIndexPoint[]>([]); const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (!id) return; marketplace.getProductDetail(id).then((item) => { setProduct(item); return marketplace.getPriceIndex(item.category); }).then(setIndex).catch((e: Error) => setError(e.message)); }, [id]);
  if (error) return <div className="alert alert-error">{error}</div>; if (!product) return <p className="hint">Загрузка товара...</p>;
  return <div><Link href="/catalog">← Каталог</Link><div className="product-detail"><section>{product.images[0] ? <img className="product-hero" src={marketplace.productImageUrl(product.images[0].id)} alt={product.name} /> : <div className="product-placeholder">Фото готовится</div>}</section><section className="card"><span className="eyebrow">{product.category}{product.subcategory ? ` / ${product.subcategory}` : ""}</span><h1>{product.name}</h1><p>{formatCharacteristics(product.characteristics)}</p><h2>{formatRub(product.price_rub)} за шт.</h2><p>Минимальный заказ: {formatUnits(product.moq_units)} · производство от {product.lead_time_days} дней</p><div className="pricing">{product.price_tiers.map((tier) => <div key={tier.min_units}>От {formatUnits(tier.min_units)} — <b>{formatRub(tier.unit_price_rub)} за шт.</b></div>)}</div><Link className="btn btn-primary" href="/needs/new">Запросить условия</Link></section></div>
    <section className="card"><div className="company-row"><div><h2>{product.producer.display_name}</h2><p className="hint">{product.producer.region ?? "География уточняется"} · {product.producer.rating ? `★ ${product.producer.rating} (${product.producer.reviews_count})` : "Пока без отзывов"}</p></div><Link href={`/producers/${product.producer.company_id}`}>Страница производителя →</Link></div><p>{product.producer.about ?? "Проверенный российский производитель. Подробности доступны в профиле."}</p></section>
    <section className="card"><h2>Получение и доставка</h2><p>Точные вес и объём партии фиксируются в сделке. ПоРукам определяет маршрут оформления и чек-лист, а покупатель выбирает самовывоз, перевозчика или согласованную доставку продавца. Площадка не оказывает транспортные услуги.</p></section>
    <section className="card"><h2>Индекс цен категории</h2>{index.length ? <div className="price-index">{index.map((point) => <div key={point.date}><span>{point.date}</span><b>{formatRub(point.average_unit_price_rub)}</b><small>{point.offers_count} набл.</small></div>)}</div> : <p className="hint">История появится после изменения цен опубликованных товаров. Индекс — справочный, не прогноз.</p>}</section></div>;
}
