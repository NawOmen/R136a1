from app.report_labels import display, label


def test_export_uses_russian_statuses_keys_and_booleans_preserving_user_values():
    assert label('in_production') == 'Производство'
    assert display({'estimate_complete':False,'cost_tax_basis':'no_vat','cost_source':'Синтетический прайс'}) == 'Полнота сметы: Нет; Налоговая база затрат: Без НДС; Источник затрат: Синтетический прайс'
    assert display('Qwen') == 'Qwen'
