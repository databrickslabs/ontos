"""API models for connector syncs: scheduled re-imports of a Schema Importer selection (#1312)."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.schema_import import ImportDepth

# Hourly at most: the connector_sync job runs once an hour
MIN_INTERVAL_MINUTES = 60
MAX_INTERVAL_MINUTES = 60 * 24 * 31


class ConnectorSyncCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    connection_id: UUID
    selected_paths: List[str] = Field(..., min_length=1)
    depth: ImportDepth = ImportDepth.FULL_RECURSIVE
    excluded_paths: List[str] = Field(default_factory=list)
    interval_minutes: int = Field(1440, ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)
    retire_after_misses: int = Field(3, ge=1, le=100, description="Complete syncs an item may be missing before it is retired")
    enabled: bool = True


class ConnectorSyncUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    selected_paths: Optional[List[str]] = Field(None, min_length=1)
    depth: Optional[ImportDepth] = None
    excluded_paths: Optional[List[str]] = None
    interval_minutes: Optional[int] = Field(None, ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)
    retire_after_misses: Optional[int] = Field(None, ge=1, le=100)
    enabled: Optional[bool] = None


class ConnectorSyncRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    connection_id: UUID
    selected_paths: List[str]
    depth: ImportDepth
    excluded_paths: List[str]
    interval_minutes: int
    retire_after_misses: int
    enabled: bool
    last_run_id: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = Field(None, description="completed | incomplete | failed")
    last_complete_sync_at: Optional[datetime] = None
    next_due_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    # Set when the scheduled job could not be installed or started
    job_warning: Optional[str] = None


class ConnectorSyncRunStarted(BaseModel):
    job_run_id: int
