from pydantic import BaseModel


class MetricsRead(BaseModel):
    registered_users: int
    active_listings: int
    matches_generated: int
    completed_exchanges: int
