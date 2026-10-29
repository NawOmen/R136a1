# ПоРукам — текущая модель

Это единственный актуальный комплект последнего завершённого и проверенного адаптера. Метрики и ограничения — model.json. Autocomplete/автономные коммерческие решения не приняты:404/412exact, авторскийнабор2/8; semanticaccuracy неизвестна.

Нужна отдельно базовая MLX Qwen3.5-9B-4bit, revision8b2b98c00a6b4d291155e4890773ca8f769aee53. На текущем Mac она сохранена в /Users/assweg/Desktop/b2b/porukam-ml-experiments/model-9b-4bit. На другом Mac AppleSilicon оператор доставляет ту же базу из mlx-community/Qwen3.5-9B-4bit и копирует base-download-manifest.json в каталог базы как download-manifest.json. Все базовыеLFSразмеры/SHA проверяются serve.py. Лицензионные сведения базы — BASE-MODEL-README.md. Пакеты нативногоPython — requirements-serving.txt; скрипт ничего не устанавливает и не скачивает.

Проверка без загрузки модели:
python serve.py --base /path/to/model-9b-4bit --adapter /path/to/porukam-model

Запуск только явным действием оператора: добавить --serve. По умолчанию bind127.0.0.1:8080. Gateway использует LOCAL_LLM_BACKEND=mlx, MLX_BASE_URL=http://host.docker.internal:8080, TRAINED_MODEL_VERSION=porukam-buyer-b2cf30b11110. Для Docker оператор обеспечивает приватную доступностьhostendpoint; публично MLXserver не выставлять. Подробная инструкция — docs/ml-trained-deployment.md в PR130. Развёртывание и merge не выполнялись.
