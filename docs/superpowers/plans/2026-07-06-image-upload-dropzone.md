# Drag-and-drop Image Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "URL de imagen" text field in the publish flow with a single-image drag-and-drop uploader that stores the image as a base64 data URL.

**Architecture:** The browser reads the dropped/selected file to a base64 `data:` URL and sends it in the existing `image_urls` array. The backend stores that string as-is in `item_images.image_url` (widened to `TEXT`), and its validator is relaxed from `HttpUrl` to a whitelist of `http(s)://` / `data:image/`. No new endpoints, storage, or dependencies.

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy (backend), React + Vite + TypeScript + lucide-react (frontend).

## Global Constraints

- Code, identifiers, comments in English; user-visible strings may be Spanish.
- No new dependencies.
- Single image, optional. Max 2 MB. Any `image/*` type.
- No migrations exist: schema changes to existing columns go in `services/schema.py::ensure_runtime_schema` (idempotent).
- The only automated frontend gate is `npm run build` (runs `tsc -b`). There is no pytest suite — the backend check is a standalone assert script, run then deleted.
- Contract coupling: `models/item.py` → `schemas/item.py` → `frontend/src/services/api.ts` must stay in sync.

---

## Task 1: Backend — accept and store base64 data URLs

**Files:**
- Modify: `backend/app/models/item.py:44` (ItemImage.image_url `String(500)` → `Text`)
- Modify: `backend/app/schemas/item.py` (relax `image_urls` validation)
- Modify: `backend/app/services/schema.py` (ALTER column to TEXT)
- Temp check (create then delete): `backend/check_image_validator.py`

**Interfaces:**
- Produces: `ItemCreate` / `ItemUpdate` with `image_urls: list[str]` accepting only strings starting with `http://`, `https://`, or `data:image/`. Route `create_item`/`update_item` still call `str(url)` — unchanged.

- [ ] **Step 1: Write the failing check**

Create `backend/check_image_validator.py`:

```python
# Temp verification, delete after running. Standalone: sets JWT key, no DB connection.
import os
os.environ.setdefault("JWT_SECRET_KEY", "x" * 32)

from pydantic import ValidationError
from app.schemas.item import ItemCreate


def make(urls):
    return ItemCreate(
        title="abc",
        description="0123456789",
        condition="ok",
        category_id=1,
        image_urls=urls,
    )


make(["data:image/png;base64,iVBORw0KGgo="])
make(["https://example.com/a.jpg"])

for bad in ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,<x>"]:
    try:
        make([bad])
        raise AssertionError(f"should have rejected {bad!r}")
    except ValidationError:
        pass

print("image validator OK")
```

- [ ] **Step 2: Run the check to verify it fails**

Run (from `backend/`, venv active):
```bash
python check_image_validator.py
```
Expected: FAIL — a `ValidationError` is raised on `make(["data:image/png;base64,..."])` because `image_urls` is still `list[HttpUrl]`, which rejects `data:` URLs.

- [ ] **Step 3: Relax the schema validator**

Replace the full contents of `backend/app/schemas/item.py` with:

```python
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.item import ItemStatus
from app.schemas.category import CategoryRead
from app.schemas.user import UserRead

# Solo http(s) o data:image/. Bloquea javascript:, file:, data:text/html, etc.
_ALLOWED_IMAGE_PREFIXES = ("http://", "https://", "data:image/")


def _validate_image_urls(urls: list[str]) -> list[str]:
    for url in urls:
        if not url.startswith(_ALLOWED_IMAGE_PREFIXES):
            raise ValueError("image_urls acepta solo URLs http(s) o data:image/")
    return urls


class ItemImageRead(BaseModel):
    id: int
    image_url: str

    model_config = {"from_attributes": True}


class ItemCreate(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(min_length=10)
    condition: str = Field(min_length=2, max_length=80)
    category_id: int
    image_urls: list[str] = Field(default=[], max_length=8)

    @field_validator("image_urls")
    @classmethod
    def check_image_urls(cls, value: list[str]) -> list[str]:
        return _validate_image_urls(value)


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=140)
    description: str | None = Field(default=None, min_length=10)
    condition: str | None = Field(default=None, min_length=2, max_length=80)
    category_id: int | None = None
    status: ItemStatus | None = None
    image_urls: list[str] | None = Field(default=None, max_length=8)

    @field_validator("image_urls")
    @classmethod
    def check_image_urls(cls, value: list[str] | None) -> list[str] | None:
        return value if value is None else _validate_image_urls(value)


class ItemRead(BaseModel):
    id: int
    title: str
    description: str
    condition: str
    status: ItemStatus
    created_at: datetime
    category: CategoryRead
    owner: UserRead
    images: list[ItemImageRead]

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Widen the model column**

In `backend/app/models/item.py`, line 44, change:

```python
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
```
to:
```python
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
```
(`Text` is already imported on line 4. `String` stays — still used for other columns.)

- [ ] **Step 5: Patch existing DBs to TEXT**

In `backend/app/services/schema.py`, inside the `if engine.dialect.name == "postgresql":` block, immediately **before** the `return` on line 35, add:

```python
            # base64 data URLs exceed VARCHAR(500). TEXT has no length cap.
            # varchar->text is metadata-only in Postgres and idempotent.
            connection.execute(text("ALTER TABLE item_images ALTER COLUMN image_url TYPE TEXT"))
```
(No SQLite branch change: SQLite does not enforce VARCHAR length, so base64 already stores fine.)

- [ ] **Step 6: Run the check to verify it passes**

Run (from `backend/`):
```bash
python check_image_validator.py
```
Expected: prints `image validator OK` and exits 0.

- [ ] **Step 7: Delete the temp check**

```bash
rm backend/check_image_validator.py
```
(CLAUDE.md: this repo keeps no test suite. The check was verification only.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/item.py backend/app/models/item.py backend/app/services/schema.py
git commit -m "feat(items): accept base64 data URLs for images"
```

---

## Task 2: Frontend — drag-and-drop uploader + admin thumbnail fix

**Files:**
- Modify: `frontend/src/pages/PublishPage.tsx` (replace URL input with dropzone)
- Modify: `frontend/src/eco-theme.css` (dropzone + preview + error styles)
- Modify: `frontend/src/pages/AdminPage.tsx:12,133` (fix `url` → `image_url`)

**Interfaces:**
- Consumes: `POST /items` with `image_urls: string[]` (from Task 1). The single base64 data URL is sent as `image_urls: [dataUrl]`, or `[]` when no image.

- [ ] **Step 1: Rewrite PublishPage with the dropzone**

Replace the full contents of `frontend/src/pages/PublishPage.tsx` with:

```tsx
import { ChangeEvent, DragEvent, FormEvent, useEffect, useState } from "react";
import { Recycle, Sprout, UploadCloud, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { api, Category } from "../services/api";
import "../eco-theme.css";

const MAX_IMAGE_BYTES = 2 * 1024 * 1024; // 2 MB

export function PublishPage() {
  const navigate = useNavigate();
  const [categories, setCategories] = useState<Category[]>([]);
  const [image, setImage] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    api.get<Category[]>("/categories").then((response) => setCategories(response.data));
  }, []);

  function handleFile(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setImageError("El archivo debe ser una imagen.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setImageError("La imagen supera el límite de 2 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setImage(reader.result as string);
      setImageError(null);
    };
    reader.readAsDataURL(file);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragOver(false);
    handleFile(event.dataTransfer.files[0]);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);

    await api.post("/items", {
      title: String(form.get("title")),
      description: String(form.get("description")),
      condition: String(form.get("condition")),
      category_id: Number(form.get("categoryId")),
      image_urls: image ? [image] : [],
    });

    navigate("/", { replace: true, state: { notice: "Publicacion agregada." } });
  }

  return (
    <section className="eco-form-page">
      <div className="eco-form-heading">
        <p className="eco-eyebrow" style={{ justifyContent: "center" }}>
          <Sprout size={20} /> Nueva publicación
        </p>
        <h1>Aporta al ecosistema académico.</h1>
      </div>
      <form className="eco-form-stack" onSubmit={handleSubmit}>
        <label>
          Titulo
          <input name="title" required minLength={3} placeholder="Ej: Libro de Cálculo Multivariable" />
        </label>
        <label>
          Descripcion
          <textarea name="description" required minLength={10} rows={4} placeholder="Detalla el estado del ítem y por qué lo ofreces..." />
        </label>
        <div className="eco-form-grid">
          <label>
            Categoria
            <select name="categoryId" required>
              <option value="">Selecciona</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Estado
            <input name="condition" required placeholder="Ej: Usado, como nuevo..." />
          </label>
        </div>
        <div className="eco-field">
          <span>Imagen</span>
          {image ? (
            <div className="eco-dropzone-preview">
              <img src={image} alt="Vista previa" />
              <button type="button" onClick={() => setImage(null)} aria-label="Quitar imagen">
                <X size={16} />
              </button>
            </div>
          ) : (
            <label
              className={`eco-dropzone${dragOver ? " is-dragover" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
            >
              <UploadCloud size={28} />
              <span>Arrastra una imagen o haz clic para subir</span>
              <input
                type="file"
                accept="image/*"
                hidden
                onChange={(event: ChangeEvent<HTMLInputElement>) => handleFile(event.target.files?.[0])}
              />
            </label>
          )}
          {imageError && <span className="eco-form-error">{imageError}</span>}
        </div>
        <button className="eco-btn-submit" type="submit">
          <Recycle size={20} />
          Publicar
        </button>
      </form>
    </section>
  );
}
```

- [ ] **Step 2: Add dropzone styles**

Append to `frontend/src/eco-theme.css`:

```css
.eco-form-stack .eco-field {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  font-weight: 500;
  color: var(--eco-text-main);
}

.eco-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 1.75rem 1rem;
  border: 2px dashed var(--eco-border);
  border-radius: 10px;
  background: #fff;
  color: #6b7280;
  cursor: pointer;
  text-align: center;
  font-weight: 400;
  transition: all 0.18s;
}

.eco-dropzone:hover,
.eco-dropzone.is-dragover {
  border-color: var(--eco-primary);
  background: var(--eco-accent);
}

.eco-dropzone-preview {
  position: relative;
  max-width: 220px;
  border: 1px solid var(--eco-border);
  border-radius: 10px;
  overflow: hidden;
}

.eco-dropzone-preview img {
  display: block;
  width: 100%;
  height: auto;
}

.eco-dropzone-preview button {
  position: absolute;
  top: 0.4rem;
  right: 0.4rem;
  display: flex;
  padding: 0.25rem;
  border: 0;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  cursor: pointer;
}

.eco-form-error {
  color: #c0392b;
  font-size: 0.85rem;
  font-weight: 400;
}
```

- [ ] **Step 3: Fix the admin thumbnail field name**

In `frontend/src/pages/AdminPage.tsx`, line 12, change:
```tsx
  images: { url: string }[];
```
to:
```tsx
  images: { image_url: string }[];
```
And on line 133, change `item.images[0].url` to `item.images[0].image_url`:
```tsx
                    <img src={item.images[0].image_url} alt={item.title} width={50} height={50} style={{ objectFit: "cover" }} />
```

- [ ] **Step 4: Run the build gate**

Run (from `frontend/`):
```bash
npm run build
```
Expected: PASS — `tsc -b` reports no errors and `vite build` completes. (This catches type mismatches in the dropzone handlers and the AdminPage fix.)

- [ ] **Step 5: Manual verification**

With `docker compose up --build` (or backend + `npm run dev`) running, as a logged-in student:
1. Go to Publicar. The URL field is gone; a dashed dropzone with an upload icon is shown.
2. Drop (or click to select) a JPG/PNG under 2 MB → a preview thumbnail with a ✕ appears.
3. Try a > 2 MB image or a non-image → inline red error, no preview.
4. Click ✕ → preview clears, dropzone returns.
5. Submit → redirected to catalog; the new item's card shows the uploaded image.
6. As admin, open the admin items table → the item's thumbnail renders (previously broken).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/PublishPage.tsx frontend/src/eco-theme.css frontend/src/pages/AdminPage.tsx
git commit -m "feat(publish): drag-and-drop image upload; fix admin thumbnail field"
```

---

## Self-Review

**Spec coverage:**
- Dropzone replacing URL input, click + drag, icon, ≤2 MB, image-type check, preview + clear, optional → Task 2 Step 1.
- CSS matching theme tokens → Task 2 Step 2.
- Model `Text`, `schema.py` ALTER, schema validator whitelist → Task 1 Steps 3–5.
- Route unchanged → confirmed (still `str(url)`).
- Drive-by AdminPage fix → Task 2 Step 3.
- No CSP work → confirmed during brainstorming (no CSP `<meta>` in `index.html`).
- Verification: `npm run build` + assert check → Task 1 Step 6, Task 2 Step 4.

**Placeholder scan:** none — all steps contain concrete code/commands.

**Type consistency:** `image_urls: list[str]` (backend) ↔ `image_urls: string[]` payload (frontend); `image_url` field name consistent across `ItemImageRead`, `api.ts`, `AdminItem`, and both render sites. `handleFile(File | undefined)` matches `files?.[0]` and `dataTransfer.files[0]` call sites.
