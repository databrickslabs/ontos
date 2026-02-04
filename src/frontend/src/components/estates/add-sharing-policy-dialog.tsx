import React from 'react';
import { useForm, useFieldArray, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogClose
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Trash2, PlusCircle } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import {
  SharingPolicy, SharingResourceType, SharingRuleOperator // SharingRule and Estate removed - unused
} from '@/views/estate-details';

// Define arrays for z.enum
const sharingRuleOperatorValues: [SharingRuleOperator, ...SharingRuleOperator[]] = [
    'equals', 'contains', 'starts_with', 'regex'
];
const sharingResourceTypeValues: [SharingResourceType, ...SharingResourceType[]] = [
    'data_product', 'business_glossary'
];

// Zod Schema for Validation
const sharingRuleSchema = z.object({
  filter_type: z.string().min(1, 'Filter type is required'),
  operator: z.enum(sharingRuleOperatorValues), // Changed to z.enum
  filter_value: z.string().min(1, 'Filter value is required'),
});

const sharingPolicySchema = z.object({
  name: z.string().min(3, 'Policy name must be at least 3 characters'),
  description: z.string().optional(),
  resource_type: z.enum(sharingResourceTypeValues), // Changed to z.enum
  rules: z.array(sharingRuleSchema).min(1, 'At least one rule is required'),
  is_enabled: z.boolean(),
});

type SharingPolicyFormData = z.infer<typeof sharingPolicySchema>;

interface AddSharingPolicyDialogProps {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  estateId: string; // Kept for context, might be useful for future validation or more complex dialog logic
  // Callback to inform parent about the new policy
  onSaveSuccess: (newPolicy: SharingPolicy) => void; 
  currentPolicies: SharingPolicy[]; // Pass current policies for potential validation (e.g., unique names)
}

const AddSharingPolicyDialog: React.FC<AddSharingPolicyDialogProps> = ({
  isOpen,
  onOpenChange,
  estateId: _estateId, // Kept for potential future use
  onSaveSuccess,
  currentPolicies: _currentPolicies, // Kept for potential validation
}) => {
  const { toast } = useToast();
  const { control, handleSubmit, register, formState: { errors }, reset, watch: _watch } = useForm<SharingPolicyFormData>({
    resolver: zodResolver(sharingPolicySchema),
    defaultValues: {
      name: '',
      description: '',
      resource_type: 'data_product', // Default value
      rules: [{ filter_type: '', operator: 'equals', filter_value: '' }],
      is_enabled: true,
    },
  });

  const { fields, append, remove } = useFieldArray({
    control,
    name: 'rules',
  });

  const onSubmit = async (data: SharingPolicyFormData) => {
    const newPolicy: SharingPolicy = {
      ...data,
      // id: `policy-${Date.now()}-${Math.random().toString(36).substring(2,7)}`, // Backend will assign ID
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    // The parent component (EstateDetailsView) will handle adding this to the estate and making the API call.
    // No need to construct updatedEstatePayload here.

    try {
        onSaveSuccess(newPolicy); // Pass only the new policy object to parent
        
        // Toast and reset are good here as the dialog is closing.
        toast({
            title: 'Policy Submitted', // Changed title as actual save happens in parent
            description: `Sharing policy "${data.name}" is being processed.`,
        });
        reset(); // Reset form fields
        onOpenChange(false); // Close dialog
    } catch (error) {
        console.error("Error saving new policy:", error);
        toast({
            title: 'Error',
            description: 'Failed to add sharing policy. Check console for details.',
            variant: 'destructive',
        });
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => {
      if (!open) reset(); // Reset form if dialog is closed without saving
      onOpenChange(open);
    }}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add New Sharing Policy</DialogTitle>
          <DialogDescription>
            Define a new policy to share resources from or with this estate.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 py-2 pb-4">
          <div>
            <Label htmlFor="name">Policy Name</Label>
            <Input id="name" {...register('name')} placeholder="e.g., Share Production Data Products" />
            {errors.name && <p className="text-sm text-red-500 mt-1">{errors.name.message}</p>}
          </div>

          <div>
            <Label htmlFor="description">Description (Optional)</Label>
            <Textarea id="description" {...register('description')} placeholder="Detailed description of the policy's purpose..." />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="resource_type">Resource Type</Label>
              <Controller
                name="resource_type"
                control={control}
                render={({ field }) => (
                  <Select onValueChange={field.onChange} defaultValue={field.value}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select resource type" />
                    </SelectTrigger>
                    <SelectContent>
                      {sharingResourceTypeValues.map(val => <SelectItem key={val} value={val}>{val.replace('_', ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}</SelectItem>)}
                    </SelectContent>
                  </Select>
                )}
              />
               {errors.resource_type && <p className="text-sm text-red-500 mt-1">{errors.resource_type.message}</p>}
            </div>
            <div className="flex flex-col justify-end">
                <div className="flex items-center space-x-2 mt-4">
                    <Controller
                        name="is_enabled"
                        control={control}
                        render={({ field }) => (
                            <Switch
                            id="is_enabled"
                            checked={field.value}
                            onCheckedChange={field.onChange}
                            />
                        )}
                    />
                    <Label htmlFor="is_enabled">Enable Policy</Label>
                </div>
            </div>
          </div>
          
          <div className="space-y-3">
            <h4 className="text-md font-medium">Rules</h4>
            {fields.map((item, index) => (
              <div key={item.id} className="p-3 border rounded-md space-y-2 bg-muted/50">
                <div className="flex justify-between items-center">
                  <Label className="text-sm font-semibold">Rule {index + 1}</Label>
                  {fields.length > 1 && (
                    <Button type="button" variant="ghost" size="icon" className="h-7 w-7 text-red-500" onClick={() => remove(index)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <Label htmlFor={`rules.${index}.filter_type`}>Filter Type</Label>
                    <Input {...register(`rules.${index}.filter_type`)} placeholder="e.g., tag, domain, status"/>
                    {errors.rules && errors.rules[index] && errors.rules[index]!.filter_type && <p className="text-sm text-red-500 mt-1">{errors.rules[index]!.filter_type!.message}</p>}
                  </div>
                  <div>
                    <Label htmlFor={`rules.${index}.operator`}>Operator</Label>
                    <Controller
                      name={`rules.${index}.operator`}
                      control={control}
                      render={({ field }) => (
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select operator" />
                          </SelectTrigger>
                          <SelectContent>
                            {sharingRuleOperatorValues.map(val => <SelectItem key={val} value={val}>{val.replace('_', ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      )}
                    />
                    {errors.rules && errors.rules[index] && errors.rules[index]!.operator && <p className="text-sm text-red-500 mt-1">{errors.rules[index]!.operator!.message}</p>}
                  </div>
                  <div>
                    <Label htmlFor={`rules.${index}.filter_value`}>Value</Label>
                    <Input {...register(`rules.${index}.filter_value`)} placeholder="e.g., finance, Active" />
                    {errors.rules && errors.rules[index] && errors.rules[index]!.filter_value && <p className="text-sm text-red-500 mt-1">{errors.rules[index]!.filter_value!.message}</p>}
                  </div>
                </div>
              </div>
            ))}
            {errors.rules && typeof errors.rules.message === 'string' && (
                <p className="text-sm text-red-500 mt-1">{errors.rules.message}</p> // For array-level errors like min(1)
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => append({ filter_type: '', operator: 'equals', filter_value: '' })}
            >
              <PlusCircle className="mr-2 h-4 w-4" /> Add Rule
            </Button>
          </div>

          <DialogFooter>
            <DialogClose asChild>
                <Button type="button" variant="outline">Cancel</Button>
            </DialogClose>
            <Button type="submit">Add Policy</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default AddSharingPolicyDialog; 