"use client";

import React, { useEffect, useRef } from "react";

export interface NativeDialogProps {
  open: boolean;
  onClose?: () => void;
  closedby?: "any" | "closerequest" | "none";
  ariaLabelledBy?: string;
  ariaLabel?: string;
  className?: string;
  backdropClassName?: string;
  children: React.ReactNode;
}

function isOutsideRect(e: PointerEvent, el: HTMLDialogElement): boolean {
  const rect = el.getBoundingClientRect();
  return (
    e.clientX < rect.left ||
    e.clientX > rect.right ||
    e.clientY < rect.top ||
    e.clientY > rect.bottom
  );
}

export default function NativeDialog({
  open,
  onClose,
  closedby = "any",
  ariaLabelledBy,
  ariaLabel,
  className,
  backdropClassName,
  children,
}: NativeDialogProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (!dialog.open) {
      dialog.showModal();
    }

    // Safari fallback for `closedby="any"` light-dismiss:
    // only dismiss when BOTH pointerdown and pointerup occur outside the dialog box
    // so dragging a text selection outside the dialog never accidentally closes it.
    if (
      closedby === "any" &&
      typeof HTMLDialogElement !== "undefined" &&
      !("closedBy" in HTMLDialogElement.prototype)
    ) {
      let pressedOutside = false;

      const onPointerDown = (e: PointerEvent) => {
        pressedOutside = e.target === dialog && isOutsideRect(e, dialog);
      };

      const onPointerUp = (e: PointerEvent) => {
        if (pressedOutside && e.target === dialog && isOutsideRect(e, dialog)) {
          dialog.close();
        }
        pressedOutside = false;
      };

      const onPointerCancel = () => {
        pressedOutside = false;
      };

      dialog.addEventListener("pointerdown", onPointerDown);
      dialog.addEventListener("pointerup", onPointerUp);
      dialog.addEventListener("pointercancel", onPointerCancel);

      return () => {
        dialog.removeEventListener("pointerdown", onPointerDown);
        dialog.removeEventListener("pointerup", onPointerUp);
        dialog.removeEventListener("pointercancel", onPointerCancel);
      };
    }
  }, [open, closedby]);

  if (!open) return null;

  const classes = [
    "m-auto max-w-[calc(100vw-1.5rem)] max-h-[calc(100dvh-1.5rem)] w-full bg-transparent p-0 border-0 text-inherit overflow-visible backdrop:bg-black/80 backdrop:backdrop-blur-sm",
    backdropClassName,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <dialog
      ref={dialogRef}
      {...({ closedby } as Record<string, unknown>)}
      aria-labelledby={ariaLabelledBy}
      aria-label={ariaLabel}
      className={classes}
      onClose={() => onClose?.()}
      onCancel={
        closedby === "none"
          ? (e) => {
              e.preventDefault();
            }
          : undefined
      }
    >
      {children}
    </dialog>
  );
}
