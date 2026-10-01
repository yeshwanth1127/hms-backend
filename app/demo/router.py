from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from ..db import Base, get_db
from ..client_modules import owner
from ..models import MediaAsset
from . import LOCK, guard

router = APIRouter(prefix='/api/v1/staff/demo', tags=['local-demo'])
KEEP = {'staff_users', 'staff_sessions', 'staff_login_limits', 'client_modules'}


def counts(db):
    guard(db)
    return {table.name: db.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables if table.name not in KEEP}


def clear(db):
    root = guard(db)
    # The whole database is disposable; no production record tagging/deletion guesses.
    files = [root / 'uploads' / row.storage_name for row in db.scalars(select(MediaAsset))]
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in KEEP:
            db.execute(delete(table))
    db.commit()
    for file in files:
        if file.parent == root / 'uploads' and file.is_file():
            file.unlink()


@router.get('')
def status(_=Depends(owner), db: Session = Depends(get_db)):
    return {'demo': True, 'counts': counts(db), 'external_transport': 'disabled'}


@router.post('/clear')
def remove(_=Depends(owner), db: Session = Depends(get_db)):
    with LOCK:
        clear(db)
        return {'counts': counts(db), 'preserved': sorted(KEEP)}


@router.post('/reload')
def reload(_=Depends(owner), db: Session = Depends(get_db)):
    from .fixtures import seed
    with LOCK:
        clear(db)
        seed(db)
        return {'counts': counts(db), 'preserved': sorted(KEEP)}
