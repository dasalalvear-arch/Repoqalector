# Design: Post editing, request detail, notification icon, and mandatory-message request flow

Date: 2026-07-07
Branch: feature/rediseno-y-mis-publicaciones

Four scoped improvements to U-Swap. Three are small; one (the request flow) enforces a
new rule server-side. UI strings stay Spanish, code stays English (per CLAUDE.md).

## 1. Post editing — reuse the Publish page

The backend already supports this: `PUT /items/{id}` in `api/routes/items.py` is owner-guarded
and accepts `title`, `description`, `condition`, `category_id`, `status`, `image_urls`. No backend
change.

Frontend:
- `routes/App.tsx`: add route `/publish/:id` rendering the same `PublishPage` (create stays `/publish`).
- `pages/PublishPage.tsx`: read `:id` via `useParams`. When present, `GET /items/:id`, prefill the
  form, and submit via `PUT /items/:id` instead of `POST /items`. Text fields prefill with
  `defaultValue`; category and image are held in state (image already is). The form renders only once
  the item has loaded, so prefill is reliable. Heading/submit label switch to an edit wording.
- `pages/MyPublicationsPage.tsx`: add an **Editar** button per row linking to `/publish/${item.id}`.

Only the owner can edit — enforced by the existing 403 in `update_item`.

## 2. Chat/Requests detail — requester name + item name

Backend:
- `schemas/match.py`: add two nested read models and expose them on `MatchRead`:
  `requester: { id, name }` and `item: { id, title }`. The `Match` model already has both
  relationships, so `from_attributes` maps them directly.
- `api/routes/matches.py::list_matches`: add `joinedload(Match.requester)` and `joinedload(Match.item)`
  to avoid N+1.

Frontend:
- `services/api.ts`: extend the `Match` type with `requester: { id: number; name: string }` and
  `item: { id: number; title: string }`.
- `pages/MatchesPage.tsx`: list rows show the **item title** and "Solicitado por {requester.name}"
  instead of "Item #id"; chat header shows the item title. Both are shown regardless of side
  (harmless when the current user is the requester).

## 3. "!" notification icon size

`components/Header.tsx`: the badge next to *Solicitudes* uses `AlertCircle size={14}` — bump to
`size={20}`. `.nav-badge` in `styles.css` gets a minor alignment nudge if the larger icon needs it.
No logic change; `usePendingMatches` is untouched.

## 4. Mandatory message on request (atomic, enforced server-side)

Today `Solicitar` fires `POST /matches { item_id }` in one click and the match exists with no message.
New rule: a request carries a message to the donor, created together with the match so a match can
never exist without a first message.

Backend:
- `schemas/match.py::MatchCreate`: add required `message: str` (min_length 1, max_length 500).
- `api/routes/matches.py::create_match`: after building the `Match`, also create a `Message`
  (`sender_id = current_user.id`, `content = payload.message`) in the same transaction/commit.

Frontend:
- `pages/CatalogPage.tsx` / `components/ItemCard.tsx`: `Solicitar` opens a small modal with a message
  textarea. On send, `POST /matches { item_id, message }`. The existing "Solicitud enviada" notice and
  the PENDING/badge/notification flow are unchanged.

## Contract touch-points (keep in sync)

- `models/match.py` (unchanged) → `schemas/match.py` (`MatchRead` nesting, `MatchCreate.message`) →
  `frontend/src/services/api.ts` (`Match` type, request payload).

## Out of scope (deliberately skipped)

- No draft/finalized match state (Q1 option B) — the atomic create makes it unnecessary.
- No inline row-editor in Mis Publicaciones (Q2 option B) — reusing the Publish form is less code.
- No new item fields, no message editing/deletion.

## Verification

One runnable backend check (no framework, `assert`-based) covering the security-ish path:
`POST /matches` without a message is rejected (422), and with a message creates both the match and
its first message. `npm run build` (tsc) is the frontend gate per CLAUDE.md.
