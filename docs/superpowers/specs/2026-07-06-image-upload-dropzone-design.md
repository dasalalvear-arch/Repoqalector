# Drag-and-drop image upload (base64, single image)

**Date:** 2026-07-06
**Status:** Approved

## Goal

Replace the "URL de imagen" text field in the publish flow with a drag-and-drop
upload zone. Users pick a local image (drag or click) instead of pasting a link.

## Decision: base64 in the DB

Chosen over disk+static serving and external object storage. Rationale: this is a
one-semester project that will not continue. Base64 needs zero new infrastructure
(no upload endpoint, no static mount, no Docker volume) and everything travels with
a single DB dump. The downsides — bigger rows, images riding along in list
responses, dropping the strict `HttpUrl` guard — do not matter at this scale.

## Scope

- `frontend/src/pages/PublishPage.tsx`
- `frontend/src/eco-theme.css`
- `backend/app/models/item.py`
- `backend/app/services/schema.py`
- `backend/app/schemas/item.py`
- Drive-by: `frontend/src/pages/AdminPage.tsx`

## Frontend — PublishPage.tsx

Replace the `<input type="url" name="imageUrl">` with a dropzone component (inline
in the page — no shared component needed for one use):

- Dashed box with a lucide `UploadCloud` icon and text
  "Arrastra una imagen o haz clic para subir".
- Click triggers a hidden `<input type="file" accept="image/*">`.
- Drag-and-drop via `onDragOver` (preventDefault + highlight state) and `onDrop`.
- On file selected:
  1. Validate it is an image (`file.type.startsWith("image/")`) and **≤ 2 MB**.
  2. On failure, set an inline error message; do not crash.
  3. On success, `FileReader.readAsDataURL(file)` → store the base64 data URL in
     component state.
- Show a preview thumbnail with a small ✕ button that clears the state.
- Submit sends `image_urls: image ? [image] : []`. Image stays **optional**
  (matches current behavior).

## CSS — eco-theme.css

Add:
- `.eco-dropzone` — dashed `--eco-border`, centered content, pointer cursor;
  hover / drag-over state highlights border to `--eco-primary`.
- `.eco-dropzone-preview` — thumbnail with a positioned clear button.

Reuse existing tokens (`--eco-primary`, `--eco-border`, `--eco-accent`,
`--eco-text-main`) and the existing 10px radius so it matches the form.

## Backend

- **`models/item.py`**: change `ItemImage.image_url` from `String(500)` to `Text`
  (base64 data URLs exceed 500 chars).
- **`services/schema.py`**: add an idempotent `ALTER TABLE item_images ALTER COLUMN
  image_url TYPE TEXT` inside `ensure_runtime_schema`. There are no migrations and
  `create_all` never alters an existing column, so existing DBs need this patch.
  Fresh DBs (`docker compose down -v`) get `Text` from the model directly.
- **`schemas/item.py`**: `HttpUrl` rejects `data:` URLs, so relax `image_urls` on
  both `ItemCreate` and `ItemUpdate` to `list[str]` with a field validator that
  accepts **only** strings starting with `http://`, `https://`, or `data:image/`.
  This keeps `javascript:`, `file:`, and other schemes blocked. Keep
  `max_length=8`.
- **`api/routes/items.py`**: unchanged — it already stores the strings as-is.

## Drive-by fix

`AdminPage.tsx` renders `item.images[0].url`, but the API field is `image_url`, so
admin thumbnails are broken today. Fix to `.image_url`.

## Constraints

- Single image, optional. Max 2 MB. Any `image/*` type.
- No new dependencies.

## Data flow

drop/select file → validate type + size → `FileReader` data URL → state → preview
→ submit → `POST /items { image_urls: [dataURL] }` → stored in
`item_images.image_url` (TEXT) → catalog/my-publications render `<img src={dataURL}>`.

## Error handling

- Wrong type or > 2 MB: inline error, no state change, no crash.
- No image: allowed, `image_urls` empty.
- Backend validator rejects non-image / non-http(s) schemes with a 422.

## Verification

- `npm run build` (tsc + vite) — the frontend gate.
- A small assert-based check that the backend `image_urls` validator accepts
  `data:image/png;base64,...` and `https://...` and rejects `javascript:alert(1)`.
