// business-terms.tsx — thin wrapper retained for backward compatibility.
//
// The former standalone Business Terms (List) view has been folded into the
// unified Explore surface (views/explore.tsx), which now feeds List / Tree /
// Graph from a single fetch + filtered selection. This module re-exports the
// Explore container so existing imports and the legacy `?concept=` redirect
// (handled inside ExploreView) keep working.
export { default } from './explore';
