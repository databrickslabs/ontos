import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Plus, Trash2 } from 'lucide-react';
import {
  type GraphNode,
  type GraphEdge,
  type NodeProperties,
  type EdgeProperties,
} from '@/types/graph-explorer';

// NodeForm Component
export interface NodeFormProps {
  open: boolean;
  onClose: () => void;
  onSave: (node: Omit<GraphNode, 'status'>) => void;
  onDelete?: (nodeId: string) => void;
  initialData?: GraphNode;
  mode: 'create' | 'edit';
}

export function NodeForm({
  open,
  onClose,
  onSave,
  onDelete,
  initialData,
  mode,
}: NodeFormProps) {
  const [id, setId] = useState(initialData?.id ?? '');
  const [label, setLabel] = useState(initialData?.label ?? '');
  const [type, setType] = useState(initialData?.type ?? '');
  const [properties, setProperties] = useState<Array<{ key: string; value: string }>>(
    initialData
      ? Object.entries(initialData.properties).map(([key, value]) => ({
          key,
          value: String(value ?? ''),
        }))
      : [],
  );

  const handleAddProperty = () => {
    setProperties([...properties, { key: '', value: '' }]);
  };

  const handleRemoveProperty = (index: number) => {
    setProperties(properties.filter((_, i) => i !== index));
  };

  const handlePropertyChange = (index: number, field: 'key' | 'value', value: string) => {
    const updated = [...properties];
    updated[index] = { ...updated[index], [field]: value };
    setProperties(updated);
  };

  const handleSave = () => {
    if (!label.trim()) {
      return;
    }

    const props: NodeProperties = {};
    properties.forEach((prop) => {
      if (prop.key.trim()) {
        // Try to parse as number or boolean, otherwise keep as string
        const trimmedValue = prop.value.trim();
        if (trimmedValue === 'true') {
          props[prop.key.trim()] = true;
        } else if (trimmedValue === 'false') {
          props[prop.key.trim()] = false;
        } else if (!isNaN(Number(trimmedValue)) && trimmedValue !== '') {
          props[prop.key.trim()] = Number(trimmedValue);
        } else if (trimmedValue === '') {
          props[prop.key.trim()] = null;
        } else {
          props[prop.key.trim()] = trimmedValue;
        }
      }
    });

    onSave({
      id: mode === 'edit' && id ? id : label.toLowerCase().replace(/\s+/g, '-'),
      label: label.trim(),
      type: type.trim() || 'Node',
      properties: props,
    });

    onClose();
  };

  const handleDelete = () => {
    if (onDelete && id) {
      onDelete(id);
      onClose();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{mode === 'create' ? 'Create Node' : 'Edit Node'}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* ID Field */}
          <div className="space-y-2">
            <Label htmlFor="node-id">ID</Label>
            <Input
              id="node-id"
              value={id}
              onChange={(e) => setId(e.target.value)}
              disabled={mode === 'edit'}
              placeholder="Auto-generated from label if empty"
            />
          </div>

          {/* Label Field */}
          <div className="space-y-2">
            <Label htmlFor="node-label">
              Label <span className="text-destructive">*</span>
            </Label>
            <Input
              id="node-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Enter node label"
              required
            />
          </div>

          {/* Type Field */}
          <div className="space-y-2">
            <Label htmlFor="node-type">Type</Label>
            <Input
              id="node-type"
              value={type}
              onChange={(e) => setType(e.target.value)}
              placeholder="Enter node type"
            />
          </div>

          {/* Properties */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Properties</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleAddProperty}
              >
                <Plus className="mr-2 h-4 w-4" />
                Add Property
              </Button>
            </div>
            <div className="space-y-2">
              {properties.map((prop, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    placeholder="Key"
                    value={prop.key}
                    onChange={(e) => handlePropertyChange(index, 'key', e.target.value)}
                    className="flex-1"
                  />
                  <Input
                    placeholder="Value"
                    value={prop.value}
                    onChange={(e) => handlePropertyChange(index, 'value', e.target.value)}
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRemoveProperty(index)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              {properties.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No properties added. Click &quot;Add Property&quot; to add key-value pairs.
                </p>
              )}
            </div>
          </div>
        </div>

        <DialogFooter>
          {mode === 'edit' && onDelete && (
            <Button type="button" variant="destructive" onClick={handleDelete}>
              Delete
            </Button>
          )}
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSave} disabled={!label.trim()}>
            {mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// EdgeForm Component
export interface EdgeFormProps {
  open: boolean;
  onClose: () => void;
  onSave: (edge: Omit<GraphEdge, 'status'>) => void;
  onDelete?: (edgeId: string) => void;
  initialData?: GraphEdge;
  sourceNodeId?: string;
  targetNodeId?: string;
  mode: 'create' | 'edit';
  availableNodes?: GraphNode[];
}

export function EdgeForm({
  open,
  onClose,
  onSave,
  onDelete,
  initialData,
  sourceNodeId: initialSourceNodeId,
  targetNodeId: initialTargetNodeId,
  mode,
  availableNodes = [],
}: EdgeFormProps) {
  const [id, setId] = useState(initialData?.id ?? '');
  const [sourceNodeId, setSourceNodeId] = useState(initialData?.source ?? initialSourceNodeId ?? '');
  const [targetNodeId, setTargetNodeId] = useState(initialData?.target ?? initialTargetNodeId ?? '');
  const [relationshipType, setRelationshipType] = useState(initialData?.relationshipType ?? '');
  const [properties, setProperties] = useState<Array<{ key: string; value: string }>>(
    initialData
      ? Object.entries(initialData.properties).map(([key, value]) => ({
          key,
          value: String(value ?? ''),
        }))
      : [],
  );

  const handleAddProperty = () => {
    setProperties([...properties, { key: '', value: '' }]);
  };

  const handleRemoveProperty = (index: number) => {
    setProperties(properties.filter((_, i) => i !== index));
  };

  const handlePropertyChange = (index: number, field: 'key' | 'value', value: string) => {
    const updated = [...properties];
    updated[index] = { ...updated[index], [field]: value };
    setProperties(updated);
  };

  const handleSave = () => {
    if (!sourceNodeId || !targetNodeId || !relationshipType.trim()) {
      return;
    }

    const props: EdgeProperties = {};
    properties.forEach((prop) => {
      if (prop.key.trim()) {
        const trimmedValue = prop.value.trim();
        if (trimmedValue === 'true') {
          props[prop.key.trim()] = true;
        } else if (trimmedValue === 'false') {
          props[prop.key.trim()] = false;
        } else if (!isNaN(Number(trimmedValue)) && trimmedValue !== '') {
          props[prop.key.trim()] = Number(trimmedValue);
        } else if (trimmedValue === '') {
          props[prop.key.trim()] = null;
        } else {
          props[prop.key.trim()] = trimmedValue;
        }
      }
    });

    onSave({
      id:
        mode === 'edit' && id
          ? id
          : `${sourceNodeId}-${relationshipType}-${targetNodeId}`,
      source: sourceNodeId,
      target: targetNodeId,
      relationshipType: relationshipType.trim(),
      properties: props,
    });

    onClose();
  };

  const handleDelete = () => {
    if (onDelete && id) {
      onDelete(id);
      onClose();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {mode === 'create' ? 'Create Edge' : 'Edit Edge'}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* ID Field */}
          <div className="space-y-2">
            <Label htmlFor="edge-id">ID</Label>
            <Input
              id="edge-id"
              value={id}
              onChange={(e) => setId(e.target.value)}
              disabled={mode === 'edit'}
              placeholder="Auto-generated if empty"
            />
          </div>

          {/* Source Node */}
          <div className="space-y-2">
            <Label htmlFor="edge-source">
              Source Node <span className="text-destructive">*</span>
            </Label>
            <Select value={sourceNodeId} onValueChange={setSourceNodeId}>
              <SelectTrigger id="edge-source">
                <SelectValue placeholder="Select source node" />
              </SelectTrigger>
              <SelectContent>
                {availableNodes.map((node) => (
                  <SelectItem key={node.id} value={node.id}>
                    {node.label} ({node.type})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Target Node */}
          <div className="space-y-2">
            <Label htmlFor="edge-target">
              Target Node <span className="text-destructive">*</span>
            </Label>
            <Select value={targetNodeId} onValueChange={setTargetNodeId}>
              <SelectTrigger id="edge-target">
                <SelectValue placeholder="Select target node" />
              </SelectTrigger>
              <SelectContent>
                {availableNodes.map((node) => (
                  <SelectItem key={node.id} value={node.id}>
                    {node.label} ({node.type})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Relationship Type */}
          <div className="space-y-2">
            <Label htmlFor="edge-type">
              Relationship Type <span className="text-destructive">*</span>
            </Label>
            <Input
              id="edge-type"
              value={relationshipType}
              onChange={(e) => setRelationshipType(e.target.value)}
              placeholder="Enter relationship type"
              required
            />
          </div>

          {/* Properties */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Properties</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleAddProperty}
              >
                <Plus className="mr-2 h-4 w-4" />
                Add Property
              </Button>
            </div>
            <div className="space-y-2">
              {properties.map((prop, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    placeholder="Key"
                    value={prop.key}
                    onChange={(e) => handlePropertyChange(index, 'key', e.target.value)}
                    className="flex-1"
                  />
                  <Input
                    placeholder="Value"
                    value={prop.value}
                    onChange={(e) => handlePropertyChange(index, 'value', e.target.value)}
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRemoveProperty(index)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              {properties.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No properties added. Click &quot;Add Property&quot; to add key-value pairs.
                </p>
              )}
            </div>
          </div>
        </div>

        <DialogFooter>
          {mode === 'edit' && onDelete && (
            <Button type="button" variant="destructive" onClick={handleDelete}>
              Delete
            </Button>
          )}
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={!sourceNodeId || !targetNodeId || !relationshipType.trim()}
          >
            {mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
