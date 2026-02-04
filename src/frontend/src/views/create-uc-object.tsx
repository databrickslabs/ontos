import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle } from 'lucide-react';
import { useApi } from '@/hooks/use-api';

type ObjectType = 'catalog' | 'schema';

export default function CreateUcObject() {
  const { t: _t } = useTranslation('common');
  const navigate = useNavigate();
  const { get: _get, post } = useApi();
  const [objectType, setObjectType] = useState<ObjectType>('catalog');
  const [catalogName, setCatalogName] = useState('');
  const [schemaName, setSchemaName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const namingConventionRule = "ASSERT obj.name MATCHES '^[a-z][a-z0-9_]*$'"; // simplified assert

  const validateInline = async () => {
    setMessages([]);
    const name = objectType === 'catalog' ? catalogName : schemaName;
    try {
      // Call backend compliance run inline with a transient object
      const payload = {
        rule: namingConventionRule,
        object: { type: objectType, name },
      };
      const res = await post<any>('/api/compliance/validate-inline', payload);
      if (res.error) throw new Error(res.error);
      const m: string[] = [];
      if (res.data && res.data.passed === false) {
        m.push(res.data.message || 'Failed naming convention');
      }
      setMessages(m);
      return !(res.data && res.data.passed === false);
    } catch (e: any) {
      setMessages([e.message || 'Validation failed']);
      return false;
    }
  };

  const handleCreate = async () => {
    setError(null);
    setIsSubmitting(true);
    const ok = await validateInline();
    if (!ok) { setIsSubmitting(false); return; }
    try {
      // For now we only validate; skip actual UC creation
      setMessages([`Validated ${objectType} '${objectType==='catalog'?catalogName:`${catalogName}.${schemaName}`}' successfully.`]);
    } catch (e: any) {
      setError(e.message || 'Create failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="py-6 space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Create Unity Catalog Object</CardTitle>
          <CardDescription>Validate inputs against compliance checks before creation.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4">
            <Button variant={objectType==='catalog' ? 'default' : 'outline'} onClick={() => setObjectType('catalog')}>Catalog</Button>
            <Button variant={objectType==='schema' ? 'default' : 'outline'} onClick={() => setObjectType('schema')}>Schema</Button>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Catalog Name</Label>
              <Input value={catalogName} onChange={e=>setCatalogName(e.target.value)} placeholder="analytics" />
            </div>
            {objectType==='schema' && (
              <div className="space-y-2">
                <Label>Schema Name</Label>
                <Input value={schemaName} onChange={e=>setSchemaName(e.target.value)} placeholder="customer_360" />
              </div>
            )}
          </div>
          {messages.length>0 && (
            <div className="space-y-1">
              {messages.map((m,i)=>(<div key={i} className="text-sm text-muted-foreground">{m}</div>))}
            </div>
          )}
          {error && (
            <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>
          )}
          <div className="flex gap-2">
            <Button onClick={handleCreate} disabled={isSubmitting}>{isSubmitting? 'Validating...' : 'Create'}</Button>
            <Button variant="outline" onClick={()=>navigate(-1)}>Cancel</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}


