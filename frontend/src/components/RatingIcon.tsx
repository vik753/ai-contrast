export type Rating = "green" | "yellow" | "red";

/**
 * Decorative rating icon. The shape differs per rating (check, exclamation,
 * cross), so the rating never depends on color alone. Always render it next
 * to a text label; the icon itself is hidden from assistive technology.
 */
export function RatingIcon({ rating }: { rating: Rating }) {
  return (
    <svg
      className={`rating-icon rating-icon--${rating}`}
      viewBox="0 0 20 20"
      width="20"
      height="20"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="10" cy="10" r="9" className="rating-icon__badge" />
      {rating === "green" && <path d="M5.5 10.5l3 3 6-6.5" className="rating-icon__mark" />}
      {rating === "yellow" && (
        <>
          <path d="M10 5v6.5" className="rating-icon__mark" />
          <path d="M10 14.5v.5" className="rating-icon__mark" />
        </>
      )}
      {rating === "red" && <path d="M6.5 6.5l7 7M13.5 6.5l-7 7" className="rating-icon__mark" />}
    </svg>
  );
}
