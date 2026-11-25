"""
Product Change Analyzer for Semantic Versioning
Analyzes changes between two data product versions to determine version bump type.
"""

from enum import Enum
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass


class ChangeType(Enum):
    """Type of change detected"""
    BREAKING = "breaking"  # Requires major version bump
    FEATURE = "feature"    # Requires minor version bump
    FIX = "fix"           # Requires patch version bump
    NONE = "none"         # No significant changes


class ChangeSeverity(Enum):
    """Severity classification for changes"""
    CRITICAL = "critical"  # Breaking changes
    MODERATE = "moderate"  # New features
    MINOR = "minor"        # Bug fixes, improvements


@dataclass
class PortChange:
    """Represents a change in a port (input/output/management)"""
    change_type: str  # "added", "removed", "modified", "type_changed"
    port_type: str    # "input", "output", "management"
    port_name: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    severity: ChangeSeverity = ChangeSeverity.MINOR


@dataclass
class ChangeAnalysisResult:
    """Result of change analysis"""
    change_type: ChangeType
    version_bump: str  # "major", "minor", "patch", "none"
    port_changes: List[PortChange]
    team_changes: List[Dict]
    support_changes: List[Dict]
    summary: str
    breaking_changes: List[str]
    new_features: List[str]
    fixes: List[str]


class ProductChangeAnalyzer:
    """
    Analyzes changes between two data product versions.

    Rules for semantic versioning (ODPS v1.0.0):
    - MAJOR (X.0.0): Breaking changes
      - Removed output ports
      - Removed input ports (every ODPS input port names a required contract)
      - Changed or removed port contract IDs (incompatible)
      - Repointed output ports (asset type, asset identifier, server)
      - Removed team members with critical roles
    - MINOR (0.X.0): New features (backward compatible)
      - New output ports
      - New input ports
      - New management ports
      - New support channels
    - PATCH (0.0.X): Bug fixes, documentation
      - Description changes
      - Metadata updates (tags, custom properties)
      - Support channel updates
    """

    def __init__(self):
        self.breaking_changes: List[str] = []
        self.new_features: List[str] = []
        self.fixes: List[str] = []
        self.port_changes: List[PortChange] = []
        self.team_changes: List[Dict] = []
        self.support_changes: List[Dict] = []

    def analyze(self, old_product: Dict, new_product: Dict) -> ChangeAnalysisResult:
        """
        Analyze changes between two products.

        Args:
            old_product: Previous version (dict representation)
            new_product: New version (dict representation)

        Returns:
            ChangeAnalysisResult with detected changes and recommended version bump
        """
        self._reset()

        # Analyze port changes (most critical for products)
        # NOTE on `(x.get('k') or default)`: chained `.get('k', default).get(...)`
        # only falls back to `default` when the key is MISSING. When the key is
        # present but the value is None (common when the API serializes optional
        # nullable relationships), the fallback is skipped and `.get(...)` crashes
        # on NoneType. The `or` form covers both missing-key and None-value.
        self._analyze_port_changes(
            self._get(old_product, 'inputPorts', 'input_ports') or [],
            self._get(new_product, 'inputPorts', 'input_ports') or [],
            'input'
        )
        self._analyze_port_changes(
            self._get(old_product, 'outputPorts', 'output_ports') or [],
            self._get(new_product, 'outputPorts', 'output_ports') or [],
            'output'
        )
        self._analyze_port_changes(
            self._get(old_product, 'managementPorts', 'management_ports') or [],
            self._get(new_product, 'managementPorts', 'management_ports') or [],
            'management'
        )

        # Analyze team changes
        self._analyze_team_changes(
            (old_product.get('team') or {}).get('members') or [],
            (new_product.get('team') or {}).get('members') or []
        )

        # Analyze support channel changes
        self._analyze_support_changes(
            self._get(old_product, 'support', 'support_channels') or [],
            self._get(new_product, 'support', 'support_channels') or []
        )

        # Analyze description changes (minor/patch)
        self._analyze_description_changes(
            old_product.get('description') or {},
            new_product.get('description') or {}
        )

        # Determine change type and version bump
        change_type, version_bump = self._determine_change_type()

        # Generate summary
        summary = self._generate_summary()

        return ChangeAnalysisResult(
            change_type=change_type,
            version_bump=version_bump,
            port_changes=self.port_changes,
            team_changes=self.team_changes,
            support_changes=self.support_changes,
            summary=summary,
            breaking_changes=self.breaking_changes,
            new_features=self.new_features,
            fixes=self.fixes
        )

    @staticmethod
    def _get(product: Dict, *keys):
        """The first key present: callers send field names or snake_case aliases."""
        for key in keys:
            if product.get(key) is not None:
                return product[key]
        return None

    def _reset(self):
        """Reset internal state"""
        self.breaking_changes = []
        self.new_features = []
        self.fixes = []
        self.port_changes = []
        self.team_changes = []
        self.support_changes = []

    def _analyze_port_changes(self, old_ports: List[Dict], new_ports: List[Dict], port_type: str):
        """Analyze changes in ports (input/output/management)"""
        # Filter out None entries defensively; serialized port lists from
        # partially-populated products can contain holes.
        old_port_map = self._port_map(old_ports)
        if port_type == 'output':
            new_port_map = self._paired_port_map(old_port_map, new_ports)
        else:
            new_port_map = self._port_map(new_ports)

        old_names = set(old_port_map.keys())
        new_names = set(new_port_map.keys())

        # Removed ports
        for removed_name in old_names - new_names:
            if port_type == 'output':
                # Removing output port is BREAKING (consumers depend on it)
                self.breaking_changes.append(f"Removed {port_type} port: {removed_name}")
                severity = ChangeSeverity.CRITICAL
            elif port_type == 'input':
                # An input port names a contract the product consumes (contractId
                # is required in ODPS), so removing one drops a dependency.
                self.breaking_changes.append(f"Removed {port_type} port: {removed_name}")
                severity = ChangeSeverity.CRITICAL
            else:
                # Management port removal is minor
                self.fixes.append(f"Removed {port_type} port: {removed_name}")
                severity = ChangeSeverity.MINOR

            self.port_changes.append(PortChange(
                change_type="removed",
                port_type=port_type,
                port_name=removed_name,
                severity=severity
            ))

        # Added ports
        for added_name in new_names - old_names:
            if port_type in ('output', 'management'):
                # New output or management port is a FEATURE
                self.new_features.append(f"Added {port_type} port: {added_name}")
                severity = ChangeSeverity.MODERATE
            else:
                # New input port: an added dependency, backward compatible
                self.new_features.append(f"Added {port_type} port: {added_name}")
                severity = ChangeSeverity.MODERATE

            self.port_changes.append(PortChange(
                change_type="added",
                port_type=port_type,
                port_name=added_name,
                severity=severity
            ))

        # Modified ports
        for port_name in old_names & new_names:
            old_port = old_port_map[port_name]
            new_port = new_port_map[port_name]

            # The repository keeps a port by id: a same-named port with another id
            # (or none) is a new port, and its relationships are gone.
            old_id, new_id = old_port.get('id'), new_port.get('id')
            if old_id and old_id != new_id and port_type == 'output':
                self._record_modified(
                    port_type, port_name, 'id', old_id, new_id,
                    f"Recreated {port_type} port '{port_name}' with a new id", True,
                )

            # Contract changes (critical for output ports)
            old_contract = old_port.get('contractId') or old_port.get('contract_id')
            new_contract = new_port.get('contractId') or new_port.get('contract_id')

            if old_contract != new_contract:
                if not new_contract:
                    # Unlinking a contract leaves consumers without their schema
                    desc = f"Removed contract from {port_type} port '{port_name}': {old_contract}"
                    breaking = port_type == 'output'
                elif not old_contract:
                    desc = f"Linked contract to {port_type} port '{port_name}': {new_contract}"
                    breaking = False
                else:
                    desc = (
                        f"Changed contract for {port_type} port '{port_name}': "
                        f"{old_contract} → {new_contract}"
                    )
                    breaking = port_type == 'output'
                self._record_modified(
                    port_type, port_name, 'contractId', old_contract, new_contract, desc, breaking
                )

            # Where the port points: repointing an output asset or server breaks consumers
            for field, aliases in self._ASSET_FIELDS:
                if not self._has_any(new_port, aliases):
                    continue  # the repository keeps what the caller leaves out
                old_val = self._norm(self._first(old_port, aliases))
                new_val = self._norm(self._first(new_port, aliases))
                if old_val != new_val:
                    self._record_modified(
                        port_type, port_name, field, old_val, new_val,
                        f"Changed {field} of {port_type} port '{port_name}': "
                        f"{old_val} → {new_val}",
                        port_type == 'output',
                    )

            # Other port attributes: informational (patch)
            for field, aliases in self._INFO_FIELDS:
                if not self._has_any(new_port, aliases):
                    continue
                old_val = self._norm(self._first(old_port, aliases))
                new_val = self._norm(self._first(new_port, aliases))
                if old_val != new_val:
                    self._record_modified(
                        port_type, port_name, field, old_val, new_val,
                        f"Changed {field} of {port_type} port '{port_name}': "
                        f"{old_val} → {new_val}",
                        False,
                    )

            # Check version changes
            old_version = old_port.get('version')
            new_version = new_port.get('version')

            if old_version and new_version and old_version != new_version:
                # Version change is informational (minor)
                self.fixes.append(
                    f"Updated version for {port_type} port '{port_name}': {old_version} → {new_version}"
                )
                self.port_changes.append(PortChange(
                    change_type="modified",
                    port_type=port_type,
                    port_name=port_name,
                    field_name="version",
                    old_value=old_version,
                    new_value=new_version,
                    severity=ChangeSeverity.MINOR
                ))

    # (field, accepted keys) compared on a port that exists on both sides
    _ASSET_FIELDS = (
        ('assetType', ('assetType', 'asset_type')),
        ('assetIdentifier', ('assetIdentifier', 'asset_identifier')),
        ('server', ('server',)),
    )
    _INFO_FIELDS = (
        ('status', ('status',)),
        ('deliveryMethodId', ('deliveryMethodId', 'delivery_method_id')),
        ('containsPii', ('containsPii', 'contains_pii')),
        ('description', ('description',)),
    )

    @staticmethod
    def _port_map(ports: List[Dict]) -> Dict[str, Dict]:
        """Ports by name; a repeated name gets a '#n' suffix so none is lost."""
        result: Dict[str, Dict] = {}
        for port in ports or []:
            if not port:
                continue
            name = port.get('name')
            key, n = name, 1
            while key in result:
                n += 1
                key = f"{name}#{n}"
            result[key] = port
        return result

    @staticmethod
    def _paired_port_map(old_map: Dict[str, Dict], ports: List[Dict]) -> Dict[str, Dict]:
        """New output ports under the key of the stored port they update.

        The repository updates an output port by id, so a sent port takes the key
        of the stored port with its id and name; the others take the next unpaired
        stored port of their name, in order, or a key of their own. Reordering two
        same-named ports so compares each with itself, not with its neighbour.
        """
        free = dict(old_map)
        result: Dict[str, Dict] = {}
        unpaired = []
        for port in ports or []:
            if not port:
                continue
            key = next((k for k, old in free.items()
                        if port.get('id') and old.get('id') == port.get('id')
                        and old.get('name') == port.get('name')), None)
            if key is None:
                unpaired.append(port)
                continue
            free.pop(key)
            result[key] = port
        for port in unpaired:
            name = port.get('name')
            key = next((k for k, old in free.items() if old.get('name') == name), None)
            if key is None:
                key, n = name, 1
                while key in old_map or key in result:
                    n += 1
                    key = f"{name}#{n}"
            else:
                free.pop(key)
            result[key] = port
        return result

    @staticmethod
    def _has_any(port: Dict, keys) -> bool:
        return any(k in port for k in keys)

    @staticmethod
    def _first(port: Dict, keys):
        for k in keys:
            if port.get(k) is not None:
                return port[k]
        return None

    @staticmethod
    def _norm(value):
        """Compare None, '' and False alike; drop unset keys of a server dict."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith('{'):
                try:
                    import json
                    value = json.loads(stripped)
                except ValueError:
                    return stripped or None
            else:
                return stripped or None
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if v not in (None, '')} or None
        return value or None

    def _record_modified(
        self, port_type: str, port_name: str, field: str, old_value, new_value,
        description: str, breaking: bool,
    ):
        if breaking:
            self.breaking_changes.append(description)
        else:
            self.fixes.append(description)
        self.port_changes.append(PortChange(
            change_type="modified",
            port_type=port_type,
            port_name=port_name,
            field_name=field,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            severity=ChangeSeverity.CRITICAL if breaking else ChangeSeverity.MINOR,
        ))

    def _analyze_team_changes(self, old_members: List[Dict], new_members: List[Dict]):
        """Analyze changes in team members"""
        # `m.get('name', m.get('email', ''))` keys on name, falling back to email.
        # `or ''` guards against a stored member with name=None / email=None.
        old_member_map = {
            (m.get('name') or m.get('email') or ''): m
            for m in (old_members or []) if m
        }
        new_member_map = {
            (m.get('name') or m.get('email') or ''): m
            for m in (new_members or []) if m
        }

        old_keys = set(old_member_map.keys())
        new_keys = set(new_member_map.keys())

        # Removed members
        for removed_key in old_keys - new_keys:
            old_member = old_member_map[removed_key]
            role = old_member.get('role') or 'unknown'

            # Removing owner or critical roles could be breaking
            if role.lower() in ('owner', 'productOwner', 'product_owner'):
                self.breaking_changes.append(f"Removed team member with critical role: {removed_key} ({role})")
            else:
                self.fixes.append(f"Removed team member: {removed_key} ({role})")
            
            self.team_changes.append({
                'type': 'removed',
                'member': removed_key,
                'role': role
            })

        # Added members (always a feature)
        for added_key in new_keys - old_keys:
            new_member = new_member_map[added_key]
            role = new_member.get('role') or 'unknown'
            self.new_features.append(f"Added team member: {added_key} ({role})")
            self.team_changes.append({
                'type': 'added',
                'member': added_key,
                'role': role
            })

    def _analyze_support_changes(self, old_support: List[Dict], new_support: List[Dict]):
        """Analyze changes in support channels"""
        old_channel_map = {
            (s.get('channel') or s.get('type') or ''): s
            for s in (old_support or []) if s
        }
        new_channel_map = {
            (s.get('channel') or s.get('type') or ''): s
            for s in (new_support or []) if s
        }

        old_channels = set(old_channel_map.keys())
        new_channels = set(new_channel_map.keys())

        # Removed support channels (minor)
        for removed_channel in old_channels - new_channels:
            self.fixes.append(f"Removed support channel: {removed_channel}")
            self.support_changes.append({
                'type': 'removed',
                'channel': removed_channel
            })

        # Added support channels (feature)
        for added_channel in new_channels - old_channels:
            self.new_features.append(f"Added support channel: {added_channel}")
            self.support_changes.append({
                'type': 'added',
                'channel': added_channel
            })

    def _analyze_description_changes(self, old_desc: Dict, new_desc: Dict):
        """Analyze changes in description (always patch level)"""
        # Description changes are informational only
        if old_desc.get('purpose') != new_desc.get('purpose'):
            self.fixes.append("Updated purpose description")
        
        if old_desc.get('limitations') != new_desc.get('limitations'):
            self.fixes.append("Updated limitations description")
        
        if old_desc.get('usage') != new_desc.get('usage'):
            self.fixes.append("Updated usage description")

    def _determine_change_type(self) -> Tuple[ChangeType, str]:
        """Determine change type and recommended version bump"""
        if self.breaking_changes:
            return ChangeType.BREAKING, "major"
        elif self.new_features:
            return ChangeType.FEATURE, "minor"
        elif self.fixes:
            return ChangeType.FIX, "patch"
        else:
            return ChangeType.NONE, "none"

    def _generate_summary(self) -> str:
        """Generate human-readable summary of changes"""
        parts = []

        if self.breaking_changes:
            parts.append(f"**Breaking Changes ({len(self.breaking_changes)}):**\n" +
                        "\n".join(f"- {c}" for c in self.breaking_changes))

        if self.new_features:
            parts.append(f"**New Features ({len(self.new_features)}):**\n" +
                        "\n".join(f"- {f}" for f in self.new_features))

        if self.fixes:
            parts.append(f"**Improvements ({len(self.fixes)}):**\n" +
                        "\n".join(f"- {f}" for f in self.fixes))

        if not parts:
            return "No significant changes detected"

        return "\n\n".join(parts)

