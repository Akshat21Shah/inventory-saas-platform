import { ImageOff } from "lucide-react";
import Link from "next/link";

/** Thumbnail, name and code, linking to the product's stock page. */
export function ProductCell({
  id,
  name,
  code,
  thumbnail,
  href = `/manage/stock/${id}`,
}: {
  id: string;
  name: string;
  code: string;
  thumbnail?: string | null;
  href?: string;
}) {
  return (
    <Link href={href} className="flex min-h-10 items-center gap-3 hover:underline">
      {thumbnail ? (
        // eslint-disable-next-line @next/next/no-img-element -- long-cached public CDN image
        <img src={thumbnail} alt="" className="size-10 shrink-0 rounded-md border object-cover" />
      ) : (
        <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-md">
          <ImageOff aria-hidden className="size-4" />
        </span>
      )}
      <span className="min-w-0">
        <span className="block font-medium">{name}</span>
        <span className="text-muted-foreground block text-xs">{code}</span>
      </span>
    </Link>
  );
}
