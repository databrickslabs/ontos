from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class NotificationRecipientBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    # Emails, groups, and app role names or ids (the PrincipalPicker values), as for workflow steps
    targets: List[str] = Field(default_factory=list)
    # App roles whose members may use this recipient in their compliance policies (admins always may)
    allowed_role_ids: List[str] = Field(default_factory=list)
    is_active: bool = True


class NotificationRecipientCreate(NotificationRecipientBase):
    pass


class NotificationRecipientUpdate(NotificationRecipientBase):
    pass


class NotificationRecipient(NotificationRecipientBase):
    id: str
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
