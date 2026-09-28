"""
ODCS JSON Schema Validation

This module provides validation utilities for Open Data Contract Standard (ODCS)
compliance using the official JSON schemas. It is version-aware: each supported
apiVersion is validated against its own vendored schema (see
``src.common.odcs_versions``), so a v3.0.1 document is checked as v3.0.1 and a
v3.2.0 document as v3.2.0.
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

import jsonschema
from jsonschema import ValidationError, Draft201909Validator
from src.common.logging import get_logger
from src.common import odcs_versions

logger = get_logger(__name__)

# Retained for backwards compatibility with any importer of this constant.
ODCS_SCHEMA_PATH = odcs_versions.schema_path_for(odcs_versions.LATEST_ODCS_VERSION)


class ODCSValidationError(Exception):
    """Custom exception for ODCS validation errors"""
    def __init__(self, message: str, validation_errors: Optional[List[str]] = None):
        self.message = message
        self.validation_errors = validation_errors or []
        super().__init__(self.message)


class ODCSValidator:
    """Version-aware ODCS JSON Schema Validator.

    Loads and caches one ``Draft201909Validator`` per vendored schema file, and
    selects the validator for a document by its ``apiVersion``.
    """

    def __init__(self):
        # Cache keyed by resolved schema file path (multiple apiVersions may map
        # to the same file, e.g. all v3.0.x -> the v3.0.2 schema).
        self._validators: Dict[str, Draft201909Validator] = {}

    def _get_validator(self, api_version: Optional[str]) -> Draft201909Validator:
        schema_path = odcs_versions.schema_path_for(api_version)
        key = str(schema_path)
        validator = self._validators.get(key)
        if validator is None:
            if not schema_path.exists():
                raise ODCSValidationError(f"ODCS schema file not found at {schema_path}")
            try:
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema = json.load(f)
                # Schema uses draft/2019-09 ($schema), which requires
                # Draft201909Validator for unevaluatedProperties and other
                # 2019-09 keywords.
                validator = Draft201909Validator(schema)
                self._validators[key] = validator
                logger.info(f"Loaded ODCS schema from {schema_path}")
            except Exception as e:
                logger.error(f"Failed to load ODCS schema {schema_path}: {e}")
                raise ODCSValidationError(f"Failed to load ODCS schema: {e}")
        return validator

    def validate(self, contract_data: Dict[str, Any], strict: bool = True,
                 api_version: Optional[str] = None) -> bool:
        """
        Validate a data contract against the schema for its apiVersion.

        Args:
            contract_data: The contract data to validate
            strict: If True, raises exception on validation errors. If False, returns boolean.
            api_version: Override apiVersion; defaults to the document's own ``apiVersion``.

        Returns:
            bool: True if valid, False if invalid (when strict=False)

        Raises:
            ODCSValidationError: If validation fails and strict=True
        """
        version = api_version or contract_data.get('apiVersion')
        validator = self._get_validator(version)

        try:
            # Validate against schema
            validator.validate(contract_data)
            logger.debug("Contract data passed ODCS validation")
            return True

        except ValidationError as e:
            errors = list(validator.iter_errors(contract_data))
            error_messages = []

            for error in errors:
                # Build a user-friendly error message
                path = " → ".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
                message = f"At '{path}': {error.message}"
                error_messages.append(message)

            logger.warning(f"Contract data failed ODCS validation: {len(error_messages)} errors found")

            if strict:
                raise ODCSValidationError(
                    f"Contract does not comply with ODCS specification. Found {len(error_messages)} validation errors.",
                    validation_errors=error_messages
                )
            else:
                return False

        except Exception as e:
            logger.error(f"Unexpected error during ODCS validation: {e}")
            if strict:
                raise ODCSValidationError(f"Validation error: {e}")
            else:
                return False

    def get_validation_errors(self, contract_data: Dict[str, Any],
                              api_version: Optional[str] = None) -> List[str]:
        """
        Get detailed validation errors for a contract without raising exceptions

        Args:
            contract_data: The contract data to validate
            api_version: Override apiVersion; defaults to the document's own value.

        Returns:
            List[str]: List of validation error messages
        """
        version = api_version or contract_data.get('apiVersion')
        try:
            validator = self._get_validator(version)
        except ODCSValidationError as e:
            return [e.message]

        try:
            validator.validate(contract_data)
            return []
        except ValidationError:
            errors = list(validator.iter_errors(contract_data))
            error_messages = []

            for error in errors:
                path = " → ".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
                message = f"At '{path}': {error.message}"
                error_messages.append(message)

            return error_messages
        except Exception as e:
            return [f"Validation error: {e}"]


# Global validator instance
_odcs_validator = None


def get_odcs_validator() -> ODCSValidator:
    """Get the global ODCS validator instance"""
    global _odcs_validator
    if _odcs_validator is None:
        _odcs_validator = ODCSValidator()
    return _odcs_validator


def validate_odcs_contract(contract_data: Dict[str, Any], strict: bool = True,
                           api_version: Optional[str] = None) -> bool:
    """
    Convenience function to validate a contract against the schema for its apiVersion.

    Args:
        contract_data: The contract data to validate
        strict: If True, raises exception on validation errors
        api_version: Override apiVersion; defaults to the document's own value.

    Returns:
        bool: True if valid, False if invalid (when strict=False)
    """
    validator = get_odcs_validator()
    return validator.validate(contract_data, strict=strict, api_version=api_version)


def get_odcs_validation_errors(contract_data: Dict[str, Any],
                               api_version: Optional[str] = None) -> List[str]:
    """
    Get validation errors for a contract without raising exceptions

    Args:
        contract_data: The contract data to validate
        api_version: Override apiVersion; defaults to the document's own value.

    Returns:
        List[str]: List of validation error messages
    """
    validator = get_odcs_validator()
    return validator.get_validation_errors(contract_data, api_version=api_version)