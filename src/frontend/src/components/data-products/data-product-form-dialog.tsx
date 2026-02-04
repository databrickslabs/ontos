import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Plus, AlertCircle, X, Loader2, Check, ChevronsUpDown } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { DataProduct, DataProductStatus, DataProductOwner, MetastoreTableInfo, Link as DataProductLink, DataProductType } from '@/types/data-product';
import { useForm, useFieldArray, Controller, SubmitHandler } from 'react-hook-form';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from "@/lib/utils"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useProjectContext } from '@/stores/project-store'
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "@/components/ui/command"
import { debounce } from 'lodash';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/hooks/use-toast"
import Ajv, { ValidateFunction, ErrorObject } from "ajv"
import addFormats from "ajv-formats"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { useApi } from '@/hooks/use-api';
import TagSelector from '@/components/ui/tag-selector';

// --- Prop Types --- 
interface DataProductFormDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  initialProduct: DataProduct | null; // Product to edit, or null for create
  statuses: DataProductStatus[];
  owners: DataProductOwner[]; // Added owners prop
  productTypes: DataProductType[]; // Add product types prop
  api: ReturnType<typeof useApi>; // Pass the API hook instance
  onSubmitSuccess: (savedProduct: DataProduct) => void; // Callback on successful save
}

// --- Helper Function Type Definition --- 
type CheckApiResponseFn = <T>(
    response: { data?: T | { detail?: string }, error?: string | null },
    name: string
) => T;

// --- Helper Function Implementation --- 
const checkApiResponse: CheckApiResponseFn = (response, name) => {
    if (response.error) {
        throw new Error(`${name} fetch failed: ${response.error}`);
    }
    if (response.data && typeof response.data === 'object' && 'detail' in response.data && typeof response.data.detail === 'string') {
        throw new Error(`${name} fetch failed: ${response.data.detail}`);
    }
    if (response.data === null || response.data === undefined) {
        throw new Error(`${name} fetch returned null or undefined data.`);
    }
    return response.data as any;
};

// --- Helper Functions for Object <-> Array Transformation --- 
const objectToArray = (obj: Record<string, any> | null | undefined): { key: string, value: any }[] => {
  if (!obj) return [];
  return Object.entries(obj).map(([key, value]) => ({ key, value }));
};

const arrayToObject = (arr: { key: string, value: any }[] | null | undefined): Record<string, any> => {
  if (!arr || !Array.isArray(arr)) return {};
  return arr.reduce((acc, { key, value }) => {
    if (key) acc[key] = value; 
    return acc;
  }, {} as Record<string, any>);
};

const linksObjectToArray = (obj: Record<string, DataProductLink> | null | undefined): { key: string, url: string, description: string }[] => {
   if (!obj) return [];
   return Object.entries(obj).map(([key, linkValue]) => ({ key, url: linkValue.url || '', description: linkValue.description || '' }));
};

const linksArrayToObject = (arr: { key: string, url: string, description: string }[] | null | undefined): Record<string, DataProductLink> => {
    if (!arr || !Array.isArray(arr)) return {};
    return arr.reduce((acc, { key, url, description }) => {
       if (key && url) { 
          acc[key] = { url, description: description || undefined }; // Set description to undefined if empty
       }
       return acc;
   }, {} as Record<string, DataProductLink>);
};

const portLinksObjectToArray = (obj: Record<string, string> | null | undefined): { key: string, value: string }[] => {
  if (!obj) return [];
  return Object.entries(obj).map(([key, value]) => ({ key, value: value || '' }));
};

const portLinksArrayToObject = (arr: { key: string, value: string }[] | null | undefined): Record<string, string> => {
  return arrayToObject(arr);
};

// --- Helper Function to Clean Empty Optional Fields --- 
const cleanEmptyOptionalStrings = (data: Record<string, any>): Record<string, any> => {
  const cleanedData = JSON.parse(JSON.stringify(data)); 

  const checkAndClean = (obj: any, fields: string[]) => {
    if (typeof obj !== 'object' || obj === null) return;
    fields.forEach(field => {
      if (obj.hasOwnProperty(field) && (obj[field] === "" || obj[field] === null || obj[field] === undefined)) {
        delete obj[field];
      }
    });
  };

  // Clean Info fields
  if (cleanedData.info) {
    checkAndClean(cleanedData.info, ['domain', 'description', 'status', 'archetype', 'maturity']);
  }

  // Clean Port fields 
  const cleanPort = (port: any) => {
     if (!port) return;
     checkAndClean(port, ['description', 'type', 'location', 'status', 'dataContractId']);
     if (port.links && typeof port.links === 'object' && Object.keys(port.links).length === 0) delete port.links;
     if (port.custom && typeof port.custom === 'object' && Object.keys(port.custom).length === 0) delete port.custom;
     if (Array.isArray(port.tags) && port.tags.length === 0) delete port.tags;

     // Clean Server fields
     if (port.server) {
        checkAndClean(port.server, [
            'project', 'dataset', 'account', 'database', 'schema_name', 
            'host', 'topic', 'location', 'delimiter', 'format', 
            'table', 'view', 'share'
        ]);
        if (port.server.additionalProperties && typeof port.server.additionalProperties === 'object' && Object.keys(port.server.additionalProperties).length === 0) {
            delete port.server.additionalProperties;
        }
        if (Object.keys(port.server).length === 0) {
           delete port.server;
        }
     }
     
     // Clean specific OutputPort fields (already covered by checkAndClean above)
     // checkAndClean(port, ['status', 'dataContractId']); 
  };

  (cleanedData.inputPorts || []).forEach(cleanPort);
  (cleanedData.outputPorts || []).forEach(cleanPort);

  // Clean top-level optional fields/empty collections
  if (Array.isArray(cleanedData.tags) && cleanedData.tags.length === 0) delete cleanedData.tags;
  if (cleanedData.links && typeof cleanedData.links === 'object' && Object.keys(cleanedData.links).length === 0) delete cleanedData.links;
  if (cleanedData.custom && typeof cleanedData.custom === 'object' && Object.keys(cleanedData.custom).length === 0) delete cleanedData.custom;
  if (Array.isArray(cleanedData.inputPorts) && cleanedData.inputPorts.length === 0) delete cleanedData.inputPorts;
  if (Array.isArray(cleanedData.outputPorts) && cleanedData.outputPorts.length === 0) delete cleanedData.outputPorts;

  // Remove timestamps as they are handled by backend/main logic
  delete cleanedData.created_at;
  delete cleanedData.updated_at;

  return cleanedData;
};

// --- Default Product Creator --- 
const createDefaultProduct = (): DataProduct => {
  // No need for timestamps here, they are added during submit or by backend
  return {
    // Required ODPS fields
    apiVersion: "v1.0.0",
    kind: "DataProduct",
    id: "", // Generated on submit
    status: "draft",
    // Optional fields
    dataProductSpecification: "0.0.1",
    info: { title: "", owner: "" },
    inputPorts: [],
    version: "1.0.0", // Default version
    productType: "", // Default type (user should select)
    outputPorts: [],
    links: {}, 
    custom: {}, 
    tags: [],
    // updated_at will be set on submit
    updated_at: '' // Placeholder, will be replaced
  };
};

// --- Port Metadata Editor Sub-Component --- 
interface PortMetadataEditorProps {
  control: any; 
  register: any; 
  getValues: any; 
  setValue: any; 
  portIndex: number;
  portType: 'inputPorts' | 'outputPorts';
}

const PortMetadataEditor: React.FC<PortMetadataEditorProps> = React.memo(({
  control: _control, register: _register, getValues, setValue, portIndex, portType
}) => {
  const linksFieldName = `${portType}.${portIndex}.links` as const;
  const customFieldName = `${portType}.${portIndex}.custom` as const;

  const initialLinks = useMemo(() => portLinksObjectToArray(getValues(linksFieldName)), [getValues, linksFieldName]);
  const initialCustom = useMemo(() => objectToArray(getValues(customFieldName)), [getValues, customFieldName]);

  const [portLinksArray, setPortLinksArray] = useState(initialLinks);
  const [portCustomArray, setPortCustomArray] = useState(initialCustom);

  useEffect(() => {
    setValue(linksFieldName, portLinksArrayToObject(portLinksArray), { shouldValidate: false, shouldDirty: true });
  }, [portLinksArray, setValue, linksFieldName]);

  useEffect(() => {
    setValue(customFieldName, arrayToObject(portCustomArray), { shouldValidate: false, shouldDirty: true });
  }, [portCustomArray, setValue, customFieldName]);

  return (
    <div className="space-y-4 mt-4 pt-4 border-t">
        {/* Port Links Editor */}
        <div className="space-y-2">
            <Label className="font-semibold">Port Links</Label>
            {portLinksArray.map((link: { key: string, value: string }, index: number) => (
               <div key={`link-${portType}-${portIndex}-${index}`} className="flex items-center gap-2">
                  <Input
                      placeholder="Link Key"
                      value={link.key}
                      onChange={(e) => {
                          const newArr = [...portLinksArray];
                          newArr[index].key = e.target.value;
                          setPortLinksArray(newArr);
                      }}
                      className="flex-1"
                  />
                  <Input
                      placeholder="URL"
                      value={link.value}
                       onChange={(e) => {
                          const newArr = [...portLinksArray];
                          newArr[index].value = e.target.value;
                          setPortLinksArray(newArr);
                      }}
                      className="flex-1"
                  />
                  <Button
                      type="button" variant="ghost" size="icon"
                      onClick={() => setPortLinksArray(portLinksArray.filter((_: { key: string, value: string }, i: number) => i !== index))}
                      className="text-destructive" title="Remove Link">
                      <X className="h-4 w-4" />
                  </Button>
               </div>
            ))}
            <div>
              <Button
                 type="button" variant="outline" size="sm"
                 onClick={() => setPortLinksArray([...portLinksArray, { key: '', value: '' }])}>
                 <Plus className="mr-2 h-4 w-4"/> Add Link
              </Button>
            </div>
        </div>

        {/* Port Custom Properties Editor */}
        <div className="space-y-2">
            <Label className="font-semibold">Port Custom Properties</Label>
            {portCustomArray.map((custom: { key: string, value: any }, index: number) => (
               <div key={`custom-${portType}-${portIndex}-${index}`} className="flex items-center gap-2">
                  <Input
                      placeholder="Property Key"
                      value={custom.key}
                      onChange={(e) => {
                          const newArr = [...portCustomArray];
                          newArr[index].key = e.target.value;
                          setPortCustomArray(newArr);
                      }}
                      className="flex-1"
                  />
                  <Input
                      placeholder="Property Value"
                      value={custom.value}
                       onChange={(e) => {
                          const newArr = [...portCustomArray];
                          newArr[index].value = e.target.value;
                          setPortCustomArray(newArr);
                      }}
                      className="flex-1"
                  />
                  <Button
                      type="button" variant="ghost" size="icon"
                      onClick={() => setPortCustomArray(portCustomArray.filter((_: { key: string, value: any }, i: number) => i !== index))}
                      className="text-destructive" title="Remove Property">
                      <X className="h-4 w-4" />
                  </Button>
               </div>
            ))}
            <div>
              <Button
                 type="button" variant="outline" size="sm"
                 onClick={() => setPortCustomArray([...portCustomArray, { key: '', value: '' }])}>
                 <Plus className="mr-2 h-4 w-4"/> Add Custom Property
              </Button>
            </div>
        </div>
    </div>
  );
});

// --- Main Dialog Component ---
const DataProductFormDialog: React.FC<DataProductFormDialogProps> = ({ 
    isOpen, 
    onOpenChange, 
    initialProduct, 
    statuses, 
    owners: _owners, // Unused but kept for prop interface compatibility
    productTypes, // Add productTypes to destructuring
    api, 
    onSubmitSuccess 
}) => {
  const { get, post, put } = api; // Destructure methods from passed api object
  const { toast } = useToast();
  const { currentProject, availableProjects, fetchUserProjects, isLoading: projectsLoading } = useProjectContext();
  const isEditMode = !!initialProduct?.id;
  const [isLoadingProduct, setIsLoadingProduct] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // State for managing dynamic arrays for Links and Custom properties (main product)
  const [linksArray, setLinksArray] = useState<{key: string, url: string, description: string}[]>([]);
  const [customArray, setCustomArray] = useState<{key: string, value: any}[]>([]); // Value can be any type

  // State for Table Search Combobox
  const [tableSearchQuery, setTableSearchQuery] = useState("");
  const [tableSearchResults, setTableSearchResults] = useState<MetastoreTableInfo[]>([]);
  const [isSearchingTables, setIsSearchingTables] = useState(false);
  const [isComboboxOpen, setIsComboboxOpen] = useState<Record<string, boolean>>({}); // Use port field id as key

  // State for JSON Editor Tab
  const [activeTab, setActiveTab] = useState<'ui' | 'json'>('ui');
  const [jsonString, setJsonString] = useState<string>('');
  const [isJsonValid, setIsJsonValid] = useState<boolean>(true);
  const [jsonParseError, setJsonParseError] = useState<string | null>(null);

  // State for Schema Validation
  const [dataProductSchema, setDataProductSchema] = useState<object | null>(null);
  const [schemaValidator, setSchemaValidator] = useState<ValidateFunction | null>(null);
  const [validationStatusMessage, setValidationStatusMessage] = useState<string | null>(null);
  const [_isSchemaLoading, setIsSchemaLoading] = useState<boolean>(false);
  const [schemaValidationErrors, setSchemaValidationErrors] = useState<ErrorObject[] | null>(null);

  const ajv = useRef<Ajv | null>(null);

  // --- React Hook Form Setup ---
  const { 
    register, 
    handleSubmit, 
    control, 
    reset, 
    watch: _watch, 
    getValues, // Get getValues and setValue from useForm
    setValue,
    formState: { errors, isSubmitting, dirtyFields: _dirtyFields, isDirty } // Track dirty state
  } = useForm<DataProduct>({
    defaultValues: createDefaultProduct(), // Start with default
  });

  // Field Arrays for Ports
  const { fields: inputPortFields, append: appendInputPort, remove: removeInputPort } = useFieldArray({ control, name: "inputPorts" });
  const { fields: outputPortFields, append: appendOutputPort, remove: removeOutputPort } = useFieldArray({ control, name: "outputPorts" });

  // --- Effects --- 

  // Initialize Ajv
  useEffect(() => {
    if (!ajv.current) {
      // Security: allErrors is set to false (default) to prevent DoS attacks
      // This means validation will stop at the first error instead of collecting all errors
      const ajvInstance = new Ajv({ strict: "log" });
      addFormats(ajvInstance);
      ajv.current = ajvInstance;
    }
  }, []);

  // Fetch and Compile Schema
  useEffect(() => {
    const schemaName = "dataproduct_schema_v0_0_1";
    const fetchAndCompileSchema = async () => {
      if (!isOpen || dataProductSchema || !ajv.current) return; // Only fetch if open and not already loaded
      setIsSchemaLoading(true);
      setValidationStatusMessage("Loading schema...");
      setSchemaValidationErrors(null);
      try {
        const response = await get<object>(`/api/metadata/schemas/${schemaName}`);
        const schema = checkApiResponse(response, 'Schema Fetch');
        setDataProductSchema(schema);
        const validate = ajv.current.compile(schema);
        setSchemaValidator(() => validate);
        setValidationStatusMessage("Schema ready.");
      } catch (err: any) {
        console.error("Error fetching or compiling schema:", err);
        setValidationStatusMessage(`Error loading schema: ${err.message}`);
        toast({ title: 'Schema Error', description: `Could not load schema: ${err.message}`, variant: 'destructive' });
      } finally {
        setIsSchemaLoading(false);
      }
    };
    fetchAndCompileSchema();
  }, [isOpen, get, dataProductSchema, toast]); // Add toast to dependencies

  // Effect to load product data when dialog opens in edit mode
  useEffect(() => {
    const loadProductForEdit = async () => {
      // Fetch user projects when dialog opens
      if (isOpen) {
        fetchUserProjects();
      }
      
      if (isOpen && isEditMode && initialProduct?.id) {
        setIsLoadingProduct(true);
        setFormError(null);
        setActiveTab('ui'); // Reset to UI tab on load
        setValidationStatusMessage(null); // Reset validation
        setSchemaValidationErrors(null);
        try {
          const response = await get<DataProduct>(`/api/data-products/${initialProduct.id}`);
          const productData = checkApiResponse(response, `Fetch product ${initialProduct.id}`);
          
          const formData = { 
            ...createDefaultProduct(),
            ...productData,
            inputPorts: productData.inputPorts || [],
            outputPorts: productData.outputPorts || [],
            tags: productData.tags || [],
            links: productData.links || {}, 
            custom: productData.custom || {},
            info: productData.info || { title: "", owner: "" },
          };
          delete formData.created_at; // Keep this for optional field
          // delete formData.updated_at; // REMOVE: updated_at is required in type

          reset(formData); 

          // Populate state arrays for custom editors *after* reset
          setLinksArray(linksObjectToArray(formData.links));
          setCustomArray(objectToArray(formData.custom));

          // Initialize JSON editor state
          const cleanedDataForJson = cleanEmptyOptionalStrings(formData);
          setJsonString(JSON.stringify(cleanedDataForJson, null, 2));
          setIsJsonValid(true);
          // Validate immediately if schema is ready
          if (schemaValidator) {
              validateProductObject(cleanedDataForJson);
          }

        } catch (err: any) {
          console.error('Error loading product for editing:', err);
          setFormError(`Failed to load product details: ${err.message}`);
          toast({ title: "Error Loading Data", description: `Could not fetch details. ${err.message}`, variant: "destructive" });
          // Maybe close the dialog if loading fails critically?
          // onOpenChange(false);
        } finally {
          setIsLoadingProduct(false);
        }
      } else if (isOpen && !isEditMode) {
          // Reset form for CREATE mode when dialog opens
          const defaultValues = createDefaultProduct();
          reset(defaultValues); 
          setLinksArray(linksObjectToArray(defaultValues.links));
          setCustomArray(objectToArray(defaultValues.custom));
          setJsonString(JSON.stringify(cleanEmptyOptionalStrings(defaultValues), null, 2));
          setIsJsonValid(true);
          setFormError(null);
          setActiveTab('ui');
          setValidationStatusMessage(null);
          setSchemaValidationErrors(null);
          setIsLoadingProduct(false); // Not loading in create mode
      }
    };

    loadProductForEdit();

  }, [isOpen, isEditMode, initialProduct, get, reset, toast, schemaValidator, fetchUserProjects]); // Dependencies

  // Set default project when creating new product and currentProject is available
  useEffect(() => {
    if (isOpen && !isEditMode && currentProject?.id) {
      const currentProjectId = getValues('project_id');
      if (!currentProjectId) {
        setValue('project_id', currentProject.id, { shouldDirty: false });
      }
    }
  }, [isOpen, isEditMode, currentProject, setValue, getValues]);

  // --- Event Handlers --- 

  // Debounced Table Search
  const debouncedTableSearch = useRef(
    debounce(async (query: string) => {
      if (!query) {
        setTableSearchResults([]); 
        setIsSearchingTables(false);
        return;
      }
      setIsSearchingTables(true);
      try {
        const response = await get<MetastoreTableInfo[]>(`/api/metadata/tables/search?query=${encodeURIComponent(query)}&limit=50`);
        setTableSearchResults(checkApiResponse(response, 'Table Search') || []);
      } catch (err) { // Error already handled by checkApiResponse, just log
        console.error("Error searching tables:", err);
        setTableSearchResults([]);
      } finally {
        setIsSearchingTables(false);
      }
    }, 300)
  ).current;

  // Initial Table Fetch for Combobox
  const fetchInitialTables = async () => {
      setIsSearchingTables(true);
      try {
        const response = await get<MetastoreTableInfo[]>('/api/metadata/tables/initial?limit=20');
        setTableSearchResults(checkApiResponse(response, 'Initial Tables Fetch') || []);
      } catch (err) {
        console.error("Error fetching initial tables:", err);
        setTableSearchResults([]);
      } finally {
         setIsSearchingTables(false);
      }
  };

  // Combobox Input Change
  const handleTableSearchInputChange = (query: string) => {
    setTableSearchQuery(query);
    debouncedTableSearch(query);
  };
  
  // Combobox Open Change
  const handleComboboxOpenChange = (open: boolean, fieldId: string) => {
      setIsComboboxOpen(prev => ({ ...prev, [fieldId]: open }));
      if (open) {
          setTableSearchQuery("");
          fetchInitialTables(); 
      }
  };

  // Validate product object against schema
  const validateProductObject = (data: any): boolean => {
    if (!schemaValidator) {
      setValidationStatusMessage("Schema not ready.");
      setIsJsonValid(false); // Assume invalid if no validator
      setSchemaValidationErrors(null);
      return false;
    }
    // Clean before validation? Maybe not, spec might require certain empty fields?
    // Let's validate the potentially non-cleaned object first, then clean before submit.
    // const cleanedData = cleanEmptyOptionalStrings(data);

    const isValid = schemaValidator(data);
    if (isValid) {
       setValidationStatusMessage("Schema Valid");
       setIsJsonValid(true);
       setSchemaValidationErrors(null);
    } else {
       setIsJsonValid(false);
       const errors = schemaValidator.errors ?? [];
       setSchemaValidationErrors(errors);
       const errorCount = errors.length;
       setValidationStatusMessage(`${errorCount} schema validation error(s)`); 
    }
    return isValid;
  };

  // Restore original JSON Text Area Change handler
  const handleJsonChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const currentJson = event.target.value;
    setJsonString(currentJson);
    // Reset validation status until parsing/validation occurs
    setValidationStatusMessage(null); 
    setSchemaValidationErrors(null); 
    setJsonParseError(null); // Clear previous parse errors

    try {
      const parsedData = JSON.parse(currentJson);
      setIsJsonValid(true); // Temporarily set valid after parsing
      validateProductObject(parsedData); // Now validate against schema
    } catch (error: any) {
      setIsJsonValid(false);
      setJsonParseError(error.message); // Set specific parse error
      setValidationStatusMessage("Invalid JSON syntax");
      setSchemaValidationErrors(null); // Clear schema errors if syntax is wrong
    }
  };

  // Tab Change
  const handleTabChange = (newTab: 'ui' | 'json') => {
    if (newTab === activeTab) return;
    setFormError(null); // Clear form errors on tab switch

    if (activeTab === 'ui' && newTab === 'json') {
      // Sync from UI (RHF) to JSON state
      handleSubmit((formDataFromRHF) => {
         try {
           const currentMainLinksObject = linksArrayToObject(linksArray); 
           const currentMainCustomObject = arrayToObject(customArray);

           const dataForJsonRaw = {
             ...formDataFromRHF, 
             links: currentMainLinksObject, 
             custom: currentMainCustomObject,
           };
           // Clean before displaying in JSON editor for better readability
           const cleanedDataForJson = cleanEmptyOptionalStrings(dataForJsonRaw);

           const formattedJson = JSON.stringify(cleanedDataForJson, null, 2);
           setJsonString(formattedJson);
           // Re-validate the generated JSON
           setIsJsonValid(true); // Assume valid structure initially
           setJsonParseError(null);
           validateProductObject(cleanedDataForJson); 
           setActiveTab('json');
         } catch (err: any) {
           console.error("Error preparing JSON from UI state:", err);
           setJsonParseError("Failed to serialize UI state to JSON.");
           toast({ title: "Sync Error", description: "Could not sync UI state to JSON editor.", variant: "destructive" });
         }
      })(); // Immediately invoke handleSubmit

    } else if (activeTab === 'json' && newTab === 'ui') {
       // Sync from JSON state to UI (RHF)
       try {
         const parsedData = JSON.parse(jsonString);
         setIsJsonValid(true); // Assume valid parse
         setJsonParseError(null);
         
         // Validate before attempting to reset the form
         if (!validateProductObject(parsedData)) {
             toast({ 
                 title: "Invalid JSON", 
                 description: "Cannot switch to UI editor. Please fix schema validation errors first.",
                 variant: "destructive"
             });
             return; // Prevent switching tabs
         }
         
         // --- Improved Compare before resetting --- 
         const currentValues = getValues();

         // Prepare parsedData for comparison (apply defaults, ensure arrays)
         const preparedParsedData = {
             ...createDefaultProduct(),
             ...parsedData,
             inputPorts: parsedData.inputPorts || [],
             outputPorts: parsedData.outputPorts || [],
             tags: parsedData.tags || [],
             links: parsedData.links || {}, 
             custom: parsedData.custom || {}, 
             info: parsedData.info || { title: "", owner: "" },
         };

         // Prepare currentValues for comparison (apply defaults, ensure arrays)
         const preparedCurrentValues = {
             ...createDefaultProduct(),
             ...currentValues,
             inputPorts: currentValues.inputPorts || [],
             outputPorts: currentValues.outputPorts || [],
             tags: currentValues.tags || [],
             links: currentValues.links || {}, // RHF should hold the object synced from linksArray
             custom: currentValues.custom || {}, // RHF should hold the object synced from customArray
             info: currentValues.info || { title: "", owner: "" },
         };

         // Clean both before comparison
         const cleanedParsed = cleanEmptyOptionalStrings(preparedParsedData);
         const cleanedCurrent = cleanEmptyOptionalStrings(preparedCurrentValues);

         // Compare using stringify
         const isDifferent = JSON.stringify(cleanedParsed) !== JSON.stringify(cleanedCurrent);

         // Only reset RHF state if data is actually different
         if (isDifferent) {
             // Reset with the raw parsed data
             reset(parsedData);
         } else {
             // Reset with current values, marking form as not dirty
             reset(getValues(), { keepDirty: false }); 
         }
         
         // Always update local state for Links/Custom editors to sync with JSON view
         setLinksArray(linksObjectToArray(parsedData.links));
         setCustomArray(objectToArray(parsedData.custom));
         setActiveTab('ui');

       } catch (error: any) {
          setIsJsonValid(false);
          setJsonParseError(`Invalid JSON: ${error.message}`);
          setValidationStatusMessage("Invalid JSON syntax");
          toast({ title: "Sync Error", description: `Could not parse JSON: ${error.message}`, variant: "destructive" });
       }
    }
  };

  // Actual Submit Logic (called by both UI form and JSON submit button)
  const performSubmit = async (data: DataProduct) => {
    setFormError(null); 
    const productId = initialProduct?.id; // Use initialProduct ID for update check
    const now = new Date().toISOString();

    // Prepare payload: Start with RHF data, add converted arrays, set timestamp
    const payloadRaw: DataProduct = {
        ...data,
        links: linksArrayToObject(linksArray),
        custom: arrayToObject(customArray),
        updated_at: now, 
    };

    // Clean the final payload right before sending
    const payload = cleanEmptyOptionalStrings(payloadRaw);

    // Re-validate the cleaned payload before submitting
    if (!validateProductObject(payload)) {
        setFormError("Data failed schema validation. Please check the highlighted fields or the JSON editor.");
        toast({ title: "Validation Error", description: "Please fix validation errors before saving.", variant: "destructive" });
        setActiveTab('json'); // Switch to JSON tab to show errors easily
        // Update jsonString state to reflect the *cleaned* payload causing validation errors
        setJsonString(JSON.stringify(payload, null, 2)); 
        return; // Stop submission
    }

    try {
        let response;
        let result: DataProduct;

        if (isEditMode && productId) {
            // --- UPDATE --- 
            payload.id = productId; // Ensure ID is in the payload for PUT
            response = await put<DataProduct>(`/api/data-products/${productId}`, payload);
            result = checkApiResponse(response, 'Update Product');
        } else {
            // --- CREATE --- 
            // Assign ID if not present (backend might also do this)
            if (!payload.id) {
                payload.id = crypto.randomUUID(); 
            }
            // Add created_at for new records (backend might override)
            payload.created_at = now;
            response = await post<DataProduct>('/api/data-products', payload);
            result = checkApiResponse(response, 'Create Product');
        }

        toast({ title: 'Success', description: `Data product ${isEditMode ? 'updated' : 'created'}.` });
        onSubmitSuccess(result); // Call the success callback from parent
        onOpenChange(false); // Close dialog on success

    } catch (err: any) {
        console.error('Error submitting product form:', err);
        const errorMsg = err.message || 'An unexpected error occurred.';
        setFormError(errorMsg);
        toast({ title: 'Save Error', description: errorMsg, variant: 'destructive' });
    }
  };

  // UI Form Submit Handler
  const onFormSubmit: SubmitHandler<DataProduct> = (data) => {
    performSubmit(data); // Pass RHF data to the actual submit logic
  };

  // JSON Submit Handler
  const submitFromJson = async () => {
    setFormError(null);
    setJsonParseError(null);

    try {
      const parsedData = JSON.parse(jsonString);
      // Validate structure first
      if (!validateProductObject(parsedData)) {
        toast({ title: "Validation Error", description: "JSON data failed schema validation. Cannot save.", variant: "destructive" });
        return; 
      }
      // Pass the parsed and validated JSON data to the submit logic
      await performSubmit(parsedData); 

    } catch (error: any) {
      console.error("Error submitting JSON:", error);
      setIsJsonValid(false);
      const errorMsg = `Invalid JSON: ${error.message}`;
      setJsonParseError(errorMsg);
      setFormError(errorMsg); // Show error in form area too
      toast({ title: "Save Error", description: errorMsg, variant: "destructive" });
    }
  };

  // Handle closing the dialog
  const handleCloseDialog = (open: boolean) => {
     if (!open) {
       if (isDirty) { // Check if form has unsaved changes
          if (!confirm('You have unsaved changes. Are you sure you want to close?')) {
             return; // Prevent closing
          }
       }
       // Reset form state only when actually closing
       reset(createDefaultProduct()); 
       setLinksArray([]);
       setCustomArray([]);
       setJsonString('');
       setIsJsonValid(true);
       setJsonParseError(null);
       setFormError(null);
       setValidationStatusMessage(null);
       setSchemaValidationErrors(null);
       setActiveTab('ui');
       setIsLoadingProduct(false);
       setDataProductSchema(null); // Allow schema refetch next time
       setSchemaValidator(null);
     }
     onOpenChange(open); // Call parent handler
  };

  // --- Render Logic --- 
  if (!isOpen) return null; // Don't render anything if not open

  return (
    <Dialog open={isOpen} onOpenChange={handleCloseDialog}> 
      <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? 'Edit Data Product' : 'Create Data Product'}
          </DialogTitle>
          <DialogDescription>
              Fill in the details for the data product. Use the tabs to switch between UI and JSON editors.
          </DialogDescription>
        </DialogHeader>
        
        {isLoadingProduct ? (
            <div className="flex justify-center items-center h-[60vh]">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p className="ml-2">Loading product details...</p>
            </div>
         ) : (
            <Tabs 
              value={activeTab} 
              onValueChange={(value) => handleTabChange(value as 'ui' | 'json')} // Cast value here
              className="flex-grow flex flex-col min-h-0"
            > 
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="ui" disabled={isSubmitting}>UI Editor</TabsTrigger>
                  <TabsTrigger value="json" disabled={isSubmitting}>JSON Editor</TabsTrigger>
                </TabsList>

                {/* UI Editor Tab */} 
                <TabsContent value="ui" className="mt-4 flex-grow min-h-0 flex flex-col"> 
                    {/* Inner scrollable div */}
                    <div className="flex-grow overflow-y-auto pr-4">
                      <form id="data-product-ui-form" onSubmit={handleSubmit(onFormSubmit)} className="space-y-4 pb-4">
                          {/* ID and Spec Version */} 
                          <div className="grid grid-cols-2 gap-4">
                              <div>
                                <Label htmlFor="productId">ID (unique identifier)</Label>
                                <Input 
                                  id="productId" 
                                  {...register("id")} 
                                  placeholder={isEditMode ? "(System ID)" : "e.g., my-unique-product (optional)"}
                                  disabled={isEditMode} // Disable ID editing for existing products
                                  className={isEditMode ? "bg-muted" : ""}
                                />
                                {errors.id && <p className="text-sm text-red-600 mt-1">{errors.id.message}</p>}
                              </div>
                              {/* Version Field */}
                              {/* Make Version editable only on create */}
                              <div>
                                <Label htmlFor="version">Version</Label>
                                <Input 
                                  id="version" 
                                  {...register("version")} 
                                  readOnly={isEditMode}
                                  disabled={isEditMode || isSubmitting}
                                  className={isEditMode ? "bg-muted cursor-not-allowed" : ""}
                                  placeholder="e.g., 1.0.0"
                                />
                                {errors.version && <p className="text-sm text-red-600 mt-1">{errors.version.message}</p>}
                              </div>
                          </div>
                          
                          {/* Info Card */} 
                          <Card>
                            <CardHeader>
                              <CardTitle>Info</CardTitle>
                              <CardDescription>Basic information about the data product.</CardDescription>
                            </CardHeader>
                            <CardContent className="space-y-4">
                              <div className="grid grid-cols-2 gap-4">
                                  <div>
                                    <Label htmlFor="info.title">Title *</Label>
                                    <Input id="info.title" {...register("info.title", { required: "Title is required" })} />
                                    {errors.info?.title && <p className="text-sm text-red-600 mt-1">{errors.info.title.message}</p>}
                                  </div>
                                  <div>
                                    <Label htmlFor="info.owner">Owner *</Label>
                                      {/* TODO: Consider using a Select if owners prop is populated and meant for dropdown */} 
                                      <Input 
                                        id="info.owner" 
                                        {...register("info.owner", { required: "Owner is required" })} 
                                      />
                                    {errors.info?.owner && <p className="text-sm text-red-600 mt-1">{errors.info.owner.message}</p>}
                                  </div>
                              </div>
                              {/* Product Type Field */} 
                              <div>
                                  <Label htmlFor="productType">Product Type *</Label>
                                  <Controller
                                      name="productType"
                                      control={control}
                                      rules={{ required: "Product Type is required" }}
                                      render={({ field }) => (
                                          <Select 
                                              onValueChange={(value) => field.onChange(value === '' ? undefined : value)} 
                                              value={field.value || ""}
                                              disabled={isSubmitting}
                                          >
                                              <SelectTrigger><SelectValue placeholder="Select product type" /></SelectTrigger>
                                              <SelectContent>
                                                  {productTypes.map(pt => <SelectItem key={pt} value={pt}>{pt}</SelectItem>)}
                                              </SelectContent>
                                          </Select>
                                      )}
                                  />
                                  {errors.productType && <p className="text-sm text-red-600 mt-1">{errors.productType.message}</p>}
                              </div>
                              {/* Project Field */}
                              <div>
                                  <Label htmlFor="project_id">Project</Label>
                                  <Controller
                                      name="project_id"
                                      control={control}
                                      render={({ field }) => (
                                          <Select 
                                              onValueChange={(value) => field.onChange(value === '_none' ? undefined : value)} 
                                              value={field.value || "_none"}
                                              disabled={isSubmitting || projectsLoading}
                                          >
                                              <SelectTrigger><SelectValue placeholder="Select project (optional)" /></SelectTrigger>
                                              <SelectContent>
                                                  <SelectItem value="_none">None</SelectItem>
                                                  {availableProjects.map(project => (
                                                      <SelectItem key={project.id} value={project.id}>
                                                          {project.name} ({project.team_count} teams)
                                                      </SelectItem>
                                                  ))}
                                              </SelectContent>
                                          </Select>
                                      )}
                                  />
                                  <p className="text-xs text-muted-foreground mt-1">
                                      You can only select projects you are a member of
                                  </p>
                              </div>
                              <div className="grid grid-cols-2 gap-4">
                                  <div>
                                    <Label htmlFor="info.domain">Domain</Label>
                                    <Input id="info.domain" {...register("info.domain")} />
                                    {errors.info?.domain && <p className="text-sm text-red-600 mt-1">{errors.info.domain.message}</p>}
                                  </div>
                                  <div>
                                    <Label htmlFor="info.archetype">Archetype</Label>
                                    <Controller
                                      name="info.archetype"
                                      control={control}
                                      render={({ field }) => (
                                        <Select onValueChange={(value) => field.onChange(value === '' ? undefined : value)} value={field.value || ""}>
                                          <SelectTrigger><SelectValue placeholder="Select archetype" /></SelectTrigger>
                                          <SelectContent>
                                            {/* Removed archetypes prop from here */}
                                          </SelectContent>
                                        </Select>
                                      )}
                                    />
                                    {errors.info?.archetype && <p className="text-sm text-red-600 mt-1">{errors.info.archetype.message}</p>}
                                  </div>
                              </div>
                              <div>
                                <Label htmlFor="info.description">Description</Label>
                                <Textarea id="info.description" {...register("info.description")} />
                                {errors.info?.description && <p className="text-sm text-red-600 mt-1">{errors.info.description.message}</p>}
                              </div>
                              <div>
                                  <Label htmlFor="info.status">Status</Label>
                                  <Controller
                                    name="info.status"
                                    control={control}
                                    render={({ field }) => (
                                      <Select onValueChange={(value) => field.onChange(value === '' ? undefined : value)} value={field.value || ""}>
                                        <SelectTrigger><SelectValue placeholder="Select status" /></SelectTrigger>
                                        <SelectContent>
                                          {statuses.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                                        </SelectContent>
                                      </Select>
                                    )}
                                  />
                                  {errors.info?.status && <p className="text-sm text-red-600 mt-1">{errors.info.status.message}</p>}
                              </div>
                            </CardContent>
                          </Card>

                          {/* Input Ports Card */} 
                          <Card>
                              <CardHeader>
                                <CardTitle>Input Ports</CardTitle>
                                <CardDescription>Sources feeding this product. Select tables from the metastore.</CardDescription>
                              </CardHeader>
                              <CardContent className="space-y-4">
                                {inputPortFields.map((field, index) => (
                                  <Card key={field.id} className="p-4 pt-8 relative"> 
                                      <Button 
                                          variant="ghost" size="icon" 
                                          className="absolute top-1 right-1 h-6 w-6 text-destructive" 
                                          onClick={() => removeInputPort(index)} type="button" title="Remove Input Port">
                                          <X className="h-4 w-4" />
                                      </Button>
                                      <div className="space-y-3">
                                        <div className="grid grid-cols-2 gap-4">
                                          <div>
                                            <Label htmlFor={`inputPorts.${index}.id`}>Port ID *</Label>
                                            <Input {...register(`inputPorts.${index}.id`, { required: "Port ID is required" })} />
                                            {errors.inputPorts?.[index]?.id && <p className="text-sm text-red-600 mt-1">{errors.inputPorts[index].id?.message}</p>}
                                          </div>
                                          <div>
                                              <Label htmlFor={`inputPorts.${index}.name`}>Port Name *</Label>
                                              <Input {...register(`inputPorts.${index}.name`, { required: "Port Name is required" })} />
                                              {errors.inputPorts?.[index]?.name && <p className="text-sm text-red-600 mt-1">{errors.inputPorts[index].name?.message}</p>}
                                          </div>
                                        </div>
                                        <div>
                                          <Label htmlFor={`inputPorts.${index}.sourceSystemId`}>Source Table (Metastore) *</Label>
                                          <Controller
                                              name={`inputPorts.${index}.sourceSystemId`}
                                              control={control}
                                              rules={{ required: "Source Table is required" }}
                                              render={({ field: controllerField }) => (
                                                <Popover open={isComboboxOpen[field.id] ?? false} onOpenChange={(open) => handleComboboxOpenChange(open, field.id)}>
                                                  <PopoverTrigger asChild>
                                                      <Button
                                                        variant="outline"
                                                        role="combobox"
                                                        aria-expanded={isComboboxOpen[field.id] ?? false}
                                                        className="w-full justify-between font-normal"
                                                      >
                                                        {controllerField.value || "Select source table..."}
                                                        <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                                                      </Button>
                                                    </PopoverTrigger>
                                                    <PopoverContent className="w-[--radix-popover-trigger-width] max-h-[--radix-popover-content-available-height] p-0">
                                                      <Command shouldFilter={false}>
                                                          <CommandInput 
                                                            placeholder="Search metastore tables..."
                                                            value={tableSearchQuery} 
                                                            onValueChange={handleTableSearchInputChange}
                                                          />
                                                          <CommandList>
                                                            <CommandEmpty>
                                                                {isSearchingTables ? "Searching..." : "No tables found."}
                                                            </CommandEmpty>
                                                            <CommandGroup>
                                                              {tableSearchResults.map((table) => (
                                                                  <CommandItem
                                                                    key={table.full_name}
                                                                    value={table.full_name} 
                                                                    onSelect={(currentValue) => {
                                                                        controllerField.onChange(currentValue === controllerField.value ? "" : currentValue);
                                                                        handleComboboxOpenChange(false, field.id);
                                                                    }}
                                                                  >
                                                                    <Check
                                                                        className={cn("mr-2 h-4 w-4", controllerField.value === table.full_name ? "opacity-100" : "opacity-0")}
                                                                      />
                                                                      {table.full_name}
                                                                  </CommandItem>
                                                                ))}
                                                            </CommandGroup>
                                                          </CommandList>
                                                        </Command>
                                                    </PopoverContent>
                                                  </Popover>
                                              )}
                                            />
                                            {errors.inputPorts?.[index]?.sourceSystemId && <p className="text-sm text-red-600 mt-1">{errors.inputPorts[index].sourceSystemId?.message}</p>}
                                            <input type="hidden" {...register(`inputPorts.${index}.type`, { value: 'table' })} />
                                        </div>
                                        <div>
                                            <Label htmlFor={`inputPorts.${index}.description`}>Description</Label>
                                            <Textarea {...register(`inputPorts.${index}.description`)} />
                                        </div>
                                        <div>
                                          <Label htmlFor={`inputPorts.${index}.tags`}>Tags</Label>
                                          <Controller
                                              name={`inputPorts.${index}.tags`}
                                              control={control}
                                              render={({ field }) => (
                                                <TagSelector
                                                    value={field.value || []}
                                                    onChange={field.onChange}
                                                    placeholder="Search and select tags for this input port..."
                                                    allowCreate={true}
                                                />
                                              )}
                                          />
                                        </div>
                                        {/* Port Links/Custom Editor */}
                                        <PortMetadataEditor 
                                            control={control} 
                                            register={register} 
                                            getValues={getValues}
                                            setValue={setValue}
                                            portIndex={index} 
                                            portType="inputPorts" 
                                        />
                                      </div>
                                  </Card>
                                ))}
                                <Button 
                                    type="button" variant="outline" 
                                    onClick={() => appendInputPort({ 
                                        id: `input-${inputPortFields.length + 1}`,
                                        name: 'New Input Port',
                                        version: '1.0.0', // Required ODPS field
                                        contractId: '', // Required ODPS field
                                        sourceSystemId: '',
                                        type: 'table', 
                                        links: {}, custom: {}, tags: []
                                    })}
                                  > 
                                    <Plus className="mr-2 h-4 w-4"/> Add Input Port 
                                </Button>
                              </CardContent>
                          </Card>

                          {/* Output Ports Card */} 
                          <Card>
                              <CardHeader>
                                <CardTitle>Output Ports</CardTitle>
                                <CardDescription>Outputs provided by this data product.</CardDescription>
                              </CardHeader>
                              <CardContent className="space-y-4">
                                {outputPortFields.map((field, index) => (
                                  <Card key={field.id} className="p-4 pt-8 relative">
                                      <Button variant="ghost" size="icon" className="absolute top-1 right-1 h-6 w-6 text-destructive" onClick={() => removeOutputPort(index)} type="button" title="Remove Output Port">
                                         <X className="h-4 w-4" />
                                       </Button>
                                       <div className="space-y-3">
                                          <div className="grid grid-cols-2 gap-4">
                                            <div>
                                              <Label htmlFor={`outputPorts.${index}.id`}>Port ID *</Label>
                                              <Input {...register(`outputPorts.${index}.id`, { required: "Port ID is required" })} />
                                              {errors.outputPorts?.[index]?.id && <p className="text-sm text-red-600 mt-1">{errors.outputPorts[index].id?.message}</p>}
                                            </div>
                                            <div>
                                                <Label htmlFor={`outputPorts.${index}.name`}>Port Name *</Label>
                                                <Input {...register(`outputPorts.${index}.name`, { required: "Port Name is required" })} />
                                                {errors.outputPorts?.[index]?.name && <p className="text-sm text-red-600 mt-1">{errors.outputPorts[index].name?.message}</p>}
                                            </div>
                                          </div>
                                          <div>
                                              <Label htmlFor={`outputPorts.${index}.description`}>Description</Label>
                                              <Textarea {...register(`outputPorts.${index}.description`)} />
                                          </div>
                                          <div>
                                            <Label htmlFor={`outputPorts.${index}.tags`}>Tags</Label>
                                            <Controller
                                                name={`outputPorts.${index}.tags`}
                                                control={control}
                                                render={({ field }) => (
                                                  <TagSelector
                                                      value={field.value || []}
                                                      onChange={field.onChange}
                                                      placeholder="Search and select tags for this output port..."
                                                      allowCreate={true}
                                                  />
                                                )}
                                            />
                                          </div>
                                          {/* Port Links/Custom Editor */}
                                          <PortMetadataEditor 
                                              control={control} 
                                              register={register} 
                                              getValues={getValues}
                                              setValue={setValue}
                                              portIndex={index} 
                                              portType="outputPorts" 
                                          />
                                       </div>
                                  </Card>
                                ))}
                                <Button 
                                  type="button" variant="outline" 
                                  onClick={() => appendOutputPort({ 
                                      id: `output-${outputPortFields.length + 1}`,
                                      name: 'New Output Port',
                                      version: '1.0.0', // Required ODPS field
                                      description: '',
                                      type: 'table', 
                                      links: {}, custom: {}, tags: [] 
                                   })}
                                > 
                                  <Plus className="mr-2 h-4 w-4"/> Add Output Port 
                                </Button>
                              </CardContent>
                          </Card>

                          {/* Main Tags Card */} 
                          <Card>
                            <CardHeader>
                              <CardTitle>Tags</CardTitle>
                              <CardDescription>Add relevant tags (comma-separated).</CardDescription>
                            </CardHeader>
                            <CardContent>
                                <Controller
                                    name="tags"
                                    control={control}
                                    render={({ field }) => (
                                      <TagSelector
                                          value={field.value || []}
                                          onChange={field.onChange}
                                          placeholder="Search and select tags for this data product..."
                                          allowCreate={true}
                                      />
                                    )}
                                />
                            </CardContent>
                          </Card>

                          {/* Main Links Card */} 
                          <Card>
                              <CardHeader>
                                  <CardTitle>Links</CardTitle>
                                  <CardDescription>Add relevant links (e.g., documentation, dashboards).</CardDescription>
                              </CardHeader>
                              <CardContent className="space-y-3">
                                  {linksArray.map((link, index) => (
                                    <div key={`main-link-${index}`} className="flex items-center gap-2">
                                        <Input 
                                            placeholder="Link Key (e.g., docs)" 
                                            value={link.key}
                                            onChange={(e) => {
                                                const newLinks = [...linksArray];
                                                newLinks[index].key = e.target.value;
                                                setLinksArray(newLinks);
                                            }}
                                            className="flex-1"
                                        />
                                        <Input 
                                            placeholder="URL *" 
                                            value={link.url}
                                            onChange={(e) => {
                                              const newLinks = [...linksArray];
                                              newLinks[index].url = e.target.value;
                                              setLinksArray(newLinks);
                                            }}
                                            className="flex-1"
                                        />
                                        <Input 
                                            placeholder="Description" 
                                            value={link.description}
                                            onChange={(e) => {
                                              const newLinks = [...linksArray];
                                              newLinks[index].description = e.target.value;
                                              setLinksArray(newLinks);
                                            }}
                                            className="flex-1"
                                        />
                                        <Button type="button" variant="ghost" size="icon" onClick={() => setLinksArray(linksArray.filter((_, i) => i !== index))} className="text-destructive" title="Remove Link">
                                            <X className="h-4 w-4" />
                                        </Button>
                                    </div>
                                  ))}
                                  <Button type="button" variant="outline" onClick={() => setLinksArray([...linksArray, { key: '', url: '', description: '' }])}>
                                    <Plus className="mr-2 h-4 w-4"/> Add Link
                                  </Button>
                              </CardContent>
                          </Card>
                          
                          {/* Main Custom Properties Card */} 
                          <Card>
                            <CardHeader>
                                <CardTitle>Custom Properties</CardTitle>
                                <CardDescription>Add custom key-value metadata.</CardDescription>
                            </CardHeader>
                            <CardContent className="space-y-3">
                                  {customArray.map((custom, index) => (
                                    <div key={`main-custom-${index}`} className="flex items-center gap-2">
                                        <Input 
                                            placeholder="Property Key" 
                                            value={custom.key}
                                            onChange={(e) => {
                                                const newCustom = [...customArray];
                                                newCustom[index].key = e.target.value;
                                                setCustomArray(newCustom);
                                            }}
                                            className="flex-1"
                                        />
                                        <Input 
                                            placeholder="Property Value (string)" 
                                            value={custom.value} // Treat as string in UI
                                            onChange={(e) => {
                                              const newCustom = [...customArray];
                                              newCustom[index].value = e.target.value;
                                              setCustomArray(newCustom);
                                            }}
                                            className="flex-1"
                                        />
                                        <Button type="button" variant="ghost" size="icon" onClick={() => setCustomArray(customArray.filter((_, i) => i !== index))} className="text-destructive" title="Remove Property">
                                            <X className="h-4 w-4" />
                                        </Button>
                                    </div>
                                  ))}
                                  <Button type="button" variant="outline" onClick={() => setCustomArray([...customArray, { key: '', value: '' }])}>
                                    <Plus className="mr-2 h-4 w-4"/> Add Custom Property
                                  </Button>
                            </CardContent>
                          </Card>
                      </form> 
                    </div> {/* End inner scrollable div */}

                  {/* Error Display - Outside scrollable div, inside TabsContent */} 
                  {formError && (
                      <div className="px-6 pt-2 pb-0"> {/* Add padding */} 
                        <Alert variant="destructive">
                          <AlertCircle className="h-4 w-4" />
                          <AlertDescription>{formError}</AlertDescription>
                        </Alert>
                      </div>
                    )}
                    
                  {/* UI Form Footer - Outside scrollable div, inside TabsContent */} 
                  <DialogFooter className="px-6 pb-6 pt-4 border-t">
                    <Button type="button" variant="outline" onClick={() => handleCloseDialog(false)} disabled={isSubmitting}>Cancel</Button>
                    <Button 
                      type="submit" 
                      form="data-product-ui-form" 
                      disabled={isSubmitting || isLoadingProduct}
                    >
                      {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin"/> : null}
                      {isSubmitting ? "Saving..." : (isEditMode ? 'Update Product' : 'Create Product')}
                    </Button>
                  </DialogFooter>
                </TabsContent>

                {/* JSON Editor Tab */} 
                {/* Restore layout: TabsContent scrolls */} 
                <TabsContent value="json" className="mt-4 flex-grow min-h-0 overflow-y-auto pr-4 space-y-2">
                    {/* Remove temporary style tag */} 
                    {/* <style>{`
                        .json-editor-wrapper pre {
                            overflow: auto !important;
                            max-height: 100%; 
                        }
                    `}</style> */} 
                    {/* Remove inner wrapper div */}
                    {/* <div className="pr-4 space-y-2 flex flex-col json-editor-wrapper"> */} 
                      <Label htmlFor="jsonEditor">JSON Payload</Label>
                      {/* Restore Textarea */}
                      <Textarea
                          id="jsonEditor"
                          value={jsonString}
                          onChange={handleJsonChange} // Use original handler
                          disabled={isSubmitting || isLoadingProduct}
                          className={cn(
                              // Standard textarea styling, fixed height
                              "font-mono text-sm h-[400px] resize-none w-full", 
                              (!isJsonValid || jsonParseError) && "border-destructive focus-visible:ring-destructive"
                          )}
                          placeholder='Enter or edit the Data Product JSON...'
                        />
                       {/* Status/Error Display Area */} 
                       <div className="text-sm min-h-[40px]"> 
                          {jsonParseError ? (
                              <p className="text-destructive">Syntax Error: {jsonParseError}</p>
                          ) : validationStatusMessage && (
                              <p className={cn(isJsonValid ? "text-green-600" : "text-destructive")}>
                                Validation Status: {validationStatusMessage}
                              </p>
                          )}
                       </div>
                       {/* Detailed Errors Accordion */} 
                       {!isJsonValid && !jsonParseError && schemaValidationErrors && schemaValidationErrors.length > 0 && (
                           <Accordion type="single" collapsible className="w-full border-t pt-2 pb-2"> {/* Add pb-2 for spacing before footer */} 
                             <AccordionItem value="item-1" className="border-b-0">
                               <AccordionTrigger className="text-sm text-destructive hover:no-underline py-1">
                                   Show {schemaValidationErrors.length} validation details
                               </AccordionTrigger>
                               <AccordionContent>
                                 <ScrollArea className="max-h-[150px] w-full rounded-md border bg-muted">
                                    <pre className="text-xs p-2 text-destructive whitespace-pre-wrap break-words">
                                        {JSON.stringify(schemaValidationErrors, null, 2)}
                                    </pre>
                                 </ScrollArea>
                               </AccordionContent>
                             </AccordionItem>
                           </Accordion>
                       )}
                    {/* </div> */} {/* Remove closing wrapper div */} 

                    {/* Footer scrolls with content */}
                    <DialogFooter className="px-6 pb-6 pt-4 border-t"> 
                      <Button type="button" variant="outline" onClick={() => handleCloseDialog(false)} disabled={isSubmitting}>Cancel</Button>
                      <Button 
                        type="button" 
                        onClick={submitFromJson}
                        disabled={isSubmitting || isLoadingProduct || !isJsonValid || !!jsonParseError}
                      >
                        {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin"/> : null}
                        {isSubmitting ? "Saving..." : (isEditMode ? 'Update via JSON' : 'Create via JSON')}
                    </Button>
                  </DialogFooter>
                </TabsContent>
            </Tabs>
         )}
      </DialogContent>
    </Dialog>
  );
};

export default DataProductFormDialog;