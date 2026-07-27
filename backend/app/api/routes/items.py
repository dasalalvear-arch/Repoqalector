from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.category import Category
from app.models.item import Item, ItemImage
from app.models.user import User
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate

router = APIRouter()


@router.get("", response_model=list[ItemRead])
def list_items(
    db: Session = Depends(get_db),
    search: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    owner_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Item]:
    query = db.query(Item).options(
        joinedload(Item.category),
        joinedload(Item.owner),
        joinedload(Item.images),
    )
    if search:
        pattern = f"%{search}%"
        query = query.filter(Item.title.ilike(pattern) | Item.description.ilike(pattern))
    if category_id:
        query = query.filter(Item.category_id == category_id)
    if owner_id:
        query = query.filter(Item.owner_id == owner_id)
    return query.order_by(Item.created_at.desc()).offset(skip).limit(limit).all()


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(
    payload: ItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Item:
    if db.get(Category, payload.category_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category")

    item = Item(
        title=payload.title,
        description=payload.description,
        condition=payload.condition,
        category_id=payload.category_id,
        owner_id=current_user.id,
        images=[ItemImage(image_url=str(url)) for url in payload.image_urls],
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=ItemRead)
def read_item(item_id: int, db: Session = Depends(get_db)) -> Item:
    item = (
        db.query(Item)
        .options(joinedload(Item.category), joinedload(Item.owner), joinedload(Item.images))
        .filter(Item.id == item_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.put("/{item_id}", response_model=ItemRead)
def update_item(
    item_id: int,
    payload: ItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Item:
    item = read_item(item_id, db)
    if item.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot edit this item")

    data = payload.model_dump(exclude_unset=True)
    image_urls = data.pop("image_urls", None)
    for field, value in data.items():
        setattr(item, field, value)
    if image_urls is not None:
        item.images = [ItemImage(image_url=str(url)) for url in image_urls]
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    item = read_item(item_id, db)
    if item.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete this item")
    db.delete(item)
    db.commit()
