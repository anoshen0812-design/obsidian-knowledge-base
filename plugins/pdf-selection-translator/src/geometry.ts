export interface RectLike {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

export interface PopupPlacement {
  left: number;
  top: number;
  side: "left" | "right" | "above" | "below";
}

const clamp = (value: number, min: number, max: number): number =>
  Math.min(Math.max(value, min), Math.max(min, max));

/** Places the popup beside the selection and clamps it to the PDF pane. */
export function placePopup(
  anchor: RectLike,
  boundary: RectLike,
  popup: { width: number; height: number },
  gap = 12,
  margin = 10,
): PopupPlacement {
  const spaces = {
    right: boundary.right - margin - anchor.right - gap,
    left: anchor.left - gap - (boundary.left + margin),
    below: boundary.bottom - margin - anchor.bottom - gap,
    above: anchor.top - gap - (boundary.top + margin),
  };

  let side: PopupPlacement["side"];
  if (spaces.right >= popup.width) {
    side = "right";
  } else if (spaces.left >= popup.width) {
    side = "left";
  } else if (spaces.below >= popup.height) {
    side = "below";
  } else if (spaces.above >= popup.height) {
    side = "above";
  } else {
    side = (Object.entries(spaces) as [PopupPlacement["side"], number][]).reduce(
      (best, current) => (current[1] > best[1] ? current : best),
    )[0];
  }

  let left: number;
  let top: number;
  if (side === "right" || side === "left") {
    left = side === "right" ? anchor.right + gap : anchor.left - gap - popup.width;
    top = anchor.top + anchor.height / 2 - popup.height / 2;
  } else {
    left = anchor.left + anchor.width / 2 - popup.width / 2;
    top = side === "below" ? anchor.bottom + gap : anchor.top - gap - popup.height;
  }

  return {
    left: clamp(left, boundary.left + margin, boundary.right - margin - popup.width),
    top: clamp(top, boundary.top + margin, boundary.bottom - margin - popup.height),
    side,
  };
}
