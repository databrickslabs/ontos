/** Status of an access grant request (mirrors the backend `AccessGrantRequestStatus`). */
export enum AccessGrantRequestStatus {
  PENDING = 'pending',
  APPROVED = 'approved',
  DENIED = 'denied',
  EXPIRED = 'expired',
  CANCELLED = 'cancelled',
}
