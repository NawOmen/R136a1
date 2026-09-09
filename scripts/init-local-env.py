"""Create a new local environment with independent random secrets; never overwrite."""
import os
from pathlib import Path
import secrets


def main():
    destination = Path(__file__).resolve().parents[1] / ".env"
    values = dict(JWT_SECRET=secrets.token_urlsafe(48), OPTIMIZER_TOKEN=secrets.token_urlsafe(48),
                  POSTGRES_PASSWORD=secrets.token_hex(24), PGADMIN_DEFAULT_PASSWORD=secrets.token_hex(24),
                  MINIO_ROOT_PASSWORD=secrets.token_hex(24),
                  SEED_ADMIN_PASSWORD=secrets.token_hex(16), SEED_DEMO_PASSWORD=secrets.token_hex(16),
                  SEED_SELLER_PASSWORD=secrets.token_hex(16))
    values.update(POSTGRES_USER="sborka", POSTGRES_DB="sborka", ENABLE_DEMO_SEED="false",
                  MINIO_ROOT_USER="porukam", MINIO_ACCESS_KEY="porukam",
                  MINIO_SECRET_KEY=values["MINIO_ROOT_PASSWORD"],
                  DATABASE_URL=f"postgresql+asyncpg://sborka:{values['POSTGRES_PASSWORD']}@localhost:5433/sborka")
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(".env уже существует. Файл не изменён; используйте инструкцию ротации секретов.")
    with os.fdopen(fd, "w") as stream:
        stream.write("# Локальные секреты. Не добавлять в Git.\n")
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    print("Создан .env с правами 0600. Значения секретов не выводятся.")


if __name__ == "__main__":
    main()
