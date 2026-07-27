from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.item import Item, ItemStatus
from app.models.match import Match
from app.models.message import Message
from app.models.user import User
from app.schemas.match import MatchCreate, MatchRead, MatchUpdate

router = APIRouter()


@router.post("", response_model=MatchRead, status_code=status.HTTP_201_CREATED)
def create_match(
    payload: MatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Match:
    item = db.get(Item, payload.item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if item.owner_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot request own item")
    if item.status != ItemStatus.available:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not available")

    match = Match(item_id=item.id, requester_id=current_user.id, owner_id=item.owner_id)
    db.add(match)
    db.flush()  # asigna match.id antes de crear el mensaje inicial
    db.add(Message(match_id=match.id, sender_id=current_user.id, content=payload.message))
    db.commit()
    db.refresh(match)
    return match


@router.get("", response_model=list[MatchRead])
def list_matches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Match]:
    return (
        db.query(Match)
        .options(joinedload(Match.requester), joinedload(Match.item))
        .filter(or_(Match.requester_id == current_user.id, Match.owner_id == current_user.id))
        .order_by(Match.created_at.desc())
        .all()
    )


@router.put("/{match_id}", response_model=MatchRead)
def update_match(
    match_id: int,
    payload: MatchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Match:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    # Solo el dueño del item decide el estado (aceptar/rechazar/completar).
    # El solicitante no puede auto-aceptar una solicitud sobre un item ajeno.
    if match.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el dueño del item puede actualizar la solicitud",
        )

    match.status = payload.status
    db.commit()
    db.refresh(match)
    return match
