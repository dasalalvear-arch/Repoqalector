# U-Swap — Resumen del proyecto

**U-Swap** es un marketplace de **economía circular** para estudiantes de la UTEM.
Permite registrarse con correo institucional `@utem.cl`, publicar artículos que ya no
se usan (libros, calculadoras, apuntes, material de laboratorio, etc.), solicitar
intercambios y coordinar la entrega presencial mediante un chat por solicitud.
**No hay pagos ni transacciones monetarias**: el objetivo es reutilizar recursos
dentro de la comunidad universitaria.

- **Interfaz:** en español, orientada a estudiantes.
- **Código:** en inglés (identificadores y comentarios); textos visibles en español.
- **Repositorio:** monorepo con `backend/` (API) y `frontend/` (SPA).

---

## 1. Stack tecnológico

| Capa | Tecnologías |
|---|---|
| **Frontend** | React + TypeScript, Vite, React Router, Axios, `lucide-react` (íconos), PWA (service worker) |
| **Backend** | FastAPI, SQLAlchemy 2.0, Pydantic / pydantic-settings, python-jose (JWT), passlib + bcrypt, slowapi (rate limiting) |
| **Base de datos** | PostgreSQL 16 (driver `psycopg` 3) |
| **Infraestructura** | Docker Compose (db + backend + frontend) |

---

## 2. Funcionalidades

### Estudiante (rol `STUDENT`)
- **Registro / login** con correo `@utem.cl` y contraseña (mínimo 8 caracteres).
- **Catálogo:** explorar publicaciones con buscador y filtro por categoría (chips).
- **Publicar** artículos (título, descripción, estado, categoría, URL de imagen opcional).
- **Solicitudes:** pedir un intercambio sobre el artículo de otra persona.
- **Chat por solicitud** para coordinar punto y horario de entrega dentro del campus.
- **Mis publicaciones:** panel para ver los artículos propios, marcarlos como
  entregados / reactivarlos y eliminarlos.

### Administrador (rol `ADMIN`)
- **Panel de KPIs:** usuarios registrados, publicaciones activas, solicitudes
  generadas e intercambios completados.
- **Moderación de publicaciones:** aprobar, ocultar o eliminar; búsqueda y filtro
  por estado de moderación.
- **Gestión de usuarios:** listar y eliminar cuentas.

> El administrador **no** se crea desde la API. Se siembra al arrancar a partir de
> las variables `ADMIN_EMAIL` / `ADMIN_PASSWORD` del entorno. El registro público
> siempre asigna el rol `STUDENT`.

---

## 3. Arquitectura

### Backend (`backend/app/`)
Estructura FastAPI en capas; cada dominio (auth, users, items, categories, matches,
chat, admin) tiene un archivo paralelo en cada carpeta:

- `models/` — ORM SQLAlchemy (tablas: `users`, `categories`, `items`, `item_images`, `matches`, `messages`).
- `schemas/` — formas de request/response con Pydantic.
- `api/routes/` — endpoints, montados en `main.py` bajo su prefijo.
- `core/` — infraestructura transversal: `config.py`, `database.py`, `security.py` (bcrypt + JWT), `limiter.py`.
- `services/` — lógica de arranque: `seed.py` (admin + categorías), `schema.py` (parches de columnas), `seed_demo.py` (datos de prueba).

**Secuencia de arranque** (`main.py`, a nivel de import):
`Base.metadata.create_all()` → `ensure_runtime_schema()` (agrega columnas añadidas
después: `role`, `moderation_status`, `is_reported`) → `create_admin()` +
`ensure_default_categories()`. No hay migraciones; `schema.py` es el sustituto
hecho a mano e idempotente.

### Frontend (`frontend/src/`)
SPA con React Router. Páginas: Auth, Catálogo, Publicar, Solicitudes, Mis
publicaciones y Admin (cada una protegida según el rol).

- `services/api.ts` — única fuente de verdad: instancia Axios + todos los tipos TS
  (espejo de los schemas del backend). Un interceptor agrega el token bearer desde
  `localStorage["uswap.token"]`; otro detecta 401 con sesión activa, limpia el token
  y emite el evento `uswap:unauthorized`.
- `hooks/useAuth.ts` — máquina de estado de autenticación: lee el token, hidrata el
  usuario con `/auth/me`, escucha `uswap:unauthorized` para forzar logout y `login()`
  devuelve el rol para redirigir estudiante vs. admin.

---

## 4. Modelo de datos

| Tabla | Campos clave | Notas |
|---|---|---|
| `users` | id, name, email (único), password_hash, career, **role** | role: `STUDENT` / `ADMIN` |
| `categories` | id, name (único) | Se siembran `Tecnologia`, `Papeleria`, `Bibliografia` |
| `items` | id, title, description, condition, category_id, owner_id, **status**, **moderation_status**, created_at | status: `AVAILABLE` / `RESERVED` / `DELIVERED` · moderación: `pending` / `approved` / `hidden` |
| `item_images` | id, item_id, image_url | Imágenes como URLs (http/https) |
| `matches` | id, item_id, requester_id, owner_id, status, created_at | status: `PENDING` / `ACCEPTED` / `REJECTED` / `COMPLETED` |
| `messages` | id, match_id, sender_id, content, created_at | Chat por solicitud |

---

## 5. API (endpoints principales)

| Módulo | Endpoints |
|---|---|
| **Auth** | `POST /auth/register` · `POST /auth/login` · `GET /auth/me` |
| **Usuarios** | `GET /users/{id}` · `PUT /users/{id}` |
| **Publicaciones** | `GET /items` (filtros: `search`, `category_id`, `owner_id`, `skip`, `limit`) · `POST /items` · `GET /items/{id}` · `PUT /items/{id}` · `DELETE /items/{id}` |
| **Categorías** | `GET /categories` |
| **Solicitudes** | `POST /matches` · `GET /matches` · `PUT /matches/{id}` |
| **Chat** | `GET /chat/{match_id}` · `POST /chat/{match_id}` |
| **Admin** | `GET /admin/metrics` · `GET /admin/users` · `DELETE /admin/users/{id}` · `GET /admin/items` · `PUT /admin/items/{id}/approve` · `PUT /admin/items/{id}/hide` · `DELETE /admin/items/{id}` |
| **Salud** | `GET /health` |

Documentación interactiva (Swagger): `http://localhost:8000/docs`.

---

## 6. Flujo de usuario

```
Registro/Login  →  Catálogo (portada)  →  Publicar  /  Solicitudes + Chat  /  Mis publicaciones
                                       →  (rol ADMIN)  →  Panel de administración
```

Tras registrarse, el usuario aterriza en el catálogo. Desde la barra de navegación
accede a las demás secciones; el administrador es redirigido a su panel al iniciar
sesión.

---

## 7. Seguridad

- **Autenticación:** tokens JWT bearer; el `sub` del token es el email del usuario.
- **Autorización:** dependencias `get_current_user` y `get_current_admin` (403 si el
  rol no es `ADMIN`). Las acciones sobre un artículo (editar/eliminar) verifican que
  el usuario sea el dueño.
- **Registro restringido:** solo correos `@utem.cl`; siempre rol `STUDENT`.
- **Contraseñas:** hash con bcrypt (passlib).
- **Rate limiting:** login y registro limitados con slowapi (429 al exceder).
- **Cabeceras de seguridad:** CSP restrictiva, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. La API solo
  devuelve JSON.
- **CORS:** orígenes configurables (por defecto `http://localhost:5173`).

---

## 8. Cómo ejecutar

### Con Docker (recomendado)
```bash
docker compose up --build     # db + backend:8000 + frontend:5173
docker compose down           # detener (añade -v para borrar la BD)
```
- Frontend: http://localhost:5173
- Backend / docs: http://localhost:8000/docs

### Manual
```bash
# Backend
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # define JWT_SECRET_KEY (>=32 chars)
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

`npm run build` (`tsc -b && vite build`) es la única verificación automatizada del
proyecto (no hay suite de tests ni linter configurados).

---

## 9. Datos de prueba

Script idempotente que crea 2 estudiantes y 7 publicaciones repartidas entre ellos:

```bash
docker compose exec backend python -m app.services.seed_demo
```

- Estudiantes demo: `valentina.rojas@utem.cl` y `matias.fuentes@utem.cl` — contraseña `demo1234`.
- Admin (desde `.env.example`): `admin@utem.cl` / `cambia-esta-clave-admin`.

Se puede volver a ejecutar sin duplicar (omite usuarios/artículos existentes).

---

## 10. Estado actual y limitaciones conocidas

- **Sin tests ni linter:** el único chequeo automático es `npm run build`.
- **Sin migraciones:** los cambios de columnas se aplican a mano en
  `services/schema.py`. Para una BD nueva conviene `docker compose down -v`.
- **Enums de moderación:** el DDL manual usa etiquetas en MAYÚSCULAS mientras que el
  modelo ORM usa minúsculas; consistente en BD nueva, pero debe alinearse antes de
  migrar una BD que no se pueda recrear.
- **`items.is_reported`:** existe en la BD pero no está mapeado en el modelo.
- **Imágenes como URL:** paso natural siguiente es mover a almacenamiento real.
- **Secretos en `.env.example`:** contraseña de admin y `JWT_SECRET_KEY` de ejemplo
  están versionados y Docker los usa por defecto; **cambiarlos antes de cualquier
  despliegue** (generar un secreto real y una contraseña fuerte fuera del repo).

---

## 11. Estructura del repositorio

```
u-swap/
├─ backend/
│  ├─ app/
│  │  ├─ api/routes/     # endpoints por dominio
│  │  ├─ core/           # config, database, security, limiter
│  │  ├─ models/         # ORM SQLAlchemy
│  │  ├─ schemas/        # Pydantic
│  │  ├─ services/       # seed, schema, seed_demo
│  │  └─ main.py         # app + arranque + middleware
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  └─ src/
│     ├─ components/     # Header, ItemCard
│     ├─ hooks/          # useAuth, usePendingMatches
│     ├─ pages/          # Auth, Catalog, Publish, Matches, MyPublications, Admin
│     ├─ routes/         # App (router)
│     ├─ services/       # api.ts (Axios + tipos)
│     └─ styles.css, eco-theme.css
└─ docker-compose.yml
```
