"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { marketplace, PublicProducer } from "../../lib/marketplace";
import { CapabilityDescription } from "../../components/CapabilityDescription";

export default function ProducerPage() {
  const params = useParams(); const id = typeof params.id === "string" ? params.id : "";
  const [producer, setProducer] = useState<PublicProducer | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (id) marketplace.getProducer(id).then(setProducer).catch((e: Error) => setError(e.message)); }, [id]);
  if (error) return <div className="alert alert-error">{error}</div>; if (!producer) return <p className="hint">Загрузка производителя...</p>;
  return <div className="producer-page"><section className="producer-hero">
    {producer.has_photo ? <figure className="producer-hero__media">
      <img src={marketplace.producerPhotoUrl(producer.company_id)} alt={`Производство ${producer.display_name}`} />
      <figcaption>Производство</figcaption>
    </figure> : <div className="product-placeholder">Фотография производства ещё не загружена</div>}
    <div className="producer-hero__copy"><span className="eyebrow">Проверенная компания</span><h1>{producer.display_name}</h1><p>{producer.region ?? "Россия"} · {producer.production_site_address ?? "Адрес производства доступен по запросу"}</p><p>{producer.about ?? "Информация о производстве уточняется."}</p><span className="badge badge-verified">{producer.rating ? `★ ${producer.rating} · отзывов ${producer.reviews_count}` : "Подтверждённых отзывов пока нет"}</span></div></section>
    {producer.capability_details && <section className="card producer-capabilities"><h2>Возможности и условия</h2><CapabilityDescription details={{ ...producer.capability_details }} /><p className="hint">Сведения предоставлены компанией. Выполнимость конкретного заказа требует подтверждения.</p></section>}
  </div>;
}
