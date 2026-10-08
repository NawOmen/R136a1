from types import SimpleNamespace
from unittest.mock import AsyncMock
import pymupdf as fitz
from app.agents import evidence_locator
from app.extractors import pdf_to_text, image_to_text
from app.schemas import SourceDescriptor


async def test_pdf_local_representation_points_to_correct_page():
    doc=fitz.open()
    doc.new_page().insert_text((72,72),'Quantity: 5000')
    doc.new_page().insert_text((72,72),'Material: wood')
    data=doc.tobytes();doc.close()
    provider=SimpleNamespace(vision_text=AsyncMock())
    value=await pdf_to_text(data,provider)
    source=SourceDescriptor(id='file_1',name='synthetic.pdf',kind='document',text=value)
    locator=evidence_locator(source,'Material: wood')
    assert locator['page']==2 and value[locator['start']:locator['end']]=='Material: wood'
    provider.vision_text.assert_not_awaited()


def test_audio_locator_uses_local_transcription_time():
    source=SourceDescriptor(id='file_1',name='synthetic.wav',kind='audio',text='[[1.25-3.50 с]] нужно дерево')
    assert evidence_locator(source,'дерево')['seconds']==['1.25','3.50']
    assert evidence_locator(source,'несуществующий фрагмент')['located'] is False


async def test_image_uses_only_local_provider():
    provider=SimpleNamespace(vision_text=AsyncMock(return_value='Видимый текст'))
    assert await image_to_text(b'synthetic-image',provider)=='Видимый текст'
    provider.vision_text.assert_awaited_once()
