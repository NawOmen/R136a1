"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { formatCharacteristics, formatRub, formatUnits, itemUnit, marketplace, PriceIndexPoint, ProductAdmissionChecklist, PublicProductDetail } from "../../lib/marketplace";

export default function ProductDetailPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [product, setProduct] = useState<PublicProductDetail | null>(null);
  const [index, setIndex] = useState<PriceIndexPoint[]>([]);
  const [admission, setAdmission] = useState<ProductAdmissionChecklist | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    marketplace.getProductDetail(id).then((item) => { setProduct(item); return marketplace.getPriceIndex(item.category, item.id); }).then(setIndex).catch((reason: Error) => setError(reason.message));
    // Чек-лист допуска справочный: он показывает только состояния требований,
    // без имён файлов и внутренних идентификаторов документов.
    marketplace.getProductAdmission(id).then(setAdmission).catch(() => setAdmission(null));
  }, [id]);

  if (error) return <div className="alert alert-error">{error}</div>;
  if (!product) return <div className="market-loading"><span /><p>Загружаем карточку товара...</p></div>;

  return <div className="product-page">
    <nav className="breadcrumbs" aria-label="Навигационная цепочка"><Link href="/catalog">Каталог</Link><span>›</span><Link href={`/catalog?q=${encodeURIComponent(product.category)}`}>{product.category}</Link><span>›</span><span>{product.name}</span></nav>
    <div className="product-detail product-detail--market">
      <section className="product-gallery">{product.images[0] ? <img className="product-hero" src={marketplace.productImageUrl(product.images[0].id)} alt={product.name} /> : <div className="product-placeholder"><b>{product.category.slice(0, 1)}</b><span>Производитель добавляет фото</span></div>}<span className="made-in-russia">ПРОИЗВЕДЕНО В РОССИИ</span></section>
      <section className="product-buybox"><span className="eyebrow">{product.category}{product.subcategory ? ` · ${product.subcategory}` : ""}</span><h1>{product.name}</h1><p className="product-characteristics">{formatCharacteristics(product.characteristics, product.category_profile)}</p><div className="product-price"><strong>{formatRub(product.price_rub)}</strong><span>за единицу</span></div><div className="product-order-facts"><div><span>Минимальный заказ</span><b>{formatUnits(product.moq_units, itemUnit(product.characteristics))}</b></div><div><span>Срок производства</span><b>от {product.lead_time_days} дней</b></div></div>{product.price_tiers.length > 0 && <div className="pricing"><span className="pricing-title">Оптовые цены</span>{product.price_tiers.map((tier) => <div key={tier.min_units}><span>От {formatUnits(tier.min_units, itemUnit(product.characteristics))}</span><b>{formatRub(tier.unit_price_rub)} / {itemUnit(product.characteristics)}</b></div>)}</div>}<Link className="btn btn-primary product-main-action" href="/needs/new">Запросить условия</Link><p className="safe-note">Условия сделки подтверждаются обеими сторонами. Площадка не меняет цену автоматически.</p></section>
    </div>
    <section className="supplier-panel"><div className="supplier-mark">{product.producer.display_name.slice(0, 1)}</div><div><span className="eyebrow">Проверенный производитель</span><h2>{product.producer.display_name}</h2><p>{product.producer.region ?? "География производства уточняется"} · {product.producer.rating ? `★ ${product.producer.rating} · ${product.producer.reviews_count} отзывов` : "Новый поставщик без отзывов"}</p></div><Link className="btn btn-secondary" href={`/producers/${product.producer.company_id}`}>Профиль компании</Link></section>
    <div className="product-info-grid"><section className="card"><span className="eyebrow">Получение партии</span><h2>Доставка и ответственность</h2><p>Вес и объём фиксируются в сделке. Покупатель выбирает самовывоз, своего перевозчика или согласованную доставку продавца. «ПоРукам» помогает оформить процесс, но не оказывает транспортные услуги.</p></section><section className="card"><span className="eyebrow">Допуск товара</span><h2>Обязательные доказательства</h2>{admission && admission.checklist.length > 0 ? <><p className="hint">Проверено у продавца: {admission.state_label.toLowerCase()}.</p><ul className="company-list">{admission.checklist.map((item) => <li key={item.code}><div className="company-row"><div><div className="company-item__name">{item.title}</div><div className="company-meta">{item.legal_reference}</div><div className="company-meta">{item.buyer_note}</div>{item.scope_note && <div className="company-meta">Применимость: {item.scope_note}</div>}</div><span className={`badge ${item.state === "satisfied" ? "badge-verified" : "badge-rejected"}`}>{item.state_label}</span></div></li>)}</ul>{admission.advisories.map((text) => <p className="hint" key={text}>Уточните у продавца: {text}</p>)}<p className="hint">{admission.note}</p></> : <p className="hint">{admission?.supported === false ? admission.summary : "Для этой категории правила проверки документов ещё не настроены. Проверка компании не подтверждает соответствие товара."}</p>}</section><section className="card"><span className="eyebrow">Цены продавца</span><h2>История цены товара</h2><p className="hint">Последняя опубликованная цена дня для этой карточки с теми же характеристиками и минимальным заказом. Это цены предложений, а не совершённых продаж.</p>{index.length ? <div className="price-index">{index.map((point) => <div key={point.date}><span>{point.date}</span><b>{formatRub(point.average_unit_price_rub)}</b><small>{point.offers_count} набл.</small></div>)}</div> : <p className="hint">История появится после изменения цен опубликованных товаров. История справочная и не является прогнозом.</p>}</section></div>
  </div>;
}
