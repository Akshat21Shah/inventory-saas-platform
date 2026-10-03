"use client";

import { Camera } from "lucide-react";
import { useTranslations } from "@/lib/i18n/translations";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "qr_code"];

interface Detector {
  detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]>;
}

/** The browser's own BarcodeDetector where it exists (Chrome on Android); otherwise the zxing
 * library, loaded only now and served from our own server (ADR-041 item 14). */
async function createDetector(): Promise<Detector> {
  const native = (globalThis as { BarcodeDetector?: new (o: object) => Detector }).BarcodeDetector;
  if (native) return new native({ formats: FORMATS });
  const { BarcodeDetector, setZXingModuleOverrides } = await import("barcode-detector/ponyfill");
  setZXingModuleOverrides({
    locateFile: (path: string, prefix: string) =>
      path.endsWith(".wasm") ? "/vendor/zxing_reader.wasm" : prefix + path,
  });
  return new BarcodeDetector({ formats: FORMATS as never });
}

/** True where a camera can be offered at all: browsers allow it only on https or localhost. */
export function cameraPossible(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    Boolean(navigator.mediaDevices?.getUserMedia)
  );
}

function Viewfinder({
  onCode,
  onProblem,
}: {
  onCode: (code: string) => void;
  onProblem: (key: string) => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  // The latest callbacks, without restarting the camera when the parent re-renders.
  const handlers = useRef({ onCode, onProblem });
  useEffect(() => {
    handlers.current = { onCode, onProblem };
  });
  useEffect(() => {
    const found = (code: string) => handlers.current.onCode(code);
    const problem = (key: string) => handlers.current.onProblem(key);
    let stream: MediaStream | undefined;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
          audio: false,
        });
      } catch {
        problem("cameraDenied");
        return;
      }
      if (stopped || !video.current) return;
      video.current.srcObject = stream;
      await video.current.play().catch(() => undefined);
      let detector: Detector;
      try {
        detector = await createDetector();
      } catch {
        problem("cameraUnsupported");
        return;
      }
      const tick = async () => {
        if (stopped || !video.current) return;
        try {
          const [hit] = await detector.detect(video.current);
          if (hit?.rawValue) {
            found(hit.rawValue.trim());
            return;
          }
        } catch {
          // A frame that can't be read yet (camera warming up): try the next one.
        }
        timer = setTimeout(() => void tick(), 200);
      };
      void tick();
    }
    void start();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);
  return (
    <video
      ref={video}
      muted
      playsInline
      className="aspect-[4/3] w-full rounded-lg bg-black object-cover"
    />
  );
}

export function CameraButton({ onCode }: { onCode: (code: string) => void }) {
  const t = useTranslations("stock.scan");
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const possible = cameraPossible();
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setProblem(null);
      }}
    >
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="size-12 shrink-0"
        aria-label={t("camera")}
        onClick={() => {
          setProblem(possible ? null : "cameraNeedsHttps");
          setOpen(true);
        }}
      >
        <Camera aria-hidden />
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("cameraTitle")}</DialogTitle>
          <DialogDescription>{problem ? t(problem) : t("cameraHelp")}</DialogDescription>
        </DialogHeader>
        {open && possible && !problem ? (
          <Viewfinder
            onProblem={setProblem}
            onCode={(code) => {
              setOpen(false);
              onCode(code);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
