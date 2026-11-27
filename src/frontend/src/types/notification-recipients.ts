/** A Notification Recipient (#1450): a named NOTIFY target that compliance policies reference. */
export interface NotificationRecipient {
  id: string;
  name: string;
  description: string | null;
  /** Emails, groups and app role ids, as the PrincipalPicker and the role picker emit them */
  targets: string[];
  /** App roles whose members may use this recipient in their policies (admins always may) */
  allowed_role_ids: string[];
  is_active: boolean;
  updated_by?: string | null;
  updated_at?: string | null;
}

/** A recipient the current user may name in a NOTIFY action. */
export interface AvailableNotificationRecipient {
  id: string;
  name: string;
  description: string | null;
}
