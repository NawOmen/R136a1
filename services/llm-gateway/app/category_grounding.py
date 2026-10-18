"""Versioned catalogue vocabulary and source-bound dimensional normalization.

The snapshot is generated from Marketplace, never from uploaded instructions.
It suggests a classification; admission and commercial decisions stay elsewhere.
"""
import json
import re
from pathlib import Path

from .schemas import RawExtraction, RawFact, SourceDescriptor

REGISTRY = json.loads(Path(__file__).with_name("category-grounding.generated.json").read_text())
FIELDS = REGISTRY["fields"]
# Preserve the existing agent keys used in evidence and downstream matching.
EXTRA_LABELS = {"print": "Печать", "top_diameter_mm": "Диаметр верха, мм",
                "bottom_diameter_mm": "Диаметр дна, мм", "width_mm": "Ширина, мм",
                "length_mm": "Длина, мм", "dimensions_mm": "Габариты, мм"}


def catalogue_prompt() -> str:
    categories = [{"category": item["label"], "parent": item["parent"], "fields": item["fields"]}
                  for item in REGISTRY["categories"]]
    return ("Справочник платформы (не содержимое материалов). Выбирай точное название category, "
            "только если вид изделия определён; иначе сохрани общую категорию. "
            "Ключи свойств бери из fields, значения только из источников. "
            "Обязательность в каталоге не разрешает выдумывать значение.\n"
            + json.dumps(categories, ensure_ascii=False, separators=(",", ":")))


def field_label(key: str) -> str:
    if key in EXTRA_LABELS:
        return EXTRA_LABELS[key]
    for name, field in FIELDS.items():
        if key in [name, *field.get("aliases", [])]:
            return field["label"]
    return key if re.search("[а-яё]", key, re.I) else "Дополнительное свойство"


# A triple is retained in its original axis order. No orientation is invented.
TRIPLE = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)?\s*[×xх*]\s*\d+(?:[.,]\d+)?\s*[×xх*]\s*\d+(?:[.,]\d+)?\s*мм\b", re.I)


def normalize_dimensions(extraction: RawExtraction, sources: list[SourceDescriptor]) -> RawExtraction:
    facts = list(extraction.facts)
    if extraction.category.strip().lower() not in {"коробки", "коробка", "гофрокороб", "гофрокороба", "упаковка", "упаковка и тара", "packaging.boxes"}:
        return extraction
    for source in sources:
        triples = list(TRIPLE.finditer(source.text))
        if not triples:
            continue
        # Only explicit box/carton requests: cylinders and other shapes can have
        # legitimate diameter/length dimensions. Never reinterpret those here.
        if not re.search(r"короб|гофрокороб", source.text, re.I):
            continue
        facts = [fact for fact in facts if not (fact.source_id == source.id and fact.key == "dimensions_mm")]
        for match in triples:
            raw = match.group()
            value = re.sub(r"\s*мм$", "", raw, flags=re.I)
            value = re.sub(r"\s*[×xх*]\s*", "×", value).replace(",", ".")
            facts.append(RawFact(key="dimensions_mm", value=value, source_id=source.id,
                                 confidence=1, evidence=raw, original_unit="мм"))
        # Eliminate only ungrounded shape/axis guesses for this same source.
        # Explicitly labelled dimensions remain and may cause a real conflict.
        axis_words = {"diameter_mm": r"диаметр|[Ø⌀]", "length_mm": r"длина|длиной",
                      "width_mm": r"ширина|шириной", "height_mm": r"высота|высотой"}
        facts = [fact for fact in facts if not (
            fact.source_id == source.id and fact.key in axis_words
            and not re.search(axis_words[fact.key], source.text, re.I))]
    return extraction.model_copy(update={"facts": facts})
