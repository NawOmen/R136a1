import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Закупки с ИИ — ПоРукам", description: "Опишите потребность. ИИ поможет подобрать производителей и подготовить условия закупки." };

export default function AiProcurementPage() {
  return <div className="procurement-page">
    <header className="procurement-heading"><span className="eyebrow">Помощник в закупках</span><h1>Закупки с ИИ</h1><p>Опишите, что нужно.<br />ИИ поможет найти подходящих производителей.</p><Link className="btn btn-primary" href="/needs/new">Создать потребность <span aria-hidden="true">↗</span></Link></header>
    <ol className="procurement-process">
      <li><span className="process-number">01</span><h2>Опишите задачу</h2><p>Текстом, голосом или файлом. Помощник соберёт характеристики, объём и срок.</p></li>
      <li><span className="process-number">02</span><h2>Сравните предложения</h2><p>Посмотрите подходящие товары и производителей, уточните условия.</p></li>
      <li><span className="process-number">03</span><h2>Подтвердите заказ</h2><p>Покупатель и производитель согласуют цену, объём и сроки.</p></li>
    </ol>
    <div className="procurement-note"><span aria-hidden="true">↳</span><p>ИИ готовит запрос и помогает с подбором.<br /><strong>Условия сделки подтверждают стороны.</strong></p><Link href="/how-it-works">Как это работает ↗</Link></div>
    <details className="procurement-details"><summary>Что ещё умеет помощник</summary><div><p>Находит совместимые запросы для объединённой закупки. Распределение объёма и стоимость рассчитывает система по данным участников.</p><p>Готовит черновики предложений и показывает источники данных. Недостающие сведения можно уточнить перед отправкой.</p><p>ИИ не назначает цену, мощность и резерв. Требования, отправку предложения, объединение заказа и резерв подтверждают участники. Документы и допуск проверяются отдельно.</p></div></details>
  </div>;
}
