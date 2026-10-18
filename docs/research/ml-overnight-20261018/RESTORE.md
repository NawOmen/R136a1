# Восстановление: прежний полный архив + новая дельта

Сначала восстановите базовый41том из [ml-training-final-20261017](https://github.com/NawOmen/R136a1/releases/tag/ml-training-final-20261017) его verify_restore.py и манифестами. Не меняйте исторический архив.

Новые тома porukam-ml-overnight-delta.tar.partNNN вместе с НОВЫМИ assets-manifest.json/files-manifest.json/verify_restore.py положите в другую папку. Проверка безраспаковки: `python3 verify_restore.py`. Проверка и извлечение только новых/изменённыхфайлов: `python3 verify_restore.py /absolute/new/empty/delta-dir`. Затем скопируйте проверенную дельта-папку поверх восстановленной базовой лаборатории, сохраняя относительные пути и заменяя перечисленные изменённые файлы. Удалений старая дельта не делает; список неизменённых невыгруженных файлов — baseline-reference.json.

Подлинность каждого тома и каждого архивного файла проверяется SHA256, абсолютные/родительские пути и ссылки запрещены. Окружение не включено: lock/installreports/licenses сохранены, зависимости восстанавливаются отдельно; ничего не устанавливается и обучение не запускается автоматически. Старые completed/failed OUT не перезапускать.

Latest FINAL-ML-STATUS-20261018.md: full2144unique training complete across288+224+1632 and2optimizerresets, newadapter1b6caec3c043deed61ebb438602803ea91d47ca02d4e696bcc24482e631cabdf. Оценка stoppedbyuser384/412,exact350/384, semanticaccuracyNULL/qualityNOTaccepted. Оставшиеся28НЕгенерировать безновогопрямогоуказания. Веса/всепромежуточныеконтрольныеточки и ошибки сохранены.
