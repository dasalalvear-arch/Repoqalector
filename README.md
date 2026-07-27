# U-Swap

Marketplace circular universitario para estudiantes UTEM. Registro con correo
`@utem.cl`, catálogo con buscador y filtros, publicaciones, solicitudes de
intercambio con chat por solicitud, panel de **Mis publicaciones** y **panel de
administración** con moderación de publicaciones y KPIs. **No hay pagos**: el
objetivo es reutilizar recursos dentro del campus mediante entregas presenciales.

> Resumen completo (arquitectura, modelo de datos, seguridad y limitaciones
> conocidas): ver [RESUMEN.md](RESUMEN.md).

## Stack

- Frontend: React, Vite, TypeScript, React Router, Axios, lucide-react, PWA
- Backend: FastAPI, SQLAlchemy, Pydantic, JWT (python-jose), bcrypt (passlib), slowapi
- Base de datos: PostgreSQL
- Infraestructura local: Docker Compose

## Roles

- **STUDENT:** registro público (solo `@utem.cl`); publica, solicita, chatea y
  gestiona sus propias publicaciones.
- **ADMIN:** se siembra desde el entorno (`ADMIN_EMAIL` / `ADMIN_PASSWORD`), nunca
  desde la API; accede al panel de administración.

## Arranque con Docker

```bash
docker compose up --build
```

Luego abre:

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs

(añade `-v` a `docker compose down` para borrar también la base de datos)

## Arranque manual

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

`npm run build` (`tsc -b && vite build`) es la única verificación automatizada del
proyecto (no hay suite de tests ni linter configurados).

## Datos de prueba

Script idempotente que crea 2 estudiantes y 7 publicaciones:

```bash
docker compose exec backend python -m app.services.seed_demo
```

- Estudiantes demo: `valentina.rojas@utem.cl` y `matias.fuentes@utem.cl` — contraseña `demo1234`.
- Admin por defecto (desde `.env.example`): `admin@utem.cl` / `cambia-esta-clave-admin`.

## Módulos y endpoints

- **Auth:** `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- **Usuarios:** `GET /users/{id}`, `PUT /users/{id}`
- **Publicaciones:** `GET /items` (filtros `search`, `category_id`, `owner_id`), `POST /items`, `GET /items/{id}`, `PUT /items/{id}`, `DELETE /items/{id}`
- **Categorías:** `GET /categories`
- **Solicitudes:** `POST /matches`, `GET /matches`, `PUT /matches/{id}`
- **Chat:** `GET /chat/{matchId}`, `POST /chat/{matchId}`
- **Admin:** `GET /admin/metrics`, `GET /admin/users`, `DELETE /admin/users/{id}`, `GET /admin/items`, `PUT /admin/items/{id}/approve`, `PUT /admin/items/{id}/hide`, `DELETE /admin/items/{id}`

> La interfaz muestra "Solicitudes", pero el prefijo de la API sigue siendo `/matches`.

## Decisiones

- No hay pagos ni transacciones monetarias.
- Solo se aceptan cuentas con correo institucional `@utem.cl`; el registro siempre crea rol `STUDENT`.
- Las imágenes se manejan como URLs (http/https) para mantener simple el MVP; el siguiente paso natural es moverlas a almacenamiento real.
- Las categorías iniciales (`Tecnologia`, `Papeleria`, `Bibliografia`) se siembran automáticamente al arrancar.
- Sin migraciones: los cambios de columnas se aplican de forma idempotente en `services/schema.py`.
