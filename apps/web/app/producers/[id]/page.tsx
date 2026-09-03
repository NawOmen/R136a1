"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { marketplace, PublicProducer } from "../../lib/marketplace";

export default function ProducerPage() {
  const params = useParams(); const id = typeof params.id === "string" ? params.id : "";
  const [producer, setProducer] = useState<PublicProducer | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (id) marketplace.getProducer(id).then(setProducer).catch((e: Error) => setError(e.message)); }, [id]);
  if (error) return <div className="alert alert-error">{error}</div>; if (!producer) return <p className="hint">Загрузка производителя...</p>;
  return <div><section className="producer-hero">{producer.has_photo ? <img src={marketplace.producerPhotoUrl(producer.company_id)} alt={`Производство ${producer.display_name}`} /> : <div className="product-placeholder">Фотография производства ещё не загружена</div>}<div><span className="eyebrow">Проверенный производитель</span><h1>{producer.display_name}</h1><p>{producer.region ?? "Россия"} · {producer.production_site_address ?? "Адрес производства доступен по запросу"}</p><p>{producer.about ?? "Информация о производстве уточняется."}</p><span className="badge badge-verified">{producer.rating ? `★ ${producer.rating} · отзывов ${producer.reviews_count}` : "Подтверждённых отзывов пока нет"}</span></div></section></div>;
}
