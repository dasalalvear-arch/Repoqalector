from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_current_admin
from app.core.database import get_db
from app.models.item import Item, ItemModerationStatus, ItemStatus
from app.models.match import Match
from app.models.user import User, UserRole
from app.schemas.admin import MetricsRead
from app.schemas.item import ItemRead
from app.schemas.user import UserRead

router = APIRouter()


@router.get("/metrics", response_model=MetricsRead)
def get_metrics(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> MetricsRead:
    # Los KPIs miden alcance real de la app: no se cuenta al admin como usuario.
    return MetricsRead(
        registered_users=db.query(User).filter(User.role == UserRole.STUDENT).count(),
        active_listings=db.query(Item).filter(Item.status == ItemStatus.available).count(),
        matches_generated=db.query(Match).count(),
        completed_exchanges=db.query(Item).filter(Item.status == ItemStatus.delivered).count(),
    )


@router.get("/users", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> None:
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar tu propia cuenta de administrador",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    db.delete(user)
    db.commit()


def admin_item_query(db: Session):
    return db.query(Item).options(
        joinedload(Item.category),
        joinedload(Item.owner),
        joinedload(Item.images),
    )


def get_admin_item_or_404(item_id: int, db: Session) -> Item:
    item = admin_item_query(db).filter(Item.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.get("/items", response_model=list[ItemRead])
def list_admin_items(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
    search: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    reported: bool | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    duplicate: bool = Query(default=False),
) -> list[Item]:
    query = admin_item_query(db)

    if search:
        pattern = f"%{search}%"
        query = query.filter(Item.title.ilike(pattern) | Item.description.ilike(pattern))
    if category_id:
        query = query.filter(Item.category_id == category_id)
    if user_id:
        query = query.filter(Item.owner_id == user_id)
    if status_filter:
        query = query.filter(Item.moderation_status == ItemModerationStatus(status_filter))
    if reported is not None:
        query = query.filter(Item.is_reported == reported)
    if date_from:
        query = query.filter(Item.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(Item.created_at <= datetime.combine(date_to, time.max))

    items = query.order_by(Item.created_at.desc()).all()
    if duplicate:
        counts: dict[tuple[str, int], int] = {}
        for item in items:
            key = (item.title.strip().lower(), item.owner_id)
            counts[key] = counts.get(key, 0) + 1
        items = [item for item in items if counts[(item.title.strip().lower(), item.owner_id)] > 1]
    return items


@router.put("/items/{item_id}/approve", response_model=ItemRead)
def approve_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> Item:
    item = get_admin_item_or_404(item_id, db)
    item.moderation_status = ItemModerationStatus.approved
    db.commit()
    db.refresh(item)
    return item


@router.put("/items/{item_id}/hide", response_model=ItemRead)
def hide_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> Item:
    item = get_admin_item_or_404(item_id, db)
    item.moderation_status = ItemModerationStatus.hidden
    db.commit()
    db.refresh(item)
    return item


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> None:
    item = get_admin_item_or_404(item_id, db)
    db.delete(item)
    db.commit()