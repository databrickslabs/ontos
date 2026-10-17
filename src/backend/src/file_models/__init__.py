"""File models for YAML serialization of governance entities.

This module provides serializers for exporting major entities to YAML format
for the indirect delivery mode. The YAML files are stored in a Git repository
and can be used by external CI/CD processes to apply governance changes.
"""

from .base import FileModel, FileModelRegistry
from .data_contracts import DataContractFileModel
from .data_products import DataProductFileModel
from .data_domains import DataDomainFileModel
from .roles import RoleFileModel
from .tags import TagFileModel

__all__ = [
    'FileModel',
    'FileModelRegistry',
    'DataContractFileModel',
    'DataProductFileModel',
    'DataDomainFileModel',
    'RoleFileModel',
    'TagFileModel',
]

