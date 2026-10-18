import { russianLabel } from "../lib/presentation";
import { Fragment } from "react";
const labels:Record<string,string>={label:"Название",type:"Тип значения",aliases:"Допустимые названия",unit:"Единица свойства",positive:"Только положительные значения",max_length:"Максимальная длина",identification:"Идентификация",units:"Единицы заказа",producer:"Производитель",commercial:"Коммерческие условия",resource:"Учёт ресурсов",documents:"Документы и применимость",compatibility:"Совместимость",logistics:"Доставка",acceptance:"Приёмка",repeat:"Повтор заказа",sources:"Источники",update_policy:"Порядок обновления",required:"Обязательные свойства",optional:"Дополнительные свойства",basis:"Основание",allowed:"Допустимые единицы",legacy_default:"Единица прежних записей",quantity_step:"Шаг в меньшей единице",fraction_policy:"Точность",pack_conversion:"Пересчёт упаковки",process:"Процесс",evidence:"Основание возможностей",price_basis:"Цена",tax_values:"Налоговая база",tax_unknown:"Если налоговая база неизвестна",moq:"Минимальный заказ",tiers:"Ценовые ступени",stock:"Склад",capacity:"Мощность",shared:"Общий ресурс",scope:"Область применимости",expiry:"Срок действия",revocation:"Отзыв",regulatory_candidates:"Правила, применимость которых проверяет редактор",legal_state:"Состояние экспертизы",hard_fields:"Жёсткие свойства",comparison:"Сравнение",individual_fields:"Индивидуальные свойства",analogue:"Замены",coalition:"Совместный заказ",risk:"Особенности перевозки",region:"Регион",conditions:"Условия",checks:"Проверки",unknown:"Недостаточно данных",exceptions:"Несоответствия",new_draft:"Создавать новый черновик",revalidate:"Повторно проверять условия",copy_approvals:"Переносить прежние согласия",copy_documents:"Переносить прежний допуск",required_when:"Зависимости свойств",field:"Свойство",values:"При значениях",review_required:"Проверка редактором обязательна"};
const risks:Record<string,string>={text:"Текст",number:"Число",integer:"Целое число",food_contact:"Контакт с пищевыми продуктами",cold_chain:"Температурный режим",fragile:"Хрупкий груз",chemical:"Химическая продукция",standard:"Обычные согласованные условия",heavy:"Тяжёлый груз",textile:"Сохранность текстильных изделий"};
export function RuleValue({value,fields={}}:{value:unknown;fields?:Record<string,{label:string}>}) {
  if(value===null || value===undefined)return <>Не было задано</>;
  if(typeof value==="boolean")return <>{value?"Да":"Нет"}</>;
  if(typeof value==="string")return <>{fields[value]?.label ?? risks[value] ?? russianLabel(value, value)}</>;
  if(typeof value==="number")return <>{value}</>;
  if(Array.isArray(value))return <ul>{value.map((item,index)=><li key={index}><RuleValue value={item} fields={fields} /></li>)}</ul>;
  if(typeof value==="object") {
    const item=value as Record<string,unknown>;
    if(typeof item.url==="string" || typeof item.path==="string")return <>{typeof item.scope==="string" && <p>{item.scope}</p>}{typeof item.url==="string" && /^https:\/\//.test(item.url)?<a href={item.url} target="_blank" rel="noreferrer">Открыть первичный источник</a>:typeof item.path==="string"?<span>Документ проекта: {item.path}</span>:null}</>;
    return <dl>{Object.entries(item).filter(([key])=>labels[key] || fields[key]).map(([key,v])=><Fragment key={key}><dt>{labels[key] ?? fields[key]?.label}</dt><dd><RuleValue value={v} fields={fields} /></dd></Fragment>)}</dl>;
  }
  return null;
}
export default function CategoryPassportDetails({passport,fields}:{passport:Record<string,unknown>;fields?:Record<string,{label:string}>}) {
  return <RuleValue value={passport} fields={fields} />;
}
