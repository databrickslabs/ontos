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
      - Removed required input ports
      - Changed port contract IDs (incompatible)
      - Removed team members with critical roles
    - MINOR (0.X.0): New features (backward compatible)
      - New output ports
      - New optional input ports
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
            old_product.get('inputPorts') or [],
            new_product.get('inputPorts') or [],
            'input'
        )
        self._analyze_port_changes(
            old_product.get('outputPorts') or [],
            new_product.get('outputPorts') or [],
            'output'
        )
        self._analyze_port_changes(
            old_product.get('managementPorts') or [],
            new_product.get('managementPorts') or [],
            'management'
        )

        # Analyze team changes
        self._analyze_team_changes(
            (old_product.get('team') or {}).get('members') or [],
            (new_product.get('team') or {}).get('members') or []
        )

        # Analyze support channel changes
        self._analyze_support_changes(
            old_product.get('support') or [],
            new_product.get('support') or []
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
        old_port_map = {p.get('name'): p for p in (old_ports or []) if p}
        new_port_map = {p.get('name'): p for p in (new_ports or []) if p}

        old_names = set(old_port_map.keys())
        new_names = set(new_port_map.keys())

        # Removed ports
        for removed_name in old_names - new_names:
            if port_type == 'output':
                # Removing output port is BREAKING (consumers depend on it)
                self.breaking_changes.append(f"Removed {port_type} port: {removed_name}")
                severity = ChangeSeverity.CRITICAL
            elif port_type == 'input':
                # Removing input port might be breaking if it was required
                old_port = old_port_map[removed_name]
                if old_port.get('required', False):
                    self.breaking_changes.append(f"Removed required {port_type} port: {removed_name}")
                    severity = ChangeSeverity.CRITICAL
                else:
                    self.fixes.append(f"Removed optional {port_type} port: {removed_name}")
                    severity = ChangeSeverity.MINOR
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
                # New input port
                new_port = new_port_map[added_name]
                if new_port.get('required', False):
                    # Adding required input is BREAKING (producers must provide it)
                    self.breaking_changes.append(f"Added required {port_type} port: {added_name}")
                    severity = ChangeSeverity.CRITICAL
                else:
                    self.new_features.append(f"Added optional {port_type} port: {added_name}")
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

            # Check contract ID changes (critical for output ports)
            old_contract = old_port.get('contractId') or old_port.get('contract_id')
            new_contract = new_port.get('contractId') or new_port.get('contract_id')

            if old_contract and new_contract and old_contract != new_contract:
                if port_type == 'output':
                    # Changing output contract is BREAKING
                    self.breaking_changes.append(
                        f"Changed contract for {port_type} port '{port_name}': {old_contract} → {new_contract}"
                    )
                    severity = ChangeSeverity.CRITICAL
                else:
                    self.fixes.append(
                        f"Changed contract for {port_type} port '{port_name}': {old_contract} → {new_contract}"
                    )
                    severity = ChangeSeverity.MINOR

                self.port_changes.append(PortChange(
                    change_type="modified",
                    port_type=port_type,
                    port_name=port_name,
                    field_name="contractId",
                    old_value=old_contract,
                    new_value=new_contract,
                    severity=severity
                ))

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

