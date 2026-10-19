"""Explicit local-only photo catalogue fixture. Never runs on service startup.

All companies, stock and admission PDFs are synthetic. The normal publication
checks still run; fixture verification does not certify real goods.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text

from app.api.products import publish_product
from app.deps import CurrentUser
from app.category_admission import characteristic_value, match_profile
from app.category_runtime import current_registry_context
from app.database import SessionLocal
from app.file_safety import validate_upload
from app.models import Document, Product, ProductImage
from app.schemas import PublishIn
from app.storage import upload_object
from seed import SELLER_COMPANY_NAME, synthetic_document_pdf
from seed_assortment import NAMESPACE


async def seed_catalog(asset_dir: Path) -> int:
    if os.getenv("ENABLE_DEMO_SEED", "false").lower() != "true":
        raise RuntimeError("Only enabled for explicitly configured synthetic local data")
    entries = json.loads((asset_dir / "prompts.json").read_text())
    # Validate every asset before changing the database.
    for entry in entries:
        if Path(entry["file"]).name != entry["file"] or not (asset_dir / entry["file"]).is_file():
            raise RuntimeError(f"Missing catalogue photo: {entry['key']}")
        await validate_upload((asset_dir / entry["file"]).read_bytes(), "image/webp")
    async with SessionLocal() as db, current_registry_context(db):
        seller = (await db.execute(text(
            "SELECT c.id, m.user_id FROM auth.companies c JOIN auth.company_members m ON m.company_id=c.id "
            "WHERE c.display_name=:name AND m.can_sell=true AND m.is_admin=true ORDER BY m.user_id LIMIT 1"
        ), {"name": SELLER_COMPANY_NAME})).first()
        admin_id = await db.scalar(text("SELECT id FROM auth.users WHERE is_marketplace_admin=true AND account_status='active' ORDER BY created_at LIMIT 1"))
        if seller is None or admin_id is None:
            raise RuntimeError("Synthetic seller and active local administrator are required")
        company_id, user_id = seller
        for entry in entries:
            key = entry["key"]
            if key in ("cup_350", "cup_400"):
                volume = 350 if key == "cup_350" else 400
                products = (await db.scalars(select(Product).where(Product.company_id == company_id))).all()
                matches = [p for p in products if p.name == f"Стакан {volume} мл PE" and p.created_by_user_id == user_id]
                if len(matches) != 1:
                    raise RuntimeError(f"Expected exactly one original synthetic cup: {key}")
                product = matches[0]
            else:
                product = await db.get(Product, uuid.uuid5(NAMESPACE, f"{company_id}:{key}"))
            if product is None:
                raise RuntimeError(f"Run the standard fixture loader first: {key}")
            marker = f"Синтетический каталог: {key}"
            previous = await db.scalar(select(Document.id).where(Document.company_id == company_id, Document.name == marker))
            file_key = f"products/{product.id}/catalog-photo-{key}.webp"
            images = (await db.scalars(select(ProductImage).where(ProductImage.product_id == product.id))).all()
            if previous is None and not any(image.file_key == file_key for image in images):
                await asyncio.to_thread(upload_object, file_key, (asset_dir / entry["file"]).read_bytes(), "image/webp")
                # Replace only our earlier schematic placeholders; retain user photos.
                for image in images:
                    if image.file_key == f"products/{product.id}/seed-{key}.png":
                        await db.delete(image)
                await db.flush()
                remaining = [i for i in images if i.file_key != f"products/{product.id}/seed-{key}.png"]
                position = max((i.position for i in remaining), default=-1) + 1
                db.add(ProductImage(product_id=product.id, file_name=f"{product.name}.webp", file_key=file_key, content_type="image/webp", position=position))
            if previous is None:
                profile = match_profile(product.category, product.subcategory, product.characteristics)
                if profile is None or not profile.supported:
                    raise RuntimeError(f"Unsupported fixture category: {key}")
                now = datetime.now(timezone.utc)
                for index, requirement in enumerate(profile.requirements):
                    confirms = {field: [value] for field in requirement.confirmable
                                if (value := characteristic_value(product.characteristics, field)) is not None}
                    document_key = f"demo/synthetic/catalog-expansion/{product.id}/{requirement.code}.pdf"
                    name = marker if index == 0 else f"{marker}: {requirement.code}"
                    await asyncio.to_thread(upload_object, document_key, synthetic_document_pdf({"name": name}), "application/pdf")
                    db.add(Document(company_id=company_id, created_by_user_id=admin_id, name=name,
                        document_type=requirement.document_types[0], file_key=document_key, content_type="application/pdf",
                        verification_status="verified", scope_category=product.category, scope_subcategory=product.subcategory,
                        valid_until=now.date()+timedelta(days=730), confirms=confirms,
                        verified_by_user_id=admin_id, verified_at=now,
                        verification_note="Синтетическая локальная фикстура. Не является проверкой реального товара или юридическим документом."))
                # All documents and the marker are in the same transaction. A failure
                # before publication rolls back the complete fixture, never half a set.
                await db.flush()
                if not product.is_published:
                    await publish_product(product.id, PublishIn(published=True), CurrentUser(user_id), db)
            # Subsequent runs never republish a product deliberately withdrawn by its seller.
            await db.commit()
        return len(entries)


if __name__ == "__main__":
    import sys
    print(asyncio.run(seed_catalog(Path(sys.argv[1]))))
