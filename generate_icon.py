"""
Generate a purple-themed .ico file for Windows App Reinstaller.
Concept: circular refresh arrow around a box/package shape.
"""

import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def draw_icon(size):
    """Draw the icon at a given size and return the Image."""
    scale = size / 256.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size / 2, size / 2
    margin = int(8 * scale)

    # --- Background: rounded purple circle with gradient feel ---
    # Draw a radial gradient background circle
    for r in range(int(cx - margin), 0, -1):
        # Gradient from lighter purple (center) to darker purple (edge)
        t = r / (cx - margin)  # 1.0 at edge, 0.0 at center
        # Dark purple at edge: (88, 28, 135), lighter at center: (168, 85, 247)
        red = int(168 - (168 - 88) * t)
        green = int(85 - (85 - 28) * t)
        blue = int(247 - (247 - 135) * t)
        bbox = [cx - r, cy - r, cx + r, cy + r]
        draw.ellipse(bbox, fill=(red, green, blue, 255))

    # --- Draw the box/package in the center ---
    box_size = int(70 * scale)
    box_x = cx - box_size // 2
    box_y = cy - box_size // 2 + int(10 * scale)

    # Box body (lighter purple / lavender)
    body_color = (232, 210, 255, 255)
    draw.rectangle(
        [box_x, box_y + int(18 * scale), box_x + box_size, box_y + box_size],
        fill=body_color,
        outline=(60, 20, 100, 255),
        width=max(1, int(2.5 * scale)),
    )

    # Box lid / flap (top part, slightly different shade)
    lid_color = (210, 180, 245, 255)
    lid_points = [
        (box_x - int(6 * scale), box_y + int(18 * scale)),
        (cx, box_y - int(2 * scale)),
        (box_x + box_size + int(6 * scale), box_y + int(18 * scale)),
    ]
    draw.polygon(lid_points, fill=lid_color, outline=(60, 20, 100, 255))

    # Center line on box (tape/seam)
    tape_x = int(cx)
    draw.line(
        [(tape_x, box_y + int(18 * scale)), (tape_x, box_y + box_size)],
        fill=(140, 80, 200, 200),
        width=max(1, int(2.5 * scale)),
    )
    # Top tape line
    draw.line(
        [(tape_x, box_y - int(1 * scale)), (tape_x, box_y + int(18 * scale))],
        fill=(140, 80, 200, 200),
        width=max(1, int(2.5 * scale)),
    )

    # --- Draw circular refresh arrow around the box ---
    arrow_radius = int(100 * scale)
    arrow_width = max(3, int(14 * scale))
    arrow_color = (255, 255, 255, 240)

    # Draw arc - going from about 200 degrees to 510 degrees (310 degree sweep)
    # We'll draw it as a thick arc using multiple thin arcs
    arc_start_deg = 160
    arc_end_deg = 440  # 280 degree sweep

    arc_bbox = [
        cx - arrow_radius,
        cy - arrow_radius,
        cx + arrow_radius,
        cy + arrow_radius,
    ]
    draw.arc(arc_bbox, arc_start_deg, arc_end_deg, fill=arrow_color, width=arrow_width)

    # --- Arrowhead at the end of the arc ---
    # The arc ends at arc_end_deg (440 = 80 degrees in standard)
    end_angle_rad = math.radians(arc_end_deg)
    arrow_tip_x = cx + arrow_radius * math.cos(end_angle_rad)
    arrow_tip_y = cy + arrow_radius * math.sin(end_angle_rad)

    # Arrowhead size
    ah_size = int(22 * scale)

    # Calculate arrowhead triangle
    # The arrow is moving along the tangent of the circle at the endpoint
    tangent_angle = end_angle_rad + math.pi / 2  # perpendicular to radius = tangent

    # Two base points of the arrowhead
    perp_angle = end_angle_rad  # perpendicular to tangent = along radius
    base_along = ah_size * 0.9

    p1_x = arrow_tip_x - base_along * math.cos(tangent_angle) + (ah_size * 0.5) * math.cos(perp_angle)
    p1_y = arrow_tip_y - base_along * math.sin(tangent_angle) + (ah_size * 0.5) * math.sin(perp_angle)
    p2_x = arrow_tip_x - base_along * math.cos(tangent_angle) - (ah_size * 0.5) * math.cos(perp_angle)
    p2_y = arrow_tip_y - base_along * math.sin(tangent_angle) - (ah_size * 0.5) * math.sin(perp_angle)

    arrowhead = [
        (arrow_tip_x, arrow_tip_y),
        (p1_x, p1_y),
        (p2_x, p2_y),
    ]
    draw.polygon(arrowhead, fill=arrow_color)

    # --- Second arrowhead at the start of the arc (opposite direction) ---
    start_angle_rad = math.radians(arc_start_deg)
    arrow_tip2_x = cx + arrow_radius * math.cos(start_angle_rad)
    arrow_tip2_y = cy + arrow_radius * math.sin(start_angle_rad)

    # Tangent at start goes the other way
    tangent_angle2 = start_angle_rad - math.pi / 2
    perp_angle2 = start_angle_rad

    p3_x = arrow_tip2_x - base_along * math.cos(tangent_angle2) + (ah_size * 0.5) * math.cos(perp_angle2)
    p3_y = arrow_tip2_y - base_along * math.sin(tangent_angle2) + (ah_size * 0.5) * math.sin(perp_angle2)
    p4_x = arrow_tip2_x - base_along * math.cos(tangent_angle2) - (ah_size * 0.5) * math.cos(perp_angle2)
    p4_y = arrow_tip2_y - base_along * math.sin(tangent_angle2) - (ah_size * 0.5) * math.sin(perp_angle2)

    arrowhead2 = [
        (arrow_tip2_x, arrow_tip2_y),
        (p3_x, p3_y),
        (p4_x, p4_y),
    ]
    draw.polygon(arrowhead2, fill=arrow_color)

    # --- Add subtle shadow/glow ---
    # For larger sizes, add a subtle drop shadow effect
    if size >= 48:
        shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_offset = max(1, int(3 * scale))
        # Darker circle behind main circle
        shadow_draw.ellipse(
            [margin + shadow_offset, margin + shadow_offset,
             size - margin + shadow_offset, size - margin + shadow_offset],
            fill=(30, 0, 50, 60),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(1, int(4 * scale))))
        # Composite shadow behind main image
        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result = Image.alpha_composite(result, shadow)
        result = Image.alpha_composite(result, img)
        return result

    return img


def main():
    sizes = [256, 48, 32, 16]
    images = []

    for s in sizes:
        icon = draw_icon(s)
        images.append(icon)
        print(f"  Generated {s}x{s} icon")

    # Save as .ico with all sizes
    output_path = r"C:\Users\jhild\apply\reinstaller\app.ico"

    # The first image is the "main" one; append the rest
    images[0].save(
        output_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"\nIcon saved to: {output_path}")


if __name__ == "__main__":
    main()
