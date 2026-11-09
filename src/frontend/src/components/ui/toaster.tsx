import { flushSync } from "react-dom"
import { removeToast, useToast } from "@/hooks/use-toast"
import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "@/components/ui/toast"

/**
 * A Radix toast is a dismissable layer without an `onDismiss`: while it is open
 * it is the topmost layer, so it receives Escape instead of any dialog, sheet
 * or popover beneath it, closes itself and leaves the event unhandled. The
 * first Escape then appears to do nothing.
 *
 * When focus is outside the toast, unmount it right away (so it stops being
 * the topmost layer) and replay the Escape so the layer beneath handles it as
 * if the toast had never been there. With nothing beneath, the replay is a
 * no-op and the toast is simply closed. Focus inside the toast keeps Radix's
 * own behaviour (close that toast only).
 */
const REPLAYED = "__toastReplayedEscape"

function escapeThroughToast(toastId: string, event: KeyboardEvent) {
  const target = event.target as Element | null
  if ((event as unknown as Record<string, unknown>)[REPLAYED]) return
  if (target?.closest?.("[data-toast-root]")) return
  event.preventDefault() // skip Radix's own close, handled here
  flushSync(() => removeToast(toastId))
  const replay = new KeyboardEvent("keydown", {
    key: "Escape",
    code: "Escape",
    bubbles: true,
    cancelable: true,
  })
  ;(replay as unknown as Record<string, unknown>)[REPLAYED] = true
  // The layers beneath re-render once the toast layer is gone; replay after.
  setTimeout(() => (target?.isConnected ? target : document).dispatchEvent(replay), 0)
}

export function Toaster() {
  const { toasts } = useToast()

  return (
    <ToastProvider>
      {toasts.map(function ({ id, title, description, action, ...props }) {
        return (
          <Toast
            key={id}
            {...props}
            onEscapeKeyDown={(e) => escapeThroughToast(id, e)}
          >
            <div className="grid gap-1">
              {title && <ToastTitle>{title}</ToastTitle>}
              {description && (
                <ToastDescription>{description}</ToastDescription>
              )}
            </div>
            {action}
            <ToastClose />
          </Toast>
        )
      })}
      <ToastViewport />
    </ToastProvider>
  )
}
