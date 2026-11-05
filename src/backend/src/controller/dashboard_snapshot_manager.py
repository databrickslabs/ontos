"""
Dashboard snapshots

Stores an image of a BI dashboard on its Dashboard asset so consumers can see
what a data product delivers: the PNG as a metadata document and a "Dashboard
preview" note that embeds it. Both are inheritable at a low level, so data
products with the dashboard as an output port show them too (metadata
inheritance from port assets).

The state lives in ``asset.properties["snapshot"]``:
``{status, document_id, note_id, captured_at, source, source_updated_at, error, risks}``.
"""

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.common.logging import get_logger
from src.connectors.base import AssetConnector
from src.db_models.assets import AssetDb
from src.db_models.metadata import DocumentMetadataDb, RichTextMetadataDb

logger = get_logger(__name__)

SNAPSHOT_PROPERTY = "snapshot"
OPT_OUT_PROPERTY = "snapshot_opt_out"
SNAPSHOT_FILENAME = "dashboard-snapshot.png"
# Low level: listed first, and inherited by products with the default max level
SNAPSHOT_LEVEL = 10

STATUS_OK = "ok"
STATUS_OPTED_OUT = "opted_out"
STATUS_USER_FILTERS = "skipped_user_filters"
STATUS_UNSUPPORTED = "unsupported"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DashboardSnapshotManager:
    """Captures dashboard snapshots through the asset's connector and stores them on the asset."""

    def __init__(
        self,
        workspace_client_provider: Optional[Callable[[], Any]] = None,
        settings_provider: Optional[Callable[[], Any]] = None,
    ):
        self._ws_provider = workspace_client_provider
        self._settings_provider = settings_provider

    # -- storage ---------------------------------------------------------------

    def _volume_path(self, asset_id: str) -> tuple:
        """(workspace client, destination file path) in the app's UC Volume."""
        from src.common.config import get_settings
        from src.common.workspace_client import get_workspace_client
        from src.controller.metadata_manager import MetadataManager

        settings = self._settings_provider() if self._settings_provider else get_settings()
        # The app's own client, as for document uploads: the volume belongs to the app
        ws = self._ws_provider() if self._ws_provider else get_workspace_client(settings)
        base_dir = f"uploads/asset/{asset_id}"
        volume_base = MetadataManager().ensure_volume_path(ws, settings, base_dir)
        try:
            ws.files.create_directory(f"{volume_base}/{base_dir}")
        except Exception:
            pass
        return ws, f"{volume_base}/{base_dir}/{SNAPSHOT_FILENAME}"

    @staticmethod
    def _note_markdown(asset: AssetDb, document_id: str, state: Dict[str, Any]) -> str:
        props = asset.properties or {}
        platform = (props.get("dashboardPlatform") or asset.platform or "the BI tool").title()
        url = props.get("dashboardUrl") or props.get("url")
        lines = [f"![{asset.name}](doc:{document_id})", ""]
        captured = f"Snapshot captured {state['captured_at']} (UTC) from {platform}."
        if state.get("source") == "preview_image":
            captured = (
                f"Thumbnail from {platform}: a fresh render failed ({state.get('status')}), "
                f"so this may be outdated. Checked {state['captured_at']} (UTC)."
            )
        lines.append(captured + (f" [Open the live dashboard]({url})" if url else ""))
        lines += [
            "",
            f"> The image shows the data as Ontos's {platform} account sees it. It is not live, "
            f"and people with row-level security may see different figures in {platform}.",
        ]
        return "\n".join(lines)

    # -- capture ---------------------------------------------------------------

    def state(self, asset: AssetDb) -> Dict[str, Any]:
        return dict((asset.properties or {}).get(SNAPSHOT_PROPERTY) or {})

    def _save_state(self, db: Session, asset: AssetDb, state: Dict[str, Any]) -> Dict[str, Any]:
        props = dict(asset.properties or {})
        props[SNAPSHOT_PROPERTY] = state
        asset.properties = props
        flag_modified(asset, "properties")
        db.flush()
        return state

    def set_opt_out(self, db: Session, asset: AssetDb, opt_out: bool) -> Dict[str, Any]:
        props = dict(asset.properties or {})
        props[OPT_OUT_PROPERTY] = bool(opt_out)
        asset.properties = props
        flag_modified(asset, "properties")
        db.flush()
        return {OPT_OUT_PROPERTY: bool(opt_out), SNAPSHOT_PROPERTY: self.state(asset)}

    def capture(
        self,
        db: Session,
        *,
        asset: AssetDb,
        connector: AssetConnector,
        current_user: Optional[str],
        force: bool = False,
    ) -> Dict[str, Any]:
        """Capture and store a snapshot of ``asset``; returns the new snapshot state.

        Without ``force``: skipped when the dashboard opted out, when its
        calculations filter by user, or when the source has not changed since
        the last successful capture.
        """
        props = asset.properties or {}
        previous = self.state(asset)
        source_updated_at = props.get("source_updated_at")

        if props.get(OPT_OUT_PROPERTY):
            return self._save_state(db, asset, {**previous, "status": STATUS_OPTED_OUT})

        if not force:
            risks = connector.snapshot_risks(asset.location)
            if risks:
                return self._save_state(db, asset, {**previous, "status": STATUS_USER_FILTERS, "risks": risks})
            if (previous.get("status") == STATUS_OK and previous.get("document_id")
                    and source_updated_at and previous.get("source_updated_at") == source_updated_at):
                return previous

        snapshot = connector.capture_snapshot(asset.location)
        if snapshot is None:
            return self._save_state(db, asset, {**previous, "status": STATUS_UNSUPPORTED})

        state: Dict[str, Any] = {
            "status": snapshot.status,
            "captured_at": _now(),
            "source": snapshot.source,
            "source_updated_at": source_updated_at,
            "error": snapshot.error,
            "document_id": previous.get("document_id"),
            "note_id": previous.get("note_id"),
        }
        if snapshot.content:
            self._store(db, asset, snapshot.content, snapshot.content_type, state, current_user)
        return self._save_state(db, asset, state)

    def _store(
        self, db: Session, asset: AssetDb, content: bytes, content_type: str,
        state: Dict[str, Any], current_user: Optional[str],
    ) -> None:
        """Write the image to the volume and upsert its document and preview note."""
        asset_id = str(asset.id)
        ws, dest = self._volume_path(asset_id)
        ws.files.upload(dest, BytesIO(content), overwrite=True)

        doc = db.get(DocumentMetadataDb, _as_uuid(state.get("document_id"))) if state.get("document_id") else None
        if doc is None:
            doc = DocumentMetadataDb(
                entity_type="asset", entity_id=asset_id, title=f"Snapshot: {asset.name}",
                short_description="Image of the dashboard, captured by Ontos",
                original_filename=SNAPSHOT_FILENAME, storage_path=dest,
                level=SNAPSHOT_LEVEL, inheritable=True, created_by=current_user,
            )
            db.add(doc)
        doc.content_type = content_type
        doc.size_bytes = len(content)
        doc.storage_path = dest
        doc.updated_by = current_user
        db.flush()
        state["document_id"] = str(doc.id)

        note = db.get(RichTextMetadataDb, _as_uuid(state.get("note_id"))) if state.get("note_id") else None
        if note is None:
            note = RichTextMetadataDb(
                entity_type="asset", entity_id=asset_id, title="Dashboard preview",
                short_description="What this dashboard shows", content_markdown="",
                level=SNAPSHOT_LEVEL, inheritable=True, created_by=current_user,
            )
            db.add(note)
        note.content_markdown = self._note_markdown(asset, state["document_id"], state)
        note.updated_by = current_user
        db.flush()
        state["note_id"] = str(note.id)


def _as_uuid(value: Optional[str]):
    from uuid import UUID
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
