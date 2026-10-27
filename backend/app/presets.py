"""Product presets. Provider request sizes are deliberately independent of output
sizes."""

PRESETS = {
    "instagram_post": (1080, 1080, "Instagram Post"),
    "instagram_story": (1080, 1920, "Instagram Story"),
    "instagram_reel_cover": (1080, 1920, "Instagram Reel Cover"),
    "facebook_post": (1200, 630, "Facebook Post"),
    "facebook_cover": (820, 312, "Facebook Cover"),
    "facebook_story": (1080, 1920, "Facebook Story"),
    "twitter_post": (1200, 675, "Twitter/X Post"),
    "twitter_header": (1500, 500, "Twitter/X Header"),
    "linkedin_post": (1200, 627, "LinkedIn Post"),
    "linkedin_banner": (1584, 396, "LinkedIn Banner"),
    "tiktok_video_cover": (1080, 1920, "TikTok Video Cover"),
    "youtube_thumbnail": (1280, 720, "YouTube Thumbnail"),
    "youtube_banner": (2560, 1440, "YouTube Banner"),
}


def provider_size(width: int, height: int) -> str:
    if width == height:
        return "1024x1024"
    return "1536x1024" if width > height else "1024x1536"


def composition_guidance(width: int, height: int) -> str:
    """Tell the model which part of its canvas survives the center crop to the
    preset, so subjects and text are not cut off on wide or tall presets."""
    canvas_width, canvas_height = map(int, provider_size(width, height).split("x"))
    target, canvas = width / height, canvas_width / canvas_height
    shape = f"The final image is {width}x{height} pixels"
    if abs(target - canvas) < 0.01:
        return f"{shape}; the whole image is used."
    if target > canvas:
        kept, axis, edges = canvas / target, "height", "top and bottom"
    else:
        kept, axis, edges = target / canvas, "width", "left and right"
    return (
        f"{shape}, so the {edges} of the image will be cropped away. Keep the main "
        f"subject and any text entirely within the middle {int(kept * 100)}% of the "
        f"image {axis}."
    )
