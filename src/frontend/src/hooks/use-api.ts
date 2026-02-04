import { useState, useCallback } from 'react';

export interface ApiResponse<T> {
  data: T;
  error?: string | null;
}

export const useApi = () => {
  const [loading, setLoading] = useState(false);

  // Use useCallback to ensure function identity is preserved across renders
  const get = useCallback(async <T>(url: string): Promise<ApiResponse<T>> => {
    setLoading(true);
    try {
      const response = await fetch(url);

      // Check for non-OK responses first
      if (!response.ok) {
        let errorBody: any;
        const contentType = response.headers.get('Content-Type');
        try {
          if (contentType?.includes('application/json')) {
            errorBody = await response.json();
          } else {
            errorBody = await response.text();
          }
        } catch (parseError) {
          errorBody = response.statusText; // Fallback
        }
        // Extract meaningful error message (FastAPI detail format or fallback)
        let errorMsg: string;
        if (Array.isArray(errorBody?.detail) && errorBody.detail.length > 0) {
          // FastAPI validation detail array - format all errors
          errorMsg = errorBody.detail.map((err: any) => {
            const loc = Array.isArray(err.loc) ? err.loc.join(' → ') : '';
            return loc ? `${loc}: ${err.msg}` : err.msg;
          }).join('; ');
        } else if (errorBody?.detail) {
          if (typeof errorBody.detail === 'string') {
            errorMsg = errorBody.detail;
          } else if (typeof errorBody.detail === 'object') {
            errorMsg = errorBody.detail.message || JSON.stringify(errorBody.detail);
          } else {
            errorMsg = String(errorBody.detail);
          }
        } else if (typeof errorBody === 'string') {
          errorMsg = errorBody;
        } else {
          errorMsg = JSON.stringify(errorBody) || `HTTP error! status: ${response.status}`;
        }
        console.error("[useApi] GET error response from", url, "(", response.status, "):", errorBody);
        return { data: {} as T, error: errorMsg };
      }

      // Handle successful responses (response.ok is true)
      // Check for empty body for 2xx status codes like 200 or 204
      const contentType = response.headers.get('Content-Type');
      const contentLength = response.headers.get('Content-Length');

      if (response.status === 204 || (contentLength !== null && parseInt(contentLength, 10) === 0)) {
        // For 204 No Content, or explicit zero content length, return default/empty data
        // Assuming T might be an array, an empty array is a sensible default.
        // If T is an object, an empty object might be better.
        // For now, provide {} and let the caller cast or handle.
        return { data: [] as unknown as T }; // Adjust default as needed, e.g., {} as T if T is an object
      }

      // Attempt to parse JSON if content type suggests it
      if (contentType?.includes('application/json')) {
        const data = await response.json();
        return { data };
      } else if (response.ok) { // Handle other 200 OK responses (non-JSON, not 204, not Content-Length 0)
        const textData = await response.text();
        // Attempt to parse as JSON if it looks like it, otherwise return as text.
        // This is a common case for APIs that might return simple strings or lists as text.
        try {
          // A simple heuristic: if it starts with [ or { assume it might be JSON-like text
          if (textData.trim().startsWith('[') || textData.trim().startsWith('{')) {
            return { data: JSON.parse(textData) as T };
          } 
        } catch (e) {
          // If JSON.parse fails, or it doesn't look like JSON, return as plain text wrapped in a way T might expect.
          // This part is tricky as T is generic. For now, we'll log a warning and return it as is,
          // which might require the caller to handle non-object/array types if T expects them.
          console.warn("[useApi] GET response from", url, "was text/plain but not directly parsable as JSON. Returning as raw text. Caller needs to handle this if T expects an object/array. Text:", textData.substring(0,100)); 
          return { data: textData as any as T }; // This cast is risky, caller must be aware
        }
        // If it didn't look like JSON initially, return as text.
        return { data: textData as any as T }; // Cast to T, caller might need to verify type
      }
      
      // Fallback if something unexpected happens, though previous branches should cover response.ok cases.
      // This line should ideally not be reached if response.ok is true.
      console.warn(`[useApi] Unhandled GET response type from ${url}. Status: ${response.status}, Content-Type: ${contentType}`);
      const fallbackData = await response.json(); // Last resort, likely to fail if previous checks didn't catch it.
      return { data: fallbackData };

    } catch (error) {
      console.error("[useApi] GET error from", url, ":", error);
      return { data: {} as T, error: (error as Error).message };
    } finally {
      setLoading(false);
    }
  }, []);

  const post = useCallback(async <T>(url: string, body: any): Promise<ApiResponse<T>> => {
    setLoading(true);
    try {
      let headers: Record<string, string> = {};
      let requestBody: BodyInit;

      if (body instanceof FormData) {
        // Don't set Content-Type for FormData, browser does it with boundary
        requestBody = body;
      } else {
        // Default to JSON
        headers['Content-Type'] = 'application/json';
        requestBody = JSON.stringify(body);
      }

      const response = await fetch(url, {
        method: 'POST',
        headers: headers, // Use dynamically set headers
        body: requestBody, // Use dynamically set body
      });
      
      // --- Primary Check: Response Status --- 
      if (!response.ok) {
          let errorBody: any;
          const contentType = response.headers.get('Content-Type');
          try {
              if (contentType?.includes('application/json')) {
                  errorBody = await response.json();
              } else {
                  errorBody = await response.text();
              }
          } catch (parseError) {
              // If parsing fails, use status text
              errorBody = response.statusText;
          }

          // Extract meaningful error message (FastAPI detail format or fallback)
          let errorMsg: string;
          if (errorBody?.detail?.[0]?.msg) {
            // FastAPI validation detail array
            errorMsg = errorBody.detail[0].msg;
          } else if (errorBody?.detail) {
            // FastAPI detail - could be string or object
            if (typeof errorBody.detail === 'string') {
              errorMsg = errorBody.detail;
            } else if (typeof errorBody.detail === 'object') {
              // Structured error object (e.g., {message: "...", errors: [...]})
              if (Array.isArray(errorBody.detail.errors)) {
                // Handle {errors: [...]} format - errors can be strings or objects
                errorMsg = errorBody.detail.errors.map((e: any) => 
                  typeof e === 'string' ? e : (e.error || e.message || JSON.stringify(e))
                ).join('. ');
              } else if (errorBody.detail.message) {
                errorMsg = errorBody.detail.message;
              } else {
                errorMsg = JSON.stringify(errorBody.detail);
              }
            } else {
              errorMsg = String(errorBody.detail);
            }
          } else if (typeof errorBody === 'string') {
            errorMsg = errorBody;
          } else {
            errorMsg = JSON.stringify(errorBody) || `HTTP error! status: ${response.status}`;
          }

          console.error("[useApi] POST error response from", url, "(", response.status, "):", errorBody);
          return { data: {} as T, error: errorMsg };
      }

      // --- Handle Successful Response (response.ok is true) --- 
      let data: any;
      try {
           // Handle potential empty response body for 2xx status codes
          if (response.headers.get('Content-Length') === '0' || response.status === 204) {
            data = {} as T; // Return empty object for success with no content
          } else if (response.headers.get('Content-Type')?.includes('application/json')){
             data = await response.json();
          } else {
             data = await response.text(); // Handle non-JSON success response
          }
          return { data: data as T };
          
      } catch (parseError) {
           console.error("[useApi] Error parsing successful response from", url, ":", parseError);
           return { data: {} as T, error: `Failed to parse response: ${(parseError as Error).message}` };
      }
      
    } catch (error) {
      // Network errors or errors before fetch response
      console.error("[useApi] Network or other error during POST to", url, ":", error);
      return { data: {} as T, error: (error as Error).message };
    } finally {
      setLoading(false);
    }
  }, []);

  const put = useCallback(async <T>(url: string, body: any): Promise<ApiResponse<T>> => {
    setLoading(true);
    try {
      const response = await fetch(url, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });
      
      // Check for non-OK responses first
      if (!response.ok) {
        let errorBody: any;
        const contentType = response.headers.get('Content-Type');
        try {
          if (contentType?.includes('application/json')) {
            errorBody = await response.json();
          } else {
            errorBody = await response.text();
          }
        } catch (parseError) {
          errorBody = response.statusText; // Fallback
        }

        // Extract meaningful error message (FastAPI detail format or fallback)
        let errorMsg: string;
        if (Array.isArray(errorBody?.detail) && errorBody.detail.length > 0) {
          // FastAPI validation detail array - format all errors
          errorMsg = errorBody.detail.map((err: any) => {
            const loc = Array.isArray(err.loc) ? err.loc.join(' → ') : '';
            return loc ? `${loc}: ${err.msg}` : err.msg;
          }).join('; ');
        } else if (errorBody?.detail) {
          // FastAPI detail - could be string or object
          if (typeof errorBody.detail === 'string') {
            errorMsg = errorBody.detail;
          } else if (typeof errorBody.detail === 'object') {
            // Structured error object (e.g., {message: "...", errors: [...]})
            errorMsg = errorBody.detail.message || JSON.stringify(errorBody.detail);
          } else {
            errorMsg = String(errorBody.detail);
          }
        } else if (typeof errorBody === 'string') {
          errorMsg = errorBody;
        } else {
          errorMsg = JSON.stringify(errorBody) || `HTTP error! status: ${response.status}`;
        }

        console.error("[useApi] PUT error response from", url, "(", response.status, "):", errorBody);
        return { data: {} as T, error: errorMsg };
      }
      
      // Handle successful response
      const data = await response.json();
      return { data };
    } catch (error) {
      console.error("[useApi] PUT error from", url, ":", error);
      return { data: {} as T, error: (error as Error).message };
    } finally {
      setLoading(false);
    }
  }, []);

  const delete_ = useCallback(async <T = unknown>(url: string): Promise<ApiResponse<T>> => {
    setLoading(true);
    let responseData: T = {} as T;
    let errorMsg: string | null = null;
    try {
      const response = await fetch(url, { method: 'DELETE' });

      // Check status and potentially parse error body
      if (!response.ok) {
          let errorBody: any;
          const contentType = response.headers.get('Content-Type');
          try {
              if (contentType?.includes('application/json')) {
                  errorBody = await response.json();
              } else {
                  errorBody = await response.text();
              }
          } catch (parseError) {
              errorBody = response.statusText; // Fallback
          }
          // Extract meaningful error message (FastAPI detail format or fallback)
          if (Array.isArray(errorBody?.detail) && errorBody.detail.length > 0) {
            // FastAPI validation detail array - format all errors
            errorMsg = errorBody.detail.map((err: any) => {
              const loc = Array.isArray(err.loc) ? err.loc.join(' → ') : '';
              return loc ? `${loc}: ${err.msg}` : err.msg;
            }).join('; ');
          } else if (errorBody?.detail) {
            if (typeof errorBody.detail === 'string') {
              errorMsg = errorBody.detail;
            } else if (typeof errorBody.detail === 'object') {
              errorMsg = errorBody.detail.message || JSON.stringify(errorBody.detail);
            } else {
              errorMsg = String(errorBody.detail);
            }
          } else if (typeof errorBody === 'string') {
            errorMsg = errorBody;
          } else {
            errorMsg = JSON.stringify(errorBody) || `HTTP error! status: ${response.status}`;
          }
          console.error("[useApi] DELETE error response from", url, "(", response.status, "):", errorBody);
      } else {
          // Success - check if there's response data (some DELETE endpoints return data)
          const contentType = response.headers.get('Content-Type');
          if (response.status !== 204 && contentType?.includes('application/json')) {
            try {
              responseData = await response.json();
            } catch {
              responseData = {} as T;
            }
          } else {
            responseData = {} as T;
          }
      }

    } catch (error) {
      // Network errors
      errorMsg = (error as Error).message;
      console.error("[useApi] Network or other error during DELETE to", url, ":", error);
    } finally {
      setLoading(false);
    }
    return { data: responseData, error: errorMsg };
  }, []);

  return { get, post, put, delete: delete_, loading };
};