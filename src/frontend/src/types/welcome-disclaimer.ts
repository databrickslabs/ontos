/**
 * Types for the configurable welcome disclaimer (first-open dialog).
 * Mirrors the LLMConsent pattern — browser-localStorage-flag tracked.
 */

export interface WelcomeDisclaimerConfig {
    enabled: boolean;
    text: string;
}

export interface WelcomeDisclaimerState {
    accepted: boolean;
    timestamp: string;
    config_version: string; // hash of disclaimer text — change re-prompts users
}
