import type { Metadata } from "next";
import { notFound } from "next/navigation";

const pages: Record<string, {title: string; body: string}> = {
  about: {title: "О компании", body: "ПоРукам — российский Маркетплейс для бизнеса совместных закупок и производственных предложений."},
  news: {title: "Новости", body: "На площадке доступны карточки потребностей, объединённые партии и контроль устойчивости сделок."},
  contacts: {title: "Контакты", body: "Обратитесь через форму поддержки в личном кабинете. Укажите номер сделки или потребности и опишите ваш вопрос."},
  guide: {title: "Инструкция", body: "Зарегистрируйтесь, создайте компанию, выберите режим «Покупаю» или «Продаю» и следуйте подсказкам в личном кабинете."},
  regulations: {title: "Регламенты", body: "Публикация товаров доступна верифицированным компаниям. Критичные условия сделок требуют явного подтверждения участника."},
  legal: {title: "Правила работы", body: "Площадка предназначена для российских компаний. Цены указываются в рублях. Условия предложения, приёмку, возврат и отмену участники подтверждают в карточке сделки. Помощник готовит предложения, а решения принимают участники."},
  privacy: {title: "Конфиденциальность", body: "Документы компании, переписка и исполнение заказа доступны в соответствующих разделах кабинета с проверкой прав. Себестоимость и расчётная прибыль видны только участникам компании-продавца. По вопросам доступа к данным обратитесь в поддержку."},
};

export async function generateMetadata({params}: {params: Promise<{slug: string}>}): Promise<Metadata> {
  const {slug} = await params;
  const page = pages[slug];
  return page ? { title: `${page.title} — ПоРукам`, description: page.body } : { title: "Страница не найдена — ПоРукам" };
}

export default async function InfoPage({params}: {params: Promise<{slug: string}>}) {
  const {slug} = await params; const page = pages[slug]; if (!page) notFound();
  return <article className="card prose"><h1>{page.title}</h1><p>{page.body}</p></article>;
}
