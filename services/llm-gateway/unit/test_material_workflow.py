from pathlib import Path

import pytest

from app.agents import build_extraction_prompt, merge_facts
from app.category_grounding import REGISTRY, normalize_dimensions
from app.extractors import material_to_text, transcribe_material, canonical_media_type, UnreadableMaterial
from app.schemas import RawExtraction, RawFact, SourceDescriptor


def test_box_dimensions_keep_all_axes_and_source_without_cylinder_guesses():
    source = SourceDescriptor(id="box", kind="text", name="Описание", text="250 гофрокоробов 400×300×300 мм, Т-23, цвет бурый")
    raw = RawExtraction(category="упаковка", facts=[
        RawFact(key="diameter_mm", value=400, source_id="box", confidence=1),
        RawFact(key="length_mm", value=300, source_id="box", confidence=1),
        RawFact(key="color", value="бурый", source_id="box", confidence=1),
    ])
    normalized = normalize_dimensions(raw, [source])
    assert normalize_dimensions(normalized, [source]) == normalized
    props, _, _ = merge_facts(raw, [source], [])
    found = {prop.key: prop for prop in props}
    assert "diameter_mm" not in found and "length_mm" not in found
    assert found["dimensions_mm"].value == "400×300×300"
    assert found["dimensions_mm"].sources[0].locator["located"]
    assert found["color"].label == "Цвет"


def test_distinct_box_sizes_conflict_and_cylinder_diameter_is_preserved():
    sources = [SourceDescriptor(id=str(i),kind="document",name="ТЗ",text=value) for i,value in enumerate(
        ["Коробка 400x300x300 мм", "Коробка 500×300×300 мм"])]
    _, conflicts, _ = merge_facts(RawExtraction(category="Коробки"), sources, [])
    assert conflicts[0].values == ["400×300×300", "500×300×300"]
    cylinder = SourceDescriptor(id="c",kind="text",name="Чертёж",text="Цилиндр 400×300×300 мм, диаметр 400 мм")
    raw = RawExtraction(category="Металлы",facts=[RawFact(key="diameter_mm",value=400,source_id="c",confidence=1)])
    assert normalize_dimensions(raw,[cylinder]) == raw


def test_prompt_has_multicategory_vocabulary_without_invented_values():
    prompt = build_extraction_prompt([SourceDescriptor(id="x",kind="text",name="Запрос",text="Нужна мебель")])
    assert 'Мебель' in prompt and 'Крепёж' in prompt and 'Коробки' in prompt
    assert 'не разрешает выдумывать значение' in prompt
    assert len(REGISTRY["categories"]) >= 46


@pytest.mark.parametrize("mime",["audio/mp4","audio/x-m4a","audio/m4a","application/octet-stream",""])
async def test_real_m4a_aliases_are_validated_before_transcription(mime):
    data = (Path(__file__).resolve().parents[3]/"packages/test-fixtures/buyer-evidence/voice-message.m4a").read_bytes()
    class Speech:
        async def transcribe(self, value, suffix):
            assert value == data and suffix == ".m4a"
            return "Синтетическая закупка"
    result, kind = await material_to_text("voice-message.m4a",mime,data,None,Speech())
    assert kind == "audio" and result == "Синтетическая закупка"


async def test_renamed_or_corrupt_m4a_never_reaches_transcriber():
    class NoSpeech:
        async def transcribe(self,*args):
            pytest.fail("Corrupt material reached speech recognition")
    assert canonical_media_type(b"not audio","application/octet-stream","voice.m4a") == "application/octet-stream"
    with pytest.raises(UnreadableMaterial):
        await transcribe_material(b"not audio","audio/x-m4a",NoSpeech())
