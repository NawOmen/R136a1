import Link from "next/link";
import { formatRub, formatUnits, itemUnit, marketplace, primaryProductImage, Product } from "../lib/marketplace";
import { Icon } from "./Icon";

export function ProductCard({ product, headingLevel = 3, manufacturerVerified = false, favorite = false, onFavorite }: {
  product: Product; supplier?: string; headingLevel?: 2 | 3; manufacturerVerified?: boolean; favorite?: boolean; onFavorite?: () => void;
}) {
  const unit = itemUnit(product.characteristics), Heading = headingLevel === 2 ? "h2" : "h3";
  const photo = primaryProductImage(product.images);
  return <article className="market-product">
    <Link className="market-product__link" href={"/catalog/" + product.id}>
      <div className="market-product__visual">
        {photo ? <img src={marketplace.productImageUrl(photo.id)} alt={product.name} loading="lazy" decoding="async" /> : <div className="product-no-photo"><Icon name="layers" size={36} /><span>Без фотографии</span></div>}
        {photo?.file_name.startsWith("Иллюстрация товара:") && <small className="product-image-note">Иллюстрация</small>}
      </div>
      <div className="market-product__body">
        <Heading>{product.name}</Heading>
        <div className="product-pricing"><strong className="market-price">{formatRub(product.price_rub, 12)}</strong><span className="market-muted">/ {unit}</span></div>
        {manufacturerVerified ? <div className="manufacturer-status"><Icon name="check" size={14} /><span>Проверенный производитель</span></div> : <div className="product-conditions">От {formatUnits(product.moq_units, unit)}</div>}
        <span className="product-open" aria-hidden="true"><Icon name="arrow" size={18} /></span>
      </div>
    </Link>
    {onFavorite && <button className="product-favorite" type="button" title="Сохраняется в этом браузере" aria-label={(favorite ? "Убрать из избранного: " : "В избранное: ") + product.name} aria-pressed={favorite} onClick={onFavorite}><Icon name="heart" size={20} /></button>}
  </article>;
}
