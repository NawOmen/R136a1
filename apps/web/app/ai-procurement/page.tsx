import { LiquidSurface } from "../components/LiquidSurface";
import Link from "next/link";
import type { Metadata } from "next";
import { Icon } from "../components/Icon";
import { HeroObject } from "../components/HeroObject";

export const metadata: Metadata = { title: "Закупки с ИИ — ПоРукам", description: "Разбор потребности, проверяемые источники и программный расчёт закупки. Критичные действия подтверждает человек." };

const roles = [
  { title: "Требования", description: "Разбирает текст, файлы и фото. Собирает характеристики и показывает источники существенных полей.", limit: "Не выдумывает данные и не подтверждает спецификацию. Карточку проверяет покупатель." },
  { title: "Подбор производства", description: "Сопоставляет запрос с паспортами производителей. Показывает совпадения, различия и недостающие сведения.", limit: "Не назначает цену, мощность и резерв: их рассчитывает код по данным продавца. Черновик КП проверяет и отправляет продавец." },
  { title: "Предложение поставщика", description: "Готовит черновик КП с источниками: цена из каталога, объём из остатка или мощности, срок из товара.", limit: "Не придумывает цену и логистику. Недостающие условия заполняет продавец и подтверждает их перед отправкой." },
  { title: "Объединение и резерв", description: "Распределение объёма, стоимость резерва и варианты N-1/N-2 рассчитываются кодом и OR-Tools.", limit: "Обязательства возникают только после отдельного согласия каждого участника на свои условия." },
  { title: "Проверка допуска", description: "Проверяющий площадки оценивает документы, их применимость к товару, материал и покрытие.", limit: "Он не заменяет продавца и не подтверждает собственные документы. Допуск проверяется перед публикацией, сделкой, групповым обязательством и резервом." },
  { title: "Работа ИИ-агентов", description: "Запуски, готовые результаты, отправленные предложения, ошибки и длительность обработки видны в панели «Проверяемые показатели».", limit: "Администратор видит показатели всей площадки." },
];

export default function AiProcurementPage() {
  return <div className="guidance-page procurement-page">
    <LiquidSurface variant="procurement" className="guidance-hero procurement-hero">
      <div className="guidance-hero__copy">
        <h1>Закупки с ИИ</h1>
        <p className="guidance-lead">Помощь с требованиями и подбором. Решения — за вами.</p>
        <Link className="btn btn-primary toggle-motion" href="/needs/new">Создать потребность<Icon name="arrow" size={18} /></Link>
        <p className="guidance-note"><Icon name="shield" size={22} /><span>ИИ не меняет цену, мощность и резерв. Выгода не гарантирована — её проверяет расчёт.</span></p>
      </div>
      <HeroObject kind="procurement" />
    </LiquidSurface>
    <ol className="guidance-flow" aria-label="Порядок закупки">
      <li><h2>Опишите задачу</h2><p>Заполните условия вручную или разберите материалы с агентом.</p></li>
      <li><h2>Сравните варианты</h2><p>Проверьте предложения, источники и ограничения.</p></li>
      <li><h2>Подтвердите условия</h2><p>Каждая сторона согласует цену, объём, сроки и действия при недоборе.</p></li>
    </ol>
    <section className="guidance-roles" aria-labelledby="agent-roles-heading">
      <h2 id="agent-roles-heading">Как работают ИИ-закупки: роли и границы ответственности</h2>
      <div className="guidance-disclosures">{roles.map(role => <details className="guidance-disclosure" key={role.title}>
        <summary><span>{role.title}</span><Icon name="arrow" size={19} /></summary>
        <div className="guidance-disclosure__body"><p>{role.description}</p><p>{role.limit}</p></div>
      </details>)}</div>
    </section>
  </div>;
}
