"""Import Markdown files from a Unity Catalog volume as documents on entities.

Each ``.md`` file under the folder becomes a document (the same records the
documents panel lists) on every entity its YAML front matter names::

    ---
    title: Customer churn            # optional; else the first "# " heading, else the file name
    domain: Customer                 # a domain id or name
    assets: [main.crm.customers]     # asset ids, FQNs (location) or names
    concepts: [Customer]             # concept IRIs or labels
    ---

Nothing is guessed: a file whose front matter names no existing entity is
reported as unlinked. A re-run compares each file's SHA-256 with the stored one
and only rewrites the documents of files that changed; a changed file that no
longer names an entity takes its document off that entity, and a file gone
from the folder (deleted or renamed) takes all its documents away. Glossary terms in a file
stay document text; no concepts are created.

The files are read with the caller's workspace client (on behalf of the user),
so an import can't expose files the user can't read. The Markdown is stored
with the document; the source file is never written or deleted.
"""
import hashlib
import json
import posixpath
import re
from typing import Any, Collection, Dict, List, Optional, Tuple
from uuid import UUID

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import BadRequest, NotFound, PermissionDenied, Unauthenticated
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.controller.metadata_manager import MetadataManager
from src.db_models.assets import AssetDb
from src.db_models.change_log import ChangeLogDb
from src.db_models.data_domains import DataDomain
from src.db_models.metadata import DocumentMetadataDb
from src.models.metadata import (
    MarkdownImportFileResult, MarkdownImportResult, MarkdownImportTarget,
    MarkdownImportUnresolved,
)
from src.repositories.metadata_repository import DocumentRepository, document_repo

logger = get_logger(__name__)

MAX_FILES = 500
MAX_FILE_BYTES = 1024 * 1024
MAX_DEPTH = 10
_TITLE_MAX = 255
_VOLUME_ROOT = re.compile(r'^/Volumes/[^/\s]+/[^/\s]+/[^/\s]+(/.*)?$')
_HEADING = re.compile(r'^#\s+(.+?)\s*#*\s*$', re.MULTILINE)

# Front matter keys per entity kind (singular and plural are both accepted).
_TARGET_KEYS = {
    'domain': ('domain', 'domains'),
    'asset': ('asset', 'assets'),
    'concept': ('concept', 'concepts'),
}
# The feature whose Read/Write level a user needs to link a document to that kind.
TARGET_FEATURES = {
    'domain': 'data-domains',
    'asset': 'assets',
    'concept': 'semantic-models',
}
# The target kind of a document's entity_type
_ENTITY_KINDS = {'data_domain': 'domain', 'asset': 'asset', 'concept': 'concept'}
MAX_FRONT_MATTER_BYTES = 32 * 1024


class MarkdownImportPathInvalidError(CodedValueError):
    """The path isn't a folder or ``.md`` file inside a Unity Catalog volume."""

    code = 'markdown_import_path_invalid'


class MarkdownImportPathNotFoundError(CodedValueError):
    """Nothing exists at the path."""

    code = 'markdown_import_path_not_found'


class MarkdownImportAccessDeniedError(CodedValueError):
    """The user may not read the path."""

    code = 'markdown_import_access_denied'


class MarkdownImportTooManyFilesError(CodedValueError):
    """The folder holds more Markdown files than one import takes."""

    code = 'markdown_import_too_many_files'


class FrontMatterError(ValueError):
    """The YAML front matter can't be read as a mapping."""


def normalize_volume_path(raw: str) -> str:
    """``raw`` as a clean ``/Volumes/<catalog>/<schema>/<volume>[/...]`` path.

    Raises:
        MarkdownImportPathInvalidError: Not inside a volume, or with ``.``/``..`` segments.
    """
    path = (raw or '').strip()
    segments = path.split('/')
    if (not path.startswith('/') or '\\' in path
            or any(segment in ('.', '..') for segment in segments)):
        raise MarkdownImportPathInvalidError(f"Invalid volume path {path!r}", path=path)
    cleaned = '/' + '/'.join(segment for segment in segments if segment)
    if not _VOLUME_ROOT.match(cleaned):
        raise MarkdownImportPathInvalidError(
            f"The path must be /Volumes/<catalog>/<schema>/<volume>[/<folder>], got {path!r}",
            path=path,
        )
    return cleaned


class _NoAliasSafeLoader(yaml.SafeLoader):
    """SafeLoader that refuses anchors and aliases (no "billion laughs" expansion)."""

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, 'anchor', None):
            raise yaml.YAMLError("Anchors and aliases are not allowed in front matter")
        return super().compose_node(parent, index)


def parse_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    """(front matter, body) of a Markdown text; ({}, text) without front matter.

    Raises:
        FrontMatterError: The block isn't valid YAML, isn't a mapping, is larger
            than MAX_FRONT_MATTER_BYTES, or uses anchors/aliases.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return {}, text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in ('---', '...'):
            block = ''.join(lines[1:index])
            body = ''.join(lines[index + 1:])
            if len(block.encode('utf-8')) > MAX_FRONT_MATTER_BYTES:
                raise FrontMatterError("Front matter is larger than 32 KB")
            try:
                data = yaml.load(block, Loader=_NoAliasSafeLoader) if block.strip() else {}
            except yaml.YAMLError as e:
                raise FrontMatterError("Front matter is not valid YAML") from e
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise FrontMatterError("Front matter must be a mapping")
            return data, body
    # An opening line without a closing one is plain Markdown (e.g. a rule).
    return {}, text


def _values(front_matter: Dict[str, Any], keys: Tuple[str, ...]) -> List[str]:
    values: List[str] = []
    for key in keys:
        raw = front_matter.get(key)
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            if isinstance(item, (str, int, float)) and not isinstance(item, bool):
                text = str(item).strip()
                if text and text not in values:
                    values.append(text)
    return values


def document_title(front_matter: Dict[str, Any], body: str, path: str) -> str:
    title = front_matter.get('title')
    if not isinstance(title, str) or not title.strip():
        heading = _HEADING.search(body)
        title = heading.group(1) if heading else posixpath.splitext(posixpath.basename(path))[0]
    return title.strip()[:_TITLE_MAX] or posixpath.basename(path)


# (target, None) when a value names one entity, else (None, 'not_found' | 'ambiguous')
_Lookup = Tuple[Optional[MarkdownImportTarget], Optional[str]]


class _TargetResolver:
    """Resolves front matter values to entities, once per value per import."""

    def __init__(self, db: Session, semantic_models_manager: Any = None,
                 writable_kinds: Optional[Collection[str]] = None):
        self._db = db
        self._semantic = semantic_models_manager
        # Kinds (domain/asset/concept) the caller may write; None = all.
        self._writable = writable_kinds
        self._cache: Dict[Tuple[str, str], _Lookup] = {}

    def may_write(self, entity_type: str) -> bool:
        """Whether the caller may change documents on an entity of this type."""
        return self._writable is None or _ENTITY_KINDS.get(entity_type) in self._writable

    def resolve(
        self, front_matter: Dict[str, Any],
    ) -> Tuple[List[MarkdownImportTarget], List[MarkdownImportUnresolved]]:
        targets: List[MarkdownImportTarget] = []
        unresolved: List[MarkdownImportUnresolved] = []
        for kind, keys in _TARGET_KEYS.items():
            for value in _values(front_matter, keys):
                if self._writable is not None and kind not in self._writable:
                    # Not even looked up: the caller can't attach documents there.
                    unresolved.append(
                        MarkdownImportUnresolved(kind=kind, value=value, reason='forbidden'))
                    continue
                key = (kind, value)
                if key not in self._cache:
                    self._cache[key] = self._lookup(kind, value)
                target, reason = self._cache[key]
                if target is None:
                    unresolved.append(
                        MarkdownImportUnresolved(kind=kind, value=value, reason=reason))
                elif all((t.entity_type, t.entity_id) != (target.entity_type, target.entity_id)
                         for t in targets):
                    targets.append(target)
        return targets, unresolved

    def _lookup(self, kind: str, value: str) -> _Lookup:
        if kind == 'domain':
            return self._one('data_domain', self._domains(value))
        if kind == 'asset':
            return self._one('asset', self._assets(value))
        return self._concept(value)

    @staticmethod
    def _one(entity_type: str, rows: List[Any]) -> _Lookup:
        if not rows:
            return None, 'not_found'
        if len(rows) > 1:
            return None, 'ambiguous'
        row = rows[0]
        target = MarkdownImportTarget(entity_type=entity_type, entity_id=str(row.id), name=row.name)
        return target, None

    def _domains(self, value: str) -> List[DataDomain]:
        by_id = self._db.query(DataDomain).filter(DataDomain.id == value).first()
        if by_id:
            return [by_id]
        return self._db.query(DataDomain).filter(func.lower(DataDomain.name) == value.lower()).all()

    def _assets(self, value: str) -> List[AssetDb]:
        try:
            asset_id = UUID(value)
        except ValueError:
            asset_id = None
        if asset_id is not None:
            by_id = self._db.query(AssetDb).filter(AssetDb.id == asset_id).first()
            if by_id:
                return [by_id]
        lowered = value.lower()
        by_fqn = self._db.query(AssetDb).filter(func.lower(AssetDb.location) == lowered).all()
        if by_fqn:
            return by_fqn
        return self._db.query(AssetDb).filter(func.lower(AssetDb.name) == lowered).all()

    def _concept(self, value: str) -> _Lookup:
        iris: List[str] = []
        if self._semantic is not None:
            try:
                iris = self._semantic.find_concept_iris(value)
            except Exception:
                logger.warning("Concept lookup failed during Markdown import", exc_info=True)
        if not iris:
            return None, 'not_found'
        if len(iris) > 1:
            return None, 'ambiguous'
        return MarkdownImportTarget(entity_type='concept', entity_id=iris[0], name=value), None


class MarkdownImportManager:
    def __init__(
        self,
        metadata_manager: MetadataManager,
        semantic_models_manager: Any = None,
        document_repository: DocumentRepository = document_repo,
    ):
        self._metadata = metadata_manager
        self._semantic = semantic_models_manager
        self._documents = document_repository

    def import_from_volume(
        self, db: Session, ws: WorkspaceClient, *, path: str, user_email: Optional[str],
        writable_kinds: Collection[str],
    ) -> MarkdownImportResult:
        """Import every ``.md`` file under ``path`` (a volume folder, or one file).

        ``writable_kinds``: the target kinds (keys of TARGET_FEATURES) the caller
        has Read/Write on; values naming another kind are reported ``forbidden``.

        Raises:
            MarkdownImportPathInvalidError, MarkdownImportPathNotFoundError,
            MarkdownImportAccessDeniedError, MarkdownImportTooManyFilesError
        """
        root = normalize_volume_path(path)
        unread: List[str] = []
        files = self._list_markdown_files(ws, root, unread)
        resolver = _TargetResolver(db, self._semantic, writable_kinds)
        result = MarkdownImportResult(path=root)
        changed: List[DocumentMetadataDb] = []
        removed_ids: List[str] = []
        for file_path, size in files:
            entry = self._import_file(db, ws, file_path, size, resolver, user_email,
                                      changed, removed_ids)
            result.files.append(entry)
            setattr(result, entry.status, getattr(result, entry.status) + 1)
        if not files and not root.lower().endswith('.md'):
            # An empty listing may be a transient or permission glitch: keep
            # what was imported from here before rather than wipe it.
            result.warnings.append('empty_folder')
        gone = self._remove_gone_files(db, root, files, unread, user_email, removed_ids, resolver)
        for entry in gone:
            result.files.append(entry)
            result.removed += 1
        db.commit()
        for doc in changed:
            db.refresh(doc)
            self._metadata.index_document(doc)
        for document_id in removed_ids:
            self._metadata.remove_document_from_index(document_id)
        logger.info(
            "Markdown import of %s: %d added, %d updated, %d unchanged, %d unlinked, "
            "%d failed, %d removed", root, result.added, result.updated, result.unchanged,
            result.unlinked, result.failed, result.removed,
        )
        return result

    # --- Volume access ---
    def _list_markdown_files(
        self, ws: WorkspaceClient, root: str, unread: Optional[List[str]] = None,
    ) -> List[Tuple[str, Optional[int]]]:
        """The ``.md`` files under ``root``, with their sizes.

        Subfolders that couldn't be listed (gone, no access, deeper than
        MAX_DEPTH) go to ``unread``: their files are unknown, not deleted.
        """
        unread = unread if unread is not None else []
        if root.lower().endswith('.md'):
            try:
                metadata = ws.files.get_metadata(root)
            except NotFound as e:
                raise MarkdownImportPathNotFoundError(f"No file at {root}", path=root) from e
            except (PermissionDenied, Unauthenticated) as e:
                raise MarkdownImportAccessDeniedError(f"Can't read {root}", path=root) from e
            return [(root, getattr(metadata, 'content_length', None))]
        found: List[Tuple[str, Optional[int]]] = []
        pending = [(root, 0)]
        while pending:
            folder, depth = pending.pop(0)
            try:
                entries = list(ws.files.list_directory_contents(folder))
            except (NotFound, BadRequest) as e:
                # BadRequest: the path is a file, not a folder
                if folder == root:
                    raise MarkdownImportPathNotFoundError(f"No folder at {root}", path=root) from e
                unread.append(folder)
                continue
            except (PermissionDenied, Unauthenticated) as e:
                if folder == root:
                    raise MarkdownImportAccessDeniedError(f"Can't read {root}", path=root) from e
                unread.append(folder)
                continue
            for entry in entries:
                entry_path = entry.path or posixpath.join(folder, entry.name or '')
                if entry.is_directory:
                    if depth + 1 <= MAX_DEPTH:
                        pending.append((entry_path, depth + 1))
                    else:
                        unread.append(entry_path)
                elif entry_path.lower().endswith('.md'):
                    found.append((entry_path, entry.file_size))
                    if len(found) > MAX_FILES:
                        raise MarkdownImportTooManyFilesError(
                            f"More than {MAX_FILES} Markdown files under {root}",
                            path=root, max=MAX_FILES,
                        )
        found.sort()
        return found

    def _remove_gone_files(
        self, db: Session, root: str, files: List[Tuple[str, Optional[int]]],
        unread: List[str], user_email: Optional[str], removed_ids: List[str],
        resolver: _TargetResolver,
    ) -> List[MarkdownImportFileResult]:
        """Remove the documents of files imported from under ``root`` that are gone.

        The files are the source of truth: a file deleted (or renamed) since an
        earlier import of this folder takes its documents off their entities.
        Documents imported from elsewhere, or from subfolders that couldn't be
        listed this time, stay, and so do documents on entities of a kind the
        caller can't edit.
        """
        if root.lower().endswith('.md') or not files:
            return []  # one file, or nothing listed: never remove
        present = {path for path, _ in files}
        skipped = tuple(folder.rstrip('/') + '/' for folder in unread)
        gone: Dict[str, List[DocumentMetadataDb]] = {}
        for doc in self._documents.list_imported_under(db, folder=root):
            if doc.source_path in present or (skipped and doc.source_path.startswith(skipped)):
                continue
            if not resolver.may_write(doc.entity_type):
                continue
            gone.setdefault(doc.source_path, []).append(doc)
        entries = []
        for path, docs in sorted(gone.items()):
            for doc in docs:
                db.add(ChangeLogDb(
                    entity_type=f"{doc.entity_type}:document",
                    entity_id=doc.entity_id,
                    action='DELETE',
                    username=user_email,
                    details_json=json.dumps({'source_path': path, 'title': doc.title,
                                             'reason': 'source_file_gone'}),
                ))
                removed_ids.append(str(doc.id))
                db.delete(doc)
            entries.append(MarkdownImportFileResult(
                path=path, status='removed', title=docs[0].title, removed=len(docs),
            ))
        db.flush()
        return entries

    @staticmethod
    def _download(ws: WorkspaceClient, path: str) -> bytes:
        response = ws.files.download(path)
        stream = getattr(response, 'contents', None)
        if stream is None or not hasattr(stream, 'read'):
            raise ValueError("Unsupported download response")
        return stream.read(MAX_FILE_BYTES + 1)

    # --- One file ---
    def _import_file(
        self, db: Session, ws: WorkspaceClient, path: str, size: Optional[int],
        resolver: _TargetResolver, user_email: Optional[str], changed: List[DocumentMetadataDb],
        removed_ids: List[str],
    ) -> MarkdownImportFileResult:
        def failed(reason: str) -> MarkdownImportFileResult:
            return MarkdownImportFileResult(path=path, status='failed', reason=reason)

        if size is not None and size > MAX_FILE_BYTES:
            return failed('too_large')
        try:
            raw = self._download(ws, path)
        except Exception:
            logger.warning("Failed to read %s during Markdown import", path, exc_info=True)
            return failed('read_failed')
        if len(raw) > MAX_FILE_BYTES:
            return failed('too_large')
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            return failed('not_utf8')
        if '\x00' in text:
            return failed('not_text')  # Postgres text columns reject NUL
        try:
            front_matter, body = parse_front_matter(text)
        except FrontMatterError:
            return failed('front_matter_invalid')

        title = document_title(front_matter, body, path)
        targets, unresolved = resolver.resolve(front_matter)
        digest = hashlib.sha256(raw).hexdigest()
        existing = {
            (doc.entity_type, doc.entity_id): doc
            for doc in self._documents.list_by_source_path(db, source_path=path)
        }

        def log(doc: DocumentMetadataDb, action: str) -> None:
            db.add(ChangeLogDb(
                entity_type=f"{doc.entity_type}:document",
                entity_id=doc.entity_id,
                action=action,
                username=user_email,
                details_json=json.dumps({'source_path': path, 'title': title}),
            ))

        # A changed file no longer naming an entity takes its document off it.
        # Only changed files: an unchanged one keeps its documents even when a
        # name stops resolving (e.g. the entity was renamed).
        wanted = {(target.entity_type, target.entity_id) for target in targets}
        removed = 0
        for key, doc in existing.items():
            if key not in wanted and doc.content_hash != digest and resolver.may_write(key[0]):
                log(doc, 'DELETE')
                removed_ids.append(str(doc.id))
                db.delete(doc)
                removed += 1

        added = updated = 0
        for target in targets:
            doc = existing.get((target.entity_type, target.entity_id))
            if doc is None:
                doc = DocumentMetadataDb(
                    entity_type=target.entity_type,
                    entity_id=target.entity_id,
                    title=title,
                    original_filename=posixpath.basename(path),
                    content_type='text/markdown',
                    size_bytes=len(raw),
                    storage_path=path,
                    source_path=path,
                    content_hash=digest,
                    content_text=text,
                    created_by=user_email,
                    updated_by=user_email,
                )
                db.add(doc)
                log(doc, 'CREATE')
                added += 1
            elif doc.content_hash != digest:
                doc.title = title
                doc.size_bytes = len(raw)
                doc.content_hash = digest
                doc.content_text = text
                doc.updated_by = user_email
                log(doc, 'UPDATE')
                updated += 1
            else:
                continue
            changed.append(doc)
        db.flush()

        if not targets:
            status = 'unlinked'
        elif added == len(targets) and not removed:
            status = 'added'
        elif not (added or updated or removed):
            status = 'unchanged'
        else:
            status = 'updated'
        return MarkdownImportFileResult(path=path, status=status, title=title, targets=targets,
                                        unresolved=unresolved, removed=removed)
