import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  onClose: () => void;
  className?: string;
  label: string;
  children: ReactNode;
}

/** Модальное окно на нативном <dialog>: фокус внутри, Esc закрывает, фон затемнён. */
export function Modal({ onClose, className, label, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    document.documentElement.classList.add("no-scroll");
    const onCancel = (e: Event) => {
      e.preventDefault();
      closeRef.current();
    };
    dialog.addEventListener("cancel", onCancel);
    return () => {
      dialog.removeEventListener("cancel", onCancel);
      document.documentElement.classList.remove("no-scroll");
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className={`modal ${className ?? ""}`}
      aria-label={label}
      onMouseDown={(e) => {
        // Клик по затемнению (вне содержимого) закрывает окно.
        if (e.target === ref.current) onClose();
      }}
    >
      {children}
    </dialog>
  );
}
