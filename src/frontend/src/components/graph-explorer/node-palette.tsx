import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { PlusCircle, Link } from 'lucide-react';

interface NodePaletteProps {
  onStartCreateNode?: () => void;
  onStartCreateEdge: () => void;
  disabled?: boolean;
}

export default function NodePalette({
  onStartCreateNode,
  onStartCreateEdge,
  disabled = false,
}: NodePaletteProps) {
  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>Create</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Create Node Button */}
        <Button
          onClick={onStartCreateNode}
          disabled={disabled || !onStartCreateNode}
          className="w-full"
          size="lg"
        >
          <PlusCircle className="mr-2 h-5 w-5" />
          Create Node
        </Button>

        <Separator />

        {/* Relationships Section */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Link className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">Relationships</CardTitle>
          </div>
          <Button
            onClick={onStartCreateEdge}
            disabled={disabled}
            variant="outline"
            className="w-full"
          >
            <Link className="mr-2 h-4 w-4" />
            Create Edge
          </Button>
        </div>

        <Separator />

        {/* Instructions */}
        <div className="space-y-3">
          <CardTitle className="text-base">Instructions</CardTitle>
          <div className="space-y-2 text-sm text-muted-foreground">
            <div className="flex items-start gap-2">
              <span className="font-semibold text-foreground">1.</span>
              <span>Click &quot;Create Node&quot; to add a new node to the graph</span>
            </div>
            <div className="flex items-start gap-2">
              <span className="font-semibold text-foreground">2.</span>
              <span>Click &quot;Create Edge&quot; to connect two nodes</span>
            </div>
            <div className="flex items-start gap-2">
              <span className="font-semibold text-foreground">3.</span>
              <span>Click on a node or edge to edit its properties</span>
            </div>
            <div className="flex items-start gap-2">
              <span className="font-semibold text-foreground">4.</span>
              <span>Right-click or use the context menu to delete items</span>
            </div>
          </div>
        </div>

        <Separator />

        {/* Tip Box */}
        <div className="rounded-lg bg-muted/50 p-3">
          <div className="text-xs font-semibold text-foreground mb-1">Tip</div>
          <div className="text-xs text-muted-foreground">
            You can drag nodes to reposition them in the graph. Use the controls panel to
            filter by type or adjust the layout.
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
